# Public value and worker collection boundary

## Input-only public consumers

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.
[`public-value-lifetime.yaml`](../tests/fixtures/sources/parity/public-value-lifetime.yaml)
contains 60 cases for ImmutableMultiDict, MultiDict, Headers, MutableHeaders,
FormData, UploadFile, State, CommaSeparatedStrings, and URL. Two UploadFile
cases drive input-defined writes with an integer-subclass size callback that
reads public size/file/filename/headers attributes during arithmetic.
[`request-property-worker-lifetime.yaml`](../tests/fixtures/sources/parity/request-property-worker-lifetime.yaml)
contains 21 cases: the 17 earlier Request lifetime graphs collected on a
worker, plus caller/worker cycles through Request.state and Request.headers.

Construction, pair counts, key/value roles, user labels, write bytes, callback
attribute reads, initial size, and collection generations/thread come from
inputs. No case identifier selects behavior and no input contains expected
outputs. Consumers never inspect private framework ownership fields, edit a
cycle to force collection, or clear user exception chains. Public containers
are the only retained roots in the value consumer; user objects are observed
through weak references. This preserves evidence of both premature release
and retained cycles. Byte/string subclasses remain valid byte/string values;
their attached user objects form the ownership cycle. FormData contains actual
UploadFile values backed by a user BytesIO subclass.

Collection first runs with the public container retained, then releases it
and collects again on the input-selected thread. Finalizer thread observations,
file-close events, warning category/message, every unraisable error, and public
value identity remain exact. Finalizer and warning records are sorted with
duplicates retained because collection order is not portable. The test
consumer controls collection; the installed Python runtime facade is unchanged.

## Rust ownership

Header stores traverse their owned raw Python list. Multi-dict stores traverse
each owned key/value reference and the mapping reference; the mapping then
visits its own entries. Repeated references are visited once per actual owned
reference, preserving Python GC reference accounting. FormData traverses its
owned file/value references. CommaSeparatedStrings traverses preserved Python
sequence items; its native parsing and codepoint semantics remain in Rust.
State and URL were passing controls and need no ownership change.

UploadFile stores its Python fields in one private GC-visible PyO3 state node.
The public wrapper and outstanding operations own references to that node;
the node owns and visits file, filename, size, headers, and cached spool limit
exactly once. This replaces hidden Python references in shared native mutexes.
UploadFile operations and FormData close operations use the Send + Sync
constrained driver and expose their directly owned references to GC.

Getters clone values during a short typed borrow. Setters replace a value,
release the state borrow, then drop the old value so user finalizers can reenter.
Write size arithmetic clones the original size, calls Python arithmetic without
holding a native borrow, then stores the result. This preserves source ordering
when an int subclass reads upload attributes from __add__. Scheduling,
file methods, and exceptions continue through Python's active loop and the
existing AnyIO boundary; Rust owns selection and state decisions.

## Reproduction and verification

The retained live reproduction found 20 failures among 61 ordinary selected
comparisons: user objects stayed alive after release in header, multi-dict,
form, upload, and sequence stores. Both fault contracts passed. The 17 Request
worker cases, Request.state, State, and URL controls already matched.

After the Rust fixes, run `1fa01f8a-7c76-4415-bd6e-07364d36f51a` passed 66/66 ordinary
package comparisons and both target-only route-cache fault contracts, with
zero failures, infrastructure errors, or skipped selected rows. This includes
all 45 new inputs, the 17 existing Request lifetime cases, an existing upload
rollover case, two FormData constructor cases, and a normal route-cache control.
Result SHA-256: `d4ea4fd8798334ff2ac479aaccbbb40ffb238e72758ba12151e116df76cdbcf8`.
Artifacts remain ignored under `build/parity/value-lifetime/`.

This is a verified ownership slice. Resurrecting finalizers, warnings-as-errors,
origin diagnostics, cancellation of in-flight upload workers, and other native
continuations still require input-only consumer comparisons. The full objective
retains all 514 upstream test functions and 24 documented pages; current atlas
mapping/backlog counts come from its generated CSV files.

## Incremental coverage

Coverage MCP verified 217 newly covered Rust lines on matching instrumented
source/build receipts. The baseline was the 17 earlier Request lifetime cases,
the existing UploadFile rollover and two FormData constructor cases, plus the
normal route-cache control and both fault contracts. The incremental batch was
the 45 new cases with those same route-cache controls. Both selections passed:
baseline 3,837/24,936 lines, batch 3,767/24,936, union 4,054/24,936
(+0.870 percentage points). This selected union does not establish full-suite
coverage or regression status. Reports, receipts, and comparison artifacts
remain ignored under `build/parity/coverage/value-lifetime-20261005/`.

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

## UploadFile backing-file replacement during size arithmetic

Four further input-only cases replace the public backing file from the size
integer's __add__ callback. Replacement content and rolled state come from the
input; each memory/worker I/O variant is collected on the caller and a worker.
The consumer observes which public file receives each write, the write thread,
bytes remaining in both files, size, identity, and the same finalizer/GC tape.
These are normally reachable oracle parity cases and require no internal fault
hook. Existing target-only route-cache fault contracts remain selected controls.

Live reproduction `87a15439-dca5-4087-b182-e040018cc61c` failed all four new
comparisons, while its normal route-cache control and both fault contracts
passed. Rust captured the file before the user arithmetic callback, writing
the first chunk into the original file and using its memory/worker policy.
The source uses the replacement. Rust now reads policy fields after arithmetic
and retrieves the current file again before I/O method lookup. Native borrows
remain released before every Python callback. Broader reentrant policy and
subclass callbacks still need their own input-driven comparisons.

Selected verification `184aca5c-dccd-42c4-a744-791d5ec202b0` passed 68/68 ordinary package comparisons and both target-only fault contracts, with zero failures, infrastructure errors, or not-run selected rows. The four new cases match exact file bytes, write targets, worker selection, and lifetime observations. Result SHA-256: `922e5d0236e65801e5e371f4eb7901e0b629d43e89f9fce04f995a17fa4bea96`; normal package tree: `9e63ddf110e4a78a06bfed9af5549e44ea9196d03426a67bc8c4dc8f99553212`. The selection also includes all earlier Request/value lifetime cases and the existing upload rollover workflow.

Coverage MCP verified 7 additional Rust lines for the replacement cases on matching source/build receipts. The baseline selected the two arithmetic-read controls, existing upload rollover workflow, normal route-cache control, and both fault contracts. The batch selected the four replacement cases with the same route-cache controls. Both live selections passed: baseline 3,155/24,937, batch 2,985/24,937, union 3,162/24,937. This selected union does not establish full-suite coverage or regressions. Receipts and reports remain ignored under `build/parity/coverage/upload-file-reentry-20261005/`.

## Clean full verification after UploadFile callback ordering fix

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

## In-place arithmetic and worker cancellation inputs

Fourteen further UploadFile inputs supply an integer subclass with __iadd__. Its
input-selected behavior returns a computed integer, the original object,
NotImplemented or None, or raises a user exception; computed results use an input integer adjustment. Replacement
file variants preserve the earlier memory/worker and caller/worker collection
boundaries. Public size observations are converted to integers, while identity
is recorded separately, so the result observer does not retain a user size
object after releasing the public container.

Eighteen further inputs drive public read/write/seek/close calls against a
user file whose rolled state is supplied in construction. A user method signals
entry, waits for the consumer's release barrier, then returns or raises the
input-selected exception. Asyncio and Trio AnyIO-scope cancellation variants
record shielded completion, scope flags, user-error identity, arguments and
cause/context categories. Raw asyncio Task.cancel variants supply a cancellation
message and observe the await outcome before releasing the worker. A bounded
input watchdog releases stalled I/O and remains visible in the result; it never
selects or manufactures a passing outcome.

The consumer waits for user I/O completion before loop teardown and collection.
Asyncio's user worker is joined after loop exit; Trio owns its persistent worker
cache, which is not modified by the consumer. Byte returns, file closure, size,
write targets, callback events, weak references, every finalizer, unraisable
error, and warning remain live observations. Input-defined user file exceptions
are normal oracle parity cases. The two target-only route-cache fault contracts
continue as controls. The runtime Python facade is unchanged.

The extended live reproduction `b8317c14-c382-4f0b-a93a-547a865a5e46` failed all
14 new arithmetic comparisons. Its 18 worker cases, normal route-cache control,
and both fault contracts passed, with no infrastructure errors or skipped rows.
Every worker source observation released both user objects after collection and
reported no unraisable errors. Rust now calls CPython's in-place operator through
the safe PyO3 pattern already used for body-limit arithmetic. Rust keeps the
state/assignment and I/O policy; Python's own object protocol performs numeric
subclass dispatch. No Python algorithm or runtime facade is added. A None result
is stored as the existing absent size state so subsequent writes skip arithmetic.
User exceptions propagate before assignment and file-policy selection, and old
values still drop after the native borrow is released.

Selected verification `ce4f9633-2558-41e5-bf8d-1cb088292116` passed 102/102 ordinary package comparisons and both fault contracts with zero failures, infrastructure errors or not-run selected rows. It includes all 32 new inputs, every earlier Request/value lifetime input, the existing upload rollover workflow and both FormData constructor cases. Result SHA-256: `4bb88e662745f3a34b39009b4195a9753e048506ceed3b6412366aa42cb7e86f`; normal package tree: `6fd042132fec89afac089aca463dc2802844f176daf091ba64bea8d06700848d`. All new arithmetic and worker observations remain exact.

Coverage MCP verified 3 additional Rust lines on matching source/build receipts. The baseline selected all six earlier arithmetic/replacement inputs plus upload rollover and the normal/fault route-cache controls. The batch selected the 32 new inputs with those same route-cache controls. Both live selections passed: baseline 3,167/24,942, batch 3,089/24,942, union 3,170/24,942. This is selected incremental coverage, with full-suite regression status unknown. Receipts and reports remain ignored under `build/parity/coverage/upload-operation-lifetime-20261005/`.
