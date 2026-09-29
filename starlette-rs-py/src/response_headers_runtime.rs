//! Construction and in-place refresh of response header views.

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};

pub(crate) fn view(py: Python<'_>, raw_headers: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let kwargs = PyDict::new(py);
    kwargs.set_item("raw", raw_headers)?;
    py.import("starlette.datastructures")?
        .getattr("MutableHeaders")?
        .call((), Some(&kwargs))
        .map(Bound::unbind)
}

pub(crate) fn items(headers: &[(Vec<u8>, Vec<u8>)]) -> Vec<(String, String)> {
    headers
        .iter()
        .map(|(name, value)| (decode_latin1(name), decode_latin1(value)))
        .collect()
}

pub(crate) fn raw_pairs(py: Python<'_>, headers: &[(Vec<u8>, Vec<u8>)]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for (name, value) in headers {
        output.append(PyTuple::new(
            py,
            [PyBytes::new(py, name), PyBytes::new(py, value)],
        )?)?;
    }
    Ok(output.into_any().unbind())
}

pub(crate) fn refresh_raw_pairs(
    py: Python<'_>,
    raw: &Bound<'_, PyAny>,
    headers: &[(Vec<u8>, Vec<u8>)],
) -> PyResult<()> {
    let raw_len = raw.len()?;
    for (index, pair) in headers.iter().enumerate() {
        let replacement = raw_pair(py, pair)?;
        if index < raw_len {
            let current = raw.get_item(index)?.extract::<(Vec<u8>, Vec<u8>)>()?;
            if current != *pair {
                raw.set_item(index, replacement)?;
            }
        } else {
            raw.call_method1("append", (replacement,))?;
        }
    }
    for index in (headers.len()..raw_len).rev() {
        raw.call_method1("__delitem__", (index,))?;
    }
    Ok(())
}

pub(crate) fn parse_raw_pairs(raw: &Bound<'_, PyAny>) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
    raw.try_iter()?
        .map(|pair| pair?.extract::<(Vec<u8>, Vec<u8>)>())
        .collect()
}

fn decode_latin1(value: &[u8]) -> String {
    value.iter().copied().map(char::from).collect()
}

fn raw_pair<'py>(py: Python<'py>, pair: &(Vec<u8>, Vec<u8>)) -> PyResult<Bound<'py, PyTuple>> {
    PyTuple::new(py, [PyBytes::new(py, &pair.0), PyBytes::new(py, &pair.1)])
}
