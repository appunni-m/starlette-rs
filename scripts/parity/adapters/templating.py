"""Input-driven comparisons for Starlette's documented Jinja2 integration."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any


def _template_event(message: dict[str, Any]) -> dict[str, Any]:
    if message["type"] == "http.response.debug":
        info = message["info"]
        context = info["context"]
        template = info["template"]
        return {
            "type": "http.response.debug",
            "template_name": template.name,
            "context_keys": sorted(context),
        }
    kind = message["type"]
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
        return {
            "type": kind,
            "body": {
                "encoding": "base64",
                "data": base64.b64encode(message.get("body", b"")).decode("ascii"),
            },
            "more_body": message.get("more_body", False),
        }
    raise ValueError(f"unsupported template response event: {kind!r}")


def run_template_response_case(case: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_run_template_response_case(case))


def _make_scope(spec: dict[str, Any]) -> dict[str, Any]:
    scope = {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": base64.b64decode(spec["raw_path_base64"], validate=True),
        "query_string": base64.b64decode(spec["query_string_base64"], validate=True),
        "root_path": spec["root_path"],
        "headers": [
            (base64.b64decode(name, validate=True), base64.b64decode(value, validate=True))
            for name, value in spec["headers_base64_pairs"]
        ],
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
        "method": spec["method"],
    }
    if "extensions" in spec:
        scope["extensions"] = dict(spec["extensions"])
    return scope


async def _run_template_response_case(case: dict[str, Any]) -> dict[str, Any]:
    from starlette.requests import Request
    from starlette.routing import Route, Router
    from starlette.templating import Jinja2Templates

    router = Router(
        routes=[
            Route(route["path"], lambda _request: None, name=route["name"])
            for route in case["routes"]
        ]
    )
    processor_trace: list[dict[str, Any]] = []
    processors = []
    for additions in case["processor_additions"]:

        def context_processor(
            active_request: Any, values: dict[str, Any] = additions
        ) -> dict[str, Any]:
            processor_trace.append(
                {
                    "request_path": str(active_request.url.path),
                    "added_keys": sorted(values),
                }
            )
            return dict(values)

        processors.append(context_processor)

    with tempfile.TemporaryDirectory(prefix="starlette-template-parity-") as temporary:
        directory_roots = {
            directory["id"]: Path(temporary) / directory["path"]
            for directory in case["template_directories"]
        }
        for directory in directory_roots.values():
            directory.mkdir(parents=True, exist_ok=True)
        for source in case["template_files"]:
            path = directory_roots[source["directory_id"]] / source["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source["text"], encoding="utf-8")

        templates = Jinja2Templates(
            directory=[
                directory_roots[directory["id"]] for directory in case["template_directories"]
            ],
            context_processors=processors,
        )
        response_values: list[dict[str, Any]] = []

        for request_spec in case["requests"]:
            scope = _make_scope(request_spec["scope"])
            scope["router"] = router
            request = Request(scope)
            response = templates.TemplateResponse(
                request,
                request_spec["template_name"],
                context=dict(request_spec["context"]),
                status_code=request_spec["status_code"],
                headers=request_spec["headers"],
                media_type=request_spec["media_type"],
            )
            events: list[dict[str, Any]] = []

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(
                message: dict[str, Any], event_target: list[dict[str, Any]] = events
            ) -> None:
                event_target.append(message)

            await response(scope, receive, send)
            response_events = [_template_event(event) for event in events]
            response_bodies = [
                event.get("body", b"") for event in events if event["type"] == "http.response.body"
            ]
            response_start = next(
                event for event in events if event["type"] == "http.response.start"
            )
            response_values.append(
                {
                    "request_path": request.url.path,
                    "response_status": response_start["status"],
                    "ordered_repeated_headers": response_events[
                        next(
                            index
                            for index, event in enumerate(response_events)
                            if event["type"] == "http.response.start"
                        )
                    ]["headers"],
                    "response_bytes": {
                        "encoding": "base64",
                        "data": base64.b64encode(b"".join(response_bodies)).decode("ascii"),
                    },
                    "asgi_event_order": [event["type"] for event in response_events],
                    "asgi_events": response_events,
                    "template_name": response.template.name,
                    "template_context_keys": sorted(response.context),
                    "request_attached": response.context["request"] is request,
                }
            )
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "template-response",
                "status": "ok",
                "value": {
                    "responses": response_values,
                    "processor_trace": processor_trace,
                },
            }
        ],
    }
