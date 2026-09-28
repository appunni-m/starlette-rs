"""Strict manifest, parity-input, and evidence validation."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import statistics
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

MANIFEST_SCHEMA = "migration-parity/manifest@2"
INPUT_SCHEMA = "migration-parity/parity-input@4"
BENCHMARK_INPUT_SCHEMA = "migration-parity/benchmark-input@1"
RESULT_SCHEMA = "migration-parity/parity-result@4"
BENCHMARK_RESULT_SCHEMA = "migration-parity/benchmark-result@1"
UPSTREAM_BENCHMARK_INPUT_SCHEMA = "migration-parity/upstream-benchmark-input@1"
UPSTREAM_BENCHMARK_RESULT_SCHEMA = "migration-parity/upstream-benchmark-result@1"
AGGREGATION_INPUT_SCHEMAS = (
    RESULT_SCHEMA,
    "migration-parity/coverage-result@1",
    BENCHMARK_RESULT_SCHEMA,
    UPSTREAM_BENCHMARK_RESULT_SCHEMA,
)
ORACLE_COMMIT = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"
GENERATED_INPUT_ROOT = Path("build/parity/inputs")
_BODY_LIMIT_MISSING = object()

TOP_KEYS = {
    "schema",
    "scope",
    "oracles",
    "targets",
    "target_profiles",
    "commands",
    "interfaces",
    "input_index",
    "coverage_components",
    "surfaces",
    "documentation",
}
CASE_KEYS = {
    "case_id",
    "surface",
    "operation",
    "covers",
    "target_profiles",
    "assets",
    "steps",
    "observations",
    "execution_schedule",
}
WEBSOCKET_SURFACE = "starlette.websockets.WebSocket"
WEBSOCKET_OPERATION = "protocol-sequence"
WEBSOCKET_STATE_OPERATION = "state-sequence"
WEBSOCKET_CONVENIENCE_OPERATION = "convenience-sequence"
WEBSOCKET_CLOSE_SURFACE = "starlette.websockets.WebSocketClose"
WEBSOCKET_CLOSE_OPERATION = "call-sequence"
EXCEPTION_VALUES_SURFACE = "starlette.exceptions"
MIDDLEWARE_CONFIG_SURFACE = "starlette.middleware.Middleware"
VALUE_FORMATTING_OPERATION = "value-formatting"
VALUE_FORMATTING_OPERATIONS = {
    (EXCEPTION_VALUES_SURFACE, VALUE_FORMATTING_OPERATION),
    (MIDDLEWARE_CONFIG_SURFACE, VALUE_FORMATTING_OPERATION),
}
REQUEST_DEFAULT_RECEIVE_OPERATION = ("starlette.requests.Request", "default-receive")
STATUS_OPERATION = ("starlette.status", "module-symbol-sequence")
CONFIG_OPERATIONS = {
    ("starlette.config.Config", "value-resolution"),
    ("starlette.config.Config", "constructor-warning"),
    ("starlette.config.Environ", "mapping-sequence"),
}
SCHEMA_OPERATIONS = {
    ("starlette.schemas.SchemaGenerator", "schema-generation"),
    ("starlette.schemas.BaseSchemaGenerator", "schema-docstring-parsing"),
    ("starlette.schemas.OpenAPIResponse", "openapi-response-render"),
}
RUST_OWNED_PYTHON_OPERATIONS = CONFIG_OPERATIONS | SCHEMA_OPERATIONS
WEBSOCKET_PROJECTED_ERROR_OPERATIONS = {
    (WEBSOCKET_SURFACE, WEBSOCKET_OPERATION),
    (WEBSOCKET_SURFACE, WEBSOCKET_STATE_OPERATION),
    (WEBSOCKET_SURFACE, WEBSOCKET_CONVENIENCE_OPERATION),
    (WEBSOCKET_CLOSE_SURFACE, WEBSOCKET_CLOSE_OPERATION),
}
WEBSOCKET_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "scope",
    "incoming",
    "actions",
}
STATUS_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "public_names",
    "deprecated_names",
    "missing_names",
    "observe_directory",
}
WEBSOCKET_CLOSE_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "scope",
    "close_app",
}
WEBSOCKET_ROUTE_SURFACE = "starlette.routing.WebSocketRoute"
WEBSOCKET_ROUTE_OPERATION = "route-dispatch"
WEBSOCKET_ROUTE_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "dispatch",
    "route",
    "scope",
    "incoming",
    "endpoint_actions",
}
WEBSOCKET_ROUTE_OBSERVATIONS = (WEBSOCKET_ROUTE_OPERATION,)
ROUTER_SURFACE = "starlette.routing.Router"
ROUTER_OPERATION = "route-dispatch"
HOST_SURFACE = "starlette.routing.Host"
HOST_REVERSE_OPERATION = "url_path_for"
ROUTER_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "custom_convertors",
    "redirect_slashes",
    "routes",
    "scope",
    "incoming",
    "send",
}
MOUNT_SURFACE = "starlette.routing.Mount"
MOUNT_OPERATION = "route-dispatch"
MOUNT_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "mount",
    "scope",
    "incoming",
    "send",
}
REDIRECT_RESPONSE_SURFACE = "starlette.responses.RedirectResponse"
REDIRECT_RESPONSE_OPERATION = "asgi-call"
REDIRECT_RESPONSE_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "url",
    "status_code",
    "header_pairs",
    "scope",
    "incoming",
    "send",
}
RESPONSE_SURFACE = "starlette.responses.Response"
JSON_RESPONSE_SURFACE = "starlette.responses.JSONResponse"
RESPONSE_SURFACES = {RESPONSE_SURFACE, JSON_RESPONSE_SURFACE}
STREAMING_RESPONSE_SURFACE = "starlette.responses.StreamingResponse"
FILE_RESPONSE_SURFACE = "starlette.responses.FileResponse"
STREAMING_RESPONSE_OPERATION = "asgi-call"
STREAMING_RESPONSE_TRACE_OPERATION = "asgi-call-with-execution-trace"
RESPONSE_OPERATION = "asgi-call"
RESPONSE_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "content",
    "status_code",
    "header_pairs",
    "media_type",
    "scope",
    "incoming",
    "send",
}
STREAMING_RESPONSE_CASE_KEYS = RESPONSE_CASE_KEYS | {"streaming"}
FILE_RESPONSE_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "file",
    "status_code",
    "header_pairs",
    "media_type",
    "filename",
    "scope",
    "incoming",
    "send",
}
RESPONSE_OBSERVATIONS = [
    "response_status",
    "ordered_repeated_headers",
    "response_bytes",
    "asgi_event_order",
    "asgi_events",
]
REVERSE_URL_CASE_KEYS = (CASE_KEYS - {"steps", "execution_schedule"}) | {
    "route_graph",
    "lookup",
    "request_scope",
    "custom_convertors",
}
REVERSE_URL_OPERATIONS = {
    ("starlette.applications.Starlette", "url_path_for"),
    ("starlette.routing.Route", "url_path_for"),
    ("starlette.routing.WebSocketRoute", "url_path_for"),
    ("starlette.routing.Router", "url_path_for"),
    ("starlette.routing.Mount", "url_path_for"),
    (HOST_SURFACE, HOST_REVERSE_OPERATION),
    ("starlette.requests.Request", "url_for"),
}
REVERSE_URL_SURFACE_KINDS = {
    "starlette.applications.Starlette": "starlette-app",
    "starlette.routing.Route": "http-route",
    "starlette.routing.WebSocketRoute": "websocket-route",
    "starlette.routing.Router": "router",
    "starlette.routing.Mount": "mount",
    HOST_SURFACE: "host-route",
}
REVERSE_URL_OBSERVATION = "reverse-url"
STEP_KEYS = {"step_id", "surface", "operation", "receiver", "arguments"}
VALUE_TYPES = {
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "bytes",
    "path",
    "enum",
    "sequence",
    "mapping",
    "record",
    "image",
    "font",
    "stream",
    "handle",
    "any_json",
}
PARAMETER_STYLES = {
    "receiver",
    "positional",
    "positional_or_keyword",
    "keyword",
    "variadic_positional",
    "variadic_keyword",
    "input_asset",
    "stdin",
    "environment",
    "option",
}
RESULT_SHAPES = {
    "none",
    "scalar",
    "sequence",
    "mapping",
    "record",
    "bytes",
    "image",
    "mask",
    "encoded_file",
    "metrics",
    "handle",
    "iterator",
    "stream",
    "cli",
    "protocol",
    "filesystem",
}
OBSERVATION_COMPARISONS = {"exact", "ordered", "bytes"}
PARITY_TERMINAL_STATUSES = {"completed", "failed", "skipped", "unsupported"}

REQUEST_OBSERVER_ENDPOINT = {
    "kind": "request-observer",
    "path_parameter": "item_id",
    "query_parameter": "tag",
    "header_primary_case": "X-MiXeD",
    "header_alternate_case": "x-mixed",
    "cookie_name": "session",
    "response_content": "request-observed",
    "status_code": 200,
    "media_type": "text/plain",
}
REQUEST_CONNECTION_PROPERTY_REQUIREMENTS = {
    "session": "starlette.request.connection-property-missing-session",
    "auth": "starlette.request.connection-property-missing-auth",
    "user": "starlette.request.connection-property-missing-user",
}
REQUEST_STREAM_REQUIREMENTS = {
    "asend": "starlette.request.stream-asend",
    "athrow": "starlette.request.stream-athrow",
    "aclose": "starlette.request.stream-aclose",
}
SYNC_REQUEST_RUNTIME_REQUIREMENTS = {
    "receive": "starlette.request.receive-worker-access",
    "stream": "starlette.request.stream-construction-worker",
    "body": "starlette.request.body-awaitable-construction-worker",
    "json": "starlette.request.json-awaitable-construction-worker",
}
SYNC_ENDPOINT_REQUIREMENTS = {
    "contextvar": "starlette.routing.sync-endpoint-contextvar-propagation",
    "worker_thread": "starlette.routing.sync-endpoint-worker-thread",
    "single_invocation": "starlette.routing.sync-endpoint-single-invocation",
    "callable_form": "starlette.routing.sync-endpoint-callable-form",
}
ASGI_CALLABLE_INSTANCE_REQUIREMENT = "starlette.routing.asgi-callable-instance-dispatch"
ASGI_CALLABLE_INSTANCE_ENDPOINT = {
    "kind": "asgi-callable-instance-observer",
    "response_content": "asgi instance ok",
}
DECLARED_UNSCOPED_SUPPORT_GAPS = {
    (
        "starlette.applications.Starlette",
        "__init__",
        "rust-native",
    ): frozenset(
        {
            "starlette.asgi.python-callables",
            "starlette.asgi.scope-mutation",
            "starlette.asgi.streaming",
            "starlette.compatibility.full-public-surface",
        }
    ),
    (
        "starlette.applications.Starlette",
        "__init__",
        "python-package",
    ): frozenset(
        {
            "starlette.asgi.boundary-cancellation",
            "starlette.asgi.scope-mutation",
            "starlette.asgi.streaming",
            "starlette.compatibility.full-public-surface",
        }
    ),
    (
        "starlette.applications.Starlette",
        "__call__",
        "rust-native",
    ): frozenset(
        {
            "starlette.asgi.python-callables",
            "starlette.asgi.scope-mutation",
            "starlette.asgi.streaming",
            "starlette.compatibility.full-public-surface",
        }
    ),
    (
        "starlette.applications.Starlette",
        "__call__",
        "python-package",
    ): frozenset(
        {
            "starlette.asgi.boundary-cancellation",
            "starlette.asgi.scope-mutation",
            "starlette.asgi.streaming",
            "starlette.compatibility.full-public-surface",
        }
    ),
    (ROUTER_SURFACE, ROUTER_OPERATION, "rust-native"): frozenset(
        {"starlette.routing.Router.route-dispatch.python-callable-endpoint"}
    ),
}
GZIP_SURFACE = "starlette.middleware.gzip.GZipMiddleware"
CORS_SURFACE = "starlette.middleware.cors.CORSMiddleware"
HTTPS_REDIRECT_SURFACE = "starlette.middleware.httpsredirect.HTTPSRedirectMiddleware"
TRUSTED_HOST_SURFACE = "starlette.middleware.trustedhost.TrustedHostMiddleware"
ASGI_MIDDLEWARE_SURFACES = {
    GZIP_SURFACE,
    CORS_SURFACE,
    HTTPS_REDIRECT_SURFACE,
    TRUSTED_HOST_SURFACE,
}
BODY_LIMIT_SURFACE = "starlette.middleware.body_limit.RequestBodyLimitMiddleware"
BODY_LIMIT_REQUIREMENT_CONSTRUCTION = (
    "starlette.middleware.body_limit.RequestBodyLimitMiddleware.construct"
)
BODY_LIMIT_REQUIREMENTS = {
    "content-length-precheck": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.content-length-precheck",
    "content-length-replacement": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.content-length-replacement",
    "streamed-body-count": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.streamed-body-count",
    "understated-content-length": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.understated-content-length",
    "invalid-content-length": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.invalid-content-length",
    "nested-limits": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.nested-limits",
    "already-started-propagation": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.already-started-propagation",
    "scope-restoration": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.scope-restoration",
    "non-http-pass-through": "starlette.middleware.body_limit.RequestBodyLimitMiddleware.non-http-pass-through",
}
GZIP_REQUIREMENT_CONSTRUCTION = "starlette.middleware.gzip.GZipMiddleware.construct"
GZIP_REQUIREMENTS = {
    "gzip-final-response": "starlette.middleware.gzip.GZipMiddleware.gzip-final-response",
    "identity-client": "starlette.middleware.gzip.GZipMiddleware.identity-client",
    "small-body-bypass": "starlette.middleware.gzip.GZipMiddleware.small-body-bypass",
    "excluded-content-type": "starlette.middleware.gzip.GZipMiddleware.excluded-content-type",
    "existing-encoding-stream-bypass": "starlette.middleware.gzip.GZipMiddleware.existing-encoding-stream-bypass",
    "partial-response-stream-bypass": "starlette.middleware.gzip.GZipMiddleware.partial-response-stream-bypass",
    "streaming-chunks": "starlette.middleware.gzip.GZipMiddleware.streaming-chunks",
    "pathsend": "starlette.middleware.gzip.GZipMiddleware.pathsend",
}


class ContractError(ValueError):
    """A malformed or incompatible parity contract or evidence artifact."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON number is forbidden: {value}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc


def load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    try:
        value = json.loads(
            raw, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant
        )
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ContractError(
                "manifest is not JSON-compatible YAML and PyYAML is unavailable"
            ) from exc
        value = yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ContractError("manifest must be an object")
    return value


def _exact(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    actual = set(value)
    if actual != keys:
        raise ContractError(
            f"{context} keys differ: missing={sorted(keys - actual)}, unknown={sorted(actual - keys)}"
        )
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{context} must be a non-empty string")
    return value


def _validate_request_stream_endpoint(endpoint: Any) -> dict[str, Any]:
    endpoint = _exact(endpoint, {"kind", "actions"}, "request stream-observer endpoint")
    if endpoint["kind"] != "request-stream-observer":
        raise ContractError("request stream endpoint must use the declared observer kind")
    actions = endpoint["actions"]
    if not isinstance(actions, list) or not actions:
        raise ContractError("request stream actions must be a non-empty sequence")
    operations: list[str] = []
    for index, action in enumerate(actions):
        context = f"request stream action[{index}]"
        if not isinstance(action, dict):
            raise ContractError(f"{context} must be an object")
        operation = action.get("operation")
        if operation in {"anext", "aclose"}:
            _exact(action, {"operation"}, context)
        elif operation == "asend":
            _exact(action, {"operation", "value"}, context)
            if not isinstance(action["value"], str):
                raise ContractError(f"{context}.value must be a string")
        elif operation == "athrow":
            _exact(action, {"operation", "exception_type", "message"}, context)
            if action["exception_type"] != "ValueError":
                raise ContractError(f"{context}.exception_type must be ValueError")
            _string(action["message"], f"{context}.message")
        else:
            raise ContractError(f"{context}.operation is unsupported")
        operations.append(operation)
    for index, operation in enumerate(operations):
        if operation in REQUEST_STREAM_REQUIREMENTS and "anext" not in operations[:index]:
            raise ContractError(f"request stream {operation} must be observed after anext")
    return endpoint


def _validate_sync_request_runtime_endpoint(endpoint: Any) -> dict[str, Any]:
    endpoint = _exact(
        endpoint,
        {"kind", "actions", "context_var_name", "context_value", "response_content"},
        "sync request runtime-observer endpoint",
    )
    if endpoint["kind"] != "sync-request-runtime-observer":
        raise ContractError("sync request runtime endpoint must use the declared observer kind")
    _string(endpoint["context_var_name"], "sync request runtime context variable name")
    _string(endpoint["context_value"], "sync request runtime context value")
    _string(endpoint["response_content"], "sync request runtime response content")

    actions = endpoint["actions"]
    if not isinstance(actions, list) or not actions:
        raise ContractError("sync request runtime actions must be a non-empty sequence")
    covered: set[str] = set()
    stream_attributes = {"__aiter__", "__anext__", "asend", "athrow", "aclose"}
    for index, action in enumerate(actions):
        context = f"sync request runtime action[{index}]"
        if not isinstance(action, dict):
            raise ContractError(f"{context} must be an object")
        operation = action.get("operation")
        if operation == "callable-property":
            _exact(action, {"operation", "property"}, context)
            if action["property"] != "receive":
                raise ContractError(f"{context}.property must be receive")
            covered.add("receive")
        elif operation == "construct-stream":
            _exact(action, {"operation", "method", "attributes"}, context)
            if action["method"] != "stream":
                raise ContractError(f"{context}.method must be stream")
            attributes = action["attributes"]
            if (
                not isinstance(attributes, list)
                or not attributes
                or any(
                    not isinstance(name, str) or name not in stream_attributes
                    for name in attributes
                )
                or len(attributes) != len(set(attributes))
            ):
                raise ContractError(f"{context}.attributes must be unique async-iterator methods")
            covered.add("stream")
        elif operation == "construct-awaitable":
            _exact(action, {"operation", "method"}, context)
            if action["method"] not in {"body", "json"}:
                raise ContractError(f"{context}.method must be body or json")
            covered.add(action["method"])
        else:
            raise ContractError(f"{context}.operation is unsupported")
    if covered != set(SYNC_REQUEST_RUNTIME_REQUIREMENTS):
        raise ContractError(
            "sync request runtime actions must cover receive, stream, body, and json"
        )
    return endpoint


def _unique_ids(rows: Any, field: str, context: str) -> set[str]:
    if not isinstance(rows, list):
        raise ContractError(f"{context} must be an array")
    ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"{context}[{index}] must be an object")
        item_id = _string(row.get(field), f"{context}[{index}].{field}")
        if item_id in ids:
            raise ContractError(f"duplicate {context} id: {item_id}")
        ids.add(item_id)
    return ids


def validate_manifest(manifest: dict[str, Any]) -> None:
    _exact(manifest, TOP_KEYS, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ContractError(f"unsupported manifest schema: {manifest['schema']!r}")
    scope = _exact(manifest["scope"], {"id", "mode", "inventory"}, "scope")
    _string(scope["id"], "scope.id")
    if scope["mode"] not in {"slice", "full"}:
        raise ContractError("scope.mode must be slice or full")
    inventory = _exact(
        scope["inventory"], {"authority", "revision", "command_id"}, "scope.inventory"
    )
    for name in inventory:
        _string(inventory[name], f"scope.inventory.{name}")
    if inventory["revision"] != ORACLE_COMMIT:
        raise ContractError(
            "scope.inventory.revision differs from the pinned Starlette 1.6.0 commit"
        )

    oracle_ids = _unique_ids(manifest["oracles"], "id", "oracles")
    target_ids = _unique_ids(manifest["targets"], "id", "targets")
    profile_ids = _unique_ids(manifest["target_profiles"], "id", "target_profiles")
    command_ids = _unique_ids(manifest["commands"], "id", "commands")
    if oracle_ids != {"starlette-python"} or target_ids != {"rust-native", "python-package"}:
        raise ContractError(
            "this slice requires the pinned Starlette oracle and both separate public targets"
        )
    for index, oracle in enumerate(manifest["oracles"]):
        _exact(
            oracle,
            {"id", "name", "version", "runtime", "identity_command_id", "contract", "components"},
            f"oracles[{index}]",
        )
        if oracle["version"] != "1.6.0":
            raise ContractError("oracle version must remain Starlette 1.6.0")
        if oracle["identity_command_id"] not in command_ids:
            raise ContractError("oracle identity command is not declared")
        if not isinstance(oracle["components"], list):
            raise ContractError("oracle components must be an array")
        for component_index, component in enumerate(oracle["components"]):
            _exact(
                component,
                {"id", "name", "version"},
                f"oracles[{index}].components[{component_index}]",
            )
    for index, target in enumerate(manifest["targets"]):
        _exact(
            target,
            {"id", "name", "runtime", "identity_command_id", "contract"},
            f"targets[{index}]",
        )
        if target["identity_command_id"] not in command_ids:
            raise ContractError(f"targets[{index}] identity command is not declared")

    seen_profiles: set[str] = set()
    for index, profile in enumerate(manifest["target_profiles"]):
        _exact(profile, {"id", "target_id", "backend", "features"}, f"target_profiles[{index}]")
        if profile["target_id"] not in target_ids:
            raise ContractError(f"target_profiles[{index}] refers to unknown target")
        if not isinstance(profile["features"], list) or any(
            not isinstance(item, str) for item in profile["features"]
        ):
            raise ContractError(f"target_profiles[{index}].features must be a string array")
        seen_profiles.add(profile["id"])
    if {row["target_id"] for row in manifest["target_profiles"]} != target_ids:
        raise ContractError("each public target must have a behavior profile")

    command_map: dict[str, dict[str, Any]] = {}
    for index, command in enumerate(manifest["commands"]):
        _exact(command, {"id", "argv", "cwd", "timeout_seconds"}, f"commands[{index}]")
        if (
            not isinstance(command["argv"], list)
            or not command["argv"]
            or any(not isinstance(part, str) or not part for part in command["argv"])
        ):
            raise ContractError(f"commands[{index}].argv must be a non-empty string array")
        if command["cwd"] != ".":
            raise ContractError(f"commands[{index}].cwd must be repository-relative '.'")
        if not isinstance(command["timeout_seconds"], int) or command["timeout_seconds"] < 1:
            raise ContractError(f"commands[{index}].timeout_seconds must be positive")
        command_map[command["id"]] = command
    expected_interpreters = {
        "oracle-starlette-python": "{environment:starlette-oracle-cpython312}",
        "target-python-package": "{environment:starlette-rs-py-cpython312}",
    }
    for command_id, interpreter in expected_interpreters.items():
        if command_id not in command_map or command_map[command_id]["argv"][0] != interpreter:
            raise ContractError(
                f"{command_id} must use its prepared root-relative CPython environment"
            )
    if "prepare-env" not in command_ids:
        raise ContractError("manifest must provide the reproducible prepare-env command")
    if inventory["command_id"] not in command_ids:
        raise ContractError("scope inventory command is not declared")

    interfaces = _exact(
        manifest["interfaces"],
        {"parity", "coverage", "benchmark", "upstream_benchmark", "aggregation"},
        "interfaces",
    )
    for lane in ("parity", "coverage", "benchmark"):
        item = _exact(
            interfaces[lane], {"input_schema", "result_schema", "command_id"}, f"interfaces.{lane}"
        )
        if item["command_id"] not in command_ids:
            raise ContractError(f"interfaces.{lane}.command_id is not declared")
    if (
        interfaces["parity"]["input_schema"] != INPUT_SCHEMA
        or interfaces["parity"]["result_schema"] != RESULT_SCHEMA
    ):
        raise ContractError("parity interface schema identifiers are incompatible")
    if (
        interfaces["benchmark"]["input_schema"] != BENCHMARK_INPUT_SCHEMA
        or interfaces["benchmark"]["result_schema"] != BENCHMARK_RESULT_SCHEMA
    ):
        raise ContractError("benchmark interface schema identifiers are incompatible")
    upstream_benchmark = _exact(
        interfaces["upstream_benchmark"],
        {"input_schema", "result_schema", "command_id"},
        "interfaces.upstream_benchmark",
    )
    if (
        upstream_benchmark["input_schema"] != UPSTREAM_BENCHMARK_INPUT_SCHEMA
        or upstream_benchmark["result_schema"] != UPSTREAM_BENCHMARK_RESULT_SCHEMA
        or upstream_benchmark["command_id"] != "benchmark-upstream"
        or upstream_benchmark["command_id"] not in command_ids
    ):
        raise ContractError("upstream benchmark interface schema or command is incompatible")
    aggregation = _exact(
        interfaces["aggregation"],
        {"input_schemas", "result_schema", "command_id"},
        "interfaces.aggregation",
    )
    if aggregation["command_id"] not in command_ids or not isinstance(
        aggregation["input_schemas"], list
    ):
        raise ContractError("aggregation command or input_schemas are invalid")
    if aggregation["input_schemas"] != list(AGGREGATION_INPUT_SCHEMAS):
        raise ContractError(
            "aggregation input schemas differ from the registered result interfaces"
        )

    index = _exact(manifest["input_index"], {"parity", "coverage", "benchmark"}, "input_index")
    for lane in index:
        paths = index[lane]
        if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
            raise ContractError(f"input_index.{lane} must be a string array")
        if len(paths) != len(set(paths)):
            raise ContractError(f"input_index.{lane} contains duplicates")
        prefix = (GENERATED_INPUT_ROOT / lane).parts
        for path in paths:
            relative = Path(path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix != ".json"
                or relative.parts[: len(prefix)] != prefix
            ):
                raise ContractError(
                    f"input_index.{lane} entries must be JSON beneath "
                    f"{(GENERATED_INPUT_ROOT / lane).as_posix()}: {path}"
                )

    if not isinstance(manifest["coverage_components"], list):
        raise ContractError("coverage_components must be an array")
    for index, component in enumerate(manifest["coverage_components"]):
        _exact(
            component,
            {"id", "target_profile", "paths", "dimensions", "thresholds"},
            f"coverage_components[{index}]",
        )

    surfaces = manifest["surfaces"]
    if not isinstance(surfaces, list) or not surfaces:
        raise ContractError("surfaces must be a non-empty array")
    _unique_ids(surfaces, "id", "surfaces")
    operation_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for surface_index, surface in enumerate(surfaces):
        _exact(
            surface,
            {"id", "kind", "source_path", "storage_slug", "operations"},
            f"surfaces[{surface_index}]",
        )
        operations = surface["operations"]
        if not isinstance(operations, list) or not operations:
            raise ContractError(f"surfaces[{surface_index}].operations must be non-empty")
        for operation_index, operation in enumerate(operations):
            context = f"surfaces[{surface_index}].operations[{operation_index}]"
            _exact(
                operation,
                {
                    "id",
                    "kind",
                    "classification",
                    "lifecycle",
                    "source",
                    "targets",
                    "requirements",
                    "parity",
                    "coverage",
                    "benchmark",
                },
                context,
            )
            if operation["classification"] not in {"endpoint", "non_endpoint"}:
                raise ContractError(f"{context}.classification is invalid")
            lifecycle = _exact(operation["lifecycle"], {"status"}, f"{context}.lifecycle")
            if lifecycle["status"] != "current":
                raise ContractError("this first slice only includes current API operations")
            key = (surface["id"], operation["id"])
            if key in operation_rows:
                raise ContractError(f"duplicate operation: {key}")
            operation_rows[key] = operation
            source = _exact(
                operation["source"],
                {"oracle_id", "path", "signature", "parameters", "result"},
                f"{context}.source",
            )
            if source["oracle_id"] not in oracle_ids:
                raise ContractError(f"{context}.source uses unknown oracle")
            params = source["parameters"]
            if not isinstance(params, list):
                raise ContractError(f"{context}.source.parameters must be an array")
            param_ids: set[str] = set()
            for param_index, parameter in enumerate(params):
                pctx = f"{context}.source.parameters[{param_index}]"
                _exact(parameter, {"id", "style", "value_types", "omission"}, pctx)
                if parameter["id"] in param_ids:
                    raise ContractError(f"{pctx}.id is duplicated")
                param_ids.add(parameter["id"])
                if parameter["style"] not in PARAMETER_STYLES:
                    raise ContractError(f"{pctx}.style is unsupported")
                if (
                    not isinstance(parameter["value_types"], list)
                    or not parameter["value_types"]
                    or not set(parameter["value_types"]) <= VALUE_TYPES
                ):
                    raise ContractError(f"{pctx}.value_types is invalid")
                omission = parameter["omission"]
                if not isinstance(omission, dict) or omission.get("kind") not in {
                    "required",
                    "literal",
                    "sentinel",
                }:
                    raise ContractError(f"{pctx}.omission is invalid")
                if omission["kind"] == "literal":
                    _exact(omission, {"kind", "value"}, f"{pctx}.omission")
                elif omission["kind"] == "required":
                    _exact(omission, {"kind"}, f"{pctx}.omission")
                else:
                    _exact(omission, {"kind", "name", "semantics"}, f"{pctx}.omission")
            result = _exact(
                source["result"], {"shape", "observations", "error"}, f"{context}.source.result"
            )
            if result["shape"] not in RESULT_SHAPES:
                raise ContractError(f"{context}.source.result.shape is invalid")
            obs_paths: set[str] = set()
            if not isinstance(result["observations"], list):
                raise ContractError(f"{context}.source.result.observations must be an array")
            for obs_index, observation in enumerate(result["observations"]):
                octx = f"{context}.source.result.observations[{obs_index}]"
                if not isinstance(observation, dict):
                    raise ContractError(f"{octx} must be an object")
                expected_observation_keys = {"path", "value_types", "comparison"}
                if "normalization" in observation:
                    expected_observation_keys.add("normalization")
                _exact(observation, expected_observation_keys, octx)
                if observation["path"] in obs_paths:
                    raise ContractError(f"{octx}.path is duplicated")
                obs_paths.add(observation["path"])
                if (
                    not isinstance(observation["value_types"], list)
                    or not observation["value_types"]
                    or not set(observation["value_types"]) <= VALUE_TYPES
                ):
                    raise ContractError(f"{octx}.value_types is invalid")
                comparison = observation["comparison"]
                if (
                    not isinstance(comparison, dict)
                    or comparison.get("kind") not in OBSERVATION_COMPARISONS
                ):
                    raise ContractError(f"{octx}.comparison is unsupported")
                _exact(comparison, {"kind"}, f"{octx}.comparison")
                if "normalization" in observation:
                    normalization_spec = observation["normalization"]
                    if not isinstance(normalization_spec, dict):
                        raise ContractError(f"{octx}.normalization must be an object")
                    normalization_kind = normalization_spec.get("kind")
                    if normalization_kind == "allow-methods-as-set":
                        _exact(normalization_spec, {"kind"}, f"{octx}.normalization")
                        if (
                            observation["path"] not in {"ordered_repeated_headers", "asgi_events"}
                            or comparison["kind"] != "ordered"
                        ):
                            raise ContractError(
                                f"{octx} only permits ordered Allow-method token-set normalization"
                            )
                    elif normalization_kind == "starlette-debug-traceback":
                        _exact(normalization_spec, {"kind"}, f"{octx}.normalization")
                        if observation["path"] == "response_bytes":
                            if comparison["kind"] == "bytes":
                                continue
                        elif (
                            observation["path"]
                            in {
                                "ordered_repeated_headers",
                                "asgi_events",
                            }
                            and comparison["kind"] == "ordered"
                        ):
                            continue
                        raise ContractError(
                            f"{octx} permits traceback normalization only for response bytes, headers, or events"
                        )
                    elif normalization_kind == "sequence":
                        _exact(
                            normalization_spec,
                            {"kind", "steps"},
                            f"{octx}.normalization",
                        )
                        steps = normalization_spec["steps"]
                        if not isinstance(steps, list):
                            raise ContractError(f"{octx}.normalization.steps must be an array")
                        step_kinds: list[str] = []
                        for step_index, step in enumerate(steps):
                            step_context = f"{octx}.normalization.steps[{step_index}]"
                            step = _exact(step, {"kind"}, step_context)
                            step_kinds.append(step["kind"])
                        if (
                            observation["path"] not in {"ordered_repeated_headers", "asgi_events"}
                            or comparison["kind"] != "ordered"
                            or step_kinds != ["allow-methods-as-set", "starlette-debug-traceback"]
                        ):
                            raise ContractError(
                                f"{octx} permits only the declared ordered header or ASGI event normalization sequence"
                            )
                    else:
                        raise ContractError(f"{octx}.normalization kind is unsupported")
            error = _exact(result["error"], {"fields", "message"}, f"{context}.source.result.error")
            # WebSocket sequence failures are part of the declared observation
            # value: callback presence for protocol-sequence, or action outcome
            # and message for state-sequence. Adapter/runtime failures remain
            # top-level infrastructure errors in the parity result.
            expected_error_fields = (
                set()
                if key in WEBSOCKET_PROJECTED_ERROR_OPERATIONS
                or key in REVERSE_URL_OPERATIONS
                or key in VALUE_FORMATTING_OPERATIONS
                or key in RUST_OWNED_PYTHON_OPERATIONS
                or key == REQUEST_DEFAULT_RECEIVE_OPERATION
                else {
                    "class",
                    "kind",
                    "message",
                    "stage",
                    "code",
                    "cause",
                    "suppress_context",
                }
            )
            if (
                not isinstance(error["fields"], list)
                or len(error["fields"]) != len(set(error["fields"]))
                or set(error["fields"]) != expected_error_fields
            ):
                raise ContractError(f"{context}.source.result.error.fields is invalid")
            message = _exact(
                error["message"],
                {"mode", "transforms", "reason"},
                f"{context}.source.result.error.message",
            )
            if message != {"mode": "exact", "transforms": [], "reason": None}:
                raise ContractError("this slice compares exact public errors without normalization")

            partial_support_gaps: list[tuple[str, list[str]]] = []
            bindings = operation["targets"]
            if (
                not isinstance(bindings, list)
                or {binding.get("target_id") for binding in bindings} != target_ids
            ):
                raise ContractError(f"{context} must bind both public targets exactly once")
            for binding_index, binding in enumerate(bindings):
                bctx = f"{context}.targets[{binding_index}]"
                _exact(binding, {"target_id", "path", "signature", "support"}, bctx)
                support = binding["support"]
                if not isinstance(support, dict) or support.get("status") not in {
                    "supported",
                    "partial",
                    "unimplemented",
                    "intentionally_unsupported",
                    "out_of_scope",
                    "not_applicable",
                }:
                    raise ContractError(f"{bctx}.support.status is invalid")
                if support["status"] == "unimplemented":
                    _exact(support, {"status", "reason", "blocker"}, f"{bctx}.support")
                    if binding["signature"] is not None:
                        raise ContractError(f"{bctx} claims a signature while unimplemented")
                elif support["status"] == "supported":
                    _exact(support, {"status"}, f"{bctx}.support")
                    if not binding["path"] or not binding["signature"]:
                        raise ContractError(f"{bctx} is supported without a path/signature")
                elif support["status"] == "partial":
                    _exact(support, {"status", "reason", "missing_requirements"}, f"{bctx}.support")
                    _string(support["reason"], f"{bctx}.support.reason")
                    missing_requirements = support["missing_requirements"]
                    if (
                        not binding["path"]
                        or not binding["signature"]
                        or not isinstance(missing_requirements, list)
                        or not missing_requirements
                        or any(
                            not isinstance(requirement, str) or not requirement
                            for requirement in missing_requirements
                        )
                        or len(missing_requirements) != len(set(missing_requirements))
                    ):
                        raise ContractError(
                            f"{bctx} partial support requires a path, signature, and unique missing requirement IDs"
                        )
                    partial_support_gaps.append((binding["target_id"], missing_requirements))
                else:
                    raise ContractError(
                        f"{bctx}.support status is not currently modeled by this slice validator"
                    )

            requirements = operation["requirements"]
            if not isinstance(requirements, list) or not requirements:
                raise ContractError(f"{context}.requirements must contain at least one record")
            for req_index, req in enumerate(requirements):
                rctx = f"{context}.requirements[{req_index}]"
                _exact(req, {"id", "dimension", "description", "lanes", "target_profiles"}, rctx)
                _string(req["id"], f"{rctx}.id")
                if req["dimension"] not in {
                    "parameter",
                    "parameter_combination",
                    "input_family",
                    "success_path",
                    "error_path",
                    "mode",
                    "format",
                    "protocol_variant",
                    "abi_variant",
                    "asset_family",
                    "boundary",
                    "backend",
                    "runtime",
                    "feature",
                    "historical_divergence",
                    "code_path",
                    "performance",
                    "documentation",
                }:
                    raise ContractError(f"{rctx}.dimension is invalid")
                if (
                    not isinstance(req["lanes"], list)
                    or not req["lanes"]
                    or not set(req["lanes"]) <= {"parity", "coverage", "benchmark"}
                ):
                    raise ContractError(f"{rctx}.lanes must select known evidence lanes")
                requirement_profiles = req["target_profiles"]
                if (
                    not isinstance(requirement_profiles, list)
                    or not requirement_profiles
                    or any(not isinstance(item, str) for item in requirement_profiles)
                    or len(requirement_profiles) != len(set(requirement_profiles))
                    or not set(requirement_profiles) <= profile_ids
                ):
                    raise ContractError(f"{rctx} must map to declared target profiles")
            requirement_ids = {req["id"] for req in requirements}
            for target_id, missing_requirements in partial_support_gaps:
                unscoped_gaps = DECLARED_UNSCOPED_SUPPORT_GAPS.get(
                    (surface["id"], operation["id"], target_id), frozenset()
                )
                unknown_requirements = set(missing_requirements) - requirement_ids - unscoped_gaps
                if unknown_requirements:
                    raise ContractError(
                        f"{context}.targets missing support references undeclared requirement IDs: {sorted(unknown_requirements)}"
                    )
            for lane in ("parity", "coverage", "benchmark"):
                policy = operation[lane]
                if not isinstance(policy, dict) or policy.get("applicability") not in {
                    "required",
                    "not_applicable",
                }:
                    raise ContractError(f"{context}.{lane}.applicability is invalid")
                if policy["applicability"] == "not_applicable":
                    _exact(policy, {"applicability", "reason"}, f"{context}.{lane}")
                    if lane == "parity":
                        raise ContractError(f"{context}.parity cannot be not_applicable")
                elif lane == "parity":
                    _exact(policy, {"applicability", "target_profiles"}, f"{context}.{lane}")
                    expected_parity_profiles = (
                        {"python-package-cpython312"}
                        if (surface["id"], operation["id"])
                        in {
                            (WEBSOCKET_ROUTE_SURFACE, WEBSOCKET_ROUTE_OPERATION),
                            (WEBSOCKET_SURFACE, WEBSOCKET_OPERATION),
                            (WEBSOCKET_SURFACE, WEBSOCKET_CONVENIENCE_OPERATION),
                            (WEBSOCKET_CLOSE_SURFACE, WEBSOCKET_CLOSE_OPERATION),
                        }
                        or (surface["id"], operation["id"]) in REVERSE_URL_OPERATIONS
                        or (surface["id"], operation["id"])
                        == (STREAMING_RESPONSE_SURFACE, STREAMING_RESPONSE_TRACE_OPERATION)
                        or surface["id"] == BODY_LIMIT_SURFACE
                        or surface["id"]
                        in {
                            CORS_SURFACE,
                            HTTPS_REDIRECT_SURFACE,
                            TRUSTED_HOST_SURFACE,
                        }
                        or (surface["id"], operation["id"]) in VALUE_FORMATTING_OPERATIONS
                        or (surface["id"], operation["id"]) in RUST_OWNED_PYTHON_OPERATIONS
                        or (surface["id"], operation["id"]) == REQUEST_DEFAULT_RECEIVE_OPERATION
                        or (surface["id"], operation["id"]) == STATUS_OPERATION
                        else profile_ids
                    )
                    if set(policy["target_profiles"]) != expected_parity_profiles:
                        raise ContractError(
                            f"{context}.parity target profiles differ from the declared operation scope"
                        )
                elif lane == "benchmark":
                    _exact(
                        policy,
                        {"applicability", "target_profiles", "metrics"},
                        f"{context}.benchmark",
                    )
                    if set(policy["target_profiles"]) != profile_ids or policy["metrics"] != [
                        "latency"
                    ]:
                        raise ContractError(
                            f"{context}.benchmark must select both profiles and latency"
                        )
                elif lane == "coverage":
                    _exact(
                        policy,
                        {"applicability", "target_profiles", "component_ids"},
                        f"{context}.coverage",
                    )
                    raise ContractError(
                        "required coverage has no active component input in this slice"
                    )
                else:
                    raise ContractError(
                        f"{context}.{lane} is required but this contract has no matching input"
                    )

    docs = _exact(
        manifest["documentation"],
        {"command_id", "specification_outputs", "evidence_outputs"},
        "documentation",
    )
    if docs["command_id"] not in command_ids:
        raise ContractError("documentation command is not declared")
    if not isinstance(docs["specification_outputs"], list) or not isinstance(
        docs["evidence_outputs"], list
    ):
        raise ContractError("documentation destinations must be arrays")


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "sequence"
    if isinstance(value, dict):
        return "mapping"
    raise ContractError(f"unsupported JSON value type: {type(value).__name__}")


def _descriptor(value: Any, previous_steps: set[str], context: str) -> Any:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be a value descriptor")
    kind = value.get("kind")
    if kind == "literal":
        _exact(value, {"kind", "value"}, context)
        return value["value"]
    if kind == "asset":
        _exact(value, {"kind", "asset_id"}, context)
        raise ContractError(f"{context} references an asset although this slice declares none")
    if kind == "binding":
        _exact(value, {"kind", "step_id"}, context)
        if value["step_id"] not in previous_steps:
            raise ContractError(f"{context} refers to a missing or later step")
        return {"__binding_step__": value["step_id"]}
    raise ContractError(f"{context} uses an unknown value descriptor kind: {kind!r}")


def _validate_websocket_scope(scope: Any) -> None:
    scope_keys = {
        "type",
        "asgi",
        "http_version",
        "scheme",
        "path",
        "raw_path_base64",
        "query_string_base64",
        "root_path",
        "headers_base64_pairs",
        "client",
        "server",
        "subprotocols",
    }
    if isinstance(scope, dict) and "extensions" in scope:
        scope_keys.add("extensions")
    scope = _exact(
        scope,
        scope_keys,
        "WebSocket scope",
    )
    if scope["type"] != "websocket":
        raise ContractError("WebSocket scope.type must be websocket")
    asgi = _exact(scope["asgi"], {"version", "spec_version"}, "WebSocket scope.asgi")
    if asgi != {"version": "3.0", "spec_version": "2.5"}:
        raise ContractError("WebSocket scope must use ASGI 3.0 with spec version 2.5")
    _string(scope["http_version"], "WebSocket scope.http_version")
    scheme = _string(scope["scheme"], "WebSocket scope.scheme")
    if scheme not in {"ws", "wss"}:
        raise ContractError("WebSocket scope.scheme must be ws or wss")
    path = _string(scope["path"], "WebSocket scope.path")
    if scope["raw_path_base64"] != base64.b64encode(path.encode("ascii")).decode("ascii"):
        raise ContractError("WebSocket raw_path bytes must match the declared ASCII path")
    if not isinstance(scope["root_path"], str):
        raise ContractError("WebSocket scope.root_path must be a string")
    for key in ("raw_path_base64", "query_string_base64"):
        try:
            base64.b64decode(scope[key], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"WebSocket scope.{key} is invalid base64") from exc
    headers = scope["headers_base64_pairs"]
    if not isinstance(headers, list):
        raise ContractError("WebSocket scope.headers_base64_pairs must be an array")
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ContractError("each WebSocket scope header must be a two-item array")
        for value in pair:
            try:
                base64.b64decode(value, validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError("WebSocket scope header contains invalid base64") from exc
    for name in ("client", "server"):
        address = scope[name]
        if (
            not isinstance(address, list)
            or len(address) != 2
            or not isinstance(address[0], str)
            or not isinstance(address[1], int)
            or isinstance(address[1], bool)
        ):
            raise ContractError(f"WebSocket scope.{name} must be [host, port]")
    subprotocols = scope["subprotocols"]
    if not isinstance(subprotocols, list) or any(
        not isinstance(item, str) for item in subprotocols
    ):
        raise ContractError("WebSocket scope.subprotocols must be an array of strings")
    if "extensions" in scope:
        extensions = scope["extensions"]
        if not isinstance(extensions, dict):
            raise ContractError("WebSocket scope.extensions must be an object")
        for extension, configuration in extensions.items():
            _string(extension, "WebSocket scope extension name")
            if not isinstance(configuration, dict):
                raise ContractError("WebSocket scope extension configurations must be objects")


def _validate_websocket_message(message: Any, context: str, *, incoming: bool) -> str:
    if not isinstance(message, dict):
        raise ContractError(f"{context} must be an ASGI message object")
    message_type = _string(message.get("type"), f"{context}.type")
    if incoming:
        if message_type == "websocket.connect":
            _exact(message, {"type", "subprotocols"}, context)
            if not isinstance(message["subprotocols"], list) or any(
                not isinstance(item, str) for item in message["subprotocols"]
            ):
                raise ContractError(f"{context}.subprotocols must be an array of strings")
        elif message_type == "websocket.receive":
            if set(message) not in ({"type", "text"}, {"type", "bytes_base64"}):
                raise ContractError(f"{context} must contain exactly type and text or bytes_base64")
            if "text" in message:
                if not isinstance(message["text"], str):
                    raise ContractError(f"{context}.text must be a string")
            else:
                try:
                    base64.b64decode(message["bytes_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{context}.bytes_base64 is invalid base64") from exc
        elif message_type == "websocket.disconnect":
            if set(message) not in (
                {"type", "code"},
                {"type", "code", "reason"},
            ):
                raise ContractError(f"{context} must contain type, code, and optional reason")
            if (
                not isinstance(message["code"], int)
                or isinstance(message["code"], bool)
                or message["code"] < 0
            ):
                raise ContractError(f"{context}.code must be a non-negative integer")
            if "reason" in message and not isinstance(message["reason"], str):
                raise ContractError(f"{context}.reason must be a string")
        else:
            raise ContractError(
                f"{context}.type is unsupported for incoming WebSocket messages: {message_type!r}"
            )
        return message_type

    if message_type == "websocket.accept":
        allowed = {"type", "subprotocol", "headers_base64_pairs"}
        if set(message) - allowed or "type" not in message:
            raise ContractError(f"{context} has fields unsupported for websocket.accept")
        if "subprotocol" in message and message["subprotocol"] is not None:
            _string(message["subprotocol"], f"{context}.subprotocol")
        if "headers_base64_pairs" in message:
            headers = message["headers_base64_pairs"]
            if not isinstance(headers, list):
                raise ContractError(f"{context}.headers_base64_pairs must be an array")
            for pair in headers:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ContractError(f"{context} header must be a two-item array")
                for value in pair:
                    try:
                        base64.b64decode(value, validate=True)
                    except (ValueError, TypeError) as exc:
                        raise ContractError(f"{context} header contains invalid base64") from exc
    elif message_type == "websocket.close":
        if set(message) not in ({"type", "code"}, {"type", "code", "reason"}):
            raise ContractError(f"{context} must contain type, code, and optional reason")
        if (
            not isinstance(message["code"], int)
            or isinstance(message["code"], bool)
            or message["code"] < 0
        ):
            raise ContractError(f"{context}.code must be a non-negative integer")
        if "reason" in message and not isinstance(message["reason"], str):
            raise ContractError(f"{context}.reason must be a string")
    elif message_type == "websocket.send":
        if set(message) not in ({"type", "text"}, {"type", "bytes_base64"}):
            raise ContractError(f"{context} must contain exactly type and text or bytes_base64")
        if "text" in message:
            if not isinstance(message["text"], str):
                raise ContractError(f"{context}.text must be a string")
        else:
            try:
                base64.b64decode(message["bytes_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError(f"{context}.bytes_base64 is invalid base64") from exc
    elif message_type == "websocket.http.response.start":
        _exact(message, {"type", "status", "headers_base64_pairs"}, context)
        if not isinstance(message["status"], int) or isinstance(message["status"], bool):
            raise ContractError(f"{context}.status must be an integer")
        headers = message["headers_base64_pairs"]
        if not isinstance(headers, list):
            raise ContractError(f"{context}.headers_base64_pairs must be an array")
        for pair in headers:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ContractError(f"{context} header must be a two-item array")
            for value in pair:
                try:
                    base64.b64decode(value, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{context} header contains invalid base64") from exc
    elif message_type == "websocket.http.response.body":
        _exact(message, {"type", "body_base64", "more_body"}, context)
        if not isinstance(message["more_body"], bool):
            raise ContractError(f"{context}.more_body must be boolean")
        try:
            base64.b64decode(message["body_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"{context}.body_base64 is invalid base64") from exc
    else:
        raise ContractError(
            f"{context}.type is unsupported for outgoing WebSocket messages: {message_type!r}"
        )
    return message_type


def _validate_websocket_case_stimulus(case: dict[str, Any]) -> None:
    operation = case["operation"]
    if operation not in {WEBSOCKET_OPERATION, WEBSOCKET_STATE_OPERATION}:
        raise ContractError("WebSocket cases must use a declared sequence operation")
    _validate_websocket_scope(case["scope"])
    incoming = case["incoming"]
    actions = case["actions"]
    if not isinstance(incoming, list) or not isinstance(actions, list) or not actions:
        raise ContractError(
            "WebSocket incoming and actions must be arrays, with at least one action"
        )
    incoming_types = [
        _validate_websocket_message(message, f"WebSocket incoming[{index}]", incoming=True)
        for index, message in enumerate(incoming)
    ]
    action_ids: set[str] = set()
    incoming_index = 0
    client_state = "CONNECTING"
    application_state = "CONNECTING"
    terminal_receive_count = 0
    send_oserror_action_valid = False
    for index, action in enumerate(actions):
        context = f"WebSocket actions[{index}]"
        if not isinstance(action, dict):
            raise ContractError(f"{context} must be an object")
        action_kind = action.get("action")
        action_id = _string(action.get("action_id"), f"{context}.action_id")
        if action_id in action_ids:
            raise ContractError(f"duplicate WebSocket action ID: {action_id}")
        action_ids.add(action_id)
        if action_kind == "receive":
            _exact(action, {"action_id", "action"}, context)
            if client_state == "CONNECTING":
                if incoming_index >= len(incoming_types):
                    raise ContractError(
                        f"{context} has no input message while the client is connecting"
                    )
                message_type = incoming_types[incoming_index]
                incoming_index += 1
                if message_type == "websocket.connect":
                    client_state = "CONNECTED"
            elif client_state == "CONNECTED":
                if incoming_index >= len(incoming_types):
                    raise ContractError(
                        f"{context} has no input message while the client is connected"
                    )
                message_type = incoming_types[incoming_index]
                incoming_index += 1
                if message_type == "websocket.disconnect":
                    client_state = "DISCONNECTED"
            else:
                terminal_receive_count += 1
        elif action_kind == "send":
            expected = {"action_id", "action", "message"}
            if "send_error" in action:
                expected.add("send_error")
            _exact(action, expected, context)
            message_type = _validate_websocket_message(
                action["message"], f"{context}.message", incoming=False
            )
            if "send_error" in action:
                send_error = _exact(
                    action["send_error"], {"kind", "message"}, f"{context}.send_error"
                )
                if send_error["kind"] != "os-error":
                    raise ContractError(f"{context}.send_error.kind must be os-error")
                _string(send_error["message"], f"{context}.send_error.message")
                if message_type != "websocket.send" or application_state != "CONNECTED":
                    raise ContractError(
                        f"{context}.send_error requires websocket.send after accept while application_state is CONNECTED"
                    )
                send_oserror_action_valid = True
                application_state = "DISCONNECTED"
            elif application_state == "CONNECTING":
                if message_type == "websocket.accept":
                    application_state = "CONNECTED"
                elif message_type == "websocket.close":
                    application_state = "DISCONNECTED"
                elif message_type == "websocket.http.response.start":
                    application_state = "RESPONSE"
            elif application_state == "CONNECTED" and message_type == "websocket.close":
                application_state = "DISCONNECTED"
            elif (
                application_state == "RESPONSE"
                and message_type == "websocket.http.response.body"
                and not action["message"].get("more_body", False)
            ):
                application_state = "DISCONNECTED"
        else:
            raise ContractError(
                f"{context}.action is unsupported by the Rust-equivalent raw protocol surface; "
                "only receive and send are declared (accept, receive_text, receive_bytes, "
                "send_text, send_bytes, and close convenience methods are outside this contract)"
            )
    if incoming_index != len(incoming):
        raise ContractError(
            "WebSocket protocol sequence must consume every supplied incoming message exactly once"
        )
    if case["observations"] != [operation]:
        raise ContractError(
            "WebSocket observations must select their declared sequence workflow result"
        )
    requirement_prefix = (
        "starlette.websocket.protocol"
        if operation == WEBSOCKET_OPERATION
        else "starlette.websocket.state"
    )
    coverage: set[str] = set()
    action_signature = [
        (
            action["action"],
            action["message"]["type"] if action["action"] == "send" else None,
        )
        for action in actions
    ]
    if (
        incoming_types[:2] == ["websocket.connect", "websocket.receive"]
        and "text" in incoming[1]
        and action_signature[:5]
        == [
            ("receive", None),
            ("send", "websocket.accept"),
            ("receive", None),
            ("send", "websocket.send"),
            ("send", "websocket.close"),
        ]
        and "text" in actions[3]["message"]
    ):
        coverage.add(f"{requirement_prefix}.handshake-text-close")
    if incoming_types[:2] == ["websocket.connect", "websocket.disconnect"] and action_signature[
        :3
    ] == [("receive", None), ("send", "websocket.accept"), ("receive", None)]:
        coverage.add(f"{requirement_prefix}.disconnect")
    if not incoming_types and action_signature[0] == ("send", "websocket.send"):
        coverage.add(f"{requirement_prefix}.invalid-transition")
    if (
        incoming_types[:2] == ["websocket.connect", "websocket.disconnect"]
        and terminal_receive_count > 0
        and action_signature[:4]
        == [
            ("receive", None),
            ("send", "websocket.accept"),
            ("receive", None),
            ("receive", None),
        ]
    ):
        coverage.add(f"{requirement_prefix}.receive-after-disconnect")
    if (
        incoming_types[:2] == ["websocket.connect", "websocket.receive"]
        and "bytes_base64" in incoming[1]
        and any(
            action["action"] == "send"
            and action["message"]["type"] == "websocket.send"
            and "bytes_base64" in action["message"]
            for action in actions
        )
    ):
        coverage.add(f"{requirement_prefix}.binary-exchange")
    if send_oserror_action_valid and incoming_types[:1] == ["websocket.connect"]:
        coverage.add(f"{requirement_prefix}.send-oserror-disconnect")
    unexercised = set(case["covers"]) - coverage
    if unexercised:
        raise ContractError(
            f"WebSocket case claims requirements not exercised by its protocol sequence: {sorted(unexercised)}"
        )


def _validate_websocket_convenience_case_stimulus(case: dict[str, Any]) -> None:
    if case["operation"] != WEBSOCKET_CONVENIENCE_OPERATION:
        raise ContractError("WebSocket cases must use a declared sequence operation")
    _validate_websocket_scope(case["scope"])
    incoming = case["incoming"]
    actions = case["actions"]
    if not isinstance(incoming, list) or not isinstance(actions, list) or not actions:
        raise ContractError(
            "WebSocket incoming and actions must be arrays, with at least one action"
        )
    incoming_types = [
        _validate_websocket_message(message, f"WebSocket incoming[{index}]", incoming=True)
        for index, message in enumerate(incoming)
    ]
    action_ids: set[str] = set()
    incoming_index = 0
    client_state = "CONNECTING"
    application_state = "CONNECTING"
    exercised: set[str] = set()

    def receive_input(context: str, expected_payload: str | None = None) -> str:
        nonlocal incoming_index, client_state
        if client_state not in {"CONNECTING", "CONNECTED"}:
            raise ContractError(f"{context} cannot receive after websocket.disconnect")
        if incoming_index >= len(incoming_types):
            raise ContractError(f"{context} has no supplied incoming message")
        message = incoming[incoming_index]
        message_type = incoming_types[incoming_index]
        incoming_index += 1
        if client_state == "CONNECTING":
            if message_type != "websocket.connect":
                raise ContractError(f"{context} must first receive websocket.connect")
            client_state = "CONNECTED"
            return message_type
        if message_type == "websocket.disconnect":
            client_state = "DISCONNECTED"
            exercised.add("starlette.websocket.api.disconnect.details")
            return message_type
        if message_type != "websocket.receive":
            raise ContractError(f"{context} requires websocket.receive or websocket.disconnect")
        if expected_payload is not None and expected_payload not in message:
            raise ContractError(f"{context} requires incoming payload field {expected_payload!r}")
        return message_type

    for index, action in enumerate(actions):
        context = f"WebSocket convenience actions[{index}]"
        if not isinstance(action, dict):
            raise ContractError(f"{context} must be an object")
        action_keys = {"action_id", "method", "arguments"}
        if "send_error" in action:
            action_keys.add("send_error")
        _exact(action, action_keys, context)
        action_id = _string(action["action_id"], f"{context}.action_id")
        method = _string(action["method"], f"{context}.method")
        if action_id in action_ids:
            raise ContractError(f"duplicate WebSocket action ID: {action_id}")
        action_ids.add(action_id)
        arguments = action["arguments"]
        if not isinstance(arguments, dict):
            raise ContractError(f"{context}.arguments must be an object")
        if "send_error" in action:
            send_error = _exact(action["send_error"], {"kind", "message"}, f"{context}.send_error")
            if send_error["kind"] != "os-error":
                raise ContractError(f"{context}.send_error.kind must be os-error")
            _string(send_error["message"], f"{context}.send_error.message")
            if method not in {"send_text", "send_bytes", "send_json", "close"}:
                raise ContractError(f"{context}.send_error requires a send convenience method")

        if method == "accept":
            _exact_keys = {"subprotocol", "headers_base64_pairs"}
            if set(arguments) - _exact_keys:
                raise ContractError(f"{context}.arguments has fields unsupported by accept")
            if "subprotocol" in arguments and arguments["subprotocol"] is not None:
                _string(arguments["subprotocol"], f"{context}.arguments.subprotocol")
            if "headers_base64_pairs" in arguments:
                headers = arguments["headers_base64_pairs"]
                if headers is not None:
                    if not isinstance(headers, list):
                        raise ContractError(
                            f"{context}.arguments.headers_base64_pairs must be an array or null"
                        )
                    for pair in headers:
                        if not isinstance(pair, list) or len(pair) != 2:
                            raise ContractError(
                                f"{context}.arguments header must be a two-item array"
                            )
                        for value in pair:
                            try:
                                base64.b64decode(value, validate=True)
                            except (ValueError, TypeError) as exc:
                                raise ContractError(
                                    f"{context}.arguments header contains invalid base64"
                                ) from exc
            if application_state != "CONNECTING":
                raise ContractError(f"{context} requires the application to be connecting")
            if client_state == "CONNECTING":
                receive_input(context)
            if client_state != "CONNECTED":
                raise ContractError(f"{context} cannot accept after client disconnect")
            application_state = "CONNECTED"
            headers = arguments.get("headers_base64_pairs")
            if headers:
                exercised.add("starlette.websocket.api.accept.headers")
            else:
                exercised.add("starlette.websocket.api.accept.empty-headers")
        elif method in {"receive_text", "receive_bytes", "receive_json"}:
            if method == "receive_json":
                _exact_keys = {"mode"}
                if set(arguments) - _exact_keys:
                    raise ContractError(
                        f"{context}.arguments has fields unsupported by receive_json"
                    )
                mode = arguments.get("mode", "text")
                mode = _string(mode, f"{context}.arguments.mode")
                if mode not in {"text", "binary"}:
                    raise ContractError(f"{context}.arguments.mode must be text or binary")
                payload = "text" if mode == "text" else "bytes_base64"
                exercised.add(f"starlette.websocket.api.receive.json.{mode}")
            else:
                if arguments:
                    raise ContractError(f"{context}.arguments must be empty for {method}")
                mode = None
                payload = "text" if method == "receive_text" else "bytes_base64"
                exercised.add(
                    "starlette.websocket.api.receive.text"
                    if method == "receive_text"
                    else "starlette.websocket.api.receive.bytes"
                )
            if application_state != "CONNECTED":
                raise ContractError(f"{context} requires a connected WebSocket")
            message_type = receive_input(context, payload)
            if message_type == "websocket.disconnect":
                exercised.add("starlette.websocket.api.disconnect.details")
        elif method in {"iter_text", "iter_bytes", "iter_json"}:
            if arguments:
                raise ContractError(f"{context}.arguments must be empty for {method}")
            if application_state != "CONNECTED":
                raise ContractError(f"{context} requires a connected WebSocket")
            payload = "bytes_base64" if method == "iter_bytes" else "text"
            iterated = False
            while True:
                message_type = receive_input(context, payload)
                if message_type == "websocket.disconnect":
                    break
                iterated = True
            if not iterated:
                raise ContractError(f"{context} must yield at least one incoming message")
            exercised.add(f"starlette.websocket.api.{method}.async-for")
        elif method in {"send_text", "send_bytes", "send_json", "close"}:
            if method == "send_text":
                _exact(arguments, {"data"}, f"{context}.arguments")
                if not isinstance(arguments["data"], str):
                    raise ContractError(f"{context}.arguments.data must be a string")
                exercised.add("starlette.websocket.api.send.text")
            elif method == "send_bytes":
                _exact(arguments, {"data_base64"}, f"{context}.arguments")
                try:
                    base64.b64decode(arguments["data_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{context}.arguments.data_base64 is invalid") from exc
                exercised.add("starlette.websocket.api.send.bytes")
            elif method == "send_json":
                if set(arguments) not in ({"data"}, {"data", "mode"}):
                    raise ContractError(f"{context}.arguments must contain data and optional mode")
                mode = arguments.get("mode", "text")
                mode = _string(mode, f"{context}.arguments.mode")
                if mode not in {"text", "binary"}:
                    raise ContractError(f"{context}.arguments.mode must be text or binary")
                exercised.add(f"starlette.websocket.api.send.json.{mode}")
            else:
                if set(arguments) - {"code", "reason"}:
                    raise ContractError(f"{context}.arguments has fields unsupported by close")
                code = arguments.get("code", 1000)
                reason = arguments.get("reason")
                if not isinstance(code, int) or isinstance(code, bool):
                    raise ContractError(f"{context}.arguments.code must be an integer")
                if reason is not None and not isinstance(reason, str):
                    raise ContractError(f"{context}.arguments.reason must be a string or null")
                exercised.add("starlette.websocket.api.close.framing")
            if application_state != "CONNECTED":
                raise ContractError(f"{context} requires a connected WebSocket")
            if method == "close":
                application_state = "DISCONNECTED"
        elif method == "send_denial_response":
            _exact(arguments, {"response"}, f"{context}.arguments")
            response = _exact(
                arguments["response"],
                {"status_code", "content_base64", "headers_base64_pairs"},
                f"{context}.arguments.response",
            )
            if not isinstance(response["status_code"], int) or isinstance(
                response["status_code"], bool
            ):
                raise ContractError(f"{context}.arguments.response.status_code must be an integer")
            try:
                base64.b64decode(response["content_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError(
                    f"{context}.arguments.response.content_base64 is invalid"
                ) from exc
            if not isinstance(response["headers_base64_pairs"], list):
                raise ContractError(
                    f"{context}.arguments.response.headers_base64_pairs must be an array"
                )
            for pair in response["headers_base64_pairs"]:
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ContractError(
                        f"{context}.arguments.response header must be a two-item array"
                    )
                for value in pair:
                    try:
                        base64.b64decode(value, validate=True)
                    except (ValueError, TypeError) as exc:
                        raise ContractError(
                            f"{context}.arguments.response header contains invalid base64"
                        ) from exc
            extension_present = "websocket.http.response" in case["scope"].get("extensions", {})
            if application_state != "CONNECTING":
                raise ContractError(
                    f"{context} requires the application to be connecting for denial response"
                )
            if extension_present:
                application_state = "DISCONNECTED"
                exercised.add("starlette.websocket.api.denial-response.present")
            else:
                exercised.add("starlette.websocket.api.denial-response.absent")
        elif method == "iterator-probe":
            _exact(arguments, {"iterator", "attributes"}, f"{context}.arguments")
            iterator_method = _string(arguments["iterator"], f"{context}.arguments.iterator")
            if iterator_method not in {"iter_text", "iter_bytes", "iter_json"}:
                raise ContractError(f"{context}.arguments.iterator is not a declared iterator")
            attributes = arguments["attributes"]
            if (
                not isinstance(attributes, list)
                or any(not isinstance(item, str) or not item for item in attributes)
                or len(attributes) != len(set(attributes))
            ):
                raise ContractError(f"{context}.arguments.attributes must be unique strings")
            if {"asend", "athrow", "aclose"} <= set(attributes):
                exercised.add("starlette.websocket.api.iterator.protocol.surface")
        elif method == "iterator-control":
            control = arguments.get("control") if isinstance(arguments, dict) else None
            expected = (
                {"iterator", "control", "value"}
                if control == "asend"
                else {"iterator", "control", "exception"}
                if control == "athrow"
                else {"iterator", "control"}
                if control == "aclose"
                else set()
            )
            if not expected:
                raise ContractError(f"{context}.arguments.control must be asend, athrow, or aclose")
            _exact(arguments, expected, f"{context}.arguments")
            iterator_method = _string(arguments["iterator"], f"{context}.arguments.iterator")
            if iterator_method not in {"iter_text", "iter_bytes", "iter_json"}:
                raise ContractError(f"{context}.arguments.iterator is not a declared iterator")
            if control == "asend":
                if arguments["value"] is not None:
                    raise ContractError(f"{context}.arguments.value must be null for asend")
                if application_state != "CONNECTED":
                    raise ContractError(f"{context} asend requires a connected WebSocket")
                payload = "bytes_base64" if arguments["iterator"] == "iter_bytes" else "text"
                message_type = receive_input(context, payload)
                if message_type == "websocket.disconnect":
                    raise ContractError(f"{context} asend stimulus must include a yielded message")
            elif control == "athrow":
                exception = _exact(
                    arguments["exception"], {"class", "message"}, f"{context}.arguments.exception"
                )
                exception_class = _string(
                    exception["class"], f"{context}.arguments.exception.class"
                )
                if exception_class not in {
                    "Exception",
                    "RuntimeError",
                    "ValueError",
                    "TypeError",
                    "LookupError",
                    "KeyError",
                }:
                    raise ContractError(
                        f"{context}.arguments.exception.class is outside the exception input vocabulary"
                    )
                _string(exception["message"], f"{context}.arguments.exception.message")
            exercised.add(f"starlette.websocket.api.iterator.{control}")
        else:
            raise ContractError(f"{context}.method is unsupported: {method!r}")

    if incoming_index != len(incoming_types):
        raise ContractError(
            "WebSocket convenience sequence must consume every supplied incoming message exactly once"
        )
    if case["observations"] != [WEBSOCKET_CONVENIENCE_OPERATION]:
        raise ContractError(
            "WebSocket observations must select the convenience-sequence workflow result"
        )
    unexercised = set(case["covers"]) - exercised
    if unexercised:
        raise ContractError(
            "WebSocket case claims requirements not exercised by its convenience sequence: "
            f"{sorted(unexercised)}"
        )


def _validate_websocket_close_case_stimulus(case: dict[str, Any]) -> None:
    if case["operation"] != WEBSOCKET_CLOSE_OPERATION:
        raise ContractError("WebSocketClose cases must use the declared call-sequence operation")
    _validate_websocket_scope(case["scope"])
    close_app = _exact(case["close_app"], {"arguments", "setters"}, "WebSocketClose input")
    arguments = close_app["arguments"]
    if not isinstance(arguments, dict) or set(arguments) - {"code", "reason"}:
        raise ContractError("WebSocketClose arguments may provide only code and reason")
    if "code" in arguments and (
        not isinstance(arguments["code"], int) or isinstance(arguments["code"], bool)
    ):
        raise ContractError("WebSocketClose code must be an integer")
    if (
        "reason" in arguments
        and arguments["reason"] is not None
        and not isinstance(arguments["reason"], str)
    ):
        raise ContractError("WebSocketClose reason must be a string or null")
    setters = close_app["setters"]
    if not isinstance(setters, dict) or set(setters) - {"code", "reason"}:
        raise ContractError("WebSocketClose setters may assign only code and reason")
    if "code" in setters and (
        not isinstance(setters["code"], int) or isinstance(setters["code"], bool)
    ):
        raise ContractError("WebSocketClose setter code must be an integer")
    if (
        "reason" in setters
        and setters["reason"] is not None
        and not isinstance(setters["reason"], str)
    ):
        raise ContractError("WebSocketClose setter reason must be a string or null")
    if case["observations"] != [WEBSOCKET_CLOSE_OPERATION]:
        raise ContractError("WebSocketClose observations must select the call-sequence result")
    exercised = {"starlette.websocket.close-app.framing-attributes"}
    if not arguments:
        exercised.add("starlette.websocket.close-app.default-attributes")
    if arguments.get("reason") is None:
        exercised.add("starlette.websocket.close-app.reason-normalization")
    if setters:
        exercised.add("starlette.websocket.close-app.attribute-assignment")
    unexercised = set(case["covers"]) - exercised
    if unexercised:
        raise ContractError(
            "WebSocketClose case claims requirements not exercised by its input: "
            f"{sorted(unexercised)}"
        )


def _validate_websocket_route_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise ContractError("WebSocketRoute scope must be an object")
    if scope.get("type") == "websocket":
        _validate_websocket_scope(scope)
        return
    scope = _exact(
        scope,
        {
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        },
        "WebSocketRoute HTTP scope",
    )
    if scope["type"] != "http":
        raise ContractError("WebSocketRoute scope.type must be websocket or http")
    asgi = _exact(scope["asgi"], {"version", "spec_version"}, "WebSocketRoute HTTP scope.asgi")
    if asgi != {"version": "3.0", "spec_version": "2.4"}:
        raise ContractError("WebSocketRoute HTTP scope must use ASGI 3.0 with spec version 2.4")
    _string(scope["http_version"], "WebSocketRoute HTTP scope.http_version")
    if scope["method"] != "GET" or scope["scheme"] != "http":
        raise ContractError("WebSocketRoute HTTP mismatch scope must be GET over http")
    path = _string(scope["path"], "WebSocketRoute HTTP scope.path")
    if scope["raw_path_base64"] != base64.b64encode(path.encode("ascii")).decode("ascii"):
        raise ContractError("WebSocketRoute HTTP raw_path bytes must match the ASCII path")
    if not isinstance(scope["root_path"], str):
        raise ContractError("WebSocketRoute HTTP scope.root_path must be a string")
    for key in ("raw_path_base64", "query_string_base64"):
        try:
            base64.b64decode(scope[key], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"WebSocketRoute HTTP scope.{key} is invalid base64") from exc
    headers = scope["headers_base64_pairs"]
    if not isinstance(headers, list):
        raise ContractError("WebSocketRoute HTTP scope.headers_base64_pairs must be an array")
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ContractError("each WebSocketRoute HTTP header must be a two-item array")
        for value in pair:
            try:
                base64.b64decode(value, validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError("WebSocketRoute HTTP header contains invalid base64") from exc
    for name in ("client", "server"):
        address = scope[name]
        if (
            not isinstance(address, list)
            or len(address) != 2
            or not isinstance(address[0], str)
            or not isinstance(address[1], int)
            or isinstance(address[1], bool)
        ):
            raise ContractError(f"WebSocketRoute HTTP scope.{name} must be [host, port]")


def _validate_websocket_route_case_stimulus(case: dict[str, Any]) -> None:
    if case["dispatch"] not in {"application", "standalone-route"}:
        raise ContractError("WebSocketRoute dispatch must be application or standalone-route")
    route = _exact(case["route"], {"path"}, "WebSocketRoute route input")
    if route["path"] != "/rooms/{room:str}":
        raise ContractError("WebSocketRoute route input must define /rooms/{room:str}")
    _validate_websocket_route_scope(case["scope"])
    incoming = case["incoming"]
    actions = case["endpoint_actions"]
    if not isinstance(incoming, list) or not isinstance(actions, list):
        raise ContractError("WebSocketRoute incoming and endpoint_actions must be arrays")
    for index, message in enumerate(incoming):
        _validate_websocket_message(message, f"WebSocketRoute incoming[{index}]", incoming=True)
    for index, action in enumerate(actions):
        context = f"WebSocketRoute endpoint_actions[{index}]"
        if not isinstance(action, dict) or not isinstance(action.get("action"), str):
            raise ContractError(f"{context} must declare an action")
        if action["action"] == "accept":
            _exact(action, {"action", "subprotocol"}, context)
            if action["subprotocol"] is not None:
                _string(action["subprotocol"], f"{context}.subprotocol")
        elif action["action"] == "send_text":
            _exact(action, {"action", "text"}, context)
            _string(action["text"], f"{context}.text")
        elif action["action"] == "close":
            _exact(action, {"action", "code", "reason"}, context)
            if type(action["code"]) is not int or action["code"] < 0:
                raise ContractError(f"{context}.code must be a non-negative integer")
            _string(action["reason"], f"{context}.reason")
        else:
            raise ContractError(f"{context}.action is unsupported")
    if case["observations"] != list(WEBSOCKET_ROUTE_OBSERVATIONS):
        raise ContractError(
            "WebSocketRoute observations must select the route-dispatch workflow result"
        )

    scope = case["scope"]
    expected_route = route["path"]
    coverage: set[str] = set()
    if (
        case["dispatch"] == "application"
        and scope["type"] == "websocket"
        and scope["root_path"] == "/edge"
        and scope["path"] == "/edge/rooms/blue"
        and expected_route == "/rooms/{room:str}"
        and [message["type"] for message in incoming] == ["websocket.connect"]
        and [action["action"] for action in actions] == ["accept", "send_text", "close"]
    ):
        coverage.add("starlette.routing.WebSocketRoute.route-dispatch.matched-root-path")
    if (
        case["dispatch"] == "application"
        and scope["type"] == "websocket"
        and scope["root_path"] == ""
        and scope["path"] == "/missing"
        and not incoming
        and not actions
    ):
        coverage.add("starlette.routing.WebSocketRoute.route-dispatch.router-miss-close")
    if (
        case["dispatch"] == "standalone-route"
        and scope["type"] == "http"
        and scope["path"] == "/rooms/blue"
        and not incoming
        and not actions
    ):
        coverage.add("starlette.routing.WebSocketRoute.route-dispatch.http-scope-404")
    unexercised = set(case["covers"]) - coverage
    if unexercised:
        raise ContractError(
            "WebSocketRoute case claims requirements not exercised by its dispatch inputs: "
            f"{sorted(unexercised)}"
        )


def _route_template_capture(
    template: str,
    path: str,
    custom: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str] | None:
    """Recognize the pinned route converter grammar for input mapping only."""
    custom = custom or {}
    parameter = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?\}")
    fragments: list[str] = []
    names: list[str] = []
    offset = 0
    for match in parameter.finditer(template):
        name, converter = match.groups()
        converter = converter or "str"
        fragments.append(re.escape(template[offset : match.start()]))
        if converter in custom:
            expression = custom[converter]["regex"]
            fragments.append(f"(?P<{name}>(?:{expression}))")
            names.append(name)
            offset = match.end()
            continue
        if converter == "str":
            fragments.append("[^/]+")
        elif converter == "int":
            fragments.append("[0-9]+")
        elif converter == "float":
            fragments.append(r"[0-9]+(?:\.[0-9]+)?")
        elif converter == "uuid":
            fragments.append(
                r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?"
                r"[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"
            )
        elif converter == "path":
            fragments.append(".*")
        else:
            return None
        fragments[-1] = f"(?P<{name}>{fragments[-1]})"
        names.append(name)
        offset = match.end()
    if "{" in template[offset:] or "}" in template[offset:]:
        return None
    fragments.append(re.escape(template[offset:]))
    try:
        matched = re.fullmatch("".join(fragments), path)
    except re.error as exc:
        raise ContractError(f"route converter expression is invalid: {exc}") from exc
    if matched is None:
        return None
    return {name: matched.group(name) for name in names}


def _route_template_matches(
    template: str,
    path: str,
    custom: dict[str, dict[str, Any]] | None = None,
) -> bool:
    return _route_template_capture(template, path, custom) is not None


def _route_template_parameters(template: str) -> list[tuple[str, str]]:
    parameter = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?\}")
    return [(name, converter or "str") for name, converter in parameter.findall(template)]


def _route_path_after_root(path: str, root_path: str) -> str:
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path) :]
    return path


def _validate_http_route_input(
    route: Any, context: str, custom_convertors: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    route = _exact(route, {"kind", "path", "methods", "endpoint"}, context)
    if (
        route["kind"] != "http-route"
        or not isinstance(route["path"], str)
        or not route["path"].startswith("/")
    ):
        raise ContractError(f"{context} must define an absolute HTTP route path")
    methods = route["methods"]
    if (
        not isinstance(methods, list)
        or not methods
        or any(not isinstance(method, str) or not method for method in methods)
        or len(methods) != len(set(methods))
    ):
        raise ContractError(f"{context}.methods must be a non-empty unique string list")
    path_parameters = _route_template_parameters(route["path"])
    parameter_names = [name for name, _converter in path_parameters]
    if len(parameter_names) != len(set(parameter_names)):
        raise ContractError(f"{context}.path must not repeat a path parameter name")
    supported_convertors = {"str", "int", "float", "uuid", "path"} | set(custom_convertors or {})
    unsupported_convertors = sorted(
        converter for _name, converter in path_parameters if converter not in supported_convertors
    )
    if unsupported_convertors:
        raise ContractError(f"{context}.path uses undeclared convertors: {unsupported_convertors}")
    endpoint = route["endpoint"]
    if not isinstance(endpoint, dict) or not isinstance(endpoint.get("kind"), str):
        raise ContractError(f"{context}.endpoint must define a supported route response")
    if endpoint["kind"] == "plain-text-response":
        endpoint = _exact(
            endpoint,
            {"kind", "content", "status_code", "media_type", "cookies"},
            f"{context}.endpoint",
        )
        if (
            not isinstance(endpoint["content"], str)
            or type(endpoint["status_code"]) is not int
            or endpoint["status_code"] != 200
            or endpoint["media_type"] != "text/plain"
            or endpoint["cookies"] != []
        ):
            raise ContractError(
                f"{context}.endpoint must use the declared fixed plain-text response input"
            )
    elif endpoint["kind"] == "converted-path-response":
        endpoint = _exact(
            endpoint,
            {"kind", "path_parameter", "status_code", "media_type"},
            f"{context}.endpoint",
        )
        path_parameter_map = dict(path_parameters)
        path_parameter = _string(endpoint["path_parameter"], f"{context}.endpoint.path_parameter")
        if path_parameter not in path_parameter_map or path_parameter_map[path_parameter] not in (
            custom_convertors or {}
        ):
            raise ContractError(
                f"{context}.endpoint must observe a registered custom-convertor path parameter"
            )
        if type(endpoint["status_code"]) is not int or endpoint["status_code"] != 200:
            raise ContractError(f"{context}.endpoint.status_code must be 200")
        if endpoint["media_type"] != "text/plain":
            raise ContractError(f"{context}.endpoint.media_type must be text/plain")
    else:
        raise ContractError(f"{context}.endpoint kind is unsupported")
    return route


def _validate_host_route_input(route: Any, context: str) -> dict[str, Any]:
    route = _exact(route, {"kind", "host", "name", "app"}, context)
    host = _string(route["host"], f"{context}.host")
    if not host or "/" in host:
        raise ContractError(f"{context}.host must be a non-empty host pattern")
    if route["name"] is not None:
        _string(route["name"], f"{context}.name")
    parameters = _route_template_parameters(host)
    if len({name for name, _converter in parameters}) != len(parameters):
        raise ContractError(f"{context}.host must not repeat a parameter name")
    unsupported = sorted(
        converter
        for _name, converter in parameters
        if converter not in {"str", "int", "float", "uuid", "path"}
    )
    if unsupported:
        raise ContractError(f"{context}.host uses undeclared convertors: {unsupported}")
    app = _exact(
        route["app"],
        {"kind", "content", "status_code", "media_type", "cookies"},
        f"{context}.app",
    )
    if (
        app["kind"] != "plain-text-response"
        or not isinstance(app["content"], str)
        or type(app["status_code"]) is not int
        or app["status_code"] != 200
        or app["media_type"] != "text/plain"
        or app["cookies"] != []
    ):
        raise ContractError(f"{context}.app must use the fixed plain-text response input")
    return route


def _validate_router_route_input(
    route: Any,
    context: str,
    custom_convertors: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(route, dict) and route.get("kind") == "host-route":
        return _validate_host_route_input(route, context)
    return _validate_http_route_input(route, context, custom_convertors)


def _validate_route_dispatch_io(
    case: dict[str, Any],
    *,
    allow_query: bool = False,
    allow_headers: bool = False,
    allow_host: bool = False,
    allow_inherited_mount_scope: bool = False,
) -> None:
    if case["scope"].get("type") != "http" or (
        not allow_query and case["scope"].get("query_string_base64") != ""
    ):
        raise ContractError(
            "route-dispatch cases require a direct HTTP scope without a query string"
        )
    if not allow_headers and case["scope"].get("headers_base64_pairs") != []:
        raise ContractError("route-dispatch cases do not declare request headers")
    if case["incoming"] != [] or case["send"] != {"kind": "capture-asgi-send"}:
        raise ContractError(
            "route-dispatch cases use an empty receive stream and captured ASGI send"
        )
    _validate_dispatch_stimulus(
        {"scope": case["scope"], "receive": case["incoming"], "send": case["send"]},
        request_dispatch=True,
        allow_root_path=True,
        allow_host=allow_host,
        allow_inherited_mount_scope=allow_inherited_mount_scope,
    )


def _validate_redirect_response_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, REDIRECT_RESPONSE_CASE_KEYS, "RedirectResponse asgi-call case")
    if (
        case["surface"] != REDIRECT_RESPONSE_SURFACE
        or case["operation"] != REDIRECT_RESPONSE_OPERATION
    ):
        raise ContractError("case is outside the declared RedirectResponse asgi-call operation")
    if case["observations"] != [REDIRECT_RESPONSE_OPERATION]:
        raise ContractError("RedirectResponse observations must select asgi-call")
    _string(case["url"], "RedirectResponse.url")
    if type(case["status_code"]) is not int or not 300 <= case["status_code"] <= 399:
        raise ContractError("RedirectResponse.status_code must be an integer redirect status")
    headers = case["header_pairs"]
    if not isinstance(headers, list):
        raise ContractError("RedirectResponse.header_pairs must be an ordered array")
    seen_names: set[str] = set()
    for index, pair in enumerate(headers):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(value, str) for value in pair)
            or not pair[0]
        ):
            raise ContractError(
                f"RedirectResponse.header_pairs[{index}] must be a non-empty name and string value"
            )
        name, value = pair
        try:
            name.encode("latin-1")
            value.encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ContractError(
                f"RedirectResponse.header_pairs[{index}] must be Latin-1 encodable"
            ) from exc
        normalized_name = name.lower()
        if normalized_name in seen_names:
            raise ContractError(
                "RedirectResponse header input must map unique case-insensitive names"
            )
        seen_names.add(normalized_name)
    if case["incoming"] != []:
        raise ContractError("RedirectResponse asgi-call inputs use an empty receive stream")
    _validate_dispatch_stimulus(
        {"scope": case["scope"], "receive": case["incoming"], "send": case["send"]},
        request_dispatch=True,
        allow_root_path=True,
        allow_query=True,
        allow_headers=True,
    )


def _validate_response_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, RESPONSE_CASE_KEYS, "Response asgi-call case")
    if case["surface"] not in RESPONSE_SURFACES or case["operation"] != RESPONSE_OPERATION:
        raise ContractError("case is outside the declared Response asgi-call operations")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ContractError("Response observations must select asgi-call")
    if type(case["status_code"]) is not int or case["status_code"] not in {200, 204}:
        raise ContractError("Response status_code must be 200 or 204 for this input slice")
    if case["header_pairs"] != []:
        raise ContractError("Response header_pairs must be empty for this input slice")
    if case["media_type"] is not None and not isinstance(case["media_type"], str):
        raise ContractError("Response media_type must be a string or null")

    content = _exact(case["content"], {"kind", "value"}, "Response content")
    content_kind = _string(content["kind"], "Response content.kind")
    if case["surface"] == RESPONSE_SURFACE:
        if content_kind == "text":
            value = _string(content["value"], "Response text content.value")
            allowed = {
                ("hi", 200, None),
                ("hi", 200, "text/html"),
                ("hello, world", 200, "text/plain"),
            }
            if (value, case["status_code"], case["media_type"]) not in allowed:
                raise ContractError(
                    "Response text, status_code, and media_type combination is unsupported"
                )
        elif content_kind == "base64-bytes":
            encoded = _string(content["value"], "Response bytes content.value")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError("Response bytes content.value must be valid base64") from exc
            if (
                decoded != b"xxxxx"
                or case["status_code"] != 200
                or case["media_type"] != "image/png"
            ):
                raise ContractError(
                    "Response bytes, status_code, and media_type combination is unsupported"
                )
        elif content_kind == "none":
            if content["value"] is not None:
                raise ContractError("Response none content.value must be null")
            if (case["status_code"], case["media_type"]) not in {
                (200, None),
                (200, "text/plain; charset=utf-8"),
                (204, None),
            }:
                raise ContractError(
                    "Response none, status_code, and media_type combination is unsupported"
                )
        else:
            raise ContractError("Response content.kind must be none, text, or base64-bytes")
    else:
        if content_kind != "json" or content["value"] is not None:
            raise ContractError("JSONResponse content must be json null for this input slice")
        if case["status_code"] != 200 or case["media_type"] is not None:
            raise ContractError(
                "JSONResponse status_code and media_type are fixed for this input slice"
            )
    if case["incoming"] != [] or case["send"] != {"kind": "capture-asgi-send"}:
        raise ContractError("Response asgi-call inputs use empty receive and captured send")
    _validate_dispatch_stimulus(
        {"scope": case["scope"], "receive": case["incoming"], "send": case["send"]},
        request_dispatch=True,
    )


def _validate_file_response_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, FILE_RESPONSE_CASE_KEYS, "FileResponse asgi-call case")
    if case["surface"] != FILE_RESPONSE_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ContractError("case is outside the declared FileResponse asgi-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ContractError("FileResponse observations must select asgi-call")

    file_input = _exact(
        case["file"],
        {"name", "contents_base64", "mtime_seconds"},
        "FileResponse file input",
    )
    name = _string(file_input["name"], "FileResponse file.name")
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ContractError("FileResponse file.name must be a basename")
    contents_base64 = _string(file_input["contents_base64"], "FileResponse file.contents_base64")
    try:
        base64.b64decode(contents_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ContractError("FileResponse file.contents_base64 must be valid base64") from exc
    mtime_seconds = file_input["mtime_seconds"]
    if type(mtime_seconds) not in {int, float} or not math.isfinite(mtime_seconds):
        raise ContractError("FileResponse file.mtime_seconds must be a finite number")

    status_code = case["status_code"]
    if type(status_code) is not int or not 100 <= status_code <= 599:
        raise ContractError("FileResponse status_code must be an HTTP status code")
    headers = case["header_pairs"]
    if not isinstance(headers, list):
        raise ContractError("FileResponse.header_pairs must be an ordered array")
    seen_names: set[str] = set()
    for index, pair in enumerate(headers):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(value, str) for value in pair)
            or not pair[0]
        ):
            raise ContractError(
                f"FileResponse.header_pairs[{index}] must be a non-empty name and string value"
            )
        try:
            pair[0].encode("latin-1")
            pair[1].encode("latin-1")
        except UnicodeEncodeError as exc:
            raise ContractError(
                f"FileResponse.header_pairs[{index}] must be Latin-1 encodable"
            ) from exc
        normalized_name = pair[0].lower()
        if normalized_name in seen_names:
            raise ContractError("FileResponse header input must map unique case-insensitive names")
        seen_names.add(normalized_name)
    if case["media_type"] is not None:
        _string(case["media_type"], "FileResponse.media_type")
    if case["filename"] is not None:
        _string(case["filename"], "FileResponse.filename")

    scope_spec = case["scope"]
    scope_keys = {
        "type",
        "asgi",
        "http_version",
        "method",
        "scheme",
        "path",
        "raw_path_base64",
        "query_string_base64",
        "root_path",
        "headers_base64_pairs",
        "client",
        "server",
    }
    if isinstance(scope_spec, dict) and "extensions" in scope_spec:
        scope_keys.add("extensions")
    scope_spec = _exact(scope_spec, scope_keys, "FileResponse HTTP scope")
    if scope_spec["type"] != "http":
        raise ContractError("FileResponse ASGI-call requires an HTTP scope")
    if "extensions" in scope_spec:
        extensions = scope_spec["extensions"]
        if not isinstance(extensions, dict) or any(
            key != "http.response.pathsend" for key in extensions
        ):
            raise ContractError(
                "FileResponse scope.extensions may only declare http.response.pathsend"
            )
    if case["incoming"] != [] or case["send"] != {"kind": "capture-asgi-send"}:
        raise ContractError("FileResponse asgi-call requires empty receive and captured send")
    dispatch_scope = {key: value for key, value in scope_spec.items() if key != "extensions"}
    _validate_dispatch_stimulus(
        {"scope": dispatch_scope, "receive": case["incoming"], "send": case["send"]},
        request_dispatch=True,
        allow_headers=True,
    )


def _validate_streaming_response_case_stimulus(case: dict[str, Any]) -> None:
    case_keys = STREAMING_RESPONSE_CASE_KEYS | ({"background"} if "background" in case else set())
    _exact(case, case_keys, "StreamingResponse asgi-call case")
    if case["surface"] != STREAMING_RESPONSE_SURFACE or case["operation"] not in {
        STREAMING_RESPONSE_OPERATION,
        STREAMING_RESPONSE_TRACE_OPERATION,
    }:
        raise ContractError("case is outside the declared StreamingResponse asgi-call operation")
    if case["observations"] != [STREAMING_RESPONSE_OPERATION]:
        raise ContractError("StreamingResponse observations must select asgi-call")
    if type(case["status_code"]) is not int or case["status_code"] != 200:
        raise ContractError("StreamingResponse status_code must be 200 for this input slice")
    if case["streaming"] not in {"sync", "async-iterator", "async-generator"}:
        raise ContractError("StreamingResponse streaming must select a declared iterator mode")

    content = _exact(case["content"], {"kind", "value"}, "StreamingResponse content")
    if content["kind"] != "chunks" or not isinstance(content["value"], list):
        raise ContractError("StreamingResponse content must contain an array of chunks")
    chunks: list[tuple[str, str]] = []
    for index, chunk in enumerate(content["value"]):
        chunk = _exact(chunk, {"kind", "value"}, f"StreamingResponse content[{index}]")
        if not isinstance(chunk["kind"], str) or chunk["kind"] not in {
            "text",
            "base64-bytes",
        }:
            raise ContractError("StreamingResponse chunks must be text or base64 bytes")
        value = _string(chunk["value"], f"StreamingResponse content[{index}].value")
        chunks.append((chunk["kind"], value))

    headers = case["header_pairs"]
    if not isinstance(headers, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(value, str) for value in pair)
        for pair in headers
    ):
        raise ContractError("StreamingResponse.header_pairs must be ordered string pairs")
    media_type = case["media_type"]
    if media_type is not None and not isinstance(media_type, str):
        raise ContractError("StreamingResponse.media_type must be a string or null")

    background = case.get("background")
    if background is not None:
        background = _exact(
            background,
            {"kind", "values"},
            "StreamingResponse background recorder",
        )
        if background["kind"] != "async-values-recorder":
            raise ContractError("StreamingResponse background kind is unsupported")
        if (
            not isinstance(background["values"], list)
            or not background["values"]
            or any(not isinstance(value, str) for value in background["values"])
        ):
            raise ContractError("StreamingResponse background values must be non-empty strings")

    stimulus = (tuple(chunks), tuple(tuple(pair) for pair in headers), media_type)
    allowed_sync = {
        ((("text", "hello"), ("text", "world")), (), None),
        ((("text", "hello"), ("text", "world")), (("content-length", "10"),), None),
        (
            (
                ("text", "1"),
                ("text", ", "),
                ("text", "2"),
                ("text", ", "),
                ("text", "3"),
                ("text", ", "),
                ("text", "4"),
                ("text", ", "),
                ("text", "5"),
            ),
            (),
            "text/plain",
        ),
        ((("base64-bytes", "AP8B"),), (), None),
    }
    async_iterator_stimulus = (
        (
            ("text", "1"),
            ("text", "2"),
            ("text", "3"),
            ("text", "4"),
            ("text", "5"),
        ),
        (),
        "text/plain",
    )
    async_generator_stimulus = (
        (
            ("text", "1"),
            ("text", ", "),
            ("text", "2"),
            ("text", ", "),
            ("text", "3"),
            ("text", ", "),
            ("text", "4"),
            ("text", ", "),
            ("text", "5"),
        ),
        (),
        "text/plain",
    )
    if case["streaming"] == "sync":
        if stimulus not in allowed_sync or background is not None:
            raise ContractError("StreamingResponse chunks and headers are outside this input slice")
    elif case["streaming"] == "async-iterator":
        if (
            stimulus != async_iterator_stimulus
            or background is not None
            or case["target_profiles"] != ["python-package-cpython312"]
        ):
            raise ContractError(
                "StreamingResponse async-iterator input is limited to its declared Python-package case"
            )
    elif (
        stimulus != async_generator_stimulus
        or background is None
        or case["operation"] != STREAMING_RESPONSE_TRACE_OPERATION
        or case["target_profiles"] != ["python-package-cpython312"]
    ):
        raise ContractError(
            "StreamingResponse async-generator/background input is limited to its declared Python-package case"
        )
    if case["streaming"] != "async-generator" and case["operation"] != STREAMING_RESPONSE_OPERATION:
        raise ContractError(
            "StreamingResponse execution-trace operation requires an async generator"
        )
    send = case["send"]
    send_raises_oserror = isinstance(send, dict) and send.get("kind") == (
        "capture-asgi-send-until-oserror"
    )
    if case["incoming"] != [] or (
        send != {"kind": "capture-asgi-send"} and not send_raises_oserror
    ):
        raise ContractError("StreamingResponse asgi-call uses empty receive and a declared send")
    if send_raises_oserror:
        send = _exact(
            send,
            {"kind", "event_index", "message"},
            "StreamingResponse failing send",
        )
        if (
            send["kind"] != "capture-asgi-send-until-oserror"
            or case["streaming"] != "sync"
            or type(send["event_index"]) is not int
            or send["event_index"] < 0
            or send["event_index"] >= len(chunks) + 2
            or not isinstance(send["message"], str)
        ):
            raise ContractError("StreamingResponse failing send must select an in-range OSError")
        if case["target_profiles"] != ["python-package-cpython312"]:
            raise ContractError(
                "StreamingResponse OSError mapping is limited to the Python package profile"
            )
    _validate_dispatch_stimulus(
        {
            "scope": case["scope"],
            "receive": case["incoming"],
            "send": case["send"],
        },
        request_dispatch=True,
        allow_oserror_send=send_raises_oserror,
    )
    if case["scope"]["query_string_base64"] != "" or case["scope"]["headers_base64_pairs"] != []:
        raise ContractError("Response asgi-call scope uses the direct HTTP baseline")


def _route_method_matches(route: dict[str, Any], method: str) -> bool:
    return method in route["methods"] or (method == "HEAD" and "GET" in route["methods"])


def _router_redirect_candidate(path: str, route_path: str) -> str | None:
    if route_path == "/":
        return None
    return path.rstrip("/") if route_path.endswith("/") else path + "/"


def _router_redirect_requirements(
    routes: list[dict[str, Any]],
    path: str,
    root_path: str,
    method: str,
    redirect_slashes: bool,
    custom_convertors: dict[str, dict[str, Any]],
    query_string_base64: str,
) -> set[str]:
    """Derive redirect coverage from the live Router match and candidate inputs."""
    prefix = "starlette.routing.Router.route-dispatch."
    original_route_path = _route_path_after_root(path, root_path)
    original_matches = [
        route
        for route in routes
        if _route_template_matches(route["path"], original_route_path, custom_convertors)
    ]
    if original_matches:
        # Router handles both full and partial original-path matches before it
        # considers slash redirects.
        return set()

    candidate_path = _router_redirect_candidate(path, original_route_path)
    if candidate_path is None:
        return set()
    candidate_route_path = _route_path_after_root(candidate_path, root_path)
    candidate_matches = [
        route
        for route in routes
        if _route_template_matches(route["path"], candidate_route_path, custom_convertors)
    ]

    if not redirect_slashes:
        if candidate_matches:
            return {prefix + "redirect-disabled"}
        return set()
    if not candidate_matches:
        return {prefix + "redirect-no-counterpart"}
    if not any(_route_method_matches(route, method) for route in candidate_matches):
        return {prefix + "redirect-candidate-partial-method-match"}

    derived: set[str] = set()
    if root_path and not original_route_path.endswith("/") and query_string_base64:
        derived.add(prefix + "redirect-slash-append-root-path-query")
    if (
        original_route_path.endswith("/")
        and len(original_route_path) - len(original_route_path.rstrip("/")) > 1
    ):
        derived.add(prefix + "redirect-rstrip-repeated-slashes")
    return derived


def _application_has_slash_redirect(
    routes: list[dict[str, Any]], path: str, root_path: str
) -> bool:
    original_route_path = _route_path_after_root(path, root_path)
    if any(_route_template_matches(route["path"], original_route_path) for route in routes):
        return False
    candidate_path = _router_redirect_candidate(path, original_route_path)
    if candidate_path is None:
        return False
    candidate_route_path = _route_path_after_root(candidate_path, root_path)
    return any(_route_template_matches(route["path"], candidate_route_path) for route in routes)


def _validate_router_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, ROUTER_CASE_KEYS, "Router route-dispatch case")
    if case["surface"] != ROUTER_SURFACE or case["operation"] != ROUTER_OPERATION:
        raise ContractError("case is outside the declared Router route-dispatch operation")
    if case["observations"] != [ROUTER_OPERATION]:
        raise ContractError("Router observations must select route-dispatch")
    if type(case["redirect_slashes"]) is not bool:
        raise ContractError("Router redirect_slashes must be boolean")
    if not isinstance(case["routes"], list) or not case["routes"]:
        raise ContractError("Router route-dispatch requires a non-empty route list")
    if not isinstance(case["custom_convertors"], list):
        raise ContractError("Router custom_convertors must be an array")
    custom_convertors: dict[str, dict[str, Any]] = {}
    for index, raw_convertor in enumerate(case["custom_convertors"]):
        context = f"Router custom_convertors[{index}]"
        convertor = _exact(raw_convertor, {"name", "regex", "lowercase"}, context)
        name = _string(convertor["name"], f"{context}.name")
        regex = _string(convertor["regex"], f"{context}.regex")
        if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name) is None:
            raise ContractError(f"{context}.name must be a converter identifier")
        if not regex:
            raise ContractError(f"{context}.regex must be non-empty")
        try:
            re.compile(regex)
        except re.error as exc:
            raise ContractError(f"{context}.regex is invalid: {exc}") from exc
        if type(convertor["lowercase"]) is not bool:
            raise ContractError(f"{context}.lowercase must be boolean")
        if name in custom_convertors:
            raise ContractError(f"Router custom converter {name!r} is registered more than once")
        custom_convertors[name] = convertor
    has_host_route = any(
        isinstance(route, dict) and route.get("kind") == "host-route" for route in case["routes"]
    )
    routes = [
        _validate_router_route_input(route, f"Router routes[{index}]", custom_convertors)
        for index, route in enumerate(case["routes"])
    ]
    path = case["scope"].get("path")
    root_path = case["scope"].get("root_path")
    method = case["scope"].get("method")
    if not isinstance(path, str) or not isinstance(root_path, str) or not isinstance(method, str):
        raise ContractError(
            "Router route-dispatch scope must declare string path, root_path, and method"
        )
    _validate_route_dispatch_io(
        case,
        allow_query=True,
        allow_headers=has_host_route,
        allow_host=has_host_route,
    )
    route_path = _route_path_after_root(path, root_path)
    http_routes = [route for route in routes if route["kind"] == "http-route"]
    matched = [
        route
        for route in http_routes
        if method in route["methods"] or (method == "HEAD" and "GET" in route["methods"])
        if _route_template_matches(route["path"], route_path, custom_convertors)
    ]
    request_host = next(
        (
            base64.b64decode(pair[1], validate=True).decode("latin-1").split(":")[0]
            for pair in case["scope"]["headers_base64_pairs"]
            if base64.b64decode(pair[0], validate=True).lower() == b"host"
        ),
        "",
    )
    host_matched = [
        (index, route)
        for index, route in enumerate(routes)
        if route["kind"] == "host-route"
        if _route_template_matches(
            "/" + route["host"].lower(), "/" + request_host.lower(), custom_convertors
        )
    ]
    derived: set[str] = set()
    derived.update(
        _router_redirect_requirements(
            http_routes,
            path,
            root_path,
            method,
            case["redirect_slashes"],
            custom_convertors,
            case["scope"]["query_string_base64"],
        )
    )
    for route in matched:
        for _name, converter in _route_template_parameters(route["path"]):
            if converter in custom_convertors:
                derived.add("starlette.routing.Router.route-dispatch.custom-converter-override")
            else:
                requirement = {
                    "str": "string-converter-match",
                    "int": "int-converter-match",
                    "float": "float-converter-match",
                    "uuid": "uuid-converter-match",
                    "path": "path-converter-match",
                }.get(converter)
                if requirement is not None:
                    derived.add(f"starlette.routing.Router.route-dispatch.{requirement}")
    if not matched:
        derived.add("starlette.routing.Router.route-dispatch.converter-miss")
    first_full_route_index = min(
        (
            index
            for index, route in enumerate(routes)
            if (
                route["kind"] == "http-route"
                and (method in route["methods"] or (method == "HEAD" and "GET" in route["methods"]))
                and _route_template_matches(route["path"], route_path, custom_convertors)
            )
            or (
                route["kind"] == "host-route"
                and _route_template_matches(
                    "/" + route["host"].lower(), "/" + request_host.lower(), custom_convertors
                )
            )
        ),
        default=None,
    )
    selected_host_route_index = next(
        (index for index, _route in host_matched if index == first_full_route_index), None
    )
    if selected_host_route_index is not None:
        derived.add("starlette.routing.Router.route-dispatch.host-route-match")
        if selected_host_route_index > 0 and any(
            route["kind"] == "http-route"
            and _route_template_matches(route["path"], route_path, custom_convertors)
            and not (method in route["methods"] or (method == "HEAD" and "GET" in route["methods"]))
            for route in routes[:selected_host_route_index]
        ):
            derived.add("starlette.routing.Router.route-dispatch.partial-before-host-full")
    elif has_host_route and not matched:
        derived.add("starlette.routing.Router.route-dispatch.host-route-miss")
    if (
        root_path
        and path.startswith(root_path)
        and (path == root_path or path[len(root_path)] == "/")
        and matched
    ):
        derived.add("starlette.routing.Router.route-dispatch.root-path-match")
    if (
        root_path
        and path.startswith(root_path)
        and path != root_path
        and path[len(root_path)] != "/"
    ):
        if any(_route_template_matches(route["path"], path) for route in routes) and not any(
            _route_template_matches(route["path"], path[len(root_path) :]) for route in routes
        ):
            derived.add("starlette.routing.Router.route-dispatch.root-path-prefix-boundary")
    if (
        len(matched) > 1
        and any(_route_template_parameters(route["path"]) for route in matched)
        and any(not _route_template_parameters(route["path"]) for route in matched)
    ):
        derived.add("starlette.routing.Router.route-dispatch.static-parameter-order")
    claimed = set(case["covers"])
    if not claimed <= derived:
        raise ContractError(
            "Router case claims route requirements not exercised by its route and scope inputs: "
            f"{sorted(claimed - derived)}"
        )


def _validate_mount_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, MOUNT_CASE_KEYS, "Mount route-dispatch case")
    if case["surface"] != MOUNT_SURFACE or case["operation"] != MOUNT_OPERATION:
        raise ContractError("case is outside the declared Mount route-dispatch operation")
    if case["observations"] != [MOUNT_OPERATION]:
        raise ContractError("Mount observations must select route-dispatch")
    mount = _exact(case["mount"], {"path", "routes"}, "Mount input")
    if not isinstance(mount["path"], str) or not mount["path"].startswith("/"):
        raise ContractError("Mount.path must be an absolute route path")
    if not isinstance(mount["routes"], list) or not mount["routes"]:
        raise ContractError("Mount.routes must contain at least one child route")
    child_routes = [
        _validate_http_route_input(route, f"Mount.routes[{index}]")
        for index, route in enumerate(mount["routes"])
    ]
    _validate_route_dispatch_io(case, allow_inherited_mount_scope=True)
    path = case["scope"]["path"]
    root_path = case["scope"]["root_path"]
    route_path = _route_path_after_root(path, root_path)
    mount_template = mount["path"].rstrip("/") + "/{_mount_path:path}"
    mount_captures = _route_template_capture(mount_template, route_path)
    mount_matches = mount_captures is not None
    if mount_captures is not None:
        remainder = mount_captures["_mount_path"]
        child_path = "/" + remainder
        matching_child_routes = [
            route for route in child_routes if _route_template_matches(route["path"], child_path)
        ]
    else:
        matching_child_routes = []
    method = case["scope"]["method"].upper()
    child_method_matches = any(
        not route["methods"]
        or method in {registered.upper() for registered in route["methods"]}
        or (method == "HEAD" and "GET" in {registered.upper() for registered in route["methods"]})
        for route in matching_child_routes
    )
    derived = set()
    if mount_matches:
        derived.add("starlette.routing.Mount.route-dispatch.scope-extension")
    if not mount_matches:
        derived.add("starlette.routing.Mount.route-dispatch.miss")
    if mount_matches and not matching_child_routes:
        derived.add("starlette.routing.Mount.route-dispatch.child-not-found")
    if matching_child_routes and not child_method_matches:
        derived.add("starlette.routing.Mount.route-dispatch.child-method-not-allowed")
    if mount_matches and "path_params" in case["scope"]:
        inherited_names = set(case["scope"]["path_params"])
        route_names = {"path"}
        route_names.update(name for name, _ in _route_template_parameters(mount["path"]))
        route_names.update(
            name for route in child_routes for name, _ in _route_template_parameters(route["path"])
        )
        if inherited_names & route_names:
            derived.add("starlette.routing.Mount.route-dispatch.inherited-path-parameter-collision")
    if not set(case["covers"]) <= derived:
        raise ContractError(
            "Mount case requirements are not exercised by its mount and scope inputs"
        )


def _validate_reverse_path(
    path: Any, custom: dict[str, dict[str, Any]], context: str
) -> list[tuple[str, str]]:
    path = _string(path, context)
    if not path.startswith("/"):
        raise ContractError(f"{context} must start with '/'")
    parameter = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_][a-zA-Z0-9_]*))?\}")
    parsed: list[tuple[str, str]] = []
    offset = 0
    for match in parameter.finditer(path):
        if "{" in path[offset : match.start()] or "}" in path[offset : match.start()]:
            raise ContractError(f"{context} contains malformed route parameters")
        name, converter = match.groups()
        converter = converter or "str"
        if converter not in {"str", "path", "int", "float", "uuid"} | set(custom):
            raise ContractError(f"{context} uses an undeclared converter {converter!r}")
        parsed.append((name, converter))
        offset = match.end()
    if "{" in path[offset:] or "}" in path[offset:]:
        raise ContractError(f"{context} contains malformed route parameters")
    if len({name for name, _ in parsed}) != len(parsed):
        raise ContractError(f"{context} repeats a route parameter name")
    return parsed


def _validate_reverse_route_node(
    node: Any,
    context: str,
    custom: dict[str, dict[str, Any]],
    *,
    allow_observer: bool,
) -> dict[str, Any]:
    if not isinstance(node, dict) or not isinstance(node.get("kind"), str):
        raise ContractError(f"{context} must declare a route node kind")
    kind = node["kind"]
    if kind in {"router", "starlette-app"}:
        node = _exact(node, {"kind", "routes"}, context)
        routes = node["routes"]
        if not isinstance(routes, list) or not routes:
            raise ContractError(f"{context}.routes must be a non-empty array")
        for index, route in enumerate(routes):
            _validate_reverse_route_node(
                route,
                f"{context}.routes[{index}]",
                custom,
                allow_observer=allow_observer,
            )
        return node
    if kind == "mount":
        node = _exact(node, {"kind", "path", "name", "routes"}, context)
        _validate_reverse_path(node["path"], custom, f"{context}.path")
        if node["name"] is not None:
            _string(node["name"], f"{context}.name")
        if not isinstance(node["routes"], list):
            raise ContractError(f"{context}.routes must be an array")
        for index, route in enumerate(node["routes"]):
            _validate_reverse_route_node(
                route,
                f"{context}.routes[{index}]",
                custom,
                allow_observer=allow_observer,
            )
        return node
    if kind == "host-route":
        node = _exact(node, {"kind", "host", "name", "routes"}, context)
        host = _string(node["host"], f"{context}.host")
        if not host or "/" in host:
            raise ContractError(f"{context}.host must be a non-empty host pattern")
        _validate_reverse_path("/" + host, custom, f"{context}.host")
        if node["name"] is not None:
            _string(node["name"], f"{context}.name")
        if not isinstance(node["routes"], list):
            raise ContractError(f"{context}.routes must be an array")
        for index, route in enumerate(node["routes"]):
            _validate_reverse_route_node(
                route,
                f"{context}.routes[{index}]",
                custom,
                allow_observer=allow_observer,
            )
        return node
    if kind == "http-route":
        node = _exact(node, {"kind", "path", "name", "methods", "observer"}, context)
        _validate_reverse_path(node["path"], custom, f"{context}.path")
        if node["name"] is not None:
            _string(node["name"], f"{context}.name")
        methods = node["methods"]
        if (
            not isinstance(methods, list)
            or not methods
            or any(not isinstance(method, str) or not method for method in methods)
            or len(methods) != len(set(methods))
        ):
            raise ContractError(f"{context}.methods must be a non-empty unique string array")
    elif kind == "websocket-route":
        node = _exact(node, {"kind", "path", "name", "observer"}, context)
        _validate_reverse_path(node["path"], custom, f"{context}.path")
        if node["name"] is not None:
            _string(node["name"], f"{context}.name")
    else:
        raise ContractError(f"{context}.kind is unsupported")
    if node["observer"] not in {None, "request-url-for"}:
        raise ContractError(f"{context}.observer is unsupported")
    if node["observer"] is not None and (not allow_observer or kind != "http-route"):
        raise ContractError(f"{context}.observer is only available on Request HTTP probes")
    return node


def _reverse_route_candidates(
    node: dict[str, Any],
    name: str,
    path_params: dict[str, Any],
    custom: dict[str, dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """Return structurally successful lookup candidates in route-list order."""
    kind = node["kind"]
    if kind in {"http-route", "websocket-route"}:
        expected = {key for key, _ in _validate_reverse_path(node["path"], custom, "route path")}
        return [(0, node)] if node["name"] == name and expected == set(path_params) else []
    if kind in {"router", "starlette-app"}:
        results: list[tuple[int, dict[str, Any]]] = []
        for index, route in enumerate(node["routes"]):
            results.extend(
                (index, match)
                for _nested_index, match in _reverse_route_candidates(
                    route, name, path_params, custom
                )
            )
        return results
    if kind == "mount":
        mount_parameters = {
            key for key, _ in _validate_reverse_path(node["path"], custom, "mount path")
        }
        # Mount adds a trailing {path:path} parameter to its own compiled path.
        mount_parameters.add("path")
        if node["name"] is not None and name == node["name"]:
            return (
                [(0, node)]
                if "path" in path_params and mount_parameters == set(path_params)
                else []
            )
        if node["name"] is None:
            child_name = name
        elif name.startswith(node["name"] + ":"):
            child_name = name[len(node["name"]) + 1 :]
        else:
            return []
        remaining = {
            key: value for key, value in path_params.items() if key not in mount_parameters
        }
        if "path" in path_params:
            remaining["path"] = path_params["path"]
        results = []
        for index, route in enumerate(node["routes"]):
            results.extend(
                (index, match)
                for _nested_index, match in _reverse_route_candidates(
                    route, child_name, remaining, custom
                )
            )
        return results
    if kind == "host-route":
        host_parameters = {
            key for key, _ in _validate_reverse_path("/" + node["host"], custom, "Host.host")
        }
        if node["name"] is not None and name == node["name"]:
            direct_parameters = host_parameters | {"path"}
            return (
                [(0, node)]
                if "path" in path_params and direct_parameters == set(path_params)
                else []
            )
        if node["name"] is None:
            child_name = name
        elif name.startswith(node["name"] + ":"):
            child_name = name[len(node["name"]) + 1 :]
        else:
            return []
        remaining = {key: value for key, value in path_params.items() if key not in host_parameters}
        results = []
        for index, route in enumerate(node["routes"]):
            results.extend(
                (index, match)
                for _nested_index, match in _reverse_route_candidates(
                    route, child_name, remaining, custom
                )
            )
        return results
    raise ContractError("reverse route graph has an unsupported node")


def _reverse_route_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    if node["kind"] in {"router", "starlette-app", "mount", "host-route"}:
        result: list[dict[str, Any]] = []
        for child in node["routes"]:
            result.extend(_reverse_route_nodes(child))
        return result
    return [node]


def _reverse_effective_observer_paths(
    node: dict[str, Any], prefix: str = ""
) -> list[tuple[str, list[str]]]:
    if node["kind"] in {"router", "starlette-app", "host-route"}:
        result: list[tuple[str, list[str]]] = []
        for child in node["routes"]:
            result.extend(_reverse_effective_observer_paths(child, prefix))
        return result
    if node["kind"] == "mount":
        mount_path = node["path"]
        next_prefix = prefix.rstrip("/") + mount_path
        result = []
        for child in node["routes"]:
            result.extend(_reverse_effective_observer_paths(child, next_prefix))
        return result
    if node["observer"] == "request-url-for":
        effective_path = prefix.rstrip("/") + node["path"]
        return [(effective_path or "/", [method for method in node.get("methods", ["GET"])])]
    return []


def _reverse_node_depth(node: dict[str, Any], kind: str) -> int:
    if node["kind"] not in {"router", "starlette-app", "mount", "host-route"}:
        return 0
    own = 1 if node["kind"] == kind else 0
    return own + max((_reverse_node_depth(child, kind) for child in node["routes"]), default=0)


def _reverse_input_requirements(case: dict[str, Any]) -> set[str]:
    surface = case["surface"]
    operation = case["operation"]
    graph = case["route_graph"]
    lookup = case["lookup"]
    params = lookup["path_params"]
    custom = {item["name"]: item for item in case["custom_convertors"]}
    derived: set[str] = set()

    def rid(suffix: str) -> str:
        return f"{surface}.{operation}.{suffix}"

    if surface == "starlette.requests.Request":
        provider = case["request_scope"]["provider"]
        if provider == "none":
            derived.add(rid("missing-context"))
        elif provider == "router":
            derived.add(rid("router-provider"))
        elif provider == "app":
            derived.add(rid("app-provider"))
        elif provider == "dispatch":
            scope = case["request_scope"]
            if scope["root_path"]:
                derived.add(rid("mount-app-root-path"))
        return derived

    candidates = _reverse_route_candidates(graph, lookup["name"], params, custom)
    found = bool(candidates)
    if surface == "starlette.routing.Route":
        route = graph
        expected = _validate_reverse_path(route["path"], custom, "Route.path")
        if route["name"] == lookup["name"] and {name for name, _ in expected} == set(params):
            if not expected:
                derived.add(rid("static-path"))
            converter_suffixes = {
                "str": "str-converter",
                "int": "int-converter",
                "float": "float-converter",
                "path": "path-converter",
                "uuid": "uuid-converter",
            }
            for _name, converter in expected:
                suffix = converter_suffixes.get(converter)
                if suffix:
                    derived.add(rid(suffix))
                if converter in custom:
                    derived.add(rid("custom-converter-override"))
                value = params[_name]
                if (
                    (converter == "str" and (not str(value) or "/" in str(value)))
                    or (converter == "int" and int(value) < 0)
                    or (converter == "float" and float(value) < 0)
                ):
                    derived.add(rid("converter-error"))
        else:
            derived.add(rid("parameter-mismatch"))
    elif surface == "starlette.routing.WebSocketRoute":
        if found:
            derived.add(rid("protocol"))
    elif surface == "starlette.routing.Router":
        if found:
            first_candidate = min(index for index, _route in candidates)
            if first_candidate > 0:
                derived.add(rid("first-success"))
        else:
            derived.add(rid("mismatch"))
    elif surface == "starlette.routing.Mount":
        if found:
            if lookup["name"] == graph["name"]:
                derived.add(rid("direct-path"))
            else:
                derived.add(rid("nested-route"))
                if _reverse_node_depth(graph, "mount") > 1:
                    derived.add(rid("double-mount"))
        else:
            derived.add(rid("mismatch"))
    elif surface == "starlette.applications.Starlette" and found:
        derived.add(rid("forwarder"))
    elif surface == HOST_SURFACE and found:
        if lookup["name"] == graph["name"]:
            derived.add(rid("direct-path"))
        else:
            derived.add(rid("nested-route"))
    return derived


def _validate_reverse_url_case_stimulus(case: dict[str, Any]) -> None:
    _exact(case, REVERSE_URL_CASE_KEYS, "reverse URL case")
    key = (case["surface"], case["operation"])
    if key not in REVERSE_URL_OPERATIONS:
        raise ContractError("case is outside the declared reverse URL operations")
    if case["observations"] != [REVERSE_URL_OBSERVATION]:
        raise ContractError("reverse URL observations must select reverse-url")
    if not isinstance(case["custom_convertors"], list):
        raise ContractError("reverse URL custom_convertors must be an array")
    custom: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(case["custom_convertors"]):
        context = f"reverse URL custom_convertors[{index}]"
        convertor = _exact(raw, {"name", "regex", "lowercase", "lowercase_to_string"}, context)
        name = _string(convertor["name"], f"{context}.name")
        regex = _string(convertor["regex"], f"{context}.regex")
        if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name) is None or not regex:
            raise ContractError(f"{context} must define a converter identifier and non-empty regex")
        try:
            re.compile(regex)
        except re.error as exc:
            raise ContractError(f"{context}.regex is invalid: {exc}") from exc
        if (
            type(convertor["lowercase"]) is not bool
            or type(convertor["lowercase_to_string"]) is not bool
        ):
            raise ContractError(f"{context} lowercase flags must be boolean")
        if name in custom:
            raise ContractError(f"reverse URL converter {name!r} is registered more than once")
        custom[name] = convertor

    graph = case["route_graph"]
    lookup = _exact(case["lookup"], {"name", "path_params"}, "reverse URL lookup")
    _string(lookup["name"], "reverse URL lookup.name")
    if not isinstance(lookup["path_params"], dict):
        raise ContractError("reverse URL lookup.path_params must be an object")
    for name, value in lookup["path_params"].items():
        _string(name, "reverse URL path parameter name")
        if isinstance(value, (dict, list)):
            raise ContractError("reverse URL path parameter values must be JSON scalars")

    request_scope = case["request_scope"]
    if key[0] == "starlette.requests.Request":
        request_scope = _exact(
            request_scope,
            {
                "provider",
                "type",
                "method",
                "scheme",
                "path",
                "root_path",
                "app_root_path",
                "server",
            },
            "Request URL scope",
        )
        if request_scope["provider"] not in {"dispatch", "router", "app", "none"}:
            raise ContractError("Request URL scope.provider is unsupported")
        if request_scope["type"] != "http":
            raise ContractError("Request.url_for cases require an HTTP scope")
        for name in ("method", "scheme", "path"):
            _string(request_scope[name], f"Request URL scope.{name}")
        if not isinstance(request_scope["root_path"], str):
            raise ContractError("Request URL scope.root_path must be a string")
        if request_scope["scheme"] not in {"http", "https"}:
            raise ContractError("Request URL scope.scheme must be http or https")
        if not request_scope["path"].startswith("/") or (
            request_scope["root_path"] and not request_scope["root_path"].startswith("/")
        ):
            raise ContractError("Request URL scope path and root_path must be absolute")
        app_root_path = request_scope["app_root_path"]
        if app_root_path is not None and (
            not isinstance(app_root_path, str)
            or (app_root_path and not app_root_path.startswith("/"))
        ):
            raise ContractError("Request URL scope.app_root_path must be null or an absolute path")
        server = request_scope["server"]
        if (
            not isinstance(server, list)
            or len(server) != 2
            or not isinstance(server[0], str)
            or type(server[1]) is not int
            or server[1] < 0
        ):
            raise ContractError("Request URL scope.server must be [host, non-negative port]")
        provider = request_scope["provider"]
        if provider == "none":
            if graph is not None:
                raise ContractError("Request provider none requires route_graph null")
        else:
            if graph is None:
                raise ContractError("Request URL provider requires a route_graph")
            expected_kind = {"dispatch": "router", "router": "router", "app": "starlette-app"}[
                provider
            ]
            if not isinstance(graph, dict) or graph.get("kind") != expected_kind:
                raise ContractError(
                    f"Request provider {provider!r} requires a {expected_kind} route_graph"
                )
    else:
        if request_scope is not None:
            raise ContractError("direct url_path_for cases must set request_scope to null")
        expected_kind = REVERSE_URL_SURFACE_KINDS[key[0]]
        if not isinstance(graph, dict) or graph.get("kind") != expected_kind:
            raise ContractError(f"{key[0]} cases require a {expected_kind} route_graph")

    allow_observer = (
        key[0] == "starlette.requests.Request" and request_scope["provider"] == "dispatch"
    )
    if graph is not None:
        graph = _validate_reverse_route_node(
            graph, "reverse URL route_graph", custom, allow_observer=allow_observer
        )
    if key[0] == "starlette.requests.Request" and allow_observer:
        observers = _reverse_effective_observer_paths(graph)
        if len(observers) != 1:
            raise ContractError(
                "Request dispatch requires exactly one request-url-for observer route"
            )
        route_path = _route_path_after_root(request_scope["path"], request_scope["root_path"])
        observer_path, methods = observers[0]
        if request_scope["method"] not in methods or not _route_template_matches(
            observer_path, route_path, custom
        ):
            raise ContractError("Request scope does not select its request-url-for observer route")
    if custom and key[0] != "starlette.routing.Route":
        raise ContractError("custom URL convertors are scoped to direct Route.url_path_for cases")
    derived = _reverse_input_requirements(case)
    if not set(case["covers"]) <= derived:
        raise ContractError(
            "reverse URL case claims requirements not exercised by its route graph and lookup inputs: "
            f"{sorted(set(case['covers']) - derived)}"
        )


def validate_case(case: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    is_websocket = isinstance(case, dict) and case.get("surface") == WEBSOCKET_SURFACE
    is_websocket_close = isinstance(case, dict) and case.get("surface") == WEBSOCKET_CLOSE_SURFACE
    is_websocket_route = (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_ROUTE_SURFACE
        and case.get("operation") == WEBSOCKET_ROUTE_OPERATION
    )
    is_router = (
        isinstance(case, dict)
        and case.get("surface") == ROUTER_SURFACE
        and case.get("operation") == ROUTER_OPERATION
    )
    is_mount = (
        isinstance(case, dict)
        and case.get("surface") == MOUNT_SURFACE
        and case.get("operation") == MOUNT_OPERATION
    )
    is_reverse_url = (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) in REVERSE_URL_OPERATIONS
    )
    is_redirect_response = (
        isinstance(case, dict)
        and case.get("surface") == REDIRECT_RESPONSE_SURFACE
        and case.get("operation") == REDIRECT_RESPONSE_OPERATION
    )
    is_file_response = (
        isinstance(case, dict)
        and case.get("surface") == FILE_RESPONSE_SURFACE
        and case.get("operation") == RESPONSE_OPERATION
    )
    is_response = isinstance(case, dict) and case.get("surface") in RESPONSE_SURFACES
    is_streaming_response = (
        isinstance(case, dict)
        and case.get("surface") == STREAMING_RESPONSE_SURFACE
        and case.get("operation")
        in {STREAMING_RESPONSE_OPERATION, STREAMING_RESPONSE_TRACE_OPERATION}
    )
    is_value_formatting = (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) in VALUE_FORMATTING_OPERATIONS
    )
    is_rust_owned_python = (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) in RUST_OWNED_PYTHON_OPERATIONS
    )
    is_default_receive = (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_DEFAULT_RECEIVE_OPERATION
    )
    is_status_symbols = (
        isinstance(case, dict) and (case.get("surface"), case.get("operation")) == STATUS_OPERATION
    )
    expected_case_keys = (
        WEBSOCKET_CASE_KEYS
        if is_websocket
        else WEBSOCKET_CLOSE_CASE_KEYS
        if is_websocket_close
        else WEBSOCKET_ROUTE_CASE_KEYS
        if is_websocket_route
        else ROUTER_CASE_KEYS
        if is_router
        else MOUNT_CASE_KEYS
        if is_mount
        else REVERSE_URL_CASE_KEYS
        if is_reverse_url
        else REDIRECT_RESPONSE_CASE_KEYS
        if is_redirect_response
        else FILE_RESPONSE_CASE_KEYS
        if is_file_response
        else RESPONSE_CASE_KEYS
        if is_response
        else STREAMING_RESPONSE_CASE_KEYS
        if is_streaming_response
        else STATUS_CASE_KEYS
        if is_status_symbols
        else CASE_KEYS
    )
    if is_value_formatting:
        value_keys = (
            {"instances"} if case["surface"] == EXCEPTION_VALUES_SURFACE else {"middleware"}
        )
        expected_case_keys = (CASE_KEYS - {"steps", "execution_schedule"}) | value_keys
    elif is_rust_owned_python:
        input_keys = {
            ("starlette.config.Config", "value-resolution"): {"config", "lookups"},
            ("starlette.config.Config", "constructor-warning"): {"env_file"},
            ("starlette.config.Environ", "mapping-sequence"): {
                "initial_environ",
                "actions",
            },
            ("starlette.schemas.SchemaGenerator", "schema-generation"): {
                "base_schema",
                "routes",
            },
            ("starlette.schemas.BaseSchemaGenerator", "schema-docstring-parsing"): {
                "docstrings",
            },
            ("starlette.schemas.OpenAPIResponse", "openapi-response-render"): {"content"},
        }[(case["surface"], case["operation"])]
        expected_case_keys = (CASE_KEYS - {"steps", "execution_schedule"}) | input_keys
    elif is_default_receive:
        expected_case_keys = (CASE_KEYS - {"steps", "execution_schedule"}) | {"scope"}
    elif is_status_symbols:
        expected_case_keys = STATUS_CASE_KEYS
    if is_streaming_response and "background" in case:
        expected_case_keys = expected_case_keys | {"background"}
    _exact(case, expected_case_keys, "case")
    case_id = _string(case["case_id"], "case.case_id")
    is_gzip = case["surface"] == GZIP_SURFACE
    is_protocol_middleware = case["surface"] in ASGI_MIDDLEWARE_SURFACES
    is_middleware_construction = is_protocol_middleware and case["operation"] == "__init__"
    is_body_limit = case["surface"] == BODY_LIMIT_SURFACE
    if is_websocket:
        if case["operation"] not in {
            WEBSOCKET_OPERATION,
            WEBSOCKET_STATE_OPERATION,
            WEBSOCKET_CONVENIENCE_OPERATION,
        }:
            raise ContractError("WebSocket cases must use a declared sequence operation")
    elif is_websocket_close:
        if case["operation"] != WEBSOCKET_CLOSE_OPERATION:
            raise ContractError(
                "WebSocketClose cases must use the declared call-sequence operation"
            )
    elif is_websocket_route:
        if case["operation"] != WEBSOCKET_ROUTE_OPERATION:
            raise ContractError(
                "WebSocketRoute cases must use the declared route-dispatch operation"
            )
    elif is_router:
        if case["operation"] != ROUTER_OPERATION:
            raise ContractError("Router cases must use the declared route-dispatch operation")
    elif is_mount:
        if case["operation"] != MOUNT_OPERATION:
            raise ContractError("Mount cases must use the declared route-dispatch operation")
    elif is_reverse_url:
        if (case["surface"], case["operation"]) not in REVERSE_URL_OPERATIONS:
            raise ContractError("case must use a declared reverse URL operation")
    elif is_redirect_response:
        if case["operation"] != REDIRECT_RESPONSE_OPERATION:
            raise ContractError("RedirectResponse cases must use the declared asgi-call operation")
    elif is_file_response:
        if case["operation"] != RESPONSE_OPERATION:
            raise ContractError("FileResponse cases must use the declared asgi-call operation")
    elif is_response:
        if case["operation"] != RESPONSE_OPERATION:
            raise ContractError("Response cases must use the declared asgi-call operation")
    elif is_streaming_response:
        if case["operation"] not in {
            STREAMING_RESPONSE_OPERATION,
            STREAMING_RESPONSE_TRACE_OPERATION,
        }:
            raise ContractError("StreamingResponse cases must use a declared ASGI-call operation")
    elif is_gzip:
        if case["operation"] != "__call__":
            raise ContractError("GZipMiddleware parity cases must call its public ASGI interface")
    elif is_protocol_middleware:
        if case["operation"] not in {"__call__", "__init__"}:
            raise ContractError("ASGI middleware cases must use a declared public operation")
    elif is_body_limit:
        if case["operation"] != "__call__":
            raise ContractError(
                "RequestBodyLimitMiddleware parity cases must call its public ASGI interface"
            )
    elif is_value_formatting:
        if case["operation"] != VALUE_FORMATTING_OPERATION:
            raise ContractError("value-formatting cases must use their declared operation")
    elif is_rust_owned_python:
        if (case["surface"], case["operation"]) not in RUST_OWNED_PYTHON_OPERATIONS:
            raise ContractError("configuration and schema cases must use declared operations")
    elif is_default_receive:
        if case["observations"] != ["receive"]:
            raise ContractError("default receive cases must select the receive observation")
    elif is_status_symbols:
        if (case["surface"], case["operation"]) != STATUS_OPERATION:
            raise ContractError(
                "status module cases must use the declared symbol-sequence operation"
            )
    elif case["surface"] != "starlette.applications.Starlette" or case["operation"] not in {
        "__call__",
        "request-dispatch",
    }:
        raise ContractError(
            "only the declared Starlette and WebSocket protocol profiles are in scope"
        )
    identity_operation = (
        STREAMING_RESPONSE_OPERATION
        if (case["surface"], case["operation"])
        == (STREAMING_RESPONSE_SURFACE, STREAMING_RESPONSE_TRACE_OPERATION)
        else case["operation"]
    )
    if not case_id.startswith(f"{case['surface']}.{identity_operation}.") or case["assets"] != []:
        raise ContractError(
            "case ID must bind to the declared surface and this slice has no assets"
        )
    profile_ids = {profile["id"] for profile in manifest["target_profiles"]}
    selected_profiles = case["target_profiles"]
    if (
        not isinstance(selected_profiles, list)
        or not selected_profiles
        or any(not isinstance(item, str) for item in selected_profiles)
        or len(selected_profiles) != len(set(selected_profiles))
        or not set(selected_profiles) <= profile_ids
    ):
        raise ContractError("case must select one or more declared target profiles")
    selected_profile_ids = set(selected_profiles)
    requirements: dict[str, dict[str, Any]] = {}
    operations: dict[tuple[str, str], dict[str, Any]] = {}
    for surface in manifest["surfaces"]:
        for operation in surface["operations"]:
            operations[(surface["id"], operation["id"])] = operation
            for requirement in operation["requirements"]:
                requirements[requirement["id"]] = requirement
    covers = case["covers"]
    if (
        not isinstance(covers, list)
        or not covers
        or any(not isinstance(item, str) for item in covers)
    ):
        raise ContractError("case.covers must contain declared requirement IDs")
    if len(covers) != len(set(covers)):
        raise ContractError("case.covers must not repeat a requirement ID")
    for requirement_id in covers:
        requirement = requirements.get(requirement_id)
        if requirement is None or "parity" not in requirement["lanes"]:
            raise ContractError(
                f"case.covers references a missing or non-parity requirement: {requirement_id}"
            )
        if not selected_profile_ids <= set(requirement["target_profiles"]):
            raise ContractError(
                f"case target profiles exceed requirement applicability: {requirement_id}"
            )

    if is_value_formatting:
        _validate_value_formatting_case(case)
        return case
    if is_default_receive:
        _validate_default_receive_case(case)
        return case
    if is_status_symbols:
        _validate_status_symbols_case(case)
        return case
    if is_rust_owned_python:
        if (case["surface"], case["operation"]) in CONFIG_OPERATIONS:
            _validate_config_case(case)
        else:
            _validate_schema_case(case)
        return case

    if is_body_limit:
        _validate_body_limit_case_stimulus(case)
        return case

    if is_websocket:
        if case["operation"] == WEBSOCKET_CONVENIENCE_OPERATION:
            _validate_websocket_convenience_case_stimulus(case)
        else:
            _validate_websocket_case_stimulus(case)
        return case
    if is_websocket_close:
        _validate_websocket_close_case_stimulus(case)
        return case
    if is_websocket_route:
        _validate_websocket_route_case_stimulus(case)
        return case
    if is_router:
        _validate_router_case_stimulus(case)
        return case
    if is_mount:
        _validate_mount_case_stimulus(case)
        return case
    if is_reverse_url:
        _validate_reverse_url_case_stimulus(case)
        return case
    if is_redirect_response:
        _validate_redirect_response_case_stimulus(case)
        return case
    if is_file_response:
        _validate_file_response_case_stimulus(case)
        return case
    if is_response:
        _validate_response_case_stimulus(case)
        return case
    if is_streaming_response:
        _validate_streaming_response_case_stimulus(case)
        return case

    if not isinstance(case["steps"], list) or (
        len(case["steps"]) not in {2, 3}
        and not (is_middleware_construction and len(case["steps"]) == 1)
    ):
        raise ContractError("case must contain construction and dispatch steps")
    step_ids = [step.get("step_id") for step in case["steps"]]
    allowed_step_sequences = (
        (["construct"],)
        if is_middleware_construction
        else (["middleware", "dispatch"],)
        if is_protocol_middleware
        else (
            ["application", "dispatch"],
            ["application", "lifecycle", "dispatch"],
            ["application", "lifecycle"],
        )
    )
    if step_ids not in allowed_step_sequences:
        raise ContractError("case steps must follow the declared construction and dispatch order")
    expected_observations = step_ids if is_middleware_construction else step_ids[1:]
    if case["observations"] != expected_observations:
        raise ContractError(
            "case observations must select each non-construction workflow step in order"
        )
    if (
        not is_protocol_middleware
        and case["operation"] == "request-dispatch"
        and step_ids
        != [
            "application",
            "dispatch",
        ]
    ):
        raise ContractError("request-dispatch must contain application then dispatch")
    if (
        case["steps"][0].get("surface") != case["surface"]
        or case["steps"][0].get("operation") != "__init__"
    ):
        raise ContractError("construction step must construct the declared public surface")
    if (
        is_protocol_middleware
        and not is_middleware_construction
        and (
            case["steps"][1].get("surface") != case["surface"]
            or case["steps"][1].get("operation") != "__call__"
        )
    ):
        raise ContractError("GZipMiddleware case must dispatch through its public __call__")
    if (
        not is_protocol_middleware
        and case["operation"] == "__call__"
        and any(
            step.get("surface") != case["surface"] or step.get("operation") != "__call__"
            for step in case["steps"][1:]
        )
    ):
        raise ContractError(
            "Starlette.__call__ workflows must dispatch every protocol step through __call__"
        )
    if case["operation"] == "request-dispatch" and (
        case["steps"][1].get("surface") != case["surface"]
        or case["steps"][1].get("operation") != "request-dispatch"
    ):
        raise ContractError(
            "request-dispatch workflow must use the declared request-dispatch operation"
        )

    previous: set[str] = set()
    for index, step in enumerate(case["steps"]):
        context = f"case.steps[{index}]"
        _exact(step, STEP_KEYS, context)
        step_id = _string(step["step_id"], f"{context}.step_id")
        if step_id in previous:
            raise ContractError(f"duplicate step id: {step_id}")
        operation = operations.get((step["surface"], step["operation"]))
        if operation is None:
            raise ContractError(f"{context} refers to an undeclared public operation")
        parameters = {parameter["id"]: parameter for parameter in operation["source"]["parameters"]}
        arguments = step["arguments"]
        if not isinstance(arguments, dict) or set(arguments) - set(parameters):
            raise ContractError(
                f"{context}.arguments is not an object or contains unknown parameters"
            )
        required = {
            parameter_id
            for parameter_id, parameter in parameters.items()
            if parameter["omission"]["kind"] == "required" and parameter["style"] != "receiver"
        }
        if required - set(arguments):
            raise ContractError(
                f"{context}.arguments misses required parameters: {sorted(required - set(arguments))}"
            )
        for name, descriptor in arguments.items():
            decoded = _descriptor(descriptor, previous, f"{context}.arguments.{name}")
            if isinstance(decoded, dict) and set(decoded) == {"__binding_step__"}:
                continue
            allowed_types = set(parameters[name]["value_types"])
            actual_type = _value_type(decoded)
            record_matches = actual_type == "mapping" and bool(
                allowed_types & {"mapping", "record"}
            )
            if (
                actual_type not in allowed_types
                and not record_matches
                and "any_json" not in allowed_types
                # JSON cannot encode Python exception-class keys or callback
                # values. parity-input@4 therefore encodes this declared
                # mapping parameter as an ordered array of tagged entries;
                # `_validate_application_stimulus` validates and materializes
                # that representation before either live adapter calls Starlette.
                and not (
                    step["surface"] == "starlette.applications.Starlette"
                    and step["operation"] == "__init__"
                    and name == "exception_handlers"
                    and isinstance(decoded, list)
                    and "mapping" in allowed_types
                )
            ):
                raise ContractError(
                    f"{context}.arguments.{name} has type {actual_type}, expected {sorted(allowed_types)}"
                )
        receiver = step["receiver"]
        if parameters.get("self", {}).get("style") == "receiver":
            if operation["kind"] == "constructor":
                if receiver is not None:
                    raise ContractError(f"{context}.receiver must be null for construction")
            elif receiver != {"kind": "binding", "step_id": step_ids[0]}:
                raise ContractError(f"{context}.receiver must bind the declared application")
        elif receiver is not None:
            raise ContractError(f"{context}.receiver must be null for this operation")
        previous.add(step_id)

    app_args = {
        key: descriptor["value"] for key, descriptor in case["steps"][0]["arguments"].items()
    }
    lifespan_only = step_ids == ["application", "lifecycle"]
    if lifespan_only:
        _validate_lifespan_only_case(case, app_args)
    if is_gzip:
        _validate_gzip_constructor_stimulus(app_args)
    elif is_protocol_middleware:
        _validate_asgi_middleware_constructor(case["surface"], app_args)
    else:
        _validate_application_stimulus(
            app_args,
            case["operation"] == "request-dispatch",
            allow_lifespan_variants=lifespan_only,
        )
    server_error_case = not is_protocol_middleware and _is_server_error_stimulus(app_args)
    body_reuse = False
    if not is_protocol_middleware:
        body_reuse = (
            isinstance(app_args["routes"][0]["endpoint"], dict)
            and app_args["routes"][0]["endpoint"].get("kind") == "http-exception-after-body"
        )
    for step in case["steps"][1:]:
        step_args = {key: descriptor["value"] for key, descriptor in step["arguments"].items()}
        if is_protocol_middleware:
            if is_gzip:
                _validate_dispatch_stimulus(step_args, request_dispatch=True)
            else:
                _validate_asgi_middleware_dispatch(case["surface"], step_args)
        else:
            _validate_dispatch_stimulus(
                step_args,
                case["operation"] == "request-dispatch",
                allow_nonempty_body=body_reuse,
                allow_headers=server_error_case,
                allow_query=case["operation"] == "__call__",
                allow_lifespan_callback_failures=lifespan_only,
            )
    dispatch = case["steps"][-1]
    dispatch_args = {key: descriptor["value"] for key, descriptor in dispatch["arguments"].items()}
    if not is_protocol_middleware and (
        body_reuse or app_args["exception_handlers"] or server_error_case
    ):
        _validate_exception_handler_dispatch(app_args, dispatch_args)
    schedule = case["execution_schedule"]
    if is_middleware_construction:
        if schedule != ["construct"]:
            raise ContractError("ASGI middleware construction cases must schedule one construction")
        expected_schedule = ["construct"]
    elif is_protocol_middleware:
        if dispatch_args["scope"]["type"] not in {"http", "websocket"} or schedule != ["dispatch"]:
            raise ContractError("ASGI middleware cases must dispatch one HTTP or WebSocket scope")
        expected_schedule = ["dispatch"]
    elif step_ids == ["application", "lifecycle"]:
        if dispatch_args["scope"]["type"] != "lifespan":
            raise ContractError("lifespan-only workflow must use a lifespan scope")
        expected_schedule = ["lifespan.startup", "lifespan.shutdown"]
    elif step_ids == ["application", "lifecycle", "dispatch"]:
        lifecycle_args = {
            key: descriptor["value"] for key, descriptor in case["steps"][1]["arguments"].items()
        }
        if (
            lifecycle_args["scope"]["type"] != "lifespan"
            or dispatch_args["scope"]["type"] != "http"
        ):
            raise ContractError("interleaved workflow must pair lifespan and HTTP scopes")
        expected_schedule = ["lifespan.startup", "dispatch", "lifespan.shutdown"]
    else:
        if dispatch_args["scope"]["type"] != "http":
            raise ContractError("dispatch step must use an HTTP scope")
        expected_schedule = ["dispatch"]
    if schedule != expected_schedule:
        raise ContractError(
            "execution_schedule does not match the scopes and protocol messages in the steps"
        )
    exercised = (
        _asgi_middleware_semantic_coverage(case)
        if is_protocol_middleware and not is_gzip
        else _gzip_semantic_coverage(case)
        if is_gzip
        else _semantic_coverage(case)
    )
    unexercised = set(covers) - exercised
    if unexercised:
        raise ContractError(
            f"case claims requirements not exercised by its route, request, and schedule: {sorted(unexercised)}"
        )
    return case


def _validate_asgi_callable_action_sequence(endpoint: Any) -> None:
    endpoint = _exact(endpoint, {"kind", "actions"}, "ASGI callable action-sequence endpoint")
    if endpoint["kind"] != "asgi-callable-action-sequence":
        raise ContractError("ASGI callable endpoint must use the declared action-sequence kind")
    actions = endpoint["actions"]
    if not isinstance(actions, list) or not actions:
        raise ContractError("ASGI callable action sequence must not be empty")

    response_started = False
    response_complete = False
    raised = False
    for index, raw_action in enumerate(actions):
        context = f"ASGI callable action[{index}]"
        if not isinstance(raw_action, dict):
            raise ContractError(f"{context} must be an object")
        action_kind = raw_action.get("action")
        if action_kind == "send":
            action = _exact(raw_action, {"action", "message"}, context)
            if raised or response_complete:
                raise ContractError(f"{context} cannot follow a completed response or exception")
            message = action["message"]
            if not isinstance(message, dict):
                raise ContractError(f"{context}.message must be an object")
            message_type = message.get("type")
            if message_type == "http.response.start":
                message = _exact(
                    message,
                    {"type", "status", "headers_base64_pairs"},
                    f"{context}.message",
                )
                if (
                    response_started
                    or type(message["status"]) is not int
                    or not 100 <= message["status"] <= 599
                ):
                    raise ContractError(f"{context} has a duplicate or invalid response start")
                headers = message["headers_base64_pairs"]
                if not isinstance(headers, list):
                    raise ContractError(f"{context}.message.headers_base64_pairs must be an array")
                for pair_index, pair in enumerate(headers):
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise ContractError(f"{context} response header[{pair_index}] is invalid")
                    try:
                        for value in pair:
                            if not isinstance(value, str):
                                raise ValueError("header values must be base64 strings")
                            base64.b64decode(value, validate=True)
                    except (ValueError, TypeError) as exc:
                        raise ContractError(
                            f"{context} response header[{pair_index}] is invalid base64"
                        ) from exc
                response_started = True
            elif message_type == "http.response.body":
                message = _exact(
                    message,
                    {"type", "body_base64", "more_body"},
                    f"{context}.message",
                )
                if not response_started or not isinstance(message["more_body"], bool):
                    raise ContractError(f"{context} body message is out of sequence")
                try:
                    if not isinstance(message["body_base64"], str):
                        raise ValueError("body must be a base64 string")
                    base64.b64decode(message["body_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{context}.message.body_base64 is invalid") from exc
                response_complete = not message["more_body"]
            else:
                raise ContractError(f"{context} uses an unsupported ASGI response message")
        elif action_kind == "raise-http-exception":
            action = _exact(
                raw_action,
                {"action", "status_code", "detail", "headers"},
                context,
            )
            if index != len(actions) - 1:
                raise ContractError("HTTPException must be the final ASGI callable action")
            if type(action["status_code"]) is not int or not 100 <= action["status_code"] <= 599:
                raise ContractError(f"{context}.status_code is invalid")
            if action["detail"] is not None and not isinstance(action["detail"], str):
                raise ContractError(f"{context}.detail must be a string or null")
            headers = action["headers"]
            if headers is not None:
                if not isinstance(headers, list):
                    raise ContractError(f"{context}.headers must be a string-pair array or null")
                for pair_index, pair in enumerate(headers):
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or any(not isinstance(value, str) for value in pair)
                    ):
                        raise ContractError(f"{context}.headers[{pair_index}] is invalid")
            if response_started and not response_complete:
                raise ContractError("ASGI callable must finish its response body before raising")
            raised = True
        elif action_kind == "raise-runtime-error":
            action = _exact(raw_action, {"action", "message"}, context)
            if index != len(actions) - 1:
                raise ContractError("RuntimeError must be the final ASGI callable action")
            _string(action["message"], f"{context}.message")
            if response_started and not response_complete:
                raise ContractError(
                    "ASGI callable must finish its response body before RuntimeError"
                )
            raised = True
        else:
            raise ContractError(f"{context} has an unsupported action kind")
    if not raised:
        raise ContractError("ASGI callable action sequence must end by raising an exception")


def _is_server_error_stimulus(args: dict[str, Any]) -> bool:
    routes = args.get("routes")
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], dict):
        return False
    endpoint = routes[0].get("endpoint")
    if not isinstance(endpoint, dict):
        return False
    if endpoint.get("kind") == "raise-runtime-error":
        return True
    if endpoint.get("kind") == "asgi-callable-action-sequence":
        return any(
            isinstance(action, dict) and action.get("action") == "raise-runtime-error"
            for action in endpoint.get("actions", [])
        )
    return (
        endpoint.get("kind") == "http-exception"
        and endpoint.get("status_code") == 500
        and any(
            isinstance(entry, dict)
            and entry.get("key") == {"kind": "status-code", "status_code": 500}
            for entry in args.get("exception_handlers", [])
        )
    )


def _validate_server_error_application(args: dict[str, Any]) -> None:
    if type(args["debug"]) is not bool:
        raise ContractError("server-error debug input must be boolean")
    if args["middleware"] != [] or args["max_body_size"] is not None:
        raise ContractError("server-error application uses the declared middleware baseline")
    if args["lifespan"] != {
        "kind": "async-context-manager",
        "record_entry": True,
        "record_exit": True,
    }:
        raise ContractError("server-error application must use the declared lifespan marker")
    if not isinstance(args["routes"], list) or len(args["routes"]) != 1:
        raise ContractError("server-error application must contain one HTTP route")
    route = _exact(args["routes"][0], {"kind", "path", "methods", "endpoint"}, "route input")
    if (
        route["kind"] != "http-route"
        or not isinstance(route["path"], str)
        or not route["path"].startswith("/")
        or route["methods"] != ["GET"]
    ):
        raise ContractError("server-error cases require one absolute-path GET route")
    endpoint = route["endpoint"]
    endpoint_kind = endpoint.get("kind") if isinstance(endpoint, dict) else None
    if endpoint_kind == "raise-runtime-error":
        endpoint = _exact(endpoint, {"kind", "message"}, "RuntimeError endpoint")
        _string(endpoint["message"], "RuntimeError endpoint.message")
    elif endpoint_kind == "asgi-callable-action-sequence":
        _validate_asgi_callable_action_sequence(endpoint)
        if not any(action["action"] == "raise-runtime-error" for action in endpoint["actions"]):
            raise ContractError("server-error callable route must raise RuntimeError")
        if not any(
            action["action"] == "send" and action["message"]["type"] == "http.response.start"
            for action in endpoint["actions"][:-1]
        ):
            raise ContractError("response-started server-error case must send response start first")
    elif endpoint_kind == "http-exception":
        endpoint = _exact(
            endpoint,
            {"kind", "status_code", "detail", "headers"},
            "HTTP exception endpoint input",
        )
        if (
            endpoint["status_code"] != 500
            or (endpoint["detail"] is not None and not isinstance(endpoint["detail"], str))
            or not isinstance(endpoint["headers"], list)
        ):
            raise ContractError("server-error HTTPException case must raise status 500")
        for index, pair in enumerate(endpoint["headers"]):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(not isinstance(value, str) for value in pair)
            ):
                raise ContractError(f"HTTP exception header input[{index}] must be a string pair")
    else:
        raise ContractError("server-error endpoint must raise RuntimeError or HTTPException(500)")

    handlers = args["exception_handlers"]
    if handlers:
        _validate_exception_handler_registry(handlers)
    elif endpoint_kind != "raise-runtime-error" or args["debug"]:
        raise ContractError(
            "an empty exception-handler registry is only valid for the default non-debug RuntimeError response"
        )
    keys = [entry["key"] for entry in handlers]
    has_outer_handler = any(
        key == {"kind": "status-code", "status_code": 500}
        or key == {"kind": "exception-class", "name": "Exception"}
        for key in keys
    )
    if handlers and not has_outer_handler:
        raise ContractError("server-error cases must register a 500 or Exception handler")
    if endpoint_kind == "http-exception":
        if {"kind": "status-code", "status_code": 500} not in keys or {
            "kind": "exception-class",
            "name": "HTTPException",
        } not in keys:
            raise ContractError(
                "handled HTTPException(500) requires distinct outer 500 and inner HTTPException handlers"
            )
    elif any(key == {"kind": "exception-class", "name": "HTTPException"} for key in keys):
        raise ContractError("RuntimeError server-error cases do not use HTTPException handlers")


def _validate_lifespan_marker(marker: Any) -> str:
    if marker == {
        "kind": "async-context-manager",
        "record_entry": True,
        "record_exit": True,
    }:
        return "async-context-manager"
    if not isinstance(marker, dict):
        raise ContractError("lifespan input must use a declared context-manager marker")
    kind = marker.get("kind")
    if kind in {"sync-generator", "async-generator"}:
        required = {
            "kind",
            "record_entry",
            "record_exit",
            "failure_stage",
            "failure_message",
            "yield_behavior",
            "shutdown_exception_behavior",
        }
        optional = {"failure_exception_type", "yield_state"}
        if not required <= marker.keys() or marker.keys() - required - optional:
            raise ContractError("generator lifespan marker has invalid fields")
        if marker["kind"] not in {"sync-generator", "async-generator"}:
            raise ContractError("generator lifespan kind is unsupported")
        if marker["record_entry"] is not True or marker["record_exit"] is not True:
            raise ContractError("generator lifespan must record entry and exit effects")
        if marker["failure_stage"] not in {"none", "startup", "shutdown"}:
            raise ContractError("generator lifespan failure_stage is unsupported")
        _string(marker["failure_message"], "generator lifespan failure_message")
        if marker["yield_behavior"] not in {"none", "single", "extra"}:
            raise ContractError("generator lifespan yield_behavior is unsupported")
        if marker["shutdown_exception_behavior"] not in {"propagate", "suppress"}:
            raise ContractError("generator lifespan shutdown exception behavior is unsupported")
        exception_type = marker.get("failure_exception_type", "RuntimeError")
        if exception_type not in {"RuntimeError", "CancelledError"}:
            raise ContractError("generator lifespan failure exception type is unsupported")
        if exception_type == "CancelledError" and (
            marker["kind"] != "async-generator" or marker["failure_stage"] == "none"
        ):
            raise ContractError("generator cancellation requires an async generator failure")
        if marker.get("yield_state") is not None and not isinstance(marker["yield_state"], dict):
            raise ContractError("generator lifespan yield_state must be an object or null")
        if marker.get("yield_state") is not None and marker["yield_behavior"] == "none":
            raise ContractError("a generator without a yield cannot supply lifespan state")
        return marker["kind"]
    if kind == "async-context-manager-shadowed-specials":
        marker = _exact(
            marker,
            {
                "kind",
                "class_entry_effect",
                "instance_entry_effect",
                "class_exit_effect",
                "instance_exit_effect",
            },
            "shadowed async context-manager marker",
        )
        for name in (
            "class_entry_effect",
            "instance_entry_effect",
            "class_exit_effect",
            "instance_exit_effect",
        ):
            _string(marker[name], f"shadowed async context-manager {name}")
        return marker["kind"]
    raise ContractError("lifespan input must use a declared context-manager marker")


def _validate_lifespan_receive_actions(receive: Any) -> None:
    if not isinstance(receive, list) or len(receive) != 2:
        raise ContractError("lifecycle receive actions must contain two callback outcomes")
    first = _exact(receive[0], {"kind", "message"}, "lifecycle receive action[0]")
    if first["kind"] != "message" or first["message"] != {"type": "lifespan.startup"}:
        raise ContractError("lifecycle receive action[0] must supply lifespan.startup")
    second = receive[1]
    if not isinstance(second, dict):
        raise ContractError("lifecycle receive action[1] must be a record")
    if second.get("kind") == "message":
        second = _exact(second, {"kind", "message"}, "lifecycle receive action[1]")
        if second["message"] != {"type": "lifespan.shutdown"}:
            raise ContractError("lifecycle receive action[1] must supply lifespan.shutdown")
    elif second.get("kind") == "raise":
        second = _exact(
            second,
            {"kind", "exception_type", "message"},
            "lifecycle receive action[1]",
        )
        if second["exception_type"] != "RuntimeError":
            raise ContractError("lifecycle receive callback failure must raise RuntimeError")
        _string(second["message"], "lifecycle receive callback failure message")
    elif second.get("kind") == "await-raise":
        second = _exact(
            second,
            {"kind", "exception_type", "message"},
            "lifecycle receive action[1]",
        )
        if second["exception_type"] != "CancelledError":
            raise ContractError("awaited lifecycle receive failure must cancel the task")
        _string(second["message"], "lifecycle receive cancellation message")
    else:
        raise ContractError("lifecycle receive action[1] must supply shutdown or raise")


def _validate_lifespan_send_callback(send: Any) -> None:
    if send == {"kind": "capture-asgi-send"}:
        return
    send = _exact(
        send,
        {"kind", "message_type", "exception_type", "message"},
        "lifecycle send callback",
    )
    if (
        send["kind"] != "raise-on-call"
        or send["message_type"] != "lifespan.startup.complete"
        or send["exception_type"] != "RuntimeError"
    ):
        raise ContractError("lifecycle send callback failure must target startup.complete")
    _string(send["message"], "lifecycle send callback failure message")


def _lifespan_case_requirement(marker: dict[str, Any], lifecycle_args: dict[str, Any]) -> str:
    kind = _validate_lifespan_marker(marker)
    if kind == "async-context-manager-shadowed-specials":
        return "starlette.asgi.lifespan.async-context-manager-special-method-lookup"
    send = lifecycle_args["send"]
    receive = lifecycle_args["receive"]
    prefix = "sync" if kind == "sync-generator" else "async"
    failure_exception_type = marker.get("failure_exception_type", "RuntimeError")
    if receive[1].get("kind") == "await-raise":
        if kind != "async-generator" or marker["failure_stage"] != "none":
            raise ContractError("shutdown-wait cancellation requires a healthy async generator")
        return "starlette.asgi.lifespan.cancel-during-shutdown-receive"
    if failure_exception_type == "CancelledError":
        if marker["failure_stage"] == "startup":
            return "starlette.asgi.lifespan.cancel-during-entry"
        if marker["failure_stage"] == "shutdown":
            return "starlette.asgi.lifespan.cancel-during-exit"
        raise ContractError("cancellation input must fail during entry or exit")
    if marker.get("yield_state") is not None:
        if "state" in lifecycle_args["scope"]:
            return "starlette.asgi.lifespan.scope-state-merge"
        return "starlette.asgi.lifespan.scope-state-required"
    if marker["yield_behavior"] == "none":
        if (
            marker["failure_stage"] != "none"
            or marker["shutdown_exception_behavior"] != "propagate"
            or send.get("kind") != "capture-asgi-send"
            or receive[1].get("kind") != "message"
        ):
            raise ContractError("a generator without a yield requires normal lifecycle callbacks")
        return f"starlette.asgi.lifespan.{prefix}-generator.no-yield"
    if marker["shutdown_exception_behavior"] == "suppress":
        if (
            marker["failure_stage"] != "none"
            or marker["yield_behavior"] != "single"
            or send.get("kind") != "capture-asgi-send"
            or receive[1].get("kind") != "raise"
        ):
            raise ContractError(
                "shutdown exception suppression requires one shutdown callback error"
            )
        return f"starlette.asgi.lifespan.{prefix}-generator.shutdown-error-suppressed"
    if marker["yield_behavior"] == "extra":
        if (
            marker["failure_stage"] != "none"
            or send.get("kind") != "capture-asgi-send"
            or receive[1].get("kind") != "message"
        ):
            raise ContractError("an extra generator yield requires normal shutdown")
        return f"starlette.asgi.lifespan.{prefix}-generator.extra-yield"
    if send.get("kind") == "raise-on-call":
        return "starlette.asgi.lifespan.startup-send-call-error"
    if receive[1].get("kind") == "raise":
        return "starlette.asgi.lifespan.shutdown-receive-call-error"
    suffix = {
        "none": "success",
        "startup": "startup-failure",
        "shutdown": "shutdown-failure",
    }[marker["failure_stage"]]
    return f"starlette.asgi.lifespan.{prefix}-generator.{suffix}"


def _validate_lifespan_only_case(case: dict[str, Any], app_args: dict[str, Any]) -> None:
    if case["operation"] != "__call__" or case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError(
            "Python lifespan callback cases must target the package __call__ surface"
        )
    if [step["step_id"] for step in case["steps"]] != ["application", "lifecycle"]:
        raise ContractError("lifespan-only workflows must contain application then lifecycle")
    lifecycle_args = {
        key: descriptor["value"] for key, descriptor in case["steps"][1]["arguments"].items()
    }
    marker_kind = _validate_lifespan_marker(app_args["lifespan"])
    if marker_kind not in {
        "sync-generator",
        "async-generator",
        "async-context-manager-shadowed-specials",
    }:
        raise ContractError(
            "lifespan-only workflow requires an explicit generator or special-method marker"
        )
    _validate_lifespan_receive_actions(lifecycle_args["receive"])
    _validate_lifespan_send_callback(lifecycle_args["send"])
    scope = lifecycle_args["scope"]
    if not isinstance(scope, dict) or set(scope) not in (
        {"type", "asgi"},
        {"type", "asgi", "state"},
    ):
        raise ContractError("lifespan scope input has invalid fields")
    if scope["type"] != "lifespan" or scope["asgi"] != {
        "version": "3.0",
        "spec_version": "2.4",
    }:
        raise ContractError("lifespan scope must use the declared ASGI versions")
    if "state" in scope and not isinstance(scope["state"], dict):
        raise ContractError("lifespan scope state must be an object")
    requirement = _lifespan_case_requirement(app_args["lifespan"], lifecycle_args)
    if case["covers"] != [requirement]:
        raise ContractError("lifespan-only input and requirement mapping differ")


def _validate_application_stimulus(
    args: dict[str, Any], request_dispatch: bool, allow_lifespan_variants: bool = False
) -> None:
    if set(args) != {
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
        "max_body_size",
    }:
        raise ContractError(
            "application inputs must explicitly encode each Starlette constructor input"
        )
    if not request_dispatch and _is_server_error_stimulus(args):
        _validate_server_error_application(args)
        return
    if args["debug"] is not False or args["middleware"] != [] or args["max_body_size"] is not None:
        raise ContractError("GET /hello application inputs differ from the declared baseline")
    handlers = args["exception_handlers"]
    if handlers != []:
        _validate_exception_handler_registry(handlers)
    lifespan_kind = _validate_lifespan_marker(args["lifespan"])
    if lifespan_kind != "async-context-manager" and not allow_lifespan_variants:
        raise ContractError(
            "generator and special-method lifespan markers require lifecycle-only input"
        )
    if not isinstance(args["routes"], list) or len(args["routes"]) != 1:
        raise ContractError("application input must contain exactly one route")
    route = args["routes"][0]
    _exact(route, {"kind", "path", "methods", "endpoint"}, "route input")
    if request_dispatch:
        if handlers != []:
            raise ContractError("request-dispatch cases use the empty exception-handler registry")
        if not isinstance(route["path"], str):
            raise ContractError("Request route path must be a string")
        route_parameters = _route_template_parameters(route["path"])
        if (
            route["kind"] != "http-route"
            or not isinstance(route["path"], str)
            or not route["path"].startswith("/")
            or route["methods"] != ["GET"]
            or len(route_parameters) != 1
            or route_parameters[0][1] not in {"str", "int", "float", "uuid", "path"}
        ):
            raise ContractError(
                "Request workflow route must define one GET path parameter with a built-in converter"
            )
        endpoint = route["endpoint"]
        if isinstance(endpoint, dict) and endpoint.get("kind") == "request-observer":
            expected_observer = {
                **REQUEST_OBSERVER_ENDPOINT,
                "path_parameter": route_parameters[0][0],
            }
            if endpoint != expected_observer:
                raise ContractError(
                    "Request observer endpoint input differs from its declared values"
                )
            return
        if isinstance(endpoint, dict) and endpoint.get("kind") == "request-connection-property":
            endpoint = _exact(
                endpoint,
                {"kind", "property"},
                "request connection-property endpoint",
            )
            if endpoint["property"] not in REQUEST_CONNECTION_PROPERTY_REQUIREMENTS:
                raise ContractError(
                    "request connection-property endpoint uses an unsupported property"
                )
            return
        if isinstance(endpoint, dict) and endpoint.get("kind") == "request-stream-observer":
            _validate_request_stream_endpoint(endpoint)
            return
        if isinstance(endpoint, dict) and endpoint.get("kind") == "sync-request-runtime-observer":
            _validate_sync_request_runtime_endpoint(endpoint)
            if route["path"] != "/items/{item_id:int}":
                raise ContractError("sync request runtime input uses the int route boundary")
            return
        if endpoint == ASGI_CALLABLE_INSTANCE_ENDPOINT:
            if route["path"] != "/items/{item_id:int}":
                raise ContractError("ASGI callable-instance input uses the int route boundary")
            return
        if isinstance(endpoint, dict) and endpoint.get("kind") == "asgi-callable-action-sequence":
            if route["path"] != "/items/{item_id:int}":
                raise ContractError("ASGI callable action input uses the int route boundary")
            _validate_asgi_callable_action_sequence(endpoint)
            return
        if not isinstance(endpoint, dict) or endpoint.get("kind") != "sync-request-observer":
            raise ContractError("Request endpoint must use a declared observer input shape")
        _exact(
            endpoint,
            {
                "kind",
                "callable_kind",
                "path_parameter",
                "context_var_name",
                "context_value",
                "response_content",
            },
            "sync endpoint input",
        )
        if (
            endpoint["callable_kind"] not in {"function", "bound_method", "partial"}
            or route["path"] != "/items/{item_id:int}"
            or endpoint["path_parameter"] != "item_id"
            or endpoint["context_var_name"] != "request_context"
            or not isinstance(endpoint["context_value"], str)
            or not endpoint["context_value"]
            or endpoint["response_content"] != "sync ok"
        ):
            raise ContractError("sync endpoint input must use the declared caller-context stimulus")
        return

    if (
        isinstance(route["endpoint"], dict)
        and route["endpoint"].get("kind") == "http-exception-after-body"
    ):
        _validate_body_reuse_application(route, handlers)
        return

    if handlers != []:
        _validate_status_precedence_application(route, handlers)
        return

    if isinstance(route["endpoint"], dict) and route["endpoint"].get("kind") == "http-exception":
        endpoint = _exact(
            route["endpoint"],
            {"kind", "status_code", "detail", "headers"},
            "HTTP exception endpoint input",
        )
        _string(route["path"], "HTTP exception route path")
        if (
            route["kind"] != "http-route"
            or not route["path"].startswith("/")
            or route["methods"] != ["GET"]
        ):
            raise ContractError("HTTP exception routes must select one absolute-path GET")
        if (
            type(endpoint["status_code"]) is not int
            or not 100 <= endpoint["status_code"] <= 599
            or (endpoint["detail"] is not None and not isinstance(endpoint["detail"], str))
            or not isinstance(endpoint["headers"], list)
        ):
            raise ContractError("HTTP exception stimulus has an invalid status, detail, or headers")
        for index, pair in enumerate(endpoint["headers"]):
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or any(not isinstance(value, str) for value in pair)
            ):
                raise ContractError(f"HTTP exception header input[{index}] must be a string pair")
        return

    if route != {
        "kind": "http-route",
        "path": "/hello",
        "methods": ["GET"],
        "endpoint": route["endpoint"],
    }:
        raise ContractError("route input must define GET /hello")
    endpoint = _exact(
        route["endpoint"],
        {"kind", "content", "status_code", "media_type", "cookies"},
        "endpoint input",
    )
    if (
        endpoint["kind"] != "plain-text-response"
        or endpoint["content"] != "hello"
        or endpoint["status_code"] != 200
    ):
        raise ContractError(
            "endpoint input must configure a plain-text response with a status code"
        )
    if endpoint["media_type"] != "text/plain":
        raise ContractError("the declared response media type is text/plain")
    cookies = endpoint["cookies"]
    if not isinstance(cookies, list) or len(cookies) != 2:
        raise ContractError(
            "the duplicate-header stimulus must use exactly two public Response.set_cookie calls"
        )
    expected_cookies = [{"key": "first", "value": "one"}, {"key": "second", "value": "two"}]
    if cookies != expected_cookies:
        raise ContractError("cookie inputs must be the two declared public set_cookie calls")
    for index, cookie in enumerate(cookies):
        _exact(cookie, {"key", "value"}, f"cookie input[{index}]")
        _string(cookie["key"], f"cookie input[{index}].key")
        _string(cookie["value"], f"cookie input[{index}].value")


def _validate_exception_handler_registry(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ContractError("non-empty exception-handler registry must be an ordered entry array")
    seen: set[tuple[str, str | int]] = set()
    for index, raw_entry in enumerate(value):
        context = f"exception_handlers[{index}]"
        entry = _exact(raw_entry, {"key", "handler"}, context)
        key = entry["key"]
        if not isinstance(key, dict) or key.get("kind") not in {"status-code", "exception-class"}:
            raise ContractError(f"{context}.key must use a declared tagged handler key")
        if key["kind"] == "status-code":
            _exact(key, {"kind", "status_code"}, f"{context}.key")
            status_code = key["status_code"]
            if type(status_code) is not int or not 100 <= status_code <= 599:
                raise ContractError(f"{context}.key.status_code must be an HTTP status code")
            identity: tuple[str, str | int] = ("status-code", status_code)
        else:
            name = key.get("name")
            if name == "HTTPException":
                _exact(key, {"kind", "name"}, f"{context}.key")
            elif name == "Exception":
                _exact(key, {"kind", "name"}, f"{context}.key")
            elif name == "BodyReuseException":
                _exact(key, {"kind", "name", "base_class"}, f"{context}.key")
                if key["base_class"] != "HTTPException":
                    raise ContractError("BodyReuseException must derive from HTTPException")
            else:
                raise ContractError(f"{context}.key names an unsupported exception class")
            identity = ("exception-class", name)
        if identity in seen:
            raise ContractError("exception-handler registry must not repeat a typed key")
        seen.add(identity)
        _validate_exception_handler_recipe(entry["handler"], f"{context}.handler")


def _validate_exception_handler_recipe(value: Any, context: str) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise ContractError(f"{context} must use a declared handler recipe")
    kind = value["kind"]
    if kind == "json-exception-detail-response":
        _exact(value, {"kind", "status_from_exception"}, context)
        if value["status_from_exception"] is not True:
            raise ContractError(f"{context} must use the HTTPException status")
    elif kind == "json-literal-response":
        _exact(value, {"kind", "status_code", "content"}, context)
        if type(value["status_code"]) is not int or not 100 <= value["status_code"] <= 599:
            raise ContractError(f"{context}.status_code must be an HTTP status code")
        if not isinstance(value["content"], dict):
            raise ContractError(f"{context}.content must be a JSON object")
    elif kind == "request-body-json-response":
        _exact(value, {"kind", "body_field", "status_from_exception"}, context)
        _string(value["body_field"], f"{context}.body_field")
        if value["status_from_exception"] is not True:
            raise ContractError(f"{context} must use the HTTPException status")
    elif kind == "server-error-response":
        _exact(value, {"kind", "label", "status_code", "content"}, context)
        _string(value["label"], f"{context}.label")
        _string(value["content"], f"{context}.content")
        if value["status_code"] != 500:
            raise ContractError(f"{context}.status_code must be 500")
    else:
        raise ContractError(f"{context} uses an unsupported handler recipe: {kind!r}")


def _validate_status_precedence_application(route: dict[str, Any], handlers: Any) -> None:
    if (
        route["kind"] != "http-route"
        or not isinstance(route["path"], str)
        or not route["path"].startswith("/")
        or route["methods"] != ["GET"]
    ):
        raise ContractError("status-code precedence requires one absolute-path GET route")
    endpoint = route["endpoint"]
    if (
        not isinstance(endpoint, dict)
        or endpoint.get("kind") != "plain-text-response"
        or set(endpoint) != {"kind", "content", "status_code", "media_type", "cookies"}
        or not isinstance(endpoint["content"], str)
        or type(endpoint["status_code"]) is not int
        or endpoint["media_type"] != "text/plain"
        or endpoint["cookies"] != []
    ):
        raise ContractError("status-code precedence route must use a plain-text endpoint")
    if len(handlers) != 2:
        raise ContractError("status-code precedence must configure two ordered handlers")
    first, second = handlers
    if (
        first["key"] != {"kind": "exception-class", "name": "HTTPException"}
        or first["handler"]
        != {
            "kind": "json-exception-detail-response",
            "status_from_exception": True,
        }
        or second["key"] != {"kind": "status-code", "status_code": 405}
        or second["handler"].get("kind") != "json-literal-response"
        or second["handler"].get("status_code") != 405
    ):
        raise ContractError("status-code precedence must put the HTTPException class handler first")


def _validate_body_reuse_application(route: dict[str, Any], handlers: Any) -> None:
    endpoint = _exact(
        route["endpoint"],
        {"kind", "exception_class", "status_code", "detail"},
        "body-reuse endpoint",
    )
    if (
        route["kind"] != "http-route"
        or not isinstance(route["path"], str)
        or not route["path"].startswith("/")
        or route["methods"] != ["POST"]
        or endpoint["kind"] != "http-exception-after-body"
        or endpoint["exception_class"] != "BodyReuseException"
        or type(endpoint["status_code"]) is not int
        or not 100 <= endpoint["status_code"] <= 599
        or (endpoint["detail"] is not None and not isinstance(endpoint["detail"], str))
    ):
        raise ContractError(
            "body-reuse endpoint must read the request body then raise its declared subclass"
        )
    expected_key = {
        "kind": "exception-class",
        "name": "BodyReuseException",
        "base_class": "HTTPException",
    }
    if (
        len(handlers) != 1
        or handlers[0]["key"] != expected_key
        or handlers[0]["handler"].get("kind") != "request-body-json-response"
        or handlers[0]["handler"].get("body_field") != "body"
    ):
        raise ContractError("body-reuse requires the declared subclass handler to read cached body")


def _validate_dispatch_stimulus(
    args: dict[str, Any],
    request_dispatch: bool,
    allow_nonempty_body: bool = False,
    allow_headers: bool = False,
    allow_root_path: bool = False,
    allow_query: bool = False,
    allow_oserror_send: bool = False,
    allow_host: bool = False,
    allow_lifespan_callback_failures: bool = False,
    allow_inherited_mount_scope: bool = False,
) -> None:
    if set(args) != {"scope", "receive", "send"}:
        raise ContractError(
            "dispatch must explicitly supply the ASGI scope, receive messages, and send collector"
        )
    scope = args["scope"]
    if not isinstance(scope, dict):
        raise ContractError("scope input must be an object")
    if scope.get("type") == "lifespan":
        scope_fields = {"type", "asgi"}
        if allow_lifespan_callback_failures and "state" in scope:
            scope_fields.add("state")
        _exact(scope, scope_fields, "lifespan scope input")
        if scope["asgi"] != {"version": "3.0", "spec_version": "2.4"}:
            raise ContractError("lifespan scope must use the declared ASGI versions")
        if "state" in scope and not isinstance(scope["state"], dict):
            raise ContractError("lifespan scope state must be an object")
        if allow_lifespan_callback_failures:
            _validate_lifespan_receive_actions(args["receive"])
            _validate_lifespan_send_callback(args["send"])
        elif args["receive"] != [
            {"type": "lifespan.startup"},
            {"type": "lifespan.shutdown"},
        ]:
            raise ContractError("lifespan input must include startup followed by shutdown")
        elif args["send"] != {"kind": "capture-asgi-send"}:
            raise ContractError("send input must contain the fixed ASGI capture selector")
    elif scope.get("type") == "http":
        scope_fields = {
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        }
        if allow_inherited_mount_scope:
            scope_fields.update(key for key in ("app_root_path", "path_params") if key in scope)
        scope = _exact(scope, scope_fields, "HTTP scope input")
        if "app_root_path" in scope:
            _string(scope["app_root_path"], "HTTP scope.app_root_path")
        if "path_params" in scope:
            path_params = scope["path_params"]
            if not isinstance(path_params, dict) or any(
                not isinstance(name, str) or not name or type(value) not in (str, int, float)
                for name, value in path_params.items()
            ):
                raise ContractError(
                    "HTTP scope.path_params must map non-empty names to strings or numbers"
                )
        _string(scope["method"], "HTTP scope.method")
        path = _string(scope["path"], "HTTP scope.path")
        if scope["raw_path_base64"] != base64.b64encode(path.encode("ascii")).decode("ascii"):
            raise ContractError("raw_path bytes must match the declared path")
        if (
            scope["asgi"] != {"version": "3.0", "spec_version": "2.4"}
            or scope["http_version"] != "1.1"
        ):
            raise ContractError("HTTP scope must use the declared ASGI and HTTP versions")
        if (
            scope["scheme"] not in ({"http", "https"} if allow_host else {"http"})
            or (not allow_root_path and scope["root_path"] != "")
            or not isinstance(scope["root_path"], str)
        ):
            raise ContractError("HTTP scope differs from the declared direct-ASGI baseline")
        if scope["client"] != ["127.0.0.1", 12345] or (
            not allow_host and scope["server"] != ["testserver", 80]
        ):
            raise ContractError("HTTP scope client/server differ from the declared baseline")
        if allow_host and (
            not isinstance(scope["server"], list)
            or len(scope["server"]) != 2
            or not isinstance(scope["server"][0], str)
            or type(scope["server"][1]) is not int
            or not 1 <= scope["server"][1] <= 65535
        ):
            raise ContractError("HTTP scope server is invalid for Host route dispatch")
        if not request_dispatch and not allow_query and scope["query_string_base64"] != "":
            raise ContractError("HTTP scope query value differs from the declared baseline")
        if not request_dispatch and not allow_headers and scope["headers_base64_pairs"] != []:
            raise ContractError("HTTP scope header values differ from the declared baseline")
        for key in ("raw_path_base64", "query_string_base64"):
            try:
                base64.b64decode(scope[key], validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError(f"scope.{key} is invalid base64") from exc
        if not isinstance(scope["headers_base64_pairs"], list):
            raise ContractError("scope.headers_base64_pairs must be an array")
        for pair in scope["headers_base64_pairs"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ContractError("each ASGI header input must be a two-item array")
            for value in pair:
                try:
                    base64.b64decode(value, validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError("ASGI header input contains invalid base64") from exc
        if not isinstance(args["receive"], list):
            raise ContractError("HTTP request input must be a list of request events")
        for message in args["receive"]:
            _exact(message, {"type", "body_base64", "more_body"}, "HTTP request message")
            if message["type"] != "http.request" or not isinstance(message["more_body"], bool):
                raise ContractError(
                    "HTTP request messages must be http.request records with a boolean more_body"
                )
            try:
                base64.b64decode(message["body_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError("HTTP request body must be valid base64") from exc
        if (
            not request_dispatch
            and not allow_nonempty_body
            and args["receive"] != [{"type": "http.request", "body_base64": "", "more_body": False}]
        ):
            raise ContractError("legacy HTTP inputs must contain one empty request event")
        if allow_nonempty_body:
            messages = args["receive"]
            if (
                len(messages) < 2
                or not all(message["more_body"] for message in messages[:-1])
                or messages[-1]["more_body"]
                or not b"".join(
                    base64.b64decode(message["body_base64"], validate=True) for message in messages
                )
            ):
                raise ContractError(
                    "body-reuse input must contain a non-empty chunked request body"
                )
    else:
        raise ContractError("scope type must be http or lifespan")
    if args["send"] != {"kind": "capture-asgi-send"}:
        if allow_lifespan_callback_failures and scope.get("type") == "lifespan":
            return
        if not allow_oserror_send:
            raise ContractError("send input must contain the fixed ASGI capture selector")
        send = _exact(
            args["send"],
            {"kind", "event_index", "message"},
            "ASGI OSError send input",
        )
        if (
            send["kind"] != "capture-asgi-send-until-oserror"
            or type(send["event_index"]) is not int
            or send["event_index"] < 0
            or not isinstance(send["message"], str)
        ):
            raise ContractError("ASGI OSError send input is invalid")


def _validate_exception_handler_dispatch(
    app_arguments: dict[str, Any], dispatch_arguments: dict[str, Any]
) -> None:
    route = app_arguments["routes"][0]
    scope = dispatch_arguments["scope"]
    endpoint = route["endpoint"]
    if scope.get("type") != "http" or scope["path"] != route["path"]:
        raise ContractError("exception-handler input must dispatch to its declared route path")
    if _is_server_error_stimulus(app_arguments):
        if scope["method"] != "GET" or route["methods"] != ["GET"]:
            raise ContractError("server-error inputs must dispatch their declared GET route")
        raw_headers = [
            (
                base64.b64decode(name, validate=True).lower(),
                base64.b64decode(value, validate=True),
            )
            for name, value in scope["headers_base64_pairs"]
        ]
        if app_arguments["debug"]:
            if len(raw_headers) != 1 or raw_headers[0][0] != b"accept":
                raise ContractError("debug traceback cases must declare one Accept header")
            if raw_headers[0][1] not in {b"application/json", b"text/html"}:
                raise ContractError(
                    "debug traceback Accept must select the declared text or HTML path"
                )
        elif raw_headers:
            raise ContractError("non-debug server-error cases must omit Accept headers")
        return
    if endpoint.get("kind") == "http-exception-after-body":
        if scope["method"] != "POST":
            raise ContractError("body-reuse input must dispatch a POST request")
    elif scope["method"] != "POST" or route["methods"] != ["GET"]:
        raise ContractError("status-code precedence input must POST to its GET-only route")


def _gzip_header_pairs(value: Any, context: str) -> list[tuple[bytes, bytes]]:
    if not isinstance(value, list):
        raise ContractError(f"{context} must be an array")
    decoded: list[tuple[bytes, bytes]] = []
    for index, pair in enumerate(value):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ContractError(f"{context}[{index}] must be a two-item byte pair")
        try:
            name = base64.b64decode(pair[0], validate=True)
            header_value = base64.b64decode(pair[1], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"{context}[{index}] contains invalid base64") from exc
        if not name:
            raise ContractError(f"{context}[{index}] has an empty header name")
        decoded.append((name, header_value))
    return decoded


def _validate_body_limit_action_sequence(value: Any, context: str, depth: int = 0) -> None:
    if depth > 8:
        raise ContractError(f"{context} exceeds the declared nested middleware depth")
    if not isinstance(value, list) or not value:
        raise ContractError(f"{context} must be a non-empty action sequence")
    for index, raw_action in enumerate(value):
        action_context = f"{context}[{index}]"
        if not isinstance(raw_action, dict) or not isinstance(raw_action.get("action"), str):
            raise ContractError(f"{action_context} must declare an action")
        kind = raw_action["action"]
        if kind in {"receive", "observe-scope"}:
            _exact(raw_action, {"action"}, action_context)
        elif kind == "send":
            action = _exact(raw_action, {"action", "message"}, action_context)
            message = action["message"]
            if not isinstance(message, dict) or message.get("type") not in {
                "http.response.start",
                "http.response.body",
            }:
                raise ContractError(f"{action_context}.message has an unsupported ASGI type")
            if message["type"] == "http.response.start":
                message = _exact(
                    message,
                    {"type", "status", "headers_base64_pairs"},
                    f"{action_context}.message",
                )
                if type(message["status"]) is not int or not 100 <= message["status"] <= 599:
                    raise ContractError(f"{action_context}.message.status is invalid")
                _gzip_header_pairs(
                    message["headers_base64_pairs"], f"{action_context}.message.headers"
                )
            else:
                message = _exact(
                    message,
                    {"type", "body_base64", "more_body"},
                    f"{action_context}.message",
                )
                if not isinstance(message["more_body"], bool):
                    raise ContractError(f"{action_context}.message.more_body must be boolean")
                try:
                    base64.b64decode(message["body_base64"], validate=True)
                except (ValueError, TypeError) as exc:
                    raise ContractError(f"{action_context}.message.body_base64 is invalid") from exc
        elif kind == "raise-http-exception":
            action = _exact(
                raw_action,
                {"action", "status_code", "detail", "headers"},
                action_context,
            )
            if type(action["status_code"]) is not int or not 100 <= action["status_code"] <= 599:
                raise ContractError(f"{action_context}.status_code is invalid")
            if action["detail"] is not None and not isinstance(action["detail"], str):
                raise ContractError(f"{action_context}.detail must be a string or null")
            if action["headers"] is not None and not isinstance(action["headers"], list):
                raise ContractError(f"{action_context}.headers must be null or an array")
        elif kind == "raise-runtime-error":
            action = _exact(raw_action, {"action", "message"}, action_context)
            _string(action["message"], f"{action_context}.message")
        elif kind == "nested":
            action = _exact(
                raw_action,
                {"action", "max_body_size", "actions"},
                action_context,
            )
            limit = action["max_body_size"]
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise ContractError(f"{action_context}.max_body_size must be non-negative")
            _validate_body_limit_action_sequence(
                action["actions"], f"{action_context}.actions", depth + 1
            )
        else:
            raise ContractError(f"{action_context}.action is unsupported")


def _validate_default_receive_case(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("default receive parity currently targets the Python package profile")
    if case["assets"] != [] or case["observations"] != ["receive"]:
        raise ContractError("default receive cases must select receive without external assets")
    if not isinstance(case["scope"], dict):
        raise ContractError("default receive scope must be a record")
    _validate_dispatch_stimulus(
        {
            "scope": case["scope"],
            "receive": [],
            "send": {"kind": "capture-asgi-send"},
        },
        request_dispatch=True,
    )
    if case["scope"]["type"] != "http":
        raise ContractError("Request default-receive input must use an HTTP scope")
    if case["covers"] != ["starlette.request.default-empty-receive-runtime-error"]:
        raise ContractError("default receive case must cover its declared runtime-error behavior")


def _validate_status_symbols_case(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("status module parity currently targets the Python package profile")
    if case["assets"] != []:
        raise ContractError("status module parity does not use external assets")
    observations = [
        "public_names",
        "public_values",
        "deprecated_values_and_warnings",
        "directory",
        "missing_attribute",
    ]
    if case["observations"] != observations:
        raise ContractError("status module parity must select every declared observation")
    public_names = case["public_names"]
    deprecated_names = case["deprecated_names"]
    missing_names = case["missing_names"]
    for label, names in (
        ("public_names", public_names),
        ("deprecated_names", deprecated_names),
        ("missing_names", missing_names),
    ):
        if (
            not isinstance(names, list)
            or any(not isinstance(name, str) or not name.isidentifier() for name in names)
            or len(names) != len(set(names))
        ):
            raise ContractError(f"status {label} must be a unique array of identifiers")
    if not public_names:
        raise ContractError("status module parity must request public names")
    if type(case["observe_directory"]) is not bool:
        raise ContractError("status observe_directory must be boolean")
    exercised = {"starlette.status.module-symbol-sequence.public-integer-constants"}
    if deprecated_names:
        exercised.add("starlette.status.module-symbol-sequence.deprecated-aliases")
    if missing_names:
        exercised.add("starlette.status.module-symbol-sequence.unknown-attribute")
    if case["observe_directory"]:
        exercised.add("starlette.status.module-symbol-sequence.directory-listing")
    if set(case["covers"]) != exercised:
        raise ContractError("status module coverage must match the requested input behaviors")


def _validate_config_case(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("configuration parity currently targets the Python package profile")
    if case["assets"] != []:
        raise ContractError("configuration parity does not use external assets")

    operation = (case["surface"], case["operation"])
    if operation == ("starlette.config.Config", "value-resolution"):
        if case["observations"] != ["lookup-results"]:
            raise ContractError("Config value resolution must select lookup-results")
        config = _exact(case["config"], {"env_prefix", "environ", "env_file_lines"}, "Config input")
        if not isinstance(config["env_prefix"], str):
            raise ContractError("Config env_prefix must be a string")
        environ = config["environ"]
        if not isinstance(environ, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in environ.items()
        ):
            raise ContractError("Config environ must be a string mapping")
        lines = config["env_file_lines"]
        if not isinstance(lines, list) or any(not isinstance(line, str) for line in lines):
            raise ContractError("Config env_file_lines must be a string array")
        lookups = case["lookups"]
        if not isinstance(lookups, list) or not lookups:
            raise ContractError("Config lookups must be a non-empty array")
        file_values = {}
        for line in lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, value = stripped.split("=", 1)
                file_values[key.strip()] = value.strip().strip("\"'")
        selected: set[str] = set()
        for index, raw in enumerate(lookups):
            if not isinstance(raw, dict):
                raise ContractError(f"Config lookups[{index}] must be an object")
            lookup = _exact(
                raw,
                {"key", "cast", "default"}
                if "cast" in raw and "default" in raw
                else {"key", "cast"}
                if "cast" in raw
                else {"key", "default"}
                if "default" in raw
                else {"key"},
                f"Config lookups[{index}]",
            )
            key = _string(lookup["key"], f"Config lookups[{index}].key")
            cast = lookup.get("cast")
            if cast is not None and cast not in {"str", "bool", "int"}:
                raise ContractError(f"Config lookups[{index}].cast is unsupported")
            prefixed = config["env_prefix"] + key
            has_default = "default" in lookup
            if prefixed in environ and prefixed in file_values:
                selected.add("starlette.config.Config.environment-precedence")
            if prefixed in file_values:
                selected.add("starlette.config.Config.file-precedence")
            if has_default:
                selected.add("starlette.config.Config.default-values")
            elif prefixed not in environ and prefixed not in file_values:
                selected.add("starlette.config.Config.missing-key-error")
            if config["env_prefix"]:
                selected.add("starlette.config.Config.env-prefix")
            raw_value = environ.get(prefixed, file_values.get(prefixed))
            if cast == "bool" and raw_value is not None:
                selected.add("starlette.config.Config.bool-cast")
                if raw_value.lower() not in {"true", "1", "false", "0"}:
                    selected.add("starlette.config.Config.invalid-bool-error")
            if cast == "int" and raw_value is not None:
                try:
                    int(raw_value)
                except ValueError:
                    selected.add("starlette.config.Config.cast-error")
        if set(case["covers"]) != selected:
            raise ContractError("Config value-resolution coverage must match its input lookups")
        return

    if operation == ("starlette.config.Config", "constructor-warning"):
        if case["observations"] != ["warning-results"]:
            raise ContractError("Config constructor must select warning-results")
        env_file = _exact(case["env_file"], {"kind", "file_name"}, "Config env_file")
        if env_file["kind"] != "missing-temporary-file":
            raise ContractError("Config warning input must identify a missing temporary file")
        _string(env_file["file_name"], "Config env_file.file_name")
        if case["covers"] != ["starlette.config.Config.missing-file-warning"]:
            raise ContractError("Config constructor coverage must match its warning input")
        return

    if operation != ("starlette.config.Environ", "mapping-sequence"):
        raise ContractError("configuration case uses an undeclared operation")
    if case["observations"] != ["action-results"]:
        raise ContractError("Environ mapping sequence must select action-results")
    initial = case["initial_environ"]
    if not isinstance(initial, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in initial.items()
    ):
        raise ContractError("Environ initial_environ must be a string mapping")
    actions = case["actions"]
    if not isinstance(actions, list) or not actions:
        raise ContractError("Environ actions must be a non-empty array")
    selected = set()
    read_keys: set[str] = set()
    present_keys = set(initial)
    for index, raw in enumerate(actions):
        context = f"Environ actions[{index}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("action"), str):
            raise ContractError(f"{context} must be an action object")
        action = raw["action"]
        if action in {"set", "delete", "get", "contains"}:
            expected = {"action", "key", "value"} if action == "set" else {"action", "key"}
            item = _exact(raw, expected, context)
            key = _string(item["key"], f"{context}.key")
            if action == "set":
                if not isinstance(item["value"], str):
                    raise ContractError(f"{context}.value must be a string")
                if key not in read_keys:
                    selected.add("starlette.config.Environ.set-before-read")
                else:
                    selected.add("starlette.config.Environ.read-freezes-set")
                present_keys.add(key)
            elif action == "delete":
                if key not in read_keys:
                    selected.add("starlette.config.Environ.delete-before-read")
                    present_keys.discard(key)
                else:
                    selected.add("starlette.config.Environ.read-freezes-delete")
            else:
                if action == "get":
                    selected.add("starlette.config.Environ.read-value")
                elif key not in present_keys:
                    selected.add("starlette.config.Environ.missing-key-membership-freezes-key")
                read_keys.add(key)
        elif action == "iterate":
            _exact(raw, {"action"}, context)
            selected.add("starlette.config.Environ.iteration")
        elif action == "length":
            _exact(raw, {"action"}, context)
            selected.add("starlette.config.Environ.length")
        else:
            raise ContractError(f"{context}.action is unsupported")
    if set(case["covers"]) != selected:
        raise ContractError("Environ mapping coverage must match its action sequence")


def _validate_schema_route_input(route: Any, context: str) -> tuple[set[str], bool]:
    if not isinstance(route, dict) or not isinstance(route.get("kind"), str):
        raise ContractError(f"{context} must be a route object")
    kind = route["kind"]
    if kind in {"route", "websocket-route"}:
        allowed = {"kind", "path", "endpoint"}
        if kind == "route":
            allowed |= {key for key in ("methods", "include_in_schema") if key in route}
        item = _exact(route, allowed, context)
        _string(item["path"], f"{context}.path")
        endpoint = item["endpoint"]
        if not isinstance(endpoint, dict) or endpoint.get("kind") not in {"function", "class"}:
            raise ContractError(f"{context}.endpoint must describe a function or class")
        if endpoint["kind"] == "function":
            endpoint = _exact(endpoint, {"kind", "docstring"}, f"{context}.endpoint")
            _string(endpoint["docstring"], f"{context}.endpoint.docstring")
            handler_count = 1
        else:
            endpoint = _exact(endpoint, {"kind", "handlers"}, f"{context}.endpoint")
            handlers = endpoint["handlers"]
            if (
                not isinstance(handlers, dict)
                or not handlers
                or any(
                    not isinstance(name, str)
                    or not name.isidentifier()
                    or not isinstance(docstring, str)
                    for name, docstring in handlers.items()
                )
            ):
                raise ContractError(f"{context}.endpoint.handlers must map names to docstrings")
            handler_count = len(handlers)
        if kind == "route":
            if "methods" in item and (
                not isinstance(item["methods"], list)
                or any(not isinstance(method, str) for method in item["methods"])
            ):
                raise ContractError(f"{context}.methods must be a string array")
            if "include_in_schema" in item and type(item["include_in_schema"]) is not bool:
                raise ContractError(f"{context}.include_in_schema must be boolean")
        selected: set[str] = set()
        if kind == "route":
            selected.add("starlette.schemas.BaseSchemaGenerator.get_endpoints")
            if item.get("include_in_schema", True):
                selected.add("starlette.schemas.BaseSchemaGenerator.parse_docstring")
            if ":" in item["path"]:
                selected.add("starlette.schemas.BaseSchemaGenerator._remove_converter")
        return selected, handler_count > 0
    if kind in {"mount", "host"}:
        allowed = {"kind", "routes", "path" if kind == "mount" else "host"}
        item = _exact(route, allowed, context)
        _string(item["path" if kind == "mount" else "host"], f"{context}.{kind}")
        nested_routes = item["routes"]
        if not isinstance(nested_routes, list):
            raise ContractError(f"{context}.routes must be an array")
        selected: set[str] = {"starlette.schemas.BaseSchemaGenerator.get_endpoints"}
        has_child = False
        for index, child in enumerate(nested_routes):
            child_selected, child_present = _validate_schema_route_input(
                child, f"{context}.routes[{index}]"
            )
            selected |= child_selected
            has_child |= child_present
        if kind == "mount":
            selected.add("starlette.schemas.BaseSchemaGenerator._remove_converter")
        return selected, has_child
    raise ContractError(f"{context}.kind is unsupported")


def _validate_schema_case(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("schema parity currently targets the Python package profile")
    if case["assets"] != []:
        raise ContractError("schema parity does not use external assets")

    operation = (case["surface"], case["operation"])
    if operation == ("starlette.schemas.SchemaGenerator", "schema-generation"):
        if case["observations"] != ["endpoints", "schema"]:
            raise ContractError("SchemaGenerator must select endpoints and schema")
        if not isinstance(case["base_schema"], dict) or not isinstance(case["routes"], list):
            raise ContractError("SchemaGenerator base_schema and routes must be records and arrays")
        selected: set[str] = {"starlette.schemas.SchemaGenerator.get_schema"}
        has_route = False
        has_converter = False
        has_mount = False
        has_host = False
        has_head_only = False
        has_excluded = False
        has_class_endpoint = False
        for index, route in enumerate(case["routes"]):
            route_selected, route_present = _validate_schema_route_input(
                route, f"SchemaGenerator routes[{index}]"
            )
            selected |= route_selected
            has_route |= route_present
            has_mount |= route.get("kind") == "mount"
            has_host |= route.get("kind") == "host"
            if route.get("kind") == "route":
                has_head_only |= route.get("methods") == ["HEAD"]
                has_excluded |= route.get("include_in_schema") is False
                endpoint = route.get("endpoint", {})
                has_class_endpoint |= endpoint.get("kind") == "class"
                has_converter |= ":" in route.get("path", "")
        required = {
            "starlette.schemas.SchemaGenerator.get_schema",
            "starlette.schemas.BaseSchemaGenerator.get_endpoints",
            "starlette.schemas.BaseSchemaGenerator._remove_converter",
            "starlette.schemas.BaseSchemaGenerator.parse_docstring",
        }
        if selected != required or not all(
            [
                has_route,
                has_converter,
                has_mount,
                has_host,
                has_head_only,
                has_excluded,
                has_class_endpoint,
            ]
        ):
            raise ContractError("SchemaGenerator input does not exercise its declared route rules")
        expected = {"starlette.schemas.SchemaGenerator.get_schema"}
        expected |= {
            "starlette.schemas.BaseSchemaGenerator.get_endpoints",
            "starlette.schemas.BaseSchemaGenerator._remove_converter",
            "starlette.schemas.BaseSchemaGenerator.parse_docstring.mapping",
            "starlette.schemas.BaseSchemaGenerator.parse_docstring.delimited-section",
        }
        if set(case["covers"]) != expected:
            raise ContractError("SchemaGenerator coverage must match its route input")
        return

    if operation == ("starlette.schemas.BaseSchemaGenerator", "schema-docstring-parsing"):
        if case["observations"] != ["parsed-docstrings", "exception"]:
            raise ContractError("docstring parsing must select parsed-docstrings and exception")
        docstrings = case["docstrings"]
        if (
            not isinstance(docstrings, list)
            or not docstrings
            or any(not isinstance(docstring, str) for docstring in docstrings)
        ):
            raise ContractError("docstring parsing input must be a non-empty string array")
        malformed = any("[unterminated" in docstring for docstring in docstrings)
        if malformed:
            if len(docstrings) != 1 or case["covers"] != [
                "starlette.schemas.BaseSchemaGenerator.parse_docstring.malformed-yaml"
            ]:
                raise ContractError("malformed YAML input must isolate its parser error")
        else:
            if not any("responses:" in docstring for docstring in docstrings):
                raise ContractError("docstring parsing input must include a YAML mapping")
            if not any("---" in docstring for docstring in docstrings):
                raise ContractError("docstring parsing input must include a schema delimiter")
            if not any(not docstring.strip() for docstring in docstrings):
                raise ContractError("docstring parsing input must include empty prose")
            if not any(
                docstring.startswith("-") or docstring.strip() == "null" for docstring in docstrings
            ):
                raise ContractError("docstring parsing input must include a non-mapping YAML value")
            if set(case["covers"]) != {
                "starlette.schemas.BaseSchemaGenerator.parse_docstring.mapping",
                "starlette.schemas.BaseSchemaGenerator.parse_docstring.delimited-section",
                "starlette.schemas.BaseSchemaGenerator.parse_docstring.non-mapping-filter",
            }:
                raise ContractError("docstring parsing coverage must match its input examples")
        return

    if operation != ("starlette.schemas.OpenAPIResponse", "openapi-response-render"):
        raise ContractError("schema case uses an undeclared operation")
    if case["observations"] != ["media-type", "rendered-bytes"]:
        raise ContractError("OpenAPIResponse must select media-type and rendered-bytes")
    if not isinstance(case["content"], dict):
        raise ContractError("OpenAPIResponse content must be a mapping")
    if set(case["covers"]) != {
        "starlette.schemas.OpenAPIResponse.render",
        "starlette.schemas.BaseSchemaGenerator.OpenAPIResponse",
    }:
        raise ContractError("OpenAPIResponse coverage must match render and generator response")


def _validate_value_formatting_case(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("value-formatting parity currently targets the Python package profile")
    if case["assets"] != []:
        raise ContractError("value-formatting cases do not use external assets")

    if case["surface"] == EXCEPTION_VALUES_SURFACE:
        if case["observations"] != [VALUE_FORMATTING_OPERATION]:
            raise ContractError("exception value-formatting must select its declared observation")
        instances = case["instances"]
        if not isinstance(instances, list) or not instances:
            raise ContractError("exception value-formatting requires at least one input instance")
        exercised: set[str] = set()
        for index, item in enumerate(instances):
            context = f"exception value-formatting instances[{index}]"
            item = _exact(item, {"kind", "subclass_name", "arguments", "mutations"}, context)
            kind = item["kind"]
            subclass_name = item["subclass_name"]
            if subclass_name is not None and (
                not isinstance(subclass_name, str) or not subclass_name.isidentifier()
            ):
                raise ContractError(f"{context}.subclass_name must be null or an identifier")
            mutations = item["mutations"]
            if not isinstance(mutations, list):
                raise ContractError(f"{context}.mutations must be an array")
            arguments = item["arguments"]
            if kind == "http":
                arguments = _exact(
                    arguments,
                    {"status_code", "detail", "headers"},
                    f"{context}.arguments",
                )
                status_code = arguments["status_code"]
                if not isinstance(status_code, int) or isinstance(status_code, bool):
                    raise ContractError(f"{context}.status_code must be an integer")
                headers = arguments["headers"]
                if headers is not None and (
                    not isinstance(headers, dict)
                    or any(
                        not isinstance(name, str) or not isinstance(value, str)
                        for name, value in headers.items()
                    )
                ):
                    raise ContractError(f"{context}.headers must be null or a string mapping")
                try:
                    HTTPStatus(status_code)
                except ValueError:
                    if arguments["detail"] is None:
                        exercised.add("starlette.exception-values.http-invalid-status")
                else:
                    if arguments["detail"] is None:
                        exercised.add("starlette.exception-values.http-default-detail")
                allowed_fields = {"status_code", "detail", "headers"}
                if subclass_name is not None and mutations:
                    exercised.add("starlette.exception-values.http-subclass-mutable-fields")
            elif kind == "websocket":
                arguments = _exact(arguments, {"code", "reason"}, f"{context}.arguments")
                code = arguments["code"]
                if not isinstance(code, int) or isinstance(code, bool):
                    raise ContractError(f"{context}.code must be an integer")
                if not arguments["reason"]:
                    exercised.add("starlette.exception-values.websocket-reason-default")
                allowed_fields = {"code", "reason"}
                if subclass_name is not None and mutations:
                    exercised.add("starlette.exception-values.websocket-subclass-mutable-fields")
            else:
                raise ContractError(f"{context}.kind must be http or websocket")
            for mutation_index, mutation in enumerate(mutations):
                mutation = _exact(
                    mutation,
                    {"field", "value"},
                    f"{context}.mutations[{mutation_index}]",
                )
                if mutation["field"] not in allowed_fields:
                    raise ContractError(f"{context} mutates an unsupported public field")
                if kind == "http" and mutation["field"] == "status_code":
                    value = mutation["value"]
                    if not isinstance(value, int) or isinstance(value, bool):
                        raise ContractError(f"{context} status_code mutation must be an integer")
                if kind == "http" and mutation["field"] == "headers":
                    value = mutation["value"]
                    if value is not None and (
                        not isinstance(value, dict)
                        or any(
                            not isinstance(name, str) or not isinstance(entry, str)
                            for name, entry in value.items()
                        )
                    ):
                        raise ContractError(
                            f"{context} headers mutation must be null or a string mapping"
                        )
                if kind == "websocket" and mutation["field"] == "code":
                    value = mutation["value"]
                    if not isinstance(value, int) or isinstance(value, bool):
                        raise ContractError(f"{context} code mutation must be an integer")
        if set(case["covers"]) != exercised:
            raise ContractError(
                "exception value-formatting coverage must match the behaviors selected by its inputs"
            )
        return

    if case["surface"] != MIDDLEWARE_CONFIG_SURFACE:
        raise ContractError("value-formatting case uses an undeclared public surface")
    if case["observations"] != ["repr", "__iter__"]:
        raise ContractError("Middleware value-formatting must select repr and __iter__")
    middleware = _exact(
        case["middleware"],
        {"class_name", "args", "kwargs"},
        "Middleware value-formatting input",
    )
    if not isinstance(middleware["class_name"], str) or not middleware["class_name"].isidentifier():
        raise ContractError("Middleware class_name must be an identifier")
    if not isinstance(middleware["args"], list) or not isinstance(middleware["kwargs"], dict):
        raise ContractError("Middleware args and kwargs must be an array and mapping")
    if any(not isinstance(key, str) for key in middleware["kwargs"]):
        raise ContractError("Middleware keyword names must be strings")
    expected = {
        "starlette.middleware.Middleware.repr",
        "starlette.middleware.Middleware.iteration",
    }
    if set(case["covers"]) != expected:
        raise ContractError(
            "Middleware value-formatting coverage must match repr and iteration inputs"
        )


def _validate_body_limit_case_stimulus(case: dict[str, Any]) -> None:
    if case["target_profiles"] != ["python-package-cpython312"]:
        raise ContractError("body-limit parity currently targets the Python package profile")
    if case["assets"] != [] or case["observations"] != ["dispatch"]:
        raise ContractError("body-limit cases must observe dispatch without external assets")
    if case["execution_schedule"] != ["dispatch"] or not isinstance(case["steps"], list):
        raise ContractError("body-limit cases must dispatch one ASGI scope")
    steps = case["steps"]
    if (
        len(steps) != 2
        or [step.get("step_id") for step in steps] != ["middleware", "dispatch"]
        or [step.get("operation") for step in steps] != ["__init__", "__call__"]
        or any(step.get("surface") != BODY_LIMIT_SURFACE for step in steps)
        or steps[0].get("receiver") is not None
        or steps[1].get("receiver") != {"kind": "binding", "step_id": "middleware"}
    ):
        raise ContractError("body-limit cases must construct and call the public middleware")
    constructor_step = _exact(steps[0], STEP_KEYS, "body-limit constructor step")
    dispatch_step = _exact(steps[1], STEP_KEYS, "body-limit dispatch step")
    constructor_args = _exact(
        constructor_step["arguments"], {"app", "max_body_size"}, "body-limit constructor arguments"
    )
    dispatch_args = _exact(
        dispatch_step["arguments"], {"scope", "receive", "send"}, "body-limit dispatch arguments"
    )
    for name, descriptor in constructor_args.items():
        _exact(descriptor, {"kind", "value"}, f"body-limit constructor {name} descriptor")
        if descriptor["kind"] != "literal":
            raise ContractError(f"body-limit constructor {name} must be an input literal")
    app_spec = _exact(
        constructor_args["app"]["value"], {"kind", "actions"}, "body-limit script app"
    )
    max_body_size = constructor_args["max_body_size"]["value"]
    if not isinstance(max_body_size, int) or isinstance(max_body_size, bool) or max_body_size < 0:
        raise ContractError("body-limit max_body_size must be a non-negative integer literal")
    if app_spec["kind"] != "asgi-body-limit-script":
        raise ContractError("body-limit app must use the declared action-script kind")
    _validate_body_limit_action_sequence(app_spec["actions"], "body-limit app actions")

    for name, descriptor in dispatch_args.items():
        _exact(descriptor, {"kind", "value"}, f"body-limit dispatch {name} descriptor")
        if descriptor["kind"] != "literal":
            raise ContractError(f"body-limit dispatch {name} must be an input literal")
    scope_value = dispatch_args["scope"]["value"]
    if not isinstance(scope_value, dict):
        raise ContractError("body-limit scope input must be a record")
    scope_check = dict(scope_value)
    prior_scope_limit = scope_check.pop("preexisting_max_body_size", _BODY_LIMIT_MISSING)
    if prior_scope_limit is not _BODY_LIMIT_MISSING and (
        prior_scope_limit is not None
        and (not isinstance(prior_scope_limit, int) or isinstance(prior_scope_limit, bool))
    ):
        raise ContractError("preexisting body limit must be an integer or null")
    if prior_scope_limit is not _BODY_LIMIT_MISSING and scope_value.get("type") != "http":
        raise ContractError("preexisting body limit input is only valid for HTTP scopes")
    _validate_dispatch_stimulus(
        {
            "scope": scope_check,
            "receive": dispatch_args["receive"]["value"],
            "send": dispatch_args["send"]["value"],
        },
        request_dispatch=True,
        allow_headers=True,
    )
    if dispatch_args["send"]["value"] != {"kind": "capture-asgi-send"}:
        raise ContractError("body-limit send must select the fixed ASGI capture collector")
    exercised = _body_limit_semantic_coverage(case)
    covered = set(case["covers"])
    expected_ids = {BODY_LIMIT_REQUIREMENT_CONSTRUCTION} | set(BODY_LIMIT_REQUIREMENTS.values())
    unknown = covered - expected_ids
    if unknown:
        raise ContractError(f"body-limit case covers undeclared requirements: {sorted(unknown)}")
    if covered - exercised:
        raise ContractError(
            "body-limit case claims requirements not exercised by its actions and inputs: "
            f"{sorted(covered - exercised)}"
        )


def _body_limit_semantic_coverage(case: dict[str, Any]) -> set[str]:
    constructor_args = {
        name: descriptor["value"] for name, descriptor in case["steps"][0]["arguments"].items()
    }
    dispatch_args = {
        name: descriptor["value"] for name, descriptor in case["steps"][1]["arguments"].items()
    }
    app_actions = constructor_args["app"]["actions"]
    scope = dispatch_args["scope"]
    coverage = {BODY_LIMIT_REQUIREMENT_CONSTRUCTION, BODY_LIMIT_REQUIREMENTS["scope-restoration"]}
    if scope["type"] != "http":
        coverage.add(BODY_LIMIT_REQUIREMENTS["non-http-pass-through"])
        return coverage

    header_pairs = _gzip_header_pairs(scope["headers_base64_pairs"], "HTTP request headers")
    lengths = [value for name, value in header_pairs if name.lower() == b"content-length"]
    declared_length = None
    invalid_length = False
    if lengths:
        try:
            declared_length = int(lengths[0])
        except ValueError:
            invalid_length = True
    messages = dispatch_args["receive"]
    body_lengths = [len(base64.b64decode(item["body_base64"], validate=True)) for item in messages]
    max_body_size = constructor_args["max_body_size"]

    def flatten(
        actions: list[dict[str, Any]], active_limit: int
    ) -> list[tuple[dict[str, Any], int]]:
        flattened: list[tuple[dict[str, Any], int]] = []
        current_limit = active_limit
        for action in actions:
            if action["action"] == "nested":
                current_limit = action["max_body_size"]
                nested_actions = flatten(action["actions"], current_limit)
                flattened.extend(nested_actions)
                if nested_actions:
                    current_limit = nested_actions[-1][1]
            else:
                flattened.append((action, current_limit))
        return flattened

    actions = flatten(app_actions, max_body_size)
    receive_actions = [action for action, _ in actions if action["action"] == "receive"]
    if declared_length is not None and declared_length > max_body_size and receive_actions:
        coverage.add(BODY_LIMIT_REQUIREMENTS["content-length-precheck"])
    if (
        declared_length is not None
        and declared_length > max_body_size
        and actions
        and actions[0][0]["action"] == "send"
        and actions[0][0]["message"].get("type") == "http.response.start"
    ):
        coverage.add(BODY_LIMIT_REQUIREMENTS["content-length-replacement"])
    received_sizes = body_lengths[: len(receive_actions)]
    accumulated_size = 0
    exceeded_after_start = False
    response_started = False
    receive_index = 0
    for action, limit in actions:
        if action["action"] == "send" and action["message"].get("type") == "http.response.start":
            response_started = True
        elif action["action"] == "receive" and receive_index < len(received_sizes):
            accumulated_size += received_sizes[receive_index]
            receive_index += 1
            if accumulated_size > limit:
                exceeded_after_start = exceeded_after_start or response_started
                if declared_length is None and not invalid_length:
                    coverage.add(BODY_LIMIT_REQUIREMENTS["streamed-body-count"])
                if declared_length is not None and declared_length <= max_body_size:
                    coverage.add(BODY_LIMIT_REQUIREMENTS["understated-content-length"])
    if invalid_length and receive_actions:
        coverage.add(BODY_LIMIT_REQUIREMENTS["invalid-content-length"])
    if exceeded_after_start:
        coverage.add(BODY_LIMIT_REQUIREMENTS["already-started-propagation"])

    def has_nested(action_sequence: list[dict[str, Any]]) -> bool:
        return any(
            action["action"] == "nested" or has_nested(action["actions"])
            for action in action_sequence
            if action["action"] == "nested"
        )

    if has_nested(app_actions) and receive_actions and any(body_lengths):
        coverage.add(BODY_LIMIT_REQUIREMENTS["nested-limits"])
    return coverage


def _validate_asgi_middleware_constructor(surface: str, args: dict[str, Any]) -> None:
    if surface == CORS_SURFACE:
        expected = {
            "app",
            "allow_origins",
            "allow_methods",
            "allow_headers",
            "allow_credentials",
            "allow_origin_regex",
            "allow_private_network",
            "expose_headers",
            "max_age",
        }
        args = _exact(args, expected, "CORSMiddleware constructor")
        for name in ("allow_origins", "allow_methods", "allow_headers", "expose_headers"):
            values = args[name]
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ContractError(f"CORSMiddleware {name} must be a string array")
        for name in ("allow_credentials", "allow_private_network"):
            if type(args[name]) is not bool:
                raise ContractError(f"CORSMiddleware {name} must be boolean")
        if args["allow_origin_regex"] is not None:
            regex = _string(args["allow_origin_regex"], "CORSMiddleware allow_origin_regex")
            try:
                re.compile(regex)
            except re.error as exc:
                raise ContractError(f"CORSMiddleware origin regex is invalid: {exc}") from exc
        if type(args["max_age"]) is not int or args["max_age"] < 0:
            raise ContractError("CORSMiddleware max_age must be a non-negative integer")
    elif surface == HTTPS_REDIRECT_SURFACE:
        _exact(args, {"app"}, "HTTPSRedirectMiddleware constructor")
    elif surface == TRUSTED_HOST_SURFACE:
        if set(args) - {"app", "allowed_hosts", "www_redirect"} or "app" not in args:
            raise ContractError("TrustedHostMiddleware constructor has an invalid argument set")
        if "allowed_hosts" in args and args["allowed_hosts"] is not None:
            hosts = args["allowed_hosts"]
            if not isinstance(hosts, list) or any(not isinstance(host, str) for host in hosts):
                raise ContractError("TrustedHostMiddleware allowed_hosts must be strings or null")
        if "www_redirect" in args and type(args["www_redirect"]) is not bool:
            raise ContractError("TrustedHostMiddleware www_redirect must be boolean")
    else:
        raise ContractError(f"unsupported protocol middleware surface: {surface}")

    _validate_asgi_middleware_app(args["app"])


def _validate_asgi_middleware_app(value: Any) -> None:
    app = _exact(value, {"kind", "messages"}, "ASGI middleware app input")
    if app["kind"] != "asgi-response-sequence" or not isinstance(app["messages"], list):
        raise ContractError("ASGI middleware app must be an input-defined message sequence")
    messages = app["messages"]
    if not messages:
        raise ContractError("ASGI middleware app message sequence must not be empty")
    if (
        len(messages) == 1
        and isinstance(messages[0], dict)
        and messages[0].get("type") == "websocket.close"
    ):
        message = _exact(messages[0], {"type", "code"}, "ASGI middleware WebSocket close")
        if message["type"] != "websocket.close" or not isinstance(message["code"], int):
            raise ContractError("ASGI middleware WebSocket close event is invalid")
        return
    start = _exact(
        messages[0],
        {"type", "status", "headers_base64_pairs"},
        "ASGI middleware HTTP response start",
    )
    if (
        start["type"] != "http.response.start"
        or not isinstance(start["status"], int)
        or isinstance(start["status"], bool)
        or not 100 <= start["status"] <= 599
    ):
        raise ContractError("ASGI middleware app must begin with a valid response-start event")
    _gzip_header_pairs(start["headers_base64_pairs"], "ASGI middleware response headers")
    if len(messages) < 2:
        raise ContractError("ASGI middleware HTTP response must include a response body event")
    body_messages = messages[1:]
    for index, raw_message in enumerate(body_messages):
        message = _exact(
            raw_message,
            {"type", "body_base64", "more_body"},
            f"ASGI middleware response body[{index}]",
        )
        if message["type"] != "http.response.body" or not isinstance(message["more_body"], bool):
            raise ContractError("ASGI middleware response body event is invalid")
        try:
            base64.b64decode(message["body_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError("ASGI middleware response body is invalid base64") from exc
    if (
        any(message["more_body"] for message in body_messages[:-1])
        or body_messages[-1]["more_body"]
    ):
        raise ContractError("ASGI middleware response body sequence must end with more_body=false")


def _validate_asgi_middleware_dispatch(surface: str, args: dict[str, Any]) -> None:
    args = _exact(args, {"scope", "receive", "send"}, f"{surface} dispatch")
    scope = args["scope"]
    if isinstance(scope, dict) and scope.get("type") == "http":
        _validate_dispatch_stimulus(
            args,
            request_dispatch=True,
            allow_headers=True,
            allow_query=True,
            allow_host=True,
        )
        return
    if not isinstance(scope, dict) or scope.get("type") != "websocket":
        raise ContractError(f"{surface} dispatch must use HTTP or WebSocket scope")
    scope = _exact(
        scope,
        {
            "type",
            "asgi",
            "http_version",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
            "subprotocols",
        },
        f"{surface} WebSocket scope",
    )
    if (
        scope["asgi"]
        not in (
            {"version": "3.0", "spec_version": "2.4"},
            {"version": "3.0", "spec_version": "2.5"},
        )
        or scope["scheme"] not in {"ws", "wss"}
        or not isinstance(scope["http_version"], str)
        or not isinstance(scope["root_path"], str)
        or not isinstance(scope["path"], str)
        or scope["raw_path_base64"] != base64.b64encode(scope["path"].encode("ascii")).decode()
    ):
        raise ContractError(f"{surface} WebSocket scope is invalid")
    if args["receive"] != [{"type": "websocket.connect"}] or args["send"] != {
        "kind": "capture-asgi-send"
    }:
        raise ContractError(f"{surface} WebSocket dispatch callbacks are invalid")
    for field in ("raw_path_base64", "query_string_base64"):
        try:
            base64.b64decode(scope[field], validate=True)
        except (ValueError, TypeError) as exc:
            raise ContractError(f"{surface} WebSocket {field} is invalid base64") from exc
    if not isinstance(scope["headers_base64_pairs"], list) or not isinstance(
        scope["subprotocols"], list
    ):
        raise ContractError(f"{surface} WebSocket headers and subprotocols must be arrays")


def _asgi_middleware_semantic_coverage(case: dict[str, Any]) -> set[str]:
    surface = case["surface"]
    constructor = {
        name: descriptor["value"] for name, descriptor in case["steps"][0]["arguments"].items()
    }
    if case["operation"] == "__init__":
        covered = {f"{surface}.construct"}
        hosts = constructor.get("allowed_hosts")
        if hosts and any(
            "*" in host[1:] or (host.startswith("*") and host != "*" and not host.startswith("*."))
            for host in hosts
        ):
            covered.add(f"{surface}.wildcard-validation-error")
        return covered
    dispatch = {
        name: descriptor["value"] for name, descriptor in case["steps"][1]["arguments"].items()
    }
    scope = dispatch["scope"]

    def suffix(value: str) -> str:
        return f"{surface}.{value}"

    covered = {suffix("construct")}

    def decoded_headers(scope_value: dict[str, Any]) -> dict[str, str]:
        return {
            base64.b64decode(name, validate=True).decode("latin-1").lower(): base64.b64decode(
                value, validate=True
            ).decode("latin-1")
            for name, value in scope_value.get("headers_base64_pairs", [])
        }

    headers = decoded_headers(scope)
    if surface == CORS_SURFACE:
        if scope["type"] != "http":
            covered.add(suffix("non-http-passthrough"))
            return covered
        origin = headers.get("origin")
        if origin is None:
            covered.add(suffix("missing-origin-passthrough"))
            return covered
        origins = constructor["allow_origins"]
        origin_regex = constructor["allow_origin_regex"]
        allowed_origin = origin == "*" or "*" in origins or origin in origins
        regex_match = re.compile(origin_regex).match(origin) if origin_regex else None
        full_regex_match = re.compile(origin_regex).fullmatch(origin) if origin_regex else None
        allowed_origin = allowed_origin or full_regex_match is not None
        if origin_regex and regex_match is not None and full_regex_match is None:
            covered.add(suffix("regex-fullmatch-origin"))
        requested_method = headers.get("access-control-request-method")
        if scope["method"] == "OPTIONS" and requested_method is not None:
            requested_headers = [
                value.strip().lower()
                for value in headers.get("access-control-request-headers", "").split(",")
                if value.strip()
            ]
            allowed_methods = constructor["allow_methods"]
            allowed_headers = {value.lower() for value in constructor["allow_headers"]}
            failures = (
                not allowed_origin,
                "*" not in allowed_methods and requested_method not in allowed_methods,
                "*" not in allowed_headers
                and any(value not in allowed_headers for value in requested_headers),
                headers.get("access-control-request-private-network") == "true"
                and not constructor["allow_private_network"],
            )
            if (
                all(
                    (
                        allowed_origin,
                        "*" in allowed_methods or requested_method in allowed_methods,
                        "*" in allowed_headers
                        or all(value in allowed_headers for value in requested_headers),
                        headers.get("access-control-request-private-network") != "true"
                        or constructor["allow_private_network"],
                    )
                )
                and constructor["allow_private_network"]
            ):
                covered.add(suffix("preflight-wildcard-credential-private-network"))
            elif sum(failures) > 1:
                covered.add(suffix("preflight-denial-failure-order"))
            return covered
        if (
            "*" in origins
            and constructor["allow_credentials"]
            and "cookie" in headers
            and any(
                base64.b64decode(name, validate=True).lower() == b"vary"
                for name, _value in constructor["app"]["messages"][0]["headers_base64_pairs"]
            )
        ):
            covered.add(suffix("simple-wildcard-credential-reflection-vary-merge"))
        elif origin_regex and regex_match is not None and full_regex_match is None:
            covered.add(suffix("regex-fullmatch-origin"))
        elif not allowed_origin:
            covered.add(suffix("simple-denied-origin-preserves-app-response"))
        return covered

    if surface == HTTPS_REDIRECT_SURFACE:
        scheme = scope.get("scheme")
        if scope["type"] in {"http", "websocket"} and scheme in {"http", "ws"}:
            if scheme == "ws":
                covered.add(suffix("websocket-redirect"))
            elif scope["server"][1] == 80:
                covered.add(suffix("http-redirect-default-port"))
            elif scope["query_string_base64"]:
                covered.add(suffix("http-redirect-preserves-port-and-query"))
        else:
            covered.add(suffix("secure-scheme-pass-through"))
        return covered

    if surface == TRUSTED_HOST_SURFACE:
        if scope["type"] != "http":
            covered.add(suffix("non-http-scope-pass-through"))
            return covered
        allowed_hosts = constructor.get("allowed_hosts")
        allowed_hosts = ["*"] if allowed_hosts is None else allowed_hosts
        if "*" in allowed_hosts:
            covered.add(suffix("default-allowed-hosts"))
            return covered
        host = headers.get("host", "").split(":")[0]
        exact_match = host in allowed_hosts
        wildcard_match = any(
            pattern.startswith("*.") and host.endswith(pattern[1:]) for pattern in allowed_hosts
        )
        www_match = "www." + host in allowed_hosts
        if exact_match:
            covered.add(suffix("exact-host-match"))
        elif wildcard_match:
            covered.add(suffix("domain-wildcard-match"))
        elif www_match and constructor.get("www_redirect", True):
            covered.add(suffix("www-redirect"))
        elif www_match:
            covered.add(suffix("www-redirect-disabled"))
        else:
            covered.add(suffix("invalid-host-response"))
        return covered

    return covered


def _validate_gzip_constructor_stimulus(args: dict[str, Any]) -> None:
    if set(args) != {
        "app",
        "minimum_size",
        "compresslevel",
        "thread_minimum_size",
        "exclude_content_types",
    }:
        raise ContractError("GZipMiddleware construction must supply its app and all settings")
    app = _exact(args["app"], {"kind", "messages"}, "GZipMiddleware app input")
    if app["kind"] != "asgi-response-sequence":
        raise ContractError("GZipMiddleware app must be an input-defined ASGI response sequence")
    messages = app["messages"]
    if not isinstance(messages, list) or len(messages) < 2:
        raise ContractError("inner ASGI response input must include response start and output")
    start = _exact(
        messages[0],
        {"type", "status", "headers_base64_pairs"},
        "inner ASGI response start",
    )
    if (
        start["type"] != "http.response.start"
        or not isinstance(start["status"], int)
        or isinstance(start["status"], bool)
        or not 100 <= start["status"] <= 599
    ):
        raise ContractError("inner ASGI response must begin with a valid response-start event")
    start_headers = _gzip_header_pairs(start["headers_base64_pairs"], "response start headers")

    output_messages = messages[1:]
    output_types: list[str] = []
    bodies: list[tuple[bytes, bool]] = []
    for index, raw_message in enumerate(output_messages):
        context = f"inner ASGI response message[{index}]"
        if not isinstance(raw_message, dict):
            raise ContractError(f"{context} must be an object")
        message_type = raw_message.get("type")
        output_types.append(message_type)
        if message_type == "http.response.body":
            message = _exact(
                raw_message,
                {"type", "body_base64", "more_body"},
                context,
            )
            if not isinstance(message["more_body"], bool):
                raise ContractError(f"{context}.more_body must be boolean")
            try:
                body = base64.b64decode(message["body_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ContractError(f"{context}.body_base64 is invalid") from exc
            bodies.append((body, message["more_body"]))
        elif message_type == "http.response.pathsend":
            message = _exact(raw_message, {"type", "path"}, context)
            _string(message["path"], f"{context}.path")
        else:
            raise ContractError(f"{context} uses an unsupported ASGI response message type")

    if output_types == ["http.response.pathsend"]:
        pass
    elif all(message_type == "http.response.body" for message_type in output_types):
        if not bodies or any(not more_body for _, more_body in bodies[:-1]) or bodies[-1][1]:
            raise ContractError("inner response body messages must end with more_body=false")
    else:
        raise ContractError("inner response must be body messages or one pathsend event")

    minimum_size = args["minimum_size"]
    compresslevel = args["compresslevel"]
    thread_minimum_size = args["thread_minimum_size"]
    if not isinstance(minimum_size, int) or isinstance(minimum_size, bool) or minimum_size < 0:
        raise ContractError("GZipMiddleware minimum_size must be a non-negative integer")
    if (
        not isinstance(compresslevel, int)
        or isinstance(compresslevel, bool)
        or not -1 <= compresslevel <= 9
    ):
        raise ContractError("GZipMiddleware compresslevel must be an integer from -1 through 9")
    if (
        not isinstance(thread_minimum_size, int)
        or isinstance(thread_minimum_size, bool)
        or thread_minimum_size < 0
    ):
        raise ContractError("GZipMiddleware thread_minimum_size must be a non-negative integer")
    exclusions = args["exclude_content_types"]
    if not isinstance(exclusions, list) or any(
        not isinstance(content_type, str) or not content_type for content_type in exclusions
    ):
        raise ContractError("GZipMiddleware exclude_content_types must be a string array")

    content_lengths = [value for name, value in start_headers if name.lower() == b"content-length"]
    if len(content_lengths) > 1:
        raise ContractError("inner response start must not repeat content-length")
    if content_lengths and bodies and not any(more_body for _, more_body in bodies):
        try:
            declared_length = int(content_lengths[0])
        except ValueError as exc:
            raise ContractError("inner content-length must be an integer") from exc
        if declared_length != sum(len(body) for body, _ in bodies):
            raise ContractError("inner content-length must match the supplied response body")


def _gzip_semantic_coverage(case: dict[str, Any]) -> set[str]:
    constructor_args = {
        key: descriptor["value"] for key, descriptor in case["steps"][0]["arguments"].items()
    }
    dispatch_args = {
        key: descriptor["value"] for key, descriptor in case["steps"][1]["arguments"].items()
    }
    app = constructor_args["app"]
    messages = app["messages"]
    response_start = messages[0]
    response_headers = _gzip_header_pairs(
        response_start["headers_base64_pairs"], "response start headers"
    )
    request_headers = _gzip_header_pairs(
        dispatch_args["scope"]["headers_base64_pairs"], "HTTP scope headers"
    )

    def header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
        return next((value for header_name, value in headers if header_name.lower() == name), None)

    accept_encoding = header_value(request_headers, b"accept-encoding") or b""
    gzip_accepted = b"gzip" in accept_encoding
    content_type_value = header_value(response_headers, b"content-type") or b""
    media_type = content_type_value.partition(b";")[0].strip().lower().decode("latin-1")
    excluded_types = {
        content_type.partition(";")[0].strip().lower()
        for content_type in constructor_args["exclude_content_types"]
    }
    media_family = media_type.partition("/")[0] + "/*"
    excluded = media_type in excluded_types or media_family in excluded_types
    content_encoded = header_value(response_headers, b"content-encoding") is not None
    partial_response = response_start["status"] == 206
    output_messages = messages[1:]
    body_messages = [
        message for message in output_messages if message["type"] == "http.response.body"
    ]
    body_lengths = [
        len(base64.b64decode(message["body_base64"], validate=True)) for message in body_messages
    ]
    complete_stream = (
        len(body_messages) >= 2
        and all(message["more_body"] for message in body_messages[:-1])
        and not body_messages[-1]["more_body"]
    )
    minimum_size = constructor_args["minimum_size"]
    compressible = not content_encoded and not partial_response and not excluded
    coverage = {GZIP_REQUIREMENT_CONSTRUCTION}

    if (
        gzip_accepted
        and len(body_messages) == 1
        and not body_messages[0]["more_body"]
        and body_lengths[0] >= minimum_size
        and compressible
    ):
        coverage.add(GZIP_REQUIREMENTS["gzip-final-response"])
    if (
        accept_encoding.strip().lower() == b"identity"
        and len(body_messages) == 1
        and not body_messages[0]["more_body"]
        and body_lengths[0] >= minimum_size
        and compressible
    ):
        coverage.add(GZIP_REQUIREMENTS["identity-client"])
    if (
        gzip_accepted
        and len(body_messages) == 1
        and not body_messages[0]["more_body"]
        and body_lengths[0] < minimum_size
        and compressible
    ):
        coverage.add(GZIP_REQUIREMENTS["small-body-bypass"])
    if (
        gzip_accepted
        and bool(body_messages)
        and body_lengths[0] >= minimum_size
        and excluded
        and not content_encoded
        and not partial_response
    ):
        coverage.add(GZIP_REQUIREMENTS["excluded-content-type"])
    if gzip_accepted and complete_stream and compressible:
        coverage.add(GZIP_REQUIREMENTS["streaming-chunks"])
    if (
        gzip_accepted
        and complete_stream
        and content_encoded
        and not partial_response
        and not excluded
    ):
        coverage.add(GZIP_REQUIREMENTS["existing-encoding-stream-bypass"])
    if (
        gzip_accepted
        and complete_stream
        and partial_response
        and not content_encoded
        and not excluded
    ):
        coverage.add(GZIP_REQUIREMENTS["partial-response-stream-bypass"])
    if (
        gzip_accepted
        and len(output_messages) == 1
        and output_messages[0]["type"] == "http.response.pathsend"
    ):
        coverage.add(GZIP_REQUIREMENTS["pathsend"])
    return coverage


def _route_path_matches(route_path: str, request_path: str) -> bool:
    return _route_template_matches(route_path, request_path)


def _semantic_coverage(case: dict[str, Any]) -> set[str]:
    if case["surface"] == GZIP_SURFACE:
        return _gzip_semantic_coverage(case)
    app_arguments = {
        key: descriptor["value"] for key, descriptor in case["steps"][0]["arguments"].items()
    }
    if case["execution_schedule"] == ["lifespan.startup", "lifespan.shutdown"]:
        lifecycle_args = {
            key: descriptor["value"] for key, descriptor in case["steps"][1]["arguments"].items()
        }
        return {_lifespan_case_requirement(app_arguments["lifespan"], lifecycle_args)}
    route = app_arguments["routes"][0]
    endpoint = route["endpoint"]
    dispatch_arguments = {
        key: descriptor["value"] for key, descriptor in case["steps"][-1]["arguments"].items()
    }
    scope = dispatch_arguments["scope"]
    path = scope["path"]
    method = scope["method"]
    path_matches = _route_path_matches(route["path"], path)
    methods = set(route["methods"])
    if "GET" in methods:
        methods.add("HEAD")
    method_matches = method in methods
    coverage: set[str] = set()

    if case["operation"] == "__call__":
        handlers = app_arguments["exception_handlers"]
        if _is_server_error_stimulus(app_arguments):
            key_specs = [entry["key"] for entry in handlers]
            has_status_500 = {"kind": "status-code", "status_code": 500} in key_specs
            has_exception = {"kind": "exception-class", "name": "Exception"} in key_specs
            if path_matches and method_matches:
                if endpoint["kind"] == "raise-runtime-error":
                    if not handlers and not app_arguments["debug"]:
                        coverage.add("starlette.asgi.server-error.default-response")
                    if has_status_500:
                        coverage.add("starlette.asgi.server-error.status-500-handler")
                    if has_exception:
                        coverage.add("starlette.asgi.server-error.exception-handler")
                    if has_status_500 and has_exception:
                        coverage.add("starlette.asgi.server-error.special-key-order")
                    if app_arguments["debug"]:
                        coverage.add("starlette.asgi.server-error.debug-traceback")
                elif endpoint["kind"] == "asgi-callable-action-sequence":
                    if any(
                        action["action"] == "raise-runtime-error" for action in endpoint["actions"]
                    ):
                        coverage.add("starlette.asgi.server-error.response-started")
                elif endpoint["kind"] == "http-exception" and endpoint["status_code"] == 500:
                    if has_status_500 and any(
                        key == {"kind": "exception-class", "name": "HTTPException"}
                        for key in key_specs
                    ):
                        coverage.add("starlette.asgi.server-error.handled-http-exception-500")
            return coverage
        if handlers:
            entries_by_key = {
                (
                    entry["key"]["kind"],
                    entry["key"].get("name", entry["key"].get("status_code")),
                ): entry
                for entry in handlers
            }
            if endpoint["kind"] == "http-exception-after-body":
                subclass_key = ("exception-class", endpoint["exception_class"])
                handler_entry = entries_by_key.get(subclass_key)
                if path_matches and method_matches and handler_entry is not None:
                    coverage.update(
                        {
                            "starlette.asgi.exception-handler.exception-class",
                            "starlette.asgi.exception-handler.async-callback",
                        }
                    )
                    if handler_entry["handler"]["kind"] == "request-body-json-response":
                        messages = dispatch_arguments["receive"]
                        chunks = [
                            base64.b64decode(message["body_base64"], validate=True)
                            for message in messages
                        ]
                        if (
                            len(chunks) > 1
                            and all(message["more_body"] for message in messages[:-1])
                            and not messages[-1]["more_body"]
                            and b"".join(chunks)
                        ):
                            coverage.add(
                                "starlette.asgi.exception-handler.request-body-cache-reuse"
                            )
            elif path_matches and not method_matches:
                if ("status-code", 405) in entries_by_key:
                    coverage.add("starlette.asgi.exception-handler.status-code")
                if ("exception-class", "HTTPException") in entries_by_key:
                    coverage.add("starlette.asgi.exception-handler.exception-class")
                if handlers and all(
                    entry["handler"]["kind"]
                    in {"json-exception-detail-response", "json-literal-response"}
                    for entry in handlers
                ):
                    coverage.add("starlette.asgi.exception-handler.async-callback")
            return coverage
        if endpoint["kind"] == "http-exception":
            if path_matches and method_matches:
                status_code = endpoint["status_code"]
                detail = endpoint["detail"]
                headers = endpoint["headers"]
                if status_code == 406 and detail is None:
                    coverage.add("starlette.asgi.http-exception.default-406-detail")
                elif status_code == 406 and isinstance(detail, str):
                    coverage.add("starlette.asgi.http-exception.explicit-detail")
                elif status_code == 204 and detail is None:
                    coverage.add("starlette.asgi.http-exception.no-content-204")
                elif status_code == 304 and detail is None:
                    coverage.add("starlette.asgi.http-exception.not-modified-304")
                elif status_code == 200 and detail is None and headers:
                    coverage.add("starlette.asgi.http-exception.headers-200")
            return coverage
        if path_matches and method_matches:
            coverage.update(
                {
                    "starlette.asgi.get-hello.application-construction",
                    "starlette.asgi.get-hello.dispatch",
                }
            )
        elif not path_matches and _application_has_slash_redirect(
            app_arguments["routes"], path, scope.get("root_path", "")
        ):
            coverage.add("starlette.asgi.get-hello.slash-redirect")
        elif not path_matches:
            coverage.add("starlette.asgi.get-hello.route-miss-404")
        else:
            coverage.add("starlette.asgi.get-hello.wrong-method-405")
        if case["execution_schedule"] == [
            "lifespan.startup",
            "dispatch",
            "lifespan.shutdown",
        ]:
            coverage.add("starlette.asgi.get-hello.lifespan")
        return coverage

    coverage.update(
        {
            "starlette.routing.request-scope-values",
            "starlette.asgi.request-dispatch-events",
        }
    )
    if not path_matches:
        coverage.add("starlette.routing.items-route-miss-404")
        return coverage
    if not method_matches:
        coverage.add("starlette.routing.items-wrong-method-405")
        return coverage

    path_parameters = dict(_route_template_parameters(route["path"]))
    path_parameter = endpoint.get("path_parameter")
    if path_parameter is not None:
        converter = path_parameters.get(path_parameter)
        requirement = {
            "str": "starlette.request.path-param-string",
            "int": "starlette.request.path-param-int",
            "float": "starlette.request.path-param-float",
            "uuid": "starlette.request.path-param-uuid",
            "path": "starlette.request.path-param-path",
        }.get(converter)
        if requirement is not None:
            coverage.add(requirement)
        if converter == "int":
            captured = _route_template_capture(route["path"], path)
            raw_value = captured.get(path_parameter) if captured is not None else None
            integer_limit = sys.get_int_max_str_digits()
            if integer_limit > 0 and raw_value is not None and len(raw_value) > integer_limit:
                coverage.add("starlette.request.path-param-int-digit-limit")

    if endpoint["kind"] == "request-observer":
        query = base64.b64decode(scope["query_string_base64"], validate=True).decode("ascii")
        query_values = [
            value
            for name, value in parse_qsl(query, keep_blank_values=True)
            if name == endpoint["query_parameter"]
        ]
        if len(query_values) > 1:
            coverage.add("starlette.request.query-params-getlist-scalar")

        headers = [
            (
                base64.b64decode(name, validate=True).decode("latin-1").casefold(),
                base64.b64decode(value, validate=True).decode("latin-1"),
            )
            for name, value in scope["headers_base64_pairs"]
        ]
        primary_header = endpoint["header_primary_case"]
        alternate_header = endpoint["header_alternate_case"]
        if (
            primary_header != alternate_header
            and primary_header.casefold() == alternate_header.casefold()
            and any(name == primary_header.casefold() for name, _ in headers)
        ):
            coverage.add("starlette.request.headers-case-insensitive")

        cookie_name = endpoint["cookie_name"]
        cookies = [
            cookie.strip().partition("=")
            for name, value in headers
            if name == "cookie"
            for cookie in value.split(";")
        ]
        if any(name == cookie_name and separator for name, separator, _ in cookies):
            coverage.add("starlette.request.cookies")

        messages = dispatch_arguments["receive"]
        chunks = [base64.b64decode(message["body_base64"], validate=True) for message in messages]
        has_complete_chunking = (
            len(messages) > 1
            and all(message["more_body"] for message in messages[:-1])
            and not messages[-1]["more_body"]
        )
        if has_complete_chunking:
            try:
                json.loads(b"".join(chunks))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            else:
                coverage.add("starlette.request.json-chunked-body")
    elif endpoint["kind"] == "request-connection-property":
        property_name = endpoint["property"]
        if property_name not in scope:
            coverage.add(REQUEST_CONNECTION_PROPERTY_REQUIREMENTS[property_name])
    elif endpoint["kind"] == "request-stream-observer":
        operations = {action["operation"] for action in endpoint["actions"]}
        coverage.update(
            requirement
            for operation, requirement in REQUEST_STREAM_REQUIREMENTS.items()
            if operation in operations
        )
    elif endpoint["kind"] == "sync-request-runtime-observer":
        coverage.update(
            SYNC_REQUEST_RUNTIME_REQUIREMENTS[action["property"]]
            if action["operation"] == "callable-property"
            else SYNC_REQUEST_RUNTIME_REQUIREMENTS[
                action["method"] if action["operation"] == "construct-awaitable" else "stream"
            ]
            for action in endpoint["actions"]
        )
        coverage.update(
            SYNC_ENDPOINT_REQUIREMENTS[key]
            for key in ("contextvar", "worker_thread", "single_invocation")
        )
    elif endpoint["kind"] == "sync-request-observer":
        coverage.update(
            SYNC_ENDPOINT_REQUIREMENTS[key]
            for key in ("contextvar", "worker_thread", "single_invocation")
        )
        if endpoint["callable_kind"] in {"bound_method", "partial"}:
            coverage.add(SYNC_ENDPOINT_REQUIREMENTS["callable_form"])
    elif endpoint["kind"] == "asgi-callable-instance-observer":
        coverage.add(ASGI_CALLABLE_INSTANCE_REQUIREMENT)
    elif endpoint["kind"] == "asgi-callable-action-sequence":
        coverage.add(ASGI_CALLABLE_INSTANCE_REQUIREMENT)
        sent_response = any(action["action"] == "send" for action in endpoint["actions"])
        coverage.add(
            "starlette.routing.asgi-callable-http-exception-after-start"
            if sent_response
            else "starlette.routing.asgi-callable-http-exception-before-start"
        )
    return coverage


def validate_input_document(document: Any, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    _exact(document, {"schema", "cases"}, "parity input")
    if document["schema"] != INPUT_SCHEMA:
        raise ContractError(f"unsupported parity input schema: {document['schema']!r}")
    if not isinstance(document["cases"], list) or not document["cases"]:
        raise ContractError("parity input must select at least one case")
    cases = [validate_case(case, manifest) for case in document["cases"]]
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ContractError("parity input case IDs must be globally unique")
    return cases


def validate_benchmark_document(
    document: Any, cases: list[dict[str, Any]], manifest: dict[str, Any]
) -> dict[str, Any]:
    _exact(document, {"schema", "workloads", "suites"}, "benchmark input")
    if document["schema"] != BENCHMARK_INPUT_SCHEMA:
        raise ContractError(f"unsupported benchmark input schema: {document['schema']!r}")
    if not isinstance(document["workloads"], list) or len(document["workloads"]) != 1:
        raise ContractError("the slice benchmark must declare exactly one explicit workload")
    workload = _exact(
        document["workloads"][0],
        {"workload_id", "covers", "subjects", "input", "measurement"},
        "benchmark workload",
    )
    if workload["workload_id"] != "starlette.asgi.get-hello.direct-dispatch":
        raise ContractError(
            "benchmark workload ID differs from the declared direct-ASGI smoke workload"
        )
    if workload["covers"] != ["starlette.asgi.get-hello.latency"]:
        raise ContractError("benchmark workload must cover the declared latency requirement")
    expected_subjects = [
        {"kind": "oracle", "id": "starlette-python"},
        {"kind": "target_profile", "id": "rust-native-local"},
        {"kind": "target_profile", "id": "python-package-cpython312"},
    ]
    if workload["subjects"] != expected_subjects:
        raise ContractError(
            "benchmark subjects must include the pinned oracle and both declared targets in order"
        )
    for subject in workload["subjects"]:
        _exact(subject, {"kind", "id"}, "benchmark subject")
    _exact(workload["input"], {"kind", "case_id"}, "benchmark workload input")
    expected_case_id = "starlette.applications.Starlette.__call__.get-hello"
    if workload["input"] != {"kind": "parity_case", "case_id": expected_case_id}:
        raise ContractError("benchmark must reference the public GET /hello parity case")
    if expected_case_id not in {case["case_id"] for case in cases}:
        raise ContractError("benchmark references a parity case outside the active input set")
    measurement = _exact(
        workload["measurement"],
        {
            "boundary",
            "step_ids",
            "metrics",
            "warmup_iterations",
            "measurement_iterations",
            "samples",
            "concurrency",
            "cache_state",
            "correctness_gate",
        },
        "benchmark measurement",
    )
    if measurement != {
        "boundary": "observed_steps",
        "step_ids": ["dispatch"],
        "metrics": ["latency"],
        "warmup_iterations": 20,
        "measurement_iterations": 100,
        "samples": 30,
        "concurrency": 1,
        "cache_state": "warm",
        "correctness_gate": "parity_pass",
    }:
        raise ContractError(
            "benchmark measurement policy differs from the declared deterministic smoke policy"
        )
    if not isinstance(document["suites"], list) or len(document["suites"]) != 1:
        raise ContractError("the smoke benchmark must declare exactly one suite")
    suite = _exact(document["suites"][0], {"suite_id", "description", "members"}, "benchmark suite")
    if (
        suite["suite_id"] != "direct-asgi-smoke"
        or not isinstance(suite["description"], str)
        or not suite["description"]
    ):
        raise ContractError("benchmark suite ID/description is invalid")
    if suite["members"] != [{"workload_id": workload["workload_id"], "weight": 1}]:
        raise ContractError(
            "benchmark suite must include the direct ASGI workload with unit weight"
        )
    _exact(suite["members"][0], {"workload_id", "weight"}, "benchmark suite member")
    requirement_rows = [
        requirement
        for surface in manifest["surfaces"]
        for operation in surface["operations"]
        for requirement in operation["requirements"]
        if requirement["id"] == workload["covers"][0]
    ]
    if len(requirement_rows) != 1 or requirement_rows[0]["lanes"] != ["benchmark"]:
        raise ContractError(
            "benchmark requirement must resolve to exactly one benchmark-only requirement"
        )
    return document


def validate_benchmark_inputs(
    root: Path, manifest: dict[str, Any], cases: list[dict[str, Any]]
) -> list[tuple[Path, dict[str, Any]]]:
    lane_root = root / GENERATED_INPUT_ROOT / "benchmark"
    indexed: set[str] = set()
    documents: list[tuple[Path, dict[str, Any]]] = []
    for relative in manifest["input_index"]["benchmark"]:
        path = root / relative
        try:
            path.resolve().relative_to(lane_root.resolve())
        except ValueError as exc:
            raise ContractError(f"benchmark input escapes its lane root: {relative}") from exc
        document = load_json(path)
        if not isinstance(document, dict):
            raise ContractError(f"benchmark input must be an object: {relative}")
        if document.get("schema") == BENCHMARK_INPUT_SCHEMA:
            validate_benchmark_document(document, cases, manifest)
        elif document.get("schema") == UPSTREAM_BENCHMARK_INPUT_SCHEMA:
            from .upstream_benchmark_contract import validate_upstream_workloads

            validate_upstream_workloads(document)
        else:
            raise ContractError(f"unsupported benchmark input schema: {document.get('schema')!r}")
        indexed.add(path.resolve().as_posix())
        documents.append((path, document))
    discovered = (
        {path.resolve().as_posix() for path in lane_root.rglob("*.json")}
        if lane_root.exists()
        else set()
    )
    if indexed != discovered:
        raise ContractError(
            f"benchmark input index mismatch: missing={sorted(discovered - indexed)}, stale={sorted(indexed - discovered)}"
        )
    return documents


def validate_inputs(
    root: Path, manifest: dict[str, Any]
) -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    index = manifest["input_index"]
    active: set[str] = set()
    loaded: list[tuple[Path, dict[str, Any]]] = []
    all_cases: list[dict[str, Any]] = []
    for relative in index["parity"]:
        path = root / relative
        try:
            path.resolve().relative_to((root / GENERATED_INPUT_ROOT / "parity").resolve())
        except ValueError as exc:
            raise ContractError(f"parity input escapes its lane root: {relative}") from exc
        active.add(path.resolve().as_posix())
        document = load_json(path)
        cases = validate_input_document(document, manifest)
        loaded.append((path, document))
        all_cases.extend(cases)
    parity_root = root / GENERATED_INPUT_ROOT / "parity"
    discovered = (
        {path.resolve().as_posix() for path in parity_root.rglob("*.json")}
        if parity_root.exists()
        else set()
    )
    if active != discovered:
        raise ContractError(
            f"parity input index mismatch: missing={sorted(discovered - active)}, stale={sorted(active - discovered)}"
        )
    case_ids = [case["case_id"] for case in all_cases]
    if len(case_ids) != len(set(case_ids)):
        raise ContractError("case IDs must be unique across all indexed parity inputs")
    parity_requirements = {
        requirement["id"]
        for surface in manifest["surfaces"]
        for operation in surface["operations"]
        for requirement in operation["requirements"]
        if "parity" in requirement["lanes"]
    }
    covered_requirements = {requirement for case in all_cases for requirement in case["covers"]}
    missing_requirements = parity_requirements - covered_requirements
    if missing_requirements:
        raise ContractError(
            f"indexed parity inputs do not cover declared parity requirements: {sorted(missing_requirements)}"
        )
    if index["coverage"]:
        raise ContractError(
            "coverage inputs are outside this slice; full replacement coverage remains required"
        )
    coverage_root = root / GENERATED_INPUT_ROOT / "coverage"
    if coverage_root.exists() and any(coverage_root.rglob("*.json")):
        raise ContractError("unindexed coverage inputs are not allowed")
    validate_benchmark_inputs(root, manifest, all_cases)
    return loaded, all_cases


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_workflow_result(value: Any, expected_case_id: str, context: str) -> dict[str, Any]:
    _exact(value, {"case_id", "status", "observations"}, context)
    if value["case_id"] != expected_case_id:
        raise ContractError(f"{context}.case_id mismatch")
    if value["status"] not in PARITY_TERMINAL_STATUSES:
        raise ContractError(f"{context}.status is invalid")
    observations = value["observations"]
    if not isinstance(observations, list):
        raise ContractError(f"{context}.observations must be an array")
    for index, item in enumerate(observations):
        item_context = f"{context}.observations[{index}]"
        if not isinstance(item, dict):
            raise ContractError(f"{item_context} must be an object")
        status = item.get("status")
        if status == "ok":
            _exact(item, {"step_id", "status", "value"}, item_context)
        elif status == "error":
            _exact(item, {"step_id", "status", "error", "partial_value"}, item_context)
            _exact(
                item["error"],
                {
                    "class",
                    "kind",
                    "message",
                    "stage",
                    "code",
                    "cause",
                    "suppress_context",
                },
                f"{item_context}.error",
            )
            for name in ("class", "kind", "message", "stage"):
                if item["error"][name] is not None and not isinstance(item["error"][name], str):
                    raise ContractError(f"{item_context}.error.{name} must be a string or null")
            code = item["error"]["code"]
            if code is not None and (not isinstance(code, (str, int)) or isinstance(code, bool)):
                raise ContractError(f"{item_context}.error.code must be a string, integer, or null")
            cause = item["error"]["cause"]
            if cause is not None:
                _exact(cause, {"class", "message", "attributes"}, f"{item_context}.error.cause")
                for name in ("class", "message"):
                    if cause[name] is not None and not isinstance(cause[name], str):
                        raise ContractError(
                            f"{item_context}.error.cause.{name} must be a string or null"
                        )
                if not isinstance(cause["attributes"], dict):
                    raise ContractError(f"{item_context}.error.cause.attributes must be an object")
            if not isinstance(item["error"]["suppress_context"], bool):
                raise ContractError(f"{item_context}.error.suppress_context must be boolean")
            if not isinstance(item["partial_value"], dict):
                raise ContractError(f"{item_context}.partial_value must be an object")
        elif status in {"skipped", "unsupported"}:
            _exact(item, {"step_id", "status", "reason"}, item_context)
            _string(item["reason"], f"{item_context}.reason")
        else:
            raise ContractError(f"{item_context}.status is invalid or unsupported")
    if value["status"] in {"skipped", "unsupported"} and not value["observations"]:
        return value
    if value["status"] == "completed" and not value["observations"]:
        raise ContractError(f"{context} completed with no observation evidence")
    return value


def _validate_sha256(value: Any, context: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContractError(f"{context} must be a lowercase SHA-256 digest")


def _validate_nonnegative_integer(value: Any, context: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ContractError(f"{context} must be a non-negative integer")


def _sample_quantile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile * len(ordered) + 0.999999999) - 1)))
    return ordered[index]


def _validate_not_run_subject_identity(identity: Any, subject_id: str, context: str) -> None:
    if identity is None:
        return
    if subject_id == "starlette-python":
        oracle = _exact(
            identity,
            {
                "oracle_id",
                "name",
                "version",
                "revision",
                "runtime",
                "module_path",
                "dependency_lock_sha256",
                "os",
                "architecture",
                "environment_sha256",
                "runtime_lock_sha256",
            },
            context,
        )
        if (
            oracle["oracle_id"] != subject_id
            or oracle["version"] != "1.6.0"
            or oracle["revision"] != ORACLE_COMMIT
        ):
            raise ContractError(f"{context} differs from the pinned Starlette oracle identity")
        for name in ("name", "version", "revision", "runtime", "module_path", "os", "architecture"):
            _string(oracle[name], f"{context}.{name}")
        for name in ("dependency_lock_sha256", "environment_sha256", "runtime_lock_sha256"):
            _validate_sha256(oracle[name], f"{context}.{name}")
        return

    expected_target_ids = {
        "rust-native-local": "rust-native",
        "python-package-cpython312": "python-package",
    }
    target = _exact(
        identity,
        {
            "target_profile",
            "target_id",
            "revision",
            "dirty",
            "runtime",
            "backend",
            "features",
            "package_version",
            "target_tree_sha256",
            "dependency_lock_sha256",
            "os",
            "architecture",
            "environment_sha256",
        },
        context,
    )
    if target["target_profile"] != subject_id or target["target_id"] != expected_target_ids.get(
        subject_id
    ):
        raise ContractError(f"{context} does not match its not_run target subject")
    for name in ("revision", "runtime", "backend", "os", "architecture"):
        _string(target[name], f"{context}.{name}")
    if not isinstance(target["dirty"], bool):
        raise ContractError(f"{context}.dirty must be boolean")
    if not isinstance(target["features"], list) or any(
        not isinstance(feature, str) for feature in target["features"]
    ):
        raise ContractError(f"{context}.features must be an array of strings")
    if target["package_version"] is not None:
        _string(target["package_version"], f"{context}.package_version")
    if target["target_tree_sha256"] is not None:
        _validate_sha256(target["target_tree_sha256"], f"{context}.target_tree_sha256")
    _validate_sha256(target["dependency_lock_sha256"], f"{context}.dependency_lock_sha256")
    if target["environment_sha256"] is not None:
        _validate_sha256(target["environment_sha256"], f"{context}.environment_sha256")


def _validate_worker_identity(identity: Any, subject_id: str, context: str) -> None:
    worker = _exact(
        identity,
        {
            "subject_id",
            "starlette_version",
            "package_version",
            "module_path",
            "core_extension_path",
            "python_executable",
            "environment_prefix",
            "runtime",
            "os",
            "architecture",
            "source_revision",
            "target_tree_sha256",
            "wheel_sha256",
        },
        context,
    )
    if worker["subject_id"] != subject_id:
        raise ContractError(f"{context}.subject_id differs from the measured subject")
    for name in (
        "starlette_version",
        "module_path",
        "python_executable",
        "environment_prefix",
        "runtime",
        "os",
        "architecture",
    ):
        _string(worker[name], f"{context}.{name}")

    if subject_id == "starlette-python":
        if (
            worker["starlette_version"] != "1.6.0"
            or worker["package_version"] is not None
            or worker["core_extension_path"] is not None
            or worker["source_revision"] != ORACLE_COMMIT
            or worker["target_tree_sha256"] is not None
            or worker["wheel_sha256"] is not None
        ):
            raise ContractError(f"{context} does not identify the pinned Starlette source")
        return

    if subject_id != "python-package-cpython312":
        raise ContractError(f"{context} has an unsupported measured worker subject")
    if (
        worker["starlette_version"] != "0.1.0"
        or worker["package_version"] != "0.1.0"
        or worker["source_revision"] is not None
    ):
        raise ContractError(f"{context} does not identify the installed Python package")
    _string(worker["core_extension_path"], f"{context}.core_extension_path")
    _validate_sha256(worker["target_tree_sha256"], f"{context}.target_tree_sha256")
    _validate_sha256(worker["wheel_sha256"], f"{context}.wheel_sha256")


def _validate_benchmark_result_artifact(value: Any) -> dict[str, Any]:
    _exact(
        value,
        {"schema", "identity", "status", "summary", "workloads", "upstream_suite"},
        "benchmark result",
    )
    if value["schema"] != BENCHMARK_RESULT_SCHEMA:
        raise ContractError("unsupported benchmark result schema")
    if value["status"] not in {"completed", "not_proven"}:
        raise ContractError("benchmark result status is invalid")

    identity = _exact(
        value["identity"],
        {
            "run_id",
            "started_at",
            "finished_at",
            "manifest",
            "benchmark_inputs",
            "parity_case_input",
            "source_validation",
            "parity_gate",
            "native_parity_adapter",
            "prepared_environments",
            "machine",
            "command",
        },
        "benchmark result.identity",
    )
    for name in ("run_id", "started_at", "finished_at"):
        _string(identity[name], f"benchmark result.identity.{name}")
    manifest = _exact(
        identity["manifest"], {"path", "schema", "sha256"}, "benchmark identity.manifest"
    )
    if manifest["path"] != "tests/fixtures/manifest.yaml" or manifest["schema"] != MANIFEST_SCHEMA:
        raise ContractError("benchmark result manifest identity differs from the active contract")
    _validate_sha256(manifest["sha256"], "benchmark identity.manifest.sha256")

    benchmark_inputs = identity["benchmark_inputs"]
    if not isinstance(benchmark_inputs, list) or len(benchmark_inputs) != 1:
        raise ContractError("benchmark result must bind exactly one benchmark input file")
    benchmark_input = _exact(
        benchmark_inputs[0],
        {"path", "schema", "sha256"},
        "benchmark result.identity.benchmark_inputs[0]",
    )
    if (
        not isinstance(benchmark_input["path"], str)
        or benchmark_input["path"] != "build/parity/inputs/benchmark/asgi-get-hello.json"
        or benchmark_input["schema"] != BENCHMARK_INPUT_SCHEMA
    ):
        raise ContractError("benchmark result input identity is outside the indexed benchmark lane")
    _validate_sha256(benchmark_input["sha256"], "benchmark identity.benchmark_inputs[0].sha256")

    parity_case_input = _exact(
        identity["parity_case_input"],
        {"case_id", "path", "sha256", "case_sha256"},
        "benchmark result.identity.parity_case_input",
    )
    _string(parity_case_input["case_id"], "benchmark identity.parity_case_input.case_id")
    if parity_case_input["case_id"] != "starlette.applications.Starlette.__call__.get-hello":
        raise ContractError("benchmark result is not bound to the declared GET /hello parity case")
    if not isinstance(parity_case_input["path"], str) or not parity_case_input["path"].startswith(
        "build/parity/inputs/parity/"
    ):
        raise ContractError("benchmark parity case identity is outside the parity input lane")
    _validate_sha256(parity_case_input["sha256"], "benchmark parity input.sha256")
    _validate_sha256(parity_case_input["case_sha256"], "benchmark parity input.case_sha256")

    source_validation = _exact(
        identity["source_validation"],
        {
            "schema",
            "scope_mode",
            "scope_id",
            "oracle_commit",
            "oracle_package",
            "runtime_dependency_lock_sha256",
            "indexed_input_files",
            "cases",
            "target_profiles",
            "operations",
            "parity_tooling_sources_compiled",
            "parity_passes_claimed",
        },
        "benchmark result.identity.source_validation",
    )
    if (
        source_validation["schema"] != MANIFEST_SCHEMA
        or source_validation["oracle_commit"] != ORACLE_COMMIT
        or source_validation["parity_passes_claimed"] != 0
    ):
        raise ContractError("benchmark source validation identity differs from the pinned contract")
    for name in ("scope_mode", "scope_id", "oracle_package"):
        _string(source_validation[name], f"benchmark source_validation.{name}")
    _validate_sha256(
        source_validation["runtime_dependency_lock_sha256"],
        "benchmark source_validation.runtime_dependency_lock_sha256",
    )
    for name in (
        "indexed_input_files",
        "cases",
        "target_profiles",
        "operations",
        "parity_tooling_sources_compiled",
    ):
        _validate_nonnegative_integer(
            source_validation[name], f"benchmark source_validation.{name}"
        )

    gate = _exact(
        identity["parity_gate"],
        {
            "status",
            "case_id",
            "parity_run_id",
            "parity_result_path",
            "parity_result_sha256",
            "profiles",
            "summary",
            "oracles",
            "targets",
            "comparison_outcomes",
            "infrastructure_errors",
        },
        "benchmark result.identity.parity_gate",
    )
    if gate["status"] not in {"pass", "failed"}:
        raise ContractError("benchmark correctness gate status is invalid")
    if (
        gate["case_id"] != parity_case_input["case_id"]
        or gate["parity_result_path"] != "build/parity/benchmark-correctness-result.json"
    ):
        raise ContractError("benchmark correctness gate does not identify its resolved input")
    _string(gate["parity_run_id"], "benchmark correctness gate.parity_run_id")
    _validate_sha256(gate["parity_result_sha256"], "benchmark correctness gate result hash")
    if gate["profiles"] != ["python-package-cpython312", "rust-native-local"]:
        raise ContractError("benchmark correctness gate must include both declared target profiles")
    gate_summary = _exact(
        gate["summary"],
        {"selected", "executed", "passed", "failed", "not_run", "infrastructure_errors"},
        "benchmark correctness gate.summary",
    )
    for name, count in gate_summary.items():
        _validate_nonnegative_integer(count, f"benchmark correctness gate.summary.{name}")
    if not isinstance(gate["oracles"], list) or not isinstance(gate["targets"], list):
        raise ContractError("benchmark correctness gate identities must be arrays")
    oracle_ids: set[str] = set()
    for index, oracle in enumerate(gate["oracles"]):
        oracle = _exact(
            oracle,
            {
                "oracle_id",
                "name",
                "version",
                "revision",
                "runtime",
                "module_path",
                "dependency_lock_sha256",
                "os",
                "architecture",
                "environment_sha256",
                "runtime_lock_sha256",
            },
            f"benchmark correctness gate.oracles[{index}]",
        )
        if oracle["oracle_id"] != "starlette-python" or oracle["revision"] != ORACLE_COMMIT:
            raise ContractError("benchmark correctness gate oracle identity differs")
        if oracle["oracle_id"] in oracle_ids:
            raise ContractError("benchmark correctness gate repeats an oracle identity")
        oracle_ids.add(oracle["oracle_id"])
        for name in (
            "name",
            "version",
            "runtime",
            "module_path",
            "os",
            "architecture",
        ):
            _string(oracle[name], f"benchmark correctness gate oracle.{name}")
        for name in (
            "dependency_lock_sha256",
            "environment_sha256",
            "runtime_lock_sha256",
        ):
            _validate_sha256(oracle[name], f"benchmark correctness gate oracle.{name}")
    target_profiles: set[str] = set()
    for index, target in enumerate(gate["targets"]):
        target = _exact(
            target,
            {
                "target_profile",
                "target_id",
                "revision",
                "dirty",
                "runtime",
                "backend",
                "features",
                "package_version",
                "target_tree_sha256",
                "dependency_lock_sha256",
                "os",
                "architecture",
                "environment_sha256",
            },
            f"benchmark correctness gate.targets[{index}]",
        )
        if target["target_profile"] not in {"rust-native-local", "python-package-cpython312"}:
            raise ContractError("benchmark correctness gate contains an unknown target profile")
        if target["target_profile"] in target_profiles:
            raise ContractError("benchmark correctness gate repeats a target profile")
        target_profiles.add(target["target_profile"])
        for name in ("target_id", "revision", "runtime", "backend", "os", "architecture"):
            _string(target[name], f"benchmark correctness gate target.{name}")
        if not isinstance(target["dirty"], bool):
            raise ContractError("benchmark correctness gate target dirty state must be boolean")
        if not isinstance(target["features"], list) or any(
            not isinstance(feature, str) for feature in target["features"]
        ):
            raise ContractError("benchmark correctness gate target features must be strings")
        if target["package_version"] is not None:
            _string(target["package_version"], "benchmark correctness gate target.package_version")
        if target["target_tree_sha256"] is not None:
            _validate_sha256(
                target["target_tree_sha256"], "benchmark correctness gate target.target_tree_sha256"
            )
        _validate_sha256(
            target["dependency_lock_sha256"],
            "benchmark correctness gate target.dependency_lock_sha256",
        )
        if target["environment_sha256"] is not None:
            _validate_sha256(
                target["environment_sha256"], "benchmark correctness gate target.environment_sha256"
            )
    if oracle_ids not in ({"starlette-python"}, set()) or (
        gate["status"] == "pass" and oracle_ids != {"starlette-python"}
    ):
        raise ContractError("benchmark correctness gate contains an unknown oracle inventory")
    expected_profiles = {"rust-native-local", "python-package-cpython312"}
    if (gate["status"] == "pass" and target_profiles != expected_profiles) or (
        gate["status"] == "failed" and not target_profiles <= expected_profiles
    ):
        raise ContractError(
            "benchmark correctness gate must identify both declared target profiles"
        )
    outcomes = gate["comparison_outcomes"]
    if not isinstance(outcomes, list):
        raise ContractError("benchmark correctness gate comparison outcomes must be an array")
    outcome_profiles: set[str] = set()
    for index, outcome in enumerate(outcomes):
        outcome = _exact(
            outcome,
            {"target_profile", "outcome"},
            f"benchmark correctness gate.comparison_outcomes[{index}]",
        )
        if (
            outcome["target_profile"] not in {"rust-native-local", "python-package-cpython312"}
            or outcome["target_profile"] in outcome_profiles
            or outcome["outcome"] not in {"pass", "fail", "not_run"}
        ):
            raise ContractError("benchmark correctness gate has invalid or duplicate outcomes")
        outcome_profiles.add(outcome["target_profile"])
    if not isinstance(gate["infrastructure_errors"], list):
        raise ContractError("benchmark correctness gate infrastructure errors must be an array")
    for index, error in enumerate(gate["infrastructure_errors"]):
        error = _exact(
            error,
            {"scope", "id", "kind", "message"},
            f"benchmark correctness gate.infrastructure_errors[{index}]",
        )
        _string(error["scope"], f"benchmark correctness gate.infrastructure_errors[{index}].scope")
        _string(error["kind"], f"benchmark correctness gate.infrastructure_errors[{index}].kind")
        _string(
            error["message"], f"benchmark correctness gate.infrastructure_errors[{index}].message"
        )
        if error["id"] is not None:
            _string(error["id"], f"benchmark correctness gate.infrastructure_errors[{index}].id")
    if gate["status"] == "pass" and (
        gate_summary["failed"]
        or gate_summary["not_run"]
        or gate_summary["infrastructure_errors"]
        or len(outcomes) != 2
        or any(item["outcome"] != "pass" for item in outcomes)
    ):
        raise ContractError("passing benchmark correctness gate requires both exact target passes")

    adapter = _exact(
        identity["native_parity_adapter"],
        {"argv", "path", "sha256"},
        "benchmark result.identity.native_parity_adapter",
    )
    if (
        not isinstance(adapter["argv"], list)
        or not adapter["argv"]
        or any(not isinstance(part, str) for part in adapter["argv"])
        or not isinstance(adapter["path"], str)
        or Path(adapter["path"]).is_absolute()
    ):
        raise ContractError("benchmark native adapter identity is malformed")
    _validate_sha256(adapter["sha256"], "benchmark native adapter.sha256")

    environments = identity["prepared_environments"]
    expected_environment_ids = {"starlette-oracle-cpython312", "starlette-rs-py-cpython312"}
    if not isinstance(environments, list) or len(environments) != 2:
        raise ContractError("benchmark result must identify both prepared Python environments")
    environment_ids: set[str] = set()
    for index, environment in enumerate(environments):
        environment = _exact(
            environment,
            {
                "id",
                "python",
                "runtime",
                "os",
                "architecture",
                "dependency_lock_path",
                "dependency_lock_sha256",
                "installed_lock_sha256",
                "artifact_sha256",
                "environment_sha256",
            },
            f"benchmark result.identity.prepared_environments[{index}]",
        )
        if (
            environment["id"] not in expected_environment_ids
            or environment["id"] in environment_ids
        ):
            raise ContractError("benchmark result contains unknown or duplicate environments")
        environment_ids.add(environment["id"])
        for name in ("python", "runtime", "os", "architecture", "dependency_lock_path"):
            _string(environment[name], f"benchmark environment.{name}")
        for name in (
            "dependency_lock_sha256",
            "installed_lock_sha256",
            "environment_sha256",
        ):
            _validate_sha256(environment[name], f"benchmark environment.{name}")
        if environment["artifact_sha256"] is not None:
            _validate_sha256(
                environment["artifact_sha256"], "benchmark environment.artifact_sha256"
            )

    machine = _exact(
        identity["machine"],
        {
            "platform",
            "architecture",
            "processor",
            "logical_cpu_count",
            "python",
            "python_executable",
            "rustc",
            "cargo",
        },
        "benchmark result.identity.machine",
    )
    for name in ("platform", "architecture", "processor", "python", "python_executable"):
        if name == "processor":
            if not isinstance(machine[name], str):
                raise ContractError("benchmark machine.processor must be a string")
        elif machine[name] is not None:
            _string(machine[name], f"benchmark machine.{name}")
    if machine["logical_cpu_count"] is not None:
        _validate_nonnegative_integer(
            machine["logical_cpu_count"], "benchmark machine.logical_cpu_count"
        )
    for name in ("rustc", "cargo"):
        if machine[name] is not None:
            _string(machine[name], f"benchmark machine.{name}")
    command = _exact(identity["command"], {"argv", "cwd"}, "benchmark result.identity.command")
    if (
        not isinstance(command["argv"], list)
        or not command["argv"]
        or any(not isinstance(part, str) for part in command["argv"])
    ):
        raise ContractError("benchmark command argv must be a non-empty string array")
    _string(command["cwd"], "benchmark command.cwd")

    workloads = value["workloads"]
    if not isinstance(workloads, list) or len(workloads) != 1:
        raise ContractError("benchmark result must include exactly one declared workload")
    workload = _exact(
        workloads[0],
        {
            "workload_id",
            "covers",
            "input",
            "correctness_gate",
            "measurement_policy",
            "subjects",
            "comparison",
        },
        "benchmark result.workloads[0]",
    )
    _string(workload["workload_id"], "benchmark workload.workload_id")
    if workload["workload_id"] != "starlette.asgi.get-hello.direct-dispatch":
        raise ContractError("benchmark result identifies an unknown workload")
    if not isinstance(workload["covers"], list) or not workload["covers"]:
        raise ContractError("benchmark workload covers must be a non-empty array")
    if workload["covers"] != ["starlette.asgi.get-hello.latency"]:
        raise ContractError("benchmark result coverage differs from the declared workload")
    workload_input = _exact(workload["input"], {"kind", "case_id"}, "benchmark workload.input")
    if (
        workload_input["kind"] != "parity_case"
        or workload_input["case_id"] != parity_case_input["case_id"]
    ):
        raise ContractError("benchmark workload input does not match the hashed parity case")
    gate_evidence = workload["correctness_gate"]
    if gate["status"] == "pass":
        gate_evidence = _exact(
            gate_evidence,
            {
                "status",
                "case_id",
                "parity_run_id",
                "parity_result_path",
                "parity_result_sha256",
                "profiles",
                "summary",
                "oracles",
                "targets",
                "comparison_outcomes",
                "infrastructure_errors",
                "observation_sha256",
                "exact_source_package_observations",
            },
            "benchmark workload.correctness_gate",
        )
        _validate_sha256(gate_evidence["observation_sha256"], "benchmark exact probe hash")
        if gate_evidence["exact_source_package_observations"] != "pass":
            raise ContractError("benchmark source/package probe must pass exact comparison")
    else:
        _exact(
            gate_evidence,
            {
                "status",
                "case_id",
                "parity_run_id",
                "parity_result_path",
                "parity_result_sha256",
                "profiles",
                "summary",
                "oracles",
                "targets",
                "comparison_outcomes",
                "infrastructure_errors",
            },
            "benchmark workload.correctness_gate",
        )
    if (
        gate_evidence["status"] != gate["status"]
        or gate_evidence["case_id"] != parity_case_input["case_id"]
    ):
        raise ContractError("workload correctness gate differs from benchmark identity")
    gate_identity = {key: gate_evidence[key] for key in gate}
    if gate_identity != gate:
        raise ContractError("workload correctness gate evidence differs from the run identity")

    policy = _exact(
        workload["measurement_policy"],
        {
            "boundary",
            "step_ids",
            "metrics",
            "warmup_iterations",
            "measurement_iterations",
            "samples",
            "concurrency",
            "cache_state",
            "correctness_gate",
        },
        "benchmark workload.measurement_policy",
    )
    if (
        policy["boundary"] != "observed_steps"
        or policy["step_ids"] != ["dispatch"]
        or policy["metrics"] != ["latency"]
        or policy["cache_state"] != "warm"
        or policy["concurrency"] != 1
        or policy["correctness_gate"] != "parity_pass"
    ):
        raise ContractError(
            "benchmark result measurement policy differs from the declared smoke lane"
        )
    for name in ("warmup_iterations", "measurement_iterations", "samples"):
        if not isinstance(policy[name], int) or isinstance(policy[name], bool) or policy[name] <= 0:
            raise ContractError(f"benchmark measurement_policy.{name} must be a positive integer")
    if (policy["warmup_iterations"], policy["measurement_iterations"], policy["samples"]) != (
        20,
        100,
        30,
    ):
        raise ContractError(
            "benchmark measurement counts differ from the indexed deterministic policy"
        )

    subjects = workload["subjects"]
    expected_subjects = ["starlette-python", "rust-native-local", "python-package-cpython312"]
    if not isinstance(subjects, list) or len(subjects) != len(expected_subjects):
        raise ContractError("benchmark workload must include all declared runtime subjects")
    subject_statuses: dict[str, str] = {}
    for index, subject in enumerate(subjects):
        if not isinstance(subject, dict) or subject.get("subject_id") != expected_subjects[index]:
            raise ContractError("benchmark workload subjects differ from the manifest order")
        subject_id = subject["subject_id"]
        if subject.get("status") == "not_run":
            _exact(
                subject,
                {"subject_id", "status", "identity", "reason"},
                f"benchmark workload.subjects[{index}]",
            )
            _string(subject["reason"], f"benchmark workload.subjects[{index}].reason")
            _validate_not_run_subject_identity(
                subject["identity"],
                subject_id,
                f"benchmark workload.subjects[{index}].identity",
            )
        elif subject.get("status") == "measured":
            _exact(
                subject,
                {"subject_id", "status", "identity", "capabilities", "measurement"},
                f"benchmark workload.subjects[{index}]",
            )
            if subject_id == "rust-native-local" or not isinstance(subject["identity"], dict):
                raise ContractError("only Python subjects can have measured worker identities")
            _validate_worker_identity(
                subject["identity"], subject_id, f"benchmark workload.subjects[{index}].identity"
            )
            capabilities = _exact(
                subject["capabilities"],
                {"router_instance_is_asgi_callable", "gzip_middleware_module_available"},
                f"benchmark workload.subjects[{index}].capabilities",
            )
            if any(not isinstance(item, bool) for item in capabilities.values()):
                raise ContractError("benchmark capability results must be booleans")
            measurement = _exact(
                subject["measurement"],
                {
                    "unit",
                    "warmup_iterations",
                    "measurement_iterations_per_sample",
                    "samples",
                    "statistics",
                },
                f"benchmark workload.subjects[{index}].measurement",
            )
            if measurement["unit"] != "nanoseconds_per_dispatch":
                raise ContractError("benchmark measurement unit is invalid")
            if (
                measurement["warmup_iterations"] != policy["warmup_iterations"]
                or measurement["measurement_iterations_per_sample"]
                != policy["measurement_iterations"]
            ):
                raise ContractError("benchmark worker counts differ from the declared policy")
            samples = measurement["samples"]
            if not isinstance(samples, list) or len(samples) != policy["samples"]:
                raise ContractError(
                    "benchmark worker samples differ from the declared sample count"
                )
            if any(
                not isinstance(sample, (int, float))
                or isinstance(sample, bool)
                or not math.isfinite(sample)
                or sample <= 0
                for sample in samples
            ):
                raise ContractError("benchmark samples must be positive finite numbers")
            stats = _exact(
                measurement["statistics"],
                {"median", "mean", "stdev", "min", "max", "p50", "p95", "p99"},
                f"benchmark workload.subjects[{index}].measurement.statistics",
            )
            if any(
                not isinstance(number, (int, float))
                or isinstance(number, bool)
                or not math.isfinite(number)
                for number in stats.values()
            ):
                raise ContractError("benchmark statistics must be numeric")
            expected_statistics = {
                "median": statistics.median(samples),
                "mean": statistics.fmean(samples),
                "stdev": statistics.stdev(samples) if len(samples) > 1 else 0.0,
                "min": min(samples),
                "max": max(samples),
                "p50": _sample_quantile(samples, 0.50),
                "p95": _sample_quantile(samples, 0.95),
                "p99": _sample_quantile(samples, 0.99),
            }
            if any(
                not math.isclose(stats[name], expected, rel_tol=1e-12, abs_tol=1e-9)
                for name, expected in expected_statistics.items()
            ):
                raise ContractError("benchmark statistics differ from their sample distribution")
        else:
            raise ContractError(f"benchmark workload.subjects[{index}].status is invalid")
        subject_statuses[subject_id] = subject["status"]

    comparison = workload["comparison"]
    if comparison.get("status") == "not_run":
        comparison = _exact(comparison, {"status", "reason"}, "benchmark workload.comparison")
        _string(comparison["reason"], "benchmark workload.comparison.reason")
    elif comparison.get("status") == "measured":
        comparison = _exact(
            comparison,
            {
                "status",
                "source_subject_id",
                "target_subject_id",
                "latency_unit",
                "source_median",
                "target_median",
                "target_over_source_median_ratio",
                "source_over_target_median_speedup",
                "sample_count",
                "measurement_iterations_per_sample",
            },
            "benchmark workload.comparison",
        )
        if (
            comparison["source_subject_id"] != "starlette-python"
            or comparison["target_subject_id"] != "python-package-cpython312"
            or comparison["latency_unit"] != "nanoseconds_per_dispatch"
        ):
            raise ContractError("benchmark comparison subjects or units are invalid")
        for name in (
            "source_median",
            "target_median",
            "target_over_source_median_ratio",
            "source_over_target_median_speedup",
        ):
            number = comparison[name]
            if not isinstance(number, (int, float)) or isinstance(number, bool) or number <= 0:
                raise ContractError(f"benchmark comparison.{name} must be positive")
        if (
            comparison["sample_count"] != policy["samples"]
            or comparison["measurement_iterations_per_sample"] != policy["measurement_iterations"]
        ):
            raise ContractError("benchmark comparison counts differ from the declared policy")
        source_measurement = next(
            subject["measurement"]
            for subject in subjects
            if subject["subject_id"] == "starlette-python"
        )
        target_measurement = next(
            subject["measurement"]
            for subject in subjects
            if subject["subject_id"] == "python-package-cpython312"
        )
        source_median = source_measurement["statistics"]["median"]
        target_median = target_measurement["statistics"]["median"]
        if (
            comparison["source_median"] != source_median
            or comparison["target_median"] != target_median
            or not math.isclose(
                comparison["target_over_source_median_ratio"],
                target_median / source_median,
                rel_tol=1e-12,
            )
            or not math.isclose(
                comparison["source_over_target_median_speedup"],
                source_median / target_median,
                rel_tol=1e-12,
            )
        ):
            raise ContractError("benchmark comparison differs from the measured medians")
    else:
        raise ContractError("benchmark comparison status is invalid")

    upstream = value["upstream_suite"]
    if gate["status"] == "failed":
        upstream = _exact(
            upstream,
            {
                "status",
                "source_revision",
                "documented_workload_count",
                "matched_workload_count",
                "not_run_workload_count",
                "reason",
                "workloads",
            },
            "benchmark upstream_suite",
        )
        if "source_supported" in upstream or "target_supported" in upstream:
            raise ContractError("unprobed capability claims are forbidden after gate failure")
        _string(upstream["reason"], "benchmark upstream_suite.reason")
    else:
        upstream = _exact(
            upstream,
            {
                "status",
                "source_revision",
                "documented_workload_count",
                "matched_workload_count",
                "not_run_workload_count",
                "source_files",
                "source_workload_categories",
                "workloads",
            },
            "benchmark upstream_suite",
        )
        source_files = upstream["source_files"]
        if not isinstance(source_files, list) or len(source_files) != 3:
            raise ContractError("benchmark result must identify all three pinned benchmark sources")
        for index, source_file in enumerate(source_files):
            source_file = _exact(
                source_file,
                {"path", "sha256"},
                f"benchmark upstream_suite.source_files[{index}]",
            )
            expected_source_paths = {
                "benchmarks/README.md",
                "benchmarks/routing_benchmark.py",
                "benchmarks/gzip_benchmark.py",
            }
            if source_file["path"] not in expected_source_paths:
                raise ContractError("benchmark result names an unknown pinned source file")
            _validate_sha256(source_file["sha256"], f"benchmark source_file[{index}].sha256")
        if {item["path"] for item in source_files} != expected_source_paths:
            raise ContractError(
                "benchmark source identity must include the complete pinned source set"
            )
        categories = upstream["source_workload_categories"]
        if not isinstance(categories, list) or len(categories) != 2:
            raise ContractError("benchmark upstream suite must report router and gzip categories")
        for index, category in enumerate(categories):
            category = _exact(
                category,
                {
                    "name",
                    "count",
                    "source_supported",
                    "target_supported",
                    "target_status",
                    "not_run_count",
                },
                f"benchmark upstream_suite.source_workload_categories[{index}]",
            )
            expected_name, expected_count = (("router", 6), ("gzip", 68))[index]
            if (
                category["name"] != expected_name
                or category["count"] != expected_count
                or not isinstance(category["source_supported"], bool)
                or not isinstance(category["target_supported"], bool)
                or category["target_status"] not in {"blocked", "not_implemented"}
                or category["target_status"]
                != ("not_implemented" if category["target_supported"] else "blocked")
                or category["not_run_count"] != expected_count
            ):
                raise ContractError("benchmark upstream workload category evidence is inconsistent")

    if (
        upstream["status"] != "not_run"
        or upstream["source_revision"] != ORACLE_COMMIT
        or upstream["documented_workload_count"] != 74
        or upstream["matched_workload_count"] != 0
        or upstream["not_run_workload_count"] != 74
    ):
        raise ContractError("the 74 source-documented workloads must remain visible as not_run")
    upstream_rows = upstream["workloads"]
    if not isinstance(upstream_rows, list) or len(upstream_rows) != 74:
        raise ContractError("benchmark upstream workload inventory must contain 74 rows")
    upstream_ids: set[str] = set()
    upstream_categories = {"router": 0, "gzip": 0}
    for index, row in enumerate(upstream_rows):
        row = _exact(
            row,
            {"workload_id", "category", "status", "reason"},
            f"benchmark upstream_suite.workloads[{index}]",
        )
        _string(row["workload_id"], f"benchmark upstream workload[{index}].workload_id")
        if (
            row["workload_id"] in upstream_ids
            or row["category"] not in upstream_categories
            or row["status"] != "not_run"
        ):
            raise ContractError("benchmark upstream workload rows have duplicate or invalid status")
        upstream_ids.add(row["workload_id"])
        upstream_categories[row["category"]] += 1
        _string(row["reason"], f"benchmark upstream workload[{index}].reason")
    if upstream_categories != {"router": 6, "gzip": 68}:
        raise ContractError("benchmark upstream workload category counts differ from the source")

    summary = _exact(
        value["summary"],
        {
            "declared_workloads",
            "measured_workloads",
            "measured_subjects",
            "not_run_subjects",
            "source_documented_workloads",
            "source_documented_workloads_matched",
            "source_documented_workloads_not_run",
        },
        "benchmark result.summary",
    )
    for name, count in summary.items():
        _validate_nonnegative_integer(count, f"benchmark result.summary.{name}")
    measured_subject_count = sum(status == "measured" for status in subject_statuses.values())
    expected_summary = {
        "declared_workloads": 1,
        "measured_workloads": int(
            subject_statuses.get("starlette-python") == "measured"
            and subject_statuses.get("python-package-cpython312") == "measured"
        ),
        "measured_subjects": measured_subject_count,
        "not_run_subjects": len(subject_statuses) - measured_subject_count,
        "source_documented_workloads": 74,
        "source_documented_workloads_matched": 0,
        "source_documented_workloads_not_run": 74,
    }
    if summary != expected_summary:
        raise ContractError("benchmark result summary does not equal its subject evidence counts")
    if value["status"] != "not_proven":
        raise ContractError(
            "benchmark cannot be completed while Rust-native or source workloads are not_run"
        )
    if gate["status"] == "failed" and any(
        status != "not_run" for status in subject_statuses.values()
    ):
        raise ContractError("benchmark gate failure cannot produce measured subjects")
    if gate["status"] == "pass" and subject_statuses.get("rust-native-local") != "not_run":
        raise ContractError(
            "Rust-native must remain not_run until its dispatch boundary is equivalent"
        )
    if (comparison.get("status") == "measured") != (expected_summary["measured_workloads"] == 1):
        raise ContractError("benchmark comparison status differs from measured workload evidence")
    return value


def _validate_positive_finite_number(value: Any, context: str, *, allow_zero: bool = False) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ContractError(f"{context} must be a finite {qualifier} number")


def _validate_upstream_measurement_policy(value: Any, context: str) -> dict[str, Any]:
    policy = _exact(
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
    for name in ("setup_outside_timer", "post_timer_checks"):
        rows = policy[name]
        if not isinstance(rows, list) or not rows:
            raise ContractError(f"{context}.{name} must be a non-empty string array")
        for index, row in enumerate(rows):
            _string(row, f"{context}.{name}[{index}]")
    timed_call = _exact(
        policy["timed_call"],
        {"boundary_id", "includes"},
        f"{context}.timed_call",
    )
    _string(timed_call["boundary_id"], f"{context}.timed_call.boundary_id")
    if not isinstance(timed_call["includes"], list) or not timed_call["includes"]:
        raise ContractError(f"{context}.timed_call.includes must be a non-empty string array")
    for index, item in enumerate(timed_call["includes"]):
        _string(item, f"{context}.timed_call.includes[{index}]")

    harness = _exact(
        policy["source_harness"],
        {"package", "method", "marker", "rounds"},
        f"{context}.source_harness",
    )
    _string(harness["package"], f"{context}.source_harness.package")
    if harness["package"] != "pytest-codspeed":
        raise ContractError(f"{context}.source_harness.package differs from the pinned benchmark")
    if harness["method"] not in {"benchmark", "benchmark.pedantic"}:
        raise ContractError(f"{context}.source_harness.method is unsupported")
    marker = harness["marker"]
    if marker is not None:
        marker = _exact(
            marker,
            {"max_time_seconds", "max_rounds"},
            f"{context}.source_harness.marker",
        )
        _validate_positive_finite_number(
            marker["max_time_seconds"], f"{context}.source_harness.marker.max_time_seconds"
        )
        if not isinstance(marker["max_rounds"], int) or isinstance(marker["max_rounds"], bool):
            raise ContractError(f"{context}.source_harness.marker.max_rounds must be an integer")
        _validate_nonnegative_integer(
            marker["max_rounds"], f"{context}.source_harness.marker.max_rounds"
        )
        if marker["max_rounds"] == 0:
            raise ContractError(f"{context}.source_harness.marker.max_rounds must be positive")
    if harness["rounds"] is not None:
        if not isinstance(harness["rounds"], int) or isinstance(harness["rounds"], bool):
            raise ContractError(f"{context}.source_harness.rounds must be an integer or null")
        if harness["rounds"] <= 0:
            raise ContractError(f"{context}.source_harness.rounds must be positive")

    runner_policy = _exact(
        policy["runner_policy"],
        {"warmup_iterations", "samples", "iterations_per_sample", "sample_statistic"},
        f"{context}.runner_policy",
    )
    for name in ("warmup_iterations", "samples", "iterations_per_sample"):
        number = runner_policy[name]
        if not isinstance(number, int) or isinstance(number, bool):
            raise ContractError(f"{context}.runner_policy.{name} must be an integer")
        if number < (0 if name == "warmup_iterations" else 1):
            raise ContractError(f"{context}.runner_policy.{name} is out of range")
    if runner_policy["sample_statistic"] != "mean_call_duration":
        raise ContractError(f"{context}.runner_policy.sample_statistic is unsupported")
    return policy


def _validate_upstream_measurement(value: Any, context: str) -> dict[str, Any]:
    measurement = _exact(
        value,
        {
            "unit",
            "runner_policy",
            "warmup_iterations",
            "samples",
            "iterations_per_sample",
            "statistics",
        },
        context,
    )
    if measurement["unit"] != "nanoseconds_per_operation":
        raise ContractError(f"{context}.unit is invalid")
    runner_policy = _exact(
        measurement["runner_policy"],
        {"warmup_iterations", "samples", "iterations_per_sample", "sample_statistic"},
        f"{context}.runner_policy",
    )
    for name in ("warmup_iterations", "samples", "iterations_per_sample"):
        number = runner_policy[name]
        if not isinstance(number, int) or isinstance(number, bool):
            raise ContractError(f"{context}.runner_policy.{name} must be an integer")
        if number < (0 if name == "warmup_iterations" else 1):
            raise ContractError(f"{context}.runner_policy.{name} is out of range")
    if runner_policy["sample_statistic"] != "mean_call_duration":
        raise ContractError(f"{context}.runner_policy.sample_statistic is unsupported")
    if (
        measurement["warmup_iterations"] != runner_policy["warmup_iterations"]
        or measurement["iterations_per_sample"] != runner_policy["iterations_per_sample"]
    ):
        raise ContractError(f"{context} counts differ from runner_policy")
    samples = measurement["samples"]
    if not isinstance(samples, list) or len(samples) != runner_policy["samples"]:
        raise ContractError(f"{context}.samples differs from runner_policy.samples")
    for index, sample in enumerate(samples):
        _validate_positive_finite_number(sample, f"{context}.samples[{index}]")
    statistics_row = _exact(
        measurement["statistics"],
        {"median", "mean", "stdev", "min", "max", "p50", "p95", "p99"},
        f"{context}.statistics",
    )
    for name, number in statistics_row.items():
        _validate_positive_finite_number(
            number, f"{context}.statistics.{name}", allow_zero=name == "stdev"
        )
    expected_statistics = {
        "median": statistics.median(samples),
        "mean": statistics.fmean(samples),
        "stdev": statistics.stdev(samples) if len(samples) > 1 else 0.0,
        "min": min(samples),
        "max": max(samples),
        "p50": _sample_quantile(samples, 0.50),
        "p95": _sample_quantile(samples, 0.95),
        "p99": _sample_quantile(samples, 0.99),
    }
    if any(
        not math.isclose(statistics_row[name], expected, rel_tol=1e-12, abs_tol=1e-9)
        for name, expected in expected_statistics.items()
    ):
        raise ContractError(f"{context}.statistics differ from the sample distribution")
    return measurement


def _validate_upstream_worker_identity(value: Any, subject_id: str, context: str) -> dict[str, Any]:
    capabilities = {
        "router_instance_is_asgi_callable",
        "gzip_middleware_available",
    }
    if subject_id == "starlette-python":
        identity = _exact(
            value,
            {
                "subject_id",
                "starlette_version",
                "source_revision",
                "module_path",
                "python_executable",
                "environment_prefix",
                "runtime",
                "os",
                "architecture",
                "capabilities",
            },
            context,
        )
        if (
            identity["subject_id"] != subject_id
            or identity["starlette_version"] != "1.6.0"
            or identity["source_revision"] != ORACLE_COMMIT
        ):
            raise ContractError(f"{context} does not identify the pinned Starlette source")
    else:
        identity = _exact(
            value,
            {
                "subject_id",
                "starlette_version",
                "package_version",
                "module_path",
                "core_extension_path",
                "python_executable",
                "environment_prefix",
                "runtime",
                "os",
                "architecture",
                "target_tree_sha256",
                "wheel_sha256",
                "capabilities",
            },
            context,
        )
        if (
            identity["subject_id"] != subject_id
            or identity["starlette_version"] != "0.1.0"
            or identity["package_version"] != "0.1.0"
        ):
            raise ContractError(f"{context} does not identify the installed Python package")
        _validate_sha256(identity["target_tree_sha256"], f"{context}.target_tree_sha256")
        _validate_sha256(identity["wheel_sha256"], f"{context}.wheel_sha256")
    for name in (
        "module_path",
        "python_executable",
        "environment_prefix",
        "runtime",
        "os",
        "architecture",
    ):
        _string(identity[name], f"{context}.{name}")
    if subject_id == "python-package-cpython312":
        _string(identity["core_extension_path"], f"{context}.core_extension_path")
    capability_row = _exact(identity["capabilities"], capabilities, f"{context}.capabilities")
    if any(not isinstance(capability, bool) for capability in capability_row.values()):
        raise ContractError(f"{context}.capabilities must contain booleans")
    return identity


def _validate_upstream_target_identity(value: Any, context: str) -> dict[str, Any]:
    identity = _exact(
        value,
        {
            "target_profile",
            "target_id",
            "revision",
            "dirty",
            "runtime",
            "backend",
            "features",
            "package_version",
            "target_tree_sha256",
            "dependency_lock_sha256",
            "os",
            "architecture",
            "environment_sha256",
        },
        context,
    )
    if identity["target_profile"] not in {"rust-native-local", "python-package-cpython312"}:
        raise ContractError(f"{context}.target_profile is unsupported")
    if not isinstance(identity["dirty"], bool):
        raise ContractError(f"{context}.dirty must be boolean")
    for name in ("target_id", "revision", "runtime", "backend", "os", "architecture"):
        _string(identity[name], f"{context}.{name}")
    if not isinstance(identity["features"], list) or any(
        not isinstance(feature, str) for feature in identity["features"]
    ):
        raise ContractError(f"{context}.features must be a string array")
    if identity["package_version"] is not None:
        _string(identity["package_version"], f"{context}.package_version")
    for name in ("target_tree_sha256", "environment_sha256"):
        if identity[name] is not None:
            _validate_sha256(identity[name], f"{context}.{name}")
    _validate_sha256(identity["dependency_lock_sha256"], f"{context}.dependency_lock_sha256")
    return identity


def _validate_upstream_subject(value: Any, subject_id: str, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("subject_id") != subject_id:
        raise ContractError(f"{context} subject identity differs from the declared order")
    status = value.get("status")
    if status == "not_run":
        subject = _exact(value, {"subject_id", "status", "identity", "reason"}, context)
        if subject["identity"] is not None:
            raise ContractError(f"{context}.identity must be null before a successful probe")
        _string(subject["reason"], f"{context}.reason")
    elif status == "probed":
        subject = _exact(
            value,
            {"subject_id", "status", "identity", "input_relations"},
            context,
        )
        _validate_upstream_worker_identity(subject["identity"], subject_id, f"{context}.identity")
        _validate_upstream_relations(subject["input_relations"], f"{context}.input_relations")
    elif status == "measured":
        subject = _exact(
            value,
            {"subject_id", "status", "identity", "input_relations", "measurement"},
            context,
        )
        _validate_upstream_worker_identity(subject["identity"], subject_id, f"{context}.identity")
        _validate_upstream_relations(subject["input_relations"], f"{context}.input_relations")
        _validate_upstream_measurement(subject["measurement"], f"{context}.measurement")
    else:
        raise ContractError(f"{context}.status is invalid")
    return subject


def _validate_upstream_relations(value: Any, context: str) -> None:
    if not isinstance(value, list):
        raise ContractError(f"{context} must be an array")
    for index, relation in enumerate(value):
        relation = _exact(relation, {"relation", "status"}, f"{context}[{index}]")
        _string(relation["relation"], f"{context}[{index}].relation")
        if relation["status"] != "pass":
            raise ContractError(f"{context}[{index}].status must be pass")


def _validate_upstream_first_difference(value: Any, context: str) -> None:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    _string(value.get("path"), f"{context}.path")
    keys = set(value)
    if keys == {"path", "source_type", "target_type"}:
        _string(value["source_type"], f"{context}.source_type")
        _string(value["target_type"], f"{context}.target_type")
    elif keys == {"path", "source_keys", "target_keys"}:
        for name in ("source_keys", "target_keys"):
            if not isinstance(value[name], list) or any(
                not isinstance(item, str) for item in value[name]
            ):
                raise ContractError(f"{context}.{name} must be a string array")
    elif keys in (
        {"path", "source_length", "target_length"},
        {"path", "source_length", "target_length", "source_sha256", "target_sha256"},
    ):
        for name in ("source_length", "target_length"):
            _validate_nonnegative_integer(value[name], f"{context}.{name}")
        for name in ("source_sha256", "target_sha256"):
            if name in value:
                _validate_sha256(value[name], f"{context}.{name}")
    elif keys == {"path", "source", "target"}:
        # The first difference leaf contains values observed live from the two
        # workers, so these fields intentionally admit any JSON value.
        return
    else:
        raise ContractError(f"{context} has an unsupported difference shape")


def _validate_upstream_benchmark_result_artifact(value: Any) -> dict[str, Any]:
    from .upstream_benchmark_contract import ROUTER_WORKLOAD_IDS, UPSTREAM_WORKLOAD_IDS

    result = _exact(
        value,
        {"schema", "completion_scope", "identity", "status", "summary", "workloads"},
        "upstream benchmark result",
    )
    if result["schema"] != UPSTREAM_BENCHMARK_RESULT_SCHEMA:
        raise ContractError("unsupported upstream benchmark result schema")
    if result["completion_scope"] != "pinned source versus installed Python package":
        raise ContractError("upstream benchmark result completion scope is invalid")
    if result["status"] not in {"completed", "not_proven"}:
        raise ContractError("upstream benchmark result status is invalid")

    identity = _exact(
        result["identity"],
        {
            "run_id",
            "started_at",
            "finished_at",
            "input",
            "manifest",
            "source_revision",
            "source_files",
            "parity_gate",
            "prepared_environments",
            "machine",
            "command",
        },
        "upstream benchmark result.identity",
    )
    for name in ("run_id", "started_at", "finished_at"):
        _string(identity[name], f"upstream benchmark identity.{name}")
    input_identity = _exact(
        identity["input"], {"path", "schema", "sha256"}, "upstream benchmark identity.input"
    )
    if (
        input_identity["path"] != "build/parity/inputs/benchmark/starlette-upstream-workloads.json"
        or input_identity["schema"] != UPSTREAM_BENCHMARK_INPUT_SCHEMA
    ):
        raise ContractError(
            "upstream benchmark result input differs from the active indexed catalog"
        )
    _validate_sha256(input_identity["sha256"], "upstream benchmark identity.input.sha256")
    manifest = _exact(
        identity["manifest"],
        {"path", "schema", "sha256"},
        "upstream benchmark identity.manifest",
    )
    if manifest["path"] != "tests/fixtures/manifest.yaml" or manifest["schema"] != MANIFEST_SCHEMA:
        raise ContractError("upstream benchmark result manifest differs from the active contract")
    _validate_sha256(manifest["sha256"], "upstream benchmark identity.manifest.sha256")
    if identity["source_revision"] != ORACLE_COMMIT:
        raise ContractError("upstream benchmark result source revision differs from the pin")

    source_files = identity["source_files"]
    expected_source_files = [
        "benchmarks/routing_benchmark.py",
        "benchmarks/gzip_benchmark.py",
    ]
    if not isinstance(source_files, list) or len(source_files) != len(expected_source_files):
        raise ContractError("upstream benchmark result must identify both pinned source files")
    observed_source_files: list[str] = []
    for index, row in enumerate(source_files):
        row = _exact(row, {"path", "sha256"}, f"upstream benchmark identity.source_files[{index}]")
        observed_source_files.append(
            _string(row["path"], f"upstream benchmark source_files[{index}].path")
        )
        _validate_sha256(row["sha256"], f"upstream benchmark source_files[{index}].sha256")
    if observed_source_files != expected_source_files:
        raise ContractError("upstream benchmark source-file identity differs from the pinned suite")

    gate = _exact(
        identity["parity_gate"],
        {"path", "run_id", "sha256", "summary"},
        "upstream benchmark identity.parity_gate",
    )
    if gate["path"] != "build/parity/upstream-benchmark-correctness-result.json":
        raise ContractError("upstream benchmark parity gate path is invalid")
    if gate["run_id"] is not None:
        _string(gate["run_id"], "upstream benchmark parity_gate.run_id")
    _validate_sha256(gate["sha256"], "upstream benchmark parity_gate.sha256")
    gate_summary = _exact(
        gate["summary"],
        {"selected", "executed", "passed", "failed", "not_run", "infrastructure_errors"},
        "upstream benchmark parity_gate.summary",
    )
    for name, count in gate_summary.items():
        _validate_nonnegative_integer(count, f"upstream benchmark parity_gate.summary.{name}")

    environments = identity["prepared_environments"]
    environment_ids = ["starlette-oracle-cpython312", "starlette-rs-py-cpython312"]
    if not isinstance(environments, list) or len(environments) != len(environment_ids):
        raise ContractError("upstream benchmark result must identify both prepared environments")
    for index, environment in enumerate(environments):
        context = f"upstream benchmark identity.prepared_environments[{index}]"
        environment = _exact(
            environment,
            {
                "id",
                "python",
                "runtime",
                "os",
                "architecture",
                "dependency_lock_path",
                "dependency_lock_sha256",
                "installed_lock_sha256",
                "artifact_sha256",
                "environment_sha256",
            },
            context,
        )
        if environment["id"] != environment_ids[index]:
            raise ContractError("upstream benchmark prepared environment order differs")
        for name in ("python", "runtime", "os", "architecture"):
            _string(environment[name], f"{context}.{name}")
        if (
            environment["dependency_lock_path"]
            != "scripts/parity/locks/asgi-runtime-cpython312.txt"
        ):
            raise ContractError(
                f"{context}.dependency_lock_path differs from the active runtime lock"
            )
        for name in ("dependency_lock_sha256", "installed_lock_sha256", "environment_sha256"):
            _validate_sha256(environment[name], f"{context}.{name}")
        if index == 0:
            if environment["artifact_sha256"] is not None:
                raise ContractError(
                    f"{context}.artifact_sha256 must be null for the source environment"
                )
        else:
            _validate_sha256(environment["artifact_sha256"], f"{context}.artifact_sha256")

    machine = _exact(
        identity["machine"],
        {
            "platform",
            "architecture",
            "processor",
            "logical_cpu_count",
            "python",
            "python_executable",
        },
        "upstream benchmark identity.machine",
    )
    for name in ("platform", "architecture", "python", "python_executable"):
        _string(machine[name], f"upstream benchmark identity.machine.{name}")
    if not isinstance(machine["processor"], str):
        raise ContractError("upstream benchmark identity.machine.processor must be a string")
    if machine["logical_cpu_count"] is not None:
        _validate_nonnegative_integer(
            machine["logical_cpu_count"], "upstream benchmark identity.machine.logical_cpu_count"
        )
    command = _exact(identity["command"], {"argv", "cwd"}, "upstream benchmark identity.command")
    argv = command["argv"]
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(part, str) or not part for part in argv)
    ):
        raise ContractError("upstream benchmark identity.command.argv must be non-empty strings")
    # The executable path is machine-specific; the module and command suffix is
    # fixed by the result interface.
    if len(argv) < 4 or argv[-3:] != ["-m", "scripts.parity.cli", "benchmark-upstream"]:
        raise ContractError("upstream benchmark command identity does not name its CLI")
    _string(command["cwd"], "upstream benchmark identity.command.cwd")

    rows = result["workloads"]
    if not isinstance(rows, list) or len(rows) != len(UPSTREAM_WORKLOAD_IDS):
        raise ContractError("upstream benchmark result must account for all 74 pinned workloads")
    if [row.get("workload_id") if isinstance(row, dict) else None for row in rows] != list(
        UPSTREAM_WORKLOAD_IDS
    ):
        raise ContractError("upstream benchmark result IDs/order differ from the pinned catalog")

    counts = {"measured": 0, "not_run": 0, "failed": 0, "router_measured": 0, "gzip_measured": 0}
    worker_identities: dict[str, dict[str, Any]] = {}
    for index, row_value in enumerate(rows):
        context = f"upstream benchmark workloads[{index}]"
        if not isinstance(row_value, dict):
            raise ContractError(f"{context} must be an object")
        workload_id = UPSTREAM_WORKLOAD_IDS[index]
        category = "router" if workload_id in ROUTER_WORKLOAD_IDS else "gzip"
        status = row_value.get("status")
        if status == "measured":
            row = _exact(
                row_value,
                {
                    "workload_id",
                    "category",
                    "status",
                    "correctness_gate",
                    "measurement_policy",
                    "comparison",
                    "subjects",
                },
                context,
            )
        elif status == "not_run":
            row = _exact(
                row_value,
                {
                    "workload_id",
                    "category",
                    "status",
                    "correctness_gate",
                    "measurement_policy",
                    "subjects",
                    "reason",
                },
                context,
            )
        elif status == "failed":
            gate_value = row_value.get("correctness_gate")
            if isinstance(gate_value, dict) and set(gate_value) == {
                "status",
                "source_observation_sha256",
                "target_observation_sha256",
                "normalized_source_observation_sha256",
                "normalized_target_observation_sha256",
                "normalization",
            }:
                row = _exact(
                    row_value,
                    {
                        "workload_id",
                        "category",
                        "status",
                        "correctness_gate",
                        "comparison",
                        "subjects",
                        "reason",
                    },
                    context,
                )
            else:
                row = _exact(
                    row_value,
                    {
                        "workload_id",
                        "category",
                        "status",
                        "correctness_gate",
                        "measurement_policy",
                        "subjects",
                        "reason",
                    },
                    context,
                )
        else:
            raise ContractError(f"{context}.status is invalid")
        if row["workload_id"] != workload_id or row["category"] != category:
            raise ContractError(f"{context} workload ID/category differs from the pinned inventory")
        counts[status] += 1

        if "measurement_policy" in row:
            _validate_upstream_measurement_policy(
                row["measurement_policy"], f"{context}.measurement_policy"
            )
        if "reason" in row:
            _string(row["reason"], f"{context}.reason")

        correctness_gate = row["correctness_gate"]
        if status == "measured":
            correctness_gate = _exact(
                correctness_gate,
                {
                    "status",
                    "source_observation_sha256",
                    "target_observation_sha256",
                    "normalized_source_observation_sha256",
                    "normalized_target_observation_sha256",
                    "normalization",
                },
                f"{context}.correctness_gate",
            )
            if correctness_gate["status"] != "pass":
                raise ContractError(f"{context}.correctness_gate must pass for measured rows")
            for name in (
                "source_observation_sha256",
                "target_observation_sha256",
                "normalized_source_observation_sha256",
                "normalized_target_observation_sha256",
            ):
                _validate_sha256(correctness_gate[name], f"{context}.correctness_gate.{name}")
            if (
                correctness_gate["normalized_source_observation_sha256"]
                != correctness_gate["normalized_target_observation_sha256"]
            ):
                raise ContractError(
                    f"{context}.correctness_gate normalized observations must match"
                )
            _string(correctness_gate["normalization"], f"{context}.correctness_gate.normalization")
            comparison = _exact(
                row["comparison"],
                {
                    "status",
                    "metric",
                    "source_median",
                    "package_median",
                    "source_over_package_speedup",
                    "measurement_order",
                },
                f"{context}.comparison",
            )
            if (
                comparison["status"] != "measured"
                or comparison["metric"] != "median_nanoseconds_per_operation"
            ):
                raise ContractError(f"{context}.comparison metric/status is invalid")
            for name in ("source_median", "package_median", "source_over_package_speedup"):
                _validate_positive_finite_number(comparison[name], f"{context}.comparison.{name}")
            expected_measurement_order = (
                ["starlette-python", "python-package-cpython312"]
                if index % 2 == 0
                else ["python-package-cpython312", "starlette-python"]
            )
            if comparison["measurement_order"] != expected_measurement_order:
                raise ContractError(
                    f"{context}.comparison.measurement_order does not follow the declared counterbalanced order"
                )
        elif status == "not_run":
            correctness_gate = _exact(correctness_gate, {"status"}, f"{context}.correctness_gate")
            if correctness_gate["status"] != "not_run":
                raise ContractError(f"{context}.correctness_gate must be not_run")
        elif "comparison" in row:
            correctness_gate = _exact(
                correctness_gate,
                {
                    "status",
                    "source_observation_sha256",
                    "target_observation_sha256",
                    "normalized_source_observation_sha256",
                    "normalized_target_observation_sha256",
                    "normalization",
                },
                f"{context}.correctness_gate",
            )
            if correctness_gate["status"] != "failed":
                raise ContractError(
                    f"{context}.correctness_gate must fail for observation differences"
                )
            for name in (
                "source_observation_sha256",
                "target_observation_sha256",
                "normalized_source_observation_sha256",
                "normalized_target_observation_sha256",
            ):
                _validate_sha256(correctness_gate[name], f"{context}.correctness_gate.{name}")
            if (
                correctness_gate["normalized_source_observation_sha256"]
                == correctness_gate["normalized_target_observation_sha256"]
            ):
                raise ContractError(
                    f"{context}.correctness_gate normalized observations must differ on failure"
                )
            _string(correctness_gate["normalization"], f"{context}.correctness_gate.normalization")
            comparison = _exact(
                row["comparison"], {"status", "first_difference"}, f"{context}.comparison"
            )
            if comparison["status"] != "fail":
                raise ContractError(f"{context}.comparison must fail for observation differences")
            _validate_upstream_first_difference(
                comparison["first_difference"], f"{context}.comparison.first_difference"
            )
        else:
            correctness_gate = _exact(correctness_gate, {"status"}, f"{context}.correctness_gate")
            if correctness_gate["status"] != "failed":
                raise ContractError(f"{context}.correctness_gate must be failed")

        subjects = row["subjects"]
        if not isinstance(subjects, list) or len(subjects) != 3:
            raise ContractError(f"{context}.subjects must account for three runtime subjects")
        source_subject = _validate_upstream_subject(
            subjects[0], "starlette-python", f"{context}.subjects[0]"
        )
        package_subject = _validate_upstream_subject(
            subjects[1], "python-package-cpython312", f"{context}.subjects[1]"
        )
        for subject in (source_subject, package_subject):
            observed_identity = subject.get("identity")
            if observed_identity is None:
                continue
            subject_id = subject["subject_id"]
            previous_identity = worker_identities.setdefault(subject_id, observed_identity)
            if previous_identity != observed_identity:
                raise ContractError(f"{context}.{subject_id} identity changed across workload rows")
        native = _exact(
            subjects[2],
            {"subject_id", "status", "identity", "reason"},
            f"{context}.subjects[2]",
        )
        if native["subject_id"] != "rust-native-local" or native["status"] != "not_run":
            raise ContractError(
                f"{context}.subjects[2] must preserve the Rust-native not_run boundary"
            )
        if native["identity"] is not None:
            _validate_upstream_target_identity(
                native["identity"], f"{context}.subjects[2].identity"
            )
            if native["identity"]["target_profile"] != "rust-native-local":
                raise ContractError(f"{context}.subjects[2].identity must identify Rust-native")
        _string(native["reason"], f"{context}.subjects[2].reason")

        if status == "measured":
            if [source_subject["status"], package_subject["status"]] != ["measured", "measured"]:
                raise ContractError(f"{context} measured status requires both Python measurements")
            declared_runner_policy = row["measurement_policy"]["runner_policy"]
            if any(
                subject["measurement"]["runner_policy"] != declared_runner_policy
                for subject in (source_subject, package_subject)
            ):
                raise ContractError(
                    f"{context} measurements differ from the declared runner policy"
                )
            source_median = source_subject["measurement"]["statistics"]["median"]
            package_median = package_subject["measurement"]["statistics"]["median"]
            comparison = row["comparison"]
            if (
                comparison["source_median"] != source_median
                or comparison["package_median"] != package_median
                or not math.isclose(
                    comparison["source_over_package_speedup"],
                    source_median / package_median,
                    rel_tol=1e-12,
                )
            ):
                raise ContractError(f"{context}.comparison differs from subject measurements")
            counts[f"{category}_measured"] += 1
        elif "comparison" in row:
            if [source_subject["status"], package_subject["status"]] != ["probed", "probed"]:
                raise ContractError(f"{context} correctness mismatch requires both live probes")
        elif any(subject["status"] == "measured" for subject in (source_subject, package_subject)):
            raise ContractError(f"{context} incomplete rows cannot claim an individual measurement")

    summary = _exact(
        result["summary"],
        {
            "declared",
            "measured",
            "not_run",
            "failed",
            "native_not_run_workloads",
            "router_measured",
            "gzip_measured",
        },
        "upstream benchmark result.summary",
    )
    for name, count in summary.items():
        _validate_nonnegative_integer(count, f"upstream benchmark result.summary.{name}")
    expected_summary = {
        "declared": 74,
        "measured": counts["measured"],
        "not_run": counts["not_run"],
        "failed": counts["failed"],
        "native_not_run_workloads": 74,
        "router_measured": counts["router_measured"],
        "gzip_measured": counts["gzip_measured"],
    }
    if summary != expected_summary:
        raise ContractError("upstream benchmark summary does not reconcile with workload rows")
    if result["status"] == "completed":
        if counts["measured"] != 74 or counts["not_run"] or counts["failed"]:
            raise ContractError("completed upstream benchmark must measure all 74 workloads")
    elif counts["measured"] == 74 and counts["not_run"] == 0 and counts["failed"] == 0:
        raise ContractError("fully measured upstream benchmark must be marked completed")
    return result


def validate_result_artifact(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema") == UPSTREAM_BENCHMARK_RESULT_SCHEMA:
        return _validate_upstream_benchmark_result_artifact(value)
    if isinstance(value, dict) and value.get("schema") == BENCHMARK_RESULT_SCHEMA:
        return _validate_benchmark_result_artifact(value)
    _exact(
        value,
        {"schema", "identity", "status", "summary", "comparisons", "infrastructure_errors"},
        "parity result",
    )
    if value["schema"] != RESULT_SCHEMA:
        raise ContractError("unsupported parity result schema")
    if value["status"] not in {"completed", "infrastructure_failed", "cancelled", "invalid"}:
        raise ContractError("parity result status is invalid")
    identity = _exact(
        value["identity"],
        {
            "run_id",
            "started_at",
            "finished_at",
            "manifest",
            "inputs",
            "assets",
            "oracles",
            "targets",
            "environments",
            "command",
        },
        "result.identity",
    )
    _string(identity["run_id"], "result.identity.run_id")
    _exact(identity["manifest"], {"path", "schema", "sha256"}, "result.identity.manifest")
    if identity["manifest"]["schema"] != MANIFEST_SCHEMA:
        raise ContractError("result manifest schema mismatch")
    for index, item in enumerate(identity["inputs"]):
        _exact(item, {"path", "schema", "sha256"}, f"result.identity.inputs[{index}]")
        if item["schema"] != INPUT_SCHEMA:
            raise ContractError(f"result.identity.inputs[{index}].schema is incompatible")
    for index, item in enumerate(identity["oracles"]):
        _exact(
            item,
            {
                "oracle_id",
                "name",
                "version",
                "revision",
                "runtime",
                "module_path",
                "dependency_lock_sha256",
                "os",
                "architecture",
                "environment_sha256",
                "runtime_lock_sha256",
            },
            f"result.identity.oracles[{index}]",
        )
    for index, item in enumerate(identity["targets"]):
        _exact(
            item,
            {
                "target_profile",
                "target_id",
                "revision",
                "dirty",
                "runtime",
                "backend",
                "features",
                "package_version",
                "target_tree_sha256",
                "dependency_lock_sha256",
                "os",
                "architecture",
                "environment_sha256",
            },
            f"result.identity.targets[{index}]",
        )
    for index, item in enumerate(identity["environments"]):
        if not isinstance(item, dict):
            raise ContractError(f"result.identity.environments[{index}] must be an object")
        if item.get("id") == "rust-native-local":
            _exact(
                item,
                {
                    "id",
                    "runtime",
                    "os",
                    "architecture",
                    "rustc",
                    "cargo",
                    "dependency_lock_path",
                    "dependency_lock_sha256",
                    "environment_sha256",
                },
                f"result.identity.environments[{index}]",
            )
            if item["dependency_lock_path"] != "Cargo.lock":
                raise ContractError("native environment must bind to Cargo.lock")
        elif item.get("id") in {"starlette-oracle-cpython312", "starlette-rs-py-cpython312"}:
            _exact(
                item,
                {
                    "id",
                    "python",
                    "runtime",
                    "os",
                    "architecture",
                    "dependency_lock_path",
                    "dependency_lock_sha256",
                    "installed_lock_sha256",
                    "artifact_sha256",
                    "environment_sha256",
                },
                f"result.identity.environments[{index}]",
            )
            if item["dependency_lock_path"] != "scripts/parity/locks/asgi-runtime-cpython312.txt":
                raise ContractError(
                    "Python environment must bind to the committed runtime dependency lock"
                )
        else:
            raise ContractError(
                f"result.identity.environments[{index}] has an unknown environment ID"
            )
    _exact(
        identity["command"],
        {"command_id", "argv", "cwd", "timeout_seconds"},
        "result.identity.command",
    )
    _exact(
        value["summary"],
        {"selected", "executed", "passed", "failed", "not_run", "infrastructure_errors"},
        "result.summary",
    )
    comparisons = value["comparisons"]
    if not isinstance(comparisons, list):
        raise ContractError("result.comparisons must be an array")
    for index, comparison in enumerate(comparisons):
        context = f"result.comparisons[{index}]"
        _exact(
            comparison,
            {"case_id", "target_profile", "requirements", "source", "target", "outcome", "diffs"},
            context,
        )
        if comparison["outcome"] not in {"pass", "fail", "not_run"}:
            raise ContractError(f"{context}.outcome is invalid")
        validate_workflow_result(comparison["source"], comparison["case_id"], f"{context}.source")
        validate_workflow_result(comparison["target"], comparison["case_id"], f"{context}.target")
        for diff_index, diff in enumerate(comparison["diffs"]):
            _exact(
                diff,
                {"step_id", "path", "kind", "source", "target", "message"},
                f"{context}.diffs[{diff_index}]",
            )
        both_completed = (
            comparison["source"]["status"] == comparison["target"]["status"] == "completed"
        )
        if comparison["outcome"] == "pass" and (not both_completed or comparison["diffs"]):
            raise ContractError(f"{context}: pass requires completed, equal observations")
        if comparison["outcome"] == "fail" and (not both_completed or not comparison["diffs"]):
            raise ContractError(
                f"{context}: fail requires two completed results and at least one exact difference"
            )
        if comparison["outcome"] == "not_run" and both_completed:
            raise ContractError(f"{context}: completed results cannot be labeled not_run")
    for index, error in enumerate(value["infrastructure_errors"]):
        _exact(error, {"scope", "id", "kind", "message"}, f"result.infrastructure_errors[{index}]")
    expected_summary = {
        "selected": len(comparisons),
        "executed": sum(
            1
            for item in comparisons
            if item["source"]["status"] == "completed" and item["target"]["status"] == "completed"
        ),
        "passed": sum(1 for item in comparisons if item["outcome"] == "pass"),
        "failed": sum(1 for item in comparisons if item["outcome"] == "fail"),
        "not_run": sum(1 for item in comparisons if item["outcome"] == "not_run"),
        "infrastructure_errors": len(value["infrastructure_errors"]),
    }
    if value["summary"] != expected_summary:
        raise ContractError("result summary does not equal its comparison/evidence counts")
    if value["status"] == "completed" and value["infrastructure_errors"]:
        raise ContractError("completed result cannot contain infrastructure errors")
    if value["status"] == "infrastructure_failed" and not value["infrastructure_errors"]:
        raise ContractError("infrastructure_failed result requires an infrastructure error")
    if any(
        item["outcome"] == "pass"
        and (item["source"]["status"] != "completed" or item["target"]["status"] != "completed")
        for item in comparisons
    ):
        raise ContractError("a pass requires completed source and target evidence")
    return value
