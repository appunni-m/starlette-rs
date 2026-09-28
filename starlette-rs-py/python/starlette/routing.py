"""Route declarations and ASGI dispatch backed by the native route table."""

from __future__ import annotations

import contextlib
import functools
import re
from collections.abc import Callable, Iterable, Sequence
from enum import Enum
from re import Pattern
from typing import Any

from starlette_rs_py import _core

from starlette.concurrency import run_in_threadpool
from starlette.convertors import _BUILTIN_CONVERTOR_TYPES, CONVERTOR_TYPES, Convertor
from starlette.datastructures import URL, URLPath
from starlette.exceptions import HTTPException, StarletteDeprecationWarning
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.websockets import WebSocket, WebSocketClose


class NoMatchFound(Exception):
    """Raised when a named route cannot be found."""

    def __init__(self, name: str, path_params: dict[str, Any]) -> None:
        super().__init__(_core.no_match_message(name, path_params))


class Match(Enum):
    """Route matching result, ordered from no match to full match."""

    NONE = 0
    PARTIAL = 1
    FULL = 2


PARAM_REGEX = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?}")


def compile_path(
    path: str,
) -> tuple[Pattern[str], str, dict[str, Convertor[Any]]]:
    """Compile a Starlette path template into a regex and parameter map."""
    return _core.compile_route_path(path, PARAM_REGEX, CONVERTOR_TYPES)


def _get_route_path(scope: dict[str, Any]) -> str:
    return _core.route_path(scope)


def _format_path_params(
    route: BaseRoute, path_params: dict[str, Any], *, partial: bool = False
) -> tuple[str, dict[str, Any]]:
    """Format already selected path parameters through Rust or custom callbacks."""

    return _core.route_format_path_params(route, path_params, partial)


def _get_name(endpoint: Callable[..., Any]) -> str:
    return _core.route_endpoint_name(endpoint)


def _apply_middleware(
    app: Callable[..., Any], middleware: Sequence[Any] | None, max_body_size: int | None = None
) -> Callable[..., Any]:
    return _core.apply_route_middleware(app, middleware, max_body_size)


class _AsyncLiftContextManager(contextlib.AbstractAsyncContextManager[Any]):
    def __init__(self, cm: Any) -> None:
        self._cm = cm

    async def __aenter__(self) -> Any:
        return self._cm.__enter__()

    async def __aexit__(self, *exc_info: Any) -> Any:
        return self._cm.__exit__(*exc_info)


class _DefaultLifespan:
    def __init__(self, router: Router) -> None:
        self._router = router
        self._runtime = _core.default_lifespan_runtime(router)

    async def __aenter__(self) -> None:
        return await _core.default_lifespan_transition(self._runtime)

    async def __aexit__(self, *exc_info: Any) -> None:
        return await _core.default_lifespan_transition(self._runtime)

    def __call__(self, app: Any) -> _DefaultLifespan:
        return _core.default_lifespan_context(self._runtime, app, self)


def _default_lifespan_factory(router: Router) -> _DefaultLifespan:
    return _DefaultLifespan(router)


def _async_generator_lifespan_factory(lifespan: Callable[..., Any]) -> Callable[..., Any]:
    return contextlib.asynccontextmanager(lifespan)


def _generator_lifespan_factory(lifespan: Callable[..., Any]) -> Callable[..., Any]:
    context_manager = contextlib.contextmanager(lifespan)

    @functools.wraps(context_manager)
    def wrapper(app: Any) -> _AsyncLiftContextManager:
        return _AsyncLiftContextManager(context_manager(app))

    return wrapper


def _request_response(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    async def app(
        scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.request_response(
            {
                "endpoint": endpoint,
                "scope": scope,
                "receive": receive,
                "send": send,
                "request_type": Request,
                "http_exception_type": HTTPException,
                "run_in_threadpool": run_in_threadpool,
            }
        )

    return app


def _websocket_endpoint(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    async def app(
        scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await endpoint(WebSocket(scope, receive, send))

    return app


class BaseRoute:
    """Common interface for a route that can be mounted in a Router."""

    path: str
    name: str | None
    param_convertors: dict[str, Convertor[Any]]
    _uses_custom_convertors: bool

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        return _core.base_route_unimplemented("matches")

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return _core.base_route_unimplemented("url_path_for")

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.base_route_unimplemented_async("handle")

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.base_route_call(self, scope, receive, send, PlainTextResponse, WebSocketClose)


class Route(BaseRoute):
    """Declare an HTTP path and its request or ASGI endpoint."""

    __slots__ = (
        "path",
        "endpoint",
        "name",
        "methods",
        "include_in_schema",
        "app",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: Iterable[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        (
            self.path,
            self.endpoint,
            self.name,
            self.methods,
            self.include_in_schema,
            _base_app,
            self.app,
            self.path_regex,
            self.path_format,
            self.param_convertors,
            self._uses_custom_convertors,
            self._route_table,
        ) = _core.initialize_route(
            "http",
            path,
            endpoint,
            methods,
            name,
            include_in_schema,
            middleware,
            max_body_size,
            None,
            PARAM_REGEX,
            CONVERTOR_TYPES,
            _BUILTIN_CONVERTOR_TYPES,
            _core.RouteTable,
            _request_response,
            _websocket_endpoint,
            Router,
        )

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        return _core.route_matches(self, scope, Match, "http", _BUILTIN_CONVERTOR_TYPES)

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.route_handle(
            {
                "route": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "route_kind": "http",
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
            }
        )

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return _core.route_url_path_for(self, name, path_params, NoMatchFound, URLPath, "http")

    def __eq__(self, other: object) -> bool:
        return _core.route_equal(self, other, Route, "http")

    def __repr__(self) -> str:
        return _core.route_repr(self, "http")


class WebSocketRoute(BaseRoute):
    """Declare a WebSocket path and its Python or ASGI endpoint."""

    __slots__ = (
        "path",
        "endpoint",
        "name",
        "app",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        name: str | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> None:
        (
            self.path,
            self.endpoint,
            self.name,
            _methods,
            _include_in_schema,
            _base_app,
            self.app,
            self.path_regex,
            self.path_format,
            self.param_convertors,
            self._uses_custom_convertors,
            self._route_table,
        ) = _core.initialize_route(
            "websocket",
            path,
            endpoint,
            None,
            name,
            True,
            middleware,
            None,
            None,
            PARAM_REGEX,
            CONVERTOR_TYPES,
            _BUILTIN_CONVERTOR_TYPES,
            _core.RouteTable,
            _request_response,
            _websocket_endpoint,
            Router,
        )

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        return _core.route_matches(self, scope, Match, "websocket", _BUILTIN_CONVERTOR_TYPES)

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.route_handle(
            {
                "route": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "route_kind": "websocket",
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
            }
        )

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return _core.route_url_path_for(self, name, path_params, NoMatchFound, URLPath, "websocket")

    def __eq__(self, other: object) -> bool:
        return _core.route_equal(self, other, WebSocketRoute, "websocket")

    def __repr__(self) -> str:
        return _core.route_repr(self, "websocket")


class Mount(BaseRoute):
    """Mount an ASGI application or nested routes below a path prefix."""

    __slots__ = (
        "path",
        "_base_app",
        "app",
        "name",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        app: Callable[..., Any] | None = None,
        routes: Sequence[BaseRoute] | None = None,
        name: str | None = None,
        *,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        (
            self.path,
            _endpoint,
            self.name,
            _methods,
            _include_in_schema,
            self._base_app,
            self.app,
            self.path_regex,
            self.path_format,
            self.param_convertors,
            self._uses_custom_convertors,
            self._route_table,
        ) = _core.initialize_route(
            "mount",
            path,
            app,
            None,
            name,
            True,
            middleware,
            max_body_size,
            routes,
            PARAM_REGEX,
            CONVERTOR_TYPES,
            _BUILTIN_CONVERTOR_TYPES,
            _core.RouteTable,
            _request_response,
            _websocket_endpoint,
            Router,
        )

    @property
    def routes(self) -> list[BaseRoute]:
        return getattr(self._base_app, "routes", [])

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        return _core.route_matches(self, scope, Match, "mount", _BUILTIN_CONVERTOR_TYPES)

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.route_handle(
            {
                "route": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "route_kind": "mount",
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
            }
        )

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return _core.mount_url_path_for(self, name, path_params, NoMatchFound, URLPath)

    def __eq__(self, other: object) -> bool:
        return _core.route_equal(self, other, Mount, "mount")

    def __repr__(self) -> str:
        return _core.route_repr(self, "mount")


class Host(BaseRoute):
    """Route requests by matching their Host header."""

    __slots__ = (
        "host",
        "app",
        "name",
        "host_regex",
        "host_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(self, host: str, app: Callable[..., Any], name: str | None = None) -> None:
        (
            self.host,
            _endpoint,
            self.name,
            _methods,
            _include_in_schema,
            _base_app,
            self.app,
            self.host_regex,
            self.host_format,
            self.param_convertors,
            self._uses_custom_convertors,
            self._route_table,
        ) = _core.initialize_route(
            "host",
            host,
            app,
            None,
            name,
            True,
            None,
            None,
            None,
            PARAM_REGEX,
            CONVERTOR_TYPES,
            _BUILTIN_CONVERTOR_TYPES,
            _core.RouteTable,
            _request_response,
            _websocket_endpoint,
            Router,
        )

    @property
    def routes(self) -> list[BaseRoute]:
        return _core.route_children(self.app)

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        return _core.route_matches(self, scope, Match, "host", _BUILTIN_CONVERTOR_TYPES)

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.route_handle(
            {
                "route": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "route_kind": "host",
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
            }
        )

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return _core.host_url_path_for(self, name, path_params, NoMatchFound, URLPath)

    def __eq__(self, other: object) -> bool:
        return _core.route_equal(self, other, Host, "host")

    def __repr__(self) -> str:
        return _core.route_repr(self, "host")


class Router:
    """Dispatch ordered HTTP and WebSocket routes through the Rust runtime."""

    __slots__ = (
        "routes",
        "redirect_slashes",
        "default",
        "_default",
        "_runtime",
        "lifespan_context",
        "middleware_stack",
    )

    def __init__(
        self,
        routes: Sequence[BaseRoute] | None = None,
        redirect_slashes: bool = True,
        default: Callable[..., Any] | None = None,
        lifespan: Callable[..., Any] | None = None,
        *,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        self.redirect_slashes = redirect_slashes
        self._default = default
        (
            self.routes,
            self.default,
            self.lifespan_context,
            self._runtime,
            self.middleware_stack,
        ) = _core.initialize_router_state(
            self,
            routes,
            default,
            lifespan,
            middleware,
            max_body_size,
            _core.RouterRuntime,
            Route,
            WebSocketRoute,
            Mount,
            Host,
            _default_lifespan_factory,
            _async_generator_lifespan_factory,
            _generator_lifespan_factory,
            StarletteDeprecationWarning,
        )

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self.middleware_stack(scope, receive, send)

    async def app(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self._runtime.dispatch(
            {
                "routes": self.routes,
                "router": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "default": self._default,
                "redirect_slashes": self.redirect_slashes,
                "url_type": URL,
                "redirect_response_type": RedirectResponse,
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
                "websocket_close_type": WebSocketClose,
                "exception_handler": None,
            }
        )

    async def _dispatch_starlette(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
        exception_handler: Callable[..., Any],
    ) -> None:
        await self._runtime.dispatch(
            {
                "routes": self.routes,
                "router": self,
                "scope": scope,
                "receive": receive,
                "send": send,
                "default": None,
                "redirect_slashes": self.redirect_slashes,
                "url_type": URL,
                "redirect_response_type": RedirectResponse,
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
                "websocket_close_type": WebSocketClose,
                "exception_handler": exception_handler,
            }
        )

    async def not_found(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self._runtime.not_found(
            {
                "scope": scope,
                "receive": receive,
                "send": send,
                "http_exception_type": HTTPException,
                "plain_text_response_type": PlainTextResponse,
                "websocket_close_type": WebSocketClose,
            }
        )

    async def lifespan(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await _core.router_lifespan(self.lifespan_context, scope, receive, send)

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return self._runtime.url_path_for(self.routes, name, path_params, NoMatchFound)

    def mount(self, path: str, app: Callable[..., Any], name: str | None = None) -> None:
        _core.router_add_mount(self.routes, Mount, path, app, name)

    def host(self, host: str, app: Callable[..., Any], name: str | None = None) -> None:
        _core.router_add_host(self.routes, Host, host, app, name)

    def add_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        methods: Iterable[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        _core.router_add_route(self.routes, Route, path, endpoint, methods, name, include_in_schema)

    def add_websocket_route(
        self, path: str, endpoint: Callable[..., Any], name: str | None = None
    ) -> None:
        _core.router_add_websocket_route(self.routes, WebSocketRoute, path, endpoint, name)

    def __eq__(self, other: object) -> bool:
        return _core.route_equal(self, other, Router, "router")
