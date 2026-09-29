"""Live adapter for the pinned Starlette 1.6.0 source checkout."""

from __future__ import annotations

import asyncio
import base64
import builtins
import contextlib
import contextvars
import errno
import functools
import hashlib
import inspect
import json
import math
import os
import platform
import stat
import subprocess
import sys
import tempfile
import threading
import warnings
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

PROTOCOL_REQUEST = "migration-parity/adapter-request@1"
PROTOCOL_RESPONSE = "migration-parity/adapter-response@1"
ORACLE_ID = "starlette-python"
ORACLE_VERSION = "1.6.0"
ORACLE_COMMIT = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"
WEBSOCKET_SURFACE = "starlette.websockets.WebSocket"
WEBSOCKET_OPERATION = "protocol-sequence"
WEBSOCKET_STATE_OPERATION = "state-sequence"
WEBSOCKET_CONVENIENCE_OPERATION = "convenience-sequence"
WEBSOCKET_CLOSE_SURFACE = "starlette.websockets.WebSocketClose"
WEBSOCKET_CLOSE_OPERATION = "call-sequence"
WEBSOCKET_ROUTE_SURFACE = "starlette.routing.WebSocketRoute"
WEBSOCKET_ROUTE_OPERATION = "route-dispatch"
ROUTER_SURFACE = "starlette.routing.Router"
ROUTER_OPERATION = "route-dispatch"
HOST_SURFACE = "starlette.routing.Host"
MOUNT_SURFACE = "starlette.routing.Mount"
MOUNT_OPERATION = "route-dispatch"
REDIRECT_RESPONSE_SURFACE = "starlette.responses.RedirectResponse"
REDIRECT_RESPONSE_OPERATION = "asgi-call"
RESPONSE_SURFACE = "starlette.responses.Response"
JSON_RESPONSE_SURFACE = "starlette.responses.JSONResponse"
STREAMING_RESPONSE_SURFACE = "starlette.responses.StreamingResponse"
FILE_RESPONSE_SURFACE = "starlette.responses.FileResponse"
STATIC_FILES_SURFACE = "starlette.staticfiles.StaticFiles"
STATIC_FILES_LOOKUP_PATH_OPERATION = "lookup-path"
STATIC_FILES_ASYNC_BOUNDARY_OPERATION = "asgi-call-async-boundary"
RESPONSE_OPERATION = "asgi-call"
STREAMING_RESPONSE_TRACE_OPERATION = "asgi-call-with-execution-trace"
BODY_LIMIT_SURFACE = "starlette.middleware.body_limit.RequestBodyLimitMiddleware"
CORS_SURFACE = "starlette.middleware.cors.CORSMiddleware"
HTTPS_REDIRECT_SURFACE = "starlette.middleware.httpsredirect.HTTPSRedirectMiddleware"
TRUSTED_HOST_SURFACE = "starlette.middleware.trustedhost.TrustedHostMiddleware"
SESSION_MIDDLEWARE_SURFACE = "starlette.middleware.sessions.SessionMiddleware"
SESSION_WORKFLOW_OPERATION = "session-workflow"
BASE_HTTP_SURFACE = "starlette.middleware.base.BaseHTTPMiddleware"
BASE_HTTP_WORKFLOW_OPERATION = "base-http-workflow"
EXCEPTION_VALUES_SURFACE = "starlette.exceptions"
MIDDLEWARE_CONFIG_SURFACE = "starlette.middleware.Middleware"
VALUE_FORMATTING_OPERATION = "value-formatting"
REQUEST_DEFAULT_RECEIVE_OPERATION = ("starlette.requests.Request", "default-receive")
REQUEST_SEND_PUSH_PROMISE_OPERATION = ("starlette.requests.Request", "send-push-promise")
REQUEST_IS_DISCONNECTED_OPERATION = ("starlette.requests.Request", "is-disconnected")
STATUS_SURFACE = "starlette.status"
STATUS_OPERATION = "module-symbol-sequence"
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
URL_QUERY_OPERATION = ("starlette.datastructures.URL", "query-parameter-operations")
_MISSING = object()


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


class _InputAsyncIterable:
    """Expose case-input values through an async-generator __aiter__ method."""

    def __init__(
        self, values: list[Any], execution_trace: list[dict[str, Any]] | None = None
    ) -> None:
        self._values = values
        self._execution_trace = execution_trace

    async def __aiter__(self) -> Any:
        for value in self._values:
            if self._execution_trace is not None:
                self._execution_trace.append(
                    {"event": "iterator-yield", "value": _json_safe(value)}
                )
            yield value


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


async def _input_repeating_async_generator(
    values: list[Any],
    execution_trace: list[dict[str, Any]],
    stream_lifecycle: dict[str, str],
    checkpoint: str,
) -> AsyncIterator[Any]:
    index = 0
    try:
        while True:
            if checkpoint == "yield-to-event-loop":
                await asyncio.sleep(0)
            value = values[index]
            index = (index + 1) % len(values)
            execution_trace.append({"event": "iterator-yield", "value": _json_safe(value)})
            yield value
    except asyncio.CancelledError:
        execution_trace.append(
            {
                "event": "iterator-cancelled",
                "marker": stream_lifecycle["cancellation_marker"],
            }
        )
        raise
    finally:
        execution_trace.append(
            {"event": "iterator-finally", "marker": stream_lifecycle["finally_marker"]}
        )


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


async def _request_stream_action(stream: Any, action: dict[str, Any]) -> dict[str, Any]:
    operation = action["operation"]
    try:
        if operation == "anext":
            value = await stream.__anext__()
        elif operation == "asend":
            value = await stream.asend(action["value"])
        elif operation == "athrow":
            exception_type = getattr(builtins, action["exception_type"])
            value = await stream.athrow(exception_type(action["message"]))
        else:
            value = await stream.aclose()
    except Exception as exc:
        return {
            "operation": operation,
            "error": {
                "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
            },
        }
    return {"operation": operation, "value": _json_safe(value)}


def _dispatch_error(exc: BaseException) -> dict[str, Any]:
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


def _strict_object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _load_starlette() -> tuple[Any, Path]:
    root_value = os.environ.get("STARLETTE_ORACLE_ROOT")
    if not root_value:
        raise RuntimeError(
            "STARLETTE_ORACLE_ROOT must point to the pinned Starlette 1.6.0 checkout"
        )
    root = Path(root_value).resolve()
    package = root / "starlette"
    if not (package / "__init__.py").is_file():
        raise RuntimeError(f"Starlette package was not found under {root}")
    if "starlette" in sys.modules:
        raise RuntimeError("the oracle adapter must start in a fresh process")
    sys.path.insert(0, str(root))
    import starlette

    source_file = Path(starlette.__file__).resolve()
    if source_file != (package / "__init__.py").resolve():
        raise RuntimeError(f"oracle imported Starlette from unexpected path: {source_file}")
    if starlette.__version__ != ORACLE_VERSION:
        raise RuntimeError(f"oracle version mismatch: {starlette.__version__!r}")
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if commit != ORACLE_COMMIT:
        raise RuntimeError(f"oracle source revision mismatch: {commit}")
    dirty = subprocess.run(
        ["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", "starlette"],
        check=False,
        timeout=10,
    ).returncode
    if dirty != 0:
        raise RuntimeError("tracked Starlette package files are modified")
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "starlette"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    if untracked:
        raise RuntimeError(
            "untracked files under the oracle Starlette package could affect imports"
        )
    return starlette, root


def _identity(starlette: Any, root: Path) -> dict[str, Any]:
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        raise RuntimeError("oracle uv.lock is missing")
    return {
        "subject_id": ORACLE_ID,
        "version": starlette.__version__,
        "revision": ORACLE_COMMIT,
        "runtime": platform.python_implementation() + " " + platform.python_version(),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "module_path": str(Path(starlette.__file__).resolve()),
        "dependency_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    }


def _decode_b64(value: str, context: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid base64 at {context}") from exc


def _make_scope(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["type"] == "lifespan":
        scope = {"type": "lifespan", "asgi": dict(spec["asgi"])}
        if "state" in spec:
            scope["state"] = dict(spec["state"])
        return scope
    scope = {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": _decode_b64(spec["raw_path_base64"], "scope.raw_path_base64"),
        "query_string": _decode_b64(spec["query_string_base64"], "scope.query_string_base64"),
        "root_path": spec["root_path"],
        "headers": [
            (_decode_b64(pair[0], "scope header name"), _decode_b64(pair[1], "scope header value"))
            for pair in spec["headers_base64_pairs"]
        ],
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
    }
    if spec["type"] == "http":
        scope["method"] = spec["method"]
    elif spec["type"] == "websocket":
        scope["subprotocols"] = list(spec["subprotocols"])
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    if "app_root_path" in spec:
        scope["app_root_path"] = spec["app_root_path"]
    if "path_params" in spec:
        scope["path_params"] = dict(spec["path_params"])
    return scope


def _message(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["type"] in {"lifespan.startup", "lifespan.shutdown"}:
        return {"type": spec["type"]}
    if spec["type"] == "http.disconnect":
        return {"type": spec["type"]}
    if spec["type"] == "websocket.connect":
        return {"type": spec["type"]}
    if spec["type"] == "websocket.disconnect":
        return {"type": spec["type"], "code": spec["code"]}
    if spec["type"] == "websocket.receive":
        if "bytes_base64" in spec:
            return {
                "type": spec["type"],
                "bytes": _decode_b64(spec["bytes_base64"], "receive.bytes_base64"),
            }
        return {"type": spec["type"], "text": spec["text"]}
    return {
        "type": spec["type"],
        "body": _decode_b64(spec["body_base64"], "receive.body_base64"),
        "more_body": spec["more_body"],
    }


def _materialize_asgi_action(action: Any, index: int) -> tuple[str, Any]:
    if not isinstance(action, dict) or not isinstance(action.get("action"), str):
        raise ValueError(f"ASGI action[{index}] must declare an action kind")
    if action["action"] == "send":
        _strict_object(action, {"action", "message"}, f"ASGI action[{index}]")
        message = action["message"]
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise ValueError(f"ASGI action[{index}].message must declare a message type")
        if message["type"] == "http.response.start":
            _strict_object(
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
                        _decode_b64(pair[0], "ASGI response header name"),
                        _decode_b64(pair[1], "ASGI response header value"),
                    )
                )
            return "send", {
                "type": "http.response.start",
                "status": message["status"],
                "headers": headers,
            }
        if message["type"] == "http.response.body":
            _strict_object(
                message,
                {"type", "body_base64", "more_body"},
                f"ASGI action[{index}].message",
            )
            if not isinstance(message["more_body"], bool):
                raise ValueError("ASGI response body more_body must be boolean")
            return "send", {
                "type": "http.response.body",
                "body": _decode_b64(message["body_base64"], "ASGI response body"),
                "more_body": message["more_body"],
            }
        raise ValueError(f"unsupported ASGI output message type: {message['type']!r}")
    if action["action"] == "raise-http-exception":
        _strict_object(
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
        _strict_object(action, {"action", "message"}, f"ASGI action[{index}]")
        if not isinstance(action["message"], str):
            raise ValueError("RuntimeError action message must be a string")
        return "raise", RuntimeError(action["message"])
    raise ValueError(f"unsupported ASGI callable action: {action['action']!r}")


def _canonical_message(message: dict[str, Any]) -> dict[str, Any]:
    kind = message["type"]
    if kind.startswith("lifespan."):
        return {"type": kind}
    if kind.startswith("websocket."):
        return _canonical_websocket_message(message)
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
    raise RuntimeError(f"unexpected ASGI event in the HTTP response slice: {kind!r}")


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
            "path_param": {
                "value": _json_safe(path_value),
                "type": type(path_value).__name__,
            },
            "context_value": context_value,
            "different_worker_thread": current_thread_id != caller_thread_id,
            "invocation_count": state["invocation_count"],
        }
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(content=spec["response_content"])


def _sync_request_runtime_observer_response(
    request: Any, spec: dict[str, Any], state: dict[str, Any]
) -> Any:
    request_actions = []
    for index, action in enumerate(spec["actions"]):
        if not isinstance(action, dict) or not isinstance(action.get("operation"), str):
            raise ValueError(f"sync request action[{index}] must be a tagged object")
        operation = action["operation"]
        if operation == "callable-property":
            _strict_object(action, {"operation", "property"}, "callable-property action")
            if action["property"] != "receive":
                raise ValueError("callable-property action must read Request.receive")
            value = getattr(request, action["property"])
            request_actions.append(
                {
                    "operation": operation,
                    "property": action["property"],
                    "callable": callable(value),
                }
            )
        elif operation == "construct-stream":
            _strict_object(
                action,
                {"operation", "method", "attributes"},
                "construct-stream action",
            )
            if action["method"] != "stream":
                raise ValueError("construct-stream action must call Request.stream")
            value = getattr(request, action["method"])()
            request_actions.append(
                {
                    "operation": operation,
                    "method": action["method"],
                    "attributes": {
                        name: callable(getattr(value, name, None)) for name in action["attributes"]
                    },
                }
            )
        elif operation == "construct-awaitable":
            _strict_object(
                action,
                {"operation", "method"},
                "construct-awaitable action",
            )
            if action["method"] not in {"body", "json"}:
                raise ValueError(
                    "construct-awaitable action must call Request.body or Request.json"
                )
            value = getattr(request, action["method"])()
            awaitable = inspect.isawaitable(value)
            close_result = value.close()
            request_actions.append(
                {
                    "operation": operation,
                    "method": action["method"],
                    "awaitable": awaitable,
                    "close_result": _json_safe(close_result),
                }
            )
        else:
            raise ValueError(f"unsupported synchronous Request action: {operation!r}")

    caller_thread_id = state["caller_thread_id"]
    if caller_thread_id is None:
        raise RuntimeError("sync endpoint ran without a caller thread identity")
    with state["lock"]:
        state["invocation_count"] += 1
        state["observation"] = {
            "context_value": state["context_var"].get(),
            "different_worker_thread": threading.get_ident() != caller_thread_id,
            "invocation_count": state["invocation_count"],
            "request_actions": request_actions,
        }
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(content=spec["response_content"])


def _materialize_exception_handlers(
    registry: Any,
    json_response_type: Any,
    plain_text_response_type: Any,
    http_exception_type: Any,
    websocket_exception_type: Any,
    handler_calls: list[str],
) -> tuple[dict[Any, Any], dict[str, Any]]:
    if not isinstance(registry, list):
        raise ValueError("exception-handler registry must be an ordered entry array")
    exception_types = {
        "HTTPException": http_exception_type,
        "WebSocketException": websocket_exception_type,
        "CustomWSException": type("CustomWSException", (Exception,), {}),
    }
    handlers: dict[Any, Any] = {}
    for index, raw_entry in enumerate(registry):
        context = f"exception_handlers[{index}]"
        entry = _strict_object(raw_entry, {"key", "handler"}, context)
        key_spec = entry["key"]
        if not isinstance(key_spec, dict) or not isinstance(key_spec.get("kind"), str):
            raise ValueError(f"{context}.key must be a tagged handler key")
        if key_spec["kind"] == "status-code":
            _strict_object(key_spec, {"kind", "status_code"}, f"{context}.key")
            key = key_spec["status_code"]
            if type(key) is not int:
                raise ValueError(f"{context}.key.status_code must be an integer")
        elif key_spec["kind"] == "exception-class":
            if key_spec.get("name") == "HTTPException":
                _strict_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = http_exception_type
            elif key_spec.get("name") == "Exception":
                _strict_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = Exception
            elif key_spec.get("name") == "BodyReuseException":
                _strict_object(key_spec, {"kind", "name", "base_class"}, f"{context}.key")
                if key_spec["base_class"] != "HTTPException":
                    raise ValueError("BodyReuseException must derive from HTTPException")
                key = type("BodyReuseException", (http_exception_type,), {})
                exception_types["BodyReuseException"] = key
            elif key_spec.get("name") == "CustomWSException":
                _strict_object(key_spec, {"kind", "name", "base_class"}, f"{context}.key")
                if key_spec["base_class"] != "Exception":
                    raise ValueError("CustomWSException must derive from Exception")
                key = exception_types["CustomWSException"]
            else:
                raise ValueError(f"{context}.key names an unsupported exception class")
        else:
            raise ValueError(f"{context}.key uses an unsupported kind")

        recipe = entry["handler"]
        if not isinstance(recipe, dict) or not isinstance(recipe.get("kind"), str):
            raise ValueError(f"{context}.handler must use a tagged handler recipe")

        def make_handler(spec: dict[str, Any]) -> Any:
            if spec.get("kind") == "websocket-close-handler":
                _strict_object(
                    spec,
                    {"kind", "label", "callable_kind", "code"},
                    "WebSocket close handler",
                )
                if spec["callable_kind"] != "sync-from-thread":
                    raise ValueError(
                        "WebSocket close handler must preserve the source sync callback"
                    )

                def websocket_close_handler(websocket: Any, _exc: Exception) -> None:
                    handler_calls.append(spec["label"])
                    import anyio

                    anyio.from_thread.run(websocket.close, spec["code"])

                return websocket_close_handler

            async def handler(request: Any, exc: Exception) -> Any:
                if spec["kind"] == "json-exception-detail-response":
                    _strict_object(
                        spec,
                        {"kind", "status_from_exception"},
                        "JSON exception-detail response handler",
                    )
                    if spec["status_from_exception"] is not True:
                        raise ValueError("exception-detail handler must use exception status")
                    return json_response_type({"detail": exc.detail}, status_code=exc.status_code)
                if spec["kind"] == "json-literal-response":
                    _strict_object(
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
                    _strict_object(
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
                    _strict_object(
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


def _raise_lifespan_failure(spec: dict[str, Any]) -> None:
    if spec.get("failure_exception_type", "RuntimeError") == "CancelledError":
        raise asyncio.CancelledError(spec["failure_message"])
    raise RuntimeError(spec["failure_message"])


def _materialize_application(
    app_spec: dict[str, Any],
) -> tuple[Any, list[str], list[dict[str, Any]], Any, list[dict[str, Any]]]:
    from starlette.applications import Starlette
    from starlette.exceptions import HTTPException, WebSocketException
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route, WebSocketRoute

    if set(app_spec) != {
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
        "max_body_size",
    }:
        raise ValueError("Starlette.__init__ arguments do not match the declared workflow")
    lifespan_spec = app_spec["lifespan"]
    lifecycle_trace: list[str] = []
    if lifespan_spec == {
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
    elif isinstance(lifespan_spec, dict) and lifespan_spec.get("kind") in {
        "sync-generator",
        "async-generator",
    }:
        required_fields = {
            "kind",
            "record_entry",
            "record_exit",
            "failure_stage",
            "failure_message",
            "yield_behavior",
            "shutdown_exception_behavior",
        }
        if not required_fields <= lifespan_spec.keys() or lifespan_spec.keys() - required_fields - {
            "failure_exception_type",
            "yield_state",
        }:
            raise ValueError("generator lifespan input has invalid fields")

        def sync_lifespan(_app: Any) -> Any:
            lifecycle_trace.append("entry")
            if lifespan_spec["failure_stage"] == "startup":
                _raise_lifespan_failure(lifespan_spec)
            if lifespan_spec["yield_behavior"] == "none":
                return
            try:
                yield lifespan_spec.get("yield_state")
                if lifespan_spec["yield_behavior"] == "extra":
                    yield lifespan_spec.get("yield_state")
            except RuntimeError:
                if lifespan_spec["shutdown_exception_behavior"] == "suppress":
                    lifecycle_trace.append("suppressed-shutdown-error")
                    return
                raise
            finally:
                if lifespan_spec["record_exit"]:
                    lifecycle_trace.append("exit")
                if lifespan_spec["failure_stage"] == "shutdown":
                    _raise_lifespan_failure(lifespan_spec)

        async def async_lifespan(_app: Any) -> Any:
            lifecycle_trace.append("entry")
            if lifespan_spec["failure_stage"] == "startup":
                _raise_lifespan_failure(lifespan_spec)
            if lifespan_spec["yield_behavior"] == "none":
                return
            try:
                yield lifespan_spec.get("yield_state")
                if lifespan_spec["yield_behavior"] == "extra":
                    yield lifespan_spec.get("yield_state")
            except RuntimeError:
                if lifespan_spec["shutdown_exception_behavior"] == "suppress":
                    lifecycle_trace.append("suppressed-shutdown-error")
                    return
                raise
            finally:
                if lifespan_spec["record_exit"]:
                    lifecycle_trace.append("exit")
                if lifespan_spec["failure_stage"] == "shutdown":
                    _raise_lifespan_failure(lifespan_spec)

        lifespan = sync_lifespan if lifespan_spec["kind"] == "sync-generator" else async_lifespan
    elif (
        isinstance(lifespan_spec, dict)
        and lifespan_spec.get("kind") == "async-context-manager-shadowed-specials"
    ):
        if set(lifespan_spec) != {
            "kind",
            "class_entry_effect",
            "instance_entry_effect",
            "class_exit_effect",
            "instance_exit_effect",
        }:
            raise ValueError("shadowed async context-manager input has invalid fields")

        class ContextManager:
            async def __aenter__(self) -> None:
                lifecycle_trace.append(lifespan_spec["class_entry_effect"])
                return None

            async def __aexit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> bool:
                lifecycle_trace.append(lifespan_spec["class_exit_effect"])
                return False

        context_manager = ContextManager()

        async def shadowed_enter() -> None:
            lifecycle_trace.append(lifespan_spec["instance_entry_effect"])
            return None

        async def shadowed_exit(_exc_type: Any, _exc: Any, _tb: Any) -> bool:
            lifecycle_trace.append(lifespan_spec["instance_exit_effect"])
            return False

        context_manager.__aenter__ = shadowed_enter
        context_manager.__aexit__ = shadowed_exit

        def lifespan(_app: Any) -> Any:
            return context_manager
    else:
        raise ValueError("lifespan input must use a declared context-manager marker")

    route_objects = []
    request_observations: list[dict[str, Any]] = []
    sync_endpoint_states: list[dict[str, Any]] = []
    handler_calls: list[str] = []
    route_endpoint: Any = None
    exception_handlers, exception_types = _materialize_exception_handlers(
        app_spec["exception_handlers"],
        JSONResponse,
        PlainTextResponse,
        HTTPException,
        WebSocketException,
        handler_calls,
    )
    for route in app_spec["routes"]:
        if isinstance(route, dict) and route.get("kind") == "websocket-route":
            _strict_object(route, {"kind", "path", "endpoint"}, "WebSocket route input")
            endpoint_spec = route["endpoint"]
            if not isinstance(endpoint_spec, dict) or not isinstance(
                endpoint_spec.get("kind"), str
            ):
                raise ValueError("WebSocket endpoint input must be a declared endpoint record")
            if endpoint_spec["kind"] == "http-exception":
                _strict_object(
                    endpoint_spec,
                    {"kind", "status_code", "detail", "headers"},
                    "WebSocket HTTPException endpoint",
                )

                def make_websocket_http_exception_endpoint(spec: dict[str, Any]) -> Any:
                    async def endpoint(_websocket: Any) -> None:
                        arguments = {
                            "status_code": spec["status_code"],
                            "headers": dict(spec["headers"]),
                        }
                        if spec["detail"] is not None:
                            arguments["detail"] = spec["detail"]
                        raise HTTPException(**arguments)

                    return endpoint

                websocket_endpoint = make_websocket_http_exception_endpoint(endpoint_spec)
            elif endpoint_spec["kind"] == "websocket-action-sequence":
                _strict_object(
                    endpoint_spec,
                    {"kind", "actions"},
                    "WebSocket exception action sequence",
                )

                def make_websocket_exception_endpoint(spec: dict[str, Any]) -> Any:
                    async def endpoint(websocket: Any) -> None:
                        for action in spec["actions"]:
                            if action["action"] == "accept":
                                await websocket.accept()
                            elif action["action"] == "raise-websocket-exception":
                                arguments = {"code": action["code"]}
                                if "reason" in action:
                                    arguments["reason"] = action["reason"]
                                raise WebSocketException(**arguments)
                            elif action["action"] == "raise-custom-exception":
                                exception_type = exception_types[action["exception_class"]]
                                raise exception_type()
                            else:
                                raise ValueError(
                                    f"unsupported WebSocket exception action: {action['action']!r}"
                                )

                    return endpoint

                websocket_endpoint = make_websocket_exception_endpoint(endpoint_spec)
            else:
                raise ValueError("WebSocket route endpoint uses an unsupported input kind")
            route_objects.append(WebSocketRoute(route["path"], websocket_endpoint))
            continue
        if set(route) != {"kind", "path", "methods", "endpoint"} or route["kind"] != "http-route":
            raise ValueError("route input must be a declared http-route record")
        response_spec = route["endpoint"]
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
            _strict_object(
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
            _strict_object(
                response_spec,
                {
                    "kind",
                    "path_parameter",
                    "query_parameter",
                    "header_primary_case",
                    "header_alternate_case",
                    "cookie_name",
                    "response_content",
                    "status_code",
                    "media_type",
                },
                "request observer endpoint",
            )

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
        elif response_spec["kind"] == "request-connection-property":
            if set(response_spec) != {"kind", "property"}:
                raise ValueError("request connection-property input does not match its schema")

            def make_request_connection_property_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    value = getattr(request, spec["property"])
                    request_observations.append(
                        {
                            "property": spec["property"],
                            "value": _json_safe(value),
                            "type": type(value).__name__,
                        }
                    )
                    return PlainTextResponse("request-property-observed")

                return endpoint

            route_endpoint = make_request_connection_property_endpoint(response_spec)
        elif response_spec["kind"] == "request-stream-observer":
            if set(response_spec) != {"kind", "actions"}:
                raise ValueError("request stream-observer input does not match its schema")

            def make_request_stream_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    stream = request.stream()
                    observations = []
                    for action in spec["actions"]:
                        observations.append(await _request_stream_action(stream, action))
                    request_observations.append({"stream_actions": observations})
                    return PlainTextResponse("request-stream-observed")

                return endpoint

            route_endpoint = make_request_stream_endpoint(response_spec)
        elif response_spec["kind"] == "http-exception":
            _strict_object(
                response_spec,
                {"kind", "status_code", "detail", "headers"},
                "HTTP exception endpoint",
            )
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
            _strict_object(
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
            _strict_object(
                response_spec,
                {
                    "kind",
                    "callable_kind",
                    "path_parameter",
                    "context_var_name",
                    "context_value",
                    "response_content",
                },
                "sync request observer endpoint",
            )
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
        elif response_spec["kind"] == "sync-request-runtime-observer":
            _strict_object(
                response_spec,
                {
                    "kind",
                    "actions",
                    "context_var_name",
                    "context_value",
                    "response_content",
                },
                "sync request runtime observer endpoint",
            )
            sync_state = {
                "context_var": contextvars.ContextVar(response_spec["context_var_name"]),
                "context_value": response_spec["context_value"],
                "caller_thread_id": None,
                "invocation_count": 0,
                "observation": None,
                "lock": threading.Lock(),
            }
            sync_endpoint_states.append(sync_state)

            def make_runtime_endpoint(spec: dict[str, Any], state: dict[str, Any]) -> Any:
                def endpoint(request: Any) -> Any:
                    return _sync_request_runtime_observer_response(request, spec, state)

                return endpoint

            route_endpoint = make_runtime_endpoint(response_spec, sync_state)
        elif response_spec["kind"] == "asgi-callable-instance-observer":
            _strict_object(
                response_spec,
                {"kind", "response_content"},
                "ASGI callable-instance observer endpoint",
            )

            class ASGICallableInstanceObserver:
                def __init__(self, content: str) -> None:
                    self.content = content

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    response = PlainTextResponse(content=self.content)
                    await response(scope, receive, send)

            route_endpoint = ASGICallableInstanceObserver(response_spec["response_content"])
        elif response_spec["kind"] == "asgi-callable-action-sequence":
            _strict_object(
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
        route_objects.append(Route(route["path"], route_endpoint, methods=route["methods"]))
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        app = Starlette(
            debug=app_spec["debug"],
            routes=route_objects,
            middleware=app_spec["middleware"],
            exception_handlers=exception_handlers,
            lifespan=lifespan,
            max_body_size=app_spec["max_body_size"],
        )
    app._parity_lifespan_warnings = [
        {
            "category": f"{item.category.__module__}.{item.category.__qualname__}",
            "message": str(item.message),
        }
        for item in recorded_warnings
    ]
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
    step_args: dict[str, Any],
    lifecycle_trace: list[str],
    request_observations: list[dict[str, Any]],
    route_endpoint: Any,
    request_dispatch: bool,
    workflow_events: list[dict[str, Any]] | None = None,
    sync_endpoint_states: list[dict[str, Any]] | None = None,
    capture_dispatch_error: bool = False,
) -> dict[str, Any] | _CapturedDispatchError:
    scope = _make_scope(step_args["scope"])
    incoming = [_message(item) for item in step_args["receive"]]
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

    if step_args["send"] != {"kind": "capture-asgi-send"}:
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
    if start is None and scope["type"] == "websocket":
        start = next(
            (event for event in events if event["type"] == "websocket.http.response.start"),
            None,
        )
    if start is None and scope["type"] not in {"lifespan", "websocket"}:
        raise RuntimeError("Starlette completed without an http.response.start event")
    body_chunks = []
    for event in events:
        if event["type"] == "http.response.body":
            body_chunks.append(event["body"]["data"])
        elif event["type"] == "websocket.http.response.body":
            body_chunks.append(event["body_base64"])
    body = b"".join(base64.b64decode(chunk) for chunk in body_chunks)
    result = {
        "response_status": start["status"] if start is not None else None,
        "ordered_repeated_headers": (
            start.get("headers", start.get("headers_base64_pairs", [])) if start is not None else []
        ),
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "lifespan_scope_state": {
            "present": "state" in scope,
            "value": _json_safe(scope.get("state")),
        },
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": _server_error_observation(app, start, body, captured_exception),
    }
    if request_dispatch:
        if len(request_observations) > 1:
            raise RuntimeError("request observer endpoint ran more than once")
        result.update(
            {
                "request_observations": request_observations[0] if request_observations else None,
                "sync_endpoint_observations": _observed_sync_endpoint(sync_endpoint_states or []),
                "route_scope": {
                    "app_is_application": scope.get("app") is app,
                    "router_is_application_router": scope.get("router") is app.router,
                    "endpoint_is_route_endpoint": scope.get("endpoint") is route_endpoint,
                    "path_params_present": "path_params" in scope,
                    "path_params": _json_safe(scope.get("path_params")),
                },
            }
        )
        result = {
            key: result[key]
            for key in (
                "request_observations",
                "sync_endpoint_observations",
                "route_scope",
                "response_status",
                "ordered_repeated_headers",
                "asgi_event_order",
                "asgi_events",
            )
        }
        if captured_exception is not None:
            return _CapturedDispatchError(
                error=_dispatch_error(captured_exception),
                partial_value=result,
            )
    else:
        result["deprecation_warnings"] = list(getattr(app, "_parity_lifespan_warnings", []))
    return result


def _literal_arguments(
    step: dict[str, Any],
    expected: set[str],
    context: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if optional is None:
        arguments = _strict_object(step["arguments"], expected, f"{context} arguments")
    else:
        arguments = step["arguments"]
        if (
            not isinstance(arguments, dict)
            or not (expected - optional).issubset(arguments)
            or set(arguments) - expected
        ):
            raise ValueError(f"{context} arguments must contain its required input fields")
    values: dict[str, Any] = {}
    for name, descriptor in arguments.items():
        descriptor = _strict_object(descriptor, {"kind", "value"}, f"{context}.{name}")
        if descriptor["kind"] != "literal":
            raise ValueError(f"{context}.{name} must be an input literal")
        values[name] = descriptor["value"]
    return values


def _materialize_asgi_sequence_app(app_spec: dict[str, Any]) -> Any:
    app_spec = _strict_object(app_spec, {"kind", "messages"}, "ASGI sequence app")
    if app_spec["kind"] != "asgi-response-sequence" or not isinstance(app_spec["messages"], list):
        raise ValueError("ASGI app must be an input-defined message sequence")
    response_messages = app_spec["messages"]

    async def response_app(_scope: Any, _receive: Any, send: Any) -> None:
        for index, spec in enumerate(response_messages):
            if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            message_type = spec["type"]
            if message_type == "http.response.start":
                _strict_object(
                    spec,
                    {"type", "status", "headers_base64_pairs"},
                    f"inner response message[{index}]",
                )
                message = {
                    "type": message_type,
                    "status": spec["status"],
                    "headers": [
                        (
                            _decode_b64(pair[0], "inner response header name"),
                            _decode_b64(pair[1], "inner response header value"),
                        )
                        for pair in spec["headers_base64_pairs"]
                    ],
                }
            elif message_type == "http.response.body":
                _strict_object(
                    spec,
                    {"type", "body_base64", "more_body"},
                    f"inner response message[{index}]",
                )
                message = {
                    "type": message_type,
                    "body": _decode_b64(spec["body_base64"], "inner response body"),
                    "more_body": spec["more_body"],
                }
            elif message_type == "http.response.pathsend":
                _strict_object(
                    spec,
                    {"type", "path"},
                    f"inner response message[{index}]",
                )
                message = {"type": message_type, "path": spec["path"]}
            elif message_type == "websocket.close":
                _strict_object(
                    spec,
                    {"type", "code"},
                    f"inner response message[{index}]",
                )
                message = {"type": message_type, "code": spec["code"]}
            else:
                raise ValueError(f"unsupported inner response event: {message_type!r}")
            await send(message)

    return response_app


def _materialize_gzip_middleware(arguments: dict[str, Any]) -> Any:
    from starlette.middleware.gzip import GZipMiddleware

    response_app = _materialize_asgi_sequence_app(arguments["app"])
    constructor_arguments: dict[str, Any] = {
        "minimum_size": arguments["minimum_size"],
        "compresslevel": arguments["compresslevel"],
        "thread_minimum_size": arguments["thread_minimum_size"],
    }
    if "exclude_content_types" in arguments:
        constructor_arguments["exclude_content_types"] = tuple(arguments["exclude_content_types"])

    return GZipMiddleware(response_app, **constructor_arguments)


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
        optional={"exclude_content_types"},
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


def _materialize_protocol_middleware(surface: str, arguments: dict[str, Any]) -> Any:
    app = _materialize_asgi_sequence_app(arguments["app"])
    if surface == CORS_SURFACE:
        from starlette.middleware.cors import CORSMiddleware

        return CORSMiddleware(
            app, **{key: value for key, value in arguments.items() if key != "app"}
        )
    if surface == HTTPS_REDIRECT_SURFACE:
        from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

        return HTTPSRedirectMiddleware(app)
    if surface == TRUSTED_HOST_SURFACE:
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        return TrustedHostMiddleware(
            app, **{key: value for key, value in arguments.items() if key != "app"}
        )
    raise ValueError(f"unsupported ASGI middleware surface: {surface}")


def _run_protocol_middleware_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    constructor_step = steps[0]
    constructor_arguments = _literal_arguments(
        constructor_step,
        set(constructor_step["arguments"]),
        f"{case['surface']} constructor",
    )
    try:
        middleware = _materialize_protocol_middleware(case["surface"], constructor_arguments)
    except Exception as exc:
        error = _dispatch_error(exc)
        error["stage"] = "construct"
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {
                    "step_id": "construct",
                    "status": "error",
                    "error": error,
                    "partial_value": {},
                }
            ],
        }
    if case["operation"] == "__init__":
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {"step_id": "construct", "status": "ok", "value": {"constructed": True}}
            ],
        }
    dispatch_arguments = _literal_arguments(
        steps[1], {"scope", "receive", "send"}, f"{case['surface']} dispatch"
    )
    value = asyncio.run(_invoke(middleware, dispatch_arguments, [], [], None, False))
    selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": selected}],
    }


def _run_base_http_workflow_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "application",
            "request",
            "observations",
        },
        "BaseHTTPMiddleware base-http-workflow case",
    )
    if case["surface"] != BASE_HTTP_SURFACE or case["operation"] != BASE_HTTP_WORKFLOW_OPERATION:
        raise ValueError("workflow is outside the BaseHTTPMiddleware base-http-workflow operation")
    if not isinstance(case["case_id"], str):
        raise ValueError("BaseHTTPMiddleware case_id must be a string")
    if case["target_profiles"] != ["python-package-cpython312"] or case["assets"] != []:
        raise ValueError(
            "BaseHTTPMiddleware workflow selects only the Python-package profile and no assets"
        )
    if case["observations"] != [BASE_HTTP_WORKFLOW_OPERATION]:
        raise ValueError("BaseHTTPMiddleware observations must select base-http-workflow")

    application = case["application"]
    allowed_application_keys = {
        frozenset({"debug", "routes", "middleware"}),
        frozenset({"debug", "routes", "middleware", "downstream"}),
    }
    if not isinstance(application, dict) or frozenset(application) not in allowed_application_keys:
        raise ValueError("BaseHTTPMiddleware application input has unknown or missing fields")
    if type(application["debug"]) is not bool:
        raise ValueError("BaseHTTPMiddleware application.debug must be boolean")
    route_specs = application["routes"]
    if not isinstance(route_specs, list) or len(route_specs) > 1:
        raise ValueError("BaseHTTPMiddleware workflow supports zero or one route")
    route_spec = None
    endpoint_spec = None
    route_kind = None
    exception_spec = None
    if route_specs:
        route_spec = _strict_object(
            route_specs[0],
            {"kind", "path", "methods", "endpoint"},
            "BaseHTTPMiddleware route",
        )
        if route_spec["kind"] != "http-route" or route_spec["path"] != "/":
            raise ValueError("BaseHTTPMiddleware route input is invalid")
        if (
            not isinstance(route_spec["methods"], list)
            or not route_spec["methods"]
            or any(not isinstance(method, str) or not method for method in route_spec["methods"])
        ):
            raise ValueError("BaseHTTPMiddleware route methods must be non-empty strings")
        endpoint_spec = route_spec["endpoint"]
        if not isinstance(endpoint_spec, dict) or not isinstance(endpoint_spec.get("kind"), str):
            raise ValueError("BaseHTTPMiddleware route endpoint must be tagged")
        route_kind = endpoint_spec["kind"]
        if route_kind == "plain-text-response":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "content", "status_code"},
                "BaseHTTPMiddleware route endpoint",
            )
            if (
                not isinstance(endpoint_spec["content"], str)
                or type(endpoint_spec["status_code"]) is not int
                or not 100 <= endpoint_spec["status_code"] <= 599
            ):
                raise ValueError("BaseHTTPMiddleware route input is invalid")
        elif route_kind == "request-body-response":
            _strict_object(endpoint_spec, {"kind"}, "BaseHTTPMiddleware request-body endpoint")
            if "POST" not in route_spec["methods"]:
                raise ValueError("request-body-response routes must accept POST")
        elif route_kind == "request-stream-response":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "stop_after_chunks"},
                "BaseHTTPMiddleware request-stream endpoint",
            )
            if (
                "POST" not in route_spec["methods"]
                or type(endpoint_spec["stop_after_chunks"]) is not int
                or endpoint_spec["stop_after_chunks"] < 1
            ):
                raise ValueError("BaseHTTPMiddleware request-stream endpoint input is invalid")
        elif route_kind == "raise-exception":
            _strict_object(
                endpoint_spec,
                {"kind", "exception"},
                "BaseHTTPMiddleware raising endpoint",
            )
            exception_spec = _strict_object(
                endpoint_spec["exception"],
                {"class", "message"},
                "BaseHTTPMiddleware endpoint exception",
            )
            if exception_spec["class"] != "Exception" or not isinstance(
                exception_spec["message"], str
            ):
                raise ValueError("BaseHTTPMiddleware endpoint exception input is invalid")
        else:
            raise ValueError("BaseHTTPMiddleware route endpoint kind is unsupported")

    middleware_specs = application["middleware"]
    if not isinstance(middleware_specs, list) or len(middleware_specs) != 1:
        raise ValueError("BaseHTTPMiddleware workflow requires one configured Middleware")
    middleware_spec = _strict_object(
        middleware_specs[0],
        {"kind", "dispatch_actions"},
        "BaseHTTPMiddleware configured Middleware",
    )
    if middleware_spec["kind"] != "base-http-middleware":
        raise ValueError("configured middleware must be a BaseHTTPMiddleware subclass")
    dispatch_actions = middleware_spec["dispatch_actions"]
    if not isinstance(dispatch_actions, list) or not dispatch_actions:
        raise ValueError("BaseHTTPMiddleware dispatch_actions must be non-empty")
    awaited = False
    await_index = None
    returned = None
    saw_header_mutation = False
    for index, raw_action in enumerate(dispatch_actions):
        context = f"BaseHTTPMiddleware dispatch_actions[{index}]"
        if not isinstance(raw_action, dict) or not isinstance(raw_action.get("kind"), str):
            raise ValueError(f"{context} must be tagged")
        kind = raw_action["kind"]
        if kind == "read-request-body":
            _strict_object(raw_action, {"kind"}, context)
        elif kind == "read-request-stream-next":
            _strict_object(raw_action, {"kind"}, context)
        elif kind == "await-call-next":
            _strict_object(raw_action, {"kind"}, context)
            if awaited or returned is not None:
                raise ValueError("BaseHTTPMiddleware dispatch must await call_next once")
            awaited = True
            await_index = index
        elif kind == "set-call-next-response-header":
            action = _strict_object(raw_action, {"kind", "name", "value"}, context)
            if not awaited or returned is not None or saw_header_mutation:
                raise ValueError("response header mutation requires one awaited call_next response")
            if (
                not isinstance(action["name"], str)
                or not action["name"]
                or not isinstance(action["value"], str)
                or not action["value"]
                or any(char in action["name"] + action["value"] for char in "\r\n")
            ):
                raise ValueError("BaseHTTPMiddleware response header input is invalid")
            saw_header_mutation = True
        elif kind == "return-call-next-response":
            _strict_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None or index != len(dispatch_actions) - 1:
                raise ValueError("call_next response must be returned as the final dispatch action")
            returned = "call-next"
        elif kind == "return-plain-text-response":
            action = _strict_object(raw_action, {"kind", "content", "status_code"}, context)
            if (
                not awaited
                or returned is not None
                or saw_header_mutation
                or index != len(dispatch_actions) - 1
                or not isinstance(action["content"], str)
                or type(action["status_code"]) is not int
                or not 100 <= action["status_code"] <= 599
            ):
                raise ValueError("replacement response must follow call_next and end dispatch")
            returned = "replacement"
        else:
            raise ValueError(f"{context} has an unsupported action kind")
    if not awaited or returned is None:
        raise ValueError("BaseHTTPMiddleware dispatch action sequence is incomplete")
    if saw_header_mutation and returned != "call-next":
        raise ValueError("only the call_next response can be mutated")
    if returned == "call-next" and route_spec is None and "downstream" not in application:
        raise ValueError("call_next response requires a configured route or downstream ASGI app")

    downstream_spec = None
    if "downstream" in application:
        downstream_spec = _strict_object(
            application["downstream"],
            {"kind", "steps"},
            "BaseHTTPMiddleware downstream ASGI input",
        )
        if downstream_spec["kind"] != "asgi-sequence" or route_spec is not None:
            raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
        steps = downstream_spec["steps"]
        if (
            not isinstance(steps, list)
            or len(steps) != 3
            or steps[0] != {"kind": "receive"}
            or steps[2] != {"kind": "receive"}
        ):
            raise ValueError("downstream ASGI input must receive, send response.start, receive")
        send_step = _strict_object(steps[1], {"kind", "message"}, "downstream ASGI send step")
        if send_step["kind"] != "send":
            raise ValueError("downstream ASGI middle step must send response.start")
        message = _strict_object(
            send_step["message"],
            {"type", "status", "headers_base64_pairs"},
            "downstream ASGI response.start input",
        )
        if (
            message["type"] != "http.response.start"
            or type(message["status"]) is not int
            or not 100 <= message["status"] <= 599
            or not isinstance(message["headers_base64_pairs"], list)
        ):
            raise ValueError("downstream ASGI send step must declare a valid response.start")

    required_covers = {
        f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.construct-configured-middleware"
    }
    if saw_header_mutation:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.await-call-next-header-mutation"
        )
    if returned == "replacement":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.return-replacement-response"
        )

    request = _strict_object(
        case["request"],
        {"scope", "receive", "receive_after_events", "send_checkpoints"},
        "BaseHTTPMiddleware request",
    )
    scope_spec = _strict_object(
        request["scope"],
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
        "BaseHTTPMiddleware HTTP scope",
    )
    _strict_object(
        scope_spec["asgi"], {"version", "spec_version"}, "BaseHTTPMiddleware ASGI version"
    )
    path = scope_spec["path"]
    if (
        scope_spec["type"] != "http"
        or scope_spec["asgi"] != {"version": "3.0", "spec_version": "2.4"}
        or not isinstance(scope_spec["method"], str)
        or scope_spec["method"] not in {"GET", "POST"}
        or scope_spec["scheme"] != "http"
        or not isinstance(scope_spec["http_version"], str)
        or not isinstance(path, str)
        or (route_spec is not None and path != route_spec["path"])
        or (route_spec is None and downstream_spec is None and path == "/")
        or (route_spec is not None and scope_spec["method"] not in route_spec["methods"])
        or (returned == "call-next" and route_spec is None and downstream_spec is None)
        or not isinstance(scope_spec["root_path"], str)
    ):
        raise ValueError("BaseHTTPMiddleware request scope does not select its declared route case")
    if _decode_b64(scope_spec["raw_path_base64"], "BaseHTTPMiddleware raw path") != path.encode(
        "ascii"
    ) or _decode_b64(scope_spec["query_string_base64"], "BaseHTTPMiddleware query string"):
        raise ValueError("BaseHTTPMiddleware scope raw path or query input is invalid")
    headers = scope_spec["headers_base64_pairs"]
    if not isinstance(headers, list):
        raise ValueError("BaseHTTPMiddleware scope headers must be an array")
    for index, pair in enumerate(headers):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"BaseHTTPMiddleware scope header[{index}] is invalid")
        for value in pair:
            if not isinstance(value, str):
                raise ValueError(f"BaseHTTPMiddleware scope header[{index}] is invalid")
            _decode_b64(value, f"BaseHTTPMiddleware scope header[{index}]")
    for name in ("client", "server"):
        address = scope_spec[name]
        if (
            not isinstance(address, list)
            or len(address) != 2
            or not isinstance(address[0], str)
            or type(address[1]) is not int
        ):
            raise ValueError(f"BaseHTTPMiddleware scope.{name} must be a host/port pair")
    receive_specs = request["receive"]
    if not isinstance(receive_specs, list) or not receive_specs:
        raise ValueError("BaseHTTPMiddleware request requires HTTP body events")
    for index, receive_spec in enumerate(receive_specs):
        receive_spec = _strict_object(
            receive_spec,
            {"type", "body_base64", "more_body"},
            f"BaseHTTPMiddleware HTTP request event[{index}]",
        )
        if (
            receive_spec["type"] != "http.request"
            or type(receive_spec["more_body"]) is not bool
            or receive_spec["more_body"] is not (index < len(receive_specs) - 1)
        ):
            raise ValueError("BaseHTTPMiddleware request events must end with one final body event")
        _decode_b64(receive_spec["body_base64"], f"BaseHTTPMiddleware request body[{index}]")
    if not isinstance(request["receive_after_events"], str) or request[
        "receive_after_events"
    ] not in {"disconnect", "block"}:
        raise ValueError("receive_after_events must be disconnect or block")
    send_checkpoints = request["send_checkpoints"]
    if (
        not isinstance(send_checkpoints, list)
        or any(type(index) is not int or not 0 <= index <= 2 for index in send_checkpoints)
        or len(set(send_checkpoints)) != len(send_checkpoints)
    ):
        raise ValueError("send_checkpoints must contain unique output-send indices from 0 to 2")

    request_body = b"".join(
        _decode_b64(item["body_base64"], "BaseHTTPMiddleware request body")
        for item in receive_specs
    )
    if (
        route_kind == "request-body-response"
        and request_body
        and await_index is not None
        and any(action["kind"] == "read-request-body" for action in dispatch_actions[:await_index])
        and any(
            action["kind"] == "read-request-body" for action in dispatch_actions[await_index + 1 :]
        )
    ):
        required_covers.add(f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.body-cache-replay")
    if route_kind == "raise-exception" and returned == "call-next":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.exception-context-propagation"
        )
    stream_reads_before_call_next = [
        index
        for index, action in enumerate(dispatch_actions)
        if action["kind"] == "read-request-stream-next"
        and await_index is not None
        and index < await_index
    ]
    stream_reads_after_call_next = [
        index
        for index, action in enumerate(dispatch_actions)
        if action["kind"] == "read-request-stream-next"
        and await_index is not None
        and index > await_index
    ]
    if route_kind == "request-stream-response":
        chunks = [
            _decode_b64(item["body_base64"], "BaseHTTPMiddleware request body")
            for item in receive_specs
        ]
        if (
            returned != "call-next"
            or not stream_reads_before_call_next
            or not stream_reads_after_call_next
            or len(chunks) != 3
            or any(not chunk for chunk in chunks)
            or request["receive_after_events"] != "block"
        ):
            raise ValueError(
                "partial request-stream forwarding requires dispatch reads on both sides of call_next, three non-empty chunks, and a blocking exhausted receive"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.partial-request-stream-forwarding"
        )
    if downstream_spec is not None:
        if (
            request["receive_after_events"] != "block"
            or returned != "replacement"
            or send_checkpoints != [0, 1]
        ):
            raise ValueError(
                "downstream receive race requires a blocking receive, replacement response, and checkpoints after both outer sends"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.response-completion-unblocks-downstream-receive"
        )
    if not isinstance(case["covers"], list) or set(case["covers"]) != required_covers:
        raise ValueError("BaseHTTPMiddleware covers differ from its input actions")

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse, Response
    from starlette.routing import Route

    execution_trace: list[dict[str, Any]] = []
    dispatch_body_reads: list[dict[str, Any]] = []
    dispatch_stream_reads: list[dict[str, Any]] = []
    downstream_stream_reads: list[dict[str, Any]] = []

    class InputDefinedBaseHTTPMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            response = None
            stream_iterator = None
            for action_index, action in enumerate(dispatch_actions):
                kind = action["kind"]
                if kind == "read-request-body":
                    body = await request.body()
                    dispatch_body_reads.append(
                        {
                            "action_index": action_index,
                            "body_base64": base64.b64encode(body).decode("ascii"),
                        }
                    )
                elif kind == "read-request-stream-next":
                    if stream_iterator is None:
                        stream_iterator = request.stream()
                    try:
                        chunk = await stream_iterator.__anext__()
                    except StopAsyncIteration:
                        chunk = None
                    dispatch_stream_reads.append(
                        {
                            "action_index": action_index,
                            "phase": (
                                "before-call-next"
                                if action_index < await_index
                                else "after-call-next"
                            ),
                            "body_base64": (
                                base64.b64encode(chunk).decode("ascii")
                                if chunk is not None
                                else None
                            ),
                        }
                    )
                elif kind == "await-call-next":
                    response = await call_next(request)
                elif kind == "set-call-next-response-header":
                    response.headers[action["name"]] = action["value"]
                elif kind == "return-call-next-response":
                    return response
                elif kind == "return-plain-text-response":
                    return PlainTextResponse(
                        action["content"],
                        status_code=action["status_code"],
                    )
            raise RuntimeError("BaseHTTPMiddleware dispatch action sequence returned no response")

    routes = []
    if route_spec is not None:
        if route_kind == "request-body-response":

            async def endpoint(request: Any) -> Any:
                return PlainTextResponse(await request.body())
        elif route_kind == "raise-exception":
            exception_type = getattr(builtins, exception_spec["class"])
            exception_message = exception_spec["message"]

            def endpoint(_request: Any) -> None:
                raise exception_type(exception_message)
        elif route_kind == "request-stream-response":
            stop_after_chunks = endpoint_spec["stop_after_chunks"]

            async def endpoint(request: Any) -> Response:
                async for chunk in request.stream():
                    downstream_stream_reads.append(
                        {
                            "index": len(downstream_stream_reads),
                            "body_base64": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                    if len(downstream_stream_reads) >= stop_after_chunks:
                        break
                return Response()
        else:

            def endpoint(_request: Any) -> Any:
                return PlainTextResponse(
                    endpoint_spec["content"],
                    status_code=endpoint_spec["status_code"],
                )

        routes.append(Route(route_spec["path"], endpoint, methods=route_spec["methods"]))
        app = Starlette(
            debug=application["debug"],
            routes=routes,
            middleware=[Middleware(InputDefinedBaseHTTPMiddleware)],
        )
    elif downstream_spec is not None:

        async def downstream(scope: Any, receive: Any, send: Any) -> None:
            receive_index = 0
            downstream_send_index = 0
            for step in downstream_spec["steps"]:
                if step["kind"] == "receive":
                    execution_trace.append(
                        {"event": "downstream-receive-enter", "index": receive_index}
                    )
                    message = await receive()
                    execution_trace.append(
                        {
                            "event": "downstream-receive-return",
                            "index": receive_index,
                            "message": _canonical_http_message(message),
                        }
                    )
                    receive_index += 1
                else:
                    message_spec = step["message"]
                    message = {
                        "type": message_spec["type"],
                        "status": message_spec["status"],
                        "headers": [
                            (
                                _decode_b64(pair[0], "downstream response header name"),
                                _decode_b64(pair[1], "downstream response header value"),
                            )
                            for pair in message_spec["headers_base64_pairs"]
                        ],
                    }
                    execution_trace.append(
                        {
                            "event": "downstream-send",
                            "index": downstream_send_index,
                            "message": _canonical_message(message),
                        }
                    )
                    await send(message)
                    downstream_send_index += 1

        app = InputDefinedBaseHTTPMiddleware(downstream)
    else:
        app = Starlette(
            debug=application["debug"],
            routes=[],
            middleware=[Middleware(InputDefinedBaseHTTPMiddleware)],
        )

    scope = _make_scope(scope_spec)
    incoming = [_message(spec) for spec in receive_specs]
    sent: list[dict[str, Any]] = []
    request_receive_events: list[dict[str, Any]] = []
    receive_index = 0
    send_index = 0
    send_checkpoint_indices = set(send_checkpoints)

    async def receive() -> dict[str, Any]:
        nonlocal receive_index
        if receive_index < len(incoming):
            message = incoming[receive_index]
            receive_index += 1
        elif request["receive_after_events"] == "block":
            await asyncio.Event().wait()
        else:
            message = {"type": "http.disconnect"}
        request_receive_events.append(_canonical_http_message(message))
        return message

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index
        sent.append(message)
        execution_trace.append(
            {"event": "outer-send", "index": send_index, "message": _canonical_message(message)}
        )
        if send_index in send_checkpoint_indices:
            await asyncio.sleep(0)
        send_index += 1

    try:
        asyncio.run(app(scope, receive, send))
        propagated_exception = None
    except Exception as exc:
        propagated_exception = _base_http_exception_value(exc)
    events = [_canonical_message(message) for message in sent]
    start = next((event for event in events if event["type"] == "http.response.start"), None)
    if start is None and propagated_exception is None:
        raise RuntimeError("Starlette completed without an http.response.start event")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    value = {
        "response_status": start["status"] if start is not None else None,
        "ordered_repeated_headers": start["headers"] if start is not None else [],
        "response_bytes": {
            "encoding": "base64",
            "data": base64.b64encode(body).decode("ascii"),
        },
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "dispatch_body_reads": dispatch_body_reads,
        "dispatch_stream_reads": dispatch_stream_reads,
        "downstream_stream_reads": downstream_stream_reads,
        "request_receive_events": request_receive_events,
        "execution_trace": execution_trace,
        "propagated_exception": propagated_exception,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": BASE_HTTP_WORKFLOW_OPERATION,
                "status": "ok",
                "value": value,
            }
        ],
    }


def _canonical_http_message(message: dict[str, Any]) -> dict[str, Any]:
    kind = message["type"]
    if kind == "http.request":
        return {
            "type": kind,
            "body_base64": base64.b64encode(message.get("body", b"")).decode("ascii"),
            "more_body": message.get("more_body", False),
        }
    if kind == "http.disconnect":
        return {"type": kind}
    return _canonical_message(message)


def _base_http_exception_value(exc: BaseException) -> dict[str, Any]:
    def relationship_value(value: BaseException | None) -> dict[str, str] | None:
        if value is None:
            return None
        return {
            "class": f"{type(value).__module__}.{type(value).__qualname__}",
            "message": str(value),
        }

    return {
        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": str(exc),
        "cause": relationship_value(exc.__cause__),
        "context": relationship_value(exc.__context__),
        "suppress_context": bool(exc.__suppress_context__),
    }


def _run_session_workflow_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "constructor",
            "requests",
            "observations",
        },
        "SessionMiddleware session-workflow case",
    )
    if (
        case["surface"] != SESSION_MIDDLEWARE_SURFACE
        or case["operation"] != SESSION_WORKFLOW_OPERATION
    ):
        raise ValueError("workflow is outside the SessionMiddleware session-workflow operation")
    if not isinstance(case["case_id"], str):
        raise ValueError("SessionMiddleware case_id must be a string")
    for field in ("covers", "target_profiles", "assets"):
        if not isinstance(case[field], list):
            raise ValueError(f"SessionMiddleware {field} must be an array")
    if case["observations"] != [SESSION_WORKFLOW_OPERATION]:
        raise ValueError("SessionMiddleware observations must select session-workflow")

    constructor = _strict_object(
        case["constructor"],
        {
            "secret_key",
            "session_cookie",
            "max_age",
            "path",
            "same_site",
            "https_only",
            "domain",
            "clock_epoch",
        },
        "SessionMiddleware constructor",
    )
    secret_key_input = constructor["secret_key"]
    secret_key_observation = None
    if isinstance(secret_key_input, str):
        secret_key = secret_key_input
    else:
        _strict_object(
            secret_key_input,
            {"kind", "value"},
            "SessionMiddleware secret key",
        )
        if secret_key_input["kind"] != "secret" or not isinstance(secret_key_input["value"], str):
            raise ValueError("SessionMiddleware secret key must be a string or Secret input")
        from starlette.datastructures import Secret

        secret_key = Secret(secret_key_input["value"])
        secret_key_observation = {
            "repr": repr(secret_key),
            "string": str(secret_key),
            "truth": bool(secret_key),
        }
    if not isinstance(constructor["session_cookie"], str):
        raise ValueError("SessionMiddleware session_cookie must be a string")
    if constructor["max_age"] is not None and type(constructor["max_age"]) is not int:
        raise ValueError("SessionMiddleware max_age must be an integer or null")
    if not isinstance(constructor["path"], str):
        raise ValueError("SessionMiddleware path must be a string")
    if not isinstance(constructor["same_site"], str):
        raise ValueError("SessionMiddleware same_site must be a string")
    if not isinstance(constructor["https_only"], bool):
        raise ValueError("SessionMiddleware https_only must be a boolean")
    if constructor["domain"] is not None and not isinstance(constructor["domain"], str):
        raise ValueError("SessionMiddleware domain must be a string or null")
    clock_epoch = constructor["clock_epoch"]
    if clock_epoch is not None and type(clock_epoch) is not int:
        raise ValueError("SessionMiddleware clock_epoch must be an integer or null")
    if not isinstance(case["requests"], list):
        raise ValueError("SessionMiddleware requests must be an array")

    from starlette.middleware.sessions import Session, SessionMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.websockets import WebSocket

    current: dict[str, Any] = {}

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        action = current["action"]
        action_kind = action["kind"]
        mutation_result = None
        if action_kind == "websocket-view":
            websocket = WebSocket(scope, receive, send)
            session = websocket.scope["session"]
            session_value = dict(session)
            accessed = session.accessed
            modified = session.modified
            accept = action["accept"]
            headers = [
                (
                    _decode_b64(pair[0], "WebSocket accept header name"),
                    _decode_b64(pair[1], "WebSocket accept header value"),
                )
                for pair in accept["headers_base64_pairs"]
            ]
            await websocket.accept(subprotocol=accept["subprotocol"], headers=headers)
            close = action["close"]
            await websocket.close(code=close["code"], reason=close["reason"])
        elif action_kind == "passthrough":
            for outbound in action["outbound"]:
                await receive()
                await send({"type": outbound["type"]})
            session_value = None
            accessed = None
            modified = None
        else:
            request = Request(scope, receive)
            if action_kind == "view":
                session = request.session
                session_value = dict(session)
            elif action_kind == "update":
                session = request.session
                session.update(action["values"])
                session_value = dict(session)
            elif action_kind == "clear":
                session = request.session
                session.clear()
                session_value = dict(session)
            elif action_kind == "session-mutation":
                session = Session(action["initial"])
                scope["session"] = session
                mutation = action["mutation"]
                mutation_kind = mutation["kind"]
                if mutation_kind == "set":
                    session[mutation["key"]] = mutation["value"]
                elif mutation_kind == "delete":
                    del session[mutation["key"]]
                elif mutation_kind == "clear":
                    session.clear()
                elif mutation_kind == "pop":
                    mutation_result = session.pop(mutation["key"], mutation["default"])
                elif mutation_kind == "setdefault":
                    mutation_result = session.setdefault(mutation["key"], mutation["default"])
                elif mutation_kind == "update":
                    session.update(mutation["values"])
                session_value = dict(session)
            else:
                session_value = None
            live_session = scope["session"]
            accessed = live_session.accessed
            modified = live_session.modified
        current["session"] = _json_safe(session_value)
        current["accessed"] = accessed
        current["modified"] = modified
        current["mutation_result"] = _json_safe(mutation_result)
        if action_kind in {"websocket-view", "passthrough"}:
            return
        response = JSONResponse(
            {
                "session": session_value,
                "accessed": current["accessed"],
                "modified": current["modified"],
                "mutation_result": current["mutation_result"],
            }
        )
        await response(scope, receive, send)

    middleware = SessionMiddleware(
        app,
        secret_key=secret_key,
        session_cookie=constructor["session_cookie"],
        max_age=constructor["max_age"],
        path=constructor["path"],
        same_site=constructor["same_site"],
        https_only=constructor["https_only"],
        domain=constructor["domain"],
    )
    if clock_epoch is not None:
        # TimestampSigner.sign() and unsign() both consult this per-instance clock.
        middleware.signer.get_timestamp = lambda: clock_epoch

    async def run_requests() -> list[dict[str, Any]]:
        outputs = []
        prior_set_cookies: dict[str, str | None] = {}
        actions_by_id: dict[str, dict[str, Any]] = {}
        seen_request_ids: set[str] = set()
        for index, request_spec in enumerate(case["requests"]):
            request_spec = _strict_object(
                request_spec,
                {"request_id", "scope", "receive", "cookie_source", "action"},
                f"SessionMiddleware request[{index}]",
            )
            request_id = request_spec["request_id"]
            if not isinstance(request_id, str) or request_id in seen_request_ids:
                raise ValueError("SessionMiddleware request_id values must be unique strings")
            seen_request_ids.add(request_id)
            scope = _make_scope(request_spec["scope"])

            cookie_source = request_spec["cookie_source"]
            if cookie_source is not None:
                if scope["type"] not in {"http", "websocket"}:
                    raise ValueError(
                        "SessionMiddleware cookie sources require HTTP or WebSocket scopes"
                    )
                if not isinstance(cookie_source, dict) or not isinstance(
                    cookie_source.get("kind"), str
                ):
                    raise ValueError("SessionMiddleware cookie_source must be a tagged object")
                if cookie_source["kind"] == "raw-cookie":
                    _strict_object(cookie_source, {"kind", "value"}, "raw-cookie source")
                    cookie_value = cookie_source["value"]
                    if not isinstance(cookie_value, str):
                        raise ValueError("raw-cookie value must be a string")
                    cookie_header = cookie_value.encode("latin-1")
                elif cookie_source["kind"] == "previous-set-cookie":
                    _strict_object(
                        cookie_source,
                        {"kind", "request_id"},
                        "previous-set-cookie source",
                    )
                    previous_request_id = cookie_source["request_id"]
                    if previous_request_id not in prior_set_cookies:
                        raise ValueError("previous-set-cookie must reference an earlier request_id")
                    previous_value = prior_set_cookies[previous_request_id]
                    if previous_value is None:
                        raise ValueError(
                            "previous-set-cookie referenced a response without Set-Cookie"
                        )
                    cookie_header = previous_value.encode("latin-1")
                else:
                    raise ValueError(
                        f"unsupported SessionMiddleware cookie source: {cookie_source['kind']!r}"
                    )
                scope["headers"].append((b"cookie", cookie_header))

            action = request_spec["action"]
            if not isinstance(action, dict) or not isinstance(action.get("kind"), str):
                raise ValueError("SessionMiddleware action must be a tagged object")
            if action["kind"] in {"view", "clear", "no-access"}:
                _strict_object(action, {"kind"}, "SessionMiddleware action")
            elif action["kind"] == "update":
                _strict_object(action, {"kind", "values"}, "SessionMiddleware update action")
                if not isinstance(action["values"], dict):
                    raise ValueError("SessionMiddleware update values must be an object")
            elif action["kind"] == "session-mutation":
                _strict_object(
                    action,
                    {"kind", "initial", "mutation"},
                    "SessionMiddleware direct Session mutation action",
                )
                if not isinstance(action["initial"], dict):
                    raise ValueError("SessionMiddleware mutation initial value must be an object")
                mutation = action["mutation"]
                if not isinstance(mutation, dict) or not isinstance(mutation.get("kind"), str):
                    raise ValueError("SessionMiddleware mutation must be a tagged object")
                mutation_keys = {
                    "set": {"kind", "key", "value"},
                    "delete": {"kind", "key"},
                    "clear": {"kind"},
                    "pop": {"kind", "key", "default"},
                    "setdefault": {"kind", "key", "default"},
                    "update": {"kind", "values"},
                }.get(mutation["kind"])
                if mutation_keys is None:
                    raise ValueError(f"unsupported Session mutation: {mutation['kind']!r}")
                _strict_object(mutation, mutation_keys, "SessionMiddleware mutation")
            elif action["kind"] == "websocket-view":
                _strict_object(
                    action,
                    {"kind", "accept", "close"},
                    "SessionMiddleware WebSocket view action",
                )
                accept = _strict_object(
                    action["accept"],
                    {"subprotocol", "headers_base64_pairs"},
                    "SessionMiddleware WebSocket accept action",
                )
                if accept["subprotocol"] is not None and not isinstance(accept["subprotocol"], str):
                    raise ValueError("WebSocket accept subprotocol must be a string or null")
                if (
                    accept["subprotocol"] is not None
                    and accept["subprotocol"] not in scope["subprotocols"]
                ):
                    raise ValueError("WebSocket accept subprotocol must be offered by the client")
                if not isinstance(accept["headers_base64_pairs"], list):
                    raise ValueError("WebSocket accept headers must be an array")
                for pair in accept["headers_base64_pairs"]:
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or any(not isinstance(part, str) for part in pair)
                    ):
                        raise ValueError("WebSocket accept headers must be base64 string pairs")
                    _decode_b64(pair[0], "WebSocket accept header name")
                    _decode_b64(pair[1], "WebSocket accept header value")
                close = _strict_object(
                    action["close"],
                    {"code", "reason"},
                    "SessionMiddleware WebSocket close action",
                )
                if (
                    type(close["code"]) is not int
                    or not 1000 <= close["code"] <= 4999
                    or not isinstance(close["reason"], str)
                ):
                    raise ValueError("WebSocket close requires an integer code and string reason")
                if scope["asgi"].get("spec_version") != "2.5":
                    raise ValueError("SessionMiddleware WebSocket action requires ASGI spec 2.5")
                offered_subprotocols = scope["subprotocols"]
                if request_spec["receive"] != [
                    {"type": "websocket.connect", "subprotocols": offered_subprotocols}
                ]:
                    raise ValueError(
                        "SessionMiddleware WebSocket action requires its offered connect input"
                    )
            elif action["kind"] == "passthrough":
                _strict_object(action, {"kind", "outbound"}, "SessionMiddleware passthrough action")
                if not isinstance(action["outbound"], list):
                    raise ValueError("SessionMiddleware passthrough outbound must be an array")
                for outbound in action["outbound"]:
                    outbound = _strict_object(
                        outbound,
                        {"type"},
                        "SessionMiddleware passthrough output event",
                    )
                    if not isinstance(outbound["type"], str):
                        raise ValueError(
                            "SessionMiddleware passthrough output type must be a string"
                        )
                if request_spec["cookie_source"] is not None:
                    raise ValueError("SessionMiddleware lifespan passthrough has no cookie source")
                if request_spec["receive"] != [
                    {"type": "lifespan.startup"},
                    {"type": "lifespan.shutdown"},
                ]:
                    raise ValueError("SessionMiddleware passthrough requires startup then shutdown")
                if action["outbound"] != [
                    {"type": "lifespan.startup.complete"},
                    {"type": "lifespan.shutdown.complete"},
                ]:
                    raise ValueError(
                        "SessionMiddleware passthrough requires matching lifecycle completions"
                    )
            else:
                raise ValueError(f"unsupported SessionMiddleware action: {action['kind']!r}")

            expected_scope_type = {
                "view": "http",
                "update": "http",
                "clear": "http",
                "no-access": "http",
                "session-mutation": "http",
                "websocket-view": "websocket",
                "passthrough": "lifespan",
            }[action["kind"]]
            if scope["type"] != expected_scope_type:
                raise ValueError(
                    f"SessionMiddleware {action['kind']} requires a {expected_scope_type} scope"
                )
            if action["kind"] == "websocket-view":
                if (
                    not isinstance(cookie_source, dict)
                    or cookie_source.get("kind") != "previous-set-cookie"
                ):
                    raise ValueError(
                        "SessionMiddleware WebSocket view requires a previous session cookie"
                    )
                previous_action = actions_by_id[cookie_source["request_id"]]
                if previous_action["kind"] != "update" or not previous_action["values"]:
                    raise ValueError(
                        "WebSocket session cookie must follow a non-empty session update"
                    )

            incoming = [_message(message) for message in request_spec["receive"]]
            sent: list[dict[str, Any]] = []
            receive_state = {"index": 0}
            current.clear()
            current.update(
                {
                    "action": action,
                    "session": None,
                    "accessed": None,
                    "modified": None,
                    "mutation_result": None,
                }
            )

            async def receive(
                _incoming: list[dict[str, Any]] = incoming,
                _state: dict[str, int] = receive_state,
            ) -> dict[str, Any]:
                received = _state["index"]
                if received < len(_incoming):
                    message = _incoming[received]
                    _state["index"] = received + 1
                    return message
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any], _sent: list[dict[str, Any]] = sent) -> None:
                _sent.append(message)

            await middleware(scope, receive, send)
            events = [_canonical_message(message) for message in sent]
            start = next(
                (message for message in sent if message["type"] == "http.response.start"),
                None,
            )
            body = b"".join(
                message.get("body", b"")
                for message in sent
                if message["type"] == "http.response.body"
            )
            set_cookie = next(
                (
                    value.decode("latin-1").partition(";")[0]
                    for message in sent
                    if message["type"] == "http.response.start"
                    for name, value in message["headers"]
                    if name.lower() == b"set-cookie"
                ),
                None,
            )
            prior_set_cookies[request_id] = set_cookie
            headers = (
                [
                    [
                        base64.b64encode(name).decode("ascii"),
                        base64.b64encode(value).decode("ascii"),
                    ]
                    for name, value in start["headers"]
                ]
                if start is not None
                else []
            )
            outputs.append(
                {
                    "request_id": request_id,
                    "action": action["kind"],
                    "session": current["session"],
                    "accessed": current["accessed"],
                    "modified": current["modified"],
                    "mutation_result": current["mutation_result"],
                    "response_status": start["status"] if start is not None else None,
                    "response_headers": headers,
                    "response_bytes": {
                        "encoding": "base64",
                        "data": base64.b64encode(body).decode("ascii"),
                    },
                    "asgi_event_order": [message["type"] for message in events],
                    "asgi_events": events,
                }
            )
            actions_by_id[request_id] = action
        return outputs

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": SESSION_WORKFLOW_OPERATION,
                "status": "ok",
                "value": {
                    "secret_key_observation": secret_key_observation,
                    "requests": asyncio.run(run_requests()),
                },
            }
        ],
    }


def _materialize_body_limit_script(spec: dict[str, Any], trace: list[dict[str, Any]]) -> Any:
    from starlette.middleware.body_limit import (
        _BODY_LIMIT_RESPONDER_SCOPE_KEY,
        MAX_BODY_SIZE_SCOPE_KEY,
        RequestBodyLimitMiddleware,
    )

    app_spec = _strict_object(spec, {"kind", "actions"}, "body-limit script app")
    if app_spec["kind"] != "asgi-body-limit-script" or not isinstance(app_spec["actions"], list):
        raise ValueError("body-limit app must be an input-defined ASGI action script")
    actions = app_spec["actions"]

    async def script(scope: Any, receive: Any, send: Any) -> None:
        for index, action in enumerate(actions):
            if not isinstance(action, dict) or not isinstance(action.get("action"), str):
                raise ValueError(f"body-limit action[{index}] must declare an action")
            kind = action["action"]
            if kind == "receive":
                _strict_object(action, {"action"}, f"body-limit action[{index}]")
                message = await receive()
                trace.append({"event": "receive", "message": _json_safe(message)})
            elif kind == "send":
                _strict_object(action, {"action", "message"}, f"body-limit action[{index}]")
                operation, message = _materialize_asgi_action(
                    {"action": "send", "message": action["message"]}, index
                )
                if operation != "send":
                    raise RuntimeError("body-limit send action did not materialize a send")
                await send(message)
                trace.append({"event": "send", "message": _canonical_message(message)})
            elif kind == "nested":
                _strict_object(
                    action,
                    {"action", "max_body_size", "actions"},
                    f"body-limit action[{index}]",
                )
                nested_app = _materialize_body_limit_script(
                    {"kind": "asgi-body-limit-script", "actions": action["actions"]}, trace
                )
                nested = RequestBodyLimitMiddleware(nested_app, action["max_body_size"])
                await nested(scope, receive, send)
                trace.append({"event": "nested-complete", "max_body_size": action["max_body_size"]})
            elif kind == "observe-scope":
                _strict_object(action, {"action"}, f"body-limit action[{index}]")
                trace.append(
                    {
                        "event": "scope",
                        "type": scope.get("type"),
                        "max_body_size_present": MAX_BODY_SIZE_SCOPE_KEY in scope,
                        "max_body_size": _json_safe(scope.get(MAX_BODY_SIZE_SCOPE_KEY)),
                        "responder_present": _BODY_LIMIT_RESPONDER_SCOPE_KEY in scope,
                    }
                )
            elif kind in {"raise-http-exception", "raise-runtime-error"}:
                operation, exception = _materialize_asgi_action(action, index)
                if operation != "raise":
                    raise RuntimeError("body-limit exception action did not materialize an error")
                raise exception
            else:
                raise ValueError(f"unsupported body-limit action: {kind!r}")

    return script


def _run_body_limit_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.middleware.body_limit import (
        _BODY_LIMIT_RESPONDER_SCOPE_KEY,
        MAX_BODY_SIZE_SCOPE_KEY,
        RequestBodyLimitMiddleware,
    )

    steps = case["steps"]
    if (
        len(steps) != 2
        or [step.get("step_id") for step in steps] != ["middleware", "dispatch"]
        or [step.get("operation") for step in steps] != ["__init__", "__call__"]
        or any(step.get("surface") != case["surface"] for step in steps)
        or steps[0].get("receiver") is not None
        or steps[1].get("receiver") != {"kind": "binding", "step_id": "middleware"}
    ):
        raise ValueError("RequestBodyLimitMiddleware cases must construct then dispatch")
    if case["execution_schedule"] != ["dispatch"] or case["observations"] != ["dispatch"]:
        raise ValueError("RequestBodyLimitMiddleware cases must observe one dispatch")
    constructor_arguments = _literal_arguments(
        steps[0], {"app", "max_body_size"}, "RequestBodyLimitMiddleware constructor"
    )
    dispatch_arguments = _literal_arguments(
        steps[1], {"scope", "receive", "send"}, "RequestBodyLimitMiddleware dispatch"
    )
    trace: list[dict[str, Any]] = []
    app = _materialize_body_limit_script(constructor_arguments["app"], trace)
    middleware = RequestBodyLimitMiddleware(app, constructor_arguments["max_body_size"])

    scope_spec = dict(dispatch_arguments["scope"])
    prior_scope_limit = scope_spec.pop("preexisting_max_body_size", _MISSING)
    scope = _make_scope(scope_spec)
    if prior_scope_limit is not _MISSING:
        scope[MAX_BODY_SIZE_SCOPE_KEY] = prior_scope_limit
    incoming = [_message(message) for message in dispatch_arguments["receive"]]
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

    async def dispatch() -> dict[str, Any] | None:
        try:
            await middleware(scope, receive, send)
        except Exception as exc:
            return _dispatch_error(exc)
        return None

    captured_error = asyncio.run(dispatch())

    events = [_canonical_message(message) for message in sent]
    response_start = next(
        (event for event in events if event["type"] == "http.response.start"), None
    )
    body = b"".join(
        base64.b64decode(event["body"]["data"])
        for event in events
        if event["type"] == "http.response.body"
    )
    value = {
        "response_status": response_start["status"] if response_start is not None else None,
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "received_message_count": received,
        "script_trace": trace,
        "scope_after": {
            "max_body_size_present": MAX_BODY_SIZE_SCOPE_KEY in scope,
            "max_body_size": _json_safe(scope.get(MAX_BODY_SIZE_SCOPE_KEY)),
            "responder_present": _BODY_LIMIT_RESPONDER_SCOPE_KEY in scope,
        },
        "dispatch_error": captured_error,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": {"dispatch": value}}],
    }


def _make_websocket_scope(spec: dict[str, Any]) -> dict[str, Any]:
    scope = {
        "type": "websocket",
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": _decode_b64(spec["raw_path_base64"], "WebSocket scope.raw_path_base64"),
        "query_string": _decode_b64(
            spec["query_string_base64"], "WebSocket scope.query_string_base64"
        ),
        "root_path": spec["root_path"],
        "headers": [
            (
                _decode_b64(name, "WebSocket scope header name"),
                _decode_b64(value, "WebSocket scope header value"),
            )
            for name, value in spec["headers_base64_pairs"]
        ],
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
        "subprotocols": list(spec["subprotocols"]),
    }
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    return scope


def _materialize_websocket_message(spec: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {}
    for name, value in spec.items():
        if name == "bytes_base64":
            message["bytes"] = _decode_b64(value, "WebSocket message.bytes_base64")
        elif name == "body_base64":
            message["body"] = _decode_b64(value, "WebSocket message.body_base64")
        elif name == "headers_base64_pairs":
            message["headers"] = [
                (
                    _decode_b64(pair[0], "WebSocket message header name"),
                    _decode_b64(pair[1], "WebSocket message header value"),
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


def _websocket_state_name(state: Any) -> str:
    name = getattr(state, "name", None)
    if isinstance(name, str):
        return name
    raise ValueError("WebSocket state does not expose its public enum name")


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


def _run_websocket_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
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
    _strict_object(
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


def _run_websocket_convenience_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
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
        "WebSocket convenience-sequence case",
    )
    if case["surface"] != WEBSOCKET_SURFACE or case["operation"] != WEBSOCKET_CONVENIENCE_OPERATION:
        raise ValueError(
            "WebSocket workflow is outside the declared convenience-sequence operation"
        )
    import builtins

    from starlette.responses import Response
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

    async def run_actions() -> list[dict[str, Any]]:
        nonlocal pending_send_error
        results: list[dict[str, Any]] = []
        for action in case["actions"]:
            action_id = action["action_id"]
            method = action["method"]
            arguments = action["arguments"]
            pending_send_error = action.get("send_error")
            try:
                if method == "accept":
                    kwargs: dict[str, Any] = {}
                    if "subprotocol" in arguments:
                        kwargs["subprotocol"] = arguments["subprotocol"]
                    if "headers_base64_pairs" in arguments:
                        header_pairs = arguments["headers_base64_pairs"]
                        kwargs["headers"] = (
                            None
                            if header_pairs is None
                            else [
                                (
                                    _decode_b64(pair[0], "WebSocket accept header name"),
                                    _decode_b64(pair[1], "WebSocket accept header value"),
                                )
                                for pair in header_pairs
                            ]
                        )
                    value = await websocket.accept(**kwargs)
                elif method in {"receive_text", "receive_bytes"}:
                    value = await getattr(websocket, method)()
                elif method == "receive_json":
                    kwargs = {"mode": arguments["mode"]} if "mode" in arguments else {}
                    value = await websocket.receive_json(**kwargs)
                elif method in {"send_text", "send_json", "close"}:
                    kwargs = dict(arguments)
                    value = await getattr(websocket, method)(**kwargs)
                elif method == "send_bytes":
                    value = await websocket.send_bytes(
                        _decode_b64(arguments["data_base64"], "WebSocket send_bytes.data")
                    )
                elif method == "iter_text" or method == "iter_bytes" or method == "iter_json":
                    iterator = getattr(websocket, method)()
                    values = []
                    async for item in iterator:
                        values.append(item)
                    value = values
                elif method == "iterator-probe":
                    iterator = getattr(websocket, arguments["iterator"])()
                    value = {
                        attribute: hasattr(iterator, attribute)
                        for attribute in arguments["attributes"]
                    }
                elif method == "iterator-control":
                    iterator = getattr(websocket, arguments["iterator"])()
                    control = arguments["control"]
                    if control == "asend":
                        value = await iterator.asend(arguments["value"])
                    elif control == "athrow":
                        exception_class = getattr(builtins, arguments["exception"]["class"])
                        exception = exception_class(arguments["exception"]["message"])
                        value = await iterator.athrow(exception)
                    else:
                        value = await iterator.aclose()
                elif method == "send_denial_response":
                    response_spec = arguments["response"]
                    header_pairs = response_spec["headers_base64_pairs"]
                    response_headers = {
                        _decode_b64(pair[0], "WebSocket denial response header name").decode(
                            "latin-1"
                        ): _decode_b64(pair[1], "WebSocket denial response header value").decode(
                            "latin-1"
                        )
                        for pair in header_pairs
                    }
                    response = Response(
                        content=_decode_b64(
                            response_spec["content_base64"], "WebSocket denial response content"
                        ),
                        status_code=response_spec["status_code"],
                        headers=response_headers,
                    )
                    value = await websocket.send_denial_response(response)
                else:
                    raise ValueError(f"unsupported WebSocket convenience action: {method!r}")
            except Exception as exc:
                results.append(
                    {
                        "action_id": action_id,
                        "method": method,
                        "outcome": "error",
                        "error": _websocket_action_error(exc),
                    }
                )
            else:
                results.append(
                    {
                        "action_id": action_id,
                        "method": method,
                        "outcome": "ok",
                        "value": _json_safe(value),
                    }
                )
            finally:
                pending_send_error = None
        return results

    action_results = asyncio.run(run_actions())
    available = {
        "action_results": action_results,
        "asgi_callback_tape": callback_tape,
        "client_state": _websocket_state_name(websocket.client_state),
        "application_state": _websocket_state_name(websocket.application_state),
    }
    if case["observations"] != [WEBSOCKET_CONVENIENCE_OPERATION]:
        raise ValueError(
            "WebSocket observations must select the convenience-sequence workflow result"
        )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": WEBSOCKET_CONVENIENCE_OPERATION,
                "status": "ok",
                "value": available,
            }
        ],
    }


def _run_websocket_close_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "close_app",
            "observations",
        },
        "WebSocketClose call-sequence case",
    )
    if case["surface"] != WEBSOCKET_CLOSE_SURFACE or case["operation"] != WEBSOCKET_CLOSE_OPERATION:
        raise ValueError("workflow is outside the declared WebSocketClose call-sequence operation")
    from starlette.websockets import WebSocketClose

    callback_tape: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        raise ValueError("WebSocketClose input provides no receive messages")

    async def send(message: dict[str, Any]) -> None:
        callback_tape.append(
            {"direction": "send", "message": _canonical_websocket_message(message)}
        )

    spec = case["close_app"]
    close_app = WebSocketClose(**spec["arguments"])
    initial_attributes = {
        "code": _json_safe(close_app.code),
        "reason": _json_safe(close_app.reason),
    }
    for name, value in spec["setters"].items():
        setattr(close_app, name, value)
    final_attributes = {"code": _json_safe(close_app.code), "reason": _json_safe(close_app.reason)}
    try:
        asyncio.run(close_app(_make_websocket_scope(case["scope"]), receive, send))
        call = {"outcome": "ok"}
    except Exception as exc:
        call = {"outcome": "error", "error": _websocket_action_error(exc)}
    available = {
        "initial_attributes": initial_attributes,
        "final_attributes": final_attributes,
        "asgi_callback_tape": callback_tape,
        "call": call,
    }
    if case["observations"] != [WEBSOCKET_CLOSE_OPERATION]:
        raise ValueError("WebSocketClose observations must select the call-sequence result")
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": WEBSOCKET_CLOSE_OPERATION, "status": "ok", "value": available}
        ],
    }


def _canonical_websocket_route_event(message: dict[str, Any]) -> dict[str, Any]:
    if message["type"].startswith("websocket."):
        return _canonical_websocket_message(message)
    return _canonical_message(message)


def _run_websocket_route_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
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


def _route_path_params(scope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": _json_safe(value), "type": type(value).__name__}
        for name, value in scope.get("path_params", {}).items()
    }


def _run_route_dispatch_case(case: dict[str, Any]) -> dict[str, Any]:
    surface = case.get("surface")
    is_router = surface == ROUTER_SURFACE
    is_mount = surface == MOUNT_SURFACE
    if not (is_router or is_mount) or case.get("operation") != "route-dispatch":
        raise ValueError(
            "workflow is outside the declared Router or Mount route-dispatch operation"
        )

    common_keys = {"case_id", "surface", "operation", "covers", "target_profiles", "assets"}
    if is_router:
        _strict_object(
            case,
            common_keys
            | {
                "custom_convertors",
                "redirect_slashes",
                "routes",
                "scope",
                "incoming",
                "send",
                "observations",
            },
            "Router route-dispatch case",
        )
        if case["observations"] != [ROUTER_OPERATION]:
            raise ValueError("Router observations must select route-dispatch")
        routes_spec = case["routes"]
        custom_convertors = case["custom_convertors"]
    else:
        _strict_object(
            case,
            common_keys | {"mount", "scope", "incoming", "send", "observations"},
            "Mount route-dispatch case",
        )
        if case["observations"] != [MOUNT_OPERATION]:
            raise ValueError("Mount observations must select route-dispatch")
        routes_spec = case["mount"]["routes"]
        custom_convertors = []

    if not isinstance(routes_spec, list) or not routes_spec:
        raise ValueError("route-dispatch requires a non-empty route list")
    if not isinstance(custom_convertors, list):
        raise ValueError("custom_convertors must be an array")
    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    from starlette.convertors import CONVERTOR_TYPES, Convertor, register_url_convertor
    from starlette.responses import PlainTextResponse
    from starlette.routing import Host, Mount, Route, Router

    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], _MISSING) for spec in custom_convertors
    }
    route_index_observations: list[int] = []

    def make_endpoint(endpoint_spec: dict[str, Any], route_index: int) -> Any:
        async def endpoint(request: Any) -> Any:
            if is_router:
                route_index_observations.append(route_index)
            kind = endpoint_spec.get("kind")
            if kind == "plain-text-response":
                _strict_object(
                    endpoint_spec,
                    {"kind", "content", "status_code", "media_type", "cookies"},
                    "plain-text route response",
                )
                content = endpoint_spec["content"]
                status_code = endpoint_spec["status_code"]
                media_type = endpoint_spec["media_type"]
                cookies = endpoint_spec["cookies"]
            elif kind == "converted-path-response":
                _strict_object(
                    endpoint_spec,
                    {"kind", "path_parameter", "status_code", "media_type"},
                    "converted-path route response",
                )
                content = str(request.path_params[endpoint_spec["path_parameter"]])
                status_code = endpoint_spec["status_code"]
                media_type = endpoint_spec["media_type"]
                cookies = []
            else:
                raise ValueError(f"unsupported route response kind: {kind!r}")
            response = PlainTextResponse(
                content=content,
                status_code=status_code,
                media_type=media_type,
            )
            for cookie in cookies:
                _strict_object(cookie, {"key", "value"}, "route response cookie")
                response.set_cookie(key=cookie["key"], value=cookie["value"])
            return response

        return endpoint

    def make_host_app(app_spec: dict[str, Any], route_index: int) -> Any:
        async def host_app(scope: Any, receive: Any, send: Any) -> None:
            route_index_observations.append(route_index)
            response = PlainTextResponse(
                content=app_spec["content"],
                status_code=app_spec["status_code"],
                media_type=app_spec["media_type"],
            )
            await response(scope, receive, send)

        return host_app

    def make_mount_child(route_spec: dict[str, Any]) -> Any:
        kind = route_spec.get("kind") if isinstance(route_spec, dict) else None
        if kind == "mount":
            _strict_object(route_spec, {"kind", "path", "routes"}, "Nested Mount input")
            nested_routes = route_spec["routes"]
            if not isinstance(nested_routes, list) or not nested_routes:
                raise ValueError("Nested Mount routes must be a non-empty array")
            return Mount(
                route_spec["path"],
                routes=[make_mount_child(child) for child in nested_routes],
            )
        if (
            not isinstance(route_spec, dict)
            or set(route_spec) != {"kind", "path", "methods", "endpoint"}
            or kind != "http-route"
        ):
            raise ValueError("Mount child input must be a declared http-route or mount record")
        return Route(
            route_spec["path"],
            make_endpoint(route_spec["endpoint"], 0),
            methods=route_spec["methods"],
        )

    async def run() -> tuple[dict[str, Any], dict[str, Any] | None]:
        if is_mount:
            route_objects = [make_mount_child(route) for route in routes_spec]
        else:
            route_objects = []
            for route_index, route_spec in enumerate(routes_spec):
                if isinstance(route_spec, dict) and route_spec.get("kind") == "host-route":
                    if set(route_spec) != {"kind", "host", "name", "app"}:
                        raise ValueError(
                            "Host route input must be a declared Router host-route record"
                        )
                    app_spec = _strict_object(
                        route_spec["app"],
                        {"kind", "content", "status_code", "media_type", "cookies"},
                        "Host route app response",
                    )
                    if app_spec["kind"] != "plain-text-response" or app_spec["cookies"]:
                        raise ValueError(
                            "Host route app must use a plain-text response without cookies"
                        )
                    route_objects.append(
                        Host(
                            route_spec["host"],
                            make_host_app(app_spec, route_index),
                            name=route_spec["name"],
                        )
                    )
                    continue
                if (
                    not isinstance(route_spec, dict)
                    or set(route_spec) != {"kind", "path", "methods", "endpoint"}
                    or route_spec["kind"] != "http-route"
                ):
                    raise ValueError("route input must be a declared http-route record")
                route_objects.append(
                    Route(
                        route_spec["path"],
                        make_endpoint(route_spec["endpoint"], route_index),
                        methods=route_spec["methods"],
                    )
                )

        if is_router:
            application = Router(
                routes=route_objects,
                redirect_slashes=case["redirect_slashes"],
            )
        else:
            mount_spec = case["mount"]
            _strict_object(mount_spec, {"path", "routes"}, "Mount input")
            application = Mount(mount_spec["path"], routes=route_objects)

        scope = _make_scope(case["scope"])
        incoming = [_message(item) for item in case["incoming"]]
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

        await application(scope, receive, send)
        if incoming_index != len(incoming):
            raise ValueError("route-dispatch left incoming messages unconsumed")

        events = [_canonical_message(message) for message in sent]
        response_start = next(
            (message for message in sent if message["type"] == "http.response.start"), None
        )
        response_body = b"".join(
            message.get("body", b"") for message in sent if message["type"] == "http.response.body"
        )
        start_event = next(
            (event for event in events if event["type"] == "http.response.start"), None
        )
        selected = {
            "response_status": response_start["status"] if response_start is not None else None,
            "ordered_repeated_headers": start_event["headers"] if start_event is not None else [],
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
        mount_scope = None
        if is_mount and "app_root_path" in scope:
            mount_scope = {
                "root_path": scope.get("root_path", ""),
                "app_root_path": scope.get("app_root_path"),
                "path_params": _route_path_params(scope),
            }
        return selected, mount_scope

    try:
        for spec in custom_convertors:
            if not isinstance(spec, dict) or set(spec) != {"name", "regex", "lowercase"}:
                raise ValueError("custom converter input must contain name, regex, and lowercase")

            class InputConvertor(Convertor[str]):
                def __init__(self, regex: str, lowercase: bool) -> None:
                    self.regex = regex
                    self.lowercase = lowercase

                def convert(self, value: str) -> str:
                    return value.lower() if self.lowercase else value

                def to_string(self, value: str) -> str:
                    return str(value)

            register_url_convertor(spec["name"], InputConvertor(spec["regex"], spec["lowercase"]))

        selected, mount_scope = asyncio.run(run())
    finally:
        for name, old_convertor in previous_convertors.items():
            if old_convertor is _MISSING:
                CONVERTOR_TYPES.pop(name, None)
            else:
                CONVERTOR_TYPES[name] = old_convertor

    observation_value = selected
    if is_mount:
        observation_value = {**selected, "mount_scope": mount_scope}
    else:
        if len(route_index_observations) > 1:
            raise RuntimeError("Router dispatched more than one route endpoint")
        observation_value = {
            **selected,
            "route_index": route_index_observations[0] if route_index_observations else None,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": ROUTER_OPERATION if is_router else MOUNT_OPERATION,
                "status": "ok",
                "value": observation_value,
            }
        ],
    }


def _run_redirect_response_case(case: dict[str, Any]) -> dict[str, Any]:
    case_keys = {
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
    }
    if "cookie_actions" in case:
        case_keys.add("cookie_actions")
    _strict_object(
        case,
        case_keys,
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
    for index, raw_action in enumerate(case.get("cookie_actions", [])):
        _apply_response_cookie_action(response, raw_action, index)
    scope = _make_scope(case["scope"])
    incoming = [_message(item) for item in case["incoming"]]
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


def _run_file_response_case(case: dict[str, Any]) -> dict[str, Any]:
    case_keys = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "file",
        "status_code",
        "header_pairs",
        "media_type",
        "filename",
        "scope",
        "incoming",
        "send",
        "observations",
    }
    if "cookie_actions" in case:
        case_keys.add("cookie_actions")
    if "chunk_size" in case:
        case_keys.add("chunk_size")
    if "max_ranges" in case:
        case_keys.add("max_ranges")
    _strict_object(
        case,
        case_keys,
        "FileResponse asgi-call case",
    )
    if case["surface"] != FILE_RESPONSE_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared FileResponse asgi-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("FileResponse observations must select asgi-call")

    file_spec = _strict_object(
        case["file"], {"name", "contents_base64", "mtime_seconds"}, "FileResponse file"
    )
    name = file_spec["name"]
    encoded_contents = file_spec["contents_base64"]
    mtime_seconds = file_spec["mtime_seconds"]
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
    ):
        raise ValueError("FileResponse file.name must be a basename")
    if not isinstance(encoded_contents, str):
        raise ValueError("FileResponse file.contents_base64 must be a string")
    if type(mtime_seconds) not in {int, float} or not math.isfinite(mtime_seconds):
        raise ValueError("FileResponse file.mtime_seconds must be a finite number")
    contents = _decode_b64(encoded_contents, "file.contents_base64")

    if type(case["status_code"]) is not int:
        raise ValueError("FileResponse status_code must be an integer")
    header_pairs = case["header_pairs"]
    if not isinstance(header_pairs, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(part, str) for part in pair)
        for pair in header_pairs
    ):
        raise ValueError("FileResponse header_pairs must be string pairs")
    media_type = case["media_type"]
    filename = case["filename"]
    if media_type is not None and not isinstance(media_type, str):
        raise ValueError("FileResponse media_type must be a string or null")
    if filename is not None and not isinstance(filename, str):
        raise ValueError("FileResponse filename must be a string or null")

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
    _strict_object(scope_spec, scope_keys, "FileResponse HTTP scope")
    if scope_spec["type"] != "http":
        raise ValueError("FileResponse ASGI-call requires an HTTP scope")
    if "extensions" in scope_spec:
        extensions = scope_spec["extensions"]
        if not isinstance(extensions, dict) or any(
            key != "http.response.pathsend" for key in extensions
        ):
            raise ValueError("FileResponse scope.extensions may only declare pathsend")
    if not isinstance(case["incoming"], list) or case["incoming"]:
        raise ValueError("FileResponse ASGI-call requires an empty incoming stream")
    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    from starlette.responses import FileResponse

    with tempfile.TemporaryDirectory(prefix="starlette-file-response-") as directory:
        path = Path(directory) / name
        path.write_bytes(contents)
        stat_result = os.stat_result(
            (
                stat.S_IFREG | 0o644,
                0,
                0,
                1,
                0,
                0,
                len(contents),
                mtime_seconds,
                mtime_seconds,
                mtime_seconds,
            )
        )
        response_class = (
            type("ConfiguredFileResponse", (FileResponse,), {"max_ranges": case["max_ranges"]})
            if "max_ranges" in case
            else FileResponse
        )
        response = response_class(
            path,
            status_code=case["status_code"],
            headers=dict(header_pairs),
            media_type=media_type,
            filename=filename,
            stat_result=stat_result,
        )
        if "chunk_size" in case:
            response.chunk_size = case["chunk_size"]
        for index, raw_action in enumerate(case.get("cookie_actions", [])):
            _apply_response_cookie_action(response, raw_action, index)
        scope = _make_scope(scope_spec)
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

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
        "observations": [{"step_id": RESPONSE_OPERATION, "status": "ok", "value": observation}],
    }


def _static_files_path_limit_candidate(
    root: Path, relative_path: str, follow_symlink: bool
) -> Path:
    joined_path = os.path.join(os.fspath(root), relative_path)
    full_path = os.path.abspath(joined_path) if follow_symlink else os.path.realpath(joined_path)
    return Path(full_path)


def _static_files_path_limit_components_fit(path: Path, component_limit: int) -> bool:
    return all(
        len(os.fsencode(component)) <= component_limit
        for component in path.parts
        if component not in {path.anchor, "", "."}
    )


def _static_files_path_limit_padding(padding_bytes: int, component_limit: int) -> list[str] | None:
    components: list[str] = []
    remaining = padding_bytes
    while remaining > component_limit + 1:
        component_bytes = component_limit + 1
        if remaining - component_bytes == 1:
            component_bytes -= 1
        component_length = component_bytes - 1
        if component_length < 1:
            return None
        components.append("p" * component_length)
        remaining -= component_bytes
    if remaining == 1:
        return None
    if remaining > 0:
        component_length = remaining - 1
        if component_length > component_limit:
            return None
        components.append("p" * component_length)
    return components


def _static_files_path_limit_skipped(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "skipped",
        "observations": [{"step_id": RESPONSE_OPERATION, "status": "skipped", "reason": reason}],
    }


def _static_files_permission_denial_skipped(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "skipped",
        "observations": [{"step_id": RESPONSE_OPERATION, "status": "skipped", "reason": reason}],
    }


def _static_files_permission_denial_mode(
    case: dict[str, Any], root: Path
) -> tuple[int | None, str | None]:
    recipe = case["permission_denial_stress"]
    if recipe is None:
        return None, None
    if os.name != "posix":
        return None, "permission-denial fixture requires POSIX directory permissions"

    original_mode = root.stat().st_mode & 0o7777
    try:
        root.chmod(recipe["mode"])
    except OSError as exc:
        return None, f"the temporary filesystem cannot apply the declared directory mode: {exc}"
    try:
        (root / case["scope"]["path"].lstrip("/")).stat()
    except PermissionError:
        return original_mode, None
    except OSError:
        root.chmod(original_mode)
        raise
    root.chmod(original_mode)
    return None, "the current process can still traverse the permission-restricted root"


def _static_files_path_limit_root(
    case: dict[str, Any], workspace: Path, root: Path, package_source_root: Path
) -> tuple[Path | None, str | None]:
    if not hasattr(os, "pathconf"):
        return None, "the temporary workspace does not support os.pathconf"
    try:
        path_limit = os.pathconf(workspace, "PC_PATH_MAX")
        name_limit = os.pathconf(workspace, "PC_NAME_MAX")
    except (OSError, ValueError, AttributeError):
        return None, "the temporary workspace does not expose PC_PATH_MAX and PC_NAME_MAX"
    if path_limit <= 0 or name_limit <= 0:
        return None, "the temporary workspace has no positive PC_PATH_MAX or PC_NAME_MAX limit"

    recipe = case["path_limit_stress"]
    component_limit = min(recipe["safe_component_bytes"], name_limit)
    relative_path = case["scope"]["path"].lstrip("/")
    if (
        component_limit < 1
        or not relative_path
        or os.path.normpath(relative_path) != relative_path
        or any(
            len(os.fsencode(component)) > component_limit
            for component in relative_path.split(os.sep)
        )
    ):
        return None, "the request path cannot fit the declared safe component limit"

    package = case["packages"][0]
    package_root = package_source_root.joinpath(*package["name"].split("."))
    package_static_root = package_root.joinpath(*package["statics_dir"].split("/"))
    later_candidate = _static_files_path_limit_candidate(
        package_static_root, relative_path, case["follow_symlink"]
    )
    if not _static_files_path_limit_components_fit(later_candidate, component_limit):
        return None, "a later package path component exceeds the declared safe component limit"
    if len(os.fsencode(os.fspath(later_candidate))) > (
        path_limit - recipe["later_root_margin_bytes"]
    ):
        return None, "the later package candidate cannot fit below the declared path-limit margin"

    first_candidate = _static_files_path_limit_candidate(
        root, relative_path, case["follow_symlink"]
    )
    if not _static_files_path_limit_components_fit(first_candidate, component_limit):
        return None, "the configured first-root path exceeds the declared safe component limit"
    target_length = path_limit + recipe["overflow_bytes"]
    padding_bytes = target_length - len(os.fsencode(os.fspath(first_candidate)))
    if padding_bytes < 0:
        return None, "the unpadded first-root candidate already exceeds the overflow target"
    padding_components = _static_files_path_limit_padding(padding_bytes, component_limit)
    if padding_components is None:
        return None, "the first-root overflow cannot be represented with safe path components"

    padded_root = root.joinpath(*padding_components)
    padded_candidate = _static_files_path_limit_candidate(
        padded_root, relative_path, case["follow_symlink"]
    )
    if len(os.fsencode(os.fspath(padded_candidate))) != target_length:
        return None, "the padded first-root candidate cannot match the declared overflow geometry"
    if not _static_files_path_limit_components_fit(padded_candidate, component_limit):
        return None, "the padded first-root candidate exceeds the declared safe component limit"
    root_candidate = Path(
        os.path.abspath(padded_root) if case["follow_symlink"] else os.path.realpath(padded_root)
    )
    if len(os.fsencode(os.fspath(root_candidate))) > path_limit:
        return None, "the padded first root itself exceeds PC_PATH_MAX"
    try:
        padded_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if exc.errno == errno.ENAMETOOLONG:
            return None, "the padded first root cannot be created within the workspace path limit"
        raise
    return padded_root, None


def _run_static_files_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "directory",
            "path_limit_stress",
            "permission_denial_stress",
            "packages",
            "files",
            "html",
            "check_dir",
            "follow_symlink",
            "scope",
            "incoming",
            "send",
            "observations",
        },
        "StaticFiles asgi-call case",
    )
    if case["surface"] != STATIC_FILES_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared StaticFiles asgi-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("StaticFiles observations must select asgi-call")

    from starlette.exceptions import HTTPException
    from starlette.staticfiles import StaticFiles

    temporary_prefix = (
        "starlette-static-path-limit-"
        if case["path_limit_stress"] is not None
        else "starlette-static-files-"
    )
    with tempfile.TemporaryDirectory(prefix=temporary_prefix) as temporary_directory:
        workspace = Path(temporary_directory)
        root = workspace / case["directory"]
        package_source_root = workspace / "package-source"
        package_source_root.mkdir()
        if case["path_limit_stress"] is not None:
            root, skip_reason = _static_files_path_limit_root(
                case, workspace, root, package_source_root
            )
            if skip_reason is not None:
                return _static_files_path_limit_skipped(case, skip_reason)
        else:
            root.mkdir(parents=True)
        for file_spec in case["files"]:
            path = root / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_decode_b64(file_spec["contents_base64"], "file.contents_base64"))
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        package_arguments = []
        for package in case["packages"]:
            package_path = package_source_root
            for component in package["name"].split("."):
                package_path = package_path / component
                package_path.mkdir(exist_ok=True)
                (package_path / "__init__.py").touch()
            static_root = package_path.joinpath(*package["statics_dir"].split("/"))
            static_root.mkdir(parents=True, exist_ok=True)
            for file_spec in package["files"]:
                path = static_root / file_spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    _decode_b64(file_spec["contents_base64"], "package file.contents_base64")
                )
                os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
            package_arguments.append(
                package["name"]
                if package["statics_dir"] == "statics"
                else (package["name"], package["statics_dir"])
            )
        sys.path.insert(0, str(package_source_root))
        try:
            application = StaticFiles(
                directory=root,
                packages=package_arguments,
                html=case["html"],
                check_dir=case["check_dir"],
                follow_symlink=case["follow_symlink"],
            )
            scope = _make_scope(case["scope"])
            sent: list[dict[str, Any]] = []

            async def receive() -> dict[str, Any]:
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                sent.append(message)

            captured_error: Exception | None = None
            permission_original_mode, permission_skip_reason = _static_files_permission_denial_mode(
                case, root
            )
            if permission_skip_reason is not None:
                return _static_files_permission_denial_skipped(case, permission_skip_reason)
            try:
                asyncio.run(application(scope, receive, send))
            except Exception as exc:
                if not isinstance(exc, HTTPException):
                    raise
                captured_error = exc
            finally:
                if permission_original_mode is not None:
                    root.chmod(permission_original_mode)
        finally:
            sys.path.remove(str(package_source_root))
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
            "response_bytes": {
                "encoding": "base64",
                "data": base64.b64encode(response_body).decode("ascii"),
            },
            "asgi_event_order": [event["type"] for event in events],
            "asgi_events": events,
        }
    observation_item = {
        "step_id": RESPONSE_OPERATION,
        "status": "ok",
        "value": observation,
    }
    if captured_error is not None:
        error = _dispatch_error(captured_error)
        error["code"] = captured_error.status_code
        observation_item = {
            "step_id": RESPONSE_OPERATION,
            "status": "error",
            "error": error,
            "partial_value": observation,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [observation_item],
    }


def _run_static_files_async_boundary_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "directory",
            "packages",
            "files",
            "html",
            "check_dir",
            "follow_symlink",
            "lookup_path_override",
            "event_loop_probe",
            "scope",
            "incoming",
            "send",
            "observations",
        },
        "StaticFiles async-boundary case",
    )
    if (
        case["surface"] != STATIC_FILES_SURFACE
        or case["operation"] != STATIC_FILES_ASYNC_BOUNDARY_OPERATION
        or case["observations"] != [STATIC_FILES_ASYNC_BOUNDARY_OPERATION]
    ):
        raise ValueError("workflow is outside the StaticFiles async-boundary operation")

    from starlette.staticfiles import StaticFiles

    gate_spec = case["lookup_path_override"]["gate"]
    release_timeout_seconds = gate_spec["release_timeout_ms"] / 1000.0
    callback_paths: list[str] = []
    callback_bound_flags: list[bool] = []
    callback_worker_flags: list[bool] = []
    loop_progress_while_blocked: list[bool] = []
    gate_started = threading.Event()
    gate_waiting = threading.Event()
    release_gate = threading.Event()
    loop: asyncio.AbstractEventLoop | None = None
    loop_thread_id = -1
    async_gate_started: asyncio.Event | None = None

    with tempfile.TemporaryDirectory(
        prefix="starlette-static-async-boundary-"
    ) as temporary_directory:
        root = Path(temporary_directory) / case["directory"]
        root.mkdir(parents=True)
        for file_spec in case["files"]:
            path = root / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_decode_b64(file_spec["contents_base64"], "file.contents_base64"))
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))

        class GatedStaticFiles(StaticFiles):
            def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
                callback_paths.append(path)
                callback_bound_flags.append(
                    self is application and application.lookup_path.__self__ is self
                )
                callback_worker_flags.append(threading.get_ident() != loop_thread_id)
                if not gate_started.is_set():
                    gate_started.set()
                    gate_waiting.set()
                    loop.call_soon_threadsafe(async_gate_started.set)
                    released_by_probe = release_gate.wait(release_timeout_seconds)
                    gate_waiting.clear()
                    if not released_by_probe:
                        release_gate.set()
                return super().lookup_path(path)

        application = GatedStaticFiles(
            directory=root,
            packages=case["packages"],
            html=case["html"],
            check_dir=case["check_dir"],
            follow_symlink=case["follow_symlink"],
        )
        scope = _make_scope(case["scope"])
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        async def dispatch() -> None:
            nonlocal loop, loop_thread_id, async_gate_started
            loop = asyncio.get_running_loop()
            loop_thread_id = threading.get_ident()
            async_gate_started = asyncio.Event()

            async def probe_event_loop() -> None:
                await async_gate_started.wait()
                await asyncio.sleep(0)
                loop_progress_while_blocked.append(gate_waiting.is_set())
                if case["event_loop_probe"]["release_gate"]:
                    release_gate.set()

            probe = asyncio.create_task(probe_event_loop())
            try:
                await application(scope, receive, send)
                if gate_started.is_set():
                    await asyncio.wait_for(asyncio.shield(probe), timeout=release_timeout_seconds)
            finally:
                release_gate.set()
                if not probe.done():
                    probe.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await probe

        asyncio.run(dispatch())
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
            "lookup_callback_paths": callback_paths,
            "lookup_callback_bound_to_application": bool(callback_bound_flags)
            and all(callback_bound_flags),
            "lookup_callback_ran_on_worker_thread": bool(callback_worker_flags)
            and all(callback_worker_flags),
            "lookup_gate_started": gate_started.is_set(),
            "event_loop_progress_while_lookup_blocked": any(loop_progress_while_blocked),
            "response_status": response_start["status"] if response_start is not None else None,
            "ordered_repeated_headers": (
                response_start_event["headers"] if response_start_event is not None else []
            ),
            "response_bytes": {
                "encoding": "base64",
                "data": base64.b64encode(response_body).decode("ascii"),
            },
            "asgi_event_order": [event["type"] for event in events],
            "asgi_events": events,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": STATIC_FILES_ASYNC_BOUNDARY_OPERATION,
                "status": "ok",
                "value": observation,
            }
        ],
    }


def _run_static_files_lookup_path_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "directory",
            "files",
            "filesystem",
            "lookup_path",
            "check_dir",
            "follow_symlink",
            "observations",
        },
        "StaticFiles lookup-path case",
    )
    if (
        case["surface"] != STATIC_FILES_SURFACE
        or case["operation"] != STATIC_FILES_LOOKUP_PATH_OPERATION
        or case["observations"] != [STATIC_FILES_LOOKUP_PATH_OPERATION]
    ):
        raise ValueError("workflow is outside the declared StaticFiles lookup-path operation")

    from starlette.staticfiles import StaticFiles

    with tempfile.TemporaryDirectory(prefix="starlette-static-lookup-") as temporary_directory:
        workspace = Path(temporary_directory)
        root = workspace / case["directory"]
        root_symlink_target = case["filesystem"]["root_symlink_target"]
        if root_symlink_target is None:
            root.mkdir(parents=True)
        else:
            target_directory = workspace / root_symlink_target
            target_directory.mkdir(parents=True, exist_ok=True)
            root.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.path.relpath(target_directory, root.parent), root)
        for file_spec in case["files"]:
            path = root / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_decode_b64(file_spec["contents_base64"], "file.contents_base64"))
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        for directory in case["filesystem"]["directories"]:
            (workspace / directory).mkdir(parents=True, exist_ok=True)
        for file_spec in case["filesystem"]["outside_files"]:
            path = workspace / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                _decode_b64(file_spec["contents_base64"], "outside_file.contents_base64")
            )
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        for symlink_spec in case["filesystem"]["symlinks"]:
            path = root / symlink_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(symlink_spec["target"], path)
        application = StaticFiles(
            directory=root,
            check_dir=case["check_dir"],
            follow_symlink=case["follow_symlink"],
        )
        full_path, stat_result = application.lookup_path(case["lookup_path"])
        relative_root = root.absolute() if case["follow_symlink"] else root.resolve()
        resolved_path = Path(full_path).relative_to(relative_root).as_posix() if full_path else None
        mode_type_bits = stat.S_IFMT(stat_result.st_mode) if stat_result is not None else None
        is_file = stat.S_ISREG(stat_result.st_mode) if stat_result is not None else None
        is_directory = stat.S_ISDIR(stat_result.st_mode) if stat_result is not None else None
        observation = {
            "resolved_path": resolved_path,
            "stat_result_present": stat_result is not None,
            "mode_type_bits": mode_type_bits,
            "is_file": is_file,
            "is_directory": is_directory,
            "size": stat_result.st_size if is_file else None,
            "mtime_seconds": stat_result.st_mtime if is_file else None,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
                "status": "ok",
                "value": observation,
            }
        ],
    }


def _apply_response_cookie_action(response: Any, raw_action: dict[str, Any], index: int) -> None:
    context = f"Response cookie_actions[{index}]"
    method = raw_action.get("method") if isinstance(raw_action, dict) else None
    if method == "set":
        action = _strict_object(
            raw_action,
            {
                "method",
                "key",
                "value",
                "max_age",
                "expires",
                "path",
                "domain",
                "secure",
                "httponly",
                "samesite",
                "partitioned",
            },
            context,
        )
    elif method == "delete":
        action = _strict_object(
            raw_action,
            {
                "method",
                "key",
                "clock_unix_seconds",
                "path",
                "domain",
                "secure",
                "httponly",
                "samesite",
            },
            context,
        )
        import time

        original_time = time.time
        time.time = lambda: float(action["clock_unix_seconds"])
        try:
            response.delete_cookie(
                key=action["key"],
                path=action["path"],
                domain=action["domain"],
                secure=action["secure"],
                httponly=action["httponly"],
                samesite=action["samesite"],
            )
        finally:
            time.time = original_time
        return
    else:
        raise ValueError(f"{context}.method must be set or delete")
    expires = action["expires"]
    clock_timestamp: float | None = None
    if isinstance(expires, dict):
        if expires["kind"] == "datetime-iso8601":
            from datetime import datetime

            expires = datetime.fromisoformat(expires["value"])
        elif expires["kind"] == "integer-offset":
            from datetime import datetime

            clock_timestamp = datetime.fromisoformat(expires["time_now"]).timestamp()
            expires = expires["value"]
        else:
            raise ValueError("Response cookie expires input has an unsupported kind")
    arguments = {
        "key": action["key"],
        "value": action["value"],
        "max_age": action["max_age"],
        "expires": expires,
        "path": action["path"],
        "domain": action["domain"],
        "secure": action["secure"],
        "httponly": action["httponly"],
        "samesite": action["samesite"],
        "partitioned": action["partitioned"],
    }
    if clock_timestamp is None:
        response.set_cookie(**arguments)
    else:
        import time

        original_time = time.time
        time.time = lambda: clock_timestamp
        try:
            response.set_cookie(**arguments)
        finally:
            time.time = original_time


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
    if "render_override" in case:
        required_fields.add("render_override")
    if "cookie_actions" in case:
        required_fields.add("cookie_actions")
    if surface == STREAMING_RESPONSE_SURFACE:
        required_fields.add("streaming")
        required_fields.update(
            key for key in ("background", "receive_behavior", "stream_lifecycle") if key in case
        )
    _strict_object(
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

    content_value = case["content"]
    content_keys = {"kind", "value"}
    if isinstance(content_value, dict) and content_value.get("kind") == "repeating-chunks":
        content_keys.add("checkpoint")
    content_spec = _strict_object(content_value, content_keys, "Response content")
    content_kind = content_spec["kind"]
    streaming: str | None = None
    repeating_stream = False
    if surface == STREAMING_RESPONSE_SURFACE:
        if content_kind not in {"chunks", "repeating-chunks"} or not isinstance(
            content_spec["value"], list
        ):
            raise ValueError("StreamingResponse content must select an array of chunks")
        repeating_stream = content_kind == "repeating-chunks"
        if repeating_stream and not content_spec["value"]:
            raise ValueError("StreamingResponse repeating content must contain at least one chunk")
        content = []
        for index, chunk_spec in enumerate(content_spec["value"]):
            chunk_spec = _strict_object(
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
                chunk = _decode_b64(encoded_chunk, f"content.value[{index}].value")
            elif chunk_spec["kind"] == "memoryview-base64":
                encoded_chunk = chunk_spec["value"]
                if not isinstance(encoded_chunk, str):
                    raise ValueError("StreamingResponse memoryview chunks must be base64 strings")
                chunk = memoryview(_decode_b64(encoded_chunk, f"content.value[{index}].value"))
            else:
                raise ValueError(
                    "StreamingResponse chunks must be text, bytes, or memoryview input"
                )
            content.append(chunk)
        streaming = case["streaming"]
        if streaming not in {"sync", "async-iterator", "async-iterable", "async-generator"}:
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
            content = _decode_b64(encoded_content, "content.value")
        elif content_kind == "memoryview-base64":
            encoded_content = content_spec["value"]
            if not isinstance(encoded_content, str):
                raise ValueError("Response memoryview content value must be a string")
            content = memoryview(_decode_b64(encoded_content, "content.value"))
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

    scope_spec = _strict_object(
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
    asgi_spec = _strict_object(scope_spec["asgi"], {"version", "spec_version"}, "ASGI version")
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
    send_error_spec: dict[str, Any] | None = None
    if case["send"] != {"kind": "capture-asgi-send"}:
        if surface != STREAMING_RESPONSE_SURFACE:
            raise ValueError("send input must select the declared ASGI message collector")
        send_error_spec = _strict_object(
            case["send"],
            {"kind", "event_index", "message"},
            "StreamingResponse failing send",
        )
        if (
            send_error_spec["kind"] != "capture-asgi-send-until-oserror"
            or type(send_error_spec["event_index"]) is not int
            or send_error_spec["event_index"] < 0
            or not isinstance(send_error_spec["message"], str)
        ):
            raise ValueError("StreamingResponse failing send input is invalid")

    background_values: list[str] | None = None
    if "background" in case:
        background_spec = _strict_object(
            case["background"], {"kind", "values"}, "Response background"
        )
        if background_spec["kind"] != "async-values-recorder":
            raise ValueError("Response background must select the async values recorder")
        values = background_spec["values"]
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("Response background values must be an array of strings")
        background_values = values

    stream_lifecycle: dict[str, str] | None = None
    if "stream_lifecycle" in case:
        stream_lifecycle_spec = _strict_object(
            case["stream_lifecycle"],
            {"kind", "cancellation_marker", "finally_marker"},
            "Response stream lifecycle recorder",
        )
        if stream_lifecycle_spec["kind"] != "cancellation-and-finally-recorder":
            raise ValueError("Response stream lifecycle recorder kind is unsupported")
        for key in ("cancellation_marker", "finally_marker"):
            if not isinstance(stream_lifecycle_spec[key], str) or not stream_lifecycle_spec[key]:
                raise ValueError(f"Response stream lifecycle {key} must be a non-empty string")
        stream_lifecycle = stream_lifecycle_spec

    receive_behavior: dict[str, Any] | None = None
    if "receive_behavior" in case:
        receive_behavior = _strict_object(
            case["receive_behavior"],
            {"kind", "minimum_body_bytes"},
            "Response receive behavior",
        )
        if (
            receive_behavior["kind"] != "disconnect-after-body-bytes"
            or type(receive_behavior["minimum_body_bytes"]) is not int
            or receive_behavior["minimum_body_bytes"] < 1
        ):
            raise ValueError("Response receive behavior input is invalid")

    execution_trace = (
        [] if streaming == "async-generator" or background_values is not None else None
    )

    from starlette.responses import JSONResponse, Response, StreamingResponse

    response_type = {
        RESPONSE_SURFACE: Response,
        JSON_RESPONSE_SURFACE: JSONResponse,
        STREAMING_RESPONSE_SURFACE: StreamingResponse,
    }[surface]
    render_override = case.get("render_override")
    if render_override is not None:
        render_override = _strict_object(
            render_override, {"kind", "prefix"}, "Response render override"
        )
        if render_override["kind"] != "prefix-text":
            raise ValueError("Response render override must select prefix-text")
        prefix = render_override["prefix"]
        if not isinstance(prefix, str):
            raise ValueError("Response render prefix must be a string")

        class InputRenderResponse(Response):
            def render(self, value: Any) -> bytes:
                return (prefix + value).encode(self.charset)

        response_type = InputRenderResponse
    if streaming == "sync":
        content = (
            _input_sync_iterator(content, execution_trace)
            if execution_trace is not None
            else iter(content)
        )
    elif streaming == "async-iterator":
        content = _InputAsyncIterator(content, execution_trace)
    elif streaming == "async-iterable":
        content = _InputAsyncIterable(content, execution_trace)
    elif streaming == "async-generator":
        if repeating_stream:
            if execution_trace is None or stream_lifecycle is None:
                raise ValueError("repeating async generator requires its lifecycle trace")
            content = _input_repeating_async_generator(
                content, execution_trace, stream_lifecycle, content_spec["checkpoint"]
            )
        else:
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
    try:
        for index, raw_action in enumerate(case.get("cookie_actions", [])):
            _apply_response_cookie_action(response, raw_action, index)
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {
                    "step_id": case["observations"][0],
                    "status": "error",
                    "error": _dispatch_error(exc),
                    "partial_value": {
                        "response_status": None,
                        "ordered_repeated_headers": [],
                        "response_bytes": {"encoding": "base64", "data": ""},
                        "asgi_event_order": [],
                        "asgi_events": [],
                    },
                }
            ],
        }
    scope = _make_scope(scope_spec)
    sent: list[dict[str, Any]] = []
    receive_gate = asyncio.Event() if receive_behavior is not None else None
    sent_body_bytes = 0

    async def receive() -> dict[str, Any]:
        if receive_gate is not None:
            await receive_gate.wait()
        message = {"type": "http.disconnect"}
        if execution_trace is not None and receive_gate is not None:
            execution_trace.append({"event": "asgi-receive", "message": _json_safe(message)})
        return message

    send_index = 0

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index, sent_body_bytes
        if send_error_spec is not None and send_index == send_error_spec["event_index"]:
            send_index += 1
            raise OSError(send_error_spec["message"])
        sent.append(message)
        if execution_trace is not None:
            execution_trace.append({"event": "asgi-send", "message": _canonical_message(message)})
        if receive_behavior is not None and message["type"] == "http.response.body":
            sent_body_bytes += len(message.get("body", b""))
            if sent_body_bytes >= receive_behavior["minimum_body_bytes"]:
                if receive_gate is None:
                    raise RuntimeError("disconnect receive behavior has no receive gate")
                receive_gate.set()
        send_index += 1

    captured_error: Exception | None = None
    try:
        asyncio.run(response(scope, receive, send))
    except Exception as exc:
        if send_error_spec is None:
            raise
        captured_error = exc
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
    item = {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": case["observations"][0], "status": "ok", "value": observation}
        ],
    }
    if captured_error is not None:
        item["observations"] = [
            {
                "step_id": case["observations"][0],
                "status": "error",
                "error": _dispatch_error(captured_error),
                "partial_value": observation,
            }
        ]
    return item


def _reverse_url_error(exc: Exception) -> dict[str, str]:
    return {"class": type(exc).__name__, "message": str(exc)}


def _reverse_url_path_value(url_path: Any) -> dict[str, str]:
    return {"path": str(url_path), "protocol": url_path.protocol, "host": url_path.host}


def _build_reverse_route_node(
    node: dict[str, Any],
    lookup: dict[str, Any],
    observation: dict[str, Any],
) -> Any:
    from starlette.responses import Response
    from starlette.routing import Host, Mount, Route, Router, WebSocketRoute

    kind = node["kind"]
    observer = node.get("observer")

    async def request_endpoint(request: Any) -> Response:
        if observer == "request-url-for":
            try:
                value = request.url_for(lookup["name"], **lookup["path_params"])
                observation["result"] = {"url": str(value)}
            except Exception as exc:
                observation["result"] = {"error": _reverse_url_error(exc)}
        return Response()

    async def websocket_endpoint(websocket: Any) -> None:
        del websocket

    if kind == "http-route":
        return Route(
            node["path"],
            request_endpoint,
            methods=node["methods"],
            name=node["name"],
        )
    if kind == "websocket-route":
        return WebSocketRoute(node["path"], websocket_endpoint, name=node["name"])
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
        from starlette.applications import Starlette

        return Starlette(
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ]
        )
    if kind == "host-route":
        return Host(
            node["host"],
            app=Router(
                routes=[
                    _build_reverse_route_node(child, lookup, observation)
                    for child in node["routes"]
                ]
            ),
            name=node["name"],
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

    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], _MISSING)
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
            if graph_spec is None:
                graph = None
            else:
                graph = _build_reverse_route_node(graph_spec, lookup, observation)

            async def dispatched_url() -> dict[str, Any]:
                scope = _reverse_request_scope(request_scope)
                provider = request_scope["provider"]
                if provider == "none":
                    observation["result"] = _request_url_value(Request(scope), lookup)
                elif provider == "router":
                    scope["router"] = graph
                    observation["result"] = _request_url_value(Request(scope), lookup)
                elif provider == "app":
                    scope["app"] = graph
                    observation["result"] = _request_url_value(Request(scope), lookup)
                else:

                    async def receive() -> dict[str, Any]:
                        return {"type": "http.disconnect"}

                    async def send(message: dict[str, Any]) -> None:
                        del message

                    await graph(scope, receive, send)
                    if "result" not in observation:
                        raise RuntimeError("request URL observer route did not run")
                return observation["result"]

            observed = asyncio.run(dispatched_url())
        else:
            graph = _build_reverse_route_node(graph_spec, lookup, observation)
            if case["surface"] == "starlette.routing.Route":
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            elif case["surface"] == "starlette.routing.WebSocketRoute":
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            elif case["surface"] == "starlette.routing.Router":
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            elif case["surface"] == "starlette.routing.Mount":
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            elif case["surface"] == HOST_SURFACE:
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            elif case["surface"] == "starlette.applications.Starlette":
                result = graph.url_path_for(lookup["name"], **lookup["path_params"])
            else:
                raise ValueError(f"unsupported reverse URL surface: {case['surface']!r}")
            observed = _reverse_url_path_value(result)
    except Exception as exc:
        observed = {"error": _reverse_url_error(exc)}
    finally:
        for name, old_convertor in previous_convertors.items():
            if old_convertor is _MISSING:
                CONVERTOR_TYPES.pop(name, None)
            else:
                CONVERTOR_TYPES[name] = old_convertor

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


def _request_url_value(request: Any, lookup: dict[str, Any]) -> dict[str, Any]:
    try:
        value = request.url_for(lookup["name"], **lookup["path_params"])
        return {"url": str(value)}
    except Exception as exc:
        return {"error": _reverse_url_error(exc)}


async def _invoke_lifespan_around_dispatch(
    app: Any,
    lifecycle_args: dict[str, Any],
    dispatch_args: dict[str, Any],
    lifecycle_trace: list[str],
    request_observations: list[dict[str, Any]],
    route_endpoint: Any,
    sync_endpoint_states: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run an ASGI lifespan session around the following HTTP workflow step."""
    if lifecycle_args["scope"].get("type") != "lifespan":
        raise ValueError("the lifecycle workflow step must use a lifespan scope")
    lifecycle_messages = [_message(item) for item in lifecycle_args["receive"]]
    if [message["type"] for message in lifecycle_messages] != [
        "lifespan.startup",
        "lifespan.shutdown",
    ]:
        raise ValueError("the lifecycle workflow must provide startup then shutdown")
    if lifecycle_args["send"] != {"kind": "capture-asgi-send"}:
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

    lifespan_scope = _make_scope(lifecycle_args["scope"])
    lifespan_task = asyncio.create_task(app(lifespan_scope, receive_lifecycle, send_lifecycle))
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
            dispatch_args,
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

    events = workflow_events
    lifecycle_value = {
        "response_status": None,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "lifespan_scope_state": {
            "present": "state" in lifespan_scope,
            "value": _json_safe(lifespan_scope.get("state")),
        },
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": {"handler_calls": [], "debug_traceback": None},
        "deprecation_warnings": list(getattr(app, "_parity_lifespan_warnings", [])),
    }
    return lifecycle_value, dispatch_value


async def _invoke_lifespan_only(
    app: Any,
    lifecycle_args: dict[str, Any],
    lifecycle_trace: list[str],
) -> dict[str, Any] | _CapturedDispatchError:
    """Run a complete lifecycle input while observing callback invocation effects."""
    if lifecycle_args["scope"].get("type") != "lifespan":
        raise ValueError("the lifecycle workflow step must use a lifespan scope")
    if lifecycle_args["send"].get("kind") not in {"capture-asgi-send", "raise-on-call"}:
        raise ValueError("send input must select a declared lifecycle callback")

    actions = lifecycle_args["receive"]
    action_index = 0
    send_spec = lifecycle_args["send"]
    workflow_events: list[dict[str, Any]] = []

    async def resolved(value: dict[str, Any]) -> dict[str, Any]:
        return value

    async def cancelled(message: str) -> dict[str, Any]:
        raise asyncio.CancelledError(message)

    def receive_lifecycle() -> Any:
        nonlocal action_index
        if action_index >= len(actions):
            raise RuntimeError("lifespan receive input was exhausted")
        action = actions[action_index]
        action_index += 1
        if action["kind"] == "raise":
            raise RuntimeError(action["message"])
        if action["kind"] == "await-raise":
            return cancelled(action["message"])
        return resolved(_message(action["message"]))

    async def record_send(message: dict[str, Any]) -> None:
        workflow_events.append(_canonical_message(message))

    def send_lifecycle(message: dict[str, Any]) -> Any:
        if (
            send_spec["kind"] == "raise-on-call"
            and message.get("type") == send_spec["message_type"]
        ):
            raise RuntimeError(send_spec["message"])
        return record_send(message)

    scope = _make_scope(lifecycle_args["scope"])
    try:
        await app(scope, receive_lifecycle, send_lifecycle)
        captured_exception = None
    except BaseException as exc:
        captured_exception = exc

    value = {
        "response_status": None,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": [event["type"] for event in workflow_events],
        "asgi_events": workflow_events,
        "lifespan_scope_state": {
            "present": "state" in scope,
            "value": _json_safe(scope.get("state")),
        },
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": {"handler_calls": [], "debug_traceback": None},
        "deprecation_warnings": list(getattr(app, "_parity_lifespan_warnings", [])),
    }
    if captured_exception is None:
        return value
    error = _dispatch_error(captured_exception)
    error["stage"] = "lifespan"
    return _CapturedDispatchError(error=error, partial_value=value)


def _exception_value_snapshot(instance: Any, fields: tuple[str, ...], phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "fields": {name: _json_safe(getattr(instance, name)) for name in fields},
        "str": str(instance),
        "repr": repr(instance),
    }


def _run_default_receive_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "observations",
        },
        "Request default-receive case",
    )
    from starlette.requests import Request

    request = Request(_make_scope(case["scope"]))

    async def observe() -> dict[str, Any]:
        try:
            message = await request.receive()
        except Exception as exc:
            return {
                "outcome": "error",
                "error": {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                },
            }
        return {"outcome": "value", "value": _json_safe(message)}

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "receive", "status": "ok", "value": {"receive": asyncio.run(observe())}}
        ],
    }


def _run_send_push_promise_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "path",
            "send_callback",
            "observations",
        },
        "Request send-push-promise case",
    )
    from starlette.requests import Request

    sent_messages: list[dict[str, Any]] = []

    async def capture_send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    scope = _make_scope(case["scope"])
    if case["send_callback"]["kind"] == "capture":
        request = Request(scope, send=capture_send)
    else:
        request = Request(scope)

    async def observe() -> dict[str, Any]:
        try:
            await request.send_push_promise(case["path"])
        except Exception as exc:
            return {
                "outcome": "error",
                "error": {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                },
                "sent": _json_safe(sent_messages),
            }
        return {"outcome": "value", "sent": _json_safe(sent_messages)}

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "send-push-promise",
                "status": "ok",
                "value": {"send": asyncio.run(observe())},
            }
        ],
    }


def _run_request_is_disconnected_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "receive",
            "receive_checkpoints",
            "observations",
        },
        "Request is-disconnected case",
    )
    import anyio
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    scope = _make_scope(case["scope"])
    incoming = [_message(message) for message in case["receive"]]
    receive_checkpoints = set(case["receive_checkpoints"])
    receive_calls = 0
    received = 0
    checkpoint_entries = 0
    checkpoint_completions = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal checkpoint_completions, checkpoint_entries, receive_calls, received
        call_index = receive_calls
        receive_calls += 1
        if call_index in receive_checkpoints:
            checkpoint_entries += 1
            await anyio.lowlevel.checkpoint()
            checkpoint_completions += 1
        message = incoming[received]
        received += 1
        return message

    async def send(message: dict[str, Any]) -> None:
        sent.append(_canonical_message(message))

    async def observe() -> dict[str, Any]:
        request = Request(scope, receive)
        body = await request.body()
        disconnected_before = await request.is_disconnected()
        await PlainTextResponse("ok")(scope, receive, send)
        disconnected_after = await request.is_disconnected()
        disconnected_cached = await request.is_disconnected()
        return {
            "body_base64": base64.b64encode(body).decode("ascii"),
            "disconnected_before": disconnected_before,
            "response_messages": sent,
            "disconnected_after": disconnected_after,
            "disconnected_cached": disconnected_cached,
            "receive_calls": receive_calls,
            "received_messages": received,
            "receive_checkpoint_entries": checkpoint_entries,
            "receive_checkpoint_completions": checkpoint_completions,
        }

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "is-disconnected",
                "status": "ok",
                "value": {"is-disconnected": asyncio.run(observe())},
            }
        ],
    }


def _run_status_symbols_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "public_names",
            "deprecated_names",
            "missing_names",
            "observe_directory",
            "observations",
        },
        "status module-symbol-sequence case",
    )
    from starlette import status

    public_names = list(status.__all__)
    public_values = {name: getattr(status, name) for name in case["public_names"]}
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        deprecated_values = [
            {"name": name, "value": getattr(status, name)} for name in case["deprecated_names"]
        ]
    missing_attributes = []
    for name in case["missing_names"]:
        try:
            value = getattr(status, name)
        except AttributeError as exc:
            missing_attributes.append(
                {
                    "name": name,
                    "outcome": "attribute-error",
                    "message": str(exc),
                }
            )
        else:
            missing_attributes.append(
                {"name": name, "outcome": "value", "value": _json_safe(value)}
            )
    values = {
        "public_names": public_names,
        "public_values": public_values,
        "deprecated_values_and_warnings": {
            "values": deprecated_values,
            "warnings": [
                {
                    "category": f"{item.category.__module__}.{item.category.__qualname__}",
                    "message": str(item.message),
                }
                for item in recorded
            ],
        },
        "directory": dir(status) if case["observe_directory"] else None,
        "missing_attribute": missing_attributes,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": values}
            for selector in case["observations"]
        ],
    }


def _run_value_formatting_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["surface"] == EXCEPTION_VALUES_SURFACE:
        _strict_object(
            case,
            {
                "case_id",
                "surface",
                "operation",
                "covers",
                "target_profiles",
                "assets",
                "instances",
                "observations",
            },
            "exception value-formatting case",
        )
        from starlette.exceptions import HTTPException, WebSocketException

        observed_instances: list[dict[str, Any]] = []
        for index, item in enumerate(case["instances"]):
            _strict_object(
                item,
                {"kind", "subclass_name", "arguments", "mutations"},
                f"exception instance[{index}]",
            )
            base = HTTPException if item["kind"] == "http" else WebSocketException
            exception_type = (
                type(item["subclass_name"], (base,), {})
                if item["subclass_name"] is not None
                else base
            )
            try:
                instance = exception_type(**item["arguments"])
            except Exception as exc:
                observed_instances.append(
                    {
                        "index": index,
                        "kind": item["kind"],
                        "outcome": "constructor-error",
                        "error": {
                            "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                            "message": str(exc),
                        },
                    }
                )
                continue

            fields = (
                ("status_code", "detail", "headers")
                if item["kind"] == "http"
                else ("code", "reason")
            )

            snapshots = [_exception_value_snapshot(instance, fields, "initial")]
            for mutation_index, mutation in enumerate(item["mutations"]):
                _strict_object(
                    mutation, {"field", "value"}, f"exception mutation[{mutation_index}]"
                )
                setattr(instance, mutation["field"], mutation["value"])
                snapshots.append(
                    _exception_value_snapshot(instance, fields, f"mutation-{mutation_index}")
                )
            observed_instances.append(
                {
                    "index": index,
                    "kind": item["kind"],
                    "outcome": "constructed",
                    "snapshots": snapshots,
                }
            )
        value = {"value-formatting": {"instances": observed_instances}}
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {"step_id": VALUE_FORMATTING_OPERATION, "status": "ok", "value": value}
            ],
        }

    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "middleware",
            "observations",
        },
        "Middleware value-formatting case",
    )
    from starlette.middleware import Middleware

    spec = _strict_object(case["middleware"], {"class_name", "args", "kwargs"}, "Middleware input")
    middleware_class = type(spec["class_name"], (), {"__module__": "starlette.middleware"})
    middleware = Middleware(middleware_class, *spec["args"], **spec["kwargs"])
    iter_values = list(middleware)
    iter_observation = [
        {"kind": "callable", "name": iter_values[0].__name__},
        _json_safe(iter_values[1]),
        _json_safe(iter_values[2]),
    ]
    values = {"repr": repr(middleware), "__iter__": iter_observation}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": values}
            for selector in case["observations"]
        ],
    }


def _error_snapshot(exc: Exception) -> dict[str, str]:
    return {"class": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)}


AUTHENTICATION_OPERATIONS = {
    ("starlette.authentication", "value-operations"),
    ("starlette.authentication", "scope-check"),
    ("starlette.authentication", "decorator-dispatch"),
    ("starlette.middleware.authentication.AuthenticationMiddleware", "dispatch"),
}


def _make_auth_endpoint(mode: str, parameter_name: str, calls: list[Any], result: Any) -> Any:
    if mode == "sync" and parameter_name == "request":

        def endpoint(request: Any, _calls: list[Any] = calls, _result: Any = result) -> Any:
            _calls.append(_result)
            return _result
    elif mode == "sync":

        def endpoint(websocket: Any, _calls: list[Any] = calls, _result: Any = result) -> Any:
            _calls.append(_result)
            return _result
    elif parameter_name == "request":

        async def endpoint(request: Any, _calls: list[Any] = calls, _result: Any = result) -> Any:
            _calls.append(_result)
            return _result
    else:

        async def endpoint(websocket: Any, _calls: list[Any] = calls, _result: Any = result) -> Any:
            _calls.append(_result)
            return _result

    return endpoint


def _run_authentication_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "actions",
        }
        if case["operation"] == "value-operations"
        else {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "checks",
        }
        if case["operation"] == "scope-check"
        else {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "scenarios",
        },
        "authentication parity case",
    )
    from starlette.authentication import (
        AuthCredentials,
        AuthenticationError,
        BaseUser,
        SimpleUser,
        UnauthenticatedUser,
        has_required_scope,
        requires,
    )

    def value_outcome(callback: Any) -> dict[str, Any]:
        try:
            value = callback()
        except Exception as exc:
            return {"outcome": "error", "error": _error_snapshot(exc)}
        return {"outcome": "value", "value": _json_safe(value)}

    operation = (case["surface"], case["operation"])
    if operation == ("starlette.authentication", "value-operations"):
        users = {
            "base": lambda action: BaseUser(),
            "simple": lambda action: SimpleUser(action["username"]),
            "unauthenticated": lambda action: UnauthenticatedUser(),
        }
        results = []
        for action in case["actions"]:
            if action["action"] == "credentials":
                source_scopes = action["scopes"]
                credentials = AuthCredentials(source_scopes)
                if "mutate_source_scopes" in action:
                    source_scopes[:] = action["mutate_source_scopes"]
                result = {"action": action["action"], "scopes": list(credentials.scopes)}
                if "mutate_source_scopes" in action:
                    result["source_scopes"] = list(source_scopes)
                results.append(result)
            else:
                user = users[action["user"]](action)
                properties = {
                    name: value_outcome(lambda user=user, name=name: getattr(user, name))
                    for name in ("is_authenticated", "display_name", "identity")
                }
                results.append({"action": action["action"], "properties": properties})
        observed = {"actions": results}
    elif operation == ("starlette.authentication", "scope-check"):
        from types import SimpleNamespace

        results = [
            {
                "granted_scopes": list(check["granted_scopes"]),
                "required_scopes": list(check["required_scopes"]),
                "result": has_required_scope(
                    SimpleNamespace(auth=AuthCredentials(check["granted_scopes"])),
                    check["required_scopes"],
                ),
            }
            for check in case["checks"]
        ]
        observed = {"checks": results}
    elif operation == ("starlette.authentication", "decorator-dispatch"):
        import asyncio
        from urllib.parse import urlsplit

        from starlette.requests import Request
        from starlette.responses import RedirectResponse
        from starlette.routing import Route, Router
        from starlette.websockets import WebSocket

        results = []
        for scenario in case["scenarios"]:
            connection_spec = scenario["connection"]
            is_websocket = connection_spec["kind"] == "websocket"
            path_url = connection_spec.get("url", "https://example.test/private")
            parts = urlsplit(path_url)
            scheme = parts.scheme or ("wss" if is_websocket else "https")
            path = parts.path or "/private"
            scope = {
                "type": "websocket" if is_websocket else "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "scheme": scheme,
                "path": path,
                "raw_path": path.encode(),
                "query_string": parts.query.encode(),
                "root_path": "",
                "headers": [(b"host", (parts.netloc or "example.test").encode())],
                "client": ("127.0.0.1", 1234),
                "server": (
                    parts.hostname or "example.test",
                    parts.port or (443 if scheme in {"https", "wss"} else 80),
                ),
                "auth": AuthCredentials(connection_spec["auth_scopes"]),
            }
            if is_websocket:
                scope["subprotocols"] = []
            else:
                scope["method"] = "GET"
                routes = [
                    Route(
                        route["path"],
                        endpoint=lambda request: None,
                        name=route["name"],
                    )
                    for route in connection_spec.get("routes", [])
                ]
                scope["router"] = Router(routes=routes)
            sent = []

            async def receive(_is_websocket: bool = is_websocket) -> dict[str, Any]:
                return {
                    "type": "websocket.connect" if _is_websocket else "http.request",
                    "body": b"",
                    "more_body": False,
                }

            async def send(message: dict[str, Any], _sent: list[Any] = sent) -> None:
                _sent.append(_json_safe(message))

            connection = WebSocket(scope, receive, send) if is_websocket else Request(scope)
            callable_spec = scenario["callable"]
            endpoint_calls = []
            result_value = callable_spec["result"]

            endpoint = _make_auth_endpoint(
                callable_spec["mode"],
                callable_spec["parameter"],
                endpoint_calls,
                result_value,
            )
            redirect = scenario.get("redirect")
            wrapped = requires(
                scenario["required_scopes"],
                status_code=scenario.get("status_code", 403),
                redirect=redirect,
            )(endpoint)
            try:
                value = (
                    wrapped(connection)
                    if callable_spec["mode"] == "sync"
                    else asyncio.run(wrapped(connection))
                )
            except Exception as exc:
                outcome = {"outcome": "error", "error": _error_snapshot(exc)}
                if hasattr(exc, "status_code"):
                    outcome["status_code"] = exc.status_code
                    outcome["detail"] = _json_safe(exc.detail)
            else:
                if isinstance(value, RedirectResponse):
                    asyncio.run(value(scope, receive, send))
                    outcome = {
                        "outcome": "response",
                        "sent": sent,
                    }
                else:
                    outcome = {"outcome": "value", "value": _json_safe(value)}
            results.append({"outcome": outcome, "endpoint_calls": endpoint_calls, "sent": sent})
        observed = {"scenarios": results}
    else:
        import asyncio

        from starlette.middleware.authentication import AuthenticationMiddleware
        from starlette.responses import PlainTextResponse

        results = []
        for scenario in case["scenarios"]:
            calls = []
            app_calls = []
            sent = []
            backend_spec = scenario["backend"]

            class Backend:
                async def authenticate(
                    self,
                    conn: Any,
                    _calls: list[Any] = calls,
                    _backend_spec: dict[str, Any] = backend_spec,
                ) -> Any:
                    _calls.append({"scope_type": conn.scope["type"]})
                    if "error" in _backend_spec:
                        raise AuthenticationError(_backend_spec["error"]["message"])
                    result = _backend_spec["outcome"]
                    if not isinstance(result, dict):
                        return None
                    return AuthCredentials(result["credentials"]), SimpleUser(result["user"])

            async def app(
                scope: dict[str, Any],
                receive: Any,
                send: Any,
                _app_calls: list[Any] = app_calls,
            ) -> None:
                observed_scope = {"type": scope["type"]}
                if "auth" in scope:
                    observed_scope["auth_scopes"] = list(scope["auth"].scopes)
                    observed_scope["user"] = {
                        "is_authenticated": scope["user"].is_authenticated,
                        "display_name": scope["user"].display_name,
                    }
                _app_calls.append(observed_scope)

            def on_error(conn: Any, exc: Exception) -> Any:
                return PlainTextResponse(f"handled:{exc}", status_code=401)

            scope_type = scenario["scope_type"]
            scope = {
                "type": scope_type,
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "path": "/",
                "raw_path": b"/",
                "query_string": b"",
                "root_path": "",
                "scheme": "http",
                "headers": [],
                "client": ("127.0.0.1", 1234),
                "server": ("example.test", 80),
            }
            if scope_type == "http":
                scope["http_version"] = "1.1"
                scope["method"] = "GET"
            elif scope_type == "websocket":
                scope["http_version"] = "1.1"
                scope["scheme"] = "ws"
                scope["subprotocols"] = []
            else:
                scope["state"] = {}

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict[str, Any], _sent: list[Any] = sent) -> None:
                _sent.append(_json_safe(message))

            middleware = AuthenticationMiddleware(
                app,
                Backend(),
                on_error if scenario["error_handler"] == "custom-response" else None,
            )
            asyncio.run(middleware(scope, receive, send))
            results.append(
                {
                    "backend_calls": calls,
                    "app_calls": app_calls,
                    "scope_auth_scopes": list(scope["auth"].scopes) if "auth" in scope else None,
                    "scope_user": (
                        {
                            "is_authenticated": scope["user"].is_authenticated,
                            "display_name": scope["user"].display_name,
                        }
                        if "user" in scope
                        else None
                    ),
                    "sent": sent,
                }
            )
        observed = {"scenarios": results}

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": step_id, "status": "ok", "value": observed}
            for step_id in case["observations"]
        ],
    }


def _run_url_query_params_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "url",
            "actions",
            "observations",
        },
        "URL query-parameter case",
    )
    from starlette.datastructures import URL

    url = URL(case["url"])
    results = []
    for action in case["actions"]:
        method = getattr(url, action["method"])
        try:
            updated = method(*action.get("args", []), **action.get("kwargs", {}))
        except Exception as exc:
            results.append(
                {"method": action["method"], "outcome": "error", "error": _error_snapshot(exc)}
            )
        else:
            url = updated
            results.append({"method": action["method"], "outcome": "value", "url": str(url)})

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "action-results", "status": "ok", "value": {"action-results": results}}
        ],
    }


def _query_params_from_input(query_params_type: Any, source: dict[str, Any]) -> Any:
    kind = source["kind"]
    if kind == "string":
        return query_params_type(source["value"])
    if kind == "bytes":
        return query_params_type(base64.b64decode(source["value_base64"], validate=True))
    if kind == "empty":
        return query_params_type()
    if kind == "pairs":
        return query_params_type(source["items"], **dict(source["kwargs"]))
    if kind == "mapping":
        return query_params_type(dict(source["items"]))
    original = query_params_type(source["items"])
    return query_params_type(original)


def _run_query_params_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "source",
            "probe_keys",
            "comparison",
            "observations",
        },
        "QueryParams construction case",
    )
    from starlette.datastructures import QueryParams

    params = _query_params_from_input(QueryParams, case["source"])
    comparison = (
        None
        if case["comparison"] is None
        else _query_params_from_input(QueryParams, case["comparison"])
    )
    lookups = [
        {
            "key": key,
            "contains": key in params,
            "get": params.get(key),
            "get_with_default": params.get(key, "__starlette_rs_default__"),
            "getlist": params.getlist(key),
            "getitem": params[key] if key in params else None,
        }
        for key in case["probe_keys"]
    ]
    snapshot = {
        "str": str(params),
        "repr": repr(params),
        "len": len(params),
        "is_empty": not params,
        "keys": list(params.keys()),
        "values": list(params.values()),
        "items": list(params.items()),
        "multi_items": params.multi_items(),
        "dict": dict(params),
        "lookups": lookups,
        "equals_comparison": None if comparison is None else params == comparison,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "snapshot", "status": "ok", "value": {"snapshot": snapshot}}],
    }


def _run_config_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.config import Config, Environ

    surface_operation = (case["surface"], case["operation"])
    if surface_operation == ("starlette.config.Config", "value-resolution"):
        config_input = case["config"]
        with tempfile.TemporaryDirectory() as directory:
            previous_directory = os.getcwd()
            os.chdir(directory)
            try:
                Path(".env").write_text("\n".join(config_input["env_file_lines"]), encoding="utf-8")
                config = Config(
                    env_file=".env",
                    environ=config_input["environ"],
                    env_prefix=config_input["env_prefix"],
                )
                results = []
                for lookup in case["lookups"]:
                    cast = getattr(builtins, lookup["cast"]) if "cast" in lookup else None
                    arguments = [lookup["key"], cast]
                    if "default" in lookup:
                        arguments.append(lookup["default"])
                    try:
                        value = config(*arguments)
                    except Exception as exc:
                        result = {
                            "key": lookup["key"],
                            "outcome": "error",
                            "error": _error_snapshot(exc),
                        }
                    else:
                        result = {
                            "key": lookup["key"],
                            "outcome": "value",
                            "value": _json_safe(value),
                        }
                    results.append(result)
            finally:
                os.chdir(previous_directory)
        value = {"lookup-results": results}
    elif surface_operation == ("starlette.config.Config", "constructor-warning"):
        previous_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter("always")
                    Config(env_file=case["env_file"]["file_name"])
                results = [
                    {
                        "category": f"{item.category.__module__}.{item.category.__qualname__}",
                        "message": str(item.message),
                    }
                    for item in recorded
                ]
            finally:
                os.chdir(previous_directory)
        value = {"warning-results": results}
    else:
        environ = Environ(dict(case["initial_environ"]))
        results = []
        for action in case["actions"]:
            name = action["action"]
            result = {"action": name}
            if "key" in action:
                result["key"] = action["key"]
            try:
                if name == "set":
                    environ[action["key"]] = action["value"]
                elif name == "delete":
                    del environ[action["key"]]
                elif name == "get":
                    result["value"] = _json_safe(environ[action["key"]])
                elif name == "contains":
                    result["value"] = action["key"] in environ
                elif name == "iterate":
                    result["value"] = list(environ)
                else:
                    result["value"] = len(environ)
            except Exception as exc:
                result["error"] = _error_snapshot(exc)
            else:
                result["outcome"] = "ok"
            results.append(result)
        value = {"action-results": results}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": value}
            for selector in case["observations"]
        ],
    }


def _schema_function(docstring: str, name: str = "endpoint") -> Any:
    async def endpoint(*_args: Any, **_kwargs: Any) -> None:
        return None

    endpoint.__name__ = name
    endpoint.__doc__ = docstring
    return endpoint


def _schema_endpoint(spec: dict[str, Any]) -> Any:
    if spec["kind"] == "function":
        return _schema_function(spec["docstring"])
    methods = {
        name: _schema_function(docstring, name) for name, docstring in spec["handlers"].items()
    }
    methods["__call__"] = _schema_function("", "__call__")
    return type("SchemaEndpoint", (), methods)()


def _schema_routes(specs: list[dict[str, Any]]) -> list[Any]:
    from starlette.routing import Host, Mount, Route, Router, WebSocketRoute

    routes = []
    for spec in specs:
        kind = spec["kind"]
        if kind == "route":
            kwargs = {}
            if "methods" in spec:
                kwargs["methods"] = spec["methods"]
            if "include_in_schema" in spec:
                kwargs["include_in_schema"] = spec["include_in_schema"]
            routes.append(Route(spec["path"], _schema_endpoint(spec["endpoint"]), **kwargs))
        elif kind == "websocket-route":
            routes.append(WebSocketRoute(spec["path"], _schema_endpoint(spec["endpoint"])))
        elif kind == "mount":
            routes.append(Mount(spec["path"], routes=_schema_routes(spec["routes"])))
        else:
            routes.append(Host(spec["host"], Router(routes=_schema_routes(spec["routes"]))))
    return routes


def _endpoint_observation(endpoint: Any) -> dict[str, Any]:
    return {
        "path": endpoint.path,
        "http_method": endpoint.http_method,
        "docstring": endpoint.func.__doc__,
    }


def _run_schema_case(case: dict[str, Any]) -> dict[str, Any]:
    surface_operation = (case["surface"], case["operation"])
    if surface_operation == ("starlette.schemas.SchemaGenerator", "schema-generation"):
        from starlette.schemas import SchemaGenerator

        generator = SchemaGenerator(case["base_schema"])
        endpoints = generator.get_endpoints(_schema_routes(case["routes"]))
        schema = generator.get_schema(_schema_routes(case["routes"]))
        value = {
            "endpoints": [_endpoint_observation(endpoint) for endpoint in endpoints],
            "schema": _json_safe(schema),
        }
    elif surface_operation == ("starlette.schemas.BaseSchemaGenerator", "schema-docstring-parsing"):
        from starlette.schemas import BaseSchemaGenerator

        generator = BaseSchemaGenerator()
        parsed_docstrings = []
        first_error = None
        for docstring in case["docstrings"]:
            try:
                parsed = generator.parse_docstring(_schema_function(docstring))
            except Exception as exc:
                error = _error_snapshot(exc)
                parsed_docstrings.append({"outcome": "error", "error": error})
                if first_error is None:
                    first_error = error
            else:
                parsed_docstrings.append({"outcome": "value", "value": _json_safe(parsed)})
        value = {"parsed-docstrings": parsed_docstrings, "exception": first_error}
    else:
        from starlette.requests import Request
        from starlette.schemas import OpenAPIResponse, SchemaGenerator

        generator = SchemaGenerator(case["content"])
        direct = OpenAPIResponse(case["content"])
        application = type("SchemaApplication", (), {"routes": []})()
        request = Request({"type": "http", "method": "GET", "app": application})
        generated = generator.OpenAPIResponse(request)
        value = {
            "media-type": {"direct": direct.media_type, "generated": generated.media_type},
            "rendered-bytes": {
                "direct": _json_safe(direct.render(case["content"])),
                "generated": _json_safe(generated.render(case["content"])),
            },
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": value}
            for selector in case["observations"]
        ],
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    if (
        isinstance(case, dict)
        and case.get("surface") == BASE_HTTP_SURFACE
        and case.get("operation") == BASE_HTTP_WORKFLOW_OPERATION
    ):
        return _run_base_http_workflow_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == SESSION_MIDDLEWARE_SURFACE
        and case.get("operation") == SESSION_WORKFLOW_OPERATION
    ):
        return _run_session_workflow_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) in AUTHENTICATION_OPERATIONS
    ):
        return _run_authentication_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_DEFAULT_RECEIVE_OPERATION
    ):
        return _run_default_receive_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_SEND_PUSH_PROMISE_OPERATION
    ):
        return _run_send_push_promise_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_IS_DISCONNECTED_OPERATION
    ):
        return _run_request_is_disconnected_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        STATUS_SURFACE,
        STATUS_OPERATION,
    ):
        return _run_status_symbols_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in CONFIG_OPERATIONS:
        return _run_config_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in SCHEMA_OPERATIONS:
        return _run_schema_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == URL_QUERY_OPERATION
    ):
        return _run_url_query_params_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.QueryParams",
        "construction-and-mapping-sequence",
    ):
        return _run_query_params_case(case)
    if (
        isinstance(case, dict)
        and case.get("operation") == VALUE_FORMATTING_OPERATION
        and case.get("surface") in {EXCEPTION_VALUES_SURFACE, MIDDLEWARE_CONFIG_SURFACE}
    ):
        return _run_value_formatting_case(case)
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
        and case.get("surface") == WEBSOCKET_SURFACE
        and case.get("operation") == WEBSOCKET_CONVENIENCE_OPERATION
    ):
        return _run_websocket_convenience_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_CLOSE_SURFACE
        and case.get("operation") == WEBSOCKET_CLOSE_OPERATION
    ):
        return _run_websocket_close_case(case)
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
    if (
        isinstance(case, dict)
        and case.get("surface") == FILE_RESPONSE_SURFACE
        and case.get("operation") == RESPONSE_OPERATION
    ):
        return _run_file_response_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == STATIC_FILES_SURFACE
        and case.get("operation") == STATIC_FILES_ASYNC_BOUNDARY_OPERATION
    ):
        return _run_static_files_async_boundary_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == STATIC_FILES_SURFACE
        and case.get("operation") == STATIC_FILES_LOOKUP_PATH_OPERATION
    ):
        return _run_static_files_lookup_path_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == STATIC_FILES_SURFACE
        and case.get("operation") == RESPONSE_OPERATION
    ):
        return _run_static_files_case(case)
    if isinstance(case, dict) and case.get("surface") in {
        RESPONSE_SURFACE,
        JSON_RESPONSE_SURFACE,
        STREAMING_RESPONSE_SURFACE,
    }:
        return _run_basic_response_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") in {ROUTER_SURFACE, MOUNT_SURFACE}
        and case.get("operation") == "route-dispatch"
    ):
        return _run_route_dispatch_case(case)
    if isinstance(case, dict) and case.get("surface") in {
        CORS_SURFACE,
        HTTPS_REDIRECT_SURFACE,
        TRUSTED_HOST_SURFACE,
    }:
        return _run_protocol_middleware_case(case)
    _strict_object(
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
    if case["surface"] == "starlette.middleware.gzip.GZipMiddleware":
        if case["operation"] != "__call__":
            raise ValueError("GZipMiddleware cases must call its public ASGI interface")
        return _run_gzip_case(case)
    if case["surface"] == BODY_LIMIT_SURFACE:
        if case["operation"] != "__call__":
            raise ValueError("RequestBodyLimitMiddleware cases must call its public ASGI interface")
        return _run_body_limit_case(case)
    steps = case["steps"]
    step_ids = [step["step_id"] for step in steps]
    schedule = case["execution_schedule"]
    is_request_dispatch = case["operation"] == "request-dispatch"
    if is_request_dispatch:
        if (
            step_ids != ["application", "dispatch"]
            or steps[-1].get("operation") != "request-dispatch"
            or schedule != ["dispatch"]
        ):
            raise ValueError(
                "request-dispatch cases must contain application then request-dispatch"
            )
    elif step_ids not in (
        ["application", "lifecycle"],
        ["application", "lifecycle", "dispatch"],
        ["application", "dispatch"],
    ):
        raise ValueError("oracle adapter received a workflow outside the declared ASGI slice")
    elif (
        (
            step_ids == ["application", "lifecycle"]
            and schedule != ["lifespan.startup", "lifespan.shutdown"]
        )
        or (
            step_ids == ["application", "lifecycle", "dispatch"]
            and schedule != ["lifespan.startup", "dispatch", "lifespan.shutdown"]
        )
        or (step_ids == ["application", "dispatch"] and schedule != ["dispatch"])
    ):
        raise ValueError("execution schedule does not match the ASGI workflow steps")
    if not is_request_dispatch and steps[-1].get("operation") != "__call__":
        raise ValueError("legacy ASGI cases must dispatch through Starlette.__call__")
    if case["observations"] != step_ids[1:]:
        raise ValueError(
            "case observations must select each non-construction workflow step in input order"
        )
    if (
        case["surface"] != "starlette.applications.Starlette"
        or steps[0].get("operation") != "__init__"
    ):
        raise ValueError("ASGI route workflows must build one public Starlette application")
    application_arguments = {name: item["value"] for name, item in steps[0]["arguments"].items()}
    route_spec = application_arguments["routes"][0]
    endpoint_kind = route_spec["endpoint"]["kind"]
    capture_dispatch_error = (
        is_request_dispatch
        or endpoint_kind
        in {
            "asgi-callable-action-sequence",
            "raise-runtime-error",
        }
        or route_spec["kind"] == "websocket-route"
    )
    (
        app,
        lifecycle_trace,
        request_observations,
        route_endpoint,
        sync_endpoint_states,
    ) = _materialize_application(application_arguments)

    async def run_steps() -> list[dict[str, Any]]:
        if schedule == ["lifespan.startup", "lifespan.shutdown"]:
            lifecycle_args = {name: item["value"] for name, item in steps[1]["arguments"].items()}
            value = await _invoke_lifespan_only(app, lifecycle_args, lifecycle_trace)
            return [_workflow_observation("lifecycle", value)]
        if schedule == ["lifespan.startup", "dispatch", "lifespan.shutdown"]:
            lifecycle_args = {name: item["value"] for name, item in steps[1]["arguments"].items()}
            dispatch_args = {name: item["value"] for name, item in steps[2]["arguments"].items()}
            lifecycle_value, dispatch_value = await _invoke_lifespan_around_dispatch(
                app,
                lifecycle_args,
                dispatch_args,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                sync_endpoint_states,
            )
            return [
                {"step_id": "lifecycle", "status": "ok", "value": lifecycle_value},
                {"step_id": "dispatch", "status": "ok", "value": dispatch_value},
            ]

        results: list[dict[str, Any]] = []
        for step in steps[1:]:
            args = {name: item["value"] for name, item in step["arguments"].items()}
            value = await _invoke(
                app,
                args,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                is_request_dispatch and step["operation"] == "request-dispatch",
                sync_endpoint_states=sync_endpoint_states,
                capture_dispatch_error=capture_dispatch_error,
            )
            results.append(_workflow_observation(step["step_id"], value))
        return results

    observations = asyncio.run(run_steps())
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": observations,
    }


def main() -> int:
    raw = sys.stdin.buffer.read()
    try:

        def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON object key: {key}")
                result[key] = value
            return result

        def reject_constant(value: str) -> None:
            raise ValueError(f"non-finite JSON value is forbidden: {value}")

        request = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject_constant)
        _strict_object(request, {"schema", "mode", "subject_id", "case"}, "adapter request")
        if request["schema"] != PROTOCOL_REQUEST or request["subject_id"] != ORACLE_ID:
            raise ValueError("adapter request schema or subject id mismatch")
        starlette, root = _load_starlette()
        if request["mode"] == "identity":
            if request["case"] is not None:
                raise ValueError("identity requests must set case to null")
            response = {
                "schema": PROTOCOL_RESPONSE,
                "mode": "identity",
                "subject_id": ORACLE_ID,
                "identity": _identity(starlette, root),
            }
        elif request["mode"] == "workflow":
            if not isinstance(request["case"], dict):
                raise ValueError("workflow request case must be an object")
            response = {
                "schema": PROTOCOL_RESPONSE,
                "mode": "workflow",
                "subject_id": ORACLE_ID,
                "result": _run_case(request["case"]),
            }
        else:
            raise ValueError("adapter request mode must be identity or workflow")
        sys.stdout.write(json.dumps(response, separators=(",", ":"), allow_nan=False) + "\n")
        return 0
    except Exception as exc:  # adapter failures are infrastructure failures in the parent runner
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
