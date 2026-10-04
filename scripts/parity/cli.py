"""Command-line entry point for contract validation and parity runs."""

from __future__ import annotations

import argparse
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
    INPUT_SCHEMA,
    MANIFEST_SCHEMA,
    ORACLE_COMMIT,
    RESULT_SCHEMA,
    UPSTREAM_BENCHMARK_RESULT_SCHEMA,
    ContractError,
    load_json,
    load_manifest,
    validate_benchmark_inputs,
    validate_inputs,
    validate_manifest,
    validate_result_artifact,
    validate_workflow_result,
)
from .envs import prepare_environments, validate_runtime_lock
from .runner import ROOT, run_parity
from .upstream_benchmark import UPSTREAM_RESULT_RELATIVE, run_upstream_benchmark

MANIFEST_RELATIVE = Path("tests/fixtures/manifest.yaml")
RESULT_SCHEMA_RELATIVE = Path("tests/fixtures/result-schema.json")
BENCHMARK_RESULT_SCHEMA_RELATIVE = Path("tests/fixtures/benchmark-result-schema.json")
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
        help="build the local wheel and prepare isolated, locked CPython 3.12 environments",
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

    for command_name, help_text in (
        ("run", "execute the isolated source oracle and target adapters"),
        ("oracle-only", "execute the isolated source oracle only"),
    ):
        command = subparsers.add_parser(command_name, help=help_text)
        command.add_argument("--root", type=Path, default=ROOT)
        command.add_argument("--manifest", type=Path, default=None)
        command.add_argument("--output", type=Path, default=None)

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
        "coverage": "validate that coverage is not applicable to this parity-only slice",
        "benchmark": "run the declared correctness-gated benchmark workload",
    }
    for lane in ("coverage", "benchmark"):
        command = subparsers.add_parser(lane, help=lane_help[lane])
        command.add_argument("--root", type=Path, default=ROOT)
        command.add_argument("--manifest", type=Path, default=None)

    upstream_benchmark = subparsers.add_parser(
        "benchmark-upstream",
        help="run the 74 pinned Starlette Router/GZip workloads behind exact source/package gates",
    )
    upstream_benchmark.add_argument("--root", type=Path, default=ROOT)
    upstream_benchmark.add_argument("--manifest", type=Path, default=None)

    aggregate = subparsers.add_parser("aggregate", help="aggregate compatible lane artifacts")
    aggregate.add_argument("results", nargs="*", type=Path)
    aggregate.add_argument("--root", type=Path, default=ROOT)
    aggregate.add_argument("--manifest", type=Path, default=None)
    return parser


def _manifest_path(root: Path, override: Path | None) -> Path:
    return (
        override if override and override.is_absolute() else root / (override or MANIFEST_RELATIVE)
    )


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
    report = validate_contract_repository(root, manifest_path)
    upstream = _upstream_path(upstream_override)
    commit, package = _source_identity(upstream)
    runtime_lock_sha256 = validate_runtime_lock(root, upstream)
    return {
        **report,
        "source_checkout_checked": True,
        "oracle_commit": commit,
        "oracle_package": package,
        "runtime_dependency_lock_sha256": runtime_lock_sha256,
    }


def validate_contract_repository(
    root: Path, manifest_override: Path | None = None
) -> dict[str, Any]:
    """Validate the repository-local parity contract without an upstream checkout."""
    root = root.resolve()
    manifest_path = _manifest_path(root, manifest_override)
    manifest = load_manifest(manifest_path)
    validate_manifest(manifest)
    metadata = load_api_metadata(root)
    validate_api_sources(manifest, metadata)
    indexed_inputs, cases = validate_inputs(root, manifest)
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

    return {
        "schema": MANIFEST_SCHEMA,
        "scope_mode": manifest["scope"]["mode"],
        "scope_id": manifest["scope"]["id"],
        "manifest_inventory_revision": manifest["scope"]["inventory"]["revision"],
        "indexed_parity_input_files": len(indexed_inputs),
        "indexed_benchmark_input_files": len(benchmark_inputs),
        "cases": len(cases),
        "target_profiles": len(manifest["target_profiles"]),
        "operations": sum(len(surface["operations"]) for surface in manifest["surfaces"]),
        "parity_requirements": sum(
            requirement["lanes"] == ["parity"]
            for surface in manifest["surfaces"]
            for operation in surface["operations"]
            for requirement in operation["requirements"]
        ),
        "parity_tooling_sources_compiled": source_count,
        "source_checkout_checked": False,
        "parity_passes_claimed": 0,
    }


def _find_case(cases: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    selected = [case for case in cases if case["case_id"] == case_id]
    if len(selected) != 1:
        raise ContractError(f"case ID must resolve exactly once: {case_id}")
    return selected[0]


def _find_operation(manifest: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return next(
        operation
        for surface in manifest["surfaces"]
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
    for surface in manifest["surfaces"]:
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
            print(
                json.dumps(
                    {"scope": manifest["scope"], "surfaces": manifest["surfaces"]},
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command in {"run", "oracle-only"}:
            result = run_parity(
                args.root.resolve(),
                "parity" if args.command == "run" else "oracle-only",
                args.output,
                _manifest_path(args.root.resolve(), args.manifest),
            )
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "summary": result["summary"],
                        "result": str(
                            args.output or (args.root.resolve() / "build/parity/parity-result.json")
                        ),
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
        if args.command in {"coverage", "benchmark"}:
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
                            "result": str(
                                args.root.resolve() / "build/parity/benchmark-result.json"
                            ),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0 if result["status"] == "completed" else 2
            return _lane_empty(args.root.resolve(), args.manifest, args.command)
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
            if not args.results:
                print(
                    json.dumps(
                        {
                            "status": "not_proven",
                            "reason": "no parity, coverage, or benchmark evidence was supplied",
                        },
                        sort_keys=True,
                    )
                )
                return 2
            active_root = args.root.resolve()
            active_manifest = _manifest_path(active_root, args.manifest)
            artifacts = [
                validate_result_artifact(
                    load_json(path), root=active_root, manifest_path=active_manifest
                )
                for path in args.results
            ]
            if len(artifacts) != len(args.results):
                raise ContractError("not every supplied artifact was validated")
            artifact_rows = [
                {
                    "path": str(path.resolve()),
                    "schema": artifact["schema"],
                    "status": artifact["status"],
                    "summary": artifact["summary"],
                }
                for path, artifact in zip(args.results, artifacts, strict=True)
            ]
            print(
                json.dumps(
                    {
                        "schema": "migration-parity/status-report@1",
                        "status": "not_proven",
                        "reason": "supplied evidence was validated, but the full replacement denominator remains incomplete",
                        "artifacts": artifact_rows,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        raise ContractError(f"unsupported command: {args.command}")
    except (ContractError, OSError, ValueError) as exc:
        print(f"parity contract error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
