//! Rust-owned URL and connection-state semantics for the Python compatibility API.
//!
//! `urllib.parse` remains the parser/formatter because Starlette exposes its
//! `SplitResult` behavior verbatim. Rust owns URL construction decisions,
//! component caching, replacement, password redaction, and State mapping/error
//! policy. The public `URLPath` subclass remains Python because its value must
//! actually be a `str` subclass.

use pyo3::exceptions::{PyAssertionError, PyAttributeError, PyKeyError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule, PyString, PyTuple};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(url_init, module)?)?;
    module.add_function(wrap_pyfunction!(url_components, module)?)?;
    module.add_function(wrap_pyfunction!(url_replace, module)?)?;
    module.add_function(wrap_pyfunction!(url_repr, module)?)?;
    module.add_function(wrap_pyfunction!(url_is_secure, module)?)?;
    module.add_function(wrap_pyfunction!(url_eq, module)?)?;
    module.add_function(wrap_pyfunction!(urlpath_validate, module)?)?;
    module.add_function(wrap_pyfunction!(urlpath_make_absolute_url, module)?)?;
    module.add_function(wrap_pyfunction!(state_new, module)?)?;
    module.add_function(wrap_pyfunction!(state_getattr, module)?)?;
    module.add_function(wrap_pyfunction!(state_set, module)?)?;
    module.add_function(wrap_pyfunction!(state_get, module)?)?;
    module.add_function(wrap_pyfunction!(state_delete, module)?)?;
    module.add_function(wrap_pyfunction!(state_iter, module)?)?;
    module.add_function(wrap_pyfunction!(state_len, module)?)?;
    Ok(())
}

#[pyfunction(name = "_url_init")]
fn url_init(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    scope: &Bound<'_, PyAny>,
    components: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    if !scope.is_none() {
        if url.is_truthy()? {
            return Err(PyAssertionError::new_err(
                "Cannot set both \"url\" and \"scope\".",
            ));
        }
        if components.len() != 0 {
            return Err(PyAssertionError::new_err(
                "Cannot set both \"scope\" and \"**components\".",
            ));
        }

        let get = scope.getattr("get")?;
        let scheme = get.call1(("scheme", "http"))?;
        let path = scope.get_item("path")?;
        let query_string = get.call1(("query_string", b""))?;
        let headers = scope.get_item("headers")?;
        let server = get.call1(("server", py.None()))?;
        let server = if server.is_none() {
            py.None()
        } else {
            let host = server.get_item(0)?;
            let port = server.get_item(1)?;
            PyTuple::new(py, [host, port])?.into_any().unbind()
        };
        let core = py.import("starlette_rs_py._core")?;
        return core
            .getattr("_connection_url")?
            .call1((scheme, path, query_string, headers, server))
            .map(Bound::unbind);
    }

    if components.len() != 0 {
        if url.is_truthy()? {
            return Err(PyAssertionError::new_err(
                "Cannot set both \"url\" and \"**components\".",
            ));
        }
        let empty = PyString::new(py, "");
        let split = url_split(py, &empty)?;
        let replaced = replace_split(py, &split, components)?;
        return replaced.call_method0("geturl").map(Bound::unbind);
    }

    Ok(url.clone().unbind())
}

#[pyfunction(name = "_url_components")]
fn url_components(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    cached: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    if cached.is_none() {
        return url_split(py, url).map(Bound::unbind);
    }
    Ok(cached.clone().unbind())
}

#[pyfunction(name = "_url_replace")]
fn url_replace(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    split: &Bound<'_, PyAny>,
    components: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let split = if split.is_none() {
        url_split(py, url)?
    } else {
        split.clone()
    };
    replace_split(py, &split, components)
        .and_then(|result| result.call_method0("geturl").map(Bound::unbind))
}

fn replace_split<'py>(
    py: Python<'py>,
    split: &Bound<'py, PyAny>,
    components: &Bound<'py, PyDict>,
) -> PyResult<Bound<'py, PyAny>> {
    let kwargs = components.copy()?.cast_into::<PyDict>()?;
    let uses_authority_fields = ["username", "password", "hostname", "port"]
        .iter()
        .try_fold(false, |found, key| -> PyResult<bool> {
            Ok(found || kwargs.contains(*key)?)
        })?;

    if uses_authority_fields {
        let hostname = kwargs.call_method1("pop", ("hostname", py.None()))?;
        let port = kwargs.call_method1("pop", ("port", split.getattr("port")?))?;
        let username = kwargs.call_method1("pop", ("username", split.getattr("username")?))?;
        let password = kwargs.call_method1("pop", ("password", split.getattr("password")?))?;

        let hostname = if hostname.is_none() {
            let netloc = split.getattr("netloc")?;
            let parts = netloc.call_method1("rpartition", ("@",))?;
            let hostname = parts.get_item(2)?;
            let nonempty = hostname.is_truthy()?;
            if nonempty && !hostname.get_item(-1)?.eq("]")? {
                hostname.call_method1("rsplit", (":", 1))?.get_item(0)?
            } else {
                hostname
            }
        } else {
            hostname
        };

        let mut netloc = hostname;
        if !port.is_none() {
            let port_text = py
                .import("builtins")?
                .getattr("format")?
                .call1((port, ""))?;
            let suffix = PyString::new(py, ":").call_method1("__add__", (port_text,))?;
            netloc = netloc.call_method1("__add__", (suffix,))?;
        }
        if !username.is_none() {
            let mut userpass = username;
            if !password.is_none() {
                let password_text = py
                    .import("builtins")?
                    .getattr("format")?
                    .call1((password, ""))?;
                let suffix = PyString::new(py, ":").call_method1("__add__", (password_text,))?;
                userpass = userpass.call_method1("__add__", (suffix,))?;
            }
            let prefix = userpass.call_method1("__add__", ("@",))?;
            netloc = prefix.call_method1("__add__", (netloc,))?;
        }
        kwargs.set_item("netloc", netloc)?;
    }

    split.call_method("_replace", (), Some(&kwargs))
}

fn url_split<'py>(py: Python<'py>, url: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    py.import("urllib.parse")?
        .getattr("urlsplit")?
        .call1((url,))
}

#[pyfunction(name = "_url_repr")]
fn url_repr(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    cached: &Bound<'_, PyAny>,
    class_name: &str,
) -> PyResult<(String, Py<PyAny>)> {
    let components = if cached.is_none() {
        url_split(py, url)?
    } else {
        cached.clone()
    };
    let password = components.getattr("password")?;
    let value = if password.is_truthy()? {
        let replacement = PyDict::new(py);
        replacement.set_item("password", "********")?;
        let redacted = components
            .call_method("_replace", (), Some(&replacement))?
            .call_method0("geturl")?;
        py.import("builtins")?.getattr("str")?.call1((redacted,))?
    } else {
        py.import("builtins")?.getattr("str")?.call1((url,))?
    };
    let value_repr = py.import("builtins")?.getattr("repr")?.call1((value,))?;
    Ok((
        format!("{class_name}({})", value_repr.extract::<String>()?),
        components.unbind(),
    ))
}

#[pyfunction(name = "_url_is_secure")]
fn url_is_secure(components: &Bound<'_, PyAny>) -> PyResult<bool> {
    let scheme = components.getattr("scheme")?;
    Ok(scheme.eq("https")? || scheme.eq("wss")?)
}

#[pyfunction(name = "_url_eq")]
fn url_eq(py: Python<'_>, left: &Bound<'_, PyAny>, right: &Bound<'_, PyAny>) -> PyResult<bool> {
    let stringify = py.import("builtins")?.getattr("str")?;
    stringify.call1((left,))?.eq(stringify.call1((right,))?)
}

#[pyfunction(name = "_urlpath_validate")]
fn urlpath_validate(py: Python<'_>, protocol: &Bound<'_, PyAny>) -> PyResult<()> {
    let valid_protocols = PyTuple::new(py, ["http", "websocket", ""])?;
    if !valid_protocols.contains(protocol)? {
        return Err(PyAssertionError::new_err(""));
    }
    Ok(())
}

#[pyfunction(name = "_urlpath_make_absolute_url")]
fn urlpath_make_absolute_url(
    py: Python<'_>,
    path: &Bound<'_, PyAny>,
    protocol: &Bound<'_, PyAny>,
    host: &Bound<'_, PyAny>,
    base_url: &Bound<'_, PyAny>,
    url_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let base_url = if base_url.is_instance_of::<PyString>() {
        url_type.call1((base_url,))?
    } else {
        base_url.clone()
    };
    let scheme = if protocol.is_truthy()? {
        let schemes = PyDict::new(py);
        let http = PyDict::new(py);
        http.set_item(true, "https")?;
        http.set_item(false, "http")?;
        let websocket = PyDict::new(py);
        websocket.set_item(true, "wss")?;
        websocket.set_item(false, "ws")?;
        schemes.set_item("http", http)?;
        schemes.set_item("websocket", websocket)?;
        let by_protocol = schemes.call_method1("__getitem__", (protocol,))?;
        let is_secure = base_url.getattr("is_secure")?;
        by_protocol.call_method1("__getitem__", (is_secure,))?
    } else {
        base_url.getattr("scheme")?
    };
    let netloc = if host.is_truthy()? {
        host.clone()
    } else {
        base_url.getattr("netloc")?
    };
    let base_path = base_url.getattr("path")?.call_method1("rstrip", ("/",))?;
    let path = base_path.call_method1("__add__", (path,))?;
    let components = PyDict::new(py);
    components.set_item("scheme", scheme)?;
    components.set_item("netloc", netloc)?;
    components.set_item("path", path)?;
    url_type.call((), Some(&components)).map(Bound::unbind)
}

#[pyfunction(name = "_state_new")]
fn state_new(py: Python<'_>, state: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    if state.is_none() {
        return Ok(PyDict::new(py).into_any().unbind());
    }
    Ok(state.clone().unbind())
}

#[pyfunction(name = "_state_getattr")]
fn state_getattr(
    py: Python<'_>,
    state: &Bound<'_, PyAny>,
    class_name: &str,
    key: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    match state.get_item(key) {
        Ok(value) => Ok(value.unbind()),
        Err(error) if error.is_instance_of::<PyKeyError>(py) => {
            let key_text = key.str()?.to_str()?.to_owned();
            let attribute_error = PyAttributeError::new_err(format!(
                "'{class_name}' object has no attribute '{key_text}'"
            ));
            attribute_error.set_context(py, Some(error));
            Err(attribute_error)
        }
        Err(error) => Err(error),
    }
}

#[pyfunction(name = "_state_set")]
fn state_set(
    state: &Bound<'_, PyAny>,
    key: &Bound<'_, PyAny>,
    value: &Bound<'_, PyAny>,
) -> PyResult<()> {
    state.set_item(key, value)
}

#[pyfunction(name = "_state_get")]
fn state_get(state: &Bound<'_, PyAny>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    state.get_item(key).map(Bound::unbind)
}

#[pyfunction(name = "_state_delete")]
fn state_delete(state: &Bound<'_, PyAny>, key: &Bound<'_, PyAny>) -> PyResult<()> {
    state.del_item(key)
}

#[pyfunction(name = "_state_iter")]
fn state_iter(state: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    state.call_method0("__iter__").map(Bound::unbind)
}

#[pyfunction(name = "_state_len")]
fn state_len(state: &Bound<'_, PyAny>) -> PyResult<usize> {
    state.len()
}
