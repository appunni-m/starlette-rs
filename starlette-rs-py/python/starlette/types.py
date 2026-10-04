# Type surface adapted from Starlette 1.6.0, commit
# 4f250d6b814587e20c5365f0a5f0c4d42bcb929f. BSD-3-Clause; see LICENSE.md.

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.websockets import WebSocket

AppType = TypeVar("AppType")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]

Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

StatelessLifespan = Callable[[AppType], AbstractAsyncContextManager[None]]
StatefulLifespan = Callable[[AppType], AbstractAsyncContextManager[Mapping[str, Any]]]
Lifespan = StatelessLifespan[AppType] | StatefulLifespan[AppType]

HTTPExceptionHandler = Callable[["Request", Exception], "Response | Awaitable[Response]"]
WebSocketExceptionHandler = Callable[["WebSocket", Exception], Awaitable[None]]
ExceptionHandler = HTTPExceptionHandler | WebSocketExceptionHandler
