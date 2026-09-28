"""Python import surface for the Rust-backed Starlette compatibility package.

The package implements the documented Starlette compatibility slices without
importing or falling back to the upstream distribution.
"""

from starlette.applications import Starlette

__all__ = ["Starlette"]
__version__ = "0.1.0"
