# StaticFiles filesystem path encoding boundary

On Unix, Python can represent undecodable filesystem bytes in a `str` with
`surrogateescape`. PyO3 cannot extract such a value as Rust UTF-8 `String`, so
the compatibility wrapper converts `os.fspath(value)` with `os.fsencode` and
constructs an `OsString` from those bytes. It applies the same representation
conversion to ASGI `scope.path` and `scope.root_path` before calling Rust's
`get_path`, then returns any path crossing back into Python through
`os.fsdecode`. Rust owns root-prefix stripping, path normalization, root
checks, and metadata lookup through `OsStr` APIs, preserving the encoded bytes
across the complete scope-to-lookup flow.

For Python `str` subclasses, the PyO3 boundary also preserves the callbacks
that pinned StaticFiles uses before normalization. `get_path` reuses the
Rust-owned route-path selector, which calls `startswith`, equality, indexing,
and slicing on the original objects under the GIL; it then calls `split("/")`
on the resulting route-path object and passes its path components to Rust
for platform joining and normalization. `lookup_path` calls the original
string's `startswith(("/", "\\"))` under the GIL and passes that decision to
Rust before native filesystem lookup. This is required by the pinned
`starlette/_utils.py::get_route_path` and `starlette/staticfiles.py::get_path`
and `lookup_path` expressions (Starlette 1.6.0 source lines 96-110, 101-107,
and 154-173). Python callbacks here only preserve user-defined protocol
dispatch and exceptions; path selection, joining, normalization, containment,
and stat lookup remain Rust-owned.

This boundary performs representation conversion only. It does not duplicate
Starlette's lookup policy in Python. The input-only
`StaticFiles.lookup_path.surrogateescape-path` case supplies an invalid UTF-8
filename byte through the declared filesystem-byte encoding. The
`StaticFiles.asgi-call.surrogateescape-scope-path` case supplies invalid bytes
in both ASGI path fields and compares the ordinary not-found response from the
live oracle and targets. Both comparisons are authored and await the grouped
parity phase. The input-only `StaticFiles.asgi-call.path-str-subclass-dispatch`
cases exercise custom `startswith`, slice, and `split` results, while
`StaticFiles.lookup-path.str-subclass-startswith` exercises both truth values
from the lookup hook. These package cases target supported CPython 3.10 through
3.14 profiles and also await the grouped parity phase.
