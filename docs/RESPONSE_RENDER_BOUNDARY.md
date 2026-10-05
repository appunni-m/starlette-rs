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

This batch changes attributes during rendering and before calling. It does not
cover changes made inside `send` callbacks, raw ASGI header-list aliasing, or
background replacement during a call. Those require additional input-only
consumer comparisons before claiming complete response behavior. The uncertain
`init_headers` candidate and other inventory gaps remain visible.
