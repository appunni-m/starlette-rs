"""ASGI WebSocket connections backed by Rust protocol state."""

from __future__ import annotations

import enum
import json
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
        self.reason = reason or ""


class WebSocket(HTTPConnection):
    """Expose an ASGI WebSocket scope and state-checked message operations."""

    __slots__ = ("_receive", "_send", "_state_machine")

    def __init__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        super().__init__(scope)
        assert scope["type"] == "websocket"
        self._receive = receive
        self._send = send
        self._state_machine = _core.WebSocketStateMachine()

    @property
    def client_state(self) -> WebSocketState:
        return WebSocketState(self._state_machine.client_state())

    @property
    def application_state(self) -> WebSocketState:
        return WebSocketState(self._state_machine.application_state())

    async def receive(self) -> dict[str, Any]:
        """Receive one ASGI message and update the Rust-owned client state."""
        if self.client_state in {WebSocketState.DISCONNECTED, WebSocketState.RESPONSE}:
            self._state_machine.receive("")
        message = await self._receive()
        self._state_machine.receive(message["type"])
        return message

    async def send(self, message: dict[str, Any]) -> None:
        """Validate a raw ASGI message before awaiting the host's send callback."""
        catches_os_error = self._state_machine.begin_send(
            message["type"], message.get("more_body", False)
        )
        if catches_os_error:
            try:
                await self._send(message)
            except OSError:
                self._state_machine.send_failed()
                # Preserve Starlette's implicit OSError context on this raise.
                raise WebSocketDisconnect(code=1006)  # noqa: B904
        else:
            await self._send(message)

    async def accept(
        self,
        subprotocol: str | None = None,
        headers: Iterable[tuple[bytes, bytes]] | None = None,
    ) -> None:
        headers = headers or []
        if self.client_state == WebSocketState.CONNECTING:
            await self.receive()
        await self.send(
            {"type": "websocket.accept", "subprotocol": subprotocol, "headers": headers}
        )

    def _raise_on_disconnect(self, message: dict[str, Any]) -> None:
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"], message.get("reason"))

    async def receive_text(self) -> str:
        if self.application_state != WebSocketState.CONNECTED:
            raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        message = await self.receive()
        self._raise_on_disconnect(message)
        return cast(str, message["text"])

    async def receive_bytes(self) -> bytes:
        if self.application_state != WebSocketState.CONNECTED:
            raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        message = await self.receive()
        self._raise_on_disconnect(message)
        return cast(bytes, message["bytes"])

    async def receive_json(self, mode: str = "text") -> Any:
        if mode not in {"text", "binary"}:
            raise RuntimeError('The "mode" argument should be "text" or "binary".')
        if self.application_state != WebSocketState.CONNECTED:
            raise RuntimeError('WebSocket is not connected. Need to call "accept" first.')
        message = await self.receive()
        self._raise_on_disconnect(message)
        text = message["text"] if mode == "text" else message["bytes"].decode("utf-8")
        return json.loads(text)

    async def iter_text(self) -> AsyncIterator[str]:
        try:
            while True:
                yield await self.receive_text()
        except WebSocketDisconnect:
            return

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        try:
            while True:
                yield await self.receive_bytes()
        except WebSocketDisconnect:
            return

    async def iter_json(self) -> AsyncIterator[Any]:
        try:
            while True:
                yield await self.receive_json()
        except WebSocketDisconnect:
            return

    async def send_text(self, data: str) -> None:
        await self.send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        await self.send({"type": "websocket.send", "bytes": data})

    async def send_json(self, data: Any, mode: str = "text") -> None:
        if mode not in {"text", "binary"}:
            raise RuntimeError('The "mode" argument should be "text" or "binary".')
        encoded = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if mode == "text":
            await self.send({"type": "websocket.send", "text": encoded})
        else:
            await self.send({"type": "websocket.send", "bytes": encoded.encode("utf-8")})

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        await self.send({"type": "websocket.close", "code": code, "reason": reason or ""})

    async def send_denial_response(self, response: Response) -> None:
        if "websocket.http.response" in self.scope.get("extensions", {}):
            await response(self.scope, self.receive, self.send)
        else:
            raise RuntimeError(
                "The server doesn't support the Websocket Denial Response extension."
            )


class WebSocketClose:
    """ASGI app that rejects a WebSocket connection with a close event."""

    def __init__(self, code: int = 1000, reason: str | None = None) -> None:
        self.code = code
        self.reason = reason or ""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "websocket.close", "code": self.code, "reason": self.reason})
