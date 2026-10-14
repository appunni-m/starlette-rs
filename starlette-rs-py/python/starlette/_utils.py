"""Static protocol types used by the Starlette compatibility facades."""

from __future__ import annotations

from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeVar

T_co = TypeVar("T_co", covariant=True)


class AwaitableOrContextManager(
    Awaitable[T_co], AbstractAsyncContextManager[T_co], Protocol[T_co]
): ...
