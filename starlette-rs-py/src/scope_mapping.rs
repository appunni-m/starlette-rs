//! Operations on the mutable ASGI scope mapping.
//!
//! ASGI scopes are mutable mappings, not necessarily dictionaries. Keep the
//! original Python object at the boundary and invoke its mapping protocol so
//! identity, overrides, and callback errors remain observable.

use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub(crate) fn optional_item<'py>(
    scope: &Bound<'py, PyAny>,
    key: &str,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    match scope.get_item(key) {
        Ok(value) => Ok(Some(value)),
        Err(error) if error.is_instance_of::<PyKeyError>(scope.py()) => Ok(None),
        Err(error) => Err(error),
    }
}

pub(crate) fn mapping_copy<'py>(scope: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
    Ok(scope
        .py()
        .import("builtins")?
        .getattr("dict")?
        .call1((scope,))?
        .cast_into()?)
}
