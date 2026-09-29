//! Raw timestamped signatures compatible with `itsdangerous` 2.2.0 defaults.
//!
//! This module signs payload bytes directly. Session serialization and the
//! surrounding cookie format belong to higher layers.

use std::error::Error;
use std::fmt::{self, Display, Formatter};

use base64::Engine;
use base64::alphabet;
use base64::engine::general_purpose::{GeneralPurpose, GeneralPurposeConfig, URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use sha1::{Digest, Sha1};

type HmacSha1 = Hmac<Sha1>;

const DEFAULT_SALT: &[u8] = b"itsdangerous.Signer";
const KEY_DERIVATION_LABEL: &[u8] = b"signer";
const SEPARATOR: u8 = b'.';
const URL_SAFE_DECODE: GeneralPurpose = GeneralPurpose::new(
    &alphabet::URL_SAFE,
    GeneralPurposeConfig::new().with_decode_allow_trailing_bits(true),
);

/// Failure returned while verifying an `itsdangerous.TimestampSigner` value.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionSignatureError {
    /// The signature segment is missing or does not match the payload.
    InvalidSignature,
    /// The authenticated signed value does not contain a timestamp segment.
    MissingTimestamp,
    /// The authenticated timestamp is not valid URL-safe base64 Unix seconds.
    MalformedTimestamp,
    /// The signature is older than the provided maximum age.
    Expired {
        /// Whole seconds elapsed since the signature was created.
        age_seconds: u64,
        /// The maximum accepted age, in seconds.
        max_age_seconds: i64,
    },
    /// The signature timestamp is later than the supplied current time.
    FutureTimestamp {
        /// Whole seconds between the signed time and the supplied current time.
        seconds_ahead: u64,
    },
    /// HMAC rejected the supplied key length. HMAC-SHA1 accepts all key sizes,
    /// so this is reserved for a backend construction failure.
    InvalidKey,
}

impl Display for SessionSignatureError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidSignature => formatter.write_str("invalid timestamp signature"),
            Self::MissingTimestamp => formatter.write_str("timestamp is missing"),
            Self::MalformedTimestamp => formatter.write_str("timestamp is malformed"),
            Self::Expired {
                age_seconds,
                max_age_seconds,
            } => write!(
                formatter,
                "signature age {age_seconds} > {max_age_seconds} seconds"
            ),
            Self::FutureTimestamp { seconds_ahead } => {
                write!(
                    formatter,
                    "signature timestamp is {seconds_ahead} seconds in the future"
                )
            }
            Self::InvalidKey => formatter.write_str("could not construct the timestamp signer key"),
        }
    }
}

impl Error for SessionSignatureError {}

/// Signs raw payload bytes with the default `itsdangerous.TimestampSigner` format.
///
/// The key is derived with SHA-1 over the default salt, the `signer` label, and
/// the UTF-8 bytes of `secret`. The timestamp is encoded as a minimal
/// big-endian unsigned integer and URL-safe base64 without padding.
///
/// # Errors
///
/// Returns [`SessionSignatureError::InvalidKey`] if the HMAC backend rejects
/// key construction. HMAC-SHA1 accepts keys of every length.
pub fn timestamp_sign(
    payload: &[u8],
    secret: &str,
    timestamp: u64,
) -> Result<Vec<u8>, SessionSignatureError> {
    let timestamp = encode_timestamp(timestamp);
    let mut signed_value = Vec::with_capacity(payload.len() + timestamp.len() + 1);
    signed_value.extend_from_slice(payload);
    signed_value.push(SEPARATOR);
    signed_value.extend_from_slice(timestamp.as_bytes());

    let key = derive_key(secret);
    let mut mac = HmacSha1::new_from_slice(&key).map_err(|_| SessionSignatureError::InvalidKey)?;
    mac.update(&signed_value);
    let signature = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());

    signed_value.push(SEPARATOR);
    signed_value.extend_from_slice(signature.as_bytes());
    Ok(signed_value)
}

/// Verifies a timestamped value and returns its original raw payload bytes.
///
/// The optional maximum age follows `itsdangerous.TimestampSigner`: age and
/// future-time checks are performed only when `max_age` is provided. Negative
/// maximum ages are accepted and make non-future values expired, matching the
/// upstream integer comparison.
///
/// # Errors
///
/// Returns [`SessionSignatureError::InvalidSignature`] when the authenticator
/// is absent or invalid, [`SessionSignatureError::MalformedTimestamp`] for an
/// invalid authenticated timestamp, and the age-specific variants when the
/// optional age check fails.
pub fn timestamp_unsign(
    value: &[u8],
    secret: &str,
    now: u64,
    max_age: Option<i64>,
) -> Result<Vec<u8>, SessionSignatureError> {
    let signature_separator = value
        .iter()
        .rposition(|byte| *byte == SEPARATOR)
        .ok_or(SessionSignatureError::InvalidSignature)?;
    let signed_value = &value[..signature_separator];
    let encoded_signature = &value[signature_separator + 1..];

    let decoded_signature = decode_itsdangerous_base64(encoded_signature)
        .ok_or(SessionSignatureError::InvalidSignature)?;
    let key = derive_key(secret);
    let mut mac = HmacSha1::new_from_slice(&key).map_err(|_| SessionSignatureError::InvalidKey)?;
    mac.update(signed_value);
    mac.verify_slice(&decoded_signature)
        .map_err(|_| SessionSignatureError::InvalidSignature)?;

    let timestamp_separator = signed_value
        .iter()
        .rposition(|byte| *byte == SEPARATOR)
        .ok_or(SessionSignatureError::MissingTimestamp)?;
    let payload = &signed_value[..timestamp_separator];
    let encoded_timestamp = &signed_value[timestamp_separator + 1..];
    let timestamp =
        decode_timestamp(encoded_timestamp).ok_or(SessionSignatureError::MalformedTimestamp)?;

    if let Some(max_age_seconds) = max_age {
        if timestamp > now {
            return Err(SessionSignatureError::FutureTimestamp {
                seconds_ahead: timestamp - now,
            });
        }

        let age_seconds = now - timestamp;
        if i128::from(age_seconds) > i128::from(max_age_seconds) {
            return Err(SessionSignatureError::Expired {
                age_seconds,
                max_age_seconds,
            });
        }
    }

    Ok(payload.to_vec())
}

fn derive_key(secret: &str) -> [u8; 20] {
    let mut digest = Sha1::new();
    digest.update(DEFAULT_SALT);
    digest.update(KEY_DERIVATION_LABEL);
    digest.update(secret.as_bytes());
    digest.finalize().into()
}

fn encode_timestamp(timestamp: u64) -> String {
    let bytes = timestamp.to_be_bytes();
    let first_nonzero = bytes
        .iter()
        .position(|byte| *byte != 0)
        .unwrap_or(bytes.len());
    URL_SAFE_NO_PAD.encode(&bytes[first_nonzero..])
}

fn decode_timestamp(encoded: &[u8]) -> Option<u64> {
    let decoded = decode_itsdangerous_base64(encoded)?;
    if decoded.len() > std::mem::size_of::<u64>() {
        return None;
    }

    let mut bytes = [0_u8; 8];
    bytes[8 - decoded.len()..].copy_from_slice(&decoded);
    Some(u64::from_be_bytes(bytes))
}

fn decode_itsdangerous_base64(encoded: &[u8]) -> Option<Vec<u8>> {
    let mut normalized = encoded
        .iter()
        .filter_map(|byte| match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'=' => Some(*byte),
            b'+' => Some(b'-'),
            b'/' => Some(b'_'),
            _ => None,
        })
        .collect::<Vec<_>>();
    while normalized.last() == Some(&b'=') {
        normalized.pop();
    }
    let missing_padding = (4 - normalized.len() % 4) % 4;
    normalized.extend(std::iter::repeat_n(b'=', missing_padding));
    URL_SAFE_DECODE.decode(normalized).ok()
}
