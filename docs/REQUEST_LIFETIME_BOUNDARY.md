# Request lifetime boundary

## Public consumer contract

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The authored input matrix is
[`request-lifetime.yaml`](../tests/fixtures/sources/parity/request-lifetime.yaml),
registered by `metadata.yaml` and the active manifest as Request
`callback-lifetime`. Its consumer uses only Request construction, public scope
and receive references, body/JSON/form methods, stream operations, Python's
public await iterator protocol, and garbage collection.

Seventeen input-driven graphs include a scope self-cycle, a receive callback
cycle, unstarted body and JSON coroutines, an unstarted stream, all four stream
operation factories, unstarted form and form-enter operations, and suspended
body, JSON, stream-next, stream-asend, form, and form-enter operations. The
input supplies scope, method arguments, suspension token, receive message,
user labels, and collection generations. No fixture supplies expected outputs.

The consumer first retains the graph and collects it, then releases only its
external roots and collects again. It never edits internal ownership links or
explicitly closes a continuation to help collection. Weak references are to
user objects, avoiding assumptions about implementation-specific Request weak
reference support. It observes user finalizers and their thread, receive start
and finally events, every unraisable error, and warning category/message.
Finalizer and warning lists are sorted with duplicates retained because their
collection order is not portable. No result normalization applies. Diagnostic
filenames, line numbers, and coroutine origin stacks are outside this observation.

## Rust ownership and finalization

The Python runtime facade remains unchanged. Rust exposes HTTPConnection's
owned scope and property caches to Python GC. Request body state and entered
form state are private GC-visible PyO3 nodes. Each directly owned Python edge
is visited exactly once; wrappers and continuations visit the shared node,
which owns and visits receive/body/JSON/form values. Visiting the same
Arc-owned Python value through several wrappers would miscount its ownership.
The remaining stream-state and protocol mutexes contain only native state.

Every Request continuation uses the Send + Sync constrained native driver.
GC traversal visits its active iterator and directly owned Python references
without acquiring the GIL or executing callbacks. Typed PyO3 borrows replace
mutexes around Python-owned body and form state. Form context exit clones the
form reference and releases its borrow before invoking Python close.

The converted native driver follows coroutine.close delegation: first close
the active delegated iterator, then deliver GeneratorExit to the Rust
continuation. Python can finalize the child before its parent during cyclic
collection; closing an already closed coroutine is idempotent. Throwing into
that finalized child instead produced a spurious coroutine-reuse error.
User callback errors continue to propagate; this change does not suppress
errors by exception message or case ID.

Unstarted native form and form-enter objects emit the source coroutine
RuntimeWarning messages from Rust. Body and JSON keep their existing
Python facade coroutine warnings. Converted machines opt into Rust
continuation finalization; older unconverted machines keep their existing
ownership and finalization behavior. Interpreter shutdown uses try_attach.
Completed drivers avoid acquiring the GIL again during destruction.

## Evidence and remaining work

The first live run failed all 17 new lifecycle cases: user callback graphs
remained alive. The first ownership fix passed 13 but exposed four spurious
unraisable errors from closing suspended child coroutines. Both failed result
artifacts remain ignored under `build/parity/request-lifetime/`.

The selected verification run `d2aef2dd-423e-4e35-a346-325061b5adf8` passed 33/33 ordinary Python-package
comparisons and both target-only route-cache fault contracts, with no
infrastructure errors or skipped selected rows. This includes all 17 new
inputs, 13 existing body-consumption inputs, two asyncio/Trio traceback
cleanup inputs, and a normal route-cache control. Its result SHA-256 is
`95e4780899beebedea658cc70385d95cab77d100807e644425f4cb78a5dc2d33`.

This does not establish all Python ownership contracts. Other native
continuations still need explicit traversal; remaining facade/value types,
worker-thread cyclic collection, resurrecting user finalizers, warnings-as-errors,
coroutine origin diagnostics, and multipart file finalization need input-only
consumer comparisons. Full compatibility remains governed by the generated
source atlas and its 514 upstream test functions and 24 documented pages.

## Incremental coverage measurement

Coverage MCP verified 223 newly covered Rust lines against a baseline of the
13 existing body-consumption inputs plus the normal route-cache control and
both fault contracts. The incremental batch was the 17 new lifecycle inputs
plus those same controls. Both selections passed on one fixed instrumented
source/build: baseline 3,335/24,872 lines, batch 3,373/24,872, union
3,558/24,872 (+0.897 percentage points). This selected union does not establish
full-suite coverage or regression status. LCOV reports, exact source hashes,
wheel identity, input selection, and passed-run receipts remain ignored under
`build/parity/coverage/request-lifetime-20261005/`.

## Clean full verification

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

## Worker and property collection extension

The 17 Request graphs now also pass worker-thread release/collection. New caller/worker state and header cycles are covered by input-only public consumers. See [Public value and worker collection](VALUE_LIFETIME_BOUNDARY.md) for the 45-case extension, reproduced native store leaks, and UploadFile callback reentry.
