"""Concurrency helpers for the Python compatibility boundary."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

import anyio.to_thread

P = ParamSpec("P")
T = TypeVar("T")


async def run_in_threadpool(func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a synchronous Python callable in AnyIO's worker thread pool."""
    call = functools.partial(func, **kwargs) if kwargs else func
    return await anyio.to_thread.run_sync(call, *args)
