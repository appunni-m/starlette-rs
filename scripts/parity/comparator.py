"""Case-independent exact comparator for declared parity observations."""

from __future__ import annotations

import base64
import os
import re
from html.parser import HTMLParser
from typing import Any

from .contract import (
    BASE_HTTP_REQUIREMENTS,
    BASE_HTTP_SURFACE,
    BASE_HTTP_WORKFLOW_OPERATION,
    TESTCLIENT_OPERATION,
    TESTCLIENT_SURFACE,
    ContractError,
    validate_workflow_result,
)


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
_TEXT_TRACEBACK_HEADER = re.compile(
    rb'^(?P<indent>[ \t]*)File "(?P<filename>[^"]+)", line \d+(?:, in .*)?(?:\r?\n)?$'
)
_HTML_TRACEBACK_PATH = re.compile(rb'(<span class="frame-filename">).*?(</span>)')
_HTML_TRACEBACK_LINE = re.compile(rb"(,\s*line <i>)\d+(</i>)")
_HTML_SOURCE_LINE_NUMBER = re.compile(rb'(<span class="lineno">)\d+(\.</span>)')
_HTML_FRAME_REFERENCE = re.compile(rb'((?:id|data-frame-id)=")[^"]*(")')
_HTML_CLOSING_DIV_SEQUENCE = re.compile(rb"</div>(?:[ \t\r\n]*</div>)+")
_PYTHON_OBJECT_ADDRESS = re.compile(r"(?<= object at )0x[0-9a-fA-F]+(?=>)")


def _normalize_python_object_address(path: str, value: Any) -> str:
    if path != "representation" or not isinstance(value, str):
        raise ContractError(
            "python-object-address normalization requires a routing representation string"
        )
    normalized, count = _PYTHON_OBJECT_ADDRESS.subn("0x<address>", value)
    if count != 1:
        raise ContractError(
            "Mount and Host representations must contain exactly one Python object address"
        )
    return normalized


_ISOLATED_PYTHON_SITE_PACKAGES = re.compile(
    r"(^|/)build/parity/envs/[^/]+/(?:lib/python[0-9.]+|Lib)/site-packages/"
)


def _normalize_isolated_python_environment_path(path: str, value: Any) -> Any:
    """Retain dependency-relative warning frames across isolated parity environments."""
    if path != "deprecation_warnings" or not isinstance(value, list):
        raise ContractError(
            "isolated-python-environment-path normalization requires deprecation warnings"
        )
    normalized = []
    for warning in value:
        if not isinstance(warning, dict) or not isinstance(warning.get("filename"), str):
            raise ContractError("deprecation warnings must contain a filename")
        normalized_warning = dict(warning)
        filename = normalized_warning["filename"].replace("\\", "/")
        normalized_warning["filename"] = _ISOLATED_PYTHON_SITE_PACKAGES.sub(
            r"\1site-packages/", filename, count=1
        )
        normalized.append(normalized_warning)
    return normalized


def _is_starlette_frame(filename: str) -> bool:
    """Identify frames defined by Python modules in the Starlette package."""
    path_parts = filename.replace("\\", "/").split("/")
    return filename.endswith(".py") and "starlette" in path_parts[:-1]


def _remove_starlette_text_frames(body: bytes) -> bytes:
    """Remove framework-owned frames while retaining user frames and the error."""
    lines = body.splitlines(keepends=True)
    retained: list[bytes] = []
    removed = False
    index = 0
    while index < len(lines):
        match = _TEXT_TRACEBACK_HEADER.match(lines[index])
        if match is None or not _is_starlette_frame(match.group("filename").decode()):
            retained.append(lines[index])
            index += 1
            continue

        removed = True
        frame_indent = len(match.group("indent"))
        index += 1
        while index < len(lines):
            line_indent = len(lines[index]) - len(lines[index].lstrip(b" \t"))
            if line_indent <= frame_indent:
                break
            index += 1
    return b"".join(retained) if removed else body


def _remove_starlette_html_frames(body: bytes) -> bytes:
    """Remove Starlette's rendered frame blocks without changing user-code HTML."""
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    line_offsets: list[int] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)

    class FrameParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.div_stack: list[dict[str, Any] | None] = []
            self.frame_blocks: list[dict[str, Any]] = []
            self.active_filename: dict[str, Any] | None = None
            self.malformed = False

        def _source_offset(self) -> int:
            line, column = self.getpos()
            if line > len(line_offsets):
                return len(source)
            return line_offsets[line - 1] + column

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attributes = dict(attrs)
            if tag == "div":
                in_traceback = any(
                    block is not None and block.get("traceback_container")
                    for block in self.div_stack
                )
                block = None
                if in_traceback and len(self.div_stack) == 2:
                    block = {
                        "start": self._source_offset(),
                        "filename": "",
                        "end": None,
                    }
                elif attributes.get("class") == "traceback-container":
                    block = {"traceback_container": True}
                self.div_stack.append(block)
            if tag == "span" and attributes.get("class") == "frame-filename":
                self.active_filename = next(
                    (
                        block
                        for block in reversed(self.div_stack)
                        if block is not None and "filename" in block
                    ),
                    None,
                )

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

        def handle_data(self, data: str) -> None:
            if self.active_filename is not None:
                self.active_filename["filename"] += data

        def handle_endtag(self, tag: str) -> None:
            if tag == "span" and self.active_filename is not None:
                self.active_filename = None
            if tag != "div":
                return
            if not self.div_stack:
                self.malformed = True
                return
            block = self.div_stack.pop()
            if block is None or "filename" not in block:
                return
            closing_tag_end = source.find(">", self._source_offset())
            if closing_tag_end < 0:
                self.malformed = True
                return
            block["end"] = closing_tag_end + 1
            self.frame_blocks.append(block)

    parser = FrameParser()
    parser.feed(source)
    if parser.malformed or parser.div_stack:
        return body

    ranges: list[tuple[int, int]] = []
    for block in parser.frame_blocks:
        filename = block["filename"]
        if not filename or not _is_starlette_frame(filename):
            continue
        start = block["start"]
        end = block["end"]
        while start > 0 and source[start - 1] in " \t\r\n":
            start -= 1
        while end < len(source) and source[end] in " \t\r\n":
            end += 1
        ranges.append((start, end))
    if not ranges:
        return body

    ranges.sort()
    merged_ranges: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged_ranges and start <= merged_ranges[-1][1]:
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))
    for start, end in reversed(merged_ranges):
        source = source[:start] + source[end:]
    return source.encode("utf-8")


def _normalize_debug_traceback_body(body: bytes) -> bytes | None:
    """Normalize source-dependent frames and insignificant traceback HTML formatting."""
    if body.startswith(b"Traceback (most recent call last):"):
        if not _TEXT_TRACEBACK_FRAME.search(body):
            return None
        body = _remove_starlette_text_frames(body)
        return _TEXT_TRACEBACK_FRAME.sub(rb'\1"<frame-path>"\2<line>', body)
    if b"<title>Starlette Debugger</title>" in body:
        if not (
            b'<div class="traceback-container">' in body
            and b'<p class="traceback-title">Traceback</p>' in body
            and b'<p class="frame-title">' in body
        ):
            return None
        body = _remove_starlette_html_frames(body)
        normalized = _HTML_TRACEBACK_PATH.sub(rb"\1<frame-path>\2", body)
        normalized = _HTML_TRACEBACK_LINE.sub(rb"\1<line>\2", normalized)
        normalized = _HTML_SOURCE_LINE_NUMBER.sub(rb"\1<line>\2", normalized)
        normalized = _HTML_CLOSING_DIV_SEQUENCE.sub(
            lambda match: b"\n".join([b"</div>"] * match.group().count(b"</div>")),
            normalized,
        )
        return _HTML_FRAME_REFERENCE.sub(rb"\1<frame-reference>\2", normalized)
    return None


def _body_bytes(value: Any) -> bytes | None:
    if not isinstance(value, dict):
        return None
    if set(value) == {"base64"}:
        encoded = value["base64"]
    elif set(value) == {"encoding", "data"} and value["encoding"] == "base64":
        encoded = value["data"]
    else:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
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
    response = value.get("response")
    if isinstance(response, dict):
        try:
            response_body = base64.b64decode(response.get("body_base64", ""), validate=True)
        except (ValueError, TypeError):
            response_body = None
        if response_body is not None and _normalize_debug_traceback_body(response_body) is not None:
            return True
    return bool(_event_traceback_bodies(value.get("asgi_events")))


def _header_component_bytes(value: Any) -> bytes | None:
    if isinstance(value, dict) and set(value) == {"base64"}:
        encoded = value["base64"]
    elif isinstance(value, str):
        encoded = value
    else:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None


def _encoded_header_component(value: Any, raw: bytes) -> Any:
    encoded = base64.b64encode(raw).decode("ascii")
    if isinstance(value, dict) and set(value) == {"base64"}:
        return {"base64": encoded}
    if isinstance(value, str):
        return encoded
    return value


def _normalize_content_length(headers: Any) -> Any:
    if not isinstance(headers, list):
        return headers
    normalized = []
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            return headers
        name = _header_component_bytes(pair[0])
        if name is None:
            return headers
        if name.lower() == b"content-length":
            normalized.append(
                [
                    pair[0],
                    _encoded_header_component(pair[1], b"<debug-traceback-body-length>"),
                ]
            )
        else:
            normalized.append(pair)
    return normalized


def _normalize_testclient_content_length(headers: Any) -> Any:
    if not isinstance(headers, list):
        return headers
    normalized = []
    for pair in headers:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(part, str) for part in pair)
        ):
            return headers
        if pair[0].lower() == "content-length":
            normalized.append([pair[0], "<debug-traceback-body-length>"])
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
    if path == "response":
        if not observation_has_debug_traceback or not isinstance(value, dict):
            return value
        try:
            body = base64.b64decode(value.get("body_base64", ""), validate=True)
        except (ValueError, TypeError):
            return value
        normalized_body = _normalize_debug_traceback_body(body)
        if normalized_body is None:
            return value
        normalized = dict(value)
        normalized["body_base64"] = base64.b64encode(normalized_body).decode("ascii")
        normalized["headers"] = _normalize_testclient_content_length(value.get("headers"))
        return normalized
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


def _normalize_anyio_cancel_scope_message(value: Any) -> Any:
    """Keep cancellation type and event order while dropping AnyIO scope/task IDs."""
    if isinstance(value, list):
        return [_normalize_anyio_cancel_scope_message(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _normalize_anyio_cancel_scope_message(item) for key, item in value.items()}
    if value.get("class") == "asyncio.exceptions.CancelledError":
        # Scope IDs are addresses, as confirmed by repeated live oracle runs.
        # Preserve the cancellation node, arguments, and remaining message text.
        def scope_address(message: Any) -> Any:
            if not isinstance(message, str):
                return message
            return re.sub(
                r"\ACancelled via cancel scope [0-9a-f]+\Z",
                "Cancelled via cancel scope <runtime-address>",
                message,
            )

        if "message" in normalized:
            normalized["message"] = scope_address(normalized["message"])
        if isinstance(normalized.get("args"), list):
            normalized["args"] = [scope_address(item) for item in normalized["args"]]
    exception = value.get("exception")
    if (
        isinstance(exception, dict)
        and exception.get("class") == "asyncio.exceptions.CancelledError"
        and isinstance(normalized.get("exception"), dict)
        and "message" in normalized["exception"]
    ):
        normalized_exception = dict(normalized["exception"])
        normalized_exception["message"] = "<AnyIO cancellation details>"
        normalized["exception"] = normalized_exception
    return normalized


def _normalize_anyio_memory_stream_eof_context(value: Any) -> Any:
    """Remove only the memory receiver's scheduling-dependent internal EOF chain."""
    if isinstance(value, list):
        return [_normalize_anyio_memory_stream_eof_context(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        key: _normalize_anyio_memory_stream_eof_context(item) for key, item in value.items()
    }
    empty_exception = {
        "args": [],
        "cause": None,
        "context": None,
        "exceptions": None,
        "message": "",
        "suppress_context": False,
    }
    blocked = {**empty_exception, "class": "anyio.WouldBlock"}
    message = "'_MemoryObjectItemReceiver' object has no attribute 'item'"
    receiver_context = {
        "class": "builtins.AttributeError",
        "message": message,
        "args": [message],
        "cause": None,
        "context": blocked,
        "exceptions": None,
        "suppress_context": False,
    }
    eof_after_wait = {
        **empty_exception,
        "class": "anyio.EndOfStream",
        "context": receiver_context,
        "suppress_context": True,
    }
    # Live oracle repetitions reach both receive_nowait() EOF and queued EOF.
    # Keep the EndOfStream node and its caller's cause/context link intact.
    # Unrecognized contexts, user exceptions, and all unraisable events stay exact.
    if value == eof_after_wait:
        normalized["context"] = None
        normalized["suppress_context"] = False
    return normalized


_MULTIPART_RANGE_CONTENT_TYPE = re.compile(
    rb"multipart/byteranges;\s*boundary=([0-9a-f]{26})", re.IGNORECASE
)
_MULTIPART_RANGE_PART_CONTENT_RANGE = re.compile(
    rb"(?:^|\r\n)Content-Range: bytes ([0-9]+)-([0-9]+)/([0-9]+)(?:\r\n|$)"
)


def _multipart_boundary_from_headers(headers: Any) -> bytes | None:
    if not isinstance(headers, list):
        return None
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        try:
            name = base64.b64decode(pair[0], validate=True).lower()
            value = base64.b64decode(pair[1], validate=True)
        except (ValueError, TypeError):
            continue
        if name != b"content-type":
            continue
        match = _MULTIPART_RANGE_CONTENT_TYPE.fullmatch(value)
        if match is not None:
            return match.group(1)
    return None


def _multipart_boundary_from_observation(observation: dict[str, Any]) -> bytes | None:
    boundary = _multipart_boundary_from_headers(observation.get("ordered_repeated_headers"))
    if boundary is not None:
        return boundary
    events = observation.get("asgi_events")
    if not isinstance(events, list):
        return None
    for event in events:
        if isinstance(event, dict) and event.get("type") == "http.response.start":
            boundary = _multipart_boundary_from_headers(event.get("headers"))
            if boundary is not None:
                return boundary
    return None


def _normalize_multipart_body(body: bytes, boundary: bytes) -> bytes:
    delimiter = b"--" + boundary
    normalized_delimiter = b"--" + (b"0" * len(boundary))
    normalized = bytearray()
    offset = 0
    while body.startswith(delimiter, offset):
        normalized.extend(normalized_delimiter)
        offset += len(delimiter)
        if body.startswith(b"--", offset):
            normalized.extend(b"--")
            offset += 2
            trailer = body[offset:]
            if trailer in {b"", b"\r\n"}:
                normalized.extend(trailer)
                return bytes(normalized)
            return body
        if not body.startswith(b"\r\n", offset):
            return body
        normalized.extend(b"\r\n")
        offset += 2
        headers_end = body.find(b"\r\n\r\n", offset)
        if headers_end < 0:
            return body
        headers = body[offset:headers_end]
        content_range = _MULTIPART_RANGE_PART_CONTENT_RANGE.search(headers)
        if content_range is None:
            return body
        start, end = (int(content_range.group(index)) for index in (1, 2))
        if end < start:
            return body
        part_body_start = headers_end + 4
        part_body_end = part_body_start + end - start + 1
        if part_body_end + 2 > len(body) or body[part_body_end : part_body_end + 2] != b"\r\n":
            return body
        normalized.extend(body[offset : part_body_end + 2])
        offset = part_body_end + 2
    return body


def _normalize_multipart_boundary_headers(headers: Any, boundary: bytes) -> Any:
    if not isinstance(headers, list):
        return headers
    normalized = []
    for pair in headers:
        if not isinstance(pair, list) or len(pair) != 2:
            return headers
        try:
            name = base64.b64decode(pair[0], validate=True).lower()
            raw_value = base64.b64decode(pair[1], validate=True)
        except (ValueError, TypeError):
            return headers
        if name == b"content-type":
            raw_value = raw_value.replace(
                b"boundary=" + boundary,
                b"boundary=" + (b"0" * len(boundary)),
                1,
            )
            normalized.append([pair[0], base64.b64encode(raw_value).decode("ascii")])
        else:
            normalized.append(pair)
    return normalized


def _normalize_multipart_boundary_events(value: Any, boundary: bytes) -> Any:
    if not isinstance(value, list):
        return value
    body_slots: list[tuple[int, int]] = []
    body_parts: list[bytes] = []
    normalized_events = list(value)
    for index, event in enumerate(value):
        if not isinstance(event, dict) or event.get("type") != "http.response.body":
            continue
        body = _body_bytes(event.get("body"))
        if body is None:
            return value
        body_slots.append((index, len(body)))
        body_parts.append(body)
    if body_parts:
        combined = b"".join(body_parts)
        normalized_combined = _normalize_multipart_body(combined, boundary)
        if normalized_combined != combined:
            offset = 0
            for index, length in body_slots:
                event = dict(normalized_events[index])
                updated_body = normalized_combined[offset : offset + length]
                event["body"] = {
                    "encoding": "base64",
                    "data": base64.b64encode(updated_body).decode("ascii"),
                }
                normalized_events[index] = event
                offset += length
    for index, event in enumerate(value):
        if not isinstance(event, dict) or event.get("type") != "http.response.start":
            continue
        updated = dict(normalized_events[index])
        updated["headers"] = _normalize_multipart_boundary_headers(event.get("headers"), boundary)
        normalized_events[index] = updated
    return normalized_events


def _normalize_multipart_range_boundary(
    path: str, value: Any, *, observation: dict[str, Any]
) -> Any:
    """Normalize only the random MIME boundary in an observed multipart FileResponse."""
    boundary = _multipart_boundary_from_observation(observation)
    if boundary is None:
        return value
    if path == "ordered_repeated_headers":
        return _normalize_multipart_boundary_headers(value, boundary)
    if path == "response_bytes":
        body = _body_bytes(value)
        if body is None:
            return value
        normalized_body = _normalize_multipart_body(body, boundary)
        if normalized_body == body:
            return value
        return {
            "encoding": "base64",
            "data": base64.b64encode(normalized_body).decode("ascii"),
        }
    if path == "asgi_events":
        return _normalize_multipart_boundary_events(value, boundary)
    raise ContractError(f"multipart-range-boundary normalization is not allowed for {path!r}")


def _has_file_response_pathsend(value: Any, *, observation_path: str) -> bool:
    if not isinstance(value, list):
        return False
    if observation_path == "asgi_events":
        return any(
            isinstance(event, dict) and event.get("type") == "http.response.pathsend"
            for event in value
        )
    if observation_path == "execution_trace":
        return any(
            isinstance(entry, dict)
            and isinstance(entry.get("message"), dict)
            and entry["message"].get("type") == "http.response.pathsend"
            for entry in value
        )
    return False


def _normalize_file_response_temp_path(
    value: Any, *, file_basename: str, side: str, observation_path: str
) -> Any:
    """Normalize a FileResponse pathsend temporary root, retaining its input basename."""
    if not isinstance(value, list):
        return value

    def normalize_pathsend_event(event: Any) -> Any:
        if not isinstance(event, dict) or event.get("type") != "http.response.pathsend":
            return event

        emitted_path = event.get("path")
        normalized_event = dict(event)
        parent_name = (
            os.path.basename(os.path.dirname(emitted_path)) if isinstance(emitted_path, str) else ""
        )
        python_temp_prefix = "starlette-file-response-"
        rust_temp_prefix = "starlette-rs-parity-file-"
        is_python_temp_parent = parent_name.startswith(python_temp_prefix) and len(
            parent_name
        ) > len(python_temp_prefix)
        rust_temp_suffix = parent_name.removeprefix(rust_temp_prefix)
        rust_temp_parts = rust_temp_suffix.split("-")
        is_rust_temp_parent = parent_name.startswith(rust_temp_prefix) and (
            len(rust_temp_parts) == 2 and all(part.isdecimal() for part in rust_temp_parts)
        )
        if (
            not isinstance(emitted_path, str)
            or not os.path.isabs(emitted_path)
            or os.path.basename(emitted_path) != file_basename
            or not (is_python_temp_parent or is_rust_temp_parent)
        ):
            normalized_event["path"] = f"<invalid-file-response-temp-path:{side}>"
        else:
            normalized_event["path"] = f"<file-response-temp-root>/{file_basename}"
        return normalized_event

    if observation_path == "asgi_events":
        return [normalize_pathsend_event(event) for event in value]
    if observation_path == "execution_trace":
        normalized_trace = []
        for entry in value:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("message"), dict)
                and entry["message"].get("type") == "http.response.pathsend"
            ):
                normalized_entry = dict(entry)
                normalized_entry["message"] = normalize_pathsend_event(entry["message"])
                normalized_trace.append(normalized_entry)
            else:
                normalized_trace.append(entry)
        return normalized_trace
    raise ContractError(
        f"file-response-temp-path normalization is not allowed for {observation_path!r}"
    )


_ROUTER_LIFESPAN_FRAME = re.compile(
    r"""^\s*File ["'][^"']*(?:/|\\)starlette(?:/|\\)routing\.py["'], line \d+, in lifespan\s*$"""
)


def _normalize_starlette_lifespan_router_frame(value: Any) -> Any:
    """Remove Starlette's source-only Router.lifespan frame from failure events."""
    if not isinstance(value, list):
        return value

    normalized_events: list[Any] = []
    for event in value:
        if (
            not isinstance(event, dict)
            or event.get("type") not in {"lifespan.startup.failed", "lifespan.shutdown.failed"}
            or not isinstance(event.get("message"), str)
        ):
            normalized_events.append(event)
            continue

        lines = event["message"].splitlines(keepends=True)
        normalized_lines: list[str] = []
        skip_source_line = False
        skip_caret_line = False
        for line in lines:
            if _ROUTER_LIFESPAN_FRAME.match(line.rstrip("\r\n")):
                skip_source_line = True
                continue
            if skip_source_line:
                skip_source_line = False
                if line.startswith("    ") and not line.lstrip().startswith("File "):
                    skip_caret_line = True
                    continue
            if skip_caret_line:
                skip_caret_line = False
                if re.fullmatch(r"[ \t]*\^+[ \t]*(?:\r?\n)?", line):
                    continue
            normalized_lines.append(line)

        normalized_message = "".join(normalized_lines)
        traceback_header = "Traceback (most recent call last):\n"
        if normalized_message.startswith(traceback_header) and not any(
            line.lstrip().startswith("File ") for line in normalized_lines
        ):
            normalized_message = normalized_message[len(traceback_header) :]
        if normalized_message == event["message"]:
            normalized_events.append(event)
        else:
            normalized_event = dict(event)
            normalized_event["message"] = normalized_message
            normalized_events.append(normalized_event)
    return normalized_events


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

    def input_path_present(input_path: str) -> bool:
        value: Any = case
        for component in input_path.split("."):
            if isinstance(value, dict):
                if component not in value:
                    return False
                value = value[component]
            elif isinstance(value, list) and component.isdecimal():
                index = int(component)
                if index >= len(value):
                    return False
                value = value[index]
            else:
                return False
        return True

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
        expected_paths = {
            selector["path"]
            for selector in selectors
            if "condition" not in selector or input_path_present(selector["condition"]["input_key"])
        }
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
            if "condition" in selector and not input_path_present(
                selector["condition"]["input_key"]
            ):
                continue
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
                    elif kind == "isolated-python-environment-path":
                        if (
                            case.get("surface") != TESTCLIENT_SURFACE
                            or case.get("operation") != TESTCLIENT_OPERATION
                        ):
                            raise ContractError(
                                "isolated Python environment path normalization is only allowed for TestClient warnings"
                            )
                        left_field = _normalize_isolated_python_environment_path(path, left_field)
                        right_field = _normalize_isolated_python_environment_path(path, right_field)
                    elif kind == "multipart-range-boundary":
                        left_field = _normalize_multipart_range_boundary(
                            path, left_field, observation=left_value
                        )
                        right_field = _normalize_multipart_range_boundary(
                            path, right_field, observation=right_value
                        )
                    elif kind == "file-response-temp-path":
                        if (
                            case.get("surface")
                            not in {"starlette.responses.FileResponse", BASE_HTTP_SURFACE}
                            or path
                            not in {
                                "asgi_events",
                                "execution_trace",
                            }
                            or (
                                case.get("surface") == "starlette.responses.FileResponse"
                                and path != "asgi_events"
                            )
                        ):
                            raise ContractError(
                                "file-response-temp-path normalization is only allowed for FileResponse ASGI events"
                            )
                        if case.get("surface") == BASE_HTTP_SURFACE:
                            if case.get("operation") != BASE_HTTP_WORKFLOW_OPERATION:
                                raise ContractError(
                                    "BaseHTTPMiddleware path normalization requires base-http-workflow"
                                )
                            has_pathsend_coverage = BASE_HTTP_REQUIREMENTS[
                                "pathsend_forwarding"
                            ] in case.get("covers", [])
                            observed_pathsend = any(
                                _has_file_response_pathsend(field, observation_path=path)
                                for field in (left_field, right_field)
                            )
                            if not has_pathsend_coverage:
                                if observed_pathsend:
                                    raise ContractError(
                                        "BaseHTTPMiddleware emitted pathsend without declared input coverage"
                                    )
                                continue
                            routes = case.get("application", {}).get("routes", [])
                            endpoint = (
                                routes[0].get("endpoint", {})
                                if isinstance(routes, list)
                                and routes
                                and isinstance(routes[0], dict)
                                else {}
                            )
                            file_input = (
                                endpoint.get("file") if isinstance(endpoint, dict) else None
                            )
                        else:
                            file_input = case.get("file")
                        if (
                            case.get("surface") == "starlette.responses.FileResponse"
                            and isinstance(file_input, dict)
                            and file_input.get("kind") in {"directory", "missing"}
                        ):
                            continue
                        if not isinstance(file_input, dict) or not isinstance(
                            file_input.get("name"), str
                        ):
                            raise ContractError(
                                "file-response-temp-path normalization requires the input file basename"
                            )
                        file_basename = file_input["name"]
                        left_field = _normalize_file_response_temp_path(
                            left_field,
                            file_basename=file_basename,
                            side="source",
                            observation_path=path,
                        )
                        right_field = _normalize_file_response_temp_path(
                            right_field,
                            file_basename=file_basename,
                            side="target",
                            observation_path=path,
                        )
                    elif kind == "anyio-cancel-scope-message":
                        cancellation_observation = (
                            case.get("surface"),
                            case.get("operation"),
                            path,
                        )
                        if cancellation_observation not in {
                            ("starlette.concurrency", "run_until_first_complete", "event_trace"),
                            (
                                "starlette.testclient.TestClient",
                                "public-client-workflow",
                                "responses",
                            ),
                        }:
                            raise ContractError(
                                "AnyIO cancellation-message normalization requires a declared cancellation observation"
                            )
                        left_field = _normalize_anyio_cancel_scope_message(left_field)
                        right_field = _normalize_anyio_cancel_scope_message(right_field)
                    elif kind == "anyio-memory-stream-eof-context":
                        if (
                            case.get("surface"),
                            case.get("operation"),
                            path,
                        ) != (
                            "starlette.testclient.TestClient",
                            "public-client-workflow",
                            "responses",
                        ):
                            raise ContractError(
                                "AnyIO EOF context normalization requires a declared response observation"
                            )
                        left_field = _normalize_anyio_memory_stream_eof_context(left_field)
                        right_field = _normalize_anyio_memory_stream_eof_context(right_field)
                    elif kind == "starlette-lifespan-router-frame":
                        if (
                            case.get("surface") != "starlette.testclient.TestClient"
                            or case.get("operation") != "lifespan-context"
                            or path != "lifespan_send_messages"
                        ):
                            raise ContractError(
                                "Starlette lifespan traceback normalization is only allowed for TestClient lifespan send messages"
                            )
                        left_field = _normalize_starlette_lifespan_router_frame(left_field)
                        right_field = _normalize_starlette_lifespan_router_frame(right_field)
                    elif kind == "python-object-address":
                        if case.get("surface") not in {
                            "starlette.routing.Mount",
                            "starlette.routing.Host",
                        }:
                            raise ContractError(
                                "python-object-address normalization is only allowed for Mount/Host representations"
                            )
                        left_field = _normalize_python_object_address(path, left_field)
                        right_field = _normalize_python_object_address(path, right_field)
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
