# starlette-rs-py

`starlette-rs-py` is the Python distribution for the in-progress Rust-backed
implementation of Starlette's Python API. It provides the `starlette.*`
compatibility import package and the `starlette_rs_py` extension module. The
project targets the documented Starlette 1.6.0 surface; full compatibility is
not yet claimed. Check the [compatibility inventory](https://github.com/appunni-m/starlette-rs/blob/main/docs/COMPATIBILITY_INVENTORY.md)
for the implemented surface and known gaps.

## Install

If a release is available from your package index, install the distribution
by its PyPI name:

```sh
python -m pip install starlette-rs-py
```

For the current development checkout, install from the repository root. A
Rust toolchain is required to build the PyO3 extension. Uvicorn is a separate,
optional ASGI server:

```sh
git clone https://github.com/appunni-m/starlette-rs.git
cd starlette-rs
python -m pip install . uvicorn
```

## Run an ASGI application

Create `app.py`:

```python
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route


async def homepage(request):
    return PlainTextResponse("Hello from Starlette-RS")


app = Starlette(routes=[Route("/", homepage)])
```

Start the server from the same directory:

```sh
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/` to see the response. Consult the [documentation
index](https://github.com/appunni-m/starlette-rs/blob/main/docs/README.md) for
API guides, compatibility evidence, and release information. The [pinned
source record](https://github.com/appunni-m/starlette-rs/blob/main/docs/UPSTREAM.md)
describes the compatibility authority and provenance. The [release-readiness
guide](https://github.com/appunni-m/starlette-rs/blob/main/docs/RELEASING.md)
tracks preparation; it does not announce or authorize a package release.

## Project links

- [Repository README and Rust-native examples](https://github.com/appunni-m/starlette-rs/blob/main/README.md)
- [Compatibility inventory](https://github.com/appunni-m/starlette-rs/blob/main/docs/COMPATIBILITY_INVENTORY.md)
- [Parity contract](https://github.com/appunni-m/starlette-rs/blob/main/docs/PARITY.md)
- [Contributing and quality gates](https://github.com/appunni-m/starlette-rs/blob/main/CONTRIBUTING.md)
- [License and third-party notices](https://github.com/appunni-m/starlette-rs/blob/main/LICENSE.md)
- [Security policy](https://github.com/appunni-m/starlette-rs/blob/main/SECURITY.md)
