//! Helpers for constructing the URL represented by an ASGI connection scope.

use std::fmt;
use std::str::{self, Utf8Error};

/// An error raised while constructing a URL from an ASGI connection scope.
#[derive(Debug)]
pub enum ConnectionUrlError {
    /// The scope's query string contains bytes that are not valid UTF-8.
    InvalidQueryUtf8(Utf8Error),
    /// The scope has a server address, but its scheme has no defined default port.
    UnsupportedScheme(String),
}

impl fmt::Display for ConnectionUrlError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidQueryUtf8(error) => {
                write!(formatter, "query string is not valid UTF-8: {error}")
            }
            Self::UnsupportedScheme(scheme) => {
                write!(
                    formatter,
                    "unsupported URL scheme for ASGI server address: {scheme}"
                )
            }
        }
    }
}

impl std::error::Error for ConnectionUrlError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::InvalidQueryUtf8(error) => Some(error),
            Self::UnsupportedScheme(_) => None,
        }
    }
}

/// Builds the absolute URL represented by an HTTP or WebSocket ASGI scope.
///
/// A missing scheme defaults to `http`. The first header whose name is exactly
/// `b"host"` is used when its value matches Starlette's accepted host-header
/// shape. Otherwise, the server address supplies the authority, with the
/// default port omitted for `http`/`ws` (80) and `https`/`wss` (443). If the
/// scope has no usable authority, the result contains only its path and
/// optional UTF-8 query string.
///
/// The header list uses raw ASGI byte pairs. The server host is paired with
/// its port, as in the ASGI `server` scope item.
///
/// # Errors
///
/// Returns [`ConnectionUrlError::InvalidQueryUtf8`] when the query bytes are
/// not valid UTF-8. Returns [`ConnectionUrlError::UnsupportedScheme`] when a
/// server address must be used and the scheme is not `http`, `https`, `ws`, or
/// `wss`.
pub fn connection_url(
    scheme: Option<&str>,
    path: &str,
    query_string: &[u8],
    headers: &[(Vec<u8>, Vec<u8>)],
    server: Option<(&str, u16)>,
) -> Result<String, ConnectionUrlError> {
    let scheme = scheme.unwrap_or("http");
    let host_header = headers
        .iter()
        .find(|(name, _)| name.as_slice() == b"host")
        .map(|(_, value)| value.as_slice());

    let netloc = match host_header {
        Some(value) if is_valid_host_header(value) => {
            // The accepted shape is ASCII-only, so this conversion must succeed.
            str::from_utf8(value).ok().map(str::to_owned)
        }
        _ => None,
    };

    let netloc = match (netloc, server) {
        (Some(netloc), _) => Some(netloc),
        (None, Some((host, port))) => {
            let default_port = match scheme {
                "http" | "ws" => 80,
                "https" | "wss" => 443,
                _ => return Err(ConnectionUrlError::UnsupportedScheme(scheme.to_owned())),
            };
            Some(if port == default_port {
                host.to_owned()
            } else {
                format!("{host}:{port}")
            })
        }
        (None, None) => None,
    };

    let query = str::from_utf8(query_string).map_err(ConnectionUrlError::InvalidQueryUtf8)?;
    let Some(netloc) = netloc else {
        return Ok(if query.is_empty() {
            path.to_owned()
        } else {
            format!("{path}?{query}")
        });
    };

    let mut url = String::new();
    if !scheme.is_empty() {
        url.push_str(scheme);
        url.push(':');
    }
    url.push_str("//");
    url.push_str(&netloc);
    if !path.is_empty() && !path.starts_with('/') {
        url.push('/');
    }
    url.push_str(path);
    if !query.is_empty() {
        url.push('?');
        url.push_str(query);
    }
    Ok(url)
}

fn is_valid_host_header(value: &[u8]) -> bool {
    if value.first() == Some(&b'[') {
        let Some(closing_bracket) = value.iter().position(|byte| *byte == b']') else {
            return false;
        };
        let host = &value[..=closing_bracket];
        let suffix = &value[closing_bracket + 1..];
        let valid_port =
            suffix.is_empty() || (suffix.first() == Some(&b':') && is_ascii_digits(&suffix[1..]));
        return valid_port && is_bracketed_ipv6_shape(host);
    }

    let (host, port) = match value.iter().position(|byte| *byte == b':') {
        Some(colon) => (&value[..colon], Some(&value[colon + 1..])),
        None => (value, None),
    };
    !host.is_empty()
        && host
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-'))
        && port.is_none_or(is_ascii_digits)
}

fn is_bracketed_ipv6_shape(value: &[u8]) -> bool {
    if value.len() < 4 || value.last() != Some(&b']') {
        return false;
    }
    let inside = &value[1..value.len() - 1];
    let Some(colon) = inside.iter().position(|byte| *byte == b':') else {
        return false;
    };
    let left = &inside[..colon];
    let right = &inside[colon + 1..];
    right
        .iter()
        .all(|byte| byte.is_ascii_hexdigit() || matches!(byte, b'.' | b':'))
        && !right.is_empty()
        && left.iter().all(u8::is_ascii_hexdigit)
}

fn is_ascii_digits(value: &[u8]) -> bool {
    !value.is_empty() && value.iter().all(u8::is_ascii_digit)
}
