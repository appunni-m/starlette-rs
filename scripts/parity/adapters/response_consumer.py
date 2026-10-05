"""Input-defined response subclasses consumed through constructors and ASGI."""

from __future__ import annotations

import asyncio
import base64
import json
import math
from typing import Any


def _content(
    spec: dict[str, Any], trace: list[Any] | None = None, errors: list[Any] | None = None
) -> Any:
    if spec["kind"] in {"memoryview-layout", "bytes-subclass"}:
        from scripts.parity.adapters.response_construction import body_value

        return body_value(spec, [] if trace is None else trace, [] if errors is None else errors)
    if spec["kind"] == "bytes":
        return base64.b64decode(spec["value"], validate=True)
    if spec["kind"] == "memoryview":
        return memoryview(base64.b64decode(spec["value"], validate=True))
    if spec["kind"] == "mutable-memoryview":
        return memoryview(bytearray(base64.b64decode(spec["value"], validate=True)))
    if spec["kind"] == "float":
        return float(spec["value"])
    if spec["kind"] == "set":
        return set(spec["value"])
    return spec["value"]


def _observe(value: Any) -> Any:
    if isinstance(value, bytes | memoryview):
        data = value.tobytes() if isinstance(value, memoryview) else value
        return {"type": type(value).__name__, "base64": base64.b64encode(data).decode("ascii")}
    if isinstance(value, dict):
        return {key: _observe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_observe(item) for item in value]
    if isinstance(value, set):
        return {"type": "set", "items": sorted(value)}
    if isinstance(value, float) and not math.isfinite(value):
        return {"type": "float", "value": str(value)}
    return value


def run_response_consumer_case(case: dict[str, Any]) -> dict[str, Any]:
    if "ownership" in case:
        from scripts.parity.adapters.response_ownership import run_response_ownership_case

        return run_response_ownership_case(case)
    from starlette import responses

    spec = case["construction"]
    base = getattr(responses, case["surface"].removeprefix("starlette.responses."))
    trace: list[Any] = []
    events: list[Any] = []
    retained_messages: list[Any] = []
    callbacks = case.get("callbacks", {})
    callback_errors: list[BaseException] = []
    backgrounds: dict[str, Any] = {}
    render = spec["render"]
    injected_error = RuntimeError(render.get("message", ""))
    error_types = {
        "RuntimeError": RuntimeError,
        "OSError": OSError,
        "StopAsyncIteration": StopAsyncIteration,
        "CancelledError": asyncio.CancelledError,
    }
    send_error = (
        error_types[case["send_failure"].get("exception_class", "OSError")](
            case["send_failure"]["message"]
        )
        if case["send_failure"]
        else None
    )
    attributes = dict(spec["class_attributes"])
    attribute_probe = {"enabled": False}
    boundary = None
    if "construction_boundary" in case:
        from scripts.parity.adapters.response_construction import ConstructionProbe

        boundary = ConstructionProbe(case, trace, callback_errors)

    def get_attribute(self: Any, name: str) -> Any:
        if attribute_probe["enabled"] and name in callbacks["attribute_probe"]:
            trace.append({"event": "attribute-read", "name": name})
        return object.__getattribute__(self, name)

    if "attribute_probe" in callbacks:
        attributes["__getattribute__"] = get_attribute
    subclass_probe = None
    if "subclass_protocol" in case:
        from scripts.parity.adapters.response_attributes import AttributeProbe

        subclass_probe = AttributeProbe(case["subclass_protocol"], trace, callback_errors)
        attributes.update(subclass_probe.attributes(base))

    def render_content(self: Any, content: Any) -> Any:
        if boundary is not None:
            boundary.render_entry(self)
        trace.append({"event": "render", "content": _observe(content)})
        for name, value in render["mutations"].items():
            setattr(self, name, value)
        if render["kind"] == "raise":
            raise injected_error
        if render["kind"] == "constant":
            return _content(render["content"], trace, callback_errors)
        if render["kind"] == "json-serializer":
            return json.dumps(content, **render["options"]).encode(render["encoding"])
        return base.render(self, content)

    if render["kind"] != "default":
        attributes["render"] = render_content
    constructor = type("ConsumerResponse", (base,), attributes)
    if boundary is not None and boundary.spec["weakref_direct"]:
        constructor = base
    kwargs = dict(spec["kwargs"])
    if boundary is not None:
        kwargs = boundary.kwargs(kwargs)

    async def background() -> None:
        trace.append({"event": "background", "label": case["background_label"]})

    if case["background_label"] is not None:
        kwargs["background"] = background

    def make_background(definition: dict[str, Any]) -> Any:
        error = (
            error_types[definition.get("exception_class", "RuntimeError")](definition["failure"])
            if definition["failure"] is not None
            else None
        )
        if error is not None:
            callback_errors.append(error)

        async def replacement() -> None:
            trace.append({"event": "background", "label": definition["label"]})
            if error is not None:
                raise error

        return replacement

    for definition in callbacks.get("background_definitions", []):
        backgrounds[definition["label"]] = make_background(definition)
    outcome: dict[str, Any] = {
        "class_media_type": base.media_type,
        "class_charset": base.charset,
        "constructed": False,
        "trace": trace,
        "asgi_events": events,
        "error": None,
    }
    phase = "constructor"
    try:
        response = (
            constructor(**kwargs)
            if spec["omit_content"]
            else constructor(_content(spec["content"], trace, callback_errors), **kwargs)
        )
        outcome["constructed"] = True
        if subclass_probe is not None:
            phase = "header-actions"
            subclass_probe.actions(response)
            phase = "constructor-observations"
        if boundary is not None:
            outcome["construction_boundary"] = boundary.observe(response)
        outcome["after_constructor"] = {
            "status_code": response.status_code,
            "media_type": response.media_type,
            "charset": response.charset,
            "body": _observe(response.body),
            "raw_headers": _observe(response.raw_headers),
        }
        phase = "attributes"
        for name, value in case["post_init_attributes"].items():
            setattr(response, name, _content(value) if name == "body" else value)
        outcome["before_call"] = {
            "status_code": response.status_code,
            "body": _observe(response.body),
            "raw_headers": _observe(response.raw_headers),
        }
        phase = "asgi"

        async def receive() -> dict[str, Any]:
            trace.append({"event": "receive"})
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            retained_messages.append(message)
            events.append(_observe(message))
            if callbacks.get("inspect_aliases"):
                trace.append(
                    {
                        "event": "send-alias",
                        "event_number": len(events),
                        "headers_are_response_raw": (
                            message["headers"] is response.raw_headers
                            if "headers" in message
                            else None
                        ),
                        "body_is_response_body": (
                            message["body"] is response.body if "body" in message else None
                        ),
                    }
                )
            for action in callbacks.get("send_actions", []):
                if action["at_event"] != len(events):
                    continue
                if action["checkpoint"]:
                    await asyncio.sleep(0)
                trace.append({"event": "send-action", "kind": action["kind"]})
                if action["kind"] == "body":
                    response.body = _content(action["value"])
                elif action["kind"] == "background":
                    response.background = backgrounds.get(action["label"])
                elif action["kind"] == "status":
                    response.status_code = action["value"]
                elif action["kind"] == "raw-headers":
                    response.raw_headers = [
                        tuple(base64.b64decode(item) for item in pair) for pair in action["pairs"]
                    ]
                elif action["kind"] == "append-header":
                    response.raw_headers.append(
                        tuple(base64.b64decode(item) for item in action["pair"])
                    )
                elif action["kind"] == "mutable-body":
                    response.body[action["index"]] = action["value"]
            if case["send_failure"] and len(events) == case["send_failure"]["at_event"]:
                raise send_error

        attribute_probe["enabled"] = True
        asyncio.run(response(dict(case["scope"]), receive, send))
        outcome["completed"] = True
    except BaseException as error:
        outcome["completed"] = False
        outcome["error"] = {
            "phase": phase,
            "class": f"{type(error).__module__}.{type(error).__qualname__}",
            "message": str(error),
            "args": _observe(error.args),
            "is_user_error": (
                error is injected_error
                or error is send_error
                or any(error is item for item in callback_errors)
            ),
            "has_cause": error.__cause__ is not None,
            "has_context": error.__context__ is not None,
            "suppress_context": error.__suppress_context__,
        }
        if boundary is not None and boundary.spec["early_headers_read"] is not None:
            outcome["error"]["attribute_name"] = getattr(error, "name", None)
            outcome["error"]["attribute_owner"] = getattr(error, "obj", None) is boundary.response
        if subclass_probe is not None and isinstance(error, AttributeError):
            outcome["error"]["attribute_name"] = error.name
            owner = locals().get("response")
            outcome["error"]["attribute_owner"] = owner is not None and error.obj is owner
    attribute_probe["enabled"] = False
    if callbacks and outcome["constructed"]:
        outcome["retained_messages"] = _observe(retained_messages)
        outcome["after_call"] = {
            "status_code": response.status_code,
            "body": _observe(response.body),
            "raw_headers": _observe(response.raw_headers),
        }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "response-consumer",
                "status": "ok",
                "value": {"response-consumer": outcome},
            }
        ],
    }
