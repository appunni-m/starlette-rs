"""Static-file serving delegated to the Rust Starlette runtime."""

from __future__ import annotations

import os

from starlette_rs_py import _core

from starlette.types import Receive, Scope, Send

PathLike = str | os.PathLike[str]


class StaticFiles:
    """Serve files from configured directories through native dispatch."""

    __slots__ = (
        "_all_directories",
        "_directory",
        "_follow_symlink",
        "_html",
        "_inner",
        "_packages",
    )

    def __init__(
        self,
        *,
        directory: PathLike | None = None,
        packages: list[str | tuple[str, str]] | None = None,
        html: bool = False,
        check_dir: bool = True,
        follow_symlink: bool = False,
    ) -> None:
        self._directory = directory
        self._packages = packages
        self._all_directories = self.get_directories(directory, packages)
        self._html = html
        self._follow_symlink = follow_symlink
        self._inner = _core.StaticFiles(
            directory,
            packages,
            html,
            check_dir,
            follow_symlink,
            self._all_directories,
        )

    @property
    def directory(self) -> PathLike | None:
        return self._directory

    @property
    def packages(self) -> list[str | tuple[str, str]] | None:
        return self._packages

    @property
    def all_directories(self) -> list[PathLike]:
        return self._all_directories

    @property
    def html(self) -> bool:
        return self._html

    @property
    def config_checked(self) -> bool:
        return self._inner.config_checked

    @property
    def follow_symlink(self) -> bool:
        return self._follow_symlink

    def get_directories(
        self,
        directory: PathLike | None = None,
        packages: list[str | tuple[str, str]] | None = None,
    ) -> list[PathLike]:
        return _core.static_files_get_directories(directory, packages)

    def get_path(self, scope: dict[str, object]) -> str:
        return self._inner.get_path(scope)

    async def get_response(self, path: str, scope: dict[str, object]) -> object:
        return await self._inner.get_response(path, scope, self.lookup_path, self.file_response)

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        return self._inner.lookup_path(path)

    def file_response(
        self,
        full_path: PathLike,
        stat_result: os.stat_result,
        scope: dict[str, object],
        status_code: int = 200,
    ) -> object:
        return self._inner.file_response(
            full_path,
            stat_result,
            scope,
            self.is_not_modified,
            status_code,
        )

    def is_not_modified(self, response_headers: object, request_headers: object) -> bool:
        return self._inner.is_not_modified(response_headers, request_headers)

    async def check_config(self) -> None:
        await self._inner.check_config()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._inner.asgi_call(
            scope,
            receive,
            send,
            self.get_path,
            self.get_response,
            self.lookup_path,
            self.file_response,
            self.check_config,
        )
