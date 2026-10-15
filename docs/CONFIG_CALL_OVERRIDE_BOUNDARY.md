# Config callable subclass dispatch boundary

Pinned Starlette 1.6.0 implements `Config.__call__` as a call to
`self.get(key, cast, default)` (`starlette/config.py::Config.__call__`). This
uses normal Python method lookup, so a `Config` subclass that overrides the
public `get` method controls the result of calling that instance.

The Rust-backed `Config` facade cannot perform Python subclass method
resolution inside its Rust `Config` value: the override belongs to the outer
Python object and may execute arbitrary caller code. The facade therefore
forwards `__call__` through `self.get`. It does not implement lookup or cast
semantics there; those remain in Rust through the existing `get` forwarding
method. An input-only parity case supplies the subclass return value and
compares the observable callable result against the pinned source.
