"""Input-driven TestClient adapter shared by the pinned oracle and package target."""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import os
import tempfile
import threading
import warnings
from pathlib import Path
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
    asgi_events: list[dict[str, Any]] = []
    app_exception_state: dict[str, BaseException] = {}
    sync_endpoint_state: dict[str, Any] | None = None
    host_route_observations: list[dict[str, Any]] = []
    starlette_application: Any = None
    temporary_filesystem: tempfile.TemporaryDirectory[str] | None = None

    def record_scope(scope: dict[str, Any]) -> None:
        scope_observations.append(
            {field: _safe(scope[field]) for field in app_input["scope_fields"]}
        )

    async def run_app_body(receive: Any, send: Any) -> None:
        for _ in range(app_input["receive_count"]):
            message = await receive()
            receive_observations.append(_safe(message))
        for message in app_input["messages"]:
            message = _message(message)
            asgi_events.append(_safe(message))
            await send(message)
        if "exception" in app_input:
            exception_type = getattr(builtins, app_input["exception"]["class"])
            raised_exception = exception_type(app_input["exception"]["message"])
            app_exception_state["raised"] = raised_exception
            if "chain" not in app_input["exception"]:
                raise raised_exception
            chain = app_input["exception"]["chain"]
            cause_type = getattr(builtins, chain["class"])
            inner_exception = cause_type(chain["message"])
            app_exception_state["inner"] = inner_exception
            if chain["relation"] == "explicit-cause":
                raise raised_exception from inner_exception
            try:
                raise inner_exception
            except BaseException:
                if chain["relation"] == "implicit-context":
                    # Preserve the input-defined implicit __context__ chain.
                    raise raised_exception  # noqa: B904
                raise raised_exception from None

    if app_input["kind"] == "starlette-route":
        from starlette.applications import Starlette
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        sync_endpoint_state = {
            "caller_thread_id": None,
            "invocation_count": 0,
            "observation": None,
            "lock": threading.Lock(),
        }

        def endpoint(_request: Any) -> Any:
            caller_thread_id = sync_endpoint_state["caller_thread_id"]
            if caller_thread_id is None:
                raise RuntimeError("sync route endpoint ran without a caller thread identity")
            with sync_endpoint_state["lock"]:
                sync_endpoint_state["invocation_count"] += 1
                sync_endpoint_state["observation"] = {
                    "different_worker_thread": threading.get_ident() != caller_thread_id,
                    "invocation_count": sync_endpoint_state["invocation_count"],
                }
            return PlainTextResponse(app_input["endpoint"]["content"])

        route_app = Starlette(
            routes=[Route(app_input["path"], endpoint, methods=app_input["methods"])]
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            sync_endpoint_state["caller_thread_id"] = threading.get_ident()

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await route_app(scope, receive, observed_send)

    elif app_input["kind"] == "starlette-app-debug":
        from starlette.applications import Starlette
        from starlette.routing import Route

        exception_type = getattr(builtins, app_input["exception"]["class"])

        async def endpoint(_request: Any) -> None:
            raise exception_type(app_input["exception"]["message"])

        starlette_application = Starlette(
            debug=app_input["debug_before"],
            routes=[Route(app_input["path"], endpoint)],
        )
        starlette_application.debug = app_input["debug_after"]

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "starlette-app-trusted-host":
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        def endpoint(_request: Any) -> Any:
            return PlainTextResponse(app_input["endpoint"]["content"])

        starlette_application = Starlette(
            routes=[Route(app_input["path"], endpoint)],
            middleware=[
                Middleware(
                    TrustedHostMiddleware,
                    allowed_hosts=app_input["allowed_hosts"],
                )
            ],
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] in {"starlette-app-host-route", "starlette-app-host-method"}:
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        from starlette.responses import PlainTextResponse
        from starlette.routing import Host, Route, Router

        def endpoint(request: Any) -> Any:
            value = request.path_params[app_input["host_parameter"]]
            host_route_observations.append(
                {
                    "host_header": request.headers.get("host"),
                    "path": request.scope["path"],
                    "path_params": _safe(request.path_params),
                    "scope_type": request.scope["type"],
                }
            )
            return PlainTextResponse(f"{app_input['endpoint_prefix']}{value}")

        child_router = Router(routes=[Route(app_input["route_path"], endpoint=endpoint)])
        middleware = [
            Middleware(
                TrustedHostMiddleware,
                allowed_hosts=app_input["allowed_hosts"],
            )
        ]
        if app_input["kind"] == "starlette-app-host-method":
            starlette_application = Starlette(middleware=middleware)
            starlette_application.host(
                app_input["host_pattern"],
                app=child_router,
                name=app_input["host_name"],
            )
        else:
            starlette_application = Starlette(
                routes=[Host(app_input["host_pattern"], app=child_router)],
                middleware=middleware,
            )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "starlette-app-static-mount":
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.staticfiles import StaticFiles

        temporary_filesystem = tempfile.TemporaryDirectory(prefix="starlette-static-mount-parity-")
        directory = Path(temporary_filesystem.name)
        for file_input in app_input["files"]:
            path = directory.joinpath(*file_input["path"].split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(file_input["contents_base64"]))
            mtime_seconds = file_input["mtime_seconds"]
            os.utime(path, (mtime_seconds, mtime_seconds))

        starlette_application = Starlette(
            routes=[
                Mount(
                    app_input["mount_path"],
                    StaticFiles(directory=str(directory)),
                )
            ]
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "router-mounted-response":
        from starlette.responses import PlainTextResponse
        from starlette.routing import Mount, Router

        mounted_response = PlainTextResponse(app_input["content"])
        starlette_application = Router(
            routes=[
                Mount(
                    app_input["mount_path"],
                    app=mounted_response,
                    name=app_input["mount_name"],
                )
            ]
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "asgi2":

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
    response = None
    response_value = None
    followup_response_values: list[dict[str, Any]] = []
    captured_error = None

    def response_observation(value: Any) -> dict[str, Any]:
        return {
            "status_code": value.status_code,
            "url": str(value.url),
            "headers": value.headers.multi_items(),
            "body_base64": base64.b64encode(value.content).decode("ascii"),
            "extensions": _safe(value.extensions),
            "template": _safe(getattr(value, "template", None)),
            "context": _safe(getattr(value, "context", None)),
        }

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        try:
            for index, current_request in enumerate(
                [request_input, *case.get("followup_requests", [])]
            ):
                request_kwargs = {
                    "headers": _decoded_pairs(current_request["headers_base64_pairs"]),
                }
                if "timeout" in current_request:
                    request_kwargs["timeout"] = current_request["timeout"]
                client_method = current_request.get("client_method")
                if client_method == "get":
                    current_response = client.get(current_request["url"], **request_kwargs)
                elif client_method == "post":
                    request_kwargs["content"] = base64.b64decode(current_request["body_base64"])
                    current_response = client.post(current_request["url"], **request_kwargs)
                else:
                    request_kwargs["content"] = base64.b64decode(current_request["body_base64"])
                    current_response = client.request(
                        current_request["method"],
                        current_request["url"],
                        **request_kwargs,
                    )
                current_response_value = response_observation(current_response)
                if index == 0:
                    response = current_response
                    response_value = current_response_value
                else:
                    followup_response_values.append(current_response_value)
        except BaseException as error:
            captured_error = error
        finally:
            try:
                client.close()
            finally:
                if temporary_filesystem is not None:
                    temporary_filesystem.cleanup()
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
        "response": response_value,
        "followup_responses": followup_response_values,
        "asgi_events": asgi_events,
        "sync_endpoint_observations": (
            None if sync_endpoint_state is None else sync_endpoint_state["observation"]
        ),
        "exception_propagation": None,
    }
    if "exception" in app_input and "chain" in app_input["exception"]:
        propagated_cause = None if captured_error is None else captured_error.__cause__
        propagated_context = None if captured_error is None else captured_error.__context__

        def exception_reference(value: BaseException | None) -> dict[str, str] | None:
            if value is None:
                return None
            return {
                "class": f"{type(value).__module__}.{type(value).__qualname__}",
                "message": str(value),
            }

        result["exception_propagation"] = {
            "raised_instance_preserved": captured_error is app_exception_state.get("raised"),
            "cause_instance_preserved": propagated_cause is app_exception_state.get("inner"),
            "context_instance_preserved": propagated_context is app_exception_state.get("inner"),
            "cause": exception_reference(propagated_cause),
            "context": exception_reference(propagated_context),
            "suppress_context": (
                False if captured_error is None else bool(captured_error.__suppress_context__)
            ),
        }
    if app_input["kind"] == "starlette-app-debug":
        result["application_debug"] = bool(starlette_application.debug)
        result["debug_exception_name_present"] = (
            response is not None and app_input["exception"]["class"] in response.text
        )
    if app_input["kind"] == "starlette-app-host-method":
        result["application_routes"] = [
            {
                "type": type(route).__name__,
                "host": getattr(route, "host", None),
                "name": route.name,
                "child_routes": [
                    {
                        "type": type(child).__name__,
                        "path": getattr(child, "path", None),
                        "name": child.name,
                    }
                    for child in getattr(route, "routes", [])
                ],
            }
            for route in starlette_application.routes
        ]
        result["host_route_observations"] = host_route_observations
    observation = {"step_id": "request-response", "status": "ok", "value": result}
    if captured_error is not None:
        cause = captured_error.__cause__
        observation = {
            "step_id": "request-response",
            "status": "error",
            "error": {
                "class": f"{type(captured_error).__module__}.{type(captured_error).__qualname__}",
                "kind": "exception",
                "message": str(captured_error),
                "stage": "dispatch",
                "code": None,
                "cause": (
                    {
                        "class": f"{type(cause).__module__}.{type(cause).__qualname__}",
                        "message": str(cause),
                        "attributes": _safe(vars(cause)),
                    }
                    if cause is not None
                    else None
                ),
                "suppress_context": bool(captured_error.__suppress_context__),
            },
            "partial_value": result,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [observation],
    }


def run_testclient_websocket_case(case: dict[str, Any]) -> dict[str, Any]:
    try:
        import httpx2 as httpx
    except ModuleNotFoundError:
        import httpx

    from starlette.testclient import TestClient, WebSocketDenialResponse
    from starlette.websockets import WebSocketDisconnect

    settings = case["testclient"]
    websocket_input = case["websocket"]
    app_input = case["asgi_app"]
    scope_observations: list[dict[str, Any]] = []
    receive_observations: list[dict[str, Any]] = []
    send_observations: list[dict[str, Any]] = []
    event_tape: list[dict[str, Any]] = []
    application_values: list[dict[str, Any]] = []
    disconnect_observations: list[dict[str, Any]] = []
    cancellation_observations: list[dict[str, str]] = []
    application_state: dict[str, Any] = {"completed": False, "thread": None}

    async def observed_receive(receive: Any) -> dict[str, Any]:
        message = await receive()
        safe_message = _safe(message)
        receive_observations.append(safe_message)
        event_tape.append({"direction": "receive", "message": safe_message})
        return message

    async def observed_send(send: Any, message: dict[str, Any]) -> None:
        safe_message = _safe(message)
        send_observations.append(safe_message)
        event_tape.append({"direction": "send", "message": safe_message})
        await send(message)

    def record_scope(scope: dict[str, Any]) -> None:
        scope_observations.append(
            {field: _safe(scope[field]) for field in app_input["scope_fields"]}
        )

    async def run_app_body(receive: Any, send: Any) -> None:
        for action in app_input["actions"]:
            if action["operation"] == "receive":
                await observed_receive(receive)
            else:
                message = _message(action["message"])
                await observed_send(send, message)

    async def run_websocket_flow(scope: dict[str, Any], receive: Any, send: Any) -> None:
        import anyio
        from starlette.websockets import WebSocket, WebSocketDisconnect

        websocket = WebSocket(
            scope,
            lambda: observed_receive(receive),
            lambda message: observed_send(send, message),
        )
        query_params_value: dict[str, Any] | None = None

        async def run_actions(actions: list[dict[str, Any]]) -> None:
            nonlocal query_params_value
            for action in actions:
                operation = action["operation"]
                if operation == "accept":
                    await websocket.accept(
                        action.get("subprotocol"),
                        _decoded_pairs(action.get("headers_base64_pairs", [])),
                    )
                elif operation == "observe_query_params":
                    query_params_value = dict(websocket.query_params)
                    application_values.append(
                        {"operation": "query_params", "value": _safe(query_params_value)}
                    )
                elif operation == "send_json":
                    await websocket.send_json(action["value"], action.get("mode", "text"))
                elif operation == "send_query_params_json":
                    await websocket.send_json({"params": query_params_value})
                elif operation == "close":
                    await websocket.close()
                elif operation == "send_scope_bytes":
                    await websocket.send_bytes(scope[action["field"]])
                elif operation == "receive_json":
                    try:
                        value = await websocket.receive_json(action.get("mode", "text"))
                    except WebSocketDisconnect as error:
                        if not action.get("capture_disconnect", False):
                            raise
                        disconnect_observations.append(
                            {
                                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                "code": error.code,
                                "reason": error.reason,
                            }
                        )
                    else:
                        application_values.append({"operation": operation, "value": _safe(value)})
                elif operation == "parallel":
                    async with anyio.create_task_group() as task_group:
                        for task in action["tasks"]:
                            task_group.start_soon(run_actions, task)
                elif operation == "wait_forever":
                    try:
                        await anyio.sleep_forever()
                    except anyio.get_cancelled_exc_class() as error:
                        cancellation_observations.append(
                            {"class": f"{type(error).__module__}.{type(error).__qualname__}"}
                        )
                        raise
                else:
                    raise ValueError(f"unsupported WebSocket app action: {operation!r}")

        try:
            await run_actions(app_input["actions"][0]["actions"])
        finally:
            application_state["completed"] = True

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        record_scope(scope)
        application_state["thread"] = threading.current_thread()
        try:
            if app_input["actions"][0]["operation"] == "websocket_flow":
                await run_websocket_flow(scope, receive, send)
            else:
                await run_app_body(receive, send)
        finally:
            application_state["completed"] = True

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
    accepted_subprotocol = None
    denial_response = None
    websocket_kwargs = {"headers": request_headers}
    if "params" in websocket_input:
        websocket_kwargs["params"] = websocket_input["params"]
    try:
        with client.websocket_connect(
            websocket_input["url"],
            subprotocols=session_input,
            **websocket_kwargs,
        ) as session:
            accepted_subprotocol = session.accepted_subprotocol
            for action in websocket_input["actions"]:
                if action["operation"] == "send_text":
                    value = session.send_text(action["text"])
                elif action["operation"] == "send_bytes":
                    value = session.send_bytes(base64.b64decode(action["data_base64"]))
                elif action["operation"] == "send_json":
                    value = session.send_json(action["value"], action.get("mode", "text"))
                elif action["operation"] == "receive_text":
                    value = session.receive_text()
                elif action["operation"] == "receive_bytes":
                    value = session.receive_bytes()
                elif action["operation"] == "receive_json":
                    value = session.receive_json(action.get("mode", "text"))
                else:
                    raise ValueError(
                        f"unsupported TestClient WebSocket action: {action['operation']!r}"
                    )
                action_results.append({"operation": action["operation"], "value": _safe(value)})
    except WebSocketDenialResponse as exception:
        exception_type = type(exception)
        denial_response = {
            "class": f"{exception_type.__module__}.{exception_type.__qualname__}",
            "is_websocket_disconnect": isinstance(exception, WebSocketDisconnect),
            "is_httpx_response": isinstance(exception, httpx.Response),
            "status_code": exception.status_code,
            "headers": exception.headers.multi_items(),
            "body_base64": base64.b64encode(exception.content).decode("ascii"),
        }
    result = {
        "scope": scope_observations,
        "receive_messages": receive_observations,
        "send_messages": send_observations,
        "session": {
            "accepted_subprotocol": accepted_subprotocol,
            "actions": action_results,
        },
        "denial_response": denial_response,
    }
    result["event_tape"] = event_tape
    portal_thread = application_state["thread"]
    result["app"] = {
        "values": application_values,
        "disconnects": disconnect_observations,
        "cancellations": cancellation_observations,
        "completed": application_state["completed"],
        "portal_thread_alive_after_exit": (
            None if portal_thread is None else portal_thread.is_alive()
        ),
    }
    client.close()
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "websocket-session", "status": "ok", "value": result}],
    }


def _run_starlette_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    settings = case["testclient"]
    app_input = case["asgi_app"]
    lifecycle_trace: list[str] = []
    lifespan_scopes: list[dict[str, Any]] = []
    lifespan_receive_messages: list[dict[str, Any]] = []
    lifespan_send_messages: list[dict[str, Any]] = []
    action_errors: list[dict[str, Any]] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        lifecycle_trace.append(app_input["callback"]["entry_effect"])
        try:
            yield
        finally:
            lifecycle_trace.append(app_input["callback"]["exit_effect"])

    starlette_app = Starlette(lifespan=lifespan)

    def record_scope(scope: dict[str, Any]) -> dict[str, Any]:
        return {field: _safe(scope.get(field)) for field in app_input["scope_fields"]}

    async def instrumented_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def observed_receive() -> dict[str, Any]:
            message = await receive()
            lifespan_receive_messages.append(_safe(message))
            return message

        async def observed_send(message: dict[str, Any]) -> None:
            lifespan_send_messages.append(_safe(message))
            await send(message)

        await starlette_app(scope, observed_receive, observed_send)
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
    lifecycle_trace_before_actions = list(lifecycle_trace)
    lifecycle_trace_after_actions: list[dict[str, Any]] = []
    for action_index, action in enumerate(case["client_actions"]):
        try:
            if action["operation"] == "enter":
                client.__enter__()
            else:
                client.__exit__(None, None, None)
            lifecycle_trace_after_actions.append(
                {
                    "action_index": action_index,
                    "operation": action["operation"],
                    "trace": list(lifecycle_trace),
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
        "http_scopes": [],
        "http_receive_messages": [],
        "http_send_messages": [],
        "request_results": [],
        "websocket_scopes": [],
        "websocket_receive_messages": [],
        "websocket_send_messages": [],
        "websocket_results": [],
        "action_errors": action_errors,
        "loop_relations": {"active_lifespan": [], "previous_http_request": []},
        "lifespan_trace_before_actions": lifecycle_trace_before_actions,
        "lifespan_trace_after_actions": lifecycle_trace_after_actions,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }


def run_testclient_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["asgi_app"]["kind"] == "starlette-lifespan":
        return _run_starlette_lifespan_case(case)
    if case["asgi_app"]["kind"] == "starlette-state":
        from scripts.parity.adapters.testclient_state import (
            run_testclient_stateful_lifespan_case,
        )

        return run_testclient_stateful_lifespan_case(case)

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
        "websocket_scopes": [],
        "websocket_receive_messages": [],
        "websocket_send_messages": [],
        "websocket_results": [],
        "action_errors": action_errors,
        "loop_relations": loop_relations,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }
