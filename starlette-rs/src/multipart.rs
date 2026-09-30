//! Rust-owned multipart/form-data parsing for the Python request boundary.

use std::convert::Infallible;

use encoding_rs::Encoding;
use futures::{executor::block_on, stream};
use multer::bytes::Bytes;
use multer::{Multipart, parse_boundary};

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
    let boundary = multipart_boundary(content_type)?;
    let stream = stream::iter([Ok::<Bytes, Infallible>(Bytes::copy_from_slice(body))]);
    let mut multipart = Multipart::new(stream, boundary);
    let charset = request_charset(content_type);

    block_on(async {
        let mut parts = Vec::new();
        let mut files = 0usize;
        let mut fields = 0usize;
        while let Some(field) =
            multipart
                .next_field()
                .await
                .map_err(|error| MultipartFormParseError::Malformed {
                    message: error.to_string(),
                })?
        {
            let name = field
                .name()
                .ok_or(MultipartFormParseError::MissingName)?
                .to_owned();
            let filename = field.file_name().map(str::to_owned);
            if filename.is_some() {
                files += 1;
                if files as f64 > max_files {
                    return Err(MultipartFormParseError::TooManyFiles {
                        maximum: max_files_display.to_owned(),
                    });
                }
            } else {
                fields += 1;
                if fields as f64 > max_fields {
                    return Err(MultipartFormParseError::TooManyFields {
                        maximum: max_fields_display.to_owned(),
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
            let data = field
                .bytes()
                .await
                .map_err(|error| MultipartFormParseError::Malformed {
                    message: error.to_string(),
                })?
                .to_vec();
            if filename.is_none() && data.len() as i128 > i128::from(max_part_size) {
                return Err(MultipartFormParseError::PartTooLarge {
                    max_part_size_kb: max_part_size / 1024,
                });
            }

            let text = filename
                .is_none()
                .then(|| user_safe_decode(&data, &charset));
            parts.push(MultipartPart {
                name,
                filename,
                headers,
                data,
                text,
            });
        }
        Ok(parts)
    })
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
