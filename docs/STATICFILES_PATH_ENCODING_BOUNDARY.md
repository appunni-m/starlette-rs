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

This boundary performs representation conversion only. It does not duplicate
Starlette's lookup policy in Python. The input-only
`StaticFiles.lookup_path.surrogateescape-path` case supplies an invalid UTF-8
filename byte through the declared filesystem-byte encoding. The
`StaticFiles.asgi-call.surrogateescape-scope-path` case supplies invalid bytes
in both ASGI path fields and compares the ordinary not-found response from the
live oracle and targets. Both comparisons are authored and await the grouped
parity phase.
