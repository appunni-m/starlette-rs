//! Rust-owned `Request` body streaming and collection with Python receive callbacks.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex, MutexGuard};

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::create_exception;
use pyo3::exceptions::{
    PyAssertionError, PyAttributeError, PyBaseException, PyException, PyRuntimeError,
    PyStopAsyncIteration, PyTypeError,
};
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyBytes, PyDict, PyList, PyModule, PyString, PyTraceback, PyTuple, PyType,
};
use starlette_rs::{
    FormData as NativeFormData, FormDataParseError, MultipartFormEvent, MultipartFormParseError,
    MultipartFormParser, RequestBodyAccumulator as NativeRequestBodyAccumulator, RequestBodyError,
    RequestStreamProgress, RequestStreamState,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
    into_sendable_python_awaitable_with_reuse_error,
};

create_exception!(_core, MultiPartException, PyException);

// Each Python edge is owned once by a GC-visible node; shared continuations
// own references to that node rather than hiding Python objects behind an Arc.
type SharedRequestBody = Py<RequestBodyRuntime>;
type BaseHTTPWrappedReceiveState = (Option<Py<PyAny>>, bool, bool, bool, bool);

#[pyclass]
struct RequestBodyRuntime {
    accumulator: NativeRequestBodyAccumulator,
    receive: Option<Py<PyAny>>,
    request_disconnected: bool,
    base_http_receive_disconnected: bool,
    base_http_receive_consumed: bool,
    body_object: Option<Py<PyBytes>>,
    json_object: Option<Py<PyAny>>,
    form_object: Option<Py<PyAny>>,
}

#[pymethods]
impl RequestBodyRuntime {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.receive)?;
        visit.call(&self.body_object)?;
        visit.call(&self.json_object)?;
        visit.call(&self.form_object)
    }

    fn __clear__(&mut self) {
        self.receive = None;
        self.body_object = None;
        self.json_object = None;
        self.form_object = None;
    }
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
    yielded_chunk: bool,
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
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.scope)?;
        visit.call(&self.request_headers)?;
        visit.call(&self.headers)?;
        visit.call(&self.query_params)?;
        visit.call(&self.cookies)?;
        visit.call(&self.url)?;
        visit.call(&self.base_url)?;
        visit.call(&self.state)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.scope = py.None();
        self.request_headers = None;
        self.headers = None;
        self.query_params = None;
        self.cookies = None;
        self.url = None;
        self.base_url = None;
        self.state = None;
    }

    #[new]
    #[pyo3(signature = (scope, expected_type=None))]
    fn new(py: Python<'_>, scope: Py<PyAny>, expected_type: Option<&str>) -> PyResult<Self> {
        let scope_type = scope.bind(py).get_item("type")?;
        let is_http = scope_type.eq("http")?;
        let is_websocket = scope_type.eq("websocket")?;
        if !is_http && !is_websocket {
            return Err(PyAssertionError::new_err(""));
        }
        let matches_expected_type = match expected_type {
            Some(expected_type) => scope_type.eq(expected_type)?,
            None => true,
        };
        if !matches_expected_type {
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
        let kwargs = PyDict::new(py);
        kwargs.set_item("scope", self.scope.bind(py))?;
        let headers_type = py.import("starlette.datastructures")?.getattr("Headers")?;
        let headers = headers_type.call((), Some(&kwargs))?.unbind();
        self.headers = Some(headers.clone_ref(py));
        Ok(headers)
    }

    #[getter]
    fn query_params(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(params) = self.query_params.as_ref() {
            return Ok(params.clone_ref(py));
        }
        let raw_query = self.scope.bind(py).get_item("query_string")?;
        let query_type = py
            .import("starlette.datastructures")?
            .getattr("QueryParams")?;
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
        let parsed_cookies = cookies_type
            .getattr("from_headers")?
            .call1((native_headers,))?;
        let cookie_items = parsed_cookies
            .call_method0("items")?
            .extract::<Vec<(String, String)>>()?;
        let cookies = PyDict::new(py);
        for (key, value) in cookie_items {
            cookies.set_item(key, value)?;
        }
        let cookies = cookies.into_any().unbind();
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
        into_sendable_python_awaitable(
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
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.connection)?;
        visit.call(&self.send_callback)?;
        visit.call(&self.path)?;
        Ok(())
    }

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
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

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
            shared: Py::new(
                py,
                RequestBodyRuntime {
                    accumulator: NativeRequestBodyAccumulator::default(),
                    receive: Some(receive),
                    request_disconnected: false,
                    base_http_receive_disconnected: false,
                    base_http_receive_consumed: false,
                    body_object: None,
                    json_object: None,
                    form_object: None,
                },
            )?,
        })
    }

    #[getter]
    fn receive(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        borrow_runtime(py, &self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| PyRuntimeError::new_err("Receive channel has not been made available"))
    }

    /// Expose the shared body state needed by Rust-owned BaseHTTPMiddleware.
    /// The cache, stream completion, and disconnect flags must come from the same
    /// accumulator used by `Request.body()` and `Request.stream()`.
    fn _base_http_wrapped_receive_state(
        &self,
        py: Python<'_>,
    ) -> PyResult<BaseHTTPWrappedReceiveState> {
        let cached_body = cached_body_object(py, &self.shared)?;
        let runtime = borrow_runtime(py, &self.shared)?;
        Ok((
            cached_body,
            runtime.accumulator.is_consumed(),
            runtime.request_disconnected || runtime.accumulator.is_disconnected(),
            runtime.base_http_receive_disconnected,
            runtime.base_http_receive_consumed,
        ))
    }

    fn _base_http_set_wrapped_receive_flags(
        &self,
        py: Python<'_>,
        disconnected: Option<bool>,
        consumed: Option<bool>,
    ) -> PyResult<()> {
        let mut runtime = borrow_runtime_mut(py, &self.shared)?;
        if let Some(disconnected) = disconnected {
            runtime.base_http_receive_disconnected = disconnected;
        }
        if let Some(consumed) = consumed {
            runtime.base_http_receive_consumed = consumed;
        }
        Ok(())
    }

    fn stream(&self, py: Python<'_>) -> PyResult<Py<PyRequestStream>> {
        Py::new(
            py,
            PyRequestStream {
                shared: self.shared.clone_ref(py),
                state: Arc::new(Mutex::new(RequestStreamState::default())),
                protocol: Arc::new(Mutex::new(StreamProtocol::default())),
            },
        )
    }

    fn body(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            BodyMachine {
                shared: self.shared.clone_ref(py),
                stream: RequestStreamState::default(),
                body: Vec::new(),
                pending_receive: false,
            },
        )
    }

    fn json(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            JsonMachine {
                shared: self.shared.clone_ref(py),
                pending_body: false,
            },
        )
    }

    #[pyo3(signature = (content_type, scope, max_files, max_fields, max_part_size))]
    fn form(
        &self,
        py: Python<'_>,
        content_type: Option<String>,
        scope: Py<PyAny>,
        max_files: &Bound<'_, PyAny>,
        max_fields: &Bound<'_, PyAny>,
        max_part_size: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyFormAwaitableContext>> {
        let machine = FormMachine {
            shared: self.shared.clone_ref(py),
            stream: RequestStreamState::default(),
            content_type,
            scope,
            max_files: max_files.extract::<f64>()?,
            max_files_display: max_files.str()?.extract::<String>()?,
            max_fields: max_fields.extract::<f64>()?,
            max_fields_display: max_fields.str()?.extract::<String>()?,
            max_part_size: max_part_size.extract::<i64>()?,
            multipart_parser: None,
            multipart_events: VecDeque::new(),
            multipart_operations: VecDeque::new(),
            multipart_items: Vec::new(),
            multipart_uploads: Vec::new(),
            multipart_temp_files: Vec::new(),
            multipart_input_finished: false,
            multipart_parse_succeeded: false,
            body: Vec::new(),
            urlencoded_limits: UrlEncodedFormLimits::default(),
            pending_receive: false,
            pending_multipart_operation: false,
        };
        let awaitable = into_sendable_python_awaitable(py, machine)?;
        Py::new(
            py,
            PyFormAwaitableContext {
                awaitable,
                entered: Py::new(py, EnteredFormState { form: None })?,
            },
        )
    }

    fn close_form(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            CloseFormMachine {
                shared: self.shared.clone_ref(py),
                pending_close: false,
            },
        )
    }

    fn is_disconnected(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let receive = borrow_runtime(py, &self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| {
                PyRuntimeError::new_err("Receive channel has not been made available")
            })?;
        into_sendable_python_awaitable(
            py,
            RequestDisconnectedMachine {
                shared: self.shared.clone_ref(py),
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
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

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
        stream_operation(
            py,
            &slf,
            StreamCommand::Throw(error.into_value(py).into_any()),
        )
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
    let shared = borrowed.shared.clone_ref(py);
    let state = borrowed.state.clone();
    let protocol = borrowed.protocol.clone();
    drop(borrowed);
    let reuse_error = match &command {
        StreamCommand::Advance(_) => "cannot reuse already awaited __anext__()/asend()",
        StreamCommand::Throw(_) | StreamCommand::Close => {
            "cannot reuse already awaited aclose()/athrow()"
        }
    };
    into_sendable_python_awaitable_with_reuse_error(
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
    Throw(Py<PyAny>),
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
    let py = module.py();
    module.add_function(wrap_pyfunction!(empty_receive, module)?)?;
    module.add_function(wrap_pyfunction!(empty_send, module)?)?;
    let multipart_exception = py.get_type::<MultiPartException>();
    module.add("MultiPartException", &multipart_exception)?;
    multipart_exception.setattr("__module__", "starlette.formparsers")?;
    module.add_class::<PyRequestBody>()?;
    module.add_class::<PyFormAwaitableContext>()?;
    module.add_class::<PyRequestStream>()?;
    module.add_class::<PyHTTPConnection>()?;
    Ok(())
}

#[pyfunction(name = "_empty_receive")]
fn empty_receive(py: Python<'_>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(py, EmptyReceive)
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
    into_sendable_python_awaitable(py, EmptySend)
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
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        visit.call(&self.receive)?;
        visit.call(&self.cancel_scope)?;
        Ok(())
    }

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
                    borrow_runtime_mut(py, &self.shared)?.request_disconnected = true;
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
        if borrow_runtime(py, &self.shared)?.request_disconnected {
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
        let disconnected = borrow_runtime(py, &self.shared)?.request_disconnected;
        Ok(MachineAction::Complete(
            PyBool::new(py, disconnected).to_owned().into_any().unbind(),
        ))
    }
}

struct BodyMachine {
    shared: SharedRequestBody,
    stream: RequestStreamState,
    body: Vec<u8>,
    pending_receive: bool,
}

impl AwaitableStateMachine for BodyMachine {
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        Ok(())
    }

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
                        self.abort_collection(py);
                        self.stream.fail();
                        return Err(error);
                    }
                };
                let progress = {
                    let mut runtime = borrow_runtime_mut(py, &self.shared)?;
                    if message_type == "http.disconnect" {
                        runtime.request_disconnected = true;
                    }
                    self.stream.accept_pending(
                        &mut runtime.accumulator,
                        &message_type,
                        &body,
                        more_body,
                    )
                };
                match progress {
                    Ok(progress) => self.consume_progress(py, progress),
                    Err(error) => {
                        self.abort_collection(py);
                        Err(request_body_error(py, error))
                    }
                }
            }
            MachineResume::AsyncIterationComplete(_) => {
                self.abort_collection(py);
                self.stream.fail();
                Err(PyRuntimeError::new_err(
                    "async generator raised StopAsyncIteration",
                ))
            }
            MachineResume::Error(error) => {
                self.abort_collection(py);
                self.stream.fail();
                Err(error)
            }
        }
    }
}

impl BodyMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if let Some(body) = cached_body_object(py, &self.shared)? {
            return Ok(MachineAction::Complete(body));
        }

        let result = {
            let mut runtime = borrow_runtime_mut(py, &self.shared)?;
            runtime.accumulator.begin_body_collection()
        };
        result.map_err(|error| request_body_error(py, error))?;
        let progress = {
            let runtime = borrow_runtime(py, &self.shared)?;
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
                RequestStreamProgress::Chunk(chunk) | RequestStreamProgress::CachedBody(chunk) => {
                    self.body.extend_from_slice(&chunk);
                    progress = {
                        let runtime = borrow_runtime(py, &self.shared)?;
                        self.stream.next(&runtime.accumulator)
                    }
                    .map_err(|error| {
                        self.abort_collection(py);
                        request_body_error(py, error)
                    })?;
                }
                RequestStreamProgress::Complete => {
                    return complete_cached_body(py, &self.shared, &self.body);
                }
            }
        }
    }

    fn await_receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = borrow_runtime(py, &self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py));
        let Some(receive) = receive else {
            self.abort_collection(py);
            self.stream.fail();
            return Err(PyRuntimeError::new_err(
                "Receive channel has not been made available",
            ));
        };
        let awaitable = match receive.bind(py).call0() {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.abort_collection(py);
                self.stream.fail();
                return Err(error);
            }
        };
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn abort_collection(&self, py: Python<'_>) {
        if let Ok(mut runtime) = self.shared.try_borrow_mut(py) {
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
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        match &self.command {
            StreamCommand::Advance(value) => visit.call(value)?,
            StreamCommand::Throw(error) => visit.call(error)?,
            StreamCommand::Close => {}
        }
        Ok(())
    }

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
                    let mut runtime = borrow_runtime_mut(py, &self.shared)?;
                    if message_type == "http.disconnect" {
                        runtime.request_disconnected = true;
                    }
                    let mut state = borrow_stream_mut(&self.state)?;
                    state.accept_pending(&mut runtime.accumulator, &message_type, &body, more_body)
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
        let yielded_chunk = protocol.yielded_chunk;
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
                return Err(PyErr::from_value(error.bind(py).clone()));
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

        // Another iterator on this Request may have consumed the final ASGI
        // message while this stream was suspended after yielding a chunk. The
        // upstream generator shares `_stream_consumed`, so it yields its final
        // empty chunk instead of issuing one more receive call.
        if yielded_chunk && borrow_runtime(py, &self.shared)?.accumulator.is_consumed() {
            self.finish(false);
            return Ok(MachineAction::Complete(
                PyBytes::new(py, b"").unbind().into_any(),
            ));
        }

        self.next_action(py)
    }

    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let progress = {
            let runtime = borrow_runtime(py, &self.shared)?;
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
                let is_terminal_chunk =
                    body.is_empty() && borrow_runtime(py, &self.shared)?.accumulator.is_consumed();
                let body = PyBytes::new(py, &body).unbind().into_any();
                self.finish(!is_terminal_chunk);
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
        let receive = borrow_runtime(py, &self.shared)?
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
            if yielded {
                protocol.yielded_chunk = true;
            }
            if !yielded {
                protocol.closed = true;
            }
        }
    }
}

struct FormMachine {
    shared: SharedRequestBody,
    stream: RequestStreamState,
    content_type: Option<String>,
    scope: Py<PyAny>,
    max_files: f64,
    max_files_display: String,
    max_fields: f64,
    max_fields_display: String,
    max_part_size: i64,
    multipart_parser: Option<MultipartFormParser>,
    multipart_events: VecDeque<MultipartFormEvent>,
    multipart_operations: VecDeque<MultipartFileOperation>,
    multipart_items: Vec<(String, Py<PyAny>)>,
    multipart_uploads: Vec<MultipartUpload>,
    multipart_temp_files: Vec<Py<PyAny>>,
    multipart_input_finished: bool,
    multipart_parse_succeeded: bool,
    body: Vec<u8>,
    urlencoded_limits: UrlEncodedFormLimits,
    pending_receive: bool,
    pending_multipart_operation: bool,
}

#[derive(Default)]
struct UrlEncodedFormLimits {
    field_size: usize,
    field_count: usize,
    field_started: bool,
    has_equals: bool,
}

impl UrlEncodedFormLimits {
    fn push_chunk(
        &mut self,
        chunk: &[u8],
        max_fields: f64,
        max_part_size: i64,
    ) -> Result<(), FormDataParseError> {
        for byte in chunk {
            if *byte == b'&' {
                self.finish_field(max_fields)?;
                continue;
            }

            self.field_started = true;
            if *byte == b'=' && !self.has_equals {
                self.has_equals = true;
                continue;
            }

            self.field_size += 1;
            if self.field_size as i128 > i128::from(max_part_size) {
                return Err(FormDataParseError::FieldTooLarge {
                    max_part_size_kb: max_part_size / 1024,
                });
            }
        }
        Ok(())
    }

    fn finish(&mut self, max_fields: f64) -> Result<(), FormDataParseError> {
        self.finish_field(max_fields)
    }

    fn finish_field(&mut self, max_fields: f64) -> Result<(), FormDataParseError> {
        if !self.field_started {
            return Ok(());
        }

        self.field_count += 1;
        self.field_size = 0;
        self.field_started = false;
        self.has_equals = false;
        if self.field_count as f64 > max_fields {
            return Err(FormDataParseError::TooManyFields);
        }
        Ok(())
    }
}

struct MultipartUpload {
    part_index: usize,
    name: String,
    upload: Py<PyAny>,
}

enum MultipartFileOperation {
    Write { part_index: usize, data: Vec<u8> },
    Seek { part_index: usize },
}

impl AwaitableStateMachine for FormMachine {
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        visit.call(&self.scope)?;
        for (_, item) in &self.multipart_items {
            visit.call(item)?;
        }
        for upload in &self.multipart_uploads {
            visit.call(&upload.upload)?;
        }
        for file in &self.multipart_temp_files {
            visit.call(file)?;
        }
        Ok(())
    }

    fn unawaited_warning(&self) -> Option<&'static std::ffi::CStr> {
        Some(c"coroutine 'Request._get_form' was never awaited")
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let result = self.resume_inner(py, input);
        if let Err(error) = result {
            self.stream.fail();
            if !self.multipart_parse_succeeded {
                return match self.close_multipart_files(py) {
                    Ok(()) => Err(error),
                    Err(cleanup_error) => Err(cleanup_error),
                };
            }
            return Err(error);
        }
        result
    }
}

impl FormMachine {
    fn resume_inner(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(message) => {
                if self.pending_receive {
                    self.pending_receive = false;
                    let (message_type, body, more_body) = request_message(py, message)?;
                    let progress = {
                        let mut runtime = borrow_runtime_mut(py, &self.shared)?;
                        if message_type == "http.disconnect" {
                            runtime.request_disconnected = true;
                        }
                        self.stream.accept_pending(
                            &mut runtime.accumulator,
                            &message_type,
                            &body,
                            more_body,
                        )
                    }
                    .map_err(|error| request_body_error(py, error))?;
                    self.consume_progress(py, progress)
                } else if self.pending_multipart_operation {
                    self.pending_multipart_operation = false;
                    self.resume_multipart_operations(py)
                } else {
                    Err(PyRuntimeError::new_err(
                        "request form parsing received an unexpected result",
                    ))
                }
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyRuntimeError::new_err(
                "async generator raised StopAsyncIteration",
            )),
            MachineResume::Error(error) => Err(error),
        }
    }

    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if let Some(form) = borrow_runtime(py, &self.shared)?.form_object.as_ref() {
            return Ok(MachineAction::Complete(form.clone_ref(py)));
        }

        if py
            .import("starlette.requests")?
            .getattr("parse_options_header")?
            .is_none()
        {
            return Err(PyAssertionError::new_err(
                "The `python-multipart` library must be installed to use form parsing.",
            ));
        }

        match request_form_media_type(self.content_type.as_deref()) {
            FormMediaType::Multipart => {
                if let Some(content_type) = self.content_type.as_deref() {
                    self.multipart_parser = Some(
                        MultipartFormParser::new(
                            content_type,
                            self.max_files,
                            &self.max_files_display,
                            self.max_fields,
                            &self.max_fields_display,
                            self.max_part_size,
                        )
                        .map_err(|error| self.multipart_parse_error(py, error))?,
                    );
                }
                let progress = {
                    let runtime = borrow_runtime(py, &self.shared)?;
                    self.stream.next(&runtime.accumulator)
                }
                .map_err(|error| request_body_error(py, error))?;
                self.consume_progress(py, progress)
            }
            FormMediaType::Other => self.complete_form(py, NativeFormData::default()),
            FormMediaType::UrlEncoded => {
                let progress = {
                    let runtime = borrow_runtime(py, &self.shared)?;
                    self.stream.next(&runtime.accumulator)
                }
                .map_err(|error| request_body_error(py, error))?;
                self.consume_progress(py, progress)
            }
        }
    }

    fn consume_progress(
        &mut self,
        py: Python<'_>,
        mut progress: RequestStreamProgress,
    ) -> PyResult<MachineAction> {
        loop {
            match progress {
                RequestStreamProgress::Receive => return self.await_receive(py),
                RequestStreamProgress::Chunk(body) | RequestStreamProgress::CachedBody(body) => {
                    if matches!(
                        request_form_media_type(self.content_type.as_deref()),
                        FormMediaType::Multipart
                    ) {
                        let Some(parser) = self.multipart_parser.as_mut() else {
                            return Err(PyRuntimeError::new_err(
                                "multipart form parser has not been initialized",
                            ));
                        };
                        let result = parser.push_chunk(body);
                        let events = parser.drain_events();
                        if let Err(error) = result {
                            self.create_multipart_files_from_error_events(py, events)?;
                            return Err(self.multipart_parse_error(py, error));
                        }
                        self.multipart_events.extend(events);
                        if let Some(action) = self.prepare_multipart_events(py)? {
                            return Ok(action);
                        }
                    } else {
                        self.urlencoded_limits
                            .push_chunk(&body, self.max_fields, self.max_part_size)
                            .map_err(|error| self.parse_error(py, error))?;
                        self.body.extend_from_slice(&body);
                    }
                    progress = {
                        let runtime = borrow_runtime(py, &self.shared)?;
                        self.stream.next(&runtime.accumulator)
                    }
                    .map_err(|error| request_body_error(py, error))?;
                }
                RequestStreamProgress::Complete => return self.finish_form(py),
            }
        }
    }

    fn await_receive(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = borrow_runtime(py, &self.shared)?
            .receive
            .as_ref()
            .map(|receive| receive.clone_ref(py))
            .ok_or_else(|| {
                PyRuntimeError::new_err("Receive channel has not been made available")
            })?;
        let awaitable = receive.bind(py).call0()?;
        self.pending_receive = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish_form(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if matches!(
            request_form_media_type(self.content_type.as_deref()),
            FormMediaType::Multipart
        ) {
            let parser = self.multipart_parser.as_mut().ok_or_else(|| {
                PyRuntimeError::new_err("multipart form parser has not been initialized")
            })?;
            let result = parser.finish_events();
            let events = parser.drain_events();
            if let Err(error) = result {
                self.create_multipart_files_from_error_events(py, events)?;
                return Err(self.multipart_parse_error(py, error));
            }
            self.multipart_events.extend(events);
            self.multipart_input_finished = true;
            return self
                .prepare_multipart_events(py)?
                .ok_or_else(|| PyRuntimeError::new_err("multipart parsing did not complete"));
        }
        self.urlencoded_limits
            .finish(self.max_fields)
            .map_err(|error| self.parse_error(py, error))?;
        let form =
            NativeFormData::parse_urlencoded(&self.body, self.max_fields, self.max_part_size)
                .map_err(|error| self.parse_error(py, error))?;
        self.complete_form(py, form)
    }

    fn parse_error(&self, py: Python<'_>, error: FormDataParseError) -> PyErr {
        let message = match error {
            FormDataParseError::TooManyFields => format!(
                "Too many fields. Maximum number of fields is {}.",
                self.max_fields_display
            ),
            FormDataParseError::FieldTooLarge { max_part_size_kb } => {
                format!("Field exceeded maximum size of {max_part_size_kb}KB.")
            }
        };
        self.form_exception(py, &message)
    }

    fn multipart_parse_error(&self, py: Python<'_>, error: MultipartFormParseError) -> PyErr {
        self.form_exception(py, &error.message())
    }

    fn form_exception(&self, py: Python<'_>, message: &str) -> PyErr {
        let has_app = self
            .scope
            .bind(py)
            .call_method1("__contains__", ("app",))
            .and_then(|present| present.is_truthy());
        match has_app {
            Ok(true) => {
                let kwargs = PyDict::new(py);
                if let Err(error) = kwargs.set_item("status_code", 400) {
                    return error;
                }
                if let Err(error) = kwargs.set_item("detail", message) {
                    return error;
                }
                py.import("starlette.exceptions")
                    .and_then(|module| module.getattr("HTTPException"))
                    .and_then(|exception_type| exception_type.call((), Some(&kwargs)))
                    .map_or_else(|error| error, PyErr::from_value)
            }
            Ok(false) => {
                let exception = MultiPartException::new_err(message.to_owned());
                match exception.value(py).setattr("message", message) {
                    Ok(()) => exception,
                    Err(error) => error,
                }
            }
            Err(error) => error,
        }
    }

    fn complete_form(&self, py: Python<'_>, form: NativeFormData) -> PyResult<MachineAction> {
        let form_items = form
            .multi_items()
            .iter()
            .map(|(key, value)| (key.clone(), PyString::new(py, value).into_any().unbind()))
            .collect::<Vec<_>>();
        self.complete_form_items(py, form_items)
    }

    fn prepare_multipart_events(&mut self, py: Python<'_>) -> PyResult<Option<MachineAction>> {
        let mut writes = VecDeque::new();
        let mut seeks = VecDeque::new();
        while let Some(event) = self.multipart_events.pop_front() {
            match event {
                MultipartFormEvent::TextField { part, .. } => {
                    let text = part.text.ok_or_else(|| {
                        PyRuntimeError::new_err("multipart text field has no decoded value")
                    })?;
                    self.multipart_items
                        .push((part.name, PyString::new(py, &text).into_any().unbind()));
                }
                MultipartFormEvent::FileStarted {
                    part_index,
                    name,
                    filename,
                    headers,
                } => self.create_multipart_upload(py, part_index, name, filename, headers)?,
                MultipartFormEvent::FileChunk { part_index, data } => {
                    writes.push_back(MultipartFileOperation::Write { part_index, data });
                }
                MultipartFormEvent::FileFinished {
                    part_index,
                    size: _,
                } => {
                    let upload = self.multipart_upload(py, part_index)?;
                    self.multipart_items.push((upload.name, upload.upload));
                    seeks.push_back(MultipartFileOperation::Seek { part_index });
                }
            }
        }
        writes.append(&mut seeks);
        self.multipart_operations.extend(writes);
        self.start_next_multipart_operation(py)
    }

    fn resume_multipart_operations(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if let Some(action) = self.start_next_multipart_operation(py)? {
            return Ok(action);
        }
        let progress = {
            let runtime = borrow_runtime(py, &self.shared)?;
            self.stream.next(&runtime.accumulator)
        }
        .map_err(|error| request_body_error(py, error))?;
        self.consume_progress(py, progress)
    }

    fn start_next_multipart_operation(
        &mut self,
        py: Python<'_>,
    ) -> PyResult<Option<MachineAction>> {
        if let Some(operation) = self.multipart_operations.pop_front() {
            let awaitable = match operation {
                MultipartFileOperation::Write { part_index, data } => self
                    .multipart_upload(py, part_index)?
                    .upload
                    .bind(py)
                    .call_method1("write", (PyBytes::new(py, &data),))?,
                MultipartFileOperation::Seek { part_index } => self
                    .multipart_upload(py, part_index)?
                    .upload
                    .bind(py)
                    .call_method1("seek", (0,))?,
            };
            self.pending_multipart_operation = true;
            return Ok(Some(MachineAction::Await(awaitable.unbind())));
        }
        if self.multipart_input_finished {
            self.multipart_parse_succeeded = true;
            let items = std::mem::take(&mut self.multipart_items);
            return self.complete_form_items(py, items).map(Some);
        }
        Ok(None)
    }

    fn create_multipart_upload(
        &mut self,
        py: Python<'_>,
        part_index: usize,
        name: String,
        filename: String,
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    ) -> PyResult<()> {
        let file = multipart_spooled_tempfile(py)?;
        self.multipart_temp_files.push(file.clone_ref(py));
        let upload = multipart_upload_file(py, file.bind(py), filename, headers)?;
        self.multipart_uploads.push(MultipartUpload {
            part_index,
            name,
            upload,
        });
        Ok(())
    }

    fn create_multipart_files_from_error_events(
        &mut self,
        py: Python<'_>,
        events: Vec<MultipartFormEvent>,
    ) -> PyResult<()> {
        for event in events {
            if let MultipartFormEvent::FileStarted {
                part_index,
                name,
                filename,
                headers,
            } = event
            {
                self.create_multipart_upload(py, part_index, name, filename, headers)?;
            }
        }
        Ok(())
    }

    fn multipart_upload(&self, py: Python<'_>, part_index: usize) -> PyResult<MultipartUpload> {
        self.multipart_uploads
            .iter()
            .find(|upload| upload.part_index == part_index)
            .map(|upload| MultipartUpload {
                part_index,
                name: upload.name.clone(),
                upload: upload.upload.clone_ref(py),
            })
            .ok_or_else(|| PyRuntimeError::new_err("multipart parser lost an uploaded file"))
    }

    fn close_multipart_files(&mut self, py: Python<'_>) -> PyResult<()> {
        for file in &self.multipart_temp_files {
            file.bind(py).call_method0("close")?;
        }
        self.multipart_temp_files.clear();
        self.multipart_uploads.clear();
        self.multipart_operations.clear();
        self.multipart_events.clear();
        self.multipart_items.clear();
        Ok(())
    }

    fn complete_form_items(
        &self,
        py: Python<'_>,
        items: Vec<(String, Py<PyAny>)>,
    ) -> PyResult<MachineAction> {
        let form_items = PyList::new(py, items)?;
        let form = py
            .import("starlette.datastructures")?
            .getattr("FormData")?
            .call1((form_items,))?
            .unbind();
        borrow_runtime_mut(py, &self.shared)?.form_object = Some(form.clone_ref(py));
        Ok(MachineAction::Complete(form))
    }
}

enum FormMediaType {
    UrlEncoded,
    Multipart,
    Other,
}

fn multipart_spooled_tempfile(py: Python<'_>) -> PyResult<Py<PyAny>> {
    // Python's SpooledTemporaryFile is the public `.file` representation in
    // Starlette's API. It remains a boundary object; Rust selects file parts,
    // sets the spool threshold, and constructs the UploadFile wrapper.
    let spool_kwargs = PyDict::new(py);
    spool_kwargs.set_item("max_size", 1024 * 1024)?;
    py.import("tempfile")?
        .getattr("SpooledTemporaryFile")?
        .call((), Some(&spool_kwargs))
        .map(Bound::unbind)
}

fn multipart_upload_file(
    py: Python<'_>,
    file: &Bound<'_, PyAny>,
    filename: String,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
) -> PyResult<Py<PyAny>> {
    let raw_headers = PyList::empty(py);
    for (name, value) in headers {
        raw_headers.append((PyBytes::new(py, &name), PyBytes::new(py, &value)))?;
    }
    let headers_kwargs = PyDict::new(py);
    headers_kwargs.set_item("raw", raw_headers)?;
    let headers = py
        .import("starlette.datastructures")?
        .getattr("Headers")?
        .call((), Some(&headers_kwargs))?;

    let upload_kwargs = PyDict::new(py);
    upload_kwargs.set_item("size", 0)?;
    upload_kwargs.set_item("filename", filename)?;
    upload_kwargs.set_item("headers", headers)?;
    py.import("starlette.datastructures")?
        .getattr("UploadFile")?
        .call((file,), Some(&upload_kwargs))
        .map(Bound::unbind)
}

fn request_form_media_type(content_type: Option<&str>) -> FormMediaType {
    let media_type = content_type
        .and_then(|value| value.split(';').next())
        .unwrap_or_default()
        .trim();
    if media_type.eq_ignore_ascii_case("application/x-www-form-urlencoded") {
        FormMediaType::UrlEncoded
    } else if media_type.eq_ignore_ascii_case("multipart/form-data") {
        FormMediaType::Multipart
    } else {
        FormMediaType::Other
    }
}

type SharedEnteredForm = Py<EnteredFormState>;

#[pyclass]
struct EnteredFormState {
    form: Option<Py<PyAny>>,
}

#[pymethods]
impl EnteredFormState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.form)
    }

    fn __clear__(&mut self) {
        self.form = None;
    }
}

#[pyclass]
struct PyFormAwaitableContext {
    awaitable: Py<PyAny>,
    entered: SharedEnteredForm,
}

#[pymethods]
impl PyFormAwaitableContext {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.awaitable)?;
        visit.call(&self.entered)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.awaitable = py.None();
    }

    fn __await__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.awaitable
            .bind(py)
            .call_method0("__await__")
            .map(Bound::unbind)
    }

    fn __aenter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            EnterFormMachine {
                awaitable: self.awaitable.clone_ref(py),
                entered: self.entered.clone_ref(py),
                pending: false,
            },
        )
    }

    #[pyo3(signature = (exc_type=None, exc=None, traceback=None))]
    fn __aexit__(
        &self,
        py: Python<'_>,
        exc_type: Option<Py<PyAny>>,
        exc: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let _ = (exc_type, exc, traceback);
        let form = self
            .entered
            .try_borrow(py)
            .map_err(|_| PyRuntimeError::new_err("form context is already borrowed"))?
            .form
            .as_ref()
            .map(|form| form.clone_ref(py))
            .ok_or_else(|| PyAttributeError::new_err("form context has not been entered"))?;
        form.bind(py).call_method0("close").map(Bound::unbind)
    }
}

struct EnterFormMachine {
    awaitable: Py<PyAny>,
    entered: SharedEnteredForm,
    pending: bool,
}

impl AwaitableStateMachine for EnterFormMachine {
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.awaitable)?;
        visit.call(&self.entered)?;
        Ok(())
    }

    fn unawaited_warning(&self) -> Option<&'static std::ffi::CStr> {
        Some(c"coroutine 'AwaitableOrContextManagerWrapper.__aenter__' was never awaited")
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                self.pending = true;
                Ok(MachineAction::Await(self.awaitable.clone_ref(py)))
            }
            MachineResume::Value(form) if self.pending => {
                self.pending = false;
                let previous = self
                    .entered
                    .try_borrow_mut(py)
                    .map_err(|_| PyRuntimeError::new_err("form context is already borrowed"))?
                    .form
                    .replace(form.clone_ref(py));
                drop(previous);
                Ok(MachineAction::Complete(form))
            }
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
            _ => Err(PyRuntimeError::new_err(
                "form context enter received an unexpected result",
            )),
        }
    }
}

struct CloseFormMachine {
    shared: SharedRequestBody,
    pending_close: bool,
}

impl AwaitableStateMachine for CloseFormMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        Ok(())
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending_close => {
                let form = borrow_runtime(py, &self.shared)?
                    .form_object
                    .as_ref()
                    .map(|form| form.clone_ref(py));
                match form {
                    Some(form) => {
                        self.pending_close = true;
                        Ok(MachineAction::Await(
                            form.bind(py).call_method0("close")?.unbind(),
                        ))
                    }
                    None => Ok(MachineAction::Complete(py.None())),
                }
            }
            MachineResume::Value(_) if self.pending_close => {
                self.pending_close = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
            _ => Err(PyRuntimeError::new_err(
                "request form close received an unexpected result",
            )),
        }
    }
}

struct JsonMachine {
    shared: SharedRequestBody,
    pending_body: bool,
}

impl AwaitableStateMachine for JsonMachine {
    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        Ok(())
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if let Some(value) = borrow_runtime(py, &self.shared)?.json_object.as_ref() {
                    return Ok(MachineAction::Complete(value.clone_ref(py)));
                }
                self.pending_body = true;
                let awaitable = into_sendable_python_awaitable(
                    py,
                    BodyMachine {
                        shared: self.shared.clone_ref(py),
                        stream: RequestStreamState::default(),
                        body: Vec::new(),
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
                borrow_runtime_mut(py, &self.shared)?.json_object = Some(result.clone_ref(py));
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

fn complete_cached_body(
    py: Python<'_>,
    shared: &SharedRequestBody,
    body: &[u8],
) -> PyResult<MachineAction> {
    let body = {
        let mut runtime = borrow_runtime_mut(py, shared)?;
        runtime
            .accumulator
            .cache_body_from(body)
            .map_err(|error| request_body_error(py, error))?
            .to_vec()
    };
    let body = PyBytes::new(py, &body).unbind();
    borrow_runtime_mut(py, shared)?.body_object = Some(body.clone_ref(py));
    Ok(MachineAction::Complete(body.into_any()))
}

fn cached_body_object(py: Python<'_>, shared: &SharedRequestBody) -> PyResult<Option<Py<PyAny>>> {
    if let Some(cached) = borrow_runtime(py, shared)?.body_object.as_ref() {
        return Ok(Some(cached.clone_ref(py).into_any()));
    }

    let body = {
        let runtime = borrow_runtime(py, shared)?;
        runtime.accumulator.cached_body().map(<[u8]>::to_vec)
    };
    let Some(body) = body else {
        return Ok(None);
    };
    let body = PyBytes::new(py, &body).unbind();
    borrow_runtime_mut(py, shared)?.body_object = Some(body.clone_ref(py));
    Ok(Some(body.into_any()))
}

fn borrow_runtime<'py>(
    py: Python<'py>,
    shared: &'py SharedRequestBody,
) -> PyResult<PyRef<'py, RequestBodyRuntime>> {
    shared
        .try_borrow(py)
        .map_err(|_| PyRuntimeError::new_err("request body state is already borrowed"))
}

fn borrow_runtime_mut<'py>(
    py: Python<'py>,
    shared: &'py SharedRequestBody,
) -> PyResult<PyRefMut<'py, RequestBodyRuntime>> {
    shared
        .try_borrow_mut(py)
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
