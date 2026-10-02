"""Input-driven public consumer workflows for ``UploadFile``."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from collections.abc import Callable
from typing import Any


def run_upload_file_case(
    case: dict[str, Any],
    upload_file_type: Callable[..., Any],
) -> dict[str, Any]:
    """Run declared read/write/seek/close sequences at each supplied spool threshold."""

    async def observe() -> dict[str, Any]:
        scenario_observations: list[dict[str, Any]] = []
        for scenario in case["scenarios"]:
            stream = tempfile.SpooledTemporaryFile(max_size=scenario["max_size"])
            upload_file = upload_file_type(
                filename=scenario["filename"],
                file=stream,
                size=scenario["initial_size"],
            )
            action_observations: list[dict[str, Any]] = []
            for action in scenario["actions"]:
                call = action["call"]
                if call == "read":
                    value = await upload_file.read(action["size"])
                    result: Any = {
                        "encoding": "base64",
                        "data": base64.b64encode(value).decode("ascii"),
                    }
                elif call == "write":
                    value = base64.b64decode(action["data_base64"], validate=True)
                    await upload_file.write(value)
                    result = None
                elif call == "seek":
                    await upload_file.seek(action["offset"])
                    result = None
                else:
                    await upload_file.close()
                    result = None
                action_observations.append(
                    {
                        "action_id": action["action_id"],
                        "result": result,
                        "size": upload_file.size,
                        "file_closed": upload_file.file.closed,
                    }
                )
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
