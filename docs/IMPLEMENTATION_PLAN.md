# Staged implementation plan

The objective is a full replacement for the pinned Starlette 1.6.0 Python
surface and ordinary ASGI contract. The pre-release `starlette-rs` API is
greenfield and carries no backward-compatibility guarantee. FastAPI and
Pydantic are outside this project's scope.

## Execution order and current status

Implementation remains the active phase. Keep implementing across feature
families and author input-only comparisons alongside the behavior. After
implementation closes, run the complete source/package and Rust-native parity
matrix, repair mismatches across families, measure coverage from that full
matrix, reconcile the source atlas, then run all correctness-gated benchmarks.

The active contract currently declares 2,391 input cases across 342
parity inputs and two benchmark inputs, 142 Starlette compatibility
operations, 13 Rust-native operations, and 1,302 parity requirements (1,260
compatibility and 42 native). Its scope mode is still `slice`. A new Config
typing consumer covers all nine pinned `Config.__call__` overload assertions;
its input-derived source/package Mypy 1.19.1 comparison passes with identical
diagnostics and revealed types, while its registered parity case remains
deferred to the full parity phase. The application typing consumer checks
both `await Request.form()` and `async with Request.form()`, and iterates
`Request.stream()` to assert that each yielded chunk is `bytes`. It also checks
`Request.body()` as `bytes`, `Request.json()` as `Any`, `Request.query_params`
as `QueryParams`, `Request.path_params` as `dict[str, Any]`, and
`Request.client` as `Address | None`. It now also asserts `Request.url` as
`URL`, `Request.cookies` as `dict[str, str]`, and inherited
`WebSocket.cookies` as `dict[str, str]`, `WebSocket.url` as `URL`, and the
inherited `WebSocket.headers` and `WebSocket.query_params` as `Headers` and
`QueryParams`. Pinned Mypy 1.19.1 produced identical output against Starlette
1.6.0 and the rebuilt installed wheel for these assertions.
A new WebSocketEndpoint input covers exception-context propagation when
resolving `json.decoder.JSONDecodeError` raises; its comparison remains
deferred to full parity. A new Jinja2Templates input observes two ordered
synchronous context processors that overwrite the same key; its
source/package comparison remains deferred to full parity.
A further Jinja2Templates input observes an unsupported async context
processor failing before template lookup, using a raising template hook to
make callback order visible. Pinned source and Rust ordering agree; the new
comparison remains deferred to full parity.
A synchronous context-processor input observes a built-in exception before
template lookup and records the processor and template-hook order; its
source/package comparison remains deferred to full parity.
The deprecated `run_until_first_complete` helper is implemented through a
Rust-owned task-group state machine with AnyIO retaining backend scheduling.
Four input-only cases cover first-completion cancellation, zero callbacks,
child-exception propagation, and external cancellation; their comparisons
remain deferred to full parity.
A direct `run_in_threadpool` input observes whether AnyIO scope cancellation
waits for its gated synchronous worker; its source/package comparison remains
deferred to full parity.
A Host→WebSocketRoute dispatch input and a TestClient cleanup-context input
are also registered and remain unexecuted until full parity.
A deferred `Request.form()` input now replaces `scope["headers"]` between
returning the form awaitable and awaiting it. The Rust state machine reads the
cached Request headers when it starts, matching pinned Starlette's `_get_form`
coroutine timing; the new comparison remains unexecuted until full parity.
A new direct
`WebSocketDisconnect` constructor input compares field assignment, inherited
exception arguments, Python truthiness, and call-binding errors; the Rust
helper and facade already match the pinned source, so no runtime change was
needed. This comparison remains deferred to the full parity phase. Commit
`162c2cb6` adds a WebSocket iterator `athrow(StopIteration)` input and the Rust
PEP 479 conversion to `RuntimeError` with cause/context; that comparison stays
unexecuted until the full parity phase. The generated
atlas has 851 source rows: 797 input mappings, 54 source-backed
`not_applicable` dispositions, and zero fixture-backlog rows. These counts
describe inventory and evidence coverage; they do not establish that every
documented behavior is implemented or compatible. The latest schema fix uses
Python's Unicode `str.isalnum()` classification at the Rust boundary to match
CPython's `re` word-character semantics when Rust's Unicode tables are newer.
The indexed U+2EBF0 literal-path input is unexecuted until full parity. A new
WebSocketEndpoint input preserves separate `message["type"]` lookups in the
dispatch `if` and `elif`; it remains unexecuted until full parity. Three newly registered
input-only comparisons cover Request cookie-cache persistence across header
mutation, TestClient shutdown and portal cleanup error precedence, and
`requires` mixed positional/keyword connection binding; they remain
unexecuted until the grouped parity phase. Two new Request.form inputs cover
positive arbitrary-precision max_fields and max_files limits beyond the finite
float range; they remain unexecuted until grouped parity. A new input-only
comparison checks
`run_in_threadpool` propagation and identity for a worker-raised
`StopAsyncIteration`; it also remains unexecuted. The latest Request boundary fix uses Python membership for the
documented `session`, `auth`, and `user` properties and adds a UserDict
instance-override input to the active source/package adapters; it remains
unexecuted until full parity. The WebSocket iterator now resolves its typed receive method through the receiver at each Rust iterator advance; three input-only descriptor-tape comparisons cover lazy lookup and the disconnect advance for text, bytes, and JSON and remains unexecuted. The Rust-native Route float negative-zero case is
also active and remains unexecuted until full parity. Commit `ba889955` adds
Request concurrent
body/disconnect recovery and terminal-event ordering, StaticFiles
package-sequence truthiness, TestClient cleanup precedence and WebSocket
portal-error context, WebSocket iterator `athrow(StopAsyncIteration)`
conversion, and a synchronous WebSocket send-callback failure case. Its seven
input-only comparisons remain unexecuted until full parity. The preceding
implementation batch fixes `QueryParams` string-subclass
hash/equality and `Mapping.get` error behavior, and reads CPython's live
`Morsel._reserved` table while preserving callback order. Four input-only cases
cover those boundaries and remain unexecuted until the grouped parity phase.
The newest implementation slices also fix TestClient debug-info
membership-before-index error propagation, Host reverse-lookup parameters
after host-prefix formatting, and route-local middleware kwargs expansion from
a non-dict Mapping. Their three input-only cases remain unexecuted until the
grouped parity phase.
A routing correction now uses exact raw `b"host"` header-name
matching, as pinned `Headers.__getitem__` does; the renamed input-only
`router-host-header-raw-name.yaml` observes that a raw `b"Host"` header does
not select a Host route. Its comparison remains unexecuted until full parity.
The latest compatibility slice corrects `Environ.__len__` to invoke the
underlying mapping's type-level Python special method and adds an input-only
case with a shadowing instance attribute; its comparison remains deferred.
The newest input-only batch adds `run_in_threadpool` ContextVar
propagation/isolation, WebSocket callback-descriptor lookup timing, and a
StaticFiles root-path prefix-boundary case. All four comparisons remain
unexecuted until full parity. The newest compatibility batch fixes tuple-backed
`user_middleware` stack construction, preserves `UploadFile` subclass
`_will_roll()` and `_in_memory` policy overrides, and matches
`Request.send_push_promise` header iteration order; its three input-only
comparisons remain unexecuted. The newest Rust-native implementation adds custom converter
registration to `NativeApplication` route dispatch and an input-only
Starlette comparison; that comparison remains unexecuted. The latest
compatibility batch adds input-only cases for
`FormData.close()` dynamic `multi_items()` dispatch and mixed native/custom
Router declaration-order error propagation; both comparisons remain
unexecuted. The preceding batch adds input-only cases for WebSocketEndpoint
PEP 479 conversion of escaping `StopIteration`, Router path
mutation preserving the compiled route pattern, and Jinja `url_for` function
annotations. It also strengthens the POSIX StaticFiles surrogateescape case
to create and match the exact invalid-byte filename, with ordinary returned
paths kept as strings and invalid UTF-8 paths represented as filesystem bytes.
These four comparisons remain unexecuted until full parity. The preceding
implementation batch fixes Request mapping special-method iteration, preserves
arbitrary Secret objects used as Config defaults, and matches CORS method
lookup before header lookup; its three new comparisons are unexecuted until
full parity. The latest implementation inputs cover mutable `BackgroundTask`
attributes, arbitrary-size `FileResponse` range endpoints, empty-filename MIME
inference, TestClient WebSocket
server ports above `u16`, non-string accepted subprotocols,
arbitrary-precision `SessionMiddleware.max_age`, FormData constructor key
preservation, mixed-case Host header names, and an unpadded one-digit
StaticFiles `If-Modified-Since` day. All ten input-only comparisons in these
four batches remain unexecuted; the date is accepted by the pinned parser.
The Jinja2 inputs inspect the default `url_for` global's name, module,
qualified name, annotations, and Python function type. A nested Python
forwarding function supplies the required function object because a PyO3
callable cannot satisfy function-type introspection; URL resolution remains in
Rust. The new function-type comparison is deferred to the full parity phase.
A new HTTPSRedirect input verifies that a syntactically valid Host header takes precedence over an out-of-range `scope.server` port; it also remains deferred.
The newest implementation cases cover CPython async-generator `athrow()` call timing and arities, TestClient response bodies supplied as `bytearray` or `memoryview`, and `MutableHeaders.add_vary_header` for existing duplicate and absent Vary headers. Rust owns the native behavior and the unavoidable TestClient buffer-protocol boundary is documented; these comparisons remain unexecuted until the grouped parity phase.
The latest implementation slice fixes Host routing to read `host_regex`, preserves multipart `UploadFile.filename` values without stripping Windows path components, and reproduces CPython's `async for` TypeError/context/cause when an `__anext__` awaitable factory raises `StopAsyncIteration`. It also makes Starlette stack construction honor a `Middleware` subclass's `__iter__` and yielded `*args/**kwargs`; the Python iterator/mapping callback boundary is documented in [`APPLICATION_MIDDLEWARE_BOUNDARY.md`](APPLICATION_MIDDLEWARE_BOUNDARY.md). Two new input-only cases cover multipart Windows filenames and middleware iterator overrides. These inputs and the existing Host and StreamingResponse cases remain unexecuted until full parity.
The latest 12 input-only cases cover non-string `HTTPException` detail and header-key errors, Python equality for special exception-handler selection, FileResponse multipart short reads, Mount `path=None`, Request custom receive events between chunks, TestClient portal-setup error policy, empty StaticFiles `If-None-Match` fallback, WebSocket raw state assignment, StreamingResponse type-level async iteration, and empty CORS private-network headers. Source inventory and contract validation pass with zero parity passes claimed; all 12 comparisons remain deferred to the grouped parity phase.
The newest four input-only cases cover the deprecated TestClient `httpx` fallback, closing `Request.stream()` before its first advance, preserving an existing WebSocketEndpoint disconnect-hook context, and duplicate-key Python mapping expansion in a synchronous `BackgroundTask`. The Request, WebSocketEndpoint, and BackgroundTask Rust paths now preserve the source behavior; the TestClient fallback input records the existing boundary. All four comparisons remain unexecuted until the full parity phase.
The latest routing slice makes `Mount.url_path_for()` treat a falsey mounted
app `routes` attribute as empty, matching the pinned `routes or []` behavior;
its `routes: null` comparison is authored and unexecuted. The compatibility
facade also restores the explicitly imported `starlette.testclient.ASGIInstance`
typing alias. Its consumer assertion is included in the existing application
typing input, but that expanded input has not yet been rechecked against the
pinned source and installed wheel.
The preceding implementation batch adds eight unexecuted cases: CPython cookie
raw-value validation before optional attributes, two lazy StaticFiles
PathLike error-display cases, and five nested Rust-native reverse-routing
inputs covering Host/Mount composition, unresolved prefixes, Mount `path`
forwarding, route-name fallback, and Python-package prefix-formatting errors.
Recent
source-confirmed fixes also cover StaticFiles internal-comment date parsing,
lifespan exception-type identity, and the SessionMiddleware, StaticFiles,
TestClient, and WebSocketEndpoint edge cases. The Python typing consumer now
covers HTTPConnection, Request, WebSocket, and WebSocketClose ASGI signatures
and Request value annotations. Exact parity comparison distinguishes JSON
booleans, integers, and floats by type.
The newest implementation batch adds five input-only cases across four files:
multipart UploadFile rollover progress and failure cleanup/size state, supplied
cookie-Morsel control-character validation, TestClient request-body and error
policy, and WebSocketEndpoint's missing-disconnect-code default. The Morsel
rendering check is implemented in Rust; all five comparisons remain unexecuted
until the full parity phase.
The latest three-case source audit preserves Config's invalid-integer-cast
`ValueError.__context__`, State's missing-attribute formatting through a
`str` subclass's `__format__`, and URL replacement's f-string formatting of a
numeric username when no password is supplied. The Config and State cases also
observe exception context. All three comparisons remain deferred to full
parity.
The current native implementation batch adds 12 input-only cases across four
inputs for mounted child dispatch, host-based service routing, lazy streaming
responses, custom converter matching, and custom converter URL formatting. It
registers five native operations and 16 parity requirements; all comparisons
remain deferred to the full parity phase. A separate compatibility input
covers explicit integer `HTTPException` status values.
The newest implementation batch fixes TestClient preservation of partial body
chunks after an incomplete response, preserves explicit `Request(receive=None)`,
accepts mapping-backed WebSocket scopes, and normalizes tuple response headers
before CORS mutation. Seven input-only cases cover:
multiple partial chunks before a suppressed exception, a StreamingResponse
callback that replaces live state after response start, an empty WSGI response
iterable, a WebSocketEndpoint invalid initial event that fails during
`on_connect` before disconnect finalization, a `UserDict` WebSocket scope,
explicit None receive callback, and tuple response-start headers under CORS. All
remain deferred to the full parity phase.
The current implementation batch adds seven input-only cases across five
files: Response, StreamingResponse, and FileResponse calls using `UserDict`
scopes; a FileResponse tuple-header write-back observation; a pinned typing
consumer for `Scope = MutableMapping[str, Any]`; TestClient denial-body error
context; WebSocket iterator `athrow()` after exhaustion; and BackgroundTask
argument expansion order. Rust now accepts mapping-backed response scopes,
keeps the original FileResponse scope through `Headers(scope=...)`, propagates
the application error after denial-stream closure, retains peer-disconnect
semantics while distinguishing throws into an exhausted iterator, and expands
mutable task arguments before re-reading `kwargs`. These comparisons remain
unexecuted until the full parity phase.
The latest implementation batch adds three input-only cases for Request custom
receive events, BaseHTTPMiddleware `body_iterator` replacement, and TestClient
mutable-mapping send messages. Rust now ignores non-request Request events
before reading request-only fields, reads the current BaseHTTP response body
iterator and preserves dict-message/final-body behavior, and consumes ASGI
send messages through mapping operations. These cases are registered but
remain unexecuted until the full parity phase.
The newest audit adds two further input-only comparisons. WSGI header-pair
unpacking now requests only the third item needed to distinguish a malformed
pair before propagating a later iterator error. The BackgroundTask case covers
an AnyIO-shielded worker callback that raises after its enclosing CancelScope
is cancelled; source review found no Rust runtime change was needed for that
boundary. Both comparisons remain deferred to the full parity phase.
The latest implementation batch makes TestClient response-header decoding
accept arbitrary two-item iterables, adds a WSGI response-iterator failure
after emitted chunks, and gives the existing WebSocketEndpoint disconnect-
finalizer cancellation input a target-side driver. A matched POSIX
surrogateescape StaticFiles filename now verifies direct lookup against an
actual file. WSGI iteration order and WebSocket finalizer cancellation already
match in Rust; those slices add source/target stimuli and adapter support. The
three new input cases and the existing cancellation comparison remain
unexecuted until the full parity phase.

Commit `c487b6c8` extends mutable ASGI scope handling through GZip, CORS,
authentication and body-limit middleware, StaticFiles, BaseHTTPMiddleware, and
StreamingResponse protocol selection. Existing UserDict comparisons cover the
public response and application/router paths. Seven new input-only cases now
cover middleware, StaticFiles, and BaseHTTP scope traces, the latter including
input-selected exception propagation from a mapping key lookup. These cases
remain unexecuted until full parity; coverage and benchmarks remain deferred.

The preceding batch adds the opposite Request body/stream truthiness-failure
order, TestClient lifespan startup-message comparison errors, and WebSocket
`receive_json` mode-comparison ordering. It also pins external GitHub workflow
actions to immutable references. Contract and source-inventory checks pass for
the 2,348-case contract; the three new behavioral inputs remain unexecuted.
The latest Request stream input covers resuming a partially consumed iterator
after `Request.body()` consumes the final request event and remains unexecuted
until the grouped parity phase.

`QueryParams` and `FormData` now inherit the public `ImmutableMultiDict` facade,
with their specialized Rust stores held in `_inner`. The registered public API
inspection input compares both classes' `__bases__` and `__mro__`; it remains
unexecuted until grouped parity. Query parsing, mapping operations, equality,
representation, and dynamic `FormData.close()` dispatch remain Rust-backed.

### Execution ledger

| Phase | State | Evidence |
| --- | --- | --- |
| Implementation | In progress. | `make contract-check PARITY_PYTHON=python3.12` validates 2,391 cases across 342 parity inputs, 142 compatibility operations, 13 native operations, and 1,302 parity requirements (1,260 compatibility / 42 native), with zero parity passes claimed. The Host→WebSocketRoute and TestClient cleanup-context inputs remain unexecuted until full parity. The new direct `run_in_threadpool` cancellation input observes AnyIO-scope cancellation while the worker is gated and remains unexecuted until full parity. The Config typing consumer covers all nine pinned `Config.__call__` overload assertions and passed direct Mypy 1.19.1 checks against the pinned source and installed wheel with identical diagnostics and revealed types; its registered parity case remains unexecuted. The application typing consumer checks `Request.form()` await/async-with, `Request.stream()` chunks as `bytes`, `Request.body()` as `bytes`, `Request.json()` as `Any`, `Request.query_params` as `QueryParams`, and `Request.path_params` as `dict[str, Any]`; pinned-source and installed-wheel Mypy 1.19.1 output matches for the existing assertions. Mypy 1.19.1 against the pinned source and rebuilt wheel now confirms the `ASGIInstance` and `QueryParams` item, `getlist()`, and `multi_items()` value types match. The Mount `routes: null` input and Rust truthiness fix are authored but unexecuted. `Request.client` is now asserted as `Address | None`; pinned-source and installed-wheel Mypy 1.19.1 output matches, and its registered consumer comparison remains deferred to full parity. A new direct `WebSocketDisconnect` constructor input covers supplied/default fields, inherited exception arguments, reason truthiness, and call-binding errors; its comparison remains unexecuted. A new FormData consumer contract preserves the pinned `UploadFile | str` types for indexing, `getlist()`, and `multi_items()`; the input comparison remains unexecuted. Two new Request.form inputs cover positive
arbitrary-precision max_fields and max_files limits; these comparisons remain
unexecuted. A new body-limit input checks that the Content-Length precheck
preserves the original scope headers mapping; both behavior and comparison
remain unexecuted. The Request stream-after-body-completion, connection-properties, and Route float negative-zero inputs remain unexecuted. This batch adds three unexecuted input-only cases for Request cookie-cache persistence across header mutation, TestClient shutdown and portal cleanup error precedence, and `requires` mixed positional/keyword connection binding; the separate `run_in_threadpool` `StopAsyncIteration` identity case is also active and unexecuted. A WebSocketEndpoint case checks ordered reads of a stateful `encoding` descriptor; its comparison is deferred to full parity. A new stateful message-mapping input
checks the distinct `message["type"]` branch lookups; it is unexecuted until full parity.
This slice moves typed WebSocket iterator descriptor lookup into each Rust iterator advance and adds three unexecuted descriptor-tape inputs for text, bytes, and JSON. `make source-inventory-check PARITY_PYTHON=python3.12` passes with 999 API candidates dispositioned and 851 atlas rows (797 mappings / 54 reasoned `not_applicable` / zero backlog). `env RUSTC_WRAPPER= make lint` passed. A prior implementation batch adds CPython `Morsel._reserved` cookie-name validation across CPython 3.10–3.14, preserves the callback order when `lower()` rebinds `_reserved`, and matches Python `str` subclass hashing/equality plus `Mapping.get` `KeyError` handling in `QueryParams`; all four input-only cases remain unexecuted until full parity. The latest implementation slices add input-only cases for TestClient debug-info membership-before-index errors, Host reverse-lookup leftover parameters after host-prefix consumption, and route-local middleware kwargs expansion from a non-dict Mapping; these three cases remain unexecuted until full parity. The preceding implementation batch adds route-instance `matches` override dispatch, TestClient WebSocket message-type equality error propagation, and a stateful FileResponse PathLike comparison; all three input-only cases remain unexecuted until full parity. The Response facade now forwards construction to Rust, which preserves assignment order and dynamically invokes Python `render` and `init_headers`; a new input-only case records render mutations at the header hook and remains unexecuted. A separate internal `_core.FileResponse.asgi_call` helper resolves `str(path)` at ASGI-call entry. The public facade uses `_core.FileResponse.call_for`, which preserves the pinned conversion timing; the helper is not part of Starlette's public surface. The newest Rust-native streaming batch adds binary and empty text/base64 chunk preservation alongside backpressure, producer-error, cancellation, and background-order cases; all remain unexecuted. Earlier input-only batches add `run_in_threadpool` ContextVar propagation/isolation, WebSocket callback-descriptor lookup timing, and a StaticFiles root-path prefix-boundary case; all four remain unexecuted. The newest compatibility batch adds input-defined tuple-backed `user_middleware`, UploadFile subclass policy overrides, and Request push-header iteration order; its three comparisons remain unexecuted. The newest Rust-native batch adds input-defined custom converter registration to `NativeApplication` route dispatch; its comparison remains unexecuted. The preceding batch adds dynamic `FormData.close()` dispatch through `multi_items()` and declaration-order error propagation in mixed native/custom Router scans; both input-only comparisons remain unexecuted. Earlier batches add WebSocketEndpoint PEP 479 conversion for `StopIteration`, Router path mutation with the original compiled matcher, Jinja `url_for.__annotations__`, and a matched POSIX StaticFiles surrogateescape filename; all four comparisons remain unexecuted. The filesystem conversion boundary is documented in [`STATICFILES_PATH_ENCODING_BOUNDARY.md`](STATICFILES_PATH_ENCODING_BOUNDARY.md). The preceding batch adds Request mapping special-method iteration, arbitrary-object Secret casts from Config defaults, and CORS method-before-header lookup ordering; all four comparisons remain unexecuted. Earlier slices cover iterable Response header-pair unpacking, Unix StaticFiles surrogateescape paths, WebSocketEndpoint status-lookup error context, Host regex selection, multipart filename preservation, invalid async-iterator awaitable error translation, and Middleware subclass iteration. Rust now treats `iterate_in_threadpool().athrow(...)` after normal exhaustion as a completed no-op; the composite input checks `StopIteration`, `ValueError`, and subsequent exhaustion, with its oracle comparison deferred until full parity. The application typing consumer also asserts `Request.url` and inherited `WebSocket.url` as `URL`, plus `WebSocket.cookies` as `dict[str, str]`; pinned-source and installed-wheel Mypy 1.19.1 results match. Full parity, coverage, and benchmarks remain deferred until implementation closes; `make docs-check` benchmark evidence must be refreshed during the benchmark phase. |
| Full parity and grouped repairs | Deferred until implementation closes. | The latest clean run, `dc8c8ca6-f2b7-449b-9f53-45860e3cad4c`, passed 2,254/2,254 comparisons for the preceding 1,992-case, 140-parity-input contract. Later optional-backend, WebSocket authorization, Router truthiness, BaseHTTPMiddleware iterator, StaticFiles path, response-protocol, close-code, TestClient exception, raw TestClient no-response return, custom-regex, Request stream retry, WebSocketEndpoint error-finalization, BaseHTTPMiddleware dispatch short-circuiting, StreamingResponse terminal-send failure, TestClient generator-body buffering, invalid initial WebSocket.accept events, Last-Modified If-Range matching, exception-class MRO precedence, Request receive-error retry, Request body retry after partial receive cancellation, empty root Mount dispatch, lazy StreamingResponse iterator acquisition after a failed response-start send, AsyncIterable descriptor failure after response-start, normal-return incomplete TestClient response, asyncio-marked TestClient ASGI3, WebSocketEndpoint hook-failure/context, bracketed IPv6 Host, StaticFiles `get_response` override, TestClient accepted-session error stream closure and completed-response exception propagation, StreamingResponse gated-send backpressure, WebSocket non-string send-type, BackgroundTask `kwargs` mapping expansion, synchronous WebSocketEndpoint `on_disconnect` failure, multipart rollover lifecycle, supplied-Morsel validation, and missing WebSocket disconnect-code cases are not included. The seven new TestClient partial-response, StreamingResponse callback, empty WSGI iterable, invalid initial WebSocketEndpoint, mutable WebSocket scope, explicit-None Request receive, and tuple CORS response-header cases are also outside that run. The current seven response, TestClient denial-body, WebSocket iterator-exhaustion, and BackgroundTask argument-order cases are likewise unexecuted. The Request custom-receive event, BaseHTTPMiddleware body-iterator replacement, TestClient MutableMapping send-message, WSGI header-unpack-order, AnyIO CancelScope worker-error, Config cast-error context, State missing-attribute formatting, and URL replacement formatting cases are also outside that run. The stateful StaticFiles PathLike, UploadFile write-error, BackgroundTasks live-list mutation, StreamingResponse caller-cancellation comparisons, and latest 12-case boundary batch remain unexecuted. The four newest TestClient fallback, Request stream-close-before-start, WebSocket context-preservation, and BackgroundTask duplicate-key comparisons are also unexecuted. |
| Full coverage and source reconciliation | Deferred until the full parity phase. | The latest measured run, `fd5b3b63-9ddc-44bd-bf38-35ecbc260dbe`, covered 19,909/28,139 Rust lines (70.7%) for the preceding contract. |
| All benchmarks | Deferred until coverage. | The latest run, `13ea2d04-7f31-4c12-93cd-855df93df8b0`, measured 74/74 source/package workloads for the preceding contract: six Router and 68 GZip workloads. |
| Packaging and interpreter qualification | Complete for the local macOS arm64 build. | Five CPython 3.10–3.14 wheels, an sdist, and the Rust crate were inspected; isolated wheel installs passed public ASGI smoke and `pip check`. Other platform builds remain unqualified. |

Prior parity, coverage, and benchmark receipts remain under ignored
`build/parity/`. The fixed compatibility denominators are 514 upstream test
functions and 24 documented pages. Derive changing mapping and backlog counts
from the generated [`coverage matrix`](atlas/coverage-matrix.csv) and
[`fixture backlog`](atlas/fixture-backlog.csv). Coverage is a measurement, not
a parity score. The full-replacement goal remains active.

`python3 scripts/check_docs.py` passes its 37-file link check. The aggregate
`make docs-check` still needs a benchmark receipt bound to the current manifest;
refresh it only during the planned full benchmark phase.

Boundary details: [response protocols](RESPONSE_RENDER_BOUNDARY.md),
[server-error traceback data](SERVER_ERROR_BOUNDARY.md),
[template callbacks](TEMPLATE_PROTOCOL_BOUNDARY.md),
[optional imports](OPTIONAL_IMPORT_BOUNDARY.md),
[ASGI ownership](WEBSOCKET_OWNERSHIP_BOUNDARY.md), and the
[custom BaseRoute callback boundary](ROUTE_MATCH_BOUNDARY.md), and
[StaticFiles filesystem path encoding](STATICFILES_PATH_ENCODING_BOUNDARY.md).

## Runtime architecture

The upstream Starlette distribution is a source oracle and is not a runtime
dependency. Rust owns Starlette decisions, branching, iteration, ordering,
state, and error policy. Python `starlette.*` modules forward inputs and
callbacks, convert values at the PyO3 boundary, and await Python callables on
their owning event loop. The runtime-wrapper policy check rejects Python
control flow in these facades.

The greenfield Rust-native API exposes a body-aware HTTP service over
`http::Request`/`Response`, streaming `http_body::Body`, and Tower `Service`/
`Layer` contracts, plus native WebSocket routing and lifespan management. Its
examples exercise streamed bodies, handshake/message sequences, hook ordering,
and host-owned future cancellation without invoking Python. Input-only
Starlette ASGI analogues are authored for all three surfaces, including Tower
middleware ordering, short-circuit responses, error propagation, and unread
request bodies; all remain unexecuted until the integrated parity phase. Three target-only lifespan fault
contracts cover shutdown error aggregation and dropping pending startup and
shutdown futures; they are authored and statically validated, but remain
unexecuted until the integrated parity phase. FastAPI composition is outside
this project's scope. See [`native-service.md`](native-service.md),
[`native-websocket.md`](native-websocket.md), and
[`native-lifespan.md`](native-lifespan.md) for the APIs and boundaries.

## 0. Establish the contract

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

The active parity contract is `parity-input@54`: the working tree currently
indexes 2,391 input cases across 342 parity files, two benchmark files, 142
Starlette compatibility operations, 13 Rust-native operations, and 1,302
parity requirements (1,260 compatibility and 42 native). The Config typing
consumer covers all nine pinned `Config.__call__` overload assertions and is
deferred to full parity. The latest clean full parity,
coverage, and benchmark receipts belong to the preceding 1,992-case, 140-file
contract. The generated source-row,
mapping, `not_applicable`, and backlog totals live in
[`coverage-matrix.csv`](atlas/coverage-matrix.csv) and
[`fixture-backlog.csv`](atlas/fixture-backlog.csv); regenerate them after
changing fixture dispositions. The implementation history below records how
the input set grew; current gate states are in the execution ledger above.
The preceding @44 working-tree matrix and instrumented coverage run passed with four
unsupported native cases retained. Clean commit `553a06a` also passed the full
parity gate and all 74 source/package benchmarks; native benchmark interfaces
remain unavailable. See [current parity evidence](PARITY.md). The latest
implementation batch also adds an input-only nested Host→Mount→Host→Route
reverse-lookup case, AuthenticationMiddleware list and generator result
unpacking cases including malformed iterators, and a Request body-to-JSON retry
after `http.disconnect`. The Rust behavior and source mapping are in place;
these inputs remain unexecuted in the deferred full parity phase. The earlier
addition maps static and path-parameter WebSocketRoute matching through TestClient for
`tests/test_routing.py::test_router_add_websocket_route`; that test does not call
`Router.add_websocket_route`, so the method candidate remains uncertain. The
preceding addition compares invalid direct `Request` and `WebSocket` scope
construction against Starlette's assertion behavior. Before that, the URL-encoded
`Request.form` field-count and part-size errors with each body delivered in one
ASGI chunk. The earlier addition maps
`routing.test_partial_async_ws_endpoint` and compares partial-wrapped async
function and bound class-method WebSocketRoute endpoints through a mounted
Router. Recent additions include the nested TestClient
case that constructs an inner client inside an input-defined synchronous outer
endpoint, plus direct FormData
constructor/equality inputs; direct UploadFile constructor/repr, spooled-file
rollover, and threadpool-boundary inputs, and Python-package-only
GZip final and streaming response inputs at the `thread_minimum_size` boundary, an input-defined shared
AnyIO thread-pool limiter case and input-derived generic
`Request[State]` and `WebSocket[State]` type contracts, four source-shaped
TrustedHost TestClient workflows for exact/wildcard acceptance, invalid-host
rejection, and HTTPS www redirect following, plus TestClient base-URL
path-prefix merging and default redirect following, Rust-backed
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

The latest generated coverage matrix contains 851 source rows: 797 input
mappings, 54 source-backed `not_applicable` rows, and zero fixture-backlog rows.
Refresh these counts from the generated atlas CSV files after changing fixture
dispositions.
The fixed denominators remain 514 upstream test functions and 24 documentation
pages; the full replacement objective is active and incomplete.

Additional bounded comparisons include six WSGIMiddleware cases, two direct
`build_environ` cases, and the module-import deprecation warning case. The
async endpoint-boundary input checks caller loop/task/thread ownership,
cancellation, and endpoint finalization. Current fixture coverage also includes
22 response-background-task workflows, 31 FileResponse behavior cases, 20 URL
scope cases, 14 URL component cases, ten Headers/MutableHeaders cases, and
24 BaseHTTPMiddleware cases. These slices pass only for their declared inputs
and profiles; detailed observations, limitations, and run identities remain in
[Migration parity contract and evidence](PARITY.md).

## Completed bounded goal: Rust-owned StaticFiles core

The Rust core now owns StaticFiles path normalization, path containment, symlink
policy, lookup, method selection, HTML index/fallback selection, redirects, and
conditional 304 handling. The Python `starlette.staticfiles` module is a thin
constructor and forwarding facade; package discovery calls Python's
`importlib.util.find_spec` at the PyO3 boundary so custom importers and package
origins remain visible. At an earlier bounded-run checkpoint, 44 input-only
cases were authored across five StaticFiles inputs. Fifteen `lookup_path`
cases ran on both target profiles and all 30 comparisons passed, including
Unix and UNC-style absolute-path rejection. Across that StaticFiles slice, all
75 selected profile comparisons passed: 37 Rust-native and 38 Python-package
comparisons.
The path-limit inputs verify that an overlong first root maps to the
source-compatible 404 before a later root can serve its matching asset, under
both symlink settings. Permission inputs deny search access to a root containing
an asset and match the 401 error for both symlink settings. Python package
discovery is profile-specific; Rust-native uses explicit package roots.
Windows path normalization is implemented and has an authored ASGI input, but
Windows execution remains unverified. The ASGI entry passes the bound
`get_response(path, scope)` override into the Rust awaitable state machine,
which calls and awaits that Python callback on the caller's loop; the default
path selection and response dispatch remain Rust-owned. This callback boundary
is required because Python subclasses can replace `get_response`. An
input-only comparison checks the supplied callback arguments and returned
response and remains unexecuted. The active contract now contains 83
StaticFiles cases across 21 input files. A source audit of all metadata-listed
StaticFiles methods and the 36 upstream `tests/test_staticfiles.py` functions
found those behaviors mapped to existing inputs and no distinct ordinary-input
gap to implement. The current complete parity matrix remains unexecuted, so the
audit does not establish runtime parity.

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
graphs remain open. Rust owns compatibility route ordering, method
FULL/PARTIAL decisions, capture conversion, and reverse formatting. It invokes
each route's source-compiled `path_regex.match` as a narrow Python boundary
because CPython's `re` syntax and matching semantics define the public custom
converter contract. For example, CPython interprets `\N{LATIN SMALL LETTER A}`
as the named Unicode character `a`; the former Rust `fancy-regex` matcher
interpreted `\N` as “not newline” and could not preserve this behavior. The
Python `convert`/`to_string` methods remain callbacks. The input-only dispatch
case exercises the Python-only Unicode character-name escape, while the
reverse-URL case exercises custom `to_string`; parity execution remains
deferred to the integrated parity phase. The separate Rust-native `RouteTable`
API still exposes its built-in converter model only. Route/router/mount-local
middleware has selected input-only cases in
[`route-local-middleware-semantics.yaml`](../tests/fixtures/sources/parity/route-local-middleware-semantics.yaml)
and [`route-middleware-dispatch.yaml`](../tests/fixtures/sources/parity/route-middleware-dispatch.yaml).
Those inputs still need the deferred full parity run; broader combinations
remain implementation work.

### Completed bounded goal: reverse URL generation

The input-only `reverse-url-routing.yaml` slice covers `Route`,
`WebSocketRoute`, `Router`, `Mount`, `Starlette`, and `Request` URL generation.
It exercises built-in converter formatting and errors, a Python custom
converter override, first-success router selection, direct and nested mounts,
`app_root_path`, provider fallback, missing context, and the top-level
application forwarder. All 21 source/package comparisons passed in the earlier
checkpoint. Rust owns the Python package's path substitution primitive and now
invokes custom `to_string` methods as boundary callbacks; the updated reverse
URL input has not yet been rerun. The separate Rust-native Router URLPath
comparisons and their limits are recorded below. A separate bounded Host case
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
message for a complete miss in that earlier run. At that checkpoint, native
support was limited to direct HTTP routes, built-in converters, and
converter-formatted string inputs. Native formatting failures remained typed
Rust errors rather than Python exception objects.

The preceding `parity-input@51` contract extended the native subset through
recursive named HTTP and WebSocket routes, Mounts, and Hosts. Input-only cases
cover full Host→Mount lookup, partial Mount/Host prefixes that preserve
unresolved placeholders, a Mount forwarding its `path` parameter to a child
Route, and route-name miss fallback. A separate Python-package case distinguishes
a matching Mount-prefix formatting error from a name miss; it remains outside
the native profile while native Python-error mapping is incomplete. These
comparisons are authored but have not run. Native custom converter registration
and formatting now have separate input-only cases; broader converter semantics
and Python exception class/message compatibility remain incomplete.

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
The latest clean full run for `parity-input@47` recorded four Rust-native
callable boundaries as `not_run`; the active @50 contract has not had its full
matrix run. The full Starlette replacement remains incomplete. Active inputs
cover direct `ServerErrorMiddleware` debug HTML, non-HTTP pass-through,
response-already-started errors, application background-task errors, and
middleware ordering in addition to construction, handler dispatch, and field
mutation. The direct cases are source-backed probes; the custom-handler input
also maps to the pinned `tests/middleware/test_errors.py::test_handler`.
Their complete comparisons remain part of the deferred full parity phase.
Further implementation work includes broader HTTP/WebSocket connection and
request-body behavior, streaming backpressure and iterator lifecycle, broader
WebSocket exception flows, remaining TestClient exception-propagation modes,
additional synchronous background-cancellation schedules, context variables,
and broader background-task error interactions. The latest input-only batch
also closes the identified runtime gaps for nested Host reverse lookup,
AuthenticationMiddleware iterator results, and Request body retry after
disconnect. Additional input-only probes now cover an invalid first ASGI message
during WebSocket.accept(), an OSError on StreamingResponse’s terminal body send,
TestClient draining a generator-backed request through its final event, a
Last-Modified If-Range match for FileResponse, exception-class MRO precedence
when a base handler was registered first, and recovery after Request.body()'s
receive callback raises. Existing Rust paths already model these outcomes; the
TestClient receive machine already yields generator-backed request chunks. New
input-only cases also verify that StreamingResponse does not acquire its async
iterator when response-start send fails, and that TestClient returns an empty
body when an ASGI app returns after an incomplete response. The current
implementation batch fixes three additional source-confirmed gaps: Python's
direct ISO-8859-1 byte mapping for multipart text, negative-zero range-end
parsing in FileResponse, and Router's one-time GET-to-HEAD inference after a
live route-method mutation. Their input-only comparisons, along with the
previously authored cases, remain unrun until the full parity phase.

## 4. Optional and edge features

Configuration and schema generation have eight package-only live parity
cases across seven Rust-backed public operations. FileResponse range, multipart,
and chunk-size cases are mapped; the package keeps PyYAML optional behind its
`schemas` extra. StaticFiles lookup/configuration, form parsing, templates,
and TestClient HTTP, WebSocket, and lifespan slices also have bounded input
coverage. Several implementation behaviors now have input-only cases but still await
the deferred parity phase, including TestClient generator-body buffering and
entry-cleanup error precedence, broader TestClient exception modes, and wider
route/middleware combinations. The generated fixture backlog
is currently empty; it tracks source mapping, not implementation completion.
Choose the next behavior from the remaining source-backed gaps and supported
public API contract, keep optional dependencies feature-gated, and preserve
unsupported target rows in the later full parity results.

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
passes against the source and installed package. The Rust-native API supports
lazy `futures::Stream` sources through `StreamingResponse::from_stream` and its
pull-driven call state machine; input-only cases cover backpressure, producer
errors, cancellation, binary chunks, and empty text/base64 chunks. These newer comparisons
remain deferred until the full parity phase. The Rust API accepts
`futures::Stream`; Python `AsyncIterator` interoperability remains a separate
boundary requirement. The Python wrapper sends the start event before iterating,
emits each chunk lazily using Rust-built ASGI messages, and sends the final
empty body event on exhaustion. The byte case is supported by the pinned source
pass-through branch; upstream has no dedicated raw-bytes test. This evidence
does not establish arbitrary iterator cancellation, disconnect races,
synchronous background-callback cancellation through StreamingResponse, ASGI 2.4
`OSError` mapping, or all memoryview formats.

### Completed bounded goal: Response background task sequencing

[`background-tasks.yaml`](../tests/fixtures/sources/parity/background-tasks.yaml)
contains twenty-two package-profile cases with callback mode, arguments, failure,
callable shape, and task-list construction supplied by each input. They cover
async and sync functions, bound methods, callable objects, partials, nested
partials, callback arguments, response-send ordering, worker-thread execution
for synchronous callbacks, both `BackgroundTasks` construction paths,
sequential execution, and propagation that stops later tasks after the first
failure. The cancellation case cancels a response after its async callback
starts and compares the propagated `CancelledError`, callback cancellation,
finalizer, and response event tape. A new input cancels while the first
synchronous task in a list is running, releases it to raise, and observes that
the next task stays unstarted; this interaction comparison is also deferred.
The earlier integrated run covered the fourteen cases then indexed, and each
passed exact source/package comparison. The single-task async and sync
cancellation cases are included in that historical profile. The active
fixture crosswalk promotes the
callable-shape behavior alongside the previously mapped BackgroundTask
behaviors. A new input-only case also cancels `Response.__call__` while the
first async callback in a two-task `BackgroundTasks` list is awaiting; it
records cancellation/finalization, the propagated `CancelledError`, and that
the second callback never starts. This comparison is authored but unexecuted.
Another input cancels `Response.__call__` while a synchronous `BackgroundTask`
waits in its AnyIO worker, then releases the callback to raise. Its trace
records the response send tape, worker callback start, release, error and
finalization, plus the propagated public exception. Starlette routes the
callback through `anyio.to_thread.run_sync`; the locked AnyIO 4.15.1 asyncio
backend awaits the worker future and publishes worker errors only while that
future is not cancelled (`anyio/_backends/_asyncio.py:2650-2706, 1068-1084`).
The cancellation/error interaction remains unverified until parity runs.

This remains a bounded slice. Additional synchronous cancellation schedules,
context-variable behavior beyond the separate input below, concurrency, and
broader middleware/error interactions with background failures remain
unproven. The latest clean integrated full-slice run
`7607d008-0ee2-4186-8efd-60fba190fc47` selected 1,160 comparisons; the Python
package passed 912/912 and Rust-native passed 244/248, with four
Request-dispatch callable rows marked `not_run`. The status-module warning
callsite, TestClient lifespan missing-scope-state case, base-URL path-prefix
merge, and followed-redirect inputs passed exact source/package comparison.

### BackgroundTask ContextVar propagation input

[`response-asgi-callbacks.yaml`](../tests/fixtures/sources/parity/response-asgi-callbacks.yaml)
adds one source/package input that sets a caller-defined `ContextVar`, attaches
a synchronous `BackgroundTask` to `Response`, and records the callback's live
value and worker-thread role in the existing response trace. Starlette's
`BackgroundTask.__call__` delegates synchronous callbacks to
`run_in_threadpool`, and locked AnyIO 4.15.1's asyncio backend copies the
current context before queueing worker execution
(`anyio/_backends/_asyncio.py:2698-2705`). The Rust-backed `BackgroundTask` bridge
calls that same `anyio.to_thread.run_sync` API. This input is authored but
unexecuted; it covers this response/background boundary only.

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
unit-test suite; `make test` runs live source-to-target parity. That historical
checkpoint had six native callable rows marked `not_run`; the later clean @47
run had four. The current @48 full matrix has not run. Full Starlette
replacement remains incomplete.

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
contains direct public-surface inputs for constructor fields, synchronous
custom-handler and default-response dispatch, post-construction `.app`,
`.handler`, and `.debug` mutation, debug HTML, non-HTTP pass-through, and an
error after response start. Only the custom-handler input maps to an upstream
test function, `tests/middleware/test_errors.py::test_handler`; the other
cases follow the pinned `ServerErrorMiddleware` source contract. The first six
cases passed exact source/package comparison in run
`30a58707-ee2a-4146-b14d-2f0b104af348`; the later boundary additions await the
full @48 parity run. Application background-task errors and middleware
ordering have separate inputs in `asgi-server-errors.yaml` and
`application-middleware.yaml`. Broader middleware and WebSocket exception
combinations remain unverified.

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
introspection beyond the declared inputs, WebSocketEndpoint behavior outside
its current authored input cases, further application-level exception modes,
`TestClient`, authentication and mount/host route behavior beyond the child-scope
case, additional denial-response and streaming workflows, file-denial behavior,
and concurrency cancellation remain follow-on work requiring their own
input-only workflows and live comparisons. Each fixture contains only
operation stimulus and observation selectors; expected values remain in live
result artifacts. A new unexecuted convenience input exercises unhashable JSON
modes and a falsey non-string close reason; source review found the Rust path
already matches those Python operations.

## Completed bounded goal: ExceptionMiddleware handler typing

The input-only Mypy consumer in
[`exception-middleware-typing.yaml`](../tests/fixtures/sources/parity/exception-middleware-typing.yaml)
maps the pinned `tests/test_exceptions.py::test_handlers_annotations` contract.
The Python facade now exposes the pinned `ASGIApp` and `ExceptionHandler`
annotations, with import-only `TYPE_CHECKING` references preserving the
`Request`, `Response`, and `WebSocket` callback types. The source and installed
package reveal identical constructor types, accept the input-defined sync and
async `JSONResponse` handlers, and emit identical diagnostics for an
incompatible integer-returning handler. This passed in full-slice run
`4042a0c1-2fdd-4966-96ac-3010bf4bf02d`; it establishes this static Python
contract only, not runtime or Rust-native parity.

## 8. Packaging and release readiness

Local artifact qualification is complete on macOS arm64: the Rust crate passed
`cargo package` verification; the sdist and CPython 3.10–3.14 wheels built and
passed content/license/notice checks; each wheel installed with its `full`
extra and passed an isolated consumer smoke and `pip check`. `make
supply-chain-check` verifies the generated Rust dependency license bundle and
the workspace license, source, and advisory policies. This does not qualify
other operating systems or authorize publication. Do not publish to crates.io
or PyPI without a later explicit request.

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
