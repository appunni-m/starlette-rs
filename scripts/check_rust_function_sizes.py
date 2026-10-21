#!/usr/bin/env python3
"""Run strict Clippy and ratchet first-party Rust functions over 100 lines."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "scripts" / "rust_function_size_baseline.json"
FUNCTION_HARD_LIMIT = 100
FUNCTION_REVIEW_THRESHOLD = 60
TOO_MANY_LINES = "clippy::too_many_lines"
LINE_COUNT_RE = re.compile(r"too many lines \((\d+)/(\d+)\)")
BASELINE_KEYS = {"format_version", "hard_limit", "review_threshold", "functions"}
FUNCTION_KEYS = {"path", "signature", "occurrence", "lines"}


def lint_code(message: dict[str, object]) -> str | None:
    code = message.get("code")
    return str(code.get("code")) if isinstance(code, dict) else None


def normalize_signature(span: dict[str, object]) -> str:
    pieces = span.get("text", [])
    if not isinstance(pieces, list):
        return ""
    return " ".join(
        " ".join(str(piece.get("text", "")).split()) for piece in pieces if isinstance(piece, dict)
    ).strip()


def source_path(file_name: str) -> str | None:
    path = Path(file_name)
    if not path.is_absolute():
        path = ROOT / path
    try:
        relative = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    if relative.suffix != ".rs":
        return None
    return relative.as_posix()


def function_metrics(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    locations: dict[tuple[str, str], dict[int, int]] = defaultdict(dict)
    for message in messages:
        match = LINE_COUNT_RE.search(str(message.get("message", "")))
        spans = message.get("spans", [])
        span = (
            next(
                (item for item in spans if item.get("is_primary")),
                None,
            )
            if isinstance(spans, list)
            else None
        )
        if match is None or span is None:
            raise ValueError("could not read a Clippy too_many_lines diagnostic")
        path = source_path(str(span.get("file_name", "")))
        if path is None:
            continue
        signature = normalize_signature(span)
        if not signature:
            raise ValueError(f"missing function signature in Clippy diagnostic for {path}")
        line = int(span.get("line_start", 0))
        locations[(path, signature)][line] = max(
            int(match.group(1)), locations[(path, signature)].get(line, 0)
        )

    metrics: list[dict[str, object]] = []
    for (path, signature), starts in sorted(locations.items()):
        for occurrence, (line, count) in enumerate(sorted(starts.items()), start=1):
            metrics.append(
                {
                    "path": path,
                    "signature": signature,
                    "occurrence": occurrence,
                    "lines": count,
                    "line_start": line,
                }
            )
    return metrics


def metric_key(metric: dict[str, object]) -> tuple[str, str, int]:
    return (
        str(metric["path"]),
        str(metric["signature"]),
        int(metric["occurrence"]),
    )


def empty_baseline() -> dict[str, object]:
    return {
        "format_version": 1,
        "hard_limit": FUNCTION_HARD_LIMIT,
        "review_threshold": FUNCTION_REVIEW_THRESHOLD,
        "functions": [],
    }


def load_baseline() -> dict[str, object]:
    if not BASELINE_PATH.exists():
        return empty_baseline()
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict) or set(baseline) != BASELINE_KEYS:
        raise ValueError("baseline must contain exactly the documented top-level keys")
    if baseline["format_version"] != 1:
        raise ValueError("unsupported function-size baseline format")
    if baseline["hard_limit"] != FUNCTION_HARD_LIMIT:
        raise ValueError("baseline hard limit does not match the checker")
    if baseline["review_threshold"] != FUNCTION_REVIEW_THRESHOLD:
        raise ValueError("baseline review threshold does not match the checker")
    functions = baseline["functions"]
    if not isinstance(functions, list):
        raise ValueError("baseline functions must be a JSON array")

    keys: set[tuple[str, str, int]] = set()
    for function in functions:
        if not isinstance(function, dict) or set(function) != FUNCTION_KEYS:
            raise ValueError("each baseline function must contain exactly the documented keys")
        path = function["path"]
        signature = function["signature"]
        occurrence = function["occurrence"]
        lines = function["lines"]
        relative = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("")
        if (
            not isinstance(path, str)
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix != ".rs"
            or not isinstance(signature, str)
            or not signature.strip()
            or not isinstance(occurrence, int)
            or isinstance(occurrence, bool)
            or occurrence < 1
            or not isinstance(lines, int)
            or isinstance(lines, bool)
            or lines <= FUNCTION_HARD_LIMIT
        ):
            raise ValueError(f"invalid function-size baseline entry: {function!r}")
        key = (path, signature, occurrence)
        if key in keys:
            raise ValueError(f"duplicate function-size baseline entry: {key!r}")
        keys.add(key)
    return baseline


def write_baseline(functions: list[dict[str, object]]) -> None:
    baseline = empty_baseline()
    baseline["functions"] = [
        {key: metric[key] for key in ("path", "signature", "occurrence", "lines")}
        for metric in functions
        if int(metric["lines"]) > FUNCTION_HARD_LIMIT
    ]
    temporary_path = BASELINE_PATH.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(BASELINE_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def run_clippy() -> tuple[list[dict[str, object]], int]:
    command = [
        *shlex.split(os.environ.get("CARGO", "cargo")),
        "clippy",
        "--workspace",
        "--all-targets",
        "--all-features",
        "--message-format=json",
        "--locked",
        "--",
        "-D",
        "warnings",
        "--force-warn",
        TOO_MANY_LINES,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        print(f"Clippy function-size check could not run: {error}", file=sys.stderr)
        return [], 2

    messages: list[dict[str, object]] = []
    for raw in result.stdout.splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            print(raw)
            continue
        if item.get("reason") != "compiler-message":
            continue
        message = item.get("message", {})
        if not isinstance(message, dict):
            continue
        if lint_code(message) == TOO_MANY_LINES:
            messages.append(message)
        elif message.get("level") == "error":
            rendered = message.get("rendered")
            if rendered:
                print(rendered, file=sys.stderr, end="")

    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode:
        print(f"Clippy failed with exit code {result.returncode}", file=sys.stderr)
    try:
        return function_metrics(messages), result.returncode
    except ValueError as error:
        print(f"Clippy function-size diagnostics were invalid: {error}", file=sys.stderr)
        return [], 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record reviewed legacy functions over the hard line limit",
    )
    args = parser.parse_args()

    try:
        baseline = load_baseline()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Function-size baseline could not be read: {error}", file=sys.stderr)
        return 2

    metrics, clippy_status = run_clippy()
    if clippy_status:
        return clippy_status

    over_limit = [metric for metric in metrics if int(metric["lines"]) > FUNCTION_HARD_LIMIT]
    if args.update_baseline:
        try:
            write_baseline(over_limit)
        except OSError as error:
            print(f"Function-size baseline could not be written: {error}", file=sys.stderr)
            return 2
        print(
            f"Recorded {len(over_limit)} reviewed legacy functions over "
            f"{FUNCTION_HARD_LIMIT} lines in {BASELINE_PATH.relative_to(ROOT)}."
        )
        return 0

    raw_baseline = baseline["functions"]
    if not isinstance(raw_baseline, list):
        print("Function-size baseline functions must be a JSON array", file=sys.stderr)
        return 2
    function_baseline = {metric_key(item): int(item["lines"]) for item in raw_baseline}
    current_keys = {metric_key(metric) for metric in over_limit}
    errors: list[str] = []
    legacy_count = 0
    for metric in over_limit:
        key = metric_key(metric)
        count = int(metric["lines"])
        previous = function_baseline.get(key)
        location = f"{metric['path']}:{metric['line_start']} {metric['signature']}"
        if previous is None:
            errors.append(
                f"new over-limit function: {location} has {count} lines "
                f"(limit {FUNCTION_HARD_LIMIT})"
            )
        elif count > previous:
            errors.append(
                f"over-limit function grew: {location} has {count} lines, baseline is {previous}"
            )
        else:
            legacy_count += 1

    for key in sorted(set(function_baseline) - current_keys):
        errors.append(f"stale function-size baseline entry: {key!r}")

    review_count = sum(int(metric["lines"]) > FUNCTION_REVIEW_THRESHOLD for metric in metrics)
    print(
        f"Rust function-size check: {review_count} functions over "
        f"{FUNCTION_REVIEW_THRESHOLD} lines; {legacy_count} legacy functions over "
        f"{FUNCTION_HARD_LIMIT} lines are at or below baseline."
    )
    for metric in sorted(metrics, key=lambda item: int(item["lines"]), reverse=True)[:5]:
        print(
            f"  review: {metric['path']}:{metric['line_start']} has "
            f"{metric['lines']} lines: {metric['signature']}"
        )
    if errors:
        print("Rust function-size ratchet violations:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
