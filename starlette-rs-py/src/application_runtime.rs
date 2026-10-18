//! Rust-owned Starlette application middleware composition and exception flow.
//!
//! Python objects remain at the compatibility boundary for public middleware
//! constructors, ASGI callables, request/response facades, and exception values.
//! Rust owns middleware order, application startup dispatch, exception-handler
//! lookup, response-start tracking, and the order in which callbacks are run.

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use pyo3::class::basic::CompareOp;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAssertionError, PyException, PyRuntimeError, PyStopAsyncIteration, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt, PyList, PyModule, PySet, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use crate::middleware_config_runtime::middleware_kwargs_to_dict;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyStarletteRuntime>()?;
    module.add_class::<PyExceptionMiddlewareRuntime>()?;
    module.add_class::<PyExceptionSendProxy>()?;
    Ok(())
}

/// Owns mutable Starlette app configuration and creates the ASGI middleware stack.
///
/// This stores only Python handles and accesses them under the GIL. TestClient
/// invokes the ASGI app on its portal thread, which may differ from the thread
/// that constructed the Starlette application.
#[pyclass(name = "StarletteRuntime")]
pub(crate) struct PyStarletteRuntime {
    app: Py<PyAny>,
    middleware_type: Py<PyAny>,
    server_error_middleware_type: Py<PyAny>,
    exception_middleware_type: Py<PyAny>,
}

#[pymethods]
impl PyStarletteRuntime {
    #[new]
    fn new(
        py: Python<'_>,
        app: Py<PyAny>,
        middleware: Option<Py<PyAny>>,
        exception_handlers: Option<Py<PyAny>>,
        middleware_type: Py<PyAny>,
        server_error_middleware_type: Py<PyAny>,
        exception_middleware_type: Py<PyAny>,
    ) -> PyResult<Self> {
        // Match Starlette's constructor evaluation order: converting a user
        // Mapping or Sequence can run Python code and observe which conversion
        // happens first.
        let exception_handlers = match exception_handlers {
            Some(handlers) => py
                .import("builtins")?
                .getattr("dict")?
                .call1((handlers,))?
                .unbind(),
            None => PyDict::new(py).into_any().unbind(),
        };
        app.bind(py)
            .setattr("exception_handlers", exception_handlers)?;

        let middleware = match middleware {
            Some(middleware) => py
                .import("builtins")?
                .getattr("list")?
                .call1((middleware,))?
                .unbind(),
            None => PyList::empty(py).into_any().unbind(),
        };

        app.bind(py).setattr("user_middleware", middleware)?;
        app.bind(py).setattr("middleware_stack", py.None())?;

        Ok(Self {
            app,
            middleware_type,
            server_error_middleware_type,
            exception_middleware_type,
        })
    }

    /// Build the middleware graph without caching it on the application.
    fn build_middleware_stack(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.build_stack(py)
    }

    /// Insert user middleware at the front of Starlette's user middleware list.
    #[pyo3(signature = (middleware_class, args, kwargs))]
    fn add_middleware(
        &self,
        py: Python<'_>,
        middleware_class: Py<PyAny>,
        args: Py<PyAny>,
        kwargs: Py<PyAny>,
    ) -> PyResult<()> {
        let app = self.app.bind(py);
        if !app.getattr("middleware_stack")?.is_none() {
            return Err(PyRuntimeError::new_err(
                "Cannot add middleware after an application has started",
            ));
        }

        let args = args.bind(py).cast::<PyTuple>()?;
        let kwargs = kwargs.bind(py).cast::<PyDict>()?;
        let config = make_middleware_config(
            py,
            self.middleware_type.bind(py),
            middleware_class.bind(py),
            args,
            kwargs,
        )?;
        app.getattr("user_middleware")?
            .call_method1("insert", (0, config))?;
        Ok(())
    }

    /// Add or replace one configured exception handler.
    fn add_exception_handler(
        &self,
        py: Python<'_>,
        key: Py<PyAny>,
        handler: Py<PyAny>,
    ) -> PyResult<()> {
        self.app
            .bind(py)
            .getattr("exception_handlers")?
            .set_item(key.bind(py), handler.bind(py))
    }

    /// Return the app's current cached stack, or `None` before first dispatch.
    #[getter]
    fn middleware_stack(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.app
            .bind(py)
            .getattr("middleware_stack")
            .map(Bound::unbind)
    }

    /// Replace the public cache value while preserving Starlette's mutation API.
    #[setter]
    fn set_middleware_stack(&self, py: Python<'_>, value: Py<PyAny>) -> PyResult<()> {
        self.app.bind(py).setattr("middleware_stack", value)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.app)?;
        visit.call(&self.middleware_type)?;
        visit.call(&self.server_error_middleware_type)?;
        visit.call(&self.exception_middleware_type)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.app = py.None();
        self.middleware_type = py.None();
        self.server_error_middleware_type = py.None();
        self.exception_middleware_type = py.None();
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
            StarletteCall {
                runtime: slf,
                scope,
                receive,
                send,
                pending: false,
            },
        )
    }
}

impl PyStarletteRuntime {
    fn build_stack(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let app = self.app.bind(py);
        // Preserve Starlette's source-order attribute reads. Subclasses may
        // expose descriptors or override __getattribute__, making each read
        // observable and allowing successive max_body_size reads to differ.
        let debug = app.getattr("debug")?;
        let handlers = app.getattr("exception_handlers")?;
        let user_exception_handlers = PyDict::new(py);
        let mut server_error_handler: Option<Py<PyAny>> = None;
        let exception_type = py.get_type::<PyException>();

        for entry in handlers.call_method0("items")?.try_iter()? {
            let pair = entry?.cast_into::<PyTuple>()?;
            let key = pair.get_item(0)?;
            let value = pair.get_item(1)?;
            // Match tuple membership in Starlette's `key in (500, Exception)`:
            // an Exception subclass may define a metaclass equality override.
            if key.eq(500)? || key.eq(&exception_type)? {
                server_error_handler = Some(value.unbind());
            } else {
                user_exception_handlers.set_item(key, value)?;
            }
        }

        let mut middleware_configs = Vec::<Py<PyAny>>::new();
        let error_kwargs = PyDict::new(py);
        error_kwargs.set_item("handler", server_error_handler)?;
        error_kwargs.set_item("debug", &debug)?;
        middleware_configs.push(
            make_middleware_config(
                py,
                self.middleware_type.bind(py),
                self.server_error_middleware_type.bind(py),
                &PyTuple::empty(py),
                &error_kwargs,
            )?
            .unbind(),
        );

        let max_body_size = app.getattr("max_body_size")?;
        if !max_body_size.is_none() {
            let body_limit_type = py
                .import("starlette.middleware.body_limit")?
                .getattr("RequestBodyLimitMiddleware")?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("max_body_size", app.getattr("max_body_size")?)?;
            middleware_configs.push(
                make_middleware_config(
                    py,
                    self.middleware_type.bind(py),
                    &body_limit_type,
                    &PyTuple::empty(py),
                    &kwargs,
                )?
                .unbind(),
            );
        }

        // Starlette appends `user_middleware` to a local list, so the public
        // attribute may be any iterable when the stack is built.
        let middleware = app.getattr("user_middleware")?;
        middleware_configs.extend(
            middleware
                .try_iter()?
                .map(|item| item.map(Bound::unbind))
                .collect::<PyResult<Vec<_>>>()?,
        );

        let exception_kwargs = PyDict::new(py);
        exception_kwargs.set_item("handlers", user_exception_handlers)?;
        exception_kwargs.set_item("debug", &debug)?;
        middleware_configs.push(
            make_middleware_config(
                py,
                self.middleware_type.bind(py),
                self.exception_middleware_type.bind(py),
                &PyTuple::empty(py),
                &exception_kwargs,
            )?
            .unbind(),
        );

        let router = app.getattr("router")?;
        let mut asgi_app = router.unbind();
        for config in middleware_configs.into_iter().rev() {
            let config = config.bind(py);
            // Python's tuple-unpacking call in Starlette must dynamically invoke a
            // Middleware subclass's `__iter__`; reading `cls`/`args`/`kwargs`
            // directly skips that public special-method override.
            let values = collect_iterable(config, Some(4))?;
            if values.len() != 3 {
                let message = if values.len() < 3 {
                    format!(
                        "not enough values to unpack (expected 3, got {})",
                        values.len()
                    )
                } else {
                    String::from("too many values to unpack (expected 3)")
                };
                return Err(PyValueError::new_err(message));
            }
            let mut values = values.into_iter();
            let middleware_class = values.next().ok_or_else(|| {
                PyRuntimeError::new_err("middleware iterator omitted its factory")
            })?;
            let args = values
                .next()
                .ok_or_else(|| PyRuntimeError::new_err("middleware iterator omitted args"))?;
            let kwargs = values
                .next()
                .ok_or_else(|| PyRuntimeError::new_err("middleware iterator omitted kwargs"))?;
            let mut positional = Vec::with_capacity(1);
            positional.push(asgi_app);
            positional.extend(collect_iterable(args.bind(py), None)?);
            let call_args = PyTuple::new(py, positional)?;
            let call_kwargs =
                middleware_kwargs_to_dict(py, kwargs.bind(py), middleware_class.bind(py))?;
            asgi_app = middleware_class
                .bind(py)
                .call(&call_args, Some(&call_kwargs))?
                .unbind();
        }
        Ok(asgi_app)
    }
}

/// Consume an iterable through its Python protocol, optionally stopping after a limit.
fn collect_iterable(iterable: &Bound<'_, PyAny>, limit: Option<usize>) -> PyResult<Vec<Py<PyAny>>> {
    let mut iterator = iterable.try_iter()?;
    let mut values = Vec::new();
    while match limit {
        Some(limit) => values.len() < limit,
        None => true,
    } {
        match iterator.next() {
            Some(value) => values.push(value?.unbind()),
            None => break,
        }
    }
    Ok(values)
}

/// Materialize Python's `**mapping` expansion as keyword arguments.
fn make_middleware_config<'py>(
    py: Python<'py>,
    middleware_type: &Bound<'py, PyAny>,
    middleware_class: &Bound<'py, PyAny>,
    args: &Bound<'py, PyTuple>,
    kwargs: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyAny>> {
    let positional_capacity = args.len().checked_add(1).ok_or_else(|| {
        pyo3::exceptions::PyOverflowError::new_err("middleware argument count overflow")
    })?;
    let mut positional = Vec::new();
    positional
        .try_reserve_exact(positional_capacity)
        .map_err(|_| {
            pyo3::exceptions::PyMemoryError::new_err("could not allocate middleware arguments")
        })?;
    positional.push(middleware_class.clone().unbind());
    positional.extend(args.iter().map(Bound::unbind));
    let positional = PyTuple::new(py, positional)?;
    middleware_type.call(&positional, Some(kwargs))
}

struct StarletteCall {
    runtime: Py<PyStarletteRuntime>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for StarletteCall {
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
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => {
                Err(PyRuntimeError::new_err(
                    "Starlette application continuation has no pending ASGI call",
                ))
            }
        }
    }
}

impl StarletteCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let runtime = self.runtime.borrow(py);
        let app = runtime.app.bind(py);
        let scope = self.scope.bind(py);
        scope.set_item("app", app)?;
        let mut stack = app.getattr("middleware_stack")?;
        if stack.is_none() {
            // Subclasses may override this Python construction hook; Rust owns
            // the lazy selection and cache while preserving that callback.
            stack = app.call_method0("build_middleware_stack")?;
            app.setattr("middleware_stack", &stack)?;
        }
        let call = stack.call1((scope, self.receive.bind(py), self.send.bind(py)))?;
        self.pending = true;
        Ok(MachineAction::Await(call.unbind()))
    }
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct ExceptionMiddlewareArgs {
    handlers: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    websocket_exception_type: Py<PyAny>,
    http_builtin_handler: Py<PyAny>,
    websocket_builtin_handler: Py<PyAny>,
    response_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
}

/// Rust runtime behind Starlette's public `ExceptionMiddleware` facade.
///
/// Middleware instances are cached on the application stack and can be called
/// by different TestClient portal threads; Python handles are accessed under
/// the GIL and routing metadata is Rust-owned.
#[pyclass(name = "ExceptionMiddlewareRuntime")]
pub(crate) struct PyExceptionMiddlewareRuntime {
    exception_handlers: Py<PyDict>,
    status_handlers: Py<PyDict>,
    http_exception_type: Py<PyAny>,
    websocket_exception_type: Py<PyAny>,
    response_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    http_builtin_handler: Py<PyAny>,
    websocket_builtin_handler: Py<PyAny>,
}

#[pymethods]
impl PyExceptionMiddlewareRuntime {
    #[new]
    fn new(py: Python<'_>, args: ExceptionMiddlewareArgs) -> PyResult<Self> {
        let ExceptionMiddlewareArgs {
            handlers,
            http_exception_type,
            websocket_exception_type,
            http_builtin_handler,
            websocket_builtin_handler,
            response_type,
            plain_text_response_type,
        } = args;
        let mut runtime = Self {
            exception_handlers: PyDict::new(py).unbind(),
            status_handlers: PyDict::new(py).unbind(),
            http_exception_type,
            websocket_exception_type,
            response_type,
            plain_text_response_type,
            http_builtin_handler,
            websocket_builtin_handler,
        };

        runtime.register_handler(
            py,
            runtime.http_exception_type.clone_ref(py),
            runtime.http_builtin_handler.clone_ref(py),
        )?;
        runtime.register_handler(
            py,
            runtime.websocket_exception_type.clone_ref(py),
            runtime.websocket_builtin_handler.clone_ref(py),
        )?;

        if !handlers.bind(py).is_none() {
            for entry in handlers.bind(py).call_method0("items")?.try_iter()? {
                let pair = entry?.cast_into::<PyTuple>()?;
                runtime.register_handler(
                    py,
                    pair.get_item(0)?.unbind(),
                    pair.get_item(1)?.unbind(),
                )?;
            }
        }
        Ok(runtime)
    }

    fn __call__(
        slf: Py<Self>,
        py: Python<'_>,
        middleware: Py<PyAny>,
        scope: Py<PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let runtime = slf.borrow(py);
        into_sendable_python_awaitable(
            py,
            ExceptionMiddlewareCall {
                middleware,
                exception_handlers: runtime.exception_handlers.clone_ref(py),
                status_handlers: runtime.status_handlers.clone_ref(py),
                http_exception_type: runtime.http_exception_type.clone_ref(py),
                request_type: py
                    .import("starlette.requests")?
                    .getattr("Request")?
                    .unbind(),
                websocket_type: py
                    .import("starlette.websockets")?
                    .getattr("WebSocket")?
                    .unbind(),
                scope,
                receive,
                send,
                sender: None,
                connection: None,
                response_started: Arc::new(AtomicBool::new(false)),
                pending: None,
                original_exception: None,
            },
        )
    }

    fn add_exception_handler(
        &mut self,
        py: Python<'_>,
        key: Py<PyAny>,
        handler: Py<PyAny>,
    ) -> PyResult<()> {
        self.register_handler(py, key, handler)
    }

    fn http_exception(
        &self,
        py: Python<'_>,
        _request: Py<PyAny>,
        exception: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let exception = exception.bind(py);
        if !exception.is_instance(self.http_exception_type.bind(py))? {
            return Err(PyAssertionError::new_err(()));
        }
        // Keep the original Python values and source evaluation order: status
        // membership may run user hashing, and rendering owns detail/header
        // conversion. An explicit HTTPException status is not limited to u16.
        let status_code_for_membership = exception.getattr("status_code")?;
        let bodyless = PySet::new(py, [204, 304])?.contains(status_code_for_membership)?;
        let kwargs = PyDict::new(py);
        if bodyless {
            kwargs.set_item("status_code", exception.getattr("status_code")?)?;
            kwargs.set_item("headers", exception.getattr("headers")?)?;
            self.response_type
                .bind(py)
                .call((), Some(&kwargs))
                .map(Bound::unbind)
        } else {
            let detail = exception.getattr("detail")?;
            kwargs.set_item("status_code", exception.getattr("status_code")?)?;
            kwargs.set_item("headers", exception.getattr("headers")?)?;
            self.plain_text_response_type
                .bind(py)
                .call((detail,), Some(&kwargs))
                .map(Bound::unbind)
        }
    }

    fn websocket_exception(
        &self,
        py: Python<'_>,
        websocket: Py<PyAny>,
        exception: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let exception = exception.bind(py);
        if !exception.is_instance(self.websocket_exception_type.bind(py))? {
            return Err(PyAssertionError::new_err(()));
        }
        let kwargs = PyDict::new(py);
        kwargs.set_item("code", exception.getattr("code")?)?;
        kwargs.set_item("reason", exception.getattr("reason")?)?;
        websocket
            .bind(py)
            .call_method("close", (), Some(&kwargs))
            .map(Bound::unbind)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.exception_handlers)?;
        visit.call(&self.status_handlers)?;
        visit.call(&self.http_exception_type)?;
        visit.call(&self.websocket_exception_type)?;
        visit.call(&self.response_type)?;
        visit.call(&self.plain_text_response_type)?;
        visit.call(&self.http_builtin_handler)?;
        visit.call(&self.websocket_builtin_handler)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.exception_handlers.bind(py).clear();
        self.status_handlers.bind(py).clear();
        self.http_exception_type = py.None();
        self.websocket_exception_type = py.None();
        self.response_type = py.None();
        self.plain_text_response_type = py.None();
        self.http_builtin_handler = py.None();
        self.websocket_builtin_handler = py.None();
    }
}

impl PyExceptionMiddlewareRuntime {
    fn register_handler(
        &mut self,
        py: Python<'_>,
        key: Py<PyAny>,
        handler: Py<PyAny>,
    ) -> PyResult<()> {
        let key = key.bind(py);
        if key.is_instance(&py.get_type::<PyInt>())? {
            self.status_handlers
                .bind(py)
                .set_item(key, handler.bind(py))?;
            return Ok(());
        }

        let is_exception_subclass = py
            .import("builtins")?
            .getattr("issubclass")?
            .call1((key, py.get_type::<PyException>()))?
            .extract::<bool>()?;
        if !is_exception_subclass {
            return Err(PyAssertionError::new_err(()));
        }
        self.exception_handlers
            .bind(py)
            .set_item(key, handler.bind(py))?;
        Ok(())
    }
}

#[pyclass(name = "_ExceptionSendProxy")]
struct PyExceptionSendProxy {
    send: Py<PyAny>,
    // Tracebacks may retain this callback after its event-loop thread exits.
    // The flag is shared without imposing thread affinity on owned Py references.
    response_started: Arc<AtomicBool>,
}

pub(crate) fn exception_send_proxy(
    py: Python<'_>,
    send: Py<PyAny>,
    response_started: Arc<AtomicBool>,
) -> PyResult<Py<PyAny>> {
    Py::new(
        py,
        PyExceptionSendProxy {
            send,
            response_started,
        },
    )
    .map(|proxy| proxy.into_any())
}

#[pymethods]
impl PyExceptionSendProxy {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.send)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.send = py.None();
    }

    fn __call__(slf: Py<Self>, py: Python<'_>, message: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let proxy = slf.borrow(py);
        into_sendable_python_awaitable(
            py,
            ExceptionSendCall {
                send: proxy.send.clone_ref(py),
                response_started: proxy.response_started.clone(),
                message,
                pending: false,
            },
        )
    }
}

struct ExceptionSendCall {
    send: Py<PyAny>,
    response_started: Arc<AtomicBool>,
    message: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for ExceptionSendCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                let message_type = self.message.bind(py).get_item("type")?;
                // Starlette compares the original ASGI type object with Python
                // `==`, then uses the result in a conditional. Preserve both
                // rich-equality and truth-testing behavior for subclasses and
                // other Python values, while forwarding the original message.
                let is_response_start = message_type
                    .rich_compare("http.response.start", CompareOp::Eq)?
                    .is_truthy()?;
                if is_response_start {
                    self.response_started.store(true, Ordering::Relaxed);
                }
                let awaitable = self.send.bind(py).call1((self.message.bind(py),))?;
                self.pending = true;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
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
                PyRuntimeError::new_err("exception middleware sender has no pending send"),
            ),
        }
    }
}

#[derive(Clone, Copy)]
enum ExceptionPending {
    PassThrough,
    App,
    Handler,
    Response,
}

struct ExceptionMiddlewareCall {
    middleware: Py<PyAny>,
    exception_handlers: Py<PyDict>,
    status_handlers: Py<PyDict>,
    http_exception_type: Py<PyAny>,
    request_type: Py<PyAny>,
    websocket_type: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    sender: Option<Py<PyAny>>,
    connection: Option<Py<PyAny>>,
    response_started: Arc<AtomicBool>,
    pending: Option<ExceptionPending>,
    original_exception: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for ExceptionMiddlewareCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.middleware)?;
        visit.call(&self.exception_handlers)?;
        visit.call(&self.status_handlers)?;
        visit.call(&self.http_exception_type)?;
        visit.call(&self.request_type)?;
        visit.call(&self.websocket_type)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.sender)?;
        visit.call(&self.connection)?;
        visit.call(&self.original_exception)
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "exception middleware already has an operation pending",
            )),
            MachineResume::Value(value) => match self.pending.take() {
                Some(ExceptionPending::PassThrough | ExceptionPending::App) => {
                    Ok(MachineAction::Complete(py.None()))
                }
                Some(ExceptionPending::Handler) => self.handle_response(py, value),
                Some(ExceptionPending::Response) => Ok(MachineAction::Complete(py.None())),
                None => Err(PyRuntimeError::new_err(
                    "exception middleware resumed without a pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(ExceptionPending::App) => self.handle_application_error(py, error),
                Some(ExceptionPending::Handler | ExceptionPending::Response) => {
                    Err(self.chain_to_original(py, error))
                }
                Some(ExceptionPending::PassThrough) | None => Err(error),
            },
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
        }
    }
}

impl ExceptionMiddlewareCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let scope_type = scope.get_item("type")?;
        let supported_scope_types = PyTuple::new(py, ["http", "websocket"])?;
        if !supported_scope_types.contains(&scope_type)? {
            self.pending = Some(ExceptionPending::PassThrough);
            let app = self.middleware.bind(py).getattr("app")?;
            let awaitable = app.call1((scope, &self.receive, &self.send))?;
            return Ok(MachineAction::Await(awaitable.unbind()));
        }

        scope.set_item(
            "starlette.exception_handlers",
            PyTuple::new(
                py,
                [
                    self.exception_handlers.clone_ref(py).into_any(),
                    self.status_handlers.clone_ref(py).into_any(),
                ],
            )?,
        )?;
        // Match the second source lookup after the handler mapping is written:
        // `scope["type"] == "http"` chooses Request versus WebSocket.
        let is_http = scope
            .get_item("type")?
            .rich_compare("http", CompareOp::Eq)?
            .is_truthy()?;
        let connection = if is_http {
            match crate::scope_mapping::optional_item(scope, "starlette._exception_request")? {
                Some(request) => {
                    scope.del_item("starlette._exception_request")?;
                    request
                }
                None => self
                    .request_type
                    .bind(py)
                    .call1((scope, &self.receive, &self.send))?,
            }
        } else {
            self.websocket_type
                .bind(py)
                .call1((scope, &self.receive, &self.send))?
        };
        self.connection = Some(connection.unbind());
        let sender =
            exception_send_proxy(py, self.send.clone_ref(py), self.response_started.clone())?;
        self.sender = Some(sender.clone_ref(py));
        self.pending = Some(ExceptionPending::App);
        let app = self.middleware.bind(py).getattr("app")?;
        match app.call1((scope, &self.receive, sender)) {
            Ok(awaitable) => Ok(MachineAction::Await(awaitable.unbind())),
            Err(error) => match self.pending.take() {
                Some(ExceptionPending::App) => self.handle_application_error(py, error),
                _ => Err(error),
            },
        }
    }

    fn handle_application_error(
        &mut self,
        py: Python<'_>,
        error: PyErr,
    ) -> PyResult<MachineAction> {
        if !error.is_instance_of::<PyException>(py) {
            return Err(error);
        }
        let error_value = error.value(py);
        let Some(handler) = self.lookup_handler(py, error_value)? else {
            return Err(error);
        };
        if self.response_started.load(Ordering::Relaxed) {
            let handled_error =
                PyRuntimeError::new_err("Caught handled exception, but response already started.");
            handled_error.set_cause(py, Some(error));
            return Err(handled_error);
        }

        let scope = self.scope.bind(py);
        if let Some(request) =
            crate::scope_mapping::optional_item(scope, "starlette._exception_request")?
        {
            self.connection = Some(request.unbind());
            scope.del_item("starlette._exception_request")?;
        }

        let exception = error_value.clone().into_any().unbind();
        self.original_exception = Some(exception.clone_ref(py));
        let connection = self
            .connection
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("exception middleware lost its connection"))?;
        let is_async = crate::background::is_async_callable(py, handler.bind(py))
            .map_err(|error| self.chain_to_original(py, error))?;
        let awaitable = if is_async {
            handler
                .bind(py)
                .call1((connection.bind(py), exception.bind(py)))
        } else {
            py.import("starlette.concurrency")?
                .getattr("run_in_threadpool")?
                .call1((handler.bind(py), connection.bind(py), exception.bind(py)))
        };
        let awaitable = awaitable.map_err(|error| self.chain_to_original(py, error))?;
        self.pending = Some(ExceptionPending::Handler);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn lookup_handler(
        &self,
        py: Python<'_>,
        exception: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyAny>>> {
        if exception.is_instance(self.http_exception_type.bind(py))? {
            let status_code = exception.getattr("status_code")?;
            if let Some(handler) = self.status_handlers.bind(py).get_item(status_code)? {
                if !handler.is_none() {
                    return Ok(Some(handler.unbind()));
                }
            }
        }

        let mro = exception.get_type().getattr("__mro__")?;
        for class in mro.try_iter()? {
            if let Some(handler) = self.exception_handlers.bind(py).get_item(class?)? {
                return Ok((!handler.is_none()).then(|| handler.unbind()));
            }
        }
        Ok(None)
    }

    fn handle_response(&mut self, py: Python<'_>, response: Py<PyAny>) -> PyResult<MachineAction> {
        if response.bind(py).is_none() {
            return Ok(MachineAction::Complete(py.None()));
        }
        let sender = self.sender.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("exception middleware lost its send callback")
        })?;
        let call =
            response
                .bind(py)
                .call1((self.scope.bind(py), self.receive.bind(py), sender.bind(py)));
        let call = call.map_err(|error| self.chain_to_original(py, error))?;
        self.pending = Some(ExceptionPending::Response);
        Ok(MachineAction::Await(call.unbind()))
    }

    fn chain_to_original(&self, py: Python<'_>, error: PyErr) -> PyErr {
        if let Some(original) = self.original_exception.as_ref() {
            if !error.value(py).is(original.bind(py)) {
                error.set_context(py, Some(PyErr::from_value(original.bind(py).clone())));
            }
        }
        error
    }
}
