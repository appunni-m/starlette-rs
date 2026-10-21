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
mod file_range_runtime;
mod file_response_runtime;
mod file_stream_runtime;
mod gzip_runtime;
mod headers_runtime;
mod host_middleware_runtime;
mod middleware_config_runtime;
mod optional_runtime;
mod path_convertors_runtime;
mod request_runtime;
mod response_construction_runtime;
mod response_headers_runtime;
mod router_runtime;
mod runtime_calls;
mod schemas_runtime;
mod scope_mapping;
mod server_error_runtime;
mod sessions_runtime;
mod staticfiles_runtime;
mod status_runtime;
mod streaming_object_runtime;
mod templating_runtime;
mod testclient_runtime;
mod websocket_calls;
mod wsgi_runtime;

use pyo3::exceptions::{PyAssertionError, PyKeyError, PyOverflowError};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyString, PyTuple};
use starlette_rs::{
    AsgiScopeKind, ConnectionUrlError, Cookies as NativeCookies, DEFAULT_EXCLUDED_CONTENT_TYPES,
    DebugTracebackFrame, DetailedRouteMatch, GzipBodyOutput, GzipCompressionError,
    GzipConfig as NativeGzipConfig, GzipHeader, GzipResponder as NativeGzipResponder,
    LifespanAction, LifespanError, LifespanState, QueryParams as NativeQueryParams,
    RequestHeaders as NativeRequestHeaders, Response, ResponseError, RouteTable, ServerErrorPlan,
    ServerErrorPolicy as NativeServerErrorPolicy, ServerErrorState as NativeServerErrorState,
    WebSocketState, WebSocketStateMachine, classify_scope,
    connection_url_with_port_text as native_connection_url_with_port_text, parse_cookie_header,
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
    compiled_path: Option<String>,
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
            compiled_path: None,
        }
    }

    fn add_route(&mut self, path: String, methods: Vec<String>) -> PyResult<usize> {
        self.inner
            .add_route(path, methods)
            .map_err(|error| PyValueError::new_err(error.to_string()))
    }

    fn _set_compiled_path(&mut self, path: String) {
        self.compiled_path = Some(path);
    }

    fn _compiled_path(&self) -> Option<String> {
        self.compiled_path.clone()
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

#[pyclass(name = "_QueryParamsStore")]
struct PyQueryParams {
    inner: NativeQueryParams,
    lookup: Py<PyDict>,
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
        let py = args.py();
        let inner = NativeQueryParams::from_pairs(items);
        // QueryParams lookup accepts arbitrary Python keys. Keep a Rust-owned
        // snapshot of Starlette's exact-str mapping so Python key hashing and
        // equality (including overridden methods on str subclasses) run at
        // this boundary instead of being erased by String extraction.
        let lookup = PyDict::new(py);
        for (key, value) in inner.items() {
            lookup.set_item(PyString::new(py, key), PyString::new(py, value))?;
        }
        Ok(Self {
            inner,
            lookup: lookup.unbind(),
        })
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let value = self.lookup.bind(py).get_item(key);
        // QueryParams inherits Mapping.get, which catches KeyError from
        // `self[key]`, including errors raised by Python key hashing/equality.
        let value = match value {
            Ok(Some(value)) => Some(value.unbind()),
            Ok(None) => None,
            Err(error) if error.is_instance_of::<PyKeyError>(py) => None,
            Err(error) => return Err(error),
        };
        Ok(value.or(default).unwrap_or_else(|| py.None()))
    }

    fn get_list(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
        let mut values = Vec::new();
        for (item_key, value) in self.inner.multi_items() {
            if PyString::new(py, item_key).as_any().eq(key)? {
                values.push(value.clone());
            }
        }
        Ok(values)
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
        self.get_list(py, key)
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.lookup.bind(py).call_method0("keys").map(Bound::unbind)
    }

    fn values(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.lookup
            .bind(py)
            .call_method0("values")
            .map(Bound::unbind)
    }

    fn items_view(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.lookup
            .bind(py)
            .call_method0("items")
            .map(Bound::unbind)
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

    fn contains(&self, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.lookup.bind(key.py()).contains(key)
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __bool__(&self) -> bool {
        !self.inner.is_empty()
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let keys = self.inner.keys();
        PyList::new(py, keys)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __contains__(&self, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.lookup.bind(key.py()).contains(key)
    }

    fn __getitem__(&self, key: &Bound<'_, PyAny>) -> PyResult<String> {
        self.lookup
            .bind(key.py())
            .get_item(key)?
            .map(|value| value.extract::<String>())
            .transpose()?
            .ok_or_else(|| PyKeyError::new_err(key.clone().unbind()))
    }

    fn __str__(&self) -> String {
        self.inner.query_string()
    }

    fn repr(
        &self,
        _py: Python<'_>,
        class_name: &str,
        owner: &Bound<'_, PyAny>,
    ) -> PyResult<String> {
        let query = owner.str()?.repr()?;
        Ok(format!("{class_name}({})", query.to_str()?))
    }

    fn equals(&self, class_type: &Bound<'_, PyAny>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        if !other.is_instance(class_type)? {
            return Ok(false);
        }
        let other = other.getattr("_inner")?.extract::<PyRef<'_, Self>>()?;
        Ok(self.inner == other.inner)
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

fn query_params_from_python(value: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    // QueryParams dispatches strings and bytes before ImmutableMultiDict's
    // generic truthiness check. CPython 3.10's parse_qsl normalizes str
    // subclasses before checking emptiness, while 3.11+ checks their truth
    // value directly; preserve that stdlib boundary behavior here.
    if value.is_instance_of::<PyString>() {
        if value.py().version_info() >= (3, 11) && !value.is_truthy()? {
            return Ok(Vec::new());
        }
        return Ok(NativeQueryParams::parse_str(&value.extract::<String>()?)
            .multi_items()
            .to_vec());
    }
    if let Ok(bytes) = value.cast::<PyBytes>() {
        return Ok(NativeQueryParams::parse(bytes.as_bytes())
            .multi_items()
            .to_vec());
    }
    if !value.is_truthy()? {
        return Ok(Vec::new());
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
                } else if values.py().version_info() >= (3, 14) {
                    // CPython 3.14 added the received-item count to this
                    // tuple-unpacking ValueError; earlier supported releases
                    // retain the shorter message.
                    format!(
                        "too many values to unpack (expected 2, got {})",
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

#[pyclass(name = "Response")]
struct PyResponse {
    inner: Response,
    raw_headers: Option<Py<PyAny>>,
}

impl PyResponse {
    fn from_inner(py: Python<'_>, inner: Response) -> PyResult<Self> {
        let raw_headers = response_headers_runtime::raw_pairs(py, inner.headers())?;
        Ok(Self {
            inner,
            raw_headers: Some(raw_headers),
        })
    }
}

#[pymethods]
impl PyResponse {
    #[staticmethod]
    fn initialize_headers(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        headers: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        response_construction_runtime::initialize_headers(py, response, headers)
    }

    /// Owns the public Response constructor's ordered Python boundary calls.
    #[staticmethod]
    fn initialize(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        // The facade has no Rust storage of its own. Install it before running
        // source-ordered assignments so render and init_headers can re-enter
        // ordinary response methods without a live native borrow.
        let native = Py::new(
            py,
            Self {
                inner: Response::from_parts(200, Vec::new(), []),
                raw_headers: None,
            },
        )?;
        py.get_type::<PyAny>()
            .call_method1("__setattr__", (response, "_inner", native))?;
        response_construction_runtime::initialize_response(py, response, arguments)
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
        scope: &Bound<'_, PyAny>,
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
    #[pyo3(signature = (response, operation, args, retained=None))]
    fn cookie_call(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        operation: &str,
        args: &Bound<'_, PyTuple>,
        retained: Option<Bound<'_, PyList>>,
    ) -> PyResult<()> {
        if operation == "delete_cookie" {
            let kwargs = PyDict::new(py);
            kwargs.set_item("max_age", 0)?;
            kwargs.set_item("expires", 0)?;
            for (index, name) in ["path", "domain", "secure", "httponly", "samesite"]
                .into_iter()
                .enumerate()
            {
                let argument_index = index
                    .checked_add(1)
                    .ok_or_else(|| PyOverflowError::new_err("cookie argument index overflow"))?;
                kwargs.set_item(name, args.get_item(argument_index)?)?;
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
        let header = cookie_runtime::header_from_arguments(py, args, retained.as_ref())?;
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
        visit.call(&self.raw_headers)
    }

    fn __clear__(&mut self) {
        self.raw_headers = None;
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

    #[getter]
    fn body(&self) -> Vec<u8> {
        self.inner.body().to_vec()
    }

    #[getter]
    fn status_code(&self) -> u16 {
        self.inner.status_code()
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
    compresslevel_overflow: bool,
}

#[pymethods]
impl PyGzipConfig {
    #[new]
    #[pyo3(signature = (minimum_size=500, compresslevel=9, thread_minimum_size=131072, exclude_content_types=None, compresslevel_overflow=false))]
    // LINT EXCEPTION: Keep Starlette's public `compresslevel` keyword spelling in the PyO3 constructor.
    #[allow(non_snake_case)]
    fn new(
        minimum_size: i64,
        compresslevel: i32,
        thread_minimum_size: i64,
        exclude_content_types: Option<Vec<String>>,
        compresslevel_overflow: bool,
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
            compresslevel_overflow,
        }
    }

    fn responder(&self, request_headers: Vec<GzipHeader>) -> PyGzipResponder {
        PyGzipResponder {
            inner: self.inner.responder(&request_headers),
            compresslevel_overflow: self.compresslevel_overflow,
        }
    }

    fn gzip_responder(&self) -> PyGzipResponder {
        PyGzipResponder {
            inner: self.inner.gzip_responder(),
            compresslevel_overflow: self.compresslevel_overflow,
        }
    }
}

#[pyclass(name = "GzipResponder")]
struct PyGzipResponder {
    inner: NativeGzipResponder,
    compresslevel_overflow: bool,
}

#[pymethods]
impl PyGzipResponder {
    #[new]
    fn new(config: PyRef<'_, PyGzipConfig>, request_headers: Vec<GzipHeader>) -> Self {
        Self {
            inner: config.inner.responder(&request_headers),
            compresslevel_overflow: config.compresslevel_overflow,
        }
    }

    fn response_start(
        &mut self,
        status: &Bound<'_, PyAny>,
        headers: Vec<GzipHeader>,
    ) -> PyResult<()> {
        // Starlette's only status-dependent GZip policy is `status == 206`.
        // The middleware forwards its original ASGI message, so retain that
        // policy result here without narrowing arbitrary Python integers.
        let status = if status.eq(206)? { 206 } else { 0 };
        self.inner.response_start(status, headers);
        Ok(())
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
        let output = match py.detach(|| self.inner.response_body(body, more_body)) {
            Ok(output) => output,
            Err(GzipCompressionError::InvalidCompressionLevel(_))
                if self.compresslevel_overflow =>
            {
                return Err(PyOverflowError::new_err(
                    "Python int too large to convert to C int",
                ));
            }
            Err(error) => return Err(gzip_compression_error(py, error)),
        };
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
    server: &Bound<'_, PyAny>,
) -> PyResult<String> {
    let query_bytes = query_string.as_bytes();
    // Starlette checks the first Host header before unpacking the server tuple.
    // Probe the native Host selection with an empty path/query so malformed or
    // stateful server values are only touched when the Host header is unusable.
    let has_valid_host_header =
        native_connection_url_with_port_text(scheme.as_deref(), "", &[], &headers, None)
            .map(|url| !url.is_empty())
            .map_err(|error| connection_url_error_to_python(py, &[], error))?;
    let server = if server.is_none() || has_valid_host_header {
        None
    } else {
        let host = server.get_item(0)?.extract::<String>()?;
        let port = py
            .import("builtins")?
            .getattr("str")?
            .call1((server.get_item(1)?,))?
            .extract::<String>()?;
        Some((host, port))
    };
    // CPython 3.10 and 3.11's urllib.parse.urlunsplit adds a leading slash
    // when serializing a relative path with an empty authority for a network
    // scheme. Keep that interpreter-specific behavior in the Rust boundary;
    // `Python::version_info` reads the running interpreter version directly.
    let default_port = match scheme.as_deref().unwrap_or("http") {
        "http" | "ws" => Some("80"),
        "https" | "wss" => Some("443"),
        _ => None,
    };
    let legacy_empty_authority_relative_path = py.version_info() < (3, 12)
        && !path.is_empty()
        && !path.starts_with('/')
        && default_port.is_some_and(|default_port| {
            server
                .as_ref()
                .is_some_and(|(host, port)| host.is_empty() && port.as_str() == default_port)
        });
    let path = if legacy_empty_authority_relative_path {
        format!("/{path}")
    } else {
        path.to_owned()
    };
    let server = server
        .as_ref()
        .map(|(host, port)| (host.as_str(), port.as_str()));
    match native_connection_url_with_port_text(
        scheme.as_deref(),
        &path,
        query_bytes,
        &headers,
        server,
    ) {
        Ok(url) => Ok(url),
        Err(error) => Err(connection_url_error_to_python(py, query_bytes, error)),
    }
}

fn connection_url_error_to_python(
    py: Python<'_>,
    query_bytes: &[u8],
    error: ConnectionUrlError,
) -> PyErr {
    match error {
        ConnectionUrlError::UnsupportedScheme(scheme) => PyKeyError::new_err(scheme),
        ConnectionUrlError::InvalidQueryUtf8(_) => {
            match PyBytes::new(py, query_bytes).call_method0("decode") {
                Err(error) => error,
                Ok(_) => PyValueError::new_err("query string is not valid UTF-8"),
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
    let inner =
        Response::http_exception(status_code, Some(detail), &headers).map_err(response_error)?;
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
    optional_runtime::register(module)?;
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
