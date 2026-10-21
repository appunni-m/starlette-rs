use super::{FileMetadata, FileResponseError, python_float_text};

/// A Unix timestamp whose numeric type is preserved for the file ETag input.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum FileTimestamp {
    /// An integer timestamp, serialized as decimal integer text for ETag generation.
    Integer(i128),
    /// A floating-point timestamp, serialized with Python-compatible float text.
    Float(f64),
}

impl FileMetadata {
    /// Creates metadata while preserving whether the timestamp was an integer or float.
    ///
    /// The timestamp is converted to floating-point seconds for date formatting while its
    /// original numeric type supplies the text hashed into the ETag.
    ///
    /// # Errors
    ///
    /// Returns [`FileResponseError::InvalidTimestamp`] if the timestamp is not finite.
    pub fn from_unix_timestamp(
        size: u64,
        modified_timestamp: FileTimestamp,
    ) -> Result<Self, FileResponseError> {
        let (modified_seconds, modified_text) = match modified_timestamp {
            FileTimestamp::Integer(seconds) => {
                // Python's stat_result exposes integer seconds as integer text for the ETag,
                // while date formatting converts the value to floating-point seconds.
                (seconds as f64, seconds.to_string())
            }
            FileTimestamp::Float(seconds) => (seconds, python_float_text(seconds)),
        };
        if !modified_seconds.is_finite() {
            return Err(FileResponseError::InvalidTimestamp);
        }
        Ok(Self {
            size,
            modified_seconds_bits: modified_seconds.to_bits(),
            modified_text,
            stat_result: None,
        })
    }
}
