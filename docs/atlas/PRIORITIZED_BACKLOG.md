# Compatibility atlas and implementation backlog

**Authority:** Starlette 1.6.0, commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. This document records work order
and links to bounded evidence; it is not itself a parity artifact or a claim
of full compatibility. The full replacement objective remains active and
incomplete.

## Current parity snapshot

The active contract contains 757 input-only cases in 84 indexed files,
covering 94 operations and 787 parity requirements. Recent additions include route-local HTTP exception responses observed through mounted middleware; custom `BaseUser` property overrides, `Request.user` type and `Request.auth.scopes` observations, and the documented login `next` query redirect; a Starlette multipart upload through `Request.form()` under the app body limit; direct UploadFile constructor/repr, rollover, and
threadpool-boundary inputs; GZip final/streaming thread-threshold comparisons;
the shared AnyIO thread-pool limiter; generic Request/WebSocket lifespan-state
typing; routed authentication UI and protected HTTP routes; six protected WebSocket cases for plain and injected endpoint forms, and three documentation-derived BasicAuth cases for wrong-scheme, malformed base64, and non-ASCII credentials.
Seven QueryParams
cases map equality and blank-value behavior to two pinned test rows. New
focused inputs cover
surrounding pure-ASGI ContextVar observations around BaseHTTPMiddleware and a
pure-ASGI control, CORSMiddleware private-network-access denial, empty-text
default decoding in WebSocketEndpoint, TestClient lifespan task/RunVar
continuity, and task-group child lifecycle under asyncio and Trio. Rust-backed
`CommaSeparatedStrings` parsing and sequence formatting, including lone
surrogate values, are included, alongside
the three-request CORS
origin-isolation input, five async Request endpoint
callable-shape and failure cases, three direct `run_in_threadpool` cases,
including the shared AnyIO limiter,
`iterate_in_threadpool` iteration and async-generator protocol behavior,
Config casts, TestClient debug responses, synchronous Request endpoint worker
cancellation and failure, ASGI callable-instance success and failure, direct
State sequences, application state reads through `request.app.state`,
application registration workflows, six direct
ServerErrorMiddleware cases, three TestClient exception-chain cases covering
no chain, implicit context, and explicit cause through BaseHTTPMiddleware, a
default middleware-boundary trace, and sixteen Request.cookies inputs pass live
source/package comparison, including the sequential TestClient cookie
round-trip from `test_request_cookies`. Added direct `GZipResponder` inputs and
invalid WebSocket JSON-mode inputs pass exact source/package comparison. Three
StaticFiles HTML fallback scenarios and seven built-in float/UUID converter
cases now pass on both target profiles. Default-string match/slash-boundary
and int/path converter scope inputs also pass on both profiles. The
input-defined datetime converter dispatch and reverse-format cases pass on the
Python-package profile. The file-like StreamingResponse case compares exact
binary line chunks through the installed Python package. The latest integrated run for the active
`parity-input@29` contract, `b0b0f52e-5c0f-488d-8d42-a51b174e6b9e`, passed
968 of 972 selected comparisons, with zero failures or infrastructure errors
and four Rust-native Python-callable rows `not_run`. The Python package passed
755/755; Rust-native passed 213/217. The four native `not_run` rows are
synchronous Request endpoint, bound-method endpoint, partial endpoint, and
callable-instance ASGI dispatch. `make test` exits with status 2 for those
declared rows. Full run identities and package hashes are recorded in
[Migration parity contract and evidence](../PARITY.md); this bounded evidence
does not establish full Starlette parity or release readiness.

The six protected-WebSocket authentication cases map the upstream
`test_websocket_authentication_required` row across plain and injection-wrapped
endpoints. The full replacement remains active and incomplete; these slice
results do not establish full Starlette parity.

The endpoint-callable-shapes backlog item is mapped in the generated coverage
matrix. The package-only input slice covers async functions, bound methods,
single or nested partial construction, sync function/bound-method/partial
success and failure, and callable instances dispatched as ASGI apps with
success and failure observations. Exact parity for these selected inputs does
not establish all callable or exception behavior.

The current coverage matrix has 802 source rows: 488 input mappings,
51 source-backed `not_applicable` rows, and 263 fixture-backlog rows. Derive
these changing counts from the generated atlas CSV files. The compatibility
objective remains active and incomplete. See
[Migration parity contract and evidence](../PARITY.md) for run evidence.

The `Starlette.max_body_size` behavior row is mapped to five live
application/route limit inputs in
[`route-body-limits.yaml`](../../tests/fixtures/sources/parity/route-body-limits.yaml).
They compare inherited, zero, raised, and lowered limits, plus declared
content-length precheck behavior, with request bodies and exact response events.

The `Starlette.mount()` behavior row is mapped to the named StaticFiles
registration and GET/POST dispatch in
[`testclient-http.yaml`](../../tests/fixtures/sources/parity/testclient-http.yaml).
The package-only oracle comparison observes the resulting Mount route, child
scope values, file response, method rejection, and ordered ASGI events.

The latest Request.form inputs compare default and custom multipart part-size
limits through direct and mounted consumers, including short-circuiting before
a later body chunk; duplicate text and file values through `multi_items()`;
2,000 text fields and 2,000 files under raised limits; stream and tempfile-write
failure cleanup; worker-thread rollover followed by request cleanup; and
direct/Mount unique and mixed 1,001-file count failures. The fixture source is
[`request-form-multipart.yaml`](../../tests/fixtures/sources/parity/request-form-multipart.yaml).
Each output comes from the pinned Starlette 1.6.0 oracle and installed package.

## P0 — Close the source-backed atlas (complete)

The merged review disposes all 999 API candidates as `supported`,
`private/internal`, or `uncertain`, with pinned-source evidence. It maps all
514 upstream test functions, 24 documentation navigation pages, and four
shared test support modules into the [coverage matrix](coverage-matrix.csv).
At the P0 atlas-close checkpoint, the matrix had 799 source rows: 278 existing
input mappings, 50 reasoned `not_applicable` entries, and 471 fixture backlog
rows. It mapped selected
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
callable-instance routes invoked as ASGI apps, and basic BackgroundTask and
BackgroundTasks execution. Response-attached tasks also cover bound-method,
callable-object, and partial callable shapes, plus async cancellation after the
callback starts with cancellation and finalizer observations. The synchronous
background cancellation input holds the worker callback until cancellation
reaches the response task, then compares worker completion and propagated
cancellation; it passes in the latest full source/package run.
The new synchronous Request worker-cancellation input matches source/package
behavior for cancellation requested after AnyIO worker entry, worker
finalization and completion, and the propagated cancellation error. Remaining
boundary work includes exception identity/chaining beyond the bounded
TestClient propagation cases,
streaming backpressure, broader lifespan state and concurrency, and other
Python/Rust ownership decisions. The new bounded generator-lifespan slice
covers sync and async entry/cleanup, startup/shutdown failures, synchronous
callback-call failures, special-method lookup, extra-yield errors, and
shutdown-error suppression. Rust implements the generator context-manager
protocol and calls the Python generator methods through PyO3. Python owns user
callables and event-loop execution. The
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
TestClient propagation and TestClient WebSocket sessions remain open. Six
direct `ServerErrorMiddleware` inputs are now authored for construction,
custom/default handler dispatch, and post-construction field mutation; all six
passed source/package comparison in run `30a58707-ee2a-4146-b14d-2f0b104af348`. Arbitrary middleware
ordering remains open.

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
attempted send when the callback raises. The ten cases in
`websocket-state-sequence.yaml` duplicate those action sequences and add direct
denial-response start, continued-body, final-body, and duplicate-start
transitions. They compare each action's outcome and optional exact error message
plus both final states across source, Python package, and Rust-native profiles;
they exclude payloads, callback tapes, and Python exception metadata. The three
cases in `websocket-route-dispatch.yaml` cover a matched root-path route, an unmatched
WebSocket Router close, and a standalone `WebSocketRoute` called with an HTTP
scope. They select route scope, ASGI events, response status, and response
bytes for the Python-package profile. The inputs contain no expected outputs.
The `websocket-convenience.yaml` inputs exercise JSON and typed methods,
iterator controls (including `asend(non-None)` before the first yield), and
denial-response callbacks for the Python-package profile. They compare live
source and installed-package results, callback order, and final state; the
manifest does not claim a Rust-native Python convenience-iterator surface.
The latest clean full-slice run `edb648a3-8fd4-4534-865d-8d85dac984c4`
selected 957 comparisons: 953 passed, with four declared Rust-native
Python-callable comparisons left `not_run` and zero failures or infrastructure
errors. The authentication WebSocket row is now mapped; other WebSocket source
rows remain in `fixture-backlog.csv`, and similar method names do not close
rows whose stimuli or observation selectors differ.

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
additional synchronous background-task cancellation schedules and remaining data structures,
forms/uploads, remaining StaticFiles edge cases, templates,
schemas, configuration, and TestClient in dependency-aware groups. The mapped
WSGI middleware, `build_environ`, and import-deprecation behaviors now have
input-only comparisons; keep any additional WSGI source rows in the backlog
until directly mapped.
Promote remaining fixture-backlog entries into the single active manifest as
independent inputs and keep unsupported behavior visible until implemented
and compared.
