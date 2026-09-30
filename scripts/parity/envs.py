"""Prepare and verify isolated CPython environments for parity adapters."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any

import tomllib

from .contract import ORACLE_COMMIT, ContractError, sha256_file

ENVIRONMENTS_SCHEMA = "migration-parity/python-environments@2"
ENVIRONMENTS_RELATIVE = Path("build/parity/python-environments.json")
RUNTIME_LOCK_RELATIVE = Path("scripts/parity/locks/asgi-runtime-cpython312.txt")
ORACLE_RUNTIME_LOCK_RELATIVE = Path("scripts/parity/locks/starlette-oracle-cpython312.txt")
ENVIRONMENT_IDS = ("starlette-oracle-cpython312", "starlette-rs-py-cpython312")
_PROCESS_ENVIRONMENT_POLICY = {
    "PYTHONHASHSEED": "0",
    "PYTHONOPTIMIZE": None,
    "PYTHONWARNINGS": None,
}
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


def _target_source_identity(root: Path) -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout
        tracked_diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--binary", "--no-ext-diff", "HEAD", "--"],
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout
        untracked_paths = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout.split(b"\0")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot inspect target source checkout identity: {exc}") from exc
    if len(revision) not in {40, 64} or any(
        character not in "0123456789abcdef" for character in revision
    ):
        raise ContractError("target source revision must be a full lowercase Git object ID")
    digest = hashlib.sha256()
    digest.update(b"revision\0")
    digest.update(revision.encode("ascii"))
    digest.update(b"\0status\0")
    digest.update(status)
    digest.update(b"\0tracked-diff\0")
    digest.update(tracked_diff)
    for raw_path in sorted(path for path in untracked_paths if path):
        path = root / os.fsdecode(raw_path)
        try:
            if path.is_symlink():
                digest.update(b"symlink\0")
                digest.update(raw_path)
                digest.update(b"\0")
                digest.update(os.fsencode(os.readlink(path)))
            elif path.is_file():
                digest.update(b"file\0")
                digest.update(raw_path)
                digest.update(b"\0")
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
            else:
                raise ContractError(
                    f"cannot fingerprint untracked target source path: {os.fsdecode(raw_path)}"
                )
            digest.update(b"\0")
        except OSError as exc:
            raise ContractError(
                f"cannot fingerprint untracked target source path {os.fsdecode(raw_path)!r}: {exc}"
            ) from exc
    return {
        "revision": revision,
        "dirty": bool(status),
        "working_tree_sha256": digest.hexdigest(),
    }


def _package_tree_sha256(files: dict[str, bytes]) -> str:
    if not files:
        raise ContractError("target wheel has no verifiable Starlette package files")
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative])
        digest.update(b"\0")
    return digest.hexdigest()


def _wheel_package_tree_sha256(wheel: Path) -> str:
    package_roots = ("starlette/", "starlette_rs_py/")
    files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            for entry in archive.infolist():
                relative = entry.filename.replace("\\", "/")
                if entry.is_dir() or not relative.startswith(package_roots):
                    continue
                parts = Path(relative).parts
                if relative.startswith("/") or ".." in parts:
                    raise ContractError(f"target wheel contains an unsafe package path: {relative}")
                if relative.endswith((".pyc", ".pyo")):
                    continue
                if relative in files:
                    raise ContractError(f"target wheel repeats package file: {relative}")
                files[relative] = archive.read(entry)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ContractError(f"cannot inspect target wheel package files: {exc}") from exc
    return _package_tree_sha256(files)


def base_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PYTHONOPTIMIZE",
        "PYTHONWARNINGS",
        "PYTHONHASHSEED",
        "VIRTUAL_ENV",
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
    ):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
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
    process = _run([str(python), "-c", _PROBE], cwd=root, env=base_environment(), timeout=30)
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
    runtime_lock_path: Path,
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
        "dependency_lock_path": runtime_lock_path.as_posix(),
        "dependency_lock_sha256": runtime_lock_digest,
        "installed_lock_sha256": installed_digest,
        "artifact_sha256": artifact_sha256,
    }
    fingerprint["environment_sha256"] = _canonical_sha256(
        {
            "environment": fingerprint,
            "process_environment_policy": _PROCESS_ENVIRONMENT_POLICY,
        }
    )
    return fingerprint


def _source_revision(upstream: Path) -> tuple[str, str]:
    if not (upstream / "starlette" / "__init__.py").is_file():
        raise ContractError(f"Starlette source package not found under {upstream}")
    process = _run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        cwd=upstream,
        env=base_environment(),
        timeout=10,
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
    expected_names = {
        "anyio",
        "certifi",
        "h11",
        "httpcore",
        "httpcore2",
        "httpx",
        "httpx2",
        "idna",
        "jinja2",
        "markupsafe",
        "sniffio",
        "truststore",
        "typing-extensions",
        "pyyaml",
    }
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
            "runtime dependency lock must contain the ASGI closure, optional YAML/template parsers, "
            "and pinned TestClient HTTP transports"
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


def _lock_declarations(path: Path) -> dict[str, tuple[str, set[str]]]:
    declarations: dict[str, tuple[str, set[str]]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
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
    return declarations


def validate_oracle_runtime_lock(root: Path, upstream: Path) -> str:
    """Check the oracle lock adds only pinned Starlette optional dependencies."""
    base = _lock_declarations(root / RUNTIME_LOCK_RELATIVE)
    oracle_path = root / ORACLE_RUNTIME_LOCK_RELATIVE
    oracle = _lock_declarations(oracle_path)
    oracle_optional_dependencies = {"itsdangerous", "python-multipart"}
    if set(oracle) != set(base) | oracle_optional_dependencies:
        raise ContractError(
            "source-oracle lock must add only optional ItsDangerous and python-multipart "
            "to the ASGI closure"
        )
    if any(oracle[name] != entry for name, entry in base.items()):
        raise ContractError(
            "source-oracle lock entries differ from the committed ASGI runtime lock"
        )

    try:
        upstream_lock = tomllib.loads((upstream / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(
            f"cannot parse pinned source uv.lock for oracle dependencies: {exc}"
        ) from exc
    source_packages = {
        item.get("name", "").lower().replace("_", "-"): item
        for item in upstream_lock.get("package", [])
    }
    source_starlette = source_packages.get("starlette")
    if source_starlette is None:
        raise ContractError("pinned Starlette source lock omits its package record")
    optional_full = {
        item["name"].lower().replace("_", "-")
        for item in source_starlette.get("optional-dependencies", {}).get("full", [])
    }
    if not oracle_optional_dependencies <= optional_full:
        raise ContractError(
            "oracle-only dependencies must be declared in the pinned Starlette full extra"
        )
    for name in sorted(oracle_optional_dependencies):
        package = source_packages.get(name)
        if package is None:
            raise ContractError(f"pinned Starlette source lock omits optional {name}")
        version, hashes = oracle[name]
        wheel_hashes = {
            wheel["hash"].removeprefix("sha256:") for wheel in package.get("wheels", [])
        }
        if version != package["version"] or not hashes or not hashes <= wheel_hashes:
            raise ContractError(
                f"oracle {name} version or hash differs from the pinned source lock"
            )
    return sha256_file(oracle_path)


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
    target_source = _target_source_identity(root)
    revision, _ = _source_revision(upstream)
    lock_path = root / RUNTIME_LOCK_RELATIVE
    lock_digest = validate_runtime_lock(root, upstream)
    oracle_lock_path = root / ORACLE_RUNTIME_LOCK_RELATIVE
    oracle_lock_digest = validate_oracle_runtime_lock(root, upstream)

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
    env = base_environment()
    wheel = _target_wheel(root, wheelhouse, host_python, env)
    wheel_digest = sha256_file(wheel)
    target_tree_digest = _wheel_package_tree_sha256(wheel)
    if _target_source_identity(root) != target_source:
        raise ContractError("target source checkout changed while building the prepared wheel")
    env_root.mkdir(parents=True)

    records: list[dict[str, Any]] = []
    source_path = _venv_python(env_root / "oracle")
    target_path = _venv_python(env_root / "python-package")
    for environment, environment_lock in (
        (env_root / "oracle", oracle_lock_path),
        (env_root / "python-package", lock_path),
    ):
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
                str(environment_lock),
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

    for environment_id, interpreter, artifact_digest, runtime_lock_path, runtime_lock_digest in (
        (ENVIRONMENT_IDS[0], source_path, None, ORACLE_RUNTIME_LOCK_RELATIVE, oracle_lock_digest),
        (ENVIRONMENT_IDS[1], target_path, wheel_digest, RUNTIME_LOCK_RELATIVE, lock_digest),
    ):
        probe = _probe(interpreter, root)
        relative_python = interpreter.relative_to(root).as_posix()
        records.append(
            _environment_fingerprints(
                environment_id,
                relative_python,
                runtime_lock_path,
                runtime_lock_digest,
                probe,
                artifact_digest,
            )
        )

    output = {
        "schema": ENVIRONMENTS_SCHEMA,
        "source_revision": revision,
        "target_source": target_source,
        "target_wheel": {
            "path": wheel.relative_to(root).as_posix(),
            "sha256": wheel_digest,
            "target_tree_sha256": target_tree_digest,
        },
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
    expected_top = {
        "schema",
        "source_revision",
        "target_source",
        "target_wheel",
        "environments",
    }
    if (
        not isinstance(document, dict)
        or set(document) != expected_top
        or document["schema"] != ENVIRONMENTS_SCHEMA
    ):
        raise ContractError("prepared environment lock has unknown fields or schema")
    if document["source_revision"] != ORACLE_COMMIT:
        raise ContractError("prepared environments were built against another source revision")
    target_source = document["target_source"]
    if (
        not isinstance(target_source, dict)
        or set(target_source) != {"revision", "dirty", "working_tree_sha256"}
        or not isinstance(target_source["revision"], str)
        or not isinstance(target_source["dirty"], bool)
        or not isinstance(target_source["working_tree_sha256"], str)
        or len(target_source["working_tree_sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in target_source["working_tree_sha256"])
    ):
        raise ContractError("prepared target source identity is malformed")
    if _target_source_identity(root) != target_source:
        raise ContractError("target source checkout changed after environment preparation")
    target_wheel = document["target_wheel"]
    if not isinstance(target_wheel, dict) or set(target_wheel) != {
        "path",
        "sha256",
        "target_tree_sha256",
    }:
        raise ContractError("prepared target wheel identity is malformed")
    wheel_path = root / target_wheel["path"]
    if not wheel_path.is_file() or sha256_file(wheel_path) != target_wheel["sha256"]:
        raise ContractError("prepared target wheel is missing or changed")
    if _wheel_package_tree_sha256(wheel_path) != target_wheel["target_tree_sha256"]:
        raise ContractError("prepared target wheel package tree is missing or changed")
    rows = document["environments"]
    if not isinstance(rows, list) or {
        row.get("id") for row in rows if isinstance(row, dict)
    } != set(ENVIRONMENT_IDS):
        raise ContractError(
            "prepared environment lock must describe the oracle and installed-wheel environments"
        )
    expected_locks = {
        ENVIRONMENT_IDS[0]: ORACLE_RUNTIME_LOCK_RELATIVE,
        ENVIRONMENT_IDS[1]: RUNTIME_LOCK_RELATIVE,
    }
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
        expected_lock = expected_locks[row["id"]]
        lock_path = root / expected_lock
        if not lock_path.is_file():
            raise ContractError(f"committed dependency lock is missing: {expected_lock.as_posix()}")
        lock_digest = sha256_file(lock_path)
        if (
            row["dependency_lock_path"] != expected_lock.as_posix()
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
            row["id"],
            row["python"],
            expected_lock,
            lock_digest,
            probe,
            row["artifact_sha256"],
        )
        if actual != row:
            raise ContractError(f"{row['id']} environment changed after preparation")
        output[row["id"]] = row
    target = output[ENVIRONMENT_IDS[1]]
    target_tree_sha256 = target_wheel["target_tree_sha256"]
    target["target_tree_sha256"] = target_tree_sha256
    target["target_revision"] = (
        f"dirty-tree:{target_tree_sha256}" if target_source["dirty"] else target_source["revision"]
    )
    target["target_dirty"] = target_source["dirty"]
    target["target_source_revision"] = target_source["revision"]
    if not require_target:
        output.pop(ENVIRONMENT_IDS[1], None)
    return output
