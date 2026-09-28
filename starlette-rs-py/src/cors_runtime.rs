//! Rust-owned ASGI CORS policy and response-header transformation.

use std::cell::RefCell;
use std::rc::Rc;

use pyo3::exceptions::{PyKeyError, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyList, PyModule, PySet, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

const ALL_METHODS: [&str; 7] = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"];
const SAFELISTED_HEADERS: [&str; 4] = [
    "Accept",
    "Accept-Language",
    "Content-Language",
    "Content-Type",
];

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyCORSMiddlewareRuntime>()?;
    module.add("CORS_ALL_METHODS", PyTuple::new(module.py(), ALL_METHODS)?)?;
    module.add(
        "CORS_SAFELISTED_HEADERS",
        PySet::new(module.py(), SAFELISTED_HEADERS)?,
    )?;
    Ok(())
}

type SharedCorsConfig = Rc<RefCell<CorsConfig>>;

struct CorsConfig {
    app: Py<PyAny>,
    allow_origins: Py<PyAny>,
    allow_methods: Py<PyAny>,
    allow_headers: Py<PyAny>,
    allow_all_origins: Py<PyAny>,
    allow_all_headers: Py<PyAny>,
    allow_credentials: Py<PyAny>,
    preflight_explicit_allow_origin: Py<PyAny>,
    allow_origin_regex: Py<PyAny>,
    allow_private_network: Py<PyAny>,
    simple_headers: Py<PyAny>,
    preflight_headers: Py<PyAny>,
}

/// Native Starlette 1.6.0 CORS middleware. Python callables remain on the
/// caller's event loop; Rust owns CORS decisions and ASGI header mutation.
#[pyclass(
    name = "CORSMiddleware",
    module = "starlette.middleware.cors",
    unsendable
)]
pub(crate) struct PyCORSMiddlewareRuntime {
    config: SharedCorsConfig,
    plain_text_response_type: Py<PyAny>,
}

#[pymethods]
impl PyCORSMiddlewareRuntime {
    #[new]
    #[pyo3(signature = (app, allow_origins, allow_methods, allow_headers, allow_credentials, allow_origin_regex, allow_private_network, expose_headers, max_age))]
    fn new(
        py: Python<'_>,
        app: Py<PyAny>,
        allow_origins: Py<PyAny>,
        allow_methods: Py<PyAny>,
        allow_headers: Py<PyAny>,
        allow_credentials: Py<PyAny>,
        allow_origin_regex: Option<Py<PyAny>>,
        allow_private_network: Py<PyAny>,
        expose_headers: Py<PyAny>,
        max_age: Py<PyAny>,
    ) -> PyResult<Self> {
        let cors_module = py.import("starlette.middleware.cors")?;
        let all_methods = cors_module.getattr("ALL_METHODS")?;
        let allow_methods = if allow_methods.bind(py).contains("*")? {
            all_methods.into_any().unbind()
        } else {
            allow_methods
        };
        let allow_all_origins = allow_origins.bind(py).contains("*")?;
        let allow_all_headers = allow_headers.bind(py).contains("*")?;
        let compiled_allow_origin_regex = match allow_origin_regex {
            Some(pattern) if !pattern.bind(py).is_none() => py
                .import("re")?
                .getattr("compile")?
                .call1((pattern.bind(py),))?
                .unbind(),
            _ => py.None(),
        };

        let simple_headers = PyDict::new(py);
        if allow_all_origins {
            simple_headers.set_item("Access-Control-Allow-Origin", "*")?;
        }
        if allow_credentials.bind(py).is_truthy()? {
            simple_headers.set_item("Access-Control-Allow-Credentials", "true")?;
        }
        if expose_headers.bind(py).is_truthy()? {
            simple_headers.set_item(
                "Access-Control-Expose-Headers",
                join_values(py, expose_headers.bind(py))?,
            )?;
        }

        let preflight_explicit_allow_origin = if !allow_all_origins {
            PyBool::new(py, true).to_owned().into_any().unbind()
        } else if allow_credentials.bind(py).is_truthy()? {
            allow_credentials.clone_ref(py)
        } else {
            PyBool::new(py, false).to_owned().into_any().unbind()
        };
        let preflight_headers = PyDict::new(py);
        if preflight_explicit_allow_origin.bind(py).is_truthy()? {
            preflight_headers.set_item("Vary", "Origin")?;
        } else {
            preflight_headers.set_item("Access-Control-Allow-Origin", "*")?;
        }
        preflight_headers.set_item(
            "Access-Control-Allow-Methods",
            join_values(py, allow_methods.bind(py))?,
        )?;
        preflight_headers.set_item(
            "Access-Control-Max-Age",
            py.import("builtins")?
                .getattr("str")?
                .call1((max_age.bind(py),))?,
        )?;

        let builtins = py.import("builtins")?;
        let configured_headers = builtins.getattr("set")?.call1((allow_headers.bind(py),))?;
        let safe_headers = cors_module.getattr("SAFELISTED_HEADERS")?;
        let combined_headers = safe_headers.call_method1("__or__", (configured_headers,))?;
        let sorted_headers = builtins.getattr("sorted")?.call1((combined_headers,))?;
        if sorted_headers.len()? > 0 && !allow_all_headers {
            preflight_headers.set_item(
                "Access-Control-Allow-Headers",
                join_values(py, &sorted_headers)?,
            )?;
        }
        let lowered_headers = PyList::empty(py);
        for header in sorted_headers.try_iter()? {
            lowered_headers.append(header?.call_method0("lower")?)?;
        }
        if allow_credentials.bind(py).is_truthy()? {
            preflight_headers.set_item("Access-Control-Allow-Credentials", "true")?;
        }

        let response_type = py
            .import("starlette.responses")?
            .getattr("PlainTextResponse")?
            .unbind();

        Ok(Self {
            config: Rc::new(RefCell::new(CorsConfig {
                app,
                allow_origins,
                allow_methods,
                allow_headers: lowered_headers.into_any().unbind(),
                allow_all_origins: PyBool::new(py, allow_all_origins)
                    .to_owned()
                    .into_any()
                    .unbind(),
                allow_all_headers: PyBool::new(py, allow_all_headers)
                    .to_owned()
                    .into_any()
                    .unbind(),
                allow_credentials,
                preflight_explicit_allow_origin,
                allow_origin_regex: compiled_allow_origin_regex,
                allow_private_network,
                simple_headers: simple_headers.into_any().unbind(),
                preflight_headers: preflight_headers.into_any().unbind(),
            })),
            plain_text_response_type: response_type,
        })
    }

    #[getter]
    fn app(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().app.clone_ref(py)
    }

    #[setter]
    fn set_app(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().app = value;
    }

    #[getter]
    fn allow_origins(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_origins.clone_ref(py)
    }

    #[setter]
    fn set_allow_origins(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_origins = value;
    }

    #[getter]
    fn allow_methods(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_methods.clone_ref(py)
    }

    #[setter]
    fn set_allow_methods(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_methods = value;
    }

    #[getter]
    fn allow_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_headers.clone_ref(py)
    }

    #[setter]
    fn set_allow_headers(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_headers = value;
    }

    #[getter]
    fn allow_all_origins(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_all_origins.clone_ref(py)
    }

    #[setter]
    fn set_allow_all_origins(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_all_origins = value;
    }

    #[getter]
    fn allow_all_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_all_headers.clone_ref(py)
    }

    #[setter]
    fn set_allow_all_headers(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_all_headers = value;
    }

    #[getter]
    fn allow_credentials(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_credentials.clone_ref(py)
    }

    #[setter]
    fn set_allow_credentials(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_credentials = value;
    }

    #[getter]
    fn preflight_explicit_allow_origin(&self, py: Python<'_>) -> Py<PyAny> {
        self.config
            .borrow()
            .preflight_explicit_allow_origin
            .clone_ref(py)
    }

    #[setter]
    fn set_preflight_explicit_allow_origin(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().preflight_explicit_allow_origin = value;
    }

    #[getter]
    fn allow_origin_regex(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_origin_regex.clone_ref(py)
    }

    #[setter]
    fn set_allow_origin_regex(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_origin_regex = value;
    }

    #[getter]
    fn allow_private_network(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().allow_private_network.clone_ref(py)
    }

    #[setter]
    fn set_allow_private_network(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().allow_private_network = value;
    }

    #[getter]
    fn simple_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().simple_headers.clone_ref(py)
    }

    #[setter]
    fn set_simple_headers(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().simple_headers = value;
    }

    #[getter]
    fn preflight_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.config.borrow().preflight_headers.clone_ref(py)
    }

    #[setter]
    fn set_preflight_headers(&mut self, value: Py<PyAny>) {
        self.config.borrow_mut().preflight_headers = value;
    }

    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            CorsCall {
                middleware: slf,
                scope,
                receive,
                send,
                pending: false,
                direct_request_headers: None,
                direct_request_origin: None,
            },
        )
    }

    fn is_allowed_origin(&self, py: Python<'_>, origin: Py<PyAny>) -> PyResult<bool> {
        is_allowed_origin(&self.config, py, origin.bind(py))
    }

    fn preflight_response(
        &self,
        py: Python<'_>,
        request_headers: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let response_type = self.plain_text_response_type.bind(py);
        let requested_origin = request_headers.bind(py).get_item("origin")?;
        let requested_method = request_headers
            .bind(py)
            .get_item("access-control-request-method")?;
        let requested_headers = request_headers
            .bind(py)
            .call_method1("get", ("access-control-request-headers",))?;
        let requested_private_network = request_headers
            .bind(py)
            .call_method1("get", ("access-control-request-private-network",))?;
        build_preflight_response_values(
            &self.config,
            py,
            &requested_origin,
            requested_method,
            &requested_headers,
            &requested_private_network,
            response_type,
        )
    }

    fn simple_response(
        slf: Py<Self>,
        py: Python<'_>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        request_headers: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            CorsCall {
                middleware: slf,
                scope,
                receive,
                send,
                pending: false,
                direct_request_headers: Some(request_headers),
                direct_request_origin: None,
            },
        )
    }

    fn send(
        slf: Py<Self>,
        py: Python<'_>,
        message: Py<PyAny>,
        send: Py<PyAny>,
        request_headers: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let proxy = Py::new(
            py,
            PyCORSSendProxy {
                middleware: slf,
                send,
                request_headers: Some(request_headers),
                request_origin: None,
                scope_headers: None,
            },
        )?;
        proxy.bind(py).call1((message,)).map(Bound::unbind)
    }

    #[staticmethod]
    fn allow_explicit_origin(
        py: Python<'_>,
        headers: Py<PyAny>,
        origin: Py<PyAny>,
    ) -> PyResult<()> {
        let headers = headers.bind(py);
        headers.set_item("Access-Control-Allow-Origin", origin.bind(py))?;
        let existing_vary = headers.call_method1("get", ("vary",))?;
        let vary = if existing_vary.is_none() {
            PyString::new(py, "Origin").into_any()
        } else {
            let vary_entry = PyString::new(py, "Origin").into_any();
            let values = PyList::new(py, [&existing_vary, &vary_entry])?;
            PyString::new(py, ", ")
                .call_method1("join", (values,))?
                .into_any()
        };
        headers.set_item("vary", vary)?;
        Ok(())
    }
}

struct CorsCall {
    middleware: Py<PyCORSMiddlewareRuntime>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: bool,
    direct_request_headers: Option<Py<PyAny>>,
    direct_request_origin: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for CorsCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("CORS middleware continuation is not pending"),
            ),
        }
    }
}

impl CorsCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.direct_request_headers.is_some() || self.direct_request_origin.is_some() {
            let request_origin = self.direct_request_origin.take();
            let request_headers = self.direct_request_headers.take();
            return self.call_simple_response(py, request_origin, request_headers, None);
        }
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?;
        if !scope_type.eq("http")? {
            return self.call_app(py, self.send.clone_ref(py));
        }

        let source_headers = scope
            .get_item("headers")?
            .ok_or_else(|| PyKeyError::new_err("headers"))?;
        let headers = py
            .import("builtins")?
            .getattr("list")?
            .call1((source_headers,))?;
        scope.set_item("headers", &headers)?;
        let origin = find_header_value(&headers, b"origin")?;
        let Some(origin) = origin else {
            return self.call_app(py, self.send.clone_ref(py));
        };
        let method = scope
            .get_item("method")?
            .ok_or_else(|| PyKeyError::new_err("method"))?;
        let requested_method = find_header_value(&headers, b"access-control-request-method")?;
        if method.eq("OPTIONS")? && requested_method.is_some() {
            let requested_method =
                PyString::new(py, requested_method.as_deref().unwrap_or_default());
            let requested_headers = find_header_value(&headers, b"access-control-request-headers")?
                .map(|value| PyString::new(py, &value).into_any().unbind())
                .unwrap_or_else(|| py.None());
            let requested_private_network =
                find_header_value(&headers, b"access-control-request-private-network")?
                    .map(|value| PyString::new(py, &value).into_any().unbind())
                    .unwrap_or_else(|| py.None());
            let response = {
                let middleware = self.middleware.borrow(py);
                build_preflight_response_values(
                    &middleware.config,
                    py,
                    &PyString::new(py, &origin).into_any(),
                    requested_method.into_any(),
                    requested_headers.bind(py),
                    requested_private_network.bind(py),
                    middleware.plain_text_response_type.bind(py),
                )?
            };
            return self.call_response(py, response.bind(py));
        }

        self.call_simple_response(py, None, None, Some(headers.unbind()))
    }

    fn call_app(&mut self, py: Python<'_>, send: Py<PyAny>) -> PyResult<MachineAction> {
        let app = self.middleware.borrow(py).config.borrow().app.clone_ref(py);
        let awaitable =
            app.bind(py)
                .call1((self.scope.bind(py), self.receive.bind(py), send.bind(py)))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn call_response(
        &mut self,
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
    ) -> PyResult<MachineAction> {
        let awaitable = response.call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn call_simple_response(
        &mut self,
        py: Python<'_>,
        request_origin: Option<Py<PyAny>>,
        request_headers: Option<Py<PyAny>>,
        scope_headers: Option<Py<PyAny>>,
    ) -> PyResult<MachineAction> {
        let proxy = Py::new(
            py,
            PyCORSSendProxy {
                middleware: self.middleware.clone_ref(py),
                send: self.send.clone_ref(py),
                request_headers,
                request_origin,
                scope_headers,
            },
        )?;
        self.call_app(py, proxy.into_any())
    }
}

#[pyclass(unsendable)]
struct PyCORSSendProxy {
    middleware: Py<PyCORSMiddlewareRuntime>,
    send: Py<PyAny>,
    request_headers: Option<Py<PyAny>>,
    request_origin: Option<Py<PyAny>>,
    scope_headers: Option<Py<PyAny>>,
}

#[pymethods]
impl PyCORSSendProxy {
    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
            py,
            CorsSendMessage {
                proxy: slf,
                message,
                pending: false,
            },
        )
    }
}

struct CorsSendMessage {
    proxy: Py<PyCORSSendProxy>,
    message: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for CorsSendMessage {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("CORS send continuation is not pending"),
            ),
        }
    }
}

impl CorsSendMessage {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py);
        if !message.get_item("type")?.eq("http.response.start")? {
            return self.send_message(py);
        }

        let proxy = self.proxy.borrow(py);
        let empty_headers = PyList::empty(py);
        let headers = message.call_method1("setdefault", ("headers", &empty_headers))?;
        let config = proxy.middleware.borrow(py).config.clone();
        let simple_headers = config.borrow().simple_headers.clone_ref(py);
        let items = simple_headers.bind(py).call_method0("items")?;
        for item in items.try_iter()? {
            let item = item?;
            let item = item.cast::<PyTuple>()?;
            set_header(py, &headers, item.get_item(0)?, item.get_item(1)?)?;
        }

        let origin = match proxy.request_origin.as_ref() {
            Some(origin) => origin.clone_ref(py),
            None => match proxy.request_headers.as_ref() {
                Some(request_headers) => request_headers.bind(py).get_item("Origin")?.unbind(),
                None => match proxy.scope_headers.as_ref() {
                    Some(scope_headers) => PyString::new(
                        py,
                        &find_header_value(scope_headers.bind(py), b"origin")?
                            .ok_or_else(|| PyKeyError::new_err("Origin"))?,
                    )
                    .into_any()
                    .unbind(),
                    None => return Err(PyRuntimeError::new_err("CORS send has no request origin")),
                },
            },
        };
        let (allow_all_origins, allow_credentials) = {
            let config = config.borrow();
            (
                config.allow_all_origins.clone_ref(py),
                config.allow_credentials.clone_ref(py),
            )
        };
        let reflect_origin = if allow_all_origins.bind(py).is_truthy()? {
            allow_credentials.bind(py).is_truthy()?
        } else {
            is_allowed_origin(&config, py, origin.bind(py))?
        };
        if reflect_origin {
            set_explicit_origin(py, &headers, origin.bind(py))?;
        }
        drop(proxy);
        self.send_message(py)
    }

    fn send_message(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let send = self.proxy.borrow(py).send.clone_ref(py);
        let awaitable = send.bind(py).call1((self.message.bind(py),))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn is_allowed_origin(
    config: &SharedCorsConfig,
    py: Python<'_>,
    origin: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let (allow_all_origins, allow_origin_regex, allow_origins) = {
        let config = config.borrow();
        (
            config.allow_all_origins.clone_ref(py),
            config.allow_origin_regex.clone_ref(py),
            config.allow_origins.clone_ref(py),
        )
    };
    if allow_all_origins.bind(py).is_truthy()? {
        return Ok(true);
    }
    if !allow_origin_regex.bind(py).is_none()
        && allow_origin_regex
            .bind(py)
            .call_method1("fullmatch", (origin,))?
            .is_truthy()?
    {
        return Ok(true);
    }
    allow_origins.bind(py).contains(origin)
}

fn build_preflight_response_values(
    config: &SharedCorsConfig,
    py: Python<'_>,
    requested_origin: &Bound<'_, PyAny>,
    requested_method: Bound<'_, PyAny>,
    requested_headers: &Bound<'_, PyAny>,
    requested_private_network: &Bound<'_, PyAny>,
    response_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let (
        preflight_headers,
        preflight_explicit,
        allow_methods,
        allow_all_headers,
        allow_headers,
        allow_private_network,
    ) = {
        let config = config.borrow();
        (
            config.preflight_headers.clone_ref(py),
            config.preflight_explicit_allow_origin.clone_ref(py),
            config.allow_methods.clone_ref(py),
            config.allow_all_headers.clone_ref(py),
            config.allow_headers.clone_ref(py),
            config.allow_private_network.clone_ref(py),
        )
    };
    let headers = py
        .import("builtins")?
        .getattr("dict")?
        .call1((preflight_headers.bind(py),))?;
    let mut failures = Vec::new();
    if is_allowed_origin(config, py, requested_origin)? {
        if preflight_explicit.bind(py).is_truthy()? {
            headers.set_item("Access-Control-Allow-Origin", requested_origin)?;
        }
    } else {
        failures.push("origin");
    }
    if !allow_methods.bind(py).contains(&requested_method)? {
        failures.push("method");
    }
    if !requested_headers.is_none() {
        if allow_all_headers.bind(py).is_truthy()? {
            headers.set_item("Access-Control-Allow-Headers", requested_headers)?;
        } else {
            let requested_header_values = requested_headers.call_method1("split", (",",))?;
            for header in requested_header_values.try_iter()? {
                let normalized = header?.call_method0("lower")?.call_method0("strip")?;
                if !allow_headers.bind(py).contains(&normalized)? {
                    failures.push("headers");
                    break;
                }
            }
        }
    }
    if !requested_private_network.is_none() {
        if allow_private_network.bind(py).is_truthy()? {
            headers.set_item("Access-Control-Allow-Private-Network", "true")?;
        } else {
            failures.push("private-network");
        }
    }

    let (text, status_code) = if failures.is_empty() {
        ("OK".to_owned(), 200)
    } else {
        (format!("Disallowed CORS {}", failures.join(", ")), 400)
    };
    let kwargs = PyDict::new(py);
    kwargs.set_item("status_code", status_code)?;
    kwargs.set_item("headers", headers)?;
    response_type
        .call((text,), Some(&kwargs))
        .map(Bound::unbind)
}

fn join_values(py: Python<'_>, values: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    PyString::new(py, ", ")
        .call_method1("join", (values,))
        .map(Bound::unbind)
}

fn find_header_value(headers: &Bound<'_, PyAny>, key: &[u8]) -> PyResult<Option<String>> {
    for item in headers.try_iter()? {
        let (header_name, header_value) = item?.extract::<(Vec<u8>, Vec<u8>)>()?;
        if header_name == key {
            return Ok(Some(latin1_decode(&header_value)));
        }
    }
    Ok(None)
}

fn latin1_decode(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

fn latin1_encode(value: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    value
        .call_method1("encode", ("latin-1",))?
        .extract::<Vec<u8>>()
}

fn set_header(
    py: Python<'_>,
    headers: &Bound<'_, PyAny>,
    key: Bound<'_, PyAny>,
    value: Bound<'_, PyAny>,
) -> PyResult<()> {
    let key = key.call_method0("lower")?;
    let key = latin1_encode(&key)?;
    let value = latin1_encode(&value)?;
    let mut indexes = Vec::new();
    for (index, item) in headers.try_iter()?.enumerate() {
        let (item_key, _item_value) = item?.extract::<(Vec<u8>, Vec<u8>)>()?;
        if item_key == key {
            indexes.push(index);
        }
    }
    if let Some(first) = indexes.first().copied() {
        for index in indexes.iter().skip(1).rev() {
            headers.del_item(*index)?;
        }
        headers.set_item(
            first,
            PyTuple::new(py, [PyBytes::new(py, &key), PyBytes::new(py, &value)])?,
        )?;
    } else {
        headers.call_method1(
            "append",
            (PyTuple::new(
                py,
                [PyBytes::new(py, &key), PyBytes::new(py, &value)],
            )?,),
        )?;
    }
    Ok(())
}

fn header_value(
    py: Python<'_>,
    headers: &Bound<'_, PyAny>,
    key: &[u8],
) -> PyResult<Option<String>> {
    for item in headers.try_iter()? {
        let (item_key, item_value) = item?.extract::<(Vec<u8>, Vec<u8>)>()?;
        if item_key == key {
            return Ok(Some(latin1_decode(&item_value)));
        }
    }
    let _ = py;
    Ok(None)
}

fn set_explicit_origin(
    py: Python<'_>,
    headers: &Bound<'_, PyAny>,
    origin: &Bound<'_, PyAny>,
) -> PyResult<()> {
    set_header(
        py,
        headers,
        PyString::new(py, "Access-Control-Allow-Origin").into_any(),
        origin.clone(),
    )?;
    let existing_vary = header_value(py, headers, b"vary")?;
    let vary = match existing_vary {
        Some(existing) => format!("{existing}, Origin"),
        None => "Origin".to_owned(),
    };
    set_header(
        py,
        headers,
        PyString::new(py, "Vary").into_any(),
        PyString::new(py, &vary).into_any(),
    )
}
