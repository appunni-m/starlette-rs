# Rust-native HTTP service API

The crate exposes a server-neutral Rust HTTP API through `NativeApplication`,
`NativeRoute`, and `NativeRequest`. This path accepts Rust
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
releases its source, but this API does not expose an explicit request
cancellation token or typed peer/TLS metadata.

Response bodies are `http_body::Body` values erased to
`UnsyncBoxBody<Bytes, NativeBodyError>` at the heterogeneous route endpoint
boundary. `box_native_body` forwards frames and maps the body error without
collecting or copying data-frame payloads. `native_body` creates a single-frame
body. Tower middleware can wrap the application with `NativeApplication::layer`;
outer layers receive requests first and responses last. Middleware ordering is
the standard Tower layer order, not a claim that every Python Starlette
middleware feature is implemented in this native API.

### Pull polling and backpressure

`NativeApplication` does not poll a request body while matching a route,
constructing the `NativeRequest`, or invoking the endpoint to obtain its
future. The endpoint or an outer Tower layer is the first consumer. Each
`Body::poll_frame` request advances the supplied body according to that body's
implementation.

The service also returns a response without polling its body. The service
consumer or an outer Tower layer requests each response frame. The body box
does not read ahead, collect frames, or copy data-frame payloads. This gives
pull-based backpressure at the `http_body::Body` boundary: the service does not
advance a body until a consumer polls it. A user-supplied body can still do
work or buffer internally when it is constructed or polled, and a Tower layer
may choose to poll or buffer it.

### Errors and cancellation

`box_native_body` preserves the concrete body error as the dynamic error
carried by `NativeBodyError`, without converting it to text. A request-body
polling error is returned to the endpoint;
the endpoint decides whether to handle it or return it as
`NativeApplicationError::Endpoint`. A response-body polling error is returned
to the consumer from that frame poll. The service does not turn a response-body
error into a second response. The endpoint/service error and response-body
error therefore remain separate: the former occurs before a response is
returned, while the latter occurs as the returned response stream is consumed.
`NativeBodyError` is an erased `Error` trait object; callers can use
`downcast_ref` to recover a concrete source error such as `std::io::Error`.
For an endpoint error, the same source is available through
`std::error::Error::source` on `NativeApplicationError`.

Dropping the service future uses ordinary Rust future-drop semantics. If the
endpoint future still owns the request, dropping it drops that future and its
request body. After the response is returned, dropping its body drops the
wrapped response source. These are the cancellation and resource-release
guarantees available at this API boundary. There is no explicit cancellation
token, peer-disconnect signal, or guarantee about how a transport reacts to a
dropped body; those behaviors belong to a server adapter and its body
implementation.

## Copies and limits

Native route handlers can pass owned `Bytes` into responses without copying
payloads. Boxing a body preserves each `Frame<Bytes>` and does not collect it.
The compatibility fallback converts the existing buffered `Response` body
from `Vec<u8>` into `Bytes`, which copies the fallback payload. The API does
not claim that URI/header parsing, TLS, compression, or downstream transport
serialization are zero-copy.

This is an initial HTTP service surface. It does not implement the Python
Starlette application model, route-level dependency injection, the full
Starlette middleware catalog, mounts, server protocol negotiation, or a
cross-repository FastAPI composition. Separate transport-neutral Rust APIs
provide [WebSocket sessions](native-websocket.md) and
[lifespan hooks](native-lifespan.md); they remain distinct from Starlette's
Python and ASGI surfaces. The pulling and drop behavior above is guaranteed by
this service boundary; an end-to-end transport's buffering and disconnect
behavior still depends on its server adapter.

## Executable example

Run the service example from the repository root:

```sh
cargo run -p starlette-rs-native-service-example --locked
```

It records request-body polling while the endpoint consumes a POST body, routes
an integer path parameter, reads the query and a middleware-inserted request
header, and records response-body polling as the consumer asks for frames. The
example demonstrates the service-local pull boundary; it does not measure
transport backpressure, disconnect behavior, Python parity, or performance.
