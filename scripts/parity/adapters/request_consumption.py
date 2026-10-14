"""Input-driven observations for the public Request body and stream methods."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import Any


class RequestBodyChunk(bytes):
    """Model a valid bytes subclass supplied by an ASGI receive callback."""

    def __new__(
        cls, value: bytes, truthiness_error: dict[str, str] | None = None
    ) -> RequestBodyChunk:
        instance = super().__new__(cls, value)
        instance.truthiness_error = truthiness_error
        return instance

    def __bool__(self) -> bool:
        if self.truthiness_error is not None:
            raise ValueError(self.truthiness_error["message"])
        return len(self) != 0


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return str(value)


def _decode_message(spec: dict[str, Any]) -> dict[str, Any]:
    message = {"type": spec["type"]}
    if spec.get("body_type") == "bytes-subclass":
        message["body"] = RequestBodyChunk(
            base64.b64decode(spec["body_base64"], validate=True),
            spec.get("body_truthiness_error"),
        )
    elif "body_value" in spec:
        message["body"] = spec["body_value"]
    elif "body_base64" in spec:
        message["body"] = base64.b64decode(spec["body_base64"], validate=True)
    if "more_body" in spec:
        message["more_body"] = spec["more_body"]
    return message


def _decode_receive_tape(receive_tape: list[dict[str, Any]]) -> list[Any]:
    return [
        (
            ValueError(event["message"])
            if event["exception_type"] == "ValueError"
            else asyncio.CancelledError(event["message"])
        )
        if event.get("kind") == "raise"
        else _decode_message(event)
        for event in receive_tape
    ]


def _error(operation: str, exc: BaseException) -> dict[str, Any]:
    return {
        "operation": operation,
        "status": "error",
        "error": {
            "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
            "message": str(exc),
        },
    }


def _value(
    operation: str,
    value: Any,
    previous_values: dict[str, Any],
) -> dict[str, Any]:
    result = {"operation": operation, "status": "ok", "value": _safe(value)}
    if operation in {"body", "json"}:
        result["same_object_as_previous"] = (
            value is previous_values[operation] if operation in previous_values else None
        )
        previous_values[operation] = value
    return result


async def _observe(case: dict[str, Any], request_type: Callable[..., Any]) -> dict[str, Any]:
    explicit_none_receive = case["receive"] is None
    receive_tape = [] if explicit_none_receive else case["receive"]
    gates = {index: asyncio.Event() for index in case["blocked_receive_calls"]}
    receive_trace: list[dict[str, Any]] = []
    receive_body_objects: list[Any] = []
    received = 0

    def make_receive(events: list[dict[str, Any]]) -> Callable[[], Any]:
        incoming = _decode_receive_tape(events)
        tape_position = 0

        async def receive() -> dict[str, Any]:
            nonlocal received, tape_position
            call_index = received
            message_index = tape_position
            received += 1
            tape_position += 1
            receive_trace.append({"event": "start", "call": call_index})
            gate = gates.get(call_index)
            if gate is not None:
                await gate.wait()
            message = incoming[message_index]
            if isinstance(message, BaseException):
                receive_trace.append(
                    {
                        "event": "error",
                        "call": call_index,
                        "error": {
                            "class": f"{type(message).__module__}.{type(message).__qualname__}",
                            "message": str(message),
                        },
                    }
                )
                raise message
            if isinstance(message, dict) and message.get("type") == "http.request":
                if "body" in message:
                    receive_body_objects.append(message["body"])
            receive_trace.append({"event": "return", "call": call_index, "message": _safe(message)})
            return message

        return receive

    scope = dict(case["scope"])
    if "headers_base64_pairs" in scope:
        scope["headers"] = [
            (base64.b64decode(name, validate=True), base64.b64decode(value, validate=True))
            for name, value in scope.pop("headers_base64_pairs")
        ]
    request = request_type(scope, None if explicit_none_receive else make_receive(receive_tape))
    streams: dict[str, Any] = {}
    tasks: dict[str, asyncio.Task[Any]] = {}
    previous_values: dict[str, Any] = {}
    observations: list[dict[str, Any]] = []

    for action in case["actions"]:
        operation = action["operation"]
        if operation in {"body", "json"}:
            try:
                value = await getattr(request, operation)()
            except BaseException as exc:
                observations.append(_error(operation, exc))
            else:
                observations.append(_value(operation, value, previous_values))
        elif operation == "form":
            try:
                value = await request.form()
            except BaseException as exc:
                observations.append(_error(operation, exc))
            else:
                observations.append(_value(operation, list(value.multi_items()), previous_values))
                await request.close()
        elif operation == "is-disconnected":
            try:
                value = await request.is_disconnected()
            except BaseException as exc:
                observations.append(_error(operation, exc))
            else:
                observations.append(_value(operation, value, previous_values))
        elif operation == "stream-next":
            stream_id = action["stream_id"]
            if stream_id not in streams:
                streams[stream_id] = request.stream()
            try:
                value = await streams[stream_id].__anext__()
            except BaseException as exc:
                observations.append(_error(operation, exc) | {"stream_id": stream_id})
            else:
                observations.append(
                    _value(operation, value, previous_values)
                    | {
                        "stream_id": stream_id,
                        "value_type": f"{type(value).__module__}.{type(value).__qualname__}",
                        "same_object_as_receive_body": any(
                            value is body_object for body_object in receive_body_objects
                        ),
                    }
                )
        elif operation == "stream-close":
            stream_id = action["stream_id"]
            if stream_id not in streams:
                streams[stream_id] = request.stream()
            try:
                value = await streams[stream_id].aclose()
            except BaseException as exc:
                observations.append(_error(operation, exc) | {"stream_id": stream_id})
            else:
                observations.append(
                    _value(operation, value, previous_values) | {"stream_id": stream_id}
                )
        elif operation == "replace-receive":
            request._receive = make_receive(action["receive"])
            observations.append({"operation": operation, "status": "ok"})
        elif operation == "start-body":
            task_id = action["task_id"]

            async def collect_body() -> Any:
                return await request.body()

            tasks[task_id] = asyncio.create_task(collect_body())
            await asyncio.sleep(0)
            observations.append({"operation": operation, "status": "started", "task_id": task_id})
        elif operation == "await-body":
            task_id = action["task_id"]
            try:
                value = await tasks[task_id]
            except BaseException as exc:
                observations.append(_error(operation, exc) | {"task_id": task_id})
            else:
                observations.append(
                    _value("body", value, previous_values)
                    | {"operation": operation, "task_id": task_id}
                )
        else:
            receive_call = action["receive_call"]
            gates[receive_call].set()
            observations.append(
                {"operation": operation, "receive_call": receive_call, "status": "released"}
            )

    return {
        "actions": observations,
        "receive_calls": received,
        "receive_trace": receive_trace,
    }


def run_request_consumption_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Run only the actions and receive tape declared in one parity input."""
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "request-consumption",
                "status": "ok",
                "value": {"request-consumption": asyncio.run(_observe(case, request_type))},
            }
        ],
    }
