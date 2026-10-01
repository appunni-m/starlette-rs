//! Rust-owned RequestBodyLimit ASGI continuation.
//!
//! Scope mutation, size accounting, nesting, response ordering, and exception
//! policy live here. ASGI callbacks and `PlainTextResponse` remain Python
//! objects so they execute on the caller's event loop and retain the public
//! exception/response classes.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyRuntimeError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt, PyModule};
use starlette_rs::Response;

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

const MAX_BODY_SIZE_SCOPE_KEY: &str = "starlette.max_body_size";
const BODY_LIMIT_RESPONDER_SCOPE_KEY: &str = "starlette._body_limit_responder";
const REQUEST_BODY_LIMIT_STATUS_CODE: u16 = 413;
const REQUEST_BODY_LIMIT_DETAIL: &str = "Content Too Large";

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyRequestBodyLimitResponder>()?;
    module.add_class::<PyRequestBodyLimitMiddlewareRuntime>()?;
    module.add("MAX_BODY_SIZE_SCOPE_KEY", MAX_BODY_SIZE_SCOPE_KEY)?;
    module.add(
        "BODY_LIMIT_RESPONDER_SCOPE_KEY",
        BODY_LIMIT_RESPONDER_SCOPE_KEY,
    )?;
    Ok(())
}

/// The public responder type keeps the source-visible mutable state attributes.
#[pyclass(
    name = "RequestBodyLimitResponder",
    module = "starlette.middleware.body_limit",
    unsendable
)]
pub(crate) struct PyRequestBodyLimitResponder {
    state: SharedBodyLimitState,
}

type SharedBodyLimitState = Rc<RefCell<BodyLimitState>>;

struct BodyLimitState {
    app: Py<PyAny>,
    max_body_size: Py<PyAny>,
    scope: Option<Py<PyAny>>,
    receive: Option<Py<PyAny>>,
    send: Option<Py<PyAny>>,
    content_length: Py<PyAny>,
    total_size: Py<PyAny>,
    response_started: bool,
    too_large_type: Py<PyAny>,
    response_sent_type: Py<PyAny>,
}

#[pymethods]
impl PyRequestBodyLimitResponder {
    #[new]
    fn new(py: Python<'_>, app: Py<PyAny>, max_body_size: Py<PyAny>) -> PyResult<Self> {
        let module = py.import("starlette.middleware.body_limit")?;
        Ok(Self {
            state: Rc::new(RefCell::new(BodyLimitState {
                app,
                max_body_size,
                scope: None,
                receive: None,
                send: None,
                content_length: py.None(),
                total_size: PyInt::new(py, 0).into_any().unbind(),
                response_started: false,
                too_large_type: module.getattr("_RequestBodyTooLarge")?.unbind(),
                response_sent_type: module.getattr("_RequestBodyLimitResponseSent")?.unbind(),
            })),
        })
    }

    #[getter]
    fn app(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow().app.clone_ref(py)
    }

    #[setter]
    fn set_app(&mut self, app: Py<PyAny>) {
        self.state.borrow_mut().app = app;
    }

    #[getter]
    fn max_body_size(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow().max_body_size.clone_ref(py)
    }

    #[setter]
    fn set_max_body_size(&mut self, max_body_size: Py<PyAny>) {
        self.state.borrow_mut().max_body_size = max_body_size;
    }

    #[getter(_scope)]
    fn internal_scope(&self, py: Python<'_>) -> Py<PyAny> {
        self.state
            .borrow()
            .scope
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py))
    }

    #[setter(_scope)]
    fn set_internal_scope(&mut self, scope: Option<Py<PyAny>>) {
        self.state.borrow_mut().scope = scope;
    }

    #[getter(_receive)]
    fn internal_receive(&self, py: Python<'_>) -> Py<PyAny> {
        self.state
            .borrow()
            .receive
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py))
    }

    #[setter(_receive)]
    fn set_internal_receive(&mut self, receive: Option<Py<PyAny>>) {
        self.state.borrow_mut().receive = receive;
    }

    #[getter(_send)]
    fn internal_send(&self, py: Python<'_>) -> Py<PyAny> {
        self.state
            .borrow()
            .send
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py))
    }

    #[setter(_send)]
    fn set_internal_send(&mut self, send: Option<Py<PyAny>>) {
        self.state.borrow_mut().send = send;
    }

    #[getter]
    fn content_length(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow().content_length.clone_ref(py)
    }

    #[setter]
    fn set_content_length(&mut self, content_length: Py<PyAny>) {
        self.state.borrow_mut().content_length = content_length;
    }

    #[getter]
    fn total_size(&self, py: Python<'_>) -> Py<PyAny> {
        self.state.borrow().total_size.clone_ref(py)
    }

    #[setter]
    fn set_total_size(&mut self, total_size: Py<PyAny>) {
        self.state.borrow_mut().total_size = total_size;
    }

    #[getter]
    fn response_started(&self) -> bool {
        self.state.borrow().response_started
    }

    #[setter]
    fn set_response_started(&mut self, response_started: bool) {
        self.state.borrow_mut().response_started = response_started;
    }

    #[getter]
    fn scope(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.state
            .borrow()
            .scope
            .as_ref()
            .map(|value| value.clone_ref(py))
            .ok_or_else(|| PyAssertionError::new_err(""))
    }

    #[getter]
    fn receive(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.state
            .borrow()
            .receive
            .as_ref()
            .map(|value| value.clone_ref(py))
            .ok_or_else(|| PyAssertionError::new_err(""))
    }

    #[getter]
    fn send(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.state
            .borrow()
            .send
            .as_ref()
            .map(|value| value.clone_ref(py))
            .ok_or_else(|| PyAssertionError::new_err(""))
    }

    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let state = slf.borrow(py).state.clone();
        into_python_awaitable(
            py,
            BodyLimitCallMachine {
                responder: slf,
                state,
                scope,
                receive,
                send,
                pending: None,
                nested: false,
                cleanup_on_finish: false,
                previous_scope_limit: None,
                had_previous_scope_limit: false,
            },
        )
    }

    fn receive_with_limit(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let state = slf.borrow(py).state.clone();
        into_python_awaitable(
            py,
            BodyLimitReceiveMachine {
                state,
                pending: false,
            },
        )
    }

    fn send_with_limit(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let state = slf.borrow(py).state.clone();
        into_python_awaitable(
            py,
            BodyLimitSendMachine {
                state,
                message,
                pending: None,
            },
        )
    }
}

/// Per-middleware Python-loop entry point; arguments are read at each call so
/// public mutations of `app` and `max_body_size` remain observable.
#[pyclass(name = "RequestBodyLimitMiddlewareRuntime", unsendable)]
pub(crate) struct PyRequestBodyLimitMiddlewareRuntime;

#[pymethods]
impl PyRequestBodyLimitMiddlewareRuntime {
    #[new]
    fn new() -> Self {
        Self
    }

    fn __call__(
        &self,
        py: Python<'_>,
        app: Py<PyAny>,
        max_body_size: Py<PyAny>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            BodyLimitMiddlewareCall {
                app,
                max_body_size,
                scope,
                receive,
                send,
                pending: false,
            },
        )
    }
}

struct BodyLimitMiddlewareCall {
    app: Py<PyAny>,
    max_body_size: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for BodyLimitMiddlewareCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
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
                PyRuntimeError::new_err("request body limit middleware has no pending ASGI call"),
            ),
        }
    }
}

impl BodyLimitMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope_type = self.scope.bind(py).get_item("type")?;
        let is_http = scope_type
            .rich_compare("http", CompareOp::Eq)?
            .is_truthy()?;
        let awaitable = if is_http {
            let responder_type = py
                .import("starlette.middleware.body_limit")?
                .getattr("RequestBodyLimitResponder")?;
            let responder =
                responder_type.call1((self.app.bind(py), self.max_body_size.bind(py)))?;
            responder.call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?
        } else {
            self.app.bind(py).call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?
        };
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

enum BodyLimitCallPending {
    Application,
    ReplacementResponse,
}

struct BodyLimitCallMachine {
    responder: Py<PyRequestBodyLimitResponder>,
    state: SharedBodyLimitState,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: Option<BodyLimitCallPending>,
    nested: bool,
    cleanup_on_finish: bool,
    previous_scope_limit: Option<Py<PyAny>>,
    had_previous_scope_limit: bool,
}

impl AwaitableStateMachine for BodyLimitCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(_) => match self.pending.take() {
                Some(BodyLimitCallPending::Application) => {
                    self.cleanup(py)?;
                    Ok(MachineAction::Complete(py.None()))
                }
                Some(BodyLimitCallPending::ReplacementResponse) => {
                    self.cleanup(py)?;
                    Ok(MachineAction::Complete(py.None()))
                }
                None => Err(PyRuntimeError::new_err(
                    "request body limit call received an unexpected result",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(BodyLimitCallPending::Application) => self.application_error(py, error),
                Some(BodyLimitCallPending::ReplacementResponse) => self.cleanup_error(py, error),
                None => Err(error),
            },
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "request body limit middleware received an unexpected start signal",
            )),
        }
    }
}

impl BodyLimitCallMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let had_previous_scope_limit = scope
            .call_method1("__contains__", (MAX_BODY_SIZE_SCOPE_KEY,))?
            .is_truthy()?;
        let previous_scope_limit = if had_previous_scope_limit {
            Some(scope.get_item(MAX_BODY_SIZE_SCOPE_KEY)?.unbind())
        } else {
            None
        };
        let max_body_size = self.state.borrow().max_body_size.clone_ref(py);
        scope.set_item(MAX_BODY_SIZE_SCOPE_KEY, max_body_size.bind(py))?;

        let active_responder = scope.call_method1("get", (BODY_LIMIT_RESPONDER_SCOPE_KEY,))?;
        if !active_responder.is_none() {
            active_responder.setattr("max_body_size", max_body_size.bind(py))?;
            let total_size = active_responder.getattr("total_size")?;
            let current_limit = active_responder.getattr("max_body_size")?;
            if greater_than(&total_size, &current_limit)? {
                return Err(new_too_large_error(py, &self.state)?);
            }
            let app = self.state.borrow().app.clone_ref(py);
            let awaitable = app
                .bind(py)
                .call1((&self.scope, &self.receive, &self.send))?;
            self.nested = true;
            self.pending = Some(BodyLimitCallPending::Application);
            return Ok(MachineAction::Await(awaitable.unbind()));
        }

        {
            let mut state = self.state.borrow_mut();
            state.scope = Some(self.scope.clone_ref(py));
            state.receive = Some(self.receive.clone_ref(py));
            state.send = Some(self.send.clone_ref(py));
        }
        let content_length = get_content_length(py, scope)?;
        self.state.borrow_mut().content_length = content_length;
        scope.set_item(BODY_LIMIT_RESPONDER_SCOPE_KEY, &self.responder)?;

        self.previous_scope_limit = previous_scope_limit;
        self.had_previous_scope_limit = had_previous_scope_limit;
        self.cleanup_on_finish = true;

        let receive_with_limit = self.responder.bind(py).getattr("receive_with_limit")?;
        let send_with_limit = self.responder.bind(py).getattr("send_with_limit")?;
        let app = self.state.borrow().app.clone_ref(py);
        let awaitable = match app
            .bind(py)
            .call1((scope, receive_with_limit, send_with_limit))
        {
            Ok(awaitable) => awaitable,
            Err(error) => return self.cleanup_error(py, error),
        };
        self.pending = Some(BodyLimitCallPending::Application);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn application_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if self.nested {
            return Err(error);
        }
        if is_instance_of_error(py, &error, &self.state.borrow().response_sent_type)? {
            self.cleanup(py)?;
            return Ok(MachineAction::Complete(py.None()));
        }
        if is_instance_of_error(py, &error, &self.state.borrow().too_large_type)? {
            if self.state.borrow().response_started {
                return self.cleanup_error(py, error);
            }
            let replacement = replacement_response_call(py, &self.state)?;
            self.pending = Some(BodyLimitCallPending::ReplacementResponse);
            return Ok(MachineAction::Await(replacement));
        }
        self.cleanup_error(py, error)
    }

    fn cleanup(&mut self, py: Python<'_>) -> PyResult<()> {
        if !self.cleanup_on_finish {
            return Ok(());
        }
        let scope = self.scope.bind(py);
        scope.call_method1("pop", (BODY_LIMIT_RESPONDER_SCOPE_KEY, py.None()))?;
        if self.had_previous_scope_limit {
            let previous = self
                .previous_scope_limit
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("saved body limit is missing"))?;
            scope.set_item(MAX_BODY_SIZE_SCOPE_KEY, previous.bind(py))?;
        } else {
            scope.call_method1("pop", (MAX_BODY_SIZE_SCOPE_KEY, py.None()))?;
        }
        self.cleanup_on_finish = false;
        Ok(())
    }

    fn cleanup_error(&mut self, py: Python<'_>, original: PyErr) -> PyResult<MachineAction> {
        self.cleanup(py)?;
        Err(original)
    }
}

struct BodyLimitReceiveMachine {
    state: SharedBodyLimitState,
    pending: bool,
}

impl AwaitableStateMachine for BodyLimitReceiveMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(message) if self.pending => {
                self.pending = false;
                self.received(py, message)
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("request body limit receive has no pending receive"),
            ),
        }
    }
}

impl BodyLimitReceiveMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let (content_length, max_body_size, receive) = {
            let state = self.state.borrow();
            (
                state.content_length.clone_ref(py),
                state.max_body_size.clone_ref(py),
                required_callback(py, state.receive.as_ref())?,
            )
        };
        if !content_length.bind(py).is_none()
            && greater_than(content_length.bind(py), max_body_size.bind(py))?
        {
            return Err(new_too_large_error(py, &self.state)?);
        }
        let awaitable = receive.bind(py).call0()?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn received(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message = message.bind(py);
        let message_type = message.get_item("type")?;
        if message_type
            .rich_compare("http.request", CompareOp::Eq)?
            .is_truthy()?
        {
            let body = message.call_method1("get", ("body", b""))?;
            let body_length = PyInt::new(py, body.len()?).into_any();
            let previous_total = self.state.borrow().total_size.clone_ref(py);
            let total_size = py
                .import("operator")?
                .getattr("iadd")?
                .call1((previous_total.bind(py), &body_length))?;
            self.state.borrow_mut().total_size = total_size.clone().unbind();
            let max_body_size = self.state.borrow().max_body_size.clone_ref(py);
            if greater_than(&total_size, max_body_size.bind(py))? {
                return Err(new_too_large_error(py, &self.state)?);
            }
        }
        Ok(MachineAction::Complete(message.clone().unbind()))
    }
}

enum BodyLimitSendPending {
    RawSend,
    ReplacementResponse,
}

struct BodyLimitSendMachine {
    state: SharedBodyLimitState,
    message: Py<PyAny>,
    pending: Option<BodyLimitSendPending>,
}

impl AwaitableStateMachine for BodyLimitSendMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(_) => match self.pending.take() {
                Some(BodyLimitSendPending::RawSend) => Ok(MachineAction::Complete(py.None())),
                Some(BodyLimitSendPending::ReplacementResponse) => {
                    Err(new_response_sent_error(py, &self.state)?)
                }
                None => Err(PyRuntimeError::new_err(
                    "request body limit send received an unexpected result",
                )),
            },
            MachineResume::Error(error) => {
                self.pending = None;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "request body limit send received an unexpected start signal",
            )),
        }
    }
}

impl BodyLimitSendMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py);
        let message_type = message.get_item("type")?;
        if message_type
            .rich_compare("http.response.start", CompareOp::Eq)?
            .is_truthy()?
        {
            self.state.borrow_mut().response_started = true;
            let (content_length, max_body_size) = {
                let state = self.state.borrow();
                (
                    state.content_length.clone_ref(py),
                    state.max_body_size.clone_ref(py),
                )
            };
            if !content_length.bind(py).is_none()
                && greater_than(content_length.bind(py), max_body_size.bind(py))?
            {
                let replacement = replacement_response_call(py, &self.state)?;
                self.pending = Some(BodyLimitSendPending::ReplacementResponse);
                return Ok(MachineAction::Await(replacement));
            }
        }
        let send = self
            .state
            .borrow()
            .send
            .as_ref()
            .map(|callback| callback.clone_ref(py));
        let send = send.ok_or_else(|| PyAssertionError::new_err(""))?;
        let awaitable = send.bind(py).call1((&self.message,))?;
        self.pending = Some(BodyLimitSendPending::RawSend);
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn get_content_length(py: Python<'_>, scope: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let headers = scope.get_item("headers")?;
    let headers_list = py.import("builtins")?.getattr("list")?.call1((headers,))?;
    scope.set_item("headers", &headers_list)?;
    let int = py.import("builtins")?.getattr("int")?;
    for pair in headers_list.try_iter()? {
        let pair = pair?;
        let name = pair.get_item(0)?.call_method0("lower")?;
        if name
            .rich_compare(b"content-length", CompareOp::Eq)?
            .is_truthy()?
        {
            let value = pair.get_item(1)?.call_method1("decode", ("latin-1",))?;
            return match int.call1((value,)) {
                Ok(content_length) => Ok(content_length.unbind()),
                Err(error) if error.is_instance_of::<PyValueError>(py) => Ok(py.None()),
                Err(error) => Err(error),
            };
        }
    }
    Ok(py.None())
}

fn replacement_response_call(py: Python<'_>, state: &SharedBodyLimitState) -> PyResult<Py<PyAny>> {
    let (scope, receive, send) = {
        let state = state.borrow();
        (
            required_callback(py, state.scope.as_ref())?,
            required_callback(py, state.receive.as_ref())?,
            required_callback(py, state.send.as_ref())?,
        )
    };
    let scope = scope.bind(py).cast::<PyDict>()?;
    let response =
        Response::plain_text_with_status(REQUEST_BODY_LIMIT_STATUS_CODE, REQUEST_BODY_LIMIT_DETAIL);
    crate::runtime_calls::response_call(py, &response, scope, receive, send, None, None)
}

fn required_callback(py: Python<'_>, callback: Option<&Py<PyAny>>) -> PyResult<Py<PyAny>> {
    callback
        .map(|value| value.clone_ref(py))
        .ok_or_else(|| PyAssertionError::new_err(""))
}

fn greater_than(left: &Bound<'_, PyAny>, right: &Bound<'_, PyAny>) -> PyResult<bool> {
    left.rich_compare(right, CompareOp::Gt)?.is_truthy()
}

fn is_instance_of_error(
    py: Python<'_>,
    error: &PyErr,
    exception_type: &Py<PyAny>,
) -> PyResult<bool> {
    error.value(py).is_instance(exception_type.bind(py))
}

fn new_too_large_error(py: Python<'_>, state: &SharedBodyLimitState) -> PyResult<PyErr> {
    let exception_type = state.borrow().too_large_type.clone_ref(py);
    let kwargs = PyDict::new(py);
    kwargs.set_item("status_code", REQUEST_BODY_LIMIT_STATUS_CODE)?;
    kwargs.set_item("detail", REQUEST_BODY_LIMIT_DETAIL)?;
    exception_type
        .bind(py)
        .call((), Some(&kwargs))
        .map(PyErr::from_value)
}

fn new_response_sent_error(py: Python<'_>, state: &SharedBodyLimitState) -> PyResult<PyErr> {
    let exception_type = state.borrow().response_sent_type.clone_ref(py);
    exception_type.bind(py).call0().map(PyErr::from_value)
}
