//! Rust-owned ASGI response control flow with Python callback delegation.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::exceptions::{PyAttributeError, PyOSError, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};
use starlette_rs::{
    Response, ResponseCall, ResponseCallError, ResponseCallInput, ResponseCallStep, ResponseError,
    ResponseEvent, StreamingResponse as NativeStreamingResponse, StreamingResponseCall,
    StreamingResponseCallError, StreamingResponseCallInput, StreamingResponseCallStep,
    StreamingResponseEvent,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

pub(crate) fn header_pairs(
    py: Python<'_>,
    headers: Option<Py<PyAny>>,
) -> PyResult<Vec<(String, String)>> {
    let Some(headers) = headers else {
        return Ok(Vec::new());
    };
    let headers = headers.bind(py);
    let items = match headers.call_method0("items") {
        Ok(items) => items,
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => headers.clone(),
        Err(error) => return Err(error),
    };
    let iterator = items.try_iter()?;
    let mut pairs = Vec::new();
    for item in iterator {
        let pair = item?;
        let pair = pair.cast::<PyTuple>()?;
        pairs.push((pair.get_item(0)?.extract()?, pair.get_item(1)?.extract()?));
    }
    Ok(pairs)
}

pub(crate) fn response_call(
    py: Python<'_>,
    response: &Response,
    scope: &Bound<'_, PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    background: Option<Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let websocket = is_websocket_scope(scope)?;
    into_python_awaitable(
        py,
        ResponseCallMachine {
            call: response.call_state(background.is_some()),
            send,
            _receive: receive,
            background,
            websocket,
            pending: None,
        },
    )
}

enum ResponsePending {
    Send,
    Background,
}

struct ResponseCallMachine {
    call: ResponseCall,
    send: Py<PyAny>,
    _receive: Py<PyAny>,
    background: Option<Py<PyAny>>,
    websocket: bool,
    pending: Option<ResponsePending>,
}

impl AwaitableStateMachine for ResponseCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(_) => {
                match self.pending.take() {
                    Some(ResponsePending::Send) => {
                        self.advance(ResponseCallInput::Send(Ok(())))?;
                    }
                    Some(ResponsePending::Background) => {
                        self.advance(ResponseCallInput::BackgroundFinished(Ok(())))?;
                    }
                    None => {
                        return Err(PyRuntimeError::new_err("no response operation is pending"));
                    }
                }
                self.next_action(py)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Error(error) => {
                match self.pending.take() {
                    Some(ResponsePending::Send) => {
                        self.advance(ResponseCallInput::Send(Err(error)))?;
                    }
                    Some(ResponsePending::Background) => {
                        self.advance(ResponseCallInput::BackgroundFinished(Err(error)))?;
                    }
                    None => return Err(error),
                }
                Err(PyRuntimeError::new_err(
                    "response operation failed without an error",
                ))
            }
        }
    }
}

impl ResponseCallMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.call.step() {
            ResponseCallStep::Send(event) => {
                self.pending = Some(ResponsePending::Send);
                let message = response_event_to_py(py, event, self.websocket)?;
                let awaitable = self.send.bind(py).call1((message,))?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            ResponseCallStep::RunBackground => {
                self.pending = Some(ResponsePending::Background);
                let background = self.background.as_ref().ok_or_else(|| {
                    PyRuntimeError::new_err("response requested a missing background callback")
                })?;
                let awaitable = background.bind(py).call0()?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            ResponseCallStep::Complete => Ok(MachineAction::Complete(py.None())),
            ResponseCallStep::Failed => {
                Err(PyRuntimeError::new_err("response call is already failed"))
            }
        }
    }

    fn advance(&mut self, input: ResponseCallInput<PyErr>) -> PyResult<()> {
        self.pending = None;
        self.call
            .advance(input)
            .map(|_| ())
            .map_err(response_call_error)
    }
}

#[pyclass(name = "StreamingResponse", unsendable)]
pub(crate) struct PyStreamingResponse {
    inner: NativeStreamingResponse,
    content: Py<PyAny>,
    async_iterable: bool,
    charset: String,
    sync_iterator: Rc<RefCell<Option<Py<PyAny>>>>,
}

#[pymethods]
impl PyStreamingResponse {
    #[new]
    #[pyo3(signature = (content, status_code=200, headers=None, media_type=None, charset="utf-8"))]
    fn new(
        py: Python<'_>,
        content: Py<PyAny>,
        status_code: u16,
        headers: Option<Py<PyAny>>,
        media_type: Option<String>,
        charset: &str,
    ) -> PyResult<Self> {
        let async_iterable = match content.bind(py).getattr("__aiter__") {
            Ok(_) => true,
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => false,
            Err(error) => return Err(error),
        };
        let inner = NativeStreamingResponse::from_chunks(
            status_code,
            Vec::<Vec<u8>>::new(),
            media_type.as_deref(),
            header_pairs(py, headers)?,
        )
        .map_err(response_error)?;
        Ok(Self {
            inner,
            content,
            async_iterable,
            charset: charset.to_owned(),
            sync_iterator: Rc::new(RefCell::new(None)),
        })
    }

    fn set_cookie(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.set_cookie(key, value).map_err(response_error)
    }

    fn asgi_call(
        &self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        background: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let websocket = is_websocket_scope(scope)?;
        let catches_client_disconnect = !websocket && asgi_spec_at_least_24(py, scope)?;
        into_python_awaitable(
            py,
            StreamingCallMachine {
                call: self.inner.call_state(background.is_some()),
                content: self.content.clone_ref(py),
                iterator: None,
                sentinel: None,
                async_iterable: self.async_iterable,
                charset: self.charset.clone(),
                sync_iterator: self.sync_iterator.clone(),
                send,
                _receive: receive,
                background,
                websocket,
                catches_client_disconnect,
                pending: None,
                body_override: None,
            },
        )
    }
}

enum StreamingPending {
    Send,
    PullChunk,
    Background,
}

struct StreamingCallMachine {
    call: StreamingResponseCall,
    content: Py<PyAny>,
    iterator: Option<Py<PyAny>>,
    sentinel: Option<Py<PyAny>>,
    async_iterable: bool,
    charset: String,
    sync_iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    send: Py<PyAny>,
    _receive: Py<PyAny>,
    background: Option<Py<PyAny>>,
    websocket: bool,
    catches_client_disconnect: bool,
    pending: Option<StreamingPending>,
    body_override: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for StreamingCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(value) => {
                match self.pending.take() {
                    Some(StreamingPending::Send) => {
                        self.advance(StreamingResponseCallInput::Send(Ok(())))?;
                    }
                    Some(StreamingPending::PullChunk) => {
                        let body = if self.is_sync_sentinel(py, &value)? {
                            None
                        } else {
                            self.body_override = Some(
                                stream_chunk_body(py, &value, &self.charset)
                                    .map_err(|error| self.stream_error(py, error))?,
                            );
                            Some(Vec::new())
                        };
                        self.advance(StreamingResponseCallInput::ChunkPulled(Ok(body)))?;
                    }
                    Some(StreamingPending::Background) => {
                        self.advance(StreamingResponseCallInput::BackgroundFinished(Ok(())))?;
                    }
                    None => {
                        return Err(PyRuntimeError::new_err("no streaming operation is pending"));
                    }
                }
                self.next_action(py)
            }
            MachineResume::AsyncIterationComplete => match self.pending.take() {
                Some(StreamingPending::PullChunk) if self.async_iterable => {
                    self.advance(StreamingResponseCallInput::ChunkPulled(Ok(None)))?;
                    self.next_action(py)
                }
                _ => Err(PyStopAsyncIteration::new_err(())),
            },
            MachineResume::Error(error) => {
                match self.pending.take() {
                    Some(StreamingPending::Send) => {
                        self.advance_stream(StreamingResponseCallInput::Send(Err(error)), py)?;
                    }
                    Some(StreamingPending::PullChunk) => {
                        self.advance_stream(
                            StreamingResponseCallInput::ChunkPulled(Err(error)),
                            py,
                        )?;
                    }
                    Some(StreamingPending::Background) => {
                        self.advance(StreamingResponseCallInput::BackgroundFinished(Err(error)))?;
                    }
                    None => return Err(error),
                }
                Err(PyRuntimeError::new_err(
                    "streaming operation failed without an error",
                ))
            }
        }
    }
}

impl StreamingCallMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.call.step() {
            StreamingResponseCallStep::Send(event) => {
                self.pending = Some(StreamingPending::Send);
                let body_override = self.body_override.take();
                let message = streaming_event_to_py(py, event, self.websocket, body_override)
                    .map_err(|error| self.stream_error(py, error))?;
                let awaitable = self
                    .send
                    .bind(py)
                    .call1((message,))
                    .map_err(|error| self.stream_error(py, error))?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            StreamingResponseCallStep::PullChunk => {
                self.pending = Some(StreamingPending::PullChunk);
                self.pull_chunk(py)
                    .map_err(|error| self.stream_error(py, error))
            }
            StreamingResponseCallStep::RunBackground => {
                self.pending = Some(StreamingPending::Background);
                let background = self.background.as_ref().ok_or_else(|| {
                    PyRuntimeError::new_err("stream requested a missing background callback")
                })?;
                let awaitable = background.bind(py).call0()?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            StreamingResponseCallStep::Complete => Ok(MachineAction::Complete(py.None())),
            StreamingResponseCallStep::Failed => {
                Err(PyRuntimeError::new_err("streaming call is already failed"))
            }
        }
    }

    fn pull_chunk(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.iterator.is_none() {
            let iterator = if self.async_iterable {
                self.content.bind(py).call_method0("__aiter__")?
            } else {
                let existing = self
                    .sync_iterator
                    .borrow()
                    .as_ref()
                    .map(|iterator| iterator.clone_ref(py));
                match existing {
                    Some(iterator) => iterator.into_bound(py),
                    None => {
                        let iterator = py
                            .import("builtins")?
                            .getattr("iter")?
                            .call1((self.content.bind(py),))?;
                        *self.sync_iterator.borrow_mut() = Some(iterator.clone().unbind());
                        iterator
                    }
                }
            };
            self.iterator = Some(iterator.unbind());
        }
        let iterator = self
            .iterator
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("stream iterator was not initialized"))?
            .bind(py);
        let awaitable = if self.async_iterable {
            iterator.call_method0("__anext__")?
        } else {
            let sentinel = match self.sentinel.as_ref() {
                Some(sentinel) => sentinel.clone_ref(py),
                None => {
                    let sentinel = py.import("builtins")?.getattr("object")?.call0()?.unbind();
                    self.sentinel = Some(sentinel.clone_ref(py));
                    sentinel
                }
            };
            let next = py.import("builtins")?.getattr("next")?;
            py.import("anyio.to_thread")?.getattr("run_sync")?.call1((
                next,
                iterator,
                sentinel.bind(py),
            ))?
        };
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn is_sync_sentinel(&self, py: Python<'_>, value: &Py<PyAny>) -> PyResult<bool> {
        if self.async_iterable {
            return Ok(false);
        }
        self.sentinel
            .as_ref()
            .map(|sentinel| value.bind(py).is(sentinel.bind(py)))
            .ok_or_else(|| PyRuntimeError::new_err("sync iterator sentinel was not initialized"))
    }

    fn advance(&mut self, input: StreamingResponseCallInput<PyErr>) -> PyResult<()> {
        self.pending = None;
        self.call
            .advance(input)
            .map(|_| ())
            .map_err(streaming_call_error)
    }

    fn advance_stream(
        &mut self,
        input: StreamingResponseCallInput<PyErr>,
        py: Python<'_>,
    ) -> PyResult<()> {
        self.advance(input)
            .map_err(|error| self.stream_error(py, error))
    }

    fn stream_error(&self, py: Python<'_>, error: PyErr) -> PyErr {
        if !self.catches_client_disconnect || !error.is_instance_of::<PyOSError>(py) {
            return error;
        }

        match py
            .import("starlette.requests")
            .and_then(|module| module.getattr("ClientDisconnect"))
            .and_then(|class| class.call0())
        {
            Ok(exception) => {
                let disconnect = PyErr::from_value(exception);
                disconnect.set_context(py, Some(error));
                disconnect
            }
            Err(factory_error) => factory_error,
        }
    }
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyStreamingResponse>()
}

fn is_websocket_scope(scope: &Bound<'_, PyDict>) -> PyResult<bool> {
    match scope.get_item("type")? {
        Some(value) => Ok(value.extract::<String>()? == "websocket"),
        None => Ok(false),
    }
}

fn asgi_spec_at_least_24(py: Python<'_>, scope: &Bound<'_, PyDict>) -> PyResult<bool> {
    let asgi = match scope.get_item("asgi")? {
        Some(asgi) => asgi,
        None => PyDict::new(py).into_any(),
    };
    let spec_version = asgi.call_method1("get", ("spec_version", "2.0"))?;
    let parts = spec_version.call_method1("split", (".",))?;
    let int = py.import("builtins")?.getattr("int")?;
    let version = parts
        .try_iter()?
        .map(|part| int.call1((part?,)))
        .collect::<PyResult<Vec<_>>>()?;
    let version = PyTuple::new(py, version)?;
    let minimum = PyTuple::new(py, [2, 4])?;
    version
        .rich_compare(minimum, pyo3::basic::CompareOp::Ge)?
        .is_truthy()
}

fn response_event_to_py(
    py: Python<'_>,
    event: ResponseEvent,
    websocket: bool,
) -> PyResult<Bound<'_, PyDict>> {
    let message = PyDict::new(py);
    match event {
        ResponseEvent::Start {
            status_code,
            headers,
        } => {
            message.set_item("type", event_type("http.response.start", websocket))?;
            message.set_item("status", status_code)?;
            message.set_item("headers", headers_to_py(py, headers)?)?;
        }
        ResponseEvent::Body { body } => {
            message.set_item("type", event_type("http.response.body", websocket))?;
            message.set_item("body", PyBytes::new(py, &body))?;
        }
    }
    Ok(message)
}

fn streaming_event_to_py(
    py: Python<'_>,
    event: StreamingResponseEvent,
    websocket: bool,
    body_override: Option<Py<PyAny>>,
) -> PyResult<Bound<'_, PyDict>> {
    let message = PyDict::new(py);
    match event {
        StreamingResponseEvent::Start {
            status_code,
            headers,
        } => {
            message.set_item("type", event_type("http.response.start", websocket))?;
            message.set_item("status", status_code)?;
            message.set_item("headers", headers_to_py(py, headers)?)?;
        }
        StreamingResponseEvent::Body { body, more_body } => {
            message.set_item("type", event_type("http.response.body", websocket))?;
            match body_override {
                Some(body) if more_body => message.set_item("body", body.bind(py))?,
                _ => message.set_item("body", PyBytes::new(py, &body))?,
            }
            message.set_item("more_body", more_body)?;
        }
    }
    Ok(message)
}

fn headers_to_py<'py>(
    py: Python<'py>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
) -> PyResult<Bound<'py, PyList>> {
    let values = PyList::empty(py);
    for (name, value) in headers {
        values.append(PyTuple::new(
            py,
            [PyBytes::new(py, &name), PyBytes::new(py, &value)],
        )?)?;
    }
    Ok(values)
}

fn event_type(http_type: &str, websocket: bool) -> String {
    if websocket {
        format!("websocket.{http_type}")
    } else {
        http_type.to_owned()
    }
}

fn stream_chunk_body(py: Python<'_>, chunk: &Py<PyAny>, charset: &str) -> PyResult<Py<PyAny>> {
    let chunk = chunk.bind(py);
    let memoryview_type = py.import("builtins")?.getattr("memoryview")?;
    if chunk.is_instance_of::<PyBytes>() || chunk.is_instance(&memoryview_type)? {
        return Ok(chunk.clone().unbind());
    }
    chunk.call_method1("encode", (charset,)).map(Bound::unbind)
}

fn response_call_error(error: ResponseCallError<PyErr>) -> PyErr {
    match error {
        ResponseCallError::Operation(error) => error,
        ResponseCallError::UnexpectedInput => {
            PyRuntimeError::new_err("unexpected result for current response call step")
        }
    }
}

fn streaming_call_error(error: StreamingResponseCallError<PyErr>) -> PyErr {
    match error {
        StreamingResponseCallError::Operation(error) => error,
        StreamingResponseCallError::UnexpectedInput => {
            PyRuntimeError::new_err("unexpected result for current streaming call step")
        }
    }
}

fn response_error(error: ResponseError) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(error.to_string())
}
