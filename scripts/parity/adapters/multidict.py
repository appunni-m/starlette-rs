"""Input-driven consumer adapter for Starlette's mutable multi-dictionary."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Any


def _construct(multidict_type: Any, source: dict[str, Any]) -> Any:
    kind = source["kind"]
    if kind == "empty":
        return multidict_type()
    if kind == "pairs":
        return multidict_type([tuple(pair) for pair in source["items"]], **dict(source["kwargs"]))
    if kind == "mapping":
        return multidict_type(dict(source["items"]))
    original = multidict_type([tuple(pair) for pair in source["items"]])
    return multidict_type(original)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return {
        "python_type": f"{type(value).__module__}.{type(value).__qualname__}",
        "repr": repr(value),
    }


def _snapshot(value: Any, probe_keys: list[Any]) -> dict[str, Any]:
    return {
        "str": str(value),
        "repr": repr(value),
        "len": len(value),
        "is_empty": not value,
        "keys": list(value.keys()),
        "values": list(value.values()),
        "items": list(value.items()),
        "multi_items": value.multi_items(),
        "dict": dict(value),
        "lookups": [
            {
                "key": key,
                "contains": key in value,
                "get": value.get(key),
                "get_with_default": value.get(key, "__starlette_rs_default__"),
                "getlist": value.getlist(key),
                "getitem": value[key] if key in value else None,
            }
            for key in probe_keys
        ],
    }


def _typecheck_consumer(contract: dict[str, Any]) -> dict[str, Any]:
    import starlette

    executable = os.environ.get("STARLETTE_PARITY_TYPECHECKER")
    if executable is None or not Path(executable).is_file():
        raise RuntimeError("the pinned parity type-checker executable is not configured")

    source_lines = [
        "from starlette.datastructures import ImmutableMultiDict, MultiDict",
        "",
    ]
    reveal_lines: dict[int, str] = {}
    expected_reveals: set[str] = set()
    for probe in contract["probes"]:
        if probe == "immutable-mapping-reads":
            source_lines.append("def immutable_reads(value: ImmutableMultiDict[str, int]) -> None:")
            for name, expression in (
                ("immutable_getitem", "value['tag']"),
                ("immutable_getlist", "value.getlist('tag')"),
                ("immutable_keys", "value.keys()"),
                ("immutable_values", "value.values()"),
                ("immutable_items", "value.items()"),
                ("immutable_multi_items", "value.multi_items()"),
            ):
                source_lines.append(f"    reveal_type({expression})")
                reveal_lines[len(source_lines)] = name
                expected_reveals.add(name)
            source_lines.append("")
        elif probe == "mutable-mutation-methods":
            source_lines.extend(
                [
                    "def mutable_operations(value: MultiDict) -> None:",
                    "    value['tag'] = 1",
                    "    value.setlist('tag', [1, 2])",
                    "    value.append('tag', 3)",
                    "    value.update({'tag': 4})",
                    "    reveal_type(value.pop('tag'))",
                    "",
                ]
            )
            reveal_lines[len(source_lines) - 1] = "mutable_pop"
            expected_reveals.add("mutable_pop")

    package_root = Path(starlette.__file__).resolve().parent.parent
    environment = dict(os.environ)
    installed_roots = {
        Path(path).resolve()
        for name, path in sysconfig.get_paths().items()
        if name in {"purelib", "platlib"}
    }
    if package_root in installed_roots:
        environment.pop("MYPYPATH", None)
    else:
        environment["MYPYPATH"] = str(package_root)
    tool_version = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if tool_version.returncode != 0:
        raise RuntimeError(
            f"the parity type checker failed to report its version: {tool_version.stderr}"
        )

    lock_path = Path(__file__).resolve().parents[1] / "locks" / "typecheck-cpython312.txt"
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="starlette-rs-multidict-types-") as directory:
        temporary_path = Path(directory)
        source_path = temporary_path / "multidict_types.py"
        source_path.write_text("\n".join(source_lines), encoding="utf-8")
        config_path = temporary_path / "mypy.ini"
        config_path.write_text("[mypy]\nfollow_imports = silent\n", encoding="utf-8")
        process = subprocess.run(
            [
                executable,
                "--config-file",
                str(config_path),
                "--python-executable",
                sys.executable,
                "--no-incremental",
                "--no-error-summary",
                "--show-column-numbers",
                "--show-error-codes",
                "--no-pretty",
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
            check=False,
        )

    diagnostics: list[dict[str, Any]] = []
    for line in (process.stdout + process.stderr).splitlines():
        match = re.match(
            r"^.*?:(?P<line>\d+)(?::(?P<column>\d+))?: "
            r"(?P<severity>error|note|warning): (?P<message>.*)$",
            line,
        )
        if match is None:
            if line:
                diagnostics.append(
                    {"name": None, "line": None, "severity": "output", "message": line}
                )
            continue
        message = match["message"]
        code_match = re.search(r" \[([a-z0-9-]+)\]$", message)
        diagnostics.append(
            {
                "name": reveal_lines.get(int(match["line"])),
                "line": int(match["line"]),
                "severity": match["severity"],
                "code": code_match[1] if code_match else None,
                "message": message[: code_match.start()] if code_match else message,
            }
        )
    revealed = {
        diagnostic["name"]
        for diagnostic in diagnostics
        if diagnostic["severity"] == "note" and diagnostic["name"] is not None
    }
    if process.returncode != 0 or revealed != expected_reveals:
        raise RuntimeError(
            "input-defined MultiDict typing consumers must pass and reveal every declared access; "
            f"exit_code={process.returncode}, diagnostics={diagnostics!r}"
        )
    return {
        "checker": tool_version.stdout.strip(),
        "checker_lock_sha256": lock_digest,
        "exit_code": process.returncode,
        "diagnostics": diagnostics,
    }


def run_multidict_case(case: dict[str, Any], multidict_type: Any) -> dict[str, Any]:
    """Run constructor and mutator inputs through the supplied public class."""
    value = _construct(multidict_type, case["source"])
    comparison_input = case["comparison"]
    comparison = None if comparison_input is None else _construct(multidict_type, comparison_input)
    initial = _snapshot(value, case["probe_keys"])
    trace: list[dict[str, Any]] = []
    for action in case["actions"]:
        result = {"action_id": action["action_id"], "method": action["method"]}
        try:
            arguments = action.get("args", [])
            if action["method"] == "update" and arguments:
                if arguments[0] == {"kind": "receiver"}:
                    arguments = [value]
                else:
                    arguments = [[tuple(pair) for pair in arguments[0]]]
            output = getattr(value, action["method"])(*arguments, **action.get("kwargs", {}))
        except Exception as error:
            result.update(
                {
                    "outcome": "error",
                    "error": {
                        "class": f"{type(error).__module__}.{type(error).__qualname__}",
                        "message": str(error),
                    },
                }
            )
        else:
            result.update({"outcome": "value", "value": _json_value(output)})
        result["snapshot"] = _snapshot(value, case["probe_keys"])
        trace.append(result)
    result = {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "mutation-sequence",
                "status": "ok",
                "value": {
                    "mutation-sequence": {
                        "initial": initial,
                        "action_trace": trace,
                        "final": _snapshot(value, case["probe_keys"]),
                        "comparison_repr": None if comparison is None else repr(comparison),
                        "equals_comparison": None if comparison is None else value == comparison,
                    }
                },
            }
        ],
    }
    if "typing_contract" in case:
        result["observations"][0]["value"]["typing_contract"] = _typecheck_consumer(
            case["typing_contract"]
        )
    return result
