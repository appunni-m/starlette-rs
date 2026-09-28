/// An ASGI connection scope type recognized by the core.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AsgiScopeKind {
    /// An HTTP request/response scope.
    Http,
    /// A WebSocket connection scope.
    WebSocket,
    /// An application lifespan scope.
    Lifespan,
    /// Any scope type outside the currently implemented slice.
    Other,
}

/// Classifies an ASGI scope type before the host dispatches loop-bound work.
///
/// Keeping this decision in Rust lets the Python package act only as the
/// required host-loop bridge for Python endpoints and lifespan context
/// managers.
#[must_use]
pub fn classify_scope(scope_type: &str) -> AsgiScopeKind {
    match scope_type {
        "http" => AsgiScopeKind::Http,
        "websocket" => AsgiScopeKind::WebSocket,
        "lifespan" => AsgiScopeKind::Lifespan,
        _ => AsgiScopeKind::Other,
    }
}
