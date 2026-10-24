# UploadFile content_type descriptor boundary

Starlette 1.6.0 exposes `UploadFile.content_type` as a Python `property` with
no setter (`starlette/datastructures.py:432-434`). Assigning to it raises the
standard property `AttributeError`, and the value continues to come from the
current `headers` object.

The Rust-backed `_core.UploadFile` getter owns the value lookup and calls the
current headers object's `get` method. PyO3 exposes that getter as a read-only
getset descriptor, whose assignment error is observably different from the
pinned Python property. A native getset descriptor cannot provide the Python
`property` object and its standard no-setter behavior. The compatibility
facade therefore declares a getter-only `@property` that forwards to
`super().content_type`. It adds no lookup policy, branching, or exception
handling in Python; Python's built-in property descriptor supplies the
read-only assignment error while Rust remains responsible for the value.

Input-only case
`starlette.datastructures.UploadFile.file-operations.content-type-read-only-property`
assigns headers, attempts to assign `content_type`, and observes the exact
exception class and message together with the value afterward. Its oracle is
the pinned Starlette package and its target is the installed compatibility
package. The case is authored for the grouped parity phase and has not been
executed yet.
