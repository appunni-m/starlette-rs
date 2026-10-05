# Response rendering and mutable public attributes

Authority: Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.
The documented consumers are `Response`, `HTMLResponse`, `PlainTextResponse`,
and `JSONResponse`, including the custom JSON render example in
`docs/responses.md:96-118`. Their constructor and ASGI implementation are in
`starlette/responses.py:29-200` in the pinned checkout.

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

## Next constructor boundary audit

The binding currently converts memoryviews with `tobytes()` before native
header construction. The pin derives content length with Python `len(body)`.
Formatted memoryviews and bytes subclasses therefore need input-only consumer
comparisons before claiming complete render/header conversion behavior. The
uncertain `init_headers` candidate remains unchanged.
