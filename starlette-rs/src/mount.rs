use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::route_table::get_route_path;
use crate::{
    ApplicationRoute, DetailedRouteMatch, PathParameterCapture, Response, ResponseError,
    RouteError, RouteTable,
};

/// The scope values a native Mount needs to route one HTTP request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MountScope<'a> {
    /// Full ASGI path, including any `root_path` prefix.
    pub path: &'a str,
    /// HTTP method used to select a child route.
    pub method: &'a str,
    /// Prefix already removed by the server or an outer Mount.
    pub root_path: &'a str,
    /// Top-level application prefix, if an outer layer already set it.
    pub app_root_path: Option<&'a str>,
    /// Path captures inherited from an outer route or Mount.
    pub path_params: &'a [PathParameterCapture],
}

impl<'a> MountScope<'a> {
    /// Creates a Mount scope projection with no inherited path parameters.
    #[must_use]
    pub const fn new(path: &'a str, method: &'a str, root_path: &'a str) -> Self {
        Self {
            path,
            method,
            root_path,
            app_root_path: None,
            path_params: &[],
        }
    }

    /// Retains an application root path established by an outer layer.
    #[must_use]
    pub const fn with_app_root_path(mut self, app_root_path: &'a str) -> Self {
        self.app_root_path = Some(app_root_path);
        self
    }

    /// Adds typed path parameters inherited from an outer route or Mount.
    #[must_use]
    pub const fn with_path_params(mut self, path_params: &'a [PathParameterCapture]) -> Self {
        self.path_params = path_params;
        self
    }
}

/// The scope extension applied when a Mount path matches.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MountScopeExtension {
    /// Root path extended by the matched Mount prefix.
    pub root_path: String,
    /// Top-level application root path retained across nested Mounts.
    pub app_root_path: String,
    /// Inherited, mount, and child-route path parameters in insertion order.
    pub path_params: Vec<PathParameterCapture>,
}

/// The result of routing through a Mount and its child routes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MountDispatchResult {
    /// Mount path decision before child routing.
    pub mount_match: DetailedRouteMatch,
    /// Child route decision when the Mount path matched.
    pub child_match: Option<DetailedRouteMatch>,
    /// Child-scope values applied after the Mount path matched.
    pub scope_extension: Option<MountScopeExtension>,
    /// Child response, or the standalone Mount fallback response.
    pub response: Response,
}

/// A native Mount over child routes with prebuilt responses.
///
/// This type handles the Mount prefix, root-path extension, parameter merging,
/// child route selection, and standalone 404/405 responses in Rust. It is an
/// additive native API for fixed-response routes; it does not invoke Python
/// endpoints or model arbitrary ASGI child applications.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Mount {
    mount_routes: RouteTable,
    child_routes: RouteTable,
    responses: Vec<Response>,
}

impl Mount {
    /// Builds a Mount from a path and ordered child routes.
    ///
    /// As in Starlette, trailing slashes are removed from the Mount prefix
    /// before its catch-all child path is added. The child routes use the same
    /// built-in converters as [`RouteTable`].
    ///
    /// # Errors
    ///
    /// Returns [`MountError::RouteRegistration`] when either the Mount path or
    /// a child route path is invalid.
    pub fn new<P>(
        path: P,
        routes: impl IntoIterator<Item = ApplicationRoute>,
    ) -> Result<Self, MountError>
    where
        P: Into<String>,
    {
        let path = path.into();
        let mount_pattern = format!("{}/{{path:path}}", path.trim_end_matches('/'));
        let mut mount_routes = RouteTable::new();
        mount_routes
            .add_route(mount_pattern, std::iter::empty::<&str>())
            .map_err(MountError::RouteRegistration)?;

        let mut child_routes = RouteTable::new();
        let mut responses = Vec::new();
        for route in routes {
            let (path, methods, response) = route.into_parts();
            child_routes
                .add_route(path, methods)
                .map_err(MountError::RouteRegistration)?;
            responses.push(response);
        }

        Ok(Self {
            mount_routes,
            child_routes,
            responses,
        })
    }

    /// Routes one HTTP scope through the Mount and its child routes.
    ///
    /// A Mount miss returns the same plain-text 404 response as calling a
    /// standalone Starlette Mount. On a Mount match, this extends `root_path`,
    /// retains the original `app_root_path` (or initializes it from
    /// `root_path`), removes the Mount's internal `path` capture, and merges
    /// child captures over inherited values while preserving insertion order.
    /// The input `path` is used unchanged for child route matching.
    ///
    /// # Errors
    ///
    /// Returns [`MountError`] if route matching invariants or response
    /// construction fail.
    pub fn dispatch(&self, scope: &MountScope<'_>) -> Result<MountDispatchResult, MountError> {
        let mount_match = self.mount_routes.matches_detailed_with_root_path(
            scope.path,
            scope.root_path,
            scope.method,
        );
        let (mount_route_index, mount_raw_params) = match &mount_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            } => (*route_index, path_params.as_slice()),
            DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => {
                let response = fallback_response(&mount_match)?;
                return Ok(MountDispatchResult {
                    mount_match,
                    child_match: None,
                    scope_extension: None,
                    response,
                });
            }
        };
        if mount_route_index != 0 {
            return Err(MountError::UnexpectedMountRouteIndex(mount_route_index));
        }

        let mount_params = self
            .mount_routes
            .capture_path_parameters(mount_route_index, mount_raw_params)
            .map_err(MountError::PathParameterCapture)?;
        let mount_remainder = mount_params
            .iter()
            .find(|parameter| parameter.name == "path")
            .ok_or(MountError::MissingMountRemainder)?;
        let remaining_path = format!("/{}", mount_remainder.value);
        let route_path = get_route_path(scope.path, scope.root_path);
        let matched_path = route_path
            .strip_suffix(&remaining_path)
            .ok_or(MountError::MountRemainderNotSuffix)?;
        let root_path = format!("{}{matched_path}", scope.root_path);
        let app_root_path = scope.app_root_path.unwrap_or(scope.root_path).to_owned();

        let mut path_params = scope.path_params.to_vec();
        merge_mount_params(&mut path_params, &mount_params);

        let child_match =
            self.child_routes
                .matches_detailed_with_root_path(scope.path, &root_path, scope.method);
        let response = match &child_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params: raw_params,
            } => {
                let child_params = self
                    .child_routes
                    .capture_path_parameters(*route_index, raw_params)
                    .map_err(MountError::PathParameterCapture)?;
                merge_path_params(&mut path_params, &child_params);
                self.responses
                    .get(*route_index)
                    .cloned()
                    .ok_or(MountError::MissingChildResponse(*route_index))?
            }
            DetailedRouteMatch::MethodNotAllowed {
                route_index,
                path_params: raw_params,
                ..
            } => {
                let child_params = self
                    .child_routes
                    .capture_path_parameters(*route_index, raw_params)
                    .map_err(MountError::PathParameterCapture)?;
                merge_path_params(&mut path_params, &child_params);
                fallback_response(&child_match)?
            }
            DetailedRouteMatch::NotFound => fallback_response(&child_match)?,
        };

        Ok(MountDispatchResult {
            mount_match,
            child_match: Some(child_match),
            scope_extension: Some(MountScopeExtension {
                root_path,
                app_root_path,
                path_params,
            }),
            response,
        })
    }
}

/// An invalid Mount, child match, or fallback response operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MountError {
    /// Mount or child route registration failed.
    RouteRegistration(RouteError),
    /// A matched route's captures did not agree with its registered pattern.
    PathParameterCapture(RouteError),
    /// A fallback response could not be represented.
    ResponseConstruction(ResponseError),
    /// The single registered Mount route produced a different index.
    UnexpectedMountRouteIndex(usize),
    /// The Mount matcher did not provide its internal catch-all path capture.
    MissingMountRemainder,
    /// The Mount remainder was not a suffix of the root-path-relative input.
    MountRemainderNotSuffix,
    /// A matched child route had no corresponding configured response.
    MissingChildResponse(usize),
    /// A non-match did not provide a fallback response.
    MissingFallbackResponse,
}

impl Display for MountError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::RouteRegistration(error) => {
                write!(formatter, "Mount route registration failed: {error}")
            }
            Self::PathParameterCapture(error) => {
                write!(formatter, "Mount path captures are invalid: {error}")
            }
            Self::ResponseConstruction(error) => {
                write!(formatter, "Mount fallback response failed: {error}")
            }
            Self::UnexpectedMountRouteIndex(index) => {
                write!(formatter, "Mount matched unexpected route index {index}")
            }
            Self::MissingMountRemainder => {
                formatter.write_str("Mount match omitted its catch-all path capture")
            }
            Self::MountRemainderNotSuffix => {
                formatter.write_str("Mount remainder is not a suffix of the request path")
            }
            Self::MissingChildResponse(index) => {
                write!(formatter, "child route {index} has no configured response")
            }
            Self::MissingFallbackResponse => {
                formatter.write_str("Mount non-match omitted its fallback response")
            }
        }
    }
}

impl Error for MountError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) | Self::PathParameterCapture(error) => Some(error),
            Self::ResponseConstruction(error) => Some(error),
            Self::UnexpectedMountRouteIndex(_)
            | Self::MissingMountRemainder
            | Self::MountRemainderNotSuffix
            | Self::MissingChildResponse(_)
            | Self::MissingFallbackResponse => None,
        }
    }
}

fn fallback_response(route_match: &DetailedRouteMatch) -> Result<Response, MountError> {
    route_match
        .fallback_response()
        .map_err(MountError::ResponseConstruction)?
        .ok_or(MountError::MissingFallbackResponse)
}

fn merge_path_params(
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

fn merge_mount_params(
    path_params: &mut Vec<PathParameterCapture>,
    mount_params: &[PathParameterCapture],
) {
    for mount_param in mount_params
        .iter()
        .filter(|parameter| parameter.name != "path")
    {
        merge_path_params(path_params, std::slice::from_ref(mount_param));
    }
}
