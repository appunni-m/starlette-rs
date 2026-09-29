"""Static-file serving delegated to the Rust Starlette runtime."""

from __future__ import annotations

import os

from starlette_rs_py import _core

PathLike = str | os.PathLike[str]


class StaticFiles:
    """Serve files from configured directories through native dispatch."""

    __slots__ = ("_inner",)

    def __init__(
        self,
        *,
        directory: PathLike | None = None,
        packages: list[str | tuple[str, str]] | None = None,
        html: bool = False,
        check_dir: bool = True,
        follow_symlink: bool = False,
    ) -> None:
        self._inner = _core.StaticFiles(directory, packages, html, check_dir, follow_symlink)

    @property
    def directory(self) -> PathLike | None:
        return self._inner.directory

    @property
    def packages(self) -> list[str | tuple[str, str]] | None:
        return self._inner.packages

    @property
    def all_directories(self) -> list[PathLike]:
        return self._inner.all_directories

    @property
    def html(self) -> bool:
        return self._inner.html

    @property
    def config_checked(self) -> bool:
        return self._inner.config_checked

    @property
    def follow_symlink(self) -> bool:
        return self._inner.follow_symlink

    def get_directories(
        self,
        directory: PathLike | None = None,
        packages: list[str | tuple[str, str]] | None = None,
    ) -> list[PathLike]:
        return self._inner.get_directories(directory, packages)

    def get_path(self, scope: dict[str, object]) -> str:
        return self._inner.get_path(scope)

    async def get_response(self, path: str, scope: dict[str, object]) -> object:
        return self._inner.get_response(path, scope)

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        return self._inner.lookup_path(path)

    async def check_config(self) -> None:
        return self._inner.check_config()

    async def __call__(self, scope: dict[str, object], receive: object, send: object) -> None:
        await self._inner.asgi_call(scope, receive, send)
