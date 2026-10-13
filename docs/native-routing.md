# Rust-native reverse routing

The Rust crate provides reverse URL construction independently from the
`starlette.*` compatibility facade. `NamedRoute` formats one named HTTP or
WebSocket route; `NamedRouteTable` searches a flat list; `NamedRouter` composes
ordered routes, nested `NamedMount` values, and nested `NamedHost` values.

The route and Mount lookup order follows the pinned Starlette 1.6.0 behavior at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`: `Router.url_path_for` tries each
route in order and skips a `NoMatchFound` result
([`routing.py:631-637`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/routing.py#L631-L637));
`Mount.url_path_for` prefixes nested names, formats its own path parameters,
and combines the Mount prefix with the child path
([`routing.py:427-450`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/routing.py#L427-L450)).
`Host.url_path_for` applies the same name prefix to children and adds the
formatted host metadata
([`routing.py:493-524`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/routing.py#L493-L524)).

## Build and query a nested router

```rust
use starlette_rs::{NamedMount, NamedRouter};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut users = NamedRouter::new();
    users.add_route("/users/{user_id:int}", "user")?;

    let api = NamedMount::new("/v1/{tenant:str}", Some(String::from("api")), users)?;
    let mut app = NamedRouter::new();
    app.add_mount(api);

    let url = app.url_path_for(
        "api:user",
        &[
            (String::from("tenant"), String::from("acme")),
            (String::from("user_id"), String::from("42")),
        ],
    )?;
    println!("{} {}", url.protocol(), url.path());
    Ok(())
}
```

This prints `http /v1/acme/users/42`.

Each parameter value is supplied as text already formatted by its built-in
converter. Values are not percent-encoded. Mount path parameters are consumed
at their own level; remaining parameters are passed to the nested router.
An unnamed Mount forwards nested route names unchanged. A named Mount adds
`<mount-name>:` to nested route names. A Mount's own name addresses the mounted
path through a `path` parameter. For nested results, Mount preserves the child
protocol and drops child Host metadata, matching Starlette's `URLPath`
reconstruction.

## Register a Rust-native path converter

`CustomPathConverterRegistry` accepts Rust implementations of
`CustomPathConverter`. Implement `matches` for a complete capture,
`convert` for the value exposed by route matching, and `to_string` for reverse
URL formatting. Register a converter before adding routes that use its name;
each route retains the converter instance used when its pattern was parsed.
`RouteTable` and `NamedRouter` support registration directly, while
`NamedRoute` accepts a registry at construction. This Rust-native contract is
string-based and never invokes Python converter callbacks.

## Add a Host and a WebSocket route

`NamedHost` applies the same name-prefix and insertion-order rules, and returns
its formatted host in `RouteUrlPath.host`:

```rust
use starlette_rs::{NamedHost, NamedRouter};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut websocket_routes = NamedRouter::new();
    websocket_routes.add_websocket_route("/ws/{room:str}", "room")?;
    let host = NamedHost::new(
        "{tenant}.example.test",
        Some(String::from("tenant-site")),
        websocket_routes,
    )?;
    let mut app = NamedRouter::new();
    app.add_host(host);
    let url = app.url_path_for(
        "tenant-site:room",
        &[
            (String::from("tenant"), String::from("acme")),
            (String::from("room"), String::from("blue")),
        ],
    )?;
    println!("{} {} {}", url.protocol(), url.host(), url.path());
    Ok(())
}
```

This prints `websocket acme.example.test /ws/blue`.

Each parameter value is supplied as text already formatted by its built-in
converter. Values are not percent-encoded. Mount path parameters are consumed
at their own level; remaining parameters are passed to the nested router. An
unnamed Mount or Host forwards child names unchanged. A named Mount or Host
adds `<name>:` to nested route names. A Mount's own name addresses the mounted
path through a `path` parameter; a Host's own name returns its formatted host
and the supplied `path` unchanged. When a Mount wraps a Host, it preserves the
child protocol and drops the child's Host metadata; when a Host wraps a Mount,
the Host supplies the result's host metadata.

The current Rust-native graph includes named HTTP and WebSocket routes,
nested Mounts, nested Host routes, and custom Rust converters. It does not
represent arbitrary Python endpoint callables or Python converter objects.
Native lookup errors are typed Rust values; Python exception identity and
messages remain part of the compatibility boundary rather than this API.
