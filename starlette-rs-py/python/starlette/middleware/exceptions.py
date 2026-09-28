"""Exception middleware facade over the Rust handler-selection runtime."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from starlette_rs_py import _core

from starlette.exceptions import HTTPException, WebSocketException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.websockets import WebSocket


class ExceptionMiddleware:
    """Dispatch handled exceptions through Rust-selected Python callbacks."""

    def __init__(
        self,
        app: Callable[..., Any],
        handlers: Mapping[Any, Callable[..., Any]] | None = None,
        debug: bool = False,
    ) -> None:
        self.app = app
        self.debug = debug
        self._runtime = _core.ExceptionMiddlewareRuntime(
            {
                "app": app,
                "handlers": handlers,
                "http_exception_type": HTTPException,
                "websocket_exception_type": WebSocketException,
                "http_builtin_handler": self.http_exception,
                "websocket_builtin_handler": self.websocket_exception,
                "response_type": Response,
                "plain_text_response_type": PlainTextResponse,
            }
        )

    def add_exception_handler(
        self,
        exc_class_or_status_code: int | type[Exception],
        handler: Callable[..., Any],
    ) -> None:
        self._runtime.add_exception_handler(exc_class_or_status_code, handler)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(scope, receive, send)

    async def http_exception(self, request: Request, exception: Exception) -> Response:
        return self._runtime.http_exception(request, exception)

    async def websocket_exception(
        self,
        websocket: WebSocket,
        exception: Exception,
    ) -> None:
        await self._runtime.websocket_exception(websocket, exception)
