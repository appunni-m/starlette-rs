"""Response wrappers whose construction and ASGI messages are owned by Rust."""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from typing import Any

from starlette_rs_py import _core

from starlette.datastructures import URL

_ContentChunk = str | bytes | memoryview
_ContentStream = Iterable[_ContentChunk] | AsyncIterable[_ContentChunk]


class Response:
    """Wrap a Rust response and await ASGI ``send`` on the caller's loop."""

    __slots__ = ("_inner", "background")

    def __init__(
        self,
        content: str | bytes = "",
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        self._inner = _core.Response(content, status_code, headers, media_type)
        self.background = background

    @classmethod
    def _from_native(cls, inner: Any) -> Response:
        """Wrap a Rust-created fallback response without rebuilding it in Python."""
        response = cls.__new__(cls)
        response._inner = inner
        response.background = None
        return response

    def set_cookie(self, key: str, value: str) -> None:
        """Append a cookie header through the Rust response implementation."""
        self._inner.set_cookie(key, value)

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self._inner.asgi_call(scope, receive, send, self.background)


class PlainTextResponse(Response):
    """A response with Starlette's plain-text media type."""

    __slots__ = ()

    def __init__(
        self,
        content: str | bytes = "",
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str = "text/plain",
        background: Any = None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)


class StreamingResponse(Response):
    """Send iterable content as a streamed ASGI response."""

    __slots__ = ()
    charset = "utf-8"
    media_type = None

    def __init__(
        self,
        content: _ContentStream,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        self.background = background
        self._inner = _core.StreamingResponse(
            content, status_code, headers, media_type, self.charset
        )

    def set_cookie(self, key: str, value: str) -> None:
        """Append a cookie header before the stream begins."""
        self._inner.set_cookie(key, value)

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self._inner.asgi_call(scope, receive, send, self.background)


class RedirectResponse(Response):
    """An empty response that redirects to a quoted URL."""

    __slots__ = ()

    def __init__(
        self,
        url: str | URL,
        status_code: int = 307,
        headers: Mapping[str, str] | None = None,
        background: Any = None,
    ) -> None:
        self._inner = _core.Response.redirect(str(url), status_code, headers)
        self.background = background


class JSONResponse(Response):
    """Encode a Python JSON value and frame it through the Rust response API."""

    __slots__ = ()
    media_type = "application/json"

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        body = self.render(content)
        self._inner = _core.Response.json(body, status_code, headers, media_type)
        self.background = background

    def render(self, content: Any) -> bytes:
        """Serialize JSON with Starlette's Python-value compatibility rules."""
        return _core.Response.render_json(content)
