"""Input-driven observations for Request's connection properties."""

from __future__ import annotations

from collections import UserDict
from collections.abc import Callable
from typing import Any

from .request_scope_mapping import _safe


def run_request_connection_properties_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Read the selected Request properties from the supplied scope mapping."""
    mapping_spec = case["scope_mapping"]
    scope = UserDict(case["scope"])
    contains_result = mapping_spec["instance_contains_result"]
    scope.__contains__ = lambda _key: contains_result

    request = request_type(scope)
    property_values = [
        {"name": name, "value": _safe(getattr(request, name))}
        for name in case["properties"]
    ]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "connection-properties",
                "status": "ok",
                "value": {"connection-properties": property_values},
            }
        ],
    }
