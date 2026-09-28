"""Exception types exposed by the Starlette compatibility package."""

from __future__ import annotations

from collections.abc import Mapping

from starlette_rs_py import _core


class HTTPException(Exception):
    """An HTTP error raised by a route endpoint."""

    def __init__(
        self,
        status_code: int,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        detail = _core._http_exception_detail(status_code, detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers

    def __str__(self) -> str:
        return _core._http_exception_string(self.status_code, self.detail)

    def __repr__(self) -> str:
        return _core._http_exception_repr(self.__class__.__name__, self.status_code, self.detail)


class WebSocketException(Exception):
    """An error that rejects or closes a WebSocket connection."""

    def __init__(self, code: int, reason: str | None = None) -> None:
        self.code = code
        self.reason = _core._websocket_exception_reason(reason)

    def __str__(self) -> str:
        return _core._websocket_exception_string(self.code, self.reason)

    def __repr__(self) -> str:
        return _core._websocket_exception_repr(self.__class__.__name__, self.code, self.reason)


class StarletteDeprecationWarning(UserWarning):
    """A custom deprecation warning for Starlette.

    Unlike the built-in DeprecationWarning, this inherits from UserWarning to ensure it is visible by default, helping
    users discover deprecated features without needing to enable warnings explicitly.
    Reference: https://sethmlarson.dev/deprecations-via-warnings-dont-work-for-python-libraries
    """
