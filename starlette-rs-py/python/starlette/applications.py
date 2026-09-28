"""Starlette application facade backed by the Rust ASGI runtime."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, ParamSpec, TypeVar

from starlette.datastructures import State, URLPath
from starlette.middleware import Middleware, _MiddlewareFactory
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute, Router
from starlette_rs_py import _core

AppType = TypeVar("AppType", bound="Starlette")
P = ParamSpec("P")


class Starlette:
    """Create an application whose middleware and dispatch decisions run in Rust."""

    def __init__(
        self: AppType,
        debug: bool = False,
        routes: Sequence[BaseRoute] | None = None,
        middleware: Sequence[Middleware] | None = None,
        exception_handlers: Mapping[Any, Callable[..., Any]] | None = None,
        lifespan: Callable[[AppType], Any] | None = None,
        *,
        max_body_size: int | None = None,
    ) -> None:
        self.debug = debug
        self.state = State()
        self.router = Router(routes, lifespan=lifespan)
        self.max_body_size = max_body_size
        self._runtime = _core.StarletteRuntime(
            self,
            middleware,
            exception_handlers,
            Middleware,
            ServerErrorMiddleware,
            ExceptionMiddleware,
        )

    def build_middleware_stack(self) -> Any:
        return self._runtime.build_middleware_stack()

    @property
    def routes(self) -> list[BaseRoute]:
        return self.router.routes

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return self.router.url_path_for(name, **path_params)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(scope, receive, send)

    def mount(self, path: str, app: Callable[..., Any], name: str | None = None) -> None:
        self.router.mount(path, app=app, name=name)

    def host(self, host: str, app: Callable[..., Any], name: str | None = None) -> None:
        self.router.host(host, app=app, name=name)

    def add_middleware(
        self,
        middleware_class: _MiddlewareFactory[P],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        self._runtime.add_middleware(middleware_class, args, kwargs)

    def add_exception_handler(
        self,
        exc_class_or_status_code: int | type[Exception],
        handler: Callable[..., Any],
    ) -> None:
        self._runtime.add_exception_handler(exc_class_or_status_code, handler)

    def add_route(
        self,
        path: str,
        route: Callable[[Request], Awaitable[Response] | Response],
        methods: list[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        self.router.add_route(
            path,
            route,
            methods=methods,
            name=name,
            include_in_schema=include_in_schema,
        )
