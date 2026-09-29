"""Process-isolated source/target runner for the active parity slice."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .api_sources import load_api_metadata, validate_api_sources
from .comparator import compare_workflows
from .contract import (
    MANIFEST_SCHEMA,
    RESULT_SCHEMA,
    ContractError,
    load_manifest,
    sha256_file,
    validate_inputs,
    validate_manifest,
    validate_result_artifact,
    validate_workflow_result,
)
from .envs import (
    ENVIRONMENT_IDS,
    load_prepared_environments,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE = Path("tests/fixtures/manifest.yaml")
RESULT_RELATIVE = Path("build/parity/parity-result.json")
ORACLE_ROOT_DEFAULT = Path("/Users/lazytrot/work/starlette")
PROTOCOL_REQUEST = "migration-parity/adapter-request@1"
PROTOCOL_RESPONSE = "migration-parity/adapter-response@1"
ENVIRONMENT_PLACEHOLDER_PREFIX = "{environment:"
MAX_DIAGNOSTIC = 2000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _command_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {command["id"]: command for command in manifest["commands"]}


def _operations(manifest: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (surface["id"], operation["id"]): operation
        for surface in manifest["surfaces"]
        for operation in surface["operations"]
    }


def _target_binding(operation: dict[str, Any], target_id: str) -> dict[str, Any]:
    matches = [binding for binding in operation["targets"] if binding["target_id"] == target_id]
    if len(matches) != 1:
        raise ContractError(
            f"operation {operation['id']} must bind target {target_id!r} exactly once"
        )
    return matches[0]


def _declared_unsupported_reason(
    operation: dict[str, Any], target_id: str, case: dict[str, Any]
) -> str | None:
    """Return the declared reason when this case exercises a partial target boundary."""
    support = _target_binding(operation, target_id)["support"]
    if support["status"] != "partial":
        return None
    missing_requirements = set(support["missing_requirements"])
    if not missing_requirements.intersection(case["covers"]):
        return None
    return support["reason"]


def _target_bindings(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {target["id"]: target for target in manifest["targets"]}


def _profiles(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {profile["id"]: profile for profile in manifest["target_profiles"]}


def _load_contract(
    root: Path, manifest_path: Path | None = None
) -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    path = manifest_path or (root / MANIFEST_RELATIVE)
    manifest = load_manifest(path)
    validate_manifest(manifest)
    validate_api_sources(manifest, load_api_metadata(root))
    indexed_inputs, cases = validate_inputs(root, manifest)
    return manifest, indexed_inputs, cases


def _parse_one_json(stdout: bytes, context: str) -> Any:
    text = stdout.decode("utf-8")
    if not text.strip():
        raise ContractError(f"{context} emitted no JSON on stdout")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError(f"{context} must emit exactly one JSON object on stdout")
    return load_json_from_text(lines[0], context)


def load_json_from_text(text: str, context: str) -> Any:
    from .contract import _pairs_no_duplicates, _reject_constant

    try:
        return json.loads(
            text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise ContractError(f"{context} emitted invalid JSON: {exc}") from exc


def _invoke_adapter(
    command: dict[str, Any],
    request: dict[str, Any],
    timeout_seconds: int,
    env: dict[str, str],
    scope: str,
    subject_id: str,
    root: Path,
) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        process = subprocess.run(
            command["argv"],
            cwd=root / command["cwd"],
            input=(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n").encode(
                "utf-8"
            ),
            capture_output=True,
            timeout=min(timeout_seconds, command["timeout_seconds"]),
            env=env,
            check=False,
        )
    except FileNotFoundError:
        return None, {
            "scope": scope,
            "id": subject_id,
            "kind": "adapter_missing",
            "message": f"adapter command executable is absent: {command['argv'][0]}",
        }
    except subprocess.TimeoutExpired:
        return None, {
            "scope": scope,
            "id": subject_id,
            "kind": "adapter_timeout",
            "message": "adapter exceeded its declared timeout",
        }
    except OSError as exc:
        return None, {
            "scope": scope,
            "id": subject_id,
            "kind": "adapter_start_failed",
            "message": str(exc)[:MAX_DIAGNOSTIC],
        }
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", errors="replace").strip()[:MAX_DIAGNOSTIC]
        if process.returncode in {126, 127}:
            kind = "adapter_missing"
        else:
            kind = "adapter_crashed"
        return None, {
            "scope": scope,
            "id": subject_id,
            "kind": kind,
            "message": detail or f"adapter exited {process.returncode}",
        }
    try:
        return _parse_one_json(process.stdout, f"{subject_id} adapter"), None
    except (UnicodeError, ContractError) as exc:
        return None, {
            "scope": scope,
            "id": subject_id,
            "kind": "malformed_adapter_transport",
            "message": str(exc)[:MAX_DIAGNOSTIC],
        }


def _request(mode: str, subject_id: str, case: dict[str, Any] | None) -> dict[str, Any]:
    return {"schema": PROTOCOL_REQUEST, "mode": mode, "subject_id": subject_id, "case": case}


def _validate_adapter_response(value: Any, mode: str, subject_id: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "mode",
        "subject_id",
        "identity" if mode == "identity" else "result",
    }:
        raise ContractError("adapter response has unknown, missing, or malformed fields")
    if (
        value["schema"] != PROTOCOL_RESPONSE
        or value["mode"] != mode
        or value["subject_id"] != subject_id
    ):
        raise ContractError("adapter response schema, mode, or subject ID mismatch")
    return value


def _resolve_command(
    command: dict[str, Any], prepared: dict[str, dict[str, Any]], root: Path
) -> dict[str, Any]:
    argv = list(command["argv"])
    executable = argv[0]
    if executable.startswith(ENVIRONMENT_PLACEHOLDER_PREFIX) and executable.endswith("}"):
        environment_id = executable[len(ENVIRONMENT_PLACEHOLDER_PREFIX) : -1]
        record = prepared.get(environment_id)
        if record is None:
            raise ContractError(f"adapter environment is not prepared: {environment_id}")
        python_relative = Path(record["python"])
        if python_relative.is_absolute() or ".." in python_relative.parts:
            raise ContractError(
                f"prepared interpreter path is not repository-relative: {record['python']}"
            )
        interpreter = root / python_relative
        if not interpreter.is_file():
            raise ContractError(f"prepared interpreter is absent: {record['python']}")
        argv[0] = str(interpreter.absolute())
    return {**command, "argv": argv}


def _oracle_identity(
    manifest: dict[str, Any],
    commands: dict[str, dict[str, Any]],
    env: dict[str, str],
    prepared: dict[str, dict[str, Any]],
    root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    oracle = manifest["oracles"][0]
    environment = prepared.get(ENVIRONMENT_IDS[0])
    if environment is None:
        return (
            None,
            None,
            {
                "scope": "oracle",
                "id": oracle["id"],
                "kind": "environment_not_prepared",
                "message": "the isolated source-oracle CPython 3.12 environment is missing",
            },
        )
    try:
        cmd = _resolve_command(commands[oracle["identity_command_id"]], prepared, root)
    except ContractError as exc:
        return (
            None,
            None,
            {
                "scope": "oracle",
                "id": oracle["id"],
                "kind": "environment_not_prepared",
                "message": str(exc),
            },
        )
    oracle_env = dict(env)
    oracle_env["STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256"] = environment["dependency_lock_sha256"]
    response, error = _invoke_adapter(
        cmd, _request("identity", oracle["id"], None), 30, oracle_env, "oracle", oracle["id"], root
    )
    if error:
        return None, None, error
    try:
        response = _validate_adapter_response(response, "identity", oracle["id"])
        identity = response["identity"]
        exact = {
            "subject_id",
            "version",
            "revision",
            "runtime",
            "os",
            "architecture",
            "module_path",
            "dependency_lock_sha256",
        }
        if not isinstance(identity, dict) or set(identity) != exact:
            raise ContractError("oracle identity has unknown, missing, or malformed fields")
        if (
            identity["version"] != oracle["version"]
            or identity["revision"] != manifest["scope"]["inventory"]["revision"]
        ):
            raise ContractError(
                "oracle identity does not match the pinned Starlette release and commit"
            )
        for field in ("runtime", "os", "architecture", "module_path", "dependency_lock_sha256"):
            if not isinstance(identity[field], str) or not identity[field]:
                raise ContractError(f"oracle identity {field} must be a non-empty string")
        if not identity["runtime"].startswith("CPython 3.12."):
            raise ContractError("source oracle must run on CPython 3.12")
        if len(identity["dependency_lock_sha256"]) != 64 or any(
            ch not in "0123456789abcdef" for ch in identity["dependency_lock_sha256"]
        ):
            raise ContractError("oracle dependency-lock digest must be lowercase SHA-256")
        if (
            identity["runtime"] != environment["runtime"]
            or identity["os"] != environment["os"]
            or identity["architecture"] != environment["architecture"]
        ):
            raise ContractError(
                "source oracle runtime or platform differs from its prepared environment"
            )
        root_value = env.get("STARLETTE_ORACLE_ROOT")
        if not root_value or not Path(identity["module_path"]).resolve().is_relative_to(
            (Path(root_value) / "starlette").resolve()
        ):
            raise ContractError("oracle adapter imported Starlette outside STARLETTE_ORACLE_ROOT")
        source_lock = Path(root_value) / "uv.lock"
        if not source_lock.is_file() or identity["dependency_lock_sha256"] != sha256_file(
            source_lock
        ):
            raise ContractError(
                "oracle source dependency-lock digest differs from its pinned uv.lock"
            )
        if (
            oracle_env["STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256"]
            != environment["dependency_lock_sha256"]
        ):
            raise ContractError("oracle runtime lock digest was not passed to the isolated adapter")
        evidence = {
            "oracle_id": oracle["id"],
            "name": oracle["name"],
            "version": oracle["version"],
            "revision": identity["revision"],
            "runtime": identity["runtime"],
            "module_path": identity["module_path"],
            "dependency_lock_sha256": identity["dependency_lock_sha256"],
            "os": identity["os"],
            "architecture": identity["architecture"],
            "environment_sha256": environment["environment_sha256"],
            "runtime_lock_sha256": environment["dependency_lock_sha256"],
        }
        return identity, evidence, None
    except (ContractError, KeyError, TypeError, OSError) as exc:
        return (
            None,
            None,
            {
                "scope": "oracle",
                "id": oracle["id"],
                "kind": "identity_mismatch",
                "message": str(exc)[:MAX_DIAGNOSTIC],
            },
        )


def _target_identity(
    target: dict[str, Any],
    profiles: list[dict[str, Any]],
    commands: dict[str, dict[str, Any]],
    env: dict[str, str],
    prepared: dict[str, dict[str, Any]],
    root: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    environment_id = ENVIRONMENT_IDS[1] if target["id"] == "python-package" else None
    target_environment = prepared.get(environment_id) if environment_id else None
    dependency_lock = (
        target_environment["dependency_lock_sha256"]
        if target_environment
        else sha256_file(root / "Cargo.lock")
        if (root / "Cargo.lock").is_file()
        else None
    )
    if not dependency_lock:
        return (
            [],
            {},
            [
                {
                    "scope": "target",
                    "id": target["id"],
                    "kind": "dependency_lock_missing",
                    "message": "target dependency lock file is missing",
                }
            ],
        )
    target_env = dict(env)
    target_env["STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256"] = dependency_lock
    try:
        cmd = _resolve_command(commands[target["identity_command_id"]], prepared, root)
    except ContractError as exc:
        return (
            [],
            {},
            [
                {
                    "scope": "target",
                    "id": target["id"],
                    "kind": "environment_not_prepared",
                    "message": str(exc),
                }
            ],
        )
    response, error = _invoke_adapter(
        cmd, _request("identity", target["id"], None), 30, target_env, "target", target["id"], root
    )
    if error:
        return [], {}, [error]
    try:
        response = _validate_adapter_response(response, "identity", target["id"])
        identity = response["identity"]
        fields = {
            "subject_id",
            "revision",
            "dirty",
            "runtime",
            "backend",
            "features",
            "package_version",
            "os",
            "architecture",
            "dependency_lock_sha256",
        }
        optional_fields = {"target_tree_sha256"}
        if not isinstance(identity, dict) or frozenset(identity) not in {
            frozenset(fields),
            frozenset(fields | optional_fields),
        }:
            raise ContractError("target identity has unknown, missing, or malformed fields")
        if (
            identity["subject_id"] != target["id"]
            or not isinstance(identity["dirty"], bool)
            or not isinstance(identity["features"], list)
        ):
            raise ContractError("target identity does not match the declared target")
        for field in (
            "revision",
            "runtime",
            "backend",
            "package_version",
            "os",
            "architecture",
            "dependency_lock_sha256",
        ):
            if not isinstance(identity[field], str) or not identity[field]:
                raise ContractError(f"target identity {field} must be a non-empty string")
        if any(not isinstance(feature, str) or not feature for feature in identity["features"]):
            raise ContractError("target identity features must be non-empty strings")
        if len(identity["features"]) != len(set(identity["features"])):
            raise ContractError("target identity features must be unique")
        if identity["dependency_lock_sha256"] != dependency_lock:
            raise ContractError(
                "target identity dependency-lock digest differs from the isolated environment"
            )
        if len(dependency_lock) != 64 or any(
            ch not in "0123456789abcdef" for ch in dependency_lock
        ):
            raise ContractError("target dependency-lock digest must be lowercase SHA-256")
        if target_environment and (
            identity["runtime"] != target_environment["runtime"]
            or identity["os"] != target_environment["os"]
            or identity["architecture"] != target_environment["architecture"]
        ):
            raise ContractError(
                "Python target identity differs from its prepared installed-wheel environment"
            )
        tree_sha = identity.get("target_tree_sha256")
        if tree_sha is not None and (
            not isinstance(tree_sha, str)
            or len(tree_sha) != 64
            or any(ch not in "0123456789abcdef" for ch in tree_sha)
        ):
            raise ContractError("target_tree_sha256 must be null or a lowercase SHA-256 digest")
        if (
            target["id"] == "python-package"
            and tree_sha is None
            and isinstance(identity["revision"], str)
            and identity["revision"].startswith("dirty-tree:")
        ):
            tree_sha = identity["revision"].removeprefix("dirty-tree:")
        records = []
        by_profile: dict[str, dict[str, Any]] = {}
        for profile in profiles:
            if (
                identity["backend"] != profile["backend"]
                or identity["features"] != profile["features"]
            ):
                raise ContractError(
                    f"target identity backend/features differ from profile {profile['id']}"
                )
            record = {
                "target_profile": profile["id"],
                "target_id": target["id"],
                "revision": identity["revision"],
                "dirty": identity["dirty"],
                "runtime": identity["runtime"],
                "backend": profile["backend"],
                "features": profile["features"],
                "package_version": identity["package_version"],
                "target_tree_sha256": tree_sha,
                "dependency_lock_sha256": dependency_lock,
                "os": identity["os"],
                "architecture": identity["architecture"],
                "environment_sha256": target_environment["environment_sha256"]
                if target_environment
                else None,
            }
            records.append(record)
            by_profile[profile["id"]] = identity
        return records, by_profile, []
    except (ContractError, KeyError, TypeError) as exc:
        return (
            [],
            {},
            [
                {
                    "scope": "target",
                    "id": target["id"],
                    "kind": "identity_mismatch",
                    "message": str(exc)[:MAX_DIAGNOSTIC],
                }
            ],
        )


def _run_case(
    command: dict[str, Any],
    subject_id: str,
    case: dict[str, Any],
    env: dict[str, str],
    scope: str,
    root: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    response, error = _invoke_adapter(
        command,
        _request("workflow", subject_id, case),
        30,
        env,
        scope,
        f"{subject_id}:{case['case_id']}",
        root,
    )
    if error:
        return None, error
    try:
        response = _validate_adapter_response(response, "workflow", subject_id)
        result = validate_workflow_result(
            response["result"], case["case_id"], f"{subject_id} workflow"
        )
        if result["status"] != "completed":
            actual_observations = [item["step_id"] for item in result["observations"]]
            if actual_observations != case["observations"]:
                raise ContractError(
                    "terminal adapter workflow observation step IDs do not exactly match the input selectors"
                )
            return result, None
        expected_observations = case["observations"]
        actual_observations = [item["step_id"] for item in result["observations"]]
        if actual_observations != expected_observations:
            raise ContractError(
                "workflow observation step IDs do not exactly match the input selectors"
            )
        return result, None
    except (ContractError, KeyError, TypeError) as exc:
        return None, {
            "scope": scope,
            "id": f"{subject_id}:{case['case_id']}",
            "kind": "invalid_adapter_result",
            "message": str(exc)[:MAX_DIAGNOSTIC],
        }


def _skipped_result(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "skipped",
        "observations": [
            {"step_id": step_id, "status": "skipped", "reason": reason}
            for step_id in case["observations"]
        ],
    }


def _unsupported_result(case: dict[str, Any], reason: str) -> dict[str, Any]:
    """Record selectors as unsupported without inventing target observations."""
    return {
        "case_id": case["case_id"],
        "status": "unsupported",
        "observations": [
            {"step_id": step_id, "status": "unsupported", "reason": reason}
            for step_id in case["observations"]
        ],
    }


def _adapter_environment(base: dict[str, str], dependency_lock_sha256: str) -> dict[str, str]:
    env = dict(base)
    env["STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256"] = dependency_lock_sha256
    return env


def _base_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
    ):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    if not env.get("STARLETTE_ORACLE_ROOT") and ORACLE_ROOT_DEFAULT.exists():
        env["STARLETTE_ORACLE_ROOT"] = str(ORACLE_ROOT_DEFAULT)
    return env


def _tool_version(name: str) -> str | None:
    executable = shutil.which(name)
    if executable is None:
        return None
    try:
        process = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if process.returncode != 0:
        return None
    return process.stdout.strip() or None


def _native_environment(
    root: Path, target_identity: dict[str, Any] | None = None
) -> dict[str, Any]:
    cargo_lock = root / "Cargo.lock"
    lock_digest = sha256_file(cargo_lock) if cargo_lock.is_file() else None
    target_identity = target_identity or {}
    rustc = _tool_version("rustc")
    value = {
        "id": "rust-native-local",
        "runtime": target_identity.get("runtime", rustc or "rustc unavailable"),
        "os": target_identity.get("os", platform.platform()),
        "architecture": target_identity.get("architecture", platform.machine()),
        "rustc": rustc,
        "cargo": _tool_version("cargo"),
        "dependency_lock_path": "Cargo.lock",
        "dependency_lock_sha256": lock_digest,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    value["environment_sha256"] = hashlib.sha256(encoded).hexdigest()
    return value


def run_parity(
    root: Path, mode: str, output_path: Path | None = None, manifest_path: Path | None = None
) -> dict[str, Any]:
    if mode not in {"parity", "oracle-only"}:
        raise ContractError("mode must be parity or oracle-only")
    root = root.resolve()
    manifest_file = manifest_path or root / MANIFEST_RELATIVE
    if not manifest_file.is_absolute():
        manifest_file = root / manifest_file
    manifest_file = manifest_file.resolve()
    try:
        manifest_relative = manifest_file.relative_to(root).as_posix()
    except ValueError as exc:
        raise ContractError("active parity manifest must be inside the repository root") from exc
    manifest, indexed_inputs, cases = _load_contract(root, manifest_file)
    commands = _command_map(manifest)
    env = _base_environment()
    environment_errors: list[dict[str, Any]] = []
    try:
        prepared = load_prepared_environments(root, require_target=True)
    except ContractError as exc:
        prepared = {}
        environment_errors.append(
            {
                "scope": "runner",
                "id": "python-environments",
                "kind": "environment_not_prepared",
                "message": str(exc)[:MAX_DIAGNOSTIC],
            }
        )
    if mode == "parity" and len(prepared) != len(ENVIRONMENT_IDS):
        environment_errors.append(
            {
                "scope": "runner",
                "id": "python-environments",
                "kind": "environment_incomplete",
                "message": "parity requires both prepared CPython 3.12 environments",
            }
        )
    started = _now()
    infra: list[dict[str, Any]] = list(environment_errors)
    _oracle_identity_raw, oracle_identity, oracle_error = _oracle_identity(
        manifest, commands, env, prepared, root
    )
    if oracle_error:
        infra.append(oracle_error)

    profiles = _profiles(manifest)
    targets = _target_bindings(manifest)
    target_records: list[dict[str, Any]] = []
    target_identity_by_profile: dict[str, dict[str, Any]] = {}
    target_errors: dict[str, dict[str, Any]] = {}
    if mode == "parity":
        for target_id, target in targets.items():
            target_profiles = [
                profile for profile in profiles.values() if profile["target_id"] == target_id
            ]
            records, identities, errors = _target_identity(
                target, target_profiles, commands, env, prepared, root
            )
            target_records.extend(records)
            target_identity_by_profile.update(identities)
            if errors:
                infra.extend(errors)
                for profile in target_profiles:
                    target_errors[profile["id"]] = errors[0]

    command = commands[mode]
    python_environments = [prepared[key] for key in ENVIRONMENT_IDS if key in prepared]
    environment_records = list(python_environments)
    native_profile_id = next(
        (profile["id"] for profile in profiles.values() if profile["target_id"] == "rust-native"),
        None,
    )
    native_identity = (
        target_identity_by_profile.get(native_profile_id) if native_profile_id else None
    )
    native_environment = _native_environment(root, native_identity)
    if mode == "parity":
        environment_records.append(native_environment)
        for target_record in target_records:
            if target_record["target_id"] == "rust-native":
                target_record["environment_sha256"] = native_environment["environment_sha256"]
    identity = {
        "run_id": str(uuid.uuid4()),
        "started_at": started,
        "finished_at": started,
        "manifest": {
            "path": manifest_relative,
            "schema": MANIFEST_SCHEMA,
            "sha256": sha256_file(manifest_file),
        },
        "inputs": [
            {
                "path": path.relative_to(root).as_posix(),
                "schema": document["schema"],
                "sha256": sha256_file(path),
            }
            for path, document in indexed_inputs
        ],
        "assets": [],
        "oracles": [oracle_identity] if oracle_identity else [],
        "targets": target_records,
        "environments": environment_records,
        "command": {
            "command_id": mode,
            "argv": command["argv"],
            "cwd": command["cwd"],
            "timeout_seconds": command["timeout_seconds"],
        },
    }

    source_results: dict[str, dict[str, Any]] = {}
    if oracle_identity is not None:
        oracle_command = _resolve_command(
            commands[manifest["oracles"][0]["identity_command_id"]], prepared, root
        )
        oracle_environment = prepared[ENVIRONMENT_IDS[0]]
        oracle_env = _adapter_environment(env, oracle_environment["dependency_lock_sha256"])
        for case in cases:
            result, error = _run_case(
                oracle_command, "starlette-python", case, oracle_env, "oracle", root
            )
            if error:
                infra.append(error)
            if result is not None:
                source_results[case["case_id"]] = result

    comparisons: list[dict[str, Any]] = []
    operation_map = _operations(manifest)
    for case in cases:
        operation = operation_map[(case["surface"], case["operation"])]
        source_result = source_results.get(case["case_id"])
        for profile_id in case["target_profiles"]:
            profile = profiles[profile_id]
            target = targets[profile["target_id"]]
            if source_result is None:
                source_for_result = _skipped_result(
                    case, "not run: source oracle identity or workflow failed"
                )
                target_result = _skipped_result(
                    case, "not run: source oracle evidence is unavailable"
                )
                outcome, diffs = "not_run", []
            elif mode == "oracle-only":
                source_for_result = source_result
                target_result = _skipped_result(
                    case,
                    "not run: target intentionally omitted by the explicit oracle-only command",
                )
                outcome, diffs = "not_run", []
            elif source_result["status"] != "completed":
                source_for_result = source_result
                target_result = _skipped_result(
                    case,
                    f"not run: source workflow was {source_result['status']}",
                )
                outcome, diffs = "not_run", []
            elif profile_id in target_errors:
                source_for_result = source_result
                target_result = _skipped_result(
                    case, f"not run: {target_errors[profile_id]['kind']}"
                )
                outcome, diffs = "not_run", []
            else:
                source_for_result = source_result
                unsupported_reason = _declared_unsupported_reason(operation, target["id"], case)
                if unsupported_reason is not None:
                    target_result = _unsupported_result(case, unsupported_reason)
                    outcome, diffs = "not_run", []
                else:
                    target_command = _resolve_command(
                        commands[target["identity_command_id"]], prepared, root
                    )
                    target_environment = (
                        prepared[ENVIRONMENT_IDS[1]] if target["id"] == "python-package" else None
                    )
                    target_lock = (
                        target_environment["dependency_lock_sha256"]
                        if target_environment
                        else sha256_file(root / "Cargo.lock")
                    )
                    target_env = _adapter_environment(env, target_lock)
                    target_result, error = _run_case(
                        target_command, target["id"], case, target_env, "target", root
                    )
                    if error:
                        infra.append(error)
                        target_errors[profile_id] = error
                    if target_result is None:
                        target_result = _skipped_result(
                            case,
                            "not run: target adapter did not produce a valid workflow result",
                        )
                        outcome, diffs = "not_run", []
                    elif error:
                        # Keep the adapter's terminal status and reason in evidence. The
                        # infrastructure error independently prevents this row from passing.
                        outcome, diffs = "not_run", []
                    elif target_result["status"] != "completed":
                        outcome, diffs = "not_run", []
                    else:
                        outcome, diffs = compare_workflows(
                            case, operation, source_result, target_result
                        )
            comparisons.append(
                {
                    "case_id": case["case_id"],
                    "target_profile": profile_id,
                    "requirements": case["covers"],
                    "source": source_for_result,
                    "target": target_result,
                    "outcome": outcome,
                    "diffs": diffs,
                }
            )

    finished = _now()
    identity["finished_at"] = finished
    summary = {
        "selected": len(comparisons),
        "executed": sum(
            1
            for row in comparisons
            if row["source"]["status"] == "completed" and row["target"]["status"] == "completed"
        ),
        "passed": sum(1 for row in comparisons if row["outcome"] == "pass"),
        "failed": sum(1 for row in comparisons if row["outcome"] == "fail"),
        "not_run": sum(1 for row in comparisons if row["outcome"] == "not_run"),
        "infrastructure_errors": len(infra),
    }
    result = {
        "schema": RESULT_SCHEMA,
        "identity": identity,
        "status": "infrastructure_failed" if infra else "completed",
        "summary": summary,
        "comparisons": comparisons,
        "infrastructure_errors": infra,
    }
    validate_result_artifact(result, root=root, manifest_path=manifest_file)
    destination = output_path or root / RESULT_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return result
