//! Rust-owned continuations for Starlette background callbacks.
//!
//! Python remains responsible for representing user callables and running the
//! active event loop. This module performs only the Python calls required at
//! that boundary; callback selection, task sequencing, and continuation state
//! remain in Rust.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyRuntimeError, PyStopAsyncIteration, PyStopIteration, PyTypeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyMapping, PyModule, PyTuple};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
    into_sendable_python_awaitable_with_reuse_error, normalize_throw,
};

#[pyclass(name = "BackgroundTask")]
struct PyBackgroundTask {
    func: Py<PyAny>,
    args: Py<PyAny>,
    kwargs: Py<PyAny>,
    is_async: Py<PyAny>,
}

#[pymethods]
impl PyBackgroundTask {
    #[new]
    #[pyo3(signature = (func, *args, **kwargs))]
    fn new(
        py: Python<'_>,
        func: Py<PyAny>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Self> {
        let is_async = is_async_callable(py, func.bind(py))?;
        let kwargs = kwargs.map_or_else(
            || PyDict::new(py).into_any().unbind(),
            |kwargs| kwargs.clone().into_any().unbind(),
        );

        Ok(Self {
            func,
            args: args.clone().into_any().unbind(),
            kwargs,
            is_async: PyBool::new(py, is_async).to_owned().into_any().unbind(),
        })
    }

    #[getter]
    fn func(&self, py: Python<'_>) -> Py<PyAny> {
        self.func.clone_ref(py)
    }

    #[setter]
    fn set_func(&mut self, func: Py<PyAny>) {
        self.func = func;
    }

    #[getter]
    fn args(&self, py: Python<'_>) -> Py<PyAny> {
        self.args.clone_ref(py)
    }

    #[setter]
    fn set_args(&mut self, args: Py<PyAny>) {
        self.args = args;
    }

    #[getter]
    fn kwargs(&self, py: Python<'_>) -> Py<PyAny> {
        self.kwargs.clone_ref(py)
    }

    #[setter]
    fn set_kwargs(&mut self, kwargs: Py<PyAny>) {
        self.kwargs = kwargs;
    }

    #[getter]
    fn is_async(&self, py: Python<'_>) -> Py<PyAny> {
        self.is_async.clone_ref(py)
    }

    #[setter]
    fn set_is_async(&mut self, is_async: Py<PyAny>) {
        self.is_async = is_async;
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.func)?;
        visit.call(&self.args)?;
        visit.call(&self.kwargs)?;
        visit.call(&self.is_async)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.func = py.None();
        self.args = py.None();
        self.kwargs = py.None();
        self.is_async = py.None();
    }

    /// Return an awaitable that executes this task through the active Python loop.
    fn run(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(py, BackgroundTaskCall { task: slf })
    }
}

#[pyclass(name = "BackgroundTasks")]
struct PyBackgroundTasks {
    tasks: Py<PyAny>,
}

#[pymethods]
impl PyBackgroundTasks {
    #[new]
    #[pyo3(signature = (tasks=None))]
    fn new(py: Python<'_>, tasks: Option<Py<PyAny>>) -> PyResult<Self> {
        let tasks = match tasks {
            Some(tasks) if tasks.bind(py).is_truthy()? => py
                .import("builtins")?
                .getattr("list")?
                .call1((tasks.bind(py),))?
                .into_any()
                .unbind(),
            _ => PyList::empty(py).into_any().unbind(),
        };
        Ok(Self { tasks })
    }

    #[getter]
    fn tasks(&self, py: Python<'_>) -> Py<PyAny> {
        self.tasks.clone_ref(py)
    }

    #[setter]
    fn set_tasks(&mut self, tasks: Py<PyAny>) {
        self.tasks = tasks;
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.tasks)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.tasks = py.None();
    }

    /// Append a public Python task wrapper to the mutable task sequence.
    fn append_task(&self, py: Python<'_>, task: Py<PyAny>) -> PyResult<()> {
        self.tasks.bind(py).call_method1("append", (task,))?;
        Ok(())
    }

    /// Return an awaitable which runs tasks sequentially in registration order.
    fn run(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            BackgroundTasksCall {
                tasks: slf,
                iterator: None,
            },
        )
    }
}

/// Async equivalent of `starlette.concurrency.run_in_threadpool`.
///
/// The returned Python awaitable is deliberately deferred: `func`, `args`,
/// and `kwargs` are read by the Rust continuation when the caller first awaits
/// it, matching Python coroutine startup semantics.
#[pyfunction]
#[pyo3(signature = (func, *args, **kwargs))]
fn run_in_threadpool(
    py: Python<'_>,
    func: Py<PyAny>,
    args: &Bound<'_, PyTuple>,
    kwargs: Option<&Bound<'_, PyDict>>,
) -> PyResult<Py<PyAny>> {
    let kwargs = kwargs.map_or_else(
        || PyDict::new(py).into_any().unbind(),
        |kwargs| kwargs.clone().into_any().unbind(),
    );
    into_sendable_python_awaitable(
        py,
        ThreadpoolCall {
            func,
            args: args.clone().into_any().unbind(),
            kwargs,
        },
    )
}

/// Run concurrent Python callbacks until the first callback completes.
///
/// Rust owns the task-group continuation and cancellation decision. AnyIO
/// continues to own backend-specific task scheduling on the caller's loop.
#[pyfunction]
#[pyo3(signature = (*args))]
fn run_until_first_complete(py: Python<'_>, args: &Bound<'_, PyTuple>) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        RunUntilFirstComplete {
            args: args.clone().unbind(),
            task_group: None,
            pending: None,
        },
    )
}

/// Return a Rust-owned async iterator that advances a synchronous Python
/// iterator in AnyIO's worker pool.
#[pyfunction]
fn iterate_in_threadpool(py: Python<'_>, iterable: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let sentinel = py.import("builtins")?.getattr("object")?.call0()?.unbind();
    Py::new(
        py,
        PyThreadpoolAsyncIterator {
            iterable: SharedPythonValue::new(py, Some(iterable))?,
            iterator: SharedPythonValue::new(py, None)?,
            awaiting: SharedPythonValue::new(py, None)?,
            sentinel,
            finished: SharedFlag::new(false),
            running: SharedFlag::new(false),
            started: SharedFlag::new(false),
        },
    )
    .map(|iterator| iterator.into_any())
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyBackgroundTask>()?;
    module.add_class::<PyBackgroundTasks>()?;
    module.add_class::<PyThreadpoolAsyncIterator>()?;
    module.add_function(wrap_pyfunction!(run_in_threadpool, module)?)?;
    module.add_class::<PyRunUntilFirstCompleteTask>()?;
    module.add_function(wrap_pyfunction!(run_until_first_complete, module)?)?;
    module.add_function(wrap_pyfunction!(iterate_in_threadpool, module)?)?;
    Ok(())
}

#[pyclass(name = "_RunUntilFirstCompleteTask")]
struct PyRunUntilFirstCompleteTask {
    func: Py<PyAny>,
    cancel_scope: Py<PyAny>,
}

#[pymethods]
impl PyRunUntilFirstCompleteTask {
    fn __call__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let task = slf.borrow(py);
        let machine = RunUntilFirstCompleteTaskCall {
            func: task.func.clone_ref(py),
            cancel_scope: task.cancel_scope.clone_ref(py),
        };
        drop(task);
        into_sendable_python_awaitable(py, machine)
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.func)?;
        visit.call(&self.cancel_scope)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.func = py.None();
        self.cancel_scope = py.None();
    }
}

// Each owner holds an actual Python reference to a private storage list.
// Unlike a shared Rust Rc containing Py references, this is both transferable
// across Python threads and accurately visible to cyclic GC. No user code runs
// with a Rust state lock held; all iterator decisions remain in Rust.
struct SharedPythonValue {
    holder: Py<PyList>,
}

impl SharedPythonValue {
    fn new(py: Python<'_>, value: Option<Py<PyAny>>) -> PyResult<Self> {
        Ok(Self {
            holder: PyList::new(py, value)?.unbind(),
        })
    }

    fn clone_ref(&self, py: Python<'_>) -> Self {
        Self {
            holder: self.holder.clone_ref(py),
        }
    }

    fn get(&self, py: Python<'_>) -> PyResult<Option<Py<PyAny>>> {
        let holder = self.holder.bind(py);
        if holder.is_empty() {
            Ok(None)
        } else {
            holder.get_item(0).map(|value| Some(value.unbind()))
        }
    }

    fn replace(&self, py: Python<'_>, value: Option<Py<PyAny>>) -> PyResult<()> {
        let holder = self.holder.bind(py);
        let previous = self.get(py)?;
        match value {
            Some(value) if holder.is_empty() => holder.append(value)?,
            Some(value) => holder.set_item(0, value)?,
            None => {
                holder.call_method0("clear")?;
            }
        }
        // Release the old value after the completed state write, permitting
        // finalizer reentry without a Rust borrow or mutex guard.
        drop(previous);
        Ok(())
    }
}

#[derive(Clone)]
struct SharedFlag(Arc<AtomicBool>);

impl SharedFlag {
    fn new(value: bool) -> Self {
        Self(Arc::new(AtomicBool::new(value)))
    }
    fn get(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
    fn set(&self, value: bool) {
        self.0.store(value, Ordering::SeqCst);
    }
}

#[pyclass(name = "ThreadpoolAsyncIterator")]
struct PyThreadpoolAsyncIterator {
    iterable: SharedPythonValue,
    iterator: SharedPythonValue,
    awaiting: SharedPythonValue,
    sentinel: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
}

#[pymethods]
impl PyThreadpoolAsyncIterator {
    fn __aiter__(slf: Py<Self>) -> Py<Self> {
        slf
    }

    fn __anext__(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        threadpool_iterator_advance(slf, py, py.None())
    }

    fn asend(slf: Py<Self>, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        threadpool_iterator_advance(slf, py, value)
    }

    #[pyo3(signature = (exception_type, value=None, traceback=None))]
    fn athrow(
        slf: Py<Self>,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        value: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let owner = slf.clone_ref(py);
        let iterable = borrowed.iterable.clone_ref(py);
        let iterator = borrowed.iterator.clone_ref(py);
        let started = borrowed.started.clone();
        let running = borrowed.running.clone();
        let finished = borrowed.finished.clone();
        drop(borrowed);
        into_sendable_python_awaitable_with_reuse_error(
            py,
            ThreadpoolIteratorThrow {
                exception_type,
                value,
                traceback,
                owner,
                iterable,
                iterator,
                started,
                running,
                finished,
            },
            "cannot reuse already awaited athrow()/asend()",
        )
    }

    fn aclose(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let borrowed = slf.borrow(py);
        let owner = slf.clone_ref(py);
        let iterable = borrowed.iterable.clone_ref(py);
        let iterator = borrowed.iterator.clone_ref(py);
        let running = borrowed.running.clone();
        let finished = borrowed.finished.clone();
        drop(borrowed);
        into_sendable_python_awaitable_with_reuse_error(
            py,
            ThreadpoolIteratorClose {
                owner,
                iterable,
                iterator,
                running,
                finished,
            },
            "cannot reuse already awaited aclose()/athrow()",
        )
    }

    #[getter]
    fn ag_running(&self) -> bool {
        self.running.get()
    }

    #[getter]
    fn ag_await(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.awaiting.get(py)?.unwrap_or_else(|| py.None()))
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.sentinel)?;
        visit.call(&self.iterable.holder)?;
        visit.call(&self.iterator.holder)?;
        visit.call(&self.awaiting.holder)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        let _ = self.iterable.replace(py, None);
        self.sentinel = py.None();
        let _ = self.iterator.replace(py, None);
        let _ = self.awaiting.replace(py, None);
        self.finished.set(true);
    }
}

fn threadpool_iterator_advance(
    iterator: Py<PyThreadpoolAsyncIterator>,
    py: Python<'_>,
    value: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let borrowed = iterator.borrow(py);
    let machine = ThreadpoolIteratorAdvance {
        owner: iterator.clone_ref(py),
        iterable: borrowed.iterable.clone_ref(py),
        iterator: borrowed.iterator.clone_ref(py),
        awaiting: borrowed.awaiting.clone_ref(py),
        sentinel: borrowed.sentinel.clone_ref(py),
        finished: borrowed.finished.clone(),
        running: borrowed.running.clone(),
        started: borrowed.started.clone(),
        value,
        pending: false,
    };
    drop(borrowed);
    into_sendable_python_awaitable_with_reuse_error(
        py,
        machine,
        "cannot reuse already awaited __anext__()/asend()",
    )
}

struct ThreadpoolIteratorAdvance {
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: SharedPythonValue,
    iterator: SharedPythonValue,
    awaiting: SharedPythonValue,
    sentinel: Py<PyAny>,
    finished: SharedFlag,
    running: SharedFlag,
    started: SharedFlag,
    value: Py<PyAny>,
    pending: bool,
}

impl ThreadpoolIteratorAdvance {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.finished.get() {
            return Err(PyStopAsyncIteration::new_err(()));
        }
        if self.running.get() {
            return Err(PyRuntimeError::new_err(
                "anext(): asynchronous generator is already running",
            ));
        }
        if !self.started.get() && !self.value.bind(py).is_none() {
            return Err(PyTypeError::new_err(
                "can't send non-None value to a just-started async generator",
            ));
        }

        self.running.set(true);
        self.started.set(true);
        let existing_iterator = self.iterator.get(py)?;
        let iterator = match existing_iterator {
            Some(iterator) => iterator,
            None => {
                let iterable = match self.iterable.get(py)?.as_ref() {
                    Some(iterable) => iterable.clone_ref(py),
                    None => {
                        self.finished.set(true);
                        return Err(PyStopAsyncIteration::new_err(()));
                    }
                };
                let iterator = match py
                    .import("builtins")
                    .and_then(|builtins| builtins.getattr("iter"))
                    .and_then(|iter| iter.call1((iterable.bind(py),)))
                {
                    Ok(iterator) => iterator.unbind(),
                    Err(error) => {
                        self.finish(py)?;
                        return Err(async_generator_escape(py, error));
                    }
                };
                self.iterator.replace(py, Some(iterator.clone_ref(py)))?;
                iterator
            }
        };
        let run_sync = match py
            .import("anyio.to_thread")
            .and_then(|module| module.getattr("run_sync"))
        {
            Ok(run_sync) => run_sync,
            Err(error) => {
                self.finish(py)?;
                return Err(async_generator_escape(py, error));
            }
        };
        let next = match py
            .import("builtins")
            .and_then(|builtins| builtins.getattr("next"))
        {
            Ok(next) => next,
            Err(error) => {
                self.finish(py)?;
                return Err(async_generator_escape(py, error));
            }
        };
        let awaitable = match run_sync.call1((next, iterator, self.sentinel.bind(py))) {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.finish(py)?;
                return Err(async_generator_escape(py, error));
            }
        };
        self.pending = true;
        self.awaiting
            .replace(py, Some(awaitable.clone().unbind()))?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish(&mut self, py: Python<'_>) -> PyResult<()> {
        self.pending = false;
        self.finished.set(true);
        self.iterator.replace(py, None)?;
        self.iterable.replace(py, None)?;
        self.awaiting.replace(py, None)?;
        self.running.set(false);
        Ok(())
    }
}

impl AwaitableStateMachine for ThreadpoolIteratorAdvance {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.owner)?;
        visit.call(&self.iterable.holder)?;
        visit.call(&self.iterator.holder)?;
        visit.call(&self.awaiting.holder)?;
        visit.call(&self.sentinel)?;
        visit.call(&self.value)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let _owner = &self.owner;
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) if self.pending => {
                self.pending = false;
                self.awaiting.replace(py, None)?;
                if value.bind(py).is(self.sentinel.bind(py)) {
                    self.finish(py)?;
                    Err(PyStopAsyncIteration::new_err(()))
                } else {
                    self.running.set(false);
                    Ok(MachineAction::Complete(value))
                }
            }
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                if self.pending {
                    self.finish(py)?;
                }
                Err(async_generator_escape(py, error))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "threadpool iterator resumed without a pending operation",
            )),
        }
    }

    fn throw_before_start(&mut self, py: Python<'_>) {
        let _ = self.finish(py);
    }
}

struct ThreadpoolIteratorThrow {
    exception_type: Py<PyAny>,
    value: Option<Py<PyAny>>,
    traceback: Option<Py<PyAny>>,
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: SharedPythonValue,
    iterator: SharedPythonValue,
    started: SharedFlag,
    running: SharedFlag,
    finished: SharedFlag,
}

impl AwaitableStateMachine for ThreadpoolIteratorThrow {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.owner)?;
        visit.call(&self.iterable.holder)?;
        visit.call(&self.iterator.holder)?;
        visit.call(&self.exception_type)?;
        visit.call(&self.value)?;
        visit.call(&self.traceback)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let _owner = &self.owner;
        match input {
            MachineResume::Start => {
                if self.running.get() {
                    return Err(PyRuntimeError::new_err(
                        "athrow(): asynchronous generator is already running",
                    ));
                }
                self.running.set(true);
                let error = match normalize_throw(
                    py,
                    self.exception_type.clone_ref(py),
                    self.value.as_ref().map(|value| value.clone_ref(py)),
                    self.traceback
                        .as_ref()
                        .map(|traceback| traceback.clone_ref(py)),
                ) {
                    Ok(error) => error,
                    Err(error) => {
                        self.running.set(false);
                        return Err(error);
                    }
                };
                self.finished.set(true);
                self.iterable.replace(py, None)?;
                self.iterator.replace(py, None)?;
                self.running.set(false);
                if self.started.get()
                    && (error.is_instance_of::<PyStopIteration>(py)
                        || error.is_instance_of::<PyStopAsyncIteration>(py))
                {
                    Err(async_generator_escape(py, error))
                } else {
                    Err(error)
                }
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }

    fn throw_before_start(&mut self, py: Python<'_>) {
        self.finished.set(true);
        let _ = self.iterable.replace(py, None);
        let _ = self.iterator.replace(py, None);
        self.running.set(false);
    }
}

struct ThreadpoolIteratorClose {
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: SharedPythonValue,
    iterator: SharedPythonValue,
    running: SharedFlag,
    finished: SharedFlag,
}

impl AwaitableStateMachine for ThreadpoolIteratorClose {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.owner)?;
        visit.call(&self.iterable.holder)?;
        visit.call(&self.iterator.holder)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let _owner = &self.owner;
        match input {
            MachineResume::Start => {
                if self.running.get() {
                    return Err(PyRuntimeError::new_err(
                        "aclose(): asynchronous generator is already running",
                    ));
                }
                self.running.set(true);
                self.finished.set(true);
                self.iterable.replace(py, None)?;
                self.iterator.replace(py, None)?;
                self.running.set(false);
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }

    fn throw_before_start(&mut self, py: Python<'_>) {
        self.finished.set(true);
        let _ = self.iterable.replace(py, None);
        let _ = self.iterator.replace(py, None);
        self.running.set(false);
    }
}

fn async_generator_escape(py: Python<'_>, error: PyErr) -> PyErr {
    let exception_name = if error.is_instance_of::<PyStopIteration>(py) {
        "StopIteration"
    } else if error.is_instance_of::<PyStopAsyncIteration>(py) {
        "StopAsyncIteration"
    } else {
        return error;
    };
    async_generator_escape_error(py, exception_name, error)
}

fn async_generator_escape_error(py: Python<'_>, exception_name: &str, cause: PyErr) -> PyErr {
    let error = PyRuntimeError::new_err(format!("async generator raised {exception_name}"));
    error.set_context(py, Some(cause.clone_ref(py)));
    error.set_cause(py, Some(cause));
    error
}

struct BackgroundTaskCall {
    task: Py<PyBackgroundTask>,
}

impl AwaitableStateMachine for BackgroundTaskCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.task)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let task = self.task.borrow(py);
                let func = task.func.clone_ref(py);
                let args = task.args.clone_ref(py);
                let kwargs = task.kwargs.clone_ref(py);
                let is_async = task.is_async.bind(py).is_truthy()?;
                drop(task);

                let awaitable = if is_async {
                    call_with_args_and_kwargs(py, &func, &args, &kwargs)?
                } else {
                    threadpool_awaitable(py, &func, &args, &kwargs)?
                };
                Ok(MachineAction::Await(awaitable))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

struct BackgroundTasksCall {
    tasks: Py<PyBackgroundTasks>,
    iterator: Option<Py<PyAny>>,
}

impl BackgroundTasksCall {
    fn pull_next(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let iterator = self
            .iterator
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("background task iterator is not initialized"))?
            .bind(py);
        let next = py.import("builtins")?.getattr("next")?;
        let task = match next.call1((iterator,)) {
            Ok(task) => task,
            Err(error) if error.is_instance_of::<PyStopIteration>(py) => {
                return Ok(MachineAction::Complete(py.None()));
            }
            Err(error) => return Err(error),
        };
        let awaitable = task.call0()?;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

impl AwaitableStateMachine for BackgroundTasksCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.tasks)?;
        visit.call(&self.iterator)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let tasks = self.tasks.borrow(py).tasks.clone_ref(py);
                let iterator = py
                    .import("builtins")?
                    .getattr("iter")?
                    .call1((tasks.bind(py),))?;
                self.iterator = Some(iterator.unbind());
                self.pull_next(py)
            }
            MachineResume::Value(_) => self.pull_next(py),
            MachineResume::AsyncIterationComplete(error) => Err(error),
            MachineResume::Error(error) => Err(error),
        }
    }
}

struct ThreadpoolCall {
    func: Py<PyAny>,
    args: Py<PyAny>,
    kwargs: Py<PyAny>,
}

enum RunUntilFirstCompletePending {
    TaskGroupEnter,
    TaskGroupExit { body_error: Option<PyErr> },
}

const RUN_UNTIL_FIRST_COMPLETE_WARNING: &str =
    "run_until_first_complete is deprecated and will be removed in a future version.";

struct RunUntilFirstComplete {
    args: Py<PyTuple>,
    task_group: Option<Py<PyAny>>,
    pending: Option<RunUntilFirstCompletePending>,
}

impl RunUntilFirstComplete {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        warn_run_until_first_complete_deprecated(py)?;
        let task_group = py.import("anyio")?.getattr("create_task_group")?.call0()?;
        let awaitable = task_group.call_method0("__aenter__")?;
        self.task_group = Some(task_group.unbind());
        self.pending = Some(RunUntilFirstCompletePending::TaskGroupEnter);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn start_tasks(&self, py: Python<'_>) -> PyResult<()> {
        let task_group = self.task_group_ref(py)?;
        let cancel_scope = task_group.getattr("cancel_scope")?;
        let builtins = py.import("builtins")?;
        let tuple = builtins.getattr("tuple")?;
        let partial = py.import("functools")?.getattr("partial")?;

        for pair_value in self.args.bind(py).try_iter()? {
            let pair = tuple.call1((pair_value?,))?;
            let pair = pair.cast::<PyTuple>()?;
            if pair.len() != 2 {
                let message = if pair.len() < 2 {
                    format!(
                        "not enough values to unpack (expected 2, got {})",
                        pair.len()
                    )
                } else {
                    String::from("too many values to unpack (expected 2)")
                };
                return Err(PyValueError::new_err(message));
            }

            let func = pair.get_item(0)?;
            let kwargs = pair.get_item(1)?;
            let kwargs_mapping = kwargs.cast::<PyMapping>()?;
            let kwargs_dict = PyDict::new(py);
            kwargs_dict.update(kwargs_mapping)?;
            let func = partial.call((func,), Some(&kwargs_dict))?.unbind();
            let task = Py::new(
                py,
                PyRunUntilFirstCompleteTask {
                    func,
                    cancel_scope: cancel_scope.clone().unbind(),
                },
            )?;
            task_group.call_method1("start_soon", (task,))?;
        }

        Ok(())
    }

    fn leave_task_group(
        &mut self,
        py: Python<'_>,
        body_error: Option<PyErr>,
    ) -> PyResult<MachineAction> {
        let task_group = self.task_group_ref(py)?;
        let awaitable = match body_error.as_ref() {
            Some(error) => {
                let traceback = error
                    .traceback(py)
                    .map_or_else(|| py.None().into_bound(py), Bound::into_any);
                task_group.call_method1(
                    "__aexit__",
                    (error.get_type(py), error.value(py), traceback),
                )?
            }
            None => task_group.call_method1("__aexit__", (py.None(), py.None(), py.None()))?,
        };
        self.pending = Some(RunUntilFirstCompletePending::TaskGroupExit { body_error });
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn task_group_ref<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.task_group
            .as_ref()
            .map(|task_group| task_group.bind(py).clone())
            .ok_or_else(|| {
                PyRuntimeError::new_err("run_until_first_complete task group is missing")
            })
    }

    fn resume_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        match self.pending.take() {
            Some(RunUntilFirstCompletePending::TaskGroupEnter) => {
                self.task_group.take();
                Err(error)
            }
            Some(RunUntilFirstCompletePending::TaskGroupExit { body_error }) => {
                self.task_group.take();
                if let Some(body_error) = body_error {
                    error.set_context(py, Some(body_error));
                }
                Err(error)
            }
            None => Err(error),
        }
    }
}

impl AwaitableStateMachine for RunUntilFirstComplete {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(RunUntilFirstCompletePending::TaskGroupEnter) => match self.start_tasks(py) {
                    Ok(()) => self.leave_task_group(py, None),
                    Err(error) => self.leave_task_group(py, Some(error)),
                },
                Some(RunUntilFirstCompletePending::TaskGroupExit { body_error }) => {
                    self.task_group.take();
                    match body_error {
                        Some(error) => {
                            if value.bind(py).is_truthy()? {
                                Ok(MachineAction::Complete(py.None()))
                            } else {
                                Err(error)
                            }
                        }
                        None => Ok(MachineAction::Complete(py.None())),
                    }
                }
                None => Err(PyRuntimeError::new_err(
                    "run_until_first_complete resumed without a pending operation",
                )),
            },
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                self.resume_error(py, error)
            }
        }
    }
}

struct RunUntilFirstCompleteTaskCall {
    func: Py<PyAny>,
    cancel_scope: Py<PyAny>,
}

impl AwaitableStateMachine for RunUntilFirstCompleteTaskCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self
                .func
                .bind(py)
                .call0()
                .map(Bound::unbind)
                .map(MachineAction::Await),
            MachineResume::Value(_) => {
                self.cancel_scope.bind(py).call_method0("cancel")?;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }
}

fn warn_run_until_first_complete_deprecated(py: Python<'_>) -> PyResult<()> {
    let category = py
        .import("starlette.exceptions")?
        .getattr("StarletteDeprecationWarning")?;
    // Keep the pinned default stacklevel of 1 at the facade's await call site.
    py.import("warnings")?
        .getattr("warn")?
        .call1((RUN_UNTIL_FIRST_COMPLETE_WARNING, category))?;
    Ok(())
}

impl AwaitableStateMachine for ThreadpoolCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => {
                let awaitable = threadpool_awaitable(py, &self.func, &self.args, &self.kwargs)?;
                Ok(MachineAction::Await(awaitable))
            }
            MachineResume::Value(value) => Ok(MachineAction::Complete(value)),
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Error(error) => Err(error),
        }
    }
}

fn threadpool_awaitable(
    py: Python<'_>,
    func: &Py<PyAny>,
    args: &Py<PyAny>,
    kwargs: &Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let kwargs = kwargs.bind(py).cast::<PyDict>()?;
    let call = if kwargs.is_empty() {
        func.clone_ref(py)
    } else {
        py.import("functools")?
            .getattr("partial")?
            .call((func.bind(py),), Some(kwargs))?
            .unbind()
    };

    let args = positional_args(py, &call, args)?;
    py.import("anyio.to_thread")?
        .getattr("run_sync")?
        .call1(args)
        .map(Bound::unbind)
}

fn call_with_args_and_kwargs(
    py: Python<'_>,
    func: &Py<PyAny>,
    args: &Py<PyAny>,
    kwargs: &Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let args = py
        .import("builtins")?
        .getattr("tuple")?
        .call1((args.bind(py),))?;
    let args = args.cast_into::<PyTuple>()?;
    let kwargs = py
        .import("builtins")?
        .getattr("dict")?
        .call1((kwargs.bind(py),))?
        .cast_into::<PyDict>()?;
    func.bind(py).call(&args, Some(&kwargs)).map(Bound::unbind)
}

fn positional_args<'py>(
    py: Python<'py>,
    leading: &Py<PyAny>,
    args: &Py<PyAny>,
) -> PyResult<Bound<'py, PyTuple>> {
    let args = py
        .import("builtins")?
        .getattr("tuple")?
        .call1((args.bind(py),))?
        .cast_into::<PyTuple>()?;
    let mut items = Vec::with_capacity(args.len() + 1);
    items.push(leading.clone_ref(py));
    for item in args.iter() {
        items.push(item.unbind());
    }
    PyTuple::new(py, items)
}

pub(crate) fn is_async_callable(py: Python<'_>, func: &Bound<'_, PyAny>) -> PyResult<bool> {
    let partial_type = py.import("functools")?.getattr("partial")?;
    let mut callable = func.clone();
    while callable.is_instance(&partial_type)? {
        callable = callable.getattr("func")?;
    }

    let version = py.import("sys")?.getattr("version_info")?;
    let major = version.get_item(0)?.extract::<u8>()?;
    let minor = version.get_item(1)?.extract::<u8>()?;
    let inspector = if major > 3 || (major == 3 && minor >= 13) {
        py.import("inspect")?
    } else {
        py.import("asyncio")?
    };
    let iscoroutinefunction = inspector.getattr("iscoroutinefunction")?;
    if iscoroutinefunction.call1((&callable,))?.extract::<bool>()? {
        return Ok(true);
    }

    let callable_predicate = py.import("builtins")?.getattr("callable")?;
    if !callable_predicate.call1((&callable,))?.extract::<bool>()? {
        return Ok(false);
    }
    let call_method = callable.getattr("__call__")?;
    iscoroutinefunction.call1((call_method,))?.extract::<bool>()
}
