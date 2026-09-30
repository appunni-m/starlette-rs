"""Input-driven adapter for the WSGI helper and module-import boundary."""

from __future__ import annotations

import base64
import importlib
import sys
import warnings
from typing import Any

WSGI_MODULE = "starlette.middleware.wsgi"
WSGI_BOUNDARY_SURFACE = WSGI_MODULE
WSGI_BUILD_ENVIRON_OPERATION = "build-environ"
WSGI_MODULE_IMPORT_OPERATION = "module-import-warning"


def _scope_from_input(spec: dict[str, Any]) -> dict[str, Any]:
    scope = {
        key: value
        for key, value in spec.items()
        if key not in {"query_string_base64", "headers_base64_pairs"}
    }
    scope["query_string"] = base64.b64decode(spec["query_string_base64"], validate=True)
    scope["headers"] = [
        (
            base64.b64decode(name, validate=True),
            base64.b64decode(value, validate=True),
        )
        for name, value in spec.get("headers_base64_pairs", [])
    ]
    if "client" in scope and scope["client"] is not None:
        scope["client"] = tuple(scope["client"])
    if "server" in scope and scope["server"] is not None:
        scope["server"] = tuple(scope["server"])
    return scope


def _plain_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"WSGI environ value is not JSON-compatible: {type(value).__name__}")


def _run_build_environ_case(case: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module(WSGI_MODULE)
    environ = module.build_environ(
        _scope_from_input(case["scope"]),
        base64.b64decode(case["body_base64"], validate=True),
    )
    observed = []
    for probe in case["environ_probes"]:
        key = probe["key"]
        kind = probe["kind"]
        present = key in environ
        item: dict[str, Any] = {"key": key, "kind": kind, "present": present}
        if present and kind == "value":
            item["value"] = _plain_value(environ[key])
        elif present and kind == "read-bytes":
            item["value_base64"] = base64.b64encode(environ[key].read()).decode("ascii")
        elif present and kind == "is-stdout":
            item["value"] = environ[key] is sys.stdout
        observed.append(item)
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "environ-results",
                "status": "ok",
                "value": {"environ-results": {"probes": observed}},
            }
        ],
    }


def _run_module_import_warning_case(case: dict[str, Any]) -> dict[str, Any]:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        module = importlib.import_module(case["module_name"])
    warning_results = [
        {
            "category": f"{item.category.__module__}.{item.category.__qualname__}",
            "message": str(item.message),
            "filename": item.filename,
            "lineno": item.lineno,
        }
        for item in recorded
    ]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "import-results",
                "status": "ok",
                "value": {
                    "import-results": {
                        "module_name": module.__name__,
                        "warnings": warning_results,
                    }
                },
            }
        ],
    }


def run_wsgi_boundary_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["operation"] == WSGI_BUILD_ENVIRON_OPERATION:
        return _run_build_environ_case(case)
    if case["operation"] == WSGI_MODULE_IMPORT_OPERATION:
        return _run_module_import_warning_case(case)
    raise ValueError(f"unsupported WSGI boundary operation: {case['operation']!r}")
