# Release readiness

This document tracks the non-publishing release path for the Rust crate, the
Python distribution, and their documentation. A published crate version is
permanent, and Python uploads are public releases. Nothing here authorizes a
package upload, tag, GitHub Release, or change to registry credentials.

## Current evidence snapshot

Recorded on 2026-10-18 from `main` at `284f31383fa78b78ac3609f293ff3bb0ed48613b`:

- The package manifests declare version `0.1.0`. The Cargo workspace declares
  Rust edition 2024 and MSRV 1.85; `rust-toolchain.toml` pins Rust 1.96.1.
- The Python project uses Maturin 1.14.1, reads its version dynamically from
  Cargo metadata, declares Python `>=3.10`, and lists CPython 3.10–3.14
  classifiers. The classifiers are declarations; the release wheel matrix has
  not been proven. The working tree removes the `Operating System :: OS
  Independent` classifier because the package includes a compiled extension.
- GitHub Actions run `39111029407` passed the five CPython parity jobs at this
  commit. The artifacts report 15,026/15,026 comparisons and 17/17 fault
  contracts. This is evidence for that revision and those lanes, not proof of
  full Starlette replacement.
- In the same run, five coverage jobs completed and the CPython 3.14 coverage
  job reported four cookie-owned-callback lifetime mismatches. A local Python
  boundary fix is present in the dirty worktree but has not been re-verified.
  The downloaded coverage reports are from a different source state and are
  marked source-unverified; they do not establish a 100% coverage result.
- The worktree contains active parity, coverage, and release-documentation
  changes. It is not a release source tree. No release tags were found on
  `origin`, and no package-publishing or documentation-site workflow is
  present.
- A crates.io API query with an identifying User-Agent returned HTTP 404 for
  `starlette-rs`, and `cargo info starlette-rs@0.1.0` found no published
  version. Recheck name ownership immediately before release; 404 is not a
  reservation. PyPI returned HTTP 404 for `starlette-rs-py` on this date; this
  also does not guarantee future name availability.
- `cargo package --list --locked --allow-dirty` was used only to inspect the
  current package file lists. Both include the root README. The core crate list
  includes license/notice files and
  `src/bin/starlette-rs-parity-adapter.rs`; its top-level `docs/` directory is
  absent even though the shared README and notice files link into it. The
  `starlette-rs-py` Cargo package list contains the Python facade and extension
  sources but no license/notice files; decide whether this crate is publishable
  and add required notices if so. No `.crate` archive was built from this dirty
  tree. Inspect link rendering from the actual crate and Python pages or point
  package links to a versioned source location.
- `make docs-check` passed local Markdown links for 43 files, then failed its
  benchmark-evidence check because the upstream benchmark result manifest
  digest differs from the active manifest. Refresh benchmark evidence only
  after implementation inputs are frozen. The documentation inventory also
  found no `SECURITY.md`, a `TODO` in the compatibility inventory, and a
  broad-claim review item in `docs/native-service.md`; review these before
  presenting public docs. It found no workspace changelog, so add curated notes
  after the release version and included surfaces are chosen. The inventory's
  broken-link count mixes local virtual-environment copies and package-local
  notice files; it is not a count of broken links in the root documentation.

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
