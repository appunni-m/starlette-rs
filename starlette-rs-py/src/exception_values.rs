//! Rust-backed value formatting for Starlette's public exception objects.
//!
//! CPython remains authoritative for `http.HTTPStatus`, truth testing, format
//! protocols, and `repr`; Rust owns the exception-value selection and assembly
//! around those compatibility calls.

use pyo3::prelude::*;
use pyo3::types::{PyModule, PyString};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(http_exception_detail, module)?)?;
    module.add_function(wrap_pyfunction!(http_exception_string, module)?)?;
    module.add_function(wrap_pyfunction!(http_exception_repr, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_exception_reason, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_exception_string, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_exception_repr, module)?)?;
    Ok(())
}

/// Return an explicit detail unchanged or CPython's HTTP status reason phrase.
#[pyfunction(name = "_http_exception_detail")]
fn http_exception_detail(
    py: Python<'_>,
    status_code: Py<PyAny>,
    detail: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    if !detail.bind(py).is_none() {
        return Ok(detail);
    }
    py.import("http")?
        .getattr("HTTPStatus")?
        .call1((status_code,))?
        .getattr("phrase")
        .map(Bound::unbind)
}

/// Render `HTTPException.__str__` with Python's empty-format semantics.
#[pyfunction(name = "_http_exception_string")]
fn http_exception_string(
    py: Python<'_>,
    status_code: Py<PyAny>,
    detail: Py<PyAny>,
) -> PyResult<String> {
    exception_string(py, status_code.bind(py), detail.bind(py))
}

/// Render `HTTPException.__repr__`, using the dynamic public class name.
#[pyfunction(name = "_http_exception_repr")]
fn http_exception_repr(
    py: Python<'_>,
    class_name: &str,
    status_code: Py<PyAny>,
    detail: Py<PyAny>,
) -> PyResult<String> {
    let status_code = python_repr(py, status_code.bind(py))?;
    let detail = python_repr(py, detail.bind(py))?;
    Ok(format!(
        "{class_name}(status_code={status_code}, detail={detail})"
    ))
}

/// Match `reason or ""` while preserving a truthy Python value as-is.
#[pyfunction(name = "_websocket_exception_reason")]
fn websocket_exception_reason(py: Python<'_>, reason: Py<PyAny>) -> PyResult<Py<PyAny>> {
    if reason.bind(py).is_truthy()? {
        Ok(reason)
    } else {
        Ok(PyString::new(py, "").into_any().unbind())
    }
}

/// Render `WebSocketException.__str__` with Python's empty-format semantics.
#[pyfunction(name = "_websocket_exception_string")]
fn websocket_exception_string(
    py: Python<'_>,
    code: Py<PyAny>,
    reason: Py<PyAny>,
) -> PyResult<String> {
    exception_string(py, code.bind(py), reason.bind(py))
}

/// Render `WebSocketException.__repr__`, using the dynamic public class name.
#[pyfunction(name = "_websocket_exception_repr")]
fn websocket_exception_repr(
    py: Python<'_>,
    class_name: &str,
    code: Py<PyAny>,
    reason: Py<PyAny>,
) -> PyResult<String> {
    let code = python_repr(py, code.bind(py))?;
    let reason = python_repr(py, reason.bind(py))?;
    Ok(format!("{class_name}(code={code}, reason={reason})"))
}

fn exception_string(
    py: Python<'_>,
    left: &Bound<'_, PyAny>,
    right: &Bound<'_, PyAny>,
) -> PyResult<String> {
    let formatter = py.import("builtins")?.getattr("format")?;
    let left = formatter.call1((left, ""))?.extract::<String>()?;
    let right = formatter.call1((right, ""))?.extract::<String>()?;
    Ok(format!("{left}: {right}"))
}

fn python_repr(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<String> {
    py.import("builtins")?
        .getattr("repr")?
        .call1((value,))?
        .extract::<String>()
}
