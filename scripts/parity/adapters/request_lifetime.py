"""Public Request ownership graphs driven only by the supplied input."""

from __future__ import annotations

import gc
import threading
import warnings
import weakref
from typing import Any

from scripts.parity.adapters.ownership_cleanup import observe_ownership
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
    operation = case["request_operation"]
    if operation == "headers":

        class UserHeader(bytes):
            pass

        index, component = case["operation_arguments"]
        pair = list(scope["headers"][index])
        value = UserHeader(pair[component])
        value.owner = receive
        pair[component] = value
        scope["headers"][index] = tuple(pair)
    request = request_type(scope, receive)
    roots: list[Any] = [request, receive]
    if operation == "scope":
        request.scope[case["cycle_key"]] = request
    elif operation == "receive":
        receive.peer = request
    elif operation == "state":
        setattr(request.state, case["cycle_key"], request)
    elif operation == "headers":
        roots.append(request.headers)
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

            observation = observe_ownership(
                case["garbage_collection"], roots, references, events, observer, warning_events
            )
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
