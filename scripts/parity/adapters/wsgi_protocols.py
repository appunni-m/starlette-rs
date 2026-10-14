"""Input-driven WSGI queueing, sender ownership, and error/cancellation probes."""

from __future__ import annotations

import asyncio
import base64
import contextvars
import gc
import threading
import weakref
from collections.abc import Iterator
from typing import Any

from scripts.parity.adapters.wsgi_boundary import _scope_from_input

WSGI_PROTOCOL_OPERATION = ("starlette.middleware.wsgi.WSGIMiddleware", "__call__")


def _plain(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value


def run_wsgi_protocol_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.middleware.wsgi import WSGIMiddleware

    app_spec = case["app"]
    context_spec = case["context"]
    action = case["send_action"]
    context = contextvars.ContextVar(context_spec["name"])
    worker_complete = threading.Event()
    worker_observations: list[Any] = []
    send_observations: list[Any] = []
    events: list[Any] = []
    dispatch_task = None
    first_sender_task = None
    incoming = [
        {
            **{key: value for key, value in message.items() if key != "body_base64"},
            "body": base64.b64decode(message["body_base64"], validate=True),
        }
        for message in case["incoming"]
    ]
    received = 0
    callback_roots: list[Any] = []
    lifetime_references: dict[str, Any] = {}
    input_error = (
        {"OSError": OSError, "RuntimeError": RuntimeError}[action["failure"]["class"]](
            action["failure"]["message"]
        )
        if action["failure"] is not None
        else None
    )

    def app(_environ: Any, start_response: Any) -> Iterator[bytes]:
        worker_observations.append({"event": "entry", "context": context.get()})
        context.set(context_spec["worker_value"])
        try:
            start_response(app_spec["status"], app_spec["headers"])
            for chunk in app_spec["chunks_base64"]:
                yield base64.b64decode(chunk, validate=True)
        finally:
            worker_observations.append({"event": "exit", "context": context.get()})
            worker_complete.set()

    class Application:
        def __call__(self, environ: Any, start_response: Any) -> Iterator[bytes]:
            self.callback = start_response
            callback_roots.append(start_response)
            return app(environ, start_response)

    class Scope(dict):
        pass

    async def receive() -> dict[str, Any]:
        nonlocal received
        message = incoming[received]
        received += 1
        return message

    async def send(message: dict[str, Any]) -> None:
        nonlocal first_sender_task
        task = asyncio.current_task()
        if first_sender_task is None:
            first_sender_task = task
        events.append(_plain(message))
        observation = {
            "event_number": len(events),
            "context": context.get(),
            "task_is_dispatch": task is dispatch_task,
            "task_is_first_sender": task is first_sender_task,
        }
        context.set(context_spec["send_value"])
        if len(events) == 1:
            # The timeout is an input stimulus. It releases an implementation
            # that blocks the worker on ASGI send, so the comparison terminates
            # and records whether the worker exhausted while send was held.
            observation["worker_completed_while_send_held"] = await asyncio.to_thread(
                worker_complete.wait, case["hold_timeout_seconds"]
            )
        send_observations.append(observation)
        if len(events) == action["at_event"]:
            if action["kind"] == "raise":
                raise input_error
            if action["kind"] == "cancel-call":
                dispatch_task.cancel()
                await asyncio.Event().wait()

    outcome: dict[str, Any] = {}

    async def dispatch() -> None:
        nonlocal dispatch_task
        dispatch_task = asyncio.current_task()
        context.set(context_spec["caller_value"])
        user_app = Application() if "callback_lifetime" in case else app
        scope = Scope(_scope_from_input(case["scope"]))
        if "callback_lifetime" in case:
            lifetime_references.update({"app": weakref.ref(user_app), "scope": weakref.ref(scope)})
        try:
            await WSGIMiddleware(user_app)(scope, receive, send)
            outcome["completed"] = True
            outcome["error"] = None
        except BaseException as error:
            outcome["completed"] = False
            outcome["error"] = {
                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                "message": str(error),
                "args": _plain(error.args),
                "is_send_error": error is input_error,
                "has_context": error.__context__ is not None,
                "has_cause": error.__cause__ is not None,
                "suppress_context": error.__suppress_context__,
            }
        finally:
            outcome["caller_context_after_call"] = context.get()

    asyncio.run(dispatch())
    if "callback_lifetime" in case:
        generations = case["callback_lifetime"]["collect_generations"]
        for generation in generations:
            gc.collect(generation)
        retained = {
            name: reference() is not None for name, reference in lifetime_references.items()
        }
        callback_roots.clear()
        for generation in generations:
            gc.collect(generation)
        outcome["callback_lifetime"] = {
            "while_retained": retained,
            "after_release": {
                name: reference() is not None for name, reference in lifetime_references.items()
            },
        }
    outcome.update(
        {
            "asgi_events": events,
            "send_observations": send_observations,
            "worker_observations": worker_observations,
            "worker_completed": worker_complete.is_set(),
            "received_message_count": received,
        }
    )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "protocol-results", "status": "ok", "value": {"protocol-results": outcome}}
        ],
    }
