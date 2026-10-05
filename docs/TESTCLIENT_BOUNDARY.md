# TestClient runtime boundary

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The repository implements
bounded HTTP request/response, lifespan, and WebSocket-session slices of the documented
`starlette.testclient.TestClient` surface. Its pinned implementation is
`starlette/testclient.py` and its public guide is `docs/testclient.md`.

The active slice compares ASGI2 and ASGI3 calls, HTTP scope projection,
request-body delivery and lazy body-read timing, response headers/body, debug
response extensions, the warning emitted when a request supplies a timeout,
and application exception policy. Exception inputs compare default
propagation, the synthesized 500 response when no response has started,
preservation of a completed response when the app raises afterward, and
preservation of the raised exception identity with explicit cause, implicit
context, and suppressed context. They record warning category, message,
filename, and line from the input-driven source and package runs. The timeout
is forwarded to HTTPX; this comparison does not claim that the ASGI transport
enforces a timeout. WebSocket inputs compare scope projection, text and binary
exchange, JSON text and UTF-8 binary frames, streamed denial responses, app
progress during a blocked receive, disconnect details, close-triggered
cancellation, completion, and portal cleanup. The separate lifespan input
compares startup and shutdown context management.
WebSocket close-message errors, explicit close reasons, the source's
GeneratorType receive branch, and other unmapped TestClient error cases remain
in the compatibility backlog. The public HTTPX2 generator-content path is
covered separately: `Request.read()` aggregates its chunks, and the ASGI
transport must not consume that generator before the app calls `receive`.

## Source-backed Python boundary

The source client subclasses its selected HTTPX implementation, uses that
client for request building, cookies, redirects, and public response objects,
and installs a synchronous transport (`testclient.py:207-367`). The transport
invokes arbitrary user ASGI callables through AnyIO's blocking portal
(`testclient.py:348-355`). HTTPX owns its documented client and response types,
and Python's selected AnyIO backend owns the event loop that executes the
user's Python callables.

The implementation boundary is:

- Python preserves the documented `TestClient` inheritance and `request`
  signature, converts HTTPX objects at the PyO3 boundary, and exposes the
  HTTPX `BaseTransport` protocol as a call-through wrapper. Its WebSocket
  session class forwards context entry/exit, accepted-subprotocol access,
  text/byte/JSON send and receive, and close calls to the native session object.
- Python supplies small ASGI2/ASGI3 call-and-await functions. Rust selects the
  callable shape, starts AnyIO's blocking portal for the selected backend, and
  drives the ASGI call on that portal without creating another executor or
  event loop.
- Rust owns request-to-scope projection, receive and send state, lazy request
  body reads, response completion, debug extensions, default headers, URL
  merging, app state, and construction of the HTTPX response through its public
  types. Rust calls the
  supplied ASGI callable through the existing PyO3 awaitable boundary.
- Rust owns WebSocket URL-to-scope projection, handshake and accepted
  subprotocol state, the client/app message streams, text/byte/JSON frame
  operations, and context-exit disconnect and task cleanup. Rust invokes
  Python's standard JSON encoder and decoder through PyO3 with the pinned
  compact/non-ASCII options and forwards their exceptions unchanged. Binary
  JSON mode uses Python string UTF-8 encoding at the same boundary. Keeping the
  standard-library calls at this boundary is necessary to preserve Python's
  JSON value conversion, serialized text, and decoder behavior; a Rust JSON
  crate would not provide the same Python semantics. The text and binary
  exchange inputs compare the emitted frames and decoded values against the
  pinned source. HTTPX constructs the request and continues to own its URL and
  request-header types.
- HTTPX continues to own its client semantics, cookies, redirects, URL types,
  and response types. The selected implementation and its optional dependency
  requirements match the pinned Starlette source lock in parity runs.

The Python code added for this feature remains a forwarding/API wrapper: no
Python branch, loop, `raise`, or `assert` implements TestClient policy. Any
additional Python-only behavior must have a pinned-source rationale here and
an input-only oracle comparison before it is accepted.

## Template objects across the portal boundary

The pinned `tests/test_templates.py` constructs `Jinja2Templates` on the
client's calling thread and closes over that object in an async route. The
route renders on TestClient's AnyIO portal thread. The template service and
its `url_for` global must support that public usage without thread affinity.

The Rust service contains owned `Py<PyAny>` references to the environment and
processors; its URL global is stateless. Both use PyO3's ordinary thread-safe
class storage, Python attachment for object access, and checked borrows. No
unsafe thread-trait implementation or Python scheduling policy is added.
Jinja remains the optional Python template engine, and user processors remain
Python callables. Rust owns Starlette's constructor decisions, environment
selection, processor merge, route URL lookup, and debug-event policy.

The input-only
[`templating-public.yaml`](../tests/fixtures/sources/parity/templating-public.yaml)
exercises main-thread construction followed by portal-thread rendering,
including a supplied environment, context processors, directory sequences,
and pass-through BaseHTTPMiddleware. Its consumers inspect TestClient's
public template/context attributes and ordered response events. The separate
direct-render cases check constructor errors and autoescape without a portal.
These inputs exposed the earlier `unsendable` class annotations as a PyO3
panic on valid public usage. This boundary does not establish free-threaded
CPython or simultaneous template mutation behavior.

## Public WebSocket denial and concurrency workflows

[`testclient-websocket-public.yaml`](../tests/fixtures/sources/parity/testclient-websocket-public.yaml)
compares four public workflows on asyncio and Trio. Default connections pass
`subprotocols=None`; an empty sequence would add a protocol header. Headers
and optional compression-module presence are observed from the live client.

The concurrency app creates its AnyIO memory stream on the caller thread,
then runs a JSON reader and writer on TestClient's selected portal backend.
The input supplies a disconnect and drains the application close frame before
context exit. This preserves deterministic frame and cleanup observations.
AnyIO owns the user's task group and Python event loop; Rust owns WebSocket
receive/send state and TestClient session cleanup.

The denial inputs remove the live server extension or send two response starts
through `WebSocket.send`. Both errors are reachable from public inputs and are
compared against the oracle, including partial event tapes and propagated
exceptions. They require no runtime fault hook and no Python facade behavior.
The separate target-only route-cache poison contracts exercise internal Rust
failures through public 500-response and exception outcomes.

## Evidence and remaining work

Each slice is authored as input-only YAML under `tests/fixtures/sources/` and
is run against the pinned source and installed package in isolated processes.
Stimuli come from the input definition; adapters may not use case IDs to
choose requests, scopes, responses, or outcomes. The HTTP request/response,
lifespan, and WebSocket fixtures compare ordered callbacks and public results
against the pinned source. The HTTP fixture includes public generator-backed
request content and records whether those chunks are consumed when the ASGI app
does not call `receive`. Other unmapped TestClient and WebSocket behavior still
needs separate input definitions.

The pinned source provides additional mappings in `tests/test_testclient.py`
and `docs/testclient.md`; those source rows remain visible in the fixture
backlog until their input-driven comparisons exist. A passing transport slice
does not establish full TestClient or Starlette parity.
