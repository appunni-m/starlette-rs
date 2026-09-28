//! Rust-owned lookup and deprecation behavior for `starlette.status`.
//!
//! The public HTTP and WebSocket integers remain Python module data. This
//! boundary owns deprecated-name resolution, warning emission, and the sorted
//! module attribute listing while preserving CPython's warning machinery.

use pyo3::exceptions::{PyAttributeError, PyKeyError};
use pyo3::prelude::*;
use pyo3::types::PyModule;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(status_getattr, module)?)?;
    module.add_function(wrap_pyfunction!(status_dir, module)?)?;
    Ok(())
}

#[pyfunction]
fn status_getattr(py: Python<'_>, name: String, deprecated: Py<PyAny>) -> PyResult<Py<PyAny>> {
    let value = deprecated.bind(py).call_method1("get", (&name,))?;
    if value.is_truthy()? {
        let replacement = match name.as_str() {
            "HTTP_413_REQUEST_ENTITY_TOO_LARGE" => "HTTP_413_CONTENT_TOO_LARGE",
            "HTTP_414_REQUEST_URI_TOO_LONG" => "HTTP_414_URI_TOO_LONG",
            "HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE" => "HTTP_416_RANGE_NOT_SATISFIABLE",
            "HTTP_422_UNPROCESSABLE_ENTITY" => "HTTP_422_UNPROCESSABLE_CONTENT",
            _ => return Err(PyKeyError::new_err(name)),
        };
        let message = format!("'{name}' is deprecated. Use '{replacement}' instead.");
        let warning_type = py
            .import("starlette.exceptions")?
            .getattr("StarletteDeprecationWarning")?;
        let kwargs = pyo3::types::PyDict::new(py);
        kwargs.set_item("category", warning_type)?;
        kwargs.set_item("stacklevel", 3)?;
        py.import("warnings")?
            .getattr("warn")?
            .call((message,), Some(&kwargs))?;
        return Ok(value.unbind());
    }
    Err(PyAttributeError::new_err(format!(
        "module 'starlette.status' has no attribute '{name}'"
    )))
}

#[pyfunction]
fn status_dir(
    py: Python<'_>,
    public_names: Py<PyAny>,
    deprecated: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    let list = py.import("builtins")?.getattr("list")?;
    let names = list.call1((public_names.bind(py),))?;
    let aliases = list.call1((deprecated.bind(py).call_method0("keys")?,))?;
    names.call_method1("extend", (aliases,))?;
    py.import("builtins")?
        .getattr("sorted")?
        .call1((names,))
        .map(Bound::unbind)
}
