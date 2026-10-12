# Server error traceback boundary

Compatibility authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.

## Python traceback data

Starlette's `ServerErrorMiddleware` debug response depends on the active
Python exception and its traceback, not only its type and message. The pinned
implementation formats plain text with `traceback.format_exception`; its HTML
path uses `TracebackException.from_exception(..., capture_locals=True)` and
`inspect.getinnerframes(..., limit=7)` to obtain exception text, frame names,
line numbers, and source context. Those values belong to live Python frame and
traceback objects, and Python's standard library supplies the version-specific
formatting and source lookup.

The Rust continuation therefore calls those standard-library APIs while the
original exception is live. It passes the resulting text or frame values to
Rust. This is representation glue for interpreter-owned traceback data; it
does not select the error policy or construct the HTML in Python.

## Rust-owned error behavior

Rust selects debug text, debug HTML, a configured handler, or the default 500
response. It tracks whether the application has started its HTTP response,
invokes and awaits a configured Python handler at the required runtime
boundary, sends a generated response only when the source behavior permits,
and propagates the original application exception after successful handling.
Handler or response-call failures retain the original exception as context.
Rust also owns traceback HTML layout, escaping, response headers, and ASGI
ordering.

## Input evidence

The active input definitions exercise the direct debug HTML response, direct
non-HTTP pass-through, and errors after response start in
[`server-error-middleware.yaml`](../tests/fixtures/sources/parity/server-error-middleware.yaml).
The direct debug-text construction is exercised through TestClient in
[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml).
Application-level background-task failures and middleware ordering are
covered by [`asgi-server-errors.yaml`](../tests/fixtures/sources/parity/asgi-server-errors.yaml)
and [`application-middleware.yaml`](../tests/fixtures/sources/parity/application-middleware.yaml).
These definitions contain inputs only; their live comparisons remain part of
the root parity phase.
