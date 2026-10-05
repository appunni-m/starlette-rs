//! Python bindings for the Rust-owned Starlette compatibility runtime.
//!
//! The public `starlette.*` modules are thin call-through façades. This
//! extension translates Python protocol objects at the boundary and delegates
//! compatibility behavior to Rust. Python owns user callables and the active
//! event loop; Rust continuations invoke and await callbacks through that loop
//! without creating a second executor or event loop.

mod application_runtime;
mod authentication_runtime;
mod awaitable;
mod background;
mod base_http_runtime;
mod body_limit_runtime;
mod config_runtime;
mod cookie_runtime;
mod cors_runtime;
mod datastructure_runtime;
mod endpoint_runtime;
mod exception_values;
mod file_object_runtime;
mod file_response_runtime;
mod gzip_runtime;
mod headers_runtime;
mod host_middleware_runtime;
mod middleware_config_runtime;
mod path_convertors_runtime;
mod request_runtime;
mod response_construction_runtime;
mod response_headers_runtime;
mod router_runtime;
mod runtime_calls;
mod schemas_runtime;
mod server_error_runtime;
mod sessions_runtime;
mod staticfiles_runtime;
mod status_runtime;
mod streaming_object_runtime;
mod templating_runtime;
mod testclient_runtime;
mod websocket_calls;
mod wsgi_runtime;

use pyo3::exceptions::{PyAssertionError, PyKeyError};
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyString, PyTuple};
use starlette_rs::{
    AsgiScopeKind, BodyProgress, ConnectionUrlError, Cookies as NativeCookies,
    DEFAULT_EXCLUDED_CONTENT_TYPES, DebugTracebackFrame, DetailedRouteMatch, GzipBodyOutput,
    GzipCompressionError, GzipConfig as NativeGzipConfig, GzipHeader,
    GzipResponder as NativeGzipResponder, HttpDispatchPlan, LifespanAction, LifespanError,
    LifespanState, QueryParams as NativeQueryParams,
    RequestBodyAccumulator as NativeRequestBodyAccumulator, RequestBodyError,
    RequestHeaders as NativeRequestHeaders, Response, ResponseError, ResponseEvent, RouteTable,
    ServerErrorPlan, ServerErrorPolicy as NativeServerErrorPolicy,
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
type HttpDispatchDecision = (
    String,
    Option<usize>,
    Vec<(String, String)>,
    Vec<String>,
    Option<String>,
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

    /// Plans an HTTP match, method rejection, slash redirect, or not-found result.
    fn dispatch_plan(&self, path: &str, root_path: &str, method: &str) -> HttpDispatchDecision {
        match self.inner.dispatch_plan(path, root_path, method) {
            HttpDispatchPlan::Matched {
                route_index,
                path_params,
            } => (
                "matched".to_owned(),
                Some(route_index),
                path_params,
                Vec::new(),
                None,
            ),
            HttpDispatchPlan::MethodNotAllowed {
                route_index,
                allowed_methods,
                path_params,
            } => (
                "method_not_allowed".to_owned(),
                Some(route_index),
                path_params,
                allowed_methods,
                None,
            ),
            HttpDispatchPlan::Redirect { path } => (
                "redirect".to_owned(),
                None,
                Vec::new(),
                Vec::new(),
                Some(path),
            ),
            HttpDispatchPlan::NotFound => {
                ("not_found".to_owned(), None, Vec::new(), Vec::new(), None)
            }
        }
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
        .map(|inner| PyResponse::from_inner(py, inner).and_then(|response| Py::new(py, response)))
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

#[pyclass(name = "QueryParams", subclass)]
struct PyQueryParams {
    inner: NativeQueryParams,
}

#[pymethods]
impl PyQueryParams {
    #[new]
    #[pyo3(signature = (*args, **kwargs))]
    fn new(args: &Bound<'_, PyTuple>, kwargs: Option<&Bound<'_, PyDict>>) -> PyResult<Self> {
        if args.len() > 1 {
            return Err(PyAssertionError::new_err("Too many arguments."));
        }
        let mut items = if args.is_empty() {
            Vec::new()
        } else {
            query_params_from_python(&args.get_item(0)?)?
        };
        if let Some(kwargs) = kwargs {
            items.extend(query_params_from_mapping(kwargs)?);
        }
        Ok(Self {
            inner: NativeQueryParams::from_pairs(items),
        })
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python<'_>, key: &Bound<'_, PyAny>, default: Option<Py<PyAny>>) -> Py<PyAny> {
        query_params_key(key)
            .as_deref()
            .and_then(|query_key| self.inner.get(query_key))
            .map(|value| PyString::new(py, value).into_any().unbind())
            .or(default)
            .unwrap_or_else(|| py.None())
    }

    fn get_list(&self, key: &Bound<'_, PyAny>) -> Vec<String> {
        let Some(key) = query_params_key(key) else {
            return Vec::new();
        };
        self.inner
            .get_list(&key)
            .into_iter()
            .map(str::to_owned)
            .collect()
    }

    fn getlist(&self, key: &Bound<'_, PyAny>) -> Vec<String> {
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

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let keys = self.inner.keys();
        PyList::new(py, keys)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __contains__(&self, key: &Bound<'_, PyAny>) -> bool {
        query_params_key(key).is_some_and(|key| self.inner.get(&key).is_some())
    }

    fn __getitem__(&self, key: &Bound<'_, PyAny>) -> PyResult<String> {
        let query_key = query_params_key(key);
        query_key
            .as_deref()
            .and_then(|query_key| self.inner.get(query_key))
            .map(str::to_owned)
            .ok_or_else(|| PyKeyError::new_err(key.clone().unbind()))
    }

    fn __str__(&self) -> String {
        self.inner.query_string()
    }

    fn __repr__(slf: PyRef<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let query = slf.inner.query_string();
        let instance = slf.into_pyobject(py)?;
        let class_name = instance.get_type().name()?.to_string();
        Ok(format!("{class_name}('{query}')"))
    }

    fn __eq__(&self, other: &Bound<'_, PyAny>) -> bool {
        other
            .extract::<PyRef<'_, PyQueryParams>>()
            .is_ok_and(|other| self.inner == other.inner)
    }
}

fn query_params_key(value: &Bound<'_, PyAny>) -> Option<String> {
    value
        .is_instance_of::<PyString>()
        .then(|| value.extract::<String>().ok())
        .flatten()
}

fn query_params_from_python(value: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    if !value.is_truthy()? {
        return Ok(Vec::new());
    }
    if value.is_instance_of::<PyString>() {
        return Ok(NativeQueryParams::parse_str(&value.extract::<String>()?)
            .multi_items()
            .to_vec());
    }
    if let Ok(bytes) = value.cast::<PyBytes>() {
        return Ok(NativeQueryParams::parse(bytes.as_bytes())
            .multi_items()
            .to_vec());
    }
    if value.hasattr("multi_items")? {
        return query_params_from_iterable(&value.call_method0("multi_items")?);
    }
    if value.hasattr("items")? {
        return query_params_from_iterable(&value.call_method0("items")?);
    }
    query_params_from_iterable(value)
}

fn query_params_from_mapping(mapping: &Bound<'_, PyDict>) -> PyResult<Vec<(String, String)>> {
    mapping
        .iter()
        .map(|(key, value)| Ok((key.str()?.extract()?, value.str()?.extract()?)))
        .collect()
}

fn query_params_from_iterable(values: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    values
        .try_iter()?
        .map(|pair| {
            let pair = pair?;
            let pair_values = pair.try_iter()?.collect::<PyResult<Vec<_>>>()?;
            if pair_values.len() != 2 {
                let message = if pair_values.len() < 2 {
                    format!(
                        "not enough values to unpack (expected 2, got {})",
                        pair_values.len()
                    )
                } else {
                    "too many values to unpack (expected 2)".to_owned()
                };
                return Err(PyValueError::new_err(message));
            }
            let key = pair_values[0].str()?.extract()?;
            let value = pair_values[1].str()?.extract()?;
            Ok((key, value))
        })
        .collect()
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
    raw_headers: Option<Py<PyAny>>,
    headers_view: Option<Py<PyAny>>,
}

impl PyResponse {
    fn from_inner(py: Python<'_>, inner: Response) -> PyResult<Self> {
        let raw_headers = response_headers_runtime::raw_pairs(py, inner.headers())?;
        Ok(Self {
            inner,
            raw_headers: Some(raw_headers),
            headers_view: None,
        })
    }
}

#[pymethods]
impl PyResponse {
    /// Creates storage before a user render callback can access headers.
    #[staticmethod]
    fn uninitialized() -> Self {
        Self {
            inner: Response::from_parts(200, Vec::new(), []),
            raw_headers: None,
            headers_view: None,
        }
    }

    #[staticmethod]
    fn set_media_type(
        response: &Bound<'_, PyAny>,
        media_type: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        if let Some(media_type) = media_type {
            response.setattr("media_type", media_type)?;
        }
        Ok(())
    }

    #[staticmethod]
    fn initialize_headers(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        headers: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        response_construction_runtime::initialize_headers(py, response, headers)
    }

    #[staticmethod]
    fn initialize_stream(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        response_construction_runtime::initialize_stream(py, response, arguments)
    }

    #[staticmethod]
    fn initialize_file(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        response_construction_runtime::initialize_file(py, response, arguments)
    }

    #[staticmethod]
    fn set_stat_headers(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        stat: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        response_construction_runtime::set_stat_headers(py, response, stat)
    }

    #[staticmethod]
    fn redirect_location(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        url: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        response_construction_runtime::redirect_location(py, response, url)
    }

    #[staticmethod]
    fn wrap_denial_send(py: Python<'_>, send: Py<PyAny>) -> PyResult<Py<PyAny>> {
        streaming_object_runtime::wrap_denial_send(py, send)
    }

    #[staticmethod]
    fn prepare(py: Python<'_>, response: &Bound<'_, PyAny>) -> PyResult<()> {
        let native = Py::new(py, Self::uninitialized())?;
        py.get_type::<PyAny>()
            .call_method1("__setattr__", (response, "_inner", native))?;
        Ok(())
    }

    #[staticmethod]
    fn headers_for(py: Python<'_>, response: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let missing = match response.getattr("_headers") {
            Ok(_) => false,
            Err(error) if error.is_instance_of::<pyo3::exceptions::PyAttributeError>(py) => true,
            Err(error) => return Err(error),
        };
        if missing {
            let headers = response_headers_runtime::view(py, &response.getattr("raw_headers")?)?;
            response.setattr("_headers", headers)?;
        }
        response.getattr("_headers").map(Bound::unbind)
    }

    #[staticmethod]
    fn asgi_call_for(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        // Native storage is representation glue, not a user attribute access.
        // Release its borrow before evaluating scope or invoking callbacks.
        let native = py
            .get_type::<PyAny>()
            .call_method1("__getattribute__", (response, "_inner"))?;
        let call = native.cast::<Self>()?.try_borrow()?.inner.call_state(true);
        runtime_calls::response_object_call(
            py,
            call,
            response.clone().unbind(),
            scope,
            receive,
            send,
        )
    }

    #[staticmethod]
    fn cookie_state(args: &Bound<'_, PyTuple>) -> cookie_runtime::PyCookieCall {
        cookie_runtime::PyCookieCall::new(args)
    }

    #[staticmethod]
    fn cookie_call(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        operation: &str,
        args: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        if operation == "delete_cookie" {
            let kwargs = PyDict::new(py);
            kwargs.set_item("max_age", 0)?;
            kwargs.set_item("expires", 0)?;
            for (index, name) in ["path", "domain", "secure", "httponly", "samesite"]
                .into_iter()
                .enumerate()
            {
                kwargs.set_item(name, args.get_item(index + 1)?)?;
            }
            response
                .getattr("set_cookie")?
                .call((args.get_item(0)?,), Some(&kwargs))?;
            return Ok(());
        }
        if operation != "set_cookie" {
            return Err(PyValueError::new_err(
                "unsupported response cookie operation",
            ));
        }
        let header = cookie_runtime::header_from_arguments(py, args, None)?;
        // Source selects the current append callable before encoding the final
        // header. Neither user conversions nor this selection hold a native borrow.
        let append = response.getattr("raw_headers")?.getattr("append")?;
        let encoded = header.text.call_method1("encode", ("latin-1",))?;
        append.call1((PyTuple::new(
            py,
            [PyBytes::new(py, b"set-cookie").into_any(), encoded],
        )?,))?;
        Ok(())
    }

    fn __traverse__(
        &self,
        visit: pyo3::class::gc::PyVisit<'_>,
    ) -> Result<(), pyo3::class::gc::PyTraverseError> {
        visit.call(&self.raw_headers)?;
        visit.call(&self.headers_view)
    }

    fn __clear__(&mut self) {
        self.raw_headers = None;
        self.headers_view = None;
    }

    #[new]
    #[pyo3(signature = (content=None, status_code=200, headers=None, media_type=None, charset="utf-8"))]
    fn new(
        py: Python<'_>,
        content: Option<Bound<'_, PyAny>>,
        status_code: u16,
        headers: Option<Py<PyAny>>,
        media_type: Option<String>,
        charset: &str,
    ) -> PyResult<Self> {
        let body = response_body_bytes(py, content.as_ref())?;
        let inner = Response::from_content_with_charset(
            status_code,
            body,
            media_type.as_deref(),
            runtime_calls::header_pairs(py, headers)?,
            charset,
        )
        .map_err(response_error)?;
        Self::from_inner(py, inner)
    }

    /// Applies Starlette's default Response.render behavior to a Python value.
    ///
    /// The public Python facade calls this only when a subclass has not
    /// provided its own `render` override. Python bytes and memoryview values
    /// are returned unchanged; other values use their Python `encode` method.
    #[staticmethod]
    fn render_content(
        py: Python<'_>,
        content: Py<PyAny>,
        response: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let content = content.bind(py);
        if content.is_none() {
            return Ok(PyBytes::new(py, &[]).into_any().unbind());
        }
        let memoryview_type = py.import("builtins")?.getattr("memoryview")?;
        if content.is_instance_of::<PyBytes>() || content.is_instance(&memoryview_type)? {
            return Ok(content.clone().unbind());
        }
        content
            .call_method1("encode", (response.getattr("charset")?,))
            .map(Bound::unbind)
    }

    /// Selects the explicit media type or the response subclass default.
    #[staticmethod]
    fn media_type_or(py: Python<'_>, media_type: Option<String>, fallback: Py<PyAny>) -> Py<PyAny> {
        media_type.map_or(fallback, |media_type| {
            PyString::new(py, &media_type).into_any().unbind()
        })
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
        let mut response = Self::from_inner(py, inner)?;
        let _ = response.headers(py)?;
        Ok(response)
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
        Self::from_inner(py, inner)
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
        response: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        // Resolve background presence after the body send, as the source does.
        // The Rust protocol always reaches that decision; no callback is invoked
        // when the live public background attribute is None.
        runtime_calls::response_object_call(
            py,
            self.inner.call_state(true),
            response,
            scope,
            receive,
            send,
        )
    }

    #[getter]
    fn body(&self) -> Vec<u8> {
        self.inner.body().to_vec()
    }

    #[getter]
    fn status_code(&self) -> u16 {
        self.inner.status_code()
    }

    #[getter]
    fn headers(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(headers) = self.headers_view.as_ref() {
            return Ok(headers.clone_ref(py));
        }
        let headers = response_headers_runtime::view(
            py,
            self.raw_headers
                .as_ref()
                .ok_or_else(|| pyo3::exceptions::PyAttributeError::new_err("raw_headers"))?
                .bind(py),
        )?;
        self.headers_view = Some(headers.clone_ref(py));
        Ok(headers)
    }

    #[getter]
    fn raw_headers(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.raw_headers
            .as_ref()
            .map(|raw| raw.clone_ref(py))
            .ok_or_else(|| pyo3::exceptions::PyAttributeError::new_err("raw_headers"))
    }

    #[setter]
    fn set_raw_headers(&mut self, headers: Py<PyAny>) {
        self.raw_headers = Some(headers);
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
        response_headers_runtime::items(self.inner.headers())
    }

    fn _header_raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        response_headers_runtime::raw_pairs(py, self.inner.headers())
    }

    fn _header_replace_raw(&mut self, raw: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner
            .replace_headers_raw(response_headers_runtime::parse_raw_pairs(raw)?);
        Ok(())
    }

    fn _header_refresh_raw(&self, py: Python<'_>) -> PyResult<()> {
        response_headers_runtime::refresh_raw_pairs(
            py,
            self.raw_headers
                .as_ref()
                .ok_or_else(|| pyo3::exceptions::PyAttributeError::new_err("raw_headers"))?
                .bind(py),
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
    // LINT EXCEPTION: Keep Starlette's public `compresslevel` keyword spelling in the PyO3 constructor.
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

    fn gzip_responder(&self) -> PyGzipResponder {
        PyGzipResponder {
            inner: self.inner.gzip_responder(),
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
    py: Python<'_>,
    status_code: u16,
    detail: &str,
    headers: Vec<(String, String)>,
) -> PyResult<PyResponse> {
    let inner = Response::http_exception(status_code, detail, &headers).map_err(response_error)?;
    PyResponse::from_inner(py, inner)
}

#[pyfunction(name = "_server_error_response")]
fn server_error_response(py: Python<'_>) -> PyResult<PyResponse> {
    PyResponse::from_inner(py, Response::server_error())
}

#[pyfunction(name = "_debug_traceback_text_response")]
fn debug_traceback_text_response(
    py: Python<'_>,
    formatted_traceback: &str,
) -> PyResult<PyResponse> {
    PyResponse::from_inner(py, Response::debug_traceback_text(formatted_traceback))
}

#[pyfunction(name = "_debug_traceback_html_response")]
fn debug_traceback_html_response(
    py: Python<'_>,
    exception_type: &str,
    exception_message: &str,
    frames: Vec<PyDebugTracebackFrame>,
) -> PyResult<PyResponse> {
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
    PyResponse::from_inner(
        py,
        Response::debug_traceback_html(exception_type, exception_message, &frames),
    )
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
    headers_runtime::register(module)?;
    runtime_calls::register(module)?;
    base_http_runtime::register(module)?;
    background::register(module)?;
    authentication_runtime::register(module)?;
    datastructure_runtime::register(module)?;
    endpoint_runtime::register(module)?;
    body_limit_runtime::register(module)?;
    cors_runtime::register(module)?;
    application_runtime::register(module)?;
    exception_values::register(module)?;
    config_runtime::register(module)?;
    schemas_runtime::register(module)?;
    middleware_config_runtime::register(module)?;
    host_middleware_runtime::register(module)?;
    path_convertors_runtime::register(module)?;
    request_runtime::register(module)?;
    file_response_runtime::register(module)?;
    staticfiles_runtime::register(module)?;
    router_runtime::register(module)?;
    gzip_runtime::register(module)?;
    server_error_runtime::register(module)?;
    sessions_runtime::register(module)?;
    status_runtime::register(module)?;
    testclient_runtime::register(module)?;
    templating_runtime::register(module)?;
    websocket_calls::register(module)?;
    wsgi_runtime::register(module)?;
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

fn response_body_bytes(py: Python<'_>, content: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<u8>> {
    let Some(content) = content else {
        return Ok(Vec::new());
    };
    if content.is_none() {
        return Ok(Vec::new());
    }
    let memoryview_type = py.import("builtins")?.getattr("memoryview")?;
    if content.is_instance(&memoryview_type)? {
        return content.call_method0("tobytes")?.extract::<Vec<u8>>();
    }
    if let Ok(text) = content.extract::<String>() {
        return Ok(text.into_bytes());
    }
    content
        .extract::<Vec<u8>>()
        .map_err(|_| PyTypeError::new_err("response content must be str, bytes, or None"))
}

fn response_error(error: ResponseError) -> PyErr {
    cookie_runtime::response_error(error)
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
