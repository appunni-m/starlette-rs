//! Rust-owned WSGI-to-ASGI protocol bridge.
//!
//! Request buffering, WSGI environment construction, response conversion, and
//! event ordering live here. AnyIO is used only for its existing worker-thread
//! and event-loop handoff, which is required to invoke the user WSGI callable
//! without blocking the ASGI loop.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyRuntimeError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PyModule, PyString, PyTraceback, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

const DEPRECATION_MESSAGE: &str = "starlette.middleware.wsgi is deprecated and will be removed in a future release. Please refer to https://github.com/abersheeran/a2wsgi as a replacement.";

type SharedExceptionInfo = Arc<Mutex<Option<Py<PyAny>>>>;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyWsgiWorker>()?;
    module.add_class::<PyWsgiStartResponse>()?;
    module.add_function(wrap_pyfunction!(build_environ, module)?)?;
    module.add_function(wrap_pyfunction!(wsgi_middleware_call, module)?)?;
    module.add_function(wrap_pyfunction!(warn_wsgi_deprecated, module)?)?;
    Ok(())
}

#[pyfunction(name = "_warn_wsgi_deprecated")]
fn warn_wsgi_deprecated(py: Python<'_>, warning_category: Py<PyAny>) -> PyResult<()> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("stacklevel", 2)?;
    py.import("warnings")?
        .getattr("warn")?
        .call((DEPRECATION_MESSAGE, warning_category), Some(&kwargs))?;
    Ok(())
}

#[pyfunction(name = "_build_wsgi_environ")]
fn build_environ(py: Python<'_>, scope: Py<PyAny>, body: Py<PyAny>) -> PyResult<Py<PyAny>> {
    build_environ_inner(py, scope.bind(py), body.bind(py)).map(|value| value.into_any().unbind())
}

fn build_environ_inner<'py>(
    py: Python<'py>,
    scope: &Bound<'py, PyAny>,
    body: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let root_path = scope.call_method1("get", ("root_path", ""))?;
    let script_name = utf8_to_latin1(&root_path)?;
    let path = scope.get_item("path")?;
    let mut path_info = utf8_to_latin1(&path)?;
    if path_info
        .call_method1("startswith", (&script_name,))?
        .is_truthy()?
    {
        let script_length = script_name.len()?;
        let slice = py.import("builtins")?.getattr("slice")?.call1((
            script_length,
            py.None(),
            py.None(),
        ))?;
        path_info = path_info.get_item(slice)?;
    }

    let query_string = scope
        .get_item("query_string")?
        .call_method1("decode", ("ascii",))?;
    let http_version = scope.get_item("http_version")?;
    let protocol = PyString::new(py, "HTTP/").call_method1("__add__", (http_version,))?;

    let environ = PyDict::new(py);
    environ.set_item("REQUEST_METHOD", scope.get_item("method")?)?;
    environ.set_item("SCRIPT_NAME", script_name)?;
    environ.set_item("PATH_INFO", path_info)?;
    environ.set_item("QUERY_STRING", query_string)?;
    environ.set_item("SERVER_PROTOCOL", protocol)?;
    environ.set_item("wsgi.version", PyTuple::new(py, [1, 0])?)?;
    environ.set_item(
        "wsgi.url_scheme",
        scope.call_method1("get", ("scheme", "http"))?,
    )?;
    let input_stream = py.import("io")?.getattr("BytesIO")?.call1((body,))?;
    environ.set_item("wsgi.input", input_stream)?;
    environ.set_item("wsgi.errors", py.import("sys")?.getattr("stdout")?)?;
    environ.set_item("wsgi.multithread", true)?;
    environ.set_item("wsgi.multiprocess", true)?;
    environ.set_item("wsgi.run_once", false)?;

    let server = scope.call_method1("get", ("server",))?;
    let server = if server.is_truthy()? {
        server
    } else {
        PyTuple::new(
            py,
            [
                PyString::new(py, "localhost").into_any(),
                PyInt::new(py, 80).into_any(),
            ],
        )?
        .into_any()
    };
    environ.set_item("SERVER_NAME", server.get_item(0)?)?;
    environ.set_item("SERVER_PORT", server.get_item(1)?)?;

    let client = scope.call_method1("get", ("client",))?;
    if client.is_truthy()? {
        environ.set_item("REMOTE_ADDR", client.get_item(0)?)?;
    }

    let empty_headers = PyList::empty(py);
    let headers = scope.call_method1("get", ("headers", &empty_headers))?;
    for header in headers.try_iter()? {
        let pair = py.import("builtins")?.getattr("tuple")?.call1((header?,))?;
        if pair.len()? != 2 {
            return Err(PyValueError::new_err(format!(
                "header pair must contain exactly 2 items (got {})",
                pair.len()?
            )));
        }
        let name = pair.get_item(0)?.call_method1("decode", ("latin1",))?;
        let value = pair.get_item(1)?.call_method1("decode", ("latin1",))?;
        let corrected_name = if name
            .rich_compare("content-length", CompareOp::Eq)?
            .is_truthy()?
        {
            PyString::new(py, "CONTENT_LENGTH").into_any()
        } else if name
            .rich_compare("content-type", CompareOp::Eq)?
            .is_truthy()?
        {
            PyString::new(py, "CONTENT_TYPE").into_any()
        } else {
            PyString::new(py, "HTTP_")
                .call_method1("__add__", (&name,))?
                .call_method0("upper")?
                .call_method1("replace", ("-", "_"))?
        };
        let value = match environ.get_item(&corrected_name)? {
            Some(previous) => previous
                .call_method1("__add__", (",",))?
                .call_method1("__add__", (&value,))?,
            None => value,
        };
        environ.set_item(corrected_name, value)?;
    }

    Ok(environ)
}

fn utf8_to_latin1<'py>(value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    value
        .call_method1("encode", ("utf8",))?
        .call_method1("decode", ("latin1",))
}

#[pyfunction(name = "_wsgi_middleware_call")]
fn wsgi_middleware_call(
    py: Python<'_>,
    app: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        WsgiMiddlewareCall {
            app,
            scope,
            receive,
            send,
            body: PyBytes::new(py, b"").into_any().unbind(),
            exception_info: Arc::new(Mutex::new(None)),
            pending: None,
        },
    )
}

enum PendingOperation {
    Receive,
    Worker,
}

struct WsgiMiddlewareCall {
    app: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    body: Py<PyAny>,
    exception_info: SharedExceptionInfo,
    pending: Option<PendingOperation>,
}

impl AwaitableStateMachine for WsgiMiddlewareCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(PendingOperation::Receive) => self.on_receive(py, value),
                Some(PendingOperation::Worker) => self.on_worker_complete(py),
                None => Err(PyRuntimeError::new_err(
                    "WSGI middleware received an unexpected continuation result",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(PendingOperation::Receive) => Err(error),
                Some(PendingOperation::Worker) => {
                    error.value(py).setattr("__suppress_context__", true)?;
                    Err(error)
                }
                None => Err(PyRuntimeError::new_err(
                    "WSGI middleware has no pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "WSGI middleware call has already started",
            )),
        }
    }
}

impl WsgiMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope_type = self.scope.bind(py).get_item("type")?;
        if !scope_type
            .rich_compare("http", CompareOp::Eq)?
            .is_truthy()?
        {
            return Err(PyAssertionError::new_err(()));
        }
        self.receive_next(py)
    }

    fn receive_next(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let awaitable = self.receive.bind(py).call0()?;
        self.pending = Some(PendingOperation::Receive);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn on_receive(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message = message.bind(py);
        let default_body = PyBytes::new(py, b"");
        let message_body = message.call_method1("get", ("body", default_body))?;
        self.body = self
            .body
            .bind(py)
            .call_method1("__add__", (&message_body,))?
            .unbind();
        let more_body = message
            .call_method1("get", ("more_body", false))?
            .is_truthy()?;
        if more_body {
            return self.receive_next(py);
        }
        self.run_worker(py)
    }

    fn run_worker(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let environ = build_environ_inner(py, self.scope.bind(py), self.body.bind(py))?;
        let response_started = Arc::new(AtomicBool::new(false));
        let worker = Py::new(
            py,
            PyWsgiWorker {
                app: self.app.clone_ref(py),
                send: self.send.clone_ref(py),
                response_started,
                exception_info: Arc::clone(&self.exception_info),
            },
        )?;
        let awaitable = py
            .import("anyio.to_thread")?
            .getattr("run_sync")?
            .call1((worker, environ))?;
        self.pending = Some(PendingOperation::Worker);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn on_worker_complete(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let exception_info = self
            .exception_info
            .lock()
            .map_err(|_| PyRuntimeError::new_err("WSGI exception state was poisoned"))?
            .as_ref()
            .map(|value| value.clone_ref(py));
        if let Some(exception_info) = exception_info {
            return Err(restore_wsgi_exception(py, exception_info.bind(py))?);
        }
        Ok(MachineAction::Complete(py.None()))
    }
}

fn restore_wsgi_exception(py: Python<'_>, info: &Bound<'_, PyAny>) -> PyResult<PyErr> {
    let exception = info.get_item(1)?;
    let traceback = info.get_item(2)?;
    let error = PyErr::from_value(exception);
    if traceback.is_none() {
        error.set_traceback(py, None);
    } else {
        error.set_traceback(py, Some(traceback.cast::<PyTraceback>()?.clone()));
    }
    Ok(error)
}

/// Runs one WSGI application call inside AnyIO's worker thread pool.
#[pyclass(name = "_WsgiWorker")]
struct PyWsgiWorker {
    app: Py<PyAny>,
    send: Py<PyAny>,
    response_started: Arc<AtomicBool>,
    exception_info: SharedExceptionInfo,
}

#[pymethods]
impl PyWsgiWorker {
    fn __call__(&self, py: Python<'_>, environ: Py<PyAny>) -> PyResult<()> {
        let start_response = Py::new(
            py,
            PyWsgiStartResponse {
                send: self.send.clone_ref(py),
                response_started: Arc::clone(&self.response_started),
                exception_info: Arc::clone(&self.exception_info),
            },
        )?;
        let iterable = self
            .app
            .bind(py)
            .call1((environ, start_response.clone_ref(py)))?;
        for chunk in iterable.try_iter()? {
            let message = PyDict::new(py);
            message.set_item("type", "http.response.body")?;
            message.set_item("body", chunk?)?;
            message.set_item("more_body", true)?;
            send_from_worker(py, self.send.bind(py), &message)?;
        }
        let final_message = PyDict::new(py);
        final_message.set_item("type", "http.response.body")?;
        final_message.set_item("body", PyBytes::new(py, b""))?;
        send_from_worker(py, self.send.bind(py), &final_message)
    }
}

/// Captures WSGI's response-start decision and sends its ASGI event on the loop.
#[pyclass(name = "_WsgiStartResponse")]
struct PyWsgiStartResponse {
    send: Py<PyAny>,
    response_started: Arc<AtomicBool>,
    exception_info: SharedExceptionInfo,
}

#[pymethods]
impl PyWsgiStartResponse {
    #[pyo3(signature = (status, response_headers, exc_info=None))]
    fn __call__(
        &self,
        py: Python<'_>,
        status: Py<PyAny>,
        response_headers: Py<PyAny>,
        exc_info: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        *self
            .exception_info
            .lock()
            .map_err(|_| PyRuntimeError::new_err("WSGI exception state was poisoned"))? = exc_info;
        if self.response_started.swap(true, Ordering::SeqCst) {
            return Ok(());
        }

        let status_parts = status.bind(py).call_method1("split", (" ", 1))?;
        let status_part_count = status_parts.len()?;
        if status_part_count != 2 {
            return Err(PyValueError::new_err(format!(
                "not enough values to unpack (expected 2, got {status_part_count})"
            )));
        }
        let status_code = py
            .import("builtins")?
            .getattr("int")?
            .call1((status_parts.get_item(0)?,))?;
        let headers = PyList::empty(py);
        for header in response_headers.bind(py).try_iter()? {
            let pair = py.import("builtins")?.getattr("tuple")?.call1((header?,))?;
            if pair.len()? != 2 {
                return Err(PyValueError::new_err(
                    "too many values to unpack (expected 2)",
                ));
            }
            let name = pair
                .get_item(0)?
                .call_method0("strip")?
                .call_method1("encode", ("ascii",))?
                .call_method0("lower")?;
            let value = pair
                .get_item(1)?
                .call_method0("strip")?
                .call_method1("encode", ("ascii",))?;
            headers.append(PyTuple::new(py, [name, value])?)?;
        }
        let message = PyDict::new(py);
        message.set_item("type", "http.response.start")?;
        message.set_item("status", status_code)?;
        message.set_item("headers", headers)?;
        send_from_worker(py, self.send.bind(py), &message)
    }
}

fn send_from_worker(
    py: Python<'_>,
    send: &Bound<'_, PyAny>,
    message: &Bound<'_, PyDict>,
) -> PyResult<()> {
    py.import("anyio.from_thread")?
        .getattr("run")?
        .call1((send, message))?;
    Ok(())
}
