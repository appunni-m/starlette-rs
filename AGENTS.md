# Project binding rules

- Compatibility authority is Starlette 1.6.0 at
  `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. Update the pin, inventories,
  fixtures, and provenance together if that authority changes.
- The goal is a full Starlette replacement. Preserve documented
  `starlette.*` import paths, behavior, and ordinary ASGI interoperability.
  This is a greenfield project: the pre-release `starlette-rs` API and
  implementation carry no backward-compatibility guarantee and may be
  redesigned freely. Keep Rust-native APIs distinct from the compatibility
  surface. Do not absorb FastAPI or Pydantic work.
- Complete the remaining implementation across feature families first, then
  run the full parity matrix and fix mismatches together, then measure full
  coverage, then run the complete benchmark workload. Do not repeat these
  phases for each individual feature. Author input-only comparisons alongside
  implementation, but defer their execution to the full parity phase. Build
  and static quality checks may run during implementation. Keep unfinished
  implementation and unexecuted comparisons explicit in progress reports.
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
- Runtime Python modules are forwarding facades: keep Starlette behavior,
  branching, iteration, event ordering, scheduling, and error policy in Rust.
  Python should construct or hold Rust objects, convert values at the PyO3
  boundary, pass user callables and ASGI callbacks through, and await native
  callables. Do not add Python `if`/`else`, loop, `raise`, or `assert` behavior
  to runtime wrappers; ask Rust to select and propagate the corresponding
  outcome. Existing Python-owned behavior is migration work, not the target
  design.
- Preserve documented Python typing contracts that static consumers observe,
  including generic class parameters and the `py.typed` package marker. These
  are Python type-system metadata and cannot be supplied by Rust runtime
  algorithms while preserving `Request[State]` and `WebSocket[State]` checking.
  Keep the facade additions declarative (`TypeVar`, `Generic`, and annotations),
  declare any directly imported typing backport, and verify input-derived
  consumer snippets against both the pinned source and installed package with
  the same pinned type checker. Do not add runtime branching to support typing.
- The upstream `starlette` distribution is a development-time oracle only. Do
  not import it or declare it as a runtime dependency; the installed package's
  own `starlette.*` modules must be backed by this repository.
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
  `scripts/check_project_policy.py` enforces the absence of conventional
  Python/Rust test sources and test-framework imports; keep `make test` bound
  to the live parity runner.
- Preserve the workspace Rust lint levels, `rustfmt.toml`, pinned Ruff
  configuration, and CI quality gates. Do not weaken or blanket-disable them
  to clear a failure. Any necessary lint exception must be narrowly scoped and
  carry a code comment explaining the specific compatibility or safety reason.
- Keep explicit Rust panic paths out of runtime code. The workspace denies
  `clippy::panic`; return a typed error for recoverable failures and retain
  invariant assertions only when they cannot be triggered by valid public input.
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

<!-- BEGIN KATA (managed by `kata init --with-agents`) -->
Kata is the system of record for intent.

- Never `kata delete` or `kata purge` without explicit user authorization.

~~~dot
digraph kata {
  rankdir=TB; node [shape=box];

  arrive   [shape=diamond label="Work arrives"];
  search   [label="Search first:\nkata search \"<terms>\" --agent\nReuse an open issue or create one."];
  route    [shape=diamond label="Work it, or delegate it?"];

  subgraph cluster_work {
    label="";
    claim  [label="On claim or start, mark it tracked:\nkata meta set <ref> work.attention ok"];
    branch [label="If the work happens on a dedicated branch, stamp it once:\nkata meta set <ref> work.branch <branch>\nor bind at creation:\nkata create ... --meta work.branch=<branch> --idempotency-key <key>"];
    live   [label="Keep state current:\nkata meta set <ref> work.attention stuck|needs-human|ok\nkata meta set <ref> work.attention_msg \"<why>\"\nstuck = blocked; needs-human = input/review; ok = unblocked.\nRequest attention:\nkata notify <ref> --to <actor>[/<teammate>] --message <reason>"];
    claim -> branch -> live;
  }

  subgraph cluster_delegate {
    label="";
    fanout [label="Tracked children: --parent <ref>, --meta work.branch=<branch>,\n--idempotency-key <key>, --json; capture .issue.short_id.\nSubagents: distinct KATA_TEAMMATE and\nKATA_INBOX_USER=<actor>/<teammate>; keep the actor.\nRead requests: kata inbox --for <actor>[/<teammate>].\nAfter handling: kata notify <ref> --to <actor>[/<teammate>] --clear."];
    join   [label="Join with kata wait <refs> --until attention --any\nMatches needs-human or stuck; a close also completes the wait,\nand the reported reason distinguishes which. Use --timeout so a\nwrapper can tell timeout from satisfaction."];
    coord  [label="Read delegated work.*; never write it."];
    fanout -> join -> coord;
  }

  done     [shape=diamond label="Verified complete?"];
  close    [label="kata close <ref> --done\nwith a message and evidence"];
  review   [label="kata label add <ref> needs-review\nplus a comment on what remains"];
  park     [shape=diamond label="Park it?"];
  schedule [label="kata schedule <ref> <date-or-time>\nsets scheduled_on; clear with -"];
  someday  [label="kata meta set <ref> someday true --json-value\nclear with kata meta unset <ref> someday"];

  arrive -> search -> route;
  route -> claim   [label="work it"];
  route -> fanout  [label="delegate it"];
  route -> park    [label="record only"];
  live  -> done;
  coord -> done;
  done -> close    [label="yes"];
  done -> park     [label="no"];
  park -> schedule [label="start date known"];
  park -> someday  [label="start date unknown"];
  park -> review   [label="needs review"];
}
~~~

Parent links group work; they do not gate readiness, but a parent cannot close with open children.
Use --blocks <dependent> / --blocked-by <prerequisite> only for real prerequisites; they gate kata ready.
Use --related <ref> for context only. kata wait observes state without requiring a dependency edge.

One writer per key: only write your own work.*. Ignore work.* on closed issues; never write it there.
Before stopping, close completed work or update both work.attention and work.attention_msg for the handoff.

Schedule/someday defer work; deadlines don’t. kata deadline <ref> <date-or-time> sets deadline_on without changing readiness.
Reached schedules and deadlines use notify.* for the current owner, or the author when unowned; clear with kata notify <ref> --to <recipient> --clear.
<!-- END KATA -->
