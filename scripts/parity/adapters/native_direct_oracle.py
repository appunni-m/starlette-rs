"""Pinned Starlette public analogues for the Rust-native direct-operation lane."""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from urllib.parse import urlsplit

NATIVE_DIRECT_OPERATIONS = {
    ("starlette-rs.FormData", "parse-urlencoded"),
    ("starlette-rs.Connection", "build-url"),
    ("starlette-rs.HostPattern", "match-format"),
    ("starlette-rs.NamedRouteTable", "url-path-for"),
    ("starlette-rs.LifespanState", "transition-sequence"),
    ("starlette-rs.RouteTable", "dispatch-plan"),
    ("starlette-rs.Response", "call-state-sequence"),
}


def run_native_direct_case(case: dict[str, Any]) -> dict[str, Any]:
    _validate_case(case)
    surface = case["surface"]
    operation = case["operation"]
    input_value = case["input"]

    if (surface, operation) == ("starlette-rs.FormData", "parse-urlencoded"):
        record = _form_data(input_value)
    elif (surface, operation) == ("starlette-rs.Connection", "build-url"):
        record = _connection_url(input_value)
    elif (surface, operation) == ("starlette-rs.HostPattern", "match-format"):
        record = _host_pattern(input_value)
    elif (surface, operation) == ("starlette-rs.NamedRouteTable", "url-path-for"):
        record = _named_route_table(input_value)
    elif (surface, operation) == ("starlette-rs.RouteTable", "dispatch-plan"):
        record = _route_dispatch(input_value)
    elif (surface, operation) == ("starlette-rs.Response", "call-state-sequence"):
        record = _response_call(input_value)
    else:
        return _unsupported(
            case,
            "LifespanState transition phases are Rust-native host coordination state; "
            "pinned Starlette exposes lifecycle behavior only through its ASGI lifespan app.",
        )

    if isinstance(record, _Unsupported):
        return _unsupported(case, record.reason)
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "workflow",
                "status": "ok",
                "value": {"workflow": record},
            }
        ],
    }


class _Unsupported(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _validate_case(case: dict[str, Any]) -> None:
    required = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "input",
        "observations",
    }
    if set(case) != required:
        raise ValueError("native direct oracle case has missing or unknown fields")
    if (case["surface"], case["operation"]) not in NATIVE_DIRECT_OPERATIONS:
        raise ValueError("case is outside the native direct operation set")
    if case["observations"] != ["workflow"]:
        raise ValueError("native direct oracle case must select the workflow observation")
    if case["assets"] != [] or not isinstance(case["input"], dict):
        raise ValueError("native direct oracle case requires empty assets and record input")


def _unsupported(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "unsupported",
        "observations": [
            {"step_id": step_id, "status": "unsupported", "reason": reason}
            for step_id in case["observations"]
        ],
    }


def _decode_base64(value: Any, context: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a string")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError(f"{context} is not valid base64") from exc


def _strict_object(value: Any, fields: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{context} has missing or unknown fields")
    return value


def _string_pairs(value: Any, context: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    pairs: list[tuple[str, str]] = []
    for index, pair in enumerate(value):
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(item, str) for item in pair)
        ):
            raise ValueError(f"{context}[{index}] must contain two strings")
        pairs.append((pair[0], pair[1]))
    return pairs


def _form_data(input_value: dict[str, Any]) -> dict[str, Any]:
    from starlette.requests import Request

    input_spec = _strict_object(
        input_value,
        {"body_base64", "max_fields", "max_part_size", "lookup_keys"},
        "FormData input",
    )
    body = _decode_base64(input_spec["body_base64"], "FormData input.body_base64")
    max_fields = input_spec["max_fields"]
    max_part_size = input_spec["max_part_size"]
    lookup_keys = input_spec["lookup_keys"]
    if (
        type(max_fields) not in (int, float)
        or type(max_part_size) is not int
        or not isinstance(lookup_keys, list)
        or any(not isinstance(key, str) for key in lookup_keys)
    ):
        raise ValueError("FormData limits or lookup_keys have invalid types")

    scope = _http_scope("POST", "/")
    scope["headers"] = [(b"content-type", b"application/x-www-form-urlencoded")]
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def parse() -> dict[str, Any]:
        request = Request(scope, receive)
        try:
            form = await request.form(
                max_fields=max_fields,
                max_part_size=max_part_size,
            )
        except Exception:
            return {"result.status": "error"}

        return {
            "result.status": "ok",
            "multi_items": form.multi_items(),
            "keys": list(form.keys()),
            "values": list(form.values()),
            "items": list(form.items()),
            "length": len(form),
            "is_empty": not bool(form),
            "lookups": [
                {"key": key, "value": form.get(key), "values": form.getlist(key)}
                for key in lookup_keys
            ],
        }

    return asyncio.run(parse())


def _connection_url(input_value: dict[str, Any]) -> dict[str, Any] | _Unsupported:
    from starlette.datastructures import URL

    input_spec = _strict_object(
        input_value,
        {"scheme", "path", "query_base64", "headers_base64_pairs", "server"},
        "Connection input",
    )
    scheme = input_spec["scheme"]
    path = input_spec["path"]
    if not isinstance(path, str):
        raise ValueError("Connection input.path must be a string")
    query = _decode_base64(input_spec["query_base64"], "Connection input.query_base64")
    raw_headers = input_spec["headers_base64_pairs"]
    if not isinstance(raw_headers, list):
        raise ValueError("Connection input.headers_base64_pairs must be an array")
    headers: list[tuple[bytes, bytes]] = []
    for index, pair in enumerate(raw_headers):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Connection input.headers_base64_pairs[{index}] is invalid")
        headers.append(
            (
                _decode_base64(pair[0], f"Connection header name[{index}]"),
                _decode_base64(pair[1], f"Connection header value[{index}]"),
            )
        )
    server_value = input_spec["server"]
    server = None
    if server_value is not None:
        server_spec = _strict_object(server_value, {"host", "port_text"}, "Connection server")
        host = server_spec["host"]
        port_text = server_spec["port_text"]
        if (
            not isinstance(host, str)
            or not isinstance(port_text, str)
            or not port_text.isdecimal()
            or str(int(port_text)) != port_text
        ):
            raise ValueError("Connection server must have a canonical decimal port")
        server = (host, int(port_text))

    scope = {
        "type": "http",
        "scheme": scheme or "http",
        "path": path,
        "query_string": query,
        "headers": headers,
        "server": server,
    }
    try:
        return {"result.status": "ok", "result.url": str(URL(scope=scope))}
    except (KeyError, UnicodeDecodeError):
        return {"result.status": "error"}


def _host_pattern(input_value: dict[str, Any]) -> dict[str, Any]:
    from starlette.routing import Host

    input_spec = _strict_object(
        input_value,
        {"pattern", "host_header", "path", "format_params"},
        "HostPattern input",
    )
    pattern, host_header, path = (
        input_spec["pattern"],
        input_spec["host_header"],
        input_spec["path"],
    )
    if not all(isinstance(value, str) for value in (pattern, host_header, path)):
        raise ValueError("HostPattern string fields must be strings")
    params = _string_pairs(input_spec["format_params"], "HostPattern format_params")
    try:
        route = Host(pattern, app=_empty_asgi_app, name="host")
    except Exception:
        return {"registration.status": "error"}

    scope = _http_scope("GET", "/")
    try:
        scope["headers"] = [(b"host", host_header.encode("latin-1"))]
    except UnicodeEncodeError as exc:
        raise ValueError("HostPattern host_header must be Latin-1 encodable") from exc
    match, child_scope = route.matches(scope)
    captures = child_scope.get("path_params") if match.value == 2 else None
    try:
        url_path = route.url_path_for("host", path=path, **dict(params))
    except Exception:
        return {
            "registration.status": "ok",
            "match": _mapping_pairs(captures),
            "format.status": "error",
        }
    return {
        "registration.status": "ok",
        "match": _mapping_pairs(captures),
        "format.status": "ok",
        "format.path": str(url_path),
        "format.protocol": url_path.protocol,
        "format.host": url_path.host,
    }


def _named_route_table(input_value: dict[str, Any]) -> dict[str, Any]:
    from starlette.routing import Route, Router

    input_spec = _strict_object(input_value, {"routes", "lookup"}, "NamedRouteTable input")
    route_specs = input_spec["routes"]
    if not isinstance(route_specs, list):
        raise ValueError("NamedRouteTable routes must be an array")
    routes = []
    for index, raw_route in enumerate(route_specs):
        route_spec = _strict_object(raw_route, {"path", "name"}, f"NamedRouteTable routes[{index}]")
        if not all(isinstance(route_spec[field], str) for field in ("path", "name")):
            raise ValueError(f"NamedRouteTable routes[{index}] fields must be strings")
        routes.append(Route(route_spec["path"], _empty_endpoint, name=route_spec["name"]))
    lookup = _strict_object(input_spec["lookup"], {"name", "params"}, "NamedRouteTable lookup")
    if not isinstance(lookup["name"], str):
        raise ValueError("NamedRouteTable lookup.name must be a string")
    params = _string_pairs(lookup["params"], "NamedRouteTable lookup.params")
    router = Router(routes=routes)
    try:
        url_path = router.url_path_for(lookup["name"], **dict(params))
    except Exception:
        return {"lookup.status": "error"}
    return {
        "lookup.status": "ok",
        "lookup.path": str(url_path),
        "lookup.protocol": url_path.protocol,
        "lookup.host": url_path.host,
    }


def _route_dispatch(input_value: dict[str, Any]) -> dict[str, Any] | _Unsupported:
    from starlette.datastructures import URL, Headers
    from starlette.routing import Match, Route, Router

    required = {"routes", "path", "root_path", "method"}
    allowed = required | {
        "router_route_indexes",
        "supplemental_matches",
        "path_builds",
        "captures",
    }
    if (
        not isinstance(input_value, dict)
        or not required <= set(input_value)
        or set(input_value) - allowed
    ):
        raise ValueError("RouteTable input has missing or unknown fields")
    if any(key in input_value for key in ("router_route_indexes", "path_builds", "captures")):
        return _Unsupported(
            "RouteTable candidate-map, partial-build, and capture-helper outputs are Rust-native "
            "public API results with no matching pinned Router observation."
        )
    raw_routes = input_value["routes"]
    if not isinstance(raw_routes, list):
        raise ValueError("RouteTable routes must be an array")
    routes = []
    for index, raw_route in enumerate(raw_routes):
        route_spec = _strict_object(raw_route, {"path", "methods"}, f"RouteTable routes[{index}]")
        if not isinstance(route_spec["path"], str) or not isinstance(route_spec["methods"], list):
            raise ValueError(f"RouteTable routes[{index}] fields have invalid types")
        routes.append(Route(route_spec["path"], _empty_endpoint, methods=route_spec["methods"]))
    path, root_path, method = (
        input_value["path"],
        input_value["root_path"],
        input_value["method"],
    )
    if not all(isinstance(value, str) for value in (path, root_path, method)):
        raise ValueError("RouteTable path, root_path, and method must be strings")
    scope = _http_scope(method, path)
    scope["root_path"] = root_path
    full_match: tuple[int, dict[str, Any]] | None = None
    partial_match: tuple[int, dict[str, Any], Any] | None = None
    for index, route in enumerate(routes):
        match, child_scope = route.matches(scope)
        if match == Match.FULL:
            full_match = (index, child_scope)
            break
        if match == Match.PARTIAL and partial_match is None:
            partial_match = (index, child_scope, route)
    if full_match is not None:
        return {
            "plan": {
                "kind": "matched",
                "route_index": full_match[0],
                "path_params": full_match[1].get("path_params", {}),
            }
        }
    if partial_match is not None:
        index, child_scope, route = partial_match
        return {
            "plan": {
                "kind": "method-not-allowed",
                "route_index": index,
                "allowed_methods": sorted(route.methods or []),
                "path_params": child_scope.get("path_params", {}),
            }
        }

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(Router(routes=routes)(scope, receive, send))
    start = next((message for message in sent if message["type"] == "http.response.start"), None)
    if start is not None and start["status"] in (307, 308):
        location = Headers(raw=start["headers"]).get("location")
        if location is not None:
            return {"plan": {"kind": "redirect", "path": URL(location).path}}
    return {"plan": {"kind": "not-found"}}


def _response_call(input_value: dict[str, Any]) -> dict[str, Any]:
    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse, Response

    input_spec = _strict_object(
        input_value,
        {
            "constructor",
            "status_code",
            "call_status_code",
            "body",
            "headers",
            "cookie",
            "has_background",
            "actions",
        },
        "Response input",
    )
    constructor, status_code, body, raw_headers = (
        input_spec["constructor"],
        input_spec["status_code"],
        input_spec["body"],
        input_spec["headers"],
    )
    call_status_code = input_spec["call_status_code"]
    if (
        constructor not in {"from-content", "plain-text", "plain-text-with-status"}
        or type(status_code) is not int
        or (
            call_status_code is not None
            and (type(call_status_code) is not int or not 0 <= call_status_code <= 0xFFFF)
        )
        or not isinstance(body, str)
    ):
        raise ValueError(
            "Response constructor, status_code, call_status_code, or body have invalid values"
        )
    header_pairs = _string_pairs(raw_headers, "Response headers")
    if not isinstance(input_spec["has_background"], bool) or not isinstance(
        input_spec["actions"], list
    ):
        raise ValueError("Response has_background or actions have invalid types")
    actions = input_spec["actions"]
    send_actions = [
        action
        for action in actions
        if isinstance(action, dict) and action.get("kind") in {"send-ok", "send-error"}
    ]
    background_actions = [
        action
        for action in actions
        if isinstance(action, dict) and action.get("kind") in {"background-ok", "background-error"}
    ]
    events: list[dict[str, Any]] = []
    send_index = 0
    background_called = False

    async def background() -> None:
        nonlocal background_called
        background_called = True
        action = background_actions[0] if background_actions else {"kind": "background-ok"}
        if action["kind"] == "background-error":
            raise RuntimeError(action.get("message", ""))

    try:
        if constructor == "from-content":
            response = Response(
                body,
                status_code=status_code,
                headers=dict(header_pairs),
                media_type="text/plain",
                background=BackgroundTask(background) if input_spec["has_background"] else None,
            )
        elif constructor == "plain-text" and status_code == 200 and not header_pairs:
            response = PlainTextResponse(
                body,
                background=BackgroundTask(background) if input_spec["has_background"] else None,
            )
        elif constructor == "plain-text-with-status" and not header_pairs:
            response = PlainTextResponse(
                body,
                status_code=status_code,
                background=BackgroundTask(background) if input_spec["has_background"] else None,
            )
        else:
            raise ValueError("Response constructor input is incompatible with its fields")
    except Exception as exc:
        return {
            "construction.status": "error",
            "construction.error.type": type(exc).__name__,
            "construction.error.message": str(exc),
        }
    if call_status_code is not None:
        response.status_code = call_status_code
    cookie = input_spec["cookie"]
    if cookie is not None:
        try:
            response.set_cookie(cookie["key"], cookie["value"])
        except Exception as exc:
            return {
                "cookie.status": "error",
                "cookie.error.type": type(exc).__name__,
                "cookie.error.message": str(exc),
            }

    async def receive() -> dict[str, Any]:
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal send_index
        action = send_actions[send_index] if send_index < len(send_actions) else {"kind": "send-ok"}
        send_index += 1
        if action["kind"] == "send-error":
            raise RuntimeError(action.get("message", ""))
        if message["type"] == "http.response.start":
            events.append(
                {
                    "kind": "send-start",
                    "status_code": message["status"],
                    "headers_base64_pairs": [
                        [
                            base64.b64encode(name).decode("ascii"),
                            base64.b64encode(value).decode("ascii"),
                        ]
                        for name, value in message["headers"]
                    ],
                }
            )
        else:
            events.append(
                {
                    "kind": "send-body",
                    "body_base64": base64.b64encode(message.get("body", b"")).decode("ascii"),
                }
            )

    error: dict[str, str] | None = None
    try:
        asyncio.run(response(_http_scope("GET", "/"), receive, send))
    except Exception as exc:
        error = {"message": str(exc)}
    return {
        "events": events,
        "background_called": background_called,
        "result_status": "error" if error is not None else "ok",
        "error": error,
    }


def _http_scope(method: str, path: str) -> dict[str, Any]:
    parsed = urlsplit(path)
    request_path = parsed.path or "/"
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": parsed.scheme or "http",
        "path": request_path,
        "raw_path": request_path.encode("utf-8"),
        "query_string": parsed.query.encode("utf-8"),
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": (parsed.hostname or "testserver", parsed.port or 80),
    }


def _mapping_pairs(value: Any) -> list[list[str]] | None:
    if value is None:
        return None
    return [[str(key), str(item)] for key, item in value.items()]


async def _empty_asgi_app(_scope: dict[str, Any], _receive: Any, _send: Any) -> None:
    return None


def _empty_endpoint(_request: Any) -> Any:
    from starlette.responses import Response

    return Response()
