//! Rust-owned ASGI message flow for GZip middleware.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyKeyError, PyLookupError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyTuple};
use starlette_rs::{DEFAULT_EXCLUDED_CONTENT_TYPES, GzipHeader};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyGzipMiddlewareRuntime>()?;
    module.add_class::<PyGzipSendProxy>()?;
    module.add(
        "GZIP_DEFAULT_EXCLUDED_CONTENT_TYPES",
        PyTuple::new(module.py(), DEFAULT_EXCLUDED_CONTENT_TYPES)?,
    )?;
    module.add_function(wrap_pyfunction!(offload_gzip_body, module)?)?;
    Ok(())
}

#[pyfunction(name = "_offload_gzip_body")]
fn offload_gzip_body(
    py: Python<'_>,
    responder: &Bound<'_, PyAny>,
    body: &Bound<'_, PyAny>,
    more_body: bool,
    capacity_limiter_run_var: &Bound<'_, PyAny>,
    capacity_limiter_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let limiter = match capacity_limiter_run_var.call_method0("get") {
        Ok(limiter) => limiter,
        Err(error) if error.is_instance_of::<PyLookupError>(py) => {
            let limiter = capacity_limiter_type.call1((40,))?;
            capacity_limiter_run_var.call_method1("set", (&limiter,))?;
            limiter
        }
        Err(error) => return Err(error),
    };

    let kwargs = PyDict::new(py);
    kwargs.set_item("limiter", &limiter)?;
    py.import("anyio.to_thread")?
        .getattr("run_sync")?
        .call(
            (responder.getattr("response_body")?, body, more_body),
            Some(&kwargs),
        )
        .map(Bound::unbind)
}

/// Owns GZip middleware configuration and delegates the Python application
/// call through the active Python task's awaitable driver.
#[pyclass(name = "GZipMiddlewareRuntime")]
pub(crate) struct PyGzipMiddlewareRuntime {
    app: Py<PyAny>,
    config: Py<PyAny>,
    offload_body: Py<PyAny>,
    gzip_always: bool,
}

#[pymethods]
impl PyGzipMiddlewareRuntime {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.config)?;
        visit.call(&self.offload_body)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
        self.config = py.None();
        self.offload_body = py.None();
    }

    #[new]
    #[pyo3(signature = (app, config, offload_body, gzip_always=false))]
    fn new(app: Py<PyAny>, config: Py<PyAny>, offload_body: Py<PyAny>, gzip_always: bool) -> Self {
        Self {
            app,
            config,
            offload_body,
            gzip_always,
        }
    }

    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let runtime = slf.borrow(py);
        into_sendable_python_awaitable(
            py,
            GzipMiddlewareCall {
                app: runtime.app.clone_ref(py),
                config: runtime.config.clone_ref(py),
                offload_body: runtime.offload_body.clone_ref(py),
                gzip_always: runtime.gzip_always,
                scope,
                receive,
                send,
                pending: false,
            },
        )
    }
}

struct GzipMiddlewareCall {
    app: Py<PyAny>,
    config: Py<PyAny>,
    offload_body: Py<PyAny>,
    gzip_always: bool,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for GzipMiddlewareCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.config)?;
        visit.call(&self.offload_body)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => Err(error),
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => {
                Err(PyRuntimeError::new_err(
                    "GZip middleware continuation has no pending application call",
                ))
            }
        }
    }
}

impl GzipMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;

        let send = if scope_type == "http" || self.gzip_always {
            let config = self.config.bind(py);
            let responder = if self.gzip_always {
                config.call_method0("gzip_responder")?.unbind()
            } else {
                let request_headers = scope
                    .get_item("headers")?
                    .ok_or_else(|| PyKeyError::new_err("headers"))?
                    .extract::<Vec<GzipHeader>>()?;
                let request_headers = gzip_headers_to_python(py, &request_headers)?;
                config
                    .call_method1("responder", (request_headers,))?
                    .unbind()
            };
            let initial_message = PyDict::new(py).into_any().unbind();
            Py::new(
                py,
                PyGzipSendProxy {
                    state: Py::new(
                        py,
                        GzipSendState {
                            responder,
                            send: self.send.clone_ref(py),
                            offload_body: self.offload_body.clone_ref(py),
                            initial_message,
                        },
                    )?,
                },
            )?
            .into_any()
        } else {
            self.send.clone_ref(py)
        };

        let awaitable =
            self.app
                .bind(py)
                .call1((self.scope.bind(py), self.receive.bind(py), send.bind(py)))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[pyclass(name = "_GZipSendProxy")]
struct PyGzipSendProxy {
    state: Py<GzipSendState>,
}

#[pymethods]
impl PyGzipSendProxy {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state)
    }

    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let state = slf.borrow(py).state.clone_ref(py);
        into_sendable_python_awaitable(
            py,
            GzipSendMessage {
                state,
                message,
                pending: None,
                original_body: None,
                compressed_body: None,
            },
        )
    }
}

#[pyclass]
struct GzipSendState {
    responder: Py<PyAny>,
    send: Py<PyAny>,
    offload_body: Py<PyAny>,
    initial_message: Py<PyAny>,
}

#[derive(Clone, Copy)]
enum BufferedFollowup {
    Body,
    Pathsend,
}

enum GzipSendPending {
    Compression,
    BufferedStart(BufferedFollowup),
    FinalMessage,
}

struct GzipSendMessage {
    state: Py<GzipSendState>,
    message: Py<PyAny>,
    pending: Option<GzipSendPending>,
    original_body: Option<Py<PyAny>>,
    compressed_body: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for GzipSendMessage {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state)?;
        visit.call(&self.message)?;
        visit.call(&self.original_body)?;
        visit.call(&self.compressed_body)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.process_message(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(GzipSendPending::Compression) => self.finish_body(py, value),
                Some(GzipSendPending::BufferedStart(BufferedFollowup::Body)) => {
                    let compressed_body = self.compressed_body.take().ok_or_else(|| {
                        PyRuntimeError::new_err("GZip body output was not retained")
                    })?;
                    self.replace_body_if_changed(py, compressed_body.bind(py))?;
                    self.send_message(
                        py,
                        self.message.clone_ref(py),
                        GzipSendPending::FinalMessage,
                    )
                }
                Some(GzipSendPending::BufferedStart(BufferedFollowup::Pathsend)) => self
                    .send_message(
                        py,
                        self.message.clone_ref(py),
                        GzipSendPending::FinalMessage,
                    ),
                Some(GzipSendPending::FinalMessage) => Ok(MachineAction::Complete(py.None())),
                None => Err(PyRuntimeError::new_err(
                    "GZip send continuation received a result without a pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(_) => Err(error),
                None => Err(PyRuntimeError::new_err(
                    "GZip send continuation has no pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "GZip send continuation has no pending operation",
            )),
        }
    }
}

impl GzipSendMessage {
    fn process_message(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message_type = {
            let message = self.message.bind(py).cast::<PyDict>()?;
            message
                .get_item("type")?
                .ok_or_else(|| PyKeyError::new_err("type"))?
                .extract::<String>()?
        };

        match message_type.as_str() {
            "http.response.start" => {
                let message = self.message.bind(py).cast::<PyDict>()?;
                let status = message
                    .get_item("status")?
                    .ok_or_else(|| PyKeyError::new_err("status"))?
                    .extract::<u16>()?;
                let headers = message
                    .get_item("headers")?
                    .ok_or_else(|| PyKeyError::new_err("headers"))?
                    .extract::<Vec<GzipHeader>>()?;
                let responder = self.responder(py);
                self.state.borrow_mut(py).initial_message = self.message.clone_ref(py);
                responder.bind(py).call_method1(
                    "response_start",
                    (status, gzip_headers_to_python(py, &headers)?),
                )?;
                Ok(MachineAction::Complete(py.None()))
            }
            "http.response.body" => self.start_body(py),
            "http.response.pathsend" => self.start_pathsend(py),
            _ => Ok(MachineAction::Complete(py.None())),
        }
    }

    fn start_body(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py).cast::<PyDict>()?;
        let empty_body = PyBytes::new(py, &[]).into_any();
        let body = message
            .get_item("body")?
            .unwrap_or_else(|| empty_body.clone());
        let more_body = message
            .get_item("more_body")?
            .map(|value| value.extract::<bool>())
            .transpose()?
            .unwrap_or(false);
        let body_length = body.len()?;
        let responder = self.responder(py);
        let offload = responder
            .bind(py)
            .call_method1("should_offload", (body_length, more_body))?
            .extract::<bool>()?;
        self.original_body = Some(body.clone().unbind());

        let output = if offload {
            let callback = self.offload_body(py);
            let awaitable = callback.bind(py).call1((responder, body, more_body))?;
            self.pending = Some(GzipSendPending::Compression);
            return Ok(MachineAction::Await(awaitable.unbind()));
        } else {
            responder
                .bind(py)
                .call_method1("response_body", (body, more_body))?
                .unbind()
        };
        self.finish_body(py, output)
    }

    fn finish_body(&mut self, py: Python<'_>, output: Py<PyAny>) -> PyResult<MachineAction> {
        let output = output.bind(py).cast::<PyTuple>()?;
        let response_start = output.get_item(0)?;
        let output_body = output.get_item(1)?;
        if !response_start.is_none() {
            let (_status, headers) = response_start.extract::<(u16, Vec<GzipHeader>)>()?;
            self.replace_initial_headers(py, &headers)?;
            self.compressed_body = Some(output_body.unbind());
            let initial_message = self.initial_message(py);
            return self.send_message(
                py,
                initial_message,
                GzipSendPending::BufferedStart(BufferedFollowup::Body),
            );
        }

        self.replace_body_if_changed(py, &output_body)?;
        self.send_message(
            py,
            self.message.clone_ref(py),
            GzipSendPending::FinalMessage,
        )
    }

    fn start_pathsend(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let responder = self.responder(py);
        let response_start = responder.bind(py).call_method0("pathsend")?;
        if !response_start.is_none() {
            let (_status, headers) = response_start.extract::<(u16, Vec<GzipHeader>)>()?;
            self.replace_initial_headers(py, &headers)?;
        }
        self.send_message(
            py,
            self.initial_message(py),
            GzipSendPending::BufferedStart(BufferedFollowup::Pathsend),
        )
    }

    fn replace_body_if_changed(
        &self,
        py: Python<'_>,
        output_body: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let Some(original_body) = self.original_body.as_ref() else {
            return Err(PyRuntimeError::new_err(
                "GZip body output has no input body",
            ));
        };
        let output_bytes = output_body.extract::<Vec<u8>>()?;
        let input_bytes = original_body.bind(py).extract::<Vec<u8>>()?;
        if output_bytes != input_bytes {
            self.message
                .bind(py)
                .cast::<PyDict>()?
                .set_item("body", PyBytes::new(py, &output_bytes))?;
        }
        Ok(())
    }

    fn replace_initial_headers(&self, py: Python<'_>, headers: &[GzipHeader]) -> PyResult<()> {
        let initial_message = self.initial_message(py);
        let message = initial_message.bind(py).cast::<PyDict>()?;
        let headers_object = message
            .get_item("headers")?
            .ok_or_else(|| PyKeyError::new_err("headers"))?;
        let headers_list = headers_object.cast::<PyList>()?;
        let replacement = gzip_headers_to_python(py, headers)?;
        headers_list.set_slice(0, headers_list.len(), &replacement)?;
        Ok(())
    }

    fn send_message(
        &mut self,
        py: Python<'_>,
        message: Py<PyAny>,
        pending: GzipSendPending,
    ) -> PyResult<MachineAction> {
        let callback = self.send(py);
        let awaitable = callback.bind(py).call1((message,))?;
        self.pending = Some(pending);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn initial_message(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow(py).initial_message.clone_ref(py)
    }

    fn responder(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow(py).responder.clone_ref(py)
    }

    fn offload_body(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow(py).offload_body.clone_ref(py)
    }

    fn send(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow(py).send.clone_ref(py)
    }
}

fn gzip_headers_to_python<'py>(
    py: Python<'py>,
    headers: &[GzipHeader],
) -> PyResult<Bound<'py, PyList>> {
    let result = PyList::empty(py);
    for (name, value) in headers {
        let pair = PyTuple::new(py, [PyBytes::new(py, name), PyBytes::new(py, value)])?;
        result.append(pair)?;
    }
    Ok(result)
}

#[pymethods]
impl GzipSendState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.responder)?;
        visit.call(&self.send)?;
        visit.call(&self.offload_body)?;
        visit.call(&self.initial_message)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.responder = py.None();
        self.send = py.None();
        self.offload_body = py.None();
        self.initial_message = py.None();
    }
}
