"""Live mypy consumer comparison for ExceptionMiddleware handler annotations."""

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


def _handler_definition(handler: dict[str, Any]) -> list[str]:
    declaration = "async def" if handler["callable_kind"] == "async" else "def"
    signature = (
        f"{declaration} {handler['name']}"
        f"(connection: {handler['connection_type']}, "
        f"exception: {handler['exception_type']}) -> {handler['return_type']}:"
    )
    if handler["return_type"] == "JSONResponse":
        body = "    return JSONResponse({})"
    elif handler["return_type"] == "Response":
        body = "    return Response()"
    else:
        body = "    return 1"
    return [signature, body, ""]


def _diagnostics(output: str, labeled_lines: dict[int, str]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = re.match(
            r"^.*?:(?P<line>\d+)(?::(?P<column>\d+))?: "
            r"(?P<severity>error|note|warning): (?P<message>.*)$",
            line,
        )
        if match is None:
            if line:
                diagnostics.append(
                    {
                        "name": None,
                        "line": None,
                        "severity": "output",
                        "code": None,
                        "message": line,
                    }
                )
            continue
        message = match["message"]
        code_match = re.search(r" \[([a-z0-9-]+)\]$", message)
        line_number = int(match["line"])
        diagnostics.append(
            {
                "name": labeled_lines.get(line_number),
                "line": line_number,
                "severity": match["severity"],
                "code": code_match[1] if code_match else None,
                "message": message[: code_match.start()] if code_match else message,
            }
        )
    return diagnostics


def _run_probe(
    executable: str,
    python_executable: str,
    environment: dict[str, str],
    config_path: Path,
    directory: Path,
    contract: dict[str, Any],
    registration: dict[str, Any],
    handlers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_lines = [
        "from starlette.middleware.exceptions import ExceptionMiddleware",
        "from starlette.requests import Request",
        "from starlette.responses import JSONResponse, Response",
        "from starlette.types import Receive, Scope, Send",
        "",
        "async def app(scope: Scope, receive: Receive, send: Send) -> None:",
        "    return None",
        "",
        *_handler_definition(handlers[registration["handler_name"]]),
    ]
    labeled_lines: dict[int, str] = {}
    if "constructor" in contract["reveals"]:
        source_lines.append("reveal_type(ExceptionMiddleware)")
        labeled_lines[len(source_lines)] = "constructor"
    source_lines.append(
        "ExceptionMiddleware(app, handlers={"
        + registration["exception_key"]
        + ": "
        + registration["handler_name"]
        + "})"
    )
    labeled_lines[len(source_lines)] = registration["probe_id"]

    source_path = directory / "consumer.py"
    source_path.write_text("\n".join(source_lines), encoding="utf-8")
    process = subprocess.run(
        [
            executable,
            "--config-file",
            str(config_path),
            "--python-executable",
            python_executable,
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
    if process.returncode not in {0, 1}:
        raise RuntimeError(
            "the pinned type checker could not analyze the input-defined consumer: "
            f"exit_code={process.returncode}, output={(process.stdout + process.stderr)!r}"
        )
    return {
        "probe_id": registration["probe_id"],
        "exit_code": process.returncode,
        "diagnostics": _diagnostics(
            process.stdout + process.stderr,
            labeled_lines,
        ),
    }


def run_exception_middleware_typing_case(case: dict[str, Any]) -> dict[str, Any]:
    """Type-check input-defined consumer callables through the imported Starlette surface."""
    import starlette

    executable = os.environ.get("STARLETTE_PARITY_TYPECHECKER")
    if executable is None or not Path(executable).is_file():
        raise RuntimeError("the pinned parity type-checker executable is not configured")

    contract = case["typing_contract"]
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
    )
    if version.returncode != 0:
        raise RuntimeError(
            f"the parity type checker failed to report its version: {version.stderr}"
        )

    lock_path = Path(__file__).resolve().parents[1] / "locks" / "typecheck-cpython312.txt"
    lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    handlers = {handler["name"]: handler for handler in contract["handler_signatures"]}
    with tempfile.TemporaryDirectory(prefix="starlette-rs-exception-types-") as temporary:
        directory = Path(temporary)
        config_path = directory / "mypy.ini"
        config_path.write_text("[mypy]\nfollow_imports = silent\n", encoding="utf-8")
        probes = [
            _run_probe(
                executable,
                sys.executable,
                environment,
                config_path,
                directory,
                contract,
                registration,
                handlers,
            )
            for registration in contract["registrations"]
        ]

    return {
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [
            {
                "step_id": "typing_contract",
                "status": "ok",
                "value": {
                    "typing_contract": {
                        "checker": version.stdout.strip(),
                        "checker_lock_sha256": lock_digest,
                        "probes": probes,
                    }
                },
            }
        ],
    }
