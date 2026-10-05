"""Input-derived Router graphs consumed through one managed TestClient."""

from __future__ import annotations

import base64
import builtins
import functools
import threading
import uuid
import warnings
from typing import Any


def _safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, uuid.UUID):
        return {"type": f"{type(value).__module__}.{type(value).__qualname__}", "value": str(value)}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def run_router_client_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route, Router, WebSocketRoute
    from starlette.testclient import TestClient

    application = case["application"]
    consumer = case["consumer"]
    endpoint_trace: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    portal_threads: set[threading.Thread] = set()

    def endpoint(specification: dict[str, Any]) -> Any:
        kind = specification["kind"]

        def record(connection: Any) -> None:
            endpoint_trace.append(
                {
                    "kind": kind,
                    "path": connection.url.path,
                    "path_params": _safe(connection.path_params),
                }
            )

        if kind == "text-response":

            def text_response(request: Any) -> Any:
                record(request)
                return Response(
                    specification["text"].format(**request.path_params),
                    media_type=specification["media_type"],
                )

            return text_response
        if kind == "converter-json":

            def converter_json(request: Any) -> Any:
                record(request)
                value = request.path_params[specification["parameter"]]
                if specification["stringify"]:
                    value = str(value)
                return JSONResponse({specification["key"]: value})

            return converter_json
        if kind == "partial-json":

            async def partial_json(argument: Any, request: Any) -> Any:
                record(request)
                return JSONResponse({specification["key"]: argument})

            class PartialEndpoint:
                @classmethod
                async def call(cls, argument: Any, request: Any) -> Any:
                    return await partial_json(argument, request)

            selected = (
                partial_json if specification["shape"] == "function" else PartialEndpoint.call
            )
            return functools.partial(selected, specification["argument"])

        async def websocket_flow(websocket: Any) -> None:
            record(websocket)
            await websocket.accept()
            if kind == "websocket-url":
                await websocket.send_json({specification["key"]: str(websocket.url)})
            else:
                await websocket.send_text(specification["text"].format(**websocket.path_params))
            await websocket.close()

        class PartialWebSocketEndpoint:
            @classmethod
            async def call(cls, websocket: Any) -> None:
                await websocket_flow(websocket)

        if kind == "websocket-url":
            selected = (
                websocket_flow
                if specification["shape"] == "function"
                else PartialWebSocketEndpoint.call
            )
            return functools.partial(selected)
        return websocket_flow

    def route(specification: dict[str, Any]) -> Any:
        kind = specification["kind"]
        if kind == "mount":
            return Mount(
                specification["path"], routes=[route(item) for item in specification["routes"]]
            )
        if kind == "response-mount":
            return Mount(specification["path"], app=Response(**specification["response"]))
        options = {"name": specification["name"]} if "name" in specification else {}
        if kind == "websocket-route":
            return WebSocketRoute(
                specification["path"], endpoint=endpoint(specification["endpoint"]), **options
            )
        if "methods" in specification:
            options["methods"] = specification["methods"]
        return Route(specification["path"], endpoint=endpoint(specification["endpoint"]), **options)

    router = Router([route(item) for item in application["routes"]])

    async def app(scope: Any, receive: Any, send: Any) -> None:
        portal_threads.add(threading.current_thread())
        scopes.append({name: _safe(scope.get(name)) for name in application["scope_fields"]})
        call_index = len(scopes) - 1

        async def observed_receive() -> Any:
            message = await receive()
            events.append(
                {"call_index": call_index, "direction": "receive", "message": _safe(message)}
            )
            return message

        async def observed_send(message: Any) -> None:
            events.append(
                {"call_index": call_index, "direction": "send", "message": _safe(message)}
            )
            await send(message)

        await router(scope, observed_receive, observed_send)

    def observe_response(response: Any) -> dict[str, Any]:
        with warnings.catch_warnings(record=True) as captured_warnings:
            warnings.simplefilter("always")
            for specification in consumer["response_warning_filters"]:
                warnings.filterwarnings(
                    specification["action"],
                    message=specification["message"],
                    category=getattr(builtins, specification["category"]),
                    module=specification["module"],
                )
            text = response.text
        return {
            "status_code": response.status_code,
            "url": str(response.url),
            "headers": response.headers.multi_items(),
            "content_base64": base64.b64encode(response.content).decode("ascii"),
            "text": text,
            "warnings": [
                {
                    "class": f"{item.category.__module__}.{item.category.__qualname__}",
                    "message": str(item.message),
                }
                for item in captured_warnings
            ],
        }

    client = TestClient(app, **consumer["kwargs"])
    entered = False
    try:
        with client:
            entered = True
            for request in consumer["requests"]:
                response = client.request(request["method"], request["url"])
                value = observe_response(response)
                value["history"] = [observe_response(item) for item in response.history]
                responses.append(value)
    finally:
        client.close()
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": case["operation"],
                "status": "ok",
                "value": {
                    "samples": [],
                    "application_trace": endpoint_trace,
                    "context": {
                        "entered": entered,
                        "is_closed": client.is_closed,
                        "portal_threads_alive_after_exit": [
                            thread.is_alive() for thread in portal_threads
                        ],
                    },
                    "responses": responses,
                    "asgi_scopes": scopes,
                    "asgi_events": events,
                },
            }
        ],
    }
