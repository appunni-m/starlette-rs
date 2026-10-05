"""User-defined body/header protocols supplied to public response constructors."""

from __future__ import annotations

import base64
import weakref
from typing import Any


def body_value(spec: dict[str, Any], trace: list[Any], errors: list[Any]) -> Any:
    value = spec["value"]
    data = base64.b64decode(value["data_base64"], validate=True)
    if spec["kind"] == "memoryview-layout":
        view = memoryview(data).cast(value["format"], shape=value["shape"])
        if value["step"] is not None:
            view = view[:: value["step"]]
        if value["released"]:
            view.release()
        return view
    failure = _error(value["failure"], errors)

    class UserBody(bytes):
        def __len__(self) -> int:
            trace.append({"event": "body-len"})
            if failure is not None:
                raise failure
            return super().__len__() if value["length"] is None else value["length"]

    return UserBody(data)


def _error(spec: Any, errors: list[Any]) -> Any:
    if spec is None:
        return None
    error = {"OSError": OSError, "RuntimeError": RuntimeError}[spec["class"]](spec["message"])
    errors.append(error)
    return error


class ConstructionProbe:
    def __init__(self, case: dict[str, Any], trace: list[Any], errors: list[Any]) -> None:
        self.spec = case["construction_boundary"]
        self.trace = trace
        self.errors = errors
        self.response: Any = None
        self.cached: Any = None
        self.media: Any = None

    def render_entry(self, response: Any) -> None:
        self.response = response
        raw = self.spec["seed_headers"]
        if raw is not None:
            response.raw_headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in raw]
            self.cached = response.headers
        if self.spec["early_headers_read"] is not None:
            getattr(response, self.spec["early_headers_read"])

    def kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        from scripts.parity.adapters.response_consumer import _content

        probe = self
        headers = self.spec["headers"]
        if headers is not None:
            items_failure = _error(headers["items_failure"], self.errors)

            class HeaderText(str):
                def __new__(cls, text: str, role: str, policy: Any) -> Any:
                    instance = super().__new__(cls, text)
                    instance.role = role
                    instance.policy = policy
                    instance.failure = _error(policy["failure"], probe.errors)
                    return instance

                def lower(self) -> Any:
                    probe.trace.append({"event": "header-lower", "text": str(self)})
                    if self.policy["failure_stage"] == "lower" and self.failure is not None:
                        raise self.failure
                    text = self.policy["lower_result"]
                    return HeaderText(
                        super().lower() if text is None else text, self.role, self.policy
                    )

                def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
                    probe.trace.append(
                        {"event": "header-encode", "role": self.role, "encoding": encoding}
                    )
                    if self.policy["failure_stage"] == "encode" and self.failure is not None:
                        raise self.failure
                    return super().encode(encoding, errors)

            class HeaderMapping:
                def items(self) -> Any:
                    probe.trace.append({"event": "header-items"})
                    if items_failure is not None:
                        raise items_failure
                    for name, value in headers["mutations"].items():
                        setattr(probe.response, name, _content(value) if name == "body" else value)
                    return [
                        (
                            HeaderText(pair["name"], "name", pair["name_policy"]),
                            HeaderText(pair["value"], "value", pair["value_policy"]),
                        )
                        for pair in headers["pairs"]
                    ]

            kwargs["headers"] = HeaderMapping()
        media = self.spec["media"]
        if media is not None:

            class UserMedia(str):
                def startswith(self, *arguments: Any) -> bool:
                    probe.trace.append({"event": "media-startswith"})
                    return super().startswith(*arguments)

                def lower(self) -> str:
                    probe.trace.append({"event": "media-lower"})
                    return super().lower()

                def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
                    probe.trace.append({"event": "media-encode", "encoding": encoding})
                    return super().encode(encoding, errors)

            self.media = UserMedia(media)
            kwargs["media_type"] = self.media
        return kwargs

    def observe(self, response: Any) -> dict[str, Any]:
        observation: dict[str, Any] = {}
        if self.media is not None:
            observation["media_identity"] = response.media_type is self.media
            observation["media_type_class"] = type(response.media_type).__name__
        if self.cached is not None:
            observation["cached_identity"] = response.headers is self.cached
            observation["cached_raw_alias"] = self.cached.raw is response.raw_headers
            observation["cached_items"] = list(self.cached.items())
        if self.spec["weakref_direct"]:
            reference = weakref.ref(response)
            observation["weakref_identity"] = reference() is response
        return observation
