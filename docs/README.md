# Documentation

This index groups the project guides, compatibility evidence, Rust-native API
contracts, and release information. The [repository README](../README.md) is
the quickest route to installation and the first Python and Rust examples.

## Project status and compatibility

- [Compatibility inventory](COMPATIBILITY_INVENTORY.md) — implemented surface,
  unresolved candidates, and known gaps.
- [Implementation plan](IMPLEMENTATION_PLAN.md) — remaining work across the
  Starlette replacement.
- [Pinned upstream sources](UPSTREAM.md) — compatibility authority and source
  provenance.
- [Parity contract](PARITY.md) — live-oracle comparison inputs and evidence.
- [Compatibility atlas](atlas/README.md) — API and fixture review conventions.
- [Atlas constraints](atlas/CONSTRAINTS.md) — project-wide compatibility
  constraints.
- [Atlas final audit](atlas/FINAL_AUDIT.md) — source-backed review results.
- [Prioritized atlas backlog](atlas/PRIORITIZED_BACKLOG.md) — open review work.

## Rust-native APIs

- [Routing](native-routing.md) — Rust-native named-route reverse lookup.
- [HTTP service](native-service.md) — Tower service, request bodies, and
  streamed responses.
- [WebSocket routes](native-websocket.md) — Rust-native WebSocket APIs.
- [Lifespan](native-lifespan.md) — Rust-native application lifecycle.

## Python and ASGI compatibility boundaries

These notes record observable Python behavior that crosses the PyO3 or ASGI
boundary and the corresponding oracle evidence.

### Requests and values

- [Request and connection lookup](REQUEST_CONNECTION_LOOKUP_BOUNDARY.md)
- [Request form lookup](REQUEST_FORM_DEFERRED_LOOKUP.md)
- [Request lifetime](REQUEST_LIFETIME_BOUNDARY.md)
- [Request receive ordering](REQUEST_RECEIVE_ORDERING.md)
- [Shared request stream completion](REQUEST_STREAM_SHARED_COMPLETION.md)
- [Concurrent request-body collection](REQUEST_BODY_CONCURRENCY.md)
- [Value and worker lifetime](VALUE_LIFETIME_BOUNDARY.md)
- [Python typing contracts](PYTHON_TYPING_BOUNDARY.md)

### Responses and errors

- [Response rendering and attributes](RESPONSE_RENDER_BOUNDARY.md)
- [Cookie callback ownership](COOKIE_OWNERSHIP_BOUNDARY.md)
- [Server-error traceback](SERVER_ERROR_BOUNDARY.md)

### Routing and middleware

- [Route matching](ROUTE_MATCH_BOUNDARY.md)
- [Route-local middleware](ROUTE_LOCAL_MIDDLEWARE_BOUNDARY.md)
- [Application middleware iteration](APPLICATION_MIDDLEWARE_BOUNDARY.md)
- [Config callable overrides](CONFIG_CALL_OVERRIDE_BOUNDARY.md)
- [Float routing and negative zero](ROUTING_FLOAT_NEGATIVE_ZERO.md)
- [Optional dependency imports](OPTIONAL_IMPORT_BOUNDARY.md)
- [StaticFiles path encoding](STATICFILES_PATH_ENCODING_BOUNDARY.md)
- [Template callback protocol](TEMPLATE_PROTOCOL_BOUNDARY.md)

### WebSockets, concurrency, and TestClient

- [WebSocket endpoint encoding](WEBSOCKET_ENDPOINT_ENCODING_BOUNDARY.md)
- [WebSocket endpoint lookup order](WEBSOCKET_ENDPOINT_LOOKUP_ORDER.md)
- [WebSocket JSON evaluation order](WEBSOCKET_JSON_MODE_ORDER.md)
- [WebSocket ownership](WEBSOCKET_OWNERSHIP_BOUNDARY.md)
- [Concurrency boundary](CONCURRENCY_BOUNDARY.md)
- [TestClient runtime boundary](TESTCLIENT_BOUNDARY.md)

## Dependencies, evidence, and releases

- [Dependency inventory](DEPENDENCIES.md) — direct and transitive dependency
  provenance and licensing.
- [Software bill of materials](SBOM.md) — generated SBOM scope and checks.
- [Benchmark mapping](BENCHMARKS.md) — deterministic workloads and benchmark
  status.
- [Release readiness](RELEASING.md) — staged Cargo, PyPI, and documentation
  preparation; it does not authorize publication.
- [Contributing](../CONTRIBUTING.md) — local quality gates and contribution
  workflow.
- [Security policy](../SECURITY.md) — private vulnerability-reporting route.
