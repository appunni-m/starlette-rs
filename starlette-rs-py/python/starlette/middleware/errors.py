"""Rust-backed server-error middleware with a narrow Python exception bridge."""

from __future__ import annotations

import inspect
import sys
import traceback
from collections.abc import Callable
from typing import Any

from starlette_rs_py import _core

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import _is_async_callable


class ServerErrorMiddleware:
    """Render Rust-selected 500 responses and re-raise application exceptions."""

    def __init__(
        self,
        app: Callable[..., Any],
        handler: Callable[..., Any] | None = None,
        debug: bool = False,
    ) -> None:
        self.app = app
        self.handler = handler
        self.debug = debug
        self.exception_handlers: list[Callable[..., Any]] = []
        self.policy = _core.ServerErrorPolicy(debug)
        if handler is not None:
            self.exception_handlers.append(handler)
            self.policy.register_handler(0)

    @classmethod
    def _from_rust_policy(
        cls,
        app: Callable[..., Any],
        exception_handlers: list[Callable[..., Any]],
        policy: Any,
    ) -> ServerErrorMiddleware:
        """Build the app wrapper from Rust's policy and shared callback registry."""
        middleware = cls.__new__(cls)
        middleware.app = app
        middleware.handler = None
        middleware.debug = False
        middleware.exception_handlers = exception_handlers
        middleware.policy = policy
        return middleware

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = _core.ServerErrorState()

        async def send_with_response_state(message: dict[str, Any]) -> None:
            state.observe_send(message)
            await send(message)

        try:
            await self.app(scope, receive, send_with_response_state)
        except Exception as exc:
            request = Request(scope)
            plan_name, handler_index = self.policy.plan(request.headers.get("accept"))

            if plan_name == "default":
                response = Response._from_native(_core._server_error_response())
            elif plan_name == "custom-handler":
                if handler_index is None:
                    raise RuntimeError(
                        "Rust selected a custom error handler without an index"
                    ) from exc
                handler = self.exception_handlers[handler_index]
                if _is_async_callable(handler):
                    response = await handler(request, exc)
                else:
                    response = await run_in_threadpool(handler, request, exc)
            elif plan_name == "debug-text":
                traceback_text = _debug_traceback_text(exc)
                response = Response._from_native(
                    _core._debug_traceback_text_response(traceback_text)
                )
            elif plan_name == "debug-html":
                exception_type, exception_message, frames = _debug_traceback_html_inputs(exc)
                response = Response._from_native(
                    _core._debug_traceback_html_response(
                        exception_type,
                        exception_message,
                        frames,
                    )
                )
            else:
                raise RuntimeError(
                    f"Rust returned an unknown server-error plan: {plan_name!r}"
                ) from exc

            if state.should_send_response():
                await response(scope, receive, send)

            # Server errors are reported to the server even after a 500 response
            # has been sent, or when an earlier response makes it undeliverable.
            raise exc


def _debug_traceback_text(exc: Exception) -> str:
    """Format the plain traceback using CPython's exception formatter."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _debug_traceback_html_inputs(
    exc: Exception,
) -> tuple[str, str, list[tuple[str, int, str, list[str], int]]]:
    """Bridge CPython HTML traceback data into Rust's renderer."""
    traceback_exception = traceback.TracebackException.from_exception(exc, capture_locals=True)
    if sys.version_info >= (3, 13):
        exception_type = traceback_exception.exc_type_str
    else:
        exception_type = traceback_exception.exc_type.__name__
    exception_display = str(traceback_exception)

    frames: list[tuple[str, int, str, list[str], int]] = []
    if exc.__traceback__ is not None:
        # The second positional argument in Starlette's inspect.getinnerframes
        # call is context lines per frame, not a frame limit.
        for frame in inspect.getinnerframes(exc.__traceback__, context=7):
            source_lines = list(frame.code_context or ())
            center_index = frame.index if frame.index is not None else 0
            frames.append(
                (
                    frame.filename,
                    frame.lineno,
                    frame.function,
                    source_lines,
                    center_index,
                )
            )

    return exception_type, exception_display, frames
