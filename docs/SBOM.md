# Rust software bill of materials

Maturin 1.14.1 generates a CycloneDX SBOM with `cargo-cyclonedx` 0.5.9. The
generator derives workspace component references from Cargo's local package
IDs, so a wheel built from a checkout can otherwise disclose its temporary
source path. Its generated serial number and timestamp also vary between
otherwise identical wheels.

The checked-in [`starlette-rs-py.cyclonedx.json`](../sboms/starlette-rs-py.cyclonedx.json)
retains the generated Rust component and dependency graph. The
[`normalize_cyclonedx_sbom.py`](../scripts/normalize_cyclonedx_sbom.py) build
utility replaces local workspace references and `file://` download qualifiers
with stable Cargo PURLs, rewrites dependency edges, and validates that every
edge resolves. It derives a stable serial number from the normalized document
and records the explicit timestamp supplied by the maintainer. Maturin's
`[tool.maturin.sbom]` configuration disables only its unnormalized Rust SBOM
and includes this normalized CycloneDX file in the wheel.
The separate `tool.maturin.include` entry retains the source file in the sdist,
so wheels built from an sdist use the same checked-in BOM.

When `Cargo.lock`, workspace package versions, or Rust dependencies change,
regenerate the raw SBOM with the pinned Maturin and `cargo-cyclonedx` versions
in a temporary source copy with Maturin's default Rust SBOM generation enabled.
Extract the generated `*.dist-info/sboms/starlette-rs-py.cyclonedx.json`, then
normalize it into the checked-in path with a stable RFC 3339 timestamp:

```sh
python3 scripts/normalize_cyclonedx_sbom.py \
  --input /path/to/raw/starlette-rs-py.cyclonedx.json \
  --output sboms/starlette-rs-py.cyclonedx.json \
  --timestamp 2026-10-16T00:00:00Z
```

Build the wheel through the normal Maturin configuration and inspect the
installed wheel's `.dist-info/sboms/` entry. The packaged BOM must retain the
current component and dependency counts, resolve every dependency reference,
and contain no local Cargo path reference or `download_url=file://` PURL.
