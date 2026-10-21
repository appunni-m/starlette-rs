# Compatibility inventory

## Current verification status

The active contract is `migration-parity/manifest@6`, SHA-256
`a1c459cc7afdadfcc0be11c77ffd44452d57f7b529db56a011aea21db0d8a111`, against Starlette 1.6.0 revision
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The implementation/input
candidate under verification is
`528d403c7566271ff745de90e0fc1e096ec97fbf`. Current `main` has since received
documentation-only status updates; runtime code, manifest, and authored inputs
are unchanged from that candidate. It declares 2,872 unique input-only cases across 492 parity
inputs, two benchmark inputs, 157 compatibility operations, 18 Rust-native
operations, 1,526 parity requirements, and six target profiles. The generated
API catalog has 999 candidates; 564 are supported. `make source-inventory-check`
passes for this manifest. It validates the authored contract and input references
but does not run source/package comparisons.

Full verification workflow
[#36](https://github.com/appunni-m/starlette-rs/actions/runs/39556068221)
completed on predecessor implementation/input candidate
`73a5c70aab4cf182ca0ea5c65b5f3c00af5d808c`, with all five CPython profiles
failing on the missing `starlette_rs_py._core.Cookies` binding. CPython 3.10,
3.11, 3.13, and 3.14 each passed 3,276/3,325 selected comparisons, with 46
failures, three not-run rows, three adapter errors, and 9/9 selected fault
contracts passing. CPython 3.12 passed 3,277/3,326 with the same failure and
error counts and 11/11 fault contracts passing. Coverage jobs were skipped.
The Rust-backed binding repair and repeated-name-across-fields input are
included on the current candidate. Workflow #37
([39566055323](https://github.com/appunni-m/starlette-rs/actions/runs/39566055323))
was canceled on predecessor `3814b2af` without qualifying results. Current full
verification workflow #39
([39569267790](https://github.com/appunni-m/starlette-rs/actions/runs/39569267790))
targets that implementation/input candidate. All five CPython profiles
succeeded. Their artifacts report 3,327 or 3,328 selected comparisons and all
selected fault contracts passing, with zero failures, `not_run` rows, or
infrastructure errors. See the per-profile table in
[the parity report](PARITY.md#current-verification-status). Six coverage
profiles have started: `rust-native-local` succeeded and five CPython profiles
are running. The eligible-line union is not yet available.
Per-input notes below that say a comparison is deferred record authoring-time
status.
Workflow
[#35](https://github.com/appunni-m/starlette-rs/actions/runs/39539987998)
is historical for target `ccfc2b032cbf5986e77893a56761a6388691f0df`: it passed
16,471/16,471 comparisons and 47/47 fault contracts, with zero failures,
`not_run` rows, or infrastructure errors. Its six-profile eligible-line union
failed at 28,247/33,443 lines (84.4631%), leaving 5,196 uncovered lines across
67 of 69 eligible production paths. That coverage measurement is for its named
source snapshot and does not identify gaps in current `main`. Earlier full workflow #15 passed
15,726/15,726 parity
comparisons and 22/22 fault contracts on `df5e784`, but its CPython 3.14.8
coverage profile reported four cookie callback-error mismatches and emitted no
coverage receipt. Focused workflow
[`39198830087`](https://github.com/appunni-m/starlette-rs/actions/runs/39198830087)
(#11) passed the four affected response cases (4 passed, 0 failed) on
`b508db19`. That diagnostic result is not full parity or coverage. Earlier
workflow details below remain historical and bounded to the named revisions.

Generated atlas counts are 867 source rows, 811 existing input mappings, 56
source-backed `not_applicable` rows, and zero fixture-backlog rows. The
current contract check reports 999 API candidates, 564 supported candidates,
and six target profiles. These counts describe reviewed source disposition and
contract shape, not verified behavioral parity or full implementation. The
pinned denominators remain 514 upstream test functions and 24 documented
pages. The atlas has no unmapped source backlog. Workflow #39 on
implementation/input candidate `528d403c` has passed all five CPython parity
profiles. `rust-native-local` coverage succeeded and five CPython coverage
profiles are running; the union is pending. Workflow
#37 was canceled, and workflow #36 is the completed failed run on the
predecessor candidate. The current parity table is at the top of this document.
The previous run's parity and coverage receipts remain historical and bounded
to their named contract and code revisions. Inventory completeness does not
prove behavior outside the declared contract.

## Historical implementation-batch notes

The 5001-digit integer path-converter inputs now target each declared Python
package profile from CPython 3.10 through 3.14. CPython added the default
4300-digit conversion limit in 3.10.7 and 3.11; the versioned built-in type
references for 3.12, 3.13, and 3.14 document the same limitation. The
manifest records minor profiles, while result environment identities carry
the exact patch release. The only prepared profile recorded in this checkout
is CPython 3.12.13, so all expanded comparisons remain unexecuted until the
grouped parity phase. Parity subprocesses clear `PYTHONINTMAXSTRDIGITS` before
interpreter startup and record the variable as unset in the environment policy;
the CPython command-line reference says it configures the limit and `0`
disables it. Sources: [CPython 3.10 What's New](https://docs.python.org/3.10/whatsnew/3.10.html),
[3.11 What's New](https://docs.python.org/3.11/whatsnew/3.11.html),
[3.12 built-in types](https://docs.python.org/3.12/library/stdtypes.html#integer-string-conversion-length-limitation),
[3.13 built-in types](https://docs.python.org/3.13/library/stdtypes.html#integer-string-conversion-length-limitation),
and [3.14 built-in types](https://docs.python.org/3.14/library/stdtypes.html#integer-string-conversion-length-limitation).
See the [CPython 3.12 command-line reference](https://docs.python.org/3.12/using/cmdline.html#envvar-PYTHONINTMAXSTRDIGITS) for the environment variable behavior.

The async Request callable-shape input now includes a synchronous function
decorated by `inspect.markcoroutinefunction`, scoped to CPython 3.12–3.14 where
the marker is available and recognized by Starlette's selected detector. The
WebSocket iterator `athrow` input now targets CPython 3.10–3.14, with fresh
iterator cases separating invalid zero/four-argument calls from valid
one/two/three-argument calls. Tagged CPython source has the same
running-flag-before-arity-unpack behavior across those versions. These new and
expanded comparisons remain unexecuted until the grouped parity phase.

The `Starlette.__init__` and `Starlette.__call__` Python-package support records
now match their operation scope. The pinned constructor's input-copy order maps
to `PyStarletteRuntime::new`; the pinned ASGI call's scope write, lazy cached
stack build, and await map to `StarletteCall::start` and the scheduler-neutral
awaitable driver. The public API inventory already lists the class, constructor,
and ASGI call as supported. Input-only workflows cover construction ordering,
streaming dispatch, and caller cancellation; those comparisons remain deferred
to full parity. This operation-level status does not establish full replacement
parity, which remains pending.

TestClient's managed lifespan now resolves the client's bound `lifespan`,
`wait_startup`, and `wait_shutdown` methods through the AnyIO portal, matching
the pinned source's Python subclass dispatch. Input-only cases also observe
record-and-delegate overrides and the `AttributeError` from `__exit__` before
`__enter__`; both comparisons remain deferred until the grouped parity phase.

A new Request.state input distinguishes the return of `scope.setdefault("state", {})` from the subsequent `scope["state"]` read using an input-defined custom mapping; Rust preserves the pinned call/read ordering. A TemplateResponse input also checks that Rust resolves `HTMLResponse.__call__` after awaiting the optional debug send callback. Both comparisons remain deferred until the full parity phase.

A direct Response input supplies an explicit Content-Type header alongside `media_type="text/plain"`; the comparison observes constructor header precedence and automatic Content-Length and remains deferred to full parity.

A new input-only comparison covers a nonterminal `StreamingResponse` send
`OSError` under ASGI 2.3 while the receive listener remains gated. Rust already
uses the corresponding task-group structure by source review; the
source/package comparison is registered, unexecuted, and deferred to the full
parity phase.

The latest implementation batch adds input-only cases for the Request
body/stream truthiness-failure order, TestClient lifespan startup-message type
comparison, and WebSocket `receive_json` mode-comparison order. The cases pass
contract validation and remain unexecuted until the grouped parity phase.

The default middleware-stack input now also traces a successful request
through two user middleware layers, alongside its handled-405 and unhandled
error requests. The source/package comparison remains deferred to full parity.

The application typing consumer asserts `Request.headers` and inherited
`WebSocket.headers` as `Headers`, `Request.cookies` and inherited
`WebSocket.cookies` as `dict[str, str]`, `Request.url` and inherited
`WebSocket.url` as `URL`, inherited `WebSocket.query_params` as `QueryParams`,
`Request.receive` as `Receive`, and assigns inherited `WebSocket.receive` and
`WebSocket.send` to ASGI `Receive` and `Send` callbacks. `Request.client` and
inherited `WebSocket.client` are
asserted as `Address | None`. Pinned-source and rebuilt installed-wheel Mypy
1.19.1 diagnostics and revealed types match; the registered consumer
comparison remains deferred to full parity.

A WebSocketEndpoint constructor input supplies a non-WebSocket scope type
and observes the pinned assertion before dispatch; its comparison remains
deferred until full parity.

The template input set now also observes an unsupported async context
processor failing before template lookup. A raising lookup hook records the
order; pinned source and Rust processing order agree, and the new comparison
remains deferred to full parity.

WebSocket async iterators now resolve the corresponding typed receive method
through Python descriptor lookup at each Rust iterator advance, matching the
pinned async-generator body including its final disconnect advance. Three
input-only descriptor-tape comparisons for text, bytes, and JSON are authored
and remain unexecuted until the grouped parity phase.

The latest compatibility slice corrects `Environ.__len__` to invoke the
underlying mapping's type-level Python special method even when the mapping
instance shadows `__len__`. A separate input-only case observes the public
length through the live oracle and package; it remains unexecuted until full
parity.

Four additional input-only cases remain unexecuted: `QueryParams` lookup
with a Python `str` subclass that customizes hashing/equality, `Mapping.get`
catching `KeyError` from key hashing, the CPython 3.10–3.14
`Morsel._reserved` cookie-name boundary, and the callback order when a key
`lower()` method rebinds `Morsel._reserved` during `Response.set_cookie`.

The current implementation batch corrects GZip's raw header-name lookup,
multipart's generic UTF-16 BOM requirement and Latin-1 fallback, StaticFiles
handling of non-string HTTP methods, and WebSocket typed-receive descriptor
lookup order. Four input-only comparisons are registered for these behaviors;
all remain deferred to grouped parity. CORS observations and Authentication
backend-result materialization were corrected in the live adapters. The
SessionMiddleware no-expiry input covers an authenticated timestamp wider than
`u64`; Rust now accepts it without narrowing, matching ItsDangerous 2.2.0's
deferred timestamp conversion when `max_age=None`. Expiry-enabled timestamp
inputs continue to cover datetime-range errors separately. Two new Request
inputs omit `scope['auth']` and `scope['user']` in
turn while an instance-level UserDict `__contains__` override returns true;
type-level membership still sees each key as absent and produces the pinned
assertion with AuthenticationMiddleware guidance.
Both comparisons remain unexecuted until full parity. The successful WebSocket
authentication requirement now cites the pinned
`test_websocket_authentication_required` function at lines 273–303.
## Historical atlas and contract snapshot

Historical contract snapshot at commit `68951650`: 2,538 cases across 416
parity inputs and 1,399 requirements; the atlas recorded 866 source rows, 810
input mappings, 56 reasoned `not_applicable` rows, and zero backlog. Its first
five-profile pass found the CPython 3.10/3.11 URL difference and one CPython
3.12 package-adapter schema crash, both repaired before the active run. The
active verification is summarized at the beginning of this document.

**Atlas state:** Source-to-fixture mapping has zero backlog, and API candidate
rows have explicit dispositions. The full Starlette replacement remains active and
incomplete. The source authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The inventory deliberately keeps
source candidates separate from the reviewed compatibility surface; an
importable name alone does not establish public status. The atlas is a source
review and fixture crosswalk. The active parity contract declares the full
Starlette 1.6.0 compatibility surface; its current evidence status is summarized
below.

The prerelease `starlette-rs` API is greenfield and carries no backward-
compatibility guarantee. Starlette 1.6.0 alone governs the compatibility
surface.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source
references and the public source, documentation, and test roots used by
inventory generation. The separate [`parity manifest`](../tests/fixtures/manifest.yaml)
indexes behavioral requirements and generated input paths. Authored parity and
benchmark definitions live as JSON-compatible YAML under
`tests/fixtures/sources/{parity,benchmark}/`; `make parity-inputs` generates
runtime JSON under ignored `build/parity/inputs/`. Result JSON under
`build/parity/` is also local, ignored output. These build artifacts are not
checked in; the run IDs and counts below describe their recorded executions.

### Prior fully verified parity snapshot (`parity-input@63`)

The prior fully verified manifest snapshot uses `parity-input@63` and declares full Starlette scope (`starlette-1.6.0-full`, `scope.mode: full`): 2,590 input-only cases across 437 parity input files and two benchmark inputs, 152 Starlette compatibility operations, 15 separately registered Rust-native operations, 1,442 parity requirements, and six target profiles. Its SHA-256 is `f8a34c2978af95382ceadcd3e3a2c5a9d7bb1d467f03b35ba55033d9b7336124`. The active manifest is described at the top of this inventory; these run results predate its additions. The two @63 lifespan failure-send exception-context cases passed in the grouped matrix; current active-manifest parity is summarized above; coverage and benchmark remain pending. Earlier run details below are historical and do not establish parity for the active manifest. Three @59 input-only cases replace AuthenticationMiddleware public `backend`, `app`, and `on_error` attributes at their pinned source read points. Four @60 input-only comparisons cover live GZip app replacement, Request cookie parsing through an overridden `headers` property, Router dispatch with a path string subclass whose `startswith` returns false, and Mount slicing through an overridden path string subclass. The @61 MultiDict rich-inequality input joins those seven @59/@60 boundary comparisons, and the @62 WSGI status split-iterator input plus four BaseHTTPMiddleware comparisons extend the same boundary set. Those cases and their repair results are historical evidence for the preceding manifest hash, `ffbf919201d9d658793b8e1d42cea97f23c856bd062b2b2f2399e8e7786c6520`; they do not establish parity for the active manifest. Five newest Request/HTTPConnection boundary inputs cover overridden Request and WebSocket scopes, `Request.url_for` string and `base_url` subclass behavior, and push-promise header lookup; all passed on the available CPython 3.12 profile. A new TestClient import-policy input covers failure when both `httpx2` and legacy `httpx` are unavailable; its comparison remains deferred to grouped parity. The following implementation-batch observations preserve their original feature-level status as historical notes. The current implementation batch adds six input-only cases for BackgroundTask public attribute lookup, StaticFiles package tuple-subclass iteration, Route/Router Python scope-type comparison behavior, and Router missing-method lookup after path misses and matches; all remain unexecuted until grouped parity. New WebSocketRoute and Mount input-only cases verify that Router dispatch uses their constructor-compiled regexes after public path mutation; the comparisons remain deferred to full parity. New unexecuted inputs cover WebSocketRoute Python equality and missing-key propagation, plus CPython 3.10–3.14 ordinary BackgroundTask and concurrency behavior; advanced async-generator protocol cases remain scoped to CPython 3.12. The new StaticFiles no-root NUL lookup, WSGI list-subclass header-iteration, and WSGI status split-iterator comparisons are authored but unexecuted until grouped parity. The newest input-only cases cover truthy non-byte Request.stream bodies and TestClient binary JSON framing for noncanonical modes; they remain unexecuted until full parity. A focused target-only run passed the three Rust-native lifespan fault assertions, but its aggregate artifact was infrastructure-failed because prepared Python environments were stale after source changes. A new input-only case relays `Request.stream()` through an application route's `StreamingResponse` for fragmented and empty request bodies; it remains unexecuted until the grouped parity phase. Five newest input-only cases cover Rust-native Route float reverse formatting and WebSocket `send_json` serialization-before-mode-comparison ordering; these remain unexecuted until the grouped parity phase. Five new input-only cases preserve Request.stream message-type lookup order, Python comparisons in both error middlewares, and TestClient WebSocket text-object identity; they remain unexecuted until the grouped parity phase. A StaticFiles input covers an overflow-day If-Modified-Since value accepted by email.utils.parsedate; that comparison remains unexecuted until the grouped parity phase. The latest batch adds Rust-backed application middleware lookup ordering, non-string scope-type dispatch for AuthenticationMiddleware, SessionMiddleware, and GZipMiddleware, ServerErrorMiddleware message-type equality, and registered app-subclass lookup-order and pre-ASGI-2.4 caller-cancellation inputs; these comparisons remain unexecuted until full parity. The generated atlas reports 867 rows (811 input mappings, 56 reasoned `not_applicable` rows, zero backlog); all 999 API candidate rows are dispositioned, and zero source rows remain uncertain. The latest implementation batch adds three Route/Router/Mount middleware-order requirements, a TestClient complete-response handled-exception case, and adapter support for the existing BackgroundTasks cancellation/error case. The latest source-backed additions also cover GZip Unicode media-type normalization and SessionMiddleware errors escaping during request dispatch; their live comparisons remain deferred until grouped parity. Four additional input-only cases cover successful WebSocket authentication scope installation, first-value CORS duplicate-request-header handling, Request.stream skipping a custom event between body chunks, and TestClient WebSocket query encoding; all remain unexecuted until the grouped parity phase. The latest batch adds Rust-backed deletion for `BackgroundTasks.tasks`, preserves Python strings including lone surrogates in built-in converter formatting, and registers five input-only cases for background deletion, BaseExceptionGroup propagation, direct converter calls, public converter imports, and registration replacement across route snapshots; all remain unexecuted until full parity. A new input checks that `HTTPConnection.auth` and `.user` preserve present `None` scope values; its source/package comparison remains deferred until full parity. A StreamingResponse awaitable input checks that instance-level `__await__` does not shadow type-level lookup; Rust now resolves the awaitable through its type, and the source/package comparison remains deferred until full parity. The Config typing consumer covers all nine pinned `Config.__call__` overload assertions; its input-derived source/package Mypy 1.19.1 comparison passed with identical diagnostics and revealed types, while the registered parity case remains unexecuted until full parity. The FormData typing input checks `UploadFile | str` preservation for indexing, `getlist()`, and `multi_items()` against the pinned source and package facade using Mypy 1.19.1; this source/package type check passed, while grouped behavioral parity remains unexecuted. The application typing consumer also checks awaited WebSocket `receive_text()` as `str` and `receive_bytes()` as `bytes`; pinned-source and installed-wheel Mypy 1.19.1 output matches. It checks awaited and async-context-manager `Request.form()`, `Request.stream()` chunks as `bytes`, `Request.body()` as `bytes`, `Request.json()` as `Any`, `Request.query_params` as `QueryParams` with `str` item values, `list[str]` from `getlist()`, and `list[tuple[str, str]]` from `multi_items()`, plus `Request.path_params` as `dict[str, Any]`, and `Request.client` as `Address | None`; pinned-source and installed-wheel Mypy 1.19.1 output matches. The registered templating inputs cover ordered context processors that overwrite a route-provided value and synchronous processor failure before template lookup, with live processor and template-hook traces; their source/package comparisons remain deferred to full parity. The new TemplateResponse input replaces HTMLResponse.__call__ from the http.response.debug send callback and records whether Rust resolves the replacement afterward; its source/package comparison remains deferred to full parity. A new WebSocketEndpoint input preserves exception context when lookup of `json.decoder.JSONDecodeError` raises; its source/package comparison remains deferred to full parity. Commit `162c2cb6` adds a WebSocket iterator `athrow(StopIteration)` input and the Rust PEP 479 error conversion; that comparison remains unexecuted until full parity. A new input-only case checks that the body-limit Content-Length precheck preserves the original scope headers mapping; the behavior and comparison remain unexecuted until full parity. Two new Request.form cases check positive arbitrary-precision max_fields and max_files values beyond the finite float range; both remain unexecuted until full parity. The Request stream-after-body-completion input, Request connection-properties membership, Rust-native Route float negative-zero case, and the newest Request cookie-cache, TestClient shutdown-cleanup, `requires` binding, and stateful WebSocketEndpoint encoding-property inputs are active; all remain unexecuted until full parity. The new WebSocketEndpoint stateful message-mapping input checks separate `message["type"]` branch lookups and remains unexecuted until full parity. The new `run_in_threadpool` `StopAsyncIteration` exception-identity input is also active and unexecuted; Rust forwards the original worker exception through the coroutine continuation. A direct `run_in_threadpool` cancellation input now observes whether an AnyIO cancellation scope waits for the gated worker to finish; its comparison remains unexecuted until full parity. Rust now treats `iterate_in_threadpool().athrow(StopIteration)` and `athrow(ValueError)` after normal exhaustion as completed no-ops; the new input is active and unexecuted until full parity. The application typing input also asserts `Request.url` as `URL`, with matching pinned-source and installed-wheel Mypy 1.19.1 results. The generated atlas has 856 source rows: 802 input mappings, 54 source-backed `not_applicable` rows, and zero backlog. Commit `ba889955` adds seven input-only Request, StaticFiles, TestClient, and WebSocket cases; all remain unexecuted until grouped parity. The newest implementation slices add input-only comparisons for TestClient debug-info membership-before-index errors, Host reverse-lookup leftover parameters after host-prefix consumption, and route-local middleware kwargs expansion from a non-dict Mapping; all three remain unexecuted until full parity. The latest implementation batch adds input-only cases for `QueryParams` string-subclass hashing/equality and `Mapping.get` handling `KeyError` from key hashing, plus version-scoped `Morsel._reserved` behavior and cookie-key `lower()` rebinding order. All four remain unexecuted until full parity. The preceding batch adds route-instance `matches` override dispatch, TestClient WebSocket message-type equality error propagation, and stateful FileResponse PathLike resolution; all three remain unexecuted until full parity. A separate internal `_core.FileResponse.asgi_call` helper converts `str(path)` at ASGI-call entry. The public facade uses `_core.FileResponse.call_for`, which preserves the pinned conversion timing; the helper is not part of Starlette's public surface. Rust now owns Response constructor orchestration while dynamically invoking the Python `render` and `init_headers` callbacks; a new input-only case records render mutations at the header hook and remains unexecuted. The native `StreamingResponse` lazy-source inputs now include binary and empty text/base64 chunk preservation alongside backpressure, producer errors, cancellation, and background ordering; these comparisons remain unexecuted until the grouped parity phase. The newest compatibility batch adds input-only cases for tuple-backed `user_middleware`, `UploadFile` subclass `_will_roll()` and `_in_memory` policy overrides, and `Request.send_push_promise` header iteration order; these three comparisons remain unexecuted until full parity. The newest Rust-native batch adds input-only coverage for custom converter registration during `NativeApplication` route dispatch; its comparison remains unexecuted. The latest compatibility batch adds input-only cases for dynamic `FormData.close()` dispatch through an overridden `multi_items()` method and declaration-order error propagation across mixed native/custom Router routes; both comparisons remain unexecuted until full parity. The preceding implementation batch adds input-only cases for WebSocketEndpoint PEP 479 conversion of escaping `StopIteration`, Router path mutation preserving its compiled route pattern, and Jinja `url_for.__annotations__`; it also strengthens the POSIX StaticFiles surrogateescape input to create and match the invalid-byte filename and compare its path bytes. The latest template boundary case observes the default `url_for` global's Python function type and function-only globals attribute; Python supplies only the nested forwarding function because a PyO3 callable cannot satisfy that introspection, while Rust retains URL resolution. These comparisons remain unexecuted until full parity. The filesystem conversion boundary is documented in [`STATICFILES_PATH_ENCODING_BOUNDARY.md`](STATICFILES_PATH_ENCODING_BOUNDARY.md). The preceding implementation batch fixes Request scope iteration through type-level special-method lookup, preserves arbitrary Python objects as Config-cast Secret values, and matches CORS method-before-header lookup order; all three input-only comparisons remain unexecuted until full parity. Recent implementation slices add iterable Response header-pair unpacking, Unix StaticFiles surrogateescape preservation through direct lookup and ASGI scope paths, and WebSocketEndpoint status-lookup error context. Their five input-only comparisons and related existing comparisons remain unexecuted until full parity. The newest batch adds arbitrary iterable TestClient response-header pairs, WSGI iterator failure after response chunks, and target-adapter support for an existing WebSocketEndpoint disconnect-finalizer cancellation input. Earlier batches fixed Host routing to use `host_regex`, preserved decoded multipart upload filenames including Windows path components, corrected StreamingResponse's invalid async-iterator awaitable error translation, and invoked `Middleware` subclass `__iter__` when building the application stack. Two new input-only cases cover multipart filename preservation and middleware iterator override; the existing Host and streaming cases also remain unexecuted until full parity. The middleware special-method callback rationale and input are documented in [`APPLICATION_MIDDLEWARE_BOUNDARY.md`](APPLICATION_MIDDLEWARE_BOUNDARY.md). The latest Request.app input supplies a preexisting true app marker in the HTTP scope and observes the public property after application dispatch; it remains unexecuted until full parity. Recent implementation inputs cover TestClient partial-response preservation, explicit `Request(receive=None)` forwarding, mapping-backed WebSocket scopes and send messages, tuple response-header normalization before CORS mutation, Request custom receive events, BaseHTTPMiddleware body-iterator replacement, WSGI header-pair unpacking order, AnyIO-shielded BackgroundTask worker errors, Config cast-error context, State missing-attribute formatting, URL replacement formatting, non-string HTTPException values, special-handler equality, multipart FileResponse short reads, Mount `path=None`, TestClient portal setup errors, empty StaticFiles validators, raw WebSocket state assignment, StreamingResponse async-iterator lookup, empty CORS private-network headers, the deprecated TestClient httpx fallback, Request stream closure before first advancement, WebSocketEndpoint disconnect-hook context preservation, duplicate-key BackgroundTask kwargs expansion, TestClient falsey `more_body` truthiness, WebSocket unhashable JSON modes and falsey close reasons, zero-size FileResponse chunks, writable `Request._receive` replacement between stream chunks, and cancellation followed by a synchronous BackgroundTasks worker error. The newest inputs also cover empty synchronous StreamingResponse chunk framing, BaseHTTPMiddleware pass-through of status 65536, StaticFiles HTML index redirect through a nonempty root_path with query preservation, WebSocket accept-send OSError propagation, HTTPException default-handler conversion order, and TestClient message-type comparison errors. All eleven cases remain unexecuted until the full parity phase. The newest three input cases preserve a bytes-subclass Request stream chunk, non-close initial WebSocket session cleanup, and StreamingResponse background OSError propagation; their comparisons are also unexecuted. The latest batch adds `Request.stream()` exhaustion after a fresh iterator's first-advance `Stream consumed` error and `WebSocket.receive_text()` handling of a disconnect without a `code`; both comparisons remain unexecuted. The newest input-only batch adds `run_in_threadpool` ContextVar propagation/isolation, WebSocket callback-descriptor lookup timing, and a StaticFiles root-path prefix-boundary case; all four comparisons remain unexecuted. Full parity, coverage, and benchmarks were deferred at the time this historical batch note was written.

The added Request cookie input covers quoted unknown escapes, invalid octal, and valid quote, slash, and octal controls. Rust’s existing unquoting matches the pinned CPython behavior by source review; the source/package comparison remains deferred to grouped parity.

The current batch adds mutable-scope identity sequences for Request and WebSocket plus WSGI query-string ASCII and Latin-1 header-value boundary inputs. Source review found that Rust already matches the pinned Request identity, WSGI environment construction, and cookie unquoting behavior. The four new comparisons remain unexecuted until grouped parity.

The latest implementation batch adds four unexecuted inputs: Starlette application-level streaming through `StreamingResponse`, caller cancellation during a gated response send, Request stream recovery after a partial receive `ValueError`, and source-reviewed public API inspection across 33 pinned modules. The public-surface case selects all 432 unique supported catalog names and the 47 unique names imported by the pinned docs; it now observes the pinned `starlette.__version__` value of `1.6.0`. App streaming and cancellation are handled by both live workflow adapters. All four comparisons remain deferred to the grouped parity phase.

The latest templating implementation batch adds input-only cases for
HTMLResponse constructor lookup after rendering and context.update lookup
before context-processor invocation. It also matches the pinned
`Jinja2Templates.get_template` return type (`jinja2.Template`); the
source and rebuilt-wheel Mypy 1.19.1 consumer check passed. These registered
cases remain unexecuted until grouped parity.

The newest multipart input checks that the last duplicate Content-Type
`charset` parameter wins, matching the pinned multipart parser; Rust now uses
the final parameter value. A two-backend TestClient input checks that
WebSocket application exceptions propagate even when HTTP
`raise_server_exceptions` is false; the Rust session path already matches.
Both comparisons remain unexecuted until the grouped parity phase.

The newest implementation batch registers input-derived comparisons for Config env-file lines without `=`, a legacy IE drive-path multipart filename, and multipart FileResponse ranges after the `content-type` header is removed. Rust now preserves the pinned filename normalization, including its UNC-path rule, and maps the missing header to `KeyError`; Config already follows the pinned ignore behavior. All comparisons remain unexecuted until grouped parity.

`QueryParams` and `FormData` now inherit the public Python `ImmutableMultiDict` facade, matching the pinned base tuples while retaining their specialized Rust stores in `_inner`. The registered input-only inspection compares both `__bases__` and `__mro__`; its execution remains deferred to the grouped parity phase. The extension stores are private implementation types, and the facade delegates mapping, representation, equality, query formatting, and form cleanup behavior to Rust.

The latest routing fix matches pinned Starlette's raw Host-header lookup: an input containing only `b"Host"` does not match `Headers.get("host")`, so Host routing follows the Router's default miss path. The Rust bridge and input-derived coverage validator now agree with the pinned source; the renamed [`router-host-header-raw-name.yaml`](../tests/fixtures/sources/parity/router-host-header-raw-name.yaml) comparison remains unexecuted until full parity.

The surrogate-route batch keeps compatibility paths as Unicode code points in Rust through construction, matching, Mount scope composition, Host/Mount reverse routing, and repr; the Rust-native `RouteTable` remains UTF-8 based. Input-only cases now cover root-path matching, converter regex extraction, slash-redirect encoding errors, compiled-pattern retention after HTTP Route, WebSocketRoute, and Mount `path` mutations, opposite-scope `matches` ordering, and WebSocket dispatch. These eleven additions remain unexecuted until full parity.

The latest full clean run, `dc8c8ca6-f2b7-449b-9f53-45860e3cad4c`, covered the preceding 1,992-case, 140-file contract and passed 2,254/2,254 profile comparisons with both fault contracts. Later @48 additions cover optional-backend behavior, WebSocket authorization, Router truthiness, BaseHTTPMiddleware iterator cancellation, response subclasses, Python-version applicability, StaticFiles OS-specific paths and NUL handling, StreamingResponse OSError mapping and await-factory exhaustion, TestClient callback decoding, BaseException and close-code behavior, WebSocket close-code forwarding, CPython custom-regex syntax, AuthenticationMiddleware iterable backend results, nested Host/Mount reverse lookup, Request body retry and interleaved iterators after `http.disconnect`, cached Request.is_disconnected() state after body/stream disconnect observations, async background-list failure short-circuiting and sync cancellation, StaticFiles subclass hooks, TestClient context-exit close behavior, and asyncio-marked TestClient ASGI3 classification on CPython 3.12. Four more input-only cases compare WebSocketEndpoint hook failures and exception context, plus bracketed IPv6 Host matching on both targets; they remain unexecuted. Fifteen more input-only cases add numeric-timezone StaticFiles handling, late background-task failure, first-send StreamingResponse disconnect, incomplete TestClient response handling, Request.stream retry after http.disconnect, WebSocketEndpoint RuntimeError finalization for a non-string ASGI message type, BaseHTTPMiddleware dispatch short-circuiting before a raising downstream route, StreamingResponse failure on its terminal send, TestClient generator-body buffering, an invalid first WebSocket event passed through accept(), FileResponse Last-Modified If-Range matching, exception-class MRO precedence when a base handler is registered first, and Request.body receive-error propagation with a retry, deferred StreamingResponse iterator acquisition after a failed response-start send, and TestClient normal return with an incomplete response. None of these later inputs have run in parity. The stateful StaticFiles PathLike, UploadFile write-error, and TestClient asyncio-marked ASGI3 inputs are authored but unexecuted. Four latest inputs cover the StaticFiles get_response subclass override, TestClient WebSocket app-error stream closure, TestClient propagation after a completed HTTP response, and StreamingResponse send backpressure; these also remain unexecuted. The lowercase Router method-mutation and out-of-range SessionMiddleware timestamp cases remain unexecuted. The three prior input-only cases cover Request.body retry after cancellation following a partial receive, empty-path root Mount dispatch, and StreamingResponse AsyncIterable descriptor failure deferred until after response.start; none has run in parity. The latest input-only cases cover BackgroundTasks live-list mutation order/error propagation, async-list cancellation, sync cancellation-then-worker-error, and StreamingResponse caller cancellation during a blocked send; these also remain unexecuted. This batch adds input-defined `BaseRoute.matches` dispatch and TestClient integer status pass-through above `u16`; their comparisons are unexecuted. It also adds a native Tower middleware workflow for layer ordering, short-circuit responses, error propagation, and unread request-body behavior; that comparison is authored but unexecuted. Two native service cases now distinguish request-body errors before response commitment from response-body errors after response start; these comparisons are also unexecuted. A BaseHTTPMiddleware case also covers returning a call_next response after closing its body iterator; its comparison remains unexecuted. The newest implementation batch adds four Request.form large-integer inputs, one StaticFiles get_directories subclass input, and two GZip integer-boundary inputs; these comparisons remain unexecuted. The newest inputs cover weekdayless StaticFiles If-Modified-Since dates, TestClient server ports above u16, and WebSocket send validation when a string-subclass hash fails; all four comparisons remain unexecuted. The deferred-phase wording and atlas count here are historical for the preceding contract; active verification is summarized at the beginning of this document. That earlier atlas snapshot had 844 source rows: 789 input mappings, 55 source-backed `not_applicable` dispositions, and zero backlog. The pinned denominators remain 514 upstream test functions and 24 documentation pages. See [`PARITY.md`](PARITY.md) for run-scoped evidence and the rest of this document for the input and implementation history. The latest unexecuted additions cover partial Request stream close and body-cache recovery, TestClient ignoring a non-string ASGI type before a completed response and suppressed app exception, and WebSocketEndpoint cancellation followed by a failing disconnect hook. This batch also adds an athrow after Request.stream() yields its terminal empty chunk, preserves a TestClient client port above u16 unchanged in the ASGI scope, and checks WebSocket.receive() with an unhashable incoming message type after connection. Two additional inputs exercise WebSocket.receive() rich-comparison and hash-error behavior for Python string subclasses; all five comparisons remain unexecuted. Earlier inputs compare the complete custom BaseHTTPMiddleware application through one client on asyncio and Trio: five ordered HTTP requests followed by a WebSocket session, with exception identity, arguments, group children, cause/context links, partial ASGI events, and thread cleanup. These exposed and fixed worker-to-portal StreamingResponse ownership, missing EndOfStream context, and asyncio streaming cancellation context in Rust. The declared normalization replaces only the hexadecimal cancel-scope address in typed asyncio CancelledError messages and arguments. Two new lifecycle inputs retain the four propagated exceptions and original tracebacks after portal shutdown, then release and collect them on the caller thread. They pass on asyncio and Trio with preserved traceback identity, all three user finalizers completed, and no unraisable errors after Rust ownership and GC traversal fixes. Active or unawaited continuations need separate comparisons. The declared AnyIO EOF normalization recognizes only the exact receiver-internal suppressed AttributeError/WouldBlock context shown to vary across identical live source inputs; it preserves EndOfStream and caller links. The preceding inputs compare the pinned composite Router graph and ten ordered requests through one managed TestClient on asyncio and Trio, including complete responses, redirect history, ASGI events, lifespan, and thread cleanup. The preceding inputs compare constructor headers without HTTP requests and middleware startup exceptions during TestClient context entry, including exception identity and thread cleanup. Earlier inputs map static and path-parameter WebSocketRoute dispatch through TestClient, alongside direct Request and WebSocket constructor scope checks. The pinned `test_router_add_websocket_route` uses a preconfigured module-level Router and does not invoke `Router.add_websocket_route`. The routing guide directs users to supply `WebSocketRoute` through `Router(routes=[...])`, and the release notes direct users from the removed decorator to that pattern; the method source candidate therefore remains `uncertain`. The Rust-backed facade constructs and appends `WebSocketRoute` in the same order as the pinned method, so this audit found no documented public gap. The preceding batch exercises URL-encoded `Request.form` field-count and part-size errors with each request body delivered in one ASGI chunk. The earlier batch maps `routing.test_partial_async_ws_endpoint`, comparing async function and bound class-method WebSocketRoute endpoints wrapped in `functools.partial` through a mounted Router. Recent parity inputs
include outer BaseHTTPMiddleware request-body transformation and replay, map the pinned WebSocket scope Mapping and identity behavior, and correct the
StaticFiles HEAD fixture to use the upstream `<file content>` asset and its
14-byte length. The upstream one-chunk URL-encoded limit test directly inspects private `FormParser` counters/messages and a 50 MiB stress bound, so that implementation-local assertion is source-backed `not_applicable`; the public `Request.form` error behavior is covered by the two live source/package inputs. Schema inputs map the pinned route graph, including missing
docstrings and mounted/hosted routes, and exercise its hidden `/schema` endpoint
through the installed ASGI application. The active fixtures also
map 11 routed protected-HTTP
authentication behaviors and six protected-WebSocket authentication behaviors
from the pinned auth tests. Four TestClient cases cover TrustedHost exact and
wildcard acceptance, invalid-host rejection, and following the HTTPS `www`
redirect. Two additional TestClient inputs cover base-URL path-prefix merging
and default redirect following through an input-defined raw ASGI path-response
map. A nested TestClient case also constructs an input-defined inner app and client inside a synchronous endpoint and observes both live request/response paths. Two new TestClient cases map HEAD through pass-through middleware and
CWD-relative StaticFiles with follow_symlink enabled. Recent additions include
direct FormData constructor/equality inputs; direct UploadFile constructor/repr, rollover, and threadpool-boundary cases; a ten-chunk 400-byte GZip streaming response using public defaults; and GZip final and
streaming responses at the configured `thread_minimum_size` boundary. Other recent
inputs compare generic `Request[State]` and
`WebSocket[State]` type contracts,
surrounding pure-ASGI ContextVar observations around BaseHTTPMiddleware and a
pure-ASGI control, concurrent BaseHTTPMiddleware background-task completion,
CORSMiddleware private-network-access denial, empty-text
default decoding in WebSocketEndpoint, TestClient lifespan task/RunVar
continuity under asyncio and Trio, lifespan task-group child lifecycle
ordering under both backends, and WebSocket URL text/components for relative
and explicit-port connections. A FileResponse async background-task case compares callback completion and ordering after response sends. A shared AnyIO thread-pool limiter input checks
the default capacity, a configured limit, shared Starlette/AnyIO consumers,
and restoration of the default. The TestClient middleware input maps `tests/test_requests.py::test_request_url_starlette_context` and captures `Request.url_for("homepage")` before routing, exercising Starlette’s app-provider fallback.
The file-like StreamingResponse input compares
newline-delimited binary body chunks through the installed Python package. It
also includes Rust-backed `CommaSeparatedStrings` parsing, sequence formatting,
quoting, Unicode
representation, Python string-subclass boundary inputs, and lone-surrogate
strings; a three-request
CORSMiddleware origin-isolation sequence and three Python-package-only direct
`run_in_threadpool` cases, including the shared AnyIO limiter, synchronous Request
endpoint worker cancellation and failure, five async Request endpoint callable
shapes and failure, ASGI callable-instance success and failure, two direct
`State` consumer sequences, `Starlette.host()` and `Starlette.mount()`
registration and dispatch, two
`Starlette.add_exception_handler`
workflows, and one URL query-parameter operations input. Seven direct QueryParams cases
map equality and blank-value behavior to `test_queryparams` and
`test_url_blank_params`. Three StaticFiles
HTML fallback scenarios cover directory index/fallback selection and missing
file exceptions. A TestClient case serves a file through a valid symlinked
StaticFiles root. Seven built-in float/UUID converter cases now observe matched
path parameter types and invalid-segment misses on both profiles. Added
default-string match and slash-boundary inputs plus int/path parameter
observations on both profiles; the routing docs now map all five built-in
converter examples to these inputs and map the separate `request.path_params`
example to its existing endpoint input. The `test_datetime_convertor` source
row now has input-only dispatch and reverse-URL cases on
the Python package; the documented custom converter example is now mapped to
the same dispatch and reverse-URL input cases. Rust owns compatibility route
ordering, method selection, capture conversion, and reverse formatting. It
calls the route's source-compiled `path_regex.match` at the Python boundary
because custom converter patterns must retain CPython `re` syntax and
semantics: CPython treats `\N{LATIN SMALL LETTER A}` as the named character
`a`, while the former Rust `fancy-regex` matcher treats `\N` as “not newline”.
The input-only custom dispatch case exercises that Python-specific escape;
converter `convert`/`to_string` methods remain boundary callbacks. The updated
inputs still await the integrated parity run. The `test_route_converters` row
now maps the five pinned request paths and all five named `Router.url_path_for`
lookups, preserving the UUID object input. The six direct
ServerErrorMiddleware inputs and three TestClient exception-
chain inputs pass live source/package comparison in the latest run. Four
exception-formatting cases now map the exact constructor inputs from
`test_http_str`, `test_http_repr`, `test_websocket_str`, and
`test_websocket_repr` to Rust-backed `str()` and `repr()` observations. Sixteen
Request.cookies inputs also pass their selected comparisons: an Okta-style
JSON-like value with duplicate and unnamed segments, all 12 active edge and
malformed parameter strings, multiple raw Cookie fields, quoted
backslash-plus-line-feed handling, and Python-package dict type/cache/mutation
behavior. The mapping probe is package-only because the
Rust-native API exposes its separate Rust `Cookies` type rather than a Python
mapping. The parameterized `test_cookies_edge_cases` and
`test_cookies_invalid` rows now map every active parameter string to an
input-only case. The sequential `test_request_cookies` flow is mapped to a
separate TestClient cookie-persistence round trip.
The authentication inputs also compare the configured custom HTTP error
response, invalid `requires` decoration, and synchronous/asynchronous redirect
dispatch, named login redirects with the `next` query value, custom `BaseUser`
property overrides, concrete `Request.user` types, and middleware-populated
`Request.auth.scopes`, while the State inventory row
links direct container operations to the existing HTTP and WebSocket
lifespan-state flow.
The authored cases span
the Starlette ASGI application and route inventory, routing and reverse URLs, URL scope/components,
Headers and MutableHeaders, requests, responses and background tasks,
async endpoint loop/task/thread ownership and cancellation, StaticFiles,
WebSockets, exceptions, status constants, endpoints,
authentication, middleware (including the default middleware-boundary trace and bounded WSGIMiddleware,
SessionMiddleware, and BaseHTTPMiddleware workflows), configuration,
schemas, one bounded Python-package Jinja2 template workflow, direct
`GZipResponder` construction and compression inputs, and invalid WebSocket
JSON-mode inputs. The latest batch adds a StaticFiles directory served through
a valid symlinked root using TestClient, an unhandled StaticFiles lookup TimeoutError captured as a TestClient 500, and middleware-configured Mount URL lookup,
handled HTTP exception responses observed through mounted middleware, ordered
StaticFiles Last-Modified requests, TestClient startup-error propagation, and
FileResponse errors for directory and missing-file paths. New authored TestClient inputs map `tests/test_routing.py::test_mount_at_root`
and `tests/test_routing.py::test_router_middleware`; the latest live parity
run passed both cases against the pinned source. The exact operation and profile
denominator is in the parity manifest; generated JSON and run results remain
ignored local build outputs. BaseHTTPMiddleware
workflows map `test_run_background_tasks_even_if_client_disconnects` and
`test_run_background_tasks_raise_exceptions`, comparing background-task
completion and exact `ValueError("TEST")` propagation through the TestClient GET
scope. The new
[`route-representations.yaml`](../tests/fixtures/sources/parity/route-representations.yaml)
input maps six pinned `Route.name` endpoint shapes and seven `Route`,
`WebSocketRoute`, `Mount`, and `Host` representation cases. All eight cases
passed source/package comparison; Mount and Host compare the complete repr
after normalizing only the child Router's process-specific object address.
The 13 corresponding upstream test rows are now mapped in the atlas; their
existing `uncertain` API dispositions remain unchanged. The new
[`route-constructor-errors.yaml`](../tests/fixtures/sources/parity/route-constructor-errors.yaml)
input maps `test_duplicated_param_names`; it observes live constructor results
for both one repeated name and multiple repeated names, and passed source/package
comparison.

A previous clean full-slice correctness preflight
`4d9a1935-b216-449f-aa60-53421675afd3` ran against Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f` and the then-active 940-case contract.
It selected 1,186 profile comparisons: 1,182 passed, zero failed, zero
infrastructure errors, and four Rust-native callable-boundary rows were
`not_run`. The installed Python package passed 936/936; Rust-native passed
246/250. Both target-only route-cache fault contracts passed (2/2) and remain
`not_applicable` to the source oracle. The result SHA-256 is
`10c37dd392b4f3433a0dceb1da7987713502e7a39c14d77b702983fe98f6b15d`; it uses
manifest SHA-256
`4539630160f3e2816d089fc0d351dc74aa73de7f0f187d4ed187e53295b5208f`, clean
target revision `c93d25a8b2e477ca689bce7b454a93b3352dd628`, target package-tree
SHA-256 `1ada9c03c40f828754761c2dfdeee90cb81ac5bbb6ed64527e462d1b84c195dc`, and
installed wheel SHA-256
`6796dece62859aa7a9cfa5739cc5e5ebcc1d0aa86f3bfbc1d27189e7cbaf622a`. These
results cover the active package slice and do not establish full Starlette
parity.

A previous clean Router/GZip benchmark run
`e8fb3ceb-f397-4f6b-99b2-1499e9861d22` measured all 74 source/package workloads:
six Router and 68 GZip. It recorded zero failures and matching normalized
observations for all 74 workloads; all 74 Rust-native workload boundaries
remain `not_run`. The correctness preflight above selected 1,186 profile
comparisons, with 1,182 passed, zero failed, zero infrastructure errors, and
four not-run rows. Median source/package latency ratios were 0.735 for Router
and 0.978 for GZip; source latency was lower in 5/6 Router and 56/68 GZip
workloads. The benchmark result SHA-256 is
`47d34ead361efddfd8f4fe846a852272c099cae00fb5b19fc08176f8670c2e5c`. These
workload-specific measurements do not establish full Starlette compatibility;
see [Benchmark mapping](BENCHMARKS.md) for timing and artifact details.

Rust owns lone-surrogate parsing and formatting through a code-point sequence;
the PyO3 boundary uses UTF-32LE with `surrogatepass` because Rust's UTF-8
`String` cannot encode unpaired surrogates. The input-only source/package
comparison covers direct parsing, sequence values, and a subclass `__repr__`
containing a lone surrogate.

The correctness-gated Router/GZip benchmark is recorded in
[Benchmark mapping](BENCHMARKS.md). The historical run above records its snapshot;
workload-specific measurements do not establish full Starlette compatibility.

The previous clean full-slice preflight `14327f2a-372b-4751-a1e4-4630740a5017` passed 974/974 Python-package comparisons, 246/250 Rust-native comparisons, and both target-only fault contracts. Four existing native Python-callable boundaries remain `not_run`, with zero failures or infrastructure errors. The target was clean at revision `f9191561cb84e9d2e270918bb025bccd96dae78c`. Result SHA-256: `5700e7bd9c678c03aaf6e62f3ed5f690f6afa5ecb91912651e9533778b23e489`; manifest SHA-256: `6cd44406888e57fa77cbfdaf26cff0ff2f723e55b63d9b6822a5010b4c5854d8`; package tree SHA-256: `8f4c85f689b289c014f9c8b38a2aed68dcc7519a28c36696c889c2d83f8f030e`, matching the earlier uncommitted full-slice run. Coverage MCP verified 2,521 additional Rust lines over the selected composite Router baseline, with passing cases and matching source/build receipts. Incremental union coverage does not assess full-suite coverage regressions. See [Parity evidence](PARITY.md) for receipts and failed-run history.

The previous clean benchmark `6e82f74a-b360-4112-8b45-012aec7924a0` measured all 74 source/package workloads with matching normalized observations and zero failures. Median source/package latency ratios were 0.747 for Router and 0.976 for GZip; source was faster in 5/6 Router and 60/68 GZip workloads. All 74 native benchmark boundaries remain `not_run`. Result SHA-256: `2fd8671c509d7d71f5361b7cf0bde37a67c9f067a96611b45819d3a3a464cc4f`. See [Benchmark mapping](BENCHMARKS.md) for the generated evidence; these are local workload measurements.

The previous clean full-slice preflight `55535731-b03c-4a49-ae6f-b8f61e10fbda` passed 976/976 Python-package comparisons, 246/250 Rust-native comparisons, and both target-only fault contracts. Four existing native Python-callable boundaries remain `not_run`, with zero failures or infrastructure errors. The target was clean at revision `8d8e48e4c5d285b41cc42d376404a6b5a11fb0f8`; package tree SHA-256 `30dff4c3a7aa8b3494efe46a5b8bac4e5520245a76786de48a157b1b2ca8a927` matches the normal selected cleanup run. Result SHA-256: `600d92f12623ebf6d535683d84c4d49ee002cd89de9c1f6bf97a8166648c4a41`; manifest SHA-256: `f1c3c3cb7ccb00c2ffa7d9e1ecdc8eca126b6fb217453a948702b6a371a18491`. Coverage MCP verified zero additional Rust lines over the selected original middleware baseline. The cleanup cases remain valuable because their added public observations detect the earlier native deallocation failures; incremental coverage does not assess full-suite regressions.

The previous clean benchmark `235c3274-3d87-494a-a9ab-62dab72158d1` measured 74/74 source/package workloads with matching normalized observations and zero failures. Median source/package latency ratios were 0.742 for Router and 0.976 for GZip; source was faster in 5/6 Router and 59/68 GZip workloads. All 74 native benchmark rows remain `not_run`. Result SHA-256: `be0e79206e67f80d85b5ea7b873a00d207b1240a9f0fb8bb60ddc9b4843299a2`. See [Benchmark mapping](BENCHMARKS.md) and [Parity evidence](PARITY.md) for current receipts and scope.

The latest source inventory check dispositioned all 999 API candidate rows.
The generated coverage matrix and fixture backlog are the source of truth for
current mapping and open-row counts; derive those changing totals from
[`coverage-matrix.csv`](atlas/coverage-matrix.csv) and
[`fixture-backlog.csv`](atlas/fixture-backlog.csv). No upstream test-function
row remains in the backlog; open rows are documentation, optional-feature,
Python-version, API-behavior, or deprecation candidates. The finished-workflow traceback-retained callback cleanup row now maps to the two passing backend inputs. The pinned denominators are 514 upstream test functions and 24 documented pages. The bundled generic Open Source auditor rejects the existing manifest extensions and generated-input layout before parsing inputs; that audit did not pass. Repository-native contract, inventory, and policy checks remain compatible. Full replacement parity is not established.

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
ASGI debug event. The 30 existing FileResponse behavior cases passed on both
profiles where selected; the added scheduling case passed on the Python
package profile. All eight SessionMiddleware cases passed on the Python package profile, and all
twenty-one BaseHTTPMiddleware workflow cases passed in that historical run. Two additional
ContextVar cases compare `call_next` context propagation with a pure-ASGI
control. The workflow cases cover header
mutation, replacement responses, body-cache replay, response-completion receive
racing, exception/context propagation (including cause, TaskGroup
`ExceptionGroup` context, and suppression-state observations), partial-stream
forwarding, caught downstream exception handling, downstream receive
transformation, repeated disconnect polling, dispatch stream consumption
followed by a downstream body read, dispatch body buffering followed by a
downstream stream read, dispatch stream reads after downstream stream/body
consumption, cached-stream replay after the downstream body read, a downstream body read
after dispatch caches the request body, and a downstream stream read after
dispatch exhausts `request.stream()`, request-disconnect checks with and
without a cached body, and async response-background-task completion. The
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
That historical contract snapshot contained 49 StaticFiles cases across five
inputs. Fifteen `lookup_path` cases ran on both profiles and all 30 comparisons
passed; all 89 StaticFiles profile comparisons passed (42 Rust-native and 47
Python-package). The package-only async-boundary case checks bound
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
tape comparisons on both targets, six projected state cases on both
targets, three package-profile route-dispatch cases, and the 16
convenience/close cases described above. Three additional package-profile
cases cover the built-in `WebSocketException` close path, an `HTTPException`
denial response, and a registered synchronous WebSocket close handler. These
map to the pinned `test_websocket_raise_*` workflows. A separate six-case,
Python-package-only input set now exercises direct `ServerErrorMiddleware`
construction, custom-handler and default-response calls, and call-time reads
after `.app`, `.handler`, or `.debug` mutation. The direct custom-handler case
maps to `tests/middleware/test_errors.py::test_handler`; the default-response
and field-mutation probes map to their pinned source behavior without claiming
additional upstream test rows. All six inputs passed in the preceding full-slice
run. The active inputs also exercise direct debug HTML, non-HTTP pass-through,
errors after response start, background-task failures, and middleware ordering;
their comparisons remain deferred with the full parity phase. Python traceback
extraction and Rust-owned error policy are described in the
[server-error boundary note](SERVER_ERROR_BOUNDARY.md). The
active TestClient contract compares fifty-four input-driven HTTP request/response
cases over forty-eight covered requirements, including exception identity and
cause/context chaining, six context-managed lifespan cases over eleven
requirements, including an input-driven Starlette async-context-manager
callback mapped to `tests/test_applications.py::test_app_async_cm_lifespan` and
`docs/lifespan.md:142-158`, and eighteen WebSocket session inputs over twenty-one
requirements, including live URL string and component reads. Those inputs cover text and binary exchange, accepted handshake
headers through `WebSocketTestSession.extra_headers`, compact JSON text
and UTF-8 binary JSON frames, streamed denial responses, concurrent JSON
receive progress while the app is blocked, disconnect exception fields,
close-triggered cancellation, app completion, portal thread cleanup, and
parsed query parameters. The two WebSocket lifecycle inputs map to
`tests/test_testclient.py::test_websocket_blocking_receive` and
`test_websocket_not_block_on_close`; their authored input and exact output
observations are described in [the parity contract](PARITY.md#testclient-websocket-blocking-receive-and-close-teardown).
The additional-header cases map to `tests/test_websockets.py::test_additional_headers`
and `test_no_additional_headers`; their live outputs preserve the accepted header
pairs and the empty list. The JSON text and binary cases are input-mapped to the documented
`WebSocketTestSession.send_json()` and `receive_json()` methods. The latest full-slice run includes eighteen WebSocket inputs; the newly added
entry-cleanup error-precedence case remains unexecuted. TestClient generator-body
buffering, lifespan re-entry, close-message errors, and explicit close reasons
remain outside that historical run; the first two now have authored inputs for
the deferred grouped parity phase.
`asgi-core.app.test_app_debug` is mapped to the TestClient input that mutates
debug after construction; direct debug-enabled construction remains a separate
documentation backlog item. The prior full-slice parity run `156f0671-69e4-4480-8072-aba3eadfa2bf` selected 1,132 comparisons: 1,128
passed with zero failures and zero infrastructure errors. The Python package
passed 891/891 comparisons; Rust-native passed 237/241, with four unsupported
callable rows marked `not_run`. The FileResponse background-task case and live
Router method-add/route-append case pass on all selected profiles. This slice does not prove full Starlette
replacement parity.
An input-only lowercase-method mutation case now checks that Router preserves
the exact spelling in a live `Route.methods` set: lowercase `get` does not
shadow a later uppercase `GET` match, and a lowercase request reaches the
mutated route. Its parity comparison is unexecuted.
The current Router/GZip source/package benchmark lane is
`completed` for all 74 declared workloads, but does not establish full
Starlette replacement parity; Rust-native remains outside those benchmark
boundaries. Ignored local results live in
`build/parity/parity-result.json` and
`build/parity/upstream-benchmark-result.json`.
These results cover the selected workflows only and do not establish full
compatibility.

### Clean full cookie ownership regression and benchmark gate

Clean commit `553a06a49d6cc24c2f74ffdb01170c7a4da19f2b` passed full preflight `72d7b8d2-508a-4d10-bf44-92a37a855cd5`: 1,740/1,740 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `e98156f566a0f6c00fa40692950b72a947e30ff80e22b2750ce223cb20a9a2c2`. Normal installed package tree: `1fe51681fa92a2f3f25650e9a2eee69a3211c3b2dc3957311eeb374b765fc666`.

Benchmark `8ece8df3-a7c2-4a44-8f1d-5cfa915e35e5` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.737 for Router and 0.980 for GZip; the source was faster in 5/6 Router and 59/68 GZip workloads. Result SHA-256: `003123ccc547becf233b63df466947cffa8ef04e25480b81120073c0c7db2230`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

## Cookie returned-value ownership and shared translation evidence

The 156 new input-only cases compare returned string lifetimes, original errors,
finalizer reentry and unraisable errors, shared translation-table mutation and
standard-library aliasing, key hash callbacks, and surrogate encoding order
across Response, HTMLResponse, PlainTextResponse and JSONResponse. Implementation
was completed before running the entire matrix, as requested. No reproduction
against the previous target is claimed for this batch.

Rust owns conversion state, validation, quoting and serialization. The Python
forwarding frame holds a GC-visible Rust object so exception tracebacks retain
converted values. This adds only object/lifetime forwarding; no runtime Python
branching, iteration, unit tests, unsafe Rust or lint weakening was added.

Full working-tree run `82b73937-71cb-40e9-b45e-a98186ed86a3` passed 1740/1740 package comparisons, 246/250 native comparisons, and both fault contracts, with zero failures or infrastructure errors. Four unsupported native callable cases remain not_run, so the full CLI returns exit status 2. This is working-tree evidence, not a clean-revision release claim. Result SHA-256: `08d58b4452fa673762e1ed9db594b8681674896083b4c6217255822325c66f85`.

Instrumented full run `fb13c949-fb6a-4ed7-8f73-b203bed180bd` retained the same counts. Coverage MCP verified 19714/25453 Rust lines with matching source/build receipts; 5739 lines remain uncovered. Instrumented tree: `7ce86e79c5fcbe1b6871925b2f91795e935b56122207fd1ce046271aeaeaf0f0`; wheel SHA-256: `c74329850c1c712d326ab3a5c4e157b12bfb64f8922de417627915cf54936474`. The LCOV report, full case receipts and MCP response remain ignored under `build/parity/coverage/response-cookie-ownership-20261005/`. This is measured line coverage for the instrumented package build; no branch coverage or regression comparison with older source is claimed.

The current contract indexes 1744 cases in 109 files: 1742 ordinary oracle
cases and two target-only fault contracts, 121 operations and 978 parity
requirements. The atlas remains 809 source rows, 694 mapped rows, 52 reasoned
not_applicable rows and 63 backlog rows. Fixed denominators remain 514 upstream
test functions and 24 documentation pages. Supplied Morsel values, further key
protocols, exception/GC cleanup after caller release, other interpreter
versions, and Streaming/File/Redirect subclass interception remain open.
Complete Starlette parity remains unproven.

The repository's strict schema/index/input and project-policy validators passed.
The bundled generic fixture audit assumes the older @2 layout and cannot ingest
this @4 manifest's fault registry and ignored build/parity inputs; its diagnostic
is retained locally and is not reported as passing evidence.


## Response attribute and header-cache evidence

The 136 new input-only consumers cover attribute interception, conditional charset reads, public header-view caching and aliasing, raw-header replacement/deletion, finalizer reentry, constructor header hooks, cookie override dispatch, and cookie conversion reentry/control characters across four documented response classes. Initial reproduction `7dc3041f-f0d7-4304-b686-50b7b5a3158b` exposed 70 divergences with 19 ordinary passes; a separate eight-case finalizer reproduction `59bb16ff-55de-45e8-9bd8-5431969adf7e` exposed eight divergences with one ordinary control pass. Both runs passed both fault contracts without infrastructure errors. The former raw-header setter held a native mutable borrow while dropping user values, so their finalizers could encounter a PyO3 borrow panic.

The facade invokes the user's constructor header hook as required calling glue. Rust selects the header cache through source-ordered user attribute accesses, forwards cookie deletion to the user's method, and reads charset only when encoding content. Public values use ordinary Python attribute storage, which preserves their dictionary presence, deletion, and finalizer callbacks without a Python semantic algorithm. Rust accesses its storage holder without invoking user attribute hooks. Cookie construction uses temporary native storage, preserves both max-age string conversion boundaries, and appends to the current public raw-header list after conversion. No runtime Python branching, loops, unsafe Rust, or unit tests were added.

Normal selection `b91ac23e-b116-43a8-be87-2a58c562d7d2` passed 570/570 ordinary comparisons and both fault contracts, including prior rendering, ASGI callback/ownership, construction-protocol, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `c43934997a80e3aae1f7d9d0dcf9acc8fd7d7255be2a171b101fb9372f2c224d`; manifest SHA-256: `7fbf5a69322f70e9f5297606adb108c907e7f4f0022cbc90ae12e054fe5f5163`; normal package tree: `f39c1c88aec7a7f3a2e60b825eaa68ba0442e07dfb2b86fdacbcb0bbce533187`.

Coverage MCP verified 10 additional Rust lines with matching source/build receipts: baseline 3,235/25,239, batch 3,041/25,239, union 3,245/25,239. Baseline `829844f5-ce76-4ca4-b1e8-3432a7063f48` passed 310 ordinary comparisons; batch `4dd9209a-7635-4bfe-8eff-2f1b49433b95` passed 137. Both passed both fault contracts. Instrumented package tree: `4772847b93f269e0ee61bf25b8a554f4dae30b4e35c2c88d3c00102ca0e15cc4`; wheel SHA-256: `03117b1709b60f9da7d572a1eecc0e03c391bbf84697242bc0cb1d97b2541b08`. Reports and receipts remain ignored under `build/parity/coverage/response-attributes-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas remains 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. The source API audit classifies `Response.init_headers` as a private/internal constructor hook: the guide documents the `Response` import, constructor, cookie methods, and `render` override, but not this method; the package root exports only `__version__`; and no upstream test or release note directly names it. The facade keeps a Rust-backed wrapper because Starlette dynamically calls `self.init_headers` during construction, and existing input-only constructor cases preserve that callback behavior. No separate public-method gap remains. Streaming/File/Redirect subclass interception and other cookie conversion/type protocols need further comparisons. Complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

## Live response ASGI callbacks and ownership evidence

The 92 new input-only consumers include 40 callback mutation/alias workflows, 32 public ownership graphs, 12 StopAsyncIteration/cancellation cases, and eight attribute-read probes. Initial reproduction `f0decca4-ccf3-4a00-9908-01ee0a315693` exposed divergences in all 72 initial inputs; its normal cache control and both fault contracts passed, with no infrastructure errors. Source messages alias raw headers and read body/background values after preceding sends. The former target copied headers, captured those values too early, and hid callback/header references from GC.

The Rust driver now reads live public values at the source lookup boundaries, performs late background selection, and forwards original callback errors. The facade only awaits the native call with its public response object. Core response headers/views and continuation-owned Python references are GC-visible; the sendable continuation closes suspended delegates when finalized on either collection thread. No runtime Python branching, loops, unsafe Rust, or unit tests were added.

Normal selected run `66ea8a21-2a9f-4b17-9546-5eb710171546` passed 302/302 ordinary comparisons and both fault contracts, including earlier response, redirect, streaming, file, and body-limit controls. All 32 new ownership inputs released user callbacks and guards, ran suspended callback finally blocks, and reported no unraisable errors. Result SHA-256: `e2338ab0c1e22d64387f7c6f44314ffa41cf146be8c76d17df167704f81fdf46`; manifest SHA-256: `20b6ee5681a27184002d35244dfbb29427d8da8091e5562d5b179d16eb0b70c2`; normal package tree: `16ed8c9e92d49c5240e6c8bda59161db80c9c3625611c16544146880249f6dd0`.

Coverage MCP verified 46 additional Rust lines on matching source/build receipts: baseline 3,206/25,052, batch 2,907/25,052, union 3,252/25,052. Baseline `b7e439b7-b76f-46fe-907b-13f6a16cb6f7` passed 86 ordinary comparisons; batch `f807cd3d-53f9-44b6-a60a-f35f80fb14ad` passed 93. Both passed both fault contracts. Instrumented package tree: `b35cb2de95ca2b21188fd9229565704d34eb1b9737e6a3117aa15b5013d25d11`; wheel SHA-256: `bd7c889cabdc7ce8313e2fc883479988ff3168e821c03a7e1289eff2a8300355`. Receipts and reports remain ignored under `build/parity/coverage/response-callback-20261005/`. This selected incremental union does not prove full-suite coverage regression status.

The generated atlas remains 809 rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. This batch adds behavior requirements within documented responses without relabeling unrelated backlog items. Fixed denominators remain 514 upstream test functions and 24 documentation pages. Complete Starlette parity remains unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full callback regression and benchmark gate

Clean commit `30becba23b568754874b17407a769c238697407f` passed full preflight `23659d68-7cc4-4e91-9134-7ab6ed4b8b19`: 1,218/1,218 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `2eec10dd17b8a4e0fb749af9a54a80ceb8b541ead7a5e1b30394c4e7488f747a`. Normal package tree `16ed8c9e92d49c5240e6c8bda59161db80c9c3625611c16544146880249f6dd0` matches the selected run.

Benchmark `b032a0d3-e787-4d23-b066-87b84086cb69` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.756 for Router and 0.975 for GZip; the source was faster in 5/6 Router and 46/68 GZip workloads. Result SHA-256: `18812538edde5287ec6ddb514f54cb07e04df01318c5935588f1abd9c09dcf24`. See [benchmark evidence](BENCHMARKS.md). Passing this active bounded contract does not establish full replacement parity.

## Response construction and rendering evidence

The 52 input-only response consumers cover documented HTML, plain-text, nested JSON, and custom JSON rendering. Live reproduction `949d28a1-4a26-4d91-b6eb-9ec5c14ca199` had 31 divergences, 22 ordinary passes, and two passing fault contracts with no infrastructure errors. It exposed PlainTextResponse class/default constructor differences, subclass charset headers, render-time status changes, and stale caller-updated ASGI status codes. Rust now selects charset headers and current call status; the Python subclasses only forward constructor and user-render calls.

Normal selection `65b6c7fe-3a99-4e86-a11d-2c5ea89da75f` passed 210/210 ordinary comparisons and both fault contracts. It includes all new inputs plus existing response/cookie, redirect, streaming, file, body-limit, and route-limit inputs. Result SHA-256: `4a8604933bccc98a6053ef29adde1aad17a7512b0f20543150ced2d70e2e61c3`; manifest SHA-256: `df764960390be4000be6f83363805c90d0ea50a384c535aeec5334099aa26420`; normal installed package tree: `ef354f63079d761d0582d1fe6896364d55bd1a394a4c6bfa2932a184148985ae`.

Coverage MCP verified 18 newly covered Rust lines with matching source/build receipts and passing live selections: baseline 3,208/24,979, batch 2,876/24,979, union 3,226/24,979. Baseline run `e962efa3-7e72-4088-adb6-449d1bbd38fc` passed 34 ordinary comparisons; batch `275a65e8-770e-469c-a285-35387ead595b` passed 53. Both passed both fault contracts. Instrumented package tree: `9cf2ae4d7eff80093ac019ff0c91b2158882a6af8f46d09c066ab7f7553ccee2`; wheel SHA-256: `14fb00f251da1f9eadac98a5482783c1ae8977fb14f61c5ed5266b33cfddbdac`. Reports and receipts remain ignored under `build/parity/coverage/response-consumer-20261005/`. This is selected incremental coverage; full-suite coverage regression status is unknown.

The generated atlas has 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Four response documentation workflows now map to live comparisons. The fixed denominators remain 514 upstream test functions and 24 documentation pages. These counts do not establish complete behavioral coverage. `Response.init_headers` is classified as a private/internal constructor hook; its callback behavior remains part of response construction. See [response rendering boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full regression and benchmark gate

Clean commit `807a41bd79f0d6f9b99a9c73f9b07449f5020880` passed preflight `a1a668eb-d8f7-43b7-9f55-e2087fb18ee1`: 1,126/1,126 Python-package and 246/250 Rust-native comparisons, plus both fault contracts. There were zero failures or infrastructure errors; four existing Rust-native comparisons remain not_run. Result SHA-256: `0bcd4afb6f07ae038d35e1475e57db9c95272dc5414f145638baac30a04d4b7c`. The installed normal package tree matches the selected run above.

Benchmark `69c5837b-24df-4708-8fee-ad27ed75049f` matched and timed all 74 source/package workloads. Native timings remain not_run for all 74. Median source/package latency ratios were 0.750 for Router and 0.967 for GZip; the source was faster in 5/6 Router and 57/68 GZip workloads. Result SHA-256: `817e7aca984eb015a7cd27fbcdd0f8b7c1e72e84842192292cd098045eae52de`. See [benchmark evidence](BENCHMARKS.md). This is the active bounded contract; complete Starlette parity remains unproven.

## FileResponse stateful PathLike boundary

Starlette retains the caller's `FileResponse.path` object and uses it at two
separate operations while serving the response: `os.stat` before response
headers are sent and `anyio.open_file` after the response-start event. A valid
`os.PathLike.__fspath__` can be stateful, so the two protocol calls may return
different paths or raise different exceptions. Converting once to a Rust
`PathBuf` would erase those Python callbacks and change which metadata and file
body the public response observes. The Rust response state therefore retains
the original Python object and requests metadata and opening at their separate
source-ordered boundaries; AnyIO performs the file operations on its worker
thread. This is Python protocol interoperability at the boundary, while Rust
owns response state and the event ordering.

The active input-only `file-response-stateful-pathlike` case supplies two
equal-length files and observes conversion count/order, worker context, the
selected response body, and opening after response-start. Its contract and
manifest entry are present, but the source/package comparison remains
unexecuted until the grouped full-parity phase. This targeted case does not
establish complete `FileResponse` parity.

A new package-only input covers `scope["method"]` as a `str` subclass whose
`upper()` override returns `HEAD` while its stored value is `GET`. The Rust
PyO3 boundary now invokes that live method before selecting the header-only
response, matching the pinned `FileResponse.__call__` dispatch. Its source/package
comparison remains deferred until the grouped full-parity phase.

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

At an earlier 60-case checkpoint, the StaticFiles inputs formed a correctness
slice. A package-only async-boundary case
checks that a bound `lookup_path` override runs on an AnyIO worker while the
event loop advances, then compares the ASGI response. Fourteen `lookup_path`
cases run on both profiles; all 28 comparisons pass. Two inputs establish that
an overlong first configured root produces the source-compatible 404 before a
later root can serve a matching asset, with both symlink settings. Two more
deny search permission on a configured root and match the 401 error under both
symlink settings. Five Python-package inputs compare constructor-time missing
root errors, deferred missing/non-directory errors, and the first successful
`check_config` call across two ASGI requests, including `config_checked` state
and event tapes. At this earlier 60-case checkpoint, Windows execution was
unverified; the two invalid-name cases have since passed in workflow
[`38892560877`](https://github.com/appunni-m/starlette-rs/actions/runs/38892560877)
with four comparisons and no failures or skipped rows. This does not establish
broader Windows filesystem parity. Stateful custom PathLike sequences and
subclass hooks beyond the input-only
`file_response` and `is_not_modified` overrides remain unproven. The active
contract now contains 83 StaticFiles cases across 21 input files. A source
audit maps all 36 upstream StaticFiles test functions to existing inputs; this
source mapping does not establish behavior beyond the declared inputs. Active
@62 parity evidence is recorded at the start of the implementation plan.
The override cases are
unexecuted and do not claim full StaticFiles parity. A new input-only case
passes a stateful `os.PathLike` root whose `__fspath__` result changes across
constructor validation and the two direct lookup conversions; it records the
source-visible call order and remains unexecuted until the full parity phase.
That case does not establish broad custom PathLike parity. Direct
`lookup_path` cases compare resolved paths,
file types, size, and modification time against the source oracle; they do not
establish complete StaticFiles parity.

## SessionMiddleware slice and boundary

The active contract includes input-only SessionMiddleware workflows for the
`python-package-cpython312` profile. They compare signed-cookie persistence and
replay, invalid-signature fallback, `max_age` expiry/default/`None` settings,
cookie name/path/SameSite/Domain/Secure attributes, access and modification
flags for direct `Session` mutations including `popitem` and in-place union,
`Vary: Cookie` behavior, clearing,
WebSocket cookie loading, lifespan pass-through, and the public `Secret` key
wrapper's redacted representation, string conversion, truth value, and signing
use. The inputs replay the earlier live `Set-Cookie` value dynamically and
contain no expected outputs. This is a bounded slice sourced from the pinned session tests
and `docs/middleware.md`; it does not establish full SessionMiddleware or
Starlette parity.

A separate input supplies a signed cookie whose future timestamp is outside
Python `datetime`'s representable range. `itsdangerous` lets that conversion
exception escape because Starlette catches only `BadSignature`; the Rust path
delegates the timestamp conversion to Python to preserve that boundary. The
comparison remains unexecuted until the full parity phase.

Another input supplies a signed cookie with a decoded 9-byte timestamp while
`max_age=None`. Starlette still calls `TimestampSigner.unsign`; ItsDangerous
2.2.0 decodes through `bytes_to_int`, which unpacks the unsigned `>Q` width, and
turns an over-8-byte value into `BadTimeSignature` before the optional age
check. Starlette catches that `BadSignature` and initializes an empty session.
The Rust decoder keeps the same 8-byte bound. This comparison remains
unexecuted until the full parity phase.

Rust owns session signing and verification, expiration, cookie response
behavior, documented `Secret` representation and truth behavior, and the
`Session` mutation state. The Rust/PyO3 value boundary calls
Python's standard-library `json.dumps` and `json.loads` to preserve the Python
JSON byte representation used by the pinned implementation. The authored
SessionMiddleware workflows compare those calls through the live source oracle.
Run `2b78c6dd-a6b3-4a96-941d-7ccec76f9518` also invokes `popitem()` and `|=` on
`request.session`, including an empty-session `KeyError`, a non-iterable union
`TypeError`, and a malformed pair sequence that partially mutates before its
`ValueError`. Source and package match on the exception class/message, session
contents, flags, absence of response events, and subsequent request state.
Starlette 1.6.0 inherits both methods from `dict`; they mutate session contents
without setting `modified`, while access through `request.session` sets
`accessed`. Rust forwards to the built-in dict operations, preserving this
behavior without Python-side branching.
The codec remains a Python-specific compatibility boundary. The public status
of `SessionMiddleware.signer` is unresolved: upstream assigns this attribute,
but the compatibility inventory has not established it as supported public API.
The installed facade does not expose ItsDangerous' signer object; ItsDangerous
remains in the isolated source-oracle environment only.

## Request connection-property mapping membership

The pinned `HTTPConnection.session`, `.auth`, and `.user` properties use the
Python membership operator on the supplied scope (`starlette/requests.py:169-186`).
Those properties are documented through `Request` in `docs/middleware.md:135`
and `docs/authentication.md:57-78`; `Request` itself is imported from
`starlette.requests` in `docs/requests.md:10`. The Rust bridge now asks Python's
membership protocol to check each scope key, preserving type-level special
method lookup and the iterable fallback for Mapping implementations. Calling
`scope.__contains__` directly could instead invoke an instance attribute and
change the presence check.

The input-only comparison in
[`request-connection-properties-mapping-membership.yaml`](../tests/fixtures/sources/parity/request-connection-properties-mapping-membership.yaml)
supplies all three values through a `collections.UserDict` with an instance
`__contains__` override returning false, then selects the documented properties
to read. Its `connection-properties` operation is part of the active manifest
and dispatches through the isolated source-oracle and installed-package
adapters. The comparison remains unexecuted until the full parity phase.

## Current denominators

`Config.__call__` now forwards through the public `get` method so Python
subclass overrides receive the same dynamic dispatch as pinned Starlette. The
Python boundary rationale and active input-only comparison are documented in
[`CONFIG_CALL_OVERRIDE_BOUNDARY.md`](CONFIG_CALL_OVERRIDE_BOUNDARY.md).

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
evidence: 564 `supported`, 435 `private/internal`, and zero `uncertain`. The
catalog's original `audit_status` field records inventory provenance; use the
merged disposition and rationale for the compatibility classification. The
root package defines only `__version__ = "1.6.0"`; it has no convenience
re-exports or `__all__`.

## Completed atlas coverage

The [`coverage matrix`](atlas/coverage-matrix.csv) contains the current
source-to-fixture mapping totals:

| Mapping | Count |
| --- | ---: |
| Upstream test functions and methods | 514 source functions; see the matrix for their mapping total |
| Documentation navigation pages | 24 |
| Shared test support modules | 4; see the matrix for downstream-use mappings |
| Existing, `not_applicable`, and backlog mappings | See the generated matrix and backlog CSVs |

The [`fixture backlog`](atlas/fixture-backlog.csv) contains no expected
outputs. Every backlog mapping has an input stimulus and observation selectors;
every `not_applicable` mapping has a concrete reason. The generated CSVs are
the current source for changing mapping counts. Runtime JSON is generated
separately under `build/parity/inputs/`. The active manifest includes
WSGIMiddleware cases, direct `build_environ` cases, a module-import deprecation
warning case, an async caller event-loop/task/thread and cancellation boundary
input, route-level request-body limit inputs, and an
application-level Router-miss 404 handler input,
post-construction `Starlette.add_route` coverage, Request.form URL-encoded
limit and multipart boundary/count/charset inputs,
one bounded native `HostPattern` port-and-capture input,
twenty-two Response background-task workflows, six
header-view and raw-pair probes, and a Router sequence that verifies live
route-method and route-list mutations across
dispatches, URL scope-construction cases, BaseHTTPMiddleware workflows and
ContextVar comparisons, Jinja2 template rendering, FileResponse behavior,
StaticFiles behavior, authentication, configuration, schema, and lifecycle
inputs in
[`config-runtime.yaml`](../tests/fixtures/sources/parity/config-runtime.yaml)
and [`schemas-runtime.yaml`](../tests/fixtures/sources/parity/schemas-runtime.yaml).
The `starlette.websockets.WebSocket.protocol-sequence`
operation contains six cases whose source, installed-package, and Rust-native
observations preserve the ordered receive/send ASGI callback tape, including
attempted sends whose callback raises. The Rust adapter uses the existing
state machine to decide callback eligibility and records only the supplied
canonical messages; it does not claim Python exception metadata or a general
Rust ASGI `WebSocket` wrapper. The `starlette.websockets.WebSocket.state-sequence` operation repeats
those six input sequences and compares action outcomes, exact error messages,
and both final state enums on source, package, and Rust-native profiles; it
does not compare payloads or Python exception metadata. The new
`starlette.websockets.WebSocket.convenience-sequence` operation compares typed
frames, action results and disconnect details, pre-accept rejection of typed
receives, input-matched text/bytes/JSON exchanges, normal async-for iterator output, async-generator API
availability/control calls, denial-response extension behavior, and final
states. A new input-only case also covers PEP 479 conversion when the typed
receive descriptor raises StopIteration on the first iterator advance; its
comparison remains unexecuted. The separate
`starlette.websockets.WebSocketClose.call-sequence` operation observes
construction defaults, mutable properties, and its ASGI close event. The six
callback-tape cases pass on both installed-package and Rust-native profiles,
and the six projected state cases also pass in Rust-native. The route operation is
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
Two newly authored `WebSocketRoute.route-dispatch` inputs cover Python equality
for a `str` subclass and direct `scope["type"]` lookup error propagation; both
remain unexecuted until the grouped parity phase.
The upstream HTTPException tests and documentation contract map to input-only
exception workflows. `test_handled_exc_after_response` now has paired inputs:
one preserves the RuntimeError and already-sent ASGI events under the default
client policy, and one records the completed 200 response returned when
`raise_server_exceptions=False`. Both inputs map to the pinned test function;
the new suppressed-exception case is authored but awaits the grouped @68 parity
phase. The remaining backlog rows are atlas mapping status, not proof that
those behaviors are absent from active inputs or untested.
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

Additional cases compare missing multipart boundaries and field names, the
default multipart field-count limit, explicitly lowered field and file limits,
and UTF-8 decoding with and without a declared charset. The URL-encoded cases
exercise default field-count and part-size limits and verify that parsing stops
before another ASGI receive. These workflows observe the direct `Request.form`
result and exception boundary; they do not capture TestClient response status
or body, so source rows requiring those selectors remain backlog.

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
confirms rollover runs outside the request thread. A new direct input injects
an `OSError` from a write after the rolled and in-memory paths have diverged,
then observes propagation and `UploadFile.size`; it remains unexecuted until
the full parity phase. Two more input-only cases exercise event-loop progress
while rollover runs on a worker and cleanup, error propagation, and size state
when rollover itself fails. Both remain unexecuted until the full parity phase;
other rollover error paths remain unproven. Separately,
the direct workflow in
[`upload-file.yaml`](../tests/fixtures/sources/parity/upload-file.yaml) maps
the pinned `test_uploadfile_rolling` case and compares direct
`UploadFile` reads, writes, seeks, rereads, and close under rolled (1-byte) and
unrolled (1024-byte) spool thresholds. It passes in the latest integrated
parity run. The worker-thread-identity and event-loop-progress boundary now has an
input-only case, but its behavior remains unverified until the full parity
phase; direct rollover parity does not close that row.

## Rust-native HostPattern matcher slice

[`host-routing-native-port.yaml`](../tests/fixtures/sources/parity/host-routing-native-port.yaml)
defines one input-only comparison: the route pattern is
`{tenant}.example.test:3600`, and the incoming header is
`Host: acme.example.test:5600`. The source and both target profiles ignore the
configured and incoming port suffixes, select the route, and expose the named
capture `tenant = "acme"` in the route scope. The capture is a string. Exact
source/package/Rust observations passed in parity run
`68a60d80-a1d1-42f6-9dc5-e888719773c8`.

The Rust-native API exports `HostPattern`, `HostPatternError`, and
`HostUrlPath` from the crate root. `HostPattern::new(pattern)` compiles one
host pattern, `match_host(host_header)` returns optional named capture pairs
in pattern order, and `format_url_path(path, host_params)` preserves the
direct Host path while formatting the host and retaining a configured port.
The input-only Host reverse-URL case selects both target profiles for this
direct branch; the source, Python package, and Rust-native observations match
in run `076ce730-4a2b-4016-8d5d-439f034af022`. Nested child lookup remains
Python-package only. This is still a bounded slice, not complete native
`Router` Host registration, ordering, or ASGI dispatch. A bracketed IPv6 Host
match input now selects both targets but has not run. Nested Host reverse-URL
lookup remains Python-package only.

## WebSocketEndpoint dispatch slice

The input-only fixtures in
[`websocket-endpoint-dispatch.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-dispatch.yaml)
and [`websocket-endpoint-disconnect-missing-code.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-disconnect-missing-code.yaml)
and [`websocket-endpoint-existing-disconnect-context.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-existing-disconnect-context.yaml)
and [`websocket-endpoint-encoding-property.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-encoding-property.yaml)
are four of thirteen indexed input files with 33 cases for the documented
`starlette.endpoints.WebSocketEndpoint` ASGI interface. They cover lifecycle
hooks, offered subprotocols, text/bytes/JSON decoding, malformed and mismatched
frames, default encoding, callback and synchronous-hook errors, invalid
encoding, cancellation, absent disconnect codes, malformed binary JSON,
unexpected message types, and a non-connect event consumed by default
`on_connect`/`accept()`. A changing Python descriptor also verifies that
ordered `encoding` lookups can select JSON after earlier unsupported values.
Every case selects the installed Python-package
profile. These @49 comparisons are authored but remain unexecuted until the
full parity phase.

The Python wrapper forwards dispatch and decoding to the Rust runtime. The
stateful descriptor boundary is documented in
[`WEBSOCKET_ENDPOINT_ENCODING_BOUNDARY.md`](WEBSOCKET_ENDPOINT_ENCODING_BOUNDARY.md).
User hooks remain Python callables invoked and awaited on Python's event loop. The
Rust-native target does not expose the Python `WebSocketEndpoint` class and
ASGI consumer interface. The new invalid-first-event case reuses the
`on-connect-error-skips-disconnect` requirement: `WebSocket.accept()` receives
the initial event before failing, while `WebSocketEndpoint.dispatch()` calls
`on_connect` before entering its finalizing block.

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

The standalone import `starlette.formparsers.MultiPartException` remains
unresolved. In pinned 1.6.0, the request and exception guides do not name this
class or document its import path, the package root exports only
`__version__`, and the API catalog records the formparsers declaration as a
source-only candidate. The optional-features API review keeps it uncertain;
its `tests/test_testclient.py:89` evidence pointer does not support this
candidate. The request-response API review classifies the separate
`starlette.requests.MultiPartException` source re-export as private/internal.
`tests/test_formparsers.py` imports the exception to assert parser and direct
`Request.form()` failure behavior, which supports that observable error
boundary but does not establish a standalone import guarantee. The pinned
release notes mention the name only in a temporary-file cleanup fix. This
package's facade forwards the exception, and its Request facade re-exports the
same object to preserve that boundary; these target imports do not establish
the upstream status. No standalone-import case or additional behavior is
justified without stronger upstream API evidence.

The deprecated `starlette.status` aliases and their replacements are:

| Deprecated name | Replacement | Compatibility detail |
| --- | --- | --- |
| `HTTP_413_REQUEST_ENTITY_TOO_LARGE` | `HTTP_413_CONTENT_TOO_LARGE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_414_REQUEST_URI_TOO_LONG` | `HTTP_414_URI_TOO_LONG` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE` | `HTTP_416_RANGE_NOT_SATISFIABLE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_422_UNPROCESSABLE_ENTITY` | `HTTP_422_UNPROCESSABLE_CONTENT` | Emits `StarletteDeprecationWarning` on access |

The pinned 1.6.0 source retains the deprecated
`starlette.concurrency.run_until_first_complete` helper. The Python package
facade forwards it to a Rust-owned task-group state machine, while AnyIO owns
backend scheduling. Four input-only cases cover first-completion cancellation,
zero callbacks, child-exception propagation, and external cancellation. The
active @62 full parity matrix exercised the profile-applicable cases and
captured the warning category, message, and location with callback and cleanup
events. Active inputs also cover the WSGI module-import warning,
generator-lifespan warnings, the `TestClient(timeout=...)` warning, and the
deprecated legacy-`httpx` fallback. These results apply to the declared cases
and do not establish parity for every deprecation path.

## Unresolved points carried into implementation

- The active API review has zero `uncertain` dispositions. Keep future
  candidates unresolved until pinned docs, source, release history, or consumer
  evidence establishes public intent; importability alone is insufficient.
- `Router.add_route` is supported: the pinned routing guide presents `Router`
  as a standalone ASGI application, and `test_add_route_to_app_after_mount`
  calls `Router.add_route` after mounting it and observes the added route. Its
  facade annotation matches the pinned `Collection[str] | None` source type.
- `Router.add_websocket_route` is classified private/internal: the guide
  directs consumers to provide `WebSocketRoute` objects in the route table,
  and the similarly named upstream test dispatches a preconfigured route
  without calling this method. The facade behavior remains source-backed, but
  this convenience helper is not part of the documented compatibility API.
- Jinja2 has no declared minimum version although templating selects between
  context decorator names; see `optional.jinja2-version-compatibility`.
- The pinned GZip source has a comment proposing a future singular name, but
  Starlette 1.6.0 exports and uses the plural
  `DEFAULT_EXCLUDED_CONTENT_TYPES`. The compatibility facade preserves that
  pinned public name; see `middleware.alias.gzip-exclusion-constant`.
- `GZipResponder` is upstream-internal machinery with a direct upstream test
  import. The compatibility package now forwards construction and ASGI calls
  through Rust, with exact input coverage for exclusion normalization and
  direct compression without negotiation. Its remaining internal attributes
  and methods stay outside the documented public compatibility surface.
- The docs label async Jinja2 context processors unsupported. The pinned
  implementation calls processors synchronously and passes their return value
  to `context.update` (pinned `starlette/templating.py:145-146`). An async
  processor therefore yields a coroutine that is not awaited, raises
  `TypeError` during the merge, and produces a 500 response through TestClient.
  The input-only case
  `starlette.templating.Jinja2Templates.template-public-workflow.docs-async-context-processor-unsupported`
  records that outcome and passed against the source and package on CPython
  3.10–3.14 in the active @66 matrix. The matrix predates the later isolated
  await-boundary optimization; see [parity status](PARITY.md).

These source-backed caveats and targeted inputs do not create fixture backlog.
The post-fix active @66 matrix had no mismatches or infrastructure errors; its
aggregate remains not_proven because macOS source-skipped one surrogateescape
filename case, leaving two target rows not run in each profile. All six active
coverage plans and the 74 source/package benchmark workloads completed. Their
limits are recorded above and in the implementation ledger. Previous @64
results are historical and do not establish behavior for @66.

The macOS arm64 Python package qualification is complete, and its SBOM
metadata normalization is verified for direct and sdist-based CPython 3.12
wheels. The
two Windows StaticFiles invalid-name cases passed in workflow
[`38892560877`](https://github.com/appunni-m/starlette-rs/actions/runs/38892560877);
broader Windows behavior remains unproven. After any new runtime implementation
batch and its input authoring are complete, run the grouped phases together as
specified in the execution ledger.
The active contract and generated atlas links above carry the current case and
backlog inventory; this document does not duplicate their changing totals.

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
fixture/documentation atlas against the same pinned checkout. The manually
dispatched `.github/workflows/parity-coverage.yml` workflow runs `make test`,
which checks the atlas before behavioral comparisons.

### Unresolved TestClient implementation-state candidate

The pinned `TestClient.portal` attribute appears only in its implementation
(`starlette/testclient.py:380,681-685`); the pinned docs and tests contain no
consumer reference. Its public status remains unresolved. Public lifespan
parity inputs observe the user application's recorded thread and exception
propagation rather than requiring this implementation-state attribute.

## Previous clean full verification

The full preflight `7945194a-1060-4426-861c-abcc72183905` passed
993/993 installed Python-package comparisons and
246/250 Rust-native comparisons,
with 4 existing native Python-callable
rows not run. Both target-only fault contracts passed. There were no failures
or infrastructure errors. The package was clean at `bc54da45849ca372121b8318041ffbc81048aec1`,
with package tree `d94f40a6bc973e4b93976c946b0b59cd01cad9589a4fb74dc9460de9039c0f01` matching the normal selected
lifecycle verification. Preflight SHA-256: `bcf2b5762333286eb60ed818d5f2c4a0a812046b4e3e1116e577bdf89c2c54db`.

Benchmark `bd78f693-7562-4384-9636-f1e66a3aa3e7` measured all 74 Router/GZip source/package
workloads with matching correctness observations. All 74 native timing
boundaries remain not run. Benchmark SHA-256: `a7afc4bf807524411635aa80dee6e90fc4984077d0e90bd92d60607fb04106fe`. See
[Benchmark mapping](BENCHMARKS.md) for latency ratios and limitations.

After the previous Request lifetime batch, the atlas contained 808 source rows, 689 fixture mappings, 52 source-backed not-applicable rows, and 67 backlog rows. The Request lifetime row mapped to its 17 new inputs. Coverage MCP verified 223 newly covered Rust lines in a selected incremental measurement; it does not establish full-suite coverage. Full replacement parity remains incomplete.

## Previous clean full verification after public value ownership fixes

The full preflight `b52b86ac-b202-4875-a6cb-8940055c133f` passed
1038/1038 installed Python-package comparisons and
246/250 Rust-native comparisons.
The 4 existing native Python-callable rows remain `not_run`.
All 2 target-only fault contracts passed, with zero failures or
infrastructure errors. The package was clean at `7c02f8540081096a642e7a1528e0919973a8c355`,
with package tree `b4d91d5491a21df1a3fc8796f2bc4033f421c7add407b26f6fa7156088f3a907` matching the normal selected
ownership verification. Preflight SHA-256: `ea90512b5d2e5b737b07ea772ff651c12505c3a6738acfcfabe9b7ddb95d349c`.
Manifest SHA-256: `96ae44c8fd64cac75901685765befc8861e88cb19e47296b05fad12bfaf01cfa`.

Benchmark `839bb33d-b9e8-4f26-84a0-f9dcd1836bb4` measured all
74 Router/GZip source/package workloads with
matching correctness observations. All 74
native timing boundaries remain `not_run`. Median source/package latency
ratios were 0.736 for Router and 0.975
for GZip; source was faster in 5/6
Router and 57/68 GZip workloads.
These are local workload measurements. Benchmark SHA-256: `3c52d488e8e57e6454dc54d8518f78ac0b3d258efc6ff927e3280330f8853890`.
See [Benchmark mapping](BENCHMARKS.md) for the generated evidence and limitations.

The current atlas contains 856 source rows, 802 fixture mappings, 54 source-backed not-applicable rows, and zero backlog rows. The new public-value row and expanded Request lifetime row account for 49 new inputs. Coverage MCP verified 217 newly covered Rust lines in a selected incremental measurement. Full-suite coverage and full replacement parity remain unproven; the denominators remain 514 upstream test functions and 24 documented pages.

## Previous clean full verification after UploadFile callback ordering fix

The full preflight `524d9fa2-6a78-46d1-94d1-22a936d05696` passed
1042/1042 installed Python-package comparisons and
246/250 Rust-native comparisons.
The 4 existing native Python-callable rows remain `not_run`.
All 2 target-only fault contracts passed, with zero failures or
infrastructure errors. The package was clean at `d0769b005ce12dce2c8fce5945800a42a3810960`,
with package tree `9e63ddf110e4a78a06bfed9af5549e44ea9196d03426a67bc8c4dc8f99553212` matching the normal selected
ownership verification. Preflight SHA-256: `86a6c9787daf1d2a8efbf8fe66f8132b6473391e97cb9e936fd3ac5aaa1de419`.
Manifest SHA-256: `0cb576784769991cf4429d31917f4665ee185ac7be73d3da9bee13c0cb3e31bf`.

Benchmark `316bf275-fb2e-4bad-9e79-d85334b22755` measured all
74 Router/GZip source/package workloads with
matching correctness observations. All 74
native timing boundaries remain `not_run`. Median source/package latency
ratios were 0.744 for Router and 0.975
for GZip; source was faster in 5/6
Router and 56/68 GZip workloads.
These are local workload measurements. Benchmark SHA-256: `0172bbd458c5647b155d93a365ab4148f7f41c988e38f3cb5d4dff44efc23d07`.
See [Benchmark mapping](BENCHMARKS.md) for the generated evidence and limitations.

The current atlas contains 856 source rows, 802 fixture mappings, 54 source-backed not-applicable rows, and zero backlog rows. The previous Request/value lifetime additions totaled 49 inputs. Coverage MCP verified 7 additional Rust lines for callback replacement in a selected incremental measurement. Full-suite coverage and full replacement parity remain unproven; the denominators remain 514 upstream test functions and 24 documented pages.

## Clean full verification after in-place arithmetic and worker cancellation

The full preflight `4c10c332-8142-4547-b03c-8e87b609355b` passed
1074/1074 installed Python-package comparisons and
246/250 Rust-native comparisons.
The 4 existing native Python-callable rows remain `not_run`.
All 2 target-only fault contracts passed, with zero failures or
infrastructure errors. The package was clean at `5f26aeeffc898ca63b9522c55bbc47f22259ffb2`,
with package tree `6fd042132fec89afac089aca463dc2802844f176daf091ba64bea8d06700848d` matching the normal selected
ownership verification. Preflight SHA-256: `9671d15e0a7d2b66c36c4181fcb17ae72eb89a2b4779c41dc57bc3debfa3425a`.
Manifest SHA-256: `89f1e5ee698bd4294c7748bc444e858eecea2f20cfa530be317b0faf23cf1384`.

Benchmark `560763f1-3514-4f26-99a7-74b39947d524` measured all
74 Router/GZip source/package workloads with
matching correctness observations. All 74
native timing boundaries remain `not_run`. Median source/package latency
ratios were 0.730 for Router and 0.968
for GZip; source was faster in 5/6
Router and 63/68 GZip workloads.
These are local workload measurements. Benchmark SHA-256: `eb6697dfa11fc7d5d4288ce9f74eaf157510de4979d81b7825fafee7314a51b9`.
See [Benchmark mapping](BENCHMARKS.md) for the generated evidence and limitations.

At the historical checkpoint associated with this batch, the generated atlas
contained 864 source rows, 808 input mappings, 56 source-backed
`not_applicable` rows, and zero backlog rows. The batch added lone-surrogate
schema converter handling, SessionMiddleware Python equality for response-start
message types, and Rust-backed TestClient lifespan methods. Those inputs were
registered at that checkpoint; this historical note does not establish their
execution status on the active @68 manifest. Current atlas totals are recorded
at the top of this inventory and in the generated CSVs. Full replacement parity
and current-source coverage remain unproven; the denominators remain 514
upstream test functions and 24 documented pages.
