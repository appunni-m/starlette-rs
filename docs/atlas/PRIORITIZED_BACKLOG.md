# Compatibility atlas and implementation backlog

**Authority:** Starlette 1.6.0, commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. This document records work order
and links to bounded evidence; it is not itself a parity artifact or a claim
of full compatibility. The full replacement objective remains active and
incomplete.

## Current parity snapshot

The active contract uses `parity-input@39` with 929 input-only cases in 91
indexed files: 927 oracle parity cases and two target-only fault contracts. It
covers 104 operations and 901 parity requirements.

The latest clean full-slice preflight
`d3ebe854-b035-45af-98b5-45ae6e72d83d` selected 1,175 profile comparisons:
1,171 passed, zero failed, zero infrastructure errors, and four Rust-native
callable-boundary cases were `not_run`. The installed Python package passed
925/925 comparisons; Rust-native passed 246/250. Both target-only fault
contracts passed (2/2) and remain `not_applicable` to the source oracle. The
active manifest SHA-256 is
`d2353e4a5aa660147c39f9567241f4104bb58029ffd5cb219284093bf899014b`; the
target was clean at `b56ee2a609c07c62c03291c7441b228db5c73351`. This is bounded
package-slice evidence, not full Starlette parity.

The nested TestClient case also passed focused selected run
`8c90f08e-3bf0-4ea2-9d98-0c7f8de847a2` (1/1 source/package comparison and 2/2
target-only fault contracts). Coverage MCP verified 26 newly covered Rust
lines (0.106 percentage points): baseline 2,774/24,539, batch 2,755/24,539,
and union 2,800/24,539. Full-suite regression status is unknown. The run and
coverage receipts are recorded in [Migration parity contract and evidence](../PARITY.md).

The correctness-gated benchmark `eaea39eb-c40f-448a-b2fd-1907c75f4ae7`
measured 74/74 source/package workloads with zero failures; Rust-native remains
`not_run` for all 74 boundaries. See [Benchmark mapping](../BENCHMARKS.md) for
workload-specific timings and hashes.

The preceding 927-case full-slice run was recorded against the prior manifest:
`a0bcf0da-4746-4490-843d-45653d987ea1` selected 1,160 profile comparisons:
1,156 passed, zero failed, zero infrastructure errors, and four Rust-native
Python-callable cases were `not_run`. The Python package passed 912/912
comparisons; Rust-native passed 244/248. The target-only route-cache poison
fault contract also passed its HTTP 500 status and body assertions. The result
artifact and target build identity are recorded in
[Migration parity contract and evidence](../PARITY.md).

The active contract also maps `routing.test_lifespan_state_async_cm` to the
Router state propagation exercised through TestClient. Instrumented run
`f54a933e-0dbf-441f-9d25-78eb7bfa3556` passed one exact source/package case and
both target-only fault contracts; oracle applicability remains
`not_applicable` for those fault rows. Coverage MCP verified 470 newly covered
Rust lines and a 1.915-point gain from a matching baseline, with 3,244/24,539
lines covered after union. Full-suite regression status remains unknown. See
[Migration parity contract and evidence](../PARITY.md) for report receipts and
build identities.

The mixed-protocol Router source test `routing.test_protocol_switch` is now
mapped to one HTTP and two WebSocket TestClient inputs. Selected run
`29e8e772-6df8-46ee-9be9-05f8c1a57859` passed all three source/package
comparisons. The two target-only route-cache fault contracts also passed in
selected run `ed8dd93c-32d2-478c-9a50-4bbff0427a6a`.

Earlier focused runs on the 917-case manifest passed the normal route and both
target-only fault contracts: `189e7aa9-c5e9-4da9-8b22-27761ae7e537`,
`68288f42-aaa7-4af3-8106-f35e69cdf9b7`, and
`cfe1e118-7b1b-4988-8a39-842fe48eb846`. Coverage MCP verified the isolated
exception-propagation case against the normal-route baseline and reported 249
newly covered Rust lines; it did not check full-suite regressions.

The preceding 922-case manifest maps the ten-layer
`test_multiple_middlewares_stacked_client_disconnected` behavior. Selected run
`3202352e-f31a-416f-92d0-471df84a52fa` passed that oracle comparison and both
target-only fault contracts. Coverage MCP's matching-receipt incremental
comparison found 1,230 newly covered Rust lines; full-suite regressions were
not checked. The fixture mapping and evidence details are in
[Migration parity contract and evidence](../PARITY.md).

The preceding 923-case contract added concurrent BaseHTTPMiddleware response
background-task completion. Normal selected run
`44a904ac-ec91-46c6-9363-68c9ddfeea77` passed one source/package parity case
and both target-only route-cache fault contracts. Coverage MCP verified 701
new Rust lines and a 2.857-point incremental gain from a matching instrumented
batch; the full suite was not rerun, so regression status remains unknown.
Fault rows remain `not_applicable` to the oracle. Evidence details are in
[Migration parity contract and evidence](../PARITY.md).

The preceding 925-case contract adds ASGI parity inputs for the default
`StaticFiles(follow_symlink=False)` behavior on external file and directory
symlinks. Selected run `1c302ec6-419c-470c-b8e8-e8f33aa84559` passed four
source/package profile comparisons and both target-only route-cache fault
contracts; the fault rows retain oracle applicability `not_applicable`. This
selected batch makes no new coverage claim and does not rerun the full suite.
Evidence details are in [Migration parity contract and evidence](../PARITY.md).

The preceding 926-case contract maps `routing.test_raise_on_shutdown` to an actual
`Router(lifespan=...)` used through TestClient. Selected run
`c5a9cc24-5d27-40d3-ab2f-52e6781d6ee6` passed the source/package comparison and
both target-only route-cache fault contracts; the fault rows remain
`not_applicable` to the oracle. The result SHA-256 is
`7b8fbf52f10ca1fa96015939962975cafea7ae6758217a4a0985b3ff297f25f0`, and the
manifest SHA-256 is
`d5c7a33a96974b63fd6714ee20c7242a24522aa0100978f1609a023c0f9f4224`. This
normal selected run does not claim full-suite parity; the incremental coverage
comparison is recorded below.

The then-active 928-case contract maps `routing.test_raise_on_startup` to an actual
`Router(lifespan=...)` whose input-defined lifespan context manager raises
`RuntimeError` before yielding. Instrumented selected run
`1323e01e-4cac-40fb-a940-88d31f770fca` passed the source/package comparison and
both target-only route-cache fault contracts; fault applicability remains
`not_applicable`. Its result SHA-256 is
`a60726b009a3a37734c53df8d7cf63782694763c114e1e8244980dfcc2e7c6a1`, and the
active manifest SHA-256 is
`800e7040a68b7ace38b5b0ce253a0d6c61d310ea5d684c63dab880833e2a151b`.

Coverage MCP verified 378 newly covered Rust lines (1.540 percentage points)
against a matching normal-route baseline: baseline 2,774/24,539, batch
2,491/24,539, and union 3,152/24,539. The result is `improved`; full-suite
regression status is unknown because the full suite was not rerun. The
comparison binds to target tree SHA-256
`4a20992251ed71021e5b00dc139989618fef141a04e19ce62022488fe5de3655` and
instrumented wheel SHA-256
`4a7f21daede2267586ddbb9d7ced7d8993fd9a4a9b8e46bd178ef8c76b48bd2a`; see
[Migration parity contract and evidence](../PARITY.md) for run IDs and receipts.

The preceding clean full-manifest preflight for the 927-case contract
`ff54cb4d-3390-463b-8ffd-96febc69b24b` selected 1,173 profile comparisons:
1,169 passed, zero failed, zero infrastructure errors, and four Rust-native
callable-boundary rows were `not_run`. The installed Python package passed
923/923 comparisons; Rust-native passed 246/250. Both target-only route-cache
fault contracts passed and remain `not_applicable` to the source oracle. The
result SHA-256 is
`4f7fa49a8a13e41205ad47cc2743779f23cc8aff2e26ab1d88a17c68806c1a0d`; manifest
SHA-256 is
`800e7040a68b7ace38b5b0ce253a0d6c61d310ea5d684c63dab880833e2a151b`. This
active package-slice evidence does not establish full Starlette parity; details
are in [Migration parity contract and evidence](../PARITY.md).

The preceding clean full-manifest preflight for the 926-case contract
`5a69e4da-e6e8-47d6-b4d9-01f613c41e77` selected 1,172 profile comparisons:
1,168 passed, zero failed, zero infrastructure errors, and four Rust-native
callable-boundary rows were `not_run`. The installed Python package passed
922/922 comparisons; Rust-native passed 246/250, and both target-only
route-cache fault contracts passed. The preflight remains bounded evidence and
does not establish full Starlette parity; details are in
[Migration parity contract and evidence](../PARITY.md).

Coverage MCP compared the Router shutdown-error case plus both target-only
fault contracts against a matching instrumented normal-route baseline. Matching
source/build receipts verified 431 newly covered Rust lines (1.756 percentage
points): baseline 2,774/24,539, batch 2,543/24,539, and union 3,205/24,539.
The result is `improved`; full-suite regression status is unknown because the
full suite was not rerun. Reports bind to active manifest SHA-256
`d5c7a33a96974b63fd6714ee20c7242a24522aa0100978f1609a023c0f9f4224`, target
tree SHA-256
`35c05c09bccec31ff3b6eed9126860907a6c87dfcd8299a64997c0e6f25cf78f`, and
instrumented wheel SHA-256
`ee0994b002a34a6ab4ecb84f1a2ce1a4fd892d7c2821af6ccac50703a1c2b755`. See
[Migration parity contract and evidence](../PARITY.md) for the run IDs and
receipts location.

The prior 920-case full preflight `84769d51-0203-41bf-8569-be53a5cbe99c`
passed 916/916 Python-package comparisons and both fault contracts. Rust-native
passed 244/248; four callable-boundary cases were `not_run`. Its
correctness-gated benchmark `d0bba2ec-079e-4d21-822e-e0ddbf0133ef` measured all
74 source/package workloads; 74 Rust-native rows remain `not_run` at a
non-equivalent ASGI boundary. The full Starlette compatibility denominator
remains incomplete.

The generated coverage matrix contains 804 source rows: 660 input mappings,
51 reasoned `not_applicable` rows, and 93 fixture-backlog rows. These changing
counts are derived from the generated atlas CSV files. The pinned denominator remains 514 upstream test
functions and 24 documented pages. Four Rust-native `not_run` rows remain for
synchronous Request endpoints, bound methods, partials, and callable-instance
ASGI dispatch. This selected slice does not establish full Starlette parity or
release readiness; the full replacement goal remains active and incomplete.

The six protected-WebSocket authentication cases map the upstream
`test_websocket_authentication_required` row across plain and injection-wrapped
endpoints. The StaticFiles lookup TimeoutError path now maps the upstream 500
response case through TestClient. The full replacement remains active and
incomplete; these slice results do not establish full Starlette parity.

The endpoint-callable-shapes backlog item is mapped in the generated coverage
matrix. The package-only input slice covers async functions, bound methods,
single or nested partial construction, sync function/bound-method/partial
success and failure, and callable instances dispatched as ASGI apps with
success and failure observations. Exact parity for these selected inputs does
not establish all callable or exception behavior.

The current coverage matrix has 804 source rows: 660 input mappings,
51 source-backed `not_applicable` rows, and 93 fixture-backlog rows, as
reported by the generated atlas. The compatibility objective remains active and incomplete. See
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
The latest full-slice run `65044ac3-c6fc-4bdb-9b3b-422ef77afdc7` selected
1,158 comparisons: 1,154 passed, with four declared Rust-native
Python-callable comparisons left `not_run` and zero failures or infrastructure
errors. The TestClient URL-prefix merge and followed-redirect behaviors, the
WebSocket send-callback `OSError` behavior, and both TestClient
`Request.url_for` contexts have exact source/package mappings; other WebSocket
source rows remain in `fixture-backlog.csv`, and similar method names do not
close rows whose stimuli or observation selectors differ.

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
