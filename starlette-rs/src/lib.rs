//! Rust-native pieces for the Starlette replacement.
//!
//! The first implementation slice covers ordered HTTP route matching and
//! reverse path formatting with Starlette's built-in converters, plain-text
//! and bounded streaming responses, and the successful ASGI lifespan transition
//! sequence.
//! The native [`Starlette`] API composes routes with prebuilt responses and
//! exposes a narrow runtime-agnostic async call boundary for native callers.
//! The crate does not implement the full Starlette API or claim Python-package
//! parity.

// These package dependencies are used by the companion parity-adapter binary.
use libc as _;
use serde_json as _;
use sha2 as _;

mod application;
mod asgi;
mod connection;
mod exception_handlers;
mod file_response;
mod gzip;
mod lifespan;
mod mount;
mod request;
mod response;
mod route_table;
mod router_dispatch;
mod server_error;
mod staticfiles;
mod websocket;

pub use application::{
    ApplicationCallError, ApplicationError, ApplicationRoute, DispatchResult, HttpScope, Starlette,
};
pub use asgi::{AsgiScopeKind, classify_scope};
pub use connection::{ConnectionUrlError, connection_url};
pub use exception_handlers::ExceptionHandlerTable;
pub use file_response::{
    FileMetadata, FileResponse, FileResponseCall, FileResponseCallError, FileResponseCallInput,
    FileResponseCallStep, FileResponseError, FileResponseEvent, FileResponseOptions, FileStat,
    FileStatTimestamp,
};
pub use gzip::{
    DEFAULT_EXCLUDED_CONTENT_TYPES, GzipBodyOutput, GzipCompressionError, GzipCompressor,
    GzipConfig, GzipHeader, GzipResponder, GzipResponseStart,
};
pub use lifespan::{
    LifespanAction, LifespanError, LifespanOperation, LifespanPhase, LifespanState,
};
pub use mount::{
    Mount, MountChild, MountDispatchResult, MountDispatchTreeResult, MountError, MountScope,
    MountScopeExtension,
};
pub use request::{
    BodyProgress, Cookies, QueryParams, RequestBodyAccumulator, RequestBodyError, RequestHeaders,
    RequestStreamProgress, RequestStreamState, parse_cookie_header,
};
pub use response::{
    CookieOptions, DebugTracebackFrame, Response, ResponseCall, ResponseCallError,
    ResponseCallInput, ResponseCallStep, ResponseError, ResponseEvent, StreamingResponse,
    StreamingResponseCall, StreamingResponseCallError, StreamingResponseCallInput,
    StreamingResponseCallStep, StreamingResponseDisconnectCall,
    StreamingResponseDisconnectCallError, StreamingResponseDisconnectCallInput,
    StreamingResponseDisconnectCallStep, StreamingResponseDisconnectListener,
    StreamingResponseDisconnectListenerError, StreamingResponseDisconnectListenerInput,
    StreamingResponseDisconnectListenerStep, StreamingResponseDisconnectMessage,
    StreamingResponseEvent,
};
pub use route_table::{
    DetailedRouteMatch, PathConverter, PathParameterCapture, RouteError, RouteMatch, RouteTable,
};
pub use router_dispatch::{DispatchPlanError, HttpDispatchPlan, SupplementalRouteMatch};
pub use server_error::{ServerErrorPlan, ServerErrorPolicy, ServerErrorState};
pub use staticfiles::{
    StaticFile, StaticFiles, StaticFilesError, StaticFilesResponse, StaticFilesResponseFlow,
    StaticFilesResponseStep,
};
pub use websocket::{WebSocketState, WebSocketStateError, WebSocketStateMachine};
