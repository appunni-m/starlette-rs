"""Public data-structure values, identity, and cyclic lifetime observations."""

from __future__ import annotations

import asyncio
import base64
import gc
import io
import threading
import warnings
import weakref
from typing import Any

from scripts.parity.adapters.ownership_cleanup import observe_ownership
from scripts.parity.adapters.traceback_cleanup import TracebackCleanup
from scripts.parity.adapters.upload_worker import UploadWorkerProbe


def _graph(case: dict[str, Any], observer: TracebackCleanup) -> tuple[Any, ...]:
    from starlette import datastructures

    spec = case["construction"]
    events: list[Any] = []
    guard = observer.guard(spec["guard_label"])
    inplace_error: BaseException | None = None
    inplace_policy = spec.get("size_callback", {}).get("inplace", {})
    if "failure" in inplace_policy:
        error_input = inplace_policy["failure"]
        exception_type = {"OSError": OSError, "RuntimeError": RuntimeError}[error_input["class"]]
        inplace_error = exception_type(error_input["message"])
        inplace_error.guard = guard

    def finalized() -> None:
        observer.finalizers.append(
            {
                "label": spec["holder_label"],
                "on_caller_thread": threading.current_thread() is observer.caller_thread,
            }
        )

    class UserValue:
        def __init__(self) -> None:
            self.guard = guard
            self.peer: Any = None

        def __str__(self) -> str:
            return spec["value_text"]

        def __del__(self) -> None:
            finalized()

    class UserFile(io.BytesIO):
        def __init__(self, text: str | None = None) -> None:
            super().__init__((spec["value_text"] if text is None else text).encode("utf-8"))
            self.guard = guard
            self.peer: Any = None
            self._rolled = spec.get("rolled", False)

        def worker_call(self, method: str, operation: Any) -> Any:
            probe = getattr(self, "worker_probe", None)
            return operation() if probe is None else probe.call(method, operation)

        def read(self, size: int = -1) -> bytes:
            return self.worker_call("read", lambda: super(UserFile, self).read(size))

        def seek(self, offset: int, whence: int = 0) -> int:
            return self.worker_call("seek", lambda: super(UserFile, self).seek(offset, whence))

        def write(self, data: bytes) -> int:
            if "replace_file" in spec.get("size_callback", {}):
                events.append(
                    {
                        "event": "file-write",
                        "is_current_file": upload.file is self,
                        "on_caller_thread": threading.current_thread() is observer.caller_thread,
                        "data_base64": base64.b64encode(data).decode("ascii"),
                    }
                )
            return self.worker_call("write", lambda: super(UserFile, self).write(data))

        def close(self) -> None:
            events.append(
                {
                    "event": "file-close",
                    "on_caller_thread": threading.current_thread() is observer.caller_thread,
                    "already_closed": self.closed,
                }
            )
            self.worker_call("close", lambda: super(UserFile, self).close())

        def __del__(self) -> None:
            finalized()
            super().__del__()

    class UserSize(int):
        def __add__(self, increment: Any) -> int:
            attributes = []
            for name in spec["size_callback"]["read_attributes"]:
                value = getattr(upload, name)
                attributes.append(
                    {"name": name, "is_operand": value is self, "is_file": value is holder}
                )
            events.append(
                {
                    "event": "size-add",
                    "operand": int(self),
                    "increment": int(increment),
                    "attributes": attributes,
                }
            )
            if "replace_file" in spec["size_callback"]:
                replacement_spec = spec["size_callback"]["replace_file"]
                replacement = UserFile(replacement_spec["value_text"])
                replacement._rolled = replacement_spec["rolled"]
                replacement.peer = upload
                upload.file = replacement
                events.append(
                    {"event": "file-replaced", "identity_preserved": upload.file is replacement}
                )
            return int(self) + increment

    if "inplace" in spec.get("size_callback", {}):

        def inplace_add(self: UserSize, increment: Any) -> Any:
            events.append(
                {
                    "event": "size-inplace-add",
                    "operand": int(self),
                    "increment": int(increment),
                }
            )
            policy = spec["size_callback"]["inplace"]
            if policy["result"] == "not-implemented":
                return NotImplemented
            if policy["result"] == "raise":
                raise inplace_error
            value = self.__add__(increment)
            if policy["result"] == "self":
                return self
            if policy["result"] == "none":
                return None
            return value + policy["extra_increment"]

        UserSize.__iadd__ = inplace_add

    class UserText(str):
        pass

    class UserBytes(bytes):
        pass

    name = case["surface"].removeprefix("starlette.datastructures.")
    constructor = getattr(datastructures, name)
    key = spec.get("key")
    count = spec.get("pair_count")
    public: dict[str, Any] = {}
    if name in {"UploadFile", "FormData"}:
        holder = UserFile()
        upload = datastructures.UploadFile(holder, filename=spec["filename"])
        if "size_callback" in spec:
            upload.size = UserSize(spec["size_callback"]["initial"])
            original_size = upload.size
        if name == "UploadFile":
            container = upload
            public = {"file_identity": container.file is holder, "filename": container.filename}
        else:
            container = constructor([(key, upload)] * count)
            values = container.getlist(key)
            public = {
                "value_identity": [value is upload for value in values],
                "file_identity": [value.file is holder for value in values],
            }
    else:
        holder = UserValue()
        if name in {"ImmutableMultiDict", "MultiDict"}:
            if spec["holder_position"] == "key":
                original = UserText(key)
                original.owner = holder
                container = constructor([(original, spec["value_text"])] * count)
                public = {"key_identity": [item is original for item, _ in container.multi_items()]}
            else:
                container = constructor([(key, holder)] * count)
                public = {"value_identity": [item is holder for item in container.getlist(key)]}
        elif name in {"Headers", "MutableHeaders"}:
            original = UserBytes(spec["value_text"].encode("latin-1"))
            original.owner = holder
            container = constructor(raw=[(key.encode("latin-1"), original)] * count)
            public = {
                "lookup": container.get(key),
                "value_identity": [value is original for _, value in container.raw],
            }
        elif name == "State":
            container = constructor({key: holder})
            public = {"value_identity": getattr(container, key) is holder}
        else:
            original = UserText(spec["value_text"])
            original.owner = holder
            if name == "CommaSeparatedStrings":
                container = constructor([original] * count)
                public = {"value_identity": [item is original for item in container]}
            elif name == "URL":
                container = constructor(original)
                public = {"url": str(container), "scheme": container.scheme}
            else:
                raise ValueError("Unsupported public value lifetime constructor")
    holder.peer = container
    if "worker_operation" in spec:
        probe = UploadWorkerProbe(spec["worker_operation"], events, observer.caller_thread, guard)
        holder.worker_probe = probe
        public["worker_operation"] = probe.run(upload)
    if "io_actions" in spec:

        async def drive_io() -> list[Any]:
            observations = []
            for action in spec["io_actions"]:
                arguments = [base64.b64decode(action["data_base64"], validate=True)]
                try:
                    result = await getattr(upload, action["method"])(*arguments)
                    observations.append({"method": action["method"], "result": result})
                except Exception as error:
                    if not spec.get("capture_errors", False):
                        raise
                    observations.append(
                        {
                            "method": action["method"],
                            "error": {
                                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                                "args": list(error.args),
                                "message": str(error),
                                "is_injected_error": error is inplace_error,
                                "has_cause": error.__cause__ is not None,
                                "has_context": error.__context__ is not None,
                                "suppress_context": error.__suppress_context__,
                            },
                        }
                    )
            return observations

        public["io_results"] = asyncio.run(drive_io())
        size_after = upload.size
        public["size_after"] = None if size_after is None else int(size_after)
        if "inplace" in spec["size_callback"]:
            public["size_identity_preserved"] = upload.size is original_size
        if "replace_file" in spec["size_callback"]:
            public["original_file_bytes"] = base64.b64encode(holder.getvalue()).decode("ascii")
            public["current_file_bytes"] = base64.b64encode(upload.file.getvalue()).decode("ascii")
    # Only the public container remains externally rooted: no consumer reference
    # to a user value can hide premature release or an opaque native ownership edge.
    return [container], [weakref.ref(holder), weakref.ref(guard)], events, public


def run_value_lifetime_case(case: dict[str, Any]) -> dict[str, Any]:
    gc.collect()
    with TracebackCleanup(case["garbage_collection"]) as observer:
        with warnings.catch_warnings(record=True) as warning_events:
            warnings.simplefilter("always")
            roots, references, events, public = _graph(case, observer)
            observation = observe_ownership(
                case["garbage_collection"], roots, references, events, observer, warning_events
            )
            observation["public_values"] = public
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "value-lifetime",
                "status": "ok",
                "value": {"value-lifetime": observation},
            }
        ],
    }
