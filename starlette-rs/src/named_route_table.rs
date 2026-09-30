//! Ordered reverse lookup for flat, named HTTP routes.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{RouteError, RouteTable};

/// An insertion-ordered table for reverse lookup across directly named HTTP routes.
///
/// This covers the flat `Router.url_path_for` behavior for named HTTP routes:
/// lookup skips routes whose name or exact parameter-name set does not match,
/// then formats the first matching route. Parameter values are strings already
/// formatted by the corresponding built-in converter. Custom converters,
/// nested `Mount` or `Host` routes, and WebSocket routes are outside this API.
///
/// Successful results carry `protocol = "http"` and an empty host, matching
/// Starlette's direct HTTP `URLPath` metadata. Path values are not
/// percent-encoded.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NamedRouteTable {
    routes: RouteTable,
    names: Vec<String>,
}

/// The path and metadata returned by [`NamedRouteTable::url_path_for`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RouteUrlPath {
    /// The formatted route path, without percent-encoding.
    pub path: String,
    /// The route protocol, always `"http"` for this table.
    pub protocol: String,
    /// The associated host, always empty for a direct HTTP route.
    pub host: String,
}

impl RouteUrlPath {
    /// Returns the formatted path without percent-encoding.
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }

    /// Returns the route protocol, which is `"http"`.
    #[must_use]
    pub fn protocol(&self) -> &str {
        &self.protocol
    }

    /// Returns the associated host, which is empty for direct HTTP routes.
    #[must_use]
    pub fn host(&self) -> &str {
        &self.host
    }
}

/// A reverse lookup miss or a failure while formatting a matching route.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NamedRouteError {
    /// No registered route had both the requested name and exact parameter names.
    NoMatchFound {
        /// The requested route name.
        name: String,
        /// Supplied path parameter names and values, in caller order.
        path_params: Vec<(String, String)>,
    },
    /// A route matched by name and parameter names, but its values could not be formatted.
    RouteFormatting(RouteError),
}

impl Display for NamedRouteError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoMatchFound { name, path_params } => {
                let names = path_params
                    .iter()
                    .map(|(name, _)| name.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                write!(
                    formatter,
                    "No route exists for name \"{name}\" and params \"{names}\"."
                )
            }
            Self::RouteFormatting(error) => write!(formatter, "route formatting failed: {error}"),
        }
    }
}

impl Error for NamedRouteError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::NoMatchFound { .. } => None,
            Self::RouteFormatting(error) => Some(error),
        }
    }
}

impl NamedRouteTable {
    /// Creates an empty reverse lookup table.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            routes: RouteTable::new(),
            names: Vec::new(),
        }
    }

    /// Adds a directly named HTTP route and returns its stable insertion index.
    ///
    /// Route path syntax and the supported built-in converters follow
    /// [`RouteTable::add_route`]. Names need not be unique; when names repeat,
    /// [`Self::url_path_for`] selects the first route whose parameter names
    /// exactly match the supplied set.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] if the path is invalid or uses an unsupported
    /// converter.
    pub fn add_route<P, N>(&mut self, path: P, name: N) -> Result<usize, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let index = self.routes.add_route(path, std::iter::empty::<&str>())?;
        self.names.push(name.into());
        Ok(index)
    }

    /// Builds a URL path for the first route matching both name and parameter names.
    ///
    /// Parameter values must already be formatted by their corresponding
    /// built-in converter, as required by [`RouteTable::build_path`]. A route
    /// with a different name or a non-exact parameter-name set is skipped.
    /// Once a route matches both, converter-formatting errors are returned
    /// immediately rather than trying later routes.
    ///
    /// # Errors
    ///
    /// Returns [`NamedRouteError::NoMatchFound`] if no route matches the name
    /// and exact parameter-name set. Returns
    /// [`NamedRouteError::RouteFormatting`] if formatting values for the first
    /// matching route fails.
    pub fn url_path_for(
        &self,
        name: &str,
        path_params: &[(String, String)],
    ) -> Result<RouteUrlPath, NamedRouteError> {
        for (route_index, route_name) in self.names.iter().enumerate() {
            if route_name != name {
                continue;
            }

            match self.routes.build_path(route_index, path_params) {
                Ok(path) => {
                    return Ok(RouteUrlPath {
                        path,
                        protocol: String::from("http"),
                        host: String::new(),
                    });
                }
                Err(RouteError::PathParameterNamesMismatch { .. }) => {}
                Err(error) => return Err(NamedRouteError::RouteFormatting(error)),
            }
        }

        Err(NamedRouteError::NoMatchFound {
            name: String::from(name),
            path_params: path_params.to_vec(),
        })
    }
}
