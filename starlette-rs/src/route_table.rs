use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::sync::Arc;

use crate::{Response, ResponseError};

/// An insertion-ordered table of HTTP paths.
///
/// Paths are case-sensitive and compared byte-for-byte as Rust strings. This
/// slice supports exact static paths, whole-segment and inline `{name}` / `{name:str}`
/// string parameters, and Starlette's `{name:int}`, `{name:float}`, `{name:uuid}`,
/// and `{name:path}` converters. Additional converter names can be registered
/// with [`Self::register_converter`].
/// Slash redirect detection is available through
/// [`find_slash_redirect_path`](Self::find_slash_redirect_path). Use
/// [`matches_detailed_with_root_path`](Self::matches_detailed_with_root_path)
/// when matching an ASGI scope with a `root_path`.
/// Methods supplied to [`Self::add_route`] are uppercased, and a `GET` route
/// also accepts `HEAD`, matching Starlette's `Route` behavior. Methods added
/// later through [`Self::add_method`] preserve their supplied spelling and do
/// not synthesize `HEAD`, matching direct mutation of `Route.methods`.
#[derive(Clone, Debug, Default)]
pub struct RouteTable {
    routes: Vec<Route>,
    custom_converters: CustomPathConverterRegistry,
}

impl PartialEq for RouteTable {
    fn eq(&self, other: &Self) -> bool {
        self.routes == other.routes && self.custom_converters == other.custom_converters
    }
}

impl Eq for RouteTable {}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Route {
    path: String,
    path_segments: Option<Vec<PathSegment>>,
    methods: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum PathSegment {
    Static(String),
    Parameter {
        name: String,
        converter: RoutePathConverter,
    },
}

/// The Starlette converter responsible for a captured route parameter.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PathConverter {
    /// A non-empty string that does not contain `/`.
    String,
    /// An arbitrary-size decimal integer, stored in canonical decimal form.
    Integer,
    /// A decimal floating-point value.
    Float,
    /// A UUID path value.
    Uuid,
    /// A string that may contain `/` and may be empty.
    Path,
}

/// A custom Rust-native path converter.
///
/// Converters operate on strings in this API. [`Self::matches`] recognizes a
/// complete candidate capture, [`Self::convert`] maps a matched capture to its
/// string parameter value, and [`Self::to_string`] formats a supplied string
/// parameter for reverse URL generation. The route table tries candidate
/// captures from longest to shortest, then accepts the first one that lets the
/// remainder of the route match. Implementations should be deterministic and
/// side-effect free because matching can inspect multiple candidate slices.
pub trait CustomPathConverter: fmt::Debug + Send + Sync {
    /// Returns whether the complete candidate capture is accepted.
    fn matches(&self, value: &str) -> bool;

    /// Converts an accepted path capture to the string value exposed by the
    /// native route table.
    fn convert(&self, value: &str) -> String {
        String::from(value)
    }

    /// Formats a supplied string parameter for reverse URL generation.
    ///
    /// Return an error when the value cannot be represented by this
    /// converter. The route table also checks the returned string with
    /// [`Self::matches`].
    fn to_string(&self, value: &str) -> Result<String, String> {
        Ok(String::from(value))
    }
}

#[derive(Clone, Debug)]
enum RoutePathConverter {
    Builtin(PathConverter),
    Custom {
        name: String,
        converter: Arc<dyn CustomPathConverter>,
    },
}

impl PartialEq for RoutePathConverter {
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Builtin(left), Self::Builtin(right)) => left == right,
            (
                Self::Custom {
                    name: left_name,
                    converter: left_converter,
                },
                Self::Custom {
                    name: right_name,
                    converter: right_converter,
                },
            ) => left_name == right_name && Arc::ptr_eq(left_converter, right_converter),
            _ => false,
        }
    }
}

impl Eq for RoutePathConverter {}

impl RoutePathConverter {
    fn tag(&self) -> PathConverter {
        match self {
            Self::Builtin(converter) => *converter,
            Self::Custom { .. } => PathConverter::String,
        }
    }
}

/// A reusable registry of custom path converters.
///
/// Register a converter before adding routes that name it. Routes retain the
/// converter that was registered when each route was added, so replacing a
/// registry entry only affects routes registered later. Equality compares
/// converter registration identity; cloning a registry preserves that
/// identity.
#[derive(Clone, Debug, Default)]
pub struct CustomPathConverterRegistry {
    converters: Vec<(String, Arc<dyn CustomPathConverter>)>,
}

impl PartialEq for CustomPathConverterRegistry {
    fn eq(&self, other: &Self) -> bool {
        self.converters.len() == other.converters.len()
            && self.converters.iter().all(|(name, converter)| {
                other
                    .converters
                    .iter()
                    .find(|(other_name, _)| other_name == name)
                    .is_some_and(|(_, other)| Arc::ptr_eq(converter, other))
            })
    }
}

impl Eq for CustomPathConverterRegistry {}

impl CustomPathConverterRegistry {
    /// Creates an empty custom converter registry.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            converters: Vec::new(),
        }
    }

    /// Registers or replaces a converter for a path parameter name.
    ///
    /// Previously added routes retain the converter they were parsed with.
    /// Replacing a name therefore changes only routes added afterwards.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::InvalidPathConverterName`] when `name` is not an
    /// ASCII identifier accepted by the route-pattern grammar.
    pub fn register_converter<N, C>(&mut self, name: N, converter: C) -> Result<(), RouteError>
    where
        N: Into<String>,
        C: CustomPathConverter + 'static,
    {
        let name = name.into();
        if !valid_converter_name(&name) {
            return Err(RouteError::InvalidPathConverterName(name));
        }
        if let Some((_, existing)) = self
            .converters
            .iter_mut()
            .find(|(existing_name, _)| existing_name == &name)
        {
            *existing = Arc::new(converter);
        } else {
            self.converters.push((name, Arc::new(converter)));
        }
        Ok(())
    }

    pub(crate) fn converter(&self, name: &str) -> Option<Arc<dyn CustomPathConverter>> {
        self.converters
            .iter()
            .find(|(converter_name, _)| converter_name == name)
            .map(|(_, converter)| Arc::clone(converter))
    }
}

/// A path capture tagged with the converter Starlette applies to it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PathParameterCapture {
    /// Parameter name from the route pattern.
    pub name: String,
    /// Captured value; integer captures use canonical decimal spelling.
    pub value: String,
    /// Built-in converter declared for this parameter. Custom converters
    /// expose their string-converted value with `String` here.
    pub converter: PathConverter,
}

type PathParams = Vec<(String, String)>;
type PathMatchMemo = HashMap<(usize, usize), Option<PathParams>>;

/// The outcome of matching an HTTP path and method against a [`RouteTable`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RouteMatch {
    /// A route accepted both the path and method.
    Matched {
        /// Zero-based insertion index of the selected route.
        route_index: usize,
    },
    /// At least one route accepted the path, but none accepted the method.
    MethodNotAllowed {
        /// Zero-based insertion index of the first path-only match.
        route_index: usize,
        /// Methods stored on that route, including constructor-normalized
        /// names and implicit `HEAD` from `GET`; later additions preserve the
        /// spelling supplied to [`RouteTable::add_method`].
        allowed_methods: Vec<String>,
    },
    /// No route accepted the path.
    NotFound,
}

/// A detailed route decision that includes captured path parameters in a
/// representation suitable for the Python compatibility boundary.
///
/// Parameter syntax follows Starlette's path pattern grammar: `{name}` or
/// `{name:str}`, `{name:int}`, `{name:float}`, `{name:uuid}`, and
/// `{name:path}`. The converter patterns match Starlette: strings use
/// `[^/]+`, integers use `[0-9]+`, floats use `[0-9]+(\.[0-9]+)?`, UUIDs
/// use the 8-4-4-4-12 hexadecimal form with optional hyphens, and paths use
/// `.*` (which may be empty and does not cross line feeds). Integer values are
/// returned as canonical decimal strings, so values are not limited by the
/// platform's integer width. Registered custom converters apply their
/// string-valued `convert` method to each accepted capture.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DetailedRouteMatch {
    /// A route accepted both the path and method.
    Matched {
        /// Zero-based insertion index of the selected route.
        route_index: usize,
        /// Parameter names and converted values in pattern order.
        /// Integer values are canonical decimal strings. Other values preserve
        /// their matched spelling for conversion at the Python boundary.
        path_params: Vec<(String, String)>,
    },
    /// At least one route accepted the path, but none accepted the method.
    MethodNotAllowed {
        /// Zero-based insertion index of the first path-only match.
        route_index: usize,
        /// Methods stored on that route, including constructor-normalized
        /// names and implicit `HEAD` from `GET`; later additions preserve the
        /// spelling supplied to [`RouteTable::add_method`].
        allowed_methods: Vec<String>,
        /// Converted parameters captured by the first path-only match.
        path_params: Vec<(String, String)>,
    },
    /// No route accepted the path.
    NotFound,
}

impl DetailedRouteMatch {
    /// Builds the Starlette text response for a path-only match or route miss.
    ///
    /// A full match has no fallback response and returns `Ok(None)`. A partial
    /// match produces status 405 with its comma-separated `Allow` methods
    /// first, followed by synthesized content headers. A miss produces the
    /// standard plain-text 404 response.
    ///
    /// # Errors
    ///
    /// Returns a response header encoding error if an allowed method cannot
    /// be represented as a Latin-1 `Allow` header.
    pub fn fallback_response(&self) -> Result<Option<Response>, ResponseError> {
        match self {
            Self::Matched { .. } => Ok(None),
            Self::MethodNotAllowed {
                allowed_methods, ..
            } => method_not_allowed_response(allowed_methods),
            Self::NotFound => RouteMatch::NotFound.fallback_response(),
        }
    }

    fn into_legacy_match(self) -> RouteMatch {
        match self {
            Self::Matched { route_index, .. } => RouteMatch::Matched { route_index },
            Self::MethodNotAllowed {
                route_index,
                allowed_methods,
                ..
            } => RouteMatch::MethodNotAllowed {
                route_index,
                allowed_methods,
            },
            Self::NotFound => RouteMatch::NotFound,
        }
    }
}

impl RouteMatch {
    /// Builds the Starlette text response for a path-only match or route miss.
    ///
    /// A full match has no fallback response and returns `Ok(None)`. A partial
    /// match produces status 405 with its comma-separated `Allow` methods
    /// first, followed by synthesized content headers. A miss produces the
    /// standard plain-text 404 response.
    ///
    /// # Errors
    ///
    /// Returns a response header encoding error if an allowed method cannot
    /// be represented as a Latin-1 `Allow` header.
    pub fn fallback_response(&self) -> Result<Option<Response>, ResponseError> {
        match self {
            Self::Matched { .. } => Ok(None),
            Self::MethodNotAllowed {
                allowed_methods, ..
            } => method_not_allowed_response(allowed_methods),
            Self::NotFound => Ok(Some(Response::plain_text_with_status(404, "Not Found"))),
        }
    }
}

/// A route registration error.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RouteError {
    /// Starlette requires routed paths to start with `/`.
    PathMustStartWithSlash,
    /// A custom converter registration name is not a valid ASCII identifier.
    InvalidPathConverterName(String),
    /// A syntactically valid path parameter names an unsupported converter.
    UnknownPathConverter(String),
    /// A parameter name occurs more than once in a path pattern.
    DuplicatePathParameter(String),
    /// The requested insertion index is not present in the table.
    RouteIndexOutOfBounds(usize),
    /// A replacement name appears in the path without a declared converter.
    UnknownPathParameter(String),
    /// Parameter values contain a duplicate name.
    DuplicatePathParameterValue(String),
    /// A strict path build did not receive exactly the route's parameter names.
    PathParameterNamesMismatch {
        /// Parameter names declared by the route, in pattern order.
        expected: Vec<String>,
        /// Parameter names supplied by the caller, in input order.
        provided: Vec<String>,
    },
    /// A preformatted path parameter violates its built-in converter contract.
    InvalidPathParameter {
        /// Parameter name from the route pattern.
        name: String,
        /// Stable description of the rejected value.
        reason: &'static str,
    },
    /// A custom converter could not format a reverse URL parameter.
    CustomPathConverterFormatting {
        /// Parameter name from the route pattern.
        name: String,
        /// Converter-specific formatting failure or validation detail.
        reason: String,
    },
}

impl Display for RouteError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::PathMustStartWithSlash => formatter.write_str("routed paths must start with '/'"),
            Self::InvalidPathConverterName(name) => {
                write!(formatter, "invalid path converter name '{name}'")
            }
            Self::UnknownPathConverter(name) => {
                write!(formatter, "unknown path converter '{name}'")
            }
            Self::DuplicatePathParameter(name) => {
                write!(formatter, "duplicate path parameter '{name}'")
            }
            Self::RouteIndexOutOfBounds(route_index) => {
                write!(formatter, "route index {route_index} is out of bounds")
            }
            Self::UnknownPathParameter(name) => {
                write!(formatter, "path parameter '{name}' has no route converter")
            }
            Self::DuplicatePathParameterValue(name) => {
                write!(
                    formatter,
                    "path parameter '{name}' was supplied more than once"
                )
            }
            Self::PathParameterNamesMismatch { expected, provided } => write!(
                formatter,
                "route path parameters {expected:?} do not match supplied parameters {provided:?}"
            ),
            Self::InvalidPathParameter { name, reason } => {
                write!(formatter, "invalid path parameter '{name}': {reason}")
            }
            Self::CustomPathConverterFormatting { name, reason } => {
                write!(formatter, "custom path converter '{name}' failed: {reason}")
            }
        }
    }
}

impl Error for RouteError {}

impl RouteTable {
    /// Creates an empty route table.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            routes: Vec::new(),
            custom_converters: CustomPathConverterRegistry::new(),
        }
    }

    /// Creates an empty route table with an existing custom converter registry.
    #[must_use]
    pub fn with_custom_converters(custom_converters: CustomPathConverterRegistry) -> Self {
        Self {
            routes: Vec::new(),
            custom_converters,
        }
    }

    /// Registers or replaces a custom converter for routes added afterwards.
    ///
    /// Routes already in the table retain the converter instance used when
    /// they were parsed.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::InvalidPathConverterName`] for names outside the
    /// route grammar's ASCII identifier syntax.
    pub fn register_converter<N, C>(&mut self, name: N, converter: C) -> Result<(), RouteError>
    where
        N: Into<String>,
        C: CustomPathConverter + 'static,
    {
        self.custom_converters.register_converter(name, converter)
    }

    /// Adds one path and returns its stable insertion index.
    ///
    /// A path may be exact and static, or contain Starlette path parameters
    /// such as `/items/{item_id:int}` and `/assets/{file:path}`, as well as
    /// converters registered before this call. Parameters may be embedded in
    /// literal path text. Methods are uppercased and
    /// deduplicated while retaining their input order.
    /// Registering `GET` also adds `HEAD`. An empty method collection follows
    /// Starlette's route matching behavior and accepts any method.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::PathMustStartWithSlash`] when `path` does not
    /// start with `/`, [`RouteError::UnknownPathConverter`] for an unknown
    /// converter, or [`RouteError::DuplicatePathParameter`] when a parameter
    /// name occurs more than once.
    pub fn add_route<P, M, S>(&mut self, path: P, methods: M) -> Result<usize, RouteError>
    where
        P: Into<String>,
        M: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let path = path.into();
        if !path.starts_with('/') {
            return Err(RouteError::PathMustStartWithSlash);
        }

        let mut normalized_methods = Vec::new();
        for method in methods {
            let method = method.as_ref().to_ascii_uppercase();
            if !normalized_methods.contains(&method) {
                normalized_methods.push(method);
            }
        }

        if normalized_methods.iter().any(|method| method == "GET")
            && !normalized_methods.iter().any(|method| method == "HEAD")
        {
            normalized_methods.push(String::from("HEAD"));
        }

        self.add_route_with_exact_methods(path, normalized_methods)
    }

    /// Adds a route with its method values already finalized by the caller.
    ///
    /// Method strings are retained exactly, and `GET` does not imply `HEAD`.
    /// This is intended for adapters that import an existing Starlette
    /// `Route.methods` collection, whose constructor normalization and later
    /// direct mutations have already taken place.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::PathMustStartWithSlash`] when `path` does not
    /// start with `/`, [`RouteError::UnknownPathConverter`] for an unknown
    /// converter, or [`RouteError::DuplicatePathParameter`] when a parameter
    /// name occurs more than once.
    pub fn add_route_with_exact_methods<P, M, S>(
        &mut self,
        path: P,
        methods: M,
    ) -> Result<usize, RouteError>
    where
        P: Into<String>,
        M: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let path = path.into();
        if !path.starts_with('/') {
            return Err(RouteError::PathMustStartWithSlash);
        }

        let mut exact_methods = Vec::new();
        for method in methods {
            let method = method.as_ref();
            if !exact_methods
                .iter()
                .any(|existing: &String| existing == method)
            {
                exact_methods.push(String::from(method));
            }
        }

        let route_index = self.routes.len();
        let path_segments = parse_path(&path, &self.custom_converters)?;
        self.routes.push(Route {
            path_segments,
            path,
            methods: exact_methods,
        });
        Ok(route_index)
    }

    /// Adds one method to an already registered route.
    ///
    /// This models mutating Starlette's public `Route.methods` set. It stores
    /// the supplied method exactly as written and does not apply constructor
    /// normalization or infer `HEAD` when adding `GET`. Adding a value that is
    /// already present is a no-op, matching set insertion.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::RouteIndexOutOfBounds`] when `route_index` does
    /// not identify a registered route.
    pub fn add_method<S>(&mut self, route_index: usize, method: S) -> Result<(), RouteError>
    where
        S: AsRef<str>,
    {
        let route = self
            .routes
            .get_mut(route_index)
            .ok_or(RouteError::RouteIndexOutOfBounds(route_index))?;
        let method = method.as_ref();
        if !route.methods.iter().any(|existing| existing == method) {
            route.methods.push(String::from(method));
        }
        Ok(())
    }

    /// Builds a route path from converter-formatted parameter values.
    ///
    /// Parameter names must exactly match those declared by the route. The
    /// caller supplies each parameter as a string. This method applies the
    /// registered custom converter's `to_string` method and validates the
    /// result with `matches`; built-in values retain their documented
    /// formatting rules. Values are not
    /// percent-escaped, matching Starlette's `URLPath` behavior.
    ///
    /// # Errors
    ///
    /// Returns a route-index, parameter-name, duplicate-value, or converter
    /// output error.
    pub fn build_path(
        &self,
        route_index: usize,
        path_params: &[(String, String)],
    ) -> Result<String, RouteError> {
        let route = self
            .routes
            .get(route_index)
            .ok_or(RouteError::RouteIndexOutOfBounds(route_index))?;
        let expected = route
            .path_segments
            .iter()
            .flatten()
            .filter_map(|segment| match segment {
                PathSegment::Parameter { name, .. } => Some(name.clone()),
                PathSegment::Static(_) => None,
            })
            .collect::<Vec<_>>();
        let mut provided_set = HashSet::new();
        for (name, _) in path_params {
            if !provided_set.insert(name.as_str()) {
                return Err(RouteError::DuplicatePathParameterValue(name.clone()));
            }
        }
        let provided = path_params
            .iter()
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        if expected.len() != provided.len()
            || expected
                .iter()
                .any(|name| !provided_set.contains(name.as_str()))
        {
            return Err(RouteError::PathParameterNamesMismatch { expected, provided });
        }

        let (path, remaining) = self.build_path_partial(route_index, path_params)?;
        debug_assert!(remaining.is_empty());
        Ok(path)
    }

    /// Returns the path parameter names for one registered route in pattern order.
    pub(crate) fn path_parameter_names(
        &self,
        route_index: usize,
    ) -> Result<Vec<String>, RouteError> {
        let route = self
            .routes
            .get(route_index)
            .ok_or(RouteError::RouteIndexOutOfBounds(route_index))?;
        Ok(route
            .path_segments
            .iter()
            .flatten()
            .filter_map(|segment| match segment {
                PathSegment::Parameter { name, .. } => Some(name.clone()),
                PathSegment::Static(_) => None,
            })
            .collect())
    }

    /// Replaces supplied route parameters and returns values not used by the
    /// pattern, matching the partial substitution used by Starlette `Mount`.
    ///
    /// Missing route parameters remain as `{name}` placeholders. Extra values
    /// remain in the returned vector in input order so a caller can pass them
    /// to a nested route. Supplied values are formatted by the corresponding
    /// converter.
    ///
    /// # Errors
    ///
    /// Returns a route-index, duplicate-value, or converter-output error.
    pub fn build_path_partial(
        &self,
        route_index: usize,
        path_params: &[(String, String)],
    ) -> Result<(String, Vec<(String, String)>), RouteError> {
        let route = self
            .routes
            .get(route_index)
            .ok_or(RouteError::RouteIndexOutOfBounds(route_index))?;
        let mut converters = HashMap::new();
        let mut output = String::new();
        if let Some(pattern) = &route.path_segments {
            for segment in pattern {
                match segment {
                    PathSegment::Static(literal) => output.push_str(literal),
                    PathSegment::Parameter { name, converter } => {
                        output.push('{');
                        output.push_str(name);
                        output.push('}');
                        converters.insert(name.as_str(), converter);
                    }
                }
            }
        } else {
            output.push_str(&route.path);
        }

        let mut provided_names = HashSet::new();
        let mut consumed = HashSet::new();
        for (name, value) in path_params {
            if !provided_names.insert(name.as_str()) {
                return Err(RouteError::DuplicatePathParameterValue(name.clone()));
            }
            let placeholder = format!("{{{name}}}");
            if !output.contains(&placeholder) {
                continue;
            }
            let Some(converter) = converters.get(name.as_str()) else {
                return Err(RouteError::UnknownPathParameter(name.clone()));
            };
            let formatted = format_path_parameter(name, value, converter)?;
            output = output.replace(&placeholder, &formatted);
            consumed.insert(name.as_str());
        }

        let remaining = path_params
            .iter()
            .filter(|(name, _)| !consumed.contains(name.as_str()))
            .cloned()
            .collect();
        Ok((output, remaining))
    }

    /// Tags matched path parameters with their route converters.
    ///
    /// `path_params` must be the captures returned by a match of
    /// `route_index`. Integer captures remain arbitrary-size canonical decimal
    /// strings; `converter` carries the type information needed by a native
    /// caller or a language-specific boundary.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::RouteIndexOutOfBounds`] when the route index is
    /// absent, [`RouteError::DuplicatePathParameterValue`] for duplicate
    /// capture names, or [`RouteError::PathParameterNamesMismatch`] when the
    /// capture names differ from the route pattern.
    pub fn capture_path_parameters(
        &self,
        route_index: usize,
        path_params: &[(String, String)],
    ) -> Result<Vec<PathParameterCapture>, RouteError> {
        let route = self
            .routes
            .get(route_index)
            .ok_or(RouteError::RouteIndexOutOfBounds(route_index))?;
        let parameters = route.path_segments.as_deref().unwrap_or_default();
        let expected = parameters
            .iter()
            .filter_map(|segment| match segment {
                PathSegment::Parameter { name, .. } => Some(name.clone()),
                PathSegment::Static(_) => None,
            })
            .collect::<Vec<_>>();
        let mut provided_names = HashSet::new();
        for (name, _) in path_params {
            if !provided_names.insert(name.as_str()) {
                return Err(RouteError::DuplicatePathParameterValue(name.clone()));
            }
        }
        let provided = path_params
            .iter()
            .map(|(name, _)| name.clone())
            .collect::<Vec<_>>();
        if expected.len() != provided.len()
            || expected
                .iter()
                .any(|name| !provided_names.contains(name.as_str()))
        {
            return Err(RouteError::PathParameterNamesMismatch { expected, provided });
        }

        path_params
            .iter()
            .map(|(name, value)| {
                let converter = parameters
                    .iter()
                    .find_map(|segment| match segment {
                        PathSegment::Parameter {
                            name: parameter_name,
                            converter,
                        } if parameter_name == name => Some(converter.tag()),
                        PathSegment::Static(_) | PathSegment::Parameter { .. } => None,
                    })
                    .ok_or_else(|| RouteError::UnknownPathParameter(name.clone()))?;
                Ok(PathParameterCapture {
                    name: name.clone(),
                    value: value.clone(),
                    converter,
                })
            })
            .collect()
    }

    /// Matches a path and method, preserving Starlette's ordered fallback.
    ///
    /// The first route matching both values wins. If no route matches both,
    /// the first route with the path is returned as
    /// [`RouteMatch::MethodNotAllowed`]. This lets a later full match take
    /// precedence over an earlier path-only match. This compatibility method
    /// omits any captured path parameters; use [`Self::matches_detailed`] to
    /// retrieve them.
    #[must_use]
    pub fn matches(&self, path: &str, method: &str) -> RouteMatch {
        self.matches_detailed(path, method).into_legacy_match()
    }

    /// Matches a path and method and returns converted path parameters.
    ///
    /// The first route matching both values wins. If no route matches both,
    /// the first route matching the path is returned as a method partial,
    /// including the parameters captured by that path match. A later full
    /// match takes precedence over an earlier partial match, matching
    /// Starlette's ordered route selection. Captured values preserve their
    /// lexical spelling, except integer parameters, which are canonical
    /// arbitrary-size decimal strings. Custom converters return their
    /// string-converted values directly.
    #[must_use]
    pub fn matches_detailed(&self, path: &str, method: &str) -> DetailedRouteMatch {
        let mut first_partial = None;

        for (route_index, route) in self.routes.iter().enumerate() {
            let Some(path_params) = route.match_path(path) else {
                continue;
            };

            if route.methods.is_empty() || route.methods.iter().any(|allowed| allowed == method) {
                return DetailedRouteMatch::Matched {
                    route_index,
                    path_params,
                };
            }

            if first_partial.is_none() {
                first_partial = Some((route_index, route.methods.clone(), path_params));
            }
        }

        match first_partial {
            Some((route_index, allowed_methods, path_params)) => {
                DetailedRouteMatch::MethodNotAllowed {
                    route_index,
                    allowed_methods,
                    path_params,
                }
            }
            None => DetailedRouteMatch::NotFound,
        }
    }

    /// Matches an ASGI path after removing a matching `root_path` prefix.
    ///
    /// The prefix is removed only when it ends at a path boundary, matching
    /// Starlette's `get_route_path` behavior. A path equal to `root_path`
    /// becomes the empty string; a partial textual prefix such as `/apiary`
    /// is left unchanged for a `root_path` of `/api`.
    #[must_use]
    pub fn matches_detailed_with_root_path(
        &self,
        path: &str,
        root_path: &str,
        method: &str,
    ) -> DetailedRouteMatch {
        self.matches_detailed(get_route_path(path, root_path), method)
    }

    /// Returns Starlette's trailing-slash alternative when it matches a route.
    ///
    /// `path` is the full ASGI scope path. The method toggles its trailing
    /// slash using Starlette's `rstrip("/")` behavior when the path relative
    /// to `root_path` ends in `/`, or appends `/` otherwise. It returns the
    /// candidate only when a route accepts its path, including a method-only
    /// partial match. A relative path of exactly `/` is never redirected.
    /// This checks only routes registered in this table and applies their
    /// registered converter matchers; it does not recurse into mounted routers.
    #[must_use]
    pub fn find_slash_redirect_path(
        &self,
        path: &str,
        root_path: &str,
        method: &str,
    ) -> Option<String> {
        let candidate = self.slash_redirect_candidate(path, root_path)?;

        match self.matches_detailed_with_root_path(&candidate, root_path, method) {
            DetailedRouteMatch::Matched { .. } | DetailedRouteMatch::MethodNotAllowed { .. } => {
                Some(candidate)
            }
            DetailedRouteMatch::NotFound => None,
        }
    }

    /// Returns the number of registered routes.
    #[must_use]
    pub fn len(&self) -> usize {
        self.routes.len()
    }

    /// Returns whether the table has no registered routes.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.routes.is_empty()
    }
}

pub(crate) fn get_route_path<'a>(path: &'a str, root_path: &str) -> &'a str {
    if root_path.is_empty() || !path.starts_with(root_path) {
        return path;
    }
    if path.len() == root_path.len() {
        return "";
    }
    if path[root_path.len()..].starts_with('/') {
        return &path[root_path.len()..];
    }
    path
}

impl Route {
    fn match_path(&self, path: &str) -> Option<Vec<(String, String)>> {
        let Some(pattern_segments) = &self.path_segments else {
            return (path == self.path || path.strip_suffix('\n') == Some(self.path.as_str()))
                .then(Vec::new);
        };
        match_path_segments(pattern_segments, path, 0, 0, &mut HashMap::new())
    }
}

fn match_path_segments(
    pattern: &[PathSegment],
    path: &str,
    pattern_index: usize,
    path_offset: usize,
    memo: &mut PathMatchMemo,
) -> Option<PathParams> {
    let key = (pattern_index, path_offset);
    if let Some(cached) = memo.get(&key) {
        return cached.clone();
    }

    let result = if pattern_index == pattern.len() {
        regex_end_matches(path, path_offset).then(Vec::new)
    } else {
        match &pattern[pattern_index] {
            PathSegment::Static(literal) => path
                .get(path_offset..)
                .and_then(|remaining| remaining.strip_prefix(literal))
                .and_then(|_| {
                    match_path_segments(
                        pattern,
                        path,
                        pattern_index + 1,
                        path_offset + literal.len(),
                        memo,
                    )
                }),
            PathSegment::Parameter { name, converter } => {
                let mut matched = None;
                for end in converter_candidate_ends(path, path_offset, converter) {
                    let Some(mut suffix) =
                        match_path_segments(pattern, path, pattern_index + 1, end, memo)
                    else {
                        continue;
                    };

                    if let Some(value) = path.get(path_offset..end) {
                        let value = match converter {
                            RoutePathConverter::Builtin(PathConverter::Integer) => {
                                canonical_integer(value)
                            }
                            RoutePathConverter::Builtin(_) => String::from(value),
                            RoutePathConverter::Custom { converter, .. } => {
                                converter.convert(value)
                            }
                        };
                        suffix.insert(0, (name.clone(), value));
                        matched = Some(suffix);
                    }
                    break;
                }
                matched
            }
        }
    };

    memo.insert(key, result.clone());
    result
}

fn regex_end_matches(path: &str, offset: usize) -> bool {
    offset == path.len() || (path.ends_with('\n') && offset + '\n'.len_utf8() == path.len())
}

fn converter_candidate_ends(
    path: &str,
    offset: usize,
    converter: &RoutePathConverter,
) -> Vec<usize> {
    let Some(suffix) = path.get(offset..) else {
        return Vec::new();
    };
    let mut ends = Vec::new();

    match converter {
        RoutePathConverter::Builtin(PathConverter::String) => {
            for (relative, character) in suffix.char_indices() {
                if character == '/' {
                    break;
                }
                ends.push(offset + relative + character.len_utf8());
            }
        }
        RoutePathConverter::Builtin(PathConverter::Integer) => {
            for (relative, byte) in suffix.bytes().enumerate() {
                if !byte.is_ascii_digit() {
                    break;
                }
                ends.push(offset + relative + 1);
            }
        }
        RoutePathConverter::Builtin(PathConverter::Float) => {
            let digit_end = suffix.bytes().take_while(u8::is_ascii_digit).count();
            if digit_end > 0 {
                let fractional_start = offset + digit_end;
                if suffix.as_bytes().get(digit_end) == Some(&b'.') {
                    let fractional_digits = suffix[digit_end + 1..]
                        .bytes()
                        .take_while(u8::is_ascii_digit)
                        .count();
                    for count in (1..=fractional_digits).rev() {
                        ends.push(fractional_start + 1 + count);
                    }
                }
                for count in (1..=digit_end).rev() {
                    ends.push(offset + count);
                }
            }
        }
        RoutePathConverter::Builtin(PathConverter::Uuid) => {
            for (relative, byte) in suffix.bytes().enumerate().take(36) {
                if !byte.is_ascii_hexdigit() && byte != b'-' {
                    break;
                }
                let end = offset + relative + 1;
                if valid_uuid_lexeme(&path[offset..end]) {
                    ends.push(end);
                }
            }
            ends.reverse();
        }
        RoutePathConverter::Builtin(PathConverter::Path) => {
            for (relative, character) in suffix.char_indices() {
                if character == '\n' {
                    break;
                }
                ends.push(offset + relative + character.len_utf8());
            }
            ends.push(offset);
        }
        RoutePathConverter::Custom { converter, .. } => {
            for (relative, character) in suffix.char_indices() {
                ends.push(offset + relative + character.len_utf8());
            }
            ends.push(offset);
            ends.reverse();
            ends.retain(|end| {
                path.get(offset..*end)
                    .is_some_and(|candidate| converter.matches(candidate))
            });
            return ends;
        }
    }

    if matches!(
        converter,
        RoutePathConverter::Builtin(
            PathConverter::String | PathConverter::Integer | PathConverter::Path
        )
    ) {
        ends.reverse();
    }
    ends
}

fn valid_uuid_lexeme(value: &str) -> bool {
    let bytes = value.as_bytes();
    let mut offset = 0;

    if !consume_uuid_hex_group(bytes, &mut offset, 8) {
        return false;
    }
    for width in [4, 4, 4, 12] {
        if bytes.get(offset) == Some(&b'-') {
            offset += 1;
        }
        if !consume_uuid_hex_group(bytes, &mut offset, width) {
            return false;
        }
    }
    offset == bytes.len()
}

fn consume_uuid_hex_group(bytes: &[u8], offset: &mut usize, width: usize) -> bool {
    let Some(end) = (*offset).checked_add(width) else {
        return false;
    };
    if !bytes
        .get(*offset..end)
        .is_some_and(|group| group.iter().all(u8::is_ascii_hexdigit))
    {
        return false;
    }
    *offset = end;
    true
}

fn canonical_integer(value: &str) -> String {
    let without_leading_zeroes = value.trim_start_matches('0');
    if without_leading_zeroes.is_empty() {
        String::from("0")
    } else {
        String::from(without_leading_zeroes)
    }
}

fn format_path_parameter(
    name: &str,
    value: &str,
    converter: &RoutePathConverter,
) -> Result<String, RouteError> {
    let invalid = |reason| RouteError::InvalidPathParameter {
        name: String::from(name),
        reason,
    };

    match converter {
        RoutePathConverter::Builtin(PathConverter::String) if value.is_empty() => {
            Err(invalid("string converter values must not be empty"))
        }
        RoutePathConverter::Builtin(PathConverter::String) if value.contains('/') => Err(invalid(
            "string converter values may not contain path separators",
        )),
        RoutePathConverter::Builtin(PathConverter::Integer)
            if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) =>
        {
            Err(invalid(
                "integer converter values must be non-negative ASCII decimal digits",
            ))
        }
        RoutePathConverter::Builtin(PathConverter::Integer) => Ok(canonical_integer(value)),
        RoutePathConverter::Builtin(PathConverter::Float) if !valid_float_lexeme(value) => Err(
            invalid("float converter values must use non-negative decimal notation"),
        ),
        RoutePathConverter::Builtin(
            PathConverter::Float | PathConverter::Uuid | PathConverter::Path,
        )
        | RoutePathConverter::Builtin(PathConverter::String) => Ok(String::from(value)),
        RoutePathConverter::Custom { name, converter } => {
            let formatted = converter.to_string(value).map_err(|reason| {
                RouteError::CustomPathConverterFormatting {
                    name: name.clone(),
                    reason,
                }
            })?;
            if converter.matches(&formatted) {
                Ok(formatted)
            } else {
                Err(RouteError::CustomPathConverterFormatting {
                    name: name.clone(),
                    reason: String::from("formatted value is not accepted by the converter"),
                })
            }
        }
    }
}

fn valid_float_lexeme(value: &str) -> bool {
    // Python's `float(-0.0) >= 0.0` is true, and its fixed-point formatter
    // consequently emits `-0` after trimming the fractional zeroes.
    if value == "-0" {
        return true;
    }

    let bytes = value.as_bytes();
    let digit_end = bytes
        .iter()
        .take_while(|byte| byte.is_ascii_digit())
        .count();
    if digit_end == 0 {
        return false;
    }
    if digit_end == bytes.len() {
        return true;
    }
    bytes.get(digit_end) == Some(&b'.')
        && digit_end + 1 < bytes.len()
        && bytes[digit_end + 1..].iter().all(u8::is_ascii_digit)
}

fn method_not_allowed_response(
    allowed_methods: &[String],
) -> Result<Option<Response>, ResponseError> {
    let allow = allowed_methods.join(", ");
    let response = Response::from_content(
        405,
        b"Method Not Allowed".to_vec(),
        Some("text/plain"),
        [(String::from("allow"), allow)],
    )?;
    Ok(Some(response))
}

fn parse_path(
    path: &str,
    custom_converters: &CustomPathConverterRegistry,
) -> Result<Option<Vec<PathSegment>>, RouteError> {
    let bytes = path.as_bytes();
    let mut segments = Vec::new();
    let mut parameter_names = HashSet::new();
    let mut literal_start = 0;
    let mut cursor = 0;

    while cursor < bytes.len() {
        if bytes[cursor] != b'{' {
            cursor += 1;
            continue;
        }

        let Some((end, name, converter_name)) = parse_parameter(path, cursor) else {
            cursor += 1;
            continue;
        };
        if literal_start < cursor {
            segments.push(PathSegment::Static(String::from(
                &path[literal_start..cursor],
            )));
        }

        let converter = if let Some(converter) = custom_converters.converter(converter_name) {
            RoutePathConverter::Custom {
                name: String::from(converter_name),
                converter,
            }
        } else {
            RoutePathConverter::Builtin(match converter_name {
                "str" => PathConverter::String,
                "int" => PathConverter::Integer,
                "float" => PathConverter::Float,
                "uuid" => PathConverter::Uuid,
                "path" => PathConverter::Path,
                other => return Err(RouteError::UnknownPathConverter(String::from(other))),
            })
        };
        if !parameter_names.insert(name) {
            return Err(RouteError::DuplicatePathParameter(String::from(name)));
        }

        segments.push(PathSegment::Parameter {
            name: String::from(name),
            converter,
        });
        cursor = end;
        literal_start = end;
    }

    if literal_start < path.len() {
        segments.push(PathSegment::Static(String::from(&path[literal_start..])));
    }

    if segments
        .iter()
        .any(|segment| matches!(segment, PathSegment::Parameter { .. }))
    {
        Ok(Some(segments))
    } else {
        Ok(None)
    }
}

fn parse_parameter(path: &str, start: usize) -> Option<(usize, &str, &str)> {
    let bytes = path.as_bytes();
    let name_start = start.checked_add(1)?;
    let name_end = scan_identifier(bytes, name_start)?;
    let name = path.get(name_start..name_end)?;
    let mut cursor = name_end;

    let converter = if bytes.get(cursor) == Some(&b':') {
        cursor += 1;
        let converter_start = cursor;
        cursor = scan_identifier(bytes, cursor)?;
        path.get(converter_start..cursor)?
    } else {
        "str"
    };

    (bytes.get(cursor) == Some(&b'}')).then_some((cursor + 1, name, converter))
}

fn scan_identifier(bytes: &[u8], start: usize) -> Option<usize> {
    let first = *bytes.get(start)?;
    if !first.is_ascii_alphabetic() && first != b'_' {
        return None;
    }
    let mut end = start + 1;
    while bytes
        .get(end)
        .is_some_and(|byte| byte.is_ascii_alphanumeric() || *byte == b'_')
    {
        end += 1;
    }
    Some(end)
}

fn valid_converter_name(name: &str) -> bool {
    let bytes = name.as_bytes();
    scan_identifier(bytes, 0) == Some(bytes.len())
}
