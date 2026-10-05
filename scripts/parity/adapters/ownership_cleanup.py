"""Input-defined collection of public consumer ownership graphs."""

from __future__ import annotations

import gc
import threading
from typing import Any


def observe_ownership(
    specification: dict[str, Any],
    roots: list[Any],
    references: list[Any],
    events: list[Any],
    observer: Any,
    warning_events: list[Any],
) -> dict[str, Any]:
    def snapshot() -> dict[str, Any]:
        return {
            "alive": [reference() is not None for reference in references],
            "events": list(events),
            "user_finalizers": observer.snapshot()["user_finalizers"],
            "unraisable": list(observer.unraisable),
            "warnings": sorted(
                [
                    {
                        "class": f"{event.category.__module__}.{event.category.__qualname__}",
                        "message": str(event.message),
                    }
                    for event in warning_events
                ],
                key=lambda item: (item["class"], item["message"]),
            ),
        }

    def collect(release: bool) -> None:
        if release:
            roots.clear()
        for generation in specification["collect_generations"]:
            gc.collect(generation)

    def drive_collection(release: bool) -> None:
        if specification.get("thread", "caller") == "worker":
            worker = threading.Thread(target=collect, args=(release,))
            worker.start()
            worker.join()
        else:
            collect(release)

    drive_collection(False)
    retained = snapshot()
    drive_collection(True)
    return {"while_retained": retained, "after_release": snapshot()}
