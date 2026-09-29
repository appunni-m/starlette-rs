# Compatibility atlas and implementation backlog

**Authority:** Starlette 1.6.0, commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. This document records work order
and links to bounded evidence; it is not itself a parity artifact or a claim
of full compatibility. The full replacement objective remains active and
incomplete.

## Current parity snapshot

The active contract has 335 input-only cases across 38 files, covering 56
operations and 411 requirements. Run `29b8e21f-90a6-43b5-97b1-979552db5618` from
`2026-09-29T18:40:17.007Z` to `2026-09-29T18:41:18.990Z`; it selected 472
comparisons: 468 passed, zero failed, zero infrastructure errors, and four
`not_run`. The Python package passed all 333 applicable cases; Rust-native
passed 135 of 139 selected cases. The four unsupported Rust-native rows require
arbitrary Python callables. All 28 FileResponse cases passed on both profiles;
all eight SessionMiddleware cases and all twenty BaseHTTPMiddleware cases
passed on the Python package profile. The twenty BaseHTTPMiddleware cases
cover configured-header mutation, awaited `call_next` response replacement,
body-cache replay, response-completion unblocking downstream receive,
exception-context propagation, caught downstream `ValueError` handling,
partial-stream forwarding, downstream receive transformation, repeated
disconnect polling with `send_body=True` and `False`, downstream disconnect
propagation followed by `Request.is_disconnected()`, body-cache/disconnect
ordering, stream consumption
followed by a downstream body read, body buffering followed by a downstream
stream read, dispatch stream reads after downstream stream/body consumption,
cached-stream replay after downstream body reading, a downstream body read
after dispatch caches the request body, and a downstream stream read after
dispatch exhausts `request.stream()`.
The two post-call-next cases at `tests/middleware/test_base.py:715-773` capture
the live read result after the endpoint consumes the stream or body; the input
does not encode an expected exception.
The new pre-call-next cache case maps to
`test_read_request_stream_in_dispatch_after_app_calls_body_with_middleware_calling_body_before_call_next`
at `tests/middleware/test_base.py:835-862`: dispatch caches the body, the
endpoint reads it, then dispatch observes the cached stream bytes, empty
terminal chunk, and exhaustion. The source and package matched exactly.
The discarded-stream case maps to `tests/middleware/test_base.py:473-546`:
dispatch consumes one `call_next` chunk, closes the iterator, and returns a
replacement response while the downstream app streams until disconnect. Its
observed close, cancellation, response, and disconnect behavior also matches.
The caught-exception case matches
`tests/middleware/test_base.py:338-356`: dispatch catches `ValueError("TEST")`
from `call_next` and returns status 400 with a body derived from `str(exc)`.
Both polling variants observe two downstream polls, raw and downstream receive
traces, drained requests and poll results, and the exact `200 b"good!"` response
tape; see `tests/middleware/test_base.py:1168-1215`. The disconnect-observation
cases map to `test_read_request_disconnected_client` and
`test_read_request_disconnected_after_consuming_steam` at
`tests/middleware/test_base.py:894-976`: one observes a downstream disconnect
before dispatch checks `Request.is_disconnected()`, and the other caches `b"hi"`,
checks for disconnect, then verifies the downstream body and disconnect
sequence. Source and package observations match. The body-buffer/stream case
matches `test_read_request_stream_in_app_after_middleware_calls_body` at
`tests/middleware/test_base.py:631-657`: dispatch reads `b"a"` before
`call_next`, and downstream stream iteration reads `b"a"` then `b""` before
returning `Homepage`. The stream-consumption case matches
`test_read_request_body_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:660-686`: dispatch exhausts `request.stream()`
and downstream reads the cached empty body before returning `Homepage`. The
case at `tests/middleware/test_base.py:599-628` drains the stream in dispatch
before `call_next`; downstream stream iteration then sees only the cached
empty chunk. Both observations match the source exactly. The
body-cache case maps to `test_read_request_body_in_app_after_middleware_calls_body`
at `tests/middleware/test_base.py:689-712`: dispatch and the downstream
endpoint both report reading `b"a"`, and the endpoint response returns those
bytes. The source test-client fixture declares asyncio and trio backends; the active input
selects the Python-package profile only. The partial-stream case consumes
`b"1"` in dispatch, forwards the next unread `b"2"` to the endpoint, then
resumes dispatch to consume `b"3"` after `call_next`; see
`tests/middleware/test_base.py:777-832`. The receive-transformation case maps
`tests/middleware/test_base.py:979-1017`: dispatch observes `b"foo "`, the
downstream wrapper doubles the request body, and the endpoint observes
`b"foo foo "`. This bounded slice leaves other partial-stream/replay
interleavings, disconnect ordering across stacked middleware, broader
exception-group shapes beyond the observed TaskGroup context and caught
`ValueError`, varied or malformed `http.response.debug` frames, broader
cancellation and cleanup ordering, path-send responses, and additional
streaming behaviors unproven. The Rust-native target was clean at revision
`067c191d1010aaafb2c8e34c01ac51bb63c1ee58+source-fnv1a64-e5a0df1c1dca21b4`;
the Python-package target tree SHA-256 is
`c087a7bf38872cf4942de94843775aa77ceb4f5904a85b0cd085bbb847d3b03f`. Manifest
SHA-256: `405f83a94b2e0507981c338e9f9d1585cee7202c0ccd7e1f194ac57b1fd12f93`;
package wheel SHA-256:
`f9c8434c43ddb3356b9d35866badf0e8cf7ca730f227e97af6914221a66cf12c`.
See [Migration parity contract and evidence](../PARITY.md) for current scope.

## P0 — Close the source-backed atlas (complete)

The merged review disposes all 999 API candidates as `supported`,
`private/internal`, or `uncertain`, with pinned-source evidence. It maps all
514 upstream test functions, 24 documentation navigation pages, and four
shared test support modules into the [coverage matrix](coverage-matrix.csv).
The current matrix has 791 mappings: 611 fixture backlog rows, 50 reasoned
`not_applicable` entries, and 130 existing input mappings. It maps selected
HTTPException, registered-handler, server-error, WebSocket, route-converter,
Mount, and typed-Request behaviors to input files. It is not a one-to-one index
of every active parity case, so backlog status does not prove a behavior is
untested. At the P0 atlas-close checkpoint, the manifest indexed 18 parity
input files containing 118 cases, including 38 request/routing, 21 reverse-URL, four direct ASGI, eight
basic Response/JSONResponse, four finite synchronous StreamingResponse, one
finite async-iterator StreamingResponse, four RedirectResponse, eight GZip,
six WebSocket protocol-tape, six WebSocket state-projection, five Request-style
HTTPException, two callable-ASGI HTTPException, two registered-handler, and
nine server-error workflows. Built-in Router
converter cases select both profiles; typed Request, reverse URL, custom
converter, async-iterator StreamingResponse, and full WebSocket protocol cases
select the Python package. Mount dispatch cases select both profiles, with
Rust-native explicitly unsupported.
The P0 snapshot run `296735f7-a06b-465e-958b-44f40b32b88c`, finished at
`2026-09-28T12:04:18.052Z`, selected 181 comparisons: 175 passed, zero failed,
six `not_run`, and zero infrastructure errors. All 118 package comparisons
passed; Rust-native passed 57 of 63. Its six `not_run` cases are four
Python-callable boundaries and two Mount cases. All six slash-redirect, four
RedirectResponse, eight basic Response/JSONResponse, and four finite
synchronous StreamingResponse cases passed on both profiles; the async iterator
passed on the Python package; all 21 reverse-URL cases
passed on the Python package, and no named Rust-native route API is claimed.
Target identities were dirty local trees, so the run is not clean aggregate or
release proof. The static merger check passes against the pinned Starlette
commit.

## P1 — Complete the Python/Rust boundary prototype (remaining)

The current slice crosses the Python/Rust boundary for a bounded set of
request and ASGI flows. Exact Python-package parity now covers async Request
endpoints, synchronous functions, bound methods and partials through AnyIO,
plus callable-instance routes invoked as ASGI apps. The remaining boundary
work includes cancellation, broader exception identity/chaining, streaming
backpressure, broader lifespan state and concurrency, and other Python/Rust
ownership decisions. The new bounded generator-lifespan slice covers sync and
async entry/cleanup, startup/shutdown failures, synchronous callback-call
failures, special-method lookup, extra-yield errors, and shutdown-error
suppression. Rust implements the generator context-manager protocol and calls
the Python generator methods through PyO3. Python owns user callables and event
loop execution. The
HTTPException slice covers exceptions raised before response start by
matched HTTP request-style endpoints, one callable-ASGI exception after
response start, status-code handler precedence over an HTTPException class
handler, and async-handler reuse of a body consumed by the endpoint. The
server-error slice now covers default and registered 500 handling, special
handler-key order, text/HTML debug responses, response-start state, and handled
`HTTPException(500)`. At the earlier WebSocket checkpoint, 21 comparisons
passed: six protocol-tape cases on the Python package, six state projections
on both targets, and three route-dispatch cases on the Python package. Later
inputs add convenience/close behavior and three app-level exception flows:
the built-in close handler, an HTTP denial response, and a custom close handler.
TestClient propagation, TestClient WebSocket sessions, direct middleware
invocation, and arbitrary middleware ordering remain open.

## P2 — Scoped ASGI and WebSocket workflows (bounded parity recorded)

The P2 checkpoint input set is
[`asgi-http-get-text.yaml`](../../tests/fixtures/sources/parity/asgi-http-get-text.yaml),
[`asgi-request-items.yaml`](../../tests/fixtures/sources/parity/asgi-request-items.yaml),
[`gzip-middleware.yaml`](../../tests/fixtures/sources/parity/gzip-middleware.yaml),
[`asgi-http-exceptions.yaml`](../../tests/fixtures/sources/parity/asgi-http-exceptions.yaml),
[`asgi-callable-http-exceptions.yaml`](../../tests/fixtures/sources/parity/asgi-callable-http-exceptions.yaml),
[`asgi-exception-handlers.yaml`](../../tests/fixtures/sources/parity/asgi-exception-handlers.yaml),
[`asgi-server-errors.yaml`](../../tests/fixtures/sources/parity/asgi-server-errors.yaml),
[`websocket-protocol.yaml`](../../tests/fixtures/sources/parity/websocket-protocol.yaml),
[`websocket-state-sequence.yaml`](../../tests/fixtures/sources/parity/websocket-state-sequence.yaml),
[`websocket-route-dispatch.yaml`](../../tests/fixtures/sources/parity/websocket-route-dispatch.yaml),
[`router-converter-dispatch.yaml`](../../tests/fixtures/sources/parity/router-converter-dispatch.yaml),
[`request-path-param-types.yaml`](../../tests/fixtures/sources/parity/request-path-param-types.yaml),
[`mount-route-dispatch.yaml`](../../tests/fixtures/sources/parity/mount-route-dispatch.yaml),
[`reverse-url-routing.yaml`](../../tests/fixtures/sources/parity/reverse-url-routing.yaml),
[`redirect-response.yaml`](../../tests/fixtures/sources/parity/redirect-response.yaml),
[`responses-basic.yaml`](../../tests/fixtures/sources/parity/responses-basic.yaml),
and [`streaming-response.yaml`](../../tests/fixtures/sources/parity/streaming-response.yaml).
The manifest contains 118 cases across 18 files: four direct ASGI cases (`GET
/hello` with lifespan, `GET /missing`, `POST /hello`, and a public slash
redirect); eight basic Response/JSONResponse cases; four finite synchronous
StreamingResponse cases and one finite async-iterator case; four RedirectResponse cases; 38 request/routing cases covering Request dispatch, built-in
converters, typed path values, slash redirects, Mount, and `WebSocketRoute`;
21 reverse-URL cases; six WebSocket protocol-tape cases; six WebSocket
state-projection cases; eight `GZipMiddleware` cases; five Request-style
HTTPException cases; two callable-ASGI HTTPException cases; two
registered-handler cases; and nine server-error cases. The latest run
`296735f7-a06b-465e-958b-44f40b32b88c`, finished at
`2026-09-28T12:04:18.052Z`, selected 181 comparisons: 175 executed and passed,
zero failed, six Rust-native rows were `not_run`, and there were zero
infrastructure errors. All 118 Python-package cases passed; Rust-native passed
57 of 63 selected comparisons. The six `not_run` cases cover four
Python-callable forms and two Mount cases. All six slash-redirect, four
RedirectResponse, eight basic Response/JSONResponse, four finite synchronous
StreamingResponse, and the finite async-iterator package comparison, all 21
reverse-URL, and all 21 WebSocket comparisons passed.
Target identities were dirty local trees, so the run is not clean aggregate or
release proof. The
new handler inputs check that status 405 beats a previously registered
HTTPException class handler, and that an async subclass handler can read a
chunked request body already cached by the endpoint. The other HTTPException
cases cover five matched HTTP request-style endpoint exceptions before
response start and two callable-ASGI exceptions (one before and one after
response start); the after-start case captures the chained RuntimeError and
partial event tape. The server-error inputs check default 500 behavior,
registered handlers, special handler-key order, debug text/HTML responses,
response-start behavior, and handled `HTTPException(500)`. The Rust-native
response builder does not resolve default Python status phrases and cannot
invoke arbitrary Python ASGI callables. This status does not claim the full
Starlette surface is compatible. See the
`build/parity/parity-result.json`.

The six cases in `websocket-protocol.yaml` drive raw `WebSocket.receive()` and
`WebSocket.send(message)` actions across handshake/text/close, disconnect
return, invalid transition, receive after disconnect, binary exchange, and a
connected send callback raising `OSError`. They select the complete ordered
receive/send ASGI callback tape for the Python-package profile, including each
attempted send when the callback raises. The six cases in
`websocket-state-sequence.yaml` duplicate those action sequences and compare
each action's outcome and optional exact error message plus both final states
across source, Python package, and Rust-native profiles; they exclude payloads,
callback tapes, and Python exception metadata. The three cases in
`websocket-route-dispatch.yaml` cover a matched root-path route, an unmatched
WebSocket Router close, and a standalone `WebSocketRoute` called with an HTTP
scope. They select route scope, ASGI events, response status, and response
bytes for the Python-package profile. The inputs contain no expected outputs.
All 21 WebSocket comparisons passed in the run above. JSON convenience
methods, iterators, and denial-response behavior remain package-test-only and
in the parity backlog.

The separate Router/GZip benchmark lane completed all 74 source-versus-package
workloads. Its result is documented in [Benchmark mapping](../BENCHMARKS.md);
Rust-native remains `not_run` for those non-equivalent workloads. Benchmark
completion is evidence for that workload catalog only; see its
`build/parity/upstream-benchmark-result.json`.

The declared workflows exercise these public consumer interfaces:

1. Construct a Starlette application with a `GET /hello` route and a
   `PlainTextResponse` endpoint.
2. Define a fresh HTTP ASGI scope and `http.request` message for each case and
   separate source-oracle, Rust-native, and installed-package targets.
3. Select response-start status, ordered/repeated headers, response body bytes,
   ASGI send-event order and termination, raised public exception identity and
   observable payload when applicable, and lifecycle/cleanup effects.
4. The adjacent route-miss and wrong-method workflows are now present for both
   the `/hello` route and the request-observer route. Their expected status or
   error values stay in live observations, never in input files.
5. Require exact oracle/target observations by default and retain distinct
   results for the Rust-native and Python-package targets.

This is a partial implementation increment. It does not narrow the full
Starlette compatibility target, establish project-wide drop-in status, or
assert exact parity before the coordinated gate records that result.

## P3 — Expand by atlas requirements

Implement routing, connections, requests/responses, middleware, authentication,
background tasks, data structures, forms/uploads, remaining StaticFiles edge cases, templates,
schemas, configuration, WSGI, and TestClient in dependency-aware groups.
Promote remaining fixture-backlog entries into the single active manifest as
independent inputs and keep unsupported behavior visible until implemented
and compared.
