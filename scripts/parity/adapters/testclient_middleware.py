"""Input-derived application and public TestClient middleware sequences."""

from __future__ import annotations

import base64
import builtins
import contextvars
import threading
from contextlib import asynccontextmanager, nullcontext
from typing import Any

try:
    _BASE_EXCEPTION_GROUP = builtins.BaseExceptionGroup
    _EXCEPTION_GROUP = builtins.ExceptionGroup
except AttributeError:
    from exceptiongroup import BaseExceptionGroup as _BASE_EXCEPTION_GROUP
    from exceptiongroup import ExceptionGroup as _EXCEPTION_GROUP


def _exception_snapshot(error: BaseException, seen: tuple[BaseException, ...] = ()) -> Any:
    identity = {
        "class": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
    }
    if any(error is item for item in seen):
        return {**identity, "cycle": True}
    visited = (*seen, error)

    def value(item: Any) -> Any:
        if isinstance(item, BaseException):
            return _exception_snapshot(item, visited)
        if isinstance(item, (tuple, list)):
            return [value(child) for child in item]
        return item

    return {
        **identity,
        "args": value(error.args),
        "cause": None if error.__cause__ is None else _exception_snapshot(error.__cause__, visited),
        "context": (
            None if error.__context__ is None else _exception_snapshot(error.__context__, visited)
        ),
        "suppress_context": error.__suppress_context__,
        "exceptions": (
            [_exception_snapshot(child, visited) for child in error.exceptions]
            if isinstance(error, _BASE_EXCEPTION_GROUP)
            else None
        ),
    }


def _safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def run_middleware_client_case(case: dict[str, Any]) -> dict[str, Any]:
    from scripts.parity.adapters.traceback_cleanup import TracebackCleanup

    specification = case["consumer"].get("exception_cleanup")
    if specification is not None:
        with TracebackCleanup(specification) as observer:
            return _run_middleware_client_case(case, observer)
    return _run_middleware_client_case(case, None)


def _run_middleware_client_case(case: dict[str, Any], lifetime: Any) -> dict[str, Any]:
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import PlainTextResponse, StreamingResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.testclient import TestClient

    application = case["application"]
    consumer = case["consumer"]
    trace: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    portal_threads: set[threading.Thread] = set()
    injected_error: BaseException | None = None
    worker_probe = application.get("worker_probe")
    worker_context = (
        contextvars.ContextVar("starlette-rs-parity-worker-context", default=None)
        if worker_probe is not None
        else None
    )

    def exception(specification: dict[str, Any]) -> BaseException:
        if specification["class"] == "ExceptionGroup":
            return _EXCEPTION_GROUP(
                specification["message"],
                [exception(child) for child in specification["exceptions"]],
            )
        return getattr(builtins, specification["class"])(*specification["args"])

    def endpoint(specification: dict[str, Any], path: str) -> Any:
        kind = specification["kind"]

        def record(path: str) -> None:
            trace.append({"operation": "endpoint", "kind": kind, "path": path})

        if kind == "text-response":

            def text_response(request: Any) -> Any:
                record(request.url.path)
                return PlainTextResponse(specification["text"])

            return text_response
        if kind == "sync-observation":

            def sync_observation(request: Any) -> Any:
                observed_context = None if worker_context is None else worker_context.get()
                trace.append(
                    {
                        "operation": "sync-worker-observation",
                        "path": request.url.path,
                        "thread": (
                            "portal" if threading.current_thread() in portal_threads else "worker"
                        ),
                        "context_value": observed_context,
                    }
                )
                return PlainTextResponse(specification["text"])

            return sync_observation
        if kind == "request-observation":

            async def request_observation(request: Any) -> Any:
                body = await request.body()
                trace.append(
                    {
                        "operation": "request-observation",
                        "url": str(request.url),
                        "path": request.url.path,
                        "query_items": request.query_params.multi_items(),
                        "header_items": request.headers.multi_items(),
                        "body_base64": base64.b64encode(body).decode("ascii"),
                    }
                )
                return PlainTextResponse("request-observed")

            return request_observation
        if kind == "exception":

            def raising_endpoint(request: Any) -> None:
                nonlocal injected_error
                # This user-owned local remains in the propagated traceback.
                _lifetime_guard = None if lifetime is None else lifetime.guard(path)
                record(request.url.path)
                injected_error = exception(specification["exception"])
                raise injected_error

            return raising_endpoint
        if kind == "faulty-sync-stream":

            def chunks() -> Any:
                nonlocal injected_error
                _lifetime_guard = None if lifetime is None else lifetime.guard(path)
                for chunk in specification["chunks_base64"]:
                    yield base64.b64decode(chunk, validate=True)
                injected_error = exception(specification["exception"])
                raise injected_error

            def stream_endpoint(request: Any) -> Any:
                record(request.url.path)
                return StreamingResponse(chunks())

            return stream_endpoint
        if kind == "awaitable-asgi-no-response":

            class NoResponse:
                def __init__(self, scope: Any, receive: Any, send: Any) -> None:
                    record(scope["path"])

                def __await__(self) -> Any:
                    return self.dispatch().__await__()

                async def dispatch(self) -> None:
                    pass

            return NoResponse

        async def websocket_endpoint(websocket: Any) -> None:
            record(websocket.url.path)
            await websocket.accept()
            await websocket.send_text(specification["text"])
            await websocket.close()

        return websocket_endpoint

    class HeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            trace.append({"operation": "dispatch", "path": request.url.path})
            token = None
            if worker_probe is not None and request.url.path == worker_probe["path"]:
                if worker_context is not None:
                    token = worker_context.set(worker_probe["context_value"])
            try:
                response = await call_next(request)
            finally:
                if token is not None:
                    worker_context.reset(token)
            for name, value in application["middleware"]["response_headers"].items():
                response.headers[name] = value
            trace.append({"operation": "response-headers", "path": request.url.path})
            return response

    routes = []
    for specification in application["routes"]:
        route_type = WebSocketRoute if specification["kind"] == "websocket-route" else Route
        routes.append(
            route_type(
                specification["path"],
                endpoint=endpoint(specification["endpoint"], specification["path"]),
                name=specification["name"],
            )
        )
    lifespan_specification = application.get("lifespan")
    if lifespan_specification is None:
        starlette = Starlette(routes=routes, middleware=[Middleware(HeaderMiddleware)])
    else:

        @asynccontextmanager
        async def lifespan_context(app: Any) -> Any:
            del app
            trace.append(
                {
                    "operation": "lifespan-startup",
                    "marker": lifespan_specification["startup_marker"],
                }
            )
            yield
            trace.append(
                {
                    "operation": "lifespan-shutdown",
                    "marker": lifespan_specification["shutdown_marker"],
                }
            )

        starlette = Starlette(
            routes=routes,
            middleware=[Middleware(HeaderMiddleware)],
            lifespan=lifespan_context,
        )

    async def app(scope: Any, receive: Any, send: Any) -> None:
        portal_threads.add(threading.current_thread())
        call_index = len(scopes)
        scopes.append({name: _safe(scope.get(name)) for name in application["scope_fields"]})

        async def observed_receive() -> Any:
            message = await receive()
            events.append(
                {"call_index": call_index, "direction": "receive", "message": _safe(message)}
            )
            return message

        async def observed_send(message: Any) -> None:
            events.append(
                {"call_index": call_index, "direction": "send", "message": _safe(message)}
            )
            await send(message)

        try:
            await starlette(scope, observed_receive, observed_send)
        finally:
            trace.append({"operation": "application-exit", "path": scope.get("path")})

    client = TestClient(app, **consumer["kwargs"])
    try:
        client_lifetime = client if lifespan_specification is not None else nullcontext(client)
        with client_lifetime:
            for step in consumer["steps"]:
                injected_error = None
                value: dict[str, Any] = {"kind": step["kind"], "response": None, "error": None}
                try:
                    if step["kind"] == "http-request":
                        request_kwargs = {}
                        if "headers" in step:
                            request_kwargs["headers"] = step["headers"]
                        if "content_base64" in step:
                            request_kwargs["content"] = base64.b64decode(
                                step["content_base64"], validate=True
                            )
                        response = client.request(step["method"], step["url"], **request_kwargs)
                        value["response"] = {
                            "status_code": response.status_code,
                            "headers": response.headers.multi_items(),
                            "content_base64": base64.b64encode(response.content).decode("ascii"),
                            "text": response.text,
                            "url": str(response.url),
                        }
                    else:
                        frames = []
                        with client.websocket_connect(step["url"]) as session:
                            for action in step["actions"]:
                                frames.append(getattr(session, action["method"])(*action["args"]))
                        value["response"] = {"frames": _safe(frames)}
                except Exception as error:
                    if lifetime is not None:
                        lifetime.capture(error)
                    value["error"] = _exception_snapshot(error)
                    value["is_injected_exception"] = (
                        None if injected_error is None else error is injected_error
                    )
                responses.append(value)
    finally:
        client.close()
    context = {
        "is_closed": client.is_closed,
        "portal_threads_alive_after_exit": [thread.is_alive() for thread in portal_threads],
    }
    if lifetime is not None:
        context["exception_cleanup"] = lifetime.cleanup()
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": case["operation"],
                "status": "ok",
                "value": {
                    "samples": [],
                    "application_trace": trace,
                    "context": context,
                    "responses": responses,
                    "asgi_scopes": scopes,
                    "asgi_events": events,
                },
            }
        ],
    }
