"""Prepare and verify isolated CPython environments for parity adapters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import tomllib

from .contract import ORACLE_COMMIT, ContractError, sha256_file

ENVIRONMENTS_SCHEMA = "migration-parity/python-environments@1"
ENVIRONMENTS_RELATIVE = Path("build/parity/python-environments.json")
RUNTIME_LOCK_RELATIVE = Path("scripts/parity/locks/asgi-runtime-cpython312.txt")
ENVIRONMENT_IDS = ("starlette-oracle-cpython312", "starlette-rs-py-cpython312")
_PROBE = r"""
import importlib.metadata as metadata
import json, platform, sys
packages = sorted(
    ({"name": item.metadata["Name"].lower().replace("_", "-"), "version": item.version} for item in metadata.distributions()),
    key=lambda item: item["name"],
)
print(json.dumps({
    "implementation": platform.python_implementation(),
    "python": platform.python_version(),
    "os": platform.platform(),
    "architecture": platform.machine(),
    "packages": packages,
}, sort_keys=True, separators=(",", ":")))
"""


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "PIP_USER"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _run(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-4000:]
        raise ContractError(
            f"environment preparation command failed ({argv[0]}): {detail}"
        ) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError(f"cannot run environment preparation command {argv[0]}: {exc}") from exc


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _probe(python: Path, root: Path) -> dict[str, Any]:
    process = _run([str(python), "-c", _PROBE], cwd=root, env=_base_env(), timeout=30)
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"environment interpreter emitted invalid identity JSON: {exc}"
        ) from exc
    if not isinstance(value, dict) or set(value) != {
        "implementation",
        "python",
        "os",
        "architecture",
        "packages",
    }:
        raise ContractError("environment interpreter identity has unknown or missing fields")
    if value["implementation"] != "CPython" or not str(value["python"]).startswith("3.12."):
        raise ContractError(
            f"parity environments require CPython 3.12, found {value['implementation']} {value['python']}"
        )
    package_rows = value["packages"]
    if not isinstance(package_rows, list) or any(
        not isinstance(item, dict) or set(item) != {"name", "version"} for item in package_rows
    ):
        raise ContractError("environment package inventory is malformed")
    if [item["name"] for item in package_rows] != sorted(item["name"] for item in package_rows):
        raise ContractError("environment package inventory must be sorted and unique")
    if len({item["name"] for item in package_rows}) != len(package_rows):
        raise ContractError("environment contains duplicate distribution names")
    return value


def _environment_fingerprints(
    environment_id: str,
    python_relative: str,
    runtime_lock_digest: str,
    probe: dict[str, Any],
    artifact_sha256: str | None,
) -> dict[str, Any]:
    installed_lock = {
        "implementation": probe["implementation"],
        "python": probe["python"],
        "packages": probe["packages"],
    }
    installed_digest = _canonical_sha256(installed_lock)
    fingerprint = {
        "id": environment_id,
        "python": python_relative,
        "runtime": f"{probe['implementation']} {probe['python']}",
        "os": probe["os"],
        "architecture": probe["architecture"],
        "dependency_lock_path": RUNTIME_LOCK_RELATIVE.as_posix(),
        "dependency_lock_sha256": runtime_lock_digest,
        "installed_lock_sha256": installed_digest,
        "artifact_sha256": artifact_sha256,
    }
    fingerprint["environment_sha256"] = _canonical_sha256(fingerprint)
    return fingerprint


def _source_revision(upstream: Path) -> tuple[str, str]:
    if not (upstream / "starlette" / "__init__.py").is_file():
        raise ContractError(f"Starlette source package not found under {upstream}")
    process = _run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"], cwd=upstream, env=_base_env(), timeout=10
    )
    revision = process.stdout.strip()
    if revision != ORACLE_COMMIT:
        raise ContractError(f"expected Starlette source {ORACLE_COMMIT}, found {revision}")
    return revision, str((upstream / "starlette").resolve())


def validate_runtime_lock(root: Path, upstream: Path) -> str:
    """Check the narrow CPython runtime lock against the pinned source uv.lock."""
    runtime_path = root / RUNTIME_LOCK_RELATIVE
    upstream_path = upstream / "uv.lock"
    if not runtime_path.is_file() or not upstream_path.is_file():
        raise ContractError("runtime dependency lock or pinned source uv.lock is missing")
    try:
        upstream_lock = tomllib.loads(upstream_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"cannot parse pinned source uv.lock: {exc}") from exc
    locked_packages = {
        item["name"].lower().replace("_", "-"): item
        for item in upstream_lock.get("package", [])
        if "version" in item
    }
    expected_names = {"anyio", "idna", "sniffio", "typing-extensions", "pyyaml"}
    declarations: dict[str, tuple[str, set[str]]] = {}
    try:
        for line in runtime_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            requirement, *hash_parts = stripped.split()
            name, version = requirement.split("==", 1)
            normalized = name.lower().replace("_", "-")
            hashes = {
                part.removeprefix("--hash=sha256:")
                for part in hash_parts
                if part.startswith("--hash=sha256:")
            }
            if not hashes or normalized in declarations:
                raise ContractError(f"runtime lock entry is malformed or duplicated: {stripped}")
            declarations[normalized] = (version, hashes)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError(f"cannot parse committed CPython runtime lock: {exc}") from exc
    if set(declarations) != expected_names:
        raise ContractError(
            "runtime dependency lock must contain the ASGI closure and optional YAML parser"
        )
    for name, (version, hashes) in declarations.items():
        package = locked_packages.get(name)
        if package is None or package["version"] != version:
            raise ContractError(
                f"runtime dependency {name}={version} differs from the pinned source lock"
            )
        wheel_hashes = {
            wheel["hash"].removeprefix("sha256:") for wheel in package.get("wheels", [])
        }
        if not hashes <= wheel_hashes:
            raise ContractError(
                f"runtime dependency {name} hash is absent from the pinned source lock"
            )
    return sha256_file(runtime_path)


def _target_wheel(root: Path, wheelhouse: Path, python: Path, env: dict[str, str]) -> Path:
    wheelhouse.mkdir(parents=True)
    _run(
        [str(python), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheelhouse), str(root)],
        cwd=root,
        env=env,
        timeout=1800,
    )
    wheels = sorted(wheelhouse.glob("starlette_rs_py-*.whl"))
    if len(wheels) != 1:
        raise ContractError(
            f"building the target must produce exactly one starlette-rs-py wheel, found {len(wheels)}"
        )
    return wheels[0]


def prepare_environments(
    root: Path,
    upstream: Path,
    python: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Build the local target wheel and prepare two independently locked venvs."""
    root = root.resolve()
    upstream = upstream.resolve()
    host_python = (python or Path(sys.executable)).resolve()
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 12):
        raise ContractError(
            "prepare-env must be invoked by CPython 3.12; no global interpreter fallback is used"
        )
    if not host_python.is_file():
        raise ContractError(f"requested Python interpreter is absent: {host_python}")
    revision, _ = _source_revision(upstream)
    lock_path = root / RUNTIME_LOCK_RELATIVE
    lock_digest = validate_runtime_lock(root, upstream)

    build_root = root / "build" / "parity"
    env_root = build_root / "envs"
    wheelhouse = build_root / "wheelhouse"
    environment_lock_path = root / ENVIRONMENTS_RELATIVE
    if (env_root.exists() or wheelhouse.exists() or environment_lock_path.exists()) and not force:
        raise ContractError(
            "parity environments already exist; pass --force to replace only generated build/parity artifacts"
        )
    if force:
        for generated in (env_root, wheelhouse):
            if generated.exists():
                generated.resolve().relative_to(build_root.resolve())
                shutil.rmtree(generated)
        if environment_lock_path.exists():
            environment_lock_path.unlink()
    build_root.mkdir(parents=True, exist_ok=True)
    env = _base_env()
    wheel = _target_wheel(root, wheelhouse, host_python, env)
    wheel_digest = sha256_file(wheel)
    env_root.mkdir(parents=True)

    records: list[dict[str, Any]] = []
    source_path = _venv_python(env_root / "oracle")
    target_path = _venv_python(env_root / "python-package")
    for environment in (env_root / "oracle", env_root / "python-package"):
        _run([str(host_python), "-m", "venv", str(environment)], cwd=root, env=env, timeout=120)
        venv_python = _venv_python(environment)
        if not venv_python.is_file():
            raise ContractError(f"venv creation did not produce interpreter: {venv_python}")
        _run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--no-deps",
                "--only-binary=:all:",
                "-r",
                str(lock_path),
            ],
            cwd=root,
            env=env,
            timeout=600,
        )

    _run(
        [str(target_path), "-m", "pip", "install", "--no-deps", str(wheel.resolve())],
        cwd=root,
        env=env,
        timeout=600,
    )

    for environment_id, interpreter, artifact_digest in (
        (ENVIRONMENT_IDS[0], source_path, None),
        (ENVIRONMENT_IDS[1], target_path, wheel_digest),
    ):
        probe = _probe(interpreter, root)
        relative_python = interpreter.relative_to(root).as_posix()
        records.append(
            _environment_fingerprints(
                environment_id, relative_python, lock_digest, probe, artifact_digest
            )
        )

    output = {
        "schema": ENVIRONMENTS_SCHEMA,
        "source_revision": revision,
        "target_wheel": {"path": wheel.relative_to(root).as_posix(), "sha256": wheel_digest},
        "environments": records,
    }
    environment_lock_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = environment_lock_path.with_name(
        environment_lock_path.name + f".{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(environment_lock_path)
    return output


def load_prepared_environments(
    root: Path, require_target: bool = True
) -> dict[str, dict[str, Any]]:
    """Validate prepared interpreter paths and recompute their frozen identity."""
    root = root.resolve()
    metadata_path = root / ENVIRONMENTS_RELATIVE
    if not metadata_path.is_file():
        raise ContractError(
            "parity environments are not prepared; run `python3.12 -m scripts.parity.cli prepare-env`"
        )
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load prepared parity environment identity: {exc}") from exc
    expected_top = {"schema", "source_revision", "target_wheel", "environments"}
    if (
        not isinstance(document, dict)
        or set(document) != expected_top
        or document["schema"] != ENVIRONMENTS_SCHEMA
    ):
        raise ContractError("prepared environment lock has unknown fields or schema")
    if document["source_revision"] != ORACLE_COMMIT:
        raise ContractError("prepared environments were built against another source revision")
    target_wheel = document["target_wheel"]
    if not isinstance(target_wheel, dict) or set(target_wheel) != {"path", "sha256"}:
        raise ContractError("prepared target wheel identity is malformed")
    wheel_path = root / target_wheel["path"]
    if not wheel_path.is_file() or sha256_file(wheel_path) != target_wheel["sha256"]:
        raise ContractError("prepared target wheel is missing or changed")
    rows = document["environments"]
    if not isinstance(rows, list) or {
        row.get("id") for row in rows if isinstance(row, dict)
    } != set(ENVIRONMENT_IDS):
        raise ContractError(
            "prepared environment lock must describe the oracle and installed-wheel environments"
        )
    lock_path = root / RUNTIME_LOCK_RELATIVE
    if not lock_path.is_file():
        raise ContractError("committed runtime dependency lock is missing")
    lock_digest = sha256_file(lock_path)
    output: dict[str, dict[str, Any]] = {}
    expected_keys = {
        "id",
        "python",
        "runtime",
        "os",
        "architecture",
        "dependency_lock_path",
        "dependency_lock_sha256",
        "installed_lock_sha256",
        "artifact_sha256",
        "environment_sha256",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise ContractError("prepared environment identity has unknown or missing fields")
        if (
            row["dependency_lock_path"] != RUNTIME_LOCK_RELATIVE.as_posix()
            or row["dependency_lock_sha256"] != lock_digest
        ):
            raise ContractError(f"{row['id']} dependency lock differs from the committed lock")
        if row["artifact_sha256"] != (
            target_wheel["sha256"] if row["id"] == ENVIRONMENT_IDS[1] else None
        ):
            raise ContractError(f"{row['id']} target artifact identity mismatch")
        python_relative = Path(row["python"])
        if python_relative.is_absolute() or ".." in python_relative.parts:
            raise ContractError(f"{row['id']} interpreter path must remain repository-relative")
        interpreter = root / python_relative
        if not interpreter.is_file() or not interpreter.absolute().is_relative_to(
            (root / "build/parity/envs").absolute()
        ):
            raise ContractError(f"{row['id']} interpreter is not under build/parity/envs")
        probe = _probe(interpreter, root)
        actual = _environment_fingerprints(
            row["id"], row["python"], lock_digest, probe, row["artifact_sha256"]
        )
        if actual != row:
            raise ContractError(f"{row['id']} environment changed after preparation")
        output[row["id"]] = row
    if not require_target:
        output.pop(ENVIRONMENT_IDS[1], None)
    return output
