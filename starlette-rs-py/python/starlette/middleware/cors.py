"""Rust-backed ASGI Cross-Origin Resource Sharing middleware."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from starlette_rs_py import _core

ALL_METHODS = _core.CORS_ALL_METHODS
SAFELISTED_HEADERS = _core.CORS_SAFELISTED_HEADERS


class CORSMiddleware:
    """Forward the Starlette CORS middleware API to its Rust runtime."""

    def __init__(
        self,
        app: Callable[..., Any],
        allow_origins: Sequence[str] = (),
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        allow_origin_regex: str | None = None,
        allow_private_network: bool = False,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
    ) -> None:
        self._runtime = _core.CORSMiddleware(
            {
                "app": app,
                "allow_origins": allow_origins,
                "allow_methods": allow_methods,
                "allow_headers": allow_headers,
                "allow_credentials": allow_credentials,
                "allow_origin_regex": allow_origin_regex,
                "allow_private_network": allow_private_network,
                "expose_headers": expose_headers,
                "max_age": max_age,
            }
        )

    @property
    def app(self) -> Any:
        return self._runtime.app

    @app.setter
    def app(self, value: Any) -> None:
        self._runtime.app = value

    @property
    def allow_origins(self) -> Any:
        return self._runtime.allow_origins

    @allow_origins.setter
    def allow_origins(self, value: Any) -> None:
        self._runtime.allow_origins = value

    @property
    def allow_methods(self) -> Any:
        return self._runtime.allow_methods

    @allow_methods.setter
    def allow_methods(self, value: Any) -> None:
        self._runtime.allow_methods = value

    @property
    def allow_headers(self) -> Any:
        return self._runtime.allow_headers

    @allow_headers.setter
    def allow_headers(self, value: Any) -> None:
        self._runtime.allow_headers = value

    @property
    def allow_all_origins(self) -> Any:
        return self._runtime.allow_all_origins

    @allow_all_origins.setter
    def allow_all_origins(self, value: Any) -> None:
        self._runtime.allow_all_origins = value

    @property
    def allow_all_headers(self) -> Any:
        return self._runtime.allow_all_headers

    @allow_all_headers.setter
    def allow_all_headers(self, value: Any) -> None:
        self._runtime.allow_all_headers = value

    @property
    def allow_credentials(self) -> Any:
        return self._runtime.allow_credentials

    @allow_credentials.setter
    def allow_credentials(self, value: Any) -> None:
        self._runtime.allow_credentials = value

    @property
    def preflight_explicit_allow_origin(self) -> Any:
        return self._runtime.preflight_explicit_allow_origin

    @preflight_explicit_allow_origin.setter
    def preflight_explicit_allow_origin(self, value: Any) -> None:
        self._runtime.preflight_explicit_allow_origin = value

    @property
    def allow_origin_regex(self) -> Any:
        return self._runtime.allow_origin_regex

    @allow_origin_regex.setter
    def allow_origin_regex(self, value: Any) -> None:
        self._runtime.allow_origin_regex = value

    @property
    def allow_private_network(self) -> Any:
        return self._runtime.allow_private_network

    @allow_private_network.setter
    def allow_private_network(self, value: Any) -> None:
        self._runtime.allow_private_network = value

    @property
    def simple_headers(self) -> Any:
        return self._runtime.simple_headers

    @simple_headers.setter
    def simple_headers(self, value: Any) -> None:
        self._runtime.simple_headers = value

    @property
    def preflight_headers(self) -> Any:
        return self._runtime.preflight_headers

    @preflight_headers.setter
    def preflight_headers(self, value: Any) -> None:
        self._runtime.preflight_headers = value

    def is_allowed_origin(self, origin: str) -> bool:
        return self._runtime.is_allowed_origin(origin)

    def preflight_response(self, request_headers: Any) -> Any:
        return self._runtime.preflight_response(request_headers)

    async def simple_response(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
        request_headers: Any,
    ) -> None:
        await self._runtime.simple_response(scope, receive, send, request_headers)

    async def send(self, message: Any, send: Callable[..., Any], request_headers: Any) -> None:
        await self._runtime.send(message, send, request_headers)

    @staticmethod
    def allow_explicit_origin(headers: Any, origin: str) -> None:
        return _core.CORSMiddleware.allow_explicit_origin(headers, origin)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        await self._runtime(scope, receive, send)
