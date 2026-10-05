# Third-party notices

## Starlette source authority

The compatibility baseline is Starlette 1.6.0 at commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, licensed under BSD-3-Clause.
The baseline source declares copyright © 2018 Encode OSS Ltd. See
[`LICENSE.md`](LICENSE.md) for the complete notice and conditions.

The source checkout is used as a local oracle and inventory authority. No
upstream module, test file, documentation page, or image asset has been copied
wholesale. The built-in URL converter rules in
[`starlette-rs-py/python/starlette/convertors.py`](starlette-rs-py/python/starlette/convertors.py)
adapt `starlette/convertors.py` from that pinned source; they retain the
upstream BSD-3-Clause provenance and are not a verbatim module copy. The
route compatibility layer and application dispatch integration in
[`starlette-rs-py/python/starlette/routing.py`](starlette-rs-py/python/starlette/routing.py)
and [`starlette-rs-py/python/starlette/applications.py`](starlette-rs-py/python/starlette/applications.py)
adapt public matching and dispatch behavior from `starlette/routing.py` and
`starlette/applications.py`, with Rust-backed built-in path matching and
Python callable boundaries; they retain the upstream BSD-3-Clause provenance
and are not verbatim module copies. The
redirect response wrapper in
[`starlette-rs-py/python/starlette/responses.py`](starlette-rs-py/python/starlette/responses.py)
adapts the `RedirectResponse` behavior in `starlette/responses.py` from the
pinned source and retains its BSD-3-Clause provenance. The benchmark worker
and [`starlette-rs-py/python/starlette/status.py`](starlette-rs-py/python/starlette/status.py)
also derive their status-code names and integer values from the pinned source;
the status module's deprecated-alias behavior is adapted from
`starlette/status.py` and retains the same BSD-3-Clause provenance. The benchmark
worker ([`scripts/parity/upstream_benchmark_worker.py`](scripts/parity/upstream_benchmark_worker.py))
adapts deterministic payload-generation recipes and the fixed text paragraph
from `benchmarks/gzip_benchmark.py` so the 68 GZip inputs reproduce the pinned
workloads. That adapted material is Copyright © 2018 Encode OSS Ltd. and is
licensed under BSD-3-Clause. [`LICENSE.md`](LICENSE.md) contains the complete
copyright notice, conditions, and disclaimer. Independently authored fixtures
and later implementation code must record their provenance and applicable
licenses.

The input definitions in
[`templating-public.yaml`](tests/fixtures/sources/parity/templating-public.yaml)
are independently authored from `tests/test_templates.py` and
`docs/templates.md` at the pinned Starlette revision. Their short template
strings reproduce the public stimuli, including the homepage URL link,
context-processor greeting, and script-like autoescape input. That reused
material is Copyright © 2018 Encode OSS Ltd., under BSD-3-Clause; the complete
notice is in [`LICENSE.md`](LICENSE.md). The shared live adapter in
[`templating.py`](scripts/parity/adapters/templating.py) executes each side's
public API and does not contain expected outputs.

The input definitions in
[`testclient-websocket-public.yaml`](tests/fixtures/sources/parity/testclient-websocket-public.yaml)
are independently authored from `tests/test_websockets.py` at the pinned
revision. The greeting JSON and short denial-response body reproduce source
stimuli, Copyright © 2018 Encode OSS Ltd., under BSD-3-Clause; the complete
notice is in [`LICENSE.md`](LICENSE.md). The shared live adapter in
[`testclient.py`](scripts/parity/adapters/testclient.py) invokes each side
through public APIs and supplies no expected outputs. The concurrency input
also supplies explicit client disconnect and close-drain actions to make
the captured cleanup tape deterministic.

The inputs in
[`testclient-public.yaml`](tests/fixtures/sources/parity/testclient-public.yaml)
are independently authored from `tests/test_testclient.py` at the pinned
revision. The mock JSON, user-agent value, authentication header, and custom
exception name reproduce source stimuli, Copyright © 2018 Encode OSS Ltd.,
under BSD-3-Clause; the complete notice is in [`LICENSE.md`](LICENSE.md).
[`testclient_public.py`](scripts/parity/adapters/testclient_public.py) invokes
each implementation through public constructors and context management. It
contains user application code and observations, with no expected outputs.

## Dependency notices

The upstream direct and transitive package metadata snapshot is maintained in
[`docs/locked-dependencies.csv`](docs/locked-dependencies.csv), based on the
pinned Starlette `uv.lock`. This is not yet a complete third-party notice set.
Before packaging, verify the license files for every shipped dependency and
include the required notices in Rust crate, Python wheel, and sdist artifacts.

The current Rust compression path depends on `flate2` 1.1.10 and `libz-sys`
1.1.29, both declared MIT OR Apache-2.0. `libz-sys` links a discovered stock
system zlib when available and can build bundled stock zlib otherwise; the
bundled zlib source carries its own zlib license. The exact native library
selected for each wheel build must be identified and its notice included in
that artifact. See the versioned feature and backend notes in
[`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md).

The Rust `FileResponse` path also depends on `getrandom` 0.4.3 (MIT OR
Apache-2.0), `httpdate` 1.0.3 (MIT OR Apache-2.0), `md-5` 0.11.0 (MIT OR
Apache-2.0), and `mime_guess` 2.0.5 (MIT). Their locked metadata and roles are
listed in [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md). MD5 is used only to
match Starlette's existing ETag format; it is not used as a security check.
Inspect the resolved crate license files and include the required notices in
release artifacts.

The multipart Request.form parser adds `multer` 3.1.0 (MIT), `encoding_rs`
0.8.35 ((Apache-2.0 OR MIT) AND BSD-3-Clause), and `futures` 0.3.34 (MIT OR
Apache-2.0), all from crates.io and pinned in `Cargo.lock`. The inspected
archives include the `multer` MIT notice (Copyright © 2020 Rousan Ali), the
`encoding_rs` Apache-2.0/MIT notices (Mozilla Foundation) and WHATWG BSD-3-Clause
notice (WHATWG contributors), and the `futures` Apache-2.0/MIT notices (Alex
Crichton and the Tokio authors). The resolved transitive parser crates are
listed in [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md). Preserve the complete
notices in any distributed artifact that includes these dependencies; the
repository does not copy their source files.
