//! PyO3 boundary for Rust-owned Starlette static-file dispatch.

use std::path::{Path, PathBuf};

use pyo3::exceptions::{
    PyAssertionError, PyKeyError, PyOSError, PyPermissionError, PyRuntimeError, PyValueError,
};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyModule, PyString, PyTuple};
use starlette_rs::{StaticFiles as NativeStaticFiles, StaticFilesError, StaticFilesResponse};

/// Registers the native static-file runtime.
pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyStaticFiles>()
}

#[pyclass(name = "StaticFiles", unsendable)]
struct PyStaticFiles {
    inner: NativeStaticFiles,
    config_checked: bool,
    directory: Option<Py<PyAny>>,
    packages: Option<Py<PyAny>>,
}

#[pymethods]
impl PyStaticFiles {
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
        match self.inner.lookup_path(path).map_err(static_files_error)? {
            Some(file) => Ok((
                path_string(&file.path)?,
                stat_result(
                    py,
                    file.metadata.size(),
                    file.metadata.modified_unix_seconds(),
                )?,
            )),
            None => Ok((String::new(), py.None())),
        }
    }

    fn check_config(&self) -> PyResult<()> {
        self.inner.check_config().map_err(static_files_error)
    }

    fn get_response(
        &self,
        py: Python<'_>,
        path: &str,
        scope: &Bound<'_, PyDict>,
    ) -> PyResult<Py<PyAny>> {
        self.prepare_response(py, path, scope)
    }

    fn asgi_call(
        &mut self,
        py: Python<'_>,
        scope: &Bound<'_, PyDict>,
        receive: Py<PyAny>,
        send: Py<PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| PyKeyError::new_err("type"))?
            .extract::<String>()?;
        if scope_type != "http" {
            return Err(PyAssertionError::new_err(()));
        }
        if !self.config_checked {
            self.inner.check_config().map_err(static_files_error)?;
            self.config_checked = true;
        }
        let path = self.get_path(scope)?;
        let response = self.prepare_response(py, &path, scope)?;
        let awaitable = response.bind(py).call1((scope, receive, send))?;
        Ok(awaitable.unbind())
    }
}

impl PyStaticFiles {
    fn prepare_response(
        &self,
        py: Python<'_>,
        path: &str,
        scope: &Bound<'_, PyDict>,
    ) -> PyResult<Py<PyAny>> {
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
        match self
            .inner
            .get_response(path, &scope_path, &method, &request_headers)
            .map_err(|error| static_files_http_error(py, error))?
        {
            StaticFilesResponse::File { file, status_code } => {
                let response_type =
                    PyModule::import(py, "starlette.responses")?.getattr("FileResponse")?;
                let kwargs = PyDict::new(py);
                kwargs.set_item("status_code", status_code)?;
                kwargs.set_item(
                    "stat_result",
                    stat_result(
                        py,
                        file.metadata.size(),
                        file.metadata.modified_unix_seconds(),
                    )?,
                )?;
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

fn stat_result(py: Python<'_>, size: u64, modified: f64) -> PyResult<Py<PyAny>> {
    let os = PyModule::import(py, "os")?;
    let stat_type = os.getattr("stat_result")?;
    stat_type
        .call1(((0o100644, 0, 0, 1, 0, 0, size, modified, modified, modified),))
        .map(Bound::unbind)
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
        StaticFilesError::Io(error) => PyOSError::new_err(error.to_string()),
        StaticFilesError::FileResponse(error) => PyValueError::new_err(error.to_string()),
        StaticFilesError::MethodNotAllowed | StaticFilesError::NotFound => {
            PyRuntimeError::new_err("static-file HTTP error was not mapped")
        }
    }
}
