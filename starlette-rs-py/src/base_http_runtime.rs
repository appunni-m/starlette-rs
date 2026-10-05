//! Rust-owned BaseHTTPMiddleware ASGI orchestration.
//!
//! Python dispatch and ASGI callbacks remain Python callables. Their awaitables
//! are driven by the active Python task through `PythonAwaitable`; AnyIO supplies
//! the backend-neutral task group and rendezvous streams used by `call_next`.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyAssertionError, PyKeyError, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
    into_python_awaitable_with_reuse_error, into_sendable_python_awaitable,
};

type SharedHeaders = Rc<RefCell<Vec<(Vec<u8>, Vec<u8>)>>>;
// Shared Python-owned nodes expose each owned reference once to Python GC.
// Callbacks may survive their portal thread through a propagated traceback.
type SharedCall = Py<BaseHTTPCallState>;
type SharedCachedRequest = Py<CachedRequestState>;
type BaseHTTPWrappedReceiveState = (Option<Py<PyAny>>, bool, bool, bool, bool);

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyBaseHTTPMiddlewareRuntime>()?;
    module.add_class::<PyBaseHTTPResponse>()?;
    module.add_class::<PyBaseHTTPHeaders>()?;
    module.add_class::<PyBaseHTTPBodyIterator>()?;
    module.add_class::<PyBaseHTTPCachedReceiveDescriptor>()?;
    module.add_function(wrap_pyfunction!(select_dispatch, module)?)?;
    module.add_function(wrap_pyfunction!(default_dispatch, module)?)?;
    Ok(())
}

/// Stateless PyO3 entry point. The ASGI protocol state belongs to each call.
#[pyclass(name = "BaseHTTPMiddlewareRuntime")]
pub(crate) struct PyBaseHTTPMiddlewareRuntime;

#[pymethods]
impl PyBaseHTTPMiddlewareRuntime {
    #[new]
    fn new() -> Self {
        Self
    }

    fn __call__(
        &self,
        py: Python<'_>,
        app: Py<PyAny>,
        dispatch: Py<PyAny>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            BaseHTTPCallMachine {
                app,
                dispatch,
                scope,
                receive,
                send,
                shared: None,
                pending: None,
            },
        )
    }
}

/// Select the explicit dispatch callback or the subclass's bound method.
#[pyfunction(name = "_base_http_select_dispatch")]
fn select_dispatch(
    py: Python<'_>,
    owner: Py<PyAny>,
    dispatch: Option<Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    match dispatch {
        Some(dispatch) => Ok(dispatch),
        None => owner.bind(py).getattr("dispatch").map(Bound::unbind),
    }
}

/// Produce the default `dispatch()` failure from Rust.
#[pyfunction(name = "_base_http_default_dispatch")]
fn default_dispatch(py: Python<'_>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(py, DefaultDispatchMachine)
}

struct DefaultDispatchMachine;

impl AwaitableStateMachine for DefaultDispatchMachine {
    fn resume(&mut self, _py: Python<'_>, _input: MachineResume) -> PyResult<MachineAction> {
        Err(pyo3::exceptions::PyNotImplementedError::new_err(()))
    }
}

/// Per-request state used by Starlette's `_CachedRequest.wrapped_receive` contract.
/// The Python `Request` remains the public request object so its existing body and
/// stream API can be called and awaited at the boundary; Rust owns the replay state
/// and selects each ASGI message.
#[pyclass]
struct CachedRequestState {
    request: Py<PyAny>,
    receive: Py<PyAny>,
}

#[pymethods]
impl CachedRequestState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.request)?;
        visit.call(&self.receive)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.request = py.None();
        self.receive = py.None();
    }
}

fn cached_request_and_receive(
    py: Python<'_>,
    scope: &Bound<'_, PyDict>,
    receive: Py<PyAny>,
) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let request_type = cached_request_type(py)?;
    // Inherited `Request.__init__` creates the one RequestBody used by its
    // public body()/stream() methods; the Rust callback reads this exact state.
    let request = request_type
        .bind(py)
        .call1((scope, receive.clone_ref(py)))?;

    request.setattr("_wrapped_rcv_disconnected", false)?;
    request.setattr("_wrapped_rcv_consumed", false)?;
    let callback = request.getattr("wrapped_receive")?.unbind();
    Ok((request.unbind(), callback))
}

fn cached_request_type(py: Python<'_>) -> PyResult<Py<PyAny>> {
    static CACHED_REQUEST_TYPE: PyOnceLock<Py<PyAny>> = PyOnceLock::new();
    CACHED_REQUEST_TYPE
        .get_or_try_init(py, || {
            // The compatibility Request uses slots and cannot hold a bound receive
            // callback. Upstream's private `_CachedRequest` subclass supplies that
            // attribute; this descriptor creates a Rust callback that retains the
            // request while keeping replay flags in the request's shared body state.
            let request_type = py.import("starlette.requests")?.getattr("Request")?;
            let bases = PyTuple::new(py, [request_type])?;
            let namespace = PyDict::new(py);
            namespace.set_item("__module__", "starlette.middleware.base")?;
            let descriptor = Py::new(py, PyBaseHTTPCachedReceiveDescriptor)?.into_any();
            namespace.set_item("wrapped_receive", descriptor)?;
            let request_type = py.import("builtins")?.getattr("type")?.call1((
                "_CachedRequest",
                bases,
                namespace,
            ))?;
            Ok(request_type.unbind())
        })
        .map(|request_type| request_type.clone_ref(py))
}

fn cached_request_object(py: Python<'_>, state: &SharedCachedRequest) -> PyResult<Py<PyAny>> {
    Ok(state.try_borrow(py)?.request.clone_ref(py))
}

fn set_cached_receive_flags(
    py: Python<'_>,
    state: &SharedCachedRequest,
    disconnected: Option<bool>,
    consumed: Option<bool>,
) -> PyResult<()> {
    let request = cached_request_object(py, state)?;
    if let Some(disconnected) = disconnected {
        request
            .bind(py)
            .setattr("_wrapped_rcv_disconnected", disconnected)?;
    }
    if let Some(consumed) = consumed {
        request
            .bind(py)
            .setattr("_wrapped_rcv_consumed", consumed)?;
    }
    request.bind(py).getattr("_body_state")?.call_method1(
        "_base_http_set_wrapped_receive_flags",
        (disconnected, consumed),
    )?;
    Ok(())
}

fn request_body_receive_state(request: &Bound<'_, PyAny>) -> PyResult<BaseHTTPWrappedReceiveState> {
    request
        .getattr("_body_state")?
        .call_method0("_base_http_wrapped_receive_state")?
        .extract()
}

#[pyclass(name = "_BaseHTTPCachedReceiveDescriptor")]
struct PyBaseHTTPCachedReceiveDescriptor;

#[pymethods]
impl PyBaseHTTPCachedReceiveDescriptor {
    fn __get__(
        slf: Py<Self>,
        py: Python<'_>,
        request: Py<PyAny>,
        _owner: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        if request.bind(py).is_none() {
            return Ok(slf.into_any());
        }
        let receive = request
            .bind(py)
            .getattr("_body_state")?
            .getattr("receive")?
            .unbind();
        Py::new(
            py,
            PyBaseHTTPCachedReceive {
                state: Py::new(py, CachedRequestState { request, receive })?,
            },
        )
        .map(Into::into)
    }
}

#[pyclass]
struct PyBaseHTTPCachedReceive {
    state: SharedCachedRequest,
}

#[pymethods]
impl PyBaseHTTPCachedReceive {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state)
    }

    fn __call__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            CachedRequestReceiveMachine {
                state: self.state.clone_ref(py),
                pending: None,
            },
        )
    }
}

enum CachedReceivePending {
    StreamChunk,
    ConsumedReceive,
}

struct CachedRequestReceiveMachine {
    state: SharedCachedRequest,
    pending: Option<CachedReceivePending>,
}

impl AwaitableStateMachine for CachedRequestReceiveMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(CachedReceivePending::StreamChunk) => self.stream_chunk(py, value),
                Some(CachedReceivePending::ConsumedReceive) => self.consumed_receive(py, value),
                None => Err(PyRuntimeError::new_err(
                    "cached request resumed without a pending receive",
                )),
            },
            MachineResume::Error(error) => self.receive_error(py, error),
            MachineResume::AsyncIterationComplete(error) => Err(error),
        }
    }
}

impl CachedRequestReceiveMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let request = cached_request_object(py, &self.state)?;
        let (body, stream_consumed, request_disconnected, disconnected, consumed) =
            request_body_receive_state(request.bind(py))?;
        if disconnected {
            return Ok(MachineAction::Complete(disconnect_message(py)?));
        }
        if consumed {
            if request_disconnected {
                set_cached_receive_flags(py, &self.state, Some(true), None)?;
                return Ok(MachineAction::Complete(disconnect_message(py)?));
            }
            return self.await_original_receive(py);
        }

        if let Some(body) = body {
            set_cached_receive_flags(py, &self.state, None, Some(true))?;
            return cached_request_message(py, body, false);
        }

        if stream_consumed {
            set_cached_receive_flags(py, &self.state, None, Some(true))?;
            return cached_request_message(py, PyBytes::new(py, b"").into_any().unbind(), false);
        }

        let stream = request.bind(py).call_method0("stream")?;
        let awaitable = stream.call_method0("__anext__")?;
        self.pending = Some(CachedReceivePending::StreamChunk);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn await_original_receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = self.state.try_borrow(py)?.receive.clone_ref(py);
        let awaitable = receive.bind(py).call0()?;
        self.pending = Some(CachedReceivePending::ConsumedReceive);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn stream_chunk(&mut self, py: Python<'_>, chunk: Py<PyAny>) -> PyResult<MachineAction> {
        let request = cached_request_object(py, &self.state)?;
        let (_, stream_consumed, _, _, _) = request_body_receive_state(request.bind(py))?;
        set_cached_receive_flags(py, &self.state, None, Some(stream_consumed))?;
        cached_request_message(py, chunk, !stream_consumed)
    }

    fn consumed_receive(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message_bound = message.bind(py).cast::<PyDict>()?;
        let message_type = message_bound
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if message_type != "http.disconnect" {
            return Err(PyRuntimeError::new_err(format!(
                "Unexpected message received: {message_type}"
            )));
        }
        set_cached_receive_flags(py, &self.state, Some(true), None)?;
        Ok(MachineAction::Complete(message))
    }

    fn receive_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(CachedReceivePending::StreamChunk) => {
                let client_disconnect = py
                    .import("starlette.requests")?
                    .getattr("ClientDisconnect")?;
                if error.value(py).is_instance(&client_disconnect)? {
                    set_cached_receive_flags(py, &self.state, Some(true), None)?;
                    return Ok(MachineAction::Complete(disconnect_message(py)?));
                }
                Err(error)
            }
            Some(CachedReceivePending::ConsumedReceive) | None => Err(error),
        }
    }
}

fn cached_request_message(
    py: Python<'_>,
    body: Py<PyAny>,
    more_body: bool,
) -> PyResult<MachineAction> {
    let message = PyDict::new(py);
    message.set_item("type", "http.request")?;
    message.set_item("body", body)?;
    message.set_item("more_body", more_body)?;
    Ok(MachineAction::Complete(message.into_any().unbind()))
}

#[pyclass]
struct BaseHTTPCallState {
    app: Py<PyAny>,
    scope: Py<PyAny>,
    request: Py<PyAny>,
    wrapped_receive: Py<PyAny>,
    send: Py<PyAny>,
    send_stream: Py<PyAny>,
    receive_stream: Py<PyAny>,
    response_sent: Py<PyAny>,
    task_group: Py<PyAny>,
    app_error: Option<Py<PyAny>>,
    exception_already_raised: bool,
}

#[pymethods]
impl BaseHTTPCallState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.scope)?;
        visit.call(&self.request)?;
        visit.call(&self.wrapped_receive)?;
        visit.call(&self.send)?;
        visit.call(&self.send_stream)?;
        visit.call(&self.receive_stream)?;
        visit.call(&self.response_sent)?;
        visit.call(&self.task_group)?;
        visit.call(&self.app_error)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
        self.scope = py.None();
        self.request = py.None();
        self.wrapped_receive = py.None();
        self.send = py.None();
        self.send_stream = py.None();
        self.receive_stream = py.None();
        self.response_sent = py.None();
        self.task_group = py.None();
        self.app_error = None;
    }
}

impl BaseHTTPCallState {
    fn clone_app(&self, py: Python<'_>) -> Py<PyAny> {
        self.app.clone_ref(py)
    }

    fn clone_scope(&self, py: Python<'_>) -> Py<PyAny> {
        self.scope.clone_ref(py)
    }

    fn clone_request(&self, py: Python<'_>) -> Py<PyAny> {
        self.request.clone_ref(py)
    }

    fn clone_wrapped_receive(&self, py: Python<'_>) -> Py<PyAny> {
        self.wrapped_receive.clone_ref(py)
    }

    fn clone_send(&self, py: Python<'_>) -> Py<PyAny> {
        self.send.clone_ref(py)
    }

    fn clone_send_stream(&self, py: Python<'_>) -> Py<PyAny> {
        self.send_stream.clone_ref(py)
    }

    fn clone_receive_stream(&self, py: Python<'_>) -> Py<PyAny> {
        self.receive_stream.clone_ref(py)
    }

    fn clone_response_sent(&self, py: Python<'_>) -> Py<PyAny> {
        self.response_sent.clone_ref(py)
    }

    fn clone_task_group(&self, py: Python<'_>) -> Py<PyAny> {
        self.task_group.clone_ref(py)
    }

    fn record_app_error(&mut self, py: Python<'_>, error: PyErr) -> Option<Py<PyAny>> {
        self.app_error
            .replace(error.value(py).clone().into_any().unbind())
    }
}

enum BaseHTTPPending {
    PassThrough,
    TaskGroupEnter,
    Dispatch,
    Response,
    TaskGroupExit { body_error: Option<PyErr> },
}

struct BaseHTTPCallMachine {
    app: Py<PyAny>,
    dispatch: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    shared: Option<SharedCall>,
    pending: Option<BaseHTTPPending>,
}

impl AwaitableStateMachine for BaseHTTPCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(BaseHTTPPending::PassThrough) => Ok(MachineAction::Complete(value)),
                Some(BaseHTTPPending::TaskGroupEnter) => self.start_dispatch(py),
                Some(BaseHTTPPending::Dispatch) => self.call_response(py, value),
                Some(BaseHTTPPending::Response) => self.finish_response(py),
                Some(BaseHTTPPending::TaskGroupExit { body_error }) => {
                    let suppressed = value.bind(py).is_truthy()?;
                    self.finish_task_group(py, body_error, suppressed)
                }
                None => Err(PyRuntimeError::new_err(
                    "BaseHTTPMiddleware resumed without a pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete(error) => self.resume_error(py, error),
            MachineResume::Error(error) => self.resume_error(py, error),
        }
    }
}

impl BaseHTTPCallMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if scope_type != "http" {
            let call = self
                .app
                .bind(py)
                .call1((scope, &self.receive, &self.send))?;
            self.pending = Some(BaseHTTPPending::PassThrough);
            return Ok(MachineAction::Await(call.unbind()));
        }

        let (request, wrapped_receive) =
            cached_request_and_receive(py, scope, self.receive.clone_ref(py))?;

        let streams = py.import("anyio")?.getattr("create_memory_object_stream")?;
        let (send_stream, receive_stream) = streams.call0()?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
        let response_sent = py.import("anyio")?.getattr("Event")?.call0()?.unbind();
        let task_group = py.import("anyio")?.getattr("create_task_group")?.call0()?;
        let enter = task_group.call_method0("__aenter__")?;
        let shared = Py::new(
            py,
            BaseHTTPCallState {
                app: self.app.clone_ref(py),
                scope: self.scope.clone_ref(py),
                request,
                wrapped_receive,
                send: self.send.clone_ref(py),
                send_stream,
                receive_stream,
                response_sent,
                task_group: task_group.unbind(),
                app_error: None,
                exception_already_raised: false,
            },
        )?;
        self.shared = Some(shared);
        self.pending = Some(BaseHTTPPending::TaskGroupEnter);
        Ok(MachineAction::Await(enter.unbind()))
    }

    fn start_dispatch(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let shared = self.shared_ref()?.clone_ref(py);
        let request = {
            let state = shared.try_borrow(py)?;
            state.clone_request(py)
        };
        let call_next = Py::new(py, PyBaseHTTPCallNext { shared })?.into_any();
        let dispatch = self.dispatch.bind(py).call1((request, call_next))?;
        self.pending = Some(BaseHTTPPending::Dispatch);
        Ok(MachineAction::Await(dispatch.unbind()))
    }

    fn call_response(&mut self, py: Python<'_>, response: Py<PyAny>) -> PyResult<MachineAction> {
        let shared = self.shared_ref()?.clone_ref(py);
        let (scope, receive, send) = {
            let state = shared.try_borrow(py)?;
            (
                state.clone_scope(py),
                state.clone_wrapped_receive(py),
                state.clone_send(py),
            )
        };
        let awaitable = match response.bind(py).call1((scope, receive, send)) {
            Ok(awaitable) => awaitable,
            Err(error) => return self.finish_with_error(py, error),
        };
        self.pending = Some(BaseHTTPPending::Response);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_response(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let shared = self.shared_ref()?.clone_ref(py);
        let event = shared.try_borrow(py)?.clone_response_sent(py);
        event.bind(py).call_method0("set")?;
        self.finish_success(py)
    }

    fn finish_success(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let shared = self.shared_ref()?.clone_ref(py);
        close_receive_stream(py, &shared)?;
        let group = shared.try_borrow(py)?.clone_task_group(py);
        let awaitable = group
            .bind(py)
            .call_method1("__aexit__", (py.None(), py.None(), py.None()))?;
        self.pending = Some(BaseHTTPPending::TaskGroupExit { body_error: None });
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_with_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let shared = self.shared_ref()?.clone_ref(py);
        close_receive_stream(py, &shared)?;
        let group = shared.try_borrow(py)?.clone_task_group(py);
        let traceback = error
            .traceback(py)
            .map_or_else(|| py.None().into_bound(py), Bound::into_any);
        let awaitable = group.bind(py).call_method1(
            "__aexit__",
            (error.get_type(py), error.value(py), traceback),
        )?;
        self.pending = Some(BaseHTTPPending::TaskGroupExit {
            body_error: Some(error),
        });
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_task_group(
        &mut self,
        py: Python<'_>,
        body_error: Option<PyErr>,
        suppressed: bool,
    ) -> PyResult<MachineAction> {
        if let Some(error) = body_error {
            if !suppressed {
                close_streams(py, &self.shared_ref()?.clone_ref(py))?;
                return Err(crate::runtime_calls::collapse_single_task_group_error(
                    py, error,
                )?);
            }
        }

        let shared = self.shared_ref()?.clone_ref(py);
        close_streams(py, &shared)?;
        let error = {
            let mut state = shared.try_borrow_mut(py)?;
            if state.exception_already_raised {
                None
            } else {
                state.app_error.take()
            }
        };
        match error {
            Some(error) => Err(PyErr::from_value(error.into_bound(py))),
            None => Ok(MachineAction::Complete(py.None())),
        }
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(BaseHTTPPending::PassThrough) => Err(error),
            Some(BaseHTTPPending::TaskGroupEnter) => {
                if let Some(shared) = self.shared.as_ref() {
                    close_streams(py, shared)?;
                }
                Err(error)
            }
            Some(BaseHTTPPending::TaskGroupExit { body_error }) => {
                let _ = body_error;
                close_streams(py, &self.shared_ref()?.clone_ref(py))?;
                Err(crate::runtime_calls::collapse_single_task_group_error(
                    py, error,
                )?)
            }
            Some(BaseHTTPPending::Dispatch | BaseHTTPPending::Response) => {
                self.finish_with_error(py, error)
            }
            None => Err(error),
        }
    }

    fn shared_ref(&self) -> PyResult<&SharedCall> {
        self.shared
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("BaseHTTPMiddleware state is unavailable"))
    }
}

fn close_receive_stream(py: Python<'_>, shared: &SharedCall) -> PyResult<()> {
    let receive_stream = shared.try_borrow(py)?.clone_receive_stream(py);
    receive_stream.bind(py).call_method0("close")?;
    Ok(())
}

fn close_streams(py: Python<'_>, shared: &SharedCall) -> PyResult<()> {
    let send_stream = shared.try_borrow(py)?.clone_send_stream(py);
    send_stream.bind(py).call_method0("close")?;
    close_receive_stream(py, shared)
}

#[pyclass]
struct PyBaseHTTPCallNext {
    shared: SharedCall,
}

#[pymethods]
impl PyBaseHTTPCallNext {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

    fn __call__(&self, py: Python<'_>, _request: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            CallNextMachine {
                shared: self.shared.clone_ref(py),
                pending_receive: false,
                info: None,
                debug_skipped: false,
            },
        )
    }
}

struct CallNextMachine {
    shared: SharedCall,
    pending_receive: bool,
    info: Option<Py<PyAny>>,
    debug_skipped: bool,
}

impl AwaitableStateMachine for CallNextMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) if self.pending_receive => {
                self.pending_receive = false;
                self.make_response(py, message)
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "call_next received an unexpected result",
            )),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                self.receive_error(py, error)
            }
        }
    }
}

impl CallNextMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let task_group = self.shared.try_borrow(py)?.clone_task_group(py);
        let child = into_sendable_python_awaitable(
            py,
            DownstreamAppMachine {
                shared: self.shared.clone_ref(py),
                pending: false,
            },
        )?;
        let factory = Py::new(py, AwaitableFactory { awaitable: child })?;
        task_group.bind(py).call_method1("start_soon", (factory,))?;
        self.receive_first_message(py)
    }

    fn receive_first_message(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let stream = self.shared.try_borrow(py)?.clone_receive_stream(py);
        let awaitable = stream.bind(py).call_method0("receive")?;
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn make_response(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message_bound = message.bind(py).cast::<PyDict>()?;
        let info = match message_bound.get_item("info")? {
            Some(info) if !info.is_none() => Some(info.unbind()),
            _ => None,
        };
        let message_type = message_bound
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if message_type == "http.response.debug" && info.is_some() && !self.debug_skipped {
            self.info = info;
            self.debug_skipped = true;
            return self.receive_after_debug(py);
        }
        if message_type != "http.response.start" {
            return Err(PyAssertionError::new_err(format!(
                "Unexpected message: {}",
                message_bound.repr()?.extract::<String>()?
            )));
        }
        let status_code = message_bound
            .get_item("status")?
            .ok_or_else(|| PyKeyError::new_err("status"))?
            .extract::<u16>()?;
        let raw_headers = message_bound
            .get_item("headers")?
            .ok_or_else(|| PyKeyError::new_err("headers"))?
            .extract::<Vec<(Vec<u8>, Vec<u8>)>>()?;
        let stream = self.shared.try_borrow(py)?.clone_receive_stream(py);
        let response_info = self.info.take().or(info);
        let response = Py::new(
            py,
            PyBaseHTTPResponse::new(status_code, raw_headers, response_info, stream),
        )?;
        let wrapper = py
            .import("starlette.middleware.base")?
            .getattr("_StreamingResponse")?
            .call1((response,))?;
        Ok(MachineAction::Complete(wrapper.unbind()))
    }

    fn receive_after_debug(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let stream = self.shared.try_borrow(py)?.clone_receive_stream(py);
        let awaitable = stream.bind(py).call_method0("receive")?;
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn receive_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if !is_end_of_stream(py, &error)? {
            return Err(error);
        }
        let (app_error, receive_stream) = {
            let mut state = self.shared.try_borrow_mut(py)?;
            (state.app_error.take(), state.receive_stream.clone_ref(py))
        };
        if let Some(app_error) = app_error {
            self.shared.try_borrow_mut(py)?.exception_already_raised = true;
            Err(preserve_application_exception(
                py,
                PyErr::from_value(app_error.into_bound(py)),
                &error,
            )?)
        } else {
            let _ = receive_stream;
            let missing_response = PyRuntimeError::new_err("No response returned.");
            // Python raises this error inside `except EndOfStream`; preserve
            // that implicit context so task-group collapse retains its cause.
            missing_response.set_context(py, Some(error));
            Err(missing_response)
        }
    }
}

#[pyclass]
struct AwaitableFactory {
    awaitable: Py<PyAny>,
}

#[pymethods]
impl AwaitableFactory {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.awaitable)
    }

    fn __call__(&self, py: Python<'_>) -> Py<PyAny> {
        self.awaitable.clone_ref(py)
    }
}

struct DownstreamAppMachine {
    shared: SharedCall,
    pending: bool,
}

impl AwaitableStateMachine for DownstreamAppMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                self.close_sender(py)?;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "downstream app received an unexpected result",
            )),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                self.handle_error(py, error)
            }
        }
    }
}

impl DownstreamAppMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let (app, scope, receive, send) = {
            let state = self.shared.try_borrow(py)?;
            (
                state.clone_app(py),
                state.clone_scope(py),
                Py::new(
                    py,
                    PyBaseHTTPReceiveOrDisconnect {
                        shared: self.shared.clone_ref(py),
                    },
                )?
                .into_any(),
                Py::new(
                    py,
                    PyBaseHTTPSendNoError {
                        shared: self.shared.clone_ref(py),
                    },
                )?
                .into_any(),
            )
        };
        let awaitable = match app.bind(py).call1((scope, receive, send)) {
            Ok(awaitable) => awaitable,
            Err(error) => return self.handle_error(py, error),
        };
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn handle_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        self.close_sender(py)?;
        if error.is_instance_of::<pyo3::exceptions::PyException>(py) {
            let previous = self.shared.try_borrow_mut(py)?.record_app_error(py, error);
            // Drop replaced Python values after the mutable borrow is released.
            drop(previous);
            Ok(MachineAction::Complete(py.None()))
        } else {
            Err(error)
        }
    }

    fn close_sender(&self, py: Python<'_>) -> PyResult<()> {
        let stream = self.shared.try_borrow(py)?.clone_send_stream(py);
        stream.bind(py).call_method0("close")?;
        Ok(())
    }
}

#[pyclass]
struct PyBaseHTTPReceiveOrDisconnect {
    shared: SharedCall,
}

#[pymethods]
impl PyBaseHTTPReceiveOrDisconnect {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

    fn __call__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            ReceiveOrDisconnectMachine {
                shared: self.shared.clone_ref(py),
                task_group: None,
                pending: None,
            },
        )
    }
}

struct ReceiveOrDisconnectMachine {
    shared: SharedCall,
    task_group: Option<Py<PyAny>>,
    pending: Option<ReceiveOrDisconnectPending>,
}

enum ReceiveOrDisconnectPending {
    TaskGroupEnter,
    Receive,
    TaskGroupExit {
        received: Option<Py<PyAny>>,
        body_error: Option<PyErr>,
    },
}

impl AwaitableStateMachine for ReceiveOrDisconnectMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(ReceiveOrDisconnectPending::TaskGroupEnter) => self.start_race(py),
                Some(ReceiveOrDisconnectPending::Receive) => self.finish_receive(py, Ok(value)),
                Some(ReceiveOrDisconnectPending::TaskGroupExit {
                    received,
                    body_error,
                }) => self.finish_task_group(py, received, body_error, value),
                None => Err(PyRuntimeError::new_err(
                    "receive callback completed without a pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(ReceiveOrDisconnectPending::TaskGroupEnter) => Err(error),
                Some(ReceiveOrDisconnectPending::Receive) => self.finish_receive(py, Err(error)),
                Some(ReceiveOrDisconnectPending::TaskGroupExit {
                    body_error: Some(_),
                    ..
                }) => Err(crate::runtime_calls::collapse_single_task_group_error(
                    py, error,
                )?),
                Some(ReceiveOrDisconnectPending::TaskGroupExit { .. }) | None => Err(error),
            },
            MachineResume::AsyncIterationComplete(error) => match self.pending.take() {
                Some(ReceiveOrDisconnectPending::Receive) => self.finish_receive(py, Err(error)),
                _ => Err(error),
            },
        }
    }
}

impl ReceiveOrDisconnectMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let event = self.shared.try_borrow(py)?.clone_response_sent(py);
        if event.bind(py).call_method0("is_set")?.extract::<bool>()? {
            return Ok(MachineAction::Complete(disconnect_message(py)?));
        }

        let task_group = py.import("anyio")?.getattr("create_task_group")?.call0()?;
        let enter = task_group.call_method0("__aenter__")?;
        self.task_group = Some(task_group.unbind());
        self.pending = Some(ReceiveOrDisconnectPending::TaskGroupEnter);
        Ok(MachineAction::Await(enter.unbind()))
    }

    fn start_race(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let event = self.shared.try_borrow(py)?.clone_response_sent(py);
        let cancel_scope = self.task_group_ref(py)?.getattr("cancel_scope")?.unbind();
        let child = into_sendable_python_awaitable(
            py,
            ResponseSentWaiterMachine {
                event,
                cancel_scope,
                pending: false,
            },
        )?;
        let factory = Py::new(py, AwaitableFactory { awaitable: child })?;
        if let Err(error) = self
            .task_group_ref(py)?
            .call_method1("start_soon", (factory,))
        {
            return self.leave_task_group(py, None, Some(error));
        }

        let receive = self.shared.try_borrow(py)?.clone_wrapped_receive(py);
        let awaitable = match receive.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => return self.leave_task_group(py, None, Some(error)),
        };
        self.pending = Some(ReceiveOrDisconnectPending::Receive);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_receive(
        &mut self,
        py: Python<'_>,
        result: Result<Py<PyAny>, PyErr>,
    ) -> PyResult<MachineAction> {
        match result {
            Ok(received) => {
                if let Err(error) = self.cancel_task_group(py) {
                    return self.leave_task_group(py, None, Some(error));
                }
                self.leave_task_group(py, Some(received), None)
            }
            Err(error) => self.leave_task_group(py, None, Some(error)),
        }
    }

    fn leave_task_group(
        &mut self,
        py: Python<'_>,
        received: Option<Py<PyAny>>,
        body_error: Option<PyErr>,
    ) -> PyResult<MachineAction> {
        let task_group = self.task_group_ref(py)?;
        let awaitable = match body_error.as_ref() {
            Some(error) => {
                let traceback = error
                    .traceback(py)
                    .map_or_else(|| py.None().into_bound(py), Bound::into_any);
                task_group.call_method1(
                    "__aexit__",
                    (error.get_type(py), error.value(py), traceback),
                )?
            }
            None => task_group.call_method1("__aexit__", (py.None(), py.None(), py.None()))?,
        };
        self.pending = Some(ReceiveOrDisconnectPending::TaskGroupExit {
            received,
            body_error,
        });
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_task_group(
        &mut self,
        py: Python<'_>,
        received: Option<Py<PyAny>>,
        body_error: Option<PyErr>,
        suppressed: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        if let Some(error) = body_error {
            let suppressed = suppressed.bind(py).is_truthy()?;
            let event = self.shared.try_borrow(py)?.clone_response_sent(py);
            if suppressed && event.bind(py).call_method0("is_set")?.extract::<bool>()? {
                return Ok(MachineAction::Complete(disconnect_message(py)?));
            }
            return Err(error);
        }

        let event = self.shared.try_borrow(py)?.clone_response_sent(py);
        if event.bind(py).call_method0("is_set")?.extract::<bool>()? {
            return Ok(MachineAction::Complete(disconnect_message(py)?));
        }
        received
            .map(MachineAction::Complete)
            .ok_or_else(|| PyRuntimeError::new_err("receive race completed without a message"))
    }

    fn cancel_task_group(&self, py: Python<'_>) -> PyResult<()> {
        self.task_group_ref(py)?
            .getattr("cancel_scope")?
            .call_method0("cancel")?;
        Ok(())
    }

    fn task_group_ref<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.task_group
            .as_ref()
            .map(|task_group| task_group.bind(py).clone())
            .ok_or_else(|| PyRuntimeError::new_err("receive race task group was not initialized"))
    }
}

struct ResponseSentWaiterMachine {
    event: Py<PyAny>,
    cancel_scope: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for ResponseSentWaiterMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                let wait = self.event.bind(py).call_method0("wait")?;
                self.pending = true;
                Ok(MachineAction::Await(wait.unbind()))
            }
            MachineResume::Value(value) if self.pending => {
                self.pending = false;
                self.cancel_scope.bind(py).call_method0("cancel")?;
                Ok(MachineAction::Complete(value))
            }
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
            _ => Err(PyRuntimeError::new_err(
                "response completion waiter resumed without a pending wait",
            )),
        }
    }
}

#[pyclass]
struct PyBaseHTTPSendNoError {
    shared: SharedCall,
}

#[pymethods]
impl PyBaseHTTPSendNoError {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

    fn __call__(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            SendNoErrorMachine {
                stream: self.shared.try_borrow(py)?.clone_send_stream(py),
                message,
                pending: false,
            },
        )
    }
}

struct SendNoErrorMachine {
    stream: Py<PyAny>,
    message: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for SendNoErrorMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let awaitable = self
                    .stream
                    .bind(py)
                    .call_method1("send", (self.message.bind(py),))?;
                self.pending = true;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            MachineResume::Value(_) if self.pending => Ok(MachineAction::Complete(py.None())),
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "send stream completed without a pending send",
            )),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                if is_broken_resource(py, &error)? {
                    Ok(MachineAction::Complete(py.None()))
                } else {
                    Err(error)
                }
            }
        }
    }
}

#[pyclass(unsendable)]
pub(crate) struct PyBaseHTTPResponse {
    status_code: u16,
    headers: SharedHeaders,
    info: Option<Py<PyAny>>,
    receive_stream: Py<PyAny>,
}

impl PyBaseHTTPResponse {
    fn new(
        status_code: u16,
        raw_headers: Vec<(Vec<u8>, Vec<u8>)>,
        info: Option<Py<PyAny>>,
        receive_stream: Py<PyAny>,
    ) -> Self {
        Self {
            status_code,
            headers: Rc::new(RefCell::new(raw_headers)),
            info,
            receive_stream,
        }
    }
}

#[pymethods]
impl PyBaseHTTPResponse {
    #[getter]
    fn status_code(&self) -> u16 {
        self.status_code
    }

    #[setter]
    fn set_status_code(&mut self, status_code: u16) {
        self.status_code = status_code;
    }

    #[getter]
    fn raw_headers(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        raw_headers_to_python(py, &self.headers)
    }

    #[setter]
    fn set_raw_headers(&mut self, value: Vec<(Vec<u8>, Vec<u8>)>) {
        *self.headers.borrow_mut() = value;
    }

    #[getter]
    fn headers(&self, py: Python<'_>) -> PyResult<Py<PyBaseHTTPHeaders>> {
        Py::new(
            py,
            PyBaseHTTPHeaders {
                values: self.headers.clone(),
            },
        )
    }

    #[getter]
    fn info(&self, py: Python<'_>) -> Py<PyAny> {
        self.info
            .as_ref()
            .map_or_else(|| py.None(), |info| info.clone_ref(py))
    }

    #[getter]
    fn body_iterator(&self, py: Python<'_>) -> PyResult<Py<PyBaseHTTPBodyIterator>> {
        Py::new(
            py,
            PyBaseHTTPBodyIterator {
                receive_stream: self.receive_stream.clone_ref(py),
                finished: Rc::new(RefCell::new(false)),
                pending: Rc::new(RefCell::new(false)),
            },
        )
    }

    fn asgi_call(
        &self,
        py: Python<'_>,
        _scope: Py<PyAny>,
        _receive: Py<PyAny>,
        send: Py<PyAny>,
        background: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            BaseHTTPResponseCallMachine {
                status_code: self.status_code,
                headers: self.headers.clone(),
                info: self.info.as_ref().map(|value| value.clone_ref(py)),
                receive_stream: self.receive_stream.clone_ref(py),
                send,
                background: if background.bind(py).is_none() {
                    None
                } else {
                    Some(background)
                },
                phase: ResponsePhase::Start,
                pending: None,
                debug_sent: false,
            },
        )
    }
}

#[pyclass(unsendable)]
struct PyBaseHTTPHeaders {
    values: SharedHeaders,
}

#[pymethods]
impl PyBaseHTTPHeaders {
    fn __getitem__(&self, py: Python<'_>, key: &str) -> PyResult<Py<PyAny>> {
        let key = key.to_ascii_lowercase().into_bytes();
        let values = self.values.borrow();
        let value = values
            .iter()
            .rev()
            .find(|(name, _)| name.eq_ignore_ascii_case(&key))
            .map(|(_, value)| value)
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(key_to_string(&key)))?;
        PyBytes::new(py, value)
            .call_method1("decode", ("latin-1",))
            .map(Bound::unbind)
    }

    fn __setitem__(&self, py: Python<'_>, key: &str, value: &str) -> PyResult<()> {
        let key = key.to_ascii_lowercase().into_bytes();
        let value = PyString::new(py, value)
            .call_method1("encode", ("latin-1",))?
            .extract::<Vec<u8>>()?;
        let mut values = self.values.borrow_mut();
        if let Some(first) = values
            .iter()
            .position(|(name, _)| name.eq_ignore_ascii_case(&key))
        {
            let replaced_key = values[first].0.clone();
            values[first] = (key, value);
            let mut index = first + 1;
            while index < values.len() {
                if values[index].0.eq_ignore_ascii_case(&replaced_key) {
                    values.remove(index);
                } else {
                    index += 1;
                }
            }
        } else {
            values.push((key, value));
        }
        Ok(())
    }

    fn __delitem__(&self, key: &str) -> PyResult<()> {
        let key = key.to_ascii_lowercase().into_bytes();
        let mut values = self.values.borrow_mut();
        let old_len = values.len();
        values.retain(|(name, _)| !name.eq_ignore_ascii_case(&key));
        if old_len == values.len() {
            return Err(pyo3::exceptions::PyKeyError::new_err(key_to_string(&key)));
        }
        Ok(())
    }

    fn __contains__(&self, key: &str) -> bool {
        let key = key.to_ascii_lowercase().into_bytes();
        self.values
            .borrow()
            .iter()
            .any(|(name, _)| name.eq_ignore_ascii_case(&key))
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let values = self.values.borrow();
        let mut keys = Vec::<String>::new();
        for (name, _) in values.iter() {
            let key = String::from_utf8_lossy(name).to_ascii_lowercase();
            if !keys.iter().any(|candidate| candidate == &key) {
                keys.push(key);
            }
        }
        PyList::new(py, keys)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __len__(&self) -> usize {
        let values = self.values.borrow();
        let mut keys = Vec::<Vec<u8>>::new();
        for (name, _) in values.iter() {
            if !keys
                .iter()
                .any(|candidate| candidate.eq_ignore_ascii_case(name))
            {
                keys.push(name.clone());
            }
        }
        keys.len()
    }

    fn items(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let values = self.values.borrow();
        let result = PyList::empty(py);
        let mut keys = Vec::<Vec<u8>>::new();
        for (name, value) in values.iter() {
            if keys
                .iter()
                .any(|candidate| candidate.eq_ignore_ascii_case(name))
            {
                continue;
            }
            keys.push(name.clone());
            let pair = PyTuple::new(
                py,
                [
                    PyBytes::new(py, name).call_method1("decode", ("latin-1",))?,
                    PyBytes::new(py, value).call_method1("decode", ("latin-1",))?,
                ],
            )?;
            result.append(pair)?;
        }
        Ok(result.into_any().unbind())
    }
}

#[pyclass(unsendable)]
pub(crate) struct PyBaseHTTPBodyIterator {
    receive_stream: Py<PyAny>,
    finished: Rc<RefCell<bool>>,
    pending: Rc<RefCell<bool>>,
}

#[pymethods]
impl PyBaseHTTPBodyIterator {
    fn __aiter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __anext__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let receive_stream = borrowed.receive_stream.clone_ref(py);
        let finished = borrowed.finished.clone();
        let pending = borrowed.pending.clone();
        drop(borrowed);
        into_python_awaitable(
            py,
            BodyIteratorMachine {
                receive_stream,
                finished,
                pending,
                waiting: false,
            },
        )
    }

    fn aclose(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let finished = borrowed.finished.clone();
        let pending = borrowed.pending.clone();
        drop(borrowed);
        into_python_awaitable_with_reuse_error(
            py,
            BodyIteratorCloseMachine { finished, pending },
            "cannot reuse already awaited aclose()/athrow()",
        )
    }
}

/// Close the Rust-backed equivalent of Starlette's `body_stream` async generator.
///
/// Closing a suspended async generator marks only that generator complete; the
/// owning BaseHTTP call closes the memory streams when its response finishes.
/// The iterator can be closed only when an `__anext__` call is not currently
/// awaiting a message, matching Python's asynchronous-generator protocol.
struct BodyIteratorCloseMachine {
    finished: Rc<RefCell<bool>>,
    pending: Rc<RefCell<bool>>,
}

impl AwaitableStateMachine for BodyIteratorCloseMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if *self.pending.borrow() {
                    return Err(PyRuntimeError::new_err(
                        "aclose(): asynchronous generator is already running",
                    ));
                }
                *self.finished.borrow_mut() = true;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }
}

struct BodyIteratorMachine {
    receive_stream: Py<PyAny>,
    finished: Rc<RefCell<bool>>,
    pending: Rc<RefCell<bool>>,
    waiting: bool,
}

impl AwaitableStateMachine for BodyIteratorMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.receive(py),
            MachineResume::Value(message) if self.waiting => {
                self.waiting = false;
                *self.pending.borrow_mut() = false;
                let message = message.bind(py).cast::<PyDict>()?;
                let message_type = message
                    .get_item("type")?
                    .ok_or_else(|| PyKeyError::new_err("type"))?
                    .extract::<String>()?;
                if message_type == "http.response.pathsend" {
                    *self.finished.borrow_mut() = true;
                    return Ok(MachineAction::Complete(message.clone().into_any().unbind()));
                }
                if message_type != "http.response.body" {
                    return Err(PyAssertionError::new_err(format!(
                        "Unexpected message: {}",
                        message.repr()?.extract::<String>()?
                    )));
                }
                let body = message
                    .get_item("body")?
                    .unwrap_or_else(|| PyBytes::new(py, b"").into_any());
                let more_body = message
                    .get_item("more_body")?
                    .map(|value| value.extract::<bool>())
                    .transpose()?
                    .unwrap_or(false);
                if !more_body {
                    *self.finished.borrow_mut() = true;
                }
                if body.is_truthy()? {
                    return Ok(MachineAction::Complete(body.unbind()));
                }
                if more_body {
                    self.receive(py)
                } else {
                    Err(PyStopAsyncIteration::new_err(()))
                }
            }
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                if self.waiting && is_end_of_stream(py, &error)? {
                    *self.finished.borrow_mut() = true;
                    *self.pending.borrow_mut() = false;
                    Err(PyStopAsyncIteration::new_err(()))
                } else {
                    Err(error)
                }
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "body stream received an unexpected result",
            )),
        }
    }
}

impl BodyIteratorMachine {
    fn receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if *self.finished.borrow() {
            return Err(PyStopAsyncIteration::new_err(()));
        }
        let awaitable = self.receive_stream.bind(py).call_method0("receive")?;
        self.waiting = true;
        *self.pending.borrow_mut() = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[derive(Clone, Copy)]
enum ResponsePhase {
    Start,
    ReceiveBody,
    FinishBody,
    Complete,
}

enum ResponsePending {
    SendDebug,
    SendStart,
    ReceiveBody,
    SendChunk { more_body: bool },
    SendFinal,
    SendPathsend,
    RunBackground,
}

struct BaseHTTPResponseCallMachine {
    status_code: u16,
    headers: SharedHeaders,
    info: Option<Py<PyAny>>,
    receive_stream: Py<PyAny>,
    send: Py<PyAny>,
    background: Option<Py<PyAny>>,
    phase: ResponsePhase,
    pending: Option<ResponsePending>,
    debug_sent: bool,
}

impl AwaitableStateMachine for BaseHTTPResponseCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(ResponsePending::SendDebug) => {
                    self.debug_sent = true;
                    self.phase = ResponsePhase::Start;
                    self.next_action(py)
                }
                Some(ResponsePending::SendStart) => {
                    self.phase = ResponsePhase::ReceiveBody;
                    self.next_action(py)
                }
                Some(ResponsePending::ReceiveBody) => self.process_body_message(py, value),
                Some(ResponsePending::SendChunk { more_body }) => {
                    if more_body {
                        self.phase = ResponsePhase::ReceiveBody;
                        self.next_action(py)
                    } else {
                        self.phase = ResponsePhase::FinishBody;
                        self.next_action(py)
                    }
                }
                Some(ResponsePending::SendFinal) | Some(ResponsePending::SendPathsend) => {
                    self.finish_response(py)
                }
                Some(ResponsePending::RunBackground) => {
                    self.phase = ResponsePhase::Complete;
                    self.next_action(py)
                }
                None => Err(PyRuntimeError::new_err(
                    "BaseHTTP response resumed without a pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                match self.pending.take() {
                    Some(ResponsePending::ReceiveBody) if is_end_of_stream(py, &error)? => {
                        self.phase = ResponsePhase::FinishBody;
                        self.next_action(py)
                    }
                    Some(_) | None => Err(error),
                }
            }
        }
    }
}

impl BaseHTTPResponseCallMachine {
    fn finish_response(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let Some(background) = self.background.as_ref() else {
            self.phase = ResponsePhase::Complete;
            return self.next_action(py);
        };
        let awaitable = background.bind(py).call0()?;
        self.pending = Some(ResponsePending::RunBackground);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.phase {
            ResponsePhase::Start => {
                if !self.debug_sent {
                    if let Some(info) = self.info.as_ref() {
                        let message = PyDict::new(py);
                        message.set_item("type", "http.response.debug")?;
                        message.set_item("info", info.bind(py))?;
                        return self.send_message(
                            py,
                            message.into_any().unbind(),
                            ResponsePending::SendDebug,
                        );
                    }
                }
                let message = self.start_message(py)?;
                self.send_message(py, message, ResponsePending::SendStart)
            }
            ResponsePhase::ReceiveBody => {
                let awaitable = self.receive_stream.bind(py).call_method0("receive")?;
                self.pending = Some(ResponsePending::ReceiveBody);
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            ResponsePhase::FinishBody => {
                let message = PyDict::new(py);
                message.set_item("type", "http.response.body")?;
                message.set_item("body", PyBytes::new(py, b""))?;
                message.set_item("more_body", false)?;
                self.send_message(py, message.into_any().unbind(), ResponsePending::SendFinal)
            }
            ResponsePhase::Complete => Ok(MachineAction::Complete(py.None())),
        }
    }

    fn process_body_message(
        &mut self,
        py: Python<'_>,
        message: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        let message = message.bind(py).cast::<PyDict>()?;
        let message_type = message
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if message_type == "http.response.pathsend" {
            return self.send_message(
                py,
                message.clone().into_any().unbind(),
                ResponsePending::SendPathsend,
            );
        }
        if message_type != "http.response.body" {
            return Err(PyAssertionError::new_err(format!(
                "Unexpected message: {}",
                message.repr()?.extract::<String>()?
            )));
        }
        let body = message
            .get_item("body")?
            .unwrap_or_else(|| PyBytes::new(py, b"").into_any());
        let more_body = message
            .get_item("more_body")?
            .map(|value| value.extract::<bool>())
            .transpose()?
            .unwrap_or(false);
        if body.is_truthy()? {
            let output = PyDict::new(py);
            output.set_item("type", "http.response.body")?;
            output.set_item("body", body)?;
            output.set_item("more_body", true)?;
            return self.send_message(
                py,
                output.into_any().unbind(),
                ResponsePending::SendChunk { more_body },
            );
        }
        if more_body {
            self.phase = ResponsePhase::ReceiveBody;
            return self.next_action(py);
        }
        self.phase = ResponsePhase::FinishBody;
        self.next_action(py)
    }

    fn start_message(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let message = PyDict::new(py);
        message.set_item("type", "http.response.start")?;
        message.set_item("status", self.status_code)?;
        message.set_item("headers", raw_headers_list(py, &self.headers)?)?;
        Ok(message.into_any().unbind())
    }

    fn send_message(
        &mut self,
        py: Python<'_>,
        message: Py<PyAny>,
        pending: ResponsePending,
    ) -> PyResult<MachineAction> {
        let awaitable = self.send.bind(py).call1((message,))?;
        self.pending = Some(pending);
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn raw_headers_to_python(py: Python<'_>, headers: &SharedHeaders) -> PyResult<Py<PyAny>> {
    Ok(raw_headers_list(py, headers)?.into_any().unbind())
}

fn raw_headers_list<'py>(py: Python<'py>, headers: &SharedHeaders) -> PyResult<Bound<'py, PyList>> {
    let result = PyList::empty(py);
    for (name, value) in headers.borrow().iter() {
        result.append(PyTuple::new(
            py,
            [PyBytes::new(py, name), PyBytes::new(py, value)],
        )?)?;
    }
    Ok(result)
}

fn disconnect_message(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let message = PyDict::new(py);
    message.set_item("type", "http.disconnect")?;
    Ok(message.into_any().unbind())
}

fn is_end_of_stream(py: Python<'_>, error: &PyErr) -> PyResult<bool> {
    let end_of_stream = py.import("anyio")?.getattr("EndOfStream")?;
    error.value(py).is_instance(&end_of_stream)
}

fn is_broken_resource(py: Python<'_>, error: &PyErr) -> PyResult<bool> {
    let broken_resource = py.import("anyio")?.getattr("BrokenResourceError")?;
    error.value(py).is_instance(&broken_resource)
}

fn preserve_application_exception(
    py: Python<'_>,
    error: PyErr,
    end_of_stream: &PyErr,
) -> PyResult<PyErr> {
    let value = error.value(py);
    let cause = value.getattr("__cause__")?;
    let cause = if cause.is_truthy()? {
        cause
    } else {
        value.getattr("__context__")?
    };
    let cause = if cause.is_none() {
        None
    } else {
        Some(PyErr::from_value(cause))
    };
    error.set_cause(py, cause);
    // This is the context Python attaches when Starlette re-raises app_exc from
    // inside its `except EndOfStream` block.
    error
        .value(py)
        .setattr("__context__", end_of_stream.value(py))?;
    Ok(error)
}

fn key_to_string(key: &[u8]) -> String {
    String::from_utf8_lossy(key).into_owned()
}
