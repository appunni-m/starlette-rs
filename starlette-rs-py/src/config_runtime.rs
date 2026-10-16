//! Rust-owned configuration lookup and environment mutation policy.
//!
//! Python mapping objects and cast callables remain owned by Python. Rust
//! selects the precedence, performs file parsing, applies bool conversion, and
//! translates cast failures to the Starlette-compatible error surface.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyKeyError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule, PySet, PyString};

create_exception!(_core, EnvironError, PyException);

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add_class::<PyUndefined>()?;
    module.add_class::<PyEnviron>()?;
    module.add_class::<PyConfig>()?;
    module.add_function(wrap_pyfunction!(config_get, module)?)?;
    module.add("EnvironError", py.get_type::<EnvironError>())?;
    py.get_type::<PyUndefined>()
        .setattr("__module__", "starlette.config")?;
    py.get_type::<EnvironError>()
        .setattr("__module__", "starlette.config")?;
    Ok(())
}

#[pyclass(name = "undefined")]
struct PyUndefined;

#[pymethods]
impl PyUndefined {
    #[new]
    fn new() -> Self {
        Self
    }
}

#[pyclass(name = "_Environ")]
struct PyEnviron {
    environ: Py<PyAny>,
    has_been_read: Py<PySet>,
}

#[pymethods]
impl PyEnviron {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.environ)?;
        visit.call(&self.has_been_read)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.environ = py.None();
        // Reuse the existing set so clearing cannot fail from allocating a
        // replacement while the cycle collector is breaking ownership edges.
        self.has_been_read.bind(py).clear();
    }

    #[new]
    fn new(py: Python<'_>, environ: Py<PyAny>) -> PyResult<Self> {
        Ok(Self {
            environ,
            has_been_read: PySet::empty(py)?.unbind(),
        })
    }

    fn __getitem__(&self, py: Python<'_>, key: Py<PyAny>) -> PyResult<Py<PyAny>> {
        self.has_been_read.bind(py).add(key.bind(py))?;
        self.environ
            .bind(py)
            .call_method1("__getitem__", (key,))
            .map(Bound::unbind)
    }

    fn __setitem__(&self, py: Python<'_>, key: Py<PyAny>, value: Py<PyAny>) -> PyResult<()> {
        if self.has_been_read.bind(py).contains(key.bind(py))? {
            return Err(environ_error("set", key.bind(py))?);
        }
        self.environ
            .bind(py)
            .call_method1("__setitem__", (key, value))?;
        Ok(())
    }

    fn __delitem__(&self, py: Python<'_>, key: Py<PyAny>) -> PyResult<()> {
        if self.has_been_read.bind(py).contains(key.bind(py))? {
            return Err(environ_error("delete", key.bind(py))?);
        }
        self.environ.bind(py).call_method1("__delitem__", (key,))?;
        Ok(())
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        py.import("builtins")?
            .getattr("iter")?
            .call1((self.environ.bind(py),))
            .map(Bound::unbind)
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        py.import("builtins")?
            .getattr("len")?
            .call1((self.environ.bind(py),))?
            .extract()
    }

    #[getter]
    fn _environ(&self, py: Python<'_>) -> Py<PyAny> {
        self.environ.clone_ref(py)
    }

    #[setter(_environ)]
    fn set_environ(&mut self, environ: Py<PyAny>) {
        self.environ = environ;
    }

    #[getter]
    fn _has_been_read(&self, py: Python<'_>) -> Py<PyAny> {
        self.has_been_read.clone_ref(py).into_any()
    }
}

fn environ_error(operation: &str, key: &Bound<'_, PyAny>) -> PyResult<PyErr> {
    let key = format_empty(key)?;
    let operation = match operation {
        "set" => "set",
        _ => "delete",
    };
    Ok(EnvironError::new_err(format!(
        "Attempting to {operation} environ['{key}'], but the value has already been read."
    )))
}

#[pyclass(name = "_Config")]
struct PyConfig {
    environ: Py<PyAny>,
    env_prefix: Py<PyAny>,
    file_values: Py<PyDict>,
}

#[pymethods]
impl PyConfig {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.environ)?;
        visit.call(&self.env_prefix)?;
        visit.call(&self.file_values)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.environ = py.None();
        self.env_prefix = py.None();
        self.file_values.bind(py).clear();
    }

    #[new]
    fn new(
        py: Python<'_>,
        env_file: Py<PyAny>,
        environ: Py<PyAny>,
        env_prefix: Py<PyAny>,
        encoding: Py<PyAny>,
    ) -> PyResult<Self> {
        let file_values = PyDict::new(py).unbind();
        let env_file = env_file.bind(py);
        let is_none = env_file.is_none();
        let mut config = Self {
            environ,
            env_prefix,
            file_values,
        };
        if !is_none {
            let is_file = py
                .import("os")?
                .getattr("path")?
                .getattr("isfile")?
                .call1((env_file,))?
                .is_truthy()?;
            if is_file {
                config.file_values = config.read_file(py, env_file, encoding.bind(py))?;
            } else {
                let path = env_file.str()?.extract::<String>()?;
                py.import("warnings")?
                    .getattr("warn")?
                    .call1((format!("Config file '{path}' not found."),))?;
            }
        }
        Ok(config)
    }

    fn read_file(
        &self,
        py: Python<'_>,
        file_name: &Bound<'_, PyAny>,
        encoding: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyDict>> {
        read_file(py, file_name, encoding)
    }

    fn perform_cast(
        &self,
        py: Python<'_>,
        key: Py<PyAny>,
        value: &Bound<'_, PyAny>,
        cast: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        perform_cast(py, key.bind(py), value, cast).map(Bound::unbind)
    }

    #[getter]
    fn environ(&self, py: Python<'_>) -> Py<PyAny> {
        self.environ.clone_ref(py)
    }

    #[setter]
    fn set_environ(&mut self, environ: Py<PyAny>) {
        self.environ = environ;
    }

    #[getter]
    fn env_prefix(&self, py: Python<'_>) -> Py<PyAny> {
        self.env_prefix.clone_ref(py)
    }

    #[setter]
    fn set_env_prefix(&mut self, env_prefix: Py<PyAny>) {
        self.env_prefix = env_prefix;
    }

    #[getter]
    fn file_values(&self, py: Python<'_>) -> Py<PyDict> {
        self.file_values.clone_ref(py)
    }

    #[setter]
    fn set_file_values(&mut self, file_values: Py<PyDict>) {
        self.file_values = file_values;
    }
}

#[pyfunction(name = "_config_get")]
fn config_get(
    py: Python<'_>,
    config: Py<PyAny>,
    key: Py<PyAny>,
    cast: Py<PyAny>,
    default: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let config = config.bind(py);
    let lookup_key = config.getattr("env_prefix")?.add(key.bind(py))?;

    let environ = config.getattr("environ")?;
    let value = if environ.contains(&lookup_key)? {
        Some(config.getattr("environ")?.get_item(&lookup_key)?)
    } else {
        let file_values = config.getattr("file_values")?;
        if file_values.contains(&lookup_key)? {
            Some(config.getattr("file_values")?.get_item(&lookup_key)?)
        } else {
            None
        }
    };
    let value = match value {
        Some(value) => value,
        None if default.bind(py).is(py.get_type::<PyUndefined>()) => {
            let key_text = format_empty(&lookup_key)?;
            return Err(PyKeyError::new_err(format!(
                "Config '{key_text}' is missing, and has no default."
            )));
        }
        None => default.bind(py).clone(),
    };

    config
        .call_method1("_perform_cast", (lookup_key, value, cast))
        .map(Bound::unbind)
}

fn format_empty(value: &Bound<'_, PyAny>) -> PyResult<String> {
    value
        .py()
        .import("builtins")?
        .getattr("format")?
        .call1((value, ""))?
        .extract()
}

fn read_file(
    py: Python<'_>,
    file_name: &Bound<'_, PyAny>,
    encoding: &Bound<'_, PyAny>,
) -> PyResult<Py<PyDict>> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("encoding", encoding)?;
    let file = py
        .import("builtins")?
        .getattr("open")?
        .call((file_name,), Some(&kwargs))?;
    let lines = file.call_method0("readlines");
    let close = file.call_method0("close");
    let lines = lines?;
    close?;

    let values = PyDict::new(py);
    for line in lines.try_iter()? {
        let line = line?;
        let line = line.call_method0("strip")?;
        let line_text = line.extract::<String>()?;
        if !line_text.starts_with('#') {
            if let Some((raw_key, raw_value)) = line_text.split_once('=') {
                let key = PyString::new(py, raw_key).call_method0("strip")?;
                let value = PyString::new(py, raw_value)
                    .call_method0("strip")?
                    .call_method1("strip", ("\"'",))?;
                values.set_item(key, value)?;
            }
        }
    }
    Ok(values.unbind())
}

fn perform_cast<'py>(
    py: Python<'py>,
    key: &Bound<'py, PyAny>,
    value: &Bound<'py, PyAny>,
    cast: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let Some(cast) = cast else {
        return Ok(value.clone());
    };
    if value.is_none() {
        return Ok(value.clone());
    }

    let bool_type = py.get_type::<pyo3::types::PyBool>();
    let str_type = py.get_type::<PyString>();
    if cast.is(&bool_type) && value.is_instance(&str_type)? {
        let normalized = value.call_method0("lower")?;
        let normalized_text = normalized.extract::<String>()?;
        return match normalized_text.as_str() {
            "true" | "1" => Ok(true.into_pyobject(py)?.to_owned().into_any()),
            "false" | "0" => Ok(false.into_pyobject(py)?.to_owned().into_any()),
            _ => {
                let key = format_empty(key)?;
                let normalized = format_empty(&normalized)?;
                Err(PyValueError::new_err(format!(
                    "Config '{key}' has value '{normalized}'. Not a valid bool."
                )))
            }
        };
    }

    match cast.call1((value,)) {
        Ok(converted) => Ok(converted),
        Err(error)
            if error.is_instance_of::<PyTypeError>(py)
                || error.is_instance_of::<PyValueError>(py) =>
        {
            let key = format_empty(key)?;
            let value = format_empty(value)?;
            let cast_name = format_empty(&cast.getattr("__name__")?)?;
            let wrapped = PyValueError::new_err(format!(
                "Config '{key}' has value '{value}'. Not a valid {cast_name}."
            ));
            // Config raises its replacement ValueError inside the except block,
            // so Python exposes the cast failure as the implicit exception context.
            wrapped.value(py).setattr("__context__", error.value(py))?;
            Err(wrapped)
        }
        Err(error) => Err(error),
    }
}
