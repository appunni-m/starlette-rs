"""Server-error middleware facade backed by Rust's ASGI continuation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette_rs_py import _core

from starlette.requests import Request
from starlette.responses import Response


class ServerErrorMiddleware:
    """Render a Rust-selected 500 response and preserve the application error."""

    def __init__(
        self,
        app: Callable[..., Any],
        handler: Callable[..., Any] | None = None,
        debug: bool = False,
    ) -> None:
        self.app = app
        self.handler = handler
        self.debug = debug
        self._runtime = _core._new_server_error_middleware_runtime(
            Request,
            Response,
        )

    @classmethod
    def _from_rust_policy(
        cls,
        app: Callable[..., Any],
        exception_handlers: list[Callable[..., Any]],
        policy: Any,
    ) -> ServerErrorMiddleware:
        """Use the application's shared callback list and Rust error policy."""
        middleware = cls.__new__(cls)
        middleware.app = app
        middleware.handler = None
        middleware.debug = False
        middleware._runtime = _core._server_error_middleware_runtime_with_policy(
            exception_handlers,
            policy,
            Request,
            Response,
        )
        return middleware

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(self, scope, receive, send)
