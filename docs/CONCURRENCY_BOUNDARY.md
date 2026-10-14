# Concurrency boundary note

`run_in_threadpool` must propagate a worker callback's exception unchanged,
including `StopAsyncIteration`. In the pinned Starlette 1.6.0 source,
`starlette/concurrency.py:32-34` builds a `functools.partial` and directly
returns `await anyio.to_thread.run_sync(func)`; it does not translate callback
exceptions. The public helper's worker behavior is also documented in
`starlette/docs/threadpool.md` and exercised through
`starlette.concurrency` in the compatibility inputs.

The Rust awaitable driver classifies a delegated `StopAsyncIteration` separately
so an async-iterator continuation can decide whether it represents normal
completion. `ThreadpoolCall` is awaiting a coroutine, not an async iterator, so
it forwards that original exception object. The input-only comparison is
[`concurrency-stop-async-iteration.yaml`](../tests/fixtures/sources/parity/concurrency-stop-async-iteration.yaml);
it remains unexecuted pending the grouped parity phase.
