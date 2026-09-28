"""Authentication ASGI middleware delegated to the native runtime."""

from __future__ import annotations

from collections.abc import Callable

from starlette_rs_py import _core

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    UnauthenticatedUser,
)
from starlette.requests import HTTPConnection
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send


class AuthenticationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        backend: AuthenticationBackend,
        on_error: Callable[[HTTPConnection, AuthenticationError], Response] | None = None,
    ) -> None:
        self.app = app
        self.backend = backend
        self.on_error: Callable[[HTTPConnection, AuthenticationError], Response]
        self.on_error, self._runtime = _core.authentication_middleware_initialize(
            app,
            backend,
            on_error,
            self.default_on_error,
            HTTPConnection,
            AuthenticationError,
            AuthCredentials,
            UnauthenticatedUser,
        )

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        await _core.authentication_middleware_invoke(self._runtime, scope, receive, send)

    @staticmethod
    def default_on_error(conn: HTTPConnection, exc: Exception) -> Response:
        return _core.authentication_default_error(conn, exc, PlainTextResponse)
