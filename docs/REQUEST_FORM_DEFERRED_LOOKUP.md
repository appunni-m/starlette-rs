# Request.form deferred lookup boundary

Pinned Starlette 1.6.0 implements `Request.form()` as a wrapper around the
`_get_form()` coroutine. The coroutine reads `self.headers` only when its
returned awaitable is first awaited. A caller can therefore change
`request.scope["headers"]` after calling `request.form()` and before awaiting
it, and the new header value selects the parser.

The compatibility facade forwards the Request object and the supplied parser
limits to Rust. Rust's form state machine retains that Request and reads its
cached `headers` property when the awaitable starts. This keeps the property
cache and scope-replacement behavior on the Rust-owned execution path without
adding Python-side branching or parsing.

`request-form-call-await-header-snapshot.yaml` supplies an unsupported initial
content type, replaces the scope headers with a URL-encoded content type after
calling `form()`, then observes the parsed URL-encoded field. The active
manifest, contract validator, and both adapters support the
`form_deferred_scope_headers` input. Its source comparison is ready and remains
unexecuted until the grouped parity phase.

Source evidence: pinned `starlette/requests.py:268-322` and
`docs/requests.md:79-105`. The new input comparison remains unexecuted until the
grouped parity phase.
