"""Shared input-driven consumer runner for ``starlette.datastructures.State``."""

from __future__ import annotations

from typing import Any

STATE_SURFACE = "starlette.datastructures.State"
STATE_CONSUMER_OPERATION = "consumer-sequence"


def _class_name(value: Any) -> str:
    return f"{type(value).__module__}.{type(value).__qualname__}"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return {"python_type": _class_name(value), "repr": repr(value)}


def _error_value(error: Exception) -> dict[str, Any]:
    context = error.__context__
    cause = error.__cause__
    return {
        "class": _class_name(error),
        "message": str(error),
        "context_class": None if context is None else _class_name(context),
        "context_message": None if context is None else str(context),
        "cause_class": None if cause is None else _class_name(cause),
        "cause_message": None if cause is None else str(cause),
        "suppress_context": error.__suppress_context__,
    }


def _call_state(state: Any, call: str, arguments: list[Any]) -> Any:
    if call == "set-attribute":
        setattr(state, *arguments)
        return None
    if call == "get-attribute":
        return getattr(state, *arguments)
    if call == "delete-attribute":
        delattr(state, *arguments)
        return None
    if call == "set-item":
        state.__setitem__(*arguments)
        return None
    if call == "get-item":
        return state.__getitem__(*arguments)
    if call == "delete-item":
        state.__delitem__(*arguments)
        return None
    if call == "iterate":
        return list(state)
    if call == "length":
        return len(state)
    if call == "vars":
        return vars(state)
    raise ValueError(f"unsupported State action: {call!r}")


def _snapshot(instance_id: str, state: Any, provided_mapping: Any) -> dict[str, Any]:
    keys = list(state)
    return {
        "instance_id": instance_id,
        "items": [[key, _json_value(state[key])] for key in keys],
        "keys": keys,
        "length": len(state),
        "instance_dict": _json_value(vars(state)),
        "provided_mapping": _json_value(provided_mapping),
    }


def run_state_case(case: dict[str, Any]) -> dict[str, Any]:
    """Execute the supplied State constructors and actions against this environment."""
    from starlette.datastructures import State

    instances: dict[str, Any] = {}
    provided_mappings: dict[str, dict[str, Any] | None] = {}
    for instance_spec in case["instances"]:
        instance_id = instance_spec["instance_id"]
        initial_state = instance_spec["initial_state"]
        mapping = None if initial_state is None else dict(initial_state)
        instances[instance_id] = State(mapping)
        provided_mappings[instance_id] = mapping

    action_trace: list[dict[str, Any]] = []
    for action in case["actions"]:
        instance_id = action["receiver"]
        result = {
            "action_id": action["action_id"],
            "receiver": instance_id,
            "call": action["call"],
        }
        try:
            value = _call_state(instances[instance_id], action["call"], action["arguments"])
        except Exception as error:
            result.update({"status": "error", "error": _error_value(error)})
        else:
            result.update({"status": "ok", "value": _json_value(value)})
        action_trace.append(result)

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "consumer-sequence",
                "status": "ok",
                "value": {
                    "consumer-sequence": {
                        "action_trace": action_trace,
                        "instances": [
                            _snapshot(instance_id, state, provided_mappings[instance_id])
                            for instance_id, state in instances.items()
                        ],
                    }
                },
            }
        ],
    }
