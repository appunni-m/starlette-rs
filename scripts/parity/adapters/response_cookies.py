"""Input-defined cookie arguments consumed through public response methods."""

from __future__ import annotations

import time
from typing import Any


def apply_cookie_protocol(
    response: Any, actions: list[Any], trace: list[Any], errors: list[Any]
) -> None:
    from scripts.parity.adapters.response_consumer import _observe

    def argument(spec: dict[str, Any]) -> Any:
        if spec["kind"] == "literal":
            return spec["value"]
        counts: dict[str, int] = {}
        failure = spec["failure"]
        error = (
            {"RuntimeError": RuntimeError, "OSError": OSError}[failure["class"]](failure["message"])
            if failure
            else None
        )
        if error is not None:
            errors.append(error)

        def visit(method: str) -> None:
            counts[method] = counts.get(method, 0) + 1
            trace.append({"event": "cookie-argument", "label": spec["label"], "method": method})
            reentry = spec["reentry"]
            if reentry and (method, counts[method]) == (
                reentry["method"],
                reentry["at_call"],
            ):
                response.set_cookie(reentry["key"], reentry["value"])
            if failure and (method, counts[method]) == (
                failure["method"],
                failure["at_call"],
            ):
                raise error

        class Protocol:
            def __str__(self) -> str:
                visit("str")
                return self if spec["str_self"] else spec["str_text"]

            def __repr__(self) -> str:
                visit("repr")
                return f"CookieArgument({spec['label']!r})"

            def __bool__(self) -> bool:
                visit("bool")
                return spec["truth"]

            def __eq__(self, other: Any) -> bool:
                visit("eq")
                if type(other) is str and other == "":
                    return spec["eq_empty"]
                return type(self).__bases__[1].__eq__(self, other)

            def lower(self) -> Any:
                visit("lower")
                return spec["lower"]

            def translate(self, table: Any) -> str:
                visit("translate")
                return (
                    str.translate(self, table)
                    if spec["translation"] is None
                    else spec["translation"]
                )

        if spec["kind"] == "text":
            return type("CookieText", (Protocol, str), {"__hash__": str.__hash__})(spec["value"])
        if spec["kind"] == "integer":
            return type("CookieInteger", (Protocol, int), {"__hash__": int.__hash__})(spec["value"])
        return type("CookieObject", (Protocol, object), {})()

    for action in actions:
        arguments = {name: argument(value) for name, value in action["arguments"].items()}
        trace.append({"event": "cookie-action", "operation": action["operation"]})
        original_time = time.time
        time.time = lambda epoch=action["clock_unix_seconds"]: float(epoch)
        try:
            getattr(response, action["operation"])(**arguments)
        finally:
            time.time = original_time
            trace.append({"event": "cookie-headers", "raw": _observe(response.raw_headers)})
