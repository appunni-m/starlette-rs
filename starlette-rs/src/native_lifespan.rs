//! Server-neutral startup and shutdown lifecycle for Rust-native applications.
//!
//! This module does not create an executor, timer, cancellation token, or
//! transport protocol. The host drives [`NativeLifespan::start`] and
//! [`ActiveNativeLifespan::shutdown`] on its executor and decides how to apply
//! deadlines. Dropping either future stops polling the operation and drops its
//! currently running hook future; it does not initiate or continue callbacks
//! after cancellation.
//!
//! A deadline is a host policy, not a guarantee made by this API. Cancellation
//! is cooperative: the host must actually stop or drop the operation, and a
//! callback that blocks while being polled or a slow synchronous destructor can
//! exceed the host's intended wall-clock limit.

use std::{
    any::{Any, TypeId, type_name},
    collections::HashMap,
    error::Error,
    fmt::{self, Debug, Display, Formatter},
    future::Future,
    pin::Pin,
    sync::{Arc, Mutex},
};

/// The type-erased form used to retain a startup or shutdown callback error.
///
/// Callbacks may return any error implementing `Error + Send + Sync + 'static`;
/// they do not need to construct this boxed form themselves.
pub type NativeLifespanHookError = Box<dyn Error + Send + Sync + 'static>;

type HookFuture =
    Pin<Box<dyn Future<Output = Result<(), NativeLifespanHookError>> + Send + 'static>>;
type HookCallback = Arc<dyn Fn(NativeLifespanState) -> HookFuture + Send + Sync + 'static>;

struct Hook {
    startup: Option<HookCallback>,
    shutdown: Option<HookCallback>,
}

/// A cloneable, typed-key store shared by the active lifecycle and its hooks.
///
/// Values must be `Send + Sync + 'static`. `get` returns an `Arc`, so a caller
/// can retain a value across an await without holding the store lock. Cloned
/// state handles and returned `Arc`s can outlive the active lifecycle and
/// extend the stored values' lifetime. Keys form one namespace across all
/// value types; removing a key does not invalidate any `Arc` already returned
/// by `get` or `remove`.
#[derive(Clone, Default)]
pub struct NativeLifespanState {
    entries: Arc<Mutex<HashMap<String, StateEntry>>>,
}

struct StateEntry {
    type_id: TypeId,
    type_name: &'static str,
    value: Arc<dyn Any + Send + Sync>,
}

impl Debug for NativeLifespanState {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self.entries.lock() {
            Ok(entries) => formatter
                .debug_struct("NativeLifespanState")
                .field("keys", &entries.keys().collect::<Vec<_>>())
                .finish(),
            Err(_) => formatter
                .debug_struct("NativeLifespanState")
                .field("poisoned", &true)
                .finish(),
        }
    }
}

impl NativeLifespanState {
    /// Inserts a value under `key` without replacing an existing value.
    ///
    /// Keys are shared across all stored types. Use descriptive, stable keys
    /// when multiple values of the same Rust type are needed.
    ///
    /// # Errors
    ///
    /// Returns [`NativeLifespanStateError::DuplicateKey`] if the key is already
    /// occupied, or [`NativeLifespanStateError::Poisoned`] if another thread
    /// panicked while it held the internal store lock.
    pub fn insert<T>(
        &self,
        key: impl Into<String>,
        value: T,
    ) -> Result<(), NativeLifespanStateError>
    where
        T: Any + Send + Sync,
    {
        let key = key.into();
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| NativeLifespanStateError::Poisoned)?;
        if entries.contains_key(&key) {
            return Err(NativeLifespanStateError::DuplicateKey { key });
        }
        entries.insert(
            key,
            StateEntry {
                type_id: TypeId::of::<T>(),
                type_name: type_name::<T>(),
                value: Arc::new(value),
            },
        );
        Ok(())
    }

    /// Returns a shared value for `key`, if present.
    ///
    /// # Errors
    ///
    /// Returns [`NativeLifespanStateError::TypeMismatch`] when the key exists
    /// with a different Rust type, or [`NativeLifespanStateError::Poisoned`]
    /// if another thread panicked while it held the internal store lock.
    pub fn get<T>(&self, key: &str) -> Result<Option<Arc<T>>, NativeLifespanStateError>
    where
        T: Any + Send + Sync,
    {
        let entries = self
            .entries
            .lock()
            .map_err(|_| NativeLifespanStateError::Poisoned)?;
        let Some(entry) = entries.get(key) else {
            return Ok(None);
        };
        if entry.type_id != TypeId::of::<T>() {
            return Err(NativeLifespanStateError::TypeMismatch {
                key: key.to_owned(),
                expected: type_name::<T>(),
                actual: entry.type_name,
            });
        }
        Arc::downcast::<T>(Arc::clone(&entry.value))
            .map(Some)
            .map_err(|_| NativeLifespanStateError::TypeMismatch {
                key: key.to_owned(),
                expected: type_name::<T>(),
                actual: entry.type_name,
            })
    }

    /// Removes and returns a shared value for `key`, if present.
    ///
    /// A type mismatch leaves the entry in the store. Removing the entry does
    /// not destroy its value while another `Arc` returned by `get` or `remove`
    /// still refers to it.
    ///
    /// # Errors
    ///
    /// Returns [`NativeLifespanStateError::TypeMismatch`] when the key exists
    /// with a different Rust type, or [`NativeLifespanStateError::Poisoned`]
    /// if another thread panicked while it held the internal store lock.
    pub fn remove<T>(&self, key: &str) -> Result<Option<Arc<T>>, NativeLifespanStateError>
    where
        T: Any + Send + Sync,
    {
        let mut entries = self
            .entries
            .lock()
            .map_err(|_| NativeLifespanStateError::Poisoned)?;
        let Some(entry) = entries.get(key) else {
            return Ok(None);
        };
        if entry.type_id != TypeId::of::<T>() {
            return Err(NativeLifespanStateError::TypeMismatch {
                key: key.to_owned(),
                expected: type_name::<T>(),
                actual: entry.type_name,
            });
        }
        let value = Arc::downcast::<T>(Arc::clone(&entry.value)).map_err(|_| {
            NativeLifespanStateError::TypeMismatch {
                key: key.to_owned(),
                expected: type_name::<T>(),
                actual: entry.type_name,
            }
        })?;
        entries.remove(key);
        Ok(Some(value))
    }
}

/// A state-store operation failed.
#[derive(Debug, Eq, PartialEq)]
pub enum NativeLifespanStateError {
    /// A key was inserted more than once.
    DuplicateKey {
        /// The occupied state key.
        key: String,
    },
    /// A key was requested with a type other than the type stored there.
    TypeMismatch {
        /// The state key requested by the caller.
        key: String,
        /// The Rust type requested by the caller.
        expected: &'static str,
        /// The Rust type stored under the key.
        actual: &'static str,
    },
    /// The internal mutex was poisoned by a panic while a thread held it.
    Poisoned,
}

impl Display for NativeLifespanStateError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateKey { key } => {
                write!(formatter, "lifespan state key {key:?} already exists")
            }
            Self::TypeMismatch {
                key,
                expected,
                actual,
            } => write!(
                formatter,
                "lifespan state key {key:?} has type {actual}, requested as {expected}"
            ),
            Self::Poisoned => formatter.write_str("lifespan state lock is poisoned"),
        }
    }
}

impl Error for NativeLifespanStateError {}

/// Configures ordered startup and shutdown callbacks.
///
/// Callbacks run in registration order during startup and reverse registration
/// order during shutdown. Each callback receives a clone of the same state
/// store. Callback closures are `Send + Sync`, their futures are `Send`, and
/// callback errors are `Send + Sync + 'static`. The builder is
/// executor-agnostic and has no built-in timeout. Each configured lifecycle is
/// consumed by [`NativeLifespan::start`], so an abandoned startup cannot be
/// resumed or retried with the same configuration.
#[must_use = "build and start the lifecycle to run its callbacks"]
pub struct NativeLifespanBuilder {
    hooks: Vec<Hook>,
}

impl NativeLifespanBuilder {
    /// Creates an empty lifecycle builder.
    pub const fn new() -> Self {
        Self { hooks: Vec::new() }
    }

    /// Registers a startup callback without a corresponding shutdown callback.
    ///
    /// The callback runs once, in registration order. If it fails,
    /// [`NativeLifespan::start`] returns the callback error and rolls back
    /// earlier registrations in reverse order. This registration has no paired
    /// shutdown callback.
    pub fn on_startup<F, Fut, E>(mut self, callback: F) -> Self
    where
        F: Fn(NativeLifespanState) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), E>> + Send + 'static,
        E: Error + Send + Sync + 'static,
    {
        self.hooks.push(Hook {
            startup: Some(box_hook(callback)),
            shutdown: None,
        });
        self
    }

    /// Registers a shutdown callback without a corresponding startup callback.
    ///
    /// The callback runs after a successful full startup. If a later startup
    /// registration fails, it also runs during rollback when this registration
    /// appears before the failing registration. On normal shutdown, its error
    /// is included in [`NativeLifespanError::Shutdown`]; during rollback, the
    /// error is recorded in [`NativeLifespanError::Startup::shutdown_failures`].
    pub fn on_shutdown<F, Fut, E>(mut self, callback: F) -> Self
    where
        F: Fn(NativeLifespanState) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), E>> + Send + 'static,
        E: Error + Send + Sync + 'static,
    {
        self.hooks.push(Hook {
            startup: None,
            shutdown: Some(box_hook(callback)),
        });
        self
    }

    /// Registers a startup/shutdown pair as one ordered lifecycle component.
    ///
    /// Startup callbacks run in registration order. A successful startup
    /// callback makes its paired shutdown callback eligible for rollback and
    /// normal shutdown. The callback whose startup returns an error is not
    /// considered started; it must clean up its own partial work. Its paired
    /// shutdown callback is not invoked for that failure. Startup callback
    /// errors are returned by [`NativeLifespan::start`]; shutdown callback
    /// errors are returned by [`ActiveNativeLifespan::shutdown`] or retained as
    /// rollback failures in [`NativeLifespanError::Startup`].
    pub fn on_lifecycle<Start, StartFut, StartError, Stop, StopFut, StopError>(
        mut self,
        startup: Start,
        shutdown: Stop,
    ) -> Self
    where
        Start: Fn(NativeLifespanState) -> StartFut + Send + Sync + 'static,
        StartFut: Future<Output = Result<(), StartError>> + Send + 'static,
        StartError: Error + Send + Sync + 'static,
        Stop: Fn(NativeLifespanState) -> StopFut + Send + Sync + 'static,
        StopFut: Future<Output = Result<(), StopError>> + Send + 'static,
        StopError: Error + Send + Sync + 'static,
    {
        self.hooks.push(Hook {
            startup: Some(box_hook(startup)),
            shutdown: Some(box_hook(shutdown)),
        });
        self
    }

    /// Builds the immutable lifecycle configuration.
    pub fn build(self) -> NativeLifespan {
        NativeLifespan { hooks: self.hooks }
    }
}

impl Default for NativeLifespanBuilder {
    fn default() -> Self {
        Self::new()
    }
}

fn box_hook<F, Fut, E>(callback: F) -> HookCallback
where
    F: Fn(NativeLifespanState) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = Result<(), E>> + Send + 'static,
    E: Error + Send + Sync + 'static,
{
    Arc::new(move |state| {
        let future = callback(state);
        Box::pin(async move {
            future
                .await
                .map_err(|error| Box::new(error) as NativeLifespanHookError)
        })
    })
}

/// An immutable collection of startup and shutdown callbacks.
#[must_use = "start the lifecycle to run its callbacks"]
pub struct NativeLifespan {
    hooks: Vec<Hook>,
}

impl NativeLifespan {
    /// Creates a builder for a Rust-native lifecycle.
    pub const fn builder() -> NativeLifespanBuilder {
        NativeLifespanBuilder::new()
    }

    /// Runs startup callbacks and returns state valid for the active lifecycle.
    ///
    /// Each completed startup registration is eligible for rollback if a later
    /// startup callback fails. Rollback continues after shutdown-hook errors,
    /// preserving the startup error as the primary failure. Dropping this
    /// future while a startup callback is pending drops that callback future
    /// and does not begin rollback. If cancellation happens while rollback is
    /// already awaiting a shutdown callback, that callback and the remaining
    /// rollback callbacks are dropped instead of completed. Side effects from
    /// completed callbacks are not undone; stored values are dropped with the
    /// operation unless a callback or host retained a state handle or value
    /// `Arc`. Detached work created by a callback is outside this future's
    /// cancellation and remains the callback or host's responsibility.
    /// The host must decide whether to await startup to completion or abandon
    /// it at its own deadline.
    ///
    /// Dropping this future before it completes is terminal: the configuration
    /// is consumed and cannot be resumed or retried. A host timeout is reported
    /// by the host's timeout mechanism, not as [`NativeLifespanError`].
    ///
    /// # Errors
    ///
    /// Returns [`NativeLifespanError::Startup`] when a startup callback fails.
    pub async fn start(self) -> Result<ActiveNativeLifespan, NativeLifespanError> {
        let state = NativeLifespanState::default();
        for (hook_index, hook) in self.hooks.iter().enumerate() {
            if let Some(startup) = &hook.startup {
                if let Err(source) = startup(state.clone()).await {
                    let mut shutdown_failures = Vec::new();
                    for (rollback_index, rollback_hook) in
                        self.hooks[..hook_index].iter().enumerate().rev()
                    {
                        if let Some(shutdown) = &rollback_hook.shutdown {
                            if let Err(source) = shutdown(state.clone()).await {
                                shutdown_failures.push(NativeLifespanHookFailure {
                                    hook_index: rollback_index,
                                    source,
                                });
                            }
                        }
                    }
                    return Err(NativeLifespanError::Startup {
                        hook_index,
                        source,
                        shutdown_failures,
                    });
                }
            }
        }

        let shutdown_hooks = self
            .hooks
            .into_iter()
            .enumerate()
            .filter_map(|(hook_index, hook)| {
                hook.shutdown.map(|callback| ShutdownHook {
                    hook_index,
                    callback,
                })
            })
            .collect();
        Ok(ActiveNativeLifespan {
            state,
            shutdown_hooks,
        })
    }
}

struct ShutdownHook {
    hook_index: usize,
    callback: HookCallback,
}

/// The successfully started lifecycle and the state shared by its hooks.
///
/// Dropping this value does not run asynchronous shutdown callbacks. Hosts
/// should drive [`ActiveNativeLifespan::shutdown`] to completion before they
/// release the application. Cloned [`NativeLifespanState`] handles or values
/// cloned from the state store may extend the lifetime of stored data. When
/// shutdown completes or this value is dropped, values with no remaining state
/// or value handles are dropped according to their Rust `Drop` implementations.
#[must_use = "call shutdown().await to run lifecycle cleanup callbacks"]
pub struct ActiveNativeLifespan {
    state: NativeLifespanState,
    shutdown_hooks: Vec<ShutdownHook>,
}

impl ActiveNativeLifespan {
    /// Borrows the state store shared by startup, shutdown, and the host.
    #[must_use]
    pub fn state(&self) -> &NativeLifespanState {
        &self.state
    }

    /// Runs every shutdown callback in reverse registration order.
    ///
    /// The host drives this future and may apply its own deadline. A callback
    /// error does not stop later shutdown callbacks. Dropping the future while
    /// a callback is pending drops that callback future and every shutdown
    /// callback not yet invoked. This consumes the active lifecycle, so a
    /// cancelled operation cannot be resumed or retried. Synchronous Rust
    /// destructors still run as their owners are dropped; no further async
    /// cleanup is started. A host timeout is reported by the host's timeout
    /// mechanism, not as [`NativeLifespanError`].
    ///
    /// # Errors
    ///
    /// Returns [`NativeLifespanError::Shutdown`] after attempting all shutdown
    /// callbacks when one or more callbacks fail. Failures are ordered by the
    /// order in which the callbacks ran.
    pub async fn shutdown(self) -> Result<(), NativeLifespanError> {
        let mut failures = Vec::new();
        for hook in self.shutdown_hooks.into_iter().rev() {
            if let Err(source) = (hook.callback)(self.state.clone()).await {
                failures.push(NativeLifespanHookFailure {
                    hook_index: hook.hook_index,
                    source,
                });
            }
        }
        if failures.is_empty() {
            Ok(())
        } else {
            Err(NativeLifespanError::Shutdown { failures })
        }
    }
}

/// A failed shutdown callback, including its registration index and source.
#[derive(Debug)]
pub struct NativeLifespanHookFailure {
    hook_index: usize,
    source: NativeLifespanHookError,
}

impl NativeLifespanHookFailure {
    /// Returns the zero-based registration index of the failed callback.
    #[must_use]
    pub const fn hook_index(&self) -> usize {
        self.hook_index
    }

    /// Returns the original callback error without the hook-index wrapper.
    #[must_use]
    pub fn source_error(&self) -> &(dyn Error + Send + Sync + 'static) {
        self.source.as_ref()
    }
}

impl Display for NativeLifespanHookFailure {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "shutdown hook {} failed: {}",
            self.hook_index, self.source
        )
    }
}

impl Error for NativeLifespanHookFailure {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        Some(self.source.as_ref())
    }
}

/// A startup callback or one or more shutdown callbacks failed.
///
/// Startup failures retain the original callback error and any errors from
/// rollback shutdown hooks. Shutdown failures contain every callback error in
/// execution order. The `Display` text summarizes the failure count; inspect
/// the enum fields to retrieve hook indexes and individual error sources.
#[derive(Debug)]
pub enum NativeLifespanError {
    /// A startup callback failed; earlier completed callbacks were rolled back.
    Startup {
        /// Zero-based registration index of the failed startup callback.
        hook_index: usize,
        /// The original startup callback error.
        source: NativeLifespanHookError,
        /// Shutdown errors collected while rolling back earlier callbacks.
        shutdown_failures: Vec<NativeLifespanHookFailure>,
    },
    /// One or more shutdown callbacks failed after all callbacks were attempted.
    Shutdown {
        /// Failures in the order in which their callbacks ran.
        failures: Vec<NativeLifespanHookFailure>,
    },
}

impl Display for NativeLifespanError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Startup {
                hook_index,
                source,
                shutdown_failures,
            } => write!(
                formatter,
                "startup hook {hook_index} failed: {source}; {} rollback shutdown hook(s) failed",
                shutdown_failures.len()
            ),
            Self::Shutdown { failures } => {
                write!(formatter, "{} shutdown hook(s) failed", failures.len())
            }
        }
    }
}

impl Error for NativeLifespanError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Startup { source, .. } => Some(source.as_ref()),
            Self::Shutdown { failures } => failures.first().map(|failure| failure as _),
        }
    }
}
