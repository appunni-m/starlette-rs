"""Response wrappers whose construction and ASGI messages are owned by Rust."""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from typing import Any

import anyio.to_thread
from starlette_rs_py import _core

from starlette.datastructures import URL

_ContentChunk = str | bytes
_ContentStream = Iterable[_ContentChunk] | AsyncIterable[_ContentChunk]


class Response:
    """Wrap a Rust response and await ASGI ``send`` on the caller's loop."""

    __slots__ = ("_inner",)

    def __init__(
        self,
        content: str | bytes = "",
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        if background is not None:
            raise NotImplementedError("background tasks are outside this slice")
        header_pairs = [] if headers is None else list(headers.items())
        self._inner = _core.Response(content, status_code, header_pairs, media_type)

    @classmethod
    def _from_native(cls, inner: Any) -> Response:
        """Wrap a Rust-created fallback response without rebuilding it in Python."""
        response = cls.__new__(cls)
        response._inner = inner
        return response

    def set_cookie(self, key: str, value: str) -> None:
        """Append a cookie header through the Rust response implementation."""
        self._inner.set_cookie(key, value)

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        for message in self._inner.asgi_messages():
            if scope.get("type") == "websocket" and message["type"] in {
                "http.response.start",
                "http.response.body",
            }:
                message = {**message, "type": "websocket." + message["type"]}
            await send(message)


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
    """Send sync or async content chunks through Rust-framed ASGI events.

    Chunks are consumed lazily after the response-start event is sent. This
    bounded implementation does not include disconnect-race handling or
    ``BackgroundTask`` parity.
    """

    __slots__ = (
        "_content",
        "_explicit_content_length",
        "_header_pairs",
        "_media_type",
        "_status_code",
    )
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
        if background is not None:
            raise NotImplementedError("background tasks are outside this slice")
        super().__init__(b"", status_code, headers, media_type)
        self._content = content
        self._status_code = status_code
        self._header_pairs = [] if headers is None else list(headers.items())
        self._explicit_content_length = any(
            name.lower() == "content-length" for name, _value in self._header_pairs
        )
        self._media_type = media_type

    def set_cookie(self, key: str, value: str) -> None:
        """Append a cookie header before the stream begins."""
        self._inner.set_cookie(key, value)
        self._header_pairs = [
            (name.decode("latin-1"), header_value.decode("latin-1"))
            for name, header_value in self._inner.asgi_messages()[0]["headers"]
            if self._explicit_content_length or name.lower() != b"content-length"
        ]

    def _chunk_bytes(self, chunk: _ContentChunk) -> bytes:
        if isinstance(chunk, str):
            return chunk.encode(self.charset)
        if isinstance(chunk, bytes):
            return chunk
        raise TypeError("StreamingResponse chunks must be strings or bytes")

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        response = _core.StreamingResponse(
            [],
            self._status_code,
            self._header_pairs,
            self._media_type,
        )

        async def send_message(message: dict[str, Any]) -> None:
            if scope.get("type") == "websocket" and message["type"] in {
                "http.response.start",
                "http.response.body",
            }:
                message = {**message, "type": "websocket." + message["type"]}
            await send(message)

        await send_message(response.start_message())

        if isinstance(self._content, AsyncIterable):
            async for chunk in self._content:
                await send_message(
                    _core.StreamingResponse.body_message(self._chunk_bytes(chunk), True)
                )
        else:
            sentinel = object()
            iterator = iter(self._content)
            while True:
                chunk = await anyio.to_thread.run_sync(next, iterator, sentinel)
                if chunk is sentinel:
                    break
                await send_message(
                    _core.StreamingResponse.body_message(self._chunk_bytes(chunk), True)
                )

        await send_message(_core.StreamingResponse.final_message())


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
        if background is not None:
            raise NotImplementedError("background tasks are outside this slice")
        header_pairs = [] if headers is None else list(headers.items())
        self._inner = _core.Response.redirect(str(url), status_code, header_pairs)


class JSONResponse(Response):
    """Encode a Python JSON value, then delegate HTTP framing to Rust."""

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
        # Starlette's JSONResponse uses Python's JSON conversion rules for
        # arbitrary Python values; Rust owns the resulting response bytes and
        # ASGI events after this representation boundary.
        body = json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        super().__init__(
            body,
            status_code,
            headers,
            self.media_type if media_type is None else media_type,
            background,
        )
