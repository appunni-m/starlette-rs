"""Input-defined Starlette subclass hooks used by application workflows."""

from __future__ import annotations

import base64
from typing import Any


def materialize_starlette_subclass(base_type: type[Any], specification: Any) -> type[Any]:
    """Build the input-defined subclass used to exercise Starlette extension hooks."""
    if not isinstance(specification, dict) or set(specification) != {
        "kind",
        "response_header_base64",
    }:
        raise ValueError("application_subclass must define its kind and response header")
    if specification["kind"] != "build-middleware-stack-delegate-and-append-header":
        raise ValueError("application_subclass.kind is unsupported")
    header = specification["response_header_base64"]
    if (
        not isinstance(header, list)
        or len(header) != 2
        or any(not isinstance(part, str) for part in header)
    ):
        raise ValueError("application_subclass response header must be a base64 pair")
    try:
        response_header = tuple(base64.b64decode(part, validate=True) for part in header)
    except (ValueError, TypeError) as exc:
        raise ValueError("application_subclass response header contains invalid base64") from exc
    if not response_header[0] or not response_header[1]:
        raise ValueError("application_subclass response header entries must be non-empty")

    def build_middleware_stack(self: Any) -> Any:
        application = super(type(self), self).build_middleware_stack()

        async def wrapped_application(scope: Any, receive: Any, send: Any) -> None:
            async def append_header(message: Any) -> None:
                if message.get("type") == "http.response.start":
                    message = dict(message)
                    message["headers"] = [*message.get("headers", ()), response_header]
                await send(message)

            await application(scope, receive, append_header)

        return wrapped_application

    return type(
        "InputStarletteSubclass",
        (base_type,),
        {"build_middleware_stack": build_middleware_stack},
    )
