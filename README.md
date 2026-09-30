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

## Rust-native named-route reverse lookup

`NamedRouteTable` provides insertion-ordered reverse lookup for flat, directly
named HTTP routes with Starlette's built-in converters (`str`, `int`, `float`,
`uuid`, and `path`). It selects the first route with a matching name and exact
parameter-name set. Pass parameter values already formatted as strings; the
returned path is not percent-encoded. Converter-formatting failures remain
typed Rust errors; they are not translated into Python exception objects.
Nested `Mount` or `Host` routes, custom converters, and WebSocket routes are
outside this API. Full Starlette parity remains in progress.

```rust
use starlette_rs::NamedRouteTable;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut routes = NamedRouteTable::new();
    routes.add_route("/users/{user_id:int}", "user")?;
    routes.add_route("/profiles/{user_id:int}", "user")?;

    let url = routes.url_path_for("user", &[("user_id".into(), "42".into())])?;
    println!("{} {}", url.protocol, url.path);
    Ok(())
}
```

See:

- [Pinned sources and discrepancies](docs/UPSTREAM.md)
- [Compatibility inventory](docs/COMPATIBILITY_INVENTORY.md)
- [Dependency inventory](docs/DEPENDENCIES.md)
- [Parity contract](docs/PARITY.md)
- [Benchmark mapping](docs/BENCHMARKS.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Contributing and quality gates](CONTRIBUTING.md)
