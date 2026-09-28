//! Rust-backed representation for Starlette middleware configuration values.

use pyo3::prelude::*;
use pyo3::types::{PyModule, PyTuple};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(middleware_repr, module)?)?;
    module.add_function(wrap_pyfunction!(middleware_iter, module)?)?;
    Ok(())
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
