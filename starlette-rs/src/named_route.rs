//! Reverse URL formatting for one named HTTP or WebSocket route.

use crate::{CustomPathConverterRegistry, NamedRouteError, RouteError, RouteTable, RouteUrlPath};

/// A Rust-native, reverse-only view of one named path pattern.
///
/// This type formats a route path without constructing an endpoint or
/// dispatching requests. Parameter values are supplied as strings already
/// represented by the corresponding converter. The supported path syntax and
/// built-in converters are the same as [`RouteTable`]. Custom
/// string converters can be provided with [`Self::new_with_custom_converters`]
/// or [`Self::new_websocket_with_custom_converters`]. Values are not
/// percent-encoded.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedRoute {
    route: RouteTable,
    name: String,
    protocol: String,
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
    /// unregistered converter, or contains invalid or duplicate parameters.
    pub fn new<P, N>(path: P, name: N) -> Result<Self, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        Self::new_with_custom_converters(path, name, &CustomPathConverterRegistry::new())
    }

    /// Creates an HTTP route using the supplied custom converter registry.
    ///
    /// Register converters before constructing the route. Converter inputs
    /// and outputs are strings; a converter's `matches`, `convert`, and
    /// `to_string` methods define its bounded native behavior.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the path is invalid or names a converter
    /// that is neither built in nor present in `converters`.
    pub fn new_with_custom_converters<P, N>(
        path: P,
        name: N,
        converters: &CustomPathConverterRegistry,
    ) -> Result<Self, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let mut route = RouteTable::with_custom_converters(converters.clone());
        route.add_route(path, std::iter::empty::<&str>())?;
        Ok(Self {
            route,
            name: name.into(),
            protocol: String::from("http"),
        })
    }

    /// Creates a reverse-only WebSocket route with an explicit name.
    ///
    /// The route shares the path converter and parameter contract of
    /// [`Self::new`], and successful URL paths carry the `websocket` protocol.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the path is invalid or uses an unregistered
    /// converter.
    pub fn new_websocket<P, N>(path: P, name: N) -> Result<Self, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        Self::new_websocket_with_custom_converters(path, name, &CustomPathConverterRegistry::new())
    }

    /// Creates a WebSocket route using the supplied custom converter registry.
    ///
    /// See [`Self::new_with_custom_converters`] for the converter contract.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the path is invalid or names an unregistered
    /// converter.
    pub fn new_websocket_with_custom_converters<P, N>(
        path: P,
        name: N,
        converters: &CustomPathConverterRegistry,
    ) -> Result<Self, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let mut route = RouteTable::with_custom_converters(converters.clone());
        route.add_route(path, std::iter::empty::<&str>())?;
        Ok(Self {
            route,
            name: name.into(),
            protocol: String::from("websocket"),
        })
    }

    /// Formats this route when `name` and the supplied parameter names match.
    ///
    /// Name mismatch and missing or extra path parameters return
    /// [`NamedRouteError::NoMatchFound`]. Built-in converter values are checked
    /// by [`RouteTable`]; custom converter output is inserted as returned.
    ///
    /// # Errors
    ///
    /// Returns [`NamedRouteError::NoMatchFound`] if the name or parameter-name
    /// set differs from this route. Returns
    /// [`NamedRouteError::RouteFormatting`] when a built-in converter rejects
    /// its value or a custom converter reports a formatting error.
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
                protocol: self.protocol.clone(),
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
