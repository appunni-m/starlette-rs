# Release readiness

This document tracks the non-publishing release path for the Rust crate, the
Python distribution, and their documentation. A published crate version is
permanent, and Python uploads are public releases. Nothing here authorizes a
package upload, tag, GitHub Release, or change to registry credentials.

## Latest preparation status (2026-10-19)

Release preparation is tracked by Kata parent `n5d2` and its Cargo (`z74v`),
PyPI (`2pan`), and documentation (`c4cy`) tasks. The evidence below covers the
current clean checkpoint `bd6820d594831b01eaef8b07a51040345609fced` on
`codex/c5j3-focused-coverage`; its runtime source follows the verifier fix in
`07c5b333`. A local Cargo archive was built and verified on this checkpoint,
but full parity, coverage, and benchmark evidence is not bound to it. This is
not a release candidate.

### Replacement proof gates

Workspace-quality workflow
[`39211198588`](https://github.com/appunni-m/starlette-rs/actions/runs/39211198588)
passed on this exact checkpoint. All nine jobs passed: Rust 1.85.0 and 1.96.1,
CPython 3.10–3.14 editable-install/import checks, Python style/documentation,
and Rust dependency security/license policy. The Python matrix does not build
release wheels, and this workflow is not the full parity, coverage, benchmark,
or release-artifact workflow. Superseded runs `39210810283` and `39210733546`
were cancelled by the branch concurrency policy.

Full verification workflow
[`39199357775`](https://github.com/appunni-m/starlette-rs/actions/runs/39199357775)
ran against the earlier target `b508db19`. All five CPython 3.10–3.14 source
parity profiles passed 15,726/15,726 comparisons and 22/22 fault contracts.
Its six coverage-profile jobs completed, but the eligible-line union job
failed on path ordering. A diagnostic union over those receipts found
27,815/34,861 eligible lines (79.7883%), with 7,046 uncovered lines across
68 of 69 eligible paths. Those receipts target `b508db19`; they do not qualify
`07c5b333`, and the diagnostic is not a passing coverage gate.

Commit `07c5b333` fixes the union path ordering. The full parity and coverage
workflow must be rerun on this exact source tree. The complete 74-workload
benchmark has not been proven on the current tree. The project's release
sequence remains implementation, full parity, eligible-line coverage, then
benchmark. Until those gates pass on one reviewed source state, no release
candidate is qualified.

The active contract is `migration-parity/manifest@6`, SHA-256
`6e60640f9f8a7919ea500398aaace0942f5edf707fb92e6659307eb0dd561984`: 2,729
cases across 461 parity inputs and two benchmark inputs, 1,485 mapped source
requirements, 867 compatibility-atlas rows, and zero fixture backlog. These
inventory counts do not establish full runtime parity, coverage, or benchmark
completion.

### Cargo

Cargo metadata declares `starlette-rs` 0.1.0, edition 2024, and MSRV 1.85 as
the only publishable workspace package. The PyO3 extension and two examples
are `publish = false`. On the clean checkpoint, `cargo package --locked -p
starlette-rs` passed with Cargo 1.96.1, and `cargo +1.85.0 package --locked -p
starlette-rs` passed with the declared MSRV. Cargo produced a 41-file archive
(about 1.3 MiB unpacked, 236 KiB compressed); the MSRV-generated local archive
SHA-256 is
`9842a02b071b16d4503783b73c20d96c256fcc800a475b073239666cda29fc85`. It is
under ignored `target/package/` and is not a release artifact. The inventory
still includes the internal `starlette-rs-parity-adapter` binary and omits
top-level `docs/`, which the README links to. Resolve that package scope and
the registry-rendered README links before freezing a candidate.

The strict static release audit reports the README path as missing, but the
Cargo inventory and archive contain `README.md`; this is a path-resolution
false positive. It also confirms that no Cargo publish workflow or workspace
changelog is configured. No explicit docs.rs metadata is present. crates.io
checks on 2026-10-19 were inconclusive (API HTTP 403; sparse index HTTP 404);
these responses do not prove name or version availability. Recheck the exact
name and version immediately before a separately authorized first upload.

### PyPI

The Python distribution is `starlette-rs-py` 0.1.0, with its version sourced
from the Cargo workspace and Maturin pinned to 1.14.1. Metadata declares
Python >=3.10, CPython 3.10–3.14, and runtime dependencies on AnyIO and
typing-extensions. Workflow `39211198588` passed the editable-install/import
checks for all five CPython versions; these do not verify built release wheels.
No PyPI release workflow is configured.

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
configured. Workflow `39211198588` passed `make docs-check` on this checkpoint,
including the 44-file Markdown link check; its benchmark-freshness subcheck
skipped an ignored result for an older manifest. `make rustdoc-check` passed
with warnings denied on source commit `07c5b333`. The broad inventory
script also traverses ignored virtual environments and reports installed-copy
links; those findings are not repository-documentation failures.

The new [documentation index](README.md) is linked from the root README and
routes readers to project status, API contracts, release evidence, license, and
security information. Recheck the README links as rendered from both the Cargo
package page and PyPI project page. Verify the final crate's rustdoc output and
license/notice links from the actual candidate artifacts. Documentation
hosting remains the repository source tree and, after an authorized Cargo
release, docs.rs; no site deployment is planned or configured in this
checkpoint.

### Release actions still open

1. Run full parity and the receipt-bound coverage union on `07c5b333` after the
   coverage fix; close any resulting mismatches before proceeding.
2. Run the complete 74-workload benchmark only after the current-tree coverage
   gate passes.
3. Decide Cargo archive scope, resolve README/package navigation, and record
   release notes and version policy before freezing package metadata.
4. After package scope is settled, rebuild and inspect a clean candidate
   `.crate`, sdist, and the declared wheel/platform matrix; run fresh consumer
   installs and examples outside the checkout.
5. Verify docs and generated rustdoc from the exact candidate and recheck
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
| Rust core crate `starlette-rs` | Cargo workspace version; intended registry is crates.io | `0.1.0` package archives verify on Rust 1.85.0 and 1.96.1 (40 files; 230.5 KiB compressed). Both include the internal parity adapter and omit top-level docs. Exact `0.1.0` was absent from the current crates.io index; recheck before upload. No publication. |
| PyO3 extension crate `starlette-rs-py` | Cargo workspace version; required to build the Python package | PyPI build component, not a standalone Cargo release. Its manifest sets `publish = false`, confirmed by current Cargo metadata. The crate depends on the local `starlette-rs` path crate. |
| Python distribution `starlette-rs-py` | Maturin reads the Cargo package version; destination is PyPI | `0.1.0` declared. Current sdist and one CPython 3.12/macOS arm64 wheel were built; the wheel was installed in a fresh environment and served the README app through separate Uvicorn. Other Python/platform wheel targets, Trusted Publisher setup, and registry consumer install remain unverified. PyPI JSON returned 404 at the latest check; recheck before upload. Runtime dependencies declared in `pyproject.toml` are AnyIO and typing-extensions. |
| Documentation | Repository Markdown and Rust API docs | Markdown is currently hosted in the Git repository. There is no configured static documentation site. A hosted API-docs route and any separate website must be checked and chosen before promising them to users. |

The planned release scope is the Rust-native `starlette-rs` crate on crates.io
and the `starlette-rs-py` distribution on PyPI. The PyO3 extension crate is a
local build component for the Python distribution and is not planned as a
separate Cargo release. Its manifest sets `publish = false`. Example workspace
packages are also not release candidates.

## Release gates

Complete these gates in order on one reviewed, clean commit. Track execution in
Kata parent `n5d2` and its Cargo (`z74v`), PyPI (`2pan`), and documentation
(`c4cy`) children.

1. **Finish the project contract.** Complete the active implementation and
   coverage work recorded under the Starlette-RS parent goal. Confirm that the
   completed benchmark and full replacement/parity evidence identify the final
   source commit; if source changes after those runs, refresh them once the
   implementation batch is frozen. Establish the coverage union from reports
   measured against that exact source. Do not describe a passing slice as full
   parity.
2. **Freeze release identity.** Choose the exact version, package set, registry,
   tag convention, and pre-1.0 compatibility statement. Keep root workspace
   metadata, internal dependency requirements, Python's dynamic version, lock
   data, a curated changelog entry, and tag assertions aligned. Check registry
   status again before choosing a first upload version.
3. **Prove Cargo artifacts.** From the clean candidate commit, inspect
   `cargo package --list --locked` for each selected crate, then run
   `cargo package --locked`. Inspect the generated archives and normalized
   manifests. Decide explicitly whether the parity adapter belongs in the
   `starlette-rs` archive. Check exact MSRV 1.85, default and advertised feature
   combinations, warnings-denied rustdoc, license/notice files, and a clean
   downstream consumer. Never package or publish a dirty worktree.
4. **Prove Python artifacts.** Build the source distribution and wheels from
   the clean candidate using the pinned Maturin version. Define and run the
   operating-system, architecture, and Python-version matrix before claiming
   wheel availability. Inspect the sdist and each wheel for the `starlette.*`
   facades, `py.typed`, native extension, licenses, notices, and SBOM. Install
   the exact built artifacts in fresh environments outside the checkout and
   verify the public import and minimal application path.
5. **Publish documentation for the same version.** Run `make rustdoc-check`,
   `make docs-check`, and `make source-inventory-check`; inspect generated
   rustdoc and the included README/license/notice files. Keep repository
   Markdown claims scoped to the verified compatibility, platform, benchmark,
   and coverage evidence. Choose a separate static-site host only if one is
   required; none is configured today.
6. **Require hosted evidence before publishing.** Add or review a release
   workflow only after the package matrix is known. Validation jobs must have
   read-only permissions. Isolate each registry upload in a distinct job and
   protected environment, with the minimum identity permissions; never expose
   publishing credentials to pull-request code. Verify the exact tag and
   version and retain artifact checksums and build evidence.
7. **Verify as a consumer.** After an authorized upload, query the exact
   registry version, install it in a fresh environment, build/read its docs,
   and verify that registry artifact, tag, source commit, notes, and provenance
   identify the same release. Treat published Cargo versions as immutable.

The final project gate should use repository-native commands, including
`make ci`, `make coverage-union`, and the complete benchmark workflow, once the
current implementation phase allows those full runs. Narrow package and docs
checks can run during preparation, but they cannot replace the final gates.

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
Python versions. Current evidence covers one locally built sdist and one
CPython 3.12/macOS arm64 wheel built from it, followed by a fresh local wheel
install and ASGI smoke check. It is not a complete wheel matrix or registry
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
