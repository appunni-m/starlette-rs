//! A small Rust-native application for fixed HTTP responses.
//!
//! [`Starlette`] composes the route matcher with prebuilt [`Response`] values.
//! Its async [`Starlette::call`] method uses standard Rust futures to send the
//! response events in order. It does not invoke Python endpoints or require a
//! runtime or executor.

use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::future::Future;

use crate::{DetailedRouteMatch, Response, ResponseError, ResponseEvent, RouteError, RouteTable};

/// One ordered route and its already-constructed response.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApplicationRoute {
    path: String,
    methods: Vec<String>,
    response: Response,
}

/// The path and method fields needed by this native HTTP dispatch slice.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HttpScope<'a> {
    /// Case-sensitive request path used for route matching.
    pub path: &'a str,
    /// HTTP method used for route matching.
    pub method: &'a str,
}

impl<'a> HttpScope<'a> {
    /// Creates a minimal scope from its path and method.
    #[must_use]
    pub const fn new(path: &'a str, method: &'a str) -> Self {
        Self { path, method }
    }
}

impl ApplicationRoute {
    /// Creates a route with a prebuilt response.
    ///
    /// Route validation occurs when the route is added to [`Starlette`].
    /// Methods are normalized by the same rules as [`RouteTable::add_route`].
    #[must_use]
    pub fn new<P, M, S>(path: P, methods: M, response: Response) -> Self
    where
        P: Into<String>,
        M: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        Self {
            path: path.into(),
            methods: methods
                .into_iter()
                .map(|method| method.as_ref().to_owned())
                .collect(),
            response,
        }
    }

    pub(crate) fn into_parts(self) -> (String, Vec<String>, Response) {
        (self.path, self.methods, self.response)
    }
}

/// A native application that routes requests to prebuilt responses.
///
/// The application preserves route insertion order and uses [`RouteTable`]
/// matching semantics. A successful match returns its configured response;
/// a path miss and a method mismatch return the standard 404 and 405
/// responses. [`Self::call`] accepts only the path and method from an HTTP
/// scope and sends the selected response events through a Rust future-based
/// callback. This bounded API does not parse a full ASGI scope, consume request
/// bodies, manage lifespan, invoke endpoints, or provide Python
/// `starlette.applications.Starlette` behavior.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Starlette {
    routes: RouteTable,
    responses: Vec<Response>,
}

impl Starlette {
    /// Builds an application from routes in dispatch order.
    ///
    /// # Errors
    ///
    /// Returns [`ApplicationError::RouteRegistration`] if a route path is
    /// invalid.
    pub fn new(
        routes: impl IntoIterator<Item = ApplicationRoute>,
    ) -> Result<Self, ApplicationError> {
        let mut route_table = RouteTable::new();
        let mut responses = Vec::new();
        for route in routes {
            route_table.add_route(route.path, route.methods)?;
            responses.push(route.response);
        }
        Ok(Self {
            routes: route_table,
            responses,
        })
    }

    /// Routes a path and method and returns its decision and response.
    ///
    /// A matched route returns the route's configured response. A method
    /// mismatch or path miss returns the response synthesized by
    /// [`DetailedRouteMatch::fallback_response`]. The response's ordered
    /// [`ResponseEvent`] values are available through
    /// [`DispatchResult::response_events`].
    ///
    /// # Errors
    ///
    /// Returns [`ApplicationError::ResponseConstruction`] if a method
    /// fallback cannot be represented as a response, or
    /// [`ApplicationError::MissingRouteResponse`] if the route table and
    /// configured responses ever become inconsistent.
    pub fn dispatch(&self, path: &str, method: &str) -> Result<DispatchResult, ApplicationError> {
        let route_match = self.routes.matches_detailed(path, method);
        let response = match &route_match {
            DetailedRouteMatch::Matched { route_index, .. } => {
                self.responses.get(*route_index).cloned().ok_or(
                    ApplicationError::MissingRouteResponse {
                        route_index: *route_index,
                    },
                )?
            }
            DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => {
                route_match
                    .fallback_response()?
                    .ok_or(ApplicationError::MissingFallbackResponse)?
            }
        };
        Ok(DispatchResult {
            route_match,
            response,
        })
    }

    /// Dispatches a minimal HTTP scope and awaits each response event in order.
    ///
    /// This runtime-agnostic entry point sends the response-start event before
    /// the final response-body event. It accepts a receive callback for an
    /// ASGI-shaped call boundary, but does not invoke it because the fixed
    /// response routes in this slice do not read request bodies.
    ///
    /// # Errors
    ///
    /// Returns [`ApplicationCallError::Dispatch`] if routing or response
    /// construction fails, or [`ApplicationCallError::Send`] if the send
    /// callback rejects an event. A send failure stops dispatch immediately;
    /// later events are not sent.
    pub async fn call<R, RFut, S, SFut, E>(
        &self,
        scope: &HttpScope<'_>,
        _receive: R,
        mut send: S,
    ) -> Result<DispatchResult, ApplicationCallError<E>>
    where
        R: FnMut() -> RFut,
        RFut: Future,
        S: FnMut(ResponseEvent) -> SFut,
        SFut: Future<Output = Result<(), E>>,
    {
        let dispatch = self
            .dispatch(scope.path, scope.method)
            .map_err(ApplicationCallError::Dispatch)?;
        for event in dispatch.response_events() {
            send(event).await.map_err(ApplicationCallError::Send)?;
        }
        Ok(dispatch)
    }
}

/// A routing decision paired with the response selected for that request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DispatchResult {
    /// Detailed route match, including any converted path parameters.
    pub route_match: DetailedRouteMatch,
    /// Configured or synthesized HTTP response.
    pub response: Response,
}

impl DispatchResult {
    /// Returns the response-start and response-body events in send order.
    #[must_use]
    pub fn response_events(&self) -> [ResponseEvent; 2] {
        self.response.asgi_events()
    }
}

/// An error while building or dispatching a native application.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplicationError {
    /// A route could not be registered in the route table.
    RouteRegistration(RouteError),
    /// A fallback response could not be constructed.
    ResponseConstruction(ResponseError),
    /// Internal route and response indices did not agree.
    MissingRouteResponse {
        /// Route index for which there was no configured response.
        route_index: usize,
    },
    /// A non-matched decision did not provide its fallback response.
    MissingFallbackResponse,
}

/// An error returned by the async native [`Starlette::call`] entry point.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplicationCallError<E> {
    /// Routing or response construction failed before sending an event.
    Dispatch(ApplicationError),
    /// The caller's send callback rejected a response event.
    Send(E),
}

impl<E> Display for ApplicationCallError<E>
where
    E: Display,
{
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Dispatch(error) => write!(formatter, "request dispatch failed: {error}"),
            Self::Send(error) => write!(formatter, "response send failed: {error}"),
        }
    }
}

impl<E> Error for ApplicationCallError<E>
where
    E: Error + 'static,
{
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Dispatch(error) => Some(error),
            Self::Send(error) => Some(error),
        }
    }
}

impl Display for ApplicationError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::RouteRegistration(error) => {
                write!(formatter, "route registration failed: {error}")
            }
            Self::ResponseConstruction(error) => {
                write!(formatter, "fallback response construction failed: {error}")
            }
            Self::MissingRouteResponse { route_index } => {
                write!(formatter, "no configured response for route {route_index}")
            }
            Self::MissingFallbackResponse => {
                formatter.write_str("route decision did not provide a fallback response")
            }
        }
    }
}

impl Error for ApplicationError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) => Some(error),
            Self::ResponseConstruction(error) => Some(error),
            Self::MissingRouteResponse { .. } | Self::MissingFallbackResponse => None,
        }
    }
}

impl From<RouteError> for ApplicationError {
    fn from(error: RouteError) -> Self {
        Self::RouteRegistration(error)
    }
}

impl From<ResponseError> for ApplicationError {
    fn from(error: ResponseError) -> Self {
        Self::ResponseConstruction(error)
    }
}
