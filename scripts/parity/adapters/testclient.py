"""Input-driven TestClient adapter shared by the pinned oracle and package target."""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import os
import sys
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
    request_content_generator_yields: list[str] = []
    sync_endpoint_state: dict[str, Any] | None = None
    host_route_observations: list[dict[str, Any]] = []
    mount_scope_observations: list[dict[str, Any]] = []
    request_url_for_observations: list[str] = []
    starlette_application: Any = None
    temporary_filesystem: tempfile.TemporaryDirectory[str] | None = None
    nested_testclient_state: dict[str, Any] | None = None

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
        from starlette.responses import JSONResponse, PlainTextResponse, Response
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
            endpoint_spec = app_input["endpoint"]
            if endpoint_spec["kind"] == "sync-json-response":
                return JSONResponse(endpoint_spec["content"])
            if endpoint_spec["kind"] == "sync-query-param-text-response":
                return Response(_request.query_params[endpoint_spec["query_parameter"]])
            if endpoint_spec["kind"] == "sync-request-url-path-response":
                return Response(_request.url.path)
            return PlainTextResponse(endpoint_spec["content"])

        route_app = Starlette(
            routes=[Route(app_input["path"], endpoint, methods=app_input["methods"])]
        )
        fault_contract = case.get("fault_contract")
        if fault_contract is not None:
            if fault_contract["fault_point"] != "starlette-rs.router.route-cache-lock.poison":
                raise ValueError("unsupported TestClient fault point")
            route_app.router._runtime._fault_contract_poison_route_cache()

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            sync_endpoint_state["caller_thread_id"] = threading.get_ident()

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await route_app(scope, receive, observed_send)

    elif app_input["kind"] == "starlette-nested-testclient":
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        nested_testclient_state = {
            "trace": [],
            "trace_lock": threading.Lock(),
            "inner_scope": [],
            "inner_asgi_events": [],
            "inner_response": None,
        }

        def record_nested_trace(stage: str, **details: Any) -> None:
            event = {"stage": stage}
            event.update(details)
            with nested_testclient_state["trace_lock"]:
                nested_testclient_state["trace"].append(event)

        inner_app_input = app_input["inner_app"]

        def inner_endpoint(_request: Any) -> Any:
            record_nested_trace("inner-endpoint-enter")
            return JSONResponse(inner_app_input["endpoint"]["content"])

        inner_route_app = Starlette(routes=[Route(inner_app_input["path"], inner_endpoint)])

        def endpoint(_request: Any) -> Any:
            record_nested_trace("outer-endpoint-enter")

            inner_settings = app_input["inner_testclient"]
            inner_client = TestClient(
                inner_app,
                base_url=inner_settings["base_url"],
                raise_server_exceptions=inner_settings["raise_server_exceptions"],
                root_path=inner_settings["root_path"],
                client=tuple(inner_settings["client"]),
                headers=dict(inner_settings["headers"]),
            )
            inner_request = app_input["inner_request"]
            inner_response = inner_client.get(
                inner_request["url"],
                headers=_decoded_pairs(inner_request["headers_base64_pairs"]),
            )
            nested_testclient_state["inner_response"] = response_observation(inner_response)
            record_nested_trace(
                "inner-client-response",
                status_code=inner_response.status_code,
            )
            record_nested_trace("outer-endpoint-return")
            return JSONResponse(inner_response.json())

        route_app = Starlette(routes=[Route(app_input["path"], endpoint)])

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            record_nested_trace("outer-app-enter")

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                send_details = {"type": message["type"]}
                if "status" in message:
                    send_details["status"] = message["status"]
                record_nested_trace("outer-app-send", **send_details)
                await send(message)

            await route_app(scope, receive, observed_send)
            record_nested_trace("outer-app-exit")

        async def inner_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            nested_testclient_state["inner_scope"].append(
                {field: _safe(scope[field]) for field in inner_app_input["scope_fields"]}
            )
            record_nested_trace("inner-app-enter")

            async def observed_inner_send(message: dict[str, Any]) -> None:
                safe_message = _safe(message)
                nested_testclient_state["inner_asgi_events"].append(safe_message)
                record_nested_trace("inner-app-send", message=safe_message)
                await send(message)

            await inner_route_app(scope, receive, observed_inner_send)
            record_nested_trace("inner-app-exit")

    elif app_input["kind"] in {
        "starlette-route-graph",
        "starlette-partial-route-graph",
        "starlette-url-for-route-graph",
        "starlette-protocol-switch",
    }:
        from functools import partial

        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route, Router, WebSocketRoute

        def endpoint_response(
            endpoint_spec: dict[str, Any], scope: dict[str, Any], request: Any = None
        ) -> Any:
            if endpoint_spec["kind"] == "request-url-for-json":
                value = {
                    lookup["key"]: str(request.url_for(lookup["name"], **lookup["path_params"]))
                    for lookup in endpoint_spec["lookups"]
                }
            else:
                value = {"name": endpoint_spec["name"]}
                value.update({field: scope[field] for field in endpoint_spec["fields"]})
            return JSONResponse(value)

        def request_endpoint_for(endpoint_spec: dict[str, Any]) -> Any:
            if endpoint_spec["kind"] == "async-partial-json":
                if endpoint_spec["callable_shape"] == "function":

                    async def endpoint(bound_value: Any, _request: Any) -> Any:
                        return JSONResponse({endpoint_spec["response_key"]: bound_value})

                    return partial(endpoint, endpoint_spec["bound_value"])

                class PartialRoutes:
                    @classmethod
                    async def endpoint(
                        cls: type[PartialRoutes], bound_value: Any, _request: Any
                    ) -> Any:
                        return JSONResponse({endpoint_spec["response_key"]: bound_value})

                return partial(
                    PartialRoutes.endpoint,
                    endpoint_spec["bound_value"],
                )

            async def endpoint(request: Any) -> Any:
                return endpoint_response(endpoint_spec, request.scope, request)

            return endpoint

        def asgi_endpoint_for(endpoint_spec: dict[str, Any]) -> Any:
            async def endpoint(scope: dict[str, Any], receive: Any, send: Any) -> None:
                response = endpoint_response(endpoint_spec, scope)
                await response(scope, receive, send)

            return endpoint

        def websocket_endpoint_for(endpoint_spec: dict[str, Any]) -> Any:
            async def endpoint(websocket: Any) -> None:
                await websocket.accept()
                lookup = endpoint_spec["lookup"]
                value = {
                    lookup["key"]: str(websocket.url_for(lookup["name"], **lookup["path_params"]))
                }
                await websocket.send_json(value)
                await websocket.close()

            return endpoint

        def build_routes(route_specs: list[dict[str, Any]]) -> list[Any]:
            routes = []
            for route_spec in route_specs:
                if route_spec["kind"] == "route":
                    routes.append(
                        Route(
                            route_spec["path"],
                            request_endpoint_for(route_spec["endpoint"]),
                            methods=route_spec["methods"],
                            name=route_spec["name"],
                        )
                    )
                elif route_spec["kind"] == "mount-routes":
                    routes.append(
                        Mount(
                            route_spec["path"],
                            name=route_spec["name"],
                            routes=build_routes(route_spec["routes"]),
                        )
                    )
                elif route_spec["kind"] == "websocket-route":
                    routes.append(
                        WebSocketRoute(
                            route_spec["path"],
                            websocket_endpoint_for(route_spec["endpoint"]),
                            name=route_spec["name"],
                        )
                    )
                else:
                    routes.append(
                        Mount(
                            route_spec["path"],
                            app=asgi_endpoint_for(route_spec["endpoint"]),
                        )
                    )
            return routes

        if app_input["kind"] == "starlette-partial-route-graph":
            route_app = Router(routes=build_routes(app_input["routes"]))
        else:
            route_app = Starlette(routes=build_routes(app_input["routes"]))

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

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

    elif app_input["kind"] == "starlette-app-cors-global-error":
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware
        from starlette.routing import Route

        exception_type = getattr(builtins, app_input["exception"]["class"])

        async def endpoint(_request: Any) -> None:
            raise exception_type(app_input["exception"]["message"])

        starlette_application = Starlette(
            debug=app_input["debug"],
            routes=[Route(app_input["path"], endpoint)],
        )
        cors_application = CORSMiddleware(
            starlette_application,
            allow_origins=app_input["allow_origins"],
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await cors_application(scope, receive, observed_send)

    elif app_input["kind"] == "server-error-middleware":
        from starlette.middleware.errors import ServerErrorMiddleware

        exception_type = getattr(builtins, app_input["exception"]["class"])

        async def raising_app(_scope: dict[str, Any], _receive: Any, _send: Any) -> None:
            raise exception_type(app_input["exception"]["message"])

        server_error_middleware = ServerErrorMiddleware(
            raising_app,
            debug=app_input["debug"],
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await server_error_middleware(scope, receive, observed_send)

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
            observation = {
                "host_header": request.headers.get("host"),
                "path": request.scope["path"],
                "path_params": _safe(request.path_params),
                "scope_type": request.scope["type"],
            }
            if "path_params_probe" in app_input:
                missing_key = app_input["path_params_probe"]["missing_key"]
                try:
                    request.path_params[missing_key]
                except KeyError as error:
                    observation["missing_key_lookup"] = {
                        "class": f"{type(error).__module__}.{type(error).__qualname__}",
                        "message": str(error),
                    }
                else:
                    observation["missing_key_lookup"] = None
            host_route_observations.append(observation)
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

    elif app_input["kind"] == "static-files-root-symlink":
        from starlette.staticfiles import StaticFiles

        temporary_filesystem = tempfile.TemporaryDirectory(
            prefix="starlette-static-root-symlink-parity-"
        )
        workspace = Path(temporary_filesystem.name)
        configured_root = workspace.joinpath(*app_input["directory"].split("/"))
        target_root = workspace.joinpath(*app_input["root_symlink_target"].split("/"))
        target_root.mkdir(parents=True)
        for file_input in app_input["files"]:
            path = target_root.joinpath(*file_input["path"].split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(file_input["contents_base64"]))
            os.utime(path, (file_input["mtime_seconds"], file_input["mtime_seconds"]))
        configured_root.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(target_root, configured_root.parent), configured_root)
        static_files = StaticFiles(
            directory=str(configured_root), follow_symlink=app_input["follow_symlink"]
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await static_files(scope, receive, observed_send)

    elif app_input["kind"] == "static-files-relative-directory":
        from starlette.staticfiles import StaticFiles

        temporary_filesystem = tempfile.TemporaryDirectory(
            prefix="starlette-static-relative-parity-", dir=Path.cwd()
        )
        workspace = Path(temporary_filesystem.name)
        relative_workspace = workspace.relative_to(Path.cwd())
        directory_components = app_input["directory"].split("/")
        directory = workspace.joinpath(*directory_components)
        directory.mkdir(parents=True)
        for file_input in app_input["files"]:
            path = directory.joinpath(*file_input["path"].split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(file_input["contents_base64"]))
            os.utime(path, (file_input["mtime_seconds"], file_input["mtime_seconds"]))
        relative_directory = relative_workspace.joinpath(*directory_components)
        static_files = StaticFiles(
            directory=str(relative_directory), follow_symlink=app_input["follow_symlink"]
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await static_files(scope, receive, observed_send)

    elif app_input["kind"] == "static-files-lookup-error":
        from starlette.applications import Starlette
        from starlette.routing import Mount
        from starlette.staticfiles import StaticFiles

        temporary_filesystem = tempfile.TemporaryDirectory(
            prefix="starlette-static-lookup-error-parity-"
        )
        directory = Path(temporary_filesystem.name).joinpath(*app_input["directory"].split("/"))
        directory.mkdir(parents=True)
        for file_input in app_input["files"]:
            path = directory.joinpath(*file_input["path"].split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(file_input["contents_base64"]))
            mtime_seconds = file_input["mtime_seconds"]
            os.utime(path, (mtime_seconds, mtime_seconds))

        exception_type = getattr(builtins, app_input["lookup_error"]["class"])

        class FailingStaticFiles(StaticFiles):
            def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
                raise exception_type()

        static_files = FailingStaticFiles(directory=str(directory))
        starlette_application = Starlette(routes=[Mount("/", app=static_files, name="static")])

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] in {
        "starlette-app-static-mount",
        "starlette-app-static-mount-method",
        "starlette-app-static-head-middleware",
    }:
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

        if app_input["kind"] == "starlette-app-static-mount-method":

            class ScopeRecordingStaticFiles(StaticFiles):
                async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
                    mount_scope_observations.append(
                        {
                            "app_root_path": scope.get("app_root_path"),
                            "path": scope.get("path"),
                            "root_path": scope.get("root_path"),
                            "type": scope.get("type"),
                        }
                    )
                    await super().__call__(scope, receive, send)

            static_files = ScopeRecordingStaticFiles(directory=str(directory))
            starlette_application = Starlette()
            starlette_application.mount(
                app_input["mount_path"],
                static_files,
                name=app_input["mount_method_name"],
            )
        elif app_input["kind"] == "starlette-app-static-head-middleware":
            from starlette.middleware import Middleware
            from starlette.middleware.base import BaseHTTPMiddleware
            from starlette.requests import Request
            from starlette.responses import Response

            async def does_nothing_middleware(request: Request, call_next: Any) -> Response:
                return await call_next(request)

            static_files = StaticFiles(directory=str(directory))
            starlette_application = Starlette(
                routes=[Mount(app_input["mount_path"], app=static_files, name="static")],
                middleware=[Middleware(BaseHTTPMiddleware, dispatch=does_nothing_middleware)],
            )
        else:
            static_files = StaticFiles(directory=str(directory))
            starlette_application = Starlette(routes=[Mount(app_input["mount_path"], static_files)])

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

    elif app_input["kind"] == "router-middleware-response":
        from starlette.middleware import Middleware
        from starlette.responses import PlainTextResponse, Response
        from starlette.routing import Route, Router

        def endpoint(_request: Any) -> Response:
            return Response(app_input["route_content"], media_type="text/plain")

        class CustomMiddleware:
            def __init__(self, wrapped_app: Any) -> None:
                self.app = wrapped_app

            async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
                response = PlainTextResponse(app_input["response_content"])
                await response(scope, receive, send)

        starlette_application = Router(
            routes=[Route(app_input["route_path"], endpoint)],
            middleware=[Middleware(CustomMiddleware)],
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "request-cookie-round-trip":
        from starlette.requests import Request
        from starlette.responses import Response

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            request = Request(scope, receive)
            cookie_value = request.cookies.get(app_input["cookie_name"])
            if cookie_value:
                response = Response(cookie_value, media_type=app_input["media_type"])
            else:
                response = Response(
                    app_input["fallback_content"], media_type=app_input["media_type"]
                )
                response.set_cookie(
                    app_input["cookie_name"],
                    app_input["cookie_value"],
                    domain=app_input.get("cookie_domain"),
                )

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await response(scope, receive, observed_send)

    elif app_input["kind"] == "request-observer":
        from starlette.requests import Request
        from starlette.responses import JSONResponse, PlainTextResponse

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            probe = app_input["probe"]
            if probe == "url":
                request = Request(scope, receive)
                url = request.url
                response = JSONResponse(
                    {
                        "method": request.method,
                        "url": str(url),
                        "components": {
                            "scheme": url.scheme,
                            "netloc": url.netloc,
                            "path": url.path,
                            "query": url.query,
                            "fragment": url.fragment,
                            "username": url.username,
                            "password": url.password,
                            "hostname": url.hostname,
                            "port": url.port,
                            "is_secure": url.is_secure,
                        },
                    }
                )
            elif probe == "query-params-mapping":
                request = Request(scope, receive)
                response = JSONResponse({"params": dict(request.query_params)})
            elif probe == "query-params-semantics":
                request = Request(scope, receive)
                query_params = request.query_params
                query_pairs = query_params.multi_items()
                query_keys = list(query_params)
                repeated_key = next(key for key in query_keys if len(query_params.getlist(key)) > 1)
                mutation_value = query_params[repeated_key]
                mutation_exception = None
                try:
                    query_params[repeated_key] = mutation_value
                except Exception as error:
                    mutation_exception = {
                        "class": f"{type(error).__module__}.{type(error).__qualname__}",
                        "message": str(error),
                    }
                response = JSONResponse(
                    {
                        "query_params": {
                            "same_instance": query_params is request.query_params,
                            "multi_items": query_pairs,
                            "mapping": dict(query_params),
                            "lookups": [
                                {
                                    "key": key,
                                    "getlist": query_params.getlist(key),
                                    "scalar": query_params[key],
                                }
                                for key in query_keys
                            ],
                            "mutation_exception": mutation_exception,
                            "after_mutation": {
                                "multi_items": query_params.multi_items(),
                                "mapping": dict(query_params),
                            },
                        }
                    }
                )
            elif probe == "headers-mapping":
                request = Request(scope, receive)
                response = JSONResponse({"headers": dict(request.headers)})
            elif probe == "headers-semantics":
                request = Request(scope, receive)
                headers = request.headers
                raw_headers = headers.raw
                header_names = list(headers)
                repeated_name = next(
                    name for name in header_names if len(headers.getlist(name)) > 1
                )
                repeated_values = headers.getlist(repeated_name)
                mutation_exception = None
                try:
                    headers[repeated_name] = headers[repeated_name]
                except Exception as error:
                    mutation_exception = {
                        "class": f"{type(error).__module__}.{type(error).__qualname__}",
                        "message": str(error),
                    }
                response = JSONResponse(
                    {
                        "headers": {
                            "same_instance": headers is request.headers,
                            "raw": raw_headers,
                            "mapping": dict(headers),
                            "items": list(headers.items()),
                            "repeated": {
                                "name": repeated_name,
                                "getlist": repeated_values,
                                "lowercase": headers[repeated_name.lower()],
                                "uppercase": headers[repeated_name.upper()],
                            },
                            "mutation_exception": mutation_exception,
                            "after_mutation": {
                                "raw": headers.raw,
                                "mapping": dict(headers),
                            },
                        }
                    }
                )
            elif probe == "raw-path":
                request = Request(scope, receive)
                response = PlainTextResponse(
                    f"{request.scope['path']}, {request.scope['raw_path']}"
                )
            elif probe == "json-without-receive":
                request = Request(scope)
                try:
                    value = await request.json()
                except RuntimeError as error:
                    value = str(error)
                response = JSONResponse({"json": value})
            else:
                raise ValueError(f"unsupported Request observer probe: {probe}")

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await response(scope, receive, observed_send)

    elif app_input["kind"] == "request-url-for-middleware":
        from starlette.applications import Starlette
        from starlette.middleware import Middleware
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route

        async def endpoint(_request: Any) -> Any:
            return PlainTextResponse(app_input["content"])

        class RequestURLForMiddleware:
            def __init__(self, inner: Any) -> None:
                self.inner = inner

            async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
                request = Request(scope, receive)
                request_url_for_observations.append(str(request.url_for(app_input["route_name"])))
                await self.inner(scope, receive, send)

        starlette_application = Starlette(
            routes=[Route(app_input["route_path"], endpoint, name=app_input["route_name"])],
            middleware=[Middleware(RequestURLForMiddleware)],
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await starlette_application(scope, receive, observed_send)

    elif app_input["kind"] == "request-url-for-error":
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            request = Request(scope, receive)
            response = JSONResponse(
                {"url": str(request.url_for(app_input["name"], **app_input["path_params"]))}
            )

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await response(scope, receive, observed_send)

    elif app_input["kind"] == "raw-asgi-error":

        async def app(scope: dict[str, Any], _receive: Any, _send: Any) -> None:
            record_scope(scope)
            exception_type = getattr(builtins, app_input["exception"]["class"])
            raise exception_type(app_input["exception"]["message"])

    elif app_input["kind"] == "path-response-map":
        from starlette.responses import RedirectResponse, Response

        responses_by_path = {
            response_input["path"]: response_input["response"]
            for response_input in app_input["responses"]
        }

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            response_input = responses_by_path[scope["path"]]
            if response_input["kind"] == "redirect":
                response = RedirectResponse(response_input["url"])
            else:
                response = Response(response_input["content"])

            async def observed_send(message: dict[str, Any]) -> None:
                asgi_events.append(_safe(message))
                await send(message)

            await response(scope, receive, observed_send)

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
        follow_redirects=settings.get("follow_redirects", True),
    )
    response = None
    response_value = None
    followup_response_values: list[dict[str, Any]] = []
    captured_error = None

    def response_observation(value: Any) -> dict[str, Any]:
        return {
            "status_code": value.status_code,
            "reason_phrase": value.reason_phrase,
            "url": str(value.url),
            "headers": value.headers.multi_items(),
            "body_base64": base64.b64encode(value.content).decode("ascii"),
            "extensions": _safe(value.extensions),
            "template": _safe(getattr(value, "template", None)),
            "context": _safe(getattr(value, "context", None)),
            "cookies": dict(value.cookies),
            "client_cookies": dict(client.cookies),
        }

    def request_content(current_request: dict[str, Any]) -> Any:
        if "content_generator_chunks_base64" not in current_request:
            return base64.b64decode(current_request["body_base64"])

        def generated_chunks() -> Any:
            for encoded_chunk in current_request["content_generator_chunks_base64"]:
                chunk = base64.b64decode(encoded_chunk)
                request_content_generator_yields.append(base64.b64encode(chunk).decode("ascii"))
                yield chunk

        return generated_chunks()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        try:
            for index, current_request in enumerate(
                [request_input, *case.get("followup_requests", [])]
            ):
                request_kwargs = {
                    "headers": _decoded_pairs(current_request["headers_base64_pairs"]),
                }
                if "params" in current_request:
                    request_kwargs["params"] = current_request["params"]
                if "timeout" in current_request:
                    request_kwargs["timeout"] = current_request["timeout"]
                client_method = current_request.get("client_method")
                if client_method == "get":
                    current_response = client.get(current_request["url"], **request_kwargs)
                elif client_method == "head":
                    current_response = client.head(current_request["url"], **request_kwargs)
                elif client_method == "post":
                    request_kwargs["content"] = request_content(current_request)
                    current_response = client.post(current_request["url"], **request_kwargs)
                else:
                    request_kwargs["content"] = request_content(current_request)
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
    nested_testclient_observation = None
    if nested_testclient_state is not None:
        nested_testclient_observation = {
            "inner_scope": nested_testclient_state["inner_scope"],
            "inner_asgi_events": nested_testclient_state["inner_asgi_events"],
            "inner_response": nested_testclient_state["inner_response"],
            "trace": nested_testclient_state["trace"],
        }
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
        "nested_testclient": nested_testclient_observation,
        "exception_propagation": None,
    }
    if "content_generator_chunks_base64" in request_input:
        result["request_content_generator_yields"] = request_content_generator_yields
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
    if app_input.get("observe_request_url_for") is True:
        result["request_url_for"] = request_url_for_observations
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
    if app_input["kind"] == "starlette-app-static-mount-method":
        result["application_mount_routes"] = [
            {
                "type": type(route).__name__,
                "path": getattr(route, "path", None),
                "name": route.name,
                "child_routes": [
                    {"type": type(child).__name__, "path": getattr(child, "path", None)}
                    for child in getattr(route, "routes", [])
                ],
            }
            for route in starlette_application.routes
        ]
        result["mount_scope_observations"] = mount_scope_observations
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
    flow_actions = app_input.get("actions", [])
    flow_actions = (
        flow_actions[0]["actions"]
        if flow_actions and flow_actions[0].get("operation") == "websocket_flow"
        else []
    )
    stream_spec = next(
        (action for action in flow_actions if action["operation"] == "memory_stream_echo"),
        None,
    )
    stream_pair = None
    if stream_spec is not None:
        import anyio

        # The pinned user app creates these streams on the client caller thread.
        stream_pair = anyio.create_memory_object_stream(stream_spec["buffer_size"])

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
            elif action["operation"] == "raise":
                exception_type = getattr(builtins, action["exception_class"])
                raise exception_type(action["message"])
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
        headers_value: dict[str, str] | None = None
        response: Any = None

        async def run_actions(actions: list[dict[str, Any]]) -> None:
            nonlocal query_params_value, headers_value, response
            for action in actions:
                operation = action["operation"]
                if operation == "receive":
                    message = await websocket.receive()
                    application_values.append({"operation": operation, "value": _safe(message)})
                elif operation == "accept":
                    accept_kwargs = {}
                    if "subprotocol" in action:
                        accept_kwargs["subprotocol"] = action["subprotocol"]
                    if "headers_base64_pairs" in action:
                        accept_kwargs["headers"] = _decoded_pairs(action["headers_base64_pairs"])
                    await websocket.accept(**accept_kwargs)
                elif operation == "observe_query_params":
                    query_params_value = dict(websocket.query_params)
                    application_values.append(
                        {"operation": "query_params", "value": _safe(query_params_value)}
                    )
                elif operation == "observe_headers":
                    headers_value = dict(websocket.headers)
                    application_values.append(
                        {
                            "operation": "headers",
                            "value": headers_value,
                            "compression_modules_loaded": [
                                name for name in ("brotli", "brotlicffi") if name in sys.modules
                            ],
                        }
                    )
                elif operation == "send_headers_json":
                    await websocket.send_json({"headers": headers_value})
                elif operation == "remove_extension":
                    del scope["extensions"][action["name"]]
                elif operation == "make_response":
                    from starlette.responses import Response

                    response = Response(**action["response"])
                elif operation == "send_response_start":
                    await websocket.send(
                        {
                            "type": "websocket.http.response.start",
                            "status": response.status_code,
                            "headers": response.raw_headers,
                        }
                    )
                elif operation == "send_denial_response":
                    try:
                        await websocket.send_denial_response(response)
                    except Exception as error:
                        if not action.get("capture_error", False):
                            raise
                        application_values.append(
                            {
                                "operation": operation,
                                "error": {
                                    "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                    "message": str(error),
                                },
                            }
                        )
                elif operation == "memory_stream_echo":
                    stream_send, stream_receive = stream_pair

                    async def reader(output_stream: Any) -> None:
                        async with output_stream:
                            async for data in websocket.iter_json():
                                application_values.append(
                                    {"operation": "stream-reader", "value": _safe(data)}
                                )
                                await output_stream.send(data)

                    async def writer(input_stream: Any) -> None:
                        async with input_stream:
                            async for message in input_stream:
                                await websocket.send_json(message)

                    async with anyio.create_task_group() as task_group:
                        task_group.start_soon(reader, stream_send)
                        await writer(stream_receive)
                elif operation == "send_json":
                    await websocket.send_json(action["value"], action.get("mode", "text"))
                elif operation == "iterate":
                    iterator = getattr(websocket, action["method"])()
                    on_item = action["on_item"]
                    async for item in iterator:
                        if on_item["operation"] == "send_text_prefix":
                            await websocket.send_text(on_item["prefix"] + item)
                        elif on_item["operation"] == "send_bytes_prefix":
                            await websocket.send_bytes(on_item["prefix"].encode("utf-8") + item)
                        else:
                            await websocket.send_json({on_item["key"]: item})
                elif operation == "send_query_params_json":
                    await websocket.send_json({"params": query_params_value})
                elif operation == "send_url_json":
                    url = websocket.url
                    value = {"url": str(url)}
                    value.update(
                        {component: getattr(url, component) for component in action["components"]}
                    )
                    application_values.append({"operation": operation, "value": value})
                    await websocket.send_json(value)
                elif operation == "close":
                    close_code = action.get("code", 1000)
                    if "reason" in action:
                        await websocket.close(close_code, action["reason"])
                    else:
                        await websocket.close(close_code)
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
                elif operation == "receive_text":
                    try:
                        value = await websocket.receive_text()
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

    if app_input["kind"] == "starlette-websocket-route-error":
        from starlette.applications import Starlette
        from starlette.routing import WebSocketRoute

        exception_type = getattr(builtins, app_input["endpoint_exception"]["class"])

        def endpoint(_websocket: Any) -> None:
            raise exception_type(app_input["endpoint_exception"]["message"])

        starlette_application = Starlette(routes=[WebSocketRoute(app_input["path"], endpoint)])

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            application_state["thread"] = threading.current_thread()
            try:
                await starlette_application(scope, receive, send)
            finally:
                application_state["completed"] = True
    elif app_input["kind"] == "starlette-partial-websocket-route-graph":
        from functools import partial

        from starlette.routing import Mount, Router, WebSocketRoute

        class PartialWebSocketRoutes:
            @classmethod
            async def endpoint(cls, websocket: Any) -> None:
                await websocket.accept()
                await websocket.send_json({"url": str(websocket.url)})
                await websocket.close()

        def endpoint_for(callable_shape: str) -> Any:
            if callable_shape == "function":

                async def endpoint(websocket: Any) -> None:
                    await websocket.accept()
                    await websocket.send_json({"url": str(websocket.url)})
                    await websocket.close()

                return partial(endpoint)
            return partial(PartialWebSocketRoutes.endpoint)

        mount_input = app_input["mount"]
        websocket_routes = [
            WebSocketRoute(
                route_spec["path"],
                endpoint_for(route_spec["callable_shape"]),
            )
            for route_spec in mount_input["routes"]
        ]
        router = Router([Mount(mount_input["path"], routes=websocket_routes)])

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            application_state["thread"] = threading.current_thread()

            async def traced_receive() -> dict[str, Any]:
                return await observed_receive(receive)

            async def traced_send(message: dict[str, Any]) -> None:
                await observed_send(send, message)

            try:
                await router(scope, traced_receive, traced_send)
            finally:
                application_state["completed"] = True

    elif app_input["kind"] in {
        "starlette-routed-websocket-graph",
        "starlette-standalone-websocket-route",
    }:
        from starlette.routing import Router, WebSocketRoute

        def endpoint_for(endpoint_spec: dict[str, Any]) -> Any:
            async def endpoint(websocket: Any) -> None:
                await websocket.accept()
                if endpoint_spec["kind"] == "literal-text":
                    text = endpoint_spec["text"]
                else:
                    text = (
                        endpoint_spec["prefix"]
                        + websocket.path_params[endpoint_spec["parameter"]]
                        + endpoint_spec["suffix"]
                    )
                await websocket.send_text(text)
                await websocket.close()

            return endpoint

        routes = [
            WebSocketRoute(route_spec["path"], endpoint_for(route_spec["endpoint"]))
            for route_spec in app_input["routes"]
        ]
        route_app = (
            routes[0]
            if app_input["kind"] == "starlette-standalone-websocket-route"
            else Router(routes=routes)
        )

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            application_state["thread"] = threading.current_thread()

            async def traced_receive() -> dict[str, Any]:
                return await observed_receive(receive)

            async def traced_send(message: dict[str, Any]) -> None:
                await observed_send(send, message)

            try:
                await route_app(scope, traced_receive, traced_send)
            finally:
                application_state["completed"] = True

    elif app_input["kind"] == "starlette-protocol-switch":
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route, WebSocketRoute

        routes = []
        for route_spec in app_input["routes"]:
            if route_spec["kind"] == "route":
                endpoint_spec = route_spec["endpoint"]

                async def request_endpoint(
                    request: Any, spec: dict[str, Any] = endpoint_spec
                ) -> Any:
                    value = {
                        lookup["key"]: str(request.url_for(lookup["name"], **lookup["path_params"]))
                        for lookup in spec["lookups"]
                    }
                    return JSONResponse(value)

                routes.append(
                    Route(
                        route_spec["path"],
                        request_endpoint,
                        methods=route_spec["methods"],
                        name=route_spec["name"],
                    )
                )
            else:
                endpoint_spec = route_spec["endpoint"]

                async def websocket_endpoint(
                    websocket: Any, spec: dict[str, Any] = endpoint_spec
                ) -> None:
                    await websocket.accept()
                    lookup = spec["lookup"]
                    value = {
                        lookup["key"]: str(
                            websocket.url_for(lookup["name"], **lookup["path_params"])
                        )
                    }
                    application_values.append({"operation": "url_for", "value": _safe(value)})
                    await websocket.send_json(value)
                    await websocket.close()

                routes.append(
                    WebSocketRoute(
                        route_spec["path"],
                        websocket_endpoint,
                        name=route_spec["name"],
                    )
                )

        starlette_application = Starlette(routes=routes)

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            record_scope(scope)
            application_state["thread"] = threading.current_thread()
            try:
                await starlette_application(scope, receive, send)
            finally:
                application_state["completed"] = True
    else:

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
        backend=settings.get("backend", "asyncio"),
        backend_options=settings.get("backend_options", {}),
    )
    session_input = websocket_input.get("subprotocols")
    request_headers = dict(websocket_input["headers"])
    action_results: list[dict[str, Any]] = []
    accepted_subprotocol = None
    accepted_extra_headers = None
    denial_response = None
    session_entered = False
    session_body_completed = False
    captured_error: BaseException | None = None
    captured_error_stage = "websocket-session-entry"
    entry_disconnect = None
    websocket_kwargs = {"headers": request_headers}
    if "params" in websocket_input:
        websocket_kwargs["params"] = websocket_input["params"]
    try:
        with client.websocket_connect(
            websocket_input["url"],
            subprotocols=session_input,
            **websocket_kwargs,
        ) as session:
            session_entered = True
            accepted_subprotocol = session.accepted_subprotocol
            accepted_extra_headers = session.extra_headers
            for action in websocket_input["actions"]:
                try:
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
                    elif action["operation"] == "close":
                        value = session.close(action.get("code", 1000), action.get("reason"))
                    else:
                        raise ValueError(
                            f"unsupported TestClient WebSocket action: {action['operation']!r}"
                        )
                except WebSocketDisconnect as error:
                    if not action.get("capture_disconnect", False):
                        raise
                    action_results.append(
                        {
                            "operation": action["operation"],
                            "disconnect": {
                                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                "code": error.code,
                                "reason": error.reason,
                            },
                        }
                    )
                else:
                    action_results.append({"operation": action["operation"], "value": _safe(value)})
            session_body_completed = True
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
    except WebSocketDisconnect as error:
        captured_error = error
        if not session_entered:
            entry_disconnect = {
                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                "code": error.code,
                "reason": error.reason,
            }
        else:
            captured_error_stage = (
                "websocket-session-exit" if session_body_completed else "websocket-session-action"
            )
    except Exception as error:
        # Exceptions from public session entry, methods, or exit are behavioral
        # outcomes. App construction and harness failures stay outside this block.
        captured_error = error
        if session_entered:
            captured_error_stage = (
                "websocket-session-exit" if session_body_completed else "websocket-session-action"
            )
    result = {
        "scope": scope_observations,
        "receive_messages": receive_observations,
        "send_messages": send_observations,
        "session": {
            "accepted_subprotocol": accepted_subprotocol,
            "extra_headers": _safe(accepted_extra_headers),
            "actions": action_results,
            "entry_disconnect": entry_disconnect,
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
    observation = {"step_id": "websocket-session", "status": "ok", "value": result}
    if captured_error is not None:
        cause = captured_error.__cause__
        observation = {
            "step_id": "websocket-session",
            "status": "error",
            "error": {
                "class": f"{type(captured_error).__module__}.{type(captured_error).__qualname__}",
                "kind": "exception",
                "message": str(captured_error),
                "stage": captured_error_stage,
                "code": getattr(captured_error, "code", None),
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


def _run_starlette_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    settings = case["testclient"]
    app_input = case["asgi_app"]
    lifecycle_trace: list[str] = []
    lifespan_scopes: list[dict[str, Any]] = []
    lifespan_receive_messages: list[dict[str, Any]] = []
    lifespan_send_messages: list[dict[str, Any]] = []
    scope_mutation_trace: list[dict[str, Any]] = []
    action_errors: list[dict[str, Any]] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        callback = app_input["callback"]
        if "entry_error" in callback:
            error = callback["entry_error"]
            lifecycle_trace.append(f"startup-error:{error['exception_type']}")
            exception_type = getattr(builtins, error["exception_type"])
            raise exception_type(error["message"])

        lifecycle_trace.append(callback["entry_effect"])

        @contextlib.asynccontextmanager
        async def managed_tasks() -> Any:
            task_group_input = callback.get("task_group")
            if task_group_input is None:
                yield
                return

            import anyio

            child_started = anyio.Event()
            child_release = anyio.Event()

            async def child() -> None:
                lifecycle_trace.append(task_group_input["child_start_effect"])
                child_started.set()
                await child_release.wait()
                lifecycle_trace.append(task_group_input["child_finish_effect"])

            async with anyio.create_task_group() as task_group:
                task_group.start_soon(child)
                await child_started.wait()
                try:
                    yield
                finally:
                    lifecycle_trace.append(task_group_input["release_effect"])
                    child_release.set()

        try:
            async with managed_tasks():
                yield callback.get("lifespan_state")
                if "exit_error" in callback:
                    error = callback["exit_error"]
                    exception_type = getattr(builtins, error["exception_type"])
                    raise exception_type(error["message"])
        finally:
            if "exit_effect" in callback:
                lifecycle_trace.append(callback["exit_effect"])

    if app_input["kind"] == "starlette-router-lifespan":
        from starlette.routing import Router

        starlette_app = Router(lifespan=lifespan)
    else:
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

        lifespan_scopes.append(record_scope(scope))
        for mutation in app_input.get("scope_mutations", []):
            if scope.get("type") == mutation["scope_type"]:
                field = mutation["field"]
                before_present = field in scope
                before_value = _safe(scope[field]) if before_present else None
                del scope[field]
                scope_mutation_trace.append(
                    {
                        "scope_type": mutation["scope_type"],
                        "operation": mutation["operation"],
                        "field": field,
                        "before_present": before_present,
                        "before_value": before_value,
                        "after_present": field in scope,
                    }
                )
        await starlette_app(scope, observed_receive, observed_send)

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
            lifecycle_trace_after_actions.append(
                {
                    "action_index": action_index,
                    "operation": action["operation"],
                    "trace": list(lifecycle_trace),
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
    if "scope_mutations" in app_input:
        result["scope_mutation_trace"] = scope_mutation_trace
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }


def _run_starlette_lifespan_runvar_case(case: dict[str, Any]) -> dict[str, Any]:
    import itertools

    import anyio
    import sniffio
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    settings = case["testclient"]
    app_input = case["asgi_app"]
    runvar_input = app_input["runvar"]
    token_source = runvar_input["token_source"]
    runvar = anyio.lowlevel.RunVar(runvar_input["name"])
    tokens = itertools.count(token_source["start"], token_source["step"])
    active_context: dict[str, int | None] = {"value": None}
    startup_samples: list[dict[str, Any]] = []
    shutdown_samples: list[dict[str, Any]] = []
    request_samples: list[dict[str, Any]] = []
    request_results: list[dict[str, Any]] = []
    lifespan_scopes: list[dict[str, Any]] = []
    lifespan_receive_messages: list[dict[str, Any]] = []
    lifespan_send_messages: list[dict[str, Any]] = []
    http_scopes: list[dict[str, Any]] = []
    http_receive_messages: list[dict[str, Any]] = []
    http_send_messages: list[dict[str, Any]] = []
    lifecycle_action_trace: list[dict[str, Any]] = []
    action_errors: list[dict[str, Any]] = []
    lifecycle_trace: list[str] = []

    def current_task() -> Any:
        backend_name = sniffio.current_async_library()
        if backend_name == "asyncio":
            task = asyncio.current_task()
            if task is None:
                raise RuntimeError("TestClient lifespan callback has no asyncio task")
            return task
        if backend_name == "trio":
            import trio.lowlevel

            return trio.lowlevel.current_task()
        raise RuntimeError(f"unsupported TestClient backend {backend_name!r}")

    def identity() -> int:
        try:
            return runvar.get()
        except LookupError:
            token = next(tokens)
            runvar.set(token)
            return token

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        context_index = active_context["value"]
        lifecycle_trace.append("startup")
        startup_samples.append(
            {
                "context_index": context_index,
                "task": current_task(),
                "runvar_value": identity(),
            }
        )
        async with anyio.create_task_group():
            yield
        lifecycle_trace.append("shutdown")
        shutdown_samples.append(
            {
                "context_index": context_index,
                "task": current_task(),
                "runvar_value": identity(),
            }
        )

    async def endpoint(_request: Any) -> JSONResponse:
        return JSONResponse(identity())

    starlette_app = Starlette(
        routes=[
            Route(app_input["route"]["path"], endpoint, methods=[app_input["route"]["method"]])
        ],
        lifespan=lifespan,
    )

    def record_scope(scope: dict[str, Any]) -> dict[str, Any]:
        return {field: _safe(scope.get(field)) for field in app_input["scope_fields"]}

    async def instrumented_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            lifespan_scopes.append(record_scope(scope))
        elif scope["type"] == "http":
            http_scopes.append(record_scope(scope))

        async def observed_receive() -> dict[str, Any]:
            message = await receive()
            destination = (
                lifespan_receive_messages if scope["type"] == "lifespan" else http_receive_messages
            )
            destination.append(_safe(message))
            return message

        async def observed_send(message: dict[str, Any]) -> None:
            destination = (
                lifespan_send_messages if scope["type"] == "lifespan" else http_send_messages
            )
            destination.append(_safe(message))
            await send(message)

        await starlette_app(scope, observed_receive, observed_send)

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
    context_number = 0
    try:
        for action_index, action in enumerate(case["client_actions"]):
            operation = action["operation"]
            try:
                if operation == "enter":
                    active_context["value"] = context_number
                    context_number += 1
                    client.__enter__()
                elif operation == "exit":
                    client.__exit__(None, None, None)
                    active_context["value"] = None
                else:
                    request = action["request"]
                    response = client.request(
                        request["method"],
                        request["url"],
                        headers=_decoded_pairs(request["headers_base64_pairs"]),
                        content=base64.b64decode(request["body_base64"]),
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
                    request_samples.append(
                        {
                            "action_index": action_index,
                            "context_index": active_context["value"],
                            "status_code": response.status_code,
                            "json_value": response.json(),
                        }
                    )
                lifecycle_action_trace.append(
                    {
                        "action_index": action_index,
                        "operation": operation,
                        "trace": list(lifecycle_trace),
                    }
                )
            except Exception as error:
                error_type = type(error)
                action_errors.append(
                    {
                        "action_index": action_index,
                        "operation": operation,
                        "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
                        "message": str(error),
                    }
                )
                break
    finally:
        client.close()

    contexts = sorted(
        {
            sample["context_index"]
            for sample in startup_samples + shutdown_samples
            if sample["context_index"] is not None
        }
    )
    lifecycle_relations: list[dict[str, Any]] = []
    for context_index in contexts:
        startup = next(
            sample for sample in startup_samples if sample["context_index"] == context_index
        )
        shutdown = next(
            sample for sample in shutdown_samples if sample["context_index"] == context_index
        )
        managed_values = [
            sample["json_value"]
            for sample in request_samples
            if sample["context_index"] == context_index
        ]
        lifecycle_relations.append(
            {
                "context_index": context_index,
                "startup_shutdown_same_task": startup["task"] is shutdown["task"],
                "startup_shutdown_same_runvar": (
                    startup["runvar_value"] == shutdown["runvar_value"]
                ),
                "managed_requests_match_startup": [
                    value == startup["runvar_value"] for value in managed_values
                ],
                "managed_requests_share_runvar": (len(set(managed_values)) <= 1),
            }
        )
    outside_values = [
        sample["json_value"] for sample in request_samples if sample["context_index"] is None
    ]
    result = {
        "lifespan_scope": lifespan_scopes[0],
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
        "loop_relations": {"active_lifespan": [], "previous_http_request": []},
        "lifespan_trace_before_actions": [],
        "lifespan_trace_after_actions": lifecycle_action_trace,
        "action_errors": action_errors,
        "runvar_context_observations": {
            "startup_samples": [
                {key: value for key, value in sample.items() if key != "task"}
                for sample in startup_samples
            ],
            "shutdown_samples": [
                {key: value for key, value in sample.items() if key != "task"}
                for sample in shutdown_samples
            ],
            "request_samples": request_samples,
            "lifecycle_relations": lifecycle_relations,
            "reentry_uses_new_task": (
                startup_samples[0]["task"] is not startup_samples[-1]["task"]
                if len(startup_samples) > 1
                else None
            ),
            "outside_runvar_values_are_distinct": len(set(outside_values)) == len(outside_values),
            "lifecycle_trace": lifecycle_trace,
        },
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "lifespan-context", "status": "ok", "value": result}],
    }


def run_testclient_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["asgi_app"]["kind"] in {
        "starlette-lifespan",
        "starlette-router-lifespan",
    }:
        return _run_starlette_lifespan_case(case)
    if case["asgi_app"]["kind"] == "starlette-lifespan-runvar":
        return _run_starlette_lifespan_runvar_case(case)
    if case["asgi_app"]["kind"] in {"starlette-state", "starlette-router-state"}:
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
