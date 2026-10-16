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


class _InputContainsUserDict(UserDict):
    """Use an input-defined type-level containment result for mapping probes."""

    def __init__(self, values: dict[str, Any], contains_result: bool) -> None:
        super().__init__(values)
        self._contains_result = contains_result

    def __contains__(self, _key: object) -> bool:
        return self._contains_result


class _InputAppRootPath(str):
    """Represent an input-defined str subclass for HTTPConnection.base_url."""

    def __new__(cls, spec: dict[str, Any]) -> _InputAppRootPath:
        instance = super().__new__(cls, spec["value"])
        instance._endswith = spec["endswith"]
        instance._iadd = spec["iadd"]
        return instance

    def endswith(self, suffix: Any, *args: Any) -> bool:
        if suffix == self._endswith["suffix"] and not args:
            return self._endswith["result"]
        return super().endswith(suffix, *args)

    def __iadd__(self, other: Any) -> Any:
        if other == self._iadd["operand"]:
            return self._iadd["result"]
        return super().__add__(other)


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
    if "class_contains_result" in mapping_spec:
        scope = _InputContainsUserDict(scope_values, mapping_spec["class_contains_result"])
    else:
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


def run_request_base_url_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Observe Request.base_url for an input-defined app_root_path subclass."""
    scope = dict(case["scope"])
    scope["server"] = tuple(scope["server"])
    scope["app_root_path"] = _InputAppRootPath(scope["app_root_path"])

    request = request_type(scope)
    observation = case["observations"][0]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": observation,
                "status": "ok",
                "value": {observation: str(request.base_url)},
            }
        ],
    }
