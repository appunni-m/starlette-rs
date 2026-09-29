"""Rust-backed ASGI GZip response transformation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import anyio.lowlevel
from starlette_rs_py import _core

DEFAULT_EXCLUDED_CONTENT_TYPES: tuple[str, ...] = _core.GZIP_DEFAULT_EXCLUDED_CONTENT_TYPES

_gzip_capacity_limiter: anyio.lowlevel.RunVar[anyio.CapacityLimiter] = anyio.lowlevel.RunVar(
    "_gzip_capacity_limiter"
)


def _offload_gzip_body(responder: Any, body: bytes, more_body: bool) -> Any:
    """Return AnyIO's worker-pool awaitable through a Rust boundary call."""
    return _core._offload_gzip_body(
        responder,
        body,
        more_body,
        _gzip_capacity_limiter,
        anyio.CapacityLimiter,
    )


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
        self._runtime = _core.GZipMiddlewareRuntime(self.app, self.config, _offload_gzip_body)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(scope, receive, send)
