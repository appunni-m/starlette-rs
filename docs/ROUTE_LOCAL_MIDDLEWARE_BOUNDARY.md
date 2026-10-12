# Route-local middleware boundary

The pinned contract is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. Its route-local stack construction
lives in `starlette/routing.py` (at the pinned revision):

- `Route.__init__` (lines 227–231), `WebSocketRoute.__init__` (321–324), and
  `Mount.__init__` (382–386) apply a stack whenever `middleware is not None`.
- `Router.__init__` (609–614) applies its stack only when `middleware` is
  truthy.
- Each constructor walks the sequence in reverse and calls each configured
  middleware class with the current ASGI app, its positional arguments, and its
  keyword arguments. The first configured layer is therefore outermost.
- Route and mount body-limit middleware is wrapped after configured middleware,
  so it is outermost when both are present.

`starlette-rs-py/src/router_runtime/route_types_runtime.rs` owns the branch,
ordering, iteration, argument unpacking, constructor dispatch, body-limit
placement, and propagation of constructor errors. Router uses a separate
truthiness gate to preserve its source-specific behavior; the other constructors
retain the `is not None` rule.

The configured middleware class and ASGI app remain arbitrary Python objects.
Their constructors run synchronously as user Python code and may use Python
descriptors or raise user-defined exceptions. Each resulting ASGI callable may
be a coroutine function or a callable object and returns an awaitable that runs
on the owning Python event loop. Python invokes the callable and awaits that
result. Rust selects the stack behavior and forwards the original Python
callable, awaitable, and exception across that boundary; the runtime facade
does not implement the stack algorithm.

Input-only parity cases belong in
`tests/fixtures/sources/parity/route-local-middleware-semantics.yaml`. The
falsey, nonempty Router sequence case additionally requires the public-consumer
adapters to materialize an input-defined sequence with `__bool__() == False`;
this is an adapter input conversion, not runtime Starlette behavior.
