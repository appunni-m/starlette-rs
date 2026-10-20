//! PyO3 namespace and native header storage used by the Starlette FileResponse facade.
//!
//! The facade routes file stat and ASGI streaming through `file_object_runtime`
//! and `file_stream_runtime`; this module provides its range helpers and maps
//! native file errors at the Python boundary.

use std::path::PathBuf;

use pyo3::exceptions::{
    PyFileNotFoundError, PyIsADirectoryError, PyKeyError, PyOSError, PyOverflowError,
    PyPermissionError, PyRuntimeError, PyUnicodeEncodeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule};
use starlette_rs::{
    FileResponse as NativeFileResponse, FileResponseError, FileResponseOptions, ResponseError,
};

use crate::cookie_runtime;

/// Registers the `FileResponse` PyO3 type.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyFileResponse>()
}

#[pyclass(name = "FileResponse")]
struct PyFileResponse {
    inner: NativeFileResponse,
    raw_headers: Py<PyAny>,
    headers_view: Option<Py<PyAny>>,
}

#[pymethods]
impl PyFileResponse {
    fn __traverse__(
        &self,
        visit: pyo3::class::gc::PyVisit<'_>,
    ) -> Result<(), pyo3::class::gc::PyTraverseError> {
        visit.call(&self.raw_headers)?;
        visit.call(&self.headers_view)
    }

    fn __clear__(&mut self, py: Python<'_>) {
        self.raw_headers = PyList::empty(py).into_any().unbind();
        self.headers_view = None;
    }

    #[staticmethod]
    fn call_for(
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
        scope: &Bound<'_, PyAny>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        crate::file_object_runtime::call(
            py,
            response.clone().unbind(),
            scope.clone().unbind(),
            receive,
            send,
        )
    }

    #[staticmethod]
    fn should_use_range(response: &Bound<'_, PyAny>, value: &Bound<'_, PyAny>) -> PyResult<bool> {
        crate::file_range_runtime::should_use_range(response, value)
    }

    #[staticmethod]
    fn parse_ranges(
        py: Python<'_>,
        text: &Bound<'_, PyAny>,
        size: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        crate::file_range_runtime::parse_ranges(py, text, size)
            .map(|ranges| ranges.into_any().unbind())
    }

    #[staticmethod]
    fn parse_range_header(
        py: Python<'_>,
        class: &Bound<'_, PyAny>,
        header: &Bound<'_, PyAny>,
        size: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        crate::file_range_runtime::parse_header(py, class, header, size)
    }

    #[staticmethod]
    fn generate_multipart(
        py: Python<'_>,
        ranges: &Bound<'_, PyAny>,
        boundary: String,
        size: &Bound<'_, PyAny>,
        content_type: String,
    ) -> PyResult<Py<PyAny>> {
        crate::file_range_runtime::multipart(py, ranges, boundary, size, content_type)
    }

    #[staticmethod]
    fn handle_simple(
        py: Python<'_>,
        response: Py<PyAny>,
        send: Py<PyAny>,
        header_only: bool,
        pathsend: bool,
    ) -> PyResult<Py<PyAny>> {
        crate::file_stream_runtime::handler(
            py,
            response,
            send,
            header_only,
            crate::file_stream_runtime::BodyKind::Simple(pathsend),
        )
    }

    #[staticmethod]
    fn handle_single_range(
        py: Python<'_>,
        response: Py<PyAny>,
        send: Py<PyAny>,
        range: &Bound<'_, PyAny>,
        header_only: bool,
    ) -> PyResult<Py<PyAny>> {
        crate::file_stream_runtime::handler(
            py,
            response,
            send,
            header_only,
            crate::file_stream_runtime::BodyKind::Single(
                range.get_item(0)?.unbind(),
                range.get_item(1)?.unbind(),
                range.get_item(2)?.unbind(),
            ),
        )
    }

    #[staticmethod]
    fn handle_multiple_ranges(
        py: Python<'_>,
        response: Py<PyAny>,
        send: Py<PyAny>,
        ranges: Py<PyAny>,
        size: Py<PyAny>,
        header_only: bool,
    ) -> PyResult<Py<PyAny>> {
        crate::file_stream_runtime::handler(
            py,
            response,
            send,
            header_only,
            crate::file_stream_runtime::BodyKind::Multiple(ranges, size),
        )
    }

    #[staticmethod]
    fn prepare_for(py: Python<'_>, response: &Bound<'_, PyAny>) -> PyResult<()> {
        // Construction must not coerce a PathLike or stat object before the
        // source uses it. This native storage is filled at ASGI call time.
        let inner = NativeFileResponse::new(
            PathBuf::new(),
            String::new(),
            200,
            &[],
            FileResponseOptions::default(),
        )
        .map_err(|error| file_response_error(py, error))?;
        let object = py.get_type::<PyAny>();
        let raw_headers = PyList::empty(py).into_any().unbind();
        let headers_view = None;
        let native = Py::new(
            py,
            Self {
                inner,
                raw_headers,
                headers_view,
            },
        )?;
        object.call_method1("__setattr__", (response, "_inner", native))?;
        Ok(())
    }

    #[getter]
    fn headers(&mut self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        if let Some(headers) = self.headers_view.as_ref() {
            return Ok(headers.clone_ref(py));
        }
        let headers = crate::response_headers_runtime::view(py, self.raw_headers.bind(py))?;
        self.headers_view = Some(headers.clone_ref(py));
        Ok(headers)
    }

    #[getter]
    fn raw_headers(&self, py: Python<'_>) -> Py<PyAny> {
        self.raw_headers.clone_ref(py)
    }

    #[setter]
    fn set_raw_headers(&mut self, headers: Py<PyAny>) {
        self.raw_headers = headers;
    }

    fn _header_get(&self, key: &str) -> PyResult<Option<String>> {
        self.inner.get_header(key).map_err(response_error)
    }

    fn _header_set(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.set_header(key, value).map_err(response_error)
    }

    fn _header_delete(&mut self, key: &str) -> PyResult<()> {
        self.inner.delete_header(key).map_err(response_error)
    }

    fn _header_append(&mut self, key: &str, value: &str) -> PyResult<()> {
        self.inner.append_header(key, value).map_err(response_error)
    }

    fn _header_values(&self, key: &str) -> PyResult<Vec<String>> {
        self.inner.get_header_values(key).map_err(response_error)
    }

    fn _header_items(&self) -> Vec<(String, String)> {
        crate::response_headers_runtime::items(self.inner.headers())
    }

    fn _header_raw(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        crate::response_headers_runtime::raw_pairs(py, self.inner.headers())
    }

    fn _header_replace_raw(&mut self, raw: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner
            .replace_headers_raw(crate::response_headers_runtime::parse_raw_pairs(raw)?);
        Ok(())
    }

    fn _header_refresh_raw(&self, py: Python<'_>) -> PyResult<()> {
        crate::response_headers_runtime::refresh_raw_pairs(
            py,
            self.raw_headers.bind(py),
            self.inner.headers(),
        )
    }

    fn _header_len(&self) -> usize {
        self.inner.headers().len()
    }
}

/// Request facts selected by the Rust facade before stat/header callbacks.
pub(crate) struct PublicFileFacts {
    pub(crate) header_only: bool,
    pub(crate) pathsend: bool,
}

pub(crate) fn file_response_error(py: Python<'_>, error: FileResponseError) -> PyErr {
    match error {
        FileResponseError::MissingFile(path) => {
            PyRuntimeError::new_err(format!("File at path {path} does not exist."))
        }
        FileResponseError::NotAFile(path) => {
            PyRuntimeError::new_err(format!("File at path {path} is not a file."))
        }
        FileResponseError::MissingContentType => PyKeyError::new_err("content-type"),
        // u128 preserves Python's unbounded multipart Content-Length for every
        // addressable input; this fallback covers only unrepresentable internal
        // lengths or invalid range invariants.
        FileResponseError::ArithmeticOverflow => {
            PyOverflowError::new_err("file response arithmetic overflow")
        }
        FileResponseError::StatIo(error) => io_error(error),
        FileResponseError::HeaderDataIsNotLatin1 { value, index } => match index.checked_add(1) {
            Some(end) => PyUnicodeEncodeError::new_err((
                "latin-1",
                value,
                index,
                end,
                "ordinal not in range(256)",
            )),
            None => PyOverflowError::new_err("Unicode encoding error index overflow"),
        },
        FileResponseError::InvalidTimestamp => {
            PyValueError::new_err("invalid file modification timestamp")
        }
        FileResponseError::TimestampYearOutOfRange(year) => {
            PyValueError::new_err(if py.version_info() >= (3, 14) {
                format!("year must be in 1..9999, not {year}")
            } else {
                format!("year {year} is out of range")
            })
        }
        FileResponseError::RandomSource => {
            PyRuntimeError::new_err("could not generate multipart range boundary")
        }
    }
}

fn io_error(error: std::io::Error) -> PyErr {
    match error.kind() {
        std::io::ErrorKind::NotFound => PyFileNotFoundError::new_err(error.to_string()),
        std::io::ErrorKind::PermissionDenied => PyPermissionError::new_err(error.to_string()),
        std::io::ErrorKind::IsADirectory => PyIsADirectoryError::new_err(error.to_string()),
        _ => PyOSError::new_err(error.to_string()),
    }
}

fn response_error(error: ResponseError) -> PyErr {
    cookie_runtime::response_error(error)
}
