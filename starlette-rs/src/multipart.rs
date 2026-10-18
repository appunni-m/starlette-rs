//! Rust-owned multipart/form-data parsing for the Python request boundary.

use std::collections::{BTreeMap, VecDeque};
use std::convert::Infallible;
use std::pin::Pin;
use std::task::{Context, Poll};

use encoding_rs::{Encoding, UTF_16BE, UTF_16LE};
use futures::{Stream, channel::mpsc};
use multer::bytes::Bytes;
use multer::{Error as MulterError, Field, Multipart};

const PYTHON_MULTIPART_MAX_BOUNDARY_LENGTH: usize = 256;
const PYTHON_MULTIPART_MAX_HEADER_COUNT: usize = 8;
const PYTHON_MULTIPART_MAX_HEADER_SIZE: usize = 4_224;

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
    /// The multipart parser dependency rejected an overlong boundary.
    BoundaryTooLong {
        /// Boundary length as bytes in the dependency's Latin-1 input model.
        length: usize,
    },
    /// The multipart parser dependency rejected a part with too many headers.
    HeaderCountExceeded {
        /// Byte offset within the current request-body chunk.
        offset: usize,
    },
    /// The multipart parser dependency rejected an oversized header line.
    HeaderSizeExceeded {
        /// Byte offset within the current request-body chunk.
        offset: usize,
    },
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

fn multipart_arithmetic_overflow() -> MultipartFormParseError {
    MultipartFormParseError::Malformed {
        message: "multipart arithmetic overflow".to_owned(),
    }
}

/// Incrementally parses multipart/form-data chunks and emits ordered part events.
///
/// Text-part size limits are enforced as bytes arrive, so callers can stop
/// requesting the input stream immediately when a part exceeds its limit.
pub struct MultipartFormParser {
    sender: mpsc::UnboundedSender<Result<Bytes, Infallible>>,
    multipart: Multipart<'static>,
    boundary_filter: MultipartBoundaryFilter,
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
    header_count: usize,
    header_line_size: usize,
    header_parse_state: HeaderParseState,
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HeaderParseState {
    Field,
    ValueStart,
    Value,
    LineFeed,
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
            header_count: 0,
            header_line_size: 0,
            header_parse_state: HeaderParseState::Field,
        }
    }

    fn push(&mut self, bytes: &[u8]) -> Result<(), (MultipartFormParseError, usize)> {
        let mut offset = 0;
        while offset < bytes.len() {
            match self.state {
                HeaderCaptureState::Preamble => {
                    if let Some(consumed) = find_stream_marker(
                        &mut self.marker_prefix,
                        &bytes[offset..],
                        &self.opening_boundary,
                    ) {
                        offset = offset
                            .checked_add(consumed)
                            .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                        self.state = HeaderCaptureState::BoundaryStart;
                    } else {
                        return Ok(());
                    }
                }
                HeaderCaptureState::Body => {
                    if let Some(consumed) = find_stream_marker(
                        &mut self.marker_prefix,
                        &bytes[offset..],
                        &self.field_boundary,
                    ) {
                        offset = offset
                            .checked_add(consumed)
                            .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                        self.state = HeaderCaptureState::BoundaryStart;
                    } else {
                        return Ok(());
                    }
                }
                HeaderCaptureState::BoundaryStart => {
                    let needed = 2usize
                        .checked_sub(self.boundary_prefix.len())
                        .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                    let available = bytes
                        .len()
                        .checked_sub(offset)
                        .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                    let take = needed.min(available);
                    let take_end = offset
                        .checked_add(take)
                        .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                    self.boundary_prefix
                        .extend_from_slice(&bytes[offset..take_end]);
                    offset = take_end;
                    if self.boundary_prefix.len() < 2 {
                        return Ok(());
                    }
                    if self.boundary_prefix == b"--" {
                        self.state = HeaderCaptureState::Done;
                        return Ok(());
                    }
                    self.state = HeaderCaptureState::BoundaryPadding;
                    let prefix = std::mem::take(&mut self.boundary_prefix);
                    for byte in prefix {
                        self.consume_boundary_suffix_byte(byte);
                        if self.state == HeaderCaptureState::Done {
                            return Ok(());
                        }
                    }
                }
                HeaderCaptureState::BoundaryPadding => {
                    let byte = bytes[offset];
                    offset = offset
                        .checked_add(1)
                        .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                    self.consume_boundary_suffix_byte(byte);
                    if self.state == HeaderCaptureState::Done {
                        return Ok(());
                    }
                }
                HeaderCaptureState::BoundaryLineFeed => {
                    let byte = bytes[offset];
                    offset = offset
                        .checked_add(1)
                        .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                    self.state = if byte == b'\n' {
                        self.begin_headers();
                        HeaderCaptureState::Headers
                    } else {
                        HeaderCaptureState::Done
                    };
                    if self.state == HeaderCaptureState::Done {
                        return Ok(());
                    }
                }
                HeaderCaptureState::Headers => {
                    let remaining = &bytes[offset..];
                    let mut consumed = 0;
                    let mut finished = false;
                    let mut size_segment_start = None;
                    while consumed < remaining.len() {
                        let byte = remaining[consumed];
                        let byte_offset = offset
                            .checked_add(consumed)
                            .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                        if let Err(error) =
                            self.validate_header_byte(byte, byte_offset, &mut size_segment_start)
                        {
                            self.header_bytes.extend_from_slice(&remaining[..consumed]);
                            return Err((error, byte_offset));
                        }
                        self.header_bytes.push(byte);
                        consumed = consumed
                            .checked_add(1)
                            .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                        if self.header_bytes.ends_with(b"\r\n\r\n") {
                            offset = offset
                                .checked_add(consumed)
                                .ok_or_else(|| (multipart_arithmetic_overflow(), offset))?;
                            self.finish_headers().map_err(|error| (error, offset))?;
                            finished = true;
                            break;
                        }
                    }
                    if !finished {
                        return Ok(());
                    }
                }
                HeaderCaptureState::Done => return Ok(()),
            }
        }
        Ok(())
    }

    fn consume_boundary_suffix_byte(&mut self, byte: u8) {
        match byte {
            b' ' | b'\t' if self.state == HeaderCaptureState::BoundaryPadding => {}
            b'\r' if self.state == HeaderCaptureState::BoundaryPadding => {
                self.state = HeaderCaptureState::BoundaryLineFeed;
            }
            b'\n' if self.state == HeaderCaptureState::BoundaryLineFeed => {
                self.begin_headers();
            }
            _ => self.state = HeaderCaptureState::Done,
        }
    }

    fn begin_headers(&mut self) {
        self.header_count = 0;
        self.header_line_size = 0;
        self.header_parse_state = HeaderParseState::Field;
        self.state = HeaderCaptureState::Headers;
    }

    fn validate_header_byte(
        &mut self,
        byte: u8,
        offset: usize,
        size_segment_start: &mut Option<usize>,
    ) -> Result<(), MultipartFormParseError> {
        match self.header_parse_state {
            HeaderParseState::Field => {
                if byte == b'\r' {
                    self.header_parse_state = HeaderParseState::LineFeed;
                    return Ok(());
                }
                if self.header_line_size == 0 {
                    self.header_count = self
                        .header_count
                        .checked_add(1)
                        .ok_or(MultipartFormParseError::HeaderCountExceeded { offset })?;
                    if self.header_count > PYTHON_MULTIPART_MAX_HEADER_COUNT {
                        return Err(MultipartFormParseError::HeaderCountExceeded { offset });
                    }
                }
                let segment_start = size_segment_start.get_or_insert(offset);
                self.header_line_size = self.header_line_size.checked_add(1).ok_or(
                    MultipartFormParseError::HeaderSizeExceeded {
                        offset: *segment_start,
                    },
                )?;
                if self.header_line_size > PYTHON_MULTIPART_MAX_HEADER_SIZE {
                    return Err(MultipartFormParseError::HeaderSizeExceeded {
                        offset: *segment_start,
                    });
                }
                if byte == b':' {
                    self.header_parse_state = HeaderParseState::ValueStart;
                    *size_segment_start = None;
                }
            }
            HeaderParseState::ValueStart if byte == b' ' => {
                self.header_line_size = self
                    .header_line_size
                    .checked_add(1)
                    .ok_or(MultipartFormParseError::HeaderSizeExceeded { offset })?;
                if self.header_line_size > PYTHON_MULTIPART_MAX_HEADER_SIZE {
                    return Err(MultipartFormParseError::HeaderSizeExceeded { offset });
                }
            }
            HeaderParseState::ValueStart => {
                if byte == b'\r' {
                    self.header_line_size = 0;
                    self.header_parse_state = HeaderParseState::LineFeed;
                    return Ok(());
                }
                self.header_parse_state = HeaderParseState::Value;
                *size_segment_start = Some(offset);
                return self.validate_header_byte(byte, offset, size_segment_start);
            }
            HeaderParseState::Value => {
                if byte == b'\r' {
                    self.header_line_size = 0;
                    self.header_parse_state = HeaderParseState::LineFeed;
                    *size_segment_start = None;
                    return Ok(());
                }
                let segment_start = size_segment_start.get_or_insert(offset);
                self.header_line_size = self.header_line_size.checked_add(1).ok_or(
                    MultipartFormParseError::HeaderSizeExceeded {
                        offset: *segment_start,
                    },
                )?;
                if self.header_line_size > PYTHON_MULTIPART_MAX_HEADER_SIZE {
                    return Err(MultipartFormParseError::HeaderSizeExceeded {
                        offset: *segment_start,
                    });
                }
            }
            HeaderParseState::LineFeed => {
                if byte == b'\n' {
                    self.header_line_size = 0;
                    self.header_parse_state = HeaderParseState::Field;
                } else {
                    self.header_parse_state = HeaderParseState::Field;
                }
            }
        }
        Ok(())
    }

    fn finish_headers(&mut self) -> Result<(), MultipartFormParseError> {
        self.headers
            .push_back(callback_headers(&self.header_bytes)?);
        self.header_bytes.clear();
        self.state = HeaderCaptureState::Body;
        Ok(())
    }

    fn pop_headers(&mut self) -> Option<Vec<(Vec<u8>, Vec<u8>)>> {
        self.headers.pop_front()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MultipartBoundaryFilterState {
    Preamble,
    OpeningSuffix,
    Headers,
    Body,
    PartSuffix,
    Done,
}

enum BoundarySuffix {
    Pending,
    Invalid,
    Valid { consumed: usize, closing: bool },
}

/// Shields Multer from boundary prefixes whose suffix is not a delimiter.
///
/// Multer scans for `\r\n--boundary` before validating its suffix. A false
/// prefix is part data for Starlette's parser, so replace its leading CR while
/// parsing, then restore that byte at the public part-data boundary.
struct MultipartBoundaryFilter {
    opening_marker: Vec<u8>,
    part_marker: Vec<u8>,
    state: MultipartBoundaryFilterState,
    buffer: Vec<u8>,
    candidate: Vec<u8>,
    parts_started: usize,
    current_part_index: usize,
    part_data_offset: usize,
    restore_offsets: BTreeMap<usize, VecDeque<usize>>,
}

impl MultipartBoundaryFilter {
    fn new(boundary: &str) -> Self {
        let mut opening_marker = b"--".to_vec();
        opening_marker.extend_from_slice(boundary.as_bytes());
        let mut part_marker = b"\r\n--".to_vec();
        part_marker.extend_from_slice(boundary.as_bytes());
        Self {
            opening_marker,
            part_marker,
            state: MultipartBoundaryFilterState::Preamble,
            buffer: Vec::new(),
            candidate: Vec::new(),
            parts_started: 0,
            current_part_index: 0,
            part_data_offset: 0,
            restore_offsets: BTreeMap::new(),
        }
    }

    fn push(&mut self, input: &[u8]) -> Result<Vec<u8>, MultipartFormParseError> {
        self.buffer.extend_from_slice(input);
        self.process()
    }

    fn finish(&mut self) -> Result<Vec<u8>, MultipartFormParseError> {
        let mut output = self.process()?;
        output.append(&mut self.candidate);
        output.append(&mut self.buffer);
        self.state = MultipartBoundaryFilterState::Done;
        Ok(output)
    }

    fn take_restore_offsets(
        &mut self,
        part_index: usize,
        chunk_start: usize,
        chunk_end: usize,
    ) -> Vec<usize> {
        let Some(offsets) = self.restore_offsets.get_mut(&part_index) else {
            return Vec::new();
        };
        while offsets.front().is_some_and(|offset| *offset < chunk_start) {
            offsets.pop_front();
        }
        let mut selected = Vec::new();
        while offsets.front().is_some_and(|offset| *offset < chunk_end) {
            if let Some(offset) = offsets.pop_front() {
                selected.push(offset);
            }
        }
        if offsets.is_empty() {
            self.restore_offsets.remove(&part_index);
        }
        selected
    }

    fn process(&mut self) -> Result<Vec<u8>, MultipartFormParseError> {
        let mut output = Vec::new();
        loop {
            match self.state {
                MultipartBoundaryFilterState::Preamble => {
                    if let Some(position) = find_subslice(&self.buffer, &self.opening_marker) {
                        output.extend(self.buffer.drain(..position));
                        self.candidate
                            .extend(self.buffer.drain(..self.opening_marker.len()));
                        self.state = MultipartBoundaryFilterState::OpeningSuffix;
                    } else {
                        let retained =
                            trailing_marker_prefix_len(&self.buffer, &self.opening_marker);
                        let safe = self
                            .buffer
                            .len()
                            .checked_sub(retained)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        output.extend(self.buffer.drain(..safe));
                        return Ok(output);
                    }
                }
                MultipartBoundaryFilterState::OpeningSuffix => {
                    match boundary_suffix(&self.buffer) {
                        BoundarySuffix::Pending => return Ok(output),
                        BoundarySuffix::Valid { consumed, closing } => {
                            output.append(&mut self.candidate);
                            output.extend(self.buffer.drain(..consumed));
                            self.state = if closing {
                                MultipartBoundaryFilterState::Done
                            } else {
                                MultipartBoundaryFilterState::Headers
                            };
                        }
                        BoundarySuffix::Invalid => {
                            if self.candidate.is_empty() {
                                self.state = MultipartBoundaryFilterState::Preamble;
                                continue;
                            }
                            output.push(0);
                            let mut replay = self.candidate.drain(1..).collect::<Vec<_>>();
                            replay.append(&mut self.buffer);
                            self.buffer = replay;
                            self.candidate.clear();
                            self.state = MultipartBoundaryFilterState::Preamble;
                        }
                    }
                }
                MultipartBoundaryFilterState::Headers => {
                    if let Some(position) = find_subslice(&self.buffer, b"\r\n\r\n") {
                        let consumed = position
                            .checked_add(b"\r\n\r\n".len())
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        output.extend(self.buffer.drain(..consumed));
                        self.current_part_index = self.parts_started;
                        self.parts_started = self
                            .parts_started
                            .checked_add(1)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        self.part_data_offset = 0;
                        self.state = MultipartBoundaryFilterState::Body;
                    } else {
                        let retained = trailing_marker_prefix_len(&self.buffer, b"\r\n\r\n");
                        let safe = self
                            .buffer
                            .len()
                            .checked_sub(retained)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        output.extend(self.buffer.drain(..safe));
                        return Ok(output);
                    }
                }
                MultipartBoundaryFilterState::Body => {
                    if let Some(position) = find_subslice(&self.buffer, &self.part_marker) {
                        output.extend(self.buffer.drain(..position));
                        self.part_data_offset = self
                            .part_data_offset
                            .checked_add(position)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        self.candidate
                            .extend(self.buffer.drain(..self.part_marker.len()));
                        self.state = MultipartBoundaryFilterState::PartSuffix;
                    } else {
                        let retained = trailing_marker_prefix_len(&self.buffer, &self.part_marker);
                        let safe = self
                            .buffer
                            .len()
                            .checked_sub(retained)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        output.extend(self.buffer.drain(..safe));
                        self.part_data_offset = self
                            .part_data_offset
                            .checked_add(safe)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        return Ok(output);
                    }
                }
                MultipartBoundaryFilterState::PartSuffix => match boundary_suffix(&self.buffer) {
                    BoundarySuffix::Pending => return Ok(output),
                    BoundarySuffix::Valid { consumed, closing } => {
                        output.append(&mut self.candidate);
                        output.extend(self.buffer.drain(..consumed));
                        self.state = if closing {
                            MultipartBoundaryFilterState::Done
                        } else {
                            MultipartBoundaryFilterState::Headers
                        };
                    }
                    BoundarySuffix::Invalid => {
                        if self.candidate.is_empty() {
                            self.state = MultipartBoundaryFilterState::Body;
                            continue;
                        }
                        self.restore_offsets
                            .entry(self.current_part_index)
                            .or_default()
                            .push_back(self.part_data_offset);
                        self.part_data_offset = self
                            .part_data_offset
                            .checked_add(1)
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        output.push(0);
                        let mut replay = self.candidate.drain(1..).collect::<Vec<_>>();
                        replay.append(&mut self.buffer);
                        self.buffer = replay;
                        self.candidate.clear();
                        self.state = MultipartBoundaryFilterState::Body;
                    }
                },
                MultipartBoundaryFilterState::Done => {
                    output.append(&mut self.buffer);
                    return Ok(output);
                }
            }
        }
    }
}

/// Recognizes the suffixes accepted by the pinned python-multipart parser.
///
/// Its `PART_DATA` state only completes a delimiter for immediate CRLF or a
/// closing suffix beginning with `--`; spaces and tabs remain part data.
fn boundary_suffix(input: &[u8]) -> BoundarySuffix {
    let Some(first) = input.first().copied() else {
        return BoundarySuffix::Pending;
    };
    match first {
        b'-' if input.len() == 1 => BoundarySuffix::Pending,
        b'-' if input.starts_with(b"--") => BoundarySuffix::Valid {
            consumed: 2,
            closing: true,
        },
        b'\r' if input.len() == 1 => BoundarySuffix::Pending,
        b'\r' if input.starts_with(b"\r\n") => BoundarySuffix::Valid {
            consumed: 2,
            closing: false,
        },
        _ => BoundarySuffix::Invalid,
    }
}

fn trailing_marker_prefix_len(input: &[u8], marker: &[u8]) -> usize {
    let Some(marker_prefix_len) = marker.len().checked_sub(1) else {
        return 0;
    };
    let maximum = input.len().min(marker_prefix_len);
    (1..=maximum)
        .rev()
        .find_map(|length| {
            let start = input.len().checked_sub(length)?;
            (input.get(start..) == marker.get(..length)).then_some(length)
        })
        .unwrap_or(0)
}

/// Finds a multipart delimiter across chunks while retaining only a possible
/// delimiter prefix between calls.
fn find_stream_marker(prefix: &mut Vec<u8>, input: &[u8], marker: &[u8]) -> Option<usize> {
    let marker_tail_len = marker.len().checked_sub(1)?;
    if !prefix.is_empty() {
        let prefix_len = prefix.len();
        let mut bridge = prefix.clone();
        bridge.extend_from_slice(input.get(..input.len().min(marker_tail_len))?);
        if let Some(position) =
            find_subslice(&bridge, marker).filter(|position| *position < prefix_len)
        {
            prefix.clear();
            return position.checked_add(marker.len())?.checked_sub(prefix_len);
        }
    }
    if let Some(position) = find_subslice(input, marker) {
        prefix.clear();
        return position.checked_add(marker.len());
    }

    let retained = if input.len() >= marker_tail_len {
        input
            .get(input.len().checked_sub(marker_tail_len)?..)?
            .to_vec()
    } else {
        let mut combined = std::mem::take(prefix);
        combined.extend_from_slice(input);
        combined
    };
    let max_prefix = retained.len().min(marker_tail_len);
    let matching_len = (1..=max_prefix).rev().find_map(|length| {
        let start = retained.len().checked_sub(length)?;
        (retained.get(start..) == marker.get(..length)).then_some(length)
    });
    prefix.clear();
    if let Some(length) = matching_len {
        let start = retained.len().checked_sub(length)?;
        prefix.extend_from_slice(retained.get(start..)?);
    }
    None
}

/// Extracts the callback-visible header names and values from a completed
/// header block. python-multipart skips leading spaces after the colon while
/// retaining other value bytes, including trailing whitespace.
type CallbackHeader = (Vec<u8>, Vec<u8>);

fn callback_headers(header_block: &[u8]) -> Result<Vec<CallbackHeader>, MultipartFormParseError> {
    let mut headers = Vec::new();
    let mut offset = 0;
    while let Some(relative_end) = find_subslice(
        header_block
            .get(offset..)
            .ok_or_else(multipart_arithmetic_overflow)?,
        b"\r\n",
    ) {
        if relative_end == 0 {
            break;
        }
        let line_end = offset
            .checked_add(relative_end)
            .ok_or_else(multipart_arithmetic_overflow)?;
        let line = header_block
            .get(offset..line_end)
            .ok_or_else(multipart_arithmetic_overflow)?;
        if let Some(colon) = line.iter().position(|byte| *byte == b':') {
            let mut value_start = colon
                .checked_add(1)
                .ok_or_else(multipart_arithmetic_overflow)?;
            while line.get(value_start) == Some(&b' ') {
                value_start = value_start
                    .checked_add(1)
                    .ok_or_else(multipart_arithmetic_overflow)?;
            }
            headers.push((
                line[..colon].to_ascii_lowercase(),
                line[value_start..].to_vec(),
            ));
        }
        offset = line_end
            .checked_add(2)
            .ok_or_else(multipart_arithmetic_overflow)?;
    }
    Ok(headers)
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
    bytes_emitted: usize,
}

impl MultipartFormParseError {
    /// Returns the error message exposed by Starlette's request form parser.
    #[must_use]
    pub fn message(&self) -> String {
        match self {
            Self::MissingBoundary => "Missing boundary in multipart.".to_owned(),
            Self::BoundaryTooLong { length } => {
                format!(
                    "Boundary length {length} exceeds maximum of {PYTHON_MULTIPART_MAX_BOUNDARY_LENGTH}"
                )
            }
            Self::HeaderCountExceeded { .. } => "Maximum header count exceeded".to_owned(),
            Self::HeaderSizeExceeded { .. } => "Maximum header size exceeded".to_owned(),
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
    // Starlette 1.6.0 parses Content-Type options into a dict, so the final
    // duplicate `boundary` parameter wins. `multer::parse_boundary` instead
    // returns the first occurrence through `mime::Mime::get_param`.
    let boundary = content_type_parameter(content_type, "boundary")
        .ok_or(MultipartFormParseError::MissingBoundary)?;
    let length = boundary.chars().count();
    if length > PYTHON_MULTIPART_MAX_BOUNDARY_LENGTH {
        return Err(MultipartFormParseError::BoundaryTooLong { length });
    }
    Ok(boundary)
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

fn collect_multipart_parts(
    events: Vec<MultipartFormEvent>,
) -> Result<Vec<MultipartPart>, MultipartFormParseError> {
    let mut parts = Vec::new();
    for event in events {
        match event {
            MultipartFormEvent::TextField { part_index, part } => {
                let index = part_index_slot(&mut parts, part_index)?;
                *index = Some(part);
            }
            MultipartFormEvent::FileStarted {
                part_index,
                name,
                filename,
                headers,
            } => {
                let index = part_index_slot(&mut parts, part_index)?;
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
    Ok(parts.into_iter().flatten().collect())
}

fn part_index_slot(
    parts: &mut Vec<Option<MultipartPart>>,
    part_index: usize,
) -> Result<&mut Option<MultipartPart>, MultipartFormParseError> {
    let required_len = part_index
        .checked_add(1)
        .ok_or_else(multipart_arithmetic_overflow)?;
    parts.resize_with(required_len, || None);
    parts
        .get_mut(part_index)
        .ok_or_else(multipart_arithmetic_overflow)
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
            boundary_filter: MultipartBoundaryFilter::new(&boundary),
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
        let filtered = self.boundary_filter.push(&chunk)?;
        self.forward_filtered_chunk(&filtered)?;
        self.process_available()
    }

    fn forward_filtered_chunk(&mut self, chunk: &[u8]) -> Result<(), MultipartFormParseError> {
        if chunk.is_empty() {
            return Ok(());
        }
        let capture_error = self.raw_header_capture.push(chunk).err();
        let forwarded_len = capture_error
            .as_ref()
            .map_or(chunk.len(), |(_, consumed)| *consumed);
        if forwarded_len > 0 {
            self.sender
                .unbounded_send(Ok(Bytes::copy_from_slice(&chunk[..forwarded_len])))
                .map_err(|_| MultipartFormParseError::Malformed {
                    message: "multipart parser input stream is closed".to_owned(),
                })?;
        }
        if let Some((error, _)) = capture_error {
            return Err(error);
        }
        Ok(())
    }

    /// Finishes the request-body stream and returns its parsed parts.
    pub fn finish(mut self) -> Result<Vec<MultipartPart>, MultipartFormParseError> {
        self.finish_events()?;
        collect_multipart_parts(self.drain_events())
    }

    /// Finishes the request-body stream while retaining events for draining.
    pub fn finish_events(&mut self) -> Result<(), MultipartFormParseError> {
        let filtered = self.boundary_filter.finish()?;
        self.forward_filtered_chunk(&filtered)?;
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
                        let Some((part_index, chunk_start)) = self
                            .active_part
                            .as_ref()
                            .map(|part| (part.part_index, part.bytes_emitted))
                        else {
                            return Err(MultipartFormParseError::Malformed {
                                message: "multipart parser lost the active part".to_owned(),
                            });
                        };
                        let chunk_end = chunk_start
                            .checked_add(chunk.len())
                            .ok_or_else(multipart_arithmetic_overflow)?;
                        let restore_offsets = self.boundary_filter.take_restore_offsets(
                            part_index,
                            chunk_start,
                            chunk_end,
                        );
                        let restored_chunk = if restore_offsets.is_empty() {
                            None
                        } else {
                            let mut data = chunk.to_vec();
                            for offset in restore_offsets {
                                let chunk_offset = offset
                                    .checked_sub(chunk_start)
                                    .ok_or_else(multipart_arithmetic_overflow)?;
                                let byte = data
                                    .get_mut(chunk_offset)
                                    .ok_or_else(multipart_arithmetic_overflow)?;
                                *byte = b'\r';
                            }
                            Some(data)
                        };
                        let chunk_data = restored_chunk.as_deref().unwrap_or(chunk.as_ref());
                        let Some(part) = self.active_part.as_mut() else {
                            return Err(MultipartFormParseError::Malformed {
                                message: "multipart parser lost the active part".to_owned(),
                            });
                        };
                        part.bytes_emitted = chunk_end;
                        if part.filename.is_none()
                            && part_size_exceeded(
                                part.data.len(),
                                chunk_data.len(),
                                self.max_part_size,
                            )
                        {
                            let max_part_size_kb = self
                                .max_part_size
                                .checked_div(1024)
                                .ok_or_else(multipart_arithmetic_overflow)?;
                            return Err(MultipartFormParseError::PartTooLarge { max_part_size_kb });
                        }
                        if part.filename.is_none() {
                            part.data.extend_from_slice(chunk_data);
                        } else {
                            part.size = part
                                .size
                                .checked_add(chunk_data.len())
                                .ok_or_else(multipart_arithmetic_overflow)?;
                            self.events.push_back(MultipartFormEvent::FileChunk {
                                part_index: part.part_index,
                                data: chunk_data.to_vec(),
                            });
                        }
                    }
                    Poll::Ready(Some(Err(error))) => {
                        if is_incomplete_multipart_error(&error) {
                            self.discard_incomplete_active_part();
                            return Ok(());
                        }
                        return Err(MultipartFormParseError::Malformed {
                            message: error.to_string(),
                        });
                    }
                    Poll::Ready(None) => {
                        self.active_field = None;
                        // Multer has found the boundary prefix but has not
                        // consumed its suffix yet. Keep this part provisional
                        // until `poll_next_field` validates the following
                        // `\r\n` or `--` bytes.
                    }
                    Poll::Pending => return Ok(()),
                }
                continue;
            }

            match self.multipart.poll_next_field(&mut context) {
                Poll::Ready(Ok(Some(field))) => {
                    if self.active_part.is_some() {
                        self.complete_active_part()?;
                    }
                    self.start_part(field)?;
                }
                Poll::Ready(Ok(None)) => {
                    if self.active_part.is_some() {
                        self.complete_active_part()?;
                    }
                    self.complete = true;
                    return Ok(());
                }
                Poll::Ready(Err(error)) => {
                    if matches!(error, MulterError::IncompleteHeaders) && self.active_part.is_some()
                    {
                        // An ordinary part separator was validated before
                        // Multer began reading the next part's headers. Keep
                        // the completed part and omit only those incomplete
                        // trailing headers, as python-multipart does.
                        self.complete_active_part()?;
                    }
                    if is_incomplete_multipart_error(&error) {
                        self.discard_incomplete_active_part();
                        return Ok(());
                    }
                    return Err(MultipartFormParseError::Malformed {
                        message: error.to_string(),
                    });
                }
                Poll::Pending => return Ok(()),
            }
        }
    }

    fn discard_incomplete_active_part(&mut self) {
        if let Some(part) = self.active_part.take() {
            let part_index = part.part_index;
            self.events.retain(|event| {
                !matches!(
                    event,
                    MultipartFormEvent::TextField { part_index: event_index, .. }
                        | MultipartFormEvent::FileStarted { part_index: event_index, .. }
                        | MultipartFormEvent::FileChunk { part_index: event_index, .. }
                        | MultipartFormEvent::FileFinished { part_index: event_index, .. }
                        if *event_index == part_index
                )
            });
        }
        self.active_field = None;
        self.complete = true;
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
            self.files = self
                .files
                .checked_add(1)
                .ok_or_else(multipart_arithmetic_overflow)?;
            if self.files as f64 > self.max_files {
                return Err(MultipartFormParseError::TooManyFiles {
                    maximum: self.max_files_display.clone(),
                });
            }
        } else {
            self.fields = self
                .fields
                .checked_add(1)
                .ok_or_else(multipart_arithmetic_overflow)?;
            if self.fields as f64 > self.max_fields {
                return Err(MultipartFormParseError::TooManyFields {
                    maximum: self.max_fields_display.clone(),
                });
            }
        }

        let part_index = self.parts_started;
        self.parts_started = self
            .parts_started
            .checked_add(1)
            .ok_or_else(multipart_arithmetic_overflow)?;
        self.active_part = Some(MultipartPartBuilder {
            part_index,
            name,
            filename,
            headers,
            data: Vec::new(),
            size: 0,
            bytes_emitted: 0,
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

fn is_incomplete_multipart_error(error: &MulterError) -> bool {
    matches!(
        error,
        MulterError::IncompleteFieldData { .. }
            | MulterError::IncompleteHeaders
            | MulterError::IncompleteStream
    )
}

fn part_size_exceeded(current_size: usize, chunk_size: usize, limit: i64) -> bool {
    let (Ok(current_size), Ok(chunk_size)) =
        (i128::try_from(current_size), i128::try_from(chunk_size))
    else {
        return true;
    };
    // An overflow here is necessarily above every i64 limit Starlette accepts.
    current_size
        .checked_add(chunk_size)
        .is_none_or(|size| size > i128::from(limit))
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
            raw_value
                .strip_prefix('"')
                .and_then(|value| value.strip_suffix('"'))?
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
    let mut even_backslashes = true;
    let mut characters = header.char_indices().peekable();
    while let Some((index, character)) = characters.next() {
        match character {
            '"' => {
                if even_backslashes {
                    quoted = !quoted;
                }
                even_backslashes = true;
            }
            '\\' => even_backslashes = !even_backslashes,
            ';' if !quoted => {
                segments.push(&header[segment_start..index]);
                segment_start = characters
                    .peek()
                    .map_or(header.len(), |(next_index, _)| *next_index);
                even_backslashes = true;
            }
            _ => even_backslashes = true,
        }
    }
    segments.push(&header[segment_start..]);
    segments
}

fn request_charset(content_type: &str) -> String {
    content_type_parameter(content_type, "charset").unwrap_or_else(|| "utf-8".to_owned())
}

/// Parses one Content-Type parameter with python-multipart's last-value rule.
fn content_type_parameter(content_type: &str, wanted: &str) -> Option<String> {
    split_disposition_parameters(content_type)
        .into_iter()
        .skip(1)
        .filter_map(|parameter| parameter.split_once('='))
        .filter_map(|(name, value)| {
            let name = name.trim().to_ascii_lowercase();
            if name.contains('*') || name != wanted {
                return None;
            }
            Some(unquote_parameter(value.trim()))
        })
        .next_back()
}

fn unquote_parameter(value: &str) -> String {
    if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
        value
            .strip_prefix('"')
            .and_then(|value| value.strip_suffix('"'))
            .unwrap_or(value)
            .replace("\\\\", "\\")
            .replace("\\\"", "\"")
    } else {
        value.to_owned()
    }
}

fn user_safe_decode(bytes: &[u8], charset: &str) -> String {
    // Python normalizes codec names by collapsing punctuation and whitespace
    // to underscores before lookup (for example, `'utf-8'` becomes `utf_8`).
    // Apply that normalization before resolving a WHATWG label so parameters
    // accepted by `bytes.decode()` are not incorrectly treated as unknown.
    let charset = normalize_python_codec_name(charset);

    // Latin-1 maps every byte directly. For ASCII, Starlette decodes strictly
    // and falls back to Latin-1 on non-ASCII bytes, so both codecs have the
    // same final output even though encoding_rs aliases ASCII to Windows-1252.
    if is_iso_8859_1_charset(&charset) || is_ascii_charset(&charset) {
        return bytes.iter().map(|byte| char::from(*byte)).collect();
    }

    if is_cp437_charset(&charset) {
        return bytes
            .iter()
            .map(|byte| {
                if byte.is_ascii() {
                    char::from(*byte)
                } else {
                    let Some(index) = usize::from(*byte).checked_sub(usize::from(0x80_u8)) else {
                        return char::from(*byte);
                    };
                    CP437_HIGH
                        .get(index)
                        .copied()
                        .unwrap_or_else(|| char::from(*byte))
                }
            })
            .collect();
    }

    if is_generic_utf16_charset(&charset) {
        return decode_generic_utf16(bytes)
            .unwrap_or_else(|| bytes.iter().map(|byte| char::from(*byte)).collect());
    }

    let label = charset.replace('_', "-");
    if let Some(encoding) = Encoding::for_label(label.as_bytes()) {
        let (decoded, had_errors) = encoding.decode_without_bom_handling(bytes);
        if !had_errors {
            return decoded.into_owned();
        }
    }
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

const CP437_HIGH: [char; 128] = [
    'Ç', 'ü', 'é', 'â', 'ä', 'à', 'å', 'ç', 'ê', 'ë', 'è', 'ï', 'î', 'ì', 'Ä', 'Å', 'É', 'æ', 'Æ',
    'ô', 'ö', 'ò', 'û', 'ù', 'ÿ', 'Ö', 'Ü', '¢', '£', '¥', '₧', 'ƒ', 'á', 'í', 'ó', 'ú', 'ñ', 'Ñ',
    'ª', 'º', '¿', '⌐', '¬', '½', '¼', '¡', '«', '»', '░', '▒', '▓', '│', '┤', '╡', '╢', '╖', '╕',
    '╣', '║', '╗', '╝', '╜', '╛', '┐', '└', '┴', '┬', '├', '─', '┼', '╞', '╟', '╚', '╔', '╩', '╦',
    '╠', '═', '╬', '╧', '╨', '╤', '╥', '╙', '╘', '╒', '╓', '╫', '╪', '┘', '┌', '█', '▄', '▌', '▐',
    '▀', 'α', 'ß', 'Γ', 'π', 'Σ', 'σ', 'µ', 'τ', 'Φ', 'Θ', 'Ω', 'δ', '∞', 'φ', 'ε', '∩', '≡', '±',
    '≥', '≤', '⌠', '⌡', '÷', '≈', '°', '∙', '·', '√', 'ⁿ', '²', '■', '\u{00a0}',
];

fn is_cp437_charset(charset: &str) -> bool {
    matches!(charset, "437" | "cp437" | "cspc8codepage437" | "ibm437")
}

fn normalize_python_codec_name(codec: &str) -> String {
    let mut normalized = String::with_capacity(codec.len());
    let mut punctuation = false;
    for character in codec.chars() {
        if character.is_alphanumeric() || character == '.' {
            if punctuation && !normalized.is_empty() {
                normalized.push('_');
            }
            if character.is_ascii() {
                normalized.push(character.to_ascii_lowercase());
            }
            punctuation = false;
        } else {
            punctuation = true;
        }
    }
    normalized
}

fn is_generic_utf16_charset(charset: &str) -> bool {
    let normalized = charset.trim().to_ascii_lowercase().replace('_', "-");
    matches!(normalized.as_str(), "utf-16" | "utf16")
}

fn decode_generic_utf16(bytes: &[u8]) -> Option<String> {
    // Python's generic utf-16 codec uses a BOM to select byte order, then
    // falls back to the native byte order when the BOM is absent. encoding_rs
    // maps the generic label to UTF-16LE, so select that behavior explicitly
    // and fall back when the source codec would reject the bytes.
    let (encoding, content) = if let Some(content) = bytes.strip_prefix(b"\xFF\xFE") {
        (UTF_16LE, content)
    } else if let Some(content) = bytes.strip_prefix(b"\xFE\xFF") {
        (UTF_16BE, content)
    } else {
        #[cfg(target_endian = "little")]
        {
            (UTF_16LE, bytes)
        }
        #[cfg(target_endian = "big")]
        {
            (UTF_16BE, bytes)
        }
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
