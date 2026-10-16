#!/usr/bin/env python3
"""Normalize local Cargo identities in a generated CycloneDX SBOM."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _components(document: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    pending = [document.get("metadata", {}).get("component", {})]
    pending.extend(document.get("components", []))
    while pending:
        component = pending.pop()
        if not isinstance(component, dict):
            continue
        components.append(component)
        children = component.get("components", [])
        if isinstance(children, list):
            pending.extend(children)
    return components


def _canonical_purl(purl: str) -> str:
    base, marker, fragment = purl.partition("#")
    path, query_marker, query = base.partition("?")
    if not query_marker:
        return purl
    retained = [item for item in query.split("&") if not item.startswith("download_url=file://")]
    if not retained:
        base = path
    else:
        base = f"{path}?{'&'.join(retained)}"
    return f"{base}#{fragment}" if marker else base


def _rewrite_references(value: Any, mapping: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "ref" and isinstance(child, str):
                value[key] = mapping.get(child, child)
            elif key == "dependsOn" and isinstance(child, list):
                value[key] = [mapping.get(ref, ref) for ref in child]
            else:
                _rewrite_references(child, mapping)
    elif isinstance(value, list):
        for child in value:
            _rewrite_references(child, mapping)


def _validate_graph(document: dict[str, Any]) -> None:
    refs = {
        component["bom-ref"]
        for component in _components(document)
        if isinstance(component.get("bom-ref"), str)
    }
    dependencies = document.get("dependencies", [])
    dangling = {
        ref
        for entry in dependencies
        if isinstance(entry, dict)
        for ref in [entry.get("ref"), *entry.get("dependsOn", [])]
        if isinstance(ref, str) and ref not in refs
    }
    if dangling:
        raise ValueError(f"SBOM dependency graph has unresolved references: {sorted(dangling)}")


def normalize(source: Path, destination: Path, timestamp: str) -> int:
    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed_timestamp.tzinfo is None:
        raise ValueError("timestamp must include a timezone, for example 2026-01-01T00:00:00Z")

    document = json.loads(source.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for component in _components(document):
        old_ref = component.get("bom-ref")
        old_purl = component.get("purl")
        if not isinstance(old_ref, str) or not isinstance(old_purl, str):
            continue
        new_purl = _canonical_purl(old_purl)
        if old_ref.startswith("path+file://") or old_purl != new_purl:
            if "file://" in new_purl:
                raise ValueError(f"could not normalize local PURL: {old_purl}")
            if new_purl in mapping.values() and mapping.get(old_ref) != new_purl:
                raise ValueError(
                    f"normalization produced a duplicate component identity: {new_purl}"
                )
            mapping[old_ref] = new_purl
            component["bom-ref"] = new_purl
            component["purl"] = new_purl

    if not mapping:
        raise ValueError("input SBOM contains no local Cargo identities to normalize")

    _rewrite_references(document.get("dependencies", []), mapping)
    metadata = document.get("metadata", {})
    if isinstance(metadata, dict):
        metadata["timestamp"] = timestamp

    document.pop("serialNumber", None)
    identity = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    serial = uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha256(identity.encode()).hexdigest())
    document["serialNumber"] = f"urn:uuid:{serial}"

    for component in _components(document):
        ref = component.get("bom-ref")
        purl = component.get("purl")
        if isinstance(ref, str) and ref.startswith("path+file://"):
            raise ValueError(f"local component reference remains: {ref}")
        if isinstance(purl, str) and "download_url=file://" in purl:
            raise ValueError(f"local component PURL remains: {purl}")
    _validate_graph(document)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(mapping)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="raw CycloneDX JSON")
    parser.add_argument("--output", required=True, type=Path, help="normalized CycloneDX JSON")
    parser.add_argument(
        "--timestamp",
        required=True,
        help="stable timezone-aware RFC 3339 timestamp recorded in the SBOM",
    )
    arguments = parser.parse_args()
    try:
        count = normalize(arguments.input, arguments.output, arguments.timestamp)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SBOM normalization failed: {exc}", file=sys.stderr)
        return 1
    print(f"normalized {count} local Cargo identities in {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
