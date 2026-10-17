//! Scheduler-neutral delegation from a Rust continuation to Python awaitables.
//!
//! Python's active task drives [`SendablePythonAwaitable`] through the iterator returned by
//! `__await__`. When a Rust state machine requests an awaitable, this driver delegates
//! to that object's own `__await__` iterator and returns every yielded object unchanged.
//! The active event loop therefore remains responsible for driving Futures and waking
//! the state machine through `send` or `throw`.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAttributeError, PyBaseException, PyGeneratorExit, PyRuntimeError, PyRuntimeWarning,
    PyStopAsyncIteration, PyStopIteration, PyTypeError,
};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyIterator, PyTraceback, PyTuple, PyType};

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
    /// Delegate to the awaitable returned by an async iterator's `__anext__`.
    ///
    /// Python's `async for` bytecode validates this result before awaiting it,
    /// and wraps invalid awaitable results in its async-iteration TypeError.
    AwaitAsyncIteratorNext(Py<PyAny>),
    /// Complete the outer Python awaitable with this result.
    Complete(Py<PyAny>),
}

/// A Rust-owned continuation whose asynchronous operations cross into Python.
///
/// Implementations hold their own protocol state and return the next Python
/// awaitable to execute. For [`MachineAction::Await`], the driver calls that
/// object's `__await__()` factory and delegates to the returned iterator. For
/// [`MachineAction::AwaitAsyncIteratorNext`], it also wraps invalid awaitable
/// results using the error raised by Python's `async for` machinery. It forwards
/// the result, `StopAsyncIteration`, or other exception through [`MachineResume`].
pub(crate) trait AwaitableStateMachine: 'static {
    /// Advance the state machine after startup or completion of a delegated awaitable.
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction>;

    /// Notify a state machine when a valid exception is thrown into its unstarted awaitable.
    ///
    /// Most Rust awaitables have no externally visible state before they start. Async
    /// generator operation awaitables can close their owning generator in this case.
    fn throw_before_start(&mut self, _py: Python<'_>) {}

    /// Visit every directly owned Python reference once without acquiring the GIL.
    /// Shared Python references are exposed through GC-visible owned nodes.
    fn traverse(&self, _visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        Ok(())
    }

    /// Whether this converted continuation implements coroutine finalization.
    fn finalize_on_drop(&self) -> bool {
        false
    }

    /// Python coroutine warning required by a public facade that returns a native object.
    fn unawaited_warning(&self) -> Option<&'static std::ffi::CStr> {
        None
    }
}

/// Wrap a thread-safe state machine whose Python traceback may outlive the
/// event-loop thread that drives it.
pub(crate) fn into_sendable_python_awaitable<M>(py: Python<'_>, machine: M) -> PyResult<Py<PyAny>>
where
    M: AwaitableStateMachine + Send + Sync,
{
    Py::new(
        py,
        SendablePythonAwaitable {
            driver: AwaitableDriver::new(
                Box::new(machine),
                "cannot reuse already awaited coroutine",
            ),
        },
    )
    .map(|awaitable| awaitable.into_any())
}

/// Thread-safe variant for Python async-generator operation reuse errors.
pub(crate) fn into_sendable_python_awaitable_with_reuse_error<M>(
    py: Python<'_>,
    machine: M,
    reuse_error: &'static str,
) -> PyResult<Py<PyAny>>
where
    M: AwaitableStateMachine + Send + Sync,
{
    Py::new(
        py,
        SendablePythonAwaitable {
            driver: AwaitableDriver::new(Box::new(machine), reuse_error),
        },
    )
    .map(|awaitable| awaitable.into_any())
}

#[pyclass]
struct SendablePythonAwaitable {
    driver: AwaitableDriver<dyn AwaitableStateMachine + Send + Sync>,
}

struct AwaitableDriver<M: AwaitableStateMachine + ?Sized> {
    machine: Option<Box<M>>,
    active_iterator: Option<Py<PyAny>>,
    started: bool,
    finished: bool,
    reuse_error: &'static str,
}

impl<M: AwaitableStateMachine + ?Sized> AwaitableDriver<M> {
    fn new(machine: Box<M>, reuse_error: &'static str) -> Self {
        Self {
            machine: Some(machine),
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
                MachineAction::AwaitAsyncIteratorNext(awaitable) => {
                    match await_iterator(py, awaitable.clone_ref(py)) {
                        Ok(iterator) => {
                            self.active_iterator = Some(iterator);
                            input = DriverInput::Send(py.None());
                        }
                        Err(cause) => {
                            input = DriverInput::Machine(MachineResume::Error(
                                async_for_invalid_anext(py, awaitable.bind(py), cause)?,
                            ));
                        }
                    }
                }
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
            if let Some(machine) = self.machine.as_mut() {
                machine.throw_before_start(py);
            }
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

        // Python coroutine.close() first closes its delegated iterator, then
        // injects GeneratorExit into the outer continuation. Throwing through
        // an already finalized child incorrectly produces a reuse error when
        // Python GC has finalized that child before the parent.
        let exit = match self.close_delegate(py) {
            Ok(()) => PyGeneratorExit::new_err(()),
            Err(error) => error,
        };
        match self.drive(py, DriverInput::Machine(MachineResume::Error(exit))) {
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

    fn close_delegate(&mut self, py: Python<'_>) -> PyResult<()> {
        let Some(iterator) = self.active_iterator.take() else {
            return Ok(());
        };
        let close = match iterator.bind(py).getattr("close") {
            Ok(close) => close,
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => return Ok(()),
            Err(error) => return Err(error),
        };
        close.call0().map(|_| ())
    }

    fn finalize(&mut self, py: Python<'_>) {
        if self.finished {
            return;
        }
        // Native form facade objects replace source coroutines, so Rust must
        // preserve their unawaited warning and suspended-callback finalization.
        let previous = PyErr::take(py);
        if !self.started {
            if let Some(message) = self
                .machine
                .as_ref()
                .and_then(|machine| machine.unawaited_warning())
            {
                if let Err(error) = PyErr::warn(py, &py.get_type::<PyRuntimeWarning>(), message, 1)
                {
                    error.write_unraisable(py, None);
                }
            }
        } else if self
            .machine
            .as_ref()
            .is_some_and(|machine| machine.finalize_on_drop())
        {
            if let Err(error) = self.handle_close(py) {
                error.write_unraisable(py, None);
            }
        }
        self.finish();
        if let Some(previous) = previous {
            previous.restore(py);
        }
    }

    fn finish(&mut self) {
        self.finished = true;
        self.active_iterator = None;
        self.machine = None;
    }
}

impl<M: AwaitableStateMachine + ?Sized> Drop for AwaitableDriver<M> {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        let _ = Python::try_attach(|py| self.finalize(py));
    }
}

enum DriverInput {
    Start,
    Send(Py<PyAny>),
    Throw(PyErr),
    Machine(MachineResume),
}

#[pymethods]
impl SendablePythonAwaitable {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.driver.active_iterator)?;
        if let Some(machine) = &self.driver.machine {
            machine.traverse(&visit)?;
        }
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.driver.finalize(py);
    }

    fn __await__(self_: Py<Self>) -> Py<Self> {
        self_
    }

    fn __iter__(self_: Py<Self>) -> Py<Self> {
        self_
    }

    fn __next__(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.driver.handle_send(py, py.None())
    }

    fn send(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
        self.driver.handle_send(py, value)
    }

    #[pyo3(signature = (exception_type, value=None, traceback=None))]
    fn throw(
        &mut self,
        py: Python<'_>,
        exception_type: Py<PyAny>,
        value: Option<Py<PyAny>>,
        traceback: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.driver
            .handle_throw(py, exception_type, value, traceback)
    }

    fn close(&mut self, py: Python<'_>) -> PyResult<()> {
        self.driver.handle_close(py)
    }
}

fn await_iterator(py: Python<'_>, awaitable: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let awaitable = awaitable.bind(py);
    if is_exact_coroutine(awaitable) {
        // Exact coroutine objects use the built-in await protocol and cannot
        // override this special method. Keep custom awaitables on the generic
        // path below so their Python protocol and error behavior stay intact.
        let iterator = awaitable.call_method0("__await__")?;
        if !iterator.is_instance_of::<PyIterator>() {
            return Err(PyTypeError::new_err("__await__() returned a non-iterator"));
        }
        return Ok(iterator.unbind());
    }

    let inspect = py.import("inspect")?;
    let is_awaitable = inspect
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

    // CPython's await protocol also accepts generator-based coroutines made
    // with `types.coroutine`. They are awaitable through the
    // CO_ITERABLE_COROUTINE code flag even though generator objects do not
    // expose a type-level `__await__` method. Starlette awaits ASGI callables
    // directly, so preserve this public Python awaitable shape at the Rust
    // boundary and delegate to the generator itself.
    let is_generator = inspect
        .getattr("isgenerator")?
        .call1((awaitable,))?
        .extract::<bool>()?;
    if is_generator {
        let code_flags = awaitable
            .getattr("gi_code")?
            .getattr("co_flags")?
            .extract::<u32>()?;
        let iterable_coroutine_flag = inspect.getattr("CO_ITERABLE_COROUTINE")?.extract::<u32>()?;
        if code_flags & iterable_coroutine_flag != 0 {
            return Ok(awaitable.clone().unbind());
        }
    }

    let iterator = call_await_special_method(py, awaitable)?;
    if !iterator.is_instance_of::<PyIterator>() {
        return Err(PyTypeError::new_err("__await__() returned a non-iterator"));
    }
    Ok(iterator.unbind())
}

fn is_exact_coroutine(awaitable: &Bound<'_, PyAny>) -> bool {
    // SAFETY: `Bound` guarantees a live Python object, and callers hold the
    // GIL. PyCoro_CheckExact only inspects that object's type.
    // LINT EXCEPTION: PyO3 exposes this exact-type predicate only through unsafe FFI; the live Bound and held GIL satisfy its pointer preconditions.
    #[allow(unsafe_code)]
    unsafe {
        pyo3::ffi::PyCoro_CheckExact(awaitable.as_ptr()) != 0
    }
}

/// Resolve `__await__` from the object's type, as CPython's `await` protocol
/// does, so an instance attribute cannot shadow the awaitable's special method.
fn call_await_special_method<'py>(
    py: Python<'py>,
    awaitable: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let type_getattribute = py.get_type::<PyType>().getattr("__getattribute__")?;
    let awaitable_type = awaitable.get_type();
    let mro = type_getattribute
        .call1((&awaitable_type, "__mro__"))?
        .cast_into::<PyTuple>()?;

    for base in mro.iter() {
        let namespace = type_getattribute.call1((&base, "__dict__"))?;
        if !namespace.contains("__await__")? {
            continue;
        }

        let descriptor = namespace.get_item("__await__")?;
        let descriptor_type = descriptor.get_type();
        let descriptor_get = match type_getattribute.call1((&descriptor_type, "__get__")) {
            Ok(descriptor_get) => Some(descriptor_get),
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => None,
            Err(error) => return Err(error),
        };
        let method = match descriptor_get {
            Some(descriptor_get) => {
                descriptor_get.call1((&descriptor, awaitable, &awaitable_type))?
            }
            None => descriptor,
        };
        return method.call0();
    }

    Err(PyTypeError::new_err(format!(
        "object {} can't be used in 'await' expression",
        awaitable_type.name()?
    )))
}

fn async_for_invalid_anext(
    py: Python<'_>,
    awaitable: &Bound<'_, PyAny>,
    cause: PyErr,
) -> PyResult<PyErr> {
    let type_name = awaitable.get_type().name()?.to_string();
    let error = PyTypeError::new_err(format!(
        "'async for' received an invalid object from __anext__: {type_name}"
    ));
    error.set_context(py, Some(cause.clone_ref(py)));
    error.set_cause(py, Some(cause));
    Ok(error)
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

pub(crate) fn normalize_throw(
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
        let exception_class = match exception_type.cast::<PyType>() {
            Ok(exception_class) => exception_class,
            Err(_) => {
                let type_name = python_type_name(py, exception_type)?;
                return Err(PyTypeError::new_err(format!(
                    "exceptions must be classes or instances deriving from BaseException, not {type_name}"
                )));
            }
        };
        let constructed = match value {
            Some(value) if value.bind(py).is_instance_of::<PyBaseException>() => value,
            Some(value) if !value.bind(py).is_none() => {
                exception_class.call1((value.bind(py),))?.unbind()
            }
            _ => exception_class.call0()?.unbind(),
        };
        if !constructed.bind(py).is_instance_of::<PyBaseException>() {
            let type_name = python_type_name(py, constructed.bind(py))?;
            return Err(PyTypeError::new_err(format!(
                "exceptions must be classes or instances deriving from BaseException, not {type_name}"
            )));
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

fn python_type_name(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<String> {
    py.import("builtins")?
        .getattr("type")?
        .call1((value,))?
        .getattr("__name__")?
        .extract()
}
