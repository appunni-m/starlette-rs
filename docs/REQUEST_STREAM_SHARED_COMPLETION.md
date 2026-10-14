# Request stream completion after another body consumer

The pinned `Request.stream()` loop checks `_stream_consumed` before each
receive (`../starlette/starlette/requests.py:239-252`). It marks the shared
request consumed on a final `http.request` event before yielding that event's
body. If one iterator has yielded a partial chunk and is suspended, a separate
`Request.body()` call can consume the final event. Resuming the original
iterator then yields its terminal `b""` and ends without another call to
`receive`.

`RequestStreamState::next` keeps iterator progress separately from shared body
state. In its receiving phase it now observes shared completion, returns that
terminal empty chunk once, and closes the iterator. It does not replay the
completed body's cache because this iterator already started before the cache
was installed.

The input-only comparison is
[`request-stream-after-concurrent-body-completion.yaml`](../tests/fixtures/sources/parity/request-stream-after-concurrent-body-completion.yaml).
Its requirement and source are integrated into the shared parity contract; the
comparison remains unexecuted until the grouped parity phase.
