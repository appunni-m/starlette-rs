"""Docstring-based OpenAPI schema generation forwarded to the Rust runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from starlette_rs_py import _core

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import BaseRoute
from starlette.routing import Host as Host
from starlette.routing import Mount as Mount
from starlette.routing import Route as Route

yaml = _core._schemas_optional_yaml_module()


class OpenAPIResponse(Response):
    media_type = "application/vnd.oai.openapi"

    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: Any = None,
        media_type: str | None = None,
        background: Any = None,
    ) -> None:
        super().__init__(content, status_code, headers, media_type, background)

    def render(self, content: Any) -> bytes:
        return _core._schemas_openapi_render(yaml, content)


class EndpointInfo(NamedTuple):
    path: str
    http_method: str
    func: Callable[..., Any]


class BaseSchemaGenerator:
    def get_schema(self, routes: list[BaseRoute]) -> dict[str, Any]:
        return _core._schemas_base_get_schema(self, routes)

    def get_endpoints(self, routes: list[BaseRoute]) -> list[EndpointInfo]:
        """Collect documented HTTP operations from routes and mounted routes."""
        return _core._schemas_get_endpoints(self, routes, EndpointInfo)

    def _remove_converter(self, path: str) -> str:
        """Remove converter annotations from path parameters."""
        return _core._schemas_remove_converter(path)

    def parse_docstring(self, func_or_method: Callable[..., Any]) -> dict[str, Any]:
        """Parse the YAML schema section from an endpoint docstring."""
        return _core._schemas_parse_docstring(yaml, func_or_method)

    def OpenAPIResponse(self, request: Request) -> Response:
        return _core._schemas_openapi_response(self, request, OpenAPIResponse)


class SchemaGenerator(BaseSchemaGenerator):
    def __init__(self, base_schema: dict[str, Any]) -> None:
        _core._schemas_generator_init(self, base_schema)

    def get_schema(self, routes: list[BaseRoute]) -> dict[str, Any]:
        return _core._schemas_generate(self, routes)
