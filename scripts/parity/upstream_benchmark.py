"""Run the pinned Starlette Router/GZip benchmarks with exact input-driven gates."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contract import (
    ORACLE_COMMIT,
    ContractError,
    load_manifest,
    sha256_file,
    validate_benchmark_inputs,
    validate_inputs,
    validate_manifest,
)
from .envs import ENVIRONMENT_IDS, load_prepared_environments
from .runner import _base_environment, run_parity
from .upstream_benchmark_contract import live_relation_kinds

UPSTREAM_INPUT_SCHEMA = "migration-parity/upstream-benchmark-input@1"
UPSTREAM_RESULT_SCHEMA = "migration-parity/upstream-benchmark-result@1"
UPSTREAM_INPUT_RELATIVE = Path("build/parity/inputs/benchmark/starlette-upstream-workloads.json")
UPSTREAM_RESULT_RELATIVE = Path("build/parity/upstream-benchmark-result.json")
GATE_RESULT_RELATIVE = Path("build/parity/upstream-benchmark-correctness-result.json")
WORKER_MODULE = "scripts.parity.upstream_benchmark_worker"
WORKER_REQUEST_SCHEMA = "starlette-rs-upstream-benchmark-worker-request@1"
WORKER_RESULT_SCHEMA = "starlette-rs-upstream-benchmark-worker-result@1"
PYTHON_SUBJECTS = ("starlette-python", "python-package-cpython312")
DEFAULT_UPSTREAM = Path("/Users/lazytrot/work/starlette")


def _measurement_order(workload_index: int) -> tuple[str, str]:
    """Counterbalance subject order across the validated catalog sequence."""
    return PYTHON_SUBJECTS if workload_index % 2 == 0 else tuple(reversed(PYTHON_SUBJECTS))


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _upstream_root() -> Path:
    value = os.environ.get("STARLETTE_ORACLE_ROOT")
    return Path(value).resolve() if value else DEFAULT_UPSTREAM.resolve()


def _source_revision(upstream: Path) -> str:
    try:
        revision = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot inspect pinned Starlette revision: {exc}") from exc
    if revision != ORACLE_COMMIT:
        raise ContractError(f"expected Starlette source revision {ORACLE_COMMIT}, found {revision}")
    version_file = upstream / "starlette/__init__.py"
    if not version_file.is_file() or '__version__ = "1.6.0"' not in version_file.read_text(
        encoding="utf-8"
    ):
        raise ContractError("upstream source does not identify as Starlette 1.6.0")
    try:
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(upstream),
                "diff",
                "--quiet",
                "HEAD",
                "--",
                "starlette",
                "benchmarks",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        untracked = subprocess.run(
            [
                "git",
                "-C",
                str(upstream),
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                "starlette",
                "benchmarks",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot verify pinned Starlette source contents: {exc}") from exc
    if dirty.returncode != 0 or untracked:
        raise ContractError("Starlette source or benchmark files differ from the pinned commit")
    return revision


def _python_for_subject(
    root: Path, subject_id: str, prepared: dict[str, dict[str, Any]]
) -> tuple[Path, dict[str, Any]]:
    environment_id = {
        "starlette-python": ENVIRONMENT_IDS[0],
        "python-package-cpython312": ENVIRONMENT_IDS[1],
    }.get(subject_id)
    if environment_id is None:
        raise ContractError(f"unsupported benchmark subject {subject_id!r}")
    environment = prepared[environment_id]
    relative = Path(environment["python"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError(f"{environment_id} interpreter path must remain repository-relative")
    python = root / relative
    if not python.is_file():
        raise ContractError(f"prepared Python interpreter is missing: {relative}")
    return python, environment


def _run_worker(
    root: Path,
    python: Path,
    subject_id: str,
    mode: str,
    workload: dict[str, Any],
    upstream: Path,
    source_revision: str,
    target_tree_sha256: str | None,
    wheel_sha256: str | None,
    expected_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "schema": WORKER_REQUEST_SCHEMA,
        "subject_id": subject_id,
        "mode": mode,
        "workload": workload,
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
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"{subject_id} {mode} worker failed to run: {exc}") from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout).strip()[-3000:]
        raise ContractError(f"{subject_id} {mode} worker failed: {detail or process.returncode}")
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError(f"{subject_id} {mode} worker must emit one JSON record")
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ContractError(f"{subject_id} {mode} worker emitted invalid JSON: {exc}") from exc
    if not isinstance(result, dict) or result.get("schema") != WORKER_RESULT_SCHEMA:
        raise ContractError(f"{subject_id} {mode} worker emitted the wrong schema")
    if result.get("workload_id") != workload["workload_id"] or result.get("mode") != mode:
        raise ContractError(f"{subject_id} {mode} worker changed the workload identity")
    if result.get("status") not in {"completed", "not_run"}:
        raise ContractError(f"{subject_id} {mode} worker returned an unsupported status")
    return result


def _normalize_allow_tokens(observation: Any, unordered_headers: list[str] | None = None) -> Any:
    """Apply only the descriptor-declared header-token ordering exceptions."""
    names = {item.lower().encode("ascii") for item in (unordered_headers or [])}

    def normalize(value: Any) -> Any:
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        normalized = {key: normalize(item) for key, item in value.items()}
        events = normalized.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict) or event.get("type") != "http.response.start":
                    continue
                headers = event.get("headers")
                if not isinstance(headers, list):
                    continue
                for header in headers:
                    if not isinstance(header, list) or len(header) != 2:
                        continue
                    try:
                        name = base64.b64decode(header[0], validate=True).lower()
                        raw_value = base64.b64decode(header[1], validate=True)
                    except (TypeError, ValueError):
                        continue
                    if name in names:
                        tokens = sorted(part.strip() for part in raw_value.split(b","))
                        header[1] = base64.b64encode(b", ".join(tokens)).decode("ascii")
        return normalized

    return normalize(observation)


def _first_difference(left: Any, right: Any, path: str = "$") -> dict[str, Any] | None:
    if type(left) is not type(right):
        return {
            "path": path,
            "source_type": type(left).__name__,
            "target_type": type(right).__name__,
        }
    if isinstance(left, dict):
        if set(left) != set(right):
            return {
                "path": path,
                "source_keys": sorted(left),
                "target_keys": sorted(right),
            }
        for key in sorted(left):
            found = _first_difference(left[key], right[key], f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return {"path": path, "source_length": len(left), "target_length": len(right)}
        for index, (source_value, target_value) in enumerate(zip(left, right, strict=True)):
            found = _first_difference(source_value, target_value, f"{path}[{index}]")
            if found is not None:
                return found
        return None
    if left == right:
        return None
    if isinstance(left, str) and isinstance(right, str) and max(len(left), len(right)) > 256:
        return {
            "path": path,
            "source_length": len(left),
            "target_length": len(right),
            "source_sha256": hashlib.sha256(left.encode("utf-8")).hexdigest(),
            "target_sha256": hashlib.sha256(right.encode("utf-8")).hexdigest(),
        }
    return {"path": path, "source": left, "target": right}


def _identity_check(
    root: Path,
    result: dict[str, Any],
    subject_id: str,
    environment: dict[str, Any],
    upstream: Path,
    source_revision: str,
    target_tree_sha256: str | None,
) -> None:
    identity = result.get("identity")
    if not isinstance(identity, dict) or identity.get("subject_id") != subject_id:
        raise ContractError(f"worker did not identify subject {subject_id}")
    if identity.get("runtime") != environment["runtime"]:
        raise ContractError(f"{subject_id} worker runtime differs from its prepared environment")
    if (
        identity.get("os") != environment["os"]
        or identity.get("architecture") != environment["architecture"]
    ):
        raise ContractError(f"{subject_id} worker platform differs from its prepared environment")
    prefix = (root / Path(environment["python"])).parent.parent.resolve()
    expected_python = (root / Path(environment["python"])).resolve()
    if identity.get("environment_prefix") != str(prefix) or identity.get(
        "python_executable"
    ) != str(expected_python):
        raise ContractError(f"{subject_id} worker used the wrong isolated environment")
    module_path = Path(identity.get("module_path", "")).resolve()
    if subject_id == "starlette-python":
        expected_package = (upstream / "starlette").resolve()
        if (
            identity.get("starlette_version") != "1.6.0"
            or not module_path.is_relative_to(expected_package)
            or identity.get("source_revision") != source_revision
        ):
            raise ContractError("source worker identity differs from pinned Starlette 1.6.0")
    else:
        if (
            identity.get("package_version") != "0.1.0"
            or identity.get("wheel_sha256") != environment["artifact_sha256"]
            or identity.get("target_tree_sha256") != target_tree_sha256
            or not module_path.is_relative_to(prefix)
        ):
            raise ContractError(
                "package worker identity differs from the prepared starlette-rs-py wheel"
            )
        extension = Path(identity.get("core_extension_path", "")).resolve()
        if not extension.is_relative_to(prefix) or not extension.is_file():
            raise ContractError(
                "Rust extension did not load from the installed package environment"
            )


def _write_result(root: Path, result: dict[str, Any], expected_ids: list[str]) -> None:
    _validate_result(result, expected_ids)
    destination = root / UPSTREAM_RESULT_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(destination)


def _benchmark_source_digests(upstream: Path) -> list[dict[str, str]]:
    paths = (
        upstream / "benchmarks/routing_benchmark.py",
        upstream / "benchmarks/gzip_benchmark.py",
    )
    if any(not path.is_file() for path in paths):
        raise ContractError("one or more pinned Starlette benchmark source files are missing")
    return [
        {"path": path.relative_to(upstream).as_posix(), "sha256": sha256_file(path)}
        for path in paths
    ]


def _validate_worker_relations(
    result: dict[str, Any], workload: dict[str, Any], context: str
) -> list[dict[str, str]]:
    actual = result.get("input_relations")
    expected_kinds = [relation["kind"] for relation in workload["observations"]["input_relations"]]
    expected_kinds.extend(live_relation_kinds(workload["input"]["kind"]))
    if not isinstance(actual, list):
        raise ContractError(f"{context} omitted input-relation evidence")
    kinds = [row.get("relation") for row in actual if isinstance(row, dict)]
    if kinds != expected_kinds or len(actual) != len(expected_kinds):
        raise ContractError(f"{context} did not validate every declared input relation")
    if any(row.get("status") != "pass" for row in actual):
        raise ContractError(f"{context} failed a declared input relation")
    return actual


def _validate_measurement_policy(
    result: dict[str, Any], policy: dict[str, Any], context: str
) -> dict[str, Any]:
    measurement = result.get("measurement")
    if not isinstance(measurement, dict):
        raise ContractError(f"{context} omitted timing results")
    if (
        measurement.get("unit") != "nanoseconds_per_operation"
        or measurement.get("warmup_iterations") != policy["warmup_iterations"]
        or measurement.get("iterations_per_sample") != policy["iterations_per_sample"]
        or not isinstance(measurement.get("samples"), list)
        or len(measurement["samples"]) != policy["samples"]
    ):
        raise ContractError(f"{context} timing results do not match the declared runner policy")
    if policy.get("sample_statistic") != "mean_call_duration":
        raise ContractError(f"{context} sample aggregation differs from the declared runner policy")
    values = measurement["samples"]
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
        for value in values
    ):
        raise ContractError(f"{context} samples must be positive numeric durations")
    statistics = measurement.get("statistics")
    if (
        not isinstance(statistics, dict)
        or not isinstance(statistics.get("median"), (int, float))
        or isinstance(statistics.get("median"), bool)
        or not math.isfinite(statistics["median"])
        or statistics["median"] <= 0
    ):
        raise ContractError(f"{context} omitted summary statistics")
    return measurement


def _native_not_run(category: str, identity: dict[str, Any] | None) -> dict[str, Any]:
    boundary = (
        "The Rust-native API does not expose Starlette Router.__call__ as an ASGI callable, so it cannot include route dispatch, scope mutation, loop entry, and send collection at the same boundary."
        if category == "router"
        else "The Rust-native API does not expose GZipMiddleware as a complete async ASGI boundary, so it cannot include response events, scheduling, compression, and send collection at the same boundary."
    )
    return {
        "subject_id": "rust-native-local",
        "status": "not_run",
        "identity": identity,
        "reason": boundary,
    }


def _profile_parity_gate_passes(
    result: dict[str, Any], profile_id: str, expected_case_ids: list[str]
) -> bool:
    """Require one passing live comparison for every case selected by a profile."""
    comparisons = result.get("comparisons")
    if not isinstance(comparisons, list):
        return False
    profile_rows = [
        row
        for row in comparisons
        if isinstance(row, dict) and row.get("target_profile") == profile_id
    ]
    observed_case_ids = [row.get("case_id") for row in profile_rows]
    return (
        bool(expected_case_ids)
        and len(profile_rows) == len(expected_case_ids)
        and all(isinstance(case_id, str) for case_id in observed_case_ids)
        and len(observed_case_ids) == len(set(observed_case_ids))
        and set(observed_case_ids) == set(expected_case_ids)
        and all(row.get("outcome") == "pass" for row in profile_rows)
    )


def _validate_result(result: dict[str, Any], expected_ids: list[str]) -> None:
    if result.get("schema") != UPSTREAM_RESULT_SCHEMA:
        raise ContractError("upstream benchmark result schema identifier differs")
    rows = result.get("workloads")
    if not isinstance(rows, list) or len(rows) != 74:
        raise ContractError("upstream benchmark result must account for exactly 74 workloads")
    if any(not isinstance(row, dict) for row in rows):
        raise ContractError("upstream benchmark workload rows must be objects")
    ids = [row.get("workload_id") for row in rows]
    if len(ids) != 74 or len(ids) != len(set(ids)):
        raise ContractError("upstream benchmark result workload IDs must be unique")
    if ids != expected_ids:
        raise ContractError(
            "upstream benchmark result IDs/order differ from the validated input catalog"
        )
    router_rows = sum(row.get("category") == "router" for row in rows)
    gzip_rows = sum(row.get("category") == "gzip" for row in rows)
    if router_rows != 6 or gzip_rows != 68:
        raise ContractError(
            "upstream benchmark result category counts differ from 6 Router and 68 GZip"
        )
    if any(row.get("status") not in {"measured", "not_run", "failed"} for row in rows):
        raise ContractError("upstream benchmark result has an unsupported workload status")
    for index, row in enumerate(rows):
        if row["status"] != "measured":
            continue
        comparison = row.get("comparison")
        if not isinstance(comparison, dict) or comparison.get("measurement_order") != list(
            _measurement_order(index)
        ):
            raise ContractError(
                f"{row['workload_id']} does not record its counterbalanced measurement order"
            )
        correctness_gate = row.get("correctness_gate")
        if (
            not isinstance(correctness_gate, dict)
            or correctness_gate.get("status") != "pass"
            or correctness_gate.get("normalized_source_observation_sha256")
            != correctness_gate.get("normalized_target_observation_sha256")
        ):
            raise ContractError(
                f"{row['workload_id']} lacks matching normalized observation digests"
            )
    summary = result.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("declared") != 74
        or sum(summary.get(key, -1) for key in ("measured", "not_run", "failed")) != 74
    ):
        raise ContractError("upstream benchmark result summary does not reconcile to 74 workloads")
    if summary["measured"] != sum(row["status"] == "measured" for row in rows):
        raise ContractError("upstream benchmark measured count differs from workload records")
    if summary["not_run"] != sum(row["status"] == "not_run" for row in rows):
        raise ContractError("upstream benchmark not_run count differs from workload records")
    if summary["failed"] != sum(row["status"] == "failed" for row in rows):
        raise ContractError("upstream benchmark failed count differs from workload records")
    if summary.get("native_not_run_workloads") != 74:
        raise ContractError(
            "Rust-native not_run accounting must include all 74 workload boundaries"
        )
    for row in rows:
        subjects = row.get("subjects")
        expected_subject_ids = [
            "starlette-python",
            "python-package-cpython312",
            "rust-native-local",
        ]
        if (
            not isinstance(subjects, list)
            or [item.get("subject_id") for item in subjects] != expected_subject_ids
        ):
            raise ContractError(
                "each workload must account for source, package, and Rust-native subjects"
            )
        if subjects[2].get("status") != "not_run" or not subjects[2].get("reason"):
            raise ContractError("Rust-native rows require a boundary-specific not_run reason")
        if row["status"] == "measured":
            if (
                row.get("correctness_gate", {}).get("status") != "pass"
                or row.get("comparison", {}).get("status") != "measured"
                or [item.get("status") for item in subjects[:2]] != ["measured", "measured"]
            ):
                raise ContractError(
                    "measured rows require a passing gate and two comparable timings"
                )
        elif (
            row["status"] == "not_run"
            and row.get("correctness_gate", {}).get("status") != "not_run"
        ):
            raise ContractError(
                "not_run workload rows require an explicit not_run correctness gate"
            )
    if result.get("completion_scope") != "pinned source versus installed Python package":
        raise ContractError("upstream completion scope must identify its matched Python subjects")
    if result.get("status") == "completed" and (
        summary["measured"] != 74 or summary["not_run"] or summary["failed"]
    ):
        raise ContractError("completed upstream benchmark result must measure all 74 workloads")


def run_upstream_benchmark(
    root: Path, manifest_path: Path, input_path: Path | None = None
) -> dict[str, Any]:
    """Probe, compare, then time each declared source workload for source and package."""
    root = root.resolve()
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest_path = manifest_path.resolve()
    active_manifest_path = (root / "tests/fixtures/manifest.yaml").resolve()
    if manifest_path != active_manifest_path:
        raise ContractError("upstream benchmarks must use the single active repository manifest")
    manifest_result_path = "tests/fixtures/manifest.yaml"
    manifest_sha256 = sha256_file(manifest_path)
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest)
    _, parity_cases = validate_inputs(root, manifest)
    benchmark_inputs = validate_benchmark_inputs(root, manifest, parity_cases)
    input_path = (input_path or (root / UPSTREAM_INPUT_RELATIVE)).resolve()
    try:
        input_path.relative_to(root / "build/parity/inputs/benchmark")
    except ValueError as exc:
        raise ContractError(
            "upstream benchmark input must stay in the indexed benchmark input lane"
        ) from exc
    indexed_catalogs = {
        path.resolve(): row
        for path, row in benchmark_inputs
        if row.get("schema") == UPSTREAM_INPUT_SCHEMA
    }
    if input_path not in indexed_catalogs:
        raise ContractError(
            "selected upstream benchmark catalog is not indexed in the active manifest"
        )
    document = indexed_catalogs[input_path]
    input_sha256 = sha256_file(input_path)
    if sha256_file(manifest_path) != manifest_sha256:
        raise ContractError("active manifest changed while preparing the upstream benchmark run")
    if sha256_file(input_path) != input_sha256:
        raise ContractError("upstream benchmark catalog changed while preparing the run")
    from .upstream_benchmark_contract import validate_upstream_workloads

    catalog = validate_upstream_workloads(document)
    source_revision = _source_revision(_upstream_root())
    if catalog.get("source_revision") != source_revision:
        raise ContractError("upstream benchmark input revision differs from the pinned source")
    upstream = _upstream_root()
    source_file_digests = _benchmark_source_digests(upstream)

    prepared = load_prepared_environments(root, require_target=True)
    started_at = _timestamp()
    gate_path = root / GATE_RESULT_RELATIVE
    gate = run_parity(root, "parity", gate_path, manifest_path)
    gate_identity = gate.get("identity") if isinstance(gate.get("identity"), dict) else {}
    target_identity = next(
        (
            row
            for row in gate_identity.get("targets", [])
            if isinstance(row, dict) and row.get("target_profile") == "python-package-cpython312"
        ),
        None,
    )
    package_case_ids = [
        case["case_id"]
        for case in parity_cases
        if "python-package-cpython312" in case["target_profiles"]
    ]
    package_gate_ready = _profile_parity_gate_passes(
        gate, "python-package-cpython312", package_case_ids
    )
    native_identity = next(
        (
            row
            for row in gate_identity.get("targets", [])
            if isinstance(row, dict) and row.get("target_profile") == "rust-native-local"
        ),
        None,
    )
    target_tree_sha256 = (
        target_identity.get("target_tree_sha256") if isinstance(target_identity, dict) else None
    )
    parity_ready = package_gate_ready and isinstance(target_tree_sha256, str)
    parity_reason = (
        "fresh source-versus-Python-package parity gate did not pass every selected case; no upstream workload was timed"
        if not package_gate_ready
        else "fresh parity result omitted the installed package identity; no upstream workload was timed"
    )
    source_paths: dict[str, Path] = {}
    source_environments: dict[str, dict[str, Any]] = {}
    for subject_id in PYTHON_SUBJECTS:
        source_paths[subject_id], source_environments[subject_id] = _python_for_subject(
            root, subject_id, prepared
        )

    records: list[dict[str, Any]] = []
    workloads = document["workloads"]
    for workload_index, workload in enumerate(workloads):
        workload_id = workload["workload_id"]
        # Alternate which implementation goes first so a suite-wide warm/cool
        # drift cannot systematically favor one subject. Keep this order in the
        # result artifact; the validated catalog order is stable and independent
        # of workload IDs or target outputs.
        measurement_order = _measurement_order(workload_index)
        subjects: dict[str, dict[str, Any]] = {
            subject_id: {
                "subject_id": subject_id,
                "status": "not_run",
                "identity": None,
                "reason": "not started",
            }
            for subject_id in PYTHON_SUBJECTS
        }
        try:
            if not parity_ready:
                raise LookupError(parity_reason)
            probes: dict[str, dict[str, Any]] = {}
            for subject_id in PYTHON_SUBJECTS:
                environment = source_environments[subject_id]
                probe = _run_worker(
                    root,
                    source_paths[subject_id],
                    subject_id,
                    "probe",
                    workload,
                    upstream,
                    source_revision,
                    target_tree_sha256 if subject_id != "starlette-python" else None,
                    environment["artifact_sha256"] if subject_id != "starlette-python" else None,
                )
                if probe["status"] == "not_run":
                    raise LookupError(
                        probe.get("reason") or f"{subject_id} cannot run this boundary"
                    )
                _identity_check(
                    root,
                    probe,
                    subject_id,
                    environment,
                    upstream,
                    source_revision,
                    target_tree_sha256 if subject_id != "starlette-python" else None,
                )
                if not isinstance(probe.get("observation"), dict):
                    raise ContractError(f"{subject_id} probe omitted its observation")
                relations = _validate_worker_relations(
                    probe, workload, f"{subject_id} probe for {workload_id}"
                )
                probes[subject_id] = probe
                subjects[subject_id] = {
                    "subject_id": subject_id,
                    "status": "probed",
                    "identity": probe["identity"],
                    "input_relations": relations,
                }

            source_observation = probes["starlette-python"]["observation"]
            target_observation = probes["python-package-cpython312"]["observation"]
            unordered_headers = workload["observations"]["events"]["unordered_header_token_order"]
            normalization = (
                f"unordered token order for headers: {', '.join(unordered_headers)}"
                if unordered_headers
                else "none"
            )
            normalized_source = _normalize_allow_tokens(source_observation, unordered_headers)
            normalized_target = _normalize_allow_tokens(target_observation, unordered_headers)
            if normalized_source != normalized_target:
                records.append(
                    {
                        "workload_id": workload_id,
                        "category": workload["category"],
                        "status": "failed",
                        "correctness_gate": {
                            "status": "failed",
                            "source_observation_sha256": _canonical_sha256(source_observation),
                            "target_observation_sha256": _canonical_sha256(target_observation),
                            "normalized_source_observation_sha256": _canonical_sha256(
                                normalized_source
                            ),
                            "normalized_target_observation_sha256": _canonical_sha256(
                                normalized_target
                            ),
                            "normalization": normalization,
                        },
                        "comparison": {
                            "status": "fail",
                            "first_difference": _first_difference(
                                normalized_source,
                                normalized_target,
                            ),
                        },
                        "subjects": [subjects[item] for item in PYTHON_SUBJECTS]
                        + [_native_not_run(workload["category"], native_identity)],
                        "reason": "pinned source and installed package observations differ",
                    }
                )
                continue

            # Measurements run serially to avoid cross-subject CPU contention.
            measured: dict[str, dict[str, Any]] = {}
            for subject_id in measurement_order:
                environment = source_environments[subject_id]
                measurement = _run_worker(
                    root,
                    source_paths[subject_id],
                    subject_id,
                    "measure",
                    workload,
                    upstream,
                    source_revision,
                    target_tree_sha256 if subject_id != "starlette-python" else None,
                    environment["artifact_sha256"] if subject_id != "starlette-python" else None,
                    expected_observation=probes[subject_id]["observation"],
                )
                if measurement["status"] != "completed":
                    raise LookupError(
                        measurement.get("reason") or f"{subject_id} measurement not run"
                    )
                _identity_check(
                    root,
                    measurement,
                    subject_id,
                    environment,
                    upstream,
                    source_revision,
                    target_tree_sha256 if subject_id != "starlette-python" else None,
                )
                if measurement["identity"] != probes[subject_id]["identity"]:
                    raise ContractError(
                        f"{subject_id} identity changed between probe and measurement"
                    )
                normalized_measurement_observation = _normalize_allow_tokens(
                    measurement.get("observation"), unordered_headers
                )
                normalized_probe_observation = _normalize_allow_tokens(
                    probes[subject_id]["observation"], unordered_headers
                )
                if normalized_measurement_observation != normalized_probe_observation:
                    raise ContractError(
                        f"{subject_id} measured calls diverged from its correctness probe"
                    )
                _validate_worker_relations(
                    measurement, workload, f"{subject_id} measurement for {workload_id}"
                )
                _validate_measurement_policy(
                    measurement,
                    workload["measurement"]["runner_policy"],
                    f"{subject_id} measurement for {workload_id}",
                )
                measured[subject_id] = measurement

            source_median = measured["starlette-python"]["measurement"]["statistics"]["median"]
            package_median = measured["python-package-cpython312"]["measurement"]["statistics"][
                "median"
            ]
            if (
                measured["starlette-python"]["measurement"]["unit"]
                != measured["python-package-cpython312"]["measurement"]["unit"]
            ):
                raise ContractError("source and package measurement units differ")
            records.append(
                {
                    "workload_id": workload_id,
                    "category": workload["category"],
                    "status": "measured",
                    "correctness_gate": {
                        "status": "pass",
                        "source_observation_sha256": _canonical_sha256(source_observation),
                        "target_observation_sha256": _canonical_sha256(target_observation),
                        "normalized_source_observation_sha256": _canonical_sha256(
                            normalized_source
                        ),
                        "normalized_target_observation_sha256": _canonical_sha256(
                            normalized_target
                        ),
                        "normalization": normalization,
                    },
                    "measurement_policy": workload["measurement"],
                    "comparison": {
                        "status": "measured",
                        "metric": "median_nanoseconds_per_operation",
                        "source_median": source_median,
                        "package_median": package_median,
                        "source_over_package_speedup": source_median / package_median,
                        "measurement_order": list(measurement_order),
                    },
                    "subjects": [
                        {
                            "subject_id": subject_id,
                            "status": "measured",
                            "identity": measured[subject_id]["identity"],
                            "input_relations": measured[subject_id].get("input_relations", []),
                            "measurement": measured[subject_id]["measurement"],
                        }
                        for subject_id in PYTHON_SUBJECTS
                    ]
                    + [_native_not_run(workload["category"], native_identity)],
                }
            )
        except LookupError as exc:
            records.append(
                {
                    "workload_id": workload_id,
                    "category": workload["category"],
                    "status": "not_run",
                    "correctness_gate": {"status": "not_run"},
                    "measurement_policy": workload["measurement"],
                    "subjects": [subjects[item] for item in PYTHON_SUBJECTS]
                    + [_native_not_run(workload["category"], native_identity)],
                    "reason": str(exc),
                }
            )
        except (ContractError, OSError, ValueError, KeyError, TypeError) as exc:
            records.append(
                {
                    "workload_id": workload_id,
                    "category": workload["category"],
                    "status": "failed",
                    "correctness_gate": {"status": "failed"},
                    "measurement_policy": workload["measurement"],
                    "subjects": [subjects[item] for item in PYTHON_SUBJECTS]
                    + [_native_not_run(workload["category"], native_identity)],
                    "reason": str(exc),
                }
            )

    if _source_revision(upstream) != source_revision:
        raise ContractError("pinned Starlette source revision changed during the benchmark run")
    if _benchmark_source_digests(upstream) != source_file_digests:
        raise ContractError("pinned benchmark source files changed during the benchmark run")
    if sha256_file(manifest_path) != manifest_sha256:
        raise ContractError("active manifest changed during the benchmark run")
    if sha256_file(input_path) != input_sha256:
        raise ContractError("upstream benchmark catalog changed during the benchmark run")
    measured_count = sum(row["status"] == "measured" for row in records)
    not_run_count = sum(row["status"] == "not_run" for row in records)
    failed_count = sum(row["status"] == "failed" for row in records)
    expected_ids = [row["workload_id"] for row in workloads]
    if [row["workload_id"] for row in records] != expected_ids:
        raise ContractError(
            "upstream benchmark result order differs from the validated input catalog"
        )
    result = {
        "schema": UPSTREAM_RESULT_SCHEMA,
        "completion_scope": "pinned source versus installed Python package",
        "identity": {
            "run_id": str(uuid.uuid4()),
            "started_at": started_at,
            "finished_at": _timestamp(),
            "input": {
                "path": input_path.relative_to(root).as_posix(),
                "schema": document["schema"],
                "sha256": input_sha256,
            },
            "manifest": {
                "path": manifest_result_path,
                "schema": manifest["schema"],
                "sha256": manifest_sha256,
            },
            "source_revision": source_revision,
            "source_files": source_file_digests,
            "parity_gate": {
                "path": GATE_RESULT_RELATIVE.as_posix(),
                "run_id": gate_identity.get("run_id"),
                "sha256": sha256_file(gate_path),
                "summary": gate["summary"],
            },
            "prepared_environments": list(prepared.values()),
            "machine": {
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "processor": platform.processor(),
                "logical_cpu_count": os.cpu_count(),
                "python": sys.version,
                "python_executable": str(Path(sys.executable).resolve()),
            },
            "command": {
                "argv": [
                    str(Path(sys.executable).resolve()),
                    "-m",
                    "scripts.parity.cli",
                    "benchmark-upstream",
                ],
                "cwd": str(root),
            },
        },
        "status": "not_proven",
        "summary": {
            "declared": 74,
            "measured": measured_count,
            "not_run": not_run_count,
            "failed": failed_count,
            "native_not_run_workloads": 74,
            "router_measured": sum(
                row["category"] == "router" and row["status"] == "measured" for row in records
            ),
            "gzip_measured": sum(
                row["category"] == "gzip" and row["status"] == "measured" for row in records
            ),
        },
        "workloads": records,
    }
    result["status"] = (
        "completed"
        if measured_count == 74 and not_run_count == 0 and failed_count == 0
        else "not_proven"
    )
    _write_result(root, result, catalog["workload_ids"])
    return result
