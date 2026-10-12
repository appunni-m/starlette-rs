"""Normalize generated text whitespace without changing its wording."""

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: normalize_line_endings.py PATH", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    content = path.read_bytes()
    normalized = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    normalized = b"\n".join(line.rstrip(b" \t") for line in normalized.split(b"\n"))
    path.write_bytes(normalized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
