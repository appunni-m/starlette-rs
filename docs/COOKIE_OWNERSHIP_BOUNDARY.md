# Response cookie callback ownership

Authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`,
`starlette/responses.py:98-121` and CPython's `http.cookies` implementation.

Cookie formatting and response header construction live in Rust. PyO3 keeps
Python callback results alive while Rust converts values and appends the final
header. When a user conversion raises partway through `set_cookie`, the Python
exception traceback must also retain those values for as long as the source
`set_cookie` frame retains its `SimpleCookie` local. In CPython 3.14, a facade
local that is used only by a failing native method call can otherwise be
released before the traceback is observed. The declarative `del cookie` after
the native call keeps the local live across that call and releases it on
successful return; on failure, traceback lifetime matches the pinned source.

The input-only cases in
[`response-cookie-ownership.yaml`](../tests/fixtures/sources/parity/response-cookie-ownership.yaml)
compare finalizer timing and callback failures for Response, HTMLResponse,
PlainTextResponse, and JSONResponse across CPython 3.10 through 3.14. The
CPython 3.14 coverage run exposed premature target finalization in these four
cases. The next grouped parity and coverage run must verify the lifetime fix;
no new compatibility claim is made here.
