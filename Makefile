# Requires GNU Make 3.81 or newer; Cargo remains the build system.

.DEFAULT_GOAL := help

CARGO ?= cargo
CARGO_DENY_VERSION ?= 0.20.2
CARGO_AUDIT_VERSION ?= 0.22.2
PYTHON ?= python3
PARITY_PYTHON ?= python3.12
STARLETTE_ORACLE_ROOT ?= ../starlette
STYLE_VENV ?= .venv-style
STYLE_PYTHON ?= $(STYLE_VENV)/bin/python
RUFF ?= $(STYLE_PYTHON) -m ruff
TYPECHECK_VENV ?= .venv-typecheck
TYPECHECK_PYTHON ?= $(TYPECHECK_VENV)/bin/python
TYPECHECKER ?= $(TYPECHECK_VENV)/bin/mypy
TYPECHECK_LOCK ?= scripts/parity/locks/typecheck-cpython312.txt
PYTHON_SOURCES ?= scripts starlette-rs-py/python/starlette starlette-rs-py/python/starlette_rs_py
CARGO_DENY ?= cargo deny
CARGO_AUDIT ?= cargo audit

.PHONY: help style-setup typecheck-setup fmt fmt-fix python-format python-format-fix clippy python-lint project-policy-check workflows-check lint check build test parity-inputs migrate-parity-inputs-v17-v18 migrate-parity-inputs-v18-v19 migrate-parity-inputs-v19-v20 migrate-parity-inputs-v20-v21 migrate-parity-inputs-v21-v22 migrate-parity-inputs-v22-v23 migrate-parity-inputs-v23-v24 migrate-parity-inputs-v24-v25 migrate-parity-inputs-v25-v26 parity-env parity-adapter parity-run contract-check source-inventory source-inventory-check benchmark-upstream rustdoc-check docs-check supply-chain-tools supply-chain-check ci

help: ## Show common Rust workspace commands
	@printf '%s\n' \
	  'starlette-rs — Rust workspace and Python compatibility package' \
	  '' \
	  '  make style-setup PYTHON=python3.12  Create the pinned Ruff environment' \
	  '  make typecheck-setup  Create the pinned public typing-contract checker environment' \
	  '  make fmt       Check Rust formatting' \
	  '  make rustdoc-check  Check Rust documentation with warnings denied' \
	  '  make python-format  Check Python formatting' \
	  '  make clippy    Run strict workspace Clippy' \
	  '  make python-lint  Run Ruff checks on Python sources' \
	  '  make project-policy-check  Enforce parity-only behavioral checks' \
	  '  make workflows-check  Lint GitHub Actions workflows' \
	  '  make lint      Run Rust and Python format/lint checks' \
	  '  make supply-chain-check  Audit Rust advisories, licenses, versions, and sources' \
	  '  make check     Type-check all workspace targets and features' \
	  '  make build     Link the PyO3 extension in extension-module mode' \
	  '  make parity-inputs  Generate ignored JSON inputs from authored YAML' \
	  '  make migrate-parity-inputs-v17-v18  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v18-v19  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v19-v20  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v20-v21  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v21-v22  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v22-v23  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v23-v24  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v24-v25  Migrate authored parity input schema headers' \
	  '  make migrate-parity-inputs-v25-v26  Migrate authored parity input schema headers' \
	  '  make parity-env  Build the wheel and prepare isolated source/package environments' \
	  '  make parity-adapter  Build the current Rust-native parity adapter' \
	  '  make source-inventory  Regenerate the metadata-derived API catalog and source atlas' \
	  '  make source-inventory-check  Check the API catalog and generated atlas for drift' \
	  '  make test       Run live source-to-package and supported Rust parity comparisons' \
	  '  make contract-check  Generate and statically validate parity inputs' \
	  '  make benchmark-upstream  Run 74 correctness-gated Starlette source/package workloads' \
	  '  make docs-check  Check local documentation links offline' \
	  '  make ci        Run the local quality-gate sequence' \
	  '  make supply-chain-tools  Install pinned cargo-deny and cargo-audit tools' \
	  '' \
	  'Set CARGO, PYTHON, PARITY_PYTHON, STYLE_VENV, STYLE_PYTHON, or RUFF to override local tools.'

style-setup: ## Create an isolated environment with the pinned Python style tool
	$(PYTHON) -m venv "$(STYLE_VENV)"
	$(STYLE_PYTHON) -m pip install --disable-pip-version-check --no-input --no-deps --requirement requirements-style.txt

typecheck-setup: ## Create an isolated environment with the hash-locked public typing-contract checker
	$(PARITY_PYTHON) -m venv --clear "$(TYPECHECK_VENV)"
	$(TYPECHECK_PYTHON) -m pip install --disable-pip-version-check --no-input --no-deps --require-hashes --only-binary=:all: --requirement "$(TYPECHECK_LOCK)"
	$(TYPECHECKER) --version

fmt: ## Check formatting
	$(CARGO) fmt --all -- --check

fmt-fix: ## Apply rustfmt formatting
	$(CARGO) fmt --all

python-format: ## Check Python formatting
	$(RUFF) format --check $(PYTHON_SOURCES)

python-format-fix: ## Apply Python formatting
	$(RUFF) format $(PYTHON_SOURCES)

clippy: ## Run strict workspace Clippy
	$(CARGO) clippy --workspace --all-targets --all-features --locked -- -D warnings

rustdoc-check: ## Check Rust documentation with warnings denied
	RUSTDOCFLAGS="-D warnings" $(CARGO) doc --workspace --all-features --no-deps --locked

python-lint: ## Run Ruff lint checks on Python sources
	$(RUFF) check $(PYTHON_SOURCES)

project-policy-check: ## Enforce parity-only behavioral checks and repository test policy
	$(PYTHON) scripts/check_project_policy.py

workflows-check: ## Validate GitHub Actions workflows with checksum-pinned actionlint
	$(PYTHON) scripts/check_workflows.py

lint: fmt python-format clippy python-lint project-policy-check workflows-check ## Check Rust and Python formatting, lints, workflow syntax, and project policy

supply-chain-tools: ## Install the pinned cargo-deny and cargo-audit tools
	$(CARGO) install cargo-deny --version "$(CARGO_DENY_VERSION)" --locked
	$(CARGO) install cargo-audit --version "$(CARGO_AUDIT_VERSION)" --locked

supply-chain-check: ## Audit Rust advisories, licenses, duplicate versions, wildcard versions, and sources
	$(CARGO_DENY) check advisories bans licenses sources
	$(CARGO_AUDIT) --deny warnings

check: ## Type-check all workspace targets and features
	$(CARGO) check --workspace --all-targets --all-features --locked

build: ## Link the Rust workspace and PyO3 extension
	PYO3_BUILD_EXTENSION_MODULE=1 $(CARGO) build --workspace --all-features --locked

parity-inputs: ## Generate ignored runtime JSON inputs from authored YAML definitions
	$(PARITY_PYTHON) -m scripts.parity.generate_inputs

migrate-parity-inputs-v17-v18: ## Migrate active authored parity input files to schema @18
	$(PYTHON) scripts/migrate_parity_input_v17_to_v18.py

migrate-parity-inputs-v18-v19: ## Migrate active authored parity input files to schema @19
	$(PYTHON) scripts/migrate_parity_input_v18_to_v19.py

migrate-parity-inputs-v19-v20: ## Migrate active authored parity input files to schema @20
	$(PYTHON) scripts/migrate_parity_input_v19_to_v20.py

migrate-parity-inputs-v20-v21: ## Migrate active authored parity input files to schema @21
	$(PYTHON) scripts/migrate_parity_input_v20_to_v21.py

migrate-parity-inputs-v21-v22: ## Migrate active authored parity input files to schema @22
	$(PYTHON) scripts/migrate_parity_input_v21_to_v22.py

migrate-parity-inputs-v22-v23: ## Migrate active authored parity input files to schema @23
	$(PYTHON) scripts/migrate_parity_input_v22_to_v23.py

migrate-parity-inputs-v23-v24: ## Migrate active authored parity input files to schema @24
	$(PYTHON) scripts/migrate_parity_input_v23_to_v24.py

migrate-parity-inputs-v24-v25: ## Migrate active authored parity input files to schema @25
	$(PYTHON) scripts/migrate_parity_input_v24_to_v25.py

migrate-parity-inputs-v25-v26: ## Migrate active authored parity input files to schema @26
	$(PYTHON) scripts/migrate_parity_input_v25_to_v26.py

parity-env: parity-inputs ## Build the package wheel and prepare isolated parity environments
	$(PARITY_PYTHON) -m scripts.parity.cli prepare-env --force --upstream "$(STARLETTE_ORACLE_ROOT)"

parity-adapter: ## Build the current Rust-native parity adapter
	$(CARGO) build --locked --bin starlette-rs-parity-adapter

contract-check: parity-inputs ## Generate inputs, then validate the local parity contract and input inventory offline
	$(PARITY_PYTHON) -m scripts.parity.cli validate-contract

source-inventory: contract-check ## Regenerate the metadata-derived API catalog and source coverage atlas
	$(PARITY_PYTHON) scripts/inventory_upstream_api.py --upstream "$(STARLETTE_ORACLE_ROOT)"
	$(PARITY_PYTHON) scripts/merge_compatibility_atlas.py --upstream "$(STARLETTE_ORACLE_ROOT)"

source-inventory-check: contract-check ## Check the API catalog and generated atlas for drift against pinned Starlette
	$(PARITY_PYTHON) scripts/inventory_upstream_api.py --upstream "$(STARLETTE_ORACLE_ROOT)" --check
	$(PARITY_PYTHON) scripts/merge_compatibility_atlas.py --check --upstream "$(STARLETTE_ORACLE_ROOT)"

parity-run: contract-check parity-env parity-adapter source-inventory-check typecheck-setup ## Run source inventory, exact source/package, and supported Rust comparisons
	STARLETTE_ORACLE_ROOT="$(STARLETTE_ORACLE_ROOT)" STARLETTE_PARITY_TYPECHECKER="$(abspath $(TYPECHECKER))" $(PARITY_PYTHON) -m scripts.parity.cli run

test: parity-run ## Run behavioral checks as live source-to-target parity only

benchmark-upstream: contract-check parity-env typecheck-setup ## Run 74 correctness-gated Starlette source/package workloads
	STARLETTE_PARITY_TYPECHECKER="$(abspath $(TYPECHECKER))" $(PARITY_PYTHON) -m scripts.parity.cli benchmark-upstream
	$(PARITY_PYTHON) -m scripts.parity.benchmark_evidence --write

docs-check: ## Check local Markdown links without network access
	$(PYTHON) scripts/check_docs.py
	$(PARITY_PYTHON) -m scripts.parity.benchmark_evidence --check

ci: lint rustdoc-check check build supply-chain-check source-inventory-check parity-run docs-check ## Run formatting, lint, compilation, supply-chain, source inventory, live parity, and docs gates
