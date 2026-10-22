"""Input-driven observations for the Rust-native request-data APIs."""

from __future__ import annotations

import asyncio
import base64
from typing import Any


def _decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _message(spec: dict[str, Any]) -> dict[str, Any]:
    message_type = spec["type"]
    if message_type == "http.request":
        return {
            "type": message_type,
            "body": _decode(spec["body_base64"]),
            "more_body": spec["more_body"],
        }
    return {"type": message_type}


def _scope(headers: list[list[str]]) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(_decode(name), _decode(value)) for name, value in headers],
    }


def _exception_name(error: BaseException) -> str:
    return type(error).__name__


async def _await_advance(stream: Any) -> dict[str, Any]:
    try:
        chunk = await stream.__anext__()
    except StopAsyncIteration:
        return {"outcome": "complete"}
    except Exception as error:
        return {"outcome": "error", "error": _exception_name(error)}
    return {"outcome": "chunk", "body_base64": _encode(chunk)}


def _workflow_result(case: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "workflow",
                "status": "ok",
                "value": {"workflow": value},
            }
        ],
    }


def run_requestdata_case(case: dict[str, Any], request_type: type[Any]) -> dict[str, Any]:
    """Observe public Request APIs from the supplied raw headers and messages."""
    inputs = case["input"]
    if inputs["kind"] == "headers-and-cookies":
        request = request_type(_scope(inputs["headers_base64_pairs"]), receive=None)
        headers = request.headers
        cookies = request.cookies
        value = {
            "raw_headers_base64_pairs": [
                [_encode(name), _encode(item)] for name, item in headers.raw
            ],
            "header_length": len(headers),
            "headers_is_empty": len(headers) == 0,
            "lookups": [
                {
                    "name": name,
                    "get": headers.get(name),
                    "get_list": headers.getlist(name),
                }
                for name in inputs["lookup_names"]
            ],
            "cookies": [[key, item] for key, item in cookies.items()],
            "cookie_length": len(cookies),
            "cookie_is_empty": not cookies,
            "cookie_lookups": [
                {"key": key, "get": cookies.get(key), "contains": key in cookies}
                for key in inputs["cookie_lookup_keys"]
            ],
        }
        return _workflow_result(case, value)

    if inputs["kind"] == "body-stream":
        messages = [_message(message) for message in inputs["messages"]]
        cursor = 0

        async def receive() -> dict[str, Any]:
            nonlocal cursor
            if cursor >= len(messages):
                raise RuntimeError("input-defined receive message sequence was exhausted")
            message = messages[cursor]
            cursor += 1
            return message

        request = request_type(_scope([]), receive)
        streams: dict[str, Any] = {}
        actions = []

        async def run_actions() -> None:
            for index, action in enumerate(inputs["actions"]):
                kind = action["kind"]
                item: dict[str, Any] = {"action_index": index, "kind": kind}
                if kind == "body":
                    try:
                        body = await request.body()
                    except Exception as error:
                        item.update({"outcome": "error", "error": _exception_name(error)})
                    else:
                        item.update({"outcome": "body", "body_base64": _encode(body)})
                elif kind == "body-cache-from":
                    try:
                        body = await request.body()
                    except Exception as error:
                        item.update({"outcome": "error", "error": _exception_name(error)})
                    else:
                        item.update({"outcome": "body", "body_base64": _encode(body)})
                elif kind == "stream-next":
                    stream_id = action["stream_id"]
                    stream = streams.setdefault(stream_id, request.stream())
                    item["stream_id"] = stream_id
                    item.update(await _await_advance(stream))
                else:
                    stream_id = action["stream_id"]
                    stream = streams.setdefault(stream_id, request.stream())
                    await stream.aclose()
                    item.update({"stream_id": stream_id, "outcome": "closed"})
                actions.append(item)

        asyncio.run(run_actions())
        return _workflow_result(case, {"actions": actions})

    if inputs["kind"] != "pending-streams":
        raise ValueError(f"unsupported request-data input kind: {inputs['kind']!r}")

    messages = [_message(message) for message in inputs["messages"]]
    receive_futures: list[asyncio.Future[dict[str, Any]]] = []
    receive_ready: asyncio.Queue[int] = asyncio.Queue()

    async def pending_receive() -> dict[str, Any]:
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        receive_futures.append(future)
        receive_ready.put_nowait(len(receive_futures) - 1)
        return await future

    request = request_type(_scope([]), pending_receive)
    streams: dict[str, Any] = {}
    tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
    receive_indices: dict[str, int] = {}
    actions = []

    async def run_pending_actions() -> None:
        for index, action in enumerate(inputs["actions"]):
            kind = action["kind"]
            item: dict[str, Any] = {"action_index": index, "kind": kind}
            if kind == "stream-next-pending":
                request_id = action["request_id"]
                stream_id = action["stream_id"]
                stream = streams.setdefault(stream_id, request.stream())
                task = asyncio.create_task(_await_advance(stream))
                receive_index = await receive_ready.get()
                tasks[request_id] = task
                receive_indices[request_id] = receive_index
                item.update(
                    {"request_id": request_id, "stream_id": stream_id, "outcome": "pending"}
                )
            elif kind == "release-pending":
                request_id = action["request_id"]
                receive_futures[receive_indices[request_id]].set_result(
                    messages[action["message_index"]]
                )
                item["request_id"] = request_id
                item.update(await tasks[request_id])
            else:
                stream_id = action["stream_id"]
                stream = streams.setdefault(stream_id, request.stream())
                item["stream_id"] = stream_id
                item.update(await _await_advance(stream))
            actions.append(item)

    asyncio.run(run_pending_actions())
    return _workflow_result(case, {"actions": actions})
