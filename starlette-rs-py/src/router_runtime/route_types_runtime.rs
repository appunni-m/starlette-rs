//! Rust-owned construction and behavior for the public route classes.
//!
//! Python remains the call boundary for regex objects, registered converters,
//! middleware constructors, and endpoint adapters. Route ordering, scope
//! decisions, and path formatting live here.

use std::collections::HashSet;

use pyo3::class::basic::CompareOp;
use pyo3::exceptions::{
    PyAssertionError, PyKeyError, PyNotImplementedError, PyRuntimeError, PyStopAsyncIteration,
    PyStopIteration, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyList, PySet, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

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
    module.add_function(wrap_pyfunction!(router_lifespan, module)?)?;
    module.add_class::<PyDefaultLifespanRuntime>()?;
    module.add_class::<PySyncGeneratorLifespanFactory>()?;
    module.add_class::<PyAsyncGeneratorLifespanFactory>()?;
    module.add_class::<PySyncGeneratorLifespanContextManager>()?;
    module.add_class::<PyAsyncGeneratorLifespanContextManager>()?;
    Ok(())
}

#[pyclass(name = "_DefaultLifespanRuntime", unsendable)]
struct PyDefaultLifespanRuntime {
    #[allow(dead_code)]
    router: Py<PyAny>,
}

/// Callable adapter created by Rust for deprecated synchronous generator lifespans.
#[pyclass(name = "_SyncGeneratorLifespanFactory", dict, unsendable)]
struct PySyncGeneratorLifespanFactory {
    lifespan: Py<PyAny>,
}

#[pymethods]
impl PySyncGeneratorLifespanFactory {
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
#[pyclass(name = "_AsyncGeneratorLifespanFactory", dict, unsendable)]
struct PyAsyncGeneratorLifespanFactory {
    lifespan: Py<PyAny>,
}

#[pymethods]
impl PyAsyncGeneratorLifespanFactory {
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
#[pyclass(name = "_SyncGeneratorLifespanContextManager", unsendable)]
struct PySyncGeneratorLifespanContextManager {
    generator: Py<PyAny>,
}

#[pymethods]
impl PySyncGeneratorLifespanContextManager {
    fn __aenter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
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
        into_python_awaitable(
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
#[pyclass(name = "_AsyncGeneratorLifespanContextManager", unsendable)]
struct PyAsyncGeneratorLifespanContextManager {
    generator: Py<PyAny>,
}

#[pymethods]
impl PyAsyncGeneratorLifespanContextManager {
    fn __aenter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_python_awaitable(
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
        into_python_awaitable(
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
    into_python_awaitable(py, BaseRouteUnimplemented)
}

#[pyfunction]
fn default_lifespan_runtime(py: Python<'_>, router: Py<PyAny>) -> PyResult<Py<PyAny>> {
    Py::new(py, PyDefaultLifespanRuntime { router }).map(|value| value.into_any())
}

#[pyfunction]
fn default_lifespan_transition(py: Python<'_>, _runtime: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    into_python_awaitable(py, DefaultLifespanTransition)
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
    into_python_awaitable(
        py,
        RouterLifespanMachine {
            lifespan_context,
            context_manager: None,
            scope,
            receive,
            send,
            pending: None,
        },
    )
}

enum RouterLifespanPending {
    StartupReceive,
    Enter,
    StartupSend,
    ShutdownReceive,
    NormalExit,
    ErrorExit { original: PyErr, started: bool },
    FailureSend { original: PyErr },
    ShutdownComplete,
}

struct RouterLifespanMachine {
    lifespan_context: Py<PyAny>,
    context_manager: Option<Py<PyAny>>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: Option<RouterLifespanPending>,
}

impl AwaitableStateMachine for RouterLifespanMachine {
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
            MachineResume::AsyncIterationComplete(_) => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
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
                    Ok(false) => self.send_failure(py, original, started),
                    Err(error) => self.send_failure(py, error, started),
                }
            }
            RouterLifespanPending::FailureSend { original } => Err(original),
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
            RouterLifespanPending::StartupReceive
            | RouterLifespanPending::FailureSend { .. }
            | RouterLifespanPending::ShutdownComplete => Err(error),
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
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let app = scope
            .get_item("app")?
            .unwrap_or_else(|| py.None().into_bound(py));
        let context_manager = match self.lifespan_context.bind(py).call1((app,)) {
            Ok(context_manager) => context_manager,
            Err(error) => return self.send_failure(py, error, false),
        };
        // `async with` resolves special methods on the manager's type, even when
        // an instance has attributes with the same names.
        let enter = match context_manager
            .get_type()
            .getattr("__aenter__")
            .and_then(|method| method.call1((context_manager.clone(),)))
        {
            Ok(enter) => enter,
            Err(error) => return self.send_failure(py, error, false),
        };
        self.context_manager = Some(context_manager.unbind());
        self.pending = Some(RouterLifespanPending::Enter);
        Ok(MachineAction::Await(enter.unbind()))
    }

    fn entered(&mut self, py: Python<'_>, maybe_state: Py<PyAny>) -> PyResult<MachineAction> {
        if !maybe_state.bind(py).is_none() {
            let state_update = (|| -> PyResult<()> {
                let scope = self.scope.bind(py).cast::<PyDict>()?;
                let state = scope.get_item("state")?.ok_or_else(|| {
                    PyRuntimeError::new_err(
                        "The server does not support \"state\" in the lifespan scope.",
                    )
                })?;
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
        let Some(context_manager) = self.context_manager.as_ref() else {
            return Err(PyRuntimeError::new_err(
                "lifespan context manager was not entered",
            ));
        };
        let context_manager = context_manager.bind(py);
        let exit = match context_manager
            .get_type()
            .getattr("__aexit__")
            .and_then(|method| method.call1((context_manager, py.None(), py.None(), py.None())))
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
        let Some(context_manager) = self.context_manager.as_ref() else {
            return self.send_failure(py, original, started);
        };
        let exception = original.value(py);
        let exception_type = exception.getattr("__class__")?;
        let traceback = exception.getattr("__traceback__")?;
        let context_manager = context_manager.bind(py);
        let exit = match context_manager
            .get_type()
            .getattr("__aexit__")
            .and_then(|method| {
                method.call1((context_manager, exception_type, exception, traceback))
            }) {
            Ok(exit) => exit,
            Err(error) => return self.send_failure(py, error, started),
        };
        self.pending = Some(RouterLifespanPending::ErrorExit { original, started });
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
            RouterLifespanPending::FailureSend { original },
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
            Err(error) if matches!(&pending, RouterLifespanPending::StartupSend) => {
                return self.exit_with_error(py, error, false);
            }
            Err(error) => return Err(error),
        };
        self.pending = Some(pending);
        Ok(MachineAction::Await(send.unbind()))
    }
}

fn traceback_text(py: Python<'_>, error: &PyErr) -> PyResult<String> {
    let exception = error.value(py);
    let formatted = py
        .import("traceback")?
        .getattr("format_exception")?
        .call1((
            exception.getattr("__class__")?,
            exception,
            exception.getattr("__traceback__")?,
        ))?;
    PyString::new(py, "")
        .call_method1("join", (formatted,))?
        .extract()
}

#[pyfunction]
fn compile_route_path(
    py: Python<'_>,
    path: &str,
    param_regex: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
) -> PyResult<(Py<PyAny>, String, Py<PyDict>)> {
    let (pattern, path_format, convertors, _) =
        compile_path_parts(py, path, param_regex, convertor_types, None)?;
    Ok((pattern.unbind(), path_format, convertors.unbind()))
}

#[pyfunction]
#[pyo3(signature = (kind, path, endpoint, methods, name, include_in_schema, middleware, max_body_size, routes, param_regex, convertor_types, builtin_convertors, route_table_type, request_response_factory, websocket_endpoint_factory, router_type))]
#[allow(clippy::too_many_arguments)]
fn initialize_route(
    py: Python<'_>,
    kind: &str,
    path: &str,
    endpoint: Option<Py<PyAny>>,
    methods: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    include_in_schema: bool,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    routes: Option<Py<PyAny>>,
    param_regex: Py<PyAny>,
    convertor_types: Py<PyAny>,
    builtin_convertors: Py<PyAny>,
    route_table_type: Py<PyAny>,
    request_response_factory: Py<PyAny>,
    websocket_endpoint_factory: Py<PyAny>,
    router_type: Py<PyAny>,
) -> PyResult<Py<PyTuple>> {
    let param_regex = param_regex.bind(py);
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
            param_regex,
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
            param_regex,
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
            param_regex,
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
            param_regex,
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
#[pyo3(signature = (router, routes, default, lifespan, middleware, max_body_size, runtime_type, http_route_type, websocket_route_type, mount_type, host_route_type, default_lifespan_factory, deprecation_warning_type))]
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
        http_route_type,
        websocket_route_type,
        mount_type,
        host_route_type,
    ))?;
    let middleware_stack = apply_middleware_inner(
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

#[allow(clippy::too_many_arguments)]
fn initialize_http_route(
    py: Python<'_>,
    path: &str,
    endpoint: Option<Py<PyAny>>,
    methods: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    include_in_schema: bool,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    param_regex: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    request_response_factory: &Bound<'_, PyAny>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if !path.starts_with('/') {
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
        max_body_size.as_ref().map(|item| item.bind(py)),
    )?;

    let normalized_methods =
        normalize_methods(py, effective_methods.as_ref().map(|item| item.bind(py)))?;
    let (regex, path_format, convertors, custom) = compile_path_parts(
        py,
        path,
        param_regex,
        convertor_types,
        Some(builtin_convertors),
    )?;
    let route_table = make_route_table(
        py,
        route_table_type,
        path,
        custom,
        normalized_methods.as_ref().map(|item| item.bind(py)),
    )?;

    Ok((
        PyString::new(py, path).into_any().unbind(),
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
        PyString::new(py, &path_format).into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom).to_owned().into_any().unbind(),
        route_table,
    ))
}

#[allow(clippy::too_many_arguments)]
fn initialize_websocket_route(
    py: Python<'_>,
    path: &str,
    endpoint: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    middleware: Option<Py<PyAny>>,
    param_regex: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    websocket_endpoint_factory: &Bound<'_, PyAny>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if !path.starts_with('/') {
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
        None,
    )?;
    let (regex, path_format, convertors, custom) = compile_path_parts(
        py,
        path,
        param_regex,
        convertor_types,
        Some(builtin_convertors),
    )?;
    let route_table = make_route_table(py, route_table_type, path, custom, None)?;

    Ok((
        PyString::new(py, path).into_any().unbind(),
        endpoint,
        route_name,
        py.None(),
        PyBool::new(py, true).to_owned().into_any().unbind(),
        py.None(),
        app,
        regex.unbind(),
        PyString::new(py, &path_format).into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom).to_owned().into_any().unbind(),
        route_table,
    ))
}

#[allow(clippy::too_many_arguments)]
fn initialize_host_route(
    py: Python<'_>,
    host: &str,
    app: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    param_regex: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    route_table_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if host.starts_with('/') {
        return Err(PyAssertionError::new_err("Host must not start with '/'"));
    }
    let app = app.unwrap_or_else(|| py.None());
    let (regex, host_format, convertors, custom) = compile_path_parts(
        py,
        host,
        param_regex,
        convertor_types,
        Some(builtin_convertors),
    )?;
    let route_table_path = format!("/{host_format}");
    let route_table = make_route_table(py, route_table_type, &route_table_path, custom, None)?;
    Ok((
        PyString::new(py, host).into_any().unbind(),
        app.clone_ref(py),
        name.unwrap_or_else(|| py.None()),
        py.None(),
        PyBool::new(py, true).to_owned().into_any().unbind(),
        py.None(),
        app,
        regex.unbind(),
        PyString::new(py, &host_format).into_any().unbind(),
        convertors.into_any().unbind(),
        PyBool::new(py, custom).to_owned().into_any().unbind(),
        route_table,
    ))
}

#[allow(clippy::too_many_arguments)]
fn initialize_mount(
    py: Python<'_>,
    path: &str,
    app: Option<Py<PyAny>>,
    routes: Option<Py<PyAny>>,
    name: Option<Py<PyAny>>,
    middleware: Option<Py<PyAny>>,
    max_body_size: Option<Py<PyAny>>,
    param_regex: &Bound<'_, PyAny>,
    convertor_types: &Bound<'_, PyDict>,
    builtin_convertors: &Bound<'_, PyDict>,
    route_table_type: &Bound<'_, PyAny>,
    router_type: &Bound<'_, PyAny>,
) -> PyResult<RouteInitValues> {
    if !path.is_empty() && !path.starts_with('/') {
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
    let path = path.trim_end_matches('/').to_owned();
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
        max_body_size.as_ref().map(|item| item.bind(py)),
    )?;
    let path_pattern = format!("{path}/{{path:path}}");
    let (regex, path_format, convertors, custom) = compile_path_parts(
        py,
        &path_pattern,
        param_regex,
        convertor_types,
        Some(builtin_convertors),
    )?;
    let route_table = make_route_table(py, route_table_type, &path_pattern, custom, None)?;

    Ok((
        PyString::new(py, &path).into_any().unbind(),
        py.None(),
        name.unwrap_or_else(|| py.None()),
        py.None(),
        true.into_pyobject(py)?.to_owned().into_any().unbind(),
        base_app,
        app,
        regex.unbind(),
        PyString::new(py, &path_format).into_any().unbind(),
        convertors.into_any().unbind(),
        custom.into_pyobject(py)?.to_owned().into_any().unbind(),
        route_table,
    ))
}

fn compile_path_parts<'py>(
    py: Python<'py>,
    path: &str,
    param_regex: &Bound<'py, PyAny>,
    convertor_types: &Bound<'py, PyDict>,
    builtin_convertors: Option<&Bound<'py, PyDict>>,
) -> PyResult<(Bound<'py, PyAny>, String, Bound<'py, PyDict>, bool)> {
    let is_host = !path.starts_with('/');
    let mut path_regex = String::from("^");
    let mut path_format = String::new();
    let mut duplicated_params = HashSet::new();
    let mut parameter_names = HashSet::new();
    let mut index = 0;
    let convertors = PyDict::new(py);
    let mut has_custom = false;
    let re = py.import("re")?;

    for capture in param_regex.call_method1("finditer", (path,))?.try_iter()? {
        let capture = capture?;
        let start = capture.call_method0("start")?.extract::<usize>()?;
        let end = capture.call_method0("end")?.extract::<usize>()?;
        let groups_value = capture.call_method1("groups", ("str",))?;
        let groups = groups_value.cast::<PyTuple>()?;
        let parameter = groups.get_item(0)?.extract::<String>()?;
        let converter_name = groups
            .get_item(1)?
            .extract::<String>()?
            .trim_start_matches(':')
            .to_owned();
        let convertor = convertor_types.get_item(&converter_name)?.ok_or_else(|| {
            PyAssertionError::new_err(format!("Unknown path convertor '{converter_name}'"))
        })?;

        let static_text = &path[index..start];
        let escaped = re
            .getattr("escape")?
            .call1((static_text,))?
            .extract::<String>()?;
        let converter_regex = convertor.getattr("regex")?.extract::<String>()?;
        path_regex.push_str(&escaped);
        path_regex.push_str("(?P<");
        path_regex.push_str(&parameter);
        path_regex.push('>');
        path_regex.push_str(&converter_regex);
        path_regex.push(')');
        path_format.push_str(static_text);
        path_format.push('{');
        path_format.push_str(&parameter);
        path_format.push('}');

        if !parameter_names.insert(parameter.clone()) {
            duplicated_params.insert(parameter.clone());
        }
        convertors.set_item(&parameter, &convertor)?;
        if let Some(builtins) = builtin_convertors {
            let builtin = builtins.get_item(&converter_name)?;
            has_custom |= builtin.is_none_or(|builtin| !convertor.is(&builtin));
        }
        index = end;
    }

    if !duplicated_params.is_empty() {
        let mut names = duplicated_params.into_iter().collect::<Vec<_>>();
        names.sort();
        let ending = if names.len() > 1 { "s" } else { "" };
        return Err(PyValueError::new_err(format!(
            "Duplicated param name{ending} {} at path {path}",
            names.join(", ")
        )));
    }

    let tail = &path[index..];
    if is_host {
        let hostname = tail.split(':').next().unwrap_or_default();
        path_regex.push_str(
            &re.getattr("escape")?
                .call1((hostname,))?
                .extract::<String>()?,
        );
    } else {
        path_regex.push_str(&re.getattr("escape")?.call1((tail,))?.extract::<String>()?);
    }
    path_regex.push('$');
    path_format.push_str(if is_host {
        tail.split(':').next().unwrap_or_default()
    } else {
        tail
    });
    let pattern = re.getattr("compile")?.call1((path_regex,))?;
    Ok((pattern, path_format, convertors, has_custom))
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
    Ok(table.unbind())
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
    max_body_size: Option<&Bound<'_, PyAny>>,
) -> PyResult<Py<PyAny>> {
    let mut app = app.clone().unbind();
    if let Some(middleware) = middleware {
        for item in py
            .import("builtins")?
            .getattr("reversed")?
            .call1((middleware,))?
            .try_iter()?
        {
            let item = item?;
            let item = item.cast::<PyTuple>()?;
            let middleware_type = item.get_item(0)?;
            let positional = item.get_item(1)?;
            let keyword_object = item.get_item(2)?;
            let keyword = keyword_object.cast::<PyDict>()?;
            let mut arguments = vec![app];
            for value in positional.try_iter()? {
                arguments.push(value?.unbind());
            }
            let arguments = PyTuple::new(py, arguments.iter().map(|value| value.bind(py)))?;
            app = middleware_type.call(&arguments, Some(keyword))?.unbind();
        }
    }
    apply_body_limit(py, app, max_body_size)
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
    apply_middleware_inner(py, app, middleware, max_body_size)
}

#[pyfunction]
fn route_path(scope: &Bound<'_, PyDict>) -> PyResult<String> {
    let path = required_string(scope, "path")?;
    let root_path = optional_string(scope, "root_path", "")?;
    Ok(route_path_from_parts(&path, &root_path).to_owned())
}

#[pyfunction]
fn route_matches(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    match_type: &Bound<'_, PyAny>,
    route_kind: &str,
    builtin_convertors: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let scope_type = optional_string(scope, "type", "")?;
    let protocol_matches = match route_kind {
        "http" => scope_type == "http",
        "websocket" => scope_type == "websocket",
        "mount" => matches!(scope_type.as_str(), "http" | "websocket"),
        "host" => matches!(scope_type.as_str(), "http" | "websocket"),
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

    let path = route_path_from_scope(scope)?;
    let custom = route
        .getattr("_uses_custom_convertors")?
        .extract::<bool>()?;
    let mut matched = if custom {
        python_regex_match(py, route, &path)?
    } else {
        native_regex_match(py, route, scope, &path, route_kind, builtin_convertors)?
    };
    let Some(matched_params) = matched.take() else {
        return match_result(py, match_type, "NONE", PyDict::new(py));
    };

    if route_kind == "mount" {
        return mount_match_result(py, route, scope, match_type, &path, matched_params);
    }

    let match_name = if route_kind == "websocket" {
        "FULL"
    } else {
        http_match_name(route, scope, custom)?
    };
    let path_params = merged_path_params(py, scope, matched_params.bind(py))?;
    let child_scope = PyDict::new(py);
    child_scope.set_item("endpoint", route.getattr("endpoint")?)?;
    child_scope.set_item("path_params", path_params.bind(py))?;
    match_result(py, match_type, match_name, child_scope)
}

pub(super) fn host_child_scope(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    host_route_child_scope(py, route, scope)?
        .map(|scope| scope.into_any())
        .ok_or_else(|| PyRuntimeError::new_err("selected Host route did not match its scope"))
}

fn host_route_child_scope(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
) -> PyResult<Option<Py<PyDict>>> {
    let host = host_header_value(py, scope)?;
    let hostname = host.split(':').next().unwrap_or_default();
    let custom = route
        .getattr("_uses_custom_convertors")?
        .extract::<bool>()?;
    let matched_params = if custom {
        python_regex_match(py, route, hostname)?
    } else {
        native_host_match(py, route, hostname)?
    };
    let Some(converted) = matched_params else {
        return Ok(None);
    };
    let path_params = merged_path_params(py, scope, converted.bind(py))?;
    let child_scope = PyDict::new(py);
    child_scope.set_item("path_params", path_params.bind(py))?;
    child_scope.set_item("endpoint", route.getattr("app")?)?;
    Ok(Some(child_scope.unbind()))
}

fn native_host_match(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    hostname: &str,
) -> PyResult<Option<Py<PyDict>>> {
    let table = route.getattr("_route_table")?;
    if table.is_none() {
        return Err(PyRuntimeError::new_err(
            "native Host route did not have a Rust route table",
        ));
    }
    let decision = table.call_method1(
        "match_route_with_root_path",
        (format!("/{hostname}"), "", "GET"),
    )?;
    let decision = decision.cast::<PyTuple>()?;
    if decision.get_item(0)?.extract::<String>()? == "not_found" {
        return Ok(None);
    }
    let captures = decision.get_item(3)?.extract::<Vec<(String, String)>>()?;
    let captured = PyDict::new(py);
    for (name, value) in captures {
        captured.set_item(name, value)?;
    }
    convert_capture_dict(py, route, &captured).map(Some)
}

fn host_header_value(py: Python<'_>, scope: &Bound<'_, PyDict>) -> PyResult<String> {
    let headers = scope
        .get_item("headers")?
        .ok_or_else(|| PyKeyError::new_err("headers"))?;
    let headers = py.import("builtins")?.getattr("list")?.call1((headers,))?;
    scope.set_item("headers", &headers)?;
    let host_key = PyBytes::new(py, b"host");
    for entry in headers.try_iter()? {
        let entry = py.import("builtins")?.getattr("tuple")?.call1((entry?,))?;
        let (name, value): (Py<PyAny>, Py<PyAny>) = entry.extract()?;
        if name.bind(py).eq(&host_key)? {
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

fn python_regex_match(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    path: &str,
) -> PyResult<Option<Py<PyDict>>> {
    let regex = route.getattr("path_regex")?;
    let match_object = regex.call_method1("match", (path,))?;
    if match_object.is_none() {
        return Ok(None);
    }
    let captured = match_object
        .call_method0("groupdict")?
        .cast_into::<PyDict>()?;
    convert_capture_dict(py, route, &captured).map(Some)
}

fn native_regex_match(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    path: &str,
    route_kind: &str,
    builtin_convertors: &Bound<'_, PyDict>,
) -> PyResult<Option<Py<PyDict>>> {
    let table = route.getattr("_route_table")?;
    if table.is_none() {
        return Err(PyRuntimeError::new_err(
            "native route did not have a Rust route table",
        ));
    }
    let root_path = optional_string(scope, "root_path", "")?;
    let method = if route_kind == "websocket" {
        "GET".to_owned()
    } else {
        optional_string(scope, "method", "GET")?
    };
    let decision = table.call_method1(
        "match_route_with_root_path",
        (required_string(scope, "path")?, root_path, method),
    )?;
    let decision = decision.cast::<PyTuple>()?;
    let decision_name = decision.get_item(0)?.extract::<String>()?;
    if decision_name == "not_found" {
        return Ok(None);
    }
    let rust_captured = decision.get_item(3)?.extract::<Vec<(String, String)>>()?;
    let regex_match = route
        .getattr("path_regex")?
        .call_method1("match", (path,))?;
    if regex_match.is_none() {
        return Err(PyRuntimeError::new_err(
            "Rust matched a route that the path converter regex did not match",
        ));
    }
    let captured_dict = regex_match
        .call_method0("groupdict")?
        .cast_into::<PyDict>()?;
    let captured_items = dict_string_items(&captured_dict)?;
    let rust_names = rust_captured
        .iter()
        .map(|(name, _)| name.as_str())
        .collect::<Vec<_>>();
    let python_names = captured_items
        .iter()
        .map(|(name, _)| name.as_str())
        .collect::<Vec<_>>();
    let convertors = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    let parameter_names = dict_keys_as_strings(&convertors)?;
    if python_names != parameter_names || rust_names != parameter_names {
        return Err(PyRuntimeError::new_err(format!(
            "Rust and Python route matchers captured different path parameters (Rust: {rust_names:?}, Python: {python_names:?})"
        )));
    }

    let converted = convert_capture_dict(py, route, &captured_dict)?;
    let rust_values = rust_captured
        .into_iter()
        .collect::<std::collections::HashMap<_, _>>();
    for (name, raw_value) in captured_items {
        let converter = convertors.get_item(&name)?.ok_or_else(|| {
            PyRuntimeError::new_err(format!("route converter missing parameter '{name}'"))
        })?;
        let builtin_int = builtin_convertors
            .get_item("int")?
            .is_some_and(|value| converter.is(&value));
        let expected = if builtin_int {
            converted
                .bind(py)
                .get_item(&name)?
                .ok_or_else(|| PyRuntimeError::new_err("converted path parameter disappeared"))?
                .str()?
                .to_str()?
                .to_owned()
        } else {
            raw_value
        };
        if rust_values.get(&name) != Some(&expected) {
            return Err(PyRuntimeError::new_err(format!(
                "Rust and Python route matchers captured different values for {name:?}"
            )));
        }
    }
    Ok(Some(converted))
}

fn convert_capture_dict<'py>(
    py: Python<'py>,
    route: &Bound<'_, PyAny>,
    captures: &Bound<'_, PyDict>,
) -> PyResult<Py<PyDict>> {
    let converted = PyDict::new(py);
    let convertors = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    for (name, value) in dict_string_items(captures)? {
        let convertor = convertors.get_item(&name)?.ok_or_else(|| {
            PyRuntimeError::new_err(format!("route converter missing parameter '{name}'"))
        })?;
        converted.set_item(name, convertor.call_method1("convert", (value,))?)?;
    }
    Ok(converted.unbind())
}

fn http_match_name(
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    custom: bool,
) -> PyResult<&'static str> {
    let methods = route.getattr("methods")?;
    if methods.is_none() || !methods.is_truthy()? {
        return Ok("FULL");
    }
    let method = required_string(scope, "method")?;
    if methods.contains(&method)? {
        Ok("FULL")
    } else if custom {
        Ok("PARTIAL")
    } else {
        let table = route.getattr("_route_table")?;
        let decision = table.call_method1(
            "match_route_with_root_path",
            (
                required_string(scope, "path")?,
                optional_string(scope, "root_path", "")?,
                &method,
            ),
        )?;
        let decision_name = decision.get_item(0)?.extract::<String>()?;
        Ok(if decision_name == "method_not_allowed" {
            "PARTIAL"
        } else {
            "FULL"
        })
    }
}

fn mount_match_result(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyDict>,
    match_type: &Bound<'_, PyAny>,
    route_path: &str,
    converted: Py<PyDict>,
) -> PyResult<Py<PyAny>> {
    let params = converted.bind(py);
    let remainder = params
        .get_item("path")?
        .ok_or_else(|| PyRuntimeError::new_err("Mount converter omitted its path parameter"))?
        .extract::<String>()?;
    params.del_item("path")?;
    let remaining_path = format!("/{remainder}");
    let remaining_chars = remaining_path.chars().count();
    let route_chars = route_path.chars().count();
    let matched_chars = route_chars.saturating_sub(remaining_chars);
    let matched_path = route_path
        .char_indices()
        .nth(matched_chars)
        .map_or(route_path, |(byte_index, _)| &route_path[..byte_index]);
    let path_params = merged_path_params(py, scope, params)?;
    let root_path = optional_string(scope, "root_path", "")?;
    let app_root_path = scope
        .get_item("app_root_path")?
        .unwrap_or_else(|| PyString::new(py, &root_path).into_any());
    let child_scope = PyDict::new(py);
    child_scope.set_item("path_params", path_params.bind(py))?;
    child_scope.set_item("app_root_path", app_root_path)?;
    child_scope.set_item("root_path", format!("{root_path}{matched_path}"))?;
    child_scope.set_item("endpoint", route.getattr("app")?)?;
    match_result(py, match_type, "FULL", child_scope)
}

fn merged_path_params(
    py: Python<'_>,
    scope: &Bound<'_, PyDict>,
    matched_params: &Bound<'_, PyDict>,
) -> PyResult<Py<PyDict>> {
    let path_params = PyDict::new(py);
    if let Some(existing) = scope.get_item("path_params")? {
        path_params.call_method1("update", (existing,))?;
    }
    path_params.call_method1("update", (matched_params,))?;
    Ok(path_params.unbind())
}

fn route_path_from_scope(scope: &Bound<'_, PyDict>) -> PyResult<String> {
    let path = required_string(scope, "path")?;
    let root_path = optional_string(scope, "root_path", "")?;
    Ok(route_path_from_parts(&path, &root_path).to_owned())
}

fn route_path_from_parts<'a>(path: &'a str, root_path: &str) -> &'a str {
    if root_path.is_empty() || !path.starts_with(root_path) {
        return path;
    }
    if path == root_path {
        return "";
    }
    let remaining = &path[root_path.len()..];
    if remaining.starts_with('/') {
        remaining
    } else {
        path
    }
}

fn required_string(scope: &Bound<'_, PyDict>, name: &'static str) -> PyResult<String> {
    scope
        .get_item(name)?
        .ok_or_else(|| PyKeyError::new_err(name))?
        .extract::<String>()
}

fn optional_string(scope: &Bound<'_, PyDict>, name: &str, default: &str) -> PyResult<String> {
    scope
        .get_item(name)?
        .map_or_else(|| Ok(default.to_owned()), |value| value.extract::<String>())
}

fn dict_string_items(dict: &Bound<'_, PyDict>) -> PyResult<Vec<(String, String)>> {
    dict.items()
        .try_iter()?
        .map(|item| {
            let item = item?.cast_into::<PyTuple>()?;
            Ok((
                item.get_item(0)?.extract::<String>()?,
                item.get_item(1)?.extract::<String>()?,
            ))
        })
        .collect()
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
            let method = required_string(scope, "method")?;
            if !methods.contains(method)? {
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
    scope: Py<PyDict>,
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
    into_python_awaitable(
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
            MachineResume::AsyncIterationComplete(_) => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
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
            let scope_dict = scope.cast::<PyDict>()?;
            let scope_type = required_string(scope_dict, "type")?;
            let callback = if scope_type == "http" {
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", 404)?;
                self.plain_text_response_type
                    .bind(py)
                    .call(("Not Found",), Some(&kwargs))?
                    .call1((scope, self.receive.bind(py), self.send.bind(py)))?
            } else if scope_type == "websocket" {
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
) -> PyResult<(String, Py<PyDict>)> {
    format_path_params(py, route, path_params, partial)
}

fn format_path_params(
    py: Python<'_>,
    route: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
    partial: bool,
) -> PyResult<(String, Py<PyDict>)> {
    let table = route.getattr("_route_table")?;
    let mut path = route.getattr("path_format")?.extract::<String>()?;
    let mut formatted = Vec::new();
    let mut consumed = HashSet::new();
    let convertors = route.getattr("param_convertors")?.cast_into::<PyDict>()?;
    for (name, value) in dict_items_as_py(path_params)? {
        let placeholder = format!("{{{name}}}");
        if !partial || path.contains(&placeholder) {
            let convertor = convertors
                .get_item(&name)?
                .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
            let formatted_value = convertor
                .call_method1("to_string", (value.bind(py),))?
                .extract::<String>()?;
            formatted.push((name.clone(), formatted_value.clone()));
            if path.contains(&placeholder) {
                path = path.replace(&placeholder, &formatted_value);
                consumed.insert(name);
            }
        }
    }

    if !table.is_none() {
        let built = if partial {
            table.call_method1("build_path_partial", (0, formatted))?
        } else {
            table.call_method1("build_path", (0, formatted))?
        };
        if partial {
            path = built.get_item(0)?.extract::<String>()?;
        } else {
            path = built.extract::<String>()?;
        }
    }

    let remaining = PyDict::new(py);
    for (name, value) in dict_items_as_py(path_params)? {
        if !consumed.contains(&name) {
            remaining.set_item(name, value.bind(py))?;
        }
    }
    Ok((path, remaining.unbind()))
}

fn format_host_path_params(
    py: Python<'_>,
    host: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
) -> PyResult<(String, Py<PyDict>)> {
    let mut formatted_host = host.getattr("host_format")?.extract::<String>()?;
    let convertors = host.getattr("param_convertors")?.cast_into::<PyDict>()?;
    let remaining = PyDict::new(py);
    for (name, value) in dict_items_as_py(path_params)? {
        let placeholder = format!("{{{name}}}");
        if formatted_host.contains(&placeholder) {
            let convertor = convertors
                .get_item(&name)?
                .ok_or_else(|| PyKeyError::new_err(name.clone()))?;
            let value = convertor
                .call_method1("to_string", (value.bind(py),))?
                .extract::<String>()?;
            formatted_host = formatted_host.replace(&placeholder, &value);
        } else {
            remaining.set_item(name, value.bind(py))?;
        }
    }
    Ok((formatted_host, remaining.unbind()))
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
    let (path, remaining) = format_path_params(py, route, path_params, false)?;
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
        let (path, remaining) = format_path_params(py, mount, &current_params, true)?;
        current_params = remaining.into_bound(py);
        if current_params.is_empty() {
            let kwargs = PyDict::new(py);
            kwargs.set_item("path", path)?;
            return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
        }
    } else if mount_name.is_none() || name_starts_with_mount(name, &mount_name)? {
        let nested_name = if mount_name.is_none() {
            name.clone()
        } else {
            let name_text = name.extract::<String>()?;
            let prefix = format!("{}:", mount_name.extract::<String>()?);
            PyString::new(py, name_text.strip_prefix(&prefix).unwrap_or(&name_text)).into_any()
        };
        let path_kwarg = current_params.get_item("path")?;
        current_params.set_item("path", "")?;
        let (path_prefix, remaining_params) = format_path_params(py, mount, &current_params, true)?;
        if let Some(path_kwarg) = path_kwarg {
            remaining_params.bind(py).set_item("path", path_kwarg)?;
        }
        let routes = mount.getattr("routes")?;
        for route in routes.try_iter()? {
            let route = route?;
            match route.call_method(
                "url_path_for",
                (nested_name.clone(),),
                Some(remaining_params.bind(py)),
            ) {
                Ok(url) => {
                    let url_text = py.import("builtins")?.getattr("str")?.call1((&url,))?;
                    let prefix = path_prefix.trim_end_matches('/');
                    let full_path = format!("{prefix}{url_text}");
                    let kwargs = PyDict::new(py);
                    kwargs.set_item("path", full_path)?;
                    kwargs.set_item("protocol", url.getattr("protocol")?)?;
                    return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
                }
                Err(error) if error.value(py).is_instance(no_match_type)? => {}
                Err(error) => return Err(error),
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
    let failure_params = path_params.copy()?.cast_into::<PyDict>()?;
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
        if remaining.bind(py).is_empty() {
            let kwargs = PyDict::new(py);
            kwargs.set_item("path", path_value)?;
            kwargs.set_item("host", host_value)?;
            return url_path_type.call((), Some(&kwargs)).map(Bound::unbind);
        }
    } else if host_name.is_none() || host_name_matches_prefix(name, &host_name)? {
        let nested_name = if host_name.is_none() {
            name.clone().unbind()
        } else {
            let host_name_text = host_name.extract::<String>()?;
            let name_text = name.extract::<String>()?;
            PyString::new(
                py,
                name_text
                    .strip_prefix(&format!("{host_name_text}:"))
                    .unwrap_or(&name_text),
            )
            .into_any()
            .unbind()
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
    }
    raise_no_match(no_match_type, name, &failure_params)
}

fn host_name_matches_prefix(
    name: &Bound<'_, PyAny>,
    host_name: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let name = name.extract::<String>()?;
    let host_name = host_name.extract::<String>()?;
    Ok(name.starts_with(&format!("{host_name}:")))
}

fn name_starts_with_mount(
    name: &Bound<'_, PyAny>,
    mount_name: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let name = name.extract::<String>()?;
    let mount_name = mount_name.extract::<String>()?;
    Ok(name.starts_with(&format!("{mount_name}:")))
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
    into_python_awaitable(
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
            pending: None,
        },
    )
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
    ExceptionHandler,
    Response,
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
    pending: Option<RequestResponsePending>,
}

impl AwaitableStateMachine for RequestResponseMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => self.resume_value(py, value),
            MachineResume::Error(error) => self.resume_error(py, error),
            MachineResume::AsyncIterationComplete(_) => {
                Err(pyo3::exceptions::PyStopAsyncIteration::new_err(()))
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
        self.request = Some(request);
        self.pending = Some(RequestResponsePending::Endpoint);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn resume_value(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(RequestResponsePending::Endpoint) => self.await_response(py, value),
            Some(RequestResponsePending::ExceptionHandler) if value.bind(py).is_none() => {
                Ok(MachineAction::Complete(py.None()))
            }
            Some(RequestResponsePending::ExceptionHandler) => self.await_response(py, value),
            Some(RequestResponsePending::Response) => Ok(MachineAction::Complete(py.None())),
            None => Err(PyRuntimeError::new_err(
                "request endpoint completed without a pending operation",
            )),
        }
    }

    fn await_response(&mut self, py: Python<'_>, response: Py<PyAny>) -> PyResult<MachineAction> {
        let callback = response.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = Some(RequestResponsePending::Response);
        Ok(MachineAction::Await(callback.unbind()))
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        if !matches!(self.pending.take(), Some(RequestResponsePending::Endpoint)) {
            return Err(error);
        }
        if !error
            .value(py)
            .is_instance(self.http_exception_type.bind(py))?
        {
            return Err(error);
        }
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let request = self
            .request
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("request endpoint lost its Request object"))?;
        let app = scope
            .get_item("app")?
            .unwrap_or_else(|| py.None().into_bound(py));
        let exception_response = py.import("builtins")?.getattr("getattr")?.call1((
            app,
            "_exception_response",
            py.None(),
        ))?;
        if exception_response.is_none() {
            scope.set_item("starlette._exception_request", request.bind(py))?;
            return Err(error);
        }
        let callback = exception_response.call1((request.bind(py), error.value(py)))?;
        self.pending = Some(RequestResponsePending::ExceptionHandler);
        Ok(MachineAction::Await(callback.unbind()))
    }
}
