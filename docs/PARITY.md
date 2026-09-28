# Migration parity contract and evidence

The active input contract is [`tests/fixtures/manifest.yaml`](../tests/fixtures/manifest.yaml), using `migration-parity/manifest@2` with `scope.mode: slice`. It contains 196 input-only cases in 29 indexed files, covering 43 operations and 242 parity requirements. The cases cover bounded Starlette application, routing, request, response, WebSocket, exception, status, endpoint, authentication, middleware, configuration, and schema behavior. The manifest is the authority for exact operation and target-profile applicability. The current scope is bounded; it does not claim full Starlette API or behavioral parity.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source references and the source roots used by the API and compatibility inventories. The active manifest is separate: its `input_index` points to generated runtime JSON beneath `build/parity/inputs/`.

Parity and benchmark inputs are authored as JSON-compatible YAML under [`tests/fixtures/sources/parity/`](../tests/fixtures/sources/parity/) and [`tests/fixtures/sources/benchmark/`](../tests/fixtures/sources/). Run `make parity-inputs` or `python3.12 -m scripts.parity.generate_inputs` to serialize the indexed source definitions as JSON under `build/parity/inputs/{parity,benchmark}/`; `make contract-check` regenerates those files before offline contract validation. Generated inputs and parity/benchmark result JSON beneath `build/parity/` are ignored local build outputs, not checked-in fixtures or committed artifacts. Recreate them locally before running a parity or benchmark command.

The compatibility authority is Starlette 1.6.0 at commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The live source oracle checks the release, commit, source import path, source `uv.lock` digest, and CPython identity before it executes any case.

## Input-only cases

[`asgi-http-get-text.yaml`](../tests/fixtures/sources/parity/asgi-http-get-text.yaml) contains JSON-compatible input values and observation selectors only. The generator serializes this authored definition to runtime JSON; no source definition stores expected status, headers, body, response messages, or lifecycle trace. Every case constructs one app with a public GET `/hello` route returning a `PlainTextResponse`; the endpoint makes two public `Response.set_cookie` calls. The successful case also declares an async-context lifespan callback and sends startup then shutdown.

The Python target runs the installed `starlette-rs-py` `Starlette` ASGI callable with a real Python scope, receive callback, and send callback. The Rust target constructs the exported `starlette_rs::Starlette` with an `ApplicationRoute` and calls its async `call` method with the scope's path/method projection and Rust future-based callbacks. It awaits response-start then response-body sends. The fixed endpoint does not read request input, so the Rust receive callback remains unused, matching the Python endpoint's behavior. The native API does not model every ASGI scope field, host an executor, or invoke Python endpoints.

The `/missing` case requests GET for an absent path. The wrong-method case requests POST for the existing GET-only path. These are separate workflows with their own source and target observations, so 404 and 405 behavior is measured rather than encoded as expected output.

[`asgi-request-items.yaml`](../tests/fixtures/sources/parity/asgi-request-items.yaml) adds three cases with a separate `request-dispatch` observation profile. Each case constructs one GET `/items/{item_id:int}` route whose declarative `request-observer` endpoint reads a Request and returns the input's fixed plain-text response marker. The successful input requests `/items/0007?tag=red&tag=blue`, supplies a lowercase ASGI header that the endpoint looks up using mixed-case names, a cookie, and JSON split across two `http.request` messages. The two other inputs exercise a route miss at `/items/nope` and POST `/items/7` against the GET-only route. All response observations come from the live source and targets; the input file contains only route/request stimulus and observation selectors.

The request observation record selects the converted path parameter and runtime type, `QueryParams.getlist` plus scalar lookup, two differently cased `Headers` lookups, the parsed cookie, and `await Request.json()`. A separate scope observation records identity checks for `app`, `router`, and `endpoint`, path-parameter presence, and the resulting `path_params` mapping. The installed Python target checks live object identity; the Rust-native request adapter builds a routed-scope model and checks identity-token references. This model applies to the three `request-dispatch` cases only; their evidence does not exercise a public Rust `Request` or the new native `Starlette::call` API. The full ASGI response events remain exact, with only the declared `Allow` token-set normalization.

The upstream basis is `starlette/requests.py` (`HTTPConnection.headers`, `query_params`, `path_params`, `cookies`, and `Request.stream`/`body`/`json`), `starlette/datastructures.py` (`ImmutableMultiDict` and `Headers`), and `starlette/routing.py` (`Route.matches` and `Router.app`). Related pinned tests include `tests/test_requests.py::test_request_query_params`, `test_request_headers`, `test_request_cookies`, `test_request_json`, `tests/test_routing.py::test_route_converters`, and `test_router`.

[`router-converter-dispatch.yaml`](../tests/fixtures/sources/parity/router-converter-dispatch.yaml)
adds 15 Router cases for built-in `str`, `int`, `float`, `uuid`, and `path`
converters, invalid paths, route declaration order, `root_path` matching and
prefix boundaries, and a Python-registered override of `str`. The Rust route
table and installed package are compared for built-in matching, misses,
ordering, and root-path behavior; the custom converter case is package-only.
Observations include response events and the selected route index.

[`router-slash-redirect.yaml`](../tests/fixtures/sources/parity/router-slash-redirect.yaml)
adds five direct Router cases and one public `Starlette.__call__` case. Inputs
cover slash append with `root_path` and a query, removal of repeated trailing
slashes, a candidate path that only partially matches by method, disabled
redirects, and an absent counterpart. The source oracle and both target
profiles observe the live response; the inputs declare no expected status or
`Location` value.

[`redirect-response.yaml`](../tests/fixtures/sources/parity/redirect-response.yaml)
adds four public `RedirectResponse` ASGI-call cases for the default 307 status,
Unicode URL quoting, the generated zero-length `Content-Length`, and
case-insensitive replacement of a mixed-case `Location` header while keeping
the caller's header order and `Content-Length`. All four cases passed against
the source on both target profiles.

[`responses-basic.yaml`](../tests/fixtures/sources/parity/responses-basic.yaml)
adds three direct ASGI-call cases for text and byte `Response` bodies plus
`JSONResponse(None)`. They preserve the upstream `text/plain` and `image/png`
media types and exercise JSON null serialization to the bytes `null`. All
three cases passed against the source on both target profiles.

[`streaming-response.yaml`](../tests/fixtures/sources/parity/streaming-response.yaml)
adds four direct `StreamingResponse` ASGI-call cases for finite synchronous
chunks: no generated `Content-Length`, preservation of an explicit length,
`text/plain` framing across five text chunks, and pass-through of one base64-
defined binary chunk. It also adds the input from Starlette's
`test_streaming_response_custom_iterator`, a finite async iterator yielding
`"1"` through `"5"`; the installed package emits each chunk as it is yielded.
The four synchronous cases passed on both target profiles, and the async
iterator case passed against the source and installed Python package. The
async-iterator case is package-only while Rust-native async streaming is
pending. Starlette has no dedicated raw-bytes streaming test; the byte case
probes its source implementation's bytes pass-through branch directly. These
cases do not establish iterator cancellation, disconnect races, background
task behavior, ASGI 2.4 `OSError` mapping, or memoryview type parity.

[`request-path-param-types.yaml`](../tests/fixtures/sources/parity/request-path-param-types.yaml)
adds six installed-package Request cases for typed path parameters, including
a 5001-digit integer that exercises CPython 3.12's default conversion limit.
[`mount-route-dispatch.yaml`](../tests/fixtures/sources/parity/mount-route-dispatch.yaml)
adds two Mount cases for child `root_path`, `app_root_path`, merged path
parameters, response, and mount miss. The source and Python package execute
both Mount cases; Rust-native records them as unsupported because it has no
Mount API.

[`reverse-url-routing.yaml`](../tests/fixtures/sources/parity/reverse-url-routing.yaml)
adds 21 input-only cases for `Route`, `WebSocketRoute`, `Router`, `Mount`,
`Starlette`, and `Request` reverse URL generation. It covers the built-in path
converters, converter failures, a custom converter override, first-success
route selection, nested mounts, `Request.url_for` provider and root-path
behavior, and the application forwarder. The Python package passed all 21
cases. The Rust route table now builds converter-formatted paths for the Python
bridge, while a Rust-native named Route/Router API remains unimplemented and is
not claimed by this slice.

[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
adds three package-profile cases for environment mapping read freezes, config
lookup precedence and casts, and missing-file warnings.
[`schemas-runtime.yaml`](../tests/fixtures/sources/parity/schemas-runtime.yaml)
adds four package-profile cases for schema route selection and path conversion,
docstring YAML parsing and parser errors, and OpenAPI response rendering. Their
Python `starlette.*` modules forward to Rust; the adapters run the same
input-only cases against pinned Starlette 1.6.0.

The latest integrated run `5e4c615e-a9e4-4305-bd7a-850b21f427d7` finished at
`2026-09-28T20:46:05.868Z`, after starting at `2026-09-28T20:45:33.579Z`. It
selected 267 profile comparisons: the Python package passed 194 of 196, and
Rust-native passed 65 of 71 selected cases. Two Python-package debug traceback
cases failed; there were zero infrastructure errors. Four arbitrary Python
callable boundaries and two Mount cases are declared unsupported for
Rust-native, so six rows are `not_run`. The CLI exits with status 2; this is
not an all-target pass. Manifest SHA-256 is
`c208c4c65d1cb4c08d544b9ac74e8835092bacbd6114b3b8a0ef0b874d349211`; the
installed wheel SHA-256 is
`e23ea2c9d10e4e7e6a732bedabff0d525df58d9e2b5fb3c430a350d0d6aec3ea`. The
Python-package target tree was dirty during this local run, so it is not clean
aggregate or release proof. The two failures are
`starlette.applications.Starlette.__call__.server-error.debug.plain-text-overrides-handler`
and `.debug.html-selected-by-accept`: the endpoint exception is the same, but
the Rust-backed thin facade produces a different internal traceback frame
stack and source context. The comparator preserves those differences instead
of normalizing them away.

The synchronous function case, `starlette.applications.Starlette.request-dispatch.sync-get-items-0007-contextvar-worker`, sends `GET /items/0007` through a route declared as `/items/{item_id:int}`. It selects the converted integer path parameter, caller `ContextVar` propagation, execution on a worker thread distinct from the ASGI caller, one endpoint invocation, route-scope observations, and complete ASGI events. The latest integrated run above compares this case exactly between pinned Starlette 1.6.0 and the installed Python package. Its Rust-native row is `not_run` because that profile cannot invoke a Python callable through this boundary; the manifest declares the sync-endpoint observations unsupported for Rust-native.

The active input contract adds two Request-style synchronous endpoint cases: `starlette.applications.Starlette.request-dispatch.sync-bound-method-get-items-0007` and `starlette.applications.Starlette.request-dispatch.sync-partial-get-items-0007`. Like the original function case, they select integer path conversion, caller `ContextVar` propagation, execution on a worker thread distinct from the ASGI caller, one invocation, route-scope observations, and complete ASGI events. The third case, `starlette.applications.Starlette.request-dispatch.asgi-callable-instance-get-items-0007`, declares a callable instance as the route's ASGI app. It receives `(scope, receive, send)` and selects route-scope observations and the complete live ASGI response events; it does not use a `Request` object or the AnyIO request-endpoint worker boundary. These are input-only parity cases, not expected outputs.

This follows pinned Starlette 1.6.0's route distinction: functions, bound methods, and `functools.partial` values resolving to those forms are Request-style endpoints. Async forms are awaited on the event loop; synchronous forms use AnyIO worker threads. Callable instances are treated as ASGI applications. The earlier 51-case checkpoint `480437e5-e1f4-4e25-91a5-1453ba82ea69` established source/package parity for these forms; the current integrated evidence is recorded above.

This repository uses live source-to-target parity as its behavioral gate and
has no conventional Python or Rust unit-test suite. `make test` runs the
declared source, installed-package, and supported Rust-native workflows; the
two debug traceback differences and six unsupported Rust-native rows keep the
current all-target gate incomplete.
An earlier 95-case parity result, including Router converter, Mount dispatch,
and reverse-URL cases, is generated locally at
`build/parity/parity-result.json`; that file is ignored and not committed.

## HTTPException default response slice

[`asgi-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-http-exceptions.yaml) adds five input-only cases in which a matched HTTP request-style endpoint raises `HTTPException` before response start. They cover an omitted detail for status 406, an explicit detail for 406, omitted details for 204 and 304, and an omitted detail plus a custom response header for status 200. The input contains only endpoint status/detail/header stimulus and observation selectors; response values come from the live source and target runs.

All five cases pass source-versus-installed-package comparison against pinned Starlette 1.6.0. The package target resolves omitted details at Python's `HTTPStatus` boundary, so the pinned response details include the relevant status phrases. Rust-native supports the explicit-detail 406 response and matches the oracle for that case; it does not provide Python's default status-phrase lookup. The Python shim catches the raised `HTTPException` because it is a Python exception from a Python callable; it forwards the resolved status, detail, and headers, while Rust constructs the HTTP response. This keeps exception-object handling at the callable boundary and response policy in the Rust core. The integrated run recorded above includes these cases; Rust-native still has unsupported callable and Mount rows.

This slice covers HTTP exceptions raised by matched request-style endpoints before response start, one callable-ASGI endpoint that raises after sending a complete response, the two registered-handler cases described below, and the bounded server-error cases in the next section. The after-start HTTPException case compares the chained `RuntimeError`, its `HTTPException` cause, `suppress_context`, and the partial response event tape. Middleware-raised errors outside these inputs, WebSocket handlers, full `TestClient` propagation modes, arbitrary middleware ordering, and exception identity/chaining beyond the declared cases remain open.

[`asgi-callable-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-callable-http-exceptions.yaml) adds two input-only callable-ASGI route cases. One raises `HTTPException(406)` before sending a response and observes Starlette's handled 406 response. The other sends an input-defined 200 response start and body, then raises `HTTPException(406)`; Starlette raises a `RuntimeError` chained from the HTTPException after the 200 events have already been sent. Both cases pass exact source-versus-installed-package comparison. The v4 result record captures the exception class, message, direct cause and public attributes, `suppress_context`, and partial ASGI observations. Rust-native is `not_run` for these Python-callable endpoints because it cannot invoke arbitrary ASGI callables.

## Registered exception-handler cases

[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml) adds two input-only `Starlette.__call__` cases, both selected for the Python-package profile. `starlette.applications.Starlette.__call__.exception-handler.status-code-precedence` registers the `HTTPException` class handler before the 405 status-code handler, then POSTs to a GET-only route. Starlette selects the exact status-code handler before the class handler, producing a distinct JSON response from the class handler's exception-detail response. The input declares handler keys and response recipes; it contains no expected response.

`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse` sends the request body in chunks. The endpoint reads `Request.body()` and raises the input-declared `BodyReuseException`, a subclass of `HTTPException`. Its async class handler reads `Request.body()` again and builds a JSON response from the decoded request bytes, exercising the cached body on the same Request. For this package boundary, `JSONResponse` uses Python JSON value serialization; Rust owns response framing, headers, and ASGI event delivery.

The earlier 51-case result selected 76 comparisons and had four Rust-native rows `not_run`. The latest integrated result is summarized above and includes these registered-handler cases; this slice does not establish full replacement parity.

## ServerErrorMiddleware application cases

[`asgi-server-errors.yaml`](../tests/fixtures/sources/parity/asgi-server-errors.yaml) adds nine input-only HTTP cases through `Starlette.__call__`, all selected for the Python-package profile. The cases cover the no-handler default 500 response, a registered integer 500 handler, a registered `Exception` handler, both insertion orders for the special 500 and `Exception` handler keys, text and HTML debug tracebacks that take precedence over a configured 500 handler, an unhandled `RuntimeError` after response start, and a handled `HTTPException(500)` that stays on the inner handled-exception path. They map to `starlette.asgi.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order`, `.debug-traceback`, `.response-started`, and `.handled-http-exception-500`.

The exact case IDs are `starlette.applications.Starlette.__call__.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order.status-then-exception`, `.special-key-order.exception-then-status`, `.debug.plain-text-overrides-handler`, `.debug.html-selected-by-accept`, `.runtime-error-after-response-start`, and `.handled-http-exception-500`. All nine passed source-versus-package comparison in the earlier run `480437e5-e1f4-4e25-91a5-1453ba82ea69`. In the latest integrated run, the other seven still pass, while the two debug traceback cases fail on different internal frame stacks and source context. No native cases are selected for these Python-callable app workflows.

The operation declares the `starlette-debug-traceback` projection for response bytes, ASGI response events, and ordered headers. The comparator inspects each live response body and projects frame paths, line numbers, and `Content-Length` only when that body has Starlette's actual debug-traceback structure. When no debug traceback is present, response bytes and headers retain their exact comparison. This decision comes from the observed body, not a case or requirement identifier. The source and target result records retain the raw traceback bodies. All other selected response fields remain exact, subject only to the separate declared `Allow` token normalization.

This evidence is limited to these input-defined `Starlette.__call__` workflows. `asgi-core.app.test_app_debug` remains backlog because these inputs construct the app with `debug=True`; they do not set `debug` after app construction. Direct `ServerErrorMiddleware` call-boundary behavior, arbitrary middleware ordering, TestClient behavior, WebSocket exception handling, and full replacement parity remain open.

## WebSocket protocol, state, and route-dispatch inputs

The WebSocket contract has three input-only operations. The full public
protocol operation compares source and installed-package behavior; the Rust
target is limited to the separate state projection because its public
`WebSocketStateMachine` does not produce Python `WebSocket` callback tapes,
payloads, or exception metadata.

[`websocket-protocol.yaml`](../tests/fixtures/sources/parity/websocket-protocol.yaml)
contains six ordered `WebSocket.receive()` and `WebSocket.send(message)`
sequences: handshake/text/close, disconnect return, invalid send transition,
receive after disconnect, binary exchange, and a connected send callback that
raises `OSError`. The observed ordered receive/send callback tape records the
message at each callback in chronological order. In the connected `OSError`
case, the attempted outgoing send is recorded before the send callback raises.
The incoming messages and action sequence are fixture stimulus. These full
callback-tape cases select the Python-package profile only.

[`websocket-state-sequence.yaml`](../tests/fixtures/sources/parity/websocket-state-sequence.yaml)
duplicates those six sequences for the projected Rust-compatible contract.
It records each action's `outcome` and optional exact `error_message`, plus
the final `client_state` and `application_state`. It excludes message payloads,
callback tapes, Python exception classes, and exception context. Each case
selects the pinned source, installed Python package, and Rust-native state
machine; the native comparison establishes only this projected state
behavior.

[`websocket-route-dispatch.yaml`](../tests/fixtures/sources/parity/websocket-route-dispatch.yaml)
contains three source/package cases: a match beneath a non-empty `root_path`,
a Router miss that closes the WebSocket, and a standalone `WebSocketRoute`
called with an HTTP scope that produces an HTTP 404 response. They observe the
route scope, ordered ASGI events, response status, and response bytes. No
Rust-native `WebSocketRoute` dispatcher is declared.

The protocol case IDs share the prefix
`starlette.websockets.WebSocket.protocol-sequence.` and have suffixes
`handshake-text-close`, `disconnect`, `invalid-transition`,
`receive-after-disconnect`, `binary-exchange`, and
`send-oserror-disconnect`. The state cases use the same suffixes under
`starlette.websockets.WebSocket.state-sequence.` The route case IDs are
`starlette.routing.WebSocketRoute.route-dispatch.matched-root-path`,
`starlette.routing.WebSocketRoute.route-dispatch.router-miss-close`, and
`starlette.routing.WebSocketRoute.route-dispatch.http-scope-404`.

Together the three operations contain 15 cases and select 21 comparisons:
six protocol tapes for Python-package, six projected state cases for each
target, and three route cases for Python-package. All 21 selected WebSocket
comparisons passed in run `480437e5-e1f4-4e25-91a5-1453ba82ea69`. Convenience
methods such as JSON send/receive and iterators, and denial-response behavior,
remain package-test-only in this milestone and in the parity backlog.

[`gzip-middleware.yaml`](../tests/fixtures/sources/parity/gzip-middleware.yaml) contains eight direct ASGI middleware cases: negotiated final compression, identity negotiation, a small-body bypass, excluded content type, streaming compression, path-send passthrough, an existing-encoding streaming bypass, and a partial-response streaming bypass. Inputs contain only middleware settings, request scopes, response events, and exact observation selectors. Every source and target observation compares ordered ASGI events and concatenated raw response bytes with no compression or event normalization. The Rust-native adapter drives `GzipConfig` and `GzipResponder`; the installed Python package exposes `starlette.middleware.gzip.GZipMiddleware`.

The Rust compressor uses `flate2`'s streaming gzip encoder and preserves zlib's sync-flush behavior across ASGI chunks. Compression decisions, exclusions, response-header edits, and stream state live in Rust. Python remains at the async boundary: it forwards ASGI callbacks and uses AnyIO's task-local capacity limiter and worker-thread facility for chunks at or above `thread_minimum_size`.

The legacy `__call__` profile selects exact response status, ordered repeated header bytes, body bytes, ASGI event order, complete ASGI events, and lifecycle/cleanup effects. The `request-dispatch` profile selects request observations, route-scope observations, response status, ordered repeated header bytes, ASGI event order, and complete ASGI events. Missing ASGI message fields remain missing in evidence. Repeated `Set-Cookie` headers must be produced by the two `Response.set_cookie` calls; adapters cannot inject output header values.

The manifest includes one direct-ASGI GET `/hello` latency workload in [`inputs/benchmark/asgi-get-hello.yaml`](../tests/fixtures/sources/benchmark/asgi-get-hello.yaml). It selects the pinned source oracle and both target profiles, times only the dispatch step, and requires a fresh successful exact parity run first. The benchmark worker then resolves the same parity case from its indexed input, verifies the input and case digests, and runs a fresh source-versus-installed-package probe before collecting samples. Warm-up, measurement count, sample count, concurrency, and cache state come from the benchmark input.

For this smoke case, the worker constructs the app and starts its fixture lifespan before warmups, keeps the lifespan active across fresh HTTP scopes and ASGI message/callback containers for every dispatch, then shuts down after sampling. It requires ordered `lifespan.startup.complete` and `lifespan.shutdown.complete` events and compares the completed cleanup trace with the source probe, outside timed regions. Each measured call's HTTP events are also checked against the probe immediately after its timer stops.

The timer measures in-loop `await app(scope, receive, send)`. It includes fixture-to-ASGI scope/message materialization, callback creation, and response collection; it excludes app construction, lifespan startup/shutdown, and event comparison. The pinned upstream routing runner enters the event loop with `loop.run_until_complete` for each dispatch, while this timer excludes per-dispatch loop-entry overhead. These numbers therefore do not reproduce upstream timings and are neither Rust-kernel-only measurements nor real-server throughput. The result is written as strict `benchmark-result@1` at `build/parity/benchmark-result.json` when the command runs. Rust-native remains `not_run` because its measured boundary is not equivalent. This is a one-case smoke benchmark, not a representative Router/GZip result. The separate `benchmark-upstream` runner now measures all 74 pinned Router/GZip workloads against source and the installed package; Rust-native remains `not_run` at those non-equivalent boundaries. See [Benchmark mapping](BENCHMARKS.md).

## Exact comparison and allowed normalization

Comparison is exact for all selected fields except the narrow `allow-methods-as-set` normalization declared on `ordered_repeated_headers` and `asgi_events`, and the declared `starlette-debug-traceback` normalization. The Allow normalization applies only to comma-separated tokens in an `Allow` header value: the comparator trims surrounding whitespace, sorts unique method tokens, and compares the normalized value. The traceback normalization activates only when live observations contain an actual Starlette debug traceback; it replaces frame paths and line numbers and normalizes the body-length header. All other traceback bytes, header names/order, duplicate headers, unrelated values, and event order stay exact. With no traceback body, raw response bytes and header values remain exact. Result records retain the original unnormalized events, headers, and raw response bodies.

The request-scope mutations are covered by the three original HTTP `request-dispatch` cases and the new typed path-parameter cases. Mounted routes and non-empty `root_path` now have bounded dispatch observations; pre-existing `path_params` beyond the declared mount merge and other application paths remain outside this slice. The successful `__call__` workflow schedules lifespan startup, HTTP dispatch, and lifespan shutdown on the same app task; it verifies that the lifespan context stays active across that in-flight dispatch and exits afterward. This covers one successful lifecycle path, not broader lifespan behavior. The Rust-native `Starlette::call` is an additive, bounded response dispatcher over a path/method projection, not a full ASGI application object. The Rust request adapter's routed-scope model is likewise not a public Rust `Request`.

## Isolated environments and adapter protocol

Run `prepare-env` before either oracle-only or full parity evidence. It builds the target wheel from this checkout, creates separate CPython 3.12 virtual environments for the pinned Starlette source oracle and installed `starlette-rs-py` wheel, and installs the four-package ASGI closure plus the pinned optional PyYAML schema dependency from the hash-pinned `scripts/parity/locks/asgi-runtime-cpython312.txt`. The generated environment lock records the repository-relative interpreter paths, runtime, platform, dependency-lock digest, installed-package freeze digest, environment digest, and target wheel digest. The runner rechecks those identities and does not fall back to a global Python interpreter. Python adapters receive `STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256` for their own environment; the native adapter receives the SHA-256 of `Cargo.lock`.

Each adapter runs in a fresh process. The runner sends one strict JSON `migration-parity/adapter-request@1` object on stdin and accepts exactly one JSON response object on stdout. The response envelope remains `migration-parity/adapter-response@1`; its opaque workflow payload follows the versioned parity-input and parity-result contracts. Diagnostics go to stderr. Identity responses are checked against the source revision or installed target environment before workflows run. The result schema is `migration-parity/parity-result@4`, which retains oracle revision/module/lock provenance, target revision/tree/lock/package identity, and per-side environment fingerprints. Unknown fields, duplicate JSON keys, malformed output, absent interpreters/adapters, crashes, timeouts, identity mismatches, missing or extra observations, skipped evidence, and unsupported evidence cannot pass.

The `parity-input@4` cases for callable-ASGI `HTTPException` behavior drive an ordered action sequence from fixture data. If the app raises after response events have been sent, the adapter marks that workflow step `error`, preserves the chained exception and `suppress_context` flag, and records the partial ASGI observations in `partial_value`. This keeps captured application behavior comparable while adapter crashes and malformed evidence remain infrastructure failures.

`oracle-only` invokes only the pinned source workflows. It writes a comparison row per target profile with target workflow status `skipped`, a reason, and outcome `not_run`. A full `run` attempts workflows for all 196 indexed cases and fails closed when a target identity or workflow is unavailable. `pass` requires completed oracle and target workflows plus exact equality after the declared normalizations. The latest run and its limitations are recorded in the parity evidence section above. See `build/parity/results/config-schemas-run-2.json`; generated results are local ignored artifacts and are not checked in.

## Maintained commands

Run these from the repository root with CPython 3.12:

```sh
python3.12 -m scripts.parity.cli validate --upstream /path/to/pinned/starlette
python3.12 -m scripts.parity.cli prepare-env --upstream /path/to/pinned/starlette
python3.12 -m scripts.parity.cli inventory-slice
python3.12 -m scripts.parity.cli oracle-only
python3.12 -m scripts.parity.cli run
python3.12 -m scripts.parity.cli compare --case-id starlette.applications.Starlette.__call__.get-hello --source source-workflow.json --target target-workflow.json
python3.12 -m scripts.parity.cli benchmark
python3.12 -m scripts.parity.cli benchmark-upstream
```

Use `prepare-env --force` only to rebuild the generated `build/parity` environments and wheelhouse. `validate` checks strict manifest, parity-input, benchmark-input, and result-schema structure; source lock consistency; source pin; input indexes; case/observation references; and Python tooling syntax. It is static validation, not runtime parity. `oracle-only` and `run` write `build/parity/parity-result.json` by default. A result with missing targets, infrastructure errors, failed comparisons, or any `not_run` row exits nonzero.

The one-case `benchmark` command runs its exact parity gate before the source/package probe and samples. If the gate fails, it emits a `not_proven` result without placeholder measurements. If the gate passes, it measures the linked source and installed package using the smoke boundary above; Rust-native remains `not_run`. Its artifact is `build/parity/benchmark-result.json`, with gate evidence at `build/parity/benchmark-correctness-result.json`. The separate `benchmark-upstream` command runs the 74 input-backed Router/GZip workloads; its result and current scope are documented in [Benchmark mapping](BENCHMARKS.md). Coverage for the overall replacement still requires the remaining upstream tests, documented behaviors, and boundary cases.

## Current boundary gaps

The current boundary has Rust own built-in path matching and path formatting, response framing, middleware compression policy, and WebSocket protocol state. Python keeps Starlette's public route objects and ASGI dispatch layer, calls registered Python converters and application endpoints, and preserves the event-loop, threadpool, exception, and lifetime behavior at those boundaries. The route matcher falls back to Python only for custom converters, which cannot be represented by the current Rust converter set. For GZip, AnyIO owns the task-local worker limiter and thread scheduling, while Rust owns compression and response policy. The upstream-internal `GZipResponder` import is not yet implemented; the parity cases exercise the public `GZipMiddleware` boundary.

The parity lifecycle step covers one successful async-context enter/exit separately from its HTTP dispatch. The Request-style synchronous endpoint inputs cover functions, bound methods, and `functools.partial`; a separate callable-instance case covers ASGI dispatch through `(scope, receive, send)`. The current integrated run includes six slash-redirect cases, four direct RedirectResponse cases, eight direct Response/JSONResponse cases, and four finite synchronous StreamingResponse cases, all passing on both target profiles; one finite async-iterator StreamingResponse case passes on the Python package. Streaming evidence establishes per-chunk iteration for that bounded async case, but not cancellation, disconnect races, background tasks, or ASGI 2.4 `OSError` mapping. Router inputs cover built-in converters, misses, route order, root paths, slash redirects, and a package-only custom override. Reverse-URL inputs cover named Python route surfaces and `Request.url_for`; they do not establish a named URL API on the Rust-native target or Host reverse lookup. Request inputs cover typed path parameters and CPython's integer-digit limit; Mount inputs cover child-scope extension and misses. The HTTPException, registered-handler, server-error, and WebSocket slices remain bounded to their declared inputs. Route/router/mount-local middleware is present in the Python compatibility layer but has not yet been selected by input cases, so its parity remains unproven. Convenience helpers, denial responses, WebSocket exception handling, TestClient propagation, direct `ServerErrorMiddleware` invocation, and arbitrary middleware ordering remain open. The new FileResponse inputs cover deterministic GET, HEAD, single-range, If-Range match/mismatch, malformed-range, unsatisfiable-range, and Unicode-filename cases; all 16 source-to-target comparisons passed across the two target profiles. Multipart-range output and `http.response.pathsend` remain unproven because their output includes a random boundary or isolated temporary path. The current facade also does not expose Starlette's mutable `headers` view, and changing its public `path`, `status_code`, or `stat_result` after construction does not update the Rust snapshot. Rust currently performs filesystem stat and reads synchronously on the ASGI caller; nonblocking filesystem scheduling remains unproven. The general replacement goal remains incomplete; broad Starlette parity and the native benchmark boundary remain unproven. The Router/GZip benchmark lane is documented in [Benchmark mapping](BENCHMARKS.md).
