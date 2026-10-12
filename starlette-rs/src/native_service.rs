//! Additive, server-neutral Tower service for Rust-native HTTP routes.
//!
//! This surface accepts `http::Request` values with any `http_body::Body`
//! implementation. Request and response payloads stay streaming; the module
//! boxes body types once at the dynamic route-handler boundary.

use std::{
    error::Error,
    fmt::{self, Display, Formatter},
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

use bytes::Bytes;
use http::{
    Extensions, HeaderMap, HeaderName, HeaderValue, Method, Request, Response as HttpResponse, Uri,
    Version, header::InvalidHeaderName, request::Parts, status::InvalidStatusCode,
};
use http_body::Body;
use http_body_util::{BodyExt, Full, combinators::UnsyncBoxBody};
use tower_layer::Layer;
use tower_service::Service;

use crate::{DetailedRouteMatch, Response, ResponseError, RouteError, RouteTable};

/// A boxed source error carried by native HTTP bodies and endpoint failures.
///
/// Body boxing retains the concrete `http_body::Body::Error` type for
/// `downcast_ref` inspection; it does not convert the error to text.
pub type NativeBodyError = Box<dyn Error + Send + Sync + 'static>;

/// A pull-based request body passed to a native Starlette endpoint.
///
/// [`NativeApplication`] does not poll this body while routing or constructing
/// the endpoint future. The endpoint or a Tower layer is the first consumer;
/// each call to [`Body::poll_frame`] advances the source according to that
/// body's implementation. Dropping the body drops the boxed source.
pub type NativeRequestBody = UnsyncBoxBody<Bytes, NativeBodyError>;

/// A pull-based response body returned by a native Starlette endpoint.
///
/// The application returns this body without polling it. The service consumer
/// or an outer Tower layer drives it by requesting frames. Dropping the body
/// drops the boxed source; transport-specific cancellation is outside this
/// server-neutral API.
pub type NativeResponseBody = UnsyncBoxBody<Bytes, NativeBodyError>;

/// A native HTTP response returned by a route endpoint.
pub type NativeHttpResponse = HttpResponse<NativeResponseBody>;

type EndpointFuture =
    Pin<Box<dyn Future<Output = Result<NativeHttpResponse, NativeApplicationError>> + Send>>;
type Endpoint = dyn Fn(NativeRequest) -> EndpointFuture + Send + Sync;

/// Boxes a body at the dynamic endpoint boundary without polling or collecting
/// its frames.
///
/// The body is polled only when a consumer asks for a frame. Each frame moves
/// through the box, and each data frame moves its `Bytes` value; this function
/// does not read ahead, collect frames, or copy payload bytes. Dropping the
/// returned body drops the wrapped body.
pub fn box_native_body<B>(body: B) -> UnsyncBoxBody<Bytes, NativeBodyError>
where
    B: Body<Data = Bytes> + Send + 'static,
    B::Error: Error + Send + Sync + 'static,
{
    body.map_err(|error| Box::new(error) as NativeBodyError)
        .boxed_unsync()
}

/// Creates a single-frame response body from the supplied bytes.
///
/// Passing an existing [`Bytes`] moves its handle without copying the payload.
/// Other `Into<Bytes>` conversions may allocate or copy according to the
/// source type's conversion implementation.
#[must_use]
pub fn native_body(bytes: impl Into<Bytes>) -> NativeResponseBody {
    box_native_body(Full::new(bytes.into()))
}

/// Request data and the converted route parameters passed to an endpoint.
pub struct NativeRequest {
    parts: Parts,
    body: NativeRequestBody,
    path_params: Vec<(String, String)>,
}

impl NativeRequest {
    /// Returns the HTTP method.
    #[must_use]
    pub fn method(&self) -> &Method {
        &self.parts.method
    }

    /// Returns the original request URI, including its query string.
    #[must_use]
    pub fn uri(&self) -> &Uri {
        &self.parts.uri
    }

    /// Returns the URI path used for route matching, preserving percent escapes.
    #[must_use]
    pub fn path(&self) -> &str {
        self.parts.uri.path()
    }

    /// Returns the query component without its leading question mark.
    #[must_use]
    pub fn query(&self) -> Option<&str> {
        self.parts.uri.query()
    }

    /// Returns the negotiated HTTP version.
    #[must_use]
    pub const fn version(&self) -> Version {
        self.parts.version
    }

    /// Returns the request headers without flattening duplicate field values.
    #[must_use]
    pub fn headers(&self) -> &HeaderMap {
        &self.parts.headers
    }

    /// Returns request extensions supplied by the server or earlier middleware.
    #[must_use]
    pub fn extensions(&self) -> &Extensions {
        &self.parts.extensions
    }

    /// Returns mutable request extensions for endpoint-owned metadata.
    pub fn extensions_mut(&mut self) -> &mut Extensions {
        &mut self.parts.extensions
    }

    /// Returns the route parameters in the order declared by the route.
    #[must_use]
    pub fn path_params(&self) -> &[(String, String)] {
        &self.path_params
    }

    /// Returns the request body for incremental, pull-based polling.
    ///
    /// The application does not poll the body before passing this request to
    /// the endpoint. Each data or trailer frame is consumed when polled.
    /// Dropping the body drops its source; any transport cancellation beyond
    /// that drop is provided by the body implementation or server adapter.
    pub fn body_mut(&mut self) -> &mut NativeRequestBody {
        &mut self.body
    }

    /// Splits the request head, streaming body, and route parameters.
    #[must_use]
    pub fn into_parts(self) -> (Parts, NativeRequestBody, Vec<(String, String)>) {
        (self.parts, self.body, self.path_params)
    }
}

/// A route backed by an asynchronous Rust endpoint.
///
/// Applications can be cloned across connections, so endpoint closures must
/// be `Sync` and may be called concurrently. Each returned future is `Send`;
/// dropping it drops the endpoint future and any request body it still owns,
/// using normal Rust future-drop semantics.
pub struct NativeRoute {
    path: String,
    methods: Vec<String>,
    endpoint: Arc<Endpoint>,
}

impl NativeRoute {
    /// Creates a native route from a path, accepted methods, and endpoint.
    ///
    /// Route ordering, path conversion, and GET-to-HEAD behavior use the same
    /// rules as [`RouteTable`]. The endpoint is shared by cloned applications.
    #[must_use]
    pub fn new<P, M, S, F, Fut>(path: P, methods: M, endpoint: F) -> Self
    where
        P: Into<String>,
        M: IntoIterator<Item = S>,
        S: AsRef<str>,
        F: Fn(NativeRequest) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<NativeHttpResponse, NativeApplicationError>> + Send + 'static,
    {
        let endpoint = Arc::new(move |request| Box::pin(endpoint(request)) as EndpointFuture);
        Self {
            path: path.into(),
            methods: methods
                .into_iter()
                .map(|method| method.as_ref().to_owned())
                .collect(),
            endpoint,
        }
    }
}

/// A server-neutral Starlette route application implementing Tower `Service`.
///
/// The service is immediately ready and routes each request when `call` is
/// invoked. It does not poll the request body during routing or poll the
/// response body before returning the response. Endpoints and outer Tower
/// layers control when they poll bodies, so `http_body::Body` demand propagates
/// through this service without framework read-ahead. Cloned applications
/// share their immutable route table and endpoint closures. It does not create
/// a runtime; its caller supplies the executor.
#[derive(Clone)]
pub struct NativeApplication {
    routes: RouteTable,
    endpoints: Vec<Arc<Endpoint>>,
}

impl NativeApplication {
    /// Builds the application from ordered native routes.
    ///
    /// # Errors
    ///
    /// Returns [`NativeApplicationError::RouteRegistration`] if any route
    /// cannot be represented by the shared route table.
    pub fn new(
        routes: impl IntoIterator<Item = NativeRoute>,
    ) -> Result<Self, NativeApplicationError> {
        let mut table = RouteTable::new();
        let mut endpoints = Vec::new();
        for route in routes {
            table
                .add_route(route.path, route.methods)
                .map_err(NativeApplicationError::RouteRegistration)?;
            endpoints.push(route.endpoint);
        }
        Ok(Self {
            routes: table,
            endpoints,
        })
    }

    /// Wraps this application in a Tower middleware layer.
    ///
    /// Layers compose in the standard Tower order: the outermost layer sees
    /// the request first and the response last. Apply layers from the
    /// innermost service outward when constructing the application stack.
    #[must_use]
    pub fn layer<L>(self, layer: L) -> L::Service
    where
        L: Layer<Self>,
    {
        layer.layer(self)
    }
}

impl<B> Service<Request<B>> for NativeApplication
where
    B: Body<Data = Bytes> + Send + 'static,
    B::Error: Error + Send + Sync + 'static,
{
    type Response = NativeHttpResponse;
    type Error = NativeApplicationError;
    type Future = EndpointFuture;

    fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, request: Request<B>) -> Self::Future {
        let path = request.uri().path();
        let method = request.method().as_str();
        let route_match = self.routes.matches_detailed(path, method);
        match route_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            } => {
                let Some(endpoint) = self.endpoints.get(route_index).cloned() else {
                    return Box::pin(async move {
                        Err(NativeApplicationError::MissingEndpoint { route_index })
                    });
                };
                let (parts, body) = request.into_parts();
                let request = NativeRequest {
                    parts,
                    body: box_native_body(body),
                    path_params,
                };
                endpoint(request)
            }
            fallback @ (DetailedRouteMatch::MethodNotAllowed { .. }
            | DetailedRouteMatch::NotFound) => {
                let response = fallback
                    .fallback_response()
                    .map_err(NativeApplicationError::FallbackResponse)
                    .and_then(|response| {
                        response.ok_or(NativeApplicationError::MissingFallbackResponse)
                    })
                    .and_then(native_response_from_legacy);
                Box::pin(async move { response })
            }
        }
    }
}

/// An error raised while dispatching a native route or constructing its response.
#[derive(Debug)]
pub enum NativeApplicationError {
    /// A route pattern could not be registered.
    RouteRegistration(RouteError),
    /// The route table selected an index without a corresponding endpoint.
    MissingEndpoint {
        /// Route index selected by the route table.
        route_index: usize,
    },
    /// A standard 404 or 405 response could not be constructed.
    FallbackResponse(ResponseError),
    /// The route matcher returned a non-match without its fallback response.
    MissingFallbackResponse,
    /// A legacy Starlette response field could not be converted to `http` types.
    InvalidLegacyResponse(NativeResponseConversionError),
    /// A route endpoint returned an application or request-body error.
    ///
    /// The original error remains available through [`Error::source`] and can
    /// be downcast to its concrete type.
    Endpoint(NativeBodyError),
}

impl Display for NativeApplicationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::RouteRegistration(error) => {
                write!(formatter, "route registration failed: {error}")
            }
            Self::MissingEndpoint { route_index } => {
                write!(formatter, "route index {route_index} has no endpoint")
            }
            Self::FallbackResponse(error) => write!(formatter, "fallback response failed: {error}"),
            Self::MissingFallbackResponse => {
                formatter.write_str("route fallback did not provide its response")
            }
            Self::InvalidLegacyResponse(error) => Display::fmt(error, formatter),
            Self::Endpoint(error) => write!(formatter, "native endpoint failed: {error}"),
        }
    }
}

impl Error for NativeApplicationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) => Some(error),
            Self::FallbackResponse(error) => Some(error),
            Self::InvalidLegacyResponse(error) => Some(error),
            Self::Endpoint(error) => Some(error.as_ref()),
            Self::MissingEndpoint { .. } => None,
            Self::MissingFallbackResponse => None,
        }
    }
}

/// A conversion failure while adapting the existing buffered response type.
#[derive(Debug)]
pub enum NativeResponseConversionError {
    /// The legacy response status is not valid in the shared HTTP type.
    StatusCode(InvalidStatusCode),
    /// A legacy response header name is not valid in the shared HTTP type.
    HeaderName(InvalidHeaderName),
    /// A legacy response header value is not valid in the shared HTTP type.
    HeaderValue(http::header::InvalidHeaderValue),
}

impl Display for NativeResponseConversionError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::StatusCode(error) => write!(formatter, "invalid response status: {error}"),
            Self::HeaderName(error) => write!(formatter, "invalid response header name: {error}"),
            Self::HeaderValue(error) => write!(formatter, "invalid response header value: {error}"),
        }
    }
}

impl Error for NativeResponseConversionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::StatusCode(error) => Some(error),
            Self::HeaderName(error) => Some(error),
            Self::HeaderValue(error) => Some(error),
        }
    }
}

fn native_response_from_legacy(
    response: Response,
) -> Result<NativeHttpResponse, NativeApplicationError> {
    let status = http::StatusCode::from_u16(response.status_code()).map_err(|error| {
        NativeApplicationError::InvalidLegacyResponse(NativeResponseConversionError::StatusCode(
            error,
        ))
    })?;
    let body = native_body(Bytes::copy_from_slice(response.body()));
    let mut native = HttpResponse::new(body);
    *native.status_mut() = status;
    for (name, value) in response.headers() {
        let name = HeaderName::from_bytes(name).map_err(|error| {
            NativeApplicationError::InvalidLegacyResponse(
                NativeResponseConversionError::HeaderName(error),
            )
        })?;
        let value = HeaderValue::from_bytes(value).map_err(|error| {
            NativeApplicationError::InvalidLegacyResponse(
                NativeResponseConversionError::HeaderValue(error),
            )
        })?;
        native.headers_mut().append(name, value);
    }
    Ok(native)
}
