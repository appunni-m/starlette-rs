//! Rust-owned FileResponse range policy and multipart header construction.
//! Source: pinned Starlette responses.py, under the upstream BSD-3-Clause notice.

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyInt, PyList, PyString};

pub(crate) fn should_use_range(
    response: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    Ok(
        value.eq(response.getattr("headers")?.get_item("last-modified")?)?
            || value.eq(response.getattr("headers")?.get_item("etag")?)?,
    )
}

pub(crate) fn parse_ranges<'py>(
    py: Python<'py>,
    text: &Bound<'py, PyAny>,
    size: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyList>> {
    let ranges = PyList::empty(py);
    let int = py.import("builtins")?.getattr("int")?;
    for part in text.call_method1("split", (",",))?.try_iter()? {
        let part = part?.call_method0("strip")?;
        if !part.is_truthy()? || part.eq("-")? || !part.contains("-")? {
            continue;
        }
        let pair = part.call_method1("split", ("-", 1))?;
        let start_text = pair.get_item(0)?.call_method0("strip")?;
        let end_text = pair.get_item(1)?.call_method0("strip")?;
        let result = (|| -> PyResult<_> {
            let start = if start_text.is_truthy()? {
                int.call1((&start_text,))?
            } else {
                let suffix = int.call1((&end_text,))?;
                py.import("builtins")?
                    .getattr("max")?
                    .call1((size.call_method1("__sub__", (suffix,))?, 0))?
            };
            let end = if start_text.is_truthy()?
                && end_text.is_truthy()?
                && int.call1((&end_text,))?.lt(size)?
            {
                int.call1((&end_text,))?.call_method1("__add__", (1,))?
            } else {
                size.clone()
            };
            Ok((start, end))
        })();
        match result {
            Ok(range) => ranges.append(range)?,
            Err(error) if error.is_instance_of::<PyValueError>(py) => {}
            Err(error) => return Err(error),
        }
    }
    Ok(ranges)
}

pub(crate) fn parse_header(
    py: Python<'_>,
    class: &Bound<'_, PyAny>,
    header: &Bound<'_, PyAny>,
    size: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let parts = header.call_method1("split", ("=", 1))?;
    if parts.len()? != 2 {
        return Err(range_error(py, "MalformedRangeHeader", None)?);
    }
    let units = parts
        .get_item(0)?
        .call_method0("strip")?
        .call_method0("lower")?;
    if !units.eq("bytes")? {
        return Err(range_error(
            py,
            "MalformedRangeHeader",
            Some(PyString::new(py, "Only support bytes range").into_any()),
        )?);
    }
    let text = parts.get_item(1)?;
    let count = text
        .call_method1("count", (",",))?
        .call_method1("__add__", (1,))?;
    if count.gt(class.getattr("max_ranges")?)? {
        return Ok(PyList::empty(py).into_any().unbind());
    }
    let ranges = class.call_method1("_parse_ranges", (text, size))?;
    if ranges.len()? == 0 {
        return Err(range_error(
            py,
            "MalformedRangeHeader",
            Some(PyString::new(py, "Range header: range must be requested").into_any()),
        )?);
    }
    for range in ranges.try_iter()? {
        let (start, _) = unpack_range(py, &range?)?;
        // Match the source expression `0 <= start < file_size`, including
        // reflected comparison dispatch for values returned by an override.
        let valid_lower_bound = PyInt::new(py, 0)
            .as_any()
            .rich_compare(&start, CompareOp::Le)?
            .is_truthy()?;
        if !valid_lower_bound || !start.rich_compare(size, CompareOp::Lt)?.is_truthy()? {
            return Err(range_error(py, "RangeNotSatisfiable", Some(size.clone()))?);
        }
    }
    for range in ranges.try_iter()? {
        let (start, end) = unpack_range(py, &range?)?;
        if start.rich_compare(&end, CompareOp::Ge)?.is_truthy()? {
            return Err(range_error(
                py,
                "MalformedRangeHeader",
                Some(PyString::new(py, "Range header: start must be less than end").into_any()),
            )?);
        }
    }
    if ranges.len()? == 1 {
        return Ok(ranges.unbind());
    }
    ranges.call_method0("sort")?;
    let result = PyList::empty(py);
    result.append(ranges.get_item(0)?)?;
    for range in ranges.try_iter()?.skip(1) {
        let range = range?;
        let start = range.get_item(0)?;
        let end = range.get_item(1)?;
        let index = result.len() - 1;
        let last = result.get_item(index)?;
        if start.le(last.get_item(1)?)? {
            let merged_end = py
                .import("builtins")?
                .getattr("max")?
                .call1((last.get_item(1)?, end))?;
            result.set_item(index, (last.get_item(0)?, merged_end))?;
        } else {
            result.append((start, end))?;
        }
    }
    Ok(result.into_any().unbind())
}

pub(crate) fn unpack_range<'py>(
    py: Python<'py>,
    range: &Bound<'py, PyAny>,
) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyAny>)> {
    let range_type = range.get_type();
    let mut values = match range.try_iter() {
        Ok(values) => values,
        Err(error)
            if error.is_instance_of::<PyTypeError>(py)
                && !range_type.hasattr("__iter__")?
                && !range_type.hasattr("__getitem__")? =>
        {
            let type_name = range_type.name()?.to_string();
            return Err(PyTypeError::new_err(format!(
                "cannot unpack non-iterable {type_name} object"
            )));
        }
        Err(error) => return Err(error),
    };
    let start = match values.next() {
        Some(value) => value?,
        None => {
            return Err(PyValueError::new_err(
                "not enough values to unpack (expected 2, got 0)",
            ));
        }
    };
    let end = match values.next() {
        Some(value) => value?,
        None => {
            return Err(PyValueError::new_err(
                "not enough values to unpack (expected 2, got 1)",
            ));
        }
    };
    if let Some(extra) = values.next() {
        extra?;
        return Err(PyValueError::new_err(
            "too many values to unpack (expected 2)",
        ));
    }
    Ok((start, end))
}

fn range_error(py: Python<'_>, name: &str, value: Option<Bound<'_, PyAny>>) -> PyResult<PyErr> {
    let class = py.import("starlette.responses")?.getattr(name)?;
    let error = match value {
        Some(value) => class.call1((value,))?,
        None => class.call0()?,
    };
    Ok(PyErr::from_value(error))
}

pub(crate) fn multipart(
    py: Python<'_>,
    ranges: &Bound<'_, PyAny>,
    boundary: String,
    size: &Bound<'_, PyAny>,
    content_type: String,
) -> PyResult<Py<PyAny>> {
    let size = size.str()?.to_str()?.to_owned();
    let boundary_length = boundary.chars().count();
    let static_length = 49 + boundary_length + content_type.chars().count() + size.chars().count();
    let mut length = (4 + boundary_length).into_pyobject(py)?.into_any();
    for range in ranges.try_iter()? {
        let range = range?;
        let start = range.get_item(0)?;
        let end = range.get_item(1)?;
        let last = end.call_method1("__sub__", (1,))?;
        let headers_length = start.str()?.len()? + last.str()?.len()? + static_length;
        let part_length = end
            .call_method1("__sub__", (&start,))?
            .call_method1("__add__", (headers_length,))?;
        length = length.call_method1("__add__", (part_length,))?;
    }
    let generator = Py::new(
        py,
        MultipartHeader {
            boundary,
            size,
            content_type,
        },
    )?;
    Ok((length, generator).into_pyobject(py)?.into_any().unbind())
}

#[pyclass(frozen)]
struct MultipartHeader {
    boundary: String,
    size: String,
    content_type: String,
}

#[pymethods]
impl MultipartHeader {
    fn __call__(
        &self,
        py: Python<'_>,
        start: &Bound<'_, PyAny>,
        end: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let last = end.call_method1("__sub__", (1,))?;
        let text = format!(
            "--{}\r\nContent-Type: {}\r\nContent-Range: bytes {}-{}/{}\r\n\r\n",
            self.boundary,
            self.content_type,
            start.str()?,
            last.str()?,
            self.size
        );
        let bytes = PyString::new(py, &text).call_method1("encode", ("latin-1",))?;
        if !bytes.is_instance_of::<PyBytes>() {
            return Err(PyRuntimeError::new_err(
                "multipart encoding did not return bytes",
            ));
        }
        Ok(bytes.unbind())
    }
}
