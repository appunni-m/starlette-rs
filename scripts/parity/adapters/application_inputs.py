"""Input-defined Python values for Starlette application workflows."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any


class ObservableMapping(Mapping[Any, Any]):
    """A Mapping whose iteration callback records that construction consumed it."""

    def __init__(self, values: Mapping[Any, Any], events: list[str], event: str) -> None:
        self._values = dict(values)
        self._events = events
        self._event = event

    def __getitem__(self, key: Any) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> Any:
        self._events.append(self._event)
        return self._values.keys()


class ObservableSequence(Sequence[Any]):
    """A Sequence whose iteration callback records that construction consumed it."""

    def __init__(self, values: Sequence[Any], events: list[str], event: str) -> None:
        self._values = list(values)
        self._events = events
        self._event = event

    def __getitem__(self, index: int | slice) -> Any:
        return self._values[index]

    def __iter__(self) -> Iterator[Any]:
        self._events.append(self._event)
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def middleware_with_iterator_override(
    middleware_type: type[Any],
    original_factory: Any,
    yielded_factory: Any,
    yielded_args: Any,
    yielded_kwargs: Mapping[Any, Any],
) -> Any:
    """Create a public Middleware subclass with input-selected iterator values."""

    class InputMiddleware(middleware_type):
        def __iter__(self) -> Iterator[Any]:
            return iter((yielded_factory, yielded_args, yielded_kwargs))

    return InputMiddleware(original_factory)
