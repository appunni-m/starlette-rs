#!/usr/bin/env python3
"""Merge domain evidence and reject gaps in the pinned Starlette atlas."""

from __future__ import annotations

import argparse
import ast
import csv
import pathlib
import re
import subprocess
import sys

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.parity.api_sources import load_api_metadata  # noqa: E402
from scripts.parity.contract import (  # noqa: E402
    ContractError,
    load_json,
    load_manifest,
    validate_input_document,
)
from scripts.parity.generate_inputs import generate_inputs  # noqa: E402

CATALOG_FIELDS = [
    "record_type",
    "qualified_name",
    "signature_or_value",
    "constructor_signature",
    "source",
    "line",
    "documentation_evidence",
    "audit_status",
]
API_REVIEW_FIELDS = [
    "catalog_row",
    *CATALOG_FIELDS,
    "api_disposition",
    "evidence_refs",
    "rationale",
]
FIXTURE_FIELDS = [
    "backlog_id",
    "source_kind",
    "source_path",
    "source_item",
    "api_disposition",
    "requirement_ids",
    "stimulus_summary",
    "observation_selectors",
    "fixture_status",
    "fixture_path",
    "exclusion_reason",
    "evidence_refs",
]
API_DISPOSITIONS = {"supported", "private/internal", "uncertain"}
SOURCE_KINDS = {
    "upstream_test",
    "test_support",
    "documentation",
    "deprecation",
    "optional_feature",
    "python_version",
    "api_behavior",
}
FIXTURE_STATUSES = {"existing", "backlog", "not_applicable"}


class AtlasError(Exception):
    pass


def read_csv(path: pathlib.Path, expected_fields: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_fields:
            raise AtlasError(
                f"{path}: expected header {expected_fields!r}, got {reader.fieldnames!r}"
            )
        return list(reader)


def write_csv(path: pathlib.Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_functions(upstream: pathlib.Path, test_source_root: str) -> set[tuple[str, str]]:
    discovered: set[tuple[str, str]] = set()
    test_files = sorted((upstream / test_source_root).rglob("test_*.py"))

    def walk(block: list[ast.stmt], parents: tuple[str, ...], relative: str) -> None:
        for node in block:
            if isinstance(node, ast.ClassDef):
                walk(node.body, (*parents, node.name), relative)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    discovered.add((relative, ".".join((*parents, node.name))))

    for path in test_files:
        relative = path.relative_to(upstream).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        walk(tree.body, (), relative)
    return discovered


def test_support_modules(upstream: pathlib.Path, test_source_root: str) -> set[str]:
    return {
        path.relative_to(upstream).as_posix()
        for path in (upstream / test_source_root).rglob("*.py")
        if not path.name.startswith("test_")
    }


def canonical_test_item(source_item: str) -> str:
    """Drop pytest's displayed parameter ID while retaining the source test."""
    return source_item.split("[", 1)[0]


def check_input_fixture(path: pathlib.Path, manifest: dict[str, object]) -> None:
    """Validate a committed YAML-compatible input source and reject output fields."""
    try:
        validate_input_document(load_json(path), manifest)
    except ContractError as error:
        raise AtlasError(f"{path}: invalid input-only parity definition: {error}") from error


def check_evidence_refs(
    raw_references: str,
    owner: pathlib.Path,
    roots: list[pathlib.Path],
) -> None:
    references = [reference.strip() for reference in raw_references.split(";")]
    if not references or any(not reference for reference in references):
        raise AtlasError(f"{owner}: evidence_refs contains an empty path")
    for reference in references:
        source_path = reference.split(":", 1)[0]
        relative_path = pathlib.Path(source_path)
        if relative_path.is_absolute():
            raise AtlasError(f"{owner}: evidence paths must be repository-relative")
        if not source_path or not any(
            (root / relative_path).resolve().is_file()
            and root in (root / relative_path).resolve().parents
            for root in roots
        ):
            raise AtlasError(
                f"{owner}: evidence file does not exist in an allowed tree: {source_path}"
            )


def nav_pages(upstream: pathlib.Path, documentation_root: str) -> set[str]:
    config = (upstream / "mkdocs.yml").read_text(encoding="utf-8")
    nav_match = re.search(r"(?ms)^nav:\s*\n(.*?)(?=^[A-Za-z_][\w-]*:\s*$|\Z)", config)
    if nav_match is None:
        raise AtlasError("could not locate the upstream mkdocs nav block")
    pages = set(re.findall(r'^\s*-\s+[^:]+:\s+"([^\"]+\.md)"\s*$', nav_match.group(1), re.M))
    return {f"{documentation_root}/{page}" for page in pages}


def check_api_reviews(
    catalog_path: pathlib.Path,
    review_paths: list[pathlib.Path],
    upstream: pathlib.Path,
) -> list[dict[str, str]]:
    catalog = read_csv(catalog_path, CATALOG_FIELDS)
    candidate_by_row = {str(index + 2): row for index, row in enumerate(catalog)}
    if len(candidate_by_row) != len(catalog):
        raise AtlasError("catalog record ordinals are not unique")

    reviewed: dict[str, dict[str, str]] = {}
    for path in review_paths:
        for row in read_csv(path, API_REVIEW_FIELDS):
            catalog_row = row["catalog_row"]
            original = candidate_by_row.get(catalog_row)
            if original is None:
                raise AtlasError(f"{path}: catalog_row {catalog_row!r} is not in the catalog")
            if catalog_row in reviewed:
                raise AtlasError(f"catalog row {catalog_row} appears in multiple review partitions")
            if any(row[field] != original[field] for field in CATALOG_FIELDS):
                raise AtlasError(
                    f"{path}: catalog row {catalog_row} was changed from its source record"
                )
            if row["api_disposition"] not in API_DISPOSITIONS:
                raise AtlasError(f"{path}: invalid disposition for catalog row {catalog_row}")
            if not row["evidence_refs"].strip() or not row["rationale"].strip():
                raise AtlasError(f"{path}: catalog row {catalog_row} needs evidence and rationale")
            check_evidence_refs(row["evidence_refs"], path, [upstream])
            reviewed[catalog_row] = row

    missing = sorted(set(candidate_by_row) - set(reviewed), key=int)
    if missing:
        raise AtlasError(
            f"API review covers {len(reviewed)}/{len(candidate_by_row)} catalog rows; "
            f"missing catalog rows: {', '.join(missing[:20])}"
        )
    return [reviewed[row_id] for row_id in sorted(reviewed, key=int)]


def check_fixture_backlog(
    fixture_paths: list[pathlib.Path],
    target_root: pathlib.Path,
    upstream: pathlib.Path,
    test_source_root: str,
    documentation_root: str,
    manifest: dict[str, object],
) -> list[dict[str, str]]:
    expected_tests = test_functions(upstream, test_source_root)
    expected_support_modules = test_support_modules(upstream, test_source_root)
    expected_docs = nav_pages(upstream, documentation_root)
    backlog: list[dict[str, str]] = []
    backlog_ids: set[str] = set()
    mapped_tests: set[tuple[str, str]] = set()
    mapped_support_modules: set[str] = set()
    mapped_docs: set[str] = set()

    for path in fixture_paths:
        for row in read_csv(path, FIXTURE_FIELDS):
            if not row["backlog_id"].strip():
                raise AtlasError(f"{path}: empty backlog_id")
            if row["backlog_id"] in backlog_ids:
                raise AtlasError(f"duplicate backlog_id {row['backlog_id']!r}")
            backlog_ids.add(row["backlog_id"])
            if row["source_kind"] not in SOURCE_KINDS:
                raise AtlasError(f"{path}: invalid source_kind for {row['backlog_id']}")
            if row["api_disposition"] not in API_DISPOSITIONS | {"n/a"}:
                raise AtlasError(f"{path}: invalid API disposition for {row['backlog_id']}")
            if row["fixture_status"] not in FIXTURE_STATUSES:
                raise AtlasError(f"{path}: invalid fixture_status for {row['backlog_id']}")
            if not row["source_path"].strip() or not row["source_item"].strip():
                raise AtlasError(f"{path}: source identity is required for {row['backlog_id']}")
            source_file = (upstream / row["source_path"]).resolve()
            if upstream not in source_file.parents or not source_file.is_file():
                raise AtlasError(
                    f"{path}: source file does not exist inside the pinned tree: {row['source_path']}"
                )
            if not row["evidence_refs"].strip():
                raise AtlasError(f"{path}: evidence_refs are required for {row['backlog_id']}")
            check_evidence_refs(row["evidence_refs"], path, [upstream, target_root])

            fixture_path = row["fixture_path"].strip()
            if row["fixture_status"] == "existing":
                if not fixture_path:
                    raise AtlasError(
                        f"{path}: existing fixture path missing for {row['backlog_id']}"
                    )
                resolved = (target_root / fixture_path).resolve()
                fixture_root = (target_root / "tests/fixtures/sources/parity").resolve()
                if fixture_root not in resolved.parents or not resolved.is_file():
                    raise AtlasError(
                        f"{path}: existing source is missing or outside authored parity inputs"
                    )
                if resolved.suffix != ".yaml":
                    raise AtlasError(f"{path}: committed parity sources must use .yaml files")
                check_input_fixture(resolved, manifest)
            elif fixture_path:
                raise AtlasError(f"{path}: fixture_path is only valid for existing inputs")
            if row["fixture_status"] == "not_applicable":
                if not row["exclusion_reason"].strip():
                    raise AtlasError(f"{path}: exclusion reason missing for {row['backlog_id']}")
            elif row["exclusion_reason"].strip():
                raise AtlasError(f"{path}: exclusion reason is only valid for not_applicable")
            if row["fixture_status"] != "not_applicable" and (
                not row["stimulus_summary"].strip() or not row["observation_selectors"].strip()
            ):
                raise AtlasError(f"{path}: stimulus and observation selectors are required")

            if row["source_kind"] == "upstream_test":
                identity = (row["source_path"], canonical_test_item(row["source_item"]))
                if identity not in expected_tests:
                    raise AtlasError(f"{path}: unknown upstream test identity {identity!r}")
                mapped_tests.add(identity)
            if (
                row["source_kind"] == "test_support"
                and row["source_path"] in expected_support_modules
            ):
                mapped_support_modules.add(row["source_path"])
            if row["source_path"] in expected_docs:
                mapped_docs.add(row["source_path"])
            backlog.append(row)

    missing_tests = expected_tests - mapped_tests
    if missing_tests:
        first = sorted(missing_tests)[:20]
        raise AtlasError(
            f"fixture backlog maps {len(mapped_tests)}/{len(expected_tests)} upstream test "
            f"functions; missing: {first!r}"
        )
    missing_support_modules = expected_support_modules - mapped_support_modules
    if missing_support_modules:
        raise AtlasError(
            f"fixture backlog maps {len(mapped_support_modules)}/{len(expected_support_modules)} "
            f"shared test support modules; missing: {', '.join(sorted(missing_support_modules))}"
        )
    missing_docs = expected_docs - mapped_docs
    if missing_docs:
        raise AtlasError(
            f"fixture backlog represents {len(mapped_docs)}/{len(expected_docs)} nav pages; "
            f"missing: {', '.join(sorted(missing_docs))}"
        )
    return sorted(
        backlog, key=lambda row: (row["backlog_id"], row["source_path"], row["source_item"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=pathlib.Path, required=True)
    parser.add_argument(
        "--catalog", type=pathlib.Path, default=pathlib.Path("docs/api-surface.csv")
    )
    parser.add_argument("--reviews", type=pathlib.Path, default=pathlib.Path("docs/atlas/reviews"))
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path("docs/atlas"))
    parser.add_argument(
        "--check", action="store_true", help="validate partitions without writing merged files"
    )
    args = parser.parse_args()

    target_root = pathlib.Path.cwd().resolve()
    upstream = args.upstream.resolve()
    try:
        metadata = load_api_metadata(target_root)
    except ContractError as error:
        raise AtlasError(f"invalid API source metadata: {error}") from error
    authority = metadata["authority"]
    inventory = metadata["api_inventory"]
    try:
        generate_inputs(target_root)
    except ContractError as error:
        raise AtlasError(f"authored parity inputs are invalid: {error}") from error
    manifest = load_manifest(target_root / "tests/fixtures/manifest.yaml")
    commit = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != authority["revision"]:
        raise AtlasError(f"expected Starlette commit {authority['revision']}, got {commit}")

    api_paths = sorted(args.reviews.glob("*-api.csv"))
    fixture_paths = sorted(args.reviews.glob("*-fixtures.csv"))
    if not api_paths or not fixture_paths:
        raise AtlasError("no domain API and fixture review partitions found")
    api_rows = check_api_reviews(args.catalog, api_paths, upstream)
    fixture_rows = check_fixture_backlog(
        fixture_paths,
        target_root,
        upstream,
        inventory["test_source_root"],
        inventory["documentation_root"],
        manifest,
    )
    if not args.check:
        write_csv(args.output / "api-review.csv", API_REVIEW_FIELDS, api_rows)
        write_csv(args.output / "coverage-matrix.csv", FIXTURE_FIELDS, fixture_rows)
        backlog_rows = [row for row in fixture_rows if row["fixture_status"] == "backlog"]
        write_csv(args.output / "fixture-backlog.csv", FIXTURE_FIELDS, backlog_rows)
    print(f"API review: {len(api_rows)}/{len(api_rows)} candidate rows dispositioned")
    test_module_count = len(
        {path for path, _ in test_functions(upstream, inventory["test_source_root"])}
    )
    nav_page_count = len(nav_pages(upstream, inventory["documentation_root"]))
    support_module_count = len(test_support_modules(upstream, inventory["test_source_root"]))
    print(
        f"Coverage matrix: {len(fixture_rows)} mappings; "
        f"new fixture backlog: {sum(row['fixture_status'] == 'backlog' for row in fixture_rows)} items; "
        f"{test_module_count} upstream test modules and "
        f"{nav_page_count} docs nav pages fully mapped; "
        f"{support_module_count} shared test support modules represented"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AtlasError as error:
        print(f"atlas error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
