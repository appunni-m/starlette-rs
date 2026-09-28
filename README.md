# Starlette-RS

Starlette-RS is being developed as a Rust-native web toolkit with a Python
compatibility package for Starlette applications. The compatibility target is
the full documented Starlette 1.6.0 surface and its observable ASGI behavior.

The repository now includes a Rust core crate and an installable PyO3 Python
package. Implemented compatibility slices cover direct async GET `/hello` ASGI
dispatch and lifespan, Request properties and typed path parameters, Router
converters and Mount dispatch, and reverse URL generation through the Python
package. The Rust route table provides the built-in path-formatting primitive;
native named-route URL lookup remains open. These slices have an installed-wheel
parity path. Full Starlette parity is not yet claimed.

See:

- [Pinned sources and discrepancies](docs/UPSTREAM.md)
- [Compatibility inventory](docs/COMPATIBILITY_INVENTORY.md)
- [Dependency inventory](docs/DEPENDENCIES.md)
- [Parity contract](docs/PARITY.md)
- [Benchmark mapping](docs/BENCHMARKS.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Contributing and quality gates](CONTRIBUTING.md)
