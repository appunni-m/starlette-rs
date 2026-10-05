"""Input-defined Python attribute protocols used on public response objects."""

from __future__ import annotations

import weakref
from typing import Any


class AttributeProbe:
    def __init__(self, spec: dict[str, Any], trace: list[Any], errors: list[Any]) -> None:
        self.spec = spec
        self.trace = trace
        self.errors = errors
        self.reads: dict[str, int] = {}
        self.writes: dict[str, int] = {}
        self.views: list[Any] = []
        self.failure = self.error(spec["failure"]["error"]) if spec["failure"] else None
        self.rejected_read = self.error(spec["rejected_read"])
        self.rejected_write = self.error(spec["rejected_write"])

    def error(self, spec: Any) -> Any:
        if spec is None:
            return None
        error = {
            "AttributeError": AttributeError,
            "OSError": OSError,
            "RuntimeError": RuntimeError,
        }[spec["class"]](spec["message"])
        self.errors.append(error)
        return error

    def attributes(self, base: Any) -> dict[str, Any]:
        probe = self

        def get_attribute(response: Any, name: str) -> Any:
            probe.reads[name] = probe.reads.get(name, 0) + 1
            if name in probe.spec["get_watch"]:
                probe.trace.append({"event": "attribute-read", "name": name})
            if probe.spec["get_allowed"] is not None and name not in probe.spec["get_allowed"]:
                probe.trace.append({"event": "rejected-read", "name": name})
                raise probe.rejected_read
            probe.check_failure("get", name, probe.reads[name])
            return object.__getattribute__(response, name)

        def set_attribute(response: Any, name: str, value: Any) -> None:
            probe.writes[name] = probe.writes.get(name, 0) + 1
            if name in probe.spec["set_watch"]:
                probe.trace.append({"event": "attribute-write", "name": name})
            if probe.spec["dict_fields"] is not None:
                dictionary = object.__getattribute__(response, "__dict__")
                probe.trace.append(
                    {
                        "event": "attribute-dictionary",
                        "write": name,
                        "present": [
                            field for field in probe.spec["dict_fields"] if field in dictionary
                        ],
                    }
                )
            if probe.spec["set_allowed"] is not None and name not in probe.spec["set_allowed"]:
                probe.trace.append({"event": "rejected-write", "name": name})
                raise probe.rejected_write
            probe.check_failure("set", name, probe.writes[name])
            object.__setattr__(response, name, value)

        attributes: dict[str, Any] = {
            "__getattribute__": get_attribute,
            "__setattr__": set_attribute,
        }
        hook = self.spec["header_hook"]
        if hook is not None:
            from scripts.parity.adapters.response_consumer import _content

            failure = self.error(hook["failure"])

            def init_headers(response: Any, headers: Any = None) -> None:
                probe.trace.append({"event": "user-init-headers"})
                for name, value in hook["mutations"].items():
                    setattr(response, name, _content(value) if name == "body" else value)
                if failure is not None:
                    raise failure
                if hook["delegate"]:
                    base.init_headers(response, headers)

            attributes["init_headers"] = init_headers
        if self.spec["override_cookie"]:
            from scripts.parity.adapters.response_consumer import _observe

            def set_cookie(response: Any, *args: Any, **kwargs: Any) -> None:
                probe.trace.append(
                    {"event": "user-set-cookie", "args": _observe(args), "kwargs": _observe(kwargs)}
                )
                base.set_cookie(response, *args, **kwargs)

            attributes["set_cookie"] = set_cookie
        accessor = self.spec["raw_accessor"]
        if accessor is not None:
            fixed = [
                (key.encode("latin-1"), value.encode("latin-1")) for key, value in accessor["pairs"]
            ]
            getter_failure = self.error(accessor["getter_failure"])
            setter_failure = self.error(accessor["setter_failure"])

            def get_raw(response: Any) -> Any:
                probe.trace.append({"event": "user-raw-get"})
                if getter_failure is not None:
                    raise getter_failure
                return (
                    fixed
                    if accessor["mode"] == "fixed"
                    else object.__getattribute__(response, "_consumer_raw")
                )

            def set_raw(response: Any, value: Any) -> None:
                probe.trace.append({"event": "user-raw-set"})
                if setter_failure is not None:
                    raise setter_failure
                object.__setattr__(response, "_consumer_raw", value)

            attributes["raw_headers"] = property(get_raw, set_raw)
        return attributes

    def check_failure(self, operation: str, name: str, count: int) -> None:
        failure = self.spec["failure"]
        if failure and (operation, name, count) == (
            failure["operation"],
            failure["name"],
            failure["at_call"],
        ):
            raise self.failure

    def actions(self, response: Any) -> None:
        for action in self.spec["actions"]:
            self.trace.append({"event": "header-action", "kind": action["kind"]})
            if action["kind"] == "read":
                view = response.headers
                observation = {
                    "event": "header-view",
                    "items": list(view.items()),
                    "previous_identity": [view is previous for previous in self.views],
                }
                if action["inspect_raw_alias"]:
                    observation["raw_alias"] = view.raw is response.raw_headers
                self.views.append(view)
                self.trace.append(observation)
            elif action["kind"] == "replace-raw":
                response.raw_headers = [
                    (key.encode("latin-1"), value.encode("latin-1"))
                    for key, value in action["pairs"]
                ]
            elif action["kind"] == "replace-owned-raw":
                response.raw_headers = self.owned_pairs(response, action)
            elif action["kind"] == "delete-raw":
                del response.raw_headers
            elif action["kind"] == "cookie":
                from scripts.parity.adapters.starlette_oracle import _apply_response_cookie_action

                _apply_response_cookie_action(response, action["cookie"], 0)
            elif action["kind"] == "cookie-reentry":
                self.cookie_reentry(response, action)

    def cookie_reentry(self, response: Any, action: dict[str, Any]) -> None:
        probe = self

        class UserAge:
            def __str__(self) -> str:
                probe.trace.append({"event": "cookie-age-str"})
                response.set_cookie(action["inner_key"], action["inner_value"])
                return action["age_text"]

            def __repr__(self) -> str:
                return f"UserAge({action['age_text']!r})"

        response.set_cookie(action["outer_key"], action["outer_value"], max_age=UserAge())

    def owned_pairs(self, response: Any, action: dict[str, Any]) -> Any:
        from scripts.parity.adapters.response_consumer import _observe

        owner = weakref.ref(response)
        trace = self.trace

        class UserRawValue(bytes):
            def __del__(self) -> None:
                current = owner()
                observation: dict[str, Any] = {
                    "event": "raw-value-finalize",
                    "owner_alive": current is not None,
                }
                if current is not None:
                    try:
                        value = getattr(current, action["read_on_finalize"])
                        observation["value"] = _observe(value)
                    except BaseException as error:
                        observation["error"] = {
                            "class": f"{type(error).__module__}.{type(error).__qualname__}",
                            "args": _observe(error.args),
                        }
                trace.append(observation)

        return [
            (UserRawValue(key.encode("latin-1")), value.encode("latin-1"))
            for key, value in action["pairs"]
        ]
