"""Rust-backed ``BaseHTTPMiddleware`` compatibility facade."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette_rs_py import _core

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]
DispatchFunction = Callable[[Request, RequestResponseEndpoint], Awaitable[Response]]


class _StreamingResponse(Response):
    """Expose the Rust-owned stream returned by ``call_next`` as a Response."""

    def __init__(self, runtime: Any) -> None:
        self._base_http_runtime = runtime
        self.headers = runtime.headers
        self.body_iterator = runtime.body_iterator
        self.background = None
        self.info = runtime.info
        self.media_type = None

    @property
    def status_code(self) -> int:
        return self._base_http_runtime.status_code

    @status_code.setter
    def status_code(self, value: int) -> None:
        self._base_http_runtime.status_code = value

    @property
    def raw_headers(self) -> list[tuple[bytes, bytes]]:
        return self._base_http_runtime.raw_headers

    @raw_headers.setter
    def raw_headers(self, value: list[tuple[bytes, bytes]]) -> None:
        self._base_http_runtime.raw_headers = value

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._base_http_runtime.asgi_call(scope, receive, send)


class BaseHTTPMiddleware:
    """Dispatch HTTP requests with a Request and a streaming ``call_next``."""

    def __init__(self, app: Callable[..., Any], dispatch: DispatchFunction | None = None) -> None:
        self.app = app
        self.dispatch_func = _core._base_http_select_dispatch(self, dispatch)
        self._runtime = _core.BaseHTTPMiddlewareRuntime()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._runtime(self.app, self.dispatch_func, scope, receive, send)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        return await _core._base_http_default_dispatch()
