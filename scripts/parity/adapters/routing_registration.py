"""Input-driven adapters for Router registration and URLPath construction."""

from __future__ import annotations

from typing import Any


def _make_endpoint(spec: dict[str, Any]) -> Any:
    if spec["async"]:

        async def endpoint(*_args: Any, **_kwargs: Any) -> None:
            return None

    else:

        def endpoint(*_args: Any, **_kwargs: Any) -> None:
            return None

    endpoint.__name__ = spec["name"]
    return endpoint


def _route_snapshot(route: Any, method_probes: list[str]) -> dict[str, Any]:
    route_methods = getattr(route, "methods", None)
    return {
        "kind": type(route).__name__,
        "path": route.path,
        "name": route.name,
        "method_membership": (
            {method: method in route_methods for method in method_probes}
            if route_methods is not None
            else None
        ),
        "include_in_schema": getattr(route, "include_in_schema", None),
    }


def _url_path_value(value: Any) -> dict[str, Any]:
    return {"path": str(value), "protocol": value.protocol, "host": value.host}


def run_router_registration_case(case: dict[str, Any], router_type: Any) -> dict[str, Any]:
    """Apply supplied registration calls, then observe routes and reverse lookups."""
    router = router_type()
    method_probes = list(
        dict.fromkeys(
            method
            for action in case["actions"]
            if action["method"] == "add_route"
            for method in action.get("methods") or []
        )
    )
    registration_states = []
    for action in case["actions"]:
        endpoint = _make_endpoint(action["endpoint"])
        if action["method"] == "add_route":
            arguments = {
                "path": action["path"],
                "endpoint": endpoint,
                "methods": action.get("methods"),
                "name": action.get("name"),
                "include_in_schema": action.get("include_in_schema", True),
            }
            router.add_route(**arguments)
        else:
            arguments = {
                "path": action["path"],
                "endpoint": endpoint,
                "name": action.get("name"),
            }
            router.add_websocket_route(**arguments)
        registration_states.append(
            {
                "method": action["method"],
                "routes": [_route_snapshot(route, method_probes) for route in router.routes],
            }
        )

    reverse_results = []
    for lookup in case["lookups"]:
        try:
            result = _url_path_value(router.url_path_for(lookup["name"], **lookup["path_params"]))
        except Exception as error:
            result = {
                "error": {
                    "class": f"{type(error).__module__}.{type(error).__qualname__}",
                    "message": str(error),
                }
            }
        reverse_results.append({"lookup": lookup, "result": result})

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "registration-state",
                "status": "ok",
                "value": {"registration-state": registration_states},
            },
            {
                "step_id": "reverse-url-results",
                "status": "ok",
                "value": {"reverse-url-results": reverse_results},
            },
        ],
    }


def run_urlpath_constructor_case(case: dict[str, Any], urlpath_type: Any) -> dict[str, Any]:
    """Construct URLPaths from supplied values and report live values or errors."""
    results = []
    for attempt in case["attempts"]:
        try:
            value = urlpath_type(
                attempt["path"],
                protocol=attempt["protocol"],
                host=attempt["host"],
            )
            result = {"value": _url_path_value(value)}
        except Exception as error:
            result = {
                "error": {
                    "class": f"{type(error).__module__}.{type(error).__qualname__}",
                    "message": str(error),
                }
            }
        results.append({"input": attempt, "result": result})

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "constructor-results",
                "status": "ok",
                "value": {"constructor-results": results},
            }
        ],
    }
