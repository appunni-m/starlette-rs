"""Runner-owned assertions for deterministic target fault contracts."""

from __future__ import annotations

import base64
from typing import Any

FAULT_POINT_IDS = frozenset({"starlette-rs.router.route-cache-lock.poison"})
FAULT_CONTRACT_ASSERTIONS = {
    "starlette.server-error.route-cache-lock-poison": (
        "public-http-status-500",
        "public-http-body-internal-server-error",
    ),
}


def evaluate_fault_contract(contract_id: str, result: dict[str, Any]) -> list[dict[str, str]]:
    """Evaluate named public-outcome assertions without consulting fixture expectations."""
    assertion_ids = FAULT_CONTRACT_ASSERTIONS.get(contract_id)
    if assertion_ids is None:
        raise ValueError(f"unknown fault contract: {contract_id}")

    observation = next(
        (
            item
            for item in result["observations"]
            if item.get("step_id") == "request-response" and item.get("status") == "ok"
        ),
        None,
    )
    response = (
        observation["value"].get("response")
        if observation is not None and isinstance(observation.get("value"), dict)
        else None
    )
    if not isinstance(response, dict):
        actual_status = None
        actual_body = None
    else:
        actual_status = response.get("status_code")
        encoded_body = response.get("body_base64")
        try:
            actual_body = base64.b64decode(encoded_body, validate=True)
        except (ValueError, TypeError):
            actual_body = None

    outcomes = {
        "public-http-status-500": actual_status == 500,
        "public-http-body-internal-server-error": actual_body == b"Internal Server Error",
    }
    return [
        {"id": assertion_id, "status": "pass" if outcomes[assertion_id] else "fail"}
        for assertion_id in assertion_ids
    ]
