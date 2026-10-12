//! Reverse URL formatting for one named HTTP route.

use crate::{NamedRouteError, RouteError, RouteTable, RouteUrlPath};

/// A Rust-native, reverse-only view of one named HTTP path pattern.
///
/// This type formats a route path without constructing an endpoint or
/// dispatching requests. Parameter values are supplied as strings already
/// formatted by the corresponding built-in converter. The supported path
/// syntax and built-in converters are the same as [`RouteTable`]. Values are
/// not percent-encoded. Python-registered converters and Python object
/// conversion are outside this Rust-native API.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedRoute {
    route: RouteTable,
    name: String,
}

impl NamedRoute {
    /// Creates a reverse-only route from its path pattern and explicit name.
    ///
    /// An explicit name avoids inferring a Python endpoint's `__name__`,
    /// which has no Rust-native equivalent.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the path does not start with `/`, uses an
    /// unsupported converter, or contains invalid or duplicate parameters.
    pub fn new<P, N>(path: P, name: N) -> Result<Self, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let mut route = RouteTable::new();
        route.add_route(path, std::iter::empty::<&str>())?;
        Ok(Self {
            route,
            name: name.into(),
        })
    }

    /// Formats this route when `name` and the supplied parameter names match.
    ///
    /// Name mismatch and missing or extra path parameters return
    /// [`NamedRouteError::NoMatchFound`]. Values that match the parameter set
    /// are checked by the built-in converter formatter in [`RouteTable`].
    ///
    /// # Errors
    ///
    /// Returns [`NamedRouteError::NoMatchFound`] if the name or parameter-name
    /// set differs from this route. Returns
    /// [`NamedRouteError::RouteFormatting`] when a matching parameter value
    /// violates its built-in converter's formatting contract.
    pub fn url_path_for(
        &self,
        name: &str,
        path_params: &[(String, String)],
    ) -> Result<RouteUrlPath, NamedRouteError> {
        if name != self.name.as_str() {
            return Err(no_match(name, path_params));
        }

        match self.route.build_path(0, path_params) {
            Ok(path) => Ok(RouteUrlPath {
                path,
                protocol: String::from("http"),
                host: String::new(),
            }),
            Err(RouteError::PathParameterNamesMismatch { .. }) => Err(no_match(name, path_params)),
            Err(error) => Err(NamedRouteError::RouteFormatting(error)),
        }
    }
}

fn no_match(name: &str, path_params: &[(String, String)]) -> NamedRouteError {
    NamedRouteError::NoMatchFound {
        name: String::from(name),
        path_params: path_params.to_vec(),
    }
}
