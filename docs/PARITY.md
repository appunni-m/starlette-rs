# Migration parity contract and evidence

The active input contract is [`tests/fixtures/manifest.yaml`](../tests/fixtures/manifest.yaml), using `migration-parity/manifest@4`, `scope.mode: slice`, and `parity-input@45` authored definitions. It contains 1800 input-only cases in 111 indexed files (1798 oracle parity cases and two target-only fault contracts), covering 124 operations and 990 parity requirements. The newest 56 response-variant/template-protocol cases are authored but unexecuted. Implementation continues across all feature families before full parity, then coverage, then all benchmarks. Earlier run records below apply to their recorded revisions and inputs; they do not validate this implementation checkpoint. Recent inputs compare async function and bound class-method Route and WebSocketRoute endpoints wrapped in functools.partial through TestClient, standard and unknown numeric HTTP response reason phrases through TestClient, HEAD-response body suppression through pass-through BaseHTTPMiddleware, CWD-relative StaticFiles with follow_symlink=True, StaticFiles directory handling when the root is a pathlib.Path, and propagation of a StaticFiles lookup TimeoutError into TestClient’s 500 response, Router lifespan state propagation plus startup- and shutdown-error propagation through TestClient, two URL-encoded Request.form limit cases with one input body chunk, direct Request/WebSocket constructor scope validation, two TestClient Router WebSocketRoute matching cases for /ws and /ws/{room}, TestClient raw_path/query_string separation when params are supplied, and TestClient cookie-domain matching over testserver, testserver.local, localhost, and example.com. Recent additions include source-shaped TestClient requests for TrustedHost exact-host acceptance, wildcard-subdomain acceptance, invalid-host rejection, HTTPS `www` redirect following, base-URL path-prefix merging, redirect following through an input-defined ASGI path-response map, and construction of an inner TestClient inside a synchronous endpoint; custom HTTP authentication-error responses, invalid `requires` decoration, synchronous and asynchronous redirect flows, direct `State` plus lifespan-state observations, route-local handling of HTTP exceptions before mounted middleware unwinds, and direct FormData constructor/equality inputs; direct `UploadFile` constructor/repr, spooled-file rollover, and threadpool-boundary cases across rolled and in-memory thresholds; a pinned GZip streaming-response case with ten input-defined 400-byte chunks and public defaults; GZip final-response and streaming-body cases at the configured `thread_minimum_size` boundary; an input-derived AnyIO thread-pool limiter case; generic `Request[State]` and `WebSocket[State]` type contracts; app-state attributes read through `request.app.state`; default string-converter match and slash-boundary cases; expanded route-scope path-parameter observations for string/int/path converters; input-defined datetime converter dispatch and reverse URL formatting; seven QueryParams cases; seven built-in float/UUID converter cases; three StaticFiles HTML fallback scenarios; a StaticFiles directory served through a valid symlinked root using TestClient; a middleware-configured Mount URL lookup; ordered StaticFiles `If-Modified-Since` requests; TestClient lifespan startup-error and missing-scope-state cases; TestClient WebSocket accepted-header observations and URL string/component observations for relative and explicit-port URLs; pre-accept WebSocket `receive_text`, `receive_bytes`, and `receive_json` comparisons; exact text, binary, and JSON send/receive exchanges; an input-defined WebSocket `client_state` reset followed by an invalid receive; WebSocket header observations for ordered repeated values, case-varied lookups, and immutable assignment; input-defined WebSocket duplicate-close, connected invalid-send/invalid-receive, and send-callback `OSError` disconnect comparisons; CORSMiddleware private-network-access denial; an empty-text WebSocketEndpoint default-decoding failure; TestClient lifespan task/RunVar continuity and task-group child lifecycle under asyncio and Trio; surrounding pure-ASGI ContextVar observations for BaseHTTPMiddleware and its pure-ASGI control; BaseHTTPMiddleware exception propagation without a chain, through implicit context, and through an explicit cause; and BaseHTTPMiddleware response-background-task completion and failure propagation, including two concurrent direct ASGI calls, async context-manager cleanup after response completion; mutable StreamingResponse status assignment; and ten-layer client-disconnect ordering and middleware background-task lifecycle; a new Starlette application case checks synchronous error-handler invocation after a response background task fails; a status-module case captures the deprecation warning callsite. Existing inputs cover file-like StreamingResponse chunk boundaries, Rust-backed `CommaSeparatedStrings` including lone-surrogate input; `iterate_in_threadpool` and `run_until_first_complete`; StaticFiles configuration and conditional responses; CORSMiddleware origin-isolation and wildcard-without-credentials; Request.cookies edge, invalid, and mapping cases; WebSocket denial and close transitions; direct `GZipResponder`; and broad application, request, response, middleware, and routing boundaries. Recent additions include routed authentication user-interface and protected HTTP routes covering async/sync functions, HTTPEndpoint, injection-wrapped endpoints, and malformed Basic credentials; three documentation-derived BasicAuth inputs cover a wrong scheme, malformed base64, and non-ASCII credentials; six protected WebSocket cases cover plain and injection-wrapped endpoints with absent, malformed, and valid Basic credentials; authentication observations compare custom `BaseUser` overrides, concrete `Request.user` types, middleware-populated `Request.auth.scopes`, and the documented login `next` query redirect; an app-level multipart upload through `Request.form()` under the body limit; and module-global `starlette.config.environ` mutation and Config lookup behavior, plus custom `HTTPException` header forwarding, both built-in and registered `WebSocketException` close policies, and a direct WebSocket constructor signature comparison. A new FileResponse case checks that the input-defined async background task runs after response events and produces `6, 7, 8, 9`. The new literal GET `/func` Router case maps `test_router_add_route` to dispatch behavior; that upstream test never calls `Router.add_route`. New TestClient inputs map `test_mount_at_root` to GET `/` against a root `Mount`, and `test_router_middleware` to GET `/` through a Router-level middleware response; both inputs passed live source/package comparison in run `89f3c4b9-6b92-4631-964e-cdeecdb480e9`, recorded below.

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


## Cookie argument conversion and serialization evidence

The 98 input-only consumers exercise original cookie value/attribute conversions, empty-value equality, string subclass formatting and translation, flag truth testing, integer subclasses, original callback errors, and reentry through documented cookie methods. Initial reproduction `44098d49-02ee-427d-958a-7230be0470ac` exposed 78 divergences in the first 81 new inputs, with 4 ordinary passes including the control and both fault contracts passing, without infrastructure errors. A fixed input clock makes deletion/integer expiry deterministic on both sides; outputs remain live and exact.

Rust now retains Python argument objects through source-ordered assignment and deferred serialization, selects cookie attributes and quoting, and invokes the active interpreter's value representation protocols. CPython compiles literal string pairs into str conversion followed by its format protocol, which matters when a string subclass returns itself. Raw-header append selection follows those conversions. User callbacks run without a native response borrow. The runtime Python facade is unchanged; no Python branching, loops, unsafe Rust, or unit tests were added.

Normal selection `8a4bc151-3147-4c94-8f90-c5b1677ac7cc` passed 668/668 ordinary comparisons and both fault contracts, with no failures or infrastructure errors. It includes previous rendering, attribute/cache, ASGI ownership, construction-protocol, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `ccec1f895844b0fd0acb4fe83f943162d8b4149d7d09d3778f5f9f41bfa45a01`; manifest SHA-256: `da6c7d67fb4ce2b49d0b10bcd4ec63db451e67863c5e9d9927b2914f422c6c4b`; normal installed package tree: `0d606843ce84425833aa38790784a5fef20173dfc6fa8837587e03fe2161eba4`.

Coverage MCP verified 20 additional Rust lines with matching source/build receipts: baseline 3,231/25,392, batch 3,004/25,392, union 3,251/25,392. Baseline `4bd2dded-21df-4ea4-9841-ee693de53c0b` passed 446 ordinary comparisons; batch `096e641a-e283-4033-af86-a6c5d005b58f` passed 99. Both passed both fault contracts. Instrumented package tree: `a52ae84285111153f866ef4a64d50a93cdc81ec920911c707c889275a0254bb9`; wheel SHA-256: `331c3aa4de2fd664057a7ff942fc2f4bcf399a97568ca7bea445bfbd79940778`. Reports and receipts remain ignored under `build/parity/coverage/response-cookie-protocols-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas remains 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. Arbitrary cookie key objects, supplied Morsel values, other interpreter versions, and Streaming/File/Redirect subclass interception need further comparisons. `Response.init_headers` remains uncertain. Complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full cookie regression and benchmark gate

Clean commit `e83cb743223ca332e3650713424ff79225e1d33d` passed full preflight `95c16ff3-05c1-478b-a759-2a97f5d7dd6f`: 1,584/1,584 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `7d2db21ccbefcd7f0971ea239cb2d7f0a4e36d44e0b722f5c9d81c6ed207d90d`. Normal package tree `0d606843ce84425833aa38790784a5fef20173dfc6fa8837587e03fe2161eba4` matches the selected run.

Benchmark `7b617ac7-8af2-42c5-8d52-4c0a9e8aac78` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.771 for Router and 0.979 for GZip; the source was faster in 5/6 Router and 45/68 GZip workloads. Result SHA-256: `b0f666021fd4a6056787f76fd5193a0fe56e90998fba2474aee9372edd0d9fa9`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

## Response attribute and header-cache evidence

The 136 new input-only consumers cover attribute interception, conditional charset reads, public header-view caching and aliasing, raw-header replacement/deletion, finalizer reentry, constructor header hooks, cookie override dispatch, and cookie conversion reentry/control characters across four documented response classes. Initial reproduction `7dc3041f-f0d7-4304-b686-50b7b5a3158b` exposed 70 divergences with 19 ordinary passes; a separate eight-case finalizer reproduction `59bb16ff-55de-45e8-9bd8-5431969adf7e` exposed eight divergences with one ordinary control pass. Both runs passed both fault contracts without infrastructure errors. The former raw-header setter held a native mutable borrow while dropping user values, so their finalizers could encounter a PyO3 borrow panic.

The facade invokes the user's constructor header hook as required calling glue. Rust selects the header cache through source-ordered user attribute accesses, forwards cookie deletion to the user's method, and reads charset only when encoding content. Public values use ordinary Python attribute storage, which preserves their dictionary presence, deletion, and finalizer callbacks without a Python semantic algorithm. Rust accesses its storage holder without invoking user attribute hooks. Cookie construction uses temporary native storage, preserves both max-age string conversion boundaries, and appends to the current public raw-header list after conversion. No runtime Python branching, loops, unsafe Rust, or unit tests were added.

Normal selection `b91ac23e-b116-43a8-be87-2a58c562d7d2` passed 570/570 ordinary comparisons and both fault contracts, including prior rendering, ASGI callback/ownership, construction-protocol, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `c43934997a80e3aae1f7d9d0dcf9acc8fd7d7255be2a171b101fb9372f2c224d`; manifest SHA-256: `7fbf5a69322f70e9f5297606adb108c907e7f4f0022cbc90ae12e054fe5f5163`; normal package tree: `f39c1c88aec7a7f3a2e60b825eaa68ba0442e07dfb2b86fdacbcb0bbce533187`.

Coverage MCP verified 10 additional Rust lines with matching source/build receipts: baseline 3,235/25,239, batch 3,041/25,239, union 3,245/25,239. Baseline `829844f5-ce76-4ca4-b1e8-3432a7063f48` passed 310 ordinary comparisons; batch `4dd9209a-7635-4bfe-8eff-2f1b49433b95` passed 137. Both passed both fault contracts. Instrumented package tree: `4772847b93f269e0ee61bf25b8a554f4dae30b4e35c2c88d3c00102ca0e15cc4`; wheel SHA-256: `03117b1709b60f9da7d572a1eecc0e03c391bbf84697242bc0cb1d97b2541b08`. Reports and receipts remain ignored under `build/parity/coverage/response-attributes-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas remains 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. `Response.init_headers` remains uncertain; forwarding the constructor hook does not establish its public status. Streaming/File/Redirect subclass interception and other cookie conversion/type protocols need further comparisons. Complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full attribute regression and benchmark gate

Clean commit `09191fd4968b0d309bb336c0f693aeb0cd606d4e` passed full preflight `8eb08944-aa22-4802-9913-760667c7e4bb`: 1,486/1,486 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `177bab1dd7bec1b19687a4c1dfe0be91ede4f0d66636b5f12fdbe776a1331335`. Normal package tree `f39c1c88aec7a7f3a2e60b825eaa68ba0442e07dfb2b86fdacbcb0bbce533187` matches the selected run.

Benchmark `4d4c57cc-1dfb-4c01-b644-f8b07c4a08bb` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.759 for Router and 0.975 for GZip; the source was faster in 5/6 Router and 54/68 GZip workloads. Result SHA-256: `f529e5553e5c4982a1ba8c86358b42769d678ed32e52681b8d6380e19e9e38fc`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

## Constructor body and header protocol evidence

The 132 new input-only consumers exposed 104 divergences in live reproduction `37afc253-71e1-47df-8fbb-08e0400f4f18`. Its 29 ordinary passes and both fault contracts passed with no infrastructure errors. The target previously measured copied body bytes, converted header/media text too early, and created its core after user rendering. This lost Python length/method protocols, live callback mutations, original encoding errors, and render-time header/cache access.

Rust now initializes storage before user rendering, constructs headers through the source-ordered Python protocols, selects length from Python `len(body)` and live status, and retains an explicit media object. Header construction finishes before replacing raw headers and preserves an existing cached view. Python only forwards these calls and declares weak-reference support. No runtime Python branching, loops, unsafe Rust, or unit tests were added. Native rendered-byte constructors retain their additive API.

Normal selection `6de84f15-3fb2-489a-8bd8-d06195f65d6b` passed 434/434 ordinary comparisons and both fault contracts, including prior response rendering, ASGI callbacks/ownership, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `0c49d90b972fc5976fb987811ea02bbf614b506a91a4222b1801d7afbf303c1f`; manifest SHA-256: `67732db6d1e68d7c2ebce213cb3dc9cf8510de5488f628c6f6625390bfe35f6d`; normal package tree: `29cbc8f9b188bc02383d451aea70605502ff577ca12eadb3956dd134cc0d7170`.

Coverage MCP verified 27 additional Rust lines with matching source/build receipts: baseline 3,278/25,179, batch 2,882/25,179, union 3,305/25,179. Baseline `a971621e-957e-4366-a602-6c8a7c476478` passed 178 ordinary comparisons; batch `b24af4a4-8bea-467a-b4bf-5c78c3144cf9` passed 133. Both passed both fault contracts. Instrumented package tree: `4a5c520948883a92183b654d412c3e35b3aa61124f087dd2de1b8c26d830f2ab`; wheel SHA-256: `40d05a57c4a2c49b5fb4b9a9a67c52a946997b709947fad5e453ce5ee8826367`. Reports/receipts remain ignored under `build/parity/coverage/response-construction-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas has 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. `Response.init_headers` remains uncertain; complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full constructor regression and benchmark gate

Clean commit `fb0210c6c0a0ecc67572c0b491641fcc9e896de9` passed full preflight `bc712157-2daf-43d4-950a-67ed70028b2d`: 1,350/1,350 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `c40cd486bb5091c5ba322c8ef8fdca8c04904bbc37958bdfc0622b816119a486`. Normal package tree `29cbc8f9b188bc02383d451aea70605502ff577ca12eadb3956dd134cc0d7170` matches the selected run.

Benchmark `fab7a6a6-da8c-4f06-8c24-860ae83438dc` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.766 for Router and 0.959 for GZip; the source was faster in 5/6 Router and 59/68 GZip workloads. Result SHA-256: `32287fc2e00e5486444af0a583d2d9e1210f6938d86c1dfecfff64fb8cd6c980`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

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

The generated atlas has 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Four response documentation workflows now map to live comparisons. The fixed denominators remain 514 upstream test functions and 24 documentation pages. These counts do not establish complete behavioral coverage. `Response.init_headers` remains uncertain. See [response rendering boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full regression and benchmark gate

Clean commit `807a41bd79f0d6f9b99a9c73f9b07449f5020880` passed preflight `a1a668eb-d8f7-43b7-9f55-e2087fb18ee1`: 1,126/1,126 Python-package and 246/250 Rust-native comparisons, plus both fault contracts. There were zero failures or infrastructure errors; four existing Rust-native comparisons remain not_run. Result SHA-256: `0bcd4afb6f07ae038d35e1475e57db9c95272dc5414f145638baac30a04d4b7c`. The installed normal package tree matches the selected run above.

Benchmark `69c5837b-24df-4708-8fee-ad27ed75049f` matched and timed all 74 source/package workloads. Native timings remain not_run for all 74. Median source/package latency ratios were 0.750 for Router and 0.967 for GZip; the source was faster in 5/6 Router and 57/68 GZip workloads. Result SHA-256: `817e7aca984eb015a7cd27fbcdd0f8b7c1e72e84842192292cd098045eae52de`. See [benchmark evidence](BENCHMARKS.md). This is the active bounded contract; complete Starlette parity remains unproven.

## Target-only fault-contract cases

[`fault-contracts.yaml`](../tests/fixtures/sources/parity/fault-contracts.yaml) contains two input-only route-cache mutex-poison cases. One checks TestClient's public HTTP 500 response when `raise_server_exceptions=False`; the other checks propagation of the injected failure when it is `True`. The injection is compiled only with the `fault-contract` feature. Both cases declare `oracle_applicability: not_applicable` because the poisoned Rust mutex is target-internal state with no upstream Starlette equivalent. The incremental public-client runs and current full-slice run below each passed both contracts.

## Latest incremental batch: traceback-retained callback cleanup

[`testclient-traceback-cleanup.yaml`](../tests/fixtures/sources/parity/testclient-traceback-cleanup.yaml) adds input-only asyncio and Trio workflows that retain the four propagated exceptions and their original public tracebacks after all portal threads stop. The consumer disables automatic GC, collects with input-defined generation arguments while retained, releases its references, and collects again on the caller thread. User-owned locals in the raising endpoints and faulty stream record finalizer completion/thread. Every unraisable error is observed through sys.unraisablehook without filtering; exceptions and tracebacks are never cleared or rewritten. User finalizer completions are sorted without discarding duplicates because GC finalizer order is not portable.

Reproduction run `f0845b55-6feb-4025-9d57-ac7ae32637a4` exposed four native callback deallocation errors under each backend. Partial-fix run `17c1bcec-12fd-4818-b325-7a07a6297960` removed the call-next errors and exposed the outer server-error sender. Those results remain under ignored `build/parity/testclient-traceback-reproduction-result.json` and `build/parity/testclient-traceback-partial-fix-result.json`. Shared Python references now use GC-visible PyO3 state nodes with one traversal edge per owned reference. Exception response-start flags use atomics, server-error policy state uses synchronized native ownership, and converted continuations use compiler-checked Send/Sync drivers. Python runtime facades were not changed; see [TestClient runtime boundary](TESTCLIENT_BOUNDARY.md).

Normal selected run `69b6022c-209b-4e43-8595-a867b2f88419` passed all five source/package comparisons (the two new workflows, two original middleware controls, and cache control) and both target-only fault contracts, with zero failures, infrastructure errors, or not-run rows. The four original traceback identities are preserved while retained, none of the three user locals are finalized before release, and all three finalize on the caller thread afterward with no unraisable errors on either implementation. Result SHA-256: `ba8e4e0c991f31c775b65615bab6ed15f4dee3c50b5a9a9ce8ae6457982be04d`; manifest SHA-256: `1b1a4759ee2f0257a2d25da6d135bfae5de2ed15447bdbe0707edd1ba82d749e`; package tree SHA-256: `30dff4c3a7aa8b3494efe46a5b8bac4e5520245a76786de48a157b1b2ca8a927`; installed wheel SHA-256: `b80798f79942107cf8a19815a60a6d40082f1d57aa7eb8dbcd68927f26763635`. This selected run measured the uncommitted worktree.

Coverage MCP compared the two original middleware workflows and cache control (`96a1ef5e-2ecd-4d63-b42c-8ef5b937fd8d`: 3/3) with the two cleanup workflows and the same control (`b6205cc0-f7cb-4111-97d0-c9d4d36d23e7`: 3/3). Both runs also passed both fault contracts. Matching source/build receipts verified zero new Rust lines: baseline 5,581/24,663, batch 5,565/24,663, and union 5,581/24,663. Status: `no_gain`. The cases are retained for their demonstrated regression value: earlier observations executed these lines without checking native deallocation errors. Selected-test absences are not regressions, and this incremental union does not assess full-suite regressions.

Reports, receipts, and the MCP comparison remain under ignored `build/parity/coverage/testclient-traceback-20261005/`. They bind to manifest SHA-256 `f1c3c3cb7ccb00c2ffa7d9e1ecdc8eca126b6fb217453a948702b6a371a18491`, instrumented package tree `320a63207109a9fb7dbb8af8ab94e3acf3f8b0f0c04b58e8e41a06cfb7c5603b`, and instrumented wheel SHA-256 `d6f058a718587cb38b681326c8ebc5ddc0c5033ff28cdda7810d658549a4113d`.

The same pinned-source Trio input was repeated 24 times: queued EOF carried the exact receiver-internal suppressed AttributeError/WouldBlock context 16 times, and immediate EOF had no context eight times. Raw outcomes and source/input identity remain in ignored `build/parity/testclient-traceback-oracle-repeats.json`. The separate declared `anyio-memory-stream-eof-context` normalization recognizes only that full internal chain and canonicalizes its scheduling-dependent context and suppression flag. EndOfStream, its caller's cause/context link, user exception chains, and all unraisable observations remain exact. The existing cancel-scope address normalization is a separate step. Recomparison of historical live failures still rejects the missing EndOfStream link and native cleanup errors; the audit is retained under ignored `build/parity/testclient-traceback-normalization-audit.json`.

The generated atlas now has 807 rows: 688 input mappings, 52 reasoned not_applicable rows, and 67 backlog rows. The traceback-retention row maps to these passing inputs. The pinned denominators remain 514 upstream test functions and 24 documented pages; full replacement parity is not established.

## Previous incremental batch: custom middleware HTTP and WebSocket sequence

[`testclient-middleware.yaml`](../tests/fixtures/sources/parity/testclient-middleware.yaml) adds two input-only workflows for the pinned `tests/middleware/test_base.py::test_custom_middleware`, on asyncio and Trio. Each constructs the complete six-route application and header-setting BaseHTTPMiddleware. One client outside a lifespan context issues the five source HTTP requests in order, then receives text from the WebSocket session. Observations include response headers and bytes, complete exception arguments and group children, original exception identity, cause/context links, ordered ASGI scopes/events, application exit, and portal-thread cleanup.

The unchanged inputs exposed three Rust boundary faults: StreamingResponse constructed by a synchronous endpoint panicked when the portal thread used it; the missing-response RuntimeError lost its EndOfStream context; and asyncio's streaming task-group exit lost its active cancellation context. Iterator state now uses synchronized owned Python references, and Rust preserves those exception links. Trio deliberately restores the nursery group's previous context, including None; the fix preserves that difference. No runtime Python behavior or unsafe thread-trait implementation was added. See [TestClient runtime boundary](TESTCLIENT_BOUNDARY.md).

Failed runs `898c2553-1ccf-4e2d-b03b-09208772b7bd`, `d6fc9eaf-c4d9-4eb6-9930-1792454ef5ce`, and `e9e4f09d-2d59-4f22-abab-866e6ea1cf8f` remain in ignored local artifacts. Repeated live oracle runs showed different hexadecimal AnyIO cancel-scope addresses. The declared reusable `anyio-cancel-scope-message` normalization removes only that address from typed asyncio CancelledError messages and arguments; exception nodes, all other text, and every chain link remain exact.

Normal selected run `5a08029f-b3b8-4737-b7dc-f0dd4a8634b9` passed all three source/package comparisons (the two workflows and unpoisoned-cache control) and both target-only fault contracts, with zero failures, infrastructure errors, or not-run rows. Result SHA-256: `cdcdc84910c5aae58a7fc8b587893bdaba96d7429e8da8e9cb2823861b7c64ea`; manifest SHA-256: `6cd44406888e57fa77cbfdaf26cff0ff2f723e55b63d9b6822a5010b4c5854d8`; package tree SHA-256: `8f4c85f689b289c014f9c8b38a2aed68dcc7519a28c36696c889c2d83f8f030e`; installed wheel SHA-256: `821c9f0f959e175966a887b98fafe68b4b11fb12b796d68c1ac5f427335a0340`.

Coverage MCP compared the two existing composite Router cases and cache control (`02c19f50-2d85-4db2-b678-c0f88bdc9170`: 3/3) with the two middleware workflows and the same control (`3371e120-80b4-4497-98bb-0d88fee17f6e`: 3/3). Both batches also passed both fault contracts. Matching source/build receipts verified 2,521 newly covered Rust lines, a 10.249 percentage-point gain over that selected baseline: baseline 3,903/24,597, batch 5,520/24,597, and union 6,424/24,597. Status: `improved`. This incremental union does not assess full-suite coverage regressions.

Reports, receipts, and the MCP comparison remain under ignored `build/parity/coverage/testclient-middleware-20261005/`. They bind to the manifest above, instrumented package tree `a1cc6699f8deca6410ec595d45c7817c2965a6b0f9c85fee79dc81b99fccf9ba`, and instrumented wheel SHA-256 `02915c4bde50d08dba5fc6fe214bdf938ba26a03f24900e05667fd8cb18b6a34`.

The generated atlas now has 807 rows: 687 input mappings, 52 reasoned `not_applicable` rows, and 68 backlog rows. No upstream test-function row remains in the backlog; this does not establish complete behavior coverage. The initial crash also logged a traceback-retained native call-next object being deallocated on another thread. That unresolved lifecycle requirement is recorded as `testclient.runtime-traceback-garbage-collection`; it needs public traceback retention/release, garbage collection, unraisable-hook, and user-finalizer comparisons. Other backlog rows cover documentation, optional features, Python versions, API behavior, and deprecation. The pinned denominator remains 514 upstream test functions and 24 documented pages.

The bundled Open Source generic fixture auditor was also run in strict mode. It rejects this repository's existing `manifest@4` extensions and generated-input layout before parsing any inputs, so that audit did not pass. Its diagnostic log remains under ignored `build/parity/testclient-middleware-specification-audit.log`. Repository contract validation, inventory checks, and policy gates remain the compatible checks; the generic tool's schema mismatch is not runtime parity evidence.

## Previous incremental batch: composite Router through one managed TestClient

[`testclient-router.yaml`](../tests/fixtures/sources/parity/testclient-router.yaml) adds two input-only workflows for the pinned `tests/test_routing.py::test_router`, one on asyncio and one on Trio. Each constructs the complete source Router graph: users, partial function and bound class-method endpoints, the static Response Mount, GET/POST method routes, converters, and WebSocket routes. Source-equivalent route names are supplied explicitly. One managed TestClient issues the ten source requests in order with default redirect following. Observations compare complete response headers and bytes, decoded text, final URLs and redirect history, endpoint path parameters, ordered ASGI scopes/events, lifespan, and thread cleanup. The input also carries the source's narrow five-byte charset warning filter; no result normalization was added.

Normal selected run `a055b36a-7104-48a3-8be5-d5ec476c1fd0` passed all 22 source/package comparisons and both target-only fault contracts, with zero failures, infrastructure errors, or not-run rows. It includes the two Router cases, the five constructor/startup cases, all fourteen existing lifespan cases, and the unpoisoned-cache control. Each Router case observed ten responses and thirteen ASGI calls, including lifespan and the two followed redirects; the client was closed and its user-app thread stopped after context exit. Result SHA-256: `a80f60554760ea3966838c1a0f799667511cfea44ec76a7237a440fae0b922ba`; manifest SHA-256: `a1546302d09d04ff1d3cc21f3c6ae0ee89c767a848b65c6d0998667e6fbdfa91`; package tree SHA-256: `c9916a321922b8837a2bd9f5befb63decf9957c3ffc255fb077a4f93f262f8ce`; installed wheel SHA-256: `cc7d2d1f17404337dcc5e3ce9403c97a03cdaa51c22ae75d0c6e11e8e3006cf4`.

Coverage MCP compared the five constructor/startup cases and cache control (`77563efa-8266-4d3a-aaf3-8b5dc47a6997`: 6/6) with the two new Router cases and the same control (`c73170fb-3071-4233-8d20-051eca06caaf`: 3/3). Both batches also passed both fault contracts. Matching source/build receipts verified 906 newly covered Rust lines, a 3.688 percentage-point gain over that baseline: baseline 3,029/24,568, batch 3,903/24,568, and union 3,935/24,568. Status: `improved`. This incremental union does not assess full-suite coverage regressions; the separate normal full-slice parity run below checks broader behavior.

Reports, receipts, and the MCP comparison remain under ignored `build/parity/coverage/testclient-router-20261005/`. They bind to manifest SHA-256 `a1546302d09d04ff1d3cc21f3c6ae0ee89c767a848b65c6d0998667e6fbdfa91`, instrumented target package tree `c14fda5861ae96181e20d87619c1256e69eb19e3f4f65a94d47d79bea3115e3b`, and instrumented wheel SHA-256 `4d1a34815f037d3b3e73e1cde83eec5d94a19bfc423387cc369c3d8b10ac1167`.

That batch brought the generated atlas to 806 rows: 686 input mappings, 52 reasoned `not_applicable` rows, and 68 backlog rows. At that snapshot, the remaining upstream test-function row was the composite custom BaseHTTPMiddleware workflow. Other backlog rows covered documentation, optional features, Python versions, API behavior, and deprecation. The pinned denominator remains 514 upstream test functions and 24 documented pages.

## Previous incremental batch: TestClient constructor headers and middleware startup failure

[`testclient-public.yaml`](../tests/fixtures/sources/parity/testclient-public.yaml) adds five input-only workflows. One reproduces the pinned test's three constructor samples: omitted headers, a supplied User-Agent, and an Authentication header. It reads the complete live header mapping and named lookups without sending an HTTP request. Four cases enter the TestClient context for an application with a raising ASGI middleware, using empty or message-bearing custom exception arguments on asyncio and Trio. They observe exception class, arguments, message, object identity, cause, and portal-thread cleanup. These map `test_testclient_headers_behavior` and `test_exception_in_middleware`; the latter never issues an HTTP request.

Initial run `d01c4e16-c866-40bb-bd07-13868eb23378` failed because the harness probed `TestClient.portal`. The pinned docs and tests do not establish that implementation-state attribute as public. The probe was removed, its unresolved status was recorded in [Compatibility inventory](COMPATIBILITY_INVENTORY.md), and cleanup is now observed through the user application's thread. The failed result remains under ignored `build/parity/testclient-public-invalid-portal-probe-result.json`. No comparison normalization or runtime workaround was added.

Normal selected run `a7eabb5b-01f8-4bf1-a423-f9045afb3bfa` passed all 20 source/package comparisons and both target-only fault contracts, with zero failures, infrastructure errors, or not-run rows. It includes the five new cases, all fourteen existing TestClient lifespan cases, and the unpoisoned-cache control. Result SHA-256: `47c53e9f8adac43960e01f502f79c64f84c7ad602ae25425f0fa1bb4491fb35d`; manifest SHA-256: `ac97b2f339eabf6e27832933d3ef1dd151b064d945cb3076652a11f68019799c`; package tree SHA-256: `c9916a321922b8837a2bd9f5befb63decf9957c3ffc255fb077a4f93f262f8ce`; installed wheel SHA-256: `142702dbdde3a58e986daad2c95201890a91762c029fe2b27947d493803b92f6`.

Coverage MCP compared the fourteen existing lifespan cases and cache control (`8d4293d9-c21a-4a5c-9175-311a1cbf7401`: 15/15) with the five new cases and the same control (`7c70bc94-8254-4435-9621-7dd68a47ce95`: 6/6). Both batches also passed both fault contracts. Matching source/build receipts verified 16 newly covered Rust lines, a 0.065 percentage-point gain: baseline 4,238/24,568, batch 3,029/24,568, and union 4,254/24,568. Status: `improved`. The incremental union does not assess full-suite coverage regressions; the separate normal full-slice parity run below checks broader behavior.

Reports, receipts, and the MCP comparison remain under ignored `build/parity/coverage/testclient-public-20261005/`. They bind to manifest SHA-256 `ac97b2f339eabf6e27832933d3ef1dd151b064d945cb3076652a11f68019799c`, instrumented target package tree `c14fda5861ae96181e20d87619c1256e69eb19e3f4f65a94d47d79bea3115e3b`, and instrumented wheel SHA-256 `521f72664d5c2d80412b8658f86841d9ef32a23814a54e12092acd8c0b7e5856`.

That batch brought the generated atlas to 806 rows: 685 input mappings, 52 reasoned `not_applicable` rows, and 69 backlog rows. At that snapshot, two upstream test-function rows remained: the composite Router sequence and custom BaseHTTPMiddleware workflow. Other backlog rows cover documentation, optional features, Python versions, API behavior, and deprecation. The pinned denominator remains 514 upstream test functions and 24 documented pages.

## Previous incremental batch: public WebSocket workflows on asyncio and Trio

[`testclient-websocket-public.yaml`](../tests/fixtures/sources/parity/testclient-websocket-public.yaml) adds eight input-only cases for four pinned public workflows under both backends: default WebSocket headers, a concurrent AnyIO memory-stream JSON reader/writer, denial responses without the server extension, and duplicate denial-response starts. These map the remaining four `tests/test_websockets.py` test-function rows to live TestClient consumers. No runtime implementation change was needed for this batch.

The default-header inputs use `subprotocols: null`, forwarding the public `None` default. Passing an empty list would add a `sec-websocket-protocol` header. Header values and loaded `brotli`/`brotlicffi` modules are observed from each live environment; the inputs contain no expected header mapping. The memory stream is created on the client caller thread, matching the source setup. The client supplies an explicit disconnect and drains the application close frame so the recorded cleanup sequence is deterministic.

The missing-extension and duplicate-start errors are reachable through ordinary public inputs on both implementations, so they belong to the paired parity lane. The shared adapter captures public session-entry, method, and context-exit exceptions plus their partial event tape. App construction and harness failures remain infrastructure failures. The target-only route-cache fault contracts remain separate with `oracle_applicability: not_applicable`.

Normal selected run `250ee33a-4dec-477f-b2c5-c582013de7b5` passed all 50 comparisons (49 Python-package and one Rust-native) and both fault contracts, with zero failures, infrastructure errors, or not-run rows. It includes all 47 WebSocket-session inputs and the unpoisoned-cache and live-cache-mutation controls. Result SHA-256: `647a98bd1294fae094b14ed2908b741c8ad1b520adfd7e631a5b88ef8de80547`; manifest SHA-256: `6fb347c5f29328ead3b396c8f67f07047e3b4c57024a4a0d716f391c75785ab2`. The installed normal package tree was `14166d8e7e12be8e55a91f4caedbe58a488718f989fe47f3ada28afc8ed90616`, with wheel SHA-256 `47f6fa2d6c99005aae3deb8f2f7f322911ca805cf2ff8154c13021988a8014bd`.

Coverage MCP compared an instrumented baseline of the 39 pre-existing WebSocket cases plus the unpoisoned-cache control (`ef75cf68-5f0d-4bb0-8526-9c3c949daaa7`: 40/40 parity comparisons) with the eight new cases and the same control (`0176c09a-0af2-4092-8722-6731e323213e`: 9/9). Both runs also passed both fault contracts. Matching source/build receipts verified 75 newly covered Rust lines, a 0.305 percentage-point gain: baseline 5,185/24,568, batch 3,843/24,568, union 5,260/24,568. Status: `improved`. This incremental union does not assess full-suite coverage regressions; the separate normal full-slice parity run below checks broader behavior.

Reports, receipts, and the MCP comparison remain under ignored `build/parity/coverage/websocket-public-20261005/`. They bind to manifest SHA-256 `6fb347c5f29328ead3b396c8f67f07047e3b4c57024a4a0d716f391c75785ab2`, instrumented target package tree `84aa0a6a44b98b453d834b4c901a56e10f39e36ec59eedf2d5b9ba467d6d77fd`, and instrumented wheel SHA-256 `9ca18813f0879a6e56d8e273eb9ccf5f971aad2a99669e396cce8f4713ad1584`.

That batch brought the generated atlas to 806 rows: 683 input mappings, 52 reasoned `not_applicable` rows, and 71 backlog rows. At that snapshot, four upstream test-function rows remained in the backlog: client header construction, middleware failure during TestClient lifespan startup, the composite Router request sequence, and custom BaseHTTPMiddleware behavior. The pinned denominator remains 514 upstream test functions and 24 documented pages.

## Previous incremental batch: public Jinja2 template workflows

[`templating-public.yaml`](../tests/fixtures/sources/parity/templating-public.yaml) adds twelve input-only public workflows. They cover missing and conflicting constructor configuration, string and pathlib.Path directory loading, direct get_template/render calls, autoescape for HTML/HTM/XML, supplied-environment identity and autoescape policy, context processors, named-route URL lookup, ordered directory sequences, and TestClient template/context metadata with and without pass-through BaseHTTPMiddleware. The nine pinned template test functions now map to their public invocation shapes; the original direct-ASGI template inputs remain as controls. The async context-processor and other unmapped template contracts remain visible in the atlas.

These inputs exposed a real target fault in run `d10a3df8-3e73-4370-9d66-7a73e3ad2bc0`: a template object constructed on the TestClient caller thread panicked when the async endpoint used it on the portal thread. Rust's template service and stateless URL global had `unsendable` PyO3 annotations. Removing those annotations lets their owned Python references cross the portal boundary with Python attachment and PyO3 borrow checks; no Python runtime logic or unsafe thread-trait implementation was added. The unchanged input sequence now passes. The boundary is documented in [TestClient runtime boundary](TESTCLIENT_BOUNDARY.md).

Selected run `4a570bcc-8e61-4fa8-8d08-9624b55dce3b` passed all sixteen source/package comparisons and both target-only fault contracts, with zero failures, infrastructure errors, or not-run rows. It included the twelve new cases, three existing direct-ASGI template controls, and the unpoisoned route-cache control. Result SHA-256: `fc54a937aba8668c6525aeb7187735f081bc3cb78ea8191da3727cb5fe9bc293`; manifest SHA-256: `9158f3dbfe1eb822b1e26871f0f9ca1d45c4f5c0ec3358bc46bb9847952d3e9a`. The target package tree was `14166d8e7e12be8e55a91f4caedbe58a488718f989fe47f3ada28afc8ed90616`, with wheel SHA-256 `f6f7c174bff0c2a5b52aaed9afd6219b2edb98ef59fed102f9f5bfb647f3726a`.

Coverage MCP compared a fresh instrumented baseline (`b0bf584c-9b67-4482-b6ac-c3647b0379c5`: the three direct-ASGI template controls and cache control) with the twelve public template cases plus the same cache control (`f8276584-2bf0-4861-808c-e4e8b4c7dd15`). Both selections also passed both fault contracts. Matching source/build receipts verified 589 newly covered Rust lines, a 2.397 percentage-point gain: baseline 3,529/24,568, batch 3,907/24,568, union 4,118/24,568. Status: `improved`. This incremental coverage comparison does not assess full-suite regressions; the separate normal full-slice parity run below provides the broader behavioral check.

The reports, receipts, and comparison are under ignored `build/parity/coverage/templating-public-20261005/`. They bind to manifest SHA-256 `9158f3dbfe1eb822b1e26871f0f9ca1d45c4f5c0ec3358bc46bb9847952d3e9a`, instrumented target package tree SHA-256 `84aa0a6a44b98b453d834b4c901a56e10f39e36ec59eedf2d5b9ba467d6d77fd`, and instrumented wheel SHA-256 `9dbdb0c7ef010071d14c124d63c8a2d5e2b39dc6fdfb7e23a23109c1c9882e57`.

## Previous incremental batch: standalone WebSocketRoute through TestClient

Two input-only cases map the pinned `tests/test_routing.py::test_standalone_ws_route_matches` and `test_standalone_ws_route_does_not_match`. A single `WebSocketRoute("/", endpoint)` is the ASGI app. Its input-defined endpoint accepts, sends a text greeting, and closes; TestClient connects to `/` or `/invalid`. The observations include session frames, the public session-entry exception, ordered receive/send events, application completion, and portal-thread cleanup. These inputs exercise direct route dispatch through the public client; the existing direct ASGI inputs remain mapped separately.

Normal selected run `8cb0e7d3-1874-4294-a956-37a715cb8832` passed all nine source/package comparisons and both target-only route-cache fault contracts (2/2), with zero failures or infrastructure errors. The selection included the existing Router static/parameterized route cases, Router protocol-switch and miss cases, direct ASGI standalone-route cases, and the unpoisoned cache control. Result SHA-256: `6406ca8e7bd1f71ed6c9cb7f0842e4f29365233bf017bb05d8c51ebf61c90ca9`; manifest SHA-256: `f9cc161f80d987ea06866c14e39891ba1857f78e778a032beb65059db3662cd4`.

Coverage MCP compared an instrumented Router baseline (`77495910-0a97-4c82-9f77-0583d5d5074f`) with the two standalone-route cases (`93ab4cc0-e097-4c2c-9180-216af9a1a74e`). Each selected run also included the same unpoisoned cache control and both fault contracts; all three parity comparisons and both fault contracts passed in each run. Matching source/build receipts verified 289 newly covered Rust lines, a 1.176 percentage-point gain: baseline 3,775/24,568, batch 3,843/24,568, and union 4,064/24,568. Status: `improved`; the incremental comparison does not check full-suite regressions.

Reports and receipts are under ignored `build/parity/coverage/standalone-websocket-route-20261005/`. They bind to manifest SHA-256 `f9cc161f80d987ea06866c14e39891ba1857f78e778a032beb65059db3662cd4`, target package tree SHA-256 `707c8b10839e055d819c0a01012d839f2d1bb083a04f633c31257d496a97ebba`, and instrumented wheel SHA-256 `e4954d53de6a7d8bda6c6e78518ab9a73865d89065733ccdc0cd53d5f9d88782`.

## Previous incremental batch: TestClient cookie-domain matching

Four input-only cases map the pinned `tests/test_testclient.py::test_domain_restricted_cookies` parameters for `testserver`, `testserver.local`, `localhost`, and `example.com`. Each case sends two requests through one TestClient, observing the response cookie view, client cookie jar, follow-up request scope, and response tape. The source and installed package match exactly for all four domains. CPython 3.12 is the selected runtime, so the pinned test's pre-3.11 xfail does not apply.

Selected normal run `3a728cc4-70e9-4f0d-a390-e8dd36d92edc` passed six source/package comparisons (the four domain cases, the existing cookie-persistence control, and the unpoisoned route-cache control) with zero diffs. Both target-only route-cache fault contracts also passed (2/2); they remain `oracle: not_applicable`. The result SHA-256 is `b2b05b598ce97532e739b2fe26c88efe9dd3c0b21e88a081eb1949cbe4592f5b`; manifest SHA-256 is `ac4fa9f14e6aa5ba338f98c21c0603b5bb4b1876d3a72204609f1a5952d4ba4a`.

Coverage MCP compared an instrumented baseline (`817851dc-92db-400b-8d36-9d54cf49a64d`) with the four domain cases (`7ea2d011-3791-4dd3-abb4-cf04b2744bfb`), each including the same route-cache control and both fault contracts. Both parity batches and both fault batches passed. The verified project-only reports covered 3,046/24,568 Rust lines each; the union also covered 3,046/24,568, for zero new lines and 0 percentage-point gain (`no_gain`). The domain cases remain valuable behavioral evidence; this selected comparison does not check full-suite regressions. Reports and receipts are under ignored `build/parity/coverage/testclient-cookie-domain-20261005/`, use manifest SHA-256 `ac4fa9f14e6aa5ba338f98c21c0603b5bb4b1876d3a72204609f1a5952d4ba4a`, target tree SHA-256 `707c8b10839e055d819c0a01012d839f2d1bb083a04f633c31257d496a97ebba`, and instrumented wheel SHA-256 `58b0da445a78ae1e80a44402fefeb6416ecae6e15828244ee50b6d55a1277ff1`.

## Previous incremental batch: TestClient raw path excludes query parameters

One input-only case maps the pinned `tests/test_testclient.py::test_raw_path_with_querystring`: issue GET `/hello-world` with `params={"foo":"bar"}` and observe the decoded ASGI path, raw path, query string, and response through the TestClient public interface. The input captures the URL-to-scope boundary where `raw_path` excludes the query and `query_string` contains the encoded parameters.

Selected run `519470b2-1d83-4316-8ed5-8f9c2a9d608f` passed the source/package comparison (1/1) and the unpoisoned route-cache control (1/1), plus both target-only route-cache fault contracts (2/2). The fault rows remain `not_applicable` to the source oracle. Result SHA-256: `9b4b11b51cb2ef0018659b4358aa25bd8380c050767bf64e1536a31b504f767b`; manifest SHA-256: `88e613991f2474adb680bd7f92b716864aa51300435e4a3a7dc92955c772b6e5`. This selected run does not claim full-slice parity or a coverage delta.

## Latest clean full-slice preflight and benchmarks: active 980-case snapshot

Clean preflight `55535731-b03c-4a49-ae6f-b8f61e10fbda` passed all 976 Python-package comparisons, 246/250 Rust-native comparisons, and both target-only fault contracts. It selected 1,226 profile comparisons, with zero failures or infrastructure errors. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. The standalone parity command continues to exit nonzero for those unsupported rows.

The target was clean at revision `8d8e48e4c5d285b41cc42d376404a6b5a11fb0f8`, with package tree SHA-256 `30dff4c3a7aa8b3494efe46a5b8bac4e5520245a76786de48a157b1b2ca8a927`, matching the normal selected cleanup run. Preflight result SHA-256: `600d92f12623ebf6d535683d84c4d49ee002cd89de9c1f6bf97a8166648c4a41`; manifest SHA-256: `f1c3c3cb7ccb00c2ffa7d9e1ecdc8eca126b6fb217453a948702b6a371a18491`; installed wheel SHA-256: `ded85bae1db44cf908e1451628de24d6bed7f8b3735182b6739590e51a85e129`.

Correctness-gated benchmark run `235c3274-3d87-494a-a9ab-62dab72158d1` measured all 74 source/package workloads: six Router and 68 GZip, with zero failures and matching normalized observations. All 74 Rust-native benchmark rows remain `not_run` because the public ASGI boundaries are not equivalent. Median source/package latency ratios were 0.742 for Router and 0.976 for GZip; source latency was lower in 5/6 Router and 59/68 GZip workloads. Result SHA-256: `be0e79206e67f80d85b5ea7b873a00d207b1240a9f0fb8bb60ddc9b4843299a2`. These local workload timings do not establish a broad speed advantage or full Starlette parity. See [Benchmark mapping](BENCHMARKS.md).

## Previous clean full-slice preflight and benchmarks: 978-case snapshot

Clean preflight `14327f2a-372b-4751-a1e4-4630740a5017` passed all 974 Python-package comparisons, 246/250 Rust-native comparisons, and both target-only fault contracts. It selected 1,224 profile comparisons, with zero failures or infrastructure errors and four existing native Python-callable boundaries `not_run`. Those four rows remain unsupported in the standalone parity command.

The target was clean at revision `f9191561cb84e9d2e270918bb025bccd96dae78c`, with package tree SHA-256 `8f4c85f689b289c014f9c8b38a2aed68dcc7519a28c36696c889c2d83f8f030e`, matching the earlier normal middleware run. Preflight result SHA-256: `5700e7bd9c678c03aaf6e62f3ed5f690f6afa5ecb91912651e9533778b23e489`; manifest SHA-256: `6cd44406888e57fa77cbfdaf26cff0ff2f723e55b63d9b6822a5010b4c5854d8`; installed wheel SHA-256: `2b30125de7cf0e71b97374549ee1c960d4dae475a2521fe96a242015e3b12a0e`.

Correctness-gated benchmark run `6e82f74a-b360-4112-8b45-012aec7924a0` measured all 74 source/package workloads: six Router and 68 GZip, with zero failures and matching normalized observations. All 74 Rust-native benchmark rows remain `not_run` because the public ASGI boundaries are not equivalent. Median source/package latency ratios were 0.747 for Router and 0.976 for GZip; source latency was lower in 5/6 Router and 60/68 GZip workloads. Benchmark result SHA-256: `2fd8671c509d7d71f5361b7cf0bde37a67c9f067a96611b45819d3a3a464cc4f`. These local workload timings do not establish a broad speed advantage or full Starlette parity. See [Benchmark mapping](BENCHMARKS.md).

## Previous full-slice parity run: uncommitted 978-case snapshot

Run `6895f13b-e664-4483-8f65-0e41ba813619` selected 1,224 profile comparisons: all 974 Python-package comparisons passed, and 246/250 Rust-native comparisons passed. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. There were zero failures or infrastructure errors; both target-only fault contracts passed (2/2). The runner exits nonzero while those native rows remain unsupported.

Result SHA-256: `9fc7e36e1a51cbde88a593a2951c3891f573b4ef70552baec8dc1579489ffce7`; manifest SHA-256: `6cd44406888e57fa77cbfdaf26cff0ff2f723e55b63d9b6822a5010b4c5854d8`; target package tree SHA-256: `8f4c85f689b289c014f9c8b38a2aed68dcc7519a28c36696c889c2d83f8f030e`; installed wheel SHA-256: `2ff881c3b41836674dbb61965f797350f525eeaf78c6d77cd90e6224815e281f`. This run measured the uncommitted worktree, rather than an immutable clean revision. It covers the active slice; full replacement parity is not established.

## Previous full-slice parity run: 976-case snapshot

Run `4eb132c7-0ecb-48cb-9e22-8b48ad97db4b` selected 1,222 profile comparisons: all 972 Python-package comparisons passed, and 246/250 Rust-native comparisons passed. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. There were zero failures or infrastructure errors; both target-only fault contracts passed (2/2). The runner exits nonzero while those native rows remain unsupported.

Result SHA-256: `4d843b2f27cf06cc3efc9540315264d219ef4013b2974f38616e2fb0ba293967`; manifest SHA-256: `a1546302d09d04ff1d3cc21f3c6ae0ee89c767a848b65c6d0998667e6fbdfa91`; target package tree SHA-256: `c9916a321922b8837a2bd9f5befb63decf9957c3ffc255fb077a4f93f262f8ce`; installed wheel SHA-256: `cc7d2d1f17404337dcc5e3ce9403c97a03cdaa51c22ae75d0c6e11e8e3006cf4`. This evidence covers the active slice. The pinned denominator remains 514 upstream test functions and 24 documented pages; full replacement parity is not established.

## Previous full-slice parity run: 974-case snapshot

Run `11929f0b-b573-4fac-a704-c1ba3bd16c49` selected 1,220 profile comparisons: all 970 Python-package comparisons passed, and 246/250 Rust-native comparisons passed. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. There were zero failures or infrastructure errors; both target-only fault contracts passed (2/2). The runner exits nonzero while those native rows remain unsupported.

Result SHA-256: `e3191f6b9b28b0b85986a007860de5eeda54105e21129674a7386f12e7620db1`; manifest SHA-256: `ac97b2f339eabf6e27832933d3ef1dd151b064d945cb3076652a11f68019799c`; target package tree SHA-256: `c9916a321922b8837a2bd9f5befb63decf9957c3ffc255fb077a4f93f262f8ce`; installed wheel SHA-256: `c1d708b4d46b60cb34cf34da8cf0d55f5175cf33bd8cc18672841f3b47ff80ed`. This evidence covers that 974-case snapshot. The pinned denominator remains 514 upstream test functions and 24 documented pages; full replacement parity is not established.

## Previous full-slice parity run: 969-case snapshot

Run `bc9111cd-ceba-49d6-8aba-b05e1df28e20` selected 1,215 profile comparisons from that 969-case manifest: all 965 Python-package comparisons passed, and 246/250 Rust-native comparisons passed. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. There were zero failures or infrastructure errors; both target-only fault contracts passed (2/2). The runner exits nonzero while those native rows remain unsupported.

Result SHA-256: `da7b9c7c3fe13188e8ca6fb050772d9a6bc64264f78d1734929c51ae8d33c727`; manifest SHA-256: `6fb347c5f29328ead3b396c8f67f07047e3b4c57024a4a0d716f391c75785ab2`; target package tree SHA-256: `14166d8e7e12be8e55a91f4caedbe58a488718f989fe47f3ada28afc8ed90616`; installed wheel SHA-256: `47f6fa2d6c99005aae3deb8f2f7f322911ca805cf2ff8154c13021988a8014bd`. This evidence covers that 969-case snapshot. The pinned denominator remains 514 upstream test functions and 24 documented pages; full replacement parity is not established.

## Previous full-slice parity run: 961-case snapshot

Run `47d0c2ff-18da-47eb-a480-e27275e60483` selected 1,207 profile comparisons from that 961-case manifest: all 957 Python-package comparisons passed, and 246/250 Rust-native comparisons passed. Four existing native Python-callable boundaries remain `not_run`: synchronous function, bound-method and partial Request endpoints, and callable-instance ASGI dispatch. There were zero failures or infrastructure errors; both target-only fault contracts passed (2/2). The runner exits nonzero while those native rows remain unsupported.

Result SHA-256: `633abab02a7a63f396a26667a1b574f54af71590e9a0dcdabc18f6b1e7cc8fbf`; manifest SHA-256: `9158f3dbfe1eb822b1e26871f0f9ca1d45c4f5c0ec3358bc46bb9847952d3e9a`; target package tree SHA-256: `14166d8e7e12be8e55a91f4caedbe58a488718f989fe47f3ada28afc8ed90616`; installed wheel SHA-256: `f6f7c174bff0c2a5b52aaed9afd6219b2edb98ef59fed102f9f5bfb647f3726a`. This evidence covers that 961-case snapshot. The pinned denominator remains 514 upstream test functions and 24 documented pages; full replacement parity is not established.

## Previous full-slice parity run: 947-case snapshot

Run `11dd5fb0-d3c1-4a82-a234-5a4f7f267ffb` used the earlier 947-case manifest, before the standalone TestClient inputs above. It selected 1,193 profile comparisons: 943/943 Python-package comparisons passed and 246/250 Rust-native comparisons passed; four Rust-native callable-boundary rows were `not_run`. There were zero failures or infrastructure errors. Both target-only route-cache fault contracts passed (2/2) and remain `not_applicable` to the source oracle. The runner reports 1,189 passed comparisons plus four `not_run`; `make test` returns nonzero while those Rust-native rows remain unsupported.

The result SHA-256 is `8a1baebceba1c2f73c099db434483a940ba44530ad6741a180ea83668cb6978f`. It used manifest SHA-256 `ac4fa9f14e6aa5ba338f98c21c0603b5bb4b1876d3a72204609f1a5952d4ba4a`, target package tree SHA-256 `1ada9c03c40f828754761c2dfdeee90cb81ac5bbb6ed64527e462d1b84c195dc`, and installed wheel SHA-256 `f1a3d28e490b559d0bf70930737211630e2f835e5824fbd02bc1ab4f23af4f9c`. This verifies that earlier slice snapshot only; the pinned Starlette denominator remains 514 upstream test functions and 24 documented pages, so full replacement parity is not established.

## Previous incremental batch: Router WebSocket route matching

Two input-only cases map the pinned `tests/test_routing.py::test_router_add_websocket_route`: TestClient connects to an input-defined Router with a static `/ws` WebSocketRoute and a parameterized `/ws/{room}` WebSocketRoute, then observes each endpoint's text frame. The source test uses the module-level Router setup; it does not call `Router.add_websocket_route`, so that method's API candidate remains `uncertain`.

Normal selected run `862a71db-e76b-4465-8436-0a3e601e821f` passed both source/package comparisons and both target-only route-cache fault contracts (2/2 each), with zero failures or infrastructure errors. The fault lane remains `not_applicable` to the oracle. Result SHA-256: `fd01699a525eb4c9ec59629e136af2b3435b3bbb6988f2431b6b7602d5cb21b4`; manifest SHA-256: `88317b643e523293f36df806a45a4bbc07060c7f4280b24d737b5d40ea0625e5`.

Coverage MCP compared fresh instrumented selected runs: baseline `1d020f37-6b83-403f-b6e4-a617bbca01aa` (two partial WebSocket endpoint cases and both fault contracts) and measurement `39c53f74-336a-41f4-92bf-231823f35a88` (these two route cases and both fault contracts). Matching source/build receipts verified 47 newly covered Rust lines, a 0.191 percentage-point gain: baseline 3,624/24,568, measurement 3,379/24,568, and union 3,671/24,568. Status: `improved`; full-suite regression status is unknown.

The receipts bind to manifest SHA-256 `88317b643e523293f36df806a45a4bbc07060c7f4280b24d737b5d40ea0625e5`, target tree SHA-256 `64163ce5558ee93325940b8e627134f2161aa2ef0457704ac514d275d055a965`, and instrumented wheel SHA-256 `c45296f0978570c392f8900484926f5767e699a68097cb81f6e6a5a6b36a0831`. The instrumented measurement result SHA-256 is `1476e51800f584fb22947c3a597e4efdf3380c74b9f07fde1e9abf625d2bb2ef`; its LCOV report SHA-256 is `990132eec3ba0a46892e6bd6966df95ceb176cfb78e7a5e1ecfe24a4702f67cd`. Ignored reports and receipts are under `build/parity/coverage/router-websocket-routing-20261005/`. This selected comparison does not claim full-suite parity or full-suite coverage.

## Previous incremental batch: Request and WebSocket constructor scope checks

Three input-only cases compare direct `Request` and `WebSocket` construction
against Starlette 1.6.0: `Request` rejects WebSocket and lifespan scopes, and
`WebSocket` rejects an HTTP scope. All three match the pinned oracle's public
`AssertionError` outcome. Four adjacent scope and callback controls ran in the
same selection.

Selected run `77763c01-30bb-452f-b887-6508cfe76adb` passed all seven selected
parity comparisons and both route-cache target-only fault contracts (2/2),
with zero failures and infrastructure errors. The fault lane asserts the
public default HTTP 500 response and exception propagation, and marks the
oracle `not_applicable`. Result SHA-256:
`72ba7bfd242f5825dae548433a053d78b45f36cd5e0cbb930d85f91be7c73186`;
manifest SHA-256:
`4539630160f3e2816d089fc0d351dc74aa73de7f0f187d4ed187e53295b5208f`.
This selected run does not claim full-slice parity or a coverage delta.

## Previous incremental batch: URL-encoded form limits in one chunk

Two input-only cases exercise the public `Request.form` limit errors with a
single ASGI body chunk: eleven URL-encoded fields against `max_fields=10`, and
a 1,025-byte field value against `max_part_size=1,024`. The source and installed
package matched the exact exception class and message.

Normal selected run `a0b78286-3bd7-419f-bca3-93a2da652f8e` passed 3/3
source/package comparisons, including the route-cache unpoisoned control, and
both target-only fault contracts (2/2). The fault rows remain
`not_applicable` to the oracle. Result SHA-256:
`45a677595a6a397f8a0115ba166f1c501df1a266ae2b4319377547ddeb48c354`.

Instrumented selected run `4d472583-df15-439b-92c9-57c3426dd3d4` passed the
same 3/3 parity comparisons and 2/2 fault contracts. Coverage MCP verified 199
newly covered Rust lines (0.810 percentage points): 3,298/24,568 in the
selected baseline, 3,051/24,568 in this batch, 4,964/24,568 after the two
previous accepted batches, and 5,163/24,568 after union. The result is
`improved`; full-suite regressions were not checked.

The upstream `test_urlencoded_limits_stop_parsing_within_a_single_chunk`
directly inspects private `FormParser` counters/messages and a 50 MiB stress
bound. Those implementation-local assertions are recorded as
source-backed `not_applicable`; this batch compares the corresponding public
`Request.form` error behavior. Receipts bind to manifest SHA-256
`48c9c23e399480334d9f7266940526a032b72f25abf42eca29a468a006d8a16c`, target
tree SHA-256
`528b61413bd72e17d720847fe5bc1e1f0867007ccdda782af6613d99936b473a`, and
instrumented wheel SHA-256
`0d45399cb3e23aa37d34f1f82c02dc5ec77c29060e49eeae75d7a6ab72512093`. The
instrumented result SHA-256 is
`d9343781728f3a50bb78006435ab7548ba0418cc64d11f8e90f559a97c62f239`, with 58
Rust source hashes matched and zero mismatches. The LCOV report SHA-256 is
`7c53fd446fba11b5117d4f4c2a092d531081d0c5facbdece325ea48eafd34598`; reports
and profiles remain under ignored
`build/parity/coverage/urlencoded-limit-20261005-corrected/`.

## Previous incremental batch: partial WebSocket endpoints

The new input maps `routing.test_partial_async_ws_endpoint` from the pinned
`tests/test_routing.py` source. It compares both `functools.partial` callable
shapes (an async function and a bound async class method) through mounted
WebSocketRoutes and TestClient, including accepted sessions, JSON URL frames,
ordered ASGI events, and portal cleanup.

Normal selected run `8be27b9b-40b3-4e60-8fa5-3ec95c3bba65` passed both
source/package comparisons (2/2) and both target-only route-cache fault
contracts (2/2). The fault rows remain `not_applicable` to the source oracle.
Result SHA-256: `d12f24cb610906f6609a5b041fbafc7e02c21e8942c1eeeb1512f627c61f70a5`.

Instrumented run `32f2e73e-e011-43da-b815-a527300cdd8a` passed both parity
cases and both fault contracts. Coverage MCP returned `improved` with verified
matching source/build receipts: 1,208 newly covered Rust lines, a 4.917
percentage-point gain. Coverage was 3,298/24,568 in the selected baseline,
3,624/24,568 in this batch, 3,756/24,568 after one prior accepted batch, and
4,964/24,568 after union. The incremental comparison does not check full-suite
regressions.

The receipts bind manifest SHA-256
`4e274a15018c41d626f62d3e23060d24207dc5b6ad4d34f88161ea042258b4aa`, target
tree SHA-256
`528b61413bd72e17d720847fe5bc1e1f0867007ccdda782af6613d99936b473a`, and
instrumented wheel SHA-256
`0d45399cb3e23aa37d34f1f82c02dc5ec77c29060e49eeae75d7a6ab72512093`. The
instrumented parity result SHA-256 is
`02b0468460e43079cf3fdcd3528b76aa05265e3e8028ebcb9110c7204c975b84`. Ignored
reports and profiles are under
`build/parity/coverage/partial-websocket-20261005/`.

## Earlier incremental batch: partial HTTP endpoints

Selected run 2189c29e-b500-4509-9422-241719950cc0 passed the new source/package comparison (1/1) and both route-cache fault contracts (2/2). The two fault results remain target-only with oracle status not_applicable. Result SHA-256: 2a90321e8bd9ba31812bfe7147ef19a875e5daaaca6ec20dbb38ded0f4dbed8d.

Coverage MCP verified 561 newly covered Rust lines, a 2.283 percentage-point gain. Coverage was 3,298/24,568 in the selected baseline, 3,181/24,568 for this batch, 3,756/24,568 after the one prior accepted batch, and 4,317/24,568 after union. Instrumented selected runs 2470158b-74b8-49df-b6f3-c1c95ebe4330 (baseline) and aa366e34-ecec-4d58-b2ea-ff878852474f (measurement) each passed one parity case and both target-only fault contracts. This incremental comparison is verified for matching source/build receipts; it does not check full-suite regressions.

The receipts bind manifest SHA-256 00b265edd5c4965f06d91281b3a3bdbc9c388e81be4599915a246ee9b08ea830, target tree SHA-256 528b61413bd72e17d720847fe5bc1e1f0867007ccdda782af6613d99936b473a, and instrumented wheel SHA-256 0d45399cb3e23aa37d34f1f82c02dc5ec77c29060e49eeae75d7a6ab72512093. The instrumented result SHA-256 is dc2928b845c52bfa5f09eb83154a1ec899069d5cb4917658dd0819408f7b1401; ignored reports and profiles are under build/parity/coverage/starlette-partial-async-20261005/.

The `tests/test_routing.py::test_lifespan_state_unsupported` input deletes
`state` from TestClient's lifespan scope before calling a Router whose lifespan
callback yields a mapping. It compares `lifespan.startup.failed`, TestClient's
propagated `RuntimeError`, and callback cleanup.
The new TestClient case maps `tests/test_requests.py::test_request_url_starlette_context`: custom Starlette middleware constructs `Request(scope, receive)`, calls `url_for("homepage")`, and captures the absolute URL during GET `/home`.

[`exception-middleware-typing.yaml`](../tests/fixtures/sources/parity/exception-middleware-typing.yaml) maps the pinned `tests/test_exceptions.py::test_handlers_annotations` contract. Its input-derived Mypy probes accept both synchronous and asynchronous `JSONResponse` catch-all handlers and reject a handler returning `int` with the same diagnostics for the pinned source and installed package. This case passed in full-slice run `83186334-c2e3-45e6-aae6-4f1711f5c0e0`.

The cases cover Starlette applications and route inventory, including synchronous route GET/HEAD behavior through raw ASGI and TestClient, post-construction `app.debug` mutation and traceback responses, configured TrustedHostMiddleware, mounted StaticFiles and Router URL sequences, host-parameter routing, input-defined follow-up requests on one TestClient instance, middleware registration and ordering; routing and reverse URLs; async endpoint loop/task/thread ownership, callable shapes, and cancellation; URL scope and components; Headers, MutableHeaders, and State behavior; direct Request body, stream, JSON, and form consumption; responses and background tasks, including cancellation and post-construction FileResponse assignments; WebSockets, exceptions, status, endpoints, authentication, middleware, configuration, schemas, and one Python-package Jinja2 workflow. The manifest is authoritative for exact operation and target-profile applicability. The pinned denominator remains 514 upstream test functions and 24 documented pages. The current scope is bounded; it does not claim full Starlette API or behavioral parity.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source references and the source roots used by the API and compatibility inventories. The active manifest is separate: its `input_index` points to generated runtime JSON beneath `build/parity/inputs/`.

Parity and benchmark inputs are authored as JSON-compatible YAML under [`tests/fixtures/sources/parity/`](../tests/fixtures/sources/parity/) and [`tests/fixtures/sources/benchmark/`](../tests/fixtures/sources/). Run `make parity-inputs` or `python3.12 -m scripts.parity.generate_inputs` to serialize the indexed source definitions as JSON under `build/parity/inputs/{parity,benchmark}/`; `make contract-check` regenerates those files before offline contract validation. Generated inputs and parity/benchmark result JSON beneath `build/parity/` are ignored local build outputs, not checked-in fixtures or committed artifacts. Recreate them locally before running a parity or benchmark command.

The compatibility authority is Starlette 1.6.0 at commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The live source oracle checks the release, commit, source import path, source `uv.lock` digest, and CPython identity before it executes any case.

A previous clean full-slice correctness preflight
`4d9a1935-b216-449f-aa60-53421675afd3` ran against Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f` and the then-active 940-case contract.
It selected 1,186 profile comparisons: 1,182 passed, zero failed, zero
infrastructure errors, and four Rust-native callable-boundary rows were
`not_run`. The installed Python package passed 936/936; Rust-native passed
246/250. Both target-only route-cache fault contracts passed (2/2) and remain
`not_applicable` to the source oracle. The result SHA-256 is
`10c37dd392b4f3433a0dceb1da7987713502e7a39c14d77b702983fe98f6b15d`;
manifest SHA-256 is
`4539630160f3e2816d089fc0d351dc74aa73de7f0f187d4ed187e53295b5208f`, clean
target revision `c93d25a8b2e477ca689bce7b454a93b3352dd628`, target package-tree
SHA-256 `1ada9c03c40f828754761c2dfdeee90cb81ac5bbb6ed64527e462d1b84c195dc`, and
installed wheel SHA-256
`6796dece62859aa7a9cfa5739cc5e5ebcc1d0aa86f3bfbc1d27189e7cbaf622a`. These
results cover the active package slice and do not establish full Starlette
parity.

A previous clean Router/GZip benchmark run
`e8fb3ceb-f397-4f6b-99b2-1499e9861d22` measured all 74 source/package workloads
on that revision: six Router and 68 GZip. It recorded zero failures and
matching normalized observations for all 74 workloads; all 74 Rust-native
workload boundaries remain `not_run`. Its correctness preflight is the
1,186-comparison run above. Median source/package latency ratios were 0.735
for Router and 0.978 for GZip; source latency was lower in 5/6 Router and
56/68 GZip workloads. The benchmark result SHA-256 is
`47d34ead361efddfd8f4fe846a852272c099cae00fb5b19fc08176f8670c2e5c`. These
workload-specific measurements do not establish full Starlette compatibility;
see [Benchmark mapping](BENCHMARKS.md) for timing and artifact details.

An earlier clean full-slice correctness preflight
`7607d008-0ee2-4186-8efd-60fba190fc47` ran from `2026-10-04T14:39:29.292Z` to
`2026-10-04T14:43:58.397Z` against Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. It used 914 input-only cases, 892
requirements, and `parity-input@35` from manifest SHA-256
`0cbd6f609cd859f21b2a2e8bd0e8910c46d5678539337d045c355f936c79c93b`. The
Python-package target was clean at commit
`b4d64546f2a2c3bb9da16d41e3fa0d61f2bc8dea`; its tree SHA-256 was
`6c10cc52ad5d3117dce70518f55bb3d1c7bb49d99d75be8a1c3ed19834fcc0cb`.

It selected 1,160 profile comparisons: 1,156 passed, zero failed, zero
infrastructure errors, and four Rust-native Python-callable rows were
`not_run`. The installed Python package passed 912/912; Rust-native passed
244/248. The two added StaticFiles cases pass source/package comparison: the
middleware HEAD response retains Content-Length 100 and suppresses its body,
and the relative-directory request returns the input-defined file bytes. The
preflight artifact SHA-256 is
`10dbfa229b5fedbc7d473416fcca032abd777ad9866d038b14184c0ea2ec8d67` at
`build/parity/parity-result.json`.

The four native `not_run` rows remain synchronous Request endpoint,
bound-method endpoint, partial endpoint, and callable-instance ASGI dispatch.
`make parity-run` reports these explicitly and exits nonzero while they remain
unsupported. The new Router lifespan-state case and status-module warning
callsite case also pass exact source/package comparison. The
`ExceptionMiddleware` typing input maps `test_handlers_annotations`: source
and installed-package Mypy reveal the same constructor signature, accept
synchronous and asynchronous catch-all handlers, and emit the same diagnostic
rejecting a handler annotated to return `int`.

The four native `not_run` rows remain synchronous Request endpoint,
bound-method endpoint, partial endpoint, and callable-instance ASGI dispatch.
`make parity-run` reports these explicitly and exits nonzero while they remain
unsupported. The clean installed wheel SHA-256 is
`24d988298400c1f65037d45be8b1adc3ddbc49fec032b1e6b04bbe59dc02c5b5`; the
preflight artifact SHA-256 is
`10dbfa229b5fedbc7d473416fcca032abd777ad9866d038b14184c0ea2ec8d67` at
`build/parity/upstream-benchmark-correctness-result.json`. This is an incomplete
native/full-replacement boundary, not a failed Python source/package comparison.

An earlier clean Router/GZip benchmark run
`d06b1c3c-e3c2-4003-9545-758d1f846f32` measured all 74 source/package workloads
on commit `b4d64546f2a2c3bb9da16d41e3fa0d61f2bc8dea`: six Router and 68 GZip,
with zero failures and matching normalized observations for all workloads. Its
preflight is the full-slice run above. Rust-native remains `not_run` for these
74 equivalent ASGI workload boundaries. Median source/package latency ratios
were 0.726 for Router and 0.975 for GZip; source latency was lower in 5/6
Router and 63/68 GZip workloads. These workload-specific results do not
establish full Starlette compatibility. See [Benchmark mapping](BENCHMARKS.md)
for artifact hashes and measurement details.

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

### Status module constants and deprecated-alias warning callsite

[`status-constants.yaml`](../tests/fixtures/sources/parity/status-constants.yaml)
compares the public HTTP and WebSocket constants, deprecated aliases, warning
category/message/filename/line, unknown-attribute behavior, and `dir(status)`.
The source and installed-package adapters use the same shared consumer callsite
so the warning's `stacklevel` resolves identically. All five requirements pass
exact source/package comparison in clean full-slice run
`65044ac3-c6fc-4bdb-9b3b-422ef77afdc7`. This case exercises the Python package
boundary; it makes no Rust-native claim.

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

### Concurrent BaseHTTPMiddleware response background tasks

The same input file adds `starlette.middleware.base.BaseHTTPMiddleware.base-http-workflow.concurrent-background-task-completion`, mapped to `tests/middleware/test_base.py::test_do_not_block_on_background_tasks` (`360-411`). It runs two concurrent direct ASGI calls through configured BaseHTTPMiddleware, with a delayed async response background task on each call. The source and installed package observations compare response events, completion ordering, and the execution trace exactly. The normal, non-instrumented selected run `44a904ac-ec91-46c6-9363-68c9ddfeea77` passed the one parity case and both target-only route-cache fault contracts; the fault lane passed 2/2 and marks oracle applicability `not_applicable`. Its result SHA-256 is `49f6b9501ebe38bcddd67f5a32a05776dbc663c34e9061c84568c2fb97ff3513`.

### BaseHTTPMiddleware async context-manager cleanup

The new `async-context-manager-cleanup-completes` input maps to
`tests/middleware/test_base.py::test_run_context_manager_exit_even_if_client_disconnects`
(`415-470`). It stacks pass-through BaseHTTPMiddleware with an input-defined
pure-ASGI `AsyncExitStack` middleware. The empty response's delayed background
callback and context-manager exit callback each wait for the input delay. The
live trace compares response completion, background-task completion, cleanup
start/completion, and return from the full application against the pinned
source and installed package. The upstream test's name mentions a client
disconnect, but its input has no `http.disconnect`: the receive callback raises
if called, and the test observes cleanup after the app returns. This case covers
that ordering only, not other disconnect or cancellation combinations. Focused
run `601b76ff-d0b3-49d3-8d4e-cc7b7a3773bc` passed 1/1 source/package cases and
both selected target-only route-cache fault contracts (2/2); the fault oracle
status remains `not_applicable`. The result SHA-256 is
`a27418faf2edc901c85c5dbb75701b3cc4c347297d580ad3464ac42f5d6e9b27`.

### StreamingResponse mutable status

[`streaming-response.yaml`](../tests/fixtures/sources/parity/streaming-response.yaml)
constructs a synchronous StreamingResponse with status 200, assigns its public
`status_code` field to 201 after construction, and compares the emitted
response-start status against the pinned source. This closes the adapter gap
where constructor-time status had been frozen in Rust before the call. The
input maps source behavior to `StreamingResponse.__init__` and
`stream_response`; it is package-only because it exercises mutation of the
Python compatibility object.

### Incremental coverage for middleware cleanup and streaming status

Instrumented baseline run `679f4063-0c0e-49e3-90ea-0a296f1e0597` passed one
configured-header source/package case and both target-only route-cache fault
contracts (2/2). Measurement run
`8b79bb98-5821-42ca-9b62-edf75ad936bc` passed the new async context-manager
cleanup and mutable StreamingResponse status cases (2/2), with the same fault
contracts passing (2/2). The fault cases remain `not_applicable` to the source
oracle. Their result SHA-256 values are
`16851d5852b6842361802727fdae7901d0cde03de80e05cda672c1dc70a6fb9b` and
`a2ea0cabe25d766d659b079f3028dafe473ed664cc1f06ee06b43d711614fe16`.

Coverage MCP compared the project-only LCOV reports with matching source/build
receipts and verified an incremental improvement: baseline 3,298/24,568 lines,
measurement 3,602/24,568, and union 3,696/24,568. The two-case batch added 398
Rust lines (1.620 percentage points); 3,204 lines were already covered by the
baseline. The result is `improved` with verified evidence. This selected
incremental comparison did not rerun the full suite, so regression status is
unknown. Reports and receipts are under ignored
`build/parity/coverage/streaming-status-20261005/` and bind to manifest SHA-256
`7c73e24ee264c4b49b368cda5a61fc4e5f44fd2366f8ebd29ec11c4f611066c8`, target
package-tree SHA-256
`7cfad1f2f2cc7c8f6dfc708995ebf617bc909de6b2c69c5d5ab4522ee51e770a`, and
instrumented wheel SHA-256
`c17965eb95ddd07d05298b85a8c23e4a12bf55ed8eb962dae99beaa69c7dd0e5`.

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
defines three direct-ASGI Python-package cases for `Jinja2Templates`. Its input supplies a
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
use this module. The public constructor, direct-render and TestClient workflows
are now compared separately in `templating-public.yaml`. The no-Jinja import,
async context-processor contract, and other unmapped workflows remain in the
fixture backlog.

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
now contains twenty-two Python-package cases. The previous integrated run
passed the earlier twenty-one; the selected run below passes the newly added
case against pinned Starlette 1.6.0. Together, the available runs cover
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
state. A separate parity-input @41 case, `outer-middleware-receive-transformation`, maps `test_pr_1519_comment_1236166180_example` at `tests/middleware/test_base.py:1020-1059`. Its input gives the original POST bytes and an outer ASGI receive wrapper that appends the declared suffix before BaseHTTPMiddleware reads and caches the body. The route reads the cached body and returns an empty response, matching the source endpoint; observations compare the raw and transformed receive messages, dispatch and endpoint body bytes, and response events. `make migrate-parity-inputs-v40-v41` updates only indexed authored input schema headers and supports `--check`. Focused run `1fa9cbfe-9a94-46b8-be40-109bd0b5623c` passed three selected oracle/package comparisons and both target-only fault contracts (2/2); the fault cases remain `not_applicable` to the oracle. Its result SHA-256 is `a6cc0f4cee4fff5d5f6acbd4409d57ef2324982ea6502b517f8fcd2fadccaa37`. The final normal-build selection also passed 3/3 oracle/package comparisons and both target-only fault contracts (2/2) in run `e8f840cb-6759-41fd-a4f2-8c3cf36a960a`, with zero failures and infrastructure errors; its result SHA-256 is `5b986c9f4242740552e5faf281f83db3958f229d9b48dd4a4c6dec8bf1e3b140`. Both runs use manifest SHA-256 `6bf22d158ed9b41fdd0a5c62aee7545d38a3ade25edfaf8bc884ab29db8c7f6e`. An instrumented selected baseline (`9a3d279a-8ecb-4bd1-9387-d1e11a8cf1dd`) passed the configured-header case and both fault contracts; the instrumented measurement (`7615faa6-1d90-4217-9342-00c3df9dca63`) passed the new case and both fault contracts. Coverage MCP compared the matching project-only reports and verified 458 newly covered Rust lines: baseline 3,298/24,568, measurement 3,638/24,568, and union 3,756/24,568, a 1.864 percentage-point gain. The result is `improved`; full-suite regressions were not checked. Both receipts bind to manifest SHA-256 `6bf22d158ed9b41fdd0a5c62aee7545d38a3ade25edfaf8bc884ab29db8c7f6e`, target tree SHA-256 `528b61413bd72e17d720847fe5bc1e1f0867007ccdda782af6613d99936b473a`, and instrumented wheel SHA-256 `0d45399cb3e23aa37d34f1f82c02dc5ec77c29060e49eeae75d7a6ab72512093`. Reports and receipts remain under ignored `build/parity/coverage/fault-contract-base-http-20261005/`. This is selected-case coverage evidence, not a full-suite or full-parity claim. The repeated-disconnect cases match
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

Unverified BaseHTTP behavior still includes other receive-transformation and wrapper combinations, partial-stream/replay interleavings beyond the tested `b"1"`/`b"2"`/`b"3"` flow, disconnect ordering across stacked middleware, broader exception cause/context combinations and exception-group shapes beyond the observed TaskGroup context and caught `ValueError`, varied and malformed `http.response.debug` frame sequences, cancellation and ContextVar behavior, other background-task/context-manager cleanup orderings, path-send combinations beyond the covered FileResponse forwarding case, the full `MutableHeaders` API and live `raw_headers` mutation, and other streaming paths. The atlas backlog retains the remaining upstream middleware cases.

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
together contain 31 input-defined `StaticFiles` ASGI-call cases,
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
AnyIO worker while the event loop progresses. The ASGI-call inputs select 29
comparisons on each target profile; package-discovery cases use Python's
`importlib`, and Rust-native explicit-root cases use supplied roots. The two
path-limit cases exercise an
overlong first root with both `follow_symlink` settings and verify that its
404 preempts a later configured root containing the requested asset. Two more
cases remove search permission from an existing asset's root and compare the
401 exception with both symlink settings. Together
with the 15 lookup cases on each profile and the package-only async-boundary
and four configuration cases, they produce 93 profile comparisons: 44
Rust-native and 49 Python-package.
They cover rooted GET and HEAD,
HTML index redirects and 404 fallback, 401/404/405 outcomes, date and ETag
validators including the two-request ETag-mismatch sequence, validator
precedence, package assets, absolute-path rejection,
file/directory metadata, path traversal and symlink containment, external file
and directory symlink serving with `follow_symlink=True`, rejection of
external file and directory symlinks under the documented default
`follow_symlink=False`, bound override dispatch, the resulting ASGI response,
and path-limit error precedence. Python
package discovery is exercised through `importlib` on the Python package
profile; Rust-native package cases pass explicit roots. The earlier 89-case
StaticFiles selection passed in run `0c6a7de9-d5f7-44db-83b1-4d1ec0a3472a`,
including all 30 direct lookup comparisons. The two newly added default-policy
symlink cases passed on both target profiles in selected run
`1c302ec6-419c-470c-b8e8-e8f33aa84559`. That same run selected the two
existing target-only route-cache fault contracts: both passed their public
outcome assertions, and each records oracle applicability as `not_applicable`.
The run selected four parity profile comparisons and two fault-contract rows;
it does not claim full-suite coverage. Its result SHA-256 is
`18b888b0b8dfc0f66bed5ed56a9df09a6ba4a7e83ab31a0d49014918a05edae7`, using
manifest SHA-256 `daa6ddd955ec1a144293fa1383fac51ba3d781b78e7c93a1b440c571b4c07fc7`.
Four package-only configuration
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
input-only operations. The raw protocol operation compares the ordered callback
tape on source, installed-package, and Rust-native profiles. The Rust adapter
uses `WebSocketStateMachine` to decide when callbacks occur and records only
the canonical messages supplied by the input; it does not compare Python
exception details or claim a general Rust ASGI `WebSocket` API.

[`websocket-protocol.yaml`](../tests/fixtures/sources/parity/websocket-protocol.yaml)
contains six ordered `WebSocket.receive()` and `WebSocket.send(message)`
sequences: handshake/text/close, disconnect return, invalid send transition,
receive after disconnect, binary exchange, and a connected send callback that
raises `OSError`. The observed ordered receive/send callback tape records the
message at each callback in chronological order. In the connected `OSError`
case, the attempted outgoing send is recorded before the send callback raises.
The incoming messages and action sequence are fixture stimulus. These six
callback-tape cases select both target profiles; state and exception
observations remain in the separate state-sequence operation.

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

Each adapter runs in a fresh process. The runner sends one strict JSON `migration-parity/adapter-request@1` object on stdin and accepts exactly one JSON response object on stdout. The response envelope remains `migration-parity/adapter-response@1`; its opaque workflow payload follows the versioned parity-input and parity-result contracts. Diagnostics go to stderr. Identity responses are checked against the source revision or installed target environment before workflows run. The result schema is `migration-parity/parity-result@6`, which retains oracle revision/module/lock provenance, target revision/tree/lock/package identity, per-side environment fingerprints, and an explicit case selection. Repeat `--case-id` to run a focused batch; the identity records the exact IDs, and selected runs default to `build/parity/parity-selected-result.json`. A selected run is never full-slice evidence. The prepared Python environment digest includes a fixed process policy: `PYTHONHASHSEED=0`, with `PYTHONOPTIMIZE` and `PYTHONWARNINGS` removed. Unknown fields, duplicate JSON keys, malformed output, absent interpreters/adapters, crashes, timeouts, identity mismatches, missing or extra observations, skipped evidence, and unsupported evidence cannot pass.

## Fault-contract cases

Fault-contract cases share the active indexed parity inputs and runner, but are
reported separately from source-to-target parity comparisons. The runner marks
the source oracle `not_applicable` with a reason because target-internal fault
injection has no upstream counterpart. The target still runs through its
public consumer interface; runner-owned named assertions check only the
externally visible outcome. The case input contains a fault-point ID and a
contract ID, never expected output values.

[`fault-contracts.yaml`](../tests/fixtures/sources/parity/fault-contracts.yaml)
contains a normal GET route input and two target-only fault contracts for the
same TestClient route shape. The normal case compares the pinned source and
installed package. Both fault cases poison the Rust router route-cache mutex
in the parity-only Python wheel, then send a request through Starlette's public
TestClient. With `raise_server_exceptions=False`, runner-owned assertions
check the default HTTP 500 status and `Internal Server Error` body. With
`raise_server_exceptions=True`, a runner-owned assertion checks that the
exception outcome is propagated. The fault registry maps these outcomes to
`starlette.asgi.server-error.default-response` and
`starlette.testclient.TestClient.request-response.exception-policy`; their
requirement associations are reported on the fault rows while `covers` stays
empty, so fault evidence does not count as an oracle parity pass. The PyO3
injection method is compiled only with the non-default `fault-contract` Cargo
feature; ordinary package builds do not expose it.

On the 917-case manifest snapshot, selected run
`189e7aa9-c5e9-4da9-8b22-27761ae7e537` passed the normal route comparison and
the new exception-propagation fault contract. Run
`68288f42-aaa7-4af3-8106-f35e69cdf9b7` passed the default-500 fault contract;
the isolated fault batch `cfe1e118-7b1b-4988-8a39-842fe48eb846` passed both
fault contracts. The new propagation case also passed alone in run
`5debde0c-8951-4f05-8837-451de7e76f73`.

Coverage MCP compared project-only LCOV from that isolated case with a passing
normal-route baseline (`66d73c42-be95-495d-bb63-13ecdbee11b5`), using matching
Rust source and instrumented wheel receipts. The baseline covered 2,524 of
24,526 lines; the new case covered 2,079, and their union covered 2,773, adding
249 lines (1.015 percentage points). The comparison was `improved` with
`evidence: verified`; `regression_checked` is false because this selected
incremental run did not rerun the full suite. Both reports used manifest
SHA-256 `ad3a7fad97f7614726e6c5c74e245b526a81e2abb221009c37e9e97da76171f8`,
target tree SHA-256
`95fee3cd9e6f3f4bc9616389550bbe91e2fc7a17d3f1ef9fd4bd0f1186fdab56`, and
instrumented wheel SHA-256
`0ac058ea91360474baf4bbb91dbb85cb4dfe3569bbe178d8beca02e47e292049`. Reports
and receipts remain under ignored `build/parity/coverage/`.

That Coverage MCP measurement is tied to target tree SHA-256
`95fee3cd9e6f3f4bc9616389550bbe91e2fc7a17d3f1ef9fd4bd0f1186fdab56`; it is
historical evidence and does not cover the current target tree or the mixed-
protocol inputs below. No Rust coverage claim is made for those new inputs.

The latest clean full preflight before the current fixture additions, on the
917-case manifest, is run
`f2adb5d3-34ae-4406-85ac-f36ea9101536`. It selected 1,161 profile comparisons:
the Python package passed 913/913, Rust-native passed 244/248 with four
callable-boundary cases `not_run`, and both target-only fault contracts passed;
there were zero failures and zero infrastructure errors. Its result SHA-256 is
`538b10f4dfc19fbcbded2e79eec7fad4280ad9047b8e70199ea51106edf4d7b6`. The
correctness-gated benchmark run `8a3f6576-289e-45e7-a434-5fb8dc831110` then
measured 74/74 pinned source/package workloads with zero failures and zero
unmeasured workloads. Its result SHA-256 is
`440eb7a2b6b167ce3194932f18406c6eb0f0e0062890c03dff22d3479b9179e2`; the
preflight SHA-256 is the value above. The Rust-native API does not expose the
equivalent ASGI workload boundaries, so all 74 native benchmark rows remain
`not_run`. These prior full preflight and benchmark runs still do not establish
full Starlette parity.

The fresh full preflight for the 920-case manifest revision is run
`84769d51-0203-41bf-8569-be53a5cbe99c`. It selected 1,164 profile comparisons:
1,160 passed, zero failed, zero infrastructure errors, and four Rust-native
callable-boundary rows were `not_run`. The Python package passed 916/916;
Rust-native passed 244/248; and both target-only fault contracts passed. Its
result SHA-256 is
`f998d067c21944f77a87c6c5d0e245b9e27281c09c3bbd6122b754bfedb2e1f4`.

A previous correctness-gated benchmark run
`d0bba2ec-079e-4d21-822e-e0ddbf0133ef` measured 74/74 source/package
workloads, with zero failures or unmeasured workloads. All 74 Rust-native
workloads remain `not_run` because their ASGI boundary is not equivalent. Its
result SHA-256 is
`a03f960a2b7718b6612db7bcc6c51a18b71dd9befd4f9faa855706218dd9ef47`. Both
runs use manifest SHA-256
`b200928d5b42a445729d6cf6609eb6724b019696dadc4cccaad3d5bc9779b7c6`, clean
target revision `bdb9f46c78d13e2bc837f67af3d141c4fd293b21`, and target tree
SHA-256 `d66b547bab6d9525a44adc67f00ce5afc5ac1a46dc0b1c32c7d484c1a3c81ce1`.
They record that historical snapshot and do not establish full Starlette parity.

On the 920-case manifest revision, selected run
`29e8e772-6df8-46ee-9be9-05f8c1a57859` executed the three input cases for
`tests/test_routing.py::test_protocol_switch`: HTTP route selection and
`Request.url_for`, matching WebSocket route selection and `WebSocket.url_for`,
and the unmatched `/404` disconnect. All three source/package comparisons
passed with zero failed or unrun cases. Its result SHA-256 is
`b7dde727eadf62dcbf762dceacdbffd235c20a759a550997448b5c8b2cfeb57d`; the
manifest SHA-256 is
`b200928d5b42a445729d6cf6609eb6724b019696dadc4cccaad3d5bc9779b7c6`.

An earlier target-only fault-contract selection
`ed8dd93c-32d2-478c-9a50-4bbff0427a6a` passed the default HTTP 500 response
and exception-propagation outcomes. It selected two fault rows, with zero
failures and zero infrastructure errors. Its result SHA-256 is
`c680dff786fe1f8e4d033e07608235f8357cebe12f1e57e4909371aa1c2f42a4`.

The latest focused selection `2c1b792b-09d9-40bf-bb31-008890b965a3` passed
one normal route source/package comparison and both target-only fault cases
(2/2), with zero failures and zero infrastructure errors. The fault lane
asserted the public default 500 response and TestClient exception propagation;
both rows retain oracle status `not_applicable`. Result SHA-256 is
`0a9d8f15fa5bc1a5479dea41f20b94e3d63428e07d55b1b96d2119d3ab8fa992`, manifest
SHA-256 is `7c73e24ee264c4b49b368cda5a61fc4e5f44fd2366f8ebd29ec11c4f611066c8`,
and the fault input SHA-256 is
`8140507332ab58863d0f59ef003a0842e173e8923ff285f0ad83ae024cc1f436`. The
target was `python-package-cpython312` on CPython 3.12.13, with package-tree
SHA-256 `24a3a923b0780d238234600950bea6fa4b326cd44e57f87ea3d4cba264f1164f`
and wheel SHA-256
`3c93fcd943e338c5f5663f5dbf79b70d6ad78bc66ef2bb092f79a7343e3bfcb3`. This
normal selected run makes no new coverage claim and does not establish full
replacement parity.

The preceding 922-case contract added
`tests/middleware/test_base.py::test_multiple_middlewares_stacked_client_disconnected`.
Selected run `3202352e-f31a-416f-92d0-471df84a52fa` passed its ten-layer
source/package comparison and both target-only route-cache fault contracts;
the parity lane selected, executed, and passed one case, while the fault lane
selected, executed, and passed two cases with the oracle marked
`not_applicable`. Its result SHA-256 is
`9c46fbda8426c38303c8a37be2e2212b058572f524367725f459be433d2bf94f`.

Coverage MCP compared an instrumented configured-header baseline
(`ab545b70-d5fe-4730-bcf2-1778086394cc`) with that selected case and fault
batch. Matching source/build receipts verified 1,230 newly covered Rust
lines and a 5.012 percentage-point gain over the selected baseline. The
baseline covered 2,689 of 24,539 lines; the new batch covered 3,831; their
union covered 3,919. The result is `improved`; `regression_checked` is false
because this incremental run did not rerun the full suite. The reports and
receipts remain under ignored `build/parity/coverage/`; both bind to manifest
SHA-256 `fe32a97f759e4b6e5685affb8836fa508cdc630d72cd3b3850bba1f68fcd9520`,
target tree SHA-256
`4f09005626ce7b10f4c29afca1676f0975ae962ab8fb065a72ee9cd9793b6be2`, and
instrumented wheel SHA-256
`d7d61e344b020c528ebb372d74d773cac27eeb33018a7d2a72fb24ab5e9346d9`.

The preceding 923-case contract adds the concurrent BaseHTTPMiddleware background-task case mapped to `tests/middleware/test_base.py::test_do_not_block_on_background_tasks`. The normal, non-instrumented selected run `44a904ac-ec91-46c6-9363-68c9ddfeea77` passed 1/1 source/package parity cases and 2/2 target-only route-cache fault contracts; the fault rows remain `not_applicable` to the oracle. Its result SHA-256 is `49f6b9501ebe38bcddd67f5a32a05776dbc663c34e9061c84568c2fb97ff3513`. The matching instrumented measurement run `e245aa2d-52d9-4fad-a8dd-a88ef838877c` also passed 1/1 and 2/2, with result SHA-256 `e7b9877ffb9733b54a6f2bf0d0cb762aacf523a2fceac007a34c86dedd6301a5`; both runs use manifest SHA-256 `75f54d14a04c8ab39937ecac2fb73b428047b8b18398d0617e7f15c47a95e1ef`.

Coverage MCP compared an instrumented configured-header baseline with this selected parity case and the same two fault contracts. Matching source/build receipts verified 701 newly covered Rust lines: baseline 2,689/24,539, batch 3,308/24,539, and union 3,390/24,539, a 2.857 percentage-point gain. The status is `improved`; full-suite regressions were not checked. Reports and receipts remain under ignored `build/parity/coverage/base-http-concurrent/`; both bind to target tree SHA-256 `1e8ca94ee6a9cc28d0e3833546a220e0969d08b957b2b7c30f6a5b3ae3cf3ffe` and instrumented wheel SHA-256 `04bef854cf79c2bf34384142257bc32493f25c21db37e6826723bf14aae6b777`.

Earlier full-slice run `a0bcf0da-4746-4490-843d-45653d987ea1`, against the
preceding 915-case `manifest@3` contract, completed from
`2026-10-04T15:21:32.383Z` to `2026-10-04T15:25:54.530Z`. It selected 1,160
profile comparisons: 1,156 passed, zero failed, zero infrastructure errors,
and four Rust-native callable-boundary cases were `not_run`. The installed
Python package passed 912/912; Rust-native passed 244/248. Its separate
route-cache fault row passed both named public-response assertions. The pinned
oracle was Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The old manifest SHA-256 was
`d106823f3130412a7a13ed36e5990431a7cace45a8be572c10b1e93bf78d54e3`, and its
result artifact SHA-256 was
`0eb98a2bc2bee3e50347e812f08e93576ff56ea3e15f90e9422d012bf3c1bdce`. Its
parity wheel enabled the non-default `fault-contract` feature and had target
tree SHA-256
`d66b547bab6d9525a44adc67f00ce5afc5ac1a46dc0b1c32c7d484c1a3c81ce1`; that
local run did not establish a clean release build or complete parity.

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

The active `starlette.testclient.TestClient.lifespan-context.router-shutdown-error`
input maps `tests/test_routing.py::test_raise_on_shutdown` to a real
`Router(lifespan=...)` and checks TestClient context exit after the lifespan
callback raises `RuntimeError("Shutdown failed")`. Focused run
`c5a9cc24-5d27-40d3-ab2f-52e6781d6ee6` passed the exact source/package
comparison with no diffs and both target-only route-cache fault contracts
(2/2); the fault rows remain `not_applicable` to the source oracle. The result
SHA-256 is `7b8fbf52f10ca1fa96015939962975cafea7ae6758217a4a0985b3ff297f25f0`
and the manifest SHA-256 is
`d5c7a33a96974b63fd6714ee20c7242a24522aa0100978f1609a023c0f9f4224`. This
focused run does not claim full-suite parity or an incremental coverage result.

The active `starlette.testclient.TestClient.lifespan-context.router-startup-error`
input maps `tests/test_routing.py::test_raise_on_startup` to a real
`Router(lifespan=...)`; its context-manager callback raises a no-argument
`RuntimeError` before yielding, and TestClient must propagate it during
context entry. Instrumented selected run
`1323e01e-4cac-40fb-a940-88d31f770fca` passed the exact source/package
comparison with no diffs and both target-only route-cache fault contracts
(2/2); the fault rows remain `not_applicable` to the oracle. Its result
SHA-256 is `a60726b009a3a37734c53df8d7cf63782694763c114e1e8244980dfcc2e7c6a1`
and its manifest SHA-256 is
`800e7040a68b7ace38b5b0ce253a0d6c61d310ea5d684c63dab880833e2a151b`.

Coverage MCP compared a matching instrumented normal-route baseline
(`ce4576b0-b20b-4461-b5e5-189d8ff0e4a6`) with the Router startup-error case
and the same fault contracts (`1323e01e-4cac-40fb-a940-88d31f770fca`).
Matching source/build receipts verified 378 newly covered Rust lines: the
baseline covered 2,774/24,539 lines, the new batch 2,491/24,539, and their
union 3,152/24,539, a 1.540 percentage-point gain. Coverage MCP reported
`improved` with verified evidence; regression status is unknown because the
full suite was not rerun. Both reports use manifest SHA-256
`800e7040a68b7ace38b5b0ce253a0d6c61d310ea5d684c63dab880833e2a151b`, target
tree SHA-256
`4a20992251ed71021e5b00dc139989618fef141a04e19ce62022488fe5de3655`, and
instrumented wheel SHA-256
`4a7f21daede2267586ddbb9d7ced7d8993fd9a4a9b8e46bd178ef8c76b48bd2a`. The
reports and receipts remain under ignored
`build/parity/coverage/router-startup/`.

The then-active 928-case contract also maps
`tests/test_routing.py::test_lifespan_state_async_cm` to a real
`Router(lifespan=...)` exercised through TestClient. Instrumented selected run
`f54a933e-0dbf-441f-9d25-78eb7bfa3556` passed its exact source/package
comparison (1/1) and both target-only route-cache fault contracts (2/2); the
fault rows remain `not_applicable` to the source oracle. The result SHA-256 is
`838ce2835e5911f6ea56e1ce19c3186af81bc840d659539972ab74ab3f3571f3` and the
manifest SHA-256 is
`4b415afca096dfba1458e672154450efbc4878efb4ef36796fffd5fdc19e948c`.

Coverage MCP compared that batch with the matching instrumented normal-route
baseline `5612c297-d411-412c-9959-64c15627039c`. Matching source/build
receipts verified 470 newly covered Rust lines: baseline 2,774/24,539, batch
3,092/24,539, and union 3,244/24,539, a 1.915 percentage-point gain. The
status is `improved`; full-suite regression status is unknown because the full
suite was not rerun. Both reports use the same manifest SHA-256, target tree
SHA-256
`5b66570dbcd0e0595fa90782f9a60b23641c700e56c868f9351f0788221a9e65`, and
instrumented wheel SHA-256
`1616e977de0dad5e88631c92dce75af2fc9ff3be008518c9f4ec83a2d74d5224`. The
reports and receipts remain under ignored
`build/parity/coverage/router-lifespan-state/`.

The clean full-manifest preflight for the active 927-case contract
`ff54cb4d-3390-463b-8ffd-96febc69b24b` selected 1,173 profile comparisons:
1,169 passed, zero failed, zero infrastructure errors, and four Rust-native
Python-callable boundary cases were `not_run`. The installed Python package
passed 923/923 comparisons; Rust-native passed 246/250. Both target-only
route-cache fault contracts passed (2/2) and remain `not_applicable` to the
source oracle. The preflight result SHA-256 is
`4f7fa49a8a13e41205ad47cc2743779f23cc8aff2e26ab1d88a17c68806c1a0d`; it uses
the active manifest SHA-256
`800e7040a68b7ace38b5b0ce253a0d6c61d310ea5d684c63dab880833e2a151b`, clean
target revision `7dc23e64981a65a0dec6944f59f5828618168c3a`, target tree
SHA-256
`a61aae38e6a1f26630de04d38590a3acc21df02ba53807a56d633b95a08a0555`, and
installed wheel SHA-256
`dfd07b09b998c46d1decb90d8ed0fc66e5ea6ed745b131441dda130c9c1cd43d`. These
results cover the active package slice and do not establish full Starlette
parity.

The preceding clean full-manifest preflight for the 926-case contract
`5a69e4da-e6e8-47d6-b4d9-01f613c41e77` selected 1,172 profile comparisons:
1,168 passed, zero failed, zero infrastructure errors, and four Rust-native
callable-boundary rows were `not_run`. The installed Python package passed
922/922 comparisons; Rust-native passed 246/250, and both target-only
route-cache fault contracts passed. The preflight result SHA-256 is
`c807e1d0fac0f2801d1c661eeddd458fad0a4dd0d89bcdee3c36fb8caf8a8e1f`; it uses
the active manifest SHA-256
`d5c7a33a96974b63fd6714ee20c7242a24522aa0100978f1609a023c0f9f4224`. These
results cover the active package slice and do not establish full Starlette
parity.

Coverage MCP compared a matching instrumented normal-route baseline
(`46489f3c-2f0f-4805-b0d9-052abf074c46`) with the Router shutdown-error case
and the same two fault contracts (`2c9b89b4-3f7f-47fb-bc88-0331f8b2c684`).
Matching source/build receipts verified 431 newly covered Rust lines: the
baseline covered 2,774/24,539 lines, the new batch 2,543/24,539, and their
union 3,205/24,539, a 1.756 percentage-point gain. Coverage MCP reported
`improved` with verified evidence; regression status is unknown because the
full suite was not rerun. Both reports use manifest SHA-256
`d5c7a33a96974b63fd6714ee20c7242a24522aa0100978f1609a023c0f9f4224`, target
tree SHA-256
`35c05c09bccec31ff3b6eed9126860907a6c87dfcd8299a64997c0e6f25cf78f`, and
instrumented wheel SHA-256
`ee0994b002a34a6ab4ecb84f1a2ce1a4fd892d7c2821af6ccac50703a1c2b755`. The
reports and receipts remain under ignored
`build/parity/coverage/router-lifespan/`.

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
### TestClient StaticFiles HEAD middleware and relative directory

Two more inputs map `tests/test_staticfiles.py::test_staticfiles_head_with_middleware`
and `test_staticfiles_relative_directory_symlinks`. The first uses the pinned
100-byte `x` asset, a `/static` Mount, and pass-through `BaseHTTPMiddleware`;
source and package both return 200, preserve `Content-Length: 100`, suppress
the HTTPX response body, and emit identical ordered ASGI events. The second
creates `tests/statics/example.txt` beneath an isolated temporary workspace
under the process working directory, passes the equivalent relative directory
to `StaticFiles(follow_symlink=True)`, and compares the 200 response, file
bytes, headers, and ASGI events. Both cases passed in full-slice run
`7607d008-0ee2-4186-8efd-60fba190fc47`; their YAML contains only request and
filesystem stimuli.


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

### Nested TestClient inside a synchronous endpoint

[`testclient-http.yaml`](../tests/fixtures/sources/parity/testclient-http.yaml)
maps `tests/test_testclient.py::test_use_testclient_in_endpoint`. An input-defined
synchronous outer endpoint constructs an inner Starlette app and TestClient,
requests its input-defined route, and returns the inner response JSON. The case
compares the inner and outer public responses, both request scopes and ASGI
event streams, and the input-derived nested execution trace. Selected run
`8c90f08e-3bf0-4ea2-9d98-0c7f8de847a2` passed the source/package comparison
(1/1); both target-only route-cache fault contracts passed separately (2/2).
The result SHA-256 is
`8d01a1b3faa2b3576b42e229fda62829dfa515b47c09e9d0319d8caaa748246b`, and the
manifest SHA-256 is
`d2353e4a5aa660147c39f9567241f4104bb58029ffd5cb219284093bf899014b`.

Instrumented baseline run
`bc973e85-6986-4198-9825-207a0bbe4665` and measurement run
`93179bc5-eb0d-47ee-8138-21b25d7aa80f` each passed the same case/fault lanes
(1/1 parity and 2/2 faults); their result SHA-256 values are
`b3a7cada205ba7bdbd327c02e187d243b2a002f56b51793905065e1ea5e7d96d` and
`38ebfcbb53e6077564f4b7c0fbdd3df0db06bf997ba01c36ddf82730d8ccbd18`.
Coverage MCP compared their matching receipts and found 26 newly covered Rust
lines (0.106 percentage points): baseline 2,774/24,539, selected batch
2,755/24,539, and union 2,800/24,539. The status is `improved`; full-suite
regression status is unknown. The measurements bind to target tree SHA-256
`a8faad7b82de5996cdd0b202c461ba0b9dad261bfa469f5ff2aedf7de929236b` and
instrumented wheel SHA-256
`13a9d5af21e138712ccc5eeee3a968f9e14cc5b63667e6df1c42a7b664dff192`; reports
and receipts remain under ignored
`build/parity/coverage/nested-testclient/`.

### TestClient WebSocket blocking receive and close teardown

[`testclient-websocket.yaml`](../tests/fixtures/sources/parity/testclient-websocket.yaml) adds two input-only workflows mapped to the pinned `tests/test_testclient.py::test_websocket_blocking_receive` and `test_websocket_not_block_on_close` tests. The first accepts the input-selected subprotocol, sends an input-defined JSON message from a task-group child while the app main task waits in `WebSocket.receive_json()`, and has the synchronous client receive the frame before it exits the session. Context exit sends the default disconnect; the app records its `WebSocketDisconnect` class, code, and reason. The observation tape compares the exact callback order and all message fields.

The second app accepts and waits forever without consuming receive input. Context exit causes cancellation; the input-defined handler records the cancellation class, re-raises it, and the app finalizer records completion. Both cases retain the app's actual portal thread object and report whether it is alive after the session context returns. The observed portal thread is stopped in the pinned source and installed package. The latest full-slice run above includes these lifecycle inputs and the JSON text/binary cases; all 912 Python-package comparisons passed.

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

## Request lifetime graphs

Seventeen public Request ownership graphs compare live source/package collection, suspended receive cleanup, and unawaited coroutine warnings without normalizing results. See [Request lifetime boundary](REQUEST_LIFETIME_BOUNDARY.md) for ownership, retained failure evidence, and the selected 33-case verification. Runtime Python facades are unchanged.

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

## Public value and worker ownership

Forty-five new input-only cases compare native value retention, caller/worker collection, and UploadFile size-arithmetic callback reentry. The selected verification passed 66 ordinary comparisons and both fault contracts. See [Public value boundary](VALUE_LIFETIME_BOUNDARY.md) for the retained 20-leak reproduction, Rust ownership changes, and 217 newly covered lines.

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

## UploadFile arithmetic replacement

Four additional public-input comparisons reproduce and fix backing-file replacement from the size callback. See [Public value boundary](VALUE_LIFETIME_BOUNDARY.md) for live failure evidence and Rust access ordering.

Selected verification `184aca5c-dccd-42c4-a744-791d5ec202b0` passed 68/68 ordinary package comparisons and both target-only fault contracts, with zero failures, infrastructure errors, or not-run selected rows. The four new cases match exact file bytes, write targets, worker selection, and lifetime observations. Result SHA-256: `922e5d0236e65801e5e371f4eb7901e0b629d43e89f9fce04f995a17fa4bea96`; normal package tree: `9e63ddf110e4a78a06bfed9af5549e44ea9196d03426a67bc8c4dc8f99553212`. The selection also includes all earlier Request/value lifetime cases and the existing upload rollover workflow.

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

Selected verification `ce4f9633-2558-41e5-bf8d-1cb088292116` passed 102/102 ordinary package comparisons and both fault contracts with zero failures, infrastructure errors or not-run selected rows. It includes all 32 new inputs, every earlier Request/value lifetime input, the existing upload rollover workflow and both FormData constructor cases. Result SHA-256: `4bb88e662745f3a34b39009b4195a9753e048506ceed3b6412366aa42cb7e86f`; normal package tree: `6fd042132fec89afac089aca463dc2802844f176daf091ba64bea8d06700848d`. All new arithmetic and worker observations remain exact.

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
