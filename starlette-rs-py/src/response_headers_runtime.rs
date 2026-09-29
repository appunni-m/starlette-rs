//! Mutable response-header views backed by Rust response objects.

use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList, PyModule, PyTuple};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyResponseHeaders>()
}

pub(crate) fn view(py: Python<'_>, inner: Py<PyAny>) -> PyResult<Py<PyAny>> {
    Py::new(py, PyResponseHeaders { inner }).map(Py::into_any)
}

pub(crate) fn items(headers: &[(Vec<u8>, Vec<u8>)]) -> Vec<(String, String)> {
    headers
        .iter()
        .map(|(name, value)| (decode_latin1(name), decode_latin1(value)))
        .collect()
}

pub(crate) fn raw_pairs(py: Python<'_>, headers: &[(Vec<u8>, Vec<u8>)]) -> PyResult<Py<PyAny>> {
    let output = PyList::empty(py);
    for (name, value) in headers {
        output.append(PyTuple::new(
            py,
            [PyBytes::new(py, name), PyBytes::new(py, value)],
        )?)?;
    }
    Ok(output.into_any().unbind())
}

pub(crate) fn parse_raw_pairs(raw: &Bound<'_, PyAny>) -> PyResult<Vec<(Vec<u8>, Vec<u8>)>> {
    raw.try_iter()?
        .map(|pair| pair?.extract::<(Vec<u8>, Vec<u8>)>())
        .collect()
}

fn decode_latin1(value: &[u8]) -> String {
    value.iter().copied().map(char::from).collect()
}

#[pyclass(name = "_MutableHeadersView")]
struct PyResponseHeaders {
    inner: Py<PyAny>,
}

#[pymethods]
impl PyResponseHeaders {
    fn __getitem__(&self, py: Python<'_>, key: &str) -> PyResult<String> {
        self.get_value(py, key)?
            .ok_or_else(|| PyKeyError::new_err(key.to_owned()))
    }

    fn __setitem__(&self, py: Python<'_>, key: &str, value: &str) -> PyResult<()> {
        self.inner
            .bind(py)
            .call_method1("_header_set", (key, value))?;
        Ok(())
    }

    fn __delitem__(&self, py: Python<'_>, key: &str) -> PyResult<()> {
        let existed = self.get_value(py, key)?.is_some();
        if !existed {
            return Err(PyKeyError::new_err(key.to_owned()));
        }
        self.inner.bind(py).call_method1("_header_delete", (key,))?;
        Ok(())
    }

    fn __contains__(&self, py: Python<'_>, key: &str) -> PyResult<bool> {
        Ok(self.get_value(py, key)?.is_some())
    }

    fn __iter__(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        PyList::new(py, self.keys(py)?)?
            .call_method0("__iter__")
            .map(Bound::unbind)
    }

    fn __len__(&self, py: Python<'_>) -> PyResult<usize> {
        self.inner
            .bind(py)
            .call_method0("_header_len")?
            .extract::<usize>()
    }

    fn keys(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self.items(py)?.into_iter().map(|(key, _)| key).collect())
    }

    fn values(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        Ok(self
            .items(py)?
            .into_iter()
            .map(|(_, value)| value)
            .collect())
    }

    fn items(&self, py: Python<'_>) -> PyResult<Vec<(String, String)>> {
        self.inner
            .bind(py)
            .call_method0("_header_items")?
            .extract::<Vec<(String, String)>>()
    }

    #[getter]
    fn raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.inner
            .bind(py)
            .call_method0("_header_raw")
            .map(Bound::unbind)
    }

    #[pyo3(signature = (key, default=None))]
    fn get(&self, py: Python<'_>, key: &str, default: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        match self.get_value(py, key)? {
            Some(value) => Ok(value.into_pyobject(py)?.into_any().unbind()),
            None => Ok(default.unwrap_or_else(|| py.None())),
        }
    }

    fn getlist(&self, py: Python<'_>, key: &str) -> PyResult<Vec<String>> {
        self.inner
            .bind(py)
            .call_method1("_header_values", (key,))?
            .extract::<Vec<String>>()
    }

    fn append(&self, py: Python<'_>, key: &str, value: &str) -> PyResult<()> {
        self.inner
            .bind(py)
            .call_method1("_header_append", (key, value))?;
        Ok(())
    }

    fn setdefault(&self, py: Python<'_>, key: &str, value: &str) -> PyResult<String> {
        if let Some(existing) = self.get_value(py, key)? {
            return Ok(existing);
        }
        self.__setitem__(py, key, value)?;
        Ok(value.to_owned())
    }

    fn update(&self, py: Python<'_>, other: &Bound<'_, PyAny>) -> PyResult<()> {
        let pairs = other
            .call_method0("items")?
            .extract::<Vec<(String, String)>>()?;
        for (key, value) in pairs {
            self.__setitem__(py, &key, &value)?;
        }
        Ok(())
    }

    fn add_vary_header(&self, py: Python<'_>, value: &str) -> PyResult<()> {
        let joined = self.get_value(py, "vary")?.map_or_else(
            || value.to_owned(),
            |existing| format!("{existing}, {value}"),
        );
        self.__setitem__(py, "vary", &joined)
    }
}

impl PyResponseHeaders {
    fn get_value(&self, py: Python<'_>, key: &str) -> PyResult<Option<String>> {
        self.inner
            .bind(py)
            .call_method1("_header_get", (key,))?
            .extract::<Option<String>>()
    }
}
