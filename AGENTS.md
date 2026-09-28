# Project binding rules

- Compatibility authority is Starlette 1.6.0 at
  `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. Update the pin, inventories,
  fixtures, and provenance together if that authority changes.
- The goal is a full Starlette replacement. Preserve documented
  `starlette.*` import paths, behavior, and ordinary ASGI interoperability;
  keep the Rust-native API additive. Do not absorb FastAPI or Pydantic work.
- Keep Python the thinnest compatibility layer possible. Put routing,
  response construction, middleware decisions, protocol state, and other
  Starlette semantics in Rust. Python may provide the required `starlette.*`
  import surface and only the glue Python requires: value conversion, Python
  callable invocation/awaiting on Python's event loop, and faithful exception
  and lifetime propagation. Do not duplicate semantic algorithms in Python or
  fall back to upstream Starlette at runtime. Prototype and document every
  unavoidable Python-only behavior at the boundary.
- Treat new Python behavior as disallowed by default. Before adding Python
  code beyond import/API wrappers, representation conversion, calling and
  awaiting user Python code, or exception/lifetime forwarding, document why
  the behavior cannot live in Rust while preserving the Python contract; add
  input-only oracle comparisons for that boundary before accepting the change.
- Use docs, root exports, API references, release notes, tests, and explicit
  compatibility imports as evidence for public status. A non-underscored name
  or a successful import alone does not make an implementation helper public.
  Keep unresolved candidates visible in `docs/COMPATIBILITY_INVENTORY.md`.
- Keep root `metadata.yaml` as the source of truth for pinned API-source
  references. It lists every public upstream `starlette/**/*.py` module plus
  the documentation and test source roots used by the API/compatibility
  inventory. Generate the API candidate catalog from that metadata and the
  pinned checkout.
- Treat arbitrary Python sync/async callables, Python event-loop ownership,
  cancellation, context variables, streaming, exceptions, and lifespan as
  boundary requirements. Do not call Python endpoints from Rust until the
  runtime and error propagation contract has been reviewed and prototyped.
- `tests/fixtures/manifest.yaml` is the one active contract manifest. Parity
  and benchmark stimuli are authored as YAML-compatible input definitions
  under `tests/fixtures/sources/`; generate runtime JSON only under the ignored
  `build/parity/inputs/` directory. Never check generated parity-input JSON or
  result JSON into the repository. Never put expected outputs or pass/fail
  expectations in metadata or input definitions. Preserve unsupported and
  skipped cases in generated result artifacts.
- Maintain zero unit tests. Behavioral tests are input-driven parity
  comparisons that run the pinned source oracle against the installed Python
  package and Rust target through their public consumer interfaces.
- Adapters dispatch by the manifest operation and derive every stimulus from
  the supplied input. A `case_id`, workload ID, requirement ID, or result
  artifact must never select hard-coded inputs, outputs, expected status, or a
  special comparison path. Keep every output on the live oracle/target side.
- Keep oracle, Rust-native, and Python-package runs isolated. Compare public
  consumer interfaces and use exact comparison unless a reusable normalization
  is documented in the manifest.
- Do not claim full parity from a passing slice. Keep the pinned Starlette
  denominators visible: 514 upstream test functions and 24 documented pages.
  Derive the changing fixture-mapping and backlog counts from the generated
  `docs/atlas/coverage-matrix.csv` and `docs/atlas/fixture-backlog.csv`; do not
  hard-code an old backlog count in project policy. Every runtime behavior
  needs an input-only oracle comparison, and every genuine non-runtime item
  needs an explicit source-backed `not_applicable` reason.
- Preserve upstream BSD-3-Clause notices for reused material. Record
  provenance and licenses for dependencies, fixtures, docs, and assets. Do not
  copy upstream test files wholesale.
- Never publish packages, push branches, or create commits without an explicit
  request. Keep changes reviewable and do not claim drop-in compatibility
  before installed-package consumer checks pass.
