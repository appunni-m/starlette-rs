"""Check local Markdown links in the maintained contributor documentation."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").rglob("*.md")))
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+).*?\1")
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(\s*(?:<([^>]+)>|([^\s)]+))")


def markdown_without_code(text: str) -> str:
    """Mask fenced and inline code so examples are not interpreted as links."""
    kept_lines: list[str] = []
    fence_char: str | None = None
    fence_size = 0

    for line in text.splitlines(keepends=True):
        marker = FENCE.match(line)
        if fence_char is None and marker:
            fence_char, fence_size = marker.group(1)[0], len(marker.group(1))
            kept_lines.append("\n" if line.endswith("\n") else "")
            continue
        if fence_char is not None:
            if marker and marker.group(1)[0] == fence_char and len(marker.group(1)) >= fence_size:
                fence_char = None
                fence_size = 0
            kept_lines.append("\n" if line.endswith("\n") else "")
            continue

        kept_lines.append(INLINE_CODE.sub(lambda match: " " * len(match.group(0)), line))

    return "".join(kept_lines)


def broken_local_links(document: Path) -> list[str]:
    """Return line-specific errors for links whose local target is missing."""
    text = document.read_text(encoding="utf-8")
    markdown = markdown_without_code(text)
    errors: list[str] = []

    for match in LINK.finditer(markdown):
        target = match.group(1) or match.group(2)
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue

        path = (document.parent / unquote(parsed.path)).resolve()
        relative_document = document.relative_to(ROOT)
        try:
            path.relative_to(ROOT)
        except ValueError:
            line = markdown.count("\n", 0, match.start()) + 1
            errors.append(
                f"{relative_document}:{line}: local link escapes the repository: {parsed.path!r}"
            )
            continue

        if not path.exists():
            line = markdown.count("\n", 0, match.start()) + 1
            errors.append(f"{relative_document}:{line}: missing local link target {parsed.path!r}")

    return errors


def main() -> int:
    missing = [path for path in DOCUMENTS if not path.is_file()]
    if missing:
        for path in missing:
            print(f"missing maintained document: {path.relative_to(ROOT)}", file=sys.stderr)
        return 1

    errors = [error for document in DOCUMENTS for error in broken_local_links(document)]
    if errors:
        print("Documentation link check failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(f"Documentation link check passed ({len(DOCUMENTS)} Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
