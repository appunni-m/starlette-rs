"""Configuration helpers backed by the Rust compatibility runtime."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import Any, TypeVar, overload

from starlette_rs_py import _core

undefined = _core.undefined
EnvironError = _core.EnvironError

T = TypeVar("T")


class Environ(MutableMapping[str, str]):
    """Mutable environment mapping that freezes each key after its first read."""

    def __init__(self, environ: MutableMapping[str, str] = os.environ) -> None:
        self._inner = _core._Environ(environ)

    @property
    def _environ(self) -> MutableMapping[str, str]:
        return self._inner._environ

    @_environ.setter
    def _environ(self, environ: MutableMapping[str, str]) -> None:
        self._inner._environ = environ

    @property
    def _has_been_read(self) -> set[str]:
        return self._inner._has_been_read

    def __getitem__(self, key: str) -> str:
        return self._inner[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._inner[key] = value

    def __delitem__(self, key: str) -> None:
        del self._inner[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)


environ = Environ()


class Config:
    """Read values from the environment, a file, or a supplied default."""

    def __init__(
        self,
        env_file: str | Path | None = None,
        environ: Mapping[str, str] = environ,
        env_prefix: str = "",
        encoding: str = "utf-8",
    ) -> None:
        self._inner = _core._Config(env_file, environ, env_prefix, encoding)

    @overload
    def __call__(self, key: str, *, default: None) -> str | None: ...

    @overload
    def __call__(self, key: str, cast: type[T], default: T = ...) -> T: ...

    @overload
    def __call__(self, key: str, cast: type[str] = ..., default: str = ...) -> str: ...

    @overload
    def __call__(
        self,
        key: str,
        cast: Callable[[Any], T] = ...,
        default: Any = ...,
    ) -> T: ...

    @overload
    def __call__(self, key: str, cast: type[str] = ..., default: T = ...) -> T | str: ...

    def __call__(
        self,
        key: str,
        cast: Callable[[Any], Any] | None = None,
        default: Any = undefined,
    ) -> Any:
        return self._inner.get(key, cast, default)

    def get(
        self,
        key: str,
        cast: Callable[[Any], Any] | None = None,
        default: Any = undefined,
    ) -> Any:
        return self._inner.get(key, cast, default)

    def _read_file(self, file_name: str | Path, encoding: str) -> dict[str, str]:
        return self._inner.read_file(file_name, encoding)

    def _perform_cast(
        self,
        key: str,
        value: Any,
        cast: Callable[[Any], Any] | None = None,
    ) -> Any:
        return self._inner.perform_cast(key, value, cast)

    @property
    def environ(self) -> Mapping[str, str]:
        return self._inner.environ

    @environ.setter
    def environ(self, environ: Mapping[str, str]) -> None:
        self._inner.environ = environ

    @property
    def env_prefix(self) -> str:
        return self._inner.env_prefix

    @env_prefix.setter
    def env_prefix(self, env_prefix: str) -> None:
        self._inner.env_prefix = env_prefix

    @property
    def file_values(self) -> dict[str, str]:
        return self._inner.file_values

    @file_values.setter
    def file_values(self, file_values: dict[str, str]) -> None:
        self._inner.file_values = file_values
