# Starlette-RS

Starlette-RS is being developed as a Rust-native web toolkit with a Python
compatibility package for Starlette applications. The compatibility target is
the full documented Starlette 1.6.0 surface and its observable ASGI behavior.

The repository includes a Rust core crate and an installable PyO3 Python
package. The runtime architecture keeps the Python `starlette` package as a
thin compatibility facade: it has no dependency on the upstream Starlette
distribution, and Python wrappers forward behavior to Rust without branches or
loops. Rust owns runtime behavior and control flow; Python remains at the
callback, awaitable, and Python-object boundaries. AnyIO is the only declared
runtime package dependency.

Compatibility work is tracked as input-only live parity slices against the
pinned upstream source. The current implemented surface and outstanding gaps
are recorded in the [compatibility inventory](docs/COMPATIBILITY_INVENTORY.md);
full Starlette parity is not yet claimed.

See:

- [Pinned sources and discrepancies](docs/UPSTREAM.md)
- [Compatibility inventory](docs/COMPATIBILITY_INVENTORY.md)
- [Dependency inventory](docs/DEPENDENCIES.md)
- [Parity contract](docs/PARITY.md)
- [Benchmark mapping](docs/BENCHMARKS.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Contributing and quality gates](CONTRIBUTING.md)
