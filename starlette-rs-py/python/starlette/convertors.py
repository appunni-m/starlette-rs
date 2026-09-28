"""URL parameter convertors exposed by the Starlette compatibility package.

The built-in patterns and conversion rules follow the pinned Starlette 1.6.0
compatibility authority. The upstream implementation is BSD-3-Clause licensed;
see the repository's ``LICENSE.md`` for the retained notice and conditions.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Generic, TypeVar

from starlette_rs_py import _core

T = TypeVar("T")


class Convertor(Generic[T]):
    """Base class for values captured from, or formatted into, URL paths."""

    regex: ClassVar[str] = ""

    def convert(self, value: str) -> T:
        return _core._convert_builtin_convertor("base", value)

    def to_string(self, value: T) -> str:
        return _core._format_builtin_convertor("base", value)


class StringConvertor(Convertor[str]):
    regex = "[^/]+"

    def convert(self, value: str) -> str:
        return _core._convert_builtin_convertor("str", value)

    def to_string(self, value: str) -> str:
        return _core._format_builtin_convertor("str", value)


class PathConvertor(Convertor[str]):
    regex = ".*"

    def convert(self, value: str) -> str:
        return _core._convert_builtin_convertor("path", value)

    def to_string(self, value: str) -> str:
        return _core._format_builtin_convertor("path", value)


class IntegerConvertor(Convertor[int]):
    regex = "[0-9]+"

    def convert(self, value: str) -> int:
        return _core._convert_builtin_convertor("int", value)

    def to_string(self, value: int) -> str:
        return _core._format_builtin_convertor("int", value)


class FloatConvertor(Convertor[float]):
    regex = r"[0-9]+(\.[0-9]+)?"

    def convert(self, value: str) -> float:
        return _core._convert_builtin_convertor("float", value)

    def to_string(self, value: float) -> str:
        return _core._format_builtin_convertor("float", value)


class UUIDConvertor(Convertor[uuid.UUID]):
    regex = "[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"

    def convert(self, value: str) -> uuid.UUID:
        return _core._convert_builtin_convertor("uuid", value)

    def to_string(self, value: uuid.UUID) -> str:
        return _core._format_builtin_convertor("uuid", value)


CONVERTOR_TYPES: dict[str, Convertor[Any]] = {
    "str": StringConvertor(),
    "path": PathConvertor(),
    "int": IntegerConvertor(),
    "float": FloatConvertor(),
    "uuid": UUIDConvertor(),
}

_BUILTIN_CONVERTOR_TYPES = CONVERTOR_TYPES.copy()


def register_url_convertor(key: str, convertor: Convertor[Any]) -> None:
    """Register a Python URL convertor under ``key``."""

    _core._register_url_convertor(CONVERTOR_TYPES, key, convertor)
