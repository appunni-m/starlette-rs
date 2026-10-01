"""Concurrency helpers backed by Rust continuations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from typing import ParamSpec, TypeVar

from starlette_rs_py import _core

P = ParamSpec("P")
T = TypeVar("T")


async def run_until_first_complete(
    *args: tuple[Callable, dict],  # type: ignore[type-arg]
) -> None:
    await _core.run_until_first_complete(*args)


async def run_in_threadpool(func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run a synchronous Python callable in AnyIO's worker thread pool."""
    return await _core.run_in_threadpool(func, *args, **kwargs)


def iterate_in_threadpool(iterator: Iterable[T]) -> AsyncIterator[T]:
    """Advance a synchronous iterator through AnyIO's worker thread pool."""
    return _core.iterate_in_threadpool(iterator)
