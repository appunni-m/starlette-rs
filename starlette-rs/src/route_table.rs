use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{Response, ResponseError};

/// An insertion-ordered table of HTTP paths.
///
/// Paths are case-sensitive and compared byte-for-byte as Rust strings. This
/// slice supports exact static paths, whole-segment `{name}` string parameters,
/// and whole-segment `{name:int}` integer parameters.
/// It does not implement slash redirects. Use
/// [`matches_detailed_with_root_path`](Self::matches_detailed_with_root_path)
/// when matching an ASGI scope with a `root_path`.
/// Registered method names are uppercased, and a `GET` route also accepts
/// `HEAD`, matching Starlette's `Route` behavior.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RouteTable {
    routes: Vec<Route>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct Route {
    path: String,
    path_segments: Option<Vec<PathSegment>>,
    methods: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum PathSegment {
    Static(String),
    StringParameter(String),
    IntegerParameter(String),
}

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
        /// Uppercased methods registered on that route, including implicit
        /// `HEAD` when `GET` was registered.
        allowed_methods: Vec<String>,
    },
    /// No route accepted the path.
    NotFound,
}

/// A detailed route decision that includes converted path parameters.
///
/// The bounded parameter syntax currently supported by [`RouteTable`] is a
/// complete path segment of the form `{name}` (or `{name:str}`) for non-empty
/// strings, and `{name:int}` for ASCII decimal digits. Integer parameters are
/// returned as canonical decimal strings, so values are not limited by the
/// platform's integer width. For example, `0007` is returned as `7`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DetailedRouteMatch {
    /// A route accepted both the path and method.
    Matched {
        /// Zero-based insertion index of the selected route.
        route_index: usize,
        /// Parameter names and converted values in pattern order.
        /// Integer values are canonical decimal strings.
        path_params: Vec<(String, String)>,
    },
    /// At least one route accepted the path, but none accepted the method.
    MethodNotAllowed {
        /// Zero-based insertion index of the first path-only match.
        route_index: usize,
        /// Uppercased methods registered on that route, including implicit
        /// `HEAD` when `GET` was registered.
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
}

impl Display for RouteError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::PathMustStartWithSlash => formatter.write_str("routed paths must start with '/'"),
        }
    }
}

impl Error for RouteError {}

impl RouteTable {
    /// Creates an empty route table.
    #[must_use]
    pub const fn new() -> Self {
        Self { routes: Vec::new() }
    }

    /// Adds one path and returns its stable insertion index.
    ///
    /// A path may be exact and static, or contain whole-segment string
    /// parameters such as `/items/{item}` and integer parameters such as
    /// `/items/{item_id:int}`. Integer parameters match ASCII digits only.
    /// Other segments remain exact static text. Methods are uppercased and
    /// deduplicated while retaining their input order.
    /// Registering `GET` also adds `HEAD`. An empty method collection follows
    /// Starlette's route matching behavior and accepts any method.
    ///
    /// # Errors
    ///
    /// Returns [`RouteError::PathMustStartWithSlash`] when `path` does not
    /// start with `/`.
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

        let route_index = self.routes.len();
        self.routes.push(Route {
            path_segments: parse_path(&path),
            path,
            methods: normalized_methods,
        });
        Ok(route_index)
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
    /// Starlette's ordered route selection. The supported converters are
    /// `{name}` / `{name:str}` for non-empty string segments and
    /// `{name:int}` for arbitrary-size canonical decimal strings.
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

fn get_route_path<'a>(path: &'a str, root_path: &str) -> &'a str {
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
            return (self.path == path).then(Vec::new);
        };

        let path_segments = path.split('/').collect::<Vec<_>>();
        if path_segments.len() != pattern_segments.len() {
            return None;
        }

        let mut path_params = Vec::new();
        for (pattern, value) in pattern_segments.iter().zip(path_segments) {
            match pattern {
                PathSegment::Static(expected) if expected == value => {}
                PathSegment::StringParameter(name) if !value.is_empty() => {
                    path_params.push((name.clone(), String::from(value)));
                }
                PathSegment::IntegerParameter(name)
                    if !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit()) =>
                {
                    let canonical = value.trim_start_matches('0');
                    let canonical = if canonical.is_empty() { "0" } else { canonical };
                    path_params.push((name.clone(), String::from(canonical)));
                }
                _ => return None,
            }
        }

        Some(path_params)
    }
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

fn parse_path(path: &str) -> Option<Vec<PathSegment>> {
    let mut has_parameter = false;
    let segments = path
        .split('/')
        .map(|segment| {
            let Some(parameter) = segment
                .strip_prefix('{')
                .and_then(|segment| segment.strip_suffix('}'))
            else {
                return PathSegment::Static(String::from(segment));
            };

            let (name, converter) = parameter
                .split_once(':')
                .map_or((parameter, "str"), |(name, converter)| (name, converter));
            if !valid_parameter_name(name) {
                return PathSegment::Static(String::from(segment));
            }

            match converter {
                "str" => {
                    has_parameter = true;
                    PathSegment::StringParameter(String::from(name))
                }
                "int" => {
                    has_parameter = true;
                    PathSegment::IntegerParameter(String::from(name))
                }
                _ => PathSegment::Static(String::from(segment)),
            }
        })
        .collect::<Vec<_>>();

    has_parameter.then_some(segments)
}

fn valid_parameter_name(name: &str) -> bool {
    let mut bytes = name.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    (first.is_ascii_alphabetic() || first == b'_')
        && bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
}
