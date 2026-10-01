"""Public-consumer observation for ``CommaSeparatedStrings`` inputs."""

from __future__ import annotations

from typing import Any


def run_comma_separated_strings_case(case: dict[str, Any], value_type: type[Any]) -> dict[str, Any]:
    """Construct values from the supplied inputs and observe sequence formats."""
    instances = []
    for input_spec in case["inputs"]:
        if input_spec["kind"] in {
            "string",
            "shlex-edge-string",
            "unicode-repr-string",
            "surrogate-string",
            "malformed-string",
        }:
            value = input_spec["value"]
        elif input_spec["kind"] == "sequence-subclass":
            suffixes = input_spec["repr_suffixes"]

            class InputString(str):
                def __new__(cls, item: str, suffix: str) -> InputString:
                    value = super().__new__(cls, item)
                    value.suffix = suffix
                    return value

                def __repr__(self) -> str:
                    return f"{super().__repr__()}<{self.suffix}>"

            value = [
                InputString(item, suffix)
                for item, suffix in zip(input_spec["items"], suffixes, strict=True)
            ]
        else:
            value = input_spec["items"]
        try:
            instance = value_type(value)
        except Exception as error:
            instances.append(
                {
                    "kind": input_spec["kind"],
                    "error": {
                        "class": type(error).__name__,
                        "message": str(error),
                    },
                }
            )
        else:
            snapshot = {
                "kind": input_spec["kind"],
                "items": list(instance),
                "length": len(instance),
                "indexed": [
                    {"index": index, "value": instance[index]} for index in case["index_probes"]
                ],
                "str": str(instance),
                "repr": repr(instance),
            }
            if input_spec["kind"] == "sequence-subclass":
                snapshot["identities"] = [
                    instance[index] is item for index, item in enumerate(value)
                ]
            instances.append(snapshot)

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "snapshot",
                "status": "ok",
                "value": {"snapshot": {"instances": instances}},
            }
        ],
    }
