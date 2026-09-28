"""ASGI WebSocket connections backed by Rust protocol state."""

from __future__ import annotations

import enum
from collections.abc import AsyncIterator, Iterable
from typing import Any, cast

from starlette_rs_py import _core

from starlette.requests import HTTPConnection
from starlette.responses import Response


class WebSocketState(enum.Enum):
    """State values used while receiving and sending ASGI WebSocket messages."""

    CONNECTING = 0
    CONNECTED = 1
    DISCONNECTED = 2
    RESPONSE = 3


class WebSocketDisconnect(Exception):
    """Raised when the ASGI server reports that the peer disconnected."""

    def __init__(self, code: int = 1000, reason: str | None = None) -> None:
        self.code = code
        self.reason = _core._websocket_exception_reason(reason)


class WebSocket(HTTPConnection):
    """Expose an ASGI WebSocket scope and state-checked message operations."""

    __slots__ = ("_protocol", "_receive", "_send")

    def __init__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        super().__init__(scope)
        self._receive = receive
        self._send = send
        self._protocol = _core.WebSocketProtocol(scope, receive, send, WebSocketDisconnect)

    @property
    def client_state(self) -> WebSocketState:
        return WebSocketState(self._protocol.client_state())

    @client_state.setter
    def client_state(self, state: WebSocketState) -> None:
        self._protocol.set_client_state(state.value)

    @property
    def application_state(self) -> WebSocketState:
        return WebSocketState(self._protocol.application_state())

    @application_state.setter
    def application_state(self, state: WebSocketState) -> None:
        self._protocol.set_application_state(state.value)

    async def receive(self) -> dict[str, Any]:
        return await self._protocol.receive()

    async def send(self, message: dict[str, Any]) -> None:
        await self._protocol.send(message)

    async def accept(
        self,
        subprotocol: str | None = None,
        headers: Iterable[tuple[bytes, bytes]] | None = None,
    ) -> None:
        await self._protocol.accept(self.receive, self.send, subprotocol, headers)

    def _raise_on_disconnect(self, message: dict[str, Any]) -> None:
        self._protocol.raise_on_disconnect(message)

    async def receive_text(self) -> str:
        return await self._protocol.receive_text(self.receive, self._raise_on_disconnect)

    async def receive_bytes(self) -> bytes:
        return await self._protocol.receive_bytes(self.receive, self._raise_on_disconnect)

    async def receive_json(self, mode: str = "text") -> Any:
        return await self._protocol.receive_json(self.receive, self._raise_on_disconnect, mode)

    def iter_text(self) -> AsyncIterator[str]:
        return cast(AsyncIterator[str], self._protocol.iter_text(self.receive_text))

    def iter_bytes(self) -> AsyncIterator[bytes]:
        return cast(AsyncIterator[bytes], self._protocol.iter_bytes(self.receive_bytes))

    def iter_json(self) -> AsyncIterator[Any]:
        return cast(AsyncIterator[Any], self._protocol.iter_json(self.receive_json))

    async def send_text(self, data: str) -> None:
        await self._protocol.send_text(self.send, data)

    async def send_bytes(self, data: bytes) -> None:
        await self._protocol.send_bytes(self.send, data)

    async def send_json(self, data: Any, mode: str = "text") -> None:
        await self._protocol.send_json(self.send, data, mode)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        await self._protocol.close(self.send, code, reason)

    async def send_denial_response(self, response: Response) -> None:
        await self._protocol.send_denial_response(self.scope, response, self.receive, self.send)


class WebSocketClose:
    """ASGI app that rejects a WebSocket connection with a close event."""

    __slots__ = ("_inner",)

    def __init__(self, code: int = 1000, reason: str | None = None) -> None:
        self._inner = _core.WebSocketClose(code, reason)

    @property
    def code(self) -> Any:
        return self._inner.code

    @code.setter
    def code(self, value: Any) -> None:
        self._inner.code = value

    @property
    def reason(self) -> Any:
        return self._inner.reason

    @reason.setter
    def reason(self, value: Any) -> None:
        self._inner.reason = value

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await self._inner.asgi_call(scope, receive, send)
