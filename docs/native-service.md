# Rust-native HTTP service API

`starlette-rs` exposes an additive, server-neutral HTTP service surface through
`NativeApplication`, `NativeRoute`, and `NativeRequest`. This path accepts Rust
`http::Request` values and does not invoke Python or ASGI dictionaries. The
existing Python-compatible Starlette/ASGI path remains a separate API.

## Contract

The workspace resolves these compatible HTTP/Tower crates:

| Crate | Cargo requirement | Locked version | Role |
| --- | --- | --- | --- |
| `http` | `1` | `1.5.0` | Request/response heads, headers, URI, extensions |
| `bytes` | `1` | `1.12.1` | Owned body data frames |
| `http-body` | `1` | `1.1.0` | Incremental data and trailer frames |
| `http-body-util` | `0.1` | `0.1.5` | Internal body adapters and public boxed body aliases |
| `tower-service` | `0.3` | `0.3.3` | Readiness and request dispatch |
| `tower-layer` | `0.3` | `0.3.3` | Middleware wrapping |

The Starlette-RS workspace, including the example executable, passes a locked
all-target check on Rust 1.85. Exact resolved versions are recorded in the
workspace lockfile.

`NativeApplication` implements `tower_service::Service<Request<B>>` for any
`B: http_body::Body<Data = bytes::Bytes> + Send + 'static`. It calls
`poll_ready` as immediately ready and uses `call` to route a request. The
application is cloneable; routes and endpoint closures are shared between
clones. A `NativeRoute` endpoint receives a `NativeRequest` and asynchronously
returns `http::Response<NativeResponseBody>` or a typed
`NativeApplicationError`.

`NativeRequest` retains the `http::request::Parts`, request body, route
parameters, and extensions. Its URI path preserves percent escapes; query
returns the value without `?`. `HeaderMap` retains repeated values. The body is
exposed as `NativeRequestBody` and can be polled frame-by-frame; consumers can
explicitly collect it if their handler requires buffering. Dropping the body
releases its transport body, but this API does not yet expose an explicit
request cancellation token or typed peer/TLS metadata.

Response bodies are `http_body::Body` values erased to
`UnsyncBoxBody<Bytes, NativeBodyError>` at the heterogeneous route endpoint
boundary. `box_native_body` forwards frames and maps the body error without
collecting or copying data-frame payloads. `native_body` creates a single-frame
body. Tower middleware can wrap the application with `NativeApplication::layer`;
outer layers receive requests first and responses last. Middleware ordering is
the standard Tower layer order, not a claim that every Python Starlette
middleware feature is implemented in this native API.

The endpoint/service error and response-body error remain distinct. A service
error occurs before the server commits the response and is handled by the
server's documented error policy. A body error after commitment terminates the
response stream; it cannot start a second response. The framework service
preserves the body error as the body's error value, but server diagnostics and
typed transport context are still being developed.

## Copies and limits

Native route handlers can pass owned `Bytes` into responses without copying
payloads. Boxing a body preserves each `Frame<Bytes>` and does not collect it.
The compatibility fallback converts the existing buffered `Response` body
from `Vec<u8>` into `Bytes`, which copies the fallback payload. The API does
not claim that URI/header parsing, TLS, compression, or downstream transport
serialization are zero-copy.

This is an initial HTTP service surface. It does not implement the Python
Starlette application model, route-level dependency injection, Starlette
middleware semantics as a full catalog, WebSockets, lifespan hooks, mounts,
server protocol negotiation, or a cross-repository FastAPI composition. The
request body is represented as a stream, but transport backpressure and
disconnect cancellation must be verified with the server integration before
the API claims those behaviors end-to-end.

## Executable example

Run the service example from the repository root:

```sh
cargo run -p starlette-rs-native-service-example --locked
```

It consumes a POST body, routes an integer path parameter, reads the query and
a middleware-inserted request header, and prints response frames as they arrive.
The example shows the public service and body APIs; it does not measure
transport backpressure, disconnect behavior, Python parity, or performance.
