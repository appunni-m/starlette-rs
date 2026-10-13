//! Ordered reverse URL lookup for named routes, Mounts, and Hosts.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{
    CustomPathConverter, CustomPathConverterRegistry, HostPattern, HostPatternError, NamedRoute,
    NamedRouteError, RouteError, RouteTable, RouteUrlPath,
};

/// A named-router miss or a nested route formatting failure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NamedRouterError {
    /// No route in the router graph matched the requested name and parameters.
    NoMatchFound {
        /// The requested route name.
        name: String,
        /// Supplied path parameter names and values, in caller order.
        path_params: Vec<(String, String)>,
    },
    /// A matching Route or Mount prefix could not format a parameter.
    RouteFormatting(RouteError),
    /// A matching Host could not format its host parameters.
    HostFormatting(HostPatternError),
}

impl Display for NamedRouterError {
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
            Self::HostFormatting(error) => write!(formatter, "host formatting failed: {error}"),
        }
    }
}

impl Error for NamedRouterError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::NoMatchFound { .. } => None,
            Self::RouteFormatting(error) => Some(error),
            Self::HostFormatting(error) => Some(error),
        }
    }
}

impl From<NamedRouteError> for NamedRouterError {
    fn from(error: NamedRouteError) -> Self {
        match error {
            NamedRouteError::NoMatchFound { name, path_params } => {
                Self::NoMatchFound { name, path_params }
            }
            NamedRouteError::RouteFormatting(error) => Self::RouteFormatting(error),
        }
    }
}

/// One entry in a Rust-native reverse-lookup router.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NamedRouterRoute {
    /// A directly named HTTP or WebSocket route.
    Route(NamedRoute),
    /// A Mount whose child routes are resolved by another named router.
    Mount(NamedMount),
    /// A Host whose child routes are resolved by another named router.
    Host(NamedHost),
}

impl From<NamedRoute> for NamedRouterRoute {
    fn from(route: NamedRoute) -> Self {
        Self::Route(route)
    }
}

impl From<NamedMount> for NamedRouterRoute {
    fn from(mount: NamedMount) -> Self {
        Self::Mount(mount)
    }
}

impl From<NamedHost> for NamedRouterRoute {
    fn from(host: NamedHost) -> Self {
        Self::Host(host)
    }
}

/// An insertion-ordered route graph for Rust-native reverse URL generation.
///
/// Direct routes and nested Mounts or Hosts are visited in registration
/// order. A lookup returns the first successful path; a formatting error from
/// a route that matched the name and parameter shape is returned immediately.
/// This mirrors Starlette `Router.url_path_for`'s ordered dispatch over route
/// objects for the Route, Mount, and Host subset represented here.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NamedRouter {
    routes: Vec<NamedRouterRoute>,
    custom_converters: CustomPathConverterRegistry,
}

impl NamedRouter {
    /// Creates an empty reverse-lookup router.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            routes: Vec::new(),
            custom_converters: CustomPathConverterRegistry::new(),
        }
    }

    /// Creates an empty router using the supplied custom converter registry.
    #[must_use]
    pub fn new_with_custom_converters(custom_converters: CustomPathConverterRegistry) -> Self {
        Self {
            routes: Vec::new(),
            custom_converters,
        }
    }

    /// Registers or replaces a custom converter for routes added afterwards.
    ///
    /// Routes already present retain their parsed converter instance.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::InvalidPathConverterName`] for names outside the
    /// path pattern's ASCII identifier syntax.
    pub fn register_converter<N, C>(&mut self, name: N, converter: C) -> Result<(), RouteError>
    where
        N: Into<String>,
        C: CustomPathConverter + 'static,
    {
        self.custom_converters.register_converter(name, converter)
    }

    /// Creates a router from insertion-ordered routes, Mounts, and Hosts.
    #[must_use]
    pub fn with_routes<I, R>(routes: I) -> Self
    where
        I: IntoIterator<Item = R>,
        R: Into<NamedRouterRoute>,
    {
        Self {
            routes: routes.into_iter().map(Into::into).collect(),
            custom_converters: CustomPathConverterRegistry::new(),
        }
    }

    /// Adds a named HTTP route and returns its stable insertion index.
    ///
    /// The route uses the same converter syntax and formatting contract as
    /// [`NamedRoute`]. Registered custom converters are captured when the
    /// route is added.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] if the path is invalid or uses an unregistered
    /// converter.
    pub fn add_route<P, N>(&mut self, path: P, name: N) -> Result<usize, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let route = NamedRoute::new_with_custom_converters(path, name, &self.custom_converters)?;
        Ok(self.add_entry(route))
    }

    /// Adds a named WebSocket route and returns its stable insertion index.
    ///
    /// Successful paths carry the `websocket` protocol metadata.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] if the path is invalid or uses an unsupported
    /// converter.
    pub fn add_websocket_route<P, N>(&mut self, path: P, name: N) -> Result<usize, RouteError>
    where
        P: Into<String>,
        N: Into<String>,
    {
        let route =
            NamedRoute::new_websocket_with_custom_converters(path, name, &self.custom_converters)?;
        Ok(self.add_entry(route))
    }

    /// Adds a prebuilt route, Mount, or Host and returns its stable index.
    pub fn add_entry(&mut self, route: impl Into<NamedRouterRoute>) -> usize {
        let index = self.routes.len();
        self.routes.push(route.into());
        index
    }

    /// Adds a nested Mount and returns its stable insertion index.
    pub fn add_mount(&mut self, mount: NamedMount) -> usize {
        self.add_entry(mount)
    }

    /// Adds a nested Host and returns its stable insertion index.
    pub fn add_host(&mut self, host: NamedHost) -> usize {
        self.add_entry(host)
    }

    /// Returns the number of routes and nested applications registered here.
    #[must_use]
    pub fn len(&self) -> usize {
        self.routes.len()
    }

    /// Returns whether this router has no entries.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.routes.is_empty()
    }

    /// Builds a URL path through the first route matching `name` and the
    /// supplied parameter names.
    ///
    /// Parameter values are strings already formatted by the route's
    /// converter. Named Mounts and Hosts prefix nested route names with `:`;
    /// unnamed ones forward child names unchanged. Values are not
    /// percent-encoded.
    ///
    /// # Errors
    ///
    /// Returns [`NamedRouterError::NoMatchFound`] if no entry matches. Returns
    /// [`NamedRouterError::RouteFormatting`] when a matching route's values are
    /// invalid for its converter or a nested Mount cannot format its prefix.
    /// Returns [`NamedRouterError::HostFormatting`] when a matching Host cannot
    /// format its host parameters.
    pub fn url_path_for(
        &self,
        name: &str,
        path_params: &[(String, String)],
    ) -> Result<RouteUrlPath, NamedRouterError> {
        for route in &self.routes {
            let result = match route {
                NamedRouterRoute::Route(route) => route
                    .url_path_for(name, path_params)
                    .map_err(NamedRouterError::from),
                NamedRouterRoute::Mount(mount) => mount.url_path_for(name, path_params),
                NamedRouterRoute::Host(host) => host.url_path_for(name, path_params),
            };
            match result {
                Ok(url_path) => return Ok(url_path),
                Err(NamedRouterError::NoMatchFound { .. }) => {}
                Err(error) => return Err(error),
            }
        }

        Err(no_match(name, path_params))
    }
}

/// A Rust-native nested Mount used by [`NamedRouter`] reverse lookup.
///
/// `path` follows Starlette Mount syntax and may contain built-in path
/// parameters. When `name` is present, nested routes are addressed as
/// `"<mount-name>:<route-name>"`. Without a name, child route names pass
/// through unchanged. A direct Mount-name lookup uses the `path` parameter
/// to format the mounted path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedMount {
    name: Option<String>,
    mount_routes: RouteTable,
    router: NamedRouter,
}

impl NamedMount {
    /// Creates a nested named-route Mount.
    ///
    /// The child router and Mount prefix remain entirely Rust-native. Route
    /// and prefix parameter values are supplied later to
    /// [`NamedRouter::url_path_for`].
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the path does not start with `/`, contains
    /// an unsupported converter, or repeats a parameter name.
    pub fn new<P>(path: P, name: Option<String>, router: NamedRouter) -> Result<Self, RouteError>
    where
        P: Into<String>,
    {
        Self::new_with_custom_converters(path, name, router, &CustomPathConverterRegistry::new())
    }

    /// Creates a nested named-route Mount using the supplied custom converter
    /// registry for its prefix path.
    ///
    /// Register converters before constructing the Mount. The child router
    /// keeps its own converter registry for child paths.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError`] when the prefix path is invalid or names an
    /// unregistered converter.
    pub fn new_with_custom_converters<P>(
        path: P,
        name: Option<String>,
        router: NamedRouter,
        converters: &CustomPathConverterRegistry,
    ) -> Result<Self, RouteError>
    where
        P: Into<String>,
    {
        let path = path.into();
        let mount_pattern = format!("{}/{{path:path}}", path.trim_end_matches('/'));
        let mut mount_routes = RouteTable::with_custom_converters(converters.clone());
        mount_routes.add_route(mount_pattern, std::iter::empty::<&str>())?;

        Ok(Self {
            name,
            mount_routes,
            router,
        })
    }

    /// Resolves the Mount's direct name or a nested route name.
    fn url_path_for(
        &self,
        name: &str,
        path_params: &[(String, String)],
    ) -> Result<RouteUrlPath, NamedRouterError> {
        if self.name.as_deref() == Some(name)
            && path_params.iter().any(|(parameter, _)| parameter == "path")
        {
            let mut direct_params = path_params.to_vec();
            for (parameter, value) in &mut direct_params {
                if parameter == "path" {
                    *value = value.trim_start_matches('/').to_owned();
                }
            }

            return match self.mount_routes.build_path_partial(0, &direct_params) {
                Ok((path, remaining)) if remaining.is_empty() => Ok(RouteUrlPath {
                    path,
                    protocol: String::new(),
                    host: String::new(),
                }),
                Ok(_) | Err(RouteError::PathParameterNamesMismatch { .. }) => {
                    Err(no_match(name, path_params))
                }
                Err(error) => Err(NamedRouterError::RouteFormatting(error)),
            };
        }

        let remaining_name = match self.name.as_deref() {
            None => name,
            Some(mount_name) if name.starts_with(&format!("{mount_name}:")) => {
                &name[mount_name.len() + 1..]
            }
            Some(_) => return Err(no_match(name, path_params)),
        };

        let (path_prefix, remaining_params) = self.format_prefix(path_params)?;
        let child_path = match self.router.url_path_for(remaining_name, &remaining_params) {
            Ok(path) => path,
            Err(NamedRouterError::NoMatchFound { .. }) => return Err(no_match(name, path_params)),
            Err(error) => return Err(error),
        };

        Ok(RouteUrlPath {
            path: format!(
                "{}{child_path}",
                path_prefix.trim_end_matches('/'),
                child_path = child_path.path
            ),
            protocol: child_path.protocol,
            // Starlette reconstructs the mounted URLPath with only its path
            // and protocol, intentionally dropping child Host metadata.
            host: String::new(),
        })
    }

    fn format_prefix(
        &self,
        path_params: &[(String, String)],
    ) -> Result<(String, Vec<(String, String)>), NamedRouterError> {
        let mut prefix_params = path_params.to_vec();
        let path_kwarg = prefix_params
            .iter()
            .find(|(name, _)| name == "path")
            .map(|(_, value)| value.clone());
        if let Some((_, value)) = prefix_params.iter_mut().find(|(name, _)| name == "path") {
            value.clear();
        } else {
            prefix_params.push((String::from("path"), String::new()));
        }
        let (path_prefix, mut remaining_params) = self
            .mount_routes
            .build_path_partial(0, &prefix_params)
            .map_err(NamedRouterError::RouteFormatting)?;
        if let Some(path_kwarg) = path_kwarg {
            remaining_params.push((String::from("path"), path_kwarg));
        }

        Ok((path_prefix, remaining_params))
    }
}

/// A Rust-native nested Host used by [`NamedRouter`] reverse lookup.
///
/// A named Host prefixes nested route names with `:`. An unnamed Host forwards
/// child names unchanged. A Host's own name addresses its host pattern through
/// the supplied `path` parameter.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NamedHost {
    name: Option<String>,
    pattern: HostPattern,
    parameter_names: Vec<String>,
    router: NamedRouter,
}

impl NamedHost {
    /// Creates a nested Host route.
    ///
    /// The host pattern uses the same built-in converter syntax as
    /// [`HostPattern`].
    ///
    /// # Errors
    ///
    /// Returns [`HostPatternError`] when the host pattern is invalid or uses
    /// an unsupported converter.
    pub fn new<P>(
        pattern: P,
        name: Option<String>,
        router: NamedRouter,
    ) -> Result<Self, HostPatternError>
    where
        P: Into<String>,
    {
        let pattern = HostPattern::new(pattern)?;
        let parameter_names = pattern.format_parameter_names()?;
        Ok(Self {
            name,
            pattern,
            parameter_names,
            router,
        })
    }

    fn url_path_for(
        &self,
        name: &str,
        path_params: &[(String, String)],
    ) -> Result<RouteUrlPath, NamedRouterError> {
        if self.name.as_deref() == Some(name)
            && path_params.iter().any(|(parameter, _)| parameter == "path")
        {
            let extra_params = path_params.iter().any(|(parameter, _)| {
                parameter != "path" && !self.parameter_names.iter().any(|name| name == parameter)
            });
            if extra_params {
                return Err(no_match(name, path_params));
            }

            let path = path_params
                .iter()
                .find(|(parameter, _)| parameter == "path")
                .map_or("", |(_, value)| value.as_str());
            let host_params = path_params
                .iter()
                .filter(|(parameter, _)| self.parameter_names.contains(parameter))
                .cloned()
                .collect::<Vec<_>>();
            if path_params
                .iter()
                .filter(|(parameter, _)| parameter == "path")
                .count()
                != 1
            {
                return Err(no_match(name, path_params));
            }
            let (host, remaining) = self
                .pattern
                .format_host_partial(&host_params)
                .map_err(NamedRouterError::HostFormatting)?;
            return if remaining.is_empty() {
                Ok(RouteUrlPath {
                    path: String::from(path),
                    protocol: String::new(),
                    host,
                })
            } else {
                Err(no_match(name, path_params))
            };
        }

        let remaining_name = match self.name.as_deref() {
            None => name,
            Some(host_name) if name.starts_with(&format!("{host_name}:")) => {
                &name[host_name.len() + 1..]
            }
            Some(_) => return Err(no_match(name, path_params)),
        };
        let host_params = path_params
            .iter()
            .filter(|(parameter, _)| self.parameter_names.contains(parameter))
            .cloned()
            .collect::<Vec<_>>();
        let (host, _) = self
            .pattern
            .format_host_partial(&host_params)
            .map_err(NamedRouterError::HostFormatting)?;
        let remaining_params = path_params
            .iter()
            .filter(|(parameter, _)| !self.parameter_names.contains(parameter))
            .cloned()
            .collect::<Vec<_>>();
        let child_path = match self.router.url_path_for(remaining_name, &remaining_params) {
            Ok(path) => path,
            Err(NamedRouterError::NoMatchFound { .. }) => return Err(no_match(name, path_params)),
            Err(error) => return Err(error),
        };
        Ok(RouteUrlPath {
            path: child_path.path,
            protocol: child_path.protocol,
            host,
        })
    }
}

fn no_match(name: &str, path_params: &[(String, String)]) -> NamedRouterError {
    NamedRouterError::NoMatchFound {
        name: String::from(name),
        path_params: path_params.to_vec(),
    }
}
