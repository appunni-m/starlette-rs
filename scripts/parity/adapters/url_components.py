"""Input-driven adapter for public ``starlette.datastructures.URL`` behavior."""

from __future__ import annotations

from typing import Any

URL_RECORD_STEP = "url-record"
ACTION_RESULTS_STEP = "action-results"
OBSERVATION_STEPS = frozenset({URL_RECORD_STEP, ACTION_RESULTS_STEP})


def run_url_components_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run URL construction and ordered component replacements from input data.

    The caller selects this helper by the manifest operation. This function
    imports the public ``URL`` facade from the currently active oracle or
    target environment and never selects stimulus values by case identifier.
    """
    from starlette.datastructures import URL

    url = URL(case["url"])
    initial_record = _url_record(url)
    action_results: list[dict[str, Any]] = []

    for action in case["actions"]:
        try:
            updated = url.replace(**action["kwargs"])
        except Exception as exc:
            action_results.append(
                {
                    "method": "replace",
                    "outcome": "error",
                    "error": _error_snapshot(exc),
                }
            )
        else:
            url = updated
            action_results.append(
                {
                    "method": "replace",
                    "outcome": "value",
                    "url-record": _url_record(url),
                }
            )

    available = {
        URL_RECORD_STEP: initial_record,
        ACTION_RESULTS_STEP: action_results,
    }
    observations: list[dict[str, Any]] = []
    for step_id in case["observations"]:
        if step_id not in OBSERVATION_STEPS:
            raise ValueError(f"unsupported URL component observation: {step_id!r}")
        observations.append({"step_id": step_id, "status": "ok", "value": available})

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": observations,
    }


def _url_record(url: Any) -> dict[str, Any]:
    return {
        "url": str(url),
        "repr": repr(url),
        "scheme": url.scheme,
        "netloc": url.netloc,
        "path": url.path,
        "query": url.query,
        "fragment": url.fragment,
        "username": url.username,
        "password": url.password,
        "hostname": url.hostname,
        "port": url.port,
        "is_secure": url.is_secure,
    }


def _error_snapshot(exc: Exception) -> dict[str, str]:
    return {
        "class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": str(exc),
    }
