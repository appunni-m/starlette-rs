//! Rust-owned construction and behavior for the public route classes.
//!
//! Python remains the call boundary for regex objects, registered converters,
//! middleware constructors, and endpoint adapters. Route ordering, scope
//! decisions, and path formatting live here.

use std::collections::HashSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use pyo3::class::basic::CompareOp;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAssertionError, PyAttributeError, PyException, PyKeyError, PyNotImplementedError,
    PyRuntimeError, PyStopAsyncIteration, PyStopIteration, PyTypeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyList, PySet, PyString, PyTuple};

use crate::application_runtime::exception_send_proxy;
use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use crate::datastructure_runtime::{codepoints_to_python_string, python_string_to_codepoints};
use crate::middleware_config_runtime::middleware_kwargs_to_dict;

pub(super) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(compile_route_path, module)?)?;
    module.add_function(wrap_pyfunction!(initialize_route, module)?)?;
    module.add_function(wrap_pyfunction!(initialize_router_state, module)?)?;
    module.add_function(wrap_pyfunction!(default_lifespan_runtime, module)?)?;
    module.add_function(wrap_pyfunction!(default_lifespan_transition, module)?)?;
    module.add_function(wrap_pyfunction!(default_lifespan_context, module)?)?;
    module.add_function(wrap_pyfunction!(base_route_unimplemented, module)?)?;
    module.add_function(wrap_pyfunction!(base_route_unimplemented_async, module)?)?;
    module.add_function(wrap_pyfunction!(apply_route_middleware, module)?)?;
    module.add_function(wrap_pyfunction!(route_endpoint_name, module)?)?;
    module.add_function(wrap_pyfunction!(no_match_message, module)?)?;
    module.add_function(wrap_pyfunction!(route_equal, module)?)?;
    module.add_function(wrap_pyfunction!(route_repr, module)?)?;
    module.add_function(wrap_pyfunction!(route_children, module)?)?;
    module.add_function(wrap_pyfunction!(router_add_host, module)?)?;
    module.add_function(wrap_pyfunction!(router_add_mount, module)?)?;
    module.add_function(wrap_pyfunction!(router_add_route, module)?)?;
    module.add_function(wrap_pyfunction!(router_add_websocket_route, module)?)?;
    module.add_function(wrap_pyfunction!(route_path, module)?)?;
    module.add_function(wrap_pyfunction!(route_matches, module)?)?;
    module.add_function(wrap_pyfunction!(route_handle, module)?)?;
    module.add_function(wrap_pyfunction!(base_route_call, module)?)?;
    module.add_function(wrap_pyfunction!(route_format_path_params, module)?)?;
    module.add_function(wrap_pyfunction!(route_url_path_for, module)?)?;
    module.add_function(wrap_pyfunction!(host_url_path_for, module)?)?;
    module.add_function(wrap_pyfunction!(mount_url_path_for, module)?)?;
    module.add_function(wrap_pyfunction!(request_response, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_session, module)?)?;
    module.add_function(wrap_pyfunction!(router_lifespan, module)?)?;
    module.add_class::<PyDefaultLifespanRuntime>()?;
    module.add_class::<PySyncGeneratorLifespanFactory>()?;
    module.add_class::<PyAsyncGeneratorLifespanFactory>()?;
    module.add_class::<PySyncGeneratorLifespanContextManager>()?;
    module.add_class::<PyAsyncGeneratorLifespanContextManager>()?;
    Ok(())
}

#[pyclass(name = "_DefaultLifespanRuntime")]
struct PyDefaultLifespanRuntime {
    _router: Py<PyAny>,
}

#[pymethods]
impl PyDefaultLifespanRuntime {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self._router)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self._router = py.None();
    }
}

/// Callable adapter created by Rust for deprecated synchronous generator lifespans.
#[pyclass(name = "_SyncGeneratorLifespanFactory", dict)]
struct PySyncGeneratorLifespanFactory {
    lifespan: Py<PyAny>,
}

#[pymethods]
impl PySyncGeneratorLifespanFactory {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.lifespan)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.lifespan = py.None();
    }

    fn __call__(&self, py: Python<'_>, app: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let generator = self.lifespan.bind(py).call1((app,))?;
        Py::new(
            py,
            PySyncGeneratorLifespanContextManager {
                generator: generator.unbind(),
            },
        )
        .map(|manager| manager.into_any())
    }

    fn __getattr__(&self, py: Python<'_>, name: &str) -> PyResult<Py<PyAny>> {
        if name == "__wrapped__" {
            Ok(self.lifespan.clone_ref(py))
        } else {
            self.lifespan.bind(py).getattr(name).map(Bound::unbind)
        }
    }
}

/// Callable adapter created by Rust for deprecated asynchronous generator lifespans.
#[pyclass(name = "_AsyncGeneratorLifespanFactory", dict)]
struct PyAsyncGeneratorLifespanFactory {
    lifespan: Py<PyAny>,
}

#[pymethods]
impl PyAsyncGeneratorLifespanFactory {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.lifespan)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.lifespan = py.None();
    }

    fn __call__(&self, py: Python<'_>, app: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let generator = self.lifespan.bind(py).call1((app,))?;
        Py::new(
            py,
            PyAsyncGeneratorLifespanContextManager {
                generator: generator.unbind(),
            },
        )
        .map(|manager| manager.into_any())
    }

    fn __getattr__(&self, py: Python<'_>, name: &str) -> PyResult<Py<PyAny>> {
        if name == "__wrapped__" {
            Ok(self.lifespan.clone_ref(py))
        } else {
            self.lifespan.bind(py).getattr(name).map(Bound::unbind)
        }
    }
}

/// Exposes the async context-manager protocol while Rust drives a Python generator.
#[pyclass(name = "_SyncGeneratorLifespanContextManager")]
struct PySyncGeneratorLifespanContextManager {
    generator: Py<PyAny>,
}

#[pymethods]
impl PySyncGeneratorLifespanContextManager {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.generator = py.None();
    }

    fn __aenter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            SyncGeneratorEnter {
                generator: self.generator.clone_ref(py),
            },
        )
    }

    fn __aexit__(
        &self,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        exception: Py<PyAny>,
        traceback: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            SyncGeneratorExit {
                generator: self.generator.clone_ref(py),
                exception_type,
                exception,
                traceback,
            },
        )
    }
}

/// Exposes the async context-manager protocol while Rust drives an async generator.
#[pyclass(name = "_AsyncGeneratorLifespanContextManager")]
struct PyAsyncGeneratorLifespanContextManager {
    generator: Py<PyAny>,
}

#[pymethods]
impl PyAsyncGeneratorLifespanContextManager {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.generator = py.None();
    }

    fn __aenter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            AsyncGeneratorEnter {
                generator: self.generator.clone_ref(py),
                pending: false,
            },
        )
    }

    fn __aexit__(
        &self,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        exception: Py<PyAny>,
        traceback: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let mode = if exception_type.bind(py).is_none() {
            AsyncGeneratorExitMode::Normal
        } else {
            AsyncGeneratorExitMode::Exceptional {
                exception: generator_exception_value(py, &exception_type, &exception)?,
                traceback,
            }
        };
        into_sendable_python_awaitable(
            py,
            AsyncGeneratorExit {
                generator: self.generator.clone_ref(py),
                mode,
                pending: None,
            },
        )
    }
}

struct SyncGeneratorEnter {
    generator: Py<PyAny>,
}

impl AwaitableStateMachine for SyncGeneratorEnter {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => match self.generator.bind(py).call_method0("__next__") {
                Ok(value) => Ok(MachineAction::Complete(value.unbind())),
                Err(error) if error.is_instance_of::<PyStopIteration>(py) => {
                    Err(generator_did_not_yield(py)?)
                }
                Err(error) => Err(error),
            },
            MachineResume::Error(error) => Err(error),
            _ => Err(PyRuntimeError::new_err(
                "synchronous generator entry resumed unexpectedly",
            )),
        }
    }
}

struct SyncGeneratorExit {
    generator: Py<PyAny>,
    exception_type: Py<PyAny>,
    exception: Py<PyAny>,
    traceback: Py<PyAny>,
}

impl AwaitableStateMachine for SyncGeneratorExit {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        visit.call(&self.exception_type)?;
        visit.call(&self.exception)?;
        visit.call(&self.traceback)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                if self.exception_type.bind(py).is_none() {
                    match self.generator.bind(py).call_method0("__next__") {
                        Ok(_) => {
                            self.generator.bind(py).call_method0("close")?;
                            Err(PyRuntimeError::new_err("generator didn't stop"))
                        }
                        Err(error) if error.is_instance_of::<PyStopIteration>(py) => {
                            Ok(MachineAction::Complete(python_bool(py, false)))
                        }
                        Err(error) => Err(error),
                    }
                } else {
                    let exception =
                        generator_exception_value(py, &self.exception_type, &self.exception)?;
                    match self
                        .generator
                        .bind(py)
                        .call_method1("throw", (exception.bind(py),))
                    {
                        Ok(_) => {
                            self.generator.bind(py).call_method0("close")?;
                            Err(PyRuntimeError::new_err(
                                "generator didn't stop after throw()",
                            ))
                        }
                        Err(error) => {
                            generator_throw_error(py, error, &exception, &self.traceback, true)
                        }
                    }
                }
            }
            MachineResume::Error(error) => Err(error),
            _ => Err(PyRuntimeError::new_err(
                "synchronous generator exit resumed unexpectedly",
            )),
        }
    }
}

enum AsyncGeneratorExitMode {
    Normal,
    Exceptional {
        exception: Py<PyAny>,
        traceback: Py<PyAny>,
    },
}

enum AsyncGeneratorExitPending {
    NormalStep,
    ExceptionalStep {
        exception: Py<PyAny>,
        traceback: Py<PyAny>,
    },
    NormalClose,
    ExceptionalClose,
}

struct AsyncGeneratorEnter {
    generator: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for AsyncGeneratorEnter {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => {
                let next = self.generator.bind(py).call_method0("__anext__")?;
                self.pending = true;
                Ok(MachineAction::Await(next.unbind()))
            }
            MachineResume::Value(value) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(value))
            }
            MachineResume::AsyncIterationComplete(_) if self.pending => {
                self.pending = false;
                Err(generator_did_not_yield(py)?)
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            _ => Err(PyRuntimeError::new_err(
                "asynchronous generator entry resumed unexpectedly",
            )),
        }
    }
}

struct AsyncGeneratorExit {
    generator: Py<PyAny>,
    mode: AsyncGeneratorExitMode,
    pending: Option<AsyncGeneratorExitPending>,
}

impl AwaitableStateMachine for AsyncGeneratorExit {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.generator)?;
        if let AsyncGeneratorExitMode::Exceptional {
            exception,
            traceback,
        } = &self.mode
        {
            visit.call(exception)?;
            visit.call(traceback)?;
        }
        if let Some(AsyncGeneratorExitPending::ExceptionalStep {
            exception,
            traceback,
        }) = &self.pending
        {
            visit.call(exception)?;
            visit.call(traceback)?;
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => self.resume_value(py, value),
            MachineResume::AsyncIterationComplete(error) => {
                self.resume_async_iteration_complete(py, error)
            }
            MachineResume::Error(error) => self.resume_error(py, error),
            _ => Err(PyRuntimeError::new_err(
                "asynchronous generator exit resumed unexpectedly",
            )),
        }
    }
}

impl AsyncGeneratorExit {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match &self.mode {
            AsyncGeneratorExitMode::Normal => {
                let next = self.generator.bind(py).call_method0("__anext__")?;
                self.pending = Some(AsyncGeneratorExitPending::NormalStep);
                Ok(MachineAction::Await(next.unbind()))
            }
            AsyncGeneratorExitMode::Exceptional {
                exception,
                traceback,
            } => {
                let thrown = self
                    .generator
                    .bind(py)
                    .call_method1("athrow", (exception.bind(py),))?;
                self.pending = Some(AsyncGeneratorExitPending::ExceptionalStep {
                    exception: exception.clone_ref(py),
                    traceback: traceback.clone_ref(py),
                });
                Ok(MachineAction::Await(thrown.unbind()))
            }
        }
    }

    fn resume_value(&mut self, py: Python<'_>, _value: Py<PyAny>) -> PyResult<MachineAction> {
        let pending = self.take_pending()?;
        let close_pending = match pending {
            AsyncGeneratorExitPending::NormalStep => AsyncGeneratorExitPending::NormalClose,
            AsyncGeneratorExitPending::ExceptionalStep { .. } => {
                AsyncGeneratorExitPending::ExceptionalClose
            }
            AsyncGeneratorExitPending::NormalClose => {
                return Err(PyRuntimeError::new_err("generator didn't stop"));
            }
            AsyncGeneratorExitPending::ExceptionalClose => {
                return Err(PyRuntimeError::new_err(
                    "generator didn't stop after athrow()",
                ));
            }
        };
        let close = self.generator.bind(py).call_method0("aclose")?;
        self.pending = Some(close_pending);
        Ok(MachineAction::Await(close.unbind()))
    }

    fn resume_async_iteration_complete(
        &mut self,
        py: Python<'_>,
        error: PyErr,
    ) -> PyResult<MachineAction> {
        match self.take_pending()? {
            AsyncGeneratorExitPending::NormalStep => {
                Ok(MachineAction::Complete(python_bool(py, false)))
            }
            AsyncGeneratorExitPending::ExceptionalStep { exception, .. } => Ok(
                MachineAction::Complete(python_bool(py, !error.value(py).is(exception.bind(py)))),
            ),
            AsyncGeneratorExitPending::NormalClose
            | AsyncGeneratorExitPending::ExceptionalClose => Err(error),
        }
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.take_pending()? {
            AsyncGeneratorExitPending::ExceptionalStep {
                exception,
                traceback,
            } => generator_throw_error(py, error, &exception, &traceback, false),
            AsyncGeneratorExitPending::NormalStep => Err(error),
            AsyncGeneratorExitPending::NormalClose
            | AsyncGeneratorExitPending::ExceptionalClose => Err(error),
        }
    }

    fn take_pending(&mut self) -> PyResult<AsyncGeneratorExitPending> {
        self.pending.take().ok_or_else(|| {
            PyRuntimeError::new_err("asynchronous generator exit has no pending operation")
        })
    }
}

fn generator_exception_value(
    py: Python<'_>,
    exception_type: &Py<PyAny>,
    exception: &Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    if exception.bind(py).is_none() {
        exception_type.bind(py).call0().map(Bound::unbind)
    } else {
        Ok(exception.clone_ref(py))
    }
}

fn generator_did_not_yield(py: Python<'_>) -> PyResult<PyErr> {
    let error = PyRuntimeError::new_err("generator didn't yield");
    error.value(py).setattr("__suppress_context__", true)?;
    Ok(error)
}

fn generator_throw_error(
    py: Python<'_>,
    error: PyErr,
    original: &Py<PyAny>,
    traceback: &Py<PyAny>,
    synchronous: bool,
) -> PyResult<MachineAction> {
    let value = error.value(py);
    if synchronous && error.is_instance_of::<PyStopIteration>(py) {
        return Ok(MachineAction::Complete(python_bool(
            py,
            !value.is(original.bind(py)),
        )));
    }

    if error.is_instance_of::<PyRuntimeError>(py) {
        if value.is(original.bind(py)) {
            original
                .bind(py)
                .setattr("__traceback__", traceback.bind(py))?;
            return Ok(MachineAction::Complete(python_bool(py, false)));
        }

        let original_is_iteration = original.bind(py).is_instance_of::<PyStopIteration>()
            || (!synchronous && original.bind(py).is_instance_of::<PyStopAsyncIteration>());
        if original_is_iteration && value.getattr("__cause__")?.is(original.bind(py)) {
            original
                .bind(py)
                .setattr("__traceback__", traceback.bind(py))?;
            return Ok(MachineAction::Complete(python_bool(py, false)));
        }
        return Err(error);
    }

    if value.is(original.bind(py)) {
        original
            .bind(py)
            .setattr("__traceback__", traceback.bind(py))?;
        return Ok(MachineAction::Complete(python_bool(py, false)));
    }
    Err(error)
}

fn python_bool(py: Python<'_>, value: bool) -> Py<PyAny> {
    PyBool::new(py, value).to_owned().into_any().unbind()
}

struct DefaultLifespanTransition;

impl AwaitableStateMachine for DefaultLifespanTransition {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Error(error) => Err(error),
            _ => Ok(MachineAction::Complete(py.None())),
        }
    }
}

struct BaseRouteUnimplemented;

impl AwaitableStateMachine for BaseRouteUnimplemented {
    fn resume(&mut self, _py: Python<'_>, _input: MachineResume) -> PyResult<MachineAction> {
        Err(PyNotImplementedError::new_err(()))
    }
}

#[pyfunction]
fn base_route_unimplemented(_method: &str) -> PyResult<Py<PyAny>> {
    Err(PyNotImplementedError::new_err(()))
}

#[pyfunction]
fn base_route_unimplemented_async(py: Python<'_>, _method: &str) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(py, BaseRouteUnimplemented)
}

#[pyfunction]
fn default_lifespan_runtime(py: Python<'_>, router: Py<PyAny>) -> PyResult<Py<PyAny>> {
    Py::new(py, PyDefaultLifespanRuntime { _router: router }).map(|value| value.into_any())
}

#[pyfunction]
fn default_lifespan_transition(py: Python<'_>, _runtime: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(py, DefaultLifespanTransition)
}

#[pyfunction]
fn default_lifespan_context(
    _runtime: &Bound<'_, PyAny>,
    _app: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> Py<PyAny> {
    context.clone().unbind()
}

#[pyfunction]
fn router_lifespan(
    py: Python<'_>,
    lifespan_context: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        RouterLifespanMachine {
            lifespan_context,
            context_manager: None,
            exit_method: None,
            scope,
            receive,
            send,
            pending: None,
        },
    )
}

fn type_attribute<'py>(
    py: Python<'py>,
    object_type: &Bound<'py, PyAny>,
    name: &str,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    let mro_value = object_type.getattr("__mro__")?;
    let mro = mro_value.cast::<PyTuple>()?;
    for base in mro.iter() {
        let namespace = base.getattr("__dict__")?;
        match namespace.get_item(name) {
            Ok(attribute) => return Ok(Some(attribute)),
            Err(error) if error.is_instance_of::<PyKeyError>(py) => {}
            Err(error) => return Err(error),
        }
    }
    Ok(None)
}

fn lookup_async_context_method<'py>(
    py: Python<'py>,
    context_manager: &Bound<'py, PyAny>,
    name: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let context_manager_type = context_manager.get_type();
    let type_name = context_manager_type
        .getattr("__name__")?
        .extract::<String>()?;
    let descriptor = type_attribute(py, &context_manager_type, name)?.ok_or_else(|| {
        if name == "__aenter__" {
            PyTypeError::new_err(format!(
                "'{type_name}' object does not support the asynchronous context manager protocol"
            ))
        } else {
            PyTypeError::new_err(format!(
                "'{type_name}' object does not support the asynchronous context manager protocol (missed {name} method)"
            ))
        }
    })?;
    match descriptor.getattr("__get__") {
        Ok(getter) => getter.call1((context_manager, context_manager_type)),
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => Ok(descriptor),
        Err(error) => Err(error),
    }
}

enum RouterLifespanPending {
    StartupReceive,
    Enter,
    StartupSend,
    ShutdownReceive,
    NormalExit,
    ErrorExit { original: Py<PyAny>, started: bool },
    FailureSend { original: Py<PyAny> },
    ShutdownComplete,
}

struct RouterLifespanMachine {
    lifespan_context: Py<PyAny>,
    context_manager: Option<Py<PyAny>>,
    exit_method: Option<Py<PyAny>>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: Option<RouterLifespanPending>,
}

impl AwaitableStateMachine for RouterLifespanMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.lifespan_context)?;
        visit.call(&self.context_manager)?;
        visit.call(&self.exit_method)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        if let Some(
            RouterLifespanPending::ErrorExit { original, .. }
            | RouterLifespanPending::FailureSend { original },
        ) = &self.pending
        {
            visit.call(original)?;
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => {
                let pending = self.take_pending()?;
                self.resume_value(py, pending, value)
            }
            MachineResume::Error(error) => {
                let pending = self.take_pending()?;
                self.resume_error(py, pending, error)
            }
            MachineResume::AsyncIterationComplete(error) => {
                self.resume(py, MachineResume::Error(error))
            }
            _ => Err(PyRuntimeError::new_err(
                "router lifespan resumed without a pending operation",
            )),
        }
    }
}

impl RouterLifespanMachine {
    fn take_pending(&mut self) -> PyResult<RouterLifespanPending> {
        self.pending.take().ok_or_else(|| {
            PyRuntimeError::new_err("router lifespan resumed without a pending operation")
        })
    }

    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let receive = self.receive.bind(py).call0()?;
        self.pending = Some(RouterLifespanPending::StartupReceive);
        Ok(MachineAction::Await(receive.unbind()))
    }

    fn resume_value(
        &mut self,
        py: Python<'_>,
        pending: RouterLifespanPending,
        value: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        match pending {
            RouterLifespanPending::StartupReceive => self.enter_context(py),
            RouterLifespanPending::Enter => self.entered(py, value),
            RouterLifespanPending::StartupSend => {
                match self.await_receive(py, RouterLifespanPending::ShutdownReceive) {
                    Ok(action) => Ok(action),
                    Err(error) => self.exit_with_error(py, error, true),
                }
            }
            RouterLifespanPending::ShutdownReceive => self.exit_normally(py),
            RouterLifespanPending::NormalExit => self.send_shutdown_complete(py),
            RouterLifespanPending::ErrorExit { original, started } => {
                match value.bind(py).is_truthy() {
                    Ok(true) => self.send_shutdown_complete(py),
                    Ok(false) => {
                        self.send_failure(py, PyErr::from_value(original.into_bound(py)), started)
                    }
                    Err(error) => self.send_failure(py, error, started),
                }
            }
            RouterLifespanPending::FailureSend { original } => {
                Err(PyErr::from_value(original.into_bound(py)))
            }
            RouterLifespanPending::ShutdownComplete => Ok(MachineAction::Complete(py.None())),
        }
    }

    fn resume_error(
        &mut self,
        py: Python<'_>,
        pending: RouterLifespanPending,
        error: PyErr,
    ) -> PyResult<MachineAction> {
        match pending {
            RouterLifespanPending::StartupReceive | RouterLifespanPending::ShutdownComplete => {
                Err(error)
            }
            RouterLifespanPending::FailureSend { original } => {
                Err(chain_lifespan_failure_send_error(py, error, &original))
            }
            RouterLifespanPending::Enter => self.send_failure(py, error, false),
            RouterLifespanPending::StartupSend => self.exit_with_error(py, error, false),
            RouterLifespanPending::ShutdownReceive => self.exit_with_error(py, error, true),
            RouterLifespanPending::NormalExit => self.send_failure(py, error, true),
            RouterLifespanPending::ErrorExit { started, .. } => {
                self.send_failure(py, error, started)
            }
        }
    }

    fn enter_context(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let app = scope.call_method1("get", ("app",))?;
        let context_manager = match self.lifespan_context.bind(py).call1((app,)) {
            Ok(context_manager) => context_manager,
            Err(error) => return self.send_failure(py, error, false),
        };
        let enter_method = match lookup_async_context_method(py, &context_manager, "__aenter__") {
            Ok(method) => method,
            Err(error) => return self.send_failure(py, error, false),
        };
        let exit_method = match lookup_async_context_method(py, &context_manager, "__aexit__") {
            Ok(method) => method,
            Err(error) => return self.send_failure(py, error, false),
        };
        let enter = match enter_method.call0() {
            Ok(enter) => enter,
            Err(error) => return self.send_failure(py, error, false),
        };
        self.context_manager = Some(context_manager.unbind());
        self.exit_method = Some(exit_method.unbind());
        self.pending = Some(RouterLifespanPending::Enter);
        Ok(MachineAction::Await(enter.unbind()))
    }

    fn entered(&mut self, py: Python<'_>, maybe_state: Py<PyAny>) -> PyResult<MachineAction> {
        if !maybe_state.bind(py).is_none() {
            let state_update = (|| -> PyResult<()> {
                let scope = self.scope.bind(py);
                if !scope.contains("state")? {
                    return Err(PyRuntimeError::new_err(
                        "The server does not support \"state\" in the lifespan scope.",
                    ));
                }
                let state = scope.get_item("state")?;
                state.call_method1("update", (maybe_state.bind(py),))?;
                Ok(())
            })();
            if let Err(error) = state_update {
                return self.exit_with_error(py, error, false);
            }
        }
        self.send_event(
            py,
            "lifespan.startup.complete",
            None,
            RouterLifespanPending::StartupSend,
        )
    }

    fn exit_normally(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.context_manager.is_none() {
            return Err(PyRuntimeError::new_err(
                "lifespan context manager was not entered",
            ));
        }
        let Some(exit_method) = self.exit_method.as_ref() else {
            return Err(PyRuntimeError::new_err(
                "lifespan context manager exit method was not resolved",
            ));
        };
        let exit = match exit_method
            .bind(py)
            .call1((py.None(), py.None(), py.None()))
        {
            Ok(exit) => exit,
            Err(error) => return self.send_failure(py, error, true),
        };
        self.pending = Some(RouterLifespanPending::NormalExit);
        Ok(MachineAction::Await(exit.unbind()))
    }

    fn exit_with_error(
        &mut self,
        py: Python<'_>,
        original: PyErr,
        started: bool,
    ) -> PyResult<MachineAction> {
        if self.context_manager.is_none() {
            return self.send_failure(py, original, started);
        }
        let exception = original.value(py);
        let exception_type = original.get_type(py);
        let traceback = original
            .traceback(py)
            .map_or_else(|| py.None().into_bound(py), Bound::into_any);
        let Some(exit_method) = self.exit_method.as_ref() else {
            return self.send_failure(py, original, started);
        };
        let exit = match exit_method
            .bind(py)
            .call1((exception_type, exception, traceback))
        {
            Ok(exit) => exit,
            Err(error) => return self.send_failure(py, error, started),
        };
        self.pending = Some(RouterLifespanPending::ErrorExit {
            original: original.value(py).clone().into_any().unbind(),
            started,
        });
        Ok(MachineAction::Await(exit.unbind()))
    }

    fn send_failure(
        &mut self,
        py: Python<'_>,
        original: PyErr,
        started: bool,
    ) -> PyResult<MachineAction> {
        let message = traceback_text(py, &original)?;
        let event_type = if started {
            "lifespan.shutdown.failed"
        } else {
            "lifespan.startup.failed"
        };
        self.send_event(
            py,
            event_type,
            Some(&message),
            RouterLifespanPending::FailureSend {
                original: original.value(py).clone().into_any().unbind(),
            },
        )
    }

    fn send_shutdown_complete(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        self.send_event(
            py,
            "lifespan.shutdown.complete",
            None,
            RouterLifespanPending::ShutdownComplete,
        )
    }

    fn await_receive(
        &mut self,
        py: Python<'_>,
        pending: RouterLifespanPending,
    ) -> PyResult<MachineAction> {
        let receive = self.receive.bind(py).call0()?;
        self.pending = Some(pending);
        Ok(MachineAction::Await(receive.unbind()))
    }

    fn send_event(
        &mut self,
        py: Python<'_>,
        event_type: &str,
        message: Option<&str>,
        pending: RouterLifespanPending,
    ) -> PyResult<MachineAction> {
        let event = PyDict::new(py);
        event.set_item("type", event_type)?;
        if let Some(message) = message {
            event.set_item("message", message)?;
        }
        let send = match self.send.bind(py).call1((event,)) {
            Ok(send) => send,
            Err(error) => {
                return match &pending {
                    RouterLifespanPending::StartupSend => self.exit_with_error(py, error, false),
                    RouterLifespanPending::FailureSend { original } => {
                        Err(chain_lifespan_failure_send_error(py, error, original))
                    }
                    _ => Err(error),
                };
            }
        };
        self.pending = Some(pending);
        Ok(MachineAction::Await(send.unbind()))
    }
}

fn chain_lifespan_failure_send_error(py: Python<'_>, error: PyErr, original: &Py<PyAny>) -> PyErr {
    if !error.value(py).is(original.bind(py)) {
        error.set_context(py, Some(PyErr::from_value(original.bind(py).clone())));
    }
    error
}

fn traceback_text(py: Python<'_>, error: &PyErr) -> PyResult<String> {
    let exception = error.value(py);
    let exception_type = error.get_type(py);
    let traceback = error
        .traceback(py)
        .map_or_else(|| py.None().into_bound(py), Bound::into_any);
    let formatted = py
        .import("traceback")?
        .getattr("format_exception")?
        .call1((exception_type, exception, traceback))?;
    PyString::new(py, "")
        .call_method1("join", (formatted,))?
        .extract()
}

#[pyfunction]
fn compile_route_path(
    py: Python<'_>,
    path: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
) -> PyResult<(Py<PyAny>, Py<PyAny>, Py<PyDict>)> {
    let (pattern, path_format, convertors, _, _) =
        compile_path_parts_compat(py, path, convertor_types, None)?;
    Ok((
        pattern.unbind(),
        path_format.into_any().unbind(),
        convertors.unbind(),
    ))
}

#[pyfunction]
#[pyo3(signature = (kind, path, endpoint, methods, name, include_in_schema, middleware, max_body_size, routes, convertor_types, builtin_convertors, route_table_type, request_response_factory, websocket_endpoint_factory, router_type))]
// LINT EXCEPTION: Preserve each Starlette route field and factory as a separate PyO3 conversion input.
#[allow(clippy::too_many_arguments)]
fn initialize_route(
    py: Python<'_>,
    kind: &str,
    path: &Bound<'_, PyAny>,
    endpoint: Option<Py<PyAny>>,
    methods: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    include_in_schema: bool,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    routes: Option<Py<PyAny>>,
    convertor_types: Py<PyAny>,
    builtin_convertors: Py<PyAny>,
    route_table_type: Py<PyAny>,
    request_response_factory: Py<PyAny>,
    websocket_endpoint_factory: Py<PyAny>,
    router_type: Py<PyAny>,
) -> PyResult<Py<PyTuple>> {
    let convertor_types = convertor_types.bind(py).cast::<PyDict>()?;
    let builtin_convertors = builtin_convertors.bind(py).cast::<PyDict>()?;
    let (
        path,
        endpoint,
        name,
        methods,
        include_in_schema,
        base_app,
        app,
        regex,
        path_format,
        convertors,
        custom,
        route_table,
    ) = match kind {
        "http" => initialize_http_route(
            py,
            path,
            endpoint,
            methods,
            name,
            include_in_schema,
            middleware,
            max_body_size,
            convertor_types,
            builtin_convertors,
            request_response_factory.bind(py),
            route_table_type.bind(py),
        )?,
        "websocket" => initialize_websocket_route(
            py,
            path,
            endpoint,
            name,
            middleware,
            convertor_types,
            builtin_convertors,
            websocket_endpoint_factory.bind(py),
            route_table_type.bind(py),
        )?,
        "host" => initialize_host_route(
            py,
            path,
            endpoint,
            name,
            convertor_types,
            builtin_convertors,
            route_table_type.bind(py),
        )?,
        "mount" => initialize_mount(
            py,
            path,
            endpoint,
            routes,
            name,
            middleware,
            max_body_size,
            convertor_types,
            builtin_convertors,
            route_table_type.bind(py),
            router_type.bind(py),
        )?,
        _ => {
            return Err(PyValueError::new_err(format!(
                "unknown route kind '{kind}'"
            )));
        }
    };

    let values: Vec<Py<PyAny>> = vec![
        path,
        endpoint,
        name,
        methods,
        include_in_schema,
        base_app,
        app,
        regex,
        path_format,
        convertors,
        custom,
        route_table,
    ];
    Ok(PyTuple::new(py, values.iter().map(|value| value.bind(py)))?.unbind())
}

#[pyfunction]
#[pyo3(signature = (router, routes, default, lifespan, middleware, max_body_size, runtime_type, base_route_type, http_route_type, websocket_route_type, mount_type, host_route_type, default_lifespan_factory, deprecation_warning_type))]
// LINT EXCEPTION: Router state and its concrete factories must cross PyO3 as distinct Python references.
#[allow(clippy::too_many_arguments)]
fn initialize_router_state(
    py: Python<'_>,
    router: Py<PyAny>,
    routes: Option<Py<PyAny>>,
    default: Option<Py<PyAny>>,
    lifespan: Option<Py<PyAny>>,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    runtime_type: Py<PyAny>,
    base_route_type: Py<PyAny>,
    http_route_type: Py<PyAny>,
    websocket_route_type: Py<PyAny>,
    mount_type: Py<PyAny>,
    host_route_type: Py<PyAny>,
    default_lifespan_factory: Py<PyAny>,
    deprecation_warning_type: Py<PyAny>,
) -> PyResult<Py<PyTuple>> {
    let router_bound = router.bind(py);
    let routes = match routes {
        Some(routes) if !routes.bind(py).is_none() => {
            py.import("builtins")?.getattr("list")?.call1((routes,))?
        }
        _ => PyList::empty(py).into_any(),
    };
    let default = match default {
        Some(default) if !default.bind(py).is_none() => default,
        _ => router_bound.getattr("not_found")?.unbind(),
    };
    let lifespan_context = build_lifespan_context(
        py,
        router_bound,
        lifespan,
        default_lifespan_factory.bind(py),
        deprecation_warning_type.bind(py),
    )?;
    let runtime = runtime_type.bind(py).call1((
        base_route_type,
        http_route_type,
        websocket_route_type,
        mount_type,
        host_route_type,
    ))?;
    let middleware_stack = apply_router_middleware_inner(
        py,
        &router_bound.getattr("app")?,
        middleware.as_ref().map(|value| value.bind(py)),
        max_body_size.as_ref().map(|value| value.bind(py)),
    )?;
    let values = [
        routes.unbind(),
        default,
        lifespan_context,
        runtime.unbind(),
        middleware_stack,
    ];
    Ok(PyTuple::new(py, values.iter().map(|value| value.bind(py)))?.unbind())
}

fn build_lifespan_context(
    py: Python<'_>,
    router: &Bound<'_, PyAny>,
    lifespan: Option<Py<PyAny>>,
    default_lifespan_factory: &Bound<'_, PyAny>,
    deprecation_warning_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let Some(lifespan) = lifespan.filter(|value| !value.bind(py).is_none()) else {
        return default_lifespan_factory.call1((router,)).map(Bound::unbind);
    };
    let lifespan_bound = lifespan.bind(py);
    let inspect = py.import("inspect")?;
    let is_async_generator = inspect
        .getattr("isasyncgenfunction")?
        .call1((lifespan_bound,))?
        .is_truthy()?;
    if is_async_generator {
        warn_deprecated_lifespan(
            py,
            "async generator function lifespans are deprecated, use an @contextlib.asynccontextmanager function instead",
            deprecation_warning_type,
        )?;
        let factory = Py::new(
            py,
            PyAsyncGeneratorLifespanFactory {
                lifespan: lifespan.clone_ref(py),
            },
        )?;
        return Ok(factory.into_any());
    }
    let is_generator = inspect
        .getattr("isgeneratorfunction")?
        .call1((lifespan_bound,))?
        .is_truthy()?;
    if is_generator {
        warn_deprecated_lifespan(
            py,
            "generator function lifespans are deprecated, use an @contextlib.asynccontextmanager function instead",
            deprecation_warning_type,
        )?;
        let factory = Py::new(
            py,
            PySyncGeneratorLifespanFactory {
                lifespan: lifespan.clone_ref(py),
            },
        )?;
        return Ok(factory.into_any());
    }
    Ok(lifespan)
}

fn warn_deprecated_lifespan(
    py: Python<'_>,
    message: &str,
    warning_type: &Bound<'_, PyAny>,
) -> PyResult<()> {
    py.import("warnings")?
        .getattr("warn")?
        .call1((message, warning_type))?;
    Ok(())
}

#[pyfunction]
fn route_endpoint_name(py: Python<'_>, endpoint: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    endpoint_name(py, endpoint)
}

#[pyfunction]
fn no_match_message(
    py: Python<'_>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
) -> PyResult<String> {
    let keys = py
        .import("builtins")?
        .getattr("list")?
        .call1((path_params.call_method0("keys")?,))?;
    let params = PyString::new(py, ", ")
        .call_method1("join", (keys,))?
        .extract::<String>()?;
    let name = name.str()?.extract::<String>()?;
    Ok(format!(
        "No route exists for name \"{name}\" and params \"{params}\"."
    ))
}

#[pyfunction]
fn route_equal(
    route: &Bound<'_, PyAny>,
    other: &Bound<'_, PyAny>,
    route_type: &Bound<'_, PyAny>,
    kind: &str,
) -> PyResult<bool> {
    if !other.is_instance(route_type)? {
        return Ok(false);
    }
    let fields: &[&str] = match kind {
        "http" => &["path", "endpoint", "methods"],
        "websocket" => &["path", "endpoint"],
        "mount" => &["path", "app"],
        "host" => &["host", "app"],
        "router" => &["routes"],
        _ => {
            return Err(PyValueError::new_err(format!(
                "unknown route kind '{kind}'"
            )));
        }
    };
    for field in fields {
        if !route.getattr(*field)?.eq(other.getattr(*field)?)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[pyfunction]
fn route_repr(py: Python<'_>, route: &Bound<'_, PyAny>, kind: &str) -> PyResult<String> {
    let class_name = route
        .getattr("__class__")?
        .getattr("__name__")?
        .extract::<String>()?;
    let name = route.getattr("name")?;
    let repr = match kind {
        "http" => {
            let path = python_repr(py, &route.getattr("path")?)?;
            let methods = route.getattr("methods")?;
            let methods = if methods.is_none() || !methods.is_truthy()? {
                PyList::empty(py).into_any()
            } else {
                py.import("builtins")?
                    .getattr("sorted")?
                    .call1((methods,))?
            };
            let methods = python_repr(py, &methods)?;
            format!(
                "{class_name}(path={path}, name={}, methods={methods})",
                python_repr(py, &name)?
            )
        }
        "websocket" => {
            let path = python_repr(py, &route.getattr("path")?)?;
            format!(
                "{class_name}(path={path}, name={})",
                python_repr(py, &name)?
            )
        }
        "mount" => {
            let path = python_repr(py, &route.getattr("path")?)?;
            let name = if name.is_truthy()? {
                name
            } else {
                PyString::new(py, "").into_any()
            };
            format!(
                "{class_name}(path={path}, name={}, app={})",
                python_repr(py, &name)?,
                python_repr(py, &route.getattr("app")?)?
            )
        }
        "host" => {
            let host = python_repr(py, &route.getattr("host")?)?;
            let name = if name.is_truthy()? {
                name
            } else {
                PyString::new(py, "").into_any()
            };
            format!(
                "{class_name}(host={host}, name={}, app={})",
                python_repr(py, &name)?,
                python_repr(py, &route.getattr("app")?)?
            )
        }
        _ => {
            return Err(PyValueError::new_err(format!(
                "unknown route kind '{kind}'"
            )));
        }
    };
    Ok(repr)
}

fn python_repr(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<String> {
    py.import("builtins")?
        .getattr("repr")?
        .call1((value,))?
        .extract::<String>()
}

#[pyfunction]
fn route_children(py: Python<'_>, app: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    py.import("builtins")?
        .getattr("getattr")?
        .call1((app, "routes", PyList::empty(py)))
        .map(Bound::unbind)
}

#[pyfunction]
fn router_add_host(
    py: Python<'_>,
    routes: &Bound<'_, PyAny>,
    host_type: &Bound<'_, PyAny>,
    host: &str,
    app: &Bound<'_, PyAny>,
    name: Option<Py<PyAny>>,
) -> PyResult<()> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("name", name.unwrap_or_else(|| py.None()))?;
    let host_route = host_type.call((host, app), Some(&kwargs))?;
    routes.call_method1("append", (host_route,))?;
    Ok(())
}

#[pyfunction]
fn router_add_mount(
    py: Python<'_>,
    routes: &Bound<'_, PyAny>,
    mount_type: &Bound<'_, PyAny>,
    path: &str,
    app: &Bound<'_, PyAny>,
    name: Option<Py<PyAny>>,
) -> PyResult<()> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("app", app)?;
    kwargs.set_item("name", name.unwrap_or_else(|| py.None()))?;
    let route = mount_type.call((path,), Some(&kwargs))?;
    routes.call_method1("append", (route,))?;
    Ok(())
}

#[pyfunction]
// LINT EXCEPTION: Forward route fields individually to the Starlette route class to preserve its call contract.
#[allow(clippy::too_many_arguments)]
fn router_add_route(
    py: Python<'_>,
    routes: &Bound<'_, PyAny>,
    route_type: &Bound<'_, PyAny>,
    path: &str,
    endpoint: &Bound<'_, PyAny>,
    methods: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    include_in_schema: bool,
) -> PyResult<()> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("endpoint", endpoint)?;
    kwargs.set_item("methods", methods.unwrap_or_else(|| py.None()))?;
    kwargs.set_item("name", name.unwrap_or_else(|| py.None()))?;
    kwargs.set_item("include_in_schema", include_in_schema)?;
    let route = route_type.call((path,), Some(&kwargs))?;
    routes.call_method1("append", (route,))?;
    Ok(())
}

#[pyfunction]
fn router_add_websocket_route(
    py: Python<'_>,
    routes: &Bound<'_, PyAny>,
    route_type: &Bound<'_, PyAny>,
    path: &str,
    endpoint: &Bound<'_, PyAny>,
    name: Option<Py<PyAny>>,
) -> PyResult<()> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("endpoint", endpoint)?;
    kwargs.set_item("name", name.unwrap_or_else(|| py.None()))?;
    let route = route_type.call((path,), Some(&kwargs))?;
    routes.call_method1("append", (route,))?;
    Ok(())
}

type RouteInitValues = (
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
    Py<PyAny>,
);

// LINT EXCEPTION: Map every HTTP route option and factory separately to preserve Starlette's route state.
#[allow(clippy::too_many_arguments)]
fn initialize_http_route(
    py: Python<'_>,
    path: &Bound<'_, PyAny>,
    endpoint: Option<Py<PyAny>>,
    methods: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    include_in_schema: bool,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    request_response_factory: &Bound<'_, PyAny>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if !path.call_method1("startswith", ("/",))?.is_truthy()? {
        return Err(PyAssertionError::new_err(
            "Routed paths must start with '/'",
        ));
    }
    let endpoint = endpoint.ok_or_else(|| PyRuntimeError::new_err("Route endpoint is missing"))?;
    let route_name = match name {
        Some(name) => name,
        None => endpoint_name(py, endpoint.bind(py))?,
    };

    let request_endpoint = is_request_endpoint(py, endpoint.bind(py))?;
    let effective_methods = match (request_endpoint, methods) {
        (true, None) => Some(
            PyList::new(py, [PyString::new(py, "GET")])?
                .into_any()
                .unbind(),
        ),
        (_, methods) => methods,
    };
    let app = if request_endpoint {
        request_response_factory
            .call1((endpoint.bind(py),))?
            .unbind()
    } else {
        endpoint.clone_ref(py)
    };
    let app = apply_middleware_inner(
        py,
        app.bind(py),
        middleware.as_ref().map(|item| item.bind(py)),
        MiddlewareSelection::Supplied,
        max_body_size.as_ref().map(|item| item.bind(py)),
    )?;

    let normalized_methods =
        normalize_methods(py, effective_methods.as_ref().map(|item| item.bind(py)))?;
    let (regex, path_format, convertors, custom, has_surrogate) =
        compile_path_parts_compat(py, path, convertor_types, Some(builtin_convertors))?;
    let route_table = make_route_table_compat(
        py,
        route_table_type,
        path,
        custom,
        has_surrogate,
        normalized_methods.as_ref().map(|item| item.bind(py)),
    )?;

    Ok((
        path.clone().unbind(),
        endpoint,
        route_name,
        normalized_methods.map_or_else(|| py.None(), |methods| methods.into_any()),
        PyBool::new(py, include_in_schema)
            .to_owned()
            .into_any()
            .unbind(),
        py.None(),
        app,
        regex.unbind(),
        path_format.into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom || has_surrogate)
            .to_owned()
            .into_any()
            .unbind(),
        route_table,
    ))
}

// LINT EXCEPTION: Keep WebSocket route options and class factories separate at the Python compatibility boundary.
#[allow(clippy::too_many_arguments)]
fn initialize_websocket_route(
    py: Python<'_>,
    path: &Bound<'_, PyAny>,
    endpoint: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    middleware: Option<Py<PyAny>>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    websocket_endpoint_factory: &Bound<'_, PyAny>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if !path.call_method1("startswith", ("/",))?.is_truthy()? {
        return Err(PyAssertionError::new_err(
            "Routed paths must start with '/'",
        ));
    }
    let endpoint =
        endpoint.ok_or_else(|| PyRuntimeError::new_err("WebSocket endpoint is missing"))?;
    let route_name = match name {
        Some(name) => name,
        None => endpoint_name(py, endpoint.bind(py))?,
    };
    let request_endpoint = is_request_endpoint(py, endpoint.bind(py))?;
    let app = if request_endpoint {
        websocket_endpoint_factory
            .call1((endpoint.bind(py),))?
            .unbind()
    } else {
        endpoint.clone_ref(py)
    };
    let app = apply_middleware_inner(
        py,
        app.bind(py),
        middleware.as_ref().map(|item| item.bind(py)),
        MiddlewareSelection::Supplied,
        None,
    )?;
    let (regex, path_format, convertors, custom, has_surrogate) =
        compile_path_parts_compat(py, path, convertor_types, Some(builtin_convertors))?;
    let route_table =
        make_route_table_compat(py, route_table_type, path, custom, has_surrogate, None)?;

    Ok((
        path.clone().unbind(),
        endpoint,
        route_name,
        py.None(),
        PyBool::new(py, true).to_owned().into_any().unbind(),
        py.None(),
        app,
        regex.unbind(),
        path_format.into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom || has_surrogate)
            .to_owned()
            .into_any()
            .unbind(),
        route_table,
    ))
}

// LINT EXCEPTION: Preserve host, application, name, and converter inputs separately for Starlette Host behavior.
#[allow(clippy::too_many_arguments)]
fn initialize_host_route(
    py: Python<'_>,
    host: &Bound<'_, PyAny>,
    app: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if host.call_method1("startswith", ("/",))?.is_truthy()? {
        return Err(PyAssertionError::new_err("Host must not start with '/'"));
    }
    let app = app.unwrap_or_else(|| py.None());
    let (regex, host_format, convertors, custom, has_surrogate) =
        compile_path_parts_compat(py, host, convertor_types, Some(builtin_convertors))?;
    let route_table = if has_surrogate {
        py.None()
    } else {
        let host_format_codepoints = CompatibilityPath::from_python(host_format.as_any())?;
        let host_format_codepoints = host_format_without_port(&host_format_codepoints);
        let mut route_table_path = vec![u32::from(b'/')];
        route_table_path.extend_from_slice(&host_format_codepoints.0);
        let route_table_path = CompatibilityPath(route_table_path)
            .to_utf8()
            .ok_or_else(|| PyValueError::new_err("host route table path is not UTF-8"))?;
        make_route_table(py, route_table_type, &route_table_path, custom, None)?
    };
    Ok((
        host.clone().unbind(),
        app.clone_ref(py),
        name.unwrap_or_else(|| py.None()),
        py.None(),
        PyBool::new(py, true).to_owned().into_any().unbind(),
        py.None(),
        app,
        regex.unbind(),
        host_format.into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom || has_surrogate)
            .to_owned()
            .into_any()
            .unbind(),
        route_table,
    ))
}

// LINT EXCEPTION: Preserve each Mount option and its Python class factory as an independent compatibility input.
#[allow(clippy::too_many_arguments)]
fn initialize_mount(
    py: Python<'_>,
    path: &Bound<'_, PyAny>,
    app: Option<Py<PyAny>>,
    routes: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    route_table_type: &Bound<'_, PyAny>,
    router_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    let is_empty = path.rich_compare("", CompareOp::Eq)?.is_truthy()?;
    if !is_empty && !path.call_method1("startswith", ("/",))?.is_truthy()? {
        return Err(PyAssertionError::new_err(
            "Routed paths must start with '/'",
        ));
    }
    if app.as_ref().is_none_or(|value| value.bind(py).is_none())
        && routes.as_ref().is_none_or(|value| value.bind(py).is_none())
    {
        return Err(PyAssertionError::new_err(
            "Either 'app=...', or 'routes=' must be specified",
        ));
    }
    let mut path = CompatibilityPath::from_python(path)?;
    path.trim_end_ascii(b'/');
    let base_app = match app {
        Some(app) if !app.bind(py).is_none() => app,
        _ => {
            let kwargs = PyDict::new(py);
            if let Some(routes) = routes.as_ref().filter(|routes| !routes.bind(py).is_none()) {
                kwargs.set_item("routes", routes.bind(py))?;
            }
            router_type.call((), Some(&kwargs))?.unbind()
        }
    };
    let app = apply_middleware_inner(
        py,
        base_app.bind(py),
        middleware.as_ref().map(|item| item.bind(py)),
        MiddlewareSelection::Supplied,
        max_body_size.as_ref().map(|item| item.bind(py)),
    )?;
    let mut path_pattern = path.clone();
    append_utf8_codepoints(&mut path_pattern.0, "/{path:path}");
    let path_pattern = path_pattern.to_python(py)?;
    let (regex, path_format, convertors, custom, has_surrogate) = compile_path_parts_compat(
        py,
        path_pattern.as_any(),
        convertor_types,
        Some(builtin_convertors),
    )?;
    let route_table = make_route_table_compat(
        py,
        route_table_type,
        path_pattern.as_any(),
        custom,
        has_surrogate,
        None,
    )?;

    Ok((
        path.to_python(py)?.into_any().unbind(),
        py.None(),
        name.unwrap_or_else(|| py.None()),
        py.None(),
        true.into_pyobject(py)?.to_owned().into_any().unbind(),
        base_app,
        app,
        regex.unbind(),
        path_format.into_any().unbind(),
        convertors.into_any().unbind(),
        (custom || has_surrogate)
            .into_pyobject(py)?
            .to_owned()
            .into_any()
            .unbind(),
        route_table,
    ))
}

struct PathParameter {
    start: usize,
    end: usize,
    name: String,
    convertor_name: String,
}

// Route, WebSocketRoute, and Mount test whether middleware was supplied;
// Router alone tests its truth value before constructing the stack.
#[derive(Clone, Copy)]
enum MiddlewareSelection {
    Supplied,
    Truthy,
}

type CompiledCompatibilityPath<'py> = (
    Bound<'py, PyAny>,
    Bound<'py, PyString>,
    Bound<'py, PyDict>,
    bool,
    bool,
);

/// A Python path kept as Unicode code points so compatibility routes can retain lone surrogates.
/// The Rust-native RouteTable continues to use UTF-8 `String` paths.
#[derive(Clone, Debug, PartialEq, Eq)]
struct CompatibilityPath(Vec<u32>);

impl CompatibilityPath {
    fn from_python(value: &Bound<'_, PyAny>) -> PyResult<Self> {
        if value.cast::<PyString>().is_ok() {
            if let Ok(path) = value.extract::<String>() {
                return Ok(Self::from_utf8(&path));
            }
        }
        python_string_to_codepoints(value).map(Self)
    }

    fn from_utf8(value: &str) -> Self {
        Self(value.chars().map(u32::from).collect())
    }

    fn has_lone_surrogate(&self) -> bool {
        self.0
            .iter()
            .any(|codepoint| (0xD800..=0xDFFF).contains(codepoint))
    }

    fn starts_with_ascii(&self, character: u8) -> bool {
        self.0.first().copied() == Some(u32::from(character))
    }

    fn trim_end_ascii(&mut self, character: u8) {
        while self.0.last().copied() == Some(u32::from(character)) {
            self.0.pop();
        }
    }

    fn contains(&self, value: &[u32]) -> bool {
        !value.is_empty() && self.0.windows(value.len()).any(|window| window == value)
    }

    fn replace_all(&mut self, from: &[u32], to: &[u32]) {
        if from.is_empty() {
            return;
        }
        let mut result = Vec::with_capacity(self.0.len());
        let mut cursor = 0;
        while cursor < self.0.len() {
            if self.0[cursor..].starts_with(from) {
                result.extend_from_slice(to);
                cursor += from.len();
            } else {
                result.push(self.0[cursor]);
                cursor += 1;
            }
        }
        self.0 = result;
    }

    fn to_python<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyString>> {
        codepoints_to_python_string(py, &self.0)
    }

    fn to_utf8(&self) -> Option<String> {
        self.0
            .iter()
            .try_fold(String::new(), |mut value, codepoint| {
                value.push(char::from_u32(*codepoint)?);
                Some(value)
            })
    }
}

fn append_utf8_codepoints(output: &mut Vec<u32>, value: &str) {
    output.extend(value.chars().map(u32::from));
}

fn path_parameters_codepoints(path: &[u32]) -> Vec<PathParameter> {
    let mut parameters = Vec::new();
    let mut search_from = 0;
    while search_from < path.len() {
        let Some(offset) = path[search_from..]
            .iter()
            .position(|codepoint| *codepoint == u32::from(b'{'))
        else {
            break;
        };
        let start = search_from + offset;
        let mut index = start + 1;
        if !path
            .get(index)
            .copied()
            .is_some_and(is_identifier_codepoint_start)
        {
            search_from = start + 1;
            continue;
        }
        let name_start = index;
        index += 1;
        while path
            .get(index)
            .copied()
            .is_some_and(is_identifier_codepoint_continue)
        {
            index += 1;
        }
        let name = codepoints_ascii_string(&path[name_start..index]);
        let convertor_name = if path.get(index).copied() == Some(u32::from(b':')) {
            index += 1;
            let convertor_start = index;
            if !path
                .get(index)
                .copied()
                .is_some_and(is_identifier_codepoint_start)
            {
                search_from = start + 1;
                continue;
            }
            index += 1;
            while path
                .get(index)
                .copied()
                .is_some_and(is_identifier_codepoint_continue)
            {
                index += 1;
            }
            codepoints_ascii_string(&path[convertor_start..index])
        } else {
            "str".to_owned()
        };
        if path.get(index).copied() != Some(u32::from(b'}')) {
            search_from = start + 1;
            continue;
        }
        parameters.push(PathParameter {
            start,
            end: index + 1,
            name,
            convertor_name,
        });
        search_from = index + 1;
    }
    parameters
}

fn is_identifier_codepoint_start(codepoint: u32) -> bool {
    u8::try_from(codepoint).is_ok_and(is_identifier_start)
}

fn is_identifier_codepoint_continue(codepoint: u32) -> bool {
    u8::try_from(codepoint).is_ok_and(is_identifier_continue)
}

fn codepoints_ascii_string(codepoints: &[u32]) -> String {
    codepoints
        .iter()
        .filter_map(|codepoint| u8::try_from(*codepoint).ok())
        .map(char::from)
        .collect()
}

fn escape_regex_codepoints(text: &[u32]) -> Vec<u32> {
    let mut escaped = Vec::with_capacity(text.len());
    for codepoint in text {
        if matches!(
            *codepoint,
            40 | 41
                | 91
                | 93
                | 123
                | 125
                | 63
                | 42
                | 43
                | 45
                | 124
                | 94
                | 36
                | 92
                | 46
                | 38
                | 126
                | 35
                | 32
                | 9
                | 10
                | 13
                | 11
                | 12
        ) {
            escaped.push(u32::from(b'\\'));
        }
        escaped.push(*codepoint);
    }
    escaped
}

fn compile_path_parts_compat<'py>(
    py: Python<'py>,
    path: &Bound<'_, PyAny>,
    convertor_types: &Bound<'py, PyDict>,
    builtin_convertors: Option<&Bound<'py, PyDict>>,
) -> PyResult<CompiledCompatibilityPath<'py>> {
    let codepoints = CompatibilityPath::from_python(path)?;
    compile_path_parts_codepoints(py, &codepoints, convertor_types, builtin_convertors)
}

fn compile_path_parts_codepoints<'py>(
    py: Python<'py>,
    path: &CompatibilityPath,
    convertor_types: &Bound<'py, PyDict>,
    builtin_convertors: Option<&Bound<'py, PyDict>>,
) -> PyResult<CompiledCompatibilityPath<'py>> {
    let is_host = !path.starts_with_ascii(b'/');
    let mut path_regex = vec![u32::from(b'^')];
    let mut path_format = Vec::new();
    let mut duplicated_params = HashSet::new();
    let mut parameter_names = HashSet::new();
    let mut index = 0;
    let convertors = PyDict::new(py);
    let mut has_custom = false;
    let mut has_surrogate = path.has_lone_surrogate();

    for parameter in path_parameters_codepoints(&path.0) {
        let convertor = convertor_types
            .get_item(&parameter.convertor_name)?
            .ok_or_else(|| {
                PyAssertionError::new_err(format!(
                    "Unknown path convertor '{}'",
                    parameter.convertor_name
                ))
            })?;

        let static_text = &path.0[index..parameter.start];
        path_regex.extend(escape_regex_codepoints(static_text));
        let converter_regex = CompatibilityPath::from_python(&convertor.getattr("regex")?)?;
        has_surrogate |= converter_regex.has_lone_surrogate();
        append_utf8_codepoints(&mut path_regex, "(?P<");
        append_utf8_codepoints(&mut path_regex, &parameter.name);
        path_regex.push(u32::from(b'>'));
        path_regex.extend_from_slice(&converter_regex.0);
        path_regex.push(u32::from(b')'));
        path_format.extend_from_slice(static_text);
        path_format.push(u32::from(b'{'));
        append_utf8_codepoints(&mut path_format, &parameter.name);
        path_format.push(u32::from(b'}'));
        if !parameter_names.insert(parameter.name.clone()) {
            duplicated_params.insert(parameter.name.clone());
        }
        convertors.set_item(&parameter.name, &convertor)?;
        if let Some(builtins) = builtin_convertors {
            let builtin = builtins.get_item(&parameter.convertor_name)?;
            has_custom |= builtin.is_none_or(|builtin| !convertor.is(&builtin));
        }
        index = parameter.end;
    }

    if !duplicated_params.is_empty() {
        let mut names = duplicated_params.into_iter().collect::<Vec<_>>();
        names.sort();
        let ending = if names.len() > 1 { "s" } else { "" };
        let mut message = Vec::new();
        append_utf8_codepoints(&mut message, "Duplicated param name");
        append_utf8_codepoints(&mut message, ending);
        message.push(u32::from(b' '));
        append_utf8_codepoints(&mut message, &names.join(", "));
        append_utf8_codepoints(&mut message, " at path ");
        message.extend_from_slice(&path.0);
        let message = codepoints_to_python_string(py, &message)?;
        let error = py.get_type::<PyValueError>().call1((message,))?;
        return Err(PyErr::from_value(error));
    }

    let tail = &path.0[index..];
    let regex_tail = if is_host {
        &tail[..tail
            .iter()
            .position(|codepoint| *codepoint == u32::from(b':'))
            .unwrap_or(tail.len())]
    } else {
        tail
    };
    path_regex.extend(escape_regex_codepoints(regex_tail));
    path_regex.push(u32::from(b'$'));
    path_format.extend_from_slice(tail);
    let path_regex = codepoints_to_python_string(py, &path_regex)?;
    let path_format = codepoints_to_python_string(py, &path_format)?;
    let pattern = py.import("re")?.getattr("compile")?.call1((path_regex,))?;
    Ok((pattern, path_format, convertors, has_custom, has_surrogate))
}

fn is_identifier_start(byte: u8) -> bool {
    byte.is_ascii_alphabetic() || byte == b'_'
}

fn is_identifier_continue(byte: u8) -> bool {
    is_identifier_start(byte) || byte.is_ascii_digit()
}

fn host_format_without_port(host_format: &CompatibilityPath) -> CompatibilityPath {
    let suffix_start = host_format
        .0
        .iter()
        .rposition(|codepoint| *codepoint == u32::from(b'}'))
        .map_or(0, |index| index.saturating_add(1));
    let suffix = &host_format.0[suffix_start..];
    let suffix_end = suffix
        .iter()
        .position(|codepoint| *codepoint == u32::from(b':'))
        .map_or(host_format.0.len(), |index| suffix_start + index);
    CompatibilityPath(host_format.0[..suffix_end].to_vec())
}

fn normalize_methods(
    py: Python<'_>,
    methods: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<Py<PySet>>> {
    let Some(methods) = methods else {
        return Ok(None);
    };
    let normalized = PySet::empty(py)?;
    for method in methods.try_iter()? {
        let upper = method?.call_method0("upper")?;
        normalized.add(&upper)?;
    }
    if normalized.contains("GET")? {
        normalized.add("HEAD")?;
    }
    Ok(Some(normalized.unbind()))
}

fn make_route_table(
    py: Python<'_>,
    route_table_type: &Bound<'_, PyAny>,
    path: &str,
    custom: bool,
    methods: Option<&Bound<'_, PySet>>,
) -> PyResult<Py<PyAny>> {
    if custom {
        return Ok(py.None());
    }
    let table = route_table_type.call0()?;
    let methods = methods
        .map(|methods| {
            methods
                .try_iter()?
                .map(|method| method?.extract::<String>())
                .collect::<PyResult<Vec<_>>>()
        })
        .transpose()?
        .unwrap_or_default();
    table.call_method1("add_route", (path, methods))?;
    table.call_method1("_set_compiled_path", (path,))?;
    Ok(table.unbind())
}

fn make_route_table_compat(
    py: Python<'_>,
    route_table_type: &Bound<'_, PyAny>,
    path: &Bound<'_, PyAny>,
    custom: bool,
    has_surrogate: bool,
    methods: Option<&Bound<'_, PySet>>,
) -> PyResult<Py<PyAny>> {
    if has_surrogate {
        return Ok(py.None());
    }
    let path = path.extract::<String>()?;
    make_route_table(py, route_table_type, &path, custom, methods)
}

fn endpoint_name(py: Python<'_>, endpoint: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let class_name = endpoint.getattr("__class__")?.getattr("__name__")?;
    py.import("builtins")?
        .getattr("getattr")?
        .call1((endpoint, "__name__", class_name))
        .map(Bound::unbind)
}

fn is_request_endpoint(py: Python<'_>, endpoint: &Bound<'_, PyAny>) -> PyResult<bool> {
    let partial_type = py.import("functools")?.getattr("partial")?;
    let mut target = endpoint.clone().unbind();
    loop {
        let bound = target.bind(py);
        if !bound.is_instance(&partial_type)? {
            break;
        }
        target = bound.getattr("func")?.unbind();
    }
    let inspect = py.import("inspect")?;
    Ok(inspect
        .getattr("isfunction")?
        .call1((target.bind(py),))?
        .is_truthy()?
        || inspect
            .getattr("ismethod")?
            .call1((target.bind(py),))?
            .is_truthy()?)
}

fn is_async_callable(py: Python<'_>, endpoint: &Bound<'_, PyAny>) -> PyResult<bool> {
    let partial_type = py.import("functools")?.getattr("partial")?;
    let mut target = endpoint.clone().unbind();
    loop {
        let bound = target.bind(py);
        if !bound.is_instance(&partial_type)? {
            break;
        }
        target = bound.getattr("func")?.unbind();
    }
    let version = py.import("sys")?.getattr("version_info")?;
    let major = version.get_item(0)?.extract::<u8>()?;
    let minor = version.get_item(1)?.extract::<u8>()?;
    let detector = if (major, minor) >= (3, 13) {
        py.import("inspect")?.getattr("iscoroutinefunction")?
    } else {
        py.import("asyncio")?.getattr("iscoroutinefunction")?
    };
    if detector.call1((target.bind(py),))?.is_truthy()? {
        return Ok(true);
    }
    if !py
        .import("builtins")?
        .getattr("callable")?
        .call1((target.bind(py),))?
        .is_truthy()?
    {
        return Ok(false);
    }
    detector
        .call1((target.bind(py).getattr("__call__")?,))?
        .is_truthy()
}

fn apply_middleware_inner(
    py: Python<'_>,
    app: &Bound<'_, PyAny>,
    middleware: Option<&Bound<'_, PyAny>>,
    selection: MiddlewareSelection,
    max_body_size: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let mut app = app.clone().unbind();
    let middleware = match (selection, middleware) {
        (MiddlewareSelection::Supplied, middleware) => middleware,
        (MiddlewareSelection::Truthy, Some(middleware)) if middleware.is_truthy()? => {
            Some(middleware)
        }
        (MiddlewareSelection::Truthy, _) => None,
    };
    if let Some(middleware) = middleware {
        for item in py
            .import("builtins")?
            .getattr("reversed")?
            .call1((middleware,))?
            .try_iter()?
        {
            let item = item?;
            let mut fields = item.try_iter()?;
            let middleware_type = fields.next().transpose()?.ok_or_else(|| {
                PyValueError::new_err("not enough values to unpack (expected 3, got 0)")
            })?;
            let positional = fields.next().transpose()?.ok_or_else(|| {
                PyValueError::new_err("not enough values to unpack (expected 3, got 1)")
            })?;
            let keyword_object = fields.next().transpose()?.ok_or_else(|| {
                PyValueError::new_err("not enough values to unpack (expected 3, got 2)")
            })?;
            if fields.next().transpose()?.is_some() {
                return Err(PyValueError::new_err(
                    "too many values to unpack (expected 3)",
                ));
            }
            let mut arguments = vec![app];
            for value in positional.try_iter()? {
                arguments.push(value?.unbind());
            }
            let arguments = PyTuple::new(py, arguments.iter().map(|value| value.bind(py)))?;
            let keyword = middleware_kwargs_to_dict(py, &keyword_object, &middleware_type)?;
            app = middleware_type.call(&arguments, Some(&keyword))?.unbind();
        }
    }
    apply_body_limit(py, app, max_body_size)
}

fn apply_router_middleware_inner(
    py: Python<'_>,
    app: &Bound<'_, PyAny>,
    middleware: Option<&Bound<'_, PyAny>>,
    max_body_size: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    apply_middleware_inner(
        py,
        app,
        middleware,
        MiddlewareSelection::Truthy,
        max_body_size,
    )
}

fn apply_body_limit(
    py: Python<'_>,
    app: Py<PyAny>,
    max_body_size: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let Some(max_body_size) = max_body_size.filter(|value| !value.is_none()) else {
        return Ok(app);
    };
    let middleware_type = py
        .import("starlette.middleware.body_limit")?
        .getattr("RequestBodyLimitMiddleware")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("max_body_size", max_body_size)?;
    middleware_type
        .call((app.bind(py),), Some(&kwargs))
        .map(Bound::unbind)
}

#[pyfunction]
fn apply_route_middleware(
    py: Python<'_>,
    app: &Bound<'_, PyAny>,
    middleware: Option<&Bound<'_, PyAny>>,
    max_body_size: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    apply_middleware_inner(
        py,
        app,
        middleware,
        MiddlewareSelection::Supplied,
        max_body_size,
    )
}

#[pyfunction]
fn route_path(scope: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    route_path_from_scope(scope)
        .map(Bound::into_any)
        .map(Bound::unbind)
}

#[pyfunction]
fn route_matches(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyAny>,
    match_type: &Bound<'_, PyAny>,
    route_kind: &str,
    _builtin_convertors: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    // The pinned route classes use direct indexing for every protocol check.
    // Keep both mapping lookup errors and Python rich-comparison behavior at
    // this boundary instead of extracting the value into a Rust String.
    let scope_type = scope.get_item("type")?;
    let protocol_matches = match route_kind {
        "http" => scope_type.eq("http")?,
        "websocket" => scope_type.eq("websocket")?,
        "mount" | "host" => PyTuple::new(py, ["http", "websocket"])?.contains(&scope_type)?,
        _ => false,
    };
    if !protocol_matches {
        return match_result(py, match_type, "NONE", PyDict::new(py));
    }

    if route_kind == "host" {
        return match host_route_child_scope(py, route, scope)? {
            Some(child_scope) => match_result(py, match_type, "FULL", child_scope.into_bound(py)),
            None => match_result(py, match_type, "NONE", PyDict::new(py)),
        };
    }

    // Mount.matches reads root_path before get_route_path reads path and then
    // root_path again. Retain that first value for the child-scope default.
    let mount_root_path = if route_kind == "mount" {
        Some(scope.call_method1("get", ("root_path", ""))?)
    } else {
        None
    };
    let path = route_path_from_scope(scope)?;
    let mut matched = python_regex_match(py, route, &path, "path_regex")?;
    let Some(matched_params) = matched.take() else {
        return match_result(py, match_type, "NONE", PyDict::new(py));
    };

    if route_kind == "mount" {
        let root_path = mount_root_path
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("Mount root path was not captured"))?;
        return mount_match_result(
            py,
            route,
            scope,
            match_type,
            &path,
            matched_params,
            root_path,
        );
    }

    let path_params = merged_path_params(py, scope, matched_params.bind(py))?;
    let child_scope = PyDict::new(py);
    child_scope.set_item("endpoint", route.getattr("endpoint")?)?;
    child_scope.set_item("path_params", path_params.bind(py))?;
    // Route.matches builds its child scope before it performs method
    // membership, so a missing scope["method"] is observed only after path
    // matching, conversion, and path-parameter merging have succeeded.
    let match_name = if route_kind == "websocket" {
        "FULL"
    } else {
        http_match_name(route, scope)?
    };
    match_result(py, match_type, match_name, child_scope)
}

pub(super) fn host_child_scope(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    host_route_child_scope(py, route, scope)?
        .map(|scope| scope.into_any())
        .ok_or_else(|| PyRuntimeError::new_err("selected Host route did not match its scope"))
}

fn host_route_child_scope(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyAny>,
) -> PyResult<Option<Py<PyDict>>> {
    let host = host_header_value(py, scope)?;
    let hostname = host.split(':').next().unwrap_or_default();
    let hostname = PyString::new(py, hostname);
    let matched_params = python_regex_match(py, route, hostname.as_any(), "host_regex")?;
    let Some(converted) = matched_params else {
        return Ok(None);
    };
    let path_params = merged_path_params(py, scope, converted.bind(py))?;
    let child_scope = PyDict::new(py);
    child_scope.set_item("path_params", path_params.bind(py))?;
    child_scope.set_item("endpoint", route.getattr("app")?)?;
    Ok(Some(child_scope.unbind()))
}

fn host_header_value(py: Python<'_>, scope: &Bound<'_, PyAny>) -> PyResult<String> {
    let headers = scope.get_item("headers")?;
    let headers = py.import("builtins")?.getattr("list")?.call1((headers,))?;
    scope.set_item("headers", &headers)?;
    for entry in headers.try_iter()? {
        let entry = py.import("builtins")?.getattr("tuple")?.call1((entry?,))?;
        let (name, value): (Py<PyAny>, Py<PyAny>) = entry.extract()?;
        // Starlette lowercases the lookup key and compares the raw ASGI bytes exactly.
        let is_host = name
            .bind(py)
            .cast::<PyBytes>()
            .is_ok_and(|header_name| header_name.as_bytes() == b"host");
        if is_host {
            return value
                .bind(py)
                .call_method1("decode", ("latin-1",))?
                .extract::<String>();
        }
    }
    Ok(String::new())
}

fn match_result(
    py: Python<'_>,
    match_type: &Bound<'_, PyAny>,
    name: &str,
    child_scope: Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let result_type = match_type.getattr(name)?;
    Ok(PyTuple::new(py, [result_type, child_scope.into_any()])?
        .into_any()
        .unbind())
}

// CPython's compiled pattern remains the exact matching boundary for converter syntax such as `\N{name}`.
// Route selection, capture conversion, and converter callback ordering stay in Rust after this call.
fn python_regex_match(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    path: &Bound<'_, PyAny>,
    regex_attribute: &str,
) -> PyResult<Option<Py<PyDict>>> {
    let pattern = route.getattr(regex_attribute)?;
    let matched = pattern.call_method1("match", (path,))?;
    if matched.is_none() {
        return Ok(None);
    }
    let captured = matched.call_method0("groupdict")?.cast_into::<PyDict>()?;
    convert_capture_dict(py, route, &captured).map(Some)
}

fn convert_capture_dict<'py>(
    py: Python<'py>,
    route: &Bound<'_, PyAny>,
    captures: &Bound<'_, PyDict>,
) -> PyResult<Py<PyDict>> {
    let converted = PyDict::new(py);
    let convertors = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    for (name, value) in dict_items_as_py(captures)? {
        let convertor = convertors
            .get_item(&name)?
            .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
        converted.set_item(name, convertor.call_method1("convert", (value.bind(py),))?)?;
    }
    Ok(converted.unbind())
}

fn http_match_name(route: &Bound<'_, PyAny>, scope: &Bound<'_, PyAny>) -> PyResult<&'static str> {
    let methods = route.getattr("methods")?;
    if methods.is_none() || !methods.is_truthy()? {
        return Ok("FULL");
    }
    // Route.matches uses Python set membership on the original scope value.
    // Calling membership directly preserves custom hash/equality behavior and
    // the exact error for malformed method values.
    let method = scope.get_item("method")?;
    if methods.contains(&method)? {
        Ok("FULL")
    } else {
        Ok("PARTIAL")
    }
}

fn mount_match_result(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyAny>,
    match_type: &Bound<'_, PyAny>,
    route_path: &Bound<'_, PyAny>,
    converted: Py<PyDict>,
    outer_root_path: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let params = converted.bind(py);
    let remainder = params
        .get_item("path")?
        .ok_or_else(|| PyRuntimeError::new_err("Mount converter omitted its path parameter"))?;
    params.del_item("path")?;
    let operator = py.import("operator")?;
    let remaining_path = operator
        .getattr("add")?
        .call1((PyString::new(py, "/"), remainder))?;
    let negative_length = operator.getattr("neg")?.call1((remaining_path.len()?,))?;
    let route_slice =
        py.import("builtins")?
            .getattr("slice")?
            .call1((py.None(), negative_length, py.None()))?;
    // Mount.matches slices the original route_path after regex conversion.
    // Keep Python's __getitem__ dispatch and exceptions visible for str
    // subclasses instead of deriving the prefix from Rust string lengths.
    let matched_path = route_path.get_item(route_slice)?;
    let path_params = merged_path_params(py, scope, params)?;
    let app_root_path = scope.call_method1("get", ("app_root_path", outer_root_path))?;
    let child_root_path = operator
        .getattr("add")?
        .call1((outer_root_path, matched_path))?;
    let child_scope = PyDict::new(py);
    child_scope.set_item("path_params", path_params.bind(py))?;
    child_scope.set_item("app_root_path", app_root_path)?;
    child_scope.set_item("root_path", child_root_path)?;
    child_scope.set_item("endpoint", route.getattr("app")?)?;
    match_result(py, match_type, "FULL", child_scope)
}

fn merged_path_params(
    py: Python<'_>,
    scope: &Bound<'_, PyAny>,
    matched_params: &Bound<'_, PyDict>,
) -> PyResult<Py<PyDict>> {
    let path_params = PyDict::new(py);
    if let Some(existing) = crate::scope_mapping::optional_item(scope, "path_params")? {
        path_params.call_method1("update", (existing,))?;
    }
    path_params.call_method1("update", (matched_params,))?;
    Ok(path_params.unbind())
}

pub(super) fn route_path_from_scope<'py>(scope: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    // Match get_route_path's Python operations in source order. In particular,
    // keep the original path object so str-subclass methods and slicing, as
    // well as their exceptions, remain observable at the Rust call boundary.
    let path = scope.get_item("path")?;
    let root_path = scope.call_method1("get", ("root_path", ""))?;
    if !root_path.is_truthy()? {
        return Ok(path);
    }
    if !path
        .call_method1("startswith", (&root_path,))?
        .is_truthy()?
    {
        return Ok(path);
    }
    if path.rich_compare(&root_path, CompareOp::Eq)?.is_truthy()? {
        return Ok(PyString::new(scope.py(), "").into_any());
    }

    let first_index = root_path.len()?;
    if path
        .get_item(first_index)?
        .rich_compare("/", CompareOp::Eq)?
        .is_truthy()?
    {
        // The pinned source evaluates len(root_path) again when creating the
        // slice; don't cache the first result, since a str subclass may expose
        // observable __len__ behavior.
        let slice_start = root_path.len()?;
        let slice = scope.py().import("builtins")?.getattr("slice")?.call1((
            slice_start,
            scope.py().None(),
            scope.py().None(),
        ))?;
        return path.get_item(slice);
    }
    Ok(path)
}

fn dict_keys_as_strings(dict: &Bound<'_, PyDict>) -> PyResult<Vec<String>> {
    dict.keys()
        .try_iter()?
        .map(|name| name?.extract::<String>())
        .collect()
}

#[pyfunction]
fn route_handle(py: Python<'_>, args: RouteHandleArgs) -> PyResult<Py<PyAny>> {
    let RouteHandleArgs {
        route,
        scope,
        receive,
        send,
        route_kind,
        http_exception_type,
        plain_text_response_type,
    } = args;
    let route = route.bind(py);
    let scope = scope.bind(py);
    let receive = receive.bind(py);
    let send = send.bind(py);
    let http_exception_type = http_exception_type.bind(py);
    let plain_text_response_type = plain_text_response_type.bind(py);
    if route_kind == "http" {
        let methods = route.getattr("methods")?;
        if !methods.is_none() && methods.is_truthy()? {
            let method = scope.get_item("method")?;
            if !methods.contains(&method)? {
                let joined_methods = PyString::new(py, ", ").call_method1("join", (methods,))?;
                let headers = PyDict::new(py);
                headers.set_item("Allow", joined_methods)?;
                if scope.contains("app")? {
                    let kwargs = PyDict::new(py);
                    kwargs.set_item("status_code", 405)?;
                    kwargs.set_item("headers", headers)?;
                    return Err(PyErr::from_value(
                        http_exception_type.call((), Some(&kwargs))?,
                    ));
                }
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", 405)?;
                kwargs.set_item("headers", headers)?;
                let response =
                    plain_text_response_type.call(("Method Not Allowed",), Some(&kwargs))?;
                return response.call1((scope, receive, send)).map(Bound::unbind);
            }
        }
    }
    route
        .getattr("app")?
        .call1((scope, receive, send))
        .map(Bound::unbind)
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct RouteHandleArgs {
    route: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    route_kind: String,
    http_exception_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
}

#[pyfunction]
fn base_route_call(
    py: Python<'_>,
    route: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        BaseRouteCallMachine {
            route,
            scope,
            receive,
            send,
            plain_text_response_type,
            websocket_close_type,
            pending: false,
        },
    )
}

struct BaseRouteCallMachine {
    route: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    websocket_close_type: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for BaseRouteCallMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.route)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.plain_text_response_type)?;
        visit.call(&self.websocket_close_type)?;
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
            MachineResume::AsyncIterationComplete(error) => {
                self.resume(py, MachineResume::Error(error))
            }
            _ => Err(PyRuntimeError::new_err(
                "base route call resumed without a pending operation",
            )),
        }
    }
}

impl BaseRouteCallMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let route_match = self.route.bind(py).call_method1("matches", (scope,))?;
        let route_match = route_match.cast::<PyTuple>()?;
        let match_kind = route_match.get_item(0)?.getattr("value")?.extract::<u8>()?;
        if match_kind == 0 {
            let callback = if scope.get_item("type")?.eq("http")? {
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", 404)?;
                self.plain_text_response_type
                    .bind(py)
                    .call(("Not Found",), Some(&kwargs))?
                    .call1((scope, self.receive.bind(py), self.send.bind(py)))?
            } else if scope.get_item("type")?.eq("websocket")? {
                self.websocket_close_type.bind(py).call0()?.call1((
                    scope,
                    self.receive.bind(py),
                    self.send.bind(py),
                ))?
            } else {
                return Ok(MachineAction::Complete(py.None()));
            };
            self.pending = true;
            return Ok(MachineAction::Await(callback.unbind()));
        }

        scope.call_method1("update", (route_match.get_item(1)?,))?;
        let callback = self
            .route
            .bind(py)
            .call_method1("handle", (scope, self.receive.bind(py), self.send.bind(py)))?;
        self.pending = true;
        Ok(MachineAction::Await(callback.unbind()))
    }
}

#[pyfunction]
fn route_format_path_params(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
    partial: bool,
) -> PyResult<(Py<PyAny>, Py<PyDict>)> {
    let (path, remaining) = format_route_path_params(py, route, path_params, partial)?;
    Ok((path.into_any().unbind(), remaining))
}

fn format_route_path_params<'py>(
    py: Python<'py>,
    route: &Bound<'py, PyAny>,
    path_params: &Bound<'py, PyDict>,
    partial: bool,
) -> PyResult<(Bound<'py, PyString>, Py<PyDict>)> {
    let table = route.getattr("_route_table")?;
    let mut path = CompatibilityPath::from_python(&route.getattr("path_format")?)?;
    let mut formatted = Vec::new();
    let mut all_formatted_values_are_utf8 = true;
    let mut consumed = HashSet::new();
    let convertors = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    for (name, value) in dict_items_as_py(path_params)? {
        let placeholder = CompatibilityPath::from_utf8(&format!("{{{name}}}"));
        if !partial || path.contains(&placeholder.0) {
            let convertor = convertors
                .get_item(&name)?
                .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
            let formatted_value = convertor.call_method1("to_string", (value.bind(py),))?;
            let formatted_path = CompatibilityPath::from_python(&formatted_value)?;
            if let Some(formatted_value) = formatted_path.to_utf8() {
                formatted.push((name.clone(), formatted_value));
            } else {
                all_formatted_values_are_utf8 = false;
            }
            if path.contains(&placeholder.0) {
                path.replace_all(&placeholder.0, &formatted_path.0);
                consumed.insert(name);
            }
        }
    }

    if !table.is_none() && !path.has_lone_surrogate() && all_formatted_values_are_utf8 {
        let built = if partial {
            table.call_method1("build_path_partial", (0, formatted))?
        } else {
            table.call_method1("build_path", (0, formatted))?
        };
        let built = if partial { built.get_item(0)? } else { built };
        path = CompatibilityPath::from_python(&built)?;
    }

    let remaining = PyDict::new(py);
    for (name, value) in dict_items_as_py(path_params)? {
        if !consumed.contains(&name) {
            remaining.set_item(name, value.bind(py))?;
        }
    }
    Ok((path.to_python(py)?, remaining.unbind()))
}

fn format_host_path_params<'py>(
    py: Python<'py>,
    host: &Bound<'py, PyAny>,
    path_params: &Bound<'py, PyDict>,
) -> PyResult<(Bound<'py, PyString>, Py<PyDict>)> {
    let mut formatted_host = CompatibilityPath::from_python(&host.getattr("host_format")?)?;
    let convertors = host.getattr("param_convertors")?.cast_into::<PyDict>()?;
    let remaining = PyDict::new(py);
    for (name, value) in dict_items_as_py(path_params)? {
        let placeholder = CompatibilityPath::from_utf8(&format!("{{{name}}}"));
        if formatted_host.contains(&placeholder.0) {
            let convertor = convertors
                .get_item(&name)?
                .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
            let value = convertor.call_method1("to_string", (value.bind(py),))?;
            let value = CompatibilityPath::from_python(&value)?;
            formatted_host.replace_all(&placeholder.0, &value.0);
        } else {
            remaining.set_item(name, value.bind(py))?;
        }
    }
    Ok((formatted_host.to_python(py)?, remaining.unbind()))
}

#[pyfunction]
fn route_url_path_for(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
    no_match_type: &Bound<'_, PyAny>,
    url_path_type: &Bound<'_, PyAny>,
    protocol: &str,
) -> PyResult<Py<PyAny>> {
    let route_name = route.getattr("name")?;
    let converters = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    let mut expected = dict_keys_as_strings(&converters)?;
    let mut provided = path_params
        .keys()
        .try_iter()?
        .map(|key| key?.extract::<String>())
        .collect::<PyResult<Vec<_>>>()?;
    expected.sort();
    provided.sort();
    if !route_name.rich_compare(name, CompareOp::Eq)?.is_truthy()? || expected != provided {
        return raise_no_match(no_match_type, name, path_params);
    }
    let (path, remaining) = format_route_path_params(py, route, path_params, false)?;
    if !remaining.bind(py).is_empty() {
        return Err(PyAssertionError::new_err(
            "route path parameters were not fully formatted",
        ));
    }
    let kwargs = PyDict::new(py);
    kwargs.set_item("path", path)?;
    kwargs.set_item("protocol", protocol)?;
    url_path_type.call((), Some(&kwargs)).map(Bound::unbind)
}

#[pyfunction]
fn mount_url_path_for(
    py: Python<'_>,
    mount: &Bound<'_, PyAny>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
    no_match_type: &Bound<'_, PyAny>,
    url_path_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let mut current_params = path_params.copy()?.cast_into::<PyDict>()?;
    let mount_name = mount.getattr("name")?;
    let has_name = !mount_name.is_none();
    let name_matches_mount =
        has_name && mount_name.rich_compare(name, CompareOp::Eq)?.is_truthy()?;
    if name_matches_mount && current_params.contains("path")? {
        let path_value = current_params
            .get_item("path")?
            .ok_or_else(|| PyKeyError::new_err("path"))?;
        current_params.set_item("path", path_value.call_method1("lstrip", ("/",))?)?;
        let (path, remaining) = format_route_path_params(py, mount, &current_params, true)?;
        current_params = remaining.into_bound(py);
        if current_params.is_empty() {
            let kwargs = PyDict::new(py);
            kwargs.set_item("path", path)?;
            return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
        }
    } else if mount_name.is_none() || named_route_prefix_matches(py, name, &mount_name)? {
        let nested_name = if mount_name.is_none() {
            name.clone()
        } else {
            name_after_named_prefix(py, name, &mount_name)?
        };
        let path_kwarg = current_params
            .get_item("path")?
            .filter(|value| !value.is_none());
        current_params.set_item("path", "")?;
        let (path_prefix, remaining_params) =
            format_route_path_params(py, mount, &current_params, true)?;
        if let Some(path_kwarg) = path_kwarg {
            remaining_params.bind(py).set_item("path", path_kwarg)?;
        }
        let routes = mount.getattr("routes")?;
        if routes.is_truthy()? {
            for route in routes.try_iter()? {
                let route = route?;
                match route.call_method(
                    "url_path_for",
                    (nested_name.clone(),),
                    Some(remaining_params.bind(py)),
                ) {
                    Ok(url) => {
                        let url_text = py.import("builtins")?.getattr("str")?.call1((&url,))?;
                        let mut full_path = CompatibilityPath::from_python(path_prefix.as_any())?;
                        full_path.trim_end_ascii(b'/');
                        full_path
                            .0
                            .extend_from_slice(&CompatibilityPath::from_python(&url_text)?.0);
                        let full_path = full_path.to_python(py)?;
                        let kwargs = PyDict::new(py);
                        kwargs.set_item("path", full_path)?;
                        kwargs.set_item("protocol", url.getattr("protocol")?)?;
                        return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
                    }
                    Err(error) if error.value(py).is_instance(no_match_type)? => {}
                    Err(error) => return Err(error),
                }
            }
        }
        current_params = remaining_params.into_bound(py);
    }
    raise_no_match(no_match_type, name, &current_params)
}

#[pyfunction]
fn host_url_path_for(
    py: Python<'_>,
    host: &Bound<'_, PyAny>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
    no_match_type: &Bound<'_, PyAny>,
    url_path_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let mut failure_params = path_params.copy()?.cast_into::<PyDict>()?;
    let host_name = host.getattr("name")?;
    if !host_name.is_none()
        && host_name.rich_compare(name, CompareOp::Eq)?.is_truthy()?
        && failure_params.contains("path")?
    {
        let path_value = failure_params
            .get_item("path")?
            .ok_or_else(|| PyKeyError::new_err("path"))?;
        failure_params.del_item("path")?;
        let (host_value, remaining) = format_host_path_params(py, host, &failure_params)?;
        let no_parameters_remain = remaining.bind(py).is_empty();
        // Starlette's replace_params mutates the kwargs dict as host parameters
        // are consumed, so a failed direct Host lookup reports only leftovers.
        failure_params = remaining.into_bound(py);
        if no_parameters_remain {
            let kwargs = PyDict::new(py);
            kwargs.set_item("path", path_value)?;
            kwargs.set_item("host", host_value)?;
            return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
        }
    } else if host_name.is_none() || named_route_prefix_matches(py, name, &host_name)? {
        let nested_name = if host_name.is_none() {
            name.clone().unbind()
        } else {
            name_after_named_prefix(py, name, &host_name)?.unbind()
        };
        let (host_value, remaining_params) = format_host_path_params(py, host, path_params)?;
        let app = host.getattr("app")?;
        let mut routes = route_children(py, &app)?;
        if routes.bind(py).is_none() || !routes.bind(py).is_truthy()? {
            routes = PyList::empty(py).into_any().unbind();
        }
        for route in routes.bind(py).try_iter()? {
            let route = route?;
            match route.call_method(
                "url_path_for",
                (nested_name.bind(py),),
                Some(remaining_params.bind(py)),
            ) {
                Ok(url) => {
                    let path = py.import("builtins")?.getattr("str")?.call1((&url,))?;
                    let kwargs = PyDict::new(py);
                    kwargs.set_item("path", path)?;
                    kwargs.set_item("protocol", url.getattr("protocol")?)?;
                    kwargs.set_item("host", host_value)?;
                    return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
                }
                Err(error) if error.value(py).is_instance(no_match_type)? => {}
                Err(error) => return Err(error),
            }
        }
        // Match the mutated kwargs passed to the final NoMatchFound in
        // Starlette Host.url_path_for after prefix parameters were formatted.
        failure_params = remaining_params.into_bound(py);
    }
    raise_no_match(no_match_type, name, &failure_params)
}

fn named_route_prefix_matches(
    py: Python<'_>,
    name: &Bound<'_, PyAny>,
    route_name: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let prefix = py
        .import("operator")?
        .getattr("add")?
        .call1((route_name, ":"))?;
    name.call_method1("startswith", (&prefix,))?.is_truthy()
}

fn name_after_named_prefix<'py>(
    py: Python<'py>,
    name: &Bound<'py, PyAny>,
    route_name: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let start = route_name.len()? + 1;
    let slice = py
        .import("builtins")?
        .getattr("slice")?
        .call1((start, py.None(), py.None()))?;
    name.get_item(slice)
}

fn raise_no_match(
    no_match_type: &Bound<'_, PyAny>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    Err(PyErr::from_value(no_match_type.call1((name, path_params))?))
}

fn dict_items_as_py(dict: &Bound<'_, PyDict>) -> PyResult<Vec<(String, Py<PyAny>)>> {
    dict.items()
        .try_iter()?
        .map(|item| {
            let item = item?.cast_into::<PyTuple>()?;
            Ok((
                item.get_item(0)?.extract::<String>()?,
                item.get_item(1)?.unbind(),
            ))
        })
        .collect()
}

#[pyfunction]
fn request_response(py: Python<'_>, args: RequestResponseArgs) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        RequestResponseMachine {
            endpoint: args.endpoint,
            scope: args.scope,
            receive: args.receive,
            send: args.send,
            request_type: args.request_type,
            http_exception_type: args.http_exception_type,
            run_in_threadpool: args.run_in_threadpool,
            request: None,
            sender: None,
            response_started: Arc::new(AtomicBool::new(false)),
            original_exception: None,
            pending: None,
        },
    )
}

#[pyfunction]
fn websocket_session(py: Python<'_>, args: WebSocketSessionArgs) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        WebSocketSessionMachine {
            endpoint: args.endpoint,
            scope: args.scope,
            receive: args.receive,
            send: args.send,
            websocket_type: args.websocket_type,
            http_exception_type: args.http_exception_type,
            run_in_threadpool: args.run_in_threadpool,
            websocket: None,
            sender: None,
            response_started: Arc::new(AtomicBool::new(false)),
            original_exception: None,
            pending: None,
        },
    )
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct WebSocketSessionArgs {
    endpoint: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    websocket_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
}

#[derive(Clone, Copy)]
enum WebSocketSessionPending {
    Endpoint,
    Handler,
    Response,
}

/// Mirrors Starlette's `websocket_session` boundary around the endpoint.
///
/// This wrapper sits inside `WebSocketRoute` middleware, so it must apply the
/// exception handlers stored by the outer `ExceptionMiddleware` before a
/// route-local middleware can observe endpoint exceptions.
struct WebSocketSessionMachine {
    endpoint: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    websocket_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
    websocket: Option<Py<PyAny>>,
    sender: Option<Py<PyAny>>,
    response_started: Arc<AtomicBool>,
    original_exception: Option<Py<PyAny>>,
    pending: Option<WebSocketSessionPending>,
}

impl AwaitableStateMachine for WebSocketSessionMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.endpoint)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.websocket_type)?;
        visit.call(&self.http_exception_type)?;
        visit.call(&self.run_in_threadpool)?;
        visit.call(&self.websocket)?;
        visit.call(&self.sender)?;
        visit.call(&self.original_exception)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "WebSocket session already has an operation pending",
            )),
            MachineResume::Value(value) => match self.pending.take() {
                Some(WebSocketSessionPending::Endpoint | WebSocketSessionPending::Response) => {
                    Ok(MachineAction::Complete(py.None()))
                }
                Some(WebSocketSessionPending::Handler) if value.bind(py).is_none() => {
                    Ok(MachineAction::Complete(py.None()))
                }
                Some(WebSocketSessionPending::Handler) => self.send_handler_response(py, value),
                None => Err(PyRuntimeError::new_err(
                    "WebSocket session resumed without a pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(WebSocketSessionPending::Endpoint) => self.handle_exception(py, error),
                Some(WebSocketSessionPending::Handler | WebSocketSessionPending::Response) => {
                    Err(self.chain_to_original(py, error))
                }
                None => Err(error),
            },
            MachineResume::AsyncIterationComplete(error) => {
                self.resume(py, MachineResume::Error(error))
            }
        }
    }
}

impl WebSocketSessionMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let websocket = self.websocket_type.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.websocket = Some(websocket.clone().unbind());
        self.sender = Some(exception_send_proxy(
            py,
            self.send.clone_ref(py),
            self.response_started.clone(),
        )?);
        let callback = match self.endpoint.bind(py).call1((websocket,)) {
            Ok(callback) => callback,
            Err(error) => return self.handle_exception(py, error),
        };
        self.pending = Some(WebSocketSessionPending::Endpoint);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn handle_exception(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if !error.is_instance_of::<PyException>(py) {
            return Err(error);
        }
        let exception = error.value(py).clone().into_any().unbind();
        self.original_exception = Some(exception.clone_ref(py));
        let handler = self
            .select_exception_handler(py, exception.bind(py))
            .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        let Some(handler) = handler else {
            return Err(error);
        };
        if handler.bind(py).is_none() {
            return Err(error);
        }
        if self.response_started.load(Ordering::Relaxed) {
            let handled_error =
                PyRuntimeError::new_err("Caught handled exception, but response already started.");
            handled_error.set_cause(py, Some(error));
            return Err(handled_error);
        }

        let websocket = self
            .websocket
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocket session lost its connection"))?;
        let is_async = crate::background::is_async_callable(py, handler.bind(py))
            .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        let callback = if is_async {
            handler
                .bind(py)
                .call1((websocket.bind(py), exception.bind(py)))
        } else {
            self.run_in_threadpool.bind(py).call1((
                handler.bind(py),
                websocket.bind(py),
                exception.bind(py),
            ))
        }
        .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        self.pending = Some(WebSocketSessionPending::Handler);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn select_exception_handler(
        &self,
        py: Python<'_>,
        exception: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let scope = self.scope.bind(py);
        let Some(handlers) =
            crate::scope_mapping::optional_item(scope, "starlette.exception_handlers")?
        else {
            return Ok(None);
        };
        let handlers = handlers.cast::<PyTuple>()?;
        let exception_handlers_value = handlers.get_item(0)?;
        let exception_handlers = exception_handlers_value.cast::<PyDict>()?;
        let status_handlers_value = handlers.get_item(1)?;
        let status_handlers = status_handlers_value.cast::<PyDict>()?;

        if exception.is_instance(self.http_exception_type.bind(py))? {
            let status_code = exception.getattr("status_code")?;
            if let Some(handler) = status_handlers.get_item(status_code)? {
                if !handler.is_none() {
                    return Ok(Some(handler.unbind()));
                }
            }
        }

        for exception_class in exception
            .get_type()
            .getattr("__mro__")?
            .cast::<PyTuple>()?
            .iter()
        {
            if let Some(handler) = exception_handlers.get_item(&exception_class)? {
                return Ok(Some(handler.unbind()));
            }
        }
        Ok(None)
    }

    fn send_handler_response(
        &mut self,
        py: Python<'_>,
        response: Py<PyAny>,
    ) -> PyResult<MachineAction> {
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocket session lost its send callback"))?;
        let callback = match response.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            sender.bind(py),
        )) {
            Ok(callback) => callback,
            Err(error) => return Err(self.chain_to_original(py, error)),
        };
        self.pending = Some(WebSocketSessionPending::Response);
        Ok(MachineAction::Await(callback.unbind()))
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

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct RequestResponseArgs {
    endpoint: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    request_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
}

#[derive(Clone, Copy)]
enum RequestResponsePending {
    Endpoint,
    Response,
    ExceptionHandler,
    ExceptionResponse,
}

struct RequestResponseMachine {
    endpoint: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    request_type: Py<PyAny>,
    http_exception_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
    request: Option<Py<PyAny>>,
    sender: Option<Py<PyAny>>,
    response_started: Arc<AtomicBool>,
    original_exception: Option<Py<PyAny>>,
    pending: Option<RequestResponsePending>,
}

impl AwaitableStateMachine for RequestResponseMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.endpoint)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.request_type)?;
        visit.call(&self.http_exception_type)?;
        visit.call(&self.run_in_threadpool)?;
        visit.call(&self.request)?;
        visit.call(&self.sender)?;
        visit.call(&self.original_exception)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => self.resume_value(py, value),
            MachineResume::Error(error) => self.resume_error(py, error),
            MachineResume::AsyncIterationComplete(error) => {
                self.resume(py, MachineResume::Error(error))
            }
            _ => Err(PyRuntimeError::new_err(
                "request endpoint resumed without a pending operation",
            )),
        }
    }
}

impl RequestResponseMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let request = self
            .request_type
            .bind(py)
            .call1((
                self.scope.bind(py),
                self.receive.bind(py),
                self.send.bind(py),
            ))?
            .unbind();
        let callback = if is_async_callable(py, self.endpoint.bind(py))? {
            self.endpoint.bind(py).call1((request.bind(py),))?
        } else {
            self.run_in_threadpool
                .bind(py)
                .call1((self.endpoint.bind(py), request.bind(py)))?
        };
        self.sender = Some(exception_send_proxy(
            py,
            self.send.clone_ref(py),
            self.response_started.clone(),
        )?);
        self.request = Some(request);
        self.pending = Some(RequestResponsePending::Endpoint);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn resume_value(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(RequestResponsePending::Endpoint) => {
                self.await_response(py, value, RequestResponsePending::Response)
            }
            Some(RequestResponsePending::ExceptionHandler) if value.bind(py).is_none() => {
                Ok(MachineAction::Complete(py.None()))
            }
            Some(RequestResponsePending::ExceptionHandler) => {
                self.await_response(py, value, RequestResponsePending::ExceptionResponse)
            }
            Some(RequestResponsePending::Response | RequestResponsePending::ExceptionResponse) => {
                Ok(MachineAction::Complete(py.None()))
            }
            None => Err(PyRuntimeError::new_err(
                "request endpoint completed without a pending operation",
            )),
        }
    }

    fn await_response(
        &mut self,
        py: Python<'_>,
        response: Py<PyAny>,
        pending: RequestResponsePending,
    ) -> PyResult<MachineAction> {
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("request endpoint lost its send callback"))?;
        let callback = match response.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            sender.bind(py),
        )) {
            Ok(callback) => callback,
            Err(error) => {
                return match pending {
                    RequestResponsePending::Response => self.handle_exception(py, error),
                    RequestResponsePending::ExceptionResponse => {
                        Err(self.chain_to_original(py, error))
                    }
                    RequestResponsePending::Endpoint | RequestResponsePending::ExceptionHandler => {
                        Err(PyRuntimeError::new_err(
                            "request response entered an invalid pending state",
                        ))
                    }
                };
            }
        };
        self.pending = Some(pending);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(RequestResponsePending::Endpoint | RequestResponsePending::Response) => {
                self.handle_exception(py, error)
            }
            Some(
                RequestResponsePending::ExceptionHandler
                | RequestResponsePending::ExceptionResponse,
            ) => Err(self.chain_to_original(py, error)),
            None => Err(error),
        }
    }

    fn handle_exception(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if !error.is_instance_of::<PyException>(py) {
            return Err(error);
        }
        let exception = error.value(py).clone().into_any().unbind();
        self.original_exception = Some(exception.clone_ref(py));
        let handler = self
            .select_exception_handler(py, exception.bind(py))
            .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        let Some(handler) = handler else {
            return self.preserve_request_and_raise(py, error);
        };
        if handler.bind(py).is_none() {
            return self.preserve_request_and_raise(py, error);
        }
        if self.response_started.load(Ordering::Relaxed) {
            let handled_error =
                PyRuntimeError::new_err("Caught handled exception, but response already started.");
            handled_error.set_cause(py, Some(error));
            return Err(handled_error);
        }

        let request = self
            .request
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("request endpoint lost its Request object"))?;
        let is_async = crate::background::is_async_callable(py, handler.bind(py))
            .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        let callback = if is_async {
            handler
                .bind(py)
                .call1((request.bind(py), exception.bind(py)))
        } else {
            self.run_in_threadpool.bind(py).call1((
                handler.bind(py),
                request.bind(py),
                exception.bind(py),
            ))
        }
        .map_err(|handler_error| self.chain_to_original(py, handler_error))?;
        self.pending = Some(RequestResponsePending::ExceptionHandler);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn select_exception_handler(
        &self,
        py: Python<'_>,
        exception: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let scope = self.scope.bind(py);
        let Some(handlers) =
            crate::scope_mapping::optional_item(scope, "starlette.exception_handlers")?
        else {
            return Ok(None);
        };
        let handlers = handlers.cast::<PyTuple>()?;
        let exception_handlers_value = handlers.get_item(0)?;
        let exception_handlers = exception_handlers_value.cast::<PyDict>()?;
        let status_handlers_value = handlers.get_item(1)?;
        let status_handlers = status_handlers_value.cast::<PyDict>()?;

        if exception.is_instance(self.http_exception_type.bind(py))? {
            let status_code = exception.getattr("status_code")?;
            if let Some(handler) = status_handlers.get_item(status_code)? {
                if !handler.is_none() {
                    return Ok(Some(handler.unbind()));
                }
            }
        }

        for exception_class in exception
            .get_type()
            .getattr("__mro__")?
            .cast::<PyTuple>()?
            .iter()
        {
            if let Some(handler) = exception_handlers.get_item(&exception_class)? {
                return Ok(Some(handler.unbind()));
            }
        }
        Ok(None)
    }

    fn preserve_request_and_raise(&self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let request = self
            .request
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("request endpoint lost its Request object"))?;
        scope.set_item("starlette._exception_request", request.bind(py))?;
        Err(error)
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
