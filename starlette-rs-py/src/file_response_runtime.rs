//! PyO3 bridge for the Rust-owned file response state machine.
//!
//! The Python task owns the event loop, so synchronous Rust filesystem steps
//! run through AnyIO's worker pool. Rust still prepares the response, owns the
//! open file, chooses each ASGI event, and advances the protocol state.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

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
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use crate::cookie_runtime;
use crate::runtime_calls::header_pairs;

/// Registers the `FileResponse` PyO3 type.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyFileResponseCallDriver>()?;
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
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let stored = py
            .get_type::<PyAny>()
            .call_method1("__getattribute__", (response, "_inner"))?;
        let inner = stored.cast::<Self>()?.try_borrow()?.inner.clone();
        // Snapshot private Rust storage, then release its borrow before every
        // public attribute lookup and user descriptor. The public cached view
        // may still refer to an older raw list after caller replacement.
        let mut native = Self {
            inner,
            raw_headers: response.getattr("raw_headers")?.unbind(),
            headers_view: Some(response.getattr("headers")?.unbind()),
        };
        native.inner.set_streaming_options(
            response.getattr("chunk_size")?.extract()?,
            response.getattr("max_ranges")?.extract()?,
        );
        let path = response.getattr("path")?.unbind();
        let status = response.getattr("status_code")?.extract()?;
        let stat = response.getattr("stat_result")?;
        let stat = (!stat.is_none()).then(|| stat.unbind());
        let background = response.getattr("background")?;
        let background = (!background.is_none()).then(|| background.unbind());
        native.asgi_call(py, scope, receive, send, background, (path, status, stat))
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
        .map_err(file_response_error)?;
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

    #[new]
    #[pyo3(signature = (path, status_code=200, headers=None, media_type=None, filename=None, stat_result=None, content_disposition_type="attachment", chunk_size=65536, max_ranges=100))]
    // LINT EXCEPTION: Preserve FileResponse's public constructor options and defaults as individual PyO3 inputs.
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
    // LINT EXCEPTION: Preserve FileResponse.set_cookie's public Python options and keyword names one-for-one.
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
    // LINT EXCEPTION: Preserve FileResponse.delete_cookie's public Python options and keyword names one-for-one.
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
        call_time_fields: (Py<PyAny>, u16, Option<Py<PyAny>>),
    ) -> PyResult<Py<PyAny>> {
        let (path, status_code, stat_result) = call_time_fields;
        let path = path.bind(py);
        let native_path = path_from_python(path)?;
        let display_path = path.str()?.to_str()?.to_owned();
        let stat_override = stat_metadata(py, stat_result)?;
        let response =
            self.inner
                .with_call_time_fields(native_path, display_path, status_code, stat_override);
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
        let driver = Py::new(
            py,
            PyFileResponseCallDriver::new(
                response,
                FileResponseHeaderViews {
                    view: view_headers,
                    raw: raw_headers,
                    view_is_raw,
                },
                scope_type.clone(),
                method,
                request_headers,
                pathsend_extension,
                background.is_some(),
                scope_type == "websocket",
            ),
        )?;
        into_sendable_python_awaitable(
            py,
            FileResponseMachine {
                driver,
                send,
                _receive: receive,
                background,
                view_raw: view_raw.unbind(),
                pending: None,
                deferred_error: None,
            },
        )
    }
}

/// Owns one response call while AnyIO schedules its synchronous Rust steps.
///
/// The mutex is shared with the AnyIO worker callback. The worker releases the
/// GIL around Rust filesystem work, then converts the selected event after it
/// returns to Python. This keeps blocking I/O off the event-loop thread without
/// moving response decisions or file state into Python.
#[pyclass(name = "_FileResponseCallDriver", frozen)]
struct PyFileResponseCallDriver {
    state: Arc<Mutex<FileResponseCallDriverState>>,
}

struct FileResponseCallDriverState {
    response: NativeFileResponse,
    header_views: FileResponseHeaderViews,
    scope_type: String,
    method: String,
    request_headers: Vec<(Vec<u8>, Vec<u8>)>,
    pathsend_extension: bool,
    has_background: bool,
    websocket: bool,
    call: Option<FileResponseCall>,
    headers_refreshed: bool,
}

struct FileResponseWorkerStep {
    step: FileResponseCallStep,
    base_headers: Vec<(Vec<u8>, Vec<u8>)>,
    refresh_headers: bool,
    websocket: bool,
}

enum FileResponseWorkerError {
    LockPoisoned,
    Preparation(FileResponseError),
    Io(std::io::Error),
}

impl PyFileResponseCallDriver {
    // LINT EXCEPTION: Keep each ASGI request fact as a separate Rust step-driver state input.
    #[allow(clippy::too_many_arguments)]
    fn new(
        response: NativeFileResponse,
        header_views: FileResponseHeaderViews,
        scope_type: String,
        method: String,
        request_headers: Vec<(Vec<u8>, Vec<u8>)>,
        pathsend_extension: bool,
        has_background: bool,
        websocket: bool,
    ) -> Self {
        Self {
            state: Arc::new(Mutex::new(FileResponseCallDriverState {
                response,
                header_views,
                scope_type,
                method,
                request_headers,
                pathsend_extension,
                has_background,
                websocket,
                call: None,
                headers_refreshed: false,
            })),
        }
    }

    fn advance(&self, input: FileResponseCallInput<PyErr>) -> PyResult<()> {
        let mut state = self
            .state
            .lock()
            .map_err(|_| PyRuntimeError::new_err("file response call state is poisoned"))?;
        let call = state
            .call
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("file response call was not prepared"))?;
        call.advance(input).map_err(|error| match error {
            FileResponseCallError::Operation(error) => error,
            FileResponseCallError::UnexpectedInput => {
                PyRuntimeError::new_err("unexpected file response operation result")
            }
        })
    }

    fn step(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let state = Arc::clone(&self.state);
        let result = py
            .detach(move || {
                state
                    .lock()
                    .map_err(|_| FileResponseWorkerError::LockPoisoned)?
                    .step()
            })
            .map_err(file_response_worker_error)?;

        let (action, message) = match result.step {
            FileResponseCallStep::Send(event) => (
                FILE_RESPONSE_STEP_SEND,
                file_response_event_to_py(py, event, result.websocket)?
                    .into_any()
                    .unbind(),
            ),
            FileResponseCallStep::RunBackground => (FILE_RESPONSE_STEP_BACKGROUND, py.None()),
            FileResponseCallStep::Complete => (FILE_RESPONSE_STEP_COMPLETE, py.None()),
            FileResponseCallStep::Failed => (FILE_RESPONSE_STEP_FAILED, py.None()),
        };
        let base_headers = headers_to_py(py, result.base_headers)?;
        let values = [
            action.into_pyobject(py)?.into_any().unbind(),
            message,
            result
                .refresh_headers
                .into_pyobject(py)?
                .to_owned()
                .into_any()
                .unbind(),
            base_headers.into_any().unbind(),
        ];
        PyTuple::new(py, values)
            .map(Bound::into_any)
            .map(Bound::unbind)
    }

    fn close(&self, py: Python<'_>) -> Py<PyAny> {
        let state = Arc::clone(&self.state);
        py.detach(move || {
            let mut state = match state.lock() {
                Ok(state) => state,
                Err(poisoned) => poisoned.into_inner(),
            };
            state.close_file();
        });
        py.None()
    }
}

impl FileResponseCallDriverState {
    fn step(&mut self) -> Result<FileResponseWorkerStep, FileResponseWorkerError> {
        let refresh_headers = !self.headers_refreshed;
        if self.call.is_none() {
            self.call = Some(
                self.response
                    .call_state_with_headers(
                        self.header_views.clone(),
                        &self.scope_type,
                        &self.method,
                        &self.request_headers,
                        self.pathsend_extension,
                        self.has_background,
                    )
                    .map_err(FileResponseWorkerError::Preparation)?,
            );
        }
        self.headers_refreshed = true;

        let call = self
            .call
            .as_mut()
            .ok_or(FileResponseWorkerError::LockPoisoned)?;
        let step = call.step().map_err(FileResponseWorkerError::Io)?;
        let base_headers = if refresh_headers {
            call.base_headers().to_vec()
        } else {
            Vec::new()
        };
        Ok(FileResponseWorkerStep {
            step,
            base_headers,
            refresh_headers,
            websocket: self.websocket,
        })
    }

    fn close_file(&mut self) {
        if let Some(call) = self.call.as_mut() {
            call.close_file();
        }
    }
}

#[pymethods]
impl PyFileResponseCallDriver {
    fn _step(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.step(py)
    }

    fn _close(&self, py: Python<'_>) -> Py<PyAny> {
        self.close(py)
    }
}

const FILE_RESPONSE_STEP_SEND: u8 = 0;
const FILE_RESPONSE_STEP_BACKGROUND: u8 = 1;
const FILE_RESPONSE_STEP_COMPLETE: u8 = 2;
const FILE_RESPONSE_STEP_FAILED: u8 = 3;

struct FileResponseMachine {
    driver: Py<PyFileResponseCallDriver>,
    send: Py<PyAny>,
    _receive: Py<PyAny>,
    background: Option<Py<PyAny>>,
    view_raw: Py<PyAny>,
    pending: Option<FileResponsePending>,
    deferred_error: Option<PyErr>,
}

enum FileResponsePending {
    Step,
    Send,
    Background,
    Close,
}

impl AwaitableStateMachine for FileResponseMachine {
    fn traverse(
        &self,
        visit: &pyo3::class::gc::PyVisit<'_>,
    ) -> Result<(), pyo3::class::gc::PyTraverseError> {
        visit.call(&self.driver)?;
        visit.call(&self.send)?;
        visit.call(&self._receive)?;
        visit.call(&self.background)?;
        visit.call(&self.view_raw)
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.next_action(py),
            MachineResume::Value(value) => {
                match self.pending.take() {
                    Some(FileResponsePending::Step) => return self.next_step_action(py, value),
                    Some(FileResponsePending::Send) => {
                        if let Err(error) = self.advance(py, FileResponseCallInput::Send(Ok(()))) {
                            return self.cleanup_after_error(py, error, None);
                        }
                    }
                    Some(FileResponsePending::Background) => {
                        if let Err(error) =
                            self.advance(py, FileResponseCallInput::BackgroundFinished(Ok(())))
                        {
                            return self.cleanup_after_error(py, error, None);
                        }
                        return Ok(MachineAction::Complete(py.None()));
                    }
                    Some(FileResponsePending::Close) => {
                        return Err(self.deferred_error.take().ok_or_else(|| {
                            PyRuntimeError::new_err("file response cleanup lost its error")
                        })?);
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
            MachineResume::Error(error) => match self.pending.take() {
                Some(FileResponsePending::Step) => self.cleanup_after_error(py, error, None),
                Some(FileResponsePending::Send) => {
                    let operation_error = error.clone_ref(py);
                    self.cleanup_after_error(
                        py,
                        error,
                        Some(FileResponseCallInput::Send(Err(operation_error))),
                    )
                }
                Some(FileResponsePending::Background) => {
                    let operation_error = error.clone_ref(py);
                    self.cleanup_after_error(
                        py,
                        error,
                        Some(FileResponseCallInput::BackgroundFinished(Err(
                            operation_error,
                        ))),
                    )
                }
                Some(FileResponsePending::Close) => match self.deferred_error.take() {
                    Some(original) => Err(original),
                    None => Err(error),
                },
                None => Err(error),
            },
        }
    }
}

impl FileResponseMachine {
    fn next_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let awaitable = match (|| {
            let step = self.driver.bind(py).getattr("_step")?;
            py.import("anyio.to_thread")?
                .getattr("run_sync")?
                .call1((step,))
        })() {
            Ok(awaitable) => awaitable,
            Err(error) => return self.cleanup_after_error(py, error, None),
        };
        self.pending = Some(FileResponsePending::Step);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn next_step_action(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        match self.apply_step_result(py, value) {
            Ok(action) => Ok(action),
            Err(error) => {
                let operation_error = error.clone_ref(py);
                let input = match self.pending.take() {
                    Some(FileResponsePending::Send) => {
                        Some(FileResponseCallInput::Send(Err(operation_error)))
                    }
                    Some(FileResponsePending::Background) => Some(
                        FileResponseCallInput::BackgroundFinished(Err(operation_error)),
                    ),
                    _ => None,
                };
                self.cleanup_after_error(py, error, input)
            }
        }
    }

    fn apply_step_result(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        let result = value.bind(py).cast::<PyTuple>()?;
        let action = result.get_item(0)?.extract::<u8>()?;
        let message = result.get_item(1)?;
        let refresh_headers = result.get_item(2)?.extract::<bool>()?;
        if refresh_headers {
            let base_headers =
                crate::response_headers_runtime::parse_raw_pairs(&result.get_item(3)?)?;
            crate::response_headers_runtime::refresh_raw_pairs(
                py,
                self.view_raw.bind(py),
                &base_headers,
            )?;
        }

        match action {
            FILE_RESPONSE_STEP_SEND => {
                self.pending = Some(FileResponsePending::Send);
                let awaitable = self.send.bind(py).call1((message,))?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            FILE_RESPONSE_STEP_BACKGROUND => {
                self.pending = Some(FileResponsePending::Background);
                let callback = self.background.as_ref().ok_or_else(|| {
                    PyRuntimeError::new_err("file response requested a missing background callback")
                })?;
                let awaitable = callback.bind(py).call0()?;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            FILE_RESPONSE_STEP_COMPLETE => Ok(MachineAction::Complete(py.None())),
            FILE_RESPONSE_STEP_FAILED => Err(PyRuntimeError::new_err(
                "file response call is already failed",
            )),
            _ => Err(PyRuntimeError::new_err("unknown file response call step")),
        }
    }

    fn cleanup_after_error(
        &mut self,
        py: Python<'_>,
        error: PyErr,
        input: Option<FileResponseCallInput<PyErr>>,
    ) -> PyResult<MachineAction> {
        self.deferred_error = Some(error.clone_ref(py));
        if let Some(input) = input {
            let _advance_result = self.advance(py, input);
        }
        self.next_close_action(py)
    }

    fn next_close_action(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        // Keep AnyIO's default cancellation shielding so the worker closes the
        // file before this state machine re-raises the original exception.
        let awaitable = match (|| {
            let close = self.driver.bind(py).getattr("_close")?;
            py.import("anyio.to_thread")?
                .getattr("run_sync")?
                .call1((close,))
        })() {
            Ok(awaitable) => awaitable,
            Err(error) => {
                return match self.deferred_error.take() {
                    Some(original) => Err(original),
                    None => Err(error),
                };
            }
        };
        self.pending = Some(FileResponsePending::Close);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn advance(&mut self, py: Python<'_>, input: FileResponseCallInput<PyErr>) -> PyResult<()> {
        self.driver.bind(py).borrow().advance(input)
    }
}

fn file_response_worker_error(error: FileResponseWorkerError) -> PyErr {
    match error {
        FileResponseWorkerError::LockPoisoned => {
            PyRuntimeError::new_err("file response call state is poisoned")
        }
        FileResponseWorkerError::Preparation(error) => file_response_error(error),
        FileResponseWorkerError::Io(error) => io_error(error),
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
