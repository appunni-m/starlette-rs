"""Rust-backed ASGI GZip response transformation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio.lowlevel
import anyio.to_thread
from starlette_rs_py import _core

DEFAULT_EXCLUDED_CONTENT_TYPES = (
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "audio/*",
    "font/woff",
    "font/woff2",
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/event-stream",
    "video/*",
)

_gzip_capacity_limiter: anyio.lowlevel.RunVar[anyio.CapacityLimiter] = anyio.lowlevel.RunVar(
    "_gzip_capacity_limiter"
)


def _get_gzip_capacity_limiter() -> anyio.CapacityLimiter:
    """Return the task-local capacity limiter used for large GZip chunks."""
    try:
        return _gzip_capacity_limiter.get()
    except LookupError:
        limiter = anyio.CapacityLimiter(40)
        _gzip_capacity_limiter.set(limiter)
        return limiter


class GZipMiddleware:
    """Compress eligible HTTP response bodies in a Rust-owned gzip stream."""

    def __init__(
        self,
        app: Callable[..., Any],
        minimum_size: int = 500,
        compresslevel: int = 9,
        thread_minimum_size: int = 128 * 1024,
        *,
        exclude_content_types: tuple[str, ...] = DEFAULT_EXCLUDED_CONTENT_TYPES,
    ) -> None:
        self.app = app
        self.config = _core.GzipConfig(
            minimum_size,
            compresslevel,
            thread_minimum_size,
            list(exclude_content_types),
        )

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = list(scope["headers"])
        scope["headers"] = request_headers
        responder = self.config.responder(request_headers)
        initial_message: dict[str, Any] = {}

        async def send_with_compression(message: dict[str, Any]) -> None:
            nonlocal initial_message
            message_type = message["type"]
            if message_type == "http.response.start":
                initial_message = message
                responder.response_start(message["status"], message["headers"])
                return

            if message_type == "http.response.body":
                body = message.get("body", b"")
                more_body = message.get("more_body", False)
                if responder.should_offload(len(body), more_body):
                    response_start, compressed_body = await anyio.to_thread.run_sync(
                        responder.response_body,
                        body,
                        more_body,
                        limiter=_get_gzip_capacity_limiter(),
                    )
                else:
                    response_start, compressed_body = responder.response_body(body, more_body)

                if response_start is not None:
                    _, headers = response_start
                    initial_message["headers"][:] = headers
                    await send(initial_message)

                if compressed_body != body:
                    message["body"] = compressed_body
                await send(message)
                return

            if message_type == "http.response.pathsend":
                response_start = responder.pathsend()
                if response_start is not None:
                    _, headers = response_start
                    initial_message["headers"][:] = headers
                await send(initial_message)
                await send(message)

        await self.app(scope, receive, send_with_compression)
