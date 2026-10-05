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


def run_template_public_case(case: dict[str, Any]) -> dict[str, Any]:
    """Exercise construction, direct rendering, or routed TestClient consumers."""
    import jinja2
    from starlette.templating import Jinja2Templates

    observed: dict[str, Any] = {
        "construction": None,
        "environment": None,
        "rendered_templates": [],
        "responses": [],
        "processor_trace": [],
        "middleware_trace": [],
        "asgi_events": [],
    }
    processors = []
    for additions in case["processor_additions"]:

        def processor(request: Any, values: dict[str, Any] = additions) -> dict[str, Any]:
            observed["processor_trace"].append(
                {"request_path": request.url.path, "additions": dict(values)}
            )
            return dict(values)

        processors.append(processor)

    with tempfile.TemporaryDirectory(prefix="starlette-template-public-parity-") as temporary:
        roots = {
            item["id"]: Path(temporary) / item["path"] for item in case["template_directories"]
        }
        for root in roots.values():
            root.mkdir(parents=True, exist_ok=True)
        for item in case["template_files"]:
            path = roots[item["directory_id"]] / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["text"], encoding="utf-8")

        constructor = case["constructor"]
        arguments: dict[str, Any] = {"context_processors": processors}
        directory = constructor["directory"]
        if directory is not None:
            selected_roots = [roots[item] for item in directory["directory_ids"]]
            if directory["kind"] == "sequence":
                arguments["directory"] = selected_roots
            elif directory["kind"] == "path":
                arguments["directory"] = selected_roots[0]
            else:
                arguments["directory"] = str(selected_roots[0])
        environment = constructor["environment"]
        supplied_environment = None
        if environment is not None:
            supplied_environment = jinja2.Environment(
                loader=jinja2.FileSystemLoader(
                    [roots[item] for item in environment["directory_ids"]]
                ),
                autoescape=environment["autoescape"],
            )
            arguments["env"] = supplied_environment

        try:
            templates = Jinja2Templates(**arguments)
        except Exception as exc:
            observed["construction"] = {
                "outcome": "error",
                "error": {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                },
            }
        else:
            observed["construction"] = {"outcome": "returned"}
            observed["environment"] = {
                "supplied_identity": supplied_environment is not None
                and templates.env is supplied_environment,
                "url_for_global_present": "url_for" in templates.env.globals,
                "autoescape_by_template": {
                    item["path"]: (
                        templates.env.autoescape(item["path"])
                        if callable(templates.env.autoescape)
                        else templates.env.autoescape
                    )
                    for item in case["template_files"]
                },
            }
            consumer = case["consumer"]
            if consumer["kind"] == "template-render":
                for item in consumer["renders"]:
                    template = templates.get_template(item["name"])
                    observed["rendered_templates"].append(
                        {
                            "template_name": template.name,
                            "rendered_text": template.render(dict(item["context"])),
                        }
                    )
            elif consumer["kind"] == "testclient":
                _run_template_client(templates, consumer, observed)

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "template-public-workflow", "status": "ok", "value": observed}
        ],
    }


def _run_template_client(
    templates: Any,
    consumer: dict[str, Any],
    observed: dict[str, Any],
) -> None:
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.routing import Route
    from starlette.testclient import TestClient

    def endpoint_for(spec: dict[str, Any]) -> Any:
        async def endpoint(request: Any) -> Any:
            return templates.TemplateResponse(
                request, spec["template_name"], context=dict(spec["context"])
            )

        return endpoint

    class PassThroughMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            observed["middleware_trace"].append(
                {"stage": "dispatch-enter", "request_path": request.url.path}
            )
            response = await call_next(request)
            observed["middleware_trace"].append(
                {"stage": "response-return", "status_code": response.status_code}
            )
            return response

    route_app = Starlette(
        debug=consumer["debug"],
        routes=[
            Route(spec["path"], endpoint_for(spec), name=spec["name"])
            for spec in consumer["routes"]
        ],
        middleware=[Middleware(PassThroughMiddleware) for _ in consumer["middleware"]],
    )

    async def app(scope: Any, receive: Any, send: Any) -> None:
        async def observed_send(message: dict[str, Any]) -> None:
            observed["asgi_events"].append(_template_event(message))
            await send(message)

        await route_app(scope, receive, observed_send)

    client = TestClient(app)
    try:
        for item in consumer["requests"]:
            response = client.request(item["method"], item["url"])
            response_context = response.context
            observed["responses"].append(
                {
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "response_bytes": base64.b64encode(response.content).decode("ascii"),
                    "template_name": response.template.name,
                    "context_keys": sorted(response_context),
                    "request_path": response_context["request"].url.path,
                    "context_values": {
                        key: value for key, value in response_context.items() if key != "request"
                    },
                }
            )
    finally:
        client.close()


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
