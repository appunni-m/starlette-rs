use std::collections::HashSet;

use serde_json::{Map, Value, json};
use starlette_rs::{
    FileTimestamp, MultipartPart, SessionSignatureError, parse_multipart_form, timestamp_unsign,
};

use super::{
    decode_base64, encode_base64, exact_object, native_observation_result, python_string_repr,
    string_array_field, string_field,
};

mod native_direct;

const NATIVE_MULTIPART_SURFACE: &str = "starlette-rs.parse_multipart_form";
const NATIVE_MULTIPART_OPERATION: &str = "parse";

pub(crate) fn dispatch_native_case(case: &Value) -> Option<Result<Value, String>> {
    native_direct::dispatch(case).or_else(|| dispatch_native_form_data_case(case))
}

pub(crate) fn native_header_name(
    arguments: &[Value],
    index: usize,
    context: &str,
) -> Result<Vec<u8>, String> {
    let name = native_header_argument_string(arguments, index, context)?;
    super::encode_mutable_headers_value(&name, &format!("{context} header name"))
}

pub(crate) fn native_header_value(
    arguments: &[Value],
    index: usize,
    context: &str,
) -> Result<Vec<u8>, String> {
    let value = native_header_argument_string(arguments, index, context)?;
    super::encode_mutable_headers_value(&value, &format!("{context} header value"))
}

fn native_header_argument_string(
    arguments: &[Value],
    index: usize,
    context: &str,
) -> Result<String, String> {
    arguments
        .get(index)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| format!("{context} argument {index} must be a string"))
}

pub(crate) fn native_header_extra_action(
    receiver: super::NativeHeaderCollection,
    call: &str,
    context: &str,
) -> Result<(Value, Option<super::NativeHeaderCollection>), String> {
    match call {
        "is_empty" => {
            let is_empty = match &receiver {
                super::NativeHeaderCollection::Headers(headers) => headers.is_empty(),
                super::NativeHeaderCollection::MutableHeaders(headers) => headers.is_empty(),
            };
            Ok((json!(is_empty), None))
        }
        "into_raw" => match receiver {
            super::NativeHeaderCollection::MutableHeaders(headers) => {
                Ok((json!(super::canonical_headers(&headers.into_raw())), None))
            }
            super::NativeHeaderCollection::Headers(_) => {
                Err(format!("{context} into_raw requires MutableHeaders"))
            }
        },
        _ => Err(format!("{context} call {call:?} is unsupported")),
    }
}

pub(crate) fn insert_request_header_observations(
    values: &mut Map<String, Value>,
    headers: &super::RequestHeaders,
) {
    let raw_headers = headers
        .raw()
        .iter()
        .map(|(name, value)| json!([encode_base64(name), encode_base64(value)]))
        .collect::<Vec<_>>();
    values.insert(String::from("raw_headers_base64_pairs"), json!(raw_headers));
    values.insert(String::from("header_length"), json!(headers.len()));
    values.insert(String::from("headers_is_empty"), json!(headers.is_empty()));
}

pub(crate) fn dispatch_native_form_data_case(case: &Value) -> Option<Result<Value, String>> {
    let surface = case.get("surface").and_then(Value::as_str);
    let operation = case.get("operation").and_then(Value::as_str);
    match (surface, operation) {
        (Some(super::NATIVE_FORM_DATA_SURFACE), Some(super::NATIVE_FORM_DATA_OPERATION)) => {
            Some(super::run_native_form_data_case(case))
        }
        (Some(NATIVE_MULTIPART_SURFACE), Some(NATIVE_MULTIPART_OPERATION)) => {
            Some(run_native_multipart_case(case))
        }
        _ => None,
    }
}

struct NativeMultipartInput {
    body: Vec<u8>,
    content_type: String,
    max_files: f64,
    max_files_display: String,
    max_fields: f64,
    max_fields_display: String,
    max_part_size: i64,
}

fn native_multipart_input(value: &Value) -> Result<NativeMultipartInput, String> {
    let context = "native multipart parser input";
    let input = exact_object(
        value,
        &[
            "body_base64",
            "content_type",
            "max_files",
            "max_fields",
            "max_part_size",
        ],
        context,
    )?;
    let limit = |field: &str| {
        input
            .get(field)
            .and_then(Value::as_i64)
            .ok_or_else(|| format!("native multipart {field} must be an integer"))
    };
    let max_files_integer = limit("max_files")?;
    let max_fields_integer = limit("max_fields")?;
    let max_part_size = limit("max_part_size")?;
    let max_files = input["max_files"]
        .as_f64()
        .ok_or_else(|| String::from("native multipart max_files must be finite"))?;
    let max_fields = input["max_fields"]
        .as_f64()
        .ok_or_else(|| String::from("native multipart max_fields must be finite"))?;
    Ok(NativeMultipartInput {
        body: decode_base64(
            string_field(input, "body_base64", context)?,
            "native multipart parser body",
        )?,
        content_type: string_field(input, "content_type", context)?.to_owned(),
        max_files,
        max_files_display: max_files_integer.to_string(),
        max_fields,
        max_fields_display: max_fields_integer.to_string(),
        max_part_size,
    })
}

fn native_multipart_parts(parts: Vec<MultipartPart>) -> Result<Vec<Value>, String> {
    parts
        .into_iter()
        .map(|part| {
            let value = match (part.filename, part.text) {
                (Some(filename), _) => json!({
                    "kind": "file",
                    "filename": filename,
                    "body_base64": encode_base64(&part.data),
                }),
                (None, Some(text)) => json!({"kind": "text", "text": text}),
                (None, None) => {
                    return Err(String::from(
                        "native multipart text part omitted its decoded value",
                    ));
                }
            };
            Ok(json!({"name": part.name, "value": value}))
        })
        .collect()
}

fn run_native_multipart_case(case: &Value) -> Result<Value, String> {
    let context = "native multipart parser case";
    let case = exact_object(
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
    let case_id = string_field(case, "case_id", context)?;
    if string_field(case, "surface", context)? != NATIVE_MULTIPART_SURFACE
        || string_field(case, "operation", context)? != NATIVE_MULTIPART_OPERATION
        || string_array_field(case, "target_profiles", context)?
            != [String::from("rust-native-local")]
        || case.get("assets") != Some(&json!([]))
        || case.get("observations") != Some(&json!(["workflow"]))
    {
        return Err(String::from(
            "case is outside the native multipart parser operation",
        ));
    }
    let input = native_multipart_input(
        case.get("input")
            .ok_or_else(|| format!("{context} misses input"))?,
    )?;
    let parsed = parse_multipart_form(
        &input.body,
        &input.content_type,
        input.max_files,
        &input.max_files_display,
        input.max_fields,
        &input.max_fields_display,
        input.max_part_size,
    );
    let mut values = Map::new();
    match parsed {
        Ok(parts) => {
            values.insert(String::from("parts"), json!(native_multipart_parts(parts)?));
        }
        Err(error) => {
            values.insert(String::from("error"), json!({"message": error.message()}));
        }
    }
    native_observation_result(case_id, case, values, context)
}

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
