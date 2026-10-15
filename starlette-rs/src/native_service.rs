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

mod host_service;
pub use host_service::{NativeHostApplication, NativeHostRoute};

use crate::{
    CustomPathConverterRegistry, DetailedRouteMatch, Mount, MountError, MountScope,
    PathParameterCapture, Response, ResponseError, RouteError, RouteTable,
};

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
    scope: NativeRequestScope,
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

    /// Returns inherited and matched route parameters in insertion order.
    #[must_use]
    pub fn path_params(&self) -> &[(String, String)] {
        &self.path_params
    }

    /// Returns the matched Mount and application scope values for this request.
    #[must_use]
    pub fn scope(&self) -> &NativeRequestScope {
        &self.scope
    }

    /// Returns the prefix removed before the current application matched routes.
    #[must_use]
    pub fn root_path(&self) -> &str {
        self.scope.root_path()
    }

    /// Returns the top-level application prefix, defaulting to `root_path`.
    #[must_use]
    pub fn app_root_path(&self) -> &str {
        self.scope
            .app_root_path()
            .unwrap_or_else(|| self.scope.root_path())
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

    /// Splits the request head, streaming body, and merged path parameters.
    #[must_use]
    pub fn into_parts(self) -> (Parts, NativeRequestBody, Vec<(String, String)>) {
        (self.parts, self.body, self.path_params)
    }
}

/// Scope metadata carried through native Mount dispatch.
///
/// Insert this value into an `http::Request` extension when the server has
/// already removed a path prefix or supplied inherited route parameters.
/// Mounted applications update it before routing child requests. Parameter
/// captures retain their converters as well as their converted string values.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NativeRequestScope {
    root_path: String,
    app_root_path: Option<String>,
    path_params: Vec<PathParameterCapture>,
}

impl NativeRequestScope {
    /// Creates an empty scope with no inherited path prefix or parameters.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the prefix already removed before the current application.
    #[must_use]
    pub fn with_root_path(mut self, root_path: impl Into<String>) -> Self {
        self.root_path = root_path.into();
        self
    }

    /// Sets the root prefix established by the top-level application.
    #[must_use]
    pub fn with_app_root_path(mut self, app_root_path: impl Into<String>) -> Self {
        self.app_root_path = Some(app_root_path.into());
        self
    }

    /// Sets captures inherited from an outer route or Mount.
    #[must_use]
    pub fn with_path_params(
        mut self,
        path_params: impl IntoIterator<Item = PathParameterCapture>,
    ) -> Self {
        self.path_params = path_params.into_iter().collect();
        self
    }

    /// Returns the prefix already removed before the current application.
    #[must_use]
    pub fn root_path(&self) -> &str {
        &self.root_path
    }

    /// Returns the top-level application prefix, if one was supplied.
    #[must_use]
    pub fn app_root_path(&self) -> Option<&str> {
        self.app_root_path.as_deref()
    }

    /// Returns typed captures inherited from outer routes and Mounts.
    #[must_use]
    pub fn path_params(&self) -> &[PathParameterCapture] {
        &self.path_params
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

/// A native Mount that delegates matching to another [`NativeApplication`].
///
/// The Mount uses Starlette's shared route and scope logic to extend
/// `root_path`, preserve `app_root_path`, and merge path captures before the
/// child application receives the original HTTP request.
#[derive(Clone)]
pub struct NativeMount {
    mount: Mount,
    application: Arc<NativeApplication>,
}

impl NativeMount {
    /// Creates a Mount at `path` that dispatches to a child application.
    ///
    /// # Errors
    ///
    /// Returns [`MountError`] when the path cannot be registered by the
    /// shared Mount route table.
    pub fn new<P>(path: P, application: NativeApplication) -> Result<Self, MountError>
    where
        P: Into<String>,
    {
        let mount = Mount::new(path, std::iter::empty::<crate::ApplicationRoute>())?;
        Ok(Self {
            mount,
            application: Arc::new(application),
        })
    }

    fn extend_request_scope<B>(
        &self,
        request: Request<B>,
        inherited_scope: &NativeRequestScope,
    ) -> Result<Request<B>, NativeApplicationError> {
        let mut mount_scope = MountScope::new(
            request.uri().path(),
            request.method().as_str(),
            inherited_scope.root_path(),
        )
        .with_path_params(inherited_scope.path_params());
        if let Some(app_root_path) = inherited_scope.app_root_path() {
            mount_scope = mount_scope.with_app_root_path(app_root_path);
        }

        let dispatch = self
            .mount
            .dispatch(&mount_scope)
            .map_err(NativeApplicationError::Mount)?;
        let Some(extension) = dispatch.scope_extension else {
            return Err(NativeApplicationError::MissingMountScopeExtension);
        };
        let child_scope = NativeRequestScope {
            root_path: extension.root_path,
            app_root_path: Some(extension.app_root_path),
            path_params: extension.path_params,
        };
        let (mut parts, body) = request.into_parts();
        parts.extensions.insert(child_scope);
        Ok(Request::from_parts(parts, body))
    }
}

/// An ordered route or mounted application in a native application.
pub enum NativeApplicationChild {
    /// An asynchronous native HTTP route.
    Route(NativeRoute),
    /// A child native application mounted below a path prefix.
    Mount(NativeMount),
}

impl From<NativeRoute> for NativeApplicationChild {
    fn from(route: NativeRoute) -> Self {
        Self::Route(route)
    }
}

impl From<NativeMount> for NativeApplicationChild {
    fn from(mount: NativeMount) -> Self {
        Self::Mount(mount)
    }
}

#[derive(Clone)]
enum NativeApplicationEntry {
    Endpoint(Arc<Endpoint>),
    Mount(NativeMount),
}

/// A server-neutral Starlette route application implementing Tower `Service`.
///
/// The service is immediately ready and routes each request when `call` is
/// invoked. It does not poll the request body during routing or poll the
/// response body before returning the response. Endpoints and outer Tower
/// layers control when they poll bodies, so `http_body::Body` demand propagates
/// through this service without framework read-ahead. Cloned applications
/// share their immutable route table and endpoint closures. Ordered Mount
/// entries can delegate requests to child applications while carrying native
/// scope metadata. It does not create a runtime; its caller supplies the
/// executor.
#[derive(Clone)]
pub struct NativeApplication {
    routes: RouteTable,
    children: Vec<NativeApplicationEntry>,
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
        Self::with_children(routes.into_iter().map(NativeApplicationChild::Route))
    }

    /// Builds the application from ordered routes and mounted child apps.
    ///
    /// Route and Mount entries share one ordered route table, so path and
    /// method selection follows the same first-full-match policy for the
    /// complete application. Mounted children receive the original request
    /// with updated [`NativeRequestScope`] metadata.
    ///
    /// # Errors
    ///
    /// Returns [`NativeApplicationError::RouteRegistration`] if any route or
    /// Mount pattern cannot be represented by the shared route table.
    pub fn with_children<C>(
        children: impl IntoIterator<Item = C>,
    ) -> Result<Self, NativeApplicationError>
    where
        C: Into<NativeApplicationChild>,
    {
        Self::with_children_and_custom_converters(children, CustomPathConverterRegistry::new())
    }

    /// Builds the application from ordered routes and mounted child apps using
    /// the supplied custom path converters for route patterns.
    ///
    /// Register each converter before constructing the application. Routes
    /// retain the converter instance used when the application compiles their
    /// patterns. Mounted child applications keep their own converter registry.
    ///
    /// # Errors
    ///
    /// Returns [`NativeApplicationError::RouteRegistration`] if any route or
    /// Mount pattern cannot be represented by the shared route table.
    pub fn with_children_and_custom_converters<C>(
        children: impl IntoIterator<Item = C>,
        custom_converters: CustomPathConverterRegistry,
    ) -> Result<Self, NativeApplicationError>
    where
        C: Into<NativeApplicationChild>,
    {
        let mut table = RouteTable::with_custom_converters(custom_converters);
        let mut entries = Vec::new();
        for child in children {
            match child.into() {
                NativeApplicationChild::Route(route) => {
                    table
                        .add_route(route.path, route.methods)
                        .map_err(NativeApplicationError::RouteRegistration)?;
                    entries.push(NativeApplicationEntry::Endpoint(route.endpoint));
                }
                NativeApplicationChild::Mount(mount) => {
                    table
                        .add_route(
                            String::from(mount.mount.route_pattern()),
                            std::iter::empty::<&str>(),
                        )
                        .map_err(NativeApplicationError::RouteRegistration)?;
                    entries.push(NativeApplicationEntry::Mount(mount));
                }
            }
        }
        Ok(Self {
            routes: table,
            children: entries,
        })
    }

    /// Builds the application from native routes using custom path converters.
    ///
    /// This is the route-only convenience form of
    /// [`Self::with_children_and_custom_converters`].
    ///
    /// # Errors
    ///
    /// Returns [`NativeApplicationError::RouteRegistration`] if any route
    /// pattern cannot be represented by the shared route table.
    pub fn with_custom_converters(
        routes: impl IntoIterator<Item = NativeRoute>,
        custom_converters: CustomPathConverterRegistry,
    ) -> Result<Self, NativeApplicationError> {
        Self::with_children_and_custom_converters(
            routes.into_iter().map(NativeApplicationChild::Route),
            custom_converters,
        )
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
        let request_scope = request
            .extensions()
            .get::<NativeRequestScope>()
            .cloned()
            .unwrap_or_default();
        let route_match =
            self.routes
                .matches_detailed_with_root_path(path, request_scope.root_path(), method);
        match route_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            } => {
                let Some(child) = self.children.get(route_index).cloned() else {
                    return Box::pin(async move {
                        Err(NativeApplicationError::MissingEndpoint { route_index })
                    });
                };
                match child {
                    NativeApplicationEntry::Endpoint(endpoint) => {
                        let captures = match self
                            .routes
                            .capture_path_parameters(route_index, &path_params)
                        {
                            Ok(captures) => captures,
                            Err(error) => {
                                return Box::pin(async move {
                                    Err(NativeApplicationError::PathParameterCapture(error))
                                });
                            }
                        };
                        let mut scope = request_scope;
                        merge_scope_path_params(&mut scope.path_params, &captures);
                        let (mut parts, body) = request.into_parts();
                        parts.extensions.insert(scope.clone());
                        let path_params = scope
                            .path_params
                            .iter()
                            .map(|parameter| (parameter.name.clone(), parameter.value.clone()))
                            .collect();
                        let request = NativeRequest {
                            parts,
                            body: box_native_body(body),
                            path_params,
                            scope,
                        };
                        endpoint(request)
                    }
                    NativeApplicationEntry::Mount(mount) => {
                        let request = match mount.extend_request_scope(request, &request_scope) {
                            Ok(request) => request,
                            Err(error) => return Box::pin(async move { Err(error) }),
                        };
                        let mut application = mount.application.as_ref().clone();
                        application.call(request)
                    }
                }
            }
            fallback @ (DetailedRouteMatch::MethodNotAllowed { .. }
            | DetailedRouteMatch::NotFound) => {
                fallback_future_for_match(fallback, &self.routes, request_scope)
            }
        }
    }
}

fn fallback_future_for_match(
    route_match: DetailedRouteMatch,
    routes: &RouteTable,
    mut scope: NativeRequestScope,
) -> EndpointFuture {
    if let DetailedRouteMatch::MethodNotAllowed {
        route_index,
        path_params,
        ..
    } = &route_match
    {
        let captures = match routes.capture_path_parameters(*route_index, path_params) {
            Ok(captures) => captures,
            Err(error) => {
                return Box::pin(async move {
                    Err(NativeApplicationError::PathParameterCapture(error))
                });
            }
        };
        merge_scope_path_params(&mut scope.path_params, &captures);
    }

    let response = route_match
        .fallback_response()
        .map_err(NativeApplicationError::FallbackResponse)
        .and_then(|response| response.ok_or(NativeApplicationError::MissingFallbackResponse))
        .and_then(native_response_from_legacy);
    Box::pin(async move {
        let mut response = response?;
        response.extensions_mut().insert(scope);
        Ok(response)
    })
}

/// An error raised while dispatching a native route or constructing its response.
#[derive(Debug)]
pub enum NativeApplicationError {
    /// A route pattern could not be registered.
    RouteRegistration(RouteError),
    /// A matched route's captures did not agree with its registered pattern.
    PathParameterCapture(RouteError),
    /// A mounted child could not extend or dispatch its request scope.
    Mount(MountError),
    /// A Mount matched in the application route table without producing scope metadata.
    MissingMountScopeExtension,
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
            Self::PathParameterCapture(error) => {
                write!(formatter, "route path captures are invalid: {error}")
            }
            Self::Mount(error) => write!(formatter, "native Mount dispatch failed: {error}"),
            Self::MissingMountScopeExtension => {
                formatter.write_str("native Mount match omitted its scope extension")
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
            Self::RouteRegistration(error) | Self::PathParameterCapture(error) => Some(error),
            Self::Mount(error) => Some(error),
            Self::FallbackResponse(error) => Some(error),
            Self::InvalidLegacyResponse(error) => Some(error),
            Self::Endpoint(error) => Some(error.as_ref()),
            Self::MissingEndpoint { .. } => None,
            Self::MissingFallbackResponse => None,
            Self::MissingMountScopeExtension => None,
        }
    }
}

fn merge_scope_path_params(
    path_params: &mut Vec<PathParameterCapture>,
    updates: &[PathParameterCapture],
) {
    for update in updates {
        if let Some(existing) = path_params
            .iter_mut()
            .find(|parameter| parameter.name == update.name)
        {
            *existing = update.clone();
        } else {
            path_params.push(update.clone());
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
