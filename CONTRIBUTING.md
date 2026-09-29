# Contributing

Starlette-RS aims to replace Starlette 1.6.0 while keeping its documented
Python import paths and ASGI behavior. The compatibility inventory and
implementation plan describe work that is incomplete; the current parity
results cover only listed cases and do not establish full compatibility.

## Toolchain

The checkout pins Rust 1.96.1 in `rust-toolchain.toml`. Rust 1.85 is the
declared minimum and is checked separately in CI. Python 3.10 is the package
floor; use Python 3.12 for the local style-tool environment.

## Local quality gates

Create the isolated Ruff environment once, then run the same formatting, lint,
compile, dependency-policy, live parity, and documentation checks used by CI:

```sh
make style-setup PYTHON=python3.12
make supply-chain-tools
make lint rustdoc-check check build supply-chain-check test docs-check
```

`make fmt`, `make rustdoc-check`, and `make python-format` are read-only checks.
Rustdoc warnings fail `make rustdoc-check`. The `fmt-fix` and
`python-format-fix` targets apply formatting. Ruff is pinned in
`requirements-style.txt`; its rules and formatting settings live in
`pyproject.toml`. Ruff covers all maintained Python under `scripts/`, both
Python package directories, and excludes generated output. `make lint` also
checks workflow syntax with checksum-verified actionlint. The
`supply-chain-check` target runs cargo-deny against all workspace features and
cargo-audit against the locked Rust dependency graph. `make supply-chain-tools`
installs cargo-deny 0.20.2 and cargo-audit 0.22.2; the workflow checker
downloads its pinned actionlint release into ignored `target/` on first use.
This project has no conventional Python or Rust unit-test suite: `make test`
runs live comparisons between pinned Starlette, the installed Python package,
and supported Rust-native workflows. `make project-policy-check` enforces that
policy.
Four currently selected Rust-native callable rows are
`not_run`, so the all-target parity command exits nonzero. The documentation
checker uses only Python's standard library and checks repository-local
Markdown link targets without network access.

If PyO3 cannot find a supported Python interpreter on the machine, set
`PYO3_PYTHON` to that interpreter when running Cargo-backed targets, for
example:

```sh
PYO3_PYTHON="$(command -v python3.12)" make check build test
```

`make ci` runs formatting, lint, Rust compilation/documentation, dependency
policy, live parity, and local documentation-link checks. It does not run the
benchmark lane; use the commands in
[`docs/PARITY.md`](docs/PARITY.md) for parity work and
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) for benchmark status.

## Release readiness

The current CI workflow checks source quality and package behavior; this
checkout does not define a package-publishing workflow. A successful CI run is
not a release or authorization to publish. Before adding release automation,
define checks for built crate and Python artifacts, installed-package consumers
outside the checkout, synchronized package metadata, and included license and
provenance files. Keep compatibility claims scoped to the installed-package
checks that have actually passed.

Before submitting a change, review `git diff`, make sure generated build output
is not included, and report the exact gates run and any remaining failures.
