# Response rendering and mutable public attributes

Authority: Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.
The documented consumers are `Response`, `HTMLResponse`, `PlainTextResponse`,
and `JSONResponse`, including the custom JSON render example in
`docs/responses.md:96-118`. Their constructor and ASGI implementation are in
`starlette/responses.py:29-200` in the pinned checkout.

## Cookie argument protocol boundary

`response-cookie-protocols.yaml` supplies 98 input-only consumers of the four
documented response classes. They call public `set_cookie`/`delete_cookie`
with original Python values and attribute objects, observe conversion and
truth-testing callbacks, retain callback exception identity, and record public
header bytes after success or failure. Callback reentry uses the same public
cookie methods. An input-defined clock controls deletion/integer expiry on both
sides without changing or normalizing the live output. The source implementation and installed package independently
execute this shared consumer; exact results are generated live.

The Rust boundary must preserve Python `str`, equality, truth testing, user
string translation, formatting and `lower` protocols in source order. CPython
compiles literal `%s` pairs into string conversion followed by its format
protocol; a string subclass can run its original conversion again there.
These callbacks preserve the required Python value representation contract.
Rust owns attribute selection, validation, ordering, quoting and header
construction. Python facades only forward the unchanged original arguments.
Python datetime/date formatting uses the active interpreter's representation
functions. No upstream Starlette module is imported at runtime. Arbitrary
cookie key objects, supplied Morsel values, Python versions beyond the pinned
interpreter, and complete cookie behavior remain separate open requirements.

Python must invoke a user subclass's `render` method on the constructor's
thread. Its values, attribute changes, and original exceptions belong to the
Python consumer contract. This invocation cannot be replaced with a Rust
serializer without changing arbitrary user code. The facade supplies this
calling glue; Rust selects defaults, renders base content, constructs headers,
and owns ASGI ordering and failure policy. Runtime facades contain no new
branching, loops, or exception policy.

The input-only `response-consumers.yaml` workflow constructs these four
documented classes or input-defined subclasses, observes public attributes,
then calls the object as an ordinary HTTP or WebSocket ASGI application.
It covers text, bytes, omitted content, nested JSON, invalid JSON values,
custom serialization, render exceptions, charset and media-type changes,
status changes during rendering or before calling, replacement body values,
send exceptions, and background ordering. User callbacks are shared consumer
code run independently against the live source and installed target. Outputs
are computed by those executions, with exact comparisons and no stored
expected values. Python subclass behavior has no equivalent native-only
consumer; existing native response cases continue to cover that interface.

`Response.init_headers` remains an unresolved public API candidate in the
inventory. These inputs do not establish its public status. Passing this
workflow does not establish complete response or Starlette parity.

## Response construction and rendering evidence

The 52 input-only response consumers cover documented HTML, plain-text, nested JSON, and custom JSON rendering. Live reproduction `949d28a1-4a26-4d91-b6eb-9ec5c14ca199` had 31 divergences, 22 ordinary passes, and two passing fault contracts with no infrastructure errors. It exposed PlainTextResponse class/default constructor differences, subclass charset headers, render-time status changes, and stale caller-updated ASGI status codes. Rust now selects charset headers and current call status; the Python subclasses only forward constructor and user-render calls.

Normal selection `65b6c7fe-3a99-4e86-a11d-2c5ea89da75f` passed 210/210 ordinary comparisons and both fault contracts. It includes all new inputs plus existing response/cookie, redirect, streaming, file, body-limit, and route-limit inputs. Result SHA-256: `4a8604933bccc98a6053ef29adde1aad17a7512b0f20543150ced2d70e2e61c3`; manifest SHA-256: `df764960390be4000be6f83363805c90d0ea50a384c535aeec5334099aa26420`; normal installed package tree: `ef354f63079d761d0582d1fe6896364d55bd1a394a4c6bfa2932a184148985ae`.

Coverage MCP verified 18 newly covered Rust lines with matching source/build receipts and passing live selections: baseline 3,208/24,979, batch 2,876/24,979, union 3,226/24,979. Baseline run `e962efa3-7e72-4088-adb6-449d1bbd38fc` passed 34 ordinary comparisons; batch `275a65e8-770e-469c-a285-35387ead595b` passed 53. Both passed both fault contracts. Instrumented package tree: `9cf2ae4d7eff80093ac019ff0c91b2158882a6af8f46d09c066ab7f7553ccee2`; wheel SHA-256: `14fb00f251da1f9eadac98a5482783c1ae8977fb14f61c5ed5266b33cfddbdac`. Reports and receipts remain ignored under `build/parity/coverage/response-consumer-20261005/`. This is selected incremental coverage; full-suite coverage regression status is unknown.

The generated atlas has 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Four response documentation workflows now map to live comparisons. The fixed denominators remain 514 upstream test functions and 24 documentation pages. These counts do not establish complete behavioral coverage. `Response.init_headers` remains uncertain. See [response rendering boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full regression and benchmark gate

Clean commit `807a41bd79f0d6f9b99a9c73f9b07449f5020880` passed preflight `a1a668eb-d8f7-43b7-9f55-e2087fb18ee1`: 1,126/1,126 Python-package and 246/250 Rust-native comparisons, plus both fault contracts. There were zero failures or infrastructure errors; four existing Rust-native comparisons remain not_run. Result SHA-256: `0bcd4afb6f07ae038d35e1475e57db9c95272dc5414f145638baac30a04d4b7c`. The installed normal package tree matches the selected run above.

Benchmark `69c5837b-24df-4708-8fee-ad27ed75049f` matched and timed all 74 source/package workloads. Native timings remain not_run for all 74. Median source/package latency ratios were 0.750 for Router and 0.967 for GZip; the source was faster in 5/6 Router and 57/68 GZip workloads. Result SHA-256: `817e7aca984eb015a7cd27fbcdd0f8b7c1e72e84842192292cd098045eae52de`. See [benchmark evidence](BENCHMARKS.md). This is the active bounded contract; complete Starlette parity remains unproven.

## Remaining response boundary work

The earlier constructor batch covered changes during rendering and before
calling. The callback extension below covers in-call changes, raw-header
aliasing, and suspended-coroutine collection. The uncertain `init_headers`
candidate and other inventory gaps remain visible; these bounded workflows do
not prove complete response behavior.

## ASGI callback and coroutine ownership inputs

The `response-asgi-callbacks.yaml` extension reuses the same constructor/ASGI
operation. Its ordinary callback stimuli replace body and background values
inside start/body sends, append or replace raw headers, mutate a memoryview's
backing buffer, yield at an input checkpoint, or raise the original user
exception. The consumer records entry snapshots and retained messages, plus
public alias checks. This exercises the source's late body/background lookup
and its direct raw-header-list reference without adding runtime Python policy.

Separate input-defined ownership graphs retain a public response or suspended
coroutine. User header values or callbacks point back to that public object.
The consumer checks retention while rooted, then user weak references,
finalizers, callback finally blocks, warnings, and unraisable errors after
caller or worker collection. Native continuations must expose every owned
Python reference to GC and permit worker collection; neither condition is
established merely by a passing normal ASGI call.

The added read probes observe the source's status/header/body lookup order and
its one background read when absent versus two reads when present. Error
inputs preserve original StopAsyncIteration and CancelledError objects as
ordinary ASGI callback failures. They remain oracle parity inputs rather than
target-only fault contracts. The two existing internal fault contracts stay in
the selected verification and coverage controls.

## Live response ASGI callbacks and ownership evidence

The 92 new input-only consumers include 40 callback mutation/alias workflows, 32 public ownership graphs, 12 StopAsyncIteration/cancellation cases, and eight attribute-read probes. Initial reproduction `f0decca4-ccf3-4a00-9908-01ee0a315693` exposed divergences in all 72 initial inputs; its normal cache control and both fault contracts passed, with no infrastructure errors. Source messages alias raw headers and read body/background values after preceding sends. The former target copied headers, captured those values too early, and hid callback/header references from GC.

The Rust driver now reads live public values at the source lookup boundaries, performs late background selection, and forwards original callback errors. The facade only awaits the native call with its public response object. Core response headers/views and continuation-owned Python references are GC-visible; the sendable continuation closes suspended delegates when finalized on either collection thread. No runtime Python branching, loops, unsafe Rust, or unit tests were added.

Normal selected run `66ea8a21-2a9f-4b17-9546-5eb710171546` passed 302/302 ordinary comparisons and both fault contracts, including earlier response, redirect, streaming, file, and body-limit controls. All 32 new ownership inputs released user callbacks and guards, ran suspended callback finally blocks, and reported no unraisable errors. Result SHA-256: `e2338ab0c1e22d64387f7c6f44314ffa41cf146be8c76d17df167704f81fdf46`; manifest SHA-256: `20b6ee5681a27184002d35244dfbb29427d8da8091e5562d5b179d16eb0b70c2`; normal package tree: `16ed8c9e92d49c5240e6c8bda59161db80c9c3625611c16544146880249f6dd0`.

Coverage MCP verified 46 additional Rust lines on matching source/build receipts: baseline 3,206/25,052, batch 2,907/25,052, union 3,252/25,052. Baseline `b7e439b7-b76f-46fe-907b-13f6a16cb6f7` passed 86 ordinary comparisons; batch `f807cd3d-53f9-44b6-a60a-f35f80fb14ad` passed 93. Both passed both fault contracts. Instrumented package tree: `b35cb2de95ca2b21188fd9229565704d34eb1b9737e6a3117aa15b5013d25d11`; wheel SHA-256: `bd7c889cabdc7ce8313e2fc883479988ff3168e821c03a7e1289eff2a8300355`. Receipts and reports remain ignored under `build/parity/coverage/response-callback-20261005/`. This selected incremental union does not prove full-suite coverage regression status.

The generated atlas remains 809 rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. This batch adds behavior requirements within documented responses without relabeling unrelated backlog items. Fixed denominators remain 514 upstream test functions and 24 documentation pages. Complete Starlette parity remains unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full callback regression and benchmark gate

Clean commit `30becba23b568754874b17407a769c238697407f` passed full preflight `23659d68-7cc4-4e91-9134-7ab6ed4b8b19`: 1,218/1,218 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `2eec10dd17b8a4e0fb749af9a54a80ceb8b541ead7a5e1b30394c4e7488f747a`. Normal package tree `16ed8c9e92d49c5240e6c8bda59161db80c9c3625611c16544146880249f6dd0` matches the selected run.

Benchmark `b032a0d3-e787-4d23-b066-87b84086cb69` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.756 for Router and 0.975 for GZip; the source was faster in 5/6 Router and 46/68 GZip workloads. Result SHA-256: `18812538edde5287ec6ddb514f54cb07e04df01318c5935588f1abd9c09dcf24`. See [benchmark evidence](BENCHMARKS.md). Passing this active bounded contract does not establish full replacement parity.

## Constructor boundary audit

The earlier binding converted memoryviews with `tobytes()` before native
header construction. The pin derives content length with Python `len(body)`.
The input extension below investigates those body/header protocols. The
uncertain `init_headers` candidate remains unchanged.

## Constructor body and header protocol inputs

`response-construction-protocols.yaml` adds 132 input-only consumers across
Response, HTMLResponse, PlainTextResponse and JSONResponse. User render hooks
supply formatted, matrix, strided or released memoryviews, bytes subclasses
with input-defined length behavior, or None. Other inputs exercise explicit
length and bodyless statuses, arbitrary Python integer statuses, header mapping
callbacks that mutate public values, lower/encode exceptions and Latin-1 errors,
explicit media object identity, render-time header access/cache creation, and
direct weak references. These are ordinary source/package comparisons; user
callback failures are not target-internal fault injections.

Calling Python protocols preserves user code and original exception identity.
Rust must own the header construction order, conditional length/content-type
selection, and cached-view lifetime. The facade may initialize a Rust state
holder before invoking user render code and forward header construction to
Rust. No Python semantic algorithm is needed. The workflow observes only the
documented constructors and public attributes; `init_headers` remains an
uncertain candidate. Existing target-only fault contracts remain separate
counts in the shared selected runs.

## Constructor body and header protocol evidence

The 132 new input-only consumers exposed 104 divergences in live reproduction `37afc253-71e1-47df-8fbb-08e0400f4f18`. Its 29 ordinary passes and both fault contracts passed with no infrastructure errors. The target previously measured copied body bytes, converted header/media text too early, and created its core after user rendering. This lost Python length/method protocols, live callback mutations, original encoding errors, and render-time header/cache access.

Rust now initializes storage before user rendering, constructs headers through the source-ordered Python protocols, selects length from Python `len(body)` and live status, and retains an explicit media object. Header construction finishes before replacing raw headers and preserves an existing cached view. Python only forwards these calls and declares weak-reference support. No runtime Python branching, loops, unsafe Rust, or unit tests were added. Native rendered-byte constructors retain their additive API.

Normal selection `6de84f15-3fb2-489a-8bd8-d06195f65d6b` passed 434/434 ordinary comparisons and both fault contracts, including prior response rendering, ASGI callbacks/ownership, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `0c49d90b972fc5976fb987811ea02bbf614b506a91a4222b1801d7afbf303c1f`; manifest SHA-256: `67732db6d1e68d7c2ebce213cb3dc9cf8510de5488f628c6f6625390bfe35f6d`; normal package tree: `29cbc8f9b188bc02383d451aea70605502ff577ca12eadb3956dd134cc0d7170`.

Coverage MCP verified 27 additional Rust lines with matching source/build receipts: baseline 3,278/25,179, batch 2,882/25,179, union 3,305/25,179. Baseline `a971621e-957e-4366-a602-6c8a7c476478` passed 178 ordinary comparisons; batch `b24af4a4-8bea-467a-b4bf-5c78c3144cf9` passed 133. Both passed both fault contracts. Instrumented package tree: `4a5c520948883a92183b654d412c3e35b3aa61124f087dd2de1b8c26d830f2ab`; wheel SHA-256: `40d05a57c4a2c49b5fb4b9a9a67c52a946997b709947fad5e453ce5ee8826367`. Reports/receipts remain ignored under `build/parity/coverage/response-construction-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas has 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. `Response.init_headers` remains uncertain; complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full constructor regression and benchmark gate

Clean commit `fb0210c6c0a0ecc67572c0b491641fcc9e896de9` passed full preflight `bc712157-2daf-43d4-950a-67ed70028b2d`: 1,350/1,350 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `c40cd486bb5091c5ba322c8ef8fdca8c04904bbc37958bdfc0622b816119a486`. Normal package tree `29cbc8f9b188bc02383d451aea70605502ff577ca12eadb3956dd134cc0d7170` matches the selected run.

Benchmark `fab7a6a6-da8c-4f06-8c24-860ae83438dc` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.766 for Router and 0.959 for GZip; the source was faster in 5/6 Router and 59/68 GZip workloads. Result SHA-256: `32287fc2e00e5486444af0a583d2d9e1210f6938d86c1dfecfff64fb8cd6c980`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

## Remaining constructor boundary work

The attribute workflow below covers user raw-header accessors, public header-view
cache changes, and constructor attribute interception for the four documented
base response classes. Streaming/File/Redirect subclass interception and other
cookie conversion/type protocols still need input-only comparisons.
`Response.init_headers` remains uncertain in the inventory; the current
workflows do not establish all Python subclass boundary behavior.

## Attribute interception and public header-view inputs

`response-attributes.yaml` supplies user-defined attribute read/write hooks and
raw-header properties to the four documented response classes. Public consumer
actions read `headers`, replace `raw_headers`, or delete `raw_headers`; they
never read or modify native state or directly manipulate a private cache.
User hooks observe names that the source itself accesses, including its cache
field, and can reject names outside an input allow-list or raise an original
input-defined exception on a selected attribute access. The hooks are ordinary
Python user code, run independently against source and target.

The source's public header property is established by
`docs/middleware.md:299-301,613-632` and `tests/test_responses.py:188-199`.
Python must invoke arbitrary user attribute hooks and preserve ordinary public
attribute storage and deletion. Rust owns cache selection, raw-view construction,
callback ordering, and error propagation. Native
storage access must avoid exposing implementation-only fields to those hooks.
Base rendering must read charset only when encoding requires it. These
workflows do not promote `init_headers` from its uncertain inventory status.

## Response attribute and header-cache evidence

The 136 new input-only consumers cover attribute interception, conditional charset reads, public header-view caching and aliasing, raw-header replacement/deletion, finalizer reentry, constructor header hooks, cookie override dispatch, and cookie conversion reentry/control characters across four documented response classes. Initial reproduction `7dc3041f-f0d7-4304-b686-50b7b5a3158b` exposed 70 divergences with 19 ordinary passes; a separate eight-case finalizer reproduction `59bb16ff-55de-45e8-9bd8-5431969adf7e` exposed eight divergences with one ordinary control pass. Both runs passed both fault contracts without infrastructure errors. The former raw-header setter held a native mutable borrow while dropping user values, so their finalizers could encounter a PyO3 borrow panic.

The facade invokes the user's constructor header hook as required calling glue. Rust selects the header cache through source-ordered user attribute accesses, forwards cookie deletion to the user's method, and reads charset only when encoding content. Public values use ordinary Python attribute storage, which preserves their dictionary presence, deletion, and finalizer callbacks without a Python semantic algorithm. Rust accesses its storage holder without invoking user attribute hooks. Cookie construction uses temporary native storage, preserves both max-age string conversion boundaries, and appends to the current public raw-header list after conversion. No runtime Python branching, loops, unsafe Rust, or unit tests were added.

Normal selection `b91ac23e-b116-43a8-be87-2a58c562d7d2` passed 570/570 ordinary comparisons and both fault contracts, including prior rendering, ASGI callback/ownership, construction-protocol, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `c43934997a80e3aae1f7d9d0dcf9acc8fd7d7255be2a171b101fb9372f2c224d`; manifest SHA-256: `7fbf5a69322f70e9f5297606adb108c907e7f4f0022cbc90ae12e054fe5f5163`; normal package tree: `f39c1c88aec7a7f3a2e60b825eaa68ba0442e07dfb2b86fdacbcb0bbce533187`.

Coverage MCP verified 10 additional Rust lines with matching source/build receipts: baseline 3,235/25,239, batch 3,041/25,239, union 3,245/25,239. Baseline `829844f5-ce76-4ca4-b1e8-3432a7063f48` passed 310 ordinary comparisons; batch `4dd9209a-7635-4bfe-8eff-2f1b49433b95` passed 137. Both passed both fault contracts. Instrumented package tree: `4772847b93f269e0ee61bf25b8a554f4dae30b4e35c2c88d3c00102ca0e15cc4`; wheel SHA-256: `03117b1709b60f9da7d572a1eecc0e03c391bbf84697242bc0cb1d97b2541b08`. Reports and receipts remain ignored under `build/parity/coverage/response-attributes-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas remains 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. `Response.init_headers` remains uncertain; forwarding the constructor hook does not establish its public status. Streaming/File/Redirect subclass interception and other cookie conversion/type protocols need further comparisons. Complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full attribute regression and benchmark gate

Clean commit `09191fd4968b0d309bb336c0f693aeb0cd606d4e` passed full preflight `8eb08944-aa22-4802-9913-760667c7e4bb`: 1,486/1,486 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `177bab1dd7bec1b19687a4c1dfe0be91ede4f0d66636b5f12fdbe776a1331335`. Normal package tree `f39c1c88aec7a7f3a2e60b825eaa68ba0442e07dfb2b86fdacbcb0bbce533187` matches the selected run.

Benchmark `4d4c57cc-1dfb-4c01-b644-f8b07c4a08bb` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.759 for Router and 0.975 for GZip; the source was faster in 5/6 Router and 54/68 GZip workloads. Result SHA-256: `f529e5553e5c4982a1ba8c86358b42769d678ed32e52681b8d6380e19e9e38fc`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.

## Cookie argument conversion and serialization evidence

The 98 input-only consumers exercise original cookie value/attribute conversions, empty-value equality, string subclass formatting and translation, flag truth testing, integer subclasses, original callback errors, and reentry through documented cookie methods. Initial reproduction `44098d49-02ee-427d-958a-7230be0470ac` exposed 78 divergences in the first 81 new inputs, with 4 ordinary passes including the control and both fault contracts passing, without infrastructure errors. A fixed input clock makes deletion/integer expiry deterministic on both sides; outputs remain live and exact.

Rust now retains Python argument objects through source-ordered assignment and deferred serialization, selects cookie attributes and quoting, and invokes the active interpreter's value representation protocols. CPython compiles literal string pairs into str conversion followed by its format protocol, which matters when a string subclass returns itself. Raw-header append selection follows those conversions. User callbacks run without a native response borrow. The runtime Python facade is unchanged; no Python branching, loops, unsafe Rust, or unit tests were added.

Normal selection `8a4bc151-3147-4c94-8f90-c5b1677ac7cc` passed 668/668 ordinary comparisons and both fault contracts, with no failures or infrastructure errors. It includes previous rendering, attribute/cache, ASGI ownership, construction-protocol, redirect, streaming, file, body-limit and route-limit controls. Result SHA-256: `ccec1f895844b0fd0acb4fe83f943162d8b4149d7d09d3778f5f9f41bfa45a01`; manifest SHA-256: `da6c7d67fb4ce2b49d0b10bcd4ec63db451e67863c5e9d9927b2914f422c6c4b`; normal installed package tree: `0d606843ce84425833aa38790784a5fef20173dfc6fa8837587e03fe2161eba4`.

Coverage MCP verified 20 additional Rust lines with matching source/build receipts: baseline 3,231/25,392, batch 3,004/25,392, union 3,251/25,392. Baseline `4bd2dded-21df-4ea4-9841-ee693de53c0b` passed 446 ordinary comparisons; batch `096e641a-e283-4033-af86-a6c5d005b58f` passed 99. Both passed both fault contracts. Instrumented package tree: `a52ae84285111153f866ef4a64d50a93cdc81ec920911c707c889275a0254bb9`; wheel SHA-256: `331c3aa4de2fd664057a7ff942fc2f4bcf399a97568ca7bea445bfbd79940778`. Reports and receipts remain ignored under `build/parity/coverage/response-cookie-protocols-20261005/`. This selected incremental union does not establish full-suite coverage regression status.

The generated atlas remains 809 source rows: 694 existing mappings, 52 source-backed not_applicable rows, and 63 backlog rows. Fixed denominators remain 514 upstream test functions and 24 documentation pages. Arbitrary cookie key objects, supplied Morsel values, other interpreter versions, and Streaming/File/Redirect subclass interception need further comparisons. `Response.init_headers` remains uncertain. Complete response and Starlette parity remain unproven. See [response boundary](RESPONSE_RENDER_BOUNDARY.md).

### Clean full cookie regression and benchmark gate

Clean commit `e83cb743223ca332e3650713424ff79225e1d33d` passed full preflight `95c16ff3-05c1-478b-a759-2a97f5d7dd6f`: 1,584/1,584 Python-package comparisons, 246/250 Rust-native comparisons, and both fault contracts. There were zero failures or infrastructure errors. Four existing native callable cases remain not_run. Result SHA-256: `7d2db21ccbefcd7f0971ea239cb2d7f0a4e36d44e0b722f5c9d81c6ed207d90d`. Normal package tree `0d606843ce84425833aa38790784a5fef20173dfc6fa8837587e03fe2161eba4` matches the selected run.

Benchmark `7b617ac7-8af2-42c5-8d52-4c0a9e8aac78` matched and timed all 74 source/package workloads. All 74 native timings remain not_run. Median source/package latency ratios were 0.771 for Router and 0.979 for GZip; the source was faster in 5/6 Router and 45/68 GZip workloads. Result SHA-256: `b0f666021fd4a6056787f76fd5193a0fe56e90998fba2474aee9372edd0d9fa9`. See [benchmark evidence](BENCHMARKS.md). These bounded comparisons do not establish full replacement parity or general speed superiority.
