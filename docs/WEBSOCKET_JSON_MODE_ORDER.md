# WebSocket JSON mode evaluation order

The pinned Starlette 1.6.0 implementation validates `mode` membership, checks
that the application state is connected, awaits a receive, and checks for a
disconnect before comparing `mode` with `"text"` (`starlette/websockets.py`
lines 130–142). This ordering determines which user-defined comparison error
is observable when a hashable mode object compares equal during membership but
raises during the later text comparison.

The Rust receive continuation follows that order: it validates mode membership
before the state check and defers `mode == "text"` until after receive and
disconnect handling. The input-only probe is
[`websocket-json-mode-state-order.yaml`](../tests/fixtures/sources/parity/websocket-json-mode-state-order.yaml).
The fixture uses the `websocket-mode-equality-after-membership` input marker;
root integration must teach both isolated WebSocket convenience adapters to
materialize that input object and add the fixture to the active manifest.
Parity execution remains deferred to the grouped parity phase.
