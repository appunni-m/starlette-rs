use std::error::Error;
use std::fmt::{self, Display, Formatter};

/// An HTTP response for the initial text-response slice.
///
/// Headers are stored as ordered byte pairs so repeated fields, including
/// repeated `set-cookie` fields, remain distinct and retain their order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Response {
    status_code: u16,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    body: Vec<u8>,
}

/// Optional attributes for a `Set-Cookie` response header.
///
/// Attribute values are strings so the Python boundary can preserve
/// `http.cookies.Morsel`'s value conversion before Rust serializes the header.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CookieOptions {
    /// `Max-Age` attribute value.
    pub max_age: Option<String>,
    /// `expires` attribute value, formatted as an HTTP date when appropriate.
    pub expires: Option<String>,
    /// `Path` attribute value. `None` omits the attribute.
    pub path: Option<String>,
    /// `Domain` attribute value.
    pub domain: Option<String>,
    /// Whether to emit the `Secure` flag.
    pub secure: bool,
    /// Whether to emit the `HttpOnly` flag.
    pub httponly: bool,
    /// `SameSite` attribute value. `None` omits the attribute.
    pub samesite: Option<String>,
    /// Whether to emit the `Partitioned` flag.
    pub partitioned: bool,
}

impl Default for CookieOptions {
    fn default() -> Self {
        Self {
            max_age: None,
            expires: None,
            path: Some(String::from("/")),
            domain: None,
            secure: false,
            httponly: false,
            samesite: Some(String::from("lax")),
            partitioned: false,
        }
    }
}

/// One Python traceback frame reduced to values needed by the debug renderer.
///
/// The Python boundary extracts filename, source context, and code metadata
/// while the exception and its live traceback are available. Rust owns the
/// Starlette HTML ordering, escaping, line formatting, and response framing.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DebugTracebackFrame {
    /// Source filename for the frame.
    pub filename: String,
    /// One-based line number at which the frame raised or propagated.
    pub line: usize,
    /// Python function name for the frame.
    pub function: String,
    /// Source lines returned by Python's `inspect.getinnerframes(..., 7)`.
    pub source_lines: Vec<String>,
    /// Zero-based index of the active line within `source_lines`.
    pub center_index: usize,
}

/// A response event in the order Starlette sends it to an ASGI `send` callable.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResponseEvent {
    /// The `http.response.start` message.
    Start {
        /// HTTP status code.
        status_code: u16,
        /// Ordered response header name/value byte pairs.
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    },
    /// The final `http.response.body` message.
    Body {
        /// Response body bytes.
        body: Vec<u8>,
    },
}

/// The next operation for a runtime driving a [`Response`] ASGI call.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResponseCallStep {
    /// Send one response event to the ASGI `send` callable.
    Send(ResponseEvent),
    /// Invoke and await the caller-owned background callback.
    RunBackground,
    /// The response and optional background callback completed successfully.
    Complete,
    /// An operation failed; no further response or background steps are due.
    Failed,
}

/// An operation result supplied to [`ResponseCall::advance`].
#[derive(Debug, PartialEq, Eq)]
pub enum ResponseCallInput<E> {
    /// Result of awaiting one ASGI `send` call.
    Send(Result<(), E>),
    /// Result of invoking and awaiting the background callback.
    BackgroundFinished(Result<(), E>),
}

/// A failed operation or invalid input to the response-call state machine.
#[derive(Debug, PartialEq, Eq)]
pub enum ResponseCallError<E> {
    /// The supplied send or background operation failed.
    Operation(E),
    /// The input does not match the operation requested by the current step.
    UnexpectedInput,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ResponseCallPhase {
    SendStart,
    SendBody,
    RunBackground,
    Complete,
    Failed,
}

/// Runtime-agnostic control flow for one response ASGI call.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResponseCall {
    events: [ResponseEvent; 2],
    has_background_callback: bool,
    phase: ResponseCallPhase,
}

/// An ASGI response event produced by [`StreamingResponse`].
///
/// This separate event type retains the `more_body` flag required by a
/// streaming response without changing the event contract for [`Response`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StreamingResponseEvent {
    /// The `http.response.start` message.
    Start {
        /// HTTP status code.
        status_code: u16,
        /// Ordered response header name/value byte pairs.
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    },
    /// An `http.response.body` message.
    Body {
        /// Response body bytes.
        body: Vec<u8>,
        /// Whether another body message follows.
        more_body: bool,
    },
}

/// A response that sends a pre-collected sequence of byte chunks.
///
/// This bounded native abstraction models the ASGI event contract for
/// Starlette's `StreamingResponse`; it does not adapt Python iterables or
/// async iterators. No `content-length` header is generated because the
/// response body is streamed. Caller-supplied headers and text media-type
/// charset handling follow [`Response::from_content`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StreamingResponse {
    status_code: u16,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    chunks: Vec<Vec<u8>>,
}

/// The next operation for a runtime driving a [`StreamingResponse`] ASGI call.
///
/// `PullChunk` requests exactly one chunk from the caller-owned stream. The
/// driver reports that pull, send, or background operation through
/// [`StreamingResponseCall::advance`]. Python objects and async runtimes stay
/// outside this state machine.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StreamingResponseCallStep {
    /// Send one response event to the ASGI `send` callable.
    Send(StreamingResponseEvent),
    /// Pull one chunk from the response's caller-owned iterator.
    PullChunk,
    /// Invoke and await the caller-owned background callback.
    RunBackground,
    /// The response and optional background callback completed successfully.
    Complete,
    /// An operation failed; no further response or background steps are due.
    Failed,
}

/// An operation result supplied to [`StreamingResponseCall::advance`].
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseCallInput<E> {
    /// Result of awaiting one ASGI `send` call.
    Send(Result<(), E>),
    /// Result of pulling exactly one stream item.
    ChunkPulled(Result<Option<Vec<u8>>, E>),
    /// Result of invoking and awaiting the background callback.
    BackgroundFinished(Result<(), E>),
}

/// A failed operation or invalid input to the streaming-call state machine.
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseCallError<E> {
    /// The supplied send, chunk-pull, or background operation failed.
    Operation(E),
    /// The input does not match the operation requested by the current step.
    UnexpectedInput,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum StreamingResponseCallPhase {
    SendStart,
    PullChunk,
    SendChunk(Vec<u8>),
    SendFinal,
    RunBackground,
    Complete,
    Failed,
}

/// A message received by the pre-ASGI-2.4 streaming disconnect listener.
///
/// The listener only needs to distinguish `http.disconnect` from every other
/// ASGI message. Converting the Python message type into this value is the
/// runtime adapter's responsibility.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectMessage {
    /// A message that does not terminate the listener, such as
    /// `http.request`.
    Other,
    /// The `http.disconnect` message that ends the listener.
    Disconnect,
}

/// The next operation for a runtime driving a
/// [`StreamingResponseDisconnectListener`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectListenerStep {
    /// Await one message from the ASGI `receive` callable.
    Receive,
    /// The listener observed `http.disconnect` and completed successfully.
    Complete,
    /// A receive operation failed; no further receive is due.
    Failed,
}

/// An operation result supplied to
/// [`StreamingResponseDisconnectListener::advance`].
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectListenerInput<E> {
    /// Result of awaiting one ASGI `receive` call after converting its type.
    Received(StreamingResponseDisconnectMessage),
    /// The receive callable or message conversion failed.
    ReceiveFailed(E),
}

/// A failed operation or invalid input to the disconnect listener.
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectListenerError<E> {
    /// The supplied receive operation failed.
    Operation(E),
    /// The input does not match the operation requested by the current step.
    UnexpectedInput,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum StreamingResponseDisconnectListenerPhase {
    Receive,
    Complete,
    Failed,
}

/// Runtime-agnostic control flow for the receive side of a streaming response
/// disconnect race.
///
/// The driver awaits exactly one `receive` operation for each `Receive` step.
/// Other messages keep the listener active; `http.disconnect` completes it.
/// This models Starlette's pre-ASGI-2.4 receive loop without assigning Python
/// message inspection or loop decisions to a runtime wrapper.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StreamingResponseDisconnectListener {
    phase: StreamingResponseDisconnectListenerPhase,
}

/// The next operation for a runtime driving a pre-ASGI-2.4 streaming response
/// race.
///
/// The caller starts the streaming sender and disconnect listener concurrently
/// after `StartConcurrent`. `AwaitFirstCompletion` waits until one branch
/// returns or fails. The cancel steps cancel the still-running peer and wait
/// for the task group to exit before reporting `ConcurrentFinished`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectCallStep {
    /// Start the stream sender and disconnect listener in one concurrent scope.
    StartConcurrent,
    /// Await whichever branch completes first.
    AwaitFirstCompletion,
    /// Cancel the stream sender and wait for the concurrent scope to exit.
    CancelStream,
    /// Cancel the disconnect listener and wait for the concurrent scope to exit.
    CancelListener,
    /// Cancel both branches after cancellation of the enclosing response call.
    CancelBoth,
    /// Invoke and await the caller-owned background callback.
    RunBackground,
    /// The response and optional background callback completed successfully.
    Complete,
    /// A task or callback failed; no further steps are due.
    Failed,
}

/// An operation result supplied to
/// [`StreamingResponseDisconnectCall::advance`].
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectCallInput<E> {
    /// Both concurrent branches were started.
    ConcurrentStarted,
    /// The stream sender returned or failed.
    StreamFinished(Result<(), E>),
    /// The disconnect listener observed `http.disconnect` or failed.
    ListenerFinished(Result<(), E>),
    /// The concurrent scope exited after the requested peer cancellation.
    ///
    /// AnyIO suppresses its own expected cancellation when a branch returns
    /// normally. Genuine child errors and task-group failures are returned as
    /// `Err` and take precedence over the initiating completion.
    ConcurrentFinished(Result<(), E>),
    /// The enclosing response call was cancelled and both children need cleanup.
    Cancelled(E),
    /// The caller-owned background callback completed or failed.
    BackgroundFinished(Result<(), E>),
}

/// A failed operation or invalid input to the disconnect-race state machine.
#[derive(Debug, PartialEq, Eq)]
pub enum StreamingResponseDisconnectCallError<E> {
    /// A child, task-group, cancellation-cleanup, or background operation failed.
    Operation(E),
    /// The input does not match the operation requested by the current step.
    UnexpectedInput,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum StreamingResponseDisconnectCallPhase {
    StartConcurrent,
    AwaitFirstCompletion,
    CancelStream,
    CancelListener,
    CancelBoth,
    RunBackground,
    Complete,
    Failed,
}

/// Runtime-agnostic control flow for Starlette's pre-ASGI-2.4 streaming race.
///
/// This coordinator chooses which child to cancel after the stream sender or
/// receive listener finishes. A normal stream completion or an observed
/// disconnect runs the optional background callback after the concurrent
/// scope has fully exited. A child or task-group error skips the background
/// callback and is returned unchanged. External cancellation requests cleanup
/// of both children and is propagated after the concurrent scope exits.
///
/// The stream branch should be driven by a [`StreamingResponseCall`] without a
/// background callback; the coordinator owns the post-race background step.
/// The receive branch should be driven by a
/// [`StreamingResponseDisconnectListener`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StreamingResponseDisconnectCall<E> {
    has_background_callback: bool,
    phase: StreamingResponseDisconnectCallPhase,
    child_error: Option<E>,
    cancellation: Option<E>,
}

/// Runtime-agnostic control flow for one streaming ASGI response call.
///
/// The caller performs the operation returned by [`Self::step`] and passes
/// its result to [`Self::advance`]. A supplied operation error is returned
/// immediately and moves the call to a terminal failed state. In particular,
/// a failed chunk pull or send skips the final send and the background step.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StreamingResponseCall {
    start_event: StreamingResponseEvent,
    has_background_callback: bool,
    phase: StreamingResponseCallPhase,
}

/// An error produced while constructing a cookie header.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ResponseError {
    /// A header name, value, or media type is not encodable as Latin-1.
    HeaderDataIsNotLatin1,
    /// Cookie names must contain only the characters accepted by
    /// `http.cookies.SimpleCookie`'s key format.
    InvalidCookieName,
    /// Cookie values cannot contain control characters.
    InvalidCookieValue,
    /// Cookie names and values must be encodable as Latin-1 response headers.
    CookieDataIsNotLatin1,
    /// SameSite must be one of `strict`, `lax`, or `none`.
    InvalidSameSite,
}

impl Display for ResponseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::HeaderDataIsNotLatin1 => {
                formatter.write_str("header data cannot be encoded as Latin-1")
            }
            Self::InvalidCookieName => formatter.write_str("invalid cookie name"),
            Self::InvalidCookieValue => {
                formatter.write_str("cookie value contains a disallowed character")
            }
            Self::CookieDataIsNotLatin1 => {
                formatter.write_str("cookie data cannot be encoded as Latin-1")
            }
            Self::InvalidSameSite => {
                formatter.write_str("samesite must be either 'strict', 'lax' or 'none'")
            }
        }
    }
}

impl Error for ResponseError {}

impl Response {
    /// Creates a UTF-8 plain-text response with status `200`.
    ///
    /// The automatically generated headers are ordered as `content-length`
    /// followed by `content-type`, matching Starlette's
    /// `PlainTextResponse` when no headers are supplied.
    #[must_use]
    pub fn plain_text(body: impl AsRef<str>) -> Self {
        Self::plain_text_with_status(200, body)
    }

    /// Creates a UTF-8 plain-text response with the supplied status code.
    ///
    /// `content-length` is omitted for status codes below 200 and for 204 or
    /// 304, while `content-type` is still emitted, matching Starlette's
    /// response header initialization behavior.
    #[must_use]
    pub fn plain_text_with_status(status_code: u16, body: impl AsRef<str>) -> Self {
        let body = body.as_ref().as_bytes().to_vec();
        let mut headers = Vec::with_capacity(2);
        if status_code >= 200 && status_code != 204 && status_code != 304 {
            headers.push((
                b"content-length".to_vec(),
                body.len().to_string().into_bytes(),
            ));
        }
        headers.push((
            b"content-type".to_vec(),
            b"text/plain; charset=utf-8".to_vec(),
        ));

        Self {
            status_code,
            headers,
            body,
        }
    }

    /// Creates Starlette's default HTTP server-error response.
    #[must_use]
    pub fn server_error() -> Self {
        Self::plain_text_with_status(500, "Internal Server Error")
    }

    /// Creates a plain-text debug response from Python's formatted traceback.
    #[must_use]
    pub fn debug_traceback_text(formatted_traceback: &str) -> Self {
        Self::plain_text_with_status(500, formatted_traceback)
    }

    /// Creates an HTML debug response from a Python traceback snapshot.
    ///
    /// `frames` are expected in traceback order (outermost to innermost).
    /// Starlette calls `inspect.getinnerframes(traceback, 7)`, where `7` is
    /// the number of source-context lines per frame, then renders every frame
    /// in reverse order. Python supplies its standard-library-formatted
    /// traceback heading; Rust performs HTML escaping and renders the frame
    /// template.
    #[must_use]
    pub fn debug_traceback_html(
        exception_type: &str,
        exception_message: &str,
        frames: &[DebugTracebackFrame],
    ) -> Self {
        let body = render_debug_traceback_html(exception_type, exception_message, frames);
        let body = body.into_bytes();
        let content_length = body.len().to_string().into_bytes();
        Self::from_parts(
            500,
            body,
            [
                (b"content-length".to_vec(), content_length),
                (
                    b"content-type".to_vec(),
                    b"text/html; charset=utf-8".to_vec(),
                ),
            ],
        )
    }

    /// Renders the body and headers for Starlette's default HTTP exception handler.
    ///
    /// For status codes 204 and 304, the response has an empty body and no
    /// automatically generated content headers. Other statuses render `detail`
    /// as a plain-text body and apply the supplied headers before generating
    /// any missing content headers.
    ///
    /// # Errors
    ///
    /// Returns [`ResponseError::HeaderDataIsNotLatin1`] if a header name or
    /// value cannot be encoded as Latin-1.
    pub fn http_exception(
        status_code: u16,
        detail: &str,
        headers: &[(String, String)],
    ) -> Result<Self, ResponseError> {
        let (body, media_type) = if matches!(status_code, 204 | 304) {
            (Vec::new(), None)
        } else {
            (detail.as_bytes().to_vec(), Some("text/plain"))
        };

        Self::from_content(
            status_code,
            body,
            media_type,
            headers
                .iter()
                .map(|(name, value)| (name.as_str(), value.as_str())),
        )
    }

    /// Creates Starlette's redirect response from a URL string.
    ///
    /// The URL is quoted using the same safe characters as
    /// `urllib.parse.quote(url, safe=":/%#?=@[]!$&'()*+,;")`. Caller headers
    /// are lowercased and retained in input order. The quoted `location`
    /// replaces any existing location header in place, while duplicate
    /// location headers are removed. `content-length: 0` is added according
    /// to the normal Starlette response rules before a new location header.
    ///
    /// # Errors
    ///
    /// Returns [`ResponseError::HeaderDataIsNotLatin1`] if a caller header
    /// cannot be encoded as Latin-1.
    pub fn redirect(
        url: &str,
        status_code: u16,
        headers: &[(String, String)],
    ) -> Result<Self, ResponseError> {
        let mut raw_headers = Vec::with_capacity(headers.len() + 2);
        for (name, value) in headers {
            let lower_name = name.to_lowercase();
            raw_headers.push((
                encode_latin1(&lower_name).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
                encode_latin1(value).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
            ));
        }

        if !raw_headers
            .iter()
            .any(|(name, _)| name.as_slice() == b"content-length")
            && status_code >= 200
            && status_code != 204
            && status_code != 304
        {
            raw_headers.push((b"content-length".to_vec(), b"0".to_vec()));
        }

        let quoted_url = quote_redirect_url(url).into_bytes();
        let mut has_location = false;
        let mut normalized_headers = Vec::with_capacity(raw_headers.len() + 1);
        for (name, value) in raw_headers {
            if name == b"location" {
                if !has_location {
                    normalized_headers.push((name, quoted_url.clone()));
                    has_location = true;
                }
            } else {
                normalized_headers.push((name, value));
            }
        }
        if !has_location {
            normalized_headers.push((b"location".to_vec(), quoted_url));
        }

        Ok(Self {
            status_code,
            headers: normalized_headers,
            body: Vec::new(),
        })
    }

    /// Creates a response from explicit status, body, and ordered raw headers.
    ///
    /// This constructor does not validate headers or synthesize defaults; it
    /// preserves the supplied bytes and repeated fields exactly.
    #[must_use]
    pub fn from_parts(
        status_code: u16,
        body: impl Into<Vec<u8>>,
        headers: impl IntoIterator<Item = (Vec<u8>, Vec<u8>)>,
    ) -> Self {
        Self {
            status_code,
            headers: headers.into_iter().collect(),
            body: body.into(),
        }
    }

    /// Creates a response while applying Starlette's default header rules.
    ///
    /// Input header names are lowercased and names/values are encoded as
    /// Latin-1. Existing headers retain their order, including duplicate
    /// fields. `content-length` is added when absent except for informational,
    /// 204, and 304 statuses. `content-type` is added from `media_type` when
    /// supplied and absent; text media types receive the UTF-8 charset unless
    /// they already contain a charset parameter.
    ///
    /// This accepts already-rendered body bytes. Converting Python content
    /// objects to those bytes remains the responsibility of the Python
    /// compatibility boundary.
    ///
    /// # Errors
    ///
    /// Returns [`ResponseError::HeaderDataIsNotLatin1`] if a header name,
    /// value, or media type cannot be encoded as Latin-1.
    pub fn from_content<B, H, K, V>(
        status_code: u16,
        body: B,
        media_type: Option<&str>,
        headers: H,
    ) -> Result<Self, ResponseError>
    where
        B: Into<Vec<u8>>,
        H: IntoIterator<Item = (K, V)>,
        K: AsRef<str>,
        V: AsRef<str>,
    {
        let body = body.into();
        let mut raw_headers = Vec::new();
        for (name, value) in headers {
            let lower_name = name.as_ref().to_lowercase();
            raw_headers.push((
                encode_latin1(&lower_name).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
                encode_latin1(value.as_ref()).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
            ));
        }

        let has_content_length = raw_headers
            .iter()
            .any(|(name, _)| name.as_slice() == b"content-length");
        let has_content_type = raw_headers
            .iter()
            .any(|(name, _)| name.as_slice() == b"content-type");

        if !has_content_length && status_code >= 200 && status_code != 204 && status_code != 304 {
            raw_headers.push((
                b"content-length".to_vec(),
                body.len().to_string().into_bytes(),
            ));
        }

        if !has_content_type {
            if let Some(media_type) = media_type {
                let mut content_type = media_type.to_owned();
                if media_type.starts_with("text/")
                    && !media_type.to_ascii_lowercase().contains("charset=")
                {
                    content_type.push_str("; charset=utf-8");
                }
                raw_headers.push((
                    b"content-type".to_vec(),
                    encode_latin1(&content_type).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
                ));
            }
        }

        Ok(Self {
            status_code,
            headers: raw_headers,
            body,
        })
    }

    /// Returns the response status code.
    #[must_use]
    pub const fn status_code(&self) -> u16 {
        self.status_code
    }

    /// Returns response headers in wire order, retaining duplicate names.
    #[must_use]
    pub fn headers(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.headers
    }

    /// Returns the response body bytes.
    #[must_use]
    pub fn body(&self) -> &[u8] {
        &self.body
    }

    /// Appends a cookie using Starlette's default cookie attributes.
    ///
    /// The output has `Path=/; SameSite=lax` attributes. Calling this multiple
    /// times appends distinct `set-cookie` headers in call order. Values that
    /// need quoting are quoted and escaped using the `SimpleCookie` format.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid ASCII cookie names, values containing
    /// control characters, or data that cannot be encoded as Latin-1. Commas,
    /// semicolons, and non-ASCII Latin-1 values are quoted and octal-escaped
    /// like `http.cookies.SimpleCookie`.
    pub fn set_cookie(&mut self, key: &str, value: &str) -> Result<(), ResponseError> {
        self.set_cookie_with_options(key, value, &CookieOptions::default())
    }

    /// Appends a cookie using the supplied Starlette cookie attributes.
    ///
    /// Attribute spelling and ordering follow `http.cookies.Morsel`.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid cookie data, an invalid SameSite value,
    /// or data that cannot be encoded as Latin-1.
    pub fn set_cookie_with_options(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), ResponseError> {
        if key.is_empty() || !is_cookie_token(key) {
            return Err(ResponseError::InvalidCookieName);
        }
        if value.chars().any(is_cookie_control) {
            return Err(ResponseError::InvalidCookieValue);
        }
        if options.samesite.as_ref().is_some_and(|samesite| {
            !matches!(
                samesite.to_ascii_lowercase().as_str(),
                "strict" | "lax" | "none"
            )
        }) {
            return Err(ResponseError::InvalidSameSite);
        }

        let mut cookie = encode_latin1(key).ok_or(ResponseError::CookieDataIsNotLatin1)?;
        cookie.push(b'=');
        if is_cookie_token(value) {
            cookie.extend(encode_latin1(value).ok_or(ResponseError::CookieDataIsNotLatin1)?);
        } else {
            cookie.push(b'"');
            for character in value.chars() {
                append_quoted_cookie_char(&mut cookie, character)?;
            }
            cookie.push(b'"');
        }
        append_cookie_attribute(&mut cookie, "Domain", options.domain.as_deref())?;
        append_cookie_attribute(&mut cookie, "expires", options.expires.as_deref())?;
        append_cookie_flag(&mut cookie, "HttpOnly", options.httponly);
        append_cookie_attribute(&mut cookie, "Max-Age", options.max_age.as_deref())?;
        append_cookie_flag(&mut cookie, "Partitioned", options.partitioned);
        append_cookie_attribute(&mut cookie, "Path", options.path.as_deref())?;
        append_cookie_attribute(&mut cookie, "SameSite", options.samesite.as_deref())?;
        append_cookie_flag(&mut cookie, "Secure", options.secure);
        self.headers.push((b"set-cookie".to_vec(), cookie));
        Ok(())
    }

    /// Returns the response-start and response-body ASGI messages in send order.
    ///
    /// The body message omits `more_body`, as Starlette's `Response.__call__`
    /// does for a single final body chunk.
    #[must_use]
    pub fn asgi_events(&self) -> [ResponseEvent; 2] {
        [
            ResponseEvent::Start {
                status_code: self.status_code,
                headers: self.headers.clone(),
            },
            ResponseEvent::Body {
                body: self.body.clone(),
            },
        ]
    }

    /// Starts a response ASGI call with an optional runtime-owned callback.
    #[must_use]
    pub fn call_state(&self, has_background_callback: bool) -> ResponseCall {
        ResponseCall {
            events: self.asgi_events(),
            has_background_callback,
            phase: ResponseCallPhase::SendStart,
        }
    }
}

impl ResponseCall {
    /// Returns the operation required to advance this call.
    #[must_use]
    pub fn step(&self) -> ResponseCallStep {
        match &self.phase {
            ResponseCallPhase::SendStart => ResponseCallStep::Send(self.events[0].clone()),
            ResponseCallPhase::SendBody => ResponseCallStep::Send(self.events[1].clone()),
            ResponseCallPhase::RunBackground => ResponseCallStep::RunBackground,
            ResponseCallPhase::Complete => ResponseCallStep::Complete,
            ResponseCallPhase::Failed => ResponseCallStep::Failed,
        }
    }

    /// Applies one operation result and returns the next required step.
    pub fn advance<E>(
        &mut self,
        input: ResponseCallInput<E>,
    ) -> Result<ResponseCallStep, ResponseCallError<E>> {
        let phase = std::mem::replace(&mut self.phase, ResponseCallPhase::Failed);
        self.phase = match (phase, input) {
            (ResponseCallPhase::SendStart, ResponseCallInput::Send(Ok(()))) => {
                ResponseCallPhase::SendBody
            }
            (ResponseCallPhase::SendBody, ResponseCallInput::Send(Ok(()))) => {
                if self.has_background_callback {
                    ResponseCallPhase::RunBackground
                } else {
                    ResponseCallPhase::Complete
                }
            }
            (
                ResponseCallPhase::SendStart | ResponseCallPhase::SendBody,
                ResponseCallInput::Send(Err(error)),
            ) => return Err(ResponseCallError::Operation(error)),
            (ResponseCallPhase::RunBackground, ResponseCallInput::BackgroundFinished(Ok(()))) => {
                ResponseCallPhase::Complete
            }
            (
                ResponseCallPhase::RunBackground,
                ResponseCallInput::BackgroundFinished(Err(error)),
            ) => return Err(ResponseCallError::Operation(error)),
            (phase, _) => {
                if matches!(
                    &phase,
                    ResponseCallPhase::Complete | ResponseCallPhase::Failed
                ) {
                    self.phase = phase;
                }
                return Err(ResponseCallError::UnexpectedInput);
            }
        };

        Ok(self.step())
    }
}

impl StreamingResponse {
    /// Creates a streaming response from byte chunks and response metadata.
    ///
    /// Header names are lowercased and names and values are encoded as
    /// Latin-1. Existing headers retain their order and duplicates. A
    /// `content-length` header is not generated; an explicitly supplied one
    /// is retained. If `media_type` is set and no `content-type` header is
    /// supplied, text media types receive `charset=utf-8` unless they already
    /// contain a charset parameter.
    ///
    /// Each input chunk produces a body event with `more_body=true`, followed
    /// by one empty body event with `more_body=false`, including when there
    /// are no input chunks.
    ///
    /// # Errors
    ///
    /// Returns [`ResponseError::HeaderDataIsNotLatin1`] if a header name,
    /// value, or media type cannot be encoded as Latin-1.
    pub fn from_chunks<C, B, H, K, V>(
        status_code: u16,
        chunks: C,
        media_type: Option<&str>,
        headers: H,
    ) -> Result<Self, ResponseError>
    where
        C: IntoIterator<Item = B>,
        B: Into<Vec<u8>>,
        H: IntoIterator<Item = (K, V)>,
        K: AsRef<str>,
        V: AsRef<str>,
    {
        let chunks = chunks.into_iter().map(Into::into).collect();
        let mut raw_headers = Vec::new();
        for (name, value) in headers {
            let lower_name = name.as_ref().to_lowercase();
            raw_headers.push((
                encode_latin1(&lower_name).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
                encode_latin1(value.as_ref()).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
            ));
        }

        let has_content_type = raw_headers
            .iter()
            .any(|(name, _)| name.as_slice() == b"content-type");
        if !has_content_type {
            if let Some(media_type) = media_type {
                let mut content_type = media_type.to_owned();
                if media_type.starts_with("text/")
                    && !media_type.to_ascii_lowercase().contains("charset=")
                {
                    content_type.push_str("; charset=utf-8");
                }
                raw_headers.push((
                    b"content-type".to_vec(),
                    encode_latin1(&content_type).ok_or(ResponseError::HeaderDataIsNotLatin1)?,
                ));
            }
        }

        Ok(Self {
            status_code,
            headers: raw_headers,
            chunks,
        })
    }

    /// Appends a cookie using the same encoding and validation as [`Response`].
    pub fn set_cookie(&mut self, key: &str, value: &str) -> Result<(), ResponseError> {
        let mut response = Response {
            status_code: self.status_code,
            headers: self.headers.clone(),
            body: Vec::new(),
        };
        response.set_cookie(key, value)?;
        self.headers = response.headers;
        Ok(())
    }

    /// Returns the response status code.
    #[must_use]
    pub const fn status_code(&self) -> u16 {
        self.status_code
    }

    /// Returns response headers in wire order, retaining duplicate names.
    #[must_use]
    pub fn headers(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.headers
    }

    /// Returns the pre-collected body chunks.
    #[must_use]
    pub fn chunks(&self) -> &[Vec<u8>] {
        &self.chunks
    }

    /// Returns the `http.response.start` event for this response.
    #[must_use]
    pub fn start_event(&self) -> StreamingResponseEvent {
        StreamingResponseEvent::Start {
            status_code: self.status_code,
            headers: self.headers.clone(),
        }
    }

    /// Creates one streamed body event with the supplied continuation flag.
    #[must_use]
    pub fn body_event(body: impl Into<Vec<u8>>, more_body: bool) -> StreamingResponseEvent {
        StreamingResponseEvent::Body {
            body: body.into(),
            more_body,
        }
    }

    /// Creates the final empty body event for a completed stream.
    #[must_use]
    pub fn final_event() -> StreamingResponseEvent {
        Self::body_event(Vec::new(), false)
    }

    /// Starts a lazy ASGI call driven by one chunk pull per state-machine step.
    #[must_use]
    pub fn call_state(&self, has_background_callback: bool) -> StreamingResponseCall {
        StreamingResponseCall::new(self, has_background_callback)
    }

    /// Returns the ASGI response events in send order.
    ///
    /// Every input chunk is sent with `more_body=true`. The sequence always
    /// ends with an empty body carrying `more_body=false`.
    #[must_use]
    pub fn asgi_events(&self) -> Vec<StreamingResponseEvent> {
        let mut events = Vec::with_capacity(self.chunks.len() + 2);
        events.push(self.start_event());
        events.extend(
            self.chunks
                .iter()
                .cloned()
                .map(|body| Self::body_event(body, true)),
        );
        events.push(Self::final_event());
        events
    }
}

impl StreamingResponseCall {
    /// Starts a streaming ASGI call for `response`.
    ///
    /// `has_background_callback` records whether the caller supplied a
    /// background operation. The callback itself remains owned and invoked by
    /// the runtime adapter after the final response event succeeds.
    #[must_use]
    pub fn new(response: &StreamingResponse, has_background_callback: bool) -> Self {
        Self {
            start_event: response.start_event(),
            has_background_callback,
            phase: StreamingResponseCallPhase::SendStart,
        }
    }

    /// Returns the operation required to advance this call.
    ///
    /// The caller must report the operation's result to [`Self::advance`]
    /// before requesting the next step. Terminal steps can be inspected
    /// repeatedly.
    #[must_use]
    pub fn step(&self) -> StreamingResponseCallStep {
        match &self.phase {
            StreamingResponseCallPhase::SendStart => {
                StreamingResponseCallStep::Send(self.start_event.clone())
            }
            StreamingResponseCallPhase::PullChunk => StreamingResponseCallStep::PullChunk,
            StreamingResponseCallPhase::SendChunk(body) => {
                StreamingResponseCallStep::Send(StreamingResponse::body_event(body.clone(), true))
            }
            StreamingResponseCallPhase::SendFinal => {
                StreamingResponseCallStep::Send(StreamingResponse::final_event())
            }
            StreamingResponseCallPhase::RunBackground => StreamingResponseCallStep::RunBackground,
            StreamingResponseCallPhase::Complete => StreamingResponseCallStep::Complete,
            StreamingResponseCallPhase::Failed => StreamingResponseCallStep::Failed,
        }
    }

    /// Applies one operation result and returns the next required step.
    ///
    /// Each error value is returned unchanged in
    /// [`StreamingResponseCallError::Operation`]. The state becomes terminal
    /// before the error is returned, so a failed send, pull, or callback can
    /// never produce another response or background step.
    pub fn advance<E>(
        &mut self,
        input: StreamingResponseCallInput<E>,
    ) -> Result<StreamingResponseCallStep, StreamingResponseCallError<E>> {
        let phase = std::mem::replace(&mut self.phase, StreamingResponseCallPhase::Failed);
        self.phase = match (phase, input) {
            (StreamingResponseCallPhase::SendStart, StreamingResponseCallInput::Send(Ok(())))
            | (
                StreamingResponseCallPhase::SendChunk(_),
                StreamingResponseCallInput::Send(Ok(())),
            ) => StreamingResponseCallPhase::PullChunk,
            (StreamingResponseCallPhase::SendFinal, StreamingResponseCallInput::Send(Ok(()))) => {
                if self.has_background_callback {
                    StreamingResponseCallPhase::RunBackground
                } else {
                    StreamingResponseCallPhase::Complete
                }
            }
            (
                StreamingResponseCallPhase::SendStart
                | StreamingResponseCallPhase::SendChunk(_)
                | StreamingResponseCallPhase::SendFinal,
                StreamingResponseCallInput::Send(Err(error)),
            ) => return Err(StreamingResponseCallError::Operation(error)),
            (
                StreamingResponseCallPhase::PullChunk,
                StreamingResponseCallInput::ChunkPulled(Ok(Some(body))),
            ) => StreamingResponseCallPhase::SendChunk(body),
            (
                StreamingResponseCallPhase::PullChunk,
                StreamingResponseCallInput::ChunkPulled(Ok(None)),
            ) => StreamingResponseCallPhase::SendFinal,
            (
                StreamingResponseCallPhase::PullChunk,
                StreamingResponseCallInput::ChunkPulled(Err(error)),
            ) => return Err(StreamingResponseCallError::Operation(error)),
            (
                StreamingResponseCallPhase::RunBackground,
                StreamingResponseCallInput::BackgroundFinished(Ok(())),
            ) => StreamingResponseCallPhase::Complete,
            (
                StreamingResponseCallPhase::RunBackground,
                StreamingResponseCallInput::BackgroundFinished(Err(error)),
            ) => return Err(StreamingResponseCallError::Operation(error)),
            (phase, _) => {
                if matches!(
                    &phase,
                    StreamingResponseCallPhase::Complete | StreamingResponseCallPhase::Failed
                ) {
                    self.phase = phase;
                }
                return Err(StreamingResponseCallError::UnexpectedInput);
            }
        };

        Ok(self.step())
    }
}

impl StreamingResponseDisconnectListener {
    /// Creates a listener that is ready to receive its first ASGI message.
    #[must_use]
    pub const fn new() -> Self {
        Self {
            phase: StreamingResponseDisconnectListenerPhase::Receive,
        }
    }

    /// Returns the operation required to advance this listener.
    #[must_use]
    pub const fn step(&self) -> StreamingResponseDisconnectListenerStep {
        match self.phase {
            StreamingResponseDisconnectListenerPhase::Receive => {
                StreamingResponseDisconnectListenerStep::Receive
            }
            StreamingResponseDisconnectListenerPhase::Complete => {
                StreamingResponseDisconnectListenerStep::Complete
            }
            StreamingResponseDisconnectListenerPhase::Failed => {
                StreamingResponseDisconnectListenerStep::Failed
            }
        }
    }

    /// Applies one receive result and returns the next required step.
    ///
    /// Any message other than `http.disconnect` starts another receive
    /// iteration. Receive and conversion errors are returned unchanged and
    /// move the listener to a terminal failed state.
    pub fn advance<E>(
        &mut self,
        input: StreamingResponseDisconnectListenerInput<E>,
    ) -> Result<StreamingResponseDisconnectListenerStep, StreamingResponseDisconnectListenerError<E>>
    {
        let phase = std::mem::replace(
            &mut self.phase,
            StreamingResponseDisconnectListenerPhase::Failed,
        );
        self.phase = match (phase, input) {
            (
                StreamingResponseDisconnectListenerPhase::Receive,
                StreamingResponseDisconnectListenerInput::Received(
                    StreamingResponseDisconnectMessage::Other,
                ),
            ) => StreamingResponseDisconnectListenerPhase::Receive,
            (
                StreamingResponseDisconnectListenerPhase::Receive,
                StreamingResponseDisconnectListenerInput::Received(
                    StreamingResponseDisconnectMessage::Disconnect,
                ),
            ) => StreamingResponseDisconnectListenerPhase::Complete,
            (
                StreamingResponseDisconnectListenerPhase::Receive,
                StreamingResponseDisconnectListenerInput::ReceiveFailed(error),
            ) => return Err(StreamingResponseDisconnectListenerError::Operation(error)),
            (phase, _) => {
                if matches!(
                    phase,
                    StreamingResponseDisconnectListenerPhase::Complete
                        | StreamingResponseDisconnectListenerPhase::Failed
                ) {
                    self.phase = phase;
                }
                return Err(StreamingResponseDisconnectListenerError::UnexpectedInput);
            }
        };

        Ok(self.step())
    }
}

impl Default for StreamingResponseDisconnectListener {
    fn default() -> Self {
        Self::new()
    }
}

impl<E> StreamingResponseDisconnectCall<E> {
    /// Starts a pre-ASGI-2.4 stream-versus-disconnect race.
    ///
    /// Drive the stream branch with a [`StreamingResponseCall`] configured
    /// without a background callback, and the receive branch with a
    /// [`StreamingResponseDisconnectListener`]. This coordinator schedules the
    /// concurrent scope and the callback that follows a clean race outcome.
    #[must_use]
    pub const fn new(has_background_callback: bool) -> Self {
        Self {
            has_background_callback,
            phase: StreamingResponseDisconnectCallPhase::StartConcurrent,
            child_error: None,
            cancellation: None,
        }
    }

    /// Returns the operation required to advance the race.
    #[must_use]
    pub const fn step(&self) -> StreamingResponseDisconnectCallStep {
        match self.phase {
            StreamingResponseDisconnectCallPhase::StartConcurrent => {
                StreamingResponseDisconnectCallStep::StartConcurrent
            }
            StreamingResponseDisconnectCallPhase::AwaitFirstCompletion => {
                StreamingResponseDisconnectCallStep::AwaitFirstCompletion
            }
            StreamingResponseDisconnectCallPhase::CancelStream => {
                StreamingResponseDisconnectCallStep::CancelStream
            }
            StreamingResponseDisconnectCallPhase::CancelListener => {
                StreamingResponseDisconnectCallStep::CancelListener
            }
            StreamingResponseDisconnectCallPhase::CancelBoth => {
                StreamingResponseDisconnectCallStep::CancelBoth
            }
            StreamingResponseDisconnectCallPhase::RunBackground => {
                StreamingResponseDisconnectCallStep::RunBackground
            }
            StreamingResponseDisconnectCallPhase::Complete => {
                StreamingResponseDisconnectCallStep::Complete
            }
            StreamingResponseDisconnectCallPhase::Failed => {
                StreamingResponseDisconnectCallStep::Failed
            }
        }
    }

    /// Applies a branch, task-group, cancellation, or background result.
    ///
    /// The first stream completion cancels the listener; a listener completion
    /// means it observed `http.disconnect` and cancels the stream. A branch
    /// error still cancels its peer, but is returned after the task group exits.
    /// `Cancelled` requests cleanup of both branches and retains the original
    /// cancellation for propagation after the task group exits. The background
    /// callback runs only after a clean race and task-group exit.
    pub fn advance(
        &mut self,
        input: StreamingResponseDisconnectCallInput<E>,
    ) -> Result<StreamingResponseDisconnectCallStep, StreamingResponseDisconnectCallError<E>> {
        let phase = std::mem::replace(
            &mut self.phase,
            StreamingResponseDisconnectCallPhase::Failed,
        );
        self.phase = match (phase, input) {
            (
                StreamingResponseDisconnectCallPhase::StartConcurrent,
                StreamingResponseDisconnectCallInput::ConcurrentStarted,
            ) => StreamingResponseDisconnectCallPhase::AwaitFirstCompletion,
            (
                StreamingResponseDisconnectCallPhase::AwaitFirstCompletion,
                StreamingResponseDisconnectCallInput::StreamFinished(result),
            ) => {
                if let Err(error) = result {
                    self.child_error = Some(error);
                }
                StreamingResponseDisconnectCallPhase::CancelListener
            }
            (
                StreamingResponseDisconnectCallPhase::AwaitFirstCompletion,
                StreamingResponseDisconnectCallInput::ListenerFinished(result),
            ) => {
                if let Err(error) = result {
                    self.child_error = Some(error);
                }
                StreamingResponseDisconnectCallPhase::CancelStream
            }
            (
                StreamingResponseDisconnectCallPhase::CancelListener,
                StreamingResponseDisconnectCallInput::ListenerFinished(result),
            )
            | (
                StreamingResponseDisconnectCallPhase::CancelBoth,
                StreamingResponseDisconnectCallInput::ListenerFinished(result),
            ) => {
                if let Err(error) = result {
                    self.child_error.get_or_insert(error);
                }
                phase
            }
            (
                StreamingResponseDisconnectCallPhase::CancelStream,
                StreamingResponseDisconnectCallInput::StreamFinished(result),
            )
            | (
                StreamingResponseDisconnectCallPhase::CancelBoth,
                StreamingResponseDisconnectCallInput::StreamFinished(result),
            ) => {
                if let Err(error) = result {
                    self.child_error.get_or_insert(error);
                }
                phase
            }
            (
                StreamingResponseDisconnectCallPhase::AwaitFirstCompletion,
                StreamingResponseDisconnectCallInput::Cancelled(error),
            ) => {
                self.cancellation = Some(error);
                StreamingResponseDisconnectCallPhase::CancelBoth
            }
            (
                StreamingResponseDisconnectCallPhase::CancelStream
                | StreamingResponseDisconnectCallPhase::CancelListener
                | StreamingResponseDisconnectCallPhase::CancelBoth,
                StreamingResponseDisconnectCallInput::ConcurrentFinished(Err(error)),
            ) => return Err(StreamingResponseDisconnectCallError::Operation(error)),
            (
                StreamingResponseDisconnectCallPhase::CancelStream
                | StreamingResponseDisconnectCallPhase::CancelListener
                | StreamingResponseDisconnectCallPhase::CancelBoth,
                StreamingResponseDisconnectCallInput::ConcurrentFinished(Ok(())),
            ) => {
                if let Some(error) = self.child_error.take() {
                    return Err(StreamingResponseDisconnectCallError::Operation(error));
                }
                if let Some(error) = self.cancellation.take() {
                    return Err(StreamingResponseDisconnectCallError::Operation(error));
                }
                if self.has_background_callback {
                    StreamingResponseDisconnectCallPhase::RunBackground
                } else {
                    StreamingResponseDisconnectCallPhase::Complete
                }
            }
            (
                StreamingResponseDisconnectCallPhase::CancelStream
                | StreamingResponseDisconnectCallPhase::CancelListener,
                StreamingResponseDisconnectCallInput::Cancelled(error),
            ) => {
                self.cancellation = Some(error);
                StreamingResponseDisconnectCallPhase::CancelBoth
            }
            (
                StreamingResponseDisconnectCallPhase::CancelBoth,
                StreamingResponseDisconnectCallInput::Cancelled(error),
            ) => {
                self.cancellation = Some(error);
                StreamingResponseDisconnectCallPhase::CancelBoth
            }
            (
                StreamingResponseDisconnectCallPhase::RunBackground,
                StreamingResponseDisconnectCallInput::BackgroundFinished(Ok(())),
            ) => StreamingResponseDisconnectCallPhase::Complete,
            (
                StreamingResponseDisconnectCallPhase::RunBackground,
                StreamingResponseDisconnectCallInput::BackgroundFinished(Err(error)),
            ) => return Err(StreamingResponseDisconnectCallError::Operation(error)),
            (
                StreamingResponseDisconnectCallPhase::RunBackground,
                StreamingResponseDisconnectCallInput::Cancelled(error),
            ) => return Err(StreamingResponseDisconnectCallError::Operation(error)),
            (phase, _) => {
                if matches!(
                    phase,
                    StreamingResponseDisconnectCallPhase::Complete
                        | StreamingResponseDisconnectCallPhase::Failed
                ) {
                    self.phase = phase;
                }
                return Err(StreamingResponseDisconnectCallError::UnexpectedInput);
            }
        };

        Ok(self.step())
    }
}

const DEBUG_STYLES: &str = r#"
p {
    color: #211c1c;
}
.traceback-container {
    border: 1px solid #038BB8;
}
.traceback-title {
    background-color: #038BB8;
    color: lemonchiffon;
    padding: 12px;
    font-size: 20px;
    margin-top: 0px;
}
.frame-line {
    padding-left: 10px;
    font-family: monospace;
}
.frame-filename {
    font-family: monospace;
}
.center-line {
    background-color: #038BB8;
    color: #f9f6e1;
    padding: 5px 0px 5px 5px;
}
.lineno {
    margin-right: 5px;
}
.frame-title {
    font-weight: unset;
    padding: 10px 10px 10px 10px;
    background-color: #E4F4FD;
    margin-right: 10px;
    color: #191f21;
    font-size: 17px;
    border: 1px solid #c7dce8;
}
.collapse-btn {
    float: right;
    padding: 0px 5px 1px 5px;
    border: solid 1px #96aebb;
    cursor: pointer;
}
.collapsed {
  display: none;
}
.source-code {
  font-family: courier;
  font-size: small;
  padding-bottom: 10px;
}
"#;

const DEBUG_SCRIPT: &str = r#"
<script type="text/javascript">
    function collapse(element){
        const frameId = element.getAttribute("data-frame-id");
        const frame = document.getElementById(frameId);

        if (frame.classList.contains("collapsed")){
            element.innerHTML = "&#8210;";
            frame.classList.remove("collapsed");
        } else {
            element.innerHTML = "+";
            frame.classList.add("collapsed");
        }
    }
</script>
"#;

const DEBUG_TEMPLATE: &str = r#"
<html>
    <head>
        <style type='text/css'>
            {styles}
        </style>
        <title>Starlette Debugger</title>
    </head>
    <body>
        <h1>500 Server Error</h1>
        <h2>{error}</h2>
        <div class="traceback-container">
            <p class="traceback-title">Traceback</p>
            <div>{exc_html}</div>
        </div>
        {js}
    </body>
</html>
"#;

const DEBUG_FRAME_TEMPLATE: &str = r#"
<div>
    <p class="frame-title">File <span class="frame-filename">{frame_filename}</span>,
    line <i>{frame_lineno}</i>,
    in <b>{frame_name}</b>
    <span class="collapse-btn" data-frame-id="{frame_filename}-{frame_lineno}" onclick="collapse(this)">{collapse_button}</span>
    </p>
    <div id="{frame_filename}-{frame_lineno}" class="source-code {collapsed}">{code_context}</div>
</div>
"#;

const DEBUG_LINE_TEMPLATE: &str = r#"
<p><span class="frame-line">
<span class="lineno">{lineno}.</span> {line}</span></p>
"#;

const DEBUG_CENTER_LINE_TEMPLATE: &str = r#"
<p class="center-line"><span class="frame-line center-line">
<span class="lineno">{lineno}.</span> {line}</span></p>
"#;

fn render_debug_traceback_html(
    exception_type: &str,
    exception_message: &str,
    frames: &[DebugTracebackFrame],
) -> String {
    let mut rendered_frames = String::new();
    for (frame_index, frame) in frames.iter().rev().enumerate() {
        render_debug_frame(&mut rendered_frames, frame, frame_index > 0);
    }

    let error = format!(
        "{}: {}",
        escape_html(exception_type),
        escape_html(exception_message)
    );
    interpolate(
        DEBUG_TEMPLATE,
        &[
            ("styles", DEBUG_STYLES),
            ("error", &error),
            ("exc_html", &rendered_frames),
            ("js", DEBUG_SCRIPT),
        ],
    )
}

fn render_debug_frame(output: &mut String, frame: &DebugTracebackFrame, collapsed: bool) {
    let mut code_context = String::new();
    for (index, line) in frame.source_lines.iter().enumerate() {
        let escaped_line = escape_html(line).replace(' ', "&nbsp");
        let line_number = frame.line as i128 - frame.center_index as i128 + index as i128;
        let template = if index == frame.center_index {
            DEBUG_CENTER_LINE_TEMPLATE
        } else {
            DEBUG_LINE_TEMPLATE
        };
        let rendered_line = interpolate(
            template,
            &[
                ("lineno", &line_number.to_string()),
                ("line", &escaped_line),
            ],
        );
        code_context.push_str(&rendered_line);
    }

    let escaped_filename = escape_html(&frame.filename);
    let escaped_function = escape_html(&frame.function);
    let line_number = frame.line.to_string();
    let frame_html = interpolate(
        DEBUG_FRAME_TEMPLATE,
        &[
            ("frame_filename", &escaped_filename),
            ("frame_lineno", &line_number),
            ("frame_name", &escaped_function),
            ("collapse_button", if collapsed { "+" } else { "&#8210;" }),
            ("collapsed", if collapsed { "collapsed" } else { "" }),
            ("code_context", &code_context),
        ],
    );
    output.push_str(&frame_html);
}

fn escape_html(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '&' => escaped.push_str("&amp;"),
            '<' => escaped.push_str("&lt;"),
            '>' => escaped.push_str("&gt;"),
            '"' => escaped.push_str("&quot;"),
            '\'' => escaped.push_str("&#x27;"),
            _ => escaped.push(character),
        }
    }
    escaped
}

/// Substitutes placeholders once, leaving values unparsed and preventing
/// traceback text from being interpreted as another template fragment.
fn interpolate(template: &str, replacements: &[(&str, &str)]) -> String {
    let mut rendered = String::with_capacity(template.len());
    let mut cursor = 0;
    while let Some(relative_start) = template[cursor..].find('{') {
        let start = cursor + relative_start;
        rendered.push_str(&template[cursor..start]);
        let Some(relative_end) = template[start..].find('}') else {
            rendered.push_str(&template[start..]);
            return rendered;
        };
        let end = start + relative_end;
        let name = &template[start + 1..end];
        if let Some((_, value)) = replacements.iter().find(|(key, _)| *key == name) {
            rendered.push_str(value);
        } else {
            rendered.push_str(&template[start..=end]);
        }
        cursor = end + 1;
    }
    rendered.push_str(&template[cursor..]);
    rendered
}

fn is_cookie_token(value: &str) -> bool {
    value.chars().all(|character| {
        character.is_ascii_alphanumeric()
            || matches!(
                character,
                '_' | '!'
                    | '#'
                    | '$'
                    | '%'
                    | '&'
                    | '\''
                    | '*'
                    | '+'
                    | '-'
                    | '.'
                    | '^'
                    | '`'
                    | '|'
                    | '~'
                    | ':'
            )
    })
}

fn is_cookie_control(character: char) -> bool {
    matches!(u32::from(character), 0..=31 | 127)
}

fn append_cookie_attribute(
    cookie: &mut Vec<u8>,
    name: &str,
    value: Option<&str>,
) -> Result<(), ResponseError> {
    if let Some(value) = value.filter(|value| !value.is_empty()) {
        cookie.extend_from_slice(b"; ");
        cookie.extend_from_slice(name.as_bytes());
        cookie.push(b'=');
        cookie.extend(encode_latin1(value).ok_or(ResponseError::CookieDataIsNotLatin1)?);
    }
    Ok(())
}

fn append_cookie_flag(cookie: &mut Vec<u8>, name: &str, enabled: bool) {
    if enabled {
        cookie.extend_from_slice(b"; ");
        cookie.extend_from_slice(name.as_bytes());
    }
}

fn append_quoted_cookie_char(cookie: &mut Vec<u8>, character: char) -> Result<(), ResponseError> {
    let codepoint = u32::from(character);
    if matches!(character, '\\' | '"') {
        cookie.push(b'\\');
        cookie.push(encode_latin1_char(character).ok_or(ResponseError::CookieDataIsNotLatin1)?);
    } else if matches!(character, ',' | ';') || (127..=255).contains(&codepoint) {
        let encoded = encode_latin1_char(character).ok_or(ResponseError::CookieDataIsNotLatin1)?;
        cookie.push(b'\\');
        cookie.push(b'0' + (encoded >> 6));
        cookie.push(b'0' + ((encoded >> 3) & 0b111));
        cookie.push(b'0' + (encoded & 0b111));
    } else {
        cookie.push(encode_latin1_char(character).ok_or(ResponseError::CookieDataIsNotLatin1)?);
    }
    Ok(())
}

fn encode_latin1(value: &str) -> Option<Vec<u8>> {
    value.chars().map(encode_latin1_char).collect()
}

fn quote_redirect_url(url: &str) -> String {
    const SAFE: &[u8] = b":/%#?=@[]!$&'()*+,;";
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut quoted = String::with_capacity(url.len());
    for byte in url.as_bytes() {
        if byte.is_ascii_alphanumeric() || b"_.-~".contains(byte) || SAFE.contains(byte) {
            quoted.push(char::from(*byte));
        } else {
            quoted.push('%');
            quoted.push(char::from(HEX[(byte >> 4) as usize]));
            quoted.push(char::from(HEX[(byte & 0x0f) as usize]));
        }
    }
    quoted
}

fn encode_latin1_char(character: char) -> Option<u8> {
    let codepoint = u32::from(character);
    u8::try_from(codepoint).ok()
}
