//! Conversion of Python cookie attributes into Rust-owned response options.

use pyo3::exceptions::{PyAssertionError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyInt, PyList, PyMemoryView, PyString, PyTuple};
use starlette_rs::{CookieOptions, ResponseError};

use crate::datastructure_runtime::{codepoints_to_python_string, python_string_to_codepoints};

/// Keeps cookie-owned Python values alive until the public header append finishes.
pub(crate) struct CookieHeader<'py> {
    pub(crate) text: Bound<'py, PyString>,
    // SimpleCookie retains its Morsel, including converted values, until the
    // set_cookie frame returns. Their finalizers may observe or reenter the response.
    _retained: Vec<Bound<'py, PyAny>>,
}

/// Rust cookie state held by the forwarding frame, including on Python errors.
#[pyclass(name = "_ResponseCookieCall")]
pub(crate) struct PyCookieCall {
    arguments: Py<PyTuple>,
    retained: Vec<Py<PyAny>>,
}

impl PyCookieCall {
    pub(crate) fn new(arguments: &Bound<'_, PyTuple>) -> Self {
        Self {
            arguments: arguments.clone().unbind(),
            retained: Vec::new(),
        }
    }
}

#[pymethods]
impl PyCookieCall {
    fn apply(slf: Py<Self>, py: Python<'_>, response: &Bound<'_, PyAny>) -> PyResult<()> {
        let arguments = slf.borrow(py).arguments.clone_ref(py);
        let header = header_from_arguments(py, arguments.bind(py), Some(&slf))?;
        let append = response.getattr("raw_headers")?.getattr("append")?;
        let encoded = header.text.call_method1("encode", ("latin-1",))?;
        append.call1((PyTuple::new(
            py,
            [PyBytes::new(py, b"set-cookie").into_any(), encoded],
        )?,))?;
        Ok(())
    }

    fn __traverse__(
        &self,
        visit: pyo3::class::gc::PyVisit<'_>,
    ) -> Result<(), pyo3::class::gc::PyTraverseError> {
        visit.call(&self.arguments)?;
        for retained in &self.retained {
            visit.call(retained)?;
        }
        Ok(())
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.arguments = PyTuple::empty(py).unbind();
        self.retained.clear();
    }
}

fn retain(py: Python<'_>, owner: Option<&Py<PyCookieCall>>, value: &Bound<'_, PyAny>) {
    if let Some(owner) = owner {
        // Adding a reference cannot invoke a user finalizer. Release this native
        // borrow before the next conversion, comparison, attribute access or append.
        owner.borrow_mut(py).retained.push(value.clone().unbind());
    }
}

/// Builds a Python cookie header while retaining original argument protocols.
/// No response borrow is held across user conversion or comparison callbacks.
pub(crate) fn header_from_arguments<'py>(
    py: Python<'py>,
    args: &Bound<'py, PyTuple>,
    owner: Option<&Py<PyCookieCall>>,
) -> PyResult<CookieHeader<'py>> {
    let key = args.get_item(0)?;
    let value = args.get_item(1)?.str()?;
    retain(py, owner, value.as_any());
    let coded = quote_value(py, &value)?;
    retain(py, owner, &coded);
    // Source SimpleCookie first looks up the original key, then validates it.
    let storage = PyDict::new(py);
    let _ = storage.get_item(&key)?;
    let reserved = PyDict::new(py);
    for name in [
        "expires", "path", "comment", "domain", "max-age", "secure", "httponly", "version",
        "samesite",
    ] {
        reserved.set_item(name, true)?;
    }
    if reserved.contains(key.call_method0("lower")?)? {
        return Err(cookie_error(
            py,
            format!("Attempt to set a reserved key {}", key.repr()?),
        )?);
    }
    if !legal_token(&string_codepoints(&key)?) {
        return Err(cookie_error(py, format!("Illegal key {}", key.repr()?))?);
    }
    for item in [&key, value.as_any(), &coded] {
        if has_control(&python_string_to_codepoints(item.str()?.as_any())?) {
            return Err(cookie_error(
                py,
                format!(
                    "Control characters are not allowed in cookies {} {} {}",
                    key.repr()?,
                    value.repr()?,
                    coded.repr()?
                ),
            )?);
        }
    }
    storage.set_item(&key, py.None())?;

    let mut attributes = Vec::new();
    for (index, name) in [(2, "max-age"), (3, "expires"), (4, "path"), (5, "domain")] {
        let mut attribute = args.get_item(index)?;
        if !attribute.is_none() {
            if name == "expires" {
                let datetime_type = py.import("datetime")?.getattr("datetime")?;
                if attribute.is_instance(&datetime_type)? {
                    let kwargs = PyDict::new(py);
                    kwargs.set_item("usegmt", true)?;
                    attribute = py
                        .import("email.utils")?
                        .getattr("format_datetime")?
                        .call((attribute,), Some(&kwargs))?;
                    retain(py, owner, &attribute);
                }
            }
            let _ = storage.as_any().get_item(&key)?;
            validate_python_attribute(py, name, &attribute)?;
            attributes.push((name, attribute));
        }
    }
    for (index, name) in [(6, "secure"), (7, "httponly")] {
        if args.get_item(index)?.is_truthy()? {
            let _ = storage.as_any().get_item(&key)?;
            attributes.push((name, true.into_pyobject(py)?.to_owned().into_any()));
        }
    }
    let samesite = args.get_item(8)?;
    if !samesite.is_none() {
        if !PyList::new(py, ["strict", "lax", "none"])?.contains(samesite.call_method0("lower")?)? {
            return Err(PyAssertionError::new_err(
                "samesite must be either 'strict', 'lax' or 'none'",
            ));
        }
        let _ = storage.as_any().get_item(&key)?;
        validate_python_attribute(py, "samesite", &samesite)?;
        attributes.push(("samesite", samesite));
    }
    if args.get_item(9)?.is_truthy()? {
        validate_partitioned_version(py, true)?;
        let _ = storage.as_any().get_item(&key)?;
        attributes.push(("partitioned", true.into_pyobject(py)?.to_owned().into_any()));
    }
    // Formatting is deliberately deferred until every source assignment and
    // its callback completed. Equality with an empty string can also run user code.
    attributes.sort_by_key(|(name, _)| *name);
    let mut output = format_pair(py, &key, &coded)?;
    for (name, attribute) in &attributes {
        if attribute.eq("")? {
            continue;
        }
        let label = match *name {
            "domain" => "Domain",
            "httponly" => "HttpOnly",
            "max-age" => "Max-Age",
            "partitioned" => "Partitioned",
            "path" => "Path",
            "samesite" => "SameSite",
            "secure" => "Secure",
            _ => "expires",
        };
        if matches!(*name, "secure" | "httponly" | "partitioned") {
            output.extend(format!("; {label}").chars().map(u32::from));
        } else {
            let text = if *name == "expires" && attribute.is_instance_of::<PyInt>() {
                py.import("http.cookies")?
                    .getattr("_getdate")?
                    .call1((attribute,))?
            } else if *name == "max-age" && attribute.is_instance_of::<PyInt>() {
                PyString::new(py, "%d").call_method1("__mod__", (attribute,))?
            } else {
                attribute.clone()
            };
            output.extend([u32::from(';'), u32::from(' ')]);
            output.extend(format_pair(py, PyString::new(py, label).as_any(), &text)?);
        }
    }
    if has_control(&output) {
        return Err(cookie_error(
            py,
            "Control characters are not allowed in cookies".to_owned(),
        )?);
    }
    let start = output.iter().position(|point| !python_whitespace(*point));
    let end = output.iter().rposition(|point| !python_whitespace(*point));
    let trimmed = match (start, end) {
        (Some(start), Some(end)) => &output[start..=end],
        _ => &[],
    };
    let text = codepoints_to_python_string(py, trimmed)?;
    let mut retained = vec![key, value.into_any(), coded];
    retained.extend(attributes.into_iter().map(|(_, attribute)| attribute));
    Ok(CookieHeader {
        text,
        _retained: retained,
    })
}

fn format_pair(
    py: Python<'_>,
    key: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<Vec<u32>> {
    // CPython compiles the source's literal %s pairs as FORMAT_VALUE with str
    // conversion, followed by Python's format protocol. A string subclass can
    // run __str__ again there. Preserve that representation boundary directly.
    let text = PyString::new(py, "{0!s}={1!s}").call_method1("format", (key, value))?;
    python_string_to_codepoints(&text)
}

fn python_whitespace(point: u32) -> bool {
    char::from_u32(point)
        .is_some_and(|character| character.is_whitespace() || matches!(point, 0x1c..=0x1f))
}

fn has_control(text: &[u32]) -> bool {
    text.iter().any(|point| matches!(point, 0..=31 | 127))
}

fn legal_token(text: &[u32]) -> bool {
    !text.is_empty()
        && text.iter().all(|point| {
            char::from_u32(*point).is_some_and(|character| {
                character.is_ascii_alphanumeric() || "!#$%&'*+-.^_`|~:".contains(character)
            })
        })
}

fn string_codepoints(value: &Bound<'_, PyAny>) -> PyResult<Vec<u32>> {
    if value.is_instance_of::<PyString>() {
        return python_string_to_codepoints(value);
    }
    if value.is_instance_of::<PyBytes>()
        || value.is_instance_of::<PyByteArray>()
        || value.is_instance_of::<PyMemoryView>()
    {
        return Err(PyTypeError::new_err(
            "cannot use a string pattern on a bytes-like object",
        ));
    }
    Err(PyTypeError::new_err(format!(
        "expected string or bytes-like object, got '{}'",
        value.get_type().name()?
    )))
}

fn cookie_error(py: Python<'_>, message: String) -> PyResult<PyErr> {
    Ok(PyErr::from_value(
        py.import("http.cookies")?
            .getattr("CookieError")?
            .call1((message,))?,
    ))
}

fn quote_value<'py>(py: Python<'py>, value: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    if legal_token(&python_string_to_codepoints(value.as_any())?) {
        return Ok(value.clone().into_any());
    }
    // translate() is a Python representation boundary. Its shared interpreter
    // dictionary is observable through user callbacks and must also alias the
    // standard library's cookie translation table. Rust still selects quoting
    // and builds the cookie; no SimpleCookie/Morsel algorithm is invoked here.
    let translations = py.import("http.cookies")?.getattr("_Translator")?;
    let translated = value.call_method1("translate", (translations,))?;
    let operator = py.import("operator")?;
    let prefix = operator.call_method1("add", ("\"", translated))?;
    operator.call_method1("add", (prefix, "\""))
}

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
    let controls = {
        let text = value.str()?;
        has_control(&python_string_to_codepoints(text.as_any())?)
    };
    if controls {
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
