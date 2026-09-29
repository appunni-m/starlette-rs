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
active and incomplete. At the source-mapping checkpoint, the parity manifest indexed 118 input-only cases
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

The current contract has 274 input-only cases across 36 files, covering 54
operations and 337 requirements. The latest integrated run
`c4297f66-3487-473a-9c80-f70cff27f16d` selected 386 comparisons: 382 passed,
zero failed, zero infrastructure errors, and four were `not_run`. The Python
package passed all 272 applicable cases; Rust-native passed 110 of 114 selected
cases. The four Rust-native rows require arbitrary Python callables. Both target
trees were dirty, so this is not release proof. Manifest SHA-256:
`99bd4d7246111229c86a093b4356ef197681669a44dccd38e083080e7bea5ce5`. See
[Migration parity contract and evidence](../PARITY.md) for current scope and
the case breakdown; the Router/GZip benchmark lane remains `not_proven`.

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
is required for `existing` and otherwise empty. It names the authored YAML
source definition under `tests/fixtures/sources/parity/`, never the generated
runtime JSON under ignored `build/parity/inputs/`. An `not_applicable` row
requires a concrete reason, such as documentation with no independent runtime behavior;
private helpers must not silently disappear. Test support helpers and modules
use `test_support` and explain their downstream fixture role or why they have no
independent parity behavior.

Mark a row `existing` only after reading the referenced YAML source definition
and confirming that it stimulates the behavior and contains every listed observation
selector. A related route or response example is not enough to claim coverage
for a different public invocation shape.

The crosswalk maps each source behavior only when an input directly stimulates
and observes it. The checked-in generated `coverage-matrix.csv` has 789 rows:
58 `existing` mappings, 681 `backlog` rows, and 50 reasoned `not_applicable`
rows. It maps the exception and registered-handler source behaviors to their
input-only fixtures; the matrix is not a one-to-one index of active parity
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

The command checks exact upstream identity, one-to-one catalog-row disposition,
evidence paths, all AST-discovered test functions (including parameter-family
rows), every shared test support module, all documentation navigation pages,
and input-only fixture paths. It writes `api-review.csv`,
`coverage-matrix.csv` (all mapped source items), and `fixture-backlog.csv`
(items still needing new input fixtures) in this directory.

For the pinned Starlette 1.6.0 source, the checked-in merge snapshot covers all
999 API candidates, all 514 test functions, 24 documentation navigation pages,
and four shared test support modules. The API review has 514 `supported`, 286
`private/internal`, and 199 `uncertain` candidates. The coverage matrix has 789
source mappings: 58 existing input mappings, 50 reasoned `not_applicable`
entries, and 681 input-only backlog rows. These counts describe the current
atlas crosswalk snapshot, not implementation parity or a one-to-one inventory
of active parity cases.
`PRIORITIZED_BACKLOG.md` gives the current work order and points to bounded
evidence. Add `--check` to validate partitions without writing merged files.
Regenerate runtime JSON inputs with `make parity-inputs` before running parity
or benchmark commands; generated inputs and result artifacts are local build
outputs, not checked-in source fixtures.
