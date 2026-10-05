//! Rust-owned URL and connection-state semantics for the Python compatibility API.
//!
//! `urllib.parse` remains the parser/formatter because Starlette exposes its
//! `SplitResult` behavior verbatim. Rust owns URL construction decisions,
//! component caching, replacement, password redaction, and State mapping/error
//! policy. The public `URLPath` subclass remains Python because its value must
//! actually be a `str` subclass.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAssertionError, PyAttributeError, PyKeyError, PyRuntimeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PyModule, PyString, PyTuple};
use starlette_rs::PythonCodePointStrings as NativePythonCodePointStrings;

use crate::awaitable::into_sendable_python_awaitable;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyCommaSeparatedStrings>()?;
    module
        .getattr("CommaSeparatedStrings")?
        .setattr("__module__", "starlette.datastructures")?;
    module.add_class::<PySecret>()?;
    module
        .getattr("Secret")?
        .setattr("__module__", "starlette.datastructures")?;
    module.add_class::<PyMultiDictStore>()?;
    module.add_function(wrap_pyfunction!(multidict_update, module)?)?;
    module.add_class::<PyFormData>()?;
    module
        .getattr("FormData")?
        .setattr("__module__", "starlette.datastructures")?;
    module.add_class::<PyUploadFile>()?;
    module
        .getattr("UploadFile")?
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

/// Python-keyed ordered pair storage with Rust-owned multi-dict operations.
#[pyclass(name = "_MultiDictStore")]
struct PyMultiDictStore {
    items: Vec<(Py<PyAny>, Py<PyAny>)>,
    mapping: Py<PyDict>,
}

#[pymethods]
impl PyMultiDictStore {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        for (key, value) in &self.items {
            visit.call(key)?;
            visit.call(value)?;
        }
        visit.call(&self.mapping)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.items.clear();
        self.mapping = PyDict::new(py).unbind();
    }

    #[new]
    #[pyo3(signature = (*args, **kwargs))]
    fn new(
        py: Python<'_>,
        args: &Bound<'_, PyTuple>,
        kwargs: Option<&Bound<'_, PyDict>>,
    ) -> PyResult<Self> {
        if args.len() > 1 {
            return Err(PyAssertionError::new_err("Too many arguments."));
        }
        let mut items = if args.is_empty() {
            Vec::new()
        } else {
            multidict_from_python(&args.get_item(0)?)?
        };
        if let Some(kwargs) = kwargs {
            items.extend(multidict_from_mapping(kwargs)?);
        }
        Self::from_items(py, items)
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, key: &Bound<'_, PyAny>, default: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        Ok(self
            .mapping
            .bind(key.py())
            .get_item(key)?
            .map(Bound::unbind)
            .or(default)
            .unwrap_or_else(|| key.py().None()))
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        self.items
            .iter()
            .filter_map(|(item_key, value)| match item_key.bind(py).eq(key) {
                Ok(true) => Some(Ok(value.clone_ref(py))),
                Ok(false) => None,
                Err(error) => Some(Err(error)),
            })
            .collect()
    }

    fn multi_items(&self, py: Python<'_>) -> Vec<(Py<PyAny>, Py<PyAny>)> {
        self.items
            .iter()
            .map(|(key, value)| (key.clone_ref(py), value.clone_ref(py)))
            .collect()
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping
            .bind(py)
            .call_method0("keys")
            .map(Bound::unbind)
    }

    fn values(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping
            .bind(py)
            .call_method0("values")
            .map(Bound::unbind)
    }

    fn items_view(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping
            .bind(py)
            .call_method0("items")
            .map(Bound::unbind)
    }

    fn len(&self, py: Python<'_>) -> usize {
        self.mapping.bind(py).len()
    }

    fn is_empty(&self, py: Python<'_>) -> bool {
        self.mapping.bind(py).is_empty()
    }

    fn contains(&self, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.mapping.bind(key.py()).contains(key)
    }

    fn __len__(&self, py: Python<'_>) -> usize {
        self.len(py)
    }

    fn __bool__(&self, py: Python<'_>) -> bool {
        !self.is_empty(py)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.keys(py)?
            .bind(py)
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __contains__(&self, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        self.contains(key)
    }

    fn __getitem__(&self, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.mapping
            .bind(key.py())
            .get_item(key)?
            .map(Bound::unbind)
            .ok_or_else(|| PyKeyError::new_err(key.clone().unbind()))
    }

    fn repr(&self, py: Python<'_>, class_name: &str) -> PyResult<String> {
        let values = PyList::new(py, self.multi_items(py))?;
        Ok(format!("{class_name}({})", values.repr()?.to_str()?))
    }

    fn equals(
        &self,
        py: Python<'_>,
        class_type: &Bound<'_, PyAny>,
        other: &Bound<'_, PyAny>,
    ) -> PyResult<bool> {
        if !other.is_instance(class_type)? {
            return Ok(false);
        }
        let other = other.getattr("_inner")?.extract::<PyRef<'_, Self>>()?;
        let left = PyList::new(py, self.multi_items(py))?;
        let right = PyList::new(py, other.multi_items(py))?;
        let sorted = py.import("builtins")?.getattr("sorted")?;
        sorted.call1((left,))?.eq(sorted.call1((right,))?)
    }

    fn set(&mut self, key: Py<PyAny>, value: Py<PyAny>, py: Python<'_>) -> PyResult<()> {
        let values = PyList::new(py, [value])?;
        self.setlist(py, key.bind(py), values.as_any())
    }

    fn delete(&mut self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        self.retain_other_keys(py, key)?;
        self.mapping.bind(py).del_item(key)
    }

    #[pyo3(signature = (key, default=None))]
    fn pop(
        &mut self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.retain_other_keys(py, key)?;
        let default = default.unwrap_or_else(|| py.None());
        self.mapping
            .bind(py)
            .call_method1("pop", (key, default))
            .map(Bound::unbind)
    }

    fn popitem(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let item = self.mapping.bind(py).call_method0("popitem")?;
        let pair = item.cast::<PyTuple>()?;
        let key = pair.get_item(0)?;
        self.retain_other_keys(py, &key)?;
        Ok(item.unbind())
    }

    fn poplist(&mut self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        let values = self.getlist(py, key)?;
        let default = py.None();
        self.pop(py, key, Some(default))?;
        Ok(values)
    }

    fn clear(&mut self, py: Python<'_>) {
        self.items.clear();
        self.mapping.bind(py).clear();
    }

    fn setdefault(
        &mut self,
        py: Python<'_>,
        key: Py<PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let mapping = self.mapping.bind(py);
        let inserted = !mapping.contains(key.bind(py))?;
        let default = default.unwrap_or_else(|| py.None());
        let value = mapping.call_method1("setdefault", (key.bind(py), default))?;
        if inserted {
            self.items.push((key.clone_ref(py), value.clone().unbind()));
        }
        Ok(value.unbind())
    }

    fn setlist(
        &mut self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        values: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let values = values.try_iter()?.collect::<PyResult<Vec<_>>>()?;
        if values.is_empty() {
            self.pop(py, key, Some(py.None()))?;
            return Ok(());
        }
        let mapping = self.mapping.bind(py);
        let mut retained = Vec::with_capacity(self.items.len());
        for (item_key, value) in &self.items {
            if !item_key.bind(py).eq(key)? {
                retained.push((item_key.clone_ref(py), value.clone_ref(py)));
            }
        }
        self.items = retained;
        for value in &values {
            self.items
                .push((key.clone().unbind(), value.clone().unbind()));
        }
        match values.last() {
            Some(value) => mapping.set_item(key, value),
            None => Ok(()),
        }
    }

    fn append(&mut self, py: Python<'_>, key: Py<PyAny>, value: Py<PyAny>) -> PyResult<()> {
        self.items.push((key.clone_ref(py), value.clone_ref(py)));
        self.mapping.bind(py).set_item(key.bind(py), value.bind(py))
    }
}

impl PyMultiDictStore {
    fn from_items(py: Python<'_>, items: Vec<(Py<PyAny>, Py<PyAny>)>) -> PyResult<Self> {
        let mapping = PyDict::new(py);
        for (key, value) in &items {
            mapping.set_item(key.bind(py), value.bind(py))?;
        }
        Ok(Self {
            items,
            mapping: mapping.unbind(),
        })
    }

    fn retain_other_keys(&mut self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        let mut retained = Vec::with_capacity(self.items.len());
        for (item_key, value) in &self.items {
            if !item_key.bind(py).eq(key)? {
                retained.push((item_key.clone_ref(py), value.clone_ref(py)));
            }
        }
        self.items = retained;
        Ok(())
    }

    fn update_from(&mut self, py: Python<'_>, value: Self) -> PyResult<()> {
        let mut retained = Vec::with_capacity(self.items.len());
        for (key, item_value) in &self.items {
            if !value.mapping.bind(py).contains(key.bind(py))? {
                retained.push((key.clone_ref(py), item_value.clone_ref(py)));
            }
        }
        self.items = retained;
        self.items.extend(value.multi_items(py));
        self.mapping
            .bind(py)
            .call_method1("update", (value.mapping.bind(py),))?;
        Ok(())
    }
}

#[pyfunction(name = "_multidict_update")]
fn multidict_update(
    py: Python<'_>,
    store: &Bound<'_, PyAny>,
    args: &Bound<'_, PyTuple>,
    kwargs: &Bound<'_, PyDict>,
) -> PyResult<()> {
    let value = PyMultiDictStore::new(py, args, Some(kwargs))?;
    store
        .extract::<PyRefMut<'_, PyMultiDictStore>>()?
        .update_from(py, value)
}

fn multidict_from_python(value: &Bound<'_, PyAny>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
    if !value.is_truthy()? {
        return Ok(Vec::new());
    }
    if value.hasattr("multi_items")? {
        return multidict_from_iterable(&value.call_method0("multi_items")?);
    }
    if value.hasattr("items")? {
        return multidict_from_iterable(&value.call_method0("items")?);
    }
    multidict_from_iterable(value)
}

fn multidict_from_mapping(mapping: &Bound<'_, PyDict>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
    Ok(mapping
        .iter()
        .map(|(key, value)| (key.unbind(), value.unbind()))
        .collect())
}

fn multidict_from_iterable(values: &Bound<'_, PyAny>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
    values
        .try_iter()?
        .map(|pair| {
            let pair = pair?;
            let pair_values = pair.try_iter()?.collect::<PyResult<Vec<_>>>()?;
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
                pair_values[0].clone().unbind(),
                pair_values[1].clone().unbind(),
            ))
        })
        .collect()
}

/// Python conversion and protocol methods for the Rust-owned value type.
#[pyclass(name = "CommaSeparatedStrings")]
pub(crate) struct PyCommaSeparatedStrings {
    inner: NativePythonCodePointStrings,
    python_items: Option<Vec<Py<PyAny>>>,
}

#[pymethods]
impl PyCommaSeparatedStrings {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        if let Some(items) = &self.python_items {
            for item in items {
                visit.call(item)?;
            }
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.python_items = None;
    }

    #[new]
    fn new(value: &Bound<'_, PyAny>) -> PyResult<Self> {
        let (inner, python_items) = if value.is_instance_of::<PyString>() {
            let codepoints = python_string_to_codepoints(value)?;
            let inner = NativePythonCodePointStrings::parse(&codepoints)
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
            (inner, None)
        } else {
            let mut native_items = Vec::new();
            let mut python_items = Vec::new();
            for item in value.try_iter()? {
                let item = item?;
                let item_string = item.cast_into::<PyString>()?;
                native_items.push(python_string_to_codepoints(item_string.as_any())?);
                python_items.push(item_string.into_any().unbind());
            }
            (
                NativePythonCodePointStrings::from_items(native_items)
                    .map_err(|error| PyValueError::new_err(error.to_string()))?,
                Some(python_items),
            )
        };
        Ok(Self {
            inner,
            python_items,
        })
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    fn __getitem__(&self, py: Python<'_>, index: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        self.as_python_list(py)?
            .as_any()
            .call_method1("__getitem__", (index,))
            .map(Bound::unbind)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.as_python_list(py)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __str__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyString>> {
        let value = match &self.python_items {
            Some(items) => self
                .inner
                .as_string_with_item_reprs(&python_item_reprs(py, items)?),
            None => self.inner.as_string(),
        };
        codepoints_to_python_string(py, &value)
    }

    fn __repr__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyString>> {
        self.class_repr(py, "CommaSeparatedStrings")
    }

    #[pyo3(name = "_repr_for_class")]
    fn repr_for_class<'py>(
        &self,
        py: Python<'py>,
        class_name: &str,
    ) -> PyResult<Bound<'py, PyString>> {
        self.class_repr(py, class_name)
    }
}

impl PyCommaSeparatedStrings {
    fn as_python_list<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        match &self.python_items {
            Some(items) => PyList::new(py, items.iter().map(|item| item.clone_ref(py))),
            None => {
                let items = self
                    .inner
                    .items()
                    .iter()
                    .map(|item| codepoints_to_python_string(py, item).map(Bound::into_any))
                    .collect::<PyResult<Vec<_>>>()?;
                PyList::new(py, items)
            }
        }
    }

    fn class_repr<'py>(&self, py: Python<'py>, class_name: &str) -> PyResult<Bound<'py, PyString>> {
        let value = match &self.python_items {
            Some(items) => NativePythonCodePointStrings::repr_with_item_reprs(
                class_name,
                &python_item_reprs(py, items)?,
            ),
            None => self.inner.repr(class_name),
        };
        codepoints_to_python_string(py, &value)
    }
}

pub(crate) fn python_string_to_codepoints(value: &Bound<'_, PyAny>) -> PyResult<Vec<u32>> {
    let py = value.py();
    let encode = py.get_type::<PyString>().getattr("encode")?;
    let encoded = encode
        .call1((value, "utf-32-le", "surrogatepass"))?
        .cast_into::<PyBytes>()?;
    let chunks = encoded.as_bytes().chunks_exact(4);
    if !chunks.remainder().is_empty() {
        return Err(PyValueError::new_err(
            "UTF-32 conversion returned an incomplete code point",
        ));
    }
    chunks
        .map(|chunk| {
            let bytes = <[u8; 4]>::try_from(chunk).map_err(|_| {
                PyValueError::new_err("UTF-32 conversion returned an incomplete code point")
            })?;
            Ok(u32::from_le_bytes(bytes))
        })
        .collect()
}

pub(crate) fn codepoints_to_python_string<'py>(
    py: Python<'py>,
    codepoints: &[u32],
) -> PyResult<Bound<'py, PyString>> {
    let mut bytes = Vec::with_capacity(codepoints.len() * 4);
    for codepoint in codepoints {
        bytes.extend_from_slice(&codepoint.to_le_bytes());
    }
    PyString::from_encoded_object(
        PyBytes::new(py, &bytes).as_any(),
        Some(c"utf-32-le"),
        Some(c"surrogatepass"),
    )
}

fn python_item_reprs(py: Python<'_>, items: &[Py<PyAny>]) -> PyResult<Vec<Vec<u32>>> {
    items
        .iter()
        .map(|item| {
            let repr = item.bind(py).repr()?;
            python_string_to_codepoints(repr.as_any())
        })
        .collect()
}

/// Immutable ordered form fields backed by Rust's multi-dict semantics.
#[pyclass(name = "FormData", subclass)]
pub(crate) struct PyFormData {
    items: Vec<(String, Py<PyAny>)>,
}

#[pymethods]
impl PyFormData {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        for (_, value) in &self.items {
            visit.call(value)?;
        }
        Ok(())
    }

    fn __clear__(&mut self) {
        self.items.clear();
    }

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
        Ok(Self { items })
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python<'_>, key: &Bound<'_, PyAny>, default: Option<Py<PyAny>>) -> Py<PyAny> {
        form_data_key(key)
            .as_deref()
            .and_then(|form_key| self.get_value(form_key))
            .map(|value| value.clone_ref(py))
            .or(default)
            .unwrap_or_else(|| py.None())
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> Vec<Py<PyAny>> {
        let Some(key) = form_data_key(key) else {
            return Vec::new();
        };
        self.items
            .iter()
            .filter(|(item_key, _)| item_key == &key)
            .map(|(_, value)| value.clone_ref(py))
            .collect()
    }

    fn get_list(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> Vec<Py<PyAny>> {
        self.getlist(py, key)
    }

    fn multi_items(&self, py: Python<'_>) -> Vec<(String, Py<PyAny>)> {
        self.items
            .iter()
            .map(|(key, value)| (key.clone(), value.clone_ref(py)))
            .collect()
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

    fn len(&self, py: Python<'_>) -> PyResult<usize> {
        self.mapping_dict(py).map(|mapping| mapping.len())
    }

    fn is_empty(&self, py: Python<'_>) -> PyResult<bool> {
        self.mapping_dict(py).map(|mapping| mapping.is_empty())
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        self.len(py)
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.mapping_dict(py)?
            .call_method0("keys")?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __contains__(&self, key: &Bound<'_, PyAny>) -> bool {
        form_data_key(key).is_some_and(|key| self.get_value(&key).is_some())
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        form_data_key(key)
            .as_deref()
            .and_then(|form_key| self.get_value(form_key))
            .map(|value| value.clone_ref(py))
            .ok_or_else(|| PyKeyError::new_err(key.clone().unbind()))
    }

    fn __repr__(slf: PyRef<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let items = slf.multi_items(py);
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
        let left = PyList::new(
            py,
            instance.extract::<PyRef<'_, PyFormData>>()?.multi_items(py),
        )?;
        let right = PyList::new(py, other.multi_items(py))?;
        let sorted = py.import("builtins")?.getattr("sorted")?;
        sorted.call1((left,))?.eq(sorted.call1((right,))?)
    }

    fn _close(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let files = self
            .items
            .iter()
            .filter(|(_, value)| value.bind(py).is_instance_of::<PyUploadFile>())
            .map(|(_, value)| value.clone_ref(py))
            .collect();
        crate::awaitable::into_sendable_python_awaitable(py, FormDataClose { files, index: 0 })
    }
}

impl PyFormData {
    fn get_value(&self, key: &str) -> Option<&Py<PyAny>> {
        self.items
            .iter()
            .rev()
            .find(|(item_key, _)| item_key == key)
            .map(|(_, value)| value)
    }

    fn mapping_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let mapping = PyDict::new(py);
        for (key, value) in &self.items {
            mapping.set_item(key, value.bind(py))?;
        }
        Ok(mapping)
    }
}

struct FormDataClose {
    files: Vec<Py<PyAny>>,
    index: usize,
}

impl crate::awaitable::AwaitableStateMachine for FormDataClose {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        for file in &self.files {
            visit.call(file)?;
        }
        Ok(())
    }

    fn resume(
        &mut self,
        py: Python<'_>,
        input: crate::awaitable::MachineResume,
    ) -> PyResult<crate::awaitable::MachineAction> {
        match input {
            crate::awaitable::MachineResume::Start => self.next(py),
            crate::awaitable::MachineResume::Value(_) => {
                self.index += 1;
                self.next(py)
            }
            crate::awaitable::MachineResume::AsyncIterationComplete(error)
            | crate::awaitable::MachineResume::Error(error) => Err(error),
        }
    }
}

impl FormDataClose {
    fn next(&mut self, py: Python<'_>) -> PyResult<crate::awaitable::MachineAction> {
        let Some(file) = self.files.get(self.index) else {
            return Ok(crate::awaitable::MachineAction::Complete(py.None()));
        };
        Ok(crate::awaitable::MachineAction::Await(
            file.bind(py).call_method0("close")?.unbind(),
        ))
    }
}

fn form_data_key(value: &Bound<'_, PyAny>) -> Option<String> {
    value
        .is_instance_of::<PyString>()
        .then(|| value.extract::<String>().ok())
        .flatten()
}

fn form_data_from_python(value: &Bound<'_, PyAny>) -> PyResult<Vec<(String, Py<PyAny>)>> {
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

fn form_data_from_mapping(mapping: &Bound<'_, PyDict>) -> PyResult<Vec<(String, Py<PyAny>)>> {
    mapping
        .iter()
        .map(|(key, value)| Ok((key.extract::<String>()?, value.unbind())))
        .collect()
}

fn form_data_from_iterable(values: &Bound<'_, PyAny>) -> PyResult<Vec<(String, Py<PyAny>)>> {
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
                pair_values[1].clone().unbind(),
            ))
        })
        .collect()
}

// Shared operations visit one GC-visible node; its Python references are
// owned and traversed once, regardless of the number of outstanding operations.
type SharedUploadFile = Py<UploadFileState>;

#[pyclass]
struct UploadFileState {
    file: Py<PyAny>,
    filename: Option<Py<PyAny>>,
    size: Option<Py<PyAny>>,
    headers: Py<PyAny>,
    max_mem_size: Py<PyAny>,
}

#[pymethods]
impl UploadFileState {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.file)?;
        visit.call(&self.filename)?;
        visit.call(&self.size)?;
        visit.call(&self.headers)?;
        visit.call(&self.max_mem_size)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.file = py.None();
        self.filename = None;
        self.size = None;
        self.headers = py.None();
        self.max_mem_size = py.None();
    }
}

fn upload_state<'py>(
    py: Python<'py>,
    shared: &'py SharedUploadFile,
) -> PyResult<PyRef<'py, UploadFileState>> {
    shared
        .try_borrow(py)
        .map_err(|_| PyRuntimeError::new_err("UploadFile is already borrowed"))
}

fn upload_state_mut<'py>(
    py: Python<'py>,
    shared: &'py SharedUploadFile,
) -> PyResult<PyRefMut<'py, UploadFileState>> {
    shared
        .try_borrow_mut(py)
        .map_err(|_| PyRuntimeError::new_err("UploadFile is already borrowed"))
}

/// Public UploadFile behavior with Rust-owned in-memory/worker-thread decisions.
///
/// The underlying Python binary file is retained because Starlette exposes it
/// directly as `UploadFile.file`, and Python consumers rely on the standard
/// file object's identity and methods.
#[pyclass(name = "UploadFile", subclass)]
pub(crate) struct PyUploadFile {
    shared: SharedUploadFile,
}

#[pymethods]
impl PyUploadFile {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)
    }

    #[new]
    #[pyo3(signature = (file, *, size=None, filename=None, headers=None))]
    fn new(
        py: Python<'_>,
        file: Py<PyAny>,
        size: Option<Py<PyAny>>,
        filename: Option<Py<PyAny>>,
        headers: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let headers = match headers {
            Some(headers) if headers.bind(py).is_truthy()? => headers,
            _ => py
                .import("starlette.datastructures")?
                .getattr("Headers")?
                .call0()?
                .unbind(),
        };
        let max_mem_size = py
            .import("builtins")?
            .getattr("getattr")?
            .call1((file.bind(py), "_max_size", 0))?
            .unbind();
        Ok(Self {
            shared: Py::new(
                py,
                UploadFileState {
                    file,
                    filename,
                    size,
                    headers,
                    max_mem_size,
                },
            )?,
        })
    }

    #[getter]
    fn file(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(upload_state(py, &self.shared)?.file.clone_ref(py))
    }

    #[setter]
    fn set_file(&self, py: Python<'_>, file: Py<PyAny>) -> PyResult<()> {
        let previous = {
            let mut state = upload_state_mut(py, &self.shared)?;
            std::mem::replace(&mut state.file, file)
        };
        // Release the state borrow before a replaced user value can finalize.
        drop(previous);
        Ok(())
    }

    #[getter]
    fn filename(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(upload_state(py, &self.shared)?
            .filename
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py)))
    }

    #[setter]
    fn set_filename(&self, py: Python<'_>, filename: Option<Py<PyAny>>) -> PyResult<()> {
        let previous = {
            let mut state = upload_state_mut(py, &self.shared)?;
            std::mem::replace(&mut state.filename, filename)
        };
        // Release the state borrow before a replaced user value can finalize.
        drop(previous);
        Ok(())
    }

    #[getter]
    fn size(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(upload_state(py, &self.shared)?
            .size
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py)))
    }

    #[setter]
    fn set_size(&self, py: Python<'_>, size: Option<Py<PyAny>>) -> PyResult<()> {
        let previous = {
            let mut state = upload_state_mut(py, &self.shared)?;
            std::mem::replace(&mut state.size, size)
        };
        // Release the state borrow before a replaced user value can finalize.
        drop(previous);
        Ok(())
    }

    #[getter]
    fn headers(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(upload_state(py, &self.shared)?.headers.clone_ref(py))
    }

    #[setter]
    fn set_headers(&self, py: Python<'_>, headers: Py<PyAny>) -> PyResult<()> {
        let previous = {
            let mut state = upload_state_mut(py, &self.shared)?;
            std::mem::replace(&mut state.headers, headers)
        };
        // Release the state borrow before a replaced user value can finalize.
        drop(previous);
        Ok(())
    }

    #[getter]
    fn content_type(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let headers = upload_state(py, &self.shared)?.headers.clone_ref(py);
        let none = py.None();
        headers
            .bind(py)
            .call_method1("get", ("content-type", none))
            .map(Bound::unbind)
    }

    #[getter]
    fn _max_mem_size(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(upload_state(py, &self.shared)?.max_mem_size.clone_ref(py))
    }

    #[setter]
    fn set_max_mem_size(&self, py: Python<'_>, max_mem_size: Py<PyAny>) -> PyResult<()> {
        let previous = {
            let mut state = upload_state_mut(py, &self.shared)?;
            std::mem::replace(&mut state.max_mem_size, max_mem_size)
        };
        // Release the state borrow before a replaced user value can finalize.
        drop(previous);
        Ok(())
    }

    #[getter]
    fn _in_memory(&self, py: Python<'_>) -> PyResult<bool> {
        let file = upload_state(py, &self.shared)?.file.clone_ref(py);
        upload_file_is_in_memory(py, file.bind(py))
    }

    fn _will_roll(&self, py: Python<'_>, size_to_add: &Bound<'_, PyAny>) -> PyResult<bool> {
        let file = upload_state(py, &self.shared)?.file.clone_ref(py);
        let max_mem_size = upload_state(py, &self.shared)?.max_mem_size.clone_ref(py);
        upload_file_will_roll(py, file.bind(py), max_mem_size.bind(py), size_to_add)
    }

    fn _write(&self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            UploadFileMachine {
                shared: self.shared.clone_ref(py),
                operation: UploadFileOperation::Write(data.clone().unbind()),
                pending: false,
            },
        )
    }

    fn _read(&self, py: Python<'_>, size: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            UploadFileMachine {
                shared: self.shared.clone_ref(py),
                operation: UploadFileOperation::Read(size.clone().unbind()),
                pending: false,
            },
        )
    }

    fn _seek(&self, py: Python<'_>, offset: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            UploadFileMachine {
                shared: self.shared.clone_ref(py),
                operation: UploadFileOperation::Seek(offset.clone().unbind()),
                pending: false,
            },
        )
    }

    fn _close(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            UploadFileMachine {
                shared: self.shared.clone_ref(py),
                operation: UploadFileOperation::Close,
                pending: false,
            },
        )
    }

    fn __repr__(slf: PyRef<'_, Self>) -> PyResult<String> {
        let py = slf.py();
        let filename = upload_state(py, &slf.shared)?
            .filename
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py));
        let size = upload_state(py, &slf.shared)?
            .size
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py));
        let headers = upload_state(py, &slf.shared)?.headers.clone_ref(py);
        let instance = slf.into_pyobject(py)?;
        let class_name = instance.get_type().name()?.to_string();
        Ok(format!(
            "{class_name}(filename={}, size={}, headers={})",
            filename.bind(py).repr()?.to_str()?,
            size.bind(py).repr()?.to_str()?,
            headers.bind(py).repr()?.to_str()?
        ))
    }
}

fn upload_file_is_in_memory(py: Python<'_>, file: &Bound<'_, PyAny>) -> PyResult<bool> {
    let rolled = py
        .import("builtins")?
        .getattr("getattr")?
        .call1((file, "_rolled", true))?;
    Ok(!rolled.is_truthy()?)
}

fn upload_file_will_roll(
    py: Python<'_>,
    file: &Bound<'_, PyAny>,
    max_mem_size: &Bound<'_, PyAny>,
    size_to_add: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    if !upload_file_is_in_memory(py, file)? {
        return Ok(true);
    }
    let future_size = file.call_method0("tell")?.add(size_to_add)?;
    if max_mem_size.is_truthy()? {
        future_size.gt(max_mem_size)
    } else {
        Ok(false)
    }
}

enum UploadFileOperation {
    Write(Py<PyAny>),
    Read(Py<PyAny>),
    Seek(Py<PyAny>),
    Close,
}

struct UploadFileMachine {
    shared: SharedUploadFile,
    operation: UploadFileOperation,
    pending: bool,
}

impl crate::awaitable::AwaitableStateMachine for UploadFileMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.shared)?;
        match &self.operation {
            UploadFileOperation::Write(value)
            | UploadFileOperation::Read(value)
            | UploadFileOperation::Seek(value) => visit.call(value)?,
            UploadFileOperation::Close => {}
        }
        Ok(())
    }

    fn resume(
        &mut self,
        py: Python<'_>,
        input: crate::awaitable::MachineResume,
    ) -> PyResult<crate::awaitable::MachineAction> {
        match input {
            crate::awaitable::MachineResume::Start if !self.pending => self.start(py),
            crate::awaitable::MachineResume::Value(value) if self.pending => {
                self.pending = false;
                match &self.operation {
                    UploadFileOperation::Read(_) => {
                        Ok(crate::awaitable::MachineAction::Complete(value))
                    }
                    _ => Ok(crate::awaitable::MachineAction::Complete(py.None())),
                }
            }
            crate::awaitable::MachineResume::Error(error)
            | crate::awaitable::MachineResume::AsyncIterationComplete(error) => Err(error),
            _ => Err(PyRuntimeError::new_err(
                "UploadFile operation received an unexpected result",
            )),
        }
    }
}

impl UploadFileMachine {
    fn start(&mut self, py: Python<'_>) -> PyResult<crate::awaitable::MachineAction> {
        let worker_required = match &self.operation {
            UploadFileOperation::Write(data) => {
                let data_length = data.bind(py).len()?;
                let size = upload_state(py, &self.shared)?
                    .size
                    .as_ref()
                    .map(|size| size.clone_ref(py));
                if let Some(size) = size {
                    // User int subclasses can define __iadd__, return themselves
                    // or None, and reenter UploadFile. CPython owns dispatch;
                    // release the native borrow before arithmetic and old-value drop.
                    let updated = py
                        .import("operator")?
                        .getattr("iadd")?
                        .call1((size.bind(py), PyInt::new(py, data_length)))?;
                    let updated = (!updated.is_none()).then(|| updated.unbind());
                    let previous =
                        std::mem::replace(&mut upload_state_mut(py, &self.shared)?.size, updated);
                    drop(previous);
                }
                // Python size arithmetic can replace the public backing file.
                // Read policy fields only after that callback has completed.
                let file = upload_state(py, &self.shared)?.file.clone_ref(py);
                let max_mem_size = upload_state(py, &self.shared)?.max_mem_size.clone_ref(py);
                let size_to_add = PyInt::new(py, data_length);
                upload_file_will_roll(py, file.bind(py), max_mem_size.bind(py), &size_to_add)?
            }
            UploadFileOperation::Read(_)
            | UploadFileOperation::Seek(_)
            | UploadFileOperation::Close => {
                let file = upload_state(py, &self.shared)?.file.clone_ref(py);
                !upload_file_is_in_memory(py, file.bind(py))?
            }
        };
        let (method, arguments): (&str, Vec<Py<PyAny>>) = match &self.operation {
            UploadFileOperation::Write(data) => ("write", vec![data.clone_ref(py)]),
            UploadFileOperation::Read(size) => ("read", vec![size.clone_ref(py)]),
            UploadFileOperation::Seek(offset) => ("seek", vec![offset.clone_ref(py)]),
            UploadFileOperation::Close => ("close", Vec::new()),
        };
        // Policy callbacks can also replace the file before source I/O lookup.
        let file = upload_state(py, &self.shared)?.file.clone_ref(py);
        let callable = file.bind(py).getattr(method)?;
        let result = if worker_required {
            let runner = py
                .import("starlette.concurrency")?
                .getattr("run_in_threadpool")?;
            let mut args = Vec::with_capacity(arguments.len() + 1);
            args.push(callable.unbind());
            args.extend(arguments);
            let args = PyTuple::new(py, args)?;
            runner.call1(args)?
        } else {
            callable.call1(PyTuple::new(py, arguments)?)?
        };
        if worker_required {
            self.pending = true;
            Ok(crate::awaitable::MachineAction::Await(result.unbind()))
        } else if matches!(&self.operation, UploadFileOperation::Read(_)) {
            Ok(crate::awaitable::MachineAction::Complete(result.unbind()))
        } else {
            Ok(crate::awaitable::MachineAction::Complete(py.None()))
        }
    }
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
