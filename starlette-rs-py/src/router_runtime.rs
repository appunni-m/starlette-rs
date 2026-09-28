//! Rust-owned route ordering, scope changes, and ASGI dispatch.

use std::cell::Cell;
use std::collections::HashMap;
use std::rc::Rc;

use pyo3::exceptions::{PyAssertionError, PyKeyError, PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString, PyTuple};
use starlette_rs::{DispatchPlanError, HttpDispatchPlan, RouteTable, SupplementalRouteMatch};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

#[path = "router_runtime/route_types_runtime.rs"]
mod route_types_runtime;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyRouterRuntime>()?;
    route_types_runtime::register(module)
}

#[derive(Clone, Copy)]
enum RouteKind {
    Http,
    WebSocket,
    Mount,
    Host,
}

struct RouteTypes {
    http: Py<PyAny>,
    websocket: Py<PyAny>,
    mount: Py<PyAny>,
    host: Py<PyAny>,
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct RouterDispatchArgs {
    routes: Py<PyAny>,
    router: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    default: Option<Py<PyAny>>,
    redirect_slashes: bool,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
    exception_handler: Option<Py<PyAny>>,
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct RouterNotFoundArgs {
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
}

struct RouterRoutes {
    routes: Vec<Py<PyAny>>,
    kinds: Vec<RouteKind>,
    http_table: RouteTable,
    http_indexes: Vec<usize>,
    custom_http_indexes: Vec<usize>,
    websocket_table: RouteTable,
    websocket_indexes: Vec<usize>,
    custom_websocket_indexes: Vec<usize>,
}

#[pyclass(name = "RouterRuntime", unsendable)]
pub(crate) struct PyRouterRuntime {
    route_types: RouteTypes,
}

#[pymethods]
impl PyRouterRuntime {
    #[new]
    fn new(
        http_route_type: Py<PyAny>,
        websocket_route_type: Py<PyAny>,
        mount_type: Py<PyAny>,
        host_type: Py<PyAny>,
    ) -> Self {
        Self {
            route_types: RouteTypes {
                http: http_route_type,
                websocket: websocket_route_type,
                mount: mount_type,
                host: host_type,
            },
        }
    }

    fn dispatch(&self, py: Python<'_>, args: RouterDispatchArgs) -> PyResult<Py<PyAny>> {
        let RouterDispatchArgs {
            routes,
            router,
            scope,
            receive,
            send,
            default,
            redirect_slashes,
            url_type,
            redirect_response_type,
            http_exception_type,
            plain_text_response_type,
            websocket_close_type,
            exception_handler,
        } = args;
        into_python_awaitable(
            py,
            RouterDispatchMachine {
                route_types: RouteTypes {
                    http: self.route_types.http.clone_ref(py),
                    websocket: self.route_types.websocket.clone_ref(py),
                    mount: self.route_types.mount.clone_ref(py),
                    host: self.route_types.host.clone_ref(py),
                },
                routes_source: routes,
                router,
                scope,
                receive,
                send,
                default,
                redirect_slashes,
                url_type,
                redirect_response_type,
                http_exception_type,
                plain_text_response_type,
                websocket_close_type,
                exception_handler,
                pending: None,
            },
        )
    }

    fn not_found(&self, py: Python<'_>, args: RouterNotFoundArgs) -> PyResult<Py<PyAny>> {
        let RouterNotFoundArgs {
            scope,
            receive,
            send,
            http_exception_type,
            plain_text_response_type,
            websocket_close_type,
        } = args;
        into_python_awaitable(
            py,
            NotFoundMachine {
                scope,
                receive,
                send,
                http_exception_type,
                plain_text_response_type,
                websocket_close_type,
                pending: false,
            },
        )
    }

    fn url_path_for(
        &self,
        py: Python<'_>,
        routes: &Bound<'_, PyAny>,
        name: &str,
        path_params: &Bound<'_, PyDict>,
        no_match_type: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        for route in routes.try_iter()? {
            let route = route?;
            let method = route.getattr("url_path_for")?;
            match method.call((name,), Some(path_params)) {
                Ok(path) => return Ok(path.unbind()),
                Err(error) if error.value(py).is_instance(no_match_type)? => {}
                Err(error) => return Err(error),
            }
        }
        Err(PyErr::from_value(no_match_type.call1((name, path_params))?))
    }
}

impl RouteTypes {
    fn build_routes(&self, py: Python<'_>, source: &Bound<'_, PyAny>) -> PyResult<RouterRoutes> {
        let mut state = RouterRoutes {
            routes: Vec::new(),
            kinds: Vec::new(),
            http_table: RouteTable::new(),
            http_indexes: Vec::new(),
            custom_http_indexes: Vec::new(),
            websocket_table: RouteTable::new(),
            websocket_indexes: Vec::new(),
            custom_websocket_indexes: Vec::new(),
        };

        for route in source.try_iter()? {
            self.register_route(py, &mut state, route?)?;
        }
        Ok(state)
    }

    fn register_route(
        &self,
        py: Python<'_>,
        state: &mut RouterRoutes,
        route: Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let kind = if route.is_instance(self.mount.bind(py))? {
            RouteKind::Mount
        } else if route.is_instance(self.host.bind(py))? {
            RouteKind::Host
        } else if route.is_instance(self.websocket.bind(py))? {
            RouteKind::WebSocket
        } else if route.is_instance(self.http.bind(py))? {
            RouteKind::Http
        } else {
            return Err(PyTypeError::new_err(
                "routes must contain Route, WebSocketRoute, Mount, or Host instances",
            ));
        };

        let path_attribute = if matches!(kind, RouteKind::Host) {
            "host"
        } else {
            "path"
        };
        let path = route.getattr(path_attribute)?.extract::<String>()?;
        let custom = route
            .getattr("_uses_custom_convertors")?
            .extract::<bool>()?;
        let route_index = state.routes.len();

        match kind {
            RouteKind::Http if custom => state.custom_http_indexes.push(route_index),
            RouteKind::Http => {
                state
                    .http_table
                    .add_route(path, route_methods(&route)?)
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                state.http_indexes.push(route_index);
            }
            RouteKind::WebSocket if custom => {
                state.custom_websocket_indexes.push(route_index);
            }
            RouteKind::WebSocket => {
                state
                    .websocket_table
                    .add_route(path, ["GET"])
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                state.websocket_indexes.push(route_index);
            }
            RouteKind::Mount if custom => {
                state.custom_http_indexes.push(route_index);
                state.custom_websocket_indexes.push(route_index);
            }
            RouteKind::Host => {
                state.custom_http_indexes.push(route_index);
                state.custom_websocket_indexes.push(route_index);
            }
            RouteKind::Mount => {
                let mount_path = format!("{path}/{{path:path}}");
                state
                    .http_table
                    .add_route(mount_path.clone(), std::iter::empty::<&str>())
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                state.http_indexes.push(route_index);
                state
                    .websocket_table
                    .add_route(mount_path, std::iter::empty::<&str>())
                    .map_err(|error| PyValueError::new_err(error.to_string()))?;
                state.websocket_indexes.push(route_index);
            }
        }

        state.kinds.push(kind);
        state.routes.push(route.unbind());
        Ok(())
    }
}

struct RouterDispatchMachine {
    route_types: RouteTypes,
    routes_source: Py<PyAny>,
    router: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    default: Option<Py<PyAny>>,
    redirect_slashes: bool,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
    exception_handler: Option<Py<PyAny>>,
    pending: Option<RouterPending>,
}

enum RouterPending {
    Route(Option<Rc<Cell<bool>>>),
    Callback,
}

impl AwaitableStateMachine for RouterDispatchMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if self.pending.is_some() {
                    return Err(PyRuntimeError::new_err(
                        "router dispatch already has an operation pending",
                    ));
                }
                let callback = self.start_dispatch(py)?;
                Ok(MachineAction::Await(callback))
            }
            MachineResume::Value(_) if self.pending.take().is_some() => {
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) => match self.pending.take() {
                Some(RouterPending::Route(response_started)) => {
                    self.handle_route_error(py, error, response_started)
                }
                Some(RouterPending::Callback) => Err(error),
                None => Err(PyRuntimeError::new_err(
                    "router dispatch resumed without a pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
            }
            _ => Err(PyRuntimeError::new_err(
                "router dispatch resumed without a pending operation",
            )),
        }
    }
}

impl RouterDispatchMachine {
    fn start_dispatch(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let scope_dict = self.scope.bind(py).cast::<PyDict>()?;
        let scope_type = required_scope_value(scope_dict, "type")?.extract::<String>()?;
        if !matches!(scope_type.as_str(), "http" | "websocket" | "lifespan") {
            return Err(PyAssertionError::new_err(()));
        }
        scope_dict.call_method1("setdefault", ("router", self.router.clone_ref(py)))?;
        if scope_type == "lifespan" {
            self.pending = Some(RouterPending::Callback);
            return self
                .router
                .bind(py)
                .call_method1("lifespan", (scope_dict, &self.receive, &self.send))
                .map(Bound::unbind);
        }

        let routes = self
            .route_types
            .build_routes(py, self.routes_source.bind(py))?;
        let (plan, custom_child_scopes) = if scope_type == "http" {
            self.http_plan(py, scope_dict, &routes)?
        } else {
            self.websocket_plan(py, scope_dict, &routes)?
        };

        match plan {
            HttpDispatchPlan::Matched {
                route_index,
                path_params,
            }
            | HttpDispatchPlan::MethodNotAllowed {
                route_index,
                path_params,
                ..
            } => {
                let route = routes.routes.get(route_index).ok_or_else(|| {
                    PyRuntimeError::new_err(format!(
                        "router selected missing route index {route_index}"
                    ))
                })?;
                let child_scope = match custom_child_scopes.get(&route_index) {
                    Some(child_scope) => child_scope.clone_ref(py),
                    None => native_child_scope(
                        py,
                        routes.kinds[route_index],
                        route.bind(py),
                        scope_dict,
                        &path_params,
                    )?,
                };
                scope_dict.call_method1("update", (child_scope,))?;
                let (route_send, response_started) = if self.exception_handler.is_some() {
                    let response_started = Rc::new(Cell::new(false));
                    let tracker = Py::new(
                        py,
                        PyResponseStartTracker {
                            send: self.send.clone_ref(py),
                            response_started: response_started.clone(),
                        },
                    )?;
                    (tracker.into_any(), Some(response_started))
                } else {
                    (self.send.clone_ref(py), None)
                };
                self.pending = Some(RouterPending::Route(response_started));
                route
                    .bind(py)
                    .call_method1(
                        "handle",
                        (self.scope.clone_ref(py), &self.receive, route_send),
                    )
                    .map(Bound::unbind)
            }
            HttpDispatchPlan::Redirect { path } => {
                let redirect_scope = scope_dict.copy()?;
                redirect_scope.set_item("path", path)?;
                let url_kwargs = PyDict::new(py);
                url_kwargs.set_item("scope", &redirect_scope)?;
                let url = self.url_type.bind(py).call((), Some(&url_kwargs))?;
                let url = py.import("builtins")?.getattr("str")?.call1((url,))?;
                let response = self.redirect_response_type.bind(py).call1((url,))?;
                self.pending = Some(RouterPending::Callback);
                response
                    .call1((self.scope.clone_ref(py), &self.receive, &self.send))
                    .map(Bound::unbind)
            }
            HttpDispatchPlan::NotFound => match (&self.default, &self.exception_handler) {
                (Some(default), _) => {
                    let callback = default.bind(py).call1((
                        self.scope.clone_ref(py),
                        &self.receive,
                        &self.send,
                    ))?;
                    self.pending = Some(RouterPending::Callback);
                    Ok(callback.unbind())
                }
                (None, Some(handler)) => {
                    let exception = self.http_exception_type.bind(py).call1((404,))?;
                    self.pending = Some(RouterPending::Callback);
                    handler
                        .bind(py)
                        .call1((
                            self.scope.clone_ref(py),
                            &self.receive,
                            &self.send,
                            exception,
                        ))
                        .map(Bound::unbind)
                }
                (None, None) => {
                    let callback = not_found_callback(
                        py,
                        self.scope.bind(py),
                        self.receive.bind(py),
                        self.send.bind(py),
                        self.http_exception_type.bind(py),
                        self.plain_text_response_type.bind(py),
                        self.websocket_close_type.bind(py),
                    )?;
                    self.pending = Some(RouterPending::Callback);
                    Ok(callback)
                }
            },
        }
    }

    fn handle_route_error(
        &mut self,
        py: Python<'_>,
        error: PyErr,
        response_started: Option<Rc<Cell<bool>>>,
    ) -> PyResult<MachineAction> {
        let Some(handler) = self.exception_handler.as_ref() else {
            return Err(error);
        };
        let error_value = error.value(py);
        if !error_value.is_instance(self.http_exception_type.bind(py))? {
            return Err(error);
        }
        if response_started.is_some_and(|state| state.get()) {
            let runtime_error =
                PyRuntimeError::new_err("Caught handled exception, but response already started.");
            runtime_error.set_cause(py, Some(error));
            return Err(runtime_error);
        }
        let callback = handler.bind(py).call1((
            self.scope.clone_ref(py),
            self.receive.clone_ref(py),
            self.send.clone_ref(py),
            error_value,
        ))?;
        self.pending = Some(RouterPending::Callback);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn http_plan(
        &self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        routes: &RouterRoutes,
    ) -> PyResult<(HttpDispatchPlan, HashMap<usize, Py<PyAny>>)> {
        let path = required_scope_value(scope, "path")?.extract::<String>()?;
        let root_path = optional_scope_string(scope, "root_path", "")?;
        let method = required_scope_value(scope, "method")?.extract::<String>()?;
        let mut child_scopes = HashMap::new();
        let mut callback_error = None;

        let plan = routes
            .http_table
            .dispatch_plan_with_candidates(
                &path,
                &root_path,
                &method,
                &routes.http_indexes,
                self.redirect_slashes,
                |candidate_path, native_full_index| match supplemental_matches(
                    SupplementalMatchArgs {
                        py,
                        scope,
                        current_path: &path,
                        candidate_path,
                        routes: &routes.routes,
                        route_indexes: &routes.custom_http_indexes,
                        native_full_index,
                        child_scopes: &mut child_scopes,
                        websocket: false,
                    },
                ) {
                    Ok(matches) => matches,
                    Err(error) => {
                        callback_error = Some(error);
                        Vec::new()
                    }
                },
            )
            .map_err(dispatch_plan_error)?;

        if let Some(error) = callback_error {
            return Err(error);
        }
        Ok((plan, child_scopes))
    }

    fn websocket_plan(
        &self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        routes: &RouterRoutes,
    ) -> PyResult<(HttpDispatchPlan, HashMap<usize, Py<PyAny>>)> {
        let path = required_scope_value(scope, "path")?.extract::<String>()?;
        let root_path = optional_scope_string(scope, "root_path", "")?;
        let mut child_scopes = HashMap::new();
        let mut callback_error = None;

        let plan = routes
            .websocket_table
            .dispatch_plan_with_candidates(
                &path,
                &root_path,
                "GET",
                &routes.websocket_indexes,
                false,
                |candidate_path, native_full_index| match supplemental_matches(
                    SupplementalMatchArgs {
                        py,
                        scope,
                        current_path: &path,
                        candidate_path,
                        routes: &routes.routes,
                        route_indexes: &routes.custom_websocket_indexes,
                        native_full_index,
                        child_scopes: &mut child_scopes,
                        websocket: true,
                    },
                ) {
                    Ok(matches) => matches,
                    Err(error) => {
                        callback_error = Some(error);
                        Vec::new()
                    }
                },
            )
            .map_err(dispatch_plan_error)?;

        if let Some(error) = callback_error {
            return Err(error);
        }
        Ok((plan, child_scopes))
    }
}

struct NotFoundMachine {
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for NotFoundMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                let scope = self.scope.bind(py).cast::<PyDict>()?;
                let callback = not_found_callback(
                    py,
                    scope.as_any(),
                    self.receive.bind(py),
                    self.send.bind(py),
                    self.http_exception_type.bind(py),
                    self.plain_text_response_type.bind(py),
                    self.websocket_close_type.bind(py),
                )?;
                self.pending = true;
                Ok(MachineAction::Await(callback))
            }
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
            }
            _ => Err(PyRuntimeError::new_err(
                "not-found dispatch resumed without a pending operation",
            )),
        }
    }
}

fn not_found_callback(
    py: Python<'_>,
    scope: &Bound<'_, PyAny>,
    receive: &Bound<'_, PyAny>,
    send: &Bound<'_, PyAny>,
    http_exception_type: &Bound<'_, PyAny>,
    plain_text_response_type: &Bound<'_, PyAny>,
    websocket_close_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let scope_dict = scope.cast::<PyDict>()?;
    let scope_type = required_scope_value(scope_dict, "type")?.extract::<String>()?;
    let callback = if scope_type == "websocket" {
        websocket_close_type
            .call0()?
            .call1((scope, receive, send))?
    } else if scope_dict.get_item("app")?.is_some() {
        return Err(PyErr::from_value(http_exception_type.call1((404,))?));
    } else {
        let kwargs = PyDict::new(py);
        kwargs.set_item("status_code", 404)?;
        plain_text_response_type
            .call(("Not Found",), Some(&kwargs))?
            .call1((scope, receive, send))?
    };
    Ok(callback.unbind())
}

#[pyclass(unsendable)]
struct PyResponseStartTracker {
    send: Py<PyAny>,
    response_started: Rc<Cell<bool>>,
}

#[pymethods]
impl PyResponseStartTracker {
    fn __call__(&self, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let message = message.bind(py);
        let message_type =
            required_scope_value(message.cast::<PyDict>()?, "type")?.extract::<String>()?;
        if message_type == "http.response.start" {
            self.response_started.set(true);
        }
        self.send.bind(py).call1((message,)).map(Bound::unbind)
    }
}

fn route_methods(route: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
    let methods = route.getattr("methods")?;
    if methods.is_none() {
        return Ok(Vec::new());
    }
    methods
        .try_iter()?
        .map(|method| method?.extract::<String>())
        .collect()
}

struct SupplementalMatchArgs<'a, 'py> {
    py: Python<'py>,
    scope: &'a Bound<'py, PyDict>,
    current_path: &'a str,
    candidate_path: &'a str,
    routes: &'a [Py<PyAny>],
    route_indexes: &'a [usize],
    native_full_index: Option<usize>,
    child_scopes: &'a mut HashMap<usize, Py<PyAny>>,
    websocket: bool,
}

fn supplemental_matches(
    args: SupplementalMatchArgs<'_, '_>,
) -> PyResult<Vec<SupplementalRouteMatch>> {
    let SupplementalMatchArgs {
        py,
        scope,
        current_path,
        candidate_path,
        routes,
        route_indexes,
        native_full_index,
        child_scopes,
        websocket,
    } = args;
    let candidate_scope = if candidate_path == current_path {
        scope.clone().into_any()
    } else {
        let candidate_scope = scope.copy()?.into_any();
        candidate_scope.set_item("path", candidate_path)?;
        candidate_scope
    };
    let mut matches = Vec::new();

    for &route_index in route_indexes {
        if native_full_index.is_some_and(|full_index| route_index > full_index) {
            break;
        }
        let Some(route) = routes.get(route_index) else {
            return Err(PyRuntimeError::new_err(format!(
                "router custom route index {route_index} is out of bounds"
            )));
        };
        let route_match = route
            .bind(py)
            .call_method1("matches", (candidate_scope.clone(),))?;
        let route_match = route_match.cast::<PyTuple>()?;
        let match_kind = route_match.get_item(0)?.getattr("value")?.extract::<u8>()?;
        let child_scope = route_match.get_item(1)?;
        match match_kind {
            2 => {
                child_scopes.insert(route_index, child_scope.unbind());
                matches.push(SupplementalRouteMatch::Matched { route_index });
                break;
            }
            1 if !websocket => {
                child_scopes.insert(route_index, child_scope.unbind());
                matches.push(SupplementalRouteMatch::MethodNotAllowed {
                    route_index,
                    allowed_methods: route_methods(route.bind(py))?,
                });
            }
            _ => {}
        }
    }

    Ok(matches)
}

fn native_child_scope(
    py: Python<'_>,
    kind: RouteKind,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    raw_path_params: &[(String, String)],
) -> PyResult<Py<PyAny>> {
    let path_params = converted_path_params(py, route, scope, raw_path_params)?;
    let child_scope = PyDict::new(py);

    match kind {
        RouteKind::Mount => {
            let route_path = scope_route_path(scope)?;
            let remainder = path_params
                .bind(py)
                .get_item("path")?
                .ok_or_else(|| PyRuntimeError::new_err("native mount match omitted path"))?
                .extract::<String>()?;
            path_params.bind(py).del_item("path")?;
            let remaining_path = format!("/{remainder}");
            let remaining_characters = remaining_path.chars().count();
            let route_character_count = route_path.chars().count();
            let matched_path = route_path
                .chars()
                .take(route_character_count.saturating_sub(remaining_characters))
                .collect::<String>();
            let root_path = optional_scope_string(scope, "root_path", "")?;
            let app_root_path = scope
                .get_item("app_root_path")?
                .unwrap_or_else(|| PyString::new(py, &root_path).into_any());
            child_scope.set_item("path_params", path_params.bind(py))?;
            child_scope.set_item("app_root_path", app_root_path)?;
            child_scope.set_item("root_path", format!("{root_path}{matched_path}"))?;
            child_scope.set_item("endpoint", route.getattr("app")?)?;
        }
        RouteKind::Http | RouteKind::WebSocket => {
            child_scope.set_item("endpoint", route.getattr("endpoint")?)?;
            child_scope.set_item("path_params", path_params.bind(py))?;
        }
        RouteKind::Host => return route_types_runtime::host_child_scope(py, route, scope),
    }

    Ok(child_scope.into_any().unbind())
}

fn converted_path_params(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    raw_path_params: &[(String, String)],
) -> PyResult<Py<PyDict>> {
    let path_params = PyDict::new(py);
    if let Some(existing) = scope.get_item("path_params")? {
        path_params.call_method1("update", (existing,))?;
    }
    let convertors = route.getattr("param_convertors")?;
    for (name, value) in raw_path_params {
        let convertor = convertors.get_item(name)?;
        let converted = convertor.call_method1("convert", (value,))?;
        path_params.set_item(name, converted)?;
    }
    Ok(path_params.unbind())
}

fn scope_route_path(scope: &Bound<'_, PyDict>) -> PyResult<String> {
    let path = required_scope_value(scope, "path")?.extract::<String>()?;
    let root_path = optional_scope_string(scope, "root_path", "")?;
    if root_path.is_empty() || !path.starts_with(&root_path) {
        return Ok(path);
    }
    if path == root_path {
        return Ok(String::new());
    }
    let remaining = &path[root_path.len()..];
    if remaining.starts_with('/') {
        Ok(remaining.to_owned())
    } else {
        Ok(path)
    }
}

fn required_scope_value<'py>(
    scope: &Bound<'py, PyDict>,
    name: &'static str,
) -> PyResult<Bound<'py, PyAny>> {
    scope
        .get_item(name)?
        .ok_or_else(|| PyKeyError::new_err(name))
}

fn optional_scope_string(scope: &Bound<'_, PyDict>, name: &str, default: &str) -> PyResult<String> {
    scope
        .get_item(name)?
        .map_or_else(|| Ok(default.to_owned()), |value| value.extract::<String>())
}

fn dispatch_plan_error(error: DispatchPlanError) -> PyErr {
    PyValueError::new_err(error.to_string())
}
