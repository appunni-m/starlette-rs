//! Conversion of Python cookie attributes into Rust-owned response options.

use pyo3::exceptions::{PyAssertionError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyString};
use starlette_rs::{CookieOptions, ResponseError};

/// Converts Starlette cookie arguments at the PyO3 boundary.
///
/// CPython's `http.cookies` and `email.utils` are used only to convert the
/// Python-specific `expires` forms into the textual HTTP date that Rust stores
/// and serializes. Cookie decisions and header construction remain in Rust.
// LINT EXCEPTION: Keep each Starlette set_cookie option separate while converting Python expires values.
#[allow(clippy::too_many_arguments)]
pub(crate) fn options_from_python(
    py: Python<'_>,
    max_age: Option<Py<PyAny>>,
    expires: Option<Py<PyAny>>,
    path: Option<String>,
    domain: Option<String>,
    secure: bool,
    httponly: bool,
    samesite: Option<String>,
    partitioned: bool,
) -> PyResult<CookieOptions> {
    if let Some(value) = max_age.as_ref() {
        validate_python_attribute(py, "max-age", value.bind(py))?;
    }
    validate_partitioned_version(py, partitioned)?;

    Ok(CookieOptions {
        max_age: max_age
            .map(|value| value.bind(py).str()?.to_str().map(str::to_owned))
            .transpose()?,
        expires: expires
            .map(|value| expiration_text(py, value.bind(py)))
            .transpose()?,
        path,
        domain,
        secure,
        httponly,
        samesite,
        partitioned,
    })
}

fn validate_python_attribute(py: Python<'_>, name: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
    // CPython 3.12.13 validates an attribute when it is assigned to a
    // Morsel, before formatting it for output. Each str() call can run
    // arbitrary user code; conversion must preserve both boundaries.
    let text = value.str()?;
    if text
        .to_str()?
        .chars()
        .any(|character| character.is_ascii_control())
    {
        let message = format!(
            "Control characters are not allowed in cookies {} {}",
            PyString::new(py, name).repr()?,
            value.repr()?
        );
        let error = py
            .import("http.cookies")?
            .getattr("CookieError")?
            .call1((message,))?;
        return Err(PyErr::from_value(error));
    }
    Ok(())
}

/// Converts deletion attributes and Python's current-time expires value.
// LINT EXCEPTION: Keep each Starlette delete_cookie option separate while converting its expires value.
#[allow(clippy::too_many_arguments)]
pub(crate) fn delete_options_from_python(
    py: Python<'_>,
    path: Option<String>,
    domain: Option<String>,
    secure: bool,
    httponly: bool,
    samesite: Option<String>,
) -> PyResult<(String, CookieOptions)> {
    let expires = py
        .import("http.cookies")?
        .getattr("_getdate")?
        .call1((0,))?
        .extract::<String>()?;
    let options = CookieOptions {
        max_age: None,
        expires: Some(expires.clone()),
        path,
        domain,
        secure,
        httponly,
        samesite,
        partitioned: false,
    };
    Ok((expires, options))
}

/// Maps response errors to the exception class used by Starlette's cookie API.
pub(crate) fn response_error(error: ResponseError) -> PyErr {
    match error {
        ResponseError::InvalidSameSite => PyAssertionError::new_err(error.to_string()),
        _ => PyValueError::new_err(error.to_string()),
    }
}

fn validate_partitioned_version(py: Python<'_>, partitioned: bool) -> PyResult<()> {
    if partitioned {
        let version_info = py.import("sys")?.getattr("version_info")?;
        let major = version_info.get_item(0)?.extract::<u8>()?;
        let minor = version_info.get_item(1)?.extract::<u8>()?;
        if (major, minor) < (3, 14) {
            return Err(PyValueError::new_err(
                "Partitioned cookies are only supported in Python 3.14 and above.",
            ));
        }
    }
    Ok(())
}

fn expiration_text(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<String> {
    let datetime_type = py.import("datetime")?.getattr("datetime")?;
    if value.is_instance(&datetime_type)? {
        let function = py.import("email.utils")?.getattr("format_datetime")?;
        let kwargs = PyDict::new(py);
        kwargs.set_item("usegmt", true)?;
        return function.call((value,), Some(&kwargs))?.extract();
    }

    let integer_type = py.import("builtins")?.getattr("int")?;
    if value.is_instance(&integer_type)? {
        return py
            .import("http.cookies")?
            .getattr("_getdate")?
            .call1((value,))?
            .extract();
    }

    Ok(value.str()?.to_str()?.to_owned())
}
