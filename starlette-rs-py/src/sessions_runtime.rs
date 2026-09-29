//! Rust-owned Starlette session middleware and mutation tracking.
//!
//! Python's dict subclass preserves the public session representation while
//! every mutation policy, signed-cookie decision, header update, and ASGI
//! continuation is owned by this module. Python's standard JSON codec is used
//! only to preserve the exact `json.dumps` byte representation Starlette signs.

use std::time::{SystemTime, UNIX_EPOCH};

use base64::Engine as _;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};
use starlette_rs::{SessionSignatureError, timestamp_sign, timestamp_unsign};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PySessionState>()?;
    module.add_class::<PySessionMiddlewareRuntime>()?;
    module.add_class::<PySessionSendWrapper>()?;
    Ok(())
}

/// State shared by a Python `dict` subclass and the Rust mutation protocol.
#[pyclass(name = "SessionState", unsendable)]
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
}

/// Rust runtime behind the public `starlette.middleware.sessions` facade.
#[pyclass(name = "SessionMiddlewareRuntime", unsendable)]
pub(crate) struct PySessionMiddlewareRuntime {
    app: Py<PyAny>,
    secret_key: String,
    session_cookie: String,
    max_age: Option<i64>,
    path: String,
    security_flags: String,
    clock_override: Option<u64>,
}

#[pymethods]
impl PySessionMiddlewareRuntime {
    #[new]
    #[pyo3(signature = (app, secret_key, session_cookie="session", max_age=Some(1209600), path="/", same_site="lax", https_only=false, domain=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        app: Py<PyAny>,
        secret_key: Py<PyAny>,
        session_cookie: &str,
        max_age: Option<i64>,
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
            session_cookie: session_cookie.to_owned(),
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
    fn session_cookie(&self) -> String {
        self.session_cookie.clone()
    }

    #[setter]
    fn set_session_cookie(&mut self, session_cookie: String) {
        self.session_cookie = session_cookie;
    }

    #[getter]
    fn max_age(&self) -> Option<i64> {
        self.max_age
    }

    #[setter]
    fn set_max_age(&mut self, max_age: Option<i64>) {
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
        into_python_awaitable(
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
        visit.call(&self.app)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
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
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("session middleware has no pending application call"),
            ),
        }
    }
}

impl SessionMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let runtime = self.runtime.borrow(py);
        let scope_type = self.scope.bind(py).get_item("type")?.extract::<String>()?;
        if scope_type != "http" && scope_type != "websocket" {
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
        let cookie_value = cookies.call_method1("get", (runtime.session_cookie.as_str(),))?;
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
            match timestamp_unsign(&cookie_bytes, &runtime.secret_key, now, runtime.max_age) {
                Ok(payload) => {
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

/// Callable ASGI send wrapper whose response-header decisions stay in Rust.
#[pyclass(name = "SessionSendWrapper", unsendable)]
pub(crate) struct PySessionSendWrapper {
    send: Py<PyAny>,
    scope: Py<PyAny>,
    runtime: Option<Py<PySessionMiddlewareRuntime>>,
    initial_session_was_empty: bool,
}

#[pymethods]
impl PySessionSendWrapper {
    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
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
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
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
        let message_type = message.get_item("type")?.extract::<String>()?;
        if message_type == "http.response.start" {
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
        let headers = match response_start.get_item("headers")? {
            Some(headers) => headers.cast_into::<PyList>()?,
            None => {
                let headers = PyList::empty(py);
                response_start.set_item("headers", &headers)?;
                headers
            }
        };

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
            let mut value = format!(
                "{}={}; path={}; ",
                runtime.session_cookie, signed, runtime.path
            );
            if runtime.max_age.is_some_and(|age| age != 0) {
                value.push_str(&format!(
                    "Max-Age={}; ",
                    runtime.max_age.unwrap_or_default()
                ));
            }
            value.push_str(&runtime.security_flags);
            append_header(py, &headers, "set-cookie", &value)?;
        } else if modified && !nonempty && !wrapper.initial_session_was_empty {
            let value = format!(
                "{}=null; path={}; expires=Thu, 01 Jan 1970 00:00:00 GMT; {}",
                runtime.session_cookie, runtime.path, runtime.security_flags
            );
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
    value: &str,
) -> PyResult<()> {
    let name = latin1_bytes(py, name)?;
    let value = latin1_bytes(py, value)?;
    headers.append(PyTuple::new(py, [name, value])?)
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
