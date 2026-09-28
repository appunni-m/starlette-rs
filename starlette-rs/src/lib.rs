//! Rust-native pieces for the Starlette replacement.
//!
//! The first implementation slice covers ordered HTTP route matching and
//! reverse path formatting with Starlette's built-in converters, a plain-text
//! response, and the successful ASGI lifespan transition sequence.
//! The native [`Starlette`] API composes routes with prebuilt responses and
//! exposes a narrow runtime-agnostic async call boundary for native callers.
//! The crate does not implement the full Starlette API or claim Python-package
//! parity.

// These package dependencies are used by the companion parity-adapter binary.
use serde_json as _;
use sha2 as _;

mod application;
mod asgi;
mod connection;
mod exception_handlers;
mod gzip;
mod lifespan;
mod request;
mod response;
mod route_table;
mod server_error;
mod websocket;

pub use application::{
    ApplicationCallError, ApplicationError, ApplicationRoute, DispatchResult, HttpScope, Starlette,
};
pub use asgi::{AsgiScopeKind, classify_scope};
pub use connection::{ConnectionUrlError, connection_url};
pub use exception_handlers::ExceptionHandlerTable;
pub use gzip::{
    DEFAULT_EXCLUDED_CONTENT_TYPES, GzipBodyOutput, GzipCompressionError, GzipCompressor,
    GzipConfig, GzipHeader, GzipResponder, GzipResponseStart,
};
pub use lifespan::{
    LifespanAction, LifespanError, LifespanOperation, LifespanPhase, LifespanState,
};
pub use request::{
    BodyProgress, Cookies, QueryParams, RequestBodyAccumulator, RequestBodyError, RequestHeaders,
    parse_cookie_header,
};
pub use response::{DebugTracebackFrame, Response, ResponseError, ResponseEvent};
pub use route_table::{DetailedRouteMatch, RouteError, RouteMatch, RouteTable};
pub use server_error::{ServerErrorPlan, ServerErrorPolicy, ServerErrorState};
pub use websocket::{WebSocketState, WebSocketStateError, WebSocketStateMachine};
