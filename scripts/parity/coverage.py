"""Managed, input-driven Rust line coverage for one declared target profile."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .comparator import compare_workflows
from .contract import (
    MANIFEST_SCHEMA,
    ContractError,
    load_json,
    sha256_file,
    validate_coverage_inputs,
    validate_manifest,
)
from .envs import (
    environment_ids,
    load_prepared_environments,
    python_version_from_runtime,
)
from .runner import (
    MAX_DIAGNOSTIC,
    _adapter_environment,
    _base_environment,
    _command_map,
    _load_contract,
    _operations,
    _oracle_identity,
    _profiles,
    _resolve_command,
    _run_case,
    _target_bindings,
    _target_identity,
    _unsupported_target_input_reason,
)

COVERAGE_RESULT_SCHEMA = "migration-parity/coverage-result@1"
COVERAGE_RESULT_SCHEMA_PATH = Path("tests/fixtures/coverage-result-schema.json")
CARGO_LLVM_COV_VERSION = "0.8.7"
COVERAGE_ROOT = Path("build/parity/coverage")
_ASSIGNMENT = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")
_VERSION = re.compile(r"\bcargo-llvm-cov\s+(\d+\.\d+\.\d+)\b")
_COVERAGE_FLAGS_ENV = (
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "__CARGO_LLVM_COV_RUSTC_WRAPPER_RUSTFLAGS",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"coverage evidence path is outside the repository: {path}") from exc


def _error(scope: str, subject_id: str, kind: str, message: str) -> dict[str, str]:
    return {
        "scope": scope,
        "id": subject_id,
        "kind": kind,
        "message": message[:MAX_DIAGNOSTIC],
    }


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return type(value) is bool
    if expected == "integer":
        return type(value) is int
    if expected == "number":
        return type(value) in {int, float}
    if expected == "null":
        return value is None
    return False


def _validate_schema_value(
    value: Any, schema: dict[str, Any], schema_root: dict[str, Any], context: str
) -> None:
    """Validate the local result schema's strict JSON Schema subset with stdlib code."""
    supported_keywords = {
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "const",
        "enum",
        "format",
        "items",
        "maximum",
        "minimum",
        "maxItems",
        "minItems",
        "minLength",
        "pattern",
        "properties",
        "required",
        "title",
        "type",
        "uniqueItems",
    }
    unsupported = schema.keys() - supported_keywords
    if unsupported:
        raise ContractError(
            f"coverage result schema uses unsupported keywords: {sorted(unsupported)}"
        )

    reference = schema.get("$ref")
    if reference is not None:
        prefix = "#/$defs/"
        if not reference.startswith(prefix):
            raise ContractError(
                f"coverage result schema uses an unsupported reference: {reference}"
            )
        definition = reference[len(prefix) :]
        definitions = schema_root.get("$defs", {})
        if definition not in definitions:
            raise ContractError(f"coverage result schema has an unknown definition: {definition}")
        _validate_schema_value(value, definitions[definition], schema_root, context)
        return

    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ContractError(f"coverage result {context} differs from its schema constant")
    if "enum" in schema and not any(
        type(value) is type(candidate) and value == candidate for candidate in schema["enum"]
    ):
        raise ContractError(f"coverage result {context} is outside its schema enum")

    expected_type = schema.get("type")
    if expected_type is not None:
        accepted_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_schema_type_matches(value, item) for item in accepted_types):
            raise ContractError(f"coverage result {context} has the wrong JSON type")

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = sorted(set(required) - value.keys())
        if missing:
            raise ContractError(f"coverage result {context} is missing fields: {missing}")
        properties = schema.get("properties", {})
        extra = sorted(value.keys() - properties.keys())
        if schema.get("additionalProperties") is False and extra:
            raise ContractError(f"coverage result {context} has unknown fields: {extra}")
        additional_schema = schema.get("additionalProperties")
        for name, child in value.items():
            if name in properties:
                _validate_schema_value(child, properties[name], schema_root, f"{context}.{name}")
            elif isinstance(additional_schema, dict):
                _validate_schema_value(child, additional_schema, schema_root, f"{context}.{name}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"coverage result {context} has too few items")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            raise ContractError(f"coverage result {context} has too many items")
        if schema.get("uniqueItems"):
            encoded_items = [
                json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False)
                for item in value
            ]
            if len(encoded_items) != len(set(encoded_items)):
                raise ContractError(f"coverage result {context} contains duplicate items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema_value(item, item_schema, schema_root, f"{context}[{index}]")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError(f"coverage result {context} is shorter than its schema minimum")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise ContractError(f"coverage result {context} does not match its schema pattern")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ContractError(f"coverage result {context} is not a date-time") from exc
            if parsed.tzinfo is None:
                raise ContractError(f"coverage result {context} must include a timezone")

    if type(value) in {int, float}:
        if value < schema.get("minimum", value):
            raise ContractError(f"coverage result {context} is below its schema minimum")
        if value > schema.get("maximum", value):
            raise ContractError(f"coverage result {context} is above its schema maximum")


def _validate_coverage_result(
    root: Path,
    result: dict[str, Any],
    *,
    manifest_identity: dict[str, str],
    input_identities: list[dict[str, str]],
    asset_identities: list[dict[str, Any]],
    command: dict[str, Any],
    plan: dict[str, Any],
    manifest: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    schema = load_json(root / COVERAGE_RESULT_SCHEMA_PATH)
    if (
        not isinstance(schema, dict)
        or schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
    ):
        raise ContractError("coverage-result-schema.json must use JSON Schema 2020-12")
    if schema.get("properties", {}).get("schema") != {"const": COVERAGE_RESULT_SCHEMA}:
        raise ContractError(
            "coverage-result-schema.json does not match the coverage result contract"
        )
    if schema.get("additionalProperties") is not False:
        raise ContractError("coverage-result-schema.json must reject unknown top-level fields")
    _validate_schema_value(result, schema, schema, "result")

    identity = result["identity"]
    if identity["manifest"] != manifest_identity:
        raise ContractError("coverage result manifest identity changed during collection")
    if identity["inputs"] != input_identities:
        raise ContractError("coverage result inputs differ from the selected indexed stimuli")
    if identity["assets"] != asset_identities:
        raise ContractError("coverage result assets differ from the selected input stimuli")
    target_rows = identity["targets"]
    has_infrastructure_error = any(
        error["scope"] != "case_outcome" for error in result["infrastructure_errors"]
    )
    if target_rows and (
        len(target_rows) != 1
        or target_rows[0]["target_profile"] != profile["id"]
        or target_rows[0]["target_id"] != profile["target_id"]
    ):
        raise ContractError("coverage result target identity differs from the selected profile")
    oracle_definition = manifest["oracles"][0]
    oracle_rows = identity["oracles"]
    if oracle_rows and (
        len(oracle_rows) != 1
        or oracle_rows[0]["oracle_id"] != oracle_definition["id"]
        or oracle_rows[0]["name"] != oracle_definition["name"]
        or oracle_rows[0]["version"] != oracle_definition["version"]
    ):
        raise ContractError("coverage result oracle identity differs from the active manifest")
    if not has_infrastructure_error and (len(target_rows) != 1 or len(oracle_rows) != 1):
        raise ContractError("coverage result omitted a successful oracle or target identity")
    if identity["command"] != {
        "command_id": command["id"],
        "argv": command["argv"],
        "cwd": command["cwd"],
        "timeout_seconds": command["timeout_seconds"],
    }:
        raise ContractError("coverage result command identity differs from the active manifest")
    if len(result["plans"]) != 1:
        raise ContractError("coverage result must contain exactly the selected profile plan")
    plan_result = result["plans"][0]
    expected_selected = {
        "parity_case_ids": plan["selectors"]["parity_case_ids"],
        "command_ids": plan["selectors"]["command_ids"],
    }
    if (
        plan_result["plan_id"] != plan["plan_id"]
        or plan_result["target_profile"] != plan["target_profile"]
        or plan_result["requirements"] != plan["covers"]
        or plan_result["selected"] != expected_selected
    ):
        raise ContractError("coverage result plan identity differs from the validated input plan")
    execution = plan_result["execution"]
    summary = result["summary"]
    if (
        summary["plans_selected"] != 1
        or summary["plans_executed"] != int(execution["status"] in {"completed", "failed"})
        or summary["plans_not_run"] != int(execution["status"] == "not_run")
        or summary["tests_passed"] != execution["tests_passed"]
        or summary["tests_failed"] != execution["tests_failed"]
    ):
        raise ContractError("coverage result summary differs from its selected plan execution")
    if execution["tests_passed"] + execution["tests_failed"] > len(
        expected_selected["parity_case_ids"]
    ):
        raise ContractError("coverage result counts exceed the selected parity case set")
    if execution["status"] in {"completed", "failed"} and (
        execution["tests_passed"] + execution["tests_failed"]
        != len(expected_selected["parity_case_ids"])
    ):
        raise ContractError("executed coverage plan does not account for every selected case")

    expected_components = {
        component["id"]: component
        for component in manifest["coverage_components"]
        if component["id"] in plan["component_ids"]
    }
    component_results = plan_result["components"]
    if [item["component_id"] for item in component_results] != [
        component["id"]
        for component in manifest["coverage_components"]
        if component["id"] in plan["component_ids"]
    ]:
        raise ContractError("coverage result component inventory differs from the selected plan")
    for component_result in component_results:
        component = expected_components[component_result["component_id"]]
        if component["target_profile"] != profile["id"]:
            raise ContractError("coverage plan selected a component for another target profile")
        if [item["path"] for item in component_result["files"]] != component["paths"]:
            raise ContractError(
                f"coverage result files differ from component {component['id']} source paths"
            )
        if component_result["thresholds"] != []:
            raise ContractError("coverage result reports undeclared coverage thresholds")
        measurement_states: set[bool] = set()
        for file_result in component_result["files"]:
            measurement_states.add(bool(file_result["dimensions"]))
            if not file_result["dimensions"]:
                continue
            if len(file_result["dimensions"]) != 1:
                raise ContractError("coverage result files must report line coverage exactly once")
            dimension = file_result["dimensions"][0]
            if dimension["covered"] > dimension["total"] or len(dimension["uncovered"]) != (
                dimension["total"] - dimension["covered"]
            ):
                raise ContractError("coverage result line totals disagree with uncovered locations")
            uncovered_lines = dimension["uncovered"]
            if uncovered_lines != sorted(set(uncovered_lines)) or any(
                not location.startswith(f"{file_result['path']}:")
                or not location.rsplit(":", 1)[-1].isdigit()
                or int(location.rsplit(":", 1)[-1]) < 1
                for location in uncovered_lines
            ):
                raise ContractError("coverage result has invalid uncovered line locations")
        if len(measurement_states) > 1:
            raise ContractError("coverage result mixes measured and unmeasured component files")
        if measurement_states == {False} and not any(
            error["scope"] != "case_outcome" for error in result["infrastructure_errors"]
        ):
            raise ContractError("coverage result omitted component measurements without an error")

    expected_status = "infrastructure_failed" if has_infrastructure_error else "not_ingested"
    if result["status"] != expected_status:
        raise ContractError(
            "coverage result status does not match execution and ingestion evidence"
        )
    if result["collector"]["snapshot_id"] is not None or result["collector"]["artifact_ingested"]:
        raise ContractError("local coverage results cannot claim an ingested snapshot")

    actual_manifest_sha = sha256_file(root / manifest_identity["path"])
    if actual_manifest_sha != manifest_identity["sha256"]:
        raise ContractError("active manifest changed during coverage collection")
    for input_identity in input_identities:
        input_path = root / input_identity["path"]
        if sha256_file(input_path) != input_identity["sha256"]:
            raise ContractError(
                f"active coverage input changed during collection: {input_identity['path']}"
            )


def _run_process(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    try:
        process = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None, f"executable is absent: {argv[0]}"
    except subprocess.TimeoutExpired:
        return None, f"command exceeded its {timeout}-second timeout: {argv[0]}"
    except OSError as exc:
        return None, str(exc)
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()[-MAX_DIAGNOSTIC:]
        return process, detail or f"command exited with status {process.returncode}"
    return process, None


def _cargo_executable() -> str | None:
    return shutil.which("cargo")


def _coverage_tool_version(
    cargo: str, root: Path, env: dict[str, str]
) -> tuple[str | None, str | None]:
    process, error = _run_process([cargo, "llvm-cov", "--version"], cwd=root, env=env, timeout=15)
    if error or process is None:
        return None, error or "cargo llvm-cov did not return a version"
    match = _VERSION.search(process.stdout.strip())
    if match is None:
        return None, f"unrecognized cargo llvm-cov version output: {process.stdout.strip()}"
    return match.group(1), None


def _parse_show_env(output: str, inherited: dict[str, str]) -> tuple[dict[str, str], str | None]:
    """Parse cargo-llvm-cov's plain KEY=value output without evaluating shell text."""
    env = dict(inherited)
    seen: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        match = _ASSIGNMENT.fullmatch(stripped)
        if match is None:
            return env, f"cargo llvm-cov show-env emitted an unexpected line: {stripped[:200]}"
        name, value = match.groups()
        if name in seen:
            return env, f"cargo llvm-cov show-env repeated environment variable {name}"
        seen.add(name)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name == "CARGO_LLVM_COV_SHOW_ENV":
            continue
        env[name] = value
    if "LLVM_PROFILE_FILE" not in seen or not env.get("LLVM_PROFILE_FILE"):
        return env, "cargo llvm-cov show-env omitted LLVM_PROFILE_FILE"
    if not any(
        "instrument-coverage" in env.get(name, "") for name in _COVERAGE_FLAGS_ENV if name in seen
    ):
        return env, "cargo llvm-cov show-env omitted -C instrument-coverage flags"
    return env, None


def _profile_coverage_environment(
    cargo: str, root: Path, target_dir: Path, inherited: dict[str, str]
) -> tuple[dict[str, str], str | None]:
    env = dict(inherited)
    env["CARGO_TARGET_DIR"] = str(target_dir)
    # External compiler wrappers can discard the pinned tool's coverage flags.
    env.pop("RUSTC_WRAPPER", None)
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    process, error = _run_process(
        [cargo, "llvm-cov", "show-env"],
        cwd=root,
        env=env,
        timeout=30,
    )
    if error or process is None:
        return env, error or "cargo llvm-cov show-env did not return environment settings"
    parsed, parse_error = _parse_show_env(process.stdout, env)
    parsed["CARGO_TARGET_DIR"] = str(target_dir)
    if parse_error is None:
        profile_pattern = Path(parsed["LLVM_PROFILE_FILE"])
        if not profile_pattern.is_absolute():
            profile_pattern = root / profile_pattern
        target_root = target_dir.resolve()
        profile_parent = profile_pattern.parent.resolve()
        try:
            profile_parent.relative_to(target_root)
        except ValueError:
            return (
                parsed,
                "cargo llvm-cov profile output path escapes its isolated target directory",
            )
        try:
            profile_parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return parsed, f"cannot create cargo llvm-cov profile directory: {exc}"
        parsed["LLVM_PROFILE_FILE"] = str(profile_parent / profile_pattern.name)
    return parsed, parse_error


def _source_input_identities(
    root: Path,
    coverage_path: Path,
    coverage_document: dict[str, Any],
    indexed_parity_inputs: list[tuple[Path, dict[str, Any]]],
    selected_case_ids: list[str],
) -> list[dict[str, str]]:
    case_input_paths: dict[str, Path] = {}
    for input_path, document in indexed_parity_inputs:
        for case in document["cases"]:
            case_input_paths[case["case_id"]] = input_path
    selected_paths = {
        case_input_paths[case_id] for case_id in selected_case_ids if case_id in case_input_paths
    }
    missing_case_ids = sorted(set(selected_case_ids) - case_input_paths.keys())
    if missing_case_ids:
        raise ContractError(
            f"coverage plan references cases absent from indexed inputs: {missing_case_ids}"
        )
    if len(selected_paths) == 0:
        raise ContractError("coverage plan selected no parity input files")
    identities = [
        {
            "path": _relative_path(coverage_path, root),
            "schema": coverage_document["schema"],
            "sha256": sha256_file(coverage_path),
        }
    ]
    identities.extend(
        {
            "path": _relative_path(path, root),
            "schema": document["schema"],
            "sha256": sha256_file(path),
        }
        for path, document in indexed_parity_inputs
        if path in selected_paths
    )
    return identities


def _json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _inline_file_assets(value: Any, pointer: str = "") -> list[tuple[str, bytes]]:
    """Find inline file bytes using their input-defined JSON pointer locations."""
    if isinstance(value, dict):
        encoded = value.get("contents_base64")
        if isinstance(encoded, str):
            try:
                contents = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ContractError(
                    f"inline file asset at {pointer or '/'} has invalid base64"
                ) from exc
            return [(pointer or "/", contents)]
        assets: list[tuple[str, bytes]] = []
        for key, child in value.items():
            if key == "contents_base64":
                continue
            child_pointer = f"{pointer}/{_json_pointer_segment(key)}"
            assets.extend(_inline_file_assets(child, child_pointer))
        return assets
    if isinstance(value, list):
        assets = []
        for index, child in enumerate(value):
            assets.extend(_inline_file_assets(child, f"{pointer}/{index}"))
        return assets
    return []


def _selected_asset_identities(
    root: Path,
    indexed_parity_inputs: list[tuple[Path, dict[str, Any]]],
    selected_case_ids: list[str],
) -> list[dict[str, Any]]:
    selected = set(selected_case_ids)
    assets: list[dict[str, Any]] = []
    resolved: set[str] = set()
    for path, document in indexed_parity_inputs:
        relative_path = _relative_path(path, root)
        for case in document["cases"]:
            if case["case_id"] not in selected:
                continue
            resolved.add(case["case_id"])
            for asset_index, (locator, contents) in enumerate(_inline_file_assets(case), start=1):
                assets.append(
                    {
                        "input_path": relative_path,
                        "item_id": case["case_id"],
                        "asset_id": f"inline-file-{asset_index}",
                        "kind": "inline",
                        "locator": locator,
                        "sha256": hashlib.sha256(contents).hexdigest(),
                    }
                )
    if resolved != selected:
        raise ContractError(
            f"coverage assets cannot resolve selected cases: {sorted(selected - resolved)}"
        )
    return assets


def _configure_typechecker(
    root: Path, env: dict[str, str], selected_cases: list[dict[str, Any]]
) -> str | None:
    """Resolve the pinned checker only when selected input stimuli require type checks."""
    if not any("typing_contract" in case for case in selected_cases):
        return None

    configured = env.get("STARLETTE_PARITY_TYPECHECKER")
    candidates = [Path(configured)] if configured else []
    if not candidates:
        executable = "mypy.exe" if os.name == "nt" else "mypy"
        folder = "Scripts" if os.name == "nt" else "bin"
        candidates.append(Path(".venv-typecheck") / folder / executable)

    for candidate in candidates:
        resolved = candidate if candidate.is_absolute() else root / candidate
        if resolved.is_file() and os.access(resolved, os.X_OK):
            env["STARLETTE_PARITY_TYPECHECKER"] = str(resolved.resolve())
            return None
    expected = configured or candidates[0].as_posix()
    return (
        "selected parity inputs include typing_contract stimuli, but the pinned type checker "
        f"is unavailable or not executable: {expected}"
    )


def _resolve_default_profile(manifest: dict[str, Any], prepared: dict[str, dict[str, Any]]) -> str:
    python_runtimes = sorted(
        {
            record["runtime"]
            for record in prepared.values()
            if record["id"].startswith("starlette-rs-py-")
        }
    )
    if len(python_runtimes) != 1:
        raise ContractError(
            "coverage requires an explicit target profile when exactly one prepared CPython "
            "environment is unavailable"
        )
    version = python_version_from_runtime(python_runtimes[0])
    profile_id = f"python-package-cpython{version.replace('.', '')}"
    if profile_id not in {profile["id"] for profile in manifest["target_profiles"]}:
        raise ContractError(f"prepared Python runtime has no coverage target profile: {version}")
    return profile_id


def _python_extension_suffix(interpreter: Path, root: Path, env: dict[str, str]) -> str:
    process, error = _run_process(
        [
            str(interpreter),
            "-c",
            "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX') or '')",
        ],
        cwd=root,
        env=env,
        timeout=15,
    )
    suffix = process.stdout.strip() if process is not None else ""
    if error or not suffix or Path(suffix).name != suffix:
        raise ContractError(
            f"cannot determine the prepared interpreter extension suffix: {error or suffix!r}"
        )
    return suffix


def _install_instrumented_extension(
    root: Path,
    run_dir: Path,
    target_dir: Path,
    prepared: dict[str, dict[str, Any]],
    python_version: str,
) -> Path:
    environment_id = environment_ids(python_version)[1]
    environment = prepared.get(environment_id)
    if environment is None:
        raise ContractError(f"coverage requires prepared target environment {environment_id}")
    interpreter = root / environment["python"]
    suffix = _python_extension_suffix(interpreter, root, _base_environment())
    debug_dir = target_dir / "debug"
    matches = sorted(
        path
        for path in debug_dir.glob("*core*")
        if path.is_file()
        and path.stem in {"_core", "lib_core", "core"}
        and path.suffix.lower() in {".so", ".dylib", ".dll"}
    )
    if len(matches) != 1:
        raise ContractError(
            f"instrumented PyO3 build must emit one lib_core shared library, found {len(matches)}"
        )
    overlay = run_dir / "python-overlay"
    package_dir = overlay / "starlette_rs_py"
    package_dir.mkdir(parents=True, exist_ok=False)
    source_package = root / "starlette-rs-py" / "python" / "starlette_rs_py"
    for source in sorted(source_package.glob("*.py")):
        shutil.copy2(source, package_dir / source.name)
    extension = package_dir / f"_core{suffix}"
    shutil.copy2(matches[0], extension)
    return overlay


def _lcov_source_path(root: Path, raw_path: str) -> str | None:
    value = raw_path.replace("\\", "/")
    source = Path(value)
    if not source.is_absolute():
        source = root / source
    try:
        return source.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None


def _parse_lcov(path: Path, root: Path) -> dict[str, dict[int, int]]:
    files: dict[str, dict[int, int]] = {}
    current: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read cargo llvm-cov LCOV export: {exc}") from exc
    for line in lines:
        if line.startswith("SF:"):
            current = _lcov_source_path(root, line[3:])
            if current is not None:
                files.setdefault(current, {})
        elif line.startswith("DA:") and current is not None:
            fields = line[3:].split(",")
            if len(fields) < 2 or not fields[0].isdigit() or not fields[1].isdigit():
                raise ContractError(f"malformed LCOV line record: {line[:200]}")
            line_number, count = int(fields[0]), int(fields[1])
            if line_number < 1:
                raise ContractError("LCOV line numbers must be positive")
            # LLVM uses near-UINT64_MAX sentinels for lines that have no counter.
            if count >= 2**63:
                count = 0
            existing = files[current].get(line_number)
            files[current][line_number] = count if existing is None else max(existing, count)
        elif line == "end_of_record":
            current = None
    return files


def _component_result(component: dict[str, Any], lcov: dict[str, dict[int, int]]) -> dict[str, Any]:
    file_rows: list[dict[str, Any]] = []
    totals = {"line": {"covered": 0, "total": 0}}
    for relative_path in component["paths"]:
        if relative_path not in lcov:
            raise ContractError(
                f"LLVM LCOV export omitted declared component source file: {relative_path}"
            )
        line_counts = lcov[relative_path]
        covered_lines = sorted(
            line_number for line_number, count in line_counts.items() if count > 0
        )
        uncovered_lines = sorted(
            line_number for line_number, count in line_counts.items() if count == 0
        )
        totals["line"]["covered"] += len(covered_lines)
        totals["line"]["total"] += len(line_counts)
        file_rows.append(
            {
                "path": relative_path,
                "dimensions": [
                    {
                        "dimension": "line",
                        "covered": len(covered_lines),
                        "total": len(line_counts),
                        "uncovered": [f"{relative_path}:{line}" for line in uncovered_lines],
                    }
                ],
            }
        )
    thresholds: list[dict[str, Any]] = []
    for threshold in component["thresholds"]:
        dimension = threshold["dimension"]
        totals_for_dimension = totals.get(dimension, {"covered": 0, "total": 0})
        covered = totals_for_dimension["covered"]
        total = totals_for_dimension["total"]
        minimum = threshold["minimum_percent"]
        outcome = (
            "not_proven" if total == 0 else "pass" if covered * 100 >= minimum * total else "fail"
        )
        thresholds.append(
            {
                "dimension": dimension,
                "minimum_percent": minimum,
                "covered": covered,
                "total": total,
                "outcome": outcome,
            }
        )
    return {"component_id": component["id"], "files": file_rows, "thresholds": thresholds}


def _target_command_for_profile(
    target: dict[str, Any],
    profile: dict[str, Any],
    commands: dict[str, dict[str, Any]],
    prepared: dict[str, dict[str, Any]],
    root: Path,
    native_binary: Path | None,
) -> dict[str, Any]:
    command = commands[target["identity_command_id"]]
    if target["id"] == "rust-native":
        if native_binary is None:
            raise ContractError("instrumented Rust-native parity adapter was not built")
        return {**command, "argv": [str(native_binary), *command["argv"][1:]]}
    environment_id = environment_ids(profile["python_version"])[1]
    return _resolve_command(command, prepared, root, environment_id)


def _set_case_outcome_error(
    errors: list[dict[str, str]], case_id: str, scope: str, result: dict[str, Any]
) -> None:
    reason = next(
        (item.get("reason") for item in result.get("observations", []) if item.get("reason")),
        f"workflow status was {result['status']}",
    )
    errors.append(_error("case_outcome", case_id, f"{scope}_{result['status']}", reason))


def run_coverage(
    root: Path,
    manifest_path: Path,
    target_profile: str | None = None,
) -> dict[str, Any]:
    """Build and run one input-selected target under cargo-llvm-cov instrumentation."""
    root = root.resolve()
    manifest_file = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest_file = manifest_file.resolve()
    try:
        manifest_relative = manifest_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError("active coverage manifest must be inside the repository root") from exc

    manifest, indexed_parity_inputs, cases = _load_contract(root, manifest_file)
    validate_manifest(manifest)
    coverage_documents = validate_coverage_inputs(root, manifest, cases)
    profiles = _profiles(manifest)
    if target_profile is not None and target_profile not in profiles:
        raise ContractError(f"unknown coverage target profile: {target_profile}")

    prepared: dict[str, dict[str, Any]] = {}
    try:
        prepared = load_prepared_environments(root, require_target=True)
    except ContractError:
        if target_profile is not None:
            raise
    if target_profile is None:
        if not prepared:
            raise ContractError(
                "coverage needs a prepared CPython environment; run prepare-env or select a "
                "profile after preparing it"
            )
        target_profile = _resolve_default_profile(manifest, prepared)
    profile = profiles[target_profile]
    plan_rows = [
        plan
        for _path, document in coverage_documents
        for plan in document["plans"]
        if plan["target_profile"] == target_profile
    ]
    if len(plan_rows) != 1:
        raise ContractError(f"coverage input must contain exactly one plan for {target_profile}")
    plan = plan_rows[0]
    coverage_path, coverage_document = next(
        (path, document) for path, document in coverage_documents if plan in document["plans"]
    )
    cases_by_id = {case["case_id"]: case for case in cases}
    selected_cases = [cases_by_id[case_id] for case_id in plan["selectors"]["parity_case_ids"]]
    input_identities = _source_input_identities(
        root,
        coverage_path,
        coverage_document,
        indexed_parity_inputs,
        plan["selectors"]["parity_case_ids"],
    )
    asset_identities = _selected_asset_identities(
        root,
        indexed_parity_inputs,
        plan["selectors"]["parity_case_ids"],
    )
    commands = _command_map(manifest)
    target = _target_bindings(manifest)[profile["target_id"]]
    oracle = manifest["oracles"][0]
    oracle_python_version = profile["python_version"] or "3.12"
    oracle_environment_id = environment_ids(oracle_python_version)[0]
    target_environment_id = (
        environment_ids(profile["python_version"])[1]
        if profile["python_version"] is not None
        else None
    )
    if oracle_environment_id not in prepared:
        raise ContractError(
            f"coverage requires the isolated source oracle environment {oracle_environment_id}"
        )
    if target_environment_id is not None and target_environment_id not in prepared:
        raise ContractError(
            f"coverage requires the isolated target environment {target_environment_id}"
        )

    run_id = str(uuid.uuid4())
    started_at = _now()
    coverage_root = root / COVERAGE_ROOT
    run_dir = coverage_root / target_profile / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    target_dir = coverage_root / "cargo-target" / target_profile / run_id
    target_dir.mkdir(parents=True, exist_ok=False)
    errors: list[dict[str, str]] = []
    source_oracle_record: dict[str, Any] | None = None
    target_identity_record: dict[str, Any] | None = None
    collector_version: str | None = None
    plan_execution_status = "not_run"
    tests_passed = 0
    tests_failed = 0
    component_results = [
        {
            "component_id": component_id,
            "files": [
                {
                    "path": path,
                    "dimensions": [],
                }
                for path in component["paths"]
            ],
            "thresholds": [
                {
                    "dimension": threshold["dimension"],
                    "minimum_percent": threshold["minimum_percent"],
                    "covered": 0,
                    "total": 0,
                    "outcome": "not_proven",
                }
                for component in manifest["coverage_components"]
                if component["id"] == component_id
                for threshold in component["thresholds"]
            ],
        }
        for component_id in plan["component_ids"]
        for component in manifest["coverage_components"]
        if component["id"] == component_id
    ]

    base_env = _base_environment()
    typechecker_error = _configure_typechecker(root, base_env, selected_cases)
    if typechecker_error:
        errors.append(
            _error("runner", "parity-typechecker", "typechecker_unavailable", typechecker_error)
        )
    cargo = _cargo_executable()
    build_env = dict(base_env)
    build_env["CARGO_TARGET_DIR"] = str(target_dir)
    if cargo is None:
        if not errors:
            errors.append(_error("collector", "cargo", "cargo_missing", "Cargo is not on PATH"))
    elif not errors:
        cargo_version, version_error = _coverage_tool_version(cargo, root, build_env)
        collector_version = cargo_version
        if version_error:
            errors.append(_error("collector", "cargo-llvm-cov", "tool_unavailable", version_error))
        elif cargo_version != CARGO_LLVM_COV_VERSION:
            errors.append(
                _error(
                    "collector",
                    "cargo-llvm-cov",
                    "tool_version_mismatch",
                    (
                        "coverage requires cargo-llvm-cov "
                        f"{CARGO_LLVM_COV_VERSION}; found {cargo_version}"
                    ),
                )
            )
        else:
            coverage_env, show_env_error = _profile_coverage_environment(
                cargo, root, target_dir, build_env
            )
            (run_dir / "cargo-llvm-cov-show-env.txt").write_text(
                "\n".join(
                    f"{key}={coverage_env[key].encode('unicode_escape').decode('ascii')}"
                    for key in sorted(coverage_env)
                    if key.startswith(("CARGO_LLVM_COV", "__CARGO_LLVM_COV"))
                    or key
                    in {
                        "LLVM_PROFILE_FILE",
                        "RUSTC_WRAPPER",
                        "RUSTFLAGS",
                        "CARGO_ENCODED_RUSTFLAGS",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            if show_env_error:
                errors.append(
                    _error(
                        "collector",
                        "cargo-llvm-cov",
                        "instrumentation_config_failed",
                        show_env_error,
                    )
                )
            else:
                build_env = dict(coverage_env)
                build_env["CARGO_TARGET_DIR"] = str(target_dir)
                build_env["LLVM_PROFILE_FILE"] = str(run_dir / "build-profraw" / "%p-%m.profraw")
                Path(build_env["LLVM_PROFILE_FILE"]).parent.mkdir(parents=True, exist_ok=True)
                build_argv = [cargo, "build", "--locked"]
                native_binary: Path | None = None
                overlay_path: Path | None = None
                if target["id"] == "rust-native":
                    build_argv.extend(
                        ["-p", "starlette-rs", "--bin", "starlette-rs-parity-adapter"]
                    )
                else:
                    target_environment = prepared[target_environment_id]
                    python_interpreter = root / target_environment["python"]
                    build_env["PYO3_PYTHON"] = str(python_interpreter)
                    build_argv.extend(
                        [
                            "-p",
                            "starlette-rs-py",
                            "--lib",
                            "--features",
                            "fault-contract,pyo3/extension-module",
                        ]
                    )
                process, build_error = _run_process(
                    build_argv, cwd=root, env=build_env, timeout=1800
                )
                (run_dir / "cargo-build.log").write_text(
                    (process.stdout if process else "")
                    + (process.stderr if process else build_error or "build did not start"),
                    encoding="utf-8",
                )
                if build_error:
                    errors.append(
                        _error(
                            "collector",
                            target_profile,
                            "instrumented_build_failed",
                            build_error,
                        )
                    )
                else:
                    if target["id"] == "rust-native":
                        executable_name = (
                            "starlette-rs-parity-adapter.exe"
                            if os.name == "nt"
                            else "starlette-rs-parity-adapter"
                        )
                        native_binary = target_dir / "debug" / executable_name
                        if not native_binary.is_file():
                            errors.append(
                                _error(
                                    "collector",
                                    target_profile,
                                    "adapter_missing",
                                    f"instrumented adapter is missing: {native_binary}",
                                )
                            )
                    else:
                        try:
                            overlay_path = _install_instrumented_extension(
                                root,
                                run_dir,
                                target_dir,
                                prepared,
                                profile["python_version"],
                            )
                        except (ContractError, OSError) as exc:
                            errors.append(
                                _error(
                                    "collector",
                                    target_profile,
                                    "instrumented_extension_missing",
                                    str(exc),
                                )
                            )

                if not errors:
                    _, source_oracle_record, oracle_error = _load_oracle_identity(
                        manifest,
                        commands,
                        base_env,
                        prepared,
                        root,
                        oracle_environment_id,
                    )
                    if oracle_error:
                        errors.append(oracle_error)
                    coverage_commands = dict(commands)
                    coverage_commands[target["identity_command_id"]] = _target_command_for_profile(
                        target,
                        profile,
                        commands,
                        prepared,
                        root,
                        native_binary,
                    )
                    if not errors:
                        identity_env = dict(coverage_env)
                        identity_env["LLVM_PROFILE_FILE"] = str(
                            run_dir / "identity-profraw" / "%p-%m.profraw"
                        )
                        Path(identity_env["LLVM_PROFILE_FILE"]).parent.mkdir(
                            parents=True, exist_ok=True
                        )
                        if overlay_path is not None:
                            identity_env["PYTHONPATH"] = str(overlay_path)
                        target_records, target_identities, target_errors = _target_identity(
                            target,
                            [profile],
                            coverage_commands,
                            identity_env,
                            prepared,
                            root,
                        )
                        if target_errors:
                            errors.extend(target_errors)
                        elif profile["id"] in target_identities and target_records:
                            target_identity_record = next(
                                (
                                    record
                                    for record in target_records
                                    if record["target_profile"] == profile["id"]
                                ),
                                None,
                            )
                            if target_identity_record is None:
                                errors.append(
                                    _error(
                                        "target",
                                        profile["id"],
                                        "identity_missing",
                                        (
                                            "instrumented target identity record omitted "
                                            "the selected profile"
                                        ),
                                    )
                                )
                        else:
                            errors.append(
                                _error(
                                    "target",
                                    profile["id"],
                                    "identity_missing",
                                    (
                                        "instrumented target identity did not identify "
                                        "the selected profile"
                                    ),
                                )
                            )

                    if (
                        not errors
                        and source_oracle_record is not None
                        and target_identity_record is not None
                    ):
                        oracle_command = _resolve_command(
                            commands[oracle["identity_command_id"]],
                            prepared,
                            root,
                            oracle_environment_id,
                        )
                        oracle_env = _adapter_environment(
                            base_env,
                            prepared[oracle_environment_id]["dependency_lock_sha256"],
                        )
                        target_environment = (
                            prepared[target_environment_id] if target_environment_id else None
                        )
                        target_env = _adapter_environment(
                            coverage_env,
                            target_environment["dependency_lock_sha256"]
                            if target_environment
                            else sha256_file(root / "Cargo.lock"),
                            target_environment,
                        )
                        if overlay_path is not None:
                            target_env["PYTHONPATH"] = str(overlay_path)
                        target_command = _target_command_for_profile(
                            target,
                            profile,
                            coverage_commands,
                            prepared,
                            root,
                            native_binary,
                        )
                        target_command = _resolve_command(
                            target_command,
                            prepared,
                            root,
                            target_environment_id,
                        )
                        operations = _operations(manifest)
                        observed_comparisons = 0
                        observed_not_run = 0
                        for case in selected_cases:
                            case_id = case["case_id"]
                            source_result, source_error = _run_case(
                                oracle_command,
                                oracle["id"],
                                case,
                                oracle_env,
                                "oracle",
                                root,
                            )
                            if source_error:
                                errors.append(source_error)
                            if source_result is None:
                                observed_not_run += 1
                                continue
                            if source_result["status"] != "completed":
                                _set_case_outcome_error(errors, case_id, "source", source_result)
                                observed_not_run += 1
                                continue
                            unsupported_reason = _unsupported_target_input_reason(
                                operations[(case["surface"], case["operation"])],
                                target["id"],
                                case,
                            )
                            if unsupported_reason is not None:
                                errors.append(
                                    _error(
                                        "case_outcome",
                                        case_id,
                                        "target_unsupported",
                                        unsupported_reason,
                                    )
                                )
                                observed_not_run += 1
                                continue
                            target_result, target_error = _run_case(
                                target_command,
                                target["id"],
                                case,
                                target_env,
                                "target",
                                root,
                            )
                            if target_error:
                                errors.append(target_error)
                            if target_result is None:
                                observed_not_run += 1
                                continue
                            if target_result["status"] != "completed":
                                _set_case_outcome_error(errors, case_id, "target", target_result)
                                observed_not_run += 1
                                continue
                            outcome, _diffs = compare_workflows(
                                case,
                                operations[(case["surface"], case["operation"])],
                                source_result,
                                target_result,
                            )
                            if outcome == "pass":
                                tests_passed += 1
                            elif outcome == "fail":
                                tests_failed += 1
                                errors.append(
                                    _error(
                                        "case_outcome",
                                        case_id,
                                        "comparison_failed",
                                        json.dumps(
                                            _diffs,
                                            ensure_ascii=False,
                                            separators=(",", ":"),
                                            allow_nan=False,
                                        ),
                                    )
                                )
                            else:
                                observed_not_run += 1
                            observed_comparisons += 1

                        if observed_not_run:
                            plan_execution_status = "not_run"
                        elif tests_failed:
                            plan_execution_status = "failed"
                        elif observed_comparisons == len(selected_cases):
                            plan_execution_status = "completed"

                        report_path = run_dir / "coverage.lcov"
                        report_env = dict(coverage_env)
                        report_argv = [
                            cargo,
                            "llvm-cov",
                            "report",
                            "--lcov",
                            "--output-path",
                            str(report_path),
                        ]
                        process, report_error = _run_process(
                            report_argv, cwd=root, env=report_env, timeout=900
                        )
                        (run_dir / "cargo-report.log").write_text(
                            (process.stdout if process else "")
                            + (
                                process.stderr
                                if process
                                else report_error or "report did not start"
                            ),
                            encoding="utf-8",
                        )
                        if report_error:
                            errors.append(
                                _error(
                                    "collector",
                                    target_profile,
                                    "lcov_export_failed",
                                    report_error,
                                )
                            )
                            plan_execution_status = "not_run"
                        else:
                            try:
                                lcov = _parse_lcov(report_path, root)
                                missing_component_paths = [
                                    relative_path
                                    for component_id in plan["component_ids"]
                                    for component in manifest["coverage_components"]
                                    if component["id"] == component_id
                                    for relative_path in component["paths"]
                                    if relative_path not in lcov
                                ]
                                if missing_component_paths:
                                    raise ContractError(
                                        "LCOV export omitted declared component source files: "
                                        + ", ".join(missing_component_paths)
                                    )
                                component_results = [
                                    _component_result(component, lcov)
                                    for component in manifest["coverage_components"]
                                    if component["id"] in plan["component_ids"]
                                ]
                            except ContractError as exc:
                                errors.append(
                                    _error(
                                        "collector",
                                        target_profile,
                                        "lcov_parse_failed",
                                        str(exc),
                                    )
                                )
                                plan_execution_status = "not_run"

    finished_at = _now()
    target_rows = []
    if target_identity_record is not None:
        target_rows = [
            {
                "target_profile": profile["id"],
                "target_id": profile["target_id"],
                "revision": target_identity_record["revision"],
                "dirty": target_identity_record["dirty"],
                "runtime": target_identity_record["runtime"],
                "backend": target_identity_record["backend"],
                "features": target_identity_record["features"],
            }
        ]
    oracle_rows = (
        [
            {
                "oracle_id": oracle["id"],
                "name": oracle["name"],
                "version": oracle["version"],
                "runtime": source_oracle_record["runtime"],
            }
        ]
        if source_oracle_record is not None
        else []
    )
    infrastructure_failure = any(error["scope"] != "case_outcome" for error in errors)
    status = "infrastructure_failed" if infrastructure_failure else "not_ingested"
    coverage_command = commands[manifest["interfaces"]["coverage"]["command_id"]]
    manifest_identity = {
        "path": manifest_relative,
        "schema": MANIFEST_SCHEMA,
        "sha256": sha256_file(manifest_file),
    }
    result: dict[str, Any] = {
        "schema": COVERAGE_RESULT_SCHEMA,
        "identity": {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "manifest": manifest_identity,
            "inputs": input_identities,
            "assets": asset_identities,
            "oracles": oracle_rows,
            "targets": target_rows,
            "command": {
                "command_id": coverage_command["id"],
                "argv": coverage_command["argv"],
                "cwd": coverage_command["cwd"],
                "timeout_seconds": coverage_command["timeout_seconds"],
            },
        },
        "status": status,
        "collector": {
            "name": "cargo-llvm-cov",
            "version": collector_version,
            "snapshot_id": None,
            "artifact_ingested": False,
        },
        "summary": {
            "plans_selected": 1,
            "plans_executed": int(plan_execution_status in {"completed", "failed"}),
            "plans_not_run": int(plan_execution_status == "not_run"),
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
        },
        "plans": [
            {
                "plan_id": plan["plan_id"],
                "target_profile": plan["target_profile"],
                "requirements": plan["covers"],
                "selected": {
                    "parity_case_ids": plan["selectors"]["parity_case_ids"],
                    "command_ids": plan["selectors"]["command_ids"],
                },
                "execution": {
                    "status": plan_execution_status,
                    "tests_passed": tests_passed,
                    "tests_failed": tests_failed,
                },
                "components": component_results,
            }
        ],
        "infrastructure_errors": errors,
    }
    _validate_coverage_result(
        root,
        result,
        manifest_identity=manifest_identity,
        input_identities=input_identities,
        asset_identities=asset_identities,
        command=coverage_command,
        plan=plan,
        manifest=manifest,
        profile=profile,
    )
    artifact_path = run_dir / "coverage-result.json"
    artifact_path.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    # The artifact remains schema-exact; this path is return-only CLI metadata.
    result["artifact_path"] = _relative_path(artifact_path, root)
    result["run_directory"] = _relative_path(run_dir, root)
    result["coverage_report_path"] = (
        _relative_path(run_dir / "coverage.lcov", root)
        if (run_dir / "coverage.lcov").is_file()
        else None
    )
    result["_identity_sha256"] = _canonical_sha256(result["identity"])
    return result


def _load_oracle_identity(
    manifest: dict[str, Any],
    commands: dict[str, dict[str, Any]],
    env: dict[str, str],
    prepared: dict[str, dict[str, Any]],
    root: Path,
    environment_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    return _oracle_identity(manifest, commands, env, prepared, root, environment_id)
