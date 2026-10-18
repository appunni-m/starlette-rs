# Response cookie callback ownership

Authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`,
`starlette/responses.py:98-121` and CPython's `http.cookies` implementation.

Cookie formatting and response header construction live in Rust. Rust appends
converted Python values to a list owned by the `Response.set_cookie` facade
frame. The list keeps values alive while Rust converts them and appends the
final header. If a callback raises, the traceback retains that Python frame and
its list for as long as the pinned source `set_cookie` frame retains its
`SimpleCookie` local. On successful return the facade releases the list after
the header append. The facade does not select cookie behavior or format values.

This Python-owned anchor is required for faithful exception and lifetime
propagation: the earlier GC-traversable PyO3 call-state object released its
converted values too early in the CPython 3.14.8 coverage-instrumented error
path. The anchor is confined to the FFI boundary; Rust still owns conversion,
validation, ordering, and header construction.

The input-only cases in
[`response-cookie-ownership.yaml`](../tests/fixtures/sources/parity/response-cookie-ownership.yaml)
compare finalizer timing and callback failures for Response, HTMLResponse,
PlainTextResponse, and JSONResponse across CPython 3.10 through 3.14. The
CPython 3.14 coverage run exposed premature target finalization in these four
cases. The four owned-attribute callback-error cases must pass both the live
oracle comparison and the instrumented CPython 3.14.8 coverage profile before
this boundary is considered verified.
