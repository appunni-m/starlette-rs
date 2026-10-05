"""Public response/coroutine cycles and suspended user callback finalization."""

from __future__ import annotations

import gc
import threading
import warnings
import weakref
from typing import Any

from scripts.parity.adapters.ownership_cleanup import observe_ownership
from scripts.parity.adapters.traceback_cleanup import TracebackCleanup


def _graph(case: dict[str, Any], observer: TracebackCleanup) -> tuple[Any, ...]:
    from starlette import responses

    from scripts.parity.adapters.response_consumer import _content, _observe

    spec = case["ownership"]
    construction = case["construction"]
    events: list[Any] = []
    guard = observer.guard(spec["guard_label"])

    class Suspension:
        def __await__(self) -> Any:
            yield spec["suspension_token"]

    class UserCallback:
        def __init__(self) -> None:
            self.guard = guard
            self.peer: Any = None

        async def __call__(self, *messages: Any) -> Any:
            events.append({"event": "callback-start", "messages": _observe(messages)})
            try:
                await Suspension()
            finally:
                events.append(
                    {
                        "event": "callback-finally",
                        "on_caller_thread": threading.current_thread() is observer.caller_thread,
                    }
                )

        def __del__(self) -> None:
            observer.finalizers.append(
                {
                    "label": spec["callback_label"],
                    "on_caller_thread": threading.current_thread() is observer.caller_thread,
                }
            )

    class UserHeader(bytes):
        pass

    callback = UserCallback()
    constructor = getattr(responses, case["surface"].removeprefix("starlette.responses."))
    response = constructor(_content(construction["content"]), **construction["kwargs"])
    roots: list[Any] = [response]
    if spec["kind"] == "raw-header":
        value = UserHeader(spec["header_value"].encode("latin-1"))
        value.owner = callback
        response.raw_headers.append((spec["header_name"].encode("latin-1"), value))
        callback.peer = response
        if spec["cache_headers"]:
            roots.append(response.headers)
    else:

        async def send(message: dict[str, Any]) -> None:
            events.append({"event": "send", "message": _observe(message)})

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        if spec["kind"] == "send":
            continuation = response(dict(case["scope"]), receive, callback)
        elif spec["kind"] == "receive":
            response.background = callback
            continuation = response(dict(case["scope"]), callback, send)
        else:
            response.background = callback
            continuation = response(dict(case["scope"]), receive, send)
        callback.peer = continuation
        roots.append(continuation)
        iterator = continuation.__await__()
        roots.append(iterator)
        events.append({"yielded": next(iterator)})
    return roots, [weakref.ref(callback), weakref.ref(guard)], events


def run_response_ownership_case(case: dict[str, Any]) -> dict[str, Any]:
    gc.collect()
    specification = case["ownership"]["garbage_collection"]
    with TracebackCleanup(specification) as observer:
        with warnings.catch_warnings(record=True) as warning_events:
            warnings.simplefilter("always")
            roots, references, events = _graph(case, observer)
            observation = observe_ownership(
                specification, roots, references, events, observer, warning_events
            )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "response-consumer",
                "status": "ok",
                "value": {"response-consumer": observation},
            }
        ],
    }
