//! Rust-owned multipart/form-data parsing for the Python request boundary.

use std::convert::Infallible;
use std::pin::Pin;
use std::task::{Context, Poll};

use encoding_rs::Encoding;
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

/// Incrementally parses multipart/form-data chunks while retaining completed
/// fields for construction of Starlette-compatible FormData values.
///
/// Text-part size limits are enforced as bytes arrive, so callers can stop
/// requesting the input stream immediately when a part exceeds its limit.
pub struct MultipartFormParser {
    sender: mpsc::UnboundedSender<Result<Bytes, Infallible>>,
    multipart: Multipart<'static>,
    active_field: Option<Field<'static>>,
    active_part: Option<MultipartPartBuilder>,
    parts: Vec<MultipartPart>,
    charset: String,
    max_files: f64,
    max_files_display: String,
    max_fields: f64,
    max_fields_display: String,
    max_part_size: i64,
    files: usize,
    fields: usize,
    complete: bool,
}

struct MultipartPartBuilder {
    name: String,
    filename: Option<String>,
    headers: Vec<(Vec<u8>, Vec<u8>)>,
    data: Vec<u8>,
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
            multipart: Multipart::new(receiver, boundary),
            active_field: None,
            active_part: None,
            parts: Vec::new(),
            charset: request_charset(content_type),
            max_files,
            max_files_display: max_files_display.to_owned(),
            max_fields,
            max_fields_display: max_fields_display.to_owned(),
            max_part_size,
            files: 0,
            fields: 0,
            complete: false,
        })
    }

    /// Feeds one request-body chunk into the parser.
    pub fn push_chunk(&mut self, chunk: Vec<u8>) -> Result<(), MultipartFormParseError> {
        if self.complete || chunk.is_empty() {
            return Ok(());
        }
        self.sender
            .unbounded_send(Ok(Bytes::from(chunk)))
            .map_err(|_| MultipartFormParseError::Malformed {
                message: "multipart parser input stream is closed".to_owned(),
            })?;
        self.process_available()
    }

    /// Finishes the request-body stream and returns its parsed parts.
    pub fn finish(mut self) -> Result<Vec<MultipartPart>, MultipartFormParseError> {
        self.sender.close_channel();
        self.process_available()?;
        Ok(self.parts)
    }

    fn process_available(&mut self) -> Result<(), MultipartFormParseError> {
        let mut context = Context::from_waker(futures::task::noop_waker_ref());
        loop {
            if self.complete {
                return Ok(());
            }
            if let Some(field) = self.active_field.as_mut() {
                match Pin::new(field).poll_next(&mut context) {
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
                        part.data.extend_from_slice(&chunk);
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
        let name = field
            .name()
            .ok_or(MultipartFormParseError::MissingName)?
            .to_owned();
        let filename = field.file_name().map(str::to_owned);
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

        let headers = field
            .headers()
            .iter()
            .map(|(name, value)| {
                (
                    name.as_str().as_bytes().to_ascii_lowercase(),
                    value.as_bytes().to_vec(),
                )
            })
            .collect();
        self.active_part = Some(MultipartPartBuilder {
            name,
            filename,
            headers,
            data: Vec::new(),
        });
        self.active_field = Some(field);
        Ok(())
    }

    fn complete_active_part(&mut self) -> Result<(), MultipartFormParseError> {
        let Some(part) = self.active_part.take() else {
            return Err(MultipartFormParseError::Malformed {
                message: "multipart parser lost the completed part".to_owned(),
            });
        };
        let text = part
            .filename
            .is_none()
            .then(|| user_safe_decode(&part.data, &self.charset));
        self.parts.push(MultipartPart {
            name: part.name,
            filename: part.filename,
            headers: part.headers,
            data: part.data,
            text,
        });
        Ok(())
    }
}

fn part_size_exceeded(current_size: usize, chunk_size: usize, limit: i64) -> bool {
    let current_size = i128::try_from(current_size).unwrap_or(i128::MAX);
    let chunk_size = i128::try_from(chunk_size).unwrap_or(i128::MAX);
    current_size.saturating_add(chunk_size) > i128::from(limit)
}

fn request_charset(content_type: &str) -> String {
    content_type
        .split(';')
        .skip(1)
        .filter_map(|parameter| parameter.split_once('='))
        .find(|(name, _)| name.trim().eq_ignore_ascii_case("charset"))
        .map(|(_, value)| value.trim().trim_matches(['"', '\'']).to_owned())
        .filter(|charset| !charset.is_empty())
        .unwrap_or_else(|| "utf-8".to_owned())
}

fn user_safe_decode(bytes: &[u8], charset: &str) -> String {
    if let Some(encoding) = Encoding::for_label(charset.as_bytes()) {
        let (decoded, had_errors) = encoding.decode_without_bom_handling(bytes);
        if !had_errors {
            return decoded.into_owned();
        }
    }
    bytes.iter().map(|byte| char::from(*byte)).collect()
}
