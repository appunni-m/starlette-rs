# Request and HTTPConnection lookup boundary

Compatibility is pinned to Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`.

## Dynamic descriptors and scope

The pinned `HTTPConnection` constructor assigns through `self.scope`, and its
mapping methods and inherited properties read `self.scope` on the public
Python object (`starlette/requests.py:86-167`). A user subclass can override
that descriptor, so a Rust-backed facade must resolve the current public
property at the same lookup point and pass its value to Rust. Python performs
only descriptor lookup and value forwarding; Rust retains property selection,
cache policy, mapping operations, and Starlette behavior. In particular,
cache hits for `url`, `base_url`, `headers`, `query_params`, `cookies`, and
`state` must retain the upstream ordering and must not trigger an unnecessary
`scope` lookup.

The same rule applies to `Request` and `WebSocket`, which inherit these
properties. Constructor assignment also goes through the public descriptor,
as it does in the pinned implementation.

## `Request.url_for` arguments

The pinned method passes `name` unchanged to `url_path_for`
(`starlette/requests.py:198-203`). A `str` subclass may override equality or
other methods observed by a custom route provider. The Rust binding therefore
keeps the original Python object when forwarding this argument; it does not
reconstruct a plain string. Provider selection, URL construction, and error
propagation remain Rust-owned.

After the provider returns a URL path, the pinned method dynamically reads
`self.base_url` before calling `make_absolute_url`. A Request subclass can
override that descriptor, so the Rust helper resolves the public property at
that point and forwards its value to the URL path operation. The input-only
comparison for this override is registered alongside the string-subclass
case.

## Push-promise headers

Pinned `Request.send_push_promise` first reads `self.scope` to check the
`http.response.push` extension, then reads the public `self.headers` property
and calls `getlist` for each copied header name
(`starlette/requests.py:342-348`). Subclasses may override either property.
The Rust state machine performs the extension decision, header-name and value
iteration, Latin-1 encoding, event construction, and send ordering. At those
lookup boundaries it invokes the public descriptors and `getlist` method,
preserving their Python values and exceptions.

The input-only comparisons for these descriptor and argument boundaries are
registered in the active parity manifest. They contain stimuli and observation
selectors only; source/package execution remains deferred to the grouped full
parity phase. No standalone unit tests or expected outputs are added.
