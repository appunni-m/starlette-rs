"""Input-driven TestClient adapter shared by the pinned oracle and package target."""

from __future__ import annotations

import base64
from typing import Any


def _decoded_pairs(value: list[list[str]]) -> list[tuple[bytes, bytes]]:
    return [(base64.b64decode(key), base64.b64decode(item)) for key, item in value]


def _message(value: dict[str, Any]) -> dict[str, Any]:
    message = dict(value)
    message.pop("headers_base64_pairs", None)
    message.pop("body_base64", None)
    if "headers_base64_pairs" in value:
        message["headers"] = _decoded_pairs(value["headers_base64_pairs"])
    if "body_base64" in value:
        message["body"] = base64.b64decode(value["body_base64"])
    return message


def _safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def run_testclient_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.testclient import TestClient

    settings = case["testclient"]
    request_input = case["request"]
    app_input = case["asgi_app"]
    scope_observations: list[dict[str, Any]] = []
    receive_observations: list[dict[str, Any]] = []

    def record_scope(scope: dict[str, Any]) -> None:
        scope_observations.append(
            {field: _safe(scope[field]) for field in app_input["scope_fields"]}
        )

    async def run_app_body(receive: Any, send: Any) -> None:
        for _ in range(app_input["receive_count"]):
            message = await receive()
            receive_observations.append(_safe(message))
        for message in app_input["messages"]:
            await send(_message(message))

    if app_input["kind"] == "asgi2":

        def app(scope: dict[str, Any]) -> Any:
            record_scope(scope)

            async def instance(receive: Any, send: Any) -> None:
                await run_app_body(receive, send)

            return instance

    else:

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            await run_app_body(receive, send)

    client = TestClient(
        app,
        base_url=settings["base_url"],
        raise_server_exceptions=settings["raise_server_exceptions"],
        root_path=settings["root_path"],
        client=tuple(settings["client"]),
        headers=dict(settings["headers"]),
    )
    response = client.request(
        request_input["method"],
        request_input["url"],
        content=base64.b64decode(request_input["body_base64"]),
        headers=_decoded_pairs(request_input["headers_base64_pairs"]),
    )
    result = {
        "scope": scope_observations,
        "receive_messages": receive_observations,
        "response": {
            "status_code": response.status_code,
            "headers": response.headers.multi_items(),
            "body_base64": base64.b64encode(response.content).decode("ascii"),
            "extensions": _safe(response.extensions),
            "template": _safe(getattr(response, "template", None)),
            "context": _safe(getattr(response, "context", None)),
        },
    }
    client.close()
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "request-response", "status": "ok", "value": result}],
    }
