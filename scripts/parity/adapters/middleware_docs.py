"""Input-driven consumer helpers for documented user-defined ASGI middleware."""

from __future__ import annotations

import asyncio
import base64
import functools
from collections.abc import Callable
from typing import Any


def make_redirects_middleware(
    url_type: Any, redirect_response_type: Any, class_name: str
) -> type[Any]:
    """Build the documented user middleware selected by its input class name."""

    if class_name == "MockResponseBodyMiddleware":
        from starlette.datastructures import Headers

        def __init__(self: Any, app: Any, content: str) -> None:
            self.app = app
            self.content = content.encode("utf-8")

        async def __call__(self: Any, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            should_mock = False

            async def maybe_send_with_mock_content(message: Any) -> None:
                nonlocal should_mock

                if message["type"] == "http.response.start":
                    headers = Headers(raw=message["headers"])
                    should_mock = headers.get("X-Mock") == "1"
                    await send(message)
                elif message["type"] == "http.response.body":
                    if should_mock:
                        message = {"type": "http.response.body", "body": self.content}
                    await send(message)

            await self.app(scope, receive, maybe_send_with_mock_content)

        return type(
            class_name,
            (),
            {
                "__module__": "starlette.middleware",
                "__init__": __init__,
                "__call__": __call__,
            },
        )

    def __init__(self: Any, app: Any, path_mapping: dict[str, str]) -> None:
        self.app = app
        self.path_mapping = path_mapping

    async def __call__(self: Any, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        url = url_type(scope=scope)
        if url.path in self.path_mapping:
            url = url.replace(path=self.path_mapping[url.path])
            response = redirect_response_type(url, status_code=301)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    return type(
        class_name,
        (),
        {
            "__module__": "starlette.middleware",
            "__init__": __init__,
            "__call__": __call__,
        },
    )


def run_eager_response_workflow(
    workflow: dict[str, Any],
    middleware_values: list[Any],
    make_scope: Callable[[dict[str, Any]], dict[str, Any]],
    make_message: Callable[[dict[str, Any]], dict[str, Any]],
    canonicalize_message: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Invoke an input-defined ASGI app through a public Middleware iterator."""
    app_spec = workflow["asgi_app"]
    if app_spec["kind"] == "asgi-responses-by-path":
        response_messages = {
            item["path"]: item["response"]["messages"] for item in app_spec["responses_by_path"]
        }

        def response_key(scope: Any) -> str | None:
            return scope.get("path")

    else:
        response_messages = {
            item["scope_type"]: item["response"]["messages"]
            for item in app_spec["responses_by_scope"]
        }

        def response_key(scope: Any) -> str:
            return scope["type"]

    downstream_calls: list[dict[str, Any]] = []

    async def downstream_app(scope: Any, _receive: Any, send: Any) -> None:
        downstream_calls.append({"scope_type": scope["type"], "path": scope.get("path")})
        for message in response_messages[response_key(scope)]:
            message_type = message["type"]
            if message_type == "http.response.start":
                event = {
                    "type": message_type,
                    "status": message["status"],
                    "headers": [
                        (
                            base64.b64decode(name, validate=True),
                            base64.b64decode(value, validate=True),
                        )
                        for name, value in message["headers_base64_pairs"]
                    ],
                }
            elif message_type == "http.response.body":
                event = {
                    "type": message_type,
                    "body": base64.b64decode(message["body_base64"], validate=True),
                    "more_body": message["more_body"],
                }
            else:
                event = dict(message)
            await send(event)

    middleware_type, middleware_args, middleware_kwargs = middleware_values
    wrapped_app = middleware_type(downstream_app, *middleware_args, **middleware_kwargs)

    async def run_calls() -> dict[str, Any]:
        schedule = workflow.get("schedule")
        barrier: asyncio.Event | None = None
        barrier_message_type: str | None = None
        barrier_participants = 0
        barrier_arrivals = 0
        interleaving_trace: list[dict[str, str]] = []

        if schedule is not None:
            if schedule["kind"] != "concurrent-send-barrier":
                raise ValueError("unsupported middleware ASGI workflow schedule")
            barrier_participants = schedule["participants"]
            if barrier_participants != len(workflow["calls"]):
                raise ValueError("send barrier participants must match concurrent calls")
            barrier_message_type = schedule["barrier_after_message"]
            barrier = asyncio.Event()

        async def run_call(call: dict[str, Any]) -> dict[str, Any]:
            nonlocal barrier_arrivals

            scope = make_scope(call["scope"])
            incoming = [make_message(message) for message in call["receive"]]
            receive_index = 0
            sent: list[dict[str, Any]] = []

            async def receive() -> dict[str, Any]:
                nonlocal receive_index
                if receive_index < len(incoming):
                    message = incoming[receive_index]
                    receive_index += 1
                    return message
                if scope["type"] == "http":
                    return {"type": "http.disconnect"}
                return {"type": "websocket.disconnect", "code": 1000}

            async def send(message: dict[str, Any]) -> None:
                nonlocal barrier_arrivals

                sent_message = canonicalize_message(message)
                sent.append(sent_message)
                interleaving_trace.append(
                    {"call_id": call["call_id"], "message_type": message["type"]}
                )
                if barrier is not None and message["type"] == barrier_message_type:
                    barrier_arrivals += 1
                    if barrier_arrivals == barrier_participants:
                        barrier.set()
                    await barrier.wait()

            await wrapped_app(scope, receive, send)
            response_start = next(
                (message for message in sent if message["type"] == "http.response.start"),
                None,
            )
            body_chunks = [
                message["body"]["data"]
                for message in sent
                if message["type"] == "http.response.body"
            ]
            downstream_invoked = any(
                item["scope_type"] == scope["type"] and item["path"] == scope.get("path")
                for item in downstream_calls
            )
            return {
                "call_id": call["call_id"],
                "scope_type": scope["type"],
                "path": scope.get("path"),
                "downstream_invoked": downstream_invoked,
                "response": {
                    "status": None if response_start is None else response_start["status"],
                    "headers": [] if response_start is None else response_start["headers"],
                    "body_chunks_base64": body_chunks,
                },
                "asgi_event_order": [message["type"] for message in sent],
                "asgi_events": sent,
            }

        if barrier is None:
            observations = []
            for call in workflow["calls"]:
                observations.append(await run_call(call))
        else:
            observations = await asyncio.gather(*(run_call(call) for call in workflow["calls"]))

        result = {"calls": observations, "downstream_calls": downstream_calls}
        if barrier is not None:
            result["interleaving_trace"] = interleaving_trace
        return result

    return asyncio.run(run_calls())


def make_input_pure_asgi_middleware(
    class_name: str,
    traces: list[dict[str, Any]],
    canonicalize_message: Callable[[dict[str, Any]], dict[str, Any]],
) -> Any:
    """Build the input-defined class or decorator-style ASGI middleware callable."""

    async def invoke(
        app: Any,
        settings: dict[str, Any],
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        selected = scope["type"] in settings["scope_types"]
        trace = {
            "scope_type": scope["type"],
            "path": scope.get("path"),
            "applied": selected,
            "receive_messages": [],
            "received_http_body_bytes": 0,
            "send_message_types": [],
        }
        traces.append(trace)
        if not selected:
            await app(scope, receive, send)
            return

        async def receive_wrapper() -> dict[str, Any]:
            message = await receive()
            if settings["observe_receive"]:
                kind = message["type"]
                if kind == "http.request":
                    body = message.get("body", b"")
                    trace["received_http_body_bytes"] += len(body)
                    trace["receive_messages"].append(
                        {
                            "type": kind,
                            "body_base64": base64.b64encode(body).decode("ascii"),
                            "more_body": message.get("more_body", False),
                        }
                    )
                elif kind.startswith("websocket."):
                    trace["receive_messages"].append(canonicalize_message(message))
                else:
                    trace["receive_messages"].append({"type": kind})
            return message

        async def send_wrapper(message: dict[str, Any]) -> None:
            outgoing = message
            kind = message["type"]
            if kind == "http.response.start":
                from starlette.datastructures import MutableHeaders

                headers = MutableHeaders(scope=outgoing)
                for name, value in settings["append_headers"]:
                    headers.append(name, value)
                suffix = settings["body_suffix"]
                content_length = headers.get("content-length")
                if suffix and content_length is not None:
                    headers["content-length"] = str(int(content_length) + len(suffix))
            elif kind == "http.response.body" and settings["body_suffix"]:
                if not message.get("more_body", False):
                    outgoing = dict(message)
                    outgoing["body"] = message.get("body", b"") + settings["body_suffix"]
            elif kind == "websocket.send" and settings["websocket_text_suffix"]:
                if isinstance(message.get("text"), str):
                    outgoing = dict(message)
                    outgoing["text"] = message["text"] + settings["websocket_text_suffix"]
            trace["send_message_types"].append(kind)
            await send(outgoing)

        try:
            await app(
                scope,
                receive_wrapper if settings["observe_receive"] else receive,
                send_wrapper,
            )
        except BaseException as exc:
            if settings["observe_errors"]:
                trace["observed_error"] = {
                    "class": type(exc).__name__,
                    "message": str(exc),
                    "is_cancellation": isinstance(exc, asyncio.CancelledError),
                }
            raise
        finally:
            if settings["observe_cleanup"]:
                trace["cleanup_completed"] = True

    def settings_from(kwargs: dict[str, Any]) -> dict[str, Any]:
        return {
            "scope_types": tuple(kwargs["scope_types"]),
            "observe_receive": kwargs["observe_receive"],
            "observe_errors": kwargs["observe_errors"],
            "observe_cleanup": kwargs["observe_cleanup"],
            "append_headers": tuple(tuple(pair) for pair in kwargs["append_headers"]),
            "body_suffix": base64.b64decode(kwargs["body_suffix_base64"], validate=True),
            "websocket_text_suffix": kwargs["websocket_text_suffix"],
        }

    if class_name == "ASGIMiddleware":

        def __init__(self: Any, app: Any, **kwargs: Any) -> None:
            self.app = app
            self.settings = settings_from(kwargs)

        async def __call__(self: Any, scope: Any, receive: Any, send: Any) -> None:
            await invoke(self.app, self.settings, scope, receive, send)

        return type(
            class_name,
            (),
            {
                "__module__": "starlette.middleware",
                "__init__": __init__,
                "__call__": __call__,
            },
        )

    if class_name == "asgi_decorator":

        def asgi_decorator(app: Any, **kwargs: Any) -> Any:
            settings = settings_from(kwargs)

            @functools.wraps(app)
            async def wrapped_app(scope: Any, receive: Any, send: Any) -> None:
                await invoke(app, settings, scope, receive, send)

            return wrapped_app

        asgi_decorator.__module__ = "starlette.middleware"
        return asgi_decorator

    raise ValueError(f"unsupported pure ASGI middleware factory: {class_name!r}")


def run_pure_asgi_workflow(
    workflow: dict[str, Any],
    middleware_descriptor: Any,
    middleware_values: list[Any],
    middleware_traces: list[dict[str, Any]],
    make_scope: Callable[[dict[str, Any]], dict[str, Any]],
    make_message: Callable[[dict[str, Any]], dict[str, Any]],
    canonicalize_message: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Run input-defined pure ASGI middleware through the public Python package path."""

    app_spec = workflow["asgi_app"]
    downstream_calls: list[dict[str, Any]] = []
    downstream_received: dict[str, list[dict[str, Any]]] = {}
    route_calls: list[dict[str, Any]] = []
    starlette_app: Any | None = None
    middleware_factory, middleware_args, middleware_kwargs = middleware_values

    def materialize_output_message(spec: dict[str, Any]) -> dict[str, Any]:
        kind = spec["type"]
        if kind.startswith("lifespan."):
            return {"type": kind}
        if kind == "http.response.start":
            return {
                "type": kind,
                "status": spec["status"],
                "headers": [
                    (
                        base64.b64decode(name, validate=True),
                        base64.b64decode(value, validate=True),
                    )
                    for name, value in spec["headers_base64_pairs"]
                ],
            }
        if kind == "http.response.body":
            return {
                "type": kind,
                "body": base64.b64decode(spec["body_base64"], validate=True),
                "more_body": spec["more_body"],
            }
        if kind == "websocket.accept":
            event: dict[str, Any] = {"type": kind}
            if "subprotocol" in spec:
                event["subprotocol"] = spec["subprotocol"]
            if "headers_base64_pairs" in spec:
                event["headers"] = [
                    (
                        base64.b64decode(name, validate=True),
                        base64.b64decode(value, validate=True),
                    )
                    for name, value in spec["headers_base64_pairs"]
                ]
            return event
        if kind == "websocket.send":
            if "text" in spec:
                return {"type": kind, "text": spec["text"]}
            return {
                "type": kind,
                "bytes": base64.b64decode(spec["bytes_base64"], validate=True),
            }
        if kind == "websocket.close":
            event = {"type": kind, "code": spec["code"]}
            if "reason" in spec:
                event["reason"] = spec["reason"]
            return event
        raise ValueError(f"unsupported pure ASGI output event: {kind!r}")

    if app_spec["kind"] == "asgi-events-by-scope":
        app_by_scope = {item["scope_type"]: item for item in app_spec["events_by_scope"]}

        async def downstream_app(scope: Any, receive: Any, send: Any) -> None:
            call = current_call[0]
            downstream_calls.append({"call_id": call["call_id"], "scope_type": scope["type"]})
            received: list[dict[str, Any]] = []
            downstream_received[call["call_id"]] = received
            app_input = app_by_scope[scope["type"]]
            receive_count = app_input.get("receive_count", len(call["receive"]))
            for _ in range(receive_count):
                message = await receive()
                kind = message["type"]
                if kind == "http.request":
                    received.append(
                        {
                            "type": kind,
                            "body_base64": base64.b64encode(message.get("body", b"")).decode(
                                "ascii"
                            ),
                            "more_body": message.get("more_body", False),
                        }
                    )
                elif kind.startswith("websocket."):
                    received.append(canonicalize_message(message))
                else:
                    received.append({"type": kind})
            for spec in app_input["events"]:
                await send(materialize_output_message(spec))
            failure = app_input.get("failure")
            if failure is not None:
                exception_types = {
                    "RuntimeError": RuntimeError,
                    "ValueError": ValueError,
                    "LookupError": LookupError,
                }
                raise exception_types[failure["exception_type"]](failure["message"])

        wrapped_app = middleware_factory(downstream_app, *middleware_args, **middleware_kwargs)
        application_observation = {
            "kind": "arbitrary-asgi-app",
            "downstream_app_type": _qualified_type(downstream_app),
            "wrapped_app_type": _qualified_type(wrapped_app),
            "top_level_app_replaced": True,
            "wrapped_application_contains_downstream": (
                getattr(wrapped_app, "app", None) is downstream_app
                or getattr(wrapped_app, "__wrapped__", None) is downstream_app
            ),
        }
    elif app_spec["kind"] == "starlette-app":
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route, WebSocketRoute

        routes = []
        for route_spec in app_spec["routes"]:
            if route_spec["kind"] == "http-route":

                async def http_endpoint(request: Any, spec: dict[str, Any] = route_spec) -> Any:
                    route_calls.append({"kind": "http", "path": request.url.path})
                    return Response(
                        content=base64.b64decode(spec["body_base64"], validate=True),
                        status_code=spec["status"],
                        headers=dict(spec["headers"]),
                    )

                routes.append(Route(route_spec["path"], http_endpoint, methods=["GET"]))
            else:

                async def websocket_endpoint(
                    websocket: Any, spec: dict[str, Any] = route_spec
                ) -> None:
                    await websocket.accept()
                    received_text = await websocket.receive_text()
                    route_calls.append(
                        {
                            "kind": "websocket",
                            "path": websocket.url.path,
                            "received_text": received_text,
                        }
                    )
                    await websocket.send_text(spec["response_prefix"] + received_text)
                    await websocket.close(code=spec["close_code"])

                routes.append(WebSocketRoute(route_spec["path"], websocket_endpoint))

        starlette_app = Starlette(routes=routes, middleware=[middleware_descriptor])
        wrapped_app = starlette_app
        application_observation = {
            "kind": "starlette-app",
            "app_type": _qualified_type(starlette_app),
            "top_level_app_replaced": False,
            "middleware_descriptor_count": len(starlette_app.user_middleware),
            "middleware_stack_built": starlette_app.middleware_stack is not None,
        }
    else:
        raise ValueError(f"unsupported pure ASGI app kind: {app_spec['kind']!r}")

    async def run_calls() -> dict[str, Any]:
        async def run_call(call: dict[str, Any]) -> dict[str, Any]:
            current_call[0] = call
            scope = make_scope(call["scope"])
            incoming = [make_message(message) for message in call["receive"]]
            receive_index = 0
            sent: list[dict[str, Any]] = []
            blocked_receive_started = asyncio.Event()
            termination = workflow.get("termination")
            cancel_while_blocked = (
                termination is not None and termination["call_id"] == call["call_id"]
            )

            async def receive() -> dict[str, Any]:
                nonlocal receive_index
                if receive_index < len(incoming):
                    message = incoming[receive_index]
                    receive_index += 1
                    return message
                if cancel_while_blocked:
                    blocked_receive_started.set()
                    await asyncio.Event().wait()
                if scope["type"] == "http":
                    return {"type": "http.disconnect"}
                if scope["type"] == "websocket":
                    return {"type": "websocket.disconnect", "code": 1000}
                raise RuntimeError("input-defined lifespan app read past its supplied events")

            async def send(message: dict[str, Any]) -> None:
                sent.append(canonicalize_message(message))

            terminal_error: BaseException | None = None
            if cancel_while_blocked:
                app_task = asyncio.create_task(wrapped_app(scope, receive, send))
                await blocked_receive_started.wait()
                app_task.cancel()
                try:
                    await app_task
                except BaseException as exc:
                    terminal_error = exc
            else:
                try:
                    await wrapped_app(scope, receive, send)
                except BaseException as exc:
                    terminal_error = exc
            if starlette_app is not None:
                application_observation["middleware_stack_built"] = (
                    starlette_app.middleware_stack is not None
                )
            start = next(
                (message for message in sent if message["type"] == "http.response.start"),
                None,
            )
            body_chunks = [
                message["body"]["data"]
                for message in sent
                if message["type"] == "http.response.body"
            ]
            invoked = (
                any(item["call_id"] == call["call_id"] for item in downstream_calls)
                if app_spec["kind"] == "asgi-events-by-scope"
                else scope["type"] == "lifespan"
                or any(
                    item["kind"] == scope["type"] and item["path"] == scope.get("path")
                    for item in route_calls
                )
            )
            observation = {
                "call_id": call["call_id"],
                "scope_type": scope["type"],
                "path": scope.get("path"),
                "downstream_invoked": invoked,
                "downstream_received_messages": downstream_received.get(call["call_id"], []),
                "response": {
                    "status": None if start is None else start["status"],
                    "headers": [] if start is None else start["headers"],
                    "body_chunks_base64": body_chunks,
                },
                "asgi_event_order": [message["type"] for message in sent],
                "asgi_events": sent,
            }
            if terminal_error is not None:
                observation["terminal_error"] = {
                    "class": type(terminal_error).__name__,
                    "message": str(terminal_error),
                    "is_cancellation": isinstance(terminal_error, asyncio.CancelledError),
                }
            return observation

        observations = [await run_call(call) for call in workflow["calls"]]
        return {
            "application": application_observation,
            "calls": observations,
            "downstream_calls": downstream_calls,
            "route_calls": route_calls,
            "middleware_traces": middleware_traces,
        }

    current_call: list[dict[str, Any]] = [{}]
    result = asyncio.run(run_calls())
    return result


def _qualified_type(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"
