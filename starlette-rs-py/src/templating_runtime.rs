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
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyJinja2Templates>()?;
    module.add_class::<PyTemplateUrlFor>()?;
    module.add_function(wrap_pyfunction!(templating_require_jinja2, module)?)?;
    module.add_function(wrap_pyfunction!(templating_render, module)?)?;
    module.add_function(wrap_pyfunction!(templating_response_call, module)?)?;
    Ok(())
}

#[pyfunction(name = "_templating_require_jinja2")]
fn templating_require_jinja2(py: Python<'_>) -> PyResult<Py<PyAny>> {
    match py.import("jinja2") {
        Ok(module) => Ok(module.into_any().unbind()),
        Err(error) if error.is_instance_of::<PyImportError>(py) => {
            let import_error =
                PyImportError::new_err("jinja2 must be installed to use Jinja2Templates");
            import_error.set_cause(py, Some(error));
            Err(import_error)
        }
        Err(error) => Err(error),
    }
}

#[pyclass(name = "_Jinja2Templates", unsendable)]
pub(crate) struct PyJinja2Templates {
    env: Py<PyAny>,
    context_processors: Py<PyAny>,
}

#[pymethods]
impl PyJinja2Templates {
    #[new]
    #[pyo3(signature = (directory=None, *, context_processors=None, env=None))]
    fn new(
        py: Python<'_>,
        directory: Option<Py<PyAny>>,
        context_processors: Option<Py<PyAny>>,
        env: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let directory_truthy = directory
            .as_ref()
            .map(|value| value.bind(py).is_truthy())
            .transpose()?
            .unwrap_or(false);
        let env_truthy = env
            .as_ref()
            .map(|value| value.bind(py).is_truthy())
            .transpose()?
            .unwrap_or(false);
        if directory_truthy == env_truthy {
            return Err(PyAssertionError::new_err(
                "either 'directory' or 'env' arguments must be passed",
            ));
        }

        let context_processors = match context_processors {
            Some(processors) if processors.bind(py).is_truthy()? => processors,
            _ => PyList::empty(py).into_any().unbind(),
        };

        let env = match directory {
            Some(directory) => {
                let jinja2 = py.import("jinja2")?;
                let loader = jinja2
                    .getattr("FileSystemLoader")?
                    .call1((directory.bind(py),))?;
                let kwargs = PyDict::new(py);
                kwargs.set_item("loader", loader)?;
                kwargs.set_item("autoescape", jinja2.getattr("select_autoescape")?.call0()?)?;
                jinja2
                    .getattr("Environment")?
                    .call((), Some(&kwargs))?
                    .unbind()
            }
            None => env.ok_or_else(|| {
                PyAssertionError::new_err("either 'directory' or 'env' arguments must be passed")
            })?,
        };

        let templates = Self {
            env,
            context_processors,
        };
        templates.setup_env_defaults(py, templates.env.bind(py))?;
        Ok(templates)
    }

    #[getter]
    fn env(&self, py: Python<'_>) -> Py<PyAny> {
        self.env.clone_ref(py)
    }

    #[setter]
    fn set_env(&mut self, env: Py<PyAny>) {
        self.env = env;
    }

    #[getter]
    fn context_processors(&self, py: Python<'_>) -> Py<PyAny> {
        self.context_processors.clone_ref(py)
    }

    #[setter]
    fn set_context_processors(&mut self, processors: Py<PyAny>) {
        self.context_processors = processors;
    }

    fn get_template(&self, py: Python<'_>, name: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.env
            .bind(py)
            .call_method1("get_template", (name,))
            .map(Bound::unbind)
    }

    #[pyo3(signature = (env))]
    fn _setup_env_defaults(&self, py: Python<'_>, env: &Bound<'_, PyAny>) -> PyResult<()> {
        self.setup_env_defaults(py, env)
    }

    fn _template_response(
        &self,
        py: Python<'_>,
        arguments: &Bound<'_, PyTuple>,
    ) -> PyResult<Py<PyAny>> {
        let request = arguments.get_item(0)?;
        let name = arguments.get_item(1)?;
        let response_type = arguments.get_item(2)?;
        let context = arguments.get_item(3)?;
        let context = match (!context.is_none() && context.is_truthy()?).then(|| context.unbind()) {
            Some(context) => context,
            _ => PyDict::new(py).into_any().unbind(),
        };
        context
            .bind(py)
            .call_method1("setdefault", ("request", &request))?;

        for processor in self.context_processors.bind(py).try_iter()? {
            let processor = processor?;
            let additions = processor.call1((&request,))?;
            context.bind(py).call_method1("update", (additions,))?;
        }

        let template = self.get_template(py, &name)?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("status_code", arguments.get_item(4)?)?;
        kwargs.set_item("headers", arguments.get_item(5)?)?;
        kwargs.set_item("media_type", arguments.get_item(6)?)?;
        kwargs.set_item("background", arguments.get_item(7)?)?;
        response_type
            .call((template, context), Some(&kwargs))
            .map(Bound::unbind)
    }
}

impl PyJinja2Templates {
    fn setup_env_defaults(&self, py: Python<'_>, env: &Bound<'_, PyAny>) -> PyResult<()> {
        let jinja2 = py.import("jinja2")?;
        let decorator = match jinja2.getattr("pass_context") {
            Ok(decorator) => decorator,
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => {
                jinja2.getattr("contextfunction")?
            }
            Err(error) => return Err(error),
        };
        let url_for = Py::new(py, PyTemplateUrlFor)?.into_bound(py);
        let url_for = decorator.call1((url_for,))?;
        let globals = env.getattr("globals")?;
        globals.call_method1("setdefault", ("url_for", url_for))?;
        Ok(())
    }
}

#[pyclass(name = "_TemplateUrlFor", unsendable, dict)]
struct PyTemplateUrlFor;

#[pymethods]
impl PyTemplateUrlFor {
    #[pyo3(signature = (context, name, /, **path_params))]
    fn __call__(
        &self,
        context: &Bound<'_, PyAny>,
        name: &Bound<'_, PyAny>,
        path_params: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Py<PyAny>> {
        let request = context.get_item("request")?;
        request
            .call_method("url_for", (name,), path_params)
            .map(Bound::unbind)
    }
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

#[pyfunction(name = "_templating_response_call")]
fn templating_response_call(
    py: Python<'_>,
    response_call: Py<PyAny>,
    template: Py<PyAny>,
    context: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        TemplateResponseCall {
            response_call,
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
    response_call: Py<PyAny>,
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
            MachineResume::AsyncIterationComplete(_) => Err(PyRuntimeError::new_err(
                "template response unexpectedly received async-iteration completion",
            )),
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
        let awaitable = self.response_call.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = Some(TemplateResponsePending::ResponseCall);
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}
