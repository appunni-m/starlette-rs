"""Fail-closed static completeness checks for the authority-wide scope."""

from __future__ import annotations

import csv
import fnmatch
import io
import os
import pathlib
import subprocess
from typing import Any

from scripts.inventory_upstream_api import make_rows
from scripts.merge_compatibility_atlas import (
    API_REVIEW_FIELDS,
    CATALOG_FIELDS,
    FIXTURE_FIELDS,
    AtlasError,
    check_api_reviews,
    check_fixture_backlog,
    read_csv,
    render_csv,
)

from .api_sources import load_api_metadata, public_module_names, validate_api_sources
from .contract import ContractError, _all_manifest_surfaces, validate_inputs

API_CATALOG_RELATIVE = pathlib.Path("docs/api-surface.csv")
API_REVIEW_RELATIVE = pathlib.Path("docs/atlas/api-review.csv")
COVERAGE_MATRIX_RELATIVE = pathlib.Path("docs/atlas/coverage-matrix.csv")
FIXTURE_BACKLOG_RELATIVE = pathlib.Path("docs/atlas/fixture-backlog.csv")
REVIEW_ROOT_RELATIVE = pathlib.Path("docs/atlas/reviews")
SOURCE_INPUT_ROOT = pathlib.Path("tests/fixtures/sources/parity")
GENERATED_INPUT_ROOT = pathlib.Path("build/parity/inputs/parity")


def _catalog_text(rows: list[dict[str, str]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CATALOG_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _checked_in_text(root: pathlib.Path, relative: pathlib.Path) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractError(
            f"full scope completeness requires readable {relative}: {error}"
        ) from error


def _require_pinned_source(
    root: pathlib.Path, metadata: dict[str, Any], override: pathlib.Path | None
) -> pathlib.Path:
    configured = os.environ.get("STARLETTE_ORACLE_ROOT")
    upstream = (
        override or (pathlib.Path(configured) if configured else root.parent / "starlette")
    ).resolve()
    package = upstream / metadata["authority"]["package_path"]
    if not (package / "__init__.py").is_file():
        raise ContractError(
            f"full scope completeness cannot find pinned Starlette under {upstream}"
        )
    try:
        revision = subprocess.run(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        version_source = (package / "__init__.py").read_text(encoding="utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise ContractError(
            f"full scope completeness cannot inspect pinned Starlette: {error}"
        ) from error
    authority = metadata["authority"]
    if revision != authority["revision"]:
        raise ContractError(
            f"full scope completeness requires Starlette revision {authority['revision']}, found {revision}"
        )
    if f'__version__ = "{authority["version"]}"' not in version_source:
        raise ContractError(
            f"full scope completeness requires Starlette {authority['version']} source"
        )

    inventory = metadata["api_inventory"]
    package_path = authority["package_path"]
    package_root = upstream / package_path
    discovered = {
        (pathlib.Path(package_path) / path.relative_to(package_root)).as_posix()
        for path in package_root.rglob("*.py")
        if not any(
            part != "__init__" and part.startswith("_")
            for part in path.relative_to(package_root).with_suffix("").parts
        )
    }
    declared = set(inventory["public_source_files"])
    if discovered != declared:
        raise ContractError(
            "full scope completeness found metadata/source module drift: "
            f"metadata-only={sorted(declared - discovered)}, source-only={sorted(discovered - declared)}"
        )
    for field in ("documentation_root", "test_source_root"):
        source_root = (upstream / inventory[field]).resolve()
        try:
            source_root.relative_to(upstream.resolve())
        except ValueError as error:
            raise ContractError(
                f"metadata.yaml {field} escapes the pinned Starlette checkout"
            ) from error
        if not source_root.is_dir():
            raise ContractError(
                f"full scope completeness cannot find pinned {field}: {source_root}"
            )
    return upstream


def _source_review_rows(
    root: pathlib.Path, upstream: pathlib.Path, manifest: dict[str, Any], metadata: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    inventory = metadata["api_inventory"]
    package_path = metadata["authority"]["package_path"]
    source_root = upstream
    docs_root = upstream / inventory["documentation_root"]
    catalog_rows = make_rows(
        source_root,
        docs_root,
        inventory["public_source_files"],
        package_path,
        package_path.replace("/", "."),
    )
    if _checked_in_text(root, API_CATALOG_RELATIVE) != _catalog_text(catalog_rows):
        raise ContractError(
            f"full scope completeness found a stale API candidate catalog: {API_CATALOG_RELATIVE}"
        )

    review_root = root / REVIEW_ROOT_RELATIVE
    api_partitions = sorted(review_root.glob("*-api.csv"))
    fixture_partitions = sorted(review_root.glob("*-fixtures.csv"))
    if not api_partitions or not fixture_partitions:
        raise ContractError(
            "full scope completeness requires API and source fixture review partitions"
        )
    try:
        api_rows = check_api_reviews(root / API_CATALOG_RELATIVE, api_partitions, upstream)
        fixture_rows = check_fixture_backlog(
            fixture_partitions,
            root,
            upstream,
            inventory["test_source_root"],
            inventory["documentation_root"],
            manifest,
            public_module_names(metadata),
        )
    except AtlasError as error:
        raise ContractError(
            f"full scope completeness found invalid source review mappings: {error}"
        ) from error

    for relative, fields, rows in (
        (API_REVIEW_RELATIVE, API_REVIEW_FIELDS, api_rows),
        (COVERAGE_MATRIX_RELATIVE, FIXTURE_FIELDS, fixture_rows),
        (
            FIXTURE_BACKLOG_RELATIVE,
            FIXTURE_FIELDS,
            [row for row in fixture_rows if row["fixture_status"] == "backlog"],
        ),
    ):
        try:
            actual_rows = read_csv(root / relative, fields)
        except (OSError, UnicodeError, AtlasError) as error:
            raise ContractError(
                f"full scope completeness cannot read {relative}: {error}"
            ) from error
        if _checked_in_text(root, relative) != render_csv(fields, rows):
            raise ContractError(
                f"full scope completeness found stale generated inventory: {relative}"
            )
        if actual_rows != rows:
            raise ContractError(
                f"full scope completeness found inconsistent inventory rows: {relative}"
            )
    return api_rows, fixture_rows


def _indexed_cases_by_source(
    root: pathlib.Path,
    manifest: dict[str, Any],
    indexed_inputs: list[tuple[pathlib.Path, dict[str, Any]]],
) -> dict[pathlib.Path, list[dict[str, Any]]]:
    documents = {path.resolve(): document for path, document in indexed_inputs}
    cases_by_source: dict[pathlib.Path, list[dict[str, Any]]] = {}
    for relative in manifest["input_index"]["parity"]:
        generated = pathlib.Path(relative)
        source = (
            root
            / SOURCE_INPUT_ROOT
            / generated.relative_to(GENERATED_INPUT_ROOT).with_suffix(".yaml")
        )
        if not source.is_file():
            source = source.with_suffix(".yml")
        document = documents.get((root / generated).resolve())
        if document is not None and source.is_file():
            cases_by_source[source.resolve()] = document.get("cases", [])
    return cases_by_source


def _api_selector(qualified_name: str, modules: frozenset[str]) -> tuple[str, str] | None:
    candidates = [
        module
        for module in modules
        if qualified_name == module or qualified_name.startswith(module + ".")
    ]
    if not candidates:
        return None
    module = max(candidates, key=len)
    return module, qualified_name[len(module) :].removeprefix(".")


def _inspection_coverage(
    root: pathlib.Path,
    metadata: dict[str, Any],
    api_rows: list[dict[str, str]],
    cases: list[dict[str, Any]],
) -> list[str]:
    public_modules = public_module_names(metadata)
    inspected_modules: set[str] = set()
    observed: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        if (case.get("surface"), case.get("operation")) != ("starlette", "public-api-inspection"):
            continue
        for module in case["inspection"]["modules"]:
            module_name = module["name"]
            inspected_modules.add(module_name)
            for symbol in module["symbols"]:
                observed.setdefault((module_name, symbol["name"]), set()).update(symbol["observe"])

    missing_modules = public_modules - inspected_modules
    missing_selectors: set[tuple[str, str]] = set()
    for row in api_rows:
        if row["api_disposition"] != "supported":
            continue
        selector = _api_selector(row["qualified_name"], public_modules)
        if selector is None:
            missing_selectors.add(("<unmapped>", row["qualified_name"]))
            continue
        module_name, symbol_name = selector
        if symbol_name and "presence" not in observed.get((module_name, symbol_name), set()):
            missing_selectors.add(selector)

    errors: list[str] = []
    if missing_modules:
        errors.append(
            f"public modules missing from public-api-inspection ({len(missing_modules)}): "
            f"{sorted(missing_modules)[:12]}"
        )
    if missing_selectors:
        errors.append(
            f"supported API names missing presence inspection ({len(missing_selectors)}): "
            f"{sorted(missing_selectors)[:12]}"
        )
    return errors


def _mapping_errors(
    root: pathlib.Path,
    manifest: dict[str, Any],
    indexed_inputs: list[tuple[pathlib.Path, dict[str, Any]]],
    api_rows: list[dict[str, str]],
    fixture_rows: list[dict[str, str]],
) -> list[str]:
    cases_by_source = _indexed_cases_by_source(root, manifest, indexed_inputs)
    public_modules = public_module_names(load_api_metadata(root))
    known_api_names = {row["qualified_name"] for row in api_rows}
    requirement_by_id = {
        requirement["id"]: (surface["id"], operation["id"], requirement)
        for surface in _all_manifest_surfaces(manifest)
        for operation in surface["operations"]
        for requirement in operation["requirements"]
    }
    input_sources = set(cases_by_source)
    errors: list[str] = []
    unmapped_source_rows: list[str] = []
    unmapped_references: list[str] = []
    uncovered_row_requirements: list[str] = []

    for row in fixture_rows:
        if row["fixture_status"] == "backlog":
            unmapped_source_rows.append(row["backlog_id"])
            continue
        if row["fixture_status"] == "not_applicable":
            if not row["exclusion_reason"].strip() or not row["evidence_refs"].strip():
                unmapped_source_rows.append(row["backlog_id"])
            continue
        if row["fixture_status"] != "existing":
            unmapped_source_rows.append(row["backlog_id"])
            continue

        source_paths = [
            (root / entry.strip()).resolve()
            for entry in row["fixture_path"].split(";")
            if entry.strip()
        ]
        if not source_paths or any(path not in input_sources for path in source_paths):
            unmapped_source_rows.append(row["backlog_id"])
            continue

        row_cases = [case for path in source_paths for case in cases_by_source[path]]
        if not row_cases or not any(case.get("covers") for case in row_cases):
            unmapped_source_rows.append(row["backlog_id"])
            continue
        covered = {
            requirement_id for case in row_cases for requirement_id in case.get("covers", [])
        }
        references = [value.strip() for value in row["requirement_ids"].split(";") if value.strip()]
        for reference in references:
            requirement = requirement_by_id.get(reference)
            if (
                requirement is not None
                and "parity" in requirement[2]["lanes"]
                and reference not in covered
            ):
                uncovered_row_requirements.append(f"{row['backlog_id']} -> {reference}")
                continue
            if reference.startswith("starlette.") and reference not in requirement_by_id:
                is_module = reference in public_modules
                has_pattern_match = "*" in reference and any(
                    fnmatch.fnmatchcase(name, reference) for name in known_api_names
                )
                if reference not in known_api_names and not is_module and not has_pattern_match:
                    # Non-applicable source rows may explicitly inventory private or historical names.
                    if row["api_disposition"] not in {"n/a", "private/internal"}:
                        unmapped_references.append(f"{row['backlog_id']} -> {reference}")

    if unmapped_source_rows:
        errors.append(
            f"source rows lack an indexed input or an explicit not_applicable explanation "
            f"({len(unmapped_source_rows)}): {sorted(set(unmapped_source_rows))[:12]}"
        )
    if uncovered_row_requirements:
        errors.append(
            f"atlas requirement mappings are not covered by their indexed fixtures "
            f"({len(uncovered_row_requirements)}): {sorted(set(uncovered_row_requirements))[:12]}"
        )
    if unmapped_references:
        errors.append(
            f"supported Starlette source references have no manifest operation or API candidate mapping "
            f"({len(unmapped_references)}): {sorted(set(unmapped_references))[:12]}"
        )
    return errors


def _requirement_errors(manifest: dict[str, Any], cases: list[dict[str, Any]]) -> list[str]:
    required_profiles: dict[str, set[str]] = {}
    for surface in _all_manifest_surfaces(manifest):
        for operation in surface["operations"]:
            for requirement in operation["requirements"]:
                if "parity" in requirement["lanes"]:
                    required_profiles[requirement["id"]] = set(requirement["target_profiles"])
    covered_profiles = {requirement_id: set() for requirement_id in required_profiles}
    for case in cases:
        for requirement_id in case["covers"]:
            if requirement_id in covered_profiles:
                covered_profiles[requirement_id].update(case["target_profiles"])
    missing = {
        requirement_id: sorted(profiles - covered_profiles[requirement_id])
        for requirement_id, profiles in required_profiles.items()
        if profiles - covered_profiles[requirement_id]
    }
    if not missing:
        return []
    pairs = [
        f"{requirement_id} ({', '.join(profiles)})"
        for requirement_id, profiles in sorted(missing.items())
    ]
    return [f"parity requirement/profile mappings are incomplete ({len(missing)}): {pairs[:12]}"]


def validate_full_scope_completeness(
    root: pathlib.Path,
    manifest: dict[str, Any],
    indexed_inputs: list[tuple[pathlib.Path, dict[str, Any]]] | None = None,
    cases: list[dict[str, Any]] | None = None,
    upstream: pathlib.Path | None = None,
) -> dict[str, int] | None:
    """Validate authoritative mappings when the manifest opts into full scope.

    Slice mode intentionally keeps its existing, bounded validation behavior.
    """
    if manifest.get("scope", {}).get("mode") != "full":
        return None

    root = root.resolve()
    metadata = load_api_metadata(root)
    validate_api_sources(manifest, metadata)
    pinned_source = _require_pinned_source(root, metadata, upstream)
    if indexed_inputs is None or cases is None:
        indexed_inputs, cases = validate_inputs(root, manifest)

    api_rows, fixture_rows = _source_review_rows(root, pinned_source, manifest, metadata)
    uncertain_api = [row for row in api_rows if row["api_disposition"] == "uncertain"]
    uncertain_sources = [row for row in fixture_rows if row["api_disposition"] == "uncertain"]
    backlog_rows = [row for row in fixture_rows if row["fixture_status"] == "backlog"]

    blockers = (
        [
            f"uncertain API candidates remain ({len(uncertain_api)}): "
            f"{[row['qualified_name'] for row in uncertain_api[:12]]}"
        ]
        if uncertain_api
        else []
    )
    if uncertain_sources:
        blockers.append(
            f"source rows retain uncertain API disposition ({len(uncertain_sources)}): "
            f"{[row['backlog_id'] for row in uncertain_sources[:12]]}"
        )
    if backlog_rows:
        blockers.append(
            f"source rows remain in fixture backlog ({len(backlog_rows)}): "
            f"{[row['backlog_id'] for row in backlog_rows[:12]]}"
        )
    blockers.extend(_inspection_coverage(root, metadata, api_rows, cases))
    blockers.extend(_mapping_errors(root, manifest, indexed_inputs, api_rows, fixture_rows))
    blockers.extend(_requirement_errors(manifest, cases))
    if blockers:
        formatted = "\n".join(f"- {blocker}" for blocker in blockers)
        raise ContractError(f"full scope completeness rejected scope.mode=full:\n{formatted}")

    return {
        "api_candidates": len(api_rows),
        "supported_api_candidates": sum(row["api_disposition"] == "supported" for row in api_rows),
        "source_rows": len(fixture_rows),
        "mapped_source_rows": sum(row["fixture_status"] == "existing" for row in fixture_rows),
        "not_applicable_source_rows": sum(
            row["fixture_status"] == "not_applicable" for row in fixture_rows
        ),
        "parity_requirements": len(
            {
                requirement["id"]
                for surface in _all_manifest_surfaces(manifest)
                for operation in surface["operations"]
                for requirement in operation["requirements"]
                if "parity" in requirement["lanes"]
            }
        ),
        "indexed_parity_input_files": len(indexed_inputs),
    }
