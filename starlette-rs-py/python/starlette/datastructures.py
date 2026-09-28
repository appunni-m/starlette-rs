"""Connection value objects exposed by the Starlette compatibility package."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, NamedTuple
from urllib.parse import SplitResult, urlsplit

from starlette_rs_py import _core


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
        if scope is not None:
            assert not url, 'Cannot set both "url" and "scope".'
            assert not components, 'Cannot set both "scope" and "**components".'
            server = scope.get("server")
            native_server = None if server is None else (server[0], server[1])
            url = _core._connection_url(
                scope.get("scheme", "http"),
                scope["path"],
                scope.get("query_string", b""),
                scope["headers"],
                native_server,
            )
        elif components:
            assert not url, 'Cannot set both "url" and "**components".'
            current = SplitResult("", "", "", "", "")
            url = current._replace(**components).geturl()

        self._url = url
        self._components: SplitResult | None = None

    @property
    def components(self) -> SplitResult:
        if self._components is None:
            self._components = urlsplit(self._url)
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
        return self.scheme in {"https", "wss"}

    def replace(self, **components: Any) -> URL:
        return URL(self.components._replace(**components).geturl())

    def __str__(self) -> str:
        return self._url

    def __repr__(self) -> str:
        value = str(self)
        if self.password:
            value = str(self.replace(password="********"))
        return f"URL({value!r})"

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)


class State:
    """Attribute and mapping access to mutable connection state."""

    __slots__ = ("_state",)

    def __init__(self, state: dict[str, Any] | None = None) -> None:
        object.__setattr__(self, "_state", {} if state is None else state)

    def __setattr__(self, key: str, value: Any) -> None:
        self._state[key] = value

    def __getattr__(self, key: str) -> Any:
        try:
            return self._state[key]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{key}'"
            ) from None

    def __delattr__(self, key: str) -> None:
        try:
            del self._state[key]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{key}'"
            ) from None

    def __getitem__(self, key: str) -> Any:
        return self._state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._state[key] = value

    def __delitem__(self, key: str) -> None:
        del self._state[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._state)

    def __len__(self) -> int:
        return len(self._state)
