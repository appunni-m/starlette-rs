//! Rust-native pieces for the Starlette replacement.
//!
//! The crate provides a Rust-native API alongside the Python compatibility
//! package. Its server-neutral HTTP service, WebSocket session, and lifespan
//! APIs leave transport framing and executor ownership to their host adapters.
//! The crate also contains shared routing, request, response, middleware, and
//! protocol primitives used by the compatibility implementation. The current
//! implementation does not claim full Starlette compatibility.

// These package dependencies are used by the companion parity-adapter binary.
#[cfg(unix)]
use libc as _;
use serde_json as _;
use sha2 as _;

mod application;
mod asgi;
mod comma_separated_strings;
mod connection;
mod exception_handlers;
mod file_response;
mod form_data;
mod gzip;
mod headers;
mod host;
mod lifespan;
mod mount;
mod multi_dict;
mod multipart;
mod named_route;
mod named_route_table;
mod named_router;
mod native_lifespan;
mod native_service;
mod native_websocket;
mod python_float;
mod request;
mod response;
mod route_table;
mod router_dispatch;
mod server_error;
mod sessions;
mod staticfiles;
mod websocket;

pub use application::{
    ApplicationCallError, ApplicationError, ApplicationRoute, DispatchResult, HttpScope, Starlette,
};
pub use asgi::{AsgiScopeKind, classify_scope};
pub use comma_separated_strings::{
    CommaSeparatedStrings, CommaSeparatedStringsParseError, PythonCodePointStrings,
};
pub use connection::{ConnectionUrlError, connection_url, connection_url_with_port_text};
pub use exception_handlers::ExceptionHandlerTable;
#[cfg(feature = "fault-contract")]
#[doc(hidden)]
pub use file_response::fault_contract_fail_next_random_boundary;
pub use file_response::{
    FileMetadata, FileResponse, FileResponseCall, FileResponseCallError, FileResponseCallInput,
    FileResponseCallStep, FileResponseError, FileResponseEvent, FileResponseHeaderViews,
    FileResponseOptions, FileStat, FileStatTimestamp, FileTimestamp,
};
pub use form_data::{FormData, FormDataParseError};
pub use gzip::{
    DEFAULT_EXCLUDED_CONTENT_TYPES, GzipBodyOutput, GzipCompressionError, GzipCompressor,
    GzipConfig, GzipHeader, GzipResponder, GzipResponseStart,
};
pub use headers::{Headers, MutableHeaders};
pub use host::{HostPattern, HostPatternError, HostUrlPath};
pub use lifespan::{
    LifespanAction, LifespanError, LifespanOperation, LifespanPhase, LifespanState,
};
pub use mount::{
    Mount, MountChild, MountDispatchResult, MountDispatchTreeResult, MountError, MountScope,
    MountScopeExtension,
};
pub use multi_dict::MultiDict;
pub use multipart::{
    MultipartFormEvent, MultipartFormParseError, MultipartFormParser, MultipartPart,
    multipart_boundary, parse_multipart_form,
};
pub use named_route::NamedRoute;
pub use named_route_table::{NamedRouteError, NamedRouteTable, RouteUrlPath};
pub use named_router::{NamedHost, NamedMount, NamedRouter, NamedRouterError, NamedRouterRoute};
pub use native_lifespan::{
    ActiveNativeLifespan, NativeLifespan, NativeLifespanBuilder, NativeLifespanError,
    NativeLifespanHookError, NativeLifespanHookFailure, NativeLifespanState,
    NativeLifespanStateError,
};
pub use native_service::{
    NativeApplication, NativeApplicationChild, NativeApplicationError, NativeBodyError,
    NativeHostApplication, NativeHostRoute, NativeHttpResponse, NativeMount, NativeRequest,
    NativeRequestBody, NativeRequestScope, NativeResponseBody, NativeResponseConversionError,
    NativeRoute, box_native_body, native_body,
};
pub use native_websocket::{
    NativeWebSocketAcceptance, NativeWebSocketApplicationError, NativeWebSocketClose,
    NativeWebSocketDispatch, NativeWebSocketDriver, NativeWebSocketError, NativeWebSocketEvent,
    NativeWebSocketHandshake, NativeWebSocketMessage, NativeWebSocketPeerClose,
    NativeWebSocketRoute, NativeWebSocketRouter, NativeWebSocketRouterError,
    NativeWebSocketSession, NativeWebSocketState, NativeWebSocketTransportError,
    select_subprotocol,
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
    StreamingResponseEvent, StreamingResponseStream,
};
pub use route_table::{
    CustomPathConverter, CustomPathConverterRegistry, DetailedRouteMatch, PathConverter,
    PathParameterCapture, PathParameterValue, RouteError, RouteMatch, RouteTable,
};
pub use router_dispatch::{DispatchPlanError, HttpDispatchPlan, SupplementalRouteMatch};
pub use server_error::{ServerErrorPlan, ServerErrorPolicy, ServerErrorState};
pub use sessions::{
    SessionSignatureError, timestamp_sign, timestamp_unsign, timestamp_unsign_with_timestamp,
    timestamp_unsign_with_timestamp_bytes,
};
pub use staticfiles::{
    StaticFile, StaticFiles, StaticFilesError, StaticFilesResponse, StaticFilesResponseFlow,
    StaticFilesResponseStep, is_not_modified_headers, not_modified_headers,
};
pub use websocket::{WebSocketState, WebSocketStateError, WebSocketStateMachine};
