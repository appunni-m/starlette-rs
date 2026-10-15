"""Prepare and verify isolated CPython environments for parity adapters."""

from __future__ import annotations

import ast
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

try:
    import tomllib
except ModuleNotFoundError:  # CPython 3.10 starts before the prepared parity lock exists.
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        # The bootstrap interpreter must parse the pinned uv.lock before the parity
        # environment can install its own hash-pinned tomli dependency.
        from pip._vendor import tomli as tomllib

from .contract import ORACLE_COMMIT, ContractError, sha256_file

ENVIRONMENTS_SCHEMA = "migration-parity/python-environments@4"
ENVIRONMENTS_RELATIVE = Path("build/parity/python-environments.json")
RUNTIME_LOCK_RELATIVE = Path("scripts/parity/locks/asgi-runtime-python.txt")
ORACLE_RUNTIME_LOCK_RELATIVE = Path("scripts/parity/locks/starlette-oracle-python.txt")
MARKUPSAFE_SOURCE_LOCK_RELATIVE = Path("scripts/parity/locks/markupsafe-cpython314-source.txt")
MARKUPSAFE_BUILD_LOCK_RELATIVE = Path("scripts/parity/locks/markupsafe-build-python.txt")
SUPPORTED_PYTHON_VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")
_PROCESS_ENVIRONMENT_POLICY = {
    "PYTHONHASHSEED": "0",
    "PYTHONOPTIMIZE": None,
    "PYTHONWARNINGS": None,
}
_PROBE = r"""
import importlib.metadata as metadata
import hashlib
import json, platform, sys
packages = sorted(
    (
        {
            "name": item.metadata["Name"].lower().replace("_", "-"),
            "version": item.version,
            **(
                {
                    "metadata_sha256": hashlib.sha256(
                        item.read_text("METADATA").encode("utf-8")
                    ).hexdigest(),
                    "provides_extra": item.metadata.get_all("Provides-Extra") or [],
                    "requires_dist": item.requires or [],
                }
                if item.metadata["Name"].lower().replace("_", "-") == "starlette"
                else {}
            ),
        }
        for item in metadata.distributions()
    ),
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


def python_version_tag(version: str) -> str:
    if version not in SUPPORTED_PYTHON_VERSIONS:
        raise ContractError(f"unsupported parity CPython version: {version}")
    return "cpython" + version.replace(".", "")


def environment_ids(version: str) -> tuple[str, str]:
    tag = python_version_tag(version)
    return (f"starlette-oracle-{tag}", f"starlette-rs-py-{tag}")


ENVIRONMENT_IDS = environment_ids("3.12")


def python_version_from_runtime(runtime: str) -> str:
    parts = runtime.split()
    if len(parts) != 2 or parts[0] != "CPython":
        raise ContractError(f"parity environment runtime is not CPython: {runtime!r}")
    version = ".".join(parts[1].split(".")[:2])
    if version not in SUPPORTED_PYTHON_VERSIONS:
        raise ContractError(f"unsupported parity CPython runtime: {runtime!r}")
    return version


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
    if "starlette/py.typed" not in files:
        raise ContractError("target wheel is missing required package marker: starlette/py.typed")
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
    runtime = f"{value['implementation']} {value['python']}"
    try:
        python_version_from_runtime(runtime)
    except ContractError as exc:
        raise ContractError(
            f"parity environments require CPython 3.10 through 3.14, found {runtime}"
        ) from exc
    package_rows = value["packages"]
    if not isinstance(package_rows, list) or any(
        not isinstance(item, dict)
        or set(item)
        != (
            {"name", "version", "metadata_sha256", "provides_extra", "requires_dist"}
            if item.get("name") == "starlette"
            else {"name", "version"}
        )
        for item in package_rows
    ):
        raise ContractError("environment package inventory is malformed")
    for item in package_rows:
        if item["name"] == "starlette" and (
            not isinstance(item["metadata_sha256"], str)
            or len(item["metadata_sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["metadata_sha256"])
            or not isinstance(item["provides_extra"], list)
            or not all(isinstance(extra, str) for extra in item["provides_extra"])
            or not isinstance(item["requires_dist"], list)
            or not all(isinstance(requirement, str) for requirement in item["requires_dist"])
        ):
            raise ContractError("Starlette source distribution metadata identity is malformed")
    if [item["name"] for item in package_rows] != sorted(item["name"] for item in package_rows):
        raise ContractError("environment package inventory must be sorted and unique")
    if len({item["name"] for item in package_rows}) != len(package_rows):
        raise ContractError("environment contains duplicate distribution names")
    return value


def _validate_oracle_source_distribution(probe: dict[str, Any]) -> None:
    distributions = [item for item in probe["packages"] if item["name"] == "starlette"]
    if len(distributions) != 1 or "full" not in distributions[0]["provides_extra"]:
        raise ContractError(
            "prepared oracle environment lacks pinned Starlette [full] metadata; rerun `make parity-env`"
        )


def _environment_fingerprints(
    environment_id: str,
    python_relative: str,
    runtime_lock_path: Path,
    runtime_lock_digest: str,
    probe: dict[str, Any],
    artifact_sha256: str | None,
    build_artifacts: list[dict[str, str]],
) -> dict[str, Any]:
    installed_lock = {
        "implementation": probe["implementation"],
        "python": probe["python"],
        "packages": probe["packages"],
        "build_artifacts": build_artifacts,
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
        "build_artifacts": build_artifacts,
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


def _source_distribution_metadata(upstream: Path) -> tuple[str, str]:
    """Project the pinned source's PEP 621 metadata to the fields its oracle exposes."""
    pyproject_path = upstream / "pyproject.toml"
    try:
        document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"cannot parse pinned Starlette pyproject.toml: {exc}") from exc
    project = document.get("project")
    if not isinstance(project, dict) or project.get("name") != "starlette":
        raise ContractError("pinned Starlette project metadata must declare name = 'starlette'")

    version = project.get("version")
    if version is None and "version" in project.get("dynamic", []):
        version_path = document.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
        if version_path != "starlette/__init__.py":
            raise ContractError("pinned Starlette dynamic version path is not recognized")
        try:
            version_source = (upstream / version_path).read_text(encoding="utf-8")
            version_module = ast.parse(version_source, filename=version_path)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ContractError(f"cannot read pinned Starlette package version: {exc}") from exc
        version_values = [
            node.value.value
            for node in version_module.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ]
        if len(version_values) != 1:
            raise ContractError("pinned Starlette package must declare one literal __version__")
        version = version_values[0]
    if not isinstance(version, str) or not version or any(char in version for char in "\r\n/\\"):
        raise ContractError("pinned Starlette project version is malformed")

    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str) or not requires_python:
        raise ContractError("pinned Starlette project omits requires-python")
    dependencies = project.get("dependencies", [])
    optional_dependencies = project.get("optional-dependencies", {})
    if not isinstance(dependencies, list) or not all(
        isinstance(requirement, str) and requirement for requirement in dependencies
    ):
        raise ContractError("pinned Starlette project dependencies are malformed")
    if not isinstance(optional_dependencies, dict) or any(
        not isinstance(extra, str)
        or not extra
        or not isinstance(requirements, list)
        or not all(isinstance(requirement, str) and requirement for requirement in requirements)
        for extra, requirements in optional_dependencies.items()
    ):
        raise ContractError("pinned Starlette optional dependencies are malformed")
    if "full" not in optional_dependencies:
        raise ContractError("pinned Starlette project metadata omits its full extra")

    lines = [
        "Metadata-Version: 2.4",
        "Name: starlette",
        f"Version: {version}",
        f"Requires-Python: {requires_python}",
    ]
    lines.extend(f"Requires-Dist: {requirement}" for requirement in dependencies)
    for extra, requirements in optional_dependencies.items():
        lines.append(f"Provides-Extra: {extra}")
        for requirement in requirements:
            expression, separator, marker = requirement.partition(";")
            marker = f"({marker.strip()}) and " if separator else ""
            lines.append(f"Requires-Dist: {expression.strip()}; {marker}extra == '{extra}'")
    return version, "\n".join(lines) + "\n"


def _install_source_distribution_metadata(
    upstream: Path,
    environment: Path,
    interpreter: Path,
    root: Path,
) -> None:
    """Expose source project metadata to importlib.metadata in the oracle venv."""
    version, metadata_text = _source_distribution_metadata(upstream)
    process = _run(
        [
            str(interpreter),
            "-c",
            "import json, sysconfig; print(json.dumps(sysconfig.get_path('purelib')))",
        ],
        cwd=root,
        env=base_environment(),
        timeout=30,
    )
    try:
        site_packages_value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"oracle interpreter emitted invalid site-packages path: {exc}"
        ) from exc
    if not isinstance(site_packages_value, str):
        raise ContractError("oracle interpreter site-packages path is malformed")
    site_packages = Path(site_packages_value).resolve()
    if not site_packages.is_relative_to(environment.resolve()):
        raise ContractError("oracle interpreter site-packages path escapes its virtual environment")

    distribution_info = site_packages / f"starlette-{version}.dist-info"
    if distribution_info.exists():
        raise ContractError(
            "oracle virtual environment already contains Starlette distribution metadata"
        )
    distribution_info.mkdir(parents=True)
    (distribution_info / "METADATA").write_text(metadata_text, encoding="utf-8")


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
        "attrs",
        "certifi",
        "cffi",
        "h11",
        "httpcore",
        "httpcore2",
        "httpx",
        "httpx2",
        "idna",
        "exceptiongroup",
        "itsdangerous",
        "jinja2",
        "markupsafe",
        "outcome",
        "sortedcontainers",
        "sniffio",
        "trio",
        "truststore",
        "typing-extensions",
        "tomli",
        "pycparser",
        "pyyaml",
        "python-multipart",
    }
    declarations: dict[str, tuple[str, set[str]]] = {}
    try:
        for line in runtime_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            requirement = stripped.split(";", 1)[0].split()[0]
            hash_parts = stripped.split()
            name, version = requirement.split("==", 1)
            normalized = name.lower().replace("_", "-")
            hashes = _sha256_hashes(hash_parts, stripped)
            if not hashes or normalized in declarations:
                raise ContractError(f"runtime lock entry is malformed or duplicated: {stripped}")
            declarations[normalized] = (version, hashes)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError(f"cannot parse committed CPython runtime lock: {exc}") from exc
    if set(declarations) != expected_names:
        raise ContractError(
            "runtime dependency lock must contain the ASGI closure, pinned full-extra dependencies, "
            "pinned TestClient HTTP transports, and the locked AnyIO Trio parity backend dependency closure"
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
        if hashes != wheel_hashes:
            raise ContractError(
                f"runtime dependency {name} wheel hashes do not exactly match the pinned source lock"
            )
    return sha256_file(runtime_path)


def _lock_declarations(path: Path) -> dict[str, tuple[str, set[str]]]:
    declarations: dict[str, tuple[str, set[str]]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            requirement = stripped.split(";", 1)[0].split()[0]
            hash_parts = stripped.split()
            name, version = requirement.split("==", 1)
            normalized = name.lower().replace("_", "-")
            hashes = _sha256_hashes(hash_parts, stripped)
            if not hashes or normalized in declarations:
                raise ContractError(f"runtime lock entry is malformed or duplicated: {stripped}")
            declarations[normalized] = (version, hashes)
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError(f"cannot parse committed CPython runtime lock: {exc}") from exc
    return declarations


def _sha256_hashes(parts: list[str], entry: str) -> set[str]:
    hash_parts = [part for part in parts if part.startswith("--hash")]
    hashes: list[str] = []
    for part in hash_parts:
        prefix = "--hash=sha256:"
        digest = part.removeprefix(prefix)
        if (
            not part.startswith(prefix)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ContractError(f"dependency lock hash must be a SHA-256 digest: {entry}")
        hashes.append(digest)
    if len(hashes) != len(set(hashes)):
        raise ContractError(f"dependency lock repeats a SHA-256 hash: {entry}")
    return set(hashes)


def validate_oracle_runtime_lock(root: Path, upstream: Path) -> str:
    """Check both full-feature environments use the pinned optional closure."""
    base = _lock_declarations(root / RUNTIME_LOCK_RELATIVE)
    oracle_path = root / ORACLE_RUNTIME_LOCK_RELATIVE
    oracle = _lock_declarations(oracle_path)
    oracle_optional_dependencies = {"itsdangerous", "python-multipart"}
    if set(oracle) != set(base) or not oracle_optional_dependencies <= set(base):
        raise ContractError(
            "source-oracle and package locks must contain the same pinned full-feature closure"
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
            "optional dependencies must be declared in the pinned Starlette full extra"
        )
    for name in sorted(oracle_optional_dependencies):
        package = source_packages.get(name)
        if package is None:
            raise ContractError(f"pinned Starlette source lock omits optional {name}")
        version, hashes = oracle[name]
        wheel_hashes = {
            wheel["hash"].removeprefix("sha256:") for wheel in package.get("wheels", [])
        }
        if version != package["version"] or not hashes or hashes != wheel_hashes:
            raise ContractError(
                f"oracle {name} version or wheel hashes differ from the pinned source lock"
            )
    return sha256_file(oracle_path)


def validate_markupsafe_build_locks(root: Path, upstream: Path) -> dict[str, str]:
    """Pin the MarkupSafe source fallback and its isolated wheel builder."""
    source_path = root / MARKUPSAFE_SOURCE_LOCK_RELATIVE
    build_path = root / MARKUPSAFE_BUILD_LOCK_RELATIVE
    runtime = _lock_declarations(root / RUNTIME_LOCK_RELATIVE)
    source = _lock_declarations(source_path)
    builder = _lock_declarations(build_path)
    if (
        set(source) != {"markupsafe"}
        or "markupsafe" not in runtime
        or source["markupsafe"][0] != runtime["markupsafe"][0]
    ):
        raise ContractError("MarkupSafe source fallback lock must match the runtime package pin")
    if set(builder) != {"pip", "setuptools"} or any(
        len(hashes) != 1 for _, hashes in builder.values()
    ):
        raise ContractError(
            "MarkupSafe source fallback must use hash-pinned pip and setuptools build tools"
        )

    try:
        upstream_lock = tomllib.loads((upstream / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(
            f"cannot parse pinned source uv.lock for MarkupSafe build: {exc}"
        ) from exc
    source_packages = {
        item.get("name", "").lower().replace("_", "-"): item
        for item in upstream_lock.get("package", [])
    }
    package = source_packages.get("markupsafe")
    if package is None or package.get("version") != source["markupsafe"][0]:
        raise ContractError(
            "MarkupSafe source fallback version differs from the pinned source lock"
        )
    sdist = package.get("sdist")
    sdist_hash = sdist.get("hash") if isinstance(sdist, dict) else None
    if not isinstance(sdist_hash, str) or not sdist_hash.startswith("sha256:"):
        raise ContractError("pinned source uv.lock omits the MarkupSafe sdist hash")
    sdist_sha256 = sdist_hash.removeprefix("sha256:")
    if len(sdist_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sdist_sha256
    ):
        raise ContractError("pinned source uv.lock contains a malformed MarkupSafe sdist hash")
    if source["markupsafe"][1] != {sdist_sha256}:
        raise ContractError("MarkupSafe source fallback hash differs from the pinned source lock")

    builder_version = builder["setuptools"][0]
    try:
        builder_version_parts = tuple(int(part) for part in builder_version.split("."))
    except ValueError as exc:
        raise ContractError("MarkupSafe build tool version must be numeric") from exc
    if builder_version_parts < (70, 1):
        raise ContractError("MarkupSafe 3.0.2 source builds require setuptools 70.1 or newer")

    return {
        "source_lock_sha256": sha256_file(source_path),
        "source_sha256": sdist_sha256,
        "source_version": source["markupsafe"][0],
        "build_lock_sha256": sha256_file(build_path),
        "pip_version": builder["pip"][0],
        "builder_version": builder_version,
    }


def _write_runtime_lock_without_markupsafe(source: Path, destination: Path) -> None:
    lines: list[str] = []
    removed = 0
    try:
        for line in source.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                requirement = stripped.split(";", 1)[0].split()[0]
                normalized = requirement.split("==", 1)[0].lower().replace("_", "-")
                if normalized == "markupsafe":
                    removed += 1
                    continue
            lines.append(line)
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"cannot read committed runtime lock {source}: {exc}") from exc
    if removed != 1:
        raise ContractError("the CPython 3.14 runtime lock must contain one MarkupSafe entry")
    try:
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot write generated filtered runtime lock: {exc}") from exc


def _validate_markupsafe_wheel(wheel: Path, version: str) -> None:
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_paths = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1:
                raise ContractError("built MarkupSafe wheel must contain one METADATA file")
            metadata = archive.read(metadata_paths[0]).decode("utf-8")
    except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ContractError(f"cannot inspect built MarkupSafe wheel: {exc}") from exc
    fields: dict[str, str] = {}
    for line in metadata.splitlines():
        name, separator, value = line.partition(":")
        if separator and name in {"Name", "Version"}:
            fields[name] = value.strip()
    if (
        fields.get("Name", "").lower().replace("_", "-") != "markupsafe"
        or fields.get("Version") != version
    ):
        raise ContractError(
            "built MarkupSafe wheel metadata differs from the pinned source package"
        )


def _build_markupsafe_wheel(
    root: Path,
    host_python: Path,
    wheelhouse: Path,
    env: dict[str, str],
    build_lock: dict[str, str],
) -> dict[str, str]:
    """Build a CPython 3.14 wheel from the pinned MarkupSafe sdist in isolation."""
    build_root = wheelhouse / f"markupsafe-{build_lock['source_version']}"
    source_dir = build_root / "source"
    builder_env = build_root / "builder-env"
    built_wheels = build_root / "wheels"
    source_dir.mkdir(parents=True)
    built_wheels.mkdir()

    source_lock = root / MARKUPSAFE_SOURCE_LOCK_RELATIVE
    _run(
        [
            str(host_python),
            "-m",
            "pip",
            "download",
            "--require-hashes",
            "--no-deps",
            "--no-binary=:all:",
            "--dest",
            str(source_dir),
            "-r",
            str(source_lock),
        ],
        cwd=root,
        env=env,
        timeout=600,
    )
    sdists = sorted(path for path in source_dir.iterdir() if path.is_file())
    expected_sdist_name = f"markupsafe-{build_lock['source_version']}.tar.gz"
    if len(sdists) != 1 or sdists[0].name.lower() != expected_sdist_name:
        raise ContractError(
            f"pinned MarkupSafe source lock must download exactly {expected_sdist_name}"
        )
    sdist = sdists[0]
    sdist_digest = sha256_file(sdist)
    if sdist_digest != build_lock["source_sha256"]:
        raise ContractError("downloaded MarkupSafe sdist differs from its pinned source hash")

    _run([str(host_python), "-m", "venv", str(builder_env)], cwd=root, env=env, timeout=120)
    builder_python = _venv_python(builder_env)
    _run(
        [
            str(builder_python),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--no-deps",
            "--only-binary=:all:",
            "-r",
            str(root / MARKUPSAFE_BUILD_LOCK_RELATIVE),
        ],
        cwd=root,
        env=env,
        timeout=600,
    )
    _run(
        [
            str(builder_python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(built_wheels),
            str(sdist),
        ],
        cwd=root,
        env=env,
        timeout=600,
    )
    wheels = sorted(built_wheels.glob("*.whl"))
    if len(wheels) != 1:
        raise ContractError(f"building MarkupSafe must produce one wheel, found {len(wheels)}")
    wheel = wheels[0]
    _validate_markupsafe_wheel(wheel, build_lock["source_version"])
    wheel_digest = sha256_file(wheel)

    requirement_path = build_root / "install-requirement.txt"
    requirement_path.write_text(
        f"MarkupSafe @ {wheel.resolve().as_uri()} --hash=sha256:{wheel_digest}\n",
        encoding="utf-8",
    )
    return {
        "name": "markupsafe",
        "version": build_lock["source_version"],
        "source_lock_path": MARKUPSAFE_SOURCE_LOCK_RELATIVE.as_posix(),
        "source_lock_sha256": build_lock["source_lock_sha256"],
        "source_sha256": sdist_digest,
        "sdist_path": sdist.relative_to(root).as_posix(),
        "build_lock_path": MARKUPSAFE_BUILD_LOCK_RELATIVE.as_posix(),
        "build_lock_sha256": build_lock["build_lock_sha256"],
        "pip_version": build_lock["pip_version"],
        "builder_version": build_lock["builder_version"],
        "wheel_path": wheel.relative_to(root).as_posix(),
        "wheel_sha256": wheel_digest,
        "install_requirement_path": requirement_path.relative_to(root).as_posix(),
    }


def _validate_markupsafe_build_artifacts(
    root: Path,
    python_version: str,
    build_artifacts: Any,
    *,
    verify_files: bool = True,
) -> list[dict[str, str]]:
    if not isinstance(build_artifacts, list):
        raise ContractError("prepared MarkupSafe build artifact inventory is malformed")
    if python_version != "3.14":
        if build_artifacts:
            raise ContractError("non-3.14 environments must not use the MarkupSafe source fallback")
        return []
    if len(build_artifacts) != 1 or not isinstance(build_artifacts[0], dict):
        raise ContractError("CPython 3.14 environments must identify one built MarkupSafe wheel")

    artifact = build_artifacts[0]
    expected_fields = {
        "name",
        "version",
        "source_lock_path",
        "source_lock_sha256",
        "source_sha256",
        "sdist_path",
        "build_lock_path",
        "build_lock_sha256",
        "pip_version",
        "builder_version",
        "wheel_path",
        "wheel_sha256",
        "install_requirement_path",
    }
    if set(artifact) != expected_fields or any(
        not isinstance(value, str) for value in artifact.values()
    ):
        raise ContractError("prepared MarkupSafe build artifact identity is malformed")
    source_lock_path = root / MARKUPSAFE_SOURCE_LOCK_RELATIVE
    build_lock_path = root / MARKUPSAFE_BUILD_LOCK_RELATIVE
    runtime = _lock_declarations(root / RUNTIME_LOCK_RELATIVE)
    source = _lock_declarations(source_lock_path)
    builder = _lock_declarations(build_lock_path)
    if (
        artifact["name"] != "markupsafe"
        or set(source) != {"markupsafe"}
        or "markupsafe" not in runtime
        or source["markupsafe"][0] != runtime["markupsafe"][0]
        or artifact["version"] != runtime["markupsafe"][0]
        or source["markupsafe"][1] != {artifact["source_sha256"]}
        or set(builder) != {"pip", "setuptools"}
        or any(len(hashes) != 1 for _, hashes in builder.values())
        or artifact["pip_version"] != builder["pip"][0]
        or artifact["builder_version"] != builder["setuptools"][0]
        or artifact["source_lock_path"] != MARKUPSAFE_SOURCE_LOCK_RELATIVE.as_posix()
        or artifact["build_lock_path"] != MARKUPSAFE_BUILD_LOCK_RELATIVE.as_posix()
        or artifact["source_lock_sha256"] != sha256_file(source_lock_path)
        or artifact["build_lock_sha256"] != sha256_file(build_lock_path)
    ):
        raise ContractError("prepared MarkupSafe build artifact differs from its committed locks")
    try:
        builder_version_parts = tuple(int(part) for part in artifact["builder_version"].split("."))
    except ValueError as exc:
        raise ContractError("prepared MarkupSafe setuptools version must be numeric") from exc
    if builder_version_parts[:2] < (70, 1):
        raise ContractError("MarkupSafe 3.0.2 source builds require setuptools 70.1 or newer")

    build_root = (
        root / "build" / "parity" / "wheelhouse" / f"markupsafe-{artifact['version']}"
    ).resolve()
    artifacts = {
        "sdist_path": artifact["sdist_path"],
        "wheel_path": artifact["wheel_path"],
        "install_requirement_path": artifact["install_requirement_path"],
    }
    expected_build_relative = Path("build/parity/wheelhouse") / f"markupsafe-{artifact['version']}"
    sdist_relative = Path(artifacts["sdist_path"])
    wheel_relative = Path(artifacts["wheel_path"])
    requirement_relative = Path(artifacts["install_requirement_path"])
    if (
        sdist_relative.parent != expected_build_relative / "source"
        or sdist_relative.name.lower() != f"markupsafe-{artifact['version']}.tar.gz"
        or wheel_relative.parent != expected_build_relative / "wheels"
        or not wheel_relative.name.lower().startswith(f"markupsafe-{artifact['version']}-")
        or wheel_relative.suffix != ".whl"
        or requirement_relative != expected_build_relative / "install-requirement.txt"
    ):
        raise ContractError("prepared MarkupSafe build artifact paths have an unexpected layout")
    resolved: dict[str, Path] = {}
    for field, relative in artifacts.items():
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or "\\" in relative
            or relative_path.as_posix() != relative
        ):
            raise ContractError(f"prepared MarkupSafe {field} must stay repository-relative")
        path = (root / relative_path).resolve()
        try:
            path.relative_to(build_root)
        except ValueError as exc:
            raise ContractError(f"prepared MarkupSafe {field} escapes its build directory") from exc
        if verify_files and not path.is_file():
            raise ContractError(f"prepared MarkupSafe build artifact is missing: {relative}")
        resolved[field] = path

    if verify_files:
        if (
            resolved["sdist_path"].name.lower() != f"markupsafe-{artifact['version']}.tar.gz"
            or sha256_file(resolved["sdist_path"]) != artifact["source_sha256"]
            or not resolved["wheel_path"].name.endswith(".whl")
            or sha256_file(resolved["wheel_path"]) != artifact["wheel_sha256"]
        ):
            raise ContractError("prepared MarkupSafe source or wheel artifact has changed")
        _validate_markupsafe_wheel(resolved["wheel_path"], artifact["version"])
        expected_requirement = (
            f"MarkupSafe @ {resolved['wheel_path'].as_uri()} "
            f"--hash=sha256:{artifact['wheel_sha256']}\n"
        )
        try:
            requirement = resolved["install_requirement_path"].read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContractError(
                f"cannot read generated MarkupSafe install requirement: {exc}"
            ) from exc
        if requirement != expected_requirement:
            raise ContractError("generated MarkupSafe wheel install requirement has changed")
    return [artifact]


def _target_wheel(root: Path, wheelhouse: Path, python: Path, env: dict[str, str]) -> Path:
    wheelhouse.mkdir(parents=True)
    _run(
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            "--config-settings=build-args=--features pyo3/extension-module,fault-contract",
            str(root),
        ],
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
    """Build the target wheel and prepare isolated venvs for one CPython minor."""
    root = root.resolve()
    upstream = upstream.resolve()
    host_python = (python or Path(sys.executable)).resolve()
    if not host_python.is_file():
        raise ContractError(f"requested Python interpreter is absent: {host_python}")
    host_probe = _probe(host_python, root)
    python_version = python_version_from_runtime(
        f"{host_probe['implementation']} {host_probe['python']}"
    )
    environment_pair = environment_ids(python_version)
    target_source = _target_source_identity(root)
    revision, _ = _source_revision(upstream)
    lock_path = root / RUNTIME_LOCK_RELATIVE
    lock_digest = validate_runtime_lock(root, upstream)
    oracle_lock_path = root / ORACLE_RUNTIME_LOCK_RELATIVE
    oracle_lock_digest = validate_oracle_runtime_lock(root, upstream)
    markupsafe_build_lock = validate_markupsafe_build_locks(root, upstream)

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
    build_artifacts: list[dict[str, str]] = []
    if python_version == "3.14":
        build_artifacts.append(
            _build_markupsafe_wheel(root, host_python, wheelhouse, env, markupsafe_build_lock)
        )
    build_artifacts = _validate_markupsafe_build_artifacts(root, python_version, build_artifacts)
    if _target_source_identity(root) != target_source:
        raise ContractError("target source checkout changed while building the prepared wheel")
    env_root.mkdir(parents=True)

    records: list[dict[str, Any]] = []
    version_root = env_root / python_version_tag(python_version)
    source_path = _venv_python(version_root / "oracle")
    target_path = _venv_python(version_root / "python-package")
    for environment, environment_lock in (
        (version_root / "oracle", oracle_lock_path),
        (version_root / "python-package", lock_path),
    ):
        _run([str(host_python), "-m", "venv", str(environment)], cwd=root, env=env, timeout=120)
        venv_python = _venv_python(environment)
        if not venv_python.is_file():
            raise ContractError(f"venv creation did not produce interpreter: {venv_python}")
        install_lock = environment_lock
        if build_artifacts:
            filtered_lock = (
                wheelhouse
                / f"markupsafe-{build_artifacts[0]['version']}"
                / f"{environment.name}-runtime-lock.txt"
            )
            _write_runtime_lock_without_markupsafe(environment_lock, filtered_lock)
            install_lock = filtered_lock
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
                str(install_lock),
            ],
            cwd=root,
            env=env,
            timeout=600,
        )
        if build_artifacts:
            requirement = root / build_artifacts[0]["install_requirement_path"]
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
                    str(requirement),
                ],
                cwd=root,
                env=env,
                timeout=600,
            )

    _install_source_distribution_metadata(
        upstream,
        version_root / "oracle",
        source_path,
        root,
    )

    _run(
        [str(target_path), "-m", "pip", "install", "--no-deps", str(wheel.resolve())],
        cwd=root,
        env=env,
        timeout=600,
    )

    for environment_id, interpreter, artifact_digest, runtime_lock_path, runtime_lock_digest in (
        (environment_pair[0], source_path, None, ORACLE_RUNTIME_LOCK_RELATIVE, oracle_lock_digest),
        (environment_pair[1], target_path, wheel_digest, RUNTIME_LOCK_RELATIVE, lock_digest),
    ):
        probe = _probe(interpreter, root)
        if environment_id == environment_pair[0]:
            _validate_oracle_source_distribution(probe)
        relative_python = interpreter.relative_to(root).as_posix()
        records.append(
            _environment_fingerprints(
                environment_id,
                relative_python,
                runtime_lock_path,
                runtime_lock_digest,
                probe,
                artifact_digest,
                build_artifacts,
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
            "parity environments are not prepared; run `python -m scripts.parity.cli prepare-env` with CPython 3.10 through 3.14"
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
    if not isinstance(rows, list) or len(rows) != 2:
        raise ContractError("prepared environment lock must describe one oracle/package pair")
    runtimes = {row.get("runtime") for row in rows if isinstance(row, dict) and "runtime" in row}
    if len(runtimes) != 1:
        raise ContractError("prepared oracle and package environments must use one CPython minor")
    python_version = python_version_from_runtime(next(iter(runtimes)))
    environment_pair = environment_ids(python_version)
    if {row.get("id") for row in rows if isinstance(row, dict)} != set(environment_pair):
        raise ContractError(
            "prepared environment lock must describe the matching oracle and installed-wheel profile"
        )
    expected_locks = {
        environment_pair[0]: ORACLE_RUNTIME_LOCK_RELATIVE,
        environment_pair[1]: RUNTIME_LOCK_RELATIVE,
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
        "build_artifacts",
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
            target_wheel["sha256"] if row["id"] == environment_pair[1] else None
        ):
            raise ContractError(f"{row['id']} target artifact identity mismatch")
        build_artifacts = _validate_markupsafe_build_artifacts(
            root, python_version, row["build_artifacts"]
        )
        python_relative = Path(row["python"])
        if python_relative.is_absolute() or ".." in python_relative.parts:
            raise ContractError(f"{row['id']} interpreter path must remain repository-relative")
        interpreter = root / python_relative
        if not interpreter.is_file() or not interpreter.absolute().is_relative_to(
            (root / "build/parity/envs").absolute()
        ):
            raise ContractError(f"{row['id']} interpreter is not under build/parity/envs")
        probe = _probe(interpreter, root)
        if row["id"] == environment_pair[0]:
            _validate_oracle_source_distribution(probe)
        actual = _environment_fingerprints(
            row["id"],
            row["python"],
            expected_lock,
            lock_digest,
            probe,
            row["artifact_sha256"],
            build_artifacts,
        )
        if actual != row:
            raise ContractError(f"{row['id']} environment changed after preparation")
        output[row["id"]] = row
    target = output[environment_pair[1]]
    target_tree_sha256 = target_wheel["target_tree_sha256"]
    target["target_identity"] = {
        "target_tree_sha256": target_tree_sha256,
        "dirty": target_source["dirty"],
        "source_revision": target_source["revision"],
    }
    if not require_target:
        output.pop(environment_pair[1], None)
    return output
