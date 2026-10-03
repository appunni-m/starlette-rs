"""Migrate active authored parity inputs from schema @30 to @31."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

OLD_SCHEMA = "migration-parity/parity-input@30"
NEW_SCHEMA = "migration-parity/parity-input@31"
MANIFEST_PATH = Path("tests/fixtures/manifest.yaml")


def _indexed_source_paths(repository_root: Path) -> list[Path]:
    manifest = json.loads((repository_root / MANIFEST_PATH).read_text(encoding="utf-8"))
    generated_paths = manifest["input_index"]["parity"]
    if not isinstance(generated_paths, list) or not generated_paths:
        raise ValueError("manifest input_index.parity must be a non-empty array")

    source_paths: list[Path] = []
    for generated_path in generated_paths:
        path = PurePosixPath(generated_path)
        if (
            len(path.parts) != 5
            or path.parts[:4] != ("build", "parity", "inputs", "parity")
            or path.suffix != ".json"
        ):
            raise ValueError(f"unsupported generated parity input path: {generated_path!r}")
        source_paths.append(
            repository_root / "tests" / "fixtures" / "sources" / "parity" / f"{path.stem}.yaml"
        )
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("manifest input_index.parity contains duplicate source paths")
    return source_paths


def _migrate_file(path: Path, *, check_only: bool) -> bool:
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path} must contain an object")
    schema = parsed.get("schema")
    if schema == NEW_SCHEMA:
        return False
    if schema != OLD_SCHEMA:
        raise ValueError(f"{path} uses unexpected schema {schema!r}")
    if check_only:
        raise ValueError(f"{path} still uses {OLD_SCHEMA}")

    lines = raw.splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"{path} has no top-level schema header")
    line_body = lines[1].rstrip("\r\n")
    line_ending = lines[1][len(line_body) :]
    match = re.fullmatch(
        r'(?P<prefix>\s*"schema"\s*:\s*")(?P<schema>[^"]+)(?P<suffix>"\s*,?)',
        line_body,
    )
    if match is None or match.group("schema") != OLD_SCHEMA:
        raise ValueError(f"{path} does not have the expected top-level schema header")
    lines[1] = f"{match.group('prefix')}{NEW_SCHEMA}{match.group('suffix')}{line_ending}"
    path.write_text("".join(lines), encoding="utf-8")
    return True


def migrate(repository_root: Path, *, check_only: bool) -> tuple[int, int]:
    source_paths = _indexed_source_paths(repository_root)
    migrated = sum(_migrate_file(path, check_only=check_only) for path in source_paths)
    return migrated, len(source_paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify all active authored parity inputs already use schema @31",
    )
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        migrated, total = migrate(repository_root, check_only=args.check)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"parity input migration failed: {error}", file=sys.stderr)
        return 2
    if args.check:
        print(f"validated {total} authored parity inputs at schema @31")
    else:
        print(f"migrated {migrated} of {total} authored parity inputs to schema @31")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
