"""Input-defined response subclasses consumed through constructors and ASGI."""

from __future__ import annotations

import asyncio
import base64
import json
import math
from typing import Any


def _content(spec: dict[str, Any]) -> Any:
    if spec["kind"] == "bytes":
        return base64.b64decode(spec["value"], validate=True)
    if spec["kind"] == "memoryview":
        return memoryview(base64.b64decode(spec["value"], validate=True))
    if spec["kind"] == "float":
        return float(spec["value"])
    if spec["kind"] == "set":
        return set(spec["value"])
    return spec["value"]


def _observe(value: Any) -> Any:
    if isinstance(value, bytes | memoryview):
        return {"type": type(value).__name__, "base64": base64.b64encode(value).decode("ascii")}
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
    from starlette import responses

    spec = case["construction"]
    base = getattr(responses, case["surface"].removeprefix("starlette.responses."))
    trace: list[Any] = []
    events: list[Any] = []
    render = spec["render"]
    injected_error = RuntimeError(render.get("message", ""))
    send_error = OSError(case["send_failure"]["message"]) if case["send_failure"] else None
    attributes = dict(spec["class_attributes"])

    def render_content(self: Any, content: Any) -> Any:
        trace.append({"event": "render", "content": _observe(content)})
        for name, value in render["mutations"].items():
            setattr(self, name, value)
        if render["kind"] == "raise":
            raise injected_error
        if render["kind"] == "constant":
            return _content(render["content"])
        if render["kind"] == "json-serializer":
            return json.dumps(content, **render["options"]).encode(render["encoding"])
        return base.render(self, content)

    if render["kind"] != "default":
        attributes["render"] = render_content
    constructor = type("ConsumerResponse", (base,), attributes)
    kwargs = dict(spec["kwargs"])

    async def background() -> None:
        trace.append({"event": "background", "label": case["background_label"]})

    if case["background_label"] is not None:
        kwargs["background"] = background
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
            else constructor(_content(spec["content"]), **kwargs)
        )
        outcome["constructed"] = True
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
            events.append(_observe(message))
            if case["send_failure"] and len(events) == case["send_failure"]["at_event"]:
                raise send_error

        asyncio.run(response(dict(case["scope"]), receive, send))
        outcome["completed"] = True
    except Exception as error:
        outcome["completed"] = False
        outcome["error"] = {
            "phase": phase,
            "class": f"{type(error).__module__}.{type(error).__qualname__}",
            "message": str(error),
            "args": _observe(error.args),
            "is_user_error": error is injected_error or error is send_error,
            "has_cause": error.__cause__ is not None,
            "has_context": error.__context__ is not None,
            "suppress_context": error.__suppress_context__,
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
