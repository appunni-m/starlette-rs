# Final independent compatibility-atlas audit (crosswalk snapshot)

**Result: PASS.** The merged Starlette 1.6.0 atlas meets the milestone
checklist at source commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The original atlas audit was
read-only and did not run the project test suite; current parity and test
results are recorded below.

This audit is a historical snapshot of the crosswalk and the pre-WebSocket
parity state. Its 781-mapping and 36-case counts are preserved as recorded at
audit time. See the current
[`COMPATIBILITY_INVENTORY.md`](../COMPATIBILITY_INVENTORY.md) for the active
manifest and crosswalk counts.

## Status recorded at audit time

The matrix counts are a crosswalk snapshot, not proof of all-source runtime
coverage. The then-active parity manifest contained 36 cases across seven files:
seven request/routing cases, three direct ASGI cases, eight GZip cases, five
Request-style HTTPException cases, two callable-ASGI HTTPException cases,
two registered-handler cases, and nine server-error cases. Run
`fd22f534-80bb-4763-9245-d37abc53dec7` selected 55 comparisons: 51 executed
and passed, zero failed, four Rust-native callable rows were `not_run`, and
there were zero infrastructure errors. All 36 Python-package cases passed;
Rust-native passed 15 cases, with four additional selected native rows
`not_run`. The server-error cases verify default and registered 500 handling,
special handler-key order, text/HTML debug responses, response-start behavior,
and the inner `HTTPException(500)` path. The earlier HTTPException cases cover
five pre-response-start errors from matched request-style endpoints and one
after-start callable-ASGI error with its chain and partial event tape; the
native response builder covers its explicit-detail 406 case. The four
`not_run` rows make `run` exit with status 2, so the all-target gate remains
incomplete. The current Python package suite passed 44 tests and the Rust
workspace suite passed all 48 core tests. The separate Router/GZip benchmark
lane completed all 74 source/package workloads. Run results are ignored local
artifacts under `build/parity/`; the scope and retained benchmark evidence are
described in [Migration parity](../PARITY.md) and [Benchmark mapping](../BENCHMARKS.md).
These bounded results do not make the full Starlette replacement complete.

## Verified coverage

- The pinned source checkout is at the exact 1.6.0 tag and commit. The
  read-only merger check reports **999/999 API candidates dispositioned**.
  The merged review contains 514 `supported`, 286 `private/internal`, and 199
  `uncertain` rows, each with evidence and rationale.
- The source tree independently yields **30 test modules and 514 test
  functions/methods**, **24 documentation navigation pages**, and **4 shared
  test support modules**. The merger confirms all are mapped.
- The coverage matrix at audit time had **781 mappings**: 537 upstream-test behavior rows,
  184 documentation rows, 23 API-behavior rows, 14 support-module rows, 7
  deprecation rows, 11 optional-feature rows, and 5 Python-version rows. Its
  fixture states are **13 existing**, **718 backlog**, and **50
  not_applicable**. Backlog IDs are unique; each N/A row has a reason. These
  are historical audit counts.
- At the time of the original audit, the sole `existing` row pointed to the input-only
  ASGI GET fixture. The fixture directly supplies two `x-parity-echo` headers
  and selects status, ordered repeated headers, response bytes, and ASGI event
  order. The input contains no expected outputs. Later crosswalk updates map
  five upstream HTTPException tests and the HTTPException documentation
  contract to the exception input files. The then-current matrix had 13 `existing`,
  718 `backlog`, and 50 `not_applicable` mappings, including the registered-
  handler and server-error cases. It is not a
  one-to-one index of all active parity cases; those counts do not imply that
  active inputs or parity evidence are missing.
- The constraints and crosswalk include the warning categories, messages,
  timing, and stack levels for the status aliases, `run_until_first_complete`,
  generator lifespans, WSGI import, TestClient timeout and HTTPX fallback, and
  the Config missing-file warning. All four status aliases appear in the
  lifecycle and warning mappings.
- Optional boundaries are represented for `itsdangerous`, Jinja2, multipart,
  PyYAML, and the preferred/fallback/missing HTTPX backend cases. Python 3.10–
  3.14, the conditional typing dependency, and the partitioned-cookie version
  boundary are mapped. Removed names and signatures are included in the
  `crosscut.removed-api-surface` probe. The named unresolved behaviors remain
  visible in the inventory and backlog.
- At the time of this atlas audit, the crosscut and constraints references
  resolved to atlas rows and checked target-documentation links and anchors
  resolved. The parity input directory contains only indexed input fixtures;
  no upstream test files were copied into the target.
- `PRIORITIZED_BACKLOG.md` keeps the Python/Rust boundary work and broad
  compatibility expansion active. At audit time its status recorded the 36-case
  parity result and separate 74-workload benchmark lane. It keeps the full
  replacement objective incomplete and says the atlas itself is not evidence
  of implementation parity.

## Corrections confirmed in the final tree

During this independent audit, the parent resolved the issues first observed:

- Added repeated response headers to the input used by the existing fixture
  crosswalk.
- Removed duplicate timeout/fallback and missing-HTTPX crosswalk rows.
- Consolidated duplicate lifespan warning mappings.
- Updated the inventory and atlas counts/state, completed P0, and expanded the
  removed-API probe to include the removals listed in `CONSTRAINTS.md`.

The final static command was:

```sh
python3 scripts/merge_compatibility_atlas.py --check \
  --upstream /Users/lazytrot/work/starlette
```

It completed successfully and reported 999 API dispositions, 781 coverage
mappings, all 30 test modules and 24 documentation navigation pages, and all
4 shared support modules. This verifies the atlas structure and source
crosswalks; it does not claim that the Rust implementation exists or passes
parity.
