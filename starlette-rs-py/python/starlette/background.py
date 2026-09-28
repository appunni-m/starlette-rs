"""Background-task API backed by Rust continuations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, ParamSpec

from starlette_rs_py import _core

P = ParamSpec("P")


class BackgroundTask:
    """Run one Python callable after its response completes."""

    def __init__(self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> None:
        self._inner = _core.BackgroundTask(func, *args, **kwargs)

    @property
    def func(self) -> Callable[P, Any]:
        return self._inner.func

    @func.setter
    def func(self, func: Callable[P, Any]) -> None:
        self._inner.func = func

    @property
    def args(self) -> P.args:
        return self._inner.args

    @args.setter
    def args(self, args: P.args) -> None:
        self._inner.args = args

    @property
    def kwargs(self) -> P.kwargs:
        return self._inner.kwargs

    @kwargs.setter
    def kwargs(self, kwargs: P.kwargs) -> None:
        self._inner.kwargs = kwargs

    @property
    def is_async(self) -> bool:
        return self._inner.is_async

    @is_async.setter
    def is_async(self, is_async: bool) -> None:
        self._inner.is_async = is_async

    async def __call__(self) -> None:
        await self._inner.run()


class BackgroundTasks(BackgroundTask):
    """Run a mutable list of background tasks in registration order."""

    def __init__(self, tasks: Sequence[BackgroundTask] | None = None) -> None:
        self._inner = _core.BackgroundTasks(tasks)

    @property
    def tasks(self) -> list[BackgroundTask]:
        return self._inner.tasks

    @tasks.setter
    def tasks(self, tasks: list[BackgroundTask]) -> None:
        self._inner.tasks = tasks

    def add_task(self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> None:
        self._inner.append_task(BackgroundTask(func, *args, **kwargs))

    async def __call__(self) -> None:
        await self._inner.run()
