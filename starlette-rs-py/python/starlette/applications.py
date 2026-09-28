"""Starlette application compatibility for the currently implemented slice."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import URLPath
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import (
    Match,
    Mount,
    Route,
    Router,
    WebSocketRoute,
    _is_async_callable,
)
from starlette_rs_py import _core


class Starlette:
    """A partial Starlette application backed by Rust routing and responses.

    This slice supports HTTP routes, HTTP and server-error handlers, debug
    traceback responses, user ASGI middleware, and successful async-context
    lifespans, and direct ASGI WebSocket route dispatch.
    """

    def __init__(
        self,
        debug: bool = False,
        routes: Sequence[Route | WebSocketRoute | Mount] | None = None,
        middleware: Sequence[Any] | None = None,
        exception_handlers: Mapping[Any, Callable[..., Any]] | None = None,
        lifespan: Callable[[Starlette], Any] | None = None,
        *,
        max_body_size: int | None = None,
    ) -> None:
        if max_body_size is not None:
            raise NotImplementedError("only default Starlette options are supported in this slice")

        self.debug = debug
        self.routes = list(routes or ())
        self.user_middleware = list(middleware or ())
        self.lifespan = lifespan
        self.exception_handlers = {} if exception_handlers is None else dict(exception_handlers)
        self.router = Router(self.routes)
        self._route_table = self.router._route_table
        handler_callbacks: list[Callable[..., Any]] = []
        server_error_handler_indexes: list[int] = []
        status_bindings: list[tuple[str, int]] = []
        class_bindings: list[tuple[int, int]] = []
        for key, handler in self.exception_handlers.items():
            handler_index = len(handler_callbacks)
            handler_callbacks.append(handler)
            if isinstance(key, int):
                if int(key) == 500:
                    server_error_handler_indexes.append(handler_index)
                else:
                    status_bindings.append((str(int(key)), handler_index))
            elif key is Exception:
                server_error_handler_indexes.append(handler_index)
            elif isinstance(key, type) and issubclass(key, HTTPException):
                class_bindings.append((id(key), handler_index))
        self._exception_handlers = handler_callbacks
        self._server_error_handler_indexes = server_error_handler_indexes
        self._exception_handler_table = _core.ExceptionHandlerTable(
            status_bindings,
            class_bindings,
        )
        self.middleware_stack: Callable[..., Any] | None = None

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        return self.router.url_path_for(name, **path_params)

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        """Dispatch one ASGI scope through user middleware on its event loop."""
        scope["app"] = self
        if self.middleware_stack is None:
            self.middleware_stack = self._build_middleware_stack()
        await self.middleware_stack(scope, receive, send)

    def _build_middleware_stack(self) -> Callable[..., Any]:
        app: Callable[..., Any] = self._dispatch
        for middleware in reversed(self.user_middleware):
            if not isinstance(middleware, Middleware):
                raise TypeError("middleware entries must be starlette.middleware.Middleware")
            app = middleware.cls(app, *middleware.args, **middleware.kwargs)
        policy = _core.ServerErrorPolicy(self.debug)
        for handler_index in self._server_error_handler_indexes:
            policy.register_handler(handler_index)
        return ServerErrorMiddleware._from_rust_policy(
            app,
            self._exception_handlers,
            policy,
        )

    async def _dispatch(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        """Handle the ASGI scope after middleware has run."""
        scope_action = _core.scope_action(scope.get("type", ""))
        if scope_action == "lifespan":
            await self._run_lifespan(receive, send)
            return
        if scope_action == "websocket":
            await self.router(scope, receive, send)
            return
        if scope_action != "http":
            raise NotImplementedError(f"ASGI scope action {scope_action!r} is outside this slice")

        await self._dispatch_http(scope, receive, send)

    async def _dispatch_http(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        """Dispatch an HTTP scope to its matched Python endpoint."""
        scope.setdefault("router", self.router)
        match, route, child_scope = self.router._select_route(scope)
        if match == Match.NONE or route is None:
            await self._dispatch_http_exception(scope, receive, send, HTTPException(404))
            return

        scope.update(child_scope)
        try:
            response_started = False

            async def send_with_response_state(message: dict[str, Any]) -> None:
                nonlocal response_started
                if message.get("type") == "http.response.start":
                    response_started = True
                await send(message)

            await route.handle(scope, receive, send_with_response_state)
        except HTTPException as exc:
            if response_started:
                raise RuntimeError(
                    "Caught handled exception, but response already started."
                ) from exc
            await self._dispatch_http_exception(scope, receive, send, exc)

    async def _dispatch_http_exception(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
        exception: HTTPException,
    ) -> None:
        request = Request(scope, receive)
        handler_index = self._select_http_exception_handler(exception)
        response = (
            await self._call_exception_handler(handler_index, request, exception)
            if handler_index is not None
            else _exception_response(exception)
        )
        if response is None:
            return
        if not isinstance(response, Response):
            raise TypeError("exception handler must return a starlette.responses.Response")
        await response(scope, receive, send)

    def _select_http_exception_handler(self, exception: HTTPException) -> int | None:
        """Resolve an HTTPException handler through the Rust-owned selector."""
        status_code = exception.status_code
        status_key = str(int(status_code)) if isinstance(status_code, int) else None
        exception_mro = [id(exception_class) for exception_class in type(exception).__mro__]
        return self._exception_handler_table.select(status_key, exception_mro)

    async def _call_exception_handler(
        self, handler_index: int, request: Request, exception: HTTPException
    ) -> Any:
        """Invoke an input-selected Python handler on its required runtime."""
        handler = self._exception_handlers[handler_index]
        if _is_async_callable(handler):
            return await handler(request, exception)
        return await run_in_threadpool(handler, request, exception)

    async def _exception_response(self, request: Request, exception: HTTPException) -> Any:
        handler_index = self._select_http_exception_handler(exception)
        if handler_index is None:
            return _exception_response(exception)
        return await self._call_exception_handler(handler_index, request, exception)

    async def _run_lifespan(self, receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        """Run a successful lifespan session using the host event loop."""
        state = _core.LifespanState()

        startup_message = await receive()
        action = state.startup_received(startup_message.get("type", ""))
        context = self._make_lifespan_context()
        if action != "enter_context":
            raise RuntimeError(f"unexpected Rust lifespan action: {action!r}")
        await context.__aenter__()

        action = state.context_entered()
        await send(_core.lifespan_message(action))

        shutdown_message = await receive()
        action = state.shutdown_received(shutdown_message.get("type", ""))
        if action != "exit_context":
            raise RuntimeError(f"unexpected Rust lifespan action: {action!r}")
        await context.__aexit__(None, None, None)

        action = state.context_exited()
        await send(_core.lifespan_message(action))

    def _make_lifespan_context(self) -> Any:
        if self.lifespan is None:
            return _empty_lifespan(self)
        return self.lifespan(self)


def _exception_response(exception: HTTPException) -> Response:
    """Build a default HTTPException response through the Rust response API."""
    headers = [] if exception.headers is None else list(exception.headers.items())
    native = _core._http_exception_response(exception.status_code, exception.detail, headers)
    return Response._from_native(native)


class _empty_lifespan:
    """Small async context manager used when no lifespan callback is supplied."""

    def __init__(self, app: Starlette) -> None:
        self.app = app

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        return False
