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

Thirty-one `optional-imports.yaml` consumers import the public modules with an
input-selected loader that raises original dependency errors, plus installed
dependency controls and warning filters. Both source and target independently
execute the same consumer. It records dependency attempts, warning category and
message, public consumer availability, and error identity/cause/context graphs.
There are no recorded expected outputs. These are normal oracle parity cases,
because the source can reach every supplied import failure.

Rust also selects the multipart primary and legacy imports, checks the optional
header-parser boundary before Request.form, and preserves the session signer
import contract. Sessions still execute signing and verification in Rust.
OpenAPI rendering and docstring parsing retain their Python YAML representation
callbacks. Request.form, schema rendering and schema docstring actions are
input-defined public consumers after the real module import.

The input definitions are unexecuted until the integrated parity phase. Loader
failures are ordinary oracle comparisons; real dependency absence and supported
interpreter qualification remain separate evidence requirements.
