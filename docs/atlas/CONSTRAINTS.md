# Compatibility constraints and lifecycle edges

This note is evidence for the Starlette compatibility atlas, pinned to upstream
Starlette 1.6.0 at `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. Source paths and line numbers below use GitHub permalinks to that exact commit, so they remain
reviewable without a sibling upstream checkout.

## Current warning sites

`StarletteDeprecationWarning` subclasses `UserWarning`, so these deprecations are
visible under Python's default warning filters
([`starlette/exceptions.py:36-42`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/exceptions.py#L36)).
An omitted `category` defaults to `UserWarning`; an omitted `stacklevel` defaults
to 1.

| Site and timing | Category, message, stack level | Fixture/backlog crosswalk |
| --- | --- | --- |
| `starlette/status.py:190-205`: each deprecated name warns when module attribute lookup resolves it. | `StarletteDeprecationWarning`; `'{name}' is deprecated. Use '{replacement}' instead.`; `stacklevel=3`. | `data-auth-errors.status.alias-lifecycle`, `data-auth-errors.status.alias-warning-metadata`; the upstream test row `data-auth-errors.status.deprecated-tested` covers only two aliases. |
| `starlette/concurrency.py:16-20`: when the `async def` body begins executing as `run_until_first_complete` is awaited/scheduled. | `StarletteDeprecationWarning`; `run_until_first_complete is deprecated and will be removed in a future version.`; omitted stack level (1). | `asgi-core.deprecation.run-until-first-complete-warning`; `asgi-core.concurrency.first-completion-cancels-peers`. |
| `starlette/routing.py:593-599`: synchronously in `Router.__init__` when `lifespan` is an async-generator function. | `StarletteDeprecationWarning`; `async generator function lifespans are deprecated, use an @contextlib.asynccontextmanager function instead`; omitted stack level (1). | `asgi-core.deprecation.async-generator-lifespan-warning`. |
| `starlette/routing.py:600-605`: synchronously in `Router.__init__` when `lifespan` is a generator function. | `StarletteDeprecationWarning`; `generator function lifespans are deprecated, use an @contextlib.asynccontextmanager function instead`; omitted stack level (1). | `asgi-core.deprecation.sync-generator-lifespan-warning`. |
| `starlette/testclient.py:35-51`: while importing `starlette.testclient`, if `httpx2` is absent but `httpx` imports successfully. | `StarletteDeprecationWarning`; `Using \`httpx\` with \`starlette.testclient\` is deprecated; install \`httpx2\` instead.`; `stacklevel=2`. | `optional.httpx-fallback-deprecation`; the both-backends-absent error is `optional.no-httpx-backend`. |
| `starlette/testclient.py:430-453`: on each `TestClient.request` call where `timeout is not httpx.USE_CLIENT_DEFAULT` (including an explicit `None`). | `StarletteDeprecationWarning`; `You should not use the 'timeout' argument with the TestClient. See https://github.com/Kludex/starlette/issues/1108 for more information.`; `stacklevel=2`. | `optional.test_testclient.test_timeout_deprecation`. |
| `starlette/middleware/wsgi.py:17-22`: when the deprecated module is imported. | `StarletteDeprecationWarning`; `starlette.middleware.wsgi is deprecated and will be removed in a future release. Please refer to https://github.com/abersheeran/a2wsgi as a replacement.`; `stacklevel=2`. | `middleware.deprecation.wsgi-module-warning`. |
| `starlette/config.py:60-64`: synchronously during `Config(env_file=...)` construction if the path is not a file. | Default `UserWarning`; `Config file '{env_file}' not found.`; omitted stack level (1). This is a missing-file warning, not a deprecation. | `data-auth-errors.config.missing-file-warning`. |

The `status` test parametrization in
[`tests/test_status.py:8-25`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/tests/test_status.py#L8)
only checks the 413 and 414 aliases. The dedicated alias lifecycle and warning
rows exercise all four current aliases and their replacements below.

## Deprecated status aliases

`starlette.status.__getattr__` preserves these aliases and returns their numeric
status codes while warning. The canonical names are the supported names
([`starlette/status.py:182-207`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/status.py#L182)).

| Deprecated name | Replacement | Value |
| --- | --- | ---: |
| `HTTP_413_REQUEST_ENTITY_TOO_LARGE` | `HTTP_413_CONTENT_TOO_LARGE` | 413 |
| `HTTP_414_REQUEST_URI_TOO_LONG` | `HTTP_414_URI_TOO_LONG` | 414 |
| `HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE` | `HTTP_416_RANGE_NOT_SATISFIABLE` | 416 |
| `HTTP_422_UNPROCESSABLE_ENTITY` | `HTTP_422_UNPROCESSABLE_CONTENT` | 422 |

## Removed API and feature history relevant to the pinned surface

Starlette 1.0 removed the following compatibility paths. The release note gives
the supported replacement for each group
([`docs/release-notes.md:173-196`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L173)):

| Removed in 1.0 | Current replacement or boundary |
| --- | --- |
| `on_startup` / `on_shutdown` constructor parameters, `on_event()`, `add_event_handler()`, and `Router.startup()` / `Router.shutdown()` | Use a `lifespan` context function. |
| `Starlette.route()` / `Router.route()` and `websocket_route()` decorators | Supply `Route` / `WebSocketRoute` instances in `routes`. |
| `Starlette.exception_handler()` decorator | Pass `exception_handlers`. |
| `Starlette.middleware()` decorator | Pass `middleware`. |
| `starlette.routing.iscoroutinefunction_or_partial()` | Removed; no public replacement is documented. |
| `Jinja2Templates(**env_options)` | Pass a configured `jinja2.Environment` using `env=`. |
| `Jinja2Templates.TemplateResponse(name, context)` legacy ordering | Use `TemplateResponse(request, name, ...)`. |
| `FileResponse(method=...)` | Removed; the release notes specify no replacement. |

Other removals that can be mistaken for current public API include:

- Built-in `GraphQLApp` was deprecated in 0.15.0 and removed in 0.17.0. The
  current GraphQL page only points to third-party integrations
  ([`docs/graphql.md:1-8`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/graphql.md#L1),
  [`docs/release-notes.md:953-984`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L953)).
- `UJSONResponse` was removed in 0.14.1; custom JSON serialization is an
  application-defined response concern
  ([`docs/release-notes.md:1034-1041`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L1034)).
- The `ExceptionMiddleware` import proxy from `starlette.exceptions` was removed
  in 0.45.0; the class remains at `starlette.middleware.exceptions`.
- Deprecated WebSocket constants `WS_1004_NO_STATUS_RCVD` and
  `WS_1005_ABNORMAL_CLOSURE` were removed in 0.45.0. Their earlier replacements
  were `WS_1005_NO_STATUS_RCVD` and `WS_1006_ABNORMAL_CLOSURE`.
- `TestClient(allow_redirects=...)` was removed in 0.43.0; use
  `follow_redirects=`. `Jinja2Templates.get_env()` and the class-level
  `TestClient.async_backend` were removed in 0.16.0; backend selection is through
  constructor arguments. The `WSGIMiddleware(workers=...)` argument had no effect
  since 0.6.3 and was removed before the GraphQL deprecation.
- The deprecated `FileResponse(method=...)` and the 1.0 template signatures above
  should not be reintroduced. The 1.0 removals and earlier removal entries are
  in [`docs/release-notes.md:173-196`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L173),
  [`:413-432`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L413),
  [`:969-977`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L969), and
  [`:1013-1020`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/release-notes.md#L1013).

The current fixture partitions have a justified N/A row for the GraphQL
documentation (`docs.graphql.removed-support`). The general release-notes row
`docs.release-notes.historical-current-contracts` is also N/A because it is
historical guidance, not a runtime behavior case.

## Python and typing support

- Package metadata declares `requires-python = ">=3.10"` and classifiers for
  Python 3.10, 3.11, 3.12, 3.13, and 3.14
  ([`pyproject.toml:12-30`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/pyproject.toml#L12)).
- The exact main CI test matrix is `3.10`, `3.11`, `3.12`, `3.13`, `3.14` on
  `ubuntu-latest`. The workflow installs dependencies, builds package/docs, runs
  tests and coverage in every lane; `scripts/check` (lint) is skipped on 3.14
  ([`.github/workflows/main.yml:13-47`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/.github/workflows/main.yml#L13)).
- `typing_extensions>=4.10.0` is a conditional required dependency when
  `python_version < '3.13'`, not a project extra
  ([`pyproject.toml:33-36`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/pyproject.toml#L33)). Code uses
  `typing_extensions.TypeIs` and `TypeVar` below 3.13
  ([`starlette/_utils.py:13-19`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/_utils.py#L13),
  [`starlette/requests.py:32-35`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/requests.py#L32));
  `Self` falls back below 3.11 in TestClient
  ([`starlette/testclient.py:27-30`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/testclient.py#L27)).
- `Response.set_cookie(partitioned=True)` is supported only on Python 3.14 and
  newer. On older versions it raises
  `ValueError("Partitioned cookies are only supported in Python 3.14 and above.")`;
  `partitioned=False` remains valid. The docs and implementation specify this
  boundary ([`docs/responses.md:32-45`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/responses.md#L32),
  [`starlette/responses.py:89-132`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/responses.py#L89)).
  Existing cases: `response.test.test_set_cookie`,
  `response.test.test_set_cookie_raises_for_invalid_python_version`, and
  `docs.responses.set-cookie`.

The cross-surface Python matrix is consolidated as
`request-response.python-version-matrix`; its selectors cover import/build,
ASGI/lifespan, sync dispatch, URL/config/exception behavior, type metadata, and
cookie behavior across the supported interpreters.

## Optional dependency boundaries

Core dependencies are `anyio>=3.6.2,<5` plus the conditional typing dependency
above. The only package optional extra is `full`; its exact dependencies are in
[`pyproject.toml:33-46`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/pyproject.toml#L33). The `dev` and
`docs` entries in `[dependency-groups]` are development groups, not published
extras ([`pyproject.toml:48-70`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/pyproject.toml#L48)).

| Full-extra package | Consumer boundary and absence behavior |
| --- | --- |
| `itsdangerous` | Required for `SessionMiddleware`; `starlette.middleware.sessions` imports it at module import (`starlette/middleware/sessions.py:8-9`). No fallback is provided. Existing case: `middleware.optional.sessions-itsdangerous`. |
| `jinja2` | Required for `Jinja2Templates`; importing `starlette.templating` without it raises `ImportError("jinja2 must be installed to use Jinja2Templates")` (`starlette/templating.py:13-28`). The missing-dependency import boundary is `optional.jinja2-import-failure`. |
| `python-multipart>=0.0.18` | Required for `Request.form()` and form parsers. Imports first try `python_multipart`, then the legacy `multipart` module; if neither is available the module remains importable, but form use asserts that python-multipart must be installed (`starlette/requests.py:17-30,268-290`; `starlette/formparsers.py:12-25,58-66,153-161`). Existing cases: `request-response.optional.multipart`, `middleware.optional.multipart-body-limit`. |
| `pyyaml` | Required by `SchemaGenerator` docstring parsing and `OpenAPIResponse` rendering. `starlette.schemas` imports without PyYAML, then raises an assertion at use (`starlette/schemas.py:12-24,98-113`). The missing-dependency use boundary is `optional.pyyaml-openapi-render-boundary`. |
| `httpx2>=2.0.0` | Preferred and documented `TestClient` backend. If absent, runtime import falls back to `httpx`; with neither installed it raises `RuntimeError` explaining that `httpx2` must be installed (`starlette/testclient.py:32-51`). The full extra also includes legacy `httpx>=0.27.0,<0.29.0`, which remains supported with a deprecation warning. The preferred, fallback, and missing-backend states are `optional.httpx2-preferred-runtime`, `optional.httpx-fallback-deprecation`, and `optional.no-httpx-backend`. |

The docs enumerate the optional use boundaries and `starlette[full]`
installation ([`docs/index.md:99-109`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/index.md#L99)); the
TestClient page documents the `httpx2` preference and deprecated `httpx`
fallback ([`docs/testclient.md:12-17`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/testclient.md#L12)).

## Source-backed fixture crosswalk

These input-only backlog cases now map the identified compatibility edges;
selectors name observations, not expected values:

- `optional.test_testclient.test_timeout_deprecation` maps
  `tests/test_testclient.py::test_timeout_deprecation`; it supplies an explicit
  timeout and observes warning category/message/call site and response behavior. The test is at
  [`tests/test_testclient.py:467-472`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/tests/test_testclient.py#L467).
- `optional.httpx-fallback-deprecation` and `optional.no-httpx-backend` isolate
  the supported `httpx` fallback and the error when both backends are absent.
- `optional.jinja2-import-failure` and
  `optional.pyyaml-openapi-render-boundary` capture their import/use absence
  boundaries.
- `crosscut.removed-api-surface` probes the removed names and former signatures
  listed above; upstream tests do not exercise these removals.

The alias lifecycle/warning fixtures cover all four deprecated status names;
the upstream-test-derived row only covers two. Each lifespan-generator warning
now has one dedicated deprecation backlog ID.
