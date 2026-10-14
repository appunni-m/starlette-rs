//! Rust-backed representation for Starlette middleware configuration values.

use pyo3::exceptions::{PyAttributeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule, PyString, PyTuple};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(middleware_repr, module)?)?;
    module.add_function(wrap_pyfunction!(middleware_iter, module)?)?;
    Ok(())
}

/// Expand the mapping used by Python's `**kwargs` call syntax.
///
/// Route-local and application middleware both accept custom Middleware
/// iterators, whose third yielded value can be any mapping rather than only a
/// `dict`.
pub(crate) fn middleware_kwargs_to_dict<'py>(
    py: Python<'py>,
    mapping: &Bound<'py, PyAny>,
    callable: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let keys = match mapping.getattr("keys") {
        Ok(keys) => keys.call0()?,
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => {
            let type_name = mapping.get_type().name()?.to_string();
            return Err(PyTypeError::new_err(format!(
                "argument after ** must be a mapping, not {type_name}"
            )));
        }
        Err(error) => return Err(error),
    };
    let result = PyDict::new(py);
    for key in keys.try_iter()? {
        let key = key?;
        if !key.is_instance_of::<PyString>() {
            return Err(PyTypeError::new_err("keywords must be strings"));
        }
        if result.contains(&key)? {
            let key_repr = key.repr()?.extract::<String>()?;
            let callable_name = callable
                .getattr("__qualname__")
                .and_then(|name| name.extract::<String>())
                .unwrap_or_else(|_| "middleware".to_owned());
            return Err(PyTypeError::new_err(format!(
                "{callable_name}() got multiple values for keyword argument {key_repr}"
            )));
        }
        result.set_item(&key, mapping.get_item(&key)?)?;
    }
    Ok(result)
}

#[pyfunction(name = "_middleware_iter")]
fn middleware_iter(py: Python<'_>, middleware: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let values = PyTuple::new(
        py,
        [
            middleware.getattr("cls")?,
            middleware.getattr("args")?,
            middleware.getattr("kwargs")?,
        ],
    )?;
    py.import("builtins")?
        .getattr("iter")?
        .call1((values,))
        .map(Bound::unbind)
}

#[pyfunction(name = "_middleware_repr")]
fn middleware_repr(py: Python<'_>, middleware: &Bound<'_, PyAny>) -> PyResult<String> {
    let class_name = middleware
        .get_type()
        .getattr("__name__")?
        .extract::<String>()?;
    let callable = middleware.getattr("cls")?;
    let args = middleware.getattr("args")?;
    let kwargs = middleware.getattr("kwargs")?;
    let builtins = py.import("builtins")?;
    let class_callable_name = builtins
        .getattr("getattr")?
        .call1((callable, "__name__", ""))?;
    let class_callable_name = builtins
        .getattr("str")?
        .call1((class_callable_name,))?
        .extract::<String>()?;

    let repr = builtins.getattr("repr")?;
    let mut parts = vec![class_callable_name];
    for value in args.try_iter()? {
        parts.push(repr.call1((value?,))?.extract::<String>()?);
    }

    let stringify = builtins.getattr("str")?;
    for item in kwargs.getattr("items")?.call0()?.try_iter()? {
        let item = item?;
        let key = item.get_item(0)?;
        let value = item.get_item(1)?;
        let key = stringify.call1((key,))?.extract::<String>()?;
        let value = repr.call1((value,))?.extract::<String>()?;
        parts.push(format!("{key}={value}"));
    }

    Ok(format!("{class_name}({})", parts.join(", ")))
}
