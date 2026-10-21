"""Live target adapter for the installed ``starlette-rs-py`` package.

The adapter accepts one JSON request per fresh process and uses only the
installed public ``starlette.*`` consumer surface for workflows. Diagnostics
go to stderr; stdout contains exactly one JSON response.
"""

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
import importlib.metadata
import inspect
import io
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import threading
import warnings
import weakref
from collections import UserDict
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any

from scripts.parity.adapters.application_inputs import (
    ObservableMapping,
    ObservableSequence,
    middleware_with_iterator_override,
    snapshot_application_attributes,
)
from scripts.parity.adapters.input_pathlike import InputSequencePathLike
from scripts.parity.adapters.staticfiles_config import (
    STATIC_FILES_CONFIGURATION_OPERATION,
    run_static_files_configuration_case,
)
from scripts.parity.adapters.status_module import run_status_module_sequence
from scripts.parity.adapters.websocket_json_mode import (
    materialize_websocket_json_mode,
    materialize_websocket_json_payload,
)

REQUEST_SCHEMA = "migration-parity/adapter-request@1"
RESPONSE_SCHEMA = "migration-parity/adapter-response@1"
SUBJECT_ID = "python-package"
PACKAGE_NAME = "starlette-rs-py"
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
HOST_SURFACE = "starlette.routing.Host"
MOUNT_SURFACE = "starlette.routing.Mount"
ROUTE_REPRESENTATION_SURFACES = {
    HTTP_ROUTE_SURFACE,
    WEBSOCKET_ROUTE_SURFACE,
    MOUNT_SURFACE,
    HOST_SURFACE,
}
REDIRECT_RESPONSE_SURFACE = "starlette.responses.RedirectResponse"
REDIRECT_RESPONSE_OPERATION = "asgi-call"
RESPONSE_SURFACE = "starlette.responses.Response"
JSON_RESPONSE_SURFACE = "starlette.responses.JSONResponse"
STREAMING_RESPONSE_SURFACE = "starlette.responses.StreamingResponse"
STREAMING_RESPONSE_AWAIT_INSTANCE_SHADOW_MODE = "async-iterator-await-instance-shadow"
FILE_RESPONSE_SURFACE = "starlette.responses.FileResponse"
STATIC_FILES_SURFACE = "starlette.staticfiles.StaticFiles"
STATIC_FILES_LOOKUP_PATH_OPERATION = "lookup-path"
STATIC_FILES_GET_RESPONSE_OPERATION = "get-response"
STATIC_FILES_ASYNC_BOUNDARY_OPERATION = "asgi-call-async-boundary"
RESPONSE_OPERATION = "asgi-call"
STREAMING_RESPONSE_TRACE_OPERATION = "asgi-call-with-execution-trace"
BODY_LIMIT_SURFACE = "starlette.middleware.body_limit.RequestBodyLimitMiddleware"
WSGI_SURFACE = "starlette.middleware.wsgi.WSGIMiddleware"
CORS_SURFACE = "starlette.middleware.cors.CORSMiddleware"
HTTPS_REDIRECT_SURFACE = "starlette.middleware.httpsredirect.HTTPSRedirectMiddleware"
TRUSTED_HOST_SURFACE = "starlette.middleware.trustedhost.TrustedHostMiddleware"
SERVER_ERROR_MIDDLEWARE_SURFACE = "starlette.middleware.errors.ServerErrorMiddleware"
EXCEPTION_MIDDLEWARE_SURFACE = "starlette.middleware.exceptions.ExceptionMiddleware"
SESSION_MIDDLEWARE_SURFACE = "starlette.middleware.sessions.SessionMiddleware"
SESSION_WORKFLOW_OPERATION = "session-workflow"
BASE_HTTP_SURFACE = "starlette.middleware.base.BaseHTTPMiddleware"
BASE_HTTP_WORKFLOW_OPERATION = "base-http-workflow"
BASE_HTTP_STATUS_INTEGER_REQUIREMENT = (
    f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.downstream-status-integer-pass-through"
)
BASE_HTTP_SCOPE_TYPE_INEQUALITY_REQUIREMENT = (
    f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.scope-type-python-inequality"
)
BASE_HTTP_RESPONSE_START_TYPE_EQUALITY_REQUIREMENT = f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.response-start-message-type-python-equality"
BASE_HTTP_RESPONSE_BODY_TYPE_EQUALITY_REQUIREMENT = (
    f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.response-body-message-type-python-equality"
)
BASE_HTTP_RESPONSE_PATHSEND_TYPE_EQUALITY_REQUIREMENT = f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.response-pathsend-message-type-python-equality"
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
REQUEST_BASE_URL_OPERATION = ("starlette.requests.Request", "base_url")
REQUEST_SCOPE_MAPPING_OPERATION = ("starlette.requests.Request", "scope-mapping")
REQUEST_IDENTITY_HASH_SEQUENCE_OPERATION = (
    "starlette.requests.Request",
    "scope-identity-hash-sequence",
)
REQUEST_STATE_READBACK_OPERATION = ("starlette.requests.Request", "state-setdefault-readback")
REQUEST_HEADER_CACHE_SEQUENCE_OPERATION = ("starlette.requests.Request", "header-cache-sequence")
REQUEST_COOKIE_CACHE_SEQUENCE_OPERATION = ("starlette.requests.Request", "cookie-cache-sequence")
REQUEST_CONSTRUCTOR_OPERATION = ("starlette.requests.Request", "constructor-contract")
WEBSOCKET_SCOPE_MAPPING_OPERATION = ("starlette.websockets.WebSocket", "scope-mapping")
WEBSOCKET_IDENTITY_HASH_SEQUENCE_OPERATION = (
    "starlette.websockets.WebSocket",
    "scope-identity-hash-sequence",
)
WEBSOCKET_CONSTRUCTOR_OPERATION = ("starlette.websockets.WebSocket", "constructor-contract")
WEBSOCKET_DISCONNECT_CONSTRUCTOR_OPERATION = (
    "starlette.websockets.WebSocketDisconnect",
    "constructor-contract",
)
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
    ("starlette.config", "environ"),
}
SCHEMA_OPERATIONS = {
    ("starlette.schemas.SchemaGenerator", "schema-generation"),
    ("starlette.schemas.BaseSchemaGenerator", "schema-docstring-parsing"),
    ("starlette.schemas.BaseSchemaGenerator", "get-schema"),
    ("starlette.schemas.OpenAPIResponse", "openapi-response-render"),
    ("starlette.schemas.OpenAPIResponse", "schema-endpoint-asgi-call"),
}
URL_QUERY_OPERATION = ("starlette.datastructures.URL", "query-parameter-operations")
URL_SCOPE_OPERATION = ("starlette.datastructures.URL", "scope-construction")
NATIVE_SERVICE_SURFACE = "starlette-rs.NativeApplication"
NATIVE_SERVICE_OPERATION = "service-body-streaming"
NATIVE_MOUNTED_CHILD_OPERATION = "service-mounted-child"
NATIVE_HOST_SERVICE_SURFACE = "starlette-rs.NativeHostApplication"
NATIVE_HOST_SERVICE_OPERATION = "service-host-routing"
NATIVE_STREAM_SOURCE_SURFACE = "starlette-rs.StreamingResponse"
NATIVE_STREAM_SOURCE_OPERATION = "lazy-source-call"
NATIVE_ROUTE_TABLE_SURFACE = "starlette-rs.RouteTable"
NATIVE_ROUTE_TABLE_CONVERTER_OPERATION = "custom-converter-match"
NATIVE_NAMED_ROUTE_SURFACE = "starlette-rs.NamedRoute"
NATIVE_NAMED_ROUTE_CONVERTER_OPERATION = "custom-converter-url-path-for"
NATIVE_WEBSOCKET_SURFACE = "starlette-rs.NativeWebSocket"
NATIVE_WEBSOCKET_OPERATION = "native-session-sequence"
NATIVE_LIFESPAN_SURFACE = "starlette-rs.NativeLifespan"
NATIVE_LIFESPAN_OPERATION = "native-lifespan"
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
    values: list[Any],
    execution_trace: list[dict[str, Any]] | None,
    finally_marker: str | None = None,
) -> AsyncIterator[Any]:
    try:
        for value in values:
            if execution_trace is not None:
                execution_trace.append({"event": "iterator-yield", "value": _json_safe(value)})
            yield value
    finally:
        if execution_trace is not None and finally_marker is not None:
            execution_trace.append({"event": "iterator-finally", "marker": finally_marker})


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
    values: list[str],
    execution_trace: list[dict[str, Any]],
    failure: dict[str, str] | None = None,
) -> None:
    execution_trace.append({"event": "background-start"})
    for value in values:
        execution_trace.append({"event": "background-value", "value": value})
    if failure is not None:
        execution_trace.append(
            {
                "event": "background-error",
                "class": failure["kind"],
                "message": failure["message"],
            }
        )
        raise OSError(failure["message"])
    execution_trace.append({"event": "background-complete"})


def _record_input_background_task(
    task_index: int,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    failure: dict[str, str] | None,
    execution_trace: list[dict[str, Any]],
    event_loop_thread_id: list[int | None],
    before_complete: Callable[[], None] | None = None,
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
        if failure["kind"] == "CancelledError":
            raise asyncio.CancelledError(failure["message"])
        raise Exception(failure["message"])
    if before_complete is not None:
        before_complete()
    execution_trace.append({"event": "task-complete", "task_index": task_index})


class _OrderedKeywordMapping:
    def __init__(self, items: list[list[Any]]) -> None:
        self._items = items

    def keys(self) -> list[Any]:
        return [key for key, _value in self._items]

    def __getitem__(self, key: Any) -> Any:
        for candidate, value in self._items:
            if candidate == key:
                return value
        raise KeyError(key)


class _InputArgumentIterable:
    def __init__(self, exception_class: type[BaseException], message: str) -> None:
        self.exception_class = exception_class
        self.message = message

    def __iter__(self) -> Any:
        raise self.exception_class(self.message)


def _input_background_tasks(
    spec: dict[str, Any],
    execution_trace: list[dict[str, Any]],
    event_loop_thread_id: list[int | None],
    cancellation_started: asyncio.Event | None = None,
    cancellation_release: threading.Event | None = None,
    cancellation_finished: asyncio.Event | None = None,
    event_loop: list[asyncio.AbstractEventLoop | None] | None = None,
) -> Any:
    from starlette.background import BackgroundTask, BackgroundTasks

    if spec["kind"] not in {
        "single-task",
        "single-task-subclass-properties",
        "task-list",
        "task-list-constructor",
        "task-list-subclass-property",
    }:
        raise ValueError("Response background task kind is unsupported")
    if not isinstance(spec["tasks"], list) or not spec["tasks"]:
        raise ValueError("Response background tasks must be a non-empty array")
    if (
        spec["kind"] in {"single-task", "single-task-subclass-properties"}
        and len(spec["tasks"]) != 1
    ):
        raise ValueError("Response background task count does not match its kind")
    if spec["kind"] in {"task-list", "task-list-constructor"} and len(spec["tasks"]) < 2:
        raise ValueError("Response background task lists must contain multiple tasks")
    background_tasks = BackgroundTasks() if spec["kind"] == "task-list" else None

    def delete_input_tasks(deleted_indices: list[int], parent_task_index: int) -> None:
        if not deleted_indices:
            return
        if background_tasks is None:
            raise RuntimeError("live task-list mutation requires BackgroundTasks")
        for task_index in sorted(deleted_indices, reverse=True):
            del background_tasks.tasks[task_index]
        execution_trace.append(
            {
                "event": "task-list-mutated",
                "task_index": parent_task_index,
                "deleted_task_indices": sorted(deleted_indices, reverse=True),
            }
        )

    def append_input_tasks(appended_specs: list[dict[str, Any]], parent_task_index: int) -> None:
        if not appended_specs:
            return
        if background_tasks is None:
            raise RuntimeError("live task-list mutation requires BackgroundTasks")
        appended_task_indices = []
        for appended_spec in appended_specs:
            task_index = len(background_tasks.tasks)
            callback = make_callback(task_index, appended_spec)
            background_tasks.tasks.append(
                BackgroundTask(callback, *appended_spec["args"], **appended_spec["kwargs"])
            )
            appended_task_indices.append(task_index)
        execution_trace.append(
            {
                "event": "task-list-mutated",
                "task_index": parent_task_index,
                "appended_task_indices": appended_task_indices,
            }
        )

    def make_callback(task_index: int, task_spec: dict[str, Any]) -> Any:
        failure = task_spec["failure"]
        append_specs = task_spec.get("append_tasks", [])
        delete_indices = task_spec.get("delete_task_indices", [])

        def mutate_scheduled_tasks() -> None:
            append_input_tasks(append_specs, task_index)
            delete_input_tasks(delete_indices, task_index)

        before_complete = mutate_scheduled_tasks if append_specs or delete_indices else None
        if task_spec["mode"] == "async":

            async def base_callback(*args: Any, **kwargs: Any) -> None:
                if cancellation_started is None:
                    _record_input_background_task(
                        task_index,
                        args,
                        kwargs,
                        failure,
                        execution_trace,
                        event_loop_thread_id,
                        before_complete,
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
                        task_index,
                        args,
                        kwargs,
                        failure,
                        execution_trace,
                        event_loop_thread_id,
                        before_complete,
                    )
                    return
                if (
                    cancellation_release is None
                    or cancellation_finished is None
                    or event_loop is None
                    or event_loop[0] is None
                ):
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
                try:
                    if not cancellation_release.wait(timeout=5.0):
                        raise TimeoutError("synchronous background task was not released")
                    execution_trace.append(
                        {"event": "task-release-observed", "task_index": task_index}
                    )
                    if failure is not None:
                        execution_trace.append(
                            {
                                "event": "task-error",
                                "task_index": task_index,
                                "class": failure["kind"],
                                "message": failure["message"],
                                "thread": "worker",
                            }
                        )
                        if failure["kind"] == "CancelledError":
                            raise asyncio.CancelledError(failure["message"])
                        raise Exception(failure["message"])
                    execution_trace.append({"event": "task-complete", "task_index": task_index})
                finally:
                    execution_trace.append(
                        {
                            "event": "task-finally",
                            "task_index": task_index,
                            "thread": (
                                "event-loop"
                                if threading.get_ident() == event_loop_thread_id[0]
                                else "worker"
                            ),
                        }
                    )
                    event_loop[0].call_soon_threadsafe(cancellation_finished.set)

        callable_spec = task_spec.get("callable", {"kind": "function"})
        callable_kind = callable_spec["kind"]
        callback = base_callback
        if callable_kind == "builtin":
            callback = getattr(builtins, callable_spec["name"])
        elif callable_kind == "non-callable-object":
            callback = object()
        elif callable_kind == "bound-method":
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
        if callable_kind == "function" and "identity" in callable_spec:
            identity = callable_spec["identity"]
            callback.__module__ = identity["module"]
            callback.__qualname__ = identity["qualname"]
            callback.__name__ = identity["qualname"].rsplit(".", 1)[-1]
        return callback

    tasks = []
    subclass_public_attributes = None
    subclass_callback = None
    if spec["kind"] == "single-task-subclass-properties":
        subclass_public_attributes = _exact_object(
            spec["public_attributes"],
            {"is_async", "func", "args", "kwargs"},
            "Response background task subclass public attributes",
        )
        subclass_callback_spec = _exact_object(
            subclass_public_attributes["func"],
            {"mode", "failure"},
            "Response background task subclass func",
        )
        subclass_callback = make_callback(0, subclass_callback_spec)

    for task_index, task_spec in enumerate(spec["tasks"]):
        task_fields = {"mode", "args", "kwargs", "failure"}
        if isinstance(task_spec, dict) and "callable" in task_spec:
            task_fields.add("callable")
        if isinstance(task_spec, dict) and "kwargs_mapping" in task_spec:
            task_fields.add("kwargs_mapping")
        if isinstance(task_spec, dict) and "append_tasks" in task_spec:
            task_fields.add("append_tasks")
        if isinstance(task_spec, dict) and "delete_task_indices" in task_spec:
            task_fields.add("delete_task_indices")
        if isinstance(task_spec, dict) and "argument_protocol" in task_spec:
            task_fields.add("argument_protocol")
        task_spec = _exact_object(
            task_spec,
            task_fields,
            f"Response background task[{task_index}]",
        )
        if task_spec["mode"] not in {"sync", "async"}:
            raise ValueError("Response background task mode is unsupported")
        if not isinstance(task_spec["args"], list) or not isinstance(task_spec["kwargs"], dict):
            raise ValueError("Response background task arguments must be arrays and objects")
        if "delete_task_indices" in task_spec:
            delete_indices = task_spec["delete_task_indices"]
            if (
                background_tasks is None
                or not isinstance(delete_indices, list)
                or not delete_indices
                or any(type(index) is not int or index < 0 for index in delete_indices)
                or len(set(delete_indices)) != len(delete_indices)
            ):
                raise ValueError("Response background delete_task_indices input is invalid")
        if "append_tasks" in task_spec:
            if background_tasks is None:
                raise ValueError("live task-list mutation requires a BackgroundTasks list")
            appended_specs = task_spec["append_tasks"]
            if not isinstance(appended_specs, list) or not appended_specs:
                raise ValueError("Response background append_tasks must be a non-empty array")
            validated_appended_specs = []
            for appended_index, appended_spec in enumerate(appended_specs):
                appended_spec = _exact_object(
                    appended_spec,
                    {"mode", "args", "kwargs", "failure"},
                    f"Response background task[{task_index}].append_tasks[{appended_index}]",
                )
                if appended_spec["mode"] not in {"sync", "async"}:
                    raise ValueError("Response appended background task mode is unsupported")
                if not isinstance(appended_spec["args"], list) or not isinstance(
                    appended_spec["kwargs"], dict
                ):
                    raise ValueError("Response appended background task arguments are invalid")
                appended_failure = appended_spec["failure"]
                if appended_failure is not None:
                    appended_failure = _exact_object(
                        appended_failure,
                        {"kind", "message"},
                        f"Response background task[{task_index}].append_tasks[{appended_index}].failure",
                    )
                    if appended_failure["kind"] not in {
                        "Exception",
                        "CancelledError",
                    } or not isinstance(appended_failure["message"], str):
                        raise ValueError("Response appended background task failure is unsupported")
                    appended_spec["failure"] = appended_failure
                validated_appended_specs.append(appended_spec)
            task_spec["append_tasks"] = validated_appended_specs
        failure = task_spec["failure"]
        if failure is not None:
            failure = _exact_object(
                failure, {"kind", "message"}, f"Response background task[{task_index}].failure"
            )
            if failure["kind"] not in {"Exception", "CancelledError"} or not isinstance(
                failure["message"], str
            ):
                raise ValueError("Response background task failure input is unsupported")
        callback = make_callback(task_index, task_spec)
        if background_tasks is None:
            if spec["kind"] == "single-task-subclass-properties":
                public_attributes = subclass_public_attributes
                public_callback = subclass_callback

                class InputBackgroundTask(BackgroundTask):
                    _input_public_attributes = public_attributes
                    _input_public_callback = public_callback

                    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                        pass

                    @property
                    def is_async(self) -> bool:
                        return type(self)._input_public_attributes["is_async"]

                    @property
                    def func(self) -> Any:
                        return type(self)._input_public_callback

                    @property
                    def args(self) -> tuple[Any, ...]:
                        return tuple(type(self)._input_public_attributes["args"])

                    @property
                    def kwargs(self) -> dict[str, Any]:
                        return type(self)._input_public_attributes["kwargs"]

                task = InputBackgroundTask(callback, *task_spec["args"], **task_spec["kwargs"])
            else:
                task = BackgroundTask(callback, *task_spec["args"], **task_spec["kwargs"])
            if "argument_protocol" in task_spec:
                protocol = _exact_object(
                    task_spec["argument_protocol"],
                    {"kind", "exception_class", "message"},
                    f"Response background task[{task_index}].argument_protocol",
                )
                if protocol["kind"] != "raise-on-iteration":
                    raise ValueError("Response background argument protocol is unsupported")
                if protocol["exception_class"] != "RuntimeError":
                    raise ValueError("Response background argument exception is unsupported")

                task.args = _InputArgumentIterable(RuntimeError, protocol["message"])
                del task.kwargs
            if "kwargs_mapping" in task_spec:
                mapping_spec = _exact_object(
                    task_spec["kwargs_mapping"],
                    {"kind", "items"},
                    f"Response background task[{task_index}].kwargs_mapping",
                )
                if mapping_spec["kind"] == "user-dict":
                    task.kwargs = UserDict(dict(mapping_spec["items"]))
                elif mapping_spec["kind"] == "ordered-key-mapping":
                    task.kwargs = _OrderedKeywordMapping(mapping_spec["items"])
                else:
                    raise ValueError("Response background kwargs mapping kind is unsupported")
            tasks.append(task)
        else:
            background_tasks.add_task(callback, *task_spec["args"], **task_spec["kwargs"])
    if spec["kind"] in {"single-task", "single-task-subclass-properties"}:
        return tasks[0]
    if spec["kind"] == "task-list-constructor":
        return BackgroundTasks(tasks)
    if spec["kind"] == "task-list-subclass-property":
        visible_tasks = [tasks[index] for index in spec["tasks_property_indices"]]

        class InputBackgroundTasks(BackgroundTasks):
            @property
            def tasks(self) -> list[Any]:
                return visible_tasks

            @tasks.setter
            def tasks(self, value: list[Any]) -> None:
                self._constructor_tasks = value

        background_tasks = InputBackgroundTasks(tasks)
        if "add_task" in spec:
            add_task_spec = spec["add_task"]
            task_index = len(spec["tasks"])
            callback = make_callback(task_index, add_task_spec)
            background_tasks.add_task(
                callback,
                *add_task_spec["args"],
                **add_task_spec["kwargs"],
            )
        return background_tasks
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


def _exception_context_chain(exc: BaseException) -> list[dict[str, str]]:
    context = exc.__context__
    chain: list[dict[str, str]] = []
    seen: set[int] = set()
    while context is not None and id(context) not in seen:
        seen.add(id(context))
        chain.append(
            {
                "class": f"{type(context).__module__}.{type(context).__qualname__}",
                "message": str(context),
            }
        )
        context = context.__context__
    return chain


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


def _is_cpython_package_profile(profile: Any) -> bool:
    prefix = "python-package-cpython"
    return (
        isinstance(profile, str)
        and profile.startswith(prefix)
        and profile[len(prefix) :].isascii()
        and profile[len(prefix) :].isdecimal()
    )


def _has_unique_cpython_package_profiles(profiles: Any) -> bool:
    return (
        isinstance(profiles, list)
        and bool(profiles)
        and all(_is_cpython_package_profile(profile) for profile in profiles)
        and len(profiles) == len(set(profiles))
    )


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
    if (
        sys.implementation.name != "cpython"
        or sys.version_info.major != 3
        or sys.version_info.minor not in {10, 11, 12, 13, 14}
    ):
        raise RuntimeError("the Python-package target must run in CPython 3.10 through 3.14")
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


def _installed_package_tree_sha256(
    distribution: importlib.metadata.Distribution,
) -> str:
    package_roots = ("starlette", "starlette_rs_py")
    files: dict[str, bytes] = {}
    for package in package_roots:
        package_path = Path(distribution.locate_file(package))
        if package_path.is_symlink():
            raise RuntimeError(f"installed target package root is a symlink: {package_path}")
        if not package_path.is_dir():
            continue
        for path in sorted(package_path.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"installed target package contains a non-file entry: {path}")
            if path.is_dir() or path.suffix in {".pyc", ".pyo"}:
                continue
            if not path.is_file():
                raise RuntimeError(f"installed target package contains a non-file entry: {path}")
            relative = f"{package}/{path.relative_to(package_path).as_posix()}"
            files[relative] = path.read_bytes()
    if not files:
        raise RuntimeError("installed target package has no verifiable package files")
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative])
        digest.update(b"\0")
    return digest.hexdigest()


def _identity(distribution: importlib.metadata.Distribution) -> dict[str, Any]:
    from starlette_rs_py import _core

    dependency_lock_sha256 = os.environ.get("STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256")
    if (
        dependency_lock_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", dependency_lock_sha256) is None
    ):
        raise RuntimeError(
            "STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256 must be a lowercase SHA-256 digest"
        )
    expected_tree_sha256 = os.environ.get("STARLETTE_PARITY_TARGET_TREE_SHA256")
    source_revision = os.environ.get("STARLETTE_PARITY_TARGET_SOURCE_REVISION")
    source_dirty = os.environ.get("STARLETTE_PARITY_TARGET_SOURCE_DIRTY")
    if (
        expected_tree_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_tree_sha256) is None
        or source_revision is None
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", source_revision) is None
        or source_dirty not in {"0", "1"}
    ):
        raise RuntimeError("prepared target package identity is missing or malformed")

    target_tree_sha256 = _installed_package_tree_sha256(distribution)
    dirty = source_dirty == "1" or target_tree_sha256 != expected_tree_sha256
    return {
        "subject_id": SUBJECT_ID,
        "revision": f"dirty-tree:{target_tree_sha256}" if dirty else source_revision,
        "dirty": dirty,
        "runtime": f"{platform.python_implementation()} {platform.python_version()}",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "backend": f"CPython {sys.version_info.major}.{sys.version_info.minor}",
        "features": (
            ["fault-contract"]
            if hasattr(_core.RouterRuntime, "_fault_contract_poison_route_cache")
            else []
        ),
        "package_version": distribution.version,
        "dependency_lock_sha256": dependency_lock_sha256,
        "target_tree_sha256": target_tree_sha256,
    }


def _decode_base64(value: str, context: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid base64 at {context}") from exc


class _ObservedScopeUserDict(UserDict):
    def __init__(self, scope: dict[str, Any], fault: dict[str, Any] | None = None) -> None:
        self.parity_operations: list[dict[str, Any]] = []
        self.parity_fault = fault
        super().__init__(scope)
        self.parity_operations.clear()

    def __getitem__(self, key: Any) -> Any:
        self.parity_operations.append({"operation": "getitem", "key": _json_safe(key)})
        fault = self.parity_fault
        if fault is not None and key == fault["key"]:
            exception_type = getattr(builtins, fault["exception"]["class"])
            raise exception_type(fault["exception"]["message"])
        return super().__getitem__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self.parity_operations.append({"operation": "setitem", "key": _json_safe(key)})
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        self.parity_operations.append({"operation": "delitem", "key": _json_safe(key)})
        super().__delitem__(key)

    def __contains__(self, key: object) -> bool:
        self.parity_operations.append({"operation": "contains", "key": _json_safe(key)})
        return key in self.data

    def get(self, key: Any, default: Any = None) -> Any:
        self.parity_operations.append({"operation": "get", "key": _json_safe(key)})
        try:
            return self[key]
        except KeyError:
            return default


def _scope_container(
    scope: dict[str, Any], container: str | dict[str, Any]
) -> dict[str, Any] | UserDict:
    if container == "user-dict":
        return _ObservedScopeUserDict(scope)
    if isinstance(container, dict) and container.get("kind") == "user-dict-fault":
        fault = container["fault"]
        if fault["method"] != "__getitem__":
            raise ValueError("ASGI scope lookup fault must select __getitem__")
        return _ObservedScopeUserDict(scope, fault)
    if container == "dict":
        return scope
    raise ValueError(f"unsupported ASGI scope container: {container!r}")


def _scope_observation(
    scope: dict[str, Any] | UserDict, selector: dict[str, Any]
) -> dict[str, Any]:
    data = scope.data if isinstance(scope, UserDict) else scope
    selected = {
        key: {
            "present": key in data,
            "value": _scope_observation_value(data[key]) if key in data else None,
        }
        for key in selector["keys"]
    }
    operations = getattr(scope, "parity_operations", [])
    return {"selected_keys": selected, "mapping_operations": list(operations)}


def _scope_observation_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, bytes, dict, list, tuple)):
        if isinstance(value, bytes):
            return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
        if isinstance(value, dict):
            return {str(key): _scope_observation_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_scope_observation_value(item) for item in value]
        return value
    return {"type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _materialize_scope_type_spec(value: Any) -> tuple[Any, Any]:
    if not isinstance(value, dict) or set(value) != {"str_subclass"}:
        return value, value
    descriptor = _exact_object(value, {"str_subclass"}, "scope type")
    subclass = descriptor["str_subclass"]
    if not isinstance(subclass, dict) or not isinstance(subclass.get("value"), str):
        raise ValueError("scope type str_subclass requires a string value")
    behavior = set(subclass) - {"value"}
    if behavior == {"equal_result"} and type(subclass["equal_result"]) is bool:
        return (
            _InputStringSubclass(subclass["value"], equal_result=subclass["equal_result"]),
            subclass["value"],
        )
    if behavior == {"not_equal_result"} and type(subclass["not_equal_result"]) is bool:
        return (
            _InputStringSubclass(subclass["value"], not_equal_result=subclass["not_equal_result"]),
            subclass["value"],
        )
    raise ValueError("scope type str_subclass must declare one boolean comparison result")


def _materialize_scope_method_spec(value: Any) -> Any:
    if not isinstance(value, dict) or set(value) != {"str_subclass"}:
        return value
    descriptor = _exact_object(value, {"str_subclass"}, "scope method")
    subclass = _exact_object(
        descriptor["str_subclass"], {"value", "upper_result"}, "scope method str_subclass"
    )
    method_value = subclass["value"]
    upper_result = subclass["upper_result"]
    if not isinstance(method_value, str) or not isinstance(upper_result, str):
        raise ValueError("scope method str_subclass values must be strings")

    class InputMethodSubclass(str):
        def upper(self, result: str = upper_result) -> str:
            return result

    return InputMethodSubclass(method_value)


def _materialize_scope_path_spec(value: Any) -> Any:
    if not isinstance(value, dict) or set(value) != {"str_subclass"}:
        return value
    descriptor = _exact_object(value, {"str_subclass"}, "scope path")
    subclass = descriptor["str_subclass"]
    allowed_fields = {"value", "startswith_result"}
    if isinstance(subclass, dict):
        if "slice_result" in subclass:
            allowed_fields.add("slice_result")
        if "split_result" in subclass:
            allowed_fields.add("split_result")
    if not isinstance(subclass, dict) or set(subclass) != allowed_fields:
        raise ValueError("scope path str_subclass has unsupported fields")
    path_value = subclass["value"]
    startswith_result = subclass["startswith_result"]
    if not isinstance(path_value, str) or type(startswith_result) is not bool:
        raise ValueError("scope path str_subclass requires a string and boolean startswith result")
    has_slice_result = "slice_result" in subclass
    slice_result = subclass.get("slice_result")
    if has_slice_result and slice_result is not None and not isinstance(slice_result, str):
        raise ValueError("scope path str_subclass slice_result must be a string or null")
    has_split_result = "split_result" in subclass
    split_result = subclass.get("split_result")

    class InputPathSubclass(str):
        def startswith(self, _prefix: Any, start: int = 0, end: int | None = None) -> bool:
            return startswith_result

        if has_slice_result:

            def __getitem__(self, key: Any) -> Any:
                if isinstance(key, slice):
                    return slice_result
                return str.__getitem__(self, key)

        if has_split_result:

            def split(self, _separator: str | None = None, _maxsplit: int = -1) -> Any:
                return split_result

    return InputPathSubclass(path_value)


def _make_scope(
    spec: dict[str, Any], container: str | dict[str, Any] = "dict"
) -> dict[str, Any] | UserDict:
    scope_type, scope_type_value = _materialize_scope_type_spec(spec["type"])
    if scope_type_value == "lifespan":
        scope = {"type": scope_type, "asgi": dict(spec["asgi"])}
        if "state" in spec:
            scope["state"] = dict(spec["state"])
        return _scope_container(scope, container)
    if set(spec) == {"type"}:
        return _scope_container({"type": scope_type}, container)
    if set(spec) == {"type", "version", "method", "path"}:
        return _scope_container({**spec, "type": scope_type}, container)
    scope = {
        "type": scope_type,
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": _materialize_scope_path_spec(spec["path"]),
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
    if scope_type_value == "http" and "method" in spec:
        scope["method"] = _materialize_scope_method_spec(spec["method"])
    elif scope_type_value == "websocket":
        scope["subprotocols"] = list(spec["subprotocols"])
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    if "app" in spec:
        scope["app"] = spec["app"]
    if "app_root_path" in spec:
        scope["app_root_path"] = spec["app_root_path"]
    if "path_params" in spec:
        scope["path_params"] = dict(spec["path_params"])
    return _scope_container(scope, container)


def _static_files_scope_path(value: Any, context: str) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"str_subclass"}:
        return value
    encoded_path = _exact_object(value, {"encoding", "data"}, context)
    if encoded_path["encoding"] != "filesystem-bytes-base64":
        raise ValueError(f"{context}.encoding must be filesystem-bytes-base64")
    return os.fsdecode(_decode_base64(encoded_path["data"], f"{context}.data"))


def _make_static_files_scope(
    spec: dict[str, Any], container: str | dict[str, Any] = "dict"
) -> dict[str, Any] | UserDict:
    decoded_spec = dict(spec)
    decoded_spec["path"] = _static_files_scope_path(spec["path"], "StaticFiles scope.path")
    decoded_spec["root_path"] = _static_files_scope_path(
        spec["root_path"], "StaticFiles scope.root_path"
    )
    return _make_scope(decoded_spec, container)


def _apply_request_form_deferred_scope_headers(scope: dict[str, Any], case: dict[str, Any]) -> None:
    if "form_deferred_scope_headers" in case:
        scope["headers"][:] = [
            (
                base64.b64decode(name, validate=True),
                base64.b64decode(value, validate=True),
            )
            for name, value in case["form_deferred_scope_headers"]
        ]


def _make_message(spec: dict[str, Any]) -> dict[str, Any]:
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
                "bytes": _decode_base64(spec["bytes_base64"], "receive.bytes_base64"),
            }
        return {"type": spec["type"], "text": spec["text"]}
    return {
        "type": spec["type"],
        "body": _decode_base64(spec["body_base64"], "receive.body_base64"),
        "more_body": spec["more_body"],
    }


def _request_form_message(spec: dict[str, Any]) -> dict[str, Any]:
    if "body_segments" in spec:
        body_parts = []
        for segment in spec["body_segments"]:
            if segment["kind"] == "literal":
                body_parts.append(
                    _decode_base64(segment["bytes_base64"], "receive.body_segments.bytes_base64")
                )
            elif segment["kind"] == "repeat":
                pattern = _decode_base64(
                    segment["pattern_base64"], "receive.body_segments.pattern_base64"
                )
                body_parts.append(pattern * segment["count"])
            else:
                template = _decode_base64(
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
        return _make_message(spec)
    repeat = spec["body_repeat"]
    pattern = _decode_base64(repeat["pattern_base64"], "receive.body_repeat.pattern_base64")
    return {
        "type": spec["type"],
        "body": pattern * repeat["count"],
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
    if isinstance(kind, str):
        kind = str.__str__(kind)
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
    raise RuntimeError(f"unexpected ASGI event in the current slice: {kind!r}")


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
            "path_param": {"value": _json_safe(path_value), "type": type(path_value).__name__},
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
        state["worker_event_trace"].append("worker-entered")
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
            state["worker_event_trace"].append("worker-finalizer-ran")
            state["worker_completed"].set()
            state["worker_event_trace"].append("worker-completed")
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
            _exact_object(action, {"operation", "property"}, "callable-property action")
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
            _exact_object(
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
            _exact_object(
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
        entry = _exact_object(raw_entry, {"key", "handler"}, context)
        key_spec = entry["key"]
        if not isinstance(key_spec, dict) or not isinstance(key_spec.get("kind"), str):
            raise ValueError(f"{context}.key must be a tagged handler key")
        if key_spec["kind"] == "status-code":
            _exact_object(key_spec, {"kind", "status_code"}, f"{context}.key")
            key = key_spec["status_code"]
            if type(key) is not int and type(key) is not bool:
                raise ValueError(f"{context}.key.status_code must be an integer or boolean key")
        elif key_spec["kind"] == "builtins-class":
            _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
            key = getattr(builtins, key_spec["name"])
            if not isinstance(key, type):
                raise ValueError(f"{context}.key.name must identify a built-in class")
        elif key_spec["kind"] == "exception-class":
            if key_spec.get("name") == "HTTPException":
                _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = http_exception_type
            elif key_spec.get("name") == "WebSocketException":
                _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = websocket_exception_type
            elif key_spec.get("name") == "Exception":
                _exact_object(key_spec, {"kind", "name"}, f"{context}.key")
                key = Exception
            elif key_spec.get("name") == "ExceptionEqualSubclass":
                _exact_object(
                    key_spec,
                    {"kind", "name", "base_class", "metaclass_equality"},
                    f"{context}.key",
                )
                if (
                    key_spec["base_class"] != "Exception"
                    or key_spec["metaclass_equality"] != "Exception"
                ):
                    raise ValueError("ExceptionEqualSubclass input is unsupported")

                class ExceptionEqualityMeta(type):
                    def __eq__(cls, other: object) -> bool:
                        if other is Exception:
                            return True
                        return type.__eq__(cls, other) is True

                    def __hash__(cls) -> int:
                        return hash(Exception)

                key = ExceptionEqualityMeta("ExceptionEqualSubclass", (Exception,), {})
                exception_types["ExceptionEqualSubclass"] = key
            elif key_spec.get("name") == "BodyReuseException":
                _exact_object(key_spec, {"kind", "name", "base_class"}, f"{context}.key")
                if key_spec["base_class"] != "HTTPException":
                    raise ValueError("BodyReuseException must derive from HTTPException")
                key = type("BodyReuseException", (http_exception_type,), {})
                exception_types["BodyReuseException"] = key
            elif key_spec.get("name") == "CustomWSException":
                _exact_object(key_spec, {"kind", "name", "base_class"}, f"{context}.key")
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
            if spec.get("kind") == "record-sync-server-error-handler":
                _exact_object(
                    spec,
                    {"kind", "label"},
                    "sync server-error callback",
                )

                def record_server_error(_request: Any, _exc: Exception) -> None:
                    handler_calls.append(spec["label"])

                return record_server_error
            if spec.get("kind") == "websocket-close-handler":
                _exact_object(
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
            if spec.get("kind") == "websocket-exception-close-handler":
                _exact_object(
                    spec,
                    {"kind", "code"},
                    "WebSocketException close handler",
                )
                if type(spec["code"]) is not int or spec["code"] < 0:
                    raise ValueError("WebSocketException handler close code must be non-negative")

                async def websocket_exception_close_handler(
                    websocket: Any, _exc: Exception
                ) -> None:
                    await websocket.close(code=spec["code"])

                return websocket_exception_close_handler

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
                if spec["kind"] == "json-exception-detail-headers-response":
                    _exact_object(
                        spec,
                        {"kind"},
                        "JSON exception-detail and headers response handler",
                    )
                    return json_response_type(
                        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                    )
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


def _has_invalid_builtin_exception_handler_class(registry: Any) -> bool:
    if isinstance(registry, dict) and registry.get("kind") == "observable-mapping":
        registry = registry.get("entries")
    if not isinstance(registry, list):
        return False
    for entry in registry:
        key_spec = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(key_spec, dict) or key_spec.get("kind") != "builtins-class":
            continue
        exception_class = getattr(builtins, key_spec["name"])
        if isinstance(exception_class, type) and not issubclass(exception_class, Exception):
            return True
    return False


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
        def __init__(self, app: Any, name: str, *, value: str = "true") -> None:
            self.app = app
            self.response_header = (
                f"X-{name}".encode("ascii"),
                value.encode("ascii"),
            )

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
        if isinstance(raw_spec, dict) and raw_spec.get("kind") in {
            "append-response-header",
            "middleware-iterator-subclass",
        }:
            spec = _exact_object(
                raw_spec,
                {"kind", "name"}
                if raw_spec["kind"] == "append-response-header"
                else {"kind", "iterated"},
                f"application middleware[{index}]",
            )
        else:
            spec = _exact_object(raw_spec, {"kind"}, f"application middleware[{index}]")
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
        elif spec["kind"] == "middleware-iterator-subclass":
            iterated = _exact_object(
                spec["iterated"],
                {"kind", "name", "value"},
                f"application middleware[{index}].iterated",
            )
            if iterated["kind"] != "append-response-header":
                raise ValueError(
                    "middleware iterator subclass must yield a declared middleware factory"
                )
            middleware.append(
                middleware_with_iterator_override(
                    Middleware,
                    CopyScopeMiddleware,
                    AppendResponseHeaderMiddleware,
                    [iterated["name"]],
                    MappingProxyType({"value": iterated["value"]}),
                )
            )
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
    application_subclass: dict[str, Any] | None = None,
) -> tuple[Any, list[Any], list[dict[str, Any]], Any, list[dict[str, Any]]]:
    from starlette.applications import Starlette
    from starlette.background import BackgroundTask
    from starlette.exceptions import HTTPException, WebSocketException
    from starlette.responses import (
        JSONResponse,
        PlainTextResponse,
        RedirectResponse,
        Response,
        StreamingResponse,
    )
    from starlette.routing import Mount, Route, Router, WebSocketRoute

    application_type = Starlette
    captured_application: dict[str, Any] = {}
    if application_subclass is not None:
        from scripts.parity.adapters.application_subclass import materialize_starlette_subclass

        application_type = materialize_starlette_subclass(
            Starlette,
            application_subclass,
            captured_application,
        )

    required_arguments = {
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
    }
    if frozenset(app_spec) not in {
        frozenset(required_arguments),
        frozenset(required_arguments | {"max_body_size"}),
    }:
        raise ValueError("Starlette.__init__ arguments do not match the declared workflow")
    lifecycle_trace: list[Any] = []
    captured_application["attribute_trace"] = lifecycle_trace
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
        and lifespan_spec.get("kind") == "async-context-manager-observe-exception-class"
    ):

        class ExceptionObservingContextManager:
            async def __aenter__(self) -> None:
                lifecycle_trace.append("entry")
                return None

            async def __aexit__(self, exception_type: Any, exception: Any, _traceback: Any) -> bool:
                if exception is None:
                    observation = {
                        "exit_type_is_runtime_type": None,
                        "runtime_type_name": None,
                        "reported_class_name": None,
                    }
                else:
                    observation = {
                        "exit_type_is_runtime_type": exception_type is type(exception),
                        "runtime_type_name": type(exception).__name__,
                        "reported_class_name": exception.__class__.__name__,
                    }
                lifecycle_trace.append(observation)
                if lifespan_spec["record_exit"]:
                    lifecycle_trace.append("exit")
                return False

        context_manager = ExceptionObservingContextManager()

        def lifespan(_app: Any) -> Any:
            return context_manager
    elif (
        isinstance(lifespan_spec, dict)
        and lifespan_spec.get("kind") == "async-context-manager-special-method-descriptor"
    ):
        descriptor = lifespan_spec["descriptor"]
        if descriptor == "classmethod":

            class ClassMethodContextManager:
                @classmethod
                async def __aenter__(cls) -> None:
                    lifecycle_trace.append(
                        {"event": "enter", "descriptor": "classmethod", "owner": cls.__name__}
                    )
                    return None

                @classmethod
                async def __aexit__(
                    cls, exception_type: Any, _exception: Any, _traceback: Any
                ) -> bool:
                    lifecycle_trace.append(
                        {
                            "event": "exit",
                            "descriptor": "classmethod",
                            "owner": cls.__name__,
                            "exception_type": (
                                None if exception_type is None else exception_type.__name__
                            ),
                        }
                    )
                    return False

            context_manager = ClassMethodContextManager()
        elif descriptor == "staticmethod":

            class StaticMethodContextManager:
                @staticmethod
                async def __aenter__() -> None:
                    lifecycle_trace.append({"event": "enter", "descriptor": "staticmethod"})
                    return None

                @staticmethod
                async def __aexit__(exception_type: Any, _exception: Any, _traceback: Any) -> bool:
                    lifecycle_trace.append(
                        {
                            "event": "exit",
                            "descriptor": "staticmethod",
                            "exception_type": (
                                None if exception_type is None else exception_type.__name__
                            ),
                        }
                    )
                    return False

            context_manager = StaticMethodContextManager()
        else:
            raise ValueError("async context-manager descriptor is unsupported")

        def lifespan(_app: Any) -> Any:
            return context_manager
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
        raise ValueError("lifespan input must be null or use a declared context-manager marker")

    routes = []
    request_observations: list[dict[str, Any]] = []
    sync_endpoint_states: list[dict[str, Any]] = []
    handler_calls: list[str] = []
    route_endpoint: Any = None
    exception_handler_spec = app_spec["exception_handlers"]
    if (
        isinstance(exception_handler_spec, dict)
        and exception_handler_spec.get("kind") == "observable-mapping"
    ):
        _exact_object(
            exception_handler_spec,
            {"kind", "event", "entries"},
            "observable application exception-handler Mapping",
        )
        if (
            not isinstance(exception_handler_spec["event"], str)
            or not exception_handler_spec["event"]
            or not isinstance(exception_handler_spec["entries"], list)
        ):
            raise ValueError("observable exception-handler Mapping input is malformed")
        exception_handler_values, exception_types = _materialize_exception_handlers(
            exception_handler_spec["entries"],
            JSONResponse,
            PlainTextResponse,
            HTTPException,
            WebSocketException,
            handler_calls,
        )
        exception_handlers = ObservableMapping(
            exception_handler_values, lifecycle_trace, exception_handler_spec["event"]
        )
    else:
        exception_handlers, exception_types = _materialize_exception_handlers(
            exception_handler_spec,
            JSONResponse,
            PlainTextResponse,
            HTTPException,
            WebSocketException,
            handler_calls,
        )

    middleware_spec = app_spec["middleware"]
    if isinstance(middleware_spec, dict) and middleware_spec.get("kind") == "observable-sequence":
        _exact_object(
            middleware_spec,
            {"kind", "event", "items"},
            "observable application middleware Sequence",
        )
        if (
            not isinstance(middleware_spec["event"], str)
            or not middleware_spec["event"]
            or not isinstance(middleware_spec["items"], list)
        ):
            raise ValueError("observable application middleware Sequence input is malformed")
        application_state_observer = None
        if (
            application_subclass is not None
            and application_subclass["kind"] == "capture-instance-during-construction"
        ):

            def application_state_observer() -> dict[str, dict[str, Any]]:
                try:
                    application = captured_application["application"]
                except KeyError as exc:
                    raise ValueError("Starlette subclass did not capture its instance") from exc
                return snapshot_application_attributes(
                    application,
                    application_subclass["observe_attributes"],
                )

        middleware_input = ObservableSequence(
            _materialize_application_middleware(middleware_spec["items"]),
            lifecycle_trace,
            middleware_spec["event"],
            application_state_observer,
        )
    else:
        middleware_input = _materialize_application_middleware(middleware_spec)

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
            if kind == "router":
                middleware = _build_reverse_route_middleware(route_spec.get("middleware", []))
                if route_spec.get("middleware_sequence_truthy") is False:
                    middleware = _InputFalseyMiddlewareSequence(middleware)
                return Router(
                    routes=[make_middleware_route(child) for child in route_spec["routes"]],
                    middleware=middleware,
                    max_body_size=route_spec.get("max_body_size"),
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

                elif endpoint_spec["kind"] == "request-body-echo":

                    async def endpoint(request: Any) -> Any:
                        return Response(await request.body())

                else:
                    raise ValueError("route-middleware endpoint uses an unsupported input kind")
                middleware = _build_reverse_route_middleware(route_spec.get("middleware", []))
                return Route(
                    route_spec["path"],
                    endpoint=endpoint,
                    methods=route_spec["methods"],
                    name=route_spec.get("name"),
                    middleware=middleware,
                    max_body_size=route_spec.get("max_body_size"),
                )
            if kind != "mount":
                raise ValueError("route-middleware node must be an HTTP route, Router, or Mount")
            middleware = _build_reverse_route_middleware(route_spec.get("middleware", []))
            if "app" in route_spec:
                return Mount(
                    route_spec["path"],
                    app=make_middleware_route(route_spec["app"]),
                    middleware=middleware,
                    max_body_size=route_spec.get("max_body_size"),
                )
            return Mount(
                route_spec["path"],
                routes=[make_middleware_route(child) for child in route_spec["routes"]],
                middleware=middleware,
                max_body_size=route_spec.get("max_body_size"),
            )

        route_objects = [make_middleware_route(route) for route in app_spec["routes"]]
        application_arguments = {
            "debug": app_spec["debug"],
            "routes": route_objects,
            "middleware": middleware_input,
            "exception_handlers": exception_handlers,
            "lifespan": lifespan,
        }
        if "max_body_size" in app_spec:
            application_arguments["max_body_size"] = app_spec["max_body_size"]
        app = application_type(**application_arguments)
        return app, lifecycle_trace, request_observations, route_endpoint, sync_endpoint_states

    for route_spec in app_spec["routes"]:
        if isinstance(route_spec, dict) and route_spec.get("kind") == "websocket-route":
            _exact_object(
                route_spec,
                {"kind", "path", "endpoint"},
                "WebSocket route input",
            )
            endpoint_spec = route_spec["endpoint"]
            if not isinstance(endpoint_spec, dict) or not isinstance(
                endpoint_spec.get("kind"), str
            ):
                raise ValueError("WebSocket endpoint input must be a declared endpoint record")
            if endpoint_spec["kind"] == "http-exception":
                _exact_object(
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
                _exact_object(
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
                _exact_object(
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
            routes.append(WebSocketRoute(route_spec["path"], websocket_endpoint))
            continue
        if (
            frozenset(route_spec)
            not in {
                frozenset({"kind", "path", "methods", "endpoint"}),
                frozenset({"kind", "path", "methods", "endpoint", "max_body_size"}),
            }
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
        elif response_spec["kind"] == "json-response":
            _exact_object(
                response_spec,
                {"kind", "content", "status_code"},
                "JSONResponse endpoint",
            )

            def make_json_endpoint(spec: dict[str, Any]) -> Any:
                async def endpoint(_request: Any) -> Any:
                    return JSONResponse(spec["content"], status_code=spec["status_code"])

                return endpoint

            route_endpoint = make_json_endpoint(response_spec)
        elif response_spec["kind"] == "streaming-response":
            _exact_object(
                response_spec,
                {"kind", "content", "streaming", "status_code", "header_pairs", "media_type"},
                "StreamingResponse endpoint",
            )
            content_spec = response_spec["content"]
            if not isinstance(content_spec, dict) or not isinstance(content_spec.get("kind"), str):
                raise ValueError("StreamingResponse endpoint content must declare its source")
            request_stream = content_spec["kind"] == "request-stream"
            if request_stream:
                _exact_object(content_spec, {"kind"}, "StreamingResponse request-stream content")
            else:
                content_spec = _exact_object(
                    content_spec,
                    {"kind", "value"},
                    "StreamingResponse endpoint content",
                )
                if content_spec["kind"] != "chunks" or not isinstance(content_spec["value"], list):
                    raise ValueError("StreamingResponse endpoint content must contain chunks")
            if response_spec["streaming"] != "async-generator":
                raise ValueError("StreamingResponse endpoint must use an async generator")
            if type(response_spec["status_code"]) is not int:
                raise ValueError("StreamingResponse endpoint status code must be an integer")
            if response_spec["media_type"] is not None and not isinstance(
                response_spec["media_type"], str
            ):
                raise ValueError("StreamingResponse endpoint media type must be text or null")
            if not isinstance(response_spec["header_pairs"], list):
                raise ValueError("StreamingResponse endpoint headers must be a list")

            chunks = []
            for index, chunk_spec in enumerate([] if request_stream else content_spec["value"]):
                chunk_spec = _exact_object(
                    chunk_spec,
                    {"kind", "value"},
                    f"StreamingResponse endpoint chunk[{index}]",
                )
                if chunk_spec["kind"] == "text":
                    if not isinstance(chunk_spec["value"], str):
                        raise ValueError("StreamingResponse endpoint text chunks must be strings")
                    chunks.append(chunk_spec["value"])
                elif chunk_spec["kind"] == "base64-bytes":
                    if not isinstance(chunk_spec["value"], str):
                        raise ValueError(
                            "StreamingResponse endpoint byte chunks must be base64 text"
                        )
                    chunks.append(
                        _decode_base64(
                            chunk_spec["value"],
                            f"StreamingResponse endpoint content[{index}].value",
                        )
                    )
                elif chunk_spec["kind"] == "memoryview-base64":
                    if not isinstance(chunk_spec["value"], str):
                        raise ValueError(
                            "StreamingResponse endpoint memoryview chunks must be base64 text"
                        )
                    chunks.append(
                        memoryview(
                            _decode_base64(
                                chunk_spec["value"],
                                f"StreamingResponse endpoint content[{index}].value",
                            )
                        )
                    )
                else:
                    raise ValueError(
                        "StreamingResponse endpoint chunks must be text, bytes, or memoryview"
                    )

            header_pairs = response_spec["header_pairs"]
            if any(
                not isinstance(pair, list)
                or len(pair) != 2
                or any(not isinstance(value, str) for value in pair)
                for pair in header_pairs
            ):
                raise ValueError("StreamingResponse endpoint headers must be string pairs")

            def make_streaming_endpoint(
                spec: dict[str, Any], values: list[Any], relay_request_stream: bool
            ) -> Any:
                async def response_body() -> Any:
                    for chunk in values:
                        yield chunk

                async def endpoint(request: Any) -> Any:
                    body_iterator = request.stream() if relay_request_stream else response_body()
                    return StreamingResponse(
                        body_iterator,
                        status_code=spec["status_code"],
                        headers=dict(spec["header_pairs"]),
                        media_type=spec["media_type"],
                    )

                return endpoint

            route_endpoint = make_streaming_endpoint(response_spec, chunks, request_stream)
        elif response_spec["kind"] == "response-background-task-error":
            _exact_object(
                response_spec,
                {"kind", "status_code", "exception_class", "message"},
                "response background-task error endpoint",
            )

            def make_background_task_error_endpoint(spec: dict[str, Any]) -> Any:
                exception_type = getattr(builtins, spec["exception_class"])

                def fail_background_task() -> None:
                    raise exception_type(spec["message"])

                background_task = BackgroundTask(fail_background_task)

                async def endpoint(_request: Any) -> Any:
                    return Response(status_code=spec["status_code"], background=background_task)

                return endpoint

            route_endpoint = make_background_task_error_endpoint(response_spec)
        elif response_spec["kind"] == "sync-plain-text-response":
            _exact_object(
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
            _exact_object(response_spec, {"kind"}, "request-body echo endpoint")

            async def route_endpoint(request: Any) -> Any:
                return Response(await request.body())
        elif response_spec["kind"] == "request-form-consumer":
            _exact_object(
                response_spec,
                {"kind", "response_content"},
                "request form-consuming endpoint",
            )
            response_content = response_spec["response_content"]

            async def route_endpoint(request: Any, content: str = response_content) -> Any:
                async with request.form():
                    return PlainTextResponse(content)
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
        elif response_spec["kind"] == "authentication-user-interface":
            _exact_object(
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
            _exact_object(
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
            _exact_object(
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
            required_fields = {"kind", "probe", "response_content", "status_code", "media_type"}
            if set(response_spec) != required_fields:
                raise ValueError(
                    "request cookies observer input does not match its declared schema"
                )
            probe = response_spec["probe"]
            if not isinstance(probe, dict) or not isinstance(probe.get("kind"), str):
                raise ValueError("request cookies observer probe must be an object with a kind")
            if probe["kind"] == "items":
                if set(probe) != {"kind"}:
                    raise ValueError(
                        "request cookies items probe does not match its declared schema"
                    )
            elif probe["kind"] == "mapping-actions":
                if set(probe) != {"kind", "actions"} or not isinstance(probe["actions"], list):
                    raise ValueError(
                        "request cookies mapping probe does not match its declared schema"
                    )
                for action in probe["actions"]:
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
                    if set(action) != action_fields or not isinstance(action.get("key"), str):
                        raise ValueError(
                            "request cookies mapping action does not match its declared schema"
                        )
                    if action["operation"] == "set" and not isinstance(action.get("value"), str):
                        raise ValueError("request cookies mapping set value must be a string")
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
            if set(response_spec) != callable_fields:
                raise ValueError("async request callable observer input does not match its schema")
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
            elif callable_kind == "marked_function":

                def make_marked_async_function_endpoint(
                    spec: dict[str, Any], state: dict[str, Any]
                ) -> Any:
                    def endpoint(request: Any) -> Any:
                        return _async_request_callable_observer_response(request, spec, state)

                    return inspect.markcoroutinefunction(endpoint)

                route_endpoint = make_marked_async_function_endpoint(
                    response_spec, async_callable_state
                )
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
            required_fields = {"kind", "state_key", "state_value", "response_content"}
            if set(response_spec) != required_fields:
                raise ValueError("request state observer input does not match its declared schema")

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
            required_fields = {"kind", "status_code", "detail", "headers"}
            if set(response_spec) != required_fields:
                raise ValueError("HTTP exception input does not match its declared schema")
            if type(response_spec["status_code"]) is not int:
                raise ValueError("HTTP exception status_code must be an integer")
            headers = response_spec["headers"]
            if not isinstance(headers, list) or any(
                not isinstance(pair, list) or len(pair) != 2 for pair in headers
            ):
                raise ValueError("HTTP exception headers must be input-defined pairs")

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
            if "error_message" in response_spec:
                required_fields.add("error_message")
            if set(response_spec) != required_fields:
                raise ValueError("sync request observer input does not match its declared schema")
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
            required_fields = {"kind", "response_content"}
            if set(response_spec) != required_fields:
                raise ValueError(
                    "sync request cancellation observer input does not match its declared schema"
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
                # Keep event-loop and worker-thread order separate; their
                # unsynchronized cross-thread interleaving is not a contract.
                "request_event_trace": [],
                "worker_event_trace": [],
            }
            sync_endpoint_states.append(sync_state)

            def make_cancellation_endpoint(spec: dict[str, Any], state: dict[str, Any]) -> Any:
                def endpoint(request: Any) -> Any:
                    return _sync_request_cancellation_response(request, spec, state)

                return endpoint

            route_endpoint = make_cancellation_endpoint(response_spec, sync_state)
            route_endpoint._parity_sync_cancellation_state = sync_state
        elif response_spec["kind"] == "sync-request-runtime-observer":
            _exact_object(
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
            required_fields = {"kind", "response_content"}
            if set(response_spec) != required_fields:
                raise ValueError(
                    "ASGI callable-instance observer input does not match its declared schema"
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
            _exact_object(
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
            _exact_object(
                response_spec,
                {"kind", "actions"},
                "ASGI callable action-sequence endpoint",
            )
            if not isinstance(response_spec["actions"], list) or not response_spec["actions"]:
                raise ValueError("ASGI callable action sequence must be a non-empty array")

            class ASGICallableActionSequence:
                def __init__(
                    self,
                    actions: list[dict[str, Any]],
                    observations: list[dict[str, Any]],
                    registered_exception_types: dict[str, Any],
                ) -> None:
                    self.actions = actions
                    self.observations = observations
                    self.registered_exception_types = registered_exception_types

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
                        if action.get("action") == "register-status-handler-from-exception-class":
                            _exact_object(
                                action,
                                {"action", "status_code", "exception_class"},
                                f"ASGI action[{index}]",
                            )
                            if type(action["status_code"]) is not int or not isinstance(
                                action["exception_class"], str
                            ):
                                raise ValueError("dynamic status handler registration is invalid")
                            exception_handlers, _ = scope["starlette.exception_handlers"]
                            exception_class = self.registered_exception_types[
                                action["exception_class"]
                            ]
                            exception_middleware = scope["app"].middleware_stack.app
                            exception_middleware.add_exception_handler(
                                action["status_code"], exception_handlers[exception_class]
                            )
                            continue
                        action_kind, value = _materialize_asgi_action(action, index)
                        if action_kind == "send":
                            await send(value)
                        else:
                            raise value

            route_endpoint = ASGICallableActionSequence(
                response_spec["actions"], request_observations, exception_types
            )
        elif response_spec["kind"] == "http-class-based-endpoint":
            _exact_object(
                response_spec,
                {"kind", "name", "handlers"},
                "HTTPEndpoint application endpoint",
            )
            from starlette.endpoints import HTTPEndpoint

            class_attributes: dict[str, Any] = {"__module__": __name__}
            for handler_spec in response_spec["handlers"]:
                _exact_object(
                    handler_spec,
                    {"name", "call_style", "response"},
                    "HTTPEndpoint method handler",
                )
                method_response = _exact_object(
                    handler_spec["response"],
                    {"kind", "content", "status_code", "media_type"},
                    "HTTPEndpoint method response",
                )
                if method_response["kind"] != "plain-text-response":
                    raise ValueError("HTTPEndpoint method response must be plain text")

                def make_endpoint_method(spec: dict[str, Any], call_style: str) -> Any:
                    if call_style == "sync":

                        def endpoint_method(_self: Any, _request: Any) -> Any:
                            return PlainTextResponse(
                                content=spec["content"],
                                status_code=spec["status_code"],
                                media_type=spec["media_type"],
                            )

                        return endpoint_method

                    async def endpoint_method(_self: Any, _request: Any) -> Any:
                        return PlainTextResponse(
                            content=spec["content"],
                            status_code=spec["status_code"],
                            media_type=spec["media_type"],
                        )

                    return endpoint_method

                class_attributes[handler_spec["name"]] = make_endpoint_method(
                    method_response, handler_spec["call_style"]
                )
            route_endpoint = type(response_spec["name"], (HTTPEndpoint,), class_attributes)
        else:
            raise ValueError(f"unsupported endpoint kind: {response_spec['kind']!r}")
        routes.append(
            Route(
                route_spec["path"],
                route_endpoint,
                methods=route_spec["methods"],
                max_body_size=route_spec.get("max_body_size"),
            )
        )

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        application_arguments = {
            "debug": app_spec["debug"],
            "routes": routes,
            "middleware": middleware_input,
            "exception_handlers": exception_handlers,
            "lifespan": lifespan,
        }
        if "max_body_size" in app_spec:
            application_arguments["max_body_size"] = app_spec["max_body_size"]
        app = application_type(**application_arguments)
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
    step_arguments: dict[str, Any],
    lifecycle_trace: list[str],
    request_observations: list[dict[str, Any]],
    route_endpoint: Any,
    request_dispatch: bool,
    workflow_events: list[dict[str, Any]] | None = None,
    sync_endpoint_states: list[dict[str, Any]] | None = None,
    capture_dispatch_error: bool = False,
    capture_dispatch_error_as_observation: bool = False,
    cancel_after_endpoint_entry: bool = False,
    cancellation_checkpoint: bool = False,
    release_worker_after_cancel: bool = False,
    allow_missing_response_start: bool = False,
    scope_container: str | dict[str, Any] = "dict",
    scope_observation: dict[str, Any] | None = None,
) -> dict[str, Any] | _CapturedDispatchError:
    scope = _make_scope(step_arguments["scope"], scope_container)
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

    send_cancellation_spec = None
    send_oserror_spec = None
    if step_arguments["send"] != {"kind": "capture-asgi-send"}:
        send_kind = (
            step_arguments["send"].get("kind") if isinstance(step_arguments["send"], dict) else None
        )
        if send_kind == "capture-asgi-send-until-oserror" and capture_dispatch_error_as_observation:
            send_oserror_spec = _exact_object(
                step_arguments["send"],
                {"kind", "event_index", "message"},
                "CORS failing send callback",
            )
            if (
                type(send_oserror_spec["event_index"]) is not int
                or send_oserror_spec["event_index"] < 0
                or not isinstance(send_oserror_spec["message"], str)
            ):
                raise ValueError("CORS failing send callback input is invalid")
        else:
            send_cancellation_spec = _exact_object(
                step_arguments["send"],
                {"kind", "event_index"},
                "Starlette caller-cancelled send",
            )
            if (
                send_cancellation_spec["kind"] != "capture-asgi-send-with-caller-cancellation"
                or type(send_cancellation_spec["event_index"]) is not int
                or send_cancellation_spec["event_index"] != 1
            ):
                raise ValueError("Starlette caller-cancelled send input is invalid")

    send_index = 0
    send_gate_entered = asyncio.Event() if send_cancellation_spec is not None else None
    send_gate_release = asyncio.Event() if send_cancellation_spec is not None else None
    send_execution_trace: list[dict[str, Any]] | None = (
        [] if send_cancellation_spec is not None else None
    )

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index
        if send_oserror_spec is not None and send_index == send_oserror_spec["event_index"]:
            raise OSError(send_oserror_spec["message"])
        if (
            send_cancellation_spec is not None
            and send_index == send_cancellation_spec["event_index"]
        ):
            if (
                send_gate_entered is None
                or send_gate_release is None
                or send_execution_trace is None
            ):
                raise RuntimeError("Starlette caller-cancellation gate is unavailable")
            send_execution_trace.append(
                {
                    "event": "asgi-send-enter",
                    "event_index": send_index,
                    "message": _canonical_message(message),
                }
            )
            send_gate_entered.set()
            await send_gate_release.wait()
        sent.append(message)
        if workflow_events is not None:
            workflow_events.append(_canonical_message(message))
        if send_execution_trace is not None:
            send_execution_trace.append(
                {"event": "asgi-send", "message": _canonical_message(message)}
            )
            if (
                send_cancellation_spec is not None
                and send_index == send_cancellation_spec["event_index"]
            ):
                send_execution_trace.append(
                    {"event": "asgi-send-complete", "event_index": send_index}
                )
        send_index += 1

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
                        state["request_event_trace"].append("request-cancel-requested")
                    if cancellation_checkpoint:
                        await asyncio.sleep(0)
                    request_task_done_before_worker_release = server_task.done()
                    if release_worker_after_cancel:
                        with state["lock"]:
                            state["request_event_trace"].append("worker-released")
                        state["worker_release"].set()
                    try:
                        await asyncio.wait_for(server_task, timeout=15)
                    except asyncio.CancelledError as exc:
                        captured_exception = exc
                        with state["lock"]:
                            state["request_event_trace"].append("request-task-cancelled")
                    except Exception as exc:
                        if not capture_dispatch_error:
                            raise
                        captured_exception = exc
                        with state["lock"]:
                            state["request_event_trace"].append("request-task-raised")
                    else:
                        with state["lock"]:
                            state["request_event_trace"].append("request-task-completed")
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
                        "request_event_trace": list(state["request_event_trace"]),
                        "worker_event_trace": list(state["worker_event_trace"]),
                    }
            else:
                raise RuntimeError("cancellation schedule requires a declared endpoint observer")
        elif send_cancellation_spec is not None:
            if (
                send_gate_entered is None
                or send_gate_release is None
                or send_execution_trace is None
            ):
                raise RuntimeError("Starlette caller-cancellation gate events are unavailable")
            server_task = asyncio.create_task(app(scope, receive, send))
            try:
                await asyncio.wait_for(send_gate_entered.wait(), timeout=5.0)
                send_execution_trace.append({"event": "response-cancellation-requested"})
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError as exc:
                    captured_exception = exc
                except Exception as exc:
                    captured_exception = exc
            finally:
                if not server_task.done():
                    server_task.cancel()
                    send_gate_release.set()
                    try:
                        await server_task
                    except BaseException:
                        pass
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

    scope_observation_result = (
        _scope_observation(scope, scope_observation) if scope_observation is not None else None
    )

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
        and not allow_missing_response_start
        and not (captured_exception is not None and capture_dispatch_error_as_observation)
    ):
        raise RuntimeError("target completed without an http.response.start event")
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
        result = {
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
            "scope_mapping_observation": {
                "type": f"{type(scope).__module__}.{type(scope).__qualname__}",
                "app_is_application": scope.get("app") is app,
                "router_is_application_router": scope.get("router") is app.router,
                "marker": _json_safe(scope.get("path")),
            },
            "response_status": result["response_status"],
            "ordered_repeated_headers": result["ordered_repeated_headers"],
            "asgi_event_order": result["asgi_event_order"],
            "asgi_events": result["asgi_events"],
        }
        if scope_observation_result is not None:
            result["scope_observation"] = scope_observation_result
        if captured_exception is not None:
            return _CapturedDispatchError(
                error=_dispatch_error(captured_exception),
                partial_value=result,
            )
        return result
    result["deprecation_warnings"] = list(getattr(app, "_parity_lifespan_warnings", []))
    result["sync_endpoint_observations"] = _observed_sync_endpoint(sync_endpoint_states or [])
    if scope_observation_result is not None:
        result["scope_observation"] = scope_observation_result
    if captured_exception is not None and (
        capture_dispatch_error_as_observation or send_cancellation_spec is not None
    ):
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
        arguments = _exact_object(step["arguments"], expected, f"{context} arguments")
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
        descriptor = _exact_object(descriptor, {"kind", "value"}, f"{context}.{name}")
        if descriptor["kind"] != "literal":
            raise ValueError(f"{context}.{name} must be an input literal")
        values[name] = descriptor["value"]
    return values


def _materialize_gzip_middleware(arguments: dict[str, Any], *, responder: bool = False) -> Any:
    from starlette.middleware.gzip import GZipMiddleware, GZipResponder

    app_spec = _exact_object(arguments["app"], {"kind", "messages"}, "GZipMiddleware app")
    if app_spec["kind"] != "asgi-response-sequence" or not isinstance(app_spec["messages"], list):
        raise ValueError("GZipMiddleware app must be an input-defined response sequence")
    response_messages = app_spec["messages"]

    async def response_app(_scope: Any, _receive: Any, send: Any) -> None:
        for index, spec in enumerate(response_messages):
            if not isinstance(spec, dict):
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            raw_message_type = spec.get("type")
            if isinstance(raw_message_type, str):
                message_type = raw_message_type
            elif isinstance(raw_message_type, dict) and "str_subclass" in raw_message_type:
                descriptor = _exact_object(raw_message_type, {"str_subclass"}, "ASGI message type")
                subclass_spec = _exact_object(
                    descriptor["str_subclass"],
                    {"value", "equal_result"},
                    "ASGI message type str_subclass",
                )
                if (
                    not isinstance(subclass_spec["value"], str)
                    or type(subclass_spec["equal_result"]) is not bool
                ):
                    raise ValueError("ASGI message type str_subclass has invalid fields")
                message_type = _InputStringSubclass(
                    subclass_spec["value"], equal_result=subclass_spec["equal_result"]
                )
            else:
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            message_kind = str.__str__(message_type)
            if message_kind == "http.response.start":
                start_keys = {"type", "status", "headers_base64_pairs"}
                if "message_mapping" in spec:
                    start_keys.add("message_mapping")
                _exact_object(
                    spec,
                    start_keys,
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
            elif message_kind == "http.response.body":
                body_keys = {"type", "body_base64", "more_body"}
                if "message_mapping" in spec:
                    body_keys.add("message_mapping")
                _exact_object(
                    spec,
                    body_keys,
                    f"inner response message[{index}]",
                )
                message = {
                    "type": message_type,
                    "body": _decode_base64(spec["body_base64"], "inner response body"),
                    "more_body": spec["more_body"],
                }
            elif message_kind == "http.response.pathsend":
                _exact_object(
                    spec,
                    {"type", "path"},
                    f"inner response message[{index}]",
                )
                message = {"type": message_type, "path": spec["path"]}
            else:
                raise ValueError(f"unsupported inner response event: {message_kind!r}")
            message_mapping = spec.get("message_mapping", "dict")
            if not isinstance(message_mapping, str) or message_mapping not in {"dict", "user-dict"}:
                raise ValueError("GZipMiddleware response message mapping is unsupported")
            if message_mapping == "user-dict":
                message = UserDict(message)
            await send(message)

    constructor_arguments: dict[str, Any] = {
        name: arguments[name]
        for name in ("minimum_size", "compresslevel", "thread_minimum_size")
        if name in arguments
    }
    if "exclude_content_types" in arguments:
        constructor_arguments["exclude_content_types"] = tuple(arguments["exclude_content_types"])

    middleware_type = GZipResponder if responder else GZipMiddleware
    return middleware_type(response_app, **constructor_arguments)


def _materialize_asgi_sequence_app(
    app_spec: dict[str, Any],
    *,
    callback_trace: list[dict[str, Any]] | None = None,
) -> Any:
    if not isinstance(app_spec, dict) or not isinstance(app_spec.get("kind"), str):
        raise ValueError("ASGI app must select an input-defined callback")
    app_kind = app_spec["kind"]
    finalizer_marker = None
    if app_kind == "asgi-callback-failure":
        app_spec = _exact_object(
            app_spec,
            {"kind", "exception_class", "message", "finally_marker"},
            "ASGI callback failure app",
        )
        if callback_trace is None:
            raise ValueError("ASGI callback failure app requires its CORS trace")
        exception_class = getattr(builtins, app_spec["exception_class"], None)
        if (
            exception_class not in {StopAsyncIteration, OSError, RuntimeError}
            or not isinstance(app_spec["message"], str)
            or not isinstance(app_spec["finally_marker"], str)
        ):
            raise ValueError("ASGI callback failure app input is invalid")

        async def failing_app(_scope: Any, _receive: Any, _send: Any) -> None:
            try:
                raise exception_class(app_spec["message"])
            finally:
                callback_trace.append(
                    {"event": "app-finally", "marker": app_spec["finally_marker"]}
                )

        return failing_app
    if app_kind == "asgi-response-sequence-with-finally":
        app_spec = _exact_object(
            app_spec,
            {"kind", "messages", "finally_marker"},
            "ASGI response sequence finalizer",
        )
        if callback_trace is None or not isinstance(app_spec["finally_marker"], str):
            raise ValueError("ASGI response sequence finalizer input is invalid")
        finalizer_marker = app_spec["finally_marker"]
    else:
        app_spec = _exact_object(app_spec, {"kind", "messages"}, "ASGI sequence app")
    if app_kind not in {
        "asgi-response-sequence",
        "asgi-response-sequence-with-finally",
    } or not isinstance(app_spec["messages"], list):
        raise ValueError("ASGI app must be an input-defined message sequence")
    response_messages = app_spec["messages"]

    async def send_response_sequence(_scope: Any, receive: Any, send: Any) -> None:
        for index, spec in enumerate(response_messages):
            if not isinstance(spec, dict):
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            raw_message_type = spec.get("type")
            if isinstance(raw_message_type, str):
                message_type = raw_message_type
            elif isinstance(raw_message_type, dict) and "str_subclass" in raw_message_type:
                descriptor = _exact_object(raw_message_type, {"str_subclass"}, "ASGI message type")
                subclass_spec = _exact_object(
                    descriptor["str_subclass"],
                    {"value", "equal_result"},
                    "ASGI message type str_subclass",
                )
                equal_result = subclass_spec["equal_result"]
                if not isinstance(subclass_spec["value"], str) or type(equal_result) is not bool:
                    raise ValueError("ASGI message type str_subclass has invalid fields")
                message_type = _InputStringSubclass(
                    subclass_spec["value"], equal_result=equal_result
                )
            else:
                raise ValueError(f"inner response message[{index}] must declare its ASGI type")
            message_kind = str.__str__(message_type)
            if message_kind == "http.response.start":
                start_keys = {"type", "status", "headers_base64_pairs"}
                if "headers_representation" in spec:
                    start_keys.add("headers_representation")
                if "message_mapping" in spec:
                    start_keys.add("message_mapping")
                _exact_object(
                    spec,
                    start_keys,
                    f"inner response message[{index}]",
                )
                response_headers = [
                    (
                        _decode_base64(name, "inner response header name"),
                        _decode_base64(value, "inner response header value"),
                    )
                    for name, value in spec["headers_base64_pairs"]
                ]
                if spec.get("headers_representation", "list") == "tuple":
                    response_headers = tuple(response_headers)
                message = {
                    "type": message_type,
                    "status": spec["status"],
                    "headers": response_headers,
                }
            elif message_kind == "http.response.body":
                expected_body_keys = {"type", "body_base64"}
                if "more_body" in spec:
                    expected_body_keys.add("more_body")
                if "message_mapping" in spec:
                    expected_body_keys.add("message_mapping")
                _exact_object(spec, expected_body_keys, f"inner response message[{index}]")
                message = {
                    "type": message_type,
                    "body": _decode_base64(spec["body_base64"], "inner response body"),
                }
                if "more_body" in spec:
                    message["more_body"] = spec["more_body"]
            elif message_kind == "http.response.pathsend":
                _exact_object(spec, {"type", "path"}, f"inner response message[{index}]")
                message = {"type": message_type, "path": spec["path"]}
            elif message_kind == "websocket.close":
                _exact_object(spec, {"type", "code"}, f"inner response message[{index}]")
                message = {"type": message_type, "code": spec["code"]}
            elif message_kind in {
                "lifespan.startup.complete",
                "lifespan.shutdown.complete",
            }:
                _exact_object(spec, {"type"}, f"inner response message[{index}]")
                message = {"type": message_type}
            else:
                raise ValueError(f"unsupported inner response event: {message_type!r}")
            message_mapping = spec.get("message_mapping", "dict")
            if not isinstance(message_mapping, str) or message_mapping not in {"dict", "user-dict"}:
                raise ValueError("inner response message mapping is unsupported")
            if message_mapping == "user-dict":
                message = UserDict(message)
            if message_kind.startswith("lifespan."):
                await receive()
            await send(message)

    if finalizer_marker is None:
        return send_response_sequence

    async def response_app(scope: Any, receive: Any, send: Any) -> None:
        try:
            await send_response_sequence(scope, receive, send)
        finally:
            if callback_trace is not None:
                callback_trace.append({"event": "app-finally", "marker": finalizer_marker})

    return response_app


def _materialize_protocol_middleware(
    surface: str,
    arguments: dict[str, Any],
    downstream_call_trace: list[dict[str, Any]] | None = None,
) -> Any:
    app = _materialize_asgi_sequence_app(
        arguments["app"],
        callback_trace=downstream_call_trace if surface == CORS_SURFACE else None,
    )
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
    if spec["kind"] in {
        "asgi-response-sequence",
        "asgi-response-sequence-then-raise",
        "asgi-response-sequence-then-http-exception",
    }:
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
            if spec["kind"] == "asgi-response-sequence-then-http-exception":
                from starlette.exceptions import HTTPException

                headers = spec["headers"]
                error = HTTPException(
                    status_code=spec["status_code"],
                    detail=spec["detail"],
                    headers=None if headers is None else dict(headers),
                )
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
    handler_property = case.get("handler_property")
    if handler_property is None:
        middleware = ServerErrorMiddleware(app, handler=handler, debug=constructor["debug"])
    else:
        handler_property = _exact_object(
            handler_property,
            {"kind", "values"},
            "ServerErrorMiddleware handler property input",
        )
        if handler_property["kind"] != "read-sequence":
            raise ValueError("unsupported ServerErrorMiddleware handler property kind")
        if not isinstance(handler_property["values"], list) or len(handler_property["values"]) != 3:
            raise ValueError("handler property read-sequence must define exactly three values")
        handler_values = [materialize_handler(spec) for spec in handler_property["values"]]

        class InputServerErrorMiddleware(ServerErrorMiddleware):
            def __init__(self, app: Any, handler: Any, debug: bool) -> None:
                self._parity_handler_values = handler_values
                self._parity_handler_property_reads = 0
                super().__init__(app, handler=handler, debug=debug)

            @property
            def handler(self) -> Any:
                index = self._parity_handler_property_reads
                self._parity_handler_property_reads = index + 1
                return self._parity_handler_values[min(index, len(self._parity_handler_values) - 1)]

            @handler.setter
            def handler(self, value: Any) -> None:
                self._parity_initial_handler = value

        middleware = InputServerErrorMiddleware(app, handler=handler, debug=constructor["debug"])
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

    for assignment in case["assignments"]:
        field = assignment["field"]
        if field == "app":
            setattr(middleware, field, materialize_app(assignment["value"]))
        elif field == "handler":
            setattr(middleware, field, materialize_handler(assignment["value"]))
        else:
            setattr(middleware, field, assignment["value"])

    dispatch = case["dispatch"]
    scope = _make_scope(dispatch["scope"])
    incoming = [_make_message(message) for message in dispatch["receive"]]
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
    if handler_property is not None:
        value["handler_property_reads"] = middleware._parity_handler_property_reads
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": value}],
    }


def _run_exception_middleware_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.middleware.exceptions import ExceptionMiddleware

    constructor = case["constructor"]
    app_calls: list[str] = []
    app_exceptions: list[BaseException] = []
    app = _materialize_server_error_middleware_app(constructor["app"], app_calls, app_exceptions)
    middleware = ExceptionMiddleware(
        app,
        handlers=constructor["handlers"],
        debug=constructor["debug"],
    )
    for assignment in case["assignments"]:
        if assignment["field"] == "app":
            middleware.app = _materialize_server_error_middleware_app(
                assignment["value"], app_calls, app_exceptions
            )

    dispatch = case["dispatch"]
    scope = _make_scope(dispatch["scope"])
    incoming = [_make_message(message) for message in dispatch["receive"]]
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
        raise ValueError("ExceptionMiddleware send input must select the ASGI event collector")
    captured_exception: BaseException | None = None
    try:
        asyncio.run(middleware(scope, receive, send))
    except Exception as exc:
        captured_exception = exc

    value = {
        "asgi_events": [_canonical_message(message) for message in sent],
        "selected_app_calls": list(app_calls),
        "propagated_error": _dispatch_error(captured_exception) if captured_exception else None,
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
            downstream_call_trace
            if case["surface"] in {CORS_SURFACE, HTTPS_REDIRECT_SURFACE}
            else None,
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
    constructor_probe_observations = []
    for probe in case.get("constructor_probes", []):
        for name in probe.get("roundtrip_attributes", []):
            setattr(middleware, name, getattr(middleware, name))
        constructor_probe_observations.append(
            {
                "probe_id": probe["probe_id"],
                "attributes": {
                    name: _json_safe(getattr(middleware, name)) for name in probe["attributes"]
                },
            }
        )
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
            value = await _invoke(
                middleware,
                dispatch_arguments,
                [],
                [],
                None,
                False,
                capture_dispatch_error=case["surface"] == CORS_SURFACE,
                capture_dispatch_error_as_observation=case["surface"] == CORS_SURFACE,
                scope_container=case.get("scope_container", "dict"),
                scope_observation=case.get("scope_observation"),
            )
            if isinstance(value, _CapturedDispatchError):
                partial_value = dict(value.partial_value)
                if constructor_probe_observations:
                    partial_value["constructor_probes"] = constructor_probe_observations
                if case["surface"] in {CORS_SURFACE, HTTPS_REDIRECT_SURFACE}:
                    selected_partial = {
                        key: partial_value[key] for key in ("asgi_events", "response_bytes")
                    }
                    if "scope_observation" in partial_value:
                        selected_partial["scope_observation"] = partial_value["scope_observation"]
                    selected_partial["downstream_call_trace"] = downstream_call_trace[trace_start:]
                    partial_value = selected_partial
                observations.append(
                    _workflow_observation(
                        dispatch_step["step_id"],
                        _CapturedDispatchError(value.error, partial_value),
                    )
                )
                continue
            selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
            if "scope_observation" in value:
                selected["scope_observation"] = value["scope_observation"]
            if constructor_probe_observations:
                selected["constructor_probes"] = constructor_probe_observations
            if case["surface"] in {CORS_SURFACE, HTTPS_REDIRECT_SURFACE}:
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


def _run_gzip_case(case: dict[str, Any]) -> dict[str, Any]:
    steps = case["steps"]
    responder = case["surface"] == "starlette.middleware.gzip.GZipResponder"
    instance_step = "responder" if responder else "middleware"
    dispatch_steps = steps[1:]
    dispatch_step_ids = [step.get("step_id") for step in dispatch_steps]
    if (
        len(steps) < 2
        or steps[0].get("step_id") != instance_step
        or steps[0].get("operation") != "__init__"
        or any(step.get("operation") != "__call__" for step in dispatch_steps)
        or any(step.get("surface") != case["surface"] for step in steps)
        or steps[0].get("receiver") is not None
        or any(
            step.get("receiver") != {"kind": "binding", "step_id": instance_step}
            for step in dispatch_steps
        )
    ):
        raise ValueError("GZip cases must construct then dispatch the declared ASGI callable")
    if case["execution_schedule"] != dispatch_step_ids or case["observations"] != dispatch_step_ids:
        raise ValueError("GZip cases must observe each dispatch step in schedule order")

    constructor_arguments = _literal_arguments(
        steps[0],
        {"app", "minimum_size", "compresslevel", "thread_minimum_size", "exclude_content_types"},
        "GZip constructor",
        optional={"minimum_size", "compresslevel", "thread_minimum_size", "exclude_content_types"},
    )
    if responder and "minimum_size" not in constructor_arguments:
        raise ValueError("GZipResponder constructor requires minimum_size")
    middleware = _materialize_gzip_middleware(constructor_arguments, responder=responder)
    assignments = case.get("assignments", [])
    if not isinstance(assignments, list):
        raise ValueError("GZip live assignments must be a list")
    for index, raw_assignment in enumerate(assignments):
        assignment = _exact_object(
            raw_assignment,
            {"field", "value"},
            f"GZip live assignment[{index}]",
        )
        if assignment["field"] != "app" or responder:
            raise ValueError("GZip live assignment must replace a middleware app")
        middleware.app = _materialize_asgi_sequence_app(assignment["value"])

    async def invoke_dispatches() -> list[dict[str, Any]]:
        observations = []
        for dispatch_step in dispatch_steps:
            dispatch_arguments = _literal_arguments(
                dispatch_step,
                {"scope", "receive", "send"},
                "GZip dispatch",
            )
            value = await _invoke(
                middleware,
                dispatch_arguments,
                [],
                [],
                None,
                False,
                capture_dispatch_error=True,
                capture_dispatch_error_as_observation=True,
                allow_missing_response_start=responder,
                scope_container=case.get("scope_container", "dict"),
                scope_observation=case.get("scope_observation"),
            )
            if isinstance(value, _CapturedDispatchError):
                partial_value = {
                    key: value.partial_value[key] for key in ("asgi_events", "response_bytes")
                }
                if "scope_observation" in case:
                    partial_value["scope_observation"] = value.partial_value["scope_observation"]
                observations.append(
                    _workflow_observation(
                        dispatch_step["step_id"],
                        _CapturedDispatchError(value.error, partial_value),
                    )
                )
                continue
            selected = {key: value[key] for key in ("asgi_events", "response_bytes")}
            if "scope_observation" in value:
                selected["scope_observation"] = value["scope_observation"]
            observations.append(
                {"step_id": dispatch_step["step_id"], "status": "ok", "value": selected}
            )
        return observations

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": asyncio.run(invoke_dispatches()),
    }


class _InputDrivenHeaderPair(list[str]):
    def __init__(self, items: list[str], iterated_items: list[str]) -> None:
        super().__init__(items)
        self._iterated_items = iterated_items

    def __iter__(self) -> Iterator[str]:
        return iter(self._iterated_items)


def _materialize_wsgi_header_pairs(headers: list[Any]) -> list[Any]:
    materialized: list[Any] = []
    for pair in headers:
        if isinstance(pair, dict):
            pair = _exact_object(
                pair,
                {"kind", "items", "iterated_items"},
                "WSGI input-defined header pair",
            )
            if (
                pair["kind"] != "list-subclass-iter-override"
                or not isinstance(pair["items"], list)
                or not isinstance(pair["iterated_items"], list)
            ):
                raise ValueError("WSGI header pair iterator input is malformed")
            materialized.append(_InputDrivenHeaderPair(pair["items"], pair["iterated_items"]))
        else:
            materialized.append(pair)
    return materialized


def _materialize_wsgi_app(spec: dict[str, Any]) -> Any:
    caller_thread_id = threading.get_ident()
    kind = spec["kind"]

    def materialize_status(value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        class StatusSplitIterator(str):
            def __new__(cls, status_value: str, split_items: list[str]) -> StatusSplitIterator:
                instance = super().__new__(cls, status_value)
                instance._split_items = tuple(split_items)
                return instance

            def split(self, sep: str | None = None, maxsplit: int = -1) -> Iterator[str]:
                return iter(self._split_items)

        return StatusSplitIterator(value["value"], value["split_items"])

    if kind == "wsgi-iterator-error":
        failure_classes = {
            "OSError": OSError,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
        }
        failure_type = failure_classes.get(spec["failure"]["class"])
        if failure_type is None:
            raise ValueError(
                f"unsupported input-defined WSGI iterator error class: {spec['failure']['class']!r}"
            )

        def iterator_failure_app(_environ: dict[str, Any], start_response: Any) -> Iterator[bytes]:
            def chunks() -> Iterator[bytes]:
                start_response(materialize_status(spec["status"]), spec["headers"])
                for chunk in spec["chunks_base64"]:
                    yield base64.b64decode(chunk, validate=True)
                raise failure_type(spec["failure"]["message"])

            return chunks()

        return iterator_failure_app

    def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        if kind == "wsgi-response":
            start_response(
                materialize_status(spec["status"]),
                _materialize_wsgi_header_pairs(spec["headers"]),
            )
            return [base64.b64decode(chunk, validate=True) for chunk in spec["chunks_base64"]]
        if kind == "wsgi-echo-body":
            start_response(materialize_status(spec["status"]), spec["headers"])
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
            start_response(materialize_status(spec["status"]), spec["headers"])
            return [json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")]
        if kind == "wsgi-raise-before-start":
            raise RuntimeError(spec["message"])
        if kind == "wsgi-exc-info-rethrow":
            try:
                raise RuntimeError(spec["message"])
            except RuntimeError:
                start_response(
                    materialize_status(spec["status"]),
                    spec["headers"],
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
    incoming = [_make_message(message) for message in dispatch_arguments["receive"]]
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
        "asgi_events": events,
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "received_message_count": received,
        "dispatch_error": captured_error,
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": value}],
    }


def _materialize_body_limit_script(spec: dict[str, Any], trace: list[dict[str, Any]]) -> Any:
    from starlette.middleware.body_limit import (
        _BODY_LIMIT_RESPONDER_SCOPE_KEY,
        MAX_BODY_SIZE_SCOPE_KEY,
        RequestBodyLimitMiddleware,
    )

    app_spec = _exact_object(spec, {"kind", "actions"}, "body-limit script app")
    if app_spec["kind"] != "asgi-body-limit-script" or not isinstance(app_spec["actions"], list):
        raise ValueError("body-limit app must be an input-defined ASGI action script")
    actions = app_spec["actions"]

    async def script(scope: Any, receive: Any, send: Any) -> None:
        for index, action in enumerate(actions):
            if not isinstance(action, dict) or not isinstance(action.get("action"), str):
                raise ValueError(f"body-limit action[{index}] must declare an action")
            kind = action["action"]
            if kind == "receive":
                _exact_object(action, {"action"}, f"body-limit action[{index}]")
                message = await receive()
                trace.append({"event": "receive", "message": _json_safe(message)})
            elif kind == "send":
                _exact_object(action, {"action", "message"}, f"body-limit action[{index}]")
                operation, message = _materialize_asgi_action(
                    {"action": "send", "message": action["message"]}, index
                )
                if operation != "send":
                    raise RuntimeError("body-limit send action did not materialize a send")
                await send(message)
                trace.append({"event": "send", "message": _canonical_message(message)})
            elif kind == "nested":
                _exact_object(
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
                _exact_object(action, {"action"}, f"body-limit action[{index}]")
                trace.append(
                    {
                        "event": "scope",
                        "type": scope.get("type"),
                        "max_body_size_present": MAX_BODY_SIZE_SCOPE_KEY in scope,
                        "max_body_size": _json_safe(scope.get(MAX_BODY_SIZE_SCOPE_KEY)),
                        "responder_present": _BODY_LIMIT_RESPONDER_SCOPE_KEY in scope,
                    }
                )
            elif kind == "observe-scope-headers":
                _exact_object(action, {"action"}, f"body-limit action[{index}]")
                trace.append(
                    {
                        "event": "scope-headers",
                        "container": type(scope["headers"]).__name__,
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
    if case.get("scope_headers_container", "list") == "tuple":
        scope["headers"] = tuple(scope["headers"])
    if prior_scope_limit is not _MISSING:
        scope[MAX_BODY_SIZE_SCOPE_KEY] = prior_scope_limit
    scope = _scope_container(scope, case.get("scope_container", "dict"))
    incoming = [_make_message(message) for message in dispatch_arguments["receive"]]
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
    scope_observation_result = (
        _scope_observation(scope, case["scope_observation"])
        if "scope_observation" in case
        else None
    )

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
    if scope_observation_result is not None:
        value["scope_observation"] = scope_observation_result
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "dispatch", "status": "ok", "value": {"dispatch": value}}],
    }


def _make_websocket_scope(spec: dict[str, Any]) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    if "type" in spec:
        scope_type, _ = _materialize_scope_type_spec(spec["type"])
        scope["type"] = scope_type
    scope.update(
        {
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
    )
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    return scope


class _InputStringSubclass(str):
    """Carry input-defined comparison or hashing behavior into an ASGI message."""

    def __new__(
        cls,
        value: str,
        *,
        equal_result: bool | None = None,
        not_equal_result: bool | None = None,
        hash_error: str | None = None,
    ) -> _InputStringSubclass:
        instance = super().__new__(cls, value)
        instance._equal_result = equal_result
        instance._not_equal_result = not_equal_result
        instance._hash_error = hash_error
        return instance

    def __eq__(self, other: object) -> Any:
        if self._equal_result is not None:
            return self._equal_result
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        if self._not_equal_result is not None:
            return self._not_equal_result
        result = str.__eq__(self, other)
        return result is NotImplemented or not result

    def __hash__(self) -> int:
        if self._hash_error is not None:
            raise TypeError(self._hash_error)
        return str.__hash__(self)


def _materialize_base_http_downstream_message_type(value: Any) -> tuple[Any, str]:
    if isinstance(value, str):
        return value, str.__str__(value)
    descriptor = _exact_object(value, {"str_subclass"}, "BaseHTTPMiddleware ASGI message type")
    subclass = _exact_object(
        descriptor["str_subclass"],
        {"value", "equal_result"},
        "BaseHTTPMiddleware ASGI message type str_subclass",
    )
    message_type = subclass["value"]
    equal_result = subclass["equal_result"]
    if (
        not isinstance(message_type, str)
        or message_type
        not in {"http.response.start", "http.response.body", "http.response.pathsend"}
        or equal_result is not False
    ):
        raise ValueError("BaseHTTPMiddleware ASGI message type subclass is invalid")
    return _InputStringSubclass(message_type, equal_result=equal_result), message_type


class _InputTypeLookupTape(dict[str, Any]):
    """A WebSocket message mapping whose type reads follow the supplied input tape."""

    def __init__(self, message: dict[str, Any], lookup_tape: list[str]) -> None:
        super().__init__(message)
        self._lookup_tape = tuple(lookup_tape)
        self._lookup_index = 0

    def __getitem__(self, key: str) -> Any:
        if key == "type":
            index = self._lookup_index
            self._lookup_index += 1
            try:
                return self._lookup_tape[index]
            except IndexError:
                raise IndexError("WebSocket message type lookup tape exhausted") from None
        return super().__getitem__(key)


def _materialize_websocket_message(spec: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {}
    for name, value in spec.items():
        if name == "type_lookup_tape":
            continue
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
        elif name == "type" and isinstance(value, dict) and "str_subclass" in value:
            # Keep this generated type's qualname aligned with the oracle's
            # function-local InputStringSubclass for matching Python errors.
            class InputStringSubclass(_InputStringSubclass):
                pass

            _exact_object(value, {"str_subclass"}, "WebSocket message type descriptor")
            subclass_spec = value["str_subclass"]
            if not isinstance(subclass_spec, dict):
                raise ValueError("WebSocket message str_subclass must be an object")
            subclass_value = subclass_spec.get("value")
            if not isinstance(subclass_value, str):
                raise ValueError("WebSocket message str_subclass value must be a string")
            if "not_equal_result" in subclass_spec:
                _exact_object(
                    subclass_spec,
                    {"value", "not_equal_result"},
                    "WebSocket message str_subclass descriptor",
                )
                if not isinstance(subclass_spec["not_equal_result"], bool):
                    raise ValueError("WebSocket message not_equal_result must be a boolean")
                message[name] = InputStringSubclass(
                    subclass_value,
                    not_equal_result=subclass_spec["not_equal_result"],
                )
            else:
                _exact_object(
                    subclass_spec,
                    {"value", "hash_error"},
                    "WebSocket message str_subclass descriptor",
                )
                if not isinstance(subclass_spec["hash_error"], str):
                    raise ValueError("WebSocket message hash_error must be a string")
                message[name] = InputStringSubclass(
                    subclass_value, hash_error=subclass_spec["hash_error"]
                )
        else:
            message[name] = value
    if "type_lookup_tape" in spec:
        return _InputTypeLookupTape(message, spec["type_lookup_tape"])
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


class _InputProbeBodyError(RuntimeError):
    """Materialize a body-source failure specified by one parity input."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _native_error_value(exc: BaseException) -> dict[str, str]:
    return {
        "kind": str(getattr(exc, "kind", type(exc).__qualname__)),
        "message": str(exc),
    }


def _native_workflow_result(case: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "workflow", "status": "ok", "value": {"workflow": workflow}}],
    }


def _run_native_service_streaming_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
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
            "drive",
            "observations",
        },
        "native service streaming case",
    )
    if case["surface"] != NATIVE_SERVICE_SURFACE or case["operation"] != NATIVE_SERVICE_OPERATION:
        raise ValueError("case is outside the native service streaming operation")

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    request_spec = case["request"]
    request_body_frames = request_spec["body"]["frames"]
    request_state: dict[str, Any] = {
        "index": 0,
        "handler_entered": False,
        "request_chunks": [],
        "request_error": None,
        "response_status": None,
        "response_chunks": [],
        "response_error": None,
    }
    response_drive = case["drive"].get("response_body")
    response_queue: asyncio.Queue[tuple[dict[str, Any], asyncio.Future[None]] | None] = (
        asyncio.Queue()
    )
    response_started = asyncio.Event()
    release_response_start = asyncio.Event()

    def make_endpoint(route_spec: dict[str, Any]) -> Callable[[Request], Any]:
        endpoint_spec = route_spec["endpoint"]

        async def endpoint(request: Request) -> Any:
            request_state["handler_entered"] = True
            projection_spec = endpoint_spec.get("response_body_from_request")
            if projection_spec is not None:
                selected = []
                for field in projection_spec["fields"]:
                    if field == "method":
                        value = request.method
                    elif field == "uri":
                        value = request.scope["path"]
                        if request.scope["query_string"]:
                            value += "?" + request.scope["query_string"].decode("ascii")
                    elif field == "path":
                        value = request.scope["path"]
                    elif field == "query":
                        value = request.scope["query_string"].decode("ascii") or None
                    elif field == "http_version":
                        value = request.scope["http_version"]
                    elif field == "headers":
                        value = [
                            [name, request.headers.getlist(name)]
                            for name in projection_spec["header_names"]
                        ]
                    elif field == "path_params":
                        value = [
                            [str(name), str(item)] for name, item in request.path_params.items()
                        ]
                    else:
                        value = request.scope.get("root_path", "")
                    selected.append([field, value])
                return JSONResponse(selected)
            if endpoint_spec["request_body_action"] != "leave-unread":
                try:
                    async for chunk in request.stream():
                        if chunk:
                            request_state["request_chunks"].append(
                                base64.b64encode(chunk).decode("ascii")
                            )
                except Exception as exc:
                    request_state["request_error"] = _native_error_value(exc)
                    raise

            async def response_body() -> AsyncIterator[bytes]:
                for frame in endpoint_spec["response_body"]["frames"]:
                    if "data_base64" in frame:
                        yield _decode_base64(frame["data_base64"], "response frame data_base64")
                    elif "error" in frame:
                        error_spec = frame["error"]
                        raise _InputProbeBodyError(error_spec["kind"], error_spec["message"])
                    elif frame.get("end") is True:
                        return
                    else:
                        raise ValueError("unsupported native service response body frame")

            return StreamingResponse(response_body())

        return endpoint

    routes = [
        Route(
            route_spec["path"],
            make_endpoint(route_spec),
            methods=route_spec["methods"],
        )
        for route_spec in case["application"]["routes"]
    ]
    app = Starlette(routes=routes)

    async def receive() -> dict[str, Any]:
        index = request_state["index"]
        if index >= len(request_body_frames):
            return {"type": "http.request", "body": b"", "more_body": False}
        frame = request_body_frames[index]
        request_state["index"] = index + 1
        if "data_base64" in frame:
            more_body = index + 1 < len(request_body_frames)
            return {
                "type": "http.request",
                "body": _decode_base64(frame["data_base64"], "request frame data_base64"),
                "more_body": more_body,
            }
        if "error" in frame:
            error_spec = frame["error"]
            raise _InputProbeBodyError(error_spec["kind"], error_spec["message"])
        if frame.get("end") is True:
            return {"type": "http.request", "body": b"", "more_body": False}
        if frame.get("pending") is True:
            await asyncio.Future()
        raise ValueError("unsupported native service request body frame")

    async def send(message: dict[str, Any]) -> None:
        if request_state["request_error"] is not None:
            return
        if message["type"] == "http.response.start":
            if request_state["response_status"] is None:
                request_state["response_status"] = message["status"]
            response_started.set()
            if response_drive == "drop-without-poll":
                await release_response_start.wait()
            return
        if message["type"] == "http.response.body":
            acknowledgement = asyncio.get_running_loop().create_future()
            await response_queue.put((message, acknowledgement))
            await acknowledgement

    parsed_uri = request_spec["uri"]
    path, separator, query = parsed_uri.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": request_spec.get("http_version", "1.1"),
        "method": request_spec["method"],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query.encode("utf-8") if separator else b"",
        "root_path": request_spec.get("root_path", ""),
        "headers": [(b"host", b"example.test")]
        + [
            (name.encode("latin-1"), value.encode("latin-1"))
            for name, value in request_spec.get("headers", [])
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("example.test", 80),
    }

    async def invoke() -> None:
        try:
            await app(scope, receive, send)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if (
                request_state["request_error"] is None
                and request_state["response_status"] is not None
            ):
                request_state["response_error"] = _native_error_value(exc)
        finally:
            await response_queue.put(None)

    async def consume_body_message() -> bool:
        item = await response_queue.get()
        if item is None:
            return False
        message, acknowledgement = item
        body = message.get("body", b"")
        if body:
            request_state["response_chunks"].append(base64.b64encode(body).decode("ascii"))
        more_body = bool(message.get("more_body", False))
        acknowledgement.set_result(None)
        return more_body

    async def run() -> dict[str, Any]:
        app_task = asyncio.create_task(invoke())
        if response_drive == "drop-without-poll":
            await response_started.wait()
            app_task.cancel()
            try:
                await app_task
            except asyncio.CancelledError:
                pass
        elif request_state["request_error"] is None and response_drive is not None:
            await response_started.wait()
            if isinstance(response_drive, str) and response_drive in {
                "read-to-end",
                "read-to-error",
            }:
                while await consume_body_message():
                    pass
            elif isinstance(response_drive, dict):
                response_body_complete = False
                for read in response_drive["read_frames"]:
                    if read == "to-end":
                        while await consume_body_message():
                            pass
                        response_body_complete = True
                        break
                    remaining = read
                    while remaining > 0:
                        has_more = await consume_body_message()
                        if not has_more:
                            response_body_complete = True
                            break
                        remaining -= 1
                    if response_body_complete:
                        break
                if not response_body_complete:
                    app_task.cancel()
                    try:
                        await app_task
                    except asyncio.CancelledError:
                        pass
                else:
                    await app_task
            else:
                raise ValueError("unsupported native service response body drive")
        else:
            await app_task

        request_error = request_state["request_error"]
        response_error = request_state["response_error"]
        workflow = {
            "handler-entry": request_state["handler_entered"],
            "request-body-chunks": request_state["request_chunks"],
            "response-available": (
                {"status": request_state["response_status"]}
                if request_state["response_status"] is not None and request_error is None
                else None
            ),
            "response-body-chunks": request_state["response_chunks"],
            "request-body-error-propagation": (
                {"message": request_error["message"]} if request_error else None
            ),
            "response-body-error-propagation": (
                {"message": response_error["message"]} if response_error else None
            ),
            "service-error": {"message": request_error["message"]} if request_error else None,
        }
        return workflow

    return _native_workflow_result(case, asyncio.run(run()))


def _native_scope_path_params(scope: Mapping[str, Any]) -> list[list[str]]:
    path_params = scope.get("path_params", {})
    if not isinstance(path_params, Mapping):
        return []
    return [[str(name), str(value)] for name, value in path_params.items()]


def _native_service_scope(
    request_spec: dict[str, Any], initial_scope: dict[str, Any]
) -> dict[str, Any]:
    uri = request_spec["uri"]
    path, separator, query = uri.partition("?")
    headers: list[tuple[bytes, bytes]] = []
    host_header = request_spec.get("host_header", "example.test")
    if host_header is not None:
        headers.append((b"host", host_header.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": request_spec.get("version", "1.1"),
        "method": request_spec["method"],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query.encode("utf-8") if separator else b"",
        "root_path": initial_scope.get("root_path", ""),
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("example.test", 80),
    }
    if "app_root_path" in initial_scope:
        scope["app_root_path"] = initial_scope["app_root_path"]
    if initial_scope.get("path_params"):
        converted: dict[str, Any] = {}
        for item in initial_scope["path_params"]:
            value = item["value"]
            if item["converter"] == "int":
                value = int(value)
            converted[item["name"]] = value
        scope["path_params"] = converted
    return scope


def _native_service_receive(request_spec: dict[str, Any]) -> Callable[[], Any]:
    frames = request_spec["body"]["frames"]
    state = {"index": 0}

    async def receive() -> dict[str, Any]:
        index = state["index"]
        if index >= len(frames):
            return {"type": "http.request", "body": b"", "more_body": False}
        frame = frames[index]
        state["index"] = index + 1
        if "data_base64" in frame:
            return {
                "type": "http.request",
                "body": _decode_base64(frame["data_base64"], "request frame data_base64"),
                "more_body": index + 1 < len(frames),
            }
        if "error" in frame:
            error_spec = frame["error"]
            raise _InputProbeBodyError(error_spec["kind"], error_spec["message"])
        if frame.get("end") is True:
            return {"type": "http.request", "body": b"", "more_body": False}
        if frame.get("pending") is True:
            await asyncio.Future()
        raise ValueError("unsupported native service request body frame")

    return receive


def _run_native_service_routing_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
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
            "drive",
            "observations",
        },
        "native service routing case",
    )
    if case["observations"] != ["workflow"]:
        raise ValueError("native service routing observations must select workflow")

    is_mounted = (
        case["surface"] == NATIVE_SERVICE_SURFACE
        and case["operation"] == NATIVE_MOUNTED_CHILD_OPERATION
    )
    is_host = (
        case["surface"] == NATIVE_HOST_SERVICE_SURFACE
        and case["operation"] == NATIVE_HOST_SERVICE_OPERATION
    )
    if not (is_mounted or is_host):
        raise ValueError("case is outside the native service routing operations")

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Host, Mount, Route

    request_spec = case["request"]
    capture: dict[str, Any] = {}

    def record_scope(scope: Mapping[str, Any]) -> None:
        capture["scope"] = scope

    def make_route(route_spec: dict[str, Any]) -> Any:
        endpoint_spec = route_spec["endpoint"]

        async def endpoint(request: Request) -> Any:
            record_scope(request.scope)
            if "response_body_from_request" in endpoint_spec:
                selected: list[list[Any]] = []
                for field in endpoint_spec["response_body_from_request"]:
                    if field == "path":
                        value = request.scope["path"]
                    elif field == "root_path":
                        value = request.scope.get("root_path", "")
                    elif field == "app_root_path":
                        value = request.scope.get(
                            "app_root_path", request.scope.get("root_path", "")
                        )
                    elif field == "path_params":
                        value = _native_scope_path_params(request.scope)
                    else:
                        raise ValueError(f"unsupported native request field: {field!r}")
                    selected.append([field, value])
                return JSONResponse(selected)
            if endpoint_spec.get("action") == "echo-path-params":
                return JSONResponse(_native_scope_path_params(request.scope))
            if "response_body" in endpoint_spec:

                async def response_body() -> AsyncIterator[bytes]:
                    for frame in endpoint_spec["response_body"]["frames"]:
                        if "data_base64" in frame:
                            yield _decode_base64(frame["data_base64"], "response frame data_base64")
                        elif "error" in frame:
                            error_spec = frame["error"]
                            raise _InputProbeBodyError(error_spec["kind"], error_spec["message"])
                        elif frame.get("end") is True:
                            return
                        else:
                            raise ValueError("unsupported native service response body frame")

                return StreamingResponse(response_body())
            return JSONResponse([])

        class ScopeCaptureRoute(Route):
            async def handle(
                self,
                scope: dict[str, Any],
                receive: Callable[..., Any],
                send: Callable[..., Any],
            ) -> None:
                record_scope(scope)
                await super().handle(scope, receive, send)

        return ScopeCaptureRoute(
            route_spec["path"],
            endpoint,
            methods=route_spec.get("methods"),
        )

    if is_mounted:
        children = case["application"]["children"]
        mounts = []
        for child in children:
            if child["kind"] == "mount":
                child_app = Starlette(
                    routes=[make_route(route_spec) for route_spec in child["application"]["routes"]]
                )

                async def capture_child_scope(
                    scope: dict[str, Any],
                    receive: Callable[..., Any],
                    send: Callable[..., Any],
                    app: Any = child_app,
                ) -> None:
                    record_scope(scope)
                    await app(scope, receive, send)

                mounts.append(Mount(child["path"], app=capture_child_scope))
            else:
                raise ValueError(f"unsupported native application child: {child['kind']!r}")
        app = Starlette(routes=mounts)
    else:
        host_routes = []
        for host_route in case["application"]["host_routes"]:
            child_app = Starlette(
                routes=[make_route(route_spec) for route_spec in host_route["routes"]]
            )

            async def capture_host_scope(
                scope: dict[str, Any],
                receive: Callable[..., Any],
                send: Callable[..., Any],
                app: Any = child_app,
            ) -> None:
                record_scope(scope)
                await app(scope, receive, send)

            host_routes.append(Host(host_route["host"], app=capture_host_scope))
        app = Starlette(routes=host_routes)

    initial_scope = case["request"].get("scope", {})
    scope = _native_service_scope(request_spec, initial_scope)
    record_scope(scope)
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    service_error: str | None = None
    try:
        asyncio.run(app(scope, _native_service_receive(request_spec), send))
    except Exception as exc:
        service_error = str(exc)

    response_start = next(
        (message for message in messages if message["type"] == "http.response.start"),
        None,
    )
    body_chunks = [
        base64.b64encode(message.get("body", b"")).decode("ascii")
        for message in messages
        if message["type"] == "http.response.body" and message.get("body", b"")
    ]
    final_scope = capture.get("scope", scope)
    workflow = {
        "status": response_start["status"] if response_start is not None else None,
        "response_body_chunks": body_chunks,
        "path_params": _native_scope_path_params(final_scope),
        "root_path": final_scope.get("root_path"),
        "app_root_path": final_scope.get("app_root_path", final_scope.get("root_path", "")),
        "service_error": service_error,
    }
    return _native_workflow_result(case, workflow)


def _native_custom_converter_scope(converter_specs: list[dict[str, Any]]) -> Any:
    from starlette.convertors import CONVERTOR_TYPES, Convertor, register_url_convertor

    previous = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], _MISSING) for spec in converter_specs
    }

    class InputDefinedConvertor(Convertor[str]):
        def __init__(self, spec: dict[str, Any]) -> None:
            self.regex = spec["regex"]
            self.convert_mode = spec["convert"]
            self.format_mode = spec["to_string"]

        @staticmethod
        def _apply(mode: str, value: str) -> str:
            if mode == "lowercase":
                return value.lower()
            if mode == "uppercase":
                return value.upper()
            if mode == "identity":
                return value
            raise ValueError(f"unsupported input converter mode: {mode!r}")

        def convert(self, value: str) -> str:
            return self._apply(self.convert_mode, value)

        def to_string(self, value: str) -> str:
            return self._apply(self.format_mode, str(value))

    class RegistryContext:
        def __enter__(self) -> None:
            for spec in converter_specs:
                register_url_convertor(spec["name"], InputDefinedConvertor(spec))
            return None

        def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
            for name, old_value in previous.items():
                if old_value is _MISSING:
                    CONVERTOR_TYPES.pop(name, None)
                else:
                    CONVERTOR_TYPES[name] = old_value
            return False

    return RegistryContext()


def _run_native_custom_converter_match_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "converters",
            "routes",
            "match",
            "observations",
        },
        "native custom-converter match case",
    )
    if (
        case["surface"] != NATIVE_ROUTE_TABLE_SURFACE
        or case["operation"] != NATIVE_ROUTE_TABLE_CONVERTER_OPERATION
        or case["observations"] != ["workflow"]
    ):
        raise ValueError("case is outside the native custom-converter match operation")

    from starlette.routing import Match, Route

    for index, spec in enumerate(case["converters"]):
        _exact_object(
            spec,
            {"name", "regex", "convert", "to_string"},
            f"custom path converter[{index}]",
        )
    path = case["match"]["path"]
    method = case["match"]["method"]
    scope = {"type": "http", "path": path, "method": method, "path_params": {}}
    matched: dict[str, Any] | None = None
    first_partial: dict[str, Any] | None = None
    try:
        with _native_custom_converter_scope(case["converters"]):
            for route_index, route_spec in enumerate(case["routes"]):
                route = Route(
                    route_spec["path"],
                    lambda _scope: None,
                    methods=route_spec.get("methods"),
                )
                match, child_scope = route.matches(scope)
                if match is Match.FULL:
                    matched = {
                        "route_index": route_index,
                        "path_params": _native_scope_path_params(child_scope),
                    }
                    break
                if match is Match.PARTIAL and first_partial is None:
                    first_partial = {
                        "route_index": route_index,
                        "path_params": _native_scope_path_params(child_scope),
                    }
    except Exception as exc:
        return _native_workflow_result(case, {"match": None, "error": str(exc)})
    return _native_workflow_result(case, {"match": matched or first_partial, "error": None})


def _run_native_custom_converter_url_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "converters",
            "route",
            "lookup",
            "observations",
        },
        "native custom-converter URL case",
    )
    if (
        case["surface"] != NATIVE_NAMED_ROUTE_SURFACE
        or case["operation"] != NATIVE_NAMED_ROUTE_CONVERTER_OPERATION
        or case["observations"] != ["workflow"]
    ):
        raise ValueError("case is outside the native custom-converter URL operation")

    from starlette.routing import Route

    for index, spec in enumerate(case["converters"]):
        _exact_object(
            spec,
            {"name", "regex", "convert", "to_string"},
            f"custom path converter[{index}]",
        )
    route_spec = case["route"]
    lookup = case["lookup"]
    try:
        with _native_custom_converter_scope(case["converters"]):
            route = Route(
                route_spec["path"],
                lambda _scope: None,
                name=route_spec["name"],
            )
            url_path = route.url_path_for(
                lookup["name"],
                **lookup["path_params"],
            )
        workflow = {
            "path": str(url_path),
            "protocol": url_path.protocol,
            "host": url_path.host,
            "error": None,
        }
    except Exception as exc:
        workflow = {
            "path": None,
            "protocol": None,
            "host": None,
            "error": str(exc),
        }
    return _native_workflow_result(case, workflow)


def _run_native_lazy_source_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "status_code",
            "header_pairs",
            "media_type",
            "source",
            "scope",
            "incoming",
            "send",
            "background",
            "observations",
            "streaming",
        },
        "native lazy streaming response case",
    )
    if (
        case["surface"] != NATIVE_STREAM_SOURCE_SURFACE
        or case["operation"] != NATIVE_STREAM_SOURCE_OPERATION
        or case["observations"] != ["workflow"]
        or case["streaming"] != "async-generator"
        or case["incoming"] != []
    ):
        raise ValueError("case is outside the native lazy streaming response operation")

    from starlette.background import BackgroundTask
    from starlette.responses import StreamingResponse

    source_spec = case["source"]
    items: list[bytes] = []
    for index, item in enumerate(source_spec["items"]):
        if item["kind"] == "text":
            items.append(item["value"].encode("utf-8"))
        elif item["kind"] == "base64-bytes":
            items.append(_decode_base64(item["value"], f"source.items[{index}].value"))
        else:
            raise ValueError(f"unsupported lazy response source item: {item['kind']!r}")
    markers = source_spec["pull_markers"]
    if len(markers) != len(items):
        raise ValueError("lazy response source pull markers must align with its items")
    terminal = source_spec["terminal"]
    execution_trace: list[str] = []
    source_poll_trace: list[str] = []
    background_trace: list[str] = []
    events: list[dict[str, Any]] = []
    send_spec = case["send"]
    send_index = 0

    background_spec = case["background"]
    background_values: list[str] | None = None
    background_error_class: type[Exception] | None = None
    background_error_message: str | None = None
    if background_spec is not None:
        if not isinstance(background_spec, dict):
            raise ValueError("lazy response background must be an object or null")
        background_fields = {"kind", "values"}
        if "failure" in background_spec:
            background_fields.add("failure")
        background_spec = _exact_object(
            background_spec, background_fields, "lazy response background"
        )
        if background_spec["kind"] != "async-values-recorder":
            raise ValueError("unsupported lazy response background kind")
        raw_background_values = background_spec["values"]
        if not isinstance(raw_background_values, list) or any(
            not isinstance(value, str) for value in raw_background_values
        ):
            raise ValueError("lazy response background values must be strings")
        background_values = raw_background_values
        if "failure" in background_spec:
            failure = _exact_object(
                background_spec["failure"],
                {"type", "message"},
                "lazy response background failure",
            )
            error_type = failure["type"]
            error_message = failure["message"]
            error_class = (
                getattr(builtins, error_type, None) if isinstance(error_type, str) else None
            )
            if (
                error_class is None
                or not isinstance(error_class, type)
                or not issubclass(error_class, Exception)
                or not isinstance(error_message, str)
            ):
                raise ValueError(
                    "lazy response background failure must name a built-in Exception and message"
                )
            background_error_class = error_class
            background_error_message = error_message

    def source_error() -> BaseException:
        error_spec = terminal["error"]
        error_class = getattr(builtins, error_spec["type"], None)
        if not isinstance(error_class, type) or not issubclass(error_class, BaseException):
            raise ValueError(f"unsupported lazy response error class: {error_spec['type']!r}")
        return error_class(error_spec["message"])

    async def source() -> AsyncIterator[bytes]:
        try:
            for marker, item in zip(markers, items, strict=True):
                source_poll_trace.append(marker)
                execution_trace.append(f"source:{marker}")
                yield item
            if terminal["kind"] == "error":
                error = source_error()
                execution_trace.append(f"source-error:{type(error).__qualname__}:{error}")
                raise error
            if terminal["kind"] != "end":
                raise ValueError(f"unsupported lazy response terminal: {terminal['kind']!r}")
        finally:
            marker = source_spec["finally_marker"]
            finalizer = f"source-finalize:{marker}"
            source_poll_trace.append(finalizer)
            execution_trace.append(finalizer)

    async def run_background() -> None:
        for value in background_values or []:
            background_trace.append(value)
            execution_trace.append(f"background:{value}")
        if background_error_class is not None and background_error_message is not None:
            raise background_error_class(background_error_message)

    response = StreamingResponse(
        source(),
        status_code=case["status_code"],
        headers=dict(case["header_pairs"]),
        media_type=case["media_type"],
        background=(BackgroundTask(run_background) if background_values is not None else None),
    )
    scope = _make_scope(case["scope"])

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index
        current_index = send_index
        send_index += 1
        if send_spec["kind"] == "capture-asgi-send-with-checkpoint-gate":
            if current_index == send_spec["event_index"]:
                for _ in range(send_spec["release_after_checkpoints"]):
                    await asyncio.sleep(0)
        elif (
            send_spec["kind"] == "capture-asgi-send-with-caller-cancellation"
            and current_index == send_spec["event_index"]
        ):
            execution_trace.append("send:cancel")
            raise asyncio.CancelledError

        if message["type"] == "http.response.start":
            header_pairs = [
                [
                    base64.b64encode(name).decode("ascii"),
                    base64.b64encode(value).decode("ascii"),
                ]
                for name, value in message["headers"]
            ]
            events.append(
                {
                    "type": message["type"],
                    "status": message["status"],
                    "headers_base64_pairs": header_pairs,
                }
            )
            execution_trace.append("send:start")
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            encoded_body = base64.b64encode(body).decode("ascii")
            more_body = bool(message.get("more_body", False))
            events.append(
                {
                    "type": message["type"],
                    "body_base64": encoded_body,
                    "more_body": more_body,
                }
            )
            if more_body:
                execution_trace.append(f"send:chunk:{encoded_body}")
            else:
                execution_trace.append("send:final")
        else:
            raise ValueError(f"unsupported lazy response ASGI message: {message['type']!r}")

    error_value: dict[str, str] | None = None
    try:
        asyncio.run(response(scope, receive, send))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        error_value = {"class": type(exc).__qualname__, "message": str(exc)}

    headers = [
        [
            base64.b64encode(name).decode("ascii"),
            base64.b64encode(value).decode("ascii"),
        ]
        for name, value in response.raw_headers
    ]
    workflow = {
        "status": response.status_code,
        "headers": headers,
        "events": events,
        "execution_trace": execution_trace,
        "source_poll_trace": source_poll_trace,
        "background_execution_trace": background_trace,
        "error": error_value,
    }
    return _native_workflow_result(case, workflow)


def _run_native_websocket_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "input",
            "observations",
        },
        "native WebSocket case",
    )
    if (
        case["surface"] != NATIVE_WEBSOCKET_SURFACE
        or case["operation"] != NATIVE_WEBSOCKET_OPERATION
    ):
        raise ValueError("case is outside the native WebSocket session operation")

    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute

    input_spec = case["input"]
    handshake = input_spec["handshake"]
    route_spec = input_spec["route"]
    offered = list(handshake["offered_subprotocols"])
    incoming_specs = list(input_spec.get("incoming", []))
    actions = input_spec["actions"]
    cancellation = input_spec.get("cancellation")
    websocket_state: dict[str, Any] = {
        "incoming_index": 0,
        "connect_sent": False,
        "pending_requested": False,
        "accepted": None,
        "handshake": None,
        "path_params": {},
        "messages": [],
        "peer_close": None,
        "close": None,
        "application_error": None,
        "application_result_error_kind": None,
        "receive_cancelled": False,
    }
    pending_receive_started = asyncio.Event()

    async def receive() -> dict[str, Any]:
        if not websocket_state["connect_sent"]:
            websocket_state["connect_sent"] = True
            return {"type": "websocket.connect"}
        index = websocket_state["incoming_index"]
        if index < len(incoming_specs):
            spec = incoming_specs[index]
            websocket_state["incoming_index"] = index + 1
            if spec["kind"] == "text":
                return {"type": "websocket.receive", "text": spec["value"]}
            if spec["kind"] == "binary":
                return {
                    "type": "websocket.receive",
                    "bytes": _decode_base64(spec["base64"], "WebSocket input binary message"),
                }
            if spec["kind"] == "peer-close":
                return {
                    "type": "websocket.disconnect",
                    "code": spec["code"],
                    "reason": spec["reason"],
                }
            raise ValueError("unsupported native WebSocket incoming event")
        if websocket_state["pending_requested"]:
            pending_receive_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                websocket_state["receive_cancelled"] = True
                raise
        return {"type": "websocket.disconnect", "code": 1000, "reason": ""}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "websocket.accept":
            websocket_state["accepted"] = message
        elif message["type"] == "websocket.close":
            websocket_state["close"] = {
                "code": message["code"],
                "reason": message.get("reason", ""),
            }

    async def endpoint(websocket: Any) -> None:
        scope_uri = bytes(websocket.scope["raw_path"]).decode("ascii")
        scope_query = bytes(websocket.scope["query_string"]).decode("ascii")
        websocket_state["handshake"] = {
            "method": websocket.scope["method"],
            "uri": f"{scope_uri}?{scope_query}" if scope_query else scope_uri,
            "version": f"HTTP/{websocket.scope['http_version']}",
            "headers": [
                [name.decode("ascii").lower(), base64.b64encode(value).decode("ascii")]
                for name, value in websocket.headers.raw
            ],
            "offered_subprotocols": list(websocket.scope["subprotocols"]),
        }
        websocket_state["path_params"] = _json_safe(websocket.path_params)
        last_message: dict[str, Any] | None = None
        for action in actions:
            if action["action"] == "accept-preferred":
                selected = next(
                    (
                        protocol
                        for protocol in route_spec["preferred_subprotocols"]
                        if protocol in offered
                    ),
                    None,
                )
                headers = [
                    (name.encode("latin-1"), value.encode("latin-1"))
                    for name, value in action["headers"]
                ]
                await websocket.accept(subprotocol=selected, headers=headers)
            elif action["action"] == "receive":
                if action.get("pending") is True:
                    websocket_state["pending_requested"] = True
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    peer_close = {
                        "code": message["code"],
                        "reason": message.get("reason", ""),
                    }
                    websocket_state["peer_close"] = peer_close
                    websocket_state["messages"].append(
                        {"direction": "received", "peer_close": peer_close}
                    )
                elif "text" in message:
                    last_message = {"kind": "text", "value": message["text"]}
                    websocket_state["messages"].append(
                        {"direction": "received", "message": last_message}
                    )
                else:
                    payload = message.get("bytes", b"")
                    last_message = {
                        "kind": "binary",
                        "base64": base64.b64encode(payload).decode("ascii"),
                    }
                    websocket_state["messages"].append(
                        {"direction": "received", "message": last_message}
                    )
            elif action["action"] == "send-received":
                if last_message is None:
                    raise ValueError("send-received requires a prior data message")
                if last_message["kind"] == "text":
                    await websocket.send_text(last_message["value"])
                else:
                    await websocket.send_bytes(
                        base64.b64decode(last_message["base64"], validate=True)
                    )
                websocket_state["messages"].append({"direction": "sent", "message": last_message})
            elif action["action"] == "close":
                await websocket.close(code=action["code"], reason=action["reason"])
            elif action["action"] == "return-application-error":
                error_spec = action["error"]
                error = OSError(error_spec["message"])
                websocket_state["application_error"] = {
                    "kind": type(error).__name__,
                    "message": str(error),
                }
                raise error
            else:
                raise ValueError("unsupported native WebSocket action")

    from urllib.parse import urlsplit

    uri = urlsplit(handshake["uri"])
    path = uri.path or "/"
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "method": handshake["method"],
        "http_version": handshake["version"].replace("HTTP/", ""),
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": uri.query.encode("utf-8"),
        "root_path": "",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in handshake["headers"]
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("example.test", 80),
        "subprotocols": offered,
    }
    app = Starlette(routes=[WebSocketRoute(route_spec["path"], endpoint)])

    async def invoke() -> None:
        try:
            await app(scope, receive, send)
        except asyncio.CancelledError:
            raise
        except Exception:
            websocket_state["application_result_error_kind"] = "application"

    async def run() -> dict[str, Any]:
        app_task = asyncio.create_task(invoke())
        if cancellation is not None:
            await pending_receive_started.wait()
            app_task.cancel()
            try:
                await app_task
            except asyncio.CancelledError:
                websocket_state["application_result_error_kind"] = "cancelled"
        else:
            await app_task

        accept_message = websocket_state["accepted"]
        acceptance = None
        selected_subprotocol = None
        if accept_message is not None:
            selected_subprotocol = accept_message.get("subprotocol")
            acceptance = {
                "accepted": True,
                "subprotocol": selected_subprotocol,
                "headers": [
                    [key.decode("ascii").lower(), base64.b64encode(value).decode("ascii")]
                    for key, value in accept_message.get("headers", [])
                ],
            }
        application_error = websocket_state["application_error"]
        return {
            "handshake.acceptance": acceptance,
            "handshake.selected_subprotocol": selected_subprotocol,
            "session.handshake": websocket_state["handshake"],
            "session.path_params": websocket_state["path_params"],
            "session.messages": websocket_state["messages"],
            "session.close": websocket_state["close"],
            "session.peer_close": websocket_state["peer_close"],
            "application_error.kind": (
                application_error["kind"] if application_error is not None else None
            ),
            "application_error.message": (
                application_error["message"] if application_error is not None else None
            ),
            "application_result.error_kind": websocket_state["application_result_error_kind"],
            "transport.receive_cancelled": websocket_state["receive_cancelled"]
            and pending_receive_started.is_set(),
        }

    return _native_workflow_result(case, asyncio.run(run()))


def _run_native_lifespan_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "inputs",
            "observations",
        },
        "native lifespan case",
    )
    if case["surface"] != NATIVE_LIFESPAN_SURFACE or case["operation"] != NATIVE_LIFESPAN_OPERATION:
        raise ValueError("case is outside the native lifespan workflow")

    from starlette.applications import Starlette

    input_spec = case["inputs"]
    registrations = input_spec["registrations"]
    host_actions = input_spec["host_actions"]
    events: list[str] = []
    state: dict[str, Any] = {}
    observation: dict[str, Any] = {
        "state_before_shutdown": None,
        "startup_failure": None,
        "shutdown_failure": None,
        "phase": None,
    }

    async def apply_actions(actions: list[dict[str, Any]]) -> None:
        for action in actions:
            if "append-event" in action:
                events.append(action["append-event"])
            elif "insert-state" in action:
                item = action["insert-state"]
                state[item["key"]] = item["value"]
            elif "remove-state" in action:
                state.pop(action["remove-state"], None)
            elif "raise" in action:
                error_spec = action["raise"]
                exception_type = getattr(builtins, error_spec["exception"], None)
                if not isinstance(exception_type, type) or not issubclass(
                    exception_type, Exception
                ):
                    raise ValueError("unsupported input-defined lifespan exception")
                raise exception_type(error_spec["message"])
            elif action.get("suspend-until-host-release") is True:
                await asyncio.Future()
            else:
                raise ValueError("unsupported native lifespan callback action")

    def make_registration_context(
        registration_index: int, registration: dict[str, Any]
    ) -> Callable[..., Any]:
        @contextlib.asynccontextmanager
        async def registration_context(_app: Any) -> AsyncIterator[None]:
            try:
                await apply_actions(registration["startup"]["actions"])
            except Exception as exc:
                observation["startup_failure"] = {
                    "kind": "startup",
                    "hook_index": registration_index,
                    "registration": registration["name"],
                    "message": str(exc),
                    "rollback_failures": [],
                }
                raise
            try:
                yield
            finally:
                try:
                    await apply_actions(registration["shutdown"]["actions"])
                except Exception as exc:
                    failure = {
                        "hook_index": registration_index,
                        "registration": registration["name"],
                        "message": str(exc),
                    }
                    if observation["phase"] == "startup":
                        startup_failure = observation["startup_failure"]
                        if startup_failure is not None:
                            startup_failure["rollback_failures"].append(failure)
                    else:
                        shutdown_failure = observation["shutdown_failure"]
                        if shutdown_failure is None:
                            shutdown_failure = {"kind": "shutdown", "failures": []}
                            observation["shutdown_failure"] = shutdown_failure
                        shutdown_failure["failures"].append(failure)
                        raise

        return registration_context

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[dict[str, Any]]:
        async with contextlib.AsyncExitStack() as stack:
            for registration_index, registration in enumerate(registrations):
                context = make_registration_context(registration_index, registration)
                await stack.enter_async_context(context(_app))
            yield state

    app = Starlette(lifespan=lifespan)
    messages = []
    for action in host_actions:
        if action == "start-to-completion":
            messages.append({"type": "lifespan.startup"})
        elif action == "shutdown-to-completion":
            messages.append({"type": "lifespan.shutdown"})
    message_index = 0
    scope: dict[str, Any] = {
        "type": "lifespan",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "state": {},
    }

    async def receive() -> dict[str, Any]:
        nonlocal message_index
        if message_index >= len(messages):
            await asyncio.Future()
        message = messages[message_index]
        message_index += 1
        observation["phase"] = "startup" if message["type"] == "lifespan.startup" else "shutdown"
        return message

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "lifespan.startup.complete" and "observe-state" in host_actions:
            observation["state_before_shutdown"] = dict(scope.get("state", {}))

    async def invoke() -> None:
        try:
            await app(scope, receive, send)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if observation["phase"] == "startup":
                if observation["startup_failure"] is None:
                    observation["startup_failure"] = _native_error_value(exc)
            elif observation["phase"] == "shutdown":
                if observation["shutdown_failure"] is None:
                    observation["shutdown_failure"] = _native_error_value(exc)

    async def run() -> dict[str, Any]:
        await invoke()
        return {
            "lifecycle-event-sequence": events,
            "lifecycle-state-before-shutdown": observation["state_before_shutdown"],
            "startup-failure": observation["startup_failure"],
            "shutdown-failure": observation["shutdown_failure"],
        }

    return _native_workflow_result(case, asyncio.run(run()))


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


def _websocket_state_name(state: Any) -> Any:
    name = getattr(state, "name", None)
    if isinstance(name, str):
        return name
    if type(state) is int:
        return state
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
    from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    incoming_index = 0
    receive_calls = 0
    pending_send_error: dict[str, Any] | None = None

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index, receive_calls
        receive_calls += 1
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
                elif action["action"] == "accept":
                    await websocket.accept()
                elif action["action"] == "send":
                    pending_send_error = action.get("send_error")
                    try:
                        await websocket.send(_materialize_websocket_message(action["message"]))
                    finally:
                        pending_send_error = None
                elif action["action"] == "set-client-state":
                    websocket.client_state = WebSocketState[action["state"]]
                elif action["action"] == "set-client-state-raw":
                    websocket.client_state = action["value"]
                elif action["action"] == "set-application-state":
                    websocket.application_state = WebSocketState[action["state"]]
                elif action["action"] == "set-application-state-raw":
                    websocket.application_state = action["value"]
                else:
                    raise ValueError(
                        "unsupported state-sequence action; only accept, raw receive/send, and state assignments are declared"
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
        "receive_calls": receive_calls,
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


class _WebSocketEndpointJSONDecoderLookupFailure:
    def __init__(self, message: str) -> None:
        self.message = message

    def __getattr__(self, name: str) -> Any:
        if name == "JSONDecodeError":
            raise RuntimeError(self.message)
        raise AttributeError(name)


class _WebSocketEndpointCaptureSend:
    def __init__(
        self,
        messages: list[dict[str, Any]],
        failure: dict[str, Any] | None = None,
    ) -> None:
        self.messages = messages
        self.failure = failure

    async def __call__(self, message: dict[str, Any]) -> None:
        if self.failure is not None and message.get("type") == self.failure["message_type"]:
            raise OSError(self.failure["message"])
        self.messages.append(dict(message))


def _websocket_endpoint_accept_hook(spec: dict[str, Any], calls: list[dict[str, Any]]) -> Any:
    async def on_connect(_endpoint: Any, websocket: Any) -> None:
        call: dict[str, Any] = {"hook": "on_connect"}
        if spec["observe_scope_subprotocols"]:
            call["scope_subprotocols"] = list(websocket.scope["subprotocols"])
        calls.append(call)
        await websocket.accept(subprotocol=spec["subprotocol"])

    return on_connect


def _websocket_endpoint_connect_error_hook(
    spec: dict[str, Any], calls: list[dict[str, Any]]
) -> Any:
    async def on_connect(_endpoint: Any, _websocket: Any) -> None:
        calls.append({"hook": "on_connect"})
        raise ValueError(spec["message"])

    return on_connect


def _websocket_endpoint_receive_hook(spec: dict[str, Any], calls: list[dict[str, Any]]) -> Any:
    if spec["kind"] == "raise-stop-iteration-synchronously":

        def on_receive(_endpoint: Any, _websocket: Any, data: Any) -> None:
            calls.append({"hook": "on_receive", "data": _json_safe(data)})
            raise StopIteration(spec["message"])

        return on_receive

    prefix = (
        _decode_base64(spec["prefix_base64"], "WebSocketEndpoint.on_receive.prefix_base64")
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
        elif spec["kind"] == "delete-internal-error-close-code-and-raise-value-error":
            from starlette import status

            delattr(status, "WS_1011_INTERNAL_ERROR")
            raise ValueError(spec["message"])
        else:
            await websocket.send_json({spec["key"]: data}, mode=spec["mode"])

    return on_receive


def _websocket_endpoint_disconnect_hook(
    spec: dict[str, Any], calls: list[dict[str, Any]], cancellation_ready: asyncio.Event
) -> Any:
    if spec["kind"] == "record-active-exception":

        def on_disconnect(_endpoint: Any, _websocket: Any, close_code: int) -> Any:
            active_exception = sys.exception()
            calls.append(
                {
                    "hook": "on_disconnect",
                    "close_code": close_code,
                    "active_exception": (
                        None
                        if active_exception is None
                        else {
                            "class": (
                                f"{type(active_exception).__module__}."
                                f"{type(active_exception).__qualname__}"
                            ),
                            "message": str(active_exception),
                        }
                    ),
                }
            )
            return asyncio.sleep(0)

        return on_disconnect

    if spec["kind"] == "raise-runtime-error-synchronously":

        def on_disconnect(_endpoint: Any, _websocket: Any, close_code: int) -> None:
            calls.append({"hook": "on_disconnect", "close_code": close_code})
            raise RuntimeError(spec["message"])

        return on_disconnect

    if spec["kind"] == "wait-for-cancellation":

        async def on_disconnect(_endpoint: Any, _websocket: Any, close_code: int) -> None:
            calls.append({"hook": "on_disconnect", "close_code": close_code})
            cancellation_ready.set()
            await asyncio.Future()

        return on_disconnect

    async def on_disconnect(_endpoint: Any, websocket: Any, close_code: int) -> None:
        calls.append({"hook": "on_disconnect", "close_code": close_code})
        if spec["kind"] == "raise-runtime-error":
            raise RuntimeError(spec["message"])
        if spec["kind"] == "raise-runtime-error-from-value-error":
            try:
                raise ValueError(spec["context_message"])
            except ValueError:
                # Preserve implicit context without setting an explicit cause.
                raise RuntimeError(spec["message"])  # noqa: B904
        await websocket.close(code=close_code)

    return on_disconnect


def _websocket_endpoint_error(
    exc: BaseException,
    *,
    include_context_chain: bool = False,
) -> dict[str, Any]:
    result = _dispatch_error(exc)
    context = exc.__context__
    result["context"] = (
        {
            "class": f"{type(context).__module__}.{type(context).__qualname__}",
            "message": str(context),
        }
        if context is not None
        else None
    )
    if include_context_chain:
        context_chain: list[dict[str, str]] = []
        seen: set[int] = set()
        while context is not None and id(context) not in seen:
            seen.add(id(context))
            context_chain.append(
                {
                    "class": f"{type(context).__module__}.{type(context).__qualname__}",
                    "message": str(context),
                }
            )
            context = context.__context__
        result["context_chain"] = context_chain
    return result


async def _await_websocket_endpoint(
    endpoint_type: Any,
    scope: dict[str, Any],
    receive: Any,
    send: Any,
    endpoint_constructed: list[bool] | None = None,
) -> None:
    endpoint = endpoint_type(scope, receive, send)
    if endpoint_constructed is not None:
        endpoint_constructed.append(True)
    await endpoint


async def _await_cancelled_websocket_endpoint(
    endpoint_type: Any,
    scope: dict[str, Any],
    receive: _WebSocketEndpointInputReceive,
    send: Any,
    cancellation_ready: asyncio.Event,
    endpoint_constructed: list[bool],
) -> dict[str, Any] | None:
    task = asyncio.create_task(
        _await_websocket_endpoint(endpoint_type, scope, receive, send, endpoint_constructed)
    )
    await cancellation_ready.wait()
    task.cancel()
    try:
        await task
    except (Exception, asyncio.CancelledError) as exc:
        # A finalizer error replaces cancellation and is the task's result.
        return _websocket_endpoint_error(exc)
    return None


def _websocket_endpoint_encoding(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if value.get("kind") == "stateful-property":
        values = tuple(value["values"])
        reads = 0

        def get_encoding(_endpoint: Any) -> str:
            nonlocal reads
            index = reads
            reads += 1
            return values[min(index, len(values) - 1)]

        return property(get_encoding)
    if value.get("kind") == "stop-iteration-str-subclass-equality":
        message = value["message"]

        class InputStopIterationEncoding(str):
            def __eq__(self, other: object) -> bool:
                raise StopIteration(message)

        return InputStopIterationEncoding(value["value"])
    if value.get("kind") != "formatted-str-subclass":
        return value
    format_value = value["format_value"]

    class InputFormattedEncoding(str):
        def __new__(cls, text: str) -> InputFormattedEncoding:
            instance = super().__new__(cls, text)
            instance.format_value = format_value
            return instance

        def __format__(self, format_spec: str) -> str:
            if not format_spec:
                return self.format_value
            return str.__format__(self, format_spec)

    return InputFormattedEncoding(value["value"])


def _run_websocket_endpoint_case(case: dict[str, Any]) -> dict[str, Any]:
    case_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "endpoint",
        "sessions",
        "observations",
    }
    if "send" in case:
        case_fields.add("send")
    if "python_optimization" in case:
        case_fields.add("python_optimization")
    _exact_object(
        case,
        case_fields,
        "WebSocketEndpoint dispatch case",
    )
    if (
        case["surface"] != WEBSOCKET_ENDPOINT_SURFACE
        or case["operation"] != WEBSOCKET_ENDPOINT_OPERATION
    ):
        raise ValueError("workflow is outside the declared WebSocketEndpoint dispatch operation")
    if case["observations"] != [WEBSOCKET_ENDPOINT_OPERATION]:
        raise ValueError("WebSocketEndpoint observations must select the dispatch workflow")
    from starlette import status
    from starlette.endpoints import WebSocketEndpoint

    endpoint_module = sys.modules[WebSocketEndpoint.__module__]
    internal_error_close_code = status.WS_1011_INTERNAL_ERROR
    send_failure = case.get("send")
    if send_failure is not None:
        _exact_object(
            send_failure,
            {"kind", "message_type", "message"},
            "WebSocketEndpoint send input",
        )
        if (
            send_failure["kind"] != "raise-oserror"
            or send_failure["message_type"] != "websocket.close"
        ):
            raise ValueError("WebSocketEndpoint send kind is unsupported")

    endpoint_spec = case["endpoint"]
    connection_results: list[dict[str, Any]] = []
    for session_spec in case["sessions"]:
        scope = _make_websocket_scope(session_spec["scope"])
        incoming = tuple(
            _materialize_websocket_message(message) for message in session_spec["incoming"]
        )
        hook_calls: list[dict[str, Any]] = []
        sent_messages: list[dict[str, Any]] = []
        cancellation_ready = asyncio.Event()
        methods: dict[str, Any] = {
            "encoding": _websocket_endpoint_encoding(endpoint_spec["encoding"])
        }

        if endpoint_spec["on_connect"]["kind"] == "accept":
            methods["on_connect"] = _websocket_endpoint_accept_hook(
                endpoint_spec["on_connect"], hook_calls
            )
        elif endpoint_spec["on_connect"]["kind"] == "raise-value-error":
            methods["on_connect"] = _websocket_endpoint_connect_error_hook(
                endpoint_spec["on_connect"], hook_calls
            )

        on_receive_spec = endpoint_spec["on_receive"]
        if on_receive_spec["kind"] != "no-op":
            methods["on_receive"] = _websocket_endpoint_receive_hook(on_receive_spec, hook_calls)

        if endpoint_spec["on_disconnect"]["kind"] in {
            "record-and-close",
            "record-active-exception",
            "raise-runtime-error",
            "raise-runtime-error-synchronously",
            "raise-runtime-error-from-value-error",
            "wait-for-cancellation",
        }:
            methods["on_disconnect"] = _websocket_endpoint_disconnect_hook(
                endpoint_spec["on_disconnect"], hook_calls, cancellation_ready
            )

        endpoint_type = type("InputWebSocketEndpoint", (WebSocketEndpoint,), methods)
        endpoint_constructed: list[bool] = []
        receive = _WebSocketEndpointInputReceive(
            incoming, cancel_on_exhaustion=session_spec.get("cancel_at") == "receive"
        )
        if session_spec.get("cancel_at") == "receive":
            receive.waiting = cancellation_ready
        send = _WebSocketEndpointCaptureSend(sent_messages, send_failure)
        json_module: Any | None = None
        original_json_decoder: Any = None

        try:
            json_decoder_lookup = endpoint_spec.get("json_decoder_lookup")
            if json_decoder_lookup is not None:
                json_module = endpoint_module.json
                original_json_decoder = json_module.decoder
                json_module.decoder = _WebSocketEndpointJSONDecoderLookupFailure(
                    json_decoder_lookup["message"]
                )
            if session_spec.get("cancel_at") in {"receive", "disconnect"}:
                error = asyncio.run(
                    _await_cancelled_websocket_endpoint(
                        endpoint_type,
                        scope,
                        receive,
                        send,
                        cancellation_ready,
                        endpoint_constructed,
                    )
                )
            else:
                error: dict[str, Any] | None = None
                try:
                    asyncio.run(
                        _await_websocket_endpoint(
                            endpoint_type, scope, receive, send, endpoint_constructed
                        )
                    )
                except Exception as exc:
                    error = _websocket_endpoint_error(
                        exc,
                        include_context_chain=send_failure is not None,
                    )
        finally:
            if json_module is not None:
                json_module.decoder = original_json_decoder
            if on_receive_spec["kind"] == "delete-internal-error-close-code-and-raise-value-error":
                status.WS_1011_INTERNAL_ERROR = internal_error_close_code
        if (
            endpoint_constructed
            and receive.index != len(incoming)
            and endpoint_spec["on_connect"]["kind"] != "raise-value-error"
        ):
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
    _exact_object(
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
    endpoint_keys = {"kind", "handlers"}
    if "method_reads" in endpoint_spec:
        endpoint_keys.add("method_reads")
    _exact_object(endpoint_spec, endpoint_keys, "HTTP class endpoint input")
    if endpoint_spec["kind"] != "http-class-based-endpoint":
        raise ValueError("HTTPEndpoint input must define an HTTP class endpoint")
    handler_specs: dict[str, dict[str, Any]] = {}
    for handler_spec in endpoint_spec["handlers"]:
        _exact_object(
            handler_spec, {"name", "call_style", "response"}, "HTTP class endpoint handler"
        )
        response_spec = handler_spec["response"]
        _exact_object(
            response_spec,
            {"kind", "content", "status_code", "media_type"},
            "HTTP class endpoint response",
        )
        if response_spec["kind"] != "plain-text-response":
            raise ValueError("HTTPEndpoint direct handlers must return plain-text responses")
        handler_specs[handler_spec["name"]] = handler_spec

    def make_response(response_spec: dict[str, Any]) -> Any:
        return PlainTextResponse(
            content=response_spec["content"],
            status_code=response_spec["status_code"],
            media_type=response_spec["media_type"],
        )

    class_attributes: dict[str, Any] = {}
    for name, handler_spec in handler_specs.items():
        response_spec = handler_spec["response"]
        if handler_spec["call_style"] == "sync":

            def handler(
                _self: Any,
                _request: Any,
                response_spec: dict[str, Any] = response_spec,
            ) -> Any:
                return make_response(response_spec)
        else:

            async def handler(
                _self: Any,
                _request: Any,
                response_spec: dict[str, Any] = response_spec,
            ) -> Any:
                return make_response(response_spec)

        class_attributes[name] = handler

    endpoint_type = type("InputHTTPEndpoint", (HTTPEndpoint,), class_attributes)
    scope = _make_scope(case["scope"])
    method_trace: list[str] = []
    if "method_reads" in endpoint_spec:
        method_values = endpoint_spec["method_reads"]

        class InputScope(dict):
            def __getitem__(self, key: Any) -> Any:
                if key == "method":
                    value = method_values[min(len(method_trace), len(method_values) - 1)]
                    method_trace.append(value)
                    return value
                return super().__getitem__(key)

        scope = InputScope(scope)
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
    if "method_reads" in endpoint_spec:
        observation["method_reads"] = method_trace
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": HTTP_ENDPOINT_OPERATION, "status": "ok", "value": observation}
        ],
    }


def _run_websocket_convenience_case(case: dict[str, Any]) -> dict[str, Any]:
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
        }
        | (
            {
                "constructor_thread",
                "iterator_thread",
                "receive_callback_actions",
                "method_descriptors",
                "scope_container",
            }
            & case.keys()
        ),
        "WebSocket convenience-sequence case",
    )
    if case["surface"] != WEBSOCKET_SURFACE or case["operation"] != WEBSOCKET_CONVENIENCE_OPERATION:
        raise ValueError(
            "WebSocket workflow is outside the declared convenience-sequence operation"
        )
    import builtins

    from starlette.responses import FileResponse, Response, StreamingResponse
    from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

    incoming = [_materialize_websocket_message(message) for message in case["incoming"]]
    receive_callback_actions = {
        action["receive_index"]: action["assign_client_state"]
        for action in case.get("receive_callback_actions", [])
    }
    incoming_index = 0
    callback_tape: list[dict[str, Any]] = []
    pending_send_error: dict[str, Any] | None = None
    file_response_directory: tempfile.TemporaryDirectory[str] | None = None
    iterator_control_cache: dict[str, Any] = {}
    method_descriptors = case.get("method_descriptors", {})
    method_descriptor_reads: list[dict[str, Any]] = []
    method_descriptor_counts: dict[str, int] = {}
    websocket: Any = None

    def record_descriptor_read(attribute: str, instance: Any) -> str:
        descriptor = method_descriptors[attribute]
        if attribute == "send":
            state = _websocket_state_name(instance.client_state)
            selected = descriptor["by_client_state"][state]
            method_descriptor_reads.append(
                {"attribute": attribute, "state": state, "selected": selected}
            )
            return selected
        read_index = method_descriptor_counts.get(attribute, 0)
        labels = descriptor["read_labels"]
        if read_index >= len(labels):
            raise ValueError(f"WebSocket {attribute} descriptor read exceeded its input labels")
        method_descriptor_counts[attribute] = read_index + 1
        selected = labels[read_index]
        method_descriptor_reads.append(
            {"attribute": attribute, "read_index": read_index, "selected": selected}
        )
        return selected

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index >= len(incoming):
            raise ValueError("WebSocket receive action exhausted its input-only message sequence")
        receive_index = incoming_index
        message = incoming[incoming_index]
        incoming_index += 1
        if receive_index in receive_callback_actions:
            await asyncio.sleep(0)
            websocket.client_state = WebSocketState[receive_callback_actions[receive_index]]
        callback_tape.append(
            {"direction": "receive", "message": _canonical_websocket_message(message)}
        )
        return message

    def send(message: dict[str, Any]) -> Any:
        callback_tape.append(
            {"direction": "send", "message": _canonical_websocket_message(message)}
        )
        send_error = pending_send_error
        if send_error is not None and send_error.get("timing", "await") == "call":
            raise OSError(send_error["message"])

        async def complete_send() -> None:
            if send_error is not None:
                raise OSError(send_error["message"])

        return complete_send()

    def construct() -> Any:
        scope = _make_websocket_scope(case["scope"])
        if not method_descriptors:
            return WebSocket(scope, receive, send)
        descriptor_members: dict[str, Any] = {"__module__": WebSocket.__module__}
        if "scope" in method_descriptors:

            def scope_descriptor(instance: Any) -> Any:
                record_descriptor_read("scope", instance)
                return WebSocket.scope.fget(instance)

            def set_scope_descriptor(instance: Any, value: Any) -> None:
                WebSocket.scope.fset(instance, value)

            descriptor_members["scope"] = property(scope_descriptor, set_scope_descriptor)
        if "receive" in method_descriptors:

            def receive_descriptor(instance: Any) -> Any:
                record_descriptor_read("receive", instance)
                return WebSocket.receive.__get__(instance, type(instance))

            descriptor_members["receive"] = property(receive_descriptor)
        for attribute in ("receive_text", "receive_bytes", "receive_json"):
            if attribute in method_descriptors:

                def typed_receive_descriptor(instance: Any, name: str = attribute) -> Any:
                    record_descriptor_read(name, instance)
                    error = method_descriptors[name].get("raises")
                    if error is not None:
                        exception_type = getattr(builtins, error["exception_type"])
                        raise exception_type(error["message"])
                    return getattr(WebSocket, name).__get__(instance, type(instance))

                descriptor_members[attribute] = property(typed_receive_descriptor)
        if "send" in method_descriptors:

            def send_descriptor(instance: Any) -> Any:
                selected = record_descriptor_read("send", instance)

                async def selected_send(message: dict[str, Any]) -> None:
                    method_descriptor_reads.append({"attribute": "send.call", "selected": selected})
                    await WebSocket.send(instance, message)

                return selected_send

            descriptor_members["send"] = property(send_descriptor)
        input_websocket_type = type("InputDefinedWebSocket", (WebSocket,), descriptor_members)
        return input_websocket_type(scope, receive, send)

    if case.get("constructor_thread", "caller") == "worker":
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            websocket = executor.submit(construct).result()
    else:
        websocket = construct()

    def create_iterator(method: str) -> Any:
        if case.get("iterator_thread", "caller") == "worker":
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(getattr(websocket, method)).result()
        return getattr(websocket, method)()

    def decode_athrow_argument(argument: dict[str, Any]) -> Any:
        kind = argument["kind"]
        if kind == "exception-class":
            exception_class_name = argument["name"]
            return (
                WebSocketDisconnect
                if exception_class_name == "WebSocketDisconnect"
                else getattr(builtins, exception_class_name)
            )
        if kind == "exception-instance":
            exception_class_name = argument["name"]
            exception_message = argument["message"]
            exception_class = (
                WebSocketDisconnect
                if exception_class_name == "WebSocketDisconnect"
                else getattr(builtins, exception_class_name)
            )
            return (
                WebSocketDisconnect(reason=exception_message)
                if exception_class_name == "WebSocketDisconnect"
                else exception_class(exception_message)
            )
        if kind == "value":
            return argument["value"]
        return None

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
                                    _decode_base64(pair[0], "WebSocket accept header name"),
                                    _decode_base64(pair[1], "WebSocket accept header value"),
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
                    kwargs = (
                        {"mode": materialize_websocket_json_mode(arguments["mode"])}
                        if "mode" in arguments
                        else {}
                    )
                    value = await websocket.receive_json(**kwargs)
                elif method in {"send_text", "send_json", "close"}:
                    kwargs = dict(arguments)
                    if method == "send_json":
                        if "data" in kwargs:
                            kwargs["data"] = materialize_websocket_json_payload(kwargs["data"])
                        if "mode" in kwargs:
                            kwargs["mode"] = materialize_websocket_json_mode(kwargs["mode"])
                    value = await getattr(websocket, method)(**kwargs)
                elif method == "send_bytes":
                    value = await websocket.send_bytes(
                        _decode_base64(arguments["data_base64"], "WebSocket send_bytes.data")
                    )
                elif method == "iter_text" or method == "iter_bytes" or method == "iter_json":
                    iterator = create_iterator(method)
                    values = []
                    async for item in iterator:
                        values.append(item)
                    value = values
                elif method == "iterator-probe":
                    iterator = create_iterator(arguments["iterator"])
                    value = {
                        attribute: hasattr(iterator, attribute)
                        for attribute in arguments["attributes"]
                    }
                elif method == "iterator-control":
                    iterator_method = arguments["iterator"]
                    iterator = iterator_control_cache.get(iterator_method)
                    if iterator is None:
                        iterator = create_iterator(iterator_method)
                        iterator_control_cache[iterator_method] = iterator
                    control = arguments["control"]
                    if control == "asend":
                        value = await iterator.asend(arguments["value"])
                    elif control == "athrow":
                        throw_arguments = [
                            decode_athrow_argument(argument)
                            for argument in arguments["throw_arguments"]
                        ]
                        throw_keywords = {
                            name: decode_athrow_argument(argument)
                            for name, argument in arguments.get(
                                "throw_keyword_arguments", {}
                            ).items()
                        }
                        value = await iterator.athrow(*throw_arguments, **throw_keywords)
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
                                yield _decode_base64(chunk, "WebSocket denial stream chunk")

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
                            _decode_base64(
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
                            _decode_base64(pair[0], "WebSocket denial response header name").decode(
                                "latin-1"
                            ): _decode_base64(
                                pair[1], "WebSocket denial response header value"
                            ).decode("latin-1")
                            for pair in header_pairs
                        }
                        response = Response(
                            content=_decode_base64(
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
        "method_descriptor_reads": method_descriptor_reads,
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
    case_fields = {
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
    }
    if "scope_container" in case:
        case_fields.add("scope_container")
    _exact_object(
        case,
        case_fields,
        "WebSocketRoute route-dispatch case",
    )
    if case["surface"] != WEBSOCKET_ROUTE_SURFACE or case["operation"] != WEBSOCKET_ROUTE_OPERATION:
        raise ValueError("workflow is outside the declared WebSocketRoute route-dispatch operation")
    from starlette.applications import Starlette
    from starlette.exceptions import WebSocketException
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
            elif action["action"] == "raise-websocket-exception":
                raise WebSocketException(code=action["code"], reason=action["reason"])
            else:
                raise ValueError(
                    f"unsupported WebSocketRoute endpoint action: {action['action']!r}"
                )

    middleware = []
    for middleware_spec in case["route"].get("middleware", []):
        if middleware_spec["kind"] == "append-websocket-accept-header":
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
        elif middleware_spec["kind"] == "catch-websocket-exception-with-close":
            code = middleware_spec["code"]
            reason = middleware_spec["reason"]

            class CatchWebSocketExceptionMiddleware:
                def __init__(self, app: Any, close_code: int, close_reason: str) -> None:
                    self.app = app
                    self.close_code = close_code
                    self.close_reason = close_reason

                async def __call__(self, middleware_scope: Any, receive: Any, send: Any) -> None:
                    try:
                        await self.app(middleware_scope, receive, send)
                    except WebSocketException:
                        await send(
                            {
                                "type": "websocket.close",
                                "code": self.close_code,
                                "reason": self.close_reason,
                            }
                        )

            middleware.append(
                Middleware(
                    CatchWebSocketExceptionMiddleware,
                    close_code=code,
                    close_reason=reason,
                )
            )

    route = WebSocketRoute(case["route"]["path"], endpoint=endpoint, middleware=middleware)
    app = Starlette(routes=[route])
    scope_spec = case["scope"]
    scope_type_value = (
        _materialize_scope_type_spec(scope_spec["type"])[1]
        if "type" in scope_spec
        else "websocket"
        if "subprotocols" in scope_spec
        else ""
    )
    scope = (
        _make_websocket_scope(scope_spec)
        if scope_type_value == "websocket"
        else _make_scope(scope_spec)
    )
    scope = _scope_container(scope, case.get("scope_container", "dict"))
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

    async def dispatch() -> BaseException | None:
        try:
            if case["dispatch"] == "application":
                await app(scope, receive, send)
            elif case["dispatch"] == "standalone-route":
                await route(scope, receive, send)
            else:
                raise ValueError(f"unsupported WebSocketRoute dispatch kind: {case['dispatch']!r}")
        except Exception as exc:
            return exc
        return None

    captured_error = asyncio.run(dispatch())
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
    route_scope_observation = {
        "app_is_application": scope.get("app") is app,
        "router_is_application_router": scope.get("router") is app.router,
        "endpoint_is_route_endpoint": scope.get("endpoint") is endpoint,
        "path_params_present": "path_params" in scope,
        "path_params": _json_safe(scope.get("path_params")),
    }
    if "scope_container" in case:
        route_scope_observation["mapping_operations"] = list(
            getattr(scope, "parity_operations", [])
        )
    available = {
        "route_scope": route_scope_observation,
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
    observation = _workflow_observation(
        WEBSOCKET_ROUTE_OPERATION,
        _CapturedDispatchError(_dispatch_error(captured_error), available)
        if captured_error is not None
        else available,
    )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [observation],
    }


def _run_http_route_call_case(case: dict[str, Any]) -> dict[str, Any]:
    expected_fields = set(HTTP_ROUTE_CALL_CASE_KEYS)
    if "observe_dispatch_error" in case:
        expected_fields.add("observe_dispatch_error")
    _exact_object(case, expected_fields, "Route __call__ case")
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
    incoming = [_make_message(message) for message in case["incoming"]]
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

    captured_error: Exception | None = None
    try:
        asyncio.run(route(scope, receive, send))
    except Exception as exc:
        if case.get("observe_dispatch_error") is not True:
            raise
        captured_error = exc
    if captured_error is None and incoming_index != len(incoming):
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
            "path_params": {
                name: {"value": _json_safe(value), "type": type(value).__name__}
                for name, value in scope.get("path_params", {}).items()
            },
        },
        "asgi_events": [_canonical_message(message) for message in sent_messages],
        "response_status": response_start["status"] if response_start is not None else None,
        "response_bytes": (
            {"encoding": "base64", "data": base64.b64encode(response_body).decode("ascii")}
            if response_start is not None
            else None
        ),
    }
    observed_value: Any = available
    if captured_error is not None:
        observed_value = _CapturedDispatchError(_dispatch_error(captured_error), available)
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [_workflow_observation(HTTP_ROUTE_CALL_OPERATION, observed_value)],
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

    lifespan_scope = _make_scope(lifecycle_arguments["scope"])
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
    lifecycle_arguments: dict[str, Any],
    lifecycle_trace: list[str],
    scope_container: str | dict[str, Any] = "dict",
    scope_observation: dict[str, Any] | None = None,
) -> dict[str, Any] | _CapturedDispatchError:
    """Run one complete lifecycle input with callback-call failures intact."""
    if lifecycle_arguments["scope"].get("type") != "lifespan":
        raise ValueError("the lifecycle workflow step must use a lifespan scope")
    if lifecycle_arguments["send"].get("kind") not in {
        "capture-asgi-send",
        "raise-on-call",
        "raise-on-await",
    }:
        raise ValueError("send input must select a declared lifecycle callback")

    actions = lifecycle_arguments["receive"]
    action_index = 0
    send_spec = lifecycle_arguments["send"]
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
        return resolved(_make_message(action["message"]))

    async def record_send(message: dict[str, Any]) -> None:
        workflow_events.append(_canonical_message(message))

    async def raise_on_await(error: BaseException) -> None:
        raise error

    def send_lifecycle(message: dict[str, Any]) -> Any:
        if (
            send_spec["kind"] in {"raise-on-call", "raise-on-await"}
            and message.get("type") == send_spec["message_type"]
        ):
            import builtins

            exception_type = getattr(builtins, send_spec["exception_type"])
            if "exception_class_override" in send_spec:
                reported_class = getattr(builtins, send_spec["exception_class_override"])

                def class_override(_exception: BaseException) -> type[BaseException]:
                    return reported_class

                exception_type = type(
                    f"InputDefined{exception_type.__name__}",
                    (exception_type,),
                    {
                        "__class__": property(class_override),
                        "__module__": exception_type.__module__,
                    },
                )
            error = exception_type(send_spec["message"])
            if send_spec["kind"] == "raise-on-call":
                raise error
            return raise_on_await(error)
        return record_send(message)

    scope = _make_scope(lifecycle_arguments["scope"], scope_container)
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
    if scope_observation is not None:
        value["scope_observation"] = _scope_observation(scope, scope_observation)
    if captured_exception is None:
        return value
    error = _dispatch_error(captured_exception)
    if send_spec.get("observe_context_chain", False):
        error["context_chain"] = _exception_context_chain(captured_exception)
    error["stage"] = "lifespan"
    return _CapturedDispatchError(error=error, partial_value=value)


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
    garbage_collection = case.get("garbage_collection")
    if garbage_collection is None:
        return _run_route_dispatch_case_inner(case, None)

    from scripts.parity.adapters.ownership_cleanup import observe_ownership
    from scripts.parity.adapters.traceback_cleanup import TracebackCleanup

    with TracebackCleanup(garbage_collection) as gc_observer:
        return _run_route_dispatch_case_inner(case, gc_observer, observe_ownership)


def _run_route_dispatch_case_inner(
    case: dict[str, Any], gc_observer: Any, observe_ownership: Any = None
) -> dict[str, Any]:
    from datetime import datetime

    from starlette.convertors import Convertor, register_url_convertor
    from starlette.endpoints import HTTPEndpoint
    from starlette.responses import JSONResponse, PlainTextResponse, Response
    from starlette.routing import BaseRoute, Host, Match, Mount, Route, Router, WebSocketRoute

    for spec in case.get("custom_convertors", []):

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

    route_index_observations: list[int] = []
    gc_endpoint_instances: list[Any] = []
    router_sequence = case.get("surface") == "starlette.routing.Router" and "steps" in case
    garbage_collection = case.get("garbage_collection")

    def make_http_route(route_spec: dict[str, Any], endpoint: Any) -> Any:
        instance_match_override = route_spec.get("instance_match_override")
        route_type = Route
        if instance_match_override is not None:
            override_kind = instance_match_override.get("kind")
            override_keys = (
                {"kind", "message"} if override_kind == "raise-runtime-error" else {"kind"}
            )
            _exact_object(instance_match_override, override_keys, "route instance matcher override")
            if override_kind not in {"none", "raise-runtime-error"}:
                raise ValueError("route instance matcher override kind is unsupported")

            class InputRoute(Route):
                pass

            route_type = InputRoute

        route = route_type(
            route_spec["path"],
            endpoint=endpoint,
            methods=route_spec["methods"],
            max_body_size=route_spec.get("max_body_size"),
        )
        if instance_match_override is not None:
            if override_kind == "none":

                def instance_matches(_scope: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
                    return Match.NONE, {}

            else:
                error_message = instance_match_override["message"]

                def instance_matches(
                    _scope: dict[str, Any], message: str = error_message
                ) -> tuple[Any, dict[str, Any]]:
                    raise RuntimeError(message)

            route.matches = instance_matches
        return route

    def make_route(route_spec: dict[str, Any], route_index: int) -> Any:
        if route_spec.get("kind") == "websocket-route":
            route_spec = _exact_object(
                route_spec,
                {"kind", "path", "endpoint_actions"},
                "WebSocket route input",
            )
            endpoint_actions = route_spec["endpoint_actions"]

            async def websocket_endpoint(
                websocket: Any,
                actions: list[dict[str, Any]] = endpoint_actions,
                observed_route_index: int = route_index,
            ) -> None:
                route_index_observations.append(observed_route_index)
                for action in actions:
                    if action["action"] == "accept":
                        await websocket.accept(subprotocol=action["subprotocol"])
                    elif action["action"] == "send_text":
                        await websocket.send_text(action["text"])
                    else:
                        await websocket.close(code=action["code"], reason=action["reason"])

            return WebSocketRoute(route_spec["path"], websocket_endpoint)

        if route_spec.get("kind") == "base-route-subclass":
            response_spec = route_spec["endpoint"]

            class InputBaseRoute(BaseRoute):
                def __init__(self) -> None:
                    self.path = route_spec["path"]

                def matches(self, scope: Any) -> tuple[Match, dict[str, Any]]:
                    if scope["path"] != route_spec["match_scope_path"]:
                        return Match.NONE, {}
                    if "match_error" in route_spec:
                        raise RuntimeError(route_spec["match_error"])
                    path_params = dict(scope.get("path_params", {}))
                    path_params.update(route_spec["path_params"])
                    return Match.FULL, {"path_params": path_params}

                async def handle(self, scope: Any, receive: Any, send: Any) -> None:
                    route_index_observations.append(route_index)
                    await PlainTextResponse(
                        content=response_spec["content"],
                        status_code=response_spec["status_code"],
                        media_type=response_spec["media_type"],
                    )(scope, receive, send)

            return InputBaseRoute()

        response_spec = route_spec["endpoint"]
        if garbage_collection is not None:
            _exact_object(
                response_spec,
                {"kind", "content", "status_code", "media_type", "cookies"},
                "Router GC endpoint response",
            )

            class CachedRouteCycleEndpoint:
                def __init__(self) -> None:
                    self.router: Any = None
                    if gc_observer is None:
                        raise RuntimeError("Router GC observer was not installed")
                    self.guard = gc_observer.guard(garbage_collection["guard_label"])

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    route_index_observations.append(route_index)
                    response = PlainTextResponse(
                        content=response_spec["content"],
                        status_code=response_spec["status_code"],
                        media_type=response_spec["media_type"],
                    )
                    await response(scope, receive, send)

            gc_endpoint_instances.append(CachedRouteCycleEndpoint())
            return make_http_route(route_spec, gc_endpoint_instances[-1])

        if response_spec.get("kind") in {"starlette-response", "json-response"}:

            async def fixed_response_endpoint(_request: Any) -> Any:
                route_index_observations.append(route_index)
                if response_spec["kind"] == "json-response":
                    return JSONResponse(
                        response_spec["content"], status_code=response_spec["status_code"]
                    )
                return Response(
                    content=response_spec["content"],
                    status_code=response_spec["status_code"],
                    media_type=response_spec["media_type"],
                )

            return make_http_route(route_spec, fixed_response_endpoint)
        if response_spec.get("kind") == "request-body-echo":
            _exact_object(response_spec, {"kind"}, "request-body echo endpoint")

            async def endpoint(request: Any) -> Any:
                route_index_observations.append(route_index)
                return Response(await request.body())

            return make_http_route(route_spec, endpoint)

        if response_spec.get("kind") == "http-class-based-endpoint":
            if set(response_spec) != {"kind", "handlers"}:
                raise ValueError("HTTP class endpoint input has unsupported fields")

            def make_class_response(request: Any, class_response_spec: dict[str, Any]) -> Any:
                kind = class_response_spec["kind"]
                if kind == "plain-text-response":
                    if set(class_response_spec) != {
                        "kind",
                        "content",
                        "status_code",
                        "media_type",
                    }:
                        raise ValueError("HTTP class endpoint response has unsupported fields")
                    content = class_response_spec["content"]
                elif kind == "path-parameter-text-response":
                    if set(class_response_spec) != {
                        "kind",
                        "path_parameter",
                        "prefix",
                        "suffix",
                        "status_code",
                        "media_type",
                    }:
                        raise ValueError("HTTP class endpoint path response has unsupported fields")
                    content = (
                        class_response_spec["prefix"]
                        + str(request.path_params[class_response_spec["path_parameter"]])
                        + class_response_spec["suffix"]
                    )
                else:
                    raise ValueError(f"unsupported HTTP class endpoint response: {kind!r}")
                return PlainTextResponse(
                    content=content,
                    status_code=class_response_spec["status_code"],
                    media_type=class_response_spec["media_type"],
                )

            class_attributes: dict[str, Any] = {"__module__": __name__}

            def endpoint_init(self: Any, scope: Any, receive: Any, send: Any) -> None:
                HTTPEndpoint.__init__(self, scope, receive, send)
                route_index_observations.append(route_index)

            class_attributes["__init__"] = endpoint_init
            for handler_spec in response_spec["handlers"]:
                if set(handler_spec) != {"name", "call_style", "response"}:
                    raise ValueError("HTTP class endpoint handler has unsupported fields")
                handler_response_spec = handler_spec["response"]
                if handler_spec["call_style"] == "async":

                    async def async_handler(
                        self: Any,
                        request: Any,
                        class_response_spec: dict[str, Any] = handler_response_spec,
                    ) -> Any:
                        return make_class_response(request, class_response_spec)

                    class_attributes[handler_spec["name"]] = async_handler
                elif handler_spec["call_style"] == "sync":

                    def sync_handler(
                        self: Any,
                        request: Any,
                        class_response_spec: dict[str, Any] = handler_response_spec,
                    ) -> Any:
                        return make_class_response(request, class_response_spec)

                    class_attributes[handler_spec["name"]] = sync_handler
                else:
                    raise ValueError("HTTP class endpoint call_style must be async or sync")

            endpoint_class = type("InputHTTPEndpoint", (HTTPEndpoint,), class_attributes)
            return make_http_route(route_spec, endpoint_class)

        if response_spec.get("kind") == "sync-datetime-json-response":

            def datetime_endpoint(request: Any, raw: dict[str, Any] = response_spec) -> Any:
                route_index_observations.append(route_index)
                value = request.path_params[raw["path_parameter"]]
                return JSONResponse(
                    {raw["json_key"]: value.strftime(raw["format"])},
                    status_code=raw["status_code"],
                )

            return make_http_route(route_spec, datetime_endpoint)

        if response_spec.get("kind") == "sync-path-parameter-json-response":

            def path_parameter_endpoint(request: Any, raw: dict[str, Any] = response_spec) -> Any:
                route_index_observations.append(route_index)
                value = request.path_params[raw["path_parameter"]]
                if raw["value_transform"] == "string":
                    value = str(value)
                return JSONResponse(
                    {raw["json_key"]: value},
                    status_code=raw["status_code"],
                )

            return make_http_route(route_spec, path_parameter_endpoint)

        if response_spec.get("kind") == "sync-plain-text-response":
            if set(response_spec) != {
                "kind",
                "content",
                "status_code",
                "media_type",
                "cookies",
            }:
                raise ValueError("synchronous plain-text route response has unsupported fields")

            def endpoint(request: Any) -> Any:
                route_index_observations.append(route_index)
                response = Response(
                    content=response_spec["content"],
                    status_code=response_spec["status_code"],
                    media_type=response_spec["media_type"],
                )
                for cookie in response_spec["cookies"]:
                    response.set_cookie(key=cookie["key"], value=cookie["value"])
                return response

            return make_http_route(route_spec, endpoint)

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

        return make_http_route(route_spec, endpoint)

    def make_mount_child(route_spec: dict[str, Any], route_index: int = 0) -> Any:
        if route_spec.get("kind") == "mount":
            if frozenset(route_spec) not in {
                frozenset({"kind", "path", "routes"}),
                frozenset({"kind", "path", "routes", "max_body_size"}),
            }:
                raise ValueError("nested Mount input has unsupported fields")
            nested_routes = route_spec["routes"]
            if not isinstance(nested_routes, list):
                raise ValueError("nested Mount routes must be an array")
            return Mount(
                route_spec["path"],
                routes=[make_mount_child(child, route_index) for child in nested_routes],
                max_body_size=route_spec.get("max_body_size"),
            )
        if route_spec.get("kind") != "http-route":
            raise ValueError("Mount child kind must be http-route or mount")
        return make_route(route_spec, route_index)

    def make_host_route(route_spec: dict[str, Any], route_index: int) -> Any:
        app_spec = route_spec["app"]

        if app_spec["kind"] == "router":
            host_routes = []
            for child in app_spec["routes"]:
                if child["kind"] == "websocket-route":
                    endpoint_actions = child["endpoint_actions"]

                    async def websocket_endpoint(
                        websocket: Any,
                        actions: list[dict[str, Any]] = endpoint_actions,
                        observed_route_index: int = route_index,
                    ) -> None:
                        route_index_observations.append(observed_route_index)
                        for action in actions:
                            if action["action"] == "accept":
                                await websocket.accept(subprotocol=action["subprotocol"])
                            elif action["action"] == "send_text":
                                await websocket.send_text(action["text"])
                            else:
                                await websocket.close(code=action["code"], reason=action["reason"])

                    host_routes.append(WebSocketRoute(child["path"], websocket_endpoint))
                    continue
                host_routes.append(make_route(child, route_index))
            app = Router(routes=host_routes)
            return Host(route_spec["host"], app, name=route_spec["name"])

        if app_spec["kind"] == "scope-path-parameter-json":
            path_parameter = app_spec["path_parameter"]

            async def subdomain_app(scope: Any, receive: Any, send: Any) -> None:
                route_index_observations.append(route_index)
                await JSONResponse({path_parameter: scope["path_params"][path_parameter]})(
                    scope, receive, send
                )

            return Host(route_spec["host"], subdomain_app, name=route_spec["name"])

        async def app(scope: Any, receive: Any, send: Any) -> None:
            route_index_observations.append(route_index)
            await PlainTextResponse(
                app_spec["content"],
                status_code=app_spec["status_code"],
                media_type=app_spec["media_type"],
            )(scope, receive, send)

        return Host(route_spec["host"], app, name=route_spec["name"])

    if case["surface"] == "starlette.routing.Router":
        redirect_slashes = case["redirect_slashes"]
        if type(redirect_slashes) is not bool:
            raise ValueError("Router redirect_slashes must be a boolean")
        route_objects = [
            make_host_route(route, index)
            if route["kind"] == "host-route"
            else make_mount_child(route, index)
            if route["kind"] == "mount"
            else make_route(route, index)
            for index, route in enumerate(case["routes"])
        ]
        app = Router(
            routes=route_objects,
            redirect_slashes=redirect_slashes,
            max_body_size=case.get("max_body_size"),
        )
    elif case["surface"] == "starlette.routing.Mount":
        mount = case["mount"]
        if frozenset(mount) not in {
            frozenset({"path", "routes"}),
            frozenset({"path", "routes", "max_body_size"}),
        }:
            raise ValueError("Mount input has unsupported fields")
        route_objects = [make_mount_child(route) for route in mount["routes"]]
        app = Mount(
            mount["path"],
            routes=route_objects,
            max_body_size=mount.get("max_body_size"),
        )
    else:
        raise ValueError("route-dispatch case has an unsupported surface")

    gc_roots: list[Any] = []
    gc_references: list[Any] = []
    gc_endpoint = None
    if garbage_collection is not None:
        if case["surface"] != "starlette.routing.Router" or router_sequence:
            raise ValueError("route-dispatch garbage collection requires a Router dispatch")
        if len(gc_endpoint_instances) != 1:
            raise RuntimeError("Router GC input did not construct one route endpoint")
        gc_endpoint = gc_endpoint_instances.pop()
        gc_endpoint.router = app
        gc_roots.append(app)
        gc_references = [weakref.ref(gc_endpoint), weakref.ref(gc_endpoint.guard)]

    async def dispatch(dispatch_input: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        scope = _make_scope(dispatch_input["scope"])
        incoming = [_make_message(message) for message in dispatch_input["incoming"]]
        received = 0
        sent: list[dict[str, Any]] = []
        route_observation_start = len(route_index_observations)

        async def receive() -> dict[str, Any]:
            nonlocal received
            if received < len(incoming):
                message = incoming[received]
                received += 1
                return message
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        if dispatch_input["send"] != {"kind": "capture-asgi-send"}:
            raise ValueError("send input must select the declared ASGI message collector")
        dispatch_error = None
        try:
            await app(scope, receive, send)
        except Exception as exc:
            if case.get("observe_dispatch_error") is not True:
                raise
            dispatch_error = _dispatch_error(exc)
        events = [_canonical_message(message) for message in sent]
        response_start = next(
            (event for event in events if event["type"] == "http.response.start"), None
        )
        response_body = b"".join(
            message.get("body", b"") for message in sent if message["type"] == "http.response.body"
        )
        observation = {
            "response_status": response_start["status"] if response_start is not None else None,
            "ordered_repeated_headers": response_start["headers"]
            if response_start is not None
            else [],
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
        if (
            case["surface"] == "starlette.routing.Router"
            and case.get("observe_router_scope") is True
        ):
            observation["route_scope.path"] = scope.get("path")
            observation["route_scope.root_path"] = scope.get("root_path", "")
            observation["route_scope.app_root_path"] = scope.get("app_root_path")
            observation["route_scope.path_params"] = {
                name: {"value": _json_safe(value), "type": type(value).__name__}
                for name, value in scope.get("path_params", {}).items()
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
            route_indexes = route_index_observations[route_observation_start:]
            if len(route_indexes) > 1:
                raise RuntimeError("Router dispatched more than one route endpoint")
            observation["route_index"] = route_indexes[0] if route_indexes else None
        if dispatch_error is not None:
            observation["dispatch_error.class"] = dispatch_error["class"]
            observation["dispatch_error.message"] = dispatch_error["message"]
        return observation, scope

    if router_sequence:

        async def run_sequence() -> list[dict[str, Any]]:
            observations = []
            for step in case["steps"]:
                for mutation in step["mutations"]:
                    if mutation["operation"] == "route-method-add":
                        app.routes[mutation["route_index"]].methods.add(mutation["method"])
                    elif mutation["operation"] == "route-path-set":
                        app.routes[mutation["route_index"]].path = mutation["path"]
                    elif mutation["operation"] == "route-list-append":
                        route = make_route(mutation["route"], len(app.routes))
                        app.routes.append(route)
                    elif mutation["operation"] == "route-list-remove":
                        app.routes.pop(mutation["route_index"])
                    elif mutation["operation"] == "mount-app-add-route":
                        route_spec = mutation["route"]
                        mounted_router = app.routes[mutation["mount_route_index"]].app
                        route = make_route(route_spec, len(mounted_router.routes))
                        mounted_router.add_route(
                            route_spec["path"],
                            endpoint=route.endpoint,
                            methods=route_spec["methods"],
                        )
                    elif mutation["operation"] == "router-default-set":
                        app.default = app.routes[mutation["route_index"]].app
                    else:
                        raise ValueError("unsupported Router route mutation")
                observation, _scope = await dispatch(step)
                observations.append(
                    {"step_id": step["step_id"], "status": "ok", "value": observation}
                )
            return observations

        sequence_observations = asyncio.run(run_sequence())
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": sequence_observations,
        }

    gc_observation = None
    if garbage_collection is None:
        observation, scope = asyncio.run(dispatch(case))
    else:
        if gc_observer is None or observe_ownership is None:
            raise RuntimeError("Router GC observer was not installed")
        with warnings.catch_warnings(record=True) as warning_events:
            warnings.simplefilter("always")
            observation, scope = asyncio.run(dispatch(case))
            del dispatch
            del app
            del route_objects
            del gc_endpoint
            del scope
            gc_observation = observe_ownership(
                garbage_collection,
                gc_roots,
                gc_references,
                [],
                gc_observer,
                warning_events,
            )
        observation["garbage_collection"] = {
            "reference_labels": [
                garbage_collection["endpoint_label"],
                garbage_collection["guard_label"],
            ],
            **gc_observation,
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
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "route-dispatch", "status": "ok", "value": observation}],
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
    _exact_object(
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
    if "header_actions" in case:
        case_keys.add("header_actions")
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
    if "background_task" in case:
        case_keys.add("background_task")
    if "stat_result" in case:
        case_keys.add("stat_result")
    if "pathlike" in case:
        case_keys.add("pathlike")
    _exact_object(
        case,
        case_keys,
        "FileResponse ASGI-call case",
    )
    if case["surface"] != FILE_RESPONSE_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared FileResponse ASGI-call operation")
    pathlike_spec = case.get("pathlike")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("FileResponse observations must select asgi-call")

    file_spec = case["file"]
    error_path: Path | None = None
    file_kind = "regular"
    if isinstance(file_spec, dict) and file_spec.get("kind") in {"directory", "missing"}:
        file_spec = _exact_object(file_spec, {"kind", "path"}, "FileResponse error path")
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
        file_spec = _exact_object(
            file_spec, {"name", "contents_base64", "mtime_seconds"}, "FileResponse file"
        )
        name = file_spec["name"]
        encoded_contents = file_spec["contents_base64"]
        mtime_seconds = file_spec["mtime_seconds"]
        if not isinstance(name, str) or not name or name in {".", ".."} or Path(name).name != name:
            raise ValueError("FileResponse file.name must be a basename")
        if not isinstance(encoded_contents, str):
            raise ValueError("FileResponse file.contents_base64 must be a string")
        if type(mtime_seconds) not in {int, float} or not math.isfinite(mtime_seconds):
            raise ValueError("FileResponse file.mtime_seconds must be a finite number")
        contents = _decode_base64(encoded_contents, "file.contents_base64")
    stat_result_spec = case.get("stat_result")
    if stat_result_spec is not None:
        stat_result_spec = _exact_object(
            stat_result_spec, {"size", "mtime_seconds"}, "FileResponse stat_result"
        )
        if (
            type(stat_result_spec["size"]) is not int
            or not 0 <= stat_result_spec["size"] <= 2**64 - 1
            or type(stat_result_spec["mtime_seconds"]) not in {int, float}
            or not math.isfinite(stat_result_spec["mtime_seconds"])
        ):
            raise ValueError("FileResponse stat_result size and mtime must be valid")
    pathlike_spec = case.get("pathlike")
    if pathlike_spec is not None:
        pathlike_spec = _exact_object(
            pathlike_spec,
            {
                "fspath_results_relative_to_workspace",
                "opened_file",
                "record_fspath_call_order",
                "record_is_event_loop_thread",
                "record_send_start_completion_before_open",
            },
            "FileResponse PathLike input",
        )
        if (
            not isinstance(pathlike_spec["fspath_results_relative_to_workspace"], list)
            or len(pathlike_spec["fspath_results_relative_to_workspace"]) != 2
        ):
            raise ValueError("FileResponse PathLike input must define metadata and open paths")

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
    background_task_spec = case.get("background_task")
    background = None
    background_value_parts: list[str] = []
    execution_trace: list[str] = []
    if background_task_spec is not None:
        _exact_object(
            background_task_spec,
            {"kind", "start", "stop", "separator"},
            "FileResponse background task",
        )
        if background_task_spec["kind"] != "append-number-sequence":
            raise ValueError("FileResponse background task kind is unsupported")
        import anyio
        from starlette.background import BackgroundTask

        async def run_background_task(start: int, stop: int, separator: str) -> None:
            execution_trace.append("background.start")
            for number in range(start, stop + 1):
                background_value_parts.append(str(number))
                if number != stop:
                    background_value_parts.append(separator)
                await anyio.lowlevel.checkpoint()
            execution_trace.append("background.complete")

        background = BackgroundTask(
            run_background_task,
            start=background_task_spec["start"],
            stop=background_task_spec["stop"],
            separator=background_task_spec["separator"],
        )
    if request_sequence:
        if any(
            key in case
            for key in (
                "header_actions",
                "header_view_probe",
                "scheduling",
                "call_time_field_assignments",
            )
        ):
            raise ValueError(
                "FileResponse call sequences do not combine with header, scheduling, or call-time probes"
            )
        call_specs = case["calls"]
        if not isinstance(call_specs, list) or len(call_specs) < 2:
            raise ValueError("FileResponse calls must contain at least two request inputs")
        for index, call in enumerate(call_specs):
            _exact_object(call, {"scope", "incoming", "send"}, f"FileResponse calls[{index}]")
            if call["incoming"] != [] or call["send"] != {"kind": "capture-asgi-send"}:
                raise ValueError(
                    f"FileResponse calls[{index}] requires empty receive and captured send"
                )
            scope = _exact_object(
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
            if scope["type"] != "http":
                raise ValueError("FileResponse call sequences require HTTP scopes")
    else:
        call_specs = [{"scope": case["scope"], "incoming": case["incoming"], "send": case["send"]}]
    scope_spec = call_specs[0]["scope"]
    if request_sequence:
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
        scope_spec = _exact_object(scope_spec, scope_keys, "FileResponse call scope")
        if scope_spec["type"] != "http":
            raise ValueError("FileResponse call sequences require HTTP scopes")
    elif not isinstance(scope_spec, dict):
        raise ValueError("FileResponse ASGI-call requires an HTTP or WebSocket scope")
    else:
        _, scope_type = _materialize_scope_type_spec(scope_spec.get("type"))
        if not isinstance(scope_type, str) or scope_type not in {"http", "websocket"}:
            raise ValueError("FileResponse ASGI-call requires an HTTP or WebSocket scope")
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
        }
        if scope_type == "http":
            scope_keys.add("method")
        else:
            scope_keys.add("subprotocols")
        if "extensions" in scope_spec:
            scope_keys.add("extensions")
        scope_spec = _exact_object(scope_spec, scope_keys, "FileResponse ASGI scope")
    if call_specs[0]["incoming"] != []:
        raise ValueError("FileResponse ASGI-call requires an empty incoming stream")
    send_error_spec: dict[str, Any] | None = None
    send_cancellation_spec: dict[str, Any] | None = None
    if call_specs[0]["send"] != {"kind": "capture-asgi-send"}:
        if request_sequence:
            raise ValueError("FileResponse call sequences require captured ASGI messages")
        send_spec = call_specs[0]["send"]
        if (
            isinstance(send_spec, dict)
            and send_spec.get("kind") == "capture-asgi-send-with-caller-cancellation"
        ):
            send_cancellation_spec = _exact_object(
                send_spec,
                {"kind", "event_index"},
                "FileResponse caller-cancelled send",
            )
            if (
                type(send_cancellation_spec["event_index"]) is not int
                or send_cancellation_spec["event_index"] != 1
            ):
                raise ValueError("FileResponse caller-cancelled send input is invalid")
        else:
            send_error_spec = _exact_object(
                send_spec,
                {"kind", "event_index", "message"},
                "FileResponse bounded failing send",
            )
            if (
                send_error_spec["kind"] != "capture-asgi-send-until-oserror"
                or type(send_error_spec["event_index"]) is not int
                or not 6 <= send_error_spec["event_index"] <= 64
                or not isinstance(send_error_spec["message"], str)
            ):
                raise ValueError("FileResponse bounded failing send input is invalid")

    scheduling = case.get("scheduling")
    if scheduling is not None:
        _exact_object(
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
            if pathlike_spec is not None:
                stat_result = None
                os.utime(path, (mtime_seconds, mtime_seconds))
            else:
                stat_size = (
                    stat_result_spec["size"] if stat_result_spec is not None else len(contents)
                )
                stat_mtime = (
                    stat_result_spec["mtime_seconds"]
                    if stat_result_spec is not None
                    else mtime_seconds
                )
                stat_result = os.stat_result(
                    (
                        stat.S_IFREG | 0o644,
                        0,
                        0,
                        1,
                        0,
                        0,
                        stat_size,
                        stat_mtime,
                        stat_mtime,
                        stat_mtime,
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
        pathlike_calls: list[dict[str, Any]] = []
        pathlike_runtime_state: dict[str, int | bool | None] = {
            "event_loop_thread_id": None,
            "response_start_send_completed": False,
        }
        if pathlike_spec is not None:
            opened_file = pathlike_spec["opened_file"]
            opened_path = Path(directory) / opened_file["name"]
            opened_path.write_bytes(_decode_base64(opened_file["contents_base64"], "opened_file"))
            os.utime(
                opened_path,
                (opened_file["mtime_seconds"], opened_file["mtime_seconds"]),
            )

            class InputPathLike:
                def __fspath__(self) -> str:
                    results = pathlike_spec["fspath_results_relative_to_workspace"]
                    call_index = len(pathlike_calls)
                    result = results[min(call_index, len(results) - 1)]
                    pathlike_calls.append(
                        {
                            "call_index": call_index,
                            "result_relative_to_workspace": result,
                            "is_event_loop_thread": threading.get_ident()
                            == pathlike_runtime_state["event_loop_thread_id"],
                            "response_start_send_completed": pathlike_runtime_state[
                                "response_start_send_completed"
                            ],
                        }
                    )
                    return str(Path(directory) / result)

            path = InputPathLike()
        field_assignments = dict(case.get("call_time_field_assignments", {}))
        for field, value in field_assignments.items():
            if field == "path":
                path_spec = value
                value = Path(directory) / path_spec["name"]
                value.write_bytes(
                    _decode_base64(
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
            field_assignments[field] = value
        response_class = (
            type("ConfiguredFileResponse", (FileResponse,), {"max_ranges": case["max_ranges"]})
            if "max_ranges" in case
            else FileResponse
        )
        try:
            response = response_class(
                path,
                status_code=case["status_code"],
                headers=dict(header_pairs),
                media_type=media_type,
                background=background,
                filename=filename,
                stat_result=stat_result,
                content_disposition_type=content_disposition_type,
            )
        except Exception as exc:
            dispatch_error = _dispatch_error(exc)
            if request_sequence:
                value = {"responses": [], "dispatch_error": dispatch_error}
            else:
                value = {
                    "response_status": None,
                    "ordered_repeated_headers": [],
                    "response_bytes": {"encoding": "base64", "data": ""},
                    "asgi_event_order": [],
                    "asgi_events": [],
                    "dispatch_error": dispatch_error,
                }
                if pathlike_spec is not None:
                    value["pathlike_fspath_calls"] = pathlike_calls
                if background_task_spec is not None:
                    value["background_task"] = {
                        "initial_value": "",
                        "value": "",
                        "execution_trace": [],
                    }
                if "header_actions" in case:
                    value["header_action_results"] = []
            return {
                "case_id": case["case_id"],
                "status": "completed",
                "observations": [{"step_id": RESPONSE_OPERATION, "status": "ok", "value": value}],
            }
        for field, value in field_assignments.items():
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
        header_action_results = (
            _apply_response_header_actions(response, case["header_actions"])
            if "header_actions" in case
            else None
        )
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
                            if message["type"]
                            in {"http.response.start", "websocket.http.response.start"}
                        ),
                        None,
                    )
                    call_start_event = next(
                        (
                            event
                            for event in call_events
                            if event["type"]
                            in {"http.response.start", "websocket.http.response.start"}
                        ),
                        None,
                    )
                    call_body = b"".join(
                        message.get("body", b"")
                        for message in call_sent
                        if message["type"] in {"http.response.body", "websocket.http.response.body"}
                    )
                    observations.append(
                        {
                            "response_status": (
                                call_start["status"] if call_start is not None else None
                            ),
                            "ordered_repeated_headers": (
                                call_start_event.get(
                                    "headers", call_start_event.get("headers_base64_pairs", [])
                                )
                                if call_start_event is not None
                                else []
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
            send_index = 0
            send_gate_entered = asyncio.Event() if send_cancellation_spec is not None else None
            send_gate_release = asyncio.Event() if send_cancellation_spec is not None else None

            async def send(message: dict[str, Any]) -> None:
                nonlocal send_index
                if (
                    send_cancellation_spec is not None
                    and send_index == send_cancellation_spec["event_index"]
                ):
                    if send_gate_entered is None or send_gate_release is None:
                        raise RuntimeError("FileResponse caller-cancellation gate is unavailable")
                    send_gate_entered.set()
                    await send_gate_release.wait()
                if send_error_spec is not None and send_index == send_error_spec["event_index"]:
                    send_index += 1
                    raise OSError(send_error_spec["message"])
                sent.append(message)
                execution_trace.append(message["type"])
                send_index += 1
                if pathlike_spec is not None and message["type"] == "http.response.start":
                    pathlike_runtime_state["response_start_send_completed"] = True

            async def invoke_response() -> None:
                if pathlike_spec is not None:
                    pathlike_runtime_state["event_loop_thread_id"] = threading.get_ident()
                await response(scope, receive, send)

            if send_cancellation_spec is not None:

                async def invoke_and_cancel_blocked_send() -> None:
                    nonlocal captured_dispatch_error
                    if send_gate_entered is None or send_gate_release is None:
                        raise RuntimeError(
                            "FileResponse caller-cancellation gate events are unavailable"
                        )
                    response_task = asyncio.create_task(invoke_response())
                    try:
                        await asyncio.wait_for(send_gate_entered.wait(), timeout=5.0)
                        response_task.cancel()
                        try:
                            await response_task
                        except asyncio.CancelledError as exc:
                            captured_dispatch_error = _dispatch_error(exc)
                        except Exception as exc:
                            captured_dispatch_error = _dispatch_error(exc)
                    finally:
                        if not response_task.done():
                            response_task.cancel()
                            send_gate_release.set()
                            try:
                                await response_task
                            except BaseException:
                                pass

                asyncio.run(invoke_and_cancel_blocked_send())
            else:
                try:
                    asyncio.run(invoke_response())
                except Exception as exc:
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
            (
                message
                for message in sent
                if message["type"] in {"http.response.start", "websocket.http.response.start"}
            ),
            None,
        )
        response_start_event = next(
            (
                event
                for event in events
                if event["type"] in {"http.response.start", "websocket.http.response.start"}
            ),
            None,
        )
        response_body = b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] in {"http.response.body", "websocket.http.response.body"}
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
        if header_action_results is not None:
            observation["header_action_results"] = header_action_results
        if event_loop_scheduling is not None:
            observation["event_loop_scheduling"] = event_loop_scheduling
        if pathlike_spec is not None:
            observation["pathlike_fspath_calls"] = pathlike_calls
        if background_task_spec is not None:
            observation["background_task"] = {
                "initial_value": "",
                "value": "".join(background_value_parts),
                "execution_trace": execution_trace,
            }
        workflow_observations = [
            {"step_id": RESPONSE_OPERATION, "status": "ok", "value": observation}
        ]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": workflow_observations,
    }


def _file_response_scheduling_skipped(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "skipped",
        "observations": [
            {"step_id": selector, "status": "skipped", "reason": reason}
            for selector in case["observations"]
        ],
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


def _apply_static_files_actions(
    root: Path,
    actions: Any,
    declared_paths: set[str],
    removed_paths: set[str],
) -> None:
    if not isinstance(actions, list):
        raise ValueError("StaticFiles filesystem_actions_before must be a list")

    safe_root = root.resolve(strict=True)
    for index, action in enumerate(actions):
        action = _exact_object(
            action,
            {"operation", "path"},
            f"StaticFiles filesystem_actions_before[{index}]",
        )
        if action["operation"] != "unlink":
            raise ValueError("StaticFiles filesystem action operation must be unlink")

        relative_path = action["path"]
        if not isinstance(relative_path, str):
            raise ValueError("StaticFiles filesystem action path must be a string")
        components = relative_path.split("/")
        if (
            not relative_path
            or "\x00" in relative_path
            or "\\" in relative_path
            or ":" in relative_path
            or relative_path.startswith("/")
            or any(component in {"", ".", ".."} for component in components)
        ):
            raise ValueError("StaticFiles filesystem action path must be a safe relative path")
        if relative_path not in declared_paths:
            raise ValueError("StaticFiles filesystem action path must name a declared file")
        if relative_path in removed_paths:
            raise ValueError("StaticFiles filesystem action path names a file already unlinked")

        parent = safe_root.joinpath(*components[:-1]).resolve(strict=True)
        try:
            parent.relative_to(safe_root)
        except ValueError as exc:
            raise ValueError(
                "StaticFiles filesystem action path must remain inside the temporary root"
            ) from exc
        (parent / components[-1]).unlink()
        removed_paths.add(relative_path)


def _run_static_files_case(case: dict[str, Any]) -> dict[str, Any]:
    request_sequence = "calls" in case
    expected_keys = {
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
    if "scope_container" in case:
        expected_keys.add("scope_container")
    if "scope_observation" in case:
        expected_keys.add("scope_observation")
    if "subclass_hooks" in case:
        expected_keys.add("subclass_hooks")
    if "package_sequence" in case:
        expected_keys.add("package_sequence")
    if "package_tuple_subclass" in case:
        expected_keys.add("package_tuple_subclass")
    if request_sequence:
        expected_keys.add("calls")
    else:
        expected_keys.update({"scope", "incoming", "send"})
    _exact_object(case, expected_keys, "StaticFiles ASGI-call case")
    if case["surface"] != STATIC_FILES_SURFACE or case["operation"] != RESPONSE_OPERATION:
        raise ValueError("workflow is outside the declared StaticFiles ASGI-call operation")
    if case["observations"] != [RESPONSE_OPERATION]:
        raise ValueError("StaticFiles observations must select asgi-call")
    subclass_hooks = case.get("subclass_hooks")
    if subclass_hooks is not None:
        if request_sequence or any(
            case[key] is not None
            for key in ("path_limit_stress", "permission_denial_stress", "filesystem")
        ):
            raise ValueError("StaticFiles subclass hooks require a single plain ASGI call")
        if not isinstance(subclass_hooks, dict) or len(subclass_hooks) != 1:
            raise ValueError("StaticFiles subclass hooks must select exactly one hook")
        selected_hook = next(iter(subclass_hooks))
        _exact_object(
            subclass_hooks,
            {selected_hook},
            "StaticFiles subclass hooks",
        )
        if "file_response" in subclass_hooks:
            _exact_object(
                subclass_hooks["file_response"],
                {"response_status", "response_body_base64"},
                "StaticFiles file_response subclass hook",
            )
        elif selected_hook == "lookup_path":
            _exact_object(
                subclass_hooks["lookup_path"],
                {"raise_permission_at_path", "message"},
                "StaticFiles lookup_path subclass hook",
            )
        elif selected_hook == "is_not_modified":
            _exact_object(
                subclass_hooks["is_not_modified"],
                {"return_value"},
                "StaticFiles is_not_modified subclass hook",
            )
        elif selected_hook == "get_directories":
            directory_hook_fields = {"return_configured_directory"}
            if "return_package_directories_before_configured" in subclass_hooks["get_directories"]:
                directory_hook_fields.add("return_package_directories_before_configured")
            _exact_object(
                subclass_hooks["get_directories"],
                directory_hook_fields,
                "StaticFiles get_directories subclass hook",
            )
            if any(
                not isinstance(subclass_hooks["get_directories"][field], bool)
                for field in directory_hook_fields
            ):
                raise ValueError("StaticFiles get_directories subclass hook values must be boolean")
        else:
            _exact_object(
                subclass_hooks["get_response"],
                {"response_status", "response_body_base64"},
                "StaticFiles get_response subclass hook",
            )

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
            call_fields = {"scope", "incoming", "send"}
            if "filesystem_actions_before" in call:
                call_fields.add("filesystem_actions_before")
            _exact_object(call, call_fields, f"StaticFiles calls[{index}]")
            if call["incoming"] != [] or call["send"] != {"kind": "capture-asgi-send"}:
                raise ValueError("StaticFiles calls require empty receive and captured send")
    else:
        call_specs = [{"scope": case["scope"], "incoming": case["incoming"], "send": case["send"]}]

    from starlette.staticfiles import StaticFiles

    subclass_hook_calls: list[dict[str, Any]] = []
    static_files_type = StaticFiles
    if subclass_hooks is not None:
        from starlette.responses import Response

        class StaticFilesSubclassHooks(StaticFiles):
            def get_directories(
                self,
                directory: Any = None,
                packages: Any = None,
            ) -> list[Any]:
                hook_spec = subclass_hooks.get("get_directories")
                if hook_spec is None:
                    return super().get_directories(directory, packages)
                subclass_hook_calls.append(
                    {
                        "hook": "get_directories",
                        "directory_basename": Path(directory).name
                        if directory is not None
                        else None,
                        "packages": packages,
                    }
                )
                if hook_spec.get("return_package_directories_before_configured"):
                    directories = super().get_directories(None, packages)
                    if hook_spec["return_configured_directory"] and directory is not None:
                        directories.append(directory)
                    return directories
                if hook_spec["return_configured_directory"] and directory is not None:
                    return [directory]
                return []

            def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
                hook_spec = subclass_hooks.get("lookup_path")
                if hook_spec is None:
                    return super().lookup_path(path)
                subclass_hook_calls.append({"hook": "lookup_path", "path": path})
                if path == hook_spec["raise_permission_at_path"]:
                    raise PermissionError(hook_spec["message"])
                return super().lookup_path(path)

            def file_response(
                self,
                full_path: str,
                stat_result: os.stat_result,
                scope: dict[str, Any],
                status_code: int = 200,
            ) -> object:
                hook_spec = subclass_hooks.get("file_response")
                if hook_spec is None:
                    return super().file_response(full_path, stat_result, scope, status_code)
                subclass_hook_calls.append(
                    {
                        "hook": "file_response",
                        "path_basename": Path(full_path).name,
                        "stat_size": stat_result.st_size,
                        "scope_method": scope["method"],
                        "scope_path": scope["path"],
                        "status_code": status_code,
                    }
                )
                return Response(
                    _decode_base64(
                        hook_spec["response_body_base64"],
                        "StaticFiles file_response subclass body",
                    ),
                    status_code=hook_spec["response_status"],
                )

            def is_not_modified(self, response_headers: Any, request_headers: Any) -> bool:
                hook_spec = subclass_hooks.get("is_not_modified")
                if hook_spec is None:
                    return super().is_not_modified(response_headers, request_headers)
                subclass_hook_calls.append(
                    {
                        "hook": "is_not_modified",
                        "response_etag": response_headers.get("etag"),
                        "request_if_none_match": request_headers.get("if-none-match"),
                        "return_value": hook_spec["return_value"],
                    }
                )
                return hook_spec["return_value"]

            async def get_response(self, path: str, scope: dict[str, Any]) -> object:
                hook_spec = subclass_hooks.get("get_response")
                if hook_spec is None:
                    return await super().get_response(path, scope)
                subclass_hook_calls.append(
                    {
                        "hook": "get_response",
                        "path": path,
                        "scope_method": scope["method"],
                        "scope_path": scope["path"],
                    }
                )
                return Response(
                    _decode_base64(
                        hook_spec["response_body_base64"],
                        "StaticFiles get_response subclass body",
                    ),
                    status_code=hook_spec["response_status"],
                )

        static_files_type = StaticFilesSubclassHooks

    temporary_prefix = (
        "starlette-static-path-limit-"
        if case["path_limit_stress"] is not None
        else "starlette-package-static-files-"
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
            path.write_bytes(_decode_base64(file_spec["contents_base64"], "file.contents_base64"))
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        if filesystem is not None:
            for directory in filesystem["directories"]:
                (workspace / directory).mkdir(parents=True, exist_ok=True)
            for file_spec in filesystem["outside_files"]:
                path = workspace / file_spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    _decode_base64(file_spec["contents_base64"], "StaticFiles outside file")
                )
                os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
            for symlink_spec in filesystem["symlinks"]:
                path = root / symlink_spec["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(symlink_spec["target"], path)
        declared_file_paths = {file_spec["path"] for file_spec in case["files"]}
        removed_file_paths: set[str] = set()
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
                    _decode_base64(file_spec["contents_base64"], "package file.contents_base64")
                )
                os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
            package_arguments.append(
                package["name"]
                if package["statics_dir"] == "statics"
                else (package["name"], package["statics_dir"])
            )
        package_tuple_trace: list[dict[str, Any]] = []
        package_tuple_subclass = case.get("package_tuple_subclass")
        if package_tuple_subclass is not None:
            _exact_object(
                package_tuple_subclass,
                {"index", "iter_values"},
                "StaticFiles package tuple subclass",
            )
            tuple_index = package_tuple_subclass["index"]
            tuple_values = package_tuple_subclass["iter_values"]

            class InputPackageTuple(tuple[Any, ...]):
                def __iter__(self) -> Any:
                    package_tuple_trace.append(
                        {"event": "iter", "index": tuple_index, "values": tuple_values}
                    )
                    return iter(tuple_values)

            package_arguments[tuple_index] = InputPackageTuple(package_arguments[tuple_index])
        package_sequence_trace: list[str] = []
        package_sequence = case.get("package_sequence")
        if package_sequence is not None:
            _exact_object(
                package_sequence,
                {"kind"},
                "StaticFiles package sequence",
            )
            if package_sequence["kind"] != "falsey-list-subclass":
                raise ValueError("StaticFiles package sequence kind is unsupported")

            class InputPackageSequence(list[Any]):
                def __bool__(self) -> bool:
                    package_sequence_trace.append("bool")
                    return False

                def __iter__(self):
                    package_sequence_trace.append("iter")
                    return super().__iter__()

            package_arguments = InputPackageSequence(package_arguments)
        sys.path.insert(0, str(package_source_root))
        try:
            application: Any = None
            construction_error: Exception | None = None
            try:
                application = static_files_type(
                    directory=root,
                    packages=package_arguments,
                    html=case["html"],
                    check_dir=case["check_dir"],
                    follow_symlink=case["follow_symlink"],
                )
            except Exception as exc:
                construction_error = exc
            if construction_error is None and application is None:
                raise RuntimeError("StaticFiles construction produced no application")
            if request_sequence:
                if construction_error is not None:
                    error = _dispatch_error(construction_error)
                    error["code"] = getattr(construction_error, "status_code", None)
                    return {
                        "case_id": case["case_id"],
                        "status": "completed",
                        "observations": [
                            {
                                "step_id": RESPONSE_OPERATION,
                                "status": "error",
                                "error": error,
                                "partial_value": {"requests": []},
                            }
                        ],
                    }

                async def observe_call(call: dict[str, Any]) -> dict[str, Any]:
                    scope = _make_static_files_scope(
                        call["scope"], case.get("scope_container", "dict")
                    )
                    sent: list[dict[str, Any]] = []

                    async def receive() -> dict[str, Any]:
                        return {"type": "http.disconnect"}

                    async def send(message: dict[str, Any]) -> None:
                        sent.append(message)

                    captured_error: Exception | None = None
                    _apply_static_files_actions(
                        root,
                        call.get("filesystem_actions_before", []),
                        declared_file_paths,
                        removed_file_paths,
                    )
                    try:
                        await application(scope, receive, send)
                    except Exception as exc:
                        captured_error = exc
                    scope_observation_result = (
                        _scope_observation(scope, case["scope_observation"])
                        if "scope_observation" in case
                        else None
                    )
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
                    if scope_observation_result is not None:
                        observation["scope_observation"] = scope_observation_result
                    if captured_error is None:
                        return {"status": "ok", "value": observation}
                    error = _dispatch_error(captured_error)
                    error["code"] = getattr(captured_error, "status_code", None)
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
            scope = _make_static_files_scope(case["scope"], case.get("scope_container", "dict"))
            sent: list[dict[str, Any]] = []

            async def receive() -> dict[str, Any]:
                return {"type": "http.disconnect"}

            async def send(message: dict[str, Any]) -> None:
                sent.append(message)

            captured_error = construction_error
            permission_original_mode = None
            permission_skip_reason = None
            if captured_error is None:
                permission_original_mode, permission_skip_reason = (
                    _static_files_permission_denial_mode(case, root)
                )
            if permission_skip_reason is not None:
                return _static_files_permission_denial_skipped(case, permission_skip_reason)
            try:
                if captured_error is None:
                    asyncio.run(application(scope, receive, send))
            except Exception as exc:
                captured_error = exc
            finally:
                if permission_original_mode is not None:
                    root.chmod(permission_original_mode)
            scope_observation_result = (
                _scope_observation(scope, case["scope_observation"])
                if "scope_observation" in case
                else None
            )
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
        if scope_observation_result is not None:
            observation["scope_observation"] = scope_observation_result
        if subclass_hooks is not None:
            observation["subclass_hook_calls"] = subclass_hook_calls
        if package_sequence is not None:
            observation["package_sequence_trace"] = package_sequence_trace
        if package_tuple_subclass is not None:
            observation["package_tuple_trace"] = package_tuple_trace
    observation_item = {
        "step_id": RESPONSE_OPERATION,
        "status": "ok",
        "value": observation,
    }
    if captured_error is not None:
        error = _dispatch_error(captured_error)
        error["code"] = getattr(captured_error, "status_code", None)
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


def _run_static_files_get_response_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
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
            "path",
            "scope",
            "html",
            "check_dir",
            "follow_symlink",
            "observations",
        },
        "StaticFiles get-response case",
    )
    if (
        case["surface"] != STATIC_FILES_SURFACE
        or case["operation"] != STATIC_FILES_GET_RESPONSE_OPERATION
        or case["observations"] != [STATIC_FILES_GET_RESPONSE_OPERATION]
    ):
        raise ValueError("workflow is outside the StaticFiles get-response operation")

    from starlette.staticfiles import StaticFiles

    with tempfile.TemporaryDirectory(
        prefix="starlette-package-static-response-"
    ) as temporary_directory:
        root = Path(temporary_directory) / case["directory"]
        root.mkdir(parents=True)
        for file_spec in case["files"]:
            path = root / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_decode_base64(file_spec["contents_base64"], "file.contents_base64"))
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        application = StaticFiles(
            directory=root,
            html=case["html"],
            check_dir=case["check_dir"],
            follow_symlink=case["follow_symlink"],
        )

        async def get_response() -> Any:
            return await application.get_response(case["path"], case["scope"])

        try:
            response = asyncio.run(get_response())
        except Exception as exc:
            error = _dispatch_error(exc)
            error["code"] = getattr(exc, "status_code", None)
            observation_item = {
                "step_id": STATIC_FILES_GET_RESPONSE_OPERATION,
                "status": "error",
                "error": error,
                "partial_value": {
                    "response_class": None,
                    "response_status": None,
                    "ordered_repeated_headers": None,
                },
            }
        else:
            observation = {
                "response_class": f"{type(response).__module__}.{type(response).__qualname__}",
                "response_status": getattr(response, "status_code", None),
                "ordered_repeated_headers": [
                    [
                        base64.b64encode(name).decode("ascii"),
                        base64.b64encode(value).decode("ascii"),
                    ]
                    for name, value in getattr(response, "raw_headers", [])
                ],
            }
            observation_item = {
                "step_id": STATIC_FILES_GET_RESPONSE_OPERATION,
                "status": "ok",
                "value": observation,
            }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [observation_item],
    }


def _static_files_lookup_error_observation(error: BaseException) -> dict[str, str]:
    if isinstance(error, PermissionError):
        return {"category": "permission-error"}
    if isinstance(error, ValueError):
        return {"category": "value-error"}
    if isinstance(error, OSError):
        return {"category": "os-error"}
    return {
        "category": "other-error",
        "class": f"{type(error).__module__}.{type(error).__qualname__}",
    }


def _run_static_files_lookup_path_case(case: dict[str, Any]) -> dict[str, Any]:
    has_pathlike = "directory_pathlike" in case
    case_fields = {
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
    }
    if has_pathlike:
        case_fields.add("directory_pathlike")
    observe_lookup_error = case.get("observe_lookup_error", False)
    if "observe_lookup_error" in case:
        case_fields.add("observe_lookup_error")
    _exact_object(
        case,
        case_fields,
        "StaticFiles lookup-path case",
    )
    expected_observations = [STATIC_FILES_LOOKUP_PATH_OPERATION]
    if (
        case["surface"] != STATIC_FILES_SURFACE
        or case["operation"] != STATIC_FILES_LOOKUP_PATH_OPERATION
        or case["observations"] != expected_observations
    ):
        raise ValueError("workflow is outside the declared StaticFiles lookup-path operation")

    lookup_path_is_subclass = isinstance(case["lookup_path"], dict) and set(
        case["lookup_path"]
    ) == {"str_subclass"}
    has_filesystem_byte_path = (
        isinstance(case["lookup_path"], dict) and not lookup_path_is_subclass
    ) or any(isinstance(file_spec.get("path"), dict) for file_spec in case["files"])
    if has_filesystem_byte_path and os.name != "posix":
        return {
            "case_id": case["case_id"],
            "status": "skipped",
            "observations": [
                {
                    "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
                    "status": "skipped",
                    "reason": (
                        "filesystem-byte paths require POSIX filesystem surrogateescape support"
                    ),
                }
            ],
        }

    from starlette.staticfiles import StaticFiles

    with tempfile.TemporaryDirectory(
        prefix="starlette-package-static-lookup-"
    ) as temporary_directory:
        workspace = Path(temporary_directory)
        root = workspace / case["directory"] if case["directory"] is not None else None
        root_symlink_target = case["filesystem"]["root_symlink_target"]
        if root is not None:
            if root_symlink_target is None:
                root.mkdir(parents=True)
            else:
                target_directory = workspace / root_symlink_target
                target_directory.mkdir(parents=True, exist_ok=True)
                root.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(os.path.relpath(target_directory, root.parent), root)
        for file_spec in case["files"]:
            if root is None:
                raise ValueError("StaticFiles lookup-path file input has no configured root")
            file_path = file_spec["path"]
            if isinstance(file_path, dict):
                file_path = _exact_object(
                    file_path,
                    {"encoding", "data"},
                    "StaticFiles lookup-path file encoded path",
                )
                if file_path["encoding"] != "filesystem-bytes-base64":
                    raise ValueError(
                        "StaticFiles lookup-path file encoding must be filesystem-bytes-base64"
                    )
                file_path = os.fsdecode(
                    _decode_base64(file_path["data"], "StaticFiles lookup-path file path data")
                )
            path = root / file_path
            has_surrogateescape = any(0xDC80 <= ord(char) <= 0xDCFF for char in file_path)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    _decode_base64(file_spec["contents_base64"], "file.contents_base64")
                )
                os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
            except OSError as exc:
                if not has_surrogateescape or (
                    not isinstance(exc, PermissionError) and exc.errno != errno.EILSEQ
                ):
                    raise
                return {
                    "case_id": case["case_id"],
                    "status": "skipped",
                    "observations": [
                        {
                            "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
                            "status": "skipped",
                            "reason": (
                                "the temporary filesystem cannot create the input's "
                                "POSIX surrogateescape filename"
                            ),
                        }
                    ],
                }
        for directory in case["filesystem"]["directories"]:
            (workspace / directory).mkdir(parents=True, exist_ok=True)
        for file_spec in case["filesystem"]["outside_files"]:
            path = workspace / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                _decode_base64(file_spec["contents_base64"], "outside_file.contents_base64")
            )
            os.utime(path, (file_spec["mtime_seconds"], file_spec["mtime_seconds"]))
        for symlink_spec in case["filesystem"]["symlinks"]:
            if root is None:
                raise ValueError("StaticFiles lookup-path symlink input has no configured root")
            path = root / symlink_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(symlink_spec["target"], path)
        directory_pathlike = None
        configured_directory: Any = root
        if has_pathlike:
            if root is None:
                raise ValueError("StaticFiles lookup-path PathLike input has no configured root")
            directory_pathlike = InputSequencePathLike(
                workspace,
                case["directory_pathlike"]["fspath_results_relative_to_workspace"],
            )
            configured_directory = directory_pathlike
        lookup_path_input = case["lookup_path"]
        if lookup_path_is_subclass:
            lookup_path = _materialize_scope_path_spec(lookup_path_input)
        elif isinstance(lookup_path_input, dict):
            lookup_path_input = _exact_object(
                lookup_path_input,
                {"encoding", "data"},
                "StaticFiles lookup-path encoded path",
            )
            if lookup_path_input["encoding"] != "filesystem-bytes-base64":
                raise ValueError("StaticFiles lookup-path encoding must be filesystem-bytes-base64")
            lookup_path = os.fsdecode(
                _decode_base64(
                    lookup_path_input["data"],
                    "StaticFiles lookup-path encoded data",
                )
            )
        elif isinstance(lookup_path_input, str):
            lookup_path = lookup_path_input
        else:
            raise ValueError(
                "StaticFiles lookup-path must be a string or tagged filesystem-byte value"
            )
        application = StaticFiles(
            directory=configured_directory,
            check_dir=case["check_dir"],
            follow_symlink=case["follow_symlink"],
        )
        try:
            full_path, stat_result = application.lookup_path(lookup_path)
        except Exception as exc:
            if observe_lookup_error:
                observation = {
                    "resolved_path": None,
                    "stat_result_present": False,
                    "mode_type_bits": None,
                    "is_file": None,
                    "is_directory": None,
                    "size": None,
                    "mtime_seconds": None,
                    "lookup_error": _static_files_lookup_error_observation(exc),
                }
            else:
                observation = {
                    "lookup_error": {
                        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                        "message": str(exc),
                    }
                }
        else:
            if directory_pathlike is None:
                relative_path = (
                    Path(full_path)
                    .relative_to(root.absolute() if case["follow_symlink"] else root.resolve())
                    .as_posix()
                    if full_path and root is not None
                    else None
                )
            else:
                relative_path = (
                    Path(full_path).relative_to(workspace).as_posix() if full_path else None
                )
            resolved_path = _filesystem_path_observation(relative_path)
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
            if observe_lookup_error:
                observation["lookup_error"] = None
        if directory_pathlike is not None:
            observation["directory-fspath-call-order.results_relative_to_workspace"] = (
                directory_pathlike.observation()["results_relative_to_workspace"]
            )
    observations = [
        {
            "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
            "status": "ok",
            "value": observation,
        }
    ]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": observations,
    }


def _filesystem_path_observation(path: str | None) -> Any:
    if path is None:
        return None
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return {
            "encoding": "filesystem-bytes-base64",
            "data": base64.b64encode(os.fsencode(path)).decode("ascii"),
        }
    return path


def _run_static_files_async_boundary_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
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
        prefix="starlette-package-static-async-boundary-"
    ) as temporary_directory:
        root = Path(temporary_directory) / case["directory"]
        root.mkdir(parents=True)
        for file_spec in case["files"]:
            path = root / file_spec["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_decode_base64(file_spec["contents_base64"], "file.contents_base64"))
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


def _apply_response_cookie_action(response: Any, raw_action: dict[str, Any], index: int) -> None:
    context = f"Response cookie_actions[{index}]"
    method = raw_action.get("method") if isinstance(raw_action, dict) else None
    if method == "set":
        action = _exact_object(
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
        action = _exact_object(
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


def _apply_response_header_action(response: Any, raw_action: dict[str, Any], index: int) -> Any:
    context = f"Response header_actions[{index}]"
    kind = raw_action.get("kind") if isinstance(raw_action, dict) else None
    if not isinstance(kind, str):
        raise ValueError(f"{context}.kind must be a string")
    keys = {
        "get": {"kind", "key"},
        "get-values": {"kind", "key"},
        "set": {"kind", "key", "value"},
        "append": {"kind", "key", "value"},
        "delete": {"kind", "key"},
    }.get(kind)
    if keys is None:
        raise ValueError(f"{context}.kind is unsupported")
    action = _exact_object(raw_action, keys, context)
    if not isinstance(action["key"], str):
        raise ValueError(f"{context}.key must be a string")
    if kind == "get":
        return response.headers.get(action["key"])
    if kind == "get-values":
        return response.headers.getlist(action["key"])
    if kind in {"set", "append"} and not isinstance(action["value"], str):
        raise ValueError(f"{context}.value must be a string")
    if kind == "set":
        response.headers[action["key"]] = action["value"]
    elif kind == "append":
        response.headers.append(action["key"], action["value"])
    else:
        del response.headers[action["key"]]
    return None


def _apply_response_header_actions(response: Any, actions: list[dict[str, Any]]) -> list[Any]:
    results = []
    for index, action in enumerate(actions):
        result = _apply_response_header_action(response, action, index)
        if action["kind"] in {"get", "get-values"}:
            results.append(result)
    return results


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
            key
            for key in (
                "background",
                "receive_behavior",
                "stream_lifecycle",
                "call_time_field_assignments",
            )
            if key in case
        )
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

    content_value = case["content"]
    content_keys = {"kind", "value"}
    if isinstance(content_value, dict) and content_value.get("kind") == "repeating-chunks":
        content_keys.add("checkpoint")
    if (
        surface == STREAMING_RESPONSE_SURFACE
        and isinstance(content_value, dict)
        and "sync_iterator_failure" in content_value
    ):
        content_keys.add("sync_iterator_failure")
    content_spec = _exact_object(content_value, content_keys, "Response content")
    content_kind = content_spec["kind"]
    streaming: str | None = None
    repeating_stream = False
    sync_iterator_failure_spec = None
    if surface == STREAMING_RESPONSE_SURFACE:
        if content_kind == "file-like-bytes":
            encoded_content = content_spec["value"]
            if not isinstance(encoded_content, str):
                raise ValueError("StreamingResponse file-like content must be base64 text")
            content = io.BytesIO(_decode_base64(encoded_content, "content.value"))
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
                elif chunk_spec["kind"] == "memoryview-base64":
                    encoded_chunk = chunk_spec["value"]
                    if not isinstance(encoded_chunk, str):
                        raise ValueError(
                            "StreamingResponse memoryview chunks must be base64 strings"
                        )
                    chunk = memoryview(
                        _decode_base64(encoded_chunk, f"content.value[{index}].value")
                    )
                else:
                    raise ValueError(
                        "StreamingResponse chunks must be text, bytes, or memoryview input"
                    )
                content.append(chunk)
        sync_iterator_failure_spec = content_spec.get("sync_iterator_failure")
        streaming = case["streaming"]
        if streaming not in {
            "sync",
            "file-like",
            "async-iterator",
            "async-iterable",
            "async-iterator-await-factory-stop",
            "async-iterator-invalid-anext",
            STREAMING_RESPONSE_AWAIT_INSTANCE_SHADOW_MODE,
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
            content = _decode_base64(encoded_content, "content.value")
        elif content_kind == "memoryview-base64":
            encoded_content = content_spec["value"]
            if not isinstance(encoded_content, str):
                raise ValueError("Response memoryview content value must be a string")
            content = memoryview(_decode_base64(encoded_content, "content.value"))
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
    minimal_streaming_scope = surface == STREAMING_RESPONSE_SURFACE and case["scope"] == {
        "type": "http"
    }
    scope_spec = _exact_object(
        case["scope"],
        {"type"} if minimal_streaming_scope else scope_fields,
        "Response ASGI-call scope",
    )
    if scope_spec["type"] == "websocket" and surface != STREAMING_RESPONSE_SURFACE:
        raise ValueError("WebSocket scope is supported only for StreamingResponse")
    asgi_spec = (
        {}
        if minimal_streaming_scope
        else _exact_object(scope_spec["asgi"], {"version", "spec_version"}, "ASGI version")
    )
    if any(not isinstance(asgi_spec[key], str) for key in asgi_spec):
        raise ValueError("ASGI versions must be strings")
    scope_string_fields = ["http_version", "scheme", "path", "root_path"]
    if scope_spec["type"] == "http":
        scope_string_fields.append("method")
    for field in scope_string_fields if not minimal_streaming_scope else ():
        if not isinstance(scope_spec[field], str):
            raise ValueError(f"Response scope.{field} must be a string")
    if scope_spec["type"] == "websocket" and (
        not isinstance(scope_spec["subprotocols"], list)
        or any(not isinstance(item, str) for item in scope_spec["subprotocols"])
    ):
        raise ValueError("Response WebSocket scope subprotocols must be strings")
    headers = scope_spec.get("headers_base64_pairs", [])
    if not isinstance(headers, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or any(not isinstance(value, str) for value in pair)
        for pair in headers
    ):
        raise ValueError("Response HTTP scope headers must be base64 string pairs")
    for field in ("client", "server") if not minimal_streaming_scope else ():
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
    send_gate_spec: dict[str, Any] | None = None
    send_cancellation_spec: dict[str, Any] | None = None
    if case["send"] != {"kind": "capture-asgi-send"}:
        if surface != STREAMING_RESPONSE_SURFACE:
            raise ValueError("send input must select the declared ASGI message collector")
        if case["send"].get("kind") == "capture-asgi-send-with-checkpoint-gate":
            send_gate_spec = _exact_object(
                case["send"],
                {"kind", "event_index", "release_after_checkpoints"},
                "StreamingResponse gated send",
            )
            if (
                type(send_gate_spec["event_index"]) is not int
                or send_gate_spec["event_index"] < 0
                or type(send_gate_spec["release_after_checkpoints"]) is not int
                or send_gate_spec["release_after_checkpoints"] < 1
            ):
                raise ValueError("StreamingResponse gated send input is invalid")
        elif case["send"].get("kind") == "capture-asgi-send-with-caller-cancellation":
            send_cancellation_spec = _exact_object(
                case["send"],
                {"kind", "event_index"},
                "StreamingResponse caller-cancelled send",
            )
            if (
                send_cancellation_spec["kind"] != "capture-asgi-send-with-caller-cancellation"
                or type(send_cancellation_spec["event_index"]) is not int
                or send_cancellation_spec["event_index"] != 1
            ):
                raise ValueError("StreamingResponse caller-cancelled send input is invalid")
        else:
            send_error_spec = _exact_object(
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

    background_control: dict[str, str] | None = None
    if "background_control" in case:
        background_control = _exact_object(
            case["background_control"], {"kind"}, "Response background control"
        )
        if (
            background_control["kind"]
            not in {
                "cancel-after-task-start",
                "cancel-scope-after-task-start",
            }
            or surface != RESPONSE_SURFACE
        ):
            raise ValueError("Response background control is unsupported")

    background_values: list[str] | None = None
    background_failure: dict[str, str] | None = None
    background_callable_failure: dict[str, str] | None = None
    background_tasks_spec: dict[str, Any] | None = None
    if "background" in case:
        if not isinstance(case["background"], dict):
            raise ValueError("Response background input must be an object")
        if case["background"].get("kind") == "async-values-recorder":
            background_fields = {"kind", "values"}
            if "failure" in case["background"]:
                background_fields.add("failure")
            background_spec = _exact_object(
                case["background"], background_fields, "Response background"
            )
            values = background_spec["values"]
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("Response background values must be an array of strings")
            background_values = values
            if "failure" in background_spec:
                failure = _exact_object(
                    background_spec["failure"], {"kind", "message"}, "Response background failure"
                )
                if failure["kind"] != "OSError" or not isinstance(failure["message"], str):
                    raise ValueError("Response background failure input is unsupported")
                background_failure = failure
        elif case["background"].get("kind") == "sync-callable-error":
            background_spec = _exact_object(
                case["background"], {"kind", "failure"}, "Response background callable"
            )
            failure = _exact_object(
                background_spec["failure"],
                {"class", "message"},
                "Response background callable failure",
            )
            if failure["class"] not in {"OSError", "RuntimeError", "ValueError"} or not isinstance(
                failure["message"], str
            ):
                raise ValueError("Response background callable failure input is unsupported")
            background_callable_failure = failure
        else:
            background_fields = {"kind", "tasks"}
            if case["background"].get("kind") == "task-list-subclass-property":
                background_fields.add("tasks_property_indices")
                if "add_task" in case["background"]:
                    background_fields.add("add_task")
            if case["background"].get("kind") == "single-task-subclass-properties":
                background_fields.add("public_attributes")
            background_tasks_spec = _exact_object(
                case["background"], background_fields, "Response background tasks"
            )
            if background_tasks_spec["kind"] not in {
                "single-task",
                "single-task-subclass-properties",
                "task-list",
                "task-list-constructor",
                "task-list-subclass-property",
            }:
                raise ValueError("Response background task kind is unsupported")
            if not isinstance(background_tasks_spec["tasks"], list):
                raise ValueError("Response background tasks must be an array")
            if background_tasks_spec["kind"] == "task-list-subclass-property":
                task_indices = background_tasks_spec["tasks_property_indices"]
                if not isinstance(task_indices, list) or any(
                    not isinstance(index, int) or isinstance(index, bool) for index in task_indices
                ):
                    raise ValueError("Response background task property indices must be integers")
                if any(
                    index < 0 or index >= len(background_tasks_spec["tasks"])
                    for index in task_indices
                ):
                    raise ValueError("Response background task property index is out of range")
                if "add_task" in background_tasks_spec:
                    add_task = _exact_object(
                        background_tasks_spec["add_task"],
                        {"mode", "args", "kwargs", "failure"},
                        "Response background subclass add_task",
                    )
                    if add_task["mode"] not in {"sync", "async"}:
                        raise ValueError("Response background subclass add_task mode is invalid")
                    if not isinstance(add_task["args"], list) or any(
                        type(value) not in {str, int} for value in add_task["args"]
                    ):
                        raise ValueError("Response background subclass add_task args are invalid")
                    if not isinstance(add_task["kwargs"], dict) or any(
                        not isinstance(key, str) or type(value) not in {str, int}
                        for key, value in add_task["kwargs"].items()
                    ):
                        raise ValueError("Response background subclass add_task kwargs are invalid")
                    if add_task["failure"] is not None:
                        raise ValueError(
                            "Response background subclass add_task failure is unsupported"
                        )

    stream_lifecycle: dict[str, str] | None = None
    if "stream_lifecycle" in case:
        if not isinstance(case["stream_lifecycle"], dict):
            raise ValueError("Response stream lifecycle recorder must be an object")
        stream_lifecycle_spec = case["stream_lifecycle"]
        if stream_lifecycle_spec["kind"] == "finally-recorder":
            stream_lifecycle_spec = _exact_object(
                stream_lifecycle_spec,
                {"kind", "finally_marker"},
                "Response stream finalization recorder",
            )
        elif stream_lifecycle_spec["kind"] == "cancellation-and-finally-recorder":
            stream_lifecycle_spec = _exact_object(
                stream_lifecycle_spec,
                {"kind", "cancellation_marker", "finally_marker"},
                "Response stream lifecycle recorder",
            )
            if (
                not isinstance(stream_lifecycle_spec["cancellation_marker"], str)
                or not stream_lifecycle_spec["cancellation_marker"]
            ):
                raise ValueError("Response stream lifecycle cancellation_marker is invalid")
        else:
            raise ValueError("Response stream lifecycle recorder kind is unsupported")
        for key in ("finally_marker",):
            if not isinstance(stream_lifecycle_spec[key], str) or not stream_lifecycle_spec[key]:
                raise ValueError(f"Response stream lifecycle {key} must be a non-empty string")
        stream_lifecycle = stream_lifecycle_spec

    receive_behavior: dict[str, Any] | None = None
    if "receive_behavior" in case:
        receive_behavior_value = case["receive_behavior"]
        if not isinstance(receive_behavior_value, dict):
            raise ValueError("Response receive behavior input must be an object")
        if receive_behavior_value.get("kind") == "disconnect-after-body-bytes":
            receive_behavior = _exact_object(
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
            receive_behavior = _exact_object(
                receive_behavior_value,
                {"kind"},
                "Response receive behavior",
            )
        elif receive_behavior_value.get("kind") == "block-until-cancelled":
            receive_behavior = _exact_object(
                receive_behavior_value,
                {"kind", "finally_marker"},
                "Response receive behavior",
            )
            if (
                not isinstance(receive_behavior["finally_marker"], str)
                or not receive_behavior["finally_marker"]
            ):
                raise ValueError("Response receive behavior finally_marker is invalid")
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
    background_finished = asyncio.Event() if synchronous_background_control else None
    background_event_loop: list[asyncio.AbstractEventLoop | None] = [None]

    from starlette.responses import JSONResponse, Response, StreamingResponse

    response_type = {
        RESPONSE_SURFACE: Response,
        JSON_RESPONSE_SURFACE: JSONResponse,
        STREAMING_RESPONSE_SURFACE: StreamingResponse,
    }[surface]
    render_override = case.get("render_override")
    if render_override is not None:
        render_override = _exact_object(
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
        if sync_iterator_failure_spec is not None:
            from scripts.parity.adapters.response_protocols import input_sync_iterable_failure

            content = input_sync_iterable_failure(content, sync_iterator_failure_spec)
        else:
            content = (
                _input_sync_iterator(content, execution_trace)
                if execution_trace is not None
                else iter(content)
            )
    elif streaming == "async-iterator":
        content = _InputAsyncIterator(content, execution_trace)
    elif streaming == "async-iterator-invalid-anext":
        invalid_result = content[0]

        class InputAsyncIteratorInvalidAnext:
            def __aiter__(self) -> InputAsyncIteratorInvalidAnext:
                return self

            def __anext__(self) -> Any:
                return invalid_result

        content = InputAsyncIteratorInvalidAnext()
    elif streaming == "async-iterable":
        content = _InputAsyncIterable(content, execution_trace)
    elif streaming == "async-iterator-await-factory-stop":

        class InputAwaitableStop:
            def __await__(self) -> Iterator[Any]:
                yield from ()
                raise StopAsyncIteration

        class InputAsyncIteratorAwaitFactoryStop:
            def __aiter__(self) -> InputAsyncIteratorAwaitFactoryStop:
                return self

            def __anext__(self) -> InputAwaitableStop:
                return InputAwaitableStop()

        content = InputAsyncIteratorAwaitFactoryStop()
    elif streaming == STREAMING_RESPONSE_AWAIT_INSTANCE_SHADOW_MODE:
        if len(content) != 2:
            raise ValueError("StreamingResponse awaitable lookup requires two input values")
        await_results = content

        def input_await_result(value: Any) -> Iterator[Any]:
            yield from ()
            return value

        class InputAwaitableInstanceShadow:
            def __init__(self, type_result: Any, instance_result: Any) -> None:
                self.type_result = type_result
                self.instance_result = instance_result

            def __await__(self) -> Iterator[Any]:
                return input_await_result(self.type_result)

        class InputAsyncIteratorAwaitInstanceShadow:
            def __init__(self) -> None:
                self.returned_item = False

            def __aiter__(self) -> InputAsyncIteratorAwaitInstanceShadow:
                return self

            def __anext__(self) -> Any:
                if self.returned_item:

                    async def exhausted() -> Any:
                        raise StopAsyncIteration

                    return exhausted()
                self.returned_item = True
                awaitable = InputAwaitableInstanceShadow(await_results[0], await_results[1])
                awaitable.__await__ = lambda: input_await_result(awaitable.instance_result)
                return awaitable

        content = InputAsyncIteratorAwaitInstanceShadow()
    elif streaming == "async-generator":
        if repeating_stream:
            if execution_trace is None or stream_lifecycle is None:
                raise ValueError("repeating async generator requires its lifecycle trace")
            content = _input_repeating_async_generator(
                content, execution_trace, stream_lifecycle, content_spec["checkpoint"]
            )
        else:
            finally_marker = (
                stream_lifecycle["finally_marker"]
                if stream_lifecycle is not None and stream_lifecycle["kind"] == "finally-recorder"
                else None
            )
            content = _input_async_generator(content, execution_trace, finally_marker)
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
            _record_background_values, background_values, execution_trace, background_failure
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
            background_finished,
            background_event_loop,
        )
    response = response_type(**response_arguments)
    if background_callable_failure is not None:
        from scripts.parity.adapters.response_protocols import input_sync_background_failure

        response.background = input_sync_background_failure(background_callable_failure)
    for field, value in case.get("call_time_field_assignments", {}).items():
        setattr(response, field, value)
    try:
        for index, raw_action in enumerate(case.get("cookie_actions", [])):
            _apply_response_cookie_action(response, raw_action, index)
        header_action_results = (
            _apply_response_header_actions(response, case["header_actions"])
            if "header_actions" in case
            else None
        )
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
                        _decode_base64(pair[0], f"Response header_view_probe[{pair_index}].name"),
                        _decode_base64(pair[1], f"Response header_view_probe[{pair_index}].value"),
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
        if "header_actions" in case:
            partial_value["header_action_results"] = []
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
    scope = dict(scope_spec) if minimal_streaming_scope else _make_scope(scope_spec)
    sent: list[dict[str, Any]] = []
    receive_gate = (
        asyncio.Event()
        if receive_behavior is not None
        and receive_behavior["kind"] in {"disconnect-after-body-bytes", "block-until-cancelled"}
        else None
    )
    receive_entered = (
        asyncio.Event()
        if receive_behavior is not None and receive_behavior["kind"] == "block-until-cancelled"
        else None
    )
    sent_body_bytes = 0

    async def receive() -> dict[str, Any]:
        if receive_behavior is not None and receive_behavior["kind"] == "raise-not-implemented":
            raise NotImplementedError
        if receive_entered is not None:
            if execution_trace is None or receive_gate is None:
                raise RuntimeError("blocked receive behavior requires its execution trace")
            execution_trace.append({"event": "asgi-receive-enter"})
            receive_entered.set()
            try:
                await receive_gate.wait()
            finally:
                execution_trace.append(
                    {
                        "event": "asgi-receive-finally",
                        "marker": receive_behavior["finally_marker"],
                    }
                )
            return {"type": "http.disconnect"}
        if receive_gate is not None:
            await receive_gate.wait()
        message = {"type": "http.disconnect"}
        if execution_trace is not None and receive_gate is not None:
            execution_trace.append({"event": "asgi-receive", "message": _json_safe(message)})
        return message

    send_index = 0
    send_gate_entered = (
        asyncio.Event()
        if send_gate_spec is not None or send_cancellation_spec is not None
        else None
    )
    send_gate_release = (
        asyncio.Event()
        if send_gate_spec is not None or send_cancellation_spec is not None
        else None
    )

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index, sent_body_bytes
        if send_error_spec is not None and send_index == send_error_spec["event_index"]:
            send_index += 1
            raise OSError(send_error_spec["message"])
        gated_event_index = (
            send_gate_spec["event_index"]
            if send_gate_spec is not None
            else send_cancellation_spec["event_index"]
            if send_cancellation_spec is not None
            else None
        )
        if gated_event_index is not None and send_index == gated_event_index:
            if execution_trace is None or send_gate_entered is None or send_gate_release is None:
                raise RuntimeError("StreamingResponse send gate requires its execution trace")
            execution_trace.append(
                {
                    "event": "asgi-send-enter",
                    "event_index": send_index,
                    "message": _canonical_message(message),
                }
            )
            send_gate_entered.set()
            await send_gate_release.wait()
        sent.append(message)
        if background_execution_trace is not None:
            if event_loop_thread_id[0] is None:
                event_loop_thread_id[0] = threading.get_ident()
            background_execution_trace.append(
                {"event": "asgi-send", "message": _canonical_message(message)}
            )
        if execution_trace is not None:
            execution_trace.append({"event": "asgi-send", "message": _canonical_message(message)})
            if gated_event_index is not None and send_index == gated_event_index:
                execution_trace.append({"event": "asgi-send-complete", "event_index": send_index})
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
        if send_cancellation_spec is not None:

            async def dispatch_and_cancel_response_on_blocked_send() -> None:
                nonlocal captured_error
                if send_gate_entered is None or execution_trace is None:
                    raise RuntimeError("StreamingResponse cancellation gate events are unavailable")
                response_task = asyncio.create_task(response(scope, receive, send))
                try:
                    await asyncio.wait_for(send_gate_entered.wait(), timeout=5.0)
                    if receive_entered is not None:
                        await asyncio.wait_for(receive_entered.wait(), timeout=5.0)
                    execution_trace.append({"event": "response-cancellation-requested"})
                    response_task.cancel()
                    try:
                        await response_task
                    except asyncio.CancelledError as exc:
                        captured_error = exc
                finally:
                    if not response_task.done():
                        response_task.cancel()
                        try:
                            await response_task
                        except BaseException:
                            pass

            asyncio.run(dispatch_and_cancel_response_on_blocked_send())
        elif send_gate_spec is not None:

            async def dispatch_with_gated_send() -> None:
                if send_gate_entered is None or send_gate_release is None:
                    raise RuntimeError("StreamingResponse send gate events are unavailable")

                async def release_gated_send() -> None:
                    if execution_trace is None:
                        raise RuntimeError(
                            "StreamingResponse send gate requires its execution trace"
                        )
                    await send_gate_entered.wait()
                    for _ in range(send_gate_spec["release_after_checkpoints"]):
                        await asyncio.sleep(0)
                    execution_trace.append(
                        {
                            "event": "asgi-send-gate-release",
                            "event_index": send_gate_spec["event_index"],
                        }
                    )
                    send_gate_release.set()

                response_task = asyncio.create_task(response(scope, receive, send))
                release_task = asyncio.create_task(release_gated_send())
                try:
                    await response_task
                finally:
                    if not send_gate_entered.is_set():
                        release_task.cancel()
                    if not send_gate_release.is_set():
                        send_gate_release.set()
                    try:
                        await release_task
                    except asyncio.CancelledError:
                        pass

            asyncio.run(dispatch_with_gated_send())
        elif background_control is None:
            if streaming == "async-iterator-invalid-anext":

                async def dispatch_and_capture_public_exception() -> Exception | None:
                    try:
                        await response(scope, receive, send)
                    except Exception as exc:
                        return exc
                    return None

                captured_error = asyncio.run(dispatch_and_capture_public_exception())
            else:
                asyncio.run(response(scope, receive, send))
        else:

            async def dispatch_and_cancel_background() -> None:
                if background_started is None:
                    raise RuntimeError("background cancellation event is unavailable")
                background_event_loop[0] = asyncio.get_running_loop()
                if background_control["kind"] == "cancel-scope-after-task-start":
                    if (
                        not synchronous_background_control
                        or background_execution_trace is None
                        or background_release is None
                        or background_finished is None
                    ):
                        raise RuntimeError("AnyIO background cancellation state is unavailable")
                    import anyio

                    cancel_scope = anyio.CancelScope()

                    async def cancel_scope_after_task_start() -> None:
                        try:
                            await asyncio.wait_for(background_started.wait(), timeout=5.0)
                        except BaseException:
                            background_release.set()
                            raise
                        cancel_scope.cancel()
                        await asyncio.sleep(0)
                        background_execution_trace.append(
                            {"event": "response-cancellation-requested"}
                        )
                        background_release.set()
                        await asyncio.wait_for(background_finished.wait(), timeout=5.0)

                    cancellation_task = asyncio.create_task(cancel_scope_after_task_start())
                    try:
                        with cancel_scope:
                            await response(scope, receive, send)
                    finally:
                        if not cancellation_task.done():
                            if not background_started.is_set():
                                cancellation_task.cancel()
                            background_release.set()
                        try:
                            await cancellation_task
                        except asyncio.CancelledError:
                            pass
                    return

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
                    if (
                        background_execution_trace is None
                        or background_release is None
                        or background_finished is None
                    ):
                        raise RuntimeError(
                            "synchronous background cancellation state is unavailable"
                        )
                    await asyncio.sleep(0)
                    background_execution_trace.append({"event": "response-cancellation-requested"})
                    background_release.set()
                    try:
                        await response_task
                    finally:
                        await asyncio.wait_for(background_finished.wait(), timeout=5.0)
                else:
                    await response_task

            try:
                if background_control["kind"] == "cancel-scope-after-task-start":
                    import anyio

                    anyio.run(dispatch_and_cancel_background)
                else:
                    asyncio.run(dispatch_and_cancel_background())
            except asyncio.CancelledError as exc:
                captured_error = exc
    except asyncio.CancelledError as exc:
        if background_tasks_spec is None:
            raise
        captured_error = exc
    except Exception as exc:
        if (
            send_error_spec is None
            and background_failure is None
            and background_callable_failure is None
            and background_tasks_spec is None
            and sync_iterator_failure_spec is None
        ):
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
    if header_action_results is not None:
        observation["header_action_results"] = header_action_results
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


def _reverse_lookup_path_params(lookup: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime
    from uuid import UUID

    return {
        name: datetime(*value["components"])  # noqa: DTZ001  # Preserve Starlette's naive converter value.
        if isinstance(value, dict) and value["kind"] == "datetime-components"
        else UUID(value["value"])
        if isinstance(value, dict) and value["kind"] == "uuid-value"
        else value
        for name, value in lookup["path_params"].items()
    }


def _build_reverse_route_middleware(specs: list[dict[str, Any]]) -> list[Any]:
    from starlette.middleware import Middleware

    configurations = []
    for spec in specs:
        if spec["kind"] == "middleware-iterator-subclass":
            iterated = spec["iterated"]
            if iterated["kind"] == "dict-subclass-kwargs":
                stored_key = iterated["stored_key"]
                stored_value = iterated["stored_value"]
                keys_result = iterated["keys_result"]
                getitem_result = iterated["getitem_result"]
                defaults = iterated["defaults"]
                header_name = iterated["header_name"]

                def make_input_middleware_kwargs_type(
                    input_keys_result: list[str], input_getitem_result: Any
                ) -> type[dict[str, Any]]:
                    class InputMiddlewareKwargs(dict[str, Any]):
                        def keys(self) -> list[str]:
                            return list(input_keys_result)

                        def __getitem__(self, _key: str) -> Any:
                            return input_getitem_result

                    return InputMiddlewareKwargs

                def make_input_dict_subclass_kwargs_middleware(
                    input_header_name: str, input_defaults: dict[str, str]
                ) -> type[Any]:
                    class InputDictSubclassKwargsMiddleware:
                        def __init__(
                            self,
                            app: Any,
                            *,
                            stored: str = input_defaults["stored"],
                            phantom: str = input_defaults["phantom"],
                        ) -> None:
                            self.app = app
                            self.response_header = (
                                input_header_name.encode("ascii"),
                                f"{stored}|{phantom}".encode("latin-1"),
                            )

                        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                            async def modified_send(message: Any) -> None:
                                if message["type"] == "http.response.start":
                                    message["headers"].append(self.response_header)
                                await send(message)

                            await self.app(scope, receive, modified_send)

                    return InputDictSubclassKwargsMiddleware

                input_kwargs_type = make_input_middleware_kwargs_type(keys_result, getitem_result)
                middleware_factory = make_input_dict_subclass_kwargs_middleware(
                    header_name, defaults
                )
                configurations.append(
                    middleware_with_iterator_override(
                        Middleware,
                        middleware_factory,
                        middleware_factory,
                        [],
                        input_kwargs_type({stored_key: stored_value}),
                    )
                )
                continue

            if iterated["kind"] != "append-response-header":
                raise ValueError(
                    "route middleware iterator subclass must yield a declared middleware factory"
                )

            class InputAppendResponseHeaderMiddleware:
                def __init__(self, app: Any, *, name: str, value: str) -> None:
                    self.app = app
                    self.response_header = (
                        f"X-{name}".encode("ascii"),
                        value.encode("latin-1"),
                    )

                async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                    async def modified_send(message: Any) -> None:
                        if message["type"] == "http.response.start":
                            message["headers"].append(self.response_header)
                        await send(message)

                    await self.app(scope, receive, modified_send)

            configurations.append(
                middleware_with_iterator_override(
                    Middleware,
                    InputAppendResponseHeaderMiddleware,
                    InputAppendResponseHeaderMiddleware,
                    [],
                    MappingProxyType({"name": iterated["name"], "value": iterated["value"]}),
                )
            )
            continue

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


class _InputFalseyMiddlewareSequence(list[Any]):
    def __bool__(self) -> bool:
        return False


def _request_url_value(request: Any, lookup: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"url": str(request.url_for(lookup["name"], **_reverse_lookup_path_params(lookup)))}
    except Exception as exc:
        return {"error": _reverse_url_error(exc)}


def _build_reverse_route_node(
    node: dict[str, Any], lookup: dict[str, Any], observation: dict[str, Any]
) -> Any:
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Host, Mount, Route, Router, WebSocketRoute

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
        mount_arguments = {}
        if "middleware" in node:
            mount_arguments["middleware"] = _build_reverse_route_middleware(node["middleware"])
        if "app" in node:
            app_spec = node["app"]
            if app_spec["kind"] == "http-route":
                app = _build_reverse_route_node(app_spec, lookup, observation)
            else:

                async def no_op_asgi(scope: Any, receive: Any, send: Any) -> None:
                    del scope, receive, send

                if "routes" in app_spec:
                    no_op_asgi.routes = app_spec["routes"]

                app = no_op_asgi
            return Mount(node["path"], app=app, name=node["name"], **mount_arguments)
        return Mount(
            node["path"],
            routes=[
                _build_reverse_route_node(child, lookup, observation) for child in node["routes"]
            ],
            name=node["name"],
            **mount_arguments,
        )
    if kind == "starlette-app":
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

    missing = object()
    previous_convertors = {
        spec["name"]: CONVERTOR_TYPES.get(spec["name"], missing)
        for spec in case["custom_convertors"]
    }
    observation: dict[str, Any] = {}
    lookup = dict(case["lookup"])
    lookup_name = lookup["name"]
    if "lookup_name_subclass" in case:
        startswith_result = case["lookup_name_subclass"]["startswith_result"]

        class InputLookupName(str):
            def startswith(self, prefix: str) -> bool:
                del prefix
                return startswith_result

        lookup_name = InputLookupName(lookup_name)
        lookup["name"] = lookup_name

    request_type = Request
    base_url_property_reads: list[str] = []
    if "base_url_override" in case:
        from starlette.datastructures import URL

        base_url = URL(case["base_url_override"]["value"])

        class InputBaseURLPropertyRequest(Request):
            @property
            def base_url(self) -> URL:
                base_url_property_reads.append("get")
                return base_url

        request_type = InputBaseURLPropertyRequest

    def observe_request_url(scope: dict[str, Any]) -> dict[str, Any]:
        result = _request_url_value(request_type(scope), lookup)
        if "base_url_override" in case:
            result["base_url_property_reads"] = list(base_url_property_reads)
        return result

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
            graph = (
                None
                if graph_spec is None
                else _build_reverse_route_node(graph_spec, lookup, observation)
            )

            async def run_request() -> dict[str, Any]:
                scope = _reverse_request_scope(request_scope)
                provider = request_scope["provider"]
                if provider == "none":
                    return observe_request_url(scope)
                if provider == "router":
                    scope["router"] = graph
                    return observe_request_url(scope)
                if provider == "app":
                    scope["app"] = graph
                    return observe_request_url(scope)

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
            path_params = _reverse_lookup_path_params(lookup)
            result = graph.url_path_for(lookup_name, **path_params)
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


def _exception_value_snapshot(instance: Any, fields: tuple[str, ...], phase: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "fields": {name: _json_safe(getattr(instance, name)) for name in fields},
        "str": str(instance),
        "repr": repr(instance),
    }


def _run_default_receive_case(case: dict[str, Any]) -> dict[str, Any]:
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
    case_keys = {
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
    }
    if "headers_property" in case:
        case_keys.add("headers_property")
    _exact_object(
        case,
        case_keys,
        "Request send-push-promise case",
    )
    from starlette.requests import Request

    sent_messages: list[dict[str, Any]] = []
    callback_calls = 0
    callback_spec = case["send_callback"]
    callback_error: BaseException | None = None
    callback_cause: BaseException | None = None
    callback_context: BaseException | None = None
    headers_property_reads: list[str] = []
    request_type = Request
    if "headers_property" in case:
        from starlette.datastructures import Headers

        header_pairs = [
            (
                _decode_base64(name, "headers_property header name"),
                _decode_base64(value, "headers_property header value"),
            )
            for name, value in case["headers_property"]["headers_base64_pairs"]
        ]
        headers_value = Headers(raw=header_pairs)

        class InputHeadersPropertyRequest(Request):
            @property
            def headers(self) -> Headers:
                headers_property_reads.append("get")
                return headers_value

        request_type = InputHeadersPropertyRequest

    async def capture_send(message: dict[str, Any]) -> None:
        nonlocal callback_calls
        callback_calls += 1
        sent_messages.append(message)

    scope = _make_scope(case["scope"])
    if callback_spec["kind"] == "capture":
        request = request_type(scope, send=capture_send)
    elif callback_spec["kind"] == "raise":
        exception_types = {
            "LookupError": LookupError,
            "RuntimeError": RuntimeError,
            "ValueError": ValueError,
        }
        exception_spec = callback_spec["exception"]
        error_to_raise = exception_types[exception_spec["class"]](exception_spec["message"])
        cause_to_raise = exception_types[exception_spec["cause"]["class"]](
            exception_spec["cause"]["message"]
        )
        context_to_raise = exception_types[exception_spec["context"]["class"]](
            exception_spec["context"]["message"]
        )
        callback_error = error_to_raise
        callback_cause = cause_to_raise
        callback_context = context_to_raise

        async def raise_send(message: dict[str, Any]) -> None:
            nonlocal callback_calls
            callback_calls += 1
            sent_messages.append(message)
            try:
                raise context_to_raise
            except Exception:
                raise error_to_raise from cause_to_raise

        request = request_type(scope, send=raise_send)
    else:
        request = request_type(scope)

    async def observe() -> dict[str, Any]:
        try:
            await request.send_push_promise(case["path"])
        except Exception as exc:
            error = {
                "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                "message": str(exc),
            }
            if callback_error is not None:

                def observe_link(
                    linked_error: BaseException | None,
                    expected_error: BaseException | None,
                ) -> dict[str, Any] | None:
                    if linked_error is None:
                        return None
                    return {
                        "class": f"{type(linked_error).__module__}.{type(linked_error).__qualname__}",
                        "message": str(linked_error),
                        "identity_preserved": linked_error is expected_error,
                    }

                error.update(
                    {
                        "callback_exception_identity": exc is callback_error,
                        "cause": observe_link(exc.__cause__, callback_cause),
                        "context": observe_link(exc.__context__, callback_context),
                        "suppress_context": exc.__suppress_context__,
                    }
                )
            result = {
                "outcome": "error",
                "error": error,
                "sent": _json_safe(sent_messages),
            }
        else:
            result = {"outcome": "value", "sent": _json_safe(sent_messages)}
        if callback_spec["kind"] == "raise":
            result["callback_calls"] = callback_calls
        if "headers_property" in case:
            result["headers_property_reads"] = headers_property_reads
        return result

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
    incoming = [_make_message(message) for message in case["receive"]]
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
        "form_close_override_result",
        "form_context_exception",
        "form_file_probe_keys",
        "form_file_probe_all",
        "form_type_probe_keys",
        "form_file_read_size",
        "form_file_write_base64",
        "form_close",
        "form_io_trace",
        "receive_error",
        "file_write_error",
        "file_rollover_error",
        "form_app",
        "form_read_body",
        "form_rollover_event_loop_progress",
        "rollover_progress_timeout_ms",
        "form_error_upload_sizes",
        "form_deferred_scope_headers",
    ):
        if key in case:
            case_fields.add(key)
    _exact_object(
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
    tracked_uploads: list[Any] = []
    tempfile_write_calls = 0
    rollover_probe: dict[str, Any] = {}

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
        if case.get("form_rollover_event_loop_progress", False):
            rollover_probe["loop"] = asyncio.get_running_loop()
            rollover_probe["timeout_ms"] = case["rollover_progress_timeout_ms"]
        observed_files = []
        try:
            form_operation = request.form(**case.get("form_options", {}))
            _apply_request_form_deferred_scope_headers(scope, case)
            if case.get("form_access", "await") == "context-manager":
                async with form_operation as form:
                    if "form_close_override_result" in case:

                        async def close_with_input_result() -> bool:
                            return case["form_close_override_result"]

                        form.close = close_with_input_result
                    context_exception = case.get("form_context_exception")
                    if context_exception is not None:
                        exception_type = getattr(builtins, context_exception["class"])
                        raise exception_type(context_exception["message"])
                    value, observed_files = await inspect_form(form)
            else:
                form = await form_operation
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
                    **(
                        {"upload_sizes_after_error": [upload.size for upload in tracked_uploads]}
                        if case.get("form_error_upload_sizes", False)
                        else {}
                    ),
                },
            }
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
                form_operation = request.form(**case.get("form_options", {}))
                _apply_request_form_deferred_scope_headers(app_scope, case)
                form = await form_operation
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
                loop = rollover_probe.get("loop")
                if loop is not None:
                    release = threading.Event()
                    progressed = threading.Event()

                    def release_after_event_loop_progress() -> None:
                        if not release.is_set():
                            io_trace.append(["event-loop-progress-during-rollover"])
                            progressed.set()
                            release.set()

                    timeout_seconds = rollover_probe["timeout_ms"] / 1000
                    fallback = threading.Timer(timeout_seconds, release.set)
                    fallback.daemon = True
                    fallback.start()
                    loop.call_soon_threadsafe(release_after_event_loop_progress)
                    release.wait()
                    fallback.cancel()
                    io_trace.append(["spooled-rollover-progress", progressed.is_set()])
                io_trace.append(
                    ["spooled-rollover-worker", threading.get_ident() != creation_thread]
                )
                rollover_error = case.get("file_rollover_error")
                if rollover_error is not None:
                    raise OSError(rollover_error["message"])
                result = original_rollover()
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
            if case.get("form_error_upload_sizes", False):
                tracked_uploads.append(self)
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
    return run_status_module_sequence(case, _exact_object, _json_safe)


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
    _exact_object(spec, keys_by_kind[kind], "routing endpoint shape")
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


def _run_routing_constructor_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.routing import Host, Mount, Route, WebSocketRoute

    surfaces = {
        HTTP_ROUTE_SURFACE,
        WEBSOCKET_ROUTE_SURFACE,
        MOUNT_SURFACE,
        HOST_SURFACE,
    }
    if case["surface"] not in surfaces or case["operation"] != "__init__":
        raise ValueError("routing constructor adapter received an unrelated operation")
    _exact_object(
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
        "routing constructor-error case",
    )

    fields_by_surface = {
        HTTP_ROUTE_SURFACE: {"path", "endpoint", "methods", "name"},
        WEBSOCKET_ROUTE_SURFACE: {"path", "endpoint", "name"},
        MOUNT_SURFACE: {"path", "app", "routes", "name"},
        HOST_SURFACE: {"host", "app", "name"},
    }
    results = []
    for constructor in case["attempts"]:
        _exact_object(
            constructor,
            fields_by_surface[case["surface"]],
            f"{case['surface']} constructor input",
        )
        try:
            if case["surface"] == HTTP_ROUTE_SURFACE:
                value = Route(
                    path=constructor["path"],
                    endpoint=_make_routing_endpoint(constructor["endpoint"]),
                    methods=constructor["methods"],
                    name=constructor["name"],
                )
            elif case["surface"] == WEBSOCKET_ROUTE_SURFACE:
                value = WebSocketRoute(
                    path=constructor["path"],
                    endpoint=_make_routing_endpoint(constructor["endpoint"]),
                    name=constructor["name"],
                )
            elif case["surface"] == MOUNT_SURFACE:
                app_spec = constructor["app"]
                app = None if app_spec is None else _materialize_asgi_sequence_app(app_spec)
                route_specs = constructor["routes"]
                routes = (
                    None
                    if route_specs is None
                    else [
                        Route(
                            path=route_spec["path"],
                            endpoint=_make_routing_endpoint(route_spec["endpoint"]),
                            methods=route_spec["methods"],
                            name=route_spec["name"],
                        )
                        for route_spec in route_specs
                    ]
                )
                value = Mount(
                    path=constructor["path"],
                    app=app,
                    routes=routes,
                    name=constructor["name"],
                )
            else:
                value = Host(
                    host=constructor["host"],
                    app=_materialize_asgi_sequence_app(constructor["app"]),
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
            results.append({"outcome": "constructed", "route_name": value.name})
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


def _run_route_endpoint_name_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.routing import Route

    if "attempts" in case:
        return _run_routing_constructor_case(case)

    _exact_object(
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
        _exact_object(
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
        _exact_object(spec, {"path", "endpoint", "methods", "name"}, "Route representation input")
        return Route(
            path=spec["path"],
            endpoint=_make_routing_endpoint(spec["endpoint"]),
            methods=spec["methods"],
            name=spec["name"],
        )
    if surface == WEBSOCKET_ROUTE_SURFACE:
        _exact_object(
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
        _exact_object(spec, {"path", "name", "routes"}, "Mount representation input")
    else:
        _exact_object(spec, {"host", "name", "routes"}, "Host representation input")
    routes = []
    for route_spec in spec["routes"]:
        _exact_object(
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
    _exact_object(
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


def _materialize_websocket_disconnect_value(value: Any) -> Any:
    if isinstance(value, dict) and value.get("$python_value") == "str-subclass":
        truthiness = value["truthiness"]

        class InputString(str):
            __slots__ = ()

            def __bool__(self) -> bool:
                if truthiness == "raise":
                    raise ValueError("input-defined reason truthiness failure")
                return truthiness == "true"

        return InputString(value["value"])
    if isinstance(value, list):
        return [_materialize_websocket_disconnect_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _materialize_websocket_disconnect_value(item) for key, item in value.items()}
    return value


def _run_websocket_disconnect_constructor_case(case: dict[str, Any]) -> dict[str, Any]:
    _exact_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "calls",
            "observations",
        },
        "WebSocketDisconnect constructor case",
    )
    from starlette.websockets import WebSocketDisconnect

    observed_calls: list[dict[str, Any]] = []
    for index, call in enumerate(case["calls"]):
        _exact_object(call, {"call_id", "args", "kwargs"}, "WebSocketDisconnect call")
        args = [_materialize_websocket_disconnect_value(value) for value in call["args"]]
        kwargs = {
            name: _materialize_websocket_disconnect_value(value)
            for name, value in call["kwargs"].items()
        }
        if len(args) > 1:
            reason_input = args[1]
            reason_input_supplied = True
        elif "reason" in kwargs:
            reason_input = kwargs["reason"]
            reason_input_supplied = True
        else:
            reason_input = None
            reason_input_supplied = False
        if args:
            code_input = args[0]
            code_input_supplied = True
        elif "code" in kwargs:
            code_input = kwargs["code"]
            code_input_supplied = True
        else:
            code_input = None
            code_input_supplied = False

        try:
            value = WebSocketDisconnect(*args, **kwargs)
        except Exception as exc:
            observed_calls.append(
                {
                    "call_id": call["call_id"],
                    "index": index,
                    "outcome": "constructor-error",
                    "error": {
                        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                        "message": str(exc),
                    },
                }
            )
        else:
            observed_calls.append(
                {
                    "call_id": call["call_id"],
                    "index": index,
                    "outcome": "constructed",
                    "code": _json_safe(value.code),
                    "reason": _json_safe(value.reason),
                    "args": _json_safe(value.args),
                    "code_input_identity": (
                        value.code is code_input if code_input_supplied else None
                    ),
                    "reason_input_identity": (
                        value.reason is reason_input if reason_input_supplied else None
                    ),
                }
            )

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "constructor-contract",
                "status": "ok",
                "value": {"constructor-contract": {"calls": observed_calls}},
            }
        ],
    }


def _run_value_formatting_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["surface"] in ROUTE_REPRESENTATION_SURFACES:
        return _run_routing_value_formatting_case(case)
    if case["surface"] == EXCEPTION_VALUES_SURFACE:
        _exact_object(
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
            _exact_object(
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
                _exact_object(mutation, {"field", "value"}, f"exception mutation[{mutation_index}]")
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

    middleware_case_keys = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "middleware",
        "observations",
    }
    if "asgi_workflow" in case:
        middleware_case_keys.add("asgi_workflow")
    _exact_object(case, middleware_case_keys, "Middleware value-formatting case")
    from starlette.middleware import Middleware

    spec = _exact_object(case["middleware"], {"class_name", "args", "kwargs"}, "Middleware input")
    if "asgi_workflow" in case:
        from starlette.datastructures import URL
        from starlette.responses import RedirectResponse

        from scripts.parity.adapters.middleware_docs import (
            make_input_pure_asgi_middleware,
            make_redirects_middleware,
        )

        middleware_traces: list[dict[str, Any]] = []
        workflow_kind = case["asgi_workflow"].get("kind")
        if workflow_kind == "pure-asgi":
            middleware_class = make_input_pure_asgi_middleware(
                spec["class_name"], middleware_traces, _canonical_message
            )
        else:
            middleware_class = make_redirects_middleware(URL, RedirectResponse, spec["class_name"])
    else:
        middleware_class = type(spec["class_name"], (), {"__module__": "starlette.middleware"})
    middleware = Middleware(middleware_class, *spec["args"], **spec["kwargs"])
    iter_values = list(middleware)
    iter_observation = [
        {"kind": "callable", "name": iter_values[0].__name__},
        _json_safe(iter_values[1]),
        _json_safe(iter_values[2]),
    ]
    values = {"repr": repr(middleware), "__iter__": iter_observation}
    if "asgi_workflow" in case:
        from scripts.parity.adapters.middleware_docs import (
            run_eager_response_workflow,
            run_pure_asgi_workflow,
        )

        if workflow_kind == "pure-asgi":
            values["asgi_workflow"] = run_pure_asgi_workflow(
                case["asgi_workflow"],
                middleware,
                iter_values,
                middleware_traces,
                _make_scope,
                _make_message,
                _canonical_message,
            )
        else:
            values["asgi_workflow"] = run_eager_response_workflow(
                case["asgi_workflow"],
                iter_values,
                _make_scope,
                _make_message,
                _canonical_message,
            )
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


def _config_error_snapshot(exc: Exception, selectors: list[str]) -> dict[str, Any]:
    snapshot: dict[str, Any] = _error_snapshot(exc)
    if "exception-context" in selectors:
        context = exc.__context__
        snapshot["context"] = _error_snapshot(context) if context is not None else None
    return snapshot


AUTHENTICATION_OPERATIONS = {
    ("starlette.authentication", "value-operations"),
    ("starlette.authentication", "scope-check"),
    ("starlette.authentication", "decorator-dispatch"),
    ("starlette.middleware.authentication.AuthenticationMiddleware", "dispatch"),
}


def _make_auth_endpoint(
    mode: str,
    parameter_name: str,
    calls: list[Any],
    result: Any,
    signature: list[str] | None = None,
) -> Any:
    if signature is not None:
        parameters = [
            inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD) for name in signature
        ]
        if mode == "sync":

            def endpoint(*args: Any, **kwargs: Any) -> Any:
                calls.append(result)
                return result
        else:

            async def endpoint(*args: Any, **kwargs: Any) -> Any:
                calls.append(result)
                return result

        endpoint.__signature__ = inspect.Signature(parameters)
        return endpoint

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
    case_fields = (
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
        }
    )
    if (
        case["operation"] == "dispatch"
        and case["surface"] == "starlette.middleware.authentication.AuthenticationMiddleware"
        and "scope_container" in case
    ):
        case_fields = case_fields | {"scope_container"}
    if (
        case["operation"] == "dispatch"
        and case["surface"] == "starlette.middleware.authentication.AuthenticationMiddleware"
        and "scope_observation" in case
    ):
        case_fields = case_fields | {"scope_observation"}
    _exact_object(
        case,
        case_fields,
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
                signature=callable_spec.get("signature"),
            )
            redirect = scenario.get("redirect")
            wrapped = requires(
                scenario["required_scopes"],
                status_code=scenario.get("status_code", 403),
                redirect=redirect,
            )(endpoint)
            try:
                invocation = scenario.get("invocation")
                if invocation is None:
                    args = (connection,)
                    kwargs = {}
                else:
                    args = tuple(invocation["positional"])
                    kwargs = (
                        {callable_spec["parameter"]: connection}
                        if invocation["connection_binding"] == "keyword"
                        else {}
                    )
                    if invocation["connection_binding"] == "positional":
                        args = (*args, connection)
                value = (
                    wrapped(*args, **kwargs)
                    if callable_spec["mode"] == "sync"
                    else asyncio.run(wrapped(*args, **kwargs))
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
            attribute_replacement = scenario.get("attribute_replacement")

            def build_app(
                response_spec: dict[str, Any] | None,
                app_call_log: list[Any],
            ) -> Any:
                async def app(
                    asgi_scope: dict[str, Any],
                    receive: Any,
                    send: Any,
                    _response_spec: dict[str, Any] | None = response_spec,
                ) -> None:
                    observed_scope = {"type": asgi_scope["type"]}
                    if "auth" in asgi_scope:
                        observed_scope["auth_scopes"] = list(asgi_scope["auth"].scopes)
                        observed_scope["user"] = {
                            "is_authenticated": asgi_scope["user"].is_authenticated,
                            "display_name": asgi_scope["user"].display_name,
                        }
                    app_call_log.append(observed_scope)
                    if _response_spec is not None:
                        response_body = {
                            _response_spec["authenticated_field"]: asgi_scope[
                                "user"
                            ].is_authenticated,
                            _response_spec["display_name_field"]: asgi_scope["user"].display_name,
                        }
                        await JSONResponse(
                            response_body,
                            status_code=_response_spec["status_code"],
                        )(asgi_scope, receive, send)

                return app

            def build_on_error(response_spec: dict[str, Any] | None) -> Any:
                def on_error(conn: Any, exc: Exception) -> Any:
                    if response_spec["kind"] == "json-error":
                        return JSONResponse(
                            {response_spec["error_field"]: str(exc)},
                            status_code=response_spec["status_code"],
                        )
                    return PlainTextResponse(
                        f"{response_spec['prefix']}{exc}",
                        status_code=response_spec["status_code"],
                    )

                return on_error

            class Backend:
                def __init__(
                    self,
                    spec: dict[str, Any],
                    *,
                    calls: list[Any],
                    app_calls: list[Any],
                    attribute_replacement: dict[str, Any] | None,
                    middleware_holder: dict[str, Any],
                    build_app: Any,
                    build_on_error: Any,
                ) -> None:
                    self.spec = spec
                    self.calls = calls
                    self.app_calls = app_calls
                    self.attribute_replacement = attribute_replacement
                    self.middleware_holder = middleware_holder
                    self.build_app = build_app
                    self.build_on_error = build_on_error

                async def authenticate(self, conn: Any) -> Any:
                    self.calls.append({"scope_type": conn.scope["type"]})
                    replacement = self.attribute_replacement
                    if replacement is not None and replacement["attribute"] == "app":
                        await asyncio.sleep(0)
                        self.middleware_holder["owner"].app = self.build_app(
                            replacement["value"], self.app_calls
                        )
                    if "error" in self.spec:
                        if replacement is not None and replacement["attribute"] == "on_error":
                            await asyncio.sleep(0)
                            self.middleware_holder["owner"].on_error = self.build_on_error(
                                replacement["value"]
                            )
                        raise AuthenticationError(self.spec["error"]["message"])
                    result = self.spec["outcome"]
                    if not isinstance(result, dict):
                        return None
                    if "non_iterable" in result:
                        return result["non_iterable"]
                    if "container" in result:

                        def unpack_value(item: dict[str, Any]) -> Any:
                            if item["kind"] == "credentials":
                                return AuthCredentials(item["scopes"])
                            if item["kind"] == "simple-user":
                                return SimpleUser(item["username"])
                            raise ValueError(item["message"])

                        if result["container"] == "list":
                            return [unpack_value(item) for item in result["items"]]

                        def result_iterator() -> Any:
                            for item in result["items"]:
                                yield unpack_value(item)

                        return result_iterator()
                    return AuthCredentials(result["credentials"]), SimpleUser(result["user"])

            error_response = scenario.get("error_response")
            middleware_holder: dict[str, Any] = {}

            def make_backend(
                spec: dict[str, Any],
                backend_calls: list[Any] = calls,
                backend_app_calls: list[Any] = app_calls,
                backend_replacement: dict[str, Any] | None = attribute_replacement,
                backend_middleware_holder: dict[str, Any] = middleware_holder,
                backend_build_app: Any = build_app,
                backend_build_on_error: Any = build_on_error,
            ) -> Any:
                return Backend(
                    spec,
                    calls=backend_calls,
                    app_calls=backend_app_calls,
                    attribute_replacement=backend_replacement,
                    middleware_holder=backend_middleware_holder,
                    build_app=backend_build_app,
                    build_on_error=backend_build_on_error,
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
            scope = _scope_container(scope, case.get("scope_container", "dict"))

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict[str, Any], _sent: list[Any] = sent) -> None:
                _sent.append(_json_safe(message))

            middleware = AuthenticationMiddleware(
                build_app(application_response_spec, app_calls),
                make_backend(backend_spec),
                build_on_error(error_response)
                if scenario["error_handler"] == "custom-response"
                else None,
            )
            middleware_holder["owner"] = middleware
            if (
                attribute_replacement is not None
                and attribute_replacement["attribute"] == "backend"
            ):
                middleware.backend = make_backend(attribute_replacement["value"])
            try:
                asyncio.run(middleware(scope, receive, send))
            except Exception as exc:
                middleware_outcome = {"outcome": "error", "error": _error_snapshot(exc)}
            else:
                middleware_outcome = {"outcome": "completed"}
            scope_observation_result = (
                _scope_observation(scope, case["scope_observation"])
                if "scope_observation" in case
                else None
            )
            scenario_result = {
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
                "middleware_outcome": middleware_outcome,
            }
            if scope_observation_result is not None:
                scenario_result["scope_observation"] = scope_observation_result
            results.append(scenario_result)
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

    try:
        url = URL(scope=scope)
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {
                    "step_id": "url-record",
                    "status": "error",
                    "error": _dispatch_error(exc),
                    "partial_value": {},
                }
            ],
        }
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
    if kind == "string-subclass":
        truthy = source["truthy"]

        class InputStringSubclass(str):
            def __bool__(self) -> bool:
                return truthy

        return query_params_type(InputStringSubclass(source["value"]))
    if kind == "bytes":
        return query_params_type(base64.b64decode(source["value_base64"], validate=True))
    if kind == "empty":
        return query_params_type()
    if kind == "positional-args":
        return query_params_type(*source["args"])
    if kind == "pairs":
        return query_params_type(source["items"], **dict(source["kwargs"]))
    if kind == "mapping":
        return query_params_type(dict(source["items"]))
    original = query_params_type(source["items"])
    return query_params_type(original)


def _query_params_probe_from_input(source: str | dict[str, Any]) -> str:
    if isinstance(source, str):
        return source

    if source["kind"] == "str-subclass-hash-keyerror":

        class InputHashErrorString(str):
            def __new__(cls, text: str, message: str) -> InputHashErrorString:
                instance = super().__new__(cls, text)
                instance.hash_error_message = message
                return instance

            def __hash__(self) -> int:
                raise KeyError(self.hash_error_message)

        return InputHashErrorString(source["text"], source["message"])

    class InputStringSubclass(str):
        def __new__(cls, text: str, hash_from_text: str, equals_text: str) -> InputStringSubclass:
            instance = super().__new__(cls, text)
            instance.hash_from_text = hash_from_text
            instance.equals_text = equals_text
            return instance

        def __hash__(self) -> int:
            return hash(self.hash_from_text)

        def __eq__(self, other: object) -> bool:
            return other == self.equals_text

    return InputStringSubclass(source["text"], source["hash_from_text"], source["equals_text"])


def _query_params_probe_result(
    params: Any,
    key: str,
    probe_input: str | dict[str, Any],
    probe_default: Any,
    has_probe_default: bool,
) -> dict[str, Any]:
    if not isinstance(probe_input, dict) or "methods" not in probe_input:
        contains = key in params
        get_with_default = params.get(key, probe_default) if has_probe_default else params.get(key)
        return {
            "key": str(key),
            "contains": contains,
            "get": params.get(key),
            "get_with_default": get_with_default,
            "getlist": params.getlist(key),
            "getitem": params[key] if contains else None,
        }

    result: dict[str, Any] = {"key": str(key)}
    for method in probe_input["methods"]:
        if method == "contains":
            result[method] = key in params
        elif method == "get":
            result[method] = params.get(key)
        elif method == "get_with_default":
            result[method] = (
                params.get(key, probe_default) if has_probe_default else params.get(key)
            )
        elif method == "getlist":
            result[method] = params.getlist(key)
        elif method == "getitem":
            result[method] = params[key] if key in params else None
    return result


def _run_query_params_case(case: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
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
    }
    if "probe_default" in case:
        expected_keys.add("probe_default")
    _exact_object(
        case,
        expected_keys,
        "QueryParams construction case",
    )
    from starlette.datastructures import QueryParams

    try:
        params = _query_params_from_input(QueryParams, case["source"])
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                _workflow_observation("snapshot", _CapturedDispatchError(_dispatch_error(exc), {}))
            ],
        }
    comparison_input = case["comparison"]
    if comparison_input is None:
        comparison = None
    elif comparison_input.get("kind") == "literal":
        comparison = comparison_input["value"]
    else:
        comparison = _query_params_from_input(QueryParams, comparison_input)
    lookups = []
    probe_default = case.get("probe_default")
    has_probe_default = "probe_default" in case
    for probe_input in case["probe_keys"]:
        key = _query_params_probe_from_input(probe_input)
        lookups.append(
            _query_params_probe_result(
                params,
                key,
                probe_input,
                probe_default,
                has_probe_default,
            )
        )
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
        if cast_spec.get("kind") == "python-callable" and "error" in cast_spec:
            _exact_object(cast_spec, {"kind", "name", "error"}, "Config Python callable cast")
            error_spec = _exact_object(
                cast_spec["error"],
                {"class", "message"},
                "Config Python callable cast error",
            )
            if error_spec["class"] != "RuntimeError":
                raise ValueError("Config Python callable cast error must be a RuntimeError")

            def custom_cast(_value: Any) -> Any:
                raise RuntimeError(error_spec["message"])

            custom_cast.__name__ = cast_spec["name"]
            return custom_cast
        converter = getattr(builtins, cast_spec["converter"])

        def custom_cast(value: Any) -> Any:
            return converter(value)

        custom_cast.__name__ = cast_spec["name"]
        return custom_cast
    return getattr(builtins, cast_spec)


def _config_lookup_key(key_spec: Any) -> tuple[Any, str]:
    if isinstance(key_spec, str):
        return key_spec, key_spec

    key_value = key_spec["value"]
    radd_result = key_spec["radd_result"]
    format_result = key_spec.get("format_result")

    class InputConfigKey(str):
        def __radd__(self, _left: Any) -> str:
            if format_result is None:
                return radd_result
            return _InputFormattedString(radd_result, format_result)

    return InputConfigKey(key_value), key_value


class _InputFormattedString(str):
    def __new__(cls, value: str, format_result: str) -> _InputFormattedString:
        instance = super().__new__(cls, value)
        instance.format_result = format_result
        return instance

    def __format__(self, format_spec: str) -> str:
        if format_spec == "":
            return self.format_result
        return str.__format__(self, format_spec)


def _config_formatted_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    return _InputFormattedString(value["value"], value["format_result"])


def _config_environ_key(key_spec: Any) -> tuple[Any, str]:
    if isinstance(key_spec, str):
        return key_spec, key_spec
    return (
        _InputFormattedString(key_spec["value"], key_spec["format_result"]),
        key_spec["value"],
    )


def _config_outer_lookup_subclass(
    config_type: Any,
    lookup: dict[str, Any],
    access_log: list[str],
) -> Any:
    class ConfigWithOuterLookup(config_type):
        @property
        def env_prefix(self) -> str:
            access_log.append("env_prefix")
            return lookup["env_prefix"]

        @env_prefix.setter
        def env_prefix(self, _value: str) -> None:
            pass

        @property
        def environ(self) -> dict[str, str]:
            access_log.append("environ")
            return lookup["environ"]

        @environ.setter
        def environ(self, _value: Any) -> None:
            pass

        @property
        def file_values(self) -> dict[str, str]:
            access_log.append("file_values")
            return lookup["file_values"]

        @file_values.setter
        def file_values(self, _value: Any) -> None:
            pass

        def _perform_cast(self, key: Any, value: Any, cast: Any = None) -> dict[str, Any]:
            access_log.append("_perform_cast")
            return {
                "key": _json_safe(key),
                "value": _json_safe(value),
                "cast_name": getattr(cast, "__name__", None),
            }

    return ConfigWithOuterLookup


def _config_value_inspections(value: Any, selectors: list[str]) -> dict[str, Any]:
    inspections = {}
    for selector in selectors:
        try:
            if selector == "repr":
                inspected = repr(value)
            elif selector == "truthiness":
                inspected = bool(value)
            elif selector == "str":
                inspected = str(value)
            else:
                inspected = getattr(value, selector)
        except Exception as exc:
            inspections[selector] = {"error": _error_snapshot(exc)}
        else:
            inspections[selector] = _json_safe(inspected)
    return inspections


def _run_config_environ_actions(case: dict[str, Any], environ: Any) -> list[dict[str, Any]]:
    results = []
    for action in case["actions"]:
        name = action["action"]
        result = {"action": name}
        if "key" in action:
            key, key_label = _config_environ_key(action["key"])
            result["key"] = key_label
        else:
            key = None
        try:
            if name == "set":
                environ[key] = action["value"]
            elif name == "delete":
                del environ[key]
            elif name == "get":
                result["value"] = _json_safe(environ[key])
            elif name == "contains":
                result["value"] = key in environ
            elif name == "config-get":
                from starlette.config import Config

                config = Config(environ=environ)
                if "default" in action:
                    value = config(key, default=action["default"])
                else:
                    value = config(key)
                result["value"] = _json_safe(value)
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


def _config_environ_mapping(case: dict[str, Any]) -> Any:
    dispatch = case.get("mapping_length_dispatch")
    values = dict(case["initial_environ"])
    if dispatch is None:
        return values
    mapping_type = type(
        "InputEnvironmentMapping",
        (dict,),
        {"__len__": lambda _self: dispatch["type_value"]},
    )
    mapping = mapping_type(values)

    def instance_length() -> int:
        return dispatch["instance_value"]

    mapping.__len__ = instance_length
    return mapping


def _run_config_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.config import Config, Environ
    from starlette.config import environ as module_environ

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
                config_class = Config
                if "get_override" in case:
                    override_result = case["get_override"]["return_value"]

                    class ConfigWithGetOverride(Config):
                        def get(
                            self,
                            key: str,
                            cast: Any = None,
                            default: Any = None,
                        ) -> Any:
                            return override_result

                    config_class = ConfigWithGetOverride
                outer_accesses: list[str] = []
                if "outer_lookup" in case:
                    config_class = _config_outer_lookup_subclass(
                        Config,
                        case["outer_lookup"],
                        outer_accesses,
                    )
                config = config_class(
                    env_file=".env",
                    environ={
                        key: _config_formatted_value(value)
                        for key, value in config_input["environ"].items()
                    },
                    env_prefix=config_input["env_prefix"],
                    encoding=encoding,
                )
                results = []
                for lookup in case["lookups"]:
                    cast = _config_cast(lookup["cast"]) if "cast" in lookup else None
                    key, key_label = _config_lookup_key(lookup["key"])
                    arguments = [key, cast]
                    if "default" in lookup:
                        arguments.append(lookup["default"])
                    access_start = len(outer_accesses)
                    try:
                        value = config(*arguments)
                    except Exception as exc:
                        result = {
                            "key": key_label,
                            "outcome": "error",
                            "error": _config_error_snapshot(exc, lookup.get("inspect", [])),
                        }
                    else:
                        result = {"key": key_label, "outcome": "value"}
                        try:
                            result["value"] = _json_safe(value)
                        except Exception as exc:
                            result["value_serialization_error"] = _error_snapshot(exc)
                        if "inspect" in lookup:
                            result["inspections"] = _config_value_inspections(
                                value, lookup["inspect"]
                            )
                    if "outer_lookup" in case:
                        result["dispatch"] = outer_accesses[access_start:]
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
    elif surface_operation == ("starlette.config", "environ"):
        original_environment = list(os.environ.items())
        read_keys = module_environ._has_been_read
        original_read_keys = set(read_keys)
        touched_keys = set(case["initial_environ"])
        touched_keys.update(
            _config_environ_key(action["key"])[1] for action in case["actions"] if "key" in action
        )
        try:
            read_keys.difference_update(touched_keys)
            for key in touched_keys:
                if key in case["initial_environ"]:
                    os.environ[key] = case["initial_environ"][key]
                else:
                    os.environ.pop(key, None)
            results = _run_config_environ_actions(case, module_environ)
        finally:
            os.environ.clear()
            os.environ.update(original_environment)
            read_keys.clear()
            read_keys.update(original_read_keys)
        value = {"action-results": results}
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
            environ = Environ(_config_environ_mapping(case))
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


def _schema_endpoint(spec: dict[str, Any], schema_generator: Any = None) -> Any:
    if spec["kind"] == "function":
        return _schema_function(spec["docstring"])
    if spec["kind"] == "schema-response":

        def endpoint(request: Any) -> Any:
            return schema_generator.OpenAPIResponse(request=request)

        return endpoint
    methods = {
        name: _schema_function(docstring, name) for name, docstring in spec["handlers"].items()
    }
    methods["__call__"] = _schema_function("", "__call__")
    return type("SchemaEndpoint", (), methods)


def _schema_routes(specs: list[dict[str, Any]], schema_generator: Any = None) -> list[Any]:
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
            routes.append(
                Route(
                    spec["path"],
                    _schema_endpoint(spec["endpoint"], schema_generator),
                    **kwargs,
                )
            )
        elif kind == "websocket-route":
            routes.append(WebSocketRoute(spec["path"], _schema_endpoint(spec["endpoint"])))
        elif kind == "mount":
            routes.append(
                Mount(
                    spec["path"],
                    routes=_schema_routes(spec["routes"], schema_generator),
                )
            )
        else:
            routes.append(
                Host(
                    spec["host"],
                    Router(routes=_schema_routes(spec["routes"], schema_generator)),
                )
            )
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
    elif surface_operation == ("starlette.schemas.BaseSchemaGenerator", "get-schema"):
        from starlette.schemas import BaseSchemaGenerator

        generator = BaseSchemaGenerator()
        try:
            result = generator.get_schema(_schema_routes(case["routes"]))
        except Exception as exc:
            value = {"outcome": {"kind": "error", "error": _error_snapshot(exc)}}
        else:
            value = {"outcome": {"kind": "value", "value": _json_safe(result)}}
    elif surface_operation == ("starlette.schemas.OpenAPIResponse", "schema-endpoint-asgi-call"):
        from starlette.applications import Starlette
        from starlette.schemas import SchemaGenerator

        generator = SchemaGenerator(case["base_schema"])
        application = Starlette(routes=_schema_routes(case["routes"], schema_generator=generator))
        scope = _make_scope(case["scope"])
        incoming = iter(_make_message(message) for message in case["incoming"])
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            try:
                return next(incoming)
            except StopIteration:
                return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        async def dispatch() -> None:
            await application(scope, receive, send)

        asyncio.run(dispatch())
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
            message.get("body", b"") for message in sent if message["type"] == "http.response.body"
        )
        content_types = [
            value.decode("latin-1")
            for name, value in (response_start or {}).get("headers", [])
            if name.lower() == b"content-type"
        ]
        value = {
            "response-status": (response_start or {}).get("status"),
            "content-type": content_types[0] if content_types else None,
            "ordered-repeated-headers": (
                response_start_event["headers"] if response_start_event is not None else []
            ),
            "response-bytes": {
                "encoding": "base64",
                "data": base64.b64encode(response_body).decode("ascii"),
            },
            "asgi-event-order": [event["type"] for event in events],
            "asgi-events": events,
        }
    elif surface_operation == ("starlette.schemas.OpenAPIResponse", "openapi-response-render"):
        from starlette.requests import Request
        from starlette.schemas import OpenAPIResponse, SchemaGenerator

        content = case["content"]
        media_type: dict[str, Any] = {"direct": None, "generated": None}
        rendered_bytes: dict[str, Any] = {"direct": None, "generated": None}
        if isinstance(content, dict):
            generator = SchemaGenerator(content)
            direct = OpenAPIResponse(content)
            application = type("SchemaApplication", (), {"routes": []})()
            request = Request({"type": "http", "method": "GET", "app": application})
            generated = generator.OpenAPIResponse(request)
            media_type = {"direct": direct.media_type, "generated": generated.media_type}
            rendered_bytes = {
                "direct": _json_safe(direct.render(content)),
                "generated": _json_safe(generated.render(content)),
            }
            outcome = {"kind": "value"}
        else:
            try:
                direct = OpenAPIResponse(content)
                direct_rendered = direct.render(content)
            except Exception as exc:
                outcome = {"kind": "error", "error": _error_snapshot(exc)}
            else:
                media_type = {"direct": direct.media_type, "generated": None}
                rendered_bytes = {"direct": _json_safe(direct_rendered), "generated": None}
                outcome = {"kind": "value"}
        value = {
            "media-type": media_type,
            "outcome": outcome,
            "rendered-bytes": rendered_bytes,
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": selector, "status": "ok", "value": value}
            for selector in case["observations"]
        ],
    }


def _run_base_http_workflow_case(case: dict[str, Any]) -> dict[str, Any]:
    case_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "application",
        "request",
        "observations",
    }
    if "scope_container" in case:
        case_fields.add("scope_container")
    if "scope_observation" in case:
        case_fields.add("scope_observation")
    _exact_object(
        case,
        case_fields,
        "BaseHTTPMiddleware base-http-workflow case",
    )
    if case["surface"] != BASE_HTTP_SURFACE or case["operation"] != BASE_HTTP_WORKFLOW_OPERATION:
        raise ValueError("workflow is outside the BaseHTTPMiddleware base-http-workflow operation")
    if not isinstance(case["case_id"], str):
        raise ValueError("BaseHTTPMiddleware case_id must be a string")
    if not _has_unique_cpython_package_profiles(case["target_profiles"]) or case["assets"] != []:
        raise ValueError(
            "BaseHTTPMiddleware workflow selects one or more Python-package profiles and no assets"
        )
    if case["observations"] != [BASE_HTTP_WORKFLOW_OPERATION]:
        raise ValueError("BaseHTTPMiddleware observations must select base-http-workflow")

    application = case["application"]
    allowed_application_keys = {
        frozenset({"debug", "routes", "middleware"}),
        frozenset({"debug", "routes", "middleware", "downstream"}),
        frozenset({"debug", "routes", "middleware", "outer_receive_transform"}),
        frozenset({"debug", "routes", "middleware", "downstream", "outer_receive_transform"}),
    }
    if not isinstance(application, dict) or frozenset(application) not in allowed_application_keys:
        raise ValueError("BaseHTTPMiddleware application input has unknown or missing fields")
    if type(application["debug"]) is not bool:
        raise ValueError("BaseHTTPMiddleware application.debug must be boolean")
    outer_receive_transform = None
    outer_receive_suffix = b""
    if "outer_receive_transform" in application:
        outer_receive_transform = _exact_object(
            application["outer_receive_transform"],
            {"kind", "suffix_base64"},
            "BaseHTTPMiddleware outer receive transformation",
        )
        if outer_receive_transform["kind"] != "append-http-request-body":
            raise ValueError("outer receive transformation kind is unsupported")
        outer_receive_suffix = _decode_base64(
            outer_receive_transform["suffix_base64"],
            "BaseHTTPMiddleware outer receive suffix",
        )
        if not outer_receive_suffix:
            raise ValueError("outer receive transformation suffix must be non-empty")
    route_specs = application["routes"]
    if not isinstance(route_specs, list) or len(route_specs) > 1:
        raise ValueError("BaseHTTPMiddleware workflow supports zero or one route")
    route_spec = None
    endpoint_spec = None
    route_kind = None
    exception_spec = None
    background_task_spec = None
    if route_specs:
        route_spec = _exact_object(
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
            endpoint_spec = _exact_object(
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
            endpoint_spec = _exact_object(
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
            raw_background_task = endpoint_spec["background_task"]
            background_task_fields = {"kind", "delay_seconds"}
            if isinstance(raw_background_task, dict) and raw_background_task.get("kind") == (
                "async-delay-and-raise"
            ):
                background_task_fields.add("exception")
            background_task_spec = _exact_object(
                raw_background_task,
                background_task_fields,
                "BaseHTTPMiddleware background task input",
            )
            delay_seconds = background_task_spec["delay_seconds"]
            if (
                background_task_spec["kind"] not in {"async-delay", "async-delay-and-raise"}
                or type(delay_seconds) not in {int, float}
                or not math.isfinite(delay_seconds)
                or not 0 <= delay_seconds <= 5
            ):
                raise ValueError("BaseHTTPMiddleware async background delay is invalid")
            if background_task_spec["kind"] == "async-delay-and-raise":
                failure = _exact_object(
                    background_task_spec["exception"],
                    {"class", "message"},
                    "BaseHTTPMiddleware background exception input",
                )
                if failure["class"] not in {"Exception", "ValueError"} or not isinstance(
                    failure["message"], str
                ):
                    raise ValueError("BaseHTTPMiddleware background exception input is invalid")
        elif route_kind == "request-body-response":
            _exact_object(endpoint_spec, {"kind"}, "BaseHTTPMiddleware request-body endpoint")
            if "POST" not in route_spec["methods"]:
                raise ValueError("request-body-response routes must accept POST")
        elif route_kind == "request-body-empty-response":
            _exact_object(
                endpoint_spec,
                {"kind"},
                "BaseHTTPMiddleware empty request-body endpoint",
            )
            if "POST" not in route_spec["methods"]:
                raise ValueError("request-body-empty-response routes must accept POST")
        elif route_kind == "request-body-plain-text-response":
            endpoint_spec = _exact_object(
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
            endpoint_spec = _exact_object(
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
            endpoint_spec = _exact_object(
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
        elif route_kind == "request-body-client-disconnect-response":
            endpoint_spec = _exact_object(
                endpoint_spec,
                {"kind", "unexpected_exception_message"},
                "BaseHTTPMiddleware client-disconnect endpoint",
            )
            if (
                not isinstance(endpoint_spec["unexpected_exception_message"], str)
                or not endpoint_spec["unexpected_exception_message"]
                or route_spec["methods"] != ["GET"]
            ):
                raise ValueError("client-disconnect endpoint input is invalid")
        elif route_kind == "file-response":
            endpoint_spec = _exact_object(
                endpoint_spec,
                {"kind", "file"},
                "BaseHTTPMiddleware FileResponse endpoint",
            )
            file_input = _exact_object(
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
            _decode_base64(
                file_input["contents_base64"], "BaseHTTPMiddleware FileResponse contents"
            )
        elif route_kind == "raise-exception":
            _exact_object(
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
                chain = _exact_object(
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
    if not isinstance(middleware_specs, list) or not middleware_specs:
        raise ValueError("BaseHTTPMiddleware workflow requires configured middleware")
    middleware_layers = []
    base_http_layers = []
    context_manager_cleanup_spec = None
    for index, value in enumerate(middleware_specs):
        context = f"BaseHTTPMiddleware configured Middleware[{index}]"
        if isinstance(value, dict) and value.get("kind") == "async-context-manager-cleanup":
            layer = _exact_object(value, {"kind", "exit_delay_seconds"}, context)
            delay_seconds = layer["exit_delay_seconds"]
            if (
                type(delay_seconds) not in {int, float}
                or not math.isfinite(delay_seconds)
                or not 0 <= delay_seconds <= 5
            ):
                raise ValueError("context-manager exit delay must be finite and between 0 and 5")
            if context_manager_cleanup_spec is not None:
                raise ValueError("BaseHTTPMiddleware workflow supports one cleanup middleware")
            context_manager_cleanup_spec = layer
        elif isinstance(value, dict) and set(value) == {"kind", "constructor_dispatch"}:
            layer = _exact_object(value, {"kind", "constructor_dispatch"}, context)
            if layer["constructor_dispatch"] != "call-next":
                raise ValueError("BaseHTTPMiddleware constructor dispatch must select call-next")
            layer["dispatch_actions"] = [
                {"kind": "await-call-next"},
                {"kind": "return-call-next-response"},
            ]
        elif isinstance(value, dict) and set(value) == {"kind", "dispatch_callable"}:
            layer = _exact_object(value, {"kind", "dispatch_callable"}, context)
            dispatch_callable = _exact_object(
                layer["dispatch_callable"],
                {"kind", "exception"},
                "BaseHTTPMiddleware dispatch callable",
            )
            if dispatch_callable["kind"] != "sync-raise":
                raise ValueError("BaseHTTPMiddleware dispatch callable kind is unsupported")
            exception = _exact_object(
                dispatch_callable["exception"],
                {"class", "message"},
                "BaseHTTPMiddleware synchronous dispatch exception",
            )
            if exception["class"] not in {
                "Exception",
                "RuntimeError",
                "ValueError",
            } or not isinstance(exception["message"], str):
                raise ValueError("BaseHTTPMiddleware synchronous dispatch exception is invalid")
            layer["dispatch_actions"] = []
        else:
            layer = _exact_object(value, {"kind", "dispatch_actions"}, context)
        middleware_layers.append(layer)
        if layer["kind"] == "base-http-middleware":
            base_http_layers.append(layer)
        elif layer["kind"] != "async-context-manager-cleanup":
            raise ValueError("configured middleware must be a BaseHTTPMiddleware subclass")
    if not base_http_layers:
        raise ValueError("configured middleware must be a BaseHTTPMiddleware subclass")
    if context_manager_cleanup_spec is not None and (
        len(middleware_layers) != 2
        or middleware_layers[0]["kind"] != "base-http-middleware"
        or middleware_layers[1] != context_manager_cleanup_spec
        or len(base_http_layers) != 1
    ):
        raise ValueError(
            "context-manager cleanup input requires BaseHTTPMiddleware followed by one cleanup layer"
        )
    layer_kinds = []
    for layer in base_http_layers:
        layer_actions = layer.get("dispatch_actions", [])
        if isinstance(layer_actions, list):
            layer_kinds.extend(
                action.get("kind")
                for action in layer_actions
                if isinstance(action, dict) and isinstance(action.get("kind"), str)
            )
    stacked_request_state = (
        len(base_http_layers) == 3
        and any(kind == "set-request-state" for kind in layer_kinds)
        and any(kind == "set-call-next-response-header-from-request-state" for kind in layer_kinds)
    )
    lifecycle_action_kinds = {
        "append-middleware-event",
        "observe-call-next-response-background",
        "set-call-next-response-background-task",
    }
    stacked_disconnect_lifecycle = len(base_http_layers) > 1 and bool(
        lifecycle_action_kinds.intersection(layer_kinds)
    )
    stacked_state_header_mutation = False
    if stacked_request_state:
        if (
            route_spec is None
            or route_kind != "plain-text-response"
            or route_spec["methods"] != ["GET"]
        ):
            raise ValueError("three-layer Request.state parity requires one GET text route")
        for layer_index, layer in enumerate(base_http_layers):
            layer_actions = layer["dispatch_actions"]
            if not isinstance(layer_actions, list) or not layer_actions:
                raise ValueError("BaseHTTPMiddleware dispatch_actions must be non-empty")
            layer_awaited = False
            layer_returned = False
            for action_index, raw_action in enumerate(layer_actions):
                context = f"BaseHTTPMiddleware layer[{layer_index}] action[{action_index}]"
                if not isinstance(raw_action, dict) or not isinstance(raw_action.get("kind"), str):
                    raise ValueError(f"{context} must be tagged")
                kind = raw_action["kind"]
                if kind == "set-request-state":
                    action = _exact_object(raw_action, {"kind", "name", "value"}, context)
                    if layer_awaited or layer_returned:
                        raise ValueError("Request.state writes must precede call_next")
                    if (
                        not isinstance(action["name"], str)
                        or not action["name"]
                        or not isinstance(action["value"], str)
                    ):
                        raise ValueError("Request.state write input is invalid")
                elif kind == "await-call-next":
                    _exact_object(raw_action, {"kind"}, context)
                    if layer_awaited or layer_returned:
                        raise ValueError("each BaseHTTPMiddleware layer must await call_next once")
                    layer_awaited = True
                elif kind == "set-call-next-response-header-from-request-state":
                    action = _exact_object(raw_action, {"kind", "name", "state_name"}, context)
                    if not layer_awaited or layer_returned:
                        raise ValueError("state-derived response headers must follow call_next")
                    if (
                        not isinstance(action["name"], str)
                        or not action["name"]
                        or not isinstance(action["state_name"], str)
                        or not action["state_name"]
                        or any(char in action["name"] for char in "\r\n:")
                    ):
                        raise ValueError("state-derived response header input is invalid")
                    stacked_state_header_mutation = True
                elif kind == "return-call-next-response":
                    _exact_object(raw_action, {"kind"}, context)
                    if (
                        not layer_awaited
                        or layer_returned
                        or action_index != len(layer_actions) - 1
                    ):
                        raise ValueError("each middleware layer must return call_next's response")
                    layer_returned = True
                else:
                    raise ValueError(f"{context} has an unsupported state-stack action")
            if not layer_awaited or not layer_returned:
                raise ValueError("each middleware layer must await and return call_next")
    elif stacked_disconnect_lifecycle:
        if (
            route_spec is None
            or route_kind != "request-body-client-disconnect-response"
            or route_spec["methods"] != ["GET"]
        ):
            raise ValueError("middleware lifecycle stack requires the direct GET disconnect route")
        for layer_index, layer in enumerate(base_http_layers):
            layer_actions = layer["dispatch_actions"]
            if not isinstance(layer_actions, list) or not layer_actions:
                raise ValueError("BaseHTTPMiddleware dispatch_actions must be non-empty")
            layer_awaited = False
            layer_returned = False
            counts = {"started": 0, "completed": 0, "background-state": 0, "background-task": 0}
            for action_index, raw_action in enumerate(layer_actions):
                context = f"BaseHTTPMiddleware layer[{layer_index}] action[{action_index}]"
                if not isinstance(raw_action, dict) or not isinstance(raw_action.get("kind"), str):
                    raise ValueError(f"{context} must be tagged")
                kind = raw_action["kind"]
                if kind == "append-middleware-event":
                    action = _exact_object(raw_action, {"kind", "phase", "value"}, context)
                    if (
                        not isinstance(action["value"], str)
                        or not action["value"]
                        or not isinstance(action["phase"], str)
                        or action["phase"] not in {"started", "completed"}
                    ):
                        raise ValueError("middleware event input requires a phase and value")
                    if action["phase"] == "started":
                        if layer_awaited or layer_returned:
                            raise ValueError("middleware start events must precede call_next")
                    elif not layer_awaited or layer_returned:
                        raise ValueError("middleware completion events must follow call_next")
                    counts[action["phase"]] += 1
                elif kind == "await-call-next":
                    _exact_object(raw_action, {"kind"}, context)
                    if layer_awaited or layer_returned:
                        raise ValueError("each middleware layer must await call_next once")
                    layer_awaited = True
                elif kind == "observe-call-next-response-background":
                    action = _exact_object(raw_action, {"kind", "label"}, context)
                    if (
                        not isinstance(action["label"], str)
                        or not action["label"]
                        or not layer_awaited
                        or layer_returned
                    ):
                        raise ValueError("response-background observation must follow call_next")
                    counts["background-state"] += 1
                elif kind == "set-call-next-response-background-task":
                    action = _exact_object(raw_action, {"kind", "value"}, context)
                    if (
                        not isinstance(action["value"], str)
                        or not action["value"]
                        or not layer_awaited
                        or layer_returned
                    ):
                        raise ValueError("middleware background task must follow call_next")
                    counts["background-task"] += 1
                elif kind == "return-call-next-response":
                    _exact_object(raw_action, {"kind"}, context)
                    if (
                        not layer_awaited
                        or layer_returned
                        or action_index != len(layer_actions) - 1
                    ):
                        raise ValueError("each middleware layer must return call_next's response")
                    layer_returned = True
                else:
                    raise ValueError(f"{context} has an unsupported lifecycle-stack action")
            if (
                not layer_awaited
                or not layer_returned
                or counts
                != {"started": 1, "completed": 1, "background-state": 1, "background-task": 1}
            ):
                raise ValueError(
                    "each lifecycle layer requires one start, completion, and background observation"
                )
    elif len(base_http_layers) > 1:
        raise ValueError("multi-layer BaseHTTPMiddleware input requires a declared stack workflow")
    middleware_spec = base_http_layers[0]
    dispatch_callable_spec = middleware_spec.get("dispatch_callable")
    dispatch_actions = middleware_spec.get("dispatch_actions", [])
    if not isinstance(dispatch_actions, list) or (
        not dispatch_actions and dispatch_callable_spec is None
    ):
        raise ValueError("BaseHTTPMiddleware dispatch_actions must be non-empty")
    awaited = False
    await_index = None
    await_action_kind = None
    returned = None
    saw_header_mutation = False
    saw_disconnect_check = False
    saw_response_body_read = False
    saw_response_body_iterator_replacement = False
    saw_response_iterator_overlap = False
    saw_response_header_observation = False
    response_header_observation_name: str | None = None
    for index, raw_action in enumerate(dispatch_actions):
        context = f"BaseHTTPMiddleware dispatch_actions[{index}]"
        if not isinstance(raw_action, dict) or not isinstance(raw_action.get("kind"), str):
            raise ValueError(f"{context} must be tagged")
        kind = raw_action["kind"]
        if kind == "read-request-body":
            _exact_object(raw_action, {"kind"}, context)
        elif kind == "observe-request-helpers":
            _exact_object(raw_action, {"kind"}, context)
            if returned is not None:
                raise ValueError("request helper observations must precede the dispatch return")
        elif kind == "set-request-state":
            action = _exact_object(raw_action, {"kind", "name", "value"}, context)
            if awaited or returned is not None:
                raise ValueError("Request.state writes must precede call_next")
            if (
                not isinstance(action["name"], str)
                or not action["name"]
                or not isinstance(action["value"], str)
            ):
                raise ValueError("Request.state write input is invalid")
        elif kind == "read-request-stream-next":
            _exact_object(raw_action, {"kind"}, context)
        elif kind == "check-request-is-disconnected":
            _exact_object(raw_action, {"kind"}, context)
            if returned is not None or saw_disconnect_check:
                raise ValueError(
                    "Request.is_disconnected() must be observed at most once before return"
                )
            saw_disconnect_check = True
        elif kind == "capture-request-stream-next":
            _exact_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None:
                raise ValueError(
                    "captured request.stream() reads must follow call_next and precede the dispatch return"
                )
        elif kind == "read-call-next-response-body-next-and-close":
            _exact_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None or saw_response_body_read:
                raise ValueError(
                    "call_next response body read requires one awaited response and must precede return"
                )
            saw_response_body_read = True
        elif kind == "set-call-next-response-body-iterator":
            action = _exact_object(raw_action, {"kind", "chunks_base64"}, context)
            chunks = action["chunks_base64"]
            if (
                not awaited
                or returned is not None
                or saw_response_body_iterator_replacement
                or not isinstance(chunks, list)
                or not chunks
            ):
                raise ValueError(
                    "call_next response body iterator replacement requires one awaited response and a non-empty chunk sequence"
                )
            decoded_chunks = [
                _decode_base64(chunk, f"{context}.chunks_base64[{chunk_index}]")
                for chunk_index, chunk in enumerate(chunks)
            ]
            if not any(decoded_chunks):
                raise ValueError(
                    "call_next response body iterator replacement requires a non-empty body chunk"
                )
            saw_response_body_iterator_replacement = True
        elif kind == "overlap-call-next-response-body-reads":
            action = _exact_object(raw_action, {"kind", "timeout_ms"}, context)
            if (
                not awaited
                or returned is not None
                or saw_response_body_read
                or saw_response_iterator_overlap
            ):
                raise ValueError(
                    "overlapping call_next response body reads require one awaited response"
                )
            if type(action["timeout_ms"]) is not int or not 1 <= action["timeout_ms"] <= 10_000:
                raise ValueError(
                    "overlapping response body read timeout_ms must be between 10 and 10000"
                )
            saw_response_iterator_overlap = True
        elif kind == "await-call-next":
            _exact_object(raw_action, {"kind"}, context)
            if awaited or returned is not None:
                raise ValueError("BaseHTTPMiddleware dispatch must await call_next once")
            awaited = True
            await_index = index
            await_action_kind = kind
        elif kind == "await-call-next-catching-exception":
            action = _exact_object(
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
        elif kind == "observe-call-next-response-headers":
            action = _exact_object(
                raw_action,
                {"kind", "name", "probes"} if "probes" in raw_action else {"kind", "name"},
                context,
            )
            if not awaited or returned is not None or saw_response_header_observation:
                raise ValueError("call_next response headers may be observed once after call_next")
            if (
                not isinstance(action["name"], str)
                or not action["name"]
                or any(char in action["name"] for char in "\r\n:")
            ):
                raise ValueError("call_next response header lookup name is invalid")
            probes = action.get("probes", [])
            if not isinstance(probes, list) or ("probes" in action and not probes):
                raise ValueError("BaseHTTP response-header probes must be a non-empty array")
            for probe in probes:
                probe = _exact_object(probe, {"kind", "name"}, context)
                if (
                    not isinstance(probe["kind"], str)
                    or probe["kind"] not in {"getitem", "contains", "delete"}
                    or not isinstance(probe["name"], str)
                    or not probe["name"]
                    or any(char in probe["name"] for char in "\r\n:")
                ):
                    raise ValueError("BaseHTTP response-header probe input is invalid")
            saw_response_header_observation = True
            response_header_observation_name = action["name"]
        elif kind == "set-call-next-response-header":
            action = _exact_object(raw_action, {"kind", "name", "value"}, context)
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
        elif kind == "set-call-next-response-header-from-request-state":
            action = _exact_object(raw_action, {"kind", "name", "state_name"}, context)
            if not awaited or returned is not None or saw_header_mutation:
                raise ValueError("state-derived response header requires call_next")
            if (
                not isinstance(action["name"], str)
                or not action["name"]
                or not isinstance(action["state_name"], str)
                or not action["state_name"]
                or any(char in action["name"] for char in "\r\n:")
            ):
                raise ValueError("state-derived response header input is invalid")
            saw_header_mutation = True
        elif kind == "append-middleware-event":
            action = _exact_object(raw_action, {"kind", "phase", "value"}, context)
            if (
                not isinstance(action["value"], str)
                or not action["value"]
                or not isinstance(action["phase"], str)
                or action["phase"] not in {"started", "completed"}
            ):
                raise ValueError("middleware event input requires a phase and value")
            if action["phase"] == "started" and (awaited or returned is not None):
                raise ValueError("middleware start events must precede call_next")
            if action["phase"] == "completed" and (not awaited or returned is not None):
                raise ValueError("middleware completion events must follow call_next")
        elif kind == "observe-call-next-response-background":
            action = _exact_object(raw_action, {"kind", "label"}, context)
            if (
                not isinstance(action["label"], str)
                or not action["label"]
                or not awaited
                or returned is not None
            ):
                raise ValueError("response-background observation must follow call_next")
        elif kind == "set-call-next-response-background-task":
            action = _exact_object(raw_action, {"kind", "value"}, context)
            if (
                not isinstance(action["value"], str)
                or not action["value"]
                or not awaited
                or returned is not None
            ):
                raise ValueError("middleware background task must follow call_next")
        elif kind == "return-call-next-response":
            _exact_object(raw_action, {"kind"}, context)
            if not awaited or returned is not None or index != len(dispatch_actions) - 1:
                raise ValueError("call_next response must be returned as the final dispatch action")
            returned = "call-next"
        elif kind == "return-plain-text-response":
            action = _exact_object(raw_action, {"kind", "content", "status_code"}, context)
            if (
                (not awaited and index != 0)
                or returned is not None
                or saw_header_mutation
                or index != len(dispatch_actions) - 1
                or not isinstance(action["content"], str)
                or type(action["status_code"]) is not int
                or not 100 <= action["status_code"] <= 599
            ):
                raise ValueError("replacement response must be final dispatch action")
            returned = "replacement"
        else:
            raise ValueError(f"{context} has an unsupported action kind")
    if dispatch_callable_spec is None and (
        (not awaited and returned != "replacement") or returned is None
    ):
        raise ValueError("BaseHTTPMiddleware dispatch action sequence is incomplete")
    if saw_header_mutation and returned != "call-next":
        raise ValueError("only the call_next response can be mutated")
    if returned == "call-next" and route_spec is None and "downstream" not in application:
        raise ValueError("call_next response requires a configured route or downstream ASGI app")

    downstream_spec = None
    wide_status_probe = False
    response_start_type_python_equality_probe = False
    response_body_type_python_equality_probe = False
    response_pathsend_type_python_equality_probe = False
    if "downstream" in application:
        raw_downstream = application["downstream"]
        if not isinstance(raw_downstream, dict) or not isinstance(raw_downstream.get("kind"), str):
            raise ValueError("BaseHTTPMiddleware downstream ASGI input must be tagged")
        if raw_downstream["kind"] == "asgi-sequence":
            downstream_spec = _exact_object(
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
                if raw_step == {"kind": "receive"}:
                    if saw_response_iterator_overlap and step_index == 1 and len(steps) == 3:
                        continue
                    raise ValueError("downstream ASGI steps before final receive must send")
                send_step_fields = {"kind", "message"}
                if isinstance(raw_step, dict) and "message_mapping" in raw_step:
                    send_step_fields.add("message_mapping")
                send_step = _exact_object(
                    raw_step,
                    send_step_fields,
                    f"downstream ASGI send step[{step_index}]",
                )
                if send_step["kind"] != "send":
                    raise ValueError("downstream ASGI steps before final receive must send")
                message_mapping = send_step.get("message_mapping", "dict")
                if not isinstance(message_mapping, str) or message_mapping not in {
                    "dict",
                    "user-dict",
                }:
                    raise ValueError("downstream ASGI message mapping must be dict or user-dict")
                message_spec = send_step["message"]
                if not isinstance(message_spec, dict) or not isinstance(
                    message_spec.get("type"), (str, dict)
                ):
                    raise ValueError("downstream ASGI send message must be tagged")
                _, message_type_value = _materialize_base_http_downstream_message_type(
                    message_spec["type"]
                )
                message_type_probe = isinstance(message_spec["type"], dict)
                if message_type_probe:
                    if (
                        response_start_type_python_equality_probe
                        or response_body_type_python_equality_probe
                        or response_pathsend_type_python_equality_probe
                    ):
                        raise ValueError(
                            "BaseHTTPMiddleware allows one downstream message type equality probe per case"
                        )
                    if message_type_value == "http.response.start":
                        response_start_type_python_equality_probe = True
                    elif message_type_value == "http.response.body":
                        response_body_type_python_equality_probe = True
                    else:
                        response_pathsend_type_python_equality_probe = True
                if message_type_value == "http.response.start":
                    message = _exact_object(
                        message_spec,
                        {"type", "status", "headers_base64_pairs"},
                        "downstream ASGI response.start input",
                    )
                    if (
                        response_started
                        or step_index != 0
                        or type(message["status"]) is not int
                        or not (100 <= message["status"] <= 599 or message["status"] == 65536)
                        or not isinstance(message["headers_base64_pairs"], list)
                    ):
                        raise ValueError("downstream ASGI must begin with one valid response.start")
                    wide_status_probe = message["status"] == 65536
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
                            _decode_base64(value, f"downstream response header[{header_index}]")
                    response_started = True
                elif message_type_value == "http.response.body":
                    message = _exact_object(
                        message_spec,
                        {"type", "body_base64", "more_body"},
                        "downstream ASGI response.body input",
                    )
                    terminal_body_allowed = (
                        saw_response_header_observation and returned == "call-next"
                    )
                    if (
                        not response_started
                        or type(message["more_body"]) is not bool
                        or (
                            message["more_body"] is not True
                            and not (terminal_body_allowed and step_index == len(steps) - 2)
                        )
                    ):
                        raise ValueError(
                            "downstream ASGI response.body must follow response.start and remain non-terminal except for a completed call_next header observation"
                        )
                    if not _decode_base64(message["body_base64"], "downstream ASGI response body"):
                        raise ValueError("downstream ASGI response body must be non-empty")
                    body_send_count += 1
                elif message_type_value == "http.response.pathsend":
                    message = _exact_object(
                        message_spec,
                        {"type", "path"},
                        "downstream ASGI response.pathsend input",
                    )
                    if (
                        not response_started
                        or step_index != 1
                        or not isinstance(message["path"], str)
                    ):
                        raise ValueError(
                            "downstream ASGI response.pathsend must follow response.start with a string path"
                        )
                else:
                    raise ValueError("downstream ASGI send message type is unsupported")
                if message_type_probe and (
                    (message_type_value == "http.response.start" and step_index != 0)
                    or (message_type_value == "http.response.body" and step_index != 1)
                ):
                    raise ValueError(
                        "BaseHTTPMiddleware message type equality probes must target the first matching stream message"
                    )
            terminal_body_case = (
                saw_response_header_observation
                and returned == "call-next"
                and body_send_count == 1
                and steps[-2]["message"].get("type") == "http.response.body"
                and steps[-2]["message"].get("more_body") is False
            )
            if not response_started or (
                body_send_count < 2
                and not terminal_body_case
                and not saw_response_iterator_overlap
                and not response_pathsend_type_python_equality_probe
            ):
                raise ValueError(
                    "downstream ASGI receive input requires response.start and at least two body sends, except for a completed call_next header observation"
                )
        elif raw_downstream["kind"] == "stream-until-disconnect-app":
            downstream_spec = _exact_object(
                raw_downstream,
                {"kind", "response_start", "body_message", "guard_timeout_ms"},
                "BaseHTTPMiddleware downstream streaming app",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            response_start = _exact_object(
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
                    _decode_base64(value, f"downstream streaming response header[{header_index}]")
            body_message = _exact_object(
                downstream_spec["body_message"],
                {"type", "body_base64", "more_body"},
                "downstream streaming response body input",
            )
            if (
                body_message["type"] != "http.response.body"
                or body_message["more_body"] is not True
                or not _decode_base64(body_message["body_base64"], "downstream streaming body")
            ):
                raise ValueError("downstream streaming response body input is invalid")
            if (
                type(downstream_spec["guard_timeout_ms"]) is not int
                or not 1 <= downstream_spec["guard_timeout_ms"] <= 10_000
            ):
                raise ValueError(
                    "downstream streaming guard_timeout_ms must be between 1 and 10000"
                )
        elif raw_downstream["kind"] == "request-stream-asgi-endpoint":
            downstream_spec = _exact_object(
                raw_downstream,
                {"kind", "stop_after_chunks", "response_status_code"},
                "BaseHTTPMiddleware downstream request-stream endpoint",
            )
            if route_spec is not None:
                raise ValueError(
                    "direct request-stream ASGI endpoint cannot declare Starlette routes"
                )
            if (
                type(downstream_spec["stop_after_chunks"]) is not int
                or not 1 <= downstream_spec["stop_after_chunks"] <= 1000
                or type(downstream_spec["response_status_code"]) is not int
                or not 100 <= downstream_spec["response_status_code"] <= 599
            ):
                raise ValueError("direct request-stream endpoint input is invalid")
        elif raw_downstream["kind"] == "asgi-middleware-stack":
            downstream_spec = _exact_object(
                raw_downstream,
                {"kind", "wrappers", "endpoint"},
                "BaseHTTPMiddleware downstream middleware stack",
            )
            if route_spec is not None:
                raise ValueError("direct BaseHTTPMiddleware ASGI input cannot declare routes")
            wrappers = downstream_spec["wrappers"]
            if not isinstance(wrappers, list) or len(wrappers) != 1:
                raise ValueError("downstream middleware stack requires one ordered wrapper")
            wrapper = _exact_object(
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
            endpoint = _exact_object(
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
            downstream_spec = _exact_object(
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
                poll = _exact_object(
                    raw_poll,
                    {"kind"},
                    f"downstream disconnect poll[{index}]",
                )
                if poll["kind"] != "drain-requests-until-disconnect":
                    raise ValueError("downstream polls must drain request messages to disconnect")
            response = _exact_object(
                downstream_spec["response"],
                {"kind", "body_base64", "status_code"},
                "downstream disconnect-polling response",
            )
            if (
                response["kind"] != "bytes-response"
                or type(response["status_code"]) is not int
                or not 100 <= response["status_code"] <= 599
                or not _decode_base64(response["body_base64"], "downstream response body")
            ):
                raise ValueError("downstream polling response input is invalid")
        elif raw_downstream["kind"] == "receive-sequence-app":
            downstream_spec = _exact_object(
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
                step = _exact_object(raw_step, {"kind"}, f"downstream receive step[{index}]")
                if step["kind"] != "receive":
                    raise ValueError("downstream receive-sequence steps must call receive")
            response = _exact_object(
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
    if dispatch_callable_spec is not None:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.synchronous-dispatch-call-error-cleanup"
        )
    if (
        downstream_spec is not None
        and downstream_spec["kind"] == "asgi-sequence"
        and any(
            step.get("message_mapping") == "user-dict"
            for step in downstream_spec["steps"][:-1]
            if isinstance(step, dict) and step.get("kind") == "send"
        )
    ):
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.mutable-downstream-response-messages"
        )
    if saw_header_mutation or stacked_state_header_mutation:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.await-call-next-header-mutation"
        )
    if stacked_request_state:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.shared-request-state-across-middleware-layers"
        )
    if stacked_disconnect_lifecycle:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.stacked-client-disconnect-background-lifecycle"
        )
    if returned == "replacement":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.return-replacement-response"
        )

    request_fields = {
        "scope",
        "receive",
        "receive_after_events",
        "send_checkpoints",
    }
    if isinstance(case["request"], dict) and "concurrent_calls" in case["request"]:
        request_fields.add("concurrent_calls")
    if isinstance(case["request"], dict) and "receive_message_mapping" in case["request"]:
        request_fields.add("receive_message_mapping")
    request = _exact_object(case["request"], request_fields, "BaseHTTPMiddleware request")
    receive_mapping = request.get("receive_message_mapping", "dict")
    if not isinstance(receive_mapping, str) or receive_mapping not in {"dict", "user-dict"}:
        raise ValueError("BaseHTTPMiddleware receive message mapping must be dict or user-dict")
    concurrent_calls = request.get("concurrent_calls", 1)
    if type(concurrent_calls) is not int or not 1 <= concurrent_calls <= 4:
        raise ValueError("BaseHTTPMiddleware concurrent_calls must be an integer from 1 to 4")
    if concurrent_calls > 1 and (
        background_task_spec is None
        or background_task_spec["kind"] != "async-delay"
        or "constructor_dispatch" not in middleware_layers[0]
        or len(middleware_layers) != 1
    ):
        raise ValueError(
            "concurrent BaseHTTPMiddleware calls require constructor call-next dispatch and an async background task"
        )
    scope_value = request["scope"]
    if not isinstance(scope_value, dict):
        raise ValueError("BaseHTTPMiddleware request scope must be an object")
    raw_scope_type = scope_value.get("type")
    _, scope_type_value = _materialize_scope_type_spec(raw_scope_type)
    scope_type_python_inequality_probe = isinstance(raw_scope_type, dict)
    if scope_type_python_inequality_probe:
        descriptor = _exact_object(
            raw_scope_type, {"str_subclass"}, "BaseHTTPMiddleware scope.type"
        )
        subclass = _exact_object(
            descriptor["str_subclass"],
            {"value", "not_equal_result"},
            "BaseHTTPMiddleware scope.type str_subclass",
        )
        if subclass["value"] != "http" or subclass["not_equal_result"] is not True:
            raise ValueError(
                "BaseHTTPMiddleware scope type subclass must return true from Python inequality"
            )
        scope_type_value = "http"
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
    background_task_case = background_task_spec is not None
    direct_request_stream_endpoint = (
        downstream_spec is not None and downstream_spec["kind"] == "request-stream-asgi-endpoint"
    )
    source_sparse_scope = (
        (background_task_case and background_task_spec["kind"] == "async-delay")
        or direct_request_stream_endpoint
        or route_kind == "request-body-client-disconnect-response"
        or scope_type_python_inequality_probe
    )
    if scope_type_python_inequality_probe:
        scope_spec = _exact_object(
            scope_value,
            {"type"},
            "BaseHTTPMiddleware scope inequality input",
        )
        if (
            downstream_spec is None
            or downstream_spec["kind"] != "asgi-sequence"
            or route_spec is not None
            or len(middleware_layers) != 1
            or dispatch_actions
            != [{"kind": "await-call-next"}, {"kind": "return-call-next-response"}]
            or returned != "call-next"
            or outer_receive_transform is not None
            or background_task_spec is not None
        ):
            raise ValueError(
                "scope inequality input requires direct pass-through to one ASGI sequence"
            )
    elif direct_request_stream_endpoint:
        scope_spec = _exact_object(
            scope_value, {"type"}, "BaseHTTPMiddleware direct ASGI HTTP scope"
        )
        if scope_spec != {"type": "http"}:
            raise ValueError("request-stream endpoint must preserve the pinned minimal HTTP scope")
    elif source_sparse_scope:
        scope_spec = _exact_object(
            scope_value,
            {"type", "version", "method", "path"},
            "BaseHTTPMiddleware source-direct HTTP scope",
        )
        if scope_spec != {"type": "http", "version": "3", "method": "GET", "path": "/"}:
            raise ValueError("direct ASGI case must preserve the pinned source scope")
    else:
        if isinstance(scope_value, dict) and "extensions" in scope_value:
            scope_keys.add("extensions")
        scope_spec = _exact_object(scope_value, scope_keys, "BaseHTTPMiddleware HTTP scope")
        _exact_object(
            scope_spec["asgi"], {"version", "spec_version"}, "BaseHTTPMiddleware ASGI version"
        )
    path = (
        "/"
        if direct_request_stream_endpoint or scope_type_python_inequality_probe
        else scope_spec["path"]
    )
    if (
        scope_type_value != "http"
        or (
            not source_sparse_scope
            and scope_spec["asgi"] != {"version": "3.0", "spec_version": "2.4"}
        )
        or (
            not direct_request_stream_endpoint
            and not scope_type_python_inequality_probe
            and (
                not isinstance(scope_spec["method"], str)
                or scope_spec["method"] not in {"GET", "POST"}
            )
        )
        or not isinstance(path, str)
        or (
            not source_sparse_scope
            and (
                not isinstance(scope_spec["scheme"], str)
                or scope_spec["scheme"] not in {"http", "https"}
            )
        )
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
        if _decode_base64(
            scope_spec["raw_path_base64"], "BaseHTTPMiddleware raw path"
        ) != path.encode("ascii"):
            raise ValueError("BaseHTTPMiddleware scope raw path input is invalid")
        _decode_base64(scope_spec["query_string_base64"], "BaseHTTPMiddleware query string")
        headers = scope_spec["headers_base64_pairs"]
        if not isinstance(headers, list):
            raise ValueError("BaseHTTPMiddleware scope headers must be an array")
        for index, pair in enumerate(headers):
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"BaseHTTPMiddleware scope header[{index}] is invalid")
            for value in pair:
                if not isinstance(value, str):
                    raise ValueError(f"BaseHTTPMiddleware scope header[{index}] is invalid")
                _decode_base64(value, f"BaseHTTPMiddleware scope header[{index}]")
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
            receive_spec = _exact_object(
                receive_spec,
                {"type", "body_base64", "more_body"},
                f"BaseHTTPMiddleware HTTP request event[{index}]",
            )
            if type(receive_spec["more_body"]) is not bool:
                raise ValueError("BaseHTTPMiddleware request more_body must be boolean")
            _decode_base64(receive_spec["body_base64"], f"BaseHTTPMiddleware request body[{index}]")
            request_event_specs.append(receive_spec)
        elif receive_spec["type"] == "http.disconnect":
            _exact_object(
                receive_spec,
                {"type"},
                f"BaseHTTPMiddleware disconnect event[{index}]",
            )
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
    if (
        disconnect_event_indices
        and (
            downstream_spec is None
            or downstream_spec["kind"] not in {"disconnect-polling-app", "receive-sequence-app"}
        )
        and not (
            route_kind == "request-body-client-disconnect-response"
            and not request_event_specs
            and receive_specs == [{"type": "http.disconnect"}]
        )
    ):
        raise ValueError("explicit http.disconnect input requires a downstream disconnect case")
    receive_after_events = request["receive_after_events"]
    if isinstance(receive_after_events, str):
        if receive_after_events not in {"disconnect", "block"}:
            raise ValueError("receive_after_events must be disconnect, block, or a raise input")
    else:
        receive_after_events = _exact_object(
            receive_after_events,
            {"kind", "class", "message"},
            "BaseHTTPMiddleware exhausted receive behavior",
        )
        allowed_receive_exceptions = (
            {"NotImplementedError"}
            if file_response_pathsend or (background_task_case and source_sparse_scope)
            else {"StopAsyncIteration"}
            if route_kind == "request-body-client-disconnect-response"
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
    if route_kind == "request-body-client-disconnect-response" and (
        receive_specs != [{"type": "http.disconnect"}]
        or request["receive_after_events"]
        != {"kind": "raise", "class": "StopAsyncIteration", "message": ""}
        or send_checkpoints
    ):
        raise ValueError(
            "client-disconnect route must preserve the pinned one-event receive sequence"
        )
    if stacked_disconnect_lifecycle and receive_specs != [{"type": "http.disconnect"}]:
        raise ValueError("middleware lifecycle stack requires one initial http.disconnect event")

    request_body = b"".join(
        _decode_base64(item["body_base64"], "BaseHTTPMiddleware request body")
        for item in request_event_specs
    )
    reads_body_before_call_next = (
        route_kind in {"request-body-response", "request-body-empty-response"}
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
        route_kind in {"request-body-response", "request-body-empty-response"}
        and request_body
        and await_index is not None
        and any(action["kind"] == "read-request-body" for action in dispatch_actions[:await_index])
        and any(
            action["kind"] == "read-request-body" for action in dispatch_actions[await_index + 1 :]
        )
    ):
        required_covers.add(f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.body-cache-replay")
    if outer_receive_transform is not None:
        if (
            downstream_spec is not None
            or route_kind != "request-body-empty-response"
            or route_spec["methods"] != ["POST"]
            or scope_spec["method"] != "POST"
            or len(request_event_specs) != 1
            or not request_body
            or request_event_specs[0]["more_body"]
            or dispatch_actions
            != [
                {"kind": "read-request-body"},
                {"kind": "await-call-next"},
                {"kind": "return-call-next-response"},
            ]
            or send_checkpoints
        ):
            raise ValueError(
                "outer receive transformation requires one non-empty POST body, a body-reading route, and cache-before-call_next dispatch"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.outer-middleware-receive-transformation"
        )
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
            _decode_base64(item["body_base64"], "BaseHTTPMiddleware request body")
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
    elif direct_request_stream_endpoint:
        chunks = [
            _decode_base64(item["body_base64"], "BaseHTTPMiddleware request body")
            for item in request_event_specs
        ]
        expected_receive_exhaustion = {
            "kind": "raise",
            "class": "AssertionError",
            "message": "Should not be called, no need to poll for disconnect",
        }
        if (
            returned != "call-next"
            or dispatch_actions
            != [
                {"kind": "read-request-stream-next"},
                {"kind": "await-call-next"},
                {"kind": "read-request-stream-next"},
                {"kind": "return-call-next-response"},
            ]
            or downstream_spec["stop_after_chunks"] != 1
            or downstream_spec["response_status_code"] != 200
            or len(chunks) != 3
            or any(not chunk for chunk in chunks)
            or request["receive_after_events"] != expected_receive_exhaustion
            or send_checkpoints
        ):
            raise ValueError(
                "direct request-stream forwarding requires the pinned three-chunk interleaving and must not poll receive after the final body event"
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
                bool(_decode_base64(event["body_base64"], "BaseHTTPMiddleware request body"))
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
        reads_stream_after_pre_call_next_body_cache = dispatch_actions == [
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
                or reads_stream_after_pre_call_next_body_cache
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
        elif reads_stream_after_pre_call_next_body_cache:
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
                bool(_decode_base64(event["body_base64"], "BaseHTTPMiddleware request body"))
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
        if returned == "replacement":
            if request["receive_after_events"] != "block" or send_checkpoints != [0, 1]:
                raise ValueError(
                    "downstream receive race requires a blocking receive, replacement response, and checkpoints after both outer sends"
                )
            required_covers.add(
                f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.response-completion-unblocks-downstream-receive"
            )
            if saw_response_iterator_overlap:
                request_body_events = [
                    event for event in request_event_specs if event["type"] == "http.request"
                ]
                downstream_steps = downstream_spec["steps"]
                if (
                    scope_spec["method"] != "GET"
                    or len(request_body_events) != 1
                    or len(request_event_specs) != 1
                    or _decode_base64(
                        request_body_events[0]["body_base64"],
                        "BaseHTTPMiddleware request body",
                    )
                    or request_body_events[0]["more_body"]
                    or disconnect_event_indices
                    or len(dispatch_actions) != 3
                    or dispatch_actions[0] != {"kind": "await-call-next"}
                    or dispatch_actions[1]["kind"] != "overlap-call-next-response-body-reads"
                    or dispatch_actions[2]["kind"] != "return-plain-text-response"
                    or len(downstream_steps) != 3
                    or downstream_steps[0]["kind"] != "send"
                    or downstream_steps[0]["message"]["type"] != "http.response.start"
                    or downstream_steps[1:] != [{"kind": "receive"}, {"kind": "receive"}]
                ):
                    raise ValueError(
                        "overlapping response body reads require one empty GET request, a pending response body, cancellation and iterator close before replacement, and two downstream receives"
                    )
                required_covers.add(
                    f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.body-iterator-overlapping-read-and-cancellation"
                )
        elif not (
            returned == "call-next"
            and (
                (
                    saw_response_header_observation
                    and request["receive_after_events"] == "block"
                    and not send_checkpoints
                )
                or scope_type_python_inequality_probe
                or response_start_type_python_equality_probe
                or response_body_type_python_equality_probe
                or response_pathsend_type_python_equality_probe
            )
        ):
            raise ValueError(
                "downstream ASGI pass-through requires a completed call_next header observation and blocking receive"
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
            or _decode_base64(
                request_body_events[0]["body_base64"], "BaseHTTPMiddleware request body"
            )
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
            _decode_base64(item["body_base64"], "BaseHTTPMiddleware request body")
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
    closed_response_body_iterator = False
    if (
        saw_response_body_read
        and downstream_spec is not None
        and downstream_spec["kind"] == "asgi-sequence"
    ):
        downstream_steps = downstream_spec["steps"]
        body_messages = [
            step["message"]
            for step in downstream_steps[:-1]
            if step.get("kind") == "send"
            and step.get("message", {}).get("type") == "http.response.body"
        ]
        closed_response_body_iterator = (
            len(dispatch_actions) == 4
            and returned == "call-next"
            and dispatch_actions[0] == {"kind": "await-call-next"}
            and dispatch_actions[1].get("kind") == "observe-call-next-response-headers"
            and dispatch_actions[2] == {"kind": "read-call-next-response-body-next-and-close"}
            and dispatch_actions[3] == {"kind": "return-call-next-response"}
            and not saw_response_iterator_overlap
            and request["receive_after_events"] == "block"
            and not send_checkpoints
            and len(body_messages) >= 2
            and all(message.get("more_body") is True for message in body_messages)
            and all(
                bool(_decode_base64(message["body_base64"], "downstream ASGI response body"))
                for message in body_messages
            )
        )
    if (
        saw_response_body_read
        and not closed_response_body_iterator
        and (downstream_spec is None or downstream_spec["kind"] != "stream-until-disconnect-app")
    ):
        raise ValueError("call_next response body read requires a streaming-until-disconnect app")
    if closed_response_body_iterator:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.return-call-next-response-with-closed-body-iterator"
        )
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
    if background_task_case:
        if (
            route_spec["methods"] != ["GET"]
            or (concurrent_calls == 1 and endpoint_spec["content"] != "")
            or endpoint_spec["status_code"] != 200
            or dispatch_actions
            != [{"kind": "await-call-next"}, {"kind": "return-call-next-response"}]
            or downstream_spec is not None
            or send_checkpoints
        ):
            raise ValueError(
                "background task case must preserve the pinned GET response and dispatch"
            )
        if source_sparse_scope:
            if receive_specs or request["receive_after_events"] != {
                "kind": "raise",
                "class": "NotImplementedError",
                "message": "Should not be called!",
            }:
                raise ValueError(
                    "background completion case must preserve the pinned direct ASGI receive callback"
                )
        elif (
            request_event_specs != [{"type": "http.request", "body_base64": "", "more_body": False}]
            or request["receive_after_events"] != "disconnect"
            or [
                (
                    _decode_base64(name, "scope header name"),
                    _decode_base64(value, "scope header value"),
                )
                for name, value in scope_spec["headers_base64_pairs"]
            ]
            != [
                (b"host", b"testserver"),
                (b"accept", b"*/*"),
                (b"accept-encoding", b"gzip, deflate"),
                (b"connection", b"keep-alive"),
                (b"user-agent", b"testclient"),
            ]
            or scope_spec["client"] != ["testclient", 50000]
            or scope_spec["server"] != ["testserver", 80]
        ):
            raise ValueError(
                "background failure case must replay the pinned empty TestClient GET scope and receive input"
            )
        background_requirement = (
            "background-task-completes-after-response-send"
            if background_task_spec["kind"] == "async-delay"
            else "background-task-failure-propagates-after-response-send"
        )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.{background_requirement}"
        )
    if context_manager_cleanup_spec is not None:
        if background_task_spec is None or background_task_spec["kind"] not in {
            "async-delay",
            "async-delay-and-raise",
        }:
            raise ValueError(
                "context-manager cleanup input requires the pinned delayed async background task"
            )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.async-context-manager-cleanup-completes"
        )
    if wide_status_probe:
        steps = downstream_spec["steps"] if downstream_spec is not None else []
        request_body_events = [event for event in receive_specs if event["type"] == "http.request"]
        if (
            downstream_spec is None
            or downstream_spec["kind"] != "asgi-sequence"
            or route_spec is not None
            or len(base_http_layers) != 1
            or len(middleware_layers) != 1
            or dispatch_actions
            != [
                {"kind": "await-call-next"},
                {
                    "kind": "observe-call-next-response-headers",
                    "name": "x-status-probe",
                },
                {"kind": "return-call-next-response"},
            ]
            or await_action_kind != "await-call-next"
            or returned != "call-next"
            or len(steps) != 3
            or steps[0]["message"].get("status") != 65536
            or steps[1]["message"].get("type") != "http.response.body"
            or steps[1]["message"].get("more_body") is not False
            or steps[2] != {"kind": "receive"}
            or scope_spec["method"] != "GET"
            or path != "/"
            or len(request_body_events) != 1
            or _decode_base64(
                request_body_events[0]["body_base64"], "BaseHTTPMiddleware request body"
            )
            or request_body_events[0]["more_body"]
            or disconnect_event_indices
            or receive_after_events != "block"
            or send_checkpoints
            or outer_receive_transform is not None
            or background_task_spec is not None
            or context_manager_cleanup_spec is not None
        ):
            raise ValueError(
                "wide downstream status requires one empty GET call_next pass-through to an ASGI sequence"
            )
        required_covers.add(BASE_HTTP_STATUS_INTEGER_REQUIREMENT)
    if saw_response_body_iterator_replacement:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.call-next-response-body-iterator-replacement"
        )
    if returned == "replacement" and not awaited:
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.dispatch-short-circuits-downstream-app"
        )
    if (
        saw_response_header_observation
        and route_kind == "plain-text-response"
        and response_header_observation_name is not None
        and response_header_observation_name.lower() not in {"content-length", "content-type"}
    ):
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.call-next-response-headers-mapping-get"
        )
    if any(
        action["kind"] == "observe-call-next-response-headers" and "probes" in action
        for action in dispatch_actions
    ):
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.call-next-response-headers-mapping-protocol"
        )
    scope_container = case.get("scope_container")
    if scope_container == "user-dict":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.mutable-scope-mapping"
        )
    elif isinstance(scope_container, dict) and scope_container.get("kind") == "user-dict-fault":
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.mutable-scope-mapping"
        )
        required_covers.add(
            f"{BASE_HTTP_SURFACE}.{BASE_HTTP_WORKFLOW_OPERATION}.scope-type-lookup-error-propagation"
        )
    if scope_type_python_inequality_probe:
        if (
            application["debug"]
            or receive_specs != [{"type": "http.request", "body_base64": "", "more_body": False}]
            or receive_after_events != "disconnect"
            or send_checkpoints
            or downstream_spec is None
            or len(downstream_spec["steps"]) != 4
            or [step.get("kind") for step in downstream_spec["steps"]]
            != ["send", "send", "send", "receive"]
            or any(
                step.get("message_mapping", "dict") != "dict"
                for step in downstream_spec["steps"][:-1]
            )
        ):
            raise ValueError(
                "scope inequality input requires an empty request and two direct response body sends"
            )
        required_covers.add(BASE_HTTP_SCOPE_TYPE_INEQUALITY_REQUIREMENT)
    if (
        response_start_type_python_equality_probe
        or response_body_type_python_equality_probe
        or response_pathsend_type_python_equality_probe
    ):
        message_steps = downstream_spec["steps"] if downstream_spec is not None else []
        expected_step_count = 3 if response_pathsend_type_python_equality_probe else 4
        if (
            not awaited
            or returned != "call-next"
            or route_spec is not None
            or scope_type_python_inequality_probe
            or application["debug"]
            or len(middleware_layers) != 1
            or dispatch_actions
            != [{"kind": "await-call-next"}, {"kind": "return-call-next-response"}]
            or downstream_spec is None
            or downstream_spec["kind"] != "asgi-sequence"
            or len(message_steps) != expected_step_count
            or [step.get("kind") for step in message_steps]
            != ["send"] * (expected_step_count - 1) + ["receive"]
            or any(step.get("message_mapping", "dict") != "dict" for step in message_steps[:-1])
            or receive_specs != [{"type": "http.request", "body_base64": "", "more_body": False}]
            or receive_after_events != "disconnect"
            or send_checkpoints
            or outer_receive_transform is not None
            or background_task_spec is not None
            or saw_response_header_observation
        ):
            raise ValueError(
                "downstream message equality probes require a direct pass-through ASGI sequence"
            )
        if response_start_type_python_equality_probe:
            required_covers.add(BASE_HTTP_RESPONSE_START_TYPE_EQUALITY_REQUIREMENT)
        if response_body_type_python_equality_probe:
            required_covers.add(BASE_HTTP_RESPONSE_BODY_TYPE_EQUALITY_REQUIREMENT)
        if response_pathsend_type_python_equality_probe:
            required_covers.add(BASE_HTTP_RESPONSE_PATHSEND_TYPE_EQUALITY_REQUIREMENT)
    if not isinstance(case["covers"], list) or set(case["covers"]) != required_covers:
        raise ValueError("BaseHTTPMiddleware covers differ from its input actions")

    import anyio
    from starlette.applications import Starlette
    from starlette.background import BackgroundTask
    from starlette.datastructures import URL, Headers, QueryParams
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import FileResponse, PlainTextResponse, Response
    from starlette.routing import Route

    execution_trace: list[dict[str, Any]] = []
    dispatch_body_reads: list[dict[str, Any]] = []
    dispatch_request_helper_observations: list[dict[str, Any]] = []
    dispatch_stream_reads: list[dict[str, Any]] = []
    dispatch_response_stream_reads: list[dict[str, Any]] = []
    dispatch_response_header_observations: list[dict[str, Any]] = []
    downstream_stream_reads: list[dict[str, Any]] = []
    downstream_body_reads: list[dict[str, Any]] = []
    downstream_receive_transformations: list[dict[str, Any]] = []
    outer_receive_transformations: list[dict[str, Any]] = []
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
    middleware_dispatch_events: list[str] = []
    middleware_background_events: list[str] = []
    middleware_response_background_states: list[dict[str, Any]] = []
    endpoint_body_events: list[dict[str, Any]] = []

    class InputDefinedBaseHTTPMiddleware(BaseHTTPMiddleware):
        def __init__(self, app: Any, dispatch_actions_for_case: list[dict[str, Any]] | None = None):
            self._input_dispatch_actions = (
                dispatch_actions if dispatch_actions_for_case is None else dispatch_actions_for_case
            )
            super().__init__(app)

        async def dispatch(self, request: Any, call_next: Any) -> Any:
            response = None
            stream_iterator = None
            input_actions = self._input_dispatch_actions
            for action_index, action in enumerate(input_actions):
                kind = action["kind"]
                if kind == "read-request-body":
                    body = await request.body()
                    dispatch_body_reads.append(
                        {
                            "action_index": action_index,
                            "body_base64": base64.b64encode(body).decode("ascii"),
                        }
                    )
                elif kind == "observe-request-helpers":
                    headers = Headers(scope=request.scope)
                    query_params = QueryParams(request.scope["query_string"])
                    url = URL(scope=request.scope)
                    dispatch_request_helper_observations.append(
                        {
                            "action_index": action_index,
                            "request": {
                                "method": request.method,
                                "url": str(request.url),
                                "headers": request.headers.items(),
                                "query_params": request.query_params.multi_items(),
                            },
                            "helpers": {
                                "headers": headers.items(),
                                "query_params": query_params.multi_items(),
                                "url": str(url),
                            },
                        }
                    )
                elif kind == "set-request-state":
                    setattr(request.state, action["name"], action["value"])
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
                elif kind == "overlap-call-next-response-body-reads":
                    body_iterator = response.body_iterator
                    read_tasks = [asyncio.create_task(body_iterator.__anext__()) for _ in range(2)]
                    _, pending_tasks = await asyncio.wait(
                        read_tasks, timeout=action["timeout_ms"] / 1000
                    )
                    timed_out = bool(pending_tasks)
                    for task in pending_tasks:
                        task.cancel()
                    read_results = await asyncio.gather(*read_tasks, return_exceptions=True)
                    outcomes = []
                    for result in read_results:
                        if isinstance(result, asyncio.CancelledError):
                            outcome = {"kind": "cancelled"}
                        elif isinstance(result, BaseException):
                            outcome = {
                                "kind": "exception",
                                "class": f"{type(result).__module__}.{type(result).__qualname__}",
                                "message": str(result),
                            }
                        else:
                            outcome = {
                                "kind": "yielded",
                                "body_base64": base64.b64encode(result).decode("ascii"),
                            }
                        outcomes.append(outcome)
                    try:
                        await body_iterator.aclose()
                    except Exception as exc:
                        iterator_close = {
                            "kind": "exception",
                            "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                            "message": str(exc),
                        }
                    else:
                        iterator_close = {"kind": "closed"}
                    dispatch_response_stream_reads.append(
                        {
                            "action_index": action_index,
                            "timed_out": timed_out,
                            "outcomes": outcomes,
                            "iterator_close": iterator_close,
                        }
                    )
                elif kind == "await-call-next":
                    response = await call_next(request)
                elif kind == "observe-call-next-response-headers":
                    name = action["name"]
                    observation = {
                        "action_index": action_index,
                        "lookup_name": name,
                        "lookup_value": response.headers.get(name),
                        "iterated_names": list(response.headers),
                        "length": len(response.headers),
                        "items": response.headers.items(),
                    }
                    if "probes" in action:
                        probe_outcomes = []
                        for probe in action["probes"]:
                            probe_name = probe["name"]
                            try:
                                if probe["kind"] == "getitem":
                                    probe_outcome = {
                                        "kind": "value",
                                        "value": response.headers[probe_name],
                                    }
                                elif probe["kind"] == "contains":
                                    probe_outcome = {
                                        "kind": "value",
                                        "value": probe_name in response.headers,
                                    }
                                else:
                                    del response.headers[probe_name]
                                    probe_outcome = {"kind": "deleted"}
                            except Exception as exc:
                                probe_outcome = {
                                    "kind": "exception",
                                    "class": type(exc).__name__,
                                    "message": str(exc),
                                }
                            probe_outcomes.append(
                                {"probe_kind": probe["kind"], "name": probe_name, **probe_outcome}
                            )
                        observation["probes"] = probe_outcomes
                    dispatch_response_header_observations.append(observation)
                elif kind == "await-call-next-catching-exception":
                    action = input_actions[action_index]
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
                elif kind == "set-call-next-response-body-iterator":
                    chunks = [
                        base64.b64decode(chunk, validate=True) for chunk in action["chunks_base64"]
                    ]

                    async def replacement_body_iterator(input_chunks: list[bytes] = chunks):
                        for chunk in input_chunks:
                            yield chunk

                    response.body_iterator = replacement_body_iterator()
                elif kind == "set-call-next-response-header-from-request-state":
                    response.headers[action["name"]] = getattr(request.state, action["state_name"])
                elif kind == "append-middleware-event":
                    middleware_dispatch_events.append(action["value"])
                elif kind == "observe-call-next-response-background":
                    middleware_response_background_states.append(
                        {
                            "label": action["label"],
                            "has_background": response.background is not None,
                        }
                    )
                elif kind == "set-call-next-response-background-task":
                    background_value = action["value"]

                    def record_middleware_background(value: str = background_value) -> None:
                        middleware_background_events.append(value)

                    response.background = BackgroundTask(record_middleware_background)
                elif kind == "return-call-next-response":
                    return response
                elif kind == "return-plain-text-response":
                    return PlainTextResponse(
                        action["content"],
                        status_code=action["status_code"],
                    )
            raise RuntimeError("BaseHTTPMiddleware dispatch action sequence returned no response")

    class InputDefinedAsyncContextManagerMiddleware:
        def __init__(self, app: Any, exit_delay_seconds: float):
            self.app = app
            self.exit_delay_seconds = exit_delay_seconds

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            execution_trace.append({"event": "context-manager-enter"})

            async def cleanup() -> None:
                execution_trace.append({"event": "context-manager-cleanup-start"})
                await anyio.sleep(self.exit_delay_seconds)
                execution_trace.append({"event": "context-manager-cleanup-complete"})

            async with contextlib.AsyncExitStack() as stack:
                stack.push_async_callback(cleanup)
                await self.app(scope, receive, send)

    def configured_middleware(middleware_spec: dict[str, Any]) -> Any:
        if middleware_spec["kind"] == "async-context-manager-cleanup":
            return Middleware(
                InputDefinedAsyncContextManagerMiddleware,
                exit_delay_seconds=middleware_spec["exit_delay_seconds"],
            )
        if "constructor_dispatch" in middleware_spec:

            async def passthrough_dispatch(request: Any, call_next: Any) -> Any:
                return await call_next(request)

            return Middleware(BaseHTTPMiddleware, dispatch=passthrough_dispatch)
        if "dispatch_callable" in middleware_spec:
            dispatch_spec = middleware_spec["dispatch_callable"]
            exception_spec = dispatch_spec["exception"]
            exception_type = getattr(builtins, exception_spec["class"])

            def sync_failing_dispatch(request: Any, call_next: Any) -> Any:
                raise exception_type(exception_spec["message"])

            return Middleware(BaseHTTPMiddleware, dispatch=sync_failing_dispatch)
        return Middleware(
            InputDefinedBaseHTTPMiddleware,
            dispatch_actions_for_case=middleware_spec["dispatch_actions"],
        )

    routes = []
    if route_spec is not None:
        if route_kind == "request-body-response":

            async def endpoint(request: Any) -> Any:
                body = await request.body()
                downstream_body_reads.append(
                    {"body_base64": base64.b64encode(body).decode("ascii")}
                )
                return PlainTextResponse(body)
        elif route_kind == "request-body-empty-response":

            async def endpoint(request: Any) -> Any:
                body = await request.body()
                downstream_body_reads.append(
                    {"body_base64": base64.b64encode(body).decode("ascii")}
                )
                return Response()
        elif route_kind == "request-body-client-disconnect-response":
            from starlette.requests import ClientDisconnect

            async def endpoint(request: Any) -> Any:
                try:
                    await request.body()
                except ClientDisconnect as exc:
                    endpoint_body_events.append(
                        {"kind": "client-disconnect", "exception_class": type(exc).__name__}
                    )
                    return Response(b"")
                raise AssertionError(endpoint_spec["unexpected_exception_message"])
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
                _decode_base64(
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
                if background_task_spec["kind"] == "async-delay-and-raise":
                    exception_type = getattr(builtins, background_task_spec["exception"]["class"])
                    raise exception_type(background_task_spec["exception"]["message"])
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
            middleware=[
                configured_middleware(middleware_spec) for middleware_spec in middleware_layers
            ],
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
                    message_type, message_type_value = (
                        _materialize_base_http_downstream_message_type(message_spec["type"])
                    )
                    if message_type_value == "http.response.start":
                        message = {
                            "type": message_type,
                            "status": message_spec["status"],
                            "headers": [
                                (
                                    _decode_base64(pair[0], "downstream response header name"),
                                    _decode_base64(pair[1], "downstream response header value"),
                                )
                                for pair in message_spec["headers_base64_pairs"]
                            ],
                        }
                    elif message_type_value == "http.response.body":
                        message = {
                            "type": message_type,
                            "body": _decode_base64(
                                message_spec["body_base64"], "downstream response body"
                            ),
                            "more_body": message_spec["more_body"],
                        }
                    else:
                        message = {"type": message_type, "path": message_spec["path"]}
                    if step.get("message_mapping", "dict") == "user-dict":
                        message = UserDict(message)
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
                            _decode_base64(pair[0], "downstream streaming response header name"),
                            _decode_base64(pair[1], "downstream streaming response header value"),
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
                                "body": _decode_base64(
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
    elif downstream_spec is not None and downstream_spec["kind"] == "request-stream-asgi-endpoint":

        async def downstream_endpoint(scope: Any, receive: Any, send: Any) -> None:
            request_value = Request(scope, receive)
            read_count = 0
            async for chunk in request_value.stream():
                downstream_stream_reads.append(
                    {
                        "index": len(downstream_stream_reads),
                        "body_base64": base64.b64encode(chunk).decode("ascii"),
                    }
                )
                read_count += 1
                if read_count >= downstream_spec["stop_after_chunks"]:
                    break
            await Response(status_code=downstream_spec["response_status_code"])(
                scope,
                receive,
                send,
            )

        app = InputDefinedBaseHTTPMiddleware(downstream_endpoint)
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
                _decode_base64(response_spec["body_base64"], "downstream response body"),
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
            middleware=[
                configured_middleware(middleware_spec) for middleware_spec in middleware_layers
            ],
        )

    scope = _make_scope(scope_spec, case.get("scope_container", "dict"))
    incoming = [_make_message(spec) for spec in receive_specs]
    if receive_mapping == "user-dict":
        incoming = [UserDict(message) for message in incoming]
    sent: list[dict[str, Any]] = []
    request_receive_events: list[dict[str, Any]] = []
    task_group_exit_events: list[dict[str, Any]] = []
    receive_index = 0
    receive_call_count = 0
    send_index = 0
    send_checkpoint_indices = set(send_checkpoints)

    async def receive() -> dict[str, Any]:
        nonlocal receive_index, receive_call_count
        receive_call_count += 1
        if background_task_case:
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
            if background_task_case:
                execution_trace.append({"event": "response-complete"})
        if send_index in send_checkpoint_indices:
            await asyncio.sleep(0)
        send_index += 1

    async def invoke_application() -> None:
        application_receive = receive
        if outer_receive_transform is not None:
            inner_receive = application_receive
            receive_transform_index = 0

            async def transformed_receive() -> dict[str, Any]:
                nonlocal receive_transform_index
                message = await inner_receive()
                before = _canonical_http_message(message)
                if message["type"] == "http.request":
                    message["body"] = message.get("body", b"") + outer_receive_suffix
                outer_receive_transformations.append(
                    {
                        "receive_index": receive_transform_index,
                        "before": before,
                        "after": _canonical_http_message(message),
                    }
                )
                receive_transform_index += 1
                return message

            application_receive = transformed_receive
        if concurrent_calls == 1:
            await app(scope, application_receive, send)
        else:
            async with anyio.create_task_group() as task_group:
                for _ in range(concurrent_calls):
                    task_group.start_soon(app, scope, application_receive, send)
        if context_manager_cleanup_spec is not None:
            execution_trace.append({"event": "application-return"})

    original_create_task_group = anyio.create_task_group
    task_group_probe_enabled = dispatch_callable_spec is not None
    if task_group_probe_enabled:

        class TaskGroupExitProbe:
            def __init__(self, task_group: Any) -> None:
                self._task_group = task_group

            async def __aenter__(self) -> Any:
                result = await self._task_group.__aenter__()
                task_group_exit_events.append({"event": "enter"})
                return result

            async def __aexit__(
                self,
                exception_type: type[BaseException] | None,
                exception: BaseException | None,
                traceback: Any,
            ) -> Any:
                task_group_exit_events.append(
                    {
                        "event": "exit",
                        "exception": (
                            None
                            if exception is None
                            else {
                                "class": f"{type(exception).__module__}.{type(exception).__qualname__}",
                                "message": str(exception),
                            }
                        ),
                    }
                )
                return await self._task_group.__aexit__(exception_type, exception, traceback)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._task_group, name)

        def observed_create_task_group(*args: Any, **kwargs: Any) -> Any:
            return TaskGroupExitProbe(original_create_task_group(*args, **kwargs))

        anyio.create_task_group = observed_create_task_group
    try:
        asyncio.run(invoke_application())
        propagated_exception = None
    except Exception as exc:
        propagated_exception = _base_http_exception_value(exc)
    finally:
        if task_group_probe_enabled:
            anyio.create_task_group = original_create_task_group
        if file_response_temporary_directory is not None:
            file_response_temporary_directory.cleanup()
    if downstream_stream_guard_fired:
        raise TimeoutError(
            "input-defined BaseHTTPMiddleware streaming guard expired before http.disconnect"
        )
    if background_task_case:
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
        "dispatch_request_helper_observations": dispatch_request_helper_observations,
        "dispatch_stream_reads": dispatch_stream_reads,
        "dispatch_response_stream_reads": dispatch_response_stream_reads,
        "dispatch_response_header_observations": dispatch_response_header_observations,
        "downstream_stream_reads": downstream_stream_reads,
        "downstream_body_reads": downstream_body_reads,
        "downstream_receive_transformations": downstream_receive_transformations,
        "outer_receive_transformations": outer_receive_transformations,
        "downstream_receive_events": downstream_receive_events,
        "downstream_poll_results": downstream_poll_results,
        "downstream_stream_cancellation_results": downstream_stream_cancellation_results,
        "dispatch_caught_exceptions": dispatch_caught_exceptions,
        "dispatch_disconnect_checks": dispatch_disconnect_checks,
        "request_receive_events": request_receive_events,
        "execution_trace": execution_trace,
        "propagated_exception": propagated_exception,
        "middleware_dispatch_events": middleware_dispatch_events,
        "middleware_background_events": sorted(middleware_background_events),
        "middleware_response_background_states": middleware_response_background_states,
        "endpoint_body_events": endpoint_body_events,
    }
    if task_group_probe_enabled:
        value["task_group_exit_events"] = task_group_exit_events
    if background_task_case:
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
    _exact_object(
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

    constructor = _exact_object(
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
        _exact_object(
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
    if constructor["clock_epoch"] is not None and type(constructor["clock_epoch"]) is not int:
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
                    _decode_base64(pair[0], "WebSocket accept header name"),
                    _decode_base64(pair[1], "WebSocket accept header value"),
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
        response_send = send
        if "response_start" in action:
            response_start = action["response_start"]
            header_pairs = [
                (
                    _decode_base64(pair[0], "SessionMiddleware response-start header name"),
                    _decode_base64(pair[1], "SessionMiddleware response-start header value"),
                )
                for pair in response_start["headers_base64_pairs"]
            ]
            response_headers = (
                tuple(header_pairs)
                if response_start["headers_representation"] == "tuple"
                else header_pairs
            )
            response_message_type = (
                _materialize_scope_type_spec(response_start["type"])[0]
                if "type" in response_start
                else None
            )

            async def send_response_start_headers(message: dict[str, Any]) -> None:
                if message["type"] == "http.response.start":
                    message["headers"] = response_headers
                    if "type" in response_start:
                        message["type"] = response_message_type
                await send(message)

            response_send = send_response_start_headers
        await response(scope, receive, response_send)

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
    clock_epoch = constructor["clock_epoch"]
    if clock_epoch is not None:
        runtime = getattr(middleware, "_runtime", None)
        set_clock_for_test = getattr(runtime, "set_clock_for_test", None)
        if callable(set_clock_for_test):
            set_clock_for_test(clock_epoch)

    workflow_error: BaseException | None = None

    async def run_requests() -> list[dict[str, Any]]:
        nonlocal workflow_error
        outputs = []
        prior_set_cookies: dict[str, str | None] = {}
        actions_by_id: dict[str, dict[str, Any]] = {}
        seen_request_ids: set[str] = set()
        for index, request_spec in enumerate(case["requests"]):
            request_spec = _exact_object(
                request_spec,
                {"request_id", "scope", "receive", "cookie_source", "action"},
                f"SessionMiddleware request[{index}]",
            )
            request_id = request_spec["request_id"]
            if not isinstance(request_id, str) or request_id in seen_request_ids:
                raise ValueError("SessionMiddleware request_id values must be unique strings")
            seen_request_ids.add(request_id)
            scope = _make_scope(request_spec["scope"])
            scope_type = scope["type"]
            if (
                scope_type not in ("http", "websocket")
                and request_spec["cookie_source"] is not None
            ):
                raise ValueError("non-HTTP pass-through cannot receive a session cookie")
            if scope_type in ("http", "websocket") and any(
                name.lower() == b"cookie" for name, _value in scope["headers"]
            ):
                raise ValueError("session cookie input must use cookie_source, not scope headers")
            if scope_type == "http":
                if request_spec["receive"] != [
                    {"type": "http.request", "body_base64": "", "more_body": False}
                ]:
                    raise ValueError("SessionMiddleware HTTP requests use one empty body event")
            elif scope_type == "websocket":
                if request_spec["receive"] != [
                    {"type": "websocket.connect", "subprotocols": scope["subprotocols"]}
                ]:
                    raise ValueError(
                        "SessionMiddleware WebSocket requests use offered connect input"
                    )
            elif request_spec["receive"] != [
                {"type": "lifespan.startup"},
                {"type": "lifespan.shutdown"},
            ]:
                raise ValueError(
                    "SessionMiddleware lifespan pass-through requires startup then shutdown"
                )

            cookie_source = request_spec["cookie_source"]
            if cookie_source is not None:
                if scope_type not in {"http", "websocket"}:
                    raise ValueError(
                        "SessionMiddleware cookie sources require HTTP or WebSocket scopes"
                    )
                if not isinstance(cookie_source, dict) or not isinstance(
                    cookie_source.get("kind"), str
                ):
                    raise ValueError("SessionMiddleware cookie_source must be a tagged object")
                if cookie_source["kind"] == "raw-cookie":
                    _exact_object(cookie_source, {"kind", "value"}, "raw-cookie source")
                    cookie_value = cookie_source["value"]
                    if not isinstance(cookie_value, str):
                        raise ValueError("raw-cookie value must be a string")
                    cookie_header = cookie_value.encode("latin-1")
                elif cookie_source["kind"] == "previous-set-cookie":
                    _exact_object(
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
                if scope_type != "http":
                    raise ValueError(
                        "session view, clear, and no-access actions require HTTP scopes"
                    )
                action_keys = (
                    {"kind", "response_start"}
                    if action["kind"] == "view" and "response_start" in action
                    else {"kind"}
                )
                _exact_object(action, action_keys, "SessionMiddleware action")
                if "response_start" in action:
                    response_start = _exact_object(
                        action["response_start"],
                        {"headers_representation", "headers_base64_pairs"}
                        | (
                            {"type"}
                            if isinstance(action["response_start"], dict)
                            and "type" in action["response_start"]
                            else set()
                        ),
                        "SessionMiddleware response-start headers",
                    )
                    if response_start["headers_representation"] not in {"list", "tuple"}:
                        raise ValueError(
                            "SessionMiddleware response-start headers representation must be list or tuple"
                        )
                    if not isinstance(response_start["headers_base64_pairs"], list):
                        raise ValueError(
                            "SessionMiddleware response-start headers must be an array"
                        )
                    for pair in response_start["headers_base64_pairs"]:
                        if (
                            not isinstance(pair, list)
                            or len(pair) != 2
                            or any(not isinstance(part, str) for part in pair)
                        ):
                            raise ValueError(
                                "SessionMiddleware response-start headers must be base64 string pairs"
                            )
                        _decode_base64(pair[0], "SessionMiddleware response-start header name")
                        _decode_base64(pair[1], "SessionMiddleware response-start header value")
            elif action["kind"] == "update":
                if scope_type != "http":
                    raise ValueError("session update actions require HTTP scopes")
                _exact_object(action, {"kind", "values"}, "SessionMiddleware update action")
                if not isinstance(action["values"], dict):
                    raise ValueError("SessionMiddleware update values must be an object")
            elif action["kind"] == "session-mutation":
                _exact_object(
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
                _exact_object(mutation, mutation_keys, "SessionMiddleware mutation")
                if scope_type != "http":
                    raise ValueError("direct Session mutations require HTTP scopes")
            elif action["kind"] == "session-operation":
                if scope_type != "http":
                    raise ValueError("Session operations require HTTP scopes")
                _exact_object(
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
                _exact_object(
                    mutation,
                    mutation_keys,
                    "SessionMiddleware request Session operation",
                )
            elif action["kind"] == "websocket-view":
                if scope_type != "websocket":
                    raise ValueError("websocket-view actions require WebSocket scopes")
                _exact_object(
                    action,
                    {"kind", "accept", "close"},
                    "SessionMiddleware WebSocket view action",
                )
                accept = _exact_object(
                    action["accept"],
                    {"subprotocol", "headers_base64_pairs"},
                    "SessionMiddleware WebSocket accept action",
                )
                if accept["subprotocol"] is not None and (
                    not isinstance(accept["subprotocol"], str)
                    or accept["subprotocol"] not in scope["subprotocols"]
                ):
                    raise ValueError(
                        "WebSocket accept subprotocol must be null or offered by client"
                    )
                if not isinstance(accept["headers_base64_pairs"], list):
                    raise ValueError("WebSocket accept headers must be an array")
                for pair in accept["headers_base64_pairs"]:
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or any(not isinstance(part, str) for part in pair)
                    ):
                        raise ValueError("WebSocket accept headers must be base64 string pairs")
                    _decode_base64(pair[0], "WebSocket accept header name")
                    _decode_base64(pair[1], "WebSocket accept header value")
                close = _exact_object(
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
                if (
                    request_spec["cookie_source"] is None
                    or not isinstance(request_spec["cookie_source"], dict)
                    or request_spec["cookie_source"].get("kind") != "previous-set-cookie"
                ):
                    raise ValueError(
                        "SessionMiddleware WebSocket view requires a previous session cookie"
                    )
                previous_action = actions_by_id[request_spec["cookie_source"]["request_id"]]
                if previous_action["kind"] != "update" or not previous_action["values"]:
                    raise ValueError("WebSocket session cookie must follow a non-empty update")
            elif action["kind"] == "passthrough":
                if scope_type in ("http", "websocket"):
                    raise ValueError("passthrough actions require non-HTTP scopes")
                _exact_object(action, {"kind", "outbound"}, "SessionMiddleware passthrough action")
                if action["outbound"] != [
                    {"type": "lifespan.startup.complete"},
                    {"type": "lifespan.shutdown.complete"},
                ]:
                    raise ValueError("lifespan pass-through requires matching completion events")
            else:
                raise ValueError(f"unsupported SessionMiddleware action: {action['kind']!r}")

            incoming = [_make_message(message) for message in request_spec["receive"]]
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
            except Exception as exc:
                if current["error"] is None:
                    workflow_error = exc
                    current["error"] = _error_snapshot(exc)
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
            if workflow_error is not None:
                break
        return outputs

    value = {
        "secret_key_observation": secret_key_observation,
        "requests": asyncio.run(run_requests()),
    }
    observation = {"step_id": SESSION_WORKFLOW_OPERATION}
    if workflow_error is not None:
        observation.update(
            {
                "status": "error",
                "error": _dispatch_error(workflow_error),
                "partial_value": value,
            }
        )
    else:
        observation.update({"status": "ok", "value": value})
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [observation],
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
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_SERVICE_SURFACE,
        NATIVE_SERVICE_OPERATION,
    ):
        return _run_native_service_streaming_case(case)
    if (case.get("surface"), case.get("operation")) in {
        (NATIVE_SERVICE_SURFACE, NATIVE_MOUNTED_CHILD_OPERATION),
        (NATIVE_HOST_SERVICE_SURFACE, NATIVE_HOST_SERVICE_OPERATION),
    }:
        return _run_native_service_routing_case(case)
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_STREAM_SOURCE_SURFACE,
        NATIVE_STREAM_SOURCE_OPERATION,
    ):
        return _run_native_lazy_source_case(case)
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_ROUTE_TABLE_SURFACE,
        NATIVE_ROUTE_TABLE_CONVERTER_OPERATION,
    ):
        return _run_native_custom_converter_match_case(case)
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_NAMED_ROUTE_SURFACE,
        NATIVE_NAMED_ROUTE_CONVERTER_OPERATION,
    ):
        return _run_native_custom_converter_url_case(case)
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_WEBSOCKET_SURFACE,
        NATIVE_WEBSOCKET_OPERATION,
    ):
        return _run_native_websocket_case(case)
    if (case.get("surface"), case.get("operation")) == (
        NATIVE_LIFESPAN_SURFACE,
        NATIVE_LIFESPAN_OPERATION,
    ):
        return _run_native_lifespan_case(case)
    if (case.get("surface"), case.get("operation")) == ("starlette", "public-api-inspection"):
        from scripts.parity.adapters.public_api_inspection import run_public_api_inspection_case

        return run_public_api_inspection_case(case)
    if (case.get("surface"), case.get("operation")) in {
        ("starlette.convertors", "direct-method-calls"),
        ("starlette.convertors", "registry-sequence"),
    }:
        from scripts.parity.adapters.convertors import (
            run_convertor_direct_methods_case,
            run_convertor_registry_sequence_case,
        )

        if case["operation"] == "direct-method-calls":
            return run_convertor_direct_methods_case(case)
        return run_convertor_registry_sequence_case(case)
    if (case.get("surface"), case.get("operation")) in {
        ("starlette.applications.Starlette", "typing-consumer"),
        ("starlette.responses.Response", "typing-consumer"),
        ("starlette.config.Config", "typing-consumer"),
        ("starlette.templating.Jinja2Templates", "typing-consumer"),
        ("starlette.authentication", "typing-consumer"),
    }:
        from scripts.parity.adapters.application_typing import run_application_typing_case

        return run_application_typing_case(case)
    if (case.get("surface"), case.get("operation")) in {
        ("starlette.testclient.TestClient", "module-import-policy"),
        ("starlette.templating.Jinja2Templates", "module-import-policy"),
        ("starlette.middleware.sessions.SessionMiddleware", "module-import-policy"),
        ("starlette.requests.Request", "module-import-policy"),
        ("starlette.schemas.OpenAPIResponse", "module-import-policy"),
        ("starlette.schemas.BaseSchemaGenerator", "module-import-policy"),
        ("starlette.schemas.SchemaGenerator", "module-import-policy"),
    }:
        from scripts.parity.adapters.optional_imports import run_optional_import_case

        return run_optional_import_case(case)
    if (case.get("surface"), case.get("operation")) == (
        "starlette.middleware.exceptions.ExceptionMiddleware",
        "__init__",
    ):
        from scripts.parity.adapters.exception_middleware_typing import (
            run_exception_middleware_typing_case,
        )

        return run_exception_middleware_typing_case(case)
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
    if (
        case.get("surface") == "starlette.applications.Starlette"
        and case.get("operation") == "routes"
    ):
        from scripts.parity.adapters.starlette_oracle import (
            _run_application_routes_property_case,
        )

        return _run_application_routes_property_case(case)
    if (
        case.get("surface") == TESTCLIENT_SURFACE
        and case.get("operation") == "public-client-workflow"
    ):
        from scripts.parity.adapters.testclient_public import run_testclient_public_case

        return run_testclient_public_case(case)
    if case.get("surface") == TESTCLIENT_SURFACE and case.get("operation") in {
        TESTCLIENT_OPERATION,
        TESTCLIENT_WEBSOCKET_OPERATION,
        TESTCLIENT_LIFESPAN_OPERATION,
    }:
        from scripts.parity.adapters.testclient import (
            run_testclient_case,
            run_testclient_lifespan_case,
            run_testclient_websocket_case,
        )

        if case.get("operation") == TESTCLIENT_WEBSOCKET_OPERATION:
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
        and case.get("operation") == "template-public-workflow"
    ):
        from scripts.parity.adapters.templating import run_template_public_case

        return run_template_public_case(case)
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
        and (case.get("surface"), case.get("operation")) == REQUEST_HEADER_CACHE_SEQUENCE_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_header_cache_sequence import (
            run_request_header_cache_sequence_case,
        )

        return run_request_header_cache_sequence_case(case, Request)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_COOKIE_CACHE_SEQUENCE_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_cookie_cache_sequence import (
            run_request_cookie_cache_sequence_case,
        )

        return run_request_cookie_cache_sequence_case(case, Request)
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
        and (case.get("surface"), case.get("operation")) == REQUEST_BASE_URL_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_connection_properties import run_request_base_url_case

        return run_request_base_url_case(case, Request)
    if (case.get("surface"), case.get("operation")) == (
        "starlette.requests.Request",
        "connection-properties",
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_connection_properties import (
            run_request_connection_properties_case,
        )

        return run_request_connection_properties_case(case, Request)
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
        and (case.get("surface"), case.get("operation")) == REQUEST_STATE_READBACK_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_scope_mapping import (
            run_request_state_readback_case,
        )

        return run_request_state_readback_case(case, Request)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_CONSTRUCTOR_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_scope_mapping import run_request_constructor_case

        return run_request_constructor_case(case, Request)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == WEBSOCKET_SCOPE_MAPPING_OPERATION
    ):
        from starlette.websockets import WebSocket

        from scripts.parity.adapters.request_scope_mapping import run_websocket_scope_mapping_case

        return run_websocket_scope_mapping_case(case, WebSocket)
    if (
        isinstance(case, dict)
        and (
            case.get("surface"),
            case.get("operation"),
        )
        == REQUEST_IDENTITY_HASH_SEQUENCE_OPERATION
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_scope_mapping import (
            run_scope_identity_hash_sequence_case,
        )

        return run_scope_identity_hash_sequence_case(case, Request)
    if (
        isinstance(case, dict)
        and (
            case.get("surface"),
            case.get("operation"),
        )
        == WEBSOCKET_IDENTITY_HASH_SEQUENCE_OPERATION
    ):
        from starlette.websockets import WebSocket

        from scripts.parity.adapters.request_scope_mapping import (
            run_scope_identity_hash_sequence_case,
        )

        return run_scope_identity_hash_sequence_case(case, WebSocket)
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == WEBSOCKET_CONSTRUCTOR_OPERATION
    ):
        from starlette.websockets import WebSocket

        from scripts.parity.adapters.request_scope_mapping import run_websocket_constructor_case

        return run_websocket_constructor_case(case, WebSocket)
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
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation")) == REQUEST_FORM_OPERATION
    ):
        return _run_request_form_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.FormData",
        "close-lifecycle",
    ):
        from starlette.datastructures import FormData, UploadFile

        from scripts.parity.adapters.formdata import run_formdata_close_case

        return run_formdata_close_case(case, FormData, UploadFile)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.FormData",
        "multidict-lookups",
    ):
        from starlette.datastructures import FormData, UploadFile

        from scripts.parity.adapters.formdata import run_formdata_case

        return run_formdata_case(case, FormData, UploadFile)
    if (case.get("surface"), case.get("operation")) == (
        "starlette.background",
        "attribute-operations",
    ):
        from starlette import background

        from scripts.parity.adapters.background_attributes import run_background_attributes_case

        return run_background_attributes_case(case, background)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.UploadFile",
        "file-operations",
    ):
        from starlette.datastructures import UploadFile

        from scripts.parity.adapters.upload_file import run_upload_file_case

        return run_upload_file_case(case, UploadFile)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in {
        (f"starlette.responses.{name}", "consumer-construction")
        for name in (
            "Response",
            "HTMLResponse",
            "PlainTextResponse",
            "JSONResponse",
            "RedirectResponse",
            "StreamingResponse",
            "FileResponse",
        )
    }:
        from scripts.parity.adapters.response_consumer import run_response_consumer_case

        return run_response_consumer_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) in {
        ("starlette.datastructures.CommaSeparatedStrings", "ownership-graph"),
        ("starlette.datastructures.UploadFile", "ownership-graph"),
        ("starlette.datastructures.ImmutableMultiDict", "ownership-graph"),
        ("starlette.datastructures.FormData", "ownership-graph"),
        ("starlette.datastructures.Headers", "ownership-graph"),
        ("starlette.datastructures.MultiDict", "ownership-graph"),
        ("starlette.datastructures.MutableHeaders", "ownership-graph"),
        ("starlette.datastructures.State", "ownership-graph"),
        ("starlette.datastructures.URL", "ownership-graph"),
    }:
        from scripts.parity.adapters.value_lifetime import run_value_lifetime_case

        return run_value_lifetime_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.requests.Request",
        "callback-lifetime",
    ):
        from starlette.requests import Request

        from scripts.parity.adapters.request_lifetime import run_request_lifetime_case

        return run_request_lifetime_case(case, Request)
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
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.routing.Router",
        "registration-sequence",
    ):
        from starlette.routing import Router

        from scripts.parity.adapters.routing_registration import (
            run_router_registration_case,
        )

        return run_router_registration_case(case, Router)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        "starlette.datastructures.URLPath",
        "constructor-sequence",
    ):
        from starlette.datastructures import URLPath

        from scripts.parity.adapters.routing_registration import run_urlpath_constructor_case

        return run_urlpath_constructor_case(case, URLPath)
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
    if (
        isinstance(case, dict)
        and (case.get("surface"), case.get("operation"))
        == WEBSOCKET_DISCONNECT_CONSTRUCTOR_OPERATION
    ):
        return _run_websocket_disconnect_constructor_case(case)
    if isinstance(case, dict) and (case.get("surface"), case.get("operation")) == (
        HTTP_ROUTE_SURFACE,
        "__init__",
    ):
        return _run_route_endpoint_name_case(case)
    if isinstance(case, dict) and case.get("operation") in {"url_path_for", "url_for"}:
        return _run_reverse_url_case(case)
    if (
        isinstance(case, dict)
        and case.get("surface") in {WEBSOCKET_ROUTE_SURFACE, MOUNT_SURFACE, HOST_SURFACE}
        and case.get("operation") == "__init__"
    ):
        return _run_routing_constructor_case(case)
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
        and case.get("operation") == STATIC_FILES_GET_RESPONSE_OPERATION
    ):
        return _run_static_files_get_response_case(case)
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
    if case.get("surface") in {"starlette.routing.Router", "starlette.routing.Mount"}:
        if case.get("operation") != "route-dispatch":
            raise ValueError("Router and Mount cases must use route-dispatch")
        return _run_route_dispatch_case(case)
    if case.get("surface") in {CORS_SURFACE, HTTPS_REDIRECT_SURFACE, TRUSTED_HOST_SURFACE}:
        return _run_protocol_middleware_case(case)
    if case.get("surface") == SERVER_ERROR_MIDDLEWARE_SURFACE:
        return _run_server_error_middleware_case(case)
    if case.get("surface") == EXCEPTION_MIDDLEWARE_SURFACE and case.get("operation") == "__call__":
        return _run_exception_middleware_case(case)
    if case.get("surface") == WSGI_SURFACE:
        if case["operation"] != "__call__":
            raise ValueError("WSGIMiddleware cases must call its public ASGI interface")
        if "steps" not in case:
            from scripts.parity.adapters.wsgi_protocols import run_wsgi_protocol_case

            return _json_safe(run_wsgi_protocol_case(case))
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
        return _run_wsgi_case(case)
    if case.get("surface") in {
        "starlette.middleware.gzip.GZipMiddleware",
        "starlette.middleware.gzip.GZipResponder",
    }:
        expected_fields = {
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
        expected_fields.update(
            {"scope_container", "scope_observation", "assignments"} & case.keys()
        )
        _exact_object(
            case,
            expected_fields,
            "parity case",
        )
        if case["operation"] != "__call__":
            raise ValueError("GZip cases must call the declared ASGI interface")
        return _run_gzip_case(case)
    if case.get("surface") == BODY_LIMIT_SURFACE:
        expected_fields = {
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
        expected_fields.update(
            {"scope_container", "scope_observation", "scope_headers_container"} & case.keys()
        )
        _exact_object(
            case,
            expected_fields,
            "parity case",
        )
        if case["operation"] != "__call__":
            raise ValueError("RequestBodyLimitMiddleware cases must call its public ASGI interface")
        return _run_body_limit_case(case)
    steps = case["steps"]
    schedule = case["execution_schedule"]
    if len(steps) < 2 or steps[0]["step_id"] != "application":
        raise ValueError("target adapter requires the application-construction step first")
    step_ids = [step["step_id"] for step in steps]
    is_request_dispatch = case["operation"] == "request-dispatch"
    if "application_subclass" in case and (
        case["surface"] != "starlette.applications.Starlette"
        or case["operation"] != "__call__"
        or step_ids != ["application", "dispatch"]
        or schedule != ["dispatch"]
        or case["observations"] != ["dispatch"]
    ):
        raise ValueError("application_subclass is supported for one Starlette dispatch")
    route_specs = steps[0]["arguments"]["routes"]["value"]
    route_middleware_workflow = _routes_have_local_middleware(route_specs) or (
        _has_mounted_app_exception_route(route_specs)
    )
    if is_request_dispatch:
        route_spec = steps[0]["arguments"]["routes"]["value"][0]
        async_call_boundary = route_spec["endpoint"] == {"kind": "async-call-boundary-observer"}
        sync_cancellation_boundary = (
            isinstance(route_spec["endpoint"], dict)
            and route_spec["endpoint"].get("kind") == "sync-request-cancellation-observer"
        )
        if async_call_boundary:
            expected_schedule = ["dispatch", "cancel-server-task"]
        elif sync_cancellation_boundary:
            expected_schedule = [
                "dispatch",
                "cancel-server-task",
                "event-loop-checkpoint",
                "release-worker",
            ]
        else:
            expected_schedule = ["dispatch"]
        if [step["step_id"] for step in steps] != [
            "application",
            "dispatch",
        ] or schedule != expected_schedule:
            raise ValueError("request-dispatch target case must contain application then dispatch")
    elif route_middleware_workflow and step_ids != ["application", "dispatch"]:
        minimum_steps = 2 if _has_mounted_app_exception_route(route_specs) else 3
        if len(steps) < minimum_steps or schedule != step_ids[1:]:
            raise ValueError(
                "route middleware workflow must schedule its input dispatches in order"
            )
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
                or steps[0]["arguments"]["routes"]["value"][0]["kind"] != "http-route"
                or steps[0]["arguments"]["routes"]["value"][0]["endpoint"]["kind"]
                != "sync-plain-text-response"
                or steps[0]["arguments"]["routes"]["value"][0]["methods"] is not None
            )
        )
    ):
        raise ValueError("execution schedule does not match the ASGI workflow steps")
    elif step_ids not in (
        ["application", "lifecycle"],
        ["application", "lifecycle", "dispatch"],
        ["application", "dispatch"],
        ["application", "dispatch-get", "dispatch-head"],
    ):
        raise ValueError("target adapter received a workflow outside the declared ASGI slice")
    app_arguments = {name: item["value"] for name, item in steps[0]["arguments"].items()}
    invalid_exception_handler_class = _has_invalid_builtin_exception_handler_class(
        app_arguments["exception_handlers"]
    )
    route_specs = app_arguments["routes"]
    middleware_specs = app_arguments.get("middleware")
    middleware_iterator_subclass = isinstance(middleware_specs, list) and any(
        isinstance(middleware, dict) and middleware.get("kind") == "middleware-iterator-subclass"
        for middleware in middleware_specs
    )
    route_spec = route_specs[0] if route_specs else {}
    endpoint_spec = route_spec.get("endpoint") if isinstance(route_spec, dict) else None
    endpoint_kind = endpoint_spec.get("kind") if isinstance(endpoint_spec, dict) else None
    capture_dispatch_error = (
        is_request_dispatch
        or route_middleware_workflow
        or endpoint_kind
        in {
            "asgi-callable-action-sequence",
            "http-exception",
            "raise-runtime-error",
            "response-background-task-error",
        }
        or route_spec.get("kind") == "websocket-route"
        or invalid_exception_handler_class
        or middleware_iterator_subclass
    )
    (
        app,
        lifecycle_trace,
        request_observations,
        route_endpoint,
        sync_endpoint_states,
    ) = _materialize_application(
        app_arguments,
        application_subclass=case.get("application_subclass"),
    )

    async def run_steps() -> list[dict[str, Any]]:
        if schedule == ["lifespan.startup", "lifespan.shutdown"]:
            lifecycle_arguments = {
                name: item["value"] for name, item in steps[1]["arguments"].items()
            }
            value = await _invoke_lifespan_only(
                app,
                lifecycle_arguments,
                lifecycle_trace,
                scope_container=case.get("scope_container", "dict"),
                scope_observation=case.get("scope_observation"),
            )
            return [_workflow_observation("lifecycle", value)]
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
            if endpoint_kind == "sync-plain-text-response":
                for state in sync_endpoint_states:
                    with state["lock"]:
                        state["invocation_count"] = 0
                        state["observation"] = None
            value = await _invoke(
                app,
                arguments,
                lifecycle_trace,
                request_observations,
                route_endpoint,
                is_request_dispatch and step["operation"] == "request-dispatch",
                sync_endpoint_states=sync_endpoint_states,
                capture_dispatch_error=capture_dispatch_error,
                capture_dispatch_error_as_observation=(
                    _has_mounted_app_exception_route(route_specs)
                    or invalid_exception_handler_class
                    or middleware_iterator_subclass
                ),
                cancel_after_endpoint_entry=(
                    "cancel-server-task" in schedule and step["operation"] == "request-dispatch"
                ),
                cancellation_checkpoint=(
                    "event-loop-checkpoint" in schedule and step["operation"] == "request-dispatch"
                ),
                release_worker_after_cancel=(
                    "release-worker" in schedule and step["operation"] == "request-dispatch"
                ),
                scope_container=case.get("scope_container", "dict"),
                scope_observation=case.get("scope_observation"),
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
        diagnostic_checkpoint = None
        diagnostic_phase_setter = None
        diagnostic_cleanup = None
        verify_target_identity_after_serialization = False
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
            expected_tree_sha256 = os.environ["STARLETTE_PARITY_TARGET_TREE_SHA256"]
            identity_before = _identity(distribution)
            if identity_before["target_tree_sha256"] != expected_tree_sha256:
                raise RuntimeError("installed target package changed after environment preparation")
            result = _run_case(request["case"])
            if os.environ.get("STARLETTE_RS_COOKIE_LIFETIME_DIAGNOSTIC"):
                from scripts.parity.adapters.response_consumer import (
                    _clear_cookie_lifetime_diagnostic,
                    _record_cookie_lifetime_adapter_checkpoint,
                    _set_cookie_lifetime_phase,
                )

                diagnostic_cleanup = _clear_cookie_lifetime_diagnostic
                diagnostic_checkpoint = _record_cookie_lifetime_adapter_checkpoint
                diagnostic_phase_setter = _set_cookie_lifetime_phase
                diagnostic_checkpoint(request["case"], "after-case-dispatch-return")
            verify_target_identity_after_serialization = True
            output = {
                "schema": RESPONSE_SCHEMA,
                "mode": "workflow",
                "subject_id": SUBJECT_ID,
                "result": result,
            }
        else:
            raise ValueError("adapter request mode must be identity or workflow")
        if diagnostic_checkpoint is not None:
            diagnostic_checkpoint(request["case"], "before-json-encode")
            diagnostic_phase_setter(request["case"], "json-encode")
        encoded_output = json.dumps(output, separators=(",", ":"), allow_nan=False)
        if diagnostic_checkpoint is not None:
            diagnostic_checkpoint(request["case"], "after-json-encode")
        if verify_target_identity_after_serialization:
            if diagnostic_phase_setter is not None:
                diagnostic_phase_setter(request["case"], "target-identity-check")
            identity_after = _identity(distribution)
            if identity_after["target_tree_sha256"] != expected_tree_sha256:
                raise RuntimeError("installed target package changed during workflow execution")
            if diagnostic_phase_setter is not None:
                diagnostic_phase_setter(request["case"], "after-target-identity-check")
                diagnostic_checkpoint(request["case"], "after-target-identity-check")
            if diagnostic_cleanup is not None:
                diagnostic_cleanup(request["case"])
        sys.stdout.write(encoded_output + "\n")
        return 0
    except Exception as error:  # adapter failures are infrastructure errors in the parent runner
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
