# Optional dependency import policy

Authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`,
`starlette/testclient.py:31-51`, `starlette/templating.py:13-29`,
`starlette/formparsers.py:11-25`, `starlette/requests.py:15-27`,
`starlette/middleware/sessions.py:7-8` and `starlette/schemas.py`.

Rust selects TestClient's HTTPX2 primary import and HTTPX fallback. Only
ModuleNotFoundError selects fallback or the missing-dependency RuntimeError;
other ImportError and arbitrary loader failures propagate unchanged. Rust
preserves the missing-error context chain and explicit suppression used by
`raise ... from None`, including warning-as-error context on fallback.

The Jinja integration catches ImportError from dependency loading and decorator
selection and retains the original exception as cause and context. Attribute
errors choose the legacy decorator only at the source lookup point. Python
facades forward imports and calls; they contain no new control flow.

Python's configured import system and warning machinery remain boundary
callbacks. Replacing them with a Rust package lookup would change custom
import loaders, installed environments, warning filters and exception objects.
Rust owns dependency choice, fallback policy, error construction and forwarding.

Thirty-eight `optional-imports.yaml` consumers import the public modules with an
input-selected loader that raises original dependency errors, plus installed
dependency controls and warning filters. The observations include resolved
optional distribution versions, TestClient's selected backend and a request
through the legacy HTTPX fallback, the selected multipart parser import path,
the Jinja2 context decorator alias, and the `full` extra's declared optional
requirements from installed distribution metadata. Both source and target
independently execute the same consumer. The inputs contain no expected
outputs; they are normal oracle parity cases because the source can reach every
supplied import failure and compatibility profile.

The legacy multipart profile aliases the locked `python-multipart` parser
objects at the old `multipart` import paths while the source package is forced
to report `python_multipart` as missing. This reaches Starlette's documented
fallback import and form parser using the same parser implementation. It does
not qualify behavior specific to an independently installed legacy `multipart`
distribution; that remains an environment-version boundary.

Rust also selects the multipart primary and legacy imports, checks the optional
header-parser boundary before Request.form, and preserves the session signer
import contract. Sessions still execute signing and verification in Rust.
OpenAPI rendering and docstring parsing retain their Python YAML representation
callbacks. Request.form, schema rendering and schema docstring actions are
input-defined public consumers after the real module import. The four schema
docstring cases exercise `SchemaGenerator.get_schema` with an empty or truthy
docstring while PyYAML is present or selected as missing; the former returns
the base schema without parsing, while the latter reaches the pinned assertion.

The input definitions are unexecuted until the integrated parity phase. Loader
failures are ordinary oracle comparisons; real dependency absence and supported
interpreter qualification remain separate evidence requirements.
