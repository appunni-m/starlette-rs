# Staged implementation plan

The objective is a full replacement for the pinned Starlette 1.6.0 Python
surface and ordinary ASGI contract. The pre-release `starlette-rs` API is
greenfield and carries no backward-compatibility guarantee. FastAPI and
Pydantic are outside this project's scope.

## Execution order and current status

Current source and contract status (2026-10-20): the runtime/input candidate
`b0dab3263d91584a2b524cfd761d936bb5f73278` is pushed on `main`. Runtime
behavior still includes the CORS fix from `62b091c8` and matches candidate
`e9f8b181`; `b0dab326` changes one input definition to use lowercase raw ASGI
header names. Later status-documentation commits do not alter this candidate.
The active manifest remains at SHA-256
`ba792771a682e431b4ad1ba3be6a4e0cbe86ed9a71651a5da329571194ff22a5`.
The older `codex/c5j3-focused-coverage` branch remains at `67abf21e`; the four
`preserve/dangling-*` refs remain local and on origin at `014181a0`,
`04d04f6f`, `97185945`, and `bd49e624`.

The required execution order is to finish implementation and input authoring,
run the complete parity matrix and fix mismatches together, measure the six
coverage profiles and eligible-line union, then run the full benchmark on that
verified candidate. The current manifest SHA-256 is
`ba792771a682e431b4ad1ba3be6a4e0cbe86ed9a71651a5da329571194ff22a5`. It
declares 2,786 cases, 472 parity input files, 157 compatibility operations,
18 Rust-native operations, 1,505 parity requirements, and six target profiles.
These declarations and the source-mapping inventory do not prove runtime
parity or implementation completeness.

The current source change fixes CORS propagation of the original
`StopAsyncIteration` from an awaited downstream app, preserving its message
and clearing the continuation's pending state. It is committed as
`62b091c8`. The latest input-only correction is `b0dab326`; the
`make contract-check` command passes on that tip with 2,786 cases and 472
parity inputs. Earlier on this source candidate, `cargo fmt --all -- --check`,
`cargo check -p starlette-rs-py`, `make lint`, `make docs-check`, and
`git diff --check` passed. Those static checks do not establish runtime parity.
The earlier native adapter/fault diagnostics were audited against `67abf21e`;
the checked-in adapter and active inputs already handle those shapes.

GitHub Actions workflow [#27](https://github.com/appunni-m/starlette-rs/actions/runs/39454724121)
was dispatched on `main@67abf21e` before the CORS fix. Four of five CPython
jobs have completed and failed (3.10–3.13); CPython 3.14 is still running.
The inspected 3.10 artifact reports the CORS message mismatch and the
uppercase-header input mismatch. Current-candidate workflow
[#28](https://github.com/appunni-m/starlette-rs/actions/runs/39455513605)
was dispatched on `main@e9f8b181` and remains queued behind #27. It does not
include the input correction from `b0dab326`, so neither run proves the exact
current `main` contract. After #28 completes, run the complete parity matrix
on `b0dab326` and repair any mismatches together. Coverage remains gated on
full parity; the final benchmark remains gated on both parity and the
eligible-line coverage union.

The complete 74-workload correctness-gated benchmark is historical evidence
from source candidate `943c1c26faadb7c9cd82303283fb365955fec662`, with run
[`b5a4637e-6adf-4735-93f5-3966681a6113`](BENCHMARKS.md). It passed its 2/2
comparison preflight and measured all 74 Router/GZip source/package workloads.
Later runtime changes and the expanded contract make it stale for the current
candidate; its ratios remain workload-specific history, not a current
performance claim. The active goal remains open in Kata `5fzj`; keep
implementation and unexecuted comparisons explicit until the current evidence
phases are complete.

### Historical source and contract status (2026-10-19; superseded)

The compatibility authority is Starlette 1.6.0 at commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The active contract has 2,759
cases across 471 parity inputs, two benchmark inputs, 157 compatibility
operations, 17 Rust-native operations, six target profiles, and 1,497 parity
requirements. Its SHA-256 is
`4f7048da1cf93e7c3392a91fc3937ba32d2af2aca70c71eaa23dcd609ae718ad`. The
generated inventory reports 999 API candidates (564 supported), 867 source
rows (811 mapped, 56 source-backed `not_applicable`), and zero fixture-backlog
rows. It covers all 30 upstream test modules, four shared test-support
modules, and 24 documented pages. The pinned denominators remain 514 upstream
test functions and 24 documented pages.

`make source-inventory-check` passes for the current worktree. It validates
the source catalog and input structure; it does not execute behavioral
comparisons and reports zero parity passes. Full verification workflow
[#22](https://github.com/appunni-m/starlette-rs/actions/runs/39271192252) is
queued on predecessor commit `6ed5b7e9`. Its checkout predates the move of the
development-only Python target adapter to `scripts/parity` and the matching
manifest command update. Workflow #21 passed its five CPython parity profiles
on older commit `2da349cf`; five Python coverage profiles are still running on
that same older commit. Neither workflow proves the current worktree.

At the 2026-10-19 checkpoint, the project reported implementation, full
parity, eligible-line coverage, and benchmark as outstanding. That checkpoint
predates the benchmark-first run and active workflow #23 recorded above; its
workflow details remain bounded to the revisions and inputs they name.

Kata `9tnt` records the 253-site `clippy::arithmetic_side_effects` hardening;
the three implementation children (`d50v`, `y532`, and `7q68`) are closed
after grouped verification. Workspace Clippy now denies that lint. After the
date-format repair, `make lint` and `make source-inventory-check` passed on
that prior checkpoint. The inventory includes the input-only FileResponse HEAD
multipart case for Content-Length values beyond u64. These checks validate the
implementation structure and contract, not runtime parity.

The previous full parity workflow #15
([`39166146776`](https://github.com/appunni-m/starlette-rs/actions/runs/39166146776))
completed against `df5e784609f436f8ff80164896201de88548e4cd`, not this
candidate. It passed all five source-parity profiles (15,726/15,726 exact
comparisons and 22/22 fault contracts) but its CPython 3.14.8 coverage profile
reported four cookie callback-error mismatches. That profile produced no
coverage receipt; these results are historical evidence for the earlier
target.

The focused follow-up established that the mismatch was caused by the target
parity adapter's post-case package identity scan running before result JSON
serialization. The scan collected an exception traceback cycle and finalized
the owned cookie before the adapter snapshot; it was absent from the oracle
path. Commit `b508db19bd01d265a833048b052160b44c62bd78` moves the same integrity
check after JSON serialization and before stdout. Focused workflow
[`39198830087`](https://github.com/appunni-m/starlette-rs/actions/runs/39198830087)
(#11) passed all four Response, HTMLResponse, PlainTextResponse, and
JSONResponse callback-error inputs under CPython 3.14.8 (4 passed, 0 failed).
The diagnostic sidecar shows the converted cookie live after JSON encoding and
finalized only during the later identity check. Its selected-case coverage
result is `not_ingested`, and the workflow verified that no full coverage
receipt was created. This focused diagnostic alone does not prove full parity
or coverage.

Full verification workflow
[`39199357775`](https://github.com/appunni-m/starlette-rs/actions/runs/39199357775)
(#16) completed against candidate `b508db19bd01d265a833048b052160b44c62bd78`
and the pinned Starlette source. It ran the complete parity matrix on CPython
3.10–3.14, followed by the six coverage profiles and eligible-line union. All
five parity jobs passed, and their receipts were checked with the strict
aggregate command. The ignored `build/parity/status-report.json` records
`parity_matrix.status: proven` on manifest SHA-256
`6e60640f9f8a7919ea500398aaace0942f5edf707fb92e6659307eb0dd561984`, oracle
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, and clean target revision
`b508db19bd01d265a833048b052160b44c62bd78`: 15,726/15,726 comparisons and
22/22 fault contracts passed, with zero failures, `not_run` rows, or
infrastructure errors. All six Rust-native and CPython coverage-profile jobs
completed, but the eligible-line union failed because of path ordering. A
diagnostic union over those receipts measured 27,815/34,861 eligible lines
(79.7883%), leaving 7,046 uncovered lines across 68 of 69 eligible paths. It
is not a passing coverage gate.

Commit `07c5b333d79a7890531c08936c7d594ba4c11a32` fixes the union verifier's
line-path ordering, and workspace-quality workflow
[`39209067276`](https://github.com/appunni-m/starlette-rs/actions/runs/39209067276)
passed on that source. Documentation-only commits `4397e88d` and `17584b30`
and later release-status commit `bd6820d5` follow. Those workflow receipts are
historical. At that earlier checkpoint, full parity and coverage still needed
to run after implementation. The current workflow and phase state are recorded
at the top of this plan. At that earlier checkpoint, the 100% Rust/PyO3 line
threshold and complete 74-workload benchmark remained unproven.

Release preparation remains active and non-publishing under Kata `n5d2`, with
Cargo (`z74v`), PyPI (`2pan`), and documentation (`c4cy`) children. The
checkpointed Cargo archive and hosted documentation checks were built against
older commit `bd6820d5`; they are not exact-candidate release evidence. The
Cargo package list still includes the internal parity adapter and omits
top-level `docs/`, so package scope and README navigation remain unresolved.
Current-candidate artifact builds and clean consumer checks remain open.
Generated parity inputs and result JSON remain under ignored `build/parity/`
paths; stale benchmark output is not current performance proof.

The following @64 results are historical and do not add evidence for the
current full-contract input set. The @64 Ubuntu source-parity workflow
[`38966623985`](https://github.com/appunni-m/starlette-rs/actions/runs/38966623985)
passed all five CPython profiles with zero mismatches, failures, skipped rows,
or infrastructure errors: 664/664 for CPython 3.10 and 3.11, 665/665 for 3.13
and 3.14, and 2,971/2,971 for the CPython 3.12 full matrix. Its Windows
invalid-name probe
[`38966623892`](https://github.com/appunni-m/starlette-rs/actions/runs/38966623892)
passed 4/4 comparisons. The local macOS @64 parity run source-skipped two
StaticFiles surrogateescape rows because its filesystem cannot create the
invalid-byte filename; Linux CI exercised them.

All six @64 coverage plans executed without failed selected cases: CPython 3.10
289, 3.11 289, 3.12 2,598, 3.13 290, 3.14 290, and Rust-native 378. Coverage
MCP marked the imported LCOV reports' source identity `unverified` and test
status `unknown` because matching source/build receipts were not ingested. The
selected-component line measurements were 13,333/33,869 (39.37%) for CPython
3.10, 13,429/33,869 (39.65%) for 3.11, 23,416/33,869 (69.14%) for 3.12,
13,281/33,869 (39.21%) for 3.13, 13,270/33,869 (39.18%) for 3.14, and
14,598/19,596 (74.49%) for Rust-native. These are scoped target-report
measurements, not Starlette-wide coverage percentages.

The complete @64 benchmark run
[`40f41f01-bb35-4617-ab01-9b87f9e21bdd`](BENCHMARKS.md) measured all 74
source/package workloads. The two macOS surrogateescape skips remain recorded
in its preflight. These @64 results do not establish current parity or
coverage.

The preceding @63 checkpoint is historical. Its manifest declared 2,604 cases
across 443 parity inputs, two benchmark inputs, 152 compatibility operations,
15 Rust-native operations, 1,448 parity requirements, and six target profiles.
That batch added input-only comparisons for integer URL conversion from
signed, underscored, whitespace-padded, and Unicode decimal strings; lifespan
scope membership followed by a faulting indexed state lookup; a FileResponse
whose supplied stat size exceeds the bytes read at EOF; and a GZip response
with status 65536. It also mapped `HTTPEndpoint.method_not_allowed` through a
`Starlette` application to its configured status-405 handler; mapped
`HTTPSRedirectMiddleware` forwarding lifespan startup and shutdown scopes; and
added StaticFiles string-subclass and TestClient `root_path` identity cases.
Those historical inputs passed their recorded contract and source-inventory
checks; their parity, coverage, and benchmark evidence is recorded below.

The workflow records below are historical evidence for the earlier verified
input set `f8a34c2978af95382ceadcd3e3a2c5a9d7bb1d467f03b35ba55033d9b7336124`
(2,590 cases, 437 parity inputs, and 1,442 requirements). The @64 parity and
coverage evidence is historical; current phase states are in the execution
ledger. The pinned denominators remain 514 upstream test functions and 24
documented pages.

The five CPython source-parity profiles passed in workflow
[`38923021415`](https://github.com/appunni-m/starlette-rs/actions/runs/38923021415):
646/646 comparisons for CPython 3.10 and 3.11, 2,943/2,943 for CPython 3.12,
and 647/647 for CPython 3.13 and 3.14. Every profile had zero failures,
`not_run` rows, or infrastructure errors; all selected fault-contract cases
passed.

All six @63 coverage profiles passed in that workflow: 375 Rust-native cases,
274 each for CPython 3.10 and 3.11, 2,573 for CPython 3.12, and 275 each for
CPython 3.13 and 3.14. Selected-component line coverage was Rust-native
5,204/8,110; CPython 3.10 11,881/33,719; 3.11 11,961/33,719; 3.12
23,307/33,719; 3.13 11,821/33,719; and 3.14 11,810/33,719. Coverage MCP read
all six LCOV reports and surfaced uncovered locations. It marked the imported
CI reports `source=unverified` and `tests=unknown` because matching source and
build receipts were not ingested. These selected-input measurements are not a
parity score or a percentage for the whole Starlette contract.

The complete @63 74-workload benchmark ran after parity and coverage. Run
`005660ff-d624-43a0-aff3-fc86fcb9b2f0` measured all six Router and 68 GZip
source/package workloads with zero failures, skips, or observation mismatches;
Rust-native remains `not_run` for all 74 because it has no equivalent ASGI
workload boundary. Its correctness preflight selected 2,943 comparisons:
2,941 passed, zero failed or had infrastructure errors, and two were skipped
because macOS cannot create the POSIX surrogateescape filename. Normalized
observations matched for 74/74 workloads. The median source/package latency
ratios were 0.274 for Router and 0.970 for GZip; source latency was lower in
6/6 Router and 56/68 GZip workloads. The full replacement goal remains active
because the pinned compatibility inventory is broader than these mapped
inputs. The pinned denominators remain 514 upstream test functions and 24
documented pages.

The macOS arm64 package qualification passed at source snapshot `fe229a998`
plus the README runtime-dependency wording correction. Five isolated installs
for CPython 3.10.20–3.14.7, `pip check`, and installed-package smoke checks
passed. Four input-derived Mypy consumers matched the pinned source on all five
interpreters (20 comparisons). Wheel, sdist, and crate inspections verified
namespace files, `py.typed`, dependency metadata, BSD-3-Clause notices, and
provenance; no upstream Starlette runtime dependency was present. The generated
CycloneDX SBOM is now normalized to stable Cargo PURLs while retaining its full
Rust dependency graph. A targeted CPython 3.12 wheel built from the checkout
and another built from its sdist each carried the 75-component, 76-record,
134-edge SBOM with no local filesystem references. See [SBOM packaging
notes](SBOM.md). The five-version qualification matrix above remains scoped to
its recorded source snapshot. The two Windows StaticFiles invalid-name cases
have since passed in workflow
[`38892560877`](https://github.com/appunni-m/starlette-rs/actions/runs/38892560877)
on Windows Server 2025 with CPython 3.12.10: four comparisons passed, with no
failures, skips, `not_run` rows, or infrastructure errors. The workflow used
Starlette 1.6.0 at the pinned source revision and target commit
`a3488d512b2680dd46b540f7db620ab7f564d70c`; its StaticFiles runtime and input
definitions are unchanged on the current branch.

### Post-checkpoint repair and verification

Workflow `38767055636` on commit `4139a724` found two Linux Rust-native parity
failures: FileResponse's default `.exe` MIME type differed, and StaticFiles
fell through to a later root after an overlong first-root lookup. Commit
`57361208` fixes both Rust paths. It also changes links to ignored LCOV output
into local artifact paths. The follow-up workflow `38769902939` passed all 14
jobs, including the corrected five-profile parity matrix above. The plan and
benchmark evidence are refreshed from that revision, and local `make
docs-check` passes.

The implementation and grouped repair phases recorded in the notes below are
historical checkpoints. Current-manifest parity, coverage, and benchmark status
is summarized at the beginning of this document and in the execution ledger.
The earlier CI/schema failure and grouped first-pass results below are
historical.
The `e8ed3b8d` base upgraded the strict result contract to @9,
constrained CPython-specific MarkupSafe provenance, added WebSocketRoute
equality and missing-scope-key inputs, and expanded ordinary BackgroundTask
and concurrency inputs across CPython 3.10–3.14. Other async-generator
protocol inputs remain at 3.12; the separately audited WebSocket `athrow`
arity input covers 3.10–3.14.

The initial grouped full matrix ran on clean commit `8b05702c` across CPython
3.10–3.14. CPython 3.10 and 3.11 each recorded 631 passes, one URL mismatch,
and one POSIX-only `not_run`; CPython 3.12 recorded 2,886 passes and one
WebSocketRoute package-adapter infrastructure error; CPython 3.13 and 3.14
each recorded 633 passes and one POSIX-only `not_run`. All 17 selected fault
contracts passed. The URL mismatch comes from CPython 3.10/3.11 `urlunsplit`
behavior for an empty authority and relative path. The Rust compatibility
boundary now uses the running interpreter version to preserve that behavior,
and the package adapter now accepts the input's declared optional
`scope_container`. The corrected active-revision results are recorded above.
Do not infer universal drop-in compatibility from the matrix alone: retain the
514 upstream test-function and 24 documented-page denominators and the
input-driven compatibility inventory status.

The implementation batch notes below preserve their checkpoint chronology;
phrases such as “deferred” and “unexecuted” describe the status when each note
was written. Current active-revision gate states are summarized above and in
the execution ledger. Historical batch notes describe their state when
recorded.

The latest implementation batch now compares FileResponse's stateful PathLike
calls inside its input-conditioned result record, and WSGIMiddleware's sender,
worker, context, queue-progress, completion, and callback-lifetime observations
are all declared and emitted by both live adapters. Rust GZip preserves
Starlette's missing-`headers` lookup when an unusual response-start type fails
equality, and TestClient cleanup keeps ExitStack exception context through
shutdown. These source-backed changes pass contract and static quality checks;
their comparisons remain deferred to the grouped full parity phase.

This checkpoint also adds an input-only GZip response case for raw-header-name
matching through compression and response-header mutation, alongside the
existing request-negotiation case. It corrects a GZip lookup to match
Starlette's exact comparison of lower-case lookup keys against unnormalized
ASGI header names. CORS error observations and tuple-header materialization,
plus AuthenticationMiddleware iterable backend stimuli, now match their public
consumer contracts in the parity adapters. A SessionMiddleware input covers an
authenticated timestamp wider than `u64`
with `max_age=None`. The Rust middleware and native verifier now preserve the
timestamp without narrowing, matching ItsDangerous 2.2.0's deferred timestamp
conversion. A dedicated native input is registered in the active contract.
The source/package and native comparisons remain unexecuted until the grouped
parity phase. This earlier checkpoint recorded contract and
source-inventory checks at 2,519 cases and 414 input files.

The next implementation batch adds BOM-required generic UTF-16 decoding with
the pinned Latin-1 fallback, StaticFiles handling for non-string HTTP methods,
and Rust-owned WebSocket typed-receive descriptor lookup order. It registers
one input-only comparison for each boundary and adds the StaticFiles source
requirement; all three comparisons remain deferred to grouped parity. The
active contract now has 2,519 cases across 414 parity inputs and 1,389
requirements. The regenerated atlas has 866 source rows, 810 input mappings,
56 reasoned `not_applicable` rows, and zero backlog. No parity, coverage, or
benchmark phase has run for the active contract.

This checkpoint adds three implementation slices. Schema converter removal
now preserves lone-surrogate paths while matching Python `str.isalnum()` for
Unicode `\w`; its input-only schema case is registered. SessionMiddleware
now compares response-start message types with Python equality, with a
`str`-subclass stimulus registered in both live adapters. TestClient now
exposes Rust-backed `lifespan`, `wait_startup`, and `wait_shutdown` methods,
including startup/shutdown failure-message validation; an input-only public
API inspection covers their signatures. All new comparisons remain unexecuted
until the grouped parity phase. The pinned denominators remain 514 upstream
test functions and 24 documented pages.

StaticFiles now propagates filesystem `InvalidInput` errors from canonicalized
lookup and metadata lookup, matching the pinned source's policy of suppressing
only missing and not-a-directory errors; embedded NUL request paths retain the
separate source-matched `ValueError`/404 path. The existing Windows invalid-
name inputs exercise both symlink policies, but their Windows runner has not
been executed; this change is implementation evidence, not parity evidence.

The latest feature batch registers input-derived comparisons for Config env-file lines without `=`, a legacy IE drive-path multipart filename, and multipart FileResponse ranges after the `content-type` header is removed. Rust now preserves the pinned filename normalization, including its UNC-path rule, and maps the missing header to `KeyError`; Config already follows the pinned ignore behavior. All comparisons remain unexecuted until grouped parity.

GZip content-type normalization now uses Unicode lowercasing on Latin-1-decoded
response headers, matching Starlette's `str.lower()` behavior; an input-only
case covers a non-ASCII case pair. The Session workflow adapters and validator
now preserve uncaught request-dispatch errors as comparable partial
observations, including the existing out-of-range timestamp and surrogate
cookie-name cases. These comparisons remain deferred to grouped parity.

The TestClient managed-lifespan implementation now dispatches the bound
`lifespan`, `wait_startup`, and `wait_shutdown` methods through AnyIO's portal,
preserving Python subclass overrides while Rust owns the lifecycle state and
cleanup. Input-only cases cover record-and-delegate overrides and calling
`__exit__` before `__enter__`; their comparisons remain deferred to the grouped
parity phase.

The recent implementation checkpoint adds
input-driven boundaries for `MultiDict.setlist` protocol order, synchronous
`HTTPEndpoint` dispatch, direct `Router` route registration, and `URLPath`
protocol construction. The `Router.add_route` and
`Router.add_websocket_route` annotations now match the pinned source, and the
existing application typing consumer exercises accepted and rejected calls.
The current implementation batch adds WSGI protocol formatting and Config
reflected-key-addition probes, Route/Router/Mount middleware-stack ordering,
and TestClient handled-exception propagation after a complete response. The
existing BackgroundTasks cancellation-then-worker-error case is now supported
by its live adapter. The BackgroundTasks facade now resolves its current public
`tasks` attribute when awaited and passes that sequence to the Rust-owned
iterator. It also constructs a task before resolving and appending to that live
property in `add_task`; a source/package input covers a subclass property
override. Both comparisons remain deferred to grouped parity. A TestClient
WebSocket input now exercises plus-space,
percent-encoded UTF-8, duplicate query keys, and blank values through both the
ASGI scope and `WebSocket.query_params`. Three more input-only cases observe
successful WebSocket authentication scope installation, first-value selection
for repeated CORS request headers, and `Request.stream()` skipping an
application-defined event between body chunks; the reviewed Rust behavior
matches the pinned source. All four new comparisons remain deferred.
Static contract validation passes for full scope with 2,522 cases, 414 parity
inputs, two benchmark inputs, 151 compatibility operations, 13 Rust-native
operations, 1,392 parity requirements, and six target profiles. The latest source-reviewed inputs cover Request and WebSocket
identity across mutable scopes, WSGI query-string ASCII decoding and Latin-1
header values, and quoted Request cookie escapes. Existing Rust behavior
matches the pinned sources for the cookie and WSGI builders by source review.
All comparisons remain deferred to the grouped full parity phase; full parity,
coverage, and benchmark work have not started. Five new input-only cases preserve Request.stream message-type lookup order, Python comparisons in ExceptionMiddleware and ServerErrorMiddleware, and TestClient WebSocket text-object identity; they remain unexecuted until the grouped parity phase. A StaticFiles input now covers an overflow-day If-Modified-Since value accepted by email.utils.parsedate; its comparison remains deferred to the grouped parity phase.

StaticFiles target workflow materialization now decodes input-defined POSIX
filesystem-byte `path` and `root_path` values, supports the registered
`get_directories` subclass hook, and records the input-defined non-HTTP scope
assertion and lookup-path exceptions as observations. The Rust boundary maps
an embedded-NUL lookup failure to the pinned `ValueError("embedded null byte")`
contract. These existing oracle/package/native inputs remain unexecuted until
the grouped parity phase.

The WebSocketRoute scope-type equality and missing-key cases are registered in
the active contract. The package adapter now materializes an input-defined
scope type through the same boundary as the oracle, preserves a missing `type`
key for direct route dispatch, and captures dispatch errors and mapping
operations. Their source/package comparisons remain deferred to the grouped
parity phase.

Nested Application, Mount, Router, and Route middleware composition has no
source-backed runtime gap in the audited Rust stack. A distinct input-only
workflow now records scope mutation during entry and response-header order
during unwind, registered against the pinned source. Its comparison remains
deferred to the grouped parity phase.

The latest application source audit found that Rust middleware-stack building
read `router` and `max_body_size` earlier than pinned Starlette, and read
`max_body_size` only once. The Rust runtime now follows the pinned attribute
lookup order, including the second read; an input-only subclass comparison is
registered and deferred to the grouped full parity phase. Request body-stream
review found no additional mismatch. StreamingResponse's implemented send,
iteration, and disconnect behavior matches the pinned source on review; a
distinct input for external caller cancellation while the pre-ASGI-2.4
disconnect listener waits on `receive()` is registered. Both inputs remain
deferred to the grouped full parity phase.

Additional boundary inputs cover non-string ASGI scope types in
AuthenticationMiddleware, SessionMiddleware, and GZipMiddleware, plus
ServerErrorMiddleware message-type equality for a `str` subclass with custom
`__eq__`. Rust preserves Python equality and membership dispatch for these
values. All comparisons remain unexecuted until the grouped full parity phase.

This implementation checkpoint also covers Python mapping-protocol exception
handlers during Starlette stack construction, GZip request-header copy/writeback,
StaticFiles scope-type equality, FileResponse `.exe` media-type inference, and
TestClient WebSocket mapping messages with same-session context re-entry.
UploadFile's documented Python field annotations are explicit, and the typing
consumer includes an input-derived assertion. These comparisons remain deferred
to the grouped full parity phase.

The latest Request.state boundary input uses a custom mapping whose `setdefault("state", {})` result differs from its subsequent `scope["state"]` read; Rust now preserves that ordering. A separate TemplateResponse input checks dynamic `HTMLResponse.__call__` lookup after the optional debug event. Both source/package comparisons remain deferred to the full parity phase.

The latest URL(scope=...) change passes the raw ASGI `server` value to Rust,
which selects a valid Host header before converting the server tuple, matching
Starlette's lookup order. Its input-only case uses a valid Host with an empty
server sequence. The source/package comparison remains deferred to the full
parity phase.

A direct Response input supplies an explicit Content-Type header alongside `media_type="text/plain"`; the comparison observes constructor header precedence and automatic Content-Length and remains deferred to full parity.

A new StreamingResponse input exercises a nonterminal send-side `OSError` under
ASGI 2.3 while the receive-side disconnect listener is gated. The Rust path
uses the corresponding collapsing task-group structure by source review; its
registered source/package comparison remains deferred to the full parity phase.

The templating runtime now renders before resolving the dynamic `HTMLResponse.__init__`, and Rust looks up `context.update` before invoking each processor. Two input-only cases record those lookup orders and remain unexecuted until grouped parity. The `Jinja2Templates.get_template` facade annotation now exposes Jinja's `Template` type; its input-derived Mypy 1.19.1 consumer passed against both the pinned source and rebuilt package wheel. The registered comparison remains deferred to full parity.

At this pre-parity checkpoint, implementation remained the active phase. The
planned order was to finish implementation across feature families, run the
complete source/package and Rust-native parity matrix, repair cross-family
mismatches, measure coverage from that matrix, reconcile the source atlas, and
then run all correctness-gated benchmarks. The active-revision outcomes are
now recorded in the execution ledger above.

At that historical checkpoint, the contract declared full Starlette scope
(`starlette-1.6.0-full`, mode `full`) with 2,519 input cases across 414
parity inputs and two benchmark inputs, 151 Starlette compatibility operations,
13 Rust-native operations, 1,389 parity requirements, and six target profiles.
At that checkpoint, no complete parity result had been accepted. The following
feature notes preserve implementation history and the status when they were
recorded. The latest implementation adds Rust-backed `BackgroundTasks.tasks`
deletion and preserves Python strings, including lone surrogates, in built-in
converter formatting. Five new input-only comparisons cover background
attribute deletion, concurrency BaseExceptionGroup propagation, public
converter methods, and registration replacement with preexisting routes; all
were awaiting the grouped full parity run at that time. The latest batch adds
input-only comparisons for StaticFiles `If-Modified-Since` dates with single-digit
time fields and Jinja environments that supply their own `url_for` global; the
StaticFiles parser now normalizes the accepted time form in Rust. Both comparisons
were also awaiting that run. A new AuthenticationMiddleware scope input
preserves present `None` values for `auth` and `user`; two Request inputs omit
`scope['auth']` and `scope['user']` in turn
while an instance-level UserDict `__contains__` override returns true; the
pinned type-level membership lookup still sees each key as absent and raises
the documented assertion. These comparisons were pending at the recorded
checkpoint. The
successful WebSocket authentication requirement now cites the pinned
`test_websocket_authentication_required` function at lines 273–303. Rust now
resolves awaitable `__await__` through type-level lookup, ignoring instance
shadow attributes. A new Config
typing consumer covers all nine pinned `Config.__call__` overload assertions;
its input-derived source/package Mypy 1.19.1 comparison passes with identical
diagnostics and revealed types. The application typing consumer checks
both `await Request.form()` and `async with Request.form()`, and iterates
`Request.stream()` to assert that each yielded chunk is `bytes`. It also checks
`Request.body()` as `bytes`, `Request.json()` as `Any`, `Request.query_params`
as `QueryParams`, `Request.path_params` as `dict[str, Any]`, and
`Request.client` as `Address | None`. It also asserts `Request.receive` as
`Receive`, `Request.headers` as `Headers`, `Request.url` as `URL`,
`Request.cookies` as `dict[str, str]`, and
inherited `WebSocket.client` as `Address | None`, `WebSocket.cookies` as
`dict[str, str]`, `WebSocket.url` as `URL`, and the inherited
`WebSocket.headers` and `WebSocket.query_params` as `Headers` and
`QueryParams`. It now also asserts `Request.session` and inherited
`WebSocket.session` as `dict[str, Any]`; pinned Mypy 1.19.1 passes on both the
Starlette source and installed package with identical diagnostics and revealed
types. The consumer also checks `Request.send_push_promise` as
`Callable[[str], Awaitable[None]]`, `Request.is_disconnected()` as `bool`,
and the yielded values from `WebSocket.iter_text()`, `iter_bytes()`, and
`iter_json()` as `str`, `bytes`, and `Any`. It assigns `WebSocket.receive` and
`WebSocket.send` to ASGI
`Receive` and `Send` callback types and asserts that awaited
`WebSocket.receive_text()` and `receive_bytes()` return `str` and `bytes`.
Pinned Mypy 1.19.1 produced identical output against Starlette 1.6.0 and the
rebuilt installed wheel for these checks.
The response typing input now asserts `Response.headers` is `MutableHeaders`
and compares the documented `Response.set_cookie` argument and return types,
including rejection of an unsupported SameSite literal. The application
typing input also asserts `UploadFile.read()` returns `bytes` and checks
`Mount` and `Host` ASGI callback parameters and `app` attributes. Their facade
annotations now retain `ASGIApp` instead of widening to `Callable[..., Any]`
or leaking `Any` from Rust initialization. Pinned Mypy 1.19.1 diagnostics are
byte-identical between the Starlette source and package consumer inputs; the
registered parity comparisons remain deferred to the full parity phase.
The latest audit batch fixes Python `repr` formatting for Unicode format
characters in invalid WebSocket event types, preserves arbitrary-precision
itsdangerous timestamps when SessionMiddleware has no expiry, and binds
classmethod/staticmethod async context-manager methods through Python's
descriptor protocol in lifespan. Four input-only cases cover those boundaries;
their comparisons remain deferred to full parity.
A direct Response input now observes `Content-Length` suppression for status
304; its live comparison remains deferred to the full parity phase.
A new multipart input covers repeated Content-Type `charset` parameters;
Rust now selects the final value, matching the pinned multipart parser. A
two-backend TestClient input confirms WebSocket application exceptions still
propagate when HTTP `raise_server_exceptions` is false; the Rust session path
already matches. Both new comparisons remain deferred to full parity.
A default middleware-stack input now also sends a successful request through
two traced user middleware layers before exercising the existing handled-405
and unhandled-error paths. Its source/package comparison remains deferred to
the full parity phase.
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
atlas has 864 source rows: 808 input mappings, 56 source-backed
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
unexecuted until full parity. The WebSocket iterator now resolves its typed receive method through the receiver at each Rust iterator advance; three input-only descriptor-tape comparisons cover lazy lookup and the disconnect advance for text, bytes, and JSON and remain unexecuted. A fourth input makes the typed receive descriptor raise StopIteration during iter_text advancement; Rust applies PEP 479 conversion with the original cause/context, and the comparison remains deferred. The Rust-native Route float negative-zero case is
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

Rust-native Route float reverse formatting now accepts Python `float(value)`
spellings and uses Starlette's fixed 20-decimal output, trimming trailing zeroes.
Four input-only cases cover `0.1`, a whitespace-wrapped signed exponent,
digit separators, and negative-zero spelling. WebSocket `send_json` now keeps
mode validation, JSON serialization, and the final text-mode comparison in the
pinned order; its input uses a stateful mode and unserializable payload. These
five comparisons remain deferred until the grouped full parity phase. The API
review of source-only re-export candidates remains a separate inventory task.
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
An earlier 12-case input-only batch covers non-string `HTTPException` detail and header-key errors, Python equality for special exception-handler selection, FileResponse multipart short reads, Mount `path=None`, Request custom receive events between chunks, TestClient portal-setup error policy, empty StaticFiles `If-None-Match` fallback, WebSocket raw state assignment, StreamingResponse type-level async iteration, and empty CORS private-network headers. Source inventory and contract validation pass with zero parity passes claimed; all 12 comparisons remain deferred to the grouped parity phase.
The newest four input-only cases cover the deprecated TestClient `httpx` fallback, closing `Request.stream()` before its first advance, preserving an existing WebSocketEndpoint disconnect-hook context, and duplicate-key Python mapping expansion in a synchronous `BackgroundTask`. The Request, WebSocketEndpoint, and BackgroundTask Rust paths now preserve the source behavior; the TestClient fallback input records the existing boundary. All four comparisons remain unexecuted until the full parity phase.

Adapter preparation now aligns source and target workflows for GZipResponder
re-use and dispatch errors, BaseHTTPMiddleware body-iterator replacement,
overlapping reads and early close, FileResponse PathLike selectors,
StaticFiles direct errors and POSIX surrogateescape host skips, minimal
StreamingResponse scopes, WebSocketRoute unused receives, and WSGI protocol
serialization. Rust also now appends the active WebSocketEndpoint dispatch
exception at the end of an existing disconnect-hook exception context chain.
These changes are not parity evidence; all affected comparisons remain
deferred to the grouped full parity phase.

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
| Implementation and input authoring | Current input/catalog mapping is complete; runtime correctness is not proven by inventory data. Keep any failures found by the current matrix in the grouped-fix phase. | `make contract-check` passed: `manifest@6`, 2,786 cases, 472 parity inputs, 157 compatibility operations, 18 Rust-native operations, 1,505 requirements, and six profiles. `make source-inventory-check` passed: 999/999 API candidates dispositioned, 867 source rows (811 mapped, 56 source-backed `not_applicable`), and zero fixture backlog. `make project-policy-check` passed, including zero conventional unit tests, no upstream runtime dependency, thin Python wrappers, ID-independent adapter dispatch, and generated parity JSON ignore enforcement. |
| Full parity and grouped repairs | Not yet proven on the current runtime candidate. Workflow #27 is still executing on older `67abf21e`; workflow #28 is queued on `e9f8b181`. | Current browser status for #27 is 0/5 CPython jobs complete; #28 is waiting for #27 under the serialized concurrency group. Use #27 only as an older baseline and retain #28 as the current-candidate proof. Neither currently supplies parity results for `e9f8b181`. |
| Full coverage and source reconciliation | Not proven for `e9f8b181`; run only after its parity matrix passes. | Workflow #28 places the six managed coverage profiles and eligible-line union after parity. No current-candidate coverage receipts or passing 100% eligible-line union exist. Older coverage diagnostics are revision-bound and cannot be combined with #28. |
| Complete benchmark | Historical only; run last against the candidate that passes parity and coverage. | Run `b5a4637e-6adf-4735-93f5-3966681a6113` measured 74/74 workloads on `943c1c26`; it predates later runtime and contract changes and is not current performance evidence. |
| Packaging and interpreter qualification | Release preparation remains open and non-publishing under Kata `n5d2`. | No candidate-tied `.crate`, sdist, or wheel matrix for `e9f8b181` has been qualified. Cargo package scope, Python support upper bound, fresh consumer installs, cross-platform artifacts, and release automation remain open. |

Parity, coverage, and benchmark result artifacts live under ignored
`build/parity/`. The pinned denominators remain 514 upstream test functions and
24 documented pages; case counts and the atlas describe our input mapping.
Historical run status remains bound to its named manifest and immutable source
revision. Full replacement, current-candidate coverage, and current-candidate
benchmark claims remain open until their required evidence phases pass.


Boundary details: [Request and HTTPConnection lookups](REQUEST_CONNECTION_LOOKUP_BOUNDARY.md),
[response protocols](RESPONSE_RENDER_BOUNDARY.md),
[server-error traceback data](SERVER_ERROR_BOUNDARY.md),
[template callbacks](TEMPLATE_PROTOCOL_BOUNDARY.md),
[optional imports](OPTIONAL_IMPORT_BOUNDARY.md),
[ASGI ownership](WEBSOCKET_OWNERSHIP_BOUNDARY.md),
[custom BaseRoute callbacks](ROUTE_MATCH_BOUNDARY.md),
[StaticFiles filesystem path encoding](STATICFILES_PATH_ENCODING_BOUNDARY.md), and
[Config callable subclass dispatch](CONFIG_CALL_OVERRIDE_BOUNDARY.md).

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
request bodies. The previous @62 five-profile grouped matrix executed these inputs;
all 17 selected fault contracts passed, including the three target-only lifespan
fault contracts for shutdown error aggregation and dropping pending startup
and shutdown futures. FastAPI composition is outside this project's scope. See [`native-service.md`](native-service.md),
[`native-websocket.md`](native-websocket.md), and [`native-lifespan.md`](native-lifespan.md)
for the APIs and boundaries.

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

The active parity contract has full scope (`starlette-1.6.0-full`): 2,759
unique cases across 471 parity inputs, two benchmark inputs, 157 Starlette
compatibility operations, 17 Rust-native operations, 1,497 mapped source
requirements, and six target profiles. The current manifest SHA-256 is
`4f7048da1cf93e7c3392a91fc3937ba32d2af2aca70c71eaa23dcd609ae718ad`.
Input generation, contract validation, the metadata-derived API catalog, and
the compatibility atlas pass. The queued full matrix targets the preceding
manifest command; no full parity or coverage run has executed on this exact
contract. The full-replacement goal remains active, and the fixed upstream
denominators are 514 test functions and 24 documented pages.
The historical `parity-input@27` integrated run includes the focused
`parity-input@23` through `@27` additions and its two BaseHTTPMiddleware
ContextVar observer comparisons; it does not establish parity for the full
current contract.

The current generated coverage matrix has 867 source rows: 811 input mappings,
56 source-backed `not_applicable` rows, and zero fixture-backlog rows. Refresh
these counts from the generated atlas CSV files after changing fixture
dispositions. The full replacement objective is active and incomplete.

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
Windows path normalization has two input-only lookup cases for an absent
`missing?.txt` component, covering canonicalized lookup with both values of
`follow_symlink`. The adapters compare a shared OS-error category because
native messages and error codes vary by platform. Dedicated Windows workflow
`38892560877` passed all four selected comparisons against the pinned source,
installed package, and Rust-native target; no `InvalidInput` mismatch was
observed for these inputs. This verifies only the declared invalid-name cases,
not every Windows filesystem behavior. The ASGI entry passes the bound
`get_response(path, scope)` override into the Rust awaitable state machine,
which calls and awaits that Python callback on the caller's loop; the default
path selection and response dispatch remain Rust-owned. This callback boundary
is required because Python subclasses can replace `get_response`. An
input-only comparison checks the supplied callback arguments and returned
response and remains unexecuted. The active contract now contains 83
StaticFiles cases across 21 input files. A source audit of all metadata-listed
StaticFiles methods and the 36 upstream `tests/test_staticfiles.py` functions
found those behaviors mapped to existing inputs and no distinct ordinary-input
gap to implement. The previous @62 parity evidence is recorded above; this source
audit and the targeted Windows result do not prove behavior beyond the declared
input cases.

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
cases exercise converted path-parameter values and CPython's 4300-digit
integer conversion limit. The digit-limit cases now target all declared
CPython 3.10–3.14 package profiles; CPython backported the limit to 3.10.7 and
introduced it in 3.11. Two Mount cases compare child-scope extension and
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
WebSocket exception flows, additional synchronous background-cancellation
schedules, context variables, and broader background-task error interactions.
The TestClient exception-policy candidates are already represented in Rust and
active input fixtures; their source/package comparisons remain deferred and
unverified. The latest input-only batch
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
coverage. The previous @62 full parity run exercised the profile-applicable cases,
including TestClient generator-body buffering, entry-cleanup error precedence,
exception modes, and route/middleware combinations; its two local filesystem
skips are recorded above. The generated fixture backlog is currently empty; it
tracks source mapping, not implementation completion. Choose the next behavior
from the remaining source-backed gaps and supported public API contract, keep
optional dependencies feature-gated, author input-only comparisons alongside
the implementation, then defer execution until the next grouped parity phase.

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
Python package resolves omitted details through Python's `HTTPStatus`
boundary. `Response::http_exception` accepts an optional detail and maps omitted
values to the pinned status phrase, retaining explicit details and the
204/304 empty-body behavior. The Rust-native response contract input drives
all 62 pinned `HTTPStatus` values plus explicit-detail and bodyless-status
inputs through the live Starlette oracle and Rust adapter. Its focused local
CPython 3.12 comparison passed (one selected case, zero failures). The manifest
normalizes only the CPython 3.13 RFC 9110 reason-phrase aliases for statuses
413, 414, 416, and 422 and their dependent content lengths because the
Rust-native API has no interpreter version; [Python's HTTP documentation]
(https://docs.python.org/3.13/library/http.html) records the renaming. Other
response fields remain exact, and the focused run does not establish the full
multi-version parity matrix.

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

The `WebSocketRoute.route-dispatch` cases select the Python-package profile:
`matched-root-path` matches `/rooms/{room:str}` beneath `/edge`;
`router-miss-close` dispatches an unmatched WebSocket scope and observes its
close event; `http-scope-404` calls a standalone route with an HTTP scope and
observes the 404 response. Two newly authored inputs exercise Python equality
for a `str` subclass and propagation of a missing `scope["type"]` KeyError from
a mapping-backed scope. Those two comparisons remain deferred until the
grouped parity phase. Native `WebSocketRoute` dispatch is not declared.

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
