#!/usr/bin/env python3
"""Check first-party Rust file lengths and prevent unreviewed growth."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "scripts" / "rust_file_size_baseline.json"
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    "build",
    "generated",
    "node_modules",
    "target",
    "third_party",
    "vendor",
}
MAX_FILE_LINES = 1_000
REVIEW_FILE_LINES = 800
BASELINE_KEYS = {
    "format_version",
    "max_file_lines",
    "review_file_lines",
    "files",
}


def rust_sources() -> list[Path]:
    sources: list[Path] = []
    for directory, child_directories, filenames in os.walk(ROOT, topdown=True):
        child_directories[:] = sorted(
            name for name in child_directories if name not in EXCLUDED_DIRECTORIES
        )
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if filename.endswith(".rs") and not path.is_symlink():
                sources.append(path)
    return sorted(sources)


def physical_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def empty_baseline() -> dict[str, object]:
    return {
        "format_version": 1,
        "max_file_lines": MAX_FILE_LINES,
        "review_file_lines": REVIEW_FILE_LINES,
        "files": {},
    }


def load_baseline() -> dict[str, object]:
    if not BASELINE_PATH.exists():
        return empty_baseline()

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict) or set(baseline) != BASELINE_KEYS:
        raise ValueError("baseline must contain exactly the documented top-level keys")
    if baseline["format_version"] != 1:
        raise ValueError("unsupported baseline format version")
    if baseline["max_file_lines"] != MAX_FILE_LINES:
        raise ValueError("baseline max_file_lines does not match the checker")
    if baseline["review_file_lines"] != REVIEW_FILE_LINES:
        raise ValueError("baseline review_file_lines does not match the checker")

    files = baseline["files"]
    if not isinstance(files, dict):
        raise ValueError("baseline files must be a JSON object")
    for path, lines in files.items():
        if not isinstance(path, str):
            raise ValueError(f"invalid baseline source path: {path!r}")
        relative_path = PurePosixPath(path)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative_path.suffix != ".rs"
        ):
            raise ValueError(f"invalid baseline source path: {path!r}")
        if not isinstance(lines, int) or isinstance(lines, bool) or lines <= MAX_FILE_LINES:
            raise ValueError(f"invalid baseline line count for {path}: {lines!r}")
    return baseline


def write_baseline(files: dict[str, int]) -> None:
    data = empty_baseline()
    data["files"] = files
    temporary_path = BASELINE_PATH.with_suffix(".json.tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(BASELINE_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="record current over-limit files after reviewing the baseline diff",
    )
    args = parser.parse_args()

    try:
        baseline = load_baseline()
        counts = {
            path.relative_to(ROOT).as_posix(): physical_line_count(path) for path in rust_sources()
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Rust source-size check could not read its inputs: {error}", file=sys.stderr)
        return 2

    if args.update_baseline:
        files = {path: count for path, count in sorted(counts.items()) if count > MAX_FILE_LINES}
        try:
            write_baseline(files)
        except OSError as error:
            print(f"Rust source-size baseline could not be written: {error}", file=sys.stderr)
            return 2
        print(
            f"Recorded {len(files)} over-limit Rust files in "
            f"{BASELINE_PATH.relative_to(ROOT)}; review the baseline diff."
        )
        return 0

    baseline_files = baseline["files"]
    if not isinstance(baseline_files, dict):
        print("baseline files must be a JSON object", file=sys.stderr)
        return 2
    errors: list[str] = []
    reports: list[str] = []
    over_limit_count = 0
    review_count = 0

    for path, count in sorted(counts.items()):
        previous = baseline_files.get(path)
        if count > MAX_FILE_LINES:
            over_limit_count += 1
            if previous is None:
                errors.append(
                    f"new over-limit file: {path} has {count} lines (limit {MAX_FILE_LINES})"
                )
                reports.append(f"new violation: {path} has {count} lines")
            elif count > previous:
                errors.append(
                    f"over-limit file grew: {path} has {count} lines, baseline is {previous}"
                )
                reports.append(f"growth: {path} has {count} lines (baseline {previous})")
            else:
                reports.append(
                    f"baseline: {path} has {count} lines "
                    f"(limit {MAX_FILE_LINES}; ceiling {previous})"
                )
        elif previous is not None:
            errors.append(
                f"stale baseline entry for {path}: it is now at {count} lines "
                f"(limit {MAX_FILE_LINES}); review and update the baseline"
            )

        if REVIEW_FILE_LINES <= count <= MAX_FILE_LINES:
            review_count += 1
            reports.append(
                f"review: {path} has {count} lines (review threshold {REVIEW_FILE_LINES})"
            )

    for path in sorted(set(baseline_files) - set(counts)):
        errors.append(f"stale baseline entry for missing Rust source {path}")

    print(
        f"Rust source-size check: {len(counts)} files; {over_limit_count} over the "
        f"{MAX_FILE_LINES}-line limit; {review_count} at the "
        f"{REVIEW_FILE_LINES}-line review threshold."
    )
    for report in reports:
        print(f"  {report}")
    if errors:
        print("Rust source-size violations:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
