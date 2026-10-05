"""User-owned response hooks and async iterator protocols from supplied input."""

from __future__ import annotations

import asyncio
from typing import Any


def configure_response_protocols(
    spec: dict[str, Any],
    attributes: dict[str, Any],
    base: Any,
    trace: list[Any],
    errors: list[BaseException],
) -> None:
    error_types = {
        "RuntimeError": RuntimeError,
        "FileNotFoundError": FileNotFoundError,
        "OSError": OSError,
        "StopAsyncIteration": StopAsyncIteration,
    }
    stat = spec["stat_hook"]
    if stat is not None:
        error = (
            error_types[stat["failure"]["class"]](stat["failure"]["message"])
            if stat["failure"]
            else None
        )
        if error is not None:
            errors.append(error)

        def set_stat_headers(response: Any, result: Any) -> None:
            trace.append({"event": "stat-hook", "size": result.st_size, "mtime": result.st_mtime})
            if error is not None:
                raise error
            if stat["delegate"]:
                base.set_stat_headers(response, result)
            for name, value in stat["headers"].items():
                response.headers[name] = value

        attributes["set_stat_headers"] = set_stat_headers
    denial = spec["denial_hook"]
    if denial is not None:

        def wrap_send(response: Any, send: Any) -> Any:
            trace.append({"event": "denial-hook"})
            selected = (
                base._wrap_websocket_denial_send(response, send) if denial["delegate"] else send
            )

            async def wrapped(message: Any) -> None:
                trace.append({"event": "denial-send", "type": message["type"]})
                await selected(message)

            return wrapped

        attributes["_wrap_websocket_denial_send"] = wrap_send


def stream_content(spec: dict[str, Any], trace: list[Any], errors: list[BaseException]) -> Any:
    from scripts.parity.adapters.response_consumer import _content

    failure = spec["failure"]
    error = (
        {"RuntimeError": RuntimeError, "StopAsyncIteration": StopAsyncIteration}[failure["class"]](
            failure["message"]
        )
        if failure
        else None
    )
    if error is not None:
        errors.append(error)

    class Iterator:
        def __init__(self) -> None:
            self.index = 0

        def __aiter__(self) -> Any:
            trace.append({"event": "aiter"})
            return self

        def __anext__(self) -> Any:
            index = self.index
            self.index += 1
            trace.append({"event": "anext", "index": index})
            if index == len(spec["chunks"]):
                if spec["completion"] == "synchronous":
                    raise error if error is not None else StopAsyncIteration()

                async def complete() -> Any:
                    if spec["checkpoint"]:
                        await asyncio.sleep(0)
                    raise error if error is not None else StopAsyncIteration()

                return complete()
            definition = spec["chunks"][index]

            async def chunk() -> Any:
                if spec["checkpoint"]:
                    await asyncio.sleep(0)
                return _content(definition, trace, errors)

            return chunk()

    return Iterator()
