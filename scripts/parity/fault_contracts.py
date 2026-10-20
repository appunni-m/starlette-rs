"""Runner-owned assertions for deterministic target fault contracts."""

from __future__ import annotations

import base64
from typing import Any

FAULT_POINT_IDS = frozenset(
    {
        "starlette-rs.router.route-cache-lock.poison",
        "starlette-rs.file-response.random-source.failure",
        "starlette-rs.native-lifespan.shutdown-error-aggregation",
        "starlette-rs.native-lifespan.start-future-drop",
        "starlette-rs.native-lifespan.shutdown-future-drop",
        "starlette-rs.native-lifespan.duplicate-state-key",
        "starlette-rs.native-lifespan.state-type-mismatch",
        "starlette-rs.native-websocket.unoffered-subprotocol",
        "starlette-rs.native-websocket.invalid-close-code",
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
    "starlette-rs.file-response.random-source-error": (
        "public-file-response-random-source-error-class",
        "public-file-response-random-source-error-message",
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
    "starlette-rs.native-lifespan.duplicate-state-key": (
        "public-lifespan-duplicate-state-key-error",
    ),
    "starlette-rs.native-lifespan.state-type-mismatch": (
        "public-lifespan-state-type-mismatch-error",
    ),
    "starlette-rs.native-websocket.unoffered-subprotocol": (
        "public-websocket-unoffered-subprotocol-rejected",
    ),
    "starlette-rs.native-websocket.invalid-close-code": (
        "public-websocket-invalid-close-code-rejected",
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
        if contract_id in {
            "starlette-rs.native-lifespan.duplicate-state-key",
            "starlette-rs.native-lifespan.state-type-mismatch",
        }:
            return _evaluate_native_lifespan_state_fault(contract_id, result, case, assertion_ids)
        return _evaluate_native_lifespan_fault(contract_id, result, case, assertion_ids)

    if contract_id.startswith("starlette-rs.native-websocket."):
        return _evaluate_native_websocket_fault(contract_id, result, case, assertion_ids)

    if contract_id == "starlette-rs.file-response.random-source-error":
        observation = next(
            (item for item in result["observations"] if item.get("step_id") == "asgi-call"),
            None,
        )
        value = (
            observation.get("value")
            if isinstance(observation, dict) and observation.get("status") == "ok"
            else None
        )
        error = value.get("dispatch_error") if isinstance(value, dict) else None
        outcomes = {
            "public-file-response-random-source-error-class": (
                isinstance(error, dict)
                and error.get("kind") == "exception"
                and error.get("class") == "builtins.RuntimeError"
                and error.get("stage") == "dispatch"
            ),
            "public-file-response-random-source-error-message": (
                isinstance(error, dict)
                and error.get("message") == "could not generate multipart boundary"
            ),
        }
        return [
            {
                "id": assertion_id,
                "status": "pass" if outcomes[assertion_id] else "fail",
            }
            for assertion_id in assertion_ids
        ]

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


def _workflow_record(result: dict[str, Any]) -> dict[str, Any] | None:
    observation = next(
        (item for item in result.get("observations", []) if item.get("step_id") == "workflow"),
        None,
    )
    value = observation.get("value") if isinstance(observation, dict) else None
    workflow = value.get("workflow") if isinstance(value, dict) else None
    return workflow if isinstance(workflow, dict) else None


def _evaluate_native_lifespan_state_fault(
    contract_id: str,
    result: dict[str, Any],
    case: dict[str, Any] | None,
    assertion_ids: tuple[str, ...],
) -> list[dict[str, str]]:
    if case is None:
        raise ValueError("native lifespan state assertions require the input case")
    record = _workflow_record(result)
    inputs = case.get("inputs")
    registrations = inputs.get("registrations") if isinstance(inputs, dict) else None
    if not isinstance(record, dict) or not isinstance(registrations, list):
        return [{"id": assertion_id, "status": "fail"} for assertion_id in assertion_ids]

    startup_failure = record.get("startup-failure")
    message = startup_failure.get("message") if isinstance(startup_failure, dict) else None
    if not isinstance(message, str):
        passed = False
    elif contract_id == "starlette-rs.native-lifespan.duplicate-state-key":
        inserted_keys = [
            action["insert-state"].get("key")
            for registration in registrations
            if isinstance(registration, dict)
            for action in registration.get("startup", {}).get("actions", [])
            if isinstance(action, dict) and isinstance(action.get("insert-state"), dict)
        ]
        repeated_key = next(
            (key for index, key in enumerate(inserted_keys) if key in inserted_keys[:index]),
            None,
        )
        passed = (
            isinstance(repeated_key, str)
            and repeated_key in message
            and "already exists" in message
        )
    else:
        lookup = next(
            (
                action.get(action_name)
                for registration in registrations
                if isinstance(registration, dict)
                for action in registration.get("startup", {}).get("actions", [])
                if isinstance(action, dict)
                for action_name in ("get-state-as", "remove-state-as")
                if isinstance(action.get(action_name), dict)
            ),
            None,
        )
        mismatch_key = lookup.get("key") if isinstance(lookup, dict) else None
        passed = (
            isinstance(mismatch_key, str)
            and mismatch_key in message
            and "has type" in message
            and "requested as" in message
        )
    return [{"id": assertion_ids[0], "status": "pass" if passed else "fail"}]


def _evaluate_native_websocket_fault(
    contract_id: str,
    result: dict[str, Any],
    case: dict[str, Any] | None,
    assertion_ids: tuple[str, ...],
) -> list[dict[str, str]]:
    if case is None:
        raise ValueError("native WebSocket assertions require the input case")
    record = _workflow_record(result)
    input_spec = case.get("input")
    actions = input_spec.get("actions") if isinstance(input_spec, dict) else None
    handshake = input_spec.get("handshake") if isinstance(input_spec, dict) else None
    if (
        not isinstance(record, dict)
        or not isinstance(actions, list)
        or not isinstance(handshake, dict)
    ):
        passed = False
    elif contract_id == "starlette-rs.native-websocket.unoffered-subprotocol":
        action = next(
            (
                item
                for item in actions
                if isinstance(item, dict) and item.get("action") == "accept-selected"
            ),
            None,
        )
        selected = action.get("subprotocol") if isinstance(action, dict) else None
        offered = handshake.get("offered_subprotocols")
        passed = (
            isinstance(selected, str)
            and isinstance(offered, list)
            and selected not in offered
            and record.get("application_result.error_kind") == "unoffered-subprotocol"
            and record.get("handshake.acceptance") is None
        )
    else:
        close = next(
            (item for item in actions if isinstance(item, dict) and item.get("action") == "close"),
            None,
        )
        code = close.get("code") if isinstance(close, dict) else None
        valid_code = type(code) is int and (
            (1000 <= code <= 1014 and code not in {1004, 1005, 1006}) or 3000 <= code <= 4999
        )
        passed = (
            type(code) is int
            and not valid_code
            and record.get("handshake.acceptance") is not None
            and record.get("session.close") is None
            and record.get("application_result.error_kind") == "invalid-close-code"
        )
    return [{"id": assertion_ids[0], "status": "pass" if passed else "fail"}]
