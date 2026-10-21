use std::collections::HashSet;

use serde_json::{Map, Value, json};
use starlette_rs::{FileTimestamp, SessionSignatureError, timestamp_unsign};

use super::{encode_base64, exact_object, python_string_repr, string_field};

pub(crate) fn file_response_timestamp(
    value: Option<&Value>,
    field: &str,
) -> Result<FileTimestamp, String> {
    let Some(Value::Number(number)) = value else {
        return Err(format!("{field} must be finite"));
    };
    if number.is_i64() || number.is_u64() {
        let integer = number
            .to_string()
            .parse::<i128>()
            .map_err(|_| format!("{field} must fit a signed 128-bit integer"))?;
        return Ok(FileTimestamp::Integer(integer));
    }
    let seconds = number
        .as_f64()
        .filter(|seconds| seconds.is_finite())
        .ok_or_else(|| format!("{field} must be finite"))?;
    Ok(FileTimestamp::Float(seconds))
}

pub(crate) fn run_timestamp_unsign_case(case: &Value) -> Result<Value, String> {
    let context = "timestamp-unsign case";
    let case_object = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "input",
            "observations",
        ],
        context,
    )?;
    if string_field(case_object, "surface", context)? != super::NATIVE_TIMESTAMP_UNSIGN_SURFACE
        || string_field(case_object, "operation", context)?
            != super::NATIVE_TIMESTAMP_UNSIGN_OPERATION
    {
        return Err(String::from(
            "case is outside the timestamp-unsign operation",
        ));
    }
    let has_result_observation = case_object
        .get("observations")
        .and_then(Value::as_array)
        .is_some_and(|observations| {
            observations.len() == 1 && observations[0].as_str() == Some("result")
        });
    if !has_result_observation {
        return Err(String::from(
            "timestamp-unsign case must select the result observation",
        ));
    }
    let observation = case_object
        .get("observations")
        .and_then(Value::as_array)
        .and_then(|observations| observations.first())
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("timestamp-unsign observation must be a string"))?;

    let input = exact_object(
        case_object
            .get("input")
            .ok_or_else(|| String::from("timestamp-unsign case.input is missing"))?,
        &["secret_key", "signed_value_ascii", "now", "max_age"],
        "timestamp-unsign input",
    )?;
    let secret_key = string_field(input, "secret_key", "timestamp-unsign input")?;
    let signed_value = string_field(input, "signed_value_ascii", "timestamp-unsign input")?;
    if !signed_value.is_ascii() {
        return Err(String::from(
            "timestamp-unsign input.signed_value_ascii must contain ASCII characters",
        ));
    }
    let now = input
        .get("now")
        .and_then(Value::as_u64)
        .ok_or_else(|| String::from("timestamp-unsign input.now must be an unsigned integer"))?;
    let max_age = match input.get("max_age") {
        Some(Value::Null) => None,
        Some(Value::Number(value)) => Some(value.as_i64().ok_or_else(|| {
            String::from("timestamp-unsign input.max_age must fit a signed 64-bit integer")
        })?),
        _ => {
            return Err(String::from(
                "timestamp-unsign input.max_age must be an integer or null",
            ));
        }
    };
    let case_id = string_field(case_object, "case_id", context)?;
    let result = match timestamp_unsign(signed_value.as_bytes(), secret_key, now, max_age) {
        Ok(payload) => json!({"encoding": "base64", "data": encode_base64(&payload)}),
        Err(SessionSignatureError::InvalidSignature) => {
            json!({"error": {"kind": "BadSignature"}})
        }
        Err(
            SessionSignatureError::MissingTimestamp | SessionSignatureError::MalformedTimestamp,
        ) => json!({"error": {"kind": "BadTimeSignature"}}),
        Err(
            SessionSignatureError::Expired { .. } | SessionSignatureError::FutureTimestamp { .. },
        ) => json!({"error": {"kind": "SignatureExpired"}}),
        Err(error @ SessionSignatureError::InvalidKey) => return Err(error.to_string()),
    };

    let mut value = Map::new();
    value.insert(observation.to_owned(), result);
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": observation,
            "status": "ok",
            "value": value,
        }],
    }))
}

pub(crate) fn native_headers_repr(
    class_name: &str,
    items: &[(String, String)],
    raw_pairs: &[(Vec<u8>, Vec<u8>)],
) -> String {
    let distinct_names = items
        .iter()
        .map(|(name, _)| name.as_str())
        .collect::<HashSet<_>>()
        .len();
    if distinct_names == items.len() {
        let entries = items
            .iter()
            .map(|(name, value)| {
                format!(
                    "{}: {}",
                    python_string_repr(name),
                    python_string_repr(value)
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        return format!("{class_name}({{{entries}}})");
    }

    let raw_pairs = raw_pairs
        .iter()
        .map(|(name, value)| {
            format!(
                "({}, {})",
                python_bytes_repr(name),
                python_bytes_repr(value)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    format!("{class_name}(raw=[{raw_pairs}])")
}

fn python_bytes_repr(value: &[u8]) -> String {
    let quote = if value.contains(&b'\'') && !value.contains(&b'"') {
        b'"'
    } else {
        b'\''
    };
    let mut output = String::with_capacity(value.len().saturating_add(3));
    output.push('b');
    output.push(char::from(quote));
    for byte in value {
        match *byte {
            b'\\' => output.push_str("\\\\"),
            b'\n' => output.push_str("\\n"),
            b'\r' => output.push_str("\\r"),
            b'\t' => output.push_str("\\t"),
            current if current == quote => {
                output.push('\\');
                output.push(char::from(current));
            }
            0x20..=0x7e => output.push(char::from(*byte)),
            current => output.push_str(&format!("\\x{current:02x}")),
        }
    }
    output.push(char::from(quote));
    output
}
