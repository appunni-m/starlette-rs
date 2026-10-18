//! Rust-owned file response planning, byte-range handling, and streaming.

use std::fmt::{self, Display, Formatter};
use std::fs::{self, File, Metadata};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[cfg(feature = "fault-contract")]
use std::sync::atomic::{AtomicBool, Ordering};

use md5::{Digest, Md5};

use crate::python_float::python_float_string;
use crate::response::{
    CookieOptions, Response, ResponseError, append_response_header, delete_response_header,
    get_response_header, get_response_header_values, set_response_header,
};

const DEFAULT_CHUNK_SIZE: usize = 65_536;
const PYTHON_INT_MAX_STR_DIGITS: usize = 4_300;
type RawHeaderPair = (Vec<u8>, Vec<u8>);
type RawHeaders = Vec<RawHeaderPair>;

#[cfg(feature = "fault-contract")]
static FAIL_NEXT_RANDOM_BOUNDARY: AtomicBool = AtomicBool::new(false);

/// Arms one injected multipart boundary generation failure for the parity adapter.
///
/// This hook is present only when the non-default `fault-contract` feature is enabled.
#[cfg(feature = "fault-contract")]
#[doc(hidden)]
pub fn fault_contract_fail_next_random_boundary() {
    FAIL_NEXT_RANDOM_BOUNDARY.store(true, Ordering::SeqCst);
}

/// File metadata supplied by the caller instead of querying the filesystem.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileMetadata {
    size: u64,
    modified: SystemTime,
    modified_seconds_bits: u64,
    modified_text: String,
    stat_result: Option<FileStat>,
}

/// Filesystem stat fields retained for Python's `os.stat_result` representation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileStat {
    /// POSIX mode bits.
    pub mode: u32,
    /// Inode number.
    pub inode: u64,
    /// Device identifier.
    pub device: u64,
    /// Number of hard links.
    pub link_count: u64,
    /// Owning user identifier.
    pub user_id: u32,
    /// Owning group identifier.
    pub group_id: u32,
    /// File size in bytes.
    pub size: u64,
    /// Last access timestamp.
    pub access_time: FileStatTimestamp,
    /// Last modification timestamp.
    pub modified_time: FileStatTimestamp,
    /// Status change timestamp.
    pub change_time: FileStatTimestamp,
    /// Preferred I/O block size when exposed by the platform.
    pub block_size: Option<u64>,
    /// Number of allocated blocks when exposed by the platform.
    pub blocks: Option<u64>,
    /// Device identifier for special files when exposed by the platform.
    pub special_device: Option<u64>,
    /// File flags when exposed by the platform.
    pub flags: Option<u32>,
    /// Filesystem generation number when exposed by the platform.
    pub generation: Option<u32>,
    /// Creation time when exposed by the platform.
    pub birth_time: Option<FileStatTimestamp>,
}

/// A filesystem timestamp represented in Unix seconds and nanoseconds.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FileStatTimestamp {
    /// Whole seconds from the Unix epoch.
    pub seconds: i64,
    /// Nanoseconds within `seconds`.
    pub nanoseconds: i64,
}

impl FileStatTimestamp {
    /// Returns the timestamp as floating-point Unix seconds.
    #[must_use]
    pub fn unix_seconds(self) -> f64 {
        self.seconds as f64 + self.nanoseconds as f64 / 1_000_000_000.0
    }
}

impl FileStat {
    fn from_metadata(metadata: &Metadata) -> Option<Self> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;

            let stat = Self {
                mode: metadata.mode(),
                inode: metadata.ino(),
                device: metadata.dev(),
                link_count: metadata.nlink(),
                user_id: metadata.uid(),
                group_id: metadata.gid(),
                size: metadata.size(),
                access_time: FileStatTimestamp {
                    seconds: metadata.atime(),
                    nanoseconds: metadata.atime_nsec(),
                },
                modified_time: FileStatTimestamp {
                    seconds: metadata.mtime(),
                    nanoseconds: metadata.mtime_nsec(),
                },
                change_time: FileStatTimestamp {
                    seconds: metadata.ctime(),
                    nanoseconds: metadata.ctime_nsec(),
                },
                block_size: Some(metadata.blksize()),
                blocks: Some(metadata.blocks()),
                special_device: Some(metadata.rdev()),
                flags: None,
                generation: None,
                birth_time: None,
            };

            #[cfg(target_os = "macos")]
            let stat = {
                use std::os::macos::fs::MetadataExt as MacMetadataExt;

                Self {
                    flags: Some(MacMetadataExt::st_flags(metadata)),
                    generation: Some(MacMetadataExt::st_gen(metadata)),
                    birth_time: Some(FileStatTimestamp {
                        seconds: MacMetadataExt::st_birthtime(metadata),
                        nanoseconds: MacMetadataExt::st_birthtime_nsec(metadata),
                    }),
                    ..stat
                }
            };

            Some(stat)
        }
        #[cfg(not(unix))]
        {
            // Keep unsupported platforms on Python's own stat_result implementation
            // instead of filling unavailable tuple fields with invented values.
            let _ = metadata;
            None
        }
    }
}

impl FileMetadata {
    /// Creates metadata from Unix seconds using Python-compatible float text.
    ///
    /// # Errors
    ///
    /// Returns [`FileResponseError::InvalidTimestamp`] if the timestamp is not
    /// finite or cannot be represented by [`SystemTime`].
    pub fn from_unix_seconds(size: u64, modified_seconds: f64) -> Result<Self, FileResponseError> {
        let modified = system_time_from_seconds(modified_seconds)
            .ok_or(FileResponseError::InvalidTimestamp)?;
        Ok(Self {
            size,
            modified,
            modified_seconds_bits: modified_seconds.to_bits(),
            modified_text: python_float_text(modified_seconds),
            stat_result: None,
        })
    }

    pub(crate) fn from_metadata(metadata: &Metadata) -> Result<Self, FileResponseError> {
        let modified = metadata.modified().map_err(FileResponseError::StatIo)?;
        let seconds = unix_seconds(modified);
        Ok(Self {
            size: metadata.len(),
            modified,
            modified_seconds_bits: seconds.to_bits(),
            modified_text: python_float_text(seconds),
            stat_result: FileStat::from_metadata(metadata),
        })
    }

    /// Returns the file length used to prepare response headers.
    #[must_use]
    pub fn size(&self) -> u64 {
        self.size
    }

    /// Returns the modification time as Unix seconds.
    #[must_use]
    pub fn modified_unix_seconds(&self) -> f64 {
        f64::from_bits(self.modified_seconds_bits)
    }

    /// Returns the full filesystem stat snapshot when the platform exposes it.
    #[must_use]
    pub fn stat_result(&self) -> Option<&FileStat> {
        self.stat_result.as_ref()
    }
}

/// A file response whose request decisions and output are planned in Rust.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileResponse {
    path: PathBuf,
    display_path: String,
    status_code: u16,
    media_type: String,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    stat_override: Option<FileMetadata>,
    stat_headers_prepared: bool,
    chunk_size: usize,
    max_ranges: usize,
}

/// Constructor options for [`FileResponse`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileResponseOptions {
    /// Explicit content type, or `None` to guess it from the file name.
    pub media_type: Option<String>,
    /// Optional download filename and content-disposition value.
    pub filename: Option<String>,
    /// Caller-supplied stat data that skips the filesystem metadata lookup.
    pub stat_override: Option<FileMetadata>,
    /// Content-disposition type, usually `attachment` or `inline`.
    pub content_disposition_type: String,
    /// Maximum number of file bytes sent in each body event.
    pub chunk_size: usize,
    /// Maximum number of ranges accepted from one Range header.
    pub max_ranges: usize,
}

/// The two Python-visible header lists used while planning a file response.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileResponseHeaderViews {
    /// Raw pairs retained by the cached `MutableHeaders` view.
    pub view: Vec<(Vec<u8>, Vec<u8>)>,
    /// Raw pairs currently exposed through `FileResponse.raw_headers`.
    pub raw: Vec<(Vec<u8>, Vec<u8>)>,
    /// Whether `view` and `raw` refer to the same Python list.
    pub view_is_raw: bool,
}

impl Default for FileResponseOptions {
    fn default() -> Self {
        Self {
            media_type: None,
            filename: None,
            stat_override: None,
            content_disposition_type: "attachment".to_owned(),
            chunk_size: DEFAULT_CHUNK_SIZE,
            max_ranges: 100,
        }
    }
}

/// An event emitted while streaming a [`FileResponse`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FileResponseEvent {
    /// The `http.response.start` message.
    Start {
        /// HTTP response status.
        status_code: u16,
        /// Ordered headers, including duplicate fields.
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    },
    /// A streamed `http.response.body` message.
    Body {
        /// This body chunk.
        body: Vec<u8>,
        /// Whether another body message follows; `None` preserves Response's
        /// body message shape for range-error fallback responses.
        more_body: Option<bool>,
    },
    /// An ASGI `http.response.pathsend` message.
    Pathsend {
        /// String form of the original path argument.
        path: String,
    },
}

/// The next action for a runtime driving a [`FileResponseCall`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FileResponseCallStep {
    /// Send one ASGI response event.
    Send(FileResponseEvent),
    /// Invoke and await the caller-owned background callback.
    RunBackground,
    /// The response completed successfully.
    Complete,
    /// The response call is already failed.
    Failed,
}

/// An operation result supplied to [`FileResponseCall::advance`].
#[derive(Debug, PartialEq, Eq)]
pub enum FileResponseCallInput<E> {
    /// Result of awaiting the ASGI `send` callable.
    Send(Result<(), E>),
    /// Result of invoking and awaiting the background callback.
    BackgroundFinished(Result<(), E>),
}

/// A failed send, background callback, or invalid state-machine input.
#[derive(Debug, PartialEq, Eq)]
pub enum FileResponseCallError<E> {
    /// The supplied Python operation failed.
    Operation(E),
    /// No operation result was expected in the current state.
    UnexpectedInput,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum FileResponseMode {
    Simple,
    SingleRange {
        start: u64,
        end: u64,
    },
    MultipleRanges {
        ranges: Vec<(u64, u64)>,
        boundary: String,
        content_type: Vec<u8>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum FileResponsePhase {
    Start,
    SelectBody,
    SimpleBody,
    SingleRangeBody { cursor: u64, end: u64 },
    MultipartHeader { index: usize },
    MultipartBody { index: usize, cursor: u64 },
    MultipartSeparator { index: usize },
    MultipartFinal,
    Background,
    Complete,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum PendingOperation {
    Send(FileResponsePhase),
    Background,
}

/// A single Rust-controlled ASGI call for a file response.
pub struct FileResponseCall {
    phase: FileResponsePhase,
    pending: Option<PendingOperation>,
    status_code: u16,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    base_headers: Vec<(Vec<u8>, Vec<u8>)>,
    mode: FileResponseMode,
    path: PathBuf,
    display_path: String,
    chunk_size: usize,
    send_header_only: bool,
    send_pathsend: bool,
    file: Option<File>,
    background: bool,
    file_size: u64,
    error_body: Option<Vec<u8>>,
    defer_open_path_conversion: bool,
}

/// An error while preparing or streaming a file response.
#[derive(Debug)]
pub enum FileResponseError {
    /// A response header contains a character outside Latin-1.
    HeaderDataIsNotLatin1 {
        /// The original value that failed encoding.
        value: String,
        /// Character index of the first value that failed encoding.
        index: usize,
    },
    /// File modification time is invalid or outside the platform time range.
    InvalidTimestamp,
    /// File modification time resolves to a year Python `datetime` cannot represent.
    TimestampYearOutOfRange(i128),
    /// The path does not exist.
    MissingFile(String),
    /// The path exists but does not identify a regular file.
    NotAFile(String),
    /// A multipart byte-range response requires a content-type header.
    MissingContentType,
    /// Checked arithmetic could not represent a file response value.
    ArithmeticOverflow,
    /// A filesystem metadata operation failed.
    StatIo(io::Error),
    /// Secure random bytes could not be obtained for a multipart boundary.
    RandomSource,
}

impl Display for FileResponseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::HeaderDataIsNotLatin1 { .. } => {
                formatter.write_str("header data cannot be encoded as Latin-1")
            }
            Self::InvalidTimestamp => formatter.write_str("invalid file modification timestamp"),
            Self::TimestampYearOutOfRange(year) => write!(formatter, "year {year} is out of range"),
            Self::MissingFile(path) => write!(formatter, "File at path {path} does not exist."),
            Self::NotAFile(path) => write!(formatter, "File at path {path} is not a file."),
            Self::MissingContentType => formatter.write_str("content-type"),
            Self::ArithmeticOverflow => formatter.write_str("file response arithmetic overflow"),
            Self::StatIo(error) => Display::fmt(error, formatter),
            Self::RandomSource => formatter.write_str("could not generate multipart boundary"),
        }
    }
}

impl std::error::Error for FileResponseError {}

impl FileResponse {
    /// Compute the quoted file ETag from the caller's serialized stat values.
    ///
    /// Starlette hashes the UTF-8 representation of modification time, a hyphen,
    /// and size. Python callers can preserve their value representation before
    /// handing those bytes to this Rust implementation. This digest is an HTTP
    /// cache validator, not a security primitive.
    #[must_use]
    pub fn stat_etag(serialized_metadata: &[u8]) -> String {
        let digest = Md5::digest(serialized_metadata);
        format!("\"{}\"", lower_hex(&digest))
    }

    /// Creates a Starlette-compatible file response.
    ///
    /// `headers` retain input order and duplicates. The default content type
    /// is guessed from `filename` when present, otherwise from `path`.
    ///
    /// # Errors
    ///
    /// Returns [`FileResponseError::HeaderDataIsNotLatin1`] for values that
    /// cannot be encoded as HTTP response headers.
    pub fn new(
        path: PathBuf,
        display_path: impl Into<String>,
        status_code: u16,
        headers: &[(String, String)],
        options: FileResponseOptions,
    ) -> Result<Self, FileResponseError> {
        let mut raw_headers = normalize_headers(headers)?;
        // Starlette guesses from `filename or path`, so an empty filename
        // selects the path for MIME lookup while remaining set for disposition.
        let source = options
            .filename
            .as_deref()
            .filter(|filename| !filename.is_empty())
            .map_or_else(|| path.clone(), PathBuf::from);
        // CPython's MIME table classifies `.mjs` as `text/javascript`, while
        // mime_guess 2.0.5 classifies it as `application/javascript`.
        // FileResponse delegates its default type to mimetypes.guess_type.
        let guessed_type = match source.extension().and_then(|extension| extension.to_str()) {
            // The MIME database loaded by CPython on Linux classifies `.exe`
            // as `application/x-msdos-program`; other supported hosts use the
            // built-in `application/x-msdownload` mapping from mime_guess.
            Some(extension) if extension.eq_ignore_ascii_case("mjs") => Some("text/javascript"),
            Some(extension) if extension.eq_ignore_ascii_case("exe") => {
                #[cfg(target_os = "linux")]
                {
                    Some("application/x-msdos-program")
                }
                #[cfg(not(target_os = "linux"))]
                {
                    Some("application/x-msdownload")
                }
            }
            _ => mime_guess::from_path(&source).first_raw(),
        };
        let media_type = options
            .media_type
            .as_deref()
            .or(guessed_type)
            .unwrap_or("application/octet-stream");

        if !contains_header(&raw_headers, b"content-type") {
            let content_type = with_charset(media_type);
            push_header(&mut raw_headers, "content-type", &content_type)?;
        }
        set_default_header(&mut raw_headers, "accept-ranges", "bytes")?;

        if let Some(filename) = options.filename.as_deref() {
            let quoted = quote_filename(filename);
            let disposition = if quoted == filename {
                format!(
                    "{}; filename=\"{filename}\"",
                    options.content_disposition_type
                )
            } else {
                format!(
                    "{}; filename*=utf-8''{quoted}",
                    options.content_disposition_type
                )
            };
            set_default_header(&mut raw_headers, "content-disposition", &disposition)?;
        }

        if let Some(metadata) = options.stat_override.as_ref() {
            set_stat_headers(&mut raw_headers, metadata)?;
        }

        Ok(Self {
            path,
            display_path: display_path.into(),
            status_code,
            media_type: media_type.to_owned(),
            headers: raw_headers,
            stat_override: options.stat_override,
            stat_headers_prepared: false,
            // Starlette reads the configured size verbatim. In particular,
            // zero produces repeated empty body events until the ASGI send
            // callback ends the call.
            chunk_size: options.chunk_size,
            max_ranges: options.max_ranges,
        })
    }

    /// Appends a response cookie using Starlette's cookie formatting.
    ///
    /// # Errors
    ///
    /// Returns a response error if the cookie cannot be represented in the
    /// Latin-1 response-header encoding.
    pub fn set_cookie(&mut self, key: &str, value: &str) -> Result<(), ResponseError> {
        self.set_cookie_with_options(key, value, &CookieOptions::default())
    }

    /// Appends a response cookie with Starlette's optional attributes.
    pub fn set_cookie_with_options(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), ResponseError> {
        let mut response =
            Response::from_content(200, Vec::new(), None, std::iter::empty::<(&str, &str)>())?;
        response.set_cookie_with_options(key, value, options)?;
        if let Some((_, cookie)) = response
            .headers()
            .iter()
            .find(|(name, _)| name.as_slice() == b"set-cookie")
        {
            self.headers.push((b"set-cookie".to_vec(), cookie.clone()));
        }
        Ok(())
    }

    /// Deletes a response cookie using zero age and the supplied HTTP date.
    pub fn delete_cookie_with_options(
        &mut self,
        key: &str,
        expires: &str,
        options: &CookieOptions,
    ) -> Result<(), ResponseError> {
        let mut response =
            Response::from_content(200, Vec::new(), None, std::iter::empty::<(&str, &str)>())?;
        response.delete_cookie_with_options(key, expires, options)?;
        if let Some((_, cookie)) = response
            .headers()
            .iter()
            .find(|(name, _)| name.as_slice() == b"set-cookie")
        {
            self.headers.push((b"set-cookie".to_vec(), cookie.clone()));
        }
        Ok(())
    }

    /// Applies the values exposed by Starlette's mutable `FileResponse`
    /// streaming and range attributes to later response calls.
    pub fn set_streaming_options(&mut self, chunk_size: usize, max_ranges: usize) {
        self.chunk_size = chunk_size;
        self.max_ranges = max_ranges;
    }

    /// Creates a call-local copy using Starlette's current mutable file fields.
    ///
    /// Existing headers and the constructor-selected media type are retained.
    /// Starlette reads path, status code, and stat result at call time without
    /// rebuilding those constructor values.
    #[must_use]
    pub fn with_call_time_fields(
        &self,
        path: PathBuf,
        display_path: impl Into<String>,
        status_code: u16,
        stat_override: Option<FileMetadata>,
    ) -> Self {
        let mut response = self.clone();
        response.path = path;
        response.display_path = display_path.into();
        response.status_code = status_code;
        response.stat_override = stat_override;
        response
    }

    /// Replaces the call-local path after a Python path-like value has been
    /// converted at the source-compatible filesystem boundary.
    #[must_use]
    pub fn with_call_path(&self, path: PathBuf) -> Self {
        let mut response = self.clone();
        response.path = path;
        response
    }

    /// Keeps the header outcome selected by a compatibility callback.
    ///
    /// A caller that has already invoked its public stat-header hook can retain
    /// that hook's replacements or omissions. Metadata is still required for
    /// file/range planning, but preparation does not insert header defaults.
    #[must_use]
    pub fn with_prepared_stat_headers(mut self) -> Self {
        self.stat_headers_prepared = true;
        self
    }

    /// Returns the explicit or extension-guessed content type.
    #[must_use]
    pub fn media_type(&self) -> &str {
        &self.media_type
    }

    /// Returns the normalized response headers before request-specific ranges.
    #[must_use]
    pub fn headers(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.headers
    }

    /// Replaces the response headers with the supplied raw byte pairs.
    ///
    /// This preserves the caller's pair order, duplicate names, and bytes.
    /// It is intended for compatibility boundaries that expose a mutable raw
    /// header list.
    pub fn replace_headers_raw(&mut self, headers: Vec<(Vec<u8>, Vec<u8>)>) {
        self.headers = headers;
    }

    /// Returns the first response-header value for a case-insensitive name.
    pub fn get_header(&self, name: &str) -> Result<Option<String>, ResponseError> {
        get_response_header(&self.headers, name)
    }

    /// Replaces a response header while retaining its first position and removing duplicates.
    pub fn set_header(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        set_response_header(&mut self.headers, name, value)
    }

    /// Removes all response headers with the supplied case-insensitive name.
    pub fn delete_header(&mut self, name: &str) -> Result<(), ResponseError> {
        delete_response_header(&mut self.headers, name)
    }

    /// Appends a response header without removing existing fields of the same name.
    pub fn append_header(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        append_response_header(&mut self.headers, name, value)
    }

    /// Returns every value for a response header in wire order.
    pub fn get_header_values(&self, name: &str) -> Result<Vec<String>, ResponseError> {
        get_response_header_values(&self.headers, name)
    }

    /// Prepares one request-specific response call.
    ///
    /// The range parser, conditional request evaluation, status/header
    /// selection, and stream plan all execute in Rust. `request_headers` are
    /// the original ASGI byte pairs.
    ///
    /// # Errors
    ///
    /// Returns a file or metadata error before emitting response headers.
    pub fn call_state(
        &self,
        scope_type: &str,
        method: &str,
        request_headers: &[(Vec<u8>, Vec<u8>)],
        pathsend_extension: bool,
        has_background: bool,
    ) -> Result<FileResponseCall, FileResponseError> {
        let raw_headers = self.headers.clone();
        self.call_state_with_headers(
            FileResponseHeaderViews {
                view: raw_headers.clone(),
                raw: raw_headers,
                view_is_raw: true,
            },
            scope_type,
            method,
            request_headers,
            pathsend_extension,
            has_background,
        )
    }

    /// Prepares a request-specific call from a cached header view and the
    /// response's current raw header list.
    ///
    /// Starlette may retain a cached `MutableHeaders` view after
    /// `raw_headers` has been rebound. In that state metadata defaults mutate
    /// the cached view, while response messages read the current raw list.
    /// `view_is_raw` identifies whether both inputs alias the same list.
    ///
    /// # Errors
    ///
    /// Returns a file or metadata error before emitting response headers.
    pub fn call_state_with_headers(
        &self,
        header_views: FileResponseHeaderViews,
        scope_type: &str,
        method: &str,
        request_headers: &[(Vec<u8>, Vec<u8>)],
        pathsend_extension: bool,
        has_background: bool,
    ) -> Result<FileResponseCall, FileResponseError> {
        self.call_state_with_header_views_and_http_match(
            header_views,
            (scope_type == "http", scope_type == "http"),
            method,
            request_headers,
            pathsend_extension,
            has_background,
        )
    }

    /// Prepares a request-specific call using scope classifications evaluated
    /// by a Python compatibility boundary.
    ///
    /// Starlette compares the original `scope["type"]` object with the HTTP
    /// and WebSocket literals. This entry point lets the Python facade preserve
    /// the HTTP rich-equality results for string subclasses while keeping file
    /// planning in Rust. The two values correspond to Starlette's separate
    /// HEAD and pathsend checks. WebSocket message names are handled by the
    /// facade.
    /// Rust-native callers should use [`Self::call_state_with_headers`].
    ///
    /// # Errors
    ///
    /// Returns a file or metadata error before emitting response headers.
    #[doc(hidden)]
    pub fn call_state_with_header_views_and_http_match(
        &self,
        header_views: FileResponseHeaderViews,
        http_scope_matches: (bool, bool),
        method: &str,
        request_headers: &[(Vec<u8>, Vec<u8>)],
        pathsend_extension: bool,
        has_background: bool,
    ) -> Result<FileResponseCall, FileResponseError> {
        let (scope_is_http_for_head, scope_is_http_for_pathsend) = http_scope_matches;
        let FileResponseHeaderViews {
            view: mut view_headers,
            raw: raw_headers,
            view_is_raw,
        } = header_views;
        let metadata = match self.stat_override.as_ref() {
            Some(metadata) => metadata.clone(),
            None => {
                let metadata = fs::metadata(&self.path).map_err(|error| {
                    if error.kind() == io::ErrorKind::NotFound {
                        FileResponseError::MissingFile(self.display_path.clone())
                    } else {
                        FileResponseError::StatIo(error)
                    }
                })?;
                if !metadata.is_file() {
                    return Err(FileResponseError::NotAFile(self.display_path.clone()));
                }
                FileMetadata::from_metadata(&metadata)?
            }
        };

        if !self.stat_headers_prepared {
            set_stat_headers(&mut view_headers, &metadata)?;
        }
        let base_headers = view_headers.clone();
        let mut headers = if view_is_raw {
            view_headers.clone()
        } else {
            raw_headers
        };
        let range = header_value(request_headers, b"range");
        let if_range = header_value(request_headers, b"if-range");
        let use_range = range.as_ref().is_some_and(|_| {
            if_range.as_ref().is_none_or(|value| {
                value == &header_text(&view_headers, b"last-modified").unwrap_or_default()
                    || value == &header_text(&view_headers, b"etag").unwrap_or_default()
            })
        });

        let send_header_only = scope_is_http_for_head && method.eq_ignore_ascii_case("HEAD");
        let mut send_pathsend =
            scope_is_http_for_pathsend && pathsend_extension && !send_header_only;
        let mut status_code = self.status_code;
        let mut mode = FileResponseMode::Simple;
        let background = has_background;
        if use_range {
            let range_text = range.as_deref().unwrap_or_default();
            match parse_range_header(range_text, metadata.size, self.max_ranges) {
                Ok(ranges) if ranges.is_empty() => {}
                Ok(ranges) if ranges.len() == 1 => {
                    send_pathsend = false;
                    let (start, end) = ranges[0];
                    status_code = 206;
                    let last_byte = end
                        .checked_sub(1)
                        .ok_or_else(file_response_arithmetic_overflow)?;
                    let content_length = end
                        .checked_sub(start)
                        .ok_or_else(file_response_arithmetic_overflow)?;
                    set_header(
                        &mut headers,
                        "content-range",
                        &format!("bytes {start}-{last_byte}/{size}", size = metadata.size),
                    )?;
                    set_header(&mut headers, "content-length", &content_length.to_string())?;
                    mode = FileResponseMode::SingleRange { start, end };
                }
                Ok(ranges) => {
                    send_pathsend = false;
                    let boundary = random_boundary()?;
                    let content_type = header_bytes(&view_headers, b"content-type")
                        .ok_or(FileResponseError::MissingContentType)?;
                    let content_length =
                        multipart_content_length(&ranges, &boundary, metadata.size, &content_type)?;
                    status_code = 206;
                    set_header(
                        &mut headers,
                        "content-type",
                        &format!("multipart/byteranges; boundary={boundary}"),
                    )?;
                    set_header(&mut headers, "content-length", &content_length.to_string())?;
                    mode = FileResponseMode::MultipleRanges {
                        ranges,
                        boundary,
                        content_type,
                    };
                }
                Err(RangeParseError::Malformed(message)) => {
                    status_code = 400;
                    headers = error_headers(&[], Some("text/plain"), message.as_bytes())?;
                    return Ok(FileResponseCall::prepared_error(
                        status_code,
                        headers,
                        message.as_bytes().to_vec(),
                        base_headers,
                    ));
                }
                Err(RangeParseError::NotSatisfiable) => {
                    status_code = 416;
                    headers = error_headers(
                        &[(
                            "content-range".to_owned(),
                            format!("bytes */{}", metadata.size),
                        )],
                        Some("text/plain"),
                        &[],
                    )?;
                    return Ok(FileResponseCall::prepared_error(
                        status_code,
                        headers,
                        Vec::new(),
                        base_headers,
                    ));
                }
            }
        }

        Ok(FileResponseCall {
            phase: FileResponsePhase::Start,
            pending: None,
            status_code,
            headers,
            base_headers,
            mode,
            path: self.path.clone(),
            display_path: self.display_path.clone(),
            chunk_size: self.chunk_size,
            send_header_only,
            send_pathsend,
            file: None,
            background,
            file_size: metadata.size,
            error_body: None,
            defer_open_path_conversion: false,
        })
    }
}

impl FileResponseCall {
    /// Whether the simple successful response sends its live base values.
    ///
    /// Range and error responses construct separate header lists. A Python
    /// compatibility boundary can preserve raw-list identity for the simple
    /// branch while retaining the Rust-selected list for those other branches.
    #[must_use]
    pub fn sends_raw_headers(&self) -> bool {
        matches!(self.mode, FileResponseMode::Simple) && self.error_body.is_none()
    }

    /// Defers conversion of the path used to open the file until the body
    /// branch is ready to open it.
    ///
    /// Python's `FileResponse` retains a path-like object and passes it to
    /// `os.stat` and `anyio.open_file` separately. Its `__fspath__` method can
    /// therefore return a different path for metadata and for opening. A
    /// compatibility bridge enables this mode after metadata planning, then
    /// supplies the path immediately before the first open operation.
    pub fn defer_open_path_conversion(&mut self) {
        self.defer_open_path_conversion = true;
    }

    /// Whether the next body-producing step needs a separately converted
    /// path before it can open the file.
    #[must_use]
    pub fn needs_open_path_conversion(&self) -> bool {
        if !self.defer_open_path_conversion
            || self.file.is_some()
            || self.error_body.is_some()
            || self.send_header_only
            || self.send_pathsend
        {
            return false;
        }

        match &self.phase {
            FileResponsePhase::SimpleBody
            | FileResponsePhase::SingleRangeBody { .. }
            | FileResponsePhase::MultipartBody { .. } => true,
            FileResponsePhase::SelectBody => {
                matches!(
                    self.mode,
                    FileResponseMode::Simple | FileResponseMode::SingleRange { .. }
                )
            }
            _ => false,
        }
    }

    /// Supplies the path returned by the compatibility boundary immediately
    /// before the first body-file open.
    pub fn set_open_path(&mut self, path: PathBuf) {
        self.path = path;
        self.defer_open_path_conversion = false;
    }

    fn prepared_error(
        status_code: u16,
        headers: Vec<(Vec<u8>, Vec<u8>)>,
        body: Vec<u8>,
        base_headers: Vec<(Vec<u8>, Vec<u8>)>,
    ) -> Self {
        Self {
            phase: FileResponsePhase::Start,
            pending: None,
            status_code,
            headers,
            base_headers,
            mode: FileResponseMode::Simple,
            path: PathBuf::new(),
            display_path: String::new(),
            chunk_size: DEFAULT_CHUNK_SIZE,
            send_header_only: body.is_empty(),
            send_pathsend: false,
            file: None,
            background: false,
            file_size: 0,
            error_body: Some(body),
            defer_open_path_conversion: false,
        }
    }

    /// Returns the stat-enriched base header view before any request-specific
    /// range or error response headers are applied.
    #[must_use]
    pub fn base_headers(&self) -> &[(Vec<u8>, Vec<u8>)] {
        &self.base_headers
    }

    /// Closes the currently open file, if any.
    ///
    /// The file is closed by dropping it on the calling thread. Runtime
    /// adapters that must keep close off an event loop should call this method
    /// from their blocking-I/O worker.
    pub fn close_file(&mut self) {
        drop(self.file.take());
    }

    /// Produces the next send/background/completion action.
    ///
    /// File reads happen one chunk at a time in Rust after the start event has
    /// been sent, so the Python bridge does not assemble the response body.
    /// An open file is closed before a terminal action, background action, or
    /// I/O error is returned.
    pub fn step(&mut self) -> Result<FileResponseCallStep, io::Error> {
        let result = self.step_inner();
        if matches!(
            &result,
            Err(_)
                | Ok(FileResponseCallStep::RunBackground)
                | Ok(FileResponseCallStep::Complete)
                | Ok(FileResponseCallStep::Failed)
        ) {
            self.close_file();
        }
        result
    }

    fn step_inner(&mut self) -> Result<FileResponseCallStep, io::Error> {
        if self.pending.is_some() {
            return Ok(FileResponseCallStep::Failed);
        }
        loop {
            match self.phase.clone() {
                FileResponsePhase::Start => {
                    self.pending = Some(PendingOperation::Send(FileResponsePhase::SelectBody));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Start {
                        status_code: self.status_code,
                        headers: self.headers.clone(),
                    }));
                }
                FileResponsePhase::SelectBody => {
                    if let Some(body) = self.error_body.take() {
                        self.pending = Some(PendingOperation::Send(self.finish_phase()));
                        return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                            body,
                            more_body: None,
                        }));
                    }
                    if self.send_header_only {
                        self.pending = Some(PendingOperation::Send(self.finish_phase()));
                        return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                            body: Vec::new(),
                            more_body: Some(false),
                        }));
                    }
                    if self.send_pathsend {
                        self.pending = Some(PendingOperation::Send(self.finish_phase()));
                        return Ok(FileResponseCallStep::Send(FileResponseEvent::Pathsend {
                            path: self.display_path.clone(),
                        }));
                    }
                    self.phase = match &self.mode {
                        FileResponseMode::Simple => FileResponsePhase::SimpleBody,
                        FileResponseMode::SingleRange { start, end } => {
                            FileResponsePhase::SingleRangeBody {
                                cursor: *start,
                                end: *end,
                            }
                        }
                        FileResponseMode::MultipleRanges { .. } => {
                            FileResponsePhase::MultipartHeader { index: 0 }
                        }
                    };
                }
                FileResponsePhase::SimpleBody => {
                    self.open_file()?;
                    let mut body = vec![0; self.chunk_size];
                    let size = self
                        .file
                        .as_mut()
                        .ok_or_else(unexpected_file_state)?
                        .read(&mut body)?;
                    body.truncate(size);
                    let more_body = size == self.chunk_size;
                    let after = if more_body {
                        FileResponsePhase::SimpleBody
                    } else {
                        self.finish_phase()
                    };
                    self.pending = Some(PendingOperation::Send(after));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body,
                        more_body: Some(more_body),
                    }));
                }
                FileResponsePhase::SingleRangeBody { cursor, end } => {
                    self.open_file()?;
                    let file = self.file.as_mut().ok_or_else(unexpected_file_state)?;
                    file.seek(SeekFrom::Start(cursor))?;
                    let remaining = end
                        .checked_sub(cursor)
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    let chunk_size = u64::try_from(self.chunk_size)
                        .map_err(|_| file_response_arithmetic_io_error())?;
                    let limit = usize::try_from(remaining.min(chunk_size))
                        .map_err(|_| file_response_arithmetic_io_error())?;
                    let mut body = vec![0; limit];
                    let size = file.read(&mut body)?;
                    body.truncate(size);
                    let read_size =
                        u64::try_from(size).map_err(|_| file_response_arithmetic_io_error())?;
                    let next_cursor = cursor
                        .checked_add(read_size)
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    let more_body = size == self.chunk_size && next_cursor < end;
                    let after = if more_body {
                        FileResponsePhase::SingleRangeBody {
                            cursor: next_cursor,
                            end,
                        }
                    } else {
                        self.finish_phase()
                    };
                    self.pending = Some(PendingOperation::Send(after));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body,
                        more_body: Some(more_body),
                    }));
                }
                FileResponsePhase::MultipartHeader { index } => {
                    let FileResponseMode::MultipleRanges {
                        ranges,
                        boundary,
                        content_type,
                    } = &self.mode
                    else {
                        self.phase = FileResponsePhase::Failed;
                        return Ok(FileResponseCallStep::Failed);
                    };
                    let (start, end) = ranges
                        .get(index)
                        .copied()
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    let body =
                        multipart_header(boundary, content_type, start, end, self.file_size)?;
                    self.pending = Some(PendingOperation::Send(FileResponsePhase::MultipartBody {
                        index,
                        cursor: start,
                    }));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body,
                        more_body: Some(true),
                    }));
                }
                FileResponsePhase::MultipartBody { index, cursor } => {
                    let FileResponseMode::MultipleRanges { ranges, .. } = &self.mode else {
                        self.phase = FileResponsePhase::Failed;
                        return Ok(FileResponseCallStep::Failed);
                    };
                    let (_, end) = ranges
                        .get(index)
                        .copied()
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    self.open_file()?;
                    let file = self.file.as_mut().ok_or_else(unexpected_file_state)?;
                    file.seek(SeekFrom::Start(cursor))?;
                    let remaining = end
                        .checked_sub(cursor)
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    let chunk_size = u64::try_from(self.chunk_size)
                        .map_err(|_| file_response_arithmetic_io_error())?;
                    let limit = usize::try_from(remaining.min(chunk_size))
                        .map_err(|_| file_response_arithmetic_io_error())?;
                    let mut body = vec![0; limit];
                    let size = file.read(&mut body)?;
                    body.truncate(size);
                    let read_size =
                        u64::try_from(size).map_err(|_| file_response_arithmetic_io_error())?;
                    let next_cursor = cursor
                        .checked_add(read_size)
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    // Starlette's `while start < end` does not advance on EOF
                    // when caller-supplied stat data is larger than the file.
                    // Preserve its repeated empty body events until the caller
                    // terminates the ASGI send sequence.
                    let after = if next_cursor >= end {
                        FileResponsePhase::MultipartSeparator { index }
                    } else {
                        FileResponsePhase::MultipartBody {
                            index,
                            cursor: next_cursor,
                        }
                    };
                    self.pending = Some(PendingOperation::Send(after));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body,
                        more_body: Some(true),
                    }));
                }
                FileResponsePhase::MultipartSeparator { index } => {
                    let range_count = match &self.mode {
                        FileResponseMode::MultipleRanges { ranges, .. } => ranges.len(),
                        _ => 0,
                    };
                    let next_index = index
                        .checked_add(1)
                        .ok_or_else(file_response_arithmetic_io_error)?;
                    let after = if next_index < range_count {
                        FileResponsePhase::MultipartHeader { index: next_index }
                    } else {
                        FileResponsePhase::MultipartFinal
                    };
                    self.pending = Some(PendingOperation::Send(after));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body: b"\r\n".to_vec(),
                        more_body: Some(true),
                    }));
                }
                FileResponsePhase::MultipartFinal => {
                    let boundary = match &self.mode {
                        FileResponseMode::MultipleRanges { boundary, .. } => boundary,
                        _ => {
                            self.phase = FileResponsePhase::Failed;
                            return Ok(FileResponseCallStep::Failed);
                        }
                    };
                    let after = self.finish_phase();
                    self.pending = Some(PendingOperation::Send(after));
                    return Ok(FileResponseCallStep::Send(FileResponseEvent::Body {
                        body: format!("--{boundary}--").into_bytes(),
                        more_body: Some(false),
                    }));
                }
                FileResponsePhase::Background => {
                    if self.background {
                        self.pending = Some(PendingOperation::Background);
                        return Ok(FileResponseCallStep::RunBackground);
                    }
                    self.phase = FileResponsePhase::Complete;
                }
                FileResponsePhase::Complete => return Ok(FileResponseCallStep::Complete),
                FileResponsePhase::Failed => return Ok(FileResponseCallStep::Failed),
            }
        }
    }

    /// Advances after the operation returned by [`Self::step`].
    pub fn advance<E>(
        &mut self,
        input: FileResponseCallInput<E>,
    ) -> Result<(), FileResponseCallError<E>> {
        match (self.pending.take(), input) {
            (Some(PendingOperation::Send(after)), FileResponseCallInput::Send(Ok(()))) => {
                self.phase = after;
                Ok(())
            }
            (
                Some(PendingOperation::Background),
                FileResponseCallInput::BackgroundFinished(Ok(())),
            ) => {
                self.phase = FileResponsePhase::Complete;
                Ok(())
            }
            (Some(PendingOperation::Send(_)), FileResponseCallInput::Send(Err(error)))
            | (
                Some(PendingOperation::Background),
                FileResponseCallInput::BackgroundFinished(Err(error)),
            ) => {
                self.phase = FileResponsePhase::Failed;
                Err(FileResponseCallError::Operation(error))
            }
            _ => {
                self.phase = FileResponsePhase::Failed;
                Err(FileResponseCallError::UnexpectedInput)
            }
        }
    }

    fn open_file(&mut self) -> io::Result<()> {
        if self.file.is_none() {
            self.file = Some(File::open(&self.path)?);
        }
        Ok(())
    }

    fn finish_phase(&self) -> FileResponsePhase {
        if self.background {
            FileResponsePhase::Background
        } else {
            FileResponsePhase::Complete
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum RangeParseError {
    Malformed(&'static str),
    NotSatisfiable,
}

fn parse_range_header(
    header: &str,
    file_size: u64,
    max_ranges: usize,
) -> Result<Vec<(u64, u64)>, RangeParseError> {
    let (units, requested) = header
        .split_once('=')
        .ok_or(RangeParseError::Malformed("Malformed range header."))?;
    if !python_strip(units).eq_ignore_ascii_case("bytes") {
        return Err(RangeParseError::Malformed("Only support bytes range"));
    }
    if requested.bytes().filter(|byte| *byte == b',').count() >= max_ranges {
        return Ok(Vec::new());
    }

    let mut ranges = Vec::new();
    for part in requested.split(',') {
        let part = python_strip(part);
        if part.is_empty() || part == "-" {
            continue;
        }
        let Some((start_text, end_text)) = part.split_once('-') else {
            continue;
        };
        let start_text = python_strip(start_text);
        let end_text = python_strip(end_text);
        let start = if start_text.is_empty() {
            let Some(suffix) = parse_decimal(end_text) else {
                continue;
            };
            if suffix.negative {
                // Starlette's Python integer arithmetic is unbounded. Saturate
                // only this internal range calculation; values beyond u64
                // still take the same out-of-file branch below.
                file_size.saturating_add(suffix.value)
            } else {
                file_size.saturating_sub(suffix.value)
            }
        } else {
            let Some(start) = parse_decimal(start_text) else {
                continue;
            };
            if start.negative {
                return Err(RangeParseError::NotSatisfiable);
            }
            start.value
        };
        let end = if !start_text.is_empty() && !end_text.is_empty() {
            let Some(raw_end) = parse_decimal(end_text) else {
                continue;
            };
            if raw_end.negative {
                0
            } else if raw_end.value < file_size {
                raw_end
                    .value
                    .checked_add(1)
                    .ok_or(RangeParseError::NotSatisfiable)?
            } else {
                file_size
            }
        } else {
            file_size
        };
        ranges.push((start, end));
    }

    if ranges.is_empty() {
        return Err(RangeParseError::Malformed(
            "Range header: range must be requested",
        ));
    }
    if ranges.iter().any(|(start, _)| *start >= file_size) {
        return Err(RangeParseError::NotSatisfiable);
    }
    if ranges.iter().any(|(start, end)| start >= end) {
        return Err(RangeParseError::Malformed(
            "Range header: start must be less than end",
        ));
    }
    if ranges.len() == 1 {
        return Ok(ranges);
    }

    ranges.sort_unstable();
    let mut merged: Vec<(u64, u64)> = Vec::with_capacity(ranges.len());
    for (start, end) in ranges {
        if let Some((_, last_end)) = merged.last_mut() {
            if start <= *last_end {
                *last_end = (*last_end).max(end);
                continue;
            }
        }
        merged.push((start, end));
    }
    Ok(merged)
}

fn python_strip(value: &str) -> &str {
    // CPython's str.strip includes these separators; Rust's Unicode whitespace predicate does not.
    value.trim_matches(|character: char| {
        character.is_whitespace() || matches!(character, '\u{001c}'..='\u{001f}')
    })
}

#[derive(Clone, Copy)]
struct ParsedDecimal {
    value: u64,
    negative: bool,
}

fn parse_decimal(value: &str) -> Option<ParsedDecimal> {
    let (negative, digits) = if let Some(digits) = value.strip_prefix('+') {
        (false, digits)
    } else if let Some(digits) = value.strip_prefix('-') {
        (true, digits)
    } else {
        (false, value)
    };
    let bytes = digits.as_bytes();
    if bytes.is_empty()
        || bytes.iter().enumerate().any(|(index, byte)| {
            if byte.is_ascii_digit() {
                return false;
            }
            if *byte != b'_' {
                return true;
            }
            let previous_is_digit = index
                .checked_sub(1)
                .and_then(|previous| bytes.get(previous))
                .is_some_and(u8::is_ascii_digit);
            let next_is_digit = index
                .checked_add(1)
                .and_then(|next| bytes.get(next))
                .is_some_and(u8::is_ascii_digit);
            !previous_is_digit || !next_is_digit
        })
    {
        return None;
    }
    // Starlette 1.6.0 parses range bounds with Python `int()` and ignores
    // ValueError. Match CPython's decimal conversion limit for the full digit
    // sequence, including leading zeroes; underscores are not digits.
    let digit_count = bytes.iter().copied().filter(|byte| *byte != b'_').count();
    if digit_count > PYTHON_INT_MAX_STR_DIGITS {
        return None;
    }
    // Python parses arbitrary-precision integers. Saturation retains the only
    // downstream distinction this u64 representation needs: a bound beyond
    // the file size remains outside the file and is clamped by range planning.
    let value =
        bytes
            .iter()
            .copied()
            .filter(|byte| *byte != b'_')
            .try_fold(0_u64, |number, byte| {
                Some(
                    number
                        .saturating_mul(10)
                        .saturating_add(u64::from(byte.checked_sub(b'0')?)),
                )
            });
    let value = value?;
    Some(ParsedDecimal {
        value,
        negative: negative && value != 0,
    })
}

fn normalize_headers(headers: &[(String, String)]) -> Result<RawHeaders, FileResponseError> {
    headers
        .iter()
        .map(|(name, value)| Ok((latin1(&name.to_ascii_lowercase())?, latin1(value)?)))
        .collect()
}

fn error_headers(
    headers: &[(String, String)],
    media_type: Option<&str>,
    body: &[u8],
) -> Result<RawHeaders, FileResponseError> {
    let mut output = normalize_headers(headers)?;
    if !contains_header(&output, b"content-length") {
        set_header(&mut output, "content-length", &body.len().to_string())?;
    }
    if !contains_header(&output, b"content-type") {
        if let Some(media_type) = media_type {
            set_header(&mut output, "content-type", &with_charset(media_type))?;
        }
    }
    Ok(output)
}

fn set_stat_headers(
    headers: &mut Vec<(Vec<u8>, Vec<u8>)>,
    metadata: &FileMetadata,
) -> Result<(), FileResponseError> {
    set_default_header(headers, "content-length", &metadata.size.to_string())?;
    set_default_header(
        headers,
        "last-modified",
        &format_http_date(metadata.modified_unix_seconds())?,
    )?;
    let input = format!("{}-{}", metadata.modified_text, metadata.size);
    set_default_header(headers, "etag", &FileResponse::stat_etag(input.as_bytes()))?;
    Ok(())
}

fn format_http_date(timestamp_seconds: f64) -> Result<String, FileResponseError> {
    let mut whole_seconds = timestamp_seconds.trunc();
    let fractional_microseconds = round_half_even(timestamp_seconds.fract() * 1_000_000.0);
    if fractional_microseconds >= 1_000_000.0 {
        whole_seconds += 1.0;
    } else if fractional_microseconds < 0.0 {
        whole_seconds -= 1.0;
    }
    if !whole_seconds.is_finite()
        || whole_seconds < i128::MIN as f64
        || whole_seconds >= -(i128::MIN as f64)
    {
        return Err(FileResponseError::InvalidTimestamp);
    }
    format_unix_http_date(truncated_seconds_to_i128(whole_seconds))
}

// LINT EXCEPTION: the caller truncates and checks finite i128 bounds before this conversion.
#[allow(clippy::cast_possible_truncation)]
fn truncated_seconds_to_i128(value: f64) -> i128 {
    value as i128
}

fn round_half_even(value: f64) -> f64 {
    let lower = value.floor();
    let fraction = value - lower;
    if fraction < 0.5 {
        lower
    } else if fraction > 0.5 || lower.rem_euclid(2.0) != 0.0 {
        lower + 1.0
    } else {
        lower
    }
}

fn format_unix_http_date(timestamp_seconds: i128) -> Result<String, FileResponseError> {
    const SECONDS_PER_DAY: i128 = 86_400;

    let days = timestamp_seconds.div_euclid(SECONDS_PER_DAY);
    let seconds_in_day = timestamp_seconds.rem_euclid(SECONDS_PER_DAY);
    let hour = seconds_in_day.div_euclid(3_600);
    let minute = seconds_in_day.rem_euclid(3_600).div_euclid(60);
    let second = seconds_in_day.rem_euclid(60);

    let days_from_civil = checked_i128_add(days, 719_468)?;
    let era_dividend = if days_from_civil >= 0 {
        days_from_civil
    } else {
        checked_i128_sub(days_from_civil, 146_096)?
    };
    let era = checked_i128_div(era_dividend, 146_097)?;
    let day_of_era = checked_i128_sub(days_from_civil, checked_i128_mul(era, 146_097)?)?;
    let leap_adjusted_days = checked_i128_sub(day_of_era, checked_i128_div(day_of_era, 1_460)?)?;
    let century_adjusted_days =
        checked_i128_add(leap_adjusted_days, checked_i128_div(day_of_era, 36_524)?)?;
    let year_of_era_days = checked_i128_sub(
        century_adjusted_days,
        checked_i128_div(day_of_era, 146_096)?,
    )?;
    let year_of_era = checked_i128_div(year_of_era_days, 365)?;
    let mut year = checked_i128_add(year_of_era, checked_i128_mul(era, 400)?)?;
    let prior_days = checked_i128_sub(
        checked_i128_add(
            checked_i128_mul(365, year_of_era)?,
            checked_i128_div(year_of_era, 4)?,
        )?,
        checked_i128_div(year_of_era, 100)?,
    )?;
    let day_of_year = checked_i128_sub(day_of_era, prior_days)?;
    let month_prime =
        checked_i128_div(checked_i128_add(checked_i128_mul(5, day_of_year)?, 2)?, 153)?;
    let prior_days =
        checked_i128_div(checked_i128_add(checked_i128_mul(153, month_prime)?, 2)?, 5)?;
    let day = checked_i128_add(checked_i128_sub(day_of_era, prior_days)?, 1)?;
    let month_adjustment = if month_prime < 10 { 3 } else { -9 };
    let month = checked_i128_add(month_prime, month_adjustment)?;
    if month <= 2 {
        year = checked_i128_add(year, 1)?;
    }
    if !(1..=9_999).contains(&year) {
        return Err(FileResponseError::TimestampYearOutOfRange(year));
    }

    let weekday = match checked_i128_add(days, 4)?.rem_euclid(7) {
        0 => "Sun",
        1 => "Mon",
        2 => "Tue",
        3 => "Wed",
        4 => "Thu",
        5 => "Fri",
        _ => "Sat",
    };
    let month_name = match month {
        1 => "Jan",
        2 => "Feb",
        3 => "Mar",
        4 => "Apr",
        5 => "May",
        6 => "Jun",
        7 => "Jul",
        8 => "Aug",
        9 => "Sep",
        10 => "Oct",
        11 => "Nov",
        _ => "Dec",
    };

    Ok(format!(
        "{weekday}, {day:02} {month_name} {year:04} {hour:02}:{minute:02}:{second:02} GMT"
    ))
}

fn checked_i128_add(left: i128, right: i128) -> Result<i128, FileResponseError> {
    left.checked_add(right)
        .ok_or(FileResponseError::InvalidTimestamp)
}

fn checked_i128_sub(left: i128, right: i128) -> Result<i128, FileResponseError> {
    left.checked_sub(right)
        .ok_or(FileResponseError::InvalidTimestamp)
}

fn checked_i128_mul(left: i128, right: i128) -> Result<i128, FileResponseError> {
    left.checked_mul(right)
        .ok_or(FileResponseError::InvalidTimestamp)
}

fn checked_i128_div(left: i128, right: i128) -> Result<i128, FileResponseError> {
    left.checked_div(right)
        .ok_or(FileResponseError::InvalidTimestamp)
}

fn with_charset(media_type: &str) -> String {
    if media_type.starts_with("text/") && !media_type.to_ascii_lowercase().contains("charset=") {
        format!("{media_type}; charset=utf-8")
    } else {
        media_type.to_owned()
    }
}

fn contains_header(headers: &[(Vec<u8>, Vec<u8>)], name: &[u8]) -> bool {
    headers.iter().any(|(header, _)| header == name)
}

fn set_default_header(
    headers: &mut Vec<(Vec<u8>, Vec<u8>)>,
    name: &str,
    value: &str,
) -> Result<(), FileResponseError> {
    if !contains_header(headers, name.as_bytes()) {
        push_header(headers, name, value)?;
    }
    Ok(())
}

fn set_header(
    headers: &mut Vec<(Vec<u8>, Vec<u8>)>,
    name: &str,
    value: &str,
) -> Result<(), FileResponseError> {
    let key = name.as_bytes().to_vec();
    let value = latin1(value)?;
    let mut found = false;
    headers.retain_mut(|(header, existing)| {
        if *header == key {
            if found {
                false
            } else {
                *existing = value.clone();
                found = true;
                true
            }
        } else {
            true
        }
    });
    if !found {
        headers.push((key, value));
    }
    Ok(())
}

fn push_header(
    headers: &mut Vec<(Vec<u8>, Vec<u8>)>,
    name: &str,
    value: &str,
) -> Result<(), FileResponseError> {
    headers.push((name.as_bytes().to_vec(), latin1(value)?));
    Ok(())
}

fn latin1(value: &str) -> Result<Vec<u8>, FileResponseError> {
    value
        .chars()
        .enumerate()
        .map(|(index, character)| {
            u8::try_from(u32::from(character)).map_err(|_| {
                FileResponseError::HeaderDataIsNotLatin1 {
                    value: value.to_owned(),
                    index,
                }
            })
        })
        .collect()
}

fn header_value(headers: &[(Vec<u8>, Vec<u8>)], name: &[u8]) -> Option<String> {
    headers
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .map(|(_, value)| latin1_text(value))
}

fn header_text(headers: &[(Vec<u8>, Vec<u8>)], name: &[u8]) -> Option<String> {
    headers
        .iter()
        .find(|(key, _)| key == name)
        .map(|(_, value)| latin1_text(value))
}

fn header_bytes(headers: &[(Vec<u8>, Vec<u8>)], name: &[u8]) -> Option<Vec<u8>> {
    headers
        .iter()
        .find(|(key, _)| key == name)
        .map(|(_, value)| value.clone())
}

fn latin1_text(value: &[u8]) -> String {
    value.iter().map(|byte| char::from(*byte)).collect()
}

fn quote_filename(filename: &str) -> String {
    const SAFE: &[u8] = b"/";
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut quoted = String::with_capacity(filename.len());
    for byte in filename.as_bytes() {
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

fn multipart_content_length(
    ranges: &[(u64, u64)],
    boundary: &str,
    file_size: u64,
    content_type: &[u8],
) -> Result<u128, FileResponseError> {
    // Python sums multipart range lengths with arbitrary-precision integers.
    // u128 covers the product of u64 range sizes and any input-sized range list
    // representable by this process, including Content-Length values > u64.
    let boundary_size =
        u128::try_from(boundary.len()).map_err(|_| file_response_arithmetic_overflow())?;
    let content_type_size =
        u128::try_from(content_type.len()).map_err(|_| file_response_arithmetic_overflow())?;
    let file_size_digits = u128::try_from(file_size.to_string().len())
        .map_err(|_| file_response_arithmetic_overflow())?;
    let mut total = 4_u128
        .checked_add(boundary_size)
        .ok_or_else(file_response_arithmetic_overflow)?;
    for (start, end) in ranges {
        let last_byte = end
            .checked_sub(1)
            .ok_or_else(file_response_arithmetic_overflow)?;
        let range_length = end
            .checked_sub(*start)
            .ok_or_else(file_response_arithmetic_overflow)?;
        let start_digits = u128::try_from(start.to_string().len())
            .map_err(|_| file_response_arithmetic_overflow())?;
        let end_digits = u128::try_from(last_byte.to_string().len())
            .map_err(|_| file_response_arithmetic_overflow())?;
        let part_length = [
            49_u128,
            boundary_size,
            content_type_size,
            file_size_digits,
            start_digits,
            end_digits,
            u128::from(range_length),
        ]
        .into_iter()
        .try_fold(0_u128, u128::checked_add)
        .ok_or_else(file_response_arithmetic_overflow)?;
        total = total
            .checked_add(part_length)
            .ok_or_else(file_response_arithmetic_overflow)?;
    }
    Ok(total)
}

fn multipart_header(
    boundary: &str,
    content_type: &[u8],
    start: u64,
    end: u64,
    file_size: u64,
) -> io::Result<Vec<u8>> {
    let last_byte = end
        .checked_sub(1)
        .ok_or_else(file_response_arithmetic_io_error)?;
    let prefix = format!("--{boundary}\r\nContent-Type: ");
    let suffix = format!(
        "\r\nContent-Range: bytes {start}-{}/{file_size}\r\n\r\n",
        last_byte
    );
    let capacity = prefix
        .len()
        .checked_add(content_type.len())
        .and_then(|capacity| capacity.checked_add(suffix.len()))
        .ok_or_else(file_response_arithmetic_io_error)?;
    let mut output = Vec::new();
    output.try_reserve_exact(capacity).map_err(|_| {
        io::Error::new(
            io::ErrorKind::OutOfMemory,
            "multipart range header allocation failed",
        )
    })?;
    output.extend_from_slice(prefix.as_bytes());
    output.extend_from_slice(content_type);
    output.extend_from_slice(suffix.as_bytes());
    Ok(output)
}

fn random_boundary() -> Result<String, FileResponseError> {
    #[cfg(feature = "fault-contract")]
    if FAIL_NEXT_RANDOM_BOUNDARY.swap(false, Ordering::SeqCst) {
        return Err(FileResponseError::RandomSource);
    }

    let mut random = [0_u8; 13];
    getrandom::fill(&mut random).map_err(|_| FileResponseError::RandomSource)?;
    let mut boundary = String::with_capacity(26);
    for byte in random {
        use std::fmt::Write as _;
        write!(&mut boundary, "{byte:02x}").map_err(|_| FileResponseError::RandomSource)?;
    }
    Ok(boundary)
}

fn lower_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::new();
    for byte in bytes {
        output.push(char::from(HEX[(byte >> 4) as usize]));
        output.push(char::from(HEX[(byte & 0x0f) as usize]));
    }
    output
}

fn unix_seconds(time: SystemTime) -> f64 {
    match time.duration_since(UNIX_EPOCH) {
        Ok(duration) => duration.as_secs_f64(),
        Err(error) => -error.duration().as_secs_f64(),
    }
}

fn python_float_text(value: f64) -> String {
    python_float_string(value)
}

fn system_time_from_seconds(seconds: f64) -> Option<SystemTime> {
    if !seconds.is_finite() {
        return None;
    }
    let duration = Duration::try_from_secs_f64(seconds.abs()).ok()?;
    if seconds.is_sign_negative() {
        UNIX_EPOCH.checked_sub(duration)
    } else {
        UNIX_EPOCH.checked_add(duration)
    }
}

fn unexpected_file_state() -> io::Error {
    io::Error::other("file response has no open file")
}

fn file_response_arithmetic_io_error() -> io::Error {
    io::Error::new(
        io::ErrorKind::InvalidData,
        "file response arithmetic overflow",
    )
}

fn file_response_arithmetic_overflow() -> FileResponseError {
    FileResponseError::ArithmeticOverflow
}
