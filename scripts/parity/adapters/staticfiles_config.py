"""Shared input-driven StaticFiles configuration parity workflow."""

from __future__ import annotations

import asyncio
import base64
import importlib
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

STATIC_FILES_SURFACE = "starlette.staticfiles.StaticFiles"
STATIC_FILES_CONFIGURATION_OPERATION = "configuration-check"
STATIC_FILES_CONFIGURATION_STEP = "configuration-check"
_FILESYSTEM_ROOT = Path("build/parity/static-files-config")


class _InputDisplayPathLike:
    """Input-backed path with a display string distinct from its filesystem path."""

    def __init__(self, path: Path, display: str) -> None:
        self._path = path
        self._display = display
        self.fspath_calls = 0
        self.str_calls = 0

    def __fspath__(self) -> str:
        self.fspath_calls += 1
        return str(self._path)

    def __str__(self) -> str:
        self.str_calls += 1
        return self._display


def _exact_object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _error_observation(exc: Exception, stage: str) -> dict[str, Any]:
    cause = exc.__cause__
    if cause is None:
        cause_observation = None
    else:
        try:
            cause_attributes = vars(cause)
        except TypeError:
            cause_attributes = {}
        cause_observation = {
            "class": f"{type(cause).__module__}.{type(cause).__qualname__}",
            "message": str(cause),
            "attributes": _json_safe(cause_attributes),
        }
    return {
        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "kind": "exception",
        "message": str(exc),
        "stage": stage,
        "code": getattr(exc, "status_code", None),
        "cause": cause_observation,
        "suppress_context": bool(exc.__suppress_context__),
    }


def _configuration_path(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("StaticFiles directory_path must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("StaticFiles directory_path must stay under build/parity")
    if relative.parts[: len(_FILESYSTEM_ROOT.parts)] != _FILESYSTEM_ROOT.parts:
        raise ValueError(
            "StaticFiles directory_path must stay under build/parity/static-files-config"
        )
    suffix = relative.parts[len(_FILESYSTEM_ROOT.parts) :]
    if not suffix or any(part in {"", "."} for part in suffix):
        raise ValueError(
            "StaticFiles directory_path must name a child of the configuration fixture root"
        )

    repository_root = Path.cwd().resolve()
    fixture_root = repository_root / _FILESYSTEM_ROOT
    fixture_root.mkdir(parents=True, exist_ok=True)
    resolved_fixture_root = fixture_root.resolve()
    resolved_parent = (fixture_root / Path(*suffix[:-1])).resolve()
    if not resolved_parent.is_relative_to(resolved_fixture_root):
        raise ValueError(
            "StaticFiles directory_path parent resolves outside build/parity/static-files-config"
        )
    return fixture_root / Path(*suffix)


def _remove_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _prepare_filesystem(case: dict[str, Any], directory: Path) -> None:
    directory_kind = case["directory_kind"]
    root_contents = case["root_file_contents_base64"]
    if directory_kind not in {"missing", "file", "directory"}:
        raise ValueError("StaticFiles directory_kind must be missing, file, or directory")
    if directory_kind == "file":
        if not isinstance(root_contents, str):
            raise ValueError("StaticFiles file directory_kind requires root_file_contents_base64")
    elif root_contents is not None:
        raise ValueError(
            "StaticFiles root_file_contents_base64 must be null unless directory_kind is file"
        )

    files = case["files"]
    if not isinstance(files, list):
        raise ValueError("StaticFiles files must be an array")
    if directory_kind != "directory" and files:
        raise ValueError("StaticFiles file fixtures require directory_kind directory")

    _remove_path(directory)
    directory.parent.mkdir(parents=True, exist_ok=True)
    if directory_kind == "file":
        try:
            root_body = base64.b64decode(root_contents, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid base64 at root_file_contents_base64") from exc
        directory.write_bytes(root_body)
    elif directory_kind == "directory":
        directory.mkdir(parents=True)
        for index, item in enumerate(files):
            item = _exact_object(
                item,
                {"path", "contents_base64", "mtime_seconds"},
                f"StaticFiles files[{index}]",
            )
            relative = Path(item["path"])
            if not isinstance(item["path"], str) or not item["path"]:
                raise ValueError(f"StaticFiles files[{index}].path must be a non-empty string")
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(
                    f"StaticFiles files[{index}].path must stay under the configured directory"
                )
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = base64.b64decode(item["contents_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"invalid base64 at StaticFiles files[{index}].contents_base64"
                ) from exc
            path.write_bytes(content)
            mtime_seconds = item["mtime_seconds"]
            if isinstance(mtime_seconds, bool) or not isinstance(mtime_seconds, (int, float)):
                raise ValueError(
                    f"StaticFiles files[{index}].mtime_seconds must be a finite number"
                )
            if not math.isfinite(float(mtime_seconds)):
                raise ValueError(
                    f"StaticFiles files[{index}].mtime_seconds must be a finite number"
                )
            os.utime(path, (float(mtime_seconds), float(mtime_seconds)))


def _package_name_parts(value: Any, context: str) -> list[str]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty dotted Python package name")
    parts = value.split(".")
    if any(not part.isascii() or not part.isidentifier() for part in parts):
        raise ValueError(f"{context} must be a dotted Python package name")
    return parts


def _package_static_path(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty relative path")
    parts = value.split("/")
    if (
        Path(value).is_absolute()
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError(f"{context} must be a relative normalized path")
    return tuple(parts)


def _materialize_package_roots(
    package_source_root: Path,
    package_roots: Any,
) -> tuple[list[tuple[str, str]], set[str]]:
    if not isinstance(package_roots, list) or not package_roots:
        raise ValueError("StaticFiles package_roots must be a non-empty array")

    package_arguments: list[tuple[str, str]] = []
    module_prefixes: set[str] = set()
    package_names: set[str] = set()
    for index, package_root in enumerate(package_roots):
        context = f"StaticFiles package_roots[{index}]"
        package_root = _exact_object(
            package_root,
            {"name", "statics_dir", "spec_kind"},
            context,
        )
        name = package_root["name"]
        name_parts = _package_name_parts(name, f"{context}.name")
        if name in package_names:
            raise ValueError("StaticFiles package_roots names must be unique")
        package_names.add(name)
        _package_static_path(
            package_root["statics_dir"],
            f"{context}.statics_dir",
        )
        spec_kind = package_root["spec_kind"]
        if spec_kind not in {"missing", "namespace", "regular"}:
            raise ValueError(f"{context}.spec_kind must be missing, namespace, or regular")

        if spec_kind == "missing":
            # Keep any dotted parent importable so find_spec() returns None for
            # the selected leaf instead of raising while resolving its parent.
            parent_parts = name_parts[:-1]
        elif spec_kind == "namespace":
            parent_parts = name_parts
        else:
            parent_parts = name_parts

        for depth in range(1, len(parent_parts) + 1):
            parent_path = package_source_root.joinpath(*parent_parts[:depth])
            parent_path.mkdir(parents=True, exist_ok=True)
            if spec_kind != "namespace":
                (parent_path / "__init__.py").touch(exist_ok=True)

        package_arguments.append((name, package_root["statics_dir"]))
        module_prefixes.update(
            ".".join(name_parts[:depth]) for depth in range(1, len(name_parts) + 1)
        )

    return package_arguments, module_prefixes


def _construct_static_files(
    case: dict[str, Any],
    static_files_type: Any,
    configured_directory: Any,
) -> Any:
    constructor_arguments = {
        "directory": configured_directory,
        "html": case["html"],
        "check_dir": case["check_dir"],
        "follow_symlink": case["follow_symlink"],
    }
    if "package_roots" not in case:
        return static_files_type(**constructor_arguments)

    with tempfile.TemporaryDirectory(prefix="starlette-staticfiles-package-roots-") as root:
        package_source_root = Path(root)
        package_arguments, module_prefixes = _materialize_package_roots(
            package_source_root,
            case["package_roots"],
        )
        package_source = str(package_source_root)
        previously_loaded_modules = set(sys.modules)
        importlib.invalidate_caches()
        sys.path.insert(0, package_source)
        try:
            return static_files_type(
                **constructor_arguments,
                packages=package_arguments,
            )
        finally:
            if package_source in sys.path:
                sys.path.remove(package_source)
            for module_name in module_prefixes:
                if module_name not in previously_loaded_modules:
                    sys.modules.pop(module_name, None)
            importlib.invalidate_caches()


def _instrument_check_config(application: Any) -> tuple[Callable[..., Any], list[int]]:
    application_type = type(application)
    original = application_type.check_config
    count = [0]

    async def observed(instance: Any) -> None:
        if instance is application:
            count[0] += 1
        await original(instance)

    application_type.check_config = observed
    return original, count


def _restore_check_config(application: Any, original: Callable[..., Any]) -> None:
    type(application).check_config = original


def _run_call(
    application: Any,
    call: dict[str, Any],
    call_index: int,
    *,
    make_scope: Callable[[dict[str, Any]], dict[str, Any]],
    canonical_message: Callable[[dict[str, Any]], dict[str, Any]],
    check_config_count: list[int],
) -> dict[str, Any]:
    if call == {"kind": "direct-check-config"}:
        checked_before = bool(application.config_checked)
        calls_before = check_config_count[0]
        error = None
        try:
            asyncio.run(application.check_config())
        except Exception as exc:
            error = _error_observation(exc, "check-config")
        return {
            "action": "direct-check-config",
            "config_checked_before": checked_before,
            "config_checked_after": bool(application.config_checked),
            "check_config_calls_before": calls_before,
            "check_config_calls_after": check_config_count[0],
            "asgi_events": [],
            "error": error,
        }

    call = _exact_object(call, {"scope", "incoming", "send"}, f"StaticFiles calls[{call_index}]")
    if not isinstance(call["incoming"], list):
        raise ValueError(f"StaticFiles calls[{call_index}].incoming must be an array")
    send_spec = _exact_object(call["send"], {"kind"}, f"StaticFiles calls[{call_index}].send")
    if send_spec["kind"] != "capture-asgi-send":
        raise ValueError("StaticFiles configuration-check send must capture ASGI events")

    scope = make_scope(call["scope"])
    incoming = list(call["incoming"])
    incoming_index = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal incoming_index
        if incoming_index < len(incoming):
            message = incoming[incoming_index]
            incoming_index += 1
            if not isinstance(message, dict):
                raise ValueError("StaticFiles incoming messages must be objects")
            return dict(message)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    checked_before = bool(application.config_checked)
    calls_before = check_config_count[0]
    error = None
    try:
        asyncio.run(application(scope, receive, send))
    except Exception as exc:
        error = _error_observation(exc, "asgi-call")
    events = [canonical_message(message) for message in sent]
    return {
        "config_checked_before": checked_before,
        "config_checked_after": bool(application.config_checked),
        "check_config_calls_before": calls_before,
        "check_config_calls_after": check_config_count[0],
        "asgi_events": events,
        "error": error,
    }


def run_static_files_configuration_case(
    case: dict[str, Any],
    static_files_type: Any,
    *,
    make_scope: Callable[[dict[str, Any]], dict[str, Any]],
    canonical_message: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Build stable input-defined filesystem state and observe construction and ASGI calls."""
    case_fields = {
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "directory_path",
        "directory_kind",
        "root_file_contents_base64",
        "files",
        "html",
        "check_dir",
        "follow_symlink",
        "calls",
        "observations",
    }
    has_pathlike = "directory_pathlike" in case
    if has_pathlike:
        case_fields.add("directory_pathlike")
    has_package_roots = "package_roots" in case
    if has_package_roots:
        case_fields.add("package_roots")
    _exact_object(
        case,
        case_fields,
        "StaticFiles configuration-check case",
    )
    if (
        case["surface"] != STATIC_FILES_SURFACE
        or case["operation"] != STATIC_FILES_CONFIGURATION_OPERATION
    ):
        raise ValueError(
            "workflow is outside the declared StaticFiles configuration-check operation"
        )
    if case["observations"] != [STATIC_FILES_CONFIGURATION_STEP]:
        raise ValueError(
            "StaticFiles configuration-check observations must select configuration-check"
        )
    if case["assets"] != []:
        raise ValueError("StaticFiles configuration-check cases do not use package assets")
    if not isinstance(case["calls"], list):
        raise ValueError("StaticFiles configuration-check calls must be an array")
    if not isinstance(case["html"], bool) or not isinstance(case["check_dir"], bool):
        raise ValueError("StaticFiles html and check_dir must be boolean")
    if not isinstance(case["follow_symlink"], bool):
        raise ValueError("StaticFiles follow_symlink must be boolean")

    directory = _configuration_path(case["directory_path"])
    directory_pathlike = None
    configured_directory: Any = directory
    if has_pathlike:
        pathlike_spec = _exact_object(
            case["directory_pathlike"],
            {"display"},
            "StaticFiles directory_pathlike",
        )
        if not isinstance(pathlike_spec["display"], str):
            raise ValueError("StaticFiles directory_pathlike.display must be a string")
        directory_pathlike = _InputDisplayPathLike(directory, pathlike_spec["display"])
        configured_directory = directory_pathlike
    observation = {
        "config_checked_after_construction": None,
        "check_config_calls_after_construction": None,
        "calls": [],
        "config_checked_final": None,
        "constructor_error": None,
        "directory_pathlike_calls": None,
    }
    try:
        _prepare_filesystem(case, directory)
        try:
            application = _construct_static_files(
                case,
                static_files_type,
                configured_directory,
            )
        except Exception as exc:
            observation["constructor_error"] = _error_observation(exc, "constructor")
            if case["calls"]:
                raise ValueError(
                    "StaticFiles constructor failure inputs must not declare ASGI calls"
                ) from exc
        else:
            observation["config_checked_after_construction"] = bool(application.config_checked)
            observation["check_config_calls_after_construction"] = 0
            original_check_config, call_count = _instrument_check_config(application)
            try:
                for index, call in enumerate(case["calls"]):
                    observation["calls"].append(
                        _run_call(
                            application,
                            call,
                            index,
                            make_scope=make_scope,
                            canonical_message=canonical_message,
                            check_config_count=call_count,
                        )
                    )
                observation["config_checked_final"] = bool(application.config_checked)
            finally:
                _restore_check_config(application, original_check_config)
        if directory_pathlike is not None:
            observation["directory_pathlike_calls"] = {
                "fspath": directory_pathlike.fspath_calls,
                "str": directory_pathlike.str_calls,
            }
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [
                {
                    "step_id": STATIC_FILES_CONFIGURATION_STEP,
                    "status": "ok",
                    "value": observation,
                }
            ],
        }
    finally:
        _remove_path(directory)
