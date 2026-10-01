"""Input-driven observations for Request's inherited scope-mapping interface."""

from __future__ import annotations

from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return str(value)


def run_request_scope_mapping_case(
    case: dict[str, Any],
    request_type: type[Any],
) -> dict[str, Any]:
    """Observe the mapping API using the exact scope supplied by the case."""
    request = request_type(case["scope"])
    value = {
        "keyed_method": _safe(request["method"]),
        "mapping": _safe(dict(request)),
        "iteration_order": _safe(list(request)),
        "length": len(request),
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "scope-mapping",
                "status": "ok",
                "value": {"scope-mapping": value},
            }
        ],
    }
