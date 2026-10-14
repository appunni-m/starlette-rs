"""Input-driven observations for Request.cookies cache and mapping behavior."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any


def _decode_headers(pairs: list[list[str]]) -> list[tuple[bytes, bytes]]:
    return [
        (base64.b64decode(name, validate=True), base64.b64decode(value, validate=True))
        for name, value in pairs
    ]


def _items(value: dict[str, str]) -> list[list[str]]:
    return [[key, item] for key, item in value.items()]


def _observe(case: dict[str, Any], request_type: Callable[..., Any]) -> dict[str, Any]:
    scope = dict(case["scope"])
    scope["headers"] = _decode_headers(scope.pop("headers_base64_pairs"))
    request = request_type(scope)
    initial_cookies: dict[str, str] | None = None
    observations: list[dict[str, Any]] = []

    for action in case["actions"]:
        operation = action["operation"]
        if operation == "read-cookies":
            cookies = request.cookies
            if initial_cookies is None:
                initial_cookies = cookies
            observations.append(
                {
                    "operation": operation,
                    "is_builtin_dict": type(cookies) is dict,
                    "same_object_as_first_read": cookies is initial_cookies,
                    "items": _items(cookies),
                }
            )
        elif operation == "mutate-headers-in-place":
            request.scope["headers"][:] = _decode_headers(action["headers_base64_pairs"])
            observations.append({"operation": operation, "status": "ok"})
        elif operation == "replace-headers":
            request.scope["headers"] = _decode_headers(action["headers_base64_pairs"])
            observations.append({"operation": operation, "status": "ok"})
        elif operation == "set-cookie":
            request.cookies[action["key"]] = action["value"]
            observations.append({"operation": operation, "status": "ok"})
        elif operation == "delete-cookie":
            del request.cookies[action["key"]]
            observations.append({"operation": operation, "status": "ok"})
        else:
            raise ValueError(f"unsupported Request.cookies action: {operation!r}")

    return {"actions": observations}


def run_request_cookie_cache_sequence_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Run cookie reads and input-defined mutations through public Request."""
    if case.get("surface") != "starlette.requests.Request" or case.get("operation") != (
        "cookie-cache-sequence"
    ):
        raise ValueError("Request.cookies input selects another surface or operation")
    if case.get("assets") != [] or case.get("observations") != ["cookie-cache-sequence"]:
        raise ValueError("Request.cookies input selects unsupported assets or observations")
    if not isinstance(case.get("target_profiles"), list) or any(
        not isinstance(profile, str) for profile in case["target_profiles"]
    ):
        raise ValueError("Request.cookies target_profiles must be strings")
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "cookie-cache-sequence",
                "status": "ok",
                "value": {
                    "cookie-cache-sequence": _observe(case, request_type),
                },
            }
        ],
    }
