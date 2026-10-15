"""Input-defined public attribute operations for Starlette background tasks."""

from __future__ import annotations

from typing import Any


def _callable(spec: dict[str, Any]) -> Any:
    def callback(*_args: Any, **_kwargs: Any) -> None:
        return None

    callback.__name__ = spec["value"]
    return callback


def _materialize(value: Any) -> Any:
    if isinstance(value, dict) and value.get("kind") == "sync-noop":
        return _callable(value)
    return value


def _observe(value: Any) -> Any:
    if callable(value):
        return {"kind": "callable", "name": getattr(value, "__name__", type(value).__name__)}
    if isinstance(value, dict):
        return {key: _observe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_observe(item) for item in value]
    return value


def run_background_attributes_case(case: dict[str, Any], background_module: Any) -> dict[str, Any]:
    """Apply declared reads, assignments, and deletions through the public classes."""
    if case["observations"] != ["background-task-attributes"]:
        raise ValueError("BackgroundTask observations must select the declared attribute record")
    task_spec = case["task"]
    if task_spec["kind"] == "background-task":
        task = background_module.BackgroundTask(
            _materialize(task_spec["func"]),
            *task_spec["args"],
            **task_spec["kwargs"],
        )
    else:
        task = background_module.BackgroundTasks(
            [
                background_module.BackgroundTask(
                    _materialize(item["func"]), *item["args"], **item["kwargs"]
                )
                for item in task_spec["tasks"]
            ]
        )

    action_results: list[dict[str, Any]] = []
    for action in task_spec["actions"]:
        name = action["attribute"]
        try:
            if action["action"] == "read":
                result = {"status": "value", "value": _observe(getattr(task, name))}
            elif action["action"] == "set":
                value = action["value"]
                setattr(task, name, _materialize(value) if name == "func" else value)
                result = {"status": "ok"}
            else:
                delattr(task, name)
                result = {"status": "ok"}
        except Exception as error:
            result = {
                "status": "error",
                "error": {"class": type(error).__name__, "message": str(error)},
            }
        action_results.append({"action": action["action"], "attribute": name, "result": result})

    observation = {
        "object_type": type(task).__name__,
        "actions": action_results,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": case["observations"][0],
                "status": "ok",
                "value": {case["observations"][0]: observation},
            }
        ],
    }
