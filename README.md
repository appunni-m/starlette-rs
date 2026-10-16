# Starlette-RS

Starlette-RS is being developed as a Rust-native web toolkit with a Python
compatibility package for Starlette applications. The compatibility target is
the full documented Starlette 1.6.0 surface and its observable ASGI behavior.

The repository includes a Rust core crate and an installable PyO3 Python
package. The runtime architecture keeps the Python `starlette` package as a
thin compatibility facade: it has no dependency on the upstream Starlette
distribution, and Python wrappers forward behavior to Rust without branches or
loops. Rust owns runtime behavior and control flow; Python remains at the
callback, awaitable, and Python-object boundaries. AnyIO and typing-extensions
are the declared runtime package dependencies.

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

## Rust-native HTTP service

The Rust-native [`NativeApplication`](docs/native-service.md) implements Tower
`Service` over `http::Request` and streaming `http_body::Body` values. Rust
endpoints can read route parameters, URI/query, headers, extensions, and request
body frames, then return a streamed response. The API does not invoke Python.
Its current middleware, cancellation, protocol, and lifecycle limits are
documented in the service contract.

Run the in-process body and response-streaming example with:

```sh
cargo run -p starlette-rs-native-service-example --locked
```

See:

- [Pinned sources and discrepancies](docs/UPSTREAM.md)
- [Compatibility inventory](docs/COMPATIBILITY_INVENTORY.md)
- [Dependency inventory](docs/DEPENDENCIES.md)
- [Parity contract](docs/PARITY.md)
- [Benchmark mapping](docs/BENCHMARKS.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Rust-native service contract](docs/native-service.md)
- [Contributing and quality gates](CONTRIBUTING.md)
