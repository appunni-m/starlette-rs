"""Public UploadFile worker I/O with input-controlled cancellation barriers."""

from __future__ import annotations

import asyncio
import base64
import threading
from collections.abc import Callable
from typing import Any

import anyio


class UploadWorkerProbe:
    """Observe the submitted user file method and the public await outcome."""

    def __init__(
        self, specification: dict[str, Any], events: list[Any], caller_thread: Any, guard: Any
    ) -> None:
        self.specification = specification
        self.events = events
        self.caller_thread = caller_thread
        self.started = threading.Event()
        self.completed = threading.Event()
        self.released = threading.Event()
        self.task_finished = threading.Event()
        self.lock = threading.Lock()
        self.release_source: str | None = None
        self.worker_thread: threading.Thread | None = None
        self.scope: Any = None
        self.armed = True
        self.error: BaseException | None = None
        error_input = specification["injected_error"]
        if error_input is not None:
            exception_type = {"OSError": OSError, "RuntimeError": RuntimeError}[
                error_input["class"]
            ]
            self.error = exception_type(error_input["message"])
            self.error.guard = guard

    def release(self, source: str) -> None:
        with self.lock:
            if self.release_source is None:
                self.release_source = source
                self.events.append({"event": "worker-release", "source": source})
                self.released.set()

    def call(self, method: str, operation: Callable[[], Any]) -> Any:
        if not self.armed or method != self.specification["method"]:
            return operation()
        self.armed = False
        self.worker_thread = threading.current_thread()
        self.events.append(
            {
                "event": "worker-enter",
                "method": method,
                "on_caller_thread": self.worker_thread is self.caller_thread,
            }
        )
        self.started.set()
        try:
            self.released.wait()
            if self.error is not None:
                self.events.append({"event": "worker-raise", "method": method})
                raise self.error
            value = operation()
            self.events.append({"event": "worker-return", "method": method})
            return value
        finally:
            self.completed.set()

    async def wait_for(self, event: threading.Event) -> None:
        with anyio.fail_after(self.specification["watchdog_seconds"] * 2):
            await anyio.to_thread.run_sync(event.wait, abandon_on_cancel=True)

    def error_value(self, error: BaseException) -> dict[str, Any]:
        def name(value: BaseException | None) -> str | None:
            return None if value is None else f"{type(value).__module__}.{type(value).__qualname__}"

        return {
            "class": name(error),
            "args": list(error.args),
            "message": str(error),
            "is_injected_error": error is self.error,
            "cause_class": name(error.__cause__),
            "context_class": name(error.__context__),
            "suppress_context": error.__suppress_context__,
        }

    def run(self, upload: Any) -> dict[str, Any]:
        arguments = list(self.specification["arguments"])
        if self.specification["method"] == "write":
            arguments[0] = base64.b64decode(arguments[0], validate=True)
        outcome: dict[str, Any] = {}

        async def invoke() -> None:
            try:
                value = await getattr(upload, self.specification["method"])(*arguments)
                if isinstance(value, bytes):
                    value = {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
                outcome["result"] = value
                self.events.append({"event": "await-return"})
            except BaseException as error:
                outcome["error"] = self.error_value(error)
                self.events.append({"event": "await-error", "class": outcome["error"]["class"]})
            finally:
                self.task_finished.set()

        async def scoped_invoke() -> None:
            with anyio.CancelScope() as scope:
                self.scope = scope
                await invoke()
            outcome["scope"] = {
                "cancel_called": scope.cancel_called,
                "cancelled_caught": scope.cancelled_caught,
            }

        async def drive() -> None:
            if self.specification["cancellation"] == "anyio-scope":
                async with anyio.create_task_group() as group:
                    group.start_soon(scoped_invoke)
                    await self.wait_for(self.started)
                    self.events.append({"event": "cancel-requested", "kind": "anyio-scope"})
                    self.scope.cancel()
                    outcome["finished_before_release"] = self.task_finished.is_set()
                    self.release("consumer")
            else:
                task = asyncio.create_task(invoke())
                await self.wait_for(self.started)
                self.events.append({"event": "cancel-requested", "kind": "asyncio-task"})
                outcome["cancel_returned"] = task.cancel(self.specification["cancel_message"])
                await task
                outcome["task_cancelled"] = task.cancelled()
                outcome["finished_before_release"] = self.task_finished.is_set()
                self.release("consumer")
            await self.wait_for(self.completed)

        watchdog = threading.Timer(
            self.specification["watchdog_seconds"], self.release, args=("watchdog",)
        )
        watchdog.daemon = True
        watchdog.start()
        try:
            anyio.run(drive, backend=self.specification["backend"])
        finally:
            self.release("cleanup")
            # Release harness waiters if the public call failed before entering
            # the user file method; the observed worker flags are captured below.
            worker_completed = self.completed.is_set()
            self.started.set()
            self.completed.set()
            watchdog.cancel()
            watchdog.join()
            if self.specification["backend"] == "asyncio" and self.worker_thread is not None:
                self.worker_thread.join(self.specification["watchdog_seconds"])
        outcome["worker_completed"] = worker_completed
        outcome["release_source"] = self.release_source
        outcome["file_closed"] = upload.file.closed
        outcome["size"] = upload.size
        return outcome
