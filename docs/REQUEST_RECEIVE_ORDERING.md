# Request receive ordering

The pinned `Request.stream()` implementation reads `body`, evaluates
`more_body`, and marks the request stream consumed when `more_body` is false
before it evaluates the truthiness of `body` (`starlette/requests.py:243-248`).
That ordering is observable when a `bytes` subclass overrides `__bool__` and
raises: the current call propagates that exception, while a later uncached
`body()` or `stream()` call raises `RuntimeError("Stream consumed")` without
calling `receive` again.

`starlette-rs-py/src/request_runtime.rs::request_message` preserves this state
transition by marking a terminal pending receive complete after evaluating
`more_body` and before evaluating body truthiness. This keeps the terminal
state even when Python truthiness or byte conversion then raises. An input-only
comparison for this boundary needs a `bytes-subclass` body whose `__bool__`
raises, followed by an observation of the original exception and a retry that
observes `Stream consumed` with no second receive.
