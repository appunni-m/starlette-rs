"""Input-driven observations for Request's inherited scope-mapping interface."""

from __future__ import annotations

import base64
import operator
from collections import UserDict
from collections.abc import Callable
from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return str(value)


def _probe(action: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"outcome": "ok", "value": _safe(action())}
    except Exception as error:
        error_type = type(error)
        return {
            "outcome": "error",
            "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
            "message": str(error),
        }


class _TypeReadUserDict(UserDict):
    """Supply the input-selected value sequence for Request's scope type lookup."""

    def __init__(self, initialdata: dict[str, Any], type_reads: list[str]) -> None:
        super().__init__(initialdata)
        self._type_reads = list(type_reads)
        self.type_read_trace: list[str] = []

    def __getitem__(self, key: Any) -> Any:
        if key == "type":
            if not self._type_reads:
                raise KeyError(key)
            value = self._type_reads.pop(0)
            self.type_read_trace.append(value)
            return value
        return super().__getitem__(key)


def _scope_from_case(case: dict[str, Any]) -> Any:
    scope = case["scope"]
    mapping_spec = case.get("scope_mapping")
    if mapping_spec is None:
        return scope
    if mapping_spec["container"] != "collections.UserDict":
        raise ValueError("unsupported Request scope mapping container")
    if "type_reads" in mapping_spec:
        return _TypeReadUserDict(scope, mapping_spec["type_reads"])
    mapped_scope = UserDict(scope)
    instance_iter_keys = tuple(mapping_spec["instance_iter_keys"])
    mapped_scope.__iter__ = lambda: iter(instance_iter_keys)
    return mapped_scope


def run_request_scope_mapping_case(
    case: dict[str, Any],
    request_type: type[Any],
) -> dict[str, Any]:
    """Observe the mapping API using the exact scope supplied by the case."""
    request = request_type(_scope_from_case(case))
    peer = request_type(dict(case["scope"]))
    value = {
        "keyed_method": _safe(request["method"]),
        "mapping": _safe(dict(request)),
        "iteration_order": _safe(list(request)),
        "length": len(request),
        "identity": {
            "same_scope_values": _probe(lambda: dict(request) == dict(peer)),
            "self_equal": _probe(lambda: request == request),
            "peer_equal": _probe(lambda: request == peer),
            "peer_not_equal": _probe(lambda: request != peer),
            "self_hashable": _probe(lambda: request in {request}),
            "peer_in_self_set": _probe(lambda: peer in {request}),
        },
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "scope-mapping",
                "status": "ok",
                "value": {"scope-mapping": value},
            }
        ],
    }


def run_request_constructor_case(
    case: dict[str, Any],
    request_type: type[Any],
) -> dict[str, Any]:
    """Compare Request construction for the scope supplied by one parity input."""
    scope = _scope_from_case(case)
    try:
        request_type(scope)
    except Exception as error:
        error_type = type(error)
        result = {
            "outcome": "error",
            "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
            "message": str(error),
        }
    else:
        result = {"outcome": "constructed"}

    if isinstance(scope, _TypeReadUserDict):
        result["scope_type_reads"] = _safe(scope.type_read_trace)

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "constructor-contract",
                "status": "ok",
                "value": {"constructor_result": result},
            }
        ],
    }


def run_websocket_constructor_case(
    case: dict[str, Any],
    websocket_type: type[Any],
) -> dict[str, Any]:
    """Compare the input-selected public WebSocket constructor argument forms."""

    async def receive() -> dict[str, str]:
        return {"type": "websocket.connect"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    supplied = {
        "scope": dict(case["scope"]),
        "receive": receive,
        "send": send,
    }
    attempts = []
    for probe in case["constructor_probes"]:
        try:
            websocket = websocket_type(*(supplied[name] for name in probe["arguments"]))
        except Exception as error:
            error_type = type(error)
            attempt = {
                "probe_id": probe["probe_id"],
                "outcome": "error",
                "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
                "message": str(error),
            }
        else:
            attempt = {
                "probe_id": probe["probe_id"],
                "outcome": "constructed",
                "client_state": _safe(websocket.client_state.name),
                "application_state": _safe(websocket.application_state.name),
            }
        attempts.append(attempt)

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "constructor-contract",
                "status": "ok",
                "value": {"constructor_attempts": attempts},
            }
        ],
    }


def run_websocket_scope_mapping_case(
    case: dict[str, Any],
    websocket_type: type[Any],
) -> dict[str, Any]:
    """Observe WebSocket's inherited mapping and identity behavior from its input scope."""

    async def receive() -> dict[str, str]:
        return {"type": "websocket.connect"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    scope = dict(case["scope"])
    if "headers_base64_pairs" in scope:
        scope["headers"] = [
            (
                base64.b64decode(name, validate=True),
                base64.b64decode(value, validate=True),
            )
            for name, value in scope.pop("headers_base64_pairs")
        ]
    websocket = websocket_type(dict(scope), receive=receive, send=send)
    peer = websocket_type(dict(scope), receive=receive, send=send)

    def probe(action: Callable[[], Any]) -> dict[str, Any]:
        try:
            return {"outcome": "ok", "value": _safe(action())}
        except Exception as error:
            error_type = type(error)
            return {
                "outcome": "error",
                "exception_type": f"{error_type.__module__}.{error_type.__qualname__}",
                "message": str(error),
            }

    headers = websocket.headers
    header_assignment = case["header_assignment"]
    header_assignment_result = probe(
        lambda: operator.setitem(
            headers,
            header_assignment["key"],
            header_assignment["value"],
        )
    )
    value = {
        "keyed_value": probe(lambda: websocket[case["lookup_key"]]),
        "mapping": probe(lambda: dict(websocket)),
        "iteration_order": probe(lambda: list(websocket)),
        "length": probe(lambda: len(websocket)),
        "headers": {
            "items": _safe(headers.items()),
            "mapping": _safe(dict(headers)),
            "length": len(headers),
            "lookups": [
                {
                    "key": key,
                    "contains": key in headers,
                    "first_value": probe(lambda key=key: headers[key]),
                    "values": _safe(headers.getlist(key)),
                }
                for key in case["header_lookup_keys"]
            ],
            "assignment": header_assignment_result,
        },
        "identity": {
            "self_equal": probe(lambda: websocket == websocket),
            "distinct_equal": probe(lambda: websocket == peer),
            "distinct_not_equal": probe(lambda: websocket != peer),
            "self_in_set": probe(lambda: websocket in {websocket}),
            "peer_in_self_set": probe(lambda: peer in {websocket}),
            "self_set_equals_recreated_self_set": probe(lambda: {websocket} == {websocket}),
        },
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "scope-mapping",
                "status": "ok",
                "value": {"scope-mapping": value},
            }
        ],
    }
