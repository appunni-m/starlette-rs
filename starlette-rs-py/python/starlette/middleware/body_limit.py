"""Rust-backed HTTP request body size limiting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette_rs_py import _core

from starlette.exceptions import HTTPException

MAX_BODY_SIZE_SCOPE_KEY = _core.MAX_BODY_SIZE_SCOPE_KEY
_BODY_LIMIT_RESPONDER_SCOPE_KEY = _core.BODY_LIMIT_RESPONDER_SCOPE_KEY


# Rust uses these Python marker types to preserve exception identity at the boundary.
class _RequestBodyTooLarge(HTTPException):
    pass


class _RequestBodyLimitResponseSent(Exception):
    pass


RequestBodyLimitResponder = _core.RequestBodyLimitResponder


class RequestBodyLimitMiddleware:
    """Limit the total size of an HTTP request body."""

    def __init__(self, app: Callable[..., Any], max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size
        self._runtime = _core.RequestBodyLimitMiddlewareRuntime()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(self.app, self.max_body_size, scope, receive, send)
