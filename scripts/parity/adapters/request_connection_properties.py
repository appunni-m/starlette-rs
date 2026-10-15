"""Input-driven observations for Request's connection properties."""

from __future__ import annotations

import base64
from collections import UserDict
from collections.abc import Callable
from typing import Any

from .request_scope_mapping import _safe


class _InputQueryStringBytes(bytes):
    """Represent an input-defined bytes subclass with explicit truthiness."""

    def __new__(cls, value: bytes, truthy: bool) -> _InputQueryStringBytes:
        instance = super().__new__(cls, value)
        instance._truthy = truthy
        return instance

    def __bool__(self) -> bool:
        return self._truthy


def run_request_connection_properties_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Read the selected Request properties from the supplied scope mapping."""
    mapping_spec = case["scope_mapping"]
    scope_values = dict(case["scope"])
    query_string = scope_values.get("query_string")
    if isinstance(query_string, dict) and query_string.get("kind") == "bytes-subclass":
        scope_values["query_string"] = _InputQueryStringBytes(
            base64.b64decode(query_string["value_base64"], validate=True),
            query_string["truthy"],
        )
    scope = UserDict(scope_values)
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
