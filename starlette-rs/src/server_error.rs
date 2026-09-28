//! Rust-owned decisions for Starlette's outer server-error middleware.

/// The response strategy selected for an unhandled HTTP exception.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ServerErrorPlan {
    /// Render a traceback as HTML.
    DebugHtml,
    /// Render a traceback as plain text.
    DebugText,
    /// Invoke the registered Python error handler at the runtime boundary.
    CustomHandler(usize),
    /// Send Starlette's default plain-text 500 response.
    Default,
}

impl ServerErrorPlan {
    /// Returns the stable Python-facing plan name and optional handler index.
    #[must_use]
    pub const fn as_parts(self) -> (&'static str, Option<usize>) {
        match self {
            Self::DebugHtml => ("debug-html", None),
            Self::DebugText => ("debug-text", None),
            Self::CustomHandler(index) => ("custom-handler", Some(index)),
            Self::Default => ("default", None),
        }
    }
}

/// Selects a 500 response strategy without holding or invoking Python values.
///
/// Starlette normalizes both a `500` key and the `Exception` class key into one
/// outer error-handler slot while it walks the configured mapping. Registering
/// either key therefore replaces the previous value, preserving input order.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ServerErrorPolicy {
    debug: bool,
    handler_index: Option<usize>,
}

impl ServerErrorPolicy {
    /// Creates an error policy with the supplied debug setting.
    #[must_use]
    pub const fn new(debug: bool) -> Self {
        Self {
            debug,
            handler_index: None,
        }
    }

    /// Registers an outer server-error handler.
    ///
    /// Call this once for each `500` or `Exception` registration, in the
    /// original mapping order. The last registration wins, matching
    /// `Starlette.build_middleware_stack`.
    pub fn register_handler(&mut self, handler_index: usize) -> Option<usize> {
        self.handler_index.replace(handler_index)
    }

    /// Selects debug HTML, debug text, the custom handler, or the default 500.
    ///
    /// In debug mode the HTML path is selected only when the byte sequence
    /// `text/html` occurs literally in the first `Accept` field. This matches
    /// Starlette's substring check rather than parsing media ranges.
    #[must_use]
    pub fn plan(&self, accept: Option<&[u8]>) -> ServerErrorPlan {
        if self.debug {
            return if accept.is_some_and(|value| contains_subslice(value, b"text/html")) {
                ServerErrorPlan::DebugHtml
            } else {
                ServerErrorPlan::DebugText
            };
        }

        self.handler_index
            .map_or(ServerErrorPlan::Default, ServerErrorPlan::CustomHandler)
    }
}

/// Tracks whether the wrapped ASGI app has started its HTTP response.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ServerErrorState {
    response_started: bool,
}

impl ServerErrorState {
    /// Creates a state with no response started.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            response_started: false,
        }
    }

    /// Records an ASGI send message and returns the current start state.
    ///
    /// Only `http.response.start` affects the state. Calling this for other
    /// message types leaves the state unchanged.
    pub fn observe_send(&mut self, message_type: &str) -> bool {
        if message_type == "http.response.start" {
            self.response_started = true;
        }
        self.response_started
    }

    /// Returns whether an inner response-start message has been observed.
    #[must_use]
    pub const fn response_started(&self) -> bool {
        self.response_started
    }

    /// Returns whether the generated server-error response should be sent.
    #[must_use]
    pub const fn should_send_response(&self) -> bool {
        !self.response_started
    }
}

fn contains_subslice(haystack: &[u8], needle: &[u8]) -> bool {
    haystack
        .windows(needle.len())
        .any(|window| window == needle)
}
