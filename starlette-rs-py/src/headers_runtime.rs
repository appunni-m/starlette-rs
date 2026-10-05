//! PyO3 boundary for Starlette's public `Headers` and `MutableHeaders` types.
//!
//! The ordered header semantics live in `starlette-rs`. This module converts
//! Python strings and byte-pair sequences, keeps the Python list identity
//! required by `MutableHeaders.raw` and `scope["headers"]`, and forwards the
//! public operations to the native types.

use pyo3::basic::CompareOp;
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyAssertionError, PyKeyError, PyOverflowError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PySlice, PyString, PyTuple};
use starlette_rs::{Headers as NativeHeaders, MutableHeaders as NativeMutableHeaders};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyHeadersStore>()?;
    module.add_function(wrap_pyfunction!(headers_equal, module)?)?;
    Ok(())
}

#[pyclass(name = "_HeadersStore")]
struct PyHeadersStore {
    raw: Py<PyAny>,
    mutable: bool,
}

#[pymethods]
impl PyHeadersStore {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.raw)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.raw = PyList::empty(py).into_any().unbind();
    }

    #[new]
    #[pyo3(signature = (headers=None, raw=None, scope=None, mutable=false))]
    fn new(
        py: Python<'_>,
        headers: Option<&Bound<'_, PyAny>>,
        raw: Option<&Bound<'_, PyAny>>,
        scope: Option<&Bound<'_, PyAny>>,
        mutable: bool,
    ) -> PyResult<Self> {
        let raw = if let Some(headers) = headers {
            if let Some(raw) = raw {
                if !raw.is_none() {
                    return Err(PyAssertionError::new_err(
                        "Cannot set both \"headers\" and \"raw\".",
                    ));
                }
            }
            if scope.is_some_and(|scope| !scope.is_none()) {
                return Err(PyAssertionError::new_err(
                    "Cannot set both \"headers\" and \"scope\".",
                ));
            }
            let pairs = mapping_pairs(py, headers)?;
            raw_pair_list(py, &pairs)?.into_any().unbind()
        } else if let Some(raw) = raw.filter(|raw| !raw.is_none()) {
            if scope.is_some_and(|scope| !scope.is_none()) {
                return Err(PyAssertionError::new_err(
                    "Cannot set both \"raw\" and \"scope\".",
                ));
            }
            raw.clone().unbind()
        } else if let Some(scope) = scope.filter(|scope| !scope.is_none()) {
            let headers = scope.get_item("headers")?;
            let list = py.import("builtins")?.getattr("list")?.call1((&headers,))?;
            scope.set_item("headers", &list)?;
            list.unbind()
        } else {
            PyList::empty(py).into_any().unbind()
        };

        Ok(Self { raw, mutable })
    }

    #[getter]
    fn raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if self.mutable {
            return Ok(self.raw.clone_ref(py));
        }
        py.import("builtins")?
            .getattr("list")?
            .call1((self.raw.bind(py),))
            .map(Bound::unbind)
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        self.header_names(py)
    }

    fn values(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        self.header_values(py)
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
        self.header_items(py)
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        let key = normalized_key(key)?;
        let mut values = Vec::new();
        for pair in self.raw.bind(py).try_iter()? {
            let (name, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            if header_key_matches(py, name.bind(py), &key)? {
                values.push(decode_header_component(value.bind(py))?);
            }
        }
        Ok(values)
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let key = normalized_key(key)?;
        match self.first_header_value(py, &key)? {
            Some(value) => decode_header_component(value.bind(py)),
            None => Ok(default.unwrap_or_else(|| py.None())),
        }
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let normalized = normalized_key(key)?;
        match self.first_header_value(py, &normalized)? {
            Some(value) => decode_header_component(value.bind(py)),
            None => Err(PyKeyError::new_err(key.clone().unbind())),
        }
    }

    fn __contains__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        let normalized = normalized_key(key)?;
        Ok(self.first_header_value(py, &normalized)?.is_some())
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        PyList::new(py, self.keys(py)?)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        self.raw.bind(py).len()
    }

    fn repr(&self, py: Python<'_>, class_name: &str) -> PyResult<String> {
        let length = self.raw.bind(py).len()?;
        let items = self.header_items(py)?;
        let mapping = PyDict::new(py);
        for (key, value) in items {
            mapping.set_item(key.bind(py), value.bind(py))?;
        }
        if mapping.len() == length {
            return Ok(format!("{class_name}({})", mapping.repr()?.to_str()?));
        }
        let raw = if self.mutable {
            self.raw.bind(py).clone()
        } else {
            py.import("builtins")?
                .getattr("list")?
                .call1((self.raw.bind(py),))?
        };
        Ok(format!("{class_name}(raw={})", raw.repr()?.to_str()?))
    }

    fn mutablecopy(&self, py: Python<'_>) -> PyResult<Self> {
        let length = self.raw.bind(py).len()?;
        let length = isize::try_from(length).map_err(|error| {
            PyOverflowError::new_err(format!("header sequence length is not indexable: {error}"))
        })?;
        let slice = PySlice::new(py, 0, length, 1);
        let raw = self.raw.bind(py).get_item(slice)?;
        Ok(Self {
            raw: raw.unbind(),
            mutable: true,
        })
    }

    fn set(
        &mut self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let key = normalized_key(key)?;
        let value = encoded_latin1(value)?;
        let mut matching = Vec::new();
        for (index, pair) in self.raw.bind(py).try_iter()?.enumerate() {
            let (name, _value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            if header_key_matches(py, name.bind(py), &key)? {
                matching.push(index);
            }
        }
        let replacement = raw_pair(py, &(key, value))?;
        if let Some(first) = matching.first().copied() {
            for index in matching.iter().skip(1).rev() {
                self.raw.bind(py).call_method1("__delitem__", (index,))?;
            }
            self.raw
                .bind(py)
                .call_method1("__setitem__", (first, replacement))?;
        } else {
            self.raw.bind(py).call_method1("append", (replacement,))?;
        }
        Ok(())
    }

    fn delete(&mut self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<()> {
        let key = normalized_key(key)?;
        let mut matching = Vec::new();
        for (index, pair) in self.raw.bind(py).try_iter()?.enumerate() {
            let (name, _value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            if header_key_matches(py, name.bind(py), &key)? {
                matching.push(index);
            }
        }
        for index in matching.iter().rev() {
            self.raw.bind(py).call_method1("__delitem__", (index,))?;
        }
        Ok(())
    }

    fn setdefault(
        &mut self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let key = normalized_key(key)?;
        let encoded_value = encoded_latin1(value)?;
        if let Some(existing) = self.first_header_value(py, &key)? {
            return decode_header_component(existing.bind(py));
        }
        let new_pair = raw_pair(py, &(key, encoded_value))?;
        self.raw.bind(py).call_method1("append", (new_pair,))?;
        Ok(value.clone().unbind())
    }

    fn append(
        &mut self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        let key = normalized_key(key)?;
        let value = encoded_latin1(value)?;
        let mut headers = NativeMutableHeaders::new();
        headers.append(&key, &value);
        let pair = raw_pair(
            py,
            headers
                .raw_pairs()
                .first()
                .ok_or_else(|| PyOverflowError::new_err("append produced no raw pair"))?,
        )?;
        self.raw.bind(py).call_method1("append", (pair,))?;
        Ok(())
    }

    fn update(&mut self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<()> {
        let items = other.call_method0("items")?;
        for pair in items.try_iter()? {
            let (key, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            self.set(py, key.bind(py), value.bind(py))?;
        }
        Ok(())
    }

    fn add_vary_header(&mut self, py: Python<'_>, vary: &Bound<'_, PyAny>) -> PyResult<()> {
        let existing = self.get(py, PyString::new(py, "vary").as_any(), None)?;
        let value = if existing.bind(py).is_none() {
            vary.clone()
        } else {
            let values = PyList::new(py, [existing.bind(py), vary])?;
            PyString::new(py, ", ")
                .call_method1("join", (values,))?
                .into_any()
        };
        self.set(py, PyString::new(py, "vary").as_any(), &value)
    }

    fn union(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<Self> {
        ensure_mapping(py, other)?;
        let mut result = self.mutablecopy(py)?;
        result.update(py, other)?;
        Ok(result)
    }

    fn inplace_union(&mut self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<()> {
        ensure_mapping(py, other)?;
        self.update(py, other)
    }

    fn _raw_pairs(&self, py: Python<'_>) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
        self.raw_pairs(py)
    }
}

#[pyfunction(name = "_headers_equal")]
fn headers_equal(
    py: Python<'_>,
    left: PyRef<'_, PyHeadersStore>,
    right: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let headers_type = py.import("starlette.datastructures")?.getattr("Headers")?;
    if !right.is_instance(&headers_type)? {
        return Ok(false);
    }
    let right_raw = right
        .getattr("_inner")?
        .call_method0("_raw_pairs")?
        .extract::<Vec<(Vec<u8>, Vec<u8>)>>()?;
    let left = NativeHeaders::from_raw(left.raw_pairs(py)?);
    Ok(left == NativeHeaders::from_raw(right_raw))
}

impl PyHeadersStore {
    fn raw_pairs(&self, py: Python<'_>) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
        self.raw
            .bind(py)
            .try_iter()?
            .map(|pair| pair?.extract::<(Vec<u8>, Vec<u8>)>())
            .collect()
    }

    /// Reads only as far as the pinned operation does before its first match.
    ///
    /// Starlette's mapping lookup methods iterate the live Python list and
    /// return immediately on a match. Parsing the full list first would make a
    /// malformed later entry observable even though upstream never inspects
    /// it. Keep iteration and conversion on the Rust side while retaining that
    /// short-circuit behavior.
    fn first_header_value(&self, py: Python<'_>, key: &[u8]) -> PyResult<Option<Py<PyAny>>> {
        for pair in self.raw.bind(py).try_iter()? {
            let (name, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            if header_key_matches(py, name.bind(py), key)? {
                return Ok(Some(value));
            }
        }
        Ok(None)
    }

    fn header_names(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let mut names = Vec::new();
        for pair in self.raw.bind(py).try_iter()? {
            let (name, _) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            names.push(decode_header_component(name.bind(py))?);
        }
        Ok(names)
    }

    fn header_values(&self, py: Python<'_>) -> PyResult<Vec<Py<PyAny>>> {
        let mut values = Vec::new();
        for pair in self.raw.bind(py).try_iter()? {
            let (_, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            values.push(decode_header_component(value.bind(py))?);
        }
        Ok(values)
    }

    fn header_items(&self, py: Python<'_>) -> PyResult<Vec<(Py<PyAny>, Py<PyAny>)>> {
        let mut items = Vec::new();
        for pair in self.raw.bind(py).try_iter()? {
            let (name, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            items.push((
                decode_header_component(name.bind(py))?,
                decode_header_component(value.bind(py))?,
            ));
        }
        Ok(items)
    }
}

fn header_key_matches(py: Python<'_>, name: &Bound<'_, PyAny>, key: &[u8]) -> PyResult<bool> {
    name.rich_compare(PyBytes::new(py, key), CompareOp::Eq)?
        .is_truthy()
}

fn decode_header_component(value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    value
        .call_method1("decode", ("latin-1",))
        .map(Bound::unbind)
}

fn mapping_pairs(py: Python<'_>, mapping: &Bound<'_, PyAny>) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
    let items = mapping.call_method0("items")?;
    items
        .try_iter()?
        .map(|pair| {
            let (key, value) = pair?.extract::<(Py<PyAny>, Py<PyAny>)>()?;
            Ok((
                normalized_key(key.bind(py))?,
                encoded_latin1(value.bind(py))?,
            ))
        })
        .collect()
}

fn raw_pair_list<'py>(
    py: Python<'py>,
    pairs: &[(Vec<u8>, Vec<u8>)],
) -> PyResult<Bound<'py, PyList>> {
    let output = PyList::empty(py);
    for (key, value) in pairs {
        let key = PyBytes::new(py, key);
        let value = PyBytes::new(py, value);
        output.append(PyTuple::new(py, [key, value])?)?;
    }
    Ok(output)
}

fn raw_pair<'py>(py: Python<'py>, pair: &(Vec<u8>, Vec<u8>)) -> PyResult<Bound<'py, PyTuple>> {
    PyTuple::new(py, [PyBytes::new(py, &pair.0), PyBytes::new(py, &pair.1)])
}

fn normalized_key(value: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let lowered = value.call_method0("lower")?;
    encoded_latin1(&lowered)
}

fn encoded_latin1(value: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    value
        .call_method1("encode", ("latin-1",))?
        .extract::<Vec<u8>>()
}

fn ensure_mapping(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<()> {
    let mapping = py.import("collections.abc")?.getattr("Mapping")?;
    if value.is_instance(&mapping)? {
        return Ok(());
    }
    let name = value.get_type().name()?;
    Err(PyTypeError::new_err(format!(
        "Expected a mapping but got {name}"
    )))
}
