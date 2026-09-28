"""Class-based HTTP and WebSocket endpoints dispatched by Rust."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any, Literal

from starlette_rs_py import _core

from starlette import status
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import Message, Receive, Scope, Send
from starlette.websockets import WebSocket


class HTTPEndpoint:
    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        _core._endpoint_validate_scope(scope, "http", __debug__)
        self.scope = scope
        self.receive = receive
        self.send = send
        self._allowed_methods = _core._http_endpoint_allowed_methods(self)

    def __await__(self) -> Generator[Any, None, None]:
        return self.dispatch().__await__()

    async def dispatch(self) -> None:
        await _core._http_endpoint_dispatch(self, Request, run_in_threadpool)

    async def method_not_allowed(self, request: Request) -> Response:
        return _core._http_endpoint_method_not_allowed(
            self, request, HTTPException, PlainTextResponse
        )


class WebSocketEndpoint:
    encoding: Literal["text", "bytes", "json"] | None = None

    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        _core._endpoint_validate_scope(scope, "websocket", __debug__)
        self.scope = scope
        self.receive = receive
        self.send = send

    def __await__(self) -> Generator[Any, None, None]:
        return self.dispatch().__await__()

    async def dispatch(self) -> None:
        await _core._websocket_endpoint_dispatch(self, WebSocket, status)

    async def decode(self, websocket: WebSocket, message: Message) -> Any:
        return await _core._websocket_endpoint_decode(
            self.encoding, websocket, message, json, status, __debug__
        )

    async def on_connect(self, websocket: WebSocket) -> None:
        """Override to handle an incoming websocket connection"""
        await _core._websocket_endpoint_on_connect(websocket)

    async def on_receive(self, websocket: WebSocket, data: Any) -> None:
        """Override to handle an incoming websocket message"""

    async def on_disconnect(self, websocket: WebSocket, close_code: int) -> None:
        """Override to handle a disconnecting websocket"""
