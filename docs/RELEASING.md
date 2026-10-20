# Release readiness

This document tracks the non-publishing release path for the Rust crate, the
Python distribution, and their documentation. A published crate version is
permanent, and Python uploads are public releases. Nothing here authorizes a
package upload, tag, GitHub Release, or change to registry credentials.

Older dated sections below are historical checkpoints. They do not qualify the
current source or replace the status at the top of this file.

## Current preparation status (2026-10-21)

### Exact-candidate verification

The pinned compatibility authority is Starlette 1.6.0 at commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. At the start of this checkpoint,
`main` matched `origin/main` and the worktree was clean. The active full-parity
candidate is `c6d0266c5384a96496bd35d646b0d8ca3d4a75b7`; commits after it are
documentation-only. The Rust runtime, Python package runtime, fixtures, and
`metadata.yaml` match between the candidate and `main`. The candidate manifest
SHA-256 is
`cd091aae4e61813cc7edf3061764c763fbc9dc9a25c0009338f918a41c89eec7`.

Full verification workflow
[#31](https://github.com/appunni-m/starlette-rs/actions/runs/39510515682)
is running on the candidate. At 2026-10-20 23:34 UTC, all five CPython 3.10–3.14
jobs were executing source-to-target parity comparisons; there were no
completed jobs or result artifacts. This is an in-progress run, not a parity
pass. Its setup reported the pinned API catalog and coverage-atlas checks
passing: 999 API candidates dispositioned, 867 upstream source rows, 811
input mappings, 56 source-backed `not_applicable` rows, and zero fixture
backlog. The active inventory is 2,848 cases in 484 parity input files, plus
two benchmark input files. Generated runtime input and result JSON remain
ignored under `build/`.

No current-candidate coverage union or complete benchmark result exists. The
older parity, coverage, and package-smoke artifacts described in the history
below belong to earlier source revisions and do not qualify this candidate.
The required order remains: finish this full matrix, repair any real
mismatches together and rerun the full matrix on the repaired candidate, prove
100% of eligible Rust/PyO3 source lines across all six profiles, then run the
complete 74-workload benchmark.

### Release preparation state

The candidate declares version `0.1.0`, Rust edition 2024, and MSRV 1.85;
`starlette-rs-py` declares Python `>=3.10` and pins Maturin 1.14.1. These are
manifest declarations, not proof that the full platform and interpreter
matrices have been qualified. The prior Cargo archive and macOS wheel smokes
were built from older commits; rebuild and inspect the release artifacts from
the eventual proven candidate and verify installs outside the checkout.

Open release decisions include whether the Cargo archive should contain the
parity-adapter executable, the version/changelog policy, and the exact sdist
and wheel matrix. A read-only release audit at `a75fcacd` found zero
structural errors and two review findings: there is no Cargo publishing
workflow and no workspace changelog. The package file list at that revision
includes `src/bin/starlette-rs-parity-adapter.rs`; the package boundary is
unresolved. The read-only command
`cargo package --list --locked -p starlette-rs` did not build or inspect an
archive. Rust API documentation and repository Markdown checks have passed on
recent documentation-only descendants, but this does not establish package or
publication readiness.
Registry availability and publishing credentials remain unverified. No
publication action was taken as part of this checkpoint.

Release preparation remains separate from publication. Do not publish or tag
until the replacement, coverage, benchmark, and exact-candidate package gates
are proven and the remaining release decisions are resolved.

## Historical preparation status (2026-10-20; superseded)

Release preparation is tracked by Kata parent `n5d2` and its Cargo (`z74v`),
PyPI (`2pan`), and documentation (`c4cy`) tasks. The latest runtime/input
candidate on `main` is
`b0dab3263d91584a2b524cfd761d936bb5f73278`. Its runtime source matches
candidate `e9f8b181d681b0f057d5e2be9592578693f5079a`; the latest commit
corrects lowercase raw header names in one parity input. The active
`migration-parity/manifest@6` has 2,786 cases across 472 parity inputs and two
benchmark inputs, 157 compatibility operations, 18 Rust-native operations,
six target profiles, and 1,505 parity requirements. Its SHA-256 is
`ba792771a682e431b4ad1ba3be6a4e0cbe86ed9a71651a5da329571194ff22a5`; the
generated atlas has zero fixture-backlog rows. The pinned Starlette 1.6.0
authority remains commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.

The implementation workstream `asyj` is closed; the required remaining order
is one full parity matrix with grouped fixes, full eligible-line coverage, then
the complete benchmark workload. The latest runtime change is `62b091c8`
(`fix(cors)`); `b0dab326` changes only a parity input, and the manifest remains
unchanged from candidate `e9f8b181`. The release guide previously described a
benchmark-first order; that wording was stale and did not match the project
plan.

Full verification workflow
[#27](https://github.com/appunni-m/starlette-rs/actions/runs/39454724121)
failed all five CPython profiles on baseline `67abf21e`; coverage and the union
were skipped. Workflow
[#28](https://github.com/appunni-m/starlette-rs/actions/runs/39455513605)
was queued on `e9f8b181`, excludes the input correction in `b0dab326`, and was
canceled before it began.
Workflow [#29](https://github.com/appunni-m/starlette-rs/actions/runs/39463750152)
was dispatched on `main@3c3dd0fd`, containing the latest runtime/input
candidate. All five CPython profiles passed 16,041/16,041 comparisons and
47/47 fault contracts with zero failures, `not_run` rows, or infrastructure
errors. The parity matrix is proven for that candidate. Coverage is still
running: `rust-native-local` and CPython 3.10–3.12 succeeded; CPython 3.13 and
3.14 are measuring. The six-profile eligible-
line union is not available yet. The full current-candidate benchmark has not
run; no release candidate is qualified.

Release audits found the Cargo package boundary, Python distribution
installation contract, artifact matrix, and change/version policy still open.
The `starlette-rs` package list includes its parity-adapter binary; decide
whether that tool belongs in the public crate. The PyPI package installs the
`starlette` namespace and cannot safely share an environment with upstream
Starlette; the package README states this restriction. Python metadata
declares `>=3.10` but only classifies CPython 3.10–3.14. CI uses editable
installs, not candidate sdist/wheel qualification. No release workflow,
changelog, or static documentation-site deployment is configured.

Warnings-denied `make rustdoc-check` passed against source revision `3a2cf1c3` and
generated documentation for the core, Python extension, examples, and parity
adapter. `cargo package -p starlette-rs --list --locked` confirms the adapter
binary is included in the core crate file list; this list-only check did not
build an archive. `cargo package --locked -p starlette-rs` then succeeded on
`main@1014c90bc426dd94e27564c0f6f407d71ef0f147`; Cargo compiled the extracted
archive successfully. It contains 41 files, including `Cargo.lock`, README,
license/notice files, and the parity-adapter binary. Its compressed size is
240.4 KiB, and SHA-256 is
`ef6666e48737c6f5d4f2a686d1bed242973359d94b81d25ced1672eddbe3dcc4`. This
docs-only descendant has the same runtime source as parity candidate
`3c3dd0fd`; the archive is local, not uploaded, and the parity-adapter package
boundary remains unresolved. A local wheel was built from `main@6467976d` in
a fresh CPython 3.12 environment and the README install command (`pip install
. uvicorn`) succeeded. The macOS arm64 wheel is 2,030,162 bytes with SHA-256
`0479dd2968b36874b9f1fa66239ea6413c3a954ead9dbad6d8f15b7d002cf2ae`; its
contents include the compatibility package, `py.typed`, native extension,
license/notice files, and SBOM. The README app returned HTTP 200, imports came
from the fresh environment, no upstream `starlette` distribution was
installed, and `pip check` passed. This is one local wheel/install smoke only;
the interpreter/platform matrix, an sdist build, and registry consumer
verification remain open. Read-only registry checks on 2026-10-20 observed
HTTP 404 for the PyPI JSON endpoint and crates.io sparse-index key; the
crates.io API returned HTTP 403. These responses do not prove name
availability or reserve either name. No package, tag, GitHub Release, registry
credential, or documentation-site publication action has occurred.

### Historical preparation status (2026-10-19; superseded)

Release preparation is tracked by Kata parent `n5d2` and its Cargo (`z74v`),
PyPI (`2pan`), and documentation (`c4cy`) tasks. The active
`migration-parity/manifest@6` has 2,759 cases across 471 parity inputs, two
benchmark inputs, and 1,497 parity requirements; its SHA-256 is
`4f7048da1cf93e7c3392a91fc3937ba32d2af2aca70c71eaa23dcd609ae718ad`.
`make source-inventory-check` passes with zero fixture-backlog rows. Full
verification workflow [#22](https://github.com/appunni-m/starlette-rs/actions/runs/39271192252)
is queued on predecessor revision `6ed5b7e9` and does not include the current
Python parity-adapter relocation or manifest command update. Workflow #21
passed all five parity profiles on `2da349cf`; its five Python coverage
profiles are still measuring that older revision. Neither workflow provides
current-worktree parity or coverage evidence, no coverage union is proven,
and no final 74-workload benchmark is available. This is not a release
candidate.

### Replacement proof gates

Workspace-quality workflow
[`39271025302`](https://github.com/appunni-m/starlette-rs/actions/runs/39271025302)
ran for the `6ed5b7e9` checkpoint. The Python/style/docs job passed, while the
Rust 1.96.1 job failed on Clippy's `nonminimal_bool` lint in the parity
adapter. That boolean expression has been simplified, and local `make lint`
and `make docs-check` now pass. This does not replace a fresh hosted quality
run, distributable release-wheel builds, parity, coverage, or benchmark
evidence for the current source.

Full verification workflow
[`39199357775`](https://github.com/appunni-m/starlette-rs/actions/runs/39199357775)
ran against the earlier target `b508db19`. All five CPython 3.10–3.14 source
parity profiles passed 15,726/15,726 comparisons and 22/22 fault contracts.
Its six coverage-profile jobs completed, but the eligible-line union job
failed on path ordering. A diagnostic union over those receipts found
27,815/34,861 eligible lines (79.7883%), with 7,046 uncovered lines across
68 of 69 eligible paths. Those receipts target `b508db19`; they do not qualify
`07c5b333`, and the diagnostic is not a passing coverage gate.

Commit `07c5b333` fixes the union path ordering. Finish implementation first,
then run full parity and coverage against the resulting clean candidate. The
complete 74-workload benchmark has not been proven on the current tree. The project's release
sequence remains implementation, full parity, eligible-line coverage, then
benchmark. Until those gates pass on one reviewed source state, no release
candidate is qualified.

The active contract is `migration-parity/manifest@6`: 2,759 cases across 471
parity inputs and two benchmark inputs, 1,497 parity requirements, 157
compatibility operations, 867 source rows, and zero fixture-backlog rows.
These inventory counts do not establish full runtime parity, coverage, or
benchmark completion.

### Cargo

Cargo metadata on the current tree declares four workspace packages, all at
0.1.0; only `starlette-rs` is publishable. Its manifest declares edition 2024
and MSRV 1.85. The PyO3 distribution and two examples are `publish = false`.
`cargo package --list --locked -p starlette-rs` listed 41 files on the prior
checkpoint, including the README, Cargo.lock, license/notices, and internal
`starlette-rs-parity-adapter` binary; top-level `docs/` is omitted. This is a
package-file inventory only. Earlier archive and MSRV package verification
belong to older commits, not the current source. The binary's package scope
remains a release decision. The package-specific README is now selected by
`starlette-rs/Cargo.toml`; verify its navigation from the exact candidate
archive.

The release audit on clean checkpoint `0a660519` found no dirty tree. Its
`missing_readme` report is contradicted by the Cargo package list, which
contains `README.md`; treat this as a path-resolution false positive. The
repository has no Cargo publish workflow or workspace changelog, and no
explicit docs.rs metadata. Keep those as readiness work for the eventual
candidate. crates.io checks on 2026-10-19 were inconclusive (API HTTP 403;
sparse index HTTP 404); these responses do not prove name or version
availability. Recheck the exact name and version before any separately
authorized first upload.

### PyPI

The Python distribution is `starlette-rs-py` 0.1.0, with its version sourced
from the Cargo workspace and Maturin pinned to 1.14.1. Metadata declares
Python >=3.10, CPython 3.10–3.14, and runtime dependencies on AnyIO and
typing-extensions. The selected `starlette_rs_py` package previously included
the development parity adapter, which imports repository-only `scripts`
modules unavailable to a regular wheel consumer. The adapter has been moved
to `scripts/parity`, and the manifest now invokes it from the checkout.
Rebuild the sdist and wheels and inspect their contents before accepting this
correction. No PyPI release workflow is configured.

Ignored local artifacts are historical: one sdist and five macOS arm64 wheels,
with no source-commit provenance; the archived sdist lacks the configured
SBOM. There is no current-candidate Linux or Windows wheel evidence. PyPI JSON
and Simple API endpoints returned HTTP 404 for `starlette-rs-py` on
2026-10-19. A 404 does not reserve the name. Define and verify the supported
artifact matrix, build from a clean candidate sdist, inspect every artifact,
and test installation outside the checkout after the proof gates.

### Documentation

The documented surfaces are repository Markdown, the root README, and Rust
API documentation. No static documentation site or deployment workflow is
configured. Workflow `39211198588` passed `make docs-check` on `bd6820d5`,
including the 44-file Markdown link check; its benchmark-freshness subcheck
skipped an ignored result for an older manifest. `make rustdoc-check` passed
with warnings denied on Rust source commit `7c036b2f`; commit `9956ac01` changes
only parity fixtures/adapters and does not alter the Rust source. Local
`make docs-check`
passes its 44-file Markdown link check; its benchmark-freshness subcheck skips
the ignored result for an older manifest. The documentation inventory script
also traverses ignored virtual environments and reports installed-copy links;
those findings are not repository-documentation failures.

The new [documentation index](README.md) is linked from the root README and
routes readers to project status, API contracts, release evidence, license, and
security information. Recheck the README links as rendered from both the Cargo
package page and PyPI project page. Verify the final crate's rustdoc output and
license/notice links from the actual candidate artifacts. Documentation
hosting remains the repository source tree and, after an authorized Cargo
release, docs.rs; no site deployment is planned or configured in this
checkpoint.

### Release actions still open

1. Let baseline workflow #27 finish and retain its artifacts as diagnostics.
   Then let exact-runtime workflow #28 run on `e9f8b181` for diagnostics. Run
   the complete matrix on current `main` after #28 finishes so the lowercase
   RequestData input correction is included; repair mismatches together
   before advancing.
2. After the complete parity matrix passes, complete all six coverage profiles
   and prove the 100% eligible-line union on that same source revision.
3. Run the complete 74-workload benchmark only after parity and coverage pass.
   If runtime code or benchmark inputs change later, repeat parity, coverage,
   and benchmark in that order on the revised candidate.
4. Decide Cargo archive scope, resolve README/package navigation, and record
   release notes and version policy before freezing package metadata.
5. After package scope is settled, rebuild and inspect a clean candidate
   `.crate`, sdist, and the declared wheel/platform matrix; run fresh consumer
   installs and examples outside the checkout.
6. Verify docs and generated rustdoc from the exact candidate and recheck
   registry state. Add or configure a publication workflow only after its
   credentials, trusted publishers, permissions, and protected environments
   have been reviewed.

This checkpoint did not upload a package, create or move a tag, create a GitHub
Release, alter registry credentials, or deploy a documentation site.

## Historical preparation snapshot before main@8fd6ec4 (superseded)

The following release audit and package evidence was collected for older
commits. It remains useful background, but must be revalidated on a reviewed
candidate after parity, coverage, and benchmark gates pass.

Release preparation is active under Kata parent `n5d2` and its Cargo (`z74v`),
PyPI (`2pan`), and documentation (`c4cy`) children. The last pushed
implementation and input checkpoint is `main@c368e740b4976cbdda66c81433f56f399430cdfa`;
grouped parity corrections are now pushed in
`main@b711bc05ed798312c5b45cd940b4820160e7b6d3`. Full parity workflow
`39134336273` is active on that exact commit and has not produced result
artifacts yet. Neither checkpoint is a release candidate: the full project
gate remains implementation, full parity, coverage, then benchmark.

The active contract is `migration-parity/manifest@6`, parity inputs `@68`,
with manifest SHA-256
`ce7494a2cd99e2fbea7c98da3d60667460df3cc9674bcbadba54746c6b6aff2a`:
2,713 cases across 457 parity inputs and 1,479 requirements. Full verification
workflow `39130750285` ran all five CPython 3.10–3.14 source-to-target
profiles on this exact commit. CPython 3.10, 3.11, 3.13, and 3.14 each
completed with 3,113/3,116 comparisons passed, three comparison failures, two
oracle-side adapter errors, four comparisons not run, and all three fault
contracts passed. CPython 3.12 completed with 3,114/3,117 comparisons passed,
the same three comparison failures, two oracle-side adapter errors, four
comparisons not run, and all five fault contracts passed. Artifacts are 3.10 ID
`12137569403` (SHA-256
`5a1040572fb8a446d6ff11362285a08c81ca16a82efaed6483b06d935c922355`), 3.11
ID `12138481785` (SHA-256
`2487fca4aab485e2baa96c05acbe8a704641ddc5c06ce54ed086a297b1e885a9`), 3.12
ID `12138981672` (SHA-256
`e2a07113887feb8084cc19053300f803b9f553c6e5168cf458cb9569a647b5de`), and
3.13 ID `12138451688` (SHA-256
`afde69b60912c18e64f3ea1103087f8004ad95aaad3d21c66df7f0c144f3c827`). The
3.14 artifact is ID `12138941262` (SHA-256
`efcefda6b2b769af1d5c9401af18d2480056a971e99fb7bf7d7051acbac147f8`). The
shared comparison failures are the Rust-native FileResponse pre-epoch ETag
mismatch and two QueryParams cases where both sides return the same
`ValueError` but the comparator expects a success snapshot. The year-range
FileResponse cases also escape the oracle adapter as `ValueError`. In the
CPython 3.14 malformed-pair-too-long case, the pinned source reports
`too many values to unpack (expected 2, got 3)` while the target omits `got 3`;
this is an additional runtime mismatch. All five profiles failed, so coverage
was skipped. Current-source coverage and the final 74-workload benchmark have
not run.

The grouped correction in `b711bc05` reuses Python-style float formatting for native
FileResponse metadata, matches CPython 3.14's expanded tuple-unpack error text,
compares error partial values exactly without requiring success-only selector
fields, and captures FileResponse dispatch errors in the oracle observation.
Full five-profile requalification is running as workflow `39134336273`; its
results are pending.

Static checks on `b711bc05` pass: `make lint`,
`cargo +1.85.0 check --workspace --all-targets --all-features --locked`, and
`make contract-check PARITY_PYTHON=python3.12` (2,713 cases and 457 indexed
parity inputs). The current release-document edit also passes `make docs-check`
for 43 Markdown files.
Warnings-denied rustdoc passed on the preceding pushed checkpoint.
Warnings-denied core rustdoc also passes on the declared Rust 1.85.0 MSRV via
`RUSTDOCFLAGS="-D warnings" cargo +1.85.0 doc --locked -p starlette-rs
--no-deps`. These checks do not establish parity or release readiness.

The core `starlette-rs` crate packages and verifies on both Rust 1.96.1 and
1.85.0. Each archive has 40 files and is 230.5 KiB compressed. The 1.96.1
archive SHA-256 is
`5447c92766236281d87370174774b4d1feb1c282894708faf7f866141c9bb349`; the
1.85.0 archive SHA-256 is
`4c03bb4ae1b1272fa62b828392735b65c94f6aefbdc8930546ebb6ee18471dbb`. Both
include the README, BSD license and third-party notices; both include the
internal `starlette-rs-parity-adapter` binary and omit the top-level `docs/`
tree. Decide whether that internal binary belongs in the published core crate
before freezing a candidate. These are local package checks, not a published
or consumer-verified artifact.

Using the isolated build environment and Maturin 1.14.1 pinned by
`pyproject.toml`, `uv build --python python3.12` produced an sdist and a
CPython 3.12/macOS arm64 wheel built from that sdist. The 665,070-byte sdist
has SHA-256
`a94ec397ab723b19243d7e583ce3ae8aaa518d4546562fee2909492def27eb6a`; the
2,150,048-byte wheel has SHA-256
`9835c76af606464fb86ff5ee37afc5cdc4df824dde69487678f2f324f8e437d7`. Both
contain the facades, `py.typed`, native extension, license/notice files and
SBOM. Installing the wheel in a fresh CPython 3.12 environment outside the
checkout, with separately installed Uvicorn 0.54.0, served the documented
response (`HTTP 200`, `Hello from Starlette-RS`). This verifies one local
macOS wheel only; the full interpreter/platform matrix and registry consumer
install remain open.

Fresh registry lookups on 2026-10-18 found no `starlette-rs` result in
`cargo search`, no `starlette-rs@0.1.0` in the current crates.io index, and an
HTTP 404 from PyPI's project JSON endpoint for `starlette-rs-py`. Recheck both
registries immediately before any authorized first upload; these observations
do not reserve either name. The release audit also finds no publishing
workflow or workspace changelog. The audit's `missing_readme` finding is a
path-resolution false positive: the verified Cargo archives include the
declared root README.

No package was uploaded, tag or GitHub Release created, production registry
credential changed, or documentation site deployed. The repository still has
no configured static documentation site; repository Markdown and generated
Rust API docs are the current documentation surfaces.

The compatibility inventory now distinguishes the pinned plural GZip export
from an upstream proposed rename. The native-service documentation scopes its
pull and drop guarantee to the `NativeApplication` and body-polling boundary.
Root `SECURITY.md` asks reporters to use GitHub private reporting when the
repository offers it, and otherwise request a private contact without
technical details. Whether private reporting is enabled in repository
settings has not been verified or changed. A release-note/changelog policy
remains open.

## Historical evidence snapshot (through e9d4e7de)

Recorded on 2026-10-18 against clean, pushed
`main@e9d4e7de3caebd076526ada77dbc494dd321e57b`.
The active contract is `migration-parity/manifest@6`, its parity-input dataset
is revision `@68`, and the manifest SHA-256 is
`c627feeef5d21757821aad03db1436c9e2fce1e978e764c69daebc692de914a9`. The
checkpoint groups fixes for multipart truncation, reverse-route converter
errors, pre-epoch response dates, and malformed QueryParams adapter inputs. It
does not change the active manifest or authored parity inputs. This is
readiness evidence, not a release candidate.

- Workspace metadata declares both `starlette-rs` and `starlette-rs-py` as
  version `0.1.0`, Rust edition 2024, and MSRV 1.85. `rust-toolchain.toml`
  pins Rust 1.96.1. Two example packages and the internal PyO3 extension
  package declare `publish = false`; only the Rust core is intended for
  crates.io publication.
- The Python project pins Maturin 1.14.1, reads its version from Cargo
  metadata, declares Python `>=3.10`, and lists CPython 3.10–3.14 classifiers.
  These are metadata claims; the current release wheel matrix is unverified.
  The `Operating System :: OS Independent` classifier has been removed because
  the distribution includes a compiled extension.
- The active full-scope contract declares 2,713 cases across 457 parity inputs,
  156 compatibility operations, 17 Rust-native operations, and 1,479
  requirements. All 999 API-candidate rows are dispositioned. The source atlas
  has 867 rows: 811 input mappings, 56 source-backed `not_applicable` rows, and
  zero fixture backlog. The contract and source-inventory checks passed on
  `5053a4cc`; the grouped repair at `e9d4e7de` does not change inputs. On
  `e9d4e7de`, `cargo check --workspace --locked`, `make lint`, and
  `git diff --check` passed before push. Full parity is running as Actions
  workflow `39126044018` on the exact commit. Its latest status is recorded
  below; the run is not a final proof because this worktree has since changed.
  Coverage is gated on parity; current-source coverage and the final
  74-workload benchmark have not been measured.
- Historical Actions run `39122567844` on `5053a4cc` failed all five CPython
  profiles with 14 mismatches and four adapter/infrastructure errors per
  profile. The grouped repair is being checked by `39126044018`; no parity pass
  is claimed yet. Earlier Actions run `39111029407` on `284f3138` reported
  15,026/15,026 comparisons and 17/17 fault contracts. Its later coverage jobs
  included four CPython 3.14 cookie-owned-callback lifetime comparison
  failures. These older results do not establish current parity or 100%
  coverage.
- The release audit found no Cargo publish workflow. No release tag was present
  at the audited revision. The workspace has no `CHANGELOG` or `SECURITY.md`,
  and no documentation-site workflow is configured. Add release automation
  only after the package set and verification matrix are settled.
- During this refresh, crates.io API requests returned HTTP 403 from the
  current environment, so registry availability for `starlette-rs` and
  `starlette-rs-py` remains unknown. The PyPI JSON endpoint returned HTTP 404
  for `starlette-rs-py`; this does not reserve the name. Recheck exact ownership
  and version availability before an authorized first upload.
- `cargo package --list --locked -p starlette-rs` and
  `cargo package --list --locked -p starlette-rs-py` were used only to inspect
  file lists. Both packages include the root README, so the release-audit
  script's `missing_readme` findings are path-resolution false positives. The
  core package includes `LICENSE.md`, third-party notices, and
  `src/bin/starlette-rs-parity-adapter.rs`, but omits the top-level `docs/`
  directory. The `starlette-rs-py` Cargo package contains the Python facade,
  `py.typed`, and extension sources but no license/notice files. The PyPI
  project metadata names license files. An earlier local CPython 3.12 macOS
  arm64 build from the working tree produced a `starlette-rs-py-0.1.0` wheel
  (2,198,115
  bytes, SHA-256
  `0f82bffdc7231a57425602396b6b0fa594dcfb36e570d5569b742dedec1345fa`). Its
  inspected contents include the `starlette.*` facade, `py.typed`, the native
  extension, and all three declared license/notice files. The source-install
  quickstart passed in a controlled CPython 3.12 environment: the documented
  Uvicorn server returned HTTP 200 with `Hello from Starlette-RS` and shut down
  cleanly. This is historical pre-`e9d4e7de` evidence and proves one local
  checkout-to-wheel path only; the sdist, other supported
  interpreter/OS/architecture combinations, and registry consumer installation
  remain unverified. No `.crate` archive was built. The planned Cargo release
  scope excludes the extension crate; inspect the core archive again on the
  clean release candidate and decide whether its parity-adapter binary belongs
  there.
- The third-party notice files now point to repository-only source, fixture,
  and documentation paths through commit-pinned GitHub URLs. Their remaining
  local license links resolve in both Cargo and wheel archives. The generated
  CPython 3.12 wheel's notice entries were checked; the documentation audit's
  remaining installed-license link findings come from the older ignored
  `.venv-router` environment, not these source notice files.
- The release audit reports no publish workflow and no workspace changelog.
  Its structural findings do not make the project ready to release. The
  documentation audit also traverses the ignored local `.venv-router` and
  reports links from installed license metadata as repository link errors;
  those findings must be separated from the checked-in documentation. The last
  repository-native `make docs-check` passed the 43-file Markdown link check
  after this refresh. Its benchmark freshness step skipped the ignored local
  result because it targets an older manifest; refresh benchmark evidence only
  after the full parity and coverage phases.
- The worktree was clean at the recorded checkpoint, but release candidates
  are not built and implementation, parity, coverage, and benchmark gates are
  not all complete. Workflow `39126044018` later completed with all five
  parity profiles failing; it is historical evidence and does not satisfy the
  current phase.
- The README has a Python installation and first-app path. Its documented
  `python -m pip install . uvicorn` command and app were exercised in the local
  CPython 3.12 environment described above, before `e9d4e7de`. Documentation
  review still needs to address the broad claim in `docs/native-service.md`, generated Rust
  API-doc review, and package-local checks for Cargo archives. The Python
  wheel's license-notice links were inspected; the Markdown docs-check covers
  repository links, not links inside Cargo archives.

The evidence above is a dated snapshot. Recheck every item against the exact
clean candidate commit before release.

## Historical release check before c368e740 (2026-10-18)

This checkpoint is superseded by the latest preparation status above.

The release-preparation worktree currently contains uncommitted parity
implementation changes, so it is not a release candidate. The release audit
reports the dirty tree and two `missing_readme` findings. The latter are known
audit-script path-resolution false positives: both manifests point to the root
README, and the prior clean-checkpoint `cargo package --list` output included
it. Current `cargo package --list --locked` attempts stopped on Cargo's dirty
worktree guard; no `--allow-dirty` override was used and no package archive was
built.

Full parity workflow `39126044018` is running against the older runtime commit
`e9d4e7de3caebd076526ada77dbc494dd321e57b`. All five CPython jobs have failed
and the coverage jobs were skipped. The available artifacts belong to the
failed parity jobs. This run cannot prove the current uncommitted implementation,
and full parity remains a release prerequisite.

The fresh documentation inventory also scanned the ignored `.venv-router`
environment and reported three installed third-party-notice links as missing
repository files. The repository-native Markdown check remains the relevant
link gate and must be rerun on the clean candidate. Findings from that
superseded snapshot included missing security guidance and service-boundary
wording; later changes added `SECURITY.md`, removed the inventory placeholder,
and scoped the native-service pull/drop statement to its documented boundary.
Registry state is still unverified: the crates.io API
request was unavailable from this host, and a PyPI 404 does not reserve the
name. No package, tag, GitHub Release, or documentation deployment has been
created.

As a preparation safeguard, `starlette-rs-py/Cargo.toml` now sets
`publish = false`. `cargo metadata --locked --no-deps --format-version 1`
confirms that only the core crate is publishable in Cargo metadata. The
repository-native `make docs-check` passes its 43-file Markdown link check;
its benchmark-freshness subcheck skips the ignored result for the old manifest,
so that artifact remains historical. `git diff --check` also passes. These
checks do not replace the candidate release gates.

## Distribution surfaces

| Surface | Version and destination | Current state |
| --- | --- | --- |
| Rust core crate `starlette-rs` | Workspace version `0.1.0`; intended registry is crates.io | Only publishable workspace package. Package-list inspection includes the parity adapter; exact-candidate archive, downstream consumer check, and registry qualification remain open. |
| PyO3 extension crate `starlette-rs-py` | Workspace version `0.1.0`; local build component for PyPI | `publish = false`; not intended as a separate Cargo release. |
| Python distribution `starlette-rs-py` | Maturin reads the Cargo version; intended registry is PyPI | Version `0.1.0` declared. Python `>=3.10` is declared, while classifiers cover 3.10–3.14. Exact-candidate artifacts and the platform matrix are unverified; no publishing workflow exists. |
| Documentation | Repository Markdown and Rust API docs | No static-site deployment is configured. Exact-candidate rustdoc and artifact README rendering remain to be verified. |

The planned distribution scope is the Rust-native `starlette-rs` crate on
crates.io and the `starlette-rs-py` distribution on PyPI. The PyO3 extension
crate is a local build component for the Python distribution. Example
workspace packages are not release candidates.

The documentation audit found no consolidated, human-readable reference for
the supported `starlette.*` compatibility surface. The generated inventory is
internal review evidence, not a substitute for an end-user API reference; add
and verify that reference before calling documentation release-ready.

## Release gates

Finish these gates on one reviewed source candidate. Track them in Kata parent
`n5d2` and its Cargo (`z74v`), PyPI (`2pan`), and documentation (`c4cy`)
children. The project sequence is implementation and input authoring, full
parity, coverage, then benchmark.

1. **Finish implementation and inputs.** Complete the remaining feature
   families and author input-only source comparisons. Keep Python runtime
   facades thin and preserve the pinned Starlette 1.6.0 authority.
2. **Prove full parity.** Run all five CPython 3.10–3.14 source profiles and
   fault-contract cases on the candidate. Resolve mismatches together. Do not
   treat a passing slice as full parity. Workflow #27 is an older baseline;
   workflow #28 is queued for runtime candidate `e9f8b181`.
3. **Prove eligible-line coverage.** After parity passes, complete all six
   managed profiles and the receipt-bound source-line union at 100% eligible
   lines on the same source state.
4. **Measure the full benchmark workload.** Run after coverage on that
   reviewed source state. If runtime code or benchmark inputs change later,
   repeat parity, coverage, and benchmark in that order.
5. **Freeze release identity.** Choose the version, package set, registry, tag
   convention, pre-1.0 compatibility statement, and curated release notes.
   Keep workspace metadata, Python's dynamic version, lock data, and tag
   assertions aligned. Check registry state again before a first upload.
6. **Qualify Cargo artifacts.** Inspect the exact `.crate` file list and
   archive, resolve the parity-adapter and `fault-contract` feature scope,
   verify Rust 1.85 and advertised features, generate warnings-denied rustdoc,
   and install the archive in a clean downstream consumer.
7. **Qualify Python artifacts.** Resolve the supported Python upper bound or
   extend qualification. Build an sdist and wheels from the clean candidate;
   inspect all artifacts for facades, `py.typed`, extension, licenses, notices,
   and SBOM. Install each artifact outside the checkout and verify a minimal
   application path across the declared OS, architecture, and Python matrix.
8. **Verify documentation for the same candidate.** Run `make docs-check`,
   `make source-inventory-check`, and `make rustdoc-check`; inspect the
   generated rustdoc and the Cargo/PyPI package READMEs from built artifacts.
   Keep every compatibility, coverage, benchmark, and support claim revision-
   bound. Decide whether a separate documentation site is needed.
9. **Review publication controls.** Add or configure publishing automation
   only after package scope and proof gates settle. Use minimal job permissions
   and protected registry environments; never expose publishing credentials
   to pull-request code. Publishing, tagging, GitHub Releases, credential
   changes, and documentation deployment each require separate authorization.

No Cargo or PyPI upload, release tag, GitHub Release, production registry
credential change, or documentation deployment has been performed as part of
this preparation.

## Publication controls

The current release workflow does not upload packages or publish a docs site.
For a first PyPI release, use PyPI's Trusted Publishing project-creation flow
if available: its pending publisher does not reserve the project name, so
recheck the name immediately before the first publish. Configure the exact
GitHub repository, release workflow, and protected environment. If manual
bootstrap is required, handle a short-lived credential outside this
repository. Prefer Trusted Publishing for later releases. Keep registry
credentials out of source, logs, build artifacts, and Kata.

Before a first PyPI upload, revalidate the README installation and
first-application path against clean release artifacts and all supported
Python versions. Earlier local records cover one sdist and one CPython
3.12/macOS arm64 wheel built from it, followed by a fresh wheel install and
ASGI smoke check. Those artifacts predate runtime candidate `e9f8b181`; they
are not current-candidate evidence or a complete wheel matrix or registry
consumer check.

No Cargo/PyPI upload, release tag, GitHub Release, production registry
credential change, or documentation deployment has been performed as part of
this preparation.

## Primary references

- [Cargo publishing](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [Cargo package command](https://doc.rust-lang.org/cargo/commands/cargo-package.html)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [Creating a PyPI project through Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [PyPI Trusted Publisher security model](https://docs.pypi.org/trusted-publishers/security-model/)
