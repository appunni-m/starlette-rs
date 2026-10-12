"""Input-backed Python PathLike values used by consumer parity adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class InputSequencePathLike:
    """Return successive input-defined workspace-relative paths from ``__fspath__``."""

    def __init__(self, workspace: Path, results: list[str]) -> None:
        self._workspace = workspace
        self._results = results
        self.results: list[str] = []

    def __fspath__(self) -> str:
        index = len(self.results)
        result = self._results[min(index, len(self._results) - 1)]
        self.results.append(result)
        return str(self._workspace / result)

    def observation(self) -> dict[str, Any]:
        return {"results_relative_to_workspace": list(self.results)}
