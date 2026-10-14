# Python typing boundary

Static compatibility is checked against Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, using Mypy 1.19.1 from
`scripts/parity/locks/typecheck-cpython312.txt`. The input-derived consumers are
in `tests/fixtures/sources/parity/application-typing-consumer.yaml`,
`config-typing-consumer.yaml`, `formdata-generic-typing.yaml`, and
`response-typing-consumer.yaml`.

The consumer sources were checked against the pinned checkout with
`MYPYPATH=../starlette` and against the current wheel installed in
`build/parity/envs/cpython312/python-package`. Both Mypy runs exited 0 and
produced identical diagnostics and revealed types. The checks cover:

- `Request[State]`, `WebSocket[State]`, and default `HTTPConnection[State]`
  typing, including the typed state access.
- `Request.form()` works through both `await` and `async with`; each result is
  asserted and revealed as `FormData`.
- Iterating `Request.stream()` yields values asserted and revealed as `bytes`.
- `Request.query_params` is asserted and revealed as `QueryParams`, and
  `Request.path_params` is asserted and revealed as `dict[str, Any]`.
- `await request.body()` is asserted and revealed as `bytes`, and
  `await request.json()` is asserted and revealed as `Any`.
- `WebSocketClose` construction and its `(Scope, Receive, Send) -> Awaitable[None]`
  ASGI callable signature.
- ASGI app, receive, send, scope, and response call signatures, including a
  mutable mapping scope.
- All nine `Config.__call__` overload assertions.
- `FormData` indexing as `UploadFile | str`, `getlist()` as
  `list[UploadFile | str]`, and `multi_items()` as
  `list[tuple[str, UploadFile | str]]`.
- The declared `starlette/py.typed` marker, present as an empty file in both
  the pinned source and installed wheel.

The application consumer also exposed a type identity difference in
`Request.form()`: the pinned annotation resolves to
`starlette._utils.AwaitableOrContextManager`, while the facade had declared an
equivalent Protocol in `starlette.requests`. The facade now defines that
declarative Protocol in `starlette/_utils.py` and imports it from
`starlette/requests.py`, so the consumer reveal matches the source module path.
This change contains no runtime branching or Starlette behavior.

One additional public typing candidate remains: assert `Request.client` as
`Address | None` in a consumer. Source evidence is
`starlette/requests.py`'s `HTTPConnection.client` annotation and the remote
address examples in `docs/requests.md`.
