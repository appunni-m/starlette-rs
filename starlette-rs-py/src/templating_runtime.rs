//! Rust-owned compatibility behavior for Starlette's Jinja2 integration.
//!
//! Jinja remains the template engine and Python retains user request/context
//! objects. Rust owns Starlette's environment setup, context merge order,
//! template selection, response construction flow, and ASGI debug-extension
//! decision.

use pyo3::exceptions::{PyAssertionError, PyAttributeError, PyImportError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyJinja2Templates>()?;
    module.add_function(wrap_pyfunction!(templating_require_jinja2, module)?)?;
    module.add_function(wrap_pyfunction!(templating_render, module)?)?;
    module.add_function(wrap_pyfunction!(templating_response_init, module)?)?;
    module.add_function(wrap_pyfunction!(templating_url_for, module)?)?;
    module.add_function(wrap_pyfunction!(templating_context_decorator, module)?)?;
    module.add_function(wrap_pyfunction!(templating_response_call, module)?)?;
    Ok(())
}

#[pyfunction(name = "_templating_require_jinja2")]
fn templating_require_jinja2(py: Python<'_>) -> PyResult<Py<PyAny>> {
    match py.import("jinja2") {
        Ok(module) => Ok(module.into_any().unbind()),
        Err(error) if error.is_instance_of::<PyImportError>(py) => {
            Err(jinja_import_error(py, error)?)
        }
        Err(error) => Err(error),
    }
}

#[pyfunction(name = "_templating_context_decorator")]
fn templating_context_decorator(jinja2: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    // Resolve at module import, just as the source does, including failure
    // when neither supported decorator exists.
    let result = match jinja2.getattr("pass_context") {
        Ok(_) => jinja2.getattr("pass_context").map(Bound::unbind),
        Err(error) if error.is_instance_of::<PyAttributeError>(jinja2.py()) => {
            jinja2.getattr("contextfunction").map(Bound::unbind)
        }
        Err(error) => Err(error),
    };
    match result {
        Err(error) if error.is_instance_of::<PyImportError>(jinja2.py()) => {
            Err(jinja_import_error(jinja2.py(), error)?)
        }
        result => result,
    }
}

fn jinja_import_error(py: Python<'_>, error: PyErr) -> PyResult<PyErr> {
    let import_error = PyImportError::new_err("jinja2 must be installed to use Jinja2Templates");
    import_error
        .value(py)
        .setattr("__context__", error.value(py))?;
    import_error.set_cause(py, Some(error));
    Ok(import_error)
}

// The Python facade owns template instances and their Python references. This
// class exposes Rust-owned operations without duplicating that state.
#[pyclass(name = "_Jinja2Templates")]
pub(crate) struct PyJinja2Templates;

#[pymethods]
impl PyJinja2Templates {
    #[staticmethod]
    fn initialize_for(
        py: Python<'_>,
        templates: &Bound<'_, PyAny>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<()> {
        let directory = arguments.get_item(0)?;
        let processors = arguments.get_item(1)?;
        let env = arguments.get_item(2)?;
        if directory.is_truthy()? == env.is_truthy()? {
            return Err(PyAssertionError::new_err(
                "either 'directory' or 'env' arguments must be passed",
            ));
        }
        let processors = if processors.is_truthy()? {
            processors
        } else {
            PyList::empty(py).into_any()
        };
        templates.setattr("context_processors", processors)?;
        let env = if !directory.is_none() {
            let jinja2 = py.import("starlette.templating")?.getattr("jinja2")?;
            let loader = jinja2.getattr("FileSystemLoader")?.call1((directory,))?;
            let kwargs = PyDict::new(py);
            kwargs.set_item("loader", loader)?;
            kwargs.set_item("autoescape", jinja2.getattr("select_autoescape")?.call0()?)?;
            jinja2.getattr("Environment")?.call((), Some(&kwargs))?
        } else {
            env
        };
        templates.setattr("env", env)?;
        // Python evaluates `self._setup_env_defaults` before `self.env` in
        // `self._setup_env_defaults(self.env)`. Keep that order observable to
        // subclasses that override `__getattribute__`.
        let setup_env_defaults = templates.getattr("_setup_env_defaults")?;
        let env = templates.getattr("env")?;
        setup_env_defaults.call1((env,))?;
        Ok(())
    }

    #[staticmethod]
    fn setup_for(env: &Bound<'_, PyAny>, url_for: &Bound<'_, PyAny>) -> PyResult<()> {
        env.getattr("globals")?
            .call_method1("setdefault", ("url_for", url_for))?;
        Ok(())
    }

    #[staticmethod]
    fn template_for(templates: &Bound<'_, PyAny>, name: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        templates
            .getattr("env")?
            .call_method1("get_template", (name,))
            .map(Bound::unbind)
    }

    #[staticmethod]
    fn response_for(
        py: Python<'_>,
        templates: &Bound<'_, PyAny>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<Py<PyAny>> {
        let request = arguments.get_item(0)?;
        let name = arguments.get_item(1)?;
        let response_type = arguments.get_item(2)?;
        let supplied = arguments.get_item(3)?;
        let context = if supplied.is_truthy()? {
            supplied
        } else {
            PyDict::new(py).into_any()
        };
        context.call_method1("setdefault", ("request", &request))?;
        for processor in templates.getattr("context_processors")?.try_iter()? {
            let processor = processor?;
            // Python evaluates `context.update` before invoking the processor
            // argument. Resolve the possibly overridden method first so a
            // dict subclass can observe the same callback order.
            let update = context.getattr("update")?;
            let additions = processor.call1((&request,))?;
            update.call1((additions,))?;
        }
        let template = templates.call_method1("get_template", (name,))?;
        let kwargs = PyDict::new(py);
        for (index, name) in [
            (4, "status_code"),
            (5, "headers"),
            (6, "media_type"),
            (7, "background"),
        ] {
            kwargs.set_item(name, arguments.get_item(index)?)?;
        }
        response_type
            .call((template, context), Some(&kwargs))
            .map(Bound::unbind)
    }
}

#[pyfunction(name = "_templating_url_for")]
fn templating_url_for(
    context: &Bound<'_, PyAny>,
    name: &Bound<'_, PyAny>,
    path_params: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let request = context.get_item("request")?;
    request
        .call_method("url_for", (name,), Some(path_params))
        .map(Bound::unbind)
}

#[pyfunction(name = "_templating_render")]
fn templating_render(
    template: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    template
        .call_method1("render", (context,))
        .map(Bound::unbind)
}

#[pyfunction(name = "_templating_response_init")]
fn templating_response_init(
    response_super: &Bound<'_, PyAny>,
    template: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
    status_code: &Bound<'_, PyAny>,
    headers: &Bound<'_, PyAny>,
    media_type: &Bound<'_, PyAny>,
    background: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let content = template.call_method1("render", (context,))?;
    // The pinned implementation resolves `super().__init__` after rendering,
    // so filters can change the base initializer observed by this lookup.
    response_super.call_method1(
        "__init__",
        (content, status_code, headers, media_type, background),
    )?;
    Ok(())
}

#[pyfunction(name = "_templating_response_call")]
fn templating_response_call(
    py: Python<'_>,
    response_super: Py<PyAny>,
    template: Py<PyAny>,
    context: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        TemplateResponseCall {
            response_super,
            template,
            context,
            scope,
            receive,
            send,
            pending: None,
        },
    )
}

struct TemplateResponseCall {
    response_super: Py<PyAny>,
    template: Py<PyAny>,
    context: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    pending: Option<TemplateResponsePending>,
}

#[derive(Clone, Copy)]
enum TemplateResponsePending {
    DebugEvent,
    ResponseCall,
}

impl AwaitableStateMachine for TemplateResponseCall {
    fn traverse(
        &self,
        visit: &pyo3::class::gc::PyVisit<'_>,
    ) -> Result<(), pyo3::class::gc::PyTraverseError> {
        visit.call(&self.response_super)?;
        visit.call(&self.template)?;
        visit.call(&self.context)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(_) => match self.pending.take() {
                Some(TemplateResponsePending::DebugEvent) => self.call_response(py),
                Some(TemplateResponsePending::ResponseCall) => {
                    Ok(MachineAction::Complete(py.None()))
                }
                None => Err(PyRuntimeError::new_err(
                    "template response resumed without a pending operation",
                )),
            },
            MachineResume::Error(error) => {
                self.pending = None;
                Err(error)
            }
            MachineResume::AsyncIterationComplete(error) => {
                self.pending = None;
                Err(error)
            }
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "template response already has an operation pending",
            )),
        }
    }
}

impl TemplateResponseCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let empty = PyDict::new(py);
        let request = self
            .context
            .bind(py)
            .call_method1("get", ("request", &empty))?;
        let extensions = request.call_method1("get", ("extensions", &empty))?;
        if extensions.contains("http.response.debug")? {
            let info = PyDict::new(py);
            info.set_item("template", self.template.bind(py))?;
            info.set_item("context", self.context.bind(py))?;
            let message = PyDict::new(py);
            message.set_item("type", "http.response.debug")?;
            message.set_item("info", info)?;
            let awaitable = self.send.bind(py).call1((message,))?;
            self.pending = Some(TemplateResponsePending::DebugEvent);
            Ok(MachineAction::Await(awaitable.unbind()))
        } else {
            self.call_response(py)
        }
    }

    fn call_response(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        // Resolve the base response method here, after the optional debug send
        // has completed. The pinned Python method evaluates `super().__call__`
        // only after that await, so the ASGI callback can affect lookup.
        let response_call = self.response_super.bind(py).getattr("__call__")?;
        let awaitable = response_call.call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = Some(TemplateResponsePending::ResponseCall);
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}
