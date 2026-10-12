"""Input-selected inspection of public Starlette Python import surfaces."""

from __future__ import annotations

import importlib
import inspect
import json
from types import ModuleType
from typing import Any

from scripts.parity.contract import PUBLIC_API_INSPECTION_OBSERVATION

_MISSING = object()


def _qualified_type(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _normalized_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if type(value) in {tuple, list}:
        return {
            "kind": type(value).__name__,
            "items": [_normalized_value(item) for item in value],
        }
    if type(value) is dict:
        return {
            "kind": "dict",
            "items": [
                [_normalized_value(key), _normalized_value(item)] for key, item in value.items()
            ],
        }
    if type(value) in {set, frozenset}:
        items = [_normalized_value(item) for item in value]
        items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return {"kind": type(value).__name__, "items": items}
    if isinstance(value, type):
        return {"kind": "type", "name": f"{value.__module__}.{value.__qualname__}"}
    if callable(value):
        return {"kind": "callable", "name": f"{value.__module__}.{value.__qualname__}"}
    return {"kind": "object", "name": _qualified_type(value)}


def _resolve_symbol(
    module: ModuleType | None,
    symbol_name: str,
    *,
    resolve_submodules: bool,
) -> Any:
    if module is None:
        return _MISSING
    current: Any = module
    for segment in symbol_name.split("."):
        try:
            current = getattr(current, segment)
        except AttributeError:
            if not resolve_submodules or not isinstance(current, ModuleType):
                return _MISSING
            try:
                current = importlib.import_module(f"{current.__name__}.{segment}")
            except ImportError:
                return _MISSING
    return current


def _module_import(module_name: str) -> tuple[ModuleType | None, dict[str, Any]]:
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        return None, {
            "name": module_name,
            "imported": False,
            "error_type": f"{type(error).__module__}.{type(error).__qualname__}",
        }
    return module, {"name": module_name, "imported": True, "error_type": None}


def run_public_api_inspection_case(case: dict[str, Any]) -> dict[str, Any]:
    """Inspect only modules and symbols selected by the parity input."""
    inspection = case["inspection"]
    module_objects: dict[str, ModuleType | None] = {}
    module_observations: list[dict[str, Any]] = []
    for module_input in inspection["modules"]:
        module_name = module_input["name"]
        module, observation = _module_import(module_name)
        module_objects[module_name] = module
        observation["symbols"] = []
        for symbol_input in module_input["symbols"]:
            symbol_name = symbol_input["name"]
            value = _resolve_symbol(
                module,
                symbol_name,
                resolve_submodules=symbol_input.get("resolve_submodules", False),
            )
            present = value is not _MISSING
            symbol_observation: dict[str, Any] = {"name": symbol_name}
            if "presence" in symbol_input["observe"]:
                symbol_observation["presence"] = present
            if "signature" in symbol_input["observe"]:
                try:
                    symbol_observation["signature"] = str(inspect.signature(value))
                except (TypeError, ValueError):
                    symbol_observation["signature"] = None
                if not present:
                    symbol_observation["signature"] = None
            if "value" in symbol_input["observe"]:
                symbol_observation["value"] = _normalized_value(value) if present else None
            observation["symbols"].append(symbol_observation)
        module_observations.append(observation)

    identity_observations: list[dict[str, Any]] = []
    for check in inspection["identity_checks"]:
        left = check["left"]
        right = check["right"]
        left_value = _resolve_symbol(
            module_objects[left["module"]], left["symbol"], resolve_submodules=False
        )
        right_value = _resolve_symbol(
            module_objects[right["module"]], right["symbol"], resolve_submodules=False
        )
        outcome = "unavailable"
        if left_value is not _MISSING and right_value is not _MISSING:
            try:
                default = inspect.signature(left_value).parameters[left["parameter"]].default
            except (KeyError, TypeError, ValueError):
                pass
            else:
                outcome = "identical" if default is right_value else "different"
        identity_observations.append(
            {
                "left": {
                    "module": left["module"],
                    "symbol": left["symbol"],
                    "parameter": left["parameter"],
                },
                "right": {"module": right["module"], "symbol": right["symbol"]},
                "outcome": outcome,
            }
        )

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": PUBLIC_API_INSPECTION_OBSERVATION,
                "status": "ok",
                "value": {
                    "inspection": {
                        "modules": module_observations,
                        "identity_checks": identity_observations,
                    }
                },
            }
        ],
    }
