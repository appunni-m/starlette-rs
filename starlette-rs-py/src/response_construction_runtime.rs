//! Source-ordered construction over live Python response protocol values.

use pyo3::basic::CompareOp;
use pyo3::exceptions::PyAttributeError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};

pub(crate) fn initialize_headers(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    headers: Option<&Bound<'_, PyAny>>,
) -> PyResult<()> {
    let raw = PyList::empty(py);
    let keys = PyList::empty(py);
    if let Some(headers) = headers {
        for pair in headers.call_method0("items")?.try_iter()? {
            let (name, value) = pair?.extract::<(Bound<'_, PyAny>, Bound<'_, PyAny>)>()?;
            let name = name
                .call_method0("lower")?
                .call_method1("encode", ("latin-1",))?;
            let value = value.call_method1("encode", ("latin-1",))?;
            raw.append(PyTuple::new(py, [&name, &value])?)?;
            keys.append(name)?;
        }
    }
    let populate_length = !keys.contains(PyBytes::new(py, b"content-length"))?;
    let populate_type = !keys.contains(PyBytes::new(py, b"content-type"))?;
    let body = match response.getattr("body") {
        Ok(body) => body,
        Err(error) if error.is_instance_of::<PyAttributeError>(py) => py.None().into_bound(py),
        Err(error) => return Err(error),
    };
    if !body.is_none()
        && populate_length
        && !response
            .getattr("status_code")?
            .rich_compare(200, CompareOp::Lt)?
            .is_truthy()?
        && !PyTuple::new(py, [204, 304])?.contains(response.getattr("status_code")?)?
    {
        let length =
            PyString::new(py, &body.len()?.to_string()).call_method1("encode", ("latin-1",))?;
        raw.append(PyTuple::new(
            py,
            [PyBytes::new(py, b"content-length").into_any(), length],
        )?)?;
    }
    let mut content_type = response.getattr("media_type")?;
    if !content_type.is_none() && populate_type {
        if content_type
            .call_method1("startswith", ("text/",))?
            .is_truthy()?
            && !content_type.call_method0("lower")?.contains("charset=")?
        {
            let operator = py.import("operator")?;
            let suffix =
                operator.call_method1("add", ("; charset=", response.getattr("charset")?))?;
            content_type = operator.call_method1("iadd", (content_type, suffix))?;
        }
        let encoded = content_type.call_method1("encode", ("latin-1",))?;
        raw.append(PyTuple::new(
            py,
            [PyBytes::new(py, b"content-type").into_any(), encoded],
        )?)?;
    }
    // User callbacks run before installing the completed list. Do not borrow
    // the native response across any of those reentrant Python calls.
    response.setattr("raw_headers", raw)
}

pub(crate) fn missing_raw_headers(py: Python<'_>, response: &Bound<'_, PyAny>) -> PyResult<PyErr> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("name", "raw_headers")?;
    kwargs.set_item("obj", response)?;
    let message = format!(
        "'{}' object has no attribute 'raw_headers'",
        response.get_type().name()?
    );
    let error = py
        .get_type::<PyAttributeError>()
        .call((message,), Some(&kwargs))?;
    Ok(PyErr::from_value(error))
}
