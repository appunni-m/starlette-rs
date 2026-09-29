//! Rust-owned file response planning, byte-range handling, and streaming.

use std::fmt::{self, Display, Formatter};
use std::fs::{self, File, Metadata};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use md5::{Digest, Md5};

use crate::response::{Response, ResponseError};

const DEFAULT_CHUNK_SIZE: usize = 64 * 1024;
type RawHeaderPair = (Vec<u8>, Vec<u8>);
type RawHeaders = Vec<RawHeaderPair>;

/// File metadata supplied by the caller instead of querying the filesystem.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileMetadata {
    size: u64,
    modified: SystemTime,
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

            let mut stat = Self {
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
            {
                use std::os::macos::fs::MetadataExt as MacMetadataExt;

                stat.flags = Some(MacMetadataExt::st_flags(metadata));
                stat.generation = Some(MacMetadataExt::st_gen(metadata));
                stat.birth_time = Some(FileStatTimestamp {
                    seconds: MacMetadataExt::st_birthtime(metadata),
                    nanoseconds: MacMetadataExt::st_birthtime_nsec(metadata),
                });
            }

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
    /// Creates metadata from the same timestamp value used by Python's `str`.
    ///
    /// # Errors
    ///
    /// Returns [`FileResponseError::InvalidTimestamp`] if the timestamp is not
    /// finite or cannot be represented by [`SystemTime`].
    pub fn from_unix_seconds(
        size: u64,
        modified_seconds: f64,
        modified_text: impl Into<String>,
    ) -> Result<Self, FileResponseError> {
        let modified = system_time_from_seconds(modified_seconds)
            .ok_or(FileResponseError::InvalidTimestamp)?;
        Ok(Self {
            size,
            modified,
            modified_text: modified_text.into(),
            stat_result: None,
        })
    }

    pub(crate) fn from_metadata(metadata: &Metadata) -> Result<Self, FileResponseError> {
        let modified = metadata.modified().map_err(FileResponseError::StatIo)?;
        let seconds = unix_seconds(modified);
        Ok(Self {
            size: metadata.len(),
            modified,
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
        unix_seconds(self.modified)
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
    /// The path does not exist.
    MissingFile(String),
    /// The path exists but does not identify a regular file.
    NotAFile(String),
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
            Self::MissingFile(path) => write!(formatter, "File at path {path} does not exist."),
            Self::NotAFile(path) => write!(formatter, "File at path {path} is not a file."),
            Self::StatIo(error) => Display::fmt(error, formatter),
            Self::RandomSource => formatter.write_str("could not generate multipart boundary"),
        }
    }
}

impl std::error::Error for FileResponseError {}

impl FileResponse {
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
        let source = options
            .filename
            .as_deref()
            .map_or_else(|| path.clone(), PathBuf::from);
        let guessed_type = mime_guess::from_path(source).first_raw();
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
            chunk_size: options.chunk_size.max(1),
            max_ranges: options.max_ranges,
        })
    }

    /// Appends a response cookie using Starlette's basic cookie formatting.
    ///
    /// # Errors
    ///
    /// Returns a response error if the cookie cannot be represented in the
    /// Latin-1 response-header encoding.
    pub fn set_cookie(&mut self, key: &str, value: &str) -> Result<(), ResponseError> {
        let mut response =
            Response::from_content(200, Vec::new(), None, std::iter::empty::<(&str, &str)>())?;
        response.set_cookie(key, value)?;
        if let Some((_, cookie)) = response
            .headers()
            .iter()
            .find(|(name, _)| name.as_slice() == b"set-cookie")
        {
            self.headers.push((b"set-cookie".to_vec(), cookie.clone()));
        }
        Ok(())
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

        let mut headers = self.headers.clone();
        set_stat_headers(&mut headers, &metadata)?;
        let range = header_value(request_headers, b"range");
        let if_range = header_value(request_headers, b"if-range");
        let use_range = range.as_ref().is_some_and(|_| {
            if_range.as_ref().is_none_or(|value| {
                value == &header_text(&headers, b"last-modified").unwrap_or_default()
                    || value == &header_text(&headers, b"etag").unwrap_or_default()
            })
        });

        let send_header_only = scope_type == "http" && method.eq_ignore_ascii_case("HEAD");
        let mut send_pathsend = scope_type == "http" && pathsend_extension && !send_header_only;
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
                    set_header(
                        &mut headers,
                        "content-range",
                        &format!("bytes {start}-{}/{size}", end - 1, size = metadata.size),
                    )?;
                    set_header(&mut headers, "content-length", &(end - start).to_string())?;
                    mode = FileResponseMode::SingleRange { start, end };
                }
                Ok(ranges) => {
                    send_pathsend = false;
                    let boundary = random_boundary()?;
                    let content_type = header_bytes(&headers, b"content-type").unwrap_or_default();
                    let content_length =
                        multipart_content_length(&ranges, &boundary, metadata.size, &content_type);
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
                    ));
                }
            }
        }

        Ok(FileResponseCall {
            phase: FileResponsePhase::Start,
            pending: None,
            status_code,
            headers,
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
        })
    }
}

impl FileResponseCall {
    fn prepared_error(status_code: u16, headers: Vec<(Vec<u8>, Vec<u8>)>, body: Vec<u8>) -> Self {
        Self {
            phase: FileResponsePhase::Start,
            pending: None,
            status_code,
            headers,
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
        }
    }

    /// Produces the next send/background/completion action.
    ///
    /// File reads happen one chunk at a time in Rust after the start event has
    /// been sent, so the Python bridge does not assemble the response body.
    pub fn step(&mut self) -> Result<FileResponseCallStep, io::Error> {
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
                    let limit = usize::try_from((end - cursor).min(self.chunk_size as u64))
                        .unwrap_or(self.chunk_size);
                    let mut body = vec![0; limit];
                    let size = file.read(&mut body)?;
                    body.truncate(size);
                    let next_cursor = cursor.saturating_add(size as u64);
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
                    let (start, end) = ranges[index];
                    let body = multipart_header(boundary, content_type, start, end, self.file_size);
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
                    let (_, end) = ranges[index];
                    self.open_file()?;
                    let file = self.file.as_mut().ok_or_else(unexpected_file_state)?;
                    file.seek(SeekFrom::Start(cursor))?;
                    let limit = usize::try_from((end - cursor).min(self.chunk_size as u64))
                        .unwrap_or(self.chunk_size);
                    let mut body = vec![0; limit];
                    let size = file.read(&mut body)?;
                    body.truncate(size);
                    let next_cursor = cursor.saturating_add(size as u64);
                    let after = if next_cursor >= end || size == 0 {
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
                    let after = if index + 1 < range_count {
                        FileResponsePhase::MultipartHeader { index: index + 1 }
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
    if !units.trim().eq_ignore_ascii_case("bytes") {
        return Err(RangeParseError::Malformed("Only support bytes range"));
    }
    if requested.bytes().filter(|byte| *byte == b',').count() + 1 > max_ranges {
        return Ok(Vec::new());
    }

    let mut ranges = Vec::new();
    for part in requested.split(',') {
        let part = part.trim();
        if part.is_empty() || part == "-" {
            continue;
        }
        let Some((start_text, end_text)) = part.split_once('-') else {
            continue;
        };
        let start_text = start_text.trim();
        let end_text = end_text.trim();
        let start = if start_text.is_empty() {
            let Some(suffix) = parse_decimal(end_text) else {
                continue;
            };
            file_size.saturating_sub(suffix)
        } else {
            let Some(start) = parse_decimal(start_text) else {
                continue;
            };
            start
        };
        let end = if !start_text.is_empty() && !end_text.is_empty() {
            let Some(raw_end) = parse_decimal(end_text) else {
                continue;
            };
            if raw_end < file_size {
                raw_end.saturating_add(1)
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

fn parse_decimal(value: &str) -> Option<u64> {
    let digits = value.strip_prefix('+').unwrap_or(value);
    if digits.is_empty() || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    Some(digits.bytes().fold(0_u64, |number, byte| {
        number
            .saturating_mul(10)
            .saturating_add(u64::from(byte - b'0'))
    }))
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
        &httpdate::fmt_http_date(metadata.modified),
    )?;
    let input = format!("{}-{}", metadata.modified_text, metadata.size);
    let mut hasher = Md5::new();
    hasher.update(input.as_bytes());
    set_default_header(
        headers,
        "etag",
        &format!("\"{}\"", lower_hex(&hasher.finalize())),
    )?;
    Ok(())
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
) -> u64 {
    let boundary_size = boundary.len() as u64;
    let content_type_size = content_type.len() as u64;
    let file_size_digits = file_size.to_string().len() as u64;
    let parts = ranges.iter().map(|(start, end)| {
        49_u64
            + boundary_size
            + content_type_size
            + file_size_digits
            + start.to_string().len() as u64
            + end.saturating_sub(1).to_string().len() as u64
            + end.saturating_sub(*start)
    });
    parts.fold(4 + boundary_size, u64::saturating_add)
}

fn multipart_header(
    boundary: &str,
    content_type: &[u8],
    start: u64,
    end: u64,
    file_size: u64,
) -> Vec<u8> {
    let prefix = format!("--{boundary}\r\nContent-Type: ");
    let suffix = format!(
        "\r\nContent-Range: bytes {start}-{}/{file_size}\r\n\r\n",
        end - 1
    );
    let mut output = Vec::with_capacity(prefix.len() + content_type.len() + suffix.len());
    output.extend_from_slice(prefix.as_bytes());
    output.extend_from_slice(content_type);
    output.extend_from_slice(suffix.as_bytes());
    output
}

fn random_boundary() -> Result<String, FileResponseError> {
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
    let mut output = String::with_capacity(bytes.len() * 2);
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
    let text = value.to_string();
    if text.contains('.') || text.contains('e') || text.contains('E') {
        text
    } else {
        format!("{text}.0")
    }
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
