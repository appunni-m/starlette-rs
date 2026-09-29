"""Shared runner for Headers and MutableHeaders input workflows."""

from __future__ import annotations

import base64
from typing import Any

HEADERS_SURFACE = "starlette.datastructures.Headers"
MUTABLE_HEADERS_SURFACE = "starlette.datastructures.MutableHeaders"
CONSUMER_SEQUENCE_OPERATION = "consumer-sequence"

_CASE_FIELDS = {
    "case_id",
    "surface",
    "operation",
    "covers",
    "target_profiles",
    "assets",
    "instances",
    "actions",
    "observations",
}
_OBSERVATION_SELECTORS = {"action-trace", "instance-snapshots", "scope-snapshots"}


def _exact_object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _pair_items(value: Any, context: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    pairs: list[tuple[str, str]] = []
    for index, pair in enumerate(value):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(part, str) for part in pair)
        ):
            raise ValueError(f"{context}[{index}] must be a two-string pair")
        pairs.append((pair[0], pair[1]))
    return pairs


def _header_pairs(value: Any, context: str) -> list[tuple[bytes, bytes]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    pairs: list[tuple[bytes, bytes]] = []
    for index, pair in enumerate(value):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(part, str) for part in pair)
        ):
            raise ValueError(f"{context}[{index}] must be a two-base64-string pair")
        try:
            pairs.append(
                (
                    base64.b64decode(pair[0], validate=True),
                    base64.b64decode(pair[1], validate=True),
                )
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{context}[{index}] contains invalid base64") from exc
    return pairs


def _construct(
    header_type: type[Any], constructor: Any, instance_id: str
) -> tuple[Any, dict[str, Any] | None, list[tuple[bytes, bytes]] | None]:
    if not isinstance(constructor, dict) or not isinstance(constructor.get("kind"), str):
        raise ValueError(f"constructor for {instance_id!r} must declare a kind")
    kind = constructor["kind"]
    if kind == "raw":
        source = _exact_object(
            constructor, {"kind", "headers_base64_pairs"}, f"{instance_id} raw constructor"
        )
        raw = _header_pairs(source["headers_base64_pairs"], instance_id)
        return header_type(raw=raw), None, raw
    if kind == "mapping":
        source = _exact_object(constructor, {"kind", "items"}, f"{instance_id} mapping constructor")
        return header_type(headers=dict(_pair_items(source["items"], instance_id))), None, None
    if kind == "scope":
        source = _exact_object(
            constructor,
            {"kind", "scope_headers_container", "headers_base64_pairs"},
            f"{instance_id} scope constructor",
        )
        container = source["scope_headers_container"]
        if container not in {"list", "tuple"}:
            raise ValueError(f"{instance_id} scope header container must be list or tuple")
        pairs = _header_pairs(source["headers_base64_pairs"], instance_id)
        headers = tuple(pairs) if container == "tuple" else pairs
        scope = {"headers": headers}
        return header_type(scope=scope), scope, None
    if kind == "empty":
        _exact_object(constructor, {"kind"}, f"{instance_id} empty constructor")
        return header_type(), None, None
    raise ValueError(f"unsupported Headers constructor kind: {kind!r}")


def _resolve_argument(value: Any, instances: dict[str, Any]) -> Any:
    if isinstance(value, dict) and set(value) == {"instance_id"}:
        instance_id = value["instance_id"]
        if not isinstance(instance_id, str) or instance_id not in instances:
            raise ValueError(f"unknown Headers instance reference: {instance_id!r}")
        return instances[instance_id]
    if isinstance(value, dict) and set(value) == {"kind", "items"}:
        items = value["items"]
        if value["kind"] == "mapping":
            return dict(_pair_items(items, "mapping operand"))
        if value["kind"] == "set":
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError("set operand items must be an array of strings")
            return set(items)
        raise ValueError(f"unsupported Headers argument kind: {value['kind']!r}")
    return value


def _raw_snapshot(raw: Any) -> list[list[str]]:
    return [
        [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
        for name, value in raw
    ]


def _json_safe(value: Any, header_types: tuple[type[Any], type[Any]]) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, header_types):
        return {
            "python_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
        }
    if isinstance(value, dict):
        return {str(key): _json_safe(item, header_types) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, header_types) for item in value]
    return str(value)


def _error_snapshot(exc: Exception) -> dict[str, str]:
    return {"class": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)}


def _call(receiver: Any, call: str, arguments: list[Any]) -> Any:
    if call == "iterate":
        return list(receiver)
    if call == "len":
        return len(receiver)
    if call == "dict":
        return dict(receiver)
    if call == "repr":
        return repr(receiver)
    if call == "raw":
        return receiver.raw
    if call in {
        "__contains__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__eq__",
        "get",
        "getlist",
        "keys",
        "values",
        "items",
        "mutablecopy",
        "setdefault",
        "update",
        "__or__",
        "__ior__",
        "append",
    }:
        return getattr(receiver, call)(*arguments)
    raise ValueError(f"unsupported Headers action call: {call!r}")


def _instance_snapshot(
    instance_id: str, value: Any, header_types: tuple[type[Any], type[Any]]
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "python_type": f"{type(value).__module__}.{type(value).__qualname__}",
        "raw_base64_pairs": _raw_snapshot(value.raw),
        "keys": _json_safe(value.keys(), header_types),
        "values": _json_safe(value.values(), header_types),
        "items": _json_safe(value.items(), header_types),
        "length": len(value),
        "repr": repr(value),
    }


def _scope_snapshot(instance_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    headers = scope["headers"]
    return {
        "instance_id": instance_id,
        "headers_container": type(headers).__name__,
        "headers_base64_pairs": _raw_snapshot(headers),
    }


def run_headers_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one Headers/MutableHeaders case using only its declared stimuli."""
    required_fields = _CASE_FIELDS - {"actions"}
    if not isinstance(case, dict) or not required_fields <= set(case) or set(case) - _CASE_FIELDS:
        raise ValueError(
            f"Headers consumer-sequence case must contain {sorted(required_fields)} "
            "and may optionally contain actions"
        )
    if case["operation"] != CONSUMER_SEQUENCE_OPERATION:
        raise ValueError(f"unsupported Headers operation: {case['operation']!r}")
    if case["surface"] == HEADERS_SURFACE:
        from starlette.datastructures import Headers, MutableHeaders

        header_type = Headers
    elif case["surface"] == MUTABLE_HEADERS_SURFACE:
        from starlette.datastructures import Headers, MutableHeaders

        header_type = MutableHeaders
    else:
        raise ValueError(f"unsupported Headers surface: {case['surface']!r}")
    header_types = (Headers, MutableHeaders)

    if not isinstance(case["instances"], list) or not case["instances"]:
        raise ValueError("Headers consumer-sequence instances must be a non-empty array")
    instances: dict[str, Any] = {}
    scopes: dict[str, dict[str, Any]] = {}
    raw_inputs: dict[str, list[tuple[bytes, bytes]]] = {}
    for index, instance_spec in enumerate(case["instances"]):
        source = _exact_object(
            instance_spec, {"instance_id", "constructor"}, f"Headers instance[{index}]"
        )
        instance_id = source["instance_id"]
        if not isinstance(instance_id, str) or not instance_id or instance_id in instances:
            raise ValueError(f"Headers instance[{index}] has an invalid or duplicate ID")
        instance, scope, raw_input = _construct(header_type, source["constructor"], instance_id)
        instances[instance_id] = instance
        if scope is not None:
            scopes[instance_id] = scope
        if raw_input is not None:
            raw_inputs[instance_id] = raw_input

    if "actions" in case and not isinstance(case["actions"], list):
        raise ValueError("Headers consumer-sequence actions must be an array")
    action_results: list[dict[str, Any]] = []
    for index, action_spec in enumerate(case.get("actions", [])):
        action_keys = {"action_id", "receiver", "call", "arguments"}
        if isinstance(action_spec, dict) and "bind_instance_id" in action_spec:
            action_keys.add("bind_instance_id")
        if isinstance(action_spec, dict) and "identity_indices" in action_spec:
            action_keys.add("identity_indices")
        action = _exact_object(action_spec, action_keys, f"Headers action[{index}]")
        action_id = action["action_id"]
        receiver_id = action["receiver"]
        call = action["call"]
        arguments = action["arguments"]
        if not isinstance(action_id, str) or not action_id:
            raise ValueError(f"Headers action[{index}] has an invalid ID")
        if receiver_id not in instances:
            raise ValueError(f"Headers action[{index}] references an unknown receiver")
        if not isinstance(call, str) or not isinstance(arguments, list):
            raise ValueError(f"Headers action[{index}] requires a call name and argument array")
        identity_indices = action.get("identity_indices", [])
        if not isinstance(identity_indices, list) or any(
            not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0
            for raw_index in identity_indices
        ):
            raise ValueError(f"Headers action[{index}] has invalid identity indices")
        raw_before = instances[receiver_id].raw
        if any(raw_index >= len(raw_before) for raw_index in identity_indices):
            raise ValueError(f"Headers action[{index}] identity index is outside the raw list")
        retained_pairs = [(raw_index, raw_before[raw_index]) for raw_index in identity_indices]
        resolved_arguments = [_resolve_argument(value, instances) for value in arguments]
        result: dict[str, Any] = {
            "action_id": action_id,
            "receiver": receiver_id,
            "call": call,
        }
        try:
            if call in {"raw-input-append", "raw-view-append"}:
                pair = _header_pairs(arguments[0], f"Headers action[{index}] pair")[0]
                raw_list = (
                    raw_inputs[receiver_id]
                    if call == "raw-input-append"
                    else instances[receiver_id].raw
                )
                raw_list.append(pair)
                value = None
            else:
                value = _call(instances[receiver_id], call, resolved_arguments)
        except Exception as exc:
            result.update({"outcome": "error", "error": _error_snapshot(exc)})
        else:
            if "bind_instance_id" in action:
                binding = action["bind_instance_id"]
                if not isinstance(binding, str) or not binding or binding in instances:
                    raise ValueError(f"Headers action[{index}] has an invalid result binding")
                instances[binding] = value
                if binding in scopes:
                    raise ValueError(f"Headers result binding collides with scope ID: {binding!r}")
                if identity_indices and isinstance(value, header_types):
                    bound_raw = value.raw
                    result["bound_raw_pair_identity"] = [
                        {
                            "source_index": raw_index,
                            "bound_index": next(
                                (
                                    current_index
                                    for current_index, current_pair in enumerate(bound_raw)
                                    if current_pair is retained_pair
                                ),
                                None,
                            ),
                        }
                        for raw_index, retained_pair in retained_pairs
                    ]
            if call == "raw":
                observed_value = _raw_snapshot(value)
            else:
                observed_value = _json_safe(value, header_types)
            result.update({"outcome": "value", "value": observed_value})
        if identity_indices:
            raw_after = instances[receiver_id].raw
            result["raw_pair_identity"] = [
                {
                    "before_index": raw_index,
                    "after_index": next(
                        (
                            current_index
                            for current_index, current_pair in enumerate(raw_after)
                            if current_pair is retained_pair
                        ),
                        None,
                    ),
                }
                for raw_index, retained_pair in retained_pairs
            ]
        action_results.append(result)

    observations = case["observations"]
    if (
        not isinstance(observations, list)
        or not observations
        or any(not isinstance(selector, str) for selector in observations)
        or any(selector not in _OBSERVATION_SELECTORS for selector in observations)
        or len(observations) != len(set(observations))
    ):
        raise ValueError("Headers observations must select unique supported selectors")

    values = {
        "action-trace": action_results,
        "instance-snapshots": [
            _instance_snapshot(instance_id, instance, header_types)
            for instance_id, instance in instances.items()
        ],
        "scope-snapshots": [
            _scope_snapshot(instance_id, scope) for instance_id, scope in scopes.items()
        ],
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": values} for selector in observations
        ],
    }
