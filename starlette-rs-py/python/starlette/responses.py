"""Response wrappers whose construction and ASGI messages are owned by Rust."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from starlette_rs_py import _core


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
