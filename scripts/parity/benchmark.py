"""Correctness-gated benchmark execution for declared parity workloads."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contract import (
    BENCHMARK_INPUT_SCHEMA,
    INPUT_SCHEMA,
    ContractError,
    load_manifest,
    sha256_file,
    validate_benchmark_inputs,
    validate_inputs,
    validate_manifest,
    validate_result_artifact,
)
from .envs import ENVIRONMENT_IDS, load_prepared_environments
from .runner import _base_environment, run_parity

BENCHMARK_RESULT_SCHEMA = "migration-parity/benchmark-result@1"
BENCHMARK_RESULT_RELATIVE = Path("build/parity/benchmark-result.json")
GATE_RESULT_RELATIVE = Path("build/parity/benchmark-correctness-result.json")
WORKER_MODULE = "scripts.parity.benchmark_worker"
WORKER_REQUEST_SCHEMA = "starlette-rs-benchmark-worker-request@1"
WORKER_RESULT_SCHEMA = "starlette-rs-benchmark-worker-result@1"
DEFAULT_UPSTREAM = Path("/Users/lazytrot/work/starlette")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_upstream() -> Path:
    value = os.environ.get("STARLETTE_ORACLE_ROOT")
    return Path(value).resolve() if value else DEFAULT_UPSTREAM.resolve()


def _runtime_subjects(workload: dict[str, Any]) -> tuple[str, str, str]:
    expected = [(subject["kind"], subject["id"]) for subject in workload["subjects"]]
    required = [
        ("oracle", "starlette-python"),
        ("target_profile", "rust-native-local"),
        ("target_profile", "python-package-cpython312"),
    ]
    if expected != required:
        raise ContractError("benchmark subjects differ from the active manifest contract")
    return tuple(subject["id"] for subject in workload["subjects"])


def _parity_gate(
    root: Path,
    manifest_path: Path,
    workload: dict[str, Any],
) -> dict[str, Any]:
    gate_path = root / GATE_RESULT_RELATIVE
    result = run_parity(root, "parity", gate_path, manifest_path)
    case_id = workload["input"]["case_id"]
    target_profiles = {
        subject["id"] for subject in workload["subjects"] if subject["kind"] == "target_profile"
    }
    comparisons = [
        row
        for row in result["comparisons"]
        if row["case_id"] == case_id and row["target_profile"] in target_profiles
    ]
    # Gate this workload on its declared input/profile comparisons. The full
    # parity artifact also retains unrelated failures and unsupported rows;
    # those remain visible without invalidating an independently passing gate.
    passed = not (
        result["status"] in {"cancelled", "invalid"}
        or len(comparisons) != len(target_profiles)
        or any(row["outcome"] != "pass" for row in comparisons)
    )
    return {
        "status": "pass" if passed else "failed",
        "case_id": case_id,
        "parity_run_id": result["identity"]["run_id"],
        "parity_result_path": GATE_RESULT_RELATIVE.as_posix(),
        "parity_result_sha256": sha256_file(gate_path),
        "profiles": sorted(target_profiles),
        "summary": result["summary"],
        "oracles": result["identity"]["oracles"],
        "targets": result["identity"]["targets"],
        "comparison_outcomes": [
            {"target_profile": row["target_profile"], "outcome": row["outcome"]}
            for row in comparisons
        ],
        "infrastructure_errors": result["infrastructure_errors"],
    }


def _unmeasured_subject_rows(
    workload: dict[str, Any],
    parity_artifact: dict[str, Any],
    reason: str,
) -> list[dict[str, Any]]:
    oracle = parity_artifact["identity"].get("oracles", [])
    targets = {row["target_profile"]: row for row in parity_artifact["identity"].get("targets", [])}
    subjects: list[dict[str, Any]] = []
    for subject in workload["subjects"]:
        subject_id = subject["id"]
        if subject["kind"] == "oracle":
            identity = oracle[0] if oracle else None
        else:
            identity = targets.get(subject_id)
        subjects.append(
            {
                "subject_id": subject_id,
                "status": "not_run",
                "identity": identity,
                "reason": reason,
            }
        )
    return subjects


def _artifact_identity(
    root: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    benchmark_inputs: list[tuple[Path, dict[str, Any]]],
    source_validation: dict[str, Any],
    gate: dict[str, Any],
    prepared: dict[str, dict[str, Any]],
    started_at: str,
    native_adapter: dict[str, Any],
    parity_case_input: dict[str, str],
) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "started_at": started_at,
        "finished_at": _timestamp(),
        "manifest": {
            "path": manifest_path.relative_to(root).as_posix(),
            "schema": manifest["schema"],
            "sha256": sha256_file(manifest_path),
        },
        "benchmark_inputs": [
            {
                "path": path.relative_to(root).as_posix(),
                "schema": document["schema"],
                "sha256": sha256_file(path),
            }
            for path, document in benchmark_inputs
        ],
        "parity_case_input": parity_case_input,
        "source_validation": source_validation,
        "parity_gate": gate,
        "native_parity_adapter": native_adapter,
        "prepared_environments": [
            {key: value for key, value in environment.items() if key != "target_identity"}
            for environment in prepared.values()
        ],
        "machine": {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python": sys.version,
            "python_executable": str(Path(sys.executable).resolve()),
            "rustc": _tool_version("rustc"),
            "cargo": _tool_version("cargo"),
        },
        "command": {
            "argv": [str(Path(sys.executable).resolve()), "-m", "scripts.parity.cli", "benchmark"],
            "cwd": str(root),
        },
    }


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
    return process.stdout.strip() if process.returncode == 0 else None


def _upstream_workload_rows(
    router_callable: bool | None,
    gzip_available: bool | None,
    prerequisite_reason: str | None = None,
) -> list[dict[str, str]]:
    router_ids = [
        "test_routing_static_early",
        "test_routing_static_late",
        "test_routing_param_late",
        "test_routing_miss",
        "test_routing_method_not_allowed",
        "test_routing_small_app",
    ]
    gzip_ids = [
        f"test_gzip[{payload}-{size}-level-{level}]"
        for payload in ("json", "text", "incompressible")
        for size, levels in (
            ("1MiB", range(1, 10)),
            ("32KiB", (1, 6, 9)),
            ("256KiB", (1, 6, 9)),
            ("5MiB", (1, 6, 9)),
            ("10MiB", (1, 6, 9)),
        )
        for level in levels
    ]
    bypass_ids = [
        f"test_gzip_bypass[{reason}]"
        for reason in (
            "below-minimum-size",
            "content-encoding",
            "event-stream",
            "pathsend",
        )
    ]
    if prerequisite_reason is None and (router_callable is None or gzip_available is None):
        raise ContractError("upstream capability status requires a completed capability probe")
    rows: list[dict[str, str]] = []
    for workload_id in router_ids:
        reason = prerequisite_reason or (
            "The installed package Router instance is not an ASGI callable, so the upstream Router ASGI "
            "timing boundary has no equivalent target call."
            if not router_callable
            else "This upstream Router workload lacks a manifest-backed exact parity input."
        )
        rows.append(
            {
                "workload_id": workload_id,
                "category": "router",
                "status": "not_run",
                "reason": str(reason),
            }
        )
    for workload_id in gzip_ids + bypass_ids + ["test_gzip_event_loop_responsiveness"]:
        reason = prerequisite_reason or (
            "The installed wheel has no starlette.middleware.gzip module or GZipMiddleware implementation."
            if not gzip_available
            else "This upstream GZip workload lacks a manifest-backed exact parity input."
        )
        rows.append(
            {"workload_id": workload_id, "category": "gzip", "status": "not_run", "reason": reason}
        )
    if len(rows) != 74:
        raise ContractError(
            f"pinned Starlette workload inventory changed: expected 74, found {len(rows)}"
        )
    return rows


def _build_native_parity_adapter(root: Path, prepared: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target_python = root / prepared[ENVIRONMENT_IDS[1]]["python"]
    env = _base_environment()
    env["PYO3_PYTHON"] = str(target_python)
    argv = ["cargo", "build", "--locked", "--bin", "starlette-rs-parity-adapter"]
    try:
        process = subprocess.run(
            argv,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(
            f"cannot build the exact Rust parity adapter for the correctness gate: {exc}"
        ) from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()[-3000:]
        raise ContractError(f"Rust parity adapter build failed: {detail}")
    binary = root / "target/debug/starlette-rs-parity-adapter"
    if not binary.is_file():
        raise ContractError(
            "Cargo reported success but did not produce the parity adapter executable"
        )
    return {
        "argv": argv,
        "path": binary.relative_to(root).as_posix(),
        "sha256": sha256_file(binary),
    }


def _worker(
    root: Path,
    python: Path,
    subject_id: str,
    mode: str,
    measurement: dict[str, Any],
    workload_input: dict[str, Any],
    parity_case_input: dict[str, str],
    expected_observation: dict[str, Any] | None,
    upstream: Path,
    source_revision: str,
    target_tree_sha256: str | None = None,
    wheel_sha256: str | None = None,
) -> dict[str, Any]:
    request = {
        "schema": WORKER_REQUEST_SCHEMA,
        "subject_id": subject_id,
        "mode": mode,
        "measurement": measurement,
        "workload_input": workload_input,
        "parity_case_input": parity_case_input,
        "expected_observation": expected_observation,
    }
    env = _base_environment()
    env["STARLETTE_ORACLE_ROOT"] = str(upstream)
    env["STARLETTE_BENCHMARK_SOURCE_REVISION"] = source_revision
    if target_tree_sha256 is not None:
        env["STARLETTE_BENCHMARK_TARGET_TREE_SHA256"] = target_tree_sha256
    if wheel_sha256 is not None:
        env["STARLETTE_BENCHMARK_WHEEL_SHA256"] = wheel_sha256
    try:
        process = subprocess.run(
            [str(python), "-m", WORKER_MODULE],
            cwd=root,
            env=env,
            input=json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n",
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"benchmark worker failed to run for {subject_id}: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.strip()[-3000:] or f"worker exited {process.returncode}"
        raise ContractError(f"benchmark worker failed for {subject_id}: {detail}")
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError(f"benchmark worker for {subject_id} must emit one JSON record")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"benchmark worker for {subject_id} emitted invalid JSON: {exc}"
        ) from exc
    if not isinstance(result, dict) or result.get("schema") != WORKER_RESULT_SCHEMA:
        raise ContractError(f"benchmark worker for {subject_id} emitted the wrong result schema")
    if result.get("identity", {}).get("subject_id") != subject_id:
        raise ContractError(f"benchmark worker identity changed subject: {subject_id}")
    if result.get("parity_case_input") != parity_case_input:
        raise ContractError(
            f"benchmark worker resolved a different parity case input: {subject_id}"
        )
    return result


def _python_subject_environment(
    root: Path,
    subject_id: str,
    prepared: dict[str, dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    if subject_id == "starlette-python":
        environment_id = ENVIRONMENT_IDS[0]
    elif subject_id == "python-package-cpython312":
        environment_id = ENVIRONMENT_IDS[1]
    else:
        raise ContractError(f"no Python benchmark environment for {subject_id}")
    environment = prepared[environment_id]
    python_relative = Path(environment["python"])
    if python_relative.is_absolute() or ".." in python_relative.parts:
        raise ContractError("prepared benchmark interpreter path must remain repository-relative")
    python = root / python_relative
    if not python.is_file():
        raise ContractError(f"prepared benchmark interpreter is missing: {environment['python']}")
    return python, environment


def _measurement_policy(workload: dict[str, Any]) -> dict[str, Any]:
    measurement = workload["measurement"]
    if measurement["boundary"] != "observed_steps" or measurement["step_ids"] != ["dispatch"]:
        raise ContractError("only the declared direct dispatch measurement boundary is implemented")
    if measurement["metrics"] != ["latency"]:
        raise ContractError("the declared smoke workload requires latency only")
    if measurement["correctness_gate"] != "parity_pass":
        raise ContractError("the declared smoke workload requires a parity_pass correctness gate")
    return {
        "step_ids": measurement["step_ids"],
        "warmup_iterations": measurement["warmup_iterations"],
        "measurement_iterations": measurement["measurement_iterations"],
        "samples": measurement["samples"],
        "cache_state": measurement["cache_state"],
        "concurrency": measurement["concurrency"],
    }


def _validate_worker_identity(
    root: Path,
    result: dict[str, Any],
    subject_id: str,
    environment: dict[str, Any],
    expected_target_tree_sha256: str | None = None,
) -> None:
    identity = result["identity"]
    if identity["runtime"] != environment["runtime"]:
        raise ContractError(f"{subject_id} worker runtime differs from its prepared environment")
    if (
        identity["os"] != environment["os"]
        or identity["architecture"] != environment["architecture"]
    ):
        raise ContractError(f"{subject_id} worker platform differs from its prepared environment")
    python_relative = Path(environment["python"])
    environment_root = (root / python_relative).parent.parent.resolve()
    if identity["environment_prefix"] != str(environment_root):
        raise ContractError(f"{subject_id} worker did not use its isolated environment prefix")
    if subject_id == "starlette-python":
        source_package = Path(_load_upstream()) / "starlette"
        if identity["starlette_version"] != "1.6.0" or not Path(
            identity["module_path"]
        ).is_relative_to(source_package.resolve()):
            raise ContractError("source worker import does not match the pinned Starlette source")
        return
    if identity["package_version"] != "0.1.0":
        raise ContractError(
            "installed package version differs from the prepared starlette-rs-py wheel"
        )
    if identity["wheel_sha256"] != environment["artifact_sha256"]:
        raise ContractError("installed wheel hash differs from the prepared target artifact")
    if identity["target_tree_sha256"] != expected_target_tree_sha256:
        raise ContractError(
            "installed-wheel worker source-tree identity differs from the parity handshake"
        )
    if not Path(identity["module_path"]).is_relative_to(environment_root):
        raise ContractError(
            "Starlette compatibility modules did not load from the prepared installed-wheel environment"
        )
    if not Path(identity["core_extension_path"]).is_relative_to(environment_root):
        raise ContractError(
            "target extension did not load from the prepared installed-package environment"
        )


def _write_result(root: Path, result: dict[str, Any]) -> None:
    validate_result_artifact(result)
    destination = root / BENCHMARK_RESULT_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)


def run_benchmark(root: Path, manifest_path: Path) -> dict[str, Any]:
    root = root.resolve()
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest)
    indexed_inputs, cases = validate_inputs(root, manifest)
    benchmark_inputs = validate_benchmark_inputs(root, manifest, cases)
    smoke_benchmark_inputs = [
        row for row in benchmark_inputs if row[1].get("schema") == BENCHMARK_INPUT_SCHEMA
    ]
    if len(smoke_benchmark_inputs) != 1 or len(smoke_benchmark_inputs[0][1]["workloads"]) != 1:
        raise ContractError("the active manifest must contain one explicit benchmark workload")
    _input_path, benchmark_document = smoke_benchmark_inputs[0]
    workload = benchmark_document["workloads"][0]
    _runtime_subjects(workload)
    by_case = {case["case_id"]: case for case in cases}
    case_id = workload["input"]["case_id"]
    if case_id not in by_case:
        raise ContractError(
            "benchmark workload references a parity case outside the active input set"
        )
    case_sources = {
        case["case_id"]: (path, case)
        for path, document in indexed_inputs
        if document.get("schema") == INPUT_SCHEMA
        for case in document["cases"]
    }
    case_path, parity_case = case_sources[case_id]
    parity_case_input = {
        "case_id": case_id,
        "path": case_path.relative_to(root).as_posix(),
        "sha256": sha256_file(case_path),
        "case_sha256": hashlib.sha256(
            json.dumps(
                parity_case,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    measurement = _measurement_policy(workload)
    upstream = _load_upstream()

    from .cli import validate_repository

    source_validation_report = validate_repository(root, manifest_path, upstream)
    if source_validation_report["oracle_commit"] != manifest["scope"]["inventory"]["revision"]:
        raise ContractError("source identity differs from the pinned manifest revision")
    if (
        source_validation_report["scope_id"] != manifest["scope"]["id"]
        or source_validation_report["scope_mode"] != manifest["scope"]["mode"]
        or source_validation_report["manifest_inventory_revision"]
        != manifest["scope"]["inventory"]["revision"]
        or source_validation_report["source_checkout_checked"] is not True
    ):
        raise ContractError("source validation report differs from the active manifest")
    source_validation = {
        "schema": source_validation_report["schema"],
        "scope_mode": source_validation_report["scope_mode"],
        "scope_id": source_validation_report["scope_id"],
        "oracle_commit": source_validation_report["oracle_commit"],
        "oracle_package": source_validation_report["oracle_package"],
        "runtime_dependency_lock_sha256": source_validation_report[
            "runtime_dependency_lock_sha256"
        ],
        "indexed_input_files": source_validation_report["indexed_parity_input_files"],
        "cases": source_validation_report["cases"],
        "target_profiles": source_validation_report["target_profiles"],
        "operations": source_validation_report["operations"],
        "parity_tooling_sources_compiled": source_validation_report[
            "parity_tooling_sources_compiled"
        ],
        "parity_passes_claimed": source_validation_report["parity_passes_claimed"],
    }

    prepared = load_prepared_environments(root, require_target=True)
    started_at = _timestamp()
    native_adapter = _build_native_parity_adapter(root, prepared)
    gate = _parity_gate(root, manifest_path, workload)
    parity_artifact = json.loads((root / GATE_RESULT_RELATIVE).read_text(encoding="utf-8"))
    oracle_rows = parity_artifact["identity"].get("oracles", [])
    source_revision = (
        oracle_rows[0]["revision"] if oracle_rows else manifest["scope"]["inventory"]["revision"]
    )

    if gate["status"] != "pass":
        reason = "fresh exact parity gate failed; no benchmark samples were collected"
        failed_workload = {
            "workload_id": workload["workload_id"],
            "covers": workload["covers"],
            "input": workload["input"],
            "correctness_gate": gate,
            "measurement_policy": workload["measurement"],
            "subjects": _unmeasured_subject_rows(workload, parity_artifact, reason),
            "comparison": {"status": "not_run", "reason": reason},
        }
        result = {
            "schema": BENCHMARK_RESULT_SCHEMA,
            "identity": _artifact_identity(
                root,
                manifest,
                manifest_path,
                smoke_benchmark_inputs,
                source_validation,
                gate,
                prepared,
                started_at,
                native_adapter,
                parity_case_input,
            ),
            "status": "not_proven",
            "summary": {
                "declared_workloads": 1,
                "measured_workloads": 0,
                "measured_subjects": 0,
                "not_run_subjects": len(workload["subjects"]),
                "source_documented_workloads": 74,
                "source_documented_workloads_matched": 0,
                "source_documented_workloads_not_run": 74,
            },
            "workloads": [failed_workload],
            "upstream_suite": {
                "status": "not_run",
                "source_revision": source_revision,
                "documented_workload_count": 74,
                "matched_workload_count": 0,
                "not_run_workload_count": 74,
                "reason": str(reason),
                "workloads": _upstream_workload_rows(
                    router_callable=None,
                    gzip_available=None,
                    prerequisite_reason=reason,
                ),
            },
        }
        _write_result(root, result)
        return result

    package_target = next(
        (
            row
            for row in parity_artifact["identity"]["targets"]
            if row["target_profile"] == "python-package-cpython312"
        ),
        None,
    )
    if package_target is None:
        raise ContractError("fresh parity identity omits the installed-wheel target profile")

    source_python, source_environment = _python_subject_environment(
        root, "starlette-python", prepared
    )
    package_python, package_environment = _python_subject_environment(
        root, "python-package-cpython312", prepared
    )
    source_probe = _worker(
        root,
        source_python,
        "starlette-python",
        "probe",
        {},
        workload["input"],
        parity_case_input,
        None,
        upstream,
        source_revision,
    )
    package_probe = _worker(
        root,
        package_python,
        "python-package-cpython312",
        "probe",
        {},
        workload["input"],
        parity_case_input,
        None,
        upstream,
        source_revision,
        package_target["target_tree_sha256"],
        package_environment["artifact_sha256"],
    )
    _validate_worker_identity(root, source_probe, "starlette-python", source_environment)
    _validate_worker_identity(
        root,
        package_probe,
        "python-package-cpython312",
        package_environment,
        package_target["target_tree_sha256"],
    )
    if source_probe["observation"] != package_probe["observation"]:
        raise ContractError("direct ASGI dispatch observations differ after the exact parity gate")
    if source_probe["parity_case_input"] != package_probe["parity_case_input"]:
        raise ContractError("source and package workers resolved different parity case inputs")

    source_measurement = _worker(
        root,
        source_python,
        "starlette-python",
        "measure",
        measurement,
        workload["input"],
        parity_case_input,
        source_probe["observation"],
        upstream,
        source_revision,
    )
    package_measurement = _worker(
        root,
        package_python,
        "python-package-cpython312",
        "measure",
        measurement,
        workload["input"],
        parity_case_input,
        source_probe["observation"],
        upstream,
        source_revision,
        package_target["target_tree_sha256"],
        package_environment["artifact_sha256"],
    )
    _validate_worker_identity(root, source_measurement, "starlette-python", source_environment)
    _validate_worker_identity(
        root,
        package_measurement,
        "python-package-cpython312",
        package_environment,
        package_target["target_tree_sha256"],
    )
    if (
        source_measurement["capabilities"] != source_probe["capabilities"]
        or package_measurement["capabilities"] != package_probe["capabilities"]
    ):
        raise ContractError(
            "benchmark workload capabilities changed between correctness probe and measurement"
        )

    source_samples = source_measurement["measurement"]["samples"]
    source_median = source_measurement["measurement"]["statistics"]["median"]
    package_median = package_measurement["measurement"]["statistics"]["median"]
    workload_result = {
        "workload_id": workload["workload_id"],
        "covers": workload["covers"],
        "input": workload["input"],
        "correctness_gate": {
            **gate,
            "observation_sha256": hashlib.sha256(
                json.dumps(
                    source_probe["observation"],
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "exact_source_package_observations": "pass",
        },
        "measurement_policy": workload["measurement"],
        "subjects": [
            {
                "subject_id": "starlette-python",
                "status": "measured",
                "identity": source_measurement["identity"],
                "capabilities": source_measurement["capabilities"],
                "measurement": source_measurement["measurement"],
            },
            {
                "subject_id": "rust-native-local",
                "status": "not_run",
                "identity": next(
                    row
                    for row in parity_artifact["identity"]["targets"]
                    if row["target_profile"] == "rust-native-local"
                ),
                "reason": (
                    "The manifest requires this profile, but starlette-rs exposes a Rust-native future API that "
                    "accepts only path/method and does not implement the Python Starlette.__call__ ASGI boundary. "
                    "Timing it as though it were the same dispatch would omit observable scope, endpoint, Request, "
                    "event-loop, and ASGI callback work."
                ),
            },
            {
                "subject_id": "python-package-cpython312",
                "status": "measured",
                "identity": package_measurement["identity"],
                "capabilities": package_measurement["capabilities"],
                "measurement": package_measurement["measurement"],
            },
        ],
        "comparison": {
            "status": "measured",
            "source_subject_id": "starlette-python",
            "target_subject_id": "python-package-cpython312",
            "latency_unit": "nanoseconds_per_dispatch",
            "source_median": source_median,
            "target_median": package_median,
            "target_over_source_median_ratio": package_median / source_median,
            "source_over_target_median_speedup": source_median / package_median,
            "sample_count": len(source_samples),
            "measurement_iterations_per_sample": workload["measurement"]["measurement_iterations"],
        },
    }

    router_callable = package_probe["capabilities"]["router_instance_is_asgi_callable"]
    gzip_available = package_probe["capabilities"]["gzip_middleware_module_available"]
    upstream_workloads = _upstream_workload_rows(router_callable, gzip_available)
    upstream_benchmark_files = [
        upstream / "benchmarks/README.md",
        upstream / "benchmarks/routing_benchmark.py",
        upstream / "benchmarks/gzip_benchmark.py",
    ]
    if any(not path.is_file() for path in upstream_benchmark_files):
        raise ContractError("one or more pinned upstream benchmark source files are missing")
    upstream_suite = {
        "status": "not_run",
        "source_revision": source_revision,
        "documented_workload_count": 74,
        "matched_workload_count": 0,
        "not_run_workload_count": 74,
        "source_files": [
            {
                "path": path.relative_to(upstream).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in upstream_benchmark_files
        ],
        "source_workload_categories": [
            {
                "name": "router",
                "count": 6,
                "source_supported": source_probe["capabilities"][
                    "router_instance_is_asgi_callable"
                ],
                "target_supported": router_callable,
                "target_status": "blocked" if not router_callable else "not_implemented",
                "not_run_count": sum(row["category"] == "router" for row in upstream_workloads),
            },
            {
                "name": "gzip",
                "count": 68,
                "source_supported": source_probe["capabilities"][
                    "gzip_middleware_module_available"
                ],
                "target_supported": gzip_available,
                "target_status": "blocked" if not gzip_available else "not_implemented",
                "not_run_count": sum(row["category"] == "gzip" for row in upstream_workloads),
            },
        ],
        "workloads": upstream_workloads,
    }
    measured_ids = {
        item["subject_id"] for item in workload_result["subjects"] if item["status"] == "measured"
    }
    not_run_ids = {
        item["subject_id"] for item in workload_result["subjects"] if item["status"] == "not_run"
    }
    completed = not not_run_ids and router_callable and gzip_available
    result = {
        "schema": BENCHMARK_RESULT_SCHEMA,
        "identity": _artifact_identity(
            root,
            manifest,
            manifest_path,
            smoke_benchmark_inputs,
            source_validation,
            gate,
            prepared,
            started_at,
            native_adapter,
            parity_case_input,
        ),
        "status": "completed" if completed else "not_proven",
        "summary": {
            "declared_workloads": 1,
            "measured_workloads": 1
            if {"starlette-python", "python-package-cpython312"} <= measured_ids
            else 0,
            "measured_subjects": len(measured_ids),
            "not_run_subjects": len(not_run_ids),
            "source_documented_workloads": 74,
            "source_documented_workloads_matched": upstream_suite["matched_workload_count"],
            "source_documented_workloads_not_run": upstream_suite["not_run_workload_count"],
        },
        "workloads": [workload_result],
        "upstream_suite": upstream_suite,
    }
    _write_result(root, result)
    return result
