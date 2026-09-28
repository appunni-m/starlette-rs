"""Case-independent exact comparator for declared parity observations."""

from __future__ import annotations

import base64
from html.parser import HTMLParser
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


class _TracebackHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_heading = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h2":
            self._in_heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._in_heading:
            self.parts.append(data)


def _debug_traceback_summary(body: bytes) -> dict[str, Any] | None:
    if body.startswith(b"Traceback (most recent call last):"):
        lines = body.decode("utf-8", errors="replace").rstrip("\n").splitlines()
        return {
            "format": "text",
            "exception_line": lines[-1] if lines else "",
            "traceback_header_present": bool(
                lines and lines[0] == "Traceback (most recent call last):"
            ),
        }
    if b"<title>Starlette Debugger</title>" in body:
        document = body.decode("utf-8", errors="replace")
        heading = _TracebackHeadingParser()
        heading.feed(document)
        return {
            "format": "html",
            "exception_heading": "".join(heading.parts),
            "traceback_title_present": 'class="traceback-title">Traceback' in document,
        }
    return None


def _normalize_debug_traceback(path: str, value: Any) -> Any:
    """Strip only interpreter-specific traceback frames from the declared response fields."""
    if path == "ordered_repeated_headers":
        if not isinstance(value, list):
            return value
        normalized_headers = []
        for pair in value:
            if not isinstance(pair, list) or len(pair) != 2:
                return value
            try:
                name = base64.b64decode(pair[0], validate=True).lower()
            except (ValueError, TypeError):
                return value
            if name == b"content-length":
                normalized_headers.append(
                    [pair[0], base64.b64encode(b"<debug-traceback-body-length>").decode("ascii")]
                )
            else:
                normalized_headers.append(pair)
        return normalized_headers
    if path == "response_bytes":
        if (
            not isinstance(value, dict)
            or set(value) != {"encoding", "data"}
            or value["encoding"] != "base64"
        ):
            return value
        try:
            body = base64.b64decode(value["data"], validate=True)
        except (ValueError, TypeError):
            return value
        summary = _debug_traceback_summary(body)
        if summary is None:
            return {"format": "raw", "data": value["data"]}
        return {"format": "debug-traceback", "summary": summary}
    if path == "asgi_events":
        if not isinstance(value, list):
            return value
        normalized: list[Any] = []
        for event in value:
            if not isinstance(event, dict):
                normalized.append(event)
                continue
            if event.get("type") == "http.response.start":
                headers = event.get("headers")
                if not isinstance(headers, list):
                    normalized.append(event)
                    continue
                normalized_headers = []
                for pair in headers:
                    if not isinstance(pair, list) or len(pair) != 2:
                        normalized_headers = headers
                        break
                    try:
                        name = base64.b64decode(pair[0], validate=True).lower()
                    except (ValueError, TypeError):
                        normalized_headers = headers
                        break
                    if name == b"content-length":
                        normalized_headers.append(
                            [
                                pair[0],
                                base64.b64encode(b"<debug-traceback-body-length>").decode("ascii"),
                            ]
                        )
                    else:
                        normalized_headers.append(pair)
                updated = dict(event)
                updated["headers"] = normalized_headers
                normalized.append(updated)
                continue
            if event.get("type") != "http.response.body":
                normalized.append(event)
                continue
            body_value = event.get("body")
            if (
                not isinstance(body_value, dict)
                or set(body_value) != {"encoding", "data"}
                or body_value["encoding"] != "base64"
            ):
                normalized.append(event)
                continue
            try:
                body = base64.b64decode(body_value["data"], validate=True)
            except (ValueError, TypeError):
                normalized.append(event)
                continue
            summary = _debug_traceback_summary(body)
            if summary is None:
                normalized.append(event)
                continue
            updated = dict(event)
            updated["body"] = {"format": "debug-traceback", "summary": summary}
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
                        if "starlette.asgi.server-error.debug-traceback" in case["covers"]:
                            left_field = _normalize_debug_traceback(path, left_field)
                            right_field = _normalize_debug_traceback(path, right_field)
                            compare_kind = "exact"
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
