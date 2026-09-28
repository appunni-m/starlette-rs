"""Run one input-only workload from the pinned upstream Starlette benchmark suite.

The worker is deliberately a one-workload, one-process program.  It reads one JSON
request from stdin and writes one JSON result to stdout.  Example request::

    {
      "schema": "starlette-rs-upstream-benchmark-worker-request@1",
      "subject_id": "starlette-python",
      "mode": "probe",
      "workload": { ... one descriptor from
        build/parity/inputs/benchmark/starlette-upstream-workloads.json ... },
      "expected_observation": null
    }

For ``measure``, ``expected_observation`` is the canonical observation returned by
the source probe.  The worker re-probes the selected subject and checks exact
observation and input-relation parity before timing.  The parent process probes
both subjects and performs the source/target comparison; this worker never reads
expected outputs from the fixture.  ``STARLETTE_ORACLE_ROOT`` selects the pinned
source checkout for ``starlette-python``.  ``python-package-cpython312`` imports
the package installed in the current isolated interpreter.

All byte stimuli come from the descriptor.  GZip generator names identify the
deterministic generators used by Starlette's upstream benchmark; message bodies,
length headers, scopes, middleware call arguments, and sample counts are resolved
from the supplied JSON.  Relation selectors are assertions about those inputs,
not fixture-provided outputs.

The payload generator recipes are adapted from Starlette's
``benchmarks/gzip_benchmark.py`` (Copyright © 2018 Encode OSS Ltd., BSD-3-Clause);
the repository's ``THIRD_PARTY_NOTICES.md`` points to the preserved license text.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from scripts.parity.upstream_benchmark_contract import live_relation_kinds

REQUEST_SCHEMA = "starlette-rs-upstream-benchmark-worker-request@1"
RESULT_SCHEMA = "starlette-rs-upstream-benchmark-worker-result@1"
SOURCE_REVISION = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"
SOURCE_VERSION = "1.6.0"


class UnsupportedWorkload(RuntimeError):
    """The selected subject does not expose an operation required by this input."""


def _strict_object(value: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{context} must contain exactly {sorted(expected)}")
    return value


def _validate_observation_declaration(workload: dict[str, Any], input_kind: str) -> None:
    observations = workload["observations"]
    expected_keys = {"events", "input_relations"}
    if input_kind == "gzip_responsiveness":
        expected_keys.add("no_pending_large_task_assertion")
    if not isinstance(observations, dict) or set(observations) != expected_keys:
        raise ValueError(f"observations must contain exactly {sorted(expected_keys)}")
    event_spec = observations["events"]
    event_keys = {"selector", "ordering", "comparison", "unordered_header_token_order"}
    if input_kind == "gzip_responsiveness":
        event_keys.add("streams")
    if not isinstance(event_spec, dict) or set(event_spec) != event_keys:
        raise ValueError(f"observations.events must contain exactly {sorted(event_keys)}")
    if (
        event_spec["selector"] != "all_asgi_send_events"
        or event_spec["ordering"] != "exact"
        or event_spec["comparison"] != "exact"
        or not isinstance(event_spec["unordered_header_token_order"], list)
        or any(not isinstance(item, str) for item in event_spec["unordered_header_token_order"])
    ):
        raise ValueError("worker supports exact ordered ASGI send-event observations only")
    if any(item.lower() != "allow" for item in event_spec["unordered_header_token_order"]):
        raise ValueError("only the reusable Allow-header token-order normalization is supported")
    if input_kind == "gzip_responsiveness":
        if (
            event_spec["streams"] != ["large", "tiny"]
            or observations["no_pending_large_task_assertion"] is not True
        ):
            raise ValueError(
                "responsiveness observations must select large and tiny streams without a pending assertion"
            )
    if not isinstance(observations["input_relations"], list):
        raise ValueError("observations.input_relations must be an array")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode_base64(value: Any, context: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{context} must be a base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid base64 at {context}") from exc


def _canonical_bytes(value: Any, context: str) -> bytes:
    """Decode the byte representations admitted by the input-only descriptor."""
    if isinstance(value, str):
        return value.encode("utf-8")
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a UTF-8 string or byte descriptor")
    if set(value) == {"bytes_hex"}:
        if not isinstance(value["bytes_hex"], str):
            raise ValueError(f"{context}.bytes_hex must be a string")
        try:
            return bytes.fromhex(value["bytes_hex"])
        except ValueError as exc:
            raise ValueError(f"invalid hexadecimal bytes at {context}") from exc
    if set(value) == {"bytes_base64"}:
        return _decode_base64(value["bytes_base64"], context)
    if set(value) == {"utf8"} and isinstance(value["utf8"], str):
        return value["utf8"].encode("utf-8")
    if set(value) == {"base64"}:
        return _decode_base64(value["base64"], context)
    raise ValueError(f"{context} has an unsupported byte representation")


def _make_json_payload(size: int) -> bytes:
    """Build the deterministic, fixed-size JSON payload used upstream."""
    if size < 64:
        raise ValueError("JSON payload size is too small for the declared generator")
    prefix = b'{"requests":['
    padding_prefix = b'],"padding":"'
    suffix = b'"}'
    output = bytearray(prefix)
    index = 0
    while True:
        row = json.dumps(
            {
                "id": index,
                "timestamp": f"2026-08-04T12:{index % 60:02d}:{index * 7 % 60:02d}.{index * 997 % 1000:03d}Z",
                "method": ("GET", "POST", "PATCH", "DELETE")[index % 4],
                "path": f"/api/v1/projects/{index % 1_009}/events/{index * 17 % 65_537}",
                "status": (200, 201, 204, 400, 404, 409, 422, 500)[index % 8],
                "duration_ms": round((index * 37 % 10_000) / 100, 2),
                "request_id": f"{index * 0x9E3779B97F4A7C15 % (1 << 128):032x}",
                "message": ("request completed", "validation failed", "resource updated")[
                    index % 3
                ],
            },
            separators=(",", ":"),
        ).encode("ascii")
        separator = b"," if index else b""
        required_tail = len(padding_prefix) + len(suffix)
        if len(output) + len(separator) + len(row) + required_tail > size:
            break
        output.extend(separator)
        output.extend(row)
        index += 1
    output.extend(padding_prefix)
    output.extend(b"x" * (size - len(output) - len(suffix)))
    output.extend(suffix)
    if len(output) != size:
        raise RuntimeError("JSON generator failed to produce its declared size")
    return bytes(output)


def _generator_bytes(spec: Any, context: str = "generator") -> bytes:
    try:
        serialized = json.dumps(
            spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} cannot be represented as canonical JSON") from exc
    return _generator_bytes_cached(serialized)


@lru_cache(maxsize=32)
def _generator_bytes_cached(serialized: str) -> bytes:
    return _generate_generator_bytes(json.loads(serialized))


def _generate_generator_bytes(spec: Any) -> bytes:
    if not isinstance(spec, dict) or set(spec) not in (
        {"name", "parameters"},
        {"name", "parameters", "source_constants"},
    ):
        raise ValueError(
            "generator must contain name, parameters, and only declared source constants"
        )
    name = spec["name"]
    parameters = spec["parameters"]
    if not isinstance(name, str) or not isinstance(parameters, dict):
        raise ValueError("generator name and parameters are malformed")
    source_constants = spec.get("source_constants")
    if name == "literal_ascii":
        if (
            source_constants is not None
            or set(parameters) != {"value_ascii"}
            or not isinstance(parameters["value_ascii"], str)
        ):
            raise ValueError("literal_ascii parameters must contain value_ascii")
        try:
            return parameters["value_ascii"].encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("literal_ascii parameters.value_ascii must be ASCII") from exc
    if name in {"make_json_payload", "make_text_payload", "shake_256_digest", "repeat_byte"}:
        allowed = {"size_bytes"}
        if name == "shake_256_digest":
            allowed.add("seed_ascii")
        if name == "repeat_byte":
            allowed.add("byte_ascii")
        if set(parameters) != allowed:
            raise ValueError(
                f"generator parameters for {name} must contain exactly {sorted(allowed)}"
            )
        size = parameters["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("generator parameters.size_bytes must be a non-negative integer")
        if name == "make_json_payload":
            if source_constants is not None:
                raise ValueError("make_json_payload has no source_constants")
            return _make_json_payload(size)
        if name == "make_text_payload":
            if not isinstance(source_constants, dict) or set(source_constants) != {
                "paragraph_ascii"
            }:
                raise ValueError("make_text_payload source_constants must declare paragraph_ascii")
            paragraph = source_constants["paragraph_ascii"]
            if not isinstance(paragraph, str):
                raise ValueError("make_text_payload paragraph_ascii must be a string")
            try:
                paragraph_bytes = paragraph.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("make_text_payload paragraph_ascii must be ASCII") from exc
            if not paragraph_bytes:
                raise ValueError("make_text_payload paragraph_ascii must be non-empty")
            if size == 0:
                return b""
            return (paragraph_bytes * (size // len(paragraph_bytes) + 1))[:size]
        if name == "shake_256_digest":
            if source_constants is not None:
                raise ValueError("shake_256_digest has no source_constants")
            seed = parameters["seed_ascii"]
            if not isinstance(seed, str):
                raise ValueError("shake_256_digest seed_ascii must be a string")
            try:
                seed_bytes = seed.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("shake_256_digest seed_ascii must be ASCII") from exc
            return hashlib.shake_256(seed_bytes).digest(size)
        byte_value = parameters["byte_ascii"]
        if source_constants is not None:
            raise ValueError("repeat_byte has no source_constants")
        if not isinstance(byte_value, str) or len(byte_value.encode("ascii", errors="strict")) != 1:
            raise ValueError("repeat_byte byte_ascii must be one ASCII character")
        return byte_value.encode("ascii") * size
    raise ValueError(f"unsupported deterministic generator: {name!r}")


def _body_bytes(spec: Any, context: str) -> bytes:
    if isinstance(spec, dict) and set(spec) == {"generator"}:
        return _generator_bytes(spec["generator"], f"{context}.generator")
    return _canonical_bytes(spec, context)


def _header_bytes(header: Any, context: str, body_size: int | None = None) -> tuple[bytes, bytes]:
    if not isinstance(header, dict):
        raise ValueError(f"{context} must be an object")
    if set(header) == {"name_ascii", "value_ascii"}:
        name, value = header["name_ascii"], header["value_ascii"]
        if not isinstance(name, str) or not isinstance(value, str):
            raise ValueError(f"{context} ASCII header fields must be strings")
        try:
            return name.encode("ascii"), value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{context} has a non-ASCII field") from exc
    if set(header) == {"name_ascii", "value_from_body_size_bytes"}:
        if (
            not isinstance(header["name_ascii"], str)
            or header["value_from_body_size_bytes"] is not True
        ):
            raise ValueError(f"{context} has an invalid body-size-derived header")
        if body_size is None:
            raise ValueError(f"{context} needs a generated body size")
        try:
            return header["name_ascii"].encode("ascii"), str(body_size).encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{context} has a non-ASCII name") from exc
    if set(header) == {"name_ascii", "value_from_case_body_size_bytes"}:
        if (
            not isinstance(header["name_ascii"], str)
            or header["value_from_case_body_size_bytes"] is not True
        ):
            raise ValueError(f"{context} has an invalid case-body-size-derived header")
        raise ValueError(f"{context} requires its workload case_body_size_bytes")
    if set(header) == {"name_base64", "value_base64"}:
        return (
            _decode_base64(header["name_base64"], f"{context}.name_base64"),
            _decode_base64(header["value_base64"], f"{context}.value_base64"),
        )
    raise ValueError(f"{context} uses an unsupported header representation")


def _materialize_message(spec: Any, context: str) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
        raise ValueError(f"{context} must declare an ASGI event type")
    kind = spec["type"]
    if kind == "http.response.start":
        if set(spec) != {"type", "status", "headers"}:
            raise ValueError(f"{context} response-start fields are malformed")
        headers_spec = spec["headers"]
        if not isinstance(headers_spec, list):
            raise ValueError(f"{context}.headers must be an array")
        # Resolve body-size-derived content length against the declared body input,
        # not against an output or a workload identifier.
        body_size = None
        return {
            "type": kind,
            "status": spec["status"],
            "headers": [
                _header_bytes(item, f"{context}.headers[{index}]", body_size)
                for index, item in enumerate(headers_spec)
            ],
        }
    if kind == "http.response.body":
        allowed = {"type", "body"}
        if "more_body" in spec:
            allowed.add("more_body")
        if set(spec) != allowed:
            raise ValueError(f"{context} response-body fields are malformed")
        body = _body_bytes(spec["body"], f"{context}.body")
        result = {"type": kind, "body": body}
        if "more_body" in spec:
            result["more_body"] = spec["more_body"]
        return result
    if kind == "http.response.pathsend":
        if set(spec) == {"type", "path_utf8"} and isinstance(spec["path_utf8"], str):
            return {"type": kind, "path": spec["path_utf8"]}
        if set(spec) != {"type", "path"} or not isinstance(spec["path"], str):
            raise ValueError(f"{context} pathsend fields are malformed")
        return {"type": kind, "path": spec["path"]}
    raise ValueError(f"{context} has unsupported ASGI event type {kind!r}")


def _materialize_response_messages(
    app_spec: Any, context: str, case_body_size_bytes: int | None = None
) -> list[dict[str, Any]]:
    if not isinstance(app_spec, dict) or set(app_spec) != {"kind", "messages"}:
        raise ValueError(f"{context} must contain kind and messages")
    if app_spec["kind"] != "static_response" or not isinstance(app_spec["messages"], list):
        raise ValueError(f"{context} must be a static_response with message inputs")
    # Resolve the body before derived content-length headers.  The declarative
    # input points body lengths at the response body's generator.
    body_size: int | None = case_body_size_bytes
    for item in app_spec["messages"]:
        if isinstance(item, dict) and item.get("type") == "http.response.body":
            body_size = len(_body_bytes(item.get("body"), f"{context}.body"))
            break
    messages: list[dict[str, Any]] = []
    for index, item in enumerate(app_spec["messages"]):
        if item.get("type") == "http.response.start":
            start = dict(item)
            headers = []
            for header_index, header in enumerate(start.get("headers", [])):
                if (
                    set(header) == {"name_ascii", "value_from_case_body_size_bytes"}
                    and header["value_from_case_body_size_bytes"] is True
                ):
                    if case_body_size_bytes is None:
                        raise ValueError(f"{context} case body size is missing")
                    try:
                        pair = (
                            header["name_ascii"].encode("ascii"),
                            str(case_body_size_bytes).encode("ascii"),
                        )
                    except (AttributeError, UnicodeEncodeError) as exc:
                        raise ValueError(f"{context} has invalid case-body-size header") from exc
                elif set(header) == {"name_ascii", "value_from_body_size_bytes"}:
                    if body_size is None:
                        raise ValueError(f"{context} content length has no response body")
                    pair = _header_bytes(
                        header, f"{context}.messages[{index}].headers[{header_index}]", body_size
                    )
                else:
                    pair = _header_bytes(
                        header, f"{context}.messages[{index}].headers[{header_index}]"
                    )
                headers.append(pair)
            messages.append(
                {"type": "http.response.start", "status": start["status"], "headers": headers}
            )
        else:
            messages.append(_materialize_message(item, f"{context}.messages[{index}]"))
    return messages


def _canonical_event(message: dict[str, Any]) -> dict[str, Any]:
    kind = message["type"]
    if kind == "http.response.start":
        return {
            "type": kind,
            "status": message["status"],
            "headers": [[_b64(name), _b64(value)] for name, value in message["headers"]],
        }
    if kind == "http.response.body":
        event: dict[str, Any] = {
            "type": kind,
            "body": {"encoding": "base64", "data": _b64(message.get("body", b""))},
        }
        if "more_body" in message:
            event["more_body"] = message["more_body"]
        return event
    if kind == "http.response.pathsend":
        return {"type": kind, "path": message["path"]}
    raise ValueError(f"unexpected ASGI send event: {kind!r}")


def _canonical_events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_canonical_event(message) for message in messages]


def _make_scope(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("type"), str):
        raise ValueError("scope must declare its ASGI type")
    scope: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "headers":
            if not isinstance(value, list):
                raise ValueError("scope.headers must be an array")
            headers: list[tuple[bytes, bytes]] = []
            for index, header in enumerate(value):
                if isinstance(header, list) and len(header) == 2:
                    name, header_value = header
                    headers.append(
                        (
                            _canonical_bytes(name, f"scope.headers[{index}].name"),
                            _canonical_bytes(header_value, f"scope.headers[{index}].value"),
                        )
                    )
                else:
                    headers.append(_header_bytes(header, f"scope.headers[{index}]"))
            scope[key] = headers
        elif key == "query_string" or key in {"raw_path", "path_bytes"}:
            scope[key] = _canonical_bytes(value, f"scope.{key}")
        else:
            scope[key] = value
    return scope


def _make_receive(spec: Any) -> Callable[[], Any]:
    if not isinstance(spec, dict) or set(spec) != {"behavior", "message"}:
        raise ValueError("receive input must contain behavior and message")
    if spec["behavior"] != "raise_assertion" or not isinstance(spec["message"], str):
        raise ValueError("receive input must use the declared assertion behavior")

    async def receive() -> dict[str, Any]:
        raise AssertionError(spec["message"])

    return receive


def _clone_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cloned: list[dict[str, Any]] = []
    for message in messages:
        result = dict(message)
        if "headers" in result:
            result["headers"] = list(result["headers"])
        cloned.append(result)
    return cloned


class _StaticResponseApp:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        for message in _clone_messages(self.messages):
            await send(message)


async def _run_asgi(
    app: Any, scope: dict[str, Any], receive: Callable[[], Any]
) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _source_identity(starlette: Any, root: Path) -> dict[str, Any]:
    if Path(starlette.__file__).resolve() != (root / "starlette" / "__init__.py").resolve():
        raise RuntimeError("source worker imported Starlette outside the pinned checkout")
    if starlette.__version__ != SOURCE_VERSION:
        raise RuntimeError(f"expected Starlette {SOURCE_VERSION}, found {starlette.__version__!r}")
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot identify the pinned Starlette source: {exc}") from exc
    if revision != SOURCE_REVISION:
        raise RuntimeError(f"expected source revision {SOURCE_REVISION}, found {revision}")
    requested_revision = os.environ.get("STARLETTE_BENCHMARK_SOURCE_REVISION")
    if requested_revision is not None and requested_revision != revision:
        raise RuntimeError("source revision differs from the benchmark request environment")
    try:
        changed = subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet", "--", "starlette"],
            check=False,
            timeout=10,
        ).returncode
        untracked = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--others",
                "--exclude-standard",
                "starlette",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"cannot verify pinned Starlette package files: {exc}") from exc
    if changed != 0 or untracked:
        raise RuntimeError("the pinned source Starlette package files are modified or untracked")
    return {
        "subject_id": "starlette-python",
        "starlette_version": starlette.__version__,
        "source_revision": revision,
        "module_path": str(Path(starlette.__file__).resolve()),
        "python_executable": str(Path(sys.executable).resolve()),
        "environment_prefix": str(Path(sys.prefix).resolve()),
        "runtime": f"{platform.python_implementation()} {platform.python_version()}",
        "os": platform.platform(),
        "architecture": platform.machine(),
    }


def _installed_target_tree_sha256(
    distribution: importlib.metadata.Distribution,
) -> str:
    digest = hashlib.sha256()
    package_roots = ("starlette/", "starlette_rs_py/")
    files = distribution.files or ()
    included = 0
    for item in sorted(files, key=lambda entry: str(entry)):
        relative = str(item).replace("\\", "/")
        if not relative.startswith(package_roots):
            continue
        path = Path(distribution.locate_file(item))
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        included += 1
    if included == 0:
        raise RuntimeError("installed starlette-rs-py has no verifiable package files")
    return digest.hexdigest()


def _load_subject(subject_id: str) -> tuple[Any, dict[str, Any]]:
    if subject_id == "starlette-python":
        root_value = os.environ.get("STARLETTE_ORACLE_ROOT")
        if not root_value:
            raise RuntimeError("source worker requires STARLETTE_ORACLE_ROOT")
        root = Path(root_value).resolve()
        if not (root / "starlette" / "__init__.py").is_file():
            raise RuntimeError(f"pinned Starlette source was not found under {root}")
        sys.path.insert(0, str(root))
        starlette = importlib.import_module("starlette")
        identity = _source_identity(starlette, root)
    elif subject_id == "python-package-cpython312":
        starlette = importlib.import_module("starlette")
        module_path = Path(starlette.__file__).resolve()
        prefix = Path(sys.prefix).resolve()
        if not module_path.is_relative_to(prefix):
            raise RuntimeError(
                f"target worker imported Starlette outside its environment: {module_path}"
            )
        from starlette_rs_py import _core

        core_path = Path(_core.__file__).resolve()
        if not core_path.is_relative_to(prefix):
            raise RuntimeError(f"target extension loaded outside its environment: {core_path}")
        distribution = importlib.metadata.distribution("starlette-rs-py")
        package_version = distribution.version
        if starlette.__version__ != package_version:
            raise RuntimeError("target package and Starlette module versions differ")
        target_tree_sha256 = _installed_target_tree_sha256(distribution)
        expected_tree_sha256 = os.environ.get("STARLETTE_BENCHMARK_TARGET_TREE_SHA256")
        if target_tree_sha256 != expected_tree_sha256:
            raise RuntimeError("installed package tree differs from the fresh parity-gate identity")
        identity = {
            "subject_id": subject_id,
            "starlette_version": starlette.__version__,
            "package_version": package_version,
            "module_path": str(module_path),
            "core_extension_path": str(core_path),
            "python_executable": str(Path(sys.executable).resolve()),
            "environment_prefix": str(prefix),
            "runtime": f"{platform.python_implementation()} {platform.python_version()}",
            "os": platform.platform(),
            "architecture": platform.machine(),
            "target_tree_sha256": target_tree_sha256,
            "wheel_sha256": os.environ.get("STARLETTE_BENCHMARK_WHEEL_SHA256"),
        }
    else:
        raise ValueError(f"unsupported benchmark subject: {subject_id!r}")

    capabilities: dict[str, Any] = {}
    try:
        routing = importlib.import_module("starlette.routing")
        router_type = routing.Router
        capabilities["router_instance_is_asgi_callable"] = callable(router_type(routes=[]))
    except (ImportError, AttributeError, ModuleNotFoundError):
        capabilities["router_instance_is_asgi_callable"] = False
    try:
        gzip_module = importlib.import_module("starlette.middleware.gzip")
        capabilities["gzip_middleware_available"] = callable(
            getattr(gzip_module, "GZipMiddleware", None)
        )
    except (ImportError, AttributeError, ModuleNotFoundError):
        capabilities["gzip_middleware_available"] = False
    identity["capabilities"] = capabilities
    return starlette, identity


def _make_router_app(
    input_spec: dict[str, Any], starlette: Any
) -> tuple[Callable[[], Any], Callable[[], Any]]:
    router_spec = input_spec["router"]
    if not isinstance(router_spec, dict) or set(router_spec) != {
        "group_expansion",
        "route_templates",
        "endpoint",
    }:
        raise ValueError("router input must contain group_expansion, route_templates, and endpoint")
    expansion = router_spec["group_expansion"]
    if not isinstance(expansion, dict) or set(expansion) != {"variable", "start", "count"}:
        raise ValueError("router group expansion is malformed")
    variable, start, count = expansion["variable"], expansion["start"], expansion["count"]
    templates = router_spec["route_templates"]
    if (
        not isinstance(variable, str)
        or not variable
        or not isinstance(start, int)
        or not isinstance(count, int)
    ):
        raise ValueError("router group expansion bounds are malformed")
    if not isinstance(templates, list) or not templates:
        raise ValueError("router route_templates must be a non-empty array")
    endpoint_spec = router_spec["endpoint"]
    if not isinstance(endpoint_spec, dict) or set(endpoint_spec) != {"response_class", "body_utf8"}:
        raise ValueError("router endpoint descriptor is malformed")
    if endpoint_spec["response_class"] != "starlette.responses.PlainTextResponse" or not isinstance(
        endpoint_spec["body_utf8"], str
    ):
        raise ValueError("router endpoint must use the declared PlainTextResponse input")

    routing = importlib.import_module("starlette.routing")
    responses = importlib.import_module("starlette.responses")
    Route = routing.Route
    Router = routing.Router
    response_type = getattr(responses, endpoint_spec["response_class"].rsplit(".", 1)[-1])
    routes = []

    async def endpoint(_request: Any) -> Any:
        return response_type(endpoint_spec["body_utf8"])

    expanded_paths: list[tuple[str, list[str]]] = []
    for group_index in range(start, start + count):
        for template_index, route_template in enumerate(templates):
            if not isinstance(route_template, dict) or set(route_template) != {"path", "methods"}:
                raise ValueError(f"router route template {template_index} is malformed")
            path, methods = route_template["path"], route_template["methods"]
            if (
                not isinstance(path, str)
                or not isinstance(methods, list)
                or any(not isinstance(method, str) for method in methods)
            ):
                raise ValueError(
                    f"router route template {template_index} has invalid path or methods"
                )
            expanded = path.replace("{" + variable + "}", str(group_index))
            expanded_paths.append((expanded, methods))
            routes.append(Route(expanded, endpoint, methods=methods))
    router = Router(routes=routes)
    if not callable(router):
        raise UnsupportedWorkload("the selected Router instance is not an ASGI callable")
    receive = _make_receive(input_spec["receive"])

    async def invoke() -> list[dict[str, Any]]:
        scope = _make_scope(input_spec["scope"])
        return await _run_asgi(router, scope, receive)

    return invoke, receive


def _response_apps(
    input_spec: dict[str, Any],
) -> tuple[dict[str, _StaticResponseApp], dict[str, list[dict[str, Any]]]]:
    apps: dict[str, _StaticResponseApp] = {}
    messages: dict[str, list[dict[str, Any]]] = {}
    for key, value in input_spec.items():
        if key == "response_app" or key.endswith("_response_app"):
            materialized = _materialize_response_messages(
                value, f"input.{key}", input_spec.get("case_body_size_bytes")
            )
            apps[key] = _StaticResponseApp(materialized)
            messages[key] = materialized
    if not apps:
        raise ValueError("GZip input must declare a static response app")
    return apps, messages


def _make_middleware(spec: Any, apps: dict[str, _StaticResponseApp]) -> Any:
    if not isinstance(spec, dict) or set(spec) != {
        "class",
        "call_arguments",
        "effective_parameters",
    }:
        raise ValueError("GZip middleware descriptor is malformed")
    if spec["class"] != "starlette.middleware.gzip.GZipMiddleware":
        raise ValueError("GZip middleware class differs from the pinned benchmark contract")
    call = spec["call_arguments"]
    if not isinstance(call, dict) or set(call) != {"positional", "keyword"}:
        raise ValueError("GZip call_arguments must contain positional and keyword")
    positional, keyword = call["positional"], call["keyword"]
    if not isinstance(positional, list) or not isinstance(keyword, dict):
        raise ValueError("GZip call arguments are malformed")

    def resolve(value: Any) -> Any:
        if isinstance(value, dict) and set(value) == {"app_ref"}:
            app_ref = value["app_ref"]
            if not isinstance(app_ref, str) or app_ref not in apps:
                raise ValueError(f"GZip app reference does not resolve: {app_ref!r}")
            return apps[app_ref]
        return value

    resolved_positional = [resolve(value) for value in positional]
    resolved_keyword = {key: resolve(value) for key, value in keyword.items()}
    try:
        module = importlib.import_module("starlette.middleware.gzip")
        middleware_type = module.GZipMiddleware
    except (ImportError, AttributeError, ModuleNotFoundError) as exc:
        raise UnsupportedWorkload(
            "the selected package has no GZipMiddleware implementation"
        ) from exc
    try:
        return middleware_type(*resolved_positional, **resolved_keyword)
    except (TypeError, ValueError) as exc:
        raise UnsupportedWorkload(
            f"GZipMiddleware does not accept the declared constructor: {exc}"
        ) from exc


def _middleware_instances(
    input_spec: dict[str, Any], apps: dict[str, _StaticResponseApp]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in input_spec.items():
        if key == "middleware" or key.endswith("_middleware"):
            result[key] = _make_middleware(value, apps)
    if not result:
        raise ValueError("GZip input must declare middleware")
    return result


def _body_from_input_path(input_spec: dict[str, Any], path: str) -> bytes:
    if not isinstance(path, str) or not path.startswith("input."):
        raise ValueError("input relation path must begin with input.")
    value: Any = input_spec
    for component in path.removeprefix("input.").split("."):
        if not isinstance(value, dict) or component not in value:
            raise ValueError(f"input relation path does not exist: {path}")
        value = value[component]
    return _generator_bytes(value, path)


def _events_from_input_path(
    path: str,
    input_spec: dict[str, Any],
    response_messages: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if path.startswith("input."):
        pieces = path.removeprefix("input.").split(".")
        if len(pieces) == 2 and pieces[-1] == "messages" and pieces[0] in response_messages:
            return _canonical_events(response_messages[pieces[0]])
    raise ValueError(f"unsupported input event relation path: {path}")


def _events_body(events: list[dict[str, Any]], event_index: int, field: str) -> bytes:
    if (
        not isinstance(event_index, int)
        or isinstance(event_index, bool)
        or not 0 <= event_index < len(events)
    ):
        raise ValueError("input relation output_event_index is outside the observation")
    event = events[event_index]
    if field != "body" or "body" not in event:
        raise ValueError("input relation must select a response body field")
    body = event.get("body")
    if (
        not isinstance(body, dict)
        or set(body) != {"encoding", "data"}
        or body["encoding"] != "base64"
    ):
        raise ValueError("observed response body is not canonical base64")
    return _decode_base64(body["data"], "observed response body")


def _http_response_shape(events: Any, context: str) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Decode the canonical two-event HTTP response shape used by these workloads."""
    if not isinstance(events, list) or len(events) != 2:
        raise ValueError(f"{context} must contain exactly response-start and response-body events")
    start, body_event = events
    if (
        not isinstance(start, dict)
        or set(start) != {"type", "status", "headers"}
        or start["type"] != "http.response.start"
        or not isinstance(start["status"], int)
        or isinstance(start["status"], bool)
        or not 100 <= start["status"] <= 599
        or not isinstance(start["headers"], list)
    ):
        raise ValueError(f"{context} has a malformed response-start event")
    headers: list[tuple[bytes, bytes]] = []
    for index, pair in enumerate(start["headers"]):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"{context} header {index} is malformed")
        name = _decode_base64(pair[0], f"{context}.headers[{index}].name")
        value = _decode_base64(pair[1], f"{context}.headers[{index}].value")
        if not name:
            raise ValueError(f"{context} header {index} has an empty name")
        headers.append((name.lower(), value))
    if (
        not isinstance(body_event, dict)
        or body_event.get("type") != "http.response.body"
        or set(body_event) not in ({"type", "body"}, {"type", "body", "more_body"})
    ):
        raise ValueError(f"{context} has a malformed response-body event")
    if "more_body" in body_event and type(body_event["more_body"]) is not bool:
        raise ValueError(f"{context} body more_body flag must be boolean")
    body = body_event.get("body")
    if (
        not isinstance(body, dict)
        or set(body) != {"encoding", "data"}
        or body["encoding"] != "base64"
    ):
        raise ValueError(f"{context} body is not canonical base64")
    return (
        start["status"],
        headers,
        _decode_base64(body["data"], f"{context}.body"),
    )


def _header_values(headers: list[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    return [value for header_name, value in headers if header_name == name]


def _router_expected_status(input_spec: dict[str, Any]) -> int:
    """Derive the Router status from its declared path templates and request."""
    router = input_spec.get("router")
    scope = input_spec.get("scope")
    if not isinstance(router, dict) or not isinstance(scope, dict):
        raise ValueError("router input must contain router and scope objects")
    expansion = router.get("group_expansion")
    templates = router.get("route_templates")
    if (
        not isinstance(expansion, dict)
        or not isinstance(templates, list)
        or not isinstance(expansion.get("variable"), str)
        or not isinstance(expansion.get("start"), int)
        or isinstance(expansion.get("start"), bool)
        or not isinstance(expansion.get("count"), int)
        or isinstance(expansion.get("count"), bool)
        or not isinstance(scope.get("method"), str)
        or not isinstance(scope.get("path"), str)
    ):
        raise ValueError("router templates or request scope are malformed")
    variable = expansion["variable"]
    request_method = scope["method"]
    request_path = scope["path"]
    path_matched = False
    for group in range(expansion["start"], expansion["start"] + expansion["count"]):
        for template in templates:
            if not isinstance(template, dict) or set(template) != {"path", "methods"}:
                raise ValueError("router route template is malformed")
            path_template, methods = template["path"], template["methods"]
            if (
                not isinstance(path_template, str)
                or not isinstance(methods, list)
                or any(not isinstance(method, str) for method in methods)
            ):
                raise ValueError("router route template path or methods are malformed")
            expanded = path_template.replace("{" + variable + "}", str(group))
            parts: list[str] = []
            offset = 0
            for match in re.finditer(
                r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_][A-Za-z0-9_]*))?\}", expanded
            ):
                parts.append(re.escape(expanded[offset : match.start()]))
                converter = match.group(2)
                if converter is None:
                    parts.append("[^/]+")
                elif converter == "int":
                    parts.append(r"\d+")
                else:
                    raise ValueError(f"unsupported route converter {converter!r}")
                offset = match.end()
            parts.append(re.escape(expanded[offset:]))
            if re.fullmatch("".join(parts), request_path):
                path_matched = True
                if request_method in methods:
                    return 200
    return 405 if path_matched else 404


def _check_router_status_and_shape(input_spec: dict[str, Any], observation: dict[str, Any]) -> bool:
    try:
        status, _headers, body = _http_response_shape(observation.get("events"), "Router response")
        expected_status = _router_expected_status(input_spec)
        if status != expected_status:
            return False
        endpoint = input_spec["router"]["endpoint"]
        if expected_status == 200:
            return body == endpoint["body_utf8"].encode("utf-8")
        return bool(body)
    except (KeyError, TypeError, ValueError):
        return False


def _input_response_status(response_messages: dict[str, list[dict[str, Any]]], key: str) -> int:
    messages = response_messages.get(key)
    if (
        not isinstance(messages, list)
        or not messages
        or messages[0].get("type") != "http.response.start"
    ):
        raise ValueError(f"input response app {key!r} has no response-start message")
    status = messages[0].get("status")
    if not isinstance(status, int) or isinstance(status, bool):
        raise ValueError(f"input response app {key!r} has an invalid status")
    return status


def _check_gzip_compression_shape(
    observation: dict[str, Any],
    response_messages: dict[str, list[dict[str, Any]]],
) -> bool:
    try:
        status, headers, _body = _http_response_shape(observation.get("events"), "GZip response")
        return status == _input_response_status(
            response_messages, "response_app"
        ) and b"gzip" in _header_values(headers, b"content-encoding")
    except (KeyError, TypeError, ValueError):
        return False


def _check_gzip_responsiveness_shape(
    observation: dict[str, Any], response_messages: dict[str, list[dict[str, Any]]]
) -> bool:
    try:
        large_status, large_headers, _large_body = _http_response_shape(
            observation.get("large_events"), "GZip responsiveness large response"
        )
        tiny_status, tiny_headers, _tiny_body = _http_response_shape(
            observation.get("tiny_events"), "GZip responsiveness tiny response"
        )
        return (
            large_status == _input_response_status(response_messages, "large_response_app")
            and b"gzip" in _header_values(large_headers, b"content-encoding")
            and tiny_status == _input_response_status(response_messages, "tiny_response_app")
            and b"gzip" not in _header_values(tiny_headers, b"content-encoding")
        )
    except (KeyError, TypeError, ValueError):
        return False


def _validate_relations(
    input_spec: dict[str, Any],
    workload: dict[str, Any],
    observation: dict[str, Any],
    response_messages: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    observations = workload["observations"]
    if not isinstance(observations, dict) or not isinstance(
        observations.get("input_relations"), list
    ):
        raise ValueError("observations.input_relations must be an array")
    results: list[dict[str, str]] = []
    for relation in observations["input_relations"]:
        if not isinstance(relation, dict) or not isinstance(relation.get("kind"), str):
            raise ValueError("each input relation must declare a kind")
        kind = relation["kind"]
        if kind == "gzip_decompress_output_body_equals_input_body":
            stream = relation.get("stream")
            default_output = {"large": "large_events", "tiny": "tiny_events"}.get(stream, "events")
            output_path = relation.get("output_path", default_output)
            if output_path not in observation or not isinstance(observation[output_path], list):
                raise ValueError(f"relation {kind} output_path is absent from observation")
            compressed = _events_body(
                observation[output_path], relation["output_event_index"], relation["output_field"]
            )
            expected = _body_from_input_path(input_spec, relation["input_path"])
            passed = gzip.decompress(compressed) == expected
        elif kind == "output_events_equal_input_response_messages":
            stream = relation.get("stream")
            default_output = {"large": "large_events", "tiny": "tiny_events"}.get(stream, "events")
            actual_path = relation.get("output_path", default_output)
            actual = observation.get(actual_path)
            expected = _events_from_input_path(
                relation["input_path"], input_spec, response_messages
            )
            passed = actual == expected
        else:
            raise ValueError(f"unsupported input relation kind: {kind!r}")
        results.append({"relation": kind, "status": "pass" if passed else "failed"})
    live_checks = {
        "router_status_and_response_shape_matches_input": lambda: _check_router_status_and_shape(
            input_spec, observation
        ),
        "gzip_compression_headers_and_event_shape": lambda: _check_gzip_compression_shape(
            observation, response_messages
        ),
        "gzip_responsiveness_headers_and_event_shape": lambda: _check_gzip_responsiveness_shape(
            observation, response_messages
        ),
    }
    for kind in live_relation_kinds(input_spec["kind"]):
        try:
            passed = live_checks[kind]()
        except KeyError as exc:
            raise ValueError(f"unsupported live relation kind: {kind!r}") from exc
        results.append({"relation": kind, "status": "pass" if passed else "failed"})
    return results


def _measurement_counts(measurement: Any) -> tuple[int, int, int]:
    if not isinstance(measurement, dict) or not isinstance(measurement.get("runner_policy"), dict):
        raise ValueError("measurement.runner_policy must be an object")
    policy = _strict_object(
        measurement["runner_policy"],
        {"warmup_iterations", "samples", "iterations_per_sample", "sample_statistic"},
        "measurement runner policy",
    )
    warmups = policy["warmup_iterations"]
    samples = policy["samples"]
    iterations = policy["iterations_per_sample"]
    for key, value in (
        ("warmup_iterations", warmups),
        ("samples", samples),
        ("iterations_per_sample", iterations),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"runner_policy.{key} must be a non-negative integer")
    if policy["sample_statistic"] != "mean_call_duration":
        raise ValueError("worker supports only the declared mean_call_duration sample statistic")
    if samples <= 0 or iterations <= 0:
        raise ValueError("runner_policy samples and iterations must be positive")
    return warmups, samples, iterations


def _expected_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("measure mode requires the source canonical observation")
    return value


def _normalize_observation(observation: dict[str, Any], workload: dict[str, Any]) -> dict[str, Any]:
    token_headers = {
        item.lower() for item in workload["observations"]["events"]["unordered_header_token_order"]
    }
    if not token_headers:
        return observation
    normalized = json.loads(json.dumps(observation))
    for value in normalized.values():
        if not isinstance(value, list):
            continue
        for event in value:
            if not isinstance(event, dict) or event.get("type") != "http.response.start":
                continue
            headers = event.get("headers")
            if not isinstance(headers, list):
                continue
            for pair in headers:
                if not isinstance(pair, list) or len(pair) != 2:
                    continue
                try:
                    name = base64.b64decode(pair[0], validate=True).lower()
                    value_bytes = base64.b64decode(pair[1], validate=True)
                except (ValueError, TypeError):
                    continue
                if name.decode("ascii", errors="ignore").lower() not in token_headers:
                    continue
                tokens = [token.strip(b" \t") for token in value_bytes.split(b",")]
                if tokens and all(tokens):
                    pair[1] = _b64(b", ".join(sorted(set(tokens))))
    return normalized


def _same_observation(
    actual: dict[str, Any], expected: dict[str, Any], workload: dict[str, Any]
) -> bool:
    return _normalize_observation(actual, workload) == _normalize_observation(expected, workload)


def _run_router_workload(
    input_spec: dict[str, Any], workload: dict[str, Any], starlette: Any
) -> tuple[
    Callable[[], Any],
    Callable[[Any], dict[str, Any]],
    Callable[[dict[str, Any]], list[dict[str, str]]],
    dict[str, list[dict[str, Any]]],
]:
    invoke, _receive = _make_router_app(input_spec, starlette)
    empty_messages: dict[str, list[dict[str, Any]]] = {}

    # Router input templates and app construction stay outside timed calls.  The
    # returned coroutine creates the fresh dispatch scope and collects raw sends.
    def observe(raw: Any) -> dict[str, Any]:
        return {"events": _canonical_events(raw)}

    def validate(observation: dict[str, Any]) -> list[dict[str, str]]:
        return _validate_relations(input_spec, workload, observation, empty_messages)

    return invoke, observe, validate, empty_messages


def _run_gzip_workload(
    input_spec: dict[str, Any], workload: dict[str, Any]
) -> tuple[
    Callable[[], Any],
    Callable[[Any], dict[str, Any]],
    Callable[[dict[str, Any]], list[dict[str, str]]],
    dict[str, list[dict[str, Any]]],
    Callable[[asyncio.AbstractEventLoop], tuple[Any, int]] | None,
]:
    apps, response_messages = _response_apps(input_spec)
    middlewares = _middleware_instances(input_spec, apps)
    scope = _make_scope(input_spec["scope"])
    receive = _make_receive(input_spec["receive"])
    kind = input_spec["kind"]

    if kind in {"gzip_compression", "gzip_bypass"}:
        if "middleware" not in middlewares:
            raise ValueError(f"{kind} must declare input.middleware")
        middleware = middlewares["middleware"]

        async def invoke() -> list[dict[str, Any]]:
            return await _run_asgi(middleware, scope, receive)

        def observe(raw: Any) -> dict[str, Any]:
            return {"events": _canonical_events(raw)}

        timed_call = None

    elif kind == "gzip_responsiveness":
        large_name = "large_middleware"
        tiny_name = "tiny_middleware"
        if large_name not in middlewares or tiny_name not in middlewares:
            raise ValueError(
                "gzip_responsiveness must declare large_middleware and tiny_middleware"
            )
        large_app, tiny_app = middlewares[large_name], middlewares[tiny_name]
        schedule = input_spec.get("task_schedule")
        if not isinstance(schedule, dict) or set(schedule) != {
            "create_order",
            "await_before_timer_stops",
            "drain_after_timer",
            "scope_is_shared",
        }:
            raise ValueError("responsiveness task_schedule is malformed")
        create_order = schedule["create_order"]
        if (
            not isinstance(create_order, list)
            or sorted(create_order) != ["large", "tiny"]
            or schedule["await_before_timer_stops"] != "tiny"
            or schedule["drain_after_timer"] != "large"
            or not isinstance(schedule["scope_is_shared"], bool)
        ):
            raise ValueError("responsiveness task_schedule uses an unsupported ASGI schedule")
        shared_scope = _make_scope(input_spec["scope"])
        calls = {"large": large_app, "tiny": tiny_app}
        state: dict[str, Any] = {}

        async def start_until_tiny() -> None:
            scopes = {
                "large": shared_scope,
                "tiny": shared_scope,
            }
            if not schedule["scope_is_shared"]:
                scopes = {name: _make_scope(input_spec["scope"]) for name in calls}
            tasks: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}
            for name in create_order:
                tasks[name] = asyncio.create_task(
                    _run_asgi(calls[name], scopes[name], receive), name=f"gzip-{name}"
                )
            state["tasks"] = tasks
            state["tiny_messages"] = await tasks["tiny"]

        async def drain_large() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            tasks = state.get("tasks")
            if not isinstance(tasks, dict) or "large" not in tasks or "tiny_messages" not in state:
                raise RuntimeError("responsiveness operation was not started")
            large_messages = await tasks["large"]
            return large_messages, state["tiny_messages"]

        async def invoke() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            await start_until_tiny()
            return await drain_large()

        def observe(raw: Any) -> dict[str, Any]:
            large_messages, tiny_messages = raw
            # Deliberately do not assert whether the large response task was still
            # pending when the tiny response completed; that is not a source
            # contract of the responsiveness benchmark.
            return {
                "large_events": _canonical_events(large_messages),
                "tiny_events": _canonical_events(tiny_messages),
            }

        def timed_call(loop: asyncio.AbstractEventLoop) -> tuple[Any, int]:
            started = time.perf_counter_ns()
            loop.run_until_complete(start_until_tiny())
            elapsed = time.perf_counter_ns() - started
            # The upstream teardown drains and validates the large response
            # after CodSpeed stops its timer.
            raw = loop.run_until_complete(drain_large())
            return raw, elapsed

    else:
        raise ValueError(f"unsupported GZip workload kind: {kind!r}")

    def validate(observation: dict[str, Any]) -> list[dict[str, str]]:
        return _validate_relations(input_spec, workload, observation, response_messages)

    if kind != "gzip_responsiveness":
        timed_call = None
    return invoke, observe, validate, response_messages, timed_call


def _record_identity(base_identity: dict[str, Any]) -> dict[str, Any]:
    # `_load_subject` already records the capability snapshot for the imported
    # package.  Do not add a second, flat copy to the strict identity record.
    return dict(base_identity)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((probability * len(ordered) + 0.999999999) - 1)))
    return ordered[index]


def _warm_anyio_worker(loop: asyncio.AbstractEventLoop) -> None:
    try:
        import anyio
    except ImportError as exc:
        raise UnsupportedWorkload("AnyIO is required by the responsiveness setup") from exc
    loop.run_until_complete(anyio.to_thread.run_sync(bool))


def _measure(
    loop: asyncio.AbstractEventLoop,
    invoke: Callable[[], Any],
    observe: Callable[[Any], dict[str, Any]],
    validate: Callable[[dict[str, Any]], list[dict[str, str]]],
    expected: dict[str, Any],
    measurement: dict[str, Any],
    workload: dict[str, Any],
    timed_call: Callable[[asyncio.AbstractEventLoop], tuple[Any, int]] | None = None,
    fresh_loop_per_iteration: bool = False,
) -> dict[str, Any]:
    warmups, samples, iterations = _measurement_counts(measurement)

    def new_loop() -> asyncio.AbstractEventLoop:
        operation_loop = asyncio.new_event_loop()
        if fresh_loop_per_iteration:
            _warm_anyio_worker(operation_loop)
        return operation_loop

    def invoke_and_check(index: int) -> None:
        operation_loop = new_loop() if fresh_loop_per_iteration else loop
        try:
            raw = operation_loop.run_until_complete(invoke())
            observation = observe(raw)
        finally:
            if fresh_loop_per_iteration:
                operation_loop.close()
        relations = validate(observation)
        if not _same_observation(observation, expected, workload):
            raise RuntimeError(f"measured operation {index} changed its exact observation")
        if any(row["status"] != "pass" for row in relations):
            raise RuntimeError(f"measured operation {index} failed a declared input relation")

    call_index = 0
    for _ in range(warmups):
        invoke_and_check(call_index)
        call_index += 1
    sample_means_ns: list[float] = []
    for _ in range(samples):
        durations: list[int] = []
        for _ in range(iterations):
            operation_loop = new_loop() if fresh_loop_per_iteration else loop
            try:
                if timed_call is None:
                    started = time.perf_counter_ns()
                    raw = operation_loop.run_until_complete(invoke())
                    elapsed = time.perf_counter_ns() - started
                else:
                    raw, elapsed = timed_call(operation_loop)
                observation = observe(raw)
            finally:
                if fresh_loop_per_iteration:
                    operation_loop.close()
            relations = validate(observation)
            if not _same_observation(observation, expected, workload):
                raise RuntimeError(f"measured operation {call_index} changed its exact observation")
            if any(row["status"] != "pass" for row in relations):
                raise RuntimeError(
                    f"measured operation {call_index} failed a declared input relation"
                )
            durations.append(elapsed)
            call_index += 1
        sample_means_ns.append(float(statistics.fmean(durations)))
    return {
        "unit": "nanoseconds_per_operation",
        "runner_policy": dict(measurement["runner_policy"]),
        "warmup_iterations": warmups,
        "samples": sample_means_ns,
        "iterations_per_sample": iterations,
        "statistics": {
            "median": statistics.median(sample_means_ns),
            "mean": statistics.fmean(sample_means_ns),
            "stdev": statistics.stdev(sample_means_ns) if len(sample_means_ns) > 1 else 0.0,
            "min": min(sample_means_ns),
            "max": max(sample_means_ns),
            "p50": _quantile(sample_means_ns, 0.50),
            "p95": _quantile(sample_means_ns, 0.95),
            "p99": _quantile(sample_means_ns, 0.99),
        },
    }


def _run_worker(request: Any) -> dict[str, Any]:
    request = _strict_object(
        request,
        {"schema", "subject_id", "mode", "workload", "expected_observation"},
        "worker request",
    )
    if request["schema"] != REQUEST_SCHEMA:
        raise ValueError("worker request schema differs")
    subject_id = request["subject_id"]
    mode = request["mode"]
    if subject_id not in {"starlette-python", "python-package-cpython312"}:
        raise ValueError("worker subject is not a declared benchmark subject")
    if mode not in {"probe", "measure"}:
        raise ValueError("worker mode must be probe or measure")
    workload = _strict_object(
        request["workload"],
        {"workload_id", "category", "input", "observations", "measurement"},
        "workload descriptor",
    )
    if not isinstance(workload["workload_id"], str) or not workload["workload_id"]:
        raise ValueError("workload_id must be a non-empty string")
    input_spec = workload["input"]
    if not isinstance(input_spec, dict) or input_spec.get("kind") not in {
        "router_dispatch",
        "gzip_compression",
        "gzip_bypass",
        "gzip_responsiveness",
    }:
        raise ValueError("workload input kind is unsupported")
    _validate_observation_declaration(workload, input_spec["kind"])
    if mode == "probe" and request["expected_observation"] is not None:
        raise ValueError("probe mode requires expected_observation=null")

    try:
        starlette, base_identity = _load_subject(subject_id)
        identity = _record_identity(base_identity)
        timed_call: Callable[[asyncio.AbstractEventLoop], tuple[Any, int]] | None = None
        if input_spec["kind"] == "router_dispatch":
            if (
                subject_id == "python-package-cpython312"
                and not identity["capabilities"]["router_instance_is_asgi_callable"]
            ):
                raise UnsupportedWorkload(
                    "installed package Router instance is not an ASGI callable"
                )
            invoke, observe, validate, response_messages = _run_router_workload(
                input_spec, workload, starlette
            )
        else:
            if (
                subject_id == "python-package-cpython312"
                and not identity["capabilities"]["gzip_middleware_available"]
            ):
                raise UnsupportedWorkload("installed package has no GZipMiddleware implementation")
            invoke, observe, validate, response_messages, timed_call = _run_gzip_workload(
                input_spec, workload
            )

        loop = asyncio.new_event_loop()
        try:
            if input_spec["kind"] == "gzip_responsiveness":
                # The upstream setup warms AnyIO's worker-thread path before the
                # timed method.  Keep this setup outside every measured call.
                _warm_anyio_worker(loop)
            raw = loop.run_until_complete(invoke())
            observation = observe(raw)
            relations = validate(observation)
            result: dict[str, Any] = {
                "schema": RESULT_SCHEMA,
                "identity": identity,
                "workload_id": workload["workload_id"],
                "mode": mode,
                "status": "completed",
                "observation": observation,
                "input_relations": relations,
            }
            if any(row["status"] != "pass" for row in relations):
                result["status"] = "failed"
                result["reason"] = "one or more declared input relations failed"
                return result
            if mode == "measure":
                expected = _expected_observation(request["expected_observation"])
                if not _same_observation(observation, expected, workload):
                    result["status"] = "failed"
                    result["reason"] = (
                        "subject probe differs from source observation; measurement skipped"
                    )
                    return result
                result["measurement"] = _measure(
                    loop,
                    invoke,
                    observe,
                    validate,
                    expected,
                    workload["measurement"],
                    workload,
                    timed_call=timed_call,
                    fresh_loop_per_iteration=input_spec["kind"] == "gzip_responsiveness",
                )
            return result
        finally:
            loop.close()
    except UnsupportedWorkload as exc:
        return {
            "schema": RESULT_SCHEMA,
            "identity": base_identity
            if "base_identity" in locals()
            else {"subject_id": subject_id},
            "workload_id": workload["workload_id"],
            "mode": mode,
            "status": "not_run",
            "reason": str(exc),
            "input_relations": [],
        }


def main() -> int:
    request: Any = None
    try:
        request = json.load(sys.stdin)
        result = _run_worker(request)
    except Exception as exc:
        workload_id = None
        if isinstance(request, dict):
            descriptor = request.get("workload")
            if isinstance(descriptor, dict):
                workload_id = descriptor.get("workload_id")
        result = {
            "schema": RESULT_SCHEMA,
            "identity": {
                "subject_id": request.get("subject_id") if isinstance(request, dict) else None
            },
            "workload_id": workload_id,
            "mode": request.get("mode") if isinstance(request, dict) else None,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "input_relations": [],
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
