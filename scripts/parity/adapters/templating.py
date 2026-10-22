"""Input-driven comparisons for Starlette's documented Jinja2 integration."""

from __future__ import annotations

import asyncio
import base64
import builtins
import importlib
import tempfile
import warnings
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


def _install_template_send_mutation(
    mutation: dict[str, str],
    mutation_trace: list[dict[str, str]],
    response_call_trace: list[dict[str, str]],
) -> tuple[type[Any], str, bool, Any]:
    module_name, class_name = mutation["target_class"].rsplit(".", 1)
    target_class = getattr(importlib.import_module(module_name), class_name)
    target_method = mutation["target_method"]
    previous = getattr(target_class, target_method)
    had_own_method = target_method in target_class.__dict__
    own_method = target_class.__dict__.get(target_method)

    async def record_and_forward(response: Any, scope: Any, receive: Any, send: Any) -> None:
        response_call_trace.append(
            {
                "target_class": mutation["target_class"],
                "target_method": target_method,
                "replacement": mutation["replacement"],
            }
        )
        await previous(response, scope, receive, send)

    setattr(target_class, target_method, record_and_forward)
    mutation_trace.append(dict(mutation))
    return target_class, target_method, had_own_method, own_method


def _install_template_render_mutation(
    mutation: dict[str, str],
    mutation_trace: list[dict[str, str]],
    constructor_trace: list[dict[str, str]],
) -> tuple[type[Any], str, bool, Any]:
    module_name, class_name = mutation["target_class"].rsplit(".", 1)
    target_class = getattr(importlib.import_module(module_name), class_name)
    target_method = mutation["target_method"]
    previous = getattr(target_class, target_method)
    had_own_method = target_method in target_class.__dict__
    own_method = target_class.__dict__.get(target_method)

    def record_and_forward(response: Any, *args: Any, **kwargs: Any) -> Any:
        constructor_trace.append(
            {
                "target_class": mutation["target_class"],
                "target_method": target_method,
                "replacement": mutation["replacement"],
            }
        )
        return previous(response, *args, **kwargs)

    setattr(target_class, target_method, record_and_forward)
    mutation_trace.append(dict(mutation))
    return target_class, target_method, had_own_method, own_method


class _InputTracingContext(dict[str, Any]):
    """Dictionary context whose input-selected method lookups are observable."""

    def __init__(
        self,
        initial: dict[str, Any],
        trace: list[dict[str, str]],
        watched_attributes: list[str],
    ) -> None:
        super().__init__(initial)
        self._trace = trace
        self._watched_attributes = set(watched_attributes)

    def __getattribute__(self, name: str) -> Any:
        if name not in {"_trace", "_watched_attributes"}:
            watched = object.__getattribute__(self, "_watched_attributes")
            if name in watched:
                object.__getattribute__(self, "_trace").append(
                    {"operation": "attribute-lookup", "name": name}
                )
        return object.__getattribute__(self, name)


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
    constructor_type = Jinja2Templates
    hooks = case.get("hooks")
    if hooks is not None:
        trace = []
        observed["hook_trace"] = trace
        hook_errors = {}
        for name in ("setup", "template"):
            definition = hooks[name]
            if definition["failure"] is not None:
                hook_errors[name] = RuntimeError(definition["failure"])

        class ConsumerTemplates(Jinja2Templates):
            def __getattribute__(self, name: str) -> Any:
                if name in hooks["get_watch"]:
                    trace.append({"operation": "get", "name": name})
                return object.__getattribute__(self, name)

            def __setattr__(self, name: str, value: Any) -> None:
                if name in hooks["set_watch"]:
                    trace.append({"operation": "set", "name": name})
                object.__setattr__(self, name, value)

            def _setup_env_defaults(self, env: Any) -> None:
                trace.append({"operation": "setup"})
                env.globals.update(hooks["setup"]["globals"])
                if hooks["setup"]["kind"] == "raise":
                    raise hook_errors["setup"]
                if hooks["setup"]["kind"] == "delegate":
                    super()._setup_env_defaults(env)

            def get_template(self, name: str) -> Any:
                trace.append({"operation": "template", "name": name})
                if hooks["template"]["kind"] == "raise":
                    raise hook_errors["template"]
                return super().get_template(name)

        constructor_type = ConsumerTemplates

    def sync_processor(additions: dict[str, Any]) -> Any:
        def processor(request: Any) -> dict[str, Any]:
            observed["processor_trace"].append(
                {"request_path": request.url.path, "additions": dict(additions)}
            )
            return dict(additions)

        return processor

    def async_processor(additions: dict[str, Any]) -> Any:
        async def processor(_request: Any) -> dict[str, Any]:
            return dict(additions)

        return processor

    def sync_raising_processor(exception_class: str, message: str) -> Any:
        exception_type = getattr(builtins, exception_class)

        def processor(request: Any) -> dict[str, Any]:
            observed["processor_trace"].append(
                {
                    "request_path": request.url.path,
                    "outcome": "raise",
                    "exception_class": f"{exception_type.__module__}.{exception_type.__qualname__}",
                    "exception_message": message,
                }
            )
            raise exception_type(message)

        return processor

    processor_factories = {
        "async": async_processor,
        "sync": sync_processor,
        "sync-raise": sync_raising_processor,
    }
    processor_specs = case.get("processor_specs")
    if processor_specs is None:
        processor_specs = [
            {"kind": "sync", "additions": additions} for additions in case["processor_additions"]
        ]
    processors = [
        (
            processor_factories[spec["kind"]](spec["exception_class"], spec["message"])
            if spec["kind"] == "sync-raise"
            else processor_factories[spec["kind"]](spec["additions"])
        )
        for spec in processor_specs
    ]

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
            custom_filters: dict[str, Any] = {}
            for filter_spec in environment.get("filters", []):
                prefix = filter_spec["prefix"]

                def prefix_filter(value: Any, filter_prefix: str = prefix) -> str:
                    return f"{filter_prefix}{value}"

                custom_filters[filter_spec["name"]] = prefix_filter
            supplied_environment = jinja2.Environment(
                loader=jinja2.FileSystemLoader(
                    [roots[item] for item in environment["directory_ids"]]
                ),
                autoescape=environment["autoescape"],
            )
            supplied_environment.filters.update(custom_filters)
            arguments["env"] = supplied_environment

        try:
            templates = constructor_type(**arguments)
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
                "custom_filter_names": sorted(
                    filter_spec["name"] for filter_spec in (environment or {}).get("filters", [])
                ),
            }
            consumer = case["consumer"]
            if consumer["kind"] == "template-render":
                for item in consumer["renders"]:
                    try:
                        template = templates.get_template(item["name"])
                        rendered = {
                            "template_name": template.name,
                            "rendered_text": template.render(dict(item["context"])),
                        }
                    except Exception as error:
                        rendered = {
                            "error": {
                                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                "message": str(error),
                                "is_hook_error": hooks is not None
                                and any(error is value for value in hook_errors.values()),
                            }
                        }
                    observed["rendered_templates"].append(rendered)
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
            event_offset = len(observed["asgi_events"])
            with warnings.catch_warnings(record=True) as request_warnings:
                warnings.simplefilter("always")
                try:
                    response = client.request(item["method"], item["url"])
                except Exception as error:
                    response_events = observed["asgi_events"][event_offset:]
                    response_start = next(
                        (
                            event
                            for event in response_events
                            if event["type"] == "http.response.start"
                        ),
                        None,
                    )
                    response_body = b"".join(
                        base64.b64decode(event["body"]["data"])
                        for event in response_events
                        if event["type"] == "http.response.body"
                    )
                    observed["responses"].append(
                        {
                            "url": item["url"],
                            "error": {
                                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                "message": str(error),
                            },
                            "warnings": [
                                {
                                    "category": warning.category.__name__,
                                    "message": str(warning.message),
                                }
                                for warning in request_warnings
                            ],
                            "response_status": (
                                None if response_start is None else response_start["status"]
                            ),
                            "response_bytes": base64.b64encode(response_body).decode("ascii"),
                            "asgi_event_order": [event["type"] for event in response_events],
                        }
                    )
                    continue
            response_context = response.context
            observed["responses"].append(
                {
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "response_bytes": base64.b64encode(response.content).decode("ascii"),
                    "warnings": [
                        {
                            "category": warning.category.__name__,
                            "message": str(warning.message),
                        }
                        for warning in request_warnings
                    ],
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
    active_context_order_trace: list[dict[str, Any]] | None = None
    processors = []
    for additions in case["processor_additions"]:

        def context_processor(
            active_request: Any, values: dict[str, Any] = additions
        ) -> dict[str, Any]:
            if active_context_order_trace is not None:
                active_context_order_trace.append(
                    {"operation": "processor-call", "request_path": str(active_request.url.path)}
                )
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
        send_mutations = case.get("send_mutations", [])
        render_mutations = case.get("render_mutations", [])

        for request_spec in case["requests"]:
            scope = _make_scope(request_spec["scope"])
            scope["router"] = router
            request = Request(scope)
            mutation_trace: list[dict[str, str]] = []
            response_call_trace: list[dict[str, str]] = []
            restorations: list[tuple[type[Any], str, bool, Any]] = []
            pending_mutations = set(range(len(send_mutations)))
            render_mutation_trace: list[dict[str, str]] = []
            constructor_trace: list[dict[str, str]] = []
            render_restorations: list[tuple[type[Any], str, bool, Any]] = []
            pending_render_mutations = set(range(len(render_mutations)))
            context_mapping = request_spec.get("context_mapping")
            if context_mapping is None:
                active_context_order_trace = None
                context_value = dict(request_spec["context"])
                context_order_trace: list[dict[str, Any]] = []
            else:
                context_order_trace = []
                active_context_order_trace = context_order_trace
                context_value = _InputTracingContext(
                    dict(request_spec["context"]),
                    context_order_trace,
                    context_mapping["trace_attribute_lookups"],
                )

            for mutation_index, mutation in enumerate(render_mutations):

                def install_during_render(
                    value: Any,
                    selected_index: int = mutation_index,
                    selected_mutation: dict[str, str] = mutation,
                    pending: set[int] = pending_render_mutations,
                    restorations_for_request: list[tuple[type[Any], str, bool, Any]] = (
                        render_restorations
                    ),
                    mutation_trace_for_request: list[dict[str, str]] = render_mutation_trace,
                    constructor_trace_for_request: list[dict[str, str]] = constructor_trace,
                ) -> Any:
                    if selected_index in pending:
                        restorations_for_request.append(
                            _install_template_render_mutation(
                                selected_mutation,
                                mutation_trace_for_request,
                                constructor_trace_for_request,
                            )
                        )
                        pending.remove(selected_index)
                    return value

                templates.env.filters[mutation["filter_name"]] = install_during_render

            try:
                response = templates.TemplateResponse(
                    request,
                    request_spec["template_name"],
                    context=context_value,
                    status_code=request_spec["status_code"],
                    headers=request_spec["headers"],
                    media_type=request_spec["media_type"],
                )
            finally:
                for (
                    target_class,
                    target_method,
                    had_own_method,
                    own_method,
                ) in reversed(render_restorations):
                    if had_own_method:
                        setattr(target_class, target_method, own_method)
                    else:
                        delattr(target_class, target_method)
            events: list[dict[str, Any]] = []
            send_failure_for_request = request_spec.get("send_failure")

            async def receive() -> dict[str, Any]:
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(
                message: dict[str, Any],
                event_target: list[dict[str, Any]] = events,
                pending_for_request: set[int] = pending_mutations,
                restorations_for_request: list[tuple[type[Any], str, bool, Any]] = restorations,
                mutation_trace_for_request: list[dict[str, str]] = mutation_trace,
                call_trace_for_request: list[dict[str, str]] = response_call_trace,
                send_failure_for_request: dict[str, Any] | None = send_failure_for_request,
            ) -> None:
                send_failure = send_failure_for_request
                if send_failure is not None and message.get("type") == send_failure["event_type"]:
                    exception_type = getattr(builtins, send_failure["exception_type"])
                    raise exception_type(send_failure["message"])
                for mutation_index in tuple(pending_for_request):
                    mutation = send_mutations[mutation_index]
                    if message.get("type") != mutation["trigger_type"]:
                        continue
                    restorations_for_request.append(
                        _install_template_send_mutation(
                            mutation,
                            mutation_trace_for_request,
                            call_trace_for_request,
                        )
                    )
                    pending_for_request.remove(mutation_index)
                event_target.append(message)

            response_error = None
            try:
                await response(scope, receive, send)
            except Exception as exc:
                response_error = {
                    "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "message": str(exc),
                }
            finally:
                for target_class, target_method, had_own_method, own_method in reversed(
                    restorations
                ):
                    if had_own_method:
                        setattr(target_class, target_method, own_method)
                    else:
                        delattr(target_class, target_method)
            response_events = [_template_event(event) for event in events]
            response_bodies = [
                event.get("body", b"") for event in events if event["type"] == "http.response.body"
            ]
            response_start = next(
                (event for event in events if event["type"] == "http.response.start"), None
            )
            response_value = {
                "request_path": request.url.path,
                "response_status": (
                    response_start["status"] if response_start is not None else None
                ),
                "ordered_repeated_headers": response_events[
                    next(
                        index
                        for index, event in enumerate(response_events)
                        if event["type"] == "http.response.start"
                    )
                ]["headers"]
                if response_start is not None
                else [],
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
            if response_error is not None:
                response_value["dispatch_error"] = response_error
            if render_mutations:
                response_value["render_mutation_trace"] = render_mutation_trace
                response_value["constructor_trace"] = constructor_trace
            if context_mapping is not None:
                response_value["context_mapping_trace"] = context_order_trace
            if send_mutations:
                response_value["send_mutation_trace"] = mutation_trace
                response_value["response_call_trace"] = response_call_trace
            response_values.append(response_value)
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
