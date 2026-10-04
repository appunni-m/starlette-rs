//! Rust-owned ASGI response control flow with Python callback delegation.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::exceptions::{
    PyAttributeError, PyImportError, PyOSError, PyRuntimeError, PyStopAsyncIteration,
};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};
use starlette_rs::{
    Response, ResponseCall, ResponseCallError, ResponseCallInput, ResponseCallStep, ResponseError,
    ResponseEvent, StreamingResponse as NativeStreamingResponse, StreamingResponseCall,
    StreamingResponseCallError, StreamingResponseCallInput, StreamingResponseCallStep,
    StreamingResponseDisconnectCall, StreamingResponseDisconnectCallError,
    StreamingResponseDisconnectCallInput, StreamingResponseDisconnectCallStep,
    StreamingResponseDisconnectListener, StreamingResponseDisconnectListenerError,
    StreamingResponseDisconnectListenerInput, StreamingResponseDisconnectListenerStep,
    StreamingResponseDisconnectMessage, StreamingResponseEvent,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};
use crate::cookie_runtime;

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
    body_override: Option<Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    let websocket = is_websocket_scope(scope)?;
    into_python_awaitable(
        py,
        ResponseCallMachine {
            call: response.call_state(background.is_some()),
            send,
            _receive: receive,
            background,
            body_override,
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
    body_override: Option<Py<PyAny>>,
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
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
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
                let body_override = self.body_override.as_ref().map(|body| body.bind(py));
                let message = response_event_to_py(py, event, self.websocket, body_override)?;
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
    raw_headers: Py<PyAny>,
    headers_view: Option<Py<PyAny>>,
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
        let raw_headers = crate::response_headers_runtime::raw_pairs(py, inner.headers())?;
        Ok(Self {
            inner,
            raw_headers,
            headers_view: None,
            content,
            async_iterable,
            charset: charset.to_owned(),
            sync_iterator: Rc::new(RefCell::new(None)),
        })
    }

    #[getter]
    fn headers(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(headers) = self.headers_view.as_ref() {
            return Ok(headers.clone_ref(py));
        }
        let headers = crate::response_headers_runtime::view(py, self.raw_headers.bind(py))?;
        self.headers_view = Some(headers.clone_ref(py));
        Ok(headers)
    }

    #[getter]
    fn raw_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.raw_headers.clone_ref(py)
    }

    #[setter]
    fn set_raw_headers(&mut self, headers: Py<PyAny>) {
        self.raw_headers = headers;
    }

    fn _header_get(&self, key: &str) -> PyResult<Option<String>> {
        self.inner.get_header(key).map_err(response_error)
    }

    fn _header_set(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.set_header(key, value).map_err(response_error)
    }

    fn _header_delete(&mut self, key: &str) -> PyResult<()> {
        self.inner.delete_header(key).map_err(response_error)
    }

    fn _header_append(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.append_header(key, value).map_err(response_error)
    }

    fn _header_values(&self, key: &str) -> PyResult<Vec<String>> {
        self.inner.get_header_values(key).map_err(response_error)
    }

    fn _header_items(&self) -> Vec<(String, String)> {
        crate::response_headers_runtime::items(self.inner.headers())
    }

    fn _header_raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::response_headers_runtime::raw_pairs(py, self.inner.headers())
    }

    fn _header_replace_raw(&mut self, raw: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner
            .replace_headers_raw(crate::response_headers_runtime::parse_raw_pairs(raw)?);
        Ok(())
    }

    fn _header_refresh_raw(&self, py: Python<'_>) -> PyResult<()> {
        crate::response_headers_runtime::refresh_raw_pairs(
            py,
            self.raw_headers.bind(py),
            self.inner.headers(),
        )
    }

    fn _header_len(&self) -> usize {
        self.inner.headers().len()
    }

    #[pyo3(signature = (key, value="", max_age=None, expires=None, path="/", domain=None, secure=false, httponly=false, samesite="lax", partitioned=false))]
    // LINT EXCEPTION: Preserve Response.set_cookie's public Python options and keyword names one-for-one.
    #[allow(clippy::too_many_arguments)]
    fn set_cookie(
        &mut self,
        py: Python<'_>,
        key: &str,
        value: &str,
        max_age: Option<Py<PyAny>>,
        expires: Option<Py<PyAny>>,
        path: Option<&str>,
        domain: Option<&str>,
        secure: bool,
        httponly: bool,
        samesite: Option<&str>,
        partitioned: bool,
    ) -> PyResult<()> {
        let options = cookie_runtime::options_from_python(
            py,
            max_age,
            expires,
            path.map(str::to_owned),
            domain.map(str::to_owned),
            secure,
            httponly,
            samesite.map(str::to_owned),
            partitioned,
        )?;
        self.inner
            .set_cookie_with_options(key, value, &options)
            .map_err(response_error)
    }

    #[pyo3(signature = (key, path="/", domain=None, secure=false, httponly=false, samesite="lax"))]
    // LINT EXCEPTION: Preserve Response.delete_cookie's public Python options and keyword names one-for-one.
    #[allow(clippy::too_many_arguments)]
    fn delete_cookie(
        &mut self,
        py: Python<'_>,
        key: &str,
        path: Option<&str>,
        domain: Option<&str>,
        secure: bool,
        httponly: bool,
        samesite: Option<&str>,
    ) -> PyResult<()> {
        let (expires, options) = cookie_runtime::delete_options_from_python(
            py,
            path.map(str::to_owned),
            domain.map(str::to_owned),
            secure,
            httponly,
            samesite.map(str::to_owned),
        )?;
        self.inner
            .delete_cookie_with_options(key, &expires, &options)
            .map_err(response_error)
    }

    #[pyo3(signature = (scope, receive, send, background=None, status_code_override=None))]
    fn asgi_call(
        &self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        background: Option<Py<PyAny>>,
        status_code_override: Option<u16>,
    ) -> PyResult<Py<PyAny>> {
        let websocket = is_websocket_scope(scope)?;
        let spec_at_least_24 = if websocket {
            false
        } else {
            asgi_spec_at_least_24(py, scope)?
        };
        if !websocket && !spec_at_least_24 {
            let has_background_callback = background.is_some();
            return into_python_awaitable(
                py,
                StreamingDisconnectCallMachine {
                    response: self.inner.clone(),
                    status_code_override,
                    content: self.content.clone_ref(py),
                    async_iterable: self.async_iterable,
                    charset: self.charset.clone(),
                    sync_iterator: self.sync_iterator.clone(),
                    send,
                    receive,
                    background,
                    call: Rc::new(RefCell::new(StreamingResponseDisconnectCall::new(
                        has_background_callback,
                    ))),
                    listener: StreamingResponseDisconnectListener::new(),
                    task_group: None,
                    pending: None,
                },
            );
        }
        let catches_client_disconnect = !websocket && spec_at_least_24;
        into_python_awaitable(
            py,
            StreamingCallMachine {
                call: streaming_response_call_state(
                    &self.inner,
                    status_code_override,
                    background.is_some(),
                ),
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
            MachineResume::AsyncIterationComplete(_) => match self.pending.take() {
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

enum StreamingDisconnectPending {
    TaskGroupEnter,
    ListenerReceive,
    TaskGroupExit,
    Background,
}

struct StreamingDisconnectCallMachine {
    response: NativeStreamingResponse,
    status_code_override: Option<u16>,
    content: Py<PyAny>,
    async_iterable: bool,
    charset: String,
    sync_iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    send: Py<PyAny>,
    receive: Py<PyAny>,
    background: Option<Py<PyAny>>,
    call: Rc<RefCell<StreamingResponseDisconnectCall<PyErr>>>,
    listener: StreamingResponseDisconnectListener,
    task_group: Option<Py<PyAny>>,
    pending: Option<StreamingDisconnectPending>,
}

impl AwaitableStateMachine for StreamingDisconnectCallMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(StreamingDisconnectPending::TaskGroupEnter) => {
                    self.task_group = Some(value);
                    match self.start_stream_child(py) {
                        Ok(()) => self.next_action(py),
                        Err(error) => self.leave_task_group(py, Some(&error)),
                    }
                }
                Some(StreamingDisconnectPending::ListenerReceive) => self.finish_receive(py, value),
                Some(StreamingDisconnectPending::TaskGroupExit) => {
                    self.advance(StreamingResponseDisconnectCallInput::ConcurrentFinished(
                        Ok(()),
                    ))?;
                    self.next_action(py)
                }
                Some(StreamingDisconnectPending::Background) => {
                    self.advance(StreamingResponseDisconnectCallInput::BackgroundFinished(
                        Ok(()),
                    ))?;
                    self.next_action(py)
                }
                None => Err(PyRuntimeError::new_err(
                    "no streaming disconnect operation is pending",
                )),
            },
            MachineResume::AsyncIterationComplete(error) => match self.pending.take() {
                Some(StreamingDisconnectPending::ListenerReceive) => {
                    self.finish_listener_error(py, error)
                }
                Some(StreamingDisconnectPending::TaskGroupExit) => {
                    self.finish_task_group_error(py, error)
                }
                Some(StreamingDisconnectPending::Background) => {
                    self.advance(StreamingResponseDisconnectCallInput::BackgroundFinished(
                        Err(error.clone_ref(py)),
                    ))?;
                    Err(error)
                }
                Some(StreamingDisconnectPending::TaskGroupEnter) => {
                    Err(collapse_single_task_group_error(py, error)?)
                }
                None => Err(error),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(StreamingDisconnectPending::ListenerReceive) => {
                    self.finish_listener_error(py, error)
                }
                Some(StreamingDisconnectPending::TaskGroupExit) => {
                    self.finish_task_group_error(py, error)
                }
                Some(StreamingDisconnectPending::Background) => {
                    self.advance(StreamingResponseDisconnectCallInput::BackgroundFinished(
                        Err(error.clone_ref(py)),
                    ))?;
                    Err(error)
                }
                Some(StreamingDisconnectPending::TaskGroupEnter) => {
                    Err(collapse_single_task_group_error(py, error)?)
                }
                None => Err(error),
            },
        }
    }
}

impl StreamingDisconnectCallMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let step = self.call.borrow().step();
        match step {
            StreamingResponseDisconnectCallStep::StartConcurrent => self.enter_task_group(py),
            StreamingResponseDisconnectCallStep::AwaitFirstCompletion => self.receive_next(py),
            StreamingResponseDisconnectCallStep::CancelStream
            | StreamingResponseDisconnectCallStep::CancelListener
            | StreamingResponseDisconnectCallStep::CancelBoth => self.leave_task_group(py, None),
            StreamingResponseDisconnectCallStep::RunBackground => self.run_background(py),
            StreamingResponseDisconnectCallStep::Complete => Ok(MachineAction::Complete(py.None())),
            StreamingResponseDisconnectCallStep::Failed => Err(PyRuntimeError::new_err(
                "streaming disconnect call is already failed",
            )),
        }
    }

    fn enter_task_group(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let group = py.import("anyio")?.getattr("create_task_group")?.call0()?;
        let awaitable = group.call_method0("__aenter__")?;
        self.task_group = Some(group.unbind());
        self.pending = Some(StreamingDisconnectPending::TaskGroupEnter);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn start_stream_child(&mut self, py: Python<'_>) -> PyResult<()> {
        self.advance(StreamingResponseDisconnectCallInput::ConcurrentStarted)?;

        let result = self.make_and_start_stream_child(py);
        if let Err(error) = result {
            if self.call.borrow().step()
                == StreamingResponseDisconnectCallStep::AwaitFirstCompletion
            {
                let _ = self.advance(StreamingResponseDisconnectCallInput::StreamFinished(Err(
                    error.clone_ref(py),
                )))?;
            }
            return Err(error);
        }

        Ok(())
    }

    fn make_and_start_stream_child(&self, py: Python<'_>) -> PyResult<()> {
        let task_group = self.task_group_ref(py)?;
        let cancel_scope = task_group.getattr("cancel_scope")?.unbind();
        let stream = StreamingCallMachine {
            call: streaming_response_call_state(&self.response, self.status_code_override, false),
            content: self.content.clone_ref(py),
            iterator: None,
            sentinel: None,
            async_iterable: self.async_iterable,
            charset: self.charset.clone(),
            sync_iterator: self.sync_iterator.clone(),
            send: self.send.clone_ref(py),
            _receive: self.receive.clone_ref(py),
            background: None,
            websocket: false,
            catches_client_disconnect: false,
            pending: None,
            body_override: None,
        };
        let child = into_python_awaitable(
            py,
            StreamingResponseChildMachine {
                stream,
                call: self.call.clone(),
                cancel_scope,
            },
        )?;
        let factory = Py::new(py, AwaitableFactory { awaitable: child })?;
        task_group.call_method1("start_soon", (factory,))?;
        Ok(())
    }

    fn receive_next(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.listener.step() {
            StreamingResponseDisconnectListenerStep::Receive => {
                let awaitable = match self.receive.bind(py).call0() {
                    Ok(awaitable) => awaitable,
                    Err(error) => return self.finish_listener_error(py, error),
                };
                self.pending = Some(StreamingDisconnectPending::ListenerReceive);
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            StreamingResponseDisconnectListenerStep::Complete => {
                self.advance(StreamingResponseDisconnectCallInput::ListenerFinished(Ok(
                    (),
                )))?;
                match self.cancel_task_group(py) {
                    Ok(()) => self.leave_task_group(py, None),
                    Err(error) => self.leave_task_group(py, Some(&error)),
                }
            }
            StreamingResponseDisconnectListenerStep::Failed => Err(PyRuntimeError::new_err(
                "streaming disconnect listener is already failed",
            )),
        }
    }

    fn finish_receive(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message_type = match message.bind(py).get_item("type") {
            Ok(message_type) => message_type,
            Err(error) => return self.finish_listener_error(py, error),
        };
        let is_disconnect = match message_type.eq("http.disconnect") {
            Ok(is_disconnect) => is_disconnect,
            Err(error) => return self.finish_listener_error(py, error),
        };
        let message = if is_disconnect {
            StreamingResponseDisconnectMessage::Disconnect
        } else {
            StreamingResponseDisconnectMessage::Other
        };
        self.listener
            .advance(StreamingResponseDisconnectListenerInput::Received(message))
            .map_err(streaming_disconnect_listener_error)?;
        self.next_action(py)
    }

    fn finish_listener_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let step = self.call.borrow().step();
        let cancelled = is_anyio_cancellation(py, &error)?;
        match step {
            StreamingResponseDisconnectCallStep::AwaitFirstCompletion if cancelled => {
                self.advance(StreamingResponseDisconnectCallInput::Cancelled(
                    error.clone_ref(py),
                ))?;
            }
            StreamingResponseDisconnectCallStep::AwaitFirstCompletion => {
                self.listener
                    .advance(StreamingResponseDisconnectListenerInput::ReceiveFailed(
                        error.clone_ref(py),
                    ))
                    .map_err(streaming_disconnect_listener_error)?;
                self.advance(StreamingResponseDisconnectCallInput::ListenerFinished(Err(
                    error.clone_ref(py),
                )))?;
            }
            StreamingResponseDisconnectCallStep::CancelListener if cancelled => {
                // The stream child completed first and cancelled this task
                // through the task group's own scope. Passing the cancellation
                // to __aexit__ lets AnyIO suppress its own cancellation while
                // still reporting any error raised by stream cleanup.
            }
            StreamingResponseDisconnectCallStep::CancelStream
            | StreamingResponseDisconnectCallStep::CancelListener
            | StreamingResponseDisconnectCallStep::CancelBoth => {}
            _ => return Err(error),
        }

        self.leave_task_group(py, Some(&error))
    }

    fn leave_task_group(
        &mut self,
        py: Python<'_>,
        body_error: Option<&PyErr>,
    ) -> PyResult<MachineAction> {
        let task_group = self.task_group_ref(py)?;
        let awaitable = match body_error {
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
        self.pending = Some(StreamingDisconnectPending::TaskGroupExit);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_task_group_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let error = collapse_single_task_group_error(py, error)?;
        let step = self.call.borrow().step();
        if is_anyio_cancellation(py, &error)?
            && step == StreamingResponseDisconnectCallStep::AwaitFirstCompletion
        {
            self.advance(StreamingResponseDisconnectCallInput::Cancelled(
                error.clone_ref(py),
            ))?;
        }
        if !matches!(
            self.call.borrow().step(),
            StreamingResponseDisconnectCallStep::CancelStream
                | StreamingResponseDisconnectCallStep::CancelListener
                | StreamingResponseDisconnectCallStep::CancelBoth
        ) {
            // Task-group startup can fail before the Rust coordinator records
            // that both concurrent branches started. The group has still been
            // exited above; preserve that original setup error unchanged.
            return Err(error);
        }
        self.advance(StreamingResponseDisconnectCallInput::ConcurrentFinished(
            Err(error.clone_ref(py)),
        ))?;
        self.next_action(py)
    }

    fn run_background(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let Some(background) = self.background.as_ref() else {
            return Err(PyRuntimeError::new_err(
                "stream requested a missing background callback",
            ));
        };
        let awaitable = match background.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.advance(StreamingResponseDisconnectCallInput::BackgroundFinished(
                    Err(error.clone_ref(py)),
                ))?;
                return Err(error);
            }
        };
        self.pending = Some(StreamingDisconnectPending::Background);
        Ok(MachineAction::Await(awaitable.unbind()))
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
            .ok_or_else(|| PyRuntimeError::new_err("streaming task group was not initialized"))
    }

    fn advance(
        &self,
        input: StreamingResponseDisconnectCallInput<PyErr>,
    ) -> PyResult<StreamingResponseDisconnectCallStep> {
        self.call
            .borrow_mut()
            .advance(input)
            .map_err(streaming_disconnect_call_error)
    }
}

struct StreamingResponseChildMachine {
    stream: StreamingCallMachine,
    call: Rc<RefCell<StreamingResponseDisconnectCall<PyErr>>>,
    cancel_scope: Py<PyAny>,
}

impl AwaitableStateMachine for StreamingResponseChildMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match self.stream.resume(py, input) {
            Ok(MachineAction::Complete(result)) => {
                if self.call.borrow().step()
                    == StreamingResponseDisconnectCallStep::AwaitFirstCompletion
                {
                    self.record_stream_completion(py, Ok(()))?;
                }
                self.cancel_scope.bind(py).call_method0("cancel")?;
                Ok(MachineAction::Complete(result))
            }
            Ok(action) => Ok(action),
            Err(error) => {
                if !is_anyio_cancellation(py, &error)? {
                    let mut call = self.call.borrow_mut();
                    if call.step() == StreamingResponseDisconnectCallStep::AwaitFirstCompletion {
                        call.advance(StreamingResponseDisconnectCallInput::StreamFinished(Err(
                            error.clone_ref(py),
                        )))
                        .map_err(streaming_disconnect_call_error)?;
                    }
                }
                Err(error)
            }
        }
    }
}

impl StreamingResponseChildMachine {
    fn record_stream_completion(
        &self,
        _py: Python<'_>,
        result: Result<(), PyErr>,
    ) -> PyResult<StreamingResponseDisconnectCallStep> {
        self.call
            .borrow_mut()
            .advance(StreamingResponseDisconnectCallInput::StreamFinished(result))
            .map_err(streaming_disconnect_call_error)
    }
}

#[pyclass(unsendable)]
struct AwaitableFactory {
    awaitable: Py<PyAny>,
}

#[pymethods]
impl AwaitableFactory {
    fn __call__(&self, py: Python<'_>) -> Py<PyAny> {
        self.awaitable.clone_ref(py)
    }
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyStreamingResponse>()
}

fn streaming_response_call_state(
    response: &NativeStreamingResponse,
    status_code_override: Option<u16>,
    has_background_callback: bool,
) -> StreamingResponseCall {
    match status_code_override {
        Some(status_code) => {
            response.call_state_with_status_code(status_code, has_background_callback)
        }
        None => response.call_state(has_background_callback),
    }
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

fn response_event_to_py<'py>(
    py: Python<'py>,
    event: ResponseEvent,
    websocket: bool,
    body_override: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
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
            match body_override {
                Some(body) => message.set_item("body", body)?,
                None => message.set_item("body", PyBytes::new(py, &body))?,
            }
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

fn streaming_disconnect_listener_error(
    error: StreamingResponseDisconnectListenerError<PyErr>,
) -> PyErr {
    match error {
        StreamingResponseDisconnectListenerError::Operation(error) => error,
        StreamingResponseDisconnectListenerError::UnexpectedInput => PyRuntimeError::new_err(
            "unexpected result for current streaming disconnect listener step",
        ),
    }
}

fn streaming_disconnect_call_error(error: StreamingResponseDisconnectCallError<PyErr>) -> PyErr {
    match error {
        StreamingResponseDisconnectCallError::Operation(error) => error,
        StreamingResponseDisconnectCallError::UnexpectedInput => {
            PyRuntimeError::new_err("unexpected result for current streaming disconnect call step")
        }
    }
}

fn is_anyio_cancellation(py: Python<'_>, error: &PyErr) -> PyResult<bool> {
    let cancellation_class = py
        .import("anyio")?
        .getattr("get_cancelled_exc_class")?
        .call0()?;
    error.value(py).is_instance(&cancellation_class)
}

pub(crate) fn collapse_single_task_group_error(py: Python<'_>, error: PyErr) -> PyResult<PyErr> {
    let base_exception_group = match py.import("builtins")?.getattr("BaseExceptionGroup") {
        Ok(base_exception_group) => base_exception_group,
        Err(attribute_error) if attribute_error.is_instance_of::<PyAttributeError>(py) => {
            match py
                .import("exceptiongroup")
                .and_then(|module| module.getattr("BaseExceptionGroup"))
            {
                Ok(base_exception_group) => base_exception_group,
                Err(import_error) if import_error.is_instance_of::<PyImportError>(py) => {
                    return Ok(error);
                }
                Err(import_error) => return Err(import_error),
            }
        }
        Err(error) => return Err(error),
    };
    let exception = error.value(py);
    if !exception.is_instance(&base_exception_group)? {
        return Ok(error);
    }

    let exception_items = exception.getattr("exceptions")?;
    let exceptions = exception_items.cast::<PyTuple>()?;
    if exceptions.len() != 1 {
        return Ok(error);
    }

    let collapsed = exceptions.get_item(0)?;
    let suppress_context = collapsed
        .getattr("__suppress_context__")?
        .extract::<bool>()?;
    let original_cause = collapsed.getattr("__cause__")?;
    let cause = if original_cause.is_truthy()? {
        Some(PyErr::from_value(original_cause))
    } else if suppress_context {
        None
    } else {
        let original_context = collapsed.getattr("__context__")?;
        if original_context.is_none() {
            None
        } else {
            Some(PyErr::from_value(original_context))
        }
    };

    let collapsed_error = PyErr::from_value(collapsed);
    collapsed_error.set_context(py, Some(error));
    collapsed_error.set_cause(py, cause);
    Ok(collapsed_error)
}

fn response_error(error: ResponseError) -> PyErr {
    cookie_runtime::response_error(error)
}
