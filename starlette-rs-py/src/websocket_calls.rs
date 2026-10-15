//! Rust-owned ASGI WebSocket receive/send sequencing with Python callback delegation.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::class::gc::{PyTraverseError, PyVisit};

use pyo3::exceptions::{
    PyAssertionError, PyOSError, PyRuntimeError, PyStopAsyncIteration, PyStopIteration,
    PyTypeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{
    PyAny, PyDict, PyDictMethods, PyList, PyModule, PySet, PySetMethods, PyString, PyTuple,
    PyTupleMethods,
};
use starlette_rs::{WebSocketState, WebSocketStateMachine};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
    normalize_throw,
};

struct ProtocolState {
    machine: WebSocketStateMachine,
    client_state_override: Option<Py<PyAny>>,
    application_state_override: Option<Py<PyAny>>,
}

type SharedProtocolState = Arc<Mutex<ProtocolState>>;

#[pyclass(name = "_WebSocketProtocolState")]
struct PyWebSocketProtocolState {
    state: SharedProtocolState,
}

fn protocol_state(state: &SharedProtocolState) -> PyResult<MutexGuard<'_, ProtocolState>> {
    state
        .lock()
        .map_err(|_| PyRuntimeError::new_err("WebSocket state mutex was poisoned"))
}

fn clone_state_gc(
    py: Python<'_>,
    state_gc: Option<&Py<PyWebSocketProtocolState>>,
) -> PyResult<Py<PyWebSocketProtocolState>> {
    state_gc
        .map(|state| state.clone_ref(py))
        .ok_or_else(|| PyRuntimeError::new_err("WebSocket state was cleared"))
}

fn visit_protocol_state_values(
    state: &SharedProtocolState,
    visit: &PyVisit<'_>,
) -> Result<(), PyTraverseError> {
    let Ok(state) = state.lock() else {
        return Ok(());
    };
    if let Some(value) = &state.client_state_override {
        visit.call(value)?;
    }
    if let Some(value) = &state.application_state_override {
        visit.call(value)?;
    }
    Ok(())
}

#[pymethods]
impl PyWebSocketProtocolState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit_protocol_state_values(&self.state, &visit)
    }

    fn __clear__(&mut self, _py: Python<'_>) {
        let overrides = if let Ok(mut state) = self.state.lock() {
            (
                state.client_state_override.take(),
                state.application_state_override.take(),
            )
        } else {
            (None, None)
        };
        // Dropping the last reference may run a Python finalizer. Do so only
        // after releasing the protocol mutex.
        drop(overrides);
    }
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
    state_gc: Option<Py<PyWebSocketProtocolState>>,
    receive_callback: Py<PyAny>,
    send_callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
    state_type: Py<PyAny>,
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyWebSocketProtocolState>()?;
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
        visit.call(&self.disconnect_error)?;
        visit.call(&self.state_type)?;
        if let Some(state_gc) = &self.state_gc {
            visit.call(state_gc)?;
        }
        Ok(())
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.receive_callback = py.None();
        self.send_callback = py.None();
        self.disconnect_error = py.None();
        self.state_type = py.None();
        // The GC-visible state node clears its raw Python overrides itself.
        // Keep this edge until then; an active awaitable may share the node.
    }
    #[new]
    fn new(
        py: Python<'_>,
        scope: &Bound<'_, PyAny>,
        receive_callback: Py<PyAny>,
        send_callback: Py<PyAny>,
        disconnect_error: Py<PyAny>,
        state_type: Py<PyAny>,
        debug: bool,
    ) -> PyResult<Self> {
        if debug && !scope.get_item("type")?.eq("websocket")? {
            return Err(PyAssertionError::new_err(()));
        }

        let state = Arc::new(Mutex::new(ProtocolState {
            machine: WebSocketStateMachine::new(),
            client_state_override: None,
            application_state_override: None,
        }));
        let state_gc = Py::new(
            py,
            PyWebSocketProtocolState {
                state: state.clone(),
            },
        )?;

        Ok(Self {
            state,
            state_gc: Some(state_gc),
            receive_callback,
            send_callback,
            disconnect_error,
            state_type,
        })
    }

    fn client_state(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let (override_value, client_state) = {
            let state = protocol_state(&self.state)?;
            (
                state
                    .client_state_override
                    .as_ref()
                    .map(|value| value.clone_ref(py)),
                state.machine.client_state(),
            )
        };
        public_state_value(py, &self.state_type, override_value.as_ref(), client_state)
    }

    fn set_client_state(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<()> {
        let (client_state, override_value) =
            if let Some(valid_state) = assigned_enum_state(py, &self.state_type, &value)? {
                (valid_state, None)
            } else {
                // Python's WebSocket.client_state is a plain assignable
                // attribute. Retain unrecognized values so the protocol
                // branch performs the same rich comparison as Starlette.
                (WebSocketState::Disconnected, Some(value))
            };
        let previous = {
            let mut state = protocol_state(&self.state)?;
            state.machine.set_client_state(client_state);
            std::mem::replace(&mut state.client_state_override, override_value)
        };
        // Replacing an override can release its last Python reference.
        drop(previous);
        Ok(())
    }

    fn application_state(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let (override_value, application_state) = {
            let state = protocol_state(&self.state)?;
            (
                state
                    .application_state_override
                    .as_ref()
                    .map(|value| value.clone_ref(py)),
                state.machine.application_state(),
            )
        };
        public_state_value(
            py,
            &self.state_type,
            override_value.as_ref(),
            application_state,
        )
    }

    fn set_application_state(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<()> {
        let (application_state, override_value) =
            if let Some(valid_state) = assigned_enum_state(py, &self.state_type, &value)? {
                (valid_state, None)
            } else {
                (WebSocketState::Disconnected, Some(value))
            };
        let previous = {
            let mut state = protocol_state(&self.state)?;
            state.machine.set_application_state(application_state);
            std::mem::replace(&mut state.application_state_override, override_value)
        };
        drop(previous);
        Ok(())
    }

    fn receive(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            WebSocketReceiveMachine {
                state: self.state.clone(),
                state_gc: clone_state_gc(py, self.state_gc.as_ref())?,
                state_type: self.state_type.clone_ref(py),
                callback: self.receive_callback.clone_ref(py),
                client_state_at_start: None,
            },
        )
    }

    fn send(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            WebSocketSendMachine {
                state: self.state.clone(),
                state_gc: clone_state_gc(py, self.state_gc.as_ref())?,
                state_type: self.state_type.clone_ref(py),
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
        websocket: Py<PyAny>,
        subprotocol: Py<PyAny>,
        headers: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            AcceptMachine {
                state: self.state.clone(),
                state_gc: clone_state_gc(py, self.state_gc.as_ref())?,
                state_type: self.state_type.clone_ref(py),
                websocket,
                subprotocol,
                headers,
                pending: AcceptPending::Start,
            },
        )
    }

    fn receive_text(&self, py: Python<'_>, websocket: Py<PyAny>) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            clone_state_gc(py, self.state_gc.as_ref())?,
            self.state_type.clone_ref(py),
            websocket,
            TypedReceiveKind::Text,
        )
    }

    fn receive_bytes(&self, py: Python<'_>, websocket: Py<PyAny>) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            clone_state_gc(py, self.state_gc.as_ref())?,
            self.state_type.clone_ref(py),
            websocket,
            TypedReceiveKind::Bytes,
        )
    }

    fn receive_json(
        &self,
        py: Python<'_>,
        websocket: Py<PyAny>,
        mode: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        typed_receive_awaitable(
            py,
            &self.state,
            clone_state_gc(py, self.state_gc.as_ref())?,
            self.state_type.clone_ref(py),
            websocket,
            TypedReceiveKind::Json(mode),
        )
    }

    fn iter_text(&self, py: Python<'_>, receiver: Py<PyAny>) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(
                receiver,
                "receive_text",
                self.disconnect_error.clone_ref(py),
            ),
        )
    }

    fn iter_bytes(&self, py: Python<'_>, receiver: Py<PyAny>) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(
                receiver,
                "receive_bytes",
                self.disconnect_error.clone_ref(py),
            ),
        )
    }

    fn iter_json(&self, py: Python<'_>, receiver: Py<PyAny>) -> PyResult<Py<PyWebSocketIterator>> {
        Py::new(
            py,
            PyWebSocketIterator::new(
                receiver,
                "receive_json",
                self.disconnect_error.clone_ref(py),
            ),
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
        websocket: Py<PyAny>,
        response: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            DenialResponseMachine {
                websocket,
                response,
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
    state_gc: Py<PyWebSocketProtocolState>,
    state_type: Py<PyAny>,
    callback: Py<PyAny>,
    client_state_at_start: Option<WebSocketState>,
}

impl AwaitableStateMachine for WebSocketReceiveMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state_gc)?;
        visit.call(&self.state_type)?;
        visit.call(&self.callback)?;
        Ok(())
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
        let client_state_at_start = if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Client,
            WebSocketState::Connecting,
            RichComparison::Equal,
        )? {
            WebSocketState::Connecting
        } else if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Client,
            WebSocketState::Connected,
            RichComparison::Equal,
        )? {
            WebSocketState::Connected
        } else {
            return Err(PyRuntimeError::new_err(
                "Cannot call \"receive\" once a disconnect message has been received.",
            ));
        };

        self.client_state_at_start = Some(client_state_at_start);
        let awaitable = self.callback.bind(py).call0()?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn record_message(&mut self, py: Python<'_>, message: &Py<PyAny>) -> PyResult<()> {
        let message_type = message.bind(py).get_item("type")?;
        let client_state_at_start = self
            .client_state_at_start
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("no WebSocket receive is pending"))?;
        // Starlette operates on the original Python message value. Preserve
        // rich comparison, hashing, and their exceptions for str subclasses
        // as well as other input types instead of extracting a Rust String.
        match client_state_at_start {
            WebSocketState::Connecting => {
                if message_type.ne("websocket.connect")? {
                    let received = message_type.repr()?.extract::<String>()?;
                    return Err(PyRuntimeError::new_err(format!(
                        "Expected ASGI message \"websocket.connect\", but got {received}"
                    )));
                }
                // Starlette assigns this after the callback returns, so it
                // overwrites state changes made while that callback was pending.
                set_client_protocol_state(&self.state, WebSocketState::Connected)?;
            }
            WebSocketState::Connected => {
                let expected = PySet::new(py, ["websocket.receive", "websocket.disconnect"])?;
                if !expected.contains(&message_type)? {
                    let received = message_type.repr()?.extract::<String>()?;
                    return Err(PyRuntimeError::new_err(format!(
                        "Expected ASGI message \"websocket.receive\" or \"websocket.disconnect\", but got {received}"
                    )));
                }
                if message_type.eq("websocket.disconnect")? {
                    set_client_protocol_state(&self.state, WebSocketState::Disconnected)?;
                }
            }
            WebSocketState::Disconnected | WebSocketState::Response => {
                return Err(PyRuntimeError::new_err(
                    "Cannot call \"receive\" once a disconnect message has been received.",
                ));
            }
        }
        Ok(())
    }
}

struct WebSocketSendMachine {
    state: SharedProtocolState,
    state_gc: Py<PyWebSocketProtocolState>,
    state_type: Py<PyAny>,
    callback: Py<PyAny>,
    disconnect_error: Py<PyAny>,
    message: Py<PyAny>,
    catches_os_error: bool,
    callback_pending: bool,
}

impl AwaitableStateMachine for WebSocketSendMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state_gc)?;
        visit.call(&self.state_type)?;
        visit.call(&self.callback)?;
        visit.call(&self.disconnect_error)?;
        visit.call(&self.message)?;
        Ok(())
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
        let application_state = if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Application,
            WebSocketState::Connecting,
            RichComparison::Equal,
        )? {
            WebSocketState::Connecting
        } else if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Application,
            WebSocketState::Connected,
            RichComparison::Equal,
        )? {
            WebSocketState::Connected
        } else if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Application,
            WebSocketState::Response,
            RichComparison::Equal,
        )? {
            WebSocketState::Response
        } else {
            return Err(PyRuntimeError::new_err(
                "Cannot call \"send\" once a close message has been sent.",
            ));
        };

        let message = self.message.bind(py);
        self.catches_os_error = Self::begin_send(py, &self.state, message, application_state)?;

        // Starlette changes application state before invoking/awaiting send.
        // A synchronous callback error is inside the same OSError handler as an
        // error raised later by its awaitable.
        self.callback_pending = true;
        match self.callback.bind(py).call1((message,)) {
            Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
            Err(error) => self.callback_error(py, error),
        }
    }

    fn begin_send(
        py: Python<'_>,
        state: &SharedProtocolState,
        message: &Bound<'_, PyAny>,
        application_state: WebSocketState,
    ) -> PyResult<bool> {
        // Starlette applies Python set membership to arbitrary message type
        // objects in the CONNECTING and CONNECTED branches, then compares the
        // original object again to select state transitions. Keep those
        // Python hash/equality operations at the PyO3 boundary so user-defined
        // values retain their TypeError, rich-comparison, and re-entrant state
        // mutation behavior while Rust still selects and records the protocol
        // outcome.
        let message_type = message.get_item("type")?;
        match application_state {
            WebSocketState::Connecting => {
                let accepted = PySet::new(
                    py,
                    [
                        "websocket.accept",
                        "websocket.close",
                        "websocket.http.response.start",
                    ],
                )?;
                if !accepted.contains(&message_type)? {
                    return Self::invalid_message_type(application_state, &message_type);
                }
                let next_state = if message_type.eq("websocket.close")? {
                    WebSocketState::Disconnected
                } else if message_type.eq("websocket.http.response.start")? {
                    WebSocketState::Response
                } else {
                    WebSocketState::Connected
                };
                set_application_protocol_state(state, next_state)?;
                Ok(false)
            }
            WebSocketState::Connected => {
                let accepted = PySet::new(py, ["websocket.send", "websocket.close"])?;
                if !accepted.contains(&message_type)? {
                    return Self::invalid_message_type(application_state, &message_type);
                }
                if message_type.eq("websocket.close")? {
                    set_application_protocol_state(state, WebSocketState::Disconnected)?;
                }
                Ok(true)
            }
            WebSocketState::Response => {
                if message_type.ne("websocket.http.response.body")? {
                    return Self::invalid_message_type(application_state, &message_type);
                }
                let more_body = message.getattr("get")?.call1(("more_body", false))?;
                if !more_body.is_truthy()? {
                    set_application_protocol_state(state, WebSocketState::Disconnected)?;
                }
                Ok(false)
            }
            WebSocketState::Disconnected => Err(PyRuntimeError::new_err(
                "Cannot call \"send\" once a close message has been sent.",
            )),
        }
    }

    fn invalid_message_type(
        application_state: WebSocketState,
        message_type: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        let received_repr = message_type.repr()?.extract::<String>()?;
        let error =
            WebSocketStateMachine::invalid_send_type_error_for(application_state, &received_repr);
        Err(PyRuntimeError::new_err(error.to_string()))
    }

    fn callback_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        self.callback_pending = false;
        if self.catches_os_error && error.is_instance_of::<PyOSError>(py) {
            let previous = {
                let mut state = protocol_state(&self.state)?;
                state.machine.send_failed();
                state.application_state_override.take()
            };
            drop(previous);
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
    state_gc: Py<PyWebSocketProtocolState>,
    state_type: Py<PyAny>,
    websocket: Py<PyAny>,
    kind: TypedReceiveKind,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        TypedReceiveMachine {
            state: state.clone(),
            state_gc,
            state_type,
            websocket,
            kind,
        },
    )
}

struct TypedReceiveMachine {
    state: SharedProtocolState,
    state_gc: Py<PyWebSocketProtocolState>,
    state_type: Py<PyAny>,
    websocket: Py<PyAny>,
    kind: TypedReceiveKind,
}

impl AwaitableStateMachine for TypedReceiveMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state_gc)?;
        visit.call(&self.state_type)?;
        visit.call(&self.websocket)?;
        if let TypedReceiveKind::Json(mode) = &self.kind {
            visit.call(mode)?;
        }
        Ok(())
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
            validate_json_mode(py, mode.bind(py))?;
        }
        if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Application,
            WebSocketState::Connected,
            RichComparison::NotEqual,
        )? {
            return Err(PyRuntimeError::new_err(
                "WebSocket is not connected. Need to call \"accept\" first.",
            ));
        }
        // Starlette checks the application state before resolving the public
        // `receive` method. Resolve it here so subclass descriptors observe
        // the same order as the pinned coroutine.
        let receive_callback = self.websocket.bind(py).getattr("receive")?;
        let awaitable = receive_callback.call0()?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_message(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        // The source resolves `_raise_on_disconnect` only after receive has
        // completed, so keep that Python method lookup at this boundary.
        self.websocket
            .bind(py)
            .getattr("_raise_on_disconnect")?
            .call1((message.bind(py),))?;

        let value = match &self.kind {
            TypedReceiveKind::Text => message.bind(py).get_item("text")?,
            TypedReceiveKind::Bytes => message.bind(py).get_item("bytes")?,
            TypedReceiveKind::Json(mode) => {
                // Starlette compares `mode` with "text" only after the state
                // check, receive, and disconnect check have completed.
                let json_binary = !mode.bind(py).eq("text")?;
                let text = if json_binary {
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

fn validate_json_mode(py: Python<'_>, mode: &Bound<'_, PyAny>) -> PyResult<()> {
    let valid_modes = PySet::new(py, ["text", "binary"])?;
    if !valid_modes.contains(mode)? {
        return Err(PyRuntimeError::new_err(
            "The \"mode\" argument should be \"text\" or \"binary\".",
        ));
    }
    Ok(())
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
    state_gc: Py<PyWebSocketProtocolState>,
    state_type: Py<PyAny>,
    websocket: Py<PyAny>,
    subprotocol: Py<PyAny>,
    headers: Py<PyAny>,
    pending: AcceptPending,
}

impl AwaitableStateMachine for AcceptMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.state_gc)?;
        visit.call(&self.state_type)?;
        visit.call(&self.websocket)?;
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
        if protocol_state_matches(
            py,
            &self.state,
            &self.state_type,
            ProtocolStateSlot::Client,
            WebSocketState::Connecting,
            RichComparison::Equal,
        )? {
            self.pending = AcceptPending::Receive;
            let receive_callback = self.websocket.bind(py).getattr("receive")?;
            let awaitable = receive_callback.call0()?;
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
        let send_callback = self.websocket.bind(py).getattr("send")?;
        let awaitable = send_callback.call1((message,))?;
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
            // Starlette 1.6.0 validates mode, serializes, then compares it with
            // "text"; preserve that order for custom mode and payload values.
            validate_json_mode(py, mode.bind(py))?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("separators", (",", ":"))?;
            kwargs.set_item("ensure_ascii", false)?;
            let encoded = py
                .import("json")?
                .getattr("dumps")?
                .call((data.bind(py),), Some(&kwargs))?;
            message.set_item("type", "websocket.send")?;
            if mode.bind(py).eq("text")? {
                message.set_item("text", encoded)?;
            } else {
                let payload = encoded.call_method1("encode", ("utf-8",))?;
                message.set_item("bytes", payload)?;
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
    websocket: Py<PyAny>,
    response: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for DenialResponseMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.websocket)?;
        visit.call(&self.response)?;
        Ok(())
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
        let scope = self.websocket.bind(py).getattr("scope")?;
        let extensions = scope
            .getattr("get")?
            .call1(("extensions", empty_extensions))?;
        if !extensions.contains("websocket.http.response")? {
            return Err(PyRuntimeError::new_err(
                "The server doesn't support the Websocket Denial Response extension.",
            ));
        }
        let response_scope = self.websocket.bind(py).getattr("scope")?;
        let receive_callback = self.websocket.bind(py).getattr("receive")?;
        let send_callback = self.websocket.bind(py).getattr("send")?;
        let awaitable =
            self.response
                .bind(py)
                .call1((response_scope, receive_callback, send_callback))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[pyclass(name = "WebSocketIterator")]
struct PyWebSocketIterator {
    receiver: Py<PyAny>,
    method_name: &'static str,
    disconnect_error: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
}

impl PyWebSocketIterator {
    fn new(receiver: Py<PyAny>, method_name: &'static str, disconnect_error: Py<PyAny>) -> Self {
        Self {
            receiver,
            method_name,
            disconnect_error,
            finished: SharedFlag::new(false),
            running: SharedFlag::new(false),
            started: SharedFlag::new(false),
        }
    }
}

fn websocket_iterator_next(slf: Py<PyWebSocketIterator>, py: Python<'_>) -> PyResult<Py<PyAny>> {
    let borrowed = slf.borrow(py);
    let receiver = borrowed.receiver.clone_ref(py);
    let method_name = borrowed.method_name;
    let disconnect_error = borrowed.disconnect_error.clone_ref(py);
    let finished = borrowed.finished.clone();
    let running = borrowed.running.clone();
    let started = borrowed.started.clone();
    drop(borrowed);
    into_sendable_python_awaitable(
        py,
        WebSocketIteratorStep {
            receiver,
            method_name,
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
        visit.call(&self.receiver)?;
        visit.call(&self.disconnect_error)
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.receiver = py.None();
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
        let receiver = borrowed.receiver.clone_ref(py);
        let method_name = borrowed.method_name;
        let disconnect_error = borrowed.disconnect_error.clone_ref(py);
        let finished = borrowed.finished.clone();
        let running = borrowed.running.clone();
        let started = borrowed.started.clone();
        drop(borrowed);
        into_sendable_python_awaitable(
            py,
            WebSocketIteratorStep {
                receiver,
                method_name,
                disconnect_error,
                finished,
                running,
                started,
                send_value: value,
                pending: false,
            },
        )
    }

    #[pyo3(signature = (*arguments, **keywords))]
    fn athrow(
        slf: Py<Self>,
        py: Python<'_>,
        arguments: &Bound<'_, PyTuple>,
        keywords: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        if keywords.is_some_and(|keywords| !keywords.is_empty()) {
            return Err(PyTypeError::new_err("athrow() takes no keyword arguments"));
        }
        let argument_count = arguments.len();
        let arity_error = match argument_count {
            0 => Some("athrow expected at least 1 argument, got 0".to_owned()),
            1..=3 => None,
            count => Some(format!("athrow expected at most 3 arguments, got {count}")),
        };
        let exception_type = if argument_count >= 1 {
            Some(arguments.get_item(0)?.unbind())
        } else {
            None
        };
        let value = if argument_count >= 2 {
            Some(arguments.get_item(1)?.unbind())
        } else {
            None
        };
        let traceback = if argument_count >= 3 {
            Some(arguments.get_item(2)?.unbind())
        } else {
            None
        };
        let borrowed = slf.borrow(py);
        let disconnect_error = borrowed.disconnect_error.clone_ref(py);
        let finished = borrowed.finished.clone();
        let running = borrowed.running.clone();
        let started = borrowed.started.clone();
        drop(borrowed);
        into_sendable_python_awaitable(
            py,
            WebSocketIteratorThrow {
                exception_type,
                value,
                traceback,
                arity_error,
                disconnect_error,
                finished,
                running,
                started,
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
    exception_type: Option<Py<PyAny>>,
    value: Option<Py<PyAny>>,
    traceback: Option<Py<PyAny>>,
    arity_error: Option<String>,
    disconnect_error: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
}

impl AwaitableStateMachine for WebSocketIteratorThrow {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.exception_type)?;
        visit.call(&self.value)?;
        visit.call(&self.traceback)?;
        visit.call(&self.disconnect_error)
    }
    fn finalize_on_drop(&self) -> bool {
        self.arity_error.is_none()
    }
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if self.running.get() {
                    return Err(PyRuntimeError::new_err(
                        "athrow(): asynchronous generator is already running",
                    ));
                }
                if let Some(message) = &self.arity_error {
                    // CPython 3.12 leaves an async generator marked as running
                    // when an awaited athrow rejects its argument count.
                    self.running.set(true);
                    return Err(PyTypeError::new_err(message.clone()));
                }
                let was_finished = self.finished.replace(true);
                if was_finished {
                    return Ok(MachineAction::Complete(py.None()));
                }
                self.running.set(false);
                let Some(exception_type) = self.exception_type.as_ref() else {
                    return Err(PyRuntimeError::new_err(
                        "async iterator athrow exception type is unavailable",
                    ));
                };
                let error = normalize_throw(
                    py,
                    exception_type.clone_ref(py),
                    self.value.as_ref().map(|value| value.clone_ref(py)),
                    self.traceback
                        .as_ref()
                        .map(|traceback| traceback.clone_ref(py)),
                )?;
                if !was_finished
                    && self.started.get()
                    && error.is_instance(py, self.disconnect_error.bind(py))
                {
                    Err(PyStopAsyncIteration::new_err(()))
                } else if !was_finished
                    && self.started.get()
                    && error.is_instance_of::<PyStopIteration>(py)
                {
                    // PEP 479 converts StopIteration escaping an async generator body.
                    Err(async_generator_stop_iteration_error(py, error))
                } else if !was_finished
                    && self.started.get()
                    && error.is_instance_of::<PyStopAsyncIteration>(py)
                {
                    Err(async_generator_stop_async_iteration_error(py, error))
                } else {
                    Err(error)
                }
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
    receiver: Py<PyAny>,
    method_name: &'static str,
    disconnect_error: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
    send_value: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for WebSocketIteratorStep {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receiver)?;
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
        match self.receiver.bind(py).getattr(self.method_name) {
            Ok(callback) => match callback.call0() {
                Ok(awaitable) => {
                    self.pending = true;
                    Ok(MachineAction::Await(awaitable.unbind()))
                }
                Err(error) => self.callback_error(py, error),
            },
            Err(error) => self.callback_error(py, error),
        }
    }

    fn callback_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        self.finish();
        if error.is_instance(py, self.disconnect_error.bind(py)) {
            Err(PyStopAsyncIteration::new_err(()))
        } else if error.is_instance_of::<PyStopIteration>(py) {
            Err(async_generator_stop_iteration_error(py, error))
        } else if error.is_instance_of::<PyStopAsyncIteration>(py) {
            Err(async_generator_stop_async_iteration_error(py, error))
        } else {
            Err(error)
        }
    }

    fn finish(&mut self) {
        self.finished.set(true);
        self.running.set(false);
    }
}

fn async_generator_stop_async_iteration_error(py: Python<'_>, cause: PyErr) -> PyErr {
    let error = PyRuntimeError::new_err("async generator raised StopAsyncIteration");
    error.set_context(py, Some(cause.clone_ref(py)));
    error.set_cause(py, Some(cause));
    error
}

fn async_generator_stop_iteration_error(py: Python<'_>, cause: PyErr) -> PyErr {
    let error = PyRuntimeError::new_err("async generator raised StopIteration");
    error.set_context(py, Some(cause.clone_ref(py)));
    error.set_cause(py, Some(cause));
    error
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

#[derive(Clone, Copy)]
enum ProtocolStateSlot {
    Client,
    Application,
}

#[derive(Clone, Copy)]
enum RichComparison {
    Equal,
    NotEqual,
}

fn protocol_state_matches(
    py: Python<'_>,
    shared: &SharedProtocolState,
    state_type: &Py<PyAny>,
    slot: ProtocolStateSlot,
    expected: WebSocketState,
    comparison: RichComparison,
) -> PyResult<bool> {
    let (override_value, current_state) = {
        let state = protocol_state(shared)?;
        match slot {
            ProtocolStateSlot::Client => (
                state
                    .client_state_override
                    .as_ref()
                    .map(|value| value.clone_ref(py)),
                state.machine.client_state(),
            ),
            ProtocolStateSlot::Application => (
                state
                    .application_state_override
                    .as_ref()
                    .map(|value| value.clone_ref(py)),
                state.machine.application_state(),
            ),
        }
    };

    // The input can define __eq__ or __ne__ that re-enters this WebSocket.
    // Snapshot references under the mutex, then perform all Python rich
    // comparisons after releasing it.
    let expected = state_type.bind(py).getattr(state_member_name(expected))?;
    match override_value {
        Some(value) => compare_python_state(value.bind(py), &expected, comparison),
        None => {
            let current = state_type
                .bind(py)
                .getattr(state_member_name(current_state))?;
            compare_python_state(&current, &expected, comparison)
        }
    }
}

fn compare_python_state(
    left: &Bound<'_, PyAny>,
    right: &Bound<'_, PyAny>,
    comparison: RichComparison,
) -> PyResult<bool> {
    match comparison {
        RichComparison::Equal => left.eq(right),
        RichComparison::NotEqual => left.ne(right),
    }
}

fn set_client_protocol_state(
    shared: &SharedProtocolState,
    next_state: WebSocketState,
) -> PyResult<()> {
    let previous = {
        let mut state = protocol_state(shared)?;
        state.machine.set_client_state(next_state);
        state.client_state_override.take()
    };
    drop(previous);
    Ok(())
}

fn set_application_protocol_state(
    shared: &SharedProtocolState,
    next_state: WebSocketState,
) -> PyResult<()> {
    let previous = {
        let mut state = protocol_state(shared)?;
        state.machine.set_application_state(next_state);
        state.application_state_override.take()
    };
    drop(previous);
    Ok(())
}

fn state_member_name(state: WebSocketState) -> &'static str {
    match state {
        WebSocketState::Connecting => "CONNECTING",
        WebSocketState::Connected => "CONNECTED",
        WebSocketState::Disconnected => "DISCONNECTED",
        WebSocketState::Response => "RESPONSE",
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

fn public_state_value(
    py: Python<'_>,
    state_type: &Py<PyAny>,
    override_value: Option<&Py<PyAny>>,
    state: WebSocketState,
) -> PyResult<Py<PyAny>> {
    match override_value {
        Some(value) => Ok(value.clone_ref(py)),
        None => state_type
            .bind(py)
            .call1((state_code(state),))
            .map(Bound::unbind),
    }
}

fn assigned_enum_state(
    py: Python<'_>,
    state_type: &Py<PyAny>,
    value: &Py<PyAny>,
) -> PyResult<Option<WebSocketState>> {
    if !value.bind(py).is_instance(state_type.bind(py))? {
        return Ok(None);
    }
    value
        .bind(py)
        .getattr("value")?
        .extract::<u8>()
        .and_then(state_from_code)
        .map(Some)
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
