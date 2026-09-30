# Compatibility inventory

**Atlas state: source-mapping milestone complete; full Starlette replacement remains active and incomplete.** The source authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The inventory deliberately keeps
source candidates separate from the reviewed compatibility surface; an
importable name alone does not establish public status. The atlas is a source
review and fixture crosswalk, while the active parity contract measures a
separate bounded implementation slice.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source
references and the public source, documentation, and test roots used by
inventory generation. The separate [`parity manifest`](../tests/fixtures/manifest.yaml)
indexes behavioral requirements and generated input paths. Authored parity and
benchmark definitions live as JSON-compatible YAML under
`tests/fixtures/sources/{parity,benchmark}/`; `make parity-inputs` generates
runtime JSON under ignored `build/parity/inputs/`. Result JSON under
`build/parity/` is also local, ignored output. These build artifacts are not
checked in; the run IDs and counts below describe their recorded executions.

The active parity manifest indexes 444 input-only cases across 49 files,
covering 67 operations and 503 parity requirements. The authored cases span
the Starlette ASGI application, routing and reverse URLs, URL scope/components,
Headers and MutableHeaders, requests, responses and background tasks,
StaticFiles, WebSockets, exceptions, status constants, endpoints,
authentication, middleware (including bounded SessionMiddleware and
BaseHTTPMiddleware workflows), configuration,
schemas, and one bounded Python-package Jinja2 template workflow. The exact
operation and profile denominator is in the parity manifest; generated JSON
and run results remain ignored local build outputs.

Latest live parity run `c1dddd42-fa0c-4a64-b07b-31f9d46b79e0` ran against the
pinned Starlette 1.6.0 source on CPython 3.12.13. It selected 592 comparisons:
588 passed, zero failed, zero infrastructure errors, and four Rust-native
comparisons were `not_run`. The installed Python package passed all 442 of its
selected comparisons. Rust-native passed 146 of 150; the four unsupported
inputs exercise sync request-dispatch callable forms. The new `Starlette.add_route`
input confirms post-construction registration and matching GET/405 dispatch
observations. Multipart inputs compare the text-limit short circuit, file
write/seek ordering across request chunks, cleanup after receive-callback and
`UploadFile.write` errors, and rollover of a file larger than 1 MiB in a worker
thread. The all-target command still exits 2 for those four unsupported
Rust-native cases; this bounded run is not full Starlette parity.

The latest correctness-gated Router/GZip benchmark run,
`07eb140d-a8d2-4964-9e33-2a408f4a171e`, measured 74 of 74 source/package
workloads with zero failed or skipped workloads after a passing 428/428
Python-package preflight. Rust-native remains separately `not_run` for all 74
workload boundaries. This is benchmark evidence for that lane only; the full
compatibility denominator remains incomplete. The latest source inventory
check dispositioned all 999 API candidate rows and reported 796 coverage
mappings and 556 new fixture-backlog items; those changing counts come from
the generated atlas, not this policy text.

Historical integrated run `af914b8c-5933-4ced-9e1d-c60b23263e1a` started at
`2026-09-29T23:48:10.322Z` and finished at `2026-09-29T23:49:31.637Z`. It
selected 556 profile comparisons: 552 passed, zero failed, zero infrastructure
errors, and four Rust-native comparisons were `not_run`. The Python package
passed all 406 selected comparisons; Rust-native passed 146 of 150, with four
Request-dispatch rows requiring Python callables marked `not_run`. The Router
live-mutation sequence passed all three observations: route-cache warmup,
adding `POST` to an existing route, and appending a new route. Twelve
input-defined BackgroundTask/BackgroundTasks cases pass on the Python package;
they cover async and sync functions, bound methods, callable objects, partials,
nested partials, worker-thread execution, sequential order, both task-list
construction paths, and fail-fast exception propagation. The run
includes the 20 URL scope, 14 URL component, ten Headers/MutableHeaders, and
one Jinja2 template case; all passed on the Python package. Six new package-
only header probes observe raw-list aliasing and pair identity, the cached
`Response.headers` view, and base-header isolation during single and multiple
FileResponse range responses; all six passed exact source/package comparison.
The template case
matches escaped HTML, processor merge, `url_for`, response metadata, and the
ASGI debug event. All 30 FileResponse cases passed on
both profiles,
all eight SessionMiddleware cases passed on the Python package profile, and all
twenty-one BaseHTTPMiddleware cases passed there. Those cases cover header
mutation, replacement responses, body-cache replay, response-completion receive
racing, exception/context propagation (including cause, TaskGroup
`ExceptionGroup` context, and suppression-state observations), partial-stream
forwarding, caught downstream exception handling, downstream receive
transformation, repeated disconnect polling, dispatch stream consumption
followed by a downstream body read, dispatch body buffering followed by a
downstream stream read, dispatch stream reads after downstream stream/body
consumption, cached-stream replay after the downstream body read, a downstream body read
after dispatch caches the request body, and a downstream stream read after
dispatch exhausts `request.stream()`, plus request-disconnect checks with and
without a cached body. The
`test_downstream_middleware_modifies_receive`
wrapper case maps to `tests/middleware/test_base.py:979-1017`: dispatch
observes `b"foo "`, the downstream wrapper doubles the body, and the endpoint
observes `b"foo foo "` with the exact empty-200 response events. The repeated-
disconnect workflow maps to `tests/middleware/test_base.py:1168-1215`; its two
inputs poll downstream receive twice and compare raw/downstream receive traces,
drained request events, poll results, and the exact `200 b"good!"` response
tape. The stream-consumption workflow maps to
`test_read_request_body_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:660-686`: dispatch exhausts `request.stream()`
over `b"a"`, the terminal empty chunk, and `StopAsyncIteration`; downstream
then reads the cached empty body and returns `Homepage`. The body-cache/stream-
replay workflow maps to
`test_read_request_stream_in_app_after_middleware_calls_body` at
`tests/middleware/test_base.py:631-657`: dispatch reads `b"a"` with `body()`,
then downstream `stream()` yields `b"a"` and `b""` before returning
`Homepage`. The source test offers asyncio and trio client backends; this input
uses the Python-package profile only and does not establish parity on both
backends. The two post-call-next cases map to
`test_read_request_stream_in_dispatch_after_app_calls_stream` and
`test_read_request_stream_in_dispatch_after_app_calls_body` at
`tests/middleware/test_base.py:715-773`. They capture the actual dispatch stream
read result after the endpoint consumes the stream or body; the input stores no
expected exception. Source and installed package report matching exception
class and message, response status, body, and ASGI events. This profile also
exercises asyncio only. The downstream-stream-after-consumption case maps to
`test_read_request_stream_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:599-628`: dispatch exhausts `b"a"`, the
terminal empty chunk, and the iterator; the endpoint then observes only
the cached empty stream chunk. Stream observations, response, and ASGI
events match the source exactly.
The dispatch/downstream body-cache case maps to
`test_read_request_body_in_app_after_middleware_calls_body` at
`tests/middleware/test_base.py:689-712`: the adapters report `b"a"` for
both dispatch and endpoint body reads, and the endpoint returns those
bytes. The source and package match exactly. The new replay case maps to
`test_read_request_stream_in_dispatch_after_app_calls_body_with_middleware_calling_body_before_call_next`
at `tests/middleware/test_base.py:835-862`: dispatch buffers `b"a"`, the
endpoint reads the cached body, and dispatch's stream yields `b"a"`, the empty
terminal chunk, and exhaustion. Those observations, the response, and ASGI
events match the source exactly. The two disconnect cases map to
`tests/middleware/test_base.py:894-976`: one observes downstream receiving
`http.disconnect` before dispatch checks `Request.is_disconnected()`; the other
observes dispatch caching `b"hi"`, polling the following disconnect, then
downstream receiving the cached body and disconnect. Both return `True` from
the live request check and match the source exactly. The pathsend workflow maps
to `tests/middleware/test_base.py:1219-1259`, forwarding FileResponse events
through BaseHTTPMiddleware without calling the receive callback. The catch case covers
`test_exception_can_be_caught` at
`tests/middleware/test_base.py:338-356`: dispatch catches `ValueError("TEST")`
from `call_next` and returns status 400 with body `TEST`. The Rust-native target
was clean at revision
`7ab9f0cee22b03035b96c2c2df5c66cc6a1d28c8+source-fnv1a64-3f737351c1674203`;
the installed Python-package target was dirty with tree SHA-256
`99fd7a11cb20c8a9bda279f5807b621c4dd3a08f86dca79503bb135319edc492`.
Manifest SHA-256:
`44e45ddbf67daa09a23ce54a3f0d43e83b8b77e00fa704ceac904374c2661766`.
Parity wheel artifact SHA-256:
`4a1736486aed60dc5a4e1894c076f919617080548874f4f79d385f72d9e88a00`.
The four unsupported Rust-native Python-callable rows keep the overall gate
incomplete; this run is not full parity or release proof.
Thirty-eight StaticFiles cases are authored across
three inputs. Fifteen `lookup_path` cases run on both profiles and all 30
comparisons pass; all 71 StaticFiles profile comparisons pass (35 Rust-native
and 36 Python-package). The package-only async-boundary case checks bound
`lookup_path` override dispatch on an AnyIO worker, event-loop progress while
the callback blocks, and the resulting ASGI response. Other StaticFiles cases
cover rooted GET and HEAD, HTML index redirects and fallback, 401/404/405
outcomes, missing-subdirectory and file-as-directory 404 paths, date and ETag
validators, validator precedence, package assets, NUL-path 404 handling, and
direct `lookup_path` metadata/path checks. Python package discovery is tested on
the Python profile; Rust-native package serving uses explicit roots. The
Rust-native target tree was clean; the installed Python-package target tree was
dirty. Its wheel SHA-256 is
`71f943856c333550a10257d0a9b4dbe6530e399d472dbb52207d1e300a16cd9a`.
`make parity-run` exits with status 2 only for the four explicitly unsupported
Rust-native Python-callable rows; this is not release proof.

The two registered-handler inputs in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml)
exercise status-code precedence over an `HTTPException` class handler and an
async class handler that reads the request body already cached by the endpoint.
Their case IDs are
`starlette.applications.Starlette.__call__.exception-handler.status-code-precedence`
and
`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse`.
The remaining HTTPException evidence covers five matched HTTP request-style
endpoint exceptions before response start and two callable-ASGI endpoint cases,
including one exception after a complete 200 response; only the explicit-detail
406 case is supported by the Rust-native response builder. The nine server-error
inputs cover the default response, registered 500 and `Exception` handlers,
special-key order, debug text/HTML responses, response-start handling, and a
handled `HTTPException(500)` through the installed package. All selected
server-error cases pass in the latest run under the declared traceback
normalization; raw source and target bodies remain in the local result
artifact. The WebSocket inputs also include six ordered receive/send callback-
tape comparisons on the Python package, six projected state cases on both
targets, three package-profile route-dispatch cases, and the 16
convenience/close cases described above. Three additional package-profile
cases cover the built-in `WebSocketException` close path, an `HTTPException`
denial response, and a registered synchronous WebSocket close handler. These
map to the pinned `test_websocket_raise_*` workflows. Direct
`ServerErrorMiddleware` invocation, arbitrary middleware ordering, and
TestClient propagation remain outside the active contract.
`asgi-core.app.test_app_debug` stays in backlog because its input constructs
the app with debug enabled rather than setting debug after construction. The
parity artifact status for that historical run was `completed`; the four
explicitly unsupported Rust-native callable rows kept its all-target gate
incomplete. The current Router/GZip source/package benchmark lane is
`completed` for all 74 declared workloads, but does not establish full
Starlette replacement parity; Rust-native remains outside those benchmark
boundaries. Ignored local results live in
`build/parity/parity-result.json` and
`build/parity/upstream-benchmark-result.json`.
These results cover the selected workflows only and do not establish full
compatibility.

## StaticFiles runtime boundary

The public `starlette.staticfiles.StaticFiles` facade now delegates path
normalization, root containment, symlink policy, file lookup, HTTP method
selection, HTML index and fallback selection, redirects, and conditional 304
selection to the Rust core. The Python module only converts constructor inputs,
forwards public helper calls, and awaits the native ASGI response.

Package assets require Python's import discovery rules. The PyO3 boundary calls
`importlib.util.find_spec` to resolve each requested package and keeps the
resulting static directory in the Rust root list; this preserves custom Python
importers and package origins that filesystem-only Rust discovery cannot
observe. The input-only `package-static-assets` cases create isolated package
roots. The Python package profile exercises both the default `statics`
directory and an explicit subdirectory through Python import discovery.
Rust-native cases exercise the corresponding trees through explicit roots; they
do not claim Python package discovery. This boundary uses no upstream
Starlette runtime import or added runtime dependency.

The 38 authored StaticFiles cases are a correctness slice, not complete
coverage of its 36 upstream test functions. A package-only async-boundary case
checks that a bound `lookup_path` override runs on an AnyIO worker while the
event loop advances, then compares the ASGI response. Fourteen `lookup_path`
cases run on both profiles; all 28 comparisons pass. Two inputs establish that
an overlong first configured root produces the source-compatible 404 before a
later root can serve a matching asset, with both symlink settings. Two more
deny search permission on a configured root and match the 401 error under both
symlink settings. Remaining gaps include Windows path normalization and
semantics, `check_config` scheduling, constructor errors, remaining validators
and subclass hooks, and the rest of the upstream StaticFiles tests. Direct
`lookup_path` cases compare resolved paths,
file types, size, and modification time against the source oracle; they do not
establish complete StaticFiles parity.

## SessionMiddleware slice and boundary

The active contract adds eight input-only SessionMiddleware workflows for the
`python-package-cpython312` profile. They compare signed-cookie persistence and
replay, invalid-signature fallback, `max_age` expiry/default/`None` settings,
cookie name/path/SameSite/Domain/Secure attributes, access and modification
flags for direct `Session` mutations, `Vary: Cookie` behavior, clearing,
WebSocket cookie loading, lifespan pass-through, and the public `Secret` key
wrapper's redacted representation, string conversion, truth value, and signing
use. The inputs replay the earlier live `Set-Cookie` value dynamically and
contain no expected outputs. This is a bounded slice sourced from the pinned session tests
and `docs/middleware.md`; it does not establish full SessionMiddleware or
Starlette parity.

Rust owns session signing and verification, expiration, cookie response
behavior, documented `Secret` representation and truth behavior, and the
`Session` mutation state. The Rust/PyO3 value boundary calls
Python's standard-library `json.dumps` and `json.loads` to preserve the Python
JSON byte representation used by the pinned implementation. The authored
SessionMiddleware workflows compare those calls through the live source oracle.
The codec remains a Python-specific compatibility boundary. The public status
of `SessionMiddleware.signer` is unresolved: upstream assigns this attribute,
but the compatibility inventory has not established it as supported public API.
The installed facade does not expose ItsDangerous' signer object; ItsDangerous
remains in the isolated source-oracle environment only.

## Current denominators

Root `metadata.yaml` selects the pinned public Starlette source files and the
documentation and test roots. The inventory generator uses that metadata and
parses the pinned source with Python's AST, recording signatures/defaults
without importing Starlette. These source and atlas
counts describe the pinned revision and checked-in atlas matrix, not the number
of active parity cases:

| Surface | Count | Meaning |
| --- | ---: | --- |
| Python files under `starlette/` | 35 | Includes package initializers and two private helper modules |
| Import-path candidates | 33 | 31 non-private leaf modules plus `starlette` and `starlette.middleware`; candidate paths are inventory aids, and a module's importability alone does not establish its public contract |
| Public-name source candidates | 237 | 93 classes, 16 functions, and 128 assignments including the explicit root `__version__` export |
| Public-named class methods | 239 | Methods whose names do not begin with `_` |
| Constructor rows | 66 | `__init__` signatures |
| Special-method rows | 102 | Dunder method signatures |
| Candidate source rows | 476 | Definitions and public-named methods; constructor/special rows are separate |
| Source re-export candidates | 230 | Local Starlette imports that may or may not be intentional public aliases |
| Documented import references | 122 | Deduplicated by import path and docs page |
| User-facing documentation pages in navigation | 24 | 20 feature pages, Introduction, Release Notes, and two Community pages |
| Explicit API expansion directives | 3 | `Starlette`, `TestClient`, and `Jinja2Templates` |
| Upstream test-tree Python files | 34 | Includes 30 `test_*.py` modules and four shared/support modules |
| Upstream test functions and methods | 514 | AST-discovered and mapped test functions in the 30 `test_*.py` modules |
| Upstream lock records | 86 | One editable Starlette record plus 85 external packages across runtime, optional, dev, and docs groups |

The candidate rows, source line numbers, signatures, defaults, constructors,
special methods, candidate re-exports, and documentary evidence are in
[`api-surface.csv`](api-surface.csv). The merged
[`API review`](atlas/api-review.csv) dispositions each of its 999 rows with
evidence: 514 `supported`, 286 `private/internal`, and 199 `uncertain`. The
catalog's original `audit_status` field records inventory provenance; use the
merged disposition and rationale for the compatibility classification. The
root package defines only `__version__ = "1.6.0"`; it has no convenience
re-exports or `__all__`.

## Completed atlas coverage

The [`coverage matrix`](atlas/coverage-matrix.csv) contains 796 mappings:

| Mapping | Count |
| --- | ---: |
| Upstream test functions and methods | 514 source functions represented by 537 behavior mappings |
| Documentation navigation pages | 24 |
| Shared test support modules | 4, with 14 downstream-use mappings |
| All source mappings | 796 |
| Existing input mappings in the atlas matrix | 190 |
| Reasoned `not_applicable` mappings | 50 |
| New input-only fixture backlog | 556 |

The [`fixture backlog`](atlas/fixture-backlog.csv) contains no expected
outputs. Every backlog mapping has an input stimulus and observation selectors;
every `not_applicable` mapping has a concrete reason. In this checked-in
crosswalk snapshot, 190 `existing` mappings point to authored YAML input
definitions; runtime JSON is generated separately under `build/parity/inputs/`.
The earlier checked-in fixture crosswalk snapshot separately indexed 19 parity
input files with 136 cases. The active manifest now contains 49 indexed files
and 444 cases, including post-construction `Starlette.add_route` coverage,
twelve Response background-task workflows, six
header-view and raw-pair probes, and a Router sequence that verifies live
route-method and route-list mutations across
dispatches, twenty URL scope-construction cases,
twenty-one BaseHTTPMiddleware cases, one Jinja2 template case, and 30 FileResponse
cases, 38 authored StaticFiles cases, four authentication cases,
three configuration cases, four schema cases, and
15 lifecycle cases in
[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
and [`schemas-runtime.yaml`](../tests/fixtures/sources/parity/schemas-runtime.yaml).
The `starlette.websockets.WebSocket.protocol-sequence`
operation contains six cases whose Python-package observations preserve the
ordered receive/send ASGI callback tape, including attempted sends whose
callback raises. The `starlette.websockets.WebSocket.state-sequence` operation repeats
those six input sequences and compares action outcomes, exact error messages,
and both final state enums on source, package, and Rust-native profiles; it
does not compare payloads or Python exception metadata. The new
`starlette.websockets.WebSocket.convenience-sequence` operation compares typed
frames, action results and disconnect details, normal async-for iterator
output, async-generator API availability/control calls, denial-response
extension behavior, and final states. The separate
`starlette.websockets.WebSocketClose.call-sequence` operation observes
construction defaults, mutable properties, and its ASGI close event. These
inputs all pass in the latest integrated Python-package run, and the six
projected state cases also pass in Rust-native. The route operation is
`starlette.routing.WebSocketRoute.route-dispatch`; its cases are
`matched-root-path`, `router-miss-close`, and `http-scope-404`; all three passed
in the Python-package profile. The
status-handler case checks that a 405 status key takes precedence over a
registered `HTTPException` class key during route dispatch. The class-handler
case raises a handled subclass after the endpoint reads the body; its async
handler reads that cached body through the same request. Both are in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml).
Their case IDs are
`starlette.applications.Starlette.__call__.exception-handler.status-code-precedence`
and
`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse`.
The five upstream HTTPException tests and
the HTTPException documentation contract map to the two exception input files;
`test_handled_exc_after_response` has a declared partial observation of its
after-start behavior, while its `TestClient(raise_server_exceptions=False)`
branch remains outside this slice. The remaining backlog rows are atlas mapping
status, not proof that those behaviors are absent from active inputs or
untested.
The merger validates the pinned upstream commit, all 999 API rows, evidence
paths, test identities, support modules, docs navigation paths, and
input-only fixture files.

## Multipart Request.form and UploadFile slice

The input-only cases in
[`request-form-multipart.yaml`](../tests/fixtures/sources/parity/request-form-multipart.yaml)
compare small, well-formed multipart bodies split across ASGI request
chunks. The baseline mixed-files-and-data case contains text fields around one
`file.txt` upload; its consumer observations cover FormData ordering and
lookups, UploadFile metadata, partial and full reads, append/write/readback,
seek, and explicit FormData.close. The cases map to this documented parser
scenario and UploadFile attributes and async methods. They do not claim broad
multipart parity.

Multipart boundaries, disposition parsing, and part values are selected in
Rust through the locked `multer` parser. Python holds the standard
`SpooledTemporaryFile` object exposed by the public UploadFile API and performs
the required PyO3 conversions and awaits the native UploadFile methods. The
request state machine feeds chunks to a Rust-owned `MultipartFormParser` and
processes its ordered file-start, file-data, and file-finished events. It does
not retain a complete file part in a Rust byte vector. The bridge creates the
standard spooled file when Rust signals `FileStarted`; the state machine awaits
`UploadFile.write` for
each file-data event before requesting another ASGI body chunk, writes all
files from a request chunk before seeking completed files, and selects cleanup
on errors.

The oversized-text input puts the limit violation in the first request chunk
and supplies a later sentinel chunk; source and package agree on the parser
error and one `receive` call. The file-streaming input splits one file across
two receives and puts a second file in the latter receive. Its observed trace
matches Starlette: the first write occurs before the second receive, both
writes from the latter chunk precede both seeks, and FormData closes both
spooled files. A separate input makes the next receive callback raise after
file bytes have been written; both implementations close the spooled file and
propagate the same `RuntimeError`. The large-file input streams an
input-defined 1 MiB-plus payload, checks its size and write-chunk digests, and
confirms rollover runs outside the request thread. Other rollover error paths
remain unproven.

## WebSocketEndpoint dispatch slice

The input-only fixture in
[`websocket-endpoint-dispatch.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-dispatch.yaml)
invokes the documented `starlette.endpoints.WebSocketEndpoint` ASGI interface.
Eight cases compare the pinned source and installed package exactly across
connect/disconnect hooks, offered subprotocols, text and bytes decoding, JSON
text and binary decoding, malformed and mismatched frames, and the default
encoding. Three additional cases exercise callback-error propagation, invalid
encoding, and cancellation while waiting for the next receive. The source
results are retained, while package-target results are recorded as unsupported
under the operation's declared partial-support gaps; they do not establish
package parity for those behaviors.

The Python wrapper forwards dispatch and decoding to the Rust runtime. User
hooks remain Python callables invoked and awaited on Python's event loop. The
Rust-native target does not currently expose the Python `WebSocketEndpoint`
class and ASGI consumer interface. Other boundary cases remain uncovered,
including failures from `on_connect` or `on_disconnect`, missing disconnect
codes, empty default-encoding text, malformed binary JSON, and unexpected ASGI
message types.

## Import-path candidates

The 31 non-private leaf module paths are:

`starlette.applications`, `starlette.authentication`, `starlette.background`,
`starlette.concurrency`, `starlette.config`, `starlette.convertors`,
`starlette.datastructures`, `starlette.endpoints`, `starlette.exceptions`,
`starlette.formparsers`, `starlette.middleware.authentication`,
`starlette.middleware.base`, `starlette.middleware.body_limit`,
`starlette.middleware.cors`, `starlette.middleware.errors`,
`starlette.middleware.exceptions`, `starlette.middleware.gzip`,
`starlette.middleware.httpsredirect`, `starlette.middleware.sessions`,
`starlette.middleware.trustedhost`, `starlette.middleware.wsgi`,
`starlette.requests`, `starlette.responses`, `starlette.routing`,
`starlette.schemas`, `starlette.staticfiles`, `starlette.status`,
`starlette.templating`, `starlette.testclient`, `starlette.types`, and
`starlette.websockets`. The leaf paths sit under the package paths `starlette`
and `starlette.middleware`.

The private implementation modules `starlette._exception_handler` and
`starlette._utils` are tracked as implementation dependencies, not public
imports. `starlette.graphql` was removed before this pin; the docs explain that
GraphQL is supplied by third-party packages. WSGI remains present but deprecated
in the pinned source.

## Errors, aliases, and deprecations identified in the pinned source

The symbol catalog includes exception declarations. Error-related public-name
candidates include `AuthenticationError`, `ClientDisconnect`, `EnvironError`,
`HTTPException`, `MalformedRangeHeader`, `MultiPartException`, `NoMatchFound`,
`RangeNotSatisfiable`, `StarletteDeprecationWarning`, `WebSocketDisconnect`,
and `WebSocketException`; their source-backed classification and observable
behavior are recorded in the merged API review and fixture matrix.

The deprecated `starlette.status` aliases and their replacements are:

| Deprecated name | Replacement | Compatibility detail |
| --- | --- | --- |
| `HTTP_413_REQUEST_ENTITY_TOO_LARGE` | `HTTP_413_CONTENT_TOO_LARGE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_414_REQUEST_URI_TOO_LONG` | `HTTP_414_URI_TOO_LONG` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE` | `HTTP_416_RANGE_NOT_SATISFIABLE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_422_UNPROCESSABLE_ENTITY` | `HTTP_422_UNPROCESSABLE_CONTENT` | Emits `StarletteDeprecationWarning` on access |

Other deprecation behavior identified for exact compatibility includes
`run_until_first_complete`, importing `starlette.middleware.wsgi`, generator
and async-generator lifespan callables, `TestClient(timeout=...)`, and the
legacy `httpx` TestClient backend. Preserve category, message, timing, and
stack level from the pinned source.

## Unresolved points carried into implementation

- The 199 `uncertain` API candidates remain deliberately unresolved where the
  pinned docs, source, and release history do not establish public intent.
- The WebSocket guide says query parameters are unsupported while a pinned test
  exercises them; both inputs remain separate in
  `doc.testclient.websocket-query-params` until the mismatch is reconciled.
- Jinja2 has no declared minimum version although templating selects between
  context decorator names; see `optional.jinja2-version-compatibility`.
- The GZip module has a TODO for a future `DEFAULT_EXCLUDED_CONTENT_TYPE`
  rename while the pinned export is plural; see
  `middleware.alias.gzip-exclusion-constant`.
- The upstream-internal `GZipResponder` import is absent from the compatibility
  package; the current exact parity slice covers the public `GZipMiddleware`
  boundary only.
- The docs say async Jinja2 context processors are unsupported without
  specifying whether use errors, is ignored, or is awaited; see
  `doc.templates.async-context-processor-constraint`.

These items are tracked as uncertain behavior or backlog stimuli; they do not
block using the atlas to choose implementation work. The remaining staged work
includes broader Python/Rust boundary characterization and expansion beyond
the current ASGI, GZip, default HTTPException, and registered-handler slices.
The backlog distinguishes that work from the 443 currently indexed cases and
the generated fixture backlog in [`fixture-backlog.csv`](atlas/fixture-backlog.csv).

## Generate the source candidate catalog

From this repository, pass the checked-out pinned source directory:

```sh
python3 scripts/inventory_upstream_api.py \
  --upstream /path/to/starlette \
  --output docs/api-surface.csv
```

The command rejects an unexpected upstream commit. The generated catalog is a
review aid, not a claim that every non-private source declaration is public.
Check for catalog drift without writing it by adding `--check`. The
`make source-inventory-check` target runs that check, then validates the full
fixture/documentation atlas against the same pinned checkout; source-parity CI
runs the target before behavioral comparisons.
