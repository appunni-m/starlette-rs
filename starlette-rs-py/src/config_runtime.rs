//! Rust-owned configuration lookup and environment mutation policy.
//!
//! Python mapping objects and cast callables remain owned by Python. Rust
//! selects the precedence, performs file parsing, applies bool conversion, and
//! translates cast failures to the Starlette-compatible error surface.

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
        self.environ.bind(py).call_method0("__len__")?.extract()
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
    let key = key.str()?.extract::<String>()?;
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

    fn get(
        &self,
        py: Python<'_>,
        key: Py<PyAny>,
        cast: Py<PyAny>,
        default: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let key = self
            .env_prefix
            .bind(py)
            .call_method1("__add__", (key.bind(py),))?;
        let key_text = key.str()?.extract::<String>()?;
        let value = if self.environ.bind(py).contains(&key)? {
            Some(self.environ.bind(py).get_item(&key)?)
        } else if self.file_values.bind(py).contains(&key)? {
            self.file_values.bind(py).get_item(&key)?
        } else {
            let default = default.bind(py);
            (!default.is(py.get_type::<PyUndefined>())).then(|| default.clone())
        };
        let Some(value) = value else {
            return Err(PyKeyError::new_err(format!(
                "Config '{key_text}' is missing, and has no default."
            )));
        };
        let cast = cast.bind(py);
        let cast = (!cast.is_none()).then(|| cast.clone());
        self.perform_cast(py, &key_text, &value, cast.as_ref())
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
        key: &str,
        value: &Bound<'_, PyAny>,
        cast: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        perform_cast(py, key, value, cast).map(Bound::unbind)
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
    key: &str,
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
        let normalized = value.call_method0("lower")?.extract::<String>()?;
        return match normalized.as_str() {
            "true" | "1" => Ok(true.into_pyobject(py)?.to_owned().into_any()),
            "false" | "0" => Ok(false.into_pyobject(py)?.to_owned().into_any()),
            _ => Err(PyValueError::new_err(format!(
                "Config '{key}' has value '{normalized}'. Not a valid bool."
            ))),
        };
    }

    match cast.call1((value,)) {
        Ok(converted) => Ok(converted),
        Err(error)
            if error.is_instance_of::<PyTypeError>(py)
                || error.is_instance_of::<PyValueError>(py) =>
        {
            let value = value.str()?.extract::<String>()?;
            let cast_name = cast.getattr("__name__")?.str()?.extract::<String>()?;
            Err(PyValueError::new_err(format!(
                "Config '{key}' has value '{value}'. Not a valid {cast_name}."
            )))
        }
        Err(error) => Err(error),
    }
}
