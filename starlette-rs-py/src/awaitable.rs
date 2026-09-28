//! Scheduler-neutral delegation from a Rust continuation to Python awaitables.
//!
//! Python's active task drives [`PythonAwaitable`] through the iterator returned by
//! `__await__`. When a Rust state machine requests an awaitable, this driver delegates
//! to that object's own `__await__` iterator and returns every yielded object unchanged.
//! The active event loop therefore remains responsible for driving Futures and waking
//! the state machine through `send` or `throw`.

use pyo3::exceptions::{
    PyBaseException, PyGeneratorExit, PyRuntimeError, PyStopAsyncIteration, PyStopIteration,
    PyTypeError,
};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyIterator, PyTraceback, PyType};

/// Input delivered to a Rust continuation when it starts or an awaited callback finishes.
pub(crate) enum MachineResume {
    /// The Python awaitable has just begun execution.
    Start,
    /// An awaited Python object completed normally.
    Value(Py<PyAny>),
    /// An awaited async-iterator step raised `StopAsyncIteration`.
    ///
    /// This is separate from `StopIteration`: the latter completes the delegated
    /// object's `__await__` iterator and its `.value` is delivered as [`Self::Value`].
    /// The Rust state machine decides whether async-iteration completion is expected
    /// in its current state. The original exception is retained for protocols that
    /// distinguish completion caused by the same exception object.
    AsyncIterationComplete(PyErr),
    /// An awaited Python object failed or the outer task threw into the awaitable.
    Error(PyErr),
}

/// The next operation requested by a Rust continuation.
pub(crate) enum MachineAction {
    /// Delegate to a Python awaitable, such as a callback or iterator operation.
    Await(Py<PyAny>),
    /// Complete the outer Python awaitable with this result.
    Complete(Py<PyAny>),
}

/// A Rust-owned continuation whose asynchronous operations cross into Python.
///
/// Implementations hold their own protocol state and return the next Python
/// awaitable to execute. For [`MachineAction::Await`], the driver calls that
/// object's `__await__()` factory and delegates to the returned iterator. It
/// forwards the result, `StopAsyncIteration`, or other exception through
/// [`MachineResume`].
pub(crate) trait AwaitableStateMachine: 'static {
    /// Advance the state machine after startup or completion of a delegated awaitable.
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction>;
}

/// Wrap a Rust state machine in an awaitable driven by the caller's Python task.
///
/// The returned object implements the Python `__await__` iterator protocol. It
/// does not create an executor or event loop; Futures yielded by Python awaitables
/// are passed directly to whichever loop is driving the returned awaitable.
pub(crate) fn into_python_awaitable<M>(py: Python<'_>, machine: M) -> PyResult<Py<PyAny>>
where
    M: AwaitableStateMachine,
{
    into_python_awaitable_with_reuse_error(py, machine, "cannot reuse already awaited coroutine")
}

/// Wrap a state machine with the reuse error exposed by a specific Python
/// awaitable protocol, such as an async-generator `asend` operation.
pub(crate) fn into_python_awaitable_with_reuse_error<M>(
    py: Python<'_>,
    machine: M,
    reuse_error: &'static str,
) -> PyResult<Py<PyAny>>
where
    M: AwaitableStateMachine,
{
    Py::new(py, PythonAwaitable::new(machine, reuse_error)).map(|awaitable| awaitable.into_any())
}

#[pyclass(unsendable)]
struct PythonAwaitable {
    machine: Option<Box<dyn AwaitableStateMachine>>,
    active_iterator: Option<Py<PyAny>>,
    started: bool,
    finished: bool,
    reuse_error: &'static str,
}

impl PythonAwaitable {
    fn new<M>(machine: M, reuse_error: &'static str) -> Self
    where
        M: AwaitableStateMachine,
    {
        Self {
            machine: Some(Box::new(machine)),
            active_iterator: None,
            started: false,
            finished: false,
            reuse_error,
        }
    }

    fn drive(&mut self, py: Python<'_>, mut input: DriverInput) -> PyResult<Py<PyAny>> {
        loop {
            if self.finished {
                return Err(PyRuntimeError::new_err(self.reuse_error));
            }

            if self.active_iterator.is_some() {
                match self.resume_delegate(py, &input) {
                    Ok(yielded) => return Ok(yielded),
                    Err(error) if error.is_instance_of::<PyStopIteration>(py) => {
                        self.active_iterator = None;
                        input = DriverInput::Machine(MachineResume::Value(
                            error.value(py).getattr("value")?.unbind(),
                        ));
                    }
                    Err(error) if error.is_instance_of::<PyStopAsyncIteration>(py) => {
                        self.active_iterator = None;
                        input = DriverInput::Machine(MachineResume::AsyncIterationComplete(error));
                    }
                    Err(error) => {
                        self.active_iterator = None;
                        input = DriverInput::Machine(MachineResume::Error(error));
                    }
                }
                continue;
            }

            let machine_input = match input {
                DriverInput::Start => MachineResume::Start,
                DriverInput::Machine(resume) => resume,
                DriverInput::Send(value) => MachineResume::Value(value),
                DriverInput::Throw(error) => MachineResume::Error(error),
            };
            let action_result = match self.machine.as_mut() {
                Some(machine) => machine.resume(py, machine_input),
                None => {
                    return Err(PyRuntimeError::new_err(self.reuse_error));
                }
            };
            let action = match action_result {
                Ok(action) => action,
                Err(error) => {
                    self.finish();
                    return Err(error);
                }
            };

            match action {
                MachineAction::Await(awaitable) => match await_iterator(py, awaitable) {
                    Ok(iterator) => {
                        self.active_iterator = Some(iterator);
                        input = DriverInput::Send(py.None());
                    }
                    Err(error) => {
                        input = DriverInput::Machine(MachineResume::Error(error));
                    }
                },
                MachineAction::Complete(value) => {
                    self.finish();
                    return Err(PyStopIteration::new_err((value,)));
                }
            }
        }
    }

    fn resume_delegate(&self, py: Python<'_>, input: &DriverInput) -> PyResult<Py<PyAny>> {
        let iterator = self
            .active_iterator
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("awaitable delegation is not active"))?
            .bind(py);

        match input {
            DriverInput::Start => send_value(iterator, py.None().bind(py)),
            DriverInput::Send(value) => send_value(iterator, value.bind(py)),
            DriverInput::Throw(error) => throw_error(iterator, py, error.clone_ref(py)),
            DriverInput::Machine(_) => Err(PyRuntimeError::new_err(
                "state-machine input cannot resume an active Python awaitable",
            )),
        }
    }

    fn handle_send(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        if !self.started {
            if !value.bind(py).is_none() {
                return Err(PyTypeError::new_err(
                    "can't send non-None value to a just-started coroutine",
                ));
            }
            self.started = true;
            return self.drive(py, DriverInput::Start);
        }
        self.drive(py, DriverInput::Send(value))
    }

    fn handle_throw(
        &mut self,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        value: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let error = normalize_throw(py, exception_type, value, traceback)?;
        if !self.started {
            self.finish();
            return Err(error);
        }
        self.drive(py, DriverInput::Throw(error))
    }

    fn handle_close(&mut self, py: Python<'_>) -> PyResult<()> {
        if self.finished {
            return Ok(());
        }
        if !self.started {
            self.finish();
            return Ok(());
        }

        let exit = PyGeneratorExit::new_err(());
        match self.drive(py, DriverInput::Throw(exit)) {
            Ok(_) => {
                self.close_active_iterator(py);
                self.finish();
                Err(PyRuntimeError::new_err("coroutine ignored GeneratorExit"))
            }
            Err(error)
                if error.is_instance_of::<PyGeneratorExit>(py)
                    || error.is_instance_of::<PyStopIteration>(py) =>
            {
                self.finish();
                Ok(())
            }
            Err(error) => Err(error),
        }
    }

    fn close_active_iterator(&mut self, py: Python<'_>) {
        if let Some(iterator) = self.active_iterator.take() {
            let iterator = iterator.bind(py);
            if let Ok(close) = iterator.getattr("close") {
                if let Err(error) = close.call0() {
                    error.write_unraisable(py, Some(iterator));
                }
            }
        }
    }

    fn finish(&mut self) {
        self.finished = true;
        self.active_iterator = None;
        self.machine = None;
    }
}

enum DriverInput {
    Start,
    Send(Py<PyAny>),
    Throw(PyErr),
    Machine(MachineResume),
}

#[pymethods]
impl PythonAwaitable {
    fn __await__(self_: Py<Self>) -> Py<Self> {
        self_
    }

    fn __iter__(self_: Py<Self>) -> Py<Self> {
        self_
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.handle_send(py, py.None())
    }

    fn send(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        PythonAwaitable::handle_send(self, py, value)
    }

    #[pyo3(signature = (exception_type, value=None, traceback=None))]
    fn throw(
        &mut self,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        value: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        PythonAwaitable::handle_throw(self, py, exception_type, value, traceback)
    }

    fn close(&mut self, py: Python<'_>) -> PyResult<()> {
        PythonAwaitable::handle_close(self, py)
    }
}

fn await_iterator(py: Python<'_>, awaitable: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let awaitable = awaitable.bind(py);
    let is_awaitable = py
        .import("inspect")?
        .getattr("isawaitable")?
        .call1((awaitable,))?
        .extract::<bool>()?;
    if !is_awaitable {
        let type_name = py
            .import("builtins")?
            .getattr("type")?
            .call1((awaitable,))?
            .getattr("__name__")?
            .extract::<String>()?;
        return Err(PyTypeError::new_err(format!(
            "object {type_name} can't be used in 'await' expression"
        )));
    }
    let iterator = awaitable.call_method0("__await__")?;
    if !iterator.is_instance_of::<PyIterator>() {
        return Err(PyTypeError::new_err("__await__() returned a non-iterator"));
    }
    Ok(iterator.unbind())
}

fn send_value(iterator: &Bound<'_, PyAny>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if value.is_none() && !iterator.hasattr("send")? {
        return iterator.call_method0("__next__").map(Bound::unbind);
    }
    iterator.call_method1("send", (value,)).map(Bound::unbind)
}

fn throw_error(iterator: &Bound<'_, PyAny>, py: Python<'_>, error: PyErr) -> PyResult<Py<PyAny>> {
    if !iterator.hasattr("throw")? {
        return Err(error);
    }
    let exception = error.into_value(py);
    iterator
        .call_method1("throw", (exception,))
        .map(Bound::unbind)
}

fn normalize_throw(
    py: Python<'_>,
    exception_type: Py<PyAny>,
    value: Option<Py<PyAny>>,
    traceback: Option<Py<PyAny>>,
) -> PyResult<PyErr> {
    let exception_type = exception_type.bind(py);
    let exception_value = if exception_type.is_instance_of::<PyBaseException>() {
        if value
            .as_ref()
            .is_some_and(|value| !value.bind(py).is_none())
        {
            return Err(PyTypeError::new_err(
                "instance exception may not have a separate value",
            ));
        }
        exception_type.clone().unbind()
    } else {
        let exception_class = exception_type.cast::<PyType>()?;
        let constructed = match value {
            Some(value) if value.bind(py).is_instance_of::<PyBaseException>() => value,
            Some(value) if !value.bind(py).is_none() => {
                exception_class.call1((value.bind(py),))?.unbind()
            }
            _ => exception_class.call0()?.unbind(),
        };
        if !constructed.bind(py).is_instance_of::<PyBaseException>() {
            return Err(PyTypeError::new_err(
                "exceptions must derive from BaseException",
            ));
        }
        constructed
    };

    let error = PyErr::from_value(exception_value.into_bound(py));
    if let Some(traceback) = traceback.filter(|traceback| !traceback.bind(py).is_none()) {
        let traceback = traceback.bind(py).cast::<PyTraceback>()?.clone();
        error.set_traceback(py, Some(traceback));
    }
    Ok(error)
}
