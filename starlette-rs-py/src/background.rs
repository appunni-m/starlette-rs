//! Rust-owned continuations for Starlette background callbacks.
//!
//! Python remains responsible for representing user callables and running the
//! active event loop. This module performs only the Python calls required at
//! that boundary; callback selection, task sequencing, and continuation state
//! remain in Rust.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyRuntimeError, PyStopAsyncIteration, PyStopIteration, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyModule, PyTuple};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
    into_python_awaitable_with_reuse_error, normalize_throw,
};

#[pyclass(name = "BackgroundTask", unsendable)]
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
        into_python_awaitable(py, BackgroundTaskCall { task: slf })
    }
}

#[pyclass(name = "BackgroundTasks", unsendable)]
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
        into_python_awaitable(
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
    into_python_awaitable(
        py,
        ThreadpoolCall {
            func,
            args: args.clone().into_any().unbind(),
            kwargs,
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
            iterable: Rc::new(RefCell::new(Some(iterable))),
            iterator: Rc::new(RefCell::new(None)),
            awaiting: Rc::new(RefCell::new(None)),
            sentinel,
            finished: Rc::new(Cell::new(false)),
            running: Rc::new(Cell::new(false)),
            started: Rc::new(Cell::new(false)),
        },
    )
    .map(|iterator| iterator.into_any())
}

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyBackgroundTask>()?;
    module.add_class::<PyBackgroundTasks>()?;
    module.add_class::<PyThreadpoolAsyncIterator>()?;
    module.add_function(wrap_pyfunction!(run_in_threadpool, module)?)?;
    module.add_function(wrap_pyfunction!(iterate_in_threadpool, module)?)?;
    Ok(())
}

#[pyclass(name = "ThreadpoolAsyncIterator", unsendable)]
struct PyThreadpoolAsyncIterator {
    iterable: Rc<RefCell<Option<Py<PyAny>>>>,
    iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    awaiting: Rc<RefCell<Option<Py<PyAny>>>>,
    sentinel: Py<PyAny>,
    finished: Rc<Cell<bool>>,
    running: Rc<Cell<bool>>,
    started: Rc<Cell<bool>>,
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
        let iterable = borrowed.iterable.clone();
        let iterator = borrowed.iterator.clone();
        let started = borrowed.started.clone();
        let running = borrowed.running.clone();
        let finished = borrowed.finished.clone();
        drop(borrowed);
        into_python_awaitable_with_reuse_error(
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
        let iterable = borrowed.iterable.clone();
        let iterator = borrowed.iterator.clone();
        let running = borrowed.running.clone();
        let finished = borrowed.finished.clone();
        drop(borrowed);
        into_python_awaitable_with_reuse_error(
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
    fn ag_await(&self, py: Python<'_>) -> Py<PyAny> {
        self.awaiting
            .borrow()
            .as_ref()
            .map_or_else(|| py.None(), |awaitable| awaitable.clone_ref(py))
    }

    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.sentinel)?;
        if let Some(iterable) = self.iterable.borrow().as_ref() {
            visit.call(iterable)?;
        }
        if let Some(iterator) = self.iterator.borrow().as_ref() {
            visit.call(iterator)?;
        }
        if let Some(awaitable) = self.awaiting.borrow().as_ref() {
            visit.call(awaitable)?;
        }
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        *self.iterable.borrow_mut() = None;
        self.sentinel = py.None();
        *self.iterator.borrow_mut() = None;
        *self.awaiting.borrow_mut() = None;
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
        iterable: borrowed.iterable.clone(),
        iterator: borrowed.iterator.clone(),
        awaiting: borrowed.awaiting.clone(),
        sentinel: borrowed.sentinel.clone_ref(py),
        finished: borrowed.finished.clone(),
        running: borrowed.running.clone(),
        started: borrowed.started.clone(),
        value,
        pending: false,
    };
    drop(borrowed);
    into_python_awaitable_with_reuse_error(
        py,
        machine,
        "cannot reuse already awaited __anext__()/asend()",
    )
}

struct ThreadpoolIteratorAdvance {
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: Rc<RefCell<Option<Py<PyAny>>>>,
    iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    awaiting: Rc<RefCell<Option<Py<PyAny>>>>,
    sentinel: Py<PyAny>,
    finished: Rc<Cell<bool>>,
    running: Rc<Cell<bool>>,
    started: Rc<Cell<bool>>,
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
        let existing_iterator = self
            .iterator
            .borrow()
            .as_ref()
            .map(|iterator| iterator.clone_ref(py));
        let iterator = match existing_iterator {
            Some(iterator) => iterator,
            None => {
                let iterable = match self.iterable.borrow().as_ref() {
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
                        self.finish();
                        return Err(async_generator_escape(py, error));
                    }
                };
                *self.iterator.borrow_mut() = Some(iterator.clone_ref(py));
                iterator
            }
        };
        let run_sync = match py
            .import("anyio.to_thread")
            .and_then(|module| module.getattr("run_sync"))
        {
            Ok(run_sync) => run_sync,
            Err(error) => {
                self.finish();
                return Err(async_generator_escape(py, error));
            }
        };
        let next = match py
            .import("builtins")
            .and_then(|builtins| builtins.getattr("next"))
        {
            Ok(next) => next,
            Err(error) => {
                self.finish();
                return Err(async_generator_escape(py, error));
            }
        };
        let awaitable = match run_sync.call1((next, iterator, self.sentinel.bind(py))) {
            Ok(awaitable) => awaitable,
            Err(error) => {
                self.finish();
                return Err(async_generator_escape(py, error));
            }
        };
        self.pending = true;
        *self.awaiting.borrow_mut() = Some(awaitable.clone().unbind());
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn finish(&mut self) {
        self.pending = false;
        self.finished.set(true);
        self.iterator.borrow_mut().take();
        self.iterable.borrow_mut().take();
        self.awaiting.borrow_mut().take();
        self.running.set(false);
    }
}

impl AwaitableStateMachine for ThreadpoolIteratorAdvance {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let _owner = &self.owner;
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(value) if self.pending => {
                self.pending = false;
                self.awaiting.borrow_mut().take();
                if value.bind(py).is(self.sentinel.bind(py)) {
                    self.finish();
                    Err(PyStopAsyncIteration::new_err(()))
                } else {
                    self.running.set(false);
                    Ok(MachineAction::Complete(value))
                }
            }
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                if self.pending {
                    self.finish();
                }
                Err(async_generator_escape(py, error))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "threadpool iterator resumed without a pending operation",
            )),
        }
    }

    fn throw_before_start(&mut self, _py: Python<'_>) {
        self.finish();
    }
}

struct ThreadpoolIteratorThrow {
    exception_type: Py<PyAny>,
    value: Option<Py<PyAny>>,
    traceback: Option<Py<PyAny>>,
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: Rc<RefCell<Option<Py<PyAny>>>>,
    iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    started: Rc<Cell<bool>>,
    running: Rc<Cell<bool>>,
    finished: Rc<Cell<bool>>,
}

impl AwaitableStateMachine for ThreadpoolIteratorThrow {
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
                self.iterable.borrow_mut().take();
                self.iterator.borrow_mut().take();
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

    fn throw_before_start(&mut self, _py: Python<'_>) {
        self.finished.set(true);
        self.iterable.borrow_mut().take();
        self.iterator.borrow_mut().take();
        self.running.set(false);
    }
}

struct ThreadpoolIteratorClose {
    owner: Py<PyThreadpoolAsyncIterator>,
    iterable: Rc<RefCell<Option<Py<PyAny>>>>,
    iterator: Rc<RefCell<Option<Py<PyAny>>>>,
    running: Rc<Cell<bool>>,
    finished: Rc<Cell<bool>>,
}

impl AwaitableStateMachine for ThreadpoolIteratorClose {
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
                self.iterable.borrow_mut().take();
                self.iterator.borrow_mut().take();
                self.running.set(false);
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Value(_) => Ok(MachineAction::Complete(py.None())),
            MachineResume::AsyncIterationComplete(error) | MachineResume::Error(error) => {
                Err(error)
            }
        }
    }

    fn throw_before_start(&mut self, _py: Python<'_>) {
        self.finished.set(true);
        self.iterable.borrow_mut().take();
        self.iterator.borrow_mut().take();
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
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
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
            MachineResume::AsyncIterationComplete(_) => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Error(error) => Err(error),
        }
    }
}

struct ThreadpoolCall {
    func: Py<PyAny>,
    args: Py<PyAny>,
    kwargs: Py<PyAny>,
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
