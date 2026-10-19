# Benchmark mapping

The active `migration-parity/manifest@6` declares 2,759 unique cases across
471 parity inputs, 1,497 parity requirements, and two benchmark inputs. Its
SHA-256 is
`4f7048da1cf93e7c3392a91fc3937ba32d2af2aca70c71eaa23dcd609ae718ad`. Full
verification workflow
[#22](https://github.com/appunni-m/starlette-rs/actions/runs/39271192252)
is queued against predecessor revision `6ed5b7e9`; it predates the current
adapter relocation and command update. The benchmark below is historical and
uses an older manifest and target revision. Run all 74 workloads only after
the final source candidate passes full parity and the eligible-line coverage
union. No current-worktree benchmark result is proven.

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

Run `4fc92237-2c25-491c-bde3-3064d29535d2` completed from `2026-10-19T11:29:24.066Z` through `2026-10-19T11:31:49.284Z`.

The source oracle is Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The target checkout is clean revision `33f97fa8960eb4847f3dc54f70f8c697f9bfeeaf` with working-tree SHA-256 `5afb0de102e4fce8ad9045c350ab87ecf9327d2c66e555189df5e2fb0acd2049`.

The runner measured 74/74 source/package workloads: 6 Router and 68 GZip. It reported 0 failures, 0 source/package not-run rows, and 74 Rust-native not-run workload rows because the native API does not expose these equivalent ASGI workload boundaries.

The correctness preflight `913d7d3c-c70d-43eb-a1ed-badb2f3e5698` selected 2 profile comparisons, with 2 passed, 0 failed, 0 infrastructure errors, and 0 not-run rows.

The preflight passed 1/1 Python-package comparisons and 1/1 Rust-native comparisons; 0 Python-package and 0 Rust-native rows were `not_run`.

The median source/package latency ratio was 0.289 for Router and 0.976 for GZip. Source latency was lower in 6/6 Router and 44/68 GZip workloads. Normalized observation hashes matched for 74/74 measured workloads.

Manifest SHA-256: `7bf7ede10d4cd09f983ee413a26d0a88cc07cbb1690fc125e45a1ec0b8d1ecc5`. Benchmark input SHA-256: `adafb558a4fadd4fe8c1a956dd03eced2039711440ac7cce2861f1124cc00ed2`. Installed wheel SHA-256: `09541fcba0af111610eed0fb11a5e53753f958fe835ae665f9707ea91055ce2b`. Result artifact SHA-256: `3c19994a5097ff85b0a908299aecf075c6b7e6a56840328f923d7883b68d4a47`.

These are workload-specific local timings, not a general performance claim, CodSpeed measurements, or evidence of full Starlette parity.

<!-- generated-upstream-benchmark:end -->

## Direct ASGI smoke measurement

Run `ea7a4051-a3b0-45f0-9508-ac3b4bd0280c` measured the declared direct-ASGI
`GET /hello` dispatch on clean target revision `fd024b83a3ecc15b75a4f6e09abf8c4c8dacbb12`.
Across 30 samples of 100 dispatches, the source median was 15,328.935 ns per
dispatch and the installed package median was 55,798.96 ns. The package measured
3.640 times slower at this boundary. Rust-native was not comparable because its
public API does not expose this ASGI call boundary. The result artifact SHA-256
is `1041938751cbc618131cb4c081861dfd72c6d2debcfa9ff31e1c71f3e919bb96`.

This one-workload smoke result is separate from the completed 74-workload
Router/GZip result above. It records a performance regression requiring
follow-up optimization; neither benchmark demonstrates full Starlette parity.

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
