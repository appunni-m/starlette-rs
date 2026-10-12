"""Input-driven Request header, cookie, and push-promise cache observations."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import Any


def _exact_object(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        actual = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise ValueError(f"{context} fields differ: expected {sorted(fields)!r}, got {actual!r}")
    return value


def _decode_scope(spec: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        spec,
        {
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
            "extensions",
        },
        "Request header-cache scope",
    )
    scope = {
        key: value
        for key, value in spec.items()
        if key not in {"headers_base64_pairs", "raw_path_base64", "query_string_base64"}
    }
    scope["raw_path"] = base64.b64decode(spec["raw_path_base64"], validate=True)
    scope["query_string"] = base64.b64decode(spec["query_string_base64"], validate=True)
    scope["headers"] = [
        (
            base64.b64decode(name, validate=True),
            base64.b64decode(value, validate=True),
        )
        for name, value in spec["headers_base64_pairs"]
    ]
    if "client" in spec:
        scope["client"] = tuple(spec["client"])
    if "server" in spec:
        scope["server"] = tuple(spec["server"])
    return scope


def _push_event(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": message["type"],
        "path": message["path"],
        "headers_base64_pairs": [
            [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
            for name, value in message["headers"]
        ],
    }


async def _observe(case: dict[str, Any], request_type: Callable[..., Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "replacement_scope",
            "actions",
            "observations",
        },
        "Request header-cache sequence case",
    )
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, str]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    request = request_type(_decode_scope(case["scope"]), receive=receive, send=send)
    replacement_scope = _decode_scope(case["replacement_scope"])
    actions: list[dict[str, Any]] = []

    for action in case["actions"]:
        operation = action.get("operation")
        if operation == "read-headers":
            _exact_object(action, {"operation", "names"}, "read-headers action")
            names = action["names"]
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                raise ValueError("read-headers names must be a list of strings")
            values = {name: request.headers.getlist(name) for name in names}
            actions.append({"operation": operation, "status": "ok", "value": values})
        elif operation == "replace-scope":
            _exact_object(action, {"operation"}, "replace-scope action")
            request.scope = replacement_scope
            actions.append({"operation": operation, "status": "ok"})
        elif operation == "read-cookies":
            _exact_object(action, {"operation"}, "read-cookies action")
            actions.append(
                {
                    "operation": operation,
                    "status": "ok",
                    "value": [[key, value] for key, value in request.cookies.items()],
                }
            )
        elif operation == "send-push-promise":
            _exact_object(action, {"operation", "path"}, "send-push-promise action")
            if not isinstance(action["path"], str):
                raise ValueError("send-push-promise path must be a string")
            previous_count = len(sent)
            await request.send_push_promise(action["path"])
            actions.append(
                {
                    "operation": operation,
                    "status": "ok",
                    "value": [_push_event(message) for message in sent[previous_count:]],
                }
            )
        else:
            raise ValueError(f"unsupported Request header-cache action: {operation!r}")

    return {"actions": actions}


def run_request_header_cache_sequence_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Run the scope replacement sequence through the supplied public Request."""
    if case.get("surface") != "starlette.requests.Request" or case.get("operation") != (
        "header-cache-sequence"
    ):
        raise ValueError("Request header-cache input selects another surface or operation")
    if case.get("assets") != [] or case.get("observations") != ["header-cache-sequence"]:
        raise ValueError("Request header-cache input selects unsupported assets or observations")
    if not isinstance(case.get("target_profiles"), list) or any(
        not isinstance(profile, str) for profile in case["target_profiles"]
    ):
        raise ValueError("Request header-cache target_profiles must be strings")
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "header-cache-sequence",
                "status": "ok",
                "value": {"header-cache-sequence": asyncio.run(_observe(case, request_type))},
            }
        ],
    }
