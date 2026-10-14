# WebSocketEndpoint message type lookup order

Pinned Starlette 1.6.0 at `../starlette` dispatches each received message with
two mapping subscriptions: it checks `message["type"]` for
`websocket.receive`, then, if that comparison is false, checks
`message["type"]` again for `websocket.disconnect` (`starlette/endpoints.py`,
lines 78-84). `WebSocket.receive()` also reads the message type while
validating a connected message (`starlette/websockets.py`, lines 46-55).

The Rust dispatch keeps those reads separate in
[`endpoint_runtime.rs`](../starlette-rs-py/src/endpoint_runtime.rs). This
preserves mappings whose `__getitem__("type")` has observable state or raises
on a particular read, including the exception timing between the two branch
checks.

The input in
[`websocket-endpoint-type-lookup-tape.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-type-lookup-tape.yaml)
supplies a three-value lookup tape for one incoming message. The fixture
adapters materialize it as a `dict` subclass and remove the tape metadata from
the ASGI message. The first value is consumed by `WebSocket.receive()`; the
following values drive the separate dispatch comparisons. This keeps the
stimulus input-defined and exercises the ordinary public dispatch path.
