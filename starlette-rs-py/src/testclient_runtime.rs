//! Rust-owned HTTPX-to-ASGI transport for Starlette's synchronous TestClient.

use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::basic::CompareOp;
use pyo3::create_exception;
use pyo3::exceptions::{PyAssertionError, PyException, PyImportError, PyKeyError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

create_exception!(_core, WebSocketUpgrade, PyException);

#[pyclass(name = "TestClientTransport")]
pub(crate) struct PyTestClientTransport {
    app: Py<PyAny>,
    httpx: Py<PyAny>,
    asgi3_runner: Py<PyAny>,
    asgi2_runner: Py<PyAny>,
    backend: String,
    backend_options: Py<PyDict>,
    raise_server_exceptions: bool,
    root_path: String,
    client_host: String,
    client_port: u16,
    app_state: Py<PyDict>,
    lifespan: Option<TestClientLifespan>,
}

#[derive(Default)]
struct TestClientLifespan {
    portal_manager: Option<Py<PyAny>>,
    portal: Option<Py<PyAny>>,
    portal_entered: bool,
    client_to_app_send: Option<Py<PyAny>>,
    app_to_client_receive: Option<Py<PyAny>>,
    app_to_client_send: Option<Py<PyAny>>,
    client_to_app_receive: Option<Py<PyAny>>,
    task: Option<Py<PyAny>>,
}

enum LifespanTaskPhase {
    App,
    CompletionSignal,
}

struct LifespanTaskMachine {
    runner: Py<PyAny>,
    app: Py<PyAny>,
    scope: Py<PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    completion_send: Py<PyAny>,
    phase: LifespanTaskPhase,
    app_error: Option<PyErr>,
}

#[pyclass]
struct LifespanTaskCallable {
    runner: Py<PyAny>,
    app: Py<PyAny>,
    scope: Py<PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    completion_send: Py<PyAny>,
}

#[pymethods]
impl LifespanTaskCallable {
    fn __call__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            LifespanTaskMachine {
                runner: self.runner.clone_ref(py),
                app: self.app.clone_ref(py),
                scope: self.scope.clone_ref(py),
                receive: self.receive.clone_ref(py),
                send: self.send.clone_ref(py),
                completion_send: self.completion_send.clone_ref(py),
                phase: LifespanTaskPhase::App,
                app_error: None,
            },
        )
    }
}

impl LifespanTaskMachine {
    fn send_completion(
        &mut self,
        py: Python<'_>,
        app_error: Option<PyErr>,
    ) -> PyResult<MachineAction> {
        self.phase = LifespanTaskPhase::CompletionSignal;
        self.app_error = app_error;
        let completion = self
            .completion_send
            .bind(py)
            .call_method1("send", (py.None(),))?;
        Ok(MachineAction::Await(completion.unbind()))
    }
}

impl AwaitableStateMachine for LifespanTaskMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match (&self.phase, input) {
            (LifespanTaskPhase::App, MachineResume::Start) => {
                let awaitable = self.runner.bind(py).call1((
                    self.app.bind(py),
                    self.scope.bind(py),
                    self.receive.bind(py),
                    self.send.bind(py),
                ));
                match awaitable {
                    Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
                    Err(error) => self.send_completion(py, Some(error)),
                }
            }
            (LifespanTaskPhase::App, MachineResume::Value(_)) => self.send_completion(py, None),
            (LifespanTaskPhase::App, MachineResume::AsyncIterationComplete(error))
            | (LifespanTaskPhase::App, MachineResume::Error(error)) => {
                self.send_completion(py, Some(error))
            }
            (LifespanTaskPhase::CompletionSignal, MachineResume::Value(_)) => {
                if let Some(error) = self.app_error.take() {
                    Err(error)
                } else {
                    Ok(MachineAction::Complete(py.None()))
                }
            }
            (
                LifespanTaskPhase::CompletionSignal,
                MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error),
            ) => Err(error),
            (LifespanTaskPhase::CompletionSignal, MachineResume::Start) => Err(
                PyRuntimeError::new_err("lifespan completion resumed before awaiting its signal"),
            ),
        }
    }
}

impl TestClientLifespan {
    fn start(
        py: Python<'_>,
        app: Py<PyAny>,
        runner: Py<PyAny>,
        app_state: Py<PyDict>,
        backend: &str,
        backend_options: &Py<PyDict>,
    ) -> PyResult<Self> {
        let mut lifespan = Self::default();
        if let Err(error) =
            lifespan.start_inner(py, app, runner, app_state, backend, backend_options)
        {
            let _ = lifespan.cleanup(py, false, None);
            return Err(error);
        }
        Ok(lifespan)
    }

    fn start_inner(
        &mut self,
        py: Python<'_>,
        app: Py<PyAny>,
        runner: Py<PyAny>,
        app_state: Py<PyDict>,
        backend: &str,
        backend_options: &Py<PyDict>,
    ) -> PyResult<()> {
        let anyio = py.import("anyio")?;
        let portal_kwargs = PyDict::new(py);
        portal_kwargs.set_item("backend", backend)?;
        portal_kwargs.set_item("backend_options", backend_options.bind(py))?;
        let manager = anyio
            .getattr("from_thread")?
            .getattr("start_blocking_portal")?
            .call((), Some(&portal_kwargs))?;
        self.portal_manager = Some(manager.unbind());
        let manager = self
            .portal_manager
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("TestClient portal manager is unavailable"))?;
        let portal = manager.bind(py).call_method0("__enter__")?;
        self.portal = Some(portal.unbind());
        self.portal_entered = true;

        let capacity = py.import("math")?.getattr("inf")?;
        let stream_factory = anyio.getattr("create_memory_object_stream")?;
        let client_to_app = stream_factory
            .call1((capacity.clone(),))?
            .cast_into::<PyTuple>()?;
        self.client_to_app_send = Some(client_to_app.get_item(0)?.unbind());
        self.client_to_app_receive = Some(client_to_app.get_item(1)?.unbind());
        let app_to_client = stream_factory.call1((capacity,))?.cast_into::<PyTuple>()?;
        self.app_to_client_send = Some(app_to_client.get_item(0)?.unbind());
        self.app_to_client_receive = Some(app_to_client.get_item(1)?.unbind());

        let scope = PyDict::new(py);
        scope.set_item("type", "lifespan")?;
        scope.set_item("state", app_state.bind(py))?;
        let receive = self
            .client_to_app_receive
            .as_ref()
            .ok_or_else(|| {
                PyRuntimeError::new_err("TestClient lifespan receive stream is unavailable")
            })?
            .bind(py)
            .getattr("receive")?
            .unbind();
        let send = self
            .app_to_client_send
            .as_ref()
            .ok_or_else(|| {
                PyRuntimeError::new_err("TestClient lifespan send stream is unavailable")
            })?
            .bind(py)
            .getattr("send")?
            .unbind();
        let completion_send = self
            .app_to_client_send
            .as_ref()
            .ok_or_else(|| {
                PyRuntimeError::new_err("TestClient lifespan completion stream is unavailable")
            })?
            .clone_ref(py);
        let task_callable = Py::new(
            py,
            LifespanTaskCallable {
                runner,
                app,
                scope: scope.unbind(),
                receive,
                send,
                completion_send,
            },
        )?;
        let portal = self
            .portal
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("TestClient portal is unavailable"))?;
        let task = portal
            .bind(py)
            .call_method1("start_task_soon", (task_callable,))?;
        self.task = Some(task.unbind());
        self.handshake(py, true)
    }

    fn handshake(&self, py: Python<'_>, startup: bool) -> PyResult<()> {
        let portal = self
            .portal
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("TestClient portal is unavailable"))?;
        let (event, complete, failed) = if startup {
            (
                "lifespan.startup",
                "lifespan.startup.complete",
                "lifespan.startup.failed",
            )
        } else {
            (
                "lifespan.shutdown",
                "lifespan.shutdown.complete",
                "lifespan.shutdown.failed",
            )
        };
        let send_stream = self.client_to_app_send.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("TestClient lifespan send stream is unavailable")
        })?;
        let receive_stream = self.app_to_client_receive.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("TestClient lifespan receive stream is unavailable")
        })?;
        let message = PyDict::new(py);
        message.set_item("type", event)?;
        let send = send_stream.bind(py).getattr("send")?;
        portal.bind(py).call_method1("call", (send, message))?;

        let response = self.receive_lifespan_message(py, portal.bind(py), receive_stream)?;
        let response_type = response.bind(py).get_item("type")?.extract::<String>()?;
        if response_type != complete && response_type != failed {
            return Err(PyAssertionError::new_err(()));
        }
        if response_type == failed {
            let _ = self.receive_lifespan_message(py, portal.bind(py), receive_stream)?;
        }
        Ok(())
    }

    fn receive_lifespan_message(
        &self,
        py: Python<'_>,
        portal: &Bound<'_, PyAny>,
        receive_stream: &Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let receive = receive_stream.bind(py).getattr("receive")?;
        let message = portal.call_method1("call", (receive,))?;
        if message.is_none() {
            self.task
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("TestClient lifespan task is unavailable"))?
                .bind(py)
                .call_method0("result")?;
        }
        Ok(message.unbind())
    }

    fn cleanup(
        &mut self,
        py: Python<'_>,
        wait_shutdown: bool,
        mut primary_error: Option<PyErr>,
    ) -> PyResult<()> {
        if wait_shutdown && self.portal.is_some() {
            if let Err(error) = self.handshake(py, false) {
                if primary_error.is_none() {
                    primary_error = Some(error);
                }
            }
        }

        for stream in [
            self.client_to_app_send.take(),
            self.client_to_app_receive.take(),
            self.app_to_client_send.take(),
            self.app_to_client_receive.take(),
        ]
        .into_iter()
        .flatten()
        {
            if let Err(error) = stream.bind(py).call_method0("close") {
                if primary_error.is_none() {
                    primary_error = Some(error);
                }
            }
        }

        self.task = None;
        self.portal = None;
        let manager = self.portal_manager.take();
        if self.portal_entered {
            if let Some(manager) = manager {
                if let Err(error) =
                    exit_portal(py, manager.bind(py).clone(), primary_error.as_ref())
                {
                    if primary_error.is_none() {
                        primary_error = Some(error);
                    }
                }
            }
        }
        self.portal_entered = false;

        match primary_error {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

impl PyTestClientTransport {
    fn start_lifespan(&mut self, py: Python<'_>) -> PyResult<()> {
        if self.lifespan.is_some() {
            return Err(PyRuntimeError::new_err("TestClient is already entered"));
        }
        let runner = if is_asgi3(py, self.app.bind(py))? {
            self.asgi3_runner.clone_ref(py)
        } else {
            self.asgi2_runner.clone_ref(py)
        };
        let lifespan = TestClientLifespan::start(
            py,
            self.app.clone_ref(py),
            runner,
            self.app_state.clone_ref(py),
            &self.backend,
            &self.backend_options,
        )?;
        self.lifespan = Some(lifespan);
        Ok(())
    }

    fn stop_lifespan(&mut self, py: Python<'_>) -> PyResult<()> {
        match self.lifespan.take() {
            Some(mut lifespan) => lifespan.cleanup(py, true, None),
            None => Ok(()),
        }
    }
}

/// Internal transport signal used to return a Rust-owned WebSocket session
/// through HTTPX's synchronous request path.
#[pyclass(name = "_WebSocketTestSession", unsendable)]
struct PyWebSocketTestSession {
    app: Py<PyAny>,
    runner: Py<PyAny>,
    scope: Py<PyDict>,
    backend: String,
    backend_options: Py<PyDict>,
    portal_manager: Option<Py<PyAny>>,
    portal: Option<Py<PyAny>>,
    client_to_app_send: Option<Py<PyAny>>,
    client_to_app_receive: Option<Py<PyAny>>,
    app_to_client_send: Option<Py<PyAny>>,
    app_to_client_receive: Option<Py<PyAny>>,
    task: Option<Py<PyAny>>,
    accepted_subprotocol: Option<String>,
    accepted: bool,
    client_closed: bool,
}

impl PyWebSocketTestSession {
    fn new(
        app: Py<PyAny>,
        runner: Py<PyAny>,
        scope: Py<PyDict>,
        backend: String,
        backend_options: Py<PyDict>,
    ) -> Self {
        Self {
            app,
            runner,
            scope,
            backend,
            backend_options,
            portal_manager: None,
            portal: None,
            client_to_app_send: None,
            client_to_app_receive: None,
            app_to_client_send: None,
            app_to_client_receive: None,
            task: None,
            accepted_subprotocol: None,
            accepted: false,
            client_closed: false,
        }
    }

    fn start(&mut self, py: Python<'_>) -> PyResult<()> {
        if self.portal.is_some() {
            return Err(PyRuntimeError::new_err(
                "WebSocketTestSession is already entered",
            ));
        }
        self.accepted = false;
        self.client_closed = false;

        let anyio = py.import("anyio")?;
        let portal_kwargs = PyDict::new(py);
        portal_kwargs.set_item("backend", &self.backend)?;
        portal_kwargs.set_item("backend_options", self.backend_options.bind(py))?;
        let manager = anyio
            .getattr("from_thread")?
            .getattr("start_blocking_portal")?
            .call((), Some(&portal_kwargs))?;
        let portal = manager.call_method0("__enter__")?;
        self.portal_manager = Some(manager.unbind());
        self.portal = Some(portal.clone().unbind());

        let capacity = py.import("math")?.getattr("inf")?;
        let stream_factory = anyio.getattr("create_memory_object_stream")?;
        let client_to_app = stream_factory
            .call1((capacity.clone(),))?
            .cast_into::<PyTuple>()?;
        let client_to_app_send = client_to_app.get_item(0)?.unbind();
        let client_to_app_receive = client_to_app.get_item(1)?.unbind();
        let app_to_client = stream_factory.call1((capacity,))?.cast_into::<PyTuple>()?;
        let app_to_client_send = app_to_client.get_item(0)?.unbind();
        let app_to_client_receive = app_to_client.get_item(1)?.unbind();

        let receive = client_to_app_receive.bind(py).getattr("receive")?.unbind();
        let send = app_to_client_send.bind(py).getattr("send")?.unbind();
        let task_args = PyTuple::new(
            py,
            [
                self.runner.bind(py),
                self.app.bind(py),
                self.scope.bind(py),
                receive.bind(py),
                send.bind(py),
            ],
        )?;
        let task = portal.call_method1("start_task_soon", task_args)?;

        self.client_to_app_send = Some(client_to_app_send);
        self.client_to_app_receive = Some(client_to_app_receive);
        self.app_to_client_send = Some(app_to_client_send);
        self.app_to_client_receive = Some(app_to_client_receive);
        self.task = Some(task.unbind());

        self.send_client_message(py, websocket_connect_message(py)?)?;
        let message = self.receive_app_message(py)?;
        let message = message.bind(py).cast::<PyDict>()?;
        let message_type = message
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        match message_type.as_str() {
            "websocket.accept" => {
                self.accepted_subprotocol = message
                    .get_item("subprotocol")?
                    .filter(|value| !value.is_none())
                    .map(|value| value.extract::<String>())
                    .transpose()?;
                self.accepted = true;
                Ok(())
            }
            "websocket.close" => Err(websocket_disconnect(py, message)?),
            "websocket.http.response.start" => Err(self.websocket_denial_response(py, message)?),
            _ => Err(PyRuntimeError::new_err(format!(
                "expected a WebSocket accept message, got {message_type:?}"
            ))),
        }
    }

    fn websocket_denial_response(
        &self,
        py: Python<'_>,
        start_message: &Bound<'_, PyDict>,
    ) -> PyResult<PyErr> {
        let status = start_message
            .get_item("status")?
            .ok_or_else(|| PyKeyError::new_err("status"))?;
        let headers = start_message
            .get_item("headers")?
            .ok_or_else(|| PyKeyError::new_err("headers"))?;
        let body_chunks = PyList::empty(py);

        loop {
            let message = self.receive_app_message(py)?;
            let message = message.bind(py).cast::<PyDict>()?;
            let message_type = message
                .get_item("type")?
                .ok_or_else(|| PyKeyError::new_err("type"))?;
            let is_body_message = message_type
                .rich_compare("websocket.http.response.body", CompareOp::Eq)?
                .is_truthy()?;
            if !is_body_message {
                return Err(PyAssertionError::new_err(()));
            }
            body_chunks.append(
                message
                    .get_item("body")?
                    .ok_or_else(|| PyKeyError::new_err("body"))?,
            )?;
            let more_body = message
                .get_item("more_body")?
                .map(|value| value.is_truthy())
                .transpose()?
                .unwrap_or(false);
            if !more_body {
                break;
            }
        }

        let content = PyBytes::new(py, b"").call_method1("join", (body_chunks,))?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("status_code", status)?;
        kwargs.set_item("headers", headers)?;
        kwargs.set_item("content", content)?;
        let exception_type = py
            .import("starlette.testclient")?
            .getattr("WebSocketDenialResponse")?;
        let exception = exception_type.call((), Some(&kwargs))?;
        Ok(PyErr::from_value(exception))
    }

    fn send_client_message(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<()> {
        let portal = self
            .portal
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocketTestSession is not entered"))?;
        let stream = self.client_to_app_send.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("WebSocketTestSession client send stream is unavailable")
        })?;
        let args = PyTuple::new(
            py,
            [stream.bind(py).getattr("send")?, message.bind(py).into()],
        )?;
        portal.bind(py).call_method1("call", args)?;
        Ok(())
    }

    fn receive_app_message(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let portal = self
            .portal
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocketTestSession is not entered"))?;
        let stream = self.app_to_client_receive.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("WebSocketTestSession client receive stream is unavailable")
        })?;
        portal
            .bind(py)
            .call_method1("call", (stream.bind(py).getattr("receive")?,))
            .map(Bound::unbind)
    }

    fn send_text_inner(&self, py: Python<'_>, data: &str) -> PyResult<()> {
        let message = PyDict::new(py);
        message.set_item("type", "websocket.receive")?;
        message.set_item("text", data)?;
        self.send_client_message(py, message.into_any().unbind())
    }

    fn send_bytes_inner(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        let message = PyDict::new(py);
        message.set_item("type", "websocket.receive")?;
        message.set_item("bytes", data)?;
        self.send_client_message(py, message.into_any().unbind())
    }

    fn close_inner(&mut self, py: Python<'_>, code: u16) -> PyResult<()> {
        let message = websocket_disconnect_message(py, code)?;
        self.send_client_message(py, message)?;
        self.client_closed = true;
        Ok(())
    }

    fn teardown(&mut self, py: Python<'_>) -> PyResult<()> {
        let mut task_error = None;
        if self.portal.is_some() && self.accepted && !self.client_closed {
            if let Err(error) = self.close_inner(py, 1000) {
                task_error = Some(error);
            }
        }

        if let (Some(portal), Some(task)) = (self.portal.as_ref(), self.task.as_ref()) {
            let _ = portal
                .bind(py)
                .call_method1("call", (py.import("anyio")?.getattr("sleep")?, 0));
            let done = task.bind(py).call_method0("done")?.extract::<bool>()?;
            if !done {
                task.bind(py).call_method0("cancel")?;
            }
            if let Err(error) = task.bind(py).call_method0("result") {
                if !is_cancelled_error(py, &error)? && task_error.is_none() {
                    task_error = Some(error);
                }
            }
        }

        for stream in [
            self.client_to_app_send.take(),
            self.client_to_app_receive.take(),
            self.app_to_client_send.take(),
            self.app_to_client_receive.take(),
        ]
        .into_iter()
        .flatten()
        {
            let _ = stream.bind(py).call_method0("close");
        }

        self.task = None;
        self.portal = None;
        let manager = self.portal_manager.take();
        if let Some(manager) = manager {
            exit_portal(py, manager.bind(py).clone(), task_error.as_ref())?;
        }

        match task_error {
            Some(error) => Err(error),
            None => Ok(()),
        }
    }
}

#[pymethods]
impl PyWebSocketTestSession {
    #[getter]
    fn accepted_subprotocol(&self) -> Option<String> {
        self.accepted_subprotocol.clone()
    }

    fn __enter__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        let result = slf.borrow_mut(py).start(py);
        if let Err(error) = result {
            let _ = slf.borrow_mut(py).teardown(py);
            return Err(error);
        }
        Ok(slf)
    }

    fn __exit__(
        slf: Py<Self>,
        py: Python<'_>,
        _exception_type: Py<PyAny>,
        _exception_value: Py<PyAny>,
        _traceback: Py<PyAny>,
    ) -> PyResult<bool> {
        slf.borrow_mut(py).teardown(py)?;
        Ok(false)
    }

    fn send_text(&self, py: Python<'_>, data: &str) -> PyResult<()> {
        self.send_text_inner(py, data)
    }

    fn receive_text(&self, py: Python<'_>) -> PyResult<String> {
        let message = self.receive_app_message(py)?;
        let message = message.bind(py).cast::<PyDict>()?;
        let message_type = message
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if message_type == "websocket.close" {
            return Err(websocket_disconnect(py, message)?);
        }
        message
            .get_item("text")?
            .ok_or_else(|| PyKeyError::new_err("text"))?
            .extract::<String>()
    }

    fn send_bytes(&self, py: Python<'_>, data: Py<PyAny>) -> PyResult<()> {
        self.send_bytes_inner(py, data.bind(py))
    }

    fn receive_bytes(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let message = self.receive_app_message(py)?;
        let message = message.bind(py).cast::<PyDict>()?;
        let message_type = message
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if message_type == "websocket.close" {
            return Err(websocket_disconnect(py, message)?);
        }
        message
            .get_item("bytes")?
            .ok_or_else(|| PyKeyError::new_err("bytes"))
            .map(Bound::unbind)
    }

    #[pyo3(signature = (code=1000))]
    fn close(&mut self, py: Python<'_>, code: u16) -> PyResult<()> {
        self.close_inner(py, code)
    }
}

#[derive(Default)]
struct TestClientResponseState {
    request_body: Vec<u8>,
    request_complete: bool,
    response_started: bool,
    response_complete: bool,
    status_code: Option<u16>,
    headers: Vec<(String, String)>,
    body: Vec<u8>,
    debug_info: Option<Py<PyAny>>,
    response_complete_event: Option<Py<PyAny>>,
    method: String,
}

type SharedResponseState = Arc<Mutex<TestClientResponseState>>;

#[pyclass]
struct TestClientReceive {
    state: SharedResponseState,
}

#[pyclass]
struct TestClientSend {
    state: SharedResponseState,
}

struct TestClientReceiveMachine {
    state: SharedResponseState,
    waiting_for_response: bool,
}

struct TestClientSendMachine {
    state: SharedResponseState,
    message: Py<PyAny>,
}

impl AwaitableStateMachine for TestClientReceiveMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(_) if self.waiting_for_response => {
                Ok(MachineAction::Complete(disconnect_message(py)?))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "TestClient receive resumed without a pending response wait",
            )),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }
}

impl TestClientReceiveMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let event = {
            let mut state = lock_state(&self.state)?;
            if !state.request_complete {
                state.request_complete = true;
                return Ok(MachineAction::Complete(request_message(
                    py,
                    &state.request_body,
                )?));
            }
            state
                .response_complete_event
                .as_ref()
                .ok_or_else(|| {
                    PyRuntimeError::new_err("TestClient response completion event is unavailable")
                })?
                .clone_ref(py)
        };
        let event = event.bind(py);
        if event.call_method0("is_set")?.extract::<bool>()? {
            return Ok(MachineAction::Complete(disconnect_message(py)?));
        }
        self.waiting_for_response = true;
        Ok(MachineAction::Await(event.call_method0("wait")?.unbind()))
    }
}

impl AwaitableStateMachine for TestClientSendMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                apply_send_message(py, &self.state, self.message.bind(py))?;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "TestClient send resumed without a pending await",
            )),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }
}

#[pymethods]
impl TestClientReceive {
    fn __call__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            TestClientReceiveMachine {
                state: Arc::clone(&self.state),
                waiting_for_response: false,
            },
        )
    }
}

#[pymethods]
impl TestClientSend {
    fn __call__(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            TestClientSendMachine {
                state: Arc::clone(&self.state),
                message,
            },
        )
    }
}

#[pymethods]
impl PyTestClientTransport {
    #[new]
    #[pyo3(signature = (app, httpx, runners, settings))]
    fn new(
        py: Python<'_>,
        app: Py<PyAny>,
        httpx: Py<PyAny>,
        runners: (Py<PyAny>, Py<PyAny>),
        settings: Py<PyDict>,
    ) -> PyResult<Self> {
        let settings = settings.bind(py);
        let backend = settings
            .get_item("backend")?
            .ok_or_else(|| PyKeyError::new_err("backend"))?
            .extract::<String>()?;
        let backend_options = settings
            .get_item("backend_options")?
            .ok_or_else(|| PyKeyError::new_err("backend_options"))?;
        let backend_options = if backend_options.is_none() || !backend_options.is_truthy()? {
            PyDict::new(py).unbind()
        } else {
            backend_options.extract::<Py<PyDict>>()?
        };
        let raise_server_exceptions = settings
            .get_item("raise_server_exceptions")?
            .ok_or_else(|| PyKeyError::new_err("raise_server_exceptions"))?
            .extract::<bool>()?;
        let root_path = settings
            .get_item("root_path")?
            .ok_or_else(|| PyKeyError::new_err("root_path"))?
            .extract::<String>()?;
        let client = settings
            .get_item("client")?
            .ok_or_else(|| PyKeyError::new_err("client"))?
            .extract::<(String, u16)>()?;
        Ok(Self {
            app,
            httpx,
            asgi3_runner: runners.0,
            asgi2_runner: runners.1,
            backend,
            backend_options,
            raise_server_exceptions,
            root_path,
            client_host: client.0,
            client_port: client.1,
            app_state: PyDict::new(py).unbind(),
            lifespan: None,
        })
    }

    fn __enter__(slf: Py<Self>, py: Python<'_>, client: Py<PyAny>) -> PyResult<Py<PyAny>> {
        slf.borrow_mut(py).start_lifespan(py)?;
        Ok(client)
    }

    #[pyo3(signature = (*args))]
    fn __exit__(slf: Py<Self>, py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<()> {
        let _ = args;
        slf.borrow_mut(py).stop_lifespan(py)
    }

    #[getter]
    fn app(&self, py: Python<'_>) -> Py<PyAny> {
        self.app.clone_ref(py)
    }

    #[getter]
    fn app_state(&self, py: Python<'_>) -> Py<PyDict> {
        self.app_state.clone_ref(py)
    }

    #[getter]
    fn async_backend(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let config = PyDict::new(py);
        config.set_item("backend", &self.backend)?;
        config.set_item("backend_options", self.backend_options.bind(py))?;
        Ok(config.unbind())
    }

    fn default_headers(&self, py: Python<'_>, headers: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        let headers = match headers {
            Some(headers) => headers,
            None => PyDict::new(py).into_any().unbind(),
        };
        headers
            .bind(py)
            .call_method1("setdefault", ("user-agent", "testclient"))?;
        Ok(headers)
    }

    fn handle_request(&self, py: Python<'_>, request: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let request = request.bind(py);
        let scheme = request
            .getattr("url")?
            .getattr("scheme")?
            .extract::<String>()?;
        if scheme == "ws" || scheme == "wss" {
            let scope = build_websocket_scope(
                py,
                request,
                &self.root_path,
                (&self.client_host, self.client_port),
                self.app_state.bind(py),
            )?;
            let runner = if is_asgi3(py, self.app.bind(py))? {
                self.asgi3_runner.clone_ref(py)
            } else {
                self.asgi2_runner.clone_ref(py)
            };
            let session = Py::new(
                py,
                PyWebSocketTestSession::new(
                    self.app.clone_ref(py),
                    runner,
                    scope,
                    self.backend.clone(),
                    self.backend_options.clone_ref(py),
                ),
            )?;
            let exception = py.get_type::<WebSocketUpgrade>().call0()?;
            exception.setattr("session", session)?;
            return Err(PyErr::from_value(exception));
        }
        let (scope, method, request_body) = build_http_scope(
            py,
            request,
            self.root_path.as_str(),
            (self.client_host.as_str(), self.client_port),
            self.app_state.bind(py),
        )?;
        let state = Arc::new(Mutex::new(TestClientResponseState {
            request_body,
            method,
            ..TestClientResponseState::default()
        }));
        let anyio = py.import("anyio")?;
        let (manager, portal) = if let Some(lifespan) = self.lifespan.as_ref() {
            let portal = lifespan
                .portal
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("TestClient portal is unavailable"))?
                .clone_ref(py);
            (None, portal)
        } else {
            let from_thread = anyio.getattr("from_thread")?;
            let start_portal = from_thread.getattr("start_blocking_portal")?;
            let portal_kwargs = PyDict::new(py);
            portal_kwargs.set_item("backend", &self.backend)?;
            portal_kwargs.set_item("backend_options", self.backend_options.bind(py))?;
            let manager = start_portal.call((), Some(&portal_kwargs))?;
            let portal = manager.call_method0("__enter__")?;
            (Some(manager.unbind()), portal.unbind())
        };
        let event = match portal
            .bind(py)
            .call_method1("call", (anyio.getattr("Event")?,))
        {
            Ok(event) => event,
            Err(error) => {
                if let Some(manager) = manager.as_ref() {
                    exit_portal(py, manager.bind(py).clone(), Some(&error))?;
                }
                return Err(error);
            }
        };
        lock_state(&state)?.response_complete_event = Some(event.unbind());
        let receive = Py::new(
            py,
            TestClientReceive {
                state: Arc::clone(&state),
            },
        )?;
        let send = Py::new(
            py,
            TestClientSend {
                state: Arc::clone(&state),
            },
        )?;
        let runner = if is_asgi3(py, self.app.bind(py))? {
            self.asgi3_runner.bind(py)
        } else {
            self.asgi2_runner.bind(py)
        };
        let app_result = portal
            .bind(py)
            .call_method1("call", (runner, self.app.bind(py), &scope, receive, send));
        if let Some(manager) = manager {
            match &app_result {
                Ok(_) => exit_portal(py, manager.bind(py).clone(), None)?,
                Err(error) => exit_portal(py, manager.bind(py).clone(), Some(error))?,
            }
        }
        if let Err(error) = app_result {
            if self.raise_server_exceptions {
                return Err(error);
            }
        }

        let (status_code, headers, body, debug_info, response_started) = {
            let state = lock_state(&state)?;
            (
                state.status_code,
                state.headers.clone(),
                if state.response_complete {
                    state.body.clone()
                } else {
                    Vec::new()
                },
                state.debug_info.as_ref().map(|info| info.clone_ref(py)),
                state.response_started,
            )
        };
        if self.raise_server_exceptions && !response_started {
            return Err(PyAssertionError::new_err(
                "TestClient did not receive any response.",
            ));
        }
        let response = self.httpx.bind(py).getattr("Response")?;
        let response_headers = PyList::empty(py);
        for (name, value) in headers {
            response_headers.append((name, value))?;
        }
        let response_kwargs = PyDict::new(py);
        response_kwargs.set_item("status_code", status_code.unwrap_or(500))?;
        response_kwargs.set_item("headers", response_headers)?;
        let response_stream = self
            .httpx
            .bind(py)
            .getattr("ByteStream")?
            .call1((PyBytes::new(py, &body),))?;
        response_kwargs.set_item("stream", response_stream)?;
        response_kwargs.set_item("request", request)?;
        let response = response.call((), Some(&response_kwargs))?;
        if let Some(debug_info) = debug_info {
            let extensions = response.getattr("extensions")?;
            extensions.set_item("http.response.debug", debug_info.bind(py))?;
            if let Ok(template) = debug_info.bind(py).get_item("template") {
                response.setattr("template", template)?;
            }
            if let Ok(context) = debug_info.bind(py).get_item("context") {
                response.setattr("context", context)?;
            }
        }
        Ok(response.unbind())
    }

    fn websocket_connect(
        &self,
        py: Python<'_>,
        client: Py<PyAny>,
        url: Py<PyAny>,
        subprotocols: Option<Py<PyAny>>,
        kwargs: Py<PyDict>,
    ) -> PyResult<Py<PyAny>> {
        let kwargs = kwargs.bind(py);
        let headers = match kwargs.get_item("headers")? {
            Some(headers) => headers,
            None => PyDict::new(py).into_any(),
        };
        headers.call_method1("setdefault", ("connection", "upgrade"))?;
        headers.call_method1("setdefault", ("sec-websocket-key", "testserver=="))?;
        headers.call_method1("setdefault", ("sec-websocket-version", "13"))?;
        if let Some(subprotocols) = subprotocols
            .as_ref()
            .filter(|value| !value.bind(py).is_none())
        {
            let protocol_header =
                PyString::new(py, ", ").call_method1("join", (subprotocols.bind(py),))?;
            headers.call_method1("setdefault", ("sec-websocket-protocol", protocol_header))?;
        }
        kwargs.set_item("headers", headers)?;

        let url = py
            .import("urllib.parse")?
            .getattr("urljoin")?
            .call1(("ws://testserver", url.bind(py)))?;
        let client_request = self.httpx.bind(py).getattr("Client")?.getattr("request")?;
        let request_args = PyTuple::new(
            py,
            [
                client.bind(py),
                PyString::new(py, "GET").as_any(),
                url.as_any(),
            ],
        )?;
        match client_request.call(request_args, Some(kwargs)) {
            Ok(_) => Err(PyRuntimeError::new_err("Expected WebSocket upgrade")),
            Err(error) if error.is_instance(py, &py.get_type::<WebSocketUpgrade>()) => {
                error.value(py).getattr("session").map(Bound::unbind)
            }
            Err(error) => Err(error),
        }
    }

    fn request(
        &self,
        py: Python<'_>,
        client: Py<PyAny>,
        method: Py<PyAny>,
        url: Py<PyAny>,
        kwargs: Py<PyDict>,
    ) -> PyResult<Py<PyAny>> {
        let kwargs = kwargs.bind(py);
        let use_default = self.httpx.bind(py).getattr("USE_CLIENT_DEFAULT")?;
        if kwargs
            .get_item("timeout")?
            .is_some_and(|timeout| !timeout.is(&use_default))
        {
            let warnings = py.import("warnings")?;
            let warning_category = py
                .import("starlette.exceptions")?
                .getattr("StarletteDeprecationWarning")?;
            warnings.getattr("warn")?.call1((
                "You should not use the 'timeout' argument with the TestClient. See https://github.com/Kludex/starlette/issues/1108 for more information.",
                warning_category,
                2,
            ))?;
        }
        let merged_url = client.bind(py).call_method1("_merge_url", (url,))?;
        let client_type = self.httpx.bind(py).getattr("Client")?;
        let parent_request = client_type.getattr("request")?;
        let args = PyTuple::new(py, [client.bind(py), method.bind(py), &merged_url])?;
        Ok(parent_request.call(args, Some(kwargs))?.unbind())
    }

    fn close(&self) {}
}

#[pyfunction]
pub(crate) fn testclient_httpx(py: Python<'_>) -> PyResult<Py<PyModule>> {
    match py.import("httpx2") {
        Ok(module) => Ok(module.unbind()),
        Err(error) if error.is_instance_of::<PyImportError>(py) => match py.import("httpx") {
            Ok(module) => {
                let warning_category = py
                    .import("starlette.exceptions")?
                    .getattr("StarletteDeprecationWarning")?;
                py.import("warnings")?.getattr("warn")?.call1((
                    "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.",
                    warning_category,
                    2,
                ))?;
                Ok(module.unbind())
            }
            Err(fallback_error) if fallback_error.is_instance_of::<PyImportError>(py) => {
                Err(PyRuntimeError::new_err(
                    "The starlette.testclient module requires the httpx2 package to be installed.\nYou can install this with:\n    $ pip install httpx2\n",
                ))
            }
            Err(fallback_error) => Err(fallback_error),
        },
        Err(error) => Err(error),
    }
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add(
        "_WebSocketUpgrade",
        module.py().get_type::<WebSocketUpgrade>(),
    )?;
    module.add_class::<PyTestClientTransport>()?;
    module.add_class::<PyWebSocketTestSession>()?;
    module.add_function(pyo3::wrap_pyfunction!(testclient_httpx, module)?)?;
    Ok(())
}

fn is_asgi3(py: Python<'_>, app: &Bound<'_, PyAny>) -> PyResult<bool> {
    let inspect = py.import("inspect")?;
    let is_class = inspect
        .getattr("isclass")?
        .call1((app,))?
        .extract::<bool>()?;
    if is_class {
        return app.hasattr("__await__");
    }

    let partial_type = py.import("functools")?.getattr("partial")?;
    let mut candidate = app.clone();
    while candidate.is_instance(&partial_type)? {
        candidate = candidate.getattr("func")?;
    }
    let is_coroutine_function = inspect.getattr("iscoroutinefunction")?;
    if is_coroutine_function
        .call1((&candidate,))?
        .extract::<bool>()?
    {
        return Ok(true);
    }
    let is_callable = py
        .import("builtins")?
        .getattr("callable")?
        .call1((&candidate,))?
        .extract::<bool>()?;
    if is_callable {
        return is_coroutine_function
            .call1((candidate.getattr("__call__")?,))?
            .extract::<bool>();
    }
    Ok(false)
}

fn lock_state(state: &SharedResponseState) -> PyResult<MutexGuard<'_, TestClientResponseState>> {
    state
        .lock()
        .map_err(|_| PyRuntimeError::new_err("TestClient response state lock is poisoned"))
}

fn request_message(py: Python<'_>, body: &[u8]) -> PyResult<Py<PyAny>> {
    let message = PyDict::new(py);
    message.set_item("type", "http.request")?;
    message.set_item("body", PyBytes::new(py, body))?;
    Ok(message.into_any().unbind())
}

fn disconnect_message(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let message = PyDict::new(py);
    message.set_item("type", "http.disconnect")?;
    Ok(message.into_any().unbind())
}

fn apply_send_message(
    py: Python<'_>,
    shared: &SharedResponseState,
    message: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let message = message.cast::<PyDict>()?;
    let message_type = message
        .get_item("type")?
        .ok_or_else(|| PyKeyError::new_err("type"))?
        .extract::<String>()
        .map_err(|_| PyKeyError::new_err("type"))?;
    let mut set_complete_event: Option<Py<PyAny>> = None;
    {
        let mut state = lock_state(shared)?;
        match message_type.as_str() {
            "http.response.start" => {
                if state.response_started {
                    return Err(PyAssertionError::new_err(
                        "Received multiple \"http.response.start\" messages.",
                    ));
                }
                state.status_code = Some(
                    message
                        .get_item("status")?
                        .ok_or_else(|| PyKeyError::new_err("status"))?
                        .extract::<u16>()?,
                );
                state.headers = decode_response_headers(py, message)?;
                state.response_started = true;
            }
            "http.response.body" => {
                if !state.response_started {
                    return Err(PyAssertionError::new_err(
                        "Received \"http.response.body\" without \"http.response.start\".",
                    ));
                }
                if state.response_complete {
                    return Err(PyAssertionError::new_err(
                        "Received \"http.response.body\" after response completed.",
                    ));
                }
                if let Some(body) = message.get_item("body")? {
                    if state.method != "HEAD" {
                        state
                            .body
                            .extend_from_slice(body.cast::<PyBytes>()?.as_bytes());
                    }
                }
                let more_body = message
                    .get_item("more_body")?
                    .map(|value| value.extract::<bool>())
                    .transpose()?
                    .unwrap_or(false);
                if !more_body {
                    state.response_complete = true;
                    set_complete_event = state
                        .response_complete_event
                        .as_ref()
                        .map(|event| event.clone_ref(py));
                }
            }
            "http.response.debug" => {
                let info = message
                    .get_item("info")?
                    .ok_or_else(|| PyKeyError::new_err("info"))?;
                state.debug_info = Some(info.unbind());
            }
            _ => {}
        }
    }
    if let Some(event) = set_complete_event {
        event.bind(py).call_method0("set")?;
    }
    Ok(())
}

fn decode_response_headers(
    _py: Python<'_>,
    message: &Bound<'_, PyAny>,
) -> PyResult<Vec<(String, String)>> {
    let message = message.cast::<PyDict>()?;
    let Some(headers) = message.get_item("headers")? else {
        return Ok(Vec::new());
    };
    let mut pairs = Vec::new();
    for item in headers.try_iter()? {
        let pair = item?.cast_into::<PyTuple>()?;
        let name = pair
            .get_item(0)?
            .call_method0("decode")?
            .extract::<String>()?;
        let value = pair
            .get_item(1)?
            .call_method0("decode")?
            .extract::<String>()?;
        pairs.push((name, value));
    }
    Ok(pairs)
}

fn build_websocket_scope(
    py: Python<'_>,
    request: &Bound<'_, PyAny>,
    root_path: &str,
    client: (&str, u16),
    app_state: &Bound<'_, PyDict>,
) -> PyResult<Py<PyDict>> {
    let url = request.getattr("url")?;
    let scheme = url.getattr("scheme")?.extract::<String>()?;
    let netloc = url
        .getattr("netloc")?
        .call_method1("decode", ("ascii",))?
        .extract::<String>()?;
    let default_port = match scheme.as_str() {
        "ws" => 80,
        "wss" => 443,
        _ => return Err(PyKeyError::new_err(scheme)),
    };
    let (host, port) = if let Some((host, port)) = netloc.split_once(':') {
        (
            host.to_owned(),
            port.parse::<u16>()
                .map_err(|_| PyRuntimeError::new_err("invalid TestClient URL port"))?,
        )
    } else {
        (netloc, default_port)
    };

    let path = url.getattr("path")?.extract::<String>()?;
    let raw_path = url
        .getattr("raw_path")?
        .cast::<PyBytes>()?
        .as_bytes()
        .to_vec();
    let query = url.getattr("query")?.call_method1("decode", ("ascii",))?;
    let query_string = query.call_method0("encode")?.cast_into::<PyBytes>()?;
    let path = py
        .import("urllib.parse")?
        .getattr("unquote")?
        .call1((path,))?;

    let request_headers = request.getattr("headers")?;
    let has_host = request_headers
        .call_method1("__contains__", ("host",))?
        .extract::<bool>()?;
    let headers = PyList::empty(py);
    if !has_host {
        let host_with_port = format!("{host}:{port}");
        let host_value = if port == default_port {
            host.as_str()
        } else {
            host_with_port.as_str()
        };
        headers.append((
            PyBytes::new(py, b"host"),
            PyBytes::new(py, host_value.as_bytes()),
        ))?;
    }
    let items = request_headers.call_method0("multi_items")?;
    for item in items.try_iter()? {
        let pair = item?.cast_into::<PyTuple>()?;
        let key = pair
            .get_item(0)?
            .call_method0("lower")?
            .call_method0("encode")?;
        let value = pair.get_item(1)?.call_method0("encode")?;
        headers.append((key, value))?;
    }

    let subprotocols = PyList::empty(py);
    let value = request_headers.call_method1("get", ("sec-websocket-protocol",))?;
    if !value.is_none() {
        let values = value.call_method1("split", (",",))?;
        for value in values.try_iter()? {
            subprotocols.append(value?.call_method0("strip")?)?;
        }
    }

    let raw_path = raw_path
        .split(|byte| *byte == b'?')
        .next()
        .unwrap_or_default();
    let scope = PyDict::new(py);
    scope.set_item("type", "websocket")?;
    scope.set_item("path", path)?;
    scope.set_item("raw_path", PyBytes::new(py, raw_path))?;
    scope.set_item("root_path", root_path)?;
    scope.set_item("scheme", scheme)?;
    scope.set_item("query_string", query_string)?;
    scope.set_item("headers", headers)?;
    scope.set_item("client", (client.0, client.1))?;
    let server = PyList::empty(py);
    server.append(host)?;
    server.append(port)?;
    scope.set_item("server", server)?;
    scope.set_item("subprotocols", subprotocols)?;
    let extensions = PyDict::new(py);
    extensions.set_item("websocket.http.response", PyDict::new(py))?;
    scope.set_item("extensions", extensions)?;
    scope.set_item("state", app_state.call_method0("copy")?)?;
    Ok(scope.unbind())
}

fn websocket_connect_message(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let message = PyDict::new(py);
    message.set_item("type", "websocket.connect")?;
    Ok(message.into_any().unbind())
}

fn websocket_disconnect_message(py: Python<'_>, code: u16) -> PyResult<Py<PyAny>> {
    let message = PyDict::new(py);
    message.set_item("type", "websocket.disconnect")?;
    message.set_item("code", code)?;
    message.set_item("reason", py.None())?;
    Ok(message.into_any().unbind())
}

fn websocket_disconnect(py: Python<'_>, message: &Bound<'_, PyDict>) -> PyResult<PyErr> {
    let code = message
        .get_item("code")?
        .map(|value| value.extract::<u16>())
        .transpose()?
        .unwrap_or(1000);
    let reason = message
        .get_item("reason")?
        .unwrap_or_else(|| PyString::new(py, "").into_any());
    let kwargs = PyDict::new(py);
    kwargs.set_item("reason", reason)?;
    let exception_type = py
        .import("starlette.websockets")?
        .getattr("WebSocketDisconnect")?;
    let exception = exception_type.call((code,), Some(&kwargs))?;
    Ok(PyErr::from_value(exception))
}

fn is_cancelled_error(py: Python<'_>, error: &PyErr) -> PyResult<bool> {
    let error_type = py.import("concurrent.futures")?.getattr("CancelledError")?;
    Ok(error.is_instance(py, &error_type))
}

fn build_http_scope(
    py: Python<'_>,
    request: &Bound<'_, PyAny>,
    root_path: &str,
    client: (&str, u16),
    app_state: &Bound<'_, PyDict>,
) -> PyResult<(Py<PyDict>, String, Vec<u8>)> {
    let url = request.getattr("url")?;
    let scheme = url.getattr("scheme")?.extract::<String>()?;
    let netloc = url
        .getattr("netloc")?
        .call_method1("decode", ("ascii",))?
        .extract::<String>()?;
    let (host, port) = if let Some((host, port)) = netloc.split_once(':') {
        (
            host.to_owned(),
            port.parse::<u16>()
                .map_err(|_| PyRuntimeError::new_err("invalid TestClient URL port"))?,
        )
    } else {
        let default_port = match scheme.as_str() {
            "http" | "ws" => 80,
            "https" | "wss" => 443,
            _ => return Err(PyKeyError::new_err(scheme)),
        };
        (netloc, default_port)
    };
    let path = url.getattr("path")?.extract::<String>()?;
    let raw_path = url
        .getattr("raw_path")?
        .cast::<PyBytes>()?
        .as_bytes()
        .to_vec();
    let query = url.getattr("query")?.call_method1("decode", ("ascii",))?;
    let query_string = query.call_method0("encode")?.cast_into::<PyBytes>()?;
    let unquoted_path = py
        .import("urllib.parse")?
        .getattr("unquote")?
        .call1((path,))?;
    let request_headers = request.getattr("headers")?;
    let has_host = request_headers
        .call_method1("__contains__", ("host",))?
        .extract::<bool>()?;
    let default_port = match scheme.as_str() {
        "http" | "ws" => 80,
        "https" | "wss" => 443,
        _ => return Err(PyKeyError::new_err(scheme)),
    };
    let headers = PyList::empty(py);
    if !has_host {
        let host_with_port = format!("{host}:{port}");
        let host_value = if port == default_port {
            host.as_str()
        } else {
            host_with_port.as_str()
        };
        headers.append((
            PyBytes::new(py, b"host"),
            PyBytes::new(py, host_value.as_bytes()),
        ))?;
    }
    let items = request_headers.call_method0("multi_items")?;
    for item in items.try_iter()? {
        let pair = item?.cast_into::<PyTuple>()?;
        let key = pair
            .get_item(0)?
            .call_method0("lower")?
            .call_method0("encode")?;
        let value = pair.get_item(1)?.call_method0("encode")?;
        headers.append((key, value))?;
    }
    let method = request.getattr("method")?.extract::<String>()?;
    let scope = PyDict::new(py);
    scope.set_item("type", "http")?;
    scope.set_item("http_version", "1.1")?;
    scope.set_item("method", &method)?;
    scope.set_item("path", unquoted_path)?;
    let raw_path = raw_path
        .split(|byte| *byte == b'?')
        .next()
        .unwrap_or_default();
    scope.set_item("raw_path", PyBytes::new(py, raw_path))?;
    scope.set_item("root_path", root_path)?;
    scope.set_item("scheme", &scheme)?;
    scope.set_item("query_string", query_string)?;
    scope.set_item("headers", headers)?;
    scope.set_item("client", (client.0, client.1))?;
    let server = PyList::empty(py);
    server.append(&host)?;
    server.append(port)?;
    scope.set_item("server", server)?;
    scope.set_item("extensions", debug_extension(py)?)?;
    scope.set_item("state", app_state.call_method0("copy")?)?;
    let body = request
        .getattr("read")?
        .call0()?
        .cast::<PyBytes>()?
        .as_bytes()
        .to_vec();
    Ok((scope.unbind(), method, body))
}

fn debug_extension(py: Python<'_>) -> PyResult<Py<PyDict>> {
    let extension = PyDict::new(py);
    let extensions = PyDict::new(py);
    extensions.set_item("http.response.debug", extension)?;
    Ok(extensions.unbind())
}

fn exit_portal(py: Python<'_>, manager: Bound<'_, PyAny>, error: Option<&PyErr>) -> PyResult<()> {
    match error {
        None => {
            manager.call_method1("__exit__", (py.None(), py.None(), py.None()))?;
        }
        Some(error) => {
            let exception_type = error.get_type(py);
            let exception_value = error.value(py);
            let traceback = error
                .traceback(py)
                .map_or_else(|| py.None().into_bound(py), |value| value.into_any());
            manager.call_method1("__exit__", (exception_type, exception_value, traceback))?;
        }
    }
    Ok(())
}
