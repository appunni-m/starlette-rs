#!/usr/bin/env python3
"""Enforce the repository's parity-only behavioral-check policy."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
FIXTURE_ROOT = TESTS_ROOT / "fixtures"
RUST_SOURCE_ROOTS = (ROOT / "starlette-rs" / "src", ROOT / "starlette-rs-py" / "src")
PYTHON_SOURCE_ROOTS = (
    ROOT / "scripts",
    ROOT / "starlette-rs-py" / "python",
)
RUST_TEST_ATTRIBUTES = re.compile(
    r"^\s*#\[\s*(?:cfg\s*\(\s*test\s*\)|"
    r"(?:tokio::|async_std::)?test(?:\s*\([^]]*\))?|rstest)\s*\]",
    re.MULTILINE,
)
RUST_TEST_MODULE = re.compile(r"^\s*mod\s+tests\s*(?:\{|;)", re.MULTILINE)
PYTHON_TEST_FRAMEWORK_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:pytest|unittest)(?:\.|\s)|import\s+(?:pytest|unittest)(?:\.|\s|$))",
    re.MULTILINE,
)
MAKE_TEST_TARGET = re.compile(r"^test\s*:\s*([^\n]*)", re.MULTILINE)


def rust_sources() -> list[Path]:
    return sorted(path for root in RUST_SOURCE_ROOTS for path in root.rglob("*.rs"))


def python_sources() -> list[Path]:
    return sorted(path for root in PYTHON_SOURCE_ROOTS for path in root.rglob("*.py"))


def main() -> int:
    violations: list[str] = []

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
        "framework imports; `make test` routes to live parity"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
