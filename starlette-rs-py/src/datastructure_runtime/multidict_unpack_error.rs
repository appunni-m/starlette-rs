use pyo3::prelude::Python;

pub(super) fn message(py: Python<'_>, item_count: usize) -> String {
    if item_count < 2 {
        format!("not enough values to unpack (expected 2, got {item_count})")
    } else if py.version_info() >= (3, 14) {
        // CPython 3.14 includes the received-item count in this ValueError.
        format!("too many values to unpack (expected 2, got {item_count})")
    } else {
        "too many values to unpack (expected 2)".to_owned()
    }
}
