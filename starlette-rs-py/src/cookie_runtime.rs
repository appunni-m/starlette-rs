//! Conversion of Python cookie attributes into Rust-owned response options.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use starlette_rs::CookieOptions;

/// Converts Starlette cookie arguments at the PyO3 boundary.
///
/// CPython's `http.cookies` and `email.utils` are used only to convert the
/// Python-specific `expires` forms into the textual HTTP date that Rust stores
/// and serializes. Cookie decisions and header construction remain in Rust.
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
