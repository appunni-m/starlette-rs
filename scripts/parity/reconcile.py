"""Reconcile focused parity runs with skipped rows in full matrix artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contract import (
    ORACLE_COMMIT,
    RESULT_SCHEMA,
    ContractError,
    load_manifest,
    sha256_file,
    validate_manifest,
    validate_result_artifact,
)
from .runner import load_json_from_text

RECONCILIATION_SCHEMA = "migration-parity/parity-reconciliation@2"
_SHARED_TARGET_FIELDS = (
    "target_id",
    "target_profile",
    "revision",
    "dirty",
    "package_version",
    "dependency_lock_sha256",
    "backend",
    "features",
)
_SHARED_PACKAGE_SOURCE_FIELDS = (
    "revision",
    "dirty",
    "package_version",
    "dependency_lock_sha256",
    "features",
)
_SHARED_ORACLE_FIELDS = (
    "oracle_id",
    "name",
    "version",
    "revision",
    "dependency_lock_sha256",
    "runtime_lock_sha256",
)


def _read_artifact(
    path: Path,
    *,
    root: Path,
    manifest_path: Path,
    manifest_identity: dict[str, Any],
) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"parity artifact must be inside the repository: {resolved}") from exc
    try:
        raw = resolved.read_bytes()
        artifact = load_json_from_text(raw.decode("utf-8"), str(resolved))
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read parity artifact {resolved}: {exc}") from exc
    artifact = validate_result_artifact(artifact, root=root, manifest_path=manifest_path)
    if artifact["schema"] != RESULT_SCHEMA:
        raise ContractError(f"reconciliation accepts parity result artifacts only: {resolved}")

    identity = artifact["identity"]
    if identity["manifest"] != manifest_identity:
        raise ContractError(f"parity artifact is not bound to the active manifest: {resolved}")
    if identity["command"]["command_id"] != "parity":
        raise ContractError(f"artifact is not a live parity run: {resolved}")
    oracles = identity["oracles"]
    if len(oracles) != 1 or oracles[0]["revision"] != ORACLE_COMMIT:
        raise ContractError(f"artifact does not identify the pinned Starlette oracle: {resolved}")

    return {
        "path": resolved,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "artifact": artifact,
    }


def _target_map(artifact: dict[str, Any], context: str) -> dict[str, dict[str, Any]]:
    targets = artifact["identity"]["targets"]
    result = {target["target_profile"]: target for target in targets}
    if len(result) != len(targets):
        raise ContractError(f"{context} repeats a target profile identity")
    return result


def _artifact_record(record: dict[str, Any], root: Path) -> dict[str, Any]:
    artifact = record["artifact"]
    return {
        "path": record["path"].relative_to(root).as_posix(),
        "sha256": record["sha256"],
        "status": artifact["status"],
        "selection": artifact["identity"]["selection"],
        "oracles": artifact["identity"]["oracles"],
        "environments": artifact["identity"]["environments"],
        "targets": artifact["identity"]["targets"],
    }


def _matches_python_profile(runtime: str, python_version: str) -> bool:
    prefix = f"CPython {python_version}"
    return runtime == prefix or runtime.startswith(f"{prefix}.")


def _validate_reconciliation_report(report: dict[str, Any]) -> None:
    expected_top_level = {
        "schema",
        "status",
        "manifest",
        "baseline_artifacts",
        "supplement_artifacts",
        "replacements",
        "unreplaced_skipped_rows",
        "non_reconcilable_not_run_rows",
        "non_reconcilable_supplement_rows",
        "parity_matrix",
        "full_replacement",
    }
    if set(report) != expected_top_level:
        raise ContractError("generated reconciliation report has an invalid field set")
    if report["schema"] != RECONCILIATION_SCHEMA or report["status"] != "completed":
        raise ContractError("generated reconciliation report has an invalid schema or status")
    if set(report["manifest"]) != {"path", "schema", "sha256"}:
        raise ContractError("generated reconciliation manifest identity has an invalid field set")
    manifest_identity = report["manifest"]
    if any(not isinstance(manifest_identity[field], str) for field in ("path", "schema")):
        raise ContractError("generated reconciliation manifest identity is malformed")
    manifest_digest = manifest_identity["sha256"]
    if len(manifest_digest) != 64 or any(
        character not in "0123456789abcdef" for character in manifest_digest
    ):
        raise ContractError("generated reconciliation manifest digest is malformed")

    matrix = report["parity_matrix"]
    if set(matrix) != {"status", "reason", "summary", "supplement_case_rows_added_to_denominator"}:
        raise ContractError("generated reconciliation matrix has an invalid field set")
    if matrix["status"] not in {"passed", "not_proven"}:
        raise ContractError("generated reconciliation matrix has an invalid status")
    if matrix["supplement_case_rows_added_to_denominator"] is not False:
        raise ContractError("focused rows must not change the parity denominator")

    summary = matrix["summary"]
    expected_summary = {
        "selected",
        "executed",
        "passed",
        "failed",
        "not_run",
        "fault_contracts",
        "infrastructure_errors",
        "profiles_expected",
        "profiles_supplied",
    }
    if set(summary) != expected_summary:
        raise ContractError("generated reconciliation summary has an invalid field set")
    if (
        any(
            type(summary[field]) is not int or summary[field] < 0
            for field in ("profiles_expected", "profiles_supplied")
        )
        or summary["profiles_expected"] != summary["profiles_supplied"]
    ):
        raise ContractError("generated reconciliation profile counts are inconsistent")
    fault_summary = summary["fault_contracts"]
    if set(fault_summary) != {"selected", "executed", "passed", "failed", "not_run"}:
        raise ContractError("generated fault-contract summary has an invalid field set")
    for name, counts in (("parity", summary), ("fault-contract", fault_summary)):
        numeric_fields = (
            ("selected", "executed", "passed", "failed", "not_run")
            if name == "fault-contract"
            else ("selected", "executed", "passed", "failed", "not_run", "infrastructure_errors")
        )
        if any(type(counts[field]) is not int or counts[field] < 0 for field in numeric_fields):
            raise ContractError(f"generated {name} summary has invalid counts")
        if counts["selected"] != counts["executed"] + counts["not_run"]:
            raise ContractError(f"generated {name} summary has inconsistent selected counts")
        if counts["executed"] != counts["passed"] + counts["failed"]:
            raise ContractError(f"generated {name} summary has inconsistent executed counts")

    if matrix["status"] == "passed" and (
        summary["failed"]
        or summary["not_run"]
        or summary["infrastructure_errors"]
        or fault_summary["failed"]
        or fault_summary["not_run"]
        or summary["passed"] != summary["selected"]
        or fault_summary["passed"] != fault_summary["selected"]
    ):
        raise ContractError("reconciliation claims passing parity with incomplete evidence")

    if set(report["full_replacement"]) != {"status", "reason"}:
        raise ContractError("generated full-replacement status has an invalid field set")
    if report["full_replacement"]["status"] != "not_proven" or not isinstance(
        report["full_replacement"]["reason"], str
    ):
        raise ContractError("parity reconciliation cannot prove the full Starlette replacement")

    row_identity_fields = {"profile", "case_id", "target_profile"}
    unreplaced_skipped_keys: set[tuple[str, str, str]] = set()
    non_reconcilable_supplement_keys: set[tuple[str, str, str]] = set()
    for field in (
        "unreplaced_skipped_rows",
        "non_reconcilable_not_run_rows",
        "non_reconcilable_supplement_rows",
    ):
        expected_fields = row_identity_fields
        if field != "unreplaced_skipped_rows":
            expected_fields = row_identity_fields | {"reason"}
        seen_rows: set[tuple[str, str, str]] = set()
        for row in report[field]:
            if set(row) != expected_fields:
                raise ContractError(f"generated {field} row has an invalid field set")
            key = (row["profile"], row["case_id"], row["target_profile"])
            if key in seen_rows:
                raise ContractError(f"generated {field} repeats a row")
            seen_rows.add(key)
            if any(not isinstance(value, str) or not value for value in key):
                raise ContractError(f"generated {field} has an empty identity field")
            if field == "unreplaced_skipped_rows":
                unreplaced_skipped_keys.add(key)
            elif field == "non_reconcilable_supplement_rows":
                non_reconcilable_supplement_keys.add(key)
            if field != "unreplaced_skipped_rows" and (
                not isinstance(row["reason"], str) or not row["reason"]
            ):
                raise ContractError(f"generated {field} row has an empty reason")

    replacement_keys: set[tuple[str, str, str]] = set()
    for replacement in report["replacements"]:
        if set(replacement) != {"profile", "case_id", "target_profile", "baseline", "supplement"}:
            raise ContractError("generated replacement row has an invalid field set")
        key = (replacement["profile"], replacement["case_id"], replacement["target_profile"])
        if key in replacement_keys:
            raise ContractError("generated reconciliation repeats a replacement row")
        replacement_keys.add(key)
        if any(not isinstance(value, str) or not value for value in key):
            raise ContractError("generated replacement row has an empty identity field")
        for source in ("baseline", "supplement"):
            evidence = replacement[source]
            if set(evidence) != {"path", "sha256"}:
                raise ContractError("generated replacement evidence has an invalid field set")
            if len(evidence["sha256"]) != 64 or any(
                character not in "0123456789abcdef" for character in evidence["sha256"]
            ):
                raise ContractError("generated replacement evidence has an invalid digest")
    if replacement_keys & non_reconcilable_supplement_keys:
        raise ContractError("generated reconciliation both accepts and rejects one supplement row")
    if not non_reconcilable_supplement_keys <= unreplaced_skipped_keys:
        raise ContractError("non-reconcilable supplement rows must remain unreplaced baseline skips")


def reconcile_parity_results(
    root: Path,
    manifest_path: Path,
    baseline_paths: list[Path],
    supplement_paths: list[Path],
) -> dict[str, Any]:
    """Return a versioned sidecar replacing only source-skipped matrix rows.

    Full matrix artifacts remain unchanged. A focused artifact can replace a
    row only when the same profile's full run recorded both source and target
    as skipped, and the focused live comparison passed under matching code,
    package, dependency, and feature identities.
    """
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
    if not python_profiles or len(native_profiles) != 1:
        raise ContractError("reconciliation requires Python-package and one Rust-native profile")

    expected_python_ids = [profile["id"] for profile in python_profiles]
    expected_python_set = set(expected_python_ids)
    native_profile_id = native_profiles[0]["id"]
    manifest_identity = {
        "path": manifest_relative,
        "schema": manifest["schema"],
        "sha256": sha256_file(manifest_file),
    }

    baselines_by_profile: dict[str, dict[str, Any]] = {}
    baseline_target_identity: dict[str, tuple[Any, ...]] = {}
    baseline_package_source_identity: tuple[Any, ...] | None = None
    for path in baseline_paths:
        record = _read_artifact(
            path,
            root=root,
            manifest_path=manifest_file,
            manifest_identity=manifest_identity,
        )
        artifact = record["artifact"]
        identity = artifact["identity"]
        selection = identity["selection"]
        if selection["kind"] != "all" or selection["case_ids"]:
            raise ContractError(f"baseline artifact is not a full all-cases run: {record['path']}")
        selected_profiles = selection["target_profiles"]
        python_ids = [
            profile_id for profile_id in selected_profiles if profile_id in expected_python_set
        ]
        if len(python_ids) != 1 or native_profile_id not in selected_profiles:
            raise ContractError(
                f"baseline artifact must select one CPython and its Rust-native profile: {record['path']}"
            )
        profile_id = python_ids[0]
        python_version = next(
            item["python_version"] for item in python_profiles if item["id"] == profile_id
        )
        if not _matches_python_profile(identity["oracles"][0]["runtime"], python_version):
            raise ContractError(
                f"full baseline oracle runtime does not match {profile_id}: {record['path']}"
            )
        expected_selection = [
            profile["id"]
            for profile in manifest["target_profiles"]
            if profile["id"] in {native_profile_id, profile_id}
        ]
        if selected_profiles != expected_selection:
            raise ContractError(
                f"baseline target selection is not in manifest order: {record['path']}"
            )
        if profile_id in baselines_by_profile:
            raise ContractError(f"duplicate full baseline for CPython profile {profile_id}")
        targets = _target_map(artifact, f"baseline {record['path']}")
        if set(targets) != {native_profile_id, profile_id}:
            raise ContractError(
                f"baseline target identities do not match selected profiles: {record['path']}"
            )
        for target_profile in (native_profile_id, profile_id):
            target = targets[target_profile]
            if target["dirty"]:
                raise ContractError(f"full baseline target is dirty: {record['path']}")
            if target_profile == profile_id and not _matches_python_profile(
                target["runtime"], python_version
            ):
                raise ContractError(
                    f"full baseline target runtime does not match {profile_id}: {record['path']}"
                )
            identity_tuple = tuple(target.get(field) for field in _SHARED_TARGET_FIELDS)
            previous = baseline_target_identity.get(target_profile)
            if previous is not None and previous != identity_tuple:
                raise ContractError(
                    f"full baselines contain mixed target identities for {target_profile}"
                )
            baseline_target_identity[target_profile] = identity_tuple
            if target_profile == profile_id:
                package_identity = tuple(
                    target.get(field) for field in _SHARED_PACKAGE_SOURCE_FIELDS
                )
                if (
                    baseline_package_source_identity is not None
                    and package_identity != baseline_package_source_identity
                ):
                    raise ContractError("full baselines contain mixed package source identities")
                baseline_package_source_identity = package_identity
        if artifact["status"] != "completed":
            raise ContractError(f"full baseline did not complete: {record['path']}")
        baselines_by_profile[profile_id] = record

    if set(baselines_by_profile) != expected_python_set:
        missing = [
            profile_id
            for profile_id in expected_python_ids
            if profile_id not in baselines_by_profile
        ]
        raise ContractError(f"full baselines are missing CPython profiles: {', '.join(missing)}")

    totals = {
        key: sum(record["artifact"]["summary"][key] for record in baselines_by_profile.values())
        for key in ("selected", "executed", "passed", "failed", "not_run")
    }
    totals["fault_contracts"] = {
        key: sum(
            record["artifact"]["summary"]["fault_contracts"][key]
            for record in baselines_by_profile.values()
        )
        for key in ("selected", "executed", "passed", "failed", "not_run")
    }
    totals["infrastructure_errors"] = sum(
        record["artifact"]["summary"]["infrastructure_errors"]
        for record in baselines_by_profile.values()
    )
    totals["profiles_expected"] = len(expected_python_ids)
    totals["profiles_supplied"] = len(baselines_by_profile)

    skipped_rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    non_reconcilable_rows: list[dict[str, str]] = []
    for profile_id, record in baselines_by_profile.items():
        for row in record["artifact"]["comparisons"]:
            if row["outcome"] != "not_run":
                continue
            key = (profile_id, row["case_id"], row["target_profile"])
            if row["source"]["status"] == "skipped" and row["target"]["status"] == "skipped":
                if key in skipped_rows:
                    raise ContractError(f"full baselines repeat a skipped comparison row: {key}")
                skipped_rows[key] = {"row": row, "baseline": record}
            else:
                non_reconcilable_rows.append(
                    {
                        "profile": profile_id,
                        "case_id": row["case_id"],
                        "target_profile": row["target_profile"],
                        "reason": "the full row was not_run without both source and target skipped",
                    }
                )

    replacements: dict[tuple[str, str, str], dict[str, Any]] = {}
    non_reconcilable_supplement_rows: dict[tuple[str, str, str], dict[str, str]] = {}
    supplements_by_profile: dict[str, list[dict[str, Any]]] = {
        key: [] for key in expected_python_ids
    }
    for path in supplement_paths:
        record = _read_artifact(
            path,
            root=root,
            manifest_path=manifest_file,
            manifest_identity=manifest_identity,
        )
        artifact = record["artifact"]
        if artifact["status"] != "completed":
            raise ContractError(f"focused parity artifact did not complete: {record['path']}")
        summary = artifact["summary"]
        if summary["failed"] or summary["not_run"] or summary["infrastructure_errors"]:
            raise ContractError(
                f"focused parity artifact has incomplete or failed rows: {record['path']}"
            )
        if summary["fault_contracts"]["selected"]:
            raise ContractError(
                f"focused artifact includes fault contracts outside row reconciliation: {record['path']}"
            )

        identity = artifact["identity"]
        selection = identity["selection"]
        if selection["kind"] != "case_ids" or not selection["case_ids"]:
            raise ContractError(f"supplement must be a focused case-id run: {record['path']}")
        selected_profiles = selection["target_profiles"]
        python_ids = [
            profile_id for profile_id in selected_profiles if profile_id in expected_python_set
        ]
        if len(python_ids) != 1 or native_profile_id not in selected_profiles:
            raise ContractError(
                f"supplement must select one CPython and its Rust-native profile: {record['path']}"
            )
        profile_id = python_ids[0]
        python_version = next(
            item["python_version"] for item in python_profiles if item["id"] == profile_id
        )
        expected_selection = [
            profile["id"]
            for profile in manifest["target_profiles"]
            if profile["id"] in {native_profile_id, profile_id}
        ]
        if selected_profiles != expected_selection:
            raise ContractError(
                f"supplement target selection is not in manifest order: {record['path']}"
            )
        if profile_id not in baselines_by_profile:
            raise ContractError(f"supplement has no matching full baseline: {profile_id}")

        baseline_artifact = baselines_by_profile[profile_id]["artifact"]
        baseline_oracle = baseline_artifact["identity"]["oracles"][0]
        supplement_oracle = identity["oracles"][0]
        if any(
            supplement_oracle.get(field) != baseline_oracle.get(field)
            for field in _SHARED_ORACLE_FIELDS
        ):
            raise ContractError(
                f"supplement mixes pinned source-oracle identities: {record['path']}"
            )
        if not _matches_python_profile(supplement_oracle["runtime"], python_version):
            raise ContractError(
                f"supplement oracle is outside the selected Python profile: {record['path']}"
            )

        supplement_targets = _target_map(artifact, f"supplement {record['path']}")
        if set(supplement_targets) != set(selected_profiles):
            raise ContractError(
                f"supplement target identities do not match selected profiles: {record['path']}"
            )
        baseline_targets = _target_map(baseline_artifact, f"baseline for {profile_id}")
        matching_target_profiles: set[str] = set()
        target_identity_reasons: dict[str, str] = {}
        for target_profile in (native_profile_id, profile_id):
            if target_profile not in supplement_targets or target_profile not in baseline_targets:
                raise ContractError(
                    f"supplement target identity is missing {target_profile}: {record['path']}"
                )
            baseline_target = baseline_targets[target_profile]
            supplement_target = supplement_targets[target_profile]
            mismatch_reasons: list[str] = []
            if supplement_target["dirty"]:
                mismatch_reasons.append("supplement target is dirty")
            if target_profile == profile_id and not _matches_python_profile(
                supplement_target["runtime"], python_version
            ):
                mismatch_reasons.append(
                    f"supplement target runtime does not match {profile_id}"
                )
            differing_fields = [
                field
                for field in _SHARED_TARGET_FIELDS
                if supplement_target.get(field) != baseline_target.get(field)
            ]
            if differing_fields:
                mismatch_reasons.append(
                    "supplement target code/package identity differs in "
                    + ", ".join(differing_fields)
                )
            if mismatch_reasons:
                target_identity_reasons[target_profile] = "; ".join(mismatch_reasons)
            else:
                matching_target_profiles.add(target_profile)
        supplements_by_profile[profile_id].append(record)

        for row in artifact["comparisons"]:
            if (
                row["outcome"] != "pass"
                or row["source"]["status"] != "completed"
                or row["target"]["status"] != "completed"
            ):
                raise ContractError(f"supplement comparison did not pass: {record['path']}")
            key = (profile_id, row["case_id"], row["target_profile"])
            baseline_row = skipped_rows.get(key)
            if baseline_row is None:
                raise ContractError(
                    f"supplement does not correspond to a full-run skipped row: {key}"
                )
            if row["target_profile"] not in matching_target_profiles:
                non_reconcilable_supplement_rows[key] = {
                    "profile": profile_id,
                    "case_id": row["case_id"],
                    "target_profile": row["target_profile"],
                    "reason": target_identity_reasons[row["target_profile"]],
                }
                continue
            if row["requirements"] != baseline_row["row"]["requirements"]:
                raise ContractError(
                    f"supplement requirement mapping differs from baseline row: {key}"
                )
            if (
                row["upstream_test_applicability"]
                != baseline_row["row"]["upstream_test_applicability"]
            ):
                raise ContractError(
                    f"supplement source-test applicability differs from baseline row: {key}"
                )
            if key in replacements:
                raise ContractError(f"duplicate focused evidence for skipped comparison row: {key}")
            replacements[key] = {
                "profile": profile_id,
                "case_id": row["case_id"],
                "target_profile": row["target_profile"],
                "baseline": {
                    "path": baseline_row["baseline"]["path"].as_posix(),
                    "sha256": baseline_row["baseline"]["sha256"],
                },
                "supplement": {"path": record["path"].as_posix(), "sha256": record["sha256"]},
            }

    effective = dict(totals)
    replacement_count = len(replacements)
    effective["executed"] += replacement_count
    effective["passed"] += replacement_count
    effective["not_run"] -= replacement_count

    reasons: list[str] = []
    if effective["failed"] or effective["fault_contracts"]["failed"]:
        reasons.append("one or more baseline parity or fault-contract comparisons failed")
    if effective["not_run"] or effective["fault_contracts"]["not_run"]:
        reasons.append("one or more parity or fault-contract comparisons remain not_run")
    if effective["infrastructure_errors"]:
        reasons.append("one or more baseline runs reported infrastructure errors")
    if effective["passed"] != effective["selected"]:
        reasons.append("not every parity comparison passed after row reconciliation")
    if effective["fault_contracts"]["passed"] != effective["fault_contracts"]["selected"]:
        reasons.append("not every selected fault contract passed")

    unreplaced = [
        {
            "profile": profile_id,
            "case_id": case_id,
            "target_profile": target_profile,
        }
        for profile_id, case_id, target_profile in sorted(skipped_rows)
        if (profile_id, case_id, target_profile) not in replacements
    ]
    unreconciled_supplement_rows = [
        non_reconcilable_supplement_rows[key]
        for key in sorted(non_reconcilable_supplement_rows)
        if key not in replacements
    ]
    if unreplaced or non_reconcilable_rows:
        if "one or more parity or fault-contract comparisons remain not_run" not in reasons:
            reasons.append("one or more parity or fault-contract comparisons remain not_run")
    if unreconciled_supplement_rows:
        reasons.append("one or more focused target identities did not match their full baseline rows")

    report = {
        "schema": RECONCILIATION_SCHEMA,
        "status": "completed",
        "manifest": manifest_identity,
        "baseline_artifacts": [
            _artifact_record(baselines_by_profile[profile_id], root)
            for profile_id in expected_python_ids
        ],
        "supplement_artifacts": [
            _artifact_record(record, root)
            for profile_id in expected_python_ids
            for record in supplements_by_profile[profile_id]
        ],
        "replacements": [replacements[key] for key in sorted(replacements)],
        "unreplaced_skipped_rows": unreplaced,
        "non_reconcilable_not_run_rows": non_reconcilable_rows,
        "non_reconcilable_supplement_rows": unreconciled_supplement_rows,
        "parity_matrix": {
            "status": "passed" if not reasons else "not_proven",
            "reason": "all baseline rows passed or were replaced by compatible focused evidence"
            if not reasons
            else "; ".join(dict.fromkeys(reasons)),
            "summary": effective,
            "supplement_case_rows_added_to_denominator": False,
        },
        "full_replacement": {
            "status": "not_proven",
            "reason": "this reconciliation covers only the active parity matrix, not every documented Starlette behavior or runtime platform",
        },
    }
    _validate_reconciliation_report(report)
    return report
