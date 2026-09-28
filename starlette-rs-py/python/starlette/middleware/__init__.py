"""Middleware configuration objects for the Starlette package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from typing import Any, ParamSpec, Protocol

from starlette_rs_py import _core

P = ParamSpec("P")

_Scope = Any
_Receive = Callable[[], Awaitable[Any]]
_Send = Callable[[Any], Awaitable[None]]
_ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class _MiddlewareFactory(Protocol[P]):
    def __call__(self, app: _ASGIApp, /, *args: P.args, **kwargs: P.kwargs) -> _ASGIApp: ...


class Middleware:
    """A middleware class and its constructor arguments."""

    def __init__(self, cls: _MiddlewareFactory[P], *args: P.args, **kwargs: P.kwargs) -> None:
        self.cls = cls
        self.args = args
        self.kwargs = kwargs

    def __iter__(self) -> Iterator[Any]:
        return _core._middleware_iter(self)

    def __repr__(self) -> str:
        return _core._middleware_repr(self)
