# Third-party notices

## Starlette source authority

The compatibility baseline is Starlette 1.6.0 at commit
`4f250d6b814587e20c5365f0a5f0c4d42bcb929f`, licensed under BSD-3-Clause.
The baseline source declares copyright © 2018 Encode OSS Ltd. See
[`LICENSE.md`](LICENSE.md) for the complete notice and conditions.

The source checkout is used as a local oracle and inventory authority. No
upstream module, test file, documentation page, or image asset has been copied
wholesale. The benchmark worker
([`scripts/parity/upstream_benchmark_worker.py`](scripts/parity/upstream_benchmark_worker.py))
adapts deterministic payload-generation recipes and the fixed text paragraph
from `benchmarks/gzip_benchmark.py` so the 68 GZip inputs reproduce the pinned
workloads. That adapted material is Copyright © 2018 Encode OSS Ltd. and is
licensed under BSD-3-Clause. [`LICENSE.md`](LICENSE.md) contains the complete
copyright notice, conditions, and disclaimer. Independently authored fixtures
and later implementation code must record their provenance and applicable
licenses.

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
