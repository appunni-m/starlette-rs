#!/usr/bin/env python3
"""Write a source-only candidate inventory for the pinned Starlette API.

This does not import Starlette and does not decide public status. Review the
generated rows against upstream docs, exports, release notes, and behavior.
"""

from __future__ import annotations

import argparse
import ast
import copy
import csv
import io
import pathlib
import re
import subprocess
import sys

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.parity.api_sources import load_api_metadata  # noqa: E402

DOC_IMPORT = re.compile(r"\bfrom\s+(starlette(?:\.[A-Za-z_][\w]*)*)\s+import\s+([^\n]+)")
DOC_DOTTED = re.compile(r"\b(starlette(?:\.[A-Za-z_][\w]*)+)\.([A-Za-z_][\w]*)")


def module_name(root: pathlib.Path, source: pathlib.Path, package_name: str) -> str:
    relative = source.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return package_name + ("." + ".".join(parts) if parts else "")


def is_private_module(root: pathlib.Path, source: pathlib.Path) -> bool:
    return any(
        part != "__init__" and part.startswith("_")
        for part in source.relative_to(root).with_suffix("").parts
    )


def header(node: ast.AST) -> str:
    """Return a definition header, retaining its annotations and defaults."""

    clone = copy.deepcopy(node)
    clone.decorator_list = []  # type: ignore[attr-defined]
    clone.body = [ast.Pass()]  # type: ignore[attr-defined]
    ast.fix_missing_locations(clone)
    rendered = ast.unparse(clone)
    return rendered.split(":\n", 1)[0] + ":"


def expression(source: str, node: ast.AST | None) -> str:
    return "" if node is None else ast.get_source_segment(source, node) or ast.unparse(node)


def class_constructor(node: ast.ClassDef) -> str:
    for member in node.body:
        if (
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name == "__init__"
        ):
            return header(member)
    return "inherited or object default; verify"


def documented_symbols(docs_root: pathlib.Path) -> tuple[set[str], list[dict[str, str]]]:
    symbols: set[str] = set()
    records: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for doc in sorted(docs_root.rglob("*.md")):
        text = doc.read_text(encoding="utf-8")
        relative = doc.relative_to(docs_root.parent).as_posix()
        for match in DOC_IMPORT.finditer(text):
            module, imported = match.groups()
            for raw_name in imported.strip().strip("()").split(","):
                raw_name = raw_name.strip().split("#", 1)[0].strip()
                if not raw_name or raw_name.startswith("*"):
                    continue
                name = raw_name.split(" as ", 1)[0].strip()
                qualified = module + "." + name
                symbols.add(qualified)
                key = (qualified, relative, "documented-import")
                if key not in seen:
                    seen.add(key)
                    records.append(
                        {
                            "record_type": "documented-import",
                            "qualified_name": qualified,
                            "signature_or_value": "",
                            "constructor_signature": "",
                            "source": relative,
                            "line": str(text[: match.start()].count("\n") + 1),
                            "documentation_evidence": "explicit Python import in upstream docs",
                            "audit_status": "confirmed documented import path",
                        }
                    )

        for match in DOC_DOTTED.finditer(text):
            qualified = match.group(1) + "." + match.group(2)
            symbols.add(qualified)

        for line_number, line in enumerate(text.splitlines(), start=1):
            directive = line.strip().removeprefix(":::").strip()
            if directive.startswith("starlette."):
                symbols.add(directive)
                key = (directive, relative, "api-directive")
                if key not in seen:
                    seen.add(key)
                    records.append(
                        {
                            "record_type": "api-directive",
                            "qualified_name": directive,
                            "signature_or_value": "",
                            "constructor_signature": "",
                            "source": relative,
                            "line": str(line_number),
                            "documentation_evidence": "mkdocstrings API expansion directive",
                            "audit_status": "confirmed documented API reference",
                        }
                    )
    return symbols, records


def make_rows(
    source_root: pathlib.Path,
    docs_root: pathlib.Path,
    source_files: list[str],
    package_path: str,
    package_name: str,
) -> list[dict[str, str]]:
    doc_symbols, rows = documented_symbols(docs_root)
    package_root = source_root / package_path

    discovered_public = {
        source.relative_to(source_root).as_posix()
        for source in package_root.rglob("*.py")
        if not is_private_module(package_root, source)
    }
    if set(source_files) != discovered_public:
        raise SystemExit(
            "metadata.yaml public_source_files differ from the pinned source tree: "
            f"missing={sorted(discovered_public - set(source_files))}, "
            f"stale={sorted(set(source_files) - discovered_public)}"
        )

    for relative_source in source_files:
        source = (source_root / relative_source).resolve()
        if source_root.resolve() not in source.parents or not source.is_file():
            raise SystemExit(
                f"metadata.yaml API source is missing or escapes upstream: {relative_source}"
            )
        if is_private_module(package_root, source):
            continue
        if source == package_root / "__init__.py":
            continue

        module = module_name(package_root, source, package_name)
        source_text = source.read_text(encoding="utf-8")
        tree = ast.parse(source_text, filename=str(source))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name.startswith("_"):
                    continue
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                qualified = module + "." + node.name
                rows.append(
                    {
                        "record_type": kind,
                        "qualified_name": qualified,
                        "signature_or_value": header(node),
                        "constructor_signature": class_constructor(node)
                        if isinstance(node, ast.ClassDef)
                        else "",
                        "source": source.relative_to(source_root).as_posix(),
                        "line": str(node.lineno),
                        "documentation_evidence": "explicitly referenced in docs"
                        if qualified in doc_symbols
                        else "module source only; symbol not matched in docs scan",
                        "audit_status": "documented symbol; review defaults and behavior"
                        if qualified in doc_symbols
                        else "public-name candidate; not reviewed",
                    }
                )

                if isinstance(node, ast.ClassDef):
                    for member in node.body:
                        if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            continue
                        is_constructor = member.name == "__init__"
                        is_special = member.name.startswith("__") and member.name.endswith("__")
                        if member.name.startswith("_") and not is_constructor and not is_special:
                            continue
                        method_path = qualified + "." + member.name
                        rows.append(
                            {
                                "record_type": "constructor"
                                if is_constructor
                                else "special-method"
                                if is_special
                                else "public-method",
                                "qualified_name": method_path,
                                "signature_or_value": header(member),
                                "constructor_signature": "",
                                "source": source.relative_to(source_root).as_posix(),
                                "line": str(member.lineno),
                                "documentation_evidence": "explicitly referenced in docs"
                                if method_path in doc_symbols
                                else "class source only; method not matched in docs scan",
                                "audit_status": "documented method; review defaults and behavior"
                                if method_path in doc_symbols
                                else "method candidate; not reviewed",
                            }
                        )

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if not isinstance(target, ast.Name) or target.id.startswith("_"):
                        continue
                    qualified = module + "." + target.id
                    rows.append(
                        {
                            "record_type": "assignment",
                            "qualified_name": qualified,
                            "signature_or_value": expression(source_text, node.value),
                            "constructor_signature": "",
                            "source": source.relative_to(source_root).as_posix(),
                            "line": str(node.lineno),
                            "documentation_evidence": "explicitly referenced in docs"
                            if qualified in doc_symbols
                            else "module source only; name not matched in docs scan",
                            "audit_status": "documented value; review aliases and behavior"
                            if qualified in doc_symbols
                            else "public-name candidate; not reviewed",
                        }
                    )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id.startswith("_"):
                    continue
                qualified = module + "." + node.target.id
                rows.append(
                    {
                        "record_type": "annotated-assignment",
                        "qualified_name": qualified,
                        "signature_or_value": expression(source_text, node.value),
                        "constructor_signature": "",
                        "source": source.relative_to(source_root).as_posix(),
                        "line": str(node.lineno),
                        "documentation_evidence": "explicitly referenced in docs"
                        if qualified in doc_symbols
                        else "module source only; name not matched in docs scan",
                        "audit_status": "documented value; review aliases and behavior"
                        if qualified in doc_symbols
                        else "public-name candidate; not reviewed",
                    }
                )

        # Keep locally imported Starlette names visible as alias candidates.
        # This is not a claim that they are intentional public re-exports.
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_module = node.module or ""
            if node.level:
                module_parts = module.split(".")
                package_parts = module_parts if source.name == "__init__.py" else module_parts[:-1]
                keep = max(0, len(package_parts) - node.level + 1)
                imported_module = ".".join(
                    package_parts[:keep] + ([imported_module] if imported_module else [])
                )
                if not imported_module.startswith("starlette"):
                    imported_module = "starlette" + (
                        "." + imported_module if imported_module else ""
                    )
            elif not imported_module.startswith("starlette"):
                continue
            for alias in node.names:
                if alias.name == "*" or alias.name.startswith("_"):
                    continue
                local_name = alias.asname or alias.name
                rows.append(
                    {
                        "record_type": "source-reexport-candidate",
                        "qualified_name": module + "." + local_name,
                        "signature_or_value": "from " + imported_module + " import " + alias.name,
                        "constructor_signature": "",
                        "source": source.relative_to(source_root).as_posix(),
                        "line": str(node.lineno),
                        "documentation_evidence": "source import only",
                        "audit_status": "candidate only; importability is not public-status evidence",
                    }
                )

    rows.sort(key=lambda row: (row["qualified_name"], row["record_type"], row["source"]))

    # Record the pinned root-package assignment after the sorted leaf-module
    # catalog so adding this explicit export does not renumber existing rows.
    root_init = package_root / "__init__.py"
    root_text = root_init.read_text(encoding="utf-8")
    root_tree = ast.parse(root_text, filename=str(root_init))
    for node in root_tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or (
                target.id.startswith("_") and target.id != "__version__"
            ):
                continue
            rows.append(
                {
                    "record_type": "assignment",
                    "qualified_name": package_name + "." + target.id,
                    "signature_or_value": expression(root_text, node.value),
                    "constructor_signature": "",
                    "source": root_init.relative_to(source_root).as_posix(),
                    "line": str(node.lineno),
                    "documentation_evidence": "explicit root package assignment",
                    "audit_status": "root export candidate; review public-status evidence",
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=pathlib.Path, required=True)
    parser.add_argument(
        "--output", type=pathlib.Path, default=REPOSITORY_ROOT / "docs/api-surface.csv"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the checked-in catalog is stale"
    )
    parser.add_argument("--metadata", type=pathlib.Path, default=REPOSITORY_ROOT / "metadata.yaml")
    args = parser.parse_args()

    source_root = args.upstream.resolve()
    metadata = load_api_metadata(REPOSITORY_ROOT, args.metadata.resolve())
    authority = metadata["authority"]
    inventory = metadata["api_inventory"]
    commit = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != authority["revision"]:
        raise SystemExit(f"expected Starlette commit {authority['revision']}, got {commit}")
    package_path = authority["package_path"]
    package_name = package_path.replace("/", ".")
    version = (source_root / package_path / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{authority["version"]}"' not in version:
        raise SystemExit(f"pinned source does not declare Starlette {authority['version']}")

    docs_root = (source_root / inventory["documentation_root"]).resolve()
    test_root = (source_root / inventory["test_source_root"]).resolve()
    for label, path in (("documentation", docs_root), ("test", test_root)):
        if source_root not in path.parents or not path.is_dir():
            raise SystemExit(f"metadata.yaml {label} source root is missing: {path}")
    rows = make_rows(
        source_root,
        docs_root,
        inventory["public_source_files"],
        package_path,
        package_name,
    )
    output = args.output.resolve()
    fieldnames = [
        "record_type",
        "qualified_name",
        "signature_or_value",
        "constructor_signature",
        "source",
        "line",
        "documentation_evidence",
        "audit_status",
    ]
    rendered = io.StringIO(newline="")
    writer = csv.DictWriter(rendered, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    catalog = rendered.getvalue()
    if args.check:
        if not output.is_file():
            raise SystemExit(f"API candidate catalog is missing: {output}")
        if output.read_text(encoding="utf-8") != catalog:
            raise SystemExit(
                f"API candidate catalog is stale: {output}; regenerate it from metadata.yaml"
            )
        print(f"API candidate catalog check passed: {len(rows)} rows match {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        file.write(catalog)
    print(f"wrote {len(rows)} candidate/documentation rows to {output}")
    print("review the audit_status column; rows are not automatic public API claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
