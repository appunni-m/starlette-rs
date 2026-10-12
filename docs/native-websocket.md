# Rust-native WebSocket routes

`starlette-rs` provides a Rust-native WebSocket API through
`NativeWebSocketRouter`, `NativeWebSocketRoute`, and
`NativeWebSocketSession`. This API is a greenfield Rust surface, separate from
the pinned Starlette 1.6.0 `starlette.websockets` and ASGI compatibility
surface.

The host parses each incoming handshake into `NativeWebSocketHandshake` and
implements `NativeWebSocketDriver`. The application receives request method,
URI, HTTP version, headers, extensions, ordered subprotocol offers, and route
parameters. It may accept with response headers and an offered subprotocol,
exchange text or binary messages, and close with an application code and
reason. A peer close is delivered as a distinct event with its optional code
and reason.

The router matches paths in registration order using the shared Starlette
path-converter syntax. It deliberately does not choose an HTTP handshake
method: the host owns HTTP/1.1 upgrade and HTTP/2 extended CONNECT negotiation.
If no route matches, dispatch returns `NoRoute` before the host commits a
handshake response.

## Host boundary

The adapter's `accept`, `receive`, `send`, and `close` methods pass semantic
values, not ASGI dictionaries or WebSocket wire frames. The host owns request
header parsing, protocol negotiation, frame parsing and encoding, ping/pong,
message-size limits, transport writes, and the pre-upgrade response for a
route miss. It should make each operation future safe to cancel when dropped.

`NativeWebSocketDriver::cancelled` resolves when the host cancels the
application session. The session races each pending host operation against
that signal and returns `NativeWebSocketError::Cancelled`; dropping the route
dispatch future drops the handler future as normal Rust cancellation. The
cancellation signal must be sticky and repeatable: once requested, every
subsequently created cancellation future must resolve. If cancellation and a
host operation are both ready when polled, cancellation takes precedence. A
cancelled or transport-failed session enters `Failed` and should be discarded
by the host. Cancellation is cooperative while the handler is in a session
operation; the host drops the dispatch future to stop a handler awaiting some
other future. This crate does not create or select an async runtime.

The route handler owns a single session, so calls are sequential at the API
boundary. The host serializes any wire operations according to its transport
contract. An application error is returned as
`NativeWebSocketError::Application` and remains distinct from host transport
errors, invalid session-state operations, and cancellation.

When a handler returns, dispatch reports completion to the host without
synthesizing a close frame. The host applies its documented cleanup or
application-error policy for sessions the handler left open.

## Subprotocols and close codes

Each route stores its server preferences in declaration order.
`accept_preferred` selects the first server preference also present in the
client offer list. When the lists do not overlap, it accepts without selecting
a subprotocol. `accept` can instead provide an explicit selection, which must
be among the client's offers. Matching is case-sensitive.

Application close requests accept codes 1000–1014 except the reserved 1004,
1005, and 1006, or application/private codes 3000–4999. The host remains
responsible for encoding the close frame and enforcing its frame-size limits.
Peer close metadata is passed through from the host without reinterpretation.

## Example

```rust,no_run
use std::sync::Arc;

use http::HeaderMap;
use starlette_rs::{
    NativeWebSocketClose, NativeWebSocketDriver, NativeWebSocketError,
    NativeWebSocketEvent, NativeWebSocketRouter, NativeWebSocketRoute,
    NativeWebSocketRouterError,
};

fn chat_route() -> NativeWebSocketRoute {
    NativeWebSocketRoute::new(
        "/rooms/{room_id:int}",
        ["json.v2", "chat.v1"],
        |mut session| async move {
            session.accept_preferred(HeaderMap::new()).await?;
            match session.receive().await? {
                NativeWebSocketEvent::Message(message) => session.send(message).await?,
                NativeWebSocketEvent::PeerClosed(_) => return Ok(()),
            }
            session
                .close(NativeWebSocketClose::normal("finished"))
                .await?;
            Ok::<(), NativeWebSocketError>(())
        },
    )
}

fn router() -> Result<NativeWebSocketRouter, NativeWebSocketRouterError> {
    NativeWebSocketRouter::new([chat_route()])
}

fn host_adapter_example(
    _driver: Arc<dyn NativeWebSocketDriver>,
) -> Result<(), NativeWebSocketRouterError> {
    let _application_router = router()?;
    Ok(())
}
```

The route API is an independent building block for the server's native
application path. The host calls `dispatch` with its parsed handshake and
driver. Rust-native WebSocket routes do not change the Python compatibility
facade, and the Python package continues to handle ordinary Starlette ASGI
servers through its separate adapter.
