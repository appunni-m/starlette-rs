"""Input-only public TestClient construction and lifespan consumers."""

from __future__ import annotations

import threading
from typing import Any


def run_testclient_public_case(case: dict[str, Any]) -> dict[str, Any]:
    if case["consumer"]["kind"] == "managed-router-requests":
        from scripts.parity.adapters.testclient_router import run_router_client_case

        return run_router_client_case(case)

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    application = case["application"]
    consumer = case["consumer"]
    trace: list[dict[str, Any]] = []
    portal_thread: threading.Thread | None = None
    injected_error: Exception | None = None

    if application["kind"] == "routed-json":
        route = application["route"]

        def endpoint(request: Any) -> Any:
            trace.append({"operation": "endpoint", "path": request.url.path})
            return JSONResponse(route["response"])

        app = Starlette(routes=[Route(route["path"], endpoint=endpoint)])
    else:
        specification = application["exception"]
        error_type = type(specification["name"], (Exception,), {"__module__": __name__})
        injected_error = error_type(*specification["args"])

        class RaisingMiddleware:
            def __init__(self, app: Any) -> None:
                self.app = app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                nonlocal portal_thread
                portal_thread = threading.current_thread()
                trace.append({"operation": "middleware", "scope_type": scope["type"]})
                raise injected_error

        app = Starlette(middleware=[Middleware(RaisingMiddleware)])

    samples: list[dict[str, Any]] = []
    context_result: dict[str, Any] | None = None
    if consumer["kind"] == "constructor-headers":
        for specification in consumer["samples"]:
            client = TestClient(app, **specification["kwargs"])
            try:
                samples.append(
                    {
                        "headers": client.headers.multi_items(),
                        "lookups": {
                            name: client.headers.get(name) for name in specification["lookups"]
                        },
                    }
                )
            finally:
                client.close()
            samples[-1]["is_closed"] = client.is_closed
    else:
        client = TestClient(app, **consumer["kwargs"])
        entered = False
        captured_error: dict[str, Any] | None = None
        try:
            with client:
                entered = True
        except Exception as error:
            captured_error = {
                "class": f"{type(error).__module__}.{type(error).__qualname__}",
                "args": list(error.args),
                "message": str(error),
                "is_injected_exception": error is injected_error,
                "cause": (
                    None
                    if error.__cause__ is None
                    else {
                        "class": f"{type(error.__cause__).__module__}.{type(error.__cause__).__qualname__}",
                        "message": str(error.__cause__),
                    }
                ),
                "suppress_context": error.__suppress_context__,
            }
        finally:
            client.close()
        context_result = {
            "entered": entered,
            "error": captured_error,
            "portal_thread_alive_after_exit": (
                None if portal_thread is None else portal_thread.is_alive()
            ),
            "is_closed": client.is_closed,
        }

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": case["operation"],
                "status": "ok",
                "value": {
                    "samples": samples,
                    "application_trace": trace,
                    "context": context_result,
                    "responses": [],
                    "asgi_scopes": [],
                    "asgi_events": [],
                },
            }
        ],
    }
