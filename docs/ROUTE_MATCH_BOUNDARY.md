# Route matching boundary

The compatibility authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. In the pinned
`starlette/routing.py`, `Router.app` visits routes in declaration order and
calls each route's `matches(scope)`. It dispatches the first `Match.FULL`, or
the first `Match.PARTIAL` if no full match exists, then applies the returned
child scope before calling `handle`.

The router accepts `BaseRoute` instances, so a user subclass can supply its own
`matches` implementation. That method is arbitrary Python user code; Rust
cannot translate or reproduce it while preserving its return values and Python
exceptions. The Rust router therefore identifies route match overrides and
passes those routes through its supplemental matcher callback. Rust still
selects which routes to visit, preserves declaration order and FULL/PARTIAL
precedence, and applies the selected child scope. The callback runs on Python's
owning thread under the GIL, where the original method and exception types are
available.

The input-only stimulus for this behavior is
`tests/fixtures/sources/parity/routing-base-route-subclass-matches.yaml`. Its
oracle and target adapters construct the input-defined `BaseRoute` subclass.
The case is in the active manifest and remains unexecuted until the full parity
phase.
