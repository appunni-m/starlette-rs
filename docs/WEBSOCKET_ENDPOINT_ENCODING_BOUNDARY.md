# WebSocketEndpoint encoding lookup boundary

Pinned Starlette 1.6.0 reads `self.encoding` separately for the `text`, `bytes`,
and `json` comparisons in `WebSocketEndpoint.decode`. The fallback assertion
reads it again, and reads it once more to format the assertion message only
when the assertion fails. A public subclass can expose `encoding` as a property
or descriptor whose value changes or raises on each access, so caching the
value changes the selected branch and observable errors.

The Python facade passes the endpoint object to Rust. Rust performs ordinary
Python attribute lookups in the pinned source order and keeps the branch
selection, message decoding, close behavior, and error policy native. CPython
must run a user-defined Python descriptor when Rust asks for `encoding`; using
Python's attribute protocol preserves that contract without moving the
decoding algorithm into Python.

[`websocket-endpoint-encoding-property.yaml`](../tests/fixtures/sources/parity/websocket-endpoint-encoding-property.yaml)
supplies a property returning `xml`, `xml`, then `json`. The live JSON response
observes the third ordered lookup. This input is authored for the deferred full
parity run and has not been executed.
