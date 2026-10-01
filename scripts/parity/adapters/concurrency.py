"""Shared input materialization for Python-callable concurrency parity cases."""

from __future__ import annotations

import asyncio
import builtins
import threading
from collections.abc import Callable
from typing import Any


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        import base64

        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def run_threadpool_case(
    case: dict[str, Any], run_in_threadpool: Callable[..., Any]
) -> dict[str, Any]:
    """Run the case-declared sync callbacks through the selected public helper."""
    trace: list[dict[str, Any]] = []

    async def run() -> dict[str, Any]:
        spec = case["call"]
        loop = asyncio.get_running_loop()
        caller_thread_id = threading.get_ident()
        callback_entered = asyncio.Event()
        callback_released = threading.Event()
        callback_exited = threading.Event()
        callable_behavior = spec["callable_behavior"]
        exception_instance: BaseException | None = None
        if callable_behavior["kind"] == "raise":
            exception_type = getattr(builtins, callable_behavior["exception_type"])
            exception_instance = exception_type(callable_behavior["message"])
        returned_value = callable_behavior.get("value")
        callback_state: dict[str, Any] = {
            "args": None,
            "kwargs": None,
            "invocation_count": 0,
            "worker_thread_role": None,
            "release_observed": False,
        }

        def callback(*args: Any, **kwargs: Any) -> Any:
            callback_state["invocation_count"] += 1
            callback_state["args"] = _json_safe(args)
            callback_state["kwargs"] = _json_safe(kwargs)
            callback_state["worker_thread_role"] = (
                "caller" if threading.get_ident() == caller_thread_id else "worker"
            )
            trace.append({"call_id": spec["call_id"], "event": "callback-start"})
            trace.append({"call_id": spec["call_id"], "event": "worker-gate-held"})
            loop.call_soon_threadsafe(callback_entered.set)
            if not callback_released.wait(spec["release_timeout_ms"] / 1000):
                trace.append({"call_id": spec["call_id"], "event": "worker-gate-timeout"})
                callback_exited.set()
                raise TimeoutError("input-defined worker gate timed out")
            callback_state["release_observed"] = True
            if callable_behavior["kind"] == "raise":
                trace.append({"call_id": spec["call_id"], "event": "callback-raise"})
                callback_exited.set()
                if exception_instance is None:
                    raise RuntimeError("missing input-defined callback exception")
                raise exception_instance
            trace.append({"call_id": spec["call_id"], "event": "callback-return"})
            callback_exited.set()
            return returned_value

        trace.append({"call_id": spec["call_id"], "event": "call-start"})
        call_task = asyncio.create_task(
            run_in_threadpool(callback, *spec["args"], **spec["kwargs"])
        )
        try:
            await asyncio.wait_for(callback_entered.wait(), spec["start_timeout_ms"] / 1000)
        except asyncio.TimeoutError as error:
            callback_released.set()
            await asyncio.gather(call_task, return_exceptions=True)
            raise RuntimeError(
                "input-defined worker callback did not enter before its deadline"
            ) from error

        checkpoints: list[dict[str, Any]] = []
        trace.append({"call_id": spec["call_id"], "event": "event-loop-observed-entry"})
        for marker in spec["event_loop_checkpoints"]:
            await asyncio.sleep(0)
            checkpoint = {
                "marker": marker,
                "callback_held": not callback_exited.is_set(),
            }
            checkpoints.append(checkpoint)
            trace.append(
                {
                    "call_id": spec["call_id"],
                    "event": "event-loop-progress",
                    **checkpoint,
                }
            )

        trace.append({"call_id": spec["call_id"], "event": "worker-release"})
        callback_released.set()
        result: Any = None
        propagated_exception: BaseException | None = None
        try:
            result = await call_task
            trace.append({"call_id": spec["call_id"], "event": "await-return"})
        except Exception as error:
            propagated_exception = error
            trace.append({"call_id": spec["call_id"], "event": "await-raise"})

        return {
            "call": {
                "call_id": spec["call_id"],
                "arguments_seen": {
                    "args": callback_state["args"],
                    "kwargs": callback_state["kwargs"],
                },
                "invocation_count": callback_state["invocation_count"],
                "worker_thread_role": callback_state["worker_thread_role"],
                "worker_gate_release_observed": callback_state["release_observed"],
                "event_loop_checkpoints": checkpoints,
                "event_loop_progress_while_worker_held": bool(checkpoints)
                and all(checkpoint["callback_held"] for checkpoint in checkpoints),
                "result": (
                    {
                        "value": _json_safe(result),
                        "type": f"{type(result).__module__}.{type(result).__qualname__}",
                        "same_object_as_callback_return": result is returned_value,
                    }
                    if propagated_exception is None
                    else None
                ),
                "exception": (
                    {
                        "class": (
                            f"{type(propagated_exception).__module__}."
                            f"{type(propagated_exception).__qualname__}"
                        ),
                        "message": str(propagated_exception),
                        "same_instance_as_callback_exception": (
                            propagated_exception is exception_instance
                        ),
                    }
                    if propagated_exception is not None
                    else None
                ),
            },
            "execution_trace": trace,
        }

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "run_in_threadpool",
                "status": "ok",
                "value": asyncio.run(run()),
            }
        ],
    }


def run_iterate_in_threadpool_case(
    case: dict[str, Any], iterate_in_threadpool: Callable[[Any], Any]
) -> dict[str, Any]:
    """Drive the input-defined iterable and async-generator protocol actions."""

    async def run() -> dict[str, Any]:
        caller_thread_id = threading.get_ident()
        trace: list[dict[str, Any]] = []

        def thread_role() -> str:
            return "caller" if threading.get_ident() == caller_thread_id else "worker"

        class InputIterable:
            def __init__(self, items: list[Any], stream_trace: list[dict[str, Any]]) -> None:
                self.items = items
                self.trace = stream_trace
                self.index = 0

            def __iter__(self) -> InputIterable:
                self.trace.append({"event": "iter", "thread_role": thread_role()})
                return self

            def __next__(self) -> Any:
                index = self.index
                role = thread_role()
                if index >= len(self.items):
                    self.trace.append(
                        {
                            "event": "next",
                            "index": index,
                            "thread_role": role,
                            "outcome": "stop-iteration",
                        }
                    )
                    raise StopIteration
                value = self.items[index]
                self.index += 1
                self.trace.append(
                    {
                        "event": "next",
                        "index": index,
                        "thread_role": role,
                        "outcome": "yield",
                        "value": _json_safe(value),
                    }
                )
                return value

        items = case["iterable"]["items"]
        yielded_items: list[Any] = []
        async for value in iterate_in_threadpool(InputIterable(items, trace)):
            yielded_items.append(_json_safe(value))

        streams = {
            stream["stream_id"]: iterate_in_threadpool(InputIterable(stream["items"], []))
            for stream in case["protocol"]["streams"]
        }
        exception_types = {
            "StopAsyncIteration": StopAsyncIteration,
            "StopIteration": StopIteration,
            "ValueError": ValueError,
        }

        def decode_arguments(arguments: list[dict[str, Any]]) -> list[Any]:
            return [
                exception_types[argument["name"]]
                if argument["kind"] == "exception-class"
                else argument["value"]
                for argument in arguments
            ]

        protocol_trace: list[dict[str, Any]] = []
        for action in case["protocol"]["actions"]:
            stream = streams[action["stream_id"]]
            operation = action["operation"]
            record: dict[str, Any] = {
                "stream_id": action["stream_id"],
                "operation": operation,
            }
            try:
                if operation == "next":
                    value = await stream.__anext__()
                    record.update({"status": "ok", "value": _json_safe(value)})
                elif operation == "athrow":
                    await stream.athrow(*decode_arguments(action["arguments"]))
                    record["status"] = "ok"
                else:
                    awaitable = getattr(stream, action["awaitable_operation"])(
                        *decode_arguments(action["awaitable_arguments"])
                    )
                    awaitable.throw(*decode_arguments(action["throw_arguments"]))
                    record["status"] = "ok"
            except StopAsyncIteration:
                record["status"] = "exhausted"
            except BaseException as error:
                cause = error.__cause__
                record.update(
                    {
                        "status": "error",
                        "error": {
                            "class": type(error).__name__,
                            "message": str(error),
                            "cause": (
                                {
                                    "class": type(cause).__name__,
                                    "message": str(cause),
                                }
                                if cause is not None
                                else None
                            ),
                            "suppress_context": bool(error.__suppress_context__),
                        },
                    }
                )
            protocol_trace.append(record)
        return {
            "yielded_items": yielded_items,
            "iteration_trace": trace,
            "termination": "exhausted",
            "protocol_trace": protocol_trace,
        }

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "iterate_in_threadpool",
                "status": "ok",
                "value": asyncio.run(run()),
            }
        ],
    }
