"""Runner-owned assertions for deterministic target fault contracts."""

from __future__ import annotations

import base64
from typing import Any

FAULT_POINT_IDS = frozenset(
    {
        "starlette-rs.router.route-cache-lock.poison",
        "starlette-rs.native-lifespan.shutdown-error-aggregation",
        "starlette-rs.native-lifespan.start-future-drop",
        "starlette-rs.native-lifespan.shutdown-future-drop",
    }
)
FAULT_CONTRACT_ASSERTIONS = {
    "starlette.server-error.route-cache-lock-poison": (
        "public-http-status-500",
        "public-http-body-internal-server-error",
    ),
    "starlette.testclient.route-cache-lock-poison-propagates": (
        "public-testclient-exception-propagated",
    ),
    "starlette-rs.native-lifespan.shutdown-error-aggregation": (
        "public-shutdown-errors-preserved-in-execution-order",
    ),
    "starlette-rs.native-lifespan.start-future-drop": (
        "public-start-future-drop-stops-at-suspension",
    ),
    "starlette-rs.native-lifespan.shutdown-future-drop": (
        "public-shutdown-future-drop-stops-at-deadline",
    ),
}
FAULT_CONTRACT_TESTCLIENT_RAISE_SERVER_EXCEPTIONS = {
    "starlette.server-error.route-cache-lock-poison": False,
    "starlette.testclient.route-cache-lock-poison-propagates": True,
}


def evaluate_fault_contract(
    contract_id: str,
    result: dict[str, Any],
    case: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Evaluate named public-outcome assertions without consulting fixture expectations."""
    assertion_ids = FAULT_CONTRACT_ASSERTIONS.get(contract_id)
    if assertion_ids is None:
        raise ValueError(f"unknown fault contract: {contract_id}")

    if contract_id.startswith("starlette-rs.native-lifespan."):
        return _evaluate_native_lifespan_fault(contract_id, result, case, assertion_ids)

    observation = next(
        (item for item in result["observations"] if item.get("step_id") == "request-response"),
        None,
    )
    if contract_id == "starlette.testclient.route-cache-lock-poison-propagates":
        error = observation.get("error") if isinstance(observation, dict) else None
        propagated = (
            isinstance(observation, dict)
            and observation.get("status") == "error"
            and isinstance(error, dict)
            and error.get("kind") == "exception"
        )
        return [
            {
                "id": "public-testclient-exception-propagated",
                "status": "pass" if propagated else "fail",
            }
        ]

    observation = (
        observation if isinstance(observation, dict) and observation.get("status") == "ok" else None
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


def _evaluate_native_lifespan_fault(
    contract_id: str,
    result: dict[str, Any],
    case: dict[str, Any] | None,
    assertion_ids: tuple[str, ...],
) -> list[dict[str, str]]:
    if case is None:
        raise ValueError("native lifespan fault assertions require the input case")
    observation = next(
        (item for item in result["observations"] if item.get("step_id") == "workflow"),
        None,
    )
    record = (
        observation.get("value", {}).get("workflow")
        if isinstance(observation, dict) and isinstance(observation.get("value"), dict)
        else None
    )
    inputs = case.get("inputs")
    registrations = inputs.get("registrations") if isinstance(inputs, dict) else None
    if not isinstance(record, dict) or not isinstance(registrations, list):
        return [{"id": assertion_id, "status": "fail"} for assertion_id in assertion_ids]

    if contract_id == "starlette-rs.native-lifespan.shutdown-error-aggregation":
        expected_failures: list[dict[str, Any]] = []
        for hook_index in range(len(registrations) - 1, -1, -1):
            registration = registrations[hook_index]
            shutdown = registration.get("shutdown") if isinstance(registration, dict) else None
            actions = shutdown.get("actions") if isinstance(shutdown, dict) else None
            if not isinstance(actions, list):
                continue
            for action in actions:
                error = action.get("raise") if isinstance(action, dict) else None
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    expected_failures.append(
                        {"hook_index": hook_index, "message": error["message"]}
                    )
                    break
        failure = record.get("shutdown-failure")
        actual_failures = failure.get("failures") if isinstance(failure, dict) else None
        passed = len(expected_failures) >= 2 and actual_failures == expected_failures
        return [{"id": assertion_ids[0], "status": "pass" if passed else "fail"}]

    phases = [("startup", range(len(registrations)))]
    if contract_id == "starlette-rs.native-lifespan.shutdown-future-drop":
        phases.append(("shutdown", range(len(registrations) - 1, -1, -1)))

    expected_events: list[str] = []
    reached_pending_hook = False
    for phase, hook_indexes in phases:
        for hook_index in hook_indexes:
            registration = registrations[hook_index]
            hook = registration.get(phase) if isinstance(registration, dict) else None
            actions = hook.get("actions") if isinstance(hook, dict) else None
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                event = action.get("append-event")
                if isinstance(event, str):
                    expected_events.append(event)
                if action.get("suspend-until-host-release") is True:
                    reached_pending_hook = True
                    break
            if reached_pending_hook:
                break
        if reached_pending_hook:
            break

    event_field = record.get("lifecycle-event-sequence")
    no_reported_failure = (
        record.get("startup-failure") is None and record.get("shutdown-failure") is None
    )
    passed = reached_pending_hook and event_field == expected_events and no_reported_failure
    return [{"id": assertion_ids[0], "status": "pass" if passed else "fail"}]
