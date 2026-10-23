"""Command-line entry point for contract validation and parity runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .api_sources import load_api_metadata, validate_api_sources
from .benchmark import run_benchmark
from .comparator import compare_workflows
from .contract import (
    BENCHMARK_RESULT_SCHEMA,
    COVERAGE_RESULT_SCHEMA,
    INPUT_SCHEMA,
    MANIFEST_SCHEMA,
    ORACLE_COMMIT,
    RESULT_SCHEMA,
    UPSTREAM_BENCHMARK_RESULT_SCHEMA,
    ContractError,
    _all_manifest_surfaces,
    load_json,
    load_manifest,
    sha256_file,
    validate_benchmark_inputs,
    validate_inputs,
    validate_manifest,
    validate_result_artifact,
    validate_workflow_result,
)
from .coverage import run_coverage
from .envs import (
    _target_source_identity,
    prepare_environments,
    validate_markupsafe_build_locks,
    validate_oracle_runtime_lock,
    validate_runtime_lock,
)
from .reconcile import reconcile_parity_results
from .runner import ROOT, load_json_from_text, run_parity
from .scope_completeness import validate_full_scope_completeness
from .upstream_benchmark import UPSTREAM_RESULT_RELATIVE, run_upstream_benchmark

MANIFEST_RELATIVE = Path("tests/fixtures/manifest.yaml")
RESULT_SCHEMA_RELATIVE = Path("tests/fixtures/result-schema.json")
BENCHMARK_RESULT_SCHEMA_RELATIVE = Path("tests/fixtures/benchmark-result-schema.json")
COVERAGE_RESULT_SCHEMA_RELATIVE = Path("tests/fixtures/coverage-result-schema.json")
UPSTREAM_BENCHMARK_RESULT_SCHEMA_RELATIVE = Path(
    "tests/fixtures/upstream-benchmark-result-schema.json"
)
DEFAULT_UPSTREAM = Path("/Users/lazytrot/work/starlette")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.parity.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="strictly validate the active slice contract and pinned source identity"
    )
    validate.add_argument("--root", type=Path, default=ROOT)
    validate.add_argument("--manifest", type=Path, default=None)
    validate.add_argument("--upstream", type=Path, default=None)

    contract_check = subparsers.add_parser(
        "validate-contract",
        help="validate local manifest, input inventory, result schemas, and parity tooling",
    )
    contract_check.add_argument("--root", type=Path, default=ROOT)
    contract_check.add_argument("--manifest", type=Path, default=None)

    prepare = subparsers.add_parser(
        "prepare-env",
        help="build the local wheel and prepare isolated, locked CPython 3.10 through 3.14 environments",
    )
    prepare.add_argument("--root", type=Path, default=ROOT)
    prepare.add_argument("--upstream", type=Path, default=None)
    prepare.add_argument("--python", type=Path, default=None)
    prepare.add_argument(
        "--force", action="store_true", help="replace only generated build/parity artifacts"
    )

    inventory = subparsers.add_parser(
        "inventory-slice", help="print the exact operation denominator for this slice"
    )
    inventory.add_argument("--root", type=Path, default=ROOT)
    inventory.add_argument("--manifest", type=Path, default=None)
    inventory.add_argument("--upstream", type=Path, default=None)

    for command_name, help_text in (
        ("run", "execute the isolated source oracle and target adapters"),
        ("oracle-only", "execute the isolated source oracle only"),
    ):
        command = subparsers.add_parser(command_name, help=help_text)
        command.add_argument("--root", type=Path, default=ROOT)
        command.add_argument("--manifest", type=Path, default=None)
        command.add_argument("--output", type=Path, default=None)
        command.add_argument(
            "--case-id",
            action="append",
            dest="case_ids",
            help="select one active input case; repeat to run a batch",
        )

    compare = subparsers.add_parser(
        "compare", help="compare two adapter workflow results by the declared exact selectors"
    )
    compare.add_argument("--root", type=Path, default=ROOT)
    compare.add_argument("--manifest", type=Path, default=None)
    compare.add_argument("--input", type=Path, default=None)
    compare.add_argument("--case-id", required=True)
    compare.add_argument("--source", type=Path, required=True)
    compare.add_argument("--target", type=Path, required=True)

    lane_help = {
        "coverage": "measure the declared Rust coverage component for selected target profiles",
        "benchmark": "run the declared correctness-gated benchmark workload",
    }
    for lane in ("coverage", "benchmark"):
        command = subparsers.add_parser(lane, help=lane_help[lane])
        command.add_argument("--root", type=Path, default=ROOT)
        command.add_argument("--manifest", type=Path, default=None)
        if lane == "coverage":
            command.add_argument(
                "--target-profile",
                default=None,
                help="measure one declared target profile (default: prepared CPython package profile)",
            )
            command.add_argument(
                "--case-id",
                action="append",
                default=None,
                help=(
                    "run only these IDs from the profile plan for diagnosis; partial selections "
                    "cannot produce a coverage receipt"
                ),
            )

    upstream_benchmark = subparsers.add_parser(
        "benchmark-upstream",
        help="run the 74 pinned Starlette Router/GZip workloads behind exact source/package gates",
    )
    upstream_benchmark.add_argument("--root", type=Path, default=ROOT)
    upstream_benchmark.add_argument("--manifest", type=Path, default=None)

    aggregate = subparsers.add_parser(
        "aggregate",
        help="aggregate five-profile parity evidence without proving full replacement parity",
    )
    aggregate.add_argument("results", nargs="*", type=Path)
    aggregate.add_argument("--root", type=Path, default=ROOT)
    aggregate.add_argument("--manifest", type=Path, default=None)
    aggregate.add_argument("--output", type=Path, default=None)

    reconcile = subparsers.add_parser(
        "reconcile",
        help="reconcile focused evidence with skipped and non-applicable full-parity rows",
    )
    reconcile.add_argument("--baseline", action="append", required=True, type=Path)
    reconcile.add_argument("--supplement", action="append", required=True, type=Path)
    reconcile.add_argument("--root", type=Path, default=ROOT)
    reconcile.add_argument("--manifest", type=Path, default=None)
    reconcile.add_argument("--output", type=Path, default=None)
    return parser


def _manifest_path(root: Path, override: Path | None) -> Path:
    return (
        override if override and override.is_absolute() else root / (override or MANIFEST_RELATIVE)
    )


def _read_result_artifact(path: Path) -> tuple[Any, str]:
    """Read and digest one artifact from the same byte snapshot."""
    try:
        raw = path.read_bytes()
        value = load_json_from_text(raw.decode("utf-8"), str(path))
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read result artifact {path}: {exc}") from exc
    return value, hashlib.sha256(raw).hexdigest()


def _current_native_target_revision(root: Path, candidate_revision: str) -> str:
    # Mirror the source list and FNV-1a stream embedded by starlette-rs/build.rs.
    workspace_root = root.resolve()
    crate_root = workspace_root / "starlette-rs"
    source_files = [
        workspace_root / "Cargo.toml",
        workspace_root / "Cargo.lock",
        crate_root / "Cargo.toml",
        crate_root / "build.rs",
    ]
    toolchain = workspace_root / "rust-toolchain.toml"
    if toolchain.is_file():
        source_files.append(toolchain)
    source_dir = crate_root / "src"
    try:
        source_files.extend(
            path for path in source_dir.rglob("*") if path.is_file() and not path.is_symlink()
        )
        source_files = sorted(set(source_files))
        fingerprint = 0xCBF29CE484222325
        for path in source_files:
            relative = path.relative_to(workspace_root).as_posix().encode()
            contents = path.read_bytes()
            for byte in relative:
                fingerprint ^= byte
                fingerprint = (fingerprint * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
            fingerprint = (fingerprint * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
            for byte in contents:
                fingerprint ^= byte
                fingerprint = (fingerprint * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
            fingerprint ^= 0xFF
            fingerprint = (fingerprint * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot compute current Rust-native target revision: {exc}") from exc
    return f"{candidate_revision}+source-fnv1a64-{fingerprint:016x}"


def _aggregate_parity_results(
    root: Path,
    manifest_path: Path,
    result_paths: list[Path],
) -> dict[str, Any]:
    """Aggregate exact full active parity runs, one artifact per CPython profile."""
    root = root.resolve()
    manifest_file = manifest_path.resolve()
    try:
        manifest_relative = manifest_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError("active parity manifest must be inside the repository root") from exc

    manifest = load_manifest(manifest_file)
    validate_manifest(manifest)
    python_profiles = [
        profile
        for profile in manifest["target_profiles"]
        if profile["target_id"] == "python-package"
    ]
    native_profiles = [
        profile for profile in manifest["target_profiles"] if profile["target_id"] == "rust-native"
    ]
    if len(python_profiles) != 5 or len(native_profiles) != 1:
        raise ContractError(
            "aggregate requires the five declared CPython profiles and one Rust-native profile"
        )

    expected_python_ids = [profile["id"] for profile in python_profiles]
    native_profile_id = native_profiles[0]["id"]
    expected_profile_set = set(expected_python_ids)
    expected_manifest = {
        "path": manifest_relative,
        "schema": manifest["schema"],
        "sha256": sha256_file(manifest_file),
    }
    oracle_revision = manifest["scope"]["inventory"]["revision"]
    if oracle_revision != ORACLE_COMMIT:
        raise ContractError("active manifest oracle revision differs from the pinned commit")
    candidate_source = _target_source_identity(root)
    candidate_revision = candidate_source["revision"]
    native_candidate_revision = _current_native_target_revision(root, candidate_revision)

    artifacts_by_profile: dict[str, dict[str, Any]] = {}
    seen_paths: set[Path] = set()
    seen_digests: set[str] = set()
    package_revision: str | None = None
    native_revision: str | None = None
    package_shared_identity: tuple[Any, ...] | None = None
    native_shared_identity: tuple[Any, ...] | None = None
    target_evidence_reasons: set[str] = set()
    if candidate_source["dirty"]:
        target_evidence_reasons.add("current candidate checkout is dirty")

    for supplied_path in result_paths:
        path = supplied_path.resolve()
        if path in seen_paths:
            raise ContractError(f"duplicate result artifact path: {path}")
        seen_paths.add(path)
        raw_artifact, digest = _read_result_artifact(path)
        artifact = validate_result_artifact(
            raw_artifact,
            root=root,
            manifest_path=manifest_file,
        )
        if artifact["schema"] != RESULT_SCHEMA:
            raise ContractError(f"aggregate accepts parity results only: {path}")
        if digest in seen_digests:
            raise ContractError(f"duplicate result artifact digest: {digest}")
        seen_digests.add(digest)

        identity = artifact["identity"]
        if identity["manifest"] != expected_manifest:
            raise ContractError(f"result artifact is not bound to the active manifest: {path}")
        if identity["command"]["command_id"] != "parity":
            raise ContractError(f"result artifact is not a parity run: {path}")
        selection = identity["selection"]
        selected_profiles = selection["target_profiles"]
        if selection["kind"] != "all" or selection["case_ids"]:
            raise ContractError(f"result artifact is not a full all-cases run: {path}")
        if len(selected_profiles) != 2 or native_profile_id not in selected_profiles:
            raise ContractError(f"result artifact does not include its Rust-native profile: {path}")
        python_ids = [
            profile_id for profile_id in selected_profiles if profile_id in expected_profile_set
        ]
        if len(python_ids) != 1:
            raise ContractError(f"result artifact must select exactly one CPython profile: {path}")
        profile_id = python_ids[0]
        if profile_id in artifacts_by_profile:
            raise ContractError(f"duplicate result for CPython profile {profile_id}")
        expected_selection = [
            profile["id"]
            for profile in manifest["target_profiles"]
            if profile["id"] in {native_profile_id, profile_id}
        ]
        if selected_profiles != expected_selection:
            raise ContractError(f"result profile selection is not in manifest order: {path}")

        oracles = identity["oracles"]
        if len(oracles) != 1 or oracles[0]["revision"] != oracle_revision:
            raise ContractError(
                f"result artifact omits or mixes the pinned source identity: {path}"
            )
        targets_by_profile = {target["target_profile"]: target for target in identity["targets"]}
        if set(targets_by_profile) != {native_profile_id, profile_id}:
            raise ContractError(f"result artifact omits a selected target identity: {path}")
        package_target = targets_by_profile[profile_id]
        native_target = targets_by_profile[native_profile_id]
        if package_target["target_id"] != "python-package":
            raise ContractError(f"result artifact package target identity is invalid: {path}")
        if native_target["target_id"] != "rust-native":
            raise ContractError(f"result artifact native target identity is invalid: {path}")

        for target in (package_target, native_target):
            if target["dirty"]:
                target_evidence_reasons.add(
                    "one or more target artifacts were built from a dirty tree"
                )
            revision = target["revision"]
            if target["target_id"] == "rust-native":
                matches_candidate = revision == native_candidate_revision
            else:
                matches_candidate = revision == candidate_revision or (
                    target["dirty"] and revision == f"dirty-tree:{target['target_tree_sha256']}"
                )
            if not matches_candidate:
                target_evidence_reasons.add(
                    "one or more target artifact revisions differ from the current "
                    "candidate checkout"
                )

        # A dirty package target identifies the installed wheel tree. That digest
        # includes its CPython-specific extension binary, so compare shared source
        # metadata here and retain the exact wheel digest in the per-profile record.
        package_identity = (
            package_target["dirty"],
            package_target["package_version"],
            package_target["dependency_lock_sha256"],
        )
        native_identity = (
            native_target["revision"],
            native_target["dirty"],
            native_target["package_version"],
            native_target["dependency_lock_sha256"],
            native_target["environment_sha256"],
        )
        if package_shared_identity is None:
            package_shared_identity = package_identity
            package_revision = candidate_revision
        elif package_identity != package_shared_identity:
            raise ContractError("CPython parity artifacts contain mixed package target identities")
        if native_shared_identity is None:
            native_shared_identity = native_identity
            native_revision = native_target["revision"]
        elif native_identity != native_shared_identity:
            raise ContractError("CPython parity artifacts contain mixed Rust-native identities")

        artifacts_by_profile[profile_id] = {
            "path": str(path),
            "result_sha256": digest,
            "status": artifact["status"],
            "summary": artifact["summary"],
            "target": {
                "revision": package_target["revision"],
                "dirty": package_target["dirty"],
                "package_version": package_target["package_version"],
                "target_tree_sha256": package_target["target_tree_sha256"],
                "runtime": package_target["runtime"],
                "os": package_target["os"],
                "architecture": package_target["architecture"],
            },
        }

    missing_profiles = [
        profile_id for profile_id in expected_python_ids if profile_id not in artifacts_by_profile
    ]
    profiles = [
        {
            "target_profile": profile_id,
            **artifacts_by_profile[profile_id],
        }
        for profile_id in expected_python_ids
        if profile_id in artifacts_by_profile
    ]
    summaries = [item["summary"] for item in artifacts_by_profile.values()]
    totals = {
        name: sum(summary[name] for summary in summaries)
        for name in ("selected", "executed", "passed", "failed", "not_run")
    }
    totals["fault_contracts"] = {
        name: sum(summary["fault_contracts"][name] for summary in summaries)
        for name in ("selected", "executed", "passed", "failed", "not_run")
    }
    totals["infrastructure_errors"] = sum(summary["infrastructure_errors"] for summary in summaries)
    totals["profiles_expected"] = len(expected_python_ids)
    totals["profiles_supplied"] = len(artifacts_by_profile)
    totals["profiles_missing"] = len(missing_profiles)

    reasons: list[str] = []
    reasons.extend(sorted(target_evidence_reasons))
    if missing_profiles:
        reasons.append("one or more CPython profiles are missing")
    if any(item["status"] != "completed" for item in artifacts_by_profile.values()):
        reasons.append("one or more profile runs did not complete")
    if totals["failed"] or totals["fault_contracts"]["failed"]:
        reasons.append("one or more parity or fault-contract comparisons failed")
    if totals["not_run"] or totals["fault_contracts"]["not_run"]:
        reasons.append("one or more parity or fault-contract comparisons were not run")
    if totals["infrastructure_errors"]:
        reasons.append("one or more profile runs reported infrastructure errors")
    if totals["passed"] != totals["selected"]:
        reasons.append("not every selected parity comparison passed")
    if totals["fault_contracts"]["passed"] != totals["fault_contracts"]["selected"]:
        reasons.append("not every selected fault contract passed")

    parity_status = "proven" if not reasons else "not_proven"
    parity_reason = (
        "; ".join(reasons)
        if reasons
        else "all five CPython profiles passed the active parity contract"
    )
    return {
        "schema": "migration-parity/status-report@1",
        "status": "not_proven",
        "reason": "full Starlette replacement remains not_proven: this aggregate summarizes "
        "the five-profile parity matrix only; compatible coverage and package qualification "
        "remain incomplete",
        "identity": {
            "manifest": expected_manifest,
            "oracle_revision": oracle_revision,
            "target_revision": package_revision,
            "rust_native_revision": native_revision,
        },
        "parity_matrix": {
            "scope": "active five-profile CPython parity matrix",
            "counting": "per-artifact run totals; repeated Rust-native rows remain per-run counts",
            "status": parity_status,
            "reason": parity_reason,
            "profiles_expected": expected_python_ids,
            "profiles_missing": missing_profiles,
            "profiles": profiles,
            "summary": totals,
        },
    }


def _aggregate_output_path(root: Path, override: Path | None) -> Path:
    root = root.resolve()
    output = (
        root / "build/parity/status-report.json"
        if override is None
        else override
        if override.is_absolute()
        else root / override
    ).resolve()
    try:
        output.relative_to((root / "build/parity").resolve())
    except ValueError as exc:
        raise ContractError("aggregate output must be inside ignored build/parity") from exc
    return output


def _upstream_path(override: Path | None) -> Path:
    if override:
        return override.resolve()
    env_value = os.environ.get("STARLETTE_ORACLE_ROOT")
    if env_value:
        return Path(env_value).resolve()
    return DEFAULT_UPSTREAM.resolve()


def _source_identity(upstream: Path) -> tuple[str, str]:
    package = upstream / "starlette"
    if not (package / "__init__.py").is_file():
        raise ContractError(f"pinned Starlette package not found under {upstream}")
    try:
        commit = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        version_source = (package / "__init__.py").read_text(encoding="utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ContractError(f"cannot inspect the pinned Starlette source: {exc}") from exc
    if commit != ORACLE_COMMIT:
        raise ContractError(f"expected Starlette commit {ORACLE_COMMIT}, found {commit}")
    if '__version__ = "1.6.0"' not in version_source:
        raise ContractError("the local upstream source does not declare Starlette 1.6.0")
    return commit, str(package.resolve())


def _validate_schema(root: Path) -> None:
    schema_path = root / RESULT_SCHEMA_RELATIVE
    schema = load_json(schema_path)
    if (
        not isinstance(schema, dict)
        or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ContractError("result-schema.json must use JSON Schema 2020-12")
    if schema.get("properties", {}).get("schema") != {"const": RESULT_SCHEMA}:
        raise ContractError(
            "result-schema.json schema identifier does not match the parity result contract"
        )
    if schema.get("additionalProperties") is not False:
        raise ContractError("result-schema.json must reject unknown top-level fields")
    if set(schema.get("required", [])) != {
        "schema",
        "identity",
        "status",
        "summary",
        "comparisons",
        "fault_contracts",
        "infrastructure_errors",
    }:
        raise ContractError(
            "result-schema.json required top-level fields differ from the fixed result contract"
        )
    input_schema = (
        schema.get("$defs", {})
        .get("identity", {})
        .get("properties", {})
        .get("inputs", {})
        .get("items", {})
        .get("properties", {})
        .get("schema")
    )
    if input_schema != {"const": INPUT_SCHEMA}:
        raise ContractError(
            "result-schema.json input schema identifier does not match the parity input contract"
        )
    benchmark_schema = load_json(root / BENCHMARK_RESULT_SCHEMA_RELATIVE)
    if (
        not isinstance(benchmark_schema, dict)
        or benchmark_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ContractError("benchmark-result-schema.json must use JSON Schema 2020-12")
    if benchmark_schema.get("properties", {}).get("schema") != {"const": BENCHMARK_RESULT_SCHEMA}:
        raise ContractError(
            "benchmark-result-schema.json schema identifier does not match the benchmark result contract"
        )
    if benchmark_schema.get("additionalProperties") is not False:
        raise ContractError("benchmark-result-schema.json must reject unknown top-level fields")
    if set(benchmark_schema.get("required", [])) != {
        "schema",
        "identity",
        "status",
        "summary",
        "workloads",
        "upstream_suite",
    }:
        raise ContractError(
            "benchmark-result-schema.json required fields differ from the benchmark result contract"
        )
    coverage_schema = load_json(root / COVERAGE_RESULT_SCHEMA_RELATIVE)
    if (
        not isinstance(coverage_schema, dict)
        or coverage_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ContractError("coverage-result-schema.json must use JSON Schema 2020-12")
    if coverage_schema.get("properties", {}).get("schema") != {"const": COVERAGE_RESULT_SCHEMA}:
        raise ContractError(
            "coverage-result-schema.json schema identifier differs from the coverage result contract"
        )
    if coverage_schema.get("additionalProperties") is not False:
        raise ContractError("coverage-result-schema.json must reject unknown top-level fields")
    if set(coverage_schema.get("required", [])) != {
        "schema",
        "identity",
        "status",
        "collector",
        "summary",
        "plans",
        "infrastructure_errors",
    }:
        raise ContractError(
            "coverage-result-schema.json required fields differ from the fixed coverage result contract"
        )
    upstream_benchmark_schema = load_json(root / UPSTREAM_BENCHMARK_RESULT_SCHEMA_RELATIVE)
    if (
        not isinstance(upstream_benchmark_schema, dict)
        or upstream_benchmark_schema.get("$schema")
        != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ContractError("upstream-benchmark-result-schema.json must use JSON Schema 2020-12")
    if upstream_benchmark_schema.get("properties", {}).get("schema") != {
        "const": UPSTREAM_BENCHMARK_RESULT_SCHEMA
    }:
        raise ContractError(
            "upstream-benchmark-result-schema.json schema identifier differs from the manifest interface"
        )
    if upstream_benchmark_schema.get("additionalProperties") is not False:
        raise ContractError(
            "upstream-benchmark-result-schema.json must reject unknown top-level fields"
        )
    if set(upstream_benchmark_schema.get("required", [])) != {
        "schema",
        "completion_scope",
        "identity",
        "status",
        "summary",
        "workloads",
    }:
        raise ContractError(
            "upstream-benchmark-result-schema.json required fields differ from the registered upstream result contract"
        )


def _validate_python_sources(root: Path) -> int:
    count = 0
    for path in sorted((root / "scripts/parity").rglob("*.py")):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ContractError(
                f"invalid parity tooling source {path.relative_to(root)}: {exc}"
            ) from exc
        count += 1
    if count == 0:
        raise ContractError("no parity tooling source files were found")
    return count


def validate_repository(
    root: Path, manifest_override: Path | None = None, upstream_override: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = _manifest_path(root, manifest_override)
    upstream = _upstream_path(upstream_override)
    report = validate_contract_repository(root, manifest_path, upstream)
    commit, package = _source_identity(upstream)
    runtime_lock_sha256 = validate_runtime_lock(root, upstream)
    oracle_runtime_lock_sha256 = validate_oracle_runtime_lock(root, upstream)
    markupsafe_build_locks = validate_markupsafe_build_locks(root, upstream)
    return {
        **report,
        "source_checkout_checked": True,
        "oracle_commit": commit,
        "oracle_package": package,
        "runtime_dependency_lock_sha256": runtime_lock_sha256,
        "oracle_runtime_dependency_lock_sha256": oracle_runtime_lock_sha256,
        "markupsafe_source_lock_sha256": markupsafe_build_locks["source_lock_sha256"],
        "markupsafe_build_lock_sha256": markupsafe_build_locks["build_lock_sha256"],
    }


def validate_contract_repository(
    root: Path, manifest_override: Path | None = None, upstream: Path | None = None
) -> dict[str, Any]:
    """Validate the repository-local parity contract without an upstream checkout."""
    root = root.resolve()
    manifest_path = _manifest_path(root, manifest_override)
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest)
    metadata = load_api_metadata(root)
    validate_api_sources(manifest, metadata)
    indexed_inputs, cases = validate_inputs(root, manifest)
    scope_completeness = validate_full_scope_completeness(
        root, manifest, indexed_inputs, cases, upstream
    )
    benchmark_inputs = validate_benchmark_inputs(root, manifest, cases)
    _validate_schema(root)
    source_count = _validate_python_sources(root)

    # All declared maintenance command IDs must resolve to the fixed CLI.
    commands = {command["id"] for command in manifest["commands"]}
    referenced = {
        manifest["scope"]["inventory"]["command_id"],
        manifest["documentation"]["command_id"],
        *(interface["command_id"] for interface in manifest["interfaces"].values()),
    }
    missing = referenced - commands
    if missing:
        raise ContractError(f"manifest references undeclared commands: {sorted(missing)}")

    lane_root = root / "build/parity/inputs/parity"
    non_json = [
        path for path in lane_root.rglob("*") if path.is_file() and path.suffix.lower() != ".json"
    ]
    if non_json:
        raise ContractError(
            f"non-JSON files remain in the active parity input tree: {[path.relative_to(root).as_posix() for path in non_json]}"
        )

    report = {
        "schema": MANIFEST_SCHEMA,
        "scope_mode": manifest["scope"]["mode"],
        "scope_id": manifest["scope"]["id"],
        "manifest_inventory_revision": manifest["scope"]["inventory"]["revision"],
        "indexed_parity_input_files": len(indexed_inputs),
        "indexed_benchmark_input_files": len(benchmark_inputs),
        "cases": len(cases),
        "target_profiles": len(manifest["target_profiles"]),
        "operations": sum(len(surface["operations"]) for surface in manifest["surfaces"]),
        "native_operations": sum(
            len(surface["operations"]) for surface in manifest["native_surfaces"]
        ),
        "parity_requirements": sum(
            requirement["lanes"] == ["parity"]
            for surface in _all_manifest_surfaces(manifest)
            for operation in surface["operations"]
            for requirement in operation["requirements"]
        ),
        "parity_tooling_sources_compiled": source_count,
        "source_checkout_checked": False,
        "parity_passes_claimed": 0,
    }
    if scope_completeness is not None:
        report["full_scope_completeness"] = scope_completeness
    return report


def _find_case(cases: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    selected = [case for case in cases if case["case_id"] == case_id]
    if len(selected) != 1:
        raise ContractError(f"case ID must resolve exactly once: {case_id}")
    return selected[0]


def _find_operation(manifest: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return next(
        operation
        for surface in _all_manifest_surfaces(manifest)
        for operation in surface["operations"]
        if surface["id"] == case["surface"] and operation["id"] == case["operation"]
    )


def _load_workflow(path: Path, case_id: str, context: str) -> dict[str, Any]:
    value = load_json(path)
    return validate_workflow_result(value, case_id, context)


def _lane_empty(root: Path, manifest_path: Path | None, lane: str) -> int:
    manifest = load_manifest(_manifest_path(root, manifest_path))
    validate_manifest(manifest)
    if manifest["input_index"][lane]:
        if lane == "benchmark":
            print(
                json.dumps(
                    {
                        "lane": "benchmark",
                        "status": "not_run",
                        "reason": "the direct-ASGI workload is indexed, but no in-process benchmark timer is implemented",
                    },
                    sort_keys=True,
                )
            )
            return 2
        raise ContractError(
            f"{lane} inputs are present but this CLI does not execute that evidence lane"
        )
    for surface in _all_manifest_surfaces(manifest):
        for operation in surface["operations"]:
            if operation[lane]["applicability"] != "not_applicable":
                raise ContractError(
                    f"{lane} is required by operation {surface['id']}.{operation['id']}"
                )
    print(f"{lane}: not applicable in this slice; no execution evidence or pass is reported")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            report = validate_repository(args.root, args.manifest, args.upstream)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "validate-contract":
            report = validate_contract_repository(args.root, args.manifest)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "prepare-env":
            report = prepare_environments(
                args.root, _upstream_path(args.upstream), args.python, args.force
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command == "inventory-slice":
            root = args.root.resolve()
            manifest = load_manifest(_manifest_path(root, args.manifest))
            validate_manifest(manifest)
            scope_completeness = None
            if manifest["scope"]["mode"] == "full":
                metadata = load_api_metadata(root)
                validate_api_sources(manifest, metadata)
                indexed_inputs, cases = validate_inputs(root, manifest)
                scope_completeness = validate_full_scope_completeness(
                    root, manifest, indexed_inputs, cases, _upstream_path(args.upstream)
                )
            report = {"scope": manifest["scope"], "surfaces": manifest["surfaces"]}
            if scope_completeness is not None:
                report["full_scope_completeness"] = scope_completeness
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command in {"run", "oracle-only"}:
            root = args.root.resolve()
            output = args.output
            if output is None and args.case_ids:
                output = root / "build/parity/parity-selected-result.json"
            result = run_parity(
                root,
                "parity" if args.command == "run" else "oracle-only",
                output,
                _manifest_path(root, args.manifest),
                args.case_ids,
            )
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "summary": result["summary"],
                        "result": str(output or (root / "build/parity/parity-result.json")),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            summary = result["summary"]
            if (
                result["status"] != "completed"
                or summary["failed"]
                or summary["infrastructure_errors"]
                or summary["fault_contracts"]["failed"]
            ):
                return 2
            if args.command == "run" and (
                summary["not_run"] or summary["fault_contracts"]["not_run"]
            ):
                return 2
            return 0
        if args.command == "compare":
            root = args.root.resolve()
            manifest = load_manifest(_manifest_path(root, args.manifest))
            validate_manifest(manifest)
            _, cases = validate_inputs(root, manifest)
            case = _find_case(cases, args.case_id)
            source = _load_workflow(args.source, args.case_id, "source workflow")
            target = _load_workflow(args.target, args.case_id, "target workflow")
            status, diffs = compare_workflows(case, _find_operation(manifest, case), source, target)
            comparison = {
                "case_id": case["case_id"],
                "requirements": case["covers"],
                "outcome": status,
                "diffs": diffs,
            }
            print(json.dumps(comparison, indent=2, sort_keys=True))
            return 0 if status == "pass" else 1
        if args.command == "coverage":
            root = args.root.resolve()
            result = run_coverage(
                root,
                _manifest_path(root, args.manifest),
                target_profile=args.target_profile,
                case_ids=args.case_id,
            )
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "summary": result["summary"],
                        "result": result.get("artifact_path"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            summary = result["summary"]
            coverage_execution_succeeded = (
                result["status"] in {"completed", "not_ingested"}
                and summary["plans_selected"] > 0
                and summary["plans_executed"] == summary["plans_selected"]
                and summary["plans_not_run"] == 0
                and summary["tests_failed"] == 0
                and not result["infrastructure_errors"]
                and summary["tests_passed"]
                == sum(plan["execution"]["tests_passed"] for plan in result["plans"])
                and summary["tests_failed"]
                == sum(plan["execution"]["tests_failed"] for plan in result["plans"])
                and all(
                    plan["execution"]["status"] == "completed"
                    and plan["execution"]["tests_passed"] + plan["execution"]["tests_failed"]
                    == len(plan["selected"]["parity_case_ids"])
                    for plan in result["plans"]
                )
            )
            return 0 if coverage_execution_succeeded else 2
        if args.command == "benchmark":
            result = run_benchmark(
                args.root.resolve(), _manifest_path(args.root.resolve(), args.manifest)
            )
            summary = result["summary"]
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "summary": summary,
                        "result": str(args.root.resolve() / "build/parity/benchmark-result.json"),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if result["status"] == "completed" else 2
        if args.command == "benchmark-upstream":
            result = run_upstream_benchmark(
                args.root.resolve(), _manifest_path(args.root.resolve(), args.manifest)
            )
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "summary": result["summary"],
                        "result": str(args.root.resolve() / UPSTREAM_RESULT_RELATIVE),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if result["status"] == "completed" else 2
        if args.command == "aggregate":
            active_root = args.root.resolve()
            active_manifest = _manifest_path(active_root, args.manifest)
            output_path = _aggregate_output_path(active_root, args.output)
            if output_path in {path.resolve() for path in args.results}:
                raise ContractError("aggregate output cannot overwrite a supplied result artifact")
            report = _aggregate_parity_results(active_root, active_manifest, args.results)
            report["artifact_path"] = output_path.relative_to(active_root).as_posix()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
            return 0 if report["parity_matrix"]["status"] == "proven" else 2
        if args.command == "reconcile":
            active_root = args.root.resolve()
            active_manifest = _manifest_path(active_root, args.manifest)
            output_path = args.output or active_root / "build/parity/reconciled-parity-report.json"
            if not output_path.is_absolute():
                output_path = active_root / output_path
            output_path = output_path.resolve()
            try:
                output_path.relative_to((active_root / "build/parity").resolve())
            except ValueError as exc:
                raise ContractError(
                    "reconciliation output must be inside ignored build/parity"
                ) from exc
            input_paths = {path.resolve() for path in (*args.baseline, *args.supplement)}
            if output_path in input_paths:
                raise ContractError(
                    "reconciliation output cannot overwrite a supplied result artifact"
                )
            report = reconcile_parity_results(
                active_root,
                active_manifest,
                args.baseline,
                args.supplement,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
            return 0 if report["parity_matrix"]["status"] == "passed" else 2
        raise ContractError(f"unsupported command: {args.command}")
    except (ContractError, OSError, ValueError) as exc:
        print(f"parity contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
