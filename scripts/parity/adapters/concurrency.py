"""Shared input materialization for Python-callable concurrency parity cases."""

from __future__ import annotations

import asyncio
import builtins
import contextvars
import threading
import warnings
from collections.abc import Callable
from types import MappingProxyType
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
    callable_behavior = case["call"]["callable_behavior"]
    if callable_behavior["kind"] == "limiter-workload":
        return _run_threadpool_limiter_case(case, run_in_threadpool, callable_behavior)

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
        contextvar_behavior = (
            callable_behavior if callable_behavior["kind"] == "contextvar" else None
        )
        context_variable: contextvars.ContextVar[Any] | None = None
        if contextvar_behavior is not None:
            context_variable = contextvars.ContextVar(contextvar_behavior["name"])
            context_variable.set(contextvar_behavior["initial_value"])
        if callable_behavior["kind"] == "raise":
            exception_type = getattr(builtins, callable_behavior["exception_type"])
            exception_instance = exception_type(callable_behavior["message"])
        returned_value = (
            contextvar_behavior["result_value"]
            if contextvar_behavior is not None
            else callable_behavior.get("value")
        )
        callback_state: dict[str, Any] = {
            "args": None,
            "kwargs": None,
            "invocation_count": 0,
            "worker_thread_role": None,
            "release_observed": False,
            "contextvar_worker_initial": None,
            "contextvar_worker_after_write": None,
        }
        cancellation_enabled = "cancellation" in spec
        cancellation_scope: Any = None
        cancellation_state: dict[str, Any] | None = None
        if cancellation_enabled:
            import anyio

            cancellation_scope = anyio.CancelScope()
            cancellation_state = {
                "outcome": "pending",
                "exception": None,
                "exception_type": None,
                "scope_cancelled_caught": False,
            }

        def callback(*args: Any, **kwargs: Any) -> Any:
            callback_state["invocation_count"] += 1
            callback_state["args"] = _json_safe(args)
            callback_state["kwargs"] = _json_safe(kwargs)
            callback_state["worker_thread_role"] = (
                "caller" if threading.get_ident() == caller_thread_id else "worker"
            )
            if context_variable is not None and contextvar_behavior is not None:
                callback_state["contextvar_worker_initial"] = _json_safe(context_variable.get())
                context_variable.set(contextvar_behavior["worker_value"])
                callback_state["contextvar_worker_after_write"] = _json_safe(context_variable.get())
            try:
                trace.append({"call_id": spec["call_id"], "event": "callback-start"})
                trace.append({"call_id": spec["call_id"], "event": "worker-gate-held"})
                loop.call_soon_threadsafe(callback_entered.set)
                if not callback_released.wait(spec["release_timeout_ms"] / 1000):
                    trace.append({"call_id": spec["call_id"], "event": "worker-gate-timeout"})
                    raise TimeoutError("input-defined worker gate timed out")
                callback_state["release_observed"] = True
                if callable_behavior["kind"] == "raise":
                    trace.append({"call_id": spec["call_id"], "event": "callback-raise"})
                    if exception_instance is None:
                        raise RuntimeError("missing input-defined callback exception")
                    raise exception_instance
                trace.append({"call_id": spec["call_id"], "event": "callback-return"})
                return returned_value
            finally:
                if cancellation_enabled:
                    trace.append({"call_id": spec["call_id"], "event": "worker-complete"})
                callback_exited.set()

        async def call_with_scope() -> Any:
            if cancellation_scope is None or cancellation_state is None:
                return await run_in_threadpool(callback, *spec["args"], **spec["kwargs"])

            try:
                with cancellation_scope:
                    try:
                        result = await run_in_threadpool(callback, *spec["args"], **spec["kwargs"])
                    except BaseException as error:
                        cancellation_state["outcome"] = "raise"
                        cancellation_state["exception"] = error
                        cancellation_state["exception_type"] = (
                            f"{type(error).__module__}.{type(error).__qualname__}"
                        )
                        trace.append({"call_id": spec["call_id"], "event": "await-raise"})
                        raise
                    else:
                        cancellation_state["outcome"] = "return"
                        trace.append({"call_id": spec["call_id"], "event": "await-return"})
                        return result
            finally:
                cancellation_state["scope_cancelled_caught"] = cancellation_scope.cancelled_caught
                trace.append({"call_id": spec["call_id"], "event": "call-task-finished"})

        trace.append({"call_id": spec["call_id"], "event": "call-start"})
        call_task = asyncio.create_task(
            call_with_scope()
            if cancellation_enabled
            else run_in_threadpool(callback, *spec["args"], **spec["kwargs"])
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
        if cancellation_enabled:
            if cancellation_scope is None:
                raise RuntimeError("input-defined cancellation scope was not created")
            trace.append({"call_id": spec["call_id"], "event": "cancellation-request"})
            cancellation_scope.cancel()
        for marker in spec["event_loop_checkpoints"]:
            await asyncio.sleep(0)
            checkpoint = {
                "marker": marker,
                "callback_held": not callback_exited.is_set(),
            }
            if cancellation_enabled:
                checkpoint["call_task_done"] = call_task.done()
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
        cancellation_observation: dict[str, Any] | None = None
        if cancellation_enabled:
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(call_task), spec["release_timeout_ms"] / 1000 + 5
                )
                call_task_outcome = "return"
            except asyncio.TimeoutError as error:
                await asyncio.gather(call_task, return_exceptions=True)
                raise RuntimeError(
                    "input-defined cancellation call did not complete after worker release"
                ) from error
            except Exception as error:
                call_task_outcome = "raise"
                propagated_exception = error
                if cancellation_state is not None and cancellation_state["exception"] is None:
                    cancellation_state["outcome"] = "raise"
                    cancellation_state["exception"] = error
                    cancellation_state["exception_type"] = (
                        f"{type(error).__module__}.{type(error).__qualname__}"
                    )

            if cancellation_state is not None:
                helper_cancellation_caught = cancellation_state["scope_cancelled_caught"]
                helper_outcome = (
                    "cancelled" if helper_cancellation_caught else cancellation_state["outcome"]
                )
                worker_complete_index = next(
                    (
                        index
                        for index, event in enumerate(trace)
                        if event["event"] == "worker-complete"
                    ),
                    None,
                )
                call_finished_index = next(
                    (
                        index
                        for index, event in enumerate(trace)
                        if event["event"] == "call-task-finished"
                    ),
                    None,
                )
                worker_completed_before_call_task = (
                    worker_complete_index is not None
                    and call_finished_index is not None
                    and worker_complete_index < call_finished_index
                )
                worker_held_through_checkpoints = all(
                    checkpoint["callback_held"] for checkpoint in checkpoints
                )
                call_task_completed_while_worker_held = any(
                    checkpoint["call_task_done"] and checkpoint["callback_held"]
                    for checkpoint in checkpoints
                )
                cancellation_observation = {
                    "cancel_scope_cancelled_caught": helper_cancellation_caught,
                    "helper_outcome": helper_outcome,
                    "helper_exception_type": cancellation_state["exception_type"],
                    "call_task_outcome": call_task_outcome,
                    "worker_held_through_checkpoints": worker_held_through_checkpoints,
                    "call_task_completed_while_worker_held": (
                        call_task_completed_while_worker_held
                    ),
                    "worker_completed_before_call_task": (worker_completed_before_call_task),
                    "cancellation_waited_for_worker_completion": (
                        worker_held_through_checkpoints
                        and not call_task_completed_while_worker_held
                        and worker_completed_before_call_task
                    ),
                }
        else:
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
                "contextvar_observation": (
                    {
                        "worker_initial_value": callback_state["contextvar_worker_initial"],
                        "worker_value_after_write": callback_state["contextvar_worker_after_write"],
                        "caller_value_after_worker": _json_safe(context_variable.get()),
                    }
                    if context_variable is not None
                    else None
                ),
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
                    if propagated_exception is not None and not cancellation_enabled
                    else None
                ),
                **(
                    {"cancellation_observation": cancellation_observation}
                    if cancellation_observation is not None
                    else {}
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


def _run_threadpool_limiter_case(
    case: dict[str, Any],
    run_in_threadpool: Callable[..., Any],
    workload: dict[str, Any],
) -> dict[str, Any]:
    """Measure shared AnyIO capacity with Starlette and direct AnyIO calls."""

    async def run() -> dict[str, Any]:
        import anyio.to_thread

        limiter = anyio.to_thread.current_default_thread_limiter()
        original_tokens = limiter.total_tokens
        configured_tokens = workload["total_tokens"]
        start_timeout_ms = case["call"]["start_timeout_ms"]
        release_timeout_ms = case["call"]["release_timeout_ms"]
        if configured_tokens == original_tokens:
            raise RuntimeError(
                "input-defined limiter capacity must change the live default token count"
            )

        loop = asyncio.get_running_loop()
        caller_thread_id = threading.get_ident()
        started: asyncio.Queue[str] = asyncio.Queue()
        release_gates = {task["task_id"]: threading.Event() for task in workload["tasks"]}
        state_lock = threading.Lock()
        active_task_ids: set[str] = set()
        task_thread_roles: dict[str, str] = {}
        maximum_active_workers = 0

        def worker(task_id: str) -> str:
            nonlocal maximum_active_workers
            with state_lock:
                active_task_ids.add(task_id)
                task_thread_roles[task_id] = (
                    "caller" if threading.get_ident() == caller_thread_id else "worker"
                )
                maximum_active_workers = max(maximum_active_workers, len(active_task_ids))
            loop.call_soon_threadsafe(started.put_nowait, task_id)
            try:
                if not release_gates[task_id].wait(release_timeout_ms / 1000):
                    raise TimeoutError("input-defined limiter worker gate timed out")
                return task_id
            finally:
                with state_lock:
                    active_task_ids.remove(task_id)

        async def invoke(task: dict[str, str]) -> str:
            task_id = task["task_id"]
            if task["consumer"] == "starlette":
                return await run_in_threadpool(worker, task_id)
            return await anyio.to_thread.run_sync(worker, task_id)

        tasks: list[asyncio.Task[str]] = []
        observation: dict[str, Any] | None = None
        limiter.total_tokens = configured_tokens
        try:
            tasks = [asyncio.create_task(invoke(task)) for task in workload["tasks"]]
            for _ in range(configured_tokens):
                await asyncio.wait_for(started.get(), start_timeout_ms / 1000)

            queued_count = len(workload["tasks"]) - configured_tokens
            queue_deadline = loop.time() + workload["queue_timeout_ms"] / 1000
            while True:
                statistics = limiter.statistics()
                with state_lock:
                    active_count = len(active_task_ids)
                if statistics.tasks_waiting == queued_count and active_count == configured_tokens:
                    break
                if loop.time() >= queue_deadline:
                    raise RuntimeError(
                        "input-defined limiter tasks did not fill capacity and queue"
                    )
                await asyncio.sleep(0.001)

            with state_lock:
                active_at_capacity = sorted(active_task_ids)
                max_active = maximum_active_workers
            observation = {
                "default_total_tokens": original_tokens,
                "configured_total_tokens": configured_tokens,
                "borrowed_tokens_at_capacity": statistics.borrowed_tokens,
                "waiting_tasks_at_capacity": statistics.tasks_waiting,
                "active_task_ids_at_capacity": active_at_capacity,
                "maximum_active_workers": max_active,
            }
            for gate in release_gates.values():
                gate.set()
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                release_timeout_ms / 1000 + 5,
            )
            if any(isinstance(outcome, BaseException) for outcome in outcomes):
                raise RuntimeError("an input-defined limiter callback did not complete")
            with state_lock:
                thread_roles = dict(task_thread_roles)
            observation["tasks"] = sorted(
                [
                    {
                        "task_id": task_spec["task_id"],
                        "consumer": task_spec["consumer"],
                        "worker_thread_role": thread_roles[task_spec["task_id"]],
                        "result": outcome,
                    }
                    for task_spec, outcome in zip(workload["tasks"], outcomes, strict=True)
                ],
                key=lambda task_result: task_result["task_id"],
            )
        finally:
            for gate in release_gates.values():
                gate.set()
            try:
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        release_timeout_ms / 1000 + 5,
                    )
            finally:
                limiter.total_tokens = original_tokens

        restored_tokens = limiter.total_tokens
        if restored_tokens != original_tokens:
            raise RuntimeError("input-defined limiter cleanup did not restore token capacity")
        if observation is None:
            raise RuntimeError("input-defined limiter workload produced no capacity observation")
        observation["restored_total_tokens"] = restored_tokens
        execution_trace = [
            {"event": "default-capacity-observed", "total_tokens": original_tokens},
            {"event": "limiter-capacity-configured", "total_tokens": configured_tokens},
            {
                "event": "capacity-and-waiters-observed",
                "borrowed_tokens": observation["borrowed_tokens_at_capacity"],
                "tasks_waiting": observation["waiting_tasks_at_capacity"],
            },
            {"event": "worker-gates-released"},
            {"event": "callbacks-completed"},
            {"event": "default-capacity-restored", "total_tokens": restored_tokens},
        ]
        return {"call": observation, "execution_trace": execution_trace}

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


def _exception_observation(error: BaseException) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "class": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
    }
    if isinstance(error, getattr(builtins, "BaseExceptionGroup", ())):
        observation["exceptions"] = [_exception_observation(item) for item in error.exceptions]
    return observation


def _warning_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    if normalized == "starlette/concurrency.py" or normalized.endswith("/starlette/concurrency.py"):
        return "starlette/concurrency.py"
    return normalized


def run_until_first_complete_case(
    case: dict[str, Any], run_until_first_complete: Callable[..., Any]
) -> dict[str, Any]:
    """Materialize the input-defined event and callback protocol for both Python lanes."""
    trace: list[dict[str, Any]] = []

    async def run() -> dict[str, Any]:
        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always")
            events = {event_id: asyncio.Event() for event_id in case["events"]}

            async def callback(task_id: str, actions: list[dict[str, Any]]) -> None:
                trace.append({"actor": task_id, "event": "task-started"})
                try:
                    for action in actions:
                        action_kind = action["action"]
                        if action_kind == "set-event":
                            events[action["event_id"]].set()
                            trace.append(
                                {
                                    "actor": task_id,
                                    "event": "event-set",
                                    "event_id": action["event_id"],
                                }
                            )
                        elif action_kind == "wait-event":
                            trace.append(
                                {
                                    "actor": task_id,
                                    "event": "event-wait-started",
                                    "event_id": action["event_id"],
                                }
                            )
                            await events[action["event_id"]].wait()
                            trace.append(
                                {
                                    "actor": task_id,
                                    "event": "event-wait-finished",
                                    "event_id": action["event_id"],
                                }
                            )
                        elif action_kind == "checkpoint":
                            trace.append({"actor": task_id, "event": "checkpoint-started"})
                            await asyncio.sleep(0)
                            trace.append({"actor": task_id, "event": "checkpoint-finished"})
                        else:
                            exception_type = getattr(builtins, action["exception_type"])
                            raise exception_type(action["message"])
                    trace.append({"actor": task_id, "event": "task-returned"})
                except asyncio.CancelledError as error:
                    trace.append(
                        {
                            "actor": task_id,
                            "event": "task-cancelled",
                            "exception": _exception_observation(error),
                        }
                    )
                    raise
                except BaseException as error:
                    trace.append(
                        {
                            "actor": task_id,
                            "event": "task-raised",
                            "exception": _exception_observation(error),
                        }
                    )
                    raise
                finally:
                    trace.append({"actor": task_id, "event": "task-finalized"})

            callbacks = []
            for task in case["tasks"]:
                callback_kwargs = {"task_id": task["task_id"], "actions": task["actions"]}
                if case.get("kwargs_container") == "mappingproxy":
                    callback_kwargs = MappingProxyType(callback_kwargs)
                callbacks.append((callback, callback_kwargs))
            construction_emitted_no_warning = not recorded_warnings
            return_value: Any = None
            raised_exception: dict[str, Any] | None = None

            async def invoke() -> Any:
                external_cancel_event = case.get("external_cancel_after_event_id")
                if external_cancel_event is None:
                    return await run_until_first_complete(*callbacks)

                helper_task = asyncio.create_task(run_until_first_complete(*callbacks))

                async def cancel_after_event() -> None:
                    await events[external_cancel_event].wait()
                    if not helper_task.done():
                        trace.append(
                            {
                                "actor": "external-driver",
                                "event": "helper-cancel-requested",
                                "event_id": external_cancel_event,
                            }
                        )
                        helper_task.cancel()

                cancellation_driver = asyncio.create_task(cancel_after_event())
                try:
                    return await helper_task
                finally:
                    cancellation_driver.cancel()
                    await asyncio.gather(cancellation_driver, return_exceptions=True)

            try:
                return_value = await invoke()
            except BaseException as error:
                raised_exception = _exception_observation(error)

            warnings_observed = [
                {
                    "category": f"{item.category.__module__}.{item.category.__qualname__}",
                    "message": str(item.message),
                    "filename": _warning_filename(item.filename),
                    "line": item.lineno,
                }
                for item in recorded_warnings
            ]
            return {
                "event_trace": trace,
                "event_states": [
                    {"event_id": event_id, "is_set": event.is_set()}
                    for event_id, event in events.items()
                ],
                "warnings": warnings_observed,
                "construction_emitted_no_warning": construction_emitted_no_warning,
                "return_value": _json_safe(return_value),
                "raised_exception": raised_exception,
            }

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "run_until_first_complete",
                "status": "ok",
                "value": asyncio.run(run()),
            }
        ],
    }
