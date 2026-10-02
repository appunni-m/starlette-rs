"""Isolated live-Starlette and installed-wheel benchmark worker."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PARITY_INPUT_SCHEMA = "migration-parity/parity-input@25"
REQUEST_SCHEMA = "starlette-rs-benchmark-worker-request@1"
RESULT_SCHEMA = "starlette-rs-benchmark-worker-result@1"


def _strict_object(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{context} must contain exactly {sorted(keys)}")
    return value


def _canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quantile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((percentile * len(ordered) + 0.999999999) - 1)))
    return ordered[index]


def _resolve_case(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    workload_input = _strict_object(
        request["workload_input"], {"kind", "case_id"}, "workload input"
    )
    if workload_input["kind"] != "parity_case" or not isinstance(workload_input["case_id"], str):
        raise ValueError("workload input must reference one parity case")

    input_identity = _strict_object(
        request["parity_case_input"],
        {"case_id", "path", "sha256", "case_sha256"},
        "parity case input",
    )
    if input_identity["case_id"] != workload_input["case_id"]:
        raise ValueError("hashed parity case identity differs from the workload input")
    relative_path = Path(input_identity["path"])
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or relative_path.parts[:4] != ("build", "parity", "inputs", "parity")
    ):
        raise ValueError("parity input path must stay repository-relative under the parity lane")
    root = Path.cwd().resolve()
    input_path = (root / relative_path).resolve()
    if not input_path.is_relative_to(root / "build/parity/inputs/parity"):
        raise ValueError("parity input path escaped the parity input lane")
    actual_sha256 = _file_sha256(input_path)
    if actual_sha256 != input_identity["sha256"]:
        raise ValueError("parity input file hash differs from the workload identity")

    document = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != PARITY_INPUT_SCHEMA:
        raise ValueError("benchmark input source does not use the active parity input schema")
    cases = document.get("cases")
    if not isinstance(cases, list):
        raise ValueError("parity input cases must be an array")
    matching = [
        case
        for case in cases
        if isinstance(case, dict) and case.get("case_id") == workload_input["case_id"]
    ]
    if len(matching) != 1:
        raise ValueError("workload input must resolve to exactly one parity case")
    case = matching[0]
    case_sha256 = _canonical_sha256(case)
    if case_sha256 != input_identity["case_sha256"]:
        raise ValueError("resolved parity case hash differs from the workload identity")
    resolved_identity = {
        "case_id": workload_input["case_id"],
        "path": relative_path.as_posix(),
        "sha256": actual_sha256,
        "case_sha256": case_sha256,
    }
    return case, resolved_identity


def _resolve_modules(subject_id: str) -> tuple[Any, dict[str, Any]]:
    if subject_id == "starlette-python":
        oracle_root_value = os.environ.get("STARLETTE_ORACLE_ROOT")
        if not oracle_root_value:
            raise RuntimeError("source worker requires STARLETTE_ORACLE_ROOT")
        oracle_root = Path(oracle_root_value).resolve()
        sys.path.insert(0, str(oracle_root))
    elif subject_id != "python-package-cpython312":
        raise RuntimeError(f"unsupported Python benchmark subject: {subject_id}")

    import starlette
    from starlette.applications import Starlette

    module_path = Path(starlette.__file__).resolve()
    if subject_id == "starlette-python":
        expected_root = Path(os.environ["STARLETTE_ORACLE_ROOT"]).resolve() / "starlette"
        if not module_path.is_relative_to(expected_root):
            raise RuntimeError(
                f"source worker imported Starlette outside pinned source: {module_path}"
            )
        package_version = None
        core_path = None
        target_tree_sha256 = None
        wheel_sha256 = None
        source_revision = os.environ.get("STARLETTE_BENCHMARK_SOURCE_REVISION")
    else:
        from starlette_rs_py import _core

        expected_environment = Path(sys.prefix).resolve()
        if not module_path.is_relative_to(expected_environment):
            raise RuntimeError(
                f"wheel worker imported Starlette outside its isolated environment: {module_path}"
            )
        core_path = str(Path(_core.__file__).resolve())
        if not Path(core_path).is_relative_to(expected_environment):
            raise RuntimeError(
                f"wheel extension loaded outside its isolated environment: {core_path}"
            )
        package_version = importlib.metadata.version("starlette-rs-py")
        target_tree_sha256 = os.environ.get("STARLETTE_BENCHMARK_TARGET_TREE_SHA256")
        wheel_sha256 = os.environ.get("STARLETTE_BENCHMARK_WHEEL_SHA256")
        source_revision = None

    expected_module_version = "1.6.0" if subject_id == "starlette-python" else package_version
    if starlette.__version__ != expected_module_version:
        raise RuntimeError(
            f"expected Starlette module version {expected_module_version!r}, "
            f"imported {starlette.__version__!r}"
        )

    try:
        gzip_spec = importlib.util.find_spec("starlette.middleware.gzip")
    except (ImportError, ModuleNotFoundError, ValueError):
        gzip_spec = None
    identity = {
        "subject_id": subject_id,
        "starlette_version": starlette.__version__,
        "package_version": package_version,
        "module_path": str(module_path),
        "core_extension_path": core_path,
        "python_executable": str(Path(sys.executable).resolve()),
        "environment_prefix": str(Path(sys.prefix).resolve()),
        "runtime": f"{platform.python_implementation()} {platform.python_version()}",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "source_revision": source_revision,
        "target_tree_sha256": target_tree_sha256,
        "wheel_sha256": wheel_sha256,
    }
    return Starlette, {
        "identity": identity,
        "gzip_middleware_module_available": gzip_spec is not None,
    }


def _literal_arguments(step: dict[str, Any]) -> dict[str, Any]:
    arguments = step.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("workflow step arguments must be an object")
    values: dict[str, Any] = {}
    for name, argument in arguments.items():
        item = _strict_object(argument, {"kind", "value"}, f"argument {name}")
        if item["kind"] != "literal":
            raise ValueError(f"benchmark argument {name} must be a fixture literal")
        values[name] = item["value"]
    return values


def _make_plain_text_endpoint(response_type: Any, spec: dict[str, Any]) -> Any:
    async def endpoint(_request: Any) -> Any:
        response = response_type(
            content=spec["content"],
            status_code=spec["status_code"],
            media_type=spec["media_type"],
        )
        for cookie_value in spec["cookies"]:
            cookie = _strict_object(cookie_value, {"key", "value"}, "response cookie input")
            response.set_cookie(key=cookie["key"], value=cookie["value"])
        return response

    return endpoint


def _make_app(starlette_type: Any, application_step: dict[str, Any]) -> tuple[Any, Any, list[str]]:
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    if application_step.get("operation") != "__init__":
        raise ValueError("first workflow step must construct a Starlette application")
    app_spec = _literal_arguments(application_step)
    if set(app_spec) != {
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
        "max_body_size",
    }:
        raise ValueError("Starlette constructor inputs differ from the supported fixture shape")
    if app_spec["exception_handlers"] != []:
        raise ValueError("benchmark worker only materializes the empty handler registry")

    lifespan_spec = app_spec["lifespan"]
    _strict_object(
        lifespan_spec,
        {"kind", "record_entry", "record_exit"},
        "lifespan marker",
    )
    if lifespan_spec["kind"] != "async-context-manager" or not all(
        isinstance(lifespan_spec[field], bool) for field in ("record_entry", "record_exit")
    ):
        raise ValueError("benchmark lifespan must use the declared async-context-manager marker")
    lifecycle_trace: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        if lifespan_spec["record_entry"]:
            lifecycle_trace.append("entry")
        try:
            yield
        finally:
            if lifespan_spec["record_exit"]:
                lifecycle_trace.append("exit")

    routes_spec = app_spec["routes"]
    if not isinstance(routes_spec, list):
        raise ValueError("route input must be an array")
    routes = []
    endpoints: list[Any] = []
    for route_spec in routes_spec:
        route = _strict_object(
            route_spec, {"kind", "path", "methods", "endpoint"}, "HTTP route input"
        )
        if route["kind"] != "http-route":
            raise ValueError("route input must use the declared http-route kind")
        endpoint_spec = route["endpoint"]
        if (
            not isinstance(endpoint_spec, dict)
            or endpoint_spec.get("kind") != "plain-text-response"
        ):
            raise ValueError("benchmark endpoint must use the fixture plain-text-response kind")
        endpoint_spec = _strict_object(
            endpoint_spec,
            {"kind", "content", "status_code", "media_type", "cookies"},
            "plain-text response input",
        )
        if not isinstance(endpoint_spec["cookies"], list):
            raise ValueError("response cookies must be an array")

        endpoint = _make_plain_text_endpoint(PlainTextResponse, endpoint_spec)
        endpoints.append(endpoint)
        routes.append(Route(route["path"], endpoint, methods=route["methods"]))

    app = starlette_type(
        debug=app_spec["debug"],
        routes=routes,
        middleware=app_spec["middleware"],
        exception_handlers={},
        lifespan=lifespan,
        max_body_size=app_spec["max_body_size"],
    )
    return app, endpoints, lifecycle_trace


def _decode_base64(value: str, context: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid base64 at {context}") from exc


def _make_scope(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("type") == "lifespan":
        _strict_object(spec, {"type", "asgi"}, "lifespan scope")
        return {"type": spec["type"], "asgi": dict(spec["asgi"])}
    _strict_object(
        spec,
        {
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        },
        "HTTP scope",
    )
    if spec["type"] != "http":
        raise ValueError("dispatch scope type must be http")
    headers = [
        (
            _decode_base64(pair[0], "scope header name"),
            _decode_base64(pair[1], "scope header value"),
        )
        for pair in spec["headers_base64_pairs"]
    ]
    return {
        "type": spec["type"],
        "asgi": dict(spec["asgi"]),
        "http_version": spec["http_version"],
        "method": spec["method"],
        "scheme": spec["scheme"],
        "path": spec["path"],
        "raw_path": _decode_base64(spec["raw_path_base64"], "scope.raw_path_base64"),
        "query_string": _decode_base64(spec["query_string_base64"], "scope.query_string_base64"),
        "root_path": spec["root_path"],
        "headers": headers,
        "client": tuple(spec["client"]),
        "server": tuple(spec["server"]),
    }


def _make_message(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("type") in {"lifespan.startup", "lifespan.shutdown"}:
        _strict_object(spec, {"type"}, "lifespan receive message")
        return {"type": spec["type"]}
    _strict_object(spec, {"type", "body_base64", "more_body"}, "HTTP receive message")
    return {
        "type": spec["type"],
        "body": _decode_base64(spec["body_base64"], "receive.body_base64"),
        "more_body": spec["more_body"],
    }


def _canonical_message(message: dict[str, Any]) -> dict[str, Any]:
    kind = message["type"]
    if kind.startswith("lifespan."):
        return {"type": kind}
    if kind == "http.response.start":
        return {
            "type": kind,
            "status": message["status"],
            "headers": [
                [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
                for name, value in message["headers"]
            ],
        }
    if kind == "http.response.body":
        event = {
            "type": kind,
            "body": {
                "encoding": "base64",
                "data": base64.b64encode(message["body"]).decode("ascii"),
            },
        }
        if "more_body" in message:
            event["more_body"] = message["more_body"]
        return event
    raise RuntimeError(f"unexpected ASGI event in benchmark dispatch: {kind!r}")


def _dispatch_step(case: dict[str, Any]) -> dict[str, Any]:
    rows = [step for step in case["steps"] if step.get("step_id") == "dispatch"]
    if len(rows) != 1 or rows[0].get("operation") != "__call__":
        raise ValueError("benchmark case must provide one Starlette.__call__ dispatch step")
    return rows[0]


def _lifecycle_step(case: dict[str, Any]) -> dict[str, Any] | None:
    rows = [step for step in case["steps"] if step.get("step_id") == "lifecycle"]
    if not rows:
        return None
    if len(rows) != 1 or rows[0].get("operation") != "__call__":
        raise ValueError("lifecycle schedule must provide one Starlette.__call__ step")
    return rows[0]


def _validate_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    _strict_object(
        case,
        {
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "steps",
            "observations",
            "execution_schedule",
        },
        "parity case",
    )
    if case["surface"] != "starlette.applications.Starlette" or case["operation"] != "__call__":
        raise ValueError("benchmark worker supports Starlette application __call__ cases")
    steps = case["steps"]
    if not isinstance(steps, list) or len(steps) not in {2, 3}:
        raise ValueError(
            "benchmark case must contain application, optional lifecycle, and dispatch"
        )
    if steps[0].get("step_id") != "application":
        raise ValueError("benchmark case must construct its application first")
    dispatch = _dispatch_step(case)
    lifecycle = _lifecycle_step(case)
    step_ids = [step.get("step_id") for step in steps]
    schedule = case["execution_schedule"]
    if lifecycle is None:
        if step_ids != ["application", "dispatch"] or schedule != ["dispatch"]:
            raise ValueError("dispatch-only schedule does not match the workflow steps")
    elif step_ids != ["application", "lifecycle", "dispatch"] or schedule != [
        "lifespan.startup",
        "dispatch",
        "lifespan.shutdown",
    ]:
        raise ValueError("lifespan schedule does not match the workflow steps")
    if case["observations"] != step_ids[1:]:
        raise ValueError("benchmark observations must select each non-construction step in order")
    return dispatch, lifecycle


def _step_arguments(step: dict[str, Any]) -> dict[str, Any]:
    values = _literal_arguments(step)
    if set(values) != {"scope", "receive", "send"}:
        raise ValueError("ASGI call inputs must provide scope, receive, and send")
    if values["send"] != {"kind": "capture-asgi-send"}:
        raise ValueError("send input must select the declared ASGI message collector")
    if not isinstance(values["receive"], list):
        raise ValueError("receive input must be an array of fixture messages")
    return values


async def _invoke_dispatch(
    app: Any,
    dispatch_args: dict[str, Any],
    *,
    scope_capture: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scope = _make_scope(dispatch_args["scope"])
    incoming = [_make_message(item) for item in dispatch_args["receive"]]
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received < len(incoming):
            message = incoming[received]
            received += 1
            return message
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(scope, receive, send)
    if scope_capture is not None:
        scope_capture["scope"] = scope
    return sent


class _LifespanSession:
    def __init__(
        self,
        app: Any,
        scope_spec: dict[str, Any],
        receive_specs: list[dict[str, Any]],
    ) -> None:
        self.incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.events: list[dict[str, Any]] = []
        self.startup_complete = asyncio.Event()
        self.receive_specs = receive_specs

        async def receive() -> dict[str, Any]:
            return await self.incoming.get()

        async def send(message: dict[str, Any]) -> None:
            self.events.append(_canonical_message(message))
            if message.get("type") in {
                "lifespan.startup.complete",
                "lifespan.startup.failed",
            }:
                self.startup_complete.set()

        self.task = asyncio.create_task(app(_make_scope(scope_spec), receive, send))

    async def start(self) -> None:
        await self.incoming.put(_make_message(self.receive_specs[0]))
        startup_wait = asyncio.create_task(self.startup_complete.wait())
        done, _ = await asyncio.wait({self.task, startup_wait}, return_when=asyncio.FIRST_COMPLETED)
        if self.task in done:
            startup_wait.cancel()
            await asyncio.gather(startup_wait, return_exceptions=True)
            await self.task
            raise RuntimeError("lifespan app returned before startup completed")
        startup_wait.cancel()
        await asyncio.gather(startup_wait, return_exceptions=True)
        if self.events[-1]["type"] == "lifespan.startup.failed":
            raise RuntimeError("fixture lifespan startup failed")

    async def close(self) -> None:
        await self.incoming.put(_make_message(self.receive_specs[1]))
        await self.task


def _validate_lifespan_completion(session: _LifespanSession) -> None:
    event_types = [event["type"] for event in session.events]
    expected = ["lifespan.startup.complete", "lifespan.shutdown.complete"]
    if event_types != expected:
        raise RuntimeError(
            "fixture lifespan must emit startup.complete then shutdown.complete; "
            f"observed {event_types!r}"
        )


async def _start_lifespan(app: Any, lifecycle_args: dict[str, Any]) -> _LifespanSession:
    scope = lifecycle_args["scope"]
    receive_specs = lifecycle_args["receive"]
    if scope.get("type") != "lifespan":
        raise ValueError("lifecycle fixture scope must have type lifespan")
    if [item.get("type") for item in receive_specs] != [
        "lifespan.startup",
        "lifespan.shutdown",
    ]:
        raise ValueError("fixture lifecycle must provide startup followed by shutdown")
    session = _LifespanSession(app, scope, receive_specs)
    try:
        await session.start()
    except BaseException as startup_error:
        if not session.task.done():
            try:
                await session.close()
            except BaseException as cleanup_error:
                startup_error.add_note(
                    f"lifespan cleanup after startup failure also failed: {cleanup_error!r}"
                )
        raise
    return session


def _observation_value(
    sent: list[dict[str, Any]],
    scope: dict[str, Any],
    app: Any,
    endpoints: list[Any],
    lifecycle_trace: list[str],
) -> dict[str, Any]:
    events = [_canonical_message(message) for message in sent]
    start = next((event for event in events if event["type"] == "http.response.start"), None)
    if start is None:
        raise RuntimeError("Starlette completed without an http.response.start event")
    body = b"".join(
        base64.b64decode(event["body"]["data"])
        for event in events
        if event["type"] == "http.response.body"
    )
    return {
        "request_observations": None,
        "route_scope": {
            "app_is_application": scope.get("app") is app,
            "router_is_application_router": scope.get("router") is app.router,
            "endpoint_is_route_endpoint": scope.get("endpoint") in endpoints,
            "path_params_present": "path_params" in scope,
            "path_params": scope.get("path_params"),
        },
        "response_status": start["status"],
        "ordered_repeated_headers": start["headers"],
        "response_bytes": {"encoding": "base64", "data": base64.b64encode(body).decode("ascii")},
        "asgi_event_order": [event["type"] for event in events],
        "asgi_events": events,
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
    }


async def _run_probe(
    app: Any,
    case: dict[str, Any],
    dispatch_step: dict[str, Any],
    lifecycle_step: dict[str, Any] | None,
    endpoints: list[Any],
    lifecycle_trace: list[str],
) -> dict[str, Any]:
    dispatch_args = _step_arguments(dispatch_step)
    if lifecycle_step is None:
        scope_capture: dict[str, Any] = {}
        sent = await _invoke_dispatch(app, dispatch_args, scope_capture=scope_capture)
        scope = scope_capture["scope"]
        value = _observation_value(sent, scope, app, endpoints, lifecycle_trace)
        return {
            "case_id": case["case_id"],
            "status": "completed",
            "observations": [{"step_id": "dispatch", "status": "ok", "value": value}],
        }

    lifecycle_args = _step_arguments(lifecycle_step)
    session = await _start_lifespan(app, lifecycle_args)
    dispatch_value: dict[str, Any] | None = None
    startup_events = list(session.events)
    try:
        # Obtain fresh dispatch containers for the probe, including an independent scope.
        scope_capture = {}
        sent = await _invoke_dispatch(app, dispatch_args, scope_capture=scope_capture)
        scope = scope_capture["scope"]
        dispatch_value = _observation_value(sent, scope, app, endpoints, lifecycle_trace)
    finally:
        await session.close()
        _validate_lifespan_completion(session)

    shutdown_events = session.events[len(startup_events) :]
    combined_events = [
        *startup_events,
        *(dispatch_value["asgi_events"] if dispatch_value is not None else []),
        *shutdown_events,
    ]
    lifecycle_value = {
        "response_status": None,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": [event["type"] for event in combined_events],
        "asgi_events": combined_events,
        "lifecycle_and_cleanup_effects": list(lifecycle_trace),
    }
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {"step_id": "lifecycle", "status": "ok", "value": lifecycle_value},
            {"step_id": "dispatch", "status": "ok", "value": dispatch_value},
        ],
    }


def _validate_measurement(measurement: Any) -> dict[str, Any]:
    policy = _strict_object(
        measurement,
        {
            "step_ids",
            "warmup_iterations",
            "measurement_iterations",
            "samples",
            "cache_state",
            "concurrency",
        },
        "worker measurement",
    )
    if policy["step_ids"] != ["dispatch"]:
        raise ValueError("worker supports only the declared dispatch measurement step")
    counts = (policy["warmup_iterations"], policy["measurement_iterations"], policy["samples"])
    if not all(isinstance(value, int) and value > 0 for value in counts):
        raise ValueError("worker measurement counts must be positive integers")
    if policy["cache_state"] != "warm" or policy["concurrency"] != 1:
        raise ValueError("worker only implements the declared warm, single-concurrency workload")
    return policy


async def _run_measurement(
    app: Any,
    dispatch_args: dict[str, Any],
    lifecycle_args: dict[str, Any] | None,
    measurement: dict[str, Any],
    expected_events: list[dict[str, Any]],
    lifecycle_trace: list[str],
    expected_lifecycle_trace: list[str] | None,
) -> dict[str, Any]:
    if (lifecycle_args is None) != (expected_lifecycle_trace is None):
        raise ValueError("measured lifespan inputs and source probe trace must both be present")
    session = await _start_lifespan(app, lifecycle_args) if lifecycle_args is not None else None
    sample_means_ns: list[float] = []

    def verify_events(sent: list[dict[str, Any]], call_index: int) -> None:
        actual_events = [_canonical_message(message) for message in sent]
        if actual_events != expected_events:
            raise RuntimeError(
                f"dispatch call {call_index} changed its ASGI events after the correctness probe"
            )

    try:
        for call_index in range(measurement["warmup_iterations"]):
            sent = await _invoke_dispatch(app, dispatch_args)
            verify_events(sent, call_index)

        call_index = measurement["warmup_iterations"]
        for _ in range(measurement["samples"]):
            durations_ns: list[int] = []
            for _ in range(measurement["measurement_iterations"]):
                started = time.perf_counter_ns()
                sent = await _invoke_dispatch(app, dispatch_args)
                elapsed_ns = time.perf_counter_ns() - started
                verify_events(sent, call_index)
                durations_ns.append(elapsed_ns)
                call_index += 1
            sample_means_ns.append(statistics.fmean(durations_ns))
    finally:
        if session is not None:
            await session.close()
            _validate_lifespan_completion(session)
            if lifecycle_trace != expected_lifecycle_trace:
                raise RuntimeError(
                    "measured lifespan cleanup effects differ from the source correctness probe: "
                    f"{lifecycle_trace!r} != {expected_lifecycle_trace!r}"
                )

    quantiles = {
        "p50": _quantile(sample_means_ns, 0.50),
        "p95": _quantile(sample_means_ns, 0.95),
        "p99": _quantile(sample_means_ns, 0.99),
    }
    return {
        "unit": "nanoseconds_per_dispatch",
        "warmup_iterations": measurement["warmup_iterations"],
        "measurement_iterations_per_sample": measurement["measurement_iterations"],
        "samples": sample_means_ns,
        "statistics": {
            "median": statistics.median(sample_means_ns),
            "mean": statistics.fmean(sample_means_ns),
            "stdev": statistics.stdev(sample_means_ns) if len(sample_means_ns) > 1 else 0.0,
            "min": min(sample_means_ns),
            "max": max(sample_means_ns),
            **quantiles,
        },
    }


def _run_worker(request: Any) -> dict[str, Any]:
    request = _strict_object(
        request,
        {
            "schema",
            "subject_id",
            "mode",
            "workload_input",
            "parity_case_input",
            "measurement",
            "expected_observation",
        },
        "worker request",
    )
    if request["schema"] != REQUEST_SCHEMA:
        raise RuntimeError("worker request schema differs")
    subject_id = request["subject_id"]
    if subject_id not in {"starlette-python", "python-package-cpython312"}:
        raise RuntimeError("worker subject is not a declared Python benchmark target")
    if request["mode"] not in {"probe", "measure"}:
        raise RuntimeError("worker mode must be probe or measure")
    case, case_input_identity = _resolve_case(request)
    dispatch_step, lifecycle_step = _validate_case(case)
    dispatch_args = _step_arguments(dispatch_step)
    lifecycle_args = _step_arguments(lifecycle_step) if lifecycle_step is not None else None
    Starlette, probe = _resolve_modules(subject_id)
    app, endpoints, lifecycle_trace = _make_app(Starlette, case["steps"][0])
    capabilities = {
        "router_instance_is_asgi_callable": callable(app.router),
        "gzip_middleware_module_available": probe["gzip_middleware_module_available"],
    }
    loop = asyncio.new_event_loop()
    try:
        if request["mode"] == "probe":
            if request["measurement"] != {} or request["expected_observation"] is not None:
                raise RuntimeError(
                    "probe mode must not include measurement or expected observations"
                )
            observation = loop.run_until_complete(
                _run_probe(
                    app,
                    case,
                    dispatch_step,
                    lifecycle_step,
                    endpoints,
                    lifecycle_trace,
                )
            )
            return {
                "schema": RESULT_SCHEMA,
                "identity": probe["identity"],
                "capabilities": capabilities,
                "parity_case_input": case_input_identity,
                "observation": observation,
            }

        measurement = _validate_measurement(request["measurement"])
        expected_observation = _strict_object(
            request["expected_observation"],
            {"case_id", "status", "observations"},
            "expected probe observation",
        )
        if (
            expected_observation["case_id"] != case["case_id"]
            or expected_observation["status"] != "completed"
            or not isinstance(expected_observation["observations"], list)
        ):
            raise RuntimeError("expected probe observation differs from the resolved parity case")
        dispatch_observation = next(
            item["value"]
            for item in expected_observation["observations"]
            if item.get("step_id") == "dispatch"
        )
        expected_lifecycle_trace = None
        if lifecycle_args is not None:
            lifecycle_observation = next(
                item["value"]
                for item in expected_observation["observations"]
                if item.get("step_id") == "lifecycle"
            )
            expected_lifecycle_trace = lifecycle_observation["lifecycle_and_cleanup_effects"]
        benchmark_measurement = loop.run_until_complete(
            _run_measurement(
                app,
                dispatch_args,
                lifecycle_args,
                measurement,
                dispatch_observation["asgi_events"],
                lifecycle_trace,
                expected_lifecycle_trace,
            )
        )
        return {
            "schema": RESULT_SCHEMA,
            "identity": probe["identity"],
            "capabilities": capabilities,
            "parity_case_input": case_input_identity,
            "measurement": benchmark_measurement,
        }
    finally:
        loop.close()


def main() -> int:
    request = json.load(sys.stdin)
    result = _run_worker(request)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
