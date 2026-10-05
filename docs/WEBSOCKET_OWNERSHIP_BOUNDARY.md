# WebSocket value and continuation ownership

Authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`,
`starlette/websockets.py:25-201` and `docs/websockets.md`.

The Rust WebSocket protocol stores client/application state in a synchronized
Rust value and iterator flags in atomic Rust values. Python references are owned
PyO3 handles. Protocol objects, iterators, close applications and continuations
can move between Python threads without unsafe thread-trait implementations.
The compiler enforces Send/Sync. State guards are released before user callbacks;
Python futures remain on the event loop that drives the call.

Protocol objects and continuations expose directly owned Python references to
cyclic GC. Non-iteration callbacks preserve their original StopAsyncIteration.
Iterator callbacks retain the original error in Python's generator-error
cause/context instead of replacing it with an empty exception.

Thirty `websocket-thread-ownership.yaml` definitions select worker construction
of public WebSocket objects and, for iterator workflows, worker construction of
the iterator. The caller then drives public typed receives, sends, iteration,
iterator controls, close/error flows and denial responses on its event loop.
These independently execute against live source/package consumers; inputs have
no expected output and dispatch does not depend on case IDs.

The definitions are statically validated and unexecuted. Active iterator
finalization, complete exception traceback lifetime,
custom callback descriptors and cancellation across Python versions remain
implementation review. This checkpoint makes no new parity or coverage claim.

## Shared ASGI continuation implementation

All ASGI families now use the Send/Sync native continuation driver, including
endpoints, routing/lifespan, authentication, sessions, static files, WSGI, GZip,
body limits and BaseHTTPMiddleware. Shared Python references live in GC-visible
PyO3 holders; Rust-only iterator/response flags use atomics. No unsafe thread
trait implementation is used, and Python callbacks remain on the driving event
loop or the source-selected AnyIO worker.

Endpoint dispatch retains request, handler and response values through the
response call, reads live method values in source order, and preserves original
callback StopAsyncIteration. WebSocket decode/disconnect failures retain original
exception contexts. Two input-defined HTTP scope mappings observe repeated
GET/HEAD method reads through the public endpoint ASGI interface. The integrated
run must validate these changes; compiler thread traits alone are not parity
evidence.
