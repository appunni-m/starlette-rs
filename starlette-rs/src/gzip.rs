//! Rust-owned gzip stream compression for ASGI response bodies.
//!
//! The compressor preserves one zlib stream across response chunks. Non-final
//! chunks are flushed with `Z_SYNC_FLUSH`, allowing each emitted chunk to be
//! consumed before the response finishes. The final call writes the gzip
//! trailer and permanently finishes the stream.

use std::error::Error;
use std::fmt::{self, Display, Formatter};
use std::io;

use flate2::{Compress, CompressError, Compression, FlushCompress, Status};

/// Raw ASGI header pair, retaining original bytes and order.
pub type GzipHeader = (Vec<u8>, Vec<u8>);

/// Starlette-compatible defaults for excluded GZip content types.
pub const DEFAULT_EXCLUDED_CONTENT_TYPES: [&str; 13] = [
    "application/gzip",
    "application/x-gzip",
    "application/zip",
    "audio/*",
    "font/woff",
    "font/woff2",
    "image/avif",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/event-stream",
    "video/*",
];

/// A stateful gzip encoder that returns newly produced bytes for each chunk.
#[derive(Debug)]
pub struct GzipCompressor {
    compressor: Option<Compress>,
    finished: bool,
}

impl GzipCompressor {
    /// Creates a gzip stream at the compression level accepted by Python zlib.
    ///
    /// `-1` selects zlib's default compression level; `0` through `9` select
    /// the corresponding explicit level.
    ///
    /// # Errors
    ///
    /// Returns [`GzipCompressionError::InvalidCompressionLevel`] outside the
    /// range accepted by Python's `zlib.compressobj`.
    #[must_use = "compression construction can fail for invalid levels"]
    pub fn new(compresslevel: i32) -> Result<Self, GzipCompressionError> {
        let compression = match compresslevel {
            -1 => Compression::default(),
            0..=9 => Compression::new(
                u32::try_from(compresslevel)
                    .map_err(|_| GzipCompressionError::InvalidCompressionLevel(compresslevel))?,
            ),
            _ => return Err(GzipCompressionError::InvalidCompressionLevel(compresslevel)),
        };

        Ok(Self {
            compressor: Some(Compress::new_gzip(compression, 15)),
            finished: false,
        })
    }

    /// Compresses one response-body chunk and returns bytes produced by it.
    ///
    /// When `more_body` is true, the compressor performs a sync flush so the
    /// returned bytes can be delivered before the next ASGI body event. When
    /// it is false, the gzip trailer is emitted and the stream is finished.
    ///
    /// # Errors
    ///
    /// Returns [`GzipCompressionError::Finished`] after a previous final
    /// chunk, or an error if zlib rejects an operation, reports an invalid
    /// counter delta, or makes no progress.
    pub fn compress_chunk(
        &mut self,
        body: &[u8],
        more_body: bool,
    ) -> Result<Vec<u8>, GzipCompressionError> {
        if self.finished {
            return Err(GzipCompressionError::Finished);
        }

        let mut output = self.compress_all(body, FlushCompress::None)?;
        if more_body {
            output.extend(self.compress_all(&[], FlushCompress::Sync)?);
        } else {
            output.extend(self.compress_all(&[], FlushCompress::Finish)?);
            self.compressor = None;
            self.finished = true;
        }
        Ok(output)
    }

    fn compress_all(
        &mut self,
        input: &[u8],
        flush: FlushCompress,
    ) -> Result<Vec<u8>, GzipCompressionError> {
        let mut output = Vec::new();
        let mut input_offset = 0;
        let mut buffer = [0_u8; COMPRESSION_BUFFER_SIZE];

        loop {
            let compressor = self
                .compressor
                .as_mut()
                .ok_or(GzipCompressionError::Finished)?;
            let before_in = compressor.total_in();
            let before_out = compressor.total_out();
            let status = compressor
                .compress(&input[input_offset..], &mut buffer, flush)
                .map_err(GzipCompressionError::Compression)?;
            let consumed = counter_delta(compressor.total_in(), before_in)?;
            let produced = counter_delta(compressor.total_out(), before_out)?;
            input_offset += consumed;
            output.extend_from_slice(&buffer[..produced]);

            match flush {
                FlushCompress::None if input_offset == input.len() => break,
                FlushCompress::Sync if input_offset == input.len() && produced < buffer.len() => {
                    break;
                }
                FlushCompress::Finish if status == Status::StreamEnd => break,
                _ if consumed == 0 && produced == 0 => {
                    return Err(GzipCompressionError::Io(io::Error::new(
                        io::ErrorKind::WriteZero,
                        "gzip compressor made no progress",
                    )));
                }
                _ => {}
            }
        }

        Ok(output)
    }
}

fn counter_delta(current: u64, previous: u64) -> Result<usize, GzipCompressionError> {
    current
        .checked_sub(previous)
        .and_then(|delta| usize::try_from(delta).ok())
        .ok_or_else(|| {
            GzipCompressionError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "gzip compressor reported an invalid counter delta",
            ))
        })
}

const COMPRESSION_BUFFER_SIZE: usize = 16 * 1024;

/// An error returned while constructing or advancing a gzip stream.
#[derive(Debug)]
pub enum GzipCompressionError {
    /// The level is outside Python zlib's accepted range of -1 through 9.
    InvalidCompressionLevel(i32),
    /// The compression stream has already emitted its final chunk.
    Finished,
    /// The compression backend rejected a zlib operation.
    Compression(CompressError),
    /// Compression reported an I/O failure or invalid counter delta.
    Io(io::Error),
}

impl Display for GzipCompressionError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCompressionLevel(level) => {
                write!(formatter, "invalid gzip compression level: {level}")
            }
            Self::Finished => formatter.write_str("gzip stream has already finished"),
            Self::Compression(error) => write!(formatter, "gzip compression failed: {error:?}"),
            Self::Io(error) => write!(formatter, "gzip compression failed: {error}"),
        }
    }
}

impl Error for GzipCompressionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Compression(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::InvalidCompressionLevel(_) | Self::Finished => None,
        }
    }
}

/// GZip middleware settings, including its ASGI streaming thresholds.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GzipConfig {
    minimum_size: i64,
    compresslevel: i32,
    thread_minimum_size: i64,
    exclude_content_types: Vec<String>,
}

impl Default for GzipConfig {
    fn default() -> Self {
        Self::new(
            500,
            9,
            128 * 1024,
            DEFAULT_EXCLUDED_CONTENT_TYPES.map(String::from),
        )
    }
}

impl GzipConfig {
    /// Creates a GZip middleware policy from Starlette-compatible settings.
    ///
    /// Content type parameters and surrounding whitespace are removed and
    /// configured values are lowercased, matching Starlette's normalizer.
    #[must_use]
    pub fn new(
        minimum_size: i64,
        compresslevel: i32,
        thread_minimum_size: i64,
        exclude_content_types: impl IntoIterator<Item = String>,
    ) -> Self {
        let exclude_content_types = exclude_content_types
            .into_iter()
            .map(|content_type| normalize_content_type(&content_type))
            .collect();
        Self {
            minimum_size,
            compresslevel,
            thread_minimum_size,
            exclude_content_types,
        }
    }

    /// Returns whether the first `Accept-Encoding` header contains `gzip`.
    ///
    /// Starlette intentionally uses a substring check here; quality values
    /// are not interpreted.
    #[must_use]
    pub fn accepts_gzip(request_headers: &[GzipHeader]) -> bool {
        request_headers
            .iter()
            .find(|(name, _)| name == b"accept-encoding")
            .is_some_and(|(_, value)| value.windows(4).any(|window| window == b"gzip"))
    }

    /// Creates the per-request response transformer for these settings.
    #[must_use]
    pub fn responder(&self, request_headers: &[GzipHeader]) -> GzipResponder {
        GzipResponder::new(self.clone(), Self::accepts_gzip(request_headers))
    }
}

/// A response-start event buffered while GZip middleware inspects headers.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GzipResponseStart {
    /// HTTP response status code.
    pub status: u16,
    /// Ordered raw response headers.
    pub headers: Vec<GzipHeader>,
}

/// The start event, if one is released, and one transformed body event.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GzipBodyOutput {
    /// Buffered response start released before this body, when applicable.
    pub response_start: Option<GzipResponseStart>,
    /// The body bytes to send for the current event.
    pub body: Vec<u8>,
}

/// Stateful response-side GZip and identity transformation for one ASGI call.
#[derive(Debug)]
pub struct GzipResponder {
    config: GzipConfig,
    gzip_enabled: bool,
    response_start: Option<GzipResponseStart>,
    content_encoding_set: bool,
    partial_response: bool,
    content_type_is_excluded: bool,
    started: bool,
    compressor: Option<GzipCompressor>,
}

impl GzipResponder {
    fn new(config: GzipConfig, gzip_enabled: bool) -> Self {
        Self {
            config,
            gzip_enabled,
            response_start: None,
            content_encoding_set: false,
            partial_response: false,
            content_type_is_excluded: false,
            started: false,
            compressor: None,
        }
    }

    /// Buffers a response-start event and records its compression exclusions.
    pub fn response_start(&mut self, status: u16, headers: Vec<GzipHeader>) {
        self.content_encoding_set = has_header(&headers, b"content-encoding");
        self.partial_response = status == 206;
        self.content_type_is_excluded =
            content_type_is_excluded(&headers, &self.config.exclude_content_types);
        self.response_start = Some(GzipResponseStart { status, headers });
    }

    /// Returns whether this body event follows Starlette's worker-thread path.
    ///
    /// The caller remains responsible for scheduling `response_body` through
    /// the active ASGI framework's worker-thread facility.
    #[must_use]
    pub fn should_offload(&self, body_length: usize, more_body: bool) -> bool {
        if !self.gzip_enabled || (body_length as i128) < i128::from(self.config.thread_minimum_size)
        {
            return false;
        }
        if self.content_encoding_set || self.partial_response || self.content_type_is_excluded {
            return false;
        }
        if !self.started
            && !more_body
            && (body_length as i128) < i128::from(self.config.minimum_size)
        {
            return false;
        }
        true
    }

    /// Transforms one ASGI response-body event.
    ///
    /// On the first body event this may release the buffered response-start
    /// event before returning the body. Later events return only their body.
    /// `more_body` controls zlib sync flushing and gzip finalization.
    ///
    /// # Errors
    ///
    /// Returns a compression error if the configured level is invalid when
    /// compression is first required, or if the backend fails.
    pub fn response_body(
        &mut self,
        body: &[u8],
        more_body: bool,
    ) -> Result<GzipBodyOutput, GzipCompressionError> {
        if self.content_encoding_set || self.partial_response || self.content_type_is_excluded {
            let response_start = if self.started {
                None
            } else {
                self.started = true;
                self.response_start_output()
            };
            return Ok(GzipBodyOutput {
                response_start,
                body: body.to_vec(),
            });
        }

        if self.started {
            return Ok(GzipBodyOutput {
                response_start: None,
                body: self.apply_compression(body, more_body)?,
            });
        }

        self.started = true;
        if !more_body && (body.len() as i128) < i128::from(self.config.minimum_size) {
            return Ok(GzipBodyOutput {
                response_start: self.response_start_output(),
                body: body.to_vec(),
            });
        }

        let compressed = self.apply_compression(body, more_body)?;
        let mut start = self.response_start_output();
        if let Some(response_start) = start.as_mut() {
            add_vary_header(&mut response_start.headers);
            if compressed != body {
                set_header(&mut response_start.headers, b"content-encoding", b"gzip");
                if more_body {
                    delete_header(&mut response_start.headers, b"content-length");
                } else {
                    set_header(
                        &mut response_start.headers,
                        b"content-length",
                        compressed.len().to_string().as_bytes(),
                    );
                }
            }
        }

        Ok(GzipBodyOutput {
            response_start: start,
            body: compressed,
        })
    }

    /// Returns the buffered response-start event for a path-send response.
    ///
    /// Starlette sends the start event and `http.response.pathsend` unchanged
    /// without attempting to gzip the file.
    pub fn pathsend(&mut self) -> Option<GzipResponseStart> {
        self.response_start.clone()
    }

    fn response_start_output(&self) -> Option<GzipResponseStart> {
        self.response_start.clone()
    }

    fn apply_compression(
        &mut self,
        body: &[u8],
        more_body: bool,
    ) -> Result<Vec<u8>, GzipCompressionError> {
        if !self.gzip_enabled {
            return Ok(body.to_vec());
        }
        if self.compressor.is_none() {
            self.compressor = Some(GzipCompressor::new(self.config.compresslevel)?);
        }
        self.compressor
            .as_mut()
            .ok_or(GzipCompressionError::Finished)?
            .compress_chunk(body, more_body)
    }
}

fn normalize_content_type(content_type: &str) -> String {
    content_type
        .split_once(';')
        .map_or(content_type, |(base, _)| base)
        .trim()
        .to_ascii_lowercase()
}

fn has_header(headers: &[GzipHeader], name: &[u8]) -> bool {
    headers.iter().any(|(key, _)| key == name)
}

fn content_type_is_excluded(headers: &[GzipHeader], excluded: &[String]) -> bool {
    let Some((_, value)) = headers.iter().find(|(key, _)| key == b"content-type") else {
        return false;
    };
    let media_type = value.split(|byte| *byte == b';').next().unwrap_or_default();
    let media_type = trim_ascii(media_type).to_ascii_lowercase();
    let top_level = media_type
        .split(|byte| *byte == b'/')
        .next()
        .unwrap_or_default();
    let wildcard = [top_level, b"/*"].concat();

    excluded.iter().any(|excluded_type| {
        excluded_type.as_bytes() == media_type || excluded_type.as_bytes() == wildcard
    })
}

fn trim_ascii(mut value: &[u8]) -> &[u8] {
    while value.first().is_some_and(u8::is_ascii_whitespace) {
        value = &value[1..];
    }
    while value.last().is_some_and(u8::is_ascii_whitespace) {
        value = &value[..value.len() - 1];
    }
    value
}

fn add_vary_header(headers: &mut Vec<GzipHeader>) {
    let vary = headers
        .iter()
        .find(|(key, _)| key == b"vary")
        .map(|(_, value)| value.as_slice());
    let value = match vary {
        Some(existing) => [existing, b", Accept-Encoding"].concat(),
        None => b"Accept-Encoding".to_vec(),
    };
    set_header(headers, b"vary", &value);
}

fn set_header(headers: &mut Vec<GzipHeader>, name: &[u8], value: &[u8]) {
    let found_indexes = headers
        .iter()
        .enumerate()
        .filter_map(|(index, (key, _))| (key == name).then_some(index));
    let indexes = found_indexes.collect::<Vec<_>>();
    if let Some(first_index) = indexes.first().copied() {
        headers[first_index].1 = value.to_vec();
        for index in indexes.into_iter().skip(1).rev() {
            headers.remove(index);
        }
    } else {
        headers.push((name.to_vec(), value.to_vec()));
    }
}

fn delete_header(headers: &mut Vec<GzipHeader>, name: &[u8]) {
    headers.retain(|(key, _)| key != name);
}
