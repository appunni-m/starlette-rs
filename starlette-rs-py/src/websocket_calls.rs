//! Rust-owned ASGI WebSocket receive/send sequencing with Python callback delegation.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::class::gc::{PyTraverseError, PyVisit};

use pyo3::exceptions::{
    PyAssertionError, PyKeyError, PyOSError, PyRuntimeError, PyStopAsyncIteration, PyTypeError,
    PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyModule, PySet, PySetMethods, PyString};
use starlette_rs::{WebSocketState, WebSocketStateMachine};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

type SharedProtocolState = Arc<Mutex<WebSocketStateMachine>>;

fn protocol_state(state: &SharedProtocolState) -> PyResult<MutexGuard<'_, WebSocketStateMachine>> {
    state
        .lock()
        .map_err(|_| PyRuntimeError::new_err("WebSocket state mutex was poisoned"))
}

// Only Rust flags cross threads. No Python callback executes while a native
// state lock is held; Python futures continue on their owning event loop.
#[derive(Clone)]
struct SharedFlag(Arc<AtomicBool>);

impl SharedFlag {
    fn new(value: bool) -> Self {
        Self(Arc::new(AtomicBool::new(value)))
    }
    fn get(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
    fn set(&self, value: bool) {
        self.0.store(value, Ordering::SeqCst);
    }
    fn replace(&self, value: bool) -> bool {
        self.0.swap(value, Ordering::SeqCst)
    }
}

/// PyO3 boundary for the raw ASGI WebSocket receive and send operations.
///
/// The ASGI callbacks remain Python callables and are awaited by the current
/// Python task. State validation, callback ordering, and the connected-send
/// `OSError` policy run in the Rust continuation.
#[pyclass(name = "WebSocketProtocol")]
pub(crate) struct PyWebSocketProtocol {
    state: SharedProtocolState,
    receive_callback: Py<PyAny>,
    send_callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyWebSocketProtocol>()?;
    module.add_class::<PyWebSocketIterator>()?;
    module.add_class::<PyWebSocketClose>()?;
    Ok(())
}

#[pymethods]
impl PyWebSocketProtocol {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receive_callback)?;
        visit.call(&self.send_callback)?;
        visit.call(&self.disconnect_error)
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.receive_callback = py.None();
        self.send_callback = py.None();
        self.disconnect_error = py.None();
    }
    #[new]
    fn new(
        scope: &Bound<'_, PyDict>,
        receive_callback: Py<PyAny>,
        send_callback: Py<PyAny>,
        disconnect_error: Py<PyAny>,
    ) -> PyResult<Self> {
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?;
        if !scope_type.eq("websocket")? {
            return Err(PyAssertionError::new_err(()));
        }

        Ok(Self {
            state: Arc::new(Mutex::new(WebSocketStateMachine::new())),
            receive_callback,
            send_callback,
            disconnect_error,
        })
    }

    fn client_state(&self) -> PyResult<u8> {
        Ok(state_code(protocol_state(&self.state)?.client_state()))
    }

    fn set_client_state(&self, state: u8) -> PyResult<()> {
        protocol_state(&self.state)?.set_client_state(state_from_code(state)?);
        Ok(())
    }

    fn application_state(&self) -> PyResult<u8> {
        Ok(state_code(protocol_state(&self.state)?.application_state()))
    }

    fn set_application_state(&self, state: u8) -> PyResult<()> {
        protocol_state(&self.state)?.set_application_state(state_from_code(state)?);
        Ok(())
    }

    fn receive(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            WebSocketReceiveMachine {
                state: self.state.clone(),
                callback: self.receive_callback.clone_ref(py),
                state_at_start: None,
            },
        )
    }

    fn send(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            WebSocketSendMachine {
                state: self.state.clone(),
                callback: self.send_callback.clone_ref(py),
                disconnect_error: self.disconnect_error.clone_ref(py),
                message,
                catches_os_error: false,
                callback_pending: false,
            },
        )
    }

    fn accept(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
        send_callback: Py<PyAny>,
        subprotocol: Py<PyAny>,
        headers: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            AcceptMachine {
                state: self.state.clone(),
                receive_callback,
                send_callback,
                subprotocol,
                headers,
                pending: AcceptPending::Start,
            },
        )
    }

    fn receive_text(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
        disconnect_handler: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            receive_callback,
            disconnect_handler,
            TypedReceiveKind::Text,
        )
    }

    fn receive_bytes(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
        disconnect_handler: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            receive_callback,
            disconnect_handler,
            TypedReceiveKind::Bytes,
        )
    }

    fn receive_json(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
        disconnect_handler: Py<PyAny>,
        mode: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            receive_callback,
            disconnect_handler,
            TypedReceiveKind::Json(mode),
        )
    }

    fn iter_text(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
    ) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(receive_callback, self.disconnect_error.clone_ref(py)),
        )
    }

    fn iter_bytes(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
    ) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(receive_callback, self.disconnect_error.clone_ref(py)),
        )
    }

    fn iter_json(
        &self,
        py: Python<'_>,
        receive_callback: Py<PyAny>,
    ) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(receive_callback, self.disconnect_error.clone_ref(py)),
        )
    }

    fn send_text(
        &self,
        py: Python<'_>,
        send_callback: Py<PyAny>,
        data: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        framed_send_awaitable(py, send_callback, WebSocketSendFrame::Text(data))
    }

    fn send_bytes(
        &self,
        py: Python<'_>,
        send_callback: Py<PyAny>,
        data: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        framed_send_awaitable(py, send_callback, WebSocketSendFrame::Bytes(data))
    }

    fn send_json(
        &self,
        py: Python<'_>,
        send_callback: Py<PyAny>,
        data: Py<PyAny>,
        mode: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        framed_send_awaitable(py, send_callback, WebSocketSendFrame::Json { data, mode })
    }

    fn close(
        &self,
        py: Python<'_>,
        send_callback: Py<PyAny>,
        code: Py<PyAny>,
        reason: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        framed_send_awaitable(
            py,
            send_callback,
            WebSocketSendFrame::Close {
                code,
                reason,
                normalize_reason: true,
            },
        )
    }

    fn send_denial_response(
        &self,
        py: Python<'_>,
        scope: Py<PyAny>,
        response: Py<PyAny>,
        receive_callback: Py<PyAny>,
        send_callback: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            DenialResponseMachine {
                scope,
                response,
                receive_callback,
                send_callback,
                pending: false,
            },
        )
    }

    fn raise_on_disconnect(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<()> {
        raise_on_disconnect(py, &self.disconnect_error, message.bind(py))
    }
}

struct WebSocketReceiveMachine {
    state: SharedProtocolState,
    callback: Py<PyAny>,
    state_at_start: Option<WebSocketStateMachine>,
}

impl AwaitableStateMachine for WebSocketReceiveMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callback)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) => {
                self.record_message(py, &message)?;
                Ok(MachineAction::Complete(message))
            }
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl WebSocketReceiveMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let mut state_at_start = *protocol_state(&self.state)?;
        if matches!(
            state_at_start.client_state(),
            WebSocketState::Disconnected | WebSocketState::Response
        ) {
            let error = match state_at_start.receive("") {
                Err(error) => error,
                Ok(()) => {
                    return Err(PyRuntimeError::new_err(
                        "Cannot call \"receive\" once a disconnect message has been received.",
                    ));
                }
            };
            return Err(PyRuntimeError::new_err(error.to_string()));
        }

        self.state_at_start = Some(state_at_start);
        let awaitable = self.callback.bind(py).call0()?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn record_message(&mut self, py: Python<'_>, message: &Py<PyAny>) -> PyResult<()> {
        let message_type = message.bind(py).get_item("type")?.extract::<String>()?;
        let mut state_at_start = self
            .state_at_start
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("no WebSocket receive is pending"))?;
        let client_state_at_start = state_at_start.client_state();

        // Validate against the state that selected the receive branch before
        // awaiting the callback. This also preserves overlapping receive calls:
        // a concurrent receive may already have advanced the shared state.
        state_at_start
            .receive(&message_type)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        let mut shared = protocol_state(&self.state)?;
        if shared.client_state() == client_state_at_start
            && state_at_start.client_state() != client_state_at_start
        {
            shared
                .receive(&message_type)
                .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;
        }
        Ok(())
    }
}

struct WebSocketSendMachine {
    state: SharedProtocolState,
    callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
    message: Py<PyAny>,
    catches_os_error: bool,
    callback_pending: bool,
}

impl AwaitableStateMachine for WebSocketSendMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callback)?;
        visit.call(&self.disconnect_error)?;
        visit.call(&self.message)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) => {
                if !self.callback_pending {
                    return Err(PyRuntimeError::new_err("no WebSocket send is pending"));
                }
                self.callback_pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => self.callback_error(py, error),
        }
    }
}

impl WebSocketSendMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let application_state = protocol_state(&self.state)?.application_state();
        if application_state == WebSocketState::Disconnected {
            let error = match protocol_state(&self.state)?.begin_send("", false) {
                Err(error) => error,
                Ok(_) => {
                    return Err(PyRuntimeError::new_err(
                        "Cannot call \"send\" once a close message has been sent.",
                    ));
                }
            };
            return Err(PyRuntimeError::new_err(error.to_string()));
        }

        let message = self.message.bind(py);
        let message_type = message.get_item("type")?.extract::<String>()?;
        let more_body = if application_state == WebSocketState::Response {
            let value = message.getattr("get")?.call1(("more_body", false))?;
            value.is_truthy()?
        } else {
            false
        };

        self.catches_os_error = protocol_state(&self.state)?
            .begin_send(&message_type, more_body)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))?;

        // Starlette changes application state before invoking/awaiting send.
        // A synchronous callback error is inside the same OSError handler as an
        // error raised later by its awaitable.
        self.callback_pending = true;
        match self.callback.bind(py).call1((message,)) {
            Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
            Err(error) => self.callback_error(py, error),
        }
    }

    fn callback_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        self.callback_pending = false;
        if self.catches_os_error && error.is_instance_of::<PyOSError>(py) {
            protocol_state(&self.state)?.send_failed();
            let kwargs = PyDict::new(py);
            kwargs.set_item("code", 1006)?;
            let exception = self.disconnect_error.bind(py).call((), Some(&kwargs))?;
            let disconnect = PyErr::from_value(exception);
            disconnect.set_context(py, Some(error));
            return Err(disconnect);
        }
        Err(error)
    }
}

enum TypedReceiveKind {
    Text,
    Bytes,
    Json(Py<PyAny>),
}

fn typed_receive_awaitable(
    py: Python<'_>,
    state: &SharedProtocolState,
    receive_callback: Py<PyAny>,
    disconnect_handler: Py<PyAny>,
    kind: TypedReceiveKind,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        TypedReceiveMachine {
            state: state.clone(),
            receive_callback,
            disconnect_handler,
            kind,
            json_binary: false,
        },
    )
}

struct TypedReceiveMachine {
    state: SharedProtocolState,
    receive_callback: Py<PyAny>,
    disconnect_handler: Py<PyAny>,
    kind: TypedReceiveKind,
    json_binary: bool,
}

impl AwaitableStateMachine for TypedReceiveMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receive_callback)?;
        visit.call(&self.disconnect_handler)?;
        match &self.kind {
            TypedReceiveKind::Json(mode) => visit.call(mode),
            _ => Ok(()),
        }
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) => self.finish_message(py, message),
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl TypedReceiveMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if let TypedReceiveKind::Json(mode) = &self.kind {
            self.json_binary = json_mode_is_binary(py, mode.bind(py))?;
        }
        if protocol_state(&self.state)?.application_state() != WebSocketState::Connected {
            return Err(PyRuntimeError::new_err(
                "WebSocket is not connected. Need to call \"accept\" first.",
            ));
        }
        let awaitable = self.receive_callback.bind(py).call0()?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_message(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        self.disconnect_handler
            .bind(py)
            .call1((message.bind(py),))?;

        let value = match self.kind {
            TypedReceiveKind::Text => message.bind(py).get_item("text")?,
            TypedReceiveKind::Bytes => message.bind(py).get_item("bytes")?,
            TypedReceiveKind::Json(_) => {
                let text = if self.json_binary {
                    message
                        .bind(py)
                        .get_item("bytes")?
                        .call_method1("decode", ("utf-8",))?
                } else {
                    message.bind(py).get_item("text")?
                };
                py.import("json")?.getattr("loads")?.call1((text,))?
            }
        };
        Ok(MachineAction::Complete(value.unbind()))
    }
}

fn json_mode_is_binary(py: Python<'_>, mode: &Bound<'_, PyAny>) -> PyResult<bool> {
    let valid_modes = PySet::new(py, ["text", "binary"])?;
    if !valid_modes.contains(mode)? {
        return Err(PyRuntimeError::new_err(
            "The \"mode\" argument should be \"text\" or \"binary\".",
        ));
    }
    Ok(!mode.eq("text")?)
}

fn raise_on_disconnect(
    py: Python<'_>,
    disconnect_error: &Py<PyAny>,
    message: &Bound<'_, PyAny>,
) -> PyResult<()> {
    if message.get_item("type")?.eq("websocket.disconnect")? {
        let code = message.get_item("code")?;
        let reason = message.getattr("get")?.call1(("reason", py.None()))?;
        let exception = disconnect_error.bind(py).call1((code, reason))?;
        return Err(PyErr::from_value(exception));
    }
    Ok(())
}

enum AcceptPending {
    Start,
    Receive,
    Send,
}

struct AcceptMachine {
    state: SharedProtocolState,
    receive_callback: Py<PyAny>,
    send_callback: Py<PyAny>,
    subprotocol: Py<PyAny>,
    headers: Py<PyAny>,
    pending: AcceptPending,
}

impl AwaitableStateMachine for AcceptMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receive_callback)?;
        visit.call(&self.send_callback)?;
        visit.call(&self.subprotocol)?;
        visit.call(&self.headers)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) => {
                match std::mem::replace(&mut self.pending, AcceptPending::Start) {
                    AcceptPending::Receive => self.send_accept(py),
                    AcceptPending::Send => Ok(MachineAction::Complete(py.None())),
                    AcceptPending::Start => Err(PyRuntimeError::new_err(
                        "WebSocket accept resumed without a pending operation",
                    )),
                }
            }
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl AcceptMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if !self.headers.bind(py).is_truthy()? {
            self.headers = PyList::empty(py).into_any().unbind();
        }
        if protocol_state(&self.state)?.client_state() == WebSocketState::Connecting {
            self.pending = AcceptPending::Receive;
            let awaitable = self.receive_callback.bind(py).call0()?;
            return Ok(MachineAction::Await(awaitable.unbind()));
        }
        self.send_accept(py)
    }

    fn send_accept(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = PyDict::new(py);
        message.set_item("type", "websocket.accept")?;
        message.set_item("subprotocol", self.subprotocol.bind(py))?;
        message.set_item("headers", self.headers.bind(py))?;
        self.pending = AcceptPending::Send;
        let awaitable = self.send_callback.bind(py).call1((message,))?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

enum WebSocketSendFrame {
    Text(Py<PyAny>),
    Bytes(Py<PyAny>),
    Json {
        data: Py<PyAny>,
        mode: Py<PyAny>,
    },
    Close {
        code: Py<PyAny>,
        reason: Py<PyAny>,
        normalize_reason: bool,
    },
}

fn framed_send_awaitable(
    py: Python<'_>,
    send_callback: Py<PyAny>,
    frame: WebSocketSendFrame,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        FramedSendMachine {
            send_callback,
            frame: Some(frame),
            pending: false,
        },
    )
}

struct FramedSendMachine {
    send_callback: Py<PyAny>,
    frame: Option<WebSocketSendFrame>,
    pending: bool,
}

impl AwaitableStateMachine for FramedSendMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send_callback)?;
        match &self.frame {
            Some(WebSocketSendFrame::Text(value) | WebSocketSendFrame::Bytes(value)) => {
                visit.call(value)
            }
            Some(WebSocketSendFrame::Json { data, mode }) => {
                visit.call(data)?;
                visit.call(mode)
            }
            Some(WebSocketSendFrame::Close { code, reason, .. }) => {
                visit.call(code)?;
                visit.call(reason)
            }
            None => Ok(()),
        }
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) => {
                if !self.pending {
                    return Err(PyRuntimeError::new_err(
                        "WebSocket framed send resumed without a pending operation",
                    ));
                }
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl FramedSendMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let frame = self
            .frame
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocket framed send has already started"))?;
        let message = build_send_frame(py, frame)?;
        self.pending = true;
        let awaitable = self.send_callback.bind(py).call1((message,))?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn build_send_frame(py: Python<'_>, frame: WebSocketSendFrame) -> PyResult<Bound<'_, PyAny>> {
    let message = PyDict::new(py);
    match frame {
        WebSocketSendFrame::Text(data) => {
            message.set_item("type", "websocket.send")?;
            message.set_item("text", data.bind(py))?;
        }
        WebSocketSendFrame::Bytes(data) => {
            message.set_item("type", "websocket.send")?;
            message.set_item("bytes", data.bind(py))?;
        }
        WebSocketSendFrame::Json { data, mode } => {
            let binary = json_mode_is_binary(py, mode.bind(py))?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("separators", (",", ":"))?;
            kwargs.set_item("ensure_ascii", false)?;
            let encoded = py
                .import("json")?
                .getattr("dumps")?
                .call((data.bind(py),), Some(&kwargs))?;
            message.set_item("type", "websocket.send")?;
            if binary {
                let payload = encoded.call_method1("encode", ("utf-8",))?;
                message.set_item("bytes", payload)?;
            } else {
                message.set_item("text", encoded)?;
            }
        }
        WebSocketSendFrame::Close {
            code,
            reason,
            normalize_reason,
        } => {
            message.set_item("type", "websocket.close")?;
            message.set_item("code", code.bind(py))?;
            let reason = if normalize_reason && !reason.bind(py).is_truthy()? {
                PyString::new(py, "").into_any()
            } else {
                reason.into_bound(py)
            };
            message.set_item("reason", reason)?;
        }
    }
    Ok(message.into_any())
}

struct DenialResponseMachine {
    scope: Py<PyAny>,
    response: Py<PyAny>,
    receive_callback: Py<PyAny>,
    send_callback: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for DenialResponseMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.scope)?;
        visit.call(&self.response)?;
        visit.call(&self.receive_callback)?;
        visit.call(&self.send_callback)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) => {
                if !self.pending {
                    return Err(PyRuntimeError::new_err(
                        "WebSocket denial response resumed without a pending operation",
                    ));
                }
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl DenialResponseMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let empty_extensions = PyDict::new(py);
        let extensions = self
            .scope
            .bind(py)
            .getattr("get")?
            .call1(("extensions", empty_extensions))?;
        if !extensions.contains("websocket.http.response")? {
            return Err(PyRuntimeError::new_err(
                "The server doesn't support the Websocket Denial Response extension.",
            ));
        }
        let awaitable = self.response.bind(py).call1((
            self.scope.bind(py),
            self.receive_callback.bind(py),
            self.send_callback.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[pyclass(name = "WebSocketIterator")]
struct PyWebSocketIterator {
    callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
}

impl PyWebSocketIterator {
    fn new(callback: Py<PyAny>, disconnect_error: Py<PyAny>) -> Self {
        Self {
            callback,
            disconnect_error,
            finished: SharedFlag::new(false),
            running: SharedFlag::new(false),
            started: SharedFlag::new(false),
        }
    }
}

fn websocket_iterator_next(slf: Py<PyWebSocketIterator>, py: Python<'_>) -> PyResult<Py<PyAny>> {
    let borrowed = slf.borrow(py);
    let callback = borrowed.callback.clone_ref(py);
    let disconnect_error = borrowed.disconnect_error.clone_ref(py);
    let finished = borrowed.finished.clone();
    let running = borrowed.running.clone();
    let started = borrowed.started.clone();
    drop(borrowed);
    into_sendable_python_awaitable(
        py,
        WebSocketIteratorStep {
            callback,
            disconnect_error,
            finished,
            running,
            started,
            send_value: py.None(),
            pending: false,
        },
    )
}

#[pymethods]
impl PyWebSocketIterator {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callback)?;
        visit.call(&self.disconnect_error)
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.callback = py.None();
        self.disconnect_error = py.None();
    }
    fn __aiter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __anext__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        websocket_iterator_next(slf, py)
    }

    fn asend(slf: Py<Self>, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let callback = borrowed.callback.clone_ref(py);
        let disconnect_error = borrowed.disconnect_error.clone_ref(py);
        let finished = borrowed.finished.clone();
        let running = borrowed.running.clone();
        let started = borrowed.started.clone();
        drop(borrowed);
        into_sendable_python_awaitable(
            py,
            WebSocketIteratorStep {
                callback,
                disconnect_error,
                finished,
                running,
                started,
                send_value: value,
                pending: false,
            },
        )
    }

    fn athrow(slf: Py<Self>, py: Python<'_>, exception: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let finished = borrowed.finished.clone();
        let running = borrowed.running.clone();
        drop(borrowed);
        into_sendable_python_awaitable(
            py,
            WebSocketIteratorThrow {
                exception,
                finished,
                running,
            },
        )
    }

    fn aclose(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let finished = borrowed.finished.clone();
        let running = borrowed.running.clone();
        drop(borrowed);
        into_sendable_python_awaitable(py, WebSocketIteratorClose { finished, running })
    }

    #[getter]
    fn ag_await(&self, py: Python<'_>) -> Py<PyAny> {
        py.None()
    }

    #[getter]
    fn ag_code(&self, py: Python<'_>) -> Py<PyAny> {
        py.None()
    }

    #[getter]
    fn ag_frame(&self, py: Python<'_>) -> Py<PyAny> {
        py.None()
    }

    #[getter]
    fn ag_running(&self) -> bool {
        self.running.get()
    }
}

struct WebSocketIteratorThrow {
    exception: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
}

impl AwaitableStateMachine for WebSocketIteratorThrow {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.exception)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if self.running.get() {
                    return Err(PyRuntimeError::new_err(
                        "athrow(): asynchronous generator is already running",
                    ));
                }
                self.finished.set(true);
                Err(PyErr::from_value(self.exception.bind(py).clone()))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::Error(error) => Err(error),
            MachineResume::AsyncIterationComplete(error) => Err(error),
        }
    }
}

struct WebSocketIteratorClose {
    finished: SharedFlag,
    running: SharedFlag,
}

impl AwaitableStateMachine for WebSocketIteratorClose {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if self.running.get() {
                    return Err(PyRuntimeError::new_err(
                        "aclose(): asynchronous generator is already running",
                    ));
                }
                self.finished.set(true);
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::Error(error) => Err(error),
            MachineResume::AsyncIterationComplete(error) => Err(error),
        }
    }
}

struct WebSocketIteratorStep {
    callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
    send_value: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for WebSocketIteratorStep {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callback)?;
        visit.call(&self.disconnect_error)?;
        visit.call(&self.send_value)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) => {
                if !self.pending {
                    return Err(PyRuntimeError::new_err(
                        "WebSocket iterator resumed without a pending operation",
                    ));
                }
                self.pending = false;
                self.running.set(false);
                Ok(MachineAction::Complete(value))
            }
            MachineResume::AsyncIterationComplete(error) => self.callback_error(py, error),
            MachineResume::Error(error) => self.callback_error(py, error),
        }
    }
}

impl WebSocketIteratorStep {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.finished.get() {
            return Err(PyStopAsyncIteration::new_err(()));
        }
        if self.running.replace(true) {
            return Err(PyRuntimeError::new_err(
                "anext(): asynchronous generator is already running",
            ));
        }
        if !self.started.get() && !self.send_value.bind(py).is_none() {
            self.running.set(false);
            return Err(PyTypeError::new_err(
                "can't send non-None value to a just-started async generator",
            ));
        }
        self.started.set(true);
        match self.callback.bind(py).call0() {
            Ok(awaitable) => {
                self.pending = true;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            Err(error) => self.callback_error(py, error),
        }
    }

    fn callback_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        self.finish();
        if error.is_instance(py, self.disconnect_error.bind(py)) {
            Err(PyStopAsyncIteration::new_err(()))
        } else if error.is_instance_of::<PyStopAsyncIteration>(py) {
            let raised = PyRuntimeError::new_err("async generator raised StopAsyncIteration");
            raised.set_context(py, Some(error.clone_ref(py)));
            raised.set_cause(py, Some(error));
            Err(raised)
        } else {
            Err(error)
        }
    }

    fn finish(&mut self) {
        self.finished.set(true);
        self.running.set(false);
    }
}

#[pyclass(name = "WebSocketClose")]
struct PyWebSocketClose {
    code: Py<PyAny>,
    reason: Py<PyAny>,
}

#[pymethods]
impl PyWebSocketClose {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.code)?;
        visit.call(&self.reason)
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.code = py.None();
        self.reason = py.None();
    }
    #[new]
    fn new(py: Python<'_>, code: Py<PyAny>, reason: Py<PyAny>) -> PyResult<Self> {
        let reason = normalize_reason(py, reason)?;
        Ok(Self { code, reason })
    }

    #[getter]
    fn code(&self, py: Python<'_>) -> Py<PyAny> {
        self.code.clone_ref(py)
    }

    #[setter]
    fn set_code(&mut self, code: Py<PyAny>) {
        self.code = code;
    }

    #[getter]
    fn reason(&self, py: Python<'_>) -> Py<PyAny> {
        self.reason.clone_ref(py)
    }

    #[setter]
    fn set_reason(&mut self, reason: Py<PyAny>) {
        self.reason = reason;
    }

    fn asgi_call(
        &self,
        py: Python<'_>,
        _scope: Py<PyAny>,
        _receive: Py<PyAny>,
        send_callback: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        framed_send_awaitable(
            py,
            send_callback,
            WebSocketSendFrame::Close {
                code: self.code.clone_ref(py),
                reason: self.reason.clone_ref(py),
                normalize_reason: false,
            },
        )
    }
}

fn normalize_reason(py: Python<'_>, reason: Py<PyAny>) -> PyResult<Py<PyAny>> {
    if reason.bind(py).is_truthy()? {
        Ok(reason)
    } else {
        Ok(PyString::new(py, "").into_any().unbind())
    }
}

fn state_code(state: WebSocketState) -> u8 {
    match state {
        WebSocketState::Connecting => 0,
        WebSocketState::Connected => 1,
        WebSocketState::Disconnected => 2,
        WebSocketState::Response => 3,
    }
}

fn state_from_code(state: u8) -> PyResult<WebSocketState> {
    match state {
        0 => Ok(WebSocketState::Connecting),
        1 => Ok(WebSocketState::Connected),
        2 => Ok(WebSocketState::Disconnected),
        3 => Ok(WebSocketState::Response),
        _ => Err(PyValueError::new_err(format!(
            "unknown WebSocket state value: {state}"
        ))),
    }
}
