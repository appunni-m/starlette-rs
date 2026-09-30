"""Validation for the input-only pinned Starlette upstream benchmark catalog.

This catalog describes stimuli, observation selectors, and measurement boundaries
for the six Router and 68 GZip workloads in Starlette 1.6.0. It deliberately does
not carry oracle/target outputs or pass/fail expectations.
"""

from __future__ import annotations

import re
from typing import Any

UPSTREAM_BENCHMARK_INPUT_SCHEMA = "migration-parity/upstream-benchmark-input@1"
STARLETTE_SOURCE_REVISION = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"

ROUTER_WORKLOAD_IDS = (
    "test_routing_static_early",
    "test_routing_static_late",
    "test_routing_param_late",
    "test_routing_miss",
    "test_routing_method_not_allowed",
    "test_routing_small_app",
)
GZIP_PAYLOAD_KINDS = ("json", "text", "incompressible")
GZIP_COMPRESSION_WORKLOAD_IDS = tuple(
    f"test_gzip[{payload}-1MiB-level-{level}]"
    for payload in GZIP_PAYLOAD_KINDS
    for level in range(1, 10)
) + tuple(
    f"test_gzip[{payload}-{size}-level-{level}]"
    for payload in GZIP_PAYLOAD_KINDS
    for size in ("32KiB", "256KiB", "5MiB", "10MiB")
    for level in (1, 6, 9)
)
GZIP_BYPASS_REASONS = (
    "below-minimum-size",
    "content-encoding",
    "event-stream",
    "pathsend",
)
GZIP_BYPASS_WORKLOAD_IDS = tuple(f"test_gzip_bypass[{reason}]" for reason in GZIP_BYPASS_REASONS)
GZIP_RESPONSIVENESS_WORKLOAD_ID = "test_gzip_event_loop_responsiveness"
UPSTREAM_WORKLOAD_IDS = (
    *ROUTER_WORKLOAD_IDS,
    *GZIP_COMPRESSION_WORKLOAD_IDS,
    GZIP_RESPONSIVENESS_WORKLOAD_ID,
    *GZIP_BYPASS_WORKLOAD_IDS,
)

INPUT_KIND_CATEGORIES = {
    "router_dispatch": "router",
    "gzip_compression": "gzip",
    "gzip_bypass": "gzip",
    "gzip_responsiveness": "gzip",
}
INPUT_KINDS = set(INPUT_KIND_CATEGORIES)
WORKLOAD_CATEGORIES = set(INPUT_KIND_CATEGORIES.values())

_NON_INPUT_KEY = re.compile(
    r"^(?:expected(?:_|$)|expect(?:_|$)|assert(?:_|$)|assertions(?:_|$)|"
    r"pass(?:_|$)|fail(?:_|$)|oracle_output(?:_|$)|target_output(?:_|$))",
    re.IGNORECASE,
)
_EXECUTION_KEY = re.compile(
    r"^(?:code|callable|function|expression|script|eval|exec|python_code|shell_command|"
    r"source_(?:code|callable|expression|command))$",
    re.IGNORECASE,
)


class UpstreamBenchmarkContractError(ValueError):
    """A malformed or incompatible upstream benchmark input catalog."""


def _exact(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UpstreamBenchmarkContractError(f"{context} must be an object")
    actual = set(value)
    if actual != keys:
        raise UpstreamBenchmarkContractError(
            f"{context} keys differ: missing={sorted(keys - actual)}, "
            f"unknown={sorted(actual - keys)}"
        )
    return value


def _reject_non_input_fields(value: Any, context: str = "catalog") -> None:
    """Reject expected-result material and executable descriptors at any depth."""
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise UpstreamBenchmarkContractError(f"{context} has a non-string object key")
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if (
                _NON_INPUT_KEY.match(key)
                or "expected" in normalized_key
                or "expectation" in normalized_key
            ):
                raise UpstreamBenchmarkContractError(
                    f"{context} contains forbidden expectation/output field {key!r}"
                )
            if normalized_key in {
                "assertions",
                "assertionresults",
                "actualoutput",
                "oracleoutput",
                "targetoutput",
                "passed",
                "failed",
            }:
                raise UpstreamBenchmarkContractError(
                    f"{context} contains forbidden result field {key!r}"
                )
            if _EXECUTION_KEY.match(key):
                raise UpstreamBenchmarkContractError(
                    f"{context} contains executable field {key!r}; generators must be declarative"
                )
            _reject_non_input_fields(child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_non_input_fields(child, f"{context}[{index}]")
    elif value is None or isinstance(value, (str, bool, int)):
        return
    elif isinstance(value, float):
        # The file loader rejects non-finite constants, and a direct API caller
        # must preserve that same JSON-only contract.
        if value != value or value in (float("inf"), float("-inf")):
            raise UpstreamBenchmarkContractError(f"{context} must not contain non-finite numbers")
    else:
        raise UpstreamBenchmarkContractError(f"{context} contains a non-JSON value")


def _same_json(value: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool/int equality shortcut."""
    if isinstance(expected, dict):
        return (
            isinstance(value, dict)
            and set(value) == set(expected)
            and all(_same_json(value[key], expected[key]) for key in expected)
        )
    if isinstance(expected, list):
        return (
            isinstance(value, list)
            and len(value) == len(expected)
            and all(
                _same_json(actual, wanted) for actual, wanted in zip(value, expected, strict=True)
            )
        )
    if expected is None:
        return value is None
    if isinstance(expected, bool):
        return type(value) is bool and value is expected
    if isinstance(expected, int):
        return type(value) is int and value == expected
    if isinstance(expected, float):
        return type(value) is float and value == expected
    return type(value) is type(expected) and value == expected


def _require_equal(value: Any, expected: Any, context: str) -> None:
    if not _same_json(value, expected):
        raise UpstreamBenchmarkContractError(
            f"{context} differs from the pinned Starlette workload definition"
        )


def _integer(value: Any, context: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise UpstreamBenchmarkContractError(
            f"{context} must be an integer greater than or equal to {minimum}"
        )
    return value


def _nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UpstreamBenchmarkContractError(f"{context} must be a non-empty string")
    return value


def _validate_receive(value: Any, context: str) -> None:
    receive = _exact(value, {"behavior", "message"}, context)
    if receive["behavior"] != "raise_assertion":
        raise UpstreamBenchmarkContractError(f"{context}.behavior is unsupported")
    _nonempty_string(receive["message"], f"{context}.message")


def _validate_generator(value: Any, context: str) -> None:
    if not isinstance(value, dict) or set(value) not in (
        {"name", "parameters"},
        {"name", "parameters", "source_constants"},
    ):
        raise UpstreamBenchmarkContractError(
            f"{context} must contain a supported declarative generator"
        )
    name = _nonempty_string(value["name"], f"{context}.name")
    parameters = value["parameters"]
    if not isinstance(parameters, dict):
        raise UpstreamBenchmarkContractError(f"{context}.parameters must be an object")
    if name == "literal_ascii":
        parameters = _exact(parameters, {"value_ascii"}, f"{context}.parameters")
        if not isinstance(parameters["value_ascii"], str):
            raise UpstreamBenchmarkContractError(f"{context}.parameters.value_ascii must be text")
        try:
            parameters["value_ascii"].encode("ascii")
        except UnicodeEncodeError as exc:
            raise UpstreamBenchmarkContractError(
                f"{context}.parameters.value_ascii must be ASCII"
            ) from exc
        if "source_constants" in value:
            raise UpstreamBenchmarkContractError(f"{context} literal generator has extra constants")
        return
    if name not in {
        "make_json_payload",
        "make_text_payload",
        "shake_256_digest",
        "repeat_byte",
    }:
        raise UpstreamBenchmarkContractError(f"{context}.name is unsupported: {name!r}")
    parameter_keys = {"size_bytes"}
    if name == "shake_256_digest":
        parameter_keys.add("seed_ascii")
    if name == "repeat_byte":
        parameter_keys.add("byte_ascii")
    parameters = _exact(parameters, parameter_keys, f"{context}.parameters")
    _integer(parameters["size_bytes"], f"{context}.parameters.size_bytes")
    if name == "shake_256_digest":
        _nonempty_string(parameters["seed_ascii"], f"{context}.parameters.seed_ascii")
    if name == "repeat_byte":
        byte = _nonempty_string(parameters["byte_ascii"], f"{context}.parameters.byte_ascii")
        try:
            byte.encode("ascii")
        except UnicodeEncodeError as exc:
            raise UpstreamBenchmarkContractError(
                f"{context}.parameters.byte_ascii must be ASCII"
            ) from exc
        if len(byte.encode("ascii")) != 1:
            raise UpstreamBenchmarkContractError(
                f"{context}.parameters.byte_ascii must encode to one byte"
            )
    if name == "make_text_payload":
        constants = _exact(
            value.get("source_constants"),
            {"paragraph_ascii"},
            f"{context}.source_constants",
        )
        paragraph = _nonempty_string(
            constants["paragraph_ascii"], f"{context}.source_constants.paragraph_ascii"
        )
        try:
            paragraph.encode("ascii")
        except UnicodeEncodeError as exc:
            raise UpstreamBenchmarkContractError(
                f"{context}.source_constants.paragraph_ascii must be ASCII"
            ) from exc
    elif "source_constants" in value:
        raise UpstreamBenchmarkContractError(f"{context} has unsupported source_constants")


def _validate_input_headers(value: Any, context: str) -> None:
    if not isinstance(value, list):
        raise UpstreamBenchmarkContractError(f"{context} must be an array")
    for index, raw_header in enumerate(value):
        header_context = f"{context}[{index}]"
        if not isinstance(raw_header, dict):
            raise UpstreamBenchmarkContractError(f"{header_context} must be an object")
        keys = set(raw_header)
        if keys not in (
            {"name_ascii", "value_ascii"},
            {"name_ascii", "value_from_body_size_bytes"},
            {"name_ascii", "value_from_case_body_size_bytes"},
        ):
            raise UpstreamBenchmarkContractError(f"{header_context} has an unsupported shape")
        name = _nonempty_string(raw_header["name_ascii"], f"{header_context}.name_ascii")
        try:
            name.encode("ascii")
        except UnicodeEncodeError as exc:
            raise UpstreamBenchmarkContractError(
                f"{header_context}.name_ascii must be ASCII"
            ) from exc
        if "value_ascii" in raw_header:
            if not isinstance(raw_header["value_ascii"], str):
                raise UpstreamBenchmarkContractError(f"{header_context}.value_ascii must be text")
            try:
                raw_header["value_ascii"].encode("ascii")
            except UnicodeEncodeError as exc:
                raise UpstreamBenchmarkContractError(
                    f"{header_context}.value_ascii must be ASCII"
                ) from exc
        elif raw_header[next(iter(keys - {"name_ascii"}))] is not True:
            raise UpstreamBenchmarkContractError(f"{header_context} size reference must be true")


def _validate_response_app(value: Any, context: str) -> None:
    app = _exact(value, {"kind", "messages"}, context)
    if app["kind"] != "static_response" or not isinstance(app["messages"], list):
        raise UpstreamBenchmarkContractError(
            f"{context} must be a static response with a message array"
        )
    if not app["messages"]:
        raise UpstreamBenchmarkContractError(f"{context}.messages must not be empty")
    for index, raw_message in enumerate(app["messages"]):
        message_context = f"{context}.messages[{index}]"
        if not isinstance(raw_message, dict) or "type" not in raw_message:
            raise UpstreamBenchmarkContractError(f"{message_context} must declare a type")
        message_type = raw_message["type"]
        if message_type == "http.response.start":
            message = _exact(raw_message, {"type", "status", "headers"}, message_context)
            _integer(message["status"], f"{message_context}.status", minimum=100)
            _validate_input_headers(message["headers"], f"{message_context}.headers")
        elif message_type == "http.response.body":
            message = _exact(raw_message, {"type", "body"}, message_context)
            body = _exact(message["body"], {"generator"}, f"{message_context}.body")
            _validate_generator(body["generator"], f"{message_context}.body.generator")
        elif message_type == "http.response.pathsend":
            message = _exact(raw_message, {"type", "path_utf8"}, message_context)
            _nonempty_string(message["path_utf8"], f"{message_context}.path_utf8")
        else:
            raise UpstreamBenchmarkContractError(
                f"{message_context}.type is unsupported: {message_type!r}"
            )


def _validate_gzip_scope(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise UpstreamBenchmarkContractError(f"{context} must be an object")
    expected = {"type", "headers"}
    if "extensions" in value:
        expected.add("extensions")
    scope = _exact(value, expected, context)
    if scope["type"] != "http":
        raise UpstreamBenchmarkContractError(f"{context}.type must be 'http'")
    _validate_input_headers(scope["headers"], f"{context}.headers")
    if "extensions" in scope:
        extensions = _exact(
            scope["extensions"], {"http.response.pathsend"}, f"{context}.extensions"
        )
        if extensions["http.response.pathsend"] != {}:
            raise UpstreamBenchmarkContractError(
                f"{context}.extensions.http.response.pathsend must be an empty object"
            )


def _validate_middleware(value: Any, app_names: set[str], context: str) -> None:
    middleware = _exact(
        value,
        {"class", "call_arguments", "effective_parameters"},
        context,
    )
    if middleware["class"] != "starlette.middleware.gzip.GZipMiddleware":
        raise UpstreamBenchmarkContractError(f"{context}.class is unsupported")
    call = _exact(
        middleware["call_arguments"], {"positional", "keyword"}, f"{context}.call_arguments"
    )
    positional = call["positional"]
    if not isinstance(positional, list) or len(positional) != 1:
        raise UpstreamBenchmarkContractError(f"{context}.call_arguments.positional is malformed")
    app_ref = _exact(positional[0], {"app_ref"}, f"{context}.call_arguments.positional[0]")
    app_name = _nonempty_string(app_ref["app_ref"], f"{context}.app_ref")
    if app_name not in app_names:
        raise UpstreamBenchmarkContractError(f"{context}.app_ref does not name an input app")
    keyword = call["keyword"]
    if not isinstance(keyword, dict) or not set(keyword) <= {"minimum_size", "compresslevel"}:
        raise UpstreamBenchmarkContractError(f"{context}.call_arguments.keyword is malformed")
    effective = _exact(
        middleware["effective_parameters"],
        {
            "app_ref",
            "minimum_size",
            "compresslevel",
            "thread_minimum_size",
            "exclude_content_types",
        },
        f"{context}.effective_parameters",
    )
    if effective["app_ref"] != app_name:
        raise UpstreamBenchmarkContractError(f"{context}.effective_parameters.app_ref differs")
    _integer(effective["minimum_size"], f"{context}.effective_parameters.minimum_size")
    compresslevel = _integer(
        effective["compresslevel"], f"{context}.effective_parameters.compresslevel"
    )
    if compresslevel > 9:
        raise UpstreamBenchmarkContractError(
            f"{context}.effective_parameters.compresslevel must be at most 9"
        )
    _integer(
        effective["thread_minimum_size"],
        f"{context}.effective_parameters.thread_minimum_size",
    )
    excluded = _exact(
        effective["exclude_content_types"],
        {"type", "items"},
        f"{context}.effective_parameters.exclude_content_types",
    )
    if excluded["type"] != "tuple":
        raise UpstreamBenchmarkContractError(
            f"{context}.effective_parameters.exclude_content_types.type must be tuple"
        )
    _string_list(
        excluded["items"],
        f"{context}.effective_parameters.exclude_content_types.items",
    )
    for name, argument in keyword.items():
        if argument != effective[name]:
            raise UpstreamBenchmarkContractError(
                f"{context}.call_arguments.keyword.{name} differs from effective parameters"
            )


def _validate_input_path(value: Any, context: str) -> str:
    path = _nonempty_string(value, context)
    if not path.startswith("input.") or any(not part for part in path.split(".")):
        raise UpstreamBenchmarkContractError(f"{context} must be a dotted input path")
    return path


def _validate_input_relations(value: Any, context: str, output_paths: set[str]) -> None:
    if not isinstance(value, list):
        raise UpstreamBenchmarkContractError(f"{context} must be an array")
    relation_kinds: set[str] = set()
    for index, raw_relation in enumerate(value):
        relation_context = f"{context}[{index}]"
        if not isinstance(raw_relation, dict):
            raise UpstreamBenchmarkContractError(f"{relation_context} must be an object")
        kind = _nonempty_string(raw_relation.get("kind"), f"{relation_context}.kind")
        if kind in relation_kinds:
            raise UpstreamBenchmarkContractError(f"{relation_context}.kind must be unique")
        relation_kinds.add(kind)
        if kind == "gzip_decompress_output_body_equals_input_body":
            relation = _exact(
                raw_relation,
                {"kind", "output_path", "output_event_index", "output_field", "input_path"},
                relation_context,
            )
            output_path = _nonempty_string(
                relation["output_path"], f"{relation_context}.output_path"
            )
            if output_path not in output_paths:
                raise UpstreamBenchmarkContractError(
                    f"{relation_context}.output_path is not selected by observations.events"
                )
            _integer(relation["output_event_index"], f"{relation_context}.output_event_index")
            if relation["output_field"] != "body":
                raise UpstreamBenchmarkContractError(
                    f"{relation_context}.output_field must select the response body"
                )
            _validate_input_path(relation["input_path"], f"{relation_context}.input_path")
        elif kind == "output_events_equal_input_response_messages":
            relation = _exact(raw_relation, {"kind", "output_path", "input_path"}, relation_context)
            output_path = _nonempty_string(
                relation["output_path"], f"{relation_context}.output_path"
            )
            if output_path not in output_paths:
                raise UpstreamBenchmarkContractError(
                    f"{relation_context}.output_path is not selected by observations.events"
                )
            _validate_input_path(relation["input_path"], f"{relation_context}.input_path")
        elif kind == "router_response_status_and_shape_matches_input":
            relation = _exact(raw_relation, {"kind", "output_path"}, relation_context)
            output_path = _nonempty_string(
                relation["output_path"], f"{relation_context}.output_path"
            )
            if output_path not in output_paths:
                raise UpstreamBenchmarkContractError(
                    f"{relation_context}.output_path is not selected by observations.events"
                )
        elif kind == "gzip_response_shape_matches_input":
            relation = _exact(raw_relation, {"kind", "responses"}, relation_context)
            responses = relation["responses"]
            if not isinstance(responses, list) or not responses:
                raise UpstreamBenchmarkContractError(
                    f"{relation_context}.responses must be a non-empty array"
                )
            seen_response_outputs: set[str] = set()
            for response_index, raw_response in enumerate(responses):
                response_context = f"{relation_context}.responses[{response_index}]"
                response = _exact(
                    raw_response,
                    {"output_path", "response_app_path", "middleware_path"},
                    response_context,
                )
                output_path = _nonempty_string(
                    response["output_path"], f"{response_context}.output_path"
                )
                if output_path not in output_paths:
                    raise UpstreamBenchmarkContractError(
                        f"{response_context}.output_path is not selected by observations.events"
                    )
                if output_path in seen_response_outputs:
                    raise UpstreamBenchmarkContractError(
                        f"{response_context}.output_path must be unique"
                    )
                seen_response_outputs.add(output_path)
                _validate_input_path(
                    response["response_app_path"], f"{response_context}.response_app_path"
                )
                _validate_input_path(
                    response["middleware_path"], f"{response_context}.middleware_path"
                )
        else:
            raise UpstreamBenchmarkContractError(
                f"{relation_context}.kind is unsupported: {kind!r}"
            )


def _validate_router_input(value: dict[str, Any], context: str) -> None:
    row = _exact(value, {"kind", "router", "scope", "receive"}, context)
    _require_equal(row["kind"], "router_dispatch", f"{context}.kind")
    router = _exact(
        row["router"], {"group_expansion", "route_templates", "endpoint"}, f"{context}.router"
    )
    expansion = _exact(
        router["group_expansion"],
        {"variable", "start", "count"},
        f"{context}.router.group_expansion",
    )
    variable = _nonempty_string(expansion["variable"], f"{context}.router.group_expansion.variable")
    _integer(expansion["start"], f"{context}.router.group_expansion.start")
    _integer(expansion["count"], f"{context}.router.group_expansion.count", minimum=1)
    route_templates = router["route_templates"]
    if not isinstance(route_templates, list) or not route_templates:
        raise UpstreamBenchmarkContractError(f"{context}.router.route_templates must be non-empty")
    for index, route in enumerate(route_templates):
        route_context = f"{context}.router.route_templates[{index}]"
        route = _exact(route, {"path", "methods"}, route_context)
        path = _nonempty_string(route["path"], f"{route_context}.path")
        if "{" + variable + "}" not in path:
            raise UpstreamBenchmarkContractError(
                f"{route_context}.path must use the declared expansion variable"
            )
        methods = _string_list(route["methods"], f"{route_context}.methods")
        if len(methods) != len(set(methods)):
            raise UpstreamBenchmarkContractError(f"{route_context}.methods must be unique")
    endpoint = _exact(
        router["endpoint"], {"response_class", "body_utf8"}, f"{context}.router.endpoint"
    )
    if endpoint["response_class"] != "starlette.responses.PlainTextResponse":
        raise UpstreamBenchmarkContractError(
            f"{context}.router.endpoint.response_class is unsupported"
        )
    if not isinstance(endpoint["body_utf8"], str):
        raise UpstreamBenchmarkContractError(
            f"{context}.router.endpoint.body_utf8 must be a string"
        )

    scope = _exact(
        row["scope"],
        {"type", "method", "path", "root_path", "headers", "query_string"},
        f"{context}.scope",
    )
    if scope["type"] != "http":
        raise UpstreamBenchmarkContractError(f"{context}.scope.type must be 'http'")
    _nonempty_string(scope["method"], f"{context}.scope.method")
    _nonempty_string(scope["path"], f"{context}.scope.path")
    if not isinstance(scope["root_path"], str) or not isinstance(scope["headers"], list):
        raise UpstreamBenchmarkContractError(f"{context}.scope root_path or headers are malformed")
    query = _exact(scope["query_string"], {"bytes_hex"}, f"{context}.scope.query_string")
    if not isinstance(query["bytes_hex"], str):
        raise UpstreamBenchmarkContractError(f"{context}.scope.query_string.bytes_hex must be text")
    try:
        bytes.fromhex(query["bytes_hex"])
    except ValueError as exc:
        raise UpstreamBenchmarkContractError(
            f"{context}.scope.query_string.bytes_hex is invalid"
        ) from exc
    _validate_receive(row["receive"], f"{context}.receive")


def _validate_observations(value: Any, input_spec: dict[str, Any], context: str) -> dict[str, Any]:
    observations = _exact(value, {"events", "input_relations"}, context)
    event_keys = {"selector", "ordering", "comparison", "unordered_header_token_order"}
    if isinstance(observations["events"], dict) and "streams" in observations["events"]:
        event_keys.add("streams")
    events = _exact(observations["events"], event_keys, f"{context}.events")
    _require_equal(events["selector"], "all_asgi_send_events", f"{context}.events.selector")
    _require_equal(events["ordering"], "exact", f"{context}.events.ordering")
    _require_equal(events["comparison"], "exact", f"{context}.events.comparison")
    headers = (
        _string_list(
            events["unordered_header_token_order"],
            f"{context}.events.unordered_header_token_order",
        )
        if events["unordered_header_token_order"]
        else []
    )
    if any(not header.isascii() or header != header.lower() for header in headers):
        raise UpstreamBenchmarkContractError(
            f"{context}.events.unordered_header_token_order must contain lowercase ASCII names"
        )
    if len(headers) != len(set(headers)):
        raise UpstreamBenchmarkContractError(
            f"{context}.events.unordered_header_token_order must not contain duplicates"
        )
    is_responsiveness = input_spec.get("kind") == "gzip_responsiveness"
    if is_responsiveness and "streams" not in events:
        raise UpstreamBenchmarkContractError(
            f"{context}.events.streams is required for multi-stream input"
        )
    output_paths = set() if is_responsiveness else {"events"}
    if "streams" in events:
        streams = events["streams"]
        if not isinstance(streams, dict) or not streams:
            raise UpstreamBenchmarkContractError(
                f"{context}.events.streams must map stream names to output paths"
            )
        stream_names = _string_list(list(streams), f"{context}.events.streams names")
        stream_paths = _string_list(
            list(streams.values()), f"{context}.events.streams output paths"
        )
        if len(stream_names) != len(set(stream_names)) or len(stream_paths) != len(
            set(stream_paths)
        ):
            raise UpstreamBenchmarkContractError(f"{context}.events.streams must be unique")
        if any(not path.endswith("_events") for path in stream_paths):
            raise UpstreamBenchmarkContractError(
                f"{context}.events.streams output paths must end with '_events'"
            )
        if input_spec.get("kind") != "gzip_responsiveness":
            raise UpstreamBenchmarkContractError(
                f"{context}.events.streams is supported only for multi-stream input"
            )
        schedule = input_spec["task_schedule"]
        if set(stream_names) != set(schedule["create_order"]):
            raise UpstreamBenchmarkContractError(
                f"{context}.events.streams names must match the declared task schedule"
            )
        output_paths.update(stream_paths)
    _validate_input_relations(
        observations["input_relations"],
        f"{context}.input_relations",
        output_paths,
    )
    return observations


def _string_list(value: Any, context: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise UpstreamBenchmarkContractError(f"{context} must be an array of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise UpstreamBenchmarkContractError(f"{context} must contain only non-empty strings")
    return value


def _validate_measurement(value: Any, context: str) -> None:
    measurement = _exact(
        value,
        {
            "setup_outside_timer",
            "timed_call",
            "post_timer_checks",
            "source_harness",
            "runner_policy",
        },
        context,
    )
    _string_list(measurement["setup_outside_timer"], f"{context}.setup_outside_timer")
    _string_list(measurement["post_timer_checks"], f"{context}.post_timer_checks")
    timed_call = _exact(
        measurement["timed_call"],
        {"boundary_id", "includes"},
        f"{context}.timed_call",
    )
    _nonempty_string(timed_call["boundary_id"], f"{context}.timed_call.boundary_id")
    _string_list(timed_call["includes"], f"{context}.timed_call.includes")

    harness = _exact(
        measurement["source_harness"],
        {"package", "method", "marker", "rounds"},
        f"{context}.source_harness",
    )
    _nonempty_string(harness["package"], f"{context}.source_harness.package")
    _nonempty_string(harness["method"], f"{context}.source_harness.method")
    marker = harness["marker"]
    if marker is not None:
        marker = _exact(
            marker, {"max_time_seconds", "max_rounds"}, f"{context}.source_harness.marker"
        )
        if (
            not isinstance(marker["max_time_seconds"], (int, float))
            or isinstance(marker["max_time_seconds"], bool)
            or marker["max_time_seconds"] <= 0
        ):
            raise UpstreamBenchmarkContractError(
                f"{context}.source_harness.marker.max_time_seconds must be positive"
            )
        _integer(marker["max_rounds"], f"{context}.source_harness.marker.max_rounds", minimum=1)
    if harness["rounds"] is not None:
        _integer(harness["rounds"], f"{context}.source_harness.rounds", minimum=1)
    policy = _exact(
        measurement["runner_policy"],
        {"warmup_iterations", "samples", "iterations_per_sample", "sample_statistic"},
        f"{context}.runner_policy",
    )
    _integer(policy["warmup_iterations"], f"{context}.runner_policy.warmup_iterations")
    _integer(policy["samples"], f"{context}.runner_policy.samples", minimum=1)
    _integer(
        policy["iterations_per_sample"],
        f"{context}.runner_policy.iterations_per_sample",
        minimum=1,
    )
    if policy["sample_statistic"] != "mean_call_duration":
        raise UpstreamBenchmarkContractError(
            f"{context}.runner_policy.sample_statistic is unsupported"
        )


_GZIP_MIDDLEWARE_CLASS = "starlette.middleware.gzip.GZipMiddleware"


def _body_generators(app: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        message["body"]["generator"]
        for message in app["messages"]
        if message.get("type") == "http.response.body"
    ]


def _validate_gzip_input(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise UpstreamBenchmarkContractError(f"{context} must be an object")
    kind = value.get("kind")
    if kind == "gzip_compression":
        row = _exact(
            value,
            {"kind", "payload_generator", "scope", "receive", "response_app", "middleware"},
            context,
        )
        _validate_generator(row["payload_generator"], f"{context}.payload_generator")
        app_names = {"response_app"}
        _validate_gzip_scope(row["scope"], f"{context}.scope")
        _validate_receive(row["receive"], f"{context}.receive")
        _validate_response_app(row["response_app"], f"{context}.response_app")
        bodies = _body_generators(row["response_app"])
        if len(bodies) != 1 or not _same_json(bodies[0], row["payload_generator"]):
            raise UpstreamBenchmarkContractError(
                f"{context}.response_app body must use the declared payload_generator"
            )
        _validate_middleware(row["middleware"], app_names, f"{context}.middleware")
        return
    if kind == "gzip_bypass":
        base_keys = {
            "kind",
            "case_body_size_bytes",
            "scope",
            "receive",
            "response_app",
            "middleware",
        }
        has_payload = "payload_generator" in value
        keys = base_keys | ({"payload_generator"} if has_payload else set())
        row = _exact(value, keys, context)
        _integer(row["case_body_size_bytes"], f"{context}.case_body_size_bytes")
        _validate_gzip_scope(row["scope"], f"{context}.scope")
        _validate_receive(row["receive"], f"{context}.receive")
        _validate_response_app(row["response_app"], f"{context}.response_app")
        bodies = _body_generators(row["response_app"])
        if has_payload:
            _validate_generator(row["payload_generator"], f"{context}.payload_generator")
            if len(bodies) != 1 or not _same_json(bodies[0], row["payload_generator"]):
                raise UpstreamBenchmarkContractError(
                    f"{context}.response_app body must use the declared payload_generator"
                )
        elif bodies:
            raise UpstreamBenchmarkContractError(
                f"{context}.response_app body requires a declared payload_generator"
            )
        _validate_middleware(row["middleware"], {"response_app"}, f"{context}.middleware")
        return
    if kind == "gzip_responsiveness":
        row = _exact(
            value,
            {
                "kind",
                "payload_generator",
                "scope",
                "receive",
                "large_response_app",
                "tiny_response_app",
                "large_middleware",
                "tiny_middleware",
                "task_schedule",
            },
            context,
        )
        _validate_generator(row["payload_generator"], f"{context}.payload_generator")
        _validate_gzip_scope(row["scope"], f"{context}.scope")
        _validate_receive(row["receive"], f"{context}.receive")
        app_names = {"large_response_app", "tiny_response_app"}
        for app_name in sorted(app_names):
            _validate_response_app(row[app_name], f"{context}.{app_name}")
        large_bodies = _body_generators(row["large_response_app"])
        if len(large_bodies) != 1 or not _same_json(large_bodies[0], row["payload_generator"]):
            raise UpstreamBenchmarkContractError(
                f"{context}.large_response_app body must use the declared payload_generator"
            )
        _validate_middleware(row["large_middleware"], app_names, f"{context}.large_middleware")
        _validate_middleware(row["tiny_middleware"], app_names, f"{context}.tiny_middleware")
        schedule = _exact(
            row["task_schedule"],
            {"create_order", "await_before_timer_stops", "drain_after_timer", "scope_is_shared"},
            f"{context}.task_schedule",
        )
        order = _string_list(schedule["create_order"], f"{context}.task_schedule.create_order")
        if len(order) != 2 or set(order) != {"large", "tiny"}:
            raise UpstreamBenchmarkContractError(
                f"{context}.task_schedule.create_order must name both response streams"
            )
        if schedule["await_before_timer_stops"] not in {"large", "tiny"}:
            raise UpstreamBenchmarkContractError(
                f"{context}.task_schedule.await_before_timer_stops is unsupported"
            )
        if schedule["drain_after_timer"] not in {"large", "tiny"}:
            raise UpstreamBenchmarkContractError(
                f"{context}.task_schedule.drain_after_timer is unsupported"
            )
        if schedule["await_before_timer_stops"] == schedule["drain_after_timer"]:
            raise UpstreamBenchmarkContractError(
                f"{context}.task_schedule must await a different stream after the timer"
            )
        if not isinstance(schedule["scope_is_shared"], bool):
            raise UpstreamBenchmarkContractError(
                f"{context}.task_schedule.scope_is_shared must be boolean"
            )
        return
    raise UpstreamBenchmarkContractError(f"{context}.kind is unsupported: {kind!r}")


def _resolve_input_path(input_spec: dict[str, Any], path: str, context: str) -> Any:
    value: Any = input_spec
    for component in path.removeprefix("input.").split("."):
        if not isinstance(value, dict) or component not in value:
            raise UpstreamBenchmarkContractError(f"{context} does not resolve: {path}")
        value = value[component]
    return value


def _validate_relation_references(input_spec: dict[str, Any], observations: dict[str, Any]) -> None:
    for index, relation in enumerate(observations["input_relations"]):
        context = f"observations.input_relations[{index}]"
        kind = relation["kind"]
        if kind == "gzip_decompress_output_body_equals_input_body":
            path = relation["input_path"]
            if len(path.split(".")) != 2:
                raise UpstreamBenchmarkContractError(
                    f"{context}.input_path must select one input payload generator"
                )
            generator = _resolve_input_path(input_spec, path, f"{context}.input_path")
            _validate_generator(generator, f"{context}.input_path")
        elif kind == "output_events_equal_input_response_messages":
            path = relation["input_path"]
            pieces = path.removeprefix("input.").split(".")
            if len(pieces) != 2 or pieces[1] != "messages":
                raise UpstreamBenchmarkContractError(
                    f"{context}.input_path must select a response app message array"
                )
            app = _resolve_input_path(input_spec, f"input.{pieces[0]}", f"{context}.input_path")
            if (
                not isinstance(app, dict)
                or app.get("kind") != "static_response"
                or not (pieces[0] == "response_app" or pieces[0].endswith("_response_app"))
            ):
                raise UpstreamBenchmarkContractError(
                    f"{context}.input_path must reference a worker-loadable static response app"
                )
            _resolve_input_path(input_spec, path, f"{context}.input_path")
        elif kind == "gzip_response_shape_matches_input":
            for response_index, response in enumerate(relation["responses"]):
                response_context = f"{context}.responses[{response_index}]"
                app_path = response["response_app_path"]
                middleware_path = response["middleware_path"]
                app_pieces = app_path.removeprefix("input.").split(".")
                middleware_pieces = middleware_path.removeprefix("input.").split(".")
                if (
                    len(app_pieces) != 1
                    or len(middleware_pieces) != 1
                    or not (
                        app_pieces[0] == "response_app" or app_pieces[0].endswith("_response_app")
                    )
                    or not (
                        middleware_pieces[0] == "middleware"
                        or middleware_pieces[0].endswith("_middleware")
                    )
                ):
                    raise UpstreamBenchmarkContractError(
                        f"{response_context} must reference a top-level app and middleware"
                    )
                app = _resolve_input_path(
                    input_spec, app_path, f"{response_context}.response_app_path"
                )
                middleware = _resolve_input_path(
                    input_spec, middleware_path, f"{response_context}.middleware_path"
                )
                if (
                    not isinstance(app, dict)
                    or app.get("kind") != "static_response"
                    or not isinstance(middleware, dict)
                    or middleware.get("effective_parameters", {}).get("app_ref") != app_pieces[0]
                ):
                    raise UpstreamBenchmarkContractError(
                        f"{response_context} does not bind the middleware to its response app"
                    )


def validate_upstream_workloads(document: Any) -> dict[str, Any]:
    """Validate the pinned input-only catalog and return a compact inventory summary.

    Workload IDs are source-lineage keys only. Each input kind selects a generic
    input validator; stimulus values, observation relations, and measurement
    policy are read from the row itself.
    """
    _reject_non_input_fields(document)
    catalog = _exact(
        document,
        {"schema", "source_revision", "workloads"},
        "upstream benchmark catalog",
    )
    if catalog["schema"] != UPSTREAM_BENCHMARK_INPUT_SCHEMA:
        raise UpstreamBenchmarkContractError(
            f"unsupported upstream benchmark schema: {catalog['schema']!r}"
        )
    if catalog["source_revision"] != STARLETTE_SOURCE_REVISION:
        raise UpstreamBenchmarkContractError(
            "source_revision differs from the pinned Starlette 1.6.0 commit"
        )
    rows = catalog["workloads"]
    if not isinstance(rows, list):
        raise UpstreamBenchmarkContractError("workloads must be an array")
    if len(rows) != len(UPSTREAM_WORKLOAD_IDS):
        raise UpstreamBenchmarkContractError(
            f"pinned Starlette workload inventory must contain 74 rows, found {len(rows)}"
        )

    seen: set[str] = set()
    category_counts = {"router": 0, "gzip": 0}
    input_kind_counts = {kind: 0 for kind in INPUT_KINDS}
    for index, raw_row in enumerate(rows):
        context = f"workloads[{index}]"
        row = _exact(
            raw_row,
            {"workload_id", "category", "input", "observations", "measurement"},
            context,
        )
        workload_id = row["workload_id"]
        if not isinstance(workload_id, str) or not workload_id:
            raise UpstreamBenchmarkContractError(
                f"{context}.workload_id must be a non-empty string"
            )
        if workload_id not in UPSTREAM_WORKLOAD_IDS:
            raise UpstreamBenchmarkContractError(
                f"{context} has unknown workload ID {workload_id!r}"
            )
        if workload_id in seen:
            raise UpstreamBenchmarkContractError(f"duplicate upstream workload ID: {workload_id}")
        seen.add(workload_id)

        workload_input = row["input"]
        if not isinstance(workload_input, dict):
            raise UpstreamBenchmarkContractError(f"{context}.input must be an object")
        input_kind = workload_input.get("kind")
        if input_kind not in INPUT_KINDS:
            raise UpstreamBenchmarkContractError(
                f"{context}.input.kind is unsupported: {input_kind!r}"
            )
        category = row["category"]
        expected_category = INPUT_KIND_CATEGORIES[input_kind]
        if category not in WORKLOAD_CATEGORIES or category != expected_category:
            raise UpstreamBenchmarkContractError(
                f"{context}.category must match input kind {input_kind!r}"
            )
        category_counts[category] += 1

        input_kind_counts[input_kind] += 1
        if input_kind == "router_dispatch":
            _validate_router_input(workload_input, f"{context}.input")
        else:
            _validate_gzip_input(workload_input, f"{context}.input")
        observations = _exact(
            row["observations"], {"events", "input_relations"}, f"{context}.observations"
        )
        observations = _validate_observations(
            observations, workload_input, f"{context}.observations"
        )
        _validate_relation_references(workload_input, observations)
        _validate_measurement(row["measurement"], f"{context}.measurement")

    missing = set(UPSTREAM_WORKLOAD_IDS) - seen
    if missing:
        raise UpstreamBenchmarkContractError(
            f"pinned Starlette workload inventory is missing IDs: {sorted(missing)}"
        )
    actual_order = [row["workload_id"] for row in rows]
    if actual_order != list(UPSTREAM_WORKLOAD_IDS):
        raise UpstreamBenchmarkContractError(
            "workload rows must follow the pinned Starlette source declaration order"
        )
    expected_categories = {"router": 6, "gzip": 68}
    if category_counts != expected_categories:
        raise UpstreamBenchmarkContractError(
            f"upstream workload category counts differ: {category_counts}"
        )
    expected_input_kinds = {
        "router_dispatch": 6,
        "gzip_compression": 63,
        "gzip_bypass": 4,
        "gzip_responsiveness": 1,
    }
    if input_kind_counts != expected_input_kinds:
        raise UpstreamBenchmarkContractError(
            f"upstream workload input-kind counts differ: {input_kind_counts}"
        )

    return {
        "schema": UPSTREAM_BENCHMARK_INPUT_SCHEMA,
        "source_revision": STARLETTE_SOURCE_REVISION,
        "workload_count": len(rows),
        "category_counts": category_counts,
        "input_kind_counts": input_kind_counts,
        "workload_ids": list(UPSTREAM_WORKLOAD_IDS),
    }
