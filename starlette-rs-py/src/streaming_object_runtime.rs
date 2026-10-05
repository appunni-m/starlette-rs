//! Streaming facade protocols over live public response attributes.
//!
//! Rust selects events, catches disconnects and coordinates the stream and
//! listener. Python only drives user awaitables on the caller's event loop.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyOSError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyMemoryView};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

pub(crate) fn stream(py: Python<'_>, response: Py<PyAny>, send: Py<PyAny>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        Stream {
            response,
            send,
            iterator: None,
            chunk: None,
            pending: StreamPending::Start,
        },
    )
}

#[derive(Clone, Copy)]
enum StreamPending {
    Start,
    Header,
    Pull,
    Body,
    Final,
}

struct Stream {
    response: Py<PyAny>,
    send: Py<PyAny>,
    iterator: Option<Py<PyAny>>,
    chunk: Option<Py<PyAny>>,
    pending: StreamPending,
}

impl AwaitableStateMachine for Stream {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.response)?;
        visit.call(&self.send)?;
        visit.call(&self.iterator)?;
        visit.call(&self.chunk)
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let message = PyDict::new(py);
                message.set_item("type", "http.response.start")?;
                message.set_item("status", self.response.bind(py).getattr("status_code")?)?;
                message.set_item("headers", self.response.bind(py).getattr("raw_headers")?)?;
                self.pending = StreamPending::Header;
                self.send(py, &message)
            }
            MachineResume::Value(value) => match self.pending {
                StreamPending::Header => {
                    // async-for selects the iterator after the start send completes.
                    let iterable = self.response.bind(py).getattr("body_iterator")?;
                    self.iterator = Some(
                        py.import("builtins")?
                            .call_method1("aiter", (iterable,))?
                            .unbind(),
                    );
                    self.pull(py)
                }
                StreamPending::Pull => {
                    let value = value.into_bound(py);
                    let chunk = if value.is_instance_of::<PyBytes>()
                        || value.is_instance_of::<PyMemoryView>()
                    {
                        value
                    } else {
                        value
                            .call_method1("encode", (self.response.bind(py).getattr("charset")?,))?
                    };
                    self.chunk = Some(chunk.clone().unbind());
                    let message = PyDict::new(py);
                    message.set_item("type", "http.response.body")?;
                    message.set_item("body", chunk)?;
                    message.set_item("more_body", true)?;
                    self.pending = StreamPending::Body;
                    self.send(py, &message)
                }
                StreamPending::Body => self.pull(py),
                StreamPending::Final => Ok(MachineAction::Complete(py.None())),
                StreamPending::Start => {
                    Err(PyRuntimeError::new_err("stream resumed before its start"))
                }
            },
            MachineResume::AsyncIterationComplete(error) => {
                if !matches!(self.pending, StreamPending::Pull) {
                    return Err(error);
                }
                let message = PyDict::new(py);
                message.set_item("type", "http.response.body")?;
                message.set_item("body", PyBytes::new(py, b""))?;
                message.set_item("more_body", false)?;
                self.pending = StreamPending::Final;
                self.send(py, &message)
            }
            MachineResume::Error(error) => Err(error),
        }
    }
}

impl Stream {
    fn send(&self, py: Python<'_>, message: &Bound<'_, PyDict>) -> PyResult<MachineAction> {
        Ok(MachineAction::Await(
            self.send.bind(py).call1((message,))?.unbind(),
        ))
    }

    fn pull(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        self.pending = StreamPending::Pull;
        let iterator = self
            .iterator
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("stream has no iterator"))?;
        Ok(MachineAction::Await(
            py.import("builtins")?
                .call_method1("anext", (iterator.bind(py),))?
                .unbind(),
        ))
    }
}

pub(crate) fn listen(py: Python<'_>, receive: Py<PyAny>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(py, Listener { receive })
}

struct Listener {
    receive: Py<PyAny>,
}

impl AwaitableStateMachine for Listener {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receive)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Value(message)
                if message.bind(py).get_item("type")?.eq("http.disconnect")? =>
            {
                return Ok(MachineAction::Complete(py.None()));
            }
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                return Err(error);
            }
            MachineResume::Start | MachineResume::Value(_) => {}
        }
        Ok(MachineAction::Await(
            self.receive.bind(py).call0()?.unbind(),
        ))
    }
}

/// The AnyIO child captures the public bound method before it is scheduled,
/// and invokes it inside the child task, preserving callback task ownership.
pub(crate) struct StreamHook {
    callable: Py<PyAny>,
    send: Py<PyAny>,
}

impl StreamHook {
    pub(crate) fn new(callable: Py<PyAny>, send: Py<PyAny>) -> Self {
        Self { callable, send }
    }
}

impl AwaitableStateMachine for StreamHook {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callable)?;
        visit.call(&self.send)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => Ok(MachineAction::Await(
                self.callable
                    .bind(py)
                    .call1((self.send.bind(py),))?
                    .unbind(),
            )),
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
        }
    }
}

pub(crate) fn call(
    py: Python<'_>,
    response: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        Call {
            response,
            scope,
            receive,
            send,
            pending: CallPending::Start,
        },
    )
}

#[derive(Clone, Copy)]
enum CallPending {
    Start,
    Stream,
    StreamWithDisconnect,
    Concurrent,
    Background,
}

struct Call {
    response: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: CallPending,
}

impl AwaitableStateMachine for Call {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.response)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(_) => match self.pending {
                CallPending::Stream | CallPending::StreamWithDisconnect => self.background(py),
                CallPending::Concurrent | CallPending::Background => {
                    Ok(MachineAction::Complete(py.None()))
                }
                CallPending::Start => Err(PyRuntimeError::new_err(
                    "stream call resumed before its start",
                )),
            },
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                if matches!(self.pending, CallPending::StreamWithDisconnect) {
                    Err(client_disconnect(py, error))
                } else {
                    Err(error)
                }
            }
        }
    }
}

impl Call {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let response = self.response.bind(py);
        if self.scope.bind(py).get_item("type")?.eq("websocket")? {
            self.send = response
                .call_method1("_wrap_websocket_denial_send", (self.send.bind(py),))?
                .unbind();
            self.pending = CallPending::Stream;
        } else if crate::runtime_calls::asgi_spec_at_least_24(
            py,
            self.scope.bind(py).cast::<PyDict>()?,
        )? {
            self.pending = CallPending::StreamWithDisconnect;
        } else {
            self.pending = CallPending::Concurrent;
            return Ok(MachineAction::Await(
                crate::runtime_calls::streaming_object_disconnect_call(
                    py,
                    self.response.clone_ref(py),
                    self.receive.clone_ref(py),
                    self.send.clone_ref(py),
                )?,
            ));
        }
        let stream = response
            .call_method1("stream_response", (self.send.bind(py),))
            .map_err(|error| {
                if matches!(self.pending, CallPending::StreamWithDisconnect) {
                    client_disconnect(py, error)
                } else {
                    error
                }
            })?;
        Ok(MachineAction::Await(stream.unbind()))
    }

    fn background(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let response = self.response.bind(py);
        if response.getattr("background")?.is_none() {
            return Ok(MachineAction::Complete(py.None()));
        }
        self.pending = CallPending::Background;
        Ok(MachineAction::Await(
            response.getattr("background")?.call0()?.unbind(),
        ))
    }
}

fn client_disconnect(py: Python<'_>, error: PyErr) -> PyErr {
    if !error.is_instance_of::<PyOSError>(py) {
        return error;
    }
    match py
        .import("starlette.requests")
        .and_then(|module| module.getattr("ClientDisconnect"))
        .and_then(|class| class.call0())
    {
        Ok(value) => {
            let disconnect = PyErr::from_value(value);
            disconnect.set_context(py, Some(error));
            disconnect
        }
        Err(factory_error) => factory_error,
    }
}

pub(crate) fn wrap_denial_send(py: Python<'_>, send: Py<PyAny>) -> PyResult<Py<PyAny>> {
    Py::new(py, DenialSend { send }).map(Py::into_any)
}

#[pyclass]
struct DenialSend {
    send: Py<PyAny>,
}

#[pymethods]
impl DenialSend {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send)
    }
    fn __clear__(&mut self, py: Python<'_>) {
        self.send = py.None();
    }

    fn __call__(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            DenialMessage {
                send: self.send.clone_ref(py),
                message,
            },
        )
    }
}

struct DenialMessage {
    send: Py<PyAny>,
    message: Py<PyAny>,
}

impl AwaitableStateMachine for DenialMessage {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send)?;
        visit.call(&self.message)
    }
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let message = self.message.bind(py);
                let kind = message.get_item("type")?;
                if kind.eq("http.response.start")? || kind.eq("http.response.body")? {
                    let copy = PyDict::new(py);
                    copy.call_method1("update", (message,))?;
                    let renamed = py
                        .import("operator")?
                        .call_method1("add", ("websocket.", kind))?;
                    copy.set_item("type", renamed)?;
                    self.message = copy.into_any().unbind();
                }
                Ok(MachineAction::Await(
                    self.send.bind(py).call1((self.message.bind(py),))?.unbind(),
                ))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
        }
    }
}
