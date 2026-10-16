#!/usr/bin/env python3
"""Enforce parity-only behavioral checks and the Rust workspace lint policy."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 tooling fallback
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = ROOT / "tests"
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
    r"^\s*#\[\s*(?:"
    r"cfg\s*\(\s*(?:test|(?:all|any)\s*\([^]]*\btest\b[^]]*\))\s*\)|"
    r"(?:tokio::|async_std::)?test(?:\s*\([^]]*\))?|rstest|test_case)\s*\]",
    re.MULTILINE,
)
RUST_TEST_MODULE = re.compile(r"^\s*mod\s+tests\s*(?:\{|;)", re.MULTILINE)
RUST_ATTRIBUTE_START = re.compile(r"^\s*#(?P<inner>!)?\[")
RUST_ALLOW_DIRECTIVE = re.compile(r"\ballow\s*\(")
RUST_CFG_ALLOW_DIRECTIVE = re.compile(r",\s*allow\s*\(")
RUST_LINT_EXCEPTION = re.compile(r"^\s*// LINT EXCEPTION:\s*(?P<rationale>.+\S)\s*$")
MIN_LINT_EXCEPTION_RATIONALE_LENGTH = 40
RUST_LINT_GROUPS = frozenset(
    {
        "future_incompatible",
        "nonstandard_style",
        "rust_2018_idioms",
        "unused",
        "warnings",
        "rustdoc::all",
    }
)
CLIPPY_LINT_GROUPS = frozenset(
    {
        "clippy::all",
        "clippy::cargo",
        "clippy::complexity",
        "clippy::correctness",
        "clippy::nursery",
        "clippy::pedantic",
        "clippy::perf",
        "clippy::restriction",
        "clippy::style",
        "clippy::suspicious",
    }
)
BROAD_RUST_LINT_GROUPS = RUST_LINT_GROUPS | CLIPPY_LINT_GROUPS
LINT_LEVEL_RANK = {"allow": 0, "warn": 1, "deny": 2, "forbid": 3}
REQUIRED_WORKSPACE_LINT_LEVELS = {
    "rust": {
        "future_incompatible": "deny",
        "nonstandard_style": "deny",
        "unused": "deny",
        "dead_code": "deny",
        "private_bounds": "deny",
        "private_interfaces": "deny",
        "unreachable_pub": "deny",
        "unused_crate_dependencies": "warn",
        "unsafe_code": "deny",
        "deprecated": "deny",
        "missing_docs": "warn",
        "rust_2018_idioms": "warn",
        "unused_must_use": "deny",
    },
    "clippy": {
        "all": "warn",
        "unwrap_used": "deny",
        "expect_used": "deny",
        "unwrap_in_result": "deny",
        "todo": "deny",
        "unimplemented": "deny",
        "panic": "deny",
        "dbg_macro": "warn",
        "redundant_clone": "deny",
        "large_enum_variant": "deny",
        "needless_collect": "deny",
        "clone_on_copy": "deny",
        "unnecessary_to_owned": "deny",
        "needless_borrow": "deny",
        "map_unwrap_or": "deny",
        "needless_range_loop": "deny",
        "unnecessary_cast": "deny",
        "cast_possible_truncation": "deny",
        "cast_sign_loss": "deny",
        "manual_assert": "deny",
        "panic_in_result_fn": "deny",
        "debug_assert_with_mut_call": "deny",
    },
}
REQUIRED_WORKSPACE_LINT_PRIORITIES = {
    "rust": {
        "future_incompatible": -1,
        "nonstandard_style": -1,
        "unused": -1,
        "rust_2018_idioms": -1,
    },
    "clippy": {
        "all": -1,
    },
}
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
DISTRIBUTED_NOTICE_FILES = (
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_RUST_LICENSES.md",
)
PYTHON_TEST_FRAMEWORK_IMPORT = re.compile(
    r"^\s*(?:from\s+(?:pytest|unittest)(?:\.|\s)|import\s+(?:pytest|unittest)(?:\.|\s|$))",
    re.MULTILINE,
)
MAKE_TEST_TARGET = re.compile(r"^test\s*:\s*([^\n]*)", re.MULTILINE)
PROJECT_SECTION = re.compile(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)")
PROJECT_DEPENDENCIES = re.compile(r"(?ms)^dependencies\s*=\s*\[(.*?)\]")
DEPENDENCY_NAME = re.compile(r"^\s*['\"]([^<>=!~;\s\[]+)")


def rust_sources(workspace_roots: list[Path]) -> list[Path]:
    return sorted({path for root in workspace_roots for path in root.rglob("*.rs")})


def read_toml_document(path: Path, violations: list[str]) -> dict[str, object] | None:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        violations.append(f"{path.relative_to(ROOT)}: unable to read TOML policy: {error}")
        return None


def lint_level_and_priority(value: object) -> tuple[object, object]:
    if isinstance(value, dict):
        return value.get("level"), value.get("priority", 0)
    if isinstance(value, str):
        return value, 0
    return None, None


def check_rust_workspace_lint_policy(violations: list[str]) -> list[Path]:
    root_manifest = read_toml_document(ROOT / "Cargo.toml", violations)
    if root_manifest is None:
        return []

    workspace = root_manifest.get("workspace")
    workspace_lints = workspace.get("lints") if isinstance(workspace, dict) else None
    if not isinstance(workspace_lints, dict):
        violations.append("Cargo.toml: [workspace.lints] must define the shared Rust lint policy")
        workspace_lints = {}

    for namespace, required_lints in REQUIRED_WORKSPACE_LINT_LEVELS.items():
        configured = workspace_lints.get(namespace)
        if not isinstance(configured, dict):
            violations.append(f"Cargo.toml: [workspace.lints.{namespace}] is required")
            continue

        for lint_name, required_level in required_lints.items():
            configured_level, _ = lint_level_and_priority(configured.get(lint_name))
            configured_rank = LINT_LEVEL_RANK.get(configured_level)
            required_rank = LINT_LEVEL_RANK[required_level]
            if configured_rank is None or configured_rank < required_rank:
                violations.append(
                    f"Cargo.toml: workspace lint `{namespace}::{lint_name}` must be at least "
                    f"`{required_level}`"
                )

        for lint_name, required_priority in REQUIRED_WORKSPACE_LINT_PRIORITIES[namespace].items():
            _, configured_priority = lint_level_and_priority(configured.get(lint_name))
            if configured_priority != required_priority:
                violations.append(
                    f"Cargo.toml: workspace lint group `{namespace}::{lint_name}` must keep "
                    f"priority {required_priority} so specific lint levels take precedence"
                )

    try:
        metadata_result = subprocess.run(
            ["cargo", "metadata", "--no-deps", "--format-version", "1"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        violations.append(f"Cargo.toml: unable to enumerate workspace members with cargo: {error}")
        return []

    if metadata_result.returncode != 0:
        detail = metadata_result.stderr.strip()
        violations.append(
            "Cargo.toml: cargo metadata could not enumerate workspace members"
            + (f": {detail}" if detail else "")
        )
        return []

    try:
        metadata = json.loads(metadata_result.stdout)
    except json.JSONDecodeError as error:
        violations.append(f"Cargo.toml: cargo metadata returned invalid JSON: {error}")
        return []

    member_ids = metadata.get("workspace_members")
    packages = metadata.get("packages")
    if not isinstance(member_ids, list) or not isinstance(packages, list):
        violations.append("Cargo.toml: cargo metadata omitted workspace members or packages")
        return []

    member_id_set = set(member_ids)
    members = [package for package in packages if package.get("id") in member_id_set]
    if len(members) != len(member_id_set):
        violations.append("Cargo.toml: cargo metadata did not describe every workspace member")

    workspace_root = ROOT.resolve()
    package_roots: list[Path] = []
    for package in members:
        manifest_path = Path(package["manifest_path"]).resolve()
        if not manifest_path.is_relative_to(workspace_root):
            violations.append(
                f"{manifest_path}: workspace member manifest must remain inside the repository"
            )
            continue

        package_root = manifest_path.parent
        package_roots.append(package_root)
        member_manifest = read_toml_document(manifest_path, violations)
        if member_manifest is None:
            continue

        member_lints = member_manifest.get("lints")
        member_name = package.get("name", package_root.relative_to(ROOT).as_posix())
        if not isinstance(member_lints, dict) or member_lints.get("workspace") is not True:
            violations.append(
                f"{package_root.relative_to(ROOT)}/Cargo.toml: workspace member `{member_name}` "
                "must inherit the root lint policy with `[lints] workspace = true`"
            )
            continue

        for namespace, local_lints in member_lints.items():
            if namespace == "workspace":
                continue
            if namespace not in REQUIRED_WORKSPACE_LINT_LEVELS:
                continue
            if not isinstance(local_lints, dict):
                violations.append(
                    f"{package_root.relative_to(ROOT)}/Cargo.toml: [lints.{namespace}] "
                    "must be a table"
                )
                continue
            for lint_name, local_value in local_lints.items():
                qualified_name = f"clippy::{lint_name}" if namespace == "clippy" else lint_name
                if qualified_name in BROAD_RUST_LINT_GROUPS:
                    violations.append(
                        f"{package_root.relative_to(ROOT)}/Cargo.toml: workspace member "
                        f"`{member_name}` cannot override lint group `{qualified_name}`"
                    )

                local_level, _ = lint_level_and_priority(local_value)
                if local_level == "allow":
                    violations.append(
                        f"{package_root.relative_to(ROOT)}/Cargo.toml: workspace member "
                        f"`{member_name}` cannot allow `{qualified_name}` in Cargo.toml; "
                        "keep lint policy at the workspace root"
                    )

                root_lints = workspace_lints.get(namespace)
                root_value = root_lints.get(lint_name) if isinstance(root_lints, dict) else None
                if root_value is None:
                    continue
                root_level, _ = lint_level_and_priority(root_value)
                local_rank = LINT_LEVEL_RANK.get(local_level)
                root_rank = LINT_LEVEL_RANK.get(root_level)
                if local_rank is None or root_rank is None or local_rank < root_rank:
                    violations.append(
                        f"{package_root.relative_to(ROOT)}/Cargo.toml: workspace member "
                        f"`{member_name}` weakens `{qualified_name}` below the root policy"
                    )

    return sorted(set(package_roots))


def python_sources() -> list[Path]:
    return sorted(path for root in PYTHON_SOURCE_ROOTS for path in root.rglob("*.py"))


def check_rust_lint_exceptions(path: Path, source: str, violations: list[str]) -> None:
    lines = source.splitlines()
    for index, line in enumerate(lines):
        attribute_start = RUST_ATTRIBUTE_START.match(line)
        if attribute_start is None:
            continue

        end_index = index
        attribute_lines = [line]
        while "]" not in attribute_lines[-1] and end_index + 1 < len(lines):
            end_index += 1
            attribute_lines.append(lines[end_index])
        attribute = "\n".join(attribute_lines)
        attribute_body = attribute.split("[", maxsplit=1)[1].rsplit("]", maxsplit=1)[0]
        attribute_body = attribute_body.lstrip()
        if attribute_body.startswith("!"):
            attribute_body = attribute_body[1:].lstrip()

        if attribute_body.startswith("allow"):
            allow_matches = list(RUST_ALLOW_DIRECTIVE.finditer(attribute_body))[:1]
        elif attribute_body.startswith("cfg_attr"):
            allow_matches = list(RUST_CFG_ALLOW_DIRECTIVE.finditer(attribute_body))
        else:
            continue
        if not allow_matches:
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

        if attribute_start.group("inner") is not None:
            violations.append(
                f"{path.relative_to(ROOT)}:{index + 1}: crate- or module-wide Rust lint "
                "allows are disallowed; scope exceptions to a specific item"
            )

        for allow_match in allow_matches:
            opening_parenthesis = attribute_body.find("(", allow_match.start())
            closing_parenthesis = attribute_body.find(")", opening_parenthesis + 1)
            lint_arguments = attribute_body[
                opening_parenthesis + 1 : closing_parenthesis if closing_parenthesis >= 0 else None
            ]
            lint_names = {
                item.partition("=")[0].strip() for item in lint_arguments.split(",") if item.strip()
            }
            broad_groups = lint_names & BROAD_RUST_LINT_GROUPS
            if broad_groups:
                rendered_groups = ", ".join(sorted(broad_groups))
                violations.append(
                    f"{path.relative_to(ROOT)}:{index + 1}: broad Rust lint groups cannot be "
                    f"allowed (`{rendered_groups}`); allow only a narrowly scoped individual lint"
                )


def is_static_typing_import_guard(path: Path, node: ast.AST) -> bool:
    """Allow the pinned source's import-only TYPE_CHECKING block in types.py."""
    # These imports preserve the public callback annotations for static consumers;
    # TYPE_CHECKING is false at runtime, so this does not add wrapper behavior.
    return (
        path == PYTHON_RUNTIME_ROOT / "types.py"
        and isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
        and not node.orelse
        and bool(node.body)
        and all(isinstance(statement, (ast.Import, ast.ImportFrom)) for statement in node.body)
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


def check_rust_crate_notice_copies(violations: list[str]) -> None:
    crate_root = ROOT / "starlette-rs"
    for name in DISTRIBUTED_NOTICE_FILES:
        canonical = ROOT / name
        packaged = crate_root / name
        if not canonical.is_file() or not packaged.is_file():
            violations.append(
                f"{packaged.relative_to(ROOT)}: required distributed notice is missing"
            )
        elif canonical.read_bytes() != packaged.read_bytes():
            violations.append(
                f"{packaged.relative_to(ROOT)}: distributed notice differs from root/{name}"
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
    check_rust_crate_notice_copies(violations)

    for path in TESTS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".py", ".rs"}:
            violations.append(
                f"{path.relative_to(ROOT)}: executable test source must be replaced "
                "with an input-only parity definition under tests/fixtures"
            )

    workspace_roots = check_rust_workspace_lint_policy(violations)
    for path in rust_sources(workspace_roots):
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
            if is_static_typing_import_guard(path, node):
                continue
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
        "control flow in Python Starlette wrappers; Rust lint exceptions and "
        "workspace lint levels and member inheritance are enforced, broad lint "
        "groups cannot be suppressed, crate notice copies are checked, parity "
        "JSON is ignored; `make test` routes to live parity"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
