"""Route declarations and ASGI dispatch backed by the native route table."""

from __future__ import annotations

import functools
import inspect
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from enum import Enum
from re import Pattern
from typing import Any

from starlette_rs_py import _core

from starlette.concurrency import run_in_threadpool
from starlette.convertors import _BUILTIN_CONVERTOR_TYPES, CONVERTOR_TYPES, Convertor
from starlette.datastructures import URL, URLPath
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.websockets import WebSocket, WebSocketClose

if sys.version_info >= (3, 13):
    from inspect import iscoroutinefunction
else:
    from asyncio import iscoroutinefunction


class NoMatchFound(Exception):
    """Raised when a named route cannot be found."""

    def __init__(self, name: str, path_params: dict[str, Any]) -> None:
        params = ", ".join(list(path_params.keys()))
        super().__init__(f'No route exists for name "{name}" and params "{params}".')


class Match(Enum):
    """Route matching result, ordered from no match to full match."""

    NONE = 0
    PARTIAL = 1
    FULL = 2


PARAM_REGEX = re.compile(r"{([a-zA-Z_][a-zA-Z0-9_]*)(:[a-zA-Z_][a-zA-Z0-9_]*)?}")


def compile_path(
    path: str,
) -> tuple[Pattern[str], str, dict[str, Convertor[Any]]]:
    """Compile a Starlette path template into a regex and parameter map."""

    is_host = not path.startswith("/")
    path_regex = "^"
    path_format = ""
    duplicated_params: set[str] = set()
    idx = 0
    param_convertors: dict[str, Convertor[Any]] = {}

    for match in PARAM_REGEX.finditer(path):
        param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        assert convertor_type in CONVERTOR_TYPES, f"Unknown path convertor '{convertor_type}'"
        convertor = CONVERTOR_TYPES[convertor_type]

        path_regex += re.escape(path[idx : match.start()])
        path_regex += f"(?P<{param_name}>{convertor.regex})"
        path_format += path[idx : match.start()]
        path_format += f"{{{param_name}}}"

        if param_name in param_convertors:
            duplicated_params.add(param_name)
        param_convertors[param_name] = convertor
        idx = match.end()

    if duplicated_params:
        names = ", ".join(sorted(duplicated_params))
        ending = "s" if len(duplicated_params) > 1 else ""
        raise ValueError(f"Duplicated param name{ending} {names} at path {path}")

    if is_host:
        hostname = path[idx:].split(":")[0]
        path_regex += re.escape(hostname) + "$"
    else:
        path_regex += re.escape(path[idx:]) + "$"
    path_format += path[idx:]
    return re.compile(path_regex), path_format, param_convertors


def _uses_custom_convertors(path: str) -> bool:
    """Keep registered Python convertors out of the built-in native parser."""

    for match in PARAM_REGEX.finditer(path):
        _param_name, convertor_type = match.groups("str")
        convertor_type = convertor_type.lstrip(":")
        builtin = _BUILTIN_CONVERTOR_TYPES.get(convertor_type)
        if builtin is None or CONVERTOR_TYPES.get(convertor_type) is not builtin:
            return True
    return False


def _match_python_path(route: BaseRoute, route_path: str) -> dict[str, Any] | None:
    """Run the Python regex/converter boundary for custom registered patterns.

    Rust's route table deliberately accepts only the five pinned built-ins.
    A custom ``Convertor`` supplies Python regex and conversion behavior, so
    this fallback is limited to routes that captured one at construction.
    """

    match = route.path_regex.match(route_path)
    if match is None:
        return None
    matched_params = match.groupdict()
    for key, value in matched_params.items():
        matched_params[key] = route.param_convertors[key].convert(value)
    return matched_params


def _get_route_path(scope: dict[str, Any]) -> str:
    path = scope["path"]
    root_path = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path) :]
    return path


def _convert_path_params(route: BaseRoute, captured: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """Convert captured path strings with the public convertors."""

    return {name: route.param_convertors[name].convert(value) for name, value in captured}


def _convert_rust_match(
    route: BaseRoute, route_path: str, rust_captured: Iterable[tuple[str, str]]
) -> dict[str, Any]:
    """Reconvert a native match from the original path text.

    Rust canonicalizes integer captures. Re-running the stored Python regex
    preserves the exact string passed to ``Convertor.convert`` while checking
    that both matchers selected the same parameters and capture boundaries.
    """

    match = route.path_regex.match(route_path)
    if match is None:
        raise RuntimeError("Rust matched a route that the Python path regex did not match")

    python_captured = match.groupdict()
    rust_captured = list(rust_captured)
    parameter_names = list(route.param_convertors)
    python_names = list(python_captured)
    rust_names = [name for name, _value in rust_captured]
    if python_names != parameter_names or rust_names != parameter_names:
        raise RuntimeError(
            "Rust and Python route matchers captured different path parameters "
            f"(Rust: {rust_names!r}, Python: {python_names!r})"
        )

    converted = _convert_path_params(route, python_captured.items())
    rust_values = dict(rust_captured)
    for name, raw_value in python_captured.items():
        convertor = route.param_convertors[name]
        expected_rust_value = (
            str(converted[name]) if convertor is _BUILTIN_CONVERTOR_TYPES["int"] else raw_value
        )
        if rust_values[name] != expected_rust_value:
            raise RuntimeError(
                f"Rust and Python route matchers captured different values for {name!r}"
            )
    return converted


def _format_path_params(
    route: BaseRoute, path_params: dict[str, Any], *, partial: bool = False
) -> tuple[str, dict[str, Any]]:
    """Format already selected path parameters through Rust or custom callbacks."""

    remaining = dict(path_params)
    if route._route_table is not None:
        if partial:
            formatted: list[tuple[str, str]] = []
            path = route.path_format
            consumed: set[str] = set()
            for name, value in path_params.items():
                placeholder = "{" + name + "}"
                if placeholder in path:
                    value = route.param_convertors[name].to_string(value)
                    formatted.append((name, value))
                    path = path.replace(placeholder, value)
                    consumed.add(name)
            path, _unmatched = route._route_table.build_path_partial(0, formatted)
            remaining = {name: value for name, value in path_params.items() if name not in consumed}
            return path, remaining

        formatted = [
            (name, route.param_convertors[name].to_string(value))
            for name, value in path_params.items()
        ]
        return route._route_table.build_path(0, formatted), {}

    path = route.path_format
    for name, value in list(remaining.items()):
        placeholder = "{" + name + "}"
        if placeholder in path:
            value = route.param_convertors[name].to_string(value)
            path = path.replace(placeholder, value)
            remaining.pop(name)
    return path, remaining


def _is_async_callable(endpoint: Callable[..., Any]) -> bool:
    """Match Starlette's async-callable detection, including partials."""

    while isinstance(endpoint, functools.partial):
        endpoint = endpoint.func
    return iscoroutinefunction(endpoint) or (
        callable(endpoint) and iscoroutinefunction(endpoint.__call__)
    )


def _is_request_endpoint(endpoint: Callable[..., Any]) -> bool:
    """Match Starlette's distinction between request endpoints and ASGI apps."""

    endpoint_handler = endpoint
    while isinstance(endpoint_handler, functools.partial):
        endpoint_handler = endpoint_handler.func
    return inspect.isfunction(endpoint_handler) or inspect.ismethod(endpoint_handler)


def _get_name(endpoint: Callable[..., Any]) -> str:
    return getattr(endpoint, "__name__", endpoint.__class__.__name__)


def _apply_middleware(
    app: Callable[..., Any], middleware: Sequence[Any] | None
) -> Callable[..., Any]:
    if middleware is None:
        return app
    for middleware_item in reversed(middleware):
        cls, args, kwargs = middleware_item
        app = cls(app, *args, **kwargs)
    return app


def _request_response(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    async def app(
        scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        request = Request(scope, receive)
        try:
            if _is_async_callable(endpoint):
                response = await endpoint(request)
            else:
                response = await run_in_threadpool(endpoint, request)
        except HTTPException as exc:
            # Match Starlette's request_response wrapper: a handled HTTP
            # exception must receive the same Request instance that the
            # endpoint used, including its cached body.
            app_instance = scope.get("app")
            exception_response = getattr(app_instance, "_exception_response", None)
            if exception_response is None:
                raise
            response = await exception_response(request, exc)
            if response is None:
                return
        await response(scope, receive, send)

    return app


class BaseRoute:
    """Common interface for a route that can be mounted in a Router."""

    path: str
    name: str | None
    param_convertors: dict[str, Convertor[Any]]
    _uses_custom_convertors: bool

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        raise NotImplementedError()  # pragma: no cover

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        raise NotImplementedError()  # pragma: no cover

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        raise NotImplementedError()  # pragma: no cover

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        match, child_scope = self.matches(scope)
        if match == Match.NONE:
            if scope["type"] == "http":
                await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
            elif scope["type"] == "websocket":
                await WebSocketClose()(scope, receive, send)
            return
        scope.update(child_scope)
        await self.handle(scope, receive, send)


class Route(BaseRoute):
    """Declare an HTTP path and its request or ASGI endpoint."""

    __slots__ = (
        "path",
        "endpoint",
        "name",
        "methods",
        "include_in_schema",
        "app",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        methods: Iterable[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        assert path.startswith("/"), "Routed paths must start with '/'"
        self.path = path
        self.endpoint = endpoint
        self.name = _get_name(endpoint) if name is None else name
        self.include_in_schema = include_in_schema

        if _is_request_endpoint(endpoint):
            self.app = _request_response(endpoint)
            if methods is None:
                methods = ["GET"]
        else:
            self.app = endpoint

        self.app = _apply_middleware(self.app, middleware)
        if max_body_size is not None:
            raise NotImplementedError("route max_body_size middleware is outside this slice")

        if methods is None:
            self.methods: set[str] | None = None
        else:
            self.methods = {method.upper() for method in methods}
            if "GET" in self.methods:
                self.methods.add("HEAD")

        self.path_regex, self.path_format, self.param_convertors = compile_path(path)
        self._uses_custom_convertors = _uses_custom_convertors(path)
        if self._uses_custom_convertors:
            self._route_table = None
        else:
            self._route_table = _core.RouteTable()
            self._route_table.add_route(path, [] if self.methods is None else list(self.methods))

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        if scope.get("type") != "http":
            return Match.NONE, {}
        if self._uses_custom_convertors:
            matched_params = _match_python_path(self, _get_route_path(scope))
            if matched_params is None:
                return Match.NONE, {}
            matched = "matched"
        else:
            assert self._route_table is not None
            matched, _index, _fallback, captured, _allowed = (
                self._route_table.match_route_with_root_path(
                    scope["path"], scope.get("root_path", ""), scope["method"]
                )
            )
            if matched == "not_found":
                return Match.NONE, {}
            matched_params = _convert_rust_match(self, _get_route_path(scope), captured)
        path_params = dict(scope.get("path_params", {}))
        path_params.update(matched_params)
        child_scope = {"endpoint": self.endpoint, "path_params": path_params}
        if matched == "matched" and self.methods and scope["method"] not in self.methods:
            matched = "method_not_allowed"
        return (Match.FULL if matched == "matched" else Match.PARTIAL), child_scope

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if self.methods and scope["method"] not in self.methods:
            headers = {"Allow": ", ".join(self.methods)}
            if "app" in scope:
                raise HTTPException(status_code=405, headers=headers)
            response = PlainTextResponse("Method Not Allowed", status_code=405, headers=headers)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        if name != self.name or set(path_params) != set(self.param_convertors):
            raise NoMatchFound(name, path_params)
        path, remaining = _format_path_params(self, path_params)
        assert not remaining
        return URLPath(path=path, protocol="http")

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Route)
            and self.path == other.path
            and self.endpoint == other.endpoint
            and self.methods == other.methods
        )

    def __repr__(self) -> str:
        methods = sorted(self.methods or [])
        return f"Route(path={self.path!r}, name={self.name!r}, methods={methods!r})"


class WebSocketRoute(BaseRoute):
    """Declare a WebSocket path and its Python or ASGI endpoint."""

    __slots__ = (
        "path",
        "endpoint",
        "name",
        "app",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        name: str | None = None,
        middleware: Sequence[Middleware] | None = None,
    ) -> None:
        assert path.startswith("/"), "Routed paths must start with '/'"
        self.path = path
        self.endpoint = endpoint
        self.name = _get_name(endpoint) if name is None else name

        if _is_request_endpoint(endpoint):

            async def app(
                scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
            ) -> None:
                await endpoint(WebSocket(scope, receive, send))

            self.app: Callable[..., Any] = app
        else:
            self.app = endpoint
        self.app = _apply_middleware(self.app, middleware)

        self.path_regex, self.path_format, self.param_convertors = compile_path(path)
        self._uses_custom_convertors = _uses_custom_convertors(path)
        if self._uses_custom_convertors:
            self._route_table = None
        else:
            self._route_table = _core.RouteTable()
            self._route_table.add_route(path, ["GET"])

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        if scope.get("type") != "websocket":
            return Match.NONE, {}
        if self._uses_custom_convertors:
            matched_params = _match_python_path(self, _get_route_path(scope))
            if matched_params is None:
                return Match.NONE, {}
        else:
            assert self._route_table is not None
            matched, _index, _fallback, captured, _allowed = (
                self._route_table.match_route_with_root_path(
                    scope["path"], scope.get("root_path", ""), "GET"
                )
            )
            if matched != "matched":
                return Match.NONE, {}
            matched_params = _convert_rust_match(self, _get_route_path(scope), captured)
        path_params = dict(scope.get("path_params", {}))
        path_params.update(matched_params)
        return Match.FULL, {"endpoint": self.endpoint, "path_params": path_params}

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self.app(scope, receive, send)

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        if name != self.name or set(path_params) != set(self.param_convertors):
            raise NoMatchFound(name, path_params)
        path, remaining = _format_path_params(self, path_params)
        assert not remaining
        return URLPath(path=path, protocol="websocket")

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, WebSocketRoute)
            and self.path == other.path
            and self.endpoint == other.endpoint
        )

    def __repr__(self) -> str:
        return f"WebSocketRoute(path={self.path!r}, name={self.name!r})"


class Mount(BaseRoute):
    """Mount an ASGI application or nested routes below a path prefix."""

    __slots__ = (
        "path",
        "_base_app",
        "app",
        "name",
        "path_regex",
        "path_format",
        "param_convertors",
        "_uses_custom_convertors",
        "_route_table",
    )

    def __init__(
        self,
        path: str,
        app: Callable[..., Any] | None = None,
        routes: Sequence[BaseRoute] | None = None,
        name: str | None = None,
        *,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        assert path == "" or path.startswith("/"), "Routed paths must start with '/'"
        assert app is not None or routes is not None, (
            "Either 'app=...', or 'routes=' must be specified"
        )
        self.path = path.rstrip("/")
        self._base_app = app if app is not None else Router(routes=routes)
        self.app = _apply_middleware(self._base_app, middleware)
        if max_body_size is not None:
            raise NotImplementedError("mount max_body_size middleware is outside this slice")
        self.name = name
        self.path_regex, self.path_format, self.param_convertors = compile_path(
            self.path + "/{path:path}"
        )
        self._uses_custom_convertors = _uses_custom_convertors(self.path + "/{path:path}")
        if self._uses_custom_convertors:
            self._route_table = None
        else:
            self._route_table = _core.RouteTable()
            self._route_table.add_route(self.path + "/{path:path}", [])

    @property
    def routes(self) -> list[BaseRoute]:
        return getattr(self._base_app, "routes", [])

    def matches(self, scope: dict[str, Any]) -> tuple[Match, dict[str, Any]]:
        if scope.get("type") not in ("http", "websocket"):
            return Match.NONE, {}
        root_path = scope.get("root_path", "")
        route_path = _get_route_path(scope)
        if self._uses_custom_convertors:
            converted = _match_python_path(self, route_path)
            if converted is None:
                return Match.NONE, {}
        else:
            assert self._route_table is not None
            matched, _index, _fallback, captured, _allowed = (
                self._route_table.match_route_with_root_path(
                    scope["path"], root_path, scope.get("method", "GET")
                )
            )
            if matched != "matched":
                return Match.NONE, {}
            converted = _convert_rust_match(self, route_path, captured)
        remaining_path = "/" + converted.pop("path")
        matched_path = route_path[: -len(remaining_path)]
        path_params = dict(scope.get("path_params", {}))
        path_params.update(converted)
        child_scope = {
            "path_params": path_params,
            "app_root_path": scope.get("app_root_path", root_path),
            "root_path": root_path + matched_path,
            "endpoint": self.app,
        }
        return Match.FULL, child_scope

    async def handle(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self.app(scope, receive, send)

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        path_params = dict(path_params)
        if self.name is not None and name == self.name and "path" in path_params:
            path_params["path"] = path_params["path"].lstrip("/")
            path, path_params = _format_path_params(self, path_params, partial=True)
            if not path_params:
                return URLPath(path=path)
        elif self.name is None or name.startswith(self.name + ":"):
            remaining_name = name if self.name is None else name[len(self.name) + 1 :]
            path_kwarg = path_params.get("path")
            path_params["path"] = ""
            path_prefix, remaining_params = _format_path_params(self, path_params, partial=True)
            if path_kwarg is not None:
                remaining_params["path"] = path_kwarg
            path_params = remaining_params
            for route in self.routes or []:
                try:
                    url = route.url_path_for(remaining_name, **remaining_params)
                    return URLPath(
                        path=path_prefix.rstrip("/") + str(url),
                        protocol=url.protocol,
                    )
                except NoMatchFound:
                    pass
        raise NoMatchFound(name, path_params)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mount) and self.path == other.path and self.app == other.app

    def __repr__(self) -> str:
        return f"Mount(path={self.path!r}, name={self.name or ''!r}, app={self.app!r})"


class Router:
    """Dispatch ordered HTTP and WebSocket routes through Rust path matching.

    If a route captured a user-registered convertor, candidates are checked in
    declaration order; built-in candidates still delegate path matching to
    their Rust route tables, while the custom callback runs in Python.
    """

    __slots__ = (
        "routes",
        "redirect_slashes",
        "default",
        "_route_table",
        "_route_indexes",
        "_custom_http_route_indexes",
        "_websocket_route_table",
        "_websocket_route_indexes",
        "_custom_websocket_route_indexes",
        "middleware_stack",
    )

    def __init__(
        self,
        routes: Sequence[BaseRoute] | None = None,
        redirect_slashes: bool = True,
        default: Callable[..., Any] | None = None,
        lifespan: Callable[..., Any] | None = None,
        *,
        middleware: Sequence[Middleware] | None = None,
        max_body_size: int | None = None,
    ) -> None:
        del lifespan
        self.routes = [] if routes is None else list(routes)
        self.redirect_slashes = redirect_slashes
        self.default = self.not_found if default is None else default
        self._route_table = _core.RouteTable()
        self._route_indexes: list[int] = []
        self._custom_http_route_indexes: list[int] = []
        self._websocket_route_table = _core.RouteTable()
        self._websocket_route_indexes: list[int] = []
        self._custom_websocket_route_indexes: list[int] = []
        for index, route in enumerate(self.routes):
            self._register_route(route, index)
        app: Callable[..., Any] = self.app
        self.middleware_stack = _apply_middleware(app, middleware)
        if max_body_size is not None:
            raise NotImplementedError("router max_body_size middleware is outside this slice")

    def _register_route(self, route: BaseRoute, index: int) -> None:
        if isinstance(route, Route):
            if route._uses_custom_convertors:
                self._custom_http_route_indexes.append(index)
            else:
                self._route_indexes.append(index)
                self._route_table.add_route(
                    route.path, [] if route.methods is None else list(route.methods)
                )
        elif isinstance(route, WebSocketRoute):
            if route._uses_custom_convertors:
                self._custom_websocket_route_indexes.append(index)
            else:
                self._websocket_route_indexes.append(index)
                self._websocket_route_table.add_route(route.path, ["GET"])
        elif isinstance(route, Mount):
            if route._uses_custom_convertors:
                self._custom_http_route_indexes.append(index)
                self._custom_websocket_route_indexes.append(index)
            else:
                mount_path = route.path + "/{path:path}"
                self._route_indexes.append(index)
                self._route_table.add_route(mount_path, [])
                self._websocket_route_indexes.append(index)
                self._websocket_route_table.add_route(mount_path, [])
        else:
            raise TypeError("routes must contain Route, WebSocketRoute, or Mount instances")

    def _select_route(
        self, scope: dict[str, Any]
    ) -> tuple[Match, BaseRoute | None, dict[str, Any]]:
        scope_type = scope.get("type")
        if scope_type == "http":
            if self._custom_http_route_indexes:
                # Merge native built-in matches with custom Python patterns in
                # the same full-first/first-partial order as Starlette Router.
                first_partial: tuple[BaseRoute, dict[str, Any]] | None = None
                for route in self.routes:
                    if not isinstance(route, (Route, Mount)):
                        continue
                    match, child_scope = route.matches(scope)
                    if match == Match.FULL:
                        return match, route, child_scope
                    if match == Match.PARTIAL and first_partial is None:
                        first_partial = (route, child_scope)
                if first_partial is not None:
                    route, child_scope = first_partial
                    return Match.PARTIAL, route, child_scope
                return Match.NONE, None, {}
            decision = self._route_table.match_route_with_root_path(
                scope["path"], scope.get("root_path", ""), scope["method"]
            )
            indexes = self._route_indexes
        elif scope_type == "websocket":
            if self._custom_websocket_route_indexes:
                for route in self.routes:
                    if not isinstance(route, (WebSocketRoute, Mount)):
                        continue
                    match, child_scope = route.matches(scope)
                    if match == Match.FULL:
                        return match, route, child_scope
                return Match.NONE, None, {}
            decision = self._websocket_route_table.match_route_with_root_path(
                scope["path"], scope.get("root_path", ""), "GET"
            )
            indexes = self._websocket_route_indexes
        else:
            return Match.NONE, None, {}

        matched, route_index, _fallback, captured, _allowed = decision
        if route_index is None:
            return Match.NONE, None, {}
        route = self.routes[indexes[route_index]]
        if isinstance(route, Mount):
            route_match, child_scope = route.matches(scope)
            return route_match, route, child_scope
        if matched == "not_found":
            return Match.NONE, None, {}
        path_params = dict(scope.get("path_params", {}))
        path_params.update(_convert_rust_match(route, _get_route_path(scope), captured))
        child_scope = {"endpoint": route.endpoint, "path_params": path_params}
        return (Match.FULL if matched == "matched" else Match.PARTIAL), route, child_scope

    def _slash_redirect_scope(self, scope: dict[str, Any]) -> dict[str, Any] | None:
        """Return a copied scope with a matching alternate slash path, if any."""

        if scope.get("type") != "http" or not self.redirect_slashes:
            return None

        route_path = _get_route_path(scope)
        if route_path == "/":
            return None

        if self._custom_http_route_indexes:
            redirect_scope = dict(scope)
            if route_path.endswith("/"):
                redirect_scope["path"] = redirect_scope["path"].rstrip("/")
            else:
                redirect_scope["path"] = redirect_scope["path"] + "/"
            # Preserve route declaration order when Python converter callbacks
            # are present. Built-in route.matches calls still delegate their
            # matching decision to Rust.
            match, _route, _child_scope = self._select_route(redirect_scope)
            return redirect_scope if match != Match.NONE else None

        redirect_path = self._route_table.find_slash_redirect_path(
            scope["path"], scope.get("root_path", ""), scope.get("method", "GET")
        )
        if redirect_path is not None:
            redirect_scope = dict(scope)
            redirect_scope["path"] = redirect_path
            return redirect_scope

        return None

    async def _send_slash_redirect(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any],
        send: Callable[..., Any],
    ) -> bool:
        redirect_scope = self._slash_redirect_scope(scope)
        if redirect_scope is None:
            return False

        redirect_url = URL(scope=redirect_scope)
        await RedirectResponse(url=str(redirect_url))(scope, receive, send)
        return True

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        await self.middleware_stack(scope, receive, send)

    async def app(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        assert scope["type"] in ("http", "websocket", "lifespan")
        scope.setdefault("router", self)
        if scope["type"] == "lifespan":
            raise NotImplementedError("Router lifespan dispatch is outside this slice")

        match, route, child_scope = self._select_route(scope)
        if match != Match.NONE and route is not None:
            scope.update(child_scope)
            await route.handle(scope, receive, send)
            return

        if await self._send_slash_redirect(scope, receive, send):
            return
        await self.default(scope, receive, send)

    async def not_found(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose()(scope, receive, send)
        elif "app" in scope:
            raise HTTPException(status_code=404)
        else:
            await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)

    def url_path_for(self, name: str, /, **path_params: Any) -> URLPath:
        for route in self.routes:
            try:
                return route.url_path_for(name, **path_params)
            except NoMatchFound:
                pass
        raise NoMatchFound(name, path_params)

    def mount(self, path: str, app: Callable[..., Any], name: str | None = None) -> None:
        route = Mount(path, app=app, name=name)
        index = len(self.routes)
        self.routes.append(route)
        self._register_route(route, index)

    def add_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        methods: Iterable[str] | None = None,
        name: str | None = None,
        include_in_schema: bool = True,
    ) -> None:
        route = Route(
            path,
            endpoint=endpoint,
            methods=methods,
            name=name,
            include_in_schema=include_in_schema,
        )
        index = len(self.routes)
        self.routes.append(route)
        self._register_route(route, index)

    def add_websocket_route(
        self, path: str, endpoint: Callable[..., Any], name: str | None = None
    ) -> None:
        route = WebSocketRoute(path, endpoint=endpoint, name=name)
        index = len(self.routes)
        self.routes.append(route)
        self._register_route(route, index)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Router) and self.routes == other.routes
