"""Rust-backed adapter for synchronous WSGI applications."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette_rs_py import _core

from starlette.exceptions import StarletteDeprecationWarning

_core._warn_wsgi_deprecated(StarletteDeprecationWarning)


def build_environ(scope: dict[str, Any], body: bytes) -> dict[str, Any]:
    """Build a WSGI environ mapping from an ASGI HTTP scope and request body."""
    return _core._build_wsgi_environ(scope, body)


class WSGIMiddleware:
    """Adapt a synchronous WSGI application to the ASGI HTTP protocol."""

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await _core._wsgi_middleware_call(self.app, scope, receive, send)
