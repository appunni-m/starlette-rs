//! Rust-owned `Request` body streaming and collection with Python receive callbacks.

use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::exceptions::{
    PyAssertionError, PyBaseException, PyKeyError, PyRuntimeError, PyStopAsyncIteration,
    PyTypeError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyList, PyModule, PyTraceback, PyTuple, PyType};
use starlette_rs::{
    RequestBodyAccumulator as NativeRequestBodyAccumulator, RequestBodyError,
    RequestStreamProgress, RequestStreamState,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
    into_python_awaitable_with_reuse_error,
};

type SharedRequestBody = Arc<Mutex<RequestBodyRuntime>>;

struct RequestBodyRuntime {
    accumulator: NativeRequestBodyAccumulator,
    receive: Option<Py<PyAny>>,
    request_disconnected: bool,
    body_object: Option<Py<PyBytes>>,
    json_object: Option<Py<PyAny>>,
}

#[pyclass(name = "RequestBody")]
pub(crate) struct PyRequestBody {
    shared: SharedRequestBody,
}

type SharedStreamProtocol = Arc<Mutex<StreamProtocol>>;

#[derive(Default)]
struct StreamProtocol {
    started: bool,
    running: bool,
    closed: bool,
}

// Starlette may execute synchronous endpoints on AnyIO worker threads. The
// connection stores only Python-owned references and per-instance caches; the
// GIL protects these fields while a Python method is running, so this wrapper
// must be transferable across threads like the upstream Python object.
#[pyclass(name = "HTTPConnection")]
pub(crate) struct PyHTTPConnection {
    scope: Py<PyAny>,
    request_headers: Option<Py<PyAny>>,
    headers: Option<Py<PyAny>>,
    query_params: Option<Py<PyAny>>,
    cookies: Option<Py<PyAny>>,
    url: Option<Py<PyAny>>,
    base_url: Option<Py<PyAny>>,
    state: Option<Py<PyAny>>,
}

#[pymethods]
impl PyHTTPConnection {
    #[new]
    #[pyo3(signature = (scope, expected_type=None))]
    fn new(py: Python<'_>, scope: Py<PyAny>, expected_type: Option<&str>) -> PyResult<Self> {
        let scope_type = scope.bind(py).get_item("type")?;
        let is_http = scope_type.eq("http")?;
        let is_websocket = scope_type.eq("websocket")?;
        if !is_http && !is_websocket {
            return Err(PyAssertionError::new_err(""));
        }
        if let Some(expected_type) = expected_type
            && !scope_type.eq(expected_type)?
        {
            return Err(PyAssertionError::new_err(""));
        }
        Ok(Self {
            scope,
            request_headers: None,
            headers: None,
            query_params: None,
            cookies: None,
            url: None,
            base_url: None,
            state: None,
        })
    }

    #[getter]
    fn scope(&self, py: Python<'_>) -> Py<PyAny> {
        self.scope.clone_ref(py)
    }

    #[setter]
    fn set_scope(&mut self, scope: Py<PyAny>) {
        self.scope = scope;
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.scope.bind(py).get_item(key).map(Bound::unbind)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.scope
            .bind(py)
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        self.scope.bind(py).len()
    }

    #[getter]
    fn app(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.scope.bind(py).get_item("app").map(Bound::unbind)
    }

    #[getter]
    fn url(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(url) = self.url.as_ref() {
            return Ok(url.clone_ref(py));
        }
        let url = url_from_scope(py, self.scope.bind(py))?;
        self.url = Some(url.clone_ref(py));
        Ok(url)
    }

    #[getter]
    fn base_url(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(url) = self.base_url.as_ref() {
            return Ok(url.clone_ref(py));
        }
        let scope = py
            .import("builtins")?
            .getattr("dict")?
            .call1((self.scope.bind(py),))?;
        let root_path = scope.call_method1("get", ("root_path", ""))?;
        let app_root_path = scope.call_method1("get", ("app_root_path", root_path))?;
        let mut path = app_root_path.extract::<String>()?;
        if !path.ends_with('/') {
            path.push('/');
        }
        scope.set_item("path", path)?;
        scope.set_item("query_string", PyBytes::new(py, b""))?;
        scope.set_item("root_path", app_root_path)?;
        let url = url_from_scope(py, &scope)?;
        self.base_url = Some(url.clone_ref(py));
        Ok(url)
    }

    #[getter]
    fn headers(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(headers) = self.headers.as_ref() {
            return Ok(headers.clone_ref(py));
        }
        let native_headers = self.native_headers(py)?;
        let view = Py::new(
            py,
            PyHeadersView {
                inner: native_headers,
            },
        )?;
        let headers_type = py.import("starlette.requests")?.getattr("Headers")?;
        let headers = headers_type.call1((view,))?.unbind();
        self.headers = Some(headers.clone_ref(py));
        Ok(headers)
    }

    #[getter]
    fn query_params(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(params) = self.query_params.as_ref() {
            return Ok(params.clone_ref(py));
        }
        let raw_query = self.scope.bind(py).get_item("query_string")?;
        let query_type = py.import("starlette_rs_py._core")?.getattr("QueryParams")?;
        let params = query_type.call1((raw_query,))?.unbind();
        self.query_params = Some(params.clone_ref(py));
        Ok(params)
    }

    #[getter]
    fn path_params(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let empty = PyDict::new(py);
        self.scope
            .bind(py)
            .call_method1("get", ("path_params", empty))
            .map(Bound::unbind)
    }

    #[getter]
    fn cookies(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(cookies) = self.cookies.as_ref() {
            return Ok(cookies.clone_ref(py));
        }
        let native_headers = self.native_headers(py)?;
        let cookies_type = py.import("starlette_rs_py._core")?.getattr("Cookies")?;
        let cookies = cookies_type
            .getattr("from_headers")?
            .call1((native_headers,))?
            .unbind();
        self.cookies = Some(cookies.clone_ref(py));
        Ok(cookies)
    }

    #[getter]
    fn client(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let client = self.scope.bind(py).call_method1("get", ("client",))?;
        if client.is_none() {
            return Ok(py.None());
        }
        let tuple = py.import("builtins")?.getattr("tuple")?.call1((client,))?;
        let address_type = py.import("starlette.datastructures")?.getattr("Address")?;
        let address = address_type.call(tuple.cast::<PyTuple>()?, None)?;
        Ok(address.unbind())
    }

    #[getter]
    fn state(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(state) = self.state.as_ref() {
            return Ok(state.clone_ref(py));
        }
        let empty = PyDict::new(py);
        let state_value = self
            .scope
            .bind(py)
            .call_method1("setdefault", ("state", empty))?;
        let state_type = py.import("starlette.datastructures")?.getattr("State")?;
        let state = state_type.call1((state_value,))?.unbind();
        self.state = Some(state.clone_ref(py));
        Ok(state)
    }

    #[getter]
    fn session(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let scope = self.scope.bind(py);
        if !scope
            .call_method1("__contains__", ("session",))?
            .is_truthy()?
        {
            return Err(PyAssertionError::new_err(
                "SessionMiddleware must be installed to access request.session",
            ));
        }
        let session = scope.get_item("session")?;
        if session.hasattr("mark_accessed")? {
            session.call_method0("mark_accessed")?;
        }
        Ok(session.unbind())
    }

    #[getter]
    fn auth(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let scope = self.scope.bind(py);
        if !scope.call_method1("__contains__", ("auth",))?.is_truthy()? {
            return Err(PyAssertionError::new_err(
                "AuthenticationMiddleware must be installed to access request.auth",
            ));
        }
        scope.get_item("auth").map(Bound::unbind)
    }

    #[getter]
    fn user(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let scope = self.scope.bind(py);
        if !scope.call_method1("__contains__", ("user",))?.is_truthy()? {
            return Err(PyAssertionError::new_err(
                "AuthenticationMiddleware must be installed to access request.user",
            ));
        }
        scope.get_item("user").map(Bound::unbind)
    }

    #[getter]
    fn method(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.scope.bind(py).get_item("method").map(Bound::unbind)
    }

    #[getter]
    fn url_path(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.scope.bind(py).get_item("path").map(Bound::unbind)
    }

    #[getter]
    fn router(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.scope.bind(py).get_item("router").map(Bound::unbind)
    }

    #[pyo3(signature = (name, /, **path_params))]
    fn url_for(
        &mut self,
        py: Python<'_>,
        name: &str,
        path_params: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        let scope = self.scope.bind(py);
        let router = scope.call_method1("get", ("router",))?;
        let provider = if router.is_truthy()? {
            router
        } else {
            scope.call_method1("get", ("app",))?
        };
        if provider.is_none() {
            return Err(PyRuntimeError::new_err(
                "The `url_for` method can only be used inside a Starlette application or with a router.",
            ));
        }
        let empty = PyDict::new(py);
        let path_params = path_params.unwrap_or(&empty);
        let args = PyTuple::new(py, [name])?;
        let url_path = provider.call_method("url_path_for", &args, Some(path_params))?;
        let base_url = self.base_url(py)?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("base_url", base_url)?;
        url_path
            .call_method("make_absolute_url", (), Some(&kwargs))
            .map(Bound::unbind)
    }

    fn _send_push_promise(
        slf: Py<Self>,
        py: Python<'_>,
        send_callback: Py<PyAny>,
        path: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            SendPushPromiseMachine {
                connection: slf,
                send_callback,
                path,
                pending_send: false,
            },
        )
    }
}

struct SendPushPromiseMachine {
    connection: Py<PyHTTPConnection>,
    send_callback: Py<PyAny>,
    path: Py<PyAny>,
    pending_send: bool,
}

impl AwaitableStateMachine for SendPushPromiseMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending_send => self.start(py),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "request push-promise send already has an operation pending",
            )),
            MachineResume::Value(_) if self.pending_send => {
                self.pending_send = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "request push-promise send resumed without a pending send",
            )),
            MachineResume::Error(error) => {
                self.pending_send = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
        }
    }
}

impl SendPushPromiseMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.connection.borrow(py).scope.clone_ref(py);
        let scope = scope.bind(py);
        let default_extensions = PyDict::new(py);
        let extensions = scope.call_method1("get", ("extensions", &default_extensions))?;
        if !extensions.contains("http.response.push")? {
            return Ok(MachineAction::Complete(py.None()));
        }

        let mut connection = self.connection.borrow_mut(py);
        let request_headers = connection.native_headers(py)?;
        let raw_headers = request_headers
            .bind(py)
            .call_method0("raw")?
            .extract::<Vec<(Vec<u8>, Vec<u8>)>>()?;
        drop(connection);

        // Upstream stores these names in a set, so their cross-process order
        // is not a public guarantee. Use a stable order for Rust observations.
        const COPIED_HEADER_NAMES: [&str; 5] = [
            "accept",
            "accept-encoding",
            "accept-language",
            "cache-control",
            "user-agent",
        ];
        let copied_headers = PyList::empty(py);
        for name in COPIED_HEADER_NAMES {
            for (header_name, value) in &raw_headers {
                if header_name.eq_ignore_ascii_case(name.as_bytes()) {
                    let pair = PyTuple::new(
                        py,
                        [PyBytes::new(py, name.as_bytes()), PyBytes::new(py, value)],
                    )?;
                    copied_headers.append(pair)?;
                }
            }
        }

        let message = PyDict::new(py);
        message.set_item("type", "http.response.push")?;
        message.set_item("path", self.path.bind(py))?;
        message.set_item("headers", copied_headers)?;
        let awaitable = self.send_callback.bind(py).call1((message,))?;
        self.pending_send = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[pyclass(name = "_HeadersView")]
struct PyHeadersView {
    inner: Py<PyAny>,
}

#[pymethods]
impl PyHeadersView {
    fn raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.inner.bind(py).call_method0("raw").map(Bound::unbind)
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self.pairs(py)?.into_iter().map(|(name, _)| name).collect())
    }

    fn values(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self
            .pairs(py)?
            .into_iter()
            .map(|(_, value)| value)
            .collect())
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(String, String)>> {
        self.pairs(py)
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let key = header_key(key)?;
        let value = self
            .inner
            .bind(py)
            .call_method1("get", (PyBytes::new(py, &key),))?;
        if value.is_none() {
            return Ok(default.unwrap_or_else(|| py.None()));
        }
        decode_latin1_py(value)
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
        let key = header_key(key)?;
        let values = self
            .inner
            .bind(py)
            .call_method1("get_list", (PyBytes::new(py, &key),))?
            .extract::<Vec<Vec<u8>>>()?;
        values
            .into_iter()
            .map(|value| decode_latin1_string(py, &value))
            .collect()
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<String> {
        let key_bytes = header_key(key)?;
        let value = self
            .inner
            .bind(py)
            .call_method1("get", (PyBytes::new(py, &key_bytes),))?;
        if value.is_none() {
            return Err(PyKeyError::new_err(key.extract::<String>()?));
        }
        decode_latin1_string(py, &value.extract::<Vec<u8>>()?)
    }

    fn __contains__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        let key = header_key(key)?;
        let value = self
            .inner
            .bind(py)
            .call_method1("get", (PyBytes::new(py, &key),))?;
        Ok(!value.is_none())
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let keys = self.keys(py)?;
        PyList::new(py, keys)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        self.inner.bind(py).len()
    }
}

impl PyHTTPConnection {
    fn native_headers(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(headers) = self.request_headers.as_ref() {
            return Ok(headers.clone_ref(py));
        }
        let raw = self.scope.bind(py).get_item("headers")?;
        let raw = py.import("builtins")?.getattr("list")?.call1((raw,))?;
        self.scope.bind(py).set_item("headers", &raw)?;
        let headers = py
            .import("starlette_rs_py._core")?
            .getattr("RequestHeaders")?
            .call1((raw,))?
            .unbind();
        self.request_headers = Some(headers.clone_ref(py));
        Ok(headers)
    }
}

impl PyHeadersView {
    fn pairs(&self, py: Python<'_>) -> PyResult<Vec<(String, String)>> {
        self.inner
            .bind(py)
            .call_method0("raw")?
            .extract::<Vec<(Vec<u8>, Vec<u8>)>>()?
            .into_iter()
            .map(|(name, value)| {
                Ok((
                    decode_latin1_string(py, &name)?,
                    decode_latin1_string(py, &value)?,
                ))
            })
            .collect()
    }
}

fn header_key(key: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    key.call_method0("lower")?
        .call_method1("encode", ("latin-1",))?
        .extract()
}

fn decode_latin1_py(value: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    value
        .call_method1("decode", ("latin-1",))
        .map(Bound::unbind)
}

fn decode_latin1_string(py: Python<'_>, value: &[u8]) -> PyResult<String> {
    PyBytes::new(py, value)
        .call_method1("decode", ("latin-1",))?
        .extract()
}

fn url_from_scope(py: Python<'_>, scope: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("scope", scope)?;
    py.import("starlette.datastructures")?
        .getattr("URL")?
        .call((), Some(&kwargs))
        .map(Bound::unbind)
}

#[pymethods]
impl PyRequestBody {
    #[new]
    #[pyo3(signature = (receive=None))]
    fn new(py: Python<'_>, receive: Option<Py<PyAny>>) -> PyResult<Self> {
        let receive = match receive {
            Some(receive) => receive,
            None => py
                .import("starlette_rs_py._core")?
                .getattr("_empty_receive")?
                .unbind(),
        };
        Ok(Self {
            shared: Arc::new(Mutex::new(RequestBodyRuntime {
                accumulator: NativeRequestBodyAccumulator::default(),
                receive: Some(receive),
                request_disconnected: false,
                body_object: None,
                json_object: None,
            })),
        })
    }

    #[getter]
    fn receive(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        borrow_runtime(&self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| PyRuntimeError::new_err("Receive channel has not been made available"))
    }

    fn stream(&self, py: Python<'_>) -> PyResult<Py<PyRequestStream>> {
        Py::new(
            py,
            PyRequestStream {
                shared: self.shared.clone(),
                state: Arc::new(Mutex::new(RequestStreamState::default())),
                protocol: Arc::new(Mutex::new(StreamProtocol::default())),
            },
        )
    }

    fn body(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            BodyMachine {
                shared: self.shared.clone(),
                stream: RequestStreamState::default(),
                pending_receive: false,
            },
        )
    }

    fn json(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            JsonMachine {
                shared: self.shared.clone(),
                pending_body: false,
            },
        )
    }

    fn is_disconnected(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let receive = borrow_runtime(&self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| {
                PyRuntimeError::new_err("Receive channel has not been made available")
            })?;
        into_python_awaitable(
            py,
            RequestDisconnectedMachine {
                shared: self.shared.clone(),
                receive,
                cancel_scope: None,
                pending_receive: false,
            },
        )
    }
}

#[pyclass(name = "_RequestBodyStream")]
struct PyRequestStream {
    shared: SharedRequestBody,
    state: Arc<Mutex<RequestStreamState>>,
    protocol: SharedStreamProtocol,
}

#[pymethods]
impl PyRequestStream {
    fn __aiter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __anext__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        stream_operation(py, &slf, StreamCommand::Advance(None))
    }

    fn asend(slf: Py<Self>, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        stream_operation(py, &slf, StreamCommand::Advance(Some(value)))
    }

    #[pyo3(signature = (exception_type, value=None, traceback=None))]
    fn athrow(
        slf: Py<Self>,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        value: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let error = normalize_stream_throw(py, exception_type, value, traceback)?;
        stream_operation(py, &slf, StreamCommand::Throw(error))
    }

    fn aclose(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        stream_operation(py, &slf, StreamCommand::Close)
    }
}

fn stream_operation(
    py: Python<'_>,
    stream: &Py<PyRequestStream>,
    command: StreamCommand,
) -> PyResult<Py<PyAny>> {
    let borrowed = stream.borrow(py);
    let shared = borrowed.shared.clone();
    let state = borrowed.state.clone();
    let protocol = borrowed.protocol.clone();
    drop(borrowed);
    let reuse_error = match &command {
        StreamCommand::Advance(_) => "cannot reuse already awaited __anext__()/asend()",
        StreamCommand::Throw(_) | StreamCommand::Close => {
            "cannot reuse already awaited aclose()/athrow()"
        }
    };
    into_python_awaitable_with_reuse_error(
        py,
        StreamMachine {
            shared,
            state,
            protocol,
            command,
            pending_receive: false,
        },
        reuse_error,
    )
}

enum StreamCommand {
    Advance(Option<Py<PyAny>>),
    Throw(PyErr),
    Close,
}

fn normalize_stream_throw(
    py: Python<'_>,
    exception_type: Py<PyAny>,
    value: Option<Py<PyAny>>,
    traceback: Option<Py<PyAny>>,
) -> PyResult<PyErr> {
    let exception_type = exception_type.bind(py);
    let exception_value = if exception_type.is_instance_of::<PyBaseException>() {
        if value
            .as_ref()
            .is_some_and(|value| !value.bind(py).is_none())
        {
            return Err(PyTypeError::new_err(
                "instance exception may not have a separate value",
            ));
        }
        exception_type.clone().unbind()
    } else {
        let exception_class = exception_type.cast::<PyType>()?;
        let constructed = match value {
            Some(value) if value.bind(py).is_instance_of::<PyBaseException>() => value,
            Some(value) if !value.bind(py).is_none() => {
                exception_class.call1((value.bind(py),))?.unbind()
            }
            _ => exception_class.call0()?.unbind(),
        };
        if !constructed.bind(py).is_instance_of::<PyBaseException>() {
            return Err(PyTypeError::new_err(
                "exceptions must derive from BaseException",
            ));
        }
        constructed
    };

    let error = PyErr::from_value(exception_value.into_bound(py));
    if let Some(traceback) = traceback.filter(|traceback| !traceback.bind(py).is_none()) {
        let traceback = traceback.bind(py).cast::<PyTraceback>()?.clone();
        error.set_traceback(py, Some(traceback));
    }
    Ok(error)
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(empty_receive, module)?)?;
    module.add_function(wrap_pyfunction!(empty_send, module)?)?;
    module.add_class::<PyRequestBody>()?;
    module.add_class::<PyRequestStream>()?;
    module.add_class::<PyHTTPConnection>()?;
    module.add_class::<PyHeadersView>()?;
    Ok(())
}

#[pyfunction(name = "_empty_receive")]
fn empty_receive(py: Python<'_>) -> PyResult<Py<PyAny>> {
    into_python_awaitable(py, EmptyReceive)
}

struct EmptyReceive;

impl AwaitableStateMachine for EmptyReceive {
    fn resume(&mut self, _py: Python<'_>, _input: MachineResume) -> PyResult<MachineAction> {
        Err(PyRuntimeError::new_err(
            "Receive channel has not been made available",
        ))
    }
}

#[pyfunction(name = "_empty_send")]
fn empty_send(py: Python<'_>) -> PyResult<Py<PyAny>> {
    into_python_awaitable(py, EmptySend)
}

struct EmptySend;

impl AwaitableStateMachine for EmptySend {
    fn resume(&mut self, _py: Python<'_>, _input: MachineResume) -> PyResult<MachineAction> {
        Err(PyRuntimeError::new_err(
            "Send channel has not been made available",
        ))
    }
}

struct RequestDisconnectedMachine {
    shared: SharedRequestBody,
    receive: Py<PyAny>,
    cancel_scope: Option<Py<PyAny>>,
    pending_receive: bool,
}

impl AwaitableStateMachine for RequestDisconnectedMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending_receive => self.start(py),
            MachineResume::Start => self.finish_error(
                py,
                PyRuntimeError::new_err(
                    "request disconnect check already has an operation pending",
                ),
            ),
            MachineResume::Value(message) if self.pending_receive => {
                self.pending_receive = false;
                self.exit_cancel_scope(py, None)?;
                if message
                    .bind(py)
                    .call_method1("get", ("type",))?
                    .eq("http.disconnect")?
                {
                    borrow_runtime_mut(&self.shared)?.request_disconnected = true;
                }
                self.complete_current(py)
            }
            MachineResume::Value(_) => self.finish_error(
                py,
                PyRuntimeError::new_err(
                    "request disconnect check resumed without a pending receive",
                ),
            ),
            MachineResume::Error(error) if self.pending_receive => {
                self.pending_receive = false;
                self.finish_error(py, error)
            }
            MachineResume::Error(error) => self.finish_error(py, error),
            MachineResume::AsyncIterationComplete(error) => {
                self.pending_receive = false;
                self.finish_error(py, error)
            }
        }
    }
}

impl RequestDisconnectedMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if borrow_runtime(&self.shared)?.request_disconnected {
            return self.complete_current(py);
        }

        let cancel_scope = py.import("anyio")?.getattr("CancelScope")?.call0()?;
        cancel_scope.call_method0("__enter__")?;
        self.cancel_scope = Some(cancel_scope.unbind());

        let cancel_result = self
            .cancel_scope
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("request cancel scope was not initialized"))?
            .bind(py)
            .call_method0("cancel")
            .map(|_| ());
        if let Err(error) = cancel_result {
            return self.finish_error(py, error);
        }

        let receive = match self.receive.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => return self.finish_error(py, error),
        };
        self.pending_receive = true;
        Ok(MachineAction::Await(receive.unbind()))
    }

    fn finish_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if self.exit_cancel_scope(py, Some(&error))? {
            self.complete_current(py)
        } else {
            Err(error)
        }
    }

    fn exit_cancel_scope(&mut self, py: Python<'_>, error: Option<&PyErr>) -> PyResult<bool> {
        let Some(cancel_scope) = self.cancel_scope.take() else {
            return Ok(false);
        };
        let cancel_scope = cancel_scope.bind(py);
        let result = match error {
            Some(error) => {
                let traceback = error
                    .traceback(py)
                    .map_or_else(|| py.None().into_bound(py), Bound::into_any);
                cancel_scope
                    .call_method1("__exit__", (error.get_type(py), error.value(py), traceback))?
            }
            None => cancel_scope.call_method1("__exit__", (py.None(), py.None(), py.None()))?,
        };
        result.is_truthy()
    }

    fn complete_current(&self, py: Python<'_>) -> PyResult<MachineAction> {
        let disconnected = borrow_runtime(&self.shared)?.request_disconnected;
        Ok(MachineAction::Complete(
            PyBool::new(py, disconnected).to_owned().into_any().unbind(),
        ))
    }
}

struct BodyMachine {
    shared: SharedRequestBody,
    stream: RequestStreamState,
    pending_receive: bool,
}

impl AwaitableStateMachine for BodyMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) => {
                if !self.pending_receive {
                    return Err(PyRuntimeError::new_err(
                        "request body collection received an unexpected result",
                    ));
                }
                self.pending_receive = false;
                let (message_type, body, more_body) = match request_message(py, message) {
                    Ok(message) => message,
                    Err(error) => {
                        self.abort_collection();
                        self.stream.fail();
                        return Err(error);
                    }
                };
                let progress = {
                    let mut runtime = borrow_runtime_mut(&self.shared)?;
                    if message_type == "http.disconnect" {
                        runtime.request_disconnected = true;
                    }
                    self.stream
                        .accept(&mut runtime.accumulator, &message_type, &body, more_body)
                };
                match progress {
                    Ok(progress) => self.consume_progress(py, progress),
                    Err(error) => {
                        self.abort_collection();
                        Err(request_body_error(py, error))
                    }
                }
            }
            MachineResume::AsyncIterationComplete(_) => {
                self.abort_collection();
                self.stream.fail();
                Err(PyRuntimeError::new_err(
                    "async generator raised StopAsyncIteration",
                ))
            }
            MachineResume::Error(error) => {
                self.abort_collection();
                self.stream.fail();
                Err(error)
            }
        }
    }
}

impl BodyMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if cached_body_object(py, &self.shared)?.is_some() {
            return complete_cached_body(py, &self.shared);
        }

        let result = {
            let mut runtime = borrow_runtime_mut(&self.shared)?;
            runtime.accumulator.begin_body_collection()
        };
        result.map_err(|error| request_body_error(py, error))?;
        let progress = {
            let runtime = borrow_runtime(&self.shared)?;
            self.stream.next(&runtime.accumulator)
        }
        .map_err(|error| request_body_error(py, error))?;
        self.consume_progress(py, progress)
    }

    fn consume_progress(
        &mut self,
        py: Python<'_>,
        mut progress: RequestStreamProgress,
    ) -> PyResult<MachineAction> {
        loop {
            match progress {
                RequestStreamProgress::Receive => return self.await_receive(py),
                RequestStreamProgress::Chunk(_) | RequestStreamProgress::CachedBody(_) => {
                    progress = {
                        let runtime = borrow_runtime(&self.shared)?;
                        self.stream.next(&runtime.accumulator)
                    }
                    .map_err(|error| {
                        self.abort_collection();
                        request_body_error(py, error)
                    })?;
                }
                RequestStreamProgress::Complete => return complete_cached_body(py, &self.shared),
            }
        }
    }

    fn await_receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = borrow_runtime(&self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py));
        let Some(receive) = receive else {
            self.abort_collection();
            self.stream.fail();
            return Err(PyRuntimeError::new_err(
                "Receive channel has not been made available",
            ));
        };
        let awaitable = match receive.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.abort_collection();
                self.stream.fail();
                return Err(error);
            }
        };
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn abort_collection(&self) {
        if let Ok(mut runtime) = self.shared.try_lock() {
            runtime.accumulator.abort_body_collection();
        }
    }
}

struct StreamMachine {
    shared: SharedRequestBody,
    state: Arc<Mutex<RequestStreamState>>,
    protocol: SharedStreamProtocol,
    command: StreamCommand,
    pending_receive: bool,
}

impl AwaitableStateMachine for StreamMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) => {
                if !self.pending_receive {
                    self.finish(false);
                    return Err(PyRuntimeError::new_err(
                        "request stream received an unexpected result",
                    ));
                }
                self.pending_receive = false;
                let (message_type, body, more_body) = match request_message(py, message) {
                    Ok(message) => message,
                    Err(error) => {
                        self.fail_stream();
                        self.finish(false);
                        return Err(error);
                    }
                };
                let progress = {
                    let mut runtime = borrow_runtime_mut(&self.shared)?;
                    if message_type == "http.disconnect" {
                        runtime.request_disconnected = true;
                    }
                    let mut state = borrow_stream_mut(&self.state)?;
                    state.accept(&mut runtime.accumulator, &message_type, &body, more_body)
                };
                match progress {
                    Ok(progress) => self.deliver(py, progress),
                    Err(error) => {
                        self.fail_stream();
                        self.finish(false);
                        Err(request_body_error(py, error))
                    }
                }
            }
            MachineResume::AsyncIterationComplete(_) => {
                self.fail_stream();
                self.finish(false);
                Err(PyRuntimeError::new_err(
                    "async generator raised StopAsyncIteration",
                ))
            }
            MachineResume::Error(error) => {
                self.fail_stream();
                self.finish(false);
                Err(error)
            }
        }
    }
}

impl StreamMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let mut protocol = self
            .protocol
            .try_lock()
            .map_err(|_| PyRuntimeError::new_err("request stream protocol is already borrowed"))?;
        if protocol.running {
            return Err(PyRuntimeError::new_err(format!(
                "{}: asynchronous generator is already running",
                match &self.command {
                    StreamCommand::Advance(_) => "anext()",
                    StreamCommand::Throw(_) => "athrow()",
                    StreamCommand::Close => "aclose()",
                }
            )));
        }
        match &self.command {
            StreamCommand::Close if protocol.closed || !protocol.started => {
                protocol.closed = true;
                return Ok(MachineAction::Complete(py.None()));
            }
            StreamCommand::Advance(_) if protocol.closed => {
                return Err(PyStopAsyncIteration::new_err(()));
            }
            StreamCommand::Throw(_) if protocol.closed => {
                return Err(PyStopAsyncIteration::new_err(()));
            }
            StreamCommand::Advance(Some(value))
                if !protocol.started && !value.bind(py).is_none() =>
            {
                return Err(PyTypeError::new_err(
                    "can't send non-None value to a just-started async generator",
                ));
            }
            StreamCommand::Throw(error) => {
                protocol.closed = true;
                drop(protocol);
                self.fail_stream();
                return Err(error.clone_ref(py));
            }
            StreamCommand::Close => {
                protocol.closed = true;
                drop(protocol);
                self.fail_stream();
                return Ok(MachineAction::Complete(py.None()));
            }
            StreamCommand::Advance(_) => {
                protocol.started = true;
                protocol.running = true;
            }
        }
        drop(protocol);
        self.next_action(py)
    }

    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let progress = {
            let runtime = borrow_runtime(&self.shared)?;
            let mut state = borrow_stream_mut(&self.state)?;
            state.next(&runtime.accumulator)
        };
        let progress = match progress {
            Ok(progress) => progress,
            Err(error) => {
                self.finish(false);
                return Err(request_body_error(py, error));
            }
        };
        self.deliver(py, progress)
    }

    fn deliver(
        &mut self,
        py: Python<'_>,
        progress: RequestStreamProgress,
    ) -> PyResult<MachineAction> {
        match progress {
            RequestStreamProgress::Receive => self.await_receive(py),
            RequestStreamProgress::Chunk(body) => {
                let body = PyBytes::new(py, &body).unbind().into_any();
                self.finish(true);
                Ok(MachineAction::Complete(body))
            }
            RequestStreamProgress::CachedBody(body) => {
                let body = cached_body_object(py, &self.shared)?
                    .unwrap_or_else(|| PyBytes::new(py, &body).unbind().into_any());
                self.finish(true);
                Ok(MachineAction::Complete(body))
            }
            RequestStreamProgress::Complete => {
                self.finish(false);
                Err(PyStopAsyncIteration::new_err(()))
            }
        }
    }

    fn await_receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = borrow_runtime(&self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| {
                self.fail_stream();
                self.finish(false);
                PyRuntimeError::new_err("Receive channel has not been made available")
            })?;
        let awaitable = match receive.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.fail_stream();
                self.finish(false);
                return Err(error);
            }
        };
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn fail_stream(&self) {
        if let Ok(mut state) = self.state.try_lock() {
            state.fail();
        }
    }

    fn finish(&self, yielded: bool) {
        if let Ok(mut protocol) = self.protocol.try_lock() {
            protocol.running = false;
            if !yielded {
                protocol.closed = true;
            }
        }
    }
}

struct JsonMachine {
    shared: SharedRequestBody,
    pending_body: bool,
}

impl AwaitableStateMachine for JsonMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if let Some(value) = borrow_runtime(&self.shared)?.json_object.as_ref() {
                    return Ok(MachineAction::Complete(value.clone_ref(py)));
                }
                self.pending_body = true;
                let awaitable = into_python_awaitable(
                    py,
                    BodyMachine {
                        shared: self.shared.clone(),
                        stream: RequestStreamState::default(),
                        pending_receive: false,
                    },
                )?;
                Ok(MachineAction::Await(awaitable))
            }
            MachineResume::Value(body) => {
                if !self.pending_body {
                    return Err(PyRuntimeError::new_err(
                        "request JSON decoding received an unexpected result",
                    ));
                }
                self.pending_body = false;
                let json = py.import("json")?;
                let value = json.getattr("loads")?.call1((body.bind(py),))?;
                let result = value.clone().unbind();
                borrow_runtime_mut(&self.shared)?.json_object = Some(result.clone_ref(py));
                Ok(MachineAction::Complete(result))
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyRuntimeError::new_err(
                "request body collection completed unexpectedly",
            )),
            MachineResume::Error(error) => Err(error),
        }
    }
}

fn request_message(py: Python<'_>, message: Py<PyAny>) -> PyResult<(String, Vec<u8>, bool)> {
    let message = message.bind(py);
    let message_type = message.get_item("type")?.extract::<String>()?;
    let empty = PyBytes::new(py, b"");
    let body = message.call_method1("get", ("body", empty))?;
    let body = if body.is_truthy()? {
        body.extract::<Vec<u8>>()?
    } else {
        Vec::new()
    };
    let more_body = message
        .call_method1("get", ("more_body", false))?
        .is_truthy()?;
    Ok((message_type, body, more_body))
}

fn complete_cached_body(py: Python<'_>, shared: &SharedRequestBody) -> PyResult<MachineAction> {
    if let Some(body) = cached_body_object(py, shared)? {
        return Ok(MachineAction::Complete(body));
    }

    let body = {
        let mut runtime = borrow_runtime_mut(shared)?;
        runtime
            .accumulator
            .cache_body()
            .map_err(|error| request_body_error(py, error))?
            .to_vec()
    };
    let body = PyBytes::new(py, &body).unbind();
    borrow_runtime_mut(shared)?.body_object = Some(body.clone_ref(py));
    Ok(MachineAction::Complete(body.into_any()))
}

fn cached_body_object(py: Python<'_>, shared: &SharedRequestBody) -> PyResult<Option<Py<PyAny>>> {
    if let Some(cached) = borrow_runtime(shared)?.body_object.as_ref() {
        return Ok(Some(cached.clone_ref(py).into_any()));
    }

    let body = {
        let runtime = borrow_runtime(shared)?;
        runtime.accumulator.cached_body().map(<[u8]>::to_vec)
    };
    let Some(body) = body else {
        return Ok(None);
    };
    let body = PyBytes::new(py, &body).unbind();
    borrow_runtime_mut(shared)?.body_object = Some(body.clone_ref(py));
    Ok(Some(body.into_any()))
}

fn borrow_runtime(shared: &SharedRequestBody) -> PyResult<MutexGuard<'_, RequestBodyRuntime>> {
    shared
        .try_lock()
        .map_err(|_| PyRuntimeError::new_err("request body state is already borrowed"))
}

fn borrow_runtime_mut(shared: &SharedRequestBody) -> PyResult<MutexGuard<'_, RequestBodyRuntime>> {
    shared
        .try_lock()
        .map_err(|_| PyRuntimeError::new_err("request body state is already borrowed"))
}

fn borrow_stream_mut(
    state: &Arc<Mutex<RequestStreamState>>,
) -> PyResult<MutexGuard<'_, RequestStreamState>> {
    state
        .try_lock()
        .map_err(|_| PyRuntimeError::new_err("request stream state is already borrowed"))
}

fn request_body_error(py: Python<'_>, error: RequestBodyError) -> PyErr {
    match error {
        RequestBodyError::StreamConsumed => PyRuntimeError::new_err("Stream consumed"),
        RequestBodyError::ClientDisconnect => {
            let exception = py
                .import("starlette.requests")
                .and_then(|module| module.getattr("ClientDisconnect"))
                .and_then(|class| class.call0());
            match exception {
                Ok(exception) => PyErr::from_value(exception),
                Err(error) => error,
            }
        }
        other => PyRuntimeError::new_err(other.to_string()),
    }
}
