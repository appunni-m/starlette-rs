"""Migrate authored parity inputs from schema @50 to @51."""

from __future__ import annotations

import argparse
import json
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
    PREVIOUS_INPUT_SCHEMA,
    ContractError,
    load_json,
    load_manifest,
    migrate_input_document_v50,
    validate_input_document,
    validate_input_document_v51,
    validate_manifest,
    validate_previous_input_document,
)


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
        document = load_json(source)
        if not isinstance(document, dict):
            raise ContractError(f"{source} must contain an object")
        schema = document.get("schema")
        if schema == PREVIOUS_INPUT_SCHEMA:
            validate_previous_input_document(
                document,
                manifest,
                public_modules=public_modules,
            )
            migrated = migrate_input_document_v50(document)
            validate_input_document_v51(migrated, manifest, public_modules=public_modules)
            serialized = json.dumps(migrated, indent=2) + "\n"
            pending.append((source, serialized))
        elif schema == INPUT_SCHEMA:
            validate_input_document(document, manifest, public_modules=public_modules)
        else:
            raise ContractError(f"{source} uses unexpected schema {schema!r}")

    if check_only and pending:
        stale = [source.relative_to(root).as_posix() for source, _ in pending]
        raise ContractError(f"indexed authored inputs still use {PREVIOUS_INPUT_SCHEMA}: {stale}")
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
    print(f"{action} {migrated} of {total} authored parity inputs at schema @51")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
