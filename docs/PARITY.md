# Migration parity contract and evidence

The active input contract is [`tests/fixtures/manifest.yaml`](../tests/fixtures/manifest.yaml), using `migration-parity/manifest@2` with `scope.mode: slice`. It contains 500 input-only cases in 54 indexed files, covering 72 operations and 530 parity requirements. The cases cover bounded Starlette application, routing and reverse URLs, including post-construction `Starlette.add_route`, route-level request-body limits, Router-generated 404 handling, Router behavior after live route mutations, flat Router reverse-URL selection, a parameterized Host-route port comparison, and direct Host reverse-URL formatting; async endpoint loop/task/thread ownership and request cancellation; URL scope and component construction/replacement; Headers and MutableHeaders; Request.form URL-encoded limits, multipart file metadata and duplicate values, charset decoding, parser limits, tempfile cleanup, and bare-app/Mount failures; responses and background tasks; StaticFiles; WebSockets; exceptions; status; endpoints; authentication; middleware including WSGIMiddleware, direct WSGI `build_environ`, its module-import deprecation warning, SessionMiddleware, and BaseHTTPMiddleware; configuration; schemas; and one Python-package Jinja2 template workflow. The manifest is the authority for exact operation and target-profile applicability. The current scope is bounded; it does not claim full Starlette API or behavioral parity.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source references and the source roots used by the API and compatibility inventories. The active manifest is separate: its `input_index` points to generated runtime JSON beneath `build/parity/inputs/`.

Parity and benchmark inputs are authored as JSON-compatible YAML under [`tests/fixtures/sources/parity/`](../tests/fixtures/sources/parity/) and [`tests/fixtures/sources/benchmark/`](../tests/fixtures/sources/). Run `make parity-inputs` or `python3.12 -m scripts.parity.generate_inputs` to serialize the indexed source definitions as JSON under `build/parity/inputs/{parity,benchmark}/`; `make contract-check` regenerates those files before offline contract validation. Generated inputs and parity/benchmark result JSON beneath `build/parity/` are ignored local build outputs, not checked-in fixtures or committed artifacts. Recreate them locally before running a parity or benchmark command.

The compatibility authority is Starlette 1.6.0 at commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The live source oracle checks the release, commit, source import path, source `uv.lock` digest, and CPython identity before it executes any case.

The latest integrated run, `a3baca57-a4bf-4304-98ad-21947b114005`, started at
`2026-09-30T10:58:24.458Z` and finished at `2026-09-30T11:00:13.611Z`. It
selected 652 profile comparisons: 648 passed, zero failed, zero infrastructure
errors, and four Rust-native Python-callable rows were `not_run`. The Python
package passed all 498 selected comparisons; Rust-native passed 150 of 154.
New Request.form inputs cover direct and mounted default/custom multipart
part-size limits with receive short-circuiting, duplicate text/file values,
2,000 text fields and 2,000 files under raised limits, tempfile cleanup after
stream and OSError failures, worker-thread rollover followed by cleanup, and
unique/mixed 1,001-file count failures through direct and mounted consumers.
The schema v10 input representation supports bounded literal, repeated, and
indexed repeated body segments; generated JSON remains ignored under
`build/parity/inputs/`. Manifest SHA-256: `99a50f34d1f79707d7d0a300b6ff9bdd3ad3168eb5e83be3ab37915408ed0922`. The installed
package source-tree SHA-256 is `785c7c716ff51360d0c8b3b39dd702bd76c70c23cf287fbc09709fd003c171c8`; its wheel artifact SHA-256 is
`51e3e208d992c43027867d789eb88d5ab0c0154b3bb6bf34c4196fab81527167`. `make parity-run` returns status 2 for the four unsupported
Rust-native callable boundaries. This is bounded local evidence, not full
parity or release proof.

## Input-only cases

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

### Async endpoint event-loop ownership and cancellation

[`asgi-call-boundary.yaml`](../tests/fixtures/sources/parity/asgi-call-boundary.yaml)
supplies an async ASGI endpoint and a `dispatch`, then `cancel-server-task`
schedule. The source and installed package observations match exactly: the
endpoint enters on the caller's event loop, request task, and thread; receives
`asyncio.CancelledError`; runs its finalizer; and propagates cancellation with
no response events. This is an asyncio-only package-profile probe of the
Python-callable boundary. It does not establish Trio behavior, cancellation of
synchronous worker functions, or every server's task ownership. The Rust-native
profile is not selected because this input intentionally invokes a Python ASGI
callable.

### Route-level request-body limits

[`route-body-limits.yaml`](../tests/fixtures/sources/parity/route-body-limits.yaml)
supplies three ASGI POST requests with application and route limits in the
input. One route inherits the application's five-byte cap, one route raises a
five-byte application cap to ten bytes, and one route lowers a ten-byte
application cap to five bytes. The source and installed package report the
same response status, headers, body bytes, and ASGI event order for each input.
The Rust-backed `Route.__init__` bridge receives `max_body_size` directly; the
Python facade contains no limit-selection logic. These cases prove only the
declared limit combinations; route limits through intervening middleware,
Mount/Router override composition, and route-level stream/error boundaries
remain in the fixture backlog.

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

### Response background tasks: bounded parity

[`background-tasks.yaml`](../tests/fixtures/sources/parity/background-tasks.yaml)
contains twelve package-profile cases with callback mode, arguments, failure,
callable shape, and task-list construction supplied by each input. They cover
async and sync functions, bound methods, callable objects, partials, nested
partials, sequential ordering, both task-list construction paths, and failure
propagation that prevents later callbacks from running. The response send
tape and background callback trace are observed from both pinned source and
installed package; no output values are encoded in the fixture. All twelve
cases pass exact source/package comparison. Rust owns callback classification,
task sequencing, and dispatch in the installed package; the Python adapter
supplies and observes user callbacks at the Python boundary. Task cancellation,
context variables, and concurrency behavior remain unproven.

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

[`asgi-http-get-text.yaml`](../tests/fixtures/sources/parity/asgi-http-get-text.yaml) contains JSON-compatible input values and observation selectors only. The generator serializes this authored definition to runtime JSON; no source definition stores expected status, headers, body, response messages, or lifecycle trace. Every case constructs one app with a public GET `/hello` route returning a `PlainTextResponse`; the endpoint makes two public `Response.set_cookie` calls. The successful case also declares an async-context lifespan callback and sends startup then shutdown.

The Python target runs the installed `starlette-rs-py` `Starlette` ASGI callable with a real Python scope, receive callback, and send callback. The Rust target constructs the exported `starlette_rs::Starlette` with an `ApplicationRoute` and calls its async `call` method with the scope's path/method projection and Rust future-based callbacks. It awaits response-start then response-body sends. The fixed endpoint does not read request input, so the Rust receive callback remains unused, matching the Python endpoint's behavior. The native API does not model every ASGI scope field, host an executor, or invoke Python endpoints.

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
propagated exception. In the partial-stream case, dispatch consumes `b"1"`,
`call_next` exposes the next chunk `b"2"` to the endpoint, then dispatch resumes
and consumes `b"3"`; the endpoint intentionally stops after `b"2"`. This
matches `tests/middleware/test_base.py:777-832`. The receive-transformation
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
disconnect behavior, background-task ordering, ASGI 2.4 `OSError` mapping, or
all memoryview formats.
The package-only `pre-asgi24-disconnect-cancellation` case is sourced from
`test_streaming_response_stops_if_receiving_http_disconnect`: it declares an
ASGI 2.3 scope, repeating binary chunk input with an event-loop checkpoint, and
a receive callback that waits for the input-defined 16-byte send threshold
before returning `http.disconnect`. Its execution trace observes the supplied
generator cancellation/finally markers and background recorder. It passed exact
source/package comparison in integrated run
`f4df4b18-8c74-46a4-9d33-96a0f684a9b6`; this bounded case does not establish
all streaming edge cases or a Rust-native async-streaming API.

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

[`static-files.yaml`](../tests/fixtures/sources/parity/static-files.yaml)
contains 22 input-defined `StaticFiles` ASGI-call cases,
[`static-files-lookup.yaml`](../tests/fixtures/sources/parity/static-files-lookup.yaml)
compares 15 direct `lookup_path` calls, including Unix and UNC-style absolute-path rejection,
parent traversal, a symlinked configured root, and internal and external file
and directory symlinks with both `follow_symlink` settings. The observations
include the resolved relative path and file metadata. A package-only case in
[`static-files-async-boundary.yaml`](../tests/fixtures/sources/parity/static-files-async-boundary.yaml)
gates the bound `lookup_path` override and observes the callback running on an
AnyIO worker while the event loop progresses. Eighteen ASGI-call cases apply
to both target profiles, with two package-only package-discovery cases and two
Rust-native explicit-root cases. The two path-limit cases exercise an
overlong first root with both `follow_symlink` settings and verify that its
404 preempts a later configured root containing the requested asset. Two more
cases remove search permission from an existing asset's root and compare the
401 exception with both symlink settings. Together
with the 15 lookup cases on each profile and the package-only async-boundary
case, they produce 71 profile comparisons: 35 Rust-native and 36 Python-package.
They cover rooted GET and HEAD,
HTML index redirects and 404 fallback, 401/404/405 outcomes, date and ETag
validators, validator precedence, package assets, absolute-path rejection,
file/directory metadata, path traversal and symlink containment, bound override
dispatch, the resulting ASGI response, and path-limit error precedence. Python
package discovery is exercised through `importlib` on the Python package
profile; Rust-native package cases pass explicit roots. All 71 selected
StaticFiles comparisons passed in the latest run, including all 30 direct
lookup comparisons. These cases do not
cover the full 36-function upstream StaticFiles suite. Known gaps include
constructor errors, permission conditions beyond root-search denial, subclass hooks beyond `lookup_path`, a
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

This slice covers HTTP exceptions raised by matched request-style endpoints before response start, one callable-ASGI endpoint that raises after sending a complete response, the two registered-handler cases described below, and the bounded server-error cases in the next section. The after-start HTTPException case compares the chained `RuntimeError`, its `HTTPException` cause, `suppress_context`, and the partial response event tape. Three application-level WebSocket exception workflows are covered in the WebSocket section; full `TestClient` propagation modes, arbitrary middleware ordering, and exception identity/chaining beyond the declared cases remain open.

[`asgi-callable-http-exceptions.yaml`](../tests/fixtures/sources/parity/asgi-callable-http-exceptions.yaml) adds two input-only callable-ASGI route cases. One raises `HTTPException(406)` before sending a response and observes Starlette's handled 406 response. The other sends an input-defined 200 response start and body, then raises `HTTPException(406)`; Starlette raises a `RuntimeError` chained from the HTTPException after the 200 events have already been sent. Both cases pass exact source-versus-installed-package comparison. The v4 result record captures the exception class, message, direct cause and public attributes, `suppress_context`, and partial ASGI observations. Rust-native is `not_run` for these Python-callable endpoints because it cannot invoke arbitrary ASGI callables.

## Registered exception-handler cases

[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml) adds two input-only `Starlette.__call__` cases, both selected for the Python-package profile. `starlette.applications.Starlette.__call__.exception-handler.status-code-precedence` registers the `HTTPException` class handler before the 405 status-code handler, then POSTs to a GET-only route. Starlette selects the exact status-code handler before the class handler, producing a distinct JSON response from the class handler's exception-detail response. The input declares handler keys and response recipes; it contains no expected response.

`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse` sends the request body in chunks. The endpoint reads `Request.body()` and raises the input-declared `BodyReuseException`, a subclass of `HTTPException`. Its async class handler reads `Request.body()` again and builds a JSON response from the decoded request bytes, exercising the cached body on the same Request. For this package boundary, `JSONResponse` uses Python JSON value serialization; Rust owns response framing, headers, and ASGI event delivery.

The earlier 51-case result selected 76 comparisons and had four Rust-native rows `not_run`. The latest integrated result is summarized above and includes these registered-handler cases; this slice does not establish full replacement parity.

## ServerErrorMiddleware application cases

[`asgi-server-errors.yaml`](../tests/fixtures/sources/parity/asgi-server-errors.yaml) adds nine input-only HTTP cases through `Starlette.__call__`, all selected for the Python-package profile. The cases cover the no-handler default 500 response, a registered integer 500 handler, a registered `Exception` handler, both insertion orders for the special 500 and `Exception` handler keys, text and HTML debug tracebacks that take precedence over a configured 500 handler, an unhandled `RuntimeError` after response start, and a handled `HTTPException(500)` that stays on the inner handled-exception path. They map to `starlette.asgi.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order`, `.debug-traceback`, `.response-started`, and `.handled-http-exception-500`.

The exact case IDs are `starlette.applications.Starlette.__call__.server-error.default-response`, `.status-500-handler`, `.exception-handler`, `.special-key-order.status-then-exception`, `.special-key-order.exception-then-status`, `.debug.plain-text-overrides-handler`, `.debug.html-selected-by-accept`, `.runtime-error-after-response-start`, and `.handled-http-exception-500`. All nine now pass source-versus-package comparison. The two debug cases use the declared traceback projection to omit only Python Starlette package frames and their source snippets, while retaining the user endpoint frame and exception summary. No native cases are selected for these Python-callable app workflows.

The operation declares the `starlette-debug-traceback` projection for response bytes, ASGI response events, and ordered headers. The comparator inspects each live response body and projects out traceback frames and source snippets from Python modules under the `starlette/` package, then normalizes remaining frame paths, line numbers, HTML frame IDs, and `Content-Length`. It retains user-code frames and the exception summary, and applies only to Starlette's actual debug-traceback structure. When no debug traceback is present, response bytes and headers retain their exact comparison. This decision comes from the observed body, not a case or requirement identifier. The source and target result records retain the raw traceback bodies. All other selected response fields remain exact, subject only to the separate declared `Allow` token normalization. The projection is parity infrastructure; it adds no behavior to the Python compatibility runtime.

This evidence is limited to these input-defined `Starlette.__call__` workflows. `asgi-core.app.test_app_debug` remains backlog because these inputs construct the app with `debug=True`; they do not set `debug` after app construction. Direct `ServerErrorMiddleware` call-boundary behavior, arbitrary middleware ordering, TestClient behavior, broader WebSocket behavior, and full replacement parity remain open.

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

Three package-profile cases in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml)
exercise WebSocket exception routing through the public `Starlette.__call__`
surface: the built-in `WebSocketException` close handler after acceptance, a
registered HTTP exception handler returning a denial response before
acceptance, and a synchronous custom exception handler that closes an accepted
connection. Their scope, connect event, route actions, handlers, and denial
extension are inputs; the captured WebSocket events and response bytes come
from the live source and target. These callback workflows select the
Python-package profile.

At the earlier WebSocket checkpoint, the three direct operations contained 15
cases and selected 21 comparisons: six protocol tapes for Python-package, six
projected state cases for each target, and three route cases for Python-package.
All 21 passed in run `480437e5-e1f4-4e25-91a5-1453ba82ea69`. The active
contract also includes the later convenience, close, and application-level
exception workflows; this does not establish TestClient WebSocket-session
parity.

[`gzip-middleware.yaml`](../tests/fixtures/sources/parity/gzip-middleware.yaml) contains eighteen direct ASGI middleware cases. The original eight cover negotiated final compression, identity negotiation, a small-body bypass, configured exclusion, streaming compression, path-send passthrough, an existing-encoding streaming bypass, and a partial-response streaming bypass. Ten source-backed additions cover all five pinned default-excluded content types, default SVG compression, all three content-type exclusion normalization triples, and per-chunk streaming with an intermediate empty chunk. Inputs omit constructor settings when the pinned tests use public defaults. Every source and target observation compares ordered ASGI events and raw response bytes without compression or event normalization. The Rust-native adapter drives `GzipConfig` and `GzipResponder`; the installed Python package exposes `starlette.middleware.gzip.GZipMiddleware`.

The Rust compressor uses `flate2`'s streaming gzip encoder and preserves zlib's sync-flush behavior across ASGI chunks. Compression decisions, exclusions, response-header edits, and stream state live in Rust. Python remains at the async boundary: it forwards ASGI callbacks and uses AnyIO's task-local capacity limiter and worker-thread facility for chunks at or above `thread_minimum_size`.

The legacy `__call__` profile selects exact response status, ordered repeated header bytes, body bytes, ASGI event order, complete ASGI events, and lifecycle/cleanup effects. The `request-dispatch` profile selects request observations, route-scope observations, response status, ordered repeated header bytes, ASGI event order, and complete ASGI events. Missing ASGI message fields remain missing in evidence. Repeated `Set-Cookie` headers must be produced by the two `Response.set_cookie` calls; adapters cannot inject output header values.

The `Response.asgi-call.set-cookie-attributes` input applies a fixture-defined sequence of public `Response.set_cookie` calls before ASGI dispatch. It covers optional attributes, a fixed HTTP-date expiry string, and omitted `Path` and `SameSite` values. The source, installed Python package, and Rust-native adapter construct their own headers from those same calls; the observation compares the complete ordered header bytes. Package-only cases also exercise timezone-aware `datetime` and integer-offset expiry conversion against a fixture-controlled clock, plus the CPython 3.12 `partitioned=True` error before ASGI dispatch.

The PyO3 boundary converts Python `datetime` expiry values with `email.utils.format_datetime(usegmt=True)` and integer expiry offsets with `http.cookies._getdate`, then passes only formatted strings to Rust. These inputs and their exact formatting follow the active interpreter's standard-library contract and clock, so reimplementing that conversion in Rust would duplicate Python-specific semantics. The boundary also reads `sys.version_info` for `partitioned=True`, because Starlette gates that option on the running Python version. These conversions and the version error are covered by the package-only inputs above; Rust owns cookie validation, attribute ordering, and header serialization.

The manifest includes one direct-ASGI GET `/hello` latency workload in [`inputs/benchmark/asgi-get-hello.yaml`](../tests/fixtures/sources/benchmark/asgi-get-hello.yaml). It selects the pinned source oracle and both target profiles, times only the dispatch step, and requires a fresh successful exact parity run first. The benchmark worker then resolves the same parity case from its indexed input, verifies the input and case digests, and runs a fresh source-versus-installed-package probe before collecting samples. Warm-up, measurement count, sample count, concurrency, and cache state come from the benchmark input.

For this smoke case, the worker constructs the app and starts its fixture lifespan before warmups, keeps the lifespan active across fresh HTTP scopes and ASGI message/callback containers for every dispatch, then shuts down after sampling. It requires ordered `lifespan.startup.complete` and `lifespan.shutdown.complete` events and compares the completed cleanup trace with the source probe, outside timed regions. Each measured call's HTTP events are also checked against the probe immediately after its timer stops.

The timer measures in-loop `await app(scope, receive, send)`. It includes fixture-to-ASGI scope/message materialization, callback creation, and response collection; it excludes app construction, lifespan startup/shutdown, and event comparison. The pinned upstream routing runner enters the event loop with `loop.run_until_complete` for each dispatch, while this timer excludes per-dispatch loop-entry overhead. These numbers therefore do not reproduce upstream timings and are neither Rust-kernel-only measurements nor real-server throughput. The result is written as strict `benchmark-result@1` at `build/parity/benchmark-result.json` when the command runs. Rust-native remains `not_run` because its measured boundary is not equivalent. This is a one-case smoke benchmark, not a representative Router/GZip result. The separate `benchmark-upstream` runner now measures all 74 pinned Router/GZip workloads against source and the installed package; Rust-native remains `not_run` at those non-equivalent boundaries. See [Benchmark mapping](BENCHMARKS.md).

## SessionMiddleware input slice

[`session-middleware.yaml`](../tests/fixtures/sources/parity/session-middleware.yaml) adds eight input-only workflows for the installed Python-package profile. The inputs cover a signed-cookie write/read/clear round trip, a malformed signature fallback, the pinned negative `max_age` expiry case, custom name/path/SameSite/Domain/Secure attributes with `max_age=None`, direct `Session` mutation flag behavior for set, delete, clear, pop, setdefault, and update, signed-cookie loading into a WebSocket scope, lifespan pass-through, and the documented `Secret` key wrapper's redacted representation, string conversion, truthiness, and signing use. A later request receives the earlier response's live `Set-Cookie` value through the `previous-set-cookie` source selector; no cookie value or output is authored in the fixture. These workflows map to the pinned session tests, the source branches for WebSocket and lifespan scopes, and the configuration and middleware documentation; they remain a bounded SessionMiddleware slice rather than full Starlette parity.

Rust owns cookie signing and verification, expiry and clearing decisions, response header behavior, the documented `Secret` representation and truth behavior, and session mutation state. The PyO3 value-conversion boundary calls Python's standard-library `json.dumps` and `json.loads` from the Rust session core to preserve the source's Python JSON byte representation before signing and after verification. The SessionMiddleware input workflows compare those boundaries against the pinned source. The WebSocket case observes the loaded scope session through the public `WebSocket` wrapper while leaving Session access and modification flags false. The lifespan case drives startup/shutdown completion messages from fixture input and compares exact event order. This codec dependency remains a documented Python compatibility boundary. The public status of the upstream `SessionMiddleware.signer` attribute remains unresolved and is tracked as an API candidate in the compatibility inventory.

## Exact comparison and allowed normalization

Comparison is exact for all selected fields except the narrow `allow-methods-as-set` normalization declared on `ordered_repeated_headers` and `asgi_events`, the declared `starlette-debug-traceback` normalization, and the FileResponse `multipart-range-boundary` and `file-response-temp-path` normalizations. The Allow normalization applies only to comma-separated tokens in an `Allow` header value: the comparator trims surrounding whitespace, sorts unique method tokens, and compares the normalized value. The traceback normalization activates only when live observations contain an actual Starlette debug traceback; it removes frames and source snippets from modules under the `starlette/` package, normalizes remaining frame paths, line numbers and HTML frame IDs, and normalizes the body-length header. It retains user-code frames and the exception summary. The multipart normalization activates only when the live FileResponse `Content-Type` is `multipart/byteranges` with Starlette's 26-character lowercase hexadecimal boundary. It replaces that token in the header and MIME delimiter lines in body bytes while preserving their lengths; file-part bytes, metadata, other headers, event ordering, and chunk boundaries remain exact. The `file-response-temp-path` normalization applies to FileResponse `http.response.pathsend` events and the BaseHTTPMiddleware forwarding case. It requires an absolute emitted path whose basename matches the input file and whose parent matches the source or target harness temporary-directory pattern, then replaces only that varying parent with a stable marker. For direct FileResponse calls it applies to `asgi_events`; for BaseHTTPMiddleware it also applies to the matching `execution_trace` message. These dynamic values are derived from live observations, never from case identifiers. Unrelated BaseHTTP cases remain unchanged, and result records retain the original unnormalized events, headers, and raw response bodies.

The request-scope mutations are covered by the three original HTTP `request-dispatch` cases and the new typed path-parameter cases. Mounted routes and non-empty `root_path` have bounded dispatch observations, including child 404/405 and inherited parameter collisions; nested Mount composition and other application paths remain outside this slice. The successful `__call__` workflow schedules lifespan startup, HTTP dispatch, and lifespan shutdown on the same app task; it verifies that the lifespan context stays active across that in-flight dispatch and exits afterward. The new lifecycle-only cases cover sync/async generator entry and cleanup, startup/shutdown failures, synchronous callback-call failures, and type-based special-method lookup. Other lifespan state, cancellation, and concurrency behaviors remain outside this slice. The Rust-native `Starlette::call` is an additive, bounded response dispatcher over a path/method projection, not a full ASGI application object. The Rust request adapter's routed-scope model is likewise not a public Rust `Request`.

## Isolated environments and adapter protocol

Run `prepare-env` before either oracle-only or full parity evidence. It builds the target wheel from this checkout, creates separate CPython 3.12 virtual environments for the pinned Starlette source oracle and installed `starlette-rs-py` wheel, and installs isolated dependencies from hash-pinned locks: the source oracle uses `scripts/parity/locks/starlette-oracle-cpython312.txt` (including ItsDangerous for the pinned session middleware), while the installed package uses `scripts/parity/locks/asgi-runtime-cpython312.txt` and its PyYAML schema dependency. The generated environment lock records the repository-relative interpreter paths, runtime, platform, dependency-lock digest, installed-package freeze digest, environment digest, and target wheel digest. The runner rechecks those identities and does not fall back to a global Python interpreter. Python adapters receive `STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256` for their own environment; the native adapter receives the SHA-256 of `Cargo.lock`.

Each adapter runs in a fresh process. The runner sends one strict JSON `migration-parity/adapter-request@1` object on stdin and accepts exactly one JSON response object on stdout. The response envelope remains `migration-parity/adapter-response@1`; its opaque workflow payload follows the versioned parity-input and parity-result contracts. Diagnostics go to stderr. Identity responses are checked against the source revision or installed target environment before workflows run. The result schema is `migration-parity/parity-result@4`, which retains oracle revision/module/lock provenance, target revision/tree/lock/package identity, and per-side environment fingerprints. The prepared Python environment digest includes a fixed process policy: `PYTHONHASHSEED=0`, with `PYTHONOPTIMIZE` and `PYTHONWARNINGS` removed. Unknown fields, duplicate JSON keys, malformed output, absent interpreters/adapters, crashes, timeouts, identity mismatches, missing or extra observations, skipped evidence, and unsupported evidence cannot pass.

[`url-scope.yaml`](../tests/fixtures/sources/parity/url-scope.yaml) adds 20 input-only `URL(scope=...)` cases mapped to the pinned ordinary construction, invalid Host fallback, and authority-in-path tests, plus a source-backed empty-server-host serialization edge. Each adapter constructs a public URL from the supplied scope and reports its live string, repr, and URL components; inputs contain no expected URL values. The Rust-backed Python facade keeps the constructor behavior in Rust. All 20 cases passed in the latest integrated run.

[`url-components.yaml`](../tests/fixtures/sources/parity/url-components.yaml) adds 14 URL component access and ordered `replace(**components)` workflows. [`datastructures-headers.yaml`](../tests/fixtures/sources/parity/datastructures-headers.yaml) adds ten `Headers` and `MutableHeaders` construction and consumer workflows, including duplicate order, scope/raw-list aliasing, mutable-copy pair identity and independence, no-op mutation identity, and ordered mutation. [`responses-basic.yaml`](../tests/fixtures/sources/parity/responses-basic.yaml) observes the cached `Response.headers` object and its raw-list alias, while [`file-response.yaml`](../tests/fixtures/sources/parity/file-response.yaml) observes base header-view isolation across single and multiple range calls. These new package-only cases passed exact source/package comparison in the latest integrated run. The Python facades forward these operations to Rust; the public Python consumer interfaces remain the compatibility contract.

The `parity-input@10` cases for callable-ASGI `HTTPException` behavior drive an ordered action sequence from fixture data. If the app raises after response events have been sent, the adapter marks that workflow step `error`, preserves the chained exception and `suppress_context` flag, and records the partial ASGI observations in `partial_value`. This keeps captured application behavior comparable while adapter crashes and malformed evidence remain infrastructure failures.

`oracle-only` invokes only the pinned source workflows. It writes a comparison row per target profile with target workflow status `skipped`, a reason, and outcome `not_run`. A full `run` attempts every target-profile comparison declared for the 500 indexed cases and fails closed when a target identity or workflow is unavailable. The latest run selected 652 comparisons; its four Rust-native callable boundaries are recorded as `not_run` in the parity evidence section above. `pass` requires completed oracle and target workflows plus exact equality after the declared normalizations. Generated results are local ignored artifacts and are not checked in.

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

The parity lifecycle step covers one successful async-context enter/exit separately from its HTTP dispatch. The Request-style synchronous endpoint inputs cover functions, bound methods, and `functools.partial`; a separate callable-instance case covers ASGI dispatch through `(scope, receive, send)`. The latest integrated run includes six slash-redirect cases, four direct RedirectResponse cases, ten direct Response/JSONResponse cases, twelve Response background-task cases, and four finite synchronous StreamingResponse cases, all passing on both target profiles where selected; the background-task and header-view probes select the Python-package profile only. The finite async iterator, memoryview chunk, and custom async iterable cases pass on the Python package. The pre-ASGI-2.4 disconnect-cancellation input passes exact source/package comparison in run `f4df4b18-8c74-46a4-9d33-96a0f684a9b6`: the three emitted chunks, receive-disconnect ordering, generator cancellation and finalizer, and background completion match. Router inputs cover built-in converters, misses, route order, root paths, slash redirects, a package-only custom override, and one bounded parameterized Host-route port match. Reverse-URL inputs cover named Python route surfaces and `Request.url_for`, plus Rust-native direct Host path formatting and two flat Router `url_path_for` cases. Nested Host child-route lookup remains Python-package only; direct `Route.url_path_for`, nested Router graphs, and custom converters remain outside the native slice. Request inputs cover typed path parameters and CPython's integer-digit limit; Mount inputs cover child-scope extension, standalone and child misses, method mismatches, inherited path-parameter collisions, nested scope composition, and inner Mount misses. The HTTPException, registered-handler, server-error, and WebSocket slices remain bounded to their declared inputs. Route/router/mount-local middleware is present in the Python compatibility layer but has not yet been selected by input cases, so its parity remains unproven. TestClient request/response construction and WebSocket sessions, broader denial-response variants, direct `ServerErrorMiddleware` invocation, and arbitrary middleware ordering remain open. The 30 FileResponse cases cover deterministic GET and HEAD, single and multipart ranges, If-Range matching, malformed and unsatisfiable inputs, suffix and single-byte ranges, ignored range elements, overlap merging, the range-count threshold and fallback, mutable chunk-size and max-range settings, Unicode filenames, and header-view isolation across range responses. All 58 source-to-target comparisons passed in the latest integrated run recorded above. Multipart comparison replaces only the live random boundary in Content-Type and MIME delimiter lines; file-part bytes, headers, event order, and chunk boundaries remain exact. The direct FileResponse `http.response.pathsend` case passes on both target profiles. The separate BaseHTTPMiddleware forwarding case passes on the Python package profile. The comparator validates each declared input basename and harness-specific temporary parent before normalizing that parent only, in ASGI events and the middleware execution trace. The Response, StreamingResponse, and FileResponse facades expose Rust-backed header views. The ten Headers/MutableHeaders cases cover selected construction, ordering, raw-input and view aliasing, copy and pair identities, and mutation behaviors. Raw-header rebinding order and broader response mutation sequences remain unproven. Changing FileResponse public `path`, `status_code`, or `stat_result` after construction does not update the Rust snapshot. Rust currently performs filesystem stat and reads synchronously on the ASGI caller; nonblocking filesystem scheduling remains unproven. The general replacement goal remains incomplete; broad Starlette parity and the native benchmark boundary remain unproven. The Router/GZip benchmark lane is documented in [Benchmark mapping](BENCHMARKS.md).
