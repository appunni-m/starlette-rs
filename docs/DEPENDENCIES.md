# Dependency inventory

**State: in progress.** This inventory is based on Starlette 1.6.0's
`pyproject.toml` and `uv.lock` at
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`. It contains 86 package records:
the editable Starlette project plus 85 third-party packages across runtime,
`full`, development, and docs selections. There are 22 distinct direct locked
third-party packages across those selections; 63 additional packages are
transitive-only. The source build backend is
`hatchling` and is not pinned in the upstream lock.

The direct packages below include the locked version and PyPI release metadata
license observed for that version. Legacy PyPI `License` text is kept as
reported; it is not treated as a substitute for reviewing the package's
included license files. A full license-file, implementation-language, native
component audit remains open for selected transitive packages and for release
artifacts.

The CSV snapshot records all 85 external lock entries, exact locked child edges,
parent chains, dependency groups, PyPI language classifiers, available wheel
types, and license metadata for the locked release version. It has reported
license metadata for 84 entries; `mypy-extensions==1.1.0` needs direct archive
license inspection. Implementation-language classifiers and platform-wheel
notes are evidence to review, not proof that a particular native component is
loaded at runtime.

## Required runtime

| Package | Upstream requirement / locked version | Why Starlette uses it | Relevant components / transitive notes | Reported license |
| --- | --- | --- | --- | --- |
| anyio | `>=3.6.2,<5`; `4.14.2` | Async task groups, cancellation, thread offload, async stream abstractions, and backend-neutral concurrency | Runtime; lock children include `idna`, `typing-extensions`; AnyIO can use asyncio or optional Trio backend | MIT |
| typing-extensions | `>=4.10.0` when Python `<3.13`; `4.15.0` locked | Backports typing constructs used by annotations and runtime checks on older supported Python | Runtime on 3.10–3.12; no native component indicated by upstream source | PSF-2.0 |

## Optional runtime feature (`starlette[full]`)

| Package | Requirement / locked version | Feature | Relevant components / transitive notes | Reported license |
| --- | --- | --- | --- | --- |
| itsdangerous | unbounded; `2.2.0` | Signed session cookies in `SessionMiddleware` | Python implementation; no locked child package | BSD License |
| jinja2 | unbounded; `3.1.6` | `Jinja2Templates` | Python with optional MarkupSafe accelerator; lock child `markupsafe` | BSD License |
| python-multipart | `>=0.0.18`; `0.0.32` | Multipart form and upload parsing | Python implementation; no locked child package | Apache-2.0 |
| pyyaml | unbounded; `6.0.3` | YAML schema/configuration support | Includes an optional native LibYAML-backed extension; no third-party lock child is required for Starlette runtime | MIT |
| httpx | `>=0.27.0,<0.29.0`; `0.28.1` | Deprecated compatibility backend for `TestClient` | Python HTTP client; lock children include `httpcore`, `anyio`, `certifi`, `idna`, `h11`, and `sniffio` | BSD-3-Clause |
| httpx2 | `>=2.0.0`; `2.9.1` | Preferred `TestClient` backend | Python package; lock children include `httpcore2`, `anyio`, `idna`, `truststore`, and `typing-extensions` | BSD-3-Clause |

## Build, upstream test-source, benchmark, and documentation dependencies

| Category | Package | Requirement / locked version | Purpose | Reported license / implementation note |
| --- | --- | --- | --- | --- |
| Build | hatchling | unpinned build-system requirement | Builds the upstream Python wheel/sdist | MIT; version and isolated build dependency closure still need pinning |
| Upstream source | pytest | `9.1.1` | Pinned Starlette test framework retained in the source lock; this repository maps source tests to parity inputs and does not run them as project unit tests | MIT; Python |
| Upstream source | coverage | `7.15.2` | Pinned Starlette test coverage tooling retained in the source lock; not used as a project unit-test gate | Apache-2.0; Python package with optional C tracer |
| Upstream source | trio | `0.33.0` | Alternate backend dependency declared for pinned Starlette's source tests; those tests are not run as project unit tests | MIT OR Apache-2.0; Python |
| Benchmark | pytest-codspeed | `5.0.3` | CodSpeed benchmark adapter | MIT; Python plugin; CodSpeed service is external |
| Test/tooling | mypy | `2.1.0` | Strict type checking | MIT; Python with mypyc-compiled distributions available |
| Test/tooling | ruff | `0.16.0` | Lint and formatting | MIT; native Rust executable |
| Test/tooling | types-PyYAML | `6.0.12.20250516` | PyYAML typing stubs | Apache-2.0; Python typing data |
| Test/tooling | importlib-metadata | `9.0.0` | Distribution metadata compatibility in CI | Apache-2.0; Python; lock child `zipp` |
| Test/tooling | twine | `7.0.0` | Inspect built distributions | Apache-2.0; Python; many CLI/keyring/HTTP transitive dependencies |
| Test extra | zstandard | `0.25.0` through `httpx2[zstd]` | Test compressed HTTPX2 responses | BSD-3-Clause; native C extension |
| Docs | black | `26.5.1` | Format documented Python snippets | MIT; Python |
| Docs | mkdocstrings | `1.0.6` | Render Python API documentation | ISC; Python; MkDocs/Jinja/Markdown transitive dependencies |
| Docs | mkdocstrings-python | `2.0.5` | Python mkdocstrings handler | ISC; Python |
| Docs | zensical | `0.0.51` | Build upstream documentation site | MIT; Python application; lock includes MkDocs-related dependencies |

The direct-package licenses and implementation notes above are an initial
inventory, not release clearance. Before packaging, audit all license files and
native build/runtime requirements in the resolved target lock, then include
third-party notices for shipped material. Do not copy the upstream lockfile as
the Starlette-RS lock: the Rust core, Python bridge, and build backend will
have a different dependency graph. [`locked-dependencies.csv`](locked-dependencies.csv)
contains a versioned metadata snapshot for every third-party lock entry, its
locked child edges and direct parent chain, PyPI license/classifier fields, and
wheel/native review status. The metadata snapshot is not a license-file audit.

Regenerate the lock and metadata snapshot from the exact local Starlette
checkout with:

```sh
python3 scripts/inventory_upstream_dependencies.py \
  --upstream /path/to/starlette \
  --output docs/locked-dependencies.csv \
  --snapshot-date YYYY-MM-DD
```

## Starlette-RS dependency policy

## Rust compression backend

| Crate | Locked version | Feature / role | Native component and license |
| --- | --- | --- | --- |
| `flate2` | `1.1.10` | `default-features = false`, `zlib`; streaming gzip framing and DEFLATE API used by `GzipCompressor` | MIT OR Apache-2.0 |
| `libz-sys` | `1.1.29` | Selected by `flate2/zlib`; uses stock zlib and links a system zlib when discovered, with a bundled-source fallback | MIT OR Apache-2.0 for the Rust crate; bundled zlib source carries its upstream zlib license |

The parity environment used CPython 3.12.13 on macOS arm64. Python's runtime
zlib and the zlib backend linked by `libz-sys` both reported version 1.2.12
during the streaming investigation. Exact GZip bytes depend on the source and
target compression implementations matching; the active byte-for-byte parity
cases verify this specific environment, not every platform or zlib release.
Record the actual linked compression backend and version for each future
wheel/platform build before claiming equivalent bytes there.

The resolved Rust graph is locked in `Cargo.lock`. Before packaging, include
the selected `flate2`, `libz-sys`, and zlib notices in the wheel/crate notice
set and inspect the final linked native component. This inventory is not a
release clearance.

- [`flate2` 1.1.10 manifest and feature definitions](https://docs.rs/crate/flate2/1.1.10)
- [`libz-sys` 1.1.29 backend and licensing notes](https://docs.rs/crate/libz-sys/1.1.29)

## Rust hashing and signed-session-cookie support

| Crate | Locked version | Role | Cargo manifest license |
| --- | --- | --- | --- |
| `base64` | `0.22.1` | URL-safe encoding for signed-cookie timestamps and signatures, plus payload encoding | MIT OR Apache-2.0 |
| `hmac` | `0.13.0` | HMAC construction and verification for timestamped session cookies | MIT OR Apache-2.0 |
| `sha1` | `0.11.0` | SHA-1 digest used to match the pinned ItsDangerous signer format | MIT OR Apache-2.0 |
| `sha2` | `0.11.0` | SHA-256 identity digest used by the Rust-native parity adapter | MIT OR Apache-2.0 |
| `digest` | `0.11.3` (transitive) | Shared digest API used by `hmac`, `sha1`, `sha2`, and `md-5` | MIT OR Apache-2.0 |
| `block-buffer` | `0.12.1` (transitive) | Shared digest block buffering | MIT OR Apache-2.0 |
| `crypto-common` | `0.2.2` (transitive) | Shared cryptographic traits and primitives | MIT OR Apache-2.0 |
| `ctutils` | `0.4.2` (transitive) | Constant-time utilities in the shared digest stack | MIT OR Apache-2.0 |
| `cmov` | `0.5.4` (transitive) | Conditional-move primitive used by `ctutils` | MIT OR Apache-2.0 |
| `cpufeatures` | `0.3.1` (transitive) | CPU feature detection for RustCrypto hash implementations | MIT OR Apache-2.0 |

The versions come from the workspace `Cargo.lock`; license expressions come
from the corresponding locked crate `Cargo.toml` files in the local Cargo
registry. These are metadata facts, not a review of each crate archive's
included license files. `deny.toml` requires one shared `digest` version,
rejects unreviewed licenses and dependency sources, and records the RustSec
advisory policy. The listed direct and transitive crates must be included in
the eventual Rust distribution notice audit.

- [`base64` 0.22.1 manifest](https://docs.rs/crate/base64/0.22.1)
- [`hmac` 0.13.0 manifest](https://docs.rs/crate/hmac/0.13.0)
- [`sha1` 0.11.0 manifest](https://docs.rs/crate/sha1/0.11.0)
- [`sha2` 0.11.0 manifest](https://docs.rs/crate/sha2/0.11.0)
- [`digest` 0.11.3 manifest](https://docs.rs/crate/digest/0.11.3)

The parity environments keep the upstream oracle separate from the installed
Starlette-RS package. `scripts/parity/locks/starlette-oracle-cpython312.txt`
pins `itsdangerous==2.2.0` for the source oracle, whose `SessionMiddleware`
uses ItsDangerous. The installed Python-package environment is defined by
`scripts/parity/locks/asgi-runtime-cpython312.txt`; it does not install
ItsDangerous because the replacement's session signing runs in Rust. This
separation keeps the source oracle dependency out of the target runtime.

## Rust file-response helpers

| Crate | Locked version | Feature / role | License and compatibility note |
| --- | --- | --- | --- |
| `getrandom` | `0.4.3` | System random source for 104-bit multipart range boundaries | MIT OR Apache-2.0; declared Rust 1.85 MSRV |
| `httpdate` | `1.0.3` | HTTP IMF-fixdate formatting for `Last-Modified` | MIT OR Apache-2.0; declared Rust 1.56 MSRV |
| `md-5` | `0.11.0` | MD5 ETag compatibility with Starlette's existing validator format | MIT OR Apache-2.0; declared Rust 1.85 MSRV; used only for legacy interoperability |
| `mime_guess` | `2.0.5` | Static file-extension content-type lookup | MIT; no `rust-version` is declared; its MIME mapping may change in patch releases |

The active Rust toolchain successfully resolves and checks these locked
versions at the workspace's Rust 1.85 minimum. File-response parity currently
uses the pinned mapping for declared fixture extensions. Python's platform
`mimetypes` database can differ from this static map, so unsupported extension
equivalence remains a compatibility boundary to cover before a release.

- Keep Pydantic and FastAPI outside this package.
- Keep Rust core dependencies separate from Python runtime and build
  dependencies. Pin features and native components explicitly before a crate
  or wheel release.
- Keep the minimal Python runtime independent of PyYAML. Install the
  `schemas` extra to enable YAML-backed schema parsing and OpenAPI responses.
- Do not require optional templates, multipart, YAML, or client packages for a
  minimal ASGI application.
- Generate a new locked graph per supported Python/platform build, record the
  complete transitive package list and licenses, and inspect crate/wheel/sdist
  contents before any release.
