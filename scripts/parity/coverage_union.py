"""Validate and aggregate the active six-profile Starlette coverage evidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .contract import ContractError, load_json, sha256_file, validate_manifest
from .coverage import CARGO_LLVM_COV_VERSION, _validate_schema_value
from .envs import _target_source_identity, python_version_from_runtime

UNION_RESULT_SCHEMA = "migration-parity/coverage-union-result@1"
RECEIPT_SCHEMA = "migration-parity/coverage-receipt@1"
COVERAGE_RESULT_SCHEMA = "migration-parity/coverage-result@1"
MANIFEST_PATH = Path("tests/fixtures/manifest.yaml")
DEFAULT_INPUT_ROOT = Path("build/parity/coverage/profiles")
DEFAULT_OUTPUT_PATH = Path("build/parity/coverage/coverage-union-result.json")
EXPECTED_PROFILE_COUNT = 6
_SHA256_LENGTH = 64


def _fail(message: str) -> ContractError:
    return ContractError(message)


def _require_keys(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(f"{context} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise _fail(f"{context} fields differ from contract: missing={missing}, extra={extra}")
    return value


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise _fail(f"{context} must be a non-empty string")
    return value


def _require_digest(value: Any, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _fail(f"{context} must be a lowercase SHA-256 digest")
    return value


def _load_strict_json(path: Path, context: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise _fail(f"{context} contains a duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail(f"cannot read {context}: {exc}") from exc


def _repo_file(root: Path, relative_value: Any, context: str) -> Path:
    relative = Path(_require_string(relative_value, f"{context}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise _fail(f"{context}.path must be repository-relative")
    path = root / relative
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise _fail(f"{context}.path cannot contain a symlink: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise _fail(f"{context}.path is missing or outside the repository: {relative}") from exc
    if not resolved.is_file():
        raise _fail(f"{context}.path is not a regular file: {relative}")
    return resolved


def _run_file(run_dir: Path, relative_value: Any, context: str) -> Path:
    relative = Path(_require_string(relative_value, f"{context}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise _fail(f"{context}.path must be relative to the coverage run directory")
    path = run_dir / relative
    candidate = run_dir
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise _fail(f"{context}.path cannot contain a symlink: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(run_dir.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise _fail(f"{context}.path is missing or escapes its run directory: {relative}") from exc
    if not resolved.is_file():
        raise _fail(f"{context}.path is not a regular file: {relative}")
    return resolved


def _verify_digest(path: Path, expected: Any, context: str) -> str:
    expected_digest = _require_digest(expected, f"{context}.sha256")
    actual_digest = sha256_file(path)
    if actual_digest != expected_digest:
        raise _fail(f"{context} digest does not match its file: {path}")
    return actual_digest


def _manifest_contract(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    manifest_file = _repo_file(root, MANIFEST_PATH.as_posix(), "active manifest")
    manifest = load_json(manifest_file)
    if not isinstance(manifest, dict):
        raise _fail("active manifest must be an object")
    validate_manifest(manifest)

    target_profiles = manifest.get("target_profiles")
    components = manifest.get("coverage_components")
    input_index = manifest.get("input_index")
    if not isinstance(target_profiles, list) or not target_profiles:
        raise _fail("active manifest must declare target profiles")
    if not isinstance(components, list) or not components:
        raise _fail("active manifest must declare coverage components")
    if not isinstance(input_index, dict) or not isinstance(input_index.get("coverage"), list):
        raise _fail("active manifest must index coverage input documents")

    profile_ids: list[str] = []
    for profile in target_profiles:
        if not isinstance(profile, dict):
            raise _fail("target profile entries must be objects")
        profile_id = _require_string(profile.get("id"), "target profile id")
        if profile_id in profile_ids:
            raise _fail(f"active manifest repeats target profile: {profile_id}")
        profile_ids.append(profile_id)
    if len(profile_ids) != EXPECTED_PROFILE_COUNT:
        raise _fail(
            f"active manifest must provide exactly six coverage profiles; found {len(profile_ids)}"
        )

    component_profiles: set[str] = set()
    eligible_paths: set[str] = set()
    component_ids: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise _fail("coverage component entries must be objects")
        component_id = _require_string(component.get("id"), "coverage component id")
        if component_id in component_ids:
            raise _fail(f"active manifest repeats coverage component: {component_id}")
        component_ids.add(component_id)
        profile_id = _require_string(component.get("target_profile"), "component target_profile")
        component_profiles.add(profile_id)
        paths = component.get("paths")
        if not isinstance(paths, list) or not paths:
            raise _fail(f"coverage component {component_id} must declare source paths")
        for path_value in paths:
            relative = Path(_require_string(path_value, f"coverage component {component_id} path"))
            if relative.is_absolute() or ".." in relative.parts:
                raise _fail(f"coverage component {component_id} has an unsafe source path")
            relative_text = relative.as_posix()
            source_path = _repo_file(root, relative_text, f"coverage component {component_id}")
            if source_path.is_symlink():
                raise _fail(f"coverage source path cannot be a symlink: {relative_text}")
            eligible_paths.add(relative_text)

    if component_profiles != set(profile_ids):
        raise _fail(
            "coverage components and target profiles differ: "
            f"missing_components={sorted(set(profile_ids) - component_profiles)}, "
            f"unknown_profiles={sorted(component_profiles - set(profile_ids))}"
        )
    if not eligible_paths:
        raise _fail("active manifest yields no eligible coverage source paths")

    coverage_inputs = input_index["coverage"]
    if len(coverage_inputs) != 1:
        raise _fail("active manifest must index exactly one full coverage input")
    input_relative = Path(_require_string(coverage_inputs[0], "coverage input path"))
    expected_prefix = Path("build/parity/inputs/coverage")
    if input_relative.is_absolute() or ".." in input_relative.parts:
        raise _fail("generated coverage input path must be repository-relative")
    if input_relative.parts[: len(expected_prefix.parts)] != expected_prefix.parts:
        raise _fail("generated coverage input must be under build/parity/inputs/coverage")
    coverage_input_file = _repo_file(root, input_relative.as_posix(), "generated coverage input")
    coverage_document = load_json(coverage_input_file)
    if not isinstance(coverage_document, dict) or coverage_document.get("schema") != (
        "migration-parity/coverage-input@1"
    ):
        raise _fail("generated coverage input has an unsupported schema")
    plans = coverage_document.get("plans")
    if not isinstance(plans, list):
        raise _fail("generated coverage input plans must be an array")
    expected_plans: dict[str, dict[str, Any]] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            raise _fail("coverage input plan entries must be objects")
        profile_id = _require_string(plan.get("target_profile"), "coverage plan target_profile")
        if profile_id not in profile_ids or profile_id in expected_plans:
            raise _fail(f"coverage input repeats or has an unknown profile: {profile_id}")
        selectors = plan.get("selectors")
        if not isinstance(selectors, dict):
            raise _fail(f"coverage plan for {profile_id} must declare selectors")
        case_ids = selectors.get("parity_case_ids")
        command_ids = selectors.get("command_ids")
        component_list = plan.get("component_ids")
        if (
            not isinstance(case_ids, list)
            or not case_ids
            or not all(isinstance(case_id, str) and case_id for case_id in case_ids)
            or len(case_ids) != len(set(case_ids))
        ):
            raise _fail(f"coverage plan for {profile_id} has invalid parity case selectors")
        if command_ids != []:
            raise _fail(f"coverage plan for {profile_id} must not select command cases")
        expected_component_ids = [
            component["id"] for component in components if component["target_profile"] == profile_id
        ]
        if component_list != expected_component_ids:
            raise _fail(f"coverage plan component selection differs from manifest for {profile_id}")
        expected_plans[profile_id] = plan
    if set(expected_plans) != set(profile_ids):
        raise _fail(
            "coverage input must provide one plan per declared profile: "
            f"missing={sorted(set(profile_ids) - set(expected_plans))}"
        )

    manifest_identity = {
        "path": MANIFEST_PATH.as_posix(),
        "schema": manifest.get("schema"),
        "sha256": sha256_file(manifest_file),
    }
    if not isinstance(manifest_identity["schema"], str):
        raise _fail("active manifest schema must be a string")
    return manifest, expected_plans, sorted(eligible_paths)


def _file_record(root: Path, value: Any, context: str) -> tuple[dict[str, Any], Path]:
    record = _require_keys(value, {"path", "sha256"}, context)
    path = _repo_file(root, record["path"], context)
    _verify_digest(path, record["sha256"], context)
    return record, path


def _verify_identity_files(root: Path, receipt: dict[str, Any]) -> None:
    for field in ("manifest",):
        record = _require_keys(receipt[field], {"path", "schema", "sha256"}, field)
        path = _repo_file(root, record["path"], field)
        _verify_digest(path, record["sha256"], field)
        if field == "manifest" and record["path"] != MANIFEST_PATH.as_posix():
            raise _fail("receipt manifest path differs from the active manifest")

    for field in ("inputs", "assets"):
        records = receipt[field]
        if not isinstance(records, list):
            raise _fail(f"receipt {field} must be an array")
        seen_records: set[tuple[str, ...]] = set()
        for index, record_value in enumerate(records):
            if field == "inputs":
                record = _require_keys(
                    record_value, {"path", "schema", "sha256"}, f"{field}[{index}]"
                )
                relative = _require_string(record["path"], f"{field}[{index}].path")
                path = _repo_file(root, relative, f"{field}[{index}]")
                _verify_digest(path, record["sha256"], f"{field}[{index}]")
                _require_string(record["schema"], f"{field}[{index}].schema")
                record_key = (relative,)
            else:
                record = _require_keys(
                    record_value,
                    {"input_path", "item_id", "asset_id", "kind", "locator", "sha256"},
                    f"{field}[{index}]",
                )
                relative = _require_string(record["input_path"], f"{field}[{index}].input_path")
                if relative not in {item["path"] for item in receipt["inputs"]}:
                    raise _fail(f"receipt asset references an unrecorded input: {relative}")
                for item_key in ("item_id", "asset_id", "kind", "locator"):
                    _require_string(record[item_key], f"{field}[{index}].{item_key}")
                _require_digest(record["sha256"], f"{field}[{index}].sha256")
                record_key = (
                    relative,
                    record["item_id"],
                    record["asset_id"],
                    record["locator"],
                )
            if record_key in seen_records:
                raise _fail(f"receipt {field} repeats an identity: {record_key}")
            seen_records.add(record_key)


def _verify_dependency_locks(
    root: Path, receipts: dict[str, dict[str, Any]], native_profile_ids: set[str]
) -> None:
    identities: dict[str, dict[str, tuple[str, str]]] = {}
    for profile_id, receipt in receipts.items():
        locks = receipt["dependency_locks"]
        if not isinstance(locks, list) or len(locks) != 3:
            raise _fail(
                f"receipt dependency_locks must contain build, oracle, and target for {profile_id}"
            )
        by_purpose: dict[str, tuple[str, str]] = {}
        for index, item_value in enumerate(locks):
            item = _require_keys(
                item_value,
                {"purpose", "path", "sha256"},
                f"{profile_id}.dependency_locks[{index}]",
            )
            purpose = _require_string(item["purpose"], "dependency lock purpose")
            if purpose not in {"build", "oracle", "target"} or purpose in by_purpose:
                raise _fail(
                    f"receipt has duplicate or unknown dependency lock purpose for {profile_id}"
                )
            path = _repo_file(root, item["path"], f"{profile_id}.{purpose} dependency lock")
            digest = _verify_digest(path, item["sha256"], f"{profile_id}.{purpose} dependency lock")
            by_purpose[purpose] = (item["path"], digest)
        if set(by_purpose) != {"build", "oracle", "target"}:
            raise _fail(
                f"receipt does not include all three dependency lock purposes for {profile_id}"
            )
        identities[profile_id] = by_purpose

    profile_ids = list(receipts)
    first_profile = profile_ids[0]
    for profile_id in profile_ids[1:]:
        for purpose in ("build", "oracle"):
            if identities[profile_id][purpose] != identities[first_profile][purpose]:
                raise _fail(f"{purpose} dependency lock differs between coverage profiles")
    python_profiles = [
        profile_id for profile_id in profile_ids if profile_id not in native_profile_ids
    ]
    if python_profiles:
        first_python = python_profiles[0]
        for profile_id in python_profiles[1:]:
            if identities[profile_id]["target"] != identities[first_python]["target"]:
                raise _fail("target dependency lock differs between CPython coverage profiles")


def _verify_toolchain_identity(profiles: list[dict[str, Any]]) -> None:
    tool_names = ("cargo", "cargo_llvm_cov", "rustc", "llvm_cov", "llvm_profdata")
    if not profiles:
        raise _fail("coverage receipts contain no toolchain identities")
    baseline = profiles[0]["toolchain_identity"]
    for profile in profiles[1:]:
        identity = profile["toolchain_identity"]
        differing = [name for name in tool_names if identity[name] != baseline[name]]
        if differing:
            raise _fail(f"coverage toolchain identity differs between profiles for: {differing}")


def _receipt_candidates(input_root: Path, expected_profile_ids: list[str]) -> dict[str, Path]:
    try:
        root = input_root.resolve(strict=True)
    except OSError as exc:
        raise _fail(f"coverage profile artifact directory is missing: {input_root}") from exc
    if not root.is_dir() or input_root.is_symlink():
        raise _fail("coverage profile artifact root must be a regular directory")
    candidates = sorted(root.rglob("coverage-receipt.json"))
    found: dict[str, Path] = {}
    for path in candidates:
        if path.is_symlink():
            raise _fail(f"coverage receipt cannot be a symlink: {path}")
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise _fail(f"coverage receipt escapes the artifact root: {path}") from exc
        document = _load_strict_json(path, "coverage receipt")
        if not isinstance(document, dict):
            raise _fail(f"coverage receipt must be an object: {path}")
        profile_id = _require_string(document.get("profile_id"), "coverage receipt profile_id")
        if profile_id not in expected_profile_ids:
            raise _fail(f"unexpected coverage receipt profile: {profile_id}")
        if profile_id in found:
            raise _fail(f"multiple coverage receipts found for profile: {profile_id}")
        found[profile_id] = path.resolve()
    if set(found) != set(expected_profile_ids):
        raise _fail(
            "coverage receipts do not match active manifest profiles: "
            f"missing={sorted(set(expected_profile_ids) - set(found))}"
        )
    return found


def _verify_receipt(
    root: Path,
    profile_id: str,
    receipt_path: Path,
    manifest_identity: dict[str, str],
    target_identity: dict[str, Any],
    target_profile: dict[str, Any],
    target_definition: dict[str, Any],
    expected_plan: dict[str, Any],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt = _load_strict_json(receipt_path, f"{profile_id} coverage receipt")
    keys = {
        "schema",
        "profile_id",
        "target",
        "source",
        "manifest",
        "inputs",
        "assets",
        "dependency_locks",
        "target_artifact",
        "collector",
        "raw_profiles",
        "outputs",
        "selected_outcomes",
    }
    _require_keys(receipt, keys, f"{profile_id} coverage receipt")
    if receipt["schema"] != RECEIPT_SCHEMA or receipt["profile_id"] != profile_id:
        raise _fail(f"coverage receipt schema or profile id mismatch for {profile_id}")
    receipt_schema = load_json(root / "tests/fixtures/coverage-receipt-schema.json")
    if not isinstance(receipt_schema, dict):
        raise _fail("coverage-receipt-schema.json must be an object")
    _validate_schema_value(receipt, receipt_schema, receipt_schema, f"{profile_id} receipt")

    target = _require_keys(receipt["target"], {"revision", "dirty"}, f"{profile_id}.target")
    _require_string(target["revision"], f"{profile_id}.target.revision")
    if type(target["dirty"]) is not bool:
        raise _fail(f"{profile_id}.target.dirty must be a boolean")
    if target != {"revision": target_identity["revision"], "dirty": target_identity["dirty"]}:
        raise _fail(f"{profile_id} target revision/dirty state differs from the current checkout")

    source = _require_keys(receipt["source"], {"tree_sha256"}, f"{profile_id}.source")
    tree_digest = _require_digest(source["tree_sha256"], f"{profile_id}.source.tree_sha256")
    if tree_digest != target_identity["working_tree_sha256"]:
        raise _fail(f"{profile_id} source tree digest differs from the current checkout")

    manifest_record = _require_keys(
        receipt["manifest"], {"path", "schema", "sha256"}, f"{profile_id}.manifest"
    )
    if manifest_record != manifest_identity:
        raise _fail(f"{profile_id} manifest identity differs from the active manifest")
    _verify_identity_files(root, receipt)

    run_dir = receipt_path.parent.resolve(strict=True)
    target_artifact = _require_keys(
        receipt["target_artifact"], {"kind", "path", "sha256"}, f"{profile_id}.target_artifact"
    )
    _require_string(target_artifact["kind"], f"{profile_id}.target_artifact.kind")
    if target_profile["python_version"] is None:
        expected_artifact_kind = "rust-native-executable"
        expected_artifact_directory = "target-artifact"
    else:
        expected_artifact_kind = "python-extension-module"
        expected_artifact_directory = "python-overlay/starlette_rs_py"
    artifact_relative_path = Path(
        _require_string(target_artifact["path"], f"{profile_id}.target_artifact.path")
    )
    if (
        target_artifact["kind"] != expected_artifact_kind
        or artifact_relative_path.parent.as_posix() != expected_artifact_directory
        or not artifact_relative_path.name
    ):
        raise _fail(f"{profile_id} target artifact kind or path differs from its manifest profile")
    artifact_path = _run_file(run_dir, target_artifact["path"], f"{profile_id}.target_artifact")
    artifact_digest = _verify_digest(
        artifact_path, target_artifact["sha256"], f"{profile_id}.target_artifact"
    )

    collector = _require_keys(
        receipt["collector"],
        {"name", "version", "configuration", "logs", "toolchain"},
        f"{profile_id}.collector",
    )
    if collector["name"] != "cargo-llvm-cov":
        raise _fail(f"{profile_id} used an unexpected coverage collector")
    if collector["version"] != CARGO_LLVM_COV_VERSION:
        raise _fail(
            f"{profile_id} collector version must be cargo-llvm-cov {CARGO_LLVM_COV_VERSION}"
        )
    configuration = _require_keys(
        collector["configuration"], {"path", "sha256"}, f"{profile_id}.collector.configuration"
    )
    configuration_path = _run_file(
        run_dir, configuration["path"], f"{profile_id}.collector.configuration"
    )
    _verify_digest(
        configuration_path, configuration["sha256"], f"{profile_id}.collector.configuration"
    )
    logs = _require_keys(
        collector["logs"], {"build", "report", "show_env"}, f"{profile_id}.collector.logs"
    )
    for log_name, log_value in logs.items():
        log = _require_keys(
            log_value, {"path", "sha256"}, f"{profile_id}.collector.logs.{log_name}"
        )
        log_path = _run_file(run_dir, log["path"], f"{profile_id}.collector.logs.{log_name}")
        _verify_digest(log_path, log["sha256"], f"{profile_id}.collector.logs.{log_name}")
    toolchain = _require_keys(
        collector["toolchain"],
        {"path", "sha256", "cargo", "cargo_llvm_cov", "rustc", "llvm_cov", "llvm_profdata"},
        f"{profile_id}.collector.toolchain",
    )
    toolchain_path = _run_file(run_dir, toolchain["path"], f"{profile_id}.collector.toolchain")
    _verify_digest(toolchain_path, toolchain["sha256"], f"{profile_id}.collector.toolchain")
    for tool_name in ("cargo", "cargo_llvm_cov", "rustc", "llvm_cov", "llvm_profdata"):
        _require_string(toolchain[tool_name], f"{profile_id}.collector.toolchain.{tool_name}")
    if toolchain["cargo_llvm_cov"] != f"cargo-llvm-cov {CARGO_LLVM_COV_VERSION}":
        raise _fail(
            f"{profile_id} toolchain does not identify cargo-llvm-cov {CARGO_LLVM_COV_VERSION}"
        )

    raw_profiles = receipt["raw_profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise _fail(f"{profile_id} receipt must list raw profiling data")
    for index, raw_value in enumerate(raw_profiles):
        raw = _require_keys(
            raw_value,
            {"path", "sha256", "size_bytes"},
            f"{profile_id}.raw_profiles[{index}]",
        )
        if type(raw["size_bytes"]) is not int or raw["size_bytes"] < 1:
            raise _fail(f"{profile_id}.raw_profiles[{index}].size_bytes must be a positive integer")
        raw_path = _run_file(run_dir, raw["path"], f"{profile_id}.raw_profiles[{index}]")
        if raw_path.stat().st_size != raw["size_bytes"]:
            raise _fail(f"{profile_id}.raw_profiles[{index}] size differs from its file")
        _verify_digest(raw_path, raw["sha256"], f"{profile_id}.raw_profiles[{index}]")

    outputs = _require_keys(
        receipt["outputs"], {"lcov", "coverage_result"}, f"{profile_id}.outputs"
    )
    output_files: dict[str, tuple[Path, str]] = {}
    for output_name, output_value in outputs.items():
        output = _require_keys(
            output_value, {"path", "sha256"}, f"{profile_id}.outputs.{output_name}"
        )
        output_path = _run_file(run_dir, output["path"], f"{profile_id}.outputs.{output_name}")
        output_digest = _verify_digest(
            output_path, output["sha256"], f"{profile_id}.outputs.{output_name}"
        )
        output_files[output_name] = (output_path, output_digest)

    dependency_locks = receipt["dependency_locks"]
    if not isinstance(dependency_locks, list):
        raise _fail(f"{profile_id}.dependency_locks must be an array")

    outcomes = receipt["selected_outcomes"]
    expected_case_ids = expected_plan["selectors"]["parity_case_ids"]
    if not isinstance(outcomes, list) or len(outcomes) != len(expected_case_ids):
        raise _fail(f"{profile_id} selected outcome count differs from the active coverage plan")
    for index, (outcome_value, expected_case_id) in enumerate(
        zip(outcomes, expected_case_ids, strict=True)
    ):
        outcome = _require_keys(
            outcome_value, {"case_id", "outcome"}, f"{profile_id}.selected_outcomes[{index}]"
        )
        if outcome["case_id"] != expected_case_id:
            raise _fail(f"{profile_id} selected case order differs from the active coverage plan")
        if outcome["outcome"] != "pass":
            raise _fail(
                f"{profile_id} case {expected_case_id} did not pass: {outcome['outcome']!r}"
            )

    coverage_result_path, coverage_result_digest = output_files["coverage_result"]
    coverage_result = _load_strict_json(coverage_result_path, f"{profile_id} coverage result")
    _validate_coverage_result(
        root,
        profile_id,
        coverage_result,
        manifest_identity,
        receipt,
        expected_plan,
        components,
        len(expected_case_ids),
        target_profile,
        target_definition,
        target_identity,
        {
            name: toolchain[name]
            for name in ("cargo", "cargo_llvm_cov", "rustc", "llvm_cov", "llvm_profdata")
        },
    )

    return {
        "profile_id": profile_id,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "receipt_sha256": sha256_file(receipt_path),
        "target_artifact": {
            "kind": target_artifact["kind"],
            "sha256": artifact_digest,
        },
        "coverage_result": coverage_result,
        "coverage_result_sha256": coverage_result_digest,
        "lcov_path": output_files["lcov"][0],
        "lcov_sha256": output_files["lcov"][1],
        "case_count": len(expected_case_ids),
        "toolchain_identity": {
            name: toolchain[name]
            for name in ("cargo", "cargo_llvm_cov", "rustc", "llvm_cov", "llvm_profdata")
        },
    }


def _validate_coverage_result(
    root: Path,
    profile_id: str,
    result: Any,
    manifest_identity: dict[str, str],
    receipt: dict[str, Any],
    expected_plan: dict[str, Any],
    components: list[dict[str, Any]],
    case_count: int,
    target_profile: dict[str, Any],
    target_definition: dict[str, Any],
    target_identity: dict[str, Any],
    toolchain_identity: dict[str, str],
) -> None:
    if not isinstance(result, dict) or result.get("schema") != COVERAGE_RESULT_SCHEMA:
        raise _fail(f"{profile_id} coverage result has an unsupported schema")
    schema_path = root / "tests/fixtures/coverage-result-schema.json"
    schema = load_json(schema_path)
    if not isinstance(schema, dict):
        raise _fail("coverage-result-schema.json must be an object")
    _validate_schema_value(result, schema, schema, f"{profile_id} coverage result")
    if result["collector"]["version"] != CARGO_LLVM_COV_VERSION:
        raise _fail(
            f"{profile_id} coverage result collector version must be "
            f"cargo-llvm-cov {CARGO_LLVM_COV_VERSION}"
        )
    if result.get("status") != "not_ingested" or result.get("infrastructure_errors") != []:
        raise _fail(f"{profile_id} coverage result is not cleanly bound to its receipt")
    identity = result.get("identity")
    if not isinstance(identity, dict) or identity.get("manifest") != manifest_identity:
        raise _fail(f"{profile_id} coverage result manifest identity differs")
    if identity.get("inputs") != receipt["inputs"] or identity.get("assets") != receipt["assets"]:
        raise _fail(f"{profile_id} receipt inputs/assets differ from its coverage result")
    targets = identity.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        raise _fail(f"{profile_id} coverage result must have exactly one target identity")
    target = targets[0]
    if (
        not isinstance(target, dict)
        or target.get("target_profile") != profile_id
        or type(target.get("dirty")) is not bool
        or target.get("dirty") != receipt["target"]["dirty"]
    ):
        raise _fail(f"{profile_id} coverage result target identity differs from its receipt")
    revision = target.get("revision")
    current_revision = target_identity["revision"]
    if revision != current_revision and not (
        isinstance(revision, str) and revision.startswith(f"{current_revision}+")
    ):
        raise _fail(
            f"{profile_id} coverage result target revision differs from the current checkout"
        )
    if (
        target.get("target_id") != target_profile["target_id"]
        or target.get("dirty") != target_identity["dirty"]
        or target.get("backend") != target_profile["backend"]
        or target.get("features") != target_profile["features"]
    ):
        raise _fail(f"{profile_id} coverage result target profile metadata differs from manifest")
    runtime = _require_string(target.get("runtime"), f"{profile_id} coverage target runtime")
    declared_runtime = _require_string(target_definition.get("runtime"), "manifest target runtime")
    python_version = target_profile["python_version"]
    if python_version is None:
        rustc_version = toolchain_identity["rustc"].splitlines()[0]
        if "rust" not in declared_runtime.lower() or not runtime.startswith(f"{rustc_version} ("):
            raise _fail(f"{profile_id} coverage target runtime differs from manifest/toolchain")
    elif (
        "cpython" not in declared_runtime.lower()
        or python_version_from_runtime(runtime) != python_version
    ):
        raise _fail(f"{profile_id} coverage target runtime differs from its manifest profile")

    summary = result.get("summary")
    if (
        not isinstance(summary, dict)
        or any(
            type(summary.get(name)) is not int
            for name in (
                "plans_selected",
                "plans_executed",
                "plans_not_run",
                "tests_passed",
                "tests_failed",
            )
        )
        or summary.get("plans_selected") != 1
        or summary.get("plans_executed") != 1
        or summary.get("plans_not_run") != 0
        or summary.get("tests_passed") != case_count
        or summary.get("tests_failed") != 0
    ):
        raise _fail(
            f"{profile_id} coverage result summary does not prove all selected cases passed"
        )

    plans = result.get("plans")
    if not isinstance(plans, list) or len(plans) != 1:
        raise _fail(f"{profile_id} coverage result must contain one plan")
    plan = plans[0]
    if not isinstance(plan, dict) or plan.get("target_profile") != profile_id:
        raise _fail(f"{profile_id} coverage result plan profile differs")
    if plan.get("plan_id") != expected_plan.get("plan_id"):
        raise _fail(f"{profile_id} coverage result plan id differs from active manifest input")
    selected = plan.get("selected")
    if (
        not isinstance(selected, dict)
        or selected.get("parity_case_ids") != expected_plan["selectors"]["parity_case_ids"]
        or selected.get("command_ids") != []
    ):
        raise _fail(f"{profile_id} coverage result case selection differs from active plan")
    execution = plan.get("execution")
    if (
        not isinstance(execution, dict)
        or any(type(execution.get(name)) is not int for name in ("tests_passed", "tests_failed"))
        or execution.get("status") != "completed"
        or execution.get("tests_passed") != case_count
        or execution.get("tests_failed") != 0
    ):
        raise _fail(f"{profile_id} coverage result plan execution has failures or is incomplete")

    expected_components = [
        component for component in components if component["target_profile"] == profile_id
    ]
    result_components = plan.get("components")
    if not isinstance(result_components, list):
        raise _fail(f"{profile_id} coverage result components must be an array")
    expected_component_ids = [component["id"] for component in expected_components]
    result_component_ids = [
        component.get("component_id") if isinstance(component, dict) else None
        for component in result_components
    ]
    if result_component_ids != expected_component_ids:
        raise _fail(f"{profile_id} coverage component results differ from the active manifest")


def _normalized_lcov_path(root: Path, source: str) -> str | None:
    value = source.replace("\\", "/")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _parse_lcov(path: Path, root: Path) -> dict[str, dict[int, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _fail(f"cannot read LCOV report {path}: {exc}") from exc
    files: dict[str, dict[int, int]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith("SF:"):
            current = _normalized_lcov_path(root, line[3:])
            if current is not None:
                files.setdefault(current, {})
        elif line.startswith("DA:") and current is not None:
            fields = line[3:].split(",")
            if len(fields) < 2 or not fields[0].isdigit() or not fields[1].isdigit():
                raise _fail(f"malformed LCOV line record: {line[:200]}")
            line_number, count = int(fields[0]), int(fields[1])
            if line_number < 1:
                raise _fail("LCOV line numbers must be positive")
            if count >= 2**63:
                count = 0
            previous = files[current].get(line_number)
            files[current][line_number] = count if previous is None else max(previous, count)
        elif line == "end_of_record":
            current = None
    return files


def _component_line_maps(
    profile_id: str,
    result: dict[str, Any],
    lcov: dict[str, dict[int, int]],
    components: list[dict[str, Any]],
) -> dict[str, dict[int, int]]:
    expected_components = [
        component for component in components if component["target_profile"] == profile_id
    ]
    result_components = result["plans"][0]["components"]
    maps: dict[str, dict[int, int]] = {}
    for expected, actual in zip(expected_components, result_components, strict=True):
        expected_paths = expected["paths"]
        files = actual.get("files")
        if not isinstance(files, list):
            raise _fail(f"{profile_id} component {expected['id']} file results must be an array")
        actual_paths = [
            file_row.get("path") if isinstance(file_row, dict) else None for file_row in files
        ]
        if actual_paths != expected_paths:
            raise _fail(f"{profile_id} component {expected['id']} file paths differ from manifest")
        for file_row in files:
            relative_path = file_row["path"]
            if relative_path not in lcov:
                raise _fail(f"{profile_id} LCOV report omitted eligible path: {relative_path}")
            dimensions = file_row.get("dimensions")
            if not isinstance(dimensions, list) or len(dimensions) != 1:
                raise _fail(
                    f"{profile_id} coverage result has invalid line dimensions for {relative_path}"
                )
            dimension = _require_keys(
                dimensions[0],
                {"dimension", "covered", "total", "uncovered"},
                f"{profile_id}.{relative_path}.dimension",
            )
            counts = lcov[relative_path]
            covered_lines = sorted(number for number, count in counts.items() if count > 0)
            uncovered_lines = sorted(number for number, count in counts.items() if count == 0)
            if dimension["dimension"] != "line":
                raise _fail(f"{profile_id} coverage result has a non-line dimension")
            expected_uncovered = [f"{relative_path}:{number}" for number in uncovered_lines]
            if (
                dimension["covered"] != len(covered_lines)
                or dimension["total"] != len(counts)
                or dimension["uncovered"] != expected_uncovered
            ):
                raise _fail(
                    f"{profile_id} coverage result line totals differ from LCOV for {relative_path}"
                )
            maps[relative_path] = counts
    return maps


def _line_summary(line_counts: dict[str, dict[int, int]]) -> dict[str, Any]:
    records = sorted(
        (path, line, count)
        for path, counts in line_counts.items()
        for line, count in counts.items()
    )
    total = len(records)
    covered = sum(count > 0 for _, _, count in records)
    uncovered = [f"{path}:{line}" for path, line, count in records if count == 0]
    return {
        "covered": covered,
        "total": total,
        "percent": round(covered * 100 / total, 4) if total else 0.0,
        "uncovered": uncovered,
    }


def _union_line_summary(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, dict[int, int]] = {}
    for profile in profiles:
        for path, counts in profile["line_counts"].items():
            destination = merged.setdefault(path, {})
            for line_number, count in counts.items():
                destination[line_number] = max(destination.get(line_number, 0), count)
    return _line_summary(merged)


def _validate_union_result(result: dict[str, Any]) -> None:
    _require_keys(
        result,
        {"schema", "status", "identity", "eligible", "profiles", "line"},
        "coverage union result",
    )
    if result["schema"] != UNION_RESULT_SCHEMA or result["status"] not in {"completed", "failed"}:
        raise _fail("coverage union result schema or status is invalid")
    identity = _require_keys(
        result["identity"], {"manifest", "target", "source_tree_sha256"}, "result.identity"
    )
    manifest = _require_keys(
        identity["manifest"], {"path", "schema", "sha256"}, "result.identity.manifest"
    )
    if (
        manifest["path"] != MANIFEST_PATH.as_posix()
        or not isinstance(manifest["schema"], str)
        or not _require_digest(manifest["sha256"], "result.identity.manifest.sha256")
    ):
        raise _fail("coverage union result manifest identity is invalid")
    target = _require_keys(identity["target"], {"revision", "dirty"}, "result.identity.target")
    _require_string(target["revision"], "result.identity.target.revision")
    if type(target["dirty"]) is not bool:
        raise _fail("result.identity.target.dirty must be a boolean")
    _require_digest(identity["source_tree_sha256"], "result.identity.source_tree_sha256")

    eligible = _require_keys(result["eligible"], {"path_count", "paths"}, "result.eligible")
    if (
        type(eligible["path_count"]) is not int
        or not isinstance(eligible["paths"], list)
        or eligible["path_count"] != len(eligible["paths"])
        or eligible["paths"] != sorted(set(eligible["paths"]))
        or not all(isinstance(path, str) and path for path in eligible["paths"])
    ):
        raise _fail("coverage union eligible path inventory is invalid")

    def validate_line_summary(value: Any, context: str) -> None:
        line = _require_keys(value, {"covered", "total", "percent", "uncovered"}, context)
        if (
            type(line["covered"]) is not int
            or type(line["total"]) is not int
            or line["covered"] < 0
            or line["total"] < line["covered"]
            or not isinstance(line["uncovered"], list)
            or not all(isinstance(location, str) and location for location in line["uncovered"])
            or line["uncovered"] != sorted(set(line["uncovered"]))
            or len(line["uncovered"]) != line["total"] - line["covered"]
            or type(line["percent"]) not in {int, float}
        ):
            raise _fail(f"{context} line totals are invalid")
        expected_percent = round(line["covered"] * 100 / line["total"], 4) if line["total"] else 0.0
        if line["percent"] != expected_percent:
            raise _fail(f"{context} line percentage differs from its totals")

    validate_line_summary(result["line"], "result.line")
    if (
        not isinstance(result["profiles"], list)
        or len(result["profiles"]) != EXPECTED_PROFILE_COUNT
    ):
        raise _fail("coverage union result must contain one row for each of the six profiles")
    profile_ids: set[str] = set()
    for index, profile in enumerate(result["profiles"]):
        _require_keys(
            profile,
            {
                "profile_id",
                "receipt_sha256",
                "target_artifact",
                "coverage_result_sha256",
                "lcov_sha256",
                "case_evidence",
                "line",
            },
            f"result.profiles[{index}]",
        )
        profile_id = _require_string(profile["profile_id"], f"result.profiles[{index}].profile_id")
        if profile_id in profile_ids:
            raise _fail(f"coverage union result repeats profile: {profile_id}")
        profile_ids.add(profile_id)
        for name in ("receipt_sha256", "coverage_result_sha256", "lcov_sha256"):
            _require_digest(profile[name], f"result.profiles[{index}].{name}")
        target_artifact = _require_keys(
            profile["target_artifact"],
            {"kind", "sha256"},
            f"result.profiles[{index}].target_artifact",
        )
        _require_string(target_artifact["kind"], f"result.profiles[{index}].target_artifact.kind")
        _require_digest(
            target_artifact["sha256"], f"result.profiles[{index}].target_artifact.sha256"
        )
        evidence = _require_keys(
            profile["case_evidence"],
            {"selected", "passed", "failed"},
            f"result.profiles[{index}].case_evidence",
        )
        if (
            any(type(evidence[name]) is not int for name in ("selected", "passed", "failed"))
            or evidence["selected"] < 1
            or evidence["passed"] != evidence["selected"]
            or evidence["failed"] != 0
        ):
            raise _fail(f"result.profiles[{index}] case evidence is invalid")
        validate_line_summary(profile["line"], f"result.profiles[{index}].line")

    expected_status = (
        "completed" if result["line"]["total"] > 0 and not result["line"]["uncovered"] else "failed"
    )
    if result["status"] != expected_status:
        raise _fail("coverage union result status differs from its line coverage totals")


def aggregate_coverage(root: Path, input_root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest, expected_plans, eligible_paths = _manifest_contract(root)
    profile_ids = [profile["id"] for profile in manifest["target_profiles"]]
    profiles_by_id = {profile["id"]: profile for profile in manifest["target_profiles"]}
    targets_by_id = {target["id"]: target for target in manifest["targets"]}
    manifest_file = root / MANIFEST_PATH
    manifest_identity = {
        "path": MANIFEST_PATH.as_posix(),
        "schema": manifest["schema"],
        "sha256": sha256_file(manifest_file),
    }
    current_target = _target_source_identity(root)
    native_profile_ids = {
        profile["id"]
        for profile in manifest["target_profiles"]
        if profile.get("python_version") is None
    }
    if len(native_profile_ids) != 1:
        raise _fail("active coverage manifest must identify exactly one Rust-native profile")

    receipt_paths = _receipt_candidates(input_root, profile_ids)
    receipts: dict[str, dict[str, Any]] = {}
    verified_profiles: list[dict[str, Any]] = []
    components = manifest["coverage_components"]
    for profile_id in profile_ids:
        verified = _verify_receipt(
            root,
            profile_id,
            receipt_paths[profile_id],
            manifest_identity,
            current_target,
            profiles_by_id[profile_id],
            targets_by_id[profiles_by_id[profile_id]["target_id"]],
            expected_plans[profile_id],
            components,
        )
        receipts[profile_id] = verified["receipt"]
        verified_profiles.append(verified)

    _verify_dependency_locks(root, receipts, native_profile_ids)
    _verify_toolchain_identity(verified_profiles)

    profile_rows: list[dict[str, Any]] = []
    covered_by_profile: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    for verified in verified_profiles:
        profile_id = verified["profile_id"]
        lcov = _parse_lcov(verified["lcov_path"], root)
        line_counts = _component_line_maps(
            profile_id,
            verified["coverage_result"],
            lcov,
            components,
        )
        observed_paths.update(line_counts)
        line_summary = _line_summary(line_counts)
        covered_by_profile.append({"profile_id": profile_id, "line_counts": line_counts})
        profile_rows.append(
            {
                "profile_id": profile_id,
                "receipt_sha256": verified["receipt_sha256"],
                "target_artifact": verified["target_artifact"],
                "coverage_result_sha256": verified["coverage_result_sha256"],
                "lcov_sha256": verified["lcov_sha256"],
                "case_evidence": {
                    "selected": verified["case_count"],
                    "passed": verified["case_count"],
                    "failed": 0,
                },
                "line": line_summary,
            }
        )

    if observed_paths != set(eligible_paths):
        raise _fail(
            "LCOV eligible paths differ from manifest: "
            f"missing={sorted(set(eligible_paths) - observed_paths)}, "
            f"unknown={sorted(observed_paths - set(eligible_paths))}"
        )

    union_summary = _union_line_summary(covered_by_profile)
    status = (
        "completed" if union_summary["total"] > 0 and not union_summary["uncovered"] else "failed"
    )
    result = {
        "schema": UNION_RESULT_SCHEMA,
        "status": status,
        "identity": {
            "manifest": manifest_identity,
            "target": {
                "revision": current_target["revision"],
                "dirty": current_target["dirty"],
            },
            "source_tree_sha256": current_target["working_tree_sha256"],
        },
        "eligible": {"path_count": len(eligible_paths), "paths": eligible_paths},
        "profiles": profile_rows,
        "line": union_summary,
    }
    _validate_union_result(result)
    return result


def _output_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise _fail("coverage union output must be a repository-relative path under build/")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to((root / "build").resolve())
    except ValueError as exc:
        raise _fail("coverage union output must be under build/") from exc
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", default=DEFAULT_INPUT_ROOT.as_posix())
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH.as_posix())
    arguments = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    input_root = Path(arguments.input_root)
    if not input_root.is_absolute():
        input_root = root / input_root
    try:
        result = aggregate_coverage(root, input_root)
        output = _output_path(root, arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (ContractError, OSError, ValueError) as exc:
        print(f"coverage union failed: {exc}", file=sys.stderr)
        return 2

    line = result["line"]
    print(
        f"coverage union: {line['covered']}/{line['total']} lines "
        f"({line['percent']:.4f}%), {len(line['uncovered'])} uncovered; artifact: {output}"
    )
    if result["status"] != "completed":
        print("eligible coverage union is not 100%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
