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
    format_routes: RouteTable,
}

/// A path returned by the direct-name branch of Host reverse lookup.
///
/// The path is preserved verbatim, `protocol` is empty, and `host` is
/// formatted from the configured Host pattern, including any configured port.
/// This result does not resolve a nested child route or assemble an absolute
/// URL.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostUrlPath {
    /// The supplied path, unchanged.
    pub path: String,
    /// The URL protocol; empty for a Host route's direct-name branch.
    pub protocol: String,
    /// The formatted Host pattern, including a configured port suffix.
    pub host: String,
}

impl HostUrlPath {
    /// Returns the path without normalization or percent-encoding.
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }

    /// Returns the protocol metadata, which is empty for this direct branch.
    #[must_use]
    pub fn protocol(&self) -> &str {
        &self.protocol
    }

    /// Returns the formatted host, retaining any configured port suffix.
    #[must_use]
    pub fn host(&self) -> &str {
        &self.host
    }
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
        let mut format_routes = RouteTable::new();
        format_routes
            .add_route(format!("/{pattern}"), ["GET"])
            .map_err(HostPatternError::RouteRegistration)?;
        Ok(Self {
            routes,
            format_routes,
        })
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

    /// Formats this Host pattern with converter-formatted parameter values.
    ///
    /// The complete parameter set is required, as with
    /// [`RouteTable::build_path`]. Formatting follows the built-in converter
    /// rules, and the output preserves any configured port suffix. Values are
    /// not percent-escaped.
    ///
    /// # Errors
    ///
    /// Returns [`HostPatternError::HostFormatting`] when parameter names are
    /// missing, extra, or duplicated, or when a value violates its built-in
    /// converter's formatting contract.
    pub fn format_host(
        &self,
        path_params: &[(String, String)],
    ) -> Result<String, HostPatternError> {
        let path = self
            .format_routes
            .build_path(0, path_params)
            .map_err(HostPatternError::HostFormatting)?;
        Ok(path
            .strip_prefix('/')
            .map_or(path.as_str(), |host| host)
            .to_owned())
    }

    /// Builds the direct-name Host reverse-lookup result from a supplied path
    /// and Host parameters.
    ///
    /// The path is copied verbatim, `protocol` is empty, and `host` is
    /// produced by [`Self::format_host`], including any configured port
    /// suffix. This represents only the Host route's own-name/direct-path
    /// branch; it does not resolve a nested child route, normalize the path,
    /// percent-encode values, or assemble an absolute URL.
    ///
    /// # Errors
    ///
    /// Returns [`HostPatternError::HostFormatting`] when the supplied host
    /// parameters are missing, extra, duplicated, or invalid for their
    /// built-in converter.
    pub fn format_url_path(
        &self,
        path: impl Into<String>,
        host_params: &[(String, String)],
    ) -> Result<HostUrlPath, HostPatternError> {
        Ok(HostUrlPath {
            path: path.into(),
            protocol: String::new(),
            host: self.format_host(host_params)?,
        })
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
    /// Host formatting failed because the parameter set or values were invalid.
    HostFormatting(RouteError),
}

impl Display for HostPatternError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::StartsWithSlash => formatter.write_str("Host patterns must not start with '/'"),
            Self::RouteRegistration(error) => {
                write!(formatter, "Host pattern registration failed: {error}")
            }
            Self::HostFormatting(error) => write!(formatter, "Host formatting failed: {error}"),
        }
    }
}

impl Error for HostPatternError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::RouteRegistration(error) | Self::HostFormatting(error) => Some(error),
            Self::StartsWithSlash => None,
        }
    }
}
