//! Rust-owned authentication policy and ASGI middleware flow.
//!
//! Python remains the boundary for user callables, decorated-function wrappers,
//! connection objects, and Python's active event loop. Rust owns scope checks,
//! decorator selection, authentication outcomes, and middleware dispatch.

use pyo3::exceptions::{
    PyAssertionError, PyException, PyKeyError, PyNotImplementedError, PyRuntimeError,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyRequiresConfig>()?;
    module.add_class::<PyRequiresRuntime>()?;
    module.add_class::<PyAuthenticationMiddlewareRuntime>()?;
    module.add_function(wrap_pyfunction!(authentication_has_required_scope, module)?)?;
    module.add_function(wrap_pyfunction!(authentication_requires_config, module)?)?;
    module.add_function(wrap_pyfunction!(authentication_requires_decorate, module)?)?;
    module.add_function(wrap_pyfunction!(
        authentication_requires_invoke_sync,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(authentication_requires_invoke, module)?)?;
    module.add_function(wrap_pyfunction!(authentication_credentials_scopes, module)?)?;
    module.add_function(wrap_pyfunction!(
        authentication_base_user_unimplemented,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_unimplemented_async,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_simple_user_is_authenticated,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_simple_user_display_name,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_unauthenticated_user_is_authenticated,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_unauthenticated_user_display_name,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        authentication_middleware_initialize,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(authentication_middleware_invoke, module)?)?;
    module.add_function(wrap_pyfunction!(authentication_default_error, module)?)?;
    Ok(())
}

#[pyclass(name = "_AuthenticationRequiresConfig", unsendable)]
struct PyRequiresConfig {
    scopes: Py<PyAny>,
    status_code: Py<PyAny>,
    redirect: Py<PyAny>,
}

#[pyclass(name = "_AuthenticationRequiresRuntime", unsendable)]
struct PyRequiresRuntime {
    mode: RequiresMode,
    func: Py<PyAny>,
    scopes: Py<PyAny>,
    status_code: Py<PyAny>,
    redirect: Py<PyAny>,
    parameter_name: String,
    parameter_index: usize,
    request_type: Py<PyAny>,
    websocket_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
}

#[derive(Clone, Copy)]
enum RequiresMode {
    WebSocket,
    AsyncRequest,
    SyncRequest,
}

#[pyfunction]
fn authentication_has_required_scope(
    conn: &Bound<'_, PyAny>,
    scopes: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let credentials = conn.getattr("auth")?;
    let granted = credentials.getattr("scopes")?;
    for scope in scopes.try_iter()? {
        if !granted.contains(scope?)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[pyfunction]
fn authentication_requires_config(
    py: Python<'_>,
    scopes: Py<PyAny>,
    status_code: Py<PyAny>,
    redirect: Option<Py<PyAny>>,
) -> PyResult<Py<PyRequiresConfig>> {
    let scopes = if scopes.bind(py).is_instance_of::<PyString>() {
        PyList::new(py, [scopes])?.into_any().unbind()
    } else {
        py.import("builtins")?
            .getattr("list")?
            .call1((scopes,))?
            .unbind()
    };
    Py::new(
        py,
        PyRequiresConfig {
            scopes,
            status_code,
            redirect: redirect.unwrap_or_else(|| py.None()),
        },
    )
}

#[allow(clippy::too_many_arguments)]
#[pyfunction]
fn authentication_requires_decorate(
    py: Python<'_>,
    config: Py<PyRequiresConfig>,
    func: Py<PyAny>,
    websocket_wrapper_factory: &Bound<'_, PyAny>,
    async_wrapper_factory: &Bound<'_, PyAny>,
    sync_wrapper_factory: &Bound<'_, PyAny>,
    request_type: Py<PyAny>,
    websocket_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let func_bound = func.bind(py);
    let inspect = py.import("inspect")?;
    let signature = inspect.getattr("signature")?.call1((func_bound,))?;
    let parameters = signature.getattr("parameters")?;
    let mut selected_parameter = None;
    for (index, parameter) in parameters.call_method0("values")?.try_iter()?.enumerate() {
        let parameter = parameter?;
        let name = parameter.getattr("name")?.extract::<String>()?;
        if name == "request" || name == "websocket" {
            selected_parameter = Some((name, index));
            break;
        }
    }
    let (parameter_name, parameter_index) = selected_parameter.ok_or_else(|| {
        let callable = py
            .import("builtins")
            .and_then(|builtins| builtins.getattr("str"))
            .and_then(|str_fn| str_fn.call1((func_bound,)))
            .and_then(|value| value.extract::<String>());
        match callable {
            Ok(callable) => PyException::new_err(format!(
                "No \"request\" or \"websocket\" argument on function \"{callable}\""
            )),
            Err(error) => error,
        }
    })?;

    let config = config.borrow(py);
    let mode = if parameter_name == "websocket" {
        RequiresMode::WebSocket
    } else if crate::background::is_async_callable(py, func_bound)? {
        RequiresMode::AsyncRequest
    } else {
        RequiresMode::SyncRequest
    };
    let runtime = Py::new(
        py,
        PyRequiresRuntime {
            mode,
            func: func.clone_ref(py),
            scopes: config.scopes.clone_ref(py),
            status_code: config.status_code.clone_ref(py),
            redirect: config.redirect.clone_ref(py),
            parameter_name,
            parameter_index,
            request_type,
            websocket_type,
            http_exception_type,
            redirect_response_type,
        },
    )?;
    let wrapper_factory = match mode {
        RequiresMode::WebSocket => websocket_wrapper_factory,
        RequiresMode::AsyncRequest => async_wrapper_factory,
        RequiresMode::SyncRequest => sync_wrapper_factory,
    };
    wrapper_factory
        .call1((runtime, func_bound))
        .map(Bound::unbind)
}

#[pyfunction]
fn authentication_requires_invoke_sync(
    py: Python<'_>,
    runtime: Py<PyRequiresRuntime>,
    args: &Bound<'_, PyTuple>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let runtime = requires_runtime_values(py, &runtime)?;
    let connection = decorator_connection(py, &runtime, args, kwargs)?;
    let connection = connection.bind(py);
    validate_connection_type(py, &runtime, connection)?;
    if connection_has_scopes(py, connection, &runtime.scopes)? {
        return runtime
            .func
            .bind(py)
            .call(args, Some(kwargs))
            .map(Bound::unbind);
    }
    if runtime.redirect.bind(py).is_none() {
        return Err(http_exception(py, &runtime)?);
    }
    denied_redirect(py, &runtime, connection)
}

#[pyfunction]
fn authentication_requires_invoke(
    py: Python<'_>,
    runtime: Py<PyRequiresRuntime>,
    args: Py<PyTuple>,
    kwargs: Py<PyDict>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        RequiresCall {
            runtime,
            args,
            kwargs,
            pending: false,
        },
    )
}

struct RequiresRuntimeValues {
    mode: RequiresMode,
    func: Py<PyAny>,
    scopes: Py<PyAny>,
    status_code: Py<PyAny>,
    redirect: Py<PyAny>,
    parameter_name: String,
    parameter_index: usize,
    request_type: Py<PyAny>,
    websocket_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
}

fn requires_runtime_values(
    py: Python<'_>,
    runtime: &Py<PyRequiresRuntime>,
) -> PyResult<RequiresRuntimeValues> {
    let runtime = runtime.borrow(py);
    Ok(RequiresRuntimeValues {
        mode: runtime.mode,
        func: runtime.func.clone_ref(py),
        scopes: runtime.scopes.clone_ref(py),
        status_code: runtime.status_code.clone_ref(py),
        redirect: runtime.redirect.clone_ref(py),
        parameter_name: runtime.parameter_name.clone(),
        parameter_index: runtime.parameter_index,
        request_type: runtime.request_type.clone_ref(py),
        websocket_type: runtime.websocket_type.clone_ref(py),
        http_exception_type: runtime.http_exception_type.clone_ref(py),
        redirect_response_type: runtime.redirect_response_type.clone_ref(py),
    })
}

fn decorator_connection(
    py: Python<'_>,
    runtime: &RequiresRuntimeValues,
    args: &Bound<'_, PyTuple>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let fallback = if runtime.parameter_index < args.len() {
        args.get_item(runtime.parameter_index)?.unbind()
    } else {
        py.None()
    };
    kwargs
        .call_method1("get", (runtime.parameter_name.as_str(), fallback))
        .map(Bound::unbind)
}

fn validate_connection_type(
    py: Python<'_>,
    runtime: &RequiresRuntimeValues,
    connection: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let (type_object, type_label) = match runtime.mode {
        RequiresMode::WebSocket => (&runtime.websocket_type, "WebSocket"),
        RequiresMode::AsyncRequest | RequiresMode::SyncRequest => {
            (&runtime.request_type, "Request")
        }
    };
    if connection.is_instance(type_object.bind(py))? {
        return Ok(());
    }
    let actual_type = py
        .import("builtins")?
        .getattr("type")?
        .call1((connection,))?
        .getattr("__name__")?
        .extract::<String>()?;
    let message = match runtime.mode {
        RequiresMode::WebSocket => format!(
            "Parameter with name 'websocket' is required to be of type 'WebSocket' not '{actual_type}'"
        ),
        RequiresMode::AsyncRequest | RequiresMode::SyncRequest => format!(
            "Parameter with name 'request' is required to be of type 'Request' not '{actual_type}'"
        ),
    };
    let _ = type_label;
    Err(PyAssertionError::new_err(message))
}

fn connection_has_scopes(
    py: Python<'_>,
    connection: &Bound<'_, PyAny>,
    required: &Py<PyAny>,
) -> PyResult<bool> {
    let auth = connection.getattr("auth")?;
    let granted = auth.getattr("scopes")?;
    for scope in required.bind(py).try_iter()? {
        if !granted.contains(scope?)? {
            return Ok(false);
        }
    }
    Ok(true)
}

fn http_exception(py: Python<'_>, runtime: &RequiresRuntimeValues) -> PyResult<PyErr> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("status_code", runtime.status_code.bind(py))?;
    let exception = runtime
        .http_exception_type
        .bind(py)
        .call((), Some(&kwargs))?;
    Ok(PyErr::from_value(exception))
}

fn denied_redirect(
    py: Python<'_>,
    runtime: &RequiresRuntimeValues,
    request: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let current_url = request.getattr("url")?.str()?.extract::<String>()?;
    let query = PyDict::new(py);
    query.set_item("next", current_url)?;
    let encoded_query = py
        .import("urllib.parse")?
        .getattr("urlencode")?
        .call1((query,))?
        .extract::<String>()?;
    let destination = request
        .call_method1("url_for", (runtime.redirect.bind(py),))?
        .str()?
        .extract::<String>()?;
    let url = format!("{destination}?{encoded_query}");
    let kwargs = PyDict::new(py);
    kwargs.set_item("url", url)?;
    kwargs.set_item("status_code", 303)?;
    runtime
        .redirect_response_type
        .bind(py)
        .call((), Some(&kwargs))
        .map(Bound::unbind)
}

struct RequiresCall {
    runtime: Py<PyRequiresRuntime>,
    args: Py<PyTuple>,
    kwargs: Py<PyDict>,
    pending: bool,
}

impl AwaitableStateMachine for RequiresCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(value) if self.pending => {
                self.pending = false;
                let runtime = self.runtime.borrow(py);
                let result = match runtime.mode {
                    RequiresMode::WebSocket => py.None(),
                    RequiresMode::AsyncRequest => value,
                    RequiresMode::SyncRequest => {
                        return Err(PyRuntimeError::new_err(
                            "synchronous requires wrapper entered the async runtime",
                        ));
                    }
                };
                Ok(MachineAction::Complete(result))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(_) => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
            }
            _ => Err(PyRuntimeError::new_err(
                "requires wrapper resumed without a pending callback",
            )),
        }
    }
}

impl RequiresCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let runtime = requires_runtime_values(py, &self.runtime)?;
        let connection =
            decorator_connection(py, &runtime, self.args.bind(py), self.kwargs.bind(py))?;
        let connection = connection.bind(py);
        validate_connection_type(py, &runtime, connection)?;
        let authorized = connection_has_scopes(py, connection, &runtime.scopes)?;
        if !authorized {
            match runtime.mode {
                RequiresMode::WebSocket => {
                    let closing = connection.call_method0("close")?.unbind();
                    self.pending = true;
                    return Ok(MachineAction::Await(closing));
                }
                RequiresMode::AsyncRequest if !runtime.redirect.bind(py).is_none() => {
                    return denied_redirect(py, &runtime, connection).map(MachineAction::Complete);
                }
                RequiresMode::AsyncRequest => return Err(http_exception(py, &runtime)?),
                RequiresMode::SyncRequest => {
                    return Err(PyRuntimeError::new_err(
                        "synchronous requires wrapper entered the async runtime",
                    ));
                }
            }
        }
        let callback = runtime
            .func
            .bind(py)
            .call(self.args.bind(py), Some(self.kwargs.bind(py)))?;
        self.pending = true;
        Ok(MachineAction::Await(callback.unbind()))
    }
}

#[pyfunction]
fn authentication_credentials_scopes(
    py: Python<'_>,
    scopes: Option<Py<PyAny>>,
) -> PyResult<Py<PyAny>> {
    match scopes {
        Some(scopes) => py
            .import("builtins")?
            .getattr("list")?
            .call1((scopes,))
            .map(Bound::unbind),
        None => Ok(PyList::empty(py).into_any().unbind()),
    }
}

#[pyfunction]
fn authentication_base_user_unimplemented(property: &str) -> PyResult<Py<PyAny>> {
    let _ = property;
    Err(PyNotImplementedError::new_err(()))
}

struct AuthenticationUnimplemented;

impl AwaitableStateMachine for AuthenticationUnimplemented {
    fn resume(&mut self, _py: Python<'_>, _input: MachineResume) -> PyResult<MachineAction> {
        Err(PyNotImplementedError::new_err(()))
    }
}

#[pyfunction]
fn authentication_unimplemented_async(py: Python<'_>, method: &str) -> PyResult<Py<PyAny>> {
    let _ = method;
    into_python_awaitable(py, AuthenticationUnimplemented)
}

#[pyfunction]
fn authentication_simple_user_is_authenticated() -> bool {
    true
}

#[pyfunction]
fn authentication_simple_user_display_name(username: Py<PyAny>) -> Py<PyAny> {
    username
}

#[pyfunction]
fn authentication_unauthenticated_user_is_authenticated() -> bool {
    false
}

#[pyfunction]
fn authentication_unauthenticated_user_display_name(py: Python<'_>) -> Py<PyAny> {
    PyString::new(py, "").into_any().unbind()
}

#[pyclass(name = "_AuthenticationMiddlewareRuntime", unsendable)]
struct PyAuthenticationMiddlewareRuntime {
    app: Py<PyAny>,
    backend: Py<PyAny>,
    on_error: Py<PyAny>,
    http_connection_type: Py<PyAny>,
    authentication_error_type: Py<PyAny>,
    credentials_type: Py<PyAny>,
    unauthenticated_user_type: Py<PyAny>,
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn authentication_middleware_initialize(
    py: Python<'_>,
    app: Py<PyAny>,
    backend: Py<PyAny>,
    on_error: Option<Py<PyAny>>,
    default_on_error: Py<PyAny>,
    http_connection_type: Py<PyAny>,
    authentication_error_type: Py<PyAny>,
    credentials_type: Py<PyAny>,
    unauthenticated_user_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let on_error = match on_error {
        Some(on_error) if !on_error.bind(py).is_none() => on_error,
        _ => default_on_error,
    };
    let runtime = Py::new(
        py,
        PyAuthenticationMiddlewareRuntime {
            app,
            backend,
            on_error: on_error.clone_ref(py),
            http_connection_type,
            authentication_error_type,
            credentials_type,
            unauthenticated_user_type,
        },
    )?;
    PyTuple::new(py, [on_error.into_any(), runtime.into_any()])
        .map(|value| value.into_any().unbind())
}

#[pyfunction]
fn authentication_default_error(
    py: Python<'_>,
    _connection: &Bound<'_, PyAny>,
    error: &Bound<'_, PyAny>,
    plain_text_response_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let message = error.str()?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("status_code", 400)?;
    plain_text_response_type
        .call((message,), Some(&kwargs))
        .map(Bound::unbind)
}

#[pyfunction]
fn authentication_middleware_invoke(
    py: Python<'_>,
    runtime: Py<PyAuthenticationMiddlewareRuntime>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        AuthenticationMiddlewareCall {
            runtime,
            scope,
            receive,
            send,
            connection: None,
            pending: None,
        },
    )
}

struct AuthenticationRuntimeValues {
    app: Py<PyAny>,
    backend: Py<PyAny>,
    on_error: Py<PyAny>,
    http_connection_type: Py<PyAny>,
    authentication_error_type: Py<PyAny>,
    credentials_type: Py<PyAny>,
    unauthenticated_user_type: Py<PyAny>,
}

fn authentication_runtime_values(
    py: Python<'_>,
    runtime: &Py<PyAuthenticationMiddlewareRuntime>,
) -> AuthenticationRuntimeValues {
    let runtime = runtime.borrow(py);
    AuthenticationRuntimeValues {
        app: runtime.app.clone_ref(py),
        backend: runtime.backend.clone_ref(py),
        on_error: runtime.on_error.clone_ref(py),
        http_connection_type: runtime.http_connection_type.clone_ref(py),
        authentication_error_type: runtime.authentication_error_type.clone_ref(py),
        credentials_type: runtime.credentials_type.clone_ref(py),
        unauthenticated_user_type: runtime.unauthenticated_user_type.clone_ref(py),
    }
}

enum AuthenticationPending {
    Authenticate,
    Application,
    ErrorResponse,
    WebSocketClose,
}

struct AuthenticationMiddlewareCall {
    runtime: Py<PyAuthenticationMiddlewareRuntime>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    connection: Option<Py<PyAny>>,
    pending: Option<AuthenticationPending>,
}

impl AwaitableStateMachine for AuthenticationMiddlewareCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(AuthenticationPending::Authenticate) => self.authenticate_completed(py, value),
                Some(AuthenticationPending::Application)
                | Some(AuthenticationPending::ErrorResponse)
                | Some(AuthenticationPending::WebSocketClose) => {
                    Ok(MachineAction::Complete(py.None()))
                }
                None => Err(PyRuntimeError::new_err(
                    "authentication middleware resumed without a pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(AuthenticationPending::Authenticate)
                    if error.value(py).is_instance(
                        authentication_runtime_values(py, &self.runtime)
                            .authentication_error_type
                            .bind(py),
                    )? =>
                {
                    self.authentication_failed(py, error)
                }
                Some(_) => Err(error),
                None => Err(PyRuntimeError::new_err(
                    "authentication middleware resumed without a pending operation",
                )),
            },
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "authentication middleware resumed without a pending operation",
            )),
            MachineResume::AsyncIterationComplete(_) => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
            }
        }
    }
}

impl AuthenticationMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        let runtime = authentication_runtime_values(py, &self.runtime);
        if scope_type != "http" && scope_type != "websocket" {
            let application = runtime.app.bind(py).call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?;
            self.pending = Some(AuthenticationPending::Application);
            return Ok(MachineAction::Await(application.unbind()));
        }
        let connection = runtime
            .http_connection_type
            .bind(py)
            .call1((self.scope.bind(py),))?
            .unbind();
        self.connection = Some(connection.clone_ref(py));
        let authentication = runtime
            .backend
            .bind(py)
            .call_method1("authenticate", (connection.bind(py),));
        let authentication = match authentication {
            Ok(authentication) => authentication.unbind(),
            Err(error)
                if error
                    .value(py)
                    .is_instance(runtime.authentication_error_type.bind(py))? =>
            {
                return self.authentication_failed(py, error);
            }
            Err(error) => return Err(error),
        };
        self.pending = Some(AuthenticationPending::Authenticate);
        Ok(MachineAction::Await(authentication))
    }

    fn authenticate_completed(
        &mut self,
        py: Python<'_>,
        result: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        let runtime = authentication_runtime_values(py, &self.runtime);
        let (credentials, user) = if result.bind(py).is_none() {
            (
                runtime.credentials_type.bind(py).call0()?.unbind(),
                runtime.unauthenticated_user_type.bind(py).call0()?.unbind(),
            )
        } else {
            result.bind(py).extract::<(Py<PyAny>, Py<PyAny>)>()?
        };
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        scope.set_item("auth", credentials)?;
        scope.set_item("user", user)?;
        let application = runtime.app.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = Some(AuthenticationPending::Application);
        Ok(MachineAction::Await(application.unbind()))
    }

    fn authentication_failed(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let runtime = authentication_runtime_values(py, &self.runtime);
        let connection = self
            .connection
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("authentication middleware lost connection"))?;
        let response = runtime
            .on_error
            .bind(py)
            .call1((connection.bind(py), error.value(py)))?;
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        let operation = if scope_type == "websocket" {
            let close_message = PyDict::new(py);
            close_message.set_item("type", "websocket.close")?;
            close_message.set_item("code", 1000)?;
            self.send.bind(py).call1((close_message,))?
        } else {
            response.call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?
        };
        self.pending = Some(if scope_type == "websocket" {
            AuthenticationPending::WebSocketClose
        } else {
            AuthenticationPending::ErrorResponse
        });
        Ok(MachineAction::Await(operation.unbind()))
    }
}
