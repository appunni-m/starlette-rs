# Compatibility atlas review format

The source authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The generated candidate catalog is
[`../api-surface.csv`](../api-surface.csv). Domain review files under
`reviews/` are evidence annotations keyed to catalog rows; they do not define a
second API surface.

Root [`metadata.yaml`](../../metadata.yaml) is authoritative for the pinned
API-source references and the public source, documentation, and test roots used
by inventory generation. Parity fixture rows point to authored, JSON-compatible
YAML under `tests/fixtures/sources/parity/`; the active manifest indexes
generated JSON under ignored `build/parity/inputs/`. Run `make parity-inputs`
to regenerate those runtime inputs. Result JSON under `build/parity/` is also
local ignored output and is not committed.

Pinned source denominator: 999 generated API/documentation candidate rows,
including the root `starlette.__version__` export; 30 `test_*.py` modules, 514
AST-discovered test functions/methods, and 24 documentation navigation pages.
The upstream test tree has 34 Python files total, including four
shared/support modules. These pinned source tests are inventoried as the
compatibility denominator; this repository's behavioral gate is live parity,
with no conventional Python or Rust unit-test suite.

## Current implementation status

The source atlas is complete, while the full Starlette replacement remains
active and incomplete. The current contract has 742 input-only cases across
83 indexed files, 94 operations, and 775 requirements. It includes direct
UploadFile constructor/repr, rollover, and threadpool-boundary cases, GZip thread-threshold cases, a shared
AnyIO thread-pool limiter case, and the
generic Request/WebSocket lifespan-state typing contract. Seven QueryParams
cases
map equality and blank-value behavior to two pinned test rows. The latest
full-slice run `a5c1537c-624f-4413-9f22-929c5f9d9c36` passed 952 of 956
selected profile comparisons, with zero failures or infrastructure errors and
four Rust-native Python-callable rows `not_run`. The Python package passed
740/740; Rust-native passed 212/216. Six protected WebSocket authentication
cases pass source/package comparison for plain and injection-wrapped routes
with missing, malformed, and valid Basic credentials. Three documentation-derived
BasicAuth cases also pass for wrong-scheme, malformed base64, and non-ASCII
credentials. The UploadFile input compares direct
construction, omitted-size operations, default and explicit-header repr values,
rolled/in-memory scheduling, event-loop progress, and OSError propagation. The
thread-pool limiter input observed the
same default capacity of 40, configured limit of 2, one waiting worker, and
restored capacity of 40 on source and package. Three BaseHTTPMiddleware
exception-context cases, covering no chain, implicit context, and explicit cause, pass with empty
diffs. Three
StaticFiles HTML fallback scenarios and seven built-in float/UUID converter
cases pass on both target profiles. Default-string match
and slash-boundary inputs and int/path converter observations also pass on both
profiles. Both input-defined datetime-converter cases pass on the Python
package. All nine selected
`CommaSeparatedStrings` comparisons pass,
including lone-surrogate strings through parsing, sequence values, and subclass
`__repr__`. The PyO3 boundary uses UTF-32LE with `surrogatepass`; parsing and
formatting remain Rust-owned. Asyncio and Trio TestClient lifespan task-group
child lifecycle cases also pass on the Python package. The WebSocket state
sequence covers ten cases, including four denial-response transitions;
package-only convenience inputs
check fresh-iterator `asend(non-None)` and invalid JSON modes. GZip adds direct
package-profile `GZipResponder` checks for exclusion normalization and
compression without negotiation, plus final and streaming middleware inputs
at the `thread_minimum_size` boundary. The four native rows are synchronous
Request endpoint, bound-method endpoint, partial endpoint, and callable-instance ASGI
dispatch. Full run and wheel identities are recorded in
[Migration parity contract and evidence](../PARITY.md); this bounded evidence
does not establish full Starlette parity or release readiness.

The generated coverage matrix has 802 source rows: 462 input mappings, 51
reasoned `not_applicable` rows, and 289 fixture-backlog rows.
Derive these changing counts from the generated atlas CSV files.

The latest Router/GZip run `bfac1bab-98b4-4544-8d45-b1c4098b5424` measured all
74 source/package workloads after correctness preflight
`f8e77519-0312-4db6-a876-b1ad91517f2e`. Median per-workload source/package
latency ratios were 0.761 for Router and 0.976 for GZip; source latency was
lower on five of six Router workloads and 62 of 68 GZip workloads. All 74
source/package observation hashes matched. See
[Benchmark mapping](../BENCHMARKS.md) for the timing summary and limits. These
bounded results do not establish full compatibility.

At the source-mapping checkpoint, the parity manifest indexed 118 input-only cases
across 18 files: 38 request/routing cases, 21 reverse-URL cases, four direct
Starlette ASGI cases, eight basic Response/JSONResponse ASGI-call cases, four
finite synchronous and one finite async-iterator StreamingResponse ASGI-call
cases, four RedirectResponse ASGI-call cases,
eight GZip cases, six full WebSocket
protocol-tape cases, six projected WebSocket state cases, five Request-style
HTTPException cases, two callable-ASGI HTTPException cases, two registered-
handler cases, and nine server-error cases. Reverse-URL, custom-converter,
and async-iterator streaming cases select the Python-package profile. Built-in
Router, slash-redirect, RedirectResponse, Response, JSONResponse, and four
synchronous StreamingResponse cases select both profiles. Mount cases select
both with Rust-native explicitly unsupported. Projected state cases select
both profiles. The integrated checkpoint run
`296735f7-a06b-465e-958b-44f40b32b88c`, finished at
`2026-09-28T12:04:18.052Z`, selected 181 comparisons: 175 passed, zero failed,
six Rust-native rows were `not_run`, and there were zero infrastructure errors.
All 118 Python-package cases passed; Rust-native passed 57 of 63 selected
cases. The six `not_run` rows are unsupported Python-callable and Mount
boundaries. All six slash-redirect, four RedirectResponse, all eight basic
Response/JSONResponse, and all four finite synchronous StreamingResponse cases
passed on both profiles. The finite async-iterator case passed on the Python
package. All 21 reverse-URL and all 21 selected WebSocket comparisons
passed. The six native `not_run` rows
cause `run` to exit with status 2, so the all-target gate remains incomplete.
Target identities were dirty local trees; this run is not clean aggregate or
release proof. The server-error inputs verify default and registered 500 handling,
special handler-key order, text/HTML debug responses, response-start behavior,
and the inner `HTTPException(500)` path. The artifact status is `completed`,
and the separate Router/GZip benchmark lane completed all 74 source/package
workloads; its evidence is summarized in
[Benchmark mapping](../BENCHMARKS.md) and recorded in local generated result
files under `build/parity/`. These bounded results do not establish full
compatibility.

The latest contract and run are recorded above. All 28
FileResponse cases passed on both profiles; all eight SessionMiddleware cases
and all twenty-one BaseHTTPMiddleware cases passed on the Python package profile.
The BaseHTTP cases cover configured-header mutation, awaited `call_next`
response replacement, request-body cache replay, response-completion
unblocking downstream receive, exception-context propagation, caught
downstream ValueError handling, partial-stream forwarding, receive
transformation, repeated disconnect polling, downstream disconnect
propagation followed by request disconnect observation, body-cache/disconnect
ordering, stream consumption followed by a
downstream body read, body buffering followed by a downstream stream read,
dispatch stream reads after downstream stream/body consumption, cached stream
replay after the endpoint reads a body cached by dispatch, a downstream body
read after dispatch caches the request body, and a downstream stream read after
dispatch exhausts `request.stream()`, and dispatch closing a consumed response
stream while the downstream app streams until disconnect, and pathsend forwarding.
The caught case matches `tests/middleware/test_base.py:338-356`: dispatch
catches `ValueError("TEST")` from `call_next` and returns a plain-text 400
response whose body comes from `str(exc)`. In the partial-stream case, dispatch
consumes `b"1"`, the endpoint reads the next chunk `b"2"`, then dispatch resumes
and consumes `b"3"` after `call_next`; see
`tests/middleware/test_base.py:777-832`. In the receive-transformation case,
dispatch reads `b"foo "`, the downstream ASGI wrapper duplicates the request
body, and the endpoint reads `b"foo foo "`; this is pinned at
`tests/middleware/test_base.py:979-1017`. The two repeated-disconnect inputs
cover `send_body=True` and `False`, poll downstream receive twice, and observe
raw/downstream receive traces, drained requests, poll results, and the exact
`200 b"good!"` response tape; see
`tests/middleware/test_base.py:1168-1215`. The disconnect-observation cases map
to `test_read_request_disconnected_client` and
`test_read_request_disconnected_after_consuming_steam` at
`tests/middleware/test_base.py:894-976`: one observes a downstream disconnect
before dispatch checks `Request.is_disconnected()`, and the other caches
`b"hi"`, checks for disconnect, then verifies the downstream body and
disconnect sequence. Source and package observations match. The
stream-consumption case maps to
`test_read_request_body_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:660-686`: dispatch exhausts the stream, then the
downstream endpoint reads the cached empty body and returns `Homepage`. The
body-cache/stream-replay case maps to
`test_read_request_stream_in_app_after_middleware_calls_body` at
`tests/middleware/test_base.py:631-657`: dispatch buffers `b"a"`, then the
downstream stream yields `b"a"` and `b""` before returning `Homepage`. The
source test offers asyncio and Trio test-client backends; this input uses the
Python-package profile and does not establish parity for both backends. The
two post-call-next cases map to
`test_read_request_stream_in_dispatch_after_app_calls_stream` and
`test_read_request_stream_in_dispatch_after_app_calls_body` at
`tests/middleware/test_base.py:715-773`. Each captures the live stream-read
outcome in dispatch without embedding an expected exception. They run through
the asyncio package profile and do not establish Trio parity. The downstream-stream-after-consumption case maps to
`test_read_request_stream_in_app_after_middleware_calls_stream` at
`tests/middleware/test_base.py:599-628`: dispatch drains `b"a"`, the terminal
empty chunk, and iterator exhaustion before `call_next`; downstream stream
iteration then yields only the cached empty chunk. All observed stream reads,
response fields, and ASGI events match the source. The body-cache case maps to
`test_read_request_body_in_app_after_middleware_calls_body` at
`tests/middleware/test_base.py:689-712`: adapters record `b"a"` from
dispatch and the downstream endpoint, and the response returns those
bytes. Both live observations match. The pre-call-next cache
case maps to
`test_read_request_stream_in_dispatch_after_app_calls_body_with_middleware_calling_body_before_call_next`
at `tests/middleware/test_base.py:835-862`: dispatch reads the body before
`call_next`, the endpoint reads it, and dispatch's stream yields the cached
bytes, an empty terminal chunk, then exhaustion. All source/package observations
match exactly. Other
receive-transform/wrapper combinations, further partial-stream/replay
interleavings, disconnect ordering across stacked middleware, broader
exception-group shapes beyond the observed TaskGroup context, varied or
malformed `http.response.debug` frames, cancellation and cleanup ordering,
path-send combinations beyond the covered FileResponse forwarding case, and additional streaming behaviors remain unproven. The
Rust-native target was clean at revision
`7ab9f0cee22b03035b96c2c2df5c66cc6a1d28c8+source-fnv1a64-3f737351c1674203`;
the Python-package target tree SHA-256 is
`99fd7a11cb20c8a9bda279f5807b621c4dd3a08f86dca79503bb135319edc492`. Manifest
SHA-256: `63a853e8902fb9f59e184d0fb6e32280cd5811175427ed4101fe1a23b84485c8`;
package wheel SHA-256:
`4a1736486aed60dc5a4e1894c076f919617080548874f4f79d385f72d9e88a00`. See
[Migration parity contract and evidence](../PARITY.md) for current scope and
the case breakdown; Rust-native parity remains incomplete.

## Candidate review CSV

Each review partition covers an explicit set of modules and includes one row
for every matching catalog row, including documented import references,
re-export candidates, constructors, and special methods. Preserve every
catalog field verbatim. Use the logical CSV record ordinal, including the
header as record 1, as `catalog_row` to make duplicate aliases unambiguous; it
is not a physical file-line count.

Columns (retain every generated catalog field verbatim before the review fields):

```text
catalog_row,record_type,qualified_name,signature_or_value,constructor_signature,source,line,documentation_evidence,audit_status,api_disposition,evidence_refs,rationale
```

`api_disposition` is exactly `supported`, `private/internal`, or `uncertain`.
It records whether the pinned upstream treats the name as part of the source
contract; it does not claim Starlette-RS has implemented it.
Use `supported` only when pinned docs, public reference, root export, release
notes, or a deliberate public compatibility export establish the contract.
A test alone may corroborate but does not make a helper public. Use
`private/internal` for an explicitly private helper or source-only machinery
with clear internal role. Use `uncertain` when evidence does not establish the
intended status. Cite repository-relative source/docs/test paths and line or
test-function names in `evidence_refs`, separated by semicolons; do not rely on
importability alone.

## Fixture backlog CSV

Create one or more rows for each upstream test function or parametrized
behavior family and each independently observable documented feature. Use the
exact module-level name such as `test_matches` or class method name such as
`TestRoute.test_matches` in `source_item`; put parameter sets in the stimulus
summary rather than changing the source identity. Multiple rows may map one
test function to distinct public requirements. Do not copy upstream test bodies
or record expected outputs.

Columns:

```text
backlog_id,source_kind,source_path,source_item,api_disposition,requirement_ids,stimulus_summary,observation_selectors,fixture_status,fixture_path,exclusion_reason,evidence_refs
```

`backlog_id` is a stable unique ID for the independently mapped source
behavior; use a distinct ID for each row, even when two rows may later share
one executable workflow.

`source_kind` is `upstream_test`, `test_support`, `documentation`, `deprecation`,
`optional_feature`, `python_version`, or `api_behavior`. IDs use the exact
`starlette.*` public spelling where a symbol is involved. `stimulus_summary`
describes only the app/request/events/arguments/assets to supply. Observation
selectors name what a future live runner records, never the expected value.
`fixture_status` is `existing`, `backlog`, or `not_applicable`. `fixture_path`
is required for `existing` and otherwise empty. It names one or more authored
YAML source definitions under `tests/fixtures/sources/parity/`, separated by
semicolons; the merger validates each path. It never names generated runtime
JSON under ignored `build/parity/inputs/`. An `not_applicable` row
requires a concrete reason, such as documentation with no independent runtime behavior;
private helpers must not silently disappear. Test support helpers and modules
use `test_support` and explain their downstream fixture role or why they have no
independent parity behavior.

Mark a row `existing` only after reading the referenced YAML source definition
and confirming that it stimulates the behavior and contains every listed observation
selector. A related route or response example is not enough to claim coverage
for a different public invocation shape.

The crosswalk maps each source behavior only when an input directly stimulates
and observes it. The checked-in generated `coverage-matrix.csv` has 802 source rows:
435 `existing` mappings, 316 `backlog` rows, and 51 reasoned `not_applicable`
rows. It maps exception, registered-handler, and direct
`ServerErrorMiddleware` custom-handler behavior to input-only fixtures; the
matrix is not a one-to-one index of active parity
cases. Some active inputs may therefore cover behavior whose other source
rows remain `backlog`. Do not read that CSV status as proof that those
behaviors are absent or untested. Promote mappings only after matching the
fixture's stimulus and every listed selector to the source behavior.

## Partition rules

- Domain files must not overlap on catalog rows or own the merged index.
- Include exact upstream test and docs paths. Capture test function names,
  parametrization, and relevant source lines where practical.
- Map fixture requirements to `backlog_id` values that can later be promoted
  to manifest requirement and case IDs.
- Record deprecation category/message/stacklevel inspection separately from
  lifecycle classification.
- Mark unobservable type-only contracts as `not_applicable` for runtime parity
  only when a suitable API/signature check is specified separately.
- Keep source review notes in their domain partitions. The checked-in merger
  joins them to `api-surface.csv`, rejects duplicate IDs or uncovered source
  items, and writes the merged matrix and backlog below.

## Merge and audit

After all domain partitions are present, run:

```sh
python3 scripts/merge_compatibility_atlas.py \
  --upstream /path/to/starlette
```

Use `make source-inventory-check STARLETTE_ORACLE_ROOT=/path/to/starlette` to
check the metadata-derived candidate catalog and atlas without rewriting the
checked-in CSV files. The source-parity CI job runs this check against the
pinned checkout.

The command checks exact upstream identity, one-to-one catalog-row disposition,
evidence paths, all AST-discovered test functions (including parameter-family
rows), every shared test support module, all documentation navigation pages,
and input-only fixture paths. It writes `api-review.csv`,
`coverage-matrix.csv` (all mapped source items), and `fixture-backlog.csv`
(items still needing new input fixtures) in this directory.

For the pinned Starlette 1.6.0 source, the checked-in merge snapshot covers all
999 API candidates, all 514 test functions, 24 documentation navigation pages,
and four shared test support modules. The API review has 517 `supported`, 285
`private/internal`, and 197 `uncertain` candidates. The coverage matrix has 802
source rows: 435 input mappings, 51 reasoned `not_applicable`
entries, and 316 input-only backlog rows. Derive these changing counts from
the generated atlas CSV files. They describe the crosswalk, not implementation
parity or a one-to-one inventory of active parity cases.
`PRIORITIZED_BACKLOG.md` gives the current work order and points to bounded
evidence. Add `--check` to validate partitions without writing merged files.
Regenerate runtime JSON inputs with `make parity-inputs` before running parity
or benchmark commands; generated inputs and result artifacts are local build
outputs, not checked-in source fixtures.
