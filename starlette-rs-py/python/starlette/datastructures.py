"""Connection value objects exposed by the Starlette compatibility package."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal, NamedTuple
from urllib.parse import SplitResult

from starlette_rs_py import _core

Secret = _core.Secret


class QueryParams(_core.QueryParams, Mapping[str, str]):
    """Immutable query parameters with Rust-owned parsing and lookup behavior."""


class Address(NamedTuple):
    """A host and port pair from an ASGI connection scope."""

    host: str
    port: int


class URL:
    """A parsed URL value with the properties used by Starlette connections."""

    __slots__ = ("_components", "_url")

    def __init__(
        self,
        url: str = "",
        scope: dict[str, Any] | None = None,
        **components: Any,
    ) -> None:
        self._url = _core._url_init(url, scope, components)
        self._components: SplitResult | None = None

    @property
    def components(self) -> SplitResult:
        self._components = _core._url_components(self._url, self._components)
        return self._components

    @property
    def scheme(self) -> str:
        return self.components.scheme

    @property
    def netloc(self) -> str:
        return self.components.netloc

    @property
    def path(self) -> str:
        return self.components.path

    @property
    def query(self) -> str:
        return self.components.query

    @property
    def fragment(self) -> str:
        return self.components.fragment

    @property
    def username(self) -> str | None:
        return self.components.username

    @property
    def password(self) -> str | None:
        return self.components.password

    @property
    def hostname(self) -> str | None:
        return self.components.hostname

    @property
    def port(self) -> int | None:
        return self.components.port

    @property
    def is_secure(self) -> bool:
        return _core._url_is_secure(self.components)

    def replace(self, **components: Any) -> URL:
        url = _core._url_replace(self._url, self.components, components)
        return self.__class__(url)

    def include_query_params(self, **kwargs: Any) -> URL:
        return _core._url_include_query_params(self, kwargs)

    def replace_query_params(self, **kwargs: Any) -> URL:
        return _core._url_replace_query_params(self, kwargs)

    def remove_query_params(self, keys: str | Sequence[str]) -> URL:
        return _core._url_remove_query_params(self, keys)

    def __str__(self) -> str:
        return self._url

    def __repr__(self) -> str:
        value, self._components = _core._url_repr(
            self._url, self._components, self.__class__.__name__
        )
        return value

    def __eq__(self, other: object) -> bool:
        return _core._url_eq(self._url, other)


class URLPath(str):
    """A route path with optional protocol and host metadata."""

    def __new__(
        cls,
        path: str,
        protocol: Literal["http", "websocket", ""] = "",
        host: str = "",
    ) -> URLPath:
        _core._urlpath_validate(protocol)
        return str.__new__(cls, path)

    def __init__(
        self,
        path: str,
        protocol: Literal["http", "websocket", ""] = "",
        host: str = "",
    ) -> None:
        self.protocol = protocol
        self.host = host

    def make_absolute_url(self, base_url: str | URL) -> URL:
        return _core._urlpath_make_absolute_url(str(self), self.protocol, self.host, base_url, URL)


class State:
    """Attribute and mapping access to mutable connection state."""

    __slots__ = ("_state",)

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "_state", _core._state_new(state))

    def __setattr__(self, key: str, value: Any) -> None:
        _core._state_set(self._state, key, value)

    def __getattr__(self, key: str) -> Any:
        return _core._state_getattr(self._state, self.__class__.__name__, key)

    def __delattr__(self, key: str) -> None:
        _core._state_delete(self._state, key)

    def __getitem__(self, key: str) -> Any:
        return _core._state_get(self._state, key)

    def __setitem__(self, key: str, value: Any) -> None:
        _core._state_set(self._state, key, value)

    def __delitem__(self, key: str) -> None:
        _core._state_delete(self._state, key)

    def __iter__(self) -> Iterator[str]:
        return _core._state_iter(self._state)

    def __len__(self) -> int:
        return _core._state_len(self._state)
