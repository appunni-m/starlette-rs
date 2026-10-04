"""Migrate authored parity inputs from schema @36 to @37."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

OLD_SCHEMA = "migration-parity/parity-input@36"
NEW_SCHEMA = "migration-parity/parity-input@37"
MANIFEST_PATH = Path("tests/fixtures/manifest.yaml")


def _indexed_sources(root: Path) -> list[Path]:
    manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    generated_paths = manifest["input_index"]["parity"]
    if not isinstance(generated_paths, list) or not generated_paths:
        raise ValueError("manifest input_index.parity must be a non-empty array")
    paths = []
    for generated_path in generated_paths:
        relative = PurePosixPath(generated_path)
        if (
            len(relative.parts) != 5
            or relative.parts[:4] != ("build", "parity", "inputs", "parity")
            or relative.suffix != ".json"
        ):
            raise ValueError(f"unsupported generated parity input path: {generated_path!r}")
        paths.append(root / "tests/fixtures/sources/parity" / f"{relative.stem}.yaml")
    if len(paths) != len(set(paths)):
        raise ValueError("manifest input_index.parity contains duplicate sources")
    return paths


def _migrate(path: Path, check_only: bool) -> bool:
    raw = path.read_text(encoding="utf-8")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain an object")
    if document.get("schema") == NEW_SCHEMA:
        return False
    if document.get("schema") != OLD_SCHEMA:
        raise ValueError(f"{path} uses unexpected schema {document.get('schema')!r}")
    if check_only:
        raise ValueError(f"{path} still uses {OLD_SCHEMA}")
    lines = raw.splitlines(keepends=True)
    if len(lines) < 2:
        raise ValueError(f"{path} has no top-level schema header")
    body = lines[1].rstrip("\r\n")
    ending = lines[1][len(body) :]
    match = re.fullmatch(
        r'(?P<prefix>\s*"schema"\s*:\s*")(?P<schema>[^"]+)(?P<suffix>"\s*,?)', body
    )
    if match is None or match.group("schema") != OLD_SCHEMA:
        raise ValueError(f"{path} does not have the expected top-level schema header")
    lines[1] = f"{match.group('prefix')}{NEW_SCHEMA}{match.group('suffix')}{ending}"
    path.write_text("".join(lines), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        sources = _indexed_sources(root)
        migrated = sum(_migrate(path, args.check) for path in sources)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"parity input migration failed: {error}", file=sys.stderr)
        return 2
    action = "validated" if args.check else "migrated"
    print(f"{action} {migrated} of {len(sources)} authored parity inputs at schema @37")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
