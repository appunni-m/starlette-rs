"""Case-independent exact comparator for declared parity observations."""

from __future__ import annotations

import base64
import re
from typing import Any

from .contract import ContractError, validate_workflow_result


def _diff(
    step_id: str, path: str, kind: str, source: Any, target: Any, message: str
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "path": path,
        "kind": kind,
        "source": source,
        "target": target,
        "message": message,
    }


def _compare_value(kind: str, source: Any, target: Any) -> bool:
    if kind == "bytes":
        if not isinstance(source, dict) or not isinstance(target, dict):
            return False
        if set(source) != {"encoding", "data"} or set(target) != {"encoding", "data"}:
            return False
        if source["encoding"] != "base64" or target["encoding"] != "base64":
            return False
        try:
            source_bytes = base64.b64decode(source["data"], validate=True)
            target_bytes = base64.b64decode(target["data"], validate=True)
        except (ValueError, TypeError):
            return False
        return source_bytes == target_bytes
    if kind in {"exact", "ordered"}:
        # JSON object key order is not observable; array order and duplicate entries are.
        return source == target
    raise ContractError(f"unsupported comparison kind: {kind}")


def _normalize_allow_methods(path: str, value: Any) -> Any:
    """Sort only method tokens in an Allow header, retaining raw evidence elsewhere."""

    def normalize_headers(headers: Any) -> Any:
        if not isinstance(headers, list):
            return headers
        normalized = []
        for pair in headers:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not all(isinstance(item, str) for item in pair)
            ):
                return headers
            try:
                name = base64.b64decode(pair[0], validate=True).lower()
            except (ValueError, TypeError):
                return headers
            if name != b"allow":
                normalized.append(pair)
                continue
            try:
                raw_value = base64.b64decode(pair[1], validate=True)
            except (ValueError, TypeError):
                return headers
            tokens = [token.strip(b" \t") for token in raw_value.split(b",")]
            if not tokens or any(not token for token in tokens):
                return headers
            normalized_value = base64.b64encode(b", ".join(sorted(set(tokens)))).decode("ascii")
            normalized.append([pair[0], normalized_value])
        return normalized

    if path == "ordered_repeated_headers":
        return normalize_headers(value)
    if path == "asgi_events":
        if not isinstance(value, list):
            return value
        events = []
        for event in value:
            if not isinstance(event, dict):
                return value
            if event.get("type") != "http.response.start":
                events.append(event)
                continue
            updated = dict(event)
            updated["headers"] = normalize_headers(event.get("headers"))
            events.append(updated)
        return events
    raise ContractError(f"allow-methods-as-set normalization is not allowed for {path!r}")


_TEXT_TRACEBACK_FRAME = re.compile(rb"(?m)^([ \t]*File ).*(, line )\d+(?=, in |$)")
_HTML_TRACEBACK_PATH = re.compile(rb'(<span class="frame-filename">).*?(</span>)')
_HTML_TRACEBACK_LINE = re.compile(rb"(,\s*line <i>)\d+(</i>)")
_HTML_SOURCE_LINE_NUMBER = re.compile(rb'(<span class="lineno">)\d+(\.</span>)')
_HTML_FRAME_REFERENCE = re.compile(rb'((?:id|data-frame-id)=")[^"]*(")')


def _normalize_debug_traceback_body(body: bytes) -> bytes | None:
    """Normalize only frame paths and line numbers in actual debug traceback bytes."""
    if body.startswith(b"Traceback (most recent call last):"):
        if not _TEXT_TRACEBACK_FRAME.search(body):
            return None
        return _TEXT_TRACEBACK_FRAME.sub(rb'\1"<frame-path>"\2<line>', body)
    if b"<title>Starlette Debugger</title>" in body:
        if not (
            b'<div class="traceback-container">' in body
            and b'<p class="traceback-title">Traceback</p>' in body
            and b'<p class="frame-title">' in body
        ):
            return None
        normalized = _HTML_TRACEBACK_PATH.sub(rb"\1<frame-path>\2", body)
        normalized = _HTML_TRACEBACK_LINE.sub(rb"\1<line>\2", normalized)
        normalized = _HTML_SOURCE_LINE_NUMBER.sub(rb"\1<line>\2", normalized)
        return _HTML_FRAME_REFERENCE.sub(rb"\1<frame-reference>\2", normalized)
    return None


def _body_bytes(value: Any) -> bytes | None:
    if (
        not isinstance(value, dict)
        or set(value) != {"encoding", "data"}
        or value["encoding"] != "base64"
    ):
        return None
    try:
        return base64.b64decode(value["data"], validate=True)
    except (ValueError, TypeError):
        return None


def _event_traceback_bodies(value: Any) -> dict[int, bytes]:
    if not isinstance(value, list):
        return {}
    bodies = {}
    for index, event in enumerate(value):
        if not isinstance(event, dict) or event.get("type") != "http.response.body":
            continue
        body = _body_bytes(event.get("body"))
        normalized = _normalize_debug_traceback_body(body) if body is not None else None
        if normalized is not None:
            bodies[index] = normalized
    return bodies


def _observation_has_debug_traceback(value: dict[str, Any]) -> bool:
    body = _body_bytes(value.get("response_bytes"))
    if body is not None and _normalize_debug_traceback_body(body) is not None:
        return True
    return bool(_event_traceback_bodies(value.get("asgi_events")))


def _normalize_content_length(headers: Any) -> Any:
    if not isinstance(headers, list):
        return headers
    normalized = []
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            return headers
        try:
            name = base64.b64decode(pair[0], validate=True).lower()
        except (ValueError, TypeError):
            return headers
        if name == b"content-length":
            normalized.append(
                [pair[0], base64.b64encode(b"<debug-traceback-body-length>").decode("ascii")]
            )
        else:
            normalized.append(pair)
    return normalized


def _normalize_debug_traceback(
    path: str, value: Any, *, observation_has_debug_traceback: bool
) -> Any:
    """Normalize dynamic traceback fields only when live observations contain a traceback."""
    if path == "ordered_repeated_headers":
        if not observation_has_debug_traceback:
            return value
        return _normalize_content_length(value)
    if path == "response_bytes":
        body = _body_bytes(value)
        normalized = _normalize_debug_traceback_body(body) if body is not None else None
        if normalized is None:
            return value
        return {"encoding": "base64", "data": base64.b64encode(normalized).decode("ascii")}
    if path == "asgi_events":
        traceback_bodies = _event_traceback_bodies(value)
        if not traceback_bodies or not isinstance(value, list):
            return value
        normalized: list[Any] = []
        for index, event in enumerate(value):
            if not isinstance(event, dict):
                normalized.append(event)
                continue
            if event.get("type") == "http.response.start":
                updated = dict(event)
                updated["headers"] = _normalize_content_length(event.get("headers"))
                normalized.append(updated)
                continue
            if event.get("type") != "http.response.body":
                normalized.append(event)
                continue
            normalized_body = traceback_bodies.get(index)
            if normalized_body is None:
                normalized.append(event)
                continue
            updated = dict(event)
            updated["body"] = {
                "encoding": "base64",
                "data": base64.b64encode(normalized_body).decode("ascii"),
            }
            normalized.append(updated)
        return normalized
    raise ContractError(f"starlette-debug-traceback normalization is not allowed for {path!r}")


def _normalization_steps(normalization: dict[str, Any]) -> list[dict[str, Any]]:
    if normalization.get("kind") == "sequence":
        return normalization["steps"]
    return [normalization]


def compare_workflows(
    case: dict[str, Any], operation: dict[str, Any], source: Any, target: Any
) -> tuple[str, list[dict[str, Any]]]:
    source_result = validate_workflow_result(source, case["case_id"], "source workflow")
    target_result = validate_workflow_result(target, case["case_id"], "target workflow")
    if source_result["status"] != "completed" or target_result["status"] != "completed":
        return "not_run", []

    selected = case["observations"]
    source_observations = {item["step_id"]: item for item in source_result["observations"]}
    target_observations = {item["step_id"]: item for item in target_result["observations"]}
    differences: list[dict[str, Any]] = []
    if set(source_observations) != set(selected):
        differences.append(
            _diff(
                "*",
                "observations",
                "step_set_mismatch",
                sorted(selected),
                sorted(source_observations),
                "source observation step set differs from input selectors",
            )
        )
    if set(target_observations) != set(selected):
        differences.append(
            _diff(
                "*",
                "observations",
                "step_set_mismatch",
                sorted(selected),
                sorted(target_observations),
                "target observation step set differs from input selectors",
            )
        )
    if differences:
        return "fail", differences

    selectors = operation["source"]["result"]["observations"]
    for step_id in selected:
        left = source_observations[step_id]
        right = target_observations[step_id]
        if left["status"] != right["status"]:
            differences.append(
                _diff(
                    step_id,
                    "status",
                    "public_status_mismatch",
                    left["status"],
                    right["status"],
                    "public observation status differs",
                )
            )
            continue
        if left["status"] == "error":
            if left["error"] != right["error"]:
                differences.append(
                    _diff(
                        step_id,
                        "error",
                        "public_error_mismatch",
                        left["error"],
                        right["error"],
                        "public error fields require exact equality",
                    )
                )
            left_value = left["partial_value"]
            right_value = right["partial_value"]
        elif left["status"] == "ok":
            left_value = left["value"]
            right_value = right["value"]
        else:
            differences.append(
                _diff(
                    step_id,
                    "status",
                    "non_comparable_status",
                    left["status"],
                    right["status"],
                    "skipped or unsupported observations cannot prove parity",
                )
            )
            continue
        if not isinstance(left_value, dict) or not isinstance(right_value, dict):
            differences.append(
                _diff(
                    step_id,
                    "value",
                    "observation_shape",
                    left_value,
                    right_value,
                    "selected protocol observations must be objects",
                )
            )
            continue
        expected_paths = {selector["path"] for selector in selectors}
        if set(left_value) != expected_paths or set(right_value) != expected_paths:
            differences.append(
                _diff(
                    step_id,
                    "value",
                    "observation_field_set_mismatch",
                    sorted(expected_paths),
                    {"source": sorted(left_value), "target": sorted(right_value)},
                    "declared observation fields must be present exactly; undeclared fields are rejected",
                )
            )
            continue
        left_has_debug_traceback = _observation_has_debug_traceback(left_value)
        right_has_debug_traceback = _observation_has_debug_traceback(right_value)
        for selector in selectors:
            path = selector["path"]
            left_field = left_value[path]
            right_field = right_value[path]
            compare_kind = selector["comparison"]["kind"]
            normalization = selector.get("normalization")
            if normalization is not None:
                for normalization_step in _normalization_steps(normalization):
                    kind = normalization_step["kind"]
                    if kind == "allow-methods-as-set":
                        left_field = _normalize_allow_methods(path, left_field)
                        right_field = _normalize_allow_methods(path, right_field)
                    elif kind == "starlette-debug-traceback":
                        left_field = _normalize_debug_traceback(
                            path,
                            left_field,
                            observation_has_debug_traceback=left_has_debug_traceback,
                        )
                        right_field = _normalize_debug_traceback(
                            path,
                            right_field,
                            observation_has_debug_traceback=right_has_debug_traceback,
                        )
                    else:
                        raise ContractError(
                            f"unsupported normalization for {path}: {normalization_step!r}"
                        )
            if not _compare_value(compare_kind, left_field, right_field):
                differences.append(
                    _diff(
                        step_id,
                        path,
                        "value_mismatch",
                        left_field,
                        right_field,
                        f"{compare_kind} comparison differs",
                    )
                )
    return ("fail", differences) if differences else ("pass", [])


def compare_artifact_results(
    source: Any, target: Any, case: dict[str, Any], operation: dict[str, Any]
) -> dict[str, Any]:
    """Return a single comparison record for the maintained CLI comparator."""
    status, diffs = compare_workflows(case, operation, source, target)
    return {
        "case_id": case["case_id"],
        "target_profile": "manual-comparison",
        "requirements": case["covers"],
        "source": source,
        "target": target,
        "outcome": status,
        "diffs": diffs,
    }
