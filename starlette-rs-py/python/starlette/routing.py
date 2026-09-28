"""Route declarations for the current Rust-backed ASGI slice."""

from __future__ import annotations

import functools
import inspect
import re
import sys
from collections.abc import Callable, Iterable
from typing import Any

from starlette_rs_py import _core

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.websockets import WebSocket, WebSocketClose

if sys.version_info >= (3, 13):
    from inspect import iscoroutinefunction
else:
    from asyncio import iscoroutinefunction

_PATH_PARAMETER_SEGMENT = re.compile(
    r"^\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?\}$"
)


def _path_parameter_types(path: str) -> dict[str, str]:
    """Record Python value conversions for parameters matched by Rust."""
    parameter_types: dict[str, str] = {}
    for segment in path.split("/"):
        match = _PATH_PARAMETER_SEGMENT.fullmatch(segment)
        if match is not None:
            name, converter = match.groups()
            converter = "str" if converter is None else converter
            if converter in {"str", "int"}:
                parameter_types[name] = converter
    return parameter_types


def _convert_path_params(
    route: Route | WebSocketRoute, captured: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    """Convert Rust's captured strings to the route's declared Python values."""
    return {
        name: int(value) if route._path_parameter_types.get(name) == "int" else value
        for name, value in captured
    }


def _is_async_callable(endpoint: Callable[..., Any]) -> bool:
    """Match Starlette's async-callable detection, including partials."""
    while isinstance(endpoint, functools.partial):
        endpoint = endpoint.func
    return iscoroutinefunction(endpoint) or (
        callable(endpoint) and iscoroutinefunction(endpoint.__call__)
    )


def _is_request_endpoint(endpoint: Callable[..., Any]) -> bool:
    """Match Starlette's distinction between request endpoints and ASGI apps."""
    endpoint_handler = endpoint
    while isinstance(endpoint_handler, functools.partial):
        endpoint_handler = endpoint_handler.func
    return inspect.isfunction(endpoint_handler) or inspect.ismethod(endpoint_handler)


class Route:
    """Declare a static HTTP path and its Python endpoint callable."""

    __slots__ = ("path", "endpoint", "methods", "_path_parameter_types")

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        methods: Iterable[str] | None = None,
    ) -> None:
        if not isinstance(path, str):
            raise TypeError("path must be a string")
        if not callable(endpoint):
            raise TypeError("endpoint must be callable")
        self.path = path
        self._path_parameter_types = _path_parameter_types(path)
        self.endpoint = endpoint
        self.methods = ("GET",) if methods is None else tuple(methods)


class WebSocketRoute:
    """Declare a WebSocket path and its Python or ASGI endpoint."""

    __slots__ = (
        "path",
        "endpoint",
        "name",
        "app",
        "_path_parameter_types",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        name: str | None = None,
        middleware: Iterable[Any] | None = None,
    ) -> None:
        assert path.startswith("/"), "Routed paths must start with '/'"
        self.path = path
        self.endpoint = endpoint
        self.name = (
            getattr(endpoint, "__name__", endpoint.__class__.__name__) if name is None else name
        )
        self._path_parameter_types = _path_parameter_types(path)
        self._route_table = _core.RouteTable()
        self._route_table.add_route(path, ["GET"])

        if _is_request_endpoint(endpoint):

            async def app(
                scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
            ) -> None:
                websocket = WebSocket(scope, receive, send)
                await endpoint(websocket)

            self.app: Callable[..., Any] = app
        else:
            self.app = endpoint

        if middleware is not None:
            for middleware_item in reversed(tuple(middleware)):
                cls, args, kwargs = middleware_item
                self.app = cls(self.app, *args, **kwargs)

    def matches(self, scope: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        if scope.get("type") != "websocket":
            return False, {}
        matched, _route_index, _fallback, captured, _allowed = (
            self._route_table.match_route_with_root_path(
                scope["path"], scope.get("root_path", ""), "GET"
            )
        )
        if matched != "matched":
            return False, {}
        return True, {
            "endpoint": self.endpoint,
            "path_params": {
                **scope.get("path_params", {}),
                **_convert_path_params(self, captured),
            },
        }

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self.app(scope, receive, send)

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        matched, child_scope = self.matches(scope)
        if not matched:
            if scope["type"] == "http":
                await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            elif scope["type"] == "websocket":
                await WebSocketClose()(scope, receive, send)
            return
        scope.update(child_scope)
        await self.handle(scope, receive, send)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, WebSocketRoute)
            and self.path == other.path
            and self.endpoint == other.endpoint
        )

    def __repr__(self) -> str:
        return f"WebSocketRoute(path={self.path!r}, name={self.name!r})"


class Router:
    """Own the Rust route table used by a :class:`Starlette` application."""

    __slots__ = (
        "routes",
        "_route_table",
        "_route_indexes",
        "_websocket_route_table",
        "_websocket_route_indexes",
    )

    def __init__(self, routes: Iterable[Route] = ()) -> None:
        self.routes = list(routes)
        self._route_table = _core.RouteTable()
        self._route_indexes: list[int] = []
        self._websocket_route_table = _core.RouteTable()
        self._websocket_route_indexes: list[int] = []
        for index, route in enumerate(self.routes):
            if isinstance(route, Route):
                self._route_indexes.append(index)
                self._route_table.add_route(route.path, list(route.methods))
            elif isinstance(route, WebSocketRoute):
                self._websocket_route_indexes.append(index)
                self._websocket_route_table.add_route(route.path, ["GET"])
            else:
                raise TypeError("routes must contain Route or WebSocketRoute instances")

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        """Dispatch one HTTP ASGI scope through the Rust route table.

        Async function and method endpoints are awaited on the caller's event
        loop, while synchronous ones run in AnyIO's worker thread. Other
        callables are treated as ASGI apps and receive scope, receive, and send.
        The Rust table owns path and method matching and fallback responses.
        """
        scope.setdefault("router", self)
        if scope.get("type") == "websocket":
            matched, route_index, _fallback, path_params, _allowed_methods = (
                self._websocket_route_table.match_route_with_root_path(
                    scope["path"], scope.get("root_path", ""), "GET"
                )
            )
            if matched != "matched" or route_index is None:
                await WebSocketClose()(scope, receive, send)
                return
            route = self.routes[self._websocket_route_indexes[route_index]]
            if not isinstance(route, WebSocketRoute):
                raise RuntimeError("Rust returned a non-WebSocket route index")
            scope["endpoint"] = route.endpoint
            scope["path_params"] = {
                **scope.get("path_params", {}),
                **_convert_path_params(route, path_params),
            }
            await route.handle(scope, receive, send)
            return
        if scope.get("type") != "http":
            raise NotImplementedError(
                "only HTTP and WebSocket Router scopes are supported in this slice"
            )

        matched, route_index, fallback, path_params, _allowed_methods = (
            self._route_table.match_route(scope["path"], scope["method"])
        )
        if matched in {"matched", "method_not_allowed"} and route_index is not None:
            route = self.routes[self._route_indexes[route_index]]
            if not isinstance(route, Route):
                raise RuntimeError("Rust returned a non-HTTP route index")
            scope["endpoint"] = route.endpoint
            scope["path_params"] = {
                **scope.get("path_params", {}),
                **_convert_path_params(route, path_params),
            }

        if fallback is not None:
            response = Response._from_native(fallback)
            await response(scope, receive, send)
            return
        if matched != "matched" or route_index is None:
            raise RuntimeError(f"Rust returned an incomplete route decision: {matched!r}")

        route = self.routes[self._route_indexes[route_index]]
        if not isinstance(route, Route):
            raise RuntimeError("Rust returned a non-HTTP route index")
        endpoint = route.endpoint
        if not _is_request_endpoint(endpoint):
            await endpoint(scope, receive, send)
            return

        request = Request(scope, receive)
        if _is_async_callable(endpoint):
            response = await endpoint(request)
        else:
            response = await run_in_threadpool(endpoint, request)
        if not isinstance(response, Response):
            raise TypeError("route endpoint must return a starlette.responses.Response")
        await response(scope, receive, send)
