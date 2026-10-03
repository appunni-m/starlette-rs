"""Live adapter for the pinned Starlette 1.6.0 source checkout."""

from __future__ import annotations

import asyncio
import base64
import binascii
import builtins
import contextlib
import contextvars
import errno
import functools
import hashlib
import importlib.util
import inspect
import io
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

from scripts.parity.adapters.staticfiles_config import (
    STATIC_FILES_CONFIGURATION_OPERATION,
    run_static_files_configuration_case,
)

PROTOCOL_REQUEST = "migration-parity/adapter-request@1"
PROTOCOL_RESPONSE = "migration-parity/adapter-response@1"
ORACLE_ID = "starlette-python"
ORACLE_VERSION = "1.6.0"
ORACLE_COMMIT = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"
APPLICATION_SURFACE = "starlette.applications.Starlette"
APPLICATION_ROUTES_OPERATION = "routes"
WEBSOCKET_SURFACE = "starlette.websockets.WebSocket"
WEBSOCKET_OPERATION = "protocol-sequence"
WEBSOCKET_STATE_OPERATION = "state-sequence"
WEBSOCKET_CONVENIENCE_OPERATION = "convenience-sequence"
WEBSOCKET_ENDPOINT_SURFACE = "starlette.endpoints.WebSocketEndpoint"
WEBSOCKET_ENDPOINT_OPERATION = "dispatch"
HTTP_ENDPOINT_SURFACE = "starlette.endpoints.HTTPEndpoint"
HTTP_ENDPOINT_OPERATION = "dispatch"
WEBSOCKET_CLOSE_SURFACE = "starlette.websockets.WebSocketClose"
WEBSOCKET_CLOSE_OPERATION = "call-sequence"
WEBSOCKET_ROUTE_SURFACE = "starlette.routing.WebSocketRoute"
WEBSOCKET_ROUTE_OPERATION = "route-dispatch"
HTTP_ROUTE_SURFACE = "starlette.routing.Route"
HTTP_ROUTE_CALL_OPERATION = "__call__"
HTTP_ROUTE_CALL_CASE_KEYS = {
    "case_id",
    "surface",
    "operation",
    "covers",
    "target_profiles",
    "assets",
    "route",
    "scope",
    "incoming",
    "send",
    "observations",
}
ROUTER_SURFACE = "starlette.routing.Router"
ROUTER_OPERATION = "route-dispatch"
HOST_SURFACE = "starlette.routing.Host"
MOUNT_SURFACE = "starlette.routing.Mount"
ROUTE_REPRESENTATION_SURFACES = {
    HTTP_ROUTE_SURFACE,
    WEBSOCKET_ROUTE_SURFACE,
    MOUNT_SURFACE,
    HOST_SURFACE,
}
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
WSGI_SURFACE = "starlette.middleware.wsgi.WSGIMiddleware"
CORS_SURFACE = "starlette.middleware.cors.CORSMiddleware"
HTTPS_REDIRECT_SURFACE = "starlette.middleware.httpsredirect.HTTPSRedirectMiddleware"
TRUSTED_HOST_SURFACE = "starlette.middleware.trustedhost.TrustedHostMiddleware"
SERVER_ERROR_MIDDLEWARE_SURFACE = "starlette.middleware.errors.ServerErrorMiddleware"
SESSION_MIDDLEWARE_SURFACE = "starlette.middleware.sessions.SessionMiddleware"
SESSION_WORKFLOW_OPERATION = "session-workflow"
BASE_HTTP_SURFACE = "starlette.middleware.base.BaseHTTPMiddleware"
BASE_HTTP_WORKFLOW_OPERATION = "base-http-workflow"
BASE_HTTP_CONTEXTVARS_OPERATION = "contextvars-propagation"
TESTCLIENT_SURFACE = "starlette.testclient.TestClient"
TESTCLIENT_OPERATION = "request-response"
TESTCLIENT_WEBSOCKET_OPERATION = "websocket-session"
TESTCLIENT_LIFESPAN_OPERATION = "lifespan-context"
EXCEPTION_VALUES_SURFACE = "starlette.exceptions"
MIDDLEWARE_CONFIG_SURFACE = "starlette.middleware.Middleware"
VALUE_FORMATTING_OPERATION = "value-formatting"
REQUEST_DEFAULT_RECEIVE_OPERATION = ("starlette.requests.Request", "default-receive")
REQUEST_CLIENT_OPERATION = ("starlette.requests.Request", "client")
REQUEST_SCOPE_MAPPING_OPERATION = ("starlette.requests.Request", "scope-mapping")
WEBSOCKET_SCOPE_MAPPING_OPERATION = ("starlette.websockets.WebSocket", "scope-mapping")
REQUEST_SEND_PUSH_PROMISE_OPERATION = ("starlette.requests.Request", "send-push-promise")
REQUEST_IS_DISCONNECTED_OPERATION = ("starlette.requests.Request", "is-disconnected")
REQUEST_FORM_OPERATION = ("starlette.requests.Request", "form")
REQUEST_BODY_STREAM_JSON_OPERATION = ("starlette.requests.Request", "body-stream-json")
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
URL_SCOPE_OPERATION = ("starlette.datastructures.URL", "scope-construction")
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


def _record_input_background_task(
    task_index: int,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    failure: dict[str, str] | None,
    execution_trace: list[dict[str, Any]],
    event_loop_thread_id: list[int | None],
) -> None:
    execution_trace.append(
        {
            "event": "task-start",
            "task_index": task_index,
            "args": _json_safe(args),
            "kwargs": _json_safe(kwargs),
            "thread": (
                "event-loop" if threading.get_ident() == event_loop_thread_id[0] else "worker"
            ),
        }
    )
    if failure is not None:
        execution_trace.append(
            {
                "event": "task-error",
                "task_index": task_index,
                "class": failure["kind"],
                "message": failure["message"],
            }
        )
        raise Exception(failure["message"])
    execution_trace.append({"event": "task-complete", "task_index": task_index})


def _input_background_tasks(
    spec: dict[str, Any],
    execution_trace: list[dict[str, Any]],
    event_loop_thread_id: list[int | None],
    cancellation_started: asyncio.Event | None = None,
    cancellation_release: threading.Event | None = None,
    event_loop: list[asyncio.AbstractEventLoop | None] | None = None,
) -> Any:
    from starlette.background import BackgroundTask, BackgroundTasks

    if spec["kind"] not in {"single-task", "task-list", "task-list-constructor"}:
        raise ValueError("Response background task kind is unsupported")
    if not isinstance(spec["tasks"], list) or not spec["tasks"]:
        raise ValueError("Response background tasks must be a non-empty array")
    if (spec["kind"] == "single-task") != (len(spec["tasks"]) == 1):
        raise ValueError("Response background task count does not match its kind")
    if spec["kind"] != "single-task" and len(spec["tasks"]) < 2:
        raise ValueError("Response background task lists must contain multiple tasks")

    def make_callback(task_index: int, task_spec: dict[str, Any]) -> Any:
        failure = task_spec["failure"]
        if task_spec["mode"] == "async":

            async def base_callback(*args: Any, **kwargs: Any) -> None:
                if cancellation_started is None:
                    _record_input_background_task(
                        task_index, args, kwargs, failure, execution_trace, event_loop_thread_id
                    )
                    return

                execution_trace.append(
                    {
                        "event": "task-start",
                        "task_index": task_index,
                        "args": _json_safe(args),
                        "kwargs": _json_safe(kwargs),
                        "thread": (
                            "event-loop"
                            if threading.get_ident() == event_loop_thread_id[0]
                            else "worker"
                        ),
                    }
                )
                cancellation_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    execution_trace.append({"event": "task-cancelled", "task_index": task_index})
                    raise
                finally:
                    execution_trace.append({"event": "task-finally", "task_index": task_index})

        else:

            def base_callback(*args: Any, **kwargs: Any) -> None:
                if cancellation_started is None:
                    _record_input_background_task(
                        task_index, args, kwargs, failure, execution_trace, event_loop_thread_id
                    )
                    return
                if cancellation_release is None or event_loop is None or event_loop[0] is None:
                    raise RuntimeError(
                        "synchronous background cancellation controls are unavailable"
                    )
                execution_trace.append(
                    {
                        "event": "task-start",
                        "task_index": task_index,
                        "args": _json_safe(args),
                        "kwargs": _json_safe(kwargs),
                        "thread": (
                            "event-loop"
                            if threading.get_ident() == event_loop_thread_id[0]
                            else "worker"
                        ),
                    }
                )
                execution_trace.append({"event": "task-awaiting-release", "task_index": task_index})
                event_loop[0].call_soon_threadsafe(cancellation_started.set)
                if not cancellation_release.wait(timeout=5.0):
                    raise TimeoutError("synchronous background task was not released")
                execution_trace.append({"event": "task-release-observed", "task_index": task_index})
                if failure is not None:
                    execution_trace.append(
                        {
                            "event": "task-error",
                            "task_index": task_index,
                            "class": failure["kind"],
                            "message": failure["message"],
                        }
                    )
                    raise Exception(failure["message"])
                execution_trace.append({"event": "task-complete", "task_index": task_index})

        callable_spec = task_spec.get("callable", {"kind": "function"})
        callable_kind = callable_spec["kind"]
        callback = base_callback
        if callable_kind == "bound-method":
            if task_spec["mode"] == "async":

                class BoundCallback:
                    async def invoke(self, *args: Any, **kwargs: Any) -> None:
                        await base_callback(*args, **kwargs)

            else:

                class BoundCallback:
                    def invoke(self, *args: Any, **kwargs: Any) -> None:
                        base_callback(*args, **kwargs)

            callback = BoundCallback().invoke
        elif callable_kind in {"callable-object", "partial", "nested-partial"}:
            if task_spec["mode"] == "async":

                class CallableObject:
                    async def __call__(self, *args: Any, **kwargs: Any) -> None:
                        await base_callback(*args, **kwargs)

            else:

                class CallableObject:
                    def __call__(self, *args: Any, **kwargs: Any) -> None:
                        base_callback(*args, **kwargs)

            if callable_kind == "callable-object" or callable_spec["target"] == "callable-object":
                callback = CallableObject()
            if callable_kind in {"partial", "nested-partial"}:
                from functools import partial

                for binding in callable_spec["bindings"]:
                    callback = partial(
                        callback,
                        *binding["args"],
                        **binding["kwargs"],
                    )
        elif callable_kind != "function":
            raise ValueError("Response background callable shape is unsupported")
        return callback

    tasks = []
    background_tasks = BackgroundTasks() if spec["kind"] == "task-list" else None
    for task_index, task_spec in enumerate(spec["tasks"]):
        task_fields = {"mode", "args", "kwargs", "failure"}
        if isinstance(task_spec, dict) and "callable" in task_spec:
            task_fields.add("callable")
        task_spec = _strict_object(
            task_spec,
            task_fields,
            f"Response background task[{task_index}]",
        )
        if task_spec["mode"] not in {"sync", "async"}:
            raise ValueError("Response background task mode is unsupported")
        if not isinstance(task_spec["args"], list) or not isinstance(task_spec["kwargs"], dict):
            raise ValueError("Response background task arguments must be arrays and objects")
        failure = task_spec["failure"]
        if failure is not None:
            failure = _strict_object(
                failure, {"kind", "message"}, f"Response background task[{task_index}].failure"
            )
            if failure["kind"] != "Exception" or not isinstance(failure["message"], str):
                raise ValueError("Response background task failure input is unsupported")
        callback = make_callback(task_index, task_spec)
        if background_tasks is None:
            tasks.append(BackgroundTask(callback, *task_spec["args"], **task_spec["kwargs"]))
        else:
            background_tasks.add_task(callback, *task_spec["args"], **task_spec["kwargs"])
    if spec["kind"] == "single-task":
        return tasks[0]
    if spec["kind"] == "task-list-constructor":
        return BackgroundTasks(tasks)
    return background_tasks


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
    spec = importlib.util.spec_from_file_location(
        "starlette",
        package / "__init__.py",
        submodule_search_locations=[str(package)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not create an isolated import spec for the Starlette package")
    starlette = importlib.util.module_from_spec(spec)
    sys.modules["starlette"] = starlette
    try:
        spec.loader.exec_module(starlette)
    except BaseException:
        sys.modules.pop("starlette", None)
        raise

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
    if set(spec) == {"type", "version", "method", "path"}:
        return dict(spec)
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
    if "app" in spec:
        scope["app"] = spec["app"]
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


def _request_form_message(spec: dict[str, Any]) -> dict[str, Any]:
    if "body_segments" in spec:
        body_parts = []
        for segment in spec["body_segments"]:
            if segment["kind"] == "literal":
                body_parts.append(
                    _decode_b64(segment["bytes_base64"], "receive.body_segments.bytes_base64")
                )
            elif segment["kind"] == "repeat":
                pattern = _decode_b64(
                    segment["pattern_base64"], "receive.body_segments.pattern_base64"
                )
                body_parts.append(pattern * segment["count"])
            else:
                template = _decode_b64(
                    segment["template_base64"], "receive.body_segments.template_base64"
                )
                body_parts.append(
                    b"".join(
                        template.replace(b"{{index}}", str(index).encode("ascii"))
                        for index in range(segment["count"])
                    )
                )
        return {
            "type": spec["type"],
            "body": b"".join(body_parts),
            "more_body": spec["more_body"],
        }
    if "body_repeat" not in spec:
        return _message(spec)
    repeat = spec["body_repeat"]
    pattern = _decode_b64(repeat["pattern_base64"], "receive.body_repeat.pattern_base64")
    return {
        "type": spec["type"],
        "body": pattern * repeat["count"],
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
    endpoint = state["route_endpoint"]
    partial_depth = 0
    while isinstance(endpoint, functools.partial):
        partial_depth += 1
        endpoint = endpoint.func
    path_value = request.path_params[spec["path_parameter"]]
    context_value = state["context_var"].get()
    caller_thread_id = state["caller_thread_id"]
    if caller_thread_id is None:
        raise RuntimeError("sync endpoint ran without a caller thread identity")
    current_thread_id = threading.get_ident()
    with state["lock"]:
        state["invocation_count"] += 1
        state["observation"] = {
            "route_endpoint_type": type(state["route_endpoint"]).__name__,
            "partial_depth": partial_depth,
            "path_param": {
                "value": _json_safe(path_value),
                "type": type(path_value).__name__,
            },
            "context_value": context_value,
            "different_worker_thread": current_thread_id != caller_thread_id,
            "invocation_count": state["invocation_count"],
        }
    if "error_message" in spec:
        raise RuntimeError(spec["error_message"])
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(content=spec["response_content"])


async def _async_request_callable_observer_response(
    request: Any, spec: dict[str, Any], state: dict[str, Any]
) -> Any:
    endpoint = state["route_endpoint"]
    partial_depth = 0
    while isinstance(endpoint, functools.partial):
        partial_depth += 1
        endpoint = endpoint.func

    current_loop = asyncio.get_running_loop()
    current_task = asyncio.current_task()
    current_thread_id = threading.get_ident()
    state["invocation_count"] += 1
    path_value = request.path_params[spec["path_parameter"]]
    observation = {
        "route_endpoint_type": type(state["route_endpoint"]).__name__,
        "partial_depth": partial_depth,
        "request_argument_type": (f"{type(request).__module__}.{type(request).__qualname__}"),
        "path_param": {
            "value": _json_safe(path_value),
            "type": type(path_value).__name__,
        },
        "same_event_loop": current_loop is state["caller_event_loop"],
        "same_request_task": current_task is state["caller_task"],
        "same_thread": current_thread_id == state["caller_thread_id"],
        "invocation_count": state["invocation_count"],
    }
    state["observation"] = observation
    state["request_observations"].append(observation)
    if "error_message" in spec:
        raise RuntimeError(spec["error_message"])
    from starlette.responses import PlainTextResponse

    return PlainTextResponse(content=spec["response_content"])


def _sync_request_cancellation_response(
    _request: Any, spec: dict[str, Any], state: dict[str, Any]
) -> Any:
    with state["lock"]:
        state["worker_thread_id"] = threading.get_ident()
        state["invocation_count"] += 1
        state["event_trace"].append("worker-entered")
    state["worker_entered"].set()
    state["event_loop"].call_soon_threadsafe(state["worker_entered_async"].set)
    try:
        state["worker_release"].wait()
        from starlette.responses import PlainTextResponse

        response = PlainTextResponse(content=spec["response_content"])
        with state["lock"]:
            state["response_constructed"] = True
        return response
    finally:
        with state["lock"]:
            state["worker_finalizer_ran"] = True
            state["event_trace"].append("worker-finalizer-ran")
            state["worker_completed"].set()
            state["event_trace"].append("worker-completed")
        state["event_loop"].call_soon_threadsafe(state["worker_completed_async"].set)


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


def _materialize_application_middleware(middleware_specs: Any) -> list[Any]:
    from starlette.authentication import (
        AuthCredentials,
        AuthenticationError,
        SimpleUser,
    )
    from starlette.middleware import Middleware
    from starlette.middleware.authentication import AuthenticationMiddleware
    from starlette.middleware.base import BaseHTTPMiddleware

    if not isinstance(middleware_specs, list):
        raise ValueError("application middleware input must be an array")

    class CopyScopeMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await self.app(dict(scope), receive, send)

    class ReadBeforeApplicationMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            await receive()
            await self.app(scope, receive, send)

    class AppendResponseHeaderMiddleware:
        def __init__(self, app: Any, *, name: str) -> None:
            self.app = app
            self.response_header = (f"X-{name}".encode("ascii"), b"true")

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            async def modified_send(message: Any) -> None:
                if message["type"] == "http.response.start":
                    message["headers"].append(self.response_header)
                await send(message)

            await self.app(scope, receive, modified_send)

    async def base_http_passthrough(request: Any, call_next: Any) -> Any:
        return await call_next(request)

    async def base_http_read_body(request: Any, call_next: Any) -> Any:
        await request.body()
        return await call_next(request)

    class BasicAuthBackend:
        async def authenticate(self, connection: Any) -> Any:
            if "Authorization" not in connection.headers:
                return None

            auth = connection.headers["Authorization"]
            try:
                scheme, credentials = auth.split()
                if scheme.casefold() != "basic":
                    return None
                decoded = base64.b64decode(credentials).decode("ascii")
            except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
                raise AuthenticationError("Invalid basic auth credentials") from exc

            username, _, _password = decoded.partition(":")
            return AuthCredentials(["authenticated"]), SimpleUser(username)

    middleware = []
    for index, raw_spec in enumerate(middleware_specs):
        if isinstance(raw_spec, dict) and raw_spec.get("kind") == "append-response-header":
            spec = _strict_object(
                raw_spec,
                {"kind", "name"},
                f"application middleware[{index}]",
            )
        else:
            spec = _strict_object(raw_spec, {"kind"}, f"application middleware[{index}]")
        if spec["kind"] == "copy-scope":
            middleware.append(Middleware(CopyScopeMiddleware))
        elif spec["kind"] == "read-before-application":
            middleware.append(Middleware(ReadBeforeApplicationMiddleware))
        elif spec["kind"] == "base-http-passthrough":
            middleware.append(Middleware(BaseHTTPMiddleware, dispatch=base_http_passthrough))
        elif spec["kind"] == "base-http-read-body":
            middleware.append(Middleware(BaseHTTPMiddleware, dispatch=base_http_read_body))
        elif spec["kind"] == "authentication-basic":
            middleware.append(Middleware(AuthenticationMiddleware, backend=BasicAuthBackend()))
        elif spec["kind"] == "append-response-header":
            middleware.append(Middleware(AppendResponseHeaderMiddleware, name=spec["name"]))
        else:
            raise ValueError(f"unsupported application middleware action: {spec['kind']!r}")
    return middleware


def _routes_have_local_middleware(routes: Any) -> bool:
    if not isinstance(routes, list):
        return False
    return any(
        isinstance(route, dict)
        and (
            "middleware" in route
            or _routes_have_local_middleware(route.get("routes"))
            or (
                isinstance(route.get("app"), dict) and _routes_have_local_middleware([route["app"]])
            )
        )
        for route in routes
    )


def _has_mounted_app_exception_route(routes: Any) -> bool:
    return (
        isinstance(routes, list)
        and len(routes) == 1
        and isinstance(routes[0], dict)
        and routes[0].get("kind") == "mount"
        and routes[0].get("path") == "/sub"
        and isinstance(routes[0].get("app"), dict)
        and routes[0]["app"].get("kind") == "starlette-app"
    )


def _materialize_application(
    app_spec: dict[str, Any],
) -> tuple[Any, list[str], list[dict[str, Any]], Any, list[dict[str, Any]]]:
    from starlette.applications import Starlette
    from starlette.exceptions import HTTPException, WebSocketException
    from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
    from starlette.routing import Mount, Route, WebSocketRoute

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

    if any(
        isinstance(route, dict) and route.get("kind") == "mount" for route in app_spec["routes"]
    ) or any(isinstance(route, dict) and "middleware" in route for route in app_spec["routes"]):
        from starlette.responses import Response

        def make_middleware_route(route_spec: dict[str, Any]) -> Any:
            kind = route_spec["kind"]
            if kind == "starlette-app":
                return Starlette(
                    routes=[make_middleware_route(child) for child in route_spec["routes"]]
                )
            if kind == "http-route":
                endpoint_spec = route_spec["endpoint"]
                if endpoint_spec["kind"] == "plain-response":

                    def endpoint(_request: Any) -> Any:
                        return Response(
                            endpoint_spec["content"], media_type=endpoint_spec["media_type"]
                        )

                elif endpoint_spec["kind"] == "scope-assert-empty-response":

                    def endpoint(request: Any) -> Any:
                        if (
                            request.scope.get(endpoint_spec["scope_key"])
                            is not endpoint_spec["scope_value"]
                        ):
                            raise AssertionError("route middleware scope marker was not set")
                        return Response()

                elif endpoint_spec["kind"] == "sync-http-exception":

                    def endpoint(_request: Any) -> Any:
                        raise HTTPException(
                            status_code=endpoint_spec["status_code"],
                            detail=endpoint_spec["detail"],
                        )

                elif endpoint_spec["kind"] == "raise-runtime-error":

                    def endpoint(_request: Any) -> None:
                        raise Exception(endpoint_spec["message"])

                else:
                    raise ValueError("route-middleware endpoint uses an unsupported input kind")
                middleware = _build_reverse_route_middleware(route_spec.get("middleware", []))
                return Route(
                    route_spec["path"],
                    endpoint=endpoint,
                    methods=route_spec["methods"],
                    name=route_spec.get("name"),
                    middleware=middleware,
                )
            if kind != "mount":
                raise ValueError("route-middleware node must be an HTTP route or Mount")
            middleware = _build_reverse_route_middleware(route_spec.get("middleware", []))
            if "app" in route_spec:
                return Mount(
                    route_spec["path"],
                    app=make_middleware_route(route_spec["app"]),
                    middleware=middleware,
                )
            return Mount(
                route_spec["path"],
                routes=[make_middleware_route(child) for child in route_spec["routes"]],
                middleware=middleware,
            )

        route_objects = [make_middleware_route(route) for route in app_spec["routes"]]
        app = Starlette(
            debug=app_spec["debug"],
            routes=route_objects,
            middleware=_materialize_application_middleware(app_spec["middleware"]),
            exception_handlers=exception_handlers,
            lifespan=lifespan,
            max_body_size=app_spec["max_body_size"],
        )
        return app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states

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
            elif endpoint_spec["kind"] == "authentication-required-websocket":
                _strict_object(
                    endpoint_spec,
                    {"kind", "form", "required_scopes"},
                    "authentication-required WebSocket endpoint",
                )
                from starlette.authentication import requires

                form = endpoint_spec["form"]
                required_scopes = endpoint_spec["required_scopes"]

                async def send_authenticated_websocket_payload(
                    websocket: Any, additional: str | None = None
                ) -> None:
                    payload = {
                        "authenticated": websocket.user.is_authenticated,
                        "user": websocket.user.display_name,
                    }
                    if additional is not None:
                        payload["additional"] = additional
                    await websocket.accept()
                    await websocket.send_json(payload)

                if form == "plain":

                    async def endpoint(websocket: Any) -> None:
                        await send_authenticated_websocket_payload(websocket)

                    websocket_endpoint = requires(required_scopes)(endpoint)
                elif form == "decorated":

                    async def protected_endpoint(websocket: Any, additional: str) -> None:
                        await send_authenticated_websocket_payload(websocket, additional)

                    protected = requires(required_scopes)(protected_endpoint)

                    def make_injected_endpoint(protected_callable: Any) -> Any:
                        async def endpoint(websocket: Any) -> None:
                            await protected_callable(websocket=websocket, additional="payload")

                        return endpoint

                    websocket_endpoint = make_injected_endpoint(protected)
                else:
                    raise ValueError(
                        "authentication-required WebSocket endpoint has an unsupported form"
                    )
            else:
                raise ValueError("WebSocket route endpoint uses an unsupported input kind")
            route_objects.append(WebSocketRoute(route["path"], websocket_endpoint))
            continue
        if (
            frozenset(route)
            not in {
                frozenset({"kind", "path", "methods", "endpoint"}),
                frozenset({"kind", "path", "methods", "endpoint", "max_body_size"}),
            }
            or route["kind"] != "http-route"
        ):
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
        elif response_spec["kind"] == "sync-plain-text-response":
            _strict_object(
                response_spec,
                {"kind", "content"},
                "synchronous plain-text response endpoint",
            )
            sync_state = {
                "caller_thread_id": None,
                "invocation_count": 0,
                "observation": None,
                "lock": threading.Lock(),
            }
            sync_endpoint_states.append(sync_state)

            def make_sync_endpoint(spec: dict[str, Any], state: dict[str, Any]) -> Any:
                def endpoint(_request: Any) -> Any:
                    caller_thread_id = state["caller_thread_id"]
                    if caller_thread_id is None:
                        raise RuntimeError(
                            "sync route endpoint ran without a caller thread identity"
                        )
                    with state["lock"]:
                        state["invocation_count"] += 1
                        state["observation"] = {
                            "different_worker_thread": threading.get_ident() != caller_thread_id,
                            "invocation_count": state["invocation_count"],
                        }
                    return PlainTextResponse(spec["content"])

                return endpoint

            route_endpoint = make_sync_endpoint(response_spec, sync_state)
        elif response_spec["kind"] == "request-body-echo":
            _strict_object(response_spec, {"kind"}, "request-body echo endpoint")

            async def route_endpoint(request: Any) -> Any:
                return Response(await request.body())
        elif response_spec["kind"] == "request-form-consumer":
            _strict_object(
                response_spec,
                {"kind", "response_content"},
                "request form-consuming endpoint",
            )
            response_content = response_spec["response_content"]

            async def route_endpoint(request: Any, content: str = response_content) -> Any:
                async with request.form():
                    return PlainTextResponse(content)
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
        elif response_spec["kind"] == "authentication-user-interface":
            _strict_object(
                response_spec,
                {"kind"},
                "authentication user-interface endpoint",
            )

            async def route_endpoint(request: Any) -> Any:
                return JSONResponse(
                    {
                        "authenticated": request.user.is_authenticated,
                        "user": request.user.display_name,
                        "user_type": type(request.user).__name__,
                        "auth_scopes": request.auth.scopes,
                    }
                )
        elif response_spec["kind"] == "authentication-login-next-redirect":
            _strict_object(
                response_spec,
                {
                    "kind",
                    "method",
                    "query_parameter",
                    "fallback_url",
                    "unauthenticated_content",
                },
                "authentication login redirect endpoint",
            )

            def make_login_redirect_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    if request.method == spec["method"] and request.user.is_authenticated:
                        next_url = request.query_params.get(spec["query_parameter"])
                        if next_url:
                            return RedirectResponse(next_url)
                        return RedirectResponse(spec["fallback_url"])
                    return PlainTextResponse(spec["unauthenticated_content"])

                return endpoint

            route_endpoint = make_login_redirect_endpoint(response_spec)
        elif response_spec["kind"] == "authentication-required-route":
            _strict_object(
                response_spec,
                {"kind", "form", "required_scopes"},
                "authentication-required route endpoint",
            )
            from starlette.authentication import requires
            from starlette.endpoints import HTTPEndpoint

            form = response_spec["form"]
            required_scopes = response_spec["required_scopes"]

            def authentication_payload(request: Any, additional: str | None = None) -> Any:
                payload = {
                    "authenticated": request.user.is_authenticated,
                    "user": request.user.display_name,
                }
                if additional is not None:
                    payload["additional"] = additional
                return JSONResponse(payload)

            if form == "class":

                class Dashboard(HTTPEndpoint):
                    @requires(required_scopes)
                    def get(self, request: Any) -> Any:
                        return authentication_payload(request)

                route_endpoint = Dashboard
            elif form == "async":

                async def endpoint(request: Any) -> Any:
                    return authentication_payload(request)

                route_endpoint = requires(required_scopes)(endpoint)
            elif form == "sync":

                def endpoint(request: Any) -> Any:
                    return authentication_payload(request)

                route_endpoint = requires(required_scopes)(endpoint)
            elif form == "decorated-async":

                async def protected_endpoint(request: Any, additional: str) -> Any:
                    return authentication_payload(request, additional)

                protected = requires(required_scopes)(protected_endpoint)

                def make_injected_async_endpoint(protected_callable: Any) -> Any:
                    async def endpoint(request: Any) -> Any:
                        return await protected_callable(request=request, additional="payload")

                    return endpoint

                route_endpoint = make_injected_async_endpoint(protected)
            elif form == "decorated-sync":

                def protected_endpoint(request: Any, additional: str) -> Any:
                    return authentication_payload(request, additional)

                protected = requires(required_scopes)(protected_endpoint)

                def make_injected_sync_endpoint(protected_callable: Any) -> Any:
                    def endpoint(request: Any) -> Any:
                        return protected_callable(request=request, additional="payload")

                    return endpoint

                route_endpoint = make_injected_sync_endpoint(protected)
            else:
                raise ValueError("authentication-required endpoint has an unsupported form")
        elif response_spec["kind"] == "request-cookies-observer":
            _strict_object(
                response_spec,
                {"kind", "probe", "response_content", "status_code", "media_type"},
                "request cookies observer endpoint",
            )
            probe = response_spec["probe"]
            if not isinstance(probe, dict) or not isinstance(probe.get("kind"), str):
                raise ValueError("request cookies observer probe must be an object with a kind")
            if probe["kind"] == "items":
                _strict_object(probe, {"kind"}, "request cookies items probe")
            elif probe["kind"] == "mapping-actions":
                _strict_object(probe, {"kind", "actions"}, "request cookies mapping probe")
                actions = probe["actions"]
                if not isinstance(actions, list):
                    raise ValueError("request cookies mapping actions must be a list")
                for action in actions:
                    if not isinstance(action, dict) or action.get("operation") not in {
                        "set",
                        "delete",
                    }:
                        raise ValueError("request cookies mapping action must be set or delete")
                    action_fields = (
                        {"operation", "key", "value"}
                        if action["operation"] == "set"
                        else {"operation", "key"}
                    )
                    _strict_object(action, action_fields, "request cookies mapping action")
                    if not isinstance(action["key"], str) or (
                        action["operation"] == "set" and not isinstance(action["value"], str)
                    ):
                        raise ValueError("request cookies mapping action fields must be strings")
            else:
                raise ValueError("unsupported request cookies observer probe kind")

            def make_request_cookies_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    cookies = request.cookies
                    if spec["probe"]["kind"] == "items":
                        request_observations.append(
                            {"cookies": [[key, value] for key, value in cookies.items()]}
                        )
                    else:
                        initial_items = [[key, value] for key, value in cookies.items()]
                        same_object = cookies is request.cookies
                        for action in spec["probe"]["actions"]:
                            if action["operation"] == "set":
                                cookies[action["key"]] = action["value"]
                            else:
                                del cookies[action["key"]]
                        request_observations.append(
                            {
                                "is_builtin_dict": type(cookies) is dict,
                                "same_object": same_object,
                                "initial_items": initial_items,
                                "final_items": [[key, value] for key, value in cookies.items()],
                                "same_after_actions": cookies is request.cookies,
                            }
                        )
                    return PlainTextResponse(
                        content=spec["response_content"],
                        status_code=spec["status_code"],
                        media_type=spec["media_type"],
                    )

                return endpoint

            route_endpoint = make_request_cookies_endpoint(response_spec)
        elif response_spec["kind"] == "async-request-callable-observer":
            callable_fields = {
                "kind",
                "callable_kind",
                "path_parameter",
                "response_content",
            }
            if "error_message" in response_spec:
                callable_fields.add("error_message")
            _strict_object(
                response_spec,
                callable_fields,
                "async request callable observer endpoint",
            )
            if "error_message" in response_spec and not isinstance(
                response_spec["error_message"], str
            ):
                raise ValueError("async request callable error_message must be a string")
            async_callable_state: dict[str, Any] = {
                "caller_event_loop": None,
                "caller_task": None,
                "caller_thread_id": None,
                "invocation_count": 0,
                "observation": None,
                "request_observations": request_observations,
            }
            callable_kind = response_spec["callable_kind"]
            if callable_kind == "function":

                def make_async_function_endpoint(
                    spec: dict[str, Any], state: dict[str, Any]
                ) -> Any:
                    async def endpoint(request: Any) -> Any:
                        return await _async_request_callable_observer_response(request, spec, state)

                    return endpoint

                route_endpoint = make_async_function_endpoint(response_spec, async_callable_state)
                route_endpoint._parity_async_request_callable_state = async_callable_state
            elif callable_kind == "bound_method":

                class AsyncBoundMethodEndpoint:
                    def __init__(self, spec: dict[str, Any], state: dict[str, Any]) -> None:
                        self.spec = spec
                        self.state = state

                    async def endpoint(self, request: Any) -> Any:
                        return await _async_request_callable_observer_response(
                            request, self.spec, self.state
                        )

                route_endpoint = AsyncBoundMethodEndpoint(
                    response_spec, async_callable_state
                ).endpoint
                route_endpoint.__func__._parity_async_request_callable_state = async_callable_state
            elif callable_kind == "partial":
                route_endpoint = functools.partial(
                    _async_request_callable_observer_response,
                    spec=response_spec,
                    state=async_callable_state,
                )
                route_endpoint._parity_async_request_callable_state = async_callable_state
            elif callable_kind == "nested_partial":
                route_endpoint = functools.partial(
                    functools.partial(
                        _async_request_callable_observer_response,
                        spec=response_spec,
                    ),
                    state=async_callable_state,
                )
                route_endpoint._parity_async_request_callable_state = async_callable_state
            else:
                raise ValueError(f"unsupported async endpoint callable kind: {callable_kind!r}")
            async_callable_state["route_endpoint"] = route_endpoint
        elif response_spec["kind"] == "request-connection-property":
            if set(response_spec) != {"kind", "property"}:
                raise ValueError("request connection-property input does not match its schema")

            def make_request_connection_property_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    value = getattr(request, spec["property"])
                    if spec["property"] == "app":
                        request_observations.append(
                            {
                                "property": "app",
                                "qualified_type": f"{type(value).__module__}.{type(value).__qualname__}",
                                "same_as_scope_app": value is request.scope["app"],
                            }
                        )
                    else:
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
        elif response_spec["kind"] == "request-state-observer":
            _strict_object(
                response_spec,
                {"kind", "state_key", "state_value", "response_content"},
                "request state observer endpoint",
            )

            def make_request_state_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(request: Any) -> Any:
                    state_missing_before_access = "state" not in request.scope
                    state = request.state
                    setattr(state, spec["state_key"], spec["state_value"])
                    attribute_value = getattr(state, spec["state_key"])
                    mapping_value = state[spec["state_key"]]
                    scope_state = request.scope["state"]
                    request_observations.append(
                        {
                            "state_missing_before_access": state_missing_before_access,
                            "attribute_value": _json_safe(attribute_value),
                            "mapping_value": _json_safe(mapping_value),
                            "scope_mapping_value": _json_safe(scope_state[spec["state_key"]]),
                            "same_cached_state": request.state is state,
                            "scope_state_type": type(scope_state).__name__,
                        }
                    )
                    return PlainTextResponse(content=spec["response_content"])

                return endpoint

            route_endpoint = make_request_state_endpoint(response_spec)
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
            callable_fields = {
                "kind",
                "callable_kind",
                "path_parameter",
                "context_var_name",
                "context_value",
                "response_content",
            }
            if "error_message" in response_spec:
                callable_fields.add("error_message")
            _strict_object(
                response_spec,
                callable_fields,
                "sync request observer endpoint",
            )
            if "error_message" in response_spec and not isinstance(
                response_spec["error_message"], str
            ):
                raise ValueError("sync request observer error_message must be a string")
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
            sync_state["route_endpoint"] = route_endpoint
        elif response_spec["kind"] == "sync-request-cancellation-observer":
            _strict_object(
                response_spec,
                {"kind", "response_content"},
                "sync request cancellation observer endpoint",
            )
            sync_state: dict[str, Any] = {
                "caller_thread_id": None,
                "worker_thread_id": None,
                "invocation_count": 0,
                "observation": None,
                "lock": threading.Lock(),
                "event_loop": None,
                "worker_entered": threading.Event(),
                "worker_release": threading.Event(),
                "worker_completed": threading.Event(),
                "worker_entered_async": None,
                "worker_completed_async": None,
                "worker_finalizer_ran": False,
                "response_constructed": False,
                "event_trace": [],
            }
            sync_endpoint_states.append(sync_state)

            def make_cancellation_endpoint(spec: dict[str, Any], state: dict[str, Any]) -> Any:
                def endpoint(request: Any) -> Any:
                    return _sync_request_cancellation_response(request, spec, state)

                return endpoint

            route_endpoint = make_cancellation_endpoint(response_spec, sync_state)
            route_endpoint._parity_sync_cancellation_state = sync_state
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
                def __init__(self, content: str, observations: list[dict[str, Any]]) -> None:
                    self.content = content
                    self.observations = observations

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    self.observations.append(
                        {
                            "route_endpoint_type": type(self).__name__,
                            "scope_type": type(scope).__name__,
                            "scope_type_value": scope.get("type"),
                            "path": scope.get("path"),
                            "receive_callable": callable(receive),
                            "send_callable": callable(send),
                        }
                    )
                    response = PlainTextResponse(content=self.content)
                    await response(scope, receive, send)

            route_endpoint = ASGICallableInstanceObserver(
                response_spec["response_content"], request_observations
            )
        elif response_spec["kind"] == "async-call-boundary-observer":
            _strict_object(
                response_spec,
                {"kind"},
                "async call-boundary observer endpoint",
            )
            boundary_state: dict[str, Any] = {
                "entered": None,
                "endpoint_loop": None,
                "endpoint_task": None,
                "endpoint_thread_id": None,
                "finalizer_ran": False,
                "cancellation_class": None,
            }

            class AsyncCallBoundaryObserver:
                def __init__(self, state: dict[str, Any]) -> None:
                    self.boundary_state = state

                async def __call__(self, _scope: Any, _receive: Any, _send: Any) -> None:
                    self.boundary_state["endpoint_loop"] = asyncio.get_running_loop()
                    self.boundary_state["endpoint_task"] = asyncio.current_task()
                    self.boundary_state["endpoint_thread_id"] = threading.get_ident()
                    self.boundary_state["entered"].set()
                    try:
                        await asyncio.Future()
                    except asyncio.CancelledError as exc:
                        self.boundary_state["cancellation_class"] = (
                            f"{type(exc).__module__}.{type(exc).__qualname__}"
                        )
                        raise
                    finally:
                        self.boundary_state["finalizer_ran"] = True

            route_endpoint = AsyncCallBoundaryObserver(boundary_state)
            route_endpoint._parity_async_boundary_state = boundary_state
        elif response_spec["kind"] == "asgi-callable-action-sequence":
            _strict_object(
                response_spec,
                {"kind", "actions"},
                "ASGI callable action-sequence endpoint",
            )
            if not isinstance(response_spec["actions"], list) or not response_spec["actions"]:
                raise ValueError("ASGI callable action sequence must be a non-empty array")

            class ASGICallableActionSequence:
                def __init__(
                    self, actions: list[dict[str, Any]], observations: list[dict[str, Any]]
                ) -> None:
                    self.actions = actions
                    self.observations = observations

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    self.observations.append(
                        {
                            "route_endpoint_type": type(self).__name__,
                            "scope_type": type(scope).__name__,
                            "scope_type_value": scope.get("type"),
                            "path": scope.get("path"),
                            "receive_callable": callable(receive),
                            "send_callable": callable(send),
                        }
                    )
                    for index, action in enumerate(self.actions):
                        action_kind, value = _materialize_asgi_action(action, index)
                        if action_kind == "send":
                            await send(value)
                        else:
                            raise value

            route_endpoint = ASGICallableActionSequence(
                response_spec["actions"], request_observations
            )
        else:
            raise ValueError(f"unsupported endpoint kind: {response_spec['kind']!r}")
        route_objects.append(
            Route(
                route["path"],
                route_endpoint,
                methods=route["methods"],
                max_body_size=route.get("max_body_size"),
            )
        )
    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        app = Starlette(
            debug=app_spec["debug"],
            routes=route_objects,
            middleware=_materialize_application_middleware(app_spec["middleware"]),
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
    capture_dispatch_error_as_observation: bool = False,
    cancel_after_endpoint_entry: bool = False,
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
    captured_exception: BaseException | None = None
    async_endpoint_observations: dict[str, Any] | None = None
    async_request_callable_state = getattr(
        route_endpoint, "_parity_async_request_callable_state", None
    )
    if async_request_callable_state is None:
        async_request_callable_state = getattr(
            getattr(route_endpoint, "__func__", None),
            "_parity_async_request_callable_state",
            None,
        )
    boundary_state = getattr(route_endpoint, "_parity_async_boundary_state", None)
    sync_cancellation_state = getattr(route_endpoint, "_parity_sync_cancellation_state", None)
    try:
        for state in sync_endpoint_states or []:
            state["caller_thread_id"] = threading.get_ident()
            if "context_var" in state:
                token = state["context_var"].set(state["context_value"])
                context_tokens.append((state, token))
        if async_request_callable_state is not None:
            async_request_callable_state["caller_event_loop"] = asyncio.get_running_loop()
            async_request_callable_state["caller_task"] = asyncio.current_task()
            async_request_callable_state["caller_thread_id"] = threading.get_ident()
        if cancel_after_endpoint_entry:
            server_loop = asyncio.get_running_loop()
            server_thread_id = threading.get_ident()
            if boundary_state is not None:
                boundary_state["entered"] = asyncio.Event()
                server_task = asyncio.create_task(app(scope, receive, send))
                await boundary_state["entered"].wait()
                cancel_requested = server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError as exc:
                    captured_exception = exc
                async_endpoint_observations = {
                    "endpoint_entered": boundary_state["endpoint_task"] is not None,
                    "endpoint_finalizer_ran": boundary_state["finalizer_ran"],
                    "endpoint_cancellation_class": boundary_state["cancellation_class"],
                    "same_event_loop": boundary_state["endpoint_loop"] is server_loop,
                    "same_request_task": boundary_state["endpoint_task"] is server_task,
                    "same_thread": boundary_state["endpoint_thread_id"] == server_thread_id,
                    "server_task_cancel_requested": cancel_requested,
                    "server_task_cancelled": server_task.cancelled(),
                }
            elif sync_cancellation_state is not None:
                state = sync_cancellation_state
                state["event_loop"] = server_loop
                state["worker_entered_async"] = asyncio.Event()
                state["worker_completed_async"] = asyncio.Event()
                server_task = asyncio.create_task(app(scope, receive, send))
                cancel_requested = False
                request_task_done_before_worker_release = None
                try:
                    await asyncio.wait_for(state["worker_entered_async"].wait(), timeout=15)
                    cancel_requested = server_task.cancel()
                    with state["lock"]:
                        state["event_trace"].append("request-cancel-requested")
                    request_task_done_before_worker_release = server_task.done()
                    with state["lock"]:
                        state["event_trace"].append("worker-released")
                        state["worker_release"].set()
                    try:
                        await asyncio.wait_for(server_task, timeout=15)
                    except asyncio.CancelledError as exc:
                        captured_exception = exc
                        with state["lock"]:
                            state["event_trace"].append("request-task-cancelled")
                    except Exception as exc:
                        if not capture_dispatch_error:
                            raise
                        captured_exception = exc
                        with state["lock"]:
                            state["event_trace"].append("request-task-raised")
                    else:
                        with state["lock"]:
                            state["event_trace"].append("request-task-completed")
                    await asyncio.wait_for(state["worker_completed_async"].wait(), timeout=15)
                finally:
                    state["worker_release"].set()
                    if not server_task.done():
                        server_task.cancel()
                        try:
                            await asyncio.wait_for(server_task, timeout=15)
                        except asyncio.CancelledError:
                            pass
                with state["lock"]:
                    state["observation"] = {
                        "worker_entered": state["worker_entered"].is_set(),
                        "different_worker_thread": state["worker_thread_id"] != server_thread_id,
                        "invocation_count": state["invocation_count"],
                        "worker_completed": state["worker_completed"].is_set(),
                        "worker_finalizer_ran": state["worker_finalizer_ran"],
                        "response_constructed": state["response_constructed"],
                        "request_task_cancel_requested": cancel_requested,
                        "request_task_done_before_worker_release": (
                            request_task_done_before_worker_release
                        ),
                        "request_task_cancelled": server_task.cancelled(),
                        "request_task_terminal_error_class": (
                            f"{type(captured_exception).__module__}."
                            f"{type(captured_exception).__qualname__}"
                            if captured_exception is not None
                            else None
                        ),
                        "event_trace": list(state["event_trace"]),
                    }
            else:
                raise RuntimeError("cancellation schedule requires a declared endpoint observer")
        else:
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
    if (
        start is None
        and scope["type"] not in {"lifespan", "websocket"}
        and async_endpoint_observations is None
        and sync_cancellation_state is None
    ):
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
                "async_endpoint_observations": async_endpoint_observations,
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
                "async_endpoint_observations",
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
        result["sync_endpoint_observations"] = _observed_sync_endpoint(sync_endpoint_states or [])
        if captured_exception is not None and capture_dispatch_error_as_observation:
            return _CapturedDispatchError(
                error=_dispatch_error(captured_exception),
                partial_value=result,
            )
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
                expected_body_keys = {"type", "body_base64"}
                if "more_body" in spec:
                    expected_body_keys.add("more_body")
                _strict_object(spec, expected_body_keys, f"inner response message[{index}]")
                message = {
                    "type": message_type,
                    "body": _decode_b64(spec["body_base64"], "inner response body"),
                }
                if "more_body" in spec:
                    message["more_body"] = spec["more_body"]
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


def _materialize_gzip_middleware(arguments: dict[str, Any], *, responder: bool = False) -> Any:
    from starlette.middleware.gzip import GZipMiddleware, GZipResponder

    response_app = _materialize_asgi_sequence_app(arguments["app"])
    constructor_arguments: dict[str, Any] = {
        name: arguments[name]
        for name in ("minimum_size", "compresslevel", "thread_minimum_size")
        if name in arguments
    }
    if "exclude_content_types" in arguments:
        constructor_arguments["exclude_content_types"] = tuple(arguments["exclude_content_types"])

    middleware_type = GZipResponder if responder else GZipMiddleware
    return middleware_type(response_app, **constructor_arguments)


def _run_gzip_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    responder = case["surface"] == "starlette.middleware.gzip.GZipResponder"
    instance_step = "responder" if responder else "middleware"
    if (
        len(steps) != 2
        or [step.get("step_id") for step in steps] != [instance_step, "dispatch"]
        or [step.get("operation") for step in steps] != ["__init__", "__call__"]
        or any(step.get("surface") != case["surface"] for step in steps)
        or steps[0].get("receiver") is not None
        or steps[1].get("receiver") != {"kind": "binding", "step_id": instance_step}
    ):
        raise ValueError("GZip cases must construct then dispatch the declared ASGI callable")
    if case["execution_schedule"] != ["dispatch"] or case["observations"] != ["dispatch"]:
        raise ValueError("GZipMiddleware cases must observe one dispatch step")

    constructor_arguments = _literal_arguments(
        steps[0],
        {"app", "minimum_size", "compresslevel", "thread_minimum_size", "exclude_content_types"},
        "GZip constructor",
        optional={"minimum_size", "compresslevel", "thread_minimum_size", "exclude_content_types"},
    )
    if responder and "minimum_size" not in constructor_arguments:
        raise ValueError("GZipResponder constructor requires minimum_size")
    dispatch_arguments = _literal_arguments(steps[1], {"scope", "receive", "send"}, "GZip dispatch")
    middleware = _materialize_gzip_middleware(constructor_arguments, responder=responder)
    value = asyncio.run(_invoke(middleware, dispatch_arguments, [], [], None, False))
    selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": selected}],
    }


def _materialize_wsgi_app(spec: dict[str, Any]) -> Any:
    caller_thread_id = threading.get_ident()
    kind = spec["kind"]

    def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        if kind == "wsgi-response":
            start_response(spec["status"], [tuple(pair) for pair in spec["headers"]])
            return [base64.b64decode(chunk, validate=True) for chunk in spec["chunks_base64"]]
        if kind == "wsgi-echo-body":
            start_response(spec["status"], [tuple(pair) for pair in spec["headers"]])
            return [environ["wsgi.input"].read()]
        if kind == "wsgi-environ-report":
            values: dict[str, Any] = {}
            for key in spec["keys"]:
                if key == "wsgi.input":
                    values[key] = base64.b64encode(environ[key].read()).decode("ascii")
                elif key == "wsgi.errors":
                    values[key] = environ[key] is sys.stdout
                else:
                    values[key] = environ[key]
            if spec["include_worker_thread"]:
                values["worker_thread"] = threading.get_ident() != caller_thread_id
            start_response(spec["status"], [tuple(pair) for pair in spec["headers"]])
            return [json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")]
        if kind == "wsgi-raise-before-start":
            raise RuntimeError(spec["message"])
        if kind == "wsgi-exc-info-rethrow":
            try:
                raise RuntimeError(spec["message"])
            except RuntimeError:
                start_response(
                    spec["status"],
                    [tuple(pair) for pair in spec["headers"]],
                    sys.exc_info(),
                )
            return [base64.b64decode(spec["body_base64"], validate=True)]
        raise ValueError(f"unsupported input-defined WSGI app kind: {kind!r}")

    return app


def _run_wsgi_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.middleware.wsgi import WSGIMiddleware

    steps = case["steps"]
    if (
        len(steps) != 2
        or [step.get("step_id") for step in steps] != ["middleware", "dispatch"]
        or [step.get("operation") for step in steps] != ["__init__", "__call__"]
        or any(step.get("surface") != case["surface"] for step in steps)
        or steps[0].get("receiver") is not None
        or steps[1].get("receiver") != {"kind": "binding", "step_id": "middleware"}
    ):
        raise ValueError("WSGIMiddleware cases must construct then dispatch the public middleware")
    if case["execution_schedule"] != ["dispatch"] or case["observations"] != ["dispatch"]:
        raise ValueError("WSGIMiddleware cases must observe one dispatch step")

    constructor_arguments = _literal_arguments(steps[0], {"app"}, "WSGIMiddleware constructor")
    dispatch_arguments = _literal_arguments(
        steps[1], {"scope", "receive", "send"}, "WSGIMiddleware dispatch"
    )
    middleware = WSGIMiddleware(_materialize_wsgi_app(constructor_arguments["app"]))
    scope = _make_scope(dispatch_arguments["scope"])
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

    captured_error: dict[str, Any] | None = None
    try:
        asyncio.run(middleware(scope, receive, send))
    except Exception as exc:
        captured_error = _dispatch_error(exc)

    events = [_canonical_message(message) for message in sent]
    body = b"".join(
        base64.b64decode(event["body"]["data"])
        for event in events
        if event["type"] == "http.response.body"
    )
    value = {
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "asgi_events": events,
        "received_message_count": received,
        "dispatch_error": captured_error,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": value}],
    }


def _materialize_protocol_middleware(
    surface: str,
    arguments: dict[str, Any],
    downstream_call_trace: list[dict[str, Any]] | None = None,
) -> Any:
    app = _materialize_asgi_sequence_app(arguments["app"])
    if downstream_call_trace is not None:
        downstream_app = app

        async def tracked_app(scope: Any, receive: Any, send: Any) -> None:
            downstream_call_trace.append(
                {
                    "scope_type": scope.get("type"),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                }
            )
            await downstream_app(scope, receive, send)

        app = tracked_app

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


def _materialize_server_error_middleware_app(
    spec: dict[str, Any], app_calls: list[str], app_exceptions: list[BaseException]
) -> Any:
    label = spec["label"]
    if spec["kind"] in {"asgi-response-sequence", "asgi-response-sequence-then-raise"}:
        response_app = _materialize_asgi_sequence_app(
            {"kind": "asgi-response-sequence", "messages": spec["messages"]}
        )

        async def app(scope: Any, receive: Any, send: Any) -> None:
            app_calls.append(label)
            await response_app(scope, receive, send)
            if spec["kind"] == "asgi-response-sequence-then-raise":
                error = RuntimeError(spec["message"])
                app_exceptions.append(error)
                raise error

        return app

    async def app(_scope: Any, _receive: Any, _send: Any) -> None:
        app_calls.append(label)
        error = RuntimeError(spec["message"])
        app_exceptions.append(error)
        raise error

    return app


def _materialize_server_error_middleware_handler(
    spec: dict[str, Any] | None,
    handler_calls: list[str],
    handler_exceptions: list[BaseException],
) -> Any:
    if spec is None:
        return None
    from starlette.responses import JSONResponse

    def record_call(exc: BaseException) -> None:
        handler_calls.append(spec["label"])
        handler_exceptions.append(exc)

    if spec["callable_kind"] == "async":

        async def handler(_request: Any, exc: BaseException) -> Any:
            record_call(exc)
            return JSONResponse(content=spec["content"], status_code=spec["status_code"])

    else:

        def handler(_request: Any, exc: BaseException) -> Any:
            record_call(exc)
            return JSONResponse(content=spec["content"], status_code=spec["status_code"])

    return handler


def _run_server_error_middleware_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.middleware.errors import ServerErrorMiddleware

    constructor = case["constructor"]
    app_calls: list[str] = []
    app_exceptions: list[BaseException] = []
    handler_calls: list[str] = []
    handler_exceptions: list[BaseException] = []

    def materialize_app(spec: dict[str, Any]) -> Any:
        return _materialize_server_error_middleware_app(spec, app_calls, app_exceptions)

    def materialize_handler(spec: dict[str, Any] | None) -> Any:
        return _materialize_server_error_middleware_handler(spec, handler_calls, handler_exceptions)

    app = materialize_app(constructor["app"])
    handler = materialize_handler(constructor["handler"])
    middleware = ServerErrorMiddleware(app, handler=handler, debug=constructor["debug"])
    if case["operation"] == "__init__":
        value = {
            "instance_class": f"{type(middleware).__module__}.{type(middleware).__qualname__}",
            "app_is_input_callable": middleware.app is app,
            "handler_is_input_callable": middleware.handler is handler,
            "debug": middleware.debug,
        }
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [{"step_id": "construct", "status": "ok", "value": value}],
        }

    latest_app = app
    latest_handler = handler
    for assignment in case["assignments"]:
        field = assignment["field"]
        if field == "app":
            latest_app = materialize_app(assignment["value"])
            setattr(middleware, field, latest_app)
        elif field == "handler":
            latest_handler = materialize_handler(assignment["value"])
            setattr(middleware, field, latest_handler)
        else:
            setattr(middleware, field, assignment["value"])

    dispatch = case["dispatch"]
    scope = _make_scope(dispatch["scope"])
    incoming = [_message(message) for message in dispatch["receive"]]
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

    if dispatch["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("ServerErrorMiddleware send input must select the ASGI event collector")
    captured_exception: BaseException | None = None
    try:
        asyncio.run(middleware(scope, receive, send))
    except Exception as exc:
        captured_exception = exc

    events = [_canonical_message(message) for message in sent]
    start = next((event for event in events if event["type"] == "http.response.start"), None)
    body = b"".join(
        base64.b64decode(event["body"]["data"], validate=True)
        for event in events
        if event["type"] == "http.response.body"
    )
    middleware._parity_server_error_handler_calls = handler_calls
    value = {
        "asgi_events": events,
        "response_status": start["status"] if start is not None else None,
        "ordered_repeated_headers": start["headers"] if start is not None else [],
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "selected_app_calls": list(app_calls),
        "selected_handler_calls": list(handler_calls),
        "handler_received_original_exception": [
            any(exc is original for original in app_exceptions) for exc in handler_exceptions
        ],
        "propagated_error": _dispatch_error(captured_exception) if captured_exception else None,
        "propagated_same_app_exception": any(
            captured_exception is original for original in app_exceptions
        ),
        "propagated_same_handler_exception": any(
            captured_exception is handled for handled in handler_exceptions
        ),
        "server_error_observation": _server_error_observation(
            middleware, start, body, captured_exception
        ),
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": value}],
    }


def _run_protocol_middleware_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    constructor_step = steps[0]
    constructor_arguments = _literal_arguments(
        constructor_step,
        set(constructor_step["arguments"]),
        f"{case['surface']} constructor",
    )
    downstream_call_trace: list[dict[str, Any]] = []
    try:
        middleware = _materialize_protocol_middleware(
            case["surface"],
            constructor_arguments,
            downstream_call_trace if case["surface"] == CORS_SURFACE else None,
        )
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
    constructor_probe_observations = [
        {
            "probe_id": probe["probe_id"],
            "attributes": {
                name: _json_safe(getattr(middleware, name)) for name in probe["attributes"]
            },
        }
        for probe in case.get("constructor_probes", [])
    ]
    if case["operation"] == "__init__":
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {"step_id": "construct", "status": "ok", "value": {"constructed": True}}
            ],
        }

    async def invoke_dispatches() -> list[dict[str, Any]]:
        observations = []
        for dispatch_step in steps[1:]:
            trace_start = len(downstream_call_trace)
            dispatch_arguments = _literal_arguments(
                dispatch_step,
                {"scope", "receive", "send"},
                f"{case['surface']} dispatch",
            )
            value = await _invoke(middleware, dispatch_arguments, [], [], None, False)
            selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
            if constructor_probe_observations:
                selected["constructor_probes"] = constructor_probe_observations
            if case["surface"] == CORS_SURFACE:
                selected["downstream_call_trace"] = downstream_call_trace[trace_start:]
            observations.append(
                {"step_id": dispatch_step["step_id"], "status": "ok", "value": selected}
            )
        return observations

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(invoke_dispatches()),
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
    background_task_spec = None
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
        elif route_kind == "plain-text-response-with-async-background-task":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "content", "status_code", "background_task"},
                "BaseHTTPMiddleware async background-task route endpoint",
            )
            if (
                not isinstance(endpoint_spec["content"], str)
                or type(endpoint_spec["status_code"]) is not int
                or not 100 <= endpoint_spec["status_code"] <= 599
            ):
                raise ValueError("BaseHTTPMiddleware background-task route input is invalid")
            background_task_spec = _strict_object(
                endpoint_spec["background_task"],
                {"kind", "delay_seconds"},
                "BaseHTTPMiddleware background task input",
            )
            delay_seconds = background_task_spec["delay_seconds"]
            if (
                background_task_spec["kind"] != "async-delay"
                or type(delay_seconds) not in {int, float}
                or not math.isfinite(delay_seconds)
                or not 0 <= delay_seconds <= 5
            ):
                raise ValueError("BaseHTTPMiddleware async background delay is invalid")
        elif route_kind == "request-body-response":
            _strict_object(endpoint_spec, {"kind"}, "BaseHTTPMiddleware request-body endpoint")
            if "POST" not in route_spec["methods"]:
                raise ValueError("request-body-response routes must accept POST")
        elif route_kind == "request-body-plain-text-response":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "content", "status_code"},
                "BaseHTTPMiddleware request-body plain-text endpoint",
            )
            if (
                "POST" not in route_spec["methods"]
                or not isinstance(endpoint_spec["content"], str)
                or type(endpoint_spec["status_code"]) is not int
                or not 100 <= endpoint_spec["status_code"] <= 599
            ):
                raise ValueError("BaseHTTPMiddleware request-body plain-text route is invalid")
        elif route_kind == "request-stream-plain-text-response":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "content", "status_code"},
                "BaseHTTPMiddleware request-stream plain-text endpoint",
            )
            if (
                "POST" not in route_spec["methods"]
                or not isinstance(endpoint_spec["content"], str)
                or type(endpoint_spec["status_code"]) is not int
                or not 100 <= endpoint_spec["status_code"] <= 599
            ):
                raise ValueError("BaseHTTPMiddleware request-stream plain-text route is invalid")
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
        elif route_kind == "file-response":
            endpoint_spec = _strict_object(
                endpoint_spec,
                {"kind", "file"},
                "BaseHTTPMiddleware FileResponse endpoint",
            )
            file_input = _strict_object(
                endpoint_spec["file"],
                {"name", "contents_base64", "mtime_seconds"},
                "BaseHTTPMiddleware FileResponse file",
            )
            name = file_input["name"]
            if (
                not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or "/" in name
                or "\\" in name
                or Path(name).name != name
                or not isinstance(file_input["contents_base64"], str)
                or type(file_input["mtime_seconds"]) not in {int, float}
                or not math.isfinite(file_input["mtime_seconds"])
            ):
                raise ValueError("BaseHTTPMiddleware FileResponse file input is invalid")
            _decode_b64(file_input["contents_base64"], "BaseHTTPMiddleware FileResponse contents")
        elif route_kind == "raise-exception":
            _strict_object(
                endpoint_spec,
                {"kind", "exception"},
                "BaseHTTPMiddleware raising endpoint",
            )
            exception_value = endpoint_spec["exception"]
            if not isinstance(exception_value, dict) or set(exception_value) not in (
                {"class", "message"},
                {"class", "message", "chain"},
            ):
                raise ValueError("BaseHTTPMiddleware endpoint exception input is invalid")
            exception_spec = exception_value
            if exception_spec["class"] not in {"Exception", "ValueError"} or not isinstance(
                exception_spec["message"], str
            ):
                raise ValueError("BaseHTTPMiddleware endpoint exception input is invalid")
            if "chain" in exception_spec:
                chain = _strict_object(
                    exception_spec["chain"],
                    {"class", "message", "relation"},
                    "BaseHTTPMiddleware endpoint exception chain",
                )
                if (
                    chain["class"] not in {"Exception", "ValueError"}
                    or not isinstance(chain["message"], str)
                    or chain["relation"] not in {"implicit-context", "explicit-cause"}
                ):
                    raise ValueError("BaseHTTPMiddleware endpoint exception chain is invalid")
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
    await_action_kind = None
    returned = None
    saw_header_mutation = False
    saw_disconnect_check = False
    saw_response_body_read = False
    for index, raw_action in enumerate(dispatch_actions):
        context = f"BaseHTTPMiddleware dispatch_actions[{index}]"
        if not isinstance(raw_action, dict) or not isinstance(raw_action.get("kind"), str):
            raise ValueError(f"{context} must be tagged")
        kind = raw_action["kind"]
        if kind == "read-request-body":
            _strict_object(raw_action, {"kind"}, context)
        elif kind == "read-request-stream-next":
            _strict_object(raw_action, {"kind"}, context)
        elif kind == "check-request-is-disconnected":
            _strict_object(raw_action, {"kind"}, context)
            if returned is not None or saw_disconnect_check:
                raise ValueError(
                    "Request.is_disconnected() must be observed at most once before return"
                )
            saw_disconnect_check = True
        elif kind == "capture-request-stream-next":
            _strict_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None:
                raise ValueError(
                    "captured request.stream() reads must follow call_next and precede the dispatch return"
                )
        elif kind == "read-call-next-response-body-next-and-close":
            _strict_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None or saw_response_body_read:
                raise ValueError(
                    "call_next response body read requires one awaited response and must precede return"
                )
            saw_response_body_read = True
        elif kind == "await-call-next":
            _strict_object(raw_action, {"kind"}, context)
            if awaited or returned is not None:
                raise ValueError("BaseHTTPMiddleware dispatch must await call_next once")
            awaited = True
            await_index = index
            await_action_kind = kind
        elif kind == "await-call-next-catching-exception":
            action = _strict_object(
                raw_action,
                {"kind", "exception_class", "response_status_code"},
                context,
            )
            if action["exception_class"] not in {"Exception", "ValueError"}:
                raise ValueError(
                    "BaseHTTPMiddleware caught exception class must be Exception or ValueError"
                )
            if (
                type(action["response_status_code"]) is not int
                or not 100 <= action["response_status_code"] <= 599
            ):
                raise ValueError("caught-exception response status must be between 100 and 599")
            if awaited or returned is not None:
                raise ValueError("BaseHTTPMiddleware dispatch must await call_next once")
            awaited = True
            await_index = index
            await_action_kind = kind
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
        raw_downstream = application["downstream"]
        if not isinstance(raw_downstream, dict) or not isinstance(raw_downstream.get("kind"), str):
            raise ValueError("BaseHTTPMiddleware downstream ASGI input must be tagged")
        if raw_downstream["kind"] == "asgi-sequence":
            downstream_spec = _strict_object(
                raw_downstream,
                {"kind", "steps"},
                "BaseHTTPMiddleware downstream ASGI input",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            steps = downstream_spec["steps"]
            if not isinstance(steps, list) or len(steps) < 3 or steps[-1] != {"kind": "receive"}:
                raise ValueError(
                    "downstream ASGI input requires response sends followed by receive"
                )
            response_started = False
            body_send_count = 0
            for step_index, raw_step in enumerate(steps[:-1]):
                send_step = _strict_object(
                    raw_step,
                    {"kind", "message"},
                    f"downstream ASGI send step[{step_index}]",
                )
                if send_step["kind"] != "send":
                    raise ValueError("downstream ASGI steps before final receive must send")
                message_spec = send_step["message"]
                if not isinstance(message_spec, dict) or not isinstance(
                    message_spec.get("type"), str
                ):
                    raise ValueError("downstream ASGI send message must be tagged")
                if message_spec["type"] == "http.response.start":
                    message = _strict_object(
                        message_spec,
                        {"type", "status", "headers_base64_pairs"},
                        "downstream ASGI response.start input",
                    )
                    if (
                        response_started
                        or step_index != 0
                        or type(message["status"]) is not int
                        or not 100 <= message["status"] <= 599
                        or not isinstance(message["headers_base64_pairs"], list)
                    ):
                        raise ValueError("downstream ASGI must begin with one valid response.start")
                    for header_index, pair in enumerate(message["headers_base64_pairs"]):
                        if not isinstance(pair, list) or len(pair) != 2:
                            raise ValueError(
                                f"downstream response header[{header_index}] is invalid"
                            )
                        for value in pair:
                            if not isinstance(value, str):
                                raise ValueError(
                                    f"downstream response header[{header_index}] is invalid"
                                )
                            _decode_b64(value, f"downstream response header[{header_index}]")
                    response_started = True
                elif message_spec["type"] == "http.response.body":
                    message = _strict_object(
                        message_spec,
                        {"type", "body_base64", "more_body"},
                        "downstream ASGI response.body input",
                    )
                    if not response_started or message["more_body"] is not True:
                        raise ValueError(
                            "downstream ASGI response.body must follow response.start and remain non-terminal"
                        )
                    if not _decode_b64(message["body_base64"], "downstream ASGI response body"):
                        raise ValueError("downstream ASGI response body must be non-empty")
                    body_send_count += 1
                else:
                    raise ValueError("downstream ASGI send message type is unsupported")
            if not response_started or body_send_count < 2:
                raise ValueError(
                    "downstream ASGI receive race requires response.start and at least two body sends"
                )
        elif raw_downstream["kind"] == "stream-until-disconnect-app":
            downstream_spec = _strict_object(
                raw_downstream,
                {"kind", "response_start", "body_message", "guard_timeout_ms"},
                "BaseHTTPMiddleware downstream streaming app",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            response_start = _strict_object(
                downstream_spec["response_start"],
                {"status", "headers_base64_pairs"},
                "downstream streaming response.start input",
            )
            if (
                type(response_start["status"]) is not int
                or not 100 <= response_start["status"] <= 599
                or not isinstance(response_start["headers_base64_pairs"], list)
            ):
                raise ValueError("downstream streaming response.start input is invalid")
            for header_index, pair in enumerate(response_start["headers_base64_pairs"]):
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError(
                        f"downstream streaming response header[{header_index}] is invalid"
                    )
                for value in pair:
                    if not isinstance(value, str):
                        raise ValueError(
                            f"downstream streaming response header[{header_index}] is invalid"
                        )
                    _decode_b64(value, f"downstream streaming response header[{header_index}]")
            body_message = _strict_object(
                downstream_spec["body_message"],
                {"type", "body_base64", "more_body"},
                "downstream streaming response body input",
            )
            if (
                body_message["type"] != "http.response.body"
                or body_message["more_body"] is not True
                or not _decode_b64(body_message["body_base64"], "downstream streaming body")
            ):
                raise ValueError("downstream streaming response body input is invalid")
            if (
                type(downstream_spec["guard_timeout_ms"]) is not int
                or not 1 <= downstream_spec["guard_timeout_ms"] <= 10_000
            ):
                raise ValueError(
                    "downstream streaming guard_timeout_ms must be between 1 and 10000"
                )
        elif raw_downstream["kind"] == "asgi-middleware-stack":
            downstream_spec = _strict_object(
                raw_downstream,
                {"kind", "wrappers", "endpoint"},
                "BaseHTTPMiddleware downstream middleware stack",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            wrappers = downstream_spec["wrappers"]
            if not isinstance(wrappers, list) or len(wrappers) != 1:
                raise ValueError("downstream middleware stack requires one ordered wrapper")
            wrapper = _strict_object(
                wrappers[0],
                {"kind", "repeat_count"},
                "downstream receive wrapper",
            )
            if wrapper["kind"] != "repeat-http-request-body" or (
                type(wrapper["repeat_count"]) is not int or wrapper["repeat_count"] < 2
            ):
                raise ValueError(
                    "downstream receive wrapper must repeat request bodies at least twice"
                )
            endpoint = _strict_object(
                downstream_spec["endpoint"],
                {"kind", "status_code"},
                "downstream ASGI endpoint",
            )
            if (
                endpoint["kind"] != "request-body-empty-response"
                or type(endpoint["status_code"]) is not int
                or not 100 <= endpoint["status_code"] <= 599
            ):
                raise ValueError(
                    "downstream endpoint must read the request body and return an empty response"
                )
        elif raw_downstream["kind"] == "disconnect-polling-app":
            downstream_spec = _strict_object(
                raw_downstream,
                {"kind", "polls", "response"},
                "BaseHTTPMiddleware downstream disconnect-polling app",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            polls = downstream_spec["polls"]
            if not isinstance(polls, list) or len(polls) != 2:
                raise ValueError("disconnect-polling app requires two ordered polls")
            for index, raw_poll in enumerate(polls):
                poll = _strict_object(
                    raw_poll,
                    {"kind"},
                    f"downstream disconnect poll[{index}]",
                )
                if poll["kind"] != "drain-requests-until-disconnect":
                    raise ValueError("downstream polls must drain request messages to disconnect")
            response = _strict_object(
                downstream_spec["response"],
                {"kind", "body_base64", "status_code"},
                "downstream disconnect-polling response",
            )
            if (
                response["kind"] != "bytes-response"
                or type(response["status_code"]) is not int
                or not 100 <= response["status_code"] <= 599
                or not _decode_b64(response["body_base64"], "downstream response body")
            ):
                raise ValueError("downstream polling response input is invalid")
        elif raw_downstream["kind"] == "receive-sequence-app":
            downstream_spec = _strict_object(
                raw_downstream,
                {"kind", "steps", "response"},
                "BaseHTTPMiddleware downstream receive-sequence app",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            steps = downstream_spec["steps"]
            if not isinstance(steps, list) or not steps:
                raise ValueError("downstream receive-sequence app requires receive steps")
            for index, raw_step in enumerate(steps):
                step = _strict_object(raw_step, {"kind"}, f"downstream receive step[{index}]")
                if step["kind"] != "receive":
                    raise ValueError("downstream receive-sequence steps must call receive")
            response = _strict_object(
                downstream_spec["response"],
                {"kind", "status_code"},
                "downstream receive-sequence response",
            )
            if (
                response["kind"] != "empty-response"
                or type(response["status_code"]) is not int
                or not 100 <= response["status_code"] <= 599
            ):
                raise ValueError("downstream receive-sequence response input is invalid")
        else:
            raise ValueError("downstream ASGI input kind is unsupported")

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
    scope_value = request["scope"]
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
    source_sparse_scope = background_task_spec is not None
    if source_sparse_scope:
        scope_spec = _strict_object(
            scope_value,
            {"type", "version", "method", "path"},
            "BaseHTTPMiddleware source-direct HTTP scope",
        )
        if scope_spec != {"type": "http", "version": "3", "method": "GET", "path": "/"}:
            raise ValueError("background task case must preserve the pinned source's direct scope")
    else:
        if isinstance(scope_value, dict) and "extensions" in scope_value:
            scope_keys.add("extensions")
        scope_spec = _strict_object(scope_value, scope_keys, "BaseHTTPMiddleware HTTP scope")
        _strict_object(
            scope_spec["asgi"], {"version", "spec_version"}, "BaseHTTPMiddleware ASGI version"
        )
    path = scope_spec["path"]
    if (
        scope_spec["type"] != "http"
        or (
            not source_sparse_scope
            and scope_spec["asgi"] != {"version": "3.0", "spec_version": "2.4"}
        )
        or not isinstance(scope_spec["method"], str)
        or scope_spec["method"] not in {"GET", "POST"}
        or not isinstance(path, str)
        or (not source_sparse_scope and scope_spec["scheme"] != "http")
        or (not source_sparse_scope and not isinstance(scope_spec["http_version"], str))
        or (route_spec is not None and path != route_spec["path"])
        or (route_spec is None and downstream_spec is None and path == "/")
        or (route_spec is not None and scope_spec["method"] not in route_spec["methods"])
        or (returned == "call-next" and route_spec is None and downstream_spec is None)
        or (not source_sparse_scope and not isinstance(scope_spec["root_path"], str))
    ):
        raise ValueError("BaseHTTPMiddleware request scope does not select its declared route case")
    extensions = scope_spec.get("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("BaseHTTPMiddleware scope.extensions must be an object")
    has_pathsend_extension = "http.response.pathsend" in extensions
    file_response_pathsend = route_kind == "file-response" and has_pathsend_extension
    if (
        (extensions and extensions != {"http.response.pathsend": {}})
        or (route_kind == "file-response" and not file_response_pathsend)
        or (route_kind != "file-response" and extensions)
    ):
        raise ValueError(
            "BaseHTTPMiddleware scope extensions are supported only for FileResponse pathsend"
        )
    if file_response_pathsend and (
        route_spec["methods"] != ["GET"]
        or scope_spec["method"] != "GET"
        or returned != "call-next"
        or dispatch_actions != [{"kind": "await-call-next"}, {"kind": "return-call-next-response"}]
    ):
        raise ValueError(
            "FileResponse pathsend requires a GET route returned directly through call_next"
        )
    if not source_sparse_scope:
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
    if not isinstance(receive_specs, list) or (
        not receive_specs and not (file_response_pathsend or source_sparse_scope)
    ):
        raise ValueError("BaseHTTPMiddleware request requires HTTP body events")
    request_event_specs = []
    disconnect_event_indices = []
    for index, receive_spec in enumerate(receive_specs):
        if not isinstance(receive_spec, dict) or not isinstance(receive_spec.get("type"), str):
            raise ValueError(f"BaseHTTPMiddleware receive event[{index}] must be tagged")
        if receive_spec["type"] == "http.request":
            receive_spec = _strict_object(
                receive_spec,
                {"type", "body_base64", "more_body"},
                f"BaseHTTPMiddleware HTTP request event[{index}]",
            )
            if type(receive_spec["more_body"]) is not bool:
                raise ValueError("BaseHTTPMiddleware request more_body must be boolean")
            _decode_b64(receive_spec["body_base64"], f"BaseHTTPMiddleware request body[{index}]")
            request_event_specs.append(receive_spec)
        elif receive_spec["type"] == "http.disconnect":
            _strict_object(receive_spec, {"type"}, f"BaseHTTPMiddleware disconnect event[{index}]")
            disconnect_event_indices.append(index)
        else:
            raise ValueError(f"BaseHTTPMiddleware receive event[{index}] has unsupported type")
    for index, receive_spec in enumerate(request_event_specs):
        if receive_spec["more_body"] is not (index < len(request_event_specs) - 1):
            raise ValueError("BaseHTTPMiddleware request events must end with one final body event")
    if disconnect_event_indices and (
        len(disconnect_event_indices) != 1 or disconnect_event_indices[0] != len(receive_specs) - 1
    ):
        raise ValueError("BaseHTTPMiddleware request input may end with one disconnect event")
    if disconnect_event_indices and (
        downstream_spec is None
        or downstream_spec["kind"] not in {"disconnect-polling-app", "receive-sequence-app"}
    ):
        raise ValueError("explicit http.disconnect input requires a downstream disconnect case")
    receive_after_events = request["receive_after_events"]
    if isinstance(receive_after_events, str):
        if receive_after_events not in {"disconnect", "block"}:
            raise ValueError("receive_after_events must be disconnect, block, or a raise input")
    else:
        receive_after_events = _strict_object(
            receive_after_events,
            {"kind", "class", "message"},
            "BaseHTTPMiddleware exhausted receive behavior",
        )
        allowed_receive_exceptions = (
            {"NotImplementedError"}
            if file_response_pathsend or source_sparse_scope
            else {"AssertionError"}
        )
        if (
            receive_after_events["kind"] != "raise"
            or receive_after_events["class"] not in allowed_receive_exceptions
        ):
            raise ValueError("exhausted receive exception is not allowed for this case")
        if not isinstance(receive_after_events["message"], str):
            raise ValueError("exhausted receive exception message must be a string")
    send_checkpoints = request["send_checkpoints"]
    if (
        not isinstance(send_checkpoints, list)
        or any(type(index) is not int or not 0 <= index <= 2 for index in send_checkpoints)
        or len(set(send_checkpoints)) != len(send_checkpoints)
    ):
        raise ValueError("send_checkpoints must contain unique output-send indices from 0 to 2")

    request_body = b"".join(
        _decode_b64(item["body_base64"], "BaseHTTPMiddleware request body")
        for item in request_event_specs
    )
    reads_body_before_call_next = (
        route_kind == "request-body-response"
        and request_body
        and await_index is not None
        and dispatch_actions[:await_index] == [{"kind": "read-request-body"}]
        and dispatch_actions[await_index + 1 :] == [{"kind": "return-call-next-response"}]
    )
    if reads_body_before_call_next:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-body-read-after-body-cache"
        )
    elif (
        route_kind == "request-body-response"
        and request_body
        and await_index is not None
        and any(action["kind"] == "read-request-body" for action in dispatch_actions[:await_index])
        and any(
            action["kind"] == "read-request-body" for action in dispatch_actions[await_index + 1 :]
        )
    ):
        required_covers.add(f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.body-cache-replay")
    if await_action_kind == "await-call-next-catching-exception":
        if route_kind != "raise-exception":
            raise ValueError(
                "call_next exception handling requires a declared raising route endpoint"
            )
        if returned != "call-next":
            raise ValueError("caught call_next exception response must be returned from dispatch")
        endpoint_exception_type = getattr(builtins, exception_spec["class"])
        caught_exception_type = getattr(builtins, dispatch_actions[await_index]["exception_class"])
        if not issubclass(endpoint_exception_type, caught_exception_type):
            raise ValueError(
                "call_next exception handler cannot catch the declared endpoint exception"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.catch-call-next-exception"
        )
    elif route_kind == "raise-exception" and returned == "call-next":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.exception-context-propagation"
        )
    if any(
        action["kind"] == "capture-request-stream-next" for action in dispatch_actions
    ) and route_kind not in {
        "request-body-plain-text-response",
        "request-stream-plain-text-response",
    }:
        raise ValueError(
            "captured post-call-next stream reads require a body- or stream-reading plain-text endpoint"
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
            for item in request_event_specs
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
    if route_kind == "request-body-plain-text-response":
        stream_body_reads = (
            [
                action
                for action in dispatch_actions[:await_index]
                if action["kind"] == "read-request-stream-next"
            ]
            if await_index is not None
            else []
        )
        expected_stream_reads = (
            sum(
                bool(_decode_b64(event["body_base64"], "BaseHTTPMiddleware request body"))
                for event in request_event_specs
            )
            + 2
        )
        reads_body_after_stream = (
            await_index is not None
            and dispatch_actions[await_index + 1 :] == [{"kind": "return-call-next-response"}]
            and len(stream_body_reads) == expected_stream_reads
            and all(
                action["kind"] == "read-request-stream-next"
                for action in dispatch_actions[:await_index]
            )
        )
        reads_stream_after_downstream_body = dispatch_actions == [
            {"kind": "await-call-next"},
            {"kind": "capture-request-stream-next"},
            {"kind": "return-call-next-response"},
        ]
        reads_stream_after_downstream_body_cache = dispatch_actions == [
            {"kind": "read-request-body"},
            {"kind": "await-call-next"},
            {"kind": "read-request-stream-next"},
            {"kind": "read-request-stream-next"},
            {"kind": "read-request-stream-next"},
            {"kind": "return-call-next-response"},
        ]
        if (
            returned != "call-next"
            or scope_spec["method"] != "POST"
            or not request_body
            or await_index is None
            or not (
                reads_body_after_stream
                or reads_stream_after_downstream_body
                or reads_stream_after_downstream_body_cache
            )
            or request["receive_after_events"] != "disconnect"
            or disconnect_event_indices
            or send_checkpoints
        ):
            raise ValueError(
                "request-body plain-text cases require a non-empty POST body, a supported body/stream read ordering around call_next, an input-defined plain-text response, and disconnect after the supplied request events"
            )
        if reads_body_after_stream:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-body-read-after-stream-consumption"
            )
        elif reads_stream_after_downstream_body_cache:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.dispatch-stream-replay-after-pre-call-next-body-cache"
            )
        else:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.dispatch-stream-read-after-downstream-body-read"
            )
    if route_kind == "request-stream-plain-text-response":
        reads_stream_after_body_cache = dispatch_actions == [
            {"kind": "read-request-body"},
            {"kind": "await-call-next"},
            {"kind": "return-call-next-response"},
        ]
        reads_stream_after_downstream_stream = dispatch_actions == [
            {"kind": "await-call-next"},
            {"kind": "capture-request-stream-next"},
            {"kind": "return-call-next-response"},
        ]
        stream_reads_before_call_next = (
            [
                action
                for action in dispatch_actions[:await_index]
                if action["kind"] == "read-request-stream-next"
            ]
            if await_index is not None
            else []
        )
        expected_stream_reads = (
            sum(
                bool(_decode_b64(event["body_base64"], "BaseHTTPMiddleware request body"))
                for event in request_event_specs
            )
            + 2
        )
        reads_stream_before_call_next = (
            await_index is not None
            and dispatch_actions[await_index + 1 :] == [{"kind": "return-call-next-response"}]
            and len(stream_reads_before_call_next) == expected_stream_reads
            and all(
                action["kind"] == "read-request-stream-next"
                for action in dispatch_actions[:await_index]
            )
        )
        if (
            returned != "call-next"
            or scope_spec["method"] != "POST"
            or not request_body
            or not (
                reads_stream_after_body_cache
                or reads_stream_after_downstream_stream
                or reads_stream_before_call_next
            )
            or disconnect_event_indices
            or send_checkpoints
        ):
            raise ValueError(
                "request-stream plain-text cases require a non-empty POST body, a supported body/stream read ordering around call_next, and a direct returned call_next response"
            )
        if reads_stream_after_body_cache:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-stream-read-after-body-cache"
            )
        elif reads_stream_before_call_next:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-stream-read-after-stream-consumption"
            )
        else:
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.dispatch-stream-read-after-downstream-stream-consumption"
            )
    if downstream_spec is not None and downstream_spec["kind"] == "asgi-sequence":
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
    elif downstream_spec is not None and downstream_spec["kind"] == "stream-until-disconnect-app":
        request_body_events = [
            event for event in request_event_specs if event["type"] == "http.request"
        ]
        if (
            not saw_response_body_read
            or returned != "replacement"
            or scope_spec["method"] != "GET"
            or request["receive_after_events"] != "block"
            or len(request_body_events) != 1
            or _decode_b64(request_body_events[0]["body_base64"], "BaseHTTPMiddleware request body")
            or request_body_events[0]["more_body"]
            or disconnect_event_indices
            or send_checkpoints != [0, 1]
            or len(dispatch_actions) != 3
            or dispatch_actions[0] != {"kind": "await-call-next"}
            or dispatch_actions[1] != {"kind": "read-call-next-response-body-next-and-close"}
            or dispatch_actions[2]["kind"] != "return-plain-text-response"
        ):
            raise ValueError(
                "discarded response streaming requires one empty GET request, one call_next body read, replacement response, blocking receive, and checkpoints after both outer sends"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.discarded-stream-cancelled-on-disconnect"
        )
    elif downstream_spec is not None and downstream_spec["kind"] == "asgi-middleware-stack":
        body_reads_before_call_next = [
            index
            for index, action in enumerate(dispatch_actions)
            if action["kind"] == "read-request-body"
            and await_index is not None
            and index < await_index
        ]
        if (
            returned != "call-next"
            or not body_reads_before_call_next
            or not request_body
            or len(receive_specs) != 1
            or scope_spec["method"] != "POST"
            or send_checkpoints
        ):
            raise ValueError(
                "downstream receive transformation requires a consumed non-empty POST body, one terminal request event, call_next, and no send checkpoints"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-middleware-receive-transformation"
        )
    elif downstream_spec is not None and downstream_spec["kind"] == "disconnect-polling-app":
        request_bodies = [
            _decode_b64(item["body_base64"], "BaseHTTPMiddleware request body")
            for item in request_event_specs
        ]
        send_body_variant = (
            len(receive_specs) == 3
            and len(request_event_specs) == 2
            and bool(request_bodies[0])
            and not request_bodies[1]
            and len(disconnect_event_indices) == 1
        )
        no_body_variant = (
            receive_specs == [{"type": "http.disconnect"}]
            and not request_event_specs
            and len(disconnect_event_indices) == 1
        )
        if (
            returned != "call-next"
            or scope_spec["method"] != "GET"
            or request["receive_after_events"] != "block"
            or send_checkpoints
            or not (send_body_variant or no_body_variant)
        ):
            raise ValueError(
                "repeated disconnect polling requires GET, two call_next polls, one disconnect, blocking exhausted receive, and either one body stream or no body"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.repeated-disconnect-polling"
        )
    elif downstream_spec is not None and downstream_spec["kind"] == "receive-sequence-app":
        receive_steps = downstream_spec["steps"]
        no_body_case = (
            receive_specs == [{"type": "http.disconnect"}]
            and len(receive_steps) == 1
            and dispatch_actions
            == [
                {"kind": "await-call-next"},
                {"kind": "check-request-is-disconnected"},
                {"kind": "return-call-next-response"},
            ]
        )
        body_case = (
            len(request_event_specs) == 1
            and bool(request_body)
            and len(receive_specs) == 2
            and len(disconnect_event_indices) == 1
            and len(receive_steps) == 2
            and dispatch_actions
            == [
                {"kind": "read-request-body"},
                {"kind": "check-request-is-disconnected"},
                {"kind": "await-call-next"},
                {"kind": "return-call-next-response"},
            ]
        )
        if (
            not saw_disconnect_check
            or returned != "call-next"
            or scope_spec["method"] != "POST"
            or not isinstance(request["receive_after_events"], dict)
            or request["receive_after_events"].get("kind") != "raise"
            or not disconnect_event_indices
            or send_checkpoints
            or not (no_body_case or body_case)
        ):
            raise ValueError(
                "Request.is_disconnected BaseHTTP cases require the source-backed one-message disconnect or cached-body-then-disconnect sequence"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.request-disconnect-observation"
        )
    if saw_disconnect_check and (
        downstream_spec is None or downstream_spec["kind"] != "receive-sequence-app"
    ):
        raise ValueError("Request.is_disconnected BaseHTTP input requires a receive-sequence app")
    if saw_response_body_read and (
        downstream_spec is None or downstream_spec["kind"] != "stream-until-disconnect-app"
    ):
        raise ValueError("call_next response body read requires a streaming-until-disconnect app")
    if route_kind == "file-response":
        if (
            not file_response_pathsend
            or receive_specs
            or request["receive_after_events"]
            != {
                "kind": "raise",
                "class": "NotImplementedError",
                "message": "Should not be called!",
            }
            or send_checkpoints
        ):
            raise ValueError(
                "BaseHTTPMiddleware FileResponse input requires pathsend and an unused receive callback"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.pathsend-event-forwarding"
        )
    if source_sparse_scope:
        if (
            route_spec["methods"] != ["GET"]
            or endpoint_spec["content"] != ""
            or endpoint_spec["status_code"] != 200
            or dispatch_actions
            != [{"kind": "await-call-next"}, {"kind": "return-call-next-response"}]
            or downstream_spec is not None
            or receive_specs
            or request["receive_after_events"]
            != {
                "kind": "raise",
                "class": "NotImplementedError",
                "message": "Should not be called!",
            }
            or send_checkpoints
        ):
            raise ValueError(
                "background task case must preserve the pinned source response and unused receive callback"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.background-task-completes-after-response-send"
        )
    if not isinstance(case["covers"], list) or set(case["covers"]) != required_covers:
        raise ValueError("BaseHTTPMiddleware covers differ from its input actions")

    import anyio
    from starlette.applications import Starlette
    from starlette.background import BackgroundTask
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import FileResponse, PlainTextResponse, Response
    from starlette.routing import Route

    execution_trace: list[dict[str, Any]] = []
    dispatch_body_reads: list[dict[str, Any]] = []
    dispatch_stream_reads: list[dict[str, Any]] = []
    dispatch_response_stream_reads: list[dict[str, Any]] = []
    downstream_stream_reads: list[dict[str, Any]] = []
    downstream_body_reads: list[dict[str, Any]] = []
    downstream_receive_transformations: list[dict[str, Any]] = []
    downstream_receive_events: list[dict[str, Any]] = []
    downstream_poll_results: list[dict[str, Any]] = []
    dispatch_caught_exceptions: list[dict[str, Any]] = []
    dispatch_disconnect_checks: list[dict[str, Any]] = []
    downstream_stream_cancellation_results: list[dict[str, Any]] = []
    downstream_stream_guard_fired = False
    file_response_temporary_directory = None
    response_complete = asyncio.Event()
    background_task_run = asyncio.Event()
    background_task_events: list[dict[str, Any]] = []

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
                elif kind == "check-request-is-disconnected":
                    disconnected = await request.is_disconnected()
                    dispatch_disconnect_checks.append(
                        {"action_index": action_index, "disconnected": disconnected}
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
                elif kind == "capture-request-stream-next":
                    if stream_iterator is None:
                        stream_iterator = request.stream()
                    try:
                        chunk = await stream_iterator.__anext__()
                    except StopAsyncIteration:
                        outcome = {"kind": "exhausted"}
                    except Exception as exc:
                        outcome = {
                            "kind": "exception",
                            "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                            "message": str(exc),
                        }
                    else:
                        outcome = {
                            "kind": "yielded",
                            "body_base64": base64.b64encode(chunk).decode("ascii"),
                        }
                    dispatch_stream_reads.append(
                        {
                            "action_index": action_index,
                            "phase": "after-call-next",
                            "outcome": outcome,
                        }
                    )
                elif kind == "read-call-next-response-body-next-and-close":
                    body_iterator = response.body_iterator
                    try:
                        chunk = await body_iterator.__anext__()
                    finally:
                        await body_iterator.aclose()
                    dispatch_response_stream_reads.append(
                        {
                            "action_index": action_index,
                            "body_base64": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                elif kind == "await-call-next":
                    response = await call_next(request)
                elif kind == "await-call-next-catching-exception":
                    action = dispatch_actions[action_index]
                    exception_type = getattr(builtins, action["exception_class"])
                    try:
                        response = await call_next(request)
                    except exception_type as exc:
                        response = PlainTextResponse(
                            content=str(exc),
                            status_code=action["response_status_code"],
                        )
                        dispatch_caught_exceptions.append(
                            {
                                "action_index": action_index,
                                "exception_class": type(exc).__name__,
                                "message": str(exc),
                                "response_status_code": action["response_status_code"],
                            }
                        )
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
                body = await request.body()
                downstream_body_reads.append(
                    {"body_base64": base64.b64encode(body).decode("ascii")}
                )
                return PlainTextResponse(body)
        elif route_kind == "request-body-plain-text-response":
            response_content = endpoint_spec["content"]
            response_status_code = endpoint_spec["status_code"]

            async def endpoint(request: Any) -> Any:
                body = await request.body()
                downstream_body_reads.append(
                    {"body_base64": base64.b64encode(body).decode("ascii")}
                )
                return PlainTextResponse(response_content, status_code=response_status_code)
        elif route_kind == "request-stream-plain-text-response":
            response_content = endpoint_spec["content"]
            response_status_code = endpoint_spec["status_code"]

            async def endpoint(request: Any) -> Any:
                async for chunk in request.stream():
                    downstream_stream_reads.append(
                        {
                            "index": len(downstream_stream_reads),
                            "body_base64": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                return PlainTextResponse(response_content, status_code=response_status_code)
        elif route_kind == "raise-exception":
            exception_type = getattr(builtins, exception_spec["class"])
            exception_message = exception_spec["message"]
            exception_chain = exception_spec.get("chain")

            def endpoint(_request: Any) -> None:
                raised_exception = exception_type(exception_message)
                if exception_chain is None:
                    raise raised_exception
                chained_type = getattr(builtins, exception_chain["class"])
                chained_exception = chained_type(exception_chain["message"])
                if exception_chain["relation"] == "explicit-cause":
                    raise raised_exception from chained_exception
                try:
                    raise chained_exception
                except BaseException:
                    raise raised_exception  # noqa: B904
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
        elif route_kind == "file-response":
            file_input = endpoint_spec["file"]
            file_response_temporary_directory = tempfile.TemporaryDirectory(
                prefix="starlette-file-response-"
            )
            file_response_path = Path(file_response_temporary_directory.name) / file_input["name"]
            file_response_path.write_bytes(
                _decode_b64(
                    file_input["contents_base64"], "BaseHTTPMiddleware FileResponse contents"
                )
            )
            os.utime(
                file_response_path,
                (file_input["mtime_seconds"], file_input["mtime_seconds"]),
            )

            async def endpoint(_request: Any) -> Any:
                return FileResponse(file_response_path)
        elif background_task_spec is not None:
            response_content = endpoint_spec["content"]
            response_status_code = endpoint_spec["status_code"]
            background_delay = background_task_spec["delay_seconds"]

            async def sleep_and_set() -> None:
                started = {"event": "background-task-start"}
                background_task_events.append(started)
                execution_trace.append(started)
                await anyio.sleep(background_delay)
                background_task_run.set()
                completed = {"event": "background-task-complete"}
                background_task_events.append(completed)
                execution_trace.append(completed)

            async def endpoint(_request: Any) -> Any:
                return PlainTextResponse(
                    response_content,
                    status_code=response_status_code,
                    background=BackgroundTask(sleep_and_set),
                )
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
    elif downstream_spec is not None and downstream_spec["kind"] == "asgi-sequence":

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
                    if message_spec["type"] == "http.response.start":
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
                    else:
                        message = {
                            "type": message_spec["type"],
                            "body": _decode_b64(
                                message_spec["body_base64"], "downstream response body"
                            ),
                            "more_body": message_spec["more_body"],
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
    elif downstream_spec is not None and downstream_spec["kind"] == "stream-until-disconnect-app":

        async def downstream_streaming_app(scope: Any, receive: Any, send: Any) -> None:
            nonlocal downstream_stream_guard_fired
            response_start = downstream_spec["response_start"]
            await send(
                {
                    "type": "http.response.start",
                    "status": response_start["status"],
                    "headers": [
                        (
                            _decode_b64(pair[0], "downstream streaming response header name"),
                            _decode_b64(pair[1], "downstream streaming response header value"),
                        )
                        for pair in response_start["headers_base64_pairs"]
                    ],
                }
            )
            disconnect_received = False
            guard_timeout = downstream_spec["guard_timeout_ms"] / 1000
            async with anyio.create_task_group() as task_group:

                async def cancel_stream_on_disconnect(
                    *, task_status: Any = anyio.TASK_STATUS_IGNORED
                ) -> None:
                    nonlocal disconnect_received
                    task_status.started()
                    receive_index = 0
                    while True:
                        message = await receive()
                        downstream_receive_events.append(
                            {
                                "poll_index": 0,
                                "receive_index": receive_index,
                                "message": _canonical_http_message(message),
                            }
                        )
                        receive_index += 1
                        if message["type"] == "http.disconnect":
                            disconnect_received = True
                            task_group.cancel_scope.cancel()
                            break

                await task_group.start(cancel_stream_on_disconnect)
                with anyio.move_on_after(guard_timeout) as safety_guard:
                    body_message = downstream_spec["body_message"]
                    while True:
                        await send(
                            {
                                "type": "http.response.body",
                                "body": _decode_b64(
                                    body_message["body_base64"],
                                    "downstream streaming response body",
                                ),
                                "more_body": body_message["more_body"],
                            }
                        )
                if safety_guard.cancel_called:
                    downstream_stream_guard_fired = True
                    task_group.cancel_scope.cancel()
            if disconnect_received:
                downstream_stream_cancellation_results.append(
                    {"disconnect_received": True, "stream_cancelled": True}
                )

        app = InputDefinedBaseHTTPMiddleware(downstream_streaming_app)
    elif downstream_spec is not None and downstream_spec["kind"] == "asgi-middleware-stack":

        async def downstream_endpoint(scope: Any, receive: Any, send: Any) -> None:
            request_value = Request(scope, receive)
            body = await request_value.body()
            downstream_body_reads.append({"body_base64": base64.b64encode(body).decode("ascii")})
            await Response(status_code=downstream_spec["endpoint"]["status_code"])(
                scope,
                receive,
                send,
            )

        downstream_app = downstream_endpoint
        for wrapper_index, wrapper_spec in reversed(list(enumerate(downstream_spec["wrappers"]))):
            wrapped_app = downstream_app
            repeat_count = wrapper_spec["repeat_count"]

            def receive_wrapper(
                app_value: Any,
                current_wrapper_index: int,
                current_repeat_count: int,
            ) -> Any:
                async def wrapped_app_value(scope: Any, receive: Any, send: Any) -> None:
                    receive_index = 0

                    async def wrapped_receive() -> Any:
                        nonlocal receive_index
                        message = await receive()
                        before = _canonical_http_message(message)
                        if message["type"] == "http.request":
                            message["body"] = message.get("body", b"") * current_repeat_count
                        downstream_receive_transformations.append(
                            {
                                "wrapper_index": current_wrapper_index,
                                "receive_index": receive_index,
                                "before": before,
                                "after": _canonical_http_message(message),
                            }
                        )
                        receive_index += 1
                        return message

                    await app_value(scope, wrapped_receive, send)

                return wrapped_app_value

            downstream_app = receive_wrapper(
                wrapped_app,
                wrapper_index,
                repeat_count,
            )

        app = InputDefinedBaseHTTPMiddleware(downstream_app)
    elif downstream_spec is not None and downstream_spec["kind"] == "disconnect-polling-app":

        async def downstream_polling_app(scope: Any, receive: Any, send: Any) -> None:
            receive_index = 0
            for poll_index, _poll_spec in enumerate(downstream_spec["polls"]):
                drained_request_events = []
                while True:
                    message = await receive()
                    canonical = _canonical_http_message(message)
                    downstream_receive_events.append(
                        {
                            "poll_index": poll_index,
                            "receive_index": receive_index,
                            "message": canonical,
                        }
                    )
                    receive_index += 1
                    if message["type"] == "http.request":
                        drained_request_events.append(canonical)
                        continue
                    downstream_poll_results.append(
                        {
                            "poll_index": poll_index,
                            "drained_request_events": drained_request_events,
                            "result": canonical,
                        }
                    )
                    if message["type"] != "http.disconnect":
                        raise AssertionError(
                            f"expected http.disconnect, received {message['type']}"
                        )
                    break

            response_spec = downstream_spec["response"]
            await Response(
                _decode_b64(response_spec["body_base64"], "downstream response body"),
                status_code=response_spec["status_code"],
            )(scope, receive, send)

        app = InputDefinedBaseHTTPMiddleware(downstream_polling_app)
    elif downstream_spec is not None and downstream_spec["kind"] == "receive-sequence-app":

        async def downstream_receive_sequence_app(scope: Any, receive: Any, send: Any) -> None:
            for receive_index, _step in enumerate(downstream_spec["steps"]):
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
            response_spec = downstream_spec["response"]
            await Response(status_code=response_spec["status_code"])(scope, receive, send)

        app = InputDefinedBaseHTTPMiddleware(downstream_receive_sequence_app)
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
    receive_call_count = 0
    send_index = 0
    send_checkpoint_indices = set(send_checkpoints)

    async def receive() -> dict[str, Any]:
        nonlocal receive_index, receive_call_count
        receive_call_count += 1
        if source_sparse_scope:
            execution_trace.append(
                {"event": "request-receive-call", "call_index": receive_call_count - 1}
            )
        if receive_index < len(incoming):
            message = incoming[receive_index]
            receive_index += 1
        elif request["receive_after_events"] == "block":
            await asyncio.Event().wait()
        elif request["receive_after_events"] == "disconnect":
            message = {"type": "http.disconnect"}
        else:
            exception_type = getattr(builtins, request["receive_after_events"]["class"])
            raise exception_type(request["receive_after_events"]["message"])
        request_receive_events.append(_canonical_http_message(message))
        return message

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index
        sent.append(message)
        execution_trace.append(
            {"event": "outer-send", "index": send_index, "message": _canonical_message(message)}
        )
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            response_complete.set()
            if source_sparse_scope:
                execution_trace.append({"event": "response-complete"})
        if send_index in send_checkpoint_indices:
            await asyncio.sleep(0)
        send_index += 1

    try:
        asyncio.run(app(scope, receive, send))
        propagated_exception = None
    except Exception as exc:
        propagated_exception = _base_http_exception_value(exc)
    finally:
        if file_response_temporary_directory is not None:
            file_response_temporary_directory.cleanup()
    if downstream_stream_guard_fired:
        raise TimeoutError(
            "input-defined BaseHTTPMiddleware streaming guard expired before http.disconnect"
        )
    if source_sparse_scope:
        execution_trace.append(
            {
                "event": "background-task-run-observed",
                "is_set": background_task_run.is_set(),
            }
        )
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
        "dispatch_response_stream_reads": dispatch_response_stream_reads,
        "downstream_stream_reads": downstream_stream_reads,
        "downstream_body_reads": downstream_body_reads,
        "downstream_receive_transformations": downstream_receive_transformations,
        "downstream_receive_events": downstream_receive_events,
        "downstream_poll_results": downstream_poll_results,
        "downstream_stream_cancellation_results": downstream_stream_cancellation_results,
        "dispatch_caught_exceptions": dispatch_caught_exceptions,
        "dispatch_disconnect_checks": dispatch_disconnect_checks,
        "request_receive_events": request_receive_events,
        "execution_trace": execution_trace,
        "propagated_exception": propagated_exception,
    }
    if source_sparse_scope:
        value.update(
            {
                "request_receive_call_count": receive_call_count,
                "response_complete": response_complete.is_set(),
                "background_task_run": background_task_run.is_set(),
                "background_task_events": background_task_events,
            }
        )
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
                elif mutation_kind == "popitem":
                    mutation_result = session.popitem()
                elif mutation_kind == "setdefault":
                    mutation_result = session.setdefault(mutation["key"], mutation["default"])
                elif mutation_kind == "update":
                    session.update(mutation["values"])
                elif mutation_kind == "in-place-union":
                    original_session = session
                    session |= mutation["values"]
                    mutation_result = session is original_session
                session_value = dict(session)
            elif action_kind == "session-operation":
                session = request.session
                mutation = action["mutation"]
                try:
                    if mutation["kind"] == "popitem":
                        mutation_result = session.popitem()
                    elif mutation["kind"] == "in-place-union":
                        original_session = session
                        session |= mutation["values"]
                        mutation_result = session is original_session
                except Exception as exc:
                    current["session"] = _json_safe(dict(session))
                    current["accessed"] = session.accessed
                    current["modified"] = session.modified
                    current["mutation_result"] = _json_safe(mutation_result)
                    current["error"] = _error_snapshot(exc)
                    raise
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
                    "popitem": {"kind"},
                    "setdefault": {"kind", "key", "default"},
                    "update": {"kind", "values"},
                    "in-place-union": {"kind", "values"},
                }.get(mutation["kind"])
                if mutation_keys is None:
                    raise ValueError(f"unsupported Session mutation: {mutation['kind']!r}")
                _strict_object(mutation, mutation_keys, "SessionMiddleware mutation")
            elif action["kind"] == "session-operation":
                if scope["type"] != "http":
                    raise ValueError("Session operations require HTTP scopes")
                _strict_object(
                    action,
                    {"kind", "mutation"},
                    "SessionMiddleware request Session operation action",
                )
                mutation = action["mutation"]
                if not isinstance(mutation, dict) or mutation.get("kind") not in {
                    "popitem",
                    "in-place-union",
                }:
                    raise ValueError("unsupported request Session operation")
                mutation_keys = {
                    "popitem": {"kind"},
                    "in-place-union": {"kind", "values"},
                }[mutation["kind"]]
                _strict_object(
                    mutation, mutation_keys, "SessionMiddleware request Session operation"
                )
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
                "session-operation": "http",
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
                    "error": None,
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

            try:
                await middleware(scope, receive, send)
            except Exception:
                if current["error"] is None:
                    raise
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
                    "outcome": "error" if current["error"] is not None else "ok",
                    "error": current["error"],
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
                            "error_class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                            "error_message": str(exc),
                        }
                    )
            except Exception as exc:
                results.append(
                    {
                        "action_id": action_id,
                        "outcome": "error",
                        "error_class": f"{type(exc).__module__}.{type(exc).__qualname__}",
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


class _WebSocketEndpointInputReceive:
    def __init__(
        self,
        messages: tuple[dict[str, Any], ...],
        *,
        cancel_on_exhaustion: bool = False,
    ) -> None:
        self.messages = messages
        self.index = 0
        self.cancel_on_exhaustion = cancel_on_exhaustion
        self.waiting: asyncio.Event | None = None

    async def __call__(self) -> dict[str, Any]:
        if self.index >= len(self.messages):
            if self.cancel_on_exhaustion:
                if self.waiting is None:
                    raise RuntimeError("WebSocketEndpoint cancellation event was not initialized")
                self.waiting.set()
                await asyncio.Future()
            raise ValueError("WebSocketEndpoint exhausted its input-only receive sequence")
        message = self.messages[self.index]
        self.index += 1
        return message


class _WebSocketEndpointCaptureSend:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(dict(message))


def _websocket_endpoint_accept_hook(spec: dict[str, Any], calls: list[dict[str, Any]]) -> Any:
    async def on_connect(_endpoint: Any, websocket: Any) -> None:
        call: dict[str, Any] = {"hook": "on_connect"}
        if spec["observe_scope_subprotocols"]:
            call["scope_subprotocols"] = list(websocket.scope["subprotocols"])
        calls.append(call)
        await websocket.accept(subprotocol=spec["subprotocol"])

    return on_connect


def _websocket_endpoint_receive_hook(spec: dict[str, Any], calls: list[dict[str, Any]]) -> Any:
    prefix = (
        _decode_b64(spec["prefix_base64"], "WebSocketEndpoint.on_receive.prefix_base64")
        if spec["kind"] == "send-bytes-prefix"
        else None
    )

    async def on_receive(_endpoint: Any, websocket: Any, data: Any) -> None:
        calls.append({"hook": "on_receive", "data": _json_safe(data)})
        if spec["kind"] == "send-text-prefix":
            await websocket.send_text(spec["prefix"] + data)
        elif spec["kind"] == "send-bytes-prefix":
            await websocket.send_bytes(prefix + data)
        elif spec["kind"] == "raise-value-error":
            raise ValueError(spec["message"])
        else:
            await websocket.send_json({spec["key"]: data}, mode=spec["mode"])

    return on_receive


def _websocket_endpoint_disconnect_hook(calls: list[dict[str, Any]]) -> Any:
    async def on_disconnect(_endpoint: Any, websocket: Any, close_code: int) -> None:
        calls.append({"hook": "on_disconnect", "close_code": close_code})
        await websocket.close(code=close_code)

    return on_disconnect


async def _await_websocket_endpoint(
    endpoint_type: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
) -> None:
    await endpoint_type(scope, receive, send)


async def _await_cancelled_websocket_endpoint(
    endpoint_type: Any,
    scope: dict[str, Any],
    receive: _WebSocketEndpointInputReceive,
    send: Any,
) -> dict[str, Any] | None:
    receive.waiting = asyncio.Event()
    task = asyncio.create_task(_await_websocket_endpoint(endpoint_type, scope, receive, send))
    await receive.waiting.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError as exc:
        return _dispatch_error(exc)
    return None


def _run_websocket_endpoint_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "endpoint",
            "sessions",
            "observations",
        },
        "WebSocketEndpoint dispatch case",
    )
    if (
        case["surface"] != WEBSOCKET_ENDPOINT_SURFACE
        or case["operation"] != WEBSOCKET_ENDPOINT_OPERATION
    ):
        raise ValueError("workflow is outside the declared WebSocketEndpoint dispatch operation")
    if case["observations"] != [WEBSOCKET_ENDPOINT_OPERATION]:
        raise ValueError("WebSocketEndpoint observations must select the dispatch workflow")
    from starlette.endpoints import WebSocketEndpoint

    endpoint_spec = case["endpoint"]
    connection_results: list[dict[str, Any]] = []
    for session_spec in case["sessions"]:
        scope = _make_websocket_scope(session_spec["scope"])
        incoming = tuple(
            _materialize_websocket_message(message) for message in session_spec["incoming"]
        )
        hook_calls: list[dict[str, Any]] = []
        sent_messages: list[dict[str, Any]] = []
        methods: dict[str, Any] = {"encoding": endpoint_spec["encoding"]}

        if endpoint_spec["on_connect"]["kind"] == "accept":
            methods["on_connect"] = _websocket_endpoint_accept_hook(
                endpoint_spec["on_connect"], hook_calls
            )

        on_receive_spec = endpoint_spec["on_receive"]
        if on_receive_spec["kind"] != "no-op":
            methods["on_receive"] = _websocket_endpoint_receive_hook(on_receive_spec, hook_calls)

        if endpoint_spec["on_disconnect"]["kind"] == "record-and-close":
            methods["on_disconnect"] = _websocket_endpoint_disconnect_hook(hook_calls)

        endpoint_type = type("InputWebSocketEndpoint", (WebSocketEndpoint,), methods)
        receive = _WebSocketEndpointInputReceive(
            incoming, cancel_on_exhaustion=session_spec.get("cancel_at") == "receive"
        )
        send = _WebSocketEndpointCaptureSend(sent_messages)

        if session_spec.get("cancel_at") == "receive":
            error = asyncio.run(
                _await_cancelled_websocket_endpoint(endpoint_type, scope, receive, send)
            )
        else:
            error: dict[str, Any] | None = None
            try:
                asyncio.run(_await_websocket_endpoint(endpoint_type, scope, receive, send))
            except Exception as exc:
                error = _dispatch_error(exc)
        if receive.index != len(incoming):
            raise ValueError("WebSocketEndpoint dispatch left supplied ASGI input unconsumed")
        connection_results.append(
            {
                "hook_calls": hook_calls,
                "asgi_events": [_canonical_websocket_message(message) for message in sent_messages],
                "exception": error,
            }
        )

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": WEBSOCKET_ENDPOINT_OPERATION,
                "status": "ok",
                "value": {"dispatch": {"connections": connection_results}},
            }
        ],
    }


async def _await_http_endpoint(
    endpoint_type: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
) -> None:
    await endpoint_type(scope, receive, send)


def _run_http_endpoint_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "endpoint",
            "scope",
            "incoming",
            "send",
            "observations",
        },
        "HTTPEndpoint dispatch case",
    )
    if case["surface"] != HTTP_ENDPOINT_SURFACE or case["operation"] != HTTP_ENDPOINT_OPERATION:
        raise ValueError("workflow is outside the declared HTTPEndpoint dispatch operation")
    if case["observations"] != [HTTP_ENDPOINT_OPERATION]:
        raise ValueError("HTTPEndpoint observations must select the dispatch workflow")
    if case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    from starlette.endpoints import HTTPEndpoint
    from starlette.responses import PlainTextResponse

    endpoint_spec = case["endpoint"]
    _strict_object(endpoint_spec, {"kind", "handlers"}, "HTTP class endpoint input")
    if endpoint_spec["kind"] != "http-class-based-endpoint" or len(endpoint_spec["handlers"]) != 1:
        raise ValueError("HTTPEndpoint input must define one HTTP class handler")
    handler_spec = endpoint_spec["handlers"][0]
    _strict_object(handler_spec, {"name", "call_style", "response"}, "HTTP class endpoint handler")
    response_spec = handler_spec["response"]
    _strict_object(
        response_spec,
        {"kind", "content", "status_code", "media_type"},
        "HTTP class endpoint response",
    )
    if response_spec["kind"] != "plain-text-response" or handler_spec["name"] != "get":
        raise ValueError("HTTPEndpoint direct input must select its GET plain-text handler")

    async def get(_self: Any, _request: Any) -> Any:
        return PlainTextResponse(
            content=response_spec["content"],
            status_code=response_spec["status_code"],
            media_type=response_spec["media_type"],
        )

    endpoint_type = type("InputHTTPEndpoint", (HTTPEndpoint,), {"get": get})
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

    asyncio.run(_await_http_endpoint(endpoint_type, scope, receive, send))
    if incoming_index != len(incoming):
        raise ValueError("HTTPEndpoint dispatch left supplied ASGI input unconsumed")
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
            {"encoding": "base64", "data": base64.b64encode(response_body).decode("ascii")}
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
            {"step_id": HTTP_ENDPOINT_OPERATION, "status": "ok", "value": observation}
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

    from starlette.responses import FileResponse, Response, StreamingResponse
    from starlette.websockets import WebSocket

    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    incoming_index = 0
    callback_tape: list[dict[str, Any]] = []
    pending_send_error: dict[str, Any] | None = None
    file_response_directory: tempfile.TemporaryDirectory[str] | None = None

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
        nonlocal file_response_directory, pending_send_error
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
                elif method == "receive":
                    value = _canonical_websocket_message(await websocket.receive())
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
                    response_kind = response_spec.get("kind", "response")
                    if response_kind == "streaming":

                        async def response_content(
                            chunks: list[str] = response_spec["chunks_base64"],
                        ) -> AsyncIterator[bytes]:
                            for chunk in chunks:
                                yield _decode_b64(chunk, "WebSocket denial stream chunk")

                        response = StreamingResponse(
                            response_content(), status_code=response_spec["status_code"]
                        )
                    elif response_kind == "file":
                        if file_response_directory is None:
                            file_response_directory = tempfile.TemporaryDirectory(
                                prefix="starlette-websocket-denial-parity-"
                            )
                        file_path = Path(file_response_directory.name) / response_spec["filename"]
                        file_path.write_bytes(
                            _decode_b64(
                                response_spec["content_base64"],
                                "WebSocket denial file content",
                            )
                        )
                        os.utime(
                            file_path,
                            (response_spec["mtime_seconds"], response_spec["mtime_seconds"]),
                        )
                        response = FileResponse(file_path, status_code=response_spec["status_code"])
                    else:
                        header_pairs = response_spec["headers_base64_pairs"]
                        response_headers = {
                            _decode_b64(pair[0], "WebSocket denial response header name").decode(
                                "latin-1"
                            ): _decode_b64(
                                pair[1], "WebSocket denial response header value"
                            ).decode("latin-1")
                            for pair in header_pairs
                        }
                        response = Response(
                            content=_decode_b64(
                                response_spec["content_base64"],
                                "WebSocket denial response content",
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

    try:
        action_results = asyncio.run(run_actions())
    finally:
        if file_response_directory is not None:
            file_response_directory.cleanup()
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
    from starlette.middleware import Middleware
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

    middleware = []
    for middleware_spec in case["route"].get("middleware", []):
        header = tuple(value.encode("latin-1") for value in middleware_spec["header"])

        class AppendWebSocketAcceptHeaderMiddleware:
            def __init__(self, app: Any, header_pair: tuple[bytes, bytes]) -> None:
                self.app = app
                self.header_pair = header_pair

            async def __call__(self, middleware_scope: Any, receive: Any, send: Any) -> None:
                async def modified_send(message: dict[str, Any]) -> None:
                    if message["type"] == "websocket.accept":
                        message["headers"].append(self.header_pair)
                    await send(message)

                await self.app(middleware_scope, receive, modified_send)

        middleware.append(Middleware(AppendWebSocketAcceptHeaderMiddleware, header_pair=header))

    route = WebSocketRoute(case["route"]["path"], endpoint=endpoint, middleware=middleware)
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


def _run_http_route_call_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(case, HTTP_ROUTE_CALL_CASE_KEYS, "Route __call__ case")
    if (case["surface"], case["operation"]) != (HTTP_ROUTE_SURFACE, HTTP_ROUTE_CALL_OPERATION):
        raise ValueError("workflow is outside the Route.__call__ operation")
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    endpoint_spec = case["route"]["endpoint"]
    if set(endpoint_spec) != {"kind", "content"} or endpoint_spec["kind"] != (
        "plain-text-response-asgi-app"
    ):
        raise ValueError("Route endpoint input is outside the plain-text ASGI response shape")
    route = Route(case["route"]["path"], endpoint=PlainTextResponse(endpoint_spec["content"]))
    scope = _make_scope(case["scope"])
    incoming = [_message(message) for message in case["incoming"]]
    incoming_index = 0
    sent_messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            raise ValueError("Route.__call__ exhausted its input-only receive sequence")
        message = incoming[incoming_index]
        incoming_index += 1
        return message

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    asyncio.run(route(scope, receive, send))
    if incoming_index != len(incoming):
        raise ValueError("Route.__call__ left input receive messages unconsumed")
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
            "app_present": "app" in scope,
            "router_present": "router" in scope,
            "endpoint_present": "endpoint" in scope,
            "endpoint_is_route_endpoint": scope.get("endpoint") is route.endpoint,
            "path_params_present": "path_params" in scope,
            "path_params": _route_path_params(scope),
        },
        "asgi_events": [_canonical_message(message) for message in sent_messages],
        "response_status": response_start["status"] if response_start is not None else None,
        "response_bytes": (
            {"encoding": "base64", "data": base64.b64encode(response_body).decode("ascii")}
            if response_start is not None
            else None
        ),
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": HTTP_ROUTE_CALL_OPERATION, "status": "ok", "value": available}
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
    router_sequence = is_router and "steps" in case
    if is_router:
        router_keys = common_keys | {
            "custom_convertors",
            "redirect_slashes",
            "routes",
            "observations",
        }
        if "max_body_size" in case:
            router_keys.add("max_body_size")
        router_keys |= {"steps"} if router_sequence else {"scope", "incoming", "send"}
        if "observe_router_scope" in case:
            router_keys.add("observe_router_scope")
        _strict_object(
            case,
            router_keys,
            "Router route-dispatch case",
        )
        if router_sequence:
            step_ids = [step["step_id"] for step in case["steps"]]
            if case["observations"] != step_ids:
                raise ValueError("Router observations must select every dispatch step in order")
        elif case["observations"] != [ROUTER_OPERATION]:
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
    if not router_sequence and case["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    from datetime import datetime

    from starlette.convertors import CONVERTOR_TYPES, Convertor, register_url_convertor
    from starlette.endpoints import HTTPEndpoint
    from starlette.responses import JSONResponse, PlainTextResponse, Response
    from starlette.routing import Host, Mount, Route, Router

    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], _MISSING) for spec in custom_convertors
    }
    route_index_observations: list[int] = []

    for spec in custom_convertors:

        class InputConvertor(Convertor[Any]):
            def __init__(self, raw: dict[str, Any]) -> None:
                self.raw = raw
                self.regex = raw["regex"]

            def convert(self, value: str) -> Any:
                if self.raw.get("kind") == "datetime":
                    # Starlette's converter deliberately returns a naive datetime.
                    return datetime.strptime(value, self.raw["format"])  # noqa: DTZ007
                return value.lower() if self.raw["lowercase"] else value

            def to_string(self, value: Any) -> str:
                if self.raw.get("kind") == "datetime":
                    return value.strftime(self.raw["format"])
                return str(value)

        register_url_convertor(spec["name"], InputConvertor(spec))

    def make_endpoint(endpoint_spec: dict[str, Any], route_index: int) -> Any:
        if endpoint_spec.get("kind") == "request-body-echo":
            _strict_object(endpoint_spec, {"kind"}, "request-body echo endpoint")

            async def request_body_echo(request: Any) -> Any:
                if is_router:
                    route_index_observations.append(route_index)
                return Response(await request.body())

            return request_body_echo

        if endpoint_spec.get("kind") in {"starlette-response", "json-response"}:

            async def fixed_response_endpoint(_request: Any) -> Any:
                if is_router:
                    route_index_observations.append(route_index)
                if endpoint_spec["kind"] == "json-response":
                    return JSONResponse(
                        endpoint_spec["content"], status_code=endpoint_spec["status_code"]
                    )
                return Response(
                    content=endpoint_spec["content"],
                    status_code=endpoint_spec["status_code"],
                    media_type=endpoint_spec["media_type"],
                )

            return fixed_response_endpoint

        if endpoint_spec.get("kind") == "http-class-based-endpoint":
            _strict_object(endpoint_spec, {"kind", "handlers"}, "HTTP class endpoint input")

            def make_response(request: Any, response_spec: dict[str, Any]) -> Any:
                kind = response_spec["kind"]
                if kind == "plain-text-response":
                    _strict_object(
                        response_spec,
                        {"kind", "content", "status_code", "media_type"},
                        "HTTP class endpoint response",
                    )
                    content = response_spec["content"]
                elif kind == "path-parameter-text-response":
                    _strict_object(
                        response_spec,
                        {
                            "kind",
                            "path_parameter",
                            "prefix",
                            "suffix",
                            "status_code",
                            "media_type",
                        },
                        "HTTP class endpoint path-parameter response",
                    )
                    content = (
                        response_spec["prefix"]
                        + str(request.path_params[response_spec["path_parameter"]])
                        + response_spec["suffix"]
                    )
                else:
                    raise ValueError(f"unsupported HTTP class endpoint response: {kind!r}")
                return PlainTextResponse(
                    content=content,
                    status_code=response_spec["status_code"],
                    media_type=response_spec["media_type"],
                )

            class_attributes: dict[str, Any] = {"__module__": __name__}

            def endpoint_init(self: Any, scope: Any, receive: Any, send: Any) -> None:
                HTTPEndpoint.__init__(self, scope, receive, send)
                route_index_observations.append(route_index)

            class_attributes["__init__"] = endpoint_init
            for handler_spec in endpoint_spec["handlers"]:
                _strict_object(
                    handler_spec,
                    {"name", "call_style", "response"},
                    "HTTP class endpoint handler",
                )
                response_spec = handler_spec["response"]
                if handler_spec["call_style"] == "async":

                    async def async_handler(
                        self: Any,
                        request: Any,
                        response_spec: dict[str, Any] = response_spec,
                    ) -> Any:
                        return make_response(request, response_spec)

                    class_attributes[handler_spec["name"]] = async_handler
                else:

                    def sync_handler(
                        self: Any,
                        request: Any,
                        response_spec: dict[str, Any] = response_spec,
                    ) -> Any:
                        return make_response(request, response_spec)

                    class_attributes[handler_spec["name"]] = sync_handler

            EndpointClass = type("InputHTTPEndpoint", (HTTPEndpoint,), class_attributes)
            return EndpointClass

        if endpoint_spec.get("kind") == "sync-plain-text-response":
            _strict_object(
                endpoint_spec,
                {"kind", "content", "status_code", "media_type", "cookies"},
                "synchronous plain-text route response",
            )

            def endpoint(request: Any) -> Any:
                if is_router:
                    route_index_observations.append(route_index)
                response = Response(
                    content=endpoint_spec["content"],
                    status_code=endpoint_spec["status_code"],
                    media_type=endpoint_spec["media_type"],
                )
                for cookie in endpoint_spec["cookies"]:
                    _strict_object(cookie, {"key", "value"}, "route response cookie")
                    response.set_cookie(key=cookie["key"], value=cookie["value"])
                return response

            return endpoint

        if endpoint_spec.get("kind") == "sync-datetime-json-response":
            _strict_object(
                endpoint_spec,
                {"kind", "path_parameter", "format", "json_key", "status_code"},
                "synchronous datetime JSON endpoint",
            )

            def datetime_endpoint(request: Any) -> Any:
                if is_router:
                    route_index_observations.append(route_index)
                value = request.path_params[endpoint_spec["path_parameter"]]
                return JSONResponse(
                    {endpoint_spec["json_key"]: value.strftime(endpoint_spec["format"])},
                    status_code=endpoint_spec["status_code"],
                )

            return datetime_endpoint

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
        if app_spec["kind"] == "router":
            return Router(
                routes=[
                    Route(
                        route_spec["path"],
                        make_endpoint(route_spec["endpoint"], route_index),
                        methods=route_spec["methods"],
                    )
                    for route_spec in app_spec["routes"]
                ]
            )
        if app_spec["kind"] == "scope-path-parameter-json":
            path_parameter = app_spec["path_parameter"]

            async def subdomain_app(scope: Any, receive: Any, send: Any) -> None:
                route_index_observations.append(route_index)
                await JSONResponse({path_parameter: scope["path_params"][path_parameter]})(
                    scope, receive, send
                )

            return subdomain_app

        async def host_app(scope: Any, receive: Any, send: Any) -> None:
            route_index_observations.append(route_index)
            response = PlainTextResponse(
                content=app_spec["content"],
                status_code=app_spec["status_code"],
                media_type=app_spec["media_type"],
            )
            await response(scope, receive, send)

        return host_app

    def make_mount_child(route_spec: dict[str, Any], route_index: int = 0) -> Any:
        kind = route_spec.get("kind") if isinstance(route_spec, dict) else None
        if kind == "mount":
            _strict_object(
                route_spec,
                {"kind", "path", "routes", "max_body_size"}
                if "max_body_size" in route_spec
                else {"kind", "path", "routes"},
                "Nested Mount input",
            )
            nested_routes = route_spec["routes"]
            if not isinstance(nested_routes, list):
                raise ValueError("Nested Mount routes must be an array")
            return Mount(
                route_spec["path"],
                routes=[make_mount_child(child, route_index) for child in nested_routes],
                max_body_size=route_spec.get("max_body_size"),
            )
        if (
            not isinstance(route_spec, dict)
            or frozenset(route_spec)
            not in {
                frozenset({"kind", "path", "methods", "endpoint"}),
                frozenset({"kind", "path", "methods", "endpoint", "max_body_size"}),
            }
            or kind != "http-route"
        ):
            raise ValueError("Mount child input must be a declared http-route or mount record")
        return Route(
            route_spec["path"],
            make_endpoint(route_spec["endpoint"], route_index),
            methods=route_spec["methods"],
            max_body_size=route_spec.get("max_body_size"),
        )

    async def run() -> tuple[Any, dict[str, Any] | None]:
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
                    app_spec = route_spec["app"]
                    if app_spec["kind"] == "plain-text-response":
                        app_spec = _strict_object(
                            app_spec,
                            {"kind", "content", "status_code", "media_type", "cookies"},
                            "Host route app response",
                        )
                        if app_spec["cookies"]:
                            raise ValueError(
                                "Host route app plain-text response cannot set cookies"
                            )
                    elif app_spec["kind"] == "router":
                        _strict_object(app_spec, {"kind", "routes"}, "Host route Router app")
                    elif app_spec["kind"] == "scope-path-parameter-json":
                        _strict_object(
                            app_spec,
                            {"kind", "path_parameter"},
                            "Host path-parameter JSON app",
                        )
                    else:
                        raise ValueError("Host route app kind is unsupported")
                    route_objects.append(
                        Host(
                            route_spec["host"],
                            make_host_app(app_spec, route_index),
                            name=route_spec["name"],
                        )
                    )
                    continue
                if isinstance(route_spec, dict) and route_spec.get("kind") == "mount":
                    route_objects.append(make_mount_child(route_spec, route_index))
                    continue
                if (
                    not isinstance(route_spec, dict)
                    or frozenset(route_spec)
                    not in {
                        frozenset({"kind", "path", "methods", "endpoint"}),
                        frozenset({"kind", "path", "methods", "endpoint", "max_body_size"}),
                    }
                    or route_spec["kind"] != "http-route"
                ):
                    raise ValueError("route input must be a declared http-route record")
                route_objects.append(
                    Route(
                        route_spec["path"],
                        make_endpoint(route_spec["endpoint"], route_index),
                        methods=route_spec["methods"],
                        max_body_size=route_spec.get("max_body_size"),
                    )
                )

        if is_router:
            application = Router(
                routes=route_objects,
                redirect_slashes=case["redirect_slashes"],
                max_body_size=case.get("max_body_size"),
            )
        else:
            mount_spec = case["mount"]
            _strict_object(
                mount_spec,
                {"path", "routes", "max_body_size"}
                if "max_body_size" in mount_spec
                else {"path", "routes"},
                "Mount input",
            )
            application = Mount(
                mount_spec["path"],
                routes=route_objects,
                max_body_size=mount_spec.get("max_body_size"),
            )

        async def dispatch(
            scope_spec: dict[str, Any], incoming_spec: list[dict[str, Any]]
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            scope = _make_scope(scope_spec)
            incoming = [_message(item) for item in incoming_spec]
            incoming_index = 0
            sent: list[dict[str, Any]] = []
            route_observation_start = len(route_index_observations)

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
            declared_limits = [
                int(base64.b64decode(value, validate=True))
                for name, value in scope_spec["headers_base64_pairs"]
                if base64.b64decode(name, validate=True).lower() == b"content-length"
                and base64.b64decode(value, validate=True).isdigit()
            ]
            content_length_precheck_left_body = (
                incoming_index == 0
                and isinstance(case.get("max_body_size"), int)
                and any(length > case["max_body_size"] for length in declared_limits)
            )
            if incoming_index != len(incoming) and not content_length_precheck_left_body:
                raise ValueError("route-dispatch left incoming messages unconsumed")

            events = [_canonical_message(message) for message in sent]
            response_start = next(
                (message for message in sent if message["type"] == "http.response.start"), None
            )
            response_body = b"".join(
                message.get("body", b"")
                for message in sent
                if message["type"] == "http.response.body"
            )
            start_event = next(
                (event for event in events if event["type"] == "http.response.start"), None
            )
            selected = {
                "response_status": (
                    response_start["status"] if response_start is not None else None
                ),
                "ordered_repeated_headers": (
                    start_event["headers"] if start_event is not None else []
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
            if is_router and case.get("observe_router_scope") is True:
                selected["route_scope.path"] = scope.get("path")
                selected["route_scope.root_path"] = scope.get("root_path", "")
                selected["route_scope.app_root_path"] = scope.get("app_root_path")
                selected["route_scope.path_params"] = _route_path_params(scope)
            mount_scope = None
            if is_mount and "app_root_path" in scope:
                mount_scope = {
                    "root_path": scope.get("root_path", ""),
                    "app_root_path": scope.get("app_root_path"),
                    "path_params": _route_path_params(scope),
                }
            if is_router:
                route_indexes = route_index_observations[route_observation_start:]
                if len(route_indexes) > 1:
                    raise RuntimeError("Router dispatched more than one route endpoint")
                selected["route_index"] = route_indexes[0] if route_indexes else None
            return selected, mount_scope

        if router_sequence:
            observations = []
            for step in case["steps"]:
                for mutation in step["mutations"]:
                    if mutation["operation"] == "route-method-add":
                        application.routes[mutation["route_index"]].methods.add(mutation["method"])
                    elif mutation["operation"] == "route-list-append":
                        route_spec = mutation["route"]
                        route_index = len(application.routes)
                        application.routes.append(
                            Route(
                                route_spec["path"],
                                make_endpoint(route_spec["endpoint"], route_index),
                                methods=route_spec["methods"],
                            )
                        )
                    elif mutation["operation"] == "mount-app-add-route":
                        route_spec = mutation["route"]
                        mounted_router = application.routes[mutation["mount_route_index"]].app
                        mounted_router.add_route(
                            route_spec["path"],
                            endpoint=make_endpoint(
                                route_spec["endpoint"], len(mounted_router.routes)
                            ),
                            methods=route_spec["methods"],
                        )
                    else:
                        raise ValueError("unsupported Router route mutation")
                selected, _mount_scope = await dispatch(step["scope"], step["incoming"])
                observations.append({"step_id": step["step_id"], "status": "ok", "value": selected})
            return observations, None

        return await dispatch(case["scope"], case["incoming"])

    try:
        selected, mount_scope = asyncio.run(run())
    finally:
        for name, old_convertor in previous_convertors.items():
            if old_convertor is _MISSING:
                CONVERTOR_TYPES.pop(name, None)
            else:
                CONVERTOR_TYPES[name] = old_convertor

    if router_sequence:
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": selected,
        }

    observation_value = selected
    if is_mount:
        observation_value = {**selected, "mount_scope": mount_scope}
    else:
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
    request_sequence = "calls" in case
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
        "observations",
    }
    if request_sequence:
        case_keys.add("calls")
    else:
        case_keys.update({"scope", "incoming", "send"})
    if "cookie_actions" in case:
        case_keys.add("cookie_actions")
    if "chunk_size" in case:
        case_keys.add("chunk_size")
    if "max_ranges" in case:
        case_keys.add("max_ranges")
    if "header_view_probe" in case:
        case_keys.add("header_view_probe")
    if "scheduling" in case:
        case_keys.add("scheduling")
    if "call_time_field_assignments" in case:
        case_keys.add("call_time_field_assignments")
    if "content_disposition_type" in case:
        case_keys.add("content_disposition_type")
    _strict_object(
        case,
        case_keys,
        "FileResponse asgi-call case",
    )
    if case["surface"] != FILE_RESPONSE_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared FileResponse asgi-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("FileResponse observations must select asgi-call")

    file_spec = case["file"]
    error_path: Path | None = None
    file_kind = "regular"
    if isinstance(file_spec, dict) and file_spec.get("kind") in {"directory", "missing"}:
        file_spec = _strict_object(file_spec, {"kind", "path"}, "FileResponse error path")
        file_kind = file_spec["kind"]
        error_path_text = file_spec["path"]
        if not isinstance(error_path_text, str):
            raise ValueError("FileResponse error path must be a string")
        error_path = Path(error_path_text)
        if (
            not error_path_text
            or "\x00" in error_path_text
            or "\\" in error_path_text
            or error_path.is_absolute()
            or ".." in error_path.parts
        ):
            raise ValueError("FileResponse error path must be a safe relative path")
        if file_kind == "directory" and not error_path.is_dir():
            raise ValueError("FileResponse directory error path is not a directory")
        if file_kind == "missing" and error_path.exists():
            raise ValueError("FileResponse missing-file error path already exists")
        name = error_path.name or error_path.as_posix()
        encoded_contents = ""
        mtime_seconds = 0.0
        contents = b""
    else:
        file_spec = _strict_object(
            file_spec, {"name", "contents_base64", "mtime_seconds"}, "FileResponse file"
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
    content_disposition_type = case.get("content_disposition_type", "attachment")
    if content_disposition_type not in {"attachment", "inline"}:
        raise ValueError("FileResponse content_disposition_type must be attachment or inline")

    if request_sequence:
        if any(
            key in case
            for key in ("header_view_probe", "scheduling", "call_time_field_assignments")
        ):
            raise ValueError(
                "FileResponse call sequences do not combine with header, scheduling, or call-time probes"
            )
        call_specs = case["calls"]
        if not isinstance(call_specs, list) or len(call_specs) < 2:
            raise ValueError("FileResponse calls must contain at least two request inputs")
        for index, call in enumerate(call_specs):
            _strict_object(call, {"scope", "incoming", "send"}, f"FileResponse calls[{index}]")
            if call["incoming"] != [] or call["send"] != {"kind": "capture-asgi-send"}:
                raise ValueError(
                    f"FileResponse calls[{index}] requires empty receive and captured send"
                )
            _strict_object(
                call["scope"],
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
                f"FileResponse calls[{index}].scope",
            )
            if call["scope"]["type"] != "http":
                raise ValueError("FileResponse call sequences require HTTP scopes")
        scope_spec = call_specs[0]["scope"]
    else:
        call_specs = [{"scope": case["scope"], "incoming": case["incoming"], "send": case["send"]}]
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
    if call_specs[0]["incoming"] != []:
        raise ValueError("FileResponse ASGI-call requires an empty incoming stream")
    if call_specs[0]["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")

    scheduling = case.get("scheduling")
    if scheduling is not None:
        _strict_object(
            scheduling,
            {
                "kind",
                "marker_delay_seconds",
                "writer_check_delay_seconds",
                "writer_release_delay_seconds",
                "writer_poll_interval_seconds",
                "writer_timeout_seconds",
                "cleanup_timeout_seconds",
            },
            "FileResponse scheduling probe",
        )
        if scheduling["kind"] != "posix-fifo-loop-marker":
            raise ValueError("FileResponse scheduling.kind is unsupported")
        if os.name != "posix" or not callable(getattr(os, "mkfifo", None)):
            return _file_response_scheduling_skipped(
                case, "the FileResponse event-loop scheduling probe requires POSIX FIFO support"
            )

    from starlette.responses import FileResponse

    with tempfile.TemporaryDirectory(prefix="starlette-file-response-") as directory:
        path = Path(directory) / name
        if file_kind != "regular":
            path = Path(file_spec["path"])
            stat_result = None
        elif scheduling is None:
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
        else:
            try:
                os.mkfifo(path)
            except OSError as exc:
                unavailable_fifo_errors = {
                    errno.ENOSYS,
                    errno.EPERM,
                    errno.EACCES,
                    getattr(errno, "ENOTSUP", errno.EPERM),
                    getattr(errno, "EOPNOTSUPP", errno.EPERM),
                }
                if exc.errno in unavailable_fifo_errors:
                    return _file_response_scheduling_skipped(
                        case,
                        "the temporary filesystem does not provide POSIX FIFO support",
                    )
                raise
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
            content_disposition_type=content_disposition_type,
        )
        for field, value in case.get("call_time_field_assignments", {}).items():
            if field == "path":
                path_spec = value
                value = Path(directory) / path_spec["name"]
                value.write_bytes(
                    _decode_b64(
                        path_spec["contents_base64"],
                        "FileResponse call-time path contents_base64",
                    )
                )
            if field == "stat_result" and value is not None:
                value = os.stat_result(
                    (
                        stat.S_IFREG | 0o644,
                        0,
                        0,
                        1,
                        0,
                        0,
                        value["size"],
                        value["mtime_seconds"],
                        value["mtime_seconds"],
                        value["mtime_seconds"],
                    )
                )
            setattr(response, field, value)
        if "chunk_size" in case:
            response.chunk_size = case["chunk_size"]
        header_view_probe_value = None
        if "header_view_probe" in case:
            header_view_before_reads = [response.headers, response.headers]
            header_view_before = header_view_before_reads[-1]
            raw_headers_before = response.raw_headers
            view_raw_before = header_view_before.raw
            header_view_probe_value = {
                "cached_property_object_before_call": all(
                    view is header_view_before_reads[0] for view in header_view_before_reads
                ),
                "response_raw_header_list_alias_before_call": view_raw_before is raw_headers_before,
                "response_raw_headers_before_call": _raw_header_pairs_snapshot(raw_headers_before),
                "header_view_raw_before_call": _raw_header_pairs_snapshot(view_raw_before),
            }
        for index, raw_action in enumerate(case.get("cookie_actions", [])):
            _apply_response_cookie_action(response, raw_action, index)
        if request_sequence:

            async def run_call_sequence() -> list[dict[str, Any]]:
                observations = []
                for call_spec in call_specs:
                    call_scope = _make_scope(call_spec["scope"])
                    call_sent: list[dict[str, Any]] = []

                    async def call_receive() -> dict[str, Any]:
                        return {"type": "http.disconnect"}

                    async def call_send(
                        message: dict[str, Any], captured: list[dict[str, Any]] = call_sent
                    ) -> None:
                        captured.append(message)

                    await response(call_scope, call_receive, call_send)
                    call_events = [_canonical_message(message) for message in call_sent]
                    call_start = next(
                        (
                            message
                            for message in call_sent
                            if message["type"] == "http.response.start"
                        ),
                        None,
                    )
                    call_start_event = next(
                        (event for event in call_events if event["type"] == "http.response.start"),
                        None,
                    )
                    call_body = b"".join(
                        message.get("body", b"")
                        for message in call_sent
                        if message["type"] == "http.response.body"
                    )
                    observations.append(
                        {
                            "response_status": (
                                call_start["status"] if call_start is not None else None
                            ),
                            "ordered_repeated_headers": (
                                call_start_event["headers"] if call_start_event is not None else []
                            ),
                            "response_bytes": {
                                "encoding": "base64",
                                "data": base64.b64encode(call_body).decode("ascii"),
                            },
                            "asgi_event_order": [event["type"] for event in call_events],
                            "asgi_events": call_events,
                        }
                    )
                return observations

            response_sequence = asyncio.run(run_call_sequence())
            return {
                "case_id": case["case_id"],
                "status": "completed",
                "observations": [
                    {
                        "step_id": RESPONSE_OPERATION,
                        "status": "ok",
                        "value": {"responses": response_sequence},
                    }
                ],
            }
        scope = _make_scope(scope_spec)
        sent: list[dict[str, Any]] = []
        event_loop_scheduling: dict[str, bool] | None = None
        writer_process: subprocess.Popen[str] | None = None

        async def receive() -> dict[str, Any]:
            return {"type": "http.disconnect"}

        captured_dispatch_error: dict[str, Any] | None = None
        if scheduling is None:

            async def send(message: dict[str, Any]) -> None:
                sent.append(message)

            try:
                asyncio.run(response(scope, receive, send))
            except Exception as exc:
                if file_kind == "regular":
                    raise
                captured_dispatch_error = _dispatch_error(exc)
        else:
            start_marker_path = Path(directory) / "response-started"
            loop_marker_path = Path(directory) / "event-loop-marker"
            marker_state = {"ran": False}
            writer_configuration = json.dumps(scheduling, separators=(",", ":"))
            writer_process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _FILE_RESPONSE_FIFO_WRITER_SCRIPT,
                    os.fspath(path),
                    os.fspath(start_marker_path),
                    os.fspath(loop_marker_path),
                    encoded_contents,
                    writer_configuration,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            async def invoke_with_loop_marker() -> None:
                response_started = asyncio.Event()

                async def marker_task() -> None:
                    await response_started.wait()
                    await asyncio.sleep(scheduling["marker_delay_seconds"])
                    loop_marker_path.touch()
                    marker_state["ran"] = True

                async def send(message: dict[str, Any]) -> None:
                    sent.append(message)
                    if message["type"] == "http.response.start":
                        start_marker_path.touch()
                        response_started.set()

                marker = asyncio.create_task(marker_task())
                try:
                    await response(scope, receive, send)
                finally:
                    if response_started.is_set():
                        await marker
                    else:
                        marker.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await marker

            try:
                asyncio.run(invoke_with_loop_marker())
                try:
                    writer_stdout, writer_stderr = writer_process.communicate(
                        timeout=scheduling["cleanup_timeout_seconds"]
                    )
                except subprocess.TimeoutExpired as exc:
                    writer_process.terminate()
                    try:
                        writer_process.communicate(timeout=scheduling["cleanup_timeout_seconds"])
                    except subprocess.TimeoutExpired:
                        writer_process.kill()
                        writer_process.communicate(timeout=scheduling["cleanup_timeout_seconds"])
                    raise RuntimeError(
                        "FileResponse FIFO writer did not finish within its input timeout"
                    ) from exc
                if writer_process.returncode != 0:
                    raise RuntimeError(
                        "FileResponse FIFO writer failed: "
                        f"{writer_stderr.strip() or writer_stdout.strip()}"
                    )
                try:
                    writer_result = json.loads(writer_stdout)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "FileResponse FIFO writer returned invalid result data"
                    ) from exc
                if (
                    not isinstance(writer_result, dict)
                    or type(writer_result.get("marker_present_at_check")) is not bool
                    or type(writer_result.get("bytes_written")) is not int
                ):
                    raise RuntimeError("FileResponse FIFO writer returned an invalid result shape")
                if writer_result["bytes_written"] != len(contents):
                    raise RuntimeError(
                        "FileResponse FIFO writer did not write the full input payload"
                    )
                event_loop_scheduling = {
                    "marker_task_ran": marker_state["ran"],
                    "marker_ran_before_writer_pre_release_check": writer_result[
                        "marker_present_at_check"
                    ],
                }
            finally:
                if writer_process.poll() is None:
                    writer_process.terminate()
                    try:
                        writer_process.communicate(timeout=scheduling["cleanup_timeout_seconds"])
                    except subprocess.TimeoutExpired:
                        writer_process.kill()
                        writer_process.communicate(timeout=scheduling["cleanup_timeout_seconds"])
        if header_view_probe_value is not None:
            header_view_after = response.headers
            header_view_probe_value.update(
                {
                    "cached_property_object_after_call": header_view_after is header_view_before,
                    "raw_property_object_after_call": header_view_after.raw is view_raw_before,
                    "response_raw_header_list_alias_after_call": (
                        header_view_after.raw is response.raw_headers
                    ),
                    "response_raw_headers_after_call": _raw_header_pairs_snapshot(
                        response.raw_headers
                    ),
                    "header_view_raw_after_call": _raw_header_pairs_snapshot(header_view_after.raw),
                }
            )
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
            "dispatch_error": captured_dispatch_error,
        }
        if header_view_probe_value is not None:
            observation["header_view_probe"] = header_view_probe_value
        if event_loop_scheduling is not None:
            observation["event_loop_scheduling"] = event_loop_scheduling
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": RESPONSE_OPERATION, "status": "ok", "value": observation}],
    }


def _file_response_scheduling_skipped(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "skipped",
        "observations": [{"step_id": RESPONSE_OPERATION, "status": "skipped", "reason": reason}],
    }


_FILE_RESPONSE_FIFO_WRITER_SCRIPT = r"""
import base64
import errno
import json
import os
import sys
import time

fifo_path, start_marker_path, loop_marker_path, payload_base64, raw_configuration = sys.argv[1:]
configuration = json.loads(raw_configuration)
poll_interval = configuration["writer_poll_interval_seconds"]
writer_timeout = configuration["writer_timeout_seconds"]

try:
    writer_deadline = time.monotonic() + writer_timeout
    start_marker_seen = False
    while time.monotonic() < writer_deadline:
        if os.path.exists(start_marker_path):
            start_marker_seen = True
            break
        time.sleep(poll_interval)

    if start_marker_seen:
        start_time = time.monotonic()
        check_delay = configuration["writer_check_delay_seconds"]
        if time.monotonic() + check_delay >= writer_deadline:
            time.sleep(max(0, writer_deadline - time.monotonic()))
            raise TimeoutError("writer deadline elapsed before the pre-release check")
        time.sleep(check_delay)
        marker_present_at_check = os.path.exists(loop_marker_path)
        remaining_release_delay = configuration["writer_release_delay_seconds"] - (
            time.monotonic() - start_time
        )
        if remaining_release_delay > 0:
            if time.monotonic() + remaining_release_delay >= writer_deadline:
                time.sleep(max(0, writer_deadline - time.monotonic()))
                raise TimeoutError("writer deadline elapsed before FIFO release")
            time.sleep(remaining_release_delay)
    else:
        # A reader may be blocked before it can send response-start; try one
        # nonblocking fallback open, then fail promptly if no reader is waiting.
        marker_present_at_check = os.path.exists(loop_marker_path)

    while True:
        try:
            descriptor = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
            break
        except OSError as error:
            if error.errno not in {errno.ENXIO, errno.EAGAIN}:
                raise
            if not start_marker_seen:
                raise TimeoutError(
                    "response start marker was absent and no FIFO reader was waiting"
                ) from error
            if time.monotonic() >= writer_deadline:
                raise TimeoutError("FIFO reader did not open before writer timeout") from error
            time.sleep(poll_interval)

    payload = base64.b64decode(payload_base64, validate=True)
    bytes_written = 0
    try:
        while bytes_written < len(payload):
            written = os.write(descriptor, payload[bytes_written:])
            if written <= 0:
                raise OSError("FIFO writer made no progress")
            bytes_written += written
    finally:
        os.close(descriptor)

    print(
        json.dumps(
            {
                "marker_present_at_check": marker_present_at_check,
                "bytes_written": bytes_written,
            }
        )
    )
except BaseException as error:
    print(json.dumps({"error": type(error).__name__, "message": str(error)}))
    sys.exit(2)
"""


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


def _run_static_files_configuration_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.staticfiles import StaticFiles

    return run_static_files_configuration_case(
        case,
        StaticFiles,
        make_scope=_make_scope,
        canonical_message=_canonical_message,
    )


def _run_static_files_case(case: dict[str, Any]) -> dict[str, Any]:
    request_sequence = "calls" in case
    expected_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "directory",
        "path_limit_stress",
        "permission_denial_stress",
        "filesystem",
        "packages",
        "files",
        "html",
        "check_dir",
        "follow_symlink",
        "observations",
    }
    if request_sequence:
        expected_fields.add("calls")
    else:
        expected_fields.update({"scope", "incoming", "send"})
    _strict_object(
        case,
        expected_fields,
        "StaticFiles asgi-call case",
    )
    if case["surface"] != STATIC_FILES_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared StaticFiles asgi-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("StaticFiles observations must select asgi-call")
    if request_sequence:
        call_specs = case["calls"]
        if not isinstance(call_specs, list) or len(call_specs) < 2:
            raise ValueError("StaticFiles calls must contain at least two request inputs")
        if (
            case["path_limit_stress"] is not None
            or case["permission_denial_stress"] is not None
            or case["filesystem"] is not None
        ):
            raise ValueError(
                "StaticFiles request sequences do not combine with stress or filesystem inputs"
            )
        for index, call in enumerate(call_specs):
            _strict_object(call, {"scope", "incoming", "send"}, f"StaticFiles calls[{index}]")
            if call["incoming"] != [] or call["send"] != {"kind": "capture-asgi-send"}:
                raise ValueError("StaticFiles calls require empty receive and captured send")
    else:
        call_specs = [{"scope": case["scope"], "incoming": case["incoming"], "send": case["send"]}]

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
        filesystem = case["filesystem"]
        if filesystem is not None and case["packages"]:
            raise ValueError("StaticFiles filesystem scenarios cannot include package roots")
        if filesystem is not None and filesystem["root_symlink_target"] is not None:
            target_directory = workspace / filesystem["root_symlink_target"]
            target_directory.mkdir(parents=True, exist_ok=True)
            os.symlink(os.path.relpath(target_directory, root.parent), root)
        elif case["path_limit_stress"] is not None:
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
        if filesystem is not None:
            for directory in filesystem["directories"]:
                (workspace / directory).mkdir(parents=True, exist_ok=True)
            for file_spec in filesystem["outside_files"]:
                path = workspace / file_spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    _decode_b64(file_spec["contents_base64"], "StaticFiles outside file")
                )
                os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
            for symlink_spec in filesystem["symlinks"]:
                path = root / symlink_spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(symlink_spec["target"], path)
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
            if request_sequence:

                async def observe_call(call: dict[str, Any]) -> dict[str, Any]:
                    scope = _make_scope(call["scope"])
                    sent: list[dict[str, Any]] = []

                    async def receive() -> dict[str, Any]:
                        return {"type": "http.disconnect"}

                    async def send(message: dict[str, Any]) -> None:
                        sent.append(message)

                    captured_error: Exception | None = None
                    try:
                        await application(scope, receive, send)
                    except Exception as exc:
                        if not isinstance(exc, HTTPException):
                            raise
                        captured_error = exc
                    events = [_canonical_message(message) for message in sent]
                    response_start = next(
                        (message for message in sent if message["type"] == "http.response.start"),
                        None,
                    )
                    response_start_event = next(
                        (event for event in events if event["type"] == "http.response.start"),
                        None,
                    )
                    response_body = b"".join(
                        message.get("body", b"")
                        for message in sent
                        if message["type"] == "http.response.body"
                    )
                    observation = {
                        "response_status": (
                            response_start["status"] if response_start is not None else None
                        ),
                        "ordered_repeated_headers": (
                            response_start_event["headers"]
                            if response_start_event is not None
                            else []
                        ),
                        "response_bytes": {
                            "encoding": "base64",
                            "data": base64.b64encode(response_body).decode("ascii"),
                        },
                        "asgi_event_order": [event["type"] for event in events],
                        "asgi_events": events,
                    }
                    if captured_error is None:
                        return {"status": "ok", "value": observation}
                    error = _dispatch_error(captured_error)
                    error["code"] = captured_error.status_code
                    return {
                        "status": "error",
                        "error": error,
                        "partial_value": observation,
                    }

                async def observe_sequence() -> list[dict[str, Any]]:
                    results = []
                    for call in call_specs:
                        results.append(await observe_call(call))
                    return results

                request_observations = asyncio.run(observe_sequence())
                return {
                    "case_id": case["case_id"],
                    "status": "completed",
                    "observations": [
                        {
                            "step_id": RESPONSE_OPERATION,
                            "status": "ok",
                            "value": {"requests": request_observations},
                        }
                    ],
                }
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


def _apply_response_header_action(response: Any, raw_action: dict[str, Any], index: int) -> None:
    context = f"Response header_actions[{index}]"
    action = _strict_object(raw_action, {"kind", "key", "value"}, context)
    if action["kind"] != "set":
        raise ValueError(f"{context}.kind must be set")
    response.headers[action["key"]] = action["value"]


def _raw_header_pairs_snapshot(raw_headers: Any) -> list[list[str]]:
    return [
        [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
        for name, value in raw_headers
    ]


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
    if "header_actions" in case:
        required_fields.add("header_actions")
    if "header_view_probe" in case:
        required_fields.add("header_view_probe")
    if "background" in case:
        required_fields.add("background")
    if "background_control" in case:
        required_fields.add("background_control")
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
        if content_kind == "file-like-bytes":
            encoded_content = content_spec["value"]
            if not isinstance(encoded_content, str):
                raise ValueError("StreamingResponse file-like content must be base64 text")
            content = io.BytesIO(_decode_b64(encoded_content, "content.value"))
        else:
            if content_kind not in {"chunks", "repeating-chunks"} or not isinstance(
                content_spec["value"], list
            ):
                raise ValueError("StreamingResponse content must select an array of chunks")
            repeating_stream = content_kind == "repeating-chunks"
            if repeating_stream and not content_spec["value"]:
                raise ValueError(
                    "StreamingResponse repeating content must contain at least one chunk"
                )
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
                        raise ValueError(
                            "StreamingResponse memoryview chunks must be base64 strings"
                        )
                    chunk = memoryview(_decode_b64(encoded_chunk, f"content.value[{index}].value"))
                else:
                    raise ValueError(
                        "StreamingResponse chunks must be text, bytes, or memoryview input"
                    )
                content.append(chunk)
        streaming = case["streaming"]
        if streaming not in {
            "sync",
            "file-like",
            "async-iterator",
            "async-iterable",
            "async-generator",
        }:
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

    scope_fields = {
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
    }
    if case["scope"].get("type") == "http":
        scope_fields.add("method")
    elif case["scope"].get("type") == "websocket":
        scope_fields.add("subprotocols")
    else:
        raise ValueError("Response ASGI-call requires an HTTP or WebSocket scope")
    scope_spec = _strict_object(case["scope"], scope_fields, "Response ASGI-call scope")
    if scope_spec["type"] == "websocket" and surface != STREAMING_RESPONSE_SURFACE:
        raise ValueError("WebSocket scope is supported only for StreamingResponse")
    asgi_spec = _strict_object(scope_spec["asgi"], {"version", "spec_version"}, "ASGI version")
    if any(not isinstance(asgi_spec[key], str) for key in asgi_spec):
        raise ValueError("ASGI versions must be strings")
    scope_string_fields = ["http_version", "scheme", "path", "root_path"]
    if scope_spec["type"] == "http":
        scope_string_fields.append("method")
    for field in scope_string_fields:
        if not isinstance(scope_spec[field], str):
            raise ValueError(f"Response scope.{field} must be a string")
    if scope_spec["type"] == "websocket" and (
        not isinstance(scope_spec["subprotocols"], list)
        or any(not isinstance(item, str) for item in scope_spec["subprotocols"])
    ):
        raise ValueError("Response WebSocket scope subprotocols must be strings")
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
    background_tasks_spec: dict[str, Any] | None = None
    background_control: dict[str, str] | None = None
    if "background_control" in case:
        background_control = _strict_object(
            case["background_control"], {"kind"}, "Response background control"
        )
        if background_control["kind"] != "cancel-after-task-start" or surface != RESPONSE_SURFACE:
            raise ValueError("Response background control is unsupported")
    if "background" in case:
        if not isinstance(case["background"], dict):
            raise ValueError("Response background input must be an object")
        if case["background"].get("kind") == "async-values-recorder":
            background_spec = _strict_object(
                case["background"], {"kind", "values"}, "Response background"
            )
            values = background_spec["values"]
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("Response background values must be an array of strings")
            background_values = values
        else:
            background_tasks_spec = _strict_object(
                case["background"], {"kind", "tasks"}, "Response background tasks"
            )
            if background_tasks_spec["kind"] not in {
                "single-task",
                "task-list",
                "task-list-constructor",
            }:
                raise ValueError("Response background task kind is unsupported")
            if not isinstance(background_tasks_spec["tasks"], list):
                raise ValueError("Response background tasks must be an array")

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
        receive_behavior_value = case["receive_behavior"]
        if not isinstance(receive_behavior_value, dict):
            raise ValueError("Response receive behavior input must be an object")
        if receive_behavior_value.get("kind") == "disconnect-after-body-bytes":
            receive_behavior = _strict_object(
                receive_behavior_value,
                {"kind", "minimum_body_bytes"},
                "Response receive behavior",
            )
            if (
                type(receive_behavior["minimum_body_bytes"]) is not int
                or receive_behavior["minimum_body_bytes"] < 1
            ):
                raise ValueError("Response receive behavior input is invalid")
        elif receive_behavior_value.get("kind") == "raise-not-implemented":
            receive_behavior = _strict_object(
                receive_behavior_value,
                {"kind"},
                "Response receive behavior",
            )
        else:
            raise ValueError("Response receive behavior input is invalid")

    execution_trace = (
        [] if streaming == "async-generator" or background_values is not None else None
    )
    background_execution_trace = (
        []
        if background_tasks_spec is not None
        or (
            surface == STREAMING_RESPONSE_SURFACE
            and case["operation"] == STREAMING_RESPONSE_TRACE_OPERATION
        )
        else None
    )
    event_loop_thread_id: list[int | None] = [None]
    background_started = asyncio.Event() if background_control is not None else None
    synchronous_background_control = (
        background_control is not None
        and background_tasks_spec is not None
        and any(
            isinstance(task, dict) and task.get("mode") == "sync"
            for task in background_tasks_spec["tasks"]
        )
    )
    background_release = threading.Event() if synchronous_background_control else None
    background_event_loop: list[asyncio.AbstractEventLoop | None] = [None]

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
    if background_tasks_spec is not None:
        if background_execution_trace is None:
            raise RuntimeError("background tasks require an execution trace")
        response_arguments["background"] = _input_background_tasks(
            background_tasks_spec,
            background_execution_trace,
            event_loop_thread_id,
            background_started,
            background_release,
            background_event_loop,
        )
    response = response_type(**response_arguments)
    try:
        for index, raw_action in enumerate(case.get("header_actions", [])):
            _apply_response_header_action(response, raw_action, index)
        for index, raw_action in enumerate(case.get("cookie_actions", [])):
            _apply_response_cookie_action(response, raw_action, index)
        header_view_probe_value = None
        if "header_view_probe" in case:
            probe = case["header_view_probe"]
            header_views = [response.headers for _ in range(probe["read_count"])]
            raw_headers_before = response.raw_headers
            header_view_probe_value = {
                "cached_property_object": all(view is header_views[0] for view in header_views),
                "raw_property_object": all(
                    view.raw is header_views[0].raw for view in header_views
                ),
                "response_raw_header_list_alias": header_views[0].raw is raw_headers_before,
                "response_raw_headers_before": _raw_header_pairs_snapshot(raw_headers_before),
            }
            for pair_index, pair in enumerate(probe["raw_append_base64_pairs"]):
                header_views[-1].raw.append(
                    (
                        _decode_b64(pair[0], f"Response header_view_probe[{pair_index}].name"),
                        _decode_b64(pair[1], f"Response header_view_probe[{pair_index}].value"),
                    )
                )
            header_view_probe_value["response_raw_headers_after"] = _raw_header_pairs_snapshot(
                response.raw_headers
            )
            header_view_probe_value["header_view_raw_after"] = _raw_header_pairs_snapshot(
                header_views[-1].raw
            )
    except Exception as exc:
        partial_value = {
            "response_status": None,
            "ordered_repeated_headers": [],
            "response_bytes": {"encoding": "base64", "data": ""},
            "asgi_event_order": [],
            "asgi_events": [],
        }
        if surface == RESPONSE_SURFACE or (
            surface == STREAMING_RESPONSE_SURFACE
            and case["operation"] == STREAMING_RESPONSE_TRACE_OPERATION
        ):
            partial_value["background_execution_trace"] = background_execution_trace
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {
                    "step_id": case["observations"][0],
                    "status": "error",
                    "error": _dispatch_error(exc),
                    "partial_value": partial_value,
                }
            ],
        }
    scope = _make_scope(scope_spec)
    sent: list[dict[str, Any]] = []
    receive_gate = (
        asyncio.Event()
        if receive_behavior is not None
        and receive_behavior["kind"] == "disconnect-after-body-bytes"
        else None
    )
    sent_body_bytes = 0

    async def receive() -> dict[str, Any]:
        if receive_behavior is not None and receive_behavior["kind"] == "raise-not-implemented":
            raise NotImplementedError
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
        if background_execution_trace is not None:
            if event_loop_thread_id[0] is None:
                event_loop_thread_id[0] = threading.get_ident()
            background_execution_trace.append(
                {"event": "asgi-send", "message": _canonical_message(message)}
            )
        if execution_trace is not None:
            execution_trace.append({"event": "asgi-send", "message": _canonical_message(message)})
        if (
            receive_behavior is not None
            and receive_behavior["kind"] == "disconnect-after-body-bytes"
            and message["type"] == "http.response.body"
        ):
            sent_body_bytes += len(message.get("body", b""))
            if sent_body_bytes >= receive_behavior["minimum_body_bytes"]:
                if receive_gate is None:
                    raise RuntimeError("disconnect receive behavior has no receive gate")
                receive_gate.set()
        send_index += 1

    captured_error: BaseException | None = None
    try:
        if background_control is None:
            asyncio.run(response(scope, receive, send))
        else:

            async def dispatch_and_cancel_background() -> None:
                if background_started is None:
                    raise RuntimeError("background cancellation event is unavailable")
                background_event_loop[0] = asyncio.get_running_loop()
                response_task = asyncio.create_task(response(scope, receive, send))
                try:
                    await asyncio.wait_for(background_started.wait(), timeout=5.0)
                except BaseException:
                    response_task.cancel()
                    if background_release is not None:
                        background_release.set()
                    try:
                        await response_task
                    except BaseException:
                        pass
                    raise
                response_task.cancel()
                if synchronous_background_control:
                    await asyncio.sleep(0)
                    if background_execution_trace is None or background_release is None:
                        raise RuntimeError(
                            "synchronous background cancellation state is unavailable"
                        )
                    background_execution_trace.append({"event": "response-cancellation-requested"})
                    background_release.set()
                await response_task

            try:
                asyncio.run(dispatch_and_cancel_background())
            except asyncio.CancelledError as exc:
                captured_error = exc
    except Exception as exc:
        if send_error_spec is None and background_tasks_spec is None:
            raise
        captured_error = exc
    events = [_canonical_message(message) for message in sent]
    response_prefix = (
        "websocket.http.response" if scope_spec["type"] == "websocket" else "http.response"
    )
    response_start_type = f"{response_prefix}.start"
    response_body_type = f"{response_prefix}.body"
    response_start = next(
        (message for message in sent if message["type"] == response_start_type), None
    )
    response_start_event = next(
        (event for event in events if event["type"] == response_start_type), None
    )
    response_body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == response_body_type
    )
    observation = {
        "response_status": response_start["status"] if response_start is not None else None,
        "ordered_repeated_headers": (
            response_start_event.get(
                "headers", response_start_event.get("headers_base64_pairs", [])
            )
            if response_start_event is not None
            else []
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
    if surface == RESPONSE_SURFACE or (
        surface == STREAMING_RESPONSE_SURFACE
        and case["operation"] == STREAMING_RESPONSE_TRACE_OPERATION
    ):
        observation["background_execution_trace"] = background_execution_trace
    if header_view_probe_value is not None:
        observation["header_view_probe"] = header_view_probe_value
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


def _build_reverse_route_middleware(specs: list[dict[str, Any]]) -> list[Any]:
    from starlette.middleware import Middleware

    configurations = []
    for spec in specs:
        if spec["kind"] == "append-response-header":

            class InputAppendResponseHeaderMiddleware:
                def __init__(self, app: Any, *, name: str) -> None:
                    self.app = app
                    self.response_header = (f"X-{name}".encode("ascii"), b"true")

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    async def modified_send(message: Any) -> None:
                        if message["type"] == "http.response.start":
                            message["headers"].append(self.response_header)
                        await send(message)

                    await self.app(scope, receive, modified_send)

            configurations.append(
                Middleware(InputAppendResponseHeaderMiddleware, name=spec["name"])
            )
            continue

        class InputScopeAndResponseHeaderMiddleware:
            def __init__(
                self,
                app: Any,
                *,
                scope_key: str,
                scope_value: Any,
                response_header: list[str],
            ) -> None:
                self.app = app
                self.scope_key = scope_key
                self.scope_value = scope_value
                self.response_header = tuple(value.encode("latin-1") for value in response_header)

            async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
                scope[self.scope_key] = self.scope_value

                async def modified_send(message: dict[str, Any]) -> None:
                    if message["type"] == "http.response.start":
                        message["headers"].append(self.response_header)
                    await send(message)

                await self.app(scope, receive, modified_send)

        configurations.append(
            Middleware(
                InputScopeAndResponseHeaderMiddleware,
                scope_key=spec["scope_key"],
                scope_value=spec["scope_value"],
                response_header=spec["response_header"],
            )
        )
    return configurations


def _build_reverse_route_node(
    node: dict[str, Any],
    lookup: dict[str, Any],
    observation: dict[str, Any],
) -> Any:
    from starlette.responses import JSONResponse, Response
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
        mount_arguments = {}
        if "middleware" in node:
            mount_arguments["middleware"] = _build_reverse_route_middleware(node["middleware"])
        if "app" in node:

            async def no_op_asgi(scope: Any, receive: Any, send: Any) -> None:
                del scope, receive, send

            return Mount(node["path"], app=no_op_asgi, name=node["name"], **mount_arguments)
        return Mount(
            node["path"],
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ],
            name=node["name"],
            **mount_arguments,
        )
    if kind == "starlette-app":
        from starlette.applications import Starlette

        return Starlette(
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ]
        )
    if kind == "host-route":
        if "app" in node:
            path_parameter = node["app"]["path_parameter"]

            async def host_app(scope: Any, receive: Any, send: Any) -> None:
                await JSONResponse({path_parameter: scope["path_params"][path_parameter]})(
                    scope, receive, send
                )

            app = host_app
        else:
            app = Router(
                routes=[
                    _build_reverse_route_node(child, lookup, observation)
                    for child in node["routes"]
                ]
            )
        return Host(
            node["host"],
            app=app,
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
    from datetime import datetime

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

            class InputConvertor(Convertor[Any]):
                def __init__(self, raw: dict[str, Any]) -> None:
                    self.raw = raw
                    self.regex = raw["regex"]

                def convert(self, value: str) -> Any:
                    if self.raw.get("kind") == "datetime":
                        # Starlette's converter deliberately returns a naive datetime.
                        return datetime.strptime(value, self.raw["format"])  # noqa: DTZ007
                    return value.lower() if self.raw["lowercase"] else value

                def to_string(self, value: Any) -> str:
                    if self.raw.get("kind") == "datetime":
                        return value.strftime(self.raw["format"])
                    text = str(value)
                    return text.lower() if self.raw["lowercase_to_string"] else text

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
            path_params = {
                name: datetime(*value["components"])  # noqa: DTZ001
                if isinstance(value, dict)
                else value
                for name, value in lookup["path_params"].items()
            }
            if case["surface"] == "starlette.routing.Route":
                result = graph.url_path_for(lookup["name"], **path_params)
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
        "sync_endpoint_observations": None,
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
        "sync_endpoint_observations": None,
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


def _run_request_form_case(case: dict[str, Any]) -> dict[str, Any]:
    case_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "scope",
        "receive",
        "form_probe_keys",
        "observations",
    }
    if "form_options" in case:
        case_fields.add("form_options")
    if "form_access" in case:
        case_fields.add("form_access")
    for key in (
        "form_file_probe_keys",
        "form_file_probe_all",
        "form_type_probe_keys",
        "form_file_read_size",
        "form_file_write_base64",
        "form_close",
        "form_io_trace",
        "receive_error",
        "file_write_error",
        "form_app",
        "form_read_body",
    ):
        if key in case:
            case_fields.add(key)
    _strict_object(
        case,
        case_fields,
        "Request form case",
    )
    from starlette.datastructures import UploadFile
    from starlette.requests import Request

    scope = _make_scope(case["scope"])
    incoming = [_request_form_message(message) for message in case["receive"]]
    received = 0
    io_trace: list[list[Any]] = []
    tracked_tempfiles: list[Any] = []
    tempfile_write_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal received
        call_index = received
        received += 1
        if case.get("form_io_trace", False):
            io_trace.append(["receive", call_index])
        receive_error = case.get("receive_error")
        if receive_error is not None and call_index == receive_error["at_call"]:
            raise RuntimeError(receive_error["message"])
        return incoming[call_index]

    async def observe() -> dict[str, Any]:
        request = Request(scope, receive)
        file_observations = []
        observed_files = []
        try:
            if case.get("form_access", "await") == "context-manager":
                async with request.form(**case.get("form_options", {})) as form:
                    value, observed_files = await inspect_form(form)
            else:
                form = await request.form(**case.get("form_options", {}))
                value, observed_files = await inspect_form(form)
                if case.get("form_close", False):
                    await form.close()
        except Exception as exc:
            fields = {
                name: _json_safe(getattr(exc, name))
                for name in ("status_code", "detail", "headers", "message")
                if hasattr(exc, name)
            }
            return {
                "form": {
                    "outcome": "error",
                    "error": {
                        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                        "message": str(exc),
                        "fields": fields,
                    },
                    "receive_calls": received,
                    **(
                        {
                            "io_trace": io_trace,
                            "temp_files_closed": [file.closed for file in tracked_tempfiles],
                        }
                        if case.get("form_io_trace", False)
                        else {}
                    ),
                },
            }
        for key, upload, observation in observed_files:
            observation["closed_after_form_scope"] = upload.file.closed
            file_observations.append([key, observation])
        if "form_file_probe_keys" in case or case.get("form_file_probe_all", False):
            value["files"] = file_observations
        value["receive_calls"] = received
        if case.get("form_io_trace", False):
            value["io_trace"] = io_trace
            value["temp_files_closed"] = [file.closed for file in tracked_tempfiles]
        return {"form": value}

    async def observe_application() -> dict[str, Any]:
        from starlette.responses import JSONResponse

        response_messages: list[dict[str, Any]] = []
        application_form: dict[str, Any] | None = None
        application_error: dict[str, Any] | None = None
        cached_body: bytes | None = None

        async def request_form_app(
            app_scope: dict[str, Any],
            app_receive: Any,
            app_send: Any,
        ) -> None:
            nonlocal application_error, application_form, cached_body
            request = Request(app_scope, app_receive)
            if case.get("form_read_body", False):
                cached_body = await request.body()
            try:
                form = await request.form(**case.get("form_options", {}))
            except Exception as exc:
                application_error = {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                    "fields": {
                        name: _json_safe(getattr(exc, name))
                        for name in ("status_code", "detail", "headers", "message")
                        if hasattr(exc, name)
                    },
                }
                raise

            value, observed_files = await inspect_form(form)
            if case.get("form_close", False):
                await request.close()
            file_observations = []
            for key, upload, observation in observed_files:
                observation["closed_after_form_scope"] = upload.file.closed
                file_observations.append([key, observation])
            if "form_file_probe_keys" in case or case.get("form_file_probe_all", False):
                value["files"] = file_observations
            value["receive_calls"] = received
            if case.get("form_io_trace", False):
                value["io_trace"] = io_trace
                value["temp_files_closed"] = [file.closed for file in tracked_tempfiles]
            application_form = value
            content = {"form": value}
            if cached_body is not None:
                content["body_base64"] = base64.b64encode(cached_body).decode("ascii")
            await JSONResponse(content)(app_scope, app_receive, app_send)

        async def send(message: dict[str, Any]) -> None:
            response_messages.append(_canonical_message(message))

        app: Any = request_form_app
        if case["form_app"] == "mount":
            from starlette.applications import Starlette
            from starlette.routing import Mount

            app = Starlette(routes=[Mount("/", app=request_form_app)])

        try:
            await app(scope, receive, send)
        except Exception as exc:
            if application_error is None:
                application_error = {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                    "fields": {
                        name: _json_safe(getattr(exc, name))
                        for name in ("status_code", "detail", "headers", "message")
                        if hasattr(exc, name)
                    },
                }

        if application_error is None:
            outcome = "response"
        elif response_messages:
            outcome = "handled-error"
        else:
            outcome = "raised-error"
        value: dict[str, Any] = {
            "outcome": outcome,
            "form": application_form,
            "error": application_error,
            "body_read_base64": (
                base64.b64encode(cached_body).decode("ascii") if cached_body is not None else None
            ),
            "response_events": response_messages,
            "receive_calls": received,
        }
        if case.get("form_io_trace", False):
            value["io_trace"] = io_trace
            value["temp_files_closed"] = [file.closed for file in tracked_tempfiles]
        return {"form": value}

    async def inspect_form(
        form: Any,
    ) -> tuple[dict[str, Any], list[tuple[str, Any, dict[str, Any]]]]:
        multi_items = [[_json_safe(key), _json_safe(value)] for key, value in form.multi_items()]
        keys = [_json_safe(key) for key in form.keys()]
        items = [[_json_safe(key), _json_safe(value)] for key, value in form.items()]
        lookup = []
        getlist = []
        value_types = []
        type_probe_keys = set(case.get("form_type_probe_keys", []))
        for key in case["form_probe_keys"]:
            try:
                value = form[key]
            except KeyError:
                value = None
                value_type = None
            else:
                value_type = f"{type(value).__module__}.{type(value).__qualname__}"
            lookup.append([key, _json_safe(value)])
            getlist.append([key, [_json_safe(value) for value in form.getlist(key)]])
            if key in type_probe_keys:
                value_types.append([key, value_type])
        value = {
            "multi_items": multi_items,
            "keys": keys,
            "items": items,
            "lookup": lookup,
            "getlist": getlist,
        }
        if type_probe_keys:
            value["lookup_types"] = value_types
        observed_files = []
        if case.get("form_file_probe_all", False):
            file_values = [
                (key, item) for key, item in form.multi_items() if isinstance(item, UploadFile)
            ]
        else:
            file_values = [(key, form[key]) for key in case.get("form_file_probe_keys", [])]
        for key, upload in file_values:
            file_value = {
                "is_upload_file": isinstance(upload, UploadFile),
                "filename": _json_safe(upload.filename),
                "size": _json_safe(upload.size),
                "content_type": _json_safe(upload.content_type),
                "headers": _json_safe(upload.headers.raw),
                "file_type": [type(upload.file).__module__, type(upload.file).__qualname__],
                "repr": repr(upload),
                "partial_read": _json_safe(await upload.read(case["form_file_read_size"])),
            }
            await upload.seek(0)
            file_value["read_all"] = _json_safe(await upload.read())
            if "form_file_write_base64" in case:
                data = base64.b64decode(case["form_file_write_base64"], validate=True)
                await upload.write(data)
                file_value["size_after_write"] = _json_safe(upload.size)
                await upload.seek(0)
                file_value["read_after_write"] = _json_safe(await upload.read())
            observed_files.append((key, upload, file_value))
        return value, observed_files

    if case.get("form_io_trace", False):
        import starlette.formparsers as formparsers

        original_spooled_tempfile = tempfile.SpooledTemporaryFile
        original_formparser_spooled_tempfile = getattr(formparsers, "SpooledTemporaryFile", None)
        original_upload_write = UploadFile.write
        original_upload_seek = UploadFile.seek

        def observed_spooled_tempfile(*args: Any, **kwargs: Any) -> Any:
            file = original_spooled_tempfile(*args, **kwargs)
            tracked_tempfiles.append(file)
            original_close = file.close
            original_write = file.write
            creation_thread = threading.get_ident()
            original_rollover = file.rollover

            def observed_write(data: bytes) -> Any:
                nonlocal tempfile_write_calls
                call_index = tempfile_write_calls
                tempfile_write_calls += 1
                io_trace.append(["tempfile-write", len(data)])
                write_error = case.get("file_write_error")
                if write_error is not None and call_index == write_error["at_call"]:
                    raise OSError(write_error["message"])
                return original_write(data)

            def observed_rollover() -> Any:
                result = original_rollover()
                io_trace.append(
                    ["spooled-rollover-worker", threading.get_ident() != creation_thread]
                )
                return result

            def observed_close() -> Any:
                result = original_close()
                io_trace.append(["spooled-file-close", bool(file.closed)])
                return result

            file.close = observed_close
            file.write = observed_write
            file.rollover = observed_rollover
            return file

        async def observed_upload_write(self: Any, data: bytes) -> None:
            io_trace.append(
                ["upload-write", self.filename, len(data), hashlib.sha256(data).hexdigest()]
            )
            await original_upload_write(self, data)

        async def observed_upload_seek(self: Any, offset: int) -> None:
            io_trace.append(["upload-seek", self.filename, offset])
            await original_upload_seek(self, offset)

        tempfile.SpooledTemporaryFile = observed_spooled_tempfile
        formparsers.SpooledTemporaryFile = observed_spooled_tempfile
        UploadFile.write = observed_upload_write
        UploadFile.seek = observed_upload_seek
    try:
        observer = observe_application if case.get("form_app") is not None else observe
        result = asyncio.run(observer())
    finally:
        if case.get("form_io_trace", False):
            tempfile.SpooledTemporaryFile = original_spooled_tempfile
            if original_formparser_spooled_tempfile is None:
                delattr(formparsers, "SpooledTemporaryFile")
            else:
                formparsers.SpooledTemporaryFile = original_formparser_spooled_tempfile
            UploadFile.write = original_upload_write
            UploadFile.seek = original_upload_seek
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "form", "status": "ok", "value": result}],
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


def _make_routing_endpoint(spec: dict[str, Any]) -> Any:
    kind = spec["kind"]
    keys_by_kind = {
        "function": {"kind", "name", "async"},
        "bound-method": {"kind", "class_name", "method_name", "async"},
        "class-method": {"kind", "class_name", "method_name", "async"},
        "static-method": {"kind", "class_name", "method_name", "async"},
        "object": {"kind", "class_name"},
        "lambda": {"kind"},
    }
    if kind not in keys_by_kind:
        raise ValueError(f"unsupported Route endpoint shape: {kind!r}")
    _strict_object(spec, keys_by_kind[kind], "routing endpoint shape")
    if kind == "function":
        if spec["async"]:

            async def endpoint(*args: Any, **kwargs: Any) -> None:
                return None

        else:

            def endpoint(*args: Any, **kwargs: Any) -> None:
                return None

        endpoint.__name__ = spec["name"]
        return endpoint
    if kind == "lambda":
        return lambda *args, **kwargs: None
    if kind == "object":
        if spec["class_name"] == "Endpoint":

            def call(self: Any, *args: Any, **kwargs: Any) -> None:
                return None

            endpoint_type = type(spec["class_name"], (), {"__call__": call})
        else:
            endpoint_type = type(spec["class_name"], (), {})
        return endpoint_type()

    method_name = spec["method_name"]
    asynchronous = spec["async"]
    if asynchronous:

        async def method(*args: Any, **kwargs: Any) -> None:
            return None

    else:

        def method(*args: Any, **kwargs: Any) -> None:
            return None

    method.__name__ = method_name
    descriptor: Any = method
    if kind == "class-method":
        descriptor = classmethod(method)
    elif kind == "static-method":
        descriptor = staticmethod(method)
    endpoint_type = type(spec["class_name"], (), {method_name: descriptor})
    endpoint_instance = endpoint_type()
    if kind == "class-method":
        return getattr(endpoint_type, method_name)
    return getattr(endpoint_instance, method_name)


def _run_route_endpoint_name_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.routing import Route

    if "attempts" in case:
        _strict_object(
            case,
            {
                "case_id",
                "surface",
                "operation",
                "covers",
                "target_profiles",
                "assets",
                "attempts",
                "observations",
            },
            "Route constructor-error case",
        )
        constructors = case["attempts"]
    else:
        _strict_object(
            case,
            {
                "case_id",
                "surface",
                "operation",
                "covers",
                "target_profiles",
                "assets",
                "path",
                "methods",
                "name",
                "endpoints",
                "observations",
            },
            "Route endpoint-name case",
        )
        constructors = [
            {
                "path": case["path"],
                "endpoint": endpoint,
                "methods": case["methods"],
                "name": case["name"],
            }
            for endpoint in case["endpoints"]
        ]

    results = []
    for constructor in constructors:
        _strict_object(
            constructor,
            {"path", "endpoint", "methods", "name"},
            "Route constructor input",
        )
        try:
            route = Route(
                path=constructor["path"],
                endpoint=_make_routing_endpoint(constructor["endpoint"]),
                methods=constructor["methods"],
                name=constructor["name"],
            )
        except Exception as error:
            results.append(
                {
                    "outcome": "error",
                    "exception_class": f"{type(error).__module__}.{type(error).__qualname__}",
                    "exception_message": str(error),
                }
            )
        else:
            results.append({"outcome": "constructed", "route_name": route.name})
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "constructor_results",
                "status": "ok",
                "value": {"constructor_results": results},
            }
        ],
    }


def _make_routing_value(spec: dict[str, Any], surface: str) -> Any:
    from starlette.routing import Host, Mount, Route, Router, WebSocketRoute

    if surface == HTTP_ROUTE_SURFACE:
        _strict_object(spec, {"path", "endpoint", "methods", "name"}, "Route representation input")
        return Route(
            path=spec["path"],
            endpoint=_make_routing_endpoint(spec["endpoint"]),
            methods=spec["methods"],
            name=spec["name"],
        )
    if surface == WEBSOCKET_ROUTE_SURFACE:
        _strict_object(
            spec,
            {"path", "endpoint", "name"},
            "WebSocketRoute representation input",
        )
        return WebSocketRoute(
            path=spec["path"],
            endpoint=_make_routing_endpoint(spec["endpoint"]),
            name=spec["name"],
        )
    if surface == MOUNT_SURFACE:
        _strict_object(spec, {"path", "name", "routes"}, "Mount representation input")
    else:
        _strict_object(spec, {"host", "name", "routes"}, "Host representation input")
    routes = []
    for route_spec in spec["routes"]:
        _strict_object(
            route_spec,
            {"path", "endpoint", "methods", "name"},
            "mounted routing child",
        )
        routes.append(
            Route(
                path=route_spec["path"],
                endpoint=_make_routing_endpoint(route_spec["endpoint"]),
                methods=route_spec["methods"],
                name=route_spec["name"],
            )
        )
    if surface == MOUNT_SURFACE:
        return Mount(path=spec["path"], routes=routes, name=spec["name"])
    return Host(host=spec["host"], app=Router(routes=routes), name=spec["name"])


def _run_routing_value_formatting_case(case: dict[str, Any]) -> dict[str, Any]:
    field = {
        HTTP_ROUTE_SURFACE: "route",
        WEBSOCKET_ROUTE_SURFACE: "route",
        MOUNT_SURFACE: "mount",
        HOST_SURFACE: "host",
    }[case["surface"]]
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            field,
            "observations",
        },
        "routing value-formatting case",
    )
    value = _make_routing_value(case[field], case["surface"])
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "representation",
                "status": "ok",
                "value": {"representation": repr(value)},
            }
        ],
    }


def _run_value_formatting_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["surface"] in ROUTE_REPRESENTATION_SURFACES:
        return _run_routing_value_formatting_case(case)
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

        def custom_user(action: dict[str, Any]) -> Any:
            class FixtureUser(BaseUser):
                @property
                def is_authenticated(self) -> bool:
                    return action["is_authenticated"]

                @property
                def display_name(self) -> str:
                    return action["display_name"]

                @property
                def identity(self) -> str:
                    return action["identity"]

            return FixtureUser()

        users = {
            "base": lambda action: BaseUser(),
            "simple": lambda action: SimpleUser(action["username"]),
            "unauthenticated": lambda action: UnauthenticatedUser(),
            "custom": custom_user,
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
                results.append(
                    {
                        "action": action["action"],
                        "user_type": type(user).__name__,
                        "properties": properties,
                    }
                )
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
            callable_spec = scenario["callable"]
            if callable_spec["kind"] == "invalid-no-connection-parameter":

                class EndpointWithoutConnectionParameter:
                    def __init__(self, display_name: str) -> None:
                        self.display_name = display_name

                    def __call__(self, other: Any = None) -> None:
                        return None

                    def __str__(self) -> str:
                        return self.display_name

                endpoint = EndpointWithoutConnectionParameter(callable_spec["display_name"])
                try:
                    requires(scenario["required_scopes"])(endpoint)
                except Exception as exc:
                    outcome = {"outcome": "error", "error": _error_snapshot(exc)}
                else:
                    outcome = {"outcome": "value", "value": None}
                results.append(
                    {
                        "stage": "decorator-construction",
                        "outcome": outcome,
                        "endpoint_calls": [],
                        "sent": [],
                    }
                )
                continue
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
        from starlette.responses import JSONResponse, PlainTextResponse

        results = []
        for scenario in case["scenarios"]:
            calls = []
            app_calls = []
            sent = []
            backend_spec = scenario["backend"]
            application_response_spec = scenario.get("application_response")

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
                _response_spec: dict[str, Any] | None = application_response_spec,
            ) -> None:
                observed_scope = {"type": scope["type"]}
                if "auth" in scope:
                    observed_scope["auth_scopes"] = list(scope["auth"].scopes)
                    observed_scope["user"] = {
                        "is_authenticated": scope["user"].is_authenticated,
                        "display_name": scope["user"].display_name,
                    }
                _app_calls.append(observed_scope)
                if _response_spec is not None:
                    response_body = {
                        _response_spec["authenticated_field"]: scope["user"].is_authenticated,
                        _response_spec["display_name_field"]: scope["user"].display_name,
                    }
                    await JSONResponse(
                        response_body,
                        status_code=_response_spec["status_code"],
                    )(scope, receive, send)

            error_response = scenario.get("error_response")

            def on_error(
                conn: Any,
                exc: Exception,
                _response_spec: dict[str, Any] | None = error_response,
            ) -> Any:
                if _response_spec["kind"] == "json-error":
                    return JSONResponse(
                        {_response_spec["error_field"]: str(exc)},
                        status_code=_response_spec["status_code"],
                    )
                return PlainTextResponse(
                    f"{_response_spec['prefix']}{exc}",
                    status_code=_response_spec["status_code"],
                )

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


def _run_url_scope_case(case: dict[str, Any]) -> dict[str, Any]:
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
        "URL scope case",
    )
    source_scope = case["scope"]
    scope_fields = {
        "scheme",
        "server",
        "path",
        "query_string_base64",
        "headers_base64_pairs",
    }
    if (
        not isinstance(source_scope, dict)
        or not {"path", "headers_base64_pairs"} <= set(source_scope)
        or set(source_scope) - scope_fields
    ):
        raise ValueError("URL scope input has missing or unknown fields")
    scope: dict[str, Any] = {
        "path": source_scope["path"],
        "query_string": base64.b64decode(
            source_scope.get("query_string_base64", ""), validate=True
        ),
        "headers": [
            (
                base64.b64decode(pair[0], validate=True),
                base64.b64decode(pair[1], validate=True),
            )
            for pair in source_scope["headers_base64_pairs"]
        ],
    }
    if "scheme" in source_scope:
        scope["scheme"] = source_scope["scheme"]
    if "server" in source_scope:
        scope["server"] = tuple(source_scope["server"])

    from starlette.datastructures import URL

    url = URL(scope=scope)
    record = {
        "url": str(url),
        "repr": repr(url),
        "scheme": url.scheme,
        "netloc": url.netloc,
        "path": url.path,
        "query": url.query,
        "fragment": url.fragment,
        "username": url.username,
        "password": url.password,
        "hostname": url.hostname,
        "port": url.port,
        "is_secure": url.is_secure,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "url-record", "status": "ok", "value": {"url-record": record}}
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
    comparison_input = case["comparison"]
    if comparison_input is None:
        comparison = None
    elif comparison_input.get("kind") == "literal":
        comparison = comparison_input["value"]
    else:
        comparison = _query_params_from_input(QueryParams, comparison_input)
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


def _config_cast(cast_spec: Any) -> Any:
    if isinstance(cast_spec, dict):
        if cast_spec["kind"] == "starlette-public-class":
            from starlette.datastructures import URL, Secret

            return {
                "starlette.datastructures.Secret": Secret,
                "starlette.datastructures.URL": URL,
            }[cast_spec["symbol"]]
        converter = getattr(builtins, cast_spec["converter"])

        def custom_cast(value: Any) -> Any:
            return converter(value)

        custom_cast.__name__ = cast_spec["name"]
        return custom_cast
    return getattr(builtins, cast_spec)


def _config_value_inspections(value: Any, selectors: list[str]) -> dict[str, Any]:
    inspections = {}
    for selector in selectors:
        if selector == "repr":
            inspected = repr(value)
        elif selector == "truthiness":
            inspected = bool(value)
        else:
            inspected = getattr(value, selector)
        inspections[selector] = _json_safe(inspected)
    return inspections


def _run_config_environ_actions(case: dict[str, Any], environ: Any) -> list[dict[str, Any]]:
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
                value = list(environ)
                result["value"] = (
                    value == list(os.environ)
                    if action.get("compare_to") == "underlying-os-environ"
                    else value
                )
            else:
                value = len(environ)
                result["value"] = (
                    value == len(os.environ)
                    if action.get("compare_to") == "underlying-os-environ"
                    else value
                )
        except Exception as exc:
            result["error"] = _error_snapshot(exc)
        else:
            result["outcome"] = "ok"
        results.append(result)
    return results


def _run_config_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.config import Config, Environ

    surface_operation = (case["surface"], case["operation"])
    if surface_operation == ("starlette.config.Config", "value-resolution"):
        config_input = case["config"]
        with tempfile.TemporaryDirectory() as directory:
            previous_directory = os.getcwd()
            os.chdir(directory)
            try:
                encoding = case.get("encoding", "utf-8")
                Path(".env").write_text(
                    "\n".join(config_input["env_file_lines"]), encoding=encoding
                )
                config = Config(
                    env_file=".env",
                    environ=config_input["environ"],
                    env_prefix=config_input["env_prefix"],
                    encoding=encoding,
                )
                results = []
                for lookup in case["lookups"]:
                    cast = _config_cast(lookup["cast"]) if "cast" in lookup else None
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
                        if "inspect" in lookup:
                            result["inspections"] = _config_value_inspections(
                                value, lookup["inspect"]
                            )
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
        if case.get("mapping_source", "explicit") == "os-environ":
            original_environment = list(os.environ.items())
            present = set(case["initial_environ"])
            read: set[str] = set()
            absent_keys: set[str] = set()
            for action in case["actions"]:
                name = action["action"]
                key = action.get("key")
                if name in {"get", "contains", "delete"} and key not in present:
                    absent_keys.add(key)
                if name == "contains":
                    read.add(key)
                elif name == "get":
                    read.add(key)
                elif name == "set" and key not in read:
                    present.add(key)
                elif name == "delete" and key not in read:
                    present.discard(key)
            try:
                for key, item in case["initial_environ"].items():
                    os.environ[key] = item
                for key in absent_keys:
                    os.environ.pop(key, None)
                environ = Environ()
                results = _run_config_environ_actions(case, environ)
            finally:
                os.environ.clear()
                os.environ.update(original_environment)
        else:
            environ = Environ(dict(case["initial_environ"]))
            results = _run_config_environ_actions(case, environ)
        value = {"action-results": results}
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": value}
            for selector in case["observations"]
        ],
    }


def _schema_function(docstring: str | None, name: str = "endpoint") -> Any:
    def endpoint(*_args: Any, **_kwargs: Any) -> None:
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
    return type("SchemaEndpoint", (), methods)


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


def _application_route_endpoint(spec: dict[str, Any]) -> Any:
    if spec["kind"] == "function":
        _strict_object(spec, {"kind", "name", "async"}, "application route function endpoint")
        if spec["async"]:

            async def endpoint(*_args: Any, **_kwargs: Any) -> None:
                return None

        else:

            def endpoint(*_args: Any, **_kwargs: Any) -> None:
                return None

        endpoint.__name__ = spec["name"]
        return endpoint
    if spec["kind"] == "class":
        _strict_object(spec, {"kind", "name"}, "application route class endpoint")
        return type(spec["name"], (), {})
    raise ValueError("application route endpoint uses an unsupported input kind")


def _application_route_object(
    value: Any, required: set[str], allowed: set[str], context: str
) -> dict[str, Any]:
    if not isinstance(value, dict) or not required <= set(value) or not set(value) <= allowed:
        raise ValueError(f"{context} must contain required fields {sorted(required)} only")
    return value


def _application_routes(specs: list[dict[str, Any]]) -> list[Any]:
    from starlette.routing import Host, Mount, Route, Router, WebSocketRoute

    routes = []
    for spec in specs:
        kind = spec.get("kind") if isinstance(spec, dict) else None
        if kind == "route":
            _application_route_object(
                spec,
                {"kind", "path", "endpoint"},
                {"kind", "path", "endpoint", "methods", "route_name"},
                "application HTTP route",
            )
            kwargs: dict[str, Any] = {}
            if "methods" in spec:
                kwargs["methods"] = spec["methods"]
            if "route_name" in spec:
                kwargs["name"] = spec["route_name"]
            routes.append(
                Route(spec["path"], _application_route_endpoint(spec["endpoint"]), **kwargs)
            )
        elif kind == "websocket-route":
            _application_route_object(
                spec,
                {"kind", "path", "endpoint"},
                {"kind", "path", "endpoint", "route_name"},
                "application WebSocket route",
            )
            kwargs = {"name": spec["route_name"]} if "route_name" in spec else {}
            routes.append(
                WebSocketRoute(
                    spec["path"], _application_route_endpoint(spec["endpoint"]), **kwargs
                )
            )
        elif kind == "mount":
            _application_route_object(
                spec,
                {"kind", "path", "routes"},
                {"kind", "path", "routes", "route_name"},
                "application Mount route",
            )
            kwargs = {"name": spec["route_name"]} if "route_name" in spec else {}
            routes.append(Mount(spec["path"], routes=_application_routes(spec["routes"]), **kwargs))
        elif kind == "host":
            _application_route_object(
                spec,
                {"kind", "host", "routes"},
                {"kind", "host", "routes", "route_name"},
                "application Host route",
            )
            kwargs = {"name": spec["route_name"]} if "route_name" in spec else {}
            child_router = Router(routes=_application_routes(spec["routes"]))
            routes.append(Host(spec["host"], child_router, **kwargs))
        else:
            raise ValueError(f"unsupported application route kind: {kind!r}")
    return routes


def _application_route_observation(route: Any) -> dict[str, Any]:
    from starlette.routing import Host, Mount, Route, WebSocketRoute

    value: dict[str, Any] = {
        "type": type(route).__name__,
        "path": getattr(route, "path", None),
        "host": getattr(route, "host", None),
        "name": route.name,
        "methods": sorted(route.methods) if getattr(route, "methods", None) is not None else None,
    }
    if isinstance(route, (Route, WebSocketRoute)):
        endpoint = route.endpoint
        endpoint_name = getattr(endpoint, "__name__", type(endpoint).__name__)
        if inspect.isclass(endpoint):
            endpoint_shape = "class"
        elif inspect.iscoroutinefunction(endpoint):
            endpoint_shape = "async-function"
        elif inspect.isfunction(endpoint):
            endpoint_shape = "function"
        else:
            endpoint_shape = "callable-instance"
        value["endpoint"] = {"shape": endpoint_shape, "name": endpoint_name}
    else:
        value["endpoint"] = None
    if isinstance(route, (Host, Mount)):
        value["child_routes"] = [_application_route_observation(child) for child in route.routes]
    else:
        value["child_routes"] = None
    return value


def _run_application_routes_property_case(case: dict[str, Any]) -> dict[str, Any]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "routes",
            "observations",
        },
        "Starlette.routes property case",
    )
    if (
        case["surface"] != APPLICATION_SURFACE
        or case["operation"] != APPLICATION_ROUTES_OPERATION
        or case["observations"] != ["route-inventory"]
    ):
        raise ValueError("workflow is outside the Starlette.routes property operation")

    from starlette.applications import Starlette

    constructor_routes = _application_routes(case["routes"])
    application = Starlette(routes=constructor_routes)
    public_routes = application.routes
    value = {
        "routes": [_application_route_observation(route) for route in public_routes],
        "same_list_as_router": public_routes is application.router.routes,
        "constructor_route_identity": [
            route is original
            for route, original in zip(public_routes, constructor_routes, strict=True)
        ],
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "route-inventory", "status": "ok", "value": value}],
    }


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


def _input_defined_middleware_callback(marker: dict[str, Any], trace: list[dict[str, Any]]) -> Any:
    callable_kind = marker["callable_kind"]
    name = marker["name"]
    boundary_trace = marker.get("boundary_trace", False)

    async def call_middleware(
        app: Any, scope: Any, receive: Any, send: Any, call_event: dict[str, Any]
    ) -> None:
        trace.append(call_event)
        if not boundary_trace:
            await app(scope, receive, send)
            return

        trace.append({"event": "enter", "name": name, "scope_type": scope["type"]})

        async def observed_send(message: Any) -> None:
            trace.append({"event": "send", "name": name, "message": _canonical_message(message)})
            await send(message)

        try:
            await app(scope, receive, observed_send)
        except BaseException as exc:
            trace.append(
                {
                    "event": "exception",
                    "name": name,
                    "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "exception_message": str(exc),
                }
            )
            raise
        finally:
            trace.append({"event": "exit", "name": name})

    if callable_kind == "class":

        class InputDefinedMiddleware:
            def __init__(self, app: Any, *args: Any, **kwargs: Any) -> None:
                self.app = app
                trace.append(
                    {
                        "event": "construct",
                        "callable_kind": callable_kind,
                        "name": name,
                        "args": args,
                        "kwargs": kwargs,
                    }
                )

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                await call_middleware(
                    self.app,
                    scope,
                    receive,
                    send,
                    {
                        "event": "call",
                        "callable_kind": callable_kind,
                        "name": name,
                        "args": (),
                        "kwargs": {},
                        "scope_type": scope["type"],
                    },
                )

        InputDefinedMiddleware.__name__ = name
        return InputDefinedMiddleware

    def middleware_factory(app: Any, *args: Any, **kwargs: Any) -> Any:
        trace.append(
            {
                "event": "construct",
                "callable_kind": callable_kind,
                "name": name,
                "args": args,
                "kwargs": kwargs,
            }
        )

        async def middleware(scope: Any, receive: Any, send: Any) -> None:
            await call_middleware(
                app,
                scope,
                receive,
                send,
                {
                    "event": "call",
                    "callable_kind": callable_kind,
                    "name": name,
                    "args": (),
                    "kwargs": {},
                    "scope_type": scope["type"],
                },
            )

        return middleware

    return middleware_factory


def _run_starlette_add_middleware_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    application_arguments = {
        name: descriptor["value"] for name, descriptor in steps[0]["arguments"].items()
    }
    app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states = (
        _materialize_application(application_arguments)
    )
    applications = {
        steps[0]["step_id"]: (
            app,
            lifecycle_trace,
            request_observations,
            route_endpoint,
            sync_endpoint_states,
        )
    }
    middleware_trace: list[dict[str, Any]] = []
    callbacks: dict[tuple[str, str], Any] = {}
    capture_dispatch_error = any(
        step.get("operation") == "add_middleware"
        and step.get("arguments", {})
        .get("middleware_class", {})
        .get("value", {})
        .get("boundary_trace", False)
        for step in steps
    )

    async def run_steps() -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for step in steps[1:]:
            arguments = {
                name: descriptor["value"] for name, descriptor in step["arguments"].items()
            }
            if step["operation"] == "__init__":
                applications[step["step_id"]] = _materialize_application(arguments)
                value = {
                    "workflow_observation": {
                        "return": None,
                        "middleware_trace": _json_safe(middleware_trace),
                    }
                }
            else:
                application = applications[step["receiver"]["step_id"]]
                app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states = (
                    application
                )
            if step["operation"] == "__call__":
                dispatch = await _invoke(
                    app,
                    arguments,
                    lifecycle_trace,
                    request_observations,
                    route_endpoint,
                    False,
                    sync_endpoint_states=sync_endpoint_states,
                    capture_dispatch_error=capture_dispatch_error,
                )
                value = {
                    "workflow_observation": {
                        "dispatch": dispatch,
                        "middleware_trace": _json_safe(middleware_trace),
                    }
                }
            elif step["operation"] == "add_middleware":
                try:
                    marker = arguments["middleware_class"]
                    key = (marker["callable_kind"], marker["name"])
                    callback = callbacks.setdefault(
                        key, _input_defined_middleware_callback(marker, middleware_trace)
                    )
                    app.add_middleware(callback, *arguments["args"], **arguments["kwargs"])
                except Exception as exc:
                    value = {
                        "workflow_observation": {
                            "error": _error_snapshot(exc),
                            "middleware_trace": _json_safe(middleware_trace),
                        }
                    }
                else:
                    value = {
                        "workflow_observation": {
                            "return": None,
                            "middleware_trace": _json_safe(middleware_trace),
                        }
                    }
            observations.append(_workflow_observation(step["step_id"], value))
        return observations

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(run_steps()),
    }


def _input_defined_exception_handler(
    marker: dict[str, Any], trace: list[dict[str, Any]], dispatch_state: dict[str, Any]
) -> Any:
    from starlette.responses import PlainTextResponse

    def record(request: Any, exc: Exception) -> None:
        caller_thread_id = dispatch_state["caller_thread_id"]
        if caller_thread_id is None:
            raise RuntimeError("exception handler ran without a caller thread identity")
        trace.append(
            {
                "callable_kind": marker["callable_kind"],
                "label": marker["label"],
                "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "exception_message": str(exc),
                "request_path": request.url.path,
                "request_type": f"{type(request).__module__}.{type(request).__qualname__}",
                "different_worker_thread": threading.get_ident() != caller_thread_id,
            }
        )

    if marker["callable_kind"] == "async":

        async def async_handler(request: Any, exc: Exception) -> Any:
            record(request, exc)
            return PlainTextResponse(marker["content"], status_code=marker["status_code"])

        return async_handler

    def sync_handler(request: Any, exc: Exception) -> Any:
        record(request, exc)
        return PlainTextResponse(marker["content"], status_code=marker["status_code"])

    return sync_handler


def _attach_exception_handler_trace(
    dispatch: dict[str, Any] | _CapturedDispatchError, trace: list[dict[str, Any]]
) -> dict[str, Any] | _CapturedDispatchError:
    snapshot = _json_safe(trace)
    if isinstance(dispatch, _CapturedDispatchError):
        return _CapturedDispatchError(
            error=dispatch.error,
            partial_value={**dispatch.partial_value, "exception_handler_trace": snapshot},
        )
    return {**dispatch, "exception_handler_trace": snapshot}


def _exception_handler_key(marker: dict[str, Any]) -> Any:
    if marker["kind"] == "status-code":
        return marker["status_code"]
    if marker["name"] == "RuntimeError":
        return RuntimeError
    raise ValueError("unsupported input-defined exception handler key")


def _run_starlette_add_exception_handler_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    applications: dict[str, dict[str, Any]] = {}
    initial_arguments = {
        name: descriptor["value"] for name, descriptor in steps[0]["arguments"].items()
    }
    applications[steps[0]["step_id"]] = {
        "runtime": _materialize_application(initial_arguments),
        "handler_trace": [],
        "dispatch_state": {"caller_thread_id": None},
    }

    async def run_steps() -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for step in steps[1:]:
            arguments = {
                name: descriptor["value"] for name, descriptor in step["arguments"].items()
            }
            if step["operation"] == "__init__":
                applications[step["step_id"]] = {
                    "runtime": _materialize_application(arguments),
                    "handler_trace": [],
                    "dispatch_state": {"caller_thread_id": None},
                }
                application = applications[step["step_id"]]
                value = {
                    "workflow_observation": {
                        "return": None,
                        "exception_handler_trace": _json_safe(application["handler_trace"]),
                    }
                }
            else:
                application = applications[step["receiver"]["step_id"]]
                app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states = (
                    application["runtime"]
                )
                if step["operation"] == "add_exception_handler":
                    marker = arguments["handler"]
                    callback = _input_defined_exception_handler(
                        marker, application["handler_trace"], application["dispatch_state"]
                    )
                    app.add_exception_handler(
                        _exception_handler_key(arguments["exc_class_or_status_code"]), callback
                    )
                    value = {
                        "workflow_observation": {
                            "return": None,
                            "exception_handler_trace": _json_safe(application["handler_trace"]),
                        }
                    }
                else:
                    application["dispatch_state"]["caller_thread_id"] = threading.get_ident()
                    dispatch = await _invoke(
                        app,
                        arguments,
                        lifecycle_trace,
                        request_observations,
                        route_endpoint,
                        True,
                        sync_endpoint_states=sync_endpoint_states,
                        capture_dispatch_error=True,
                    )
                    dispatch = _attach_exception_handler_trace(
                        dispatch, application["handler_trace"]
                    )
                    dispatch_observation = (
                        {
                            "status": "error",
                            "error": dispatch.error,
                            "partial_value": dispatch.partial_value,
                        }
                        if isinstance(dispatch, _CapturedDispatchError)
                        else {"status": "ok", "value": dispatch}
                    )
                    value = {
                        "workflow_observation": {
                            "dispatch": dispatch_observation,
                            "exception_handler_trace": _json_safe(application["handler_trace"]),
                        }
                    }
            observations.append(_workflow_observation(step["step_id"], value))
        return observations

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(run_steps()),
    }


def _run_starlette_add_route_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    application_arguments = {
        name: descriptor["value"] for name, descriptor in steps[0]["arguments"].items()
    }
    app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states = (
        _materialize_application(application_arguments)
    )

    async def run_steps() -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for step in steps[1:]:
            arguments = {
                name: descriptor["value"] for name, descriptor in step["arguments"].items()
            }
            if step["operation"] == "add_route":
                endpoint_reference = arguments["route"]
                if endpoint_reference["kind"] != "route-endpoint-reference":
                    raise ValueError(
                        "Starlette.add_route requires an input-defined endpoint reference"
                    )
                app.add_route(
                    arguments["path"],
                    route_endpoint,
                    methods=arguments["methods"],
                    name=arguments["name"],
                    include_in_schema=arguments["include_in_schema"],
                )
                continue
            else:
                value = await _invoke(
                    app,
                    arguments,
                    lifecycle_trace,
                    request_observations,
                    route_endpoint,
                    False,
                    sync_endpoint_states=sync_endpoint_states,
                )
            observations.append(_workflow_observation(step["step_id"], value))
        return observations

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(run_steps()),
    }


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    if (
        case.get("surface") == "starlette.concurrency"
        and case.get("operation") == "run_until_first_complete"
    ):
        from starlette.concurrency import run_until_first_complete

        from scripts.parity.adapters.concurrency import run_until_first_complete_case

        return run_until_first_complete_case(case, run_until_first_complete)
    if (
        case.get("surface") == "starlette.concurrency"
        and case.get("operation") == "run_in_threadpool"
    ):
        from starlette.concurrency import run_in_threadpool

        from scripts.parity.adapters.concurrency import run_threadpool_case

        return run_threadpool_case(case, run_in_threadpool)
    if (
        case.get("surface") == "starlette.concurrency"
        and case.get("operation") == "iterate_in_threadpool"
    ):
        from starlette.concurrency import iterate_in_threadpool

        from scripts.parity.adapters.concurrency import run_iterate_in_threadpool_case

        return run_iterate_in_threadpool_case(case, iterate_in_threadpool)
    if case.get("surface") == TESTCLIENT_SURFACE and case.get("operation") in {
        TESTCLIENT_OPERATION,
        TESTCLIENT_WEBSOCKET_OPERATION,
        TESTCLIENT_LIFESPAN_OPERATION,
    }:
        from scripts.parity.adapters.testclient import (
            run_testclient_case,
            run_testclient_lifespan_case,
        )

        if case.get("operation") == TESTCLIENT_WEBSOCKET_OPERATION:
            from scripts.parity.adapters.testclient import run_testclient_websocket_case

            return run_testclient_websocket_case(case)
        if case.get("operation") == TESTCLIENT_LIFESPAN_OPERATION:
            return run_testclient_lifespan_case(case)
        return run_testclient_case(case)
    if case.get("surface") == "starlette.middleware.wsgi" and case.get("operation") in {
        "build-environ",
        "module-import-warning",
    }:
        from scripts.parity.adapters.wsgi_boundary import run_wsgi_boundary_case

        return run_wsgi_boundary_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == "starlette.applications.Starlette"
        and isinstance(case.get("steps"), list)
        and any(step.get("operation") == "add_exception_handler" for step in case["steps"])
    ):
        return _run_starlette_add_exception_handler_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == "starlette.applications.Starlette"
        and isinstance(case.get("steps"), list)
        and any(step.get("operation") == "add_middleware" for step in case["steps"])
    ):
        return _run_starlette_add_middleware_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == "starlette.applications.Starlette"
        and isinstance(case.get("steps"), list)
        and any(step.get("operation") == "add_route" for step in case["steps"])
    ):
        return _run_starlette_add_route_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == "starlette.templating.Jinja2Templates"
        and case.get("operation") == "template-response"
    ):
        from scripts.parity.adapters.templating import run_template_response_case

        return run_template_response_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == BASE_HTTP_SURFACE
        and case.get("operation") == BASE_HTTP_CONTEXTVARS_OPERATION
    ):
        from scripts.parity.adapters.base_http_contextvars import (
            run_base_http_contextvars_case,
        )

        return run_base_http_contextvars_case(case)
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
        and (
            case.get("surface"),
            case.get("operation"),
        )
        == REQUEST_CLIENT_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_client import run_request_client_case

        return run_request_client_case(case, Request)
    if (
        isinstance(case, dict)
        and (
            case.get("surface"),
            case.get("operation"),
        )
        == REQUEST_SCOPE_MAPPING_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_scope_mapping import run_request_scope_mapping_case

        return run_request_scope_mapping_case(case, Request)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == WEBSOCKET_SCOPE_MAPPING_OPERATION
    ):
        from starlette.websockets import WebSocket

        from scripts.parity.adapters.request_scope_mapping import run_websocket_scope_mapping_case

        return run_websocket_scope_mapping_case(case, WebSocket)
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
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_FORM_OPERATION
    ):
        return _run_request_form_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.FormData",
        "multidict-lookups",
    ):
        from starlette.datastructures import FormData, UploadFile

        from scripts.parity.adapters.formdata import run_formdata_case

        return run_formdata_case(case, FormData, UploadFile)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.UploadFile",
        "file-operations",
    ):
        from starlette.datastructures import UploadFile

        from scripts.parity.adapters.upload_file import run_upload_file_case

        return run_upload_file_case(case, UploadFile)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_BODY_STREAM_JSON_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_consumption import run_request_consumption_case

        return run_request_consumption_case(case, Request)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        STATUS_SURFACE,
        STATUS_OPERATION,
    ):
        return _run_status_symbols_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in CONFIG_OPERATIONS:
        return _run_config_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        APPLICATION_SURFACE,
        APPLICATION_ROUTES_OPERATION,
    ):
        return _run_application_routes_property_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in SCHEMA_OPERATIONS:
        return _run_schema_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == URL_QUERY_OPERATION
    ):
        return _run_url_query_params_case(case)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == URL_SCOPE_OPERATION
    ):
        return _run_url_scope_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.URL",
        "component-and-replacement-sequence",
    ):
        from scripts.parity.adapters.url_components import run_url_components_case

        return run_url_components_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.URLPath",
        "make-absolute-url",
    ):
        from scripts.parity.adapters.urlpath_absolute import run_urlpath_absolute_case

        return run_urlpath_absolute_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in {
        ("starlette.datastructures.Headers", "consumer-sequence"),
        ("starlette.datastructures.MutableHeaders", "consumer-sequence"),
    }:
        from scripts.parity.adapters.headers import run_headers_case

        return run_headers_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.State",
        "consumer-sequence",
    ):
        from scripts.parity.adapters.state import run_state_case

        return run_state_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.MultiDict",
        "mutation-sequence",
    ):
        from starlette.datastructures import MultiDict

        from scripts.parity.adapters.multidict import run_multidict_case

        return run_multidict_case(case, MultiDict)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.QueryParams",
        "construction-and-mapping-sequence",
    ):
        return _run_query_params_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.CommaSeparatedStrings",
        "consumer-sequence",
    ):
        from starlette.datastructures import CommaSeparatedStrings

        from scripts.parity.adapters.comma_separated_strings import (
            run_comma_separated_strings_case,
        )

        return run_comma_separated_strings_case(case, CommaSeparatedStrings)
    if (
        isinstance(case, dict)
        and case.get("operation") == VALUE_FORMATTING_OPERATION
        and case.get("surface")
        in {EXCEPTION_VALUES_SURFACE, MIDDLEWARE_CONFIG_SURFACE, *ROUTE_REPRESENTATION_SURFACES}
    ):
        return _run_value_formatting_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        HTTP_ROUTE_SURFACE,
        "__init__",
    ):
        return _run_route_endpoint_name_case(case)
    if isinstance(case, dict) and case.get("operation") in {"url_path_for", "url_for"}:
        return _run_reverse_url_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == WEBSOCKET_ENDPOINT_SURFACE
        and case.get("operation") == WEBSOCKET_ENDPOINT_OPERATION
    ):
        return _run_websocket_endpoint_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") == HTTP_ENDPOINT_SURFACE
        and case.get("operation") == HTTP_ENDPOINT_OPERATION
    ):
        return _run_http_endpoint_case(case)
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
        and case.get("surface") == HTTP_ROUTE_SURFACE
        and case.get("operation") == HTTP_ROUTE_CALL_OPERATION
    ):
        return _run_http_route_call_case(case)
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
        and case.get("operation") == STATIC_FILES_CONFIGURATION_OPERATION
    ):
        return _run_static_files_configuration_case(case)
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
    if isinstance(case, dict) and case.get("surface") == SERVER_ERROR_MIDDLEWARE_SURFACE:
        return _run_server_error_middleware_case(case)
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
    if case["surface"] == WSGI_SURFACE:
        if case["operation"] != "__call__":
            raise ValueError("WSGIMiddleware cases must call its public ASGI interface")
        return _run_wsgi_case(case)
    if case["surface"] in {
        "starlette.middleware.gzip.GZipMiddleware",
        "starlette.middleware.gzip.GZipResponder",
    }:
        if case["operation"] != "__call__":
            raise ValueError("GZip cases must call the declared ASGI interface")
        return _run_gzip_case(case)
    if case["surface"] == BODY_LIMIT_SURFACE:
        if case["operation"] != "__call__":
            raise ValueError("RequestBodyLimitMiddleware cases must call its public ASGI interface")
        return _run_body_limit_case(case)
    steps = case["steps"]
    step_ids = [step["step_id"] for step in steps]
    schedule = case["execution_schedule"]
    is_request_dispatch = case["operation"] == "request-dispatch"
    route_specs = steps[0]["arguments"]["routes"]["value"]
    route_middleware_workflow = _routes_have_local_middleware(route_specs) or (
        _has_mounted_app_exception_route(route_specs)
    )
    if is_request_dispatch:
        endpoint_spec = steps[0]["arguments"]["routes"]["value"][0]["endpoint"]
        expected_schedule = (
            ["dispatch", "cancel-server-task"]
            if endpoint_spec == {"kind": "async-call-boundary-observer"}
            or (
                isinstance(endpoint_spec, dict)
                and endpoint_spec.get("kind") == "sync-request-cancellation-observer"
            )
            else ["dispatch"]
        )
        if (
            step_ids != ["application", "dispatch"]
            or steps[-1].get("operation") != "request-dispatch"
            or schedule != expected_schedule
        ):
            raise ValueError(
                "request-dispatch cases must contain application then request-dispatch"
            )
    elif route_middleware_workflow:
        minimum_steps = 2 if _has_mounted_app_exception_route(route_specs) else 3
        if len(steps) < minimum_steps or schedule != step_ids[1:]:
            raise ValueError(
                "route middleware workflow must schedule its input dispatches in order"
            )
    elif step_ids not in (
        ["application", "lifecycle"],
        ["application", "lifecycle", "dispatch"],
        ["application", "dispatch"],
        ["application", "dispatch-get", "dispatch-head"],
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
        or (
            step_ids == ["application", "dispatch-get", "dispatch-head"]
            and (
                schedule != ["dispatch-get", "dispatch-head"]
                or steps[0]["arguments"]["routes"]["value"][0]["endpoint"]["kind"]
                != "sync-plain-text-response"
                or steps[0]["arguments"]["routes"]["value"][0]["methods"] is not None
            )
        )
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
    endpoint_spec = route_spec.get("endpoint") if isinstance(route_spec, dict) else None
    endpoint_kind = endpoint_spec.get("kind") if isinstance(endpoint_spec, dict) else None
    capture_dispatch_error = (
        is_request_dispatch
        or route_middleware_workflow
        or endpoint_kind
        in {
            "asgi-callable-action-sequence",
            "raise-runtime-error",
        }
        or route_spec.get("kind") == "websocket-route"
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
            if endpoint_kind == "sync-plain-text-response":
                for state in sync_endpoint_states:
                    with state["lock"]:
                        state["invocation_count"] = 0
                        state["observation"] = None
            value = await _invoke(
                app,
                args,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                is_request_dispatch and step["operation"] == "request-dispatch",
                sync_endpoint_states=sync_endpoint_states,
                capture_dispatch_error=capture_dispatch_error,
                capture_dispatch_error_as_observation=(
                    _has_mounted_app_exception_route(route_specs)
                ),
                cancel_after_endpoint_entry=(
                    case["execution_schedule"] == ["dispatch", "cancel-server-task"]
                ),
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
