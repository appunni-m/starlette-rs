# Application middleware iterator boundary

The authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. Its source builds the application
stack by iterating
`reversed(middleware)`, unpacking each entry as `cls, args, kwargs`, and calling
`cls(app, *args, **kwargs)` in `starlette/applications.py::Starlette.build_middleware_stack`.
`starlette/middleware/__init__.py::Middleware.__iter__` provides that unpacking
protocol and can be overridden by a public Python subclass.
The pinned `tests/middleware/test_middleware.py::test_middleware_iter` also
exercises that public iterator, while `docs/middleware.md` documents configured
middleware as part of ordinary ASGI wrapping.

Rust owns stack order, consumes exactly the three yielded configuration values,
expands positional iterables and keyword mappings, constructs each middleware
layer, and propagates callback errors. It invokes Python's iterator and mapping
protocols at the PyO3 boundary because a subclass's `__iter__` implementation
may be arbitrary Python code and CPython's special-method lookup must dispatch
to that override. Reimplementing the iterator in Rust or reading `.cls`,
`.args`, and `.kwargs` directly would bypass that public subclass behavior.

The input-only comparison is
`starlette.applications.Starlette.__call__.middleware-config-subclass-iteration`
in `tests/fixtures/sources/parity/application-middleware.yaml`. Its `Middleware`
subclass yields a different response-header middleware configuration from the
one stored in its base instance; both the pinned oracle and Python package
materialize that subclass from the declared input in isolated runs. The case is
authored for the full parity phase and has not been executed during this
implementation slice.
