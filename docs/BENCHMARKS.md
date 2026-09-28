# Benchmark mapping

The pinned Starlette 1.6.0 benchmark suite has six Router workloads and 68
GZip workloads. The dedicated runner measures all 74 against both pinned
Python source and the installed `starlette-rs-py` package after exact
input-backed correctness gates. Before timing, it requires every selected
`python-package-cpython312` parity case to pass; Rust-native outcomes remain
recorded separately and do not block this source/package lane. This proves
that source/package slice only. Rust-native remains `not_run` for all 74
because its public dispatch boundary is not equivalent, and the overall
Starlette replacement remains `not_proven`.

Run `make parity-inputs` to generate local benchmark JSON, then reproduce the
run with `python3.12 -m scripts.parity.cli benchmark-upstream`. The result is
written to `build/parity/upstream-benchmark-result.json`; it records source
revision `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, pinned benchmark-file
hashes, and active input-catalog and manifest hashes. The latest attempt,
`2311eb92-753a-4d59-a882-a0d06ef1970e`, ran from
`2026-09-28T20:54:10.030Z` to `2026-09-28T20:54:46.122Z` and finished
`not_proven`: 0 of 74 workloads were measured and all 74 were `not_run` because
the fresh correctness preflight did not pass. Preflight run
`8118a073-211f-48a9-b9b1-a1c52dddbbe3` selected 267 comparisons: 259 passed,
two debug traceback cases failed, six unsupported Rust-native rows were
`not_run`, and there were zero infrastructure errors. Since the gate failed,
the source and installed-package benchmark subjects were not started;
Rust-native is also `not_run` for all 74 because its public dispatch boundary
is not equivalent. This attempt makes no performance claim. The package wheel
SHA-256 was
`a65ef46ca4c84d14f213b6756270805d7bd65068d849c179280a0de7918db81d`.

The preceding full parity run `a217b1d7-5baa-45e2-a3c1-7f373b8a5d5d` selected
276 comparisons after adding nine lifecycle cases: 268 passed, two debug
traceback cases failed, six Rust-native rows were `not_run`, and there were
zero infrastructure errors. The current run
`efd76095-d4d6-48a2-951f-030dde4bb49a` selected 282 comparisons after adding
six generator-protocol cases: 274 passed, the same two debug traceback cases
failed, six Rust-native rows were `not_run`, and there were zero infrastructure
errors. The benchmark command was not rerun, and its 74 workloads remain
unmeasured until the two Python-package failures are resolved.

An earlier run, `5f88f441-8747-4d0f-9e1b-fb7153aeb218`, ran from
`2026-09-28T12:04:48.059Z` to `2026-09-28T12:06:19.166Z` and measured 74/74
workloads under the then-current comparison policy. Its preflight,
`e45ffb4f-29e7-4267-b84d-91ed40d9ef97`, selected 181 comparisons: 175 passed,
zero failed, zero infrastructure errors, and six Rust-native rows were
`not_run` (package 118/118; Rust-native 57/63). That result is historical and
does not replace the latest failed preflight. Target identities came from
dirty local trees, so neither run is clean aggregate or release proof. The
input-only workload catalog is
[`starlette-upstream-workloads.yaml`](../tests/fixtures/sources/benchmark/starlette-upstream-workloads.yaml);
the source-invocation inventory is
[`router-gzip-benchmark-workloads.csv`](atlas/reviews/router-gzip-benchmark-workloads.csv).
The YAML catalog is the authored source; its JSON form under
`build/parity/inputs/benchmark/` and result artifacts under `build/parity/`
are ignored local outputs and are not committed.

| Evidence | Artifact | Result |
| --- | --- | --- |
| Router/GZip upstream runner, latest attempt | `build/parity/upstream-benchmark-result.json` | `not_proven`; run `2311eb92-753a-4d59-a882-a0d06ef1970e`; 0/74 measured, 74 `not_run`; preflight `8118a073-211f-48a9-b9b1-a1c52dddbbe3`: 259 pass, 2 fail, 6 unsupported native rows `not_run` |
| Router/GZip upstream runner, earlier completed run | `build/parity/upstream-benchmark-result.json` | Historical `completed`; run `5f88f441-8747-4d0f-9e1b-fb7153aeb218`; 74/74 measured before the stricter current preflight; not current gate evidence |
| Direct-ASGI smoke correctness | `build/parity/benchmark-correctness-result.json` | Historical smoke gate; separate from the 74-workload runner |
| Direct-ASGI smoke measurement | `build/parity/benchmark-result.json` | Historical smoke result `not_proven`; does not describe the completed upstream runner |

The custom runner uses one warmup and seven samples per workload. It measures
100 operations per sample for the six Router workloads and one operation per
sample for the 68 GZip workloads. It reports nanoseconds per operation and
distribution statistics, and compares source/package medians. Measurement
order alternates between source-first and package-first by validated catalog
position; each measured comparison records the actual order. The recorded
machine was macOS 15.7.7 arm64
with CPython 3.12.13 and 12 logical CPUs. These are matched local timer
measurements, not CodSpeed results; no CodSpeed CPU, memory, or allocation
metrics were collected. Treat them as workload-specific evidence, not a
general performance claim. `aggregate` validates the result artifact but
continues to report the overall replacement as `not_proven` because the full
compatibility denominator is still incomplete.

Correctness gates run before timing and outside timed regions. Build the app,
payload, middleware, and response input before timing where upstream does so.
Router creates a fresh scope for each dispatch because it mutates the scope;
GZip follows the pinned benchmark's scope reuse and creates fresh response
message containers as required by that workload. Record machine,
OS/architecture, runtime/compiler, dependencies, features, fixture/input
digests, samples, and distribution statistics. Keep in-process ASGI results
distinct from real-server throughput.

## Current direct-ASGI smoke boundary

The currently indexed smoke workload resolves its app, response cookies,
lifespan schedule, HTTP scope, and receive messages from the linked parity
case. It constructs the app and completes lifespan startup before warmups and
samples, keeps lifespan active during each dispatch, then shuts it down after
timing. Each call creates fresh scope, receive, and send containers. It checks
that every call emits the same ASGI events as the exact source/package probe
immediately after each timer stops.

The separate smoke timer measures an in-loop `await app(scope, receive,
send)`. It includes fixture-to-ASGI scope and message materialization, callback
creation, and response collection. It excludes app construction, lifespan
startup and shutdown, and event normalization/comparison. The pinned routing
runner instead wraps each dispatch in `loop.run_until_complete`; the smoke
timer excludes that per-call loop-entry overhead, so its numbers do not
reproduce the upstream timings. It is an in-process Python ASGI dispatch
measurement, not a Rust-kernel-only result or real-server throughput.

## Earlier completed run: 74-workload Router/GZip benchmark lane

The earlier run's input catalog maps all 74 pinned source IDs to input-only
workloads. At that time, the source and installed package matched the declared
observations for all 74 correctness gates, then both were measured using the
same declared timer policy. The artifact
records raw and post-normalization observation hashes:
73 cases have identical raw hashes, while `test_routing_method_not_allowed`
uses the declared `Allow` token-order normalization and has matching normalized
hashes. That historical result accounts for all 74 as measured, with zero
failed and zero not-run workloads. In the latest attempt, the fresh parity
gate failed before measurement, so none of those earlier timings serve as
current correctness-gated performance evidence. Rust-native remains explicitly
`not_run` on each row because the public boundary is not equivalent. The strict aggregator accepts
the artifact, while the overall project status remains `not_proven` because
the full compatibility denominator is incomplete.

The public Python `Router.__call__` path used by the six upstream Router
benchmarks runs through the Rust matcher, including default string parameters.
The 68 GZip measurements follow the pinned payload and configuration
workloads. This lane does not prove Python request-handler parity or make a
Rust-native performance claim.

## Router: six workloads

The table is four routes per resource group: 120 routes (30 groups) and a
20-route small app (5 groups).

| Upstream case | Route table | Input | Correctness gate |
| --- | ---: | --- | --- |
| `routing_static_early` | 120 | `GET /resources0` | ASGI response status 200 |
| `routing_static_late` | 120 | `GET /resources29` | ASGI response status 200 |
| `routing_param_late` | 120 | `GET /resources29/123/items/first` | ASGI response status 200 |
| `routing_miss` | 120 | `GET /no/such/path` | ASGI response status 404 |
| `routing_method_not_allowed` | 120 | `DELETE /resources29` | ASGI response status 405 |
| `routing_small_app` | 20 | `GET /resources4/7` | ASGI response status 200 |

Use one loop per runner as upstream does, but generate a fresh scope per
dispatch because routing mutates it. Keep response status validation outside
the timed call.

## GZip: 68 workloads

Use deterministic valid JSON, repeated text, and high-entropy bytes. Compress
all levels 1–9 at 1 MiB (27 workloads); levels 1, 6, and 9 at 32 KiB, 256 KiB,
5 MiB, and 10 MiB (36 workloads); and four 499-byte/1-MiB bypass cases. Add one
event-loop responsiveness workload with a 10 MiB JSON response competing with
a tiny response. Total: 63 compression + 4 bypass + 1 responsiveness = 68.

| Family | Input and configuration | Required correctness observation |
| --- | --- | --- |
| Compression | JSON / text / incompressible; size-level matrix above; `minimum_size=0` | GZip header, ASGI event shape, decompressed bytes equal input |
| Bypass below minimum | 499 bytes; default 500-byte threshold | Messages unchanged, no GZip encoding |
| Existing content encoding | 1 MiB, `Content-Encoding: br` | Messages unchanged |
| Event stream | 1 MiB `text/event-stream` | Messages unchanged |
| Path send | 1 MiB path-send event with extension enabled | Path-send event unchanged |
| Event-loop responsiveness | 10 MiB JSON at level 9 plus tiny `{}` response | Time to tiny response; validate both afterward (no pending-state assertion) |

Payload construction and app setup remain outside timing. Each measured
invocation follows the source workload's scope/message reuse policy; validation
and decompression remain outside timing. The custom runner records wall-clock
samples only, not CodSpeed CPU, memory, or allocation measurements.

## Downstream consumer scope

FastAPI `0.141.1` is recorded as a pinned downstream reference in
[`UPSTREAM.md`](UPSTREAM.md), but FastAPI and Pydantic behavior and benchmarks
are outside this Starlette replacement's current scope. The benchmark evidence
here covers pinned Starlette 1.6.0 workloads only.
