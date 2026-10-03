# Staged implementation plan

The full Starlette replacement remains active and incomplete; full
compatibility remains the target at every stage. A stage's completed scope is
evidence for that scope only; scaffolding or one passing example cannot
establish drop-in compatibility.

## Runtime architecture

The upstream Starlette distribution is a source oracle and is not a runtime
dependency. Rust owns Starlette decisions, branching, iteration, ordering,
state, and error policy. Python `starlette.*` modules forward inputs and
callbacks, convert values at the PyO3 boundary, and await Python callables on
their owning event loop. The runtime-wrapper policy check rejects Python
control flow in these facades.

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

The active parity contract contains 778 input-only cases in 84 indexed files,
covering 94 operations and 801 requirements, including direct FormData
constructor/equality inputs; direct UploadFile constructor/repr, spooled-file
rollover, and threadpool-boundary inputs, and Python-package-only
GZip final and streaming response inputs at the `thread_minimum_size` boundary, an input-defined shared
AnyIO thread-pool limiter case and input-derived generic
`Request[State]` and `WebSocket[State]` type contracts, four source-shaped
TrustedHost TestClient workflows for exact/wildcard acceptance, invalid-host
rejection, and HTTPS www redirect following, Rust-backed
`CommaSeparatedStrings` parsing, quoting, sequence formatting, Python
string-subclass boundary behavior, and lone-surrogate values, the direct
`starlette.concurrency.run_in_threadpool` helper, including the shared AnyIO
default/configured limiter capacity and mixed-consumer observations,
synchronous Request endpoint worker cancellation and failure, five async Request endpoint callable shapes
and failure, ASGI callable-instance success and failure, `Starlette.host()` and
`Starlette.mount()` registration and dispatch, two direct `State` consumer
sequences, app-state attribute reads through `request.app.state`, two
`Starlette.add_exception_handler` workflows, one URL
query-parameter operations input, seven QueryParams equality and
blank-value cases, a three-request CORSMiddleware origin-
isolation workflow, one default middleware-boundary trace, sixteen Request.cookies
parser and dictionary-boundary inputs, and the TestClient cookie-persistence
round trip for `test_request_cookies`, including every active
parameter from the edge-case and malformed-cookie source rows. New WebSocket
inputs add four denial-response state transitions and exact connected invalid-
send/invalid-receive errors, a fresh-iterator
`asend(non-None)` error boundary, and invalid JSON-mode cases. Direct
`GZipResponder` package inputs cover configured exclusion normalization and
compression without negotiation. TestClient lifespan inputs also start and
release an input-defined task-group child under asyncio and Trio. The file-like
StreamingResponse case observes each newline-delimited binary chunk through the
installed Python package. The six direct ServerErrorMiddleware inputs and three
TestClient exception-chain cases, including implicit context and explicit cause
propagation through BaseHTTPMiddleware, also pass in the latest run. Three
StaticFiles HTML fallback scenarios and seven built-in float/UUID converter
cases pass on both target profiles. Default-string and int/path converter
scope observations also pass on both profiles. The datetime converter
dispatch and reverse-URL inputs pass on the Python package. Run
The earlier `parity-input@27` checkpoint run
`da7529b3-3fe0-4417-8d9b-005d772fc57f` selected 918 comparisons: 914 passed,
zero failed, zero infrastructure errors, and four declared Rust-native
Python-callable rows `not_run`. The installed Python package passed 708/708;
Rust-native passed 206/210. The FormData input compares direct repeated-pair
construction, mapping/copy equality, lookup and views, repr, and constructor
arity errors against the pinned source. The UploadFile input compares direct construction, omitted-size reads and writes,
default and explicit-header repr values, rolled/in-memory scheduling, event-loop
progress, and OSError propagation against the pinned source. The four native
`not_run` rows are synchronous
Request endpoint, bound-method endpoint, partial endpoint, and callable-instance
ASGI dispatch. `make test` exits with status 2 for these declared rows. The
complete run identity, wheel and tree hashes, and case-level evidence are in
[Migration parity contract and evidence](PARITY.md). This bounded run does not
establish full Starlette parity or release readiness. The type-contract
inputs also run an input-derived Mypy consumer check: parameterized Request
and WebSocket state keys resolve to the supplied TypedDict value type, while
bare `Request.state` retains Starlette's `State` type.

That integrated run includes the focused `parity-input@23` through `@27` additions.
The two BaseHTTPMiddleware ContextVar observer comparisons pass exactly against
the pinned source and installed package in the integrated run.

The generated coverage matrix contains 802 source rows: 611 input mappings,
51 source-backed `not_applicable` rows, and 140 fixture-backlog rows. These
changing counts come from the generated atlas CSV files. The denominator
remains 514 upstream test functions and 24 documentation pages; the full
replacement objective is active and incomplete.

Additional bounded comparisons include six WSGIMiddleware cases, two direct
`build_environ` cases, and the module-import deprecation warning case. The
async endpoint-boundary input checks caller loop/task/thread ownership,
cancellation, and endpoint finalization. Current fixture coverage also includes
14 response-background-task workflows, 31 FileResponse behavior cases, 20 URL
scope cases, 14 URL component cases, ten Headers/MutableHeaders cases, and
23 BaseHTTPMiddleware cases. These slices pass only for their declared inputs
and profiles; detailed observations, limitations, and run identities remain in
[Migration parity contract and evidence](PARITY.md).

## Completed bounded goal: Rust-owned StaticFiles core

The Rust core now owns StaticFiles path normalization, path containment, symlink
policy, lookup, method selection, HTML index/fallback selection, redirects, and
conditional 304 handling. The Python `starlette.staticfiles` module is a thin
constructor and forwarding facade; package discovery calls Python's
`importlib.util.find_spec` at the PyO3 boundary so custom importers and package
origins remain visible. Forty-four input-only cases are authored across
five StaticFiles inputs. Fifteen `lookup_path` cases run on both target
profiles and all 30 comparisons pass, including Unix and UNC-style absolute
path rejection. Across the StaticFiles slice, all 75 selected profile
comparisons pass: 37 Rust-native and 38 Python-package
comparisons.
The path-limit inputs verify that an overlong first root maps to the
source-compatible 404 before a later root can serve its matching asset, under
both symlink settings. Permission inputs deny search access to a root containing
an asset and match the 401 error for both symlink settings. Python package
discovery is profile-specific; Rust-native uses explicit package roots.
Remaining gaps include broader Windows path normalization and path semantics,
`check_config` scheduling, constructor errors, remaining validators and
subclass hooks, and the rest of the 36 upstream StaticFiles tests.

## 1. Completed bounded goal: lifespan state and cancellation

Five input-only cases now exercise yielded state merge, missing
`scope["state"]`, and cancellation during context entry, shutdown receive, and
context exit. The observations include post-call scope state, cleanup order,
startup/shutdown events, and the propagated exception. All five match pinned
Starlette 1.6.0 through the installed package; all 20 cases in the lifecycle
generator slice pass. Rust's lifespan state machine owns the transitions and
scope mutation. Python only creates the declared test callback and forwards
its result or exception at runtime. This checkpoint covers these lifecycle
inputs only; it does not establish cancellation parity across HTTP, WebSocket,
streaming, or background tasks.

## Completed bounded goal: server-error debug traceback parity

The two debug-mode 500 response mismatches came from Python framework stack
frames and source snippets present in the oracle but absent from the
Rust-dispatched package. The declared reusable traceback projection now removes
only frames from modules under the `starlette/` package, keeps user-code frames
and the exception summary, and normalizes the remaining source paths, line
numbers, HTML frame IDs, and body length. It activates only for the live
Starlette debug-traceback structure and changes parity comparison only; the
Python runtime wrappers remain pass-through. Both text and HTML debug cases
match source/package behavior. The integrated result above has zero parity
failures; the all-target command remains incomplete only for its four
Rust-native callable `not_run` rows.

## Completed bounded goal: Rust-native Mount child-scope and miss parity

The public Rust-native `Mount` API matches the Mount prefix, extends
`root_path`, retains or initializes `app_root_path`, merges inherited, mount,
and child-route captures, dispatches a fixed child response, and distinguishes
Mount misses from child 404 and 405 responses. Five input-only Mount workflows
pass against the pinned source, installed package, and native API, including an
inherited `path` value that survives the internal Mount remainder capture. The
implementation is bounded to HTTP child routes with prebuilt responses;
arbitrary ASGI child applications and middleware are not part of this slice.
The Python facade remains a pass-through, while matching and scope decisions
run in Rust.

## Completed bounded goal: Rust-native nested Mount composition

The native Mount child tree now accepts recursively nested Mounts and HTTP
routes. Rust propagates the original path, accumulated `root_path`, retained
`app_root_path`, and merged typed captures through each selected level, and
returns the deepest response. Two input-only cases pass against pinned
Starlette 1.6.0, the installed package, and the native API: a successful inner
response with inherited/outer/inner/leaf parameter overrides, and an inner
integer-converter miss that leaves only the outer scope extension applied.
The nested success case also found and fixed a Rust package-dispatch bug that
removed an inherited `path` key when stripping Mount's internal catch-all
capture. The Python Starlette facade remains a pass-through; no upstream
Starlette runtime dependency was added.

## Completed bounded goal: Session inherited dictionary operations and errors

The Session facade now forwards inherited `dict.popitem()` and `Session |=
values` operations through Rust. Rust invokes the built-in `dict` methods to
preserve mapping and pair-sequence inputs, return values, identity, and native
dict mutation semantics without Python wrapper branching. Input-driven oracle
comparisons confirm Starlette 1.6.0 leaves `modified` false for these inherited
operations. Access through `request.session` still sets `accessed`, adds
`Vary: Cookie`, and leaves the signed cookie unchanged for the next request.
The same live workflow observes empty `popitem()`, non-iterable `|=`, and a
malformed pair sequence that mutates the session before raising. Oracle and
package match exactly on the error class/message, partial state, flags, absent
response events, and the state seen by a subsequent request. The package
comparisons pass in full-slice run
`2b78c6dd-a6b3-4a96-941d-7ccec76f9518`; this adds bounded evidence, not full
SessionMiddleware parity.

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
mount misses. At this checkpoint, Rust-native ran the built-in Router
projection and marked the Mount cases plus four Python-callable Request
endpoint shapes unsupported. The later bounded Mount goal below closes those
two Mount rows; the four callback rows remain unsupported.

The integrated full run `b2fc5183-407c-4843-b9e3-7e228342159e`, finished at
`2026-09-28T09:08:03.998Z`, selected 148 comparisons: 142 passed, zero failed,
zero infrastructure errors, and six `not_run`. All 101 package comparisons
and 41 of 47 Rust-native comparisons passed. Its manifest SHA-256 is
`f40bd02d232ff032835781aec47a532f6787a375289f14b8213ca9f0758e70ea`; the
target wheel SHA-256 is
`4faf7bf1db038332fa0734e5c86b37c56e55e0fbb71db4ac110c620fe1e498b1`. The
result is local evidence from dirty trees, not an all-target or release pass.
The 21-case reverse URL slice covers the named Python route surfaces and
`Request.url_for`; a separate bounded Rust-native slice now covers two flat
`Router.url_path_for` cases. Direct `Route.url_path_for`, nested Router route
graphs, and Rust custom converter registration remain open. Route/router/mount-
local middleware is present in the Python compatibility layer but is not yet
covered by input-only parity cases.

### Completed bounded goal: reverse URL generation

The input-only `reverse-url-routing.yaml` slice covers `Route`,
`WebSocketRoute`, `Router`, `Mount`, `Starlette`, and `Request` URL generation.
It exercises built-in converter formatting and errors, a Python custom
converter override, first-success router selection, direct and nested mounts,
`app_root_path`, provider fallback, missing context, and the top-level
application forwarder. All 21 source/package comparisons passed. Rust owns the
built-in path substitution primitive used by the Python package; the separate
Rust-native Router URLPath comparisons and their limits are recorded below.
Rust custom converter registration remains open. A separate bounded Host case
is also recorded below.

### Completed bounded goal: direct Host reverse URL formatting

The existing Host reverse-URL input now includes a configured `:3600` port
and selects both the Python package and Rust-native profiles. Rust exposes
`HostPattern::format_url_path` and `HostUrlPath` for the Host route's own-name
branch: the supplied path is preserved, the protocol is empty, and the
formatted host retains its configured port. Nested child-route lookup remains
Python-package only. This slice does not claim full named-route lookup or
absolute URL construction.

### Completed bounded goal: flat Router reverse URL lookup

The two existing `Router.url_path_for` input cases also select the
Rust-native profile. The public `NamedRouteTable` preserves route order, skips
name and exact-parameter-set mismatches, and returns the first matching flat
HTTP route with `http` protocol metadata. Source, package, and Rust return the
same `/objects/7` URLPath for first-success lookup and the same `NoMatchFound`
message for a complete miss. Native support is limited to direct HTTP routes,
built-in converters, and converter-formatted string inputs. Native formatting
failures remain typed Rust errors rather than Python exception objects. Nested
Mount/Host routes, WebSocket routes, and Python custom converters remain
unsupported.

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
four finite synchronous StreamingResponse cases, and the async-iterator,
memoryview-chunk, and custom-async-iterable StreamingResponse cases in section 6
pass source/package parity; the synchronous cases also pass against Rust-native.
Four Rust-native observations remain explicitly `not_run`; the full Starlette
replacement is still incomplete. Six direct `ServerErrorMiddleware` inputs are
now authored for the Python-package profile: construction, custom-handler and
default-response calls, and post-construction `.app`, `.handler`, and `.debug`
mutations. All six pass live source/package comparison in run
`30a58707-ee2a-4146-b14d-2f0b104af348`. The custom-handler input maps to the pinned
`tests/middleware/test_errors.py::test_handler`; the other cases are additional
source-backed behavior probes. Direct debug construction, non-HTTP
pass-through, response-already-started failures, background-task errors, and
other built-in/user middleware combinations remain open. Further work includes broader
HTTP/WebSocket connection and request-body behavior, streaming backpressure
and iterator lifecycle, route-local middleware, nested Host reverse lookup,
broader WebSocket exception flows beyond the three declared cases, remaining
TestClient exception-propagation modes, middleware composition,
authentication, additional synchronous background-cancellation schedules,
context variables, and broader background-task error interactions.

## 4. Optional and edge features

Configuration and schema generation have seven package-only live parity
cases across six Rust-backed public operations. FileResponse range, multipart,
and chunk-size cases are mapped; the package keeps PyYAML optional behind its
`schemas` extra. StaticFiles lookup/configuration, form parsing, templates,
and TestClient HTTP, WebSocket, and lifespan slices also have bounded input
coverage. These are not complete feature implementations: streaming request
bodies, broader TestClient exception modes, route and middleware integration,
and the remaining source-backed behaviors remain in the generated backlog.
Continue from the ranked rows in
[`docs/atlas/fixture-backlog.csv`](atlas/fixture-backlog.csv), keeping optional
dependencies feature-gated and unsupported coverage source-backed.

## 5. Completed bounded goal: Router/GZip benchmark parity

The pinned Starlette 1.6.0 Router/GZip workload catalog contains six Router
and 68 GZip benchmark IDs. All 74 have input-only descriptors and exact
source-versus-installed-package correctness gates. Validation at this
milestone used run
`8bf84b86-3b0f-4003-81bb-bbace448bdcd` ran from
`2026-10-02T14:11:40.374Z` to `2026-10-02T14:15:51.851Z` and measured all
74 source/package workloads with zero failures and zero source/package
`not_run` rows. Its correctness preflight,
`a98b1eac-ec13-4a50-ac49-a239622a9178`, used the active
710-case/734-requirement `parity-input@27` manifest (SHA-256
`7a36d378e7921e3dc1101b5cc55ff65ef77abd27f18b5b968d71acc51f69514f`) and
selected 918 comparisons: 914 passed, zero failed, zero infrastructure errors,
and four Rust-native Python-callable rows were `not_run` (package 708/708;
Rust-native 206 passed, 4 not_run). The target was clean at commit
`f70ee02e33081f52dbefee60ad2b39ff8f23206f` with working-tree SHA-256
`0b9d100a7d3b411776bae1f45e34864cc5e568af566c557344f2b8144268e082`; the
target wheel SHA-256 is
`020d4cee4d224def3d080d0f4878ae96fa21c26ff4d0a4867c3496130305c163`. The
median per-workload source/package latency ratios were 0.774 for Router and
0.973 for GZip; source latency was lower in five of six Router workloads and
54 of 68 GZip workloads. All 74 source/package observation hashes matched.
Benchmark input SHA-256 is
`adafb558a4fadd4fe8c1a956dd03eced2039711440ac7cce2861f1124cc00ed2`; result
artifact SHA-256 is
`b8ae774385a7ad8f9c0bd936a805096c3bb4826f3d5d97264a563be5bb0fc8ae`.
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
Rust selects the endpoint path and invokes the Python function through PyO3.
The synchronous endpoint is passed to the Rust-backed
`starlette.concurrency.run_in_threadpool` awaitable, which delegates execution
to AnyIO's worker-thread API. Python's active task drives each returned
awaitable; the user function body remains Python code.

The new package-only case in
[`asgi-request-cancellation.yaml`](../tests/fixtures/sources/parity/asgi-request-cancellation.yaml)
requests cancellation after the synchronous endpoint enters the worker and
releases the worker afterward. Exact source/package comparison confirms the
request task remains unfinished before release, the worker completes its
finalizer after constructing a response, and `CancelledError` propagates with
no ASGI response events. Rust-native remains unselected because it does not
invoke arbitrary Python Request endpoint callables.

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
Rust selects the callable path, invokes Python callables through PyO3, and
awaits their results through its `PythonAwaitable` continuation. The active
Python task remains the event-loop driver; synchronous Request endpoints use
the Rust-backed AnyIO threadpool bridge described above. This keeps callable
execution and Python exception objects at the boundary while Rust owns route
selection, ASGI ordering, and response policy.

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

### Bounded `StreamingResponse` iteration slice

Four input-only cases cover finite synchronous text and byte chunks: omitted
generated `Content-Length`, preservation of a caller-supplied content length,
`text/plain` framing with per-chunk ASGI events, and byte pass-through. All
eight target comparisons pass against the pinned source, installed Python
package, and Rust-native profile. Python-package cases also cover Starlette's
custom async iterator, a memoryview chunk, and a custom async iterable; each
passes against the source and installed package. Native async iteration remains
unimplemented. The Python wrapper sends the start event before iterating,
emits each chunk lazily using Rust-built ASGI messages, and sends the final
empty body event on exhaustion. The byte case is supported by the pinned source
pass-through branch; upstream has no dedicated raw-bytes test. This evidence
does not establish arbitrary iterator cancellation, disconnect races,
synchronous background-callback cancellation through StreamingResponse, ASGI 2.4
`OSError` mapping, or all memoryview formats.

### Completed bounded goal: Response background task sequencing

[`background-tasks.yaml`](../tests/fixtures/sources/parity/background-tasks.yaml)
contains fourteen package-profile cases with callback mode, arguments, failure,
callable shape, and task-list construction supplied by each input. They cover
async and sync functions, bound methods, callable objects, partials, nested
partials, callback arguments, response-send ordering, worker-thread execution
for synchronous callbacks, both `BackgroundTasks` construction paths,
sequential execution, and propagation that stops later tasks after the first
failure. The cancellation case cancels a response after its async callback
starts and compares the propagated `CancelledError`, callback cancellation,
finalizer, and response event tape. The latest integrated run covers all
fourteen cases, and each passes exact source/package comparison. The
synchronous cancellation case is included in that full profile. The active
fixture crosswalk promotes the
callable-shape behavior alongside the previously mapped BackgroundTask
behaviors.

This remains a bounded slice. Additional synchronous cancellation schedules,
context variables, concurrency, and broader middleware/error interactions with
background failures remain unproven. The latest full run records four
Rust-native Request-dispatch callable rows as `not_run`; the Python package
passed 551/551 comparisons and Rust-native passed 156/160.

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
exceptions or all `TestClient` propagation modes; the three application-level
WebSocket exception workflows are declared separately in the parity evidence.
The separate server-error application cases below cover a bounded
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
not by themselves cover direct `ServerErrorMiddleware` invocation, arbitrary
middleware ordering, or broader WebSocket exception workflows. The separate
`asgi-core.app.test_app_debug` TestClient case now sets debug after construction
and passes source/package comparison. The raw protocol and route-dispatch cases
pass in their declared profiles. Full replacement parity remains open.

[`server-error-middleware.yaml`](../tests/fixtures/sources/parity/server-error-middleware.yaml)
adds six direct public-surface inputs: constructor field observation, direct
synchronous custom-handler dispatch, direct default-response dispatch, and
post-construction `.app`, `.handler`, and `.debug` mutation. Only the custom-
handler input is mapped to an upstream test function,
`tests/middleware/test_errors.py::test_handler`; the other cases are tied to
the pinned `ServerErrorMiddleware` source contract. All six inputs pass exact
source/package comparison in run `30a58707-ee2a-4146-b14d-2f0b104af348`. Direct debug construction,
non-HTTP pass-through, an error after response start, background-task errors,
and other built-in/user middleware combinations remain outside this bounded input set.

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

Broader JSON convenience behavior and async-generator protocol or
introspection beyond the declared inputs, `WebSocketEndpoint`, further
application-level exception modes, `TestClient`, authentication and mount/host
route behavior beyond the child-scope case, additional denial-response and
streaming workflows, file-denial behavior, and concurrency cancellation remain
follow-on work requiring their own input-only workflows and live comparisons. Each fixture contains only
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
