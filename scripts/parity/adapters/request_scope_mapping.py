"""Input-driven observations for Request's inherited scope-mapping interface."""

from __future__ import annotations

import base64
import builtins
import operator
from collections import UserDict
from collections.abc import Callable, Mapping
from typing import Any


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
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
    if "scope_override" in case:
        return run_scope_property_override_case(case, request_type)

    request = request_type(_scope_from_case(case))
    peer = request_type(dict(case["scope"]))
    value = {
        "keyed_method": _safe(request["method"]),
        "scope_property": _safe(request.scope),
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


def _scope_override_subclass(
    connection_type: type[Any],
    overridden_scope: Any,
) -> type[Any]:
    class InputScopePropertyOverride(connection_type):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._input_overridden_scope = overridden_scope
            self.scope_property_read_trace: list[str] = []
            super().__init__(*args, **kwargs)

        @property
        def scope(self) -> Any:
            self.scope_property_read_trace.append("get")
            return self._input_overridden_scope

        @scope.setter
        def scope(self, value: Any) -> None:
            self._input_assigned_scope = value

    return InputScopePropertyOverride


def _scope_override_property_value(connection: Any, name: str) -> Any:
    value = getattr(connection, name)
    if name == "headers":
        return _safe(value.raw)
    if name == "query_params":
        return _safe(list(value.multi_items()))
    return _safe(value)


def _scope_override_from_spec(spec: dict[str, Any]) -> dict[str, Any]:
    scope = {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": base64.b64decode(spec["raw_path_base64"], validate=True),
        "query_string": base64.b64decode(spec["query_string_base64"], validate=True),
        "root_path": spec["root_path"],
        "headers": [
            (
                base64.b64decode(name, validate=True),
                base64.b64decode(value, validate=True),
            )
            for name, value in spec["headers_base64_pairs"]
        ],
        "client": None if spec["client"] is None else tuple(spec["client"]),
        "server": tuple(spec["server"]),
    }
    if spec["type"] == "http":
        scope["method"] = spec["method"]
    else:
        scope["subprotocols"] = list(spec["subprotocols"])
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    if "app" in spec:
        scope["app"] = spec["app"]
    if "app_root_path" in spec:
        scope["app_root_path"] = spec["app_root_path"]
    if "path_params" in spec:
        scope["path_params"] = dict(spec["path_params"])
    return scope


def run_scope_property_override_case(
    case: dict[str, Any],
    connection_type: type[Any],
) -> dict[str, Any]:
    """Observe inherited connection properties through an input-defined scope override."""
    override_spec = case["scope_override"]
    overridden_scope = _scope_override_from_spec(override_spec["scope"])
    subclass = _scope_override_subclass(connection_type, overridden_scope)
    initial_scope = _scope_from_case(case)

    if case["surface"] == "starlette.websockets.WebSocket":

        async def receive() -> dict[str, str]:
            return {"type": "websocket.connect"}

        async def send(_message: dict[str, Any]) -> None:
            return None

        connection = subclass(initial_scope, receive=receive, send=send)
    else:
        connection = subclass(initial_scope)

    scope_property = _probe(lambda: _safe(connection.scope))
    properties = [
        {
            "name": name,
            **_probe(lambda name=name: _scope_override_property_value(connection, name)),
        }
        for name in override_spec["properties"]
    ]
    mapping_spec = override_spec["mapping"]
    mapping = {
        "__getitem__": _probe(lambda: connection[mapping_spec["lookup_key"]]),
        "__iter__": _probe(lambda: list(iter(connection))),
        "__len__": _probe(lambda: len(connection)),
    }
    value = {
        "scope_property": scope_property,
        "inherited_properties": properties,
        "scope_mapping_protocol": mapping,
        "scope_property_read_trace": list(connection.scope_property_read_trace),
    }
    observation = case["observations"][0]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": observation,
                "status": "ok",
                "value": {observation: value},
            }
        ],
    }


class _StateReadbackUserDict(UserDict):
    """Return separate input-selected values from Request.state's mapping reads."""

    def __init__(self, initialdata: dict[str, Any], state_values: dict[str, Any]) -> None:
        super().__init__(initialdata)
        self._setdefault_value = state_values["setdefault_value"]
        self._getitem_value = state_values["getitem_value_after_setdefault"]
        self._state_readback_armed = False
        self.state_operation_trace: list[str] = []

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key != "state":
            return super().setdefault(key, default)
        self.state_operation_trace.append("setdefault")
        self.data.setdefault(key, self._setdefault_value)
        self._state_readback_armed = True
        return self._setdefault_value

    def __getitem__(self, key: Any) -> Any:
        if key == "state" and self._state_readback_armed:
            self.state_operation_trace.append("getitem")
            return self._getitem_value
        return super().__getitem__(key)


def run_request_state_readback_case(
    case: dict[str, Any],
    request_type: type[Any],
) -> dict[str, Any]:
    """Observe the public Request.state value and its supplied scope lookups."""
    scope = _StateReadbackUserDict(case["scope"], case["scope_mapping"]["state"])
    request = request_type(scope)
    state = request.state
    selected_values = case["scope_mapping"]["state"]["getitem_value_after_setdefault"]
    state_attributes = {key: _safe(getattr(state, key)) for key in selected_values}
    observation = case["observations"][0]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": observation,
                "status": "ok",
                "value": {
                    observation: {
                        "state_attributes": state_attributes,
                        "scope_operation_trace": scope.state_operation_trace,
                    }
                },
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


def run_scope_identity_hash_sequence_case(
    case: dict[str, Any],
    connection_type: type[Any],
) -> dict[str, Any]:
    """Observe connection identity while input-defined mutable scopes change."""

    hook_spec = case["scope_mapping"]

    class RecordingScope(UserDict):
        def __init__(self, scope_id: str, initialdata: dict[str, Any]) -> None:
            super().__init__(initialdata)
            self.scope_id = scope_id
            self.hook_trace: list[str] = []

        def __eq__(self, other: object) -> bool:
            del other
            self.hook_trace.append("equality")
            hook = hook_spec["equality_hook"]
            exception_type = getattr(builtins, hook["exception_type"])
            raise exception_type(hook["message"])

        def __hash__(self) -> int:
            self.hook_trace.append("hash")
            hook = hook_spec["hash_hook"]
            exception_type = getattr(builtins, hook["exception_type"])
            raise exception_type(hook["message"])

    scopes = {
        scope_id: RecordingScope(scope_id, scope_value)
        for scope_id, scope_value in case["scopes"].items()
    }

    async def receive() -> dict[str, str]:
        return {"type": "websocket.connect"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    connections: dict[str, Any] = {}
    for definition in case["connections"]:
        scope = scopes[definition["scope_id"]]
        if case["surface"] == "starlette.websockets.WebSocket":
            connection = connection_type(scope, receive=receive, send=send)
        else:
            connection = connection_type(scope)
        connections[definition["connection_id"]] = connection
    if hook_spec["reset_trace_after_construction"]:
        for scope in scopes.values():
            scope.hook_trace.clear()

    stored_connections: dict[Any, str] = {}
    connections_by_key_id: dict[str, Any] = {}

    def run_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for action_index, action in enumerate(actions):
            operation = action["operation"]
            if operation == "compare-connections":
                result = _probe(
                    lambda action=action: (
                        connections[action["left"]] == connections[action["right"]]
                    )
                )
            elif operation == "compare-scope-values":
                result = _probe(
                    lambda action=action: (
                        connections[action["left"]].scope == connections[action["right"]].scope
                    )
                )
            elif operation == "probe-hashability":

                def probe_hashability(action: dict[str, Any] = action) -> bool:
                    hash(connections[action["connection"]])
                    return True

                result = _probe(probe_hashability)
            elif operation == "store-connection-key":

                def store_connection_key(action: dict[str, Any] = action) -> None:
                    connection = connections[action["connection"]]
                    stored_connections[connection] = action["key_id"]
                    connections_by_key_id[action["key_id"]] = connection

                result = _probe(store_connection_key)
            elif operation == "contains-connection-key":

                def contains_connection_key(action: dict[str, Any] = action) -> bool:
                    connection = connections[action["connection"]]
                    key_id = action["key_id"]
                    return (
                        connection in stored_connections
                        and stored_connections[connection] == key_id
                        and connections_by_key_id[key_id] is connection
                    )

                result = _probe(contains_connection_key)
            elif operation == "read-scope-hook-trace":
                result = _probe(
                    lambda: {scope_id: list(scope.hook_trace) for scope_id, scope in scopes.items()}
                )
            else:
                result = {"outcome": "error", "message": f"Unsupported action: {operation}"}
            results.append({"action_index": action_index, "operation": operation, **result})
        return results

    before = run_actions(case["actions_before_mutation"])
    mutations: list[dict[str, Any]] = []
    for mutation_index, mutation in enumerate(case["scope_mutations"]):
        operation = mutation["operation"]
        if operation == "set-scope-item":
            result = _probe(
                lambda mutation=mutation: operator.setitem(
                    connections[mutation["connection"]].scope,
                    mutation["key"],
                    mutation["value"],
                )
            )
        else:
            result = _probe(
                lambda mutation=mutation: setattr(
                    connections[mutation["connection"]],
                    "scope",
                    scopes[mutation["scope_id"]],
                )
            )
        mutations.append({"mutation_index": mutation_index, "operation": operation, **result})
    after = run_actions(case["actions_after_mutation"])
    value = {"before_mutation": before, "mutations": mutations, "after_mutation": after}

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "scope-identity-hash-sequence",
                "status": "ok",
                "value": {"scope-identity-hash-sequence": value},
            }
        ],
    }


def run_websocket_scope_mapping_case(
    case: dict[str, Any],
    websocket_type: type[Any],
) -> dict[str, Any]:
    """Observe WebSocket's inherited mapping and identity behavior from its input scope."""
    if "scope_override" in case:
        return run_scope_property_override_case(case, websocket_type)

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
