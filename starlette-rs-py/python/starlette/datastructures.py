"""Connection value objects exposed by the Starlette compatibility package."""

from __future__ import annotations

from collections.abc import (
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    MutableMapping,
    Sequence,
    ValuesView,
)
from typing import Any, Literal, NamedTuple, TypeVar
from urllib.parse import SplitResult

from starlette_rs_py import _core

Secret = _core.Secret

_KeyType = TypeVar("_KeyType")
_CovariantValueType = TypeVar("_CovariantValueType", covariant=True)


class ImmutableMultiDict(Mapping[_KeyType, _CovariantValueType]):
    """An immutable ordered mapping that retains repeated key/value pairs."""

    __slots__ = ("_inner",)

    def __init__(
        self,
        *args: ImmutableMultiDict[_KeyType, _CovariantValueType]
        | Mapping[_KeyType, _CovariantValueType]
        | Iterable[tuple[_KeyType, _CovariantValueType]],
        **kwargs: Any,
    ) -> None:
        self._inner = _core._MultiDictStore(*args, **kwargs)

    def getlist(self, key: Any) -> list[_CovariantValueType]:
        return self._inner.getlist(key)

    def keys(self) -> KeysView[_KeyType]:
        return self._inner.keys()

    def values(self) -> ValuesView[_CovariantValueType]:
        return self._inner.values()

    def items(self) -> ItemsView[_KeyType, _CovariantValueType]:
        return self._inner.items_view()

    def multi_items(self) -> list[tuple[_KeyType, _CovariantValueType]]:
        return self._inner.multi_items()

    def get(self, key: _KeyType, default: Any = None) -> _CovariantValueType | Any:
        return self._inner.get(key, default)

    def __getitem__(self, key: _KeyType) -> _CovariantValueType:
        return self._inner[key]

    def __contains__(self, key: object) -> bool:
        return self._inner.contains(key)

    def __iter__(self) -> Iterator[_KeyType]:
        return iter(self._inner)

    def __len__(self) -> int:
        return self._inner.len()

    def __bool__(self) -> bool:
        return self._inner.__bool__()

    def __eq__(self, other: Any) -> bool:
        return self._inner.equals(self.__class__, other)

    def __repr__(self) -> str:
        return self._inner.repr(self.__class__.__name__)


class MultiDict(ImmutableMultiDict[Any, Any]):
    """A mutable ordered mapping that retains repeated key/value pairs."""

    def __setitem__(self, key: Any, value: Any) -> None:
        self._inner.set(key, value)

    def __delitem__(self, key: Any) -> None:
        self._inner.delete(key)

    def pop(self, key: Any, default: Any = None) -> Any:
        return self._inner.pop(key, default)

    def popitem(self) -> tuple[Any, Any]:
        return self._inner.popitem()

    def poplist(self, key: Any) -> list[Any]:
        return self._inner.poplist(key)

    def clear(self) -> None:
        self._inner.clear()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        return self._inner.setdefault(key, default)

    def setlist(self, key: Any, values: list[Any]) -> None:
        self._inner.setlist(key, values)

    def append(self, key: Any, value: Any) -> None:
        self._inner.append(key, value)

    def update(
        self,
        *args: MultiDict | Mapping[Any, Any] | list[tuple[Any, Any]],
        **kwargs: Any,
    ) -> None:
        _core._multidict_update(self._inner, args, kwargs)


class CommaSeparatedStrings(Sequence[str]):
    """A sequence parsed from a comma-separated string by Rust."""

    __slots__ = ("_inner",)

    def __init__(self, value: str | Sequence[str]) -> None:
        self._inner = _core.CommaSeparatedStrings(value)

    def __getitem__(self, index: int | slice) -> Any:
        return self._inner[index]

    def __iter__(self) -> Iterator[str]:
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)

    def __repr__(self) -> str:
        return self._inner._repr_for_class(self.__class__.__name__)

    def __str__(self) -> str:
        return str(self._inner)


class Headers(Mapping[str, str]):
    """Immutable ordered HTTP headers backed by Rust-owned semantics."""

    __slots__ = ("_inner",)

    def __init__(
        self,
        headers: Mapping[str, str] | None = None,
        raw: list[tuple[bytes, bytes]] | None = None,
        scope: MutableMapping[str, Any] | None = None,
    ) -> None:
        self._inner = _core._HeadersStore(headers, raw, scope, False)

    @property
    def raw(self) -> list[tuple[bytes, bytes]]:
        return self._inner.raw

    def keys(self) -> list[str]:
        return self._inner.keys()

    def values(self) -> list[str]:
        return self._inner.values()

    def items(self) -> list[tuple[str, str]]:
        return self._inner.items()

    def getlist(self, key: str) -> list[str]:
        return self._inner.getlist(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self._inner.get(key, default)

    def mutablecopy(self) -> MutableHeaders:
        return MutableHeaders._from_inner(self._inner.mutablecopy())

    def __getitem__(self, key: str) -> str:
        return self._inner[key]

    def __contains__(self, key: Any) -> bool:
        return key in self._inner

    def __iter__(self) -> Iterator[str]:
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)

    def __eq__(self, other: Any) -> bool:
        return _core._headers_equal(self._inner, other)

    def __repr__(self) -> str:
        return self._inner.repr(self.__class__.__name__)

    @classmethod
    def _from_inner(cls, inner: Any) -> Headers:
        value = cls.__new__(cls)
        value._inner = inner
        return value


class MutableHeaders(Headers):
    """Mutable ordered HTTP headers backed by Rust-owned semantics."""

    def __init__(
        self,
        headers: Mapping[str, str] | None = None,
        raw: list[tuple[bytes, bytes]] | None = None,
        scope: MutableMapping[str, Any] | None = None,
    ) -> None:
        self._inner = _core._HeadersStore(headers, raw, scope, True)

    def __setitem__(self, key: str, value: str) -> None:
        self._inner.set(key, value)

    def __delitem__(self, key: str) -> None:
        self._inner.delete(key)

    def __ior__(self, other: Mapping[str, str]) -> MutableHeaders:
        self._inner.inplace_union(other)
        return self

    def __or__(self, other: Mapping[str, str]) -> MutableHeaders:
        return self._from_inner(self._inner.union(other))

    def setdefault(self, key: str, value: str) -> str:
        return self._inner.setdefault(key, value)

    def update(self, other: Mapping[str, str]) -> None:
        self._inner.update(other)

    def append(self, key: str, value: str) -> None:
        self._inner.append(key, value)

    def add_vary_header(self, vary: str) -> None:
        self._inner.add_vary_header(vary)


class QueryParams(_core.QueryParams, Mapping[str, str]):
    """Immutable query parameters with Rust-owned parsing and lookup behavior."""


class UploadFile(_core.UploadFile):
    """An uploaded file whose storage and I/O policy are owned by Rust."""

    async def write(self, data: bytes) -> None:
        await self._write(data)

    async def read(self, size: int = -1) -> bytes:
        return await self._read(size)

    async def seek(self, offset: int) -> None:
        await self._seek(offset)

    async def close(self) -> None:
        await self._close()


class FormData(_core.FormData, Mapping[str, Any]):
    """Immutable ordered form values backed by Rust-owned multi-dict semantics."""

    async def close(self) -> None:
        await self._close()


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
    """
    An object that can be used to store arbitrary state.

    Used for `request.state` and `app.state`.
    """

    _state: dict[str, Any]

    def __init__(self, state: dict[str, Any] | None = None):
        object.__setattr__(self, "_state", _core._state_new(state))

    def __setattr__(self, key: Any, value: Any) -> None:
        _core._state_set(self._state, key, value)

    def __getattr__(self, key: Any) -> Any:
        return _core._state_getattr(self._state, self.__class__.__name__, key)

    def __delattr__(self, key: Any) -> None:
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
