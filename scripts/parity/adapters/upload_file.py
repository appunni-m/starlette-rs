"""Input-driven public consumer workflows for ``UploadFile``."""

from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
from collections.abc import Callable
from typing import Any


class _UploadOperationProbe:
    """Observe operation scheduling without recording process-specific thread IDs."""

    def __init__(
        self,
        loop_thread_id: int,
        loop_release_delay_ms: int,
        watchdog_release_delay_ms: int,
    ) -> None:
        self._loop_thread_id = loop_thread_id
        self._loop_release_delay_ms = loop_release_delay_ms
        self._watchdog_release_delay_ms = watchdog_release_delay_ms
        self._lock = threading.Lock()
        self._released = threading.Event()
        self._release_source: str | None = None
        self._operation_thread_id: int | None = None
        self._blocked = False
        self._event_loop_released_operation = False
        self._watchdog: threading.Timer | None = None

    def observe_operation(self, rolled: bool) -> None:
        self._operation_thread_id = threading.get_ident()
        if not rolled:
            return

        self._blocked = True
        self._watchdog = threading.Timer(
            self._watchdog_release_delay_ms / 1000,
            self._release_from_watchdog,
        )
        self._watchdog.daemon = True
        self._watchdog.start()
        self._released.wait()
        with self._lock:
            self._event_loop_released_operation = self._release_source == "event_loop"
        self._watchdog.cancel()

    async def release_after_delay(self) -> None:
        await asyncio.sleep(self._loop_release_delay_ms / 1000)
        with self._lock:
            if self._blocked and self._release_source is None:
                self._release_source = "event_loop"
                self._released.set()

    def _release_from_watchdog(self) -> None:
        with self._lock:
            if self._release_source is None:
                self._release_source = "watchdog"
                self._released.set()

    def observation(self) -> dict[str, Any]:
        release_source = self._release_source if self._blocked else "not_blocked"
        return {
            "operation_on_event_loop": self._operation_thread_id == self._loop_thread_id,
            "event_loop_released_operation": self._event_loop_released_operation,
            "release_source": release_source,
        }


class _ThreadObservedSpooledTemporaryFile(tempfile.SpooledTemporaryFile):
    """Spooled file that records calls and can hold rolled operations briefly."""

    def arm(
        self,
        probe: _UploadOperationProbe,
        injected_error: dict[str, str] | None,
    ) -> None:
        self._pending_probe = probe
        self._pending_error = injected_error

    def _observe(self) -> dict[str, str] | None:
        probe = getattr(self, "_pending_probe", None)
        injected_error = getattr(self, "_pending_error", None)
        self._pending_probe = None
        self._pending_error = None
        if probe is not None:
            probe.observe_operation(bool(self._rolled))
        return injected_error

    def read(self, size: int = -1) -> bytes:
        injected_error = self._observe()
        if injected_error is not None:
            raise OSError(injected_error["message"])
        return tempfile.SpooledTemporaryFile.read(self, size)

    def write(self, value: bytes) -> int:
        injected_error = self._observe()
        if injected_error is not None:
            raise OSError(injected_error["message"])
        return tempfile.SpooledTemporaryFile.write(self, value)

    def seek(self, offset: int, whence: int = 0) -> int:
        injected_error = self._observe()
        if injected_error is not None:
            raise OSError(injected_error["message"])
        return tempfile.SpooledTemporaryFile.seek(self, offset, whence)

    def close(self) -> None:
        injected_error = self._observe()
        if injected_error is not None:
            raise OSError(injected_error["message"])
        tempfile.SpooledTemporaryFile.close(self)


def run_upload_file_case(
    case: dict[str, Any],
    upload_file_type: Callable[..., Any],
) -> dict[str, Any]:
    """Run declared file operations and observe rolled-file scheduling."""

    async def observe() -> dict[str, Any]:
        scenario_observations: list[dict[str, Any]] = []
        loop_thread_id = threading.get_ident()
        for scenario in case["scenarios"]:
            probe_settings = scenario.get("thread_probe")
            stream = _ThreadObservedSpooledTemporaryFile(max_size=scenario["max_size"])
            upload_file = upload_file_type(
                filename=scenario["filename"],
                file=stream,
                size=scenario["initial_size"],
            )
            action_observations: list[dict[str, Any]] = []
            for action in scenario["actions"]:
                call = action["call"]
                probe: _UploadOperationProbe | None = None
                release_task: asyncio.Task[None] | None = None
                if probe_settings is not None:
                    probe = _UploadOperationProbe(
                        loop_thread_id,
                        probe_settings["event_loop_release_delay_ms"],
                        probe_settings["watchdog_release_delay_ms"],
                    )
                    stream.arm(probe, action.get("injected_error"))
                    release_task = asyncio.create_task(probe.release_after_delay())
                    await asyncio.sleep(0)

                result: Any = None
                error: dict[str, str] | None = None
                try:
                    if call == "read":
                        value = await upload_file.read(action["size"])
                        result = {
                            "encoding": "base64",
                            "data": base64.b64encode(value).decode("ascii"),
                        }
                    elif call == "write":
                        value = base64.b64decode(action["data_base64"], validate=True)
                        await upload_file.write(value)
                    elif call == "seek":
                        await upload_file.seek(action["offset"])
                    else:
                        await upload_file.close()
                except Exception as exception:
                    error = {
                        "class": type(exception).__name__,
                        "message": str(exception),
                    }
                if release_task is not None:
                    await release_task

                action_observation: dict[str, Any] = {
                    "action_id": action["action_id"],
                    "result": result,
                    "size": upload_file.size,
                    "file_closed": upload_file.file.closed,
                }
                if error is not None:
                    action_observation["error"] = error
                if probe is not None:
                    action_observation["thread_probe"] = probe.observation()
                action_observations.append(action_observation)
            scenario_observations.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "actions": action_observations,
                }
            )
        return {"scenarios": scenario_observations}

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "file-operations",
                "status": "ok",
                "value": {"file-operations": asyncio.run(observe())},
            }
        ],
    }
