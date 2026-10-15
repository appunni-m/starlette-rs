"""Input-defined public URL-converter behavior comparisons."""

from __future__ import annotations

import uuid
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


def _path_params(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": _json_safe(value), "type": type(value).__name__}
        for name, value in values.items()
    }


def _converter_argument(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"type", "value"} and value["type"] == "uuid":
        return uuid.UUID(value["value"])
    return value


def run_convertor_direct_methods_case(case: dict[str, Any]) -> dict[str, Any]:
    """Invoke converter methods selected by the public input case."""
    from starlette import convertors

    input_case = case["input_case"]
    instances = {name: getattr(convertors, name)() for name in input_case["classes"]}
    call_results: list[dict[str, Any]] = []
    error_results: list[dict[str, Any]] = []
    for index, call in enumerate(input_case["calls"]):
        method = getattr(instances[call["class"]], call["method"])
        arguments = [_converter_argument(value) for value in call["arguments"]]
        row: dict[str, Any] = {
            "index": index,
            "class": call["class"],
            "method": call["method"],
        }
        try:
            result = method(*arguments)
        except Exception as error:
            observed_error = {
                "class": type(error).__name__,
                "message": str(error),
            }
            row["error"] = observed_error
            error_results.append({**row, "error": observed_error})
        else:
            row["result"] = {"value": _json_safe(result), "type": type(result).__name__}
        call_results.append(row)

    observations = {
        "call-results-in-order": call_results,
        "exception-class-and-message": error_results,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": name, "status": "ok", "value": {name: observations[name]}}
            for name in case["observations"]
        ],
    }


def _converter(spec: dict[str, str], convertor_type: type[Any]) -> Any:
    class InputConvertor(convertor_type):
        def __init__(self) -> None:
            self.regex = spec["regex"]

        def convert(self, value: str) -> str:
            mode = spec["convert"]
            if mode == "lowercase":
                return value.lower()
            if mode == "uppercase":
                return value.upper()
            return value

        def to_string(self, value: Any) -> str:
            text = str(value)
            mode = spec["to_string"]
            if mode == "lowercase":
                return text.lower()
            if mode == "uppercase":
                return text.upper()
            return text

    return InputConvertor()


def run_convertor_registry_sequence_case(case: dict[str, Any]) -> dict[str, Any]:
    """Apply input-defined converter registration and route actions in order."""
    from starlette.convertors import CONVERTOR_TYPES, Convertor, register_url_convertor
    from starlette.routing import Match, Route

    input_case = case["input_case"]
    registry_key = input_case["registry_key"]
    missing = object()
    previous = CONVERTOR_TYPES.get(registry_key, missing)
    routes: dict[str, Any] = {}
    action_results: list[dict[str, Any]] = []
    route_results: list[dict[str, Any]] = []
    try:
        for index, action in enumerate(input_case["actions"]):
            kind = action["kind"]
            route_id = action.get("route_id")
            try:
                if kind == "register":
                    convertor = _converter(
                        input_case["convertors"][action["convertor_index"]], Convertor
                    )
                    register_url_convertor(registry_key, convertor)
                    result: Any = {
                        "registry_key": registry_key,
                        "convertor_index": action["convertor_index"],
                    }
                elif kind == "construct-route":
                    endpoint_input = action["endpoint"]
                    if endpoint_input["async"]:

                        async def async_endpoint(_scope: Any) -> None:
                            return None

                        endpoint = async_endpoint
                    else:

                        def sync_endpoint(_scope: Any) -> None:
                            return None

                        endpoint = sync_endpoint
                    endpoint.__name__ = endpoint_input["name"]
                    route = Route(action["path"], endpoint, name=action["name"])
                    routes[action["route_id"]] = route
                    result = {"name": route.name, "path": route.path}
                elif kind == "route-matches":
                    route = routes[route_id]
                    match, child_scope = route.matches(action["scope"])
                    result = {
                        "match": match.name if isinstance(match, Match) else str(match),
                        "path_params": _path_params(child_scope.get("path_params", {})),
                    }
                else:
                    route = routes[route_id]
                    path = route.url_path_for(action["name"], **action["path_params"])
                    result = {
                        "path": str(path),
                        "type": type(path).__name__,
                        "protocol": path.protocol,
                        "host": path.host,
                    }
            except Exception as error:
                result = {"error": {"class": type(error).__name__, "message": str(error)}}

            row = {"action_index": index, "kind": kind}
            if route_id is not None:
                row["route_id"] = route_id
            row["result"] = result
            action_results.append(row)
            if kind in {"route-matches", "url-path-for"}:
                route_results.append(
                    {
                        "action_index": index,
                        "kind": kind,
                        "route_id": route_id,
                        "result": result,
                    }
                )
    finally:
        if previous is missing:
            CONVERTOR_TYPES.pop(registry_key, None)
        else:
            CONVERTOR_TYPES[registry_key] = previous

    observations = {
        "action-results-in-order": action_results,
        "route-snapshot-conversion-results": route_results,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": name, "status": "ok", "value": {name: observations[name]}}
            for name in case["observations"]
        ],
    }
