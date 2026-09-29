"""Signed cookie sessions with Rust-owned ASGI and session behavior."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from starlette_rs_py import _core

from starlette.datastructures import Secret


class Session(dict[str, Any]):
    """Dictionary-compatible session state used by ``request.session``."""

    accessed: bool
    modified: bool

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._runtime = _core.SessionState()
        dict.__init__(self, *args, **kwargs)
        self._runtime.accessed = False
        self._runtime.modified = False

    @property
    def accessed(self) -> bool:
        return self._runtime.accessed

    @accessed.setter
    def accessed(self, value: bool) -> None:
        self._runtime.accessed = value

    @property
    def modified(self) -> bool:
        return self._runtime.modified

    @modified.setter
    def modified(self, value: bool) -> None:
        self._runtime.modified = value

    def mark_accessed(self) -> None:
        self._runtime.mark_accessed()

    def mark_modified(self) -> None:
        self._runtime.mark_modified()

    def __setitem__(self, key: str, value: Any) -> None:
        self._runtime.set_item(self, key, value)

    def __delitem__(self, key: str) -> None:
        self._runtime.del_item(self, key)

    def clear(self) -> None:
        self._runtime.clear(self)

    def pop(self, key: str, *args: Any) -> Any:
        return self._runtime.pop(self, key, *args)

    def setdefault(self, key: str, default: Any = None) -> Any:
        return self._runtime.setdefault(self, key, default)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._runtime.update(self, *args, **kwargs)


class SessionMiddleware:
    """Persist ``request.session`` in a signed, HTTP-only cookie."""

    def __init__(
        self,
        app: Callable[..., Any],
        secret_key: str | Secret,
        session_cookie: str = "session",
        max_age: int | None = 14 * 24 * 60 * 60,
        path: str = "/",
        same_site: Literal["lax", "strict", "none"] = "lax",
        https_only: bool = False,
        domain: str | None = None,
    ) -> None:
        self._runtime = _core.SessionMiddlewareRuntime(
            app,
            secret_key,
            session_cookie,
            max_age,
            path,
            same_site,
            https_only,
            domain,
        )

    @property
    def app(self) -> Callable[..., Any]:
        return self._runtime.app

    @app.setter
    def app(self, value: Callable[..., Any]) -> None:
        self._runtime.app = value

    @property
    def session_cookie(self) -> str:
        return self._runtime.session_cookie

    @session_cookie.setter
    def session_cookie(self, value: str) -> None:
        self._runtime.session_cookie = value

    @property
    def max_age(self) -> int | None:
        return self._runtime.max_age

    @max_age.setter
    def max_age(self, value: int | None) -> None:
        self._runtime.max_age = value

    @property
    def path(self) -> str:
        return self._runtime.path

    @path.setter
    def path(self, value: str) -> None:
        self._runtime.path = value

    @property
    def security_flags(self) -> str:
        return self._runtime.security_flags

    @security_flags.setter
    def security_flags(self, value: str) -> None:
        self._runtime.security_flags = value

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(scope, receive, send)
