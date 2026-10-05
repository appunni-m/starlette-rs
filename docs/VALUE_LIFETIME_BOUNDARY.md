# Public value and worker collection boundary

## Input-only public consumers

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.
[`public-value-lifetime.yaml`](../tests/fixtures/sources/parity/public-value-lifetime.yaml)
contains 24 cases for ImmutableMultiDict, MultiDict, Headers, MutableHeaders,
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

## Clean full verification after public value ownership fixes

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
