# Staged implementation plan

The full Starlette replacement remains active and incomplete; full
compatibility remains the target at every stage. A stage's completed scope is
evidence for that scope only; scaffolding or one passing example cannot
establish drop-in compatibility.

## 0. Establish the contract (current)

- Pin Starlette 1.6.0 and record FastAPI 0.141.1 as a downstream reference
  identity only.
- Keep root `metadata.yaml` authoritative for pinned API-source references and
  API inventory roots; keep the parity manifest as the active behavior contract.
- Finish API/signature/deprecation and dependency/license inventories with
  explicit denominators.
- Expand the single input-only manifest and map each upstream test/doc behavior
  to independently authored YAML source definitions and observations.
- Prototype isolated live oracle and target runners plus strict result schema.

Parity and benchmark inputs are authored under `tests/fixtures/sources/` and
generated as runtime JSON beneath ignored `build/parity/inputs/` by
`make parity-inputs`. Parity and benchmark result JSON under `build/parity/` is
also local generated output and is not committed; the run IDs and counts in
this plan identify recorded executions.

The current parity contract has 116 input-only cases and 120 parity requirements
across 18 indexed files. Latest integrated run `ca7e0adc-e449-4f0a-92fe-9d48211e1041`,
finished at `2026-09-28T11:18:31.918Z`, selected 178 comparisons: 172 passed,
zero failed, zero infrastructure errors, and six `not_run`. All 116
Python-package cases passed; Rust-native passed 56 of 62 selected comparisons.
The six unsupported Rust-native rows keep the all-target gate incomplete.

## 1. Decide the Python/Rust boundary

Prototype arbitrary sync and async Python endpoint calls on Python's event
loop, including cancellation, context variables, streaming, exceptions,
threadpool behavior, and lifespan cleanup. Define which layers remain Python
and which operations enter Rust. Do not assume a native Rust runtime can invoke
Python callables while preserving these semantics.

## 2. Initial ASGI-to-response vertical slice (partial)

Implement a single `GET /hello` route through the public Rust-native app API
and through the installed Python compatibility package. Start from a real ASGI
scope/receive/send sequence; return a text response; exercise the pinned Python
oracle and both targets in separate processes; compare status, repeated and
ordered headers, bytes, event order, errors, and cleanup. The package import
path must be exercised after installation, not from the source tree.

The bounded GET `/hello`, 404, and 405 workflows run through the installed
Python ASGI callable and the exported Rust `Starlette::call` API. The Rust API
accepts only an HTTP path/method projection, and its response-only handler
leaves the receive callback untouched. The successful `/hello` workflow now
runs lifespan startup, HTTP dispatch, and lifespan shutdown on the same app
task, so the request occurs while lifespan remains active. The fresh full-run
artifact `build/parity/parity-result.json` records run
`8f2d2205-dadb-4386-b39a-4ecd1c7510c0`: 12/12 comparisons passed, with manifest
SHA-256
`e9e909097474fa0df3f89edad3251b93e1ab6e93d2be78a57627e2fe3c0fbb73`. This
proves only the declared cases; full ASGI scope handling and lifecycle
concurrency remain open.

## 3. Grow the core contract

### Completed bounded goal: parameterized routing and `Request`

After the initial static-route slice passes its installed-package runner, make
the Rust-native and Python-compatible targets pass one bounded Starlette
`Request` flow through the public interfaces:

- `GET /items/{item_id:int}` receives `/items/0007?tag=red&tag=blue`, a
  mixed-case request header, a cookie, and JSON delivered in two ASGI request
  body chunks. An async endpoint observes integer `item_id == 7`, ordered
  repeated query values, Starlette's last-value scalar query lookup,
  case-insensitive headers, cookies, parsed JSON, and the route's `app`,
  `router`, `endpoint`, and `path_params` scope values.
- `/items/nope` produces the Starlette 404 response.
- `POST /items/7` produces the Starlette 405 response and `Allow` token set
  `{GET, HEAD}`. The fixture documents the order-insensitive comparison for
  that header because its source order depends on set iteration.

Acceptance requires input-only cases in the active manifest, exact live
comparison against pinned Starlette 1.6.0 through the installed Python package
and Rust-native public API, and strict source/target/runtime/dependency identity
in result artifacts. Preserve ASGI event order and scope mutations. This goal
does not establish parity for untested request properties, converters,
mounts, broader streaming response semantics, or the wider Starlette API.

The three original request workflows pass against the pinned source and both
targets. The Rust target uses exported request primitives through its parity
adapter; the crate does not yet expose one public Rust `Request` type.

### Completed bounded goal: Router converters, typed path values, and Mount

The next input-only slice adds 15 Router cases for the five built-in
converters, converter misses, route order, root-path matching and prefix
boundaries, plus a package-only custom `str` converter override. Six Request
cases exercise converted path-parameter values and CPython 3.12's 4300-digit
integer conversion limit. Two Mount cases compare child-scope extension and
mount misses. Rust-native runs the built-in Router projection; it marks the
Mount cases and four Python-callable Request endpoint shapes unsupported.

The integrated full run `b2fc5183-407c-4843-b9e3-7e228342159e`, finished at
`2026-09-28T09:08:03.998Z`, selected 148 comparisons: 142 passed, zero failed,
zero infrastructure errors, and six `not_run`. All 101 package comparisons
and 41 of 47 Rust-native comparisons passed. Its manifest SHA-256 is
`f40bd02d232ff032835781aec47a532f6787a375289f14b8213ca9f0758e70ea`; the
target wheel SHA-256 is
`4faf7bf1db038332fa0734e5c86b37c56e55e0fbb71db4ac110c620fe1e498b1`. The
result is local evidence from dirty trees, not an all-target or release pass.
The 21-case reverse URL slice now covers the named Python route surfaces and
`Request.url_for`; the Rust-native named Route/Router API and Rust custom
converter registration remain open. Route/router/mount-local middleware is
present in the Python compatibility layer but is not yet covered by input-only
parity cases.

### Completed bounded goal: reverse URL generation

The input-only `reverse-url-routing.yaml` slice covers `Route`,
`WebSocketRoute`, `Router`, `Mount`, `Starlette`, and `Request` URL generation.
It exercises built-in converter formatting and errors, a Python custom
converter override, first-success router selection, direct and nested mounts,
`app_root_path`, provider fallback, missing context, and the top-level
application forwarder. All 21 source/package comparisons passed. Rust owns the
built-in path substitution primitive used by the Python package; the
Rust-native named URL API is still unimplemented and is excluded from these
comparisons.

### Completed bounded goal: run HTTP inside an active lifespan

The input-only `/hello` workflow now schedules startup, dispatch, and shutdown
in order on the same app task. Its successful source and target observations
verify that lifespan stays active through the HTTP response and exits after
dispatch. The fresh full-run artifact and identity are recorded in stage 2.
The separate benchmark correctness gate also passed 12/12 comparisons in run
`2c849961-2ee3-45b0-a013-b14110387471`; its smoke result and limits are recorded
in [the benchmark mapping](BENCHMARKS.md). This closes the declared lifecycle
ordering gap only; it does not establish general ASGI concurrency,
cancellation, or full-scope parity.

The bounded sync-callable, ASGI-callable, exception-handler, server-error,
and finite StreamingResponse cases in section 6 pass source/package parity.
Six Rust-native observations remain explicitly `not_run`; the full Starlette
replacement is still incomplete. Later work includes broader HTTP/WebSocket
connection and request-body behavior, streaming backpressure and iterator
lifecycle, route-local middleware, Host reverse lookup,
direct `ServerErrorMiddleware` call-boundary
parity, WebSocket exception handlers, remaining TestClient
exception-propagation modes, arbitrary middleware ordering, middleware
composition, authentication, background tasks, and concurrency.

## 4. Optional and edge features

Static files, forms/uploads, templates, schemas, config, WSGI, and TestClient;
then broader streaming lifecycle, duplicate headers/cookies, failure
propagation, cancellation, and platform-specific paths. Keep optional
dependencies feature-gated and preserve unsupported coverage visibly.

## 5. Completed bounded goal: Router/GZip benchmark parity

The pinned Starlette 1.6.0 Router/GZip workload catalog contains six Router
and 68 GZip benchmark IDs. All 74 now have input-only descriptors and exact
source-versus-installed-package correctness gates. The full runner measured
all 74 with zero failed and zero not-run source/package rows. Its latest result
is `build/parity/upstream-benchmark-result.json`. Run
`4b478188-8546-43ce-95fd-1b58e18672f7` ran from
`2026-09-28T09:09:13.967Z` to `2026-09-28T09:10:42.274Z`; all 74 declared
workload correctness gates passed for pinned source and the installed package.
The recorded source revision is `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.
Its correctness preflight, `351d9fe9-c482-4b2f-b181-f6f59a66c93b`, selected
148 parity comparisons: 142 passed, zero failed, zero infrastructure errors,
and six Rust-native rows were `not_run` (package 101/101; Rust-native 41/47).
The target trees were dirty local trees, so this is not clean aggregate or
release proof. The benchmark result records source, input, and manifest hashes.

Rust-native remains `not_run` for all 74 because its public API does not expose
the same Starlette Router/GZip dispatch boundary. The result is accepted by the
strict aggregator, while the overall replacement remains `not_proven` because
the pinned compatibility inventory is much broader. Measurements are matched
local wall-clock samples, not CodSpeed CPU/memory/allocation evidence. See
[Benchmark mapping](BENCHMARKS.md) for timer policy and workload details.

## 6. Completed bounded goal: sync Request endpoints and ASGI callable dispatch

The input-only case
`starlette.applications.Starlette.request-dispatch.sync-get-items-0007-contextvar-worker`
exercises one ordinary synchronous Python endpoint on
`GET /items/{item_id:int}` with request path `/items/0007`. The endpoint
observes integer `item_id == 7`, the caller's `ContextVar` value after dispatch
through AnyIO's worker thread, execution on a thread distinct from the ASGI
caller, and exactly one invocation. Its complete ASGI events match exactly
between pinned Starlette 1.6.0 and the installed `starlette-rs-py` package.
Python owns calling the user function and the AnyIO threadpool boundary; Rust
does not invoke a Python callable.

The earlier 51-case checkpoint was run `480437e5-e1f4-4e25-91a5-1453ba82ea69`.
It predates the Router and Mount cases; the latest integrated run is recorded
in section 3.

The original function case specifically covers one integer path parameter,
caller `ContextVar` propagation through one AnyIO worker, distinct
worker-thread identity, one invocation, and exact ASGI events. The additional
callable shapes and their selected observations are described below.

### Callable and ASGI endpoint forms: source/package parity verified

Pinned Starlette 1.6.0 treats functions, bound methods, and `functools.partial`
values resolving to those forms as Request-style endpoints. Async forms are
awaited on the caller event loop; synchronous forms run through AnyIO's worker
thread facility. Other callable instances are treated as ASGI applications and
are called with `(scope, receive, send)`; they do not receive a `Request` or use
the AnyIO request-endpoint worker boundary. Python owns these call boundaries;
Rust does not invoke Python callables.

The active input contract adds two Request-style sync cases alongside the
original function case: `starlette.applications.Starlette.request-dispatch.sync-bound-method-get-items-0007`
and `starlette.applications.Starlette.request-dispatch.sync-partial-get-items-0007`.
Each declares the same `/items/0007` request and selects integer path
conversion, route-scope observations, caller `ContextVar` propagation,
worker-thread identity, single invocation, and complete ASGI events. A third
case, `starlette.applications.Starlette.request-dispatch.asgi-callable-instance-get-items-0007`,
declares a callable instance as the route's ASGI app; it observes route-scope
values and the complete ASGI response sent through `(scope, receive, send)`.
The manifest leaves Rust-native support explicitly partial because the native
profile cannot invoke Python callables. At the 51-case checkpoint, all
Python-package cases, including these three, passed exact comparison against
the pinned source. The Rust-native rows for the ordinary sync function, bound
method, partial, and ASGI callable instance were `not_run` under the manifest's
declared unsupported boundary; this does not count as native parity. The
latest full run is summarized in section 3.

### Completed bounded goal: finite `StreamingResponse` output

Three input-only cases cover finite synchronous text chunks: omitted generated
`Content-Length`, preservation of a caller-supplied content length, and
`text/plain` framing with per-chunk ASGI events. All six pinned-source versus
target comparisons passed in run `ca7e0adc-e449-4f0a-92fe-9d48211e1041` across
the installed Python package and Rust-native profile. This evidence does not
establish lazy iteration, backpressure, asynchronous iterator lifecycle,
disconnect handling, background tasks, or memoryview type parity.

### HTTPException default-response slice: bounded parity verified

Five input-only cases in
[`asgi-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-http-exceptions.yaml)
cover a matched HTTP request-style endpoint raising `HTTPException` before
response start. They exercise omitted detail for status 406, explicit detail
for 406, omitted detail for 204 and 304, and omitted detail plus a custom
header for status 200. All five source/package comparisons pass exactly. The
Python package resolves omitted details through Python's `HTTPStatus` boundary;
Rust-native accepts the resolved explicit detail and passes the explicit-detail
406 case. The native response constructor does not implement Python's
status-phrase lookup.

This result is limited to those five request-style endpoint inputs. A separate
callable-ASGI input file adds one case that raises `HTTPException(406)` before
response start and another that sends a complete 200 response before raising
the exception. The latter matches Starlette's chained `RuntimeError`, direct
`HTTPException` cause, suppression flag, and partial ASGI event tape against
the installed package. Rust-native cannot invoke these Python callables, so its
rows are `not_run`. These HTTPException cases do not cover middleware-raised
exceptions, WebSocket exception handlers, or all `TestClient` propagation
modes. The separate server-error application cases below cover a bounded
subset of 500/Exception handling and debug responses. At the 51-case
checkpoint, all package comparisons passed and Rust-native had four
callable-boundary rows `not_run`. The current integrated result is in section
3. This evidence applies only to the selected inputs; the full Starlette
replacement remains incomplete.

### Completed bounded goal: input-driven HTTP exception-handler parity

Two input-only cases in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml)
exercise registered HTTP exception handlers through the public application
dispatch path:

- `starlette.applications.Starlette.__call__.exception-handler.status-code-precedence`
  registers the `HTTPException` class handler before status 405, then sends a
  POST to a GET-only route. The status handler wins for the generated 405, and
  the async handler's custom response is observed.
- `starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse`
  raises an input-defined `BodyReuseException`, an `HTTPException` subclass,
  after the endpoint reads the request body. Its async class handler reads the
  body again from the same `Request` object and returns a JSON
  response with status 422.

Both cases pass source-versus-installed-package comparison. Their two inputs
cover status-code precedence and cached request-body reuse; broader error-path
behavior is in the server-error slice below. The 51-case checkpoint
`480437e5-e1f4-4e25-91a5-1453ba82ea69` selected 76 comparisons: 72 passed,
zero failed, zero infrastructure errors, and four Rust-native Python-callable
rows were `not_run`. The package profile passed all 51 cases; Rust-native
passed 21. Target identities were dirty local trees, so the run is not clean
aggregate or release proof. The repository has no conventional Python or Rust
unit-test suite; `make test` runs live source-to-target parity. The current
full run has six unsupported rows, so the all-target gate remains incomplete.
Full Starlette replacement remains incomplete.

### Completed bounded goal: ServerErrorMiddleware application error-path parity

Nine input-only cases in
[`asgi-server-errors.yaml`](../tests/fixtures/sources/parity/asgi-server-errors.yaml)
exercise server-error selection through `Starlette.__call__`. They cover the
default no-handler 500 response, integer 500 and `Exception` handlers, both
special handler-key insertion orders, text and HTML debug traceback selection
ahead of a configured 500 handler, an error after response start, and a handled
`HTTPException(500)`. Their manifest requirements are
`starlette.asgi.server-error.default-response`, `.status-500-handler`,
`.exception-handler`, `.special-key-order`, `.debug-traceback`,
`.response-started`, and `.handled-http-exception-500`. The exact case IDs and
selected observations are listed in [the parity evidence](PARITY.md).

All nine server-error cases passed against the pinned source in the Python
package profile in run `480437e5-e1f4-4e25-91a5-1453ba82ea69`. The two debug cases use the
declared stable traceback
projection for response bodies and ASGI events, and normalize `Content-Length`
only for those cases; raw bodies remain in the result artifact. These cases do
not cover direct `ServerErrorMiddleware` invocation, arbitrary middleware
ordering, TestClient behavior, or WebSocket exception handling. The raw
protocol and route-dispatch cases pass in their declared profiles. Full
replacement parity remains open.
The upstream `asgi-core.app.test_app_debug` crosswalk row stays backlog because
the fixture does not set debug after app construction.

The recorded evidence does not establish general exception propagation or
identity beyond the selected chained-error, same-request body-cache, and
server-error cases; nor does it establish cancellation, general streaming
lifecycle or backpressure, concurrency,
the native benchmark boundary, or general 100% Starlette parity.
The Router/GZip benchmark work remains a
separate lane with unchanged evidence in [Benchmark mapping](BENCHMARKS.md).
The full replacement goal remains active and incomplete; unsupported and
unmeasured behavior stays on the roadmap.

## 7. Bounded WebSocket protocol, state, and route-dispatch slice

The active manifest contains 15 WebSocket cases in three operations across
three input files. The six full protocol-sequence cases select the installed
Python-package target profile for comparison against the source oracle and
observe the complete ordered receive/send ASGI callback tape. It records
callback messages in chronological order and keeps the attempted send whose
callback raises `OSError`. This operation does not select Rust-native behavior
because `WebSocketStateMachine` does not produce Python `WebSocket` callback
tapes or payloads.

The six `state-sequence` cases duplicate the same handshake/text/close,
disconnect, invalid transition, receive-after-disconnect, binary, and
connected-send-`OSError` inputs. They select the pinned source, installed
package, and Rust-native state machine. The observation projects each action
to its outcome and optional exact `error_message`, then records both final
state enums. It excludes message payloads, callback tapes, Python exception
classes, and exception context. The native comparison establishes only this
projected state-machine behavior.

The three `WebSocketRoute.route-dispatch` cases select the Python-package
profile: `matched-root-path` matches `/rooms/{room:str}` beneath `/edge`;
`router-miss-close` dispatches an unmatched WebSocket scope and observes its
close event; `http-scope-404` calls a standalone route with an HTTP scope and
observes the 404 response. Native `WebSocketRoute` dispatch is not declared.

All 21 selected WebSocket comparisons passed in run
`480437e5-e1f4-4e25-91a5-1453ba82ea69`, finished at
`2026-09-28T05:59:25.632Z`: six protocol-tape package comparisons, 12 state
comparisons across package and Rust-native, and three route-dispatch package
comparisons. The full run selected 76 comparisons, with 72 passed, zero
failed, four unsupported Python-callable Rust-native rows `not_run`, and zero
infrastructure errors. The adapter exits with status 2 for those `not_run`
rows. Target identities were dirty local trees, so the run is not clean
aggregate or release proof. The full replacement remains incomplete.

JSON convenience methods, async iterators, denial-response behavior,
`WebSocketEndpoint`, application-level exception handling, `TestClient`,
authentication and mount/host route behavior beyond the child-scope case,
broader streaming and file-denial
behavior, and concurrency cancellation remain follow-on work requiring their
own input-only workflows and live comparisons. Each fixture contains only
operation stimulus and observation selectors; expected values remain in live
result artifacts.

## 8. Packaging and release readiness

Prepare a Rust crate and Python wheel/sdist, inspect contents and notices,
validate imports and dependency metadata in clean environments, and run package
dry-runs. Do not publish to crates.io or PyPI without a later explicit request.

## Python distribution and `starlette` namespace

The Python distribution cannot use the occupied PyPI distribution name
`starlette`. Current plan: package the Python target as `starlette-rs-py`, ship
the compatibility API under the import namespace `starlette`, and ship the
native extension under `starlette_rs_py`. The separate Rust crate is
`starlette-rs`. These distributions must not coexist
with upstream Starlette in one environment: both would own the same
`site-packages/starlette/` paths, and installing/uninstalling them can overwrite
or remove each other's files.

Install instructions must create a dedicated environment and explicitly
remove upstream `starlette` before installing `starlette-rs-py`. Add package
preflight/consumer checks that detect both distribution metadata entries and
fail clearly. Python package metadata includes `Obsoletes-Dist: starlette` only
if packaging checks show value, but it is not an enforcement mechanism: the
[Python Packaging User Guide](https://packaging.python.org/en/latest/specifications/core-metadata/)
marks `Obsoletes-Dist` as rarely used and says popular installers ignore such
fields. This project does not claim FastAPI compatibility or replacement of
FastAPI's declared `starlette` dependency. Do not write installation
instructions that silently overlay upstream files.
