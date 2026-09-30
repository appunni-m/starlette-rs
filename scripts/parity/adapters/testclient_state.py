"""Input-driven TestClient lifecycle and lifespan-state workflow."""

from __future__ import annotations

import asyncio
import base64
import contextlib
from typing import Any


def _safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def _decoded_pairs(value: list[list[str]]) -> list[tuple[bytes, bytes]]:
    return [(base64.b64decode(key), base64.b64decode(item)) for key, item in value]


def _state_owner(connection: Any, source: str, lifespan_state: dict[str, Any]) -> Any:
    if source in {"request", "websocket"}:
        return connection.state
    if source == "app":
        return connection.scope["app"].state
    return lifespan_state


def _state_reference(
    connection: Any,
    reference: dict[str, Any],
    lifespan_state: dict[str, Any],
) -> Any:
    current = _state_owner(connection, reference["source"], lifespan_state)
    path = reference["path"]
    if not path:
        return current
    key = path[0]
    current = getattr(current, key) if reference["access"] == "attribute" else current[key]
    for key in path[1:]:
        current = current[key]
    return current


def _apply_state_actions(
    connection: Any,
    route: dict[str, Any],
    lifespan_state: dict[str, Any],
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for action in route["actions"]:
        if action["operation"] == "read":
            reference = {key: action[key] for key in ("source", "path", "access")}
            observations[action["name"]] = _safe(
                _state_reference(connection, reference, lifespan_state)
            )
        elif action["operation"] == "identity":
            observations[action["name"]] = _state_reference(
                connection, action["left"], lifespan_state
            ) is _state_reference(connection, action["right"], lifespan_state)
        else:
            target = _state_owner(connection, action["target"], lifespan_state)
            path = action["path"]
            if len(path) == 1:
                if action["access"] == "attribute":
                    setattr(target, path[0], action["value"])
                else:
                    target[path[0]] = action["value"]
            else:
                root = (
                    getattr(target, path[0]) if action["access"] == "attribute" else target[path[0]]
                )
                for key in path[1:-1]:
                    root = root[key]
                root[path[-1]] = action["value"]
    return observations


def run_testclient_stateful_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.testclient import TestClient

    settings = case["testclient"]
    app_input = case["asgi_app"]
    lifespan_state = app_input["lifespan_state"]
    scope_fields = app_input["scope_fields"]
    lifespan_scopes: list[dict[str, Any]] = []
    lifespan_receive_messages: list[dict[str, Any]] = []
    lifespan_send_messages: list[dict[str, Any]] = []
    http_scopes: list[dict[str, Any]] = []
    http_receive_messages: list[dict[str, Any]] = []
    http_send_messages: list[dict[str, Any]] = []
    websocket_scopes: list[dict[str, Any]] = []
    websocket_receive_messages: list[dict[str, Any]] = []
    websocket_send_messages: list[dict[str, Any]] = []
    request_results: list[dict[str, Any]] = []
    websocket_results: list[dict[str, Any]] = []
    action_errors: list[dict[str, Any]] = []
    loop_state: dict[str, Any] = {"lifespan": None, "previous_http_request": None}
    loop_relations = {name: [] for name in app_input["loop_relations"]}

    def record_scope(scope: dict[str, Any]) -> dict[str, Any]:
        return {field: _safe(scope.get(field)) for field in scope_fields}

    routes: list[Any] = []
    for route_input in app_input["routes"]:
        if route_input["transport"] == "http":

            def make_http_endpoint(route: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    values = _apply_state_actions(request, route, lifespan_state)
                    return JSONResponse(values)

                return endpoint

            routes.append(
                Route(
                    route_input["path"],
                    make_http_endpoint(route_input),
                    methods=[route_input["method"]],
                )
            )
        else:

            def make_websocket_endpoint(route: dict[str, Any]) -> Any:
                async def endpoint(websocket: Any) -> None:
                    await websocket.accept()
                    values = _apply_state_actions(websocket, route, lifespan_state)
                    await websocket.send_json(values)
                    await websocket.close()

                return endpoint

            routes.append(
                WebSocketRoute(
                    route_input["path"],
                    make_websocket_endpoint(route_input),
                )
            )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        yield lifespan_state

    app = Starlette(routes=routes, lifespan=lifespan)
    for key, value in app_input["app_state"].items():
        setattr(app.state, key, value)

    async def instrumented_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        connection_type = scope["type"]
        if connection_type == "lifespan":
            loop_state["lifespan"] = asyncio.get_running_loop()
            receive_messages = lifespan_receive_messages
            send_messages = lifespan_send_messages
        else:
            current_loop = asyncio.get_running_loop()
            loop_relations["active_lifespan"].append(
                None if loop_state["lifespan"] is None else current_loop is loop_state["lifespan"]
            )
            previous_loop = loop_state["previous_http_request"]
            loop_relations["previous_http_request"].append(
                None if previous_loop is None else current_loop is previous_loop
            )
            if connection_type == "http":
                http_scopes.append(record_scope(scope))
                loop_state["previous_http_request"] = current_loop
                receive_messages = http_receive_messages
                send_messages = http_send_messages
            else:
                websocket_scopes.append(record_scope(scope))
                receive_messages = websocket_receive_messages
                send_messages = websocket_send_messages

        async def observed_receive() -> dict[str, Any]:
            message = await receive()
            receive_messages.append(_safe(message))
            return message

        async def observed_send(message: dict[str, Any]) -> None:
            send_messages.append(_safe(message))
            await send(message)

        await app(scope, observed_receive, observed_send)
        if connection_type == "lifespan":
            lifespan_scopes.append(record_scope(scope))

    client = TestClient(
        instrumented_app,
        base_url=settings["base_url"],
        raise_server_exceptions=settings["raise_server_exceptions"],
        root_path=settings["root_path"],
        client=tuple(settings["client"]),
        headers=dict(settings["headers"]),
        backend=settings["backend"],
        backend_options=settings["backend_options"],
    )
    for action_index, action in enumerate(case["client_actions"]):
        try:
            if action["operation"] == "enter":
                client.__enter__()
            elif action["operation"] == "exit":
                client.__exit__(None, None, None)
            elif action["operation"] == "request":
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
            else:
                with client.websocket_connect(
                    action["url"],
                    subprotocols=action["subprotocols"],
                ) as websocket:
                    websocket_results.append(
                        {
                            "action_index": action_index,
                            "url": action["url"],
                            "accepted_subprotocol": websocket.accepted_subprotocol,
                            "received_json": websocket.receive_json(),
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
        "lifespan_scope": lifespan_scopes[0],
        "lifespan_receive_messages": lifespan_receive_messages,
        "lifespan_send_messages": lifespan_send_messages,
        "http_scopes": http_scopes,
        "http_receive_messages": http_receive_messages,
        "http_send_messages": http_send_messages,
        "request_results": request_results,
        "websocket_scopes": websocket_scopes,
        "websocket_receive_messages": websocket_receive_messages,
        "websocket_send_messages": websocket_send_messages,
        "websocket_results": websocket_results,
        "action_errors": action_errors,
        "loop_relations": loop_relations,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }
