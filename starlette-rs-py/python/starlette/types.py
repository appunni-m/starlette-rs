# Type surface adapted from Starlette 1.6.0, commit
# 4f250d6b814587e20c5365f0a5f0c4d42bcb929f. BSD-3-Clause; see LICENSE.md.

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar

AppType = TypeVar("AppType")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]

Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

StatelessLifespan = Callable[[AppType], AbstractAsyncContextManager[None]]
StatefulLifespan = Callable[[AppType], AbstractAsyncContextManager[Mapping[str, Any]]]
Lifespan = StatelessLifespan[AppType] | StatefulLifespan[AppType]

HTTPExceptionHandler = Callable[["Request", Exception], "Response | Awaitable[Response]"]  # noqa: F821
WebSocketExceptionHandler = Callable[["WebSocket", Exception], Awaitable[None]]  # noqa: F821
ExceptionHandler = HTTPExceptionHandler | WebSocketExceptionHandler
