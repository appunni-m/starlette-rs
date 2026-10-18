# Release readiness

This document tracks the non-publishing release path for the Rust crate, the
Python distribution, and their documentation. A published crate version is
permanent, and Python uploads are public releases. Nothing here authorizes a
package upload, tag, GitHub Release, or change to registry credentials.

## Latest preparation status (2026-10-18)

Release preparation is active under Kata parent `n5d2` and its Cargo (`z74v`),
PyPI (`2pan`), and documentation (`c4cy`) children. The source worktree is
dirty at `main@3f0a864035cda33c751f2d9bf9f482ac32526e56` with implementation
and input-only parity changes at the time of this snapshot. This is not a
release candidate. The project gate remains implementation, full parity,
coverage, then benchmark; no release artifact should be built from this
intermediate state.

The current contract is `migration-parity/manifest@6`, parity inputs `@68`,
with manifest SHA-256
`ce7494a2cd99e2fbea7c98da3d60667460df3cc9674bcbadba54746c6b6aff2a`:
2,713 cases across 457 parity inputs and 1,479 requirements. The prior full
Actions run `39126044018` has now failed all five CPython profiles on the older
`e9d4e7de` runtime commit; both coverage jobs were skipped. It does not test
the current changes and does not establish parity.

On the current worktree, `make docs-check` passed the repository link check
for 43 Markdown files. Its benchmark-freshness check skipped the ignored
result for the older manifest. `make rustdoc-check` passed with warnings
denied. `make lint`, including Rust API boundary, Python formatting/lint,
project policy, and workflow checks, passed. `cargo metadata --locked
--no-deps --format-version 1` confirms
`starlette-rs` is the only publishable workspace package. The extension crate
and example packages are marked `publish = false`. These are preparation
checks, not release-candidate evidence.

The release audit reports a dirty-worktree error, no release workflow, and no
workspace changelog. Its two `missing_readme` findings are path-resolution
false positives: prior `cargo package --list` output included the README for
both declared package paths. The documentation inventory also scans ignored
`.venv-router` license metadata and reports its repository-relative links as
missing files; those are not checked-in docs. Remaining documentation work
includes a security-reporting route, a compatibility-inventory TODO, and
evidence/scope review for the `guaranteed` claim in `docs/native-service.md`.

Registry ownership and version availability are still unverified. The
previous crates.io request was unavailable and a PyPI 404 does not reserve a
name. No `.crate`, sdist, or wheel was built from the current source; no
package was uploaded, tag or GitHub Release created, or documentation site
deployed. Recheck registry status immediately before any separately authorized
publication.

## Current evidence snapshot

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
  not all complete. Workflow `39126044018` remains in progress at the latest
  status read; wait for its terminal result before reporting phase advancement.
- The README has a Python installation and first-app path. Its documented
  `python -m pip install . uvicorn` command and app were exercised in the local
  CPython 3.12 environment described above, before `e9d4e7de`. Documentation
  review still needs to address the broad claim in `docs/native-service.md`, generated Rust
  API-doc review, and package-local checks for Cargo archives. The Python
  wheel's license-notice links were inspected; the Markdown docs-check covers
  repository links, not links inside Cargo archives.

The evidence above is a dated snapshot. Recheck every item against the exact
clean candidate commit before release.

## Fresh release check (2026-10-18)

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
link gate and must be rerun on the clean candidate. The audit still flags the
missing root `SECURITY.md`, a `TODO` in the compatibility inventory, and the
scope of the `guaranteed` claim in `docs/native-service.md`; these remain
documentation work. Registry state is still unverified: the crates.io API
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
| Rust core crate `starlette-rs` | Cargo workspace version; intended registry is crates.io | Planned public Cargo artifact at `0.1.0`; current registry state is unknown. Review whether the internal parity-adapter binary belongs in its archive. |
| PyO3 extension crate `starlette-rs-py` | Cargo workspace version; required to build the Python package | PyPI build component, not a standalone Cargo release. Its manifest sets `publish = false`, confirmed by current Cargo metadata. The crate depends on the local `starlette-rs` path crate. |
| Python distribution `starlette-rs-py` | Maturin reads the Cargo package version; destination is PyPI | `0.1.0` declared. One earlier local CPython 3.12 macOS arm64 wheel was built and smoke-checked from source; sdist and other wheel targets remain unverified. The current JSON endpoint returned 404; this does not establish name availability. Trusted Publisher setup is unverified. Runtime dependencies declared in `pyproject.toml` are AnyIO and typing-extensions. |
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
Python versions. Current evidence covers only one local CPython 3.12
checkout-built wheel and is not a registry consumer check.

No Cargo/PyPI upload, release tag, GitHub Release, production registry
credential change, or documentation deployment has been performed as part of
this preparation.

## Primary references

- [Cargo publishing](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [Cargo package command](https://doc.rust-lang.org/cargo/commands/cargo-package.html)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [Creating a PyPI project through Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [PyPI Trusted Publisher security model](https://docs.pypi.org/trusted-publishers/security-model/)
