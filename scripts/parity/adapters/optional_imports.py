"""Import public modules with input-selected dependency loader failures."""

from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.abc
import importlib.util
import re
import sys
import warnings
from importlib import metadata
from pathlib import Path
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
    module_overrides = spec.get("module_overrides", [])
    module_aliases = spec.get("module_aliases", [])
    failure_parents = set()
    for failure_module in failures:
        parts = failure_module.split(".")
        failure_parents.update(".".join(parts[:depth]) for depth in range(1, len(parts)))
    roots = {
        "starlette",
        *failures,
        *failure_parents,
        *(override["module"] for override in module_overrides),
        *(alias[key] for alias in module_aliases for key in ("module", "source")),
    }
    saved = {
        name: value
        for name, value in tuple(sys.modules.items())
        if any(name == root or name.startswith(root + ".") for root in roots)
    }
    starlette_package = saved.get("starlette")
    package_paths = getattr(starlette_package, "__path__", ())
    package_path = next(iter(package_paths), None)
    package_parent = str(Path(package_path).parent) if package_path is not None else None
    original_sys_path = sys.path[:]
    for name in saved:
        del sys.modules[name]
    if package_parent is not None:
        # The oracle loads its pinned package by file spec, so its package parent
        # is not necessarily importable after this fresh-import reset.
        sys.path.insert(0, package_parent)
    loader = FailureLoader()
    loader_installed = False
    overridden_attributes: list[tuple[Any, str, Any]] = []
    missing_attribute = object()
    outcome: dict[str, Any] = {"imported": False, "error": None, "warnings": [], "trace": trace}
    try:
        if "distributions" in spec:
            versions = []
            for name in spec["distributions"]:
                try:
                    version = metadata.version(name)
                except metadata.PackageNotFoundError:
                    version = None
                versions.append({"name": name, "version": version})
            outcome["dependency_distributions"] = versions

        try:
            aliased_sources = []
            for alias in module_aliases:
                dependency = importlib.import_module(alias["source"])
                sys.modules[alias["module"]] = dependency
                aliased_sources.append(alias["source"])
            for source in set(aliased_sources):
                for name in tuple(sys.modules):
                    if name == source or name.startswith(source + "."):
                        del sys.modules[name]

            for override in module_overrides:
                dependency = importlib.import_module(override["module"])
                for alias in override["aliases"]:
                    attribute = alias["target_attribute"]
                    previous = getattr(dependency, attribute, missing_attribute)
                    overridden_attributes.append((dependency, attribute, previous))
                    setattr(dependency, attribute, getattr(dependency, alias["source_attribute"]))
                for attribute in override["missing_attributes"]:
                    previous = getattr(dependency, attribute, missing_attribute)
                    overridden_attributes.append((dependency, attribute, previous))
                    if previous is not missing_attribute:
                        delattr(dependency, attribute)
        except BaseException as error:
            outcome["error"] = observe_error(error, set())
        else:
            sys.meta_path.insert(0, loader)
            loader_installed = True
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
                            elif stimulus["action"] == "client-backend":
                                value = [
                                    {"module": base.__module__, "name": base.__qualname__}
                                    for base in selected.__bases__
                                ]
                            elif stimulus["action"] == "package-extra":
                                requirements = set()
                                available = False
                                extra = stimulus["extra"]
                                marker_pattern = re.compile(
                                    rf"extra\s*==\s*(['\"]){re.escape(extra)}\1",
                                    re.IGNORECASE,
                                )
                                for distribution_name in stimulus["distribution_candidates"]:
                                    try:
                                        distribution = metadata.distribution(distribution_name)
                                    except metadata.PackageNotFoundError:
                                        continue
                                    provided_extras = (
                                        distribution.metadata.get_all("Provides-Extra") or []
                                    )
                                    if extra not in provided_extras:
                                        continue
                                    available = True
                                    for requirement in distribution.requires or []:
                                        expression, separator, marker = requirement.partition(";")
                                        if separator and marker_pattern.search(marker):
                                            requirements.add(expression.strip())
                                value = {
                                    "extra": extra,
                                    "available": available,
                                    "requirements": sorted(requirements),
                                }
                            elif stimulus["action"] == "client-request":
                                response_status = stimulus["status_code"]
                                response_content_type = stimulus["content_type"]
                                response_body = stimulus["body_base64"]

                                async def app(
                                    scope: Any,
                                    receive: Any,
                                    send: Any,
                                    response_status: int = response_status,
                                    response_content_type: str = response_content_type,
                                    response_body: str = response_body,
                                ) -> None:
                                    await send(
                                        {
                                            "type": "http.response.start",
                                            "status": response_status,
                                            "headers": [
                                                (b"content-type", response_content_type.encode())
                                            ],
                                        }
                                    )
                                    await send(
                                        {
                                            "type": "http.response.body",
                                            "body": base64.b64decode(response_body),
                                        }
                                    )

                                with selected(app) as client:
                                    response = client.request(stimulus["method"], stimulus["path"])
                                value = {
                                    "status_code": response.status_code,
                                    "content_base64": base64.b64encode(response.content).decode(
                                        "ascii"
                                    ),
                                    "content_type": response.headers.get("content-type"),
                                }
                            elif stimulus["action"] == "dependency-selection":
                                dependency = getattr(module, stimulus["attribute"])
                                value = {
                                    "module": getattr(dependency, "__module__", None),
                                    "name": getattr(dependency, "__name__", None),
                                    "selected_candidates": [
                                        {
                                            "module": candidate,
                                            "selected": dependency is not None
                                            and candidate in sys.modules
                                            and getattr(
                                                sys.modules[candidate], stimulus["attribute"], None
                                            )
                                            is dependency,
                                        }
                                        for candidate in stimulus["candidate_modules"]
                                    ],
                                }
                                if dependency is None:
                                    value["module"] = None
                                    value["name"] = None
                            elif stimulus["action"] == "decorator-selection":
                                dependency = importlib.import_module("jinja2")
                                selected_decorator = module.pass_context
                                candidates = stimulus["attributes"]
                                value = {
                                    "available": [
                                        name for name in candidates if hasattr(dependency, name)
                                    ],
                                    "selected": [
                                        name
                                        for name in candidates
                                        if getattr(dependency, name, None) is selected_decorator
                                    ],
                                    "module": getattr(selected_decorator, "__module__", None),
                                    "name": getattr(selected_decorator, "__name__", None),
                                }
                            elif stimulus["action"] == "render":
                                response = selected(stimulus["content"])
                                value = {
                                    "status_code": response.status_code,
                                    "media_type": response.media_type,
                                    "content_type": response.headers.get("content-type"),
                                    "body": response.body.decode("utf-8"),
                                }
                            elif stimulus["action"] == "generate-schema":

                                def endpoint() -> None:
                                    pass

                                endpoint.__doc__ = stimulus["endpoint_docstring"]
                                route_type = importlib.import_module("starlette.routing").Route
                                route = route_type(
                                    stimulus["path"], endpoint, methods=stimulus["methods"]
                                )
                                generator = selected(stimulus["base_schema"])
                                value = generator.get_schema([route])
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
                                {
                                    "action": stimulus["action"],
                                    "error": observe_error(error, set()),
                                }
                            )
                    if "actions" in spec:
                        outcome["actions"] = actions
                except BaseException as error:
                    outcome["error"] = observe_error(error, set())
                outcome["warnings"] = [
                    {
                        "category": f"{item.category.__module__}.{item.category.__qualname__}",
                        "message": str(item.message),
                        "filename": item.filename,
                        "lineno": item.lineno,
                    }
                    for item in recorded
                ]
    finally:
        if loader_installed:
            sys.meta_path.remove(loader)
        for dependency, attribute, previous in reversed(overridden_attributes):
            if previous is missing_attribute:
                try:
                    delattr(dependency, attribute)
                except AttributeError:
                    pass
            else:
                setattr(dependency, attribute, previous)
        for name in tuple(sys.modules):
            if any(name == root or name.startswith(root + ".") for root in roots):
                del sys.modules[name]
        sys.modules.update(saved)
        sys.path[:] = original_sys_path
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "import-policy", "status": "ok", "value": {"import-policy": outcome}}
        ],
    }
