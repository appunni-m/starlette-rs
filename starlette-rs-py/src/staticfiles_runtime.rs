//! PyO3 boundary for Rust-owned Starlette static-file dispatch.

use std::path::{Path, PathBuf};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{
    PyAssertionError, PyKeyError, PyOSError, PyPermissionError, PyRuntimeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyInt, PyList, PyModule, PyString, PyTuple};
use starlette_rs::{
    FileMetadata, FileStat, FileStatTimestamp, StaticFile, StaticFiles as NativeStaticFiles,
    StaticFilesError, StaticFilesResponse, StaticFilesResponseFlow, StaticFilesResponseStep,
};

/// Registers the native static-file runtime.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyStaticFiles>()
}

#[pyclass(name = "StaticFiles")]
struct PyStaticFiles {
    inner: NativeStaticFiles,
    config_checked: bool,
    directory: Option<Py<PyAny>>,
    packages: Option<Py<PyAny>>,
}

#[pymethods]
impl PyStaticFiles {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.directory)?;
        visit.call(&self.packages)?;
        Ok(())
    }

    fn __clear__(&mut self, _py: Python<'_>) {
        self.directory = None;
        self.packages = None;
    }

    #[new]
    #[pyo3(signature = (directory=None, packages=None, html=false, check_dir=true, follow_symlink=false))]
    fn new(
        py: Python<'_>,
        directory: Option<Py<PyAny>>,
        packages: Option<Py<PyAny>>,
        html: bool,
        check_dir: bool,
        follow_symlink: bool,
    ) -> PyResult<Self> {
        let (all_directories, native_directory) =
            resolve_directories(py, directory.as_ref(), packages.as_ref())?;
        let inner = NativeStaticFiles::new(
            native_directory,
            all_directories,
            html,
            check_dir,
            follow_symlink,
        )
        .map_err(static_files_error)?;
        Ok(Self {
            inner,
            config_checked: false,
            directory,
            packages,
        })
    }

    #[getter]
    fn directory(&self, py: Python<'_>) -> Py<PyAny> {
        self.directory
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py))
    }

    #[getter]
    fn packages(&self, py: Python<'_>) -> Py<PyAny> {
        self.packages
            .as_ref()
            .map_or_else(|| py.None(), |value| value.clone_ref(py))
    }

    #[getter]
    fn all_directories(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let paths = PyList::empty(py);
        if let Some(directory) = self.directory.as_ref() {
            paths.append(directory.bind(py))?;
        }
        for path in self
            .inner
            .directories()
            .iter()
            .skip(usize::from(self.directory.is_some()))
        {
            paths.append(path_string(path)?)?;
        }
        Ok(paths.into_any().unbind())
    }

    #[getter]
    fn html(&self) -> bool {
        self.inner.html()
    }

    #[getter]
    fn follow_symlink(&self) -> bool {
        self.inner.follow_symlink()
    }

    #[getter]
    fn config_checked(&self) -> bool {
        self.config_checked
    }

    fn get_directories(
        &self,
        py: Python<'_>,
        directory: Option<Py<PyAny>>,
        packages: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let (directories, _) = resolve_directories(py, None, packages.as_ref())?;
        let paths = PyList::empty(py);
        if let Some(directory) = directory.as_ref() {
            paths.append(directory.bind(py))?;
        }
        for path in directories {
            paths.append(path_string(&path)?)?;
        }
        Ok(paths.into_any().unbind())
    }

    fn get_path(&self, scope: &Bound<'_, PyDict>) -> PyResult<String> {
        let path = scope
            .get_item("path")?
            .ok_or_else(|| PyValueError::new_err("ASGI scope is missing 'path'"))?
            .extract::<String>()?;
        let root_path = scope
            .get_item("root_path")?
            .map(|value| value.extract::<String>())
            .transpose()?
            .unwrap_or_default();
        Ok(NativeStaticFiles::get_path(&path, &root_path))
    }

    fn lookup_path(&self, py: Python<'_>, path: &str) -> PyResult<(String, Py<PyAny>)> {
        let inner = self.inner.clone();
        let path = path.to_owned();
        let lookup = py
            .detach(move || inner.lookup_path(&path))
            .map_err(static_files_error)?;
        match lookup {
            Some(file) => Ok((
                path_string(&file.path)?,
                stat_result(py, &file.path, file.metadata.stat_result())?,
            )),
            None => Ok((String::new(), py.None())),
        }
    }

    #[pyo3(name = "_check_config_sync")]
    fn check_config_sync(&self, py: Python<'_>) -> PyResult<()> {
        let inner = self.inner.clone();
        py.detach(move || inner.check_config())
            .map_err(static_files_error)
    }

    fn check_config(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let callback = slf.bind(py).getattr("_check_config_sync")?.unbind();
        into_sendable_python_awaitable(
            py,
            StaticFilesCheckConfigMachine {
                callback,
                waiting: false,
            },
        )
    }

    fn get_response(
        slf: Py<Self>,
        py: Python<'_>,
        path: &str,
        scope: &Bound<'_, PyDict>,
        lookup_path: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        into_sendable_python_awaitable(
            py,
            StaticFilesCallMachine::new(
                slf,
                scope.clone().into_any().unbind(),
                lookup_path,
                None,
                None,
                None,
                path.to_owned(),
                StaticFilesCallPurpose::Response,
            ),
        )
    }

    // LINT EXCEPTION: PyO3 passes the ASGI scope, two callbacks, and three facade methods separately.
    #[allow(clippy::too_many_arguments)]
    fn asgi_call(
        slf: Py<Self>,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
        get_path: Py<PyAny>,
        lookup_path: Py<PyAny>,
        check_config: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if scope_type != "http" {
            return Err(PyAssertionError::new_err(()));
        }
        into_sendable_python_awaitable(
            py,
            StaticFilesCallMachine::new(
                slf,
                scope.clone().into_any().unbind(),
                lookup_path,
                Some(check_config),
                Some(get_path),
                Some((receive, send)),
                String::new(),
                StaticFilesCallPurpose::Asgi,
            ),
        )
    }
}

impl PyStaticFiles {
    fn prepare_response(
        py: Python<'_>,
        response: StaticFilesResponse,
        scope: &Bound<'_, PyDict>,
        selected_stat_result: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        match response {
            StaticFilesResponse::File { file, status_code } => {
                let response_type =
                    PyModule::import(py, "starlette.responses")?.getattr("FileResponse")?;
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", status_code)?;
                let stat_result = match selected_stat_result {
                    Some(stat_result) => stat_result.clone().unbind(),
                    None => stat_result(py, &file.path, file.metadata.stat_result())?,
                };
                kwargs.set_item("stat_result", stat_result)?;
                response_type
                    .call((path_string(&file.path)?,), Some(&kwargs))
                    .map(Bound::unbind)
            }
            StaticFilesResponse::NotModified { headers } => {
                let response_type =
                    PyModule::import(py, "starlette.responses")?.getattr("Response")?;
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", 304)?;
                kwargs.set_item("headers", headers_mapping(py, headers)?)?;
                response_type
                    .call((PyBytes::new(py, b""),), Some(&kwargs))
                    .map(Bound::unbind)
            }
            StaticFilesResponse::Redirect { .. } => {
                let datastructures = PyModule::import(py, "starlette.datastructures")?;
                let url_type = datastructures.getattr("URL")?;
                let url_kwargs = PyDict::new(py);
                url_kwargs.set_item("scope", scope)?;
                let url = url_type.call((), Some(&url_kwargs))?;
                let target_path = url.getattr("path")?.extract::<String>()? + "/";
                let replace_kwargs = PyDict::new(py);
                replace_kwargs.set_item("path", target_path)?;
                let redirect_url = url.call_method("replace", (), Some(&replace_kwargs))?;
                let redirect_type =
                    PyModule::import(py, "starlette.responses")?.getattr("RedirectResponse")?;
                redirect_type.call1((redirect_url,)).map(Bound::unbind)
            }
        }
    }
}

#[derive(Clone, Copy)]
enum StaticFilesCallPurpose {
    Response,
    Asgi,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum StaticFilesCallState {
    Start,
    AwaitCheckConfig,
    AwaitLookup,
    AwaitResponse,
}

struct StaticFilesCallMachine {
    owner: Py<PyStaticFiles>,
    scope: Py<PyAny>,
    lookup_path: Py<PyAny>,
    check_config: Option<Py<PyAny>>,
    get_path: Option<Py<PyAny>>,
    response_callbacks: Option<(Py<PyAny>, Py<PyAny>)>,
    response_path: String,
    purpose: StaticFilesCallPurpose,
    state: StaticFilesCallState,
    flow: Option<StaticFilesResponseFlow>,
    selected_stat_result: Option<Py<PyAny>>,
}

impl StaticFilesCallMachine {
    // LINT EXCEPTION: Store owner, scope, callbacks, and request purpose as distinct state-machine inputs.
    #[allow(clippy::too_many_arguments)]
    fn new(
        owner: Py<PyStaticFiles>,
        scope: Py<PyAny>,
        lookup_path: Py<PyAny>,
        check_config: Option<Py<PyAny>>,
        get_path: Option<Py<PyAny>>,
        response_callbacks: Option<(Py<PyAny>, Py<PyAny>)>,
        response_path: String,
        purpose: StaticFilesCallPurpose,
    ) -> Self {
        Self {
            owner,
            scope,
            lookup_path,
            check_config,
            get_path,
            response_callbacks,
            response_path,
            purpose,
            state: StaticFilesCallState::Start,
            flow: None,
            selected_stat_result: None,
        }
    }

    fn begin_response_flow(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py).cast::<PyDict>()?;
        let path = match self.purpose {
            StaticFilesCallPurpose::Response => self.response_path.clone(),
            StaticFilesCallPurpose::Asgi => self
                .get_path
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("StaticFiles get_path callback is missing"))?
                .bind(py)
                .call1((scope,))?
                .extract::<String>()?,
        };
        let scope_path = scope
            .get_item("path")?
            .ok_or_else(|| PyValueError::new_err("ASGI scope is missing 'path'"))?
            .extract::<String>()?;
        let method = scope
            .get_item("method")?
            .ok_or_else(|| PyValueError::new_err("ASGI HTTP scope is missing 'method'"))?
            .extract::<String>()?;
        let request_headers = scope
            .get_item("headers")?
            .map(|value| value.extract::<Vec<(Vec<u8>, Vec<u8>)>>())
            .transpose()?
            .unwrap_or_default();
        let (flow, step) = {
            let owner = self.owner.borrow(py);
            owner
                .inner
                .start_response_flow(&path, &scope_path, &method, &request_headers)
                .map_err(|error| static_files_http_error(py, error))?
        };
        self.flow = Some(flow);
        self.apply_response_step(py, step)
    }

    fn apply_response_step(
        &mut self,
        py: Python<'_>,
        step: StaticFilesResponseStep,
    ) -> PyResult<MachineAction> {
        match step {
            StaticFilesResponseStep::Lookup(path) => {
                let awaitable = anyio_run_sync(py, &self.lookup_path, Some(path))?;
                self.state = StaticFilesCallState::AwaitLookup;
                Ok(MachineAction::Await(awaitable))
            }
            StaticFilesResponseStep::Complete(response) => {
                let scope = self.scope.bind(py).cast::<PyDict>()?;
                let response = PyStaticFiles::prepare_response(
                    py,
                    response,
                    scope,
                    self.selected_stat_result
                        .as_ref()
                        .map(|value| value.bind(py)),
                )?;
                match self.purpose {
                    StaticFilesCallPurpose::Response => Ok(MachineAction::Complete(response)),
                    StaticFilesCallPurpose::Asgi => {
                        let (receive, send) =
                            self.response_callbacks.as_ref().ok_or_else(|| {
                                PyRuntimeError::new_err("StaticFiles ASGI callbacks are missing")
                            })?;
                        let awaitable =
                            response
                                .bind(py)
                                .call1((scope, receive.bind(py), send.bind(py)))?;
                        self.state = StaticFilesCallState::AwaitResponse;
                        Ok(MachineAction::Await(awaitable.unbind()))
                    }
                }
            }
        }
    }

    fn resume_lookup(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        let (lookup, stat_result) = lookup_result_from_python(py, value)?;
        self.selected_stat_result = stat_result;
        let owner = self.owner.borrow(py);
        let inner = owner.inner.clone();
        drop(owner);
        let flow = self
            .flow
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("StaticFiles response flow is missing"))?;
        let step = flow
            .resume_lookup(&inner, Ok(lookup))
            .map_err(|error| static_files_http_error(py, error))?;
        self.apply_response_step(py, step)
    }

    fn resume_lookup_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let native_error = static_files_lookup_error(py, error)?;
        let owner = self.owner.borrow(py);
        let inner = owner.inner.clone();
        drop(owner);
        let flow = self
            .flow
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("StaticFiles response flow is missing"))?;
        match flow.resume_lookup(&inner, Err(native_error)) {
            Ok(step) => self.apply_response_step(py, step),
            Err(error) => Err(static_files_http_error(py, error)),
        }
    }
}

impl AwaitableStateMachine for StaticFilesCallMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.owner)?;
        visit.call(&self.scope)?;
        visit.call(&self.lookup_path)?;
        visit.call(&self.check_config)?;
        visit.call(&self.get_path)?;
        visit.call(&self.selected_stat_result)?;
        if let Some((receive, send)) = &self.response_callbacks {
            visit.call(receive)?;
            visit.call(send)?;
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match (self.state, input) {
            (StaticFilesCallState::Start, MachineResume::Start) => {
                let config_checked = self.owner.borrow(py).config_checked;
                match (self.purpose, config_checked) {
                    (StaticFilesCallPurpose::Asgi, false) => {
                        let callback = self.check_config.as_ref().ok_or_else(|| {
                            PyRuntimeError::new_err("StaticFiles check_config callback is missing")
                        })?;
                        let awaitable = callback.bind(py).call0()?.unbind();
                        self.state = StaticFilesCallState::AwaitCheckConfig;
                        Ok(MachineAction::Await(awaitable))
                    }
                    _ => self.begin_response_flow(py),
                }
            }
            (StaticFilesCallState::AwaitCheckConfig, MachineResume::Value(_)) => {
                self.owner.borrow_mut(py).config_checked = true;
                self.begin_response_flow(py)
            }
            (StaticFilesCallState::AwaitCheckConfig, MachineResume::Error(error)) => Err(error),
            (StaticFilesCallState::AwaitLookup, MachineResume::Value(value)) => {
                self.resume_lookup(py, value)
            }
            (StaticFilesCallState::AwaitLookup, MachineResume::Error(error)) => {
                self.resume_lookup_error(py, error)
            }
            (StaticFilesCallState::AwaitResponse, MachineResume::Value(_)) => {
                Ok(MachineAction::Complete(py.None()))
            }
            (StaticFilesCallState::AwaitResponse, MachineResume::Error(error)) => Err(error),
            (_, MachineResume::AsyncIterationComplete(error)) => Err(error),
            (_, MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_)) => Err(
                PyRuntimeError::new_err("invalid StaticFiles awaitable transition"),
            ),
        }
    }
}

struct StaticFilesCheckConfigMachine {
    callback: Py<PyAny>,
    waiting: bool,
}

impl AwaitableStateMachine for StaticFilesCheckConfigMachine {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.callback)?;
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.waiting => {
                let awaitable = anyio_run_sync(py, &self.callback, None)?;
                self.waiting = true;
                Ok(MachineAction::Await(awaitable))
            }
            MachineResume::Value(_) if self.waiting => Ok(MachineAction::Complete(py.None())),
            MachineResume::Error(error) if self.waiting => Err(error),
            MachineResume::AsyncIterationComplete(error) => Err(error),
            _ => Err(PyRuntimeError::new_err(
                "invalid StaticFiles check_config transition",
            )),
        }
    }
}

fn anyio_run_sync(
    py: Python<'_>,
    callback: &Py<PyAny>,
    argument: Option<String>,
) -> PyResult<Py<PyAny>> {
    let run_sync = PyModule::import(py, "anyio.to_thread")?.getattr("run_sync")?;
    let awaitable = match argument {
        Some(argument) => run_sync.call1((callback.bind(py), argument))?,
        None => run_sync.call1((callback.bind(py),))?,
    };
    Ok(awaitable.unbind())
}

fn lookup_result_from_python(
    py: Python<'_>,
    value: Py<PyAny>,
) -> PyResult<(Option<StaticFile>, Option<Py<PyAny>>)> {
    let pair = value.bind(py).cast::<PyTuple>()?;
    if pair.len() != 2 {
        return Err(PyValueError::new_err(
            "StaticFiles.lookup_path must return a pair",
        ));
    }
    let full_path = pair.get_item(0)?;
    let stat_result = pair.get_item(1)?;
    if !stat_result.is_truthy()? {
        return Ok((None, None));
    }
    let path = path_from_python(py, &full_path)?;
    let mode = stat_result.getattr("st_mode")?.extract::<u32>()?;
    let size = stat_result.getattr("st_size")?.extract::<u64>()?;
    let modified_value = stat_result.getattr("st_mtime")?;
    let modified = modified_value.extract::<f64>()?;
    let modified_text = py
        .import("builtins")?
        .getattr("str")?
        .call1((modified_value,))?
        .extract::<String>()?;
    let metadata = FileMetadata::from_unix_seconds(size, modified, modified_text)
        .map_err(|error| static_files_error(StaticFilesError::FileResponse(error)))?;
    let file = StaticFile::from_path_and_metadata(path, metadata, mode);
    Ok((Some(file), Some(stat_result.unbind())))
}

fn static_files_lookup_error(py: Python<'_>, error: PyErr) -> Result<StaticFilesError, PyErr> {
    if error.is_instance_of::<PyPermissionError>(py) {
        return Ok(StaticFilesError::PermissionDenied);
    }
    if error.is_instance_of::<PyValueError>(py) {
        return Ok(StaticFilesError::NotFound);
    }
    if error.is_instance_of::<PyOSError>(py) {
        let errno = error
            .value(py)
            .getattr("errno")
            .ok()
            .and_then(|value| value.extract::<i32>().ok());
        let too_long = py
            .import("errno")
            .and_then(|module| module.getattr("ENAMETOOLONG"))
            .and_then(|value| value.extract::<i32>())
            .ok();
        if errno.is_some() && errno == too_long {
            return Ok(StaticFilesError::NotFound);
        }
    }
    Err(error)
}

fn resolve_directories(
    py: Python<'_>,
    directory: Option<&Py<PyAny>>,
    packages: Option<&Py<PyAny>>,
) -> PyResult<(Vec<PathBuf>, Option<PathBuf>)> {
    let native_directory = directory
        .map(|directory| path_from_python(py, directory.bind(py)))
        .transpose()?;
    let directories = PyList::empty(py);
    if let Some(directory) = directory {
        directories.append(directory.bind(py))?;
    }
    if let Some(packages) = packages {
        for item in packages.bind(py).try_iter()? {
            let item = item?;
            let (package, statics_dir) = if let Ok(package_tuple) = item.cast::<PyTuple>() {
                (
                    package_tuple.get_item(0)?.extract::<String>()?,
                    package_tuple.get_item(1)?.extract::<String>()?,
                )
            } else {
                (item.extract::<String>()?, "statics".to_owned())
            };
            let package_repr = PyString::new(py, &package).repr()?.to_str()?.to_owned();
            let spec = PyModule::import(py, "importlib.util")?
                .getattr("find_spec")?
                .call1((package.as_str(),))?;
            if spec.is_none() {
                return Err(PyAssertionError::new_err(format!(
                    "Package {package_repr} could not be found."
                )));
            }
            let origin = spec.getattr("origin")?;
            if origin.is_none() {
                return Err(PyAssertionError::new_err(format!(
                    "Package {package_repr} could not be found."
                )));
            }
            let os_path = PyModule::import(py, "os.path")?;
            let package_directory = os_path.getattr("normpath")?.call1((os_path
                .getattr("join")?
                .call1((origin, "..", &statics_dir))?,))?;
            if !os_path
                .getattr("isdir")?
                .call1((package_directory.clone(),))?
                .extract::<bool>()?
            {
                let statics_repr = PyString::new(py, &statics_dir).repr()?.to_str()?.to_owned();
                return Err(PyAssertionError::new_err(format!(
                    "Directory {statics_repr} in package {package_repr} could not be found."
                )));
            }
            directories.append(package_directory)?;
        }
    }
    let mut paths = Vec::new();
    for directory in directories.iter() {
        paths.push(path_from_python(py, &directory)?);
    }
    Ok((paths, native_directory))
}

fn path_from_python(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<PathBuf> {
    let path = PyModule::import(py, "os")?
        .getattr("fspath")?
        .call1((value,))?;
    path.extract::<String>()
        .map(PathBuf::from)
        .map_err(|_| pyo3::exceptions::PyTypeError::new_err("path must be str or path-like"))
}

fn path_string(path: &Path) -> PyResult<String> {
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| PyValueError::new_err("filesystem path is not valid UTF-8"))
}

fn stat_result(py: Python<'_>, path: &Path, stat: Option<&FileStat>) -> PyResult<Py<PyAny>> {
    let os = PyModule::import(py, "os")?;
    let Some(stat) = stat else {
        return os
            .getattr("stat")?
            .call1((path_string(path)?,))
            .map(Bound::unbind);
    };

    let stat_type = os.getattr("stat_result")?;
    let tuple_fields = (
        stat.mode,
        stat.inode,
        stat.device,
        stat.link_count,
        stat.user_id,
        stat.group_id,
        stat.size,
        stat.access_time.seconds,
        stat.modified_time.seconds,
        stat.change_time.seconds,
    );
    let extra_fields = PyDict::new(py);
    set_timestamp_fields(py, &extra_fields, "atime", stat.access_time)?;
    set_timestamp_fields(py, &extra_fields, "mtime", stat.modified_time)?;
    set_timestamp_fields(py, &extra_fields, "ctime", stat.change_time)?;
    if let Some(block_size) = stat.block_size {
        extra_fields.set_item("st_blksize", block_size)?;
    }
    if let Some(blocks) = stat.blocks {
        extra_fields.set_item("st_blocks", blocks)?;
    }
    if let Some(special_device) = stat.special_device {
        extra_fields.set_item("st_rdev", special_device)?;
    }
    if let Some(flags) = stat.flags {
        extra_fields.set_item("st_flags", flags)?;
    }
    if let Some(generation) = stat.generation {
        extra_fields.set_item("st_gen", generation)?;
    }
    if let Some(birth_time) = stat.birth_time {
        extra_fields.set_item("st_birthtime", birth_time.unix_seconds())?;
    }
    stat_type
        .call1((tuple_fields, extra_fields))
        .map(Bound::unbind)
}

fn set_timestamp_fields(
    py: Python<'_>,
    fields: &Bound<'_, PyDict>,
    name: &str,
    timestamp: FileStatTimestamp,
) -> PyResult<()> {
    let key = format!("st_{name}");
    fields.set_item(key.as_str(), timestamp.unix_seconds())?;
    let nanoseconds_key = format!("st_{name}_ns");
    let nanoseconds = PyInt::new(py, timestamp.seconds)
        .call_method1("__mul__", (1_000_000_000_i64,))?
        .call_method1("__add__", (timestamp.nanoseconds,))?;
    fields.set_item(nanoseconds_key.as_str(), nanoseconds)?;
    Ok(())
}

fn headers_mapping<'py>(
    py: Python<'py>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
) -> PyResult<Bound<'py, PyDict>> {
    let mapping = PyDict::new(py);
    for (name, value) in headers {
        mapping.set_item(latin1_string(py, &name)?, latin1_string(py, &value)?)?;
    }
    Ok(mapping)
}

fn latin1_string<'py>(py: Python<'py>, bytes: &[u8]) -> PyResult<Bound<'py, PyAny>> {
    PyBytes::new(py, bytes).call_method1("decode", ("latin-1",))
}

fn static_files_http_error(py: Python<'_>, error: StaticFilesError) -> PyErr {
    match error {
        StaticFilesError::MethodNotAllowed => http_exception(py, 405),
        StaticFilesError::NotFound => http_exception(py, 404),
        StaticFilesError::PermissionDenied => http_exception(py, 401),
        error => static_files_error(error),
    }
}

fn http_exception(py: Python<'_>, status_code: u16) -> PyErr {
    PyModule::import(py, "starlette.exceptions")
        .and_then(|module| module.getattr("HTTPException"))
        .and_then(|exception_type| exception_type.call1((status_code,)))
        .map_or_else(|error| error, PyErr::from_value)
}

fn static_files_error(error: StaticFilesError) -> PyErr {
    match error {
        StaticFilesError::DirectoryConfiguration(message) => PyRuntimeError::new_err(message),
        StaticFilesError::PermissionDenied => PyPermissionError::new_err("permission denied"),
        StaticFilesError::Io(error) if error.kind() == std::io::ErrorKind::PermissionDenied => {
            PyPermissionError::new_err(error.to_string())
        }
        StaticFilesError::Io(error) => match error.raw_os_error() {
            Some(errno) => PyOSError::new_err((errno, error.to_string())),
            None => PyOSError::new_err(error.to_string()),
        },
        StaticFilesError::FileResponse(error) => PyValueError::new_err(error.to_string()),
        StaticFilesError::MethodNotAllowed | StaticFilesError::NotFound => {
            PyRuntimeError::new_err("static-file HTTP error was not mapped")
        }
    }
}
