//! Server-neutral WebSocket routes and application sessions.
//!
//! A host adapter supplies the parsed handshake offer and implements
//! [`NativeWebSocketDriver`] with semantic accept, receive, send, close, and
//! cancellation operations. HTTP upgrade negotiation, frame encoding, and
//! transport details remain with that host.

use std::{
    error::Error,
    fmt::{self, Display, Formatter},
    future::Future,
    pin::Pin,
    sync::Arc,
};

use bytes::Bytes;
use futures::future::{BoxFuture, Either, select};
use http::{Extensions, HeaderMap, Method, Uri, Version, request::Parts};

use crate::{DetailedRouteMatch, RouteError, RouteTable};

/// An error returned by the host's WebSocket transport adapter.
pub type NativeWebSocketTransportError = Box<dyn Error + Send + Sync + 'static>;

/// An application error returned by a native WebSocket route.
pub type NativeWebSocketApplicationError = Box<dyn Error + Send + Sync + 'static>;

type RouteFuture = Pin<Box<dyn Future<Output = Result<(), NativeWebSocketError>> + Send>>;
type RouteEndpoint = dyn Fn(NativeWebSocketSession) -> RouteFuture + Send + Sync;

/// Request-head data and the ordered subprotocol offers parsed by the host.
pub struct NativeWebSocketHandshake {
    parts: Parts,
    offered_subprotocols: Vec<String>,
}

impl NativeWebSocketHandshake {
    /// Builds handshake metadata from an HTTP request head and parsed offers.
    ///
    /// The host owns parsing the protocol's handshake headers. The supplied
    /// subprotocols retain their client offer order.
    #[must_use]
    pub fn from_parts<I, S>(parts: Parts, offered_subprotocols: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            parts,
            offered_subprotocols: offered_subprotocols.into_iter().map(Into::into).collect(),
        }
    }

    /// Returns the request method used by the host for this handshake.
    #[must_use]
    pub fn method(&self) -> &Method {
        &self.parts.method
    }

    /// Returns the complete request URI supplied by the host.
    #[must_use]
    pub fn uri(&self) -> &Uri {
        &self.parts.uri
    }

    /// Returns the negotiated HTTP version.
    #[must_use]
    pub const fn version(&self) -> Version {
        self.parts.version
    }

    /// Returns request headers without flattening duplicate values.
    #[must_use]
    pub fn headers(&self) -> &HeaderMap {
        &self.parts.headers
    }

    /// Returns request extensions supplied by the server or earlier layers.
    #[must_use]
    pub fn extensions(&self) -> &Extensions {
        &self.parts.extensions
    }

    /// Returns client subprotocol offers in their received order.
    #[must_use]
    pub fn offered_subprotocols(&self) -> &[String] {
        &self.offered_subprotocols
    }

    /// Splits the request head from the ordered offer list.
    #[must_use]
    pub fn into_parts(self) -> (Parts, Vec<String>) {
        (self.parts, self.offered_subprotocols)
    }
}

/// Application-selected handshake response metadata.
#[derive(Debug, Default)]
pub struct NativeWebSocketAcceptance {
    subprotocol: Option<String>,
    headers: HeaderMap,
}

impl NativeWebSocketAcceptance {
    /// Creates accepted handshake metadata.
    #[must_use]
    pub fn new(subprotocol: Option<String>, headers: HeaderMap) -> Self {
        Self {
            subprotocol,
            headers,
        }
    }

    /// Returns the selected subprotocol, if one was selected.
    #[must_use]
    pub fn subprotocol(&self) -> Option<&str> {
        self.subprotocol.as_deref()
    }

    /// Returns additional handshake response headers.
    #[must_use]
    pub fn headers(&self) -> &HeaderMap {
        &self.headers
    }

    /// Splits the selected protocol and headers for the host adapter.
    #[must_use]
    pub fn into_parts(self) -> (Option<String>, HeaderMap) {
        (self.subprotocol, self.headers)
    }
}

/// A text or binary WebSocket message.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeWebSocketMessage {
    /// A UTF-8 text message.
    Text(String),
    /// An owned binary message payload.
    Binary(Bytes),
}

/// An application-requested close, including its code and UTF-8 reason.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeWebSocketClose {
    code: u16,
    reason: String,
}

impl NativeWebSocketClose {
    /// Creates a close request with a protocol-usable close code.
    ///
    /// Close-code validation is semantic API validation; the host still owns
    /// encoding the close control frame and enforcing transport limits.
    ///
    /// # Errors
    ///
    /// Returns [`NativeWebSocketError::InvalidCloseCode`] for reserved or
    /// out-of-range codes.
    pub fn new(code: u16, reason: impl Into<String>) -> Result<Self, NativeWebSocketError> {
        if !is_usable_close_code(code) {
            return Err(NativeWebSocketError::InvalidCloseCode(code));
        }
        Ok(Self {
            code,
            reason: reason.into(),
        })
    }

    /// Creates a normal closure with code 1000.
    #[must_use]
    pub fn normal(reason: impl Into<String>) -> Self {
        Self {
            code: 1000,
            reason: reason.into(),
        }
    }

    /// Returns the close code.
    #[must_use]
    pub const fn code(&self) -> u16 {
        self.code
    }

    /// Returns the close reason.
    #[must_use]
    pub fn reason(&self) -> &str {
        &self.reason
    }
}

/// A close received from the peer. The code is absent for an unclean close.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeWebSocketPeerClose {
    /// Peer close code, if the host received one.
    pub code: Option<u16>,
    /// Peer close reason decoded by the host.
    pub reason: String,
}

/// One semantic event received from the host.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeWebSocketEvent {
    /// A text or binary data message.
    Message(NativeWebSocketMessage),
    /// The peer closed the session.
    PeerClosed(NativeWebSocketPeerClose),
}

/// The operations a host adapter must provide for one WebSocket session.
///
/// Implementations perform semantic operations only. The host remains
/// responsible for HTTP upgrade or extended CONNECT negotiation, WebSocket
/// frame parsing and serialization, and its transport-specific limits. Each
/// operation future may be dropped when cancellation wins and must leave the
/// host transport safe to discard or close. `cancelled` is a repeatable,
/// level-triggered signal: it must resolve once cancellation has been
/// requested, including when a future is created after that request. The
/// session creates and drops this future around individual operations, so
/// creating or dropping it must not consume or clear the cancellation signal.
pub trait NativeWebSocketDriver: Send + Sync {
    /// Accepts the connection with application-selected metadata.
    fn accept(
        &self,
        acceptance: NativeWebSocketAcceptance,
    ) -> BoxFuture<'_, Result<(), NativeWebSocketTransportError>>;

    /// Receives the next message or peer-close event.
    fn receive(&self)
    -> BoxFuture<'_, Result<NativeWebSocketEvent, NativeWebSocketTransportError>>;

    /// Sends one text or binary message.
    fn send(
        &self,
        message: NativeWebSocketMessage,
    ) -> BoxFuture<'_, Result<(), NativeWebSocketTransportError>>;

    /// Sends the application's close code and reason.
    fn close(
        &self,
        close: NativeWebSocketClose,
    ) -> BoxFuture<'_, Result<(), NativeWebSocketTransportError>>;

    /// Resolves when the host cancels this application session.
    ///
    /// This must be a sticky signal rather than a one-shot event receiver,
    /// because the session may create this future again for a later operation.
    fn cancelled(&self) -> BoxFuture<'_, ()>;
}

/// The current application-visible session phase.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeWebSocketState {
    /// The application has not accepted or closed the handshake.
    AwaitingAcceptance,
    /// The host is processing the acceptance operation.
    Accepting,
    /// The connection is accepted and may exchange messages.
    Open,
    /// The application has requested closure and the host is processing it.
    Closing,
    /// The peer or application has closed the session.
    Closed,
    /// A transport operation or host cancellation ended the session.
    Failed,
}

/// Errors crossing the native WebSocket application boundary.
#[derive(Debug)]
pub enum NativeWebSocketError {
    /// The operation is not valid for the current session phase.
    InvalidState {
        /// Name of the attempted operation.
        operation: &'static str,
        /// Session phase observed by the operation.
        state: NativeWebSocketState,
    },
    /// The application selected a protocol the client did not offer.
    UnofferedSubprotocol(String),
    /// The application selected a reserved or out-of-range close code.
    InvalidCloseCode(u16),
    /// The native router could not dispatch a registered route.
    Router(NativeWebSocketRouterError),
    /// The host adapter returned an operation error.
    Transport(NativeWebSocketTransportError),
    /// The route handler returned an application error.
    Application(NativeWebSocketApplicationError),
    /// The host cancelled the session while an operation was pending.
    Cancelled,
}

impl NativeWebSocketError {
    /// Wraps an application error for propagation from a route handler.
    #[must_use]
    pub fn application<E>(error: E) -> Self
    where
        E: Error + Send + Sync + 'static,
    {
        Self::Application(Box::new(error))
    }
}

impl Display for NativeWebSocketError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidState { operation, state } => {
                write!(formatter, "cannot {operation} while WebSocket is {state:?}")
            }
            Self::UnofferedSubprotocol(protocol) => {
                write!(formatter, "client did not offer subprotocol '{protocol}'")
            }
            Self::InvalidCloseCode(code) => {
                write!(formatter, "invalid WebSocket close code {code}")
            }
            Self::Router(error) => Display::fmt(error, formatter),
            Self::Transport(error) => write!(formatter, "WebSocket transport failed: {error}"),
            Self::Application(error) => write!(formatter, "WebSocket application failed: {error}"),
            Self::Cancelled => formatter.write_str("WebSocket application session was cancelled"),
        }
    }
}

impl Error for NativeWebSocketError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Transport(error) => Some(error.as_ref()),
            Self::Application(error) => Some(error.as_ref()),
            Self::Router(error) => Some(error),
            Self::InvalidState { .. }
            | Self::UnofferedSubprotocol(_)
            | Self::InvalidCloseCode(_)
            | Self::Cancelled => None,
        }
    }
}

/// An application session for one matched native WebSocket route.
pub struct NativeWebSocketSession {
    handshake: NativeWebSocketHandshake,
    path_params: Vec<(String, String)>,
    preferred_subprotocols: Vec<String>,
    driver: Arc<dyn NativeWebSocketDriver>,
    state: NativeWebSocketState,
}

impl NativeWebSocketSession {
    fn new(
        handshake: NativeWebSocketHandshake,
        path_params: Vec<(String, String)>,
        preferred_subprotocols: Vec<String>,
        driver: Arc<dyn NativeWebSocketDriver>,
    ) -> Self {
        Self {
            handshake,
            path_params,
            preferred_subprotocols,
            driver,
            state: NativeWebSocketState::AwaitingAcceptance,
        }
    }

    /// Returns the incoming handshake metadata.
    #[must_use]
    pub fn handshake(&self) -> &NativeWebSocketHandshake {
        &self.handshake
    }

    /// Returns captured path parameters in route declaration order.
    #[must_use]
    pub fn path_params(&self) -> &[(String, String)] {
        &self.path_params
    }

    /// Returns the route's server-preference order for subprotocols.
    #[must_use]
    pub fn preferred_subprotocols(&self) -> &[String] {
        &self.preferred_subprotocols
    }

    /// Returns the current application-visible phase.
    #[must_use]
    pub const fn state(&self) -> NativeWebSocketState {
        self.state
    }

    /// Accepts the handshake with the supplied selected protocol and headers.
    ///
    /// A selected protocol must occur in the client's parsed offer list.
    /// Duplicate offers are retained by the handshake, while matching is
    /// case-sensitive as required by the protocol token contract.
    pub async fn accept(
        &mut self,
        acceptance: NativeWebSocketAcceptance,
    ) -> Result<(), NativeWebSocketError> {
        self.ensure_state("accept", NativeWebSocketState::AwaitingAcceptance)?;
        if let Some(protocol) = acceptance.subprotocol() {
            if !self
                .handshake
                .offered_subprotocols()
                .iter()
                .any(|offered| offered == protocol)
            {
                return Err(NativeWebSocketError::UnofferedSubprotocol(
                    protocol.to_owned(),
                ));
            }
        }

        self.state = NativeWebSocketState::Accepting;
        let result = self.await_driver(self.driver.accept(acceptance)).await;
        self.finish_operation(&result, NativeWebSocketState::Open);
        result
    }

    /// Selects the first server-preferred protocol offered by the client.
    ///
    /// If there is no overlap, the handshake is accepted without a selected
    /// protocol. The server preference list is evaluated in declaration
    /// order; the client offer order does not override that preference.
    pub async fn accept_preferred(
        &mut self,
        headers: HeaderMap,
    ) -> Result<(), NativeWebSocketError> {
        let subprotocol = select_subprotocol(
            &self.preferred_subprotocols,
            self.handshake.offered_subprotocols(),
        );
        self.accept(NativeWebSocketAcceptance::new(subprotocol, headers))
            .await
    }

    /// Receives the next message or peer-close event.
    pub async fn receive(&mut self) -> Result<NativeWebSocketEvent, NativeWebSocketError> {
        self.ensure_state("receive", NativeWebSocketState::Open)?;
        let result = self.await_driver(self.driver.receive()).await;
        match &result {
            Ok(NativeWebSocketEvent::PeerClosed(_)) => {
                self.state = NativeWebSocketState::Closed;
            }
            Ok(NativeWebSocketEvent::Message(_)) => {}
            Err(_) => self.finish_operation(&result, NativeWebSocketState::Open),
        }
        result
    }

    /// Sends one text or binary message to the peer.
    pub async fn send(
        &mut self,
        message: NativeWebSocketMessage,
    ) -> Result<(), NativeWebSocketError> {
        self.ensure_state("send", NativeWebSocketState::Open)?;
        let result = self.await_driver(self.driver.send(message)).await;
        self.finish_operation(&result, NativeWebSocketState::Open);
        result
    }

    /// Requests closure with an application-selected code and reason.
    ///
    /// This may be called before accepting the handshake or after accepting it.
    /// A close requested before acceptance rejects the WebSocket handshake.
    pub async fn close(&mut self, close: NativeWebSocketClose) -> Result<(), NativeWebSocketError> {
        if !matches!(
            self.state,
            NativeWebSocketState::AwaitingAcceptance | NativeWebSocketState::Open
        ) {
            return Err(NativeWebSocketError::InvalidState {
                operation: "close",
                state: self.state,
            });
        }
        self.state = NativeWebSocketState::Closing;
        let result = self.await_driver(self.driver.close(close)).await;
        self.finish_operation(&result, NativeWebSocketState::Closed);
        result
    }

    fn ensure_state(
        &self,
        operation: &'static str,
        expected: NativeWebSocketState,
    ) -> Result<(), NativeWebSocketError> {
        if self.state == expected {
            Ok(())
        } else {
            Err(NativeWebSocketError::InvalidState {
                operation,
                state: self.state,
            })
        }
    }

    async fn await_driver<T>(
        &self,
        operation: BoxFuture<'_, Result<T, NativeWebSocketTransportError>>,
    ) -> Result<T, NativeWebSocketError> {
        // Poll cancellation first so that a simultaneously-ready cancellation
        // signal takes precedence over a completed host operation.
        match select(self.driver.cancelled(), operation).await {
            Either::Left(((), _)) => Err(NativeWebSocketError::Cancelled),
            Either::Right((result, _)) => result.map_err(NativeWebSocketError::Transport),
        }
    }

    fn finish_operation<T>(
        &mut self,
        result: &Result<T, NativeWebSocketError>,
        success_state: NativeWebSocketState,
    ) {
        self.state = match result {
            Ok(_) => success_state,
            Err(NativeWebSocketError::Cancelled | NativeWebSocketError::Transport(_)) => {
                NativeWebSocketState::Failed
            }
            Err(
                NativeWebSocketError::InvalidState { .. }
                | NativeWebSocketError::UnofferedSubprotocol(_)
                | NativeWebSocketError::InvalidCloseCode(_)
                | NativeWebSocketError::Router(_)
                | NativeWebSocketError::Application(_),
            ) => self.state,
        };
    }
}

/// An ordered native WebSocket route.
pub struct NativeWebSocketRoute {
    path: String,
    preferred_subprotocols: Vec<String>,
    endpoint: Arc<RouteEndpoint>,
}

impl NativeWebSocketRoute {
    /// Creates a route from a path, server-preference order, and handler.
    ///
    /// Route matching uses the same path syntax and insertion ordering as
    /// [`RouteTable`]. A route handles any handshake method recognized by the
    /// host; the router matches paths only and does not negotiate the upgrade.
    #[must_use]
    pub fn new<P, I, S, F, Fut>(path: P, preferred_subprotocols: I, endpoint: F) -> Self
    where
        P: Into<String>,
        I: IntoIterator<Item = S>,
        S: Into<String>,
        F: Fn(NativeWebSocketSession) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<(), NativeWebSocketError>> + Send + 'static,
    {
        let endpoint = Arc::new(move |session| Box::pin(endpoint(session)) as RouteFuture);
        Self {
            path: path.into(),
            preferred_subprotocols: preferred_subprotocols.into_iter().map(Into::into).collect(),
            endpoint,
        }
    }
}

/// An ordered path router for Rust-native WebSocket routes.
#[derive(Clone)]
pub struct NativeWebSocketRouter {
    routes: RouteTable,
    endpoints: Vec<(Vec<String>, Arc<RouteEndpoint>)>,
}

impl NativeWebSocketRouter {
    /// Builds a router from routes in dispatch order.
    ///
    /// # Errors
    ///
    /// Returns [`NativeWebSocketRouterError::RouteRegistration`] when a path
    /// cannot be represented by the shared route table.
    pub fn new(
        routes: impl IntoIterator<Item = NativeWebSocketRoute>,
    ) -> Result<Self, NativeWebSocketRouterError> {
        let mut table = RouteTable::new();
        let mut endpoints = Vec::new();
        for route in routes {
            // Empty methods make RouteTable perform path-only matching. The
            // host's HTTP version determines which handshake method applies.
            table
                .add_route(route.path, std::iter::empty::<String>())
                .map_err(NativeWebSocketRouterError::RouteRegistration)?;
            endpoints.push((route.preferred_subprotocols, route.endpoint));
        }
        Ok(Self {
            routes: table,
            endpoints,
        })
    }

    /// Dispatches one host-parsed handshake to the first matching route.
    ///
    /// A path miss returns [`NativeWebSocketDispatch::NoRoute`] so the host
    /// can choose its own pre-upgrade HTTP response. Dropping this future
    /// cancels the route handler future using normal Rust future-drop
    /// semantics; a live handler can also observe host cancellation through
    /// its session operations.
    pub async fn dispatch(
        &self,
        handshake: NativeWebSocketHandshake,
        driver: Arc<dyn NativeWebSocketDriver>,
    ) -> Result<NativeWebSocketDispatch, NativeWebSocketError> {
        let route_match = self.routes.matches_detailed(handshake.uri().path(), "");
        let DetailedRouteMatch::Matched {
            route_index,
            path_params,
        } = route_match
        else {
            return Ok(NativeWebSocketDispatch::NoRoute);
        };

        let Some((preferred_subprotocols, endpoint)) = self.endpoints.get(route_index) else {
            return Err(NativeWebSocketError::Router(
                NativeWebSocketRouterError::MissingEndpoint(route_index),
            ));
        };
        let session = NativeWebSocketSession::new(
            handshake,
            path_params,
            preferred_subprotocols.clone(),
            driver,
        );
        endpoint(session).await?;
        Ok(NativeWebSocketDispatch::Completed { route_index })
    }
}

/// The dispatch result returned to a host adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeWebSocketDispatch {
    /// No route matched; the host still owns the pre-upgrade response.
    NoRoute,
    /// The handler for this route returned successfully.
    Completed {
        /// Zero-based insertion index of the route that handled the session.
        route_index: usize,
    },
}

/// A registration error from the native WebSocket router.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeWebSocketRouterError {
    /// A route path could not be registered.
    RouteRegistration(RouteError),
    /// Router state did not contain the endpoint for a matched route.
    MissingEndpoint(usize),
}

impl Display for NativeWebSocketRouterError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::RouteRegistration(error) => {
                write!(formatter, "WebSocket route registration failed: {error}")
            }
            Self::MissingEndpoint(index) => {
                write!(formatter, "WebSocket route {index} has no endpoint")
            }
        }
    }
}

impl Error for NativeWebSocketRouterError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) => Some(error),
            Self::MissingEndpoint(_) => None,
        }
    }
}

/// Selects the first server preference also present in the client offers.
#[must_use]
pub fn select_subprotocol(preferred: &[String], offered: &[String]) -> Option<String> {
    preferred
        .iter()
        .find(|protocol| offered.iter().any(|offer| offer == *protocol))
        .cloned()
}

fn is_usable_close_code(code: u16) -> bool {
    (1000..=4999).contains(&code)
        && !matches!(code, 1004 | 1005 | 1006 | 1015)
        && !(1016..=2999).contains(&code)
}
