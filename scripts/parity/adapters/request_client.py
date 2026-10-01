"""Input-driven observations for ``Request.client`` address projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _observe_client(
    scope_id: str,
    scope: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    client = request_type(dict(scope)).client
    observation = {
        "scope_id": scope_id,
        "is_none": client is None,
        "type": type(client).__name__,
        "value": None,
        "host": None,
        "port": None,
    }
    if client is not None:
        observation.update(
            {
                "value": list(client),
                "host": client.host,
                "port": client.port,
            }
        )
    return observation


def run_request_client_case(
    case: dict[str, Any],
    request_type: Callable[..., Any],
) -> dict[str, Any]:
    """Construct a Request for each supplied scope and read its client address."""
    client_observations = [
        _observe_client(scope_case["scope_id"], scope_case["scope"], request_type)
        for scope_case in case["scope_cases"]
    ]
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "client-addresses",
                "status": "ok",
                "value": {"client-addresses": client_observations},
            }
        ],
    }
