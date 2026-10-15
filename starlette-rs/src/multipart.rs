//! Rust-owned multipart/form-data parsing for the Python request boundary.

use std::collections::VecDeque;
use std::convert::Infallible;
use std::pin::Pin;
use std::task::{Context, Poll};

use encoding_rs::{Encoding, UTF_16BE, UTF_16LE};
use futures::{Stream, channel::mpsc};
use multer::bytes::Bytes;
use multer::{Field, Multipart, parse_boundary};

/// One part from an input-driven multipart request body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MultipartPart {
    /// Decoded field name.
    pub name: String,
    /// Decoded filename; `None` identifies a text field.
    pub filename: Option<String>,
    /// Lowercase header names and original header value bytes from the parser.
    pub headers: Vec<(Vec<u8>, Vec<u8>)>,
    /// Text field bytes or uploaded file bytes.
    pub data: Vec<u8>,
    /// Decoded text value, or `None` for an uploaded file.
    pub text: Option<String>,
}

/// One ordered parser result, with uploaded file bytes kept outside Rust buffers.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MultipartFormEvent {
    /// A complete text field.
    TextField {
        /// Zero-based position of this part in the multipart body.
        part_index: usize,
        /// Parsed text field.
        part: MultipartPart,
    },
    /// Headers for a file part have been parsed.
    FileStarted {
        /// Zero-based position of this part in the multipart body.
        part_index: usize,
        /// Decoded field name.
        name: String,
        /// Decoded filename.
        filename: String,
        /// Lowercase header names and original header value bytes.
        headers: Vec<(Vec<u8>, Vec<u8>)>,
    },
    /// File bytes produced by the current request-body chunk.
    FileChunk {
        /// Zero-based position of this part in the multipart body.
        part_index: usize,
        /// Bytes belonging to this file part.
        data: Vec<u8>,
    },
    /// The parser reached the end of a file part.
    FileFinished {
        /// Zero-based position of this part in the multipart body.
        part_index: usize,
        /// Total file size in bytes.
        size: usize,
    },
}

/// Multipart parser failures that have Starlette-compatible public messages.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MultipartFormParseError {
    /// The multipart content type has no usable boundary parameter.
    MissingBoundary,
    /// A part did not provide the required Content-Disposition `name` option.
    MissingName,
    /// The configured number of file parts was exceeded.
    TooManyFiles {
        /// Input-provided string form of the configured maximum.
        maximum: String,
    },
    /// The configured number of non-file parts was exceeded.
    TooManyFields {
        /// Input-provided string form of the configured maximum.
        maximum: String,
    },
    /// A non-file part exceeded the configured limit.
    PartTooLarge {
        /// The configured byte limit converted to the displayed KB value.
        max_part_size_kb: i64,
    },
    /// The Rust multipart parser rejected the body.
    Malformed {
        /// Parser diagnostic for a malformed body.
        message: String,
    },
}

/// Incrementally parses multipart/form-data chunks and emits ordered part events.
///
/// Text-part size limits are enforced as bytes arrive, so callers can stop
/// requesting the input stream immediately when a part exceeds its limit.
pub struct MultipartFormParser {
    sender: mpsc::UnboundedSender<Result<Bytes, Infallible>>,
    multipart: Multipart<'static>,
    raw_header_capture: MultipartHeaderCapture,
    active_field: Option<Field<'static>>,
    active_part: Option<MultipartPartBuilder>,
    events: VecDeque<MultipartFormEvent>,
    charset: String,
    max_files: f64,
    max_files_display: String,
    max_fields: f64,
    max_fields_display: String,
    max_part_size: i64,
    files: usize,
    fields: usize,
    parts_started: usize,
    complete: bool,
}

/// Captures multipart part headers before Multer converts them into a map.
///
/// Multer owns parsing decisions and errors. This scanner only retains header
/// blocks so public UploadFile headers can preserve Starlette's callback order
/// and duplicate occurrences.
struct MultipartHeaderCapture {
    opening_boundary: Vec<u8>,
    field_boundary: Vec<u8>,
    state: HeaderCaptureState,
    boundary_prefix: Vec<u8>,
    marker_prefix: Vec<u8>,
    header_bytes: Vec<u8>,
    headers: VecDeque<Vec<(Vec<u8>, Vec<u8>)>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HeaderCaptureState {
    Preamble,
    BoundaryStart,
    BoundaryPadding,
    BoundaryLineFeed,
    Headers,
    Body,
    Done,
}

impl MultipartHeaderCapture {
    fn new(boundary: &str) -> Self {
        let mut opening_boundary = b"--".to_vec();
        opening_boundary.extend_from_slice(boundary.as_bytes());
        let mut field_boundary = b"\r\n--".to_vec();
        field_boundary.extend_from_slice(boundary.as_bytes());
        Self {
            opening_boundary,
            field_boundary,
            state: HeaderCaptureState::Preamble,
            boundary_prefix: Vec::with_capacity(2),
            marker_prefix: Vec::new(),
            header_bytes: Vec::new(),
            headers: VecDeque::new(),
        }
    }

    fn push(&mut self, bytes: &[u8]) {
        let mut offset = 0;
        while offset < bytes.len() {
            match self.state {
                HeaderCaptureState::Preamble => {
                    if let Some(consumed) = find_stream_marker(
                        &mut self.marker_prefix,
                        &bytes[offset..],
                        &self.opening_boundary,
                    ) {
                        offset += consumed;
                        self.state = HeaderCaptureState::BoundaryStart;
                    } else {
                        return;
                    }
                }
                HeaderCaptureState::Body => {
                    if let Some(consumed) = find_stream_marker(
                        &mut self.marker_prefix,
                        &bytes[offset..],
                        &self.field_boundary,
                    ) {
                        offset += consumed;
                        self.state = HeaderCaptureState::BoundaryStart;
                    } else {
                        return;
                    }
                }
                HeaderCaptureState::BoundaryStart => {
                    let needed = 2usize.saturating_sub(self.boundary_prefix.len());
                    let available = bytes.len().saturating_sub(offset);
                    let take = needed.min(available);
                    self.boundary_prefix
                        .extend_from_slice(&bytes[offset..offset + take]);
                    offset += take;
                    if self.boundary_prefix.len() < 2 {
                        return;
                    }
                    if self.boundary_prefix == b"--" {
                        self.state = HeaderCaptureState::Done;
                        return;
                    }
                    self.state = HeaderCaptureState::BoundaryPadding;
                    let prefix = std::mem::take(&mut self.boundary_prefix);
                    for byte in prefix {
                        self.consume_boundary_suffix_byte(byte);
                        if self.state == HeaderCaptureState::Done {
                            return;
                        }
                    }
                }
                HeaderCaptureState::BoundaryPadding => {
                    let byte = bytes[offset];
                    offset += 1;
                    self.consume_boundary_suffix_byte(byte);
                    if self.state == HeaderCaptureState::Done {
                        return;
                    }
                }
                HeaderCaptureState::BoundaryLineFeed => {
                    let byte = bytes[offset];
                    offset += 1;
                    self.state = if byte == b'\n' {
                        HeaderCaptureState::Headers
                    } else {
                        HeaderCaptureState::Done
                    };
                    if self.state == HeaderCaptureState::Done {
                        return;
                    }
                }
                HeaderCaptureState::Headers => {
                    let remaining = &bytes[offset..];
                    let delimiter = b"\r\n\r\n";
                    let cross_prefix = self.header_bytes.len().min(delimiter.len() - 1);
                    let mut cross =
                        self.header_bytes[self.header_bytes.len() - cross_prefix..].to_vec();
                    cross.extend_from_slice(&remaining[..remaining.len().min(delimiter.len() - 1)]);
                    let cross_delimiter = find_subslice(&cross, delimiter)
                        .filter(|position| *position < cross_prefix);
                    if let Some(position) = cross_delimiter {
                        let needed = position + delimiter.len() - cross_prefix;
                        self.header_bytes.extend_from_slice(&remaining[..needed]);
                        offset += needed;
                        self.finish_headers();
                    } else if let Some(position) = find_subslice(remaining, delimiter) {
                        let consumed = position + delimiter.len();
                        self.header_bytes.extend_from_slice(&remaining[..consumed]);
                        offset += consumed;
                        self.finish_headers();
                    } else {
                        self.header_bytes.extend_from_slice(remaining);
                        return;
                    }
                }
                HeaderCaptureState::Done => return,
            }
        }
    }

    fn consume_boundary_suffix_byte(&mut self, byte: u8) {
        match byte {
            b' ' | b'\t' if self.state == HeaderCaptureState::BoundaryPadding => {}
            b'\r' if self.state == HeaderCaptureState::BoundaryPadding => {
                self.state = HeaderCaptureState::BoundaryLineFeed;
            }
            b'\n' if self.state == HeaderCaptureState::BoundaryLineFeed => {
                self.state = HeaderCaptureState::Headers;
            }
            _ => self.state = HeaderCaptureState::Done,
        }
    }

    fn finish_headers(&mut self) {
        self.headers.push_back(callback_headers(&self.header_bytes));
        self.header_bytes.clear();
        self.state = HeaderCaptureState::Body;
    }

    fn pop_headers(&mut self) -> Option<Vec<(Vec<u8>, Vec<u8>)>> {
        self.headers.pop_front()
    }
}

/// Finds a multipart delimiter across chunks while retaining only a possible
/// delimiter prefix between calls.
fn find_stream_marker(prefix: &mut Vec<u8>, input: &[u8], marker: &[u8]) -> Option<usize> {
    if !prefix.is_empty() {
        let prefix_len = prefix.len();
        let mut bridge = prefix.clone();
        bridge.extend_from_slice(&input[..input.len().min(marker.len() - 1)]);
        if let Some(position) =
            find_subslice(&bridge, marker).filter(|position| *position < prefix_len)
        {
            prefix.clear();
            return Some(position + marker.len() - prefix_len);
        }
    }
    if let Some(position) = find_subslice(input, marker) {
        prefix.clear();
        return Some(position + marker.len());
    }

    let retained = if input.len() >= marker.len() - 1 {
        input[input.len() - (marker.len() - 1)..].to_vec()
    } else {
        let mut combined = std::mem::take(prefix);
        combined.extend_from_slice(input);
        combined
    };
    let max_prefix = retained.len().min(marker.len() - 1);
    let matching_len = (1..=max_prefix)
        .rev()
        .find(|length| retained[retained.len() - length..] == marker[..*length]);
    prefix.clear();
    if let Some(length) = matching_len {
        prefix.extend_from_slice(&retained[retained.len() - length..]);
    }
    None
}

/// Extracts the callback-visible header names and values from a completed
/// header block. python-multipart skips leading spaces after the colon while
/// retaining other value bytes, including trailing whitespace.
fn callback_headers(header_block: &[u8]) -> Vec<(Vec<u8>, Vec<u8>)> {
    let mut headers = Vec::new();
    let mut offset = 0;
    while let Some(relative_end) = find_subslice(&header_block[offset..], b"\r\n") {
        if relative_end == 0 {
            break;
        }
        let line_end = offset + relative_end;
        let line = &header_block[offset..line_end];
        if let Some(colon) = line.iter().position(|byte| *byte == b':') {
            let mut value_start = colon + 1;
            while line.get(value_start) == Some(&b' ') {
                value_start += 1;
            }
            headers.push((
                line[..colon].to_ascii_lowercase(),
                line[value_start..].to_vec(),
            ));
        }
        offset = line_end + 2;
    }
    headers
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() {
        return Some(0);
    }
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

struct MultipartPartBuilder {
    part_index: usize,
    name: String,
    filename: Option<String>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    data: Vec<u8>,
    size: usize,
}

impl MultipartFormParseError {
    /// Returns the error message exposed by Starlette's request form parser.
    #[must_use]
    pub fn message(&self) -> String {
        match self {
            Self::MissingBoundary => "Missing boundary in multipart.".to_owned(),
            Self::MissingName => {
                "The Content-Disposition header field \"name\" must be provided.".to_owned()
            }
            Self::TooManyFiles { maximum } => {
                format!("Too many files. Maximum number of files is {maximum}.")
            }
            Self::TooManyFields { maximum } => {
                format!("Too many fields. Maximum number of fields is {maximum}.")
            }
            Self::PartTooLarge { max_part_size_kb } => {
                format!("Part exceeded maximum size of {max_part_size_kb}KB.")
            }
            Self::Malformed { message } => message.clone(),
        }
    }
}

/// Extracts the boundary before Request.form starts receiving request chunks.
pub fn multipart_boundary(content_type: &str) -> Result<String, MultipartFormParseError> {
    parse_boundary(content_type).map_err(|_| MultipartFormParseError::MissingBoundary)
}

/// Parses a multipart/form-data body and enforces Starlette's file, field,
/// and text-part limits.
pub fn parse_multipart_form(
    body: &[u8],
    content_type: &str,
    max_files: f64,
    max_files_display: &str,
    max_fields: f64,
    max_fields_display: &str,
    max_part_size: i64,
) -> Result<Vec<MultipartPart>, MultipartFormParseError> {
    let mut parser = MultipartFormParser::new(
        content_type,
        max_files,
        max_files_display,
        max_fields,
        max_fields_display,
        max_part_size,
    )?;
    parser.push_chunk(body.to_vec())?;
    parser.finish()
}

fn collect_multipart_parts(events: Vec<MultipartFormEvent>) -> Vec<MultipartPart> {
    let mut parts = Vec::new();
    for event in events {
        match event {
            MultipartFormEvent::TextField { part_index, part } => {
                let index = part_index_slot(&mut parts, part_index);
                *index = Some(part);
            }
            MultipartFormEvent::FileStarted {
                part_index,
                name,
                filename,
                headers,
            } => {
                let index = part_index_slot(&mut parts, part_index);
                *index = Some(MultipartPart {
                    name,
                    filename: Some(filename),
                    headers,
                    data: Vec::new(),
                    text: None,
                });
            }
            MultipartFormEvent::FileChunk { part_index, data } => {
                if let Some(Some(part)) = parts.get_mut(part_index) {
                    part.data.extend_from_slice(&data);
                }
            }
            MultipartFormEvent::FileFinished { .. } => {}
        }
    }
    parts.into_iter().flatten().collect()
}

fn part_index_slot(
    parts: &mut Vec<Option<MultipartPart>>,
    part_index: usize,
) -> &mut Option<MultipartPart> {
    parts.resize_with(part_index + 1, || None);
    &mut parts[part_index]
}

impl MultipartFormParser {
    /// Creates a parser with the supplied Starlette multipart limits.
    pub fn new(
        content_type: &str,
        max_files: f64,
        max_files_display: &str,
        max_fields: f64,
        max_fields_display: &str,
        max_part_size: i64,
    ) -> Result<Self, MultipartFormParseError> {
        let boundary = multipart_boundary(content_type)?;
        let (sender, receiver) = mpsc::unbounded();
        Ok(Self {
            sender,
            multipart: Multipart::new(receiver, boundary.clone()),
            raw_header_capture: MultipartHeaderCapture::new(&boundary),
            active_field: None,
            active_part: None,
            events: VecDeque::new(),
            charset: request_charset(content_type),
            max_files,
            max_files_display: max_files_display.to_owned(),
            max_fields,
            max_fields_display: max_fields_display.to_owned(),
            max_part_size,
            files: 0,
            fields: 0,
            parts_started: 0,
            complete: false,
        })
    }

    /// Feeds one request-body chunk into the parser.
    pub fn push_chunk(&mut self, chunk: Vec<u8>) -> Result<(), MultipartFormParseError> {
        if self.complete || chunk.is_empty() {
            return Ok(());
        }
        self.raw_header_capture.push(&chunk);
        self.sender
            .unbounded_send(Ok(Bytes::from(chunk)))
            .map_err(|_| MultipartFormParseError::Malformed {
                message: "multipart parser input stream is closed".to_owned(),
            })?;
        self.process_available()
    }

    /// Finishes the request-body stream and returns its parsed parts.
    pub fn finish(mut self) -> Result<Vec<MultipartPart>, MultipartFormParseError> {
        self.finish_events()?;
        Ok(collect_multipart_parts(self.drain_events()))
    }

    /// Finishes the request-body stream while retaining events for draining.
    pub fn finish_events(&mut self) -> Result<(), MultipartFormParseError> {
        self.sender.close_channel();
        self.process_available()
    }

    /// Removes parser events produced since the previous drain.
    pub fn drain_events(&mut self) -> Vec<MultipartFormEvent> {
        self.events.drain(..).collect()
    }

    fn process_available(&mut self) -> Result<(), MultipartFormParseError> {
        let mut context = Context::from_waker(futures::task::noop_waker_ref());
        loop {
            if self.complete {
                return Ok(());
            }
            if let Some(field) = self.active_field.as_mut() {
                match Pin::new(field).poll_next(&mut context) {
                    Poll::Ready(Some(Ok(chunk))) if chunk.is_empty() => {}
                    Poll::Ready(Some(Ok(chunk))) => {
                        let Some(part) = self.active_part.as_mut() else {
                            return Err(MultipartFormParseError::Malformed {
                                message: "multipart parser lost the active part".to_owned(),
                            });
                        };
                        if part.filename.is_none()
                            && part_size_exceeded(part.data.len(), chunk.len(), self.max_part_size)
                        {
                            return Err(MultipartFormParseError::PartTooLarge {
                                max_part_size_kb: self.max_part_size / 1024,
                            });
                        }
                        if part.filename.is_none() {
                            part.data.extend_from_slice(&chunk);
                        } else {
                            part.size = part.size.saturating_add(chunk.len());
                            self.events.push_back(MultipartFormEvent::FileChunk {
                                part_index: part.part_index,
                                data: chunk.to_vec(),
                            });
                        }
                    }
                    Poll::Ready(Some(Err(error))) => {
                        return Err(MultipartFormParseError::Malformed {
                            message: error.to_string(),
                        });
                    }
                    Poll::Ready(None) => {
                        self.active_field = None;
                        self.complete_active_part()?;
                    }
                    Poll::Pending => return Ok(()),
                }
                continue;
            }

            match self.multipart.poll_next_field(&mut context) {
                Poll::Ready(Ok(Some(field))) => self.start_part(field)?,
                Poll::Ready(Ok(None)) => {
                    self.complete = true;
                    return Ok(());
                }
                Poll::Ready(Err(error)) => {
                    return Err(MultipartFormParseError::Malformed {
                        message: error.to_string(),
                    });
                }
                Poll::Pending => return Ok(()),
            }
        }
    }

    fn start_part(&mut self, field: Field<'static>) -> Result<(), MultipartFormParseError> {
        let headers = self.raw_header_capture.pop_headers().unwrap_or_else(|| {
            field
                .headers()
                .iter()
                .map(|(name, value)| {
                    (
                        name.as_str().as_bytes().to_ascii_lowercase(),
                        value.as_bytes().to_vec(),
                    )
                })
                .collect()
        });
        // Starlette overwrites its stored Content-Disposition value on every
        // callback, so the final wire occurrence selects the part metadata.
        let disposition = headers
            .iter()
            .rev()
            .find(|(name, _)| name == b"content-disposition")
            .map(|(_, value)| value.clone())
            .or_else(|| {
                field
                    .headers()
                    .get("content-disposition")
                    .map(|value| value.as_bytes().to_vec())
            });
        let name = disposition
            .as_deref()
            .and_then(|value| disposition_parameter(value, "name"))
            .map(|value| user_safe_decode(&value, &self.charset))
            .ok_or(MultipartFormParseError::MissingName)?;
        let filename = disposition
            .as_deref()
            .and_then(|value| disposition_parameter(value, "filename"))
            .map(|value| user_safe_decode(&value, &self.charset));
        if filename.is_some() {
            self.files += 1;
            if self.files as f64 > self.max_files {
                return Err(MultipartFormParseError::TooManyFiles {
                    maximum: self.max_files_display.clone(),
                });
            }
        } else {
            self.fields += 1;
            if self.fields as f64 > self.max_fields {
                return Err(MultipartFormParseError::TooManyFields {
                    maximum: self.max_fields_display.clone(),
                });
            }
        }

        let part_index = self.parts_started;
        self.parts_started += 1;
        self.active_part = Some(MultipartPartBuilder {
            part_index,
            name,
            filename,
            headers,
            data: Vec::new(),
            size: 0,
        });
        if let Some(part) = self.active_part.as_ref() {
            if let Some(filename) = part.filename.as_ref() {
                self.events.push_back(MultipartFormEvent::FileStarted {
                    part_index,
                    name: part.name.clone(),
                    filename: filename.clone(),
                    headers: part.headers.clone(),
                });
            }
        }
        self.active_field = Some(field);
        Ok(())
    }

    fn complete_active_part(&mut self) -> Result<(), MultipartFormParseError> {
        let Some(part) = self.active_part.take() else {
            return Err(MultipartFormParseError::Malformed {
                message: "multipart parser lost the completed part".to_owned(),
            });
        };
        if part.filename.is_none() {
            let text = user_safe_decode(&part.data, &self.charset);
            self.events.push_back(MultipartFormEvent::TextField {
                part_index: part.part_index,
                part: MultipartPart {
                    name: part.name,
                    filename: None,
                    headers: part.headers,
                    data: part.data,
                    text: Some(text),
                },
            });
        } else {
            self.events.push_back(MultipartFormEvent::FileFinished {
                part_index: part.part_index,
                size: part.size,
            });
        }
        Ok(())
    }
}

fn part_size_exceeded(current_size: usize, chunk_size: usize, limit: i64) -> bool {
    let current_size = i128::try_from(current_size).unwrap_or(i128::MAX);
    let chunk_size = i128::try_from(chunk_size).unwrap_or(i128::MAX);
    current_size.saturating_add(chunk_size) > i128::from(limit)
}

fn disposition_parameter(header: &[u8], wanted: &str) -> Option<Vec<u8>> {
    // Starlette passes the parser's original header bytes through
    // `parse_options_header`, then decodes the `name` and `filename` options
    // with the request charset (falling back to Latin-1). Multer's convenience
    // accessors require UTF-8 and would reject otherwise valid legacy form
    // submissions before that compatibility decoding can happen.
    let header: String = header.iter().map(|byte| char::from(*byte)).collect();
    let mut value = None;
    for segment in split_disposition_parameters(&header).into_iter().skip(1) {
        let Some((key, raw_value)) = segment.split_once('=') else {
            continue;
        };
        let key = key.trim().to_ascii_lowercase();
        if key.contains('*') || key != wanted {
            continue;
        }

        let raw_value = raw_value.trim();
        let quoted = raw_value.len() >= 2 && raw_value.starts_with('"') && raw_value.ends_with('"');
        let parsed = if quoted {
            raw_value[1..raw_value.len() - 1]
                .replace("\\\\", "\\")
                .replace("\\\"", "\"")
        } else {
            raw_value.to_owned()
        };

        // Starlette delegates Content-Disposition parsing to
        // python-multipart, which removes the local path from legacy IE
        // filenames before returning the filename parameter.
        let parsed = if wanted == "filename"
            && (parsed.as_bytes().get(1..3) == Some(b":\\") || parsed.starts_with("\\\\"))
        {
            parsed.rsplit('\\').next().unwrap_or_default().to_owned()
        } else {
            parsed
        };

        value = Some(parsed.chars().map(|character| character as u8).collect());
    }
    value
}

fn split_disposition_parameters(header: &str) -> Vec<&str> {
    let mut segments = Vec::new();
    let mut segment_start = 0;
    let mut quoted = false;
    let mut backslashes = 0usize;
    for (index, character) in header.char_indices() {
        match character {
            '"' => {
                if backslashes % 2 == 0 {
                    quoted = !quoted;
                }
                backslashes = 0;
            }
            '\\' => backslashes += 1,
            ';' if !quoted => {
                segments.push(&header[segment_start..index]);
                segment_start = index + character.len_utf8();
                backslashes = 0;
            }
            _ => backslashes = 0,
        }
    }
    segments.push(&header[segment_start..]);
    segments
}

fn request_charset(content_type: &str) -> String {
    // `parse_options_header` stores parameters in a dict, so a later charset
    // replaces an earlier one when the header repeats this parameter.
    split_disposition_parameters(content_type)
        .into_iter()
        .skip(1)
        .filter_map(|parameter| parameter.split_once('='))
        .rfind(|(name, _)| name.trim().eq_ignore_ascii_case("charset"))
        .map_or_else(
            || "utf-8".to_owned(),
            |(_, value)| unquote_parameter(value.trim()),
        )
}

fn unquote_parameter(value: &str) -> String {
    if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
        value[1..value.len() - 1]
            .replace("\\\\", "\\")
            .replace("\\\"", "\"")
    } else {
        value.to_owned()
    }
}

fn user_safe_decode(bytes: &[u8], charset: &str) -> String {
    // Latin-1 maps every byte directly. For ASCII, Starlette decodes strictly
    // and falls back to Latin-1 on non-ASCII bytes, so both codecs have the
    // same final output even though encoding_rs aliases ASCII to Windows-1252.
    if is_iso_8859_1_charset(charset) || is_ascii_charset(charset) {
        return bytes.iter().map(|byte| char::from(*byte)).collect();
    }

    if is_generic_utf16_charset(charset) {
        return decode_generic_utf16(bytes)
            .unwrap_or_else(|| bytes.iter().map(|byte| char::from(*byte)).collect());
    }

    if let Some(encoding) = Encoding::for_label(charset.as_bytes()) {
        let (decoded, had_errors) = encoding.decode_without_bom_handling(bytes);
        if !had_errors {
            return decoded.into_owned();
        }
    }
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

fn is_generic_utf16_charset(charset: &str) -> bool {
    let normalized = charset.trim().to_ascii_lowercase().replace('_', "-");
    matches!(normalized.as_str(), "utf-16" | "utf16")
}

fn decode_generic_utf16(bytes: &[u8]) -> Option<String> {
    // Python's generic utf-16 codec requires a BOM to select byte order.
    // encoding_rs maps the generic label to UTF-16LE and accepts BOM-less
    // input, so select the codec's endianness explicitly and fall back when
    // the source codec would reject the bytes.
    let (encoding, content) = if let Some(content) = bytes.strip_prefix(b"\xFF\xFE") {
        (UTF_16LE, content)
    } else if let Some(content) = bytes.strip_prefix(b"\xFE\xFF") {
        (UTF_16BE, content)
    } else {
        return None;
    };
    let (decoded, had_errors) = encoding.decode_without_bom_handling(content);
    (!had_errors).then(|| decoded.into_owned())
}

fn is_iso_8859_1_charset(charset: &str) -> bool {
    let normalized = charset
        .bytes()
        .filter(u8::is_ascii_alphanumeric)
        .map(|byte| byte.to_ascii_lowercase() as char)
        .collect::<String>();
    matches!(
        normalized.as_str(),
        "8859"
            | "cp819"
            | "csisolatin1"
            | "ibm819"
            | "iso8859"
            | "iso88591"
            | "iso885911987"
            | "isoir100"
            | "l1"
            | "latin"
            | "latin1"
    )
}

fn is_ascii_charset(charset: &str) -> bool {
    let normalized = charset
        .bytes()
        .filter(u8::is_ascii_alphanumeric)
        .map(|byte| byte.to_ascii_lowercase() as char)
        .collect::<String>();
    matches!(
        normalized.as_str(),
        "ascii"
            | "usascii"
            | "iso646us"
            | "ansix341968"
            | "ansix341986"
            | "isoir6"
            | "csascii"
            | "cp367"
            | "ibm367"
    )
}
