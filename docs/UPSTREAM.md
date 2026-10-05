# Upstream identities

## Starlette oracle

| Field | Pinned identity |
| --- | --- |
| Repository | <https://github.com/Kludex/starlette> |
| Release | `1.6.0` |
| Commit | `4f250d6b814587e20c5365f0a5f0c4d42bcb929f` |
| Local source inspected | `/Users/lazytrot/work/starlette` |
| Local checkout observed | Exact pinned commit, detached `HEAD`; one unrelated untracked `.DS_Store` is present |
| License | BSD-3-Clause, copyright Encode OSS Ltd (2018) |
| Python floor / CI matrix | `>=3.10`; 3.10, 3.11, 3.12, 3.13, 3.14 |

The package metadata and CI matrix in this checkout agree on the Python floor
and supported matrix. The source declares `anyio>=3.6.2,<5` and
`typing_extensions>=4.10.0` for Python below 3.13. The `full` extra contains
`itsdangerous`, `jinja2`, `python-multipart>=0.0.18`, `pyyaml`,
`httpx>=0.27.0,<0.29.0`, and `httpx2>=2.0.0`.

The inventory reads tracked Python source from this commit. The untracked
`.DS_Store` is unrelated and was left untouched.

## FastAPI downstream consumer

| Field | Identity |
| --- | --- |
| Repository | <https://github.com/fastapi/fastapi> |
| Release tag | `0.141.1` |
| Commit | `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f` |
| Local checkout | `/Users/lazytrot/work/fastapi`, detached at the exact tag commit, clean |

The pinned release commit's `uv.lock` resolves Starlette **1.3.1** and Pydantic
**2.13.4**. This checkout records the downstream version only; this project
does not create a derived FastAPI environment or implement FastAPI/Pydantic
behavior. FastAPI remains outside the Starlette replacement scope.

## Reference structure

`/Users/lazytrot/work/pillow-rs` was inspected read-only at
`e9fa12c237fc4e89cfd7e2b5dedf477067ec162a`. Its checkout has unrelated local
changes; none were modified. Relevant patterns adapted here are a fixed
input-only manifest, isolated live oracle/target processes, strict run
identity, correctness-gated benchmarks, and release preflight separated from
publication. Image-specific code, assets, and backend machinery are not part of
this project.

## Request lifecycle input provenance

The Request callback-lifetime fixture and public consumer were authored for this repository from the pinned `starlette/requests.py` and `starlette/_utils.py` behavior and `docs/requests.md`; no upstream test file was copied. Starlette source remains a development-time BSD-3-Clause oracle, with its existing Encode OSS notices preserved. Python GC and coroutine behavior is observed live in both isolated environments. See [Request lifetime boundary](REQUEST_LIFETIME_BOUNDARY.md).
