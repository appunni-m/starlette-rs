"""Live adapter for the pinned Starlette 1.6.0 source checkout."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import functools
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
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
WEBSOCKET_ROUTE_SURFACE = "starlette.routing.WebSocketRoute"
WEBSOCKET_ROUTE_OPERATION = "route-dispatch"
ROUTER_SURFACE = "starlette.routing.Router"
ROUTER_OPERATION = "route-dispatch"
MOUNT_SURFACE = "starlette.routing.Mount"
MOUNT_OPERATION = "route-dispatch"
REDIRECT_RESPONSE_SURFACE = "starlette.responses.RedirectResponse"
REDIRECT_RESPONSE_OPERATION = "asgi-call"
_MISSING = object()


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
        ["git", "-C", str(root), "diff", "--quiet", "--", "starlette"],
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
        return {"type": "lifespan", "asgi": dict(spec["asgi"])}
    return {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "method": spec["method"],
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


def _message(spec: dict[str, Any]) -> dict[str, Any]:
    if spec["type"] in {"lifespan.startup", "lifespan.shutdown"}:
        return {"type": spec["type"]}
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


def _materialize_application(
    app_spec: dict[str, Any],
) -> tuple[Any, list[str], list[dict[str, Any]], Any, list[dict[str, Any]]]:
    from starlette.applications import Starlette
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route

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
    if lifespan_spec != {
        "kind": "async-context-manager",
        "record_entry": True,
        "record_exit": True,
    }:
        raise ValueError("lifespan input must use the declared async-context-manager marker")
    lifecycle_trace: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        lifecycle_trace.append("entry")
        try:
            yield
        finally:
            lifecycle_trace.append("exit")

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
        handler_calls,
    )
    for route in app_spec["routes"]:
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
    app = Starlette(
        debug=app_spec["debug"],
        routes=route_objects,
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
    if start is None and scope["type"] != "lifespan":
        raise RuntimeError("Starlette completed without an http.response.start event")
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
    return result


def _literal_arguments(step: dict[str, Any], expected: set[str], context: str) -> dict[str, Any]:
    arguments = _strict_object(step["arguments"], expected, f"{context} arguments")
    values: dict[str, Any] = {}
    for name, descriptor in arguments.items():
        descriptor = _strict_object(descriptor, {"kind", "value"}, f"{context}.{name}")
        if descriptor["kind"] != "literal":
            raise ValueError(f"{context}.{name} must be an input literal")
        values[name] = descriptor["value"]
    return values


def _materialize_gzip_middleware(arguments: dict[str, Any]) -> Any:
    from starlette.middleware.gzip import GZipMiddleware

    app_spec = _strict_object(arguments["app"], {"kind", "messages"}, "GZipMiddleware app")
    if app_spec["kind"] != "asgi-response-sequence" or not isinstance(app_spec["messages"], list):
        raise ValueError("GZipMiddleware app must be an input-defined response sequence")
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
    from starlette.routing import Mount, Route, Router

    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], _MISSING) for spec in custom_convertors
    }
    mount_scope_observations: list[dict[str, Any]] = []
    route_index_observations: list[int] = []

    def make_endpoint(endpoint_spec: dict[str, Any], route_index: int) -> Any:
        async def endpoint(request: Any) -> Any:
            if is_router:
                route_index_observations.append(route_index)
            if is_mount:
                request_scope = request.scope
                mount_scope_observations.append(
                    {
                        "root_path": request_scope.get("root_path", ""),
                        "app_root_path": request_scope.get("app_root_path"),
                        "path_params": _route_path_params(request_scope),
                    }
                )
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

    async def run() -> tuple[dict[str, Any], dict[str, Any] | None]:
        route_objects = []
        for route_index, route_spec in enumerate(routes_spec):
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
        mount_scope = mount_scope_observations[0] if mount_scope_observations else None
        if len(mount_scope_observations) > 1:
            raise RuntimeError("Mount child route endpoint ran more than once")
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
    from starlette.routing import Mount, Route, Router, WebSocketRoute

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

    lifespan_task = asyncio.create_task(
        app(_make_scope(lifecycle_args["scope"]), receive_lifecycle, send_lifecycle)
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
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
        "server_error_observation": {"handler_calls": [], "debug_traceback": None},
    }
    return lifecycle_value, dispatch_value


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
    if (
        isinstance(case, dict)
        and case.get("surface") in {ROUTER_SURFACE, MOUNT_SURFACE}
        and case.get("operation") == "route-dispatch"
    ):
        return _run_route_dispatch_case(case)
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
    elif step_ids not in (["application", "lifecycle", "dispatch"], ["application", "dispatch"]):
        raise ValueError("oracle adapter received a workflow outside the declared ASGI slice")
    elif (
        step_ids == ["application", "lifecycle", "dispatch"]
        and schedule != ["lifespan.startup", "dispatch", "lifespan.shutdown"]
    ) or (step_ids == ["application", "dispatch"] and schedule != ["dispatch"]):
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
    capture_dispatch_error = is_request_dispatch or application_arguments["routes"][0]["endpoint"][
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
    ) = _materialize_application(application_arguments)

    async def run_steps() -> list[dict[str, Any]]:
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
