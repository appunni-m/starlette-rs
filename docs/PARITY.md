# Migration parity contract and evidence

The active input contract is [`tests/fixtures/manifest.yaml`](../tests/fixtures/manifest.yaml), using `migration-parity/manifest@2`, `scope.mode: slice`, and `parity-input@34` authored definitions. It contains 895 input-only cases in 88 indexed files, covering 103 operations and 877 parity requirements. Recent inputs compare standard and unknown numeric HTTP response reason phrases through TestClient, HEAD-response body suppression, StaticFiles directory handling when the root is a pathlib.Path, and propagation of a StaticFiles lookup TimeoutError into TestClient’s 500 response. Recent additions include source-shaped TestClient requests for TrustedHost exact-host acceptance, wildcard-subdomain acceptance, invalid-host rejection, and HTTPS `www` redirect following; custom HTTP authentication-error responses, invalid `requires` decoration, synchronous and asynchronous redirect flows, direct `State` plus lifespan-state observations, route-local handling of HTTP exceptions before mounted middleware unwinds, and direct FormData constructor/equality inputs; direct `UploadFile` constructor/repr, spooled-file rollover, and threadpool-boundary cases across rolled and in-memory thresholds; a pinned GZip streaming-response case with ten input-defined 400-byte chunks and public defaults; GZip final-response and streaming-body cases at the configured `thread_minimum_size` boundary; an input-derived AnyIO thread-pool limiter case; generic `Request[State]` and `WebSocket[State]` type contracts; app-state attributes read through `request.app.state`; default string-converter match and slash-boundary cases; expanded route-scope path-parameter observations for string/int/path converters; input-defined datetime converter dispatch and reverse URL formatting; seven QueryParams cases; seven built-in float/UUID converter cases; three StaticFiles HTML fallback scenarios; a StaticFiles directory served through a valid symlinked root using TestClient; a middleware-configured Mount URL lookup; ordered StaticFiles `If-Modified-Since` requests; a TestClient lifespan startup error; TestClient WebSocket accepted-header observations and URL string/component observations for relative and explicit-port URLs; pre-accept WebSocket `receive_text`, `receive_bytes`, and `receive_json` comparisons; exact text, binary, and JSON send/receive exchanges; an input-defined WebSocket `client_state` reset followed by an invalid receive; WebSocket header observations for ordered repeated values, case-varied lookups, and immutable assignment; input-defined WebSocket duplicate-close, connected invalid-send/invalid-receive, and send-callback `OSError` disconnect comparisons; CORSMiddleware private-network-access denial; an empty-text WebSocketEndpoint default-decoding failure; TestClient lifespan task/RunVar continuity and task-group child lifecycle under asyncio and Trio; surrounding pure-ASGI ContextVar observations for BaseHTTPMiddleware and its pure-ASGI control; BaseHTTPMiddleware exception propagation without a chain, through implicit context, and through an explicit cause; and BaseHTTPMiddleware response-background-task completion and failure propagation; a new Starlette application case checks synchronous error-handler invocation after a response background task fails. Existing inputs cover file-like StreamingResponse chunk boundaries, Rust-backed `CommaSeparatedStrings` including lone-surrogate input; `iterate_in_threadpool` and `run_until_first_complete`; StaticFiles configuration and conditional responses; CORSMiddleware origin-isolation and wildcard-without-credentials; Request.cookies edge, invalid, and mapping cases; WebSocket denial and close transitions; direct `GZipResponder`; and broad application, request, response, middleware, and routing boundaries. Recent additions include routed authentication user-interface and protected HTTP routes covering async/sync functions, HTTPEndpoint, injection-wrapped endpoints, and malformed Basic credentials; three documentation-derived BasicAuth inputs cover a wrong scheme, malformed base64, and non-ASCII credentials; six protected WebSocket cases cover plain and injection-wrapped endpoints with absent, malformed, and valid Basic credentials; authentication observations compare custom `BaseUser` overrides, concrete `Request.user` types, middleware-populated `Request.auth.scopes`, and the documented login `next` query redirect; an app-level multipart upload through `Request.form()` under the body limit; and module-global `starlette.config.environ` mutation and Config lookup behavior, plus custom `HTTPException` header forwarding, both built-in and registered `WebSocketException` close policies, and a direct WebSocket constructor signature comparison. A new FileResponse case checks that the input-defined async background task runs after response events and produces `6, 7, 8, 9`. The new literal GET `/func` Router case maps `test_router_add_route` to dispatch behavior; that upstream test never calls `Router.add_route`. New TestClient inputs map `test_mount_at_root` to GET `/` against a root `Mount`, and `test_router_middleware` to GET `/` through a Router-level middleware response; both inputs passed live source/package comparison in run `89f3c4b9-6b92-4631-964e-cdeecdb480e9`, recorded below.

The cases cover Starlette applications and route inventory, including synchronous route GET/HEAD behavior through raw ASGI and TestClient, post-construction `app.debug` mutation and traceback responses, configured TrustedHostMiddleware, mounted StaticFiles and Router URL sequences, host-parameter routing, input-defined follow-up requests on one TestClient instance, middleware registration and ordering; routing and reverse URLs; async endpoint loop/task/thread ownership, callable shapes, and cancellation; URL scope and components; Headers, MutableHeaders, and State behavior; direct Request body, stream, JSON, and form consumption; responses and background tasks, including cancellation and post-construction FileResponse assignments; WebSockets, exceptions, status, endpoints, authentication, middleware, configuration, schemas, and one Python-package Jinja2 workflow. The manifest is authoritative for exact operation and target-profile applicability. The pinned denominator remains 514 upstream test functions and 24 documented pages. The current scope is bounded; it does not claim full Starlette API or behavioral parity.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source references and the source roots used by the API and compatibility inventories. The active manifest is separate: its `input_index` points to generated runtime JSON beneath `build/parity/inputs/`.

Parity and benchmark inputs are authored as JSON-compatible YAML under [`tests/fixtures/sources/parity/`](../tests/fixtures/sources/parity/) and [`tests/fixtures/sources/benchmark/`](../tests/fixtures/sources/). Run `make parity-inputs` or `python3.12 -m scripts.parity.generate_inputs` to serialize the indexed source definitions as JSON under `build/parity/inputs/{parity,benchmark}/`; `make contract-check` regenerates those files before offline contract validation. Generated inputs and parity/benchmark result JSON beneath `build/parity/` are ignored local build outputs, not checked-in fixtures or committed artifacts. Recreate them locally before running a parity or benchmark command.

The compatibility authority is Starlette 1.6.0 at commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The live source oracle checks the release, commit, source import path, source `uv.lock` digest, and CPython identity before it executes any case.

The latest full-slice correctness run `89f3c4b9-6b92-4631-964e-cdeecdb480e9`
ran from `2026-10-04T05:44:33.873Z` to `2026-10-04T05:48:08.653Z` against
Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. It used 895
input-only cases, 877 requirements, and `parity-input@34`. The Rust-native
target and installed package were both built from clean commit
`32a7dcbaf019951715763ff303305998cebcf1dd`.

It selected 1,134 profile comparisons: 1,130 passed, zero failed, zero
infrastructure errors, and four Rust-native Python-callable rows were
`not_run`. The Python-package profile passed 893/893; Rust-native passed
237/241. Both new routing inputs, TestClient `Mount("/")` and Router-level
middleware short-circuiting, passed on the installed-package profile. The
direct-ASGI BaseHTTPMiddleware request-stream case passed on the Python-package
profile against `tests/middleware/test_base.py:777-832`; the input preserves
the minimal `{"type":"http"}` scope, three request-body events, and the source
callback's error if polled beyond those events. Dispatch reads `b"1"`, the
downstream endpoint reads `b"2"`, and dispatch resumes to read `b"3"`, with no
extra receive call. The FileResponse background-task case also passed on both
profiles with callback values `6, 7, 8, 9` after response start and body events.

The four native `not_run` rows remain synchronous Request endpoint,
bound-method endpoint, partial endpoint, and callable-instance ASGI dispatch.
Strict aggregation remains `not_proven` because the pinned compatibility
denominator is incomplete and four Rust-native rows are `not_run`. The native
source fingerprint is
`32a7dcbaf019951715763ff303305998cebcf1dd+source-fnv1a64-6d43214008960872`;
the installed package tree SHA-256 is
`ba3ecbcd806205f620b0ffa3e51997f6fa6cf064f77de0d1474a18a9e4f4cf52` and its
wheel SHA-256 is
`768fff4e12885df888831214f6ea34def04d6793320231ac9e270de3ede1d5fd`. The
manifest SHA-256 is
`a1e9dbf833ff52c6c8aac871968b88e1b4445be648d529fe37348b73f2c04186`; the
result artifact SHA-256 is
`a2a472a1e40012af7de8e4896517be932c4e38ab4774b5e2a470ff5347aeec82` at
`build/parity/parity-result.json`. The command exits with status 2 because the
four declared Rust-native rows remain `not_run`; this is an incomplete strict
gate, not a failed source/package comparison.
The latest clean Router/GZip benchmark run `2dcfd852-43d9-4e1b-9d82-207e482534e5`
measured all 74 source/package workloads on clean commit
`5bcb4bb925304739a16c93484559ff2350c0548a`, with zero failures and matching
normalized observations. Its correctness preflight `53fd98e2-6728-40c7-bb13-7b498906fa10`
selected 1,132 comparisons: 1,128 passed, zero failed, zero infrastructure
errors, and four Rust-native rows were `not_run`; the Python package passed
891/891 and Rust-native passed 237/241. Median source/package latency ratios
were 0.730 for Router and 0.968 for GZip. Rust-native remains `not_run` for
these 74 equivalent ASGI workload boundaries. See [Benchmark mapping](BENCHMARKS.md)
for the run identity and artifact hash. These workload-specific results do not
establish full Starlette compatibility.

For `lifespan_send_messages`, the manifest declares a narrow
`starlette-lifespan-router-frame` normalization: it removes only the
source-only `starlette.routing.Router.lifespan` traceback frame and its source
context lines from startup/shutdown failure messages. Rust implements this
protocol without that Python frame; all other event fields and traceback
frames remain exact.

UploadFile scheduling parity covers rolled and in-memory operation inputs;
direct construction, omitted-size operations, and default/custom-header repr
cases now pass the source comparison.

## Input-only cases

### Direct UploadFile constructor, repr, rollover, and threadpool boundary

[`upload-file.yaml`](../tests/fixtures/sources/parity/upload-file.yaml) adds
one input-only case now maps the direct constructor, representation, rollover,
and scheduling requirements to `tests/test_datastructures.py::test_upload_file_file_input`,
`test_upload_file_without_size`, `test_upload_file_repr`,
`test_upload_file_repr_headers`, `test_uploadfile_rolling`, and
`docs/threadpool.md:6-14`. It creates public `UploadFile` instances over
1-byte and 1024-byte `SpooledTemporaryFile` thresholds, then reads, writes,
seeks, rereads, and closes each file through the async methods. An input-timed
probe checks whether each operation runs on the event-loop thread or a worker,
whether the event loop releases a held rolled-file operation, and whether an
input-defined `OSError` retains its class and message. The source oracle and
installed package match exactly in run
`ec5ae157-c009-4aa3-ab99-f39272234725`. The same case also exercises
BytesIO-backed construction with explicit and omitted size, default and explicit
headers, file identity, metadata, read/write/seek behavior, and initial repr.
All three UploadFile requirements pass exact source/package comparison for these
inputs; broad Starlette parity remains incomplete.

### GZip worker-thread threshold inputs

[`gzip-middleware.yaml`](../tests/fixtures/sources/parity/gzip-middleware.yaml)
adds a final response whose body length equals `thread_minimum_size` and a
streaming response whose first chunk equals that threshold and is followed by
a final tail chunk. Both are Python-package-only because the scheduling bridge
uses AnyIO's Python event loop. They compare exact response headers, compressed
body bytes/chunks, and ASGI event order against pinned Starlette. They do not
claim to observe worker-thread identity. Both comparisons passed in run
`ec5ae157-c009-4aa3-ab99-f39272234725`.

### Shared AnyIO thread-pool limiter

[`concurrency.yaml`](../tests/fixtures/sources/parity/concurrency.yaml) adds
one package-only case grounded in `docs/threadpool.md`. It
starts two `starlette.concurrency.run_in_threadpool` workers and one direct
`anyio.to_thread.run_sync` worker, reduces the shared AnyIO limiter from its
default of 40 tokens to 2, and observes two borrowed tokens with one waiting
task. After releasing the workers, it verifies the configured limit is
restored to 40. The case compares source and installed-package observations
exactly. It is package-only because the stimulus invokes arbitrary Python
callbacks through the Python event-loop boundary.

### QueryParams pair and blank-value comparisons

[`query-params.yaml`](../tests/fixtures/sources/parity/query-params.yaml)
adds seven cases mapped to `test_queryparams` and
`test_url_blank_params`. They compare pair lookup and equality against mappings
and query strings, order-independent mapping equality, duplicate pairs, blank
values, and parameters without an equals sign. Six cases run on both target
profiles. The heterogeneous comparison against the literal string `"invalid"`
is package-only because the native consumer API has no Python object equality
boundary. All 13 selected comparisons pass in the latest full-slice run
`ec5ae157-c009-4aa3-ab99-f39272234725`.

### StaticFiles HTML fallback selection

Three input definitions map
`tests/test_staticfiles.py::test_staticfiles_html_without_index`,
`tests/test_staticfiles.py::test_staticfiles_html_without_404`, and
`tests/test_staticfiles.py::test_staticfiles_html_only_files`.
They exercise an existing directory without an index but with a `404.html`
fallback, an index directory without a fallback page, and an HTML-only tree
without either special file. Ordered ASGI observations include the slash
redirect, selected file body, and propagated 404 exception. All six
oracle-to-target profile comparisons pass in integrated run
`ec5ae157-c009-4aa3-ab99-f39272234725`.

### Built-in float and UUID converters

Seven input cases map the pinned float and UUID converter tests, including
`1.0` versus `1-0`, lowercase and uppercase UUID text with and without
hyphens, and an invalid UUID segment. They observe the selected status and
ASGI response; matched cases also compare the converted `route_scope.path_params`
value and type. The Rust-native parity adapter projects these fields from
`DetailedRouteMatch` captures. All 14 oracle-to-target comparisons pass in
integrated run `ec5ae157-c009-4aa3-ab99-f39272234725`. Additional cases
observe converted path parameters for int/path routes and the default string
converter, including a path with an additional slash that must not match. The
int/float/path/UUID documentation rows now map to those input observations.
Both default-string cases pass on Rust and the Python package in the same run.
The datetime converter cases are package-only because Rust-native route tables
cannot call Python-registered converter callbacks.

### Mount lookup, StaticFiles dates, and TestClient startup failures

The reverse-URL fixture places a named Route inside a Mount configured with
`Middleware` and confirms `Starlette.url_path_for()` returns `/http/`; Rust now
unpacks the public iterable middleware spec instead of requiring a tuple. The
StaticFiles fixture sends the pinned test's two ordered `If-Modified-Since`
headers to one fixed-mtime asset; its first date has a weekday label that
disagrees with the calendar date, which Python accepts and the Rust parser now
handles. The TestClient fixture supplies a startup callback that raises an
input-defined `RuntimeError`; the Send+Sync awaitable removes the cross-thread
drop warning, while the declared traceback normalization is limited to the
source-only Router frame described above. All three cases pass their selected
live comparisons in preflight `0666fe7e-f0b9-42ec-87a7-33baf1fc9e38`; they are
also included in the latest integrated run above.

### `CommaSeparatedStrings` parser and sequence boundary

[`comma-separated-strings.yaml`](../tests/fixtures/sources/parity/comma-separated-strings.yaml)
adds six input-only consumer cases sourced from
`starlette.datastructures.CommaSeparatedStrings` and
`tests/test_datastructures.py::test_csv`. They compare parsed strings,
sequence access, `str()` and `repr()` for the upstream CSV examples, POSIX
shell quoting/comments/empty fields, malformed quotes and escapes, selected
Unicode printable categories, Python `str` subclass identity and live
`__repr__` behavior, and lone-surrogate strings across parsing, sequence
construction, and subclass `__repr__`. Rust owns parsing and formatting in a
Unicode-code-point representation; the PyO3 boundary converts Python strings
through UTF-32LE with `surrogatepass` because Rust UTF-8 `String` cannot encode
unpaired surrogates. The input generator falls back to ASCII-escaped JSON when
the authored input contains a lone surrogate. The Python facade remains a
forwarder. All nine selected native/package comparisons pass in run
`f386b6b5-485b-4914-aad3-89bc05e12085`.

### Request.cookies parsing and Python mapping boundary

[`request-cookies.yaml`](../tests/fixtures/sources/parity/request-cookies.yaml)
defines 15 cookie parsing inputs selected on both profiles and one
Python-package-only mapping probe. The shared inputs observe ordered cookie
items for a structured JSON-like cookie with duplicate and unnamed segments,
all seven `test_cookies_edge_cases` strings, all five `test_cookies_invalid`
strings, multiple raw Cookie fields, and a quoted backslash followed by LF.
The package-only probe observes the live object type, repeated-access
identity, and input-defined assignment and deletion through `Request.cookies`.
All 31 selected profile comparisons pass in run
`df0051d6-23e6-4605-b615-7825c01b848a`. The two parameterized source rows map
to the individual active inputs. The sequential absent-cookie behavior is
covered separately by the TestClient workflow below.

### TestClient cookie persistence round trip

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
defines one input-driven ASGI app and two empty GET requests through the same
TestClient. The app reads `Request.cookies`, responds from the cookie when
present, and sets the configured cookie on the first response. Observations
include both request scopes and headers, both responses, and ordered ASGI send
events. The source and installed-package results match exactly in run
`df0051d6-23e6-4605-b615-7825c01b848a`; the source test row is now mapped in the
generated coverage matrix.

### Async Request endpoint callable shapes

[`asgi-request-callable-shapes.yaml`](../tests/fixtures/sources/parity/asgi-request-callable-shapes.yaml)
defines package-only Request dispatch inputs for async functions, bound methods,
`functools.partial`, and nested partial construction, plus an async function that
raises an input-defined `RuntimeError`. The live comparisons observe the actual
endpoint callable type, partial depth, Request argument, integer path parameter,
single invocation, ASGI response events, loop/task/thread identity, and the
resulting server-error response and exception message. All five cases pass in
run `d54f762e-aac1-461e-8a2d-59223eeb62ca`. Python flattens nested partials
when constructing the object, so the nested-partial input is observed as a
partial with depth 1 on both source and package.

### Request endpoint and ASGI callable failures

[`asgi-request-items.yaml`](../tests/fixtures/sources/parity/asgi-request-items.yaml)
adds an input-defined `RuntimeError` from a synchronous Request endpoint and
from a callable-instance ASGI endpoint. The comparisons observe the synchronous
endpoint's callable, ContextVar, worker-thread, exception, and response details;
the ASGI app comparison observes the concrete callable type, scope and callback
arguments, exception, and response events. Both match the pinned source exactly
in run `d54f762e-aac1-461e-8a2d-59223eeb62ca`. Callable instances follow
Starlette's ASGI-app path and do not receive a Request object. These cases map
the corresponding callable-dispatch and default server-error requirements;
they do not establish all endpoint or exception behavior.

### `Starlette.host()` registration and dispatch

The `starlette-host-method-subdomain` input in
[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
constructs the child Router from input, registers it through `Starlette.host()`,
and sends a matching HTTPS TestClient request. It observes the actual
`application.routes` Host entry and child Route, the request Host header and
captured `path_params`, the 200 response, and ordered ASGI events. The pinned
source and installed package match exactly in run
`d54f762e-aac1-461e-8a2d-59223eeb62ca`. This maps the app-level registration
method for this host pattern and request; other Host matching, naming, and
reverse-URL cases remain bounded by their own inputs.

### `Starlette.mount()` method registration

The `mounted-static-files-get-post` input in
[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
creates a `Starlette` app and registers its named `StaticFiles` child through
`Starlette.mount()`. The package-only observations record the resulting
`application.routes` Mount entry and the child ASGI scope for both GET and POST,
alongside the 200 file response, 405 method response, and ordered ASGI events.
The pinned source and installed package match exactly in run
`d54f762e-aac1-461e-8a2d-59223eeb62ca`. This maps named StaticFiles registration
and dispatch for the supplied path and methods; other mounted-app types and
mount naming or URL-generation cases remain bounded by their own inputs.

### `State` attribute and mapping behavior

[`datastructures-state.yaml`](../tests/fixtures/sources/parity/datastructures-state.yaml)
defines two consumer sequences for `starlette.datastructures.State`. They
compare attribute and item reads, writes, and deletes; aliasing between item
and attribute access; missing-key errors; iteration and length; the instance
dictionary; retention of a supplied mapping; and independent default
instances. Both source/package comparisons pass in the latest full-slice run.

### Application middleware registration and lifecycle

[`application-middleware.yaml`](../tests/fixtures/sources/parity/application-middleware.yaml)
adds five input-only workflows for `Starlette.add_middleware`: class
middleware with distinct positional arguments across lifespan and a later HTTP
dispatch, a factory with positional and keyword arguments, the exact error
after the stack has been initialized, a two-application workflow that checks
stack construction is per application and reuse is per instance, and a
built-in/user boundary trace. The boundary workflow registers two input-defined
middleware classes, compares a POST method-miss handled as 405, then a GET that
raises and produces the outer default 500 while the original RuntimeError
unwinds through user middleware. It records each layer's entry, wrapped sends,
exception, and exit. All five workflows passed exact source/package comparison
in run `d54f762e-aac1-461e-8a2d-59223eeb62ca`. The two-application workflow
maps the constructor-count behavior in upstream `test_middleware_stack_init`;
other built-in/user middleware combinations remain open.

### CORSMiddleware request-origin isolation

[`cors-middleware.yaml`](../tests/fixtures/sources/parity/cors-middleware.yaml)
reuses one `CORSMiddleware` instance for three HTTP dispatches: an allowed
origin, a denied origin, then the same allowed origin again. Each response's
ordered ASGI headers, body bytes, and event order are compared independently.
The pinned source and installed package add `Access-Control-Allow-Origin` to
the first and third response and leave it off the denied response; the final
allowed request retains its header after the denied request. The case passes
exactly in run `2b78c6dd-a6b3-4a96-941d-7ccec76f9518` and maps
`tests/middleware/test_cors.py::test_cors_allowed_origin_does_not_leak_between_requests`
at lines 474-492. This case exercises the Python-package profile only.

### Exception-handler registration and middleware-stack snapshots

[`application-exception-handlers-method.yaml`](../tests/fixtures/sources/parity/application-exception-handlers-method.yaml)
adds two package-only workflows for `Starlette.add_exception_handler`. One
registers async `RuntimeError` handlers before dispatch and after a separate
application's uncaught dispatch has built its middleware stack; it observes
that the late handler does not replace the cached stack's handler snapshot. The
other registers a synchronous status-500 handler before dispatch and records
its exception and Request arguments, response, and worker-thread execution.
The input-defined callbacks supply their labels and response values. Both
source/package comparisons pass exactly with no diffs in run
`d54f762e-aac1-461e-8a2d-59223eeb62ca`. This adds evidence for these
registration boundaries; it does not establish complete exception-policy
parity.

### Request.state lazy initialization

[`request-runtime.yaml`](../tests/fixtures/sources/parity/request-runtime.yaml)
starts a routed request without `scope["state"]`, reads `Request.state`, sets
an input-defined key and value, and observes the value through attribute and
mapping access. The live observations also compare the resulting scope mapping
and confirm repeated property access returns the cached state object. The
Python-package-only case passes exact comparison against the pinned source.

### Request.form multipart limits and cleanup

[`request-form-multipart.yaml`](../tests/fixtures/sources/parity/request-form-multipart.yaml)
now includes the pinned high-count case (2,000 distinct text fields plus 2,000
empty file fields), duplicate text/file values enumerated through
`FormData.multi_items()`, and default/custom `max_part_size` failures through
direct and mounted applications. The latter place oversized part bytes in the
first ASGI message and a sentinel in the next message so the adapters observe
whether parsing stops early. Additional cases compare stream and tempfile
`OSError` cleanup, and verify that large-file rollover occurs in a worker
thread before `Request.close()` closes the upload. All selected Python-package
comparisons match the pinned source exactly. These inputs cover these specific
boundaries and do not establish complete multipart parser parity.

### Synchronous background callback cancellation

[`background-tasks.yaml`](../tests/fixtures/sources/parity/background-tasks.yaml)
holds an input-defined synchronous callback in the AnyIO worker thread until the
response task has received cancellation. The latest clean full-profile run
matches the ordered ASGI send, worker entry and release, worker completion, and
propagated `CancelledError` exactly.

### Direct `run_in_threadpool` callable behavior

[`concurrency.yaml`](../tests/fixtures/sources/parity/concurrency.yaml) adds two
Python-package-only calls through the public `starlette.concurrency` helper.
Each callback, argument list, keyword mapping, and returning or raising behavior
is constructed from input. A synchronous callback waits behind an input-defined
release gate while the event loop records input-defined checkpoints. The
consumer observations compare forwarded arguments, result or propagated
exception identity, worker-versus-caller thread role, and the execution trace
exactly against pinned Starlette 1.6.0. These two cases cover the declared
boundaries only; they do not establish complete thread-pool parity.

### `iterate_in_threadpool` async iteration

[`concurrency.yaml`](../tests/fixtures/sources/parity/concurrency.yaml) defines
input sequences and protocol actions for the public helper. The comparison
observes ordered items, caller-thread iterator construction, worker-thread
`next()` calls, normal exhaustion, invalid `athrow` preserving the next item,
PEP 479 errors for started `StopIteration` and `StopAsyncIteration` throws, and
close-on-throw behavior for unstarted `__anext__`, `asend`, `athrow`, and
`aclose` awaitables. The pinned source and installed package match these
observations exactly in run `d54f762e-aac1-461e-8a2d-59223eeb62ca`. The Python
facade forwards the input to the Rust-owned iterator, which asks AnyIO to
advance it in a worker. This slice does not cover custom iterator failures or
async-generator identity and introspection such as `inspect.isasyncgen()`.

### Config boolean and integer casts

[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
adds an input-only `Config` value-resolution case mapped to
`tests/test_config.py::test_config`. It supplies true/false words, numeric
boolean forms, an invalid boolean, an env-file value cast as both `bool` and
`int`, and a boolean default cast to `int`. The source and installed package
observations match exactly in run
`d54f762e-aac1-461e-8a2d-59223eeb62ca`; each adapter returns the live lookup
results and errors.

### Module-global `config.environ`

The module-global environment input in
[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
mutates the exported singleton before reads, reads present and defaulted
missing keys through public `Config`, then attempts set/delete after each
read. It also compares the singleton's live iteration and length with
`os.environ`. The source and installed package match exactly in the latest
full-slice run; the Python facade and Rust-backed `Config` preserve Starlette's
`EnvironError` behavior at the boundary.

### Response background tasks: bounded parity

[`background-tasks.yaml`](../tests/fixtures/sources/parity/background-tasks.yaml)
contains fourteen package-profile cases with callback mode, arguments, failure,
callable shape, and task-list construction supplied by each input. They cover
async and sync functions, bound methods, callable objects, partials, nested
partials, sequential ordering, both task-list construction paths, and failure
propagation that prevents later callbacks from running. The response send tape
and background callback trace are observed from both pinned source and installed
package; no output values are encoded in the fixture. All fourteen cases pass
exact source/package comparison in the latest integrated run. The async
cancellation case records propagated `CancelledError`, callback cancellation,
finalization, and response events. The synchronous cancellation case holds its
worker callback until cancellation reaches the response task, then compares
worker completion and propagated `CancelledError`. Rust owns callback
classification, task sequencing, and dispatch in the installed package; the
Python adapter supplies and observes user callbacks at the Python boundary.
Additional synchronous cancellation schedules, context variables, concurrency,
and broader middleware/error interactions with background failures remain
unproven.

### BaseHTTPMiddleware waits for a response background task

[`base-http-middleware.yaml`](../tests/fixtures/sources/parity/base-http-middleware.yaml)
adds one input case mapped to
`tests/middleware/test_base.py::test_run_background_tasks_even_if_client_disconnects`.
It invokes a configured BaseHTTPMiddleware app with the pinned direct ASGI
scope, a receive callback that raises if used, and an async endpoint returning
a response with an input-delayed `BackgroundTask`. Source and installed-package
observations match exactly: the response body completes, the receive callback
is never called, the background task starts and finishes before the app
returns, and no exception propagates. This checks the declared middleware and
response lifecycle boundary only; it does not claim broad disconnect handling
or full background-task compatibility.

### Async endpoint event-loop ownership and cancellation

[`asgi-call-boundary.yaml`](../tests/fixtures/sources/parity/asgi-call-boundary.yaml)
supplies an async ASGI endpoint and a `dispatch`, then `cancel-server-task`
schedule. The source and installed package observations match exactly: the
endpoint enters on the caller's event loop, request task, and thread; receives
`asyncio.CancelledError`; runs its finalizer; and propagates cancellation with
no response events. This is an asyncio-only package-profile probe of the
Python-callable boundary. It does not establish Trio behavior or cancellation
propagation for synchronous Request endpoints. The Rust-native profile is not
selected because this input intentionally invokes a Python ASGI
callable.

### Synchronous Request endpoint worker cancellation

[`asgi-request-cancellation.yaml`](../tests/fixtures/sources/parity/asgi-request-cancellation.yaml)
holds a synchronous Request endpoint in AnyIO's worker pool, requests
cancellation of the ASGI request task after worker entry, and then releases the
worker. The source and installed package match exactly: the request task is not
done before release, the worker constructs its response and runs its finalizer,
the worker completes, and the request task propagates
`asyncio.exceptions.CancelledError` without sending response events. This case
selects the Python package profile because the Rust-native consumer does not
invoke arbitrary Python Request endpoint callables.

### Application and route request-body limits

[`route-body-limits.yaml`](../tests/fixtures/sources/parity/route-body-limits.yaml)
supplies four ASGI POST requests with application and route limits in the
input. One route inherits the application's five-byte cap and rejects a
fragmented six-byte body without Content-Length; another rejects a one-byte
body under an application cap of zero. The remaining routes raise a five-byte
application cap to ten bytes and lower a ten-byte application cap to five
bytes. The source and installed package report the same response status,
headers, body bytes, and ASGI event order for each input. The Rust-backed
`Route.__init__` bridge receives `max_body_size` directly; Rust also builds the
limit middleware's 413 response through the shared response state machine. The
Python facade contains no limit-selection or response-construction logic.
These cases prove only the declared limit combinations; app-limit placement
relative to body-reading user middleware, Mount/Router override composition,
and broader route stream/error boundaries remain in the fixture backlog.

### Application Router-miss 404 handler

The `router-miss-404-http-exception-handler` input requests an unmatched GET
path while the app has a registered async handler for `HTTPException`. Starlette
`Router.not_found` raises its application-scoped 404, and the configured
handler returns a JSON response. The pinned source and installed package
produce the same 404 status, content headers, JSON bytes, and ordered ASGI
events. The input contains no expected output; the callback and request path
are supplied as stimulus.

### Parameterized Host pattern and port handling

[`host-routing-native-port.yaml`](../tests/fixtures/sources/parity/host-routing-native-port.yaml)
contains one HTTP Router case with a fixed-response child. The Host pattern is
`{tenant}.example.test:3600`, and the input Host header is
`acme.example.test:5600`. The source and both target profiles match the Host
route, expose `tenant="acme"` in the child scope, and return the same 200
response bytes and ordered ASGI events. The additive Rust API exposes
`HostPattern::new` and `HostPattern::match_host` for named captures; this
fixture is one bounded consumer comparison of that behavior.

The source behavior is defined by pinned Starlette 1.6.0
`starlette/routing.py::compile_path` and `Host.matches`: Host pattern
compilation discards a configured port suffix, and `Host.matches` removes the
incoming Host port before matching and adding captures to `path_params`. The
upstream `tests/test_routing.py::test_host_routing` also documents that the
requested port is irrelevant. This evidence covers the one parameterized HTTP
route and port pair in this fixture. A separate direct Host reverse-URL input
compares the supplied path, empty protocol, and configured `:3600` host port
on the Python package and Rust-native profiles. It does not establish full
Router Host dispatch, Host route ordering, nested Mount behavior, WebSocket
Host matching, IPv6 authority parsing, or nested Host reverse lookup.

The BaseHTTP body/stream parity cases map to `tests/middleware/test_base.py:599-712,715-773,835-862`. At `599-628`, dispatch exhausts `request.stream()` before `call_next`, then downstream stream iteration yields only the cached empty chunk. At `689-712`, adapters record the `b"a"` body read in dispatch and again in the endpoint; the endpoint response carries those observed bytes. The two cases at `715-773` record dispatch reads after the endpoint exhausts its stream or reads `request.body()`. The case at `835-862` caches the body before `call_next`, then records dispatch stream replay after the endpoint reads the cached body. These inputs contain no expected exceptions or chunks: source and installed package report the live reads and exact response events. The selected profiles run through asyncio and do not establish Trio behavior from the upstream test-client fixture.

The two disconnect cases map to `tests/middleware/test_base.py:894-976`. One records the downstream app receiving `http.disconnect` before dispatch checks `Request.is_disconnected()`; the other records dispatch caching `b"hi"`, observing the following disconnect, then downstream receiving the cached body and disconnect. Both report `True` from the live request check and match source/package receive and response traces exactly. These direct ASGI cases select the Python package profile and exercise asyncio.

[`templating-runtime.yaml`](../tests/fixtures/sources/parity/templating-runtime.yaml)
adds one Python-package case for `Jinja2Templates`. Its input supplies a
directory template, markup and route values, a synchronous context processor,
response metadata, and an ASGI scope with the debug extension. The source and
package observations match exactly for autoescaped HTML, processor merge
order, `url_for`, template/context metadata, headers, body bytes, and ASGI
event order. Rust owns template environment setup, processor invocation and
merge, template lookup, the URL global's request lookup, and the debug-event
decision. The thin Python response class inherits the `HTMLResponse` facade,
which sends through Rust's response implementation; the Rust URL callable
exposes dynamic attributes because Jinja's `pass_context` decorator attaches
its context marker to the callable. Install the opt-in `templates` extra to
use this module. The configured-environment, no-Jinja import, and broader
template workflows remain in the fixture backlog.

[`asgi-http-get-text.yaml`](../tests/fixtures/sources/parity/asgi-http-get-text.yaml) contains JSON-compatible input values and observation selectors only. The generator serializes this authored definition to runtime JSON; no source definition stores expected status, headers, body, response messages, or lifecycle trace. The GET, missing-path, and wrong-method cases construct one app with a public `/hello` route returning a `PlainTextResponse`; the endpoint makes two public `Response.set_cookie` calls. The successful case also declares an async-context lifespan callback and sends startup then shutdown. A post-construction registration case calls `Starlette.add_route` and dispatches both GET and POST. The new async-route case models `test_app_add_route`: its input-defined async endpoint returns a `PlainTextResponse` from `GET /`.

The Python target runs the installed `starlette-rs-py` `Starlette` ASGI callable with a real Python scope, receive callback, and send callback. The Rust target constructs the exported `starlette_rs::Starlette` with an `ApplicationRoute` and calls its async `call` method with the scope's path/method projection and Rust future-based callbacks. It awaits response-start then response-body sends. The static response cases do not read request input, so the Rust receive callback remains unused, matching the Python endpoint's behavior. The native API does not model every ASGI scope field, host an executor, or invoke Python endpoints. The input-defined async-route case selects only the installed Python package because it exercises a real Python `Request` endpoint: the Rust-backed package dispatches and awaits that callable at the Python boundary, and the complete ASGI response is compared to the source oracle.

The `/missing` case requests GET for an absent path. The wrong-method case requests POST for the existing GET-only path. These are separate workflows with their own source and target observations, so 404 and 405 behavior is measured rather than encoded as expected output.

[`asgi-request-items.yaml`](../tests/fixtures/sources/parity/asgi-request-items.yaml) adds three cases with a separate `request-dispatch` observation profile. Each case constructs one GET `/items/{item_id:int}` route whose declarative `request-observer` endpoint reads a Request and returns the input's fixed plain-text response marker. The successful input requests `/items/0007?tag=red&tag=blue`, supplies a lowercase ASGI header that the endpoint looks up using mixed-case names, a cookie, and JSON split across two `http.request` messages. The two other inputs exercise a route miss at `/items/nope` and POST `/items/7` against the GET-only route. All response observations come from the live source and targets; the input file contains only route/request stimulus and observation selectors.

The request observation record selects the converted path parameter and runtime type, `QueryParams.getlist` plus scalar lookup, two differently cased `Headers` lookups, the parsed cookie, and `await Request.json()`. A separate scope observation records identity checks for `app`, `router`, and `endpoint`, path-parameter presence, and the resulting `path_params` mapping. The installed Python target checks live object identity; the Rust-native request adapter builds a routed-scope model and checks identity-token references. This model applies to the three `request-dispatch` cases only; their evidence does not exercise a public Rust `Request` or the new native `Starlette::call` API. The full ASGI response events remain exact, with only the declared `Allow` token-set normalization.

[`request-runtime.yaml`](../tests/fixtures/sources/parity/request-runtime.yaml)
adds three source/package cases for `Request.send_push_promise`: extension-
enabled event construction with one allowed and one ignored request header,
the no-op when the extension is absent, and the exact default missing-send
error. Rust owns the extension check, header filtering, event construction, and
callback await; the Python method forwards the call through PyO3. These cases
exercise the Python callback boundary and do not claim a Rust-native
`Request` API.

The same input file adds two `Request.is_disconnected` cases. Rust owns the
cancel scope, receive polling, disconnect cache, and boolean result; the Python
method delegates directly to that state machine. The cancellation case blocks
the receive callback at an AnyIO checkpoint, then verifies that the canceled
poll leaves `http.disconnect` queued for the later check. Both cases match the
pinned source and installed package exactly.

The upstream basis is `starlette/requests.py` (`HTTPConnection.headers`, `query_params`, `path_params`, `cookies`, and `Request.stream`/`body`/`json`), `starlette/datastructures.py` (`ImmutableMultiDict` and `Headers`), and `starlette/routing.py` (`Route.matches` and `Router.app`). Related pinned tests include `tests/test_requests.py::test_request_query_params`, `test_request_headers`, `test_request_cookies`, `test_request_json`, `tests/test_routing.py::test_route_converters`, and `test_router`.

[`base-http-middleware.yaml`](../tests/fixtures/sources/parity/base-http-middleware.yaml)
now contains twenty-one Python-package cases, all passing exact comparison
against pinned Starlette 1.6.0 in the latest integrated run. They cover
configured-middleware response-header mutation and replacement responses,
request-body cache/replay across dispatch and the downstream endpoint, response
completion waking a blocked downstream receive as `http.disconnect`, downstream
exception/context propagation (including its cause, TaskGroup `ExceptionGroup`
context, and suppression observations), partial-stream forwarding, and
downstream receive transformation, repeated disconnect polling, and request
body/stream replay orderings across dispatch and the downstream endpoint. The pathsend case maps to `tests/middleware/test_base.py:1219-1259`: a GET FileResponse sends `http.response.start` followed by `http.response.pathsend` through BaseHTTPMiddleware without calling receive. Status, headers, event order, and the declared basename match exactly; only the harness temporary root is normalized. The
caught-exception case matches
`tests/middleware/test_base.py:338-356`: the endpoint raises
`ValueError("TEST")`, dispatch catches it from `call_next`, and returns a
plain-text 400 response whose body is derived from `str(exc)`; the compared
observations include the caught exception class/message/status and no
propagated exception. The partial-stream case maps `test_read_request_stream_in_dispatch_wrapping_app_calls_body` at
`tests/middleware/test_base.py:777-832`. It passes the source test’s minimal
`{"type":"http"}` scope and three input-defined body events. Dispatch consumes
`b"1"`, the downstream endpoint consumes `b"2"`, then dispatch resumes and
consumes `b"3"`; the receive callback would raise if called again. Source and
installed package make exactly three receive calls and produce identical
observations. The receive-transformation
case matches `tests/middleware/test_base.py:979-1017`: dispatch reads the
original `b"foo "`, a downstream ASGI wrapper doubles the `http.request` body,
and the endpoint reads `b"foo foo "`; observations include both bodies, the
before/after receive message, and the outer empty-200 ASGI events. Rust owns
the BaseHTTP state machine, cached receive/replay decisions, response-completion
race, and response sending. The downstream transformation is a
caller-supplied Python ASGI middleware callable: the facade passes it through
and awaits it at the Python boundary while Rust handles BaseHTTP protocol
state. The repeated-disconnect cases match
`tests/middleware/test_base.py:1168-1215`: one supplies a chunked body followed
by disconnect and the other begins with disconnect; both poll downstream
receive twice. Their observations include raw and downstream receive traces,
each poll's drained request events and result, and the exact `200 b"good!"`
response tape. The stream-consumption workflow matches
`test_read_request_body_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:660-686`: dispatch exhausts `request.stream()`
through `b"a"`, the terminal empty chunk, and iterator exhaustion; downstream
reads the cached empty body and returns `Homepage`. The body-cache/stream-replay
workflow matches `test_read_request_stream_in_app_after_middleware_calls_body`
at `tests/middleware/test_base.py:631-657`: dispatch reads `b"a"` with
`request.body()`, then downstream `request.stream()` yields `b"a"` and `b""`
before returning `Homepage`. The source TestClient fixture declares asyncio and
trio backends, while the active input selects the Python-package profile only;
this case does not establish parity for both backends. This is a bounded
Python-package slice, not general `BaseHTTPMiddleware` parity.

The new dispatch replay case maps to
`test_read_request_stream_in_dispatch_after_app_calls_body_with_middleware_calling_body_before_call_next`
at `tests/middleware/test_base.py:835-862`: dispatch caches `b"a"`, the
endpoint reads that body, and dispatch's stream iterator yields `b"a"`, then
`b""`, then exhausts. All observed chunks and the response tape matched the
source exactly. Rust already owns the cache/replay state; this adds parity
evidence without adding runtime Python behavior.

The discarded-stream cancellation case maps to
`tests/middleware/test_base.py:473-546`: dispatch reads one `call_next` body
chunk, closes the response iterator, and returns a replacement response while
the downstream app streams until disconnect. The observations compare the
consumed chunk, cancelled stream, replacement response, and disconnect trace.
Rust implements the iterator's async `aclose()` protocol; the source and
installed package match exactly. The adjacent response-completion case maps to
`tests/middleware/test_base.py:549-596` and checks that completion unblocks a
downstream receive.

Unverified BaseHTTP behavior still includes other receive-transformation and wrapper combinations, partial-stream/replay interleavings beyond the tested `b"1"`/`b"2"`/`b"3"` flow, disconnect ordering across stacked middleware, broader exception cause/context combinations and exception-group shapes beyond the observed TaskGroup context and caught `ValueError`, varied and malformed `http.response.debug` frame sequences, cancellation and ContextVar behavior, background-task and context-manager cleanup ordering, path-send combinations beyond the covered FileResponse forwarding case, the full `MutableHeaders` API and live `raw_headers` mutation, and other streaming paths. The atlas backlog retains the remaining upstream middleware cases.

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
contains 14 direct `Response` and `JSONResponse` ASGI-call cases for text,
bytes, null content, header initialization and mutation, an input-defined
`Response.render` subclass override, memoryview content, and cookie behavior.
The mutable-header case maps to
`tests/test_responses.py::test_response_headers`: it constructs a response with
two headers, changes `x-header-2` through `response.headers`, and captures the
ASGI output. The default renderer, media-type selection, and response-header
mutation are Rust-backed; subclass rendering remains a user-Python callback.
The latest integrated run passed this case against the pinned source, installed
package, and Rust-native response adapter. The memoryview, override, and
version-bound cookie cases select the Python-package profile.

[`streaming-response.yaml`](../tests/fixtures/sources/parity/streaming-response.yaml)
adds four direct `StreamingResponse` ASGI-call cases for finite synchronous
chunks: no generated `Content-Length`, preservation of an explicit length,
`text/plain` framing across five text chunks, and pass-through of one base64-
defined binary chunk. It also adds the input from Starlette's
`test_streaming_response_custom_iterator`, a finite async iterator yielding
`"1"` through `"5"`, a memoryview chunk, and a custom async iterable. The four
synchronous cases passed on both target profiles. The iterator, memoryview,
and custom-iterable cases are Python-package-only and passed against the source
and installed package. Starlette has no dedicated raw-bytes streaming test; the
byte case probes its source implementation's bytes pass-through branch
directly. These cases do not establish arbitrary iterator cancellation,
disconnect behavior, background-task ordering, or all memoryview formats.
The package-only `pre-asgi24-disconnect-cancellation` case is sourced from
`test_streaming_response_stops_if_receiving_http_disconnect`: it declares an
ASGI 2.3 scope, repeating binary chunk input with an event-loop checkpoint, and
a receive callback that waits for the input-defined 16-byte send threshold
before returning `http.disconnect`. Its execution trace observes the supplied
generator cancellation/finally markers and background recorder. It passed exact
source/package comparison in integrated run
`d54f762e-aac1-461e-8a2d-59223eeb62ca`; this bounded case does not establish
all streaming edge cases or a Rust-native async-streaming API.
The package-only `client-disconnect-oserror` case follows
`test_streaming_response_on_client_disconnects`: it uses an ASGI 2.4 scope,
repeating byte input after event-loop checkpoints, a receive callback that
raises `NotImplementedError` if called, and an input-selected send failure on
the second body event. The comparison observes the partial ASGI event tape,
generator trace, and propagated `ClientDisconnect` from the pinned source and
installed package.

[`request-path-param-types.yaml`](../tests/fixtures/sources/parity/request-path-param-types.yaml)
adds six installed-package Request cases for typed path parameters, including
a 5001-digit integer that exercises CPython 3.12's default conversion limit.
[`mount-route-dispatch.yaml`](../tests/fixtures/sources/parity/mount-route-dispatch.yaml)
adds seven Mount cases for child `root_path`, `app_root_path`, merged path
parameters, response, mount miss, child 404, child 405, inherited parameter
collisions, nested scope composition, and inner Mount miss. The source,
installed Python package, and Rust-native `Mount` API execute all seven cases.
The native API supports recursively nested Mounts and HTTP child routes with
prebuilt responses; Rust owns Mount matching, typed capture merging,
child-scope projection, and fallback responses.

[`lifespan-generators.yaml`](../tests/fixtures/sources/parity/lifespan-generators.yaml)
adds 15 Python-package `Starlette.__call__` lifecycle cases: sync and async
generator lifespans each cover success, startup failure, and shutdown failure;
six cases cover generators that return without yielding, extra yields, and
suppression of shutdown callback errors; two cases cover synchronous exceptions
while invoking startup `send` and shutdown `receive`; and one verifies
type-level `__aenter__`/`__aexit__` lookup when the manager instance shadows
them. All 15 pass against the pinned source. Rust
owns generator detection, deprecation policy, generator context-manager state,
sync-to-async adaptation, lifecycle ordering, and failure transitions. Rust
drives Python's generator protocol methods; the Python callable and event loop
remain the host boundary. The package facade no longer defines generator
factory, context-manager, or lift helpers.

[`reverse-url-routing.yaml`](../tests/fixtures/sources/parity/reverse-url-routing.yaml)
adds 21 input-only cases for `Route`, `WebSocketRoute`, `Router`, `Mount`,
`Starlette`, and `Request` reverse URL generation. It covers the built-in path
converters, converter failures, a custom converter override, first-success
route selection, nested mounts, `Request.url_for` provider and root-path
behavior, and the application forwarder. The Python package passed all 21
cases. Two existing Router inputs also select the Rust-native profile: a
first-success lookup returns `/objects/7`, and a complete miss returns the
source `NoMatchFound` class and message. `NamedRouteTable` is limited to flat
direct HTTP routes, built-in converters, and converter-formatted string
parameters. Native converter-formatting failures remain typed Rust errors
rather than Python exception objects. Nested Mount/Host routes, WebSocket
routes, custom Python converters, and direct `Route.url_path_for` remain outside
the native slice.
The Rust route table also builds converter-formatted paths for the Python
bridge.

[`router-cache-invalidation.yaml`](../tests/fixtures/sources/parity/router-cache-invalidation.yaml)
adds source/package/Rust-native parity for live Router mutations. It dispatches
once, adds `POST` to an existing route's method set, dispatches again, appends
a new route, and dispatches a third time. Rust's `RouteTable::add_method`
preserves the supplied spelling and does not apply route-constructor `GET` to
`HEAD` inference. Exact observations cover selected route indices, status,
headers, response bytes, and ASGI event order for all three steps. This maps
live method mutation and route-list append; mounted child-router mutation
remains a separate gap.

[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
adds three package-profile cases for environment mapping read freezes, config
lookup precedence and casts, and missing-file warnings.
[`schemas-runtime.yaml`](../tests/fixtures/sources/parity/schemas-runtime.yaml)
adds four package-profile cases for schema route selection and path conversion,
docstring YAML parsing and parser errors, and OpenAPI response rendering. Their
Python `starlette.*` modules forward to Rust; the adapters run the same
input-only cases against pinned Starlette 1.6.0.

[`authentication-runtime.yaml`](../tests/fixtures/sources/parity/authentication-runtime.yaml)
adds four package-profile cases covering credential and user values, scope
checks, sync/async `requires` outcomes, redirects, WebSocket denial, and
authentication middleware success, error, and non-HTTP dispatch. The source
oracle and installed package receive the same inputs; the public Python
facades forward to Rust-owned policy and middleware state handling. These
cases cover 19 declared requirements and do not claim complete authentication
API parity.

[`static-files.yaml`](../tests/fixtures/sources/parity/static-files.yaml) and
[`static-files-symlink-asgi.yaml`](../tests/fixtures/sources/parity/static-files-symlink-asgi.yaml)
together contain 29 input-defined `StaticFiles` ASGI-call cases,
[`static-files-lookup.yaml`](../tests/fixtures/sources/parity/static-files-lookup.yaml)
compares 15 direct `lookup_path` calls, including Unix and UNC-style absolute-path rejection,
parent traversal, a symlinked configured root, and internal and external file
and directory symlinks with both `follow_symlink` settings. The observations
include the resolved relative path and file metadata. Four package-only cases
in [`static-files-config.yaml`](../tests/fixtures/sources/parity/static-files-config.yaml)
compare constructor-time missing-directory failure, lazy checks for missing
and non-directory roots, and `config_checked` across repeated missing-path
requests. A package-only case in
[`static-files-async-boundary.yaml`](../tests/fixtures/sources/parity/static-files-async-boundary.yaml)
gates the bound `lookup_path` override and observes the callback running on an
AnyIO worker while the event loop progresses. The ASGI-call inputs select 27
comparisons on each target profile; package-discovery cases use Python's
`importlib`, and Rust-native explicit-root cases use supplied roots. The two
path-limit cases exercise an
overlong first root with both `follow_symlink` settings and verify that its
404 preempts a later configured root containing the requested asset. Two more
cases remove search permission from an existing asset's root and compare the
401 exception with both symlink settings. Together
with the 15 lookup cases on each profile and the package-only async-boundary
and four configuration cases, they produce 89 profile comparisons: 42
Rust-native and 47 Python-package.
They cover rooted GET and HEAD,
HTML index redirects and 404 fallback, 401/404/405 outcomes, date and ETag
validators including the two-request ETag-mismatch sequence, validator
precedence, package assets, absolute-path rejection,
file/directory metadata, path traversal and symlink containment, external file
and directory symlink serving, bound override dispatch, the resulting ASGI response, and path-limit error precedence. Python
package discovery is exercised through `importlib` on the Python package
profile; Rust-native package cases pass explicit roots. All 89 selected
StaticFiles comparisons passed in run `0c6a7de9-d5f7-44db-83b1-4d1ec0a3472a`,
including all 30 direct lookup comparisons. Four package-only configuration
inputs match the pinned constructor-missing-directory, lazy missing-root,
lazy file-root, and repeated-request checks at `tests/test_staticfiles.py:124-165`.
These cases do not cover the full 36-function upstream StaticFiles suite.
Known gaps include constructor errors beyond the missing-directory case,
permission conditions beyond root-search denial, subclass hooks beyond `lookup_path`, a
separate scheduling assertion for `check_config`, cross-platform
`os.stat_result` fields and Windows path normalization and semantics, and
remaining validator branches.

Earlier integrated run `2a46e263-b1d2-4b80-bde4-262075bd998c` (superseded by
the latest run recorded above) started at
`2026-09-29T12:09:32.851Z` and finished at `2026-09-29T12:10:30.993Z`. It
selected 448 profile comparisons: 444 passed, zero failed, zero infrastructure
errors, and four were `not_run`. The Python package passed all 311 selected
cases; Rust-native passed 133 of 137 selected cases. The four Rust-native rows
require arbitrary Python endpoint callables. All 27 FileResponse cases passed
on both target profiles, and all eight SessionMiddleware cases passed on the
Python package profile. The native target was dirty at revision
`268ccde19b0eef1d0c7401303daca50ff940abf9+source-fnv1a64-6d02a046883b0cf5`;
the installed Python package is identified by content hash
`8285e8f4e2f6b18e01e8d5f2766d7aabc960413e18b00b26b8f5b1a14bfad646` and is
marked dirty by the adapter. Manifest SHA-256:
`287280853528a55a455e26e2ecb9c2f6c0600e7d7a853c0f41b04c82af99cfb6`.
Package wheel artifact SHA-256:
`5fc234604060873cb4f1c6b5933743790007443feae652d74e6182574c8c5f22`.
`make parity-run` exits with status 2 for the four explicitly unsupported
Rust-native Python-callable rows; this run does not establish full Starlette
parity or release readiness.

The package policy check confirms there is no upstream Starlette runtime
dependency and no Python control flow in its runtime facades. Routing template
tokenization, URL scope construction and query operations, response defaults and rendering, push-
promise policy, middleware defaults, and middleware error policy are
implemented in Rust; Python methods forward values through the PyO3 boundary.
Python remains the public import and user-callable/event-loop boundary. The
overall Starlette replacement remains incomplete.

The synchronous function case, `starlette.applications.Starlette.request-dispatch.sync-get-items-0007-contextvar-worker`, sends `GET /items/0007` through a route declared as `/items/{item_id:int}`. It selects the converted integer path parameter, caller `ContextVar` propagation, execution on a worker thread distinct from the ASGI caller, one endpoint invocation, route-scope observations, and complete ASGI events. The latest integrated run above compares this case exactly between pinned Starlette 1.6.0 and the installed Python package. Its Rust-native row is `not_run` because that profile cannot invoke a Python callable through this boundary; the manifest declares the sync-endpoint observations unsupported for Rust-native.

The active input contract adds two Request-style synchronous endpoint cases: `starlette.applications.Starlette.request-dispatch.sync-bound-method-get-items-0007` and `starlette.applications.Starlette.request-dispatch.sync-partial-get-items-0007`. Like the original function case, they select integer path conversion, caller `ContextVar` propagation, execution on a worker thread distinct from the ASGI caller, one invocation, route-scope observations, and complete ASGI events. The third case, `starlette.applications.Starlette.request-dispatch.asgi-callable-instance-get-items-0007`, declares a callable instance as the route's ASGI app. It receives `(scope, receive, send)` and selects route-scope observations and the complete live ASGI response events; it does not use a `Request` object or the AnyIO request-endpoint worker boundary. These are input-only parity cases, not expected outputs.

This follows pinned Starlette 1.6.0's route distinction: functions, bound methods, and `functools.partial` values resolving to those forms are Request-style endpoints. Async forms are awaited on the event loop; synchronous forms use AnyIO worker threads. Callable instances are treated as ASGI applications. The earlier 51-case checkpoint `480437e5-e1f4-4e25-91a5-1453ba82ea69` established source/package parity for these forms; the current integrated evidence is recorded above.

This repository uses live source-to-target parity as its behavioral gate and
has no conventional Python or Rust unit-test suite. `make test` runs the
declared source, installed-package, and supported Rust-native workflows; the
four unsupported Rust-native callable rows keep the current all-target gate
incomplete. `make parity-run` builds the Rust-native adapter before executing
it, so the adapter matches the current source tree.
An earlier 95-case parity result, including Router converter, Mount dispatch,
and reverse-URL cases, is generated locally at
`build/parity/parity-result.json`; that file is ignored and not committed.

## HTTPException default response slice

[`asgi-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-http-exceptions.yaml) adds five input-only cases in which a matched HTTP request-style endpoint raises `HTTPException` before response start. They cover an omitted detail for status 406, an explicit detail for 406, omitted details for 204 and 304, and an omitted detail plus a custom response header for status 200. The input contains only endpoint status/detail/header stimulus and observation selectors; response values come from the live source and target runs.

All five cases pass source-versus-installed-package comparison against pinned Starlette 1.6.0. The package target resolves omitted details at Python's `HTTPStatus` boundary, so the pinned response details include the relevant status phrases. Rust-native supports the explicit-detail 406 response and matches the oracle for that case; it does not provide Python's default status-phrase lookup. The Python shim catches the raised `HTTPException` because it is a Python exception from a Python callable; it forwards the resolved status, detail, and headers, while Rust constructs the HTTP response. This keeps exception-object handling at the callable boundary and response policy in the Rust core. The integrated run recorded above includes these cases; four callable rows remain unsupported for Rust-native, while Mount dispatch is covered by its public native API.

This slice covers HTTP exceptions raised by matched request-style endpoints before response start, one callable-ASGI endpoint that raises after sending a complete response, the two registered-handler cases described below, and the bounded server-error cases in the next section. The after-start HTTPException case compares the chained `RuntimeError`, its `HTTPException` cause, `suppress_context`, and the partial response event tape. Three application-level WebSocket exception workflows are covered in the WebSocket section; the declared TestClient propagation cases are covered separately, while custom error-handler output, other built-in/user middleware combinations, and broader exception identity/chaining remain open.

[`asgi-callable-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-callable-http-exceptions.yaml) adds two input-only callable-ASGI route cases. One raises `HTTPException(406)` before sending a response and observes Starlette's handled 406 response. The other sends an input-defined 200 response start and body, then raises `HTTPException(406)`; Starlette raises a `RuntimeError` chained from the HTTPException after the 200 events have already been sent. Both cases pass exact source-versus-installed-package comparison. The v4 result record captures the exception class, message, direct cause and public attributes, `suppress_context`, and partial ASGI observations. Rust-native is `not_run` for these Python-callable endpoints because it cannot invoke arbitrary ASGI callables.

## Registered exception-handler cases

[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml) adds three input-only `Starlette.__call__` cases, all selected for the Python-package profile. `starlette.applications.Starlette.__call__.exception-handler.status-code-precedence` registers the `HTTPException` class handler before the 405 status-code handler, then POSTs to a GET-only route. Starlette selects the exact status-code handler before the class handler, producing a distinct JSON response from the class handler's exception-detail response. The input declares handler keys and response recipes; it contains no expected response.

`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse` sends the request body in chunks. The endpoint reads `Request.body()` and raises the input-declared `BodyReuseException`, a subclass of `HTTPException`. Its async class handler reads `Request.body()` again and builds a JSON response from the decoded request bytes, exercising the cached body on the same Request. For this package boundary, `JSONResponse` uses Python JSON value serialization; Rust owns response framing, headers, and ASGI event delivery.

`starlette.applications.Starlette.__call__.exception-handler.headers-forwarding` raises an input-defined `HTTPException` with two headers. Its registered async class handler passes the exception status, detail, and headers into `JSONResponse`, so the result exercises header preservation through the public application call. The input defines the handler recipe and exception values; the source oracle and installed package produce the response.

The earlier 51-case result selected 76 comparisons and had four Rust-native rows `not_run`. The latest integrated result is summarized above and includes these registered-handler cases; this slice does not establish full replacement parity.

## ServerErrorMiddleware application cases

[`asgi-server-errors.yaml`](../tests/fixtures/sources/parity/asgi-server-errors.yaml) adds nine input-only HTTP cases through `Starlette.__call__`, all selected for the Python-package profile. The cases cover the no-handler default 500 response, a registered integer 500 handler, a registered `Exception` handler, both insertion orders for the special 500 and `Exception` handler keys, text and HTML debug tracebacks that take precedence over a configured 500 handler, an unhandled `RuntimeError` after response start, and a handled `HTTPException(500)` that stays on the inner handled-exception path. They map to `starlette.asgi.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order`, `.debug-traceback`, `.response-started`, and `.handled-http-exception-500`.

The exact case IDs are `starlette.applications.Starlette.__call__.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order.status-then-exception`, `.special-key-order.exception-then-status`, `.debug.plain-text-overrides-handler`, `.debug.html-selected-by-accept`, `.runtime-error-after-response-start`, and `.handled-http-exception-500`. All nine now pass source-versus-package comparison. The two debug cases use the declared traceback projection to omit only Python Starlette package frames and their source snippets, while retaining the user endpoint frame and exception summary. No native cases are selected for these Python-callable app workflows.

The operation declares the `starlette-debug-traceback` projection for response bytes, ASGI response events, and ordered headers. The comparator inspects each live response body and projects out traceback frames and source snippets from Python modules under the `starlette/` package, then normalizes remaining frame paths, line numbers, HTML frame IDs, and `Content-Length`. For HTML tracebacks, it also canonicalizes whitespace-only separators between adjacent closing `div` tags after framework-frame removal; these separators do not change the rendered markup. It retains user-code frames and the exception summary, and applies only to Starlette's actual debug-traceback structure. When no debug traceback is present, response bytes and headers retain their exact comparison. This decision comes from the observed body, not a case or requirement identifier. The source and target result records retain the raw traceback bodies. All other selected response fields remain exact, subject only to the separate declared `Allow` token normalization. The projection is parity infrastructure; it adds no behavior to the Python compatibility runtime.

This evidence is limited to these input-defined `Starlette.__call__` workflows. `asgi-core.app.test_app_debug` remains backlog because these inputs construct the app with `debug=True`; they do not set `debug` after app construction. Direct `ServerErrorMiddleware` coverage now includes HTML debug rendering, post-response exception propagation, and non-HTTP passthrough; remaining direct error-policy cases, other built-in/user middleware combinations, TestClient behavior, broader WebSocket behavior, and full replacement parity remain open.

## WebSocket protocol, state, and route-dispatch inputs

The direct WebSocket protocol, state, and route-dispatch contract has three
input-only operations. The full public
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
contains six core protocol sequences, four denial-response transitions
(response start, body continuation, final body, and duplicate response start),
two invalid connected-state transitions, and one public `client_state`
reassignment case based on `test_receive_before_accept`. It records each
action's outcome and, for errors, the exact Python compatibility class and
message, plus final `client_state` and `application_state`. It excludes message
payloads, callback tapes, and exception context. Each case selects the pinned
source, installed Python package, and Rust-native state machine; the native
comparison establishes only this projected state behavior.

[`websocket-convenience.yaml`](../tests/fixtures/sources/parity/websocket-convenience.yaml)
adds an iterator boundary case for `asend(non-None)` on a fresh async
generator. The source and installed package return CPython's `TypeError`
before consuming the next WebSocket event; the send value is forwarded
into the Rust-owned iterator state machine. It also maps
`test_receive_text_before_accept`, `test_receive_bytes_before_accept`, and
`test_receive_json_before_accept` to single-action cases that compare the
typed-receive error, ASGI callback tape, and final states. Three additional
cases map the text, binary, and JSON send/receive exchange tests, alongside the
existing Unicode text-JSON and binary-JSON cases. These comparisons select the
Python-package profile.

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

Five package-profile cases in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml)
exercise WebSocket exception routing through the public `Starlette.__call__`
surface: the built-in `WebSocketException` close handler with omitted and
input-defined reasons, a registered HTTP exception handler returning a denial
response before acceptance, a synchronous custom exception handler for a
custom exception, and an async handler registered for `WebSocketException`.
The supplied-reason case raises `WebSocketException(code=1008, reason="policy
violation")` and compares the close code and reason. The custom-class-handler
case raises `WebSocketException(code=1011, reason="endpoint failure")` while
the registered handler closes with its input-defined code 1008, confirming that
the custom handler overrides the built-in close behavior. Scope, connect event,
route actions, handlers, and denial extension are inputs; captured WebSocket
events and response bytes come from the live source and target. These callback
workflows select the Python-package profile.

[`websocket-scope-interface.yaml`](../tests/fixtures/sources/parity/websocket-scope-interface.yaml) also compares the constructor calls shown by the WebSocket docs. The docs list `receive` and `send` as optional; the pinned `WebSocket.__init__` and installed package both raise the same exact `TypeError` when called with only `scope`, and both construct successfully with explicit callbacks. This records the source/docs discrepancy in favor of the pinned implementation. The Python constructor check is package-profile-only because Rust-native does not expose this Python API.

At the earlier WebSocket checkpoint, the three direct operations contained 15
cases and selected 21 comparisons: six protocol tapes for Python-package, six
projected state cases for each target, and three route cases for Python-package.
All 21 passed in run `480437e5-e1f4-4e25-91a5-1453ba82ea69`. The active
contract also includes the later convenience, close, and application-level
exception workflows; this does not establish TestClient WebSocket-session
parity.

[`gzip-middleware.yaml`](../tests/fixtures/sources/parity/gzip-middleware.yaml) contains eighteen direct ASGI middleware cases. The original eight cover negotiated final compression, identity negotiation, a small-body bypass, configured exclusion, streaming compression, path-send passthrough, an existing-encoding streaming bypass, and a partial-response streaming bypass. Ten source-backed additions cover all five pinned default-excluded content types, default SVG compression, all three content-type exclusion normalization triples, and per-chunk streaming with an intermediate empty chunk. Inputs omit constructor settings when the pinned tests use public defaults. Every source and target observation compares ordered ASGI events and raw response bytes without compression or event normalization. The Rust-native adapter drives `GzipConfig` and `GzipResponder`; the installed Python package exposes `starlette.middleware.gzip.GZipMiddleware`.

[`gzip-responder.yaml`](../tests/fixtures/sources/parity/gzip-responder.yaml)
adds two Python-package inputs for the upstream test's direct
`starlette.middleware.gzip.GZipResponder` import. One constructs the responder
with a mixed-case, parameterized excluded content type and compares the
uncompressed ASGI response; the other calls the responder without an
`Accept-Encoding` request header and compares the compressed response bytes.
The Python facade forwards construction and invocation to Rust's gzip runtime.
This slice does not claim parity for the responder's other internal methods or
mutable attributes, and Rust-native does not select the Python ASGI-callable
boundary.

The Rust compressor uses `flate2`'s streaming gzip encoder and preserves zlib's sync-flush behavior across ASGI chunks. Compression decisions, exclusions, response-header edits, and stream state live in Rust. Python remains at the async boundary: it forwards ASGI callbacks and uses AnyIO's task-local capacity limiter and worker-thread facility for chunks at or above `thread_minimum_size`.

The legacy `__call__` profile selects exact response status, ordered repeated header bytes, body bytes, ASGI event order, complete ASGI events, and lifecycle/cleanup effects. The `request-dispatch` profile selects request observations, route-scope observations, response status, ordered repeated header bytes, ASGI event order, and complete ASGI events. Missing ASGI message fields remain missing in evidence. Repeated `Set-Cookie` headers must be produced by the two `Response.set_cookie` calls; adapters cannot inject output header values.

The `Response.asgi-call.set-cookie-attributes` input applies a fixture-defined sequence of public `Response.set_cookie` calls before ASGI dispatch. It covers optional attributes, a fixed HTTP-date expiry string, and omitted `Path` and `SameSite` values. The source, installed Python package, and Rust-native adapter construct their own headers from those same calls; the observation compares the complete ordered header bytes. Package-only cases also exercise timezone-aware `datetime` and integer-offset expiry conversion against a fixture-controlled clock, plus the CPython 3.12 `partitioned=True` error before ASGI dispatch.

The PyO3 boundary converts Python `datetime` expiry values with `email.utils.format_datetime(usegmt=True)` and integer expiry offsets with `http.cookies._getdate`, then passes only formatted strings to Rust. These inputs and their exact formatting follow the active interpreter's standard-library contract and clock, so reimplementing that conversion in Rust would duplicate Python-specific semantics. The boundary also reads `sys.version_info` for `partitioned=True`, because Starlette gates that option on the running Python version. These conversions and the version error are covered by the package-only inputs above; Rust owns cookie validation, attribute ordering, and header serialization.

The manifest includes one direct-ASGI GET `/hello` latency workload in [`inputs/benchmark/asgi-get-hello.yaml`](../tests/fixtures/sources/benchmark/asgi-get-hello.yaml). It selects the pinned source oracle and both target profiles, times only the dispatch step, and requires a fresh successful exact parity run first. The benchmark worker then resolves the same parity case from its indexed input, verifies the input and case digests, and runs a fresh source-versus-installed-package probe before collecting samples. Warm-up, measurement count, sample count, concurrency, and cache state come from the benchmark input.

For this smoke case, the worker constructs the app and starts its fixture lifespan before warmups, keeps the lifespan active across fresh HTTP scopes and ASGI message/callback containers for every dispatch, then shuts down after sampling. It requires ordered `lifespan.startup.complete` and `lifespan.shutdown.complete` events and compares the completed cleanup trace with the source probe, outside timed regions. Each measured call's HTTP events are also checked against the probe immediately after its timer stops.

The timer measures in-loop `await app(scope, receive, send)`. It includes fixture-to-ASGI scope/message materialization, callback creation, and response collection; it excludes app construction, lifespan startup/shutdown, and event comparison. The pinned upstream routing runner enters the event loop with `loop.run_until_complete` for each dispatch, while this timer excludes per-dispatch loop-entry overhead. These numbers therefore do not reproduce upstream timings and are neither Rust-kernel-only measurements nor real-server throughput. The result is written as strict `benchmark-result@1` at `build/parity/benchmark-result.json` when the command runs. Rust-native remains `not_run` because its measured boundary is not equivalent. This is a one-case smoke benchmark, not a representative Router/GZip result. The separate `benchmark-upstream` runner now measures all 74 pinned Router/GZip workloads against source and the installed package; Rust-native remains `not_run` at those non-equivalent boundaries. See [Benchmark mapping](BENCHMARKS.md).

## SessionMiddleware input slice

[`session-middleware.yaml`](../tests/fixtures/sources/parity/session-middleware.yaml) defines input-only workflows for the installed Python-package profile. The inputs cover a signed-cookie write/read/clear round trip, a malformed signature fallback, the pinned negative `max_age` expiry case, custom name/path/SameSite/Domain/Secure attributes with `max_age=None`, direct `Session` mutation flag behavior for set, delete, clear, pop, popitem, setdefault, update, and in-place union, signed-cookie loading into a WebSocket scope, lifespan pass-through, and the documented `Secret` key wrapper's redacted representation, string conversion, truthiness, and signing use. A later request receives the earlier response's live `Set-Cookie` value through the `previous-set-cookie` source selector; no cookie value or output is authored in the fixture. These workflows map to the pinned session tests, the source branches for WebSocket and lifespan scopes, and the configuration and middleware documentation; they remain a bounded SessionMiddleware slice rather than full Starlette parity.

Run `2b78c6dd-a6b3-4a96-941d-7ccec76f9518` compares inherited `dict.popitem()` and `Session |= values` through the actual `request.session`, including mapping and pair-sequence inputs and their failure paths. The empty `popitem()` raises `KeyError`; union with a non-iterable raises `TypeError`; and union over a valid pair followed by a malformed pair applies the first pair before raising `ValueError`. Source and package match exactly on exception class and message, the partial session contents, `accessed=True`, `modified=False`, the absence of response events after the error, and the later request's session view. The Python methods forward to Rust, which invokes built-in `dict` operations to retain mapping, pair-sequence, partial-mutation, return-value, and identity behavior.

Rust owns cookie signing and verification, expiry and clearing decisions, response header behavior, the documented `Secret` representation and truth behavior, and session mutation state. The PyO3 value-conversion boundary calls Python's standard-library `json.dumps` and `json.loads` from the Rust session core to preserve the source's Python JSON byte representation before signing and after verification. The SessionMiddleware input workflows compare those boundaries against the pinned source. The WebSocket case observes the loaded scope session through the public `WebSocket` wrapper while leaving Session access and modification flags false. The lifespan case drives startup/shutdown completion messages from fixture input and compares exact event order. This codec dependency remains a documented Python compatibility boundary. The public status of the upstream `SessionMiddleware.signer` attribute remains unresolved and is tracked as an API candidate in the compatibility inventory.

## Exact comparison and allowed normalization

Comparison is exact for all selected fields except the narrow `allow-methods-as-set` normalization declared on `ordered_repeated_headers` and `asgi_events`, the declared `starlette-debug-traceback` normalization, and the FileResponse `multipart-range-boundary` and `file-response-temp-path` normalizations. The Allow normalization applies only to comma-separated tokens in an `Allow` header value: the comparator trims surrounding whitespace, sorts unique method tokens, and compares the normalized value. The traceback normalization activates only when live observations contain an actual Starlette debug traceback; it removes frames and source snippets from modules under the `starlette/` package, normalizes remaining frame paths, line numbers and HTML frame IDs, canonicalizes whitespace-only separators between adjacent closing `div` tags in HTML, and normalizes the body-length header. It retains user-code frames and the exception summary. The multipart normalization activates only when the live FileResponse `Content-Type` is `multipart/byteranges` with Starlette's 26-character lowercase hexadecimal boundary. It replaces that token in the header and MIME delimiter lines in body bytes while preserving their lengths; file-part bytes, metadata, other headers, event ordering, and chunk boundaries remain exact. The `file-response-temp-path` normalization applies to FileResponse `http.response.pathsend` events and the BaseHTTPMiddleware forwarding case. It requires an absolute emitted path whose basename matches the input file and whose parent matches the source or target harness temporary-directory pattern, then replaces only that varying parent with a stable marker. For direct FileResponse calls it applies to `asgi_events`; for BaseHTTPMiddleware it also applies to the matching `execution_trace` message. These dynamic values are derived from live observations, never from case identifiers. Unrelated BaseHTTP cases remain unchanged, and result records retain the original unnormalized events, headers, and raw response bodies.

The request-scope mutations are covered by the three original HTTP `request-dispatch` cases and the new typed path-parameter cases. Mounted routes and non-empty `root_path` have bounded dispatch observations, including child 404/405 and inherited parameter collisions; nested Mount composition and other application paths remain outside this slice. The successful `__call__` workflow schedules lifespan startup, HTTP dispatch, and lifespan shutdown on the same app task; it verifies that the lifespan context stays active across that in-flight dispatch and exits afterward. The lifecycle-only cases cover sync/async generator entry and cleanup, startup/shutdown failures, synchronous callback-call failures, and type-based special-method lookup. TestClient parity also constructs an actual Starlette application with an input-defined async-context-manager lifespan callback and compares its startup-entry and shutdown-cleanup effects around context entry and exit; this maps to `tests/test_applications.py::test_app_async_cm_lifespan` and `docs/lifespan.md:142-158`. A stateful TestClient workflow compares lifespan-yielded state through HTTP and WebSocket consumers, attribute and mapping access, per-request shallow copies, shared nested objects, isolation from `app.state`, and portal reuse across lifecycle, HTTP, and WebSocket calls. Lifespan cancellation and broader concurrency behavior remain outside this slice. The Rust-native `Starlette::call` is an additive, bounded response dispatcher over a path/method projection, not a full ASGI application object. The Rust request adapter's routed-scope model is likewise not a public Rust `Request`.

## Isolated environments and adapter protocol

Run `prepare-env` before either oracle-only or full parity evidence. It builds the target wheel from this checkout, creates separate CPython 3.12 virtual environments for the pinned Starlette source oracle and installed `starlette-rs-py` wheel, and installs isolated dependencies from hash-pinned locks: the source oracle uses `scripts/parity/locks/starlette-oracle-cpython312.txt` (including ItsDangerous for the pinned session middleware), while the installed package uses `scripts/parity/locks/asgi-runtime-cpython312.txt` and its PyYAML schema dependency. The generated environment lock records the repository-relative interpreter paths, runtime, platform, dependency-lock digest, installed-package freeze digest, environment digest, target wheel digest and its canonical package-tree digest. It also binds the target source commit and working-tree identity. The runner rechecks those identities, verifies the installed package tree against the wheel, and does not fall back to a global Python interpreter. Python adapters receive `STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256` for their own environment; the native adapter receives the SHA-256 of `Cargo.lock`.

Each adapter runs in a fresh process. The runner sends one strict JSON `migration-parity/adapter-request@1` object on stdin and accepts exactly one JSON response object on stdout. The response envelope remains `migration-parity/adapter-response@1`; its opaque workflow payload follows the versioned parity-input and parity-result contracts. Diagnostics go to stderr. Identity responses are checked against the source revision or installed target environment before workflows run. The result schema is `migration-parity/parity-result@4`, which retains oracle revision/module/lock provenance, target revision/tree/lock/package identity, and per-side environment fingerprints. The prepared Python environment digest includes a fixed process policy: `PYTHONHASHSEED=0`, with `PYTHONOPTIMIZE` and `PYTHONWARNINGS` removed. Unknown fields, duplicate JSON keys, malformed output, absent interpreters/adapters, crashes, timeouts, identity mismatches, missing or extra observations, skipped evidence, and unsupported evidence cannot pass.

[`url-scope.yaml`](../tests/fixtures/sources/parity/url-scope.yaml) adds 20 input-only `URL(scope=...)` cases mapped to the pinned ordinary construction, invalid Host fallback, and authority-in-path tests, plus a source-backed empty-server-host serialization edge. Each adapter constructs a public URL from the supplied scope and reports its live string, repr, and URL components; inputs contain no expected URL values. The Rust-backed Python facade keeps the constructor behavior in Rust. All 20 cases passed in the latest integrated run.

[`url-components.yaml`](../tests/fixtures/sources/parity/url-components.yaml) adds 14 URL component access and ordered `replace(**components)` workflows. [`datastructures-headers.yaml`](../tests/fixtures/sources/parity/datastructures-headers.yaml) adds ten `Headers` and `MutableHeaders` construction and consumer workflows, including duplicate order, scope/raw-list aliasing, mutable-copy pair identity and independence, no-op mutation identity, and ordered mutation. [`responses-basic.yaml`](../tests/fixtures/sources/parity/responses-basic.yaml) observes the cached `Response.headers` object and its raw-list alias, while [`file-response.yaml`](../tests/fixtures/sources/parity/file-response.yaml) observes base header-view isolation across single and multiple range calls. These new package-only cases passed exact source/package comparison in the latest integrated run. The Python facades forward these operations to Rust; the public Python consumer interfaces remain the compatibility contract.

The `parity-input@13` contract adds an explicit filesystem graph to StaticFiles ASGI cases. Its callable-ASGI `HTTPException` cases drive an ordered action sequence from fixture data. If the app raises after response events have been sent, the adapter marks that workflow step `error`, preserves the chained exception and `suppress_context` flag, and records the partial ASGI observations in `partial_value`. This keeps captured application behavior comparable while adapter crashes and malformed evidence remain infrastructure failures.

The `parity-input@14` contract adds an optional `params` mapping to TestClient WebSocket inputs. The authored cases compare inline URL query text with `websocket_connect(..., params=...)`, then observe the live `query_string`, `raw_path`, and raw-path bytes received by the client. The shared adapter forwards the input mapping to the public TestClient call; it does not encode an expected query result.

The `parity-input@15` contract adds `app` to the Request connection-property input family. The new routed request observes the live qualified type of `request.app` and whether it is the same object as `request.scope["app"]`; expected observations stay in the source and target runs.

The `parity-input@16` contract adds a routed Request.state case with no initial `scope["state"]`. It observes lazy scope initialization, input-defined assignment and reads through attribute and mapping access, and reuse of the cached State object. The comparison derives every value from the live source and installed-package request.

The `parity-input@17` contract adds an input-defined TestClient WebSocket app action that constructs the public `WebSocket`, reads `dict(websocket.query_params)`, sends that live mapping as JSON, and closes. It maps `docs/websockets.md:40-44` and `tests/test_websockets.py::test_websocket_query_params`; the separate raw query-string and `raw_path` projection cases remain distinct.

The `parity-input@18` contract added a TestClient workflow that constructs `Starlette(debug=False)`, mutates `debug` after construction, and invokes an input-defined exception route with `raise_server_exceptions=False`. It observes the public response, emitted ASGI events, post-request `app.debug`, and whether the input exception name occurs in the live body. The source and package raw traceback outputs remain available; the declared reusable normalization handles only source-dependent traceback frames and body length.

The `parity-input@19` contract added an input-defined Starlette app with `TrustedHostMiddleware` configured in its middleware stack, then sent the pinned invalid-host TestClient request. The observations include the live Host scope, HTTPX response, and emitted ASGI events.

The `parity-input@20` contract added an input-defined sequence of TestClient follow-up requests and a Starlette app that mounts StaticFiles. The `test_app_mount` workflow keeps one app and TestClient instance for GET then POST, supplies file contents and a fixed modification time as inputs, and compares each live response and the ordered ASGI effects. All active authored parity inputs were migrated by `make migrate-parity-inputs-v19-v20`; the migrator changes only the top-level schema header and supports `--check`.

The `parity-input@21` contract added TestClient app shapes for a named Router Mount and a Starlette Host route. The mounted-URL case derives four GETs from input and records each HTTPX response URL, including the final URL after the `/users` slash redirect. The Host-route case supplies the HTTPS base URL, allowed hosts, host pattern, child route, and endpoint prefix as input. It also records `response.url` for every TestClient response. All indexed authored inputs were migrated by `make migrate-parity-inputs-v20-v21`; the migrator changes only the top-level schema header and supports `--check`.

The prior `parity-input@22` contract added input-defined exception cause and context relationships to TestClient ASGI exception cases. Three inputs compare identity preservation and cause/context observations for explicit cause, implicit context, and suppressed context while the same TestClient call propagates the application exception. The `@21` to `@22` migrator changed only the top-level schema header.

The previous integrated run above used `parity-input@22`; all three TestClient exception-chain cases passed exact source/package comparisons. `oracle-only` invokes only the pinned source workflows. It writes a comparison row per target profile with target workflow status `skipped`, a reason, and outcome `not_run`. The benchmark correctness gate accepts only a clean target identity. Generated results are local ignored artifacts and are not checked in.

The `parity-input@23` contract adds a TestClient lifecycle workflow derived from `tests/test_testclient.py::test_use_testclient_as_contextmanager`. The input-defined lifespan callback enters a task group, uses an input-defined AnyIO `RunVar` token source, and serves managed and transient HTTP requests. Adapter observations include live request values, startup/shutdown values, same-task identity, and whether re-entry creates a new task. Separate cases exercise the source test's `asyncio` and `trio` backend instantiations; Trio and its platform-specific dependency closure are locked for parity environments only and are not Starlette runtime dependencies. All 77 indexed authored inputs were migrated by `make migrate-parity-inputs-v22-v23`, which changes only the top-level schema header and supports `--check`. Focused run `d60a8b0c-8bf9-494c-8eb1-73aef835b37c` passed both exact source/package comparisons with no diffs on the dirty shared checkout.

The `parity-input@24` contract extends
[`base-http-contextvars.yaml`](../tests/fixtures/sources/parity/base-http-contextvars.yaml)
with the same input-defined surrounding pure-ASGI observer for the
BaseHTTPMiddleware case and its pure-ASGI control. It reads the live ContextVar
before and after downstream execution alongside the existing caller,
middleware, endpoint, and ASGI response observations. The BaseHTTPMiddleware
observer returns with `middleware-value`; the pure-ASGI control returns with
`endpoint-value`, as the pinned docs and test describe. These are live source
and package observations; the authored input contains selectors and actions,
not expected outputs. The case is grounded in `docs/middleware.md:343-350`,
`tests/middleware/test_base.py:208-265`, and
`starlette/middleware/base.py:101-199`. Focused run
`85372de5-e607-4ca3-8f57-a03d2a759d11` passed both exact source/package
comparisons with no diffs. The `@23` to `@24` migrator changes only the schema
header and validates all 77 indexed authored inputs.

The `parity-input@25` contract adds two input-only cases for
`tests/test_convertors.py::test_datetime_convertor`: Router dispatch parses a
date-time path segment into a Python `datetime` for the synchronous endpoint,
and direct `Route.url_path_for` formats a datetime value through the converter.
The datetime format, regular expression, request path, endpoint projection,
and reverse-path datetime components are supplied as inputs. The `@24` to
`@25` migrator changes only the schema header and validates all 77 indexed
authored inputs. Full run `6d3d141b-58bc-4294-a9fd-af5c1b0e4015` passed both
exact Python-package comparisons.

The `parity-input@26` contract adds two input-defined static type requirements
for generic lifespan state. A consumer TypedDict supplies an `http_client`
string through lifespan; Mypy checks that `Request[LifespanState].state` and
`WebSocket[LifespanState].state` expose that key as `builtins.str`, while a
bare `Request.state` retains `starlette.datastructures.State`. The pinned
source and installed package produce the same reveal types with Mypy 1.19.1 on
CPython 3.12. The wheel includes `starlette/py.typed`; the facade's
`TypeVar` default uses `typing_extensions>=4.12.0`. Rust cannot provide these
Python static generic declarations at runtime, so the boundary is limited to
declarative annotations and the package marker. The `@25` to `@26` migrator
changes the schema header and validates all 77 indexed authored inputs.

The same `parity-input@23` revision adds a two-dispatch CORSMiddleware input for private-network-access denial and a WebSocketEndpoint input for empty text under `encoding=None`. Both focused source/package comparisons passed; the output artifacts remain in ignored `build/parity/` storage. Together, the `@23` additions increase the indexed denominator from 671 cases/703 requirements to 675/706 without claiming a new full-slice run. The `@24` observer adds one parity requirement, leaving 675 cases and increasing the requirement count to 707. Later input additions under that schema add three StaticFiles HTML fallback cases and three requirements; the resulting `@24` contract had 678 cases and 710 requirements.

### TestClient lifespan child-task lifecycle

The active schema adds asyncio and Trio TestClient cases that start an
input-defined child task inside the lifespan callback, release its wait gate
during teardown, and observe task-group completion before the callback exits.
Both source/package comparisons pass exactly in run
`6d3d141b-58bc-4294-a9fd-af5c1b0e4015`. After TestClient enter, the trace is
`lifespan-started`, `child-started`; after exit it is
`lifespan-started`, `child-started`, `child-release-requested`,
`child-finished`, `lifespan-finished`, followed by the shutdown-complete
message. The cases map `docs/lifespan.md:27-33` and
`starlette/routing.py::Router.lifespan`; they establish this controlled
child-task lifecycle only.

### TestClient exception policy

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
also describes application exceptions as input. The three exception-policy
cases compare default exception propagation, the synthesized 500 response when
an app fails before sending a response with `raise_server_exceptions=False`,
and preservation of a completed response when the app raises after sending it.
The adapter records the live response or exception and partial ASGI observations;
the case ID does not select the behavior. Rust owns this policy in the transport,
and the Python `starlette.testclient` methods forward to it.

### TestClient debug response observations

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
supplies one response sequence containing `http.response.debug` and observes
the resulting `response.extensions` mapping alongside the response body and
event order. A second input constructs `ServerErrorMiddleware(debug=True)` around
an app that raises an input-defined `RuntimeError`, then observes the TestClient
500 response and generated debug text with exception propagation disabled.
These cases map `tests/test_testclient.py::test_debug_info_in_response_extensions`
and `tests/middleware/test_errors.py::test_debug_text`; both match the pinned
source exactly in run `d54f762e-aac1-461e-8a2d-59223eeb62ca`.

### TestClient configured TrustedHostMiddleware

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
also constructs a Starlette app with input-defined `TrustedHostMiddleware`
configuration and a route, then sends `GET /func` through TestClient using
`http://incorrecthost`. Both live consumers observe the Host scope and the
middleware-generated 400 response, including ordered headers, bytes, and ASGI
event order. This maps `tests/test_applications.py::test_middleware` and
checks the app-level middleware stack; direct middleware dispatch remains a
separate input slice.

### TestClient mounted StaticFiles sequence

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
also reproduces `tests/test_applications.py::test_app_mount`: it writes the
input-defined file into isolated temporary roots with an input-fixed mtime,
mounts `StaticFiles` at `/static`, and sends GET then POST through the same
Starlette app and TestClient. The source and package both return 200 with
`<file content>` and then 405 with `Method Not Allowed`; response headers and
the ordered four-event ASGI trace match exactly. The fixture stores only file
bytes and metadata, not expected outputs.

### TestClient mounted Router URLs and host routing

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
also maps `tests/test_routing.py::test_mount_urls`: one TestClient calls
`/users`, `/users/`, `/users/a`, and `/usersa` against an input-defined Router
with a named Mount and PlainTextResponse child. The first call follows the
slash redirect and records final URL `http://testserver/users/`; all four
responses and five ASGI request scopes match the pinned source exactly.
Another input maps `tests/test_applications.py::test_subdomain_route` through
Starlette, TrustedHostMiddleware, Host, a child Router, and a synchronous
endpoint. The source and package both return `Subdomain: foo` for the HTTPS
host `foo.example.org`, with the request scope and ordered ASGI events equal.
The existing app-level `url_path_for` input is also linked to
`tests/test_applications.py::test_url_path_for` in the source atlas.

### TestClient WebSocket blocking receive and close teardown

[`testclient-websocket.yaml`](../tests/fixtures/sources/parity/testclient-websocket.yaml) adds two input-only workflows mapped to the pinned `tests/test_testclient.py::test_websocket_blocking_receive` and `test_websocket_not_block_on_close` tests. The first accepts the input-selected subprotocol, sends an input-defined JSON message from a task-group child while the app main task waits in `WebSocket.receive_json()`, and has the synchronous client receive the frame before it exits the session. Context exit sends the default disconnect; the app records its `WebSocketDisconnect` class, code, and reason. The observation tape compares the exact callback order and all message fields.

The second app accepts and waits forever without consuming receive input. Context exit causes cancellation; the input-defined handler records the cancellation class, re-raises it, and the app finalizer records completion. Both cases retain the app's actual portal thread object and report whether it is alive after the session context returns. The observed portal thread is stopped in the pinned source and installed package. The latest full-slice run above includes these lifecycle inputs and the JSON text/binary cases; all 893 Python-package comparisons passed.

The Rust-backed `WebSocketTestSession.receive_json(mode="text")` method selects the text or binary frame, forwards disconnect as the public `WebSocketDisconnect`, and invokes Python's JSON decoder through the Rust boundary. Its `starlette.testclient` method is a direct forwarding facade.

Two more input-only cases exercise `WebSocketTestSession.send_json()` and `receive_json()` in text and binary modes. The app observes the live ordered ASGI event tape, including compact JSON text with non-ASCII characters and UTF-8 bytes for binary frames. Rust calls Python's standard JSON encoder with Starlette's pinned `separators=(",", ":")` and `ensure_ascii=False` options, and leaves serialization and decoding errors unchanged across PyO3. The Python methods retain Starlette's `Literal["text", "binary"]` annotations and forward directly to Rust.

### TestClient WebSocket accepted headers

Two input-only workflows map `tests/test_websockets.py::test_additional_headers` and `test_no_additional_headers`. Each starts a live TestClient WebSocket session and compares the ordered `websocket.accept` header pairs with `WebSocketTestSession.extra_headers`, including the empty list emitted by `WebSocket.accept()` without custom headers. Rust retains the accepted ASGI value and the Python property forwards it directly. Both source/package comparisons pass in the latest run.

### Mounted middleware and route-local HTTP exception handling

[`route-middleware-dispatch.yaml`](../tests/fixtures/sources/parity/route-middleware-dispatch.yaml)
adds an input-only workflow mapped to
`tests/test_routing.py::test_mounted_middleware_does_not_catch_exception`.
It sends four ordered requests through root and mounted routes, with
input-defined response-header middleware at both levels and endpoints that
raise `HTTPException(403, "auth")`. The Rust route state machine selects a
status handler before walking exception classes in MRO order, invokes async
handlers on the active loop and sync handlers through Starlette's threadpool
boundary, and tracks response-start messages through a Rust-created send
proxy. Python remains only at the endpoint and registered-handler call
boundaries. The `/mount/err` response includes both `X-Mounted` and `X-Outer`,
and the status, ordered headers, body, and ASGI event tape match the pinned
source exactly in run `b0b0f52e-5c0f-488d-8d42-a51b174e6b9e`.

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

The current boundary has Rust own built-in path matching and path formatting, response framing, middleware compression policy, and WebSocket protocol state. Python keeps Starlette's public route objects and ASGI dispatch layer, calls registered Python converters and application endpoints, and preserves the event-loop, threadpool, exception, and lifetime behavior at those boundaries. The route matcher falls back to Python only for custom converters, which cannot be represented by the current Rust converter set. For GZip, AnyIO owns the task-local worker limiter and thread scheduling, while Rust owns compression and response policy. `GZipResponder` now has a thin package facade for construction and ASGI invocation, with direct input coverage for exclusion normalization and compression without negotiation; its other internal attributes and methods remain outside the selected slice.

The parity lifecycle step covers one successful async-context enter/exit separately from its HTTP dispatch. The Request-style synchronous endpoint inputs cover functions, bound methods, and `functools.partial`; a separate callable-instance case covers ASGI dispatch through `(scope, receive, send)`. The latest integrated run includes six slash-redirect cases, four direct RedirectResponse cases, ten direct Response/JSONResponse cases, fourteen Response background-task cases, and four finite synchronous StreamingResponse cases, all passing on both target profiles where selected. The synchronous background-cancellation input passes exact source/package parity in the latest run; the background-task and header-view probes select the Python-package profile only. The async background-task cancellation case compares cancellation after callback start, propagated `CancelledError`, callback cancellation and finalization, and the response event tape against the pinned source. The finite async iterator, memoryview chunk, and custom async iterable cases pass on the Python package. The pre-ASGI-2.4 disconnect-cancellation input passes exact source/package comparison in run `d54f762e-aac1-461e-8a2d-59223eeb62ca`: the three emitted chunks, receive-disconnect ordering, generator cancellation and finalizer, and background completion match. Router inputs cover built-in converters, misses, route order, root paths, slash redirects, a package-only custom override, and one bounded parameterized Host-route port match. Reverse-URL inputs cover named Python route surfaces and `Request.url_for`, plus Rust-native direct Host path formatting and two flat Router `url_path_for` cases. Nested Host child-route lookup remains Python-package only; direct `Route.url_path_for`, nested Router graphs, and custom converters remain outside the native slice. Request inputs cover typed path parameters and CPython's integer-digit limit; Mount inputs cover child-scope extension, standalone and child misses, method mismatches, inherited path-parameter collisions, nested scope composition, and inner Mount misses. The HTTPException, registered-handler, server-error, and WebSocket slices remain bounded to their declared inputs. `Starlette.add_middleware` class/factory registration order, the late-add error, and one built-in/user middleware boundary workflow now have exact Python-package input comparisons; broader route/router/mount-local middleware combinations remain unselected. Broader TestClient HTTP/session coverage, other middleware combinations, and denial-response variants beyond the streamed 401 and multi-chunk 404 cases remain open. The 35 FileResponse response-behavior cases cover deterministic GET and HEAD, single and multipart ranges, If-Range matching, malformed and unsatisfiable inputs, suffix and single-byte ranges, ignored range elements, overlap merging, unsorted range insertion order, the range-count threshold and fallback, mutable chunk-size and max-range settings, Unicode filenames, header-view isolation across range responses, and post-construction path, status_code, and stat_result assignments. All 66 selected FileResponse source-to-target comparisons passed in the latest integrated run recorded above, including one Python-package-only FIFO scheduling probe that confirms event-loop progress while file opening blocks. Multipart comparison replaces only the live random boundary in Content-Type and MIME delimiter lines; file-part bytes, headers, event order, and chunk boundaries remain exact. The direct FileResponse `http.response.pathsend` case passes on both target profiles. The separate BaseHTTPMiddleware forwarding case passes on the Python package profile. The comparator validates each declared input basename and harness-specific temporary parent before normalizing that parent only, in ASGI events and the middleware execution trace. The Response, StreamingResponse, and FileResponse facades expose Rust-backed header views. The ten Headers/MutableHeaders cases cover selected construction, ordering, raw-input and view aliasing, copy and pair identities, and mutation behaviors. Raw-header rebinding order and broader response mutation sequences remain unproven. Input-only comparisons confirm that call-time path, status_code, and stat_result assignments reach Rust while constructor-selected metadata remains intact. FileResponse filesystem stat, open, read, seek, and close operations now cross an AnyIO worker-thread boundary; Python-package parity directly observes event-loop progress during a FIFO-blocked open. The general replacement goal remains incomplete; broad Starlette parity and the native benchmark boundary remain unproven. The Router/GZip benchmark lane is documented in [Benchmark mapping](BENCHMARKS.md).
