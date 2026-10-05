"""Import public modules with input-selected dependency loader failures."""

from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.abc
import importlib.util
import sys
import warnings
from typing import Any


def run_optional_import_case(case: dict[str, Any]) -> dict[str, Any]:
    spec = case["imports"]
    failures = {
        rule["module"]: {
            "ModuleNotFoundError": ModuleNotFoundError,
            "ImportError": ImportError,
            "RuntimeError": RuntimeError,
        }[rule["exception"]](rule["message"])
        for rule in spec["failures"]
    }
    trace: list[Any] = []

    class FailureLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
            if fullname in failures:
                trace.append({"event": "dependency-import", "module": fullname})
                return importlib.util.spec_from_loader(fullname, self)
            return None

        def create_module(self, module_spec: Any) -> Any:
            return None

        def exec_module(self, module: Any) -> None:
            raise failures[module.__name__]

    def observe_error(error: BaseException | None, seen: set[int]) -> Any:
        if error is None:
            return None
        if id(error) in seen:
            return {"cycle": True}
        seen = seen | {id(error)}
        return {
            "class": f"{type(error).__module__}.{type(error).__qualname__}",
            "args": list(error.args),
            "message": str(error),
            "input_error_modules": [name for name, value in failures.items() if error is value],
            "suppress_context": error.__suppress_context__,
            "cause": observe_error(error.__cause__, seen),
            "context": observe_error(error.__context__, seen),
        }

    module_name = spec["module"]
    roots = {"starlette", *failures}
    saved = {
        name: value
        for name, value in tuple(sys.modules.items())
        if any(name == root or name.startswith(root + ".") for root in roots)
    }
    for name in saved:
        del sys.modules[name]
    loader = FailureLoader()
    sys.meta_path.insert(0, loader)
    outcome: dict[str, Any] = {"imported": False, "error": None, "warnings": [], "trace": trace}
    try:
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter(spec["warning_filter"])
            try:
                module = importlib.import_module(module_name)
                outcome["imported"] = True
                selected = getattr(module, spec["consumer_attribute"])
                outcome["consumer_attribute"] = selected.__name__
                actions = []
                for stimulus in spec.get("actions", []):
                    try:
                        if stimulus["action"] == "form":
                            delivered = False

                            async def receive(stimulus: Any = stimulus) -> Any:
                                nonlocal delivered
                                if delivered:
                                    return {"type": "http.disconnect"}
                                delivered = True
                                return {
                                    "type": "http.request",
                                    "body": base64.b64decode(stimulus["body_base64"]),
                                    "more_body": False,
                                }

                            request = selected(
                                {
                                    "type": "http",
                                    "method": "POST",
                                    "path": "/",
                                    "headers": [
                                        (b"content-type", stimulus["content_type"].encode())
                                    ],
                                },
                                receive,
                            )

                            async def form(request: Any = request) -> Any:
                                async with request.form() as data:
                                    return [[key, value] for key, value in data.multi_items()]

                            value = asyncio.run(form())
                        elif stimulus["action"] == "render":
                            value = selected(stimulus["content"]).body.decode("utf-8")
                        else:

                            def endpoint() -> None:
                                pass

                            endpoint.__doc__ = stimulus["docstring"]
                            value = selected().parse_docstring(endpoint)
                        actions.append(
                            {"action": stimulus["action"], "value": value, "error": None}
                        )
                    except BaseException as error:
                        actions.append(
                            {"action": stimulus["action"], "error": observe_error(error, set())}
                        )
                if "actions" in spec:
                    outcome["actions"] = actions
            except BaseException as error:
                outcome["error"] = observe_error(error, set())
            outcome["warnings"] = [
                {
                    "category": f"{item.category.__module__}.{item.category.__qualname__}",
                    "message": str(item.message),
                }
                for item in recorded
            ]
    finally:
        sys.meta_path.remove(loader)
        for name in tuple(sys.modules):
            if any(name == root or name.startswith(root + ".") for root in roots):
                del sys.modules[name]
        sys.modules.update(saved)
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "import-policy", "status": "ok", "value": {"import-policy": outcome}}
        ],
    }
