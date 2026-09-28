"""Live target adapter for the installed ``starlette-rs-py`` package.

The adapter accepts one JSON request per fresh process and uses only the
installed public ``starlette.*`` consumer surface for workflows. Diagnostics
go to stderr; stdout contains exactly one JSON response.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import functools
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "migration-parity/adapter-request@1"
RESPONSE_SCHEMA = "migration-parity/adapter-response@1"
SUBJECT_ID = "python-package"
PACKAGE_NAME = "starlette-rs-py"
WEBSOCKET_SURFACE = "starlette.websockets.WebSocket"
WEBSOCKET_OPERATION = "protocol-sequence"
WEBSOCKET_STATE_OPERATION = "state-sequence"
WEBSOCKET_ROUTE_SURFACE = "starlette.routing.WebSocketRoute"
WEBSOCKET_ROUTE_OPERATION = "route-dispatch"
REDIRECT_RESPONSE_SURFACE = "starlette.responses.RedirectResponse"
REDIRECT_RESPONSE_OPERATION = "asgi-call"
RESPONSE_SURFACE = "starlette.responses.Response"
JSON_RESPONSE_SURFACE = "starlette.responses.JSONResponse"
STREAMING_RESPONSE_SURFACE = "starlette.responses.StreamingResponse"
RESPONSE_OPERATION = "asgi-call"
STREAMING_RESPONSE_TRACE_OPERATION = "asgi-call-with-execution-trace"


class _InputAsyncIterator:
    """Expose decoded case-input values through the async-iterator protocol."""

    def __init__(
        self, values: list[Any], execution_trace: list[dict[str, Any]] | None = None
    ) -> None:
        self._values = iter(values)
        self._execution_trace = execution_trace

    def __aiter__(self) -> _InputAsyncIterator:
        return self

    async def __anext__(self) -> Any:
        try:
            value = next(self._values)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        if self._execution_trace is not None:
            self._execution_trace.append({"event": "iterator-yield", "value": _json_safe(value)})
        return value


def _input_sync_iterator(values: list[Any], execution_trace: list[dict[str, Any]]) -> Iterator[Any]:
    for value in values:
        execution_trace.append({"event": "iterator-yield", "value": _json_safe(value)})
        yield value


async def _input_async_generator(
    values: list[Any], execution_trace: list[dict[str, Any]] | None
) -> AsyncIterator[Any]:
    for value in values:
        if execution_trace is not None:
            execution_trace.append({"event": "iterator-yield", "value": _json_safe(value)})
        yield value


async def _record_background_values(
    values: list[str], execution_trace: list[dict[str, Any]]
) -> None:
    execution_trace.append({"event": "background-start"})
    for value in values:
        execution_trace.append({"event": "background-value", "value": value})
    execution_trace.append({"event": "background-complete"})


@dataclass(frozen=True)
class _CapturedDispatchError:
    error: dict[str, Any]
    partial_value: dict[str, Any]


def _workflow_observation(step_id: str, value: Any) -> dict[str, Any]:
    if isinstance(value, _CapturedDispatchError):
        return {
            "step_id": step_id,
            "status": "error",
            "error": value.error,
            "partial_value": value.partial_value,
        }
    return {"step_id": step_id, "status": "ok", "value": value}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _dispatch_error(exc: Exception) -> dict[str, Any]:
    cause = exc.__cause__
    return {
        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "kind": "exception",
        "message": str(exc),
        "stage": "dispatch",
        "code": None,
        "cause": (
            {
                "class": f"{type(cause).__module__}.{type(cause).__qualname__}",
                "message": str(cause),
                "attributes": _json_safe(vars(cause)),
            }
            if cause is not None
            else None
        ),
        "suppress_context": bool(exc.__suppress_context__),
    }


class _ExceptionHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_heading = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self.parts.append(data)


def _server_error_observation(
    app: Any,
    start: dict[str, Any] | None,
    body: bytes,
    captured_exception: Exception | None,
) -> dict[str, Any]:
    """Compare stable error semantics while excluding runtime-specific frame paths."""
    debug_traceback: dict[str, Any] | None = None
    if captured_exception is not None and getattr(app, "debug", False) and start is not None:
        content_type = next(
            (
                base64.b64decode(value, validate=True).split(b";", 1)[0]
                for name, value in start["headers"]
                if base64.b64decode(name, validate=True).lower() == b"content-type"
            ),
            b"",
        )
        if content_type == b"text/html":
            document = body.decode("utf-8", errors="replace")
            heading = _ExceptionHeadingParser()
            heading.feed(document)
            debug_traceback = {
                "format": "html",
                "exception_heading": "".join(heading.parts),
                "traceback_title_present": 'class="traceback-title">Traceback' in document,
            }
        else:
            lines = body.decode("utf-8", errors="replace").rstrip("\n").splitlines()
            debug_traceback = {
                "format": "text",
                "exception_line": lines[-1] if lines else "",
                "traceback_header_present": bool(
                    lines and lines[0] == "Traceback (most recent call last):"
                ),
            }
    return {
        "handler_calls": list(getattr(app, "_parity_server_error_handler_calls", [])),
        "debug_traceback": debug_traceback,
    }


def _exact_object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _strict_json(raw: bytes) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value is forbidden: {value}")

    return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def _load_installed_package() -> tuple[Any, Any, importlib.metadata.Distribution]:
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("the Python-package target must run in CPython 3.12")
    distribution = importlib.metadata.distribution(PACKAGE_NAME)
    version = distribution.version
    if not version:
        raise RuntimeError("installed starlette-rs-py distribution has no version")
    if "starlette" in sys.modules:
        raise RuntimeError("the target adapter must start in a fresh process")

    import starlette

    from starlette_rs_py import _core

    package_file = Path(starlette.__file__).resolve()
    extension_file = Path(_core.__file__).resolve()
    expected_package_file = Path(distribution.locate_file("starlette/__init__.py")).resolve()
    if package_file != expected_package_file:
        raise RuntimeError(f"starlette imported from {package_file}, outside the installed target")
    if not extension_file.is_file():
        raise RuntimeError("installed starlette-rs-py native extension is missing")
    return starlette, _core, distribution


def _identity(distribution: importlib.metadata.Distribution) -> dict[str, Any]:
    dependency_lock_sha256 = os.environ.get("STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256")
    if (
        dependency_lock_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", dependency_lock_sha256) is None
    ):
        raise RuntimeError(
            "STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256 must be a lowercase SHA-256 digest"
        )

    digest = hashlib.sha256()
    package_roots = ("starlette/", "starlette_rs_py/")
    files = distribution.files or ()
    included = 0
    for item in sorted(files, key=lambda entry: str(entry)):
        relative = str(item).replace("\\", "/")
        if not relative.startswith(package_roots):
            continue
        path = Path(distribution.locate_file(item))
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        included += 1
    if included == 0:
        raise RuntimeError("installed target package has no verifiable package files")
    target_tree_sha256 = digest.hexdigest()
    return {
        "subject_id": SUBJECT_ID,
        "revision": f"dirty-tree:{target_tree_sha256}",
        "dirty": True,
        "runtime": f"{platform.python_implementation()} {platform.python_version()}",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "backend": "CPython 3.12",
        "features": [],
        "package_version": distribution.version,
        "dependency_lock_sha256": dependency_lock_sha256,
        "target_tree_sha256": target_tree_sha256,
    }


def _decode_base64(value: str, context: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid base64 at {context}") from exc


def _make_scope(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["type"] == "lifespan":
        return {"type": "lifespan", "asgi": dict(spec["asgi"])}
    return {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "method": spec["method"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": _decode_base64(spec["raw_path_base64"], "scope.raw_path_base64"),
        "query_string": _decode_base64(spec["query_string_base64"], "scope.query_string_base64"),
        "root_path": spec["root_path"],
        "headers": [
            (_decode_base64(name, "scope header name"), _decode_base64(value, "scope header value"))
            for name, value in spec["headers_base64_pairs"]
        ],
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
    }


def _make_message(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["type"] in {"lifespan.startup", "lifespan.shutdown"}:
        return {"type": spec["type"]}
    return {
        "type": spec["type"],
        "body": _decode_base64(spec["body_base64"], "receive.body_base64"),
        "more_body": spec["more_body"],
    }


def _materialize_asgi_action(action: Any, index: int) -> tuple[str, Any]:
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        raise ValueError(f"ASGI action[{index}] must declare an action kind")
    if action["action"] == "send":
        _exact_object(action, {"action", "message"}, f"ASGI action[{index}]")
        message = action["message"]
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise ValueError(f"ASGI action[{index}].message must declare a message type")
        if message["type"] == "http.response.start":
            _exact_object(
                message,
                {"type", "status", "headers_base64_pairs"},
                f"ASGI action[{index}].message",
            )
            if (
                type(message["status"]) is not int
                or not 100 <= message["status"] <= 599
                or not isinstance(message["headers_base64_pairs"], list)
            ):
                raise ValueError("ASGI response start has invalid fields")
            headers = []
            for pair in message["headers_base64_pairs"]:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(not isinstance(part, str) for part in pair)
                ):
                    raise ValueError("ASGI response headers must be base64 string pairs")
                headers.append(
                    (
                        _decode_base64(pair[0], "ASGI response header name"),
                        _decode_base64(pair[1], "ASGI response header value"),
                    )
                )
            return "send", {
                "type": "http.response.start",
                "status": message["status"],
                "headers": headers,
            }
        if message["type"] == "http.response.body":
            _exact_object(
                message,
                {"type", "body_base64", "more_body"},
                f"ASGI action[{index}].message",
            )
            if not isinstance(message["more_body"], bool):
                raise ValueError("ASGI response body more_body must be boolean")
            return "send", {
                "type": "http.response.body",
                "body": _decode_base64(message["body_base64"], "ASGI response body"),
                "more_body": message["more_body"],
            }
        raise ValueError(f"unsupported ASGI output message type: {message['type']!r}")
    if action["action"] == "raise-http-exception":
        _exact_object(
            action,
            {"action", "status_code", "detail", "headers"},
            f"ASGI action[{index}]",
        )
        if (
            type(action["status_code"]) is not int
            or not 100 <= action["status_code"] <= 599
            or (action["detail"] is not None and not isinstance(action["detail"], str))
        ):
            raise ValueError("HTTP exception action has invalid status or detail")
        headers = action["headers"]
        if headers is not None and (
            not isinstance(headers, list)
            or any(
                not isinstance(pair, list)
                or len(pair) != 2
                or any(not isinstance(part, str) for part in pair)
                for pair in headers
            )
        ):
            raise ValueError("HTTP exception headers must be null or string pairs")
        from starlette.exceptions import HTTPException

        arguments: dict[str, Any] = {"status_code": action["status_code"]}
        if action["detail"] is not None:
            arguments["detail"] = action["detail"]
        arguments["headers"] = None if headers is None else dict(headers)
        return "raise", HTTPException(**arguments)
    if action["action"] == "raise-runtime-error":
        _exact_object(action, {"action", "message"}, f"ASGI action[{index}]")
        if not isinstance(action["message"], str):
            raise ValueError("RuntimeError action message must be a string")
        return "raise", RuntimeError(action["message"])
    raise ValueError(f"unsupported ASGI callable action: {action['action']!r}")


def _canonical_message(message: dict[str, Any]) -> dict[str, Any]:
    kind = message["type"]
    if kind.startswith("lifespan."):
        return {"type": kind}
    if kind == "http.response.start":
        return {
            "type": kind,
            "status": message["status"],
            "headers": [
                [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
                for name, value in message["headers"]
            ],
        }
    if kind == "http.response.body":
        event = {
            "type": kind,
            "body": {
                "encoding": "base64",
                "data": base64.b64encode(message["body"]).decode("ascii"),
            },
        }
        if "more_body" in message:
            event["more_body"] = message["more_body"]
        return event
    if kind == "http.response.pathsend":
        return {"type": kind, "path": message["path"]}
    raise RuntimeError(f"unexpected ASGI event in the current slice: {kind!r}")


def _sync_request_observer_response(
    request: Any, spec: dict[str, Any], state: dict[str, Any]
) -> Any:
    path_value = request.path_params[spec["path_parameter"]]
    context_value = state["context_var"].get()
    caller_thread_id = state["caller_thread_id"]
    if caller_thread_id is None:
        raise RuntimeError("sync endpoint ran without a caller thread identity")
    current_thread_id = threading.get_ident()
    with state["lock"]:
        state["invocation_count"] += 1
        state["observation"] = {
            "path_param": {"value": _json_safe(path_value), "type": type(path_value).__name__},
            "context_value": context_value,
            "different_worker_thread": current_thread_id != caller_thread_id,
            "invocation_count": state["invocation_count"],
        }
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(content=spec["response_content"])


def _materialize_exception_handlers(
    registry: Any,
    json_response_type: Any,
    plain_text_response_type: Any,
    http_exception_type: Any,
    handler_calls: list[str],
) -> tuple[dict[Any, Any], dict[str, Any]]:
    if not isinstance(registry, list):
        raise ValueError("exception-handler registry must be an ordered entry array")
    exception_types = {"HTTPException": http_exception_type}
    handlers: dict[Any, Any] = {}
    for index, raw_entry in enumerate(registry):
        context = f"exception_handlers[{index}]"
        entry = _exact_object(raw_entry, {"key", "handler"}, context)
        key_spec = entry["key"]
        if not isinstance(key_spec, dict) or not isinstance(key_spec.get("kind"), str):
            raise ValueError(f"{context}.key must be a tagged handler key")
        if key_spec["kind"] == "status-code":
            _exact_object(key_spec, {"kind", "status_code"}, f"{context}.key")
            key = key_spec["status_code"]
            if type(key) is not int:
                raise ValueError(f"{context}.key.status_code must be an integer")
        elif key_spec["kind"] == "exception-class":
            if key_spec.get("name") == "HTTPException":
                _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = http_exception_type
            elif key_spec.get("name") == "Exception":
                _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = Exception
            elif key_spec.get("name") == "BodyReuseException":
                _exact_object(key_spec, {"kind", "name", "base_class"}, f"{context}.key")
                if key_spec["base_class"] != "HTTPException":
                    raise ValueError("BodyReuseException must derive from HTTPException")
                key = type("BodyReuseException", (http_exception_type,), {})
                exception_types["BodyReuseException"] = key
            else:
                raise ValueError(f"{context}.key names an unsupported exception class")
        else:
            raise ValueError(f"{context}.key uses an unsupported kind")

        recipe = entry["handler"]
        if not isinstance(recipe, dict) or not isinstance(recipe.get("kind"), str):
            raise ValueError(f"{context}.handler must use a tagged handler recipe")

        def make_handler(spec: dict[str, Any]) -> Any:
            async def handler(request: Any, exc: Exception) -> Any:
                if spec["kind"] == "json-exception-detail-response":
                    _exact_object(
                        spec,
                        {"kind", "status_from_exception"},
                        "JSON exception-detail response handler",
                    )
                    if spec["status_from_exception"] is not True:
                        raise ValueError("exception-detail handler must use exception status")
                    return json_response_type({"detail": exc.detail}, status_code=exc.status_code)
                if spec["kind"] == "json-literal-response":
                    _exact_object(
                        spec,
                        {"kind", "status_code", "content"},
                        "JSON literal response handler",
                    )
                    if type(spec["status_code"]) is not int or not isinstance(
                        spec["content"], dict
                    ):
                        raise ValueError("JSON literal handler has invalid status or content")
                    return json_response_type(
                        content=spec["content"], status_code=spec["status_code"]
                    )
                if spec["kind"] == "request-body-json-response":
                    _exact_object(
                        spec,
                        {"kind", "body_field", "status_from_exception"},
                        "request-body JSON response handler",
                    )
                    if (
                        not isinstance(spec["body_field"], str)
                        or spec["status_from_exception"] is not True
                    ):
                        raise ValueError("request-body handler has invalid response selectors")
                    body = await request.body()
                    return json_response_type(
                        {spec["body_field"]: body.decode("utf-8")},
                        status_code=exc.status_code,
                    )
                if spec["kind"] == "server-error-response":
                    _exact_object(
                        spec,
                        {"kind", "label", "status_code", "content"},
                        "server-error response handler",
                    )
                    if (
                        not isinstance(spec["label"], str)
                        or type(spec["status_code"]) is not int
                        or not isinstance(spec["content"], str)
                    ):
                        raise ValueError("server-error handler response has invalid fields")
                    handler_calls.append(spec["label"])
                    return plain_text_response_type(
                        spec["content"], status_code=spec["status_code"]
                    )
                raise ValueError(f"unsupported exception-handler recipe: {spec['kind']!r}")

            return handler

        handlers[key] = make_handler(recipe)
    return handlers, exception_types


def _materialize_application(
    app_spec: dict[str, Any],
) -> tuple[Any, list[str], list[dict[str, Any]], Any, list[dict[str, Any]]]:
    from starlette.applications import Starlette
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route

    required_arguments = {
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
        "max_body_size",
    }
    if set(app_spec) != required_arguments:
        raise ValueError("Starlette.__init__ arguments do not match the declared workflow")
    lifecycle_trace: list[str] = []
    lifespan_spec = app_spec["lifespan"]
    if lifespan_spec is None:
        lifespan = None
    elif lifespan_spec == {
        "kind": "async-context-manager",
        "record_entry": True,
        "record_exit": True,
    }:

        @contextlib.asynccontextmanager
        async def lifespan(_app: Any) -> Any:
            lifecycle_trace.append("entry")
            try:
                yield
            finally:
                lifecycle_trace.append("exit")
    else:
        raise ValueError(
            "lifespan input must be null or use the declared async-context-manager marker"
        )

    routes = []
    request_observations: list[dict[str, Any]] = []
    sync_endpoint_states: list[dict[str, Any]] = []
    handler_calls: list[str] = []
    route_endpoint: Any = None
    exception_handlers, exception_types = _materialize_exception_handlers(
        app_spec["exception_handlers"],
        JSONResponse,
        PlainTextResponse,
        HTTPException,
        handler_calls,
    )
    for route_spec in app_spec["routes"]:
        if (
            set(route_spec) != {"kind", "path", "methods", "endpoint"}
            or route_spec["kind"] != "http-route"
        ):
            raise ValueError("route input must be a declared http-route record")
        response_spec = route_spec["endpoint"]
        if not isinstance(response_spec, dict) or not isinstance(response_spec.get("kind"), str):
            raise ValueError("endpoint input must be a declared endpoint record")
        if response_spec["kind"] == "plain-text-response":
            if set(response_spec) != {"kind", "content", "status_code", "media_type", "cookies"}:
                raise ValueError("endpoint input must match the plain-text-response schema")

            def make_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(_request: Any) -> Any:
                    response = PlainTextResponse(
                        content=spec["content"],
                        status_code=spec["status_code"],
                        media_type=spec["media_type"],
                    )
                    for cookie in spec["cookies"]:
                        if set(cookie) != {"key", "value"}:
                            raise ValueError("each cookie input must contain exactly key and value")
                        response.set_cookie(key=cookie["key"], value=cookie["value"])
                    return response

                return endpoint

            route_endpoint = make_endpoint(response_spec)
        elif response_spec["kind"] == "raise-runtime-error":
            _exact_object(
                response_spec,
                {"kind", "message"},
                "RuntimeError endpoint",
            )
            if not isinstance(response_spec["message"], str):
                raise ValueError("RuntimeError endpoint message must be a string")

            def make_runtime_error_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(_request: Any) -> Any:
                    raise RuntimeError(spec["message"])

                return endpoint

            route_endpoint = make_runtime_error_endpoint(response_spec)
        elif response_spec["kind"] == "request-observer":
            required_fields = {
                "kind",
                "path_parameter",
                "query_parameter",
                "header_primary_case",
                "header_alternate_case",
                "cookie_name",
                "response_content",
                "status_code",
                "media_type",
            }
            if set(response_spec) != required_fields:
                raise ValueError("request observer input does not match its declared schema")

            def make_request_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    path_value = request.path_params[spec["path_parameter"]]
                    query_params = request.query_params
                    request_observations.append(
                        {
                            "path_param": {
                                "value": _json_safe(path_value),
                                "type": type(path_value).__name__,
                            },
                            "query_params": {
                                "getlist": query_params.getlist(spec["query_parameter"]),
                                "scalar": query_params[spec["query_parameter"]],
                            },
                            "headers": {
                                "primary_case": request.headers[spec["header_primary_case"]],
                                "alternate_case": request.headers[spec["header_alternate_case"]],
                            },
                            "cookie": request.cookies[spec["cookie_name"]],
                            "json": await request.json(),
                        }
                    )
                    return PlainTextResponse(
                        content=spec["response_content"],
                        status_code=spec["status_code"],
                        media_type=spec["media_type"],
                    )

                return endpoint

            route_endpoint = make_request_endpoint(response_spec)
        elif response_spec["kind"] == "http-exception":
            required_fields = {"kind", "status_code", "detail", "headers"}
            if set(response_spec) != required_fields:
                raise ValueError("HTTP exception input does not match its declared schema")
            if type(response_spec["status_code"]) is not int:
                raise ValueError("HTTP exception status_code must be an integer")
            if response_spec["detail"] is not None and not isinstance(response_spec["detail"], str):
                raise ValueError("HTTP exception detail must be a string or null")
            headers = response_spec["headers"]
            if not isinstance(headers, list) or any(
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(value, str) for value in pair)
                for pair in headers
            ):
                raise ValueError("HTTP exception headers must be string pairs")

            from starlette.exceptions import HTTPException

            def make_http_exception_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(_request: Any) -> Any:
                    arguments = {
                        "status_code": spec["status_code"],
                        "headers": dict(spec["headers"]),
                    }
                    if spec["detail"] is not None:
                        arguments["detail"] = spec["detail"]
                    raise HTTPException(**arguments)

                return endpoint

            route_endpoint = make_http_exception_endpoint(response_spec)
        elif response_spec["kind"] == "http-exception-after-body":
            _exact_object(
                response_spec,
                {"kind", "exception_class", "status_code", "detail"},
                "body-reading HTTP exception endpoint",
            )
            exception_type = exception_types.get(response_spec["exception_class"])
            if exception_type is None:
                raise ValueError("body-reading endpoint references an undeclared exception class")

            def make_body_exception_endpoint(spec: dict[str, Any], exc_type: Any) -> Any:
                async def endpoint(request: Any) -> Any:
                    await request.body()
                    arguments: dict[str, Any] = {"status_code": spec["status_code"]}
                    if spec["detail"] is not None:
                        arguments["detail"] = spec["detail"]
                    raise exc_type(**arguments)

                return endpoint

            route_endpoint = make_body_exception_endpoint(response_spec, exception_type)
        elif response_spec["kind"] == "sync-request-observer":
            required_fields = {
                "kind",
                "callable_kind",
                "path_parameter",
                "context_var_name",
                "context_value",
                "response_content",
            }
            if set(response_spec) != required_fields:
                raise ValueError("sync request observer input does not match its declared schema")
            sync_state: dict[str, Any] = {
                "context_var": contextvars.ContextVar(response_spec["context_var_name"]),
                "context_value": response_spec["context_value"],
                "caller_thread_id": None,
                "invocation_count": 0,
                "observation": None,
                "lock": threading.Lock(),
            }
            sync_endpoint_states.append(sync_state)

            callable_kind = response_spec["callable_kind"]
            if callable_kind == "function":

                def make_function_endpoint(spec: dict[str, Any], state: dict[str, Any]) -> Any:
                    def endpoint(request: Any) -> Any:
                        return _sync_request_observer_response(request, spec, state)

                    return endpoint

                route_endpoint = make_function_endpoint(response_spec, sync_state)
            elif callable_kind == "bound_method":

                class BoundMethodEndpoint:
                    def __init__(self, spec: dict[str, Any], state: dict[str, Any]) -> None:
                        self.spec = spec
                        self.state = state

                    def endpoint(self, request: Any) -> Any:
                        return _sync_request_observer_response(request, self.spec, self.state)

                route_endpoint = BoundMethodEndpoint(response_spec, sync_state).endpoint
            elif callable_kind == "partial":
                route_endpoint = functools.partial(
                    _sync_request_observer_response,
                    spec=response_spec,
                    state=sync_state,
                )
            else:
                raise ValueError(f"unsupported sync endpoint callable kind: {callable_kind!r}")
        elif response_spec["kind"] == "asgi-callable-instance-observer":
            required_fields = {"kind", "response_content"}
            if set(response_spec) != required_fields:
                raise ValueError(
                    "ASGI callable-instance observer input does not match its declared schema"
                )

            class ASGICallableInstanceObserver:
                def __init__(self, content: str) -> None:
                    self.content = content

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    response = PlainTextResponse(content=self.content)
                    await response(scope, receive, send)

            route_endpoint = ASGICallableInstanceObserver(response_spec["response_content"])
        elif response_spec["kind"] == "asgi-callable-action-sequence":
            _exact_object(
                response_spec,
                {"kind", "actions"},
                "ASGI callable action-sequence endpoint",
            )
            if not isinstance(response_spec["actions"], list) or not response_spec["actions"]:
                raise ValueError("ASGI callable action sequence must be a non-empty array")

            class ASGICallableActionSequence:
                def __init__(self, actions: list[dict[str, Any]]) -> None:
                    self.actions = actions

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    for index, action in enumerate(self.actions):
                        action_kind, value = _materialize_asgi_action(action, index)
                        if action_kind == "send":
                            await send(value)
                        else:
                            raise value

            route_endpoint = ASGICallableActionSequence(response_spec["actions"])
        else:
            raise ValueError(f"unsupported endpoint kind: {response_spec['kind']!r}")
        routes.append(Route(route_spec["path"], route_endpoint, methods=route_spec["methods"]))

    app = Starlette(
        debug=app_spec["debug"],
        routes=routes,
        middleware=app_spec["middleware"],
        exception_handlers=exception_handlers,
        lifespan=lifespan,
        max_body_size=app_spec["max_body_size"],
    )
    app._parity_server_error_handler_calls = handler_calls
    return app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states


def _observed_sync_endpoint(
    sync_endpoint_states: list[dict[str, Any]],
) -> dict[str, Any] | None:
    observations: list[dict[str, Any]] = []
    for state in sync_endpoint_states:
        with state["lock"]:
            observation = state["observation"]
            if observation is not None:
                observations.append(dict(observation))
    if len(observations) > 1:
        raise RuntimeError("more than one sync observer endpoint ran for one request")
    return observations[0] if observations else None


async def _invoke(
    app: Any,
    step_arguments: dict[str, Any],
    lifecycle_trace: list[str],
    request_observations: list[dict[str, Any]],
    route_endpoint: Any,
    request_dispatch: bool,
    workflow_events: list[dict[str, Any]] | None = None,
    sync_endpoint_states: list[dict[str, Any]] | None = None,
    capture_dispatch_error: bool = False,
) -> dict[str, Any] | _CapturedDispatchError:
    scope = _make_scope(step_arguments["scope"])
    incoming = [_make_message(item) for item in step_arguments["receive"]]
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received < len(incoming):
            message = incoming[received]
            received += 1
            return message
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if workflow_events is not None:
            workflow_events.append(_canonical_message(message))

    if step_arguments["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")
    context_tokens: list[tuple[dict[str, Any], contextvars.Token[Any]]] = []
    captured_exception: Exception | None = None
    try:
        for state in sync_endpoint_states or []:
            state["caller_thread_id"] = threading.get_ident()
            token = state["context_var"].set(state["context_value"])
            context_tokens.append((state, token))
        try:
            await app(scope, receive, send)
        except Exception as exc:
            if not capture_dispatch_error:
                raise
            captured_exception = exc
    finally:
        for state, token in reversed(context_tokens):
            state["context_var"].reset(token)

    events = [_canonical_message(message) for message in sent]
    start = next((event for event in events if event["type"] == "http.response.start"), None)
    if start is None and scope["type"] != "lifespan":
        raise RuntimeError("target completed without an http.response.start event")
    body_chunks = [
        event["body"]["data"] for event in events if event["type"] == "http.response.body"
    ]
    body = b"".join(base64.b64decode(chunk) for chunk in body_chunks)
    result = {
        "response_status": start["status"] if start is not None else None,
        "ordered_repeated_headers": start["headers"] if start is not None else [],
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": _server_error_observation(app, start, body, captured_exception),
    }
    if request_dispatch:
        if len(request_observations) > 1:
            raise RuntimeError("request observer endpoint ran more than once")
        result = {
            "request_observations": request_observations[0] if request_observations else None,
            "sync_endpoint_observations": _observed_sync_endpoint(sync_endpoint_states or []),
            "route_scope": {
                "app_is_application": scope.get("app") is app,
                "router_is_application_router": scope.get("router") is app.router,
                "endpoint_is_route_endpoint": scope.get("endpoint") is route_endpoint,
                "path_params_present": "path_params" in scope,
                "path_params": _json_safe(scope.get("path_params")),
            },
            "response_status": result["response_status"],
            "ordered_repeated_headers": result["ordered_repeated_headers"],
            "asgi_event_order": result["asgi_event_order"],
            "asgi_events": result["asgi_events"],
        }
        if captured_exception is not None:
            return _CapturedDispatchError(
                error=_dispatch_error(captured_exception),
                partial_value=result,
            )
        return result
    return result


def _literal_arguments(step: dict[str, Any], expected: set[str], context: str) -> dict[str, Any]:
    arguments = _exact_object(step["arguments"], expected, f"{context} arguments")
    values: dict[str, Any] = {}
    for name, descriptor in arguments.items():
        descriptor = _exact_object(descriptor, {"kind", "value"}, f"{context}.{name}")
        if descriptor["kind"] != "literal":
            raise ValueError(f"{context}.{name} must be an input literal")
        values[name] = descriptor["value"]
    return values


def _materialize_gzip_middleware(arguments: dict[str, Any]) -> Any:
    from starlette.middleware.gzip import GZipMiddleware

    app_spec = _exact_object(arguments["app"], {"kind", "messages"}, "GZipMiddleware app")
    if app_spec["kind"] != "asgi-response-sequence" or not isinstance(app_spec["messages"], list):
        raise ValueError("GZipMiddleware app must be an input-defined response sequence")
    response_messages = app_spec["messages"]

    async def response_app(_scope: Any, _receive: Any, send: Any) -> None:
        for index, spec in enumerate(response_messages):
            if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            message_type = spec["type"]
            if message_type == "http.response.start":
                _exact_object(
                    spec,
                    {"type", "status", "headers_base64_pairs"},
                    f"inner response message[{index}]",
                )
                message = {
                    "type": message_type,
                    "status": spec["status"],
                    "headers": [
                        (
                            _decode_base64(name, "inner response header name"),
                            _decode_base64(value, "inner response header value"),
                        )
                        for name, value in spec["headers_base64_pairs"]
                    ],
                }
            elif message_type == "http.response.body":
                _exact_object(
                    spec,
                    {"type", "body_base64", "more_body"},
                    f"inner response message[{index}]",
                )
                message = {
                    "type": message_type,
                    "body": _decode_base64(spec["body_base64"], "inner response body"),
                    "more_body": spec["more_body"],
                }
            elif message_type == "http.response.pathsend":
                _exact_object(
                    spec,
                    {"type", "path"},
                    f"inner response message[{index}]",
                )
                message = {"type": message_type, "path": spec["path"]}
            else:
                raise ValueError(f"unsupported inner response event: {message_type!r}")
            await send(message)

    return GZipMiddleware(
        response_app,
        minimum_size=arguments["minimum_size"],
        compresslevel=arguments["compresslevel"],
        thread_minimum_size=arguments["thread_minimum_size"],
        exclude_content_types=tuple(arguments["exclude_content_types"]),
    )


def _run_gzip_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    if (
        len(steps) != 2
        or [step.get("step_id") for step in steps] != ["middleware", "dispatch"]
        or [step.get("operation") for step in steps] != ["__init__", "__call__"]
        or any(step.get("surface") != case["surface"] for step in steps)
        or steps[0].get("receiver") is not None
        or steps[1].get("receiver") != {"kind": "binding", "step_id": "middleware"}
    ):
        raise ValueError("GZipMiddleware cases must construct then dispatch the public middleware")
    if case["execution_schedule"] != ["dispatch"] or case["observations"] != ["dispatch"]:
        raise ValueError("GZipMiddleware cases must observe one dispatch step")

    constructor_arguments = _literal_arguments(
        steps[0],
        {"app", "minimum_size", "compresslevel", "thread_minimum_size", "exclude_content_types"},
        "GZipMiddleware constructor",
    )
    dispatch_arguments = _literal_arguments(
        steps[1], {"scope", "receive", "send"}, "GZipMiddleware dispatch"
    )
    middleware = _materialize_gzip_middleware(constructor_arguments)
    value = asyncio.run(_invoke(middleware, dispatch_arguments, [], [], None, False))
    selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": selected}],
    }


def _make_websocket_scope(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "websocket",
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": _decode_base64(spec["raw_path_base64"], "WebSocket scope.raw_path_base64"),
        "query_string": _decode_base64(
            spec["query_string_base64"], "WebSocket scope.query_string_base64"
        ),
        "root_path": spec["root_path"],
        "headers": [
            (
                _decode_base64(name, "WebSocket scope header name"),
                _decode_base64(value, "WebSocket scope header value"),
            )
            for name, value in spec["headers_base64_pairs"]
        ],
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
        "subprotocols": list(spec["subprotocols"]),
    }


def _materialize_websocket_message(spec: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {}
    for name, value in spec.items():
        if name == "bytes_base64":
            message["bytes"] = _decode_base64(value, "WebSocket message.bytes_base64")
        elif name == "body_base64":
            message["body"] = _decode_base64(value, "WebSocket message.body_base64")
        elif name == "headers_base64_pairs":
            message["headers"] = [
                (
                    _decode_base64(pair[0], "WebSocket message header name"),
                    _decode_base64(pair[1], "WebSocket message header value"),
                )
                for pair in value
            ]
        else:
            message[name] = value
    return message


def _canonical_websocket_message(message: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in message.items():
        if name == "bytes":
            result["bytes_base64"] = base64.b64encode(value).decode("ascii")
        elif name == "body":
            result["body_base64"] = base64.b64encode(value).decode("ascii")
        elif name == "headers":
            result["headers_base64_pairs"] = [
                [base64.b64encode(key).decode("ascii"), base64.b64encode(item).decode("ascii")]
                for key, item in value
            ]
        else:
            result[name] = _json_safe(value)
    return result


def _websocket_action_error(exc: Exception) -> dict[str, Any]:
    context = exc.__context__
    cause = exc.__cause__
    return {
        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "kind": "exception",
        "message": str(exc),
        "stage": "action",
        "code": getattr(exc, "code", None),
        "cause": (
            {
                "class": f"{type(cause).__module__}.{type(cause).__qualname__}",
                "message": str(cause),
            }
            if cause is not None
            else None
        ),
        "suppress_context": bool(exc.__suppress_context__),
        "reason": getattr(exc, "reason", None),
        "context": (
            {
                "class": f"{type(context).__module__}.{type(context).__qualname__}",
                "message": str(context),
            }
            if context is not None
            else None
        ),
    }


def _websocket_state_name(state: Any) -> str:
    name = getattr(state, "name", None)
    if isinstance(name, str):
        return name
    raise ValueError("WebSocket state does not expose its public enum name")


def _run_websocket_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "incoming",
            "actions",
            "observations",
        },
        "WebSocket protocol-sequence case",
    )
    if case["surface"] != WEBSOCKET_SURFACE or case["operation"] != WEBSOCKET_OPERATION:
        raise ValueError("WebSocket workflow is outside the declared protocol-sequence operation")
    from starlette.websockets import WebSocket

    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    incoming_index = 0
    callback_tape: list[dict[str, Any]] = []
    pending_send_error: dict[str, Any] | None = None

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            raise ValueError("WebSocket receive action exhausted its input-only message sequence")
        message = incoming[incoming_index]
        incoming_index += 1
        callback_tape.append(
            {"direction": "receive", "message": _canonical_websocket_message(message)}
        )
        return message

    async def send(message: dict[str, Any]) -> None:
        callback_tape.append(
            {"direction": "send", "message": _canonical_websocket_message(message)}
        )
        if pending_send_error is not None:
            raise OSError(pending_send_error["message"])

    websocket = WebSocket(_make_websocket_scope(case["scope"]), receive, send)

    async def run_actions() -> None:
        nonlocal pending_send_error
        for action in case["actions"]:
            try:
                if action["action"] == "receive":
                    await websocket.receive()
                elif action["action"] == "send":
                    pending_send_error = action.get("send_error")
                    try:
                        await websocket.send(_materialize_websocket_message(action["message"]))
                    finally:
                        pending_send_error = None
                else:
                    raise ValueError(
                        "unsupported raw WebSocket action; only receive and send are declared"
                    )
            except Exception:
                # Protocol errors are visible through the absence of callbacks;
                # state-sequence separately observes their messages and states.
                continue

    asyncio.run(run_actions())
    if incoming_index != len(incoming):
        raise ValueError("WebSocket protocol sequence left incoming messages unconsumed")
    available = {"asgi_callback_tape": callback_tape}
    if case["observations"] != [WEBSOCKET_OPERATION]:
        raise ValueError("WebSocket observations must select the protocol-sequence workflow result")
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": WEBSOCKET_OPERATION, "status": "ok", "value": available}],
    }


def _run_websocket_state_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "incoming",
            "actions",
            "observations",
        },
        "WebSocket state-sequence case",
    )
    if case["surface"] != WEBSOCKET_SURFACE or case["operation"] != WEBSOCKET_STATE_OPERATION:
        raise ValueError("WebSocket workflow is outside the declared state-sequence operation")
    from starlette.websockets import WebSocket, WebSocketDisconnect

    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    incoming_index = 0
    pending_send_error: dict[str, Any] | None = None

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            raise ValueError("WebSocket receive action exhausted its input-only message sequence")
        message = incoming[incoming_index]
        incoming_index += 1
        return message

    async def send(_message: dict[str, Any]) -> None:
        if pending_send_error is not None:
            raise OSError(pending_send_error["message"])

    websocket = WebSocket(_make_websocket_scope(case["scope"]), receive, send)

    async def run_actions() -> list[dict[str, Any]]:
        nonlocal pending_send_error
        results: list[dict[str, Any]] = []
        for action in case["actions"]:
            action_id = action["action_id"]
            try:
                if action["action"] == "receive":
                    await websocket.receive()
                elif action["action"] == "send":
                    pending_send_error = action.get("send_error")
                    try:
                        await websocket.send(_materialize_websocket_message(action["message"]))
                    finally:
                        pending_send_error = None
                else:
                    raise ValueError(
                        "unsupported state-sequence action; only raw receive and send are declared"
                    )
            except WebSocketDisconnect as exc:
                if action.get("send_error") is not None:
                    results.append({"action_id": action_id, "outcome": "send-error-handled"})
                else:
                    results.append(
                        {
                            "action_id": action_id,
                            "outcome": "error",
                            "error_message": str(exc),
                        }
                    )
            except Exception as exc:
                results.append(
                    {
                        "action_id": action_id,
                        "outcome": "error",
                        "error_message": str(exc),
                    }
                )
            else:
                results.append({"action_id": action_id, "outcome": "ok"})
        return results

    action_results = asyncio.run(run_actions())
    if incoming_index != len(incoming):
        raise ValueError("WebSocket state sequence left incoming messages unconsumed")
    available = {
        "action_results": action_results,
        "client_state": _websocket_state_name(websocket.client_state),
        "application_state": _websocket_state_name(websocket.application_state),
    }
    if case["observations"] != [WEBSOCKET_STATE_OPERATION]:
        raise ValueError("WebSocket observations must select the state-sequence workflow result")
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": WEBSOCKET_STATE_OPERATION, "status": "ok", "value": available}
        ],
    }


def _canonical_websocket_route_event(message: dict[str, Any]) -> dict[str, Any]:
    if message["type"].startswith("websocket."):
        return _canonical_websocket_message(message)
    return _canonical_message(message)


def _run_websocket_route_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "dispatch",
            "route",
            "scope",
            "incoming",
            "endpoint_actions",
            "observations",
        },
        "WebSocketRoute route-dispatch case",
    )
    if case["surface"] != WEBSOCKET_ROUTE_SURFACE or case["operation"] != WEBSOCKET_ROUTE_OPERATION:
        raise ValueError("workflow is outside the declared WebSocketRoute route-dispatch operation")
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute

    endpoint_actions = case["endpoint_actions"]

    async def endpoint(websocket: Any) -> None:
        for action in endpoint_actions:
            if action["action"] == "accept":
                await websocket.accept(subprotocol=action["subprotocol"])
            elif action["action"] == "send_text":
                await websocket.send_text(action["text"])
            elif action["action"] == "close":
                await websocket.close(code=action["code"], reason=action["reason"])
            else:
                raise ValueError(
                    f"unsupported WebSocketRoute endpoint action: {action['action']!r}"
                )

    route = WebSocketRoute(case["route"]["path"], endpoint=endpoint)
    app = Starlette(routes=[route])
    scope_spec = case["scope"]
    scope = (
        _make_websocket_scope(scope_spec)
        if scope_spec["type"] == "websocket"
        else _make_scope(scope_spec)
    )
    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    incoming_index = 0
    sent_messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            raise ValueError("WebSocketRoute workflow exhausted its input-only receive sequence")
        message = incoming[incoming_index]
        incoming_index += 1
        return message

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def dispatch() -> None:
        if case["dispatch"] == "application":
            await app(scope, receive, send)
        elif case["dispatch"] == "standalone-route":
            await route(scope, receive, send)
        else:
            raise ValueError(f"unsupported WebSocketRoute dispatch kind: {case['dispatch']!r}")

    asyncio.run(dispatch())
    if incoming_index != len(incoming):
        raise ValueError("WebSocketRoute dispatch left incoming messages unconsumed")
    events = [_canonical_websocket_route_event(message) for message in sent_messages]
    response_start = next(
        (message for message in sent_messages if message["type"] == "http.response.start"),
        None,
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent_messages
        if message["type"] == "http.response.body"
    )
    available = {
        "route_scope": {
            "app_is_application": scope.get("app") is app,
            "router_is_application_router": scope.get("router") is app.router,
            "endpoint_is_route_endpoint": scope.get("endpoint") is endpoint,
            "path_params_present": "path_params" in scope,
            "path_params": _json_safe(scope.get("path_params")),
        },
        "asgi_events": events,
        "response_status": response_start["status"] if response_start is not None else None,
        "response_bytes": (
            {"encoding": "base64", "data": base64.b64encode(response_body).decode("ascii")}
            if response_start is not None
            else None
        ),
    }
    if case["observations"] != [WEBSOCKET_ROUTE_OPERATION]:
        raise ValueError(
            "WebSocketRoute observations must select the route-dispatch workflow result"
        )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": WEBSOCKET_ROUTE_OPERATION, "status": "ok", "value": available}
        ],
    }


async def _invoke_lifespan_around_dispatch(
    app: Any,
    lifecycle_arguments: dict[str, Any],
    dispatch_arguments: dict[str, Any],
    lifecycle_trace: list[str],
    request_observations: list[dict[str, Any]],
    route_endpoint: Any,
    sync_endpoint_states: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep the source ASGI lifespan call active for the following HTTP call."""
    if lifecycle_arguments["scope"].get("type") != "lifespan":
        raise ValueError("the lifecycle workflow step must use a lifespan scope")
    lifecycle_messages = [_make_message(item) for item in lifecycle_arguments["receive"]]
    if [message["type"] for message in lifecycle_messages] != [
        "lifespan.startup",
        "lifespan.shutdown",
    ]:
        raise ValueError("the lifecycle workflow must provide startup then shutdown")
    if lifecycle_arguments["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    incoming_lifecycle: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    await incoming_lifecycle.put(lifecycle_messages[0])
    workflow_events: list[dict[str, Any]] = []
    startup_complete = asyncio.Event()

    async def receive_lifecycle() -> dict[str, Any]:
        return await incoming_lifecycle.get()

    async def send_lifecycle(message: dict[str, Any]) -> None:
        workflow_events.append(_canonical_message(message))
        if message.get("type") == "lifespan.startup.complete":
            startup_complete.set()

    lifespan_task = asyncio.create_task(
        app(_make_scope(lifecycle_arguments["scope"]), receive_lifecycle, send_lifecycle)
    )
    startup_wait = asyncio.create_task(startup_complete.wait())
    try:
        done, _ = await asyncio.wait(
            {lifespan_task, startup_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if lifespan_task in done:
            await lifespan_task
            raise RuntimeError("lifespan app returned before startup completed")
        startup_wait.cancel()
        await asyncio.gather(startup_wait, return_exceptions=True)

        dispatch_value = await _invoke(
            app,
            dispatch_arguments,
            lifecycle_trace,
            request_observations,
            route_endpoint,
            False,
            workflow_events,
            sync_endpoint_states,
        )
        await incoming_lifecycle.put(lifecycle_messages[1])
        await lifespan_task
    except BaseException:
        startup_wait.cancel()
        if not lifespan_task.done():
            await incoming_lifecycle.put(lifecycle_messages[1])
        await asyncio.gather(lifespan_task, startup_wait, return_exceptions=True)
        raise

    lifecycle_value = {
        "response_status": None,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": [event["type"] for event in workflow_events],
        "asgi_events": workflow_events,
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": {"handler_calls": [], "debug_traceback": None},
    }
    return lifecycle_value, dispatch_value


def _run_route_dispatch_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.convertors import CONVERTOR_TYPES

    missing = object()
    prior_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], missing)
        for spec in case.get("custom_convertors", [])
    }
    try:
        return _run_route_dispatch_case_impl(case)
    finally:
        for name, prior in prior_convertors.items():
            if prior is missing:
                CONVERTOR_TYPES.pop(name, None)
            else:
                CONVERTOR_TYPES[name] = prior


def _run_route_dispatch_case_impl(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.convertors import Convertor, register_url_convertor
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route, Router

    for spec in case.get("custom_convertors", []):

        class InputConvertor(Convertor[str]):
            regex = spec["regex"]
            lowercase = spec["lowercase"]

            def convert(self, value: str) -> str:
                return value.lower() if self.lowercase else value

            def to_string(self, value: str) -> str:
                return str(value)

        register_url_convertor(spec["name"], InputConvertor())

    route_index_observations: list[int] = []

    def make_route(route_spec: dict[str, Any], route_index: int) -> Any:
        response_spec = route_spec["endpoint"]
        if response_spec["kind"] not in {"plain-text-response", "converted-path-response"}:
            raise ValueError(f"unsupported route endpoint input: {response_spec['kind']!r}")

        async def endpoint(request: Any) -> Any:
            if response_spec["kind"] == "converted-path-response":
                content = str(request.path_params[response_spec["path_parameter"]])
            else:
                content = response_spec["content"]
            route_index_observations.append(route_index)
            return PlainTextResponse(
                content=content,
                status_code=response_spec["status_code"],
                media_type=response_spec["media_type"],
            )

        return Route(route_spec["path"], endpoint=endpoint, methods=route_spec["methods"])

    if case["surface"] == "starlette.routing.Router":
        redirect_slashes = case["redirect_slashes"]
        if type(redirect_slashes) is not bool:
            raise ValueError("Router redirect_slashes must be a boolean")
        app = Router(
            routes=[make_route(route, index) for index, route in enumerate(case["routes"])],
            redirect_slashes=redirect_slashes,
        )
    elif case["surface"] == "starlette.routing.Mount":
        mount = case["mount"]
        app = Mount(
            mount["path"],
            routes=[make_route(route, index) for index, route in enumerate(mount["routes"])],
        )
    else:
        raise ValueError("route-dispatch case has an unsupported surface")

    scope = _make_scope(case["scope"])
    incoming = [_make_message(message) for message in case["incoming"]]
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received < len(incoming):
            message = incoming[received]
            received += 1
            return message
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")
    asyncio.run(app(scope, receive, send))
    events = [_canonical_message(message) for message in sent]
    response_start = next(
        (event for event in events if event["type"] == "http.response.start"), None
    )
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    observation = {
        "response_status": response_start["status"] if response_start is not None else None,
        "ordered_repeated_headers": response_start["headers"] if response_start is not None else [],
        "response_bytes": {
            "encoding": "base64",
            "data": base64.b64encode(response_body).decode("ascii"),
        },
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
    }
    if case["surface"] == "starlette.routing.Mount":
        observation["mount_scope"] = (
            {
                "root_path": scope.get("root_path"),
                "app_root_path": scope.get("app_root_path"),
                "path_params": {
                    name: {"value": _json_safe(value), "type": type(value).__name__}
                    for name, value in scope.get("path_params", {}).items()
                },
            }
            if "app_root_path" in scope
            else None
        )
    else:
        if len(route_index_observations) > 1:
            raise RuntimeError("Router dispatched more than one route endpoint")
        observation["route_index"] = (
            route_index_observations[0] if route_index_observations else None
        )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "route-dispatch", "status": "ok", "value": observation}],
    }


def _run_redirect_response_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "url",
            "status_code",
            "header_pairs",
            "scope",
            "incoming",
            "send",
            "observations",
        },
        "RedirectResponse ASGI-call case",
    )
    if (
        case["surface"] != REDIRECT_RESPONSE_SURFACE
        or case["operation"] != REDIRECT_RESPONSE_OPERATION
    ):
        raise ValueError("workflow is outside the declared RedirectResponse ASGI-call operation")
    if case["observations"] != [REDIRECT_RESPONSE_OPERATION]:
        raise ValueError("RedirectResponse observations must select asgi-call")
    if not isinstance(case["url"], str):
        raise ValueError("RedirectResponse url must be a string")
    if type(case["status_code"]) is not int:
        raise ValueError("RedirectResponse status_code must be an integer")
    header_pairs = case["header_pairs"]
    if not isinstance(header_pairs, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(part, str) for part in pair)
        for pair in header_pairs
    ):
        raise ValueError("RedirectResponse header_pairs must be string pairs")
    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    from starlette.responses import RedirectResponse

    response = RedirectResponse(
        case["url"],
        status_code=case["status_code"],
        headers=dict(header_pairs),
    )
    scope = _make_scope(case["scope"])
    incoming = [_make_message(item) for item in case["incoming"]]
    incoming_index = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            return {"type": "http.disconnect"}
        message = incoming[incoming_index]
        incoming_index += 1
        return message

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(response(scope, receive, send))
    events = [_canonical_message(message) for message in sent]
    response_start = next(
        (message for message in sent if message["type"] == "http.response.start"), None
    )
    response_start_event = next(
        (event for event in events if event["type"] == "http.response.start"), None
    )
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    observation = {
        "response_status": response_start["status"] if response_start is not None else None,
        "ordered_repeated_headers": (
            response_start_event["headers"] if response_start_event is not None else []
        ),
        "response_bytes": (
            {
                "encoding": "base64",
                "data": base64.b64encode(response_body).decode("ascii"),
            }
            if response_start is not None
            else None
        ),
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": REDIRECT_RESPONSE_OPERATION, "status": "ok", "value": observation}
        ],
    }


def _run_basic_response_case(case: dict[str, Any]) -> dict[str, Any]:
    surface = case.get("surface")
    required_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "content",
        "status_code",
        "header_pairs",
        "media_type",
        "scope",
        "incoming",
        "send",
        "observations",
    }
    if surface == STREAMING_RESPONSE_SURFACE:
        required_fields.add("streaming")
        if "background" in case:
            required_fields.add("background")
    _exact_object(
        case,
        required_fields,
        "Response ASGI-call case",
    )
    if surface not in {
        RESPONSE_SURFACE,
        JSON_RESPONSE_SURFACE,
        STREAMING_RESPONSE_SURFACE,
    }:
        raise ValueError("workflow is outside the declared Response ASGI-call surfaces")
    if not isinstance(case["case_id"], str):
        raise ValueError("Response case_id must be a string")
    for field in ("covers", "target_profiles", "assets"):
        if not isinstance(case[field], list):
            raise ValueError(f"Response {field} must be an array")
    expected_operation = (
        STREAMING_RESPONSE_TRACE_OPERATION
        if surface == STREAMING_RESPONSE_SURFACE and case.get("streaming") == "async-generator"
        else RESPONSE_OPERATION
    )
    if case["operation"] != expected_operation:
        raise ValueError("Response case must use the declared operation for its input mode")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("Response observations must select asgi-call")

    content_spec = _exact_object(case["content"], {"kind", "value"}, "Response content")
    content_kind = content_spec["kind"]
    streaming: str | None = None
    if surface == STREAMING_RESPONSE_SURFACE:
        if content_kind != "chunks" or not isinstance(content_spec["value"], list):
            raise ValueError("StreamingResponse content must select an array of chunks")
        content = []
        for index, chunk_spec in enumerate(content_spec["value"]):
            chunk_spec = _exact_object(
                chunk_spec, {"kind", "value"}, f"StreamingResponse content chunk[{index}]"
            )
            if chunk_spec["kind"] == "text":
                chunk = chunk_spec["value"]
                if not isinstance(chunk, str):
                    raise ValueError("StreamingResponse text chunks must be strings")
            elif chunk_spec["kind"] == "base64-bytes":
                encoded_chunk = chunk_spec["value"]
                if not isinstance(encoded_chunk, str):
                    raise ValueError("StreamingResponse base64-bytes chunks must be strings")
                chunk = _decode_base64(encoded_chunk, f"content.value[{index}].value")
            else:
                raise ValueError("StreamingResponse chunks must be text or base64-bytes")
            content.append(chunk)
        streaming = case["streaming"]
        if streaming not in {"sync", "async-iterator", "async-generator"}:
            raise ValueError("StreamingResponse streaming must select a supported iterator")
    elif surface == RESPONSE_SURFACE:
        if content_kind == "text":
            content = content_spec["value"]
            if not isinstance(content, str):
                raise ValueError("Response text content value must be a string")
        elif content_kind == "base64-bytes":
            encoded_content = content_spec["value"]
            if not isinstance(encoded_content, str):
                raise ValueError("Response base64-bytes content value must be a string")
            content = _decode_base64(encoded_content, "content.value")
        elif content_kind == "none" and content_spec["value"] is None:
            content = None
        else:
            raise ValueError("Response content must be text, base64-bytes, or null")
    else:
        if content_kind != "json" or content_spec["value"] is not None:
            raise ValueError("JSONResponse content must select json with a null value")
        content = None

    if type(case["status_code"]) is not int:
        raise ValueError("Response status_code must be an integer")
    header_pairs = case["header_pairs"]
    if not isinstance(header_pairs, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(part, str) for part in pair)
        for pair in header_pairs
    ):
        raise ValueError("Response header_pairs must be string pairs")
    media_type = case["media_type"]
    if media_type is not None and not isinstance(media_type, str):
        raise ValueError("Response media_type must be a string or null")

    scope_spec = _exact_object(
        case["scope"],
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
        "Response HTTP scope",
    )
    if scope_spec["type"] != "http":
        raise ValueError("Response ASGI-call requires an HTTP scope")
    asgi_spec = _exact_object(scope_spec["asgi"], {"version", "spec_version"}, "ASGI version")
    if any(not isinstance(asgi_spec[key], str) for key in asgi_spec):
        raise ValueError("ASGI versions must be strings")
    for field in ("http_version", "method", "scheme", "path", "root_path"):
        if not isinstance(scope_spec[field], str):
            raise ValueError(f"Response HTTP scope.{field} must be a string")
    headers = scope_spec["headers_base64_pairs"]
    if not isinstance(headers, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(value, str) for value in pair)
        for pair in headers
    ):
        raise ValueError("Response HTTP scope headers must be base64 string pairs")
    for field in ("client", "server"):
        address = scope_spec[field]
        if (
            not isinstance(address, list)
            or len(address) != 2
            or not isinstance(address[0], str)
            or type(address[1]) is not int
        ):
            raise ValueError(f"Response HTTP scope.{field} must be a [host, port] pair")
    if not isinstance(case["incoming"], list) or case["incoming"]:
        raise ValueError("Response ASGI-call requires an empty incoming stream")
    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    background_values: list[str] | None = None
    if "background" in case:
        background_spec = _exact_object(
            case["background"], {"kind", "values"}, "Response background"
        )
        if background_spec["kind"] != "async-values-recorder":
            raise ValueError("Response background must select the async values recorder")
        values = background_spec["values"]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Response background values must be an array of strings")
        background_values = values

    execution_trace = (
        [] if streaming == "async-generator" or background_values is not None else None
    )

    from starlette.responses import JSONResponse, Response, StreamingResponse

    response_type = {
        RESPONSE_SURFACE: Response,
        JSON_RESPONSE_SURFACE: JSONResponse,
        STREAMING_RESPONSE_SURFACE: StreamingResponse,
    }[surface]
    if streaming == "sync":
        content = (
            _input_sync_iterator(content, execution_trace)
            if execution_trace is not None
            else iter(content)
        )
    elif streaming == "async-iterator":
        content = _InputAsyncIterator(content, execution_trace)
    elif streaming == "async-generator":
        content = _input_async_generator(content, execution_trace)
    response_arguments: dict[str, Any] = {
        "content": content,
        "status_code": case["status_code"],
        "headers": dict(header_pairs),
    }
    if media_type is not None:
        response_arguments["media_type"] = media_type
    if background_values is not None:
        from starlette.background import BackgroundTask

        if execution_trace is None:
            raise RuntimeError("background execution requires an execution trace")
        response_arguments["background"] = BackgroundTask(
            _record_background_values, background_values, execution_trace
        )
    response = response_type(**response_arguments)
    scope = _make_scope(scope_spec)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        if execution_trace is not None:
            execution_trace.append({"event": "asgi-send", "message": _canonical_message(message)})

    asyncio.run(response(scope, receive, send))
    events = [_canonical_message(message) for message in sent]
    response_start = next(
        (message for message in sent if message["type"] == "http.response.start"), None
    )
    response_start_event = next(
        (event for event in events if event["type"] == "http.response.start"), None
    )
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    observation = {
        "response_status": response_start["status"] if response_start is not None else None,
        "ordered_repeated_headers": (
            response_start_event["headers"] if response_start_event is not None else []
        ),
        "response_bytes": (
            {
                "encoding": "base64",
                "data": base64.b64encode(response_body).decode("ascii"),
            }
            if response_start is not None
            else None
        ),
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
    }
    if execution_trace is not None:
        observation["execution_trace"] = execution_trace
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": case["observations"][0], "status": "ok", "value": observation}
        ],
    }


def _reverse_url_error(exc: Exception) -> dict[str, str]:
    return {"class": type(exc).__name__, "message": str(exc)}


def _reverse_url_path_value(url_path: Any) -> dict[str, str]:
    return {"path": str(url_path), "protocol": url_path.protocol, "host": url_path.host}


def _request_url_value(request: Any, lookup: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"url": str(request.url_for(lookup["name"], **lookup["path_params"]))}
    except Exception as exc:
        return {"error": _reverse_url_error(exc)}


def _build_reverse_route_node(
    node: dict[str, Any], lookup: dict[str, Any], observation: dict[str, Any]
) -> Any:
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Mount, Route, Router, WebSocketRoute

    kind = node["kind"]
    if kind == "http-route":

        async def endpoint(request: Any) -> Any:
            if node["observer"] == "request-url-for":
                observation["result"] = _request_url_value(request, lookup)
            return PlainTextResponse("")

        return Route(
            node["path"],
            endpoint=endpoint,
            methods=node["methods"],
            name=node["name"],
        )
    if kind == "websocket-route":

        async def websocket_endpoint(websocket: Any) -> None:
            await websocket.close()

        return WebSocketRoute(node["path"], endpoint=websocket_endpoint, name=node["name"])
    if kind == "router":
        return Router(
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ]
        )
    if kind == "mount":
        return Mount(
            node["path"],
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ],
            name=node["name"],
        )
    if kind == "starlette-app":
        return Starlette(
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ]
        )
    raise ValueError(f"unsupported reverse URL route node kind: {kind!r}")


def _reverse_request_scope(spec: dict[str, Any]) -> dict[str, Any]:
    path = spec["path"]
    scope = {
        "type": spec["type"],
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": spec["method"],
        "scheme": spec["scheme"],
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": spec["root_path"],
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": tuple(spec["server"]),
    }
    if spec["app_root_path"] is not None:
        scope["app_root_path"] = spec["app_root_path"]
    return scope


def _run_reverse_url_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.convertors import CONVERTOR_TYPES, Convertor, register_url_convertor
    from starlette.requests import Request

    missing = object()
    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], missing)
        for spec in case["custom_convertors"]
    }
    observation: dict[str, Any] = {}
    lookup = case["lookup"]
    try:
        for spec in case["custom_convertors"]:

            class InputConvertor(Convertor[str]):
                def __init__(self, raw: dict[str, Any]) -> None:
                    self.regex = raw["regex"]
                    self.lowercase = raw["lowercase"]
                    self.lowercase_to_string = raw["lowercase_to_string"]

                def convert(self, value: str) -> str:
                    return value.lower() if self.lowercase else value

                def to_string(self, value: Any) -> str:
                    text = str(value)
                    return text.lower() if self.lowercase_to_string else text

            register_url_convertor(spec["name"], InputConvertor(spec))

        graph_spec = case["route_graph"]
        if case["surface"] == "starlette.requests.Request":
            request_scope = case["request_scope"]
            graph = (
                None
                if graph_spec is None
                else _build_reverse_route_node(graph_spec, lookup, observation)
            )

            async def run_request() -> dict[str, Any]:
                scope = _reverse_request_scope(request_scope)
                provider = request_scope["provider"]
                if provider == "none":
                    return _request_url_value(Request(scope), lookup)
                if provider == "router":
                    scope["router"] = graph
                    return _request_url_value(Request(scope), lookup)
                if provider == "app":
                    scope["app"] = graph
                    return _request_url_value(Request(scope), lookup)

                async def receive() -> dict[str, Any]:
                    return {"type": "http.disconnect"}

                async def send(message: dict[str, Any]) -> None:
                    del message

                await graph(scope, receive, send)
                if "result" not in observation:
                    raise RuntimeError("request URL observer route did not run")
                return observation["result"]

            observed = asyncio.run(run_request())
        else:
            graph = _build_reverse_route_node(graph_spec, lookup, observation)
            result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            observed = _reverse_url_path_value(result)
    except Exception as exc:
        observed = {"error": _reverse_url_error(exc)}
    finally:
        for name, previous in previous_convertors.items():
            if previous is missing:
                CONVERTOR_TYPES.pop(name, None)
            else:
                CONVERTOR_TYPES[name] = previous

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "reverse-url",
                "status": "ok",
                "value": {"reverse-url": observed},
            }
        ],
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    if isinstance(case, dict) and case.get("operation") in {"url_path_for", "url_for"}:
        return _run_reverse_url_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_SURFACE
        and case.get("operation") == WEBSOCKET_OPERATION
    ):
        return _run_websocket_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_SURFACE
        and case.get("operation") == WEBSOCKET_STATE_OPERATION
    ):
        return _run_websocket_state_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_ROUTE_SURFACE
        and case.get("operation") == WEBSOCKET_ROUTE_OPERATION
    ):
        return _run_websocket_route_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == REDIRECT_RESPONSE_SURFACE
        and case.get("operation") == REDIRECT_RESPONSE_OPERATION
    ):
        return _run_redirect_response_case(case)
    if isinstance(case, dict) and case.get("surface") in {
        RESPONSE_SURFACE,
        JSON_RESPONSE_SURFACE,
        STREAMING_RESPONSE_SURFACE,
    }:
        return _run_basic_response_case(case)
    if case.get("surface") in {"starlette.routing.Router", "starlette.routing.Mount"}:
        if case.get("operation") != "route-dispatch":
            raise ValueError("Router and Mount cases must use route-dispatch")
        return _run_route_dispatch_case(case)
    if case.get("surface") == "starlette.middleware.gzip.GZipMiddleware":
        _exact_object(
            case,
            {
                "case_id",
                "surface",
                "operation",
                "covers",
                "target_profiles",
                "assets",
                "steps",
                "observations",
                "execution_schedule",
            },
            "parity case",
        )
        if case["operation"] != "__call__":
            raise ValueError("GZipMiddleware cases must call its public ASGI interface")
        return _run_gzip_case(case)
    steps = case["steps"]
    schedule = case["execution_schedule"]
    if len(steps) < 2 or steps[0]["step_id"] != "application":
        raise ValueError("target adapter requires the application-construction step first")
    is_request_dispatch = case["operation"] == "request-dispatch"
    if is_request_dispatch:
        if [step["step_id"] for step in steps] != ["application", "dispatch"] or schedule != [
            "dispatch"
        ]:
            raise ValueError("request-dispatch target case must contain application then dispatch")
    elif (
        [step["step_id"] for step in steps] == ["application", "lifecycle", "dispatch"]
        and schedule != ["lifespan.startup", "dispatch", "lifespan.shutdown"]
    ) or (
        [step["step_id"] for step in steps] == ["application", "dispatch"]
        and schedule != ["dispatch"]
    ):
        raise ValueError("execution schedule does not match the ASGI workflow steps")
    elif [step["step_id"] for step in steps] not in (
        ["application", "lifecycle", "dispatch"],
        ["application", "dispatch"],
    ):
        raise ValueError("target adapter received a workflow outside the declared ASGI slice")
    app_arguments = {name: item["value"] for name, item in steps[0]["arguments"].items()}
    capture_dispatch_error = is_request_dispatch or app_arguments["routes"][0]["endpoint"][
        "kind"
    ] in {
        "asgi-callable-action-sequence",
        "raise-runtime-error",
    }
    (
        app,
        lifecycle_trace,
        request_observations,
        route_endpoint,
        sync_endpoint_states,
    ) = _materialize_application(app_arguments)

    async def run_steps() -> list[dict[str, Any]]:
        if schedule == ["lifespan.startup", "dispatch", "lifespan.shutdown"]:
            lifecycle_arguments = {
                name: item["value"] for name, item in steps[1]["arguments"].items()
            }
            dispatch_arguments = {
                name: item["value"] for name, item in steps[2]["arguments"].items()
            }
            lifecycle_value, dispatch_value = await _invoke_lifespan_around_dispatch(
                app,
                lifecycle_arguments,
                dispatch_arguments,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                sync_endpoint_states,
            )
            return [
                {"step_id": "lifecycle", "status": "ok", "value": lifecycle_value},
                {"step_id": "dispatch", "status": "ok", "value": dispatch_value},
            ]

        results = []
        for step in steps[1:]:
            arguments = {name: item["value"] for name, item in step["arguments"].items()}
            value = await _invoke(
                app,
                arguments,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                is_request_dispatch and step["operation"] == "request-dispatch",
                sync_endpoint_states=sync_endpoint_states,
                capture_dispatch_error=capture_dispatch_error,
            )
            results.append(_workflow_observation(step["step_id"], value))
        return results

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(run_steps()),
    }


def main() -> int:
    try:
        request = _strict_json(sys.stdin.buffer.read())
        _exact_object(request, {"schema", "mode", "subject_id", "case"}, "adapter request")
        if request["schema"] != REQUEST_SCHEMA or request["subject_id"] != SUBJECT_ID:
            raise ValueError("adapter request schema or subject id mismatch")
        _, _, distribution = _load_installed_package()
        if request["mode"] == "identity":
            if request["case"] is not None:
                raise ValueError("identity requests must set case to null")
            output = {
                "schema": RESPONSE_SCHEMA,
                "mode": "identity",
                "subject_id": SUBJECT_ID,
                "identity": _identity(distribution),
            }
        elif request["mode"] == "workflow":
            if not isinstance(request["case"], dict):
                raise ValueError("workflow request case must be an object")
            output = {
                "schema": RESPONSE_SCHEMA,
                "mode": "workflow",
                "subject_id": SUBJECT_ID,
                "result": _run_case(request["case"]),
            }
        else:
            raise ValueError("adapter request mode must be identity or workflow")
        sys.stdout.write(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n")
        return 0
    except Exception as error:  # adapter failures are infrastructure errors in the parent runner
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
