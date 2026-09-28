# Compatibility inventory

**Atlas state: source-mapping milestone complete; full Starlette replacement remains active and incomplete.** The source authority is Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. The inventory deliberately keeps
source candidates separate from the reviewed compatibility surface; an
importable name alone does not establish public status. The atlas is a source
review and fixture crosswalk, while the active parity contract measures a
separate bounded implementation slice.

Root [`metadata.yaml`](../metadata.yaml) is authoritative for pinned API-source
references and the public source, documentation, and test roots used by
inventory generation. The separate [`parity manifest`](../tests/fixtures/manifest.yaml)
indexes behavioral requirements and generated input paths. Authored parity and
benchmark definitions live as JSON-compatible YAML under
`tests/fixtures/sources/{parity,benchmark}/`; `make parity-inputs` generates
runtime JSON under ignored `build/parity/inputs/`. Result JSON under
`build/parity/` is also local, ignored output. These build artifacts are not
checked in; the run IDs and counts below describe their recorded executions.

The active parity manifest indexes 105 input-only cases across 16 files: 38
request/routing cases, 21 reverse-URL cases, four direct Starlette ASGI cases,
eight GZip cases, six full WebSocket protocol-tape cases, six projected
WebSocket state cases, five Request-style HTTPException cases, two callable-ASGI
HTTPException cases, two registered-handler cases, nine server-error cases,
and four direct RedirectResponse ASGI-call cases. The protocol-tape,
reverse-URL, and Request cases select the Python-package profile. Built-in
Router, slash-redirect, and RedirectResponse cases select both profiles; Mount
cases also select both, with their Rust-native rows declared unsupported. The
six state-sequence cases select both profiles. The four direct RedirectResponse
cases in [`redirect-response.yaml`](../tests/fixtures/sources/parity/redirect-response.yaml)
were included in the recorded run below; all eight source-to-target comparisons
passed. Run `5b5ed1db-5669-427f-b882-9a4c0fef7fad`, finished at
`2026-09-28T09:45:15.116Z`, selected 156 comparisons: 150 passed, zero failed,
six were `not_run`, and there were zero infrastructure errors. All 105
Python-package cases passed. Rust-native passed 45 of 51 selected cases; the
remaining six rows are unsupported Python-callable and Mount boundaries. All
21 reverse-URL cases and all 21 selected WebSocket comparisons passed. The six
native `not_run` rows make `run` exit with status 2, so the all-target gate
remains incomplete. Target identities were dirty local trees; this run is not
clean aggregate or release proof. The manifest SHA-256 is
`a5353f06b0bb7a8d5d826a7b203c07e816f3a53cd7b6a5f0996ac7fde27f9ecb`; the
target wheel SHA-256 is
`0db65164f127e01a4474105182b9a61214f1296e9adabc4d5f11f9541afe1044`. The two
registered-handler inputs in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml)
exercise status-code precedence over an `HTTPException` class handler and an
async class handler that reads the request body already cached by the endpoint.
Their case IDs are
`starlette.applications.Starlette.__call__.exception-handler.status-code-precedence`
and
`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse`.
The remaining HTTPException evidence covers five matched HTTP request-style
endpoint exceptions before response start and two callable-ASGI endpoint cases,
including one exception after a complete 200 response; only the explicit-detail
406 case is supported by the Rust-native response builder. The nine server-error
inputs cover the default response, registered 500 and `Exception` handlers,
special-key order, debug text/HTML responses, response-start handling, and a
handled `HTTPException(500)` through the installed package. The debug body
comparison uses the declared stable traceback projection; raw bodies remain in
the result artifacts. The WebSocket inputs cover six ordered receive/send
callback-tape comparisons on the Python package, six projected state cases on
both targets, and three package-profile route-dispatch cases. All 21 WebSocket
comparisons passed in the current run. Convenience methods, denial responses,
WebSocket exception handlers, direct `ServerErrorMiddleware`
invocation, arbitrary middleware ordering, and TestClient propagation remain
outside the active contract. `asgi-core.app.test_app_debug` stays in backlog because its input
constructs the app with debug enabled rather than setting debug after
construction. The parity artifact status is `completed`, but six `not_run`
rows keep the all-target gate incomplete.
The separate Router/GZip benchmark lane completed all 74 source/package
workloads; Rust-native remains `not_run` for that non-equivalent benchmark
boundary. Its ignored local result files are `build/parity/parity-result.json`
and `build/parity/upstream-benchmark-result.json`.
These results cover the selected workflows only and do not establish full
compatibility.

## Current denominators

Root `metadata.yaml` selects the pinned public Starlette source files and the
documentation and test roots. The inventory generator uses that metadata and
parses the pinned source with Python's AST, recording signatures/defaults
without importing Starlette. These source and atlas
counts describe the pinned revision and checked-in atlas matrix, not the number
of active parity cases:

| Surface | Count | Meaning |
| --- | ---: | --- |
| Python files under `starlette/` | 35 | Includes package initializers and two private helper modules |
| Import-path candidates | 33 | 31 non-private leaf modules plus `starlette` and `starlette.middleware`; candidate paths are inventory aids, and a module's importability alone does not establish its public contract |
| Public-name source candidates | 237 | 93 classes, 16 functions, and 128 assignments including the explicit root `__version__` export |
| Public-named class methods | 239 | Methods whose names do not begin with `_` |
| Constructor rows | 66 | `__init__` signatures |
| Special-method rows | 102 | Dunder method signatures |
| Candidate source rows | 476 | Definitions and public-named methods; constructor/special rows are separate |
| Source re-export candidates | 230 | Local Starlette imports that may or may not be intentional public aliases |
| Documented import references | 122 | Deduplicated by import path and docs page |
| User-facing documentation pages in navigation | 24 | 20 feature pages, Introduction, Release Notes, and two Community pages |
| Explicit API expansion directives | 3 | `Starlette`, `TestClient`, and `Jinja2Templates` |
| Upstream test-tree Python files | 34 | Includes 30 `test_*.py` modules and four shared/support modules |
| Upstream test functions and methods | 514 | AST-discovered and mapped test functions in the 30 `test_*.py` modules |
| Upstream lock records | 86 | One editable Starlette record plus 85 external packages across runtime, optional, dev, and docs groups |

The candidate rows, source line numbers, signatures, defaults, constructors,
special methods, candidate re-exports, and documentary evidence are in
[`api-surface.csv`](api-surface.csv). The merged
[`API review`](atlas/api-review.csv) dispositions each of its 999 rows with
evidence: 514 `supported`, 286 `private/internal`, and 199 `uncertain`. The
catalog's original `audit_status` field records inventory provenance; use the
merged disposition and rationale for the compatibility classification. The
root package defines only `__version__ = "1.6.0"`; it has no convenience
re-exports or `__all__`.

## Completed atlas coverage

The [`coverage matrix`](atlas/coverage-matrix.csv) contains 789 mappings:

| Mapping | Count |
| --- | ---: |
| Upstream test functions and methods | 514 source functions represented by 537 behavior mappings |
| Documentation navigation pages | 24 |
| Shared test support modules | 4, with 14 downstream-use mappings |
| All source mappings | 789 |
| Existing input mappings in the atlas matrix | 25 |
| Reasoned `not_applicable` mappings | 50 |
| New input-only fixture backlog | 714 |

The [`fixture backlog`](atlas/fixture-backlog.csv) contains no expected
outputs. Every backlog mapping has an input stimulus and observation selectors;
every `not_applicable` mapping has a concrete reason. In this checked-in
crosswalk snapshot, 25 `existing` mappings point to authored YAML input
definitions; runtime JSON is generated separately under `build/parity/inputs/`.
The active manifest separately indexes 16 parity input files with 105 cases:
38 request/routing cases (including async and synchronous Request endpoints,
a callable-instance ASGI route, slash redirects, and three `WebSocketRoute`
dispatch cases), 21 reverse-URL cases, four direct ASGI cases for `/hello`,
`/missing`, the wrong method, and a public slash redirect, eight
`GZipMiddleware` cases, four direct `RedirectResponse` ASGI-call cases (all
eight selected source-to-target comparisons passed), six full WebSocket protocol-tape
cases, six projected WebSocket state cases, five Request-style HTTPException
cases, two callable-ASGI HTTPException cases, two registered-handler cases,
and nine server-error cases. The `starlette.websockets.WebSocket.protocol-sequence`
operation contains six cases whose Python-package observations preserve the
ordered receive/send ASGI callback tape, including attempted sends whose
callback raises. The `starlette.websockets.WebSocket.state-sequence` operation repeats
those six input sequences and compares action outcomes, exact error messages,
and both final state enums on source, package, and Rust-native profiles; it
does not compare payloads or Python exception metadata. All 18 protocol/state
comparisons passed in the current run. The route operation is
`starlette.routing.WebSocketRoute.route-dispatch`; its cases are
`matched-root-path`, `router-miss-close`, and `http-scope-404`; all three passed
in the Python-package profile. The
status-handler case checks that a 405 status key takes precedence over a
registered `HTTPException` class key during route dispatch. The class-handler
case raises a handled subclass after the endpoint reads the body; its async
handler reads that cached body through the same request. Both are in
[`asgi-exception-handlers.yaml`](../tests/fixtures/sources/parity/asgi-exception-handlers.yaml).
Their case IDs are
`starlette.applications.Starlette.__call__.exception-handler.status-code-precedence`
and
`starlette.applications.Starlette.__call__.exception-handler.request-body-cache-reuse`.
The five upstream HTTPException tests and
the HTTPException documentation contract map to the two exception input files;
`test_handled_exc_after_response` has a declared partial observation of its
after-start behavior, while its `TestClient(raise_server_exceptions=False)`
branch remains outside this slice. The remaining 714 backlog rows are atlas
mapping status, not proof that those behaviors are absent from active inputs or
untested.
The merger validates the pinned upstream commit, all 999 API rows, evidence
paths, test identities, support modules, docs navigation paths, and
input-only fixture files.

## Import-path candidates

The 31 non-private leaf module paths are:

`starlette.applications`, `starlette.authentication`, `starlette.background`,
`starlette.concurrency`, `starlette.config`, `starlette.convertors`,
`starlette.datastructures`, `starlette.endpoints`, `starlette.exceptions`,
`starlette.formparsers`, `starlette.middleware.authentication`,
`starlette.middleware.base`, `starlette.middleware.body_limit`,
`starlette.middleware.cors`, `starlette.middleware.errors`,
`starlette.middleware.exceptions`, `starlette.middleware.gzip`,
`starlette.middleware.httpsredirect`, `starlette.middleware.sessions`,
`starlette.middleware.trustedhost`, `starlette.middleware.wsgi`,
`starlette.requests`, `starlette.responses`, `starlette.routing`,
`starlette.schemas`, `starlette.staticfiles`, `starlette.status`,
`starlette.templating`, `starlette.testclient`, `starlette.types`, and
`starlette.websockets`. The leaf paths sit under the package paths `starlette`
and `starlette.middleware`.

The private implementation modules `starlette._exception_handler` and
`starlette._utils` are tracked as implementation dependencies, not public
imports. `starlette.graphql` was removed before this pin; the docs explain that
GraphQL is supplied by third-party packages. WSGI remains present but deprecated
in the pinned source.

## Errors, aliases, and deprecations identified in the pinned source

The symbol catalog includes exception declarations. Error-related public-name
candidates include `AuthenticationError`, `ClientDisconnect`, `EnvironError`,
`HTTPException`, `MalformedRangeHeader`, `MultiPartException`, `NoMatchFound`,
`RangeNotSatisfiable`, `StarletteDeprecationWarning`, `WebSocketDisconnect`,
and `WebSocketException`; their source-backed classification and observable
behavior are recorded in the merged API review and fixture matrix.

The deprecated `starlette.status` aliases and their replacements are:

| Deprecated name | Replacement | Compatibility detail |
| --- | --- | --- |
| `HTTP_413_REQUEST_ENTITY_TOO_LARGE` | `HTTP_413_CONTENT_TOO_LARGE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_414_REQUEST_URI_TOO_LONG` | `HTTP_414_URI_TOO_LONG` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE` | `HTTP_416_RANGE_NOT_SATISFIABLE` | Emits `StarletteDeprecationWarning` on access |
| `HTTP_422_UNPROCESSABLE_ENTITY` | `HTTP_422_UNPROCESSABLE_CONTENT` | Emits `StarletteDeprecationWarning` on access |

Other deprecation behavior identified for exact compatibility includes
`run_until_first_complete`, importing `starlette.middleware.wsgi`, generator
and async-generator lifespan callables, `TestClient(timeout=...)`, and the
legacy `httpx` TestClient backend. Preserve category, message, timing, and
stack level from the pinned source.

## Unresolved points carried into implementation

- The 199 `uncertain` API candidates remain deliberately unresolved where the
  pinned docs, source, and release history do not establish public intent.
- The WebSocket guide says query parameters are unsupported while a pinned test
  exercises them; both inputs remain separate in
  `doc.testclient.websocket-query-params` until the mismatch is reconciled.
- Jinja2 has no declared minimum version although templating selects between
  context decorator names; see `optional.jinja2-version-compatibility`.
- The GZip module has a TODO for a future `DEFAULT_EXCLUDED_CONTENT_TYPE`
  rename while the pinned export is plural; see
  `middleware.alias.gzip-exclusion-constant`.
- The upstream-internal `GZipResponder` import is absent from the compatibility
  package; the current exact parity slice covers the public `GZipMiddleware`
  boundary only.
- The docs say async Jinja2 context processors are unsupported without
  specifying whether use errors, is ignored, or is awaited; see
  `doc.templates.async-context-processor-constraint`.

These items are tracked as uncertain behavior or backlog stimuli; they do not
block using the atlas to choose implementation work. The remaining staged work
includes broader Python/Rust boundary characterization and expansion beyond
the current ASGI, GZip, default HTTPException, and registered-handler slices.
The backlog distinguishes that work from the 105 currently indexed cases and
the 714-row atlas backlog snapshot
in [`PRIORITIZED_BACKLOG.md`](atlas/PRIORITIZED_BACKLOG.md).

## Generate the source candidate catalog

From this repository, pass the checked-out pinned source directory:

```sh
python3 scripts/inventory_upstream_api.py \
  --upstream /path/to/starlette \
  --output docs/api-surface.csv
```

The command rejects an unexpected upstream commit. The generated catalog is a
review aid, not a claim that every non-private source declaration is public.
