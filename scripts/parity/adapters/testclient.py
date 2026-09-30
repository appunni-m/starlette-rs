"""Input-driven TestClient adapter shared by the pinned oracle and package target."""

from __future__ import annotations

import asyncio
import base64
import builtins
import warnings
from typing import Any


def _decoded_pairs(value: list[list[str]]) -> list[tuple[bytes, bytes]]:
    return [(base64.b64decode(key), base64.b64decode(item)) for key, item in value]


def _message(value: dict[str, Any]) -> dict[str, Any]:
    message = dict(value)
    message.pop("headers_base64_pairs", None)
    message.pop("body_base64", None)
    message.pop("bytes_base64", None)
    if "headers_base64_pairs" in value:
        message["headers"] = _decoded_pairs(value["headers_base64_pairs"])
    if "body_base64" in value:
        message["body"] = base64.b64decode(value["body_base64"])
    if "bytes_base64" in value:
        message["bytes"] = base64.b64decode(value["bytes_base64"])
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
    request_kwargs = {
        "content": base64.b64decode(request_input["body_base64"]),
        "headers": _decoded_pairs(request_input["headers_base64_pairs"]),
    }
    if "timeout" in request_input:
        request_kwargs["timeout"] = request_input["timeout"]
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        response = client.request(request_input["method"], request_input["url"], **request_kwargs)
    deprecation_warnings = [
        {
            "category": f"{item.category.__module__}.{item.category.__qualname__}",
            "message": str(item.message),
            "filename": item.filename,
            "lineno": item.lineno,
        }
        for item in recorded
    ]
    result = {
        "scope": scope_observations,
        "receive_messages": receive_observations,
        "deprecation_warnings": deprecation_warnings,
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


def run_testclient_websocket_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.testclient import TestClient

    settings = case["testclient"]
    websocket_input = case["websocket"]
    app_input = case["asgi_app"]
    scope_observations: list[dict[str, Any]] = []
    receive_observations: list[dict[str, Any]] = []
    send_observations: list[dict[str, Any]] = []

    def record_scope(scope: dict[str, Any]) -> None:
        scope_observations.append(
            {field: _safe(scope[field]) for field in app_input["scope_fields"]}
        )

    async def run_app_body(receive: Any, send: Any) -> None:
        for action in app_input["actions"]:
            if action["operation"] == "receive":
                receive_observations.append(_safe(await receive()))
            else:
                message = _message(action["message"])
                send_observations.append(_safe(message))
                await send(message)

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
    session_input = websocket_input.get("subprotocols")
    request_headers = dict(websocket_input["headers"])
    action_results: list[dict[str, Any]] = []
    with client.websocket_connect(
        websocket_input["url"],
        subprotocols=session_input,
        headers=request_headers,
    ) as session:
        accepted_subprotocol = session.accepted_subprotocol
        for action in websocket_input["actions"]:
            if action["operation"] == "send_text":
                value = session.send_text(action["text"])
            elif action["operation"] == "send_bytes":
                value = session.send_bytes(base64.b64decode(action["data_base64"]))
            elif action["operation"] == "receive_text":
                value = session.receive_text()
            elif action["operation"] == "receive_bytes":
                value = session.receive_bytes()
            else:
                raise ValueError(
                    f"unsupported TestClient WebSocket action: {action['operation']!r}"
                )
            action_results.append({"operation": action["operation"], "value": _safe(value)})
    result = {
        "scope": scope_observations,
        "receive_messages": receive_observations,
        "send_messages": send_observations,
        "session": {
            "accepted_subprotocol": accepted_subprotocol,
            "actions": action_results,
        },
    }
    client.close()
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "websocket-session", "status": "ok", "value": result}],
    }


def run_testclient_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.testclient import TestClient

    settings = case["testclient"]
    app_input = case["asgi_app"]
    lifespan_scope: list[dict[str, Any]] = []
    lifespan_receive_messages: list[dict[str, Any]] = []
    lifespan_send_messages: list[dict[str, Any]] = []
    http_scopes: list[dict[str, Any]] = []
    http_receive_messages: list[dict[str, Any]] = []
    http_send_messages: list[dict[str, Any]] = []
    request_results: list[dict[str, Any]] = []
    loop_state: dict[str, Any] = {"lifespan": None, "previous_http_request": None}
    loop_relations = {name: [] for name in app_input["loop_relations"]}

    def record_scope(scope: dict[str, Any]) -> dict[str, Any]:
        return {field: _safe(scope[field]) for field in app_input["scope_fields"]}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            lifespan_scope.append(record_scope(scope))
            loop_state["lifespan"] = asyncio.get_running_loop()
            for action in app_input["lifespan_actions"]:
                if action["operation"] == "receive":
                    message = await receive()
                    lifespan_receive_messages.append(_safe(message))
                elif action["operation"] == "send":
                    message = _message(action["message"])
                    lifespan_send_messages.append(_safe(message))
                    await send(message)
                else:
                    exception_type = getattr(builtins, action["exception_type"])
                    raise exception_type(action["message"])
            return

        current_loop = asyncio.get_running_loop()
        http_scopes.append(record_scope(scope))
        for relation in app_input["loop_relations"]:
            if relation == "active_lifespan":
                lifespan_loop = loop_state["lifespan"]
                loop_relations[relation].append(
                    None if lifespan_loop is None else current_loop is lifespan_loop
                )
            else:
                previous_loop = loop_state["previous_http_request"]
                loop_relations[relation].append(
                    None if previous_loop is None else current_loop is previous_loop
                )
        loop_state["previous_http_request"] = current_loop
        for _ in range(app_input["http"]["receive_count"]):
            http_receive_messages.append(_safe(await receive()))
        for message_spec in app_input["http"]["messages"]:
            message = _message(message_spec)
            http_send_messages.append(_safe(message))
            await send(message)

    client = TestClient(
        app,
        base_url=settings["base_url"],
        raise_server_exceptions=settings["raise_server_exceptions"],
        root_path=settings["root_path"],
        client=tuple(settings["client"]),
        headers=dict(settings["headers"]),
        backend=settings["backend"],
        backend_options=settings["backend_options"],
    )
    action_errors: list[dict[str, Any]] = []
    for action_index, action in enumerate(case["client_actions"]):
        try:
            if action["operation"] == "enter":
                client.__enter__()
            elif action["operation"] == "exit":
                client.__exit__(None, None, None)
            else:
                request_input = action["request"]
                response = client.request(
                    request_input["method"],
                    request_input["url"],
                    content=base64.b64decode(request_input["body_base64"]),
                    headers=_decoded_pairs(request_input["headers_base64_pairs"]),
                )
                request_results.append(
                    {
                        "action_index": action_index,
                        "url": str(response.request.url),
                        "status_code": response.status_code,
                        "headers": response.headers.multi_items(),
                        "body_base64": base64.b64encode(response.content).decode("ascii"),
                    }
                )
        except Exception as error:
            error_type = type(error)
            action_errors.append(
                {
                    "action_index": action_index,
                    "operation": action["operation"],
                    "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
                    "message": str(error),
                }
            )
            break
    client.close()
    result = {
        "lifespan_scope": lifespan_scope[0],
        "lifespan_receive_messages": lifespan_receive_messages,
        "lifespan_send_messages": lifespan_send_messages,
        "http_scopes": http_scopes,
        "http_receive_messages": http_receive_messages,
        "http_send_messages": http_send_messages,
        "request_results": request_results,
        "action_errors": action_errors,
        "loop_relations": loop_relations,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }
