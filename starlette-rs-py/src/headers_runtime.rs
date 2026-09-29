//! PyO3 boundary for Starlette's public `Headers` and `MutableHeaders` types.
//!
//! The ordered header semantics live in `starlette-rs`. This module converts
//! Python strings and byte-pair sequences, keeps the Python list identity
//! required by `MutableHeaders.raw` and `scope["headers"]`, and forwards the
//! public operations to the native types.

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

    fn keys(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self.headers(py)?.keys())
    }

    fn values(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self.headers(py)?.values())
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(String, String)>> {
        Ok(self.headers(py)?.items())
    }

    fn getlist(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Vec<String>> {
        let key = normalized_key(key)?;
        self.headers(py)?
            .get_list(&key)
            .into_iter()
            .map(|value| Ok(decode_latin1(py, value)?.to_str()?.to_owned()))
            .collect()
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
        default: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let key = normalized_key(key)?;
        match self.headers(py)?.get(&key) {
            Some(value) => decode_latin1(py, value).map(|value| value.into_any().unbind()),
            None => Ok(default.unwrap_or_else(|| py.None())),
        }
    }

    fn __getitem__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let normalized = normalized_key(key)?;
        match self.headers(py)?.get(&normalized) {
            Some(value) => decode_latin1(py, value).map(|value| value.into_any().unbind()),
            None => Err(PyKeyError::new_err(key.clone().unbind())),
        }
    }

    fn __contains__(&self, py: Python<'_>, key: &Bound<'_, PyAny>) -> PyResult<bool> {
        let normalized = normalized_key(key)?;
        Ok(self.headers(py)?.contains_key(&normalized))
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
        let headers = self.headers(py)?;
        let mapping = PyDict::new(py);
        for (key, value) in headers.items() {
            mapping.set_item(key, value)?;
        }
        if mapping.len() == headers.len() {
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
        let mut headers = self.mutable_headers(py)?;
        let matching: Vec<usize> = headers
            .raw_pairs()
            .iter()
            .enumerate()
            .filter_map(|(index, (name, _))| (name == &key).then_some(index))
            .collect();
        headers.set(&key, &value);
        let replacement = headers
            .raw_pairs()
            .get(
                matching
                    .first()
                    .copied()
                    .unwrap_or(headers.raw_pairs().len() - 1),
            )
            .ok_or_else(|| PyOverflowError::new_err("header set produced no raw pair"))?;
        let replacement = raw_pair(py, replacement)?;
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
        let mut headers = self.mutable_headers(py)?;
        let matching: Vec<usize> = headers
            .raw_pairs()
            .iter()
            .enumerate()
            .filter_map(|(index, (name, _))| (name == &key).then_some(index))
            .collect();
        headers.delete(&key);
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
        let mut headers = self.mutable_headers(py)?;
        if let Some(existing) = headers.get(&key) {
            return Ok(decode_latin1(py, existing)?.into_any().unbind());
        }
        headers.setdefault(&key, &encoded_value);
        let new_pair = raw_pair(
            py,
            headers
                .raw_pairs()
                .last()
                .ok_or_else(|| PyOverflowError::new_err("setdefault produced no raw pair"))?,
        )?;
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

    fn headers(&self, py: Python<'_>) -> PyResult<NativeHeaders> {
        Ok(NativeHeaders::from_raw(self.raw_pairs(py)?))
    }

    fn mutable_headers(&self, py: Python<'_>) -> PyResult<NativeMutableHeaders> {
        Ok(NativeMutableHeaders::from_raw(self.raw_pairs(py)?))
    }
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

fn decode_latin1<'py>(py: Python<'py>, value: &[u8]) -> PyResult<Bound<'py, PyString>> {
    let decoded: String = value.iter().copied().map(char::from).collect();
    Ok(PyString::new(py, &decoded))
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
