# Float converter reverse lookup and negative zero

Starlette 1.6.0 documents `Route` paths with the built-in `float` converter
([routing guide](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/docs/routing.md#path-parameters)).
Its `FloatConvertor.to_string` converts the supplied value to `float`, accepts
negative zero because `-0.0 >= 0.0`, and formats it as `-0`
([`convertors.py:55-66`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/convertors.py#L55-L66)).
`Route.url_path_for` passes each named parameter through that converter
([`routing.py:260-269`](https://github.com/Kludex/starlette/blob/4f250d6b814587e20c5365f0a5f0c4d42bcb929f/starlette/routing.py#L260-L269)).

The Rust-native parity adapter turns the input JSON number `-0.0` into the
text `-0.0`. The native float converter therefore canonicalizes that exact
negative-zero spelling to `-0`, preserving Starlette's reverse-lookup result.
The input-only comparison is
[`route-url-path-float-negative-zero.yaml`](../tests/fixtures/sources/parity/route-url-path-float-negative-zero.yaml).
It reuses the existing `float-converter` requirement and the existing reverse
URL adapter flow; the full parity lane has not been run for this input.
