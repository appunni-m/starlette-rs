//! Conversion of Python cookie attributes into Rust-owned response options.

use pyo3::exceptions::{PyAssertionError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt, PyList, PyString, PyTuple};
use starlette_rs::ResponseError;

use crate::datastructure_runtime::{codepoints_to_python_string, python_string_to_codepoints};

/// Keeps cookie-owned Python values alive until the public header append finishes.
pub(crate) struct CookieHeader<'py> {
    pub(crate) text: Bound<'py, PyString>,
    // SimpleCookie retains its Morsel, including converted values, until the
    // set_cookie frame returns. Their finalizers may observe or reenter the response.
    _retained: Vec<Bound<'py, PyAny>>,
}

fn retain(retained: Option<&Bound<'_, PyList>>, value: &Bound<'_, PyAny>) -> PyResult<()> {
    if let Some(retained) = retained {
        retained.append(value)?;
    }
    Ok(())
}

/// Builds a Python cookie header while retaining original argument protocols.
/// No response borrow is held across user conversion or comparison callbacks.
pub(crate) fn header_from_arguments<'py>(
    py: Python<'py>,
    args: &Bound<'py, PyTuple>,
    retained: Option<&Bound<'py, PyList>>,
) -> PyResult<CookieHeader<'py>> {
    let supplied = args.get_item(1)?;
    if supplied.is_instance(&py.import("http.cookies")?.getattr("Morsel")?)? {
        return header_from_morsel(py, args, supplied, retained);
    }
    let key = args.get_item(0)?;
    let value = args.get_item(1)?.str()?;
    retain(retained, value.as_any())?;
    let coded = quote_value(py, &value)?;
    retain(retained, &coded)?;
    // Source SimpleCookie first looks up the original key, then validates it.
    let storage = PyDict::new(py);
    let _ = storage.get_item(&key)?;
    // Morsel.set evaluates key.lower() before resolving its _reserved attribute.
    // A Python key override can rebind that class attribute during lower().
    let lowered_key = key.call_method0("lower")?;
    let reserved = py
        .import("http.cookies")?
        .getattr("Morsel")?
        .getattr("_reserved")?;
    if reserved.contains(&lowered_key)? {
        return Err(cookie_error(
            py,
            format!("Attempt to set a reserved key {}", key.repr()?),
        )?);
    }
    let legal_key = py
        .import("http.cookies")?
        .getattr("_is_legal_key")?
        .call1((&key,))?;
    if !legal_key.is_truthy()? {
        return Err(cookie_error(py, format!("Illegal key {}", key.repr()?))?);
    }
    // Starlette quotes the value before Morsel.set checks both the raw and
    // quoted forms, and it does so before processing any optional attributes.
    validate_morsel_cookie_values(py, &key, value.as_any(), &coded)?;
    // SimpleCookie quotes control characters in cookie values through
    // `_Translator`. Keep the original value and its translated representation
    // observable while key and attribute validation remain separate.
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
                    retain(retained, &attribute)?;
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
    // Maintenance releases can backport the stdlib check within a Python
    // minor line. Use its helper as the capability marker instead of assuming
    // that the behavior is tied to a minor version.
    if cookie_control_checks_enabled(py)? && has_control(&output) {
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

fn header_from_morsel<'py>(
    py: Python<'py>,
    args: &Bound<'py, PyTuple>,
    morsel: Bound<'py, PyAny>,
    retained: Option<&Bound<'py, PyList>>,
) -> PyResult<CookieHeader<'py>> {
    // A supplied Morsel is mutable user representation. Source SimpleCookie
    // stores that exact object without validating/replacing its key or value.
    // Mutations invoke that object's mapping protocol; Rust owns their order,
    // option selection and final cookie formatting, never OutputString/output.
    retain(retained, &morsel)?;
    let key = args.get_item(0)?;
    let storage = PyDict::new(py);
    storage.set_item(&key, &morsel)?;
    for (index, name) in [(2, "max-age"), (3, "expires"), (4, "path"), (5, "domain")] {
        let mut value = args.get_item(index)?;
        if !value.is_none() {
            if name == "expires"
                && value.is_instance(&py.import("datetime")?.getattr("datetime")?)?
            {
                let kwargs = PyDict::new(py);
                kwargs.set_item("usegmt", true)?;
                value = py
                    .import("email.utils")?
                    .getattr("format_datetime")?
                    .call((value,), Some(&kwargs))?;
                retain(retained, &value)?;
            }
            storage.as_any().get_item(&key)?.set_item(name, value)?;
        }
    }
    for (index, name) in [(6, "secure"), (7, "httponly")] {
        if args.get_item(index)?.is_truthy()? {
            storage.as_any().get_item(&key)?.set_item(name, true)?;
        }
    }
    let samesite = args.get_item(8)?;
    if !samesite.is_none() {
        if !PyList::new(py, ["strict", "lax", "none"])?.contains(samesite.call_method0("lower")?)? {
            return Err(PyAssertionError::new_err(
                "samesite must be either 'strict', 'lax' or 'none'",
            ));
        }
        storage
            .as_any()
            .get_item(&key)?
            .set_item("samesite", samesite)?;
    }
    if args.get_item(9)?.is_truthy()? {
        validate_partitioned_version(py, true)?;
        storage
            .as_any()
            .get_item(&key)?
            .set_item("partitioned", true)?;
    }
    let public_key = morsel.getattr("key")?;
    let coded = morsel.getattr("coded_value")?;
    let mut output = format_pair(py, &public_key, &coded)?;
    let items = morsel.call_method0("items")?;
    let mut attributes = Vec::new();
    for item in items.try_iter()? {
        let item = item?;
        attributes.push((item.get_item(0)?.extract::<String>()?, item.get_item(1)?));
    }
    attributes.sort_by(|left, right| left.0.cmp(&right.0));
    let labels = morsel.getattr("_reserved")?;
    let flags = morsel.getattr("_flags")?;
    for (name, value) in &attributes {
        if value.eq("")? || !labels.contains(name)? {
            continue;
        }
        let label = labels.get_item(name)?;
        let formatted = if name == "expires" && value.is_instance_of::<PyInt>() {
            py.import("http.cookies")?
                .getattr("_getdate")?
                .call1((value,))?
        } else if name == "max-age" && value.is_instance_of::<PyInt>() {
            PyString::new(py, "%d").call_method1("__mod__", (value,))?
        } else if name == "comment" && value.is_instance_of::<PyString>() {
            quote_value(py, value.cast::<PyString>()?)?
        } else if flags.contains(name)? {
            if value.is_truthy()? {
                output.extend([u32::from(';'), u32::from(' ')]);
                output.extend(python_string_to_codepoints(label.str()?.as_any())?);
            }
            continue;
        } else {
            value.clone()
        };
        output.extend([u32::from(';'), u32::from(' ')]);
        output.extend(format_pair(py, &label, &formatted)?);
    }
    // BaseCookie.output checks completed Morsel output, including attributes
    // inserted through lower-level mutation paths that bypass __setitem__.
    if cookie_control_checks_enabled(py)? && has_control(&output) {
        return Err(cookie_error(
            py,
            "Control characters are not allowed in cookies".to_owned(),
        )?);
    }
    // SimpleCookie.output(header="") strips the completed header.
    let text = codepoints_to_python_string(py, &output)?
        .call_method0("strip")?
        .cast::<PyString>()?
        .clone();
    Ok(CookieHeader {
        text,
        _retained: vec![morsel, public_key, coded, items],
    })
}

fn format_pair(
    py: Python<'_>,
    key: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<Vec<u32>> {
    // A literal Python `%` expression invokes subclass __str__ differently
    // from calling str.__mod__ directly. The facade helper supplies only that
    // representation conversion; Rust still selects and assembles cookie fields.
    let text = py
        .import("starlette.responses")?
        .getattr("_format_cookie_pair")?
        .call1((key, value))?;
    python_string_to_codepoints(&text)
}

fn python_whitespace(point: u32) -> bool {
    char::from_u32(point)
        .is_some_and(|character| character.is_whitespace() || matches!(point, 0x1c..=0x1f))
}

fn has_control(text: &[u32]) -> bool {
    text.iter().any(|point| matches!(point, 0..=31 | 127))
}

fn cookie_control_checks_enabled(py: Python<'_>) -> PyResult<bool> {
    // CPython has backported the http.cookies control checks to maintenance
    // releases. The helper's presence identifies the behavior of this runtime
    // more accurately than a Python minor-version comparison.
    py.import("http.cookies")?.hasattr("_has_control_character")
}

fn legal_token(text: &[u32]) -> bool {
    !text.is_empty()
        && text.iter().all(|point| {
            char::from_u32(*point).is_some_and(|character| {
                character.is_ascii_alphanumeric() || "!#$%&'*+-.^_`|~:".contains(character)
            })
        })
}

fn cookie_error(py: Python<'_>, message: String) -> PyResult<PyErr> {
    Ok(PyErr::from_value(
        py.import("http.cookies")?
            .getattr("CookieError")?
            .call1((message,))?,
    ))
}

fn validate_morsel_cookie_values(
    py: Python<'_>,
    key: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
    coded_value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    // Morsel.set invokes this check in runtimes that expose the stdlib helper.
    // Keep its ordered str() conversions because subclasses can observe them.
    if !cookie_control_checks_enabled(py)? {
        return Ok(());
    }
    for candidate in [key, value, coded_value] {
        let rendered = candidate.str()?.into_any();
        // Rust owns the predicate without relying on a private stdlib regex
        // that is absent in supported CPython versions.
        if has_control(&python_string_to_codepoints(rendered.as_any())?) {
            let arguments = PyTuple::new(py, [key.clone(), value.clone(), coded_value.clone()])?;
            let message =
                PyString::new(py, "Control characters are not allowed in cookies %r %r %r")
                    .call_method1("__mod__", (arguments,))?;
            let error = py
                .import("http.cookies")?
                .getattr("CookieError")?
                .call1((message,))?;
            return Err(PyErr::from_value(error));
        }
    }
    Ok(())
}

fn quote_value<'py>(py: Python<'py>, value: &Bound<'py, PyString>) -> PyResult<Bound<'py, PyAny>> {
    // CPython's `_quote` runs `_is_legal_key` even though Rust selects whether
    // quoting is needed. Preserve callbacks when `str(value)` returned a
    // Python string subclass.
    py.import("http.cookies")?
        .getattr("_is_legal_key")?
        .call1((value,))?;
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

fn validate_python_attribute(py: Python<'_>, name: &str, value: &Bound<'_, PyAny>) -> PyResult<()> {
    // Morsel validates attributes at assignment when this stdlib capability is
    // present. This happens before formatting and can invoke user __str__.
    if !cookie_control_checks_enabled(py)? {
        return Ok(());
    }
    let controls = {
        let text = value.str()?;
        // Keep Python's conversion callback while Rust owns the predicate; the
        // stdlib's private regex is not present across supported Python minors.
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
