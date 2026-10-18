# Release readiness

This document tracks the non-publishing release path for the Rust crate, the
Python distribution, and their documentation. A published crate version is
permanent, and Python uploads are public releases. Nothing here authorizes a
package upload, tag, GitHub Release, or change to registry credentials.

## Current evidence snapshot

Recorded on 2026-10-18 against the pushed runtime checkpoint `a9c857b0` at
`main`; the active contract is `parity-input@68` with manifest SHA-256
`c627feeef5d21757821aad03db1436c9e2fce1e978e764c69daebc692de914a9`. The
documentation and evidence-checker edits accompanying this snapshot are
preparation work, not a release candidate.

- Workspace metadata declares both `starlette-rs` and `starlette-rs-py` as
  version `0.1.0`, Rust edition 2024, and MSRV 1.85. `rust-toolchain.toml`
  pins Rust 1.96.1. Two example packages declare `publish = []`.
- The Python project pins Maturin 1.14.1, reads its version from Cargo
  metadata, declares Python `>=3.10`, and lists CPython 3.10–3.14 classifiers.
  These are metadata claims; the current release wheel matrix is unverified.
  The `Operating System :: OS Independent` classifier has been removed because
  the distribution includes a compiled extension.
- The active @68 contract now declares 2,704 cases across 457 parity inputs, 156
  compatibility operations, 17 Rust-native operations, and 1,479 requirements.
  Contract, source-inventory, project-policy, lint, formatting, compile, and
  Clippy checks passed on `a9c857b0`. The current full parity matrix, eligible
  coverage union, and final 74-workload benchmark have not run on this
  checkpoint.
- Historical Actions run `39111029407` on `284f3138` reported 15,026/15,026
  comparisons and 17/17 fault contracts. Its later coverage jobs included four
  CPython 3.14 cookie-owned-callback lifetime comparison failures. These
  results predate @68 and do not establish current parity or 100% coverage.
- The release audit found no Cargo publish workflow. The remote tag query
  returned no tags. The workspace has no `CHANGELOG` or `SECURITY.md`, and no
  documentation-site workflow is configured. Add release automation only
  after the package set and verification matrix are settled.
- A prior crates.io lookup returned HTTP 404 for `starlette-rs`, and a prior
  PyPI lookup returned HTTP 404 for `starlette-rs-py`. These checks do not
  reserve either name; recheck exact ownership and version availability before
  an authorized first upload.
- `cargo package --list --locked --allow-dirty` was used only to inspect file
  lists. Both packages include the root README, so the release-audit script's
  `missing_readme` findings are path-resolution false positives. The core
  package also includes `LICENSE.md` and
  `src/bin/starlette-rs-parity-adapter.rs`, but omits the top-level `docs/`
  directory. The `starlette-rs-py` Cargo package contains the Python facade,
  `py.typed`, and extension sources but no license/notice files. No `.crate`
  archive was built; the extension crate's license contents and the core
  adapter's inclusion still require decisions.
- The source snapshot is not ready for packaging: implementation is active,
  the worktree was dirty during the audit, and no release candidate was built.
  `make docs-check` now passes the 43-file Markdown link check. Its benchmark
  evidence freshness step skips the ignored local result because it targets an
  older manifest; the checked-in benchmark remains explicitly historical.
  Refresh benchmark evidence only after the full parity and coverage phases.
- Documentation review still needs a Python installation and first-app path in
  the README, a review of the broad claim in `docs/native-service.md`, and
  package-local link checks for the actual archives. The Markdown docs-check
  covers repository links, not links inside Cargo archives.

The evidence above is a dated snapshot. Recheck every item against the exact
clean candidate commit before release.

## Distribution surfaces

| Surface | Version and destination | Current state |
| --- | --- | --- |
| Rust core crate `starlette-rs` | Cargo workspace version; intended registry is crates.io | `0.1.0` declared; registry state unknown. The package inventory includes the parity-adapter binary, so its inclusion must be explicitly reviewed. |
| PyO3 extension crate `starlette-rs-py` | Cargo workspace version; required to build the Python package | `0.1.0` declared and depends on the local `starlette-rs` path crate. Decide whether it is a public crates.io package or only a source-build component before designing the Cargo release order. |
| Python distribution `starlette-rs-py` | Maturin reads the Cargo package version; destination is PyPI | `0.1.0` declared. No public PyPI project was found by the JSON endpoint at the snapshot date; project-name availability and trusted-publisher setup are unverified. Runtime dependencies declared in `pyproject.toml` are AnyIO and typing-extensions. |
| Documentation | Repository Markdown and Rust API docs | Markdown is currently hosted in the Git repository. There is no configured static documentation site. A hosted API-docs route and any separate website must be checked and chosen before promising them to users. |

The release scope is intentionally not inferred from the workspace membership.
Before the first Cargo upload, decide whether Cargo publishes only
`starlette-rs` or also `starlette-rs-py`. If both are published, publish and
verify the core crate first because the extension crate has a versioned path
dependency on it. Example workspace packages declare `publish = []` and are
not release candidates.

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

Before the first PyPI upload, add and validate a Python installation and
first-application path in the README. The current README is centered on the
Rust-native APIs and its example command requires a clone of the whole
workspace; it is not yet a sufficient PyPI landing page. The command is now
labelled as a workspace example, but that does not substitute for the Python
consumer journey.

No Cargo/PyPI upload, release tag, GitHub Release, production registry
credential change, or documentation deployment has been performed as part of
this preparation.

## Primary references

- [Cargo publishing](https://doc.rust-lang.org/cargo/reference/publishing.html)
- [Cargo package command](https://doc.rust-lang.org/cargo/commands/cargo-package.html)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [Creating a PyPI project through Trusted Publishing](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
- [PyPI Trusted Publisher security model](https://docs.pypi.org/trusted-publishers/security-model/)
