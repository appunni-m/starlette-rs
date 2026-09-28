//! Rust-owned continuations for Starlette background callbacks.
//!
//! Python remains responsible for representing user callables and running the
//! active event loop. This module performs only the Python calls required at
//! that boundary; callback selection, task sequencing, and continuation state
//! remain in Rust.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyRuntimeError, PyStopAsyncIteration, PyStopIteration};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyList, PyModule, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
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

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyBackgroundTask>()?;
    module.add_class::<PyBackgroundTasks>()?;
    module.add_function(wrap_pyfunction!(run_in_threadpool, module)?)?;
    Ok(())
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
