"""Render and validate the checked-in summary of the latest upstream benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .contract import (
    _pairs_no_duplicates,
    _reject_constant,
    validate_result_artifact,
)

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "build/parity/upstream-benchmark-result.json"
DOCUMENT_PATH = ROOT / "docs/BENCHMARKS.md"
START_MARKER = "<!-- generated-upstream-benchmark:start -->"
END_MARKER = "<!-- generated-upstream-benchmark:end -->"


def _decode_json(path: Path, contents: bytes) -> dict[str, Any]:
    value = json.loads(
        contents,
        object_pairs_hook=_pairs_no_duplicates,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _profile_summary(result: dict[str, Any]) -> str:
    identity = result["identity"]
    gate = identity["parity_gate"]
    preflight_path = ROOT / gate["path"]
    preflight_bytes = preflight_path.read_bytes()
    if hashlib.sha256(preflight_bytes).hexdigest() != gate["sha256"]:
        raise ValueError("benchmark correctness preflight changed after validation")
    preflight = _decode_json(preflight_path, preflight_bytes)
    counts = Counter(
        (row["target_profile"], row["outcome"]) for row in preflight.get("comparisons", [])
    )
    package_profile = "python-package-cpython312"
    native_profile = "rust-native-local"
    package_passed = counts[(package_profile, "pass")]
    package_selected = sum(
        value for (profile, _), value in counts.items() if profile == package_profile
    )
    native_passed = counts[(native_profile, "pass")]
    native_not_run = counts[(native_profile, "not_run")]
    native_selected = sum(
        value for (profile, _), value in counts.items() if profile == native_profile
    )
    return (
        f"The preflight passed {package_passed}/{package_selected} Python-package "
        f"comparisons and {native_passed}/{native_selected} Rust-native comparisons; "
        f"{native_not_run} Rust-native rows were `not_run`."
    )


def render(result_path: Path = RESULT_PATH) -> str:
    result_bytes = result_path.read_bytes()
    result = _decode_json(result_path, result_bytes)
    validate_result_artifact(result, root=ROOT)
    if result["status"] != "completed":
        raise ValueError("only a completed 74-workload benchmark can update this evidence")

    identity = result["identity"]
    summary = result["summary"]
    workloads = result["workloads"]
    if not isinstance(workloads, list):
        raise ValueError("upstream benchmark result workloads must be an array")

    categories: dict[str, list[dict[str, Any]]] = {"router": [], "gzip": []}
    for workload in workloads:
        category = workload.get("category")
        if category not in categories:
            raise ValueError(f"unsupported benchmark category: {category!r}")
        categories[category].append(workload)

    hashes_match = 0
    faster: dict[str, int] = {}
    ratios: dict[str, float] = {}
    for category, rows in categories.items():
        if not rows:
            raise ValueError(f"benchmark result has no {category} workloads")
        if any(row.get("comparison", {}).get("status") != "measured" for row in rows):
            raise ValueError(f"benchmark result has an unmeasured {category} workload")
        category_ratios: list[float] = []
        faster[category] = 0
        for row in rows:
            comparison = row["comparison"]
            source_median = comparison["source_median"]
            package_median = comparison["package_median"]
            if package_median <= 0:
                raise ValueError("package median must be positive")
            category_ratios.append(source_median / package_median)
            faster[category] += source_median < package_median
            gate = row["correctness_gate"]
            if gate.get("status") != "pass" or gate.get(
                "normalized_source_observation_sha256"
            ) != gate.get("normalized_target_observation_sha256"):
                raise ValueError("benchmark workload has a failed source/package gate")
            hashes_match += 1
        ratios[category] = statistics.median(category_ratios)

    declared = summary["declared"]
    measured = summary["measured"]
    if declared != len(workloads) or measured != len(workloads):
        raise ValueError("benchmark result counts do not match its workload rows")

    source_revision = identity["source_revision"]
    target = identity.get("target_checkout")
    if target is None:
        raise ValueError("benchmark result has no target checkout identity")
    target_state = "dirty" if target["dirty"] else "clean"
    package_environment = next(
        item
        for item in identity["prepared_environments"]
        if item["id"] == "starlette-rs-py-cpython312"
    )
    result_sha256 = hashlib.sha256(result_bytes).hexdigest()
    preflight = identity["parity_gate"]
    profile_summary = _profile_summary(result)

    lines = [
        "## Latest paired benchmark run",
        "",
        f"Run `{identity['run_id']}` completed from `{identity['started_at']}` "
        f"through `{identity['finished_at']}`.",
        "",
        f"The source oracle is Starlette 1.6.0 at `{source_revision}`. The target "
        f"checkout is {target_state} revision `{target['revision']}` with working-tree "
        f"SHA-256 `{target['working_tree_sha256']}`.",
        "",
        f"The runner measured {measured}/{declared} source/package workloads: "
        f"{len(categories['router'])} Router and {len(categories['gzip'])} GZip. "
        f"It reported {summary['failed']} failures, {summary['not_run']} source/package "
        f"not-run rows, and {summary['native_not_run_workloads']} Rust-native "
        "not-run workload rows because the native API does not expose these equivalent "
        "ASGI workload boundaries.",
        "",
        f"The correctness preflight `{preflight['run_id']}` selected "
        f"{preflight['summary']['selected']} profile comparisons, with "
        f"{preflight['summary']['passed']} passed, "
        f"{preflight['summary']['failed']} failed, "
        f"{preflight['summary']['infrastructure_errors']} infrastructure errors, and "
        f"{preflight['summary']['not_run']} not-run rows.",
    ]
    lines.extend(["", profile_summary])

    lines.extend(
        [
            "",
            f"The median source/package latency ratio was {ratios['router']:.3f} for "
            f"Router and {ratios['gzip']:.3f} for GZip. Source latency was lower in "
            f"{faster['router']}/{len(categories['router'])} Router and "
            f"{faster['gzip']}/{len(categories['gzip'])} GZip workloads. "
            f"Normalized observation hashes matched for {hashes_match}/{measured} "
            "measured workloads.",
            "",
            f"Manifest SHA-256: `{identity['manifest']['sha256']}`. Benchmark input "
            f"SHA-256: `{identity['input']['sha256']}`. Installed wheel SHA-256: "
            f"`{package_environment['artifact_sha256']}`. Result artifact SHA-256: "
            f"`{result_sha256}`.",
            "",
            "These are workload-specific local timings, not a general performance "
            "claim, CodSpeed measurements, or evidence of full Starlette parity.",
        ]
    )
    return "\n".join(lines)


def replace_block(document: str, block: str) -> str:
    if document.count(START_MARKER) != 1 or document.count(END_MARKER) != 1:
        raise ValueError("benchmark evidence markers must occur exactly once")
    start = document.index(START_MARKER) + len(START_MARKER)
    end = document.index(END_MARKER)
    if end < start:
        raise ValueError("benchmark evidence markers are out of order")
    return f"{document[:start]}\n\n{block}\n\n{document[end:]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="update the marked evidence block")
    mode.add_argument("--check", action="store_true", help="check the marked block (default)")
    args = parser.parse_args()

    if not RESULT_PATH.is_file():
        if args.write:
            print("benchmark result is missing; run make benchmark-upstream first", file=sys.stderr)
            return 1
        print("benchmark evidence freshness check skipped: no local result artifact")
        return 0

    try:
        document = DOCUMENT_PATH.read_text(encoding="utf-8")
        rendered = replace_block(document, render())
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"benchmark evidence check failed: {error}", file=sys.stderr)
        return 1

    if args.write:
        DOCUMENT_PATH.write_text(rendered, encoding="utf-8")
        print("updated docs/BENCHMARKS.md from the latest local result artifact")
        return 0
    if rendered != DOCUMENT_PATH.read_text(encoding="utf-8"):
        print(
            "docs/BENCHMARKS.md is stale; run make benchmark-upstream to refresh its evidence",
            file=sys.stderr,
        )
        return 1
    print("benchmark evidence check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
