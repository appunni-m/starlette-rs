use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{Response, ResponseError};

/// An insertion-ordered table of HTTP paths.
///
/// Paths are case-sensitive and compared byte-for-byte as Rust strings. This
/// slice supports exact static paths, whole-segment and inline `{name}` / `{name:str}`
/// string parameters, and Starlette's `{name:int}`, `{name:float}`, `{name:uuid}`,
/// and `{name:path}` converters.
/// Only these five built-in converters are recognized by the Rust-native
/// table; Python-registered custom URL converters remain outside this API.
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
    Parameter {
        name: String,
        converter: PathConverter,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum PathConverter {
    String,
    Integer,
    Float,
    Uuid,
    Path,
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
        /// Uppercased methods registered on that route, including implicit
        /// `HEAD` when `GET` was registered.
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
/// platform's integer width. Other values preserve their matched spelling for
/// conversion at the Python boundary.
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
    /// A syntactically valid path parameter names an unsupported converter.
    UnknownPathConverter(String),
    /// A parameter name occurs more than once in a path pattern.
    DuplicatePathParameter(String),
}

impl Display for RouteError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::PathMustStartWithSlash => formatter.write_str("routed paths must start with '/'"),
            Self::UnknownPathConverter(name) => {
                write!(formatter, "unknown path converter '{name}'")
            }
            Self::DuplicatePathParameter(name) => {
                write!(formatter, "duplicate path parameter '{name}'")
            }
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
    /// A path may be exact and static, or contain Starlette path parameters
    /// such as `/items/{item_id:int}` and `/assets/{file:path}`. Parameters
    /// may be embedded in literal path text. Methods are uppercased and
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

        let route_index = self.routes.len();
        let path_segments = parse_path(&path)?;
        self.routes.push(Route {
            path_segments,
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
    /// Starlette's ordered route selection. Captured values preserve their
    /// lexical spelling, except integer parameters, which are canonical
    /// arbitrary-size decimal strings. The Python boundary converts float and
    /// UUID values into their Starlette runtime types.
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
                        let value = if *converter == PathConverter::Integer {
                            canonical_integer(value)
                        } else {
                            String::from(value)
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

fn converter_candidate_ends(path: &str, offset: usize, converter: &PathConverter) -> Vec<usize> {
    let Some(suffix) = path.get(offset..) else {
        return Vec::new();
    };
    let mut ends = Vec::new();

    match converter {
        PathConverter::String => {
            for (relative, character) in suffix.char_indices() {
                if character == '/' {
                    break;
                }
                ends.push(offset + relative + character.len_utf8());
            }
        }
        PathConverter::Integer => {
            for (relative, byte) in suffix.bytes().enumerate() {
                if !byte.is_ascii_digit() {
                    break;
                }
                ends.push(offset + relative + 1);
            }
        }
        PathConverter::Float => {
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
        PathConverter::Uuid => {
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
        PathConverter::Path => {
            for (relative, character) in suffix.char_indices() {
                if character == '\n' {
                    break;
                }
                ends.push(offset + relative + character.len_utf8());
            }
            ends.push(offset);
        }
    }

    if matches!(
        converter,
        PathConverter::String | PathConverter::Integer | PathConverter::Path
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

fn parse_path(path: &str) -> Result<Option<Vec<PathSegment>>, RouteError> {
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

        let converter = match converter_name {
            "str" => PathConverter::String,
            "int" => PathConverter::Integer,
            "float" => PathConverter::Float,
            "uuid" => PathConverter::Uuid,
            "path" => PathConverter::Path,
            other => return Err(RouteError::UnknownPathConverter(String::from(other))),
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
