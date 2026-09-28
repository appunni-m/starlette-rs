"""Rust-backed HTTP request body size limiting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette_rs_py import _core

from starlette.exceptions import HTTPException

MAX_BODY_SIZE_SCOPE_KEY = "starlette.max_body_size"
_BODY_LIMIT_RESPONDER_SCOPE_KEY = "starlette._body_limit_responder"


class _RequestBodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Content Too Large")


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
