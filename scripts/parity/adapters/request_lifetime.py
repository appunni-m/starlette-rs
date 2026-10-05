"""Public Request ownership graphs driven only by the supplied input."""

from __future__ import annotations

import gc
import threading
import warnings
import weakref
from typing import Any

from scripts.parity.adapters.request_consumption import _decode_message
from scripts.parity.adapters.traceback_cleanup import TracebackCleanup


def _graph(
    case: dict[str, Any], request_type: type[Any], observer: TracebackCleanup
) -> tuple[list[Any], list[weakref.ReferenceType[Any]], list[Any]]:
    events: list[Any] = []
    guard = observer.guard(case["guard_label"])

    class Suspension:
        def __await__(self) -> Any:
            yield case["suspension_token"]

    class Receive:
        def __init__(self) -> None:
            self.guard = guard
            self.peer: Any = None

        async def __call__(self) -> dict[str, Any]:
            events.append("receive-start")
            try:
                await Suspension()
                return _decode_message(case["receive_message"])
            finally:
                events.append("receive-finally")

        def __del__(self) -> None:
            observer.finalizers.append(
                {
                    "label": case["receive_label"],
                    "on_caller_thread": threading.current_thread() is observer.caller_thread,
                }
            )

    receive = Receive()
    scope = dict(case["scope"])
    scope["headers"] = [
        (key.encode("latin-1"), value.encode("latin-1")) for key, value in scope["headers"]
    ]
    request = request_type(scope, receive)
    operation = case["request_operation"]
    roots: list[Any] = [request, receive]
    if operation == "scope":
        request.scope[case["cycle_key"]] = request
    elif operation == "receive":
        receive.peer = request
    else:
        if operation == "stream":
            continuation = request.stream()
        elif operation.startswith("stream-"):
            stream = request.stream()
            roots.append(stream)
            method = operation.removeprefix("stream-")
            arguments = case["operation_arguments"]
            if method == "athrow":
                arguments = [RuntimeError(*arguments)]
            continuation = getattr(stream, method)(*arguments)
        elif operation == "form-enter":
            context = request.form()
            roots.append(context)
            continuation = context.__aenter__()
        else:
            continuation = getattr(request, operation)(*case["operation_arguments"])
        roots.append(continuation)
        receive.peer = continuation
        if case["drive"] == "suspend":
            iterator = continuation.__await__()
            roots.append(iterator)
            events.append({"yielded": next(iterator)})
    return roots, [weakref.ref(receive), weakref.ref(guard)], events


def run_request_lifetime_case(case: dict[str, Any], request_type: type[Any]) -> dict[str, Any]:
    # Discard prior consumer garbage before installing this case's observers.
    gc.collect()
    with TracebackCleanup(case["garbage_collection"]) as observer:
        with warnings.catch_warnings(record=True) as warning_events:
            warnings.simplefilter("always")
            roots, references, events = _graph(case, request_type, observer)

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

            for generation in case["garbage_collection"]["collect_generations"]:
                gc.collect(generation)
            retained = snapshot()
            roots.clear()
            for generation in case["garbage_collection"]["collect_generations"]:
                gc.collect(generation)
            observation = {"while_retained": retained, "after_release": snapshot()}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "request-lifetime",
                "status": "ok",
                "value": {"request-lifetime": observation},
            }
        ],
    }
