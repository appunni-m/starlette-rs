# Benchmark mapping

The active `parity-input@66` manifest declares 2,628 cases across 452 parity
inputs, 1,467 requirements, and SHA-256
`474c5a1e8f413ab0a02cb0b6ca5e9c46b85a5e29f26bfde93d4cd3e735faf12f`. The
grouped @66 local parity run passed every executable comparison but left the
two macOS surrogateescape filename rows not run; full parity is not yet proven.
Local coverage runs produced Rust-native and CPython 3.12 reports, but Coverage
MCP marks them source-unverified and test-unknown because the plans were not
ingested. The @66 74-workload benchmark awaits a clean committed parity gate.
The latest completed benchmark used @64: it measured all 74 declared
source/package workloads (six Router and 68 GZip); all 74 Rust-native rows are
`not_run` because the native API has no equivalent ASGI workload boundary.
Coverage MCP marked the imported @64 reports' source identity unverified and
test status unknown because no matching source/build receipt was ingested.
These results cover only the declared @64 slices and do not prove full
Starlette replacement parity or @66 behavior.

The pinned Starlette 1.6.0 benchmark suite has six Router workloads and 68
GZip workloads. The dedicated runner measures all 74 against both pinned
Python source and the installed `starlette-rs-py` package after exact
input-backed correctness gate. Before timing, it requires every selected
`python-package-cpython312` case to pass or be an explicit two-sided
source/platform skip; Rust-native outcomes remain recorded separately and do
not block this source/package lane. This proves that source/package slice only.
Rust-native remains `not_run` for all 74
because its public dispatch boundary is not equivalent, and the overall
Starlette replacement remains `not_proven`.

Run `make parity-inputs` to generate local benchmark JSON, then reproduce the
run with `python3.12 -m scripts.parity.cli benchmark-upstream`. The result is
written to `build/parity/upstream-benchmark-result.json`; it records source
revision `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, pinned benchmark-file
hashes, active input-catalog and manifest hashes, and a target checkout
identity containing the Git revision, dirty marker, and working-tree SHA-256.
It verifies that this identity remains unchanged during the run.

<!-- generated-upstream-benchmark:start -->

## Latest paired benchmark run

Run `40f41f01-bb35-4617-ab01-9b87f9e21bdd` completed from `2026-10-16T22:07:07.906Z` through `2026-10-16T22:23:41.804Z`.

The source oracle is Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The target checkout is clean revision `6310c68f9b036724fe01f4fd97a49206d7cae7f7` with working-tree SHA-256 `c42dcf91e5cc2f66c689492bd48c0781312575e70695262fba322887d89ea9b4`.

The runner measured 74/74 source/package workloads: 6 Router and 68 GZip. It reported 0 failures, 0 source/package not-run rows, and 74 Rust-native not-run workload rows because the native API does not expose these equivalent ASGI workload boundaries.

The correctness preflight `5e280d8f-55d2-4cbc-b035-4ad97b3d7829` selected 2971 profile comparisons, with 2969 passed, 0 failed, 0 infrastructure errors, and 2 not-run rows.

The preflight passed 2595/2596 Python-package comparisons and 374/375 Rust-native comparisons; 1 Python-package and 1 Rust-native rows were `not_run`.

The median source/package latency ratio was 0.358 for Router and 0.972 for GZip. Source latency was lower in 5/6 Router and 56/68 GZip workloads. Normalized observation hashes matched for 74/74 measured workloads.

Manifest SHA-256: `6d591e84da1a97cc73a6f04f9b0280704c214c1b1f793c1a9e16b4c6ab42e3b5`. Benchmark input SHA-256: `adafb558a4fadd4fe8c1a956dd03eced2039711440ac7cce2861f1124cc00ed2`. Installed wheel SHA-256: `27e6bd2e91f8f111bae3496ee0b79d42b9344dd8cc9cea601a39395077f0b319`. Result artifact SHA-256: `db615bdd1ba1673fe03662367c783a45efe6dad1343642485e2a160e875111d4`.

These are workload-specific local timings, not a general performance claim, CodSpeed measurements, or evidence of full Starlette parity.

<!-- generated-upstream-benchmark:end -->

Earlier invocation results are not retained by the runner, which overwrites
the ignored local result artifact. Only the generated latest-run evidence
above is treated as auditable benchmark data. The
input-only workload catalog is
[`starlette-upstream-workloads.yaml`](../tests/fixtures/sources/benchmark/starlette-upstream-workloads.yaml);
the source-invocation inventory is
[`router-gzip-benchmark-workloads.csv`](atlas/reviews/router-gzip-benchmark-workloads.csv).
The YAML catalog is the authored source; its JSON form under
`build/parity/inputs/benchmark/` and result artifacts under `build/parity/`
are ignored local outputs and are not committed.

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

The parity-matrix status is nested under `parity_matrix.status`. A passing
five-profile matrix does not change the top-level replacement status; coverage
and package qualification remain separate evidence requirements.

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
