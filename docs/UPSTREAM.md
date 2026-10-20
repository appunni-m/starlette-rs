# Upstream identities

## Cookie protocol input provenance

`response-cookie-protocols.yaml` is independently authored from the pinned
`starlette/responses.py:90-160`, `docs/responses.md:29-52`, and the active
CPython 3.12.13 `http.cookies` value/attribute conversion behavior. User
argument subclasses and callback/error/reentry stimuli are original consumer
code; no upstream test file, stored expected output, or standard-library
implementation is copied. Starlette's BSD-3-Clause provenance remains
applicable. The active Python standard library is supplied by CPython under
the PSF license and remains a runtime representation boundary for Python
date values and exception classes.

## Starlette oracle

| Field | Pinned identity |
| --- | --- |
| Repository | <https://github.com/Kludex/starlette> |
| Release | `1.6.0` |
| Commit | `4f250d6b814587e20c5365f0a5f0c4d42bcb929f` |
| License | BSD-3-Clause, copyright Encode OSS Ltd (2018) |
| Python floor / CI matrix | `>=3.10`; 3.10, 3.11, 3.12, 3.13, 3.14 |

The package metadata and CI matrix in this checkout agree on the Python floor
and supported matrix. The source declares `anyio>=3.6.2,<5` and
`typing_extensions>=4.10.0` for Python below 3.13. The `full` extra contains
`itsdangerous`, `jinja2`, `python-multipart>=0.0.18`, `pyyaml`,
`httpx>=0.27.0,<0.29.0`, and `httpx2>=2.0.0`.

The compatibility inventory and fixtures derive from tracked Python source at
the pinned commit above. Machine-specific checkout state is not part of the
source authority.

## FastAPI downstream consumer

| Field | Identity |
| --- | --- |
| Repository | <https://github.com/fastapi/fastapi> |
| Release tag | `0.141.1` |
| Commit | `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f` |

The pinned release commit's `uv.lock` resolves Starlette **1.3.1** and Pydantic
**2.13.4**. This checkout records the downstream version only; this project
does not create a derived FastAPI environment or implement FastAPI/Pydantic
behavior. FastAPI remains outside the Starlette replacement scope.

## Reference structure

The `pillow-rs` repository at commit
`e9fa12c237fc4e89cfd7e2b5dedf477067ec162a` was consulted as a structural
reference. Relevant patterns adapted here are a fixed input-only manifest,
isolated live oracle/target processes, strict run identity, correctness-gated
benchmarks, and release preflight separated from publication. Image-specific
code, assets, and backend machinery are not part of this project.

## Request lifecycle input provenance

The Request callback-lifetime fixture and public consumer were authored for this repository from the pinned `starlette/requests.py` and `starlette/_utils.py` behavior and `docs/requests.md`; no upstream test file was copied. Starlette source remains a development-time BSD-3-Clause oracle, with its existing Encode OSS notices preserved. Python GC and coroutine behavior is observed live in both isolated environments. See [Request lifetime boundary](REQUEST_LIFETIME_BOUNDARY.md).

The marked-coroutine route input in `asgi-request-callable-shapes.yaml` is
independently authored from pinned `starlette/routing.py` and
`starlette/_utils.py`, plus CPython's `inspect.markcoroutinefunction` behavior
available in Python 3.12 and later. It supplies a synchronous user function
that returns a coroutine and records the public route-dispatch result; no
upstream test body or expected output is copied. The source/package comparison
is scoped to CPython 3.12–3.14 and remains deferred to the grouped parity
phase. See [Python 3.12 inspect documentation](https://docs.python.org/3.12/library/inspect.html#inspect.markcoroutinefunction).

The `websocket-iterator-athrow-arities.yaml` inputs are independently authored
from pinned `starlette/websockets.py` and CPython's async-generator protocol.
They use separate public WebSocket workflows so invalid arity failures cannot
leave one iterator running before the valid one/two/three-argument cases. No
upstream test body or expected output is copied. The source/package comparison
is scoped to CPython 3.10–3.14 and remains deferred to the grouped parity
phase. See the tagged [CPython 3.10](https://github.com/python/cpython/blob/v3.10.0/Objects/genobject.c),
[3.11](https://github.com/python/cpython/blob/v3.11.9/Objects/genobject.c),
[3.12](https://github.com/python/cpython/blob/v3.12.0/Objects/genobject.c),
[3.13](https://github.com/python/cpython/blob/v3.13.0/Objects/genobject.c), and
[3.14](https://github.com/python/cpython/blob/v3.14.0/Objects/genobject.c)
implementations.

The `websocket-route-dispatch.yaml` scope-type inputs are independently
authored from the pinned `starlette/routing.py::WebSocketRoute.matches` and
`BaseRoute.__call__` behavior. They observe Python rich equality for a string
subclass and missing-key propagation through a mapping-backed scope; no
upstream test body or expected output is copied. Their source/package
comparisons remain deferred to the grouped parity phase.

The `nested-middleware-composition.yaml` input is independently authored from
the pinned Application, Mount, Router, and Route middleware construction and
dispatch behavior. It supplies one matched request, path/state mutations on
entry, and headers during unwind to expose the layer order; no upstream test
body or expected output is copied. Its source/package comparison remains
deferred to the grouped parity phase.

## Public value lifetime input provenance

The public value and Request property/worker fixtures and their consumers were authored for this repository from pinned `starlette/datastructures.py`, `starlette/requests.py`, their public documentation, and live Python collection behavior. No upstream test file was copied. Existing Starlette BSD-3-Clause notices remain preserved. See [Public value and worker boundary](VALUE_LIFETIME_BOUNDARY.md).

The four further UploadFile ownership inputs author backing-file replacement
from a user integer arithmetic callback. They derive observable ordering from
the pinned `UploadFile.write` implementation and use public file/size access;
no upstream test body or expected byte output is copied.

The UploadFile in-place arithmetic and worker cancellation definitions are
authored from the pinned public write/read/seek/close methods and
`starlette.concurrency.run_in_threadpool`. User integer/file subclasses and
cancellation barriers are new public-consumer stimuli; no upstream test body
or expected result is copied.

## Response consumer input provenance

`tests/fixtures/sources/parity/response-consumers.yaml` contains independently authored input definitions derived from the pinned `starlette/responses.py:29-200` and `docs/responses.md:10-118`. It uses documented response classes, custom render subclasses, and ordinary ASGI callbacks. No upstream test file or expected output is copied. The source remains the development-time BSD-3-Clause oracle; exact outputs are produced live by both implementations. See `docs/RESPONSE_RENDER_BOUNDARY.md` for the Python calling boundary and limits.

## Response ASGI callback input provenance

`tests/fixtures/sources/parity/response-asgi-callbacks.yaml` is independently authored from the pinned `starlette/responses.py:29-200`, the responses guide's ASGI consumer contract, and the project's Python callback/lifetime boundary requirements. It supplies callback mutations, byte/header values, background functions, suspended coroutines, and collection schedules. Public observations are generated live; no source test file, expected output, or target-private state is copied. The development-time source oracle retains its BSD-3-Clause provenance. See `docs/RESPONSE_RENDER_BOUNDARY.md`.

The input-only `response-construction-protocols.yaml` definitions derive body
length, header conversion ordering, and raw-header/cache behavior from the
pinned `starlette/responses.py:29-101` and documented constructors in
`docs/responses.md:10-118`. User body/header/media classes are independently
authored consumer callbacks. No upstream test file or expected output is
copied. The upstream BSD-3-Clause provenance above applies to reused behavior
specifications.

The input-only `response-attributes.yaml` definitions derive documented response
and public header-view behavior from pinned `starlette/responses.py:29-101`,
`docs/responses.md:10-118`, `docs/middleware.md:299-301,613-632`, and the header
consumer in `tests/test_responses.py:188-199`. Attribute hooks and raw-header
properties are independently authored user callbacks, without copied upstream
test files or expected outputs. The pinned upstream BSD-3-Clause notice above
remains applicable to reused behavior specifications.

## StaticFiles path-subclass input provenance

`tests/fixtures/sources/parity/static-files-str-subclass-path.yaml` is
independently authored from pinned `starlette/_utils.py::get_route_path` and
`starlette/staticfiles.py::StaticFiles.get_path` and `lookup_path` (1.6.0
lines 96-110 and 154-173). Its Python `str` subclasses override only the
source-used `startswith`, slice, or `split` protocol and supply their results
as input; the file trees and response/lookup observations are likewise
input-defined. No upstream test file or expected output is copied. The
source/package comparisons cover CPython 3.10 through 3.14 and remain deferred
to the grouped parity phase. The pinned Starlette BSD-3-Clause provenance
above applies to the behavior specification.

## TestClient input provenance

`tests/fixtures/sources/parity/testclient-root-path-subclass.yaml` is
independently authored from the pinned `starlette/testclient.py:190-205,239-261`
and the `TestClient` scope contract in `docs/testclient.md`. The HTTP and
WebSocket inputs construct their `str` subclass from input fields and compare
the live scope value's type and identity with that original object across
CPython 3.10–3.14. No upstream test body, expected output, or target-private
state is copied. The source remains a development-time BSD-3-Clause oracle;
the comparisons are deferred to the grouped parity phase. See
[`TESTCLIENT_BOUNDARY.md`](TESTCLIENT_BOUNDARY.md).
