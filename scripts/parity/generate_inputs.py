"""Generate runtime JSON inputs from authored YAML-compatible source documents.

The source documents use JSON-compatible YAML so the generator can reject
duplicate keys with the Python standard library and run in the pinned parity
environment without an additional YAML dependency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .api_sources import apply_api_sources, load_api_metadata, validate_api_sources
from .contract import (
    BENCHMARK_INPUT_SCHEMA,
    ContractError,
    load_json,
    load_manifest,
    validate_benchmark_document,
    validate_input_document,
    validate_manifest,
)
from .upstream_benchmark_contract import validate_upstream_workloads

MANIFEST_RELATIVE = Path("tests/fixtures/manifest.yaml")
SOURCE_ROOT = Path("tests/fixtures/sources")
INPUT_ROOT = Path("build/parity/inputs")
LANES = ("parity", "benchmark")


def _relative_input_path(value: str, lane: str) -> Path:
    path = Path(value)
    expected_prefix = INPUT_ROOT / lane
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.suffix != ".json"
        or path.parts[: len(expected_prefix.parts)] != expected_prefix.parts
    ):
        raise ContractError(
            f"manifest input path must stay under {expected_prefix.as_posix()}: {value}"
        )
    return path


def _source_path(root: Path, relative_input: Path, lane: str) -> Path:
    source_root = (root / SOURCE_ROOT / lane).resolve()
    source = (source_root / f"{relative_input.stem}.yaml").resolve()
    if source_root not in source.parents or not source.is_file():
        raise ContractError(
            f"missing authored YAML input for {relative_input.as_posix()}: "
            f"{source.relative_to(root).as_posix() if source.is_relative_to(root) else source}"
        )
    return source


def _json_bytes(document: Any) -> bytes:
    try:
        text = json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise ContractError(f"input source cannot be serialized as JSON: {exc}") from exc
    return text.encode("utf-8")


def _validate_sources(
    root: Path, manifest: dict[str, Any]
) -> list[tuple[Path, bytes, dict[str, Any]]]:
    generated: list[tuple[Path, bytes, dict[str, Any]]] = []
    parity_cases: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for lane in LANES:
        paths = manifest["input_index"][lane]
        for value in paths:
            relative = _relative_input_path(value, lane)
            if relative in seen_paths:
                raise ContractError(f"duplicate generated input path: {value}")
            seen_paths.add(relative)
            source_path = _source_path(root, relative, lane)
            document = load_json(source_path)
            if not isinstance(document, dict):
                raise ContractError(f"YAML input source must be an object: {source_path}")
            if lane == "parity":
                parity_cases.extend(validate_input_document(document, manifest))
            generated.append((relative, _json_bytes(document), document))

    case_ids = [case["case_id"] for case in parity_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("case IDs must be unique across authored parity input sources")
    parity_requirements = {
        requirement["id"]
        for surface in manifest["surfaces"]
        for operation in surface["operations"]
        for requirement in operation["requirements"]
        if "parity" in requirement["lanes"]
    }
    covered_requirements = {requirement for case in parity_cases for requirement in case["covers"]}
    missing_requirements = parity_requirements - covered_requirements
    if missing_requirements:
        raise ContractError(
            f"authored parity input sources omit requirements: {sorted(missing_requirements)}"
        )

    for relative, _raw, document in generated:
        if relative.parts[3] == "benchmark":
            if document.get("schema") == BENCHMARK_INPUT_SCHEMA:
                validate_benchmark_document(document, parity_cases, manifest)
            else:
                validate_upstream_workloads(document)
    return generated


def _write_generated(root: Path, generated: list[tuple[Path, bytes, dict[str, Any]]]) -> None:
    output_root = (root / INPUT_ROOT).resolve()
    if not output_root.is_relative_to(root.resolve() / "build/parity"):
        raise ContractError("generated input root escaped build/parity")
    expected: dict[str, bytes] = {}
    for relative, raw, _document in generated:
        path = (root / relative).resolve()
        if not path.is_relative_to(output_root):
            raise ContractError(f"generated input path escaped its output root: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        expected[path.as_posix()] = raw
    for lane in LANES:
        lane_root = output_root / lane
        if not lane_root.exists():
            continue
        for path in lane_root.rglob("*.json"):
            if path.resolve().as_posix() not in expected:
                path.unlink()
        for path in sorted(lane_root.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()


def _check_generated(root: Path, generated: list[tuple[Path, bytes, dict[str, Any]]]) -> None:
    expected = {str(root / relative): raw for relative, raw, _document in generated}
    output_root = root / INPUT_ROOT
    actual = {
        str(path): path.read_bytes()
        for lane in LANES
        for path in (output_root / lane).rglob("*.json")
    }
    if set(actual) != set(expected):
        raise ContractError(
            "generated input inventory differs: "
            f"missing={sorted(set(expected) - set(actual))}, "
            f"stale={sorted(set(actual) - set(expected))}"
        )
    mismatched = sorted(path for path in expected if actual[path] != expected[path])
    if mismatched:
        raise ContractError(f"generated input JSON differs from YAML sources: {mismatched}")


def generate_inputs(root: Path, *, check: bool = False) -> dict[str, int]:
    root = root.resolve()
    manifest_path = root / MANIFEST_RELATIVE
    manifest = load_manifest(manifest_path)
    metadata = load_api_metadata(root)
    if check:
        validate_api_sources(manifest, metadata)
    else:
        changed = apply_api_sources(manifest, metadata)
        if changed:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    validate_manifest(manifest)
    generated = _validate_sources(root, manifest)
    if check:
        _check_generated(root, generated)
    else:
        _write_generated(root, generated)
    return {
        "api_sources": len(metadata["api_sources"]),
        "parity_inputs": len(manifest["input_index"]["parity"]),
        "benchmark_inputs": len(manifest["input_index"]["benchmark"]),
        "generated_json": len(generated),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--check", action="store_true", help="verify generated JSON without writing"
    )
    args = parser.parse_args(argv)
    report = generate_inputs(args.root, check=args.check)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
