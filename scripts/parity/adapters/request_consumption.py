"""Input-driven observations for the public Request body and stream methods."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable
from typing import Any


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
    if "body_base64" in spec:
        message["body"] = base64.b64decode(spec["body_base64"], validate=True)
    if "more_body" in spec:
        message["more_body"] = spec["more_body"]
    return message


def _error(operation: str, exc: Exception) -> dict[str, Any]:
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
    incoming = [_decode_message(message) for message in case["receive"]]
    gates = {index: asyncio.Event() for index in case["blocked_receive_calls"]}
    receive_trace: list[dict[str, Any]] = []
    received = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        call_index = received
        received += 1
        receive_trace.append({"event": "start", "call": call_index})
        gate = gates.get(call_index)
        if gate is not None:
            await gate.wait()
        message = incoming[call_index]
        receive_trace.append({"event": "return", "call": call_index, "message": _safe(message)})
        return message

    scope = dict(case["scope"])
    if "headers_base64_pairs" in scope:
        scope["headers"] = [
            (base64.b64decode(name, validate=True), base64.b64decode(value, validate=True))
            for name, value in scope.pop("headers_base64_pairs")
        ]
    request = request_type(scope, receive)
    streams: dict[str, Any] = {}
    tasks: dict[str, asyncio.Task[Any]] = {}
    previous_values: dict[str, Any] = {}
    observations: list[dict[str, Any]] = []

    for action in case["actions"]:
        operation = action["operation"]
        if operation in {"body", "json"}:
            try:
                value = await getattr(request, operation)()
            except Exception as exc:
                observations.append(_error(operation, exc))
            else:
                observations.append(_value(operation, value, previous_values))
        elif operation == "form":
            try:
                value = await request.form()
            except Exception as exc:
                observations.append(_error(operation, exc))
            else:
                observations.append(_value(operation, list(value.multi_items()), previous_values))
                await request.close()
        elif operation == "stream-next":
            stream_id = action["stream_id"]
            if stream_id not in streams:
                streams[stream_id] = request.stream()
            try:
                value = await streams[stream_id].__anext__()
            except Exception as exc:
                observations.append(_error(operation, exc) | {"stream_id": stream_id})
            else:
                observations.append(
                    _value(operation, value, previous_values) | {"stream_id": stream_id}
                )
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
            except Exception as exc:
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
