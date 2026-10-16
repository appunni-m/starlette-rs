"""Migrate authored parity inputs from schema @62 to @63."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from scripts.migrate_parity_input_v49_to_v50 import (
    MANIFEST_PATH,
    _authored_sources,
    _indexed_sources,
)
from scripts.parity.api_sources import load_api_metadata, public_module_names
from scripts.parity.contract import (
    INPUT_SCHEMA,
    INPUT_SCHEMA_V62,
    INPUT_SCHEMA_V63,
    ContractError,
    load_json,
    load_manifest,
    migrate_input_document_v62,
    validate_input_document,
    validate_input_document_v62,
    validate_input_document_v63,
    validate_manifest,
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
    if match is None or match.group("schema") != INPUT_SCHEMA_V62:
        raise ContractError(f"{source} does not have the expected top-level schema header")
    lines[1] = f"{match['prefix']}{INPUT_SCHEMA_V63}{match['suffix']}{ending}"
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
        if schema == INPUT_SCHEMA_V62:
            validate_input_document_v62(document, manifest, public_modules=public_modules)
            migrated = migrate_input_document_v62(document)
            validate_input_document_v63(migrated, manifest, public_modules=public_modules)
            pending.append((source, _replace_schema_header(raw, source)))
        elif schema == INPUT_SCHEMA_V63:
            validate_input_document_v63(document, manifest, public_modules=public_modules)
        elif schema == INPUT_SCHEMA:
            validate_input_document(document, manifest, public_modules=public_modules)
        else:
            raise ContractError(f"{source} uses unexpected schema {schema!r}")

    if check_only and pending:
        stale = [source.relative_to(root).as_posix() for source, _ in pending]
        raise ContractError(f"indexed authored inputs still use {INPUT_SCHEMA_V62}: {stale}")
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
    print(f"{action} {migrated} of {total} authored parity inputs at schema @63")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
