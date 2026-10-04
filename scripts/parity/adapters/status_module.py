"""Shared input-only workflow for the public ``starlette.status`` module."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any


def _deprecated_values(status: Any, names: list[str]) -> list[dict[str, Any]]:
    return [{"name": name, "value": getattr(status, name)} for name in names]


def run_status_module_sequence(
    case: dict[str, Any],
    strict_object: Callable[[dict[str, Any], set[str], str], None],
    json_safe: Callable[[Any], Any],
) -> dict[str, Any]:
    """Run identical public calls from this shared consumer call site."""
    strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "public_names",
            "deprecated_names",
            "missing_names",
            "observe_directory",
            "observations",
        },
        "status module-symbol-sequence case",
    )
    from starlette import status

    public_names = list(status.__all__)
    public_values = {name: getattr(status, name) for name in case["public_names"]}
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        deprecated_values = _deprecated_values(status, case["deprecated_names"])
    missing_attributes = []
    for name in case["missing_names"]:
        try:
            value = getattr(status, name)
        except AttributeError as exc:
            missing_attributes.append(
                {
                    "name": name,
                    "outcome": "attribute-error",
                    "message": str(exc),
                }
            )
        else:
            missing_attributes.append({"name": name, "outcome": "value", "value": json_safe(value)})
    values = {
        "public_names": public_names,
        "public_values": public_values,
        "deprecated_values_and_warnings": {
            "values": deprecated_values,
            "warnings": [
                {
                    "category": f"{item.category.__module__}.{item.category.__qualname__}",
                    "message": str(item.message),
                    "filename": item.filename,
                    "lineno": item.lineno,
                }
                for item in recorded
            ],
        },
        "directory": dir(status) if case["observe_directory"] else None,
        "missing_attribute": missing_attributes,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": values}
            for selector in case["observations"]
        ],
    }
