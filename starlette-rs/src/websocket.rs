//! Rust-owned ASGI WebSocket protocol state.
//!
//! The host remains responsible for receiving and sending ASGI messages. It
//! passes each message type through this state machine before the send call,
//! then calls [`WebSocketStateMachine::send_failed`] when a send in the
//! connected branch raises an `OSError`. This preserves Starlette's ordering
//! around asynchronous host calls without moving Python event-loop work into
//! Rust.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

/// The state of one side of an ASGI WebSocket connection.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WebSocketState {
    /// No WebSocket handshake message has been observed on this side.
    Connecting,
    /// The WebSocket handshake is established.
    Connected,
    /// A disconnect or close message has completed this side of the protocol.
    Disconnected,
    /// The application is returning an HTTP denial response over WebSocket.
    Response,
}

/// A state-transition error with Starlette-compatible runtime error wording.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WebSocketStateError {
    message: String,
}

impl WebSocketStateError {
    fn new(message: String) -> Self {
        Self { message }
    }

    /// Returns the error message used by Starlette's WebSocket state machine.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for WebSocketStateError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for WebSocketStateError {}

/// Validates ASGI WebSocket message order for the client and application.
///
/// The two sides have independent states, matching Starlette's
/// `client_state` and `application_state`. Call [`receive`](Self::receive)
/// after the host successfully receives an ASGI event. Call
/// [`begin_send`](Self::begin_send) before invoking the host's send callable;
/// the returned boolean tells the host whether an `OSError` from that send
/// must become an abnormal disconnect with code 1006. In that case, call
/// [`send_failed`](Self::send_failed) before surfacing the disconnect.
///
/// ```
/// use starlette_rs::{WebSocketState, WebSocketStateMachine};
///
/// let mut state = WebSocketStateMachine::new();
/// state.receive("websocket.connect").expect("connect message");
/// let catches_os_error = state
///     .begin_send("websocket.accept", false)
///     .expect("accept message");
/// assert!(!catches_os_error);
/// assert_eq!(state.application_state(), WebSocketState::Connected);
/// ```
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WebSocketStateMachine {
    client_state: WebSocketState,
    application_state: WebSocketState,
}

impl Default for WebSocketStateMachine {
    fn default() -> Self {
        Self::new()
    }
}

impl WebSocketStateMachine {
    /// Creates a state machine with both sides awaiting their first message.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            client_state: WebSocketState::Connecting,
            application_state: WebSocketState::Connecting,
        }
    }

    /// Returns the state of messages received from the ASGI server.
    #[must_use]
    pub const fn client_state(&self) -> WebSocketState {
        self.client_state
    }

    /// Sets the state used to validate messages received from the server.
    ///
    /// This mirrors Starlette's assignable `WebSocket.client_state` attribute.
    pub fn set_client_state(&mut self, state: WebSocketState) {
        self.client_state = state;
    }

    /// Returns the state of messages sent to the ASGI server.
    #[must_use]
    pub const fn application_state(&self) -> WebSocketState {
        self.application_state
    }

    /// Sets the state used to validate messages sent to the server.
    ///
    /// This mirrors Starlette's assignable `WebSocket.application_state` attribute.
    pub fn set_application_state(&mut self, state: WebSocketState) {
        self.application_state = state;
    }

    /// Validates and records an ASGI event received from the server.
    ///
    /// A successful `websocket.connect` moves the client side to
    /// [`WebSocketState::Connected`]. In that state, `websocket.receive`
    /// leaves it connected and `websocket.disconnect` moves it to
    /// [`WebSocketState::Disconnected`].
    ///
    /// # Errors
    ///
    /// Returns an error containing Starlette's exact runtime error wording
    /// when the message type is invalid for the current client state or after
    /// a disconnect has been received.
    pub fn receive(&mut self, message_type: &str) -> Result<(), WebSocketStateError> {
        match self.client_state {
            WebSocketState::Connecting => {
                if message_type != "websocket.connect" {
                    return Err(WebSocketStateError::new(format!(
                        "Expected ASGI message \"websocket.connect\", but got {}",
                        python_string_repr(message_type)
                    )));
                }
                self.client_state = WebSocketState::Connected;
            }
            WebSocketState::Connected => match message_type {
                "websocket.receive" => {}
                "websocket.disconnect" => {
                    self.client_state = WebSocketState::Disconnected;
                }
                _ => {
                    return Err(WebSocketStateError::new(format!(
                        "Expected ASGI message \"websocket.receive\" or \"websocket.disconnect\", but got {}",
                        python_string_repr(message_type)
                    )));
                }
            },
            WebSocketState::Disconnected | WebSocketState::Response => {
                return Err(WebSocketStateError::new(
                    "Cannot call \"receive\" once a disconnect message has been received."
                        .to_owned(),
                ));
            }
        }
        Ok(())
    }

    /// Validates and records an ASGI event before the host invokes its send
    /// callable.
    ///
    /// `more_body` is consulted only for
    /// `websocket.http.response.body`: a false value completes the denial
    /// response and moves the application side to
    /// [`WebSocketState::Disconnected`]. The returned boolean is true only
    /// for sends started while the application side was connected. Starlette
    /// catches an `OSError` from that branch, marks the application side
    /// disconnected, and raises `WebSocketDisconnect(code=1006)`; other send
    /// branches let the host's original error propagate.
    ///
    /// # Errors
    ///
    /// Returns an error containing Starlette's exact runtime error wording
    /// when the message type is invalid for the current application state or
    /// after a close has been sent.
    pub fn begin_send(
        &mut self,
        message_type: &str,
        more_body: bool,
    ) -> Result<bool, WebSocketStateError> {
        match self.application_state {
            WebSocketState::Connecting => {
                if !matches!(
                    message_type,
                    "websocket.accept" | "websocket.close" | "websocket.http.response.start"
                ) {
                    return Err(WebSocketStateError::new(format!(
                        "Expected ASGI message \"websocket.accept\", \"websocket.close\" or \"websocket.http.response.start\", but got {}",
                        python_string_repr(message_type)
                    )));
                }
                self.application_state = match message_type {
                    "websocket.close" => WebSocketState::Disconnected,
                    "websocket.http.response.start" => WebSocketState::Response,
                    _ => WebSocketState::Connected,
                };
                Ok(false)
            }
            WebSocketState::Connected => {
                if !matches!(message_type, "websocket.send" | "websocket.close") {
                    return Err(WebSocketStateError::new(format!(
                        "Expected ASGI message \"websocket.send\" or \"websocket.close\", but got {}",
                        python_string_repr(message_type)
                    )));
                }
                if message_type == "websocket.close" {
                    self.application_state = WebSocketState::Disconnected;
                }
                Ok(true)
            }
            WebSocketState::Response => {
                if message_type != "websocket.http.response.body" {
                    return Err(WebSocketStateError::new(format!(
                        "Expected ASGI message \"websocket.http.response.body\", but got {}",
                        python_string_repr(message_type)
                    )));
                }
                if !more_body {
                    self.application_state = WebSocketState::Disconnected;
                }
                Ok(false)
            }
            WebSocketState::Disconnected => Err(WebSocketStateError::new(
                "Cannot call \"send\" once a close message has been sent.".to_owned(),
            )),
        }
    }

    /// Records the connected-branch `OSError` handling performed by Starlette.
    ///
    /// Call this after [`begin_send`](Self::begin_send) returned `true` and
    /// the host send callable raised an `OSError`. The host should then surface
    /// a WebSocket disconnect with close code 1006.
    pub fn send_failed(&mut self) {
        self.application_state = WebSocketState::Disconnected;
    }
}

fn python_string_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut representation = String::with_capacity(value.len() + 2);
    representation.push(quote);
    for character in value.chars() {
        match character {
            '\\' => representation.push_str("\\\\"),
            '\n' => representation.push_str("\\n"),
            '\r' => representation.push_str("\\r"),
            '\t' => representation.push_str("\\t"),
            character if character == quote => {
                representation.push('\\');
                representation.push(character);
            }
            character if character.is_control() => {
                use fmt::Write as _;
                let _ = write!(representation, "\\x{:02x}", u32::from(character));
            }
            character => representation.push(character),
        }
    }
    representation.push(quote);
    representation
}
