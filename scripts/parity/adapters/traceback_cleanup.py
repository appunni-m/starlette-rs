"""Public exception lifetime and deterministic garbage-collection observations."""

from __future__ import annotations

import gc
import sys
import threading
from typing import Any


class TracebackCleanup:
    def __init__(self, specification: dict[str, Any]) -> None:
        self.specification = specification
        self.caller_thread = threading.current_thread()
        self.retained: list[tuple[BaseException, Any]] = []
        self.finalizers: list[dict[str, Any]] = []
        self.unraisable: list[dict[str, Any]] = []
        self.previous_hook = sys.unraisablehook
        self.automatic_gc = gc.isenabled()

    def __enter__(self) -> TracebackCleanup:
        sys.unraisablehook = self.observe_unraisable
        if not self.specification["automatic_gc"]:
            gc.disable()
        return self

    def __exit__(self, *exception: Any) -> None:
        sys.unraisablehook = self.previous_hook
        if self.automatic_gc:
            gc.enable()
        else:
            gc.disable()

    def observe_unraisable(self, event: Any) -> None:
        self.unraisable.append(
            {
                "class": f"{event.exc_type.__module__}.{event.exc_type.__qualname__}",
                "message": str(event.exc_value),
                "err_msg": event.err_msg,
                "on_caller_thread": threading.current_thread() is self.caller_thread,
            }
        )

    def guard(self, label: str) -> Any:
        observer = self

        class UserObject:
            def __del__(self) -> None:
                observer.finalizers.append(
                    {
                        "label": label,
                        "on_caller_thread": threading.current_thread() is observer.caller_thread,
                    }
                )

        return UserObject()

    def capture(self, error: BaseException) -> None:
        self.retained.append((error, error.__traceback__))

    def snapshot(self) -> dict[str, Any]:
        return {
            "retained_count": len(self.retained),
            "tracebacks_present": [traceback is not None for _, traceback in self.retained],
            "traceback_identity_preserved": [
                error.__traceback__ is traceback for error, traceback in self.retained
            ],
            # GC has no portable finalizer ordering contract. Observe the set of
            # labeled user objects and their thread, retaining every completion.
            "user_finalizers": sorted(self.finalizers, key=lambda item: item["label"]),
            "unraisable": list(self.unraisable),
        }

    def cleanup(self) -> dict[str, Any]:
        for generation in self.specification["collect_generations"]:
            gc.collect(generation)
        retained = self.snapshot()
        self.retained.clear()
        for generation in self.specification["collect_generations"]:
            gc.collect(generation)
        return {"while_retained": retained, "after_release": self.snapshot()}
