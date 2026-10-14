#!/usr/bin/env python3
"""Validate GitHub Actions workflows with a checksum-pinned actionlint binary."""

from __future__ import annotations

import hashlib
import io
import platform
import re
import subprocess
import tarfile
import urllib.request
from pathlib import Path

VERSION = "1.7.12"
# Official release checksums: https://github.com/rhysd/actionlint/releases/tag/v1.7.12
ARCHIVES = {
    ("Darwin", "arm64"): (
        "darwin_arm64",
        "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f",
    ),
    ("Darwin", "x86_64"): (
        "darwin_amd64",
        "5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644",
    ),
    ("Linux", "x86_64"): (
        "linux_amd64",
        "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
    ),
    ("Linux", "aarch64"): (
        "linux_arm64",
        "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
    ),
}
ROOT = Path(__file__).resolve().parent.parent
USES_DIRECTIVE = re.compile(r"^\s*uses:\s*(?P<reference>[^#\s]+)")
ACTION_COMMIT = re.compile(r"^[0-9a-f]{40}$")
CONTAINER_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def binary_bytes(archive: bytes, checksum: str) -> bytes:
    if hashlib.sha256(archive).hexdigest() != checksum:
        raise ValueError("actionlint archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as contents:
        member = contents.getmember("actionlint")
        if not member.isfile():
            raise ValueError("actionlint archive does not contain a regular binary")
        # Copy only the verified member; never extract archive paths or links.
        source = contents.extractfile(member)
        if source is None:
            raise ValueError("actionlint binary is missing")
        return source.read()


def check_immutable_action_references(workflows: list[Path]) -> list[str]:
    """Require external workflow actions and container actions to be immutable."""
    violations: list[str] = []
    for workflow in workflows:
        for line_number, line in enumerate(workflow.read_text().splitlines(), start=1):
            match = USES_DIRECTIVE.match(line)
            if match is None:
                continue

            reference = match.group("reference")
            if reference.startswith("./"):
                continue
            if reference.startswith("docker://"):
                pinned = CONTAINER_DIGEST.search(reference) is not None
                requirement = "a sha256 image digest"
            else:
                _, separator, revision = reference.rpartition("@")
                pinned = bool(separator) and ACTION_COMMIT.fullmatch(revision) is not None
                requirement = "a full 40-character commit SHA"

            if not pinned:
                relative = workflow.relative_to(ROOT)
                violations.append(
                    f"{relative}:{line_number}: external workflow action reference "
                    f"{reference!r} must use {requirement}"
                )
    return violations


def main() -> int:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
    if not workflows:
        raise SystemExit("No GitHub workflows found")
    violations = check_immutable_action_references(workflows)
    if violations:
        print("Workflow action pinning violations:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    target = (platform.system(), platform.machine())
    if target not in ARCHIVES:
        raise SystemExit(f"Workflow lint supports Linux/macOS x86-64 and ARM64; got {target}")
    suffix, checksum = ARCHIVES[target]
    directory = ROOT / "target" / "workflow-tools" / f"actionlint-{VERSION}-{suffix}"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "archive.tar.gz"
    if archive.exists():
        data = archive.read_bytes()
    else:
        url = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}/actionlint_{VERSION}_{suffix}.tar.gz"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
    executable = binary_bytes(data, checksum)
    archive.write_bytes(data)
    binary = directory / "actionlint"
    binary.write_bytes(executable)
    binary.chmod(0o755)
    # Shell and Python linters are separate tools, not host-dependent checks.
    result = subprocess.run(
        [str(binary), "-shellcheck=", "-pyflakes=", *(str(path) for path in workflows)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode == 0:
        print(f"Workflow lint passed: {len(workflows)} files, actionlint {VERSION}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
