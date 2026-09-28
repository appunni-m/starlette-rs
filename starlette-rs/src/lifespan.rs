use std::error::Error;
use std::fmt::{self, Display, Formatter};

/// The current state of the successful ASGI lifespan flow.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifespanPhase {
    /// Waiting for `lifespan.startup`.
    AwaitingStartup,
    /// The host should enter its Python lifespan context manager.
    EnteringContext,
    /// Startup completed and the application is running.
    Running,
    /// The host should exit its Python lifespan context manager.
    ExitingContext,
    /// Shutdown completed.
    Complete,
}

/// A host action emitted by a successful lifespan transition.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifespanAction {
    /// Enter the user-provided async lifespan context manager on the host loop.
    EnterContext,
    /// Send the ASGI `lifespan.startup.complete` event.
    SendStartupComplete,
    /// Exit the user-provided async lifespan context manager on the host loop.
    ExitContext,
    /// Send the ASGI `lifespan.shutdown.complete` event.
    SendShutdownComplete,
}

/// An operation attempted on the lifespan state machine.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifespanOperation {
    /// Processing the startup input message.
    StartupReceived,
    /// Reporting successful completion of the context manager's enter call.
    ContextEntered,
    /// Processing the shutdown input message.
    ShutdownReceived,
    /// Reporting successful completion of the context manager's exit call.
    ContextExited,
}

/// A lifespan protocol or transition error.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LifespanError {
    /// The requested operation does not follow the current phase.
    InvalidTransition {
        /// Current state when the invalid operation was attempted.
        phase: LifespanPhase,
        /// Operation that could not be applied.
        operation: LifespanOperation,
    },
    /// An input ASGI message type did not match the expected protocol event.
    UnexpectedMessage {
        /// The exact message type required for this transition.
        expected: &'static str,
        /// The exact message type that was supplied.
        actual: String,
    },
}

impl Display for LifespanError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidTransition { phase, operation } => {
                write!(formatter, "cannot apply {operation:?} during {phase:?}")
            }
            Self::UnexpectedMessage { expected, actual } => {
                write!(
                    formatter,
                    "expected ASGI message {expected:?}, got {actual:?}"
                )
            }
        }
    }
}

impl Error for LifespanError {}

/// Tracks successful ASGI startup and shutdown transitions.
///
/// The state machine owns the order of protocol decisions, while the host
/// performs user Python async context-manager calls between actions. This
/// first slice models successful lifecycle callbacks; the host propagates
/// callback exceptions through its native Python exception boundary.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LifespanState {
    phase: LifespanPhase,
}

impl Default for LifespanState {
    fn default() -> Self {
        Self::new()
    }
}

impl LifespanState {
    /// Creates a state machine awaiting `lifespan.startup`.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            phase: LifespanPhase::AwaitingStartup,
        }
    }

    /// Returns the current lifecycle phase.
    #[must_use]
    pub const fn phase(&self) -> LifespanPhase {
        self.phase
    }

    /// Validates and accepts the `lifespan.startup` message.
    ///
    /// On success, returns [`LifespanAction::EnterContext`] for the host to
    /// execute on its event loop.
    ///
    /// # Errors
    ///
    /// Returns [`LifespanError::UnexpectedMessage`] for any other message type
    /// and [`LifespanError::InvalidTransition`] outside the initial phase.
    pub fn startup_received(
        &mut self,
        message_type: &str,
    ) -> Result<LifespanAction, LifespanError> {
        if message_type != "lifespan.startup" {
            return Err(LifespanError::UnexpectedMessage {
                expected: "lifespan.startup",
                actual: message_type.to_owned(),
            });
        }
        self.transition(
            LifespanPhase::AwaitingStartup,
            LifespanOperation::StartupReceived,
            LifespanPhase::EnteringContext,
            LifespanAction::EnterContext,
        )
    }

    /// Records that the host successfully entered its context manager.
    ///
    /// On success, returns [`LifespanAction::SendStartupComplete`].
    ///
    /// # Errors
    ///
    /// Returns [`LifespanError::InvalidTransition`] unless a startup message
    /// previously requested context entry.
    pub fn context_entered(&mut self) -> Result<LifespanAction, LifespanError> {
        self.transition(
            LifespanPhase::EnteringContext,
            LifespanOperation::ContextEntered,
            LifespanPhase::Running,
            LifespanAction::SendStartupComplete,
        )
    }

    /// Validates and accepts the `lifespan.shutdown` message.
    ///
    /// On success, returns [`LifespanAction::ExitContext`] for the host to
    /// execute on its event loop.
    ///
    /// # Errors
    ///
    /// Returns [`LifespanError::UnexpectedMessage`] for any other message type
    /// and [`LifespanError::InvalidTransition`] unless startup completed.
    pub fn shutdown_received(
        &mut self,
        message_type: &str,
    ) -> Result<LifespanAction, LifespanError> {
        if message_type != "lifespan.shutdown" {
            return Err(LifespanError::UnexpectedMessage {
                expected: "lifespan.shutdown",
                actual: message_type.to_owned(),
            });
        }
        self.transition(
            LifespanPhase::Running,
            LifespanOperation::ShutdownReceived,
            LifespanPhase::ExitingContext,
            LifespanAction::ExitContext,
        )
    }

    /// Records that the host successfully exited its context manager.
    ///
    /// On success, returns [`LifespanAction::SendShutdownComplete`].
    ///
    /// # Errors
    ///
    /// Returns [`LifespanError::InvalidTransition`] unless a shutdown message
    /// previously requested context exit.
    pub fn context_exited(&mut self) -> Result<LifespanAction, LifespanError> {
        self.transition(
            LifespanPhase::ExitingContext,
            LifespanOperation::ContextExited,
            LifespanPhase::Complete,
            LifespanAction::SendShutdownComplete,
        )
    }

    fn transition(
        &mut self,
        expected_phase: LifespanPhase,
        operation: LifespanOperation,
        next_phase: LifespanPhase,
        action: LifespanAction,
    ) -> Result<LifespanAction, LifespanError> {
        if self.phase != expected_phase {
            return Err(LifespanError::InvalidTransition {
                phase: self.phase,
                operation,
            });
        }
        self.phase = next_phase;
        Ok(action)
    }
}
