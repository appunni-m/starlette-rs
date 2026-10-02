"""Input-driven observations for the public ``FormData`` multidict interface."""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any


def _entries(entries: list[list[Any]], upload_file_type: type[Any]) -> list[tuple[str, Any]]:
    return [(key, _value(value, upload_file_type)) for key, value in entries]


def _value(value: Any, upload_file_type: type[Any]) -> Any:
    if isinstance(value, str):
        return value
    if value["kind"] == "upload-file":
        return upload_file_type(
            filename=value["filename"],
            file=BytesIO(base64.b64decode(value["body_base64"], validate=True)),
            size=value["size"],
        )
    raise ValueError(f"unsupported FormData value kind: {value['kind']!r}")


def _materialize(
    spec: dict[str, Any],
    form_data_type: type[Any],
    upload_file_type: type[Any],
    primary: Any,
) -> Any:
    kind = spec["kind"]
    if kind == "pairs":
        return _entries(spec["entries"], upload_file_type)
    if kind == "mapping":
        return dict(_entries(spec["entries"], upload_file_type))
    if kind == "primary":
        return primary
    if kind == "form-data":
        args = [
            _materialize(argument, form_data_type, upload_file_type, primary)
            for argument in spec["args"]
        ]
        kwargs = dict(_entries(spec["kwargs"], upload_file_type))
        return form_data_type(*args, **kwargs)
    raise ValueError(f"unsupported FormData input kind: {kind!r}")


def _stable(value: Any, upload_file_type: type[Any]) -> Any:
    if isinstance(value, upload_file_type):
        return {
            "type": f"{type(value).__module__}.{type(value).__qualname__}",
            "repr": repr(value),
        }
    return value


def _constructor_snapshot(
    case: dict[str, Any], form_data_type: type[Any], upload_file_type: type[Any]
) -> dict[str, Any]:
    constructor = case["constructor"]
    args = [
        _materialize(argument, form_data_type, upload_file_type, None)
        for argument in constructor["args"]
    ]
    kwargs = dict(_entries(constructor["kwargs"], upload_file_type))
    try:
        form = form_data_type(*args, **kwargs)
    except Exception as error:
        return {
            "constructor": {
                "outcome": "error",
                "error": {
                    "class": f"{type(error).__module__}.{type(error).__qualname__}",
                    "message": str(error),
                },
            }
        }

    def stable(value: Any) -> Any:
        return _stable(value, upload_file_type)

    getitems = []
    for key in case["probe_keys"]:
        if key not in form:
            getitem = {"outcome": "missing"}
        else:
            try:
                value = form[key]
            except Exception as error:
                getitem = {
                    "outcome": "error",
                    "error": {
                        "class": f"{type(error).__module__}.{type(error).__qualname__}",
                        "message": str(error),
                    },
                }
            else:
                getitem = {"outcome": "value", "value": stable(value)}
        getitems.append(
            {
                "key": key,
                "contains": key in form,
                "get": stable(form.get(key)),
                "getlist": [stable(value) for value in form.getlist(key)],
                "getitem": getitem,
            }
        )

    equalities = []
    for comparison in case["equalities"]:
        left = _materialize(comparison["left"], form_data_type, upload_file_type, form)
        right = _materialize(comparison["right"], form_data_type, upload_file_type, form)
        equalities.append(
            {
                "left_kind": comparison["left"]["kind"],
                "right_kind": comparison["right"]["kind"],
                "equal": left == right,
            }
        )

    return {
        "constructor": {"outcome": "value"},
        "snapshot": {
            "multi_items": [[key, stable(value)] for key, value in form.multi_items()],
            "keys": list(form.keys()),
            "values": [stable(value) for value in form.values()],
            "items": [[key, stable(value)] for key, value in form.items()],
            "length": len(form),
            "iteration": list(form),
            "dict": {key: stable(value) for key, value in dict(form).items()},
            "repr": repr(form),
            "probes": getitems,
            "equalities": equalities,
        },
    }


def run_formdata_case(
    case: dict[str, Any],
    form_data_type: type[Any],
    upload_file_type: type[Any],
) -> dict[str, Any]:
    """Construct FormData from case inputs and observe public mapping operations."""
    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "multidict-lookups",
                "status": "ok",
                "value": {
                    "multidict-lookups": _constructor_snapshot(
                        case, form_data_type, upload_file_type
                    )
                },
            }
        ],
    }
