#!/usr/bin/env python3
"""Enforce the repository's parity-only behavioral-check policy."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
FIXTURE_ROOT = TESTS_ROOT / "fixtures"
RUST_PACKAGE_ROOTS = (ROOT / "starlette-rs", ROOT / "starlette-rs-py")
PYTHON_SOURCE_ROOTS = (
    ROOT / "scripts",
    ROOT / "starlette-rs-py",
)
PYTHON_RUNTIME_ROOT = ROOT / "starlette-rs-py" / "python" / "starlette"
PYTHON_RUNTIME_CONTROL_FLOW_NAMES = (
    "If",
    "For",
    "AsyncFor",
    "While",
    "IfExp",
    "ListComp",
    "SetComp",
    "DictComp",
    "GeneratorExp",
    "BoolOp",
    "Raise",
    "Assert",
    "Try",
    "Match",
)
PYTHON_RUNTIME_CONTROL_FLOW = tuple(
    node_type
    for name in PYTHON_RUNTIME_CONTROL_FLOW_NAMES
    if (node_type := getattr(ast, name, None)) is not None
)
RUST_TEST_ATTRIBUTES = re.compile(
    r"^\s*#\[\s*(?:cfg\s*\(\s*test\s*\)|"
    r"(?:tokio::|async_std::)?test(?:\s*\([^]]*\))?|rstest)\s*\]",
    re.MULTILINE,
)
RUST_TEST_MODULE = re.compile(r"^\s*mod\s+tests\s*(?:\{|;)", re.MULTILINE)
RUST_ALLOW_ATTRIBUTE = re.compile(r"^\s*#!?\[\s*allow\s*\(")
RUST_LINT_EXCEPTION = re.compile(r"^\s*// LINT EXCEPTION:\s*(?P<rationale>.+\S)\s*$")
MIN_LINT_EXCEPTION_RATIONALE_LENGTH = 40
GENERATED_PARITY_JSON_PATHS = (
    "build/parity/inputs/parity/asgi-http-get-text.json",
    "build/parity/inputs/benchmark/asgi-get-hello.json",
    "build/parity/inputs/benchmark/starlette-upstream-workloads.json",
    "build/parity/parity-result.json",
    "build/parity/benchmark-result.json",
    "build/parity/benchmark-correctness-result.json",
    "build/parity/upstream-benchmark-result.json",
    "build/parity/upstream-benchmark-correctness-result.json",
)
PYTHON_TEST_FRAMEWORK_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:pytest|unittest)(?:\.|\s)|import\s+(?:pytest|unittest)(?:\.|\s|$))",
    re.MULTILINE,
)
MAKE_TEST_TARGET = re.compile(r"^test\s*:\s*([^\n]*)", re.MULTILINE)
PROJECT_SECTION = re.compile(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)")
PROJECT_DEPENDENCIES = re.compile(r"(?ms)^dependencies\s*=\s*\[(.*?)\]")
DEPENDENCY_NAME = re.compile(r"^\s*['\"]([^<>=!~;\s\[]+)")


def rust_sources() -> list[Path]:
    return sorted(path for root in RUST_PACKAGE_ROOTS for path in root.rglob("*.rs"))


def python_sources() -> list[Path]:
    return sorted(path for root in PYTHON_SOURCE_ROOTS for path in root.rglob("*.py"))


def check_rust_lint_exceptions(path: Path, source: str, violations: list[str]) -> None:
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if not RUST_ALLOW_ATTRIBUTE.match(line):
            continue
        rationale_line = lines[index - 1] if index > 0 else ""
        rationale = RUST_LINT_EXCEPTION.match(rationale_line)
        if (
            rationale is None
            or len(rationale.group("rationale").strip()) < MIN_LINT_EXCEPTION_RATIONALE_LENGTH
        ):
            violations.append(
                f"{path.relative_to(ROOT)}:{index + 1}: Rust lint allow attributes need an "
                "immediately adjacent `// LINT EXCEPTION:` comment with a specific rationale "
                f"of at least {MIN_LINT_EXCEPTION_RATIONALE_LENGTH} characters"
            )


def check_generated_parity_json(violations: list[str]) -> None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--", "build/parity"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        violations.append(f"build/parity: unable to inspect tracked outputs with git: {error}")
        return

    if tracked.returncode != 0:
        detail = tracked.stderr.strip()
        violations.append(
            "build/parity: `git ls-files` could not verify generated JSON tracking"
            + (f": {detail}" if detail else "")
        )
        return

    for relative_path in tracked.stdout.splitlines():
        if Path(relative_path).suffix.lower() == ".json":
            violations.append(
                f"{relative_path}: generated JSON under build/parity must not be tracked"
            )

    for relative_path in GENERATED_PARITY_JSON_PATHS:
        try:
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", "--no-index", "--", relative_path],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            violations.append(
                f"{relative_path}: unable to verify generated-output ignore rule: {error}"
            )
            continue
        if ignored.returncode != 0:
            detail = ignored.stderr.strip()
            violations.append(
                f"{relative_path}: generated parity input/result path must be ignored by Git"
                + (f" ({detail})" if detail else "")
            )


def main() -> int:
    violations: list[str] = []
    check_generated_parity_json(violations)

    for path in TESTS_ROOT.rglob("*"):
        if not path.is_file() or path.is_relative_to(FIXTURE_ROOT):
            continue
        if path.suffix in {".py", ".rs"}:
            violations.append(
                f"{path.relative_to(ROOT)}: executable test source must be replaced "
                "with an input-only parity definition under tests/fixtures"
            )

    for path in rust_sources():
        source = path.read_text()
        check_rust_lint_exceptions(path, source, violations)
        for pattern in (RUST_TEST_ATTRIBUTES, RUST_TEST_MODULE):
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                violations.append(
                    f"{path.relative_to(ROOT)}:{line}: conventional Rust unit-test "
                    "harnesses are disallowed; use live parity inputs"
                )

    for path in python_sources():
        if path.name.startswith("test_"):
            violations.append(
                f"{path.relative_to(ROOT)}: conventional Python test modules are "
                "disallowed; use live parity inputs"
            )
        for line, text in enumerate(path.read_text().splitlines(), 1):
            if PYTHON_TEST_FRAMEWORK_IMPORT.match(text):
                violations.append(
                    f"{path.relative_to(ROOT)}:{line}: pytest/unittest imports are "
                    "disallowed in project tooling and runtime sources"
                )

    for path in sorted(PYTHON_RUNTIME_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, PYTHON_RUNTIME_CONTROL_FLOW):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: Python compatibility "
                    f"wrappers must forward behavior to Rust ({type(node).__name__})"
                )

    project_metadata = (ROOT / "pyproject.toml").read_text()
    project_section = PROJECT_SECTION.search(project_metadata)
    dependencies_block = (
        PROJECT_DEPENDENCIES.search(project_section.group(1))
        if project_section is not None
        else None
    )
    if dependencies_block is None:
        violations.append("pyproject.toml: unable to locate project runtime dependencies")
    else:
        for dependency in DEPENDENCY_NAME.finditer(dependencies_block.group(1)):
            normalized_name = re.sub(r"[-_.]+", "-", dependency.group(1)).casefold()
            if normalized_name == "starlette":
                violations.append(
                    "pyproject.toml: the upstream Starlette distribution cannot be a "
                    "runtime dependency of this replacement"
                )

    makefile = (ROOT / "Makefile").read_text()
    test_target = MAKE_TEST_TARGET.search(makefile)
    if test_target is None or "parity-run" not in test_target.group(1).split():
        violations.append("Makefile: the maintained `test` target must run parity-run")
    if re.search(r"\bcargo\s+test\b|\bpytest\b|python(?:3(?:\.\d+)?)?\s+-m\s+unittest", makefile):
        violations.append("Makefile: conventional unit-test commands are disallowed")

    if violations:
        print("project policy violations:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print(
        "project policy check passed: no conventional unit-test sources or "
        "framework imports, no upstream Starlette runtime dependency, and no "
        "control flow in Python Starlette wrappers; Rust lint exceptions are "
        "documented, parity JSON is untracked and ignored; `make test` routes to live parity"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
