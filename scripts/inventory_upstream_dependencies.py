#!/usr/bin/env python3
"""Snapshot the pinned upstream uv.lock graph and PyPI release metadata."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import pathlib
import re
import urllib.error
import urllib.request

EXPECTED_COMMIT = "4f250d6b814587e20c5365f0a5f0c4d42bcb929f"
DIRECT = {
    "anyio": (
        "runtime-required",
        "Async task groups, cancellation, thread offload, and backend-neutral concurrency.",
    ),
    "typing-extensions": ("runtime-required", "Typing backports on Python versions below 3.13."),
    "itsdangerous": ("optional-full", "Signing and validating SessionMiddleware cookies."),
    "jinja2": ("optional-full", "Rendering Jinja2Templates."),
    "python-multipart": ("optional-full", "Parsing multipart forms and uploaded files."),
    "pyyaml": ("optional-full", "YAML schema support."),
    "httpx": ("optional-full", "Deprecated TestClient transport/backend compatibility."),
    "httpx2": ("optional-full+dev", "Preferred TestClient backend; zstd extra is enabled in dev."),
    "zstandard": ("dev-extra", "The httpx2[zstd] development/test extra."),
    "coverage": ("dev", "Coverage collection/reporting."),
    "importlib-metadata": ("dev", "Distribution metadata compatibility checks."),
    "mypy": ("dev", "Strict type checking."),
    "pytest-codspeed": ("dev-benchmark", "CodSpeed benchmark integration."),
    "ruff": ("dev", "Linting and formatting."),
    "types-pyyaml": ("dev", "PyYAML typing stubs."),
    "pytest": ("dev", "Upstream test runner."),
    "trio": ("dev", "AnyIO alternate-backend test coverage."),
    "twine": ("dev-package-check", "Inspect built Python distributions."),
    "black": ("docs", "Format Python snippets in documentation."),
    "mkdocstrings": ("docs", "Render API documentation."),
    "mkdocstrings-python": ("docs", "Python API documentation handler."),
    "zensical": ("docs", "Build the upstream documentation site."),
}


def parse_lock(path: pathlib.Path) -> dict[str, dict[str, object]]:
    packages: dict[str, dict[str, object]] = {}
    text = path.read_text(encoding="utf-8")
    for block in re.split(r"(?m)^\[\[package\]\]\s*\n", text)[1:]:
        name_match = re.search(r'(?m)^name = "([^"]+)"', block)
        version_match = re.search(r'(?m)^version = "([^"]+)"', block)
        if not name_match or not version_match:
            continue
        name = name_match.group(1).lower()
        children = sorted(set(re.findall(r'\{\s*name\s*=\s*"([^"]+)"', block)))
        packages[name] = {"version": version_match.group(1), "children": children}
    return packages


def pypi_metadata(name: str, version: str) -> dict[str, str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "starlette-rs-inventory/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return {
            "license": "UNVERIFIED: " + type(error).__name__,
            "implementation_classifiers": "",
            "wheel_summary": "metadata unavailable; inspect release artifacts",
            "metadata_source": url,
        }

    info = release.get("info", {})
    license_value = info.get("license_expression") or info.get("license")
    if not license_value:
        license_value = next(
            (
                item.rsplit(" :: ", 1)[-1]
                for item in info.get("classifiers", [])
                if item.startswith("License :: OSI Approved :: ")
            ),
            "UNSPECIFIED; inspect release license files",
        )
    license_value = " ".join(str(license_value).split())
    classifiers = [
        item.removeprefix("Programming Language :: ")
        for item in info.get("classifiers", [])
        if item.startswith("Programming Language :: ")
    ]
    files = release.get("urls", [])
    wheels = [
        item.get("filename", "") for item in files if item.get("packagetype") == "bdist_wheel"
    ]
    has_universal = any(filename.endswith("-none-any.whl") for filename in wheels)
    has_platform = any(
        filename.endswith(".whl")
        and len(filename[:-4].rsplit("-", 1)) > 1
        and filename[:-4].rsplit("-", 1)[-1] != "any"
        for filename in wheels
    )
    if has_universal and not has_platform:
        wheel_summary = "universal Python wheel(s); native implementation not inferred"
    elif has_platform:
        wheel_summary = "platform-specific wheel(s); inspect for native/runtime components"
    elif wheels:
        wheel_summary = "wheel(s) present; inspect wheel tags and contents"
    else:
        wheel_summary = "no wheel listed for this release; inspect source build requirements"
    return {
        "license": license_value,
        "implementation_classifiers": "; ".join(classifiers),
        "wheel_summary": wheel_summary,
        "metadata_source": url,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--snapshot-date", default="2026-09-27")
    args = parser.parse_args()

    upstream = args.upstream.resolve()
    import subprocess

    commit = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != EXPECTED_COMMIT:
        raise SystemExit(f"expected Starlette commit {EXPECTED_COMMIT}, got {commit}")

    packages = parse_lock(upstream / "uv.lock")
    if len(packages) != 85:
        raise SystemExit(f"expected 85 third-party locked packages, found {len(packages)}")

    parents: dict[str, list[str]] = {name: [] for name in packages}
    for parent, package in packages.items():
        for child in package["children"]:
            if child in parents:
                parents[child].append(parent)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        future_by_name = {
            name: pool.submit(pypi_metadata, name, str(package["version"]))
            for name, package in packages.items()
        }
        metadata = {name: future.result() for name, future in future_by_name.items()}

    categories: dict[str, set[str]] = {name: set() for name in packages}
    for direct_name, (group_names, _) in DIRECT.items():
        if direct_name not in packages:
            raise SystemExit(f"direct dependency missing from lock: {direct_name}")
        for category in group_names.split("+"):
            pending = [direct_name]
            while pending:
                current = pending.pop()
                if category in categories[current]:
                    continue
                categories[current].add(category)
                pending.extend(packages[current]["children"])

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "name",
        "version",
        "role",
        "why_selected_or_parent_chain",
        "locked_transitive_dependencies",
        "dependency_groups",
        "reported_license",
        "implementation_classifiers",
        "wheel_or_native_review_note",
        "metadata_source",
        "metadata_snapshot_date",
        "license_review_status",
    ]
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for name in sorted(packages):
            direct = DIRECT.get(name)
            info = metadata[name]
            writer.writerow(
                {
                    "name": name,
                    "version": packages[name]["version"],
                    "role": direct[0] if direct else "transitive-only",
                    "why_selected_or_parent_chain": direct[1]
                    if direct
                    else "Transitive dependency required by: " + ", ".join(sorted(parents[name])),
                    "locked_transitive_dependencies": ", ".join(packages[name]["children"]),
                    "dependency_groups": ", ".join(sorted(categories[name])),
                    "reported_license": info["license"],
                    "implementation_classifiers": info["implementation_classifiers"],
                    "wheel_or_native_review_note": info["wheel_summary"],
                    "metadata_source": info["metadata_source"],
                    "metadata_snapshot_date": args.snapshot_date,
                    "license_review_status": "metadata snapshot; archive/license text review pending",
                }
            )
    print(f"wrote metadata for {len(packages)} third-party locked packages to {output}")
    print("license and native-component review remains required before packaging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
