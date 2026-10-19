//! Source-ordered construction over live Python response protocol values.

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAttributeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyString, PyTuple};

/// Apply Starlette's public `Response.__init__` assignments and virtual calls
/// in source order while keeping Python values and exceptions at the boundary.
pub(crate) fn initialize_response(
    _py: Python<'_>,
    response: &Bound<'_, PyAny>,
    arguments: &Bound<'_, PyTuple>,
) -> PyResult<()> {
    response.setattr("status_code", arguments.get_item(1)?)?;
    let media_type = arguments.get_item(3)?;
    if !media_type.is_none() {
        response.setattr("media_type", media_type)?;
    }
    response.setattr("background", arguments.get_item(4)?)?;

    // Starlette calls these methods through `self`; resolving each at the point
    // of use preserves subclass overrides and mutations made by render.
    let body = response
        .getattr("render")?
        .call1((arguments.get_item(0)?,))?;
    response.setattr("body", body)?;
    response
        .getattr("init_headers")?
        .call1((arguments.get_item(2)?,))?;
    Ok(())
}

/// Source-order initialization; descriptors and overrides remain user callables.
pub(crate) fn initialize_stream(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    arguments: &Bound<'_, PyTuple>,
) -> PyResult<()> {
    let content = arguments.get_item(0)?;
    let async_iterable = py.import("collections.abc")?.getattr("AsyncIterable")?;
    let iterator = if content.is_instance(&async_iterable)? {
        content
    } else {
        py.import("starlette.concurrency")?
            .call_method1("iterate_in_threadpool", (content,))?
    };
    response.setattr("body_iterator", iterator)?;
    response.setattr("status_code", arguments.get_item(1)?)?;
    let media_type = arguments.get_item(3)?;
    let media_type = if media_type.is_none() {
        response.getattr("media_type")?
    } else {
        media_type
    };
    response.setattr("media_type", media_type)?;
    response.setattr("background", arguments.get_item(4)?)?;
    response.call_method1("init_headers", (arguments.get_item(2)?,))?;
    Ok(())
}

/// Quote UTF-8 bytes in Rust after invoking the Python value's encoding protocol.
fn quote<'py>(
    py: Python<'py>,
    value: &Bound<'_, PyAny>,
    safe: &[u8],
) -> PyResult<Bound<'py, PyString>> {
    if value.is_instance_of::<PyString>() && !value.is_truthy()? {
        return Ok(value.cast::<PyString>()?.clone().unbind().into_bound(py));
    }
    let encoded = value.call_method1("encode", ("utf-8",))?;
    let bytes = encoded.cast::<PyBytes>()?.as_bytes();
    let mut output = String::with_capacity(bytes.len());
    for byte in bytes {
        if byte.is_ascii_alphanumeric() || b"-._~".contains(byte) || safe.contains(byte) {
            output.push(char::from(*byte));
        } else {
            use std::fmt::Write;
            // Writing to an owned String is infallible.
            let _ = write!(output, "%{byte:02X}");
        }
    }
    Ok(PyString::new(py, &output))
}

pub(crate) fn redirect_location(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    url: &Bound<'_, PyAny>,
) -> PyResult<()> {
    // The source selects the header view only after quote(str(url)) completes.
    let url = url.str()?;
    let location = quote(py, url.as_any(), b":/%#?=@[]!$&'()*+,;")?;
    response.getattr("headers")?.set_item("location", location)
}

pub(crate) fn initialize_file(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    arguments: &Bound<'_, PyTuple>,
) -> PyResult<()> {
    let path = arguments.get_item(0)?;
    response.setattr("path", &path)?;
    response.setattr("status_code", arguments.get_item(1)?)?;
    let filename = arguments.get_item(5)?;
    response.setattr("filename", &filename)?;
    let mut media_type = arguments.get_item(3)?;
    if media_type.is_none() {
        let guess_path = if filename.is_truthy()? {
            filename
        } else {
            path
        };
        media_type = py
            .import("mimetypes")?
            .call_method1("guess_type", (guess_path,))?
            .get_item(0)?;
        if !media_type.is_truthy()? {
            media_type = PyString::new(py, "application/octet-stream").into_any();
        }
    }
    response.setattr("media_type", media_type)?;
    response.setattr("background", arguments.get_item(4)?)?;
    response.call_method1("init_headers", (arguments.get_item(2)?,))?;
    response
        .getattr("headers")?
        .call_method1("setdefault", ("accept-ranges", "bytes"))?;
    if !response.getattr("filename")?.is_none() {
        let filename = response.getattr("filename")?;
        let quoted = quote(py, &filename, b"/")?;
        let disposition = if !quoted.as_any().eq(response.getattr("filename")?)? {
            PyString::new(py, "{0}; filename*=utf-8''{1}")
                .call_method1("format", (arguments.get_item(7)?, quoted))?
        } else {
            PyString::new(py, "{0}; filename=\"{1}\"").call_method1(
                "format",
                (arguments.get_item(7)?, response.getattr("filename")?),
            )?
        };
        response
            .getattr("headers")?
            .call_method1("setdefault", ("content-disposition", disposition))?;
    }
    let stat_result = arguments.get_item(6)?;
    response.setattr("stat_result", &stat_result)?;
    if !stat_result.is_none() {
        response.call_method1("set_stat_headers", (stat_result,))?;
    }
    Ok(())
}

pub(crate) fn set_stat_headers(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    stat: &Bound<'_, PyAny>,
) -> PyResult<()> {
    let length = stat.getattr("st_size")?.str()?;
    let kwargs = pyo3::types::PyDict::new(py);
    kwargs.set_item("usegmt", true)?;
    let modified = py
        .import("email.utils")?
        .getattr("formatdate")?
        .call((stat.getattr("st_mtime")?,), Some(&kwargs))?;
    let operator = py.import("operator")?;
    let etag_base = operator.call_method1("add", (stat.getattr("st_mtime")?.str()?, "-"))?;
    let etag_base = operator.call_method1("add", (etag_base, stat.getattr("st_size")?.str()?))?;
    let encoded = etag_base.call_method0("encode")?;
    let etag = starlette_rs::FileResponse::stat_etag(encoded.cast::<PyBytes>()?.as_bytes());
    let etag = PyString::new(py, &etag).into_any();
    for (name, value) in [
        ("content-length", length.into_any()),
        ("last-modified", modified),
        ("etag", etag),
    ] {
        response
            .getattr("headers")?
            .call_method1("setdefault", (name, value))?;
    }
    Ok(())
}

pub(crate) fn initialize_headers(
    py: Python<'_>,
    response: &Bound<'_, PyAny>,
    headers: Option<&Bound<'_, PyAny>>,
) -> PyResult<()> {
    let raw = PyList::empty(py);
    let keys = PyList::empty(py);
    if let Some(headers) = headers {
        for pair in headers.call_method0("items")?.try_iter()? {
            let pair = pair?;
            // Starlette's tuple unpacking accepts any two-item iterable and
            // raises Python's ValueError after observing exhaustion or a third item.
            let mut pair_items = pair.try_iter()?;
            let name = match pair_items.next() {
                Some(name) => name?,
                None => {
                    return Err(PyValueError::new_err(
                        "not enough values to unpack (expected 2, got 0)",
                    ));
                }
            };
            let value = match pair_items.next() {
                Some(value) => value?,
                None => {
                    return Err(PyValueError::new_err(
                        "not enough values to unpack (expected 2, got 1)",
                    ));
                }
            };
            if let Some(extra) = pair_items.next() {
                extra?;
                // CPython 3.14 reports the full length for exact built-in
                // sequences and dictionaries; arbitrary iterators still only
                // reveal that at least one extra value exists.
                let exact_length = if pair.is_exact_instance_of::<PyList>()
                    || pair.is_exact_instance_of::<PyTuple>()
                    || pair.is_exact_instance_of::<PyDict>()
                {
                    Some(pair.len()?)
                } else {
                    None
                };
                let message = match (py.version_info() >= (3, 14), exact_length) {
                    (true, Some(length)) => {
                        format!("too many values to unpack (expected 2, got {length})")
                    }
                    _ => "too many values to unpack (expected 2)".to_owned(),
                };
                return Err(PyValueError::new_err(message));
            }
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
