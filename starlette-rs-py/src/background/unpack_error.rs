use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

pub(super) fn message(py: Python<'_>, value: &Bound<'_, PyAny>, item_count: usize) -> String {
    if item_count < 2 {
        return format!("not enough values to unpack (expected 2, got {item_count})");
    }
    let exact_sequence = value.is_exact_instance_of::<PyList>()
        || value.is_exact_instance_of::<PyTuple>()
        || value.is_exact_instance_of::<PyDict>();
    if py.version_info() >= (3, 14) && exact_sequence {
        format!("too many values to unpack (expected 2, got {item_count})")
    } else {
        String::from("too many values to unpack (expected 2)")
    }
}
