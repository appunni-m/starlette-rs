"""Input-defined Starlette subclass hooks used by application workflows."""

from __future__ import annotations

import base64
from typing import Any

STARLETTE_ATTRIBUTE_READ_PLAN_KIND = "build-middleware-stack-observe-attribute-reads"


def _summarize_attribute_value(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return {"type": type(value).__name__, "length": len(value)}
    return {"type": type(value).__name__}


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

    if specification["kind"] == "build-middleware-stack-delegate-through-generator-coroutine":
        if set(specification) != {"kind"}:
            raise ValueError("generator-coroutine subclass input has unexpected fields")

        import types

        def build_middleware_stack(self: Any) -> Any:
            application = super(type(self), self).build_middleware_stack()

            @types.coroutine
            def wrapped_application(scope: Any, receive: Any, send: Any) -> Any:
                return (yield from application(scope, receive, send).__await__())

            return wrapped_application

        return type(
            "GeneratorCoroutineStarletteSubclass",
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

    if specification["kind"] == STARLETTE_ATTRIBUTE_READ_PLAN_KIND:
        if set(specification) != {"kind", "access_plan"}:
            raise ValueError("application attribute access subclass input has unexpected fields")
        if captured_application is None:
            raise ValueError("application attribute access requires a trace capture")
        raw_plan = specification["access_plan"]
        if not isinstance(raw_plan, list) or not raw_plan:
            raise ValueError("application attribute access plan must be a non-empty list")

        access_plan: dict[tuple[str, int], dict[str, Any]] = {}
        for index, raw_entry in enumerate(raw_plan):
            if not isinstance(raw_entry, dict):
                raise ValueError(f"application attribute access plan[{index}] must be an object")
            fields = {"attribute", "read_index"}
            if "return_value" in raw_entry:
                fields.add("return_value")
            if set(raw_entry) != fields:
                raise ValueError(
                    f"application attribute access plan[{index}] has unexpected fields"
                )
            attribute = raw_entry["attribute"]
            read_index = raw_entry["read_index"]
            if not isinstance(attribute, str) or not attribute:
                raise ValueError(
                    f"application attribute access plan[{index}].attribute must be text"
                )
            if type(read_index) is not int or read_index < 1:
                raise ValueError(
                    f"application attribute access plan[{index}].read_index must be positive"
                )
            if "return_value" in raw_entry and type(raw_entry["return_value"]) not in (
                type(None),
                bool,
                int,
                float,
                str,
            ):
                raise ValueError(
                    f"application attribute access plan[{index}].return_value must be scalar"
                )
            key = (attribute, read_index)
            if key in access_plan:
                raise ValueError("application attribute access plan repeats an attribute read")
            access_plan[key] = raw_entry

        observed_attributes = {attribute for attribute, _read_index in access_plan}
        access_counts: dict[str, int] = {}
        access_state = {"active": False}

        def observe_attribute(self: Any, attribute: str) -> Any:
            value = object.__getattribute__(self, attribute)
            if access_state["active"] and attribute in observed_attributes:
                read_index = access_counts.get(attribute, 0) + 1
                access_counts[attribute] = read_index
                plan_entry = access_plan.get((attribute, read_index))
                if plan_entry is not None and "return_value" in plan_entry:
                    value = plan_entry["return_value"]
                trace = captured_application.get("attribute_trace")
                if not isinstance(trace, list):
                    raise RuntimeError("application attribute access trace was not bound")
                trace.append(
                    {
                        "event": "starlette.application.attribute-read",
                        "attribute": attribute,
                        "read_index": read_index,
                        "value": _summarize_attribute_value(value),
                    }
                )
            return value

        def build_middleware_stack(self: Any) -> Any:
            access_state["active"] = True
            try:
                return super(type(self), self).build_middleware_stack()
            finally:
                access_state["active"] = False

        return type(
            "AttributeReadPlanStarletteSubclass",
            (base_type,),
            {
                "__getattribute__": observe_attribute,
                "build_middleware_stack": build_middleware_stack,
            },
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
