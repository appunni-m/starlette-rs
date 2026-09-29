# Requires GNU Make 3.81 or newer; Cargo remains the build system.

.DEFAULT_GOAL := help

CARGO ?= cargo
PYTHON ?= python3
PARITY_PYTHON ?= python3.12
STARLETTE_ORACLE_ROOT ?= /Users/lazytrot/work/starlette
STYLE_VENV ?= .venv-style
STYLE_PYTHON ?= $(STYLE_VENV)/bin/python
RUFF ?= $(STYLE_PYTHON) -m ruff
PYTHON_SOURCES ?= scripts starlette-rs-py/python/starlette starlette-rs-py/python/starlette_rs_py

.PHONY: help style-setup fmt fmt-fix python-format python-format-fix clippy python-lint project-policy-check lint check build test parity-inputs parity-env parity-adapter parity-run contract-check source-inventory-check benchmark-upstream rustdoc-check docs-check ci

help: ## Show common Rust workspace commands
	@printf '%s\n' \
	  'starlette-rs — Rust workspace and Python compatibility package' \
	  '' \
	  '  make style-setup PYTHON=python3.12  Create the pinned Ruff environment' \
	  '  make fmt       Check Rust formatting' \
	  '  make rustdoc-check  Check Rust documentation with warnings denied' \
	  '  make python-format  Check Python formatting' \
	  '  make clippy    Run strict workspace Clippy' \
	  '  make python-lint  Run Ruff checks on Python sources' \
	  '  make project-policy-check  Enforce parity-only behavioral checks' \
	  '  make lint      Run Rust and Python format/lint checks' \
	  '  make check     Type-check all workspace targets and features' \
	  '  make build     Link the PyO3 extension in extension-module mode' \
	  '  make parity-inputs  Generate ignored JSON inputs from authored YAML' \
	  '  make parity-env  Build the wheel and prepare isolated source/package environments' \
	  '  make parity-adapter  Build the current Rust-native parity adapter' \
	  '  make source-inventory-check  Check the metadata-derived API catalog and source atlas' \
	  '  make test       Run live source-to-package and supported Rust parity comparisons' \
	  '  make contract-check  Generate and statically validate parity inputs' \
	  '  make benchmark-upstream  Run 74 correctness-gated Starlette source/package workloads' \
	  '  make docs-check  Check local documentation links offline' \
	  '  make ci        Run the local quality-gate sequence' \
	  '' \
	  'Set CARGO, PYTHON, PARITY_PYTHON, STYLE_VENV, STYLE_PYTHON, or RUFF to override local tools.'

style-setup: ## Create an isolated environment with the pinned Python style tool
	$(PYTHON) -m venv "$(STYLE_VENV)"
	$(STYLE_PYTHON) -m pip install --disable-pip-version-check --no-input --no-deps --requirement requirements-style.txt

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

lint: fmt python-format clippy python-lint project-policy-check ## Check Rust and Python formatting, lints, and project policy

check: ## Type-check all workspace targets and features
	$(CARGO) check --workspace --all-targets --all-features --locked

build: ## Link the Rust workspace and PyO3 extension
	PYO3_BUILD_EXTENSION_MODULE=1 $(CARGO) build --workspace --all-features --locked

parity-inputs: ## Generate ignored runtime JSON inputs from authored YAML definitions
	$(PARITY_PYTHON) -m scripts.parity.generate_inputs

parity-env: parity-inputs ## Build the package wheel and prepare isolated parity environments
	$(PARITY_PYTHON) -m scripts.parity.cli prepare-env --force --upstream "$(STARLETTE_ORACLE_ROOT)"

parity-adapter: ## Build the current Rust-native parity adapter
	$(CARGO) build --locked --bin starlette-rs-parity-adapter

contract-check: parity-inputs ## Generate inputs, then validate the local parity contract and input inventory offline
	$(PARITY_PYTHON) -m scripts.parity.cli validate-contract

source-inventory-check: contract-check ## Check the generated API catalog and source coverage atlas against pinned Starlette
	$(PARITY_PYTHON) scripts/inventory_upstream_api.py --upstream "$(STARLETTE_ORACLE_ROOT)" --check
	$(PARITY_PYTHON) scripts/merge_compatibility_atlas.py --check --upstream "$(STARLETTE_ORACLE_ROOT)"

parity-run: contract-check parity-env parity-adapter source-inventory-check ## Run source inventory, exact source/package, and supported Rust comparisons
	STARLETTE_ORACLE_ROOT="$(STARLETTE_ORACLE_ROOT)" $(PARITY_PYTHON) -m scripts.parity.cli run

test: parity-run ## Run behavioral checks as live source-to-target parity only

benchmark-upstream: contract-check parity-env ## Run 74 correctness-gated Starlette source/package workloads
	$(PARITY_PYTHON) -m scripts.parity.cli benchmark-upstream

docs-check: ## Check local Markdown links without network access
	$(PYTHON) scripts/check_docs.py

ci: lint rustdoc-check check build source-inventory-check parity-run docs-check ## Run formatting, lint, compilation, source inventory, live parity, and docs gates
