"""Input-driven parity adapter for public ``URLPath.make_absolute_url``."""

from __future__ import annotations

from typing import Any


def run_urlpath_absolute_case(case: dict[str, Any]) -> dict[str, Any]:
    """Resolve supplied route lookups against supplied string and URL bases."""
    from starlette.applications import Starlette
    from starlette.datastructures import URL
    from starlette.responses import Response
    from starlette.routing import Host, Route, Router, WebSocketRoute

    async def http_endpoint(request: Any) -> Response:
        del request
        return Response()

    async def websocket_endpoint(websocket: Any) -> None:
        del websocket

    def build_route(node: dict[str, Any]) -> Any:
        kind = node["kind"]
        if kind == "http-route":
            return Route(
                node["path"],
                http_endpoint,
                methods=node["methods"],
                name=node["name"],
            )
        if kind == "websocket-route":
            return WebSocketRoute(node["path"], websocket_endpoint, name=node["name"])
        if kind == "host-route":
            return Host(
                node["host"],
                app=Router(routes=[build_route(route) for route in node["routes"]]),
                name=node["name"],
            )
        if kind == "router":
            return Router(routes=[build_route(route) for route in node["routes"]])
        if kind == "starlette-app":
            return Starlette(routes=[build_route(route) for route in node["routes"]])
        raise ValueError(f"unsupported URLPath route node: {kind!r}")

    graph = build_route(case["route_graph"])
    results = []
    for lookup in case["lookups"]:
        url_path = graph.url_path_for(lookup["name"], **lookup["path_params"])
        for base_spec in case["base_urls"]:
            base_url = URL(base_spec["value"]) if base_spec["kind"] == "url" else base_spec["value"]
            absolute_url = url_path.make_absolute_url(base_url)
            results.append(
                {
                    "lookup": lookup,
                    "url_path": {
                        "path": str(url_path),
                        "protocol": url_path.protocol,
                        "host": url_path.host,
                    },
                    "base_url": {"kind": base_spec["kind"], "value": str(base_url)},
                    "absolute_url": {
                        "url": str(absolute_url),
                        "scheme": absolute_url.scheme,
                        "netloc": absolute_url.netloc,
                        "path": absolute_url.path,
                        "query": absolute_url.query,
                        "fragment": absolute_url.fragment,
                    },
                }
            )

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "absolute-url-results",
                "status": "ok",
                "value": {"absolute-url-results": results},
            }
        ],
    }
