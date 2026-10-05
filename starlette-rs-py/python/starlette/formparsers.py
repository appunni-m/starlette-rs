"""Form dependency and exception representations selected by the Rust runtime."""

from starlette_rs_py import _core

MultiPartException = _core.MultiPartException
multipart, parse_options_header = _core._form_dependencies()
