"""Response wrappers whose construction and ASGI messages are owned by Rust."""

from __future__ import annotations

import os
from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, Literal

from starlette_rs_py import _core

from starlette.datastructures import URL, MutableHeaders

_ContentChunk = str | bytes | memoryview
_ContentStream = Iterable[_ContentChunk] | AsyncIterable[_ContentChunk]


class Response:
    """Wrap a Rust response and await ASGI ``send`` on the caller's loop."""

    __slots__ = ("__dict__", "_inner", "background", "body", "status_code")
    media_type = None
    charset = "utf-8"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        self.status_code = status_code
        self.media_type = _core.Response.media_type_or(media_type, self.media_type)
        self.background = background
        self.body = self.render(content)
        self._inner = _core.Response(self.body, status_code, headers, self.media_type)

    @classmethod
    def _from_native(cls, inner: Any) -> Response:
        """Wrap a Rust-created fallback response without rebuilding it in Python."""
        response = cls.__new__(cls)
        response._inner = inner
        response.background = None
        response.body = inner.body
        response.status_code = inner.status_code
        return response

    def render(self, content: Any) -> bytes | memoryview:
        """Render content using Rust's default policy.

        Subclasses may override this method with Python code; construction
        invokes that override before handing the result to the Rust response.
        """
        return _core.Response.render_content(content, self.charset)

    @property
    def raw_headers(self) -> list[tuple[bytes, bytes]]:
        """Return the response's mutable raw header list."""
        return self._inner.raw_headers

    @raw_headers.setter
    def raw_headers(self, value: list[tuple[bytes, bytes]]) -> None:
        self._inner.raw_headers = value

    @property
    def headers(self) -> MutableHeaders:
        """Return the Rust-cached mutable header view."""
        return self._inner.headers

    def _sync_raw_headers(self) -> None:
        self._inner._header_replace_raw(self.raw_headers)

    def _refresh_raw_headers(self) -> None:
        self._inner._header_refresh_raw()

    def set_cookie(
        self,
        key: str,
        value: str = "",
        max_age: int | None = None,
        expires: datetime | str | int | None = None,
        path: str | None = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Literal["lax", "strict", "none"] | None = "lax",
        partitioned: bool = False,
    ) -> None:
        """Append a cookie header through the Rust response implementation."""
        self._sync_raw_headers()
        self._inner.set_cookie(
            key, value, max_age, expires, path, domain, secure, httponly, samesite, partitioned
        )
        self._refresh_raw_headers()

    def delete_cookie(
        self,
        key: str,
        path: str = "/",
        domain: str | None = None,
        secure: bool = False,
        httponly: bool = False,
        samesite: Literal["lax", "strict", "none"] | None = "lax",
    ) -> None:
        """Delete a cookie through the Rust response implementation."""
        self._sync_raw_headers()
        self._inner.delete_cookie(key, path, domain, secure, httponly, samesite)
        self._refresh_raw_headers()

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        self._sync_raw_headers()
        await self._inner.asgi_call(scope, receive, send, self.background, self.body)


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


class HTMLResponse(Response):
    """A response with Starlette's HTML media type."""

    __slots__ = ()
    media_type = "text/html"


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

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        self._sync_raw_headers()
        await self._inner.asgi_call(scope, receive, send, self.background)


class FileResponse(Response):
    """Stream a file using the Rust-owned response and range implementation."""

    chunk_size = 64 * 1024
    max_ranges = 100

    def __init__(
        self,
        path: str | os.PathLike[str],
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
        filename: str | None = None,
        stat_result: os.stat_result | None = None,
        content_disposition_type: str = "attachment",
    ) -> None:
        self.path = path
        self.status_code = status_code
        self.filename = filename
        self.background = background
        self.stat_result = stat_result
        self._inner = _core.FileResponse(
            path,
            status_code,
            headers,
            media_type,
            filename,
            stat_result,
            content_disposition_type,
            self.chunk_size,
            self.max_ranges,
        )
        self.media_type = self._inner.media_type

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        self._inner.set_streaming_options(self.chunk_size, self.max_ranges)
        self._sync_raw_headers()
        await self._inner.asgi_call(
            scope,
            receive,
            send,
            self.background,
            (self.path, self.status_code, self.stat_result),
        )


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
        self.body = b""
        self.status_code = status_code


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
        self.status_code = status_code
        self.media_type = _core.Response.media_type_or(media_type, self.media_type)
        self.background = background
        self.body = self.render(content)
        self._inner = _core.Response.json(self.body, status_code, headers, self.media_type)

    def render(self, content: Any) -> bytes:
        """Serialize JSON with Starlette's Python-value compatibility rules."""
        return _core.Response.render_json(content)
