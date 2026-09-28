"""Authentication interfaces backed by native policy and scope handling."""

from __future__ import annotations

import functools
from collections.abc import Callable, Sequence
from typing import Any, ParamSpec

from starlette_rs_py import _core

from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection, Request
from starlette.responses import RedirectResponse
from starlette.websockets import WebSocket

_P = ParamSpec("_P")


def has_required_scope(conn: HTTPConnection, scopes: Sequence[str]) -> bool:
    return _core.authentication_has_required_scope(conn, scopes)


def _requires_websocket_wrapper(runtime: Any, func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> None:
        return await _core.authentication_requires_invoke(runtime, args, kwargs)

    return wrapper


def _requires_async_wrapper(runtime: Any, func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await _core.authentication_requires_invoke(runtime, args, kwargs)

    return wrapper


def _requires_sync_wrapper(runtime: Any, func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return _core.authentication_requires_invoke_sync(runtime, args, kwargs)

    return wrapper


def requires(
    scopes: str | Sequence[str],
    status_code: int = 403,
    redirect: str | None = None,
) -> Callable[[Callable[_P, Any]], Callable[_P, Any]]:
    runtime = _core.authentication_requires_config(scopes, status_code, redirect)

    def decorator(func: Callable[_P, Any]) -> Callable[_P, Any]:
        return _core.authentication_requires_decorate(
            runtime,
            func,
            _requires_websocket_wrapper,
            _requires_async_wrapper,
            _requires_sync_wrapper,
            Request,
            WebSocket,
            HTTPException,
            RedirectResponse,
        )

    return decorator


class AuthenticationError(Exception):
    pass


class AuthenticationBackend:
    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, BaseUser] | None:
        await _core.authentication_unimplemented_async("authenticate")


class AuthCredentials:
    def __init__(self, scopes: Sequence[str] | None = None):
        self.scopes = _core.authentication_credentials_scopes(scopes)


class BaseUser:
    @property
    def is_authenticated(self) -> bool:
        return _core.authentication_base_user_unimplemented("is_authenticated")

    @property
    def display_name(self) -> str:
        return _core.authentication_base_user_unimplemented("display_name")

    @property
    def identity(self) -> str:
        return _core.authentication_base_user_unimplemented("identity")


class SimpleUser(BaseUser):
    def __init__(self, username: str) -> None:
        self.username = username

    @property
    def is_authenticated(self) -> bool:
        return _core.authentication_simple_user_is_authenticated()

    @property
    def display_name(self) -> str:
        return _core.authentication_simple_user_display_name(self.username)


class UnauthenticatedUser(BaseUser):
    @property
    def is_authenticated(self) -> bool:
        return _core.authentication_unauthenticated_user_is_authenticated()

    @property
    def display_name(self) -> str:
        return _core.authentication_unauthenticated_user_display_name()
