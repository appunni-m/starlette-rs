# TestClient runtime boundary

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The repository implements a
bounded HTTP request/response slice of the documented
`starlette.testclient.TestClient` surface. Its pinned implementation is
`starlette/testclient.py` and its public guide is `docs/testclient.md`.

The active slice compares ASGI2 and ASGI3 calls, HTTP scope projection,
request-body delivery, response headers/body, and debug response extensions.
Lifespan context management, WebSocket sessions, streaming request bodies,
timeout warnings, and remaining error-policy behavior are still in the
compatibility backlog.

## Source-backed Python boundary

The source client subclasses its selected HTTPX implementation, uses that
client for request building, cookies, redirects, and public response objects,
and installs a synchronous transport (`testclient.py:207-367`). The transport
invokes arbitrary user ASGI callables through AnyIO's blocking portal
(`testclient.py:348-355`). HTTPX owns its documented client and response types,
and Python's selected AnyIO backend owns the event loop that executes the
user's Python callables.

The implementation boundary is:

- Python preserves the documented `TestClient` inheritance and `request`
  signature, converts HTTPX objects at the PyO3 boundary, and exposes the
  HTTPX `BaseTransport` protocol as a call-through wrapper.
- Python supplies small ASGI2/ASGI3 call-and-await functions. Rust selects the
  callable shape, starts AnyIO's blocking portal for the selected backend, and
  drives the ASGI call on that portal without creating another executor or
  event loop.
- Rust owns request-to-scope projection, receive and send state, response
  completion, debug extensions, default headers, URL merging, app state, and
  construction of the HTTPX response through its public types. Rust calls the
  supplied ASGI callable through the existing PyO3 awaitable boundary.
- HTTPX continues to own its client semantics, cookies, redirects, URL types,
  and response types. The selected implementation and its optional dependency
  requirements match the pinned Starlette source lock in parity runs.

The Python code added for this feature remains a forwarding/API wrapper: no
Python branch, loop, `raise`, or `assert` implements TestClient policy. Any
additional Python-only behavior must have a pinned-source rationale here and
an input-only oracle comparison before it is accepted.

## Evidence and remaining work

Each slice is authored as input-only YAML under `tests/fixtures/sources/` and
is run against the pinned source and installed package in isolated processes.
Stimuli come from the input definition; adapters may not use case IDs to
choose requests, scopes, responses, or outcomes. The current HTTP
request/response slice has three data-driven cases covering four requirements,
and all three compare exactly against the pinned source. Error-policy,
timeout-warning, streaming-body, lifespan, and WebSocket behavior need
separate inputs with their own ordered callback and cleanup observations.

The pinned source provides additional mappings in `tests/test_testclient.py`
and `docs/testclient.md`; those source rows remain visible in the fixture
backlog until their input-driven comparisons exist. A passing transport slice
does not establish full TestClient or Starlette parity.
