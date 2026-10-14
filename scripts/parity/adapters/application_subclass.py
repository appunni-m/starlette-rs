"""Input-defined Starlette subclass hooks used by application workflows."""

from __future__ import annotations

import base64
from typing import Any


def materialize_starlette_subclass(
    base_type: type[Any],
    specification: Any,
    captured_application: dict[str, Any] | None = None,
) -> type[Any]:
    """Build the input-defined subclass used to exercise Starlette extension hooks."""
    if not isinstance(specification, dict) or not isinstance(specification.get("kind"), str):
        raise ValueError("application_subclass must define its kind")
    if specification["kind"] == "capture-instance-during-construction":
        if set(specification) != {"kind", "observe_attributes"}:
            raise ValueError("constructor observation subclass input has unexpected fields")
        if captured_application is None:
            raise ValueError("constructor observation requires an application capture")

        def capture_instance(cls: type[Any], *_args: Any, **_kwargs: Any) -> Any:
            instance = object.__new__(cls)
            captured_application["application"] = instance
            return instance

        return type(
            "ConstructorObservationStarletteSubclass",
            (base_type,),
            {"__new__": capture_instance},
        )

    if specification["kind"] == "build-middleware-stack-set-user-middleware-tuple":
        if set(specification) != {"kind"}:
            raise ValueError("tuple user_middleware subclass input has unexpected fields")

        def build_middleware_stack(self: Any) -> Any:
            self.user_middleware = tuple(self.user_middleware)
            return super(type(self), self).build_middleware_stack()

        return type(
            "IterableMiddlewareStarletteSubclass",
            (base_type,),
            {"build_middleware_stack": build_middleware_stack},
        )

    if specification["kind"] == "build-middleware-stack-wrap-exception-handlers-userdict":
        if set(specification) != {"kind"}:
            raise ValueError("UserDict exception-handler subclass input has unexpected fields")

        def build_middleware_stack(self: Any) -> Any:
            from collections import UserDict

            self.exception_handlers = UserDict(self.exception_handlers)
            return super(type(self), self).build_middleware_stack()

        return type(
            "MappingExceptionHandlersStarletteSubclass",
            (base_type,),
            {"build_middleware_stack": build_middleware_stack},
        )

    if set(specification) != {"kind", "response_header_base64"}:
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
