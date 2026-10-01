//! Rust-owned primitives for Starlette request data.
//!
//! These types cover the raw headers, query strings, cookies, and incremental
//! HTTP body state used by the compatibility layer. ASGI receive calls remain
//! on Python's event loop; the host passes each received message to
//! [`RequestBodyAccumulator`] for interpretation.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

/// Ordered raw HTTP headers retaining duplicate fields and original bytes.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RequestHeaders {
    raw: Vec<(Vec<u8>, Vec<u8>)>,
}

impl RequestHeaders {
    /// Creates a header collection from ordered raw name/value pairs.
    #[must_use]
    pub fn new(headers: impl IntoIterator<Item = (Vec<u8>, Vec<u8>)>) -> Self {
        Self {
            raw: headers.into_iter().collect(),
        }
    }

    /// Returns the original ordered raw header pairs.
    #[must_use]
    pub fn raw(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.raw
    }

    /// Returns the first value for a name, comparing ASCII letters without
    /// regard to case.
    #[must_use]
    pub fn get(&self, name: &[u8]) -> Option<&[u8]> {
        self.raw
            .iter()
            .find(|(header_name, _)| header_name.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.as_slice())
    }

    /// Returns every value for a name in original wire order.
    #[must_use]
    pub fn get_list(&self, name: &[u8]) -> Vec<&[u8]> {
        self.raw
            .iter()
            .filter(|(header_name, _)| header_name.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.as_slice())
            .collect()
    }

    /// Returns the number of raw fields, including duplicate names.
    #[must_use]
    pub fn len(&self) -> usize {
        self.raw.len()
    }

    /// Returns whether the collection has no raw fields.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.raw.is_empty()
    }
}

/// Ordered query parameters parsed from an ASGI raw query string.
///
/// Repeated keys remain in [`multi_items`](Self::multi_items) and
/// [`get_list`](Self::get_list); scalar lookup returns the last value, as
/// Starlette's `QueryParams` does.
#[derive(Clone, Debug, Default)]
pub struct QueryParams {
    items: Vec<(String, String)>,
}

impl QueryParams {
    /// Parses an ASGI query-string byte sequence using Starlette's
    /// `parse_qsl(..., keep_blank_values=True)` behavior.
    #[must_use]
    pub fn parse(raw_query: &[u8]) -> Self {
        Self::parse_fields(raw_query, true)
    }

    /// Parses a Unicode query string using Starlette's `parse_qsl` behavior.
    #[must_use]
    pub fn parse_str(query: &str) -> Self {
        Self::parse_fields(query.as_bytes(), false)
    }

    /// Creates query parameters from ordered key/value pairs.
    #[must_use]
    pub fn from_pairs(items: impl IntoIterator<Item = (String, String)>) -> Self {
        Self {
            items: items.into_iter().collect(),
        }
    }

    fn parse_fields(raw_query: &[u8], decode_raw_as_latin1: bool) -> Self {
        let mut items = Vec::new();
        for field in raw_query.split(|byte| *byte == b'&') {
            // `parse_qsl` ignores empty fields but retains a non-empty key with
            // an empty value (including fields without an equals sign).
            if field.is_empty() {
                continue;
            }

            let equals = field.iter().position(|byte| *byte == b'=');
            let (key, value) = match equals {
                Some(index) => (&field[..index], &field[index + 1..]),
                None => (field, &[][..]),
            };
            items.push((
                decode_query_component(key, decode_raw_as_latin1),
                decode_query_component(value, decode_raw_as_latin1),
            ));
        }
        Self { items }
    }

    /// Returns the last value for `key`, or `None` when the key is absent.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&str> {
        self.items
            .iter()
            .rev()
            .find(|(item_key, _)| item_key == key)
            .map(|(_, value)| value.as_str())
    }

    /// Returns all values for `key` in query-string order.
    #[must_use]
    pub fn get_list(&self, key: &str) -> Vec<&str> {
        self.items
            .iter()
            .filter(|(item_key, _)| item_key == key)
            .map(|(_, value)| value.as_str())
            .collect()
    }

    /// Returns every parsed key/value pair, retaining repeated keys and order.
    #[must_use]
    pub fn multi_items(&self) -> &[(String, String)] {
        &self.items
    }

    /// Returns distinct keys in their first-occurrence order.
    #[must_use]
    pub fn keys(&self) -> Vec<&str> {
        self.items
            .iter()
            .enumerate()
            .filter(|(index, (key, _))| {
                !self.items[..*index]
                    .iter()
                    .any(|(prior_key, _)| prior_key == key)
            })
            .map(|(_, (key, _))| key.as_str())
            .collect()
    }

    /// Returns the last value for each key in first-occurrence key order.
    #[must_use]
    pub fn values(&self) -> Vec<&str> {
        self.keys()
            .into_iter()
            .filter_map(|key| self.get(key))
            .collect()
    }

    /// Returns one last-value pair per key in first-occurrence key order.
    #[must_use]
    pub fn items(&self) -> Vec<(&str, &str)> {
        self.keys()
            .into_iter()
            .filter_map(|key| self.get(key).map(|value| (key, value)))
            .collect()
    }

    /// Serializes every pair using `urllib.parse.urlencode` form encoding.
    #[must_use]
    pub fn query_string(&self) -> String {
        self.items
            .iter()
            .map(|(key, value)| {
                format!(
                    "{}={}",
                    encode_query_component(key),
                    encode_query_component(value)
                )
            })
            .collect::<Vec<_>>()
            .join("&")
    }

    /// Returns the number of distinct keys.
    #[must_use]
    pub fn len(&self) -> usize {
        self.items
            .iter()
            .enumerate()
            .filter(|(index, (key, _))| {
                !self.items[..*index]
                    .iter()
                    .any(|(prior_key, _)| prior_key == key)
            })
            .count()
    }

    /// Returns whether there are no parsed parameters.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }
}

impl PartialEq for QueryParams {
    fn eq(&self, other: &Self) -> bool {
        let mut left = self.items.clone();
        let mut right = other.items.clone();
        left.sort_unstable();
        right.sort_unstable();
        left == right
    }
}

impl Eq for QueryParams {}

fn decode_query_component(component: &[u8], decode_raw_as_latin1: bool) -> String {
    // Starlette first decodes the raw query as Latin-1, then urllib's
    // unquote_plus encodes those Unicode characters as UTF-8 before replacing
    // percent escapes and decoding the result as UTF-8 with replacement.
    let mut encoded = Vec::with_capacity(component.len());
    let mut index = 0;
    while index < component.len() {
        match component[index] {
            b'+' => {
                encoded.push(b' ');
                index += 1;
            }
            b'%' if index + 2 < component.len() => {
                if let (Some(high), Some(low)) = (
                    hex_value(component[index + 1]),
                    hex_value(component[index + 2]),
                ) {
                    encoded.push((high << 4) | low);
                    index += 3;
                } else {
                    encoded.push(b'%');
                    index += 1;
                }
            }
            b'%' => {
                encoded.push(b'%');
                index += 1;
            }
            byte => {
                if decode_raw_as_latin1 && !byte.is_ascii() {
                    let mut utf8 = [0; 2];
                    let character = char::from(byte);
                    encoded.extend_from_slice(character.encode_utf8(&mut utf8).as_bytes());
                } else {
                    encoded.push(byte);
                }
                index += 1;
            }
        }
    }
    String::from_utf8_lossy(&encoded).into_owned()
}

fn encode_query_component(component: &str) -> String {
    let mut encoded = String::with_capacity(component.len());
    for byte in component.as_bytes() {
        if byte.is_ascii_alphanumeric() || b"_.-~".contains(byte) {
            encoded.push(char::from(*byte));
        } else if *byte == b' ' {
            encoded.push('+');
        } else {
            use fmt::Write as _;
            let _ = write!(encoded, "%{byte:02X}");
        }
    }
    encoded
}

fn hex_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

/// Parsed cookie name/value pairs, with duplicate names resolved to the last
/// value while retaining the first insertion position.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Cookies {
    items: Vec<(String, String)>,
}

impl Cookies {
    /// Parses one Cookie header string using Starlette's lenient parser.
    #[must_use]
    pub fn from_header(header: &str) -> Self {
        let mut cookies = Self::default();
        cookies.extend_header(header);
        cookies
    }

    /// Parses one raw Cookie header, decoding its bytes as Latin-1 as
    /// `starlette.datastructures.Headers` does.
    #[must_use]
    pub fn from_header_bytes(header: &[u8]) -> Self {
        Self::from_header(&decode_latin1(header))
    }

    /// Parses all Cookie fields from [`RequestHeaders`], merging them in wire
    /// order so later values override earlier values of the same name.
    #[must_use]
    pub fn from_headers(headers: &RequestHeaders) -> Self {
        let mut cookies = Self::default();
        for header in headers.get_list(b"cookie") {
            cookies.extend_header(&decode_latin1(header));
        }
        cookies
    }

    /// Returns the cookie value for `key`.
    #[must_use]
    pub fn get(&self, key: &str) -> Option<&str> {
        self.items
            .iter()
            .find(|(item_key, _)| item_key == key)
            .map(|(_, value)| value.as_str())
    }

    /// Returns the unique cookie pairs in first-insertion order.
    #[must_use]
    pub fn items(&self) -> &[(String, String)] {
        &self.items
    }

    /// Returns the number of unique cookie names.
    #[must_use]
    pub fn len(&self) -> usize {
        self.items.len()
    }

    /// Returns whether there are no cookies.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    fn extend_header(&mut self, header: &str) {
        for chunk in header.split(';') {
            let (key, value) = match chunk.split_once('=') {
                Some((key, value)) => (key, value),
                None => ("", chunk),
            };
            let key = trim_python_whitespace(key);
            let value = trim_python_whitespace(value);
            if key.is_empty() && value.is_empty() {
                continue;
            }
            let value = unquote_cookie_value(value);
            if let Some((_, existing)) = self.items.iter_mut().find(|(name, _)| name == key) {
                *existing = value;
            } else {
                self.items.push((key.to_owned(), value));
            }
        }
    }
}

/// Parses a Cookie header using the lenient behavior used by Starlette 1.6.0.
#[must_use]
pub fn parse_cookie_header(header: &str) -> Cookies {
    Cookies::from_header(header)
}

fn decode_latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

fn trim_python_whitespace(value: &str) -> &str {
    fn is_python_whitespace(character: char) -> bool {
        character.is_whitespace() || matches!(character, '\u{001c}'..='\u{001f}')
    }

    value.trim_matches(is_python_whitespace)
}

fn unquote_cookie_value(value: &str) -> String {
    let Some(inner) = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
    else {
        return value.to_owned();
    };

    let mut result = String::with_capacity(inner.len());
    let mut characters = inner.chars().peekable();
    while let Some(character) = characters.next() {
        if character != '\\' {
            result.push(character);
            continue;
        }

        let mut lookahead = characters.clone();
        let octal = (lookahead.next(), lookahead.next(), lookahead.next());
        if let (Some(first @ '0'..='3'), Some(second @ '0'..='7'), Some(third @ '0'..='7')) = octal
        {
            let value =
                (first as u32 - '0' as u32) * 64 + (second as u32 - '0' as u32) * 8 + third as u32
                    - '0' as u32;
            result.push(char::from_u32(value).unwrap_or('\u{fffd}'));
            characters.next();
            characters.next();
            characters.next();
        } else if let Some(escaped) = characters.next() {
            if escaped == '\n' {
                // Python's regex `.` does not match LF, preserving this slash.
                result.push('\\');
            }
            result.push(escaped);
        } else {
            // Python's regular expression does not match a final lone slash.
            result.push('\\');
        }
    }
    result
}

/// The effect of processing one ASGI message for a request body.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BodyProgress {
    /// A request-body chunk was accepted. `complete` is true for the final
    /// `http.request` event.
    RequestChunk {
        /// Number of bytes in the current message's body field.
        chunk_length: usize,
        /// Whether the message completed the request stream.
        complete: bool,
    },
    /// A message type outside the body protocol was ignored, as by Starlette's
    /// request stream loop.
    Ignored,
}

/// An error produced while consuming or caching an ASGI request body.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequestBodyError {
    /// The ASGI receive stream has already completed and has no cached body to
    /// replay.
    StreamConsumed,
    /// The receive side disconnected while the body was being read.
    ClientDisconnect,
    /// A complete request body is required before it can be cached.
    BodyNotComplete,
    /// Body collection was not started before the receive stream was read.
    BodyCollectionNotStarted,
    /// An `http.request` message arrived after the final request message.
    AlreadyComplete,
}

impl Display for RequestBodyError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::StreamConsumed => formatter.write_str("Stream consumed"),
            Self::ClientDisconnect => formatter.write_str("Client disconnected"),
            Self::BodyNotComplete => formatter.write_str("request body is not complete"),
            Self::BodyCollectionNotStarted => {
                formatter.write_str("request body collection was not started")
            }
            Self::AlreadyComplete => formatter.write_str("request body is already complete"),
        }
    }
}

impl Error for RequestBodyError {}

/// Accumulates ASGI request chunks and tracks completion, disconnection, and
/// whether a complete body has been cached for replay.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RequestBodyAccumulator {
    received: Vec<u8>,
    complete: bool,
    disconnected: bool,
    collecting_body: bool,
    cached_body: Option<Vec<u8>>,
}

impl RequestBodyAccumulator {
    /// Processes one ASGI message. The caller should pass an empty body when
    /// `http.request` omits its optional `body` field and `false` when
    /// `more_body` is omitted.
    pub fn accept_asgi_message(
        &mut self,
        message_type: &str,
        body: &[u8],
        more_body: bool,
    ) -> Result<BodyProgress, RequestBodyError> {
        match message_type {
            "http.request" => {
                if self.disconnected {
                    return Err(RequestBodyError::ClientDisconnect);
                }
                if self.complete {
                    return Err(RequestBodyError::AlreadyComplete);
                }
                if self.collecting_body {
                    self.received.extend_from_slice(body);
                }
                self.complete = !more_body;
                Ok(BodyProgress::RequestChunk {
                    chunk_length: body.len(),
                    complete: self.complete,
                })
            }
            "http.disconnect" => {
                self.disconnected = true;
                Err(RequestBodyError::ClientDisconnect)
            }
            _ => Ok(BodyProgress::Ignored),
        }
    }

    /// Applies a message returned by an already-pending ASGI receive call.
    ///
    /// Independent Starlette stream consumers can have receive calls in flight
    /// at the same time. Another consumer may observe the final message first;
    /// a receive call that was already pending still yields its own message,
    /// while the shared stream remains complete.
    pub fn accept_pending_message(
        &mut self,
        message_type: &str,
        body: &[u8],
        more_body: bool,
    ) -> Result<BodyProgress, RequestBodyError> {
        match message_type {
            "http.request" => {
                if self.disconnected {
                    return Err(RequestBodyError::ClientDisconnect);
                }
                self.complete |= !more_body;
                Ok(BodyProgress::RequestChunk {
                    chunk_length: body.len(),
                    complete: self.complete,
                })
            }
            "http.disconnect" => {
                self.disconnected = true;
                Err(RequestBodyError::ClientDisconnect)
            }
            _ => Ok(BodyProgress::Ignored),
        }
    }

    /// Returns whether the final `http.request` message has been received.
    #[must_use]
    pub const fn is_complete(&self) -> bool {
        self.complete
    }

    /// Returns whether an `http.disconnect` message has been observed.
    #[must_use]
    pub const fn is_disconnected(&self) -> bool {
        self.disconnected
    }

    /// Returns whether the ASGI request stream has been consumed to its final
    /// message. A cached body can still be replayed after this returns true.
    #[must_use]
    pub const fn is_consumed(&self) -> bool {
        self.complete
    }

    /// Begins collecting chunks for `Request.body()`. Call this before the
    /// receive loop; a stream already consumed without a cache cannot later be
    /// converted into a cached body.
    pub fn begin_body_collection(&mut self) -> Result<(), RequestBodyError> {
        if self.cached_body.is_some() {
            return Ok(());
        }
        if self.disconnected {
            return Err(RequestBodyError::ClientDisconnect);
        }
        if self.complete {
            return Err(RequestBodyError::StreamConsumed);
        }
        self.collecting_body = true;
        Ok(())
    }

    /// Returns whether the next stream read should fail because the receive
    /// stream was consumed without a cached body.
    #[must_use]
    pub const fn stream_is_consumed(&self) -> bool {
        self.complete && self.cached_body.is_none()
    }

    /// Stores the completed request body for repeat access, returning the
    /// cached bytes.
    pub fn cache_body(&mut self) -> Result<&[u8], RequestBodyError> {
        if self.cached_body.is_none() {
            if self.disconnected {
                return Err(RequestBodyError::ClientDisconnect);
            }
            if !self.collecting_body {
                return Err(RequestBodyError::BodyCollectionNotStarted);
            }
            if !self.complete {
                return Err(RequestBodyError::BodyNotComplete);
            }
            self.cached_body = Some(std::mem::take(&mut self.received));
        }
        self.cached_body
            .as_deref()
            .ok_or(RequestBodyError::BodyNotComplete)
    }

    /// Stores bytes collected by one body consumer after its receive loop
    /// finishes. The caller owns the local chunks because concurrent stream
    /// consumers may have received other messages from the same callback.
    pub fn cache_body_from(&mut self, body: &[u8]) -> Result<&[u8], RequestBodyError> {
        if self.disconnected {
            return Err(RequestBodyError::ClientDisconnect);
        }
        if !self.collecting_body && self.cached_body.is_none() {
            return Err(RequestBodyError::BodyCollectionNotStarted);
        }
        if !self.complete {
            return Err(RequestBodyError::BodyNotComplete);
        }
        self.cached_body = Some(body.to_vec());
        self.received.clear();
        self.collecting_body = false;
        self.cached_body
            .as_deref()
            .ok_or(RequestBodyError::BodyNotComplete)
    }

    /// Discards bytes from an interrupted `body()` collection.
    ///
    /// Starlette accumulates `body()` chunks in a local list and installs the
    /// cache only after the stream finishes. If receive fails, those partial
    /// bytes are not retained for a later call.
    pub fn abort_body_collection(&mut self) {
        if self.cached_body.is_none() {
            self.received.clear();
            self.collecting_body = false;
        }
    }

    /// Returns the cached body, if the caller has completed body collection.
    #[must_use]
    pub fn cached_body(&self) -> Option<&[u8]> {
        self.cached_body.as_deref()
    }

    /// Checks whether a fresh stream can begin under Starlette's stream rules.
    /// A body cache permits replay after the original receive stream ends.
    pub fn check_stream_start(&self) -> Result<(), RequestBodyError> {
        if self.cached_body.is_some() {
            Ok(())
        } else if self.disconnected {
            Err(RequestBodyError::ClientDisconnect)
        } else if self.complete {
            Err(RequestBodyError::StreamConsumed)
        } else {
            Ok(())
        }
    }
}

/// The effect of advancing one public `Request.stream()` iterator.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RequestStreamProgress {
    /// The iterator needs another ASGI message from the receive callback.
    Receive,
    /// Yield these bytes to the Python async iterator consumer.
    Chunk(Vec<u8>),
    /// Yield the request's cached body object to preserve its Python identity.
    CachedBody(Vec<u8>),
    /// The stream emitted its final empty chunk and is exhausted.
    Complete,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum RequestStreamPhase {
    #[default]
    New,
    Receiving,
    CachedTail,
    FinalTail,
    Complete,
}

/// Per-iterator protocol state for `Request.stream()`.
///
/// The request body accumulator is shared across streams and body collection;
/// this value tracks only which chunks this particular iterator still needs to
/// yield.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RequestStreamState {
    phase: RequestStreamPhase,
}

impl RequestStreamState {
    /// Starts or resumes an iterator, yielding cached bytes or requesting input.
    pub fn next(
        &mut self,
        body: &RequestBodyAccumulator,
    ) -> Result<RequestStreamProgress, RequestBodyError> {
        match self.phase {
            RequestStreamPhase::New => {
                if let Some(cached) = body.cached_body() {
                    self.phase = RequestStreamPhase::CachedTail;
                    return Ok(RequestStreamProgress::CachedBody(cached.to_vec()));
                }
                body.check_stream_start()?;
                self.phase = RequestStreamPhase::Receiving;
                Ok(RequestStreamProgress::Receive)
            }
            RequestStreamPhase::Receiving => Ok(RequestStreamProgress::Receive),
            RequestStreamPhase::CachedTail | RequestStreamPhase::FinalTail => {
                self.phase = RequestStreamPhase::Complete;
                Ok(RequestStreamProgress::Chunk(Vec::new()))
            }
            RequestStreamPhase::Complete => Ok(RequestStreamProgress::Complete),
        }
    }

    /// Applies one received ASGI message and decides whether to read again or yield.
    pub fn accept(
        &mut self,
        body: &mut RequestBodyAccumulator,
        message_type: &str,
        chunk: &[u8],
        more_body: bool,
    ) -> Result<RequestStreamProgress, RequestBodyError> {
        if self.phase != RequestStreamPhase::Receiving {
            return Err(RequestBodyError::StreamConsumed);
        }

        let progress = match body.accept_asgi_message(message_type, chunk, more_body) {
            Ok(progress) => progress,
            Err(error) => {
                self.phase = RequestStreamPhase::Complete;
                return Err(error);
            }
        };

        match progress {
            BodyProgress::Ignored => Ok(RequestStreamProgress::Receive),
            BodyProgress::RequestChunk { complete, .. } if chunk.is_empty() => {
                if complete {
                    self.phase = RequestStreamPhase::Complete;
                    Ok(RequestStreamProgress::Chunk(Vec::new()))
                } else {
                    Ok(RequestStreamProgress::Receive)
                }
            }
            BodyProgress::RequestChunk { complete, .. } => {
                if complete {
                    self.phase = RequestStreamPhase::FinalTail;
                }
                Ok(RequestStreamProgress::Chunk(chunk.to_vec()))
            }
        }
    }

    /// Applies a message returned by this iterator's already-pending receive.
    ///
    /// Unlike [`Self::accept`], this preserves pending receives across another
    /// iterator completing the shared request stream first.
    pub fn accept_pending(
        &mut self,
        body: &mut RequestBodyAccumulator,
        message_type: &str,
        chunk: &[u8],
        more_body: bool,
    ) -> Result<RequestStreamProgress, RequestBodyError> {
        if self.phase != RequestStreamPhase::Receiving {
            return Err(RequestBodyError::StreamConsumed);
        }

        let progress = match body.accept_pending_message(message_type, chunk, more_body) {
            Ok(progress) => progress,
            Err(error) => {
                self.phase = RequestStreamPhase::Complete;
                return Err(error);
            }
        };

        match progress {
            BodyProgress::Ignored if body.is_complete() => {
                self.phase = RequestStreamPhase::Complete;
                Ok(RequestStreamProgress::Chunk(Vec::new()))
            }
            BodyProgress::Ignored => Ok(RequestStreamProgress::Receive),
            BodyProgress::RequestChunk { complete, .. } if chunk.is_empty() => {
                if complete {
                    self.phase = RequestStreamPhase::Complete;
                    Ok(RequestStreamProgress::Chunk(Vec::new()))
                } else {
                    Ok(RequestStreamProgress::Receive)
                }
            }
            BodyProgress::RequestChunk { complete, .. } => {
                if complete {
                    self.phase = RequestStreamPhase::FinalTail;
                }
                Ok(RequestStreamProgress::Chunk(chunk.to_vec()))
            }
        }
    }

    /// Closes the iterator after the awaited receive callback raises.
    pub fn fail(&mut self) {
        self.phase = RequestStreamPhase::Complete;
    }
}
