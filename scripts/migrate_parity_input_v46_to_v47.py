"""Migrate authored parity inputs from schema @46 to @47."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath

from scripts.parity.api_sources import load_api_metadata, public_module_names
from scripts.parity.contract import (
    INPUT_SCHEMA_V46,
    INPUT_SCHEMA_V47,
    ContractError,
    load_json,
    load_manifest,
    validate_input_document_v46,
    validate_input_document_v47,
    validate_manifest,
)

MANIFEST_PATH = Path("tests/fixtures/manifest.yaml")


def _indexed_sources(root: Path, manifest: dict[str, object]) -> list[Path]:
    input_index = manifest.get("input_index")
    if not isinstance(input_index, dict):
        raise ContractError("manifest input_index must be an object")
    generated_paths = input_index.get("parity")
    if not isinstance(generated_paths, list) or not generated_paths:
        raise ContractError("manifest input_index.parity must be a non-empty array")
    paths: list[Path] = []
    for generated_path in generated_paths:
        if not isinstance(generated_path, str):
            raise ContractError("manifest input_index.parity entries must be strings")
        relative = PurePosixPath(generated_path)
        if (
            len(relative.parts) != 5
            or relative.parts[:4] != ("build", "parity", "inputs", "parity")
            or relative.suffix != ".json"
            or relative.name != f"{relative.stem}.json"
        ):
            raise ContractError(f"unsupported generated parity input path: {generated_path!r}")
        source_root = root / "tests/fixtures/sources/parity"
        candidates = [source_root / f"{relative.stem}{suffix}" for suffix in (".yaml", ".yml")]
        existing = [source for source in candidates if source.is_file()]
        if len(existing) > 1:
            raise ContractError(
                f"multiple authored YAML sources map to {generated_path!r}: "
                f"{', '.join(source.name for source in existing)}; keep exactly one"
            )
        paths.append(existing[0] if existing else candidates[0])
    if len(paths) != len(set(paths)):
        raise ContractError("manifest input_index.parity contains duplicate sources")
    return paths


def _authored_sources(root: Path) -> list[Path]:
    source_root = root / "tests/fixtures/sources/parity"
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )


def _replace_schema_header(raw: str, source: Path) -> str:
    lines = raw.splitlines(keepends=True)
    if len(lines) < 2:
        raise ContractError(f"{source} has no top-level schema header")
    body = lines[1].rstrip("\r\n")
    ending = lines[1][len(body) :]
    match = re.fullmatch(
        r'(?P<prefix>\s*"schema"\s*:\s*")(?P<schema>[^"]+)(?P<suffix>"\s*,?)',
        body,
    )
    if match is None or match.group("schema") != INPUT_SCHEMA_V46:
        raise ContractError(f"{source} does not have the expected top-level schema header")
    lines[1] = f"{match.group('prefix')}{INPUT_SCHEMA_V47}{match.group('suffix')}{ending}"
    return "".join(lines)


def migrate(root: Path, *, check_only: bool) -> tuple[int, int]:
    manifest = load_manifest(root / MANIFEST_PATH)
    validate_manifest(manifest)
    public_modules = public_module_names(load_api_metadata(root))
    indexed_sources = _indexed_sources(root, manifest)
    sources = _authored_sources(root)
    if set(indexed_sources) != set(sources):
        unindexed = sorted(
            source.relative_to(root).as_posix() for source in set(sources) - set(indexed_sources)
        )
        missing = sorted(
            source.relative_to(root).as_posix() for source in set(indexed_sources) - set(sources)
        )
        raise ContractError(
            "manifest parity index must cover every authored parity YAML file; "
            f"unindexed={unindexed}, missing={missing}"
        )
    pending: list[tuple[Path, str]] = []

    for source in sources:
        raw = source.read_text(encoding="utf-8")
        document = load_json(source)
        if not isinstance(document, dict):
            raise ContractError(f"{source} must contain an object")
        schema = document.get("schema")
        if schema == INPUT_SCHEMA_V46:
            validate_input_document_v46(
                document,
                manifest,
                public_modules=public_modules,
            )
            migrated = dict(document)
            migrated["schema"] = INPUT_SCHEMA_V47
            validate_input_document_v47(migrated, manifest, public_modules=public_modules)
            pending.append((source, _replace_schema_header(raw, source)))
        elif schema == INPUT_SCHEMA_V47:
            validate_input_document_v47(document, manifest, public_modules=public_modules)
        else:
            raise ContractError(f"{source} uses unexpected schema {schema!r}")

    if check_only and pending:
        stale = [source.relative_to(root).as_posix() for source, _ in pending]
        raise ContractError(f"indexed authored inputs still use {INPUT_SCHEMA_V46}: {stale}")
    for source, updated in pending:
        source.write_text(updated, encoding="utf-8")
    return len(pending), len(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        migrated, total = migrate(root, check_only=args.check)
    except (ContractError, OSError, UnicodeError, TypeError, ValueError) as error:
        print(f"parity input migration failed: {error}", file=sys.stderr)
        return 2
    action = "validated" if args.check else "migrated"
    print(f"{action} {migrated} of {total} authored parity inputs at schema @47")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
