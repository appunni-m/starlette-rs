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

WORKLOAD_CATEGORIES = {"router", "gzip"}
INPUT_KINDS = {
    "router_dispatch",
    "gzip_compression",
    "gzip_bypass",
    "gzip_responsiveness",
}
_LIVE_RELATION_KINDS = {
    "router_dispatch": ("router_status_and_response_shape_matches_input",),
    "gzip_compression": ("gzip_compression_headers_and_event_shape",),
    "gzip_bypass": (),
    "gzip_responsiveness": ("gzip_responsiveness_headers_and_event_shape",),
}

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
_COMPRESSION_ID = re.compile(
    r"^test_gzip\[(json|text|incompressible)-(1MiB|32KiB|256KiB|5MiB|10MiB)-level-([1-9])\]$"
)

_DEFAULT_EXCLUDED_CONTENT_TYPES = (
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "audio/*",
    "font/woff",
    "font/woff2",
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/event-stream",
    "video/*",
)


class UpstreamBenchmarkContractError(ValueError):
    """A malformed or incompatible upstream benchmark input catalog."""


def live_relation_kinds(input_kind: str) -> tuple[str, ...]:
    """Return runtime relations implied by an input kind, without fixture outputs.

    These checks make the pinned benchmark's post-timer response assertions
    executable. Their expected values are derived from the supplied request,
    route, middleware, and response inputs or from the live source observation.
    """
    try:
        return _LIVE_RELATION_KINDS[input_kind]
    except KeyError as exc:
        raise UpstreamBenchmarkContractError(
            f"no live response relations are declared for input kind {input_kind!r}"
        ) from exc


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


def _expected_category(workload_id: str) -> str:
    return "router" if workload_id in ROUTER_WORKLOAD_IDS else "gzip"


def _expected_input_kind(workload_id: str) -> str:
    if workload_id in ROUTER_WORKLOAD_IDS:
        return "router_dispatch"
    if workload_id in GZIP_COMPRESSION_WORKLOAD_IDS:
        return "gzip_compression"
    if workload_id in GZIP_BYPASS_WORKLOAD_IDS:
        return "gzip_bypass"
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return "gzip_responsiveness"
    raise UpstreamBenchmarkContractError(f"unknown pinned workload ID: {workload_id}")


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


def _validate_router_input(workload_id: str, value: dict[str, Any], context: str) -> None:
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
    expected_group_count = 5 if workload_id == "test_routing_small_app" else 30
    _require_equal(expansion["variable"], "i", f"{context}.router.group_expansion.variable")
    _require_equal(expansion["start"], 0, f"{context}.router.group_expansion.start")
    _require_equal(
        expansion["count"], expected_group_count, f"{context}.router.group_expansion.count"
    )
    route_templates = [
        {"path": "/resources{i}", "methods": ["GET", "POST"]},
        {"path": "/resources{i}/{id:int}", "methods": ["GET", "PUT", "DELETE"]},
        {"path": "/resources{i}/{id:int}/items", "methods": ["GET", "POST"]},
        {"path": "/resources{i}/{id:int}/items/{item}", "methods": ["GET"]},
    ]
    _require_equal(router["route_templates"], route_templates, f"{context}.router.route_templates")
    # Expansion is represented compactly, but its effective source route count
    # is fixed at 120 (large) or 20 (small).
    expected_route_count = 20 if expected_group_count == 5 else 120
    if expected_group_count * len(route_templates) != expected_route_count:
        raise UpstreamBenchmarkContractError(f"{context} has an invalid effective route count")
    _require_equal(
        router["endpoint"],
        {"response_class": "starlette.responses.PlainTextResponse", "body_utf8": "ok"},
        f"{context}.router.endpoint",
    )

    expected_request = {
        "test_routing_static_early": ("GET", "/resources0"),
        "test_routing_static_late": ("GET", "/resources29"),
        "test_routing_param_late": ("GET", "/resources29/123/items/first"),
        "test_routing_miss": ("GET", "/no/such/path"),
        "test_routing_method_not_allowed": ("DELETE", "/resources29"),
        "test_routing_small_app": ("GET", "/resources4/7"),
    }[workload_id]
    _require_equal(
        row["scope"],
        {
            "type": "http",
            "method": expected_request[0],
            "path": expected_request[1],
            "root_path": "",
            "headers": [],
            "query_string": {"bytes_hex": ""},
        },
        f"{context}.scope",
    )
    _require_equal(
        row["receive"],
        {
            "behavior": "raise_assertion",
            "message": "The benchmark app must not receive a request body",
        },
        f"{context}.receive",
    )


def _expected_relations(workload_id: str) -> list[dict[str, Any]]:
    if workload_id in GZIP_COMPRESSION_WORKLOAD_IDS:
        return [
            {
                "kind": "gzip_decompress_output_body_equals_input_body",
                "output_event_index": 1,
                "output_field": "body",
                "input_path": "input.payload_generator",
            }
        ]
    if workload_id in GZIP_BYPASS_WORKLOAD_IDS:
        return [
            {
                "kind": "output_events_equal_input_response_messages",
                "output_path": "events",
                "input_path": "input.response_app.messages",
            }
        ]
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return [
            {
                "kind": "gzip_decompress_output_body_equals_input_body",
                "stream": "large",
                "output_event_index": 1,
                "output_field": "body",
                "input_path": "input.payload_generator",
            },
            {
                "kind": "output_events_equal_input_response_messages",
                "stream": "tiny",
                "output_path": "tiny_events",
                "input_path": "input.tiny_response_app.messages",
            },
        ]
    return []


def _validate_observations(workload_id: str, value: Any, context: str) -> None:
    expected_keys = {"events", "input_relations"}
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        expected_keys.add("no_pending_large_task_assertion")
    observations = _exact(value, expected_keys, context)
    event_keys = {"selector", "ordering", "comparison", "unordered_header_token_order"}
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        event_keys.add("streams")
    events = _exact(observations["events"], event_keys, f"{context}.events")
    _require_equal(events["selector"], "all_asgi_send_events", f"{context}.events.selector")
    _require_equal(events["ordering"], "exact", f"{context}.events.ordering")
    _require_equal(events["comparison"], "exact", f"{context}.events.comparison")
    _require_equal(
        events["unordered_header_token_order"],
        ["allow"] if workload_id == "test_routing_method_not_allowed" else [],
        f"{context}.events.unordered_header_token_order",
    )
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        _require_equal(events["streams"], ["large", "tiny"], f"{context}.events.streams")
    _require_equal(
        observations["input_relations"],
        _expected_relations(workload_id),
        f"{context}.input_relations",
    )
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        _require_equal(
            observations["no_pending_large_task_assertion"],
            True,
            f"{context}.no_pending_large_task_assertion",
        )


def _string_list(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise UpstreamBenchmarkContractError(f"{context} must be a non-empty array of strings")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise UpstreamBenchmarkContractError(f"{context} must contain only non-empty strings")
    return value


def _expected_timer_setup(workload_id: str) -> list[str]:
    if workload_id in ROUTER_WORKLOAD_IDS:
        groups = 5 if workload_id == "test_routing_small_app" else 30
        return [
            f"Build the router with {groups} resource groups (four routes per group) before timing.",
            "Construct the module-scoped ASGIRunner and its asyncio event loop before timing.",
        ]
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return [
            "Generate the large JSON payload; build both response message tuples, middleware apps, shared scope, and ResponsivenessBenchmark before timing.",
            "In benchmark setup, create the event loop and warm the AnyIO worker before timing.",
        ]
    if workload_id.startswith("test_gzip_bypass["):
        return [
            "Generate the bypass response input and inner message tuple before timing.",
            "Build GZipMiddleware, scope, and ASGIRunner/event loop before timing.",
        ]
    return [
        "Generate the deterministic response payload before timing.",
        "Build the response message tuple, GZipMiddleware instance, scope, and ASGIRunner/event loop before timing.",
    ]


def _expected_post_timer_checks(workload_id: str) -> list[str]:
    if workload_id in ROUTER_WORKLOAD_IDS:
        return [
            "The upstream assertion reads the status field of the first sent event after the benchmark call."
        ]
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return [
            "In teardown after the timer stops, drain and await the large task.",
            "Select both complete sent event sequences; decompress the large response body and compare it with the generated input body.",
            "Compare the tiny response events with the supplied tiny inner response messages.",
            "No pending-large-task assertion is made.",
            "Record the upstream extra-info fields after the timer stops.",
        ]
    if workload_id.startswith("test_gzip_bypass["):
        return [
            "Select the complete sent event sequence and compare it with the supplied inner response messages.",
            "Record the upstream extra-info fields after the timer stops.",
        ]
    return [
        "Select the full sent event sequence, all response headers, and response body bytes.",
        "Decompress the output body and compare it with the generated input body.",
        "Record the upstream extra-info metrics after the timer stops.",
    ]


def _expected_timed_call_includes(workload_id: str) -> list[str]:
    if workload_id in ROUTER_WORKLOAD_IDS:
        return [
            "runner.run(app, method, path)",
            "Fresh http_scope(method, path) creation for this dispatch",
            "loop.run_until_complete(run_asgi(app, scope))",
            "ASGI receive/send callback setup and sent-event collection",
        ]
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return [
            "The run_until_tiny_response call",
            "loop.run_until_complete of the coroutine that starts the large task, then the tiny task, and awaits the tiny task",
            "Concurrent GZipMiddleware processing until the tiny response completes",
        ]
    return [
        "The full runner.run(app, scope) ASGI call",
        "loop.run_until_complete(run_asgi(app, scope))",
        "GZipMiddleware response handling, fresh outgoing message containers, and send-event collection",
    ]


def _expected_measurement(workload_id: str) -> dict[str, Any]:
    if workload_id in ROUTER_WORKLOAD_IDS:
        return {
            "boundary_id": "router_runner_dispatch",
            "package": "pytest-codspeed",
            "method": "benchmark",
            "marker": None,
            "rounds": None,
        }
    if workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        return {
            "boundary_id": "gzip_tiny_response_latency",
            "package": "pytest-codspeed",
            "method": "benchmark.pedantic",
            "marker": {"max_time_seconds": 0.5, "max_rounds": 1},
            "rounds": 1,
        }
    return {
        "boundary_id": "gzip_middleware_asgi_call",
        "package": "pytest-codspeed",
        "method": "benchmark.pedantic",
        "marker": {"max_time_seconds": 0.5, "max_rounds": 10},
        "rounds": 1,
    }


def _validate_measurement(workload_id: str, value: Any, context: str) -> None:
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
    _require_equal(
        _string_list(measurement["setup_outside_timer"], f"{context}.setup_outside_timer"),
        _expected_timer_setup(workload_id),
        f"{context}.setup_outside_timer",
    )
    _require_equal(
        _string_list(measurement["post_timer_checks"], f"{context}.post_timer_checks"),
        _expected_post_timer_checks(workload_id),
        f"{context}.post_timer_checks",
    )
    timed_call = _exact(
        measurement["timed_call"],
        {"boundary_id", "includes"},
        f"{context}.timed_call",
    )
    expected = _expected_measurement(workload_id)
    _require_equal(
        timed_call["boundary_id"],
        expected["boundary_id"],
        f"{context}.timed_call.boundary_id",
    )
    includes = _string_list(timed_call["includes"], f"{context}.timed_call.includes")
    _require_equal(
        includes,
        _expected_timed_call_includes(workload_id),
        f"{context}.timed_call.includes",
    )
    # The timed boundary is part of this catalog's contract: route timing calls
    # through the source runner, GZip timing encloses one complete middleware
    # call, and responsiveness timing ends as soon as the tiny response arrives.
    joined_includes = " ".join(includes).lower()
    if workload_id in ROUTER_WORKLOAD_IDS:
        required_terms = ("scope", "run_until_complete", "dispatch", "send")
    elif workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        required_terms = ("starts the large task", "tiny response")
    else:
        required_terms = ("gzipmiddleware", "asgi", "send")
    missing_terms = [term for term in required_terms if term not in joined_includes]
    if missing_terms:
        raise UpstreamBenchmarkContractError(
            f"{context}.timed_call.includes omits boundary terms: {missing_terms}"
        )

    harness = _exact(
        measurement["source_harness"],
        {"package", "method", "marker", "rounds"},
        f"{context}.source_harness",
    )
    for field in ("package", "method", "marker", "rounds"):
        _require_equal(harness[field], expected[field], f"{context}.source_harness.{field}")
    expected_runner_policy = {
        "warmup_iterations": 1,
        "samples": 7,
        "iterations_per_sample": 100 if workload_id in ROUTER_WORKLOAD_IDS else 1,
        "sample_statistic": "mean_call_duration",
    }
    _require_equal(
        _exact(
            measurement["runner_policy"],
            {"warmup_iterations", "samples", "iterations_per_sample", "sample_statistic"},
            f"{context}.runner_policy",
        ),
        expected_runner_policy,
        f"{context}.runner_policy",
    )
    setup_joined = " ".join(measurement["setup_outside_timer"]).lower()
    post_joined = " ".join(measurement["post_timer_checks"]).lower()
    if workload_id in ROUTER_WORKLOAD_IDS:
        if "route" not in setup_joined or "runner" not in setup_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.setup_outside_timer must keep route and runner construction outside timing"
            )
        if "status" not in post_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.post_timer_checks must retain the upstream status check"
            )
    elif workload_id == GZIP_RESPONSIVENESS_WORKLOAD_ID:
        if "worker" not in setup_joined or "warm" not in setup_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.setup_outside_timer must warm the AnyIO worker before timing"
            )
        if "drain" not in post_joined or "select" not in post_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.post_timer_checks must drain and validate both response streams"
            )
    else:
        payload_term = "input" if workload_id in GZIP_BYPASS_WORKLOAD_IDS else "payload"
        if payload_term not in setup_joined or "middleware" not in setup_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.setup_outside_timer must construct payload and middleware outside timing"
            )
        if "decompress" not in post_joined and workload_id in GZIP_COMPRESSION_WORKLOAD_IDS:
            raise UpstreamBenchmarkContractError(
                f"{context}.post_timer_checks must validate decompression outside timing"
            )
        if workload_id in GZIP_BYPASS_WORKLOAD_IDS and "compare" not in post_joined:
            raise UpstreamBenchmarkContractError(
                f"{context}.post_timer_checks must compare bypass events outside timing"
            )


def _size_bytes(size_label: str) -> int:
    return {
        "32KiB": 32 * 1024,
        "256KiB": 256 * 1024,
        "1MiB": 1024 * 1024,
        "5MiB": 5 * 1024 * 1024,
        "10MiB": 10 * 1024 * 1024,
    }[size_label]


def _payload_descriptor(payload_kind: str, size_bytes: int) -> dict[str, Any]:
    if payload_kind == "json":
        return {"name": "make_json_payload", "parameters": {"size_bytes": size_bytes}}
    if payload_kind == "text":
        return {
            "name": "make_text_payload",
            "parameters": {"size_bytes": size_bytes},
            "source_constants": {"paragraph_ascii": _TEXT_PARAGRAPH_ASCII},
        }
    if payload_kind == "incompressible":
        return {
            "name": "shake_256_digest",
            "parameters": {
                "seed_ascii": "starlette-gzip-benchmark-v1",
                "size_bytes": size_bytes,
            },
        }
    raise UpstreamBenchmarkContractError(f"unsupported payload kind: {payload_kind}")


_TEXT_PARAGRAPH_ASCII = (
    "Starlette is a lightweight ASGI framework/toolkit, which is ideal for building async web services in Python. "
    "It is production-ready and gives you the following: seriously impressive performance, WebSocket support, "
    "in-process background tasks, startup and shutdown events, and a test client built on HTTPX.\n"
)
_BODY_REQUEST_RECEIVE = {
    "behavior": "raise_assertion",
    "message": "The benchmark app must not receive a request body",
}
_HTTP_GZIP_SCOPE = {
    "type": "http",
    "headers": [{"name_ascii": "accept-encoding", "value_ascii": "gzip"}],
}
_GZIP_MIDDLEWARE_CLASS = "starlette.middleware.gzip.GZipMiddleware"


def _headers_for_response(
    content_type: str,
    *,
    length_key: str = "value_from_body_size_bytes",
    content_encoding: str | None = None,
) -> list[dict[str, Any]]:
    headers: list[dict[str, Any]] = [
        {"name_ascii": "content-type", "value_ascii": content_type},
        {"name_ascii": "content-length", length_key: True},
    ]
    if content_encoding is not None:
        headers.append({"name_ascii": "content-encoding", "value_ascii": content_encoding})
    return headers


def _static_response(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"kind": "static_response", "messages": messages}


def _response_start(headers: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "http.response.start", "status": 200, "headers": headers}


def _body_message(descriptor: dict[str, Any]) -> dict[str, Any]:
    return {"type": "http.response.body", "body": {"generator": descriptor}}


def _middleware(
    app_ref: str,
    keyword: dict[str, Any],
    minimum_size: int,
    compresslevel: int,
) -> dict[str, Any]:
    return {
        "class": _GZIP_MIDDLEWARE_CLASS,
        "call_arguments": {
            "positional": [{"app_ref": app_ref}],
            "keyword": keyword,
        },
        "effective_parameters": {
            "app_ref": app_ref,
            "minimum_size": minimum_size,
            "compresslevel": compresslevel,
            "thread_minimum_size": 131072,
            "exclude_content_types": {
                "type": "tuple",
                "items": list(_DEFAULT_EXCLUDED_CONTENT_TYPES),
            },
        },
    }


def _validate_gzip_common(
    value: dict[str, Any], context: str, *, pathsend_extension: bool = False
) -> None:
    expected_scope = _HTTP_GZIP_SCOPE
    if pathsend_extension:
        expected_scope = {**_HTTP_GZIP_SCOPE, "extensions": {"http.response.pathsend": {}}}
    _require_equal(value["scope"], expected_scope, f"{context}.scope")
    _require_equal(value["receive"], _BODY_REQUEST_RECEIVE, f"{context}.receive")


def _validate_compression_input(workload_id: str, value: dict[str, Any], context: str) -> None:
    match = _COMPRESSION_ID.fullmatch(workload_id)
    if match is None:
        raise UpstreamBenchmarkContractError(f"{context} is not a compression workload")
    payload_kind, size_label, level_text = match.groups()
    size_bytes = _size_bytes(size_label)
    level = int(level_text)
    row = _exact(
        value,
        {"kind", "payload_generator", "scope", "receive", "response_app", "middleware"},
        context,
    )
    _validate_gzip_common(row, context)
    descriptor = _payload_descriptor(payload_kind, size_bytes)
    _require_equal(row["payload_generator"], descriptor, f"{context}.payload_generator")
    _require_equal(
        row["response_app"],
        _static_response(
            [
                _response_start(_headers_for_response("application/json")),
                _body_message(descriptor),
            ]
        ),
        f"{context}.response_app",
    )
    _require_equal(
        row["middleware"],
        _middleware(
            "response_app",
            {"minimum_size": 0, "compresslevel": level},
            minimum_size=0,
            compresslevel=level,
        ),
        f"{context}.middleware",
    )


def _bypass_body_size(workload_id: str) -> int:
    return 499 if workload_id == "test_gzip_bypass[below-minimum-size]" else 1024 * 1024


def _validate_bypass_input(workload_id: str, value: dict[str, Any], context: str) -> None:
    reason = workload_id.removeprefix("test_gzip_bypass[").removesuffix("]")
    size_bytes = _bypass_body_size(workload_id)
    expected_keys = {
        "kind",
        "case_body_size_bytes",
        "scope",
        "receive",
        "response_app",
        "middleware",
    }
    has_payload = reason != "pathsend"
    if has_payload:
        expected_keys.add("payload_generator")
    row = _exact(value, expected_keys, context)
    _validate_gzip_common(row, context, pathsend_extension=reason == "pathsend")
    _require_equal(row["case_body_size_bytes"], size_bytes, f"{context}.case_body_size_bytes")

    content_type = "text/event-stream" if reason == "event-stream" else "application/json"
    content_encoding = "br" if reason == "content-encoding" else None
    if reason == "pathsend":
        response_messages = [
            _response_start(
                _headers_for_response(
                    content_type,
                    length_key="value_from_case_body_size_bytes",
                    content_encoding=content_encoding,
                )
            ),
            {"type": "http.response.pathsend", "path_utf8": "/tmp/starlette-benchmark"},
        ]
    else:
        descriptor = {
            "name": "repeat_byte",
            "parameters": {"byte_ascii": "x", "size_bytes": size_bytes},
        }
        _require_equal(row["payload_generator"], descriptor, f"{context}.payload_generator")
        response_messages = [
            _response_start(
                _headers_for_response(
                    content_type,
                    content_encoding=content_encoding,
                )
            ),
            _body_message(descriptor),
        ]
    _require_equal(
        row["response_app"], _static_response(response_messages), f"{context}.response_app"
    )
    _require_equal(
        row["middleware"],
        _middleware(
            "response_app",
            {"minimum_size": 500},
            minimum_size=500,
            compresslevel=9,
        ),
        f"{context}.middleware",
    )


def _validate_responsiveness_input(value: dict[str, Any], context: str) -> None:
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
    _validate_gzip_common(row, context)
    payload = _payload_descriptor("json", 10 * 1024 * 1024)
    _require_equal(row["payload_generator"], payload, f"{context}.payload_generator")
    large_messages = [
        _response_start(_headers_for_response("application/json")),
        _body_message(payload),
    ]
    tiny_messages = [
        _response_start(
            [
                {"name_ascii": "content-type", "value_ascii": "application/json"},
                {"name_ascii": "content-length", "value_ascii": "2"},
            ]
        ),
        _body_message({"name": "literal_ascii", "parameters": {"value_ascii": "{}"}}),
    ]
    _require_equal(
        row["large_response_app"],
        _static_response(large_messages),
        f"{context}.large_response_app",
    )
    _require_equal(
        row["tiny_response_app"],
        _static_response(tiny_messages),
        f"{context}.tiny_response_app",
    )
    _require_equal(
        row["large_middleware"],
        _middleware("large_response_app", {"compresslevel": 9}, 500, 9),
        f"{context}.large_middleware",
    )
    _require_equal(
        row["tiny_middleware"],
        _middleware("tiny_response_app", {"compresslevel": 9}, 500, 9),
        f"{context}.tiny_middleware",
    )
    _require_equal(
        row["task_schedule"],
        {
            "create_order": ["large", "tiny"],
            "await_before_timer_stops": "tiny",
            "drain_after_timer": "large",
            "scope_is_shared": True,
        },
        f"{context}.task_schedule",
    )


def _validate_gzip_input(workload_id: str, value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise UpstreamBenchmarkContractError(f"{context} must be an object")
    kind = _expected_input_kind(workload_id)
    if kind == "gzip_compression":
        _validate_compression_input(workload_id, value, context)
    elif kind == "gzip_bypass":
        _validate_bypass_input(workload_id, value, context)
    elif kind == "gzip_responsiveness":
        _validate_responsiveness_input(value, context)
    else:
        raise UpstreamBenchmarkContractError(f"{context} has a non-GZip workload kind")


def validate_upstream_workloads(document: Any) -> dict[str, Any]:
    """Validate the pinned input-only catalog and return a compact inventory summary.

    The expected inventory is derived from the benchmark definitions, never from
    row-provided metadata. Observation values are restricted separately by the
    per-workload schema to selectors and boundary descriptions only.
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

        category = row["category"]
        expected_category = _expected_category(workload_id)
        if category not in WORKLOAD_CATEGORIES or category != expected_category:
            raise UpstreamBenchmarkContractError(
                f"{context}.category must be {expected_category!r} for {workload_id}"
            )
        category_counts[category] += 1

        workload_input = row["input"]
        if not isinstance(workload_input, dict):
            raise UpstreamBenchmarkContractError(f"{context}.input must be an object")
        input_kind = workload_input.get("kind")
        expected_kind = _expected_input_kind(workload_id)
        if input_kind not in INPUT_KINDS or input_kind != expected_kind:
            raise UpstreamBenchmarkContractError(
                f"{context}.input.kind must be {expected_kind!r} for {workload_id}"
            )
        input_kind_counts[input_kind] += 1
        if input_kind == "router_dispatch":
            _validate_router_input(workload_id, workload_input, f"{context}.input")
        else:
            _validate_gzip_input(workload_id, workload_input, f"{context}.input")
        _validate_observations(workload_id, row["observations"], f"{context}.observations")
        _validate_measurement(workload_id, row["measurement"], f"{context}.measurement")

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
