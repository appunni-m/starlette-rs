//! Rust-owned HTTPX-to-ASGI transport for Starlette's synchronous TestClient.

use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::exceptions::{PyAssertionError, PyImportError, PyKeyError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

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
        })
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
        let from_thread = anyio.getattr("from_thread")?;
        let start_portal = from_thread.getattr("start_blocking_portal")?;
        let portal_kwargs = PyDict::new(py);
        portal_kwargs.set_item("backend", &self.backend)?;
        portal_kwargs.set_item("backend_options", self.backend_options.bind(py))?;
        let manager = start_portal.call((), Some(&portal_kwargs))?;
        let portal = manager.call_method0("__enter__")?;
        let event = match portal.call_method1("call", (anyio.getattr("Event")?,)) {
            Ok(event) => event,
            Err(error) => {
                exit_portal(py, manager, Some(&error))?;
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
        let app_result =
            portal.call_method1("call", (runner, self.app.bind(py), &scope, receive, send));
        match &app_result {
            Ok(_) => exit_portal(py, manager, None)?,
            Err(error) => exit_portal(py, manager, Some(error))?,
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
    module.add_class::<PyTestClientTransport>()?;
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
