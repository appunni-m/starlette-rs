"""Load and apply the pinned public API source catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contract import ORACLE_COMMIT, ContractError, load_json

METADATA_RELATIVE = Path("metadata.yaml")
METADATA_SCHEMA = "starlette-rs/api-source-metadata@1"


def load_api_metadata(root: Path, path: Path | None = None) -> dict[str, Any]:
    metadata = load_json(path or (root / METADATA_RELATIVE))
    if not isinstance(metadata, dict) or set(metadata) != {
        "schema",
        "authority",
        "api_inventory",
        "api_sources",
    }:
        raise ContractError(
            "metadata.yaml must contain only schema, authority, api_inventory, and api_sources"
        )
    if metadata["schema"] != METADATA_SCHEMA:
        raise ContractError(f"unsupported API source metadata schema: {metadata['schema']!r}")
    authority = metadata["authority"]
    if not isinstance(authority, dict) or set(authority) != {
        "name",
        "version",
        "revision",
        "package_path",
    }:
        raise ContractError("metadata.yaml authority has an invalid shape")
    if (
        authority["name"] != "Starlette"
        or authority["version"] != "1.6.0"
        or authority["revision"] != ORACLE_COMMIT
        or authority["package_path"] != "starlette"
    ):
        raise ContractError("metadata.yaml authority differs from pinned Starlette 1.6.0")
    inventory = metadata["api_inventory"]
    if not isinstance(inventory, dict) or set(inventory) != {
        "package_path",
        "public_source_files",
        "documentation_root",
        "test_source_root",
    }:
        raise ContractError("metadata.yaml api_inventory has an invalid shape")
    if inventory["package_path"] != authority["package_path"]:
        raise ContractError("metadata.yaml API package path differs from its authority")
    module_paths = inventory["public_source_files"]
    if not isinstance(module_paths, list) or not module_paths:
        raise ContractError("metadata.yaml public_source_files must be a non-empty array")
    if any(
        not isinstance(path, str)
        or not path.startswith(f"{inventory['package_path']}/")
        or not path.endswith(".py")
        or ".." in Path(path).parts
        for path in module_paths
    ):
        raise ContractError("metadata.yaml public_source_files contains an invalid path")
    if len(module_paths) != len(set(module_paths)):
        raise ContractError("metadata.yaml public_source_files contains duplicates")
    for root_name in ("documentation_root", "test_source_root"):
        source_root = inventory[root_name]
        if (
            not isinstance(source_root, str)
            or not source_root
            or Path(source_root).is_absolute()
            or ".." in Path(source_root).parts
        ):
            raise ContractError(f"metadata.yaml api_inventory.{root_name} is invalid")
    sources = metadata["api_sources"]
    if not isinstance(sources, list) or not sources:
        raise ContractError("metadata.yaml api_sources must be a non-empty array")
    seen_surfaces: set[str] = set()
    public_source_files = set(module_paths)
    for source_index, source in enumerate(sources):
        context = f"metadata.yaml api_sources[{source_index}]"
        if not isinstance(source, dict) or set(source) != {
            "surface_id",
            "source_path",
            "operations",
        }:
            raise ContractError(f"{context} has an invalid shape")
        surface_id = source["surface_id"]
        source_path = source["source_path"]
        if not isinstance(surface_id, str) or not surface_id.startswith("starlette."):
            raise ContractError(f"{context}.surface_id must be a qualified Starlette name")
        if not isinstance(source_path, str) or not source_path.startswith("starlette/"):
            raise ContractError(f"{context}.source_path must be repository-relative")
        source_file = source_path.split(":", 1)[0]
        if source_file not in public_source_files:
            raise ContractError(
                f"{context}.source_path is absent from api_inventory.public_source_files"
            )
        if surface_id in seen_surfaces:
            raise ContractError(f"duplicate API source surface {surface_id!r}")
        seen_surfaces.add(surface_id)
        operations = source["operations"]
        if not isinstance(operations, list) or not operations:
            raise ContractError(f"{context}.operations must be a non-empty array")
        seen_operations: set[str] = set()
        for operation_index, operation in enumerate(operations):
            operation_context = f"{context}.operations[{operation_index}]"
            if not isinstance(operation, dict) or set(operation) != {"operation_id", "source_path"}:
                raise ContractError(f"{operation_context} has an invalid shape")
            operation_id = operation["operation_id"]
            operation_path = operation["source_path"]
            if not isinstance(operation_id, str) or not operation_id:
                raise ContractError(f"{operation_context}.operation_id must be non-empty")
            if not isinstance(operation_path, str) or not operation_path.startswith("starlette."):
                raise ContractError(f"{operation_context}.source_path must be qualified")
            if operation_id in seen_operations:
                raise ContractError(f"duplicate API source operation {surface_id}.{operation_id}")
            seen_operations.add(operation_id)
    return metadata


def _source_maps(metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["surface_id"]: source for source in metadata["api_sources"]}


def apply_api_sources(manifest: dict[str, Any], metadata: dict[str, Any]) -> bool:
    """Apply catalog source references to the active manifest; return whether it changed."""
    sources = _source_maps(metadata)
    surfaces = {surface["id"]: surface for surface in manifest.get("surfaces", [])}
    if set(surfaces) != set(sources):
        raise ContractError(
            "metadata.yaml API surface IDs differ from the active manifest: "
            f"metadata-only={sorted(set(sources) - set(surfaces))}, "
            f"manifest-only={sorted(set(surfaces) - set(sources))}"
        )
    changed = False
    for surface_id, surface in surfaces.items():
        source = sources[surface_id]
        if surface.get("source_path") != source["source_path"]:
            surface["source_path"] = source["source_path"]
            changed = True
        operations = {operation["id"]: operation for operation in surface.get("operations", [])}
        metadata_operations = {
            operation["operation_id"]: operation["source_path"]
            for operation in source["operations"]
        }
        if set(operations) != set(metadata_operations):
            raise ContractError(
                f"metadata.yaml operation IDs differ for {surface_id}: "
                f"metadata-only={sorted(set(metadata_operations) - set(operations))}, "
                f"manifest-only={sorted(set(operations) - set(metadata_operations))}"
            )
        for operation_id, operation in operations.items():
            operation_source = operation.get("source")
            if not isinstance(operation_source, dict):
                raise ContractError(f"manifest operation {surface_id}.{operation_id} has no source")
            source_path = metadata_operations[operation_id]
            if operation_source.get("path") != source_path:
                operation_source["path"] = source_path
                changed = True
    return changed


def validate_api_sources(manifest: dict[str, Any], metadata: dict[str, Any]) -> int:
    """Check the active manifest's references against metadata.yaml without mutation."""
    candidate = {
        **manifest,
        "surfaces": [
            {
                **surface,
                "operations": [
                    {**operation, "source": dict(operation["source"])}
                    for operation in surface["operations"]
                ],
            }
            for surface in manifest["surfaces"]
        ],
    }
    apply_api_sources(candidate, metadata)
    for actual_surface, expected_surface in zip(
        manifest["surfaces"], candidate["surfaces"], strict=True
    ):
        if actual_surface["source_path"] != expected_surface["source_path"]:
            raise ContractError(
                f"manifest API source for {actual_surface['id']} differs from metadata.yaml"
            )
        for actual_operation, expected_operation in zip(
            actual_surface["operations"], expected_surface["operations"], strict=True
        ):
            if actual_operation["source"]["path"] != expected_operation["source"]["path"]:
                raise ContractError(
                    "manifest API source for "
                    f"{actual_surface['id']}.{actual_operation['id']} differs from metadata.yaml"
                )
    return len(metadata["api_sources"])
