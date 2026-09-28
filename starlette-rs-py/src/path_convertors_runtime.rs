//! Rust-owned built-in path-convertor behavior with Python value protocols.

use pyo3::exceptions::{PyAssertionError, PyNotImplementedError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(convert_builtin, module)?)?;
    module.add_function(wrap_pyfunction!(format_builtin, module)?)?;
    module.add_function(wrap_pyfunction!(register_convertor, module)?)?;
    Ok(())
}

#[pyfunction(name = "_convert_builtin_convertor")]
fn convert_builtin(py: Python<'_>, kind: &str, value: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let value = value.bind(py);
    match kind {
        "base" => Err(PyNotImplementedError::new_err(())),
        "str" => Ok(value.clone().unbind()),
        "path" => python_str(py, value).map(Bound::unbind),
        "int" => py
            .import("builtins")?
            .getattr("int")?
            .call1((value,))
            .map(Bound::unbind),
        "float" => py
            .import("builtins")?
            .getattr("float")?
            .call1((value,))
            .map(Bound::unbind),
        "uuid" => py
            .import("uuid")?
            .getattr("UUID")?
            .call1((value,))
            .map(Bound::unbind),
        _ => Err(PyValueError::new_err(format!(
            "unknown built-in path convertor '{kind}'"
        ))),
    }
}

#[pyfunction(name = "_format_builtin_convertor")]
fn format_builtin(py: Python<'_>, kind: &str, value: Py<PyAny>) -> PyResult<String> {
    let value = value.bind(py);
    match kind {
        "base" => Err(PyNotImplementedError::new_err(())),
        "str" => {
            let value = python_str(py, value)?;
            let value = value.extract::<String>()?;
            if value.contains('/') {
                return Err(PyAssertionError::new_err("May not contain path separators"));
            }
            if value.is_empty() {
                return Err(PyAssertionError::new_err("Must not be empty"));
            }
            Ok(value)
        }
        "path" => {
            let value = python_str(py, value)?;
            value.extract::<String>()
        }
        "int" => {
            let value = py.import("builtins")?.getattr("int")?.call1((value,))?;
            if !value
                .rich_compare(0, pyo3::class::basic::CompareOp::Ge)?
                .is_truthy()?
            {
                return Err(PyAssertionError::new_err(
                    "Negative integers are not supported",
                ));
            }
            python_str(py, &value)?.extract::<String>()
        }
        "float" => {
            let value = py
                .import("builtins")?
                .getattr("float")?
                .call1((value,))?
                .extract::<f64>()?;
            if matches!(
                value.partial_cmp(&0.0),
                Some(std::cmp::Ordering::Less) | None
            ) {
                return Err(PyAssertionError::new_err(
                    "Negative floats are not supported",
                ));
            }
            if value.is_nan() {
                return Err(PyAssertionError::new_err("NaN values are not supported"));
            }
            if value.is_infinite() {
                return Err(PyAssertionError::new_err(
                    "Infinite values are not supported",
                ));
            }
            let formatted = py
                .import("builtins")?
                .getattr("format")?
                .call1((value, "0.20f"))?
                .extract::<String>()?;
            Ok(formatted
                .trim_end_matches('0')
                .trim_end_matches('.')
                .to_owned())
        }
        "uuid" => {
            let value = python_str(py, value)?;
            value.extract::<String>()
        }
        _ => Err(PyValueError::new_err(format!(
            "unknown built-in path convertor '{kind}'"
        ))),
    }
}

#[pyfunction(name = "_register_url_convertor")]
fn register_convertor(
    convertors: &Bound<'_, PyDict>,
    key: &Bound<'_, PyAny>,
    convertor: Py<PyAny>,
) -> PyResult<()> {
    convertors.set_item(key, convertor)
}

fn python_str<'py>(py: Python<'py>, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    py.import("builtins")?.getattr("str")?.call1((value,))
}
