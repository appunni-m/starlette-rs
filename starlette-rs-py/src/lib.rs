//! Python boundary for the first Starlette compatibility slice.
//!
//! The extension delegates route matching, response construction, cookie
//! generation, response event sequencing, and lifespan state transitions to
//! `starlette-rs`. Python owns user callables and the active event loop; Rust
//! continuations invoke and await callbacks through that loop without creating
//! a second executor or event loop.

mod awaitable;
mod background;
mod runtime_calls;

use pyo3::exceptions::PyKeyError;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyTuple};
use starlette_rs::{
    AsgiScopeKind, BodyProgress, ConnectionUrlError, Cookies as NativeCookies,
    DEFAULT_EXCLUDED_CONTENT_TYPES, DebugTracebackFrame, DetailedRouteMatch, GzipBodyOutput,
    GzipCompressionError, GzipConfig as NativeGzipConfig, GzipHeader,
    GzipResponder as NativeGzipResponder, LifespanAction, LifespanError, LifespanState,
    QueryParams as NativeQueryParams, RequestBodyAccumulator as NativeRequestBodyAccumulator,
    RequestBodyError, RequestHeaders as NativeRequestHeaders, Response, ResponseError,
    ResponseEvent, RouteTable, ServerErrorPlan, ServerErrorPolicy as NativeServerErrorPolicy,
    ServerErrorState as NativeServerErrorState, WebSocketState, WebSocketStateMachine,
    classify_scope, connection_url as native_connection_url, parse_cookie_header,
};

type RouteDecision = (
    String,
    Option<usize>,
    Option<Py<PyResponse>>,
    Vec<(String, String)>,
    Vec<String>,
);
type PyGzipResponseStart = (u16, Vec<GzipHeader>);
type PyGzipBodyOutput = (Option<PyGzipResponseStart>, Vec<u8>);

#[pyclass(name = "RouteTable")]
struct PyRouteTable {
    inner: RouteTable,
}

#[pyclass(name = "ExceptionHandlerTable")]
struct PyExceptionHandlerTable {
    inner: starlette_rs::ExceptionHandlerTable<u64>,
}

#[pyclass(name = "ServerErrorPolicy")]
struct PyServerErrorPolicy {
    inner: NativeServerErrorPolicy,
}

#[pyclass(name = "ServerErrorState")]
struct PyServerErrorState {
    inner: NativeServerErrorState,
}

#[pyclass(name = "WebSocketStateMachine")]
struct PyWebSocketStateMachine {
    inner: WebSocketStateMachine,
}

type PyDebugTracebackFrame = (String, usize, String, Vec<String>, usize);

#[pymethods]
impl PyExceptionHandlerTable {
    #[new]
    fn new(status_handlers: Vec<(String, usize)>, class_handlers: Vec<(u64, usize)>) -> Self {
        let mut inner = starlette_rs::ExceptionHandlerTable::new();
        for (status_key, handler_index) in status_handlers {
            let _ = inner.insert_status(status_key, handler_index);
        }
        for (class_key, handler_index) in class_handlers {
            let _ = inner.insert_class(class_key, handler_index);
        }
        Self { inner }
    }

    fn select(&self, status_key: Option<&str>, exception_mro: Vec<u64>) -> Option<usize> {
        self.inner.select(status_key, &exception_mro)
    }
}

#[pymethods]
impl PyServerErrorPolicy {
    #[new]
    fn new(debug: bool) -> Self {
        Self {
            inner: NativeServerErrorPolicy::new(debug),
        }
    }

    /// Registers a normalized `500` or `Exception` handler in input order.
    fn register_handler(&mut self, handler_index: usize) -> Option<usize> {
        self.inner.register_handler(handler_index)
    }

    /// Returns `(plan_name, handler_index)` for an HTTP error.
    fn plan(&self, accept: Option<String>) -> (&'static str, Option<usize>) {
        server_error_plan_parts(self.inner.plan(accept.as_deref().map(str::as_bytes)))
    }
}

#[pymethods]
impl PyServerErrorState {
    #[new]
    fn new() -> Self {
        Self {
            inner: NativeServerErrorState::new(),
        }
    }

    /// Records an ASGI send message and returns the current response-start state.
    fn observe_send(&mut self, message: &Bound<'_, PyDict>) -> PyResult<bool> {
        let message_type = message
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        Ok(self.inner.observe_send(&message_type))
    }

    fn response_started(&self) -> bool {
        self.inner.response_started()
    }

    fn should_send_response(&self) -> bool {
        self.inner.should_send_response()
    }
}

#[pymethods]
impl PyWebSocketStateMachine {
    #[new]
    fn new() -> Self {
        Self {
            inner: WebSocketStateMachine::new(),
        }
    }

    fn client_state(&self) -> u8 {
        websocket_state_code(self.inner.client_state())
    }

    fn application_state(&self) -> u8 {
        websocket_state_code(self.inner.application_state())
    }

    fn receive(&mut self, message_type: &str) -> PyResult<()> {
        self.inner
            .receive(message_type)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))
    }

    #[pyo3(signature = (message_type, more_body=false))]
    fn begin_send(&mut self, message_type: &str, more_body: bool) -> PyResult<bool> {
        self.inner
            .begin_send(message_type, more_body)
            .map_err(|error| PyRuntimeError::new_err(error.to_string()))
    }

    fn send_failed(&mut self) {
        self.inner.send_failed();
    }
}

#[pymethods]
impl PyRouteTable {
    #[new]
    fn new() -> Self {
        Self {
            inner: RouteTable::new(),
        }
    }

    fn add_route(&mut self, path: String, methods: Vec<String>) -> PyResult<usize> {
        self.inner
            .add_route(path, methods)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    fn match_route(&self, py: Python<'_>, path: &str, method: &str) -> PyResult<RouteDecision> {
        route_decision(py, self.inner.matches_detailed(path, method))
    }

    /// Matches an ASGI scope path after applying its `root_path` prefix.
    fn match_route_with_root_path(
        &self,
        py: Python<'_>,
        path: &str,
        root_path: &str,
        method: &str,
    ) -> PyResult<RouteDecision> {
        route_decision(
            py,
            self.inner
                .matches_detailed_with_root_path(path, root_path, method),
        )
    }

    /// Finds a matching trailing-slash alternative using the ASGI `root_path`.
    fn find_slash_redirect_path(
        &self,
        path: &str,
        root_path: &str,
        method: &str,
    ) -> Option<String> {
        self.inner.find_slash_redirect_path(path, root_path, method)
    }

    /// Builds one route's path from converter-formatted parameters.
    fn build_path(
        &self,
        route_index: usize,
        path_params: Vec<(String, String)>,
    ) -> PyResult<String> {
        self.inner
            .build_path(route_index, &path_params)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    /// Partially builds one route's path and returns parameters for a child route.
    fn build_path_partial(
        &self,
        route_index: usize,
        path_params: Vec<(String, String)>,
    ) -> PyResult<(String, Vec<(String, String)>)> {
        self.inner
            .build_path_partial(route_index, &path_params)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }
}

fn route_decision(py: Python<'_>, route_match: DetailedRouteMatch) -> PyResult<RouteDecision> {
    let fallback = route_match
        .fallback_response()
        .map_err(response_error)?
        .map(|inner| Py::new(py, PyResponse { inner }))
        .transpose()?;
    let (kind, route_index, path_params, allowed_methods) = match route_match {
        DetailedRouteMatch::Matched {
            route_index,
            path_params,
        } => ("matched", Some(route_index), path_params, Vec::new()),
        DetailedRouteMatch::MethodNotAllowed {
            route_index,
            allowed_methods,
            path_params,
        } => (
            "method_not_allowed",
            Some(route_index),
            path_params,
            allowed_methods,
        ),
        DetailedRouteMatch::NotFound => ("not_found", None, Vec::new(), Vec::new()),
    };
    Ok((
        kind.to_owned(),
        route_index,
        fallback,
        path_params,
        allowed_methods,
    ))
}

#[pyclass(name = "RequestHeaders")]
struct PyRequestHeaders {
    inner: NativeRequestHeaders,
}

#[pymethods]
impl PyRequestHeaders {
    #[new]
    fn new(headers: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        Self {
            inner: NativeRequestHeaders::new(headers),
        }
    }

    fn raw(&self) -> Vec<(Vec<u8>, Vec<u8>)> {
        self.inner.raw().to_vec()
    }

    fn get(&self, name: &[u8]) -> Option<Vec<u8>> {
        self.inner.get(name).map(<[u8]>::to_vec)
    }

    fn get_list(&self, name: &[u8]) -> Vec<Vec<u8>> {
        self.inner
            .get_list(name)
            .into_iter()
            .map(<[u8]>::to_vec)
            .collect()
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }
}

#[pyclass(name = "QueryParams")]
struct PyQueryParams {
    inner: NativeQueryParams,
}

#[pymethods]
impl PyQueryParams {
    #[new]
    fn new(raw_query: Vec<u8>) -> Self {
        Self {
            inner: NativeQueryParams::parse(&raw_query),
        }
    }

    fn get(&self, key: &str) -> Option<String> {
        self.inner.get(key).map(str::to_owned)
    }

    fn get_list(&self, key: &str) -> Vec<String> {
        self.inner
            .get_list(key)
            .into_iter()
            .map(str::to_owned)
            .collect()
    }

    fn getlist(&self, key: &str) -> Vec<String> {
        self.get_list(key)
    }

    fn multi_items(&self) -> Vec<(String, String)> {
        self.inner.multi_items().to_vec()
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.inner.get(key).is_some()
    }

    fn __getitem__(&self, key: &str) -> PyResult<String> {
        self.get(key)
            .ok_or_else(|| PyKeyError::new_err(key.to_owned()))
    }
}

#[pyclass(name = "Cookies")]
struct PyCookies {
    inner: NativeCookies,
}

#[pymethods]
impl PyCookies {
    #[new]
    fn new(header: Option<String>) -> Self {
        Self {
            inner: header
                .as_deref()
                .map(parse_cookie_header)
                .unwrap_or_default(),
        }
    }

    #[staticmethod]
    fn from_header(header: &str) -> Self {
        Self {
            inner: parse_cookie_header(header),
        }
    }

    #[staticmethod]
    fn from_header_bytes(header: Vec<u8>) -> Self {
        Self {
            inner: NativeCookies::from_header_bytes(&header),
        }
    }

    #[staticmethod]
    fn from_headers(headers: &PyRequestHeaders) -> Self {
        Self {
            inner: NativeCookies::from_headers(&headers.inner),
        }
    }

    fn get(&self, key: &str) -> Option<String> {
        self.inner.get(key).map(str::to_owned)
    }

    fn items(&self) -> Vec<(String, String)> {
        self.inner.items().to_vec()
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __contains__(&self, key: &str) -> bool {
        self.inner.get(key).is_some()
    }

    fn __getitem__(&self, key: &str) -> PyResult<String> {
        self.get(key)
            .ok_or_else(|| PyKeyError::new_err(key.to_owned()))
    }
}

#[pyclass(name = "RequestBodyAccumulator")]
struct PyRequestBodyAccumulator {
    inner: NativeRequestBodyAccumulator,
}

#[pymethods]
impl PyRequestBodyAccumulator {
    #[new]
    fn new() -> Self {
        Self {
            inner: NativeRequestBodyAccumulator::default(),
        }
    }

    fn begin_body_collection(&mut self) -> PyResult<()> {
        self.inner
            .begin_body_collection()
            .map_err(request_body_error)
    }

    fn accept_asgi_message(
        &mut self,
        message_type: &str,
        body: Vec<u8>,
        more_body: bool,
    ) -> PyResult<(String, usize, bool)> {
        let progress = self
            .inner
            .accept_asgi_message(message_type, &body, more_body)
            .map_err(request_body_error)?;
        match progress {
            BodyProgress::RequestChunk {
                chunk_length,
                complete,
            } => Ok((String::from("request_chunk"), chunk_length, complete)),
            BodyProgress::Ignored => Ok((String::from("ignored"), 0, false)),
        }
    }

    fn is_complete(&self) -> bool {
        self.inner.is_complete()
    }

    fn is_disconnected(&self) -> bool {
        self.inner.is_disconnected()
    }

    fn is_consumed(&self) -> bool {
        self.inner.is_consumed()
    }

    fn stream_is_consumed(&self) -> bool {
        self.inner.stream_is_consumed()
    }

    fn cache_body(&mut self) -> PyResult<Vec<u8>> {
        self.inner
            .cache_body()
            .map(<[u8]>::to_vec)
            .map_err(request_body_error)
    }

    fn cached_body(&self) -> Option<Vec<u8>> {
        self.inner.cached_body().map(<[u8]>::to_vec)
    }

    fn check_stream_start(&self) -> PyResult<()> {
        self.inner.check_stream_start().map_err(request_body_error)
    }
}

#[pyclass(name = "Response")]
struct PyResponse {
    inner: Response,
}

#[pymethods]
impl PyResponse {
    #[new]
    #[pyo3(signature = (content=None, status_code=200, headers=None, media_type=None))]
    fn new(
        py: Python<'_>,
        content: Option<Bound<'_, PyAny>>,
        status_code: u16,
        headers: Option<Py<PyAny>>,
        media_type: Option<String>,
    ) -> PyResult<Self> {
        let body = render_content(content.as_ref())?;
        let inner = Response::from_content(
            status_code,
            body,
            media_type.as_deref(),
            runtime_calls::header_pairs(py, headers)?,
        )
        .map_err(response_error)?;
        Ok(Self { inner })
    }

    /// Creates a Starlette-compatible redirect response from a URL string.
    #[staticmethod]
    #[pyo3(signature = (url, status_code=307, headers=None))]
    fn redirect(
        py: Python<'_>,
        url: String,
        status_code: u16,
        headers: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let inner = Response::redirect(
            &url,
            status_code,
            &runtime_calls::header_pairs(py, headers)?,
        )
        .map_err(response_error)?;
        Ok(Self { inner })
    }

    #[staticmethod]
    #[pyo3(signature = (content, status_code=200, headers=None, media_type=None))]
    fn json(
        py: Python<'_>,
        content: Vec<u8>,
        status_code: u16,
        headers: Option<Py<PyAny>>,
        media_type: Option<String>,
    ) -> PyResult<Self> {
        let inner = Response::from_content(
            status_code,
            content,
            Some(media_type.as_deref().unwrap_or("application/json")),
            runtime_calls::header_pairs(py, headers)?,
        )
        .map_err(response_error)?;
        Ok(Self { inner })
    }

    #[staticmethod]
    fn render_json(py: Python<'_>, content: Py<PyAny>) -> PyResult<Vec<u8>> {
        let options = PyDict::new(py);
        options.set_item("ensure_ascii", false)?;
        options.set_item("allow_nan", false)?;
        options.set_item("separators", PyTuple::new(py, [",", ":"])?)?;
        py.import("json")?
            .getattr("dumps")?
            .call((content,), Some(&options))?
            .call_method1("encode", ("utf-8",))?
            .extract::<Vec<u8>>()
    }

    fn asgi_call(
        &self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        background: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        runtime_calls::response_call(py, &self.inner, scope, receive, send, background)
    }

    fn set_cookie(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.set_cookie(key, value).map_err(response_error)
    }

    fn asgi_messages<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let messages = PyList::empty(py);
        for event in self.inner.asgi_events() {
            let message = PyDict::new(py);
            match event {
                ResponseEvent::Start {
                    status_code,
                    headers,
                } => {
                    message.set_item("type", "http.response.start")?;
                    message.set_item("status", status_code)?;
                    let python_headers = PyList::empty(py);
                    for (name, value) in headers {
                        let pair =
                            PyTuple::new(py, [PyBytes::new(py, &name), PyBytes::new(py, &value)])?;
                        python_headers.append(pair)?;
                    }
                    message.set_item("headers", python_headers)?;
                }
                ResponseEvent::Body { body } => {
                    message.set_item("type", "http.response.body")?;
                    message.set_item("body", PyBytes::new(py, &body))?;
                }
            }
            messages.append(message)?;
        }
        Ok(messages)
    }
}

#[pyclass(name = "LifespanState")]
struct PyLifespanState {
    inner: LifespanState,
}

#[pymethods]
impl PyLifespanState {
    #[new]
    fn new() -> Self {
        Self {
            inner: LifespanState::new(),
        }
    }

    fn startup_received(&mut self, message_type: &str) -> PyResult<&'static str> {
        self.inner
            .startup_received(message_type)
            .map(action_name)
            .map_err(lifespan_error)
    }

    fn context_entered(&mut self) -> PyResult<&'static str> {
        self.inner
            .context_entered()
            .map(action_name)
            .map_err(lifespan_error)
    }

    fn shutdown_received(&mut self, message_type: &str) -> PyResult<&'static str> {
        self.inner
            .shutdown_received(message_type)
            .map(action_name)
            .map_err(lifespan_error)
    }

    fn context_exited(&mut self) -> PyResult<&'static str> {
        self.inner
            .context_exited()
            .map(action_name)
            .map_err(lifespan_error)
    }

    fn phase(&self) -> String {
        format!("{:?}", self.inner.phase())
    }
}

#[pyclass(name = "GzipConfig")]
struct PyGzipConfig {
    inner: NativeGzipConfig,
}

#[pymethods]
impl PyGzipConfig {
    #[new]
    #[pyo3(signature = (minimum_size=500, compresslevel=9, thread_minimum_size=131072, exclude_content_types=None))]
    #[allow(non_snake_case)]
    fn new(
        minimum_size: i64,
        compresslevel: i32,
        thread_minimum_size: i64,
        exclude_content_types: Option<Vec<String>>,
    ) -> Self {
        let exclude_content_types = exclude_content_types.unwrap_or_else(|| {
            DEFAULT_EXCLUDED_CONTENT_TYPES
                .iter()
                .map(|content_type| (*content_type).to_owned())
                .collect()
        });
        Self {
            inner: NativeGzipConfig::new(
                minimum_size,
                compresslevel,
                thread_minimum_size,
                exclude_content_types,
            ),
        }
    }

    fn responder(&self, request_headers: Vec<GzipHeader>) -> PyGzipResponder {
        PyGzipResponder {
            inner: self.inner.responder(&request_headers),
        }
    }
}

#[pyclass(name = "GzipResponder")]
struct PyGzipResponder {
    inner: NativeGzipResponder,
}

#[pymethods]
impl PyGzipResponder {
    #[new]
    fn new(config: PyRef<'_, PyGzipConfig>, request_headers: Vec<GzipHeader>) -> Self {
        Self {
            inner: config.inner.responder(&request_headers),
        }
    }

    fn response_start(&mut self, status: u16, headers: Vec<GzipHeader>) {
        self.inner.response_start(status, headers);
    }

    fn should_offload(&self, body_len: usize, more_body: bool) -> bool {
        self.inner.should_offload(body_len, more_body)
    }

    fn response_body(
        &mut self,
        py: Python<'_>,
        body: &[u8],
        more_body: bool,
    ) -> PyResult<PyGzipBodyOutput> {
        let output = py
            .detach(|| self.inner.response_body(body, more_body))
            .map_err(|error| gzip_compression_error(py, error))?;
        Ok(gzip_body_output(output))
    }

    fn pathsend(&mut self) -> Option<PyGzipResponseStart> {
        self.inner
            .pathsend()
            .map(|start| (start.status, start.headers))
    }
}

#[pyfunction]
fn lifespan_message<'py>(py: Python<'py>, action: &str) -> PyResult<Bound<'py, PyDict>> {
    let message_type = match action {
        "startup_complete" => "lifespan.startup.complete",
        "shutdown_complete" => "lifespan.shutdown.complete",
        _ => {
            return Err(PyValueError::new_err(
                "action does not produce an ASGI message",
            ));
        }
    };
    let message = PyDict::new(py);
    message.set_item("type", message_type)?;
    Ok(message)
}

#[pyfunction]
fn scope_action(scope_type: &str) -> &'static str {
    match classify_scope(scope_type) {
        AsgiScopeKind::Http => "http",
        AsgiScopeKind::WebSocket => "websocket",
        AsgiScopeKind::Lifespan => "lifespan",
        AsgiScopeKind::Other => "other",
    }
}

#[pyfunction(name = "_connection_url")]
fn connection_url(
    py: Python<'_>,
    scheme: Option<String>,
    path: &str,
    query_string: &Bound<'_, PyBytes>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    server: Option<(String, u16)>,
) -> PyResult<String> {
    let query_bytes = query_string.as_bytes();
    let server = server.as_ref().map(|(host, port)| (host.as_str(), *port));
    match native_connection_url(scheme.as_deref(), path, query_bytes, &headers, server) {
        Ok(url) => Ok(url),
        Err(ConnectionUrlError::UnsupportedScheme(scheme)) => Err(PyKeyError::new_err(scheme)),
        Err(ConnectionUrlError::InvalidQueryUtf8(_)) => {
            match PyBytes::new(py, query_bytes).call_method0("decode") {
                Err(error) => Err(error),
                Ok(_) => Err(PyValueError::new_err("query string is not valid UTF-8")),
            }
        }
    }
}

#[pyfunction(name = "_http_exception_response")]
fn http_exception_response(
    status_code: u16,
    detail: &str,
    headers: Vec<(String, String)>,
) -> PyResult<PyResponse> {
    let inner = Response::http_exception(status_code, detail, &headers).map_err(response_error)?;
    Ok(PyResponse { inner })
}

#[pyfunction(name = "_server_error_response")]
fn server_error_response() -> PyResponse {
    PyResponse {
        inner: Response::server_error(),
    }
}

#[pyfunction(name = "_debug_traceback_text_response")]
fn debug_traceback_text_response(formatted_traceback: &str) -> PyResponse {
    PyResponse {
        inner: Response::debug_traceback_text(formatted_traceback),
    }
}

#[pyfunction(name = "_debug_traceback_html_response")]
fn debug_traceback_html_response(
    exception_type: &str,
    exception_message: &str,
    frames: Vec<PyDebugTracebackFrame>,
) -> PyResponse {
    let frames = frames
        .into_iter()
        .map(
            |(filename, line, function, source_lines, center_index)| DebugTracebackFrame {
                filename,
                line,
                function,
                source_lines,
                center_index,
            },
        )
        .collect::<Vec<_>>();
    PyResponse {
        inner: Response::debug_traceback_html(exception_type, exception_message, &frames),
    }
}

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyRouteTable>()?;
    module.add_class::<PyExceptionHandlerTable>()?;
    module.add_class::<PyServerErrorPolicy>()?;
    module.add_class::<PyServerErrorState>()?;
    module.add_class::<PyWebSocketStateMachine>()?;
    module.add_class::<PyRequestHeaders>()?;
    module.add_class::<PyQueryParams>()?;
    module.add_class::<PyCookies>()?;
    module.add_class::<PyRequestBodyAccumulator>()?;
    module.add_class::<PyResponse>()?;
    runtime_calls::register(module)?;
    background::register(module)?;
    module.add_class::<PyLifespanState>()?;
    module.add_class::<PyGzipConfig>()?;
    module.add_class::<PyGzipResponder>()?;
    module.add_function(wrap_pyfunction!(lifespan_message, module)?)?;
    module.add_function(wrap_pyfunction!(scope_action, module)?)?;
    module.add_function(wrap_pyfunction!(connection_url, module)?)?;
    module.add_function(wrap_pyfunction!(http_exception_response, module)?)?;
    module.add_function(wrap_pyfunction!(server_error_response, module)?)?;
    module.add_function(wrap_pyfunction!(debug_traceback_text_response, module)?)?;
    module.add_function(wrap_pyfunction!(debug_traceback_html_response, module)?)?;
    Ok(())
}

fn render_content(content: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<u8>> {
    let Some(content) = content else {
        return Ok(Vec::new());
    };
    if let Ok(text) = content.extract::<String>() {
        return Ok(text.into_bytes());
    }
    content
        .extract::<Vec<u8>>()
        .map_err(|_| PyTypeError::new_err("response content must be str, bytes, or None"))
}

fn response_error(error: ResponseError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

fn server_error_plan_parts(plan: ServerErrorPlan) -> (&'static str, Option<usize>) {
    plan.as_parts()
}

fn websocket_state_code(state: WebSocketState) -> u8 {
    match state {
        WebSocketState::Connecting => 0,
        WebSocketState::Connected => 1,
        WebSocketState::Disconnected => 2,
        WebSocketState::Response => 3,
    }
}

fn gzip_body_output(output: GzipBodyOutput) -> PyGzipBodyOutput {
    (
        output
            .response_start
            .map(|start| (start.status, start.headers)),
        output.body,
    )
}

fn gzip_compression_error(py: Python<'_>, error: GzipCompressionError) -> PyErr {
    let message = match error {
        GzipCompressionError::InvalidCompressionLevel(_) => {
            String::from("Invalid initialization option")
        }
        GzipCompressionError::Compression(error) => format!("{error:?}"),
        GzipCompressionError::Io(error) => error.to_string(),
        GzipCompressionError::Finished => {
            return PyRuntimeError::new_err("gzip stream has already finished");
        }
    };

    if let Ok(error_instance) = py
        .import("zlib")
        .and_then(|zlib| zlib.getattr("error"))
        .and_then(|error_type| error_type.call1((message.as_str(),)))
    {
        return PyErr::from_value(error_instance);
    }
    PyRuntimeError::new_err(message)
}

fn request_body_error(error: RequestBodyError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn lifespan_error(error: LifespanError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

fn action_name(action: LifespanAction) -> &'static str {
    match action {
        LifespanAction::EnterContext => "enter_context",
        LifespanAction::SendStartupComplete => "startup_complete",
        LifespanAction::ExitContext => "exit_context",
        LifespanAction::SendShutdownComplete => "shutdown_complete",
    }
}
