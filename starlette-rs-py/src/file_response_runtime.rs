//! PyO3 bridge for the Rust-owned file response state machine.

use std::path::PathBuf;

use pyo3::exceptions::{
    PyFileNotFoundError, PyIsADirectoryError, PyOSError, PyPermissionError, PyRuntimeError,
    PyUnicodeEncodeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyTuple};
use starlette_rs::{
    FileMetadata, FileResponse as NativeFileResponse, FileResponseCall, FileResponseCallError,
    FileResponseCallInput, FileResponseCallStep, FileResponseError, FileResponseEvent,
    FileResponseHeaderViews, FileResponseOptions, ResponseError,
};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};
use crate::cookie_runtime;
use crate::runtime_calls::header_pairs;

/// Registers the `FileResponse` PyO3 type.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyFileResponse>()
}

#[pyclass(name = "FileResponse", unsendable)]
struct PyFileResponse {
    inner: NativeFileResponse,
    raw_headers: Py<PyAny>,
    headers_view: Option<Py<PyAny>>,
}

#[pymethods]
impl PyFileResponse {
    #[new]
    #[pyo3(signature = (path, status_code=200, headers=None, media_type=None, filename=None, stat_result=None, content_disposition_type="attachment", chunk_size=65536, max_ranges=100))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        path: Py<PyAny>,
        status_code: u16,
        headers: Option<Py<PyAny>>,
        media_type: Option<String>,
        filename: Option<String>,
        stat_result: Option<Py<PyAny>>,
        content_disposition_type: &str,
        chunk_size: usize,
        max_ranges: usize,
    ) -> PyResult<Self> {
        let path = path.bind(py);
        let native_path = path_from_python(path)?;
        let display_path = path.str()?.to_str()?.to_owned();
        let header_pairs = header_pairs(py, headers)?;
        let stat_override = stat_metadata(py, stat_result)?;
        let inner = NativeFileResponse::new(
            native_path,
            display_path,
            status_code,
            &header_pairs,
            FileResponseOptions {
                media_type,
                filename,
                stat_override,
                content_disposition_type: content_disposition_type.to_owned(),
                chunk_size,
                max_ranges,
            },
        )
        .map_err(file_response_error)?;
        let raw_headers = crate::response_headers_runtime::raw_pairs(py, inner.headers())?;
        let headers_view = crate::response_headers_runtime::view(py, raw_headers.bind(py))?;
        Ok(Self {
            inner,
            raw_headers,
            headers_view: Some(headers_view),
        })
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

    #[getter]
    fn media_type(&self) -> String {
        self.inner.media_type().to_owned()
    }

    fn set_streaming_options(&mut self, chunk_size: usize, max_ranges: usize) {
        self.inner.set_streaming_options(chunk_size, max_ranges);
    }

    #[pyo3(signature = (key, value="", max_age=None, expires=None, path="/", domain=None, secure=false, httponly=false, samesite="lax", partitioned=false))]
    #[allow(clippy::too_many_arguments)]
    fn set_cookie(
        &mut self,
        py: Python<'_>,
        key: &str,
        value: &str,
        max_age: Option<Py<PyAny>>,
        expires: Option<Py<PyAny>>,
        path: Option<&str>,
        domain: Option<&str>,
        secure: bool,
        httponly: bool,
        samesite: Option<&str>,
        partitioned: bool,
    ) -> PyResult<()> {
        let options = cookie_runtime::options_from_python(
            py,
            max_age,
            expires,
            path.map(str::to_owned),
            domain.map(str::to_owned),
            secure,
            httponly,
            samesite.map(str::to_owned),
            partitioned,
        )?;
        self.inner
            .set_cookie_with_options(key, value, &options)
            .map_err(response_error)
    }

    #[pyo3(signature = (key, path="/", domain=None, secure=false, httponly=false, samesite="lax"))]
    #[allow(clippy::too_many_arguments)]
    fn delete_cookie(
        &mut self,
        py: Python<'_>,
        key: &str,
        path: Option<&str>,
        domain: Option<&str>,
        secure: bool,
        httponly: bool,
        samesite: Option<&str>,
    ) -> PyResult<()> {
        let (expires, options) = cookie_runtime::delete_options_from_python(
            py,
            path.map(str::to_owned),
            domain.map(str::to_owned),
            secure,
            httponly,
            samesite.map(str::to_owned),
        )?;
        self.inner
            .delete_cookie_with_options(key, &expires, &options)
            .map_err(response_error)
    }

    fn asgi_call(
        &mut self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        background: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyValueError::new_err("ASGI scope is missing 'type'"))?
            .extract::<String>()?;
        let method = if scope_type == "http" {
            scope
                .get_item("method")?
                .ok_or_else(|| PyValueError::new_err("ASGI HTTP scope is missing 'method'"))?
                .extract::<String>()?
        } else {
            String::new()
        };
        let request_headers = scope
            .get_item("headers")?
            .map(|value| value.extract::<Vec<(Vec<u8>, Vec<u8>)>>())
            .transpose()?
            .unwrap_or_default();
        let pathsend_extension = match scope.get_item("extensions")? {
            Some(extensions) => extensions.contains("http.response.pathsend")?,
            None => false,
        };
        let headers_view = self.headers(py)?;
        let view_raw = headers_view.bind(py).getattr("raw")?;
        let view_headers = crate::response_headers_runtime::parse_raw_pairs(&view_raw)?;
        let raw_headers =
            crate::response_headers_runtime::parse_raw_pairs(self.raw_headers.bind(py))?;
        let view_is_raw = view_raw.is(self.raw_headers.bind(py));
        let call = self
            .inner
            .call_state_with_headers(
                FileResponseHeaderViews {
                    view: view_headers,
                    raw: raw_headers,
                    view_is_raw,
                },
                &scope_type,
                &method,
                &request_headers,
                pathsend_extension,
                background.is_some(),
            )
            .map_err(file_response_error)?;
        crate::response_headers_runtime::refresh_raw_pairs(py, &view_raw, call.base_headers())?;
        into_python_awaitable(
            py,
            FileResponseMachine {
                call,
                send,
                _receive: receive,
                background,
                websocket: scope_type == "websocket",
                pending: None,
            },
        )
    }
}

struct FileResponseMachine {
    call: FileResponseCall,
    send: Py<PyAny>,
    _receive: Py<PyAny>,
    background: Option<Py<PyAny>>,
    websocket: bool,
    pending: Option<FileResponsePending>,
}

enum FileResponsePending {
    Send,
    Background,
}

impl AwaitableStateMachine for FileResponseMachine {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(_) => {
                match self.pending.take() {
                    Some(FileResponsePending::Send) => {
                        self.advance(FileResponseCallInput::Send(Ok(())))?;
                    }
                    Some(FileResponsePending::Background) => {
                        self.advance(FileResponseCallInput::BackgroundFinished(Ok(())))?;
                    }
                    None => {
                        return Err(PyRuntimeError::new_err(
                            "no file response operation is pending",
                        ));
                    }
                }
                self.next_action(py)
            }
            MachineResume::AsyncIterationComplete(_) => Err(PyRuntimeError::new_err(
                "file response unexpectedly received async-iteration completion",
            )),
            MachineResume::Error(error) => {
                match self.pending.take() {
                    Some(FileResponsePending::Send) => {
                        self.advance(FileResponseCallInput::Send(Err(error)))?;
                    }
                    Some(FileResponsePending::Background) => {
                        self.advance(FileResponseCallInput::BackgroundFinished(Err(error)))?;
                    }
                    None => return Err(error),
                }
                Err(PyRuntimeError::new_err(
                    "file response operation failed without an error",
                ))
            }
        }
    }
}

impl FileResponseMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.call.step().map_err(io_error)? {
            FileResponseCallStep::Send(event) => {
                self.pending = Some(FileResponsePending::Send);
                let message = file_response_event_to_py(py, event, self.websocket)?;
                let awaitable = self.send.bind(py).call1((message,))?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            FileResponseCallStep::RunBackground => {
                self.pending = Some(FileResponsePending::Background);
                let callback = self.background.as_ref().ok_or_else(|| {
                    PyRuntimeError::new_err("file response requested a missing background callback")
                })?;
                let awaitable = callback.bind(py).call0()?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            FileResponseCallStep::Complete => Ok(MachineAction::Complete(py.None())),
            FileResponseCallStep::Failed => Err(PyRuntimeError::new_err(
                "file response call is already failed",
            )),
        }
    }

    fn advance(&mut self, input: FileResponseCallInput<PyErr>) -> PyResult<()> {
        self.call.advance(input).map_err(|error| match error {
            FileResponseCallError::Operation(error) => error,
            FileResponseCallError::UnexpectedInput => {
                PyRuntimeError::new_err("unexpected file response operation result")
            }
        })
    }
}

fn path_from_python(path: &Bound<'_, PyAny>) -> PyResult<PathBuf> {
    let filesystem_path = path.py().import("os")?.call_method1("fspath", (path,))?;
    if let Ok(path) = filesystem_path.extract::<String>() {
        return Ok(PathBuf::from(path));
    }
    #[cfg(unix)]
    {
        use std::ffi::OsString;
        use std::os::unix::ffi::OsStringExt;

        let bytes = filesystem_path.cast::<PyBytes>()?;
        Ok(PathBuf::from(OsString::from_vec(bytes.as_bytes().to_vec())))
    }
    #[cfg(not(unix))]
    {
        Err(pyo3::exceptions::PyTypeError::new_err(
            "path must be str or path-like",
        ))
    }
}

fn stat_metadata(py: Python<'_>, value: Option<Py<PyAny>>) -> PyResult<Option<FileMetadata>> {
    value
        .map(|value| {
            let stat_result = value.bind(py);
            let size = stat_result.getattr("st_size")?.extract::<u64>()?;
            let modified = stat_result.getattr("st_mtime")?;
            let seconds = modified.extract::<f64>()?;
            let text = modified.str()?.to_str()?.to_owned();
            FileMetadata::from_unix_seconds(size, seconds, text).map_err(file_response_error)
        })
        .transpose()
}

fn file_response_event_to_py<'py>(
    py: Python<'py>,
    event: FileResponseEvent,
    websocket: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let message = PyDict::new(py);
    match event {
        FileResponseEvent::Start {
            status_code,
            headers,
        } => {
            message.set_item("type", event_name("http.response.start", websocket))?;
            message.set_item("status", status_code)?;
            message.set_item("headers", headers_to_py(py, headers)?)?;
        }
        FileResponseEvent::Body { body, more_body } => {
            message.set_item("type", event_name("http.response.body", websocket))?;
            message.set_item("body", PyBytes::new(py, &body))?;
            if let Some(more_body) = more_body {
                message.set_item("more_body", more_body)?;
            }
        }
        FileResponseEvent::Pathsend { path } => {
            message.set_item("type", "http.response.pathsend")?;
            message.set_item("path", path)?;
        }
    }
    Ok(message)
}

fn headers_to_py<'py>(
    py: Python<'py>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
) -> PyResult<Bound<'py, PyList>> {
    let output = PyList::empty(py);
    for (name, value) in headers {
        output.append(PyTuple::new(
            py,
            [PyBytes::new(py, &name), PyBytes::new(py, &value)],
        )?)?;
    }
    Ok(output)
}

fn event_name(name: &str, websocket: bool) -> String {
    if websocket {
        format!("websocket.{name}")
    } else {
        name.to_owned()
    }
}

fn file_response_error(error: FileResponseError) -> PyErr {
    match error {
        FileResponseError::MissingFile(path) => {
            PyRuntimeError::new_err(format!("File at path {path} does not exist."))
        }
        FileResponseError::NotAFile(path) => {
            PyRuntimeError::new_err(format!("File at path {path} is not a file."))
        }
        FileResponseError::StatIo(error) => io_error(error),
        FileResponseError::HeaderDataIsNotLatin1 { value, index } => {
            PyUnicodeEncodeError::new_err((
                "latin-1",
                value,
                index,
                index + 1,
                "ordinal not in range(256)",
            ))
        }
        FileResponseError::InvalidTimestamp => {
            PyValueError::new_err("invalid file modification timestamp")
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
