"""Run input-authored Starlette consumer snippets with the pinned Mypy checker."""

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

TYPING_OPERATION = "typing-consumer"
TYPING_SURFACES = {
    "starlette.applications.Starlette",
    "starlette.responses.Response",
}
TYPING_OBSERVATION = "typing_consumer"
_DIAGNOSTIC = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<column>\d+))?: "
    r"(?P<severity>error|note|warning): (?P<message>.*)$"
)


def _normalized_file(value: str, *, source_root: Path, consumer_path: Path) -> str:
    path = Path(value)
    if path == consumer_path:
        return "consumer.py"
    try:
        return path.resolve().relative_to(source_root).as_posix()
    except (OSError, ValueError):
        return value


def _diagnostics(
    output: str,
    *,
    source_root: Path,
    consumer_path: Path,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = _DIAGNOSTIC.match(line)
        if match is None:
            if line:
                diagnostics.append(
                    {
                        "file": None,
                        "line": None,
                        "column": None,
                        "severity": "output",
                        "code": None,
                        "message": line,
                    }
                )
            continue
        message = match["message"]
        code_match = re.search(r" \[([a-z0-9-]+)\]$", message)
        diagnostics.append(
            {
                "file": _normalized_file(
                    match["file"],
                    source_root=source_root,
                    consumer_path=consumer_path,
                ),
                "line": int(match["line"]),
                "column": int(match["column"]) if match["column"] else None,
                "severity": match["severity"],
                "code": code_match[1] if code_match else None,
                "message": message[: code_match.start()] if code_match else message,
            }
        )
    return diagnostics


def run_application_typing_case(case: dict[str, Any]) -> dict[str, Any]:
    """Type-check the exact Python consumer source supplied by a parity input."""
    if case.get("surface") not in TYPING_SURFACES or case.get("operation") != TYPING_OPERATION:
        raise ValueError("Starlette typing adapter received an unrelated operation")

    import starlette

    executable = os.environ.get("STARLETTE_PARITY_TYPECHECKER")
    if executable is None or not Path(executable).is_file():
        raise RuntimeError("the pinned parity type-checker executable is not configured")

    source = case["typing_consumer"]["source"]
    if not isinstance(source, str) or not source.strip():
        raise ValueError("typing_consumer.source must be non-empty Python source text")

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

    version = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=environment,
    )
    if version.returncode != 0:
        raise RuntimeError(
            f"the parity type checker failed to report its version: {version.stderr}"
        )

    lock_path = Path(__file__).resolve().parents[1] / "locks" / "typecheck-cpython312.txt"
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="starlette-rs-application-types-") as temporary:
        directory = Path(temporary)
        config_path = directory / "mypy.ini"
        config_path.write_text("[mypy]\nfollow_imports = silent\n", encoding="utf-8")
        consumer_path = directory / "consumer.py"
        consumer_path.write_text(source, encoding="utf-8")
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
                str(consumer_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=environment,
            check=False,
        )
        if process.returncode not in {0, 1}:
            raise RuntimeError(
                "the pinned type checker could not analyze the input-defined consumer: "
                f"exit_code={process.returncode}, "
                f"output={(process.stdout + process.stderr)!r}"
            )
        diagnostics = _diagnostics(
            process.stdout + process.stderr,
            source_root=package_root,
            consumer_path=consumer_path,
        )

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": TYPING_OBSERVATION,
                "status": "ok",
                "value": {
                    TYPING_OBSERVATION: {
                        "checker": version.stdout.strip(),
                        "checker_lock_sha256": lock_digest,
                        "exit_code": process.returncode,
                        "diagnostics": diagnostics,
                    }
                },
            }
        ],
    }
