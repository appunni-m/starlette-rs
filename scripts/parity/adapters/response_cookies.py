"""Input-defined cookie arguments consumed through public response methods."""

from __future__ import annotations

import sys
import time
import weakref
from typing import Any


def apply_cookie_protocol(
    response: Any, actions: list[Any], trace: list[Any], errors: list[Any]
) -> None:
    from scripts.parity.adapters.response_consumer import _observe

    owner_ref = weakref.ref(response)
    owned_refs: list[Any] = []
    tables: list[Any] = []
    table_originals: list[tuple[Any, dict[Any, Any]]] = []

    def argument(spec: dict[str, Any]) -> Any:
        if spec["kind"] == "literal":
            return spec["value"]
        if spec["kind"] == "morsel":
            from http.cookies import Morsel

            class InputMorsel(Morsel):
                def __setitem__(self, key: Any, value: Any) -> None:
                    trace.append(
                        {"event": "morsel-attribute", "name": key, "value": _observe(value)}
                    )
                    super().__setitem__(key, value)

            value = InputMorsel()
            value.set(spec["key"], spec["value"], spec["coded_value"])
            value.update(spec["attributes"])
            trace.append({"event": "morsel-created", "key": value.key})
            return value
        counts: dict[str, int] = {}
        failure = spec["failure"]
        error = (
            {"RuntimeError": RuntimeError, "OSError": OSError}[failure["class"]](failure["message"])
            if failure
            else None
        )
        if error is not None:
            errors.append(error)

        owned = spec["owned_result"]
        finalizer_error = (
            {"RuntimeError": RuntimeError, "OSError": OSError}[owned["failure"]["class"]](
                owned["failure"]["message"]
            )
            if owned and owned["failure"]
            else None
        )
        if finalizer_error is not None:
            errors.append(finalizer_error)

        class OwnedCookieText(str):
            def __str__(self) -> str:
                trace.append({"event": "cookie-owned-str", "label": owned["label"]})
                return self

            def __del__(self) -> None:
                owner = owner_ref()
                trace.append(
                    {
                        "event": "cookie-owned-finalize",
                        "label": owned["label"],
                        "owner_alive": owner is not None,
                        "raw": _observe(owner.raw_headers) if owner is not None else None,
                    }
                )
                if owner is not None and owned["reentry"]:
                    owner.set_cookie(**owned["reentry"])
                if finalizer_error is not None:
                    raise finalizer_error

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
                if owned:
                    result = OwnedCookieText(owned["text"])
                    owned_refs.append(weakref.ref(result))
                    return result
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
                callback = spec["table_callback"]
                if callback:
                    trace.append(
                        {
                            "event": "cookie-table",
                            "label": spec["label"],
                            "same_as_previous": [table is previous for previous in tables],
                            "values": [
                                [point, table.get(point)]
                                for point in callback["observe_codepoints"]
                            ],
                        }
                    )
                    if not any(table is previous for previous, _ in table_originals):
                        table_originals.append((table, dict(table)))
                    tables.append(table)
                    for mutation in callback["mutations"]:
                        if mutation["action"] == "set":
                            table[mutation["codepoint"]] = mutation["value"]
                        else:
                            table.pop(mutation["codepoint"], None)
                    nested = callback["stdlib_cookie"]
                    if nested:
                        from http.cookies import SimpleCookie

                        class StandardCookieText(str):
                            def __str__(self) -> str:
                                return self

                            def translate(self, supplied: Any) -> str:
                                trace.append(
                                    {
                                        "event": "cookie-stdlib-table-alias",
                                        "same": supplied is table,
                                    }
                                )
                                return str.translate(self, supplied)

                        cookie = SimpleCookie()
                        cookie[nested["key"]] = StandardCookieText(nested["value"])
                        trace.append({"event": "cookie-stdlib-output", "text": cookie.output()})
                return (
                    str.translate(self, table)
                    if spec["translation"] is None
                    else spec["translation"]
                )

        if spec["hash_result"] is not None:

            def hash_value(self: Any) -> int:
                visit("hash")
                return spec["hash_result"]

            Protocol.__hash__ = hash_value

        if spec["kind"] == "text":
            attributes = {} if spec["hash_result"] is not None else {"__hash__": str.__hash__}
            return type("CookieText", (Protocol, str), attributes)(spec["value"])
        if spec["kind"] == "integer":
            return type("CookieInteger", (Protocol, int), {"__hash__": int.__hash__})(spec["value"])
        return type("CookieObject", (Protocol, object), {})()

    original_hook = sys.unraisablehook

    def unraisable(event: Any) -> None:
        trace.append(
            {
                "event": "cookie-unraisable",
                "class": type(event.exc_value).__name__,
                "message": str(event.exc_value),
                "is_user_error": any(event.exc_value is error for error in errors),
            }
        )

    sys.unraisablehook = unraisable
    try:
        for action in actions:
            arguments = {name: argument(value) for name, value in action["arguments"].items()}
            trace.append({"event": "cookie-action", "operation": action["operation"]})
            original_time = time.time
            original_get = type(response).__getattribute__
            watching = {"enabled": action["observe_raw_reads"]}

            def read_attribute(
                self: Any, name: str, getter: Any = original_get, monitor: Any = watching
            ) -> Any:
                if monitor["enabled"] and name == "raw_headers":
                    trace.append({"event": "cookie-raw-read"})
                return getter(self, name)

            type(response).__getattribute__ = read_attribute
            time.time = lambda epoch=action["clock_unix_seconds"]: float(epoch)
            try:
                getattr(response, action["operation"])(**arguments)
            finally:
                watching["enabled"] = False
                type(response).__getattribute__ = original_get
                time.time = original_time
                trace.append({"event": "cookie-headers", "raw": _observe(response.raw_headers)})
    finally:
        sys.unraisablehook = original_hook
        for table, original in table_originals:
            table.clear()
            table.update(original)
        if owned_refs:
            trace.append(
                {"event": "cookie-owned-live", "live": [ref() is not None for ref in owned_refs]}
            )
