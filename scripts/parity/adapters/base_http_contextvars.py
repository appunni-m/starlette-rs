"""Input-driven ContextVar observations for BaseHTTPMiddleware parity."""

from __future__ import annotations

import asyncio
import base64
import contextvars
from typing import Any

SURFACE = "starlette.middleware.base.BaseHTTPMiddleware"
OPERATION = "contextvars-propagation"


def _scope_from_input(value: dict[str, Any]) -> dict[str, Any]:
    scope = {
        key: item
        for key, item in value.items()
        if key not in {"raw_path_base64", "query_string_base64", "headers_base64_pairs"}
    }
    scope["raw_path"] = base64.b64decode(value["raw_path_base64"], validate=True)
    scope["query_string"] = base64.b64decode(value["query_string_base64"], validate=True)
    scope["headers"] = [
        (
            base64.b64decode(name, validate=True),
            base64.b64decode(header_value, validate=True),
        )
        for name, header_value in value["headers_base64_pairs"]
    ]
    scope["client"] = tuple(scope["client"])
    scope["server"] = tuple(scope["server"])
    return scope


def _receive_messages(case: dict[str, Any]) -> Any:
    messages = case["request"]["receive"]
    decoded = [
        {
            **{key: value for key, value in message.items() if key != "body_base64"},
            **(
                {"body": base64.b64decode(message["body_base64"], validate=True)}
                if "body_base64" in message
                else {}
            ),
        }
        for message in messages
    ]
    index = 0
    after_messages = case["request"]["receive_after_messages"]

    async def receive() -> dict[str, Any]:
        nonlocal index
        if index < len(decoded):
            message = decoded[index]
            index += 1
            return message
        return dict(after_messages)

    return receive


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


async def _run(case: dict[str, Any]) -> dict[str, Any]:
    context_input = case["context"]
    request_input = case["request"]
    response_input = case["response"]
    context_var: contextvars.ContextVar[str] = contextvars.ContextVar(
        context_input["name"], default=context_input["default_value"]
    )
    context_var.set(context_input["initial_value"])
    observed: dict[str, Any] = {"caller_before": context_var.get()}
    events: list[dict[str, Any]] = []
    receive = _receive_messages(case)

    async def endpoint(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observed["endpoint_before"] = context_var.get()
        context_var.set(context_input["endpoint_value"])
        observed["endpoint_after"] = context_var.get()
        await send(
            {
                "type": "http.response.start",
                "status": response_input["status"],
                "headers": [
                    (
                        base64.b64decode(name, validate=True),
                        base64.b64decode(value, validate=True),
                    )
                    for name, value in response_input["headers_base64_pairs"]
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": base64.b64decode(response_input["body_base64"], validate=True),
                "more_body": False,
            }
        )

    async def record_send(message: dict[str, Any]) -> None:
        events.append(_json_safe(message))

    async def middleware(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observed["middleware_before_set"] = context_var.get()
        context_var.set(context_input["middleware_value"])
        observed["middleware_after_set"] = context_var.get()
        await endpoint(scope, receive, send)
        observed["middleware_after_downstream"] = context_var.get()

    kind = case["middleware_kind"]
    if kind == "base-http":
        from starlette.middleware.base import BaseHTTPMiddleware

        async def dispatch(request: Any, call_next: Any) -> Any:
            observed["middleware_before_set"] = context_var.get()
            context_var.set(context_input["middleware_value"])
            observed["middleware_after_set"] = context_var.get()
            response = await call_next(request)
            observed["middleware_after_downstream"] = context_var.get()
            return response

        app = BaseHTTPMiddleware(endpoint, dispatch=dispatch)
    elif kind == "pure-asgi":
        app = middleware
    else:
        raise ValueError(f"unsupported ContextVar middleware kind: {kind!r}")

    scope = _scope_from_input(request_input["scope"])
    observed["caller_before"] = context_var.get()
    await app(scope, receive, record_send)
    observed["caller_after"] = context_var.get()
    return {
        "context_values": observed,
        "asgi_events": events,
    }


def run_base_http_contextvars_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["surface"] != SURFACE or case["operation"] != OPERATION:
        raise ValueError("case is outside the BaseHTTPMiddleware ContextVar operation")
    value = asyncio.run(_run(case))
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": OPERATION,
                "status": "ok",
                "value": value,
            }
        ],
    }
