//! Rust-owned WSGI-to-ASGI protocol bridge.
//!
//! Request buffering, WSGI environment construction, response conversion, and
//! event ordering live here. AnyIO is used only for its existing worker-thread
//! and event-loop handoff, which is required to invoke the user WSGI callable
//! without blocking the ASGI loop.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use pyo3::basic::CompareOp;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAssertionError, PyBaseException, PyRuntimeError, PyStopAsyncIteration, PyTypeError,
    PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{
    PyBytes, PyDict, PyInt, PyIterator, PyList, PyModule, PyString, PyTraceback, PyTuple, PyType,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

const DEPRECATION_MESSAGE: &str = "starlette.middleware.wsgi is deprecated and will be removed in a future release. Please refer to https://github.com/abersheeran/a2wsgi as a replacement.";

// A shared Python container exposes responder references and traceback cycles
// to Python GC. Rust selects every read/write; no Python semantic glue is used.
type SharedExceptionInfo = Py<PyList>;

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
    let protocol_version = py
        .import("builtins")?
        .getattr("format")?
        .call1((http_version, ""))?;
    let protocol = PyString::new(py, "HTTP/").call_method1("__add__", (protocol_version,))?;

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
        let mut pair = header?.try_iter()?;
        let name = next_wsgi_header_part(&mut pair, 0)?;
        let value = next_wsgi_header_part(&mut pair, 1)?;
        if pair.next().transpose()?.is_some() {
            return Err(PyValueError::new_err(
                "too many values to unpack (expected 2)",
            ));
        }
        let name = name.call_method1("decode", ("latin1",))?;
        let value = value.call_method1("decode", ("latin1",))?;
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

fn next_wsgi_header_part<'py>(
    pair: &mut Bound<'py, PyIterator>,
    consumed: usize,
) -> PyResult<Bound<'py, PyAny>> {
    pair.next().transpose()?.ok_or_else(|| {
        PyValueError::new_err(format!(
            "not enough values to unpack (expected 2, got {consumed})"
        ))
    })
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
    let exception_info =
        PyList::new(py, [py.None(), app.clone_ref(py), scope.clone_ref(py)])?.unbind();
    into_sendable_python_awaitable(
        py,
        WsgiMiddlewareCall {
            app,
            scope,
            receive,
            send,
            body: PyBytes::new(py, b"").into_any().unbind(),
            exception_info,
            environ: None,
            stream_send: None,
            stream_receive: None,
            task_group: None,
            pending: None,
        },
    )
}

enum PendingOperation {
    Receive,
    TaskGroupEnter,
    StreamEnter,
    Worker,
    StreamExit { body_error: Option<StoredException> },
    TaskGroupExit { body_error: Option<StoredException> },
}

/// A Python exception retained across an await boundary.
///
/// Keeping a `PyErr` in a Rust state machine hides its references from Python's
/// cyclic GC. These explicit handles are traversed by the owning awaitable. The
/// value is the original exception instance, so restoring a `PyErr` preserves
/// its identity and its live `__cause__`/`__context__` chain; the traceback is
/// retained separately because it is not stored on the exception instance.
struct StoredException {
    exception_type: Py<PyType>,
    value: Py<PyBaseException>,
    traceback: Option<Py<PyTraceback>>,
}

impl StoredException {
    fn capture(py: Python<'_>, error: PyErr) -> Self {
        Self {
            exception_type: error.get_type(py).unbind(),
            value: error.value(py).clone().unbind(),
            traceback: error.traceback(py).map(Bound::unbind),
        }
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.exception_type)?;
        visit.call(&self.value)?;
        visit.call(&self.traceback)
    }

    fn to_pyerr(&self, py: Python<'_>) -> PyErr {
        let error = PyErr::from_value(self.value.bind(py).clone().into_any());
        error.set_traceback(py, self.traceback.as_ref().map(|tb| tb.bind(py).clone()));
        error
    }
}

struct WsgiMiddlewareCall {
    app: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    body: Py<PyAny>,
    exception_info: SharedExceptionInfo,
    environ: Option<Py<PyAny>>,
    stream_send: Option<Py<PyAny>>,
    stream_receive: Option<Py<PyAny>>,
    task_group: Option<Py<PyAny>>,
    pending: Option<PendingOperation>,
}

impl AwaitableStateMachine for WsgiMiddlewareCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.body)?;
        visit.call(&self.exception_info)?;
        visit.call(&self.environ)?;
        visit.call(&self.stream_send)?;
        visit.call(&self.stream_receive)?;
        visit.call(&self.task_group)?;
        if let Some(pending) = &self.pending {
            pending.traverse(visit)?;
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(PendingOperation::Receive) => self.on_receive(py, value),
                Some(PendingOperation::TaskGroupEnter) => match self.start_sender(py) {
                    Ok(action) => Ok(action),
                    Err(error) => {
                        self.leave_task_group(py, Some(StoredException::capture(py, error)))
                    }
                },
                Some(PendingOperation::StreamEnter) => match self.run_worker(py) {
                    Ok(action) => Ok(action),
                    Err(error) => self.leave_stream(py, Some(StoredException::capture(py, error))),
                },
                Some(PendingOperation::Worker) => self.leave_stream(py, None),
                Some(PendingOperation::StreamExit { body_error }) => {
                    self.leave_task_group(py, body_error)
                }
                Some(PendingOperation::TaskGroupExit { body_error }) => {
                    if !value.bind(py).is_truthy()? {
                        if let Some(error) = body_error {
                            return Err(error.to_pyerr(py));
                        }
                    }
                    self.on_worker_complete(py)
                }
                None => Err(PyRuntimeError::new_err(
                    "WSGI middleware received an unexpected continuation result",
                )),
            },
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                self.resume_error(py, error)
            }
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
        // Starlette's unbounded stream lets the WSGI worker continue while the
        // dedicated sender task awaits external ASGI backpressure.
        let streams = py
            .import("anyio")?
            .getattr("create_memory_object_stream")?
            .call1((f64::INFINITY,))?;
        self.stream_send = Some(streams.get_item(0)?.unbind());
        self.stream_receive = Some(streams.get_item(1)?.unbind());
        // A retained start_response callback keeps the same responder-owned
        // app, scope, and streams alive as Starlette's bound method does.
        self.exception_info
            .bind(py)
            .append(self.stream_send_ref(py)?)?;
        self.exception_info
            .bind(py)
            .append(self.stream_receive_ref(py)?)?;
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
        self.environ = Some(
            build_environ_inner(py, self.scope.bind(py), self.body.bind(py))?
                .into_any()
                .unbind(),
        );
        let task_group = py.import("anyio")?.getattr("create_task_group")?.call0()?;
        let awaitable = task_group.call_method0("__aenter__")?;
        self.task_group = Some(task_group.unbind());
        self.pending = Some(PendingOperation::TaskGroupEnter);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn start_sender(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let sender = Py::new(
            py,
            PyWsgiSender {
                stream: self.stream_receive_ref(py)?.clone().unbind(),
                send: self.send.clone_ref(py),
            },
        )?;
        self.task_group_ref(py)?
            .call_method1("start_soon", (sender,))?;
        let awaitable = self.stream_send_ref(py)?.call_method0("__aenter__")?;
        self.pending = Some(PendingOperation::StreamEnter);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn run_worker(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let environ = self
            .environ
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WSGI environ is unavailable"))?
            .bind(py);
        let response_started = Arc::new(AtomicBool::new(false));
        let worker = Py::new(
            py,
            PyWsgiWorker {
                app: self.app.clone_ref(py),
                send: self.stream_send_ref(py)?.getattr("send")?.unbind(),
                response_started,
                exception_info: self.exception_info.clone_ref(py),
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
        let exception_info = self.exception_info.bind(py).get_item(0)?;
        if !exception_info.is_none() {
            return Err(restore_wsgi_exception(py, &exception_info)?);
        }
        Ok(MachineAction::Complete(py.None()))
    }

    fn leave_stream(
        &mut self,
        py: Python<'_>,
        body_error: Option<StoredException>,
    ) -> PyResult<MachineAction> {
        let awaitable = context_exit(py, &self.stream_send_ref(py)?, body_error.as_ref())?;
        self.pending = Some(PendingOperation::StreamExit { body_error });
        Ok(MachineAction::Await(awaitable))
    }

    fn leave_task_group(
        &mut self,
        py: Python<'_>,
        body_error: Option<StoredException>,
    ) -> PyResult<MachineAction> {
        let awaitable = context_exit(py, &self.task_group_ref(py)?, body_error.as_ref())?;
        self.pending = Some(PendingOperation::TaskGroupExit { body_error });
        Ok(MachineAction::Await(awaitable))
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(PendingOperation::Worker) => {
                self.leave_stream(py, Some(StoredException::capture(py, error)))
            }
            Some(PendingOperation::StreamEnter) => {
                self.leave_task_group(py, Some(StoredException::capture(py, error)))
            }
            Some(PendingOperation::StreamExit { body_error }) => {
                error.set_context(py, body_error.map(|body| body.to_pyerr(py)));
                self.leave_task_group(py, Some(StoredException::capture(py, error)))
            }
            Some(PendingOperation::TaskGroupExit { body_error }) => {
                // The Rust continuation awaits __aexit__ outside a Python except
                // frame, so forward the context Python would install there.
                if let Some(body_error) = body_error {
                    if !error.value(py).is(body_error.value.bind(py)) {
                        error.set_context(py, Some(body_error.to_pyerr(py)));
                    }
                }
                Err(crate::runtime_calls::collapse_single_task_group_error(
                    py, error,
                )?)
            }
            Some(PendingOperation::Receive | PendingOperation::TaskGroupEnter) | None => Err(error),
        }
    }

    fn stream_send_ref<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        optional_bound(py, &self.stream_send, "WSGI send stream is unavailable")
    }

    fn stream_receive_ref<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        optional_bound(
            py,
            &self.stream_receive,
            "WSGI receive stream is unavailable",
        )
    }

    fn task_group_ref<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        optional_bound(py, &self.task_group, "WSGI task group is unavailable")
    }
}

fn optional_bound<'py>(
    py: Python<'py>,
    value: &Option<Py<PyAny>>,
    message: &'static str,
) -> PyResult<Bound<'py, PyAny>> {
    value
        .as_ref()
        .map(|value| value.bind(py).clone())
        .ok_or_else(|| PyRuntimeError::new_err(message))
}

impl PendingOperation {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        match self {
            Self::StreamExit { body_error } | Self::TaskGroupExit { body_error } => {
                if let Some(error) = body_error {
                    error.traverse(visit)?;
                }
                Ok(())
            }
            Self::Receive | Self::TaskGroupEnter | Self::StreamEnter | Self::Worker => Ok(()),
        }
    }
}

fn context_exit(
    py: Python<'_>,
    context: &Bound<'_, PyAny>,
    error: Option<&StoredException>,
) -> PyResult<Py<PyAny>> {
    let awaitable = match error {
        Some(error) => {
            let traceback = error.traceback.as_ref().map_or_else(
                || py.None().into_bound(py),
                |tb| tb.bind(py).clone().into_any(),
            );
            context.call_method1(
                "__aexit__",
                (
                    error.exception_type.bind(py),
                    error.value.bind(py),
                    traceback,
                ),
            )?
        }
        None => context.call_method1("__aexit__", (py.None(), py.None(), py.None()))?,
    };
    Ok(awaitable.unbind())
}

/// Starts the sender on the task group's child task with its inherited context.
#[pyclass]
struct PyWsgiSender {
    stream: Py<PyAny>,
    send: Py<PyAny>,
}

#[pymethods]
impl PyWsgiSender {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.stream)?;
        visit.call(&self.send)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.stream = py.None();
        self.send = py.None();
    }

    fn __call__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            WsgiSenderCall {
                stream: self.stream.clone_ref(py),
                send: self.send.clone_ref(py),
                message: None,
                pending: SenderPending::Start,
            },
        )
    }
}

enum SenderPending {
    Start,
    Enter,
    Receive,
    Send,
    Exit { body_error: Option<StoredException> },
}

struct WsgiSenderCall {
    stream: Py<PyAny>,
    send: Py<PyAny>,
    message: Option<Py<PyAny>>,
    pending: SenderPending,
}

impl AwaitableStateMachine for WsgiSenderCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.stream)?;
        visit.call(&self.send)?;
        visit.call(&self.message)?;
        if let SenderPending::Exit {
            body_error: Some(error),
        } = &self.pending
        {
            error.traverse(visit)?;
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                self.pending = SenderPending::Enter;
                Ok(MachineAction::Await(
                    self.stream.bind(py).call_method0("__aenter__")?.unbind(),
                ))
            }
            MachineResume::Value(value) => match &self.pending {
                SenderPending::Enter | SenderPending::Send => self.receive_next(py),
                SenderPending::Receive => {
                    // The async-for local survives the following receive and
                    // the stream exit, preserving Python-visible lifetimes.
                    self.message = Some(value.clone_ref(py));
                    self.pending = SenderPending::Send;
                    match self.send.bind(py).call1((value.bind(py),)) {
                        Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
                        Err(error) => self.leave_stream(py, Some(error)),
                    }
                }
                SenderPending::Exit { .. } => {
                    let pending = std::mem::replace(&mut self.pending, SenderPending::Start);
                    match pending {
                        SenderPending::Exit {
                            body_error: Some(error),
                        } if !value.bind(py).is_truthy()? => Err(error.to_pyerr(py)),
                        _ => Ok(MachineAction::Complete(py.None())),
                    }
                }
                SenderPending::Start => Err(PyRuntimeError::new_err("WSGI sender has not started")),
            },
            MachineResume::AsyncIterationComplete(error)
                if matches!(self.pending, SenderPending::Receive) =>
            {
                let _ = error;
                self.leave_stream(py, None)
            }
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                match &self.pending {
                    SenderPending::Receive if error.is_instance_of::<PyStopAsyncIteration>(py) => {
                        self.leave_stream(py, None)
                    }
                    SenderPending::Receive | SenderPending::Send => {
                        self.leave_stream(py, Some(error))
                    }
                    SenderPending::Exit { body_error } => {
                        if let Some(body_error) = body_error {
                            if !error.value(py).is(body_error.value.bind(py)) {
                                error.set_context(py, Some(body_error.to_pyerr(py)));
                            }
                        }
                        Err(error)
                    }
                    SenderPending::Start | SenderPending::Enter => Err(error),
                }
            }
        }
    }
}

impl WsgiSenderCall {
    fn receive_next(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        self.pending = SenderPending::Receive;
        match self.stream.bind(py).call_method0("__anext__") {
            Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
            Err(error) if error.is_instance_of::<PyStopAsyncIteration>(py) => {
                self.leave_stream(py, None)
            }
            Err(error) => self.leave_stream(py, Some(error)),
        }
    }

    fn leave_stream(
        &mut self,
        py: Python<'_>,
        body_error: Option<PyErr>,
    ) -> PyResult<MachineAction> {
        let body_error = body_error.map(|error| StoredException::capture(py, error));
        let awaitable = context_exit(py, self.stream.bind(py), body_error.as_ref())?;
        self.pending = SenderPending::Exit { body_error };
        Ok(MachineAction::Await(awaitable))
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
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.send)?;
        visit.call(&self.exception_info)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
        self.send = py.None();
        self.exception_info = PyList::empty(py).unbind();
    }

    fn __call__(&self, py: Python<'_>, environ: Py<PyAny>) -> PyResult<()> {
        let start_response = Py::new(
            py,
            PyWsgiStartResponse {
                send: self.send.clone_ref(py),
                response_started: Arc::clone(&self.response_started),
                exception_info: self.exception_info.clone_ref(py),
            },
        )?;
        let iterable = self
            .app
            .bind(py)
            .call1((environ, start_response.clone_ref(py)))?;
        let iterator = iterable.try_iter()?;
        drop(iterable);
        let mut last_chunk = None;
        for chunk in iterator {
            let chunk = chunk?;
            last_chunk.replace(chunk.clone().unbind());
            let message = PyDict::new(py);
            message.set_item("type", "http.response.body")?;
            message.set_item("body", chunk)?;
            message.set_item("more_body", true)?;
            send_from_worker(py, self.send.bind(py), &message)?;
        }
        let final_message = PyDict::new(py);
        final_message.set_item("type", "http.response.body")?;
        final_message.set_item("body", PyBytes::new(py, b""))?;
        let result = send_from_worker(py, self.send.bind(py), &final_message);
        drop(last_chunk);
        result
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
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send)?;
        visit.call(&self.exception_info)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.send = py.None();
        self.exception_info = PyList::empty(py).unbind();
    }

    #[pyo3(signature = (status, response_headers, exc_info=None))]
    fn __call__(
        &self,
        py: Python<'_>,
        status: Py<PyAny>,
        response_headers: Py<PyAny>,
        exc_info: Option<Py<PyAny>>,
    ) -> PyResult<()> {
        self.exception_info
            .bind(py)
            .set_item(0, exc_info.unwrap_or_else(|| py.None()))?;
        if self.response_started.swap(true, Ordering::SeqCst) {
            return Ok(());
        }

        let status_parts = status.bind(py).call_method1("split", (" ", 1))?;
        let (status_code_part, _) = unpack_wsgi_pair(py, &status_parts)?;
        let status_code = py
            .import("builtins")?
            .getattr("int")?
            .call1((status_code_part,))?;
        let headers = PyList::empty(py);
        for header in response_headers.bind(py).try_iter()? {
            let header = header?;
            let (name, value) = unpack_wsgi_pair(py, &header)?;
            let name = name
                .bind(py)
                .call_method0("strip")?
                .call_method1("encode", ("ascii",))?
                .call_method0("lower")?;
            let value = value
                .bind(py)
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

/// Match the two-target unpacking performed for WSGI status parts and response headers.
fn unpack_wsgi_pair(py: Python<'_>, header: &Bound<'_, PyAny>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    // Python's unpack fast path skips subclass overrides only for exact lists and tuples.
    if header.is_exact_instance_of::<PyTuple>() {
        let values = header.cast::<PyTuple>()?;
        let value_count = values.len();
        if value_count != 2 {
            return Err(wsgi_pair_arity_error(value_count));
        }
        return Ok((values.get_item(0)?.unbind(), values.get_item(1)?.unbind()));
    }
    if header.is_exact_instance_of::<PyList>() {
        let values = header.cast::<PyList>()?;
        let value_count = values.len();
        if value_count != 2 {
            return Err(wsgi_pair_arity_error(value_count));
        }
        return Ok((values.get_item(0)?.unbind(), values.get_item(1)?.unbind()));
    }

    let header_type = header.get_type();
    let mut values = match header.try_iter() {
        Ok(values) => values,
        Err(error)
            if error.is_instance_of::<PyTypeError>(py)
                && !header_type.hasattr("__iter__")?
                && !header_type.hasattr("__getitem__")? =>
        {
            let type_name = header_type.name()?.to_string();
            return Err(PyTypeError::new_err(format!(
                "cannot unpack non-iterable {type_name} object"
            )));
        }
        Err(error) => return Err(error),
    };
    let name = values
        .next()
        .transpose()?
        .ok_or_else(|| wsgi_pair_arity_error(0))?;
    let value = values
        .next()
        .transpose()?
        .ok_or_else(|| wsgi_pair_arity_error(1))?;
    if values.next().transpose()?.is_some() {
        return Err(wsgi_pair_arity_error(3));
    }
    Ok((name.unbind(), value.unbind()))
}

fn wsgi_pair_arity_error(value_count: usize) -> PyErr {
    if value_count < 2 {
        PyValueError::new_err(format!(
            "not enough values to unpack (expected 2, got {value_count})"
        ))
    } else {
        PyValueError::new_err("too many values to unpack (expected 2)")
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
