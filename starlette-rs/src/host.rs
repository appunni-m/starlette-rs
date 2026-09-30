//! Rust-native matching for Starlette Host patterns.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use crate::{DetailedRouteMatch, RouteError, RouteTable};

/// A single Starlette-style Host pattern matched against a Host header value.
///
/// The pattern uses the same built-in parameter syntax as [`RouteTable`]. Any
/// configured port and the incoming Host header port are ignored before
/// matching, as Starlette does when preparing a Host route's hostname.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostPattern {
    routes: RouteTable,
}

impl HostPattern {
    /// Creates a Host matcher from a host pattern such as
    /// `"{tenant}.example.test"`.
    ///
    /// # Errors
    ///
    /// Returns [`HostPatternError::StartsWithSlash`] when the pattern starts
    /// with `/`, or [`HostPatternError::RouteRegistration`] when its
    /// parameter syntax is invalid.
    pub fn new(pattern: impl Into<String>) -> Result<Self, HostPatternError> {
        let pattern = pattern.into();
        if pattern.starts_with('/') {
            return Err(HostPatternError::StartsWithSlash);
        }

        let hostname = host_pattern_without_port(&pattern);
        let mut routes = RouteTable::new();
        routes
            .add_route(format!("/{hostname}"), ["GET"])
            .map_err(HostPatternError::RouteRegistration)?;
        Ok(Self { routes })
    }

    /// Matches a Host header value and returns named captures in pattern
    /// order. Capture values are strings, following [`RouteTable`]'s native
    /// representation.
    ///
    /// Configured and incoming port suffixes are discarded before matching.
    /// For example, the pattern `"{tenant}.example.test:3600"` matches
    /// `"acme.example.test:5600"` and returns `[("tenant", "acme")]`.
    #[must_use]
    pub fn match_host(&self, host_header: &str) -> Option<Vec<(String, String)>> {
        let hostname = host_header
            .split_once(':')
            .map_or(host_header, |(hostname, _port)| hostname);
        match self.routes.matches_detailed(&format!("/{hostname}"), "GET") {
            DetailedRouteMatch::Matched { path_params, .. } => Some(path_params),
            DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => None,
        }
    }
}

fn host_pattern_without_port(pattern: &str) -> &str {
    let suffix_start = last_parameter_end(pattern).unwrap_or(0);
    let suffix = &pattern[suffix_start..];
    let suffix_end = suffix
        .find(':')
        .map_or(pattern.len(), |index| suffix_start + index);
    &pattern[..suffix_end]
}

fn last_parameter_end(pattern: &str) -> Option<usize> {
    let bytes = pattern.as_bytes();
    let mut cursor = 0;
    let mut last_parameter_end = None;

    while cursor < bytes.len() {
        if bytes[cursor] == b'{' {
            if let Some(end) = parameter_end(bytes, cursor) {
                last_parameter_end = Some(end);
                cursor = end;
                continue;
            }
        }
        cursor += 1;
    }

    last_parameter_end
}

fn parameter_end(bytes: &[u8], start: usize) -> Option<usize> {
    let name_end = identifier_end(bytes, start.checked_add(1)?)?;
    let parameter_end = if bytes.get(name_end) == Some(&b':') {
        identifier_end(bytes, name_end.checked_add(1)?)?
    } else {
        name_end
    };
    (bytes.get(parameter_end) == Some(&b'}')).then_some(parameter_end + 1)
}

fn identifier_end(bytes: &[u8], start: usize) -> Option<usize> {
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

/// An invalid Host pattern registration.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum HostPatternError {
    /// Starlette Host patterns must not start with `/`.
    StartsWithSlash,
    /// The pattern contains invalid or unsupported route parameter syntax.
    RouteRegistration(RouteError),
}

impl Display for HostPatternError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::StartsWithSlash => formatter.write_str("Host patterns must not start with '/'"),
            Self::RouteRegistration(error) => {
                write!(formatter, "Host pattern registration failed: {error}")
            }
        }
    }
}

impl Error for HostPatternError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) => Some(error),
            Self::StartsWithSlash => None,
        }
    }
}
