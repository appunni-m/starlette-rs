# Rust-native lifespan API

`NativeLifespan` provides an executor-neutral startup and shutdown lifecycle for
Rust-native applications. It is separate from the Python-compatible
`starlette.*` and ASGI surface: it does not encode ASGI lifespan messages, own a
transport, or create an executor.

The lifecycle types are available from the `starlette_rs` crate root.

## Lifecycle and ordering

Register hooks with `NativeLifespan::builder()`, then consume the built
configuration with `start().await`. A successful start returns
`ActiveNativeLifespan`, which retains the application state and cleanup hooks.
Calling `shutdown().await` consumes that active lifecycle and runs its cleanup.

Startup callbacks run in registration order. Shutdown callbacks run in reverse
registration order, so later resources are released before earlier resources.
Startup rollback also runs shutdown callbacks in reverse registration order,
but only for registrations before the failing startup callback. A failed
startup callback is not considered started: its paired shutdown callback does
not run, so the callback must undo its own partial work before returning an
error.

The builder supports three registration shapes:

| Registration | Successful startup | Normal shutdown | Rollback after a later startup error |
| --- | --- | --- | --- |
| `on_startup` | Runs its callback | No paired callback | No cleanup callback |
| `on_shutdown` | No callback | Runs its callback | Runs if registered before the failing startup |
| `on_lifecycle` | Runs its startup callback | Runs its paired shutdown callback | Runs its paired shutdown callback if startup completed |

Hooks are awaited sequentially. A completed startup hook is the unit of
rollback eligibility. Shutdown-only hooks registered after the failing startup
are not called during rollback.

## State and lifetime

Every hook receives a clone of the same `NativeLifespanState`. The store uses
string keys in one namespace across all value types. Values must be
`Send + Sync + 'static`; `get` and `remove` return `Arc<T>`, so callers can keep
a value alive without holding the store lock. `insert` does not replace a key:
a duplicate key returns `NativeLifespanStateError::DuplicateKey`. Looking up or
removing a key with the wrong type returns `TypeMismatch` and leaves the entry
in place.

The active lifecycle owns its state store. When `shutdown` completes, the
lifecycle's state handle is dropped; stored values are dropped when their last
state handle or returned `Arc` is dropped. A host or hook may clone a state
handle or value `Arc` to extend that lifetime deliberately. Dropping an active
lifecycle without calling `shutdown` does not invoke asynchronous cleanup
callbacks.

## Failure model

`NativeLifespanError::Startup` contains the failing registration index, the
original callback error, and any rollback shutdown failures. Rollback continues
after cleanup errors, and those failures are stored in the order their callbacks
ran (reverse registration order). The failing callback's own shutdown callback
is not included.

`NativeLifespanError::Shutdown` contains every failed shutdown callback in
execution order (reverse registration order); one failure does not prevent the
remaining callbacks from running. Each `NativeLifespanHookFailure` exposes the
original registration index with `hook_index()` and the callback error with
`source_error()`. `NativeLifespanError` display text summarizes the failure
count; inspect its fields to retrieve all individual errors. Its standard
`Error::source()` chain points to the primary startup error or, for shutdown,
the first callback failure.

Callback error types may be any `Error + Send + Sync + 'static`. The API keeps
them as error sources instead of reducing them to strings.

## Executor, cancellation, and deadlines

The host owns the executor, timer, cancellation mechanism, and deadline policy.
The lifecycle API has no built-in timeout and does not return a lifecycle error
when the host cancels an operation.

Dropping a pending `start` future drops the currently pending callback future
and the rest of the unstarted lifecycle configuration. If a startup callback
was pending, rollback does not begin, even for earlier startup callbacks that
completed. If startup had already failed and rollback was pending, the current
rollback callback and remaining rollback callbacks are dropped. Previously
completed external side effects are not undone by future cancellation; values
held only in the lifecycle state are dropped unless a state handle or value
`Arc` was retained elsewhere. The consumed configuration cannot be resumed or
retried.

Dropping a pending `shutdown` future drops the pending callback future and every
shutdown callback that has not run yet. The active lifecycle is consumed, so
cancellation does not preserve progress for a retry. Rust destructors for
owned callback captures and state values still run when their final owner is
dropped, but the lifecycle starts no further asynchronous cleanup. Detached
tasks or external work created by a callback are not cancelled by dropping its
future; the callback or host must manage those separately.

A host may race either future against its own timer or cancellation signal. To
abandon the operation, the host must actually stop or drop the future (or abort
the task that owns it); merely stopping the wait while a detached task continues
polling does not cancel it. This remains cooperative cancellation: a callback
that blocks in `poll`, or synchronous `Drop` code that blocks, can prevent the
executor from observing its timer and exceed the intended wall-clock deadline.
The API therefore makes no hard real-time deadline guarantee. Hosts that need
graceful cleanup should drive shutdown to completion; hosts that abandon it
must account for the callbacks and side effects that will not be resumed.

## Example

The standalone example uses `futures::executor::block_on` as one possible host
choice:

```sh
cargo run -p starlette-rs-native-lifespan-example --locked
```

It drives both lifecycle operations to completion and keeps a returned `Arc`
alive across shutdown to show that the value lifetime can outlast the active
lifecycle. A server may use a different executor and its own deadline policy;
the cancellation rules above still apply.
