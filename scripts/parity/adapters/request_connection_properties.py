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
    property_values = []
    for name in case["properties"]:
        try:
            value = getattr(request, name)
        except Exception as error:
            error_type = type(error)
            property_values.append(
                {
                    "name": name,
                    "outcome": "error",
                    "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
                    "message": str(error),
                }
            )
        else:
            property_values.append({"name": name, "value": _safe(value)})
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
