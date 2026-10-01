//! Rust-owned ASGI continuation for Starlette's outer server-error middleware.
//!
//! Python remains at the boundaries where its runtime is required: invoking
//! the ASGI application and user handler, awaiting their objects on the active
//! event loop, constructing the public Request facade, and extracting CPython
//! traceback/source context for Rust's renderer.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::exceptions::{PyAttributeError, PyException, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString, PyTuple};
use starlette_rs::ServerErrorState;

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

type SharedErrorState = Rc<RefCell<ServerErrorState>>;
type TracebackFrame = (String, usize, String, Vec<String>, usize);
type HtmlTracebackInputs = (String, String, Vec<TracebackFrame>);

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyServerErrorMiddlewareRuntime>()?;
    module.add_class::<PyServerErrorSendProxy>()?;
    module.add_function(wrap_pyfunction!(
        new_server_error_middleware_runtime,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        server_error_middleware_runtime_with_policy,
        module
    )?)?;
    Ok(())
}

/// Holds application callbacks and asks Rust's policy to select each error path.
///
/// The runtime is cached in Starlette's middleware stack and may be invoked on
/// a TestClient portal thread other than the one that built the stack.
#[pyclass(name = "ServerErrorMiddlewareRuntime")]
struct PyServerErrorMiddlewareRuntime {
    policy_source: ServerErrorPolicySource,
    request_type: Py<PyAny>,
    response_type: Py<PyAny>,
}

enum ServerErrorPolicySource {
    Direct,
    Shared {
        handlers: Py<PyAny>,
        policy: Py<PyAny>,
    },
}

impl ServerErrorPolicySource {
    fn clone_ref(&self, py: Python<'_>) -> Self {
        match self {
            Self::Direct => Self::Direct,
            Self::Shared { handlers, policy } => Self::Shared {
                handlers: handlers.clone_ref(py),
                policy: policy.clone_ref(py),
            },
        }
    }
}

#[pymethods]
impl PyServerErrorMiddlewareRuntime {
    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        middleware: Py<PyAny>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let runtime = slf.borrow(py);
        into_python_awaitable(
            py,
            ServerErrorCall {
                middleware,
                policy_source: runtime.policy_source.clone_ref(py),
                request_type: runtime.request_type.clone_ref(py),
                response_type: runtime.response_type.clone_ref(py),
                scope,
                receive,
                send,
                send_proxy: None,
                state: Rc::new(RefCell::new(ServerErrorState::new())),
                pending: None,
                original_exception: None,
            },
        )
    }
}

impl PyServerErrorMiddlewareRuntime {
    fn new(
        policy_source: ServerErrorPolicySource,
        request_type: Py<PyAny>,
        response_type: Py<PyAny>,
    ) -> Self {
        Self {
            policy_source,
            request_type,
            response_type,
        }
    }
}

/// Construct a direct middleware runtime that reads public fields per call.
#[pyfunction(name = "_new_server_error_middleware_runtime")]
fn new_server_error_middleware_runtime(
    py: Python<'_>,
    request_type: Py<PyAny>,
    response_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    Py::new(
        py,
        PyServerErrorMiddlewareRuntime::new(
            ServerErrorPolicySource::Direct,
            request_type,
            response_type,
        ),
    )
    .map(|runtime| runtime.into_any())
}

/// Construct the app's shared callback registry and already-configured Rust policy.
#[pyfunction(name = "_server_error_middleware_runtime_with_policy")]
fn server_error_middleware_runtime_with_policy(
    py: Python<'_>,
    handlers: Py<PyAny>,
    policy: Py<PyAny>,
    request_type: Py<PyAny>,
    response_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    Py::new(
        py,
        PyServerErrorMiddlewareRuntime::new(
            ServerErrorPolicySource::Shared { handlers, policy },
            request_type,
            response_type,
        ),
    )
    .map(|runtime| runtime.into_any())
}

#[pyclass(name = "_ServerErrorSendProxy", unsendable)]
struct PyServerErrorSendProxy {
    send: Py<PyAny>,
    state: SharedErrorState,
}

#[pymethods]
impl PyServerErrorSendProxy {
    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let proxy = slf.borrow(py);
        into_python_awaitable(
            py,
            ServerErrorSendCall {
                send: proxy.send.clone_ref(py),
                state: proxy.state.clone(),
                message,
                pending: false,
            },
        )
    }
}

struct ServerErrorSendCall {
    send: Py<PyAny>,
    state: SharedErrorState,
    message: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for ServerErrorSendCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                let message_type = self
                    .message
                    .bind(py)
                    .get_item("type")?
                    .extract::<String>()?;
                self.state.borrow_mut().observe_send(&message_type);
                let awaitable = self.send.bind(py).call1((self.message.bind(py),))?;
                self.pending = true;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("server-error send continuation has no pending send"),
            ),
        }
    }
}

#[derive(Clone, Copy)]
enum ServerErrorPending {
    Passthrough,
    Application,
    Handler,
    Response,
}

struct ServerErrorCall {
    middleware: Py<PyAny>,
    policy_source: ServerErrorPolicySource,
    request_type: Py<PyAny>,
    response_type: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    send_proxy: Option<Py<PyAny>>,
    state: SharedErrorState,
    pending: Option<ServerErrorPending>,
    original_exception: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for ServerErrorCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "server-error middleware continuation has a pending call",
            )),
            MachineResume::Value(value) => match self.pending.take() {
                Some(ServerErrorPending::Passthrough) => Ok(MachineAction::Complete(py.None())),
                Some(ServerErrorPending::Application) => Ok(MachineAction::Complete(py.None())),
                Some(ServerErrorPending::Handler) => self.finish_error_response(py, value),
                Some(ServerErrorPending::Response) => self.reraise_application_exception(py),
                None => Err(PyRuntimeError::new_err(
                    "server-error middleware continuation has no pending call",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(ServerErrorPending::Passthrough) => Err(error),
                Some(ServerErrorPending::Application) => self.application_failed(py, error),
                Some(ServerErrorPending::Handler | ServerErrorPending::Response) => {
                    Err(self.chain_to_original(py, error))
                }
                None => Err(error),
            },
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
        }
    }
}

impl ServerErrorCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope_type = self.scope.bind(py).get_item("type")?.extract::<String>()?;
        let send = if scope_type == "http" {
            let proxy = Py::new(
                py,
                PyServerErrorSendProxy {
                    send: self.send.clone_ref(py),
                    state: self.state.clone(),
                },
            )?
            .into_any();
            self.send_proxy = Some(proxy.clone_ref(py));
            proxy
        } else {
            self.send.clone_ref(py)
        };

        self.pending = Some(if scope_type == "http" {
            ServerErrorPending::Application
        } else {
            ServerErrorPending::Passthrough
        });
        let application_call =
            self.middleware.bind(py).getattr("app").and_then(|app| {
                app.call1((self.scope.bind(py), self.receive.bind(py), send.bind(py)))
            });
        match application_call {
            Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
            Err(error) => match self.pending.take() {
                Some(ServerErrorPending::Passthrough) => Err(error),
                Some(ServerErrorPending::Application) => self.application_failed(py, error),
                Some(ServerErrorPending::Handler | ServerErrorPending::Response) | None => {
                    Err(error)
                }
            },
        }
    }

    fn application_failed(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if !error.is_instance_of::<PyException>(py) {
            return Err(error);
        }
        let original = error.value(py).clone().into_any().unbind();
        self.original_exception = Some(original.clone_ref(py));
        self.handle_exception(py, original.bind(py))
            .map_err(|handling_error| chain_error(py, handling_error, &original))
    }

    fn handle_exception(
        &mut self,
        py: Python<'_>,
        exception: &Bound<'_, PyAny>,
    ) -> PyResult<MachineAction> {
        let request = self.request_type.bind(py).call1((self.scope.bind(py),))?;
        let headers = request.getattr("headers")?;
        let accept = headers.call_method1("get", ("accept", ""))?;
        let (handlers, policy) = self.current_policy(py)?;
        let plan = policy.bind(py).call_method1("plan", (accept,))?;
        let plan = plan.cast::<PyTuple>()?;
        let plan_name = plan.get_item(0)?.extract::<String>()?;
        let handler_index = plan.get_item(1)?.extract::<Option<usize>>()?;

        let response = match plan_name.as_str() {
            "default" => self.response_type.bind(py).call_method1(
                "_from_native",
                (py.import("starlette_rs_py._core")?
                    .getattr("_server_error_response")?
                    .call0()?,),
            )?,
            "custom-handler" => {
                let Some(handler_index) = handler_index else {
                    let error = PyRuntimeError::new_err(
                        "Rust selected a custom error handler without an index",
                    );
                    let original = PyErr::from_value(exception.clone());
                    error.set_context(py, Some(original.clone_ref(py)));
                    error.set_cause(py, Some(original));
                    return Err(error);
                };
                let handler = handlers.bind(py).get_item(handler_index)?;
                let is_async = crate::background::is_async_callable(py, &handler)?;
                let awaitable = if is_async {
                    handler.call1((request, exception))?
                } else {
                    py.import("starlette_rs_py._core")?
                        .getattr("run_in_threadpool")?
                        .call1((handler, request, exception))?
                };
                self.pending = Some(ServerErrorPending::Handler);
                return Ok(MachineAction::Await(awaitable.unbind()));
            }
            "debug-text" => {
                let traceback = debug_traceback_text(py, exception)?;
                let native_response = py
                    .import("starlette_rs_py._core")?
                    .getattr("_debug_traceback_text_response")?
                    .call1((traceback,))?;
                self.response_type
                    .bind(py)
                    .call_method1("_from_native", (native_response,))?
            }
            "debug-html" => {
                let (exception_type, exception_message, frames) =
                    debug_traceback_html_inputs(py, exception)?;
                let native_response = py
                    .import("starlette_rs_py._core")?
                    .getattr("_debug_traceback_html_response")?
                    .call1((exception_type, exception_message, frames))?;
                self.response_type
                    .bind(py)
                    .call_method1("_from_native", (native_response,))?
            }
            _ => {
                let error = PyRuntimeError::new_err(format!(
                    "Rust returned an unknown server-error plan: {plan_name:?}"
                ));
                let original = PyErr::from_value(exception.clone());
                error.set_context(py, Some(original.clone_ref(py)));
                error.set_cause(py, Some(original));
                return Err(error);
            }
        };

        self.send_response_or_reraise(py, response)
    }

    fn current_policy(&self, py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
        match &self.policy_source {
            ServerErrorPolicySource::Direct => {
                let middleware = self.middleware.bind(py);
                let debug = middleware.getattr("debug")?.is_truthy()?;
                let core = py.import("starlette_rs_py._core")?;
                let policy = core.getattr("ServerErrorPolicy")?.call1((debug,))?;
                let handlers = PyList::empty(py);
                if !debug {
                    let handler = middleware.getattr("handler")?;
                    if !handler.is_none() {
                        policy.call_method1("register_handler", (0,))?;
                        handlers.append(handler)?;
                    }
                }
                Ok((handlers.into_any().unbind(), policy.unbind()))
            }
            ServerErrorPolicySource::Shared { handlers, policy } => {
                Ok((handlers.clone_ref(py), policy.clone_ref(py)))
            }
        }
    }

    fn finish_error_response(
        &mut self,
        py: Python<'_>,
        response: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        let original = self
            .original_exception
            .as_ref()
            .ok_or_else(|| {
                PyRuntimeError::new_err("server-error middleware lost the application exception")
            })?
            .clone_ref(py);
        self.send_response_or_reraise(py, response.into_bound(py))
            .map_err(|error| chain_error(py, error, &original))
    }

    fn send_response_or_reraise(
        &mut self,
        py: Python<'_>,
        response: Bound<'_, PyAny>,
    ) -> PyResult<MachineAction> {
        let should_send = self.state.borrow().should_send_response();
        if !should_send {
            return self.reraise_application_exception(py);
        }
        let awaitable = response.call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = Some(ServerErrorPending::Response);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn reraise_application_exception(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let exception = self.original_exception.take().ok_or_else(|| {
            PyRuntimeError::new_err("server-error middleware lost the application exception")
        })?;
        Err(PyErr::from_value(exception.into_bound(py)))
    }

    fn chain_to_original(&self, py: Python<'_>, error: PyErr) -> PyErr {
        match self.original_exception.as_ref() {
            Some(exception) => chain_error(py, error, exception),
            None => error,
        }
    }
}

fn chain_error(py: Python<'_>, error: PyErr, original: &Py<PyAny>) -> PyErr {
    if !error.value(py).is(original.bind(py)) {
        error.set_context(py, Some(PyErr::from_value(original.bind(py).clone())));
    }
    error
}

fn debug_traceback_text(py: Python<'_>, exception: &Bound<'_, PyAny>) -> PyResult<String> {
    let traceback = py.import("traceback")?;
    let formatted = traceback.getattr("format_exception")?.call1((
        exception.get_type(),
        exception,
        exception.getattr("__traceback__")?,
    ))?;
    PyString::new(py, "")
        .call_method1("join", (formatted,))?
        .extract()
}

fn debug_traceback_html_inputs(
    py: Python<'_>,
    exception: &Bound<'_, PyAny>,
) -> PyResult<HtmlTracebackInputs> {
    let traceback = py.import("traceback")?;
    let traceback_exception_type = traceback.getattr("TracebackException")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("capture_locals", true)?;
    let traceback_exception = traceback_exception_type
        .getattr("from_exception")?
        .call((exception,), Some(&kwargs))?;
    let exception_type = match traceback_exception.getattr("exc_type_str") {
        Ok(value) => value.extract::<String>()?,
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => traceback_exception
            .getattr("exc_type")?
            .getattr("__name__")?
            .extract::<String>()?,
        Err(error) => return Err(error),
    };
    let exception_message = py
        .import("builtins")?
        .getattr("str")?
        .call1((traceback_exception,))?
        .extract::<String>()?;

    let traceback_object = exception.getattr("__traceback__")?;
    let mut frames = Vec::new();
    if !traceback_object.is_none() {
        let inspect = py.import("inspect")?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("context", 7)?;
        let inner_frames = inspect
            .getattr("getinnerframes")?
            .call((traceback_object,), Some(&kwargs))?;
        for frame in inner_frames.try_iter()? {
            let frame = frame?;
            let filename = frame.getattr("filename")?.extract::<String>()?;
            let line = frame.getattr("lineno")?.extract::<usize>()?;
            let function = frame.getattr("function")?.extract::<String>()?;
            let code_context = frame.getattr("code_context")?;
            let source_lines = if code_context.is_none() {
                Vec::new()
            } else {
                code_context.extract::<Vec<String>>()?
            };
            let center_index = frame
                .getattr("index")?
                .extract::<Option<usize>>()?
                .unwrap_or(0);
            frames.push((filename, line, function, source_lines, center_index));
        }
    }

    Ok((exception_type, exception_message, frames))
}
