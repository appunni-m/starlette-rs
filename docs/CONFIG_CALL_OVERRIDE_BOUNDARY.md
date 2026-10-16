# Config callable subclass dispatch boundary

Pinned Starlette 1.6.0 implements `Config.__call__` as a call to
`self.get(key, cast, default)` (`starlette/config.py::Config.__call__`). This
uses normal Python method lookup, so a `Config` subclass that overrides the
public `get` method controls the result of calling that instance.

The Rust-backed facade cannot resolve an override on the outer Python object
from its internal Rust `Config` value. `__call__` therefore forwards through
`self.get`, and `Config.get` calls Rust with the public Config object. Rust
dynamically reads `env_prefix`, `environ`, and `file_values` from that object in
the pinned lookup order, then invokes its `_perform_cast` method so subclass
overrides remain observable. Base lookup, precedence, defaults, error policy,
and casts remain Rust-owned; Python provides descriptor lookup and the call
into user-defined methods.

Input-only cases cover a subclass whose public properties return values
different from its internal Config state, and verify `_perform_cast` dispatch.
They also cover Python's empty-format-spec behavior for string subclasses in
Config and Environ errors. These cases are contract-validated in
`parity-input@66` and remain unexecuted until the grouped parity phase.
