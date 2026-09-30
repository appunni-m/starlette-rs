//! Rust-owned URL and connection-state semantics for the Python compatibility API.
//!
//! `urllib.parse` remains the parser/formatter because Starlette exposes its
//! `SplitResult` behavior verbatim. Rust owns URL construction decisions,
//! component caching, replacement, password redaction, and State mapping/error
//! policy. The public `URLPath` subclass remains Python because its value must
//! actually be a `str` subclass.

use pyo3::exceptions::{PyAssertionError, PyAttributeError, PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString, PyTuple};
use starlette_rs::FormData as NativeFormData;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PySecret>()?;
    module
        .getattr("Secret")?
        .setattr("__module__", "starlette.datastructures")?;
    module.add_class::<PyFormData>()?;
    module
        .getattr("FormData")?
        .setattr("__module__", "starlette.datastructures")?;
    module.add_function(wrap_pyfunction!(url_init, module)?)?;
    module.add_function(wrap_pyfunction!(url_components, module)?)?;
    module.add_function(wrap_pyfunction!(url_replace, module)?)?;
    module.add_function(wrap_pyfunction!(url_include_query_params, module)?)?;
    module.add_function(wrap_pyfunction!(url_replace_query_params, module)?)?;
    module.add_function(wrap_pyfunction!(url_remove_query_params, module)?)?;
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

/// Immutable ordered form fields backed by Rust's multi-dict semantics.
#[pyclass(name = "FormData", subclass)]
pub(crate) struct PyFormData {
    inner: NativeFormData,
}

#[pymethods]
impl PyFormData {
    #[new]
    #[pyo3(signature = (*args, **kwargs))]
    fn new(args: &Bound<'_, PyTuple>, kwargs: Option<&Bound<'_, PyDict>>) -> PyResult<Self> {
        if args.len() > 1 {
            return Err(PyAssertionError::new_err("Too many arguments."));
        }
        let mut items = if args.is_empty() {
            Vec::new()
        } else {
            form_data_from_python(&args.get_item(0)?)?
        };
        if let Some(kwargs) = kwargs {
            items.extend(form_data_from_mapping(kwargs)?);
        }
        Ok(Self {
            inner: NativeFormData::from_pairs(items),
        })
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python<'_>, key: &Bound<'_, PyAny>, default: Option<Py<PyAny>>) -> Py<PyAny> {
        form_data_key(key)
            .as_deref()
            .and_then(|form_key| self.inner.get(form_key))
            .map(|value| PyString::new(py, value).into_any().unbind())
            .or(default)
            .unwrap_or_else(|| py.None())
    }

    fn getlist(&self, key: &Bound<'_, PyAny>) -> Vec<String> {
        let Some(key) = form_data_key(key) else {
            return Vec::new();
        };
        self.inner
            .get_list(&key)
            .into_iter()
            .map(str::to_owned)
            .collect()
    }

    fn get_list(&self, key: &Bound<'_, PyAny>) -> Vec<String> {
        self.getlist(key)
    }

    fn multi_items(&self) -> Vec<(String, String)> {
        self.inner.multi_items().to_vec()
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping_dict(py)?
            .call_method0("keys")
            .map(Bound::unbind)
    }

    fn values(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping_dict(py)?
            .call_method0("values")
            .map(Bound::unbind)
    }

    fn items(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping_dict(py)?
            .call_method0("items")
            .map(Bound::unbind)
    }

    fn len(&self) -> usize {
        self.inner.len()
    }

    fn is_empty(&self) -> bool {
        self.inner.is_empty()
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping_dict(py)?
            .call_method0("keys")?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __contains__(&self, key: &Bound<'_, PyAny>) -> bool {
        form_data_key(key).is_some_and(|key| self.inner.get(&key).is_some())
    }

    fn __getitem__(&self, key: &Bound<'_, PyAny>) -> PyResult<String> {
        form_data_key(key)
            .as_deref()
            .and_then(|form_key| self.inner.get(form_key))
            .map(str::to_owned)
            .ok_or_else(|| PyKeyError::new_err(key.clone().unbind()))
    }

    fn __repr__(slf: PyRef<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let items = slf.inner.multi_items().to_vec();
        let instance = slf.into_pyobject(py)?;
        let class_name = instance.get_type().name()?.to_string();
        let list = PyList::new(py, items)?;
        let items_repr = list.repr()?.to_str()?.to_owned();
        Ok(format!("{class_name}({items_repr})"))
    }

    fn __eq__(slf: PyRef<'_, Self>, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<bool> {
        let instance = slf.into_pyobject(py)?;
        if !other.is_instance(&instance.get_type())? {
            return Ok(false);
        }
        let other = other.extract::<PyRef<'_, PyFormData>>()?;
        Ok(instance.extract::<PyRef<'_, PyFormData>>()?.inner == other.inner)
    }

    fn _close(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::awaitable::into_python_awaitable(py, FormDataClose)
    }
}

impl PyFormData {
    fn mapping_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let mapping = PyDict::new(py);
        for (key, value) in self.inner.items() {
            mapping.set_item(key, value)?;
        }
        Ok(mapping)
    }
}

struct FormDataClose;

impl crate::awaitable::AwaitableStateMachine for FormDataClose {
    fn resume(
        &mut self,
        py: Python<'_>,
        input: crate::awaitable::MachineResume,
    ) -> PyResult<crate::awaitable::MachineAction> {
        match input {
            crate::awaitable::MachineResume::Start => {
                Ok(crate::awaitable::MachineAction::Complete(py.None()))
            }
            crate::awaitable::MachineResume::Value(_) => Err(PyValueError::new_err(
                "form data close received an unexpected result",
            )),
            crate::awaitable::MachineResume::AsyncIterationComplete(error)
            | crate::awaitable::MachineResume::Error(error) => Err(error),
        }
    }
}

fn form_data_key(value: &Bound<'_, PyAny>) -> Option<String> {
    value
        .is_instance_of::<PyString>()
        .then(|| value.extract::<String>().ok())
        .flatten()
}

fn form_data_from_python(value: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    if !value.is_truthy()? {
        return Ok(Vec::new());
    }
    if value.hasattr("multi_items")? {
        return form_data_from_iterable(&value.call_method0("multi_items")?);
    }
    if value.hasattr("items")? {
        return form_data_from_iterable(&value.call_method0("items")?);
    }
    form_data_from_iterable(value)
}

fn form_data_from_mapping(mapping: &Bound<'_, PyDict>) -> PyResult<Vec<(String, String)>> {
    mapping
        .iter()
        .map(|(key, value)| Ok((key.extract::<String>()?, value.extract::<String>()?)))
        .collect()
}

fn form_data_from_iterable(values: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    values
        .try_iter()?
        .map(|pair| {
            let pair_values = pair?.try_iter()?.collect::<PyResult<Vec<_>>>()?;
            if pair_values.len() != 2 {
                let message = if pair_values.len() < 2 {
                    format!(
                        "not enough values to unpack (expected 2, got {})",
                        pair_values.len()
                    )
                } else {
                    "too many values to unpack (expected 2)".to_owned()
                };
                return Err(PyValueError::new_err(message));
            }
            Ok((
                pair_values[0].extract::<String>()?,
                pair_values[1].extract::<String>()?,
            ))
        })
        .collect()
}

/// Redacted string value accepted by configuration and session middleware.
#[pyclass(name = "Secret", subclass)]
pub(crate) struct PySecret {
    value: String,
}

#[pymethods]
impl PySecret {
    #[new]
    fn new(value: String) -> Self {
        Self { value }
    }

    fn __str__(&self) -> String {
        self.value.clone()
    }

    fn __repr__(slf: PyRef<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let instance = slf.into_pyobject(py)?;
        let class_name = instance.get_type().name()?.to_string();
        Ok(format!("{class_name}('**********')"))
    }

    fn __bool__(&self) -> bool {
        !self.value.is_empty()
    }
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

#[pyfunction(name = "_url_include_query_params")]
fn url_include_query_params(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let mut pairs = parse_query_pairs(py, url)?;
    let updates = PyDict::new(py);
    let stringify = py.import("builtins")?.getattr("str")?;
    for (key, value) in kwargs.iter() {
        let key = stringify.call1((key,))?;
        let value = stringify.call1((value,))?;
        updates.set_item(&key, &value)?;
    }

    let update_keys = updates.keys();
    let mut retained = Vec::with_capacity(pairs.len());
    for (key, value) in pairs.drain(..) {
        if !update_keys.contains(key.bind(py))? {
            retained.push((key, value));
        }
    }
    for pair in updates.items().try_iter()? {
        let pair = pair?.cast_into::<PyTuple>()?;
        retained.push((pair.get_item(0)?.unbind(), pair.get_item(1)?.unbind()));
    }

    let query = encode_query_pairs(py, &retained)?;
    replace_url_query(url, query.bind(py))
}

#[pyfunction(name = "_url_replace_query_params")]
fn url_replace_query_params(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let stringify = py.import("builtins")?.getattr("str")?;
    let mut pairs = Vec::with_capacity(kwargs.len());
    for (key, value) in kwargs.iter() {
        pairs.push((
            stringify.call1((key,))?.unbind(),
            stringify.call1((value,))?.unbind(),
        ));
    }
    let query = encode_query_pairs(py, &pairs)?;
    replace_url_query(url, query.bind(py))
}

#[pyfunction(name = "_url_remove_query_params")]
fn url_remove_query_params(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
    keys: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let mut pairs = parse_query_pairs(py, url)?;
    let parameters = PyDict::new(py);
    for (key, value) in &pairs {
        parameters.set_item(key.bind(py), value.bind(py))?;
    }

    let keys = if keys.is_instance_of::<PyString>() {
        PyList::new(py, [keys.clone()])?.into_any()
    } else {
        keys.clone()
    };
    for key in keys.try_iter()? {
        let key = key?;
        let mut retained = Vec::with_capacity(pairs.len());
        for (parameter, value) in pairs.drain(..) {
            if parameter
                .bind(py)
                .rich_compare(&key, pyo3::class::basic::CompareOp::Ne)?
                .is_truthy()?
            {
                retained.push((parameter, value));
            }
        }
        pairs = retained;
        parameters.call_method1("pop", (&key, py.None()))?;
    }

    let query = encode_query_pairs(py, &pairs)?;
    replace_url_query(url, query.bind(py))
}

fn parse_query_pairs(
    py: Python<'_>,
    url: &Bound<'_, PyAny>,
) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
    let parse_qsl = py.import("urllib.parse")?.getattr("parse_qsl")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("keep_blank_values", true)?;
    let parsed = parse_qsl.call((url.getattr("query")?,), Some(&kwargs))?;
    parsed
        .try_iter()?
        .map(|pair| {
            let pair = pair?.cast_into::<PyTuple>()?;
            Ok((pair.get_item(0)?.unbind(), pair.get_item(1)?.unbind()))
        })
        .collect()
}

fn encode_query_pairs(py: Python<'_>, pairs: &[(Py<PyAny>, Py<PyAny>)]) -> PyResult<Py<PyAny>> {
    let values = PyList::empty(py);
    for (key, value) in pairs {
        values.append(PyTuple::new(py, [key.clone_ref(py), value.clone_ref(py)])?)?;
    }
    py.import("urllib.parse")?
        .getattr("urlencode")?
        .call1((values,))
        .map(Bound::unbind)
}

fn replace_url_query(url: &Bound<'_, PyAny>, query: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let kwargs = PyDict::new(url.py());
    kwargs.set_item("query", query)?;
    url.call_method("replace", (), Some(&kwargs))
        .map(Bound::unbind)
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
        let redacted = replace_split(py, &components, &replacement)?.call_method0("geturl")?;
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
