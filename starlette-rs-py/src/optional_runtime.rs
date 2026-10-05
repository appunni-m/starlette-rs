//! Source-compatible dependency availability probes; algorithms stay in Rust.

use pyo3::exceptions::PyModuleNotFoundError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(form_dependencies, module)?)?;
    module.add_function(wrap_pyfunction!(request_form_dependency, module)?)?;
    module.add_function(wrap_pyfunction!(sessions_dependency, module)?)?;
    Ok(())
}

fn import_form(py: Python<'_>, root: &str) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let module = py.import(root)?;
    let header_parser = py
        .import(format!("{root}.multipart"))?
        .getattr("parse_options_header")?;
    Ok((module.into_any().unbind(), header_parser.unbind()))
}

#[pyfunction(name = "_form_dependencies")]
fn form_dependencies(py: Python<'_>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    match import_form(py, "python_multipart") {
        Ok(value) => Ok(value),
        Err(primary) if primary.is_instance_of::<PyModuleNotFoundError>(py) => {
            match import_form(py, "multipart") {
                Ok(value) => Ok(value),
                Err(error) if error.is_instance_of::<PyModuleNotFoundError>(py) => {
                    Ok((py.None(), py.None()))
                }
                Err(error) => {
                    error.set_context(py, Some(primary));
                    Err(error)
                }
            }
        }
        Err(error) => Err(error),
    }
}

#[pyfunction(name = "_request_form_dependency")]
fn request_form_dependency(py: Python<'_>) -> PyResult<Py<PyAny>> {
    let import = |root: &str| -> PyResult<Py<PyAny>> {
        py.import(format!("{root}.multipart"))?
            .getattr("parse_options_header")
            .map(Bound::unbind)
    };
    match import("python_multipart") {
        Ok(value) => Ok(value),
        Err(primary) if primary.is_instance_of::<PyModuleNotFoundError>(py) => {
            match import("multipart") {
                Ok(value) => Ok(value),
                Err(error) if error.is_instance_of::<PyModuleNotFoundError>(py) => Ok(py.None()),
                Err(error) => {
                    error.set_context(py, Some(primary));
                    Err(error)
                }
            }
        }
        Err(error) => Err(error),
    }
}

#[pyfunction(name = "_sessions_dependency")]
fn sessions_dependency(py: Python<'_>) -> PyResult<()> {
    py.import("itsdangerous")?;
    py.import("itsdangerous.exc")?.getattr("BadSignature")?;
    Ok(())
}
