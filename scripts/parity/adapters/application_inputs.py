"""Input-defined Python values for Starlette application workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any


class ObservableMapping(Mapping[Any, Any]):
    """A Mapping whose iteration callback records that construction consumed it."""

    def __init__(self, values: Mapping[Any, Any], events: list[Any], event: str) -> None:
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

    def __init__(
        self,
        values: Sequence[Any],
        events: list[Any],
        event: str,
        application_state_observer: Callable[[], dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self._values = list(values)
        self._events = events
        self._event = event
        self._application_state_observer = application_state_observer

    def __getitem__(self, index: int | slice) -> Any:
        return self._values[index]

    def __iter__(self) -> Iterator[Any]:
        self._events.append(self._event)
        if self._application_state_observer is not None:
            self._events.append(
                {
                    "event": f"{self._event}.application-state",
                    "attributes": self._application_state_observer(),
                }
            )
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def snapshot_application_attributes(
    application: Any,
    attribute_names: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Record the current public attributes selected by a constructor input."""
    snapshot: dict[str, dict[str, Any]] = {}
    for name in attribute_names:
        try:
            value = getattr(application, name)
        except AttributeError:
            snapshot[name] = {"present": False}
            continue

        attribute: dict[str, Any] = {"present": True, "type": type(value).__name__}
        if type(value) in {dict, list, tuple, set, frozenset}:
            attribute["size"] = len(value)
        snapshot[name] = attribute
    return snapshot


def middleware_with_iterator_override(
    middleware_type: type[Any],
    original_factory: Any,
    yielded_factory: Any,
    yielded_args: Any,
    yielded_kwargs: Mapping[Any, Any],
    yielded_values: Sequence[Any] | None = None,
) -> Any:
    """Create a public Middleware subclass with input-selected iterator values."""

    class InputMiddleware(middleware_type):
        def __iter__(self) -> Iterator[Any]:
            if yielded_values is not None:
                return iter(yielded_values)
            return iter((yielded_factory, yielded_args, yielded_kwargs))

    return InputMiddleware(original_factory)
