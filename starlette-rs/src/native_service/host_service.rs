//! Host-based dispatch for the Rust-native HTTP service.

use std::{
    error::Error,
    sync::Arc,
    task::{Context, Poll},
};

use bytes::Bytes;
use http::{Request, header::HOST};
use http_body::Body;
use tower_service::Service;

use crate::{HostPattern, NativeRoute, PathConverter, PathParameterCapture, RouteTable};

use super::{
    Endpoint, EndpointFuture, NativeApplicationError, NativeRequest, NativeRequestScope,
    box_native_body, merge_scope_path_params, native_response_from_legacy,
};

/// A host pattern and the HTTP routes mounted below it.
///
/// Each value represents one host-level dispatch entry. Routes within the
/// entry share its host parameters, which are made available alongside path
/// parameters to the selected endpoint.
pub struct NativeHostRoute {
    host: HostPattern,
    routes: Vec<NativeRoute>,
}

impl NativeHostRoute {
    /// Creates one host entry from a compiled host pattern and ordered routes.
    #[must_use]
    pub fn new(host: HostPattern, routes: impl IntoIterator<Item = NativeRoute>) -> Self {
        Self {
            host,
            routes: routes.into_iter().collect(),
        }
    }
}

#[derive(Clone)]
struct HostEntry {
    host: HostPattern,
    routes: RouteTable,
    endpoints: Vec<Arc<Endpoint>>,
}

/// A Tower service that dispatches HTTP requests by Host and then by path.
///
/// Host entries are checked in registration order. A matching host entry
/// owns the request even when none of its child paths match, in which case
/// its route table returns the ordinary 404 or 405 fallback. The first
/// matching child route receives host parameters followed by path parameters;
/// a path parameter with the same name replaces the host value.
#[derive(Clone)]
pub struct NativeHostApplication {
    hosts: Vec<HostEntry>,
    empty_routes: RouteTable,
}

impl NativeHostApplication {
    /// Builds the service from ordered host entries.
    ///
    /// # Errors
    ///
    /// Returns [`NativeApplicationError::RouteRegistration`] when a child
    /// path or method cannot be represented by the native route table.
    pub fn new(
        host_routes: impl IntoIterator<Item = NativeHostRoute>,
    ) -> Result<Self, NativeApplicationError> {
        let mut hosts = Vec::new();
        for host_route in host_routes {
            let mut routes = RouteTable::new();
            let mut endpoints = Vec::new();
            for route in host_route.routes {
                routes
                    .add_route(route.path, route.methods)
                    .map_err(NativeApplicationError::RouteRegistration)?;
                endpoints.push(route.endpoint);
            }
            hosts.push(HostEntry {
                host: host_route.host,
                routes,
                endpoints,
            });
        }
        Ok(Self {
            hosts,
            empty_routes: RouteTable::new(),
        })
    }
}

impl<B> Service<Request<B>> for NativeHostApplication
where
    B: Body<Data = Bytes> + Send + 'static,
    B::Error: Error + Send + Sync + 'static,
{
    type Response = super::NativeHttpResponse;
    type Error = NativeApplicationError;
    type Future = EndpointFuture;

    fn poll_ready(&mut self, _context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, request: Request<B>) -> Self::Future {
        let host = request.headers().get(HOST).map(|value| {
            value
                .as_bytes()
                .iter()
                .map(|byte| char::from(*byte))
                .collect::<String>()
        });

        let Some(host) = host.as_deref() else {
            return fallback_future(&self.empty_routes, &request);
        };

        for entry in &self.hosts {
            let Some(host_params) = entry.host.match_host(host) else {
                continue;
            };
            let mut scope = request
                .extensions()
                .get::<NativeRequestScope>()
                .cloned()
                .unwrap_or_default();
            let route_match = entry.routes.matches_detailed_with_root_path(
                request.uri().path(),
                scope.root_path(),
                request.method().as_str(),
            );
            return match route_match {
                crate::DetailedRouteMatch::Matched {
                    route_index,
                    path_params,
                } => {
                    let Some(endpoint) = entry.endpoints.get(route_index).cloned() else {
                        return Box::pin(async move {
                            Err(NativeApplicationError::MissingEndpoint { route_index })
                        });
                    };
                    let host_captures = host_params
                        .into_iter()
                        .map(|(name, value)| PathParameterCapture {
                            name,
                            value,
                            converter: PathConverter::String,
                        })
                        .collect::<Vec<_>>();
                    merge_scope_path_params(&mut scope.path_params, &host_captures);
                    let path_captures = match entry
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
                    merge_scope_path_params(&mut scope.path_params, &path_captures);
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
                fallback @ (crate::DetailedRouteMatch::MethodNotAllowed { .. }
                | crate::DetailedRouteMatch::NotFound) => fallback_future_for_match(fallback),
            };
        }

        fallback_future(&self.empty_routes, &request)
    }
}

fn fallback_future<B>(routes: &RouteTable, request: &Request<B>) -> EndpointFuture {
    let route_match = routes.matches_detailed(request.uri().path(), request.method().as_str());
    fallback_future_for_match(route_match)
}

fn fallback_future_for_match(route_match: crate::DetailedRouteMatch) -> EndpointFuture {
    let response = route_match
        .fallback_response()
        .map_err(NativeApplicationError::FallbackResponse)
        .and_then(|response| response.ok_or(NativeApplicationError::MissingFallbackResponse))
        .and_then(native_response_from_legacy);
    Box::pin(async move { response })
}
