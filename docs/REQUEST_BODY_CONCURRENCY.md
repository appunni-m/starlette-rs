# Concurrent request body collection

The pinned `Request.body()` implementation keeps each call's chunks in a local
list and installs `self._body` only after that call's `stream()` iterator
finishes (`starlette/requests.py:234-260`). A second body call can fail while
the first call is still awaiting a receive event; that failure does not cancel
the first call's local collection.

The Rust accumulator therefore treats `cache_body_from` as the commit point for
one completed consumer. It checks that the shared request stream has reached a
final `http.request` event, but it does not use the shared collection flag as a
proxy for whether that consumer began collecting. A sibling body call may have
cleared that flag while aborting its own local chunks.

`tests/fixtures/sources/parity/request-concurrent-body-disconnect-recovery.yaml`
defines an input-only comparison for this ordering: one body call blocks on a
partial request, a sibling observes `http.disconnect` and fails, then the first
call resumes through the final request event and its cached body is read twice.
The fixture remains unexecuted until the grouped parity phase.
