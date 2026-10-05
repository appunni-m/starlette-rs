# Template callbacks during the implementation phase

Authority: Starlette 1.6.0 at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, `starlette/templating.py:80-158`
and `docs/templates.md`.

Rust now initializes the facade's public `context_processors` and `env` values
in source order, invokes the subclass environment setup hook, merges context
processor results, and invokes the public template lookup callback before response
construction. Python holds the required attributes and forwards calls. No runtime
Python branching, iteration, error policy or template selection is added.

Jinja2 remains the optional template engine. Its environment, decorators, loader
and render callbacks cannot be replaced by Rust Starlette algorithms while
preserving user-supplied Jinja environments and extensions. Rust owns Starlette's
configuration decisions and callback ordering. The decorator compatibility alias
is selected at module import by Rust; failure and alias-version environments need
further comparison.

Ten input-only `templating-protocols.yaml` consumers construct subclasses with
attribute callbacks, setup delegation/replacement/failure and template lookup
delegation/failure. They exercise directory and preconfigured environments plus
TemplateResponse through TestClient. All stimuli and injected user exceptions are
input-derived; source and target produce the observations live. Static validation
passes; the inputs have not been executed. They join the full parity phase after
implementation across all remaining feature families, followed by coverage and
benchmarks.
