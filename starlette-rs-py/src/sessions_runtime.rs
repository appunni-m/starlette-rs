//! Rust-owned Starlette session middleware and mutation tracking.
//!
//! Python's dict subclass preserves the public session representation while
//! every mutation policy, signed-cookie decision, header update, and ASGI
//! continuation is owned by this module. Python's standard JSON codec is used
//! only to preserve the exact `json.dumps` byte representation Starlette signs.

use std::time::{SystemTime, UNIX_EPOCH};

use base64::Engine as _;
use pyo3::basic::CompareOp;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PyString, PyTuple};
use starlette_rs::{SessionSignatureError, timestamp_sign, timestamp_unsign_with_timestamp_bytes};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PySessionState>()?;
    module.add_class::<PySessionMiddlewareRuntime>()?;
    module.add_class::<PySessionSendWrapper>()?;
    Ok(())
}

/// State shared by a Python `dict` subclass and the Rust mutation protocol.
#[pyclass(name = "SessionState")]
pub(crate) struct PySessionState {
    accessed: bool,
    modified: bool,
}

#[pymethods]
impl PySessionState {
    #[new]
    fn new() -> Self {
        Self {
            accessed: false,
            modified: false,
        }
    }

    #[getter]
    fn accessed(&self) -> bool {
        self.accessed
    }

    #[setter]
    fn set_accessed(&mut self, value: bool) {
        self.accessed = value;
    }

    #[getter]
    fn modified(&self) -> bool {
        self.modified
    }

    #[setter]
    fn set_modified(&mut self, value: bool) {
        self.modified = value;
    }

    fn mark_accessed(&mut self) {
        self.accessed = true;
    }

    fn mark_modified(&mut self) {
        self.accessed = true;
        self.modified = true;
    }

    fn set_item(
        &mut self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.mark_modified();
        py.get_type::<PyDict>()
            .getattr("__setitem__")?
            .call1((session, key, value))?;
        Ok(())
    }

    fn del_item(
        &mut self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        key: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.mark_modified();
        py.get_type::<PyDict>()
            .getattr("__delitem__")?
            .call1((session, key))?;
        Ok(())
    }

    fn clear(&mut self, py: Python<'_>, session: &Bound<'_, PyAny>) -> PyResult<()> {
        self.mark_modified();
        py.get_type::<PyDict>()
            .getattr("clear")?
            .call1((session,))?;
        Ok(())
    }

    #[pyo3(signature = (session, key, *args))]
    fn pop(
        &mut self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        key: &Bound<'_, PyAny>,
        args: &Bound<'_, PyTuple>,
    ) -> PyResult<Py<PyAny>> {
        if !self.modified {
            self.modified = py
                .get_type::<PyDict>()
                .getattr("__contains__")?
                .call1((session, key))?
                .is_truthy()?;
        }

        let mut positional = vec![session.clone().unbind(), key.clone().unbind()];
        positional.extend(args.iter().map(Bound::unbind));
        let positional = PyTuple::new(py, positional)?;
        py.get_type::<PyDict>()
            .getattr("pop")?
            .call(&positional, None)
            .map(Bound::unbind)
    }

    fn setdefault(
        &mut self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        key: &Bound<'_, PyAny>,
        default: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let exists = py
            .get_type::<PyDict>()
            .getattr("__contains__")?
            .call1((session, key))?
            .is_truthy()?;
        if !exists {
            self.mark_modified();
        }
        let method = py.get_type::<PyDict>().getattr("setdefault")?;
        match default {
            Some(default) => method.call1((session, key, default)),
            None => method.call1((session, key)),
        }
        .map(Bound::unbind)
    }

    #[pyo3(signature = (session, *args, **kwargs))]
    fn update(
        &mut self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<()> {
        self.mark_modified();
        let mut positional = vec![session.clone().unbind()];
        positional.extend(args.iter().map(Bound::unbind));
        let positional = PyTuple::new(py, positional)?;
        py.get_type::<PyDict>()
            .getattr("update")?
            .call(&positional, kwargs)?;
        Ok(())
    }

    fn popitem(&self, py: Python<'_>, session: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        py.get_type::<PyDict>()
            .getattr("popitem")?
            .call1((session,))
            .map(Bound::unbind)
    }

    fn ior(
        &self,
        py: Python<'_>,
        session: &Bound<'_, PyAny>,
        other: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        py.get_type::<PyDict>()
            .getattr("__ior__")?
            .call1((session, other))
            .map(Bound::unbind)
    }
}

/// Rust runtime behind the public `starlette.middleware.sessions` facade.
#[pyclass(name = "SessionMiddlewareRuntime")]
pub(crate) struct PySessionMiddlewareRuntime {
    app: Py<PyAny>,
    secret_key: String,
    session_cookie: Py<PyAny>,
    max_age: Py<PyAny>,
    path: String,
    security_flags: String,
    clock_override: Option<u64>,
}

#[pymethods]
impl PySessionMiddlewareRuntime {
    #[new]
    #[pyo3(signature = (app, secret_key, session_cookie, max_age, path, same_site, https_only, domain))]
    // LINT EXCEPTION: Preserve Starlette SessionMiddleware's constructor options and defaults one-for-one.
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        app: Py<PyAny>,
        secret_key: Py<PyAny>,
        session_cookie: Py<PyAny>,
        max_age: Py<PyAny>,
        path: &str,
        same_site: &str,
        https_only: bool,
        domain: Option<String>,
    ) -> PyResult<Self> {
        let secret_key = py
            .import("builtins")?
            .getattr("str")?
            .call1((secret_key,))?
            .extract::<String>()?;
        let mut security_flags = format!("httponly; samesite={same_site}");
        if https_only {
            security_flags.push_str("; secure");
        }
        if let Some(domain) = domain {
            security_flags.push_str("; domain=");
            security_flags.push_str(&domain);
        }
        Ok(Self {
            app,
            secret_key,
            session_cookie,
            max_age,
            path: path.to_owned(),
            security_flags,
            clock_override: None,
        })
    }

    #[getter]
    fn app(&self, py: Python<'_>) -> Py<PyAny> {
        self.app.clone_ref(py)
    }

    #[setter]
    fn set_app(&mut self, app: Py<PyAny>) {
        self.app = app;
    }

    #[getter]
    fn session_cookie(&self, py: Python<'_>) -> Py<PyAny> {
        self.session_cookie.clone_ref(py)
    }

    #[setter]
    fn set_session_cookie(&mut self, session_cookie: Py<PyAny>) {
        self.session_cookie = session_cookie;
    }

    #[getter]
    fn max_age(&self, py: Python<'_>) -> Py<PyAny> {
        self.max_age.clone_ref(py)
    }

    #[setter]
    fn set_max_age(&mut self, max_age: Py<PyAny>) {
        self.max_age = max_age;
    }

    #[getter]
    fn path(&self) -> String {
        self.path.clone()
    }

    #[setter]
    fn set_path(&mut self, path: String) {
        self.path = path;
    }

    /// Private parity seam; normal package calls use the live system clock.
    fn set_clock_for_test(&mut self, epoch_seconds: u64) {
        self.clock_override = Some(epoch_seconds);
    }

    #[getter]
    fn security_flags(&self) -> String {
        self.security_flags.clone()
    }

    #[setter]
    fn set_security_flags(&mut self, security_flags: String) {
        self.security_flags = security_flags;
    }

    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            SessionMiddlewareCall {
                runtime: slf,
                scope,
                receive,
                send,
                pending: false,
            },
        )
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.session_cookie)?;
        visit.call(&self.max_age)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
        self.session_cookie = py.None();
        self.max_age = py.None();
    }
}

struct SessionMiddlewareCall {
    runtime: Py<PySessionMiddlewareRuntime>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for SessionMiddlewareCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.runtime)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

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
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("session middleware has no pending application call"),
            ),
        }
    }
}

impl SessionMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let runtime = self.runtime.borrow(py);
        let scope_type = self.scope.bind(py).get_item("type")?;
        let supported_scope_types = PyTuple::new(py, ["http", "websocket"])?;
        // Keep Python's tuple-membership behavior for arbitrary ASGI scope values.
        if !supported_scope_types.contains(&scope_type)? {
            let awaitable = runtime.app.bind(py).call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?;
            self.pending = true;
            return Ok(MachineAction::Await(awaitable.unbind()));
        }

        let connection_type = py.import("starlette.requests")?.getattr("HTTPConnection")?;
        let connection = connection_type.call1((self.scope.bind(py),))?;
        let cookies = connection.getattr("cookies")?;
        let cookie_value = cookies.call_method1("get", (runtime.session_cookie.bind(py),))?;
        let now = match runtime.clock_override {
            Some(value) => value,
            None => system_time_seconds()?,
        };

        let (session_value, initial_session_was_empty) = if cookie_value.is_none() {
            (py.None(), true)
        } else {
            let cookie_bytes = cookie_value
                .call_method1("encode", ("utf-8",))?
                .extract::<Vec<u8>>()?;
            match timestamp_unsign_with_timestamp_bytes(&cookie_bytes, &runtime.secret_key) {
                Ok((payload, timestamp_bytes)) => {
                    let timestamp = python_unsigned_integer(py, &timestamp_bytes)?;
                    let max_age = runtime.max_age.bind(py);
                    let expired = if max_age.is_none() {
                        false
                    } else {
                        let age =
                            PyInt::new(py, now).call_method1("__sub__", (timestamp.bind(py),))?;
                        let exceeds_max_age =
                            age.rich_compare(max_age, CompareOp::Gt)?.is_truthy()?;
                        let is_future_timestamp = age
                            .rich_compare(PyInt::new(py, 0), CompareOp::Lt)?
                            .is_truthy()?;
                        exceeds_max_age || is_future_timestamp
                    };
                    if expired {
                        // itsdangerous converts the timestamp while building
                        // SignatureExpired; datetime can reject out-of-range
                        // authenticated timestamps before Starlette catches it.
                        timestamp_to_datetime(py, timestamp.bind(py))?;
                        (py.None(), true)
                    } else {
                        let encoded_json = py
                            .import("base64")?
                            .getattr("b64decode")?
                            .call1((PyBytes::new(py, &payload),))?;
                        let decoded = py
                            .import("json")?
                            .getattr("loads")?
                            .call1((encoded_json,))?;
                        (decoded.unbind(), false)
                    }
                }
                Err(_) => (py.None(), true),
            }
        };

        let session_type = py
            .import("starlette.middleware.sessions")?
            .getattr("Session")?;
        let session = match session_value.is_none(py) {
            true => session_type.call0()?,
            false => session_type.call1((session_value,))?,
        };
        self.scope.bind(py).set_item("session", &session)?;

        let wrapper = Py::new(
            py,
            PySessionSendWrapper {
                send: self.send.clone_ref(py),
                scope: self.scope.clone_ref(py),
                runtime: Some(self.runtime.clone_ref(py)),
                initial_session_was_empty,
            },
        )?;
        let awaitable =
            runtime
                .app
                .bind(py)
                .call1((self.scope.bind(py), self.receive.bind(py), wrapper))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn python_unsigned_integer(py: Python<'_>, bytes: &[u8]) -> PyResult<Py<PyAny>> {
    let integer = py
        .import("builtins")?
        .getattr("int")?
        .call_method1("from_bytes", (PyBytes::new(py, bytes), "big"))?;
    Ok(integer.unbind())
}

fn timestamp_to_datetime(py: Python<'_>, timestamp: &Bound<'_, PyAny>) -> PyResult<()> {
    let datetime = py.import("datetime")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("tz", datetime.getattr("timezone")?.getattr("utc")?)?;
    datetime
        .getattr("datetime")?
        .call_method("fromtimestamp", (timestamp,), Some(&kwargs))?;
    Ok(())
}

/// Callable ASGI send wrapper whose response-header decisions stay in Rust.
#[pyclass(name = "SessionSendWrapper")]
pub(crate) struct PySessionSendWrapper {
    send: Py<PyAny>,
    scope: Py<PyAny>,
    runtime: Option<Py<PySessionMiddlewareRuntime>>,
    initial_session_was_empty: bool,
}

#[pymethods]
impl PySessionSendWrapper {
    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            SessionSendCall {
                wrapper: slf,
                message,
                pending: false,
            },
        )
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send)?;
        visit.call(&self.scope)?;
        if let Some(runtime) = &self.runtime {
            visit.call(runtime)?;
        }
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.send = py.None();
        self.scope = py.None();
        self.runtime = None;
    }
}

struct SessionSendCall {
    wrapper: Py<PySessionSendWrapper>,
    message: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for SessionSendCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.wrapper)?;
        visit.call(&self.message)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

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
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("session send wrapper has no pending send callback"),
            ),
        }
    }
}

impl SessionSendCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let wrapper = self.wrapper.borrow(py);
        let message = self.message.bind(py);
        // Starlette uses Python equality here; preserve overrides on str subclasses.
        if message.get_item("type")?.eq("http.response.start")? {
            self.apply_session_headers(py, &wrapper, message)?;
        }
        let awaitable = wrapper.send.bind(py).call1((message,))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn apply_session_headers(
        &self,
        py: Python<'_>,
        wrapper: &PySessionSendWrapper,
        message: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let runtime = wrapper.runtime.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("session middleware runtime has been cleared")
        })?;
        let runtime = runtime.borrow(py);
        let session = wrapper.scope.bind(py).get_item("session")?;
        let accessed = session.getattr("accessed")?.is_truthy()?;
        let modified = session.getattr("modified")?.is_truthy()?;
        let nonempty = session.is_truthy()?;
        let response_start = message.cast::<PyDict>()?;
        let headers = response_start
            .get_item("headers")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("headers"))?;
        // MutableHeaders(scope=message) normalizes the ASGI header iterable
        // with list() and stores that list back on the response-start message.
        let headers = py.import("builtins")?.getattr("list")?.call1((headers,))?;
        response_start.set_item("headers", &headers)?;
        let headers = headers.cast_into::<PyList>()?;

        if accessed {
            add_vary_cookie(py, &headers)?;
        }
        if modified && nonempty {
            let json = py.import("json")?.getattr("dumps")?.call1((session,))?;
            let json_bytes = json
                .call_method1("encode", ("utf-8",))?
                .extract::<Vec<u8>>()?;
            let encoded = base64::engine::general_purpose::STANDARD.encode(json_bytes);
            let clock_epoch = match runtime.clock_override {
                Some(value) => value,
                None => system_time_seconds()?,
            };
            let signed = timestamp_sign(encoded.as_bytes(), &runtime.secret_key, clock_epoch)
                .map_err(signature_error)?;
            let signed = String::from_utf8(signed).map_err(|_| {
                PyRuntimeError::new_err("session signer returned a non-UTF-8 cookie value")
            })?;
            let max_age = if runtime.max_age.bind(py).is_truthy()? {
                let max_age = py
                    .import("builtins")?
                    .getattr("str")?
                    .call1((runtime.max_age.bind(py),))?
                    .extract::<String>()?;
                format!("Max-Age={max_age}; ")
            } else {
                String::new()
            };
            let value = format_cookie_header(
                py,
                "{session_cookie}={data}; path={path}; {max_age}{security_flags}",
                runtime.session_cookie.bind(py),
                &signed,
                &runtime.path,
                &max_age,
                &runtime.security_flags,
            )?;
            append_header(py, &headers, "set-cookie", &value)?;
        } else if modified && !nonempty && !wrapper.initial_session_was_empty {
            let value = format_cookie_header(
                py,
                "{session_cookie}=null; path={path}; expires=Thu, 01 Jan 1970 00:00:00 GMT; {security_flags}",
                runtime.session_cookie.bind(py),
                "",
                &runtime.path,
                "",
                &runtime.security_flags,
            )?;
            append_header(py, &headers, "set-cookie", &value)?;
        }
        Ok(())
    }
}

fn add_vary_cookie(py: Python<'_>, headers: &Bound<'_, PyList>) -> PyResult<()> {
    let mut matches = Vec::new();
    let mut current = None;
    for index in 0..headers.len() {
        let pair = headers.get_item(index)?.cast_into::<PyTuple>()?;
        let name = pair.get_item(0)?.extract::<Vec<u8>>()?;
        if name == b"vary" {
            if current.is_none() {
                current = Some(pair.get_item(1)?.extract::<Vec<u8>>()?);
            }
            matches.push(index);
        }
    }
    let value = match current {
        Some(value) => {
            let existing = PyBytes::new(py, &value)
                .call_method1("decode", ("latin-1",))?
                .extract::<String>()?;
            format!("{existing}, Cookie")
        }
        None => String::from("Cookie"),
    };
    let value = latin1_bytes(py, &value)?;
    if let Some(first) = matches.first().copied() {
        headers.set_item(
            first,
            PyTuple::new(py, [PyBytes::new(py, b"vary"), value.clone()])?,
        )?;
        for index in matches.into_iter().skip(1).rev() {
            headers.del_item(index)?;
        }
    } else {
        headers.append(PyTuple::new(py, [PyBytes::new(py, b"vary"), value])?)?;
    }
    Ok(())
}

fn append_header(
    py: Python<'_>,
    headers: &Bound<'_, PyList>,
    name: &str,
    value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let name = latin1_bytes(py, name)?;
    let value = value
        .call_method1("encode", ("latin-1",))?
        .cast_into::<PyBytes>()?;
    headers.append(PyTuple::new(py, [name, value])?)
}

fn format_cookie_header<'py>(
    py: Python<'py>,
    template: &str,
    session_cookie: &Bound<'py, PyAny>,
    data: &str,
    path: &str,
    max_age: &str,
    security_flags: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let fields = PyDict::new(py);
    fields.set_item("session_cookie", session_cookie)?;
    fields.set_item("data", data)?;
    fields.set_item("path", path)?;
    fields.set_item("max_age", max_age)?;
    fields.set_item("security_flags", security_flags)?;
    PyString::new(py, template).call_method("format", (), Some(&fields))
}

fn latin1_bytes<'py>(py: Python<'py>, value: &str) -> PyResult<Bound<'py, PyBytes>> {
    Ok(PyString::new(py, value)
        .call_method1("encode", ("latin-1",))?
        .cast_into::<PyBytes>()?)
}

fn system_time_seconds() -> PyResult<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|error| PyRuntimeError::new_err(error.to_string()))
}

fn signature_error(error: SessionSignatureError) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}
