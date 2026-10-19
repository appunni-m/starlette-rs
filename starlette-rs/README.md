# starlette-rs

`starlette-rs` is the Rust library crate in the Starlette-RS project. Its
Rust-native APIs are separate from the Python `starlette.*` compatibility
package. The crate also contains shared primitives used by that compatibility
implementation. The current implementation does not claim full Starlette
compatibility.

## Install

For a crates.io install, first confirm that a release is available there; then
add the published crate with `cargo add starlette-rs`. This is a conditional
registry route and does not imply that a release is currently published.

To use the unreleased source from a local checkout, place your application next
to the cloned repository and add this path dependency to the application's
`Cargo.toml`:

```toml
[dependencies]
starlette-rs = { path = "../starlette-rs/starlette-rs" }
```

Here `../starlette-rs` is the repository checkout and its `starlette-rs`
subdirectory contains the crate. Adjust the path if your directories differ.

## Build metadata

The Cargo manifest declares Rust edition 2024 and MSRV 1.85. The default
feature set is empty. The opt-in `fault-contract` feature enables an internal
fault-injection hook used by the project's target-only parity cases; normal
library use does not need it.

The crate exposes Rust-native routing, HTTP service, WebSocket, and lifespan
APIs. For example, `NamedRouteTable` provides insertion-ordered reverse lookup
for flat, directly named HTTP routes:

```rust
use starlette_rs::NamedRouteTable;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut routes = NamedRouteTable::new();
    routes.add_route("/users/{user_id:int}", "user")?;

    let url = routes.url_path_for("user", &[("user_id".into(), "42".into())])?;
    println!("{} {}", url.protocol, url.path);
    Ok(())
}
```

Parameter values are supplied as strings and are not percent-encoded. This
API covers flat named routes; nested routing, custom converters, HTTP service,
WebSocket, and lifespan contracts are described in the project documentation.

## Start here

- [Documentation index](https://github.com/appunni-m/starlette-rs/blob/main/docs/README.md)
- [Rust-native routing](https://github.com/appunni-m/starlette-rs/blob/main/docs/native-routing.md)
- [Rust-native HTTP service](https://github.com/appunni-m/starlette-rs/blob/main/docs/native-service.md)
- [Rust-native WebSocket API](https://github.com/appunni-m/starlette-rs/blob/main/docs/native-websocket.md)
- [Rust-native lifespan API](https://github.com/appunni-m/starlette-rs/blob/main/docs/native-lifespan.md)
- [Python compatibility inventory](https://github.com/appunni-m/starlette-rs/blob/main/docs/COMPATIBILITY_INVENTORY.md)
- [Pinned upstream source and provenance](https://github.com/appunni-m/starlette-rs/blob/main/docs/UPSTREAM.md)
- [Release readiness](https://github.com/appunni-m/starlette-rs/blob/main/docs/RELEASING.md)
- [License and third-party notices](https://github.com/appunni-m/starlette-rs/blob/main/LICENSE.md)
- [Security policy](https://github.com/appunni-m/starlette-rs/blob/main/SECURITY.md)

This README documents the Rust crate only. For the separate Python
distribution, see the [Python package guide](https://github.com/appunni-m/starlette-rs/blob/main/README-PYPI.md).
