//! Process-isolated native adapter for the first Starlette migration-parity slice.

use std::collections::{BTreeSet, HashSet, VecDeque};
use std::env;
use std::error::Error;
use std::ffi::OsString;
use std::fs;
use std::future::{Future, pending, poll_fn, ready};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::process::ExitCode;
use std::str::FromStr;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};
use std::time::{Duration, UNIX_EPOCH};

#[cfg(unix)]
use std::ffi::CString;
#[cfg(unix)]
use std::os::unix::ffi::{OsStrExt, OsStringExt};
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

// The workspace's flate2 dependency is used by the companion library target.
use base64 as _;
use bytes as _;
use bytes::Bytes;
use encoding_rs as _;
use flate2 as _;
use futures as _;
use futures::Stream;
use futures::executor::block_on;
use getrandom as _;
use hmac as _;
use http as _;
use http::{HeaderMap, HeaderName, HeaderValue, Method, Request, Response as HttpResponse, Uri};
use http_body as _;
use http_body::{Body, Frame};
use http_body_util as _;
use http_body_util::BodyExt;
use md5 as _;
use mime_guess as _;
use multer as _;
use serde_json::{Map, Number, Value, json};
use sha1 as _;
use sha2 as _;
#[cfg(feature = "fault-contract")]
use starlette_rs::fault_contract_fail_next_random_boundary;
use starlette_rs::{
    ActiveNativeLifespan, ApplicationRoute, AsgiScopeKind, CommaSeparatedStrings, CookieOptions,
    Cookies, CustomPathConverter, CustomPathConverterRegistry, DEFAULT_EXCLUDED_CONTENT_TYPES,
    DetailedRouteMatch, ExceptionHandlerTable, FileMetadata, FileResponse as NativeFileResponse,
    FileResponseCallError, FileResponseCallInput, FileResponseCallStep, FileResponseError,
    FileResponseEvent, FileResponseHeaderViews, FileResponseOptions, FormData as NativeFormData,
    GzipConfig, GzipHeader, GzipResponseStart, HostPattern, HttpScope, LifespanAction,
    LifespanState, Mount as NativeMount, MountChild, MountScope, MultiDict as NativeMultiDict,
    MutableHeaders as NativeMutableHeaders, NamedHost, NamedMount, NamedRoute as NativeNamedRoute,
    NamedRouteError, NamedRouter, NamedRouterError, NativeApplication as NativeServiceApplication,
    NativeApplicationChild, NativeApplicationError, NativeHostApplication, NativeHostRoute,
    NativeLifespan, NativeLifespanError, NativeLifespanState, NativeMount as NativeServiceMount,
    NativeRequest, NativeRequestScope, NativeRoute, NativeWebSocketAcceptance,
    NativeWebSocketClose, NativeWebSocketDriver, NativeWebSocketError, NativeWebSocketEvent,
    NativeWebSocketHandshake, NativeWebSocketMessage, NativeWebSocketPeerClose,
    NativeWebSocketRoute, NativeWebSocketRouter, NativeWebSocketTransportError, PathConverter,
    PathParameterCapture, PathParameterValue, QueryParams, RequestBodyAccumulator, RequestHeaders,
    Response, ResponseError, ResponseEvent, RouteError, RouteTable, Starlette as NativeApplication,
    StaticFiles as NativeStaticFiles, StaticFilesError, StaticFilesResponse, StreamingResponse,
    StreamingResponseCallInput, StreamingResponseCallStep, StreamingResponseEvent, WebSocketState,
    WebSocketStateMachine, classify_scope, connection_url, timestamp_unsign,
};
use tower_layer as _;
use tower_service as _;
use unicode_general_category::{GeneralCategory, get_general_category};

const REQUEST_SCHEMA: &str = "migration-parity/adapter-request@1";
const RESPONSE_SCHEMA: &str = "migration-parity/adapter-response@1";
const SUBJECT_ID: &str = "rust-native";
const REDIRECT_RESPONSE_SURFACE: &str = "starlette.responses.RedirectResponse";
const REDIRECT_RESPONSE_OPERATION: &str = "asgi-call";
const RESPONSE_SURFACE: &str = "starlette.responses.Response";
const JSON_RESPONSE_SURFACE: &str = "starlette.responses.JSONResponse";
const STREAMING_RESPONSE_SURFACE: &str = "starlette.responses.StreamingResponse";
const NATIVE_RESPONSE_SURFACE: &str = "starlette-rs.Response";
const NATIVE_HTTP_EXCEPTION_OPERATION: &str = "http-exception";
const NATIVE_EXCEPTION_HANDLER_TABLE_SURFACE: &str = "starlette-rs.ExceptionHandlerTable";
const NATIVE_EXCEPTION_HANDLER_TABLE_OPERATION: &str = "select";
const NATIVE_FORM_DATA_SURFACE: &str = "starlette-rs.FormData";
const NATIVE_FORM_DATA_OPERATION: &str = "from-pairs-and-lookups";
const NATIVE_STREAMING_RESPONSE_SURFACE: &str = "starlette-rs.StreamingResponse";
const FILE_RESPONSE_SURFACE: &str = "starlette.responses.FileResponse";
const FILE_RESPONSE_RANDOM_SOURCE_FAULT_POINT: &str =
    "starlette-rs.file-response.random-source.failure";
const STATIC_FILES_SURFACE: &str = "starlette.staticfiles.StaticFiles";
const STATIC_FILES_LOOKUP_PATH_OPERATION: &str = "lookup-path";
const RESPONSE_OPERATION: &str = "asgi-call";
const QUERY_PARAMS_SURFACE: &str = "starlette.datastructures.QueryParams";
const QUERY_PARAMS_OPERATION: &str = "construction-and-mapping-sequence";
const MULTIDICT_SURFACE: &str = "starlette.datastructures.MultiDict";
const MULTIDICT_OPERATION: &str = "mutation-sequence";
const MUTABLE_HEADERS_SURFACE: &str = "starlette.datastructures.MutableHeaders";
const MUTABLE_HEADERS_OPERATION: &str = "consumer-sequence";
const COMMA_SEPARATED_STRINGS_SURFACE: &str = "starlette.datastructures.CommaSeparatedStrings";
const COMMA_SEPARATED_STRINGS_OPERATION: &str = "consumer-sequence";
const HOST_SURFACE: &str = "starlette.routing.Host";
const HOST_URL_PATH_OPERATION: &str = "url_path_for";
const ROUTE_URL_PATH_OPERATION: &str = "url_path_for";
const ROUTER_URL_PATH_OPERATION: &str = "url_path_for";
const WEBSOCKET_SURFACE: &str = "starlette.websockets.WebSocket";
const WEBSOCKET_OPERATION: &str = "protocol-sequence";
const WEBSOCKET_STATE_OPERATION: &str = "state-sequence";
const NATIVE_WEBSOCKET_SURFACE: &str = "starlette-rs.NativeWebSocket";
const NATIVE_WEBSOCKET_OPERATION: &str = "native-session-sequence";
const NATIVE_SERVICE_MIDDLEWARE_OPERATION: &str = "service-tower-middleware";
const NATIVE_SERVICE_MOUNTED_CHILD_OPERATION: &str = "service-mounted-child";
const NATIVE_SERVICE_CUSTOM_CONVERTER_OPERATION: &str = "service-custom-converter-dispatch";
const NATIVE_SERVICE_HOST_ROUTING_OPERATION: &str = "service-host-routing";
const NATIVE_STREAMING_RESPONSE_SOURCE_OPERATION: &str = "lazy-source-call";
const NATIVE_ROUTE_TABLE_CUSTOM_CONVERTER_OPERATION: &str = "custom-converter-match";
const NATIVE_NAMED_ROUTE_CUSTOM_CONVERTER_OPERATION: &str = "custom-converter-url-path-for";
const NATIVE_TIMESTAMP_UNSIGN_SURFACE: &str = "starlette_rs.timestamp_unsign";
const NATIVE_TIMESTAMP_UNSIGN_OPERATION: &str = "timestamp-unsign";
// The Python facade maps Rust state-transition errors through PyRuntimeError.
const WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS: &str = "builtins.RuntimeError";
const WEBSOCKET_CALLBACK_OSERROR_CLASS: &str = "builtins.OSError";

static NEXT_FILE_RESPONSE_TEMP: AtomicU64 = AtomicU64::new(0);

struct FileResponseTempDirectory(PathBuf);

#[derive(Clone, Copy)]
struct StaticFilesPathLimitStress {
    overflow_bytes: usize,
    later_root_margin_bytes: usize,
    safe_component_bytes: usize,
}

#[derive(Clone, Copy)]
struct StaticFilesPermissionDenialStress {
    mode: u32,
}

#[cfg(unix)]
struct StaticFilesPermissionDenialGuard {
    path: PathBuf,
    original_permissions: fs::Permissions,
}

#[cfg(unix)]
type StaticFilesPermissionGuard = StaticFilesPermissionDenialGuard;
#[cfg(not(unix))]
type StaticFilesPermissionGuard = ();

#[cfg(unix)]
impl Drop for StaticFilesPermissionDenialGuard {
    fn drop(&mut self) {
        let _ = fs::set_permissions(&self.path, self.original_permissions.clone());
    }
}

enum StaticFilesPathLimitStressSetup {
    #[cfg(unix)]
    Ready(PathBuf),
    Skipped(String),
}

enum StaticFilesPermissionDenialStressSetup {
    #[cfg(unix)]
    Ready(StaticFilesPermissionDenialGuard),
    Skipped(String),
}

impl Drop for FileResponseTempDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            let _ = writeln!(io::stderr(), "{error}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let request = read_request()?;
    let request_object = exact_object(
        &request,
        &["schema", "mode", "subject_id", "case"],
        "adapter request",
    )?;
    let schema = string_field(request_object, "schema", "adapter request")?;
    let mode = string_field(request_object, "mode", "adapter request")?;
    let subject_id = string_field(request_object, "subject_id", "adapter request")?;
    if schema != REQUEST_SCHEMA || subject_id != SUBJECT_ID {
        return Err(String::from(
            "adapter request schema or subject ID does not match this target",
        ));
    }

    let response = match mode {
        "identity" => {
            if !request_object.get("case").is_some_and(Value::is_null) {
                return Err(String::from("identity requests must set case to null"));
            }
            json!({
                "schema": RESPONSE_SCHEMA,
                "mode": "identity",
                "subject_id": SUBJECT_ID,
                "identity": identity()?,
            })
        }
        "workflow" => {
            let case = request_object
                .get("case")
                .filter(|value| value.is_object())
                .ok_or_else(|| String::from("workflow request case must be an object"))?;
            json!({
                "schema": RESPONSE_SCHEMA,
                "mode": "workflow",
                "subject_id": SUBJECT_ID,
                "result": run_case(case)?,
            })
        }
        _ => {
            return Err(String::from(
                "adapter request mode must be identity or workflow",
            ));
        }
    };

    let mut stdout = io::stdout().lock();
    serde_json::to_writer(&mut stdout, &response).map_err(|error| error.to_string())?;
    stdout.write_all(b"\n").map_err(|error| error.to_string())?;
    stdout.flush().map_err(|error| error.to_string())
}

fn read_request() -> Result<Value, String> {
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .map_err(|error| format!("cannot read adapter request: {error}"))?;
    let mut lines = input.split_terminator('\n');
    let line = lines
        .next()
        .filter(|line| !line.trim().is_empty())
        .ok_or_else(|| String::from("adapter request stdin is empty"))?;
    if lines.next().is_some() {
        return Err(String::from(
            "adapter request must contain exactly one JSON line",
        ));
    }
    // serde_json::Value replaces duplicate map entries, so inspect every object
    // first while leaving full JSON grammar and value decoding to serde_json.
    reject_duplicate_json_object_keys(line)?;
    serde_json::from_str(line).map_err(|error| format!("invalid adapter request JSON: {error}"))
}

fn reject_duplicate_json_object_keys(input: &str) -> Result<(), String> {
    JsonObjectKeyScanner {
        input: input.as_bytes(),
        position: 0,
    }
    .scan_value(0)
}

const MAX_JSON_NESTING: usize = 128;

fn checked_usize_add(value: usize, amount: usize, context: &str) -> Result<usize, String> {
    value
        .checked_add(amount)
        .ok_or_else(|| format!("{context} overflow"))
}

fn checked_usize_increment(value: &mut usize, context: &str) -> Result<(), String> {
    *value = checked_usize_add(*value, 1, context)?;
    Ok(())
}

fn checked_u64_increment(value: &mut u64, context: &str) -> Result<(), String> {
    *value = value
        .checked_add(1)
        .ok_or_else(|| format!("{context} overflow"))?;
    Ok(())
}

struct JsonObjectKeyScanner<'a> {
    input: &'a [u8],
    position: usize,
}

impl JsonObjectKeyScanner<'_> {
    fn scan_value(&mut self, nesting: usize) -> Result<(), String> {
        if nesting > MAX_JSON_NESTING {
            return Err(String::from(
                "invalid adapter request JSON: nesting exceeds the JSON parser limit",
            ));
        }
        self.skip_whitespace()?;
        match self.input.get(self.position) {
            Some(b'{') => self.scan_object(nesting),
            Some(b'[') => self.scan_array(nesting),
            Some(b'"') => self.scan_string().map(|_| ()),
            Some(_) => self.scan_primitive(),
            None => Ok(()),
        }
    }

    fn scan_object(&mut self, nesting: usize) -> Result<(), String> {
        checked_usize_increment(&mut self.position, "JSON scanner position")?;
        self.skip_whitespace()?;
        if self.input.get(self.position) == Some(&b'}') {
            checked_usize_increment(&mut self.position, "JSON scanner position")?;
            return Ok(());
        }

        let mut keys = HashSet::new();
        loop {
            self.skip_whitespace()?;
            if self.input.get(self.position) != Some(&b'"') {
                return Ok(());
            }
            let key = self.scan_string()?;
            if !keys.insert(key.clone()) {
                return Err(format!("duplicate JSON object key {key:?}"));
            }
            self.skip_whitespace()?;
            if self.input.get(self.position) != Some(&b':') {
                return Ok(());
            }
            checked_usize_increment(&mut self.position, "JSON scanner position")?;
            let child_nesting = checked_usize_add(nesting, 1, "JSON nesting depth")?;
            self.scan_value(child_nesting)?;
            self.skip_whitespace()?;
            match self.input.get(self.position) {
                Some(b',') => checked_usize_increment(&mut self.position, "JSON scanner position")?,
                Some(b'}') => {
                    checked_usize_increment(&mut self.position, "JSON scanner position")?;
                    return Ok(());
                }
                _ => return Ok(()),
            }
        }
    }

    fn scan_array(&mut self, nesting: usize) -> Result<(), String> {
        checked_usize_increment(&mut self.position, "JSON scanner position")?;
        self.skip_whitespace()?;
        if self.input.get(self.position) == Some(&b']') {
            checked_usize_increment(&mut self.position, "JSON scanner position")?;
            return Ok(());
        }

        loop {
            let child_nesting = checked_usize_add(nesting, 1, "JSON nesting depth")?;
            self.scan_value(child_nesting)?;
            self.skip_whitespace()?;
            match self.input.get(self.position) {
                Some(b',') => checked_usize_increment(&mut self.position, "JSON scanner position")?,
                Some(b']') => {
                    checked_usize_increment(&mut self.position, "JSON scanner position")?;
                    return Ok(());
                }
                _ => return Ok(()),
            }
        }
    }

    fn scan_primitive(&mut self) -> Result<(), String> {
        while let Some(byte) = self.input.get(self.position) {
            if byte.is_ascii_whitespace() || matches!(byte, b',' | b']' | b'}') {
                return Ok(());
            }
            checked_usize_increment(&mut self.position, "JSON scanner position")?;
        }
        Ok(())
    }

    fn scan_string(&mut self) -> Result<String, String> {
        let start = self.position;
        checked_usize_increment(&mut self.position, "JSON scanner position")?;
        while let Some(byte) = self.input.get(self.position) {
            match byte {
                b'"' => {
                    checked_usize_increment(&mut self.position, "JSON scanner position")?;
                    return serde_json::from_slice(&self.input[start..self.position])
                        .map_err(|error| format!("invalid adapter request JSON: {error}"));
                }
                b'\\' => {
                    checked_usize_increment(&mut self.position, "JSON scanner position")?;
                    if self.position >= self.input.len() {
                        break;
                    }
                    checked_usize_increment(&mut self.position, "JSON scanner position")?;
                }
                _ => checked_usize_increment(&mut self.position, "JSON scanner position")?,
            }
        }
        Err(String::from(
            "invalid adapter request JSON: unterminated JSON string",
        ))
    }

    fn skip_whitespace(&mut self) -> Result<(), String> {
        while self
            .input
            .get(self.position)
            .is_some_and(u8::is_ascii_whitespace)
        {
            checked_usize_increment(&mut self.position, "JSON scanner position")?;
        }
        Ok(())
    }
}

fn exact_object<'a>(
    value: &'a Value,
    expected: &[&str],
    context: &str,
) -> Result<&'a Map<String, Value>, String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("{context} must be a JSON object"))?;
    let mut actual: Vec<&str> = object.keys().map(String::as_str).collect();
    actual.sort_unstable();
    let mut wanted = expected.to_vec();
    wanted.sort_unstable();
    if actual != wanted {
        return Err(format!(
            "{context} fields differ: expected {wanted:?}, got {actual:?}"
        ));
    }
    Ok(object)
}

fn object_with_optional_keys<'a>(
    value: &'a Value,
    required: &[&str],
    optional: &[&str],
    context: &str,
) -> Result<&'a Map<String, Value>, String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("{context} must be a JSON object"))?;
    for required_key in required {
        if !object.contains_key(*required_key) {
            return Err(format!("{context} misses required field {required_key:?}"));
        }
    }
    for actual_key in object.keys() {
        if !required.contains(&actual_key.as_str()) && !optional.contains(&actual_key.as_str()) {
            return Err(format!("{context} has unsupported field {actual_key:?}"));
        }
    }
    Ok(object)
}

fn string_field<'a>(
    object: &'a Map<String, Value>,
    field: &str,
    context: &str,
) -> Result<&'a str, String> {
    object
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{context}.{field} must be a string"))
}

fn is_cpython_package_profile(profile: &str) -> bool {
    profile
        .strip_prefix("python-package-cpython")
        .is_some_and(|version| {
            !version.is_empty() && version.bytes().all(|byte| byte.is_ascii_digit())
        })
}

fn validate_native_package_target_profiles(
    case: &Map<String, Value>,
    context: &str,
) -> Result<(), String> {
    let profiles = case
        .get("target_profiles")
        .and_then(Value::as_array)
        .filter(|profiles| profiles.len() >= 2)
        .ok_or_else(|| {
            format!(
                "{context} target_profiles must contain rust-native-local followed by CPython package profiles"
            )
        })?;
    if profiles.first().and_then(Value::as_str) != Some("rust-native-local") {
        return Err(format!(
            "{context} target_profiles must begin with rust-native-local"
        ));
    }

    let mut seen = HashSet::new();
    let profiles_are_valid = profiles.iter().all(|profile| {
        profile.as_str().is_some_and(|profile| {
            seen.insert(profile)
                && (profile == "rust-native-local" || is_cpython_package_profile(profile))
        })
    });
    if !profiles_are_valid {
        return Err(format!(
            "{context} target_profiles must contain unique CPython package profiles after rust-native-local"
        ));
    }
    Ok(())
}

fn optional_string_field(
    object: &Map<String, Value>,
    field: &str,
    context: &str,
) -> Result<Option<String>, String> {
    match object.get(field) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        _ => Err(format!("{context}.{field} must be a string or null")),
    }
}

fn bool_field(object: &Map<String, Value>, field: &str, context: &str) -> Result<bool, String> {
    object
        .get(field)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("{context}.{field} must be a boolean"))
}

fn identity() -> Result<Value, String> {
    let dependency_lock_sha256 = env!("STARLETTE_PARITY_BUILD_DEPENDENCY_LOCK_SHA256");
    if let Ok(expected) = env::var("STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256") {
        if expected != dependency_lock_sha256 {
            return Err(String::from(
                "workspace Cargo.lock SHA256 does not match STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256",
            ));
        }
    }

    #[cfg(feature = "fault-contract")]
    let features = vec!["fault-contract"];
    #[cfg(not(feature = "fault-contract"))]
    let features: Vec<&str> = Vec::new();

    Ok(json!({
        "subject_id": SUBJECT_ID,
        "revision": env!("STARLETTE_PARITY_BUILD_REVISION"),
        "dirty": env!("STARLETTE_PARITY_BUILD_DIRTY") == "true",
        "runtime": env!("STARLETTE_PARITY_BUILD_RUNTIME"),
        "os": env!("STARLETTE_PARITY_BUILD_OS"),
        "architecture": env!("STARLETTE_PARITY_BUILD_ARCHITECTURE"),
        "backend": "native",
        "features": features,
        "package_version": env!("CARGO_PKG_VERSION"),
        "dependency_lock_sha256": dependency_lock_sha256,
    }))
}

fn run_case(case: &Value) -> Result<Value, String> {
    if case.get("surface").and_then(Value::as_str) == Some(NATIVE_FORM_DATA_SURFACE)
        && case.get("operation").and_then(Value::as_str) == Some(NATIVE_FORM_DATA_OPERATION)
    {
        return run_native_form_data_case(case);
    }
    if case.get("surface").and_then(Value::as_str) == Some(NATIVE_WEBSOCKET_SURFACE)
        && case.get("operation").and_then(Value::as_str) == Some(NATIVE_WEBSOCKET_OPERATION)
    {
        return run_native_websocket_case(case);
    }
    if case.get("surface").and_then(Value::as_str) == Some(WEBSOCKET_SURFACE) {
        return match case.get("operation").and_then(Value::as_str) {
            Some(WEBSOCKET_STATE_OPERATION) => run_websocket_state_case(case),
            Some(WEBSOCKET_OPERATION) => run_websocket_protocol_case(case),
            _ => Err(String::from("WebSocket operation is unsupported")),
        };
    }
    match (
        case.get("surface").and_then(Value::as_str),
        case.get("operation").and_then(Value::as_str),
    ) {
        (Some("starlette-rs.NativeApplication"), Some("service-body-streaming")) => {
            return run_native_service_case(case);
        }
        (Some("starlette-rs.NativeApplication"), Some(NATIVE_SERVICE_MOUNTED_CHILD_OPERATION)) => {
            return run_native_mounted_child_case(case);
        }
        (
            Some("starlette-rs.NativeApplication"),
            Some(NATIVE_SERVICE_CUSTOM_CONVERTER_OPERATION),
        ) => {
            return run_native_service_custom_converter_case(case);
        }
        (
            Some("starlette-rs.NativeHostApplication"),
            Some(NATIVE_SERVICE_HOST_ROUTING_OPERATION),
        ) => {
            return run_native_host_routing_case(case);
        }
        (
            Some("starlette-rs.StreamingResponse"),
            Some(NATIVE_STREAMING_RESPONSE_SOURCE_OPERATION),
        ) => {
            return run_native_streaming_source_case(case);
        }
        (Some(NATIVE_RESPONSE_SURFACE), Some(NATIVE_HTTP_EXCEPTION_OPERATION)) => {
            return run_native_http_exception_case(case);
        }
        (
            Some(NATIVE_EXCEPTION_HANDLER_TABLE_SURFACE),
            Some(NATIVE_EXCEPTION_HANDLER_TABLE_OPERATION),
        ) => {
            return run_native_exception_handler_table_case(case);
        }
        (Some("starlette-rs.RouteTable"), Some(NATIVE_ROUTE_TABLE_CUSTOM_CONVERTER_OPERATION)) => {
            return run_native_custom_converter_match_case(case);
        }
        (Some("starlette-rs.NamedRoute"), Some(NATIVE_NAMED_ROUTE_CUSTOM_CONVERTER_OPERATION)) => {
            return run_native_custom_converter_url_case(case);
        }
        (Some(NATIVE_TIMESTAMP_UNSIGN_SURFACE), Some(NATIVE_TIMESTAMP_UNSIGN_OPERATION)) => {
            return run_timestamp_unsign_case(case);
        }
        (Some("starlette-rs.NativeApplication"), Some(NATIVE_SERVICE_MIDDLEWARE_OPERATION)) => {
            return run_native_service_middleware_case(case);
        }
        (
            Some("starlette-rs.NativeLifespan"),
            Some("native-lifespan" | "start" | "shutdown" | "active-shutdown"),
        ) => {
            return run_native_lifespan_case(case);
        }
        (Some("starlette.middleware.gzip.GZipMiddleware"), Some("__call__")) => {
            return run_gzip_case(case);
        }
        (Some("starlette.applications.Starlette"), Some("request-dispatch")) => {
            return run_request_case(case);
        }
        (Some("starlette.routing.Router"), Some("route-dispatch")) => {
            return run_router_case(case);
        }
        (Some("starlette.routing.Route"), Some(ROUTE_URL_PATH_OPERATION)) => {
            return run_route_reverse_url_case(case);
        }
        (Some("starlette.routing.Router"), Some(ROUTER_URL_PATH_OPERATION)) => {
            return run_router_reverse_url_case(case);
        }
        (Some(HOST_SURFACE), Some(HOST_URL_PATH_OPERATION)) => {
            return run_host_reverse_url_case(case);
        }
        (Some(REDIRECT_RESPONSE_SURFACE), Some(REDIRECT_RESPONSE_OPERATION)) => {
            return run_redirect_response_case(case);
        }
        (Some(RESPONSE_SURFACE | JSON_RESPONSE_SURFACE), Some(RESPONSE_OPERATION)) => {
            return run_basic_response_case(case);
        }
        (Some(STREAMING_RESPONSE_SURFACE), Some(RESPONSE_OPERATION)) => {
            return run_streaming_response_case(case);
        }
        (Some(FILE_RESPONSE_SURFACE), Some(RESPONSE_OPERATION)) => {
            return run_file_response_case(case);
        }
        (Some(STATIC_FILES_SURFACE), Some(STATIC_FILES_LOOKUP_PATH_OPERATION)) => {
            return run_static_files_lookup_path_case(case);
        }
        (Some(STATIC_FILES_SURFACE), Some(RESPONSE_OPERATION)) => {
            return run_static_files_case(case);
        }
        (Some("starlette.routing.Mount"), Some("route-dispatch")) => {
            return run_mount_case(case);
        }
        (Some(QUERY_PARAMS_SURFACE), Some(QUERY_PARAMS_OPERATION)) => {
            return run_query_params_case(case);
        }
        (Some(MULTIDICT_SURFACE), Some(MULTIDICT_OPERATION)) => {
            return run_multidict_case(case);
        }
        (Some(MUTABLE_HEADERS_SURFACE), Some(MUTABLE_HEADERS_OPERATION)) => {
            return run_mutable_headers_case(case);
        }
        (Some(COMMA_SEPARATED_STRINGS_SURFACE), Some(COMMA_SEPARATED_STRINGS_OPERATION)) => {
            return run_comma_separated_strings_case(case);
        }
        (Some("starlette.applications.Starlette"), Some("__call__")) => {}
        _ => return Err(String::from("workflow surface or operation is unsupported")),
    }

    run_application_case(case)
}

fn run_timestamp_unsign_case(case: &Value) -> Result<Value, String> {
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
    if string_field(case_object, "surface", context)? != NATIVE_TIMESTAMP_UNSIGN_SURFACE
        || string_field(case_object, "operation", context)? != NATIVE_TIMESTAMP_UNSIGN_OPERATION
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
    let payload = timestamp_unsign(signed_value.as_bytes(), secret_key, now, max_age)
        .map_err(|error| error.to_string())?;
    let case_id = string_field(case_object, "case_id", context)?;

    let mut value = Map::new();
    value.insert(
        observation.to_owned(),
        json!({"encoding": "base64", "data": encode_base64(&payload)}),
    );
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

#[derive(Clone)]
enum NativeProbeFrame {
    Data(Bytes),
    Error { kind: String, message: String },
    Pending,
    End,
}

#[derive(Debug)]
struct NativeProbeBodyError {
    kind: String,
    message: String,
}

impl std::fmt::Display for NativeProbeBodyError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for NativeProbeBodyError {}

struct NativeProbeBody {
    frames: VecDeque<NativeProbeFrame>,
    trace: Arc<Mutex<Vec<Value>>>,
    dropped: Arc<AtomicBool>,
    ended: bool,
}

impl NativeProbeBody {
    fn new(
        frames: Vec<NativeProbeFrame>,
        trace: Arc<Mutex<Vec<Value>>>,
        dropped: Arc<AtomicBool>,
    ) -> Self {
        Self {
            frames: frames.into(),
            trace,
            dropped,
            ended: false,
        }
    }

    fn record(&self, event: Value) {
        if let Ok(mut trace) = self.trace.lock() {
            trace.push(event);
        }
    }
}

impl Body for NativeProbeBody {
    type Data = Bytes;
    type Error = NativeProbeBodyError;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        _context: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        let this = self.as_mut().get_mut();
        if this.ended {
            return Poll::Ready(None);
        }
        match this.frames.front().cloned() {
            Some(NativeProbeFrame::Pending) => {
                this.record(json!({"event": "pending"}));
                Poll::Pending
            }
            Some(NativeProbeFrame::Data(data)) => {
                let _ = this.frames.pop_front();
                this.record(json!({
                    "event": "data",
                    "data_base64": encode_base64(&data),
                }));
                Poll::Ready(Some(Ok(Frame::data(data))))
            }
            Some(NativeProbeFrame::Error { kind, message }) => {
                let _ = this.frames.pop_front();
                this.record(json!({
                    "event": "error",
                    "kind": kind,
                    "message": message,
                }));
                Poll::Ready(Some(Err(NativeProbeBodyError { kind, message })))
            }
            Some(NativeProbeFrame::End) | None => {
                let _ = this.frames.pop_front();
                this.ended = true;
                this.record(json!({"event": "end"}));
                Poll::Ready(None)
            }
        }
    }
}

impl Drop for NativeProbeBody {
    fn drop(&mut self) {
        self.dropped.store(true, Ordering::Release);
    }
}

#[derive(Default)]
struct NativeServiceObservations {
    handler_entered: bool,
    request_chunks: Vec<String>,
    request_error: Option<(String, String)>,
}

fn run_native_service_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "application",
            "request",
            "drive",
            "observations",
        ],
        "native service case",
    )?;
    let case_id = string_field(case, "case_id", "native service case")?;
    if string_field(case, "surface", "native service case")? != "starlette-rs.NativeApplication"
        || string_field(case, "operation", "native service case")? != "service-body-streaming"
    {
        return Err(String::from(
            "case is outside the native service streaming operation",
        ));
    }

    let input_profiles = case
        .get("target_profiles")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native service target_profiles must be an array"))?;
    if input_profiles
        .iter()
        .any(|profile| profile.as_str().is_none())
    {
        return Err(String::from(
            "native service target_profiles must contain strings",
        ));
    }
    let request = object_with_optional_keys(
        case.get("request")
            .ok_or_else(|| String::from("native service case misses request"))?,
        &["method", "uri", "body"],
        &["http_version", "headers", "root_path"],
        "native service request",
    )?;
    let request_body = exact_object(
        request
            .get("body")
            .ok_or_else(|| String::from("native service request misses body"))?,
        &["frames"],
        "native service request body",
    )?;
    let request_frames = parse_native_probe_frames(
        request_body
            .get("frames")
            .ok_or_else(|| String::from("native service request body misses frames"))?,
        "native service request body frames",
    )?;
    let request_trace = Arc::new(Mutex::new(Vec::new()));
    let request_dropped = Arc::new(AtomicBool::new(false));
    let request_body = NativeProbeBody::new(
        request_frames,
        Arc::clone(&request_trace),
        Arc::clone(&request_dropped),
    );

    let observations = Arc::new(Mutex::new(NativeServiceObservations::default()));
    let response_trace = Arc::new(Mutex::new(Vec::new()));
    let response_dropped = Arc::new(AtomicBool::new(false));
    let application = exact_object(
        case.get("application")
            .ok_or_else(|| String::from("native service case misses application"))?,
        &["routes"],
        "native service application",
    )?;
    let route_values = application
        .get("routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| String::from("native service application routes must be non-empty"))?;
    let mut routes = Vec::with_capacity(route_values.len());
    for (index, route_value) in route_values.iter().enumerate() {
        let context = format!("native service route[{index}]");
        let route = exact_object(route_value, &["path", "methods", "endpoint"], &context)?;
        let path = string_field(route, "path", &context)?.to_owned();
        let methods = string_array_field(route, "methods", &context)?;
        let raw_endpoint = route
            .get("endpoint")
            .ok_or_else(|| format!("{context} misses endpoint"))?;
        let endpoint_context = format!("{context}.endpoint");
        let request_projection = raw_endpoint
            .get("response_body_from_request")
            .map(|value| native_request_projection_from_input(value, &endpoint_context))
            .transpose()?;
        let endpoint = if request_projection.is_some() {
            exact_object(
                raw_endpoint,
                &["request_body_action", "response_body_from_request"],
                &endpoint_context,
            )?
        } else {
            exact_object(
                raw_endpoint,
                &["request_body_action", "response_body"],
                &endpoint_context,
            )?
        };
        let request_action = string_field(endpoint, "request_body_action", &context)?.to_owned();
        if !matches!(
            request_action.as_str(),
            "read-all" | "read-all-and-propagate-error" | "leave-unread"
        ) {
            return Err(format!("{context}.request_body_action is unsupported"));
        }
        if request_projection.is_some() && request_action != "leave-unread" {
            return Err(format!(
                "{endpoint_context}.request_body_action must be leave-unread for request projection"
            ));
        }
        let response_frames = if request_projection.is_none() {
            let response_body = exact_object(
                endpoint
                    .get("response_body")
                    .ok_or_else(|| format!("{endpoint_context} misses response_body"))?,
                &["frames"],
                &format!("{endpoint_context}.response_body"),
            )?;
            parse_native_probe_frames(
                response_body
                    .get("frames")
                    .ok_or_else(|| format!("{endpoint_context}.response_body misses frames"))?,
                &format!("{endpoint_context}.response_body.frames"),
            )?
        } else {
            Vec::new()
        };
        let observations = Arc::clone(&observations);
        let response_trace = Arc::clone(&response_trace);
        let response_dropped = Arc::clone(&response_dropped);
        let endpoint = move |mut request: starlette_rs::NativeRequest| {
            let observations = Arc::clone(&observations);
            let response_trace = Arc::clone(&response_trace);
            let response_dropped = Arc::clone(&response_dropped);
            let request_action = request_action.clone();
            let response_frames = response_frames.clone();
            let request_projection = request_projection.clone();
            async move {
                {
                    let mut captured = observations.lock().map_err(|_| {
                        NativeApplicationError::Endpoint(Box::new(io::Error::other(
                            "native service observation lock is poisoned",
                        )))
                    })?;
                    captured.handler_entered = true;
                }
                if request_action != "leave-unread" {
                    let mut chunks = Vec::new();
                    let body = request.body_mut();
                    while let Some(frame) = body.frame().await {
                        match frame {
                            Ok(frame) => {
                                if let Ok(data) = frame.into_data() {
                                    let encoded = encode_base64(&data);
                                    chunks.push(encoded.clone());
                                    if let Ok(mut captured) = observations.lock() {
                                        captured.request_chunks = chunks.clone();
                                    }
                                }
                            }
                            Err(error) => {
                                let error_text = error.to_string();
                                let error_kind =
                                    error.downcast_ref::<NativeProbeBodyError>().map_or_else(
                                        || String::from("body-error"),
                                        |source| source.kind.clone(),
                                    );
                                if let Ok(mut captured) = observations.lock() {
                                    captured.request_chunks = chunks;
                                    captured.request_error = Some((error_kind, error_text));
                                }
                                return Err(NativeApplicationError::Endpoint(error));
                            }
                        }
                    }
                    if let Ok(mut captured) = observations.lock() {
                        captured.request_chunks = chunks;
                    }
                }
                if let Some(projection) = request_projection {
                    let projected = native_request_projection_bytes(&request, &projection)
                        .map_err(|error| {
                            NativeApplicationError::Endpoint(Box::new(io::Error::other(error)))
                        })?;
                    Ok(HttpResponse::new(starlette_rs::native_body(Bytes::from(
                        projected,
                    ))))
                } else {
                    let body =
                        NativeProbeBody::new(response_frames, response_trace, response_dropped);
                    Ok(HttpResponse::new(starlette_rs::box_native_body(body)))
                }
            }
        };
        routes.push(NativeRoute::new(path, methods, endpoint));
    }

    let mut application =
        starlette_rs::NativeApplication::new(routes).map_err(|error| error.to_string())?;
    let method =
        Method::from_bytes(string_field(request, "method", "native service request")?.as_bytes())
            .map_err(|error| format!("native service request method is invalid: {error}"))?;
    let uri = Uri::from_str(string_field(request, "uri", "native service request")?)
        .map_err(|error| format!("native service request URI is invalid: {error}"))?;
    let version = match request
        .get("http_version")
        .and_then(Value::as_str)
        .unwrap_or("1.1")
    {
        "0.9" => http::Version::HTTP_09,
        "1.0" => http::Version::HTTP_10,
        "1.1" => http::Version::HTTP_11,
        "2" => http::Version::HTTP_2,
        "3" => http::Version::HTTP_3,
        value => {
            return Err(format!(
                "native service request HTTP version {value:?} is unsupported"
            ));
        }
    };
    let empty_headers = Value::Array(Vec::new());
    let request_headers = parse_native_headers(
        request.get("headers").unwrap_or(&empty_headers),
        "native service request headers",
    )?;
    let mut native_request = Request::builder()
        .method(method)
        .uri(uri)
        .version(version)
        .body(request_body)
        .map_err(|error| format!("cannot construct native service request: {error}"))?;
    *native_request.headers_mut() = request_headers;
    if let Some(root_path) = request.get("root_path") {
        let root_path = root_path
            .as_str()
            .ok_or_else(|| String::from("native service request root_path must be a string"))?;
        native_request
            .extensions_mut()
            .insert(NativeRequestScope::new().with_root_path(root_path));
    }

    let drive = object_with_optional_keys(
        case.get("drive")
            .ok_or_else(|| String::from("native service case misses drive"))?,
        &["service_future"],
        &["response_body"],
        "native service drive",
    )?;
    let service_mode = string_field(drive, "service_future", "native service drive")?;
    let mut service_error = None;
    let mut response = if service_mode == "resolve" {
        match block_on(tower_service::Service::call(
            &mut application,
            native_request,
        )) {
            Ok(response) => Some(response),
            Err(error) => {
                service_error = Some(native_application_error_message(&error));
                None
            }
        }
    } else if service_mode == "poll-until-pending-then-drop" {
        let mut future = Box::pin(tower_service::Service::call(
            &mut application,
            native_request,
        ));
        let poll = poll_future_once(future.as_mut());
        match poll {
            Poll::Ready(Ok(response)) => Some(response),
            Poll::Ready(Err(error)) => {
                service_error = Some(native_application_error_message(&error));
                None
            }
            Poll::Pending => None,
        }
    } else {
        return Err(String::from(
            "native service drive.service_future is unsupported",
        ));
    };

    let response_drive = drive.get("response_body");
    let mut response_chunks = Vec::new();
    let mut response_error = None;
    let mut response_status = None;
    if let Some(mut response) = response.take() {
        response_status = Some(response.status().as_u16());
        if let Some(response_drive) = response_drive {
            if response_drive == "drop-without-poll" {
                drop(response);
            } else if response_drive == "read-to-end" || response_drive == "read-to-error" {
                block_on(async {
                    while let Some(frame) = response.body_mut().frame().await {
                        match frame {
                            Ok(frame) => {
                                if let Ok(data) = frame.into_data() {
                                    response_chunks.push(encode_base64(&data));
                                }
                            }
                            Err(error) => {
                                let error_kind =
                                    error.downcast_ref::<NativeProbeBodyError>().map_or_else(
                                        || String::from("body-error"),
                                        |source| source.kind.clone(),
                                    );
                                response_error = Some((error_kind, error.to_string()));
                                break;
                            }
                        }
                    }
                });
            } else if let Some(read_schedule) = response_drive.get("read_frames") {
                let reads = read_schedule.as_array().ok_or_else(|| {
                    String::from("native service drive.response_body.read_frames must be an array")
                })?;
                let mut ended = false;
                let counts = reads
                    .iter()
                    .enumerate()
                    .map(|(index, read)| {
                        if read.as_str() == Some("to-end") {
                            Ok(None)
                        } else {
                            read.as_u64().map(Some).ok_or_else(|| {
                                format!("native service read_frames[{index}] must be a positive count or to-end")
                            })
                        }
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                block_on(async {
                    for count in counts {
                        if let Some(count) = count {
                            for _ in 0..count {
                                match response.body_mut().frame().await {
                                    Some(Ok(frame)) => {
                                        if let Ok(data) = frame.into_data() {
                                            response_chunks.push(encode_base64(&data));
                                        }
                                    }
                                    Some(Err(error)) => {
                                        let error_kind = error
                                            .downcast_ref::<NativeProbeBodyError>()
                                            .map_or_else(
                                                || String::from("body-error"),
                                                |source| source.kind.clone(),
                                            );
                                        response_error = Some((error_kind, error.to_string()));
                                        ended = true;
                                        break;
                                    }
                                    None => {
                                        ended = true;
                                        break;
                                    }
                                }
                            }
                        } else {
                            while let Some(frame) = response.body_mut().frame().await {
                                match frame {
                                    Ok(frame) => {
                                        if let Ok(data) = frame.into_data() {
                                            response_chunks.push(encode_base64(&data));
                                        }
                                    }
                                    Err(error) => {
                                        let error_kind = error
                                            .downcast_ref::<NativeProbeBodyError>()
                                            .map_or_else(
                                                || String::from("body-error"),
                                                |source| source.kind.clone(),
                                            );
                                        response_error = Some((error_kind, error.to_string()));
                                        break;
                                    }
                                }
                            }
                            ended = true;
                        }
                        if ended {
                            break;
                        }
                    }
                });
                drop(response);
            } else {
                return Err(String::from(
                    "native service response_body drive is unsupported",
                ));
            }
        } else {
            // An omitted body schedule means the consumer stops after receiving
            // the response and drops its body without polling another frame.
            drop(response);
        }
    }

    let captured = observations
        .lock()
        .map_err(|_| String::from("native service observation lock is poisoned"))?;
    let request_chunks = captured.request_chunks.clone();
    let handler_entered = captured.handler_entered;
    let request_error = captured.request_error.clone();
    drop(captured);
    let response_available = response_status.map(|status| json!({"status": status}));
    let mut values = Map::new();
    values.insert(String::from("handler-entry"), json!(handler_entered));
    values.insert(String::from("request-body-chunks"), json!(request_chunks));
    values.insert(String::from("response-body-chunks"), json!(response_chunks));
    values.insert(
        String::from("response-available"),
        response_available.unwrap_or(Value::Null),
    );
    values.insert(
        String::from("request-body-error-propagation"),
        request_error.map_or(Value::Null, |(_kind, message)| json!({"message": message})),
    );
    values.insert(
        String::from("response-body-error-propagation"),
        response_error.map_or(Value::Null, |(_kind, message)| json!({"message": message})),
    );
    values.insert(
        String::from("service-error"),
        service_error.map_or(Value::Null, |message| json!({"message": message})),
    );
    native_observation_result(case_id, case, values, "native service")
}

#[derive(Clone, Default)]
struct NativeServiceObservation {
    path_params: Vec<(String, String)>,
    root_path: Option<String>,
    app_root_path: Option<String>,
}

#[derive(Clone)]
enum NativeServiceEndpointOutput {
    Frames(Vec<NativeProbeFrame>),
    ResponseBodyFromRequest(Vec<String>),
    EchoPathParams,
}

#[derive(Clone)]
struct NativeRequestProjection {
    fields: Vec<String>,
    header_names: Vec<String>,
}

fn native_request_projection_from_input(
    value: &Value,
    context: &str,
) -> Result<NativeRequestProjection, String> {
    let projection = exact_object(value, &["fields", "header_names"], context)?;
    let fields = string_array_field(projection, "fields", context)?;
    let header_names = string_array_field(projection, "header_names", context)?;
    let supported_fields = [
        "method",
        "uri",
        "path",
        "query",
        "http_version",
        "headers",
        "path_params",
        "root_path",
    ];
    if fields.is_empty()
        || fields
            .iter()
            .any(|field| !supported_fields.contains(&field.as_str()))
        || fields.iter().collect::<HashSet<_>>().len() != fields.len()
        || header_names.iter().collect::<HashSet<_>>().len() != header_names.len()
        || fields.iter().any(|field| field == "headers") == header_names.is_empty()
    {
        return Err(format!("{context} fields or header_names are unsupported"));
    }
    for name in &header_names {
        HeaderName::from_bytes(name.as_bytes())
            .map_err(|error| format!("{context} header name is invalid: {error}"))?;
    }
    Ok(NativeRequestProjection {
        fields,
        header_names,
    })
}

fn native_request_projection_bytes(
    request: &NativeRequest,
    projection: &NativeRequestProjection,
) -> Result<Vec<u8>, String> {
    let fields = projection
        .fields
        .iter()
        .map(|field| {
            let value = match field.as_str() {
                "method" => Value::String(request.method().as_str().to_owned()),
                "uri" => Value::String(request.uri().to_string()),
                "path" => Value::String(request.path().to_owned()),
                "query" => request
                    .query()
                    .map_or(Value::Null, |query| Value::String(query.to_owned())),
                "http_version" => Value::String(
                    native_http_version_name(request.version())
                        .strip_prefix("HTTP/")
                        .unwrap_or_else(|| native_http_version_name(request.version()))
                        .to_owned(),
                ),
                "headers" => {
                    let headers = projection
                        .header_names
                        .iter()
                        .map(|name| {
                            let header_name = HeaderName::from_bytes(name.as_bytes())
                                .map_err(|error| error.to_string())?;
                            let values = request
                                .headers()
                                .get_all(header_name)
                                .iter()
                                .map(|value| {
                                    value
                                        .to_str()
                                        .map(str::to_owned)
                                        .map_err(|error| error.to_string())
                                })
                                .collect::<Result<Vec<_>, _>>()?;
                            Ok(json!([name, values]))
                        })
                        .collect::<Result<Vec<_>, String>>()?;
                    Value::Array(headers)
                }
                "path_params" => json!(request.path_params()),
                "root_path" => Value::String(request.root_path().to_owned()),
                _ => {
                    return Err(format!(
                        "native request projection field {field:?} is unsupported"
                    ));
                }
            };
            Ok(json!([field, value]))
        })
        .collect::<Result<Vec<_>, String>>()?;
    serde_json::to_vec(&Value::Array(fields)).map_err(|error| error.to_string())
}

type NativeServiceObservationHandle = Arc<Mutex<Option<NativeServiceObservation>>>;

fn native_route_from_input(
    value: &Value,
    observation: NativeServiceObservationHandle,
    context: &str,
) -> Result<NativeRoute, String> {
    let route = exact_object(value, &["path", "methods", "endpoint"], context)?;
    let path = string_field(route, "path", context)?.to_owned();
    let methods = string_array_field(route, "methods", context)?;
    let endpoint = route
        .get("endpoint")
        .ok_or_else(|| format!("{context}.endpoint is missing"))?;
    let endpoint_context = format!("{context}.endpoint");
    let output = if endpoint.get("action").is_some() {
        let endpoint = exact_object(endpoint, &["action"], &endpoint_context)?;
        if string_field(endpoint, "action", &endpoint_context)? != "echo-path-params" {
            return Err(format!("{endpoint_context}.action is unsupported"));
        }
        NativeServiceEndpointOutput::EchoPathParams
    } else if endpoint.get("response_body_from_request").is_some() {
        let endpoint = exact_object(
            endpoint,
            &["request_body_action", "response_body_from_request"],
            &endpoint_context,
        )?;
        if string_field(endpoint, "request_body_action", &endpoint_context)? != "leave-unread" {
            return Err(format!(
                "{endpoint_context}.request_body_action is unsupported"
            ));
        }
        let fields = endpoint
            .get("response_body_from_request")
            .and_then(Value::as_array)
            .ok_or_else(|| {
                format!("{endpoint_context}.response_body_from_request must be an array")
            })?
            .iter()
            .enumerate()
            .map(|(index, field)| {
                field.as_str().map(str::to_owned).ok_or_else(|| {
                    format!(
                        "{endpoint_context}.response_body_from_request[{index}] must be a string"
                    )
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        if fields.iter().any(|field| {
            !["path", "root_path", "app_root_path", "path_params"].contains(&field.as_str())
        }) {
            return Err(format!(
                "{endpoint_context}.response_body_from_request has an unsupported field"
            ));
        }
        NativeServiceEndpointOutput::ResponseBodyFromRequest(fields)
    } else {
        let endpoint = exact_object(
            endpoint,
            &["request_body_action", "response_body"],
            &endpoint_context,
        )?;
        if string_field(endpoint, "request_body_action", &endpoint_context)? != "leave-unread" {
            return Err(format!(
                "{endpoint_context}.request_body_action is unsupported"
            ));
        }
        let body = exact_object(
            endpoint
                .get("response_body")
                .ok_or_else(|| format!("{endpoint_context}.response_body is missing"))?,
            &["frames"],
            &format!("{endpoint_context}.response_body"),
        )?;
        NativeServiceEndpointOutput::Frames(parse_native_probe_frames(
            body.get("frames")
                .ok_or_else(|| format!("{endpoint_context}.response_body.frames is missing"))?,
            &format!("{endpoint_context}.response_body.frames"),
        )?)
    };

    Ok(NativeRoute::new(
        path,
        methods,
        move |request: NativeRequest| {
            let observation = Arc::clone(&observation);
            let output = output.clone();
            async move {
                let captured = NativeServiceObservation {
                    path_params: request.path_params().to_vec(),
                    root_path: Some(request.root_path().to_owned()),
                    app_root_path: Some(request.app_root_path().to_owned()),
                };
                let mut slot = observation.lock().map_err(|_| {
                    NativeApplicationError::Endpoint(Box::new(io::Error::other(
                        "native service observation lock is poisoned",
                    )))
                })?;
                *slot = Some(captured);
                drop(slot);

                let body = match output {
                    NativeServiceEndpointOutput::Frames(frames) => {
                        let trace = Arc::new(Mutex::new(Vec::new()));
                        let dropped = Arc::new(AtomicBool::new(false));
                        let body = NativeProbeBody::new(frames, trace, dropped);
                        starlette_rs::box_native_body(body)
                    }
                    NativeServiceEndpointOutput::ResponseBodyFromRequest(fields) => {
                        let pairs = fields
                            .iter()
                            .map(|field| {
                                let value = match field.as_str() {
                                    "path" => Value::String(request.path().to_owned()),
                                    "root_path" => Value::String(request.root_path().to_owned()),
                                    "app_root_path" => {
                                        Value::String(request.app_root_path().to_owned())
                                    }
                                    "path_params" => json!(request.path_params()),
                                    _ => Value::Null,
                                };
                                json!([field, value])
                            })
                            .collect::<Vec<_>>();
                        let bytes = serde_json::to_vec(&Value::Array(pairs))
                            .map_err(|error| NativeApplicationError::Endpoint(Box::new(error)))?;
                        starlette_rs::native_body(Bytes::from(bytes))
                    }
                    NativeServiceEndpointOutput::EchoPathParams => {
                        let bytes = serde_json::to_vec(&json!(request.path_params()))
                            .map_err(|error| NativeApplicationError::Endpoint(Box::new(error)))?;
                        starlette_rs::native_body(Bytes::from(bytes))
                    }
                };
                Ok(HttpResponse::new(body))
            }
        },
    ))
}

fn native_children_from_input(
    value: &Value,
    observation: NativeServiceObservationHandle,
    context: &str,
) -> Result<Vec<NativeApplicationChild>, String> {
    let children = value
        .as_array()
        .filter(|children| !children.is_empty())
        .ok_or_else(|| format!("{context} must be a non-empty array"))?;
    children
        .iter()
        .enumerate()
        .map(|(index, child)| {
            let child_context = format!("{context}[{index}]");
            let kind = child
                .get("kind")
                .and_then(Value::as_str)
                .ok_or_else(|| format!("{child_context}.kind must be a string"))?;
            match kind {
                "mount" => {
                    let child =
                        exact_object(child, &["kind", "path", "application"], &child_context)?;
                    let path = string_field(child, "path", &child_context)?;
                    let application_input = exact_object(
                        child
                            .get("application")
                            .ok_or_else(|| format!("{child_context}.application is missing"))?,
                        &["routes"],
                        &format!("{child_context}.application"),
                    )?;
                    let route_values = application_input
                        .get("routes")
                        .and_then(Value::as_array)
                        .filter(|routes| !routes.is_empty())
                        .ok_or_else(|| {
                            format!("{child_context}.application.routes must be a non-empty array")
                        })?;
                    let routes = route_values
                        .iter()
                        .enumerate()
                        .map(|(route_index, route)| {
                            native_route_from_input(
                                route,
                                Arc::clone(&observation),
                                &format!("{child_context}.application.routes[{route_index}]"),
                            )
                        })
                        .collect::<Result<Vec<_>, _>>()?;
                    let child_application =
                        NativeServiceApplication::new(routes).map_err(|error| error.to_string())?;
                    let mount = NativeServiceMount::new(path, child_application)
                        .map_err(|error| error.to_string())?;
                    Ok(NativeApplicationChild::Mount(mount))
                }
                "route" => native_route_from_input(child, Arc::clone(&observation), &child_context)
                    .map(NativeApplicationChild::Route),
                _ => Err(format!("{child_context}.kind is unsupported")),
            }
        })
        .collect()
}

fn native_request_scope_from_input(value: Option<&Value>) -> Result<NativeRequestScope, String> {
    let Some(value) = value else {
        return Ok(NativeRequestScope::new());
    };
    let scope = object_with_optional_keys(
        value,
        &[],
        &["root_path", "app_root_path", "path_params"],
        "native service request scope",
    )?;
    let mut result = NativeRequestScope::new();
    if let Some(root_path) = scope.get("root_path") {
        result = result.with_root_path(
            root_path
                .as_str()
                .ok_or_else(|| String::from("native service scope.root_path must be a string"))?,
        );
    }
    if let Some(app_root_path) = scope.get("app_root_path") {
        result =
            result.with_app_root_path(app_root_path.as_str().ok_or_else(|| {
                String::from("native service scope.app_root_path must be a string")
            })?);
    }
    let mut path_params = Vec::new();
    if let Some(raw_params) = scope.get("path_params") {
        let raw_params = raw_params
            .as_array()
            .ok_or_else(|| String::from("native service scope.path_params must be an array"))?;
        for (index, raw_param) in raw_params.iter().enumerate() {
            let context = format!("native service scope.path_params[{index}]");
            let param = exact_object(raw_param, &["name", "value", "converter"], &context)?;
            let name = string_field(param, "name", &context)?.to_owned();
            let value = match param.get("value") {
                Some(Value::String(value)) => value.clone(),
                Some(Value::Number(value)) => value.to_string(),
                _ => return Err(format!("{context}.value must be a string or number")),
            };
            let converter = match string_field(param, "converter", &context)? {
                "str" => PathConverter::String,
                "int" => PathConverter::Integer,
                "float" => PathConverter::Float,
                "path" => PathConverter::Path,
                "uuid" => PathConverter::Uuid,
                _ => return Err(format!("{context}.converter is unsupported")),
            };
            path_params.push(PathParameterCapture {
                name,
                value,
                converter,
            });
        }
    }
    Ok(result.with_path_params(path_params))
}

fn native_service_request_from_input(
    value: &Value,
    include_host: bool,
) -> Result<Request<NativeProbeBody>, String> {
    let request = if include_host {
        object_with_optional_keys(
            value,
            &["method", "uri", "host_header", "body"],
            &["scope"],
            "native host request",
        )?
    } else {
        object_with_optional_keys(
            value,
            &["method", "uri", "body"],
            &["scope"],
            "native mounted request",
        )?
    };
    let body = exact_object(
        request
            .get("body")
            .ok_or_else(|| String::from("native service request body is missing"))?,
        &["frames"],
        "native service request body",
    )?;
    let frames = parse_native_probe_frames(
        body.get("frames")
            .ok_or_else(|| String::from("native service request body.frames is missing"))?,
        "native service request body.frames",
    )?;
    let request_body = NativeProbeBody::new(
        frames,
        Arc::new(Mutex::new(Vec::new())),
        Arc::new(AtomicBool::new(false)),
    );
    let method =
        Method::from_bytes(string_field(request, "method", "native service request")?.as_bytes())
            .map_err(|error| format!("native service request method is invalid: {error}"))?;
    let uri = Uri::from_str(string_field(request, "uri", "native service request")?)
        .map_err(|error| format!("native service request URI is invalid: {error}"))?;
    let scope = native_request_scope_from_input(request.get("scope"))?;
    let mut builder = Request::builder().method(method).uri(uri);
    if let Some(host_header) = request.get("host_header") {
        match host_header {
            Value::Null => {}
            Value::String(host) => builder = builder.header(http::header::HOST, host),
            _ => {
                return Err(String::from(
                    "native host request.host_header must be a string or null",
                ));
            }
        }
    }
    let mut request = builder
        .body(request_body)
        .map_err(|error| format!("cannot construct native service request: {error}"))?;
    request.extensions_mut().insert(scope);
    Ok(request)
}

fn native_service_response_observation(
    case_id: &str,
    case: &Map<String, Value>,
    mut response: Option<starlette_rs::NativeHttpResponse>,
    service_error: Option<String>,
    observation: &NativeServiceObservationHandle,
    context: &str,
) -> Result<Value, String> {
    let mut response_body_chunks = Vec::new();
    let mut status = None;
    let mut service_error = service_error;
    let response_scope = response
        .as_ref()
        .and_then(|response| response.extensions().get::<NativeRequestScope>())
        .cloned();
    if let Some(mut response) = response.take() {
        status = Some(response.status().as_u16());
        block_on(async {
            while let Some(frame) = response.body_mut().frame().await {
                match frame {
                    Ok(frame) => {
                        if let Ok(data) = frame.into_data() {
                            response_body_chunks.push(encode_base64(&data));
                        }
                    }
                    Err(error) => {
                        service_error = Some(error.to_string());
                        break;
                    }
                }
            }
        });
    }
    let captured = observation
        .lock()
        .map_err(|_| format!("{context} observation lock is poisoned"))?
        .clone();
    let (path_params, root_path, app_root_path) = if let Some(captured) = captured {
        let root_path = captured.root_path.unwrap_or_default();
        let app_root_path = captured.app_root_path.unwrap_or_else(|| root_path.clone());
        (captured.path_params, root_path, app_root_path)
    } else if let Some(scope) = response_scope {
        let root_path = scope.root_path().to_owned();
        let app_root_path = scope
            .app_root_path()
            .unwrap_or_else(|| scope.root_path())
            .to_owned();
        let path_params = scope
            .path_params()
            .iter()
            .map(|parameter| (parameter.name.clone(), parameter.value.clone()))
            .collect::<Vec<_>>();
        (path_params, root_path, app_root_path)
    } else {
        (Vec::new(), String::new(), String::new())
    };
    let values = Map::from_iter([
        (
            String::from("status"),
            status.map_or(Value::Null, |value| json!(value)),
        ),
        (
            String::from("response_body_chunks"),
            json!(response_body_chunks),
        ),
        (String::from("path_params"), json!(path_params)),
        (String::from("root_path"), json!(root_path)),
        (String::from("app_root_path"), json!(app_root_path)),
        (
            String::from("service_error"),
            service_error.map_or(Value::Null, Value::String),
        ),
    ]);
    native_observation_result(case_id, case, values, context)
}

fn run_native_mounted_child_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "application",
            "request",
            "drive",
            "observations",
        ],
        "native mounted child case",
    )?;
    let case_id = string_field(case, "case_id", "native mounted child case")?;
    if string_field(case, "surface", "native mounted child case")?
        != "starlette-rs.NativeApplication"
        || string_field(case, "operation", "native mounted child case")?
            != NATIVE_SERVICE_MOUNTED_CHILD_OPERATION
    {
        return Err(String::from(
            "case is outside the native mounted-child operation",
        ));
    }
    let observation = Arc::new(Mutex::new(None));
    let application_input = exact_object(
        case.get("application")
            .ok_or_else(|| String::from("native mounted child case misses application"))?,
        &["children"],
        "native mounted child application",
    )?;
    let children = native_children_from_input(
        application_input
            .get("children")
            .ok_or_else(|| String::from("native mounted child application misses children"))?,
        Arc::clone(&observation),
        "native mounted child application.children",
    )?;
    let mut application =
        NativeServiceApplication::with_children(children).map_err(|error| error.to_string())?;
    let request = native_service_request_from_input(
        case.get("request")
            .ok_or_else(|| String::from("native mounted child case misses request"))?,
        false,
    )?;
    let (response, service_error) =
        match block_on(tower_service::Service::call(&mut application, request)) {
            Ok(response) => (Some(response), None),
            Err(error) => (None, Some(native_application_error_message(&error))),
        };
    native_service_response_observation(
        case_id,
        case,
        response,
        service_error,
        &observation,
        "native mounted child",
    )
}

fn run_native_host_routing_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "application",
            "request",
            "drive",
            "observations",
        ],
        "native host routing case",
    )?;
    let case_id = string_field(case, "case_id", "native host routing case")?;
    if string_field(case, "surface", "native host routing case")?
        != "starlette-rs.NativeHostApplication"
        || string_field(case, "operation", "native host routing case")?
            != NATIVE_SERVICE_HOST_ROUTING_OPERATION
    {
        return Err(String::from(
            "case is outside the native host-routing operation",
        ));
    }
    let observation = Arc::new(Mutex::new(None));
    let application_input = exact_object(
        case.get("application")
            .ok_or_else(|| String::from("native host routing case misses application"))?,
        &["host_routes"],
        "native host application",
    )?;
    let host_values = application_input
        .get("host_routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| String::from("native host application.host_routes must be non-empty"))?;
    let mut host_routes = Vec::with_capacity(host_values.len());
    for (index, value) in host_values.iter().enumerate() {
        let context = format!("native host application.host_routes[{index}]");
        let value = exact_object(value, &["host", "routes"], &context)?;
        let host = HostPattern::new(string_field(value, "host", &context)?)
            .map_err(|error| error.to_string())?;
        let route_values = value
            .get("routes")
            .and_then(Value::as_array)
            .filter(|routes| !routes.is_empty())
            .ok_or_else(|| format!("{context}.routes must be a non-empty array"))?;
        let routes = route_values
            .iter()
            .enumerate()
            .map(|(route_index, route)| {
                native_route_from_input(
                    route,
                    Arc::clone(&observation),
                    &format!("{context}.routes[{route_index}]"),
                )
            })
            .collect::<Result<Vec<_>, _>>()?;
        host_routes.push(NativeHostRoute::new(host, routes));
    }
    let mut application =
        NativeHostApplication::new(host_routes).map_err(|error| error.to_string())?;
    let request = native_service_request_from_input(
        case.get("request")
            .ok_or_else(|| String::from("native host routing case misses request"))?,
        true,
    )?;
    let (response, service_error) =
        match block_on(tower_service::Service::call(&mut application, request)) {
            Ok(response) => (Some(response), None),
            Err(error) => (None, Some(native_application_error_message(&error))),
        };
    native_service_response_observation(
        case_id,
        case,
        response,
        service_error,
        &observation,
        "native host routing",
    )
}

#[derive(Clone, Debug)]
enum InputRegexNode {
    Bytes(Box<[bool; 256]>),
    Sequence(Vec<Self>),
    Alternative(Vec<Self>),
    Repeat { inner: Box<Self>, minimum: usize },
}

impl InputRegexNode {
    fn matches_from(&self, input: &[u8], start: usize) -> BTreeSet<usize> {
        match self {
            Self::Bytes(accepted) => {
                let mut positions = BTreeSet::new();
                if let Some(byte) = input.get(start) {
                    if accepted[usize::from(*byte)] {
                        if let Some(next_start) = start.checked_add(1) {
                            positions.insert(next_start);
                        }
                    }
                }
                positions
            }
            Self::Sequence(nodes) => {
                let mut positions = BTreeSet::from([start]);
                for node in nodes {
                    let mut next = BTreeSet::new();
                    for position in positions {
                        next.extend(node.matches_from(input, position));
                    }
                    positions = next;
                    if positions.is_empty() {
                        break;
                    }
                }
                positions
            }
            Self::Alternative(nodes) => nodes
                .iter()
                .flat_map(|node| node.matches_from(input, start))
                .collect(),
            Self::Repeat { inner, minimum } => {
                let mut reachable = BTreeSet::new();
                let mut frontier = if *minimum == 0 {
                    BTreeSet::from([start])
                } else {
                    inner.matches_from(input, start)
                };
                reachable.extend(frontier.iter().copied());
                loop {
                    let mut next = BTreeSet::new();
                    for position in &frontier {
                        next.extend(
                            inner
                                .matches_from(input, *position)
                                .into_iter()
                                .filter(|candidate| candidate > position),
                        );
                    }
                    next.retain(|position| !reachable.contains(position));
                    if next.is_empty() {
                        break;
                    }
                    reachable.extend(next.iter().copied());
                    frontier = next;
                }
                reachable
            }
        }
    }

    fn matches_entire_input(&self, input: &str) -> bool {
        self.matches_from(input.as_bytes(), 0)
            .contains(&input.len())
    }
}

struct InputRegexParser<'a> {
    pattern: &'a [u8],
    offset: usize,
}

impl<'a> InputRegexParser<'a> {
    fn parse(pattern: &'a str) -> Result<InputRegexNode, String> {
        let mut parser = Self {
            pattern: pattern.as_bytes(),
            offset: 0,
        };
        let expression = parser.parse_alternative()?;
        if parser.offset != parser.pattern.len() {
            return Err(String::from("converter regex has trailing syntax"));
        }
        Ok(expression)
    }

    fn parse_alternative(&mut self) -> Result<InputRegexNode, String> {
        let mut alternatives = vec![InputRegexNode::Sequence(self.parse_sequence()?)];
        while self.peek() == Some(b'|') {
            checked_usize_increment(&mut self.offset, "converter regex offset")?;
            alternatives.push(InputRegexNode::Sequence(self.parse_sequence()?));
        }
        if alternatives.len() == 1 {
            alternatives
                .pop()
                .ok_or_else(|| String::from("converter regex alternative is missing"))
        } else {
            Ok(InputRegexNode::Alternative(alternatives))
        }
    }

    fn parse_sequence(&mut self) -> Result<Vec<InputRegexNode>, String> {
        let mut nodes = Vec::new();
        while let Some(byte) = self.peek() {
            if byte == b')' || byte == b'|' {
                break;
            }
            let atom = self.parse_atom()?;
            let node = match self.peek() {
                Some(b'*') => {
                    checked_usize_increment(&mut self.offset, "converter regex offset")?;
                    InputRegexNode::Repeat {
                        inner: Box::new(atom),
                        minimum: 0,
                    }
                }
                Some(b'+') => {
                    checked_usize_increment(&mut self.offset, "converter regex offset")?;
                    InputRegexNode::Repeat {
                        inner: Box::new(atom),
                        minimum: 1,
                    }
                }
                Some(b'?') => {
                    checked_usize_increment(&mut self.offset, "converter regex offset")?;
                    InputRegexNode::Repeat {
                        inner: Box::new(atom),
                        minimum: 0,
                    }
                }
                Some(b'{') => {
                    return Err(String::from(
                        "converter regex counted repeats are unsupported",
                    ));
                }
                _ => atom,
            };
            nodes.push(node);
        }
        Ok(nodes)
    }

    fn parse_atom(&mut self) -> Result<InputRegexNode, String> {
        let byte = self
            .next()
            .ok_or_else(|| String::from("converter regex atom is missing"))?;
        match byte {
            b'[' => self.parse_character_class(),
            b'(' => {
                let group_prefix_end =
                    checked_usize_add(self.offset, 2, "converter regex group prefix")?;
                if self.pattern.get(self.offset..group_prefix_end) == Some(b"?:") {
                    self.offset = group_prefix_end;
                }
                let expression = self.parse_alternative()?;
                if self.next() != Some(b')') {
                    return Err(String::from("converter regex group is not closed"));
                }
                Ok(expression)
            }
            b'.' => Ok(InputRegexNode::Bytes(Box::new([true; 256]))),
            b'\\' => self.parse_literal(),
            b')' | b'|' | b'*' | b'+' | b'?' => Err(String::from(
                "converter regex has an unexpected metacharacter",
            )),
            literal => Ok(Self::literal_node(literal)),
        }
    }

    fn parse_character_class(&mut self) -> Result<InputRegexNode, String> {
        let mut accepted = [false; 256];
        let negated = self.peek() == Some(b'^');
        if negated {
            checked_usize_increment(&mut self.offset, "converter regex offset")?;
        }
        let mut found = false;
        while let Some(byte) = self.peek() {
            if byte == b']' {
                checked_usize_increment(&mut self.offset, "converter regex offset")?;
                if !found {
                    return Err(String::from("converter regex character class is empty"));
                }
                if negated {
                    for value in &mut accepted {
                        *value = !*value;
                    }
                }
                return Ok(InputRegexNode::Bytes(Box::new(accepted)));
            }
            let left = self.parse_class_byte()?;
            let next_offset = checked_usize_add(self.offset, 1, "converter regex offset")?;
            if self.peek() == Some(b'-') && self.pattern.get(next_offset) != Some(&b']') {
                self.offset = next_offset;
                let right = self.parse_class_byte()?;
                if left > right {
                    return Err(String::from("converter regex character range is reversed"));
                }
                for value in left..=right {
                    accepted[usize::from(value)] = true;
                }
            } else {
                accepted[usize::from(left)] = true;
            }
            found = true;
        }
        Err(String::from(
            "converter regex character class is not closed",
        ))
    }

    fn parse_class_byte(&mut self) -> Result<u8, String> {
        match self.next() {
            Some(b'\\') => self
                .next()
                .ok_or_else(|| String::from("converter regex class escape is incomplete")),
            Some(byte) => Ok(byte),
            None => Err(String::from("converter regex class byte is missing")),
        }
    }

    fn parse_literal(&mut self) -> Result<InputRegexNode, String> {
        self.next()
            .map(Self::literal_node)
            .ok_or_else(|| String::from("converter regex escape is incomplete"))
    }

    fn literal_node(byte: u8) -> InputRegexNode {
        let mut accepted = [false; 256];
        accepted[usize::from(byte)] = true;
        InputRegexNode::Bytes(Box::new(accepted))
    }

    fn peek(&self) -> Option<u8> {
        self.pattern.get(self.offset).copied()
    }

    fn next(&mut self) -> Option<u8> {
        let byte = self.peek()?;
        self.offset = self.offset.checked_add(1)?;
        Some(byte)
    }
}

#[derive(Debug)]
struct InputCustomPathConverter {
    regex: InputRegexNode,
    conversion: String,
    formatting: String,
}

impl CustomPathConverter for InputCustomPathConverter {
    fn matches(&self, value: &str) -> bool {
        self.regex.matches_entire_input(value)
    }

    fn convert(&self, value: &str) -> String {
        match self.conversion.as_str() {
            "lowercase" => value.to_lowercase(),
            "uppercase" => value.to_uppercase(),
            _ => String::from(value),
        }
    }

    fn to_string(&self, value: &str) -> Result<String, String> {
        let value = match self.formatting.as_str() {
            "lowercase" => value.to_lowercase(),
            "uppercase" => value.to_uppercase(),
            _ => String::from(value),
        };
        Ok(value)
    }
}

fn custom_converter_registry_from_input(
    value: &Value,
    context: &str,
) -> Result<CustomPathConverterRegistry, String> {
    let converters = value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    let mut registry = CustomPathConverterRegistry::new();
    for (index, raw_converter) in converters.iter().enumerate() {
        let converter_context = format!("{context}[{index}]");
        let raw_converter = exact_object(
            raw_converter,
            &["name", "regex", "convert", "to_string"],
            &converter_context,
        )?;
        let name = string_field(raw_converter, "name", &converter_context)?;
        let regex =
            InputRegexParser::parse(string_field(raw_converter, "regex", &converter_context)?)?;
        let conversion = string_field(raw_converter, "convert", &converter_context)?;
        let formatting = string_field(raw_converter, "to_string", &converter_context)?;
        if !["identity", "lowercase", "uppercase"].contains(&conversion)
            || !["identity", "lowercase", "uppercase"].contains(&formatting)
        {
            return Err(format!(
                "{converter_context} conversion mode is unsupported"
            ));
        }
        registry
            .register_converter(
                name,
                InputCustomPathConverter {
                    regex,
                    conversion: conversion.to_owned(),
                    formatting: formatting.to_owned(),
                },
            )
            .map_err(|error| error.to_string())?;
    }
    Ok(registry)
}

fn custom_converter_case_error(
    case_id: &str,
    case: &Map<String, Value>,
    error: String,
) -> Result<Value, String> {
    let mut values = Map::new();
    values.insert(String::from("error"), Value::String(error));
    values.insert(String::from("match"), Value::Null);
    native_observation_result(case_id, case, values, "native custom converter match")
}

fn run_native_service_custom_converter_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "converters",
            "application",
            "request",
            "observations",
        ],
        "native service custom converter case",
    )?;
    let case_id = string_field(case, "case_id", "native service custom converter case")?;
    if string_field(case, "surface", "native service custom converter case")?
        != "starlette-rs.NativeApplication"
        || string_field(case, "operation", "native service custom converter case")?
            != NATIVE_SERVICE_CUSTOM_CONVERTER_OPERATION
    {
        return Err(String::from(
            "case is outside the native service custom-converter operation",
        ));
    }

    let registry = custom_converter_registry_from_input(
        case.get("converters").ok_or_else(|| {
            String::from("native service custom converter case misses converters")
        })?,
        "native service custom converters",
    )?;
    let application_input = exact_object(
        case.get("application").ok_or_else(|| {
            String::from("native service custom converter case misses application")
        })?,
        &["routes"],
        "native service custom converter application",
    )?;
    let route_values = application_input
        .get("routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| {
            String::from("native service custom converter application routes must be non-empty")
        })?;
    let observation = Arc::new(Mutex::new(None));
    let routes = route_values
        .iter()
        .enumerate()
        .map(|(index, route)| {
            native_route_from_input(
                route,
                Arc::clone(&observation),
                &format!("native service custom converter route[{index}]"),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    let mut application = NativeServiceApplication::with_custom_converters(routes, registry)
        .map_err(|error| error.to_string())?;
    let request = native_service_request_from_input(
        case.get("request")
            .ok_or_else(|| String::from("native service custom converter case misses request"))?,
        false,
    )?;
    let response = block_on(tower_service::Service::call(&mut application, request))
        .map_err(|error| error.to_string())?;
    native_service_response_observation(
        case_id,
        case,
        Some(response),
        None,
        &observation,
        "native service custom converter",
    )
}

fn run_native_custom_converter_match_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "converters",
            "routes",
            "match",
            "observations",
        ],
        "native custom converter match case",
    )?;
    let case_id = string_field(case, "case_id", "native custom converter match case")?;
    if string_field(case, "surface", "native custom converter match case")?
        != "starlette-rs.RouteTable"
        || string_field(case, "operation", "native custom converter match case")?
            != NATIVE_ROUTE_TABLE_CUSTOM_CONVERTER_OPERATION
    {
        return Err(String::from(
            "case is outside the native custom-converter match operation",
        ));
    }
    let result = (|| {
        let registry = custom_converter_registry_from_input(
            case.get("converters")
                .ok_or_else(|| String::from("native custom converter case misses converters"))?,
            "native custom converters",
        )?;
        let mut table = RouteTable::with_custom_converters(registry);
        let routes = case
            .get("routes")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("native custom converter routes must be an array"))?;
        for (index, raw_route) in routes.iter().enumerate() {
            let context = format!("native custom converter routes[{index}]");
            let route = exact_object(raw_route, &["path", "methods"], &context)?;
            table
                .add_route(
                    string_field(route, "path", &context)?,
                    string_array_field(route, "methods", &context)?,
                )
                .map_err(|error| error.to_string())?;
        }
        let lookup = exact_object(
            case.get("match")
                .ok_or_else(|| String::from("native custom converter case misses match"))?,
            &["path", "method"],
            "native custom converter match input",
        )?;
        let route_match = table.matches_detailed(
            string_field(lookup, "path", "native custom converter match input")?,
            string_field(lookup, "method", "native custom converter match input")?,
        );
        Ok::<_, String>(match route_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            } => json!({
                "route_index": route_index,
                "path_params": path_params,
            }),
            DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => {
                Value::Null
            }
        })
    })();
    match result {
        Ok(route_match) => {
            let values = Map::from_iter([
                (String::from("match"), route_match),
                (String::from("error"), Value::Null),
            ]);
            native_observation_result(case_id, case, values, "native custom converter match")
        }
        Err(error) => custom_converter_case_error(case_id, case, error),
    }
}

fn run_native_custom_converter_url_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "converters",
            "route",
            "lookup",
            "observations",
        ],
        "native custom converter URL case",
    )?;
    let case_id = string_field(case, "case_id", "native custom converter URL case")?;
    if string_field(case, "surface", "native custom converter URL case")?
        != "starlette-rs.NamedRoute"
        || string_field(case, "operation", "native custom converter URL case")?
            != NATIVE_NAMED_ROUTE_CUSTOM_CONVERTER_OPERATION
    {
        return Err(String::from(
            "case is outside the native custom-converter URL operation",
        ));
    }
    let result = (|| {
        let registry = custom_converter_registry_from_input(
            case.get("converters").ok_or_else(|| {
                String::from("native custom converter URL case misses converters")
            })?,
            "native custom converters",
        )?;
        let route_input = exact_object(
            case.get("route")
                .ok_or_else(|| String::from("native custom converter URL case misses route"))?,
            &["path", "name"],
            "native custom converter route",
        )?;
        let route = starlette_rs::NamedRoute::new_with_custom_converters(
            string_field(route_input, "path", "native custom converter route")?,
            string_field(route_input, "name", "native custom converter route")?,
            &registry,
        )
        .map_err(|error| error.to_string())?;
        let lookup = exact_object(
            case.get("lookup")
                .ok_or_else(|| String::from("native custom converter URL case misses lookup"))?,
            &["name", "path_params"],
            "native custom converter URL lookup",
        )?;
        let params = lookup
            .get("path_params")
            .and_then(Value::as_object)
            .ok_or_else(|| {
                String::from("native custom converter URL path_params must be an object")
            })?
            .iter()
            .map(|(name, value)| {
                value
                    .as_str()
                    .map(|value| (name.clone(), value.to_owned()))
                    .ok_or_else(|| {
                        String::from("native custom converter URL values must be strings")
                    })
            })
            .collect::<Result<Vec<_>, _>>()?;
        route
            .url_path_for(
                string_field(lookup, "name", "native custom converter URL lookup")?,
                &params,
            )
            .map(|url| json!({"path": url.path, "protocol": url.protocol, "host": url.host}))
            .map_err(|error| error.to_string())
    })();
    let values = match result {
        Ok(url) => Map::from_iter([
            (String::from("path"), url["path"].clone()),
            (String::from("protocol"), url["protocol"].clone()),
            (String::from("host"), url["host"].clone()),
            (String::from("error"), Value::Null),
        ]),
        Err(error) => Map::from_iter([
            (String::from("path"), Value::Null),
            (String::from("protocol"), Value::Null),
            (String::from("host"), Value::Null),
            (String::from("error"), Value::String(error)),
        ]),
    };
    native_observation_result(case_id, case, values, "native custom converter URL")
}

#[derive(Debug)]
struct NativeStreamProducerError {
    class: String,
    message: String,
}

impl std::fmt::Display for NativeStreamProducerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for NativeStreamProducerError {}

#[derive(Clone, Copy)]
enum NativeStreamTerminal {
    End,
    Error,
}

struct NativeSourceProbe {
    items: VecDeque<Vec<u8>>,
    pull_markers: Vec<String>,
    next_marker: usize,
    terminal: NativeStreamTerminal,
    producer_error: Option<NativeStreamProducerError>,
    terminal_sent: bool,
    finally_marker: String,
    poll_trace: Arc<Mutex<Vec<String>>>,
    execution_trace: Arc<Mutex<Vec<String>>>,
    finalized: Arc<AtomicBool>,
}

impl Stream for NativeSourceProbe {
    type Item = Result<Vec<u8>, NativeStreamProducerError>;

    fn poll_next(mut self: Pin<&mut Self>, _context: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        if let Some(item) = self.items.pop_front() {
            let marker = self.pull_markers.get(self.next_marker).cloned();
            let Some(next_marker) = self.next_marker.checked_add(1) else {
                return Poll::Ready(Some(Err(NativeStreamProducerError {
                    class: String::from("OverflowError"),
                    message: String::from("stream source marker index overflow"),
                })));
            };
            self.next_marker = next_marker;
            if let Some(marker) = marker {
                if let Ok(mut trace) = self.poll_trace.lock() {
                    trace.push(marker.clone());
                }
                if let Ok(mut trace) = self.execution_trace.lock() {
                    trace.push(format!("source:{marker}"));
                }
            }
            return Poll::Ready(Some(Ok(item)));
        }
        if !self.terminal_sent {
            self.terminal_sent = true;
            if let NativeStreamTerminal::Error = self.terminal {
                return Poll::Ready(self.producer_error.take().map(Err));
            }
        }
        Poll::Ready(None)
    }
}

impl Drop for NativeSourceProbe {
    fn drop(&mut self) {
        if !self.finalized.swap(true, Ordering::AcqRel) {
            if let Ok(mut trace) = self.poll_trace.lock() {
                trace.push(format!("source-finalize:{}", self.finally_marker));
            }
        }
    }
}

fn native_stream_event(event: starlette_rs::StreamingResponseEvent) -> Value {
    match event {
        starlette_rs::StreamingResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers_base64_pairs": canonical_headers(&headers),
        }),
        starlette_rs::StreamingResponseEvent::Body { body, more_body } => json!({
            "type": "http.response.body",
            "body_base64": encode_base64(&body),
            "more_body": more_body,
        }),
    }
}

fn run_native_http_exception_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "inputs",
            "observations",
        ],
        "native HTTP exception case",
    )?;
    if string_field(case, "surface", "native HTTP exception case")? != NATIVE_RESPONSE_SURFACE
        || string_field(case, "operation", "native HTTP exception case")?
            != NATIVE_HTTP_EXCEPTION_OPERATION
    {
        return Err(String::from(
            "case is outside native Response::http_exception",
        ));
    }
    let case_id = string_field(case, "case_id", "native HTTP exception case")?;

    let inputs = case
        .get("inputs")
        .and_then(Value::as_array)
        .filter(|inputs| !inputs.is_empty())
        .ok_or_else(|| String::from("native HTTP exception inputs must be non-empty"))?;
    let responses = inputs
        .iter()
        .enumerate()
        .map(|(index, input)| {
            let context = format!("native HTTP exception inputs[{index}]");
            let input = exact_object(input, &["status_code", "detail", "headers"], &context)?;
            let status_code = input
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .ok_or_else(|| format!("{context}.status_code must be a u16"))?;
            let detail = match input.get("detail") {
                Some(Value::String(detail)) => Some(detail.as_str()),
                Some(Value::Null) => None,
                _ => return Err(format!("{context}.detail must be a string or null")),
            };
            let headers = input
                .get("headers")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("{context}.headers must be an array"))?
                .iter()
                .enumerate()
                .map(|(header_index, header)| {
                    let header_context = format!("{context}.headers[{header_index}]");
                    let pair = header
                        .as_array()
                        .filter(|pair| pair.len() == 2)
                        .ok_or_else(|| format!("{header_context} must be a pair"))?;
                    let name = pair[0]
                        .as_str()
                        .ok_or_else(|| format!("{header_context}[0] must be a string"))?;
                    let value = pair[1]
                        .as_str()
                        .ok_or_else(|| format!("{header_context}[1] must be a string"))?;
                    Ok((name.to_owned(), value.to_owned()))
                })
                .collect::<Result<Vec<_>, String>>()?;
            let response = Response::http_exception(status_code, detail, &headers)
                .map_err(|error| error.to_string())?;
            Ok(json!({
                "status_code": response.status_code(),
                "headers_base64_pairs": canonical_headers(response.headers()),
                "body_base64": encode_base64(response.body()),
            }))
        })
        .collect::<Result<Vec<_>, String>>()?;

    let mut values = Map::new();
    values.insert(String::from("responses"), Value::Array(responses));
    native_observation_result(case_id, case, values, "native HTTP exception")
}

fn run_native_exception_handler_table_case(case: &Value) -> Result<Value, String> {
    let context = "native exception handler table case";
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
    if string_field(case, "surface", context)? != NATIVE_EXCEPTION_HANDLER_TABLE_SURFACE
        || string_field(case, "operation", context)? != NATIVE_EXCEPTION_HANDLER_TABLE_OPERATION
    {
        return Err(String::from(
            "case is outside ExceptionHandlerTable::select",
        ));
    }
    let target_profiles = string_array_field(case, "target_profiles", context)?;
    if target_profiles != [String::from("rust-native-local")]
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "native exception handler table requires only rust-native-local and no assets",
        ));
    }

    let input = exact_object(
        case.get("input")
            .ok_or_else(|| format!("{context} misses input"))?,
        &["registrations", "exception"],
        "native exception handler table input",
    )?;
    let registrations = input
        .get("registrations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native exception handler registrations must be an array"))?;
    let mut table = ExceptionHandlerTable::<String>::new();
    for (index, registration_value) in registrations.iter().enumerate() {
        let registration_context = format!("native exception handler registrations[{index}]");
        let registration = registration_value
            .as_object()
            .ok_or_else(|| format!("{registration_context} must be an object"))?;
        match string_field(registration, "kind", &registration_context)? {
            "status" => {
                let registration = exact_object(
                    registration_value,
                    &["kind", "status_code"],
                    &registration_context,
                )?;
                let status_code = string_field(registration, "status_code", &registration_context)?;
                if !is_canonical_decimal_integer(status_code) {
                    return Err(format!(
                        "{registration_context}.status_code must be a canonical decimal integer"
                    ));
                }
                table.insert_status(status_code, index);
            }
            "exception" => {
                let registration = exact_object(
                    registration_value,
                    &["kind", "class_key"],
                    &registration_context,
                )?;
                let class_key = string_field(registration, "class_key", &registration_context)?;
                if class_key.is_empty() {
                    return Err(format!(
                        "{registration_context}.class_key must be non-empty"
                    ));
                }
                table.insert_class(class_key.to_owned(), index);
            }
            kind => {
                return Err(format!(
                    "{registration_context}.kind is unsupported: {kind:?}"
                ));
            }
        }
    }

    let exception = exact_object(
        input
            .get("exception")
            .ok_or_else(|| format!("{context} input misses exception"))?,
        &["mro", "status_code"],
        "native exception",
    )?;
    let exception_mro = string_array_field(exception, "mro", "native exception")?;
    if exception_mro.is_empty() {
        return Err(String::from("native exception mro must be non-empty"));
    }
    let terminal_class = exception_mro
        .last()
        .map(String::as_str)
        .ok_or_else(|| String::from("native exception mro must be non-empty"))?;
    let terminal_index = exception_mro
        .len()
        .checked_sub(1)
        .ok_or_else(|| String::from("native exception mro must be non-empty"))?;
    let mut seen_class_keys = HashSet::with_capacity(exception_mro.len());
    if !matches!(terminal_class, "Exception" | "HTTPException")
        || exception_mro
            .iter()
            .any(|class_key| !seen_class_keys.insert(class_key.as_str()))
        || exception_mro[..terminal_index]
            .iter()
            .any(|class_key| matches!(class_key.as_str(), "Exception" | "HTTPException"))
    {
        return Err(String::from(
            "native exception mro must be unique and end in Exception or HTTPException",
        ));
    }
    let status_code = optional_string_field(exception, "status_code", "native exception")?;
    match (terminal_class, status_code.as_deref()) {
        ("Exception", None) => {}
        ("HTTPException", Some(status_code)) if is_canonical_decimal_integer(status_code) => {}
        ("HTTPException", _) => {
            return Err(String::from(
                "native HTTPException status_code must be a canonical decimal integer",
            ));
        }
        ("Exception", Some(_)) => {
            return Err(String::from("native Exception status_code must be null"));
        }
        _ => {
            return Err(String::from(
                "native exception terminal class is unsupported",
            ));
        }
    }

    let selected_handler_index = table.select(status_code.as_deref(), &exception_mro);
    let mut values = Map::new();
    values.insert(
        String::from("selected_handler_index"),
        selected_handler_index.map_or(Value::Null, |index| json!(index)),
    );
    native_observation_result(case_id, case, values, context)
}

fn run_native_form_data_case(case: &Value) -> Result<Value, String> {
    let context = "native FormData case";
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
    if string_field(case, "surface", context)? != NATIVE_FORM_DATA_SURFACE
        || string_field(case, "operation", context)? != NATIVE_FORM_DATA_OPERATION
    {
        return Err(String::from(
            "case is outside the native FormData lookup operation",
        ));
    }
    let target_profiles = string_array_field(case, "target_profiles", context)?;
    if target_profiles != [String::from("rust-native-local")]
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "native FormData requires only rust-native-local and no assets",
        ));
    }

    let input = exact_object(
        case.get("input")
            .ok_or_else(|| format!("{context} misses input"))?,
        &["entries", "probe_keys", "comparisons"],
        "native FormData input",
    )?;
    let entries = native_form_data_pairs(
        input
            .get("entries")
            .ok_or_else(|| String::from("native FormData input misses entries"))?,
        "native FormData input entries",
    )?;
    let form = NativeFormData::from_pairs(entries);
    let probe_keys = string_array_field(input, "probe_keys", "native FormData input")?;
    let lookups = probe_keys
        .iter()
        .map(|key| {
            let value = form.get(key);
            json!({
                "key": key,
                "contains": value.is_some(),
                "get": value,
                "get_list": form.get_list(key),
            })
        })
        .collect::<Vec<_>>();
    let comparisons = input
        .get("comparisons")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native FormData input comparisons must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, comparison_value)| {
            let comparison_context = format!("native FormData comparisons[{index}]");
            let comparison = exact_object(
                comparison_value,
                &["comparison_id", "entries"],
                &comparison_context,
            )?;
            let comparison_id = string_field(comparison, "comparison_id", &comparison_context)?;
            let pairs = native_form_data_pairs(
                comparison
                    .get("entries")
                    .ok_or_else(|| format!("{comparison_context} misses entries"))?,
                &format!("{comparison_context}.entries"),
            )?;
            let other = NativeFormData::from_pairs(pairs);
            Ok(json!({"comparison_id": comparison_id, "equal": form == other}))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let items = form
        .items()
        .into_iter()
        .map(|(key, value)| json!([key, value]))
        .collect::<Vec<_>>();
    let mut values = Map::new();
    values.insert(String::from("multi_items"), json!(form.multi_items()));
    values.insert(String::from("keys"), json!(form.keys()));
    values.insert(String::from("values"), json!(form.values()));
    values.insert(String::from("items"), json!(items));
    values.insert(String::from("iteration"), json!(form.keys()));
    values.insert(String::from("length"), json!(form.len()));
    values.insert(String::from("is_empty"), json!(form.is_empty()));
    values.insert(String::from("lookups"), json!(lookups));
    values.insert(String::from("comparisons"), json!(comparisons));
    native_observation_result(case_id, case, values, context)
}

fn native_form_data_pairs(value: &Value, context: &str) -> Result<Vec<(String, String)>, String> {
    value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair_value)| {
            let pair = pair_value
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}[{index}] must be a two-item array"))?;
            let key = pair[0]
                .as_str()
                .ok_or_else(|| format!("{context}[{index}][0] must be a string"))?;
            let value = pair[1]
                .as_str()
                .ok_or_else(|| format!("{context}[{index}][1] must be a string"))?;
            Ok((key.to_owned(), value.to_owned()))
        })
        .collect()
}

fn is_canonical_decimal_integer(value: &str) -> bool {
    let digits = value.strip_prefix('-').unwrap_or(value);
    !digits.is_empty()
        && digits.bytes().all(|byte| byte.is_ascii_digit())
        && (digits.len() == 1 || !digits.starts_with('0'))
        && value != "-0"
}

fn run_native_streaming_source_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "status_code",
            "header_pairs",
            "media_type",
            "source",
            "scope",
            "incoming",
            "send",
            "background",
            "observations",
            "streaming",
        ],
        "native streaming source case",
    )?;
    let case_id = string_field(case, "case_id", "native streaming source case")?;
    if string_field(case, "surface", "native streaming source case")?
        != NATIVE_STREAMING_RESPONSE_SURFACE
        || string_field(case, "operation", "native streaming source case")?
            != NATIVE_STREAMING_RESPONSE_SOURCE_OPERATION
    {
        return Err(String::from(
            "case is outside the native lazy-source operation",
        ));
    }
    if case.get("incoming") != Some(&json!([])) {
        return Err(String::from(
            "native streaming source incoming must be empty",
        ));
    }
    if string_field(case, "streaming", "native streaming source case")? != "async-generator" {
        return Err(String::from(
            "native streaming source must use async-generator input",
        ));
    }
    let status_code = case
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|status| u16::try_from(status).ok())
        .ok_or_else(|| String::from("native streaming source status_code must be a u16"))?;
    let headers = case
        .get("header_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native streaming source header_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| {
                    format!("native streaming source header_pairs[{index}] must be a pair")
                })?;
            let name = pair[0].as_str().ok_or_else(|| {
                format!("native streaming source header_pairs[{index}] name must be a string")
            })?;
            let value = pair[1].as_str().ok_or_else(|| {
                format!("native streaming source header_pairs[{index}] value must be a string")
            })?;
            Ok((name.to_owned(), value.to_owned()))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let media_type = match case.get("media_type") {
        Some(Value::Null) => None,
        Some(Value::String(media_type)) => Some(media_type.as_str()),
        _ => {
            return Err(String::from(
                "native streaming source media_type must be a string or null",
            ));
        }
    };

    let source = exact_object(
        case.get("source")
            .ok_or_else(|| String::from("native streaming source misses source"))?,
        &["items", "terminal", "pull_markers", "finally_marker"],
        "native streaming source input",
    )?;
    let item_values = source
        .get("items")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native streaming source items must be an array"))?;
    let items = item_values
        .iter()
        .enumerate()
        .map(|(index, item)| {
            let context = format!("native streaming source items[{index}]");
            let item = exact_object(item, &["kind", "value"], &context)?;
            let value = string_field(item, "value", &context)?;
            match string_field(item, "kind", &context)? {
                "text" => Ok(value.as_bytes().to_vec()),
                "base64-bytes" => decode_base64(value, &context),
                _ => Err(format!("{context}.kind must be text or base64-bytes")),
            }
        })
        .collect::<Result<Vec<_>, String>>()?;
    let pull_markers = source
        .get("pull_markers")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native streaming source pull_markers must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, marker)| {
            marker.as_str().map(str::to_owned).ok_or_else(|| {
                format!("native streaming source pull_markers[{index}] must be a string")
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    if items.len() != pull_markers.len() || pull_markers.iter().any(String::is_empty) {
        return Err(String::from(
            "native streaming source pull_markers must have one non-empty marker per item",
        ));
    }
    let finally_marker = string_field(source, "finally_marker", "native streaming source")?;
    if finally_marker.is_empty() {
        return Err(String::from(
            "native streaming source finally_marker must be non-empty",
        ));
    }
    let finally_marker = finally_marker.to_owned();
    let terminal = exact_object(
        source
            .get("terminal")
            .ok_or_else(|| String::from("native streaming source terminal is missing"))?,
        if source
            .get("terminal")
            .and_then(|value| value.get("kind"))
            .and_then(Value::as_str)
            == Some("error")
        {
            &["kind", "error"]
        } else {
            &["kind"]
        },
        "native streaming source terminal",
    )?;
    let (terminal, producer_error) =
        match string_field(terminal, "kind", "native streaming source terminal")? {
            "end" => (NativeStreamTerminal::End, None),
            "error" => {
                let error = exact_object(
                    terminal.get("error").ok_or_else(|| {
                        String::from("native streaming source terminal error is missing")
                    })?,
                    &["type", "message"],
                    "native streaming source terminal error",
                )?;
                (
                    NativeStreamTerminal::Error,
                    Some(NativeStreamProducerError {
                        class: string_field(
                            error,
                            "type",
                            "native streaming source terminal error",
                        )?
                        .to_owned(),
                        message: string_field(
                            error,
                            "message",
                            "native streaming source terminal error",
                        )?
                        .to_owned(),
                    }),
                )
            }
            _ => {
                return Err(String::from(
                    "native streaming source terminal.kind is unsupported",
                ));
            }
        };
    let send = case
        .get("send")
        .ok_or_else(|| String::from("native streaming source send input is missing"))?;
    let send = send
        .as_object()
        .ok_or_else(|| String::from("native streaming source send must be an object"))?;
    let send_kind = string_field(send, "kind", "native streaming source send")?;
    let cancellation_event_index = match send_kind {
        "capture-asgi-send" => {
            exact_keys(send, &["kind"], "native streaming source send")?;
            None
        }
        "capture-asgi-send-with-checkpoint-gate" => {
            exact_keys(
                send,
                &["kind", "event_index", "release_after_checkpoints"],
                "native streaming source send",
            )?;
            for field in ["event_index", "release_after_checkpoints"] {
                if send.get(field).and_then(Value::as_u64).is_none() {
                    return Err(format!(
                        "native streaming source send.{field} must be an unsigned integer"
                    ));
                }
            }
            None
        }
        "capture-asgi-send-with-caller-cancellation" => {
            exact_keys(
                send,
                &["kind", "event_index"],
                "native streaming source send",
            )?;
            Some(
                send.get("event_index")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| {
                        String::from(
                            "native streaming source send.event_index must be an unsigned integer",
                        )
                    })?,
            )
        }
        _ => {
            return Err(String::from(
                "native streaming source send kind is unsupported",
            ));
        }
    };
    let background = exact_object(
        case.get("background")
            .ok_or_else(|| String::from("native streaming source background is missing"))?,
        &["kind", "values"],
        "native streaming source background",
    )?;
    if string_field(background, "kind", "native streaming source background")?
        != "async-values-recorder"
    {
        return Err(String::from(
            "native streaming source background kind is unsupported",
        ));
    }
    let background_values =
        string_array_field(background, "values", "native streaming source background")?;

    let source_poll_trace = Arc::new(Mutex::new(Vec::new()));
    let execution_trace = Arc::new(Mutex::new(Vec::new()));
    let finalized = Arc::new(AtomicBool::new(false));
    let source = NativeSourceProbe {
        items: items.into(),
        pull_markers,
        next_marker: 0,
        terminal,
        producer_error,
        terminal_sent: false,
        finally_marker: finally_marker.clone(),
        poll_trace: Arc::clone(&source_poll_trace),
        execution_trace: Arc::clone(&execution_trace),
        finalized: Arc::clone(&finalized),
    };
    let mut response = StreamingResponse::from_stream(
        status_code,
        source,
        media_type,
        headers
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    )
    .map_err(|error| error.to_string())?;
    let mut call = response.call_state(true);
    let mut events = Vec::new();
    let mut sent_status = None;
    let mut sent_headers = Vec::new();
    let mut error = Value::Null;
    let mut sent_index = 0_u64;
    let mut execution_finalized = false;
    let mut background_execution_trace = Vec::new();
    loop {
        match call.step() {
            StreamingResponseCallStep::Send(event) => {
                if cancellation_event_index == Some(sent_index) {
                    if let Ok(mut trace) = execution_trace.lock() {
                        trace.push(String::from("send:cancel"));
                    }
                    let cancellation = NativeStreamProducerError {
                        class: String::from("CancelledError"),
                        message: String::new(),
                    };
                    let _ = call.advance(
                        StreamingResponseCallInput::<NativeStreamProducerError>::Send(Err(
                            cancellation,
                        )),
                    );
                    error = json!({"class": "CancelledError", "message": ""});
                    drop(response);
                    if finalized.load(Ordering::Acquire) && !execution_finalized {
                        if let Ok(mut trace) = execution_trace.lock() {
                            trace.push(format!("source-finalize:{finally_marker}"));
                        }
                    }
                    break;
                }
                let observation_event = native_stream_event(event.clone());
                match &event {
                    starlette_rs::StreamingResponseEvent::Start {
                        status_code,
                        headers,
                    } => {
                        sent_status = Some(*status_code);
                        sent_headers = canonical_headers(headers);
                        if let Ok(mut trace) = execution_trace.lock() {
                            trace.push(String::from("send:start"));
                        }
                    }
                    starlette_rs::StreamingResponseEvent::Body { body, more_body } => {
                        if let Ok(mut trace) = execution_trace.lock() {
                            if *more_body {
                                trace.push(format!("send:chunk:{}", encode_base64(body)));
                            } else {
                                trace.push(String::from("send:final"));
                            }
                        }
                    }
                }
                events.push(observation_event);
                checked_u64_increment(&mut sent_index, "stream response event index")?;
                if let Err(advance_error) = call
                    .advance(StreamingResponseCallInput::<NativeStreamProducerError>::Send(Ok(())))
                {
                    error = json!({"class": "NativeCallError", "message": format!("{advance_error:?}")});
                    break;
                }
            }
            StreamingResponseCallStep::PullChunk => {
                let pulled = block_on(futures::future::poll_fn(|context| {
                    Pin::new(&mut response).poll_next(context)
                }));
                match pulled {
                    Some(Ok(chunk)) => {
                        let _ = call.advance(
                            StreamingResponseCallInput::<NativeStreamProducerError>::ChunkPulled(
                                Ok(Some(chunk)),
                            ),
                        );
                    }
                    Some(Err(producer_error)) => {
                        if let Ok(mut trace) = execution_trace.lock() {
                            trace.push(format!(
                                "source-error:{}:{}",
                                producer_error.class, producer_error.message
                            ));
                        }
                        let error_class = producer_error.class.clone();
                        let error_message = producer_error.message.clone();
                        let _ = call.advance(
                            StreamingResponseCallInput::<NativeStreamProducerError>::ChunkPulled(
                                Err(producer_error),
                            ),
                        );
                        error = json!({
                            "class": error_class,
                            "message": error_message,
                        });
                        if finalized.load(Ordering::Acquire) && !execution_finalized {
                            if let Ok(mut trace) = execution_trace.lock() {
                                trace.push(format!("source-finalize:{finally_marker}"));
                            }
                        }
                        break;
                    }
                    None => {
                        if finalized.load(Ordering::Acquire) && !execution_finalized {
                            if let Ok(mut trace) = execution_trace.lock() {
                                trace.push(format!("source-finalize:{finally_marker}"));
                            }
                            execution_finalized = true;
                        }
                        let _ = call.advance(
                            StreamingResponseCallInput::<NativeStreamProducerError>::ChunkPulled(
                                Ok(None),
                            ),
                        );
                    }
                }
            }
            StreamingResponseCallStep::RunBackground => {
                for value in &background_values {
                    if let Ok(mut trace) = execution_trace.lock() {
                        trace.push(format!("background:{value}"));
                    }
                    background_execution_trace.push(value.clone());
                }
                let _ = call.advance(
                    StreamingResponseCallInput::<NativeStreamProducerError>::BackgroundFinished(
                        Ok(()),
                    ),
                );
            }
            StreamingResponseCallStep::Complete | StreamingResponseCallStep::Failed => break,
        }
    }
    let source_poll_trace = source_poll_trace
        .lock()
        .map_err(|_| String::from("native streaming source poll trace lock is poisoned"))?
        .clone();
    let execution_trace = execution_trace
        .lock()
        .map_err(|_| String::from("native streaming source execution trace lock is poisoned"))?
        .clone();
    let values = Map::from_iter([
        (
            String::from("status"),
            sent_status.map_or(Value::Null, |status| json!(status)),
        ),
        (String::from("headers"), json!(sent_headers)),
        (String::from("events"), json!(events)),
        (String::from("execution_trace"), json!(execution_trace)),
        (String::from("source_poll_trace"), json!(source_poll_trace)),
        (
            String::from("background_execution_trace"),
            json!(background_execution_trace),
        ),
        (String::from("error"), error),
    ]);
    native_observation_result(case_id, case, values, "native streaming source")
}

type NativeTowerFuture = Pin<
    Box<
        dyn Future<Output = Result<starlette_rs::NativeHttpResponse, NativeApplicationError>>
            + Send
            + 'static,
    >,
>;

trait NativeTowerService:
    tower_service::Service<
        Request<NativeProbeBody>,
        Response = starlette_rs::NativeHttpResponse,
        Error = NativeApplicationError,
        Future = NativeTowerFuture,
    > + Send
{
}

impl<S> NativeTowerService for S where
    S: tower_service::Service<
            Request<NativeProbeBody>,
            Response = starlette_rs::NativeHttpResponse,
            Error = NativeApplicationError,
            Future = NativeTowerFuture,
        > + Send
{
}

struct ErasedNativeTowerService(Box<dyn NativeTowerService>);

impl tower_service::Service<Request<NativeProbeBody>> for ErasedNativeTowerService {
    type Response = starlette_rs::NativeHttpResponse;
    type Error = NativeApplicationError;
    type Future = NativeTowerFuture;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.0.poll_ready(context)
    }

    fn call(&mut self, request: Request<NativeProbeBody>) -> Self::Future {
        self.0.call(request)
    }
}

#[derive(Clone)]
struct NativeTowerCallId(String);

#[derive(Clone)]
struct NativeTowerResponseSpec {
    status: http::StatusCode,
    headers: Vec<(HeaderName, HeaderValue)>,
    body: Vec<NativeProbeFrame>,
}

impl NativeTowerResponseSpec {
    fn into_response(self) -> starlette_rs::NativeHttpResponse {
        let body = NativeProbeBody::new(
            self.body,
            Arc::new(Mutex::new(Vec::new())),
            Arc::new(AtomicBool::new(false)),
        );
        let mut response = HttpResponse::new(starlette_rs::box_native_body(body));
        *response.status_mut() = self.status;
        for (name, value) in self.headers {
            response.headers_mut().append(name, value);
        }
        response
    }
}

#[derive(Clone)]
enum NativeTowerOutcome {
    Response(NativeTowerResponseSpec),
    Error { message: String },
}

impl NativeTowerOutcome {
    fn into_result(self) -> Result<starlette_rs::NativeHttpResponse, NativeApplicationError> {
        match self {
            Self::Response(response) => Ok(response.into_response()),
            Self::Error { message } => Err(NativeApplicationError::Endpoint(Box::new(
                io::Error::other(message),
            ))),
        }
    }
}

#[derive(Clone)]
struct NativeTowerLayerSpec {
    name: String,
    record: Vec<String>,
    short_circuit: Option<(String, NativeTowerResponseSpec)>,
    events: Arc<Mutex<Vec<Value>>>,
}

impl NativeTowerLayerSpec {
    fn record_event(
        &self,
        call_id: Option<&str>,
        event_name: &str,
        status: Option<u16>,
        message: Option<&str>,
    ) {
        if !self.record.iter().any(|event| event == event_name) {
            return;
        }
        let Some(call_id) = call_id else {
            return;
        };
        let mut event = Map::new();
        event.insert(String::from("call_id"), json!(call_id));
        event.insert(String::from("layer"), json!(self.name));
        event.insert(String::from("event"), json!(event_name));
        if let Some(status) = status {
            event.insert(String::from("status"), json!(status));
        }
        if let Some(message) = message {
            event.insert(String::from("message"), json!(message));
        }
        if let Ok(mut events) = self.events.lock() {
            events.push(Value::Object(event));
        }
    }
}

impl<S> tower_layer::Layer<S> for NativeTowerLayerSpec {
    type Service = NativeTowerRecordedService<S>;

    fn layer(&self, inner: S) -> Self::Service {
        NativeTowerRecordedService {
            inner,
            layer: self.clone(),
        }
    }
}

struct NativeTowerRecordedService<S> {
    inner: S,
    layer: NativeTowerLayerSpec,
}

impl<S> tower_service::Service<Request<NativeProbeBody>> for NativeTowerRecordedService<S>
where
    S: tower_service::Service<
            Request<NativeProbeBody>,
            Response = starlette_rs::NativeHttpResponse,
            Error = NativeApplicationError,
            Future = NativeTowerFuture,
        > + Send
        + 'static,
{
    type Response = starlette_rs::NativeHttpResponse;
    type Error = NativeApplicationError;
    type Future = NativeTowerFuture;

    fn poll_ready(&mut self, context: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(context)
    }

    fn call(&mut self, request: Request<NativeProbeBody>) -> Self::Future {
        let call_id = request
            .extensions()
            .get::<NativeTowerCallId>()
            .map(|call_id| call_id.0.clone());
        let request_uri = request.uri().path().to_owned();
        self.layer
            .record_event(call_id.as_deref(), "request", None, None);

        if let Some((short_circuit_uri, response)) = &self.layer.short_circuit {
            if *short_circuit_uri == request_uri {
                let layer = self.layer.clone();
                let response = response.clone();
                return Box::pin(async move {
                    let response = response.into_response();
                    layer.record_event(
                        call_id.as_deref(),
                        "response",
                        Some(response.status().as_u16()),
                        None,
                    );
                    Ok(response)
                });
            }
        }

        let future = self.inner.call(request);
        let layer = self.layer.clone();
        Box::pin(async move {
            match future.await {
                Ok(response) => {
                    layer.record_event(
                        call_id.as_deref(),
                        "response",
                        Some(response.status().as_u16()),
                        None,
                    );
                    Ok(response)
                }
                Err(error) => {
                    let message = native_application_error_message(&error);
                    layer.record_event(call_id.as_deref(), "error", None, Some(&message));
                    Err(error)
                }
            }
        })
    }
}

fn native_application_error_message(error: &NativeApplicationError) -> String {
    error
        .source()
        .map_or_else(|| error.to_string(), std::string::ToString::to_string)
}

fn parse_native_tower_response(
    value: &Value,
    context: &str,
) -> Result<NativeTowerResponseSpec, String> {
    let response = exact_object(value, &["status", "headers", "body"], context)?;
    let status = response
        .get("status")
        .and_then(Value::as_u64)
        .and_then(|status| u16::try_from(status).ok())
        .ok_or_else(|| format!("{context}.status must be an HTTP status code"))?;
    let status = http::StatusCode::from_u16(status)
        .map_err(|error| format!("{context}.status is invalid: {error}"))?;
    let raw_headers = response
        .get("headers")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.headers must be an array"))?;
    let mut headers = Vec::with_capacity(raw_headers.len());
    for (index, pair) in raw_headers.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| format!("{context}.headers[{index}] must be a name/value pair"))?;
        let name = pair[0]
            .as_str()
            .ok_or_else(|| format!("{context}.headers[{index}][0] must be a string"))?;
        let value = pair[1]
            .as_str()
            .ok_or_else(|| format!("{context}.headers[{index}][1] must be a string"))?;
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|error| format!("{context}.headers[{index}] has an invalid name: {error}"))?;
        let value = HeaderValue::from_str(value)
            .map_err(|error| format!("{context}.headers[{index}] has an invalid value: {error}"))?;
        headers.push((name, value));
    }
    let body = exact_object(
        response
            .get("body")
            .ok_or_else(|| format!("{context}.body is required"))?,
        &["frames"],
        &format!("{context}.body"),
    )?;
    let body = parse_native_probe_frames(
        body.get("frames")
            .ok_or_else(|| format!("{context}.body.frames is required"))?,
        &format!("{context}.body.frames"),
    )?;
    Ok(NativeTowerResponseSpec {
        status,
        headers,
        body,
    })
}

fn parse_native_tower_outcome(value: &Value, context: &str) -> Result<NativeTowerOutcome, String> {
    let outcome = value
        .as_object()
        .ok_or_else(|| format!("{context} must be an outcome object"))?;
    match outcome.get("kind").and_then(Value::as_str) {
        Some("response") if outcome.contains_key("response") => {
            let outcome = exact_object(value, &["kind", "response"], context)?;
            let response = parse_native_tower_response(
                outcome
                    .get("response")
                    .ok_or_else(|| format!("{context}.response is required"))?,
                &format!("{context}.response"),
            )?;
            Ok(NativeTowerOutcome::Response(response))
        }
        Some("response") => {
            let mut response_value = value.clone();
            let response_fields = response_value
                .as_object_mut()
                .ok_or_else(|| format!("{context} must be an outcome object"))?;
            response_fields.remove("kind");
            let response = parse_native_tower_response(&response_value, context)?;
            Ok(NativeTowerOutcome::Response(response))
        }
        Some("error") => {
            let outcome = exact_object(value, &["kind", "error"], context)?;
            let error = exact_object(
                outcome
                    .get("error")
                    .ok_or_else(|| format!("{context}.error is required"))?,
                &["kind", "message"],
                &format!("{context}.error"),
            )?;
            if string_field(error, "kind", context)? != "std::io::Error" {
                return Err(format!("{context}.error.kind must be std::io::Error"));
            }
            Ok(NativeTowerOutcome::Error {
                message: string_field(error, "message", context)?.to_owned(),
            })
        }
        _ => Err(format!("{context}.kind must be response or error")),
    }
}

fn parse_native_tower_layer(
    value: &Value,
    events: Arc<Mutex<Vec<Value>>>,
    context: &str,
) -> Result<NativeTowerLayerSpec, String> {
    let layer = object_with_optional_keys(value, &["name", "record"], &["short_circuit"], context)?;
    let name = string_field(layer, "name", context)?.to_owned();
    let record = string_array_field(layer, "record", context)?;
    if record.is_empty()
        || record
            .iter()
            .any(|event| !matches!(event.as_str(), "request" | "response" | "error"))
    {
        return Err(format!("{context}.record contains an unsupported event"));
    }
    let short_circuit = match layer.get("short_circuit") {
        Some(value) => {
            let short_circuit = exact_object(value, &["request_uri", "response"], context)?;
            let request_uri = string_field(short_circuit, "request_uri", context)?.to_owned();
            let response = parse_native_tower_response(
                short_circuit
                    .get("response")
                    .ok_or_else(|| format!("{context}.short_circuit.response is required"))?,
                &format!("{context}.short_circuit.response"),
            )?;
            Some((request_uri, response))
        }
        None => None,
    };
    Ok(NativeTowerLayerSpec {
        name,
        record,
        short_circuit,
        events,
    })
}

fn run_native_service_middleware_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "inputs",
            "observations",
        ],
        "native service middleware case",
    )?;
    let case_id = string_field(case, "case_id", "native service middleware case")?;
    if string_field(case, "surface", "native service middleware case")?
        != "starlette-rs.NativeApplication"
        || string_field(case, "operation", "native service middleware case")?
            != NATIVE_SERVICE_MIDDLEWARE_OPERATION
    {
        return Err(String::from(
            "case is outside the native service middleware operation",
        ));
    }
    let inputs = exact_object(
        case.get("inputs")
            .ok_or_else(|| String::from("native service middleware case misses inputs"))?,
        &["application", "layers_outer_to_inner", "calls", "drive"],
        "native service middleware inputs",
    )?;
    let application_input = exact_object(
        inputs
            .get("application")
            .ok_or_else(|| String::from("native service middleware inputs miss application"))?,
        &["routes"],
        "native service middleware application",
    )?;
    let route_values = application_input
        .get("routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| String::from("native service middleware routes must be non-empty"))?;
    let mut routes = Vec::with_capacity(route_values.len());
    let mut declared_header_names = HashSet::new();
    for (index, route_value) in route_values.iter().enumerate() {
        let context = format!("native service middleware route[{index}]");
        let route = exact_object(route_value, &["path", "methods", "endpoint"], &context)?;
        let path = string_field(route, "path", &context)?.to_owned();
        let methods = string_array_field(route, "methods", &context)?;
        let endpoint = exact_object(
            route
                .get("endpoint")
                .ok_or_else(|| format!("{context}.endpoint is required"))?,
            &["request_body_action", "outcome"],
            &format!("{context}.endpoint"),
        )?;
        if string_field(endpoint, "request_body_action", &context)? != "leave-unread" {
            return Err(format!(
                "{context}.endpoint.request_body_action must be leave-unread"
            ));
        }
        let outcome = parse_native_tower_outcome(
            endpoint
                .get("outcome")
                .ok_or_else(|| format!("{context}.endpoint.outcome is required"))?,
            &format!("{context}.endpoint.outcome"),
        )?;
        if let NativeTowerOutcome::Response(response) = &outcome {
            declared_header_names.extend(response.headers.iter().map(|(name, _)| name.clone()));
        }
        let endpoint = move |_request: starlette_rs::NativeRequest| {
            let outcome = outcome.clone();
            async move { outcome.into_result() }
        };
        routes.push(NativeRoute::new(path, methods, endpoint));
    }
    let application = starlette_rs::NativeApplication::new(routes)
        .map_err(|error| format!("cannot create native application: {error}"))?;

    let events = Arc::new(Mutex::new(Vec::new()));
    let layer_values = inputs
        .get("layers_outer_to_inner")
        .and_then(Value::as_array)
        .filter(|layers| !layers.is_empty())
        .ok_or_else(|| String::from("native service middleware layers must be non-empty"))?;
    let parsed_layers = layer_values
        .iter()
        .enumerate()
        .map(|(index, layer)| {
            parse_native_tower_layer(
                layer,
                Arc::clone(&events),
                &format!("native service middleware layer[{index}]"),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    for layer in &parsed_layers {
        if let Some((_, response)) = &layer.short_circuit {
            declared_header_names.extend(response.headers.iter().map(|(name, _)| name.clone()));
        }
    }
    let mut layers = parsed_layers.into_iter().rev();
    let inner_layer = layers
        .next()
        .ok_or_else(|| String::from("native service middleware has no layers"))?;
    let mut service: Box<dyn NativeTowerService> = Box::new(application.layer(inner_layer));
    for layer in layers {
        service = Box::new(tower_layer::Layer::layer(
            &layer,
            ErasedNativeTowerService(service),
        ));
    }
    let mut service = ErasedNativeTowerService(service);

    let drive = exact_object(
        inputs
            .get("drive")
            .ok_or_else(|| String::from("native service middleware inputs miss drive"))?,
        &[
            "poll_ready_before_each_call",
            "service_future",
            "response_body",
        ],
        "native service middleware drive",
    )?;
    let poll_ready = bool_field(
        drive,
        "poll_ready_before_each_call",
        "native service middleware drive",
    )?;
    if string_field(drive, "service_future", "native service middleware drive")? != "resolve" {
        return Err(String::from(
            "native service middleware drive.service_future must be resolve",
        ));
    }
    if string_field(drive, "response_body", "native service middleware drive")? != "read-to-end" {
        return Err(String::from(
            "native service middleware drive.response_body must be read-to-end",
        ));
    }

    let calls = inputs
        .get("calls")
        .and_then(Value::as_array)
        .filter(|calls| !calls.is_empty())
        .ok_or_else(|| String::from("native service middleware calls must be non-empty"))?;
    let mut service_results = Vec::with_capacity(calls.len());
    let mut request_body_poll_counts = Vec::with_capacity(calls.len());
    for (index, call_value) in calls.iter().enumerate() {
        let context = format!("native service middleware call[{index}]");
        let call = exact_object(call_value, &["call_id", "request"], &context)?;
        let call_id = string_field(call, "call_id", &context)?.to_owned();
        let request = exact_object(
            call.get("request")
                .ok_or_else(|| format!("{context}.request is required"))?,
            &["method", "uri", "body"],
            &format!("{context}.request"),
        )?;
        let method = Method::from_bytes(string_field(request, "method", &context)?.as_bytes())
            .map_err(|error| format!("{context}.request.method is invalid: {error}"))?;
        let uri = Uri::from_str(string_field(request, "uri", &context)?)
            .map_err(|error| format!("{context}.request.uri is invalid: {error}"))?;
        let body = exact_object(
            request
                .get("body")
                .ok_or_else(|| format!("{context}.request.body is required"))?,
            &["frames"],
            &format!("{context}.request.body"),
        )?;
        let request_poll_trace = Arc::new(Mutex::new(Vec::new()));
        let request_body = NativeProbeBody::new(
            parse_native_probe_frames(
                body.get("frames")
                    .ok_or_else(|| format!("{context}.request.body.frames is required"))?,
                &format!("{context}.request.body.frames"),
            )?,
            Arc::clone(&request_poll_trace),
            Arc::new(AtomicBool::new(false)),
        );
        let mut request = Request::builder()
            .method(method)
            .uri(uri)
            .body(request_body)
            .map_err(|error| format!("{context}: cannot construct request: {error}"))?;
        request
            .extensions_mut()
            .insert(NativeTowerCallId(call_id.clone()));

        let service_result = if poll_ready {
            let readiness = block_on(futures::future::poll_fn(|task_context| {
                tower_service::Service::poll_ready(&mut service, task_context)
            }));
            match readiness {
                Ok(()) => block_on(tower_service::Service::call(&mut service, request)),
                Err(error) => Err(error),
            }
        } else {
            block_on(tower_service::Service::call(&mut service, request))
        };

        match service_result {
            Ok(mut response) => {
                let status = response.status().as_u16();
                let headers = response
                    .headers()
                    .iter()
                    .filter(|(name, _)| declared_header_names.contains(*name))
                    .map(|(name, value)| {
                        value
                            .to_str()
                            .map(|value| json!([name.as_str(), value]))
                            .map_err(|error| {
                                format!("{context}.response has a non-text header value: {error}")
                            })
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                let body_chunks_base64 = block_on(async {
                    let mut chunks = Vec::new();
                    while let Some(frame) = response.body_mut().frame().await {
                        match frame {
                            Ok(frame) => {
                                if let Ok(data) = frame.into_data() {
                                    if !data.is_empty() {
                                        chunks.push(encode_base64(&data));
                                    }
                                }
                            }
                            Err(error) => {
                                return Err(format!(
                                    "{context}.response body polling failed: {error}"
                                ));
                            }
                        }
                    }
                    Ok(chunks)
                })?;
                service_results.push(json!({
                    "call_id": call_id.clone(),
                    "kind": "response",
                    "status": status,
                    "headers": headers,
                    "body_chunks_base64": body_chunks_base64,
                }));
            }
            Err(error) => service_results.push(json!({
                "call_id": call_id.clone(),
                "kind": "error",
                "message": native_application_error_message(&error),
            })),
        }
        let count = request_poll_trace
            .lock()
            .map_err(|_| format!("{context}.request body poll trace lock is poisoned"))?
            .len();
        request_body_poll_counts.push(json!({"call_id": call_id, "count": count}));
    }

    let middleware_events = events
        .lock()
        .map_err(|_| String::from("native middleware event trace lock is poisoned"))?
        .clone();
    let mut values = Map::new();
    values.insert(String::from("middleware_events"), json!(middleware_events));
    values.insert(String::from("service_results"), json!(service_results));
    values.insert(
        String::from("request_body_poll_counts"),
        json!(request_body_poll_counts),
    );
    native_observation_result(case_id, case, values, "native service middleware")
}

fn parse_native_probe_frames(
    value: &Value,
    context: &str,
) -> Result<Vec<NativeProbeFrame>, String> {
    let frames = value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    let mut parsed = Vec::with_capacity(frames.len());
    for (index, frame) in frames.iter().enumerate() {
        let frame_context = format!("{context}[{index}]");
        let object = frame
            .as_object()
            .ok_or_else(|| format!("{frame_context} must be an object"))?;
        if object.contains_key("data_base64") {
            exact_keys(object, &["data_base64"], &frame_context)?;
            let encoded = string_field(object, "data_base64", &frame_context)?;
            parsed.push(NativeProbeFrame::Data(Bytes::from(decode_base64(
                encoded,
                &format!("{frame_context}.data_base64"),
            )?)));
        } else if object.contains_key("error") {
            exact_keys(object, &["error"], &frame_context)?;
            let error = exact_object(
                object
                    .get("error")
                    .ok_or_else(|| format!("{frame_context} misses error"))?,
                &["kind", "message"],
                &format!("{frame_context}.error"),
            )?;
            parsed.push(NativeProbeFrame::Error {
                kind: string_field(error, "kind", &frame_context)?.to_owned(),
                message: string_field(error, "message", &frame_context)?.to_owned(),
            });
        } else if object.get("pending").and_then(Value::as_bool) == Some(true) {
            exact_keys(object, &["pending"], &frame_context)?;
            parsed.push(NativeProbeFrame::Pending);
        } else if object.get("end").and_then(Value::as_bool) == Some(true) {
            exact_keys(object, &["end"], &frame_context)?;
            parsed.push(NativeProbeFrame::End);
        } else {
            return Err(format!(
                "{frame_context} must declare data_base64, error, pending, or end"
            ));
        }
    }
    Ok(parsed)
}

fn poll_future_once<F: Future>(future: Pin<&mut F>) -> Poll<F::Output> {
    let waker = futures::task::noop_waker();
    let mut context = Context::from_waker(&waker);
    future.poll(&mut context)
}

fn string_array_field(
    object: &Map<String, Value>,
    key: &str,
    context: &str,
) -> Result<Vec<String>, String> {
    object
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.{key} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, value)| {
            value
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("{context}.{key}[{index}] must be a string"))
        })
        .collect()
}

fn native_observation_result(
    case_id: &str,
    case: &Map<String, Value>,
    values: Map<String, Value>,
    context: &str,
) -> Result<Value, String> {
    let selectors = case
        .get("observations")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context} observations must be an array"))?;
    if selectors.len() != 1 || selectors.first().and_then(Value::as_str) != Some("workflow") {
        return Err(format!(
            "{context} must select exactly one workflow observation"
        ));
    }
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "workflow",
            "status": "ok",
            "value": {"workflow": Value::Object(values)},
        }],
    }))
}

#[derive(Default)]
struct NativeWebSocketProbe {
    acceptance: Option<Value>,
    messages: Vec<Value>,
    close: Option<Value>,
    peer_close: Option<Value>,
    path_params: Option<Value>,
    handshake: Option<Value>,
    application_error: Option<Value>,
    result_error_kind: Option<String>,
    receive_started: bool,
    receive_cancelled: bool,
}

struct NativeWebSocketDriverProbe {
    incoming: Mutex<VecDeque<NativeWebSocketEvent>>,
    pending_receive: bool,
    cancel_receive: bool,
    cancellation: Arc<NativeWebSocketCancellation>,
    observations: Arc<Mutex<NativeWebSocketProbe>>,
}

#[derive(Default)]
struct NativeWebSocketCancellation {
    requested: AtomicBool,
    waiter: Mutex<Option<Waker>>,
}

impl NativeWebSocketCancellation {
    fn request(&self) {
        self.requested.store(true, Ordering::Release);
        let waker = match self.waiter.lock() {
            Ok(mut waiter) => waiter.take(),
            Err(error) => error.into_inner().take(),
        };
        if let Some(waker) = waker {
            waker.wake();
        }
    }

    fn poll_requested(&self, context: &mut Context<'_>) -> Poll<()> {
        if self.requested.load(Ordering::Acquire) {
            return Poll::Ready(());
        }
        match self.waiter.lock() {
            Ok(mut waiter) => *waiter = Some(context.waker().clone()),
            Err(error) => *error.into_inner() = Some(context.waker().clone()),
        }
        if self.requested.load(Ordering::Acquire) {
            Poll::Ready(())
        } else {
            Poll::Pending
        }
    }
}

impl NativeWebSocketDriver for NativeWebSocketDriverProbe {
    fn accept(
        &self,
        acceptance: NativeWebSocketAcceptance,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        Box::pin(async move {
            let (subprotocol, headers) = acceptance.into_parts();
            let mut probe = self.observations.lock().map_err(|_| {
                Box::new(io::Error::other("WebSocket observation lock is poisoned"))
                    as NativeWebSocketTransportError
            })?;
            probe.acceptance = Some(json!({
                "accepted": true,
                "subprotocol": subprotocol,
                "headers": native_header_pairs(&headers),
            }));
            Ok(())
        })
    }

    fn receive(
        &self,
    ) -> futures::future::BoxFuture<'_, Result<NativeWebSocketEvent, NativeWebSocketTransportError>>
    {
        Box::pin(async move {
            if let Ok(mut probe) = self.observations.lock() {
                probe.receive_started = true;
            }
            if self.pending_receive {
                if self.cancel_receive {
                    self.cancellation.request();
                }
                return pending::<Result<NativeWebSocketEvent, NativeWebSocketTransportError>>()
                    .await;
            }
            let event = self
                .incoming
                .lock()
                .map_err(|_| {
                    Box::new(io::Error::other("WebSocket input queue is poisoned"))
                        as NativeWebSocketTransportError
                })?
                .pop_front()
                .ok_or_else(|| {
                    Box::new(io::Error::other("WebSocket input has no next event"))
                        as NativeWebSocketTransportError
                })?;
            if let Ok(mut probe) = self.observations.lock() {
                match &event {
                    NativeWebSocketEvent::Message(message) => {
                        probe.messages.push(json!({
                            "direction": "received",
                            "message": native_websocket_message_value(message),
                        }));
                    }
                    NativeWebSocketEvent::PeerClosed(close) => {
                        let value = json!({"code": close.code, "reason": close.reason});
                        probe.peer_close = Some(value.clone());
                        probe.messages.push(json!({
                            "direction": "received",
                            "peer_close": value,
                        }));
                    }
                }
            }
            Ok(event)
        })
    }

    fn send(
        &self,
        message: NativeWebSocketMessage,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        Box::pin(async move {
            let mut probe = self.observations.lock().map_err(|_| {
                Box::new(io::Error::other("WebSocket observation lock is poisoned"))
                    as NativeWebSocketTransportError
            })?;
            probe.messages.push(json!({
                "direction": "sent",
                "message": native_websocket_message_value(&message),
            }));
            Ok(())
        })
    }

    fn close(
        &self,
        close: NativeWebSocketClose,
    ) -> futures::future::BoxFuture<'_, Result<(), NativeWebSocketTransportError>> {
        Box::pin(async move {
            let value = json!({"code": close.code(), "reason": close.reason()});
            let mut probe = self.observations.lock().map_err(|_| {
                Box::new(io::Error::other("WebSocket observation lock is poisoned"))
                    as NativeWebSocketTransportError
            })?;
            probe.close = Some(value);
            Ok(())
        })
    }

    fn cancelled(&self) -> futures::future::BoxFuture<'_, ()> {
        if !self.cancel_receive {
            return Box::pin(pending());
        }
        let cancellation = Arc::clone(&self.cancellation);
        let observations = Arc::clone(&self.observations);
        Box::pin(poll_fn(move |context| {
            if cancellation.poll_requested(context).is_ready() {
                let mut probe = match observations.lock() {
                    Ok(probe) => probe,
                    Err(error) => error.into_inner(),
                };
                probe.receive_cancelled = true;
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }))
    }
}

fn run_native_websocket_case(case: &Value) -> Result<Value, String> {
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
        "native WebSocket case",
    )?;
    let case_id = string_field(case, "case_id", "native WebSocket case")?;
    if string_field(case, "surface", "native WebSocket case")? != NATIVE_WEBSOCKET_SURFACE
        || string_field(case, "operation", "native WebSocket case")? != NATIVE_WEBSOCKET_OPERATION
    {
        return Err(String::from(
            "case is outside the native WebSocket session operation",
        ));
    }
    let target_profiles = case
        .get("target_profiles")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native WebSocket target_profiles must be an array"))?;
    if target_profiles
        .iter()
        .any(|profile| profile.as_str().is_none())
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "native WebSocket target_profiles must contain strings and assets must be empty",
        ));
    }
    let input = object_with_optional_keys(
        case.get("input")
            .ok_or_else(|| String::from("native WebSocket case misses input"))?,
        &["handshake", "route", "actions"],
        &["incoming", "cancellation"],
        "native WebSocket input",
    )?;
    let handshake_input = exact_object(
        input
            .get("handshake")
            .ok_or_else(|| String::from("native WebSocket input misses handshake"))?,
        &[
            "method",
            "uri",
            "version",
            "headers",
            "offered_subprotocols",
        ],
        "native WebSocket handshake",
    )?;
    let method = Method::from_bytes(
        string_field(handshake_input, "method", "native WebSocket handshake")?.as_bytes(),
    )
    .map_err(|error| format!("native WebSocket method is invalid: {error}"))?;
    let uri = Uri::from_str(string_field(
        handshake_input,
        "uri",
        "native WebSocket handshake",
    )?)
    .map_err(|error| format!("native WebSocket URI is invalid: {error}"))?;
    let version = match string_field(handshake_input, "version", "native WebSocket handshake")? {
        "HTTP/0.9" => http::Version::HTTP_09,
        "HTTP/1.0" => http::Version::HTTP_10,
        "HTTP/1.1" => http::Version::HTTP_11,
        "HTTP/2" => http::Version::HTTP_2,
        "HTTP/3" => http::Version::HTTP_3,
        version => {
            return Err(format!(
                "unsupported native WebSocket HTTP version {version:?}"
            ));
        }
    };
    let headers = parse_native_headers(
        handshake_input
            .get("headers")
            .ok_or_else(|| String::from("native WebSocket handshake misses headers"))?,
        "native WebSocket handshake headers",
    )?;
    let offered = string_array_field(
        handshake_input,
        "offered_subprotocols",
        "native WebSocket handshake",
    )?;
    let request = Request::builder()
        .method(method)
        .uri(uri)
        .version(version)
        .body(())
        .map_err(|error| format!("cannot construct WebSocket handshake head: {error}"))?;
    let (mut parts, _) = request.into_parts();
    parts.headers = headers;
    let handshake = NativeWebSocketHandshake::from_parts(parts, offered);

    let route = exact_object(
        input
            .get("route")
            .ok_or_else(|| String::from("native WebSocket input misses route"))?,
        &["path", "preferred_subprotocols"],
        "native WebSocket route",
    )?;
    let route_path = string_field(route, "path", "native WebSocket route")?.to_owned();
    let preferred = string_array_field(route, "preferred_subprotocols", "native WebSocket route")?;
    let (route_path_params, typed_route_path_params) =
        native_websocket_path_parameters(&route_path, handshake.uri())?;
    let actions = input
        .get("actions")
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| String::from("native WebSocket actions must be an array"))?;
    let pending_receive = actions.iter().any(|action| {
        action.get("action").and_then(Value::as_str) == Some("receive")
            && action.get("pending").and_then(Value::as_bool) == Some(true)
    });
    let cancel_receive = if let Some(cancellation) = input.get("cancellation") {
        let cancellation = exact_object(
            cancellation,
            &["operation", "timing"],
            "native WebSocket cancellation",
        )?;
        if string_field(cancellation, "operation", "native WebSocket cancellation")? != "receive"
            || string_field(cancellation, "timing", "native WebSocket cancellation")?
                != "after-operation-started"
        {
            return Err(String::from(
                "native WebSocket cancellation input is unsupported",
            ));
        }
        true
    } else {
        false
    };
    if pending_receive && !cancel_receive {
        return Err(String::from(
            "pending WebSocket receive requires an input-defined cancellation event",
        ));
    }
    let incoming = input
        .get("incoming")
        .and_then(Value::as_array)
        .map(|events| {
            events
                .iter()
                .enumerate()
                .map(|(index, event)| parse_native_websocket_event(event, index))
                .collect::<Result<VecDeque<_>, _>>()
        })
        .transpose()?
        .unwrap_or_default();
    let observations = Arc::new(Mutex::new(NativeWebSocketProbe::default()));
    let cancellation = Arc::new(NativeWebSocketCancellation::default());
    let driver: Arc<dyn NativeWebSocketDriver> = Arc::new(NativeWebSocketDriverProbe {
        incoming: Mutex::new(incoming),
        pending_receive,
        cancel_receive,
        cancellation,
        observations: Arc::clone(&observations),
    });
    let route_observations = Arc::clone(&observations);
    let route = NativeWebSocketRoute::new(route_path, preferred, move |mut session| {
        let observations = Arc::clone(&route_observations);
        let actions = actions.clone();
        let route_path_params = route_path_params.clone();
        let typed_route_path_params = typed_route_path_params.clone();
        async move {
            if session.path_params() != route_path_params.as_slice() {
                return Err(NativeWebSocketError::application(io::Error::other(
                    "native WebSocket route captures differ from the route table",
                )));
            }
            let handshake = json!({
                "method": session.handshake().method().as_str(),
                "uri": session.handshake().uri().to_string(),
                "version": native_http_version_name(session.handshake().version()),
                "headers": native_header_pairs(session.handshake().headers()),
                "offered_subprotocols": session.handshake().offered_subprotocols(),
            });
            if let Ok(mut probe) = observations.lock() {
                probe.path_params = Some(typed_route_path_params);
                probe.handshake = Some(handshake);
            }
            let mut last_message = None::<NativeWebSocketMessage>;
            for (index, action_value) in actions.iter().enumerate() {
                let context = format!("native WebSocket actions[{index}]");
                let action = action_value.as_object().ok_or_else(|| {
                    NativeWebSocketError::application(io::Error::other(format!(
                        "{context} must be an object"
                    )))
                })?;
                match action.get("action").and_then(Value::as_str) {
                    Some("accept-preferred") => {
                        let headers = parse_native_headers(
                            action.get("headers").ok_or_else(|| {
                                NativeWebSocketError::application(io::Error::other(format!(
                                    "{context} misses headers"
                                )))
                            })?,
                            &format!("{context}.headers"),
                        )
                        .map_err(|error| {
                            NativeWebSocketError::application(io::Error::other(error))
                        })?;
                        session.accept_preferred(headers).await?;
                    }
                    Some("receive") => match session.receive().await {
                        Ok(NativeWebSocketEvent::Message(message)) => {
                            last_message = Some(message);
                        }
                        Ok(NativeWebSocketEvent::PeerClosed(_)) => {
                            last_message = None;
                        }
                        Err(error) => {
                            let error_kind = match &error {
                                NativeWebSocketError::Cancelled => "cancelled",
                                NativeWebSocketError::Transport(_) => "transport",
                                NativeWebSocketError::Application(_) => "application",
                                _ => "protocol",
                            };
                            if let Ok(mut probe) = observations.lock() {
                                probe.result_error_kind = Some(error_kind.to_owned());
                            }
                            return Err(error);
                        }
                    },
                    Some("send-received") => {
                        if let Some(message) = last_message.take() {
                            session.send(message).await?;
                        }
                    }
                    Some("close") => {
                        let code = action
                            .get("code")
                            .and_then(Value::as_u64)
                            .and_then(|code| u16::try_from(code).ok())
                            .ok_or_else(|| {
                                NativeWebSocketError::application(io::Error::other(format!(
                                    "{context}.code must be a u16"
                                )))
                            })?;
                        let reason =
                            action
                                .get("reason")
                                .and_then(Value::as_str)
                                .ok_or_else(|| {
                                    NativeWebSocketError::application(io::Error::other(format!(
                                        "{context}.reason must be a string"
                                    )))
                                })?;
                        let close = NativeWebSocketClose::new(code, reason).map_err(|error| {
                            NativeWebSocketError::application(io::Error::other(error.to_string()))
                        })?;
                        session.close(close).await?;
                    }
                    Some("return-application-error") => {
                        let error =
                            action
                                .get("error")
                                .and_then(Value::as_object)
                                .ok_or_else(|| {
                                    NativeWebSocketError::application(io::Error::other(format!(
                                        "{context}.error must be an object"
                                    )))
                                })?;
                        let kind = error.get("kind").and_then(Value::as_str).ok_or_else(|| {
                            NativeWebSocketError::application(io::Error::other(format!(
                                "{context}.error.kind must be a string"
                            )))
                        })?;
                        if kind != "io-error" {
                            return Err(NativeWebSocketError::application(io::Error::other(
                                format!("{context}.error.kind must select io-error"),
                            )));
                        }
                        let message =
                            error
                                .get("message")
                                .and_then(Value::as_str)
                                .ok_or_else(|| {
                                    NativeWebSocketError::application(io::Error::other(format!(
                                        "{context}.error.message must be a string"
                                    )))
                                })?;
                        if let Ok(mut probe) = observations.lock() {
                            probe.application_error =
                                Some(json!({"kind": "OSError", "message": message}));
                        }
                        return Err(NativeWebSocketError::application(io::Error::other(
                            message.to_owned(),
                        )));
                    }
                    Some(unsupported) => {
                        return Err(NativeWebSocketError::application(io::Error::other(
                            format!("{context}.action {unsupported:?} is unsupported"),
                        )));
                    }
                    None => {
                        return Err(NativeWebSocketError::application(io::Error::other(
                            format!("{context}.action must be a string"),
                        )));
                    }
                }
            }
            Ok(())
        }
    });
    let router = NativeWebSocketRouter::new([route]).map_err(|error| error.to_string())?;
    let dispatch_result = block_on(router.dispatch(handshake, driver));
    if let Err(error) = dispatch_result {
        if let Ok(mut probe) = observations.lock() {
            if probe.result_error_kind.is_none() {
                probe.result_error_kind = Some(match &error {
                    NativeWebSocketError::Cancelled => String::from("cancelled"),
                    NativeWebSocketError::Transport(_) => String::from("transport"),
                    NativeWebSocketError::Application(_) => String::from("application"),
                    _ => String::from("protocol"),
                });
            }
        }
    }
    let probe = observations
        .lock()
        .map_err(|_| String::from("native WebSocket observation lock is poisoned"))?;
    let mut values = Map::new();
    values.insert(
        String::from("handshake.acceptance"),
        probe.acceptance.clone().unwrap_or(Value::Null),
    );
    values.insert(
        String::from("handshake.selected_subprotocol"),
        probe
            .acceptance
            .as_ref()
            .and_then(|accepted| accepted.get("subprotocol"))
            .cloned()
            .unwrap_or(Value::Null),
    );
    values.insert(
        String::from("session.handshake"),
        probe.handshake.clone().unwrap_or(Value::Null),
    );
    values.insert(
        String::from("session.path_params"),
        probe.path_params.clone().unwrap_or(Value::Null),
    );
    values.insert(String::from("session.messages"), json!(probe.messages));
    values.insert(
        String::from("session.close"),
        probe.close.clone().unwrap_or(Value::Null),
    );
    values.insert(
        String::from("session.peer_close"),
        probe.peer_close.clone().unwrap_or(Value::Null),
    );
    values.insert(
        String::from("application_error.kind"),
        probe
            .application_error
            .as_ref()
            .and_then(|error| error.get("kind"))
            .cloned()
            .unwrap_or(Value::Null),
    );
    values.insert(
        String::from("application_error.message"),
        probe
            .application_error
            .as_ref()
            .and_then(|error| error.get("message"))
            .cloned()
            .unwrap_or(Value::Null),
    );
    values.insert(
        String::from("application_result.error_kind"),
        probe
            .result_error_kind
            .clone()
            .map_or(Value::Null, |kind| json!(kind)),
    );
    values.insert(
        String::from("transport.receive_cancelled"),
        json!(probe.receive_cancelled && probe.receive_started),
    );
    native_observation_result(case_id, case, values, "native WebSocket")
}

fn native_websocket_path_parameters(
    route_path: &str,
    uri: &Uri,
) -> Result<(Vec<(String, String)>, Value), String> {
    let mut routes = RouteTable::new();
    routes
        .add_route(route_path, std::iter::empty::<&str>())
        .map_err(|error| format!("native WebSocket route is invalid: {error}"))?;
    let DetailedRouteMatch::Matched {
        route_index,
        path_params,
    } = routes.matches_detailed(uri.path(), "")
    else {
        return Ok((Vec::new(), Value::Null));
    };
    let captures = routes
        .capture_path_parameters(route_index, &path_params)
        .map_err(|error| format!("native WebSocket route captures are invalid: {error}"))?;
    let string_params = captures
        .iter()
        .map(|capture| (capture.name.clone(), capture.value.clone()))
        .collect();
    let typed_params = captures
        .into_iter()
        .map(|capture| {
            let value = match capture.converter {
                PathConverter::Integer | PathConverter::Float => {
                    serde_json::from_str::<Value>(&capture.value).map_err(|error| {
                        format!(
                            "native WebSocket numeric path parameter {} is invalid: {error}",
                            capture.name
                        )
                    })?
                }
                PathConverter::String | PathConverter::Uuid | PathConverter::Path => {
                    Value::String(capture.value)
                }
            };
            Ok((capture.name, value))
        })
        .collect::<Result<Map<_, _>, String>>()?;
    Ok((string_params, Value::Object(typed_params)))
}

fn parse_native_websocket_event(
    value: &Value,
    index: usize,
) -> Result<NativeWebSocketEvent, String> {
    let context = format!("native WebSocket incoming[{index}]");
    let object = value
        .as_object()
        .ok_or_else(|| format!("{context} must be an object"))?;
    match string_field(object, "kind", &context)? {
        "text" => {
            exact_keys(object, &["kind", "value"], &context)?;
            Ok(NativeWebSocketEvent::Message(NativeWebSocketMessage::Text(
                string_field(object, "value", &context)?.to_owned(),
            )))
        }
        "binary" => {
            exact_keys(object, &["kind", "base64"], &context)?;
            Ok(NativeWebSocketEvent::Message(
                NativeWebSocketMessage::Binary(Bytes::from(decode_base64(
                    string_field(object, "base64", &context)?,
                    &format!("{context}.base64"),
                )?)),
            ))
        }
        "peer-close" => {
            object_with_optional_keys(value, &["kind", "reason"], &["code"], &context)?;
            let code = object
                .get("code")
                .and_then(Value::as_u64)
                .and_then(|code| u16::try_from(code).ok());
            Ok(NativeWebSocketEvent::PeerClosed(NativeWebSocketPeerClose {
                code,
                reason: string_field(object, "reason", &context)?.to_owned(),
            }))
        }
        kind => Err(format!("{context}.kind {kind:?} is unsupported")),
    }
}

fn parse_native_headers(value: &Value, context: &str) -> Result<HeaderMap, String> {
    let pairs = value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    let mut headers = HeaderMap::new();
    for (index, pair) in pairs.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| format!("{context}[{index}] must be a two-element pair"))?;
        let name = pair[0]
            .as_str()
            .ok_or_else(|| format!("{context}[{index}][0] must be a string"))?;
        let value = pair[1]
            .as_str()
            .ok_or_else(|| format!("{context}[{index}][1] must be a string"))?;
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|error| format!("{context}[{index}] header name is invalid: {error}"))?;
        let value = HeaderValue::from_bytes(value.as_bytes())
            .map_err(|error| format!("{context}[{index}] header value is invalid: {error}"))?;
        headers.append(name, value);
    }
    Ok(headers)
}

fn native_header_pairs(headers: &HeaderMap) -> Vec<Value> {
    headers
        .iter()
        .map(|(name, value)| json!([name.as_str(), encode_base64(value.as_bytes())]))
        .collect()
}

fn native_websocket_message_value(message: &NativeWebSocketMessage) -> Value {
    match message {
        NativeWebSocketMessage::Text(value) => json!({"kind": "text", "value": value}),
        NativeWebSocketMessage::Binary(value) => {
            json!({"kind": "binary", "base64": encode_base64(value)})
        }
    }
}

fn native_http_version_name(version: http::Version) -> &'static str {
    match version {
        http::Version::HTTP_09 => "HTTP/0.9",
        http::Version::HTTP_10 => "HTTP/1.0",
        http::Version::HTTP_11 => "HTTP/1.1",
        http::Version::HTTP_2 => "HTTP/2",
        http::Version::HTTP_3 => "HTTP/3",
        _ => "unknown",
    }
}

#[derive(Debug)]
struct NativeLifespanFixtureError(String);

impl std::fmt::Display for NativeLifespanFixtureError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for NativeLifespanFixtureError {}

#[derive(Default)]
struct NativeLifespanProbe {
    events: Vec<String>,
}

fn run_native_lifespan_case(case: &Value) -> Result<Value, String> {
    let case = object_with_optional_keys(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "inputs",
            "observations",
        ],
        &["oracle_applicability", "fault_contract"],
        "native lifespan case",
    )?;
    let case_id = string_field(case, "case_id", "native lifespan case")?;
    let surface = string_field(case, "surface", "native lifespan case")?;
    let operation = string_field(case, "operation", "native lifespan case")?;
    if surface != "starlette-rs.NativeLifespan"
        || !matches!(
            operation,
            "native-lifespan" | "start" | "shutdown" | "active-shutdown"
        )
    {
        return Err(String::from(
            "native lifespan surface or operation is unsupported",
        ));
    }
    let inputs = exact_object(
        case.get("inputs")
            .ok_or_else(|| String::from("native lifespan case misses inputs"))?,
        &["registrations", "host_actions"],
        "native lifespan inputs",
    )?;
    let registrations = inputs
        .get("registrations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native lifespan registrations must be an array"))?;
    let host_actions = inputs
        .get("host_actions")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("native lifespan host_actions must be an array"))?
        .iter()
        .map(|action| {
            action
                .as_str()
                .ok_or_else(|| String::from("native lifespan host_actions must contain strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;

    let mut hook_specs = Vec::with_capacity(registrations.len());
    let mut registration_names = Vec::with_capacity(registrations.len());
    for (index, registration) in registrations.iter().enumerate() {
        let context = format!("native lifespan registrations[{index}]");
        let registration = exact_object(registration, &["name", "startup", "shutdown"], &context)?;
        registration_names.push(string_field(registration, "name", &context)?.to_owned());
        let startup = exact_object(
            registration
                .get("startup")
                .ok_or_else(|| format!("{context} misses startup"))?,
            &["actions"],
            &format!("{context}.startup"),
        )?;
        let shutdown = exact_object(
            registration
                .get("shutdown")
                .ok_or_else(|| format!("{context} misses shutdown"))?,
            &["actions"],
            &format!("{context}.shutdown"),
        )?;
        hook_specs.push((
            parse_lifespan_actions(startup, &format!("{context}.startup"))?,
            parse_lifespan_actions(shutdown, &format!("{context}.shutdown"))?,
        ));
    }

    let probe = Arc::new(Mutex::new(NativeLifespanProbe::default()));
    let mut builder = NativeLifespan::builder();
    for (startup_actions, shutdown_actions) in hook_specs {
        let startup_probe = Arc::clone(&probe);
        let shutdown_probe = Arc::clone(&probe);
        builder = builder.on_lifecycle(
            move |state| {
                let actions = startup_actions.clone();
                let probe = Arc::clone(&startup_probe);
                async move { run_lifespan_actions(&actions, state, Arc::clone(&probe)).await }
            },
            move |state| {
                let actions = shutdown_actions.clone();
                let probe = Arc::clone(&shutdown_probe);
                async move { run_lifespan_actions(&actions, state, Arc::clone(&probe)).await }
            },
        );
    }
    let lifecycle = builder.build();

    let mut state_before_shutdown = Value::Null;
    let mut startup_failure = Value::Null;
    let mut shutdown_failure = Value::Null;
    let mut lifecycle = Some(lifecycle);
    let mut active = None::<ActiveNativeLifespan>;
    let mut pending_start_future =
        None::<Pin<Box<dyn Future<Output = Result<ActiveNativeLifespan, NativeLifespanError>>>>>;
    let mut pending_shutdown_future =
        None::<Pin<Box<dyn Future<Output = Result<(), NativeLifespanError>>>>>;

    for action in host_actions.iter().copied() {
        match action {
            "start-to-completion" => {
                let lifecycle_to_start = lifecycle
                    .take()
                    .ok_or_else(|| String::from("native lifespan start was requested twice"))?;
                match block_on(lifecycle_to_start.start()) {
                    Ok(started) => active = Some(started),
                    Err(error) => {
                        startup_failure = native_lifespan_error_value(&error, &registration_names)?;
                        break;
                    }
                }
            }
            "observe-state" => {
                let active_lifecycle = active.as_ref().ok_or_else(|| {
                    String::from("native lifespan state observation requires startup")
                })?;
                state_before_shutdown =
                    native_lifespan_state_snapshot(active_lifecycle.state(), registrations)?;
            }
            "shutdown-to-completion" => {
                let active_lifecycle = active
                    .take()
                    .ok_or_else(|| String::from("native lifespan shutdown requires startup"))?;
                if let Err(error) = block_on(active_lifecycle.shutdown()) {
                    shutdown_failure =
                        if operation == "shutdown" && case.get("fault_contract").is_some() {
                            native_lifespan_aggregated_shutdown_error_value(
                                &error,
                                &registration_names,
                            )?
                        } else {
                            native_lifespan_error_value(&error, &registration_names)?
                        };
                }
            }
            "start-to-cache-suspension" => {
                let lifecycle_to_start = lifecycle
                    .take()
                    .ok_or_else(|| String::from("native lifespan start was requested twice"))?;
                let mut start_future = Box::pin(lifecycle_to_start.start());
                match poll_future_once(start_future.as_mut()) {
                    Poll::Pending => pending_start_future = Some(start_future),
                    Poll::Ready(Ok(started)) => {
                        active = Some(started);
                    }
                    Poll::Ready(Err(error)) => {
                        startup_failure = native_lifespan_error_value(&error, &registration_names)?;
                    }
                }
            }
            "drive-shutdown-until-host-deadline" => {
                let active_lifecycle = active.take().ok_or_else(|| {
                    String::from("native lifespan deadline requires completed startup")
                })?;
                let mut shutdown_future = Box::pin(active_lifecycle.shutdown());
                match poll_future_once(shutdown_future.as_mut()) {
                    Poll::Pending => pending_shutdown_future = Some(shutdown_future),
                    Poll::Ready(Ok(())) => {}
                    Poll::Ready(Err(error)) => {
                        shutdown_failure =
                            native_lifespan_error_value(&error, &registration_names)?;
                    }
                }
            }
            "drop-start-future" => {
                if pending_start_future.take().is_none() {
                    return Err(String::from(
                        "drop-start-future requires a startup future suspended by the host",
                    ));
                }
            }
            "drop-shutdown-future" => {
                if pending_shutdown_future.take().is_none() {
                    return Err(String::from(
                        "drop-shutdown-future requires a shutdown future suspended by the host",
                    ));
                }
            }
            _ => {
                return Err(format!(
                    "native lifespan host action {action:?} is unsupported"
                ));
            }
        }
    }
    if pending_start_future.is_some() || pending_shutdown_future.is_some() {
        return Err(String::from(
            "native lifespan host_actions must explicitly drop each pending future",
        ));
    }
    let event_sequence = native_lifespan_events(&probe)?;
    let record = json!({
        "lifecycle-event-sequence": event_sequence,
        "lifecycle-state-before-shutdown": state_before_shutdown,
        "startup-failure": startup_failure,
        "shutdown-failure": shutdown_failure,
    });
    let mut values = Map::new();
    if let Some(record) = record.as_object() {
        for (key, value) in record {
            values.insert(key.clone(), value.clone());
        }
    }
    native_observation_result(case_id, case, values, "native lifespan")
}

fn parse_lifespan_actions(hook: &Map<String, Value>, context: &str) -> Result<Vec<Value>, String> {
    let actions = hook
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.actions must be an array"))?;
    Ok(actions.clone())
}

async fn run_lifespan_actions(
    actions: &[Value],
    state: NativeLifespanState,
    probe: Arc<Mutex<NativeLifespanProbe>>,
) -> Result<(), NativeLifespanFixtureError> {
    for action in actions {
        let object = action.as_object().ok_or_else(|| {
            NativeLifespanFixtureError(String::from("lifespan hook action must be an object"))
        })?;
        if let Some(raw_event) = object.get("append-event") {
            let event = raw_event.as_str().ok_or_else(|| {
                NativeLifespanFixtureError(String::from("append-event value must be a string"))
            })?;
            probe
                .lock()
                .map_err(|_| {
                    NativeLifespanFixtureError(String::from("lifespan probe is poisoned"))
                })?
                .events
                .push(event.to_owned());
        } else if let Some(raw_state) = object.get("insert-state") {
            let state_spec = raw_state.as_object().ok_or_else(|| {
                NativeLifespanFixtureError(String::from("insert-state must be an object"))
            })?;
            let key = state_spec
                .get("key")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    NativeLifespanFixtureError(String::from("state key must be a string"))
                })?;
            let value = state_spec
                .get("value")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    NativeLifespanFixtureError(String::from("state value must be a string"))
                })?;
            state
                .insert(key, value.to_owned())
                .map_err(|error| NativeLifespanFixtureError(error.to_string()))?;
        } else if let Some(raw_key) = object.get("remove-state") {
            let key = raw_key.as_str().ok_or_else(|| {
                NativeLifespanFixtureError(String::from("remove-state value must be a string"))
            })?;
            let _ = state
                .remove::<String>(key)
                .map_err(|error| NativeLifespanFixtureError(error.to_string()))?;
        } else if let Some(raw_error) = object.get("raise") {
            let error = raw_error.as_object().ok_or_else(|| {
                NativeLifespanFixtureError(String::from("raise action must be an object"))
            })?;
            let message = error
                .get("message")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    NativeLifespanFixtureError(String::from("raise message must be a string"))
                })?;
            return Err(NativeLifespanFixtureError(message.to_owned()));
        } else if object.get("suspend-until-host-release") == Some(&Value::Bool(true)) {
            pending::<()>().await;
        } else {
            return Err(NativeLifespanFixtureError(String::from(
                "lifespan hook action is unsupported",
            )));
        }
    }
    Ok(())
}

fn native_lifespan_events(probe: &Arc<Mutex<NativeLifespanProbe>>) -> Result<Vec<String>, String> {
    probe
        .lock()
        .map(|probe| probe.events.clone())
        .map_err(|_| String::from("native lifespan probe lock is poisoned"))
}

fn native_lifespan_state_snapshot(
    state: &NativeLifespanState,
    registrations: &[Value],
) -> Result<Value, String> {
    let mut snapshot = Map::new();
    for registration in registrations {
        let registration = registration
            .as_object()
            .ok_or_else(|| String::from("native lifespan registration must be an object"))?;
        for hook_name in ["startup", "shutdown"] {
            let hook = registration
                .get(hook_name)
                .and_then(Value::as_object)
                .ok_or_else(|| format!("native lifespan registration misses {hook_name}"))?;
            let actions = hook
                .get("actions")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("native lifespan {hook_name} actions must be an array"))?;
            for action in actions {
                if let Some(state_spec) = action.get("insert-state").and_then(Value::as_object) {
                    let key = state_spec
                        .get("key")
                        .and_then(Value::as_str)
                        .ok_or_else(|| {
                            String::from("native lifespan state key must be a string")
                        })?;
                    if let Some(value) = state
                        .get::<String>(key)
                        .map_err(|error| error.to_string())?
                    {
                        snapshot.insert(key.to_owned(), json!(value.as_str()));
                    }
                }
            }
        }
    }
    Ok(Value::Object(snapshot))
}

fn native_lifespan_registration_name(
    registration_names: &[String],
    hook_index: usize,
) -> Result<&str, String> {
    registration_names
        .get(hook_index)
        .map(String::as_str)
        .ok_or_else(|| {
            format!("native lifespan failure references missing hook index {hook_index}")
        })
}

fn native_lifespan_failure_value(
    hook_index: usize,
    message: String,
    registration_names: &[String],
) -> Result<Value, String> {
    Ok(json!({
        "hook_index": hook_index,
        "registration": native_lifespan_registration_name(registration_names, hook_index)?,
        "message": message,
    }))
}

fn native_lifespan_error_value(
    error: &NativeLifespanError,
    registration_names: &[String],
) -> Result<Value, String> {
    match error {
        NativeLifespanError::Startup {
            hook_index,
            source,
            shutdown_failures,
        } => {
            let rollback_failures = shutdown_failures
                .iter()
                .map(|failure| {
                    native_lifespan_failure_value(
                        failure.hook_index(),
                        failure.source_error().to_string(),
                        registration_names,
                    )
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok(json!({
                "kind": "startup",
                "hook_index": hook_index,
                "registration": native_lifespan_registration_name(
                    registration_names,
                    *hook_index,
                )?,
                "message": source.to_string(),
                "rollback_failures": rollback_failures,
            }))
        }
        NativeLifespanError::Shutdown { failures } => Ok(json!({
            "kind": "shutdown",
            "failures": failures.iter().map(|failure| {
                native_lifespan_failure_value(
                    failure.hook_index(),
                    failure.source_error().to_string(),
                    registration_names,
                )
            }).collect::<Result<Vec<_>, _>>()?,
        })),
    }
}

fn native_lifespan_aggregated_shutdown_error_value(
    error: &NativeLifespanError,
    registration_names: &[String],
) -> Result<Value, String> {
    match error {
        NativeLifespanError::Shutdown { failures } => Ok(json!({
            "failures": failures.iter().map(|failure| json!({
                "hook_index": failure.hook_index(),
                "message": failure.source_error().to_string(),
            })).collect::<Vec<_>>(),
        })),
        NativeLifespanError::Startup { .. } => {
            native_lifespan_error_value(error, registration_names)
        }
    }
}

fn run_query_params_case(case: &Value) -> Result<Value, String> {
    let case = object_with_optional_keys(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "source",
            "probe_keys",
            "comparison",
            "observations",
        ],
        &["probe_default"],
        "QueryParams construction case",
    )?;
    if string_field(case, "surface", "QueryParams case")? != QUERY_PARAMS_SURFACE
        || string_field(case, "operation", "QueryParams case")? != QUERY_PARAMS_OPERATION
    {
        return Err(String::from(
            "QueryParams surface or operation is unsupported",
        ));
    }

    let params = query_params_from_input(
        case.get("source")
            .ok_or_else(|| String::from("QueryParams case has no source"))?,
    )?;
    let comparison = match case.get("comparison") {
        Some(Value::Null) => None,
        Some(value) => Some(query_params_from_input(value)?),
        None => return Err(String::from("QueryParams case has no comparison input")),
    };
    let probe_keys = case
        .get("probe_keys")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("QueryParams probe_keys must be an array"))?;
    let mut lookups = Vec::with_capacity(probe_keys.len());
    for (index, key) in probe_keys.iter().enumerate() {
        let key = key
            .as_str()
            .ok_or_else(|| format!("QueryParams probe_keys[{index}] must be a string"))?;
        let scalar = params.get(key);
        let get_with_default = scalar
            .map(|value| Value::String(value.to_owned()))
            .or_else(|| case.get("probe_default").cloned())
            .unwrap_or(Value::Null);
        lookups.push(json!({
            "key": key,
            "contains": scalar.is_some(),
            "get": scalar,
            "get_with_default": get_with_default,
            "getlist": params.get_list(key),
            "getitem": scalar,
        }));
    }
    let mut dict = Map::new();
    for (key, value) in params.items() {
        dict.insert(key.to_owned(), Value::String(value.to_owned()));
    }
    let query_string = params.query_string();
    let snapshot = json!({
        "str": query_string,
        "repr": format!("QueryParams('{query_string}')"),
        "len": params.len(),
        "is_empty": params.is_empty(),
        "keys": params.keys(),
        "values": params.values(),
        "items": params.items(),
        "multi_items": params.multi_items(),
        "dict": dict,
        "lookups": lookups,
        "equals_comparison": comparison.map(|value| params == value),
    });
    Ok(json!({
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{"step_id": "snapshot", "status": "ok", "value": {"snapshot": snapshot}}],
    }))
}

fn run_multidict_case(case: &Value) -> Result<Value, String> {
    let case = object_with_optional_keys(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "source",
            "probe_keys",
            "comparison",
            "actions",
            "observations",
        ],
        &["probe_default"],
        "MultiDict mutation case",
    )?;
    if string_field(case, "surface", "MultiDict case")? != MULTIDICT_SURFACE
        || string_field(case, "operation", "MultiDict case")? != MULTIDICT_OPERATION
    {
        return Err(String::from(
            "MultiDict surface or operation is unsupported",
        ));
    }
    let mut value = multidict_from_source(
        case.get("source")
            .ok_or_else(|| String::from("MultiDict case has no source"))?,
    )?;
    let comparison = match case.get("comparison") {
        Some(Value::Null) => None,
        Some(source) => Some(multidict_from_source(source)?),
        None => return Err(String::from("MultiDict case has no comparison input")),
    };
    let probe_keys = case
        .get("probe_keys")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("MultiDict probe_keys must be an array"))?;
    let probe_default = case.get("probe_default");
    let initial = multidict_snapshot(&value, probe_keys, probe_default)?;
    let actions = case
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("MultiDict actions must be an array"))?;
    let mut action_trace = Vec::with_capacity(actions.len());
    for (index, action) in actions.iter().enumerate() {
        let action = exact_object(
            action,
            &["action_id", "method", "args", "kwargs"],
            "MultiDict action",
        )?;
        let action_id = string_field(action, "action_id", "MultiDict action")?;
        let method = string_field(action, "method", "MultiDict action")?;
        let args = action
            .get("args")
            .and_then(Value::as_array)
            .ok_or_else(|| format!("MultiDict actions[{index}].args must be an array"))?;
        let kwargs = action
            .get("kwargs")
            .and_then(Value::as_object)
            .ok_or_else(|| format!("MultiDict actions[{index}].kwargs must be an object"))?;
        let output = apply_multidict_action(&mut value, method, args, kwargs)?;
        action_trace.push(json!({
            "action_id": action_id,
            "method": method,
            "outcome": "value",
            "value": output,
            "snapshot": multidict_snapshot(&value, probe_keys, probe_default)?,
        }));
    }
    let final_snapshot = multidict_snapshot(&value, probe_keys, probe_default)?;
    let comparison_repr = comparison.as_ref().map(multidict_repr).transpose()?;
    let equals_comparison = comparison.as_ref().map(|other| value.unordered_eq(other));
    Ok(json!({
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{
            "step_id": "mutation-sequence",
            "status": "ok",
            "value": {
                "mutation-sequence": {
                    "initial": initial,
                    "action_trace": action_trace,
                    "final": final_snapshot,
                    "comparison_repr": comparison_repr,
                    "equals_comparison": equals_comparison,
                }
            }
        }],
    }))
}

fn run_mutable_headers_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "instances",
            "actions",
            "observations",
        ],
        "MutableHeaders consumer-sequence case",
    )?;
    if string_field(case, "surface", "MutableHeaders case")? != MUTABLE_HEADERS_SURFACE
        || string_field(case, "operation", "MutableHeaders case")? != MUTABLE_HEADERS_OPERATION
    {
        return Err(String::from(
            "MutableHeaders surface or operation is unsupported",
        ));
    }
    let case_id = string_field(case, "case_id", "MutableHeaders case")?;
    let raw_instances = case
        .get("instances")
        .and_then(Value::as_array)
        .filter(|instances| !instances.is_empty())
        .ok_or_else(|| String::from("MutableHeaders instances must be a non-empty array"))?;
    let mut instances: Vec<(String, NativeMutableHeaders)> =
        Vec::with_capacity(raw_instances.len());
    for (index, raw_instance) in raw_instances.iter().enumerate() {
        let instance = exact_object(
            raw_instance,
            &["instance_id", "constructor"],
            "MutableHeaders instance",
        )?;
        let instance_id = string_field(instance, "instance_id", "MutableHeaders instance")?;
        if instance_id.is_empty()
            || instances
                .iter()
                .any(|(existing, _)| existing == instance_id)
        {
            return Err(format!(
                "MutableHeaders instances[{index}] has an invalid or duplicate ID"
            ));
        }
        let constructor = exact_object(
            instance
                .get("constructor")
                .ok_or_else(|| format!("MutableHeaders instances[{index}] has no constructor"))?,
            &["kind", "headers_base64_pairs"],
            "MutableHeaders raw constructor",
        )?;
        if string_field(constructor, "kind", "MutableHeaders raw constructor")? != "raw" {
            return Err(String::from(
                "MutableHeaders native adapter supports only raw constructors",
            ));
        }
        let raw_pairs = decode_mutable_headers_pairs(
            constructor
                .get("headers_base64_pairs")
                .ok_or_else(|| String::from("MutableHeaders raw constructor has no pairs"))?,
            &format!("MutableHeaders instances[{index}].headers_base64_pairs"),
        )?;
        instances.push((
            instance_id.to_owned(),
            NativeMutableHeaders::from_raw(raw_pairs),
        ));
    }

    let actions = case
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("MutableHeaders actions must be an array"))?;
    let mut action_trace = Vec::with_capacity(actions.len());
    for (index, raw_action) in actions.iter().enumerate() {
        let action = exact_object(
            raw_action,
            &["action_id", "receiver", "call", "arguments"],
            "MutableHeaders action",
        )?;
        let action_id = string_field(action, "action_id", "MutableHeaders action")?;
        if action_id.is_empty() {
            return Err(format!(
                "MutableHeaders actions[{index}].action_id is empty"
            ));
        }
        let receiver = string_field(action, "receiver", "MutableHeaders action")?;
        let call = string_field(action, "call", "MutableHeaders action")?;
        if call != "add_vary_header" {
            return Err(format!(
                "MutableHeaders actions[{index}] supports only add_vary_header"
            ));
        }
        let arguments = action
            .get("arguments")
            .and_then(Value::as_array)
            .filter(|arguments| arguments.len() == 1)
            .ok_or_else(|| {
                format!("MutableHeaders actions[{index}].arguments must have one string")
            })?;
        let vary = arguments[0].as_str().ok_or_else(|| {
            format!("MutableHeaders actions[{index}].arguments[0] must be a string")
        })?;
        let vary = encode_mutable_headers_value(vary, &format!("MutableHeaders actions[{index}]"))?;
        let (_, headers) = instances
            .iter_mut()
            .find(|(instance_id, _)| instance_id == receiver)
            .ok_or_else(|| {
                format!("MutableHeaders actions[{index}] references an unknown receiver")
            })?;
        headers.add_vary_header(&vary);
        action_trace.push(json!({
            "action_id": action_id,
            "receiver": receiver,
            "call": call,
            "outcome": "value",
            "value": Value::Null,
        }));
    }

    let observations = case
        .get("observations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("MutableHeaders observations must be an array"))?;
    if observations.len() != 1 || observations[0].as_str() != Some("raw-pairs") {
        return Err(String::from(
            "MutableHeaders observations must select exactly raw-pairs",
        ));
    }
    let observation = observations
        .first()
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("MutableHeaders observation must be a string"))?;
    let raw_pairs = instances
        .iter()
        .map(|(instance_id, headers)| {
            json!({
                "instance_id": instance_id,
                "headers_base64_pairs": canonical_headers(headers.raw_pairs()),
            })
        })
        .collect::<Vec<_>>();
    let instance_snapshots = instances
        .iter()
        .map(|(instance_id, headers)| {
            let view = headers.as_headers();
            json!({
                "instance_id": instance_id,
                "python_type": "starlette.datastructures.MutableHeaders",
                "raw_base64_pairs": canonical_headers(headers.raw_pairs()),
                "keys": view.keys(),
                "values": view.values(),
                "items": view.items(),
                "length": view.len(),
                "repr": mutable_headers_repr(headers.raw_pairs()),
            })
        })
        .collect::<Vec<_>>();
    let mut observation_value = Map::new();
    observation_value.insert(String::from("action-trace"), json!(action_trace));
    observation_value.insert(
        String::from("instance-snapshots"),
        json!(instance_snapshots),
    );
    observation_value.insert(String::from("scope-snapshots"), json!([]));
    observation_value.insert(String::from("raw-pairs"), json!(raw_pairs));

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": observation,
            "status": "ok",
            "value": observation_value,
        }],
    }))
}

fn mutable_headers_repr(headers: &[(Vec<u8>, Vec<u8>)]) -> String {
    let mut mapping = Vec::<(String, String)>::new();
    for (name, value) in headers {
        let name = decode_latin1(name);
        let value = decode_latin1(value);
        if let Some((_, existing_value)) = mapping.iter_mut().find(|(key, _)| key.as_str() == name)
        {
            *existing_value = value;
        } else {
            mapping.push((name, value));
        }
    }

    if mapping.len() == headers.len() {
        let entries = mapping
            .iter()
            .map(|(name, value)| {
                format!(
                    "{}: {}",
                    mutable_headers_string_repr(name),
                    mutable_headers_string_repr(value)
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        format!("MutableHeaders({{{entries}}})")
    } else {
        let pairs = headers
            .iter()
            .map(|(name, value)| {
                format!(
                    "({}, {})",
                    mutable_headers_bytes_repr(name),
                    mutable_headers_bytes_repr(value)
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        format!("MutableHeaders(raw=[{pairs}])")
    }
}

fn mutable_headers_string_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut output = String::new();
    output.push(quote);
    for character in value.chars() {
        match character {
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            current if current == quote => {
                output.push('\\');
                output.push(current);
            }
            current if !python_character_is_printable(current) => {
                use std::fmt::Write as _;
                let codepoint = u32::from(current);
                if codepoint <= 0xff {
                    let _ = write!(output, "\\x{codepoint:02x}");
                } else if codepoint <= 0xffff {
                    let _ = write!(output, "\\u{codepoint:04x}");
                } else {
                    let _ = write!(output, "\\U{codepoint:08x}");
                }
            }
            current => output.push(current),
        }
    }
    output.push(quote);
    output
}

fn mutable_headers_bytes_repr(value: &[u8]) -> String {
    let quote = if value.contains(&b'\'') && !value.contains(&b'"') {
        '"'
    } else {
        '\''
    };
    let mut output = String::new();
    output.push('b');
    output.push(quote);
    for byte in value {
        match *byte {
            b'\\' => output.push_str("\\\\"),
            b'\n' => output.push_str("\\n"),
            b'\r' => output.push_str("\\r"),
            b'\t' => output.push_str("\\t"),
            current if current == quote as u8 => {
                output.push('\\');
                output.push(char::from(current));
            }
            0x20..=0x7e => output.push(char::from(*byte)),
            current => output.push_str(&format!("\\x{current:02x}")),
        }
    }
    output.push(quote);
    output
}

fn python_character_is_printable(character: char) -> bool {
    match get_general_category(character) {
        GeneralCategory::Control
        | GeneralCategory::Format
        | GeneralCategory::Surrogate
        | GeneralCategory::PrivateUse
        | GeneralCategory::Unassigned
        | GeneralCategory::LineSeparator
        | GeneralCategory::ParagraphSeparator => false,
        GeneralCategory::SpaceSeparator => character == ' ',
        _ => true,
    }
}

fn decode_mutable_headers_pairs(value: &Value, context: &str) -> Result<HeaderPairs, String> {
    let pairs = value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    pairs
        .iter()
        .enumerate()
        .map(|(index, raw_pair)| {
            let pair = raw_pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}[{index}] must be a two-item pair"))?;
            let name = pair[0]
                .as_str()
                .ok_or_else(|| format!("{context}[{index}].name must be base64 text"))?;
            let value = pair[1]
                .as_str()
                .ok_or_else(|| format!("{context}[{index}].value must be base64 text"))?;
            Ok((
                decode_base64(name, &format!("{context}[{index}].name"))?,
                decode_base64(value, &format!("{context}[{index}].value"))?,
            ))
        })
        .collect()
}

fn encode_mutable_headers_value(value: &str, context: &str) -> Result<Vec<u8>, String> {
    value
        .chars()
        .map(|character| {
            u8::try_from(u32::from(character))
                .map_err(|_| format!("{context} value cannot be encoded as Latin-1"))
        })
        .collect()
}

fn multidict_from_source(source: &Value) -> Result<NativeMultiDict<String, Value>, String> {
    let source = source
        .as_object()
        .ok_or_else(|| String::from("MultiDict source must be an object"))?;
    let kind = source
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("MultiDict source.kind must be a string"))?;
    if kind == "empty" {
        let _ = exact_object(
            &Value::Object(source.clone()),
            &["kind"],
            "empty MultiDict source",
        )?;
        return Ok(NativeMultiDict::default());
    }
    let items = source
        .get("items")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("MultiDict source.items must be an array"))?;
    let mut pairs = multidict_pairs(items, "MultiDict source.items")?;
    if kind == "pairs" {
        let kwargs = source
            .get("kwargs")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("MultiDict source.kwargs must be an array"))?;
        pairs.extend(multidict_pairs(kwargs, "MultiDict source.kwargs")?);
    } else if kind != "mapping" && kind != "copy" {
        return Err(String::from("MultiDict source.kind is unsupported"));
    }
    Ok(NativeMultiDict::from_pairs(pairs))
}

fn multidict_pairs(items: &[Value], context: &str) -> Result<Vec<(String, Value)>, String> {
    items
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}[{index}] must be a two-item array"))?;
            let key = pair[0]
                .as_str()
                .ok_or_else(|| format!("{context}[{index}][0] must be a string"))?;
            Ok((key.to_owned(), pair[1].clone()))
        })
        .collect()
}

fn apply_multidict_action(
    value: &mut NativeMultiDict<String, Value>,
    method: &str,
    args: &[Value],
    kwargs: &Map<String, Value>,
) -> Result<Value, String> {
    let key_arg = |index: usize| -> Result<String, String> {
        args.get(index)
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(|| format!("MultiDict action {method} key must be a string"))
    };
    let default_arg = |index: usize| {
        args.get(index)
            .cloned()
            .or_else(|| kwargs.get("default").cloned())
    };
    match method {
        "__setitem__" => {
            let key = key_arg(0)?;
            let item = args
                .get(1)
                .cloned()
                .ok_or_else(|| String::from("MultiDict __setitem__ value is missing"))?;
            value.set(key, item);
            Ok(Value::Null)
        }
        "__delitem__" => {
            let key = key_arg(0)?;
            value
                .pop(&key)
                .map(|_| Value::Null)
                .ok_or_else(|| format!("MultiDict key {key:?} is missing"))
        }
        "pop" => {
            let key = key_arg(0)?;
            Ok(value
                .pop(&key)
                .or_else(|| default_arg(1))
                .unwrap_or(Value::Null))
        }
        "popitem" => value
            .pop_item()
            .map(|(key, item)| json!([key, item]))
            .ok_or_else(|| String::from("MultiDict is empty")),
        "poplist" => {
            let key = key_arg(0)?;
            Ok(json!(value.pop_list(&key)))
        }
        "clear" => {
            value.clear();
            Ok(Value::Null)
        }
        "setdefault" => {
            let key = key_arg(0)?;
            Ok(value.set_default(key, default_arg(1).unwrap_or(Value::Null)))
        }
        "setlist" => {
            let key = key_arg(0)?;
            let values = args
                .get(1)
                .and_then(Value::as_array)
                .ok_or_else(|| String::from("MultiDict setlist values must be an array"))?
                .to_vec();
            value.set_list(key, values);
            Ok(Value::Null)
        }
        "append" => {
            let key = key_arg(0)?;
            let item = args
                .get(1)
                .cloned()
                .ok_or_else(|| String::from("MultiDict append value is missing"))?;
            value.append(key, item);
            Ok(Value::Null)
        }
        "update" => {
            let mut items = match args.first() {
                Some(source)
                    if source
                        .get("kind")
                        .and_then(Value::as_str)
                        .is_some_and(|kind| kind == "receiver") =>
                {
                    value.multi_items().to_vec()
                }
                Some(source) => multidict_pairs(
                    source
                        .as_array()
                        .ok_or_else(|| String::from("MultiDict update source must be an array"))?,
                    "MultiDict update source",
                )?,
                None => Vec::new(),
            };
            items.extend(kwargs.iter().map(|(key, item)| (key.clone(), item.clone())));
            value.update(NativeMultiDict::from_pairs(items));
            Ok(Value::Null)
        }
        _ => Err(format!("MultiDict action method {method:?} is unsupported")),
    }
}

fn multidict_snapshot(
    value: &NativeMultiDict<String, Value>,
    probe_keys: &[Value],
    probe_default: Option<&Value>,
) -> Result<Value, String> {
    let mut mapping = Map::new();
    for (key, item) in value.items() {
        mapping.insert(key.clone(), item.clone());
    }
    let lookups = probe_keys
        .iter()
        .map(|probe| {
            let key = probe
                .as_str()
                .ok_or_else(|| String::from("MultiDict probe key must be a string"))?;
            let scalar = value.get(&key.to_owned());
            let get_with_default = scalar
                .cloned()
                .or_else(|| probe_default.cloned())
                .unwrap_or(Value::Null);
            Ok(json!({
                "key": key,
                "contains": scalar.is_some(),
                "get": scalar,
                "get_with_default": get_with_default,
                "getlist": value.get_list(&key.to_owned()),
                "getitem": scalar,
            }))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let repr = multidict_repr(value)?;
    Ok(json!({
        "str": repr,
        "repr": multidict_repr(value)?,
        "len": value.len(),
        "is_empty": value.is_empty(),
        "keys": value.keys(),
        "values": value.values(),
        "items": value.items(),
        "multi_items": value.multi_items(),
        "dict": mapping,
        "lookups": lookups,
    }))
}

fn multidict_repr(value: &NativeMultiDict<String, Value>) -> Result<String, String> {
    let items = value
        .multi_items()
        .iter()
        .map(|(key, item)| {
            Ok(format!(
                "({}, {})",
                python_string_repr(key),
                python_json_repr(item)?
            ))
        })
        .collect::<Result<Vec<_>, String>>()?
        .join(", ");
    Ok(format!("MultiDict([{items}])"))
}

fn python_json_repr(value: &Value) -> Result<String, String> {
    match value {
        Value::Null => Ok(String::from("None")),
        Value::Bool(value) => Ok(if *value {
            String::from("True")
        } else {
            String::from("False")
        }),
        Value::Number(value) => Ok(value.to_string()),
        Value::String(value) => Ok(python_string_repr(value)),
        Value::Array(_) | Value::Object(_) => Err(String::from(
            "native MultiDict repr currently accepts scalar fixture values",
        )),
    }
}

fn python_string_repr(value: &str) -> String {
    let quote = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut output = String::new();
    output.push(quote);
    for character in value.chars() {
        match character {
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            current if current == quote => {
                output.push('\\');
                output.push(current);
            }
            current if current.is_control() => {
                output.push_str(&format!("\\x{:02x}", current as u32));
            }
            current => output.push(current),
        }
    }
    output.push(quote);
    output
}

fn run_comma_separated_strings_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "inputs",
            "index_probes",
            "observations",
        ],
        "CommaSeparatedStrings case",
    )?;
    if string_field(case, "surface", "CommaSeparatedStrings case")?
        != COMMA_SEPARATED_STRINGS_SURFACE
        || string_field(case, "operation", "CommaSeparatedStrings case")?
            != COMMA_SEPARATED_STRINGS_OPERATION
    {
        return Err(String::from(
            "CommaSeparatedStrings surface or operation is unsupported",
        ));
    }

    let inputs = case
        .get("inputs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("CommaSeparatedStrings inputs must be an array"))?;
    let index_probes = case
        .get("index_probes")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("CommaSeparatedStrings index_probes must be an array"))?;
    let mut instances = Vec::with_capacity(inputs.len());
    for (input_number, input) in inputs.iter().enumerate() {
        let input = input.as_object().ok_or_else(|| {
            format!("CommaSeparatedStrings inputs[{input_number}] must be an object")
        })?;
        let kind = input.get("kind").and_then(Value::as_str).ok_or_else(|| {
            format!("CommaSeparatedStrings inputs[{input_number}].kind must be a string")
        })?;
        if kind == "sequence-subclass" {
            return Err(String::from(
                "Python string-subclass inputs apply only to the Python-package target",
            ));
        }
        let mut item_reprs = None;
        let value = match kind {
            "string" | "shlex-edge-string" | "unicode-repr-string" | "malformed-string" => {
                let input_value = Value::Object(input.clone());
                let input = exact_object(
                    &input_value,
                    &["kind", "value"],
                    "CommaSeparatedStrings string input",
                )?;
                CommaSeparatedStrings::parse(string_field(
                    input,
                    "value",
                    "CommaSeparatedStrings string input",
                )?)
            }
            "sequence" => {
                let input_value = Value::Object(input.clone());
                let input = exact_object(
                    &input_value,
                    &["kind", "items"],
                    "CommaSeparatedStrings sequence input",
                )?;
                let items = input
                    .get("items")
                    .and_then(Value::as_array)
                    .ok_or_else(|| String::from("CommaSeparatedStrings items must be an array"))?
                    .iter()
                    .enumerate()
                    .map(|(item_number, item)| {
                        item.as_str().map(str::to_owned).ok_or_else(|| {
                            format!("CommaSeparatedStrings items[{item_number}] must be a string")
                        })
                    })
                    .collect::<Result<Vec<_>, _>>()?;
                Ok(CommaSeparatedStrings::from_items(items))
            }
            "sequence-item-reprs" => {
                let input_value = Value::Object(input.clone());
                let input = exact_object(
                    &input_value,
                    &["kind", "items", "item_reprs"],
                    "CommaSeparatedStrings item-repr sequence input",
                )?;
                let items = string_array_field(
                    input,
                    "items",
                    "CommaSeparatedStrings item-repr sequence input",
                )?;
                item_reprs = Some(string_array_field(
                    input,
                    "item_reprs",
                    "CommaSeparatedStrings item-repr sequence input",
                )?);
                Ok(CommaSeparatedStrings::from_items(items))
            }
            _ => {
                return Err(String::from(
                    "CommaSeparatedStrings input kind is unsupported",
                ));
            }
        };
        match value {
            Err(error) => instances.push(json!({
                "kind": kind,
                "error": {"message": error.to_string()},
            })),
            Ok(value) => {
                let mut indexed = Vec::with_capacity(index_probes.len());
                for (probe_number, raw_index) in index_probes.iter().enumerate() {
                    let index = raw_index
                        .as_i64()
                        .and_then(|index| isize::try_from(index).ok())
                        .ok_or_else(|| {
                            format!(
                                "CommaSeparatedStrings index_probes[{probe_number}] must fit a signed platform index"
                            )
                        })?;
                    let item = value.get(index).ok_or_else(|| {
                        format!("CommaSeparatedStrings index probe {index} is out of range")
                    })?;
                    indexed.push(json!({"index": index, "value": item}));
                }
                let (string_value, repr_value) = match item_reprs.as_deref() {
                    Some(item_reprs) => (
                        value.as_string_with_item_reprs(item_reprs),
                        value.repr_with_item_reprs("CommaSeparatedStrings", item_reprs),
                    ),
                    None => (value.as_string(), value.repr("CommaSeparatedStrings")),
                };
                instances.push(json!({
                    "kind": kind,
                    "items": value.items(),
                    "length": value.len(),
                    "indexed": indexed,
                    "str": string_value,
                    "repr": repr_value,
                }));
            }
        }
    }

    Ok(json!({
        "case_id": case["case_id"],
        "status": "completed",
        "observations": [{
            "step_id": "snapshot",
            "status": "ok",
            "value": {"snapshot": {"instances": instances}},
        }],
    }))
}

fn query_params_from_input(source: &Value) -> Result<QueryParams, String> {
    let object = source
        .as_object()
        .ok_or_else(|| String::from("QueryParams source must be an object"))?;
    match object.get("kind").and_then(Value::as_str) {
        Some("string") => {
            let object = exact_object(source, &["kind", "value"], "QueryParams string source")?;
            Ok(QueryParams::parse_str(string_field(
                object,
                "value",
                "QueryParams string source",
            )?))
        }
        Some("bytes") => {
            let object = exact_object(
                source,
                &["kind", "value_base64"],
                "QueryParams bytes source",
            )?;
            let bytes = decode_base64(
                string_field(object, "value_base64", "QueryParams bytes source")?,
                "QueryParams bytes source.value_base64",
            )?;
            Ok(QueryParams::parse(&bytes))
        }
        Some("empty") => {
            let _ = exact_object(source, &["kind"], "QueryParams empty source")?;
            Ok(QueryParams::default())
        }
        Some(kind @ ("pairs" | "mapping" | "copy")) => {
            let expected = if kind == "pairs" {
                &["kind", "items", "kwargs"][..]
            } else {
                &["kind", "items"][..]
            };
            let object = exact_object(source, expected, "QueryParams pair source")?;
            let mut items = query_params_pairs(
                object
                    .get("items")
                    .ok_or_else(|| String::from("QueryParams source has no items"))?,
                "QueryParams source.items",
            )?;
            if kind == "pairs" {
                let kwargs = query_params_pairs(
                    object
                        .get("kwargs")
                        .ok_or_else(|| String::from("QueryParams source has no kwargs"))?,
                    "QueryParams source.kwargs",
                )?;
                items.extend(kwargs);
            }
            Ok(QueryParams::from_pairs(items))
        }
        _ => Err(String::from("QueryParams source kind is unsupported")),
    }
}

fn query_params_pairs(value: &Value, context: &str) -> Result<Vec<(String, String)>, String> {
    value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}[{index}] must be a two-item array"))?;
            Ok((
                query_params_value_string(&pair[0], &format!("{context}[{index}][0]"))?,
                query_params_value_string(&pair[1], &format!("{context}[{index}][1]"))?,
            ))
        })
        .collect()
}

fn query_params_value_string(value: &Value, context: &str) -> Result<String, String> {
    match value {
        Value::Null => Ok(String::from("None")),
        Value::Bool(value) => Ok(if *value { "True" } else { "False" }.to_owned()),
        Value::Number(value) => Ok(value.to_string()),
        Value::String(value) => Ok(value.clone()),
        _ => Err(format!("{context} must be a JSON scalar")),
    }
}

fn run_router_case(case: &Value) -> Result<Value, String> {
    let is_sequence = case.get("steps").is_some();
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "custom_convertors",
        "routes",
        "redirect_slashes",
        "observations",
    ];
    if is_sequence {
        expected_fields.push("steps");
    } else {
        expected_fields.extend(["scope", "incoming", "send"]);
    }
    if case.get("observe_router_scope").is_some() {
        expected_fields.push("observe_router_scope");
    }
    let case = exact_object(case, &expected_fields, "Router route-dispatch case")?;
    let observe_router_scope = match case.get("observe_router_scope") {
        None => false,
        Some(Value::Bool(true)) => true,
        Some(_) => {
            return Err(String::from(
                "Router observe_router_scope must be true when supplied",
            ));
        }
    };
    let case_id = string_field(case, "case_id", "Router route-dispatch case")?;
    let observations_match = if is_sequence {
        let step_ids = case
            .get("steps")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("Router steps must be an array"))?
            .iter()
            .map(|step| {
                let step = step
                    .as_object()
                    .ok_or_else(|| String::from("Router step must be an object"))?;
                string_field(step, "step_id", "Router step")
            })
            .collect::<Result<Vec<_>, _>>()?;
        case.get("observations") == Some(&json!(step_ids))
    } else {
        case.get("observations") == Some(&json!(["route-dispatch"]))
    };
    if string_field(case, "surface", "Router route-dispatch case")? != "starlette.routing.Router"
        || string_field(case, "operation", "Router route-dispatch case")? != "route-dispatch"
        || !observations_match
        || case.get("assets") != Some(&json!([]))
        || case.get("custom_convertors") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Router route-dispatch accepts only the built-in converter projection",
        ));
    }
    let routes = case
        .get("routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| String::from("Router routes must be a non-empty array"))?;
    let redirect_slashes = case
        .get("redirect_slashes")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("Router redirect_slashes must be a boolean"))?;
    if !is_sequence
        && (case.get("incoming") != Some(&json!([]))
            || case.get("send") != Some(&json!({"kind": "capture-asgi-send"})))
    {
        return Err(String::from(
            "Router dispatch requires an empty receive sequence and captured ASGI send",
        ));
    }
    if routes
        .iter()
        .any(|route| route.get("kind").and_then(Value::as_str) == Some("host-route"))
    {
        if routes.len() != 1 {
            return Err(String::from(
                "Rust-native Router Host dispatch supports one Host route",
            ));
        }
        return run_router_host_case(case, &routes[0], case_id);
    }
    let mut route_table = RouteTable::new();
    let mut endpoints = Vec::with_capacity(routes.len());
    for route in routes {
        endpoints.push(add_native_router_route(&mut route_table, route)?);
    }
    if is_sequence {
        return run_router_sequence_case(case, &mut route_table, &mut endpoints, case_id);
    }
    let observation = router_dispatch_observation(
        &route_table,
        &endpoints,
        case.get("scope")
            .ok_or_else(|| String::from("Router scope is missing"))?,
        redirect_slashes,
        observe_router_scope,
    )?;
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "route-dispatch",
            "status": "ok",
            "value": observation,
        }],
    }))
}

fn add_native_router_route(route_table: &mut RouteTable, route: &Value) -> Result<Value, String> {
    let route = exact_object(
        route,
        &["kind", "path", "methods", "endpoint"],
        "Router route input",
    )?;
    if string_field(route, "kind", "Router route input")? != "http-route" {
        return Err(String::from("Router route kind must be http-route"));
    }
    let path = string_field(route, "path", "Router route input")?;
    let methods = route
        .get("methods")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Router route methods must be an array"))?;
    let method_values = methods
        .iter()
        .map(|method| {
            method
                .as_str()
                .ok_or_else(|| String::from("Router route methods must contain strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    route_table
        .add_route(path, method_values)
        .map_err(|error| error.to_string())?;
    let endpoint = exact_object(
        route
            .get("endpoint")
            .ok_or_else(|| String::from("Router route endpoint is missing"))?,
        &["kind", "content", "status_code", "media_type", "cookies"],
        "Router plain-text endpoint input",
    )?;
    if string_field(endpoint, "kind", "Router endpoint")? != "plain-text-response"
        || string_field(endpoint, "media_type", "Router endpoint")? != "text/plain"
        || endpoint.get("cookies") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Router projection requires a fixed plain-text endpoint",
        ));
    }
    Ok(Value::Object(endpoint.clone()))
}

fn run_router_sequence_case(
    case: &Map<String, Value>,
    route_table: &mut RouteTable,
    endpoints: &mut Vec<Value>,
    case_id: &str,
) -> Result<Value, String> {
    let steps = case
        .get("steps")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Router steps must be an array"))?;
    let mut observations = Vec::with_capacity(steps.len());
    for step in steps {
        let step = exact_object(
            step,
            &["step_id", "scope", "incoming", "send", "mutations"],
            "Router mutation step",
        )?;
        let step_id = string_field(step, "step_id", "Router mutation step")?;
        if step.get("incoming") != Some(&json!([]))
            || step.get("send") != Some(&json!({"kind": "capture-asgi-send"}))
        {
            return Err(String::from(
                "Router mutation dispatch requires an empty receive sequence and captured ASGI send",
            ));
        }
        let mutations = step
            .get("mutations")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("Router mutations must be an array"))?;
        for mutation in mutations {
            let mutation = mutation
                .as_object()
                .ok_or_else(|| String::from("Router mutation must be an object"))?;
            match mutation.get("operation").and_then(Value::as_str) {
                Some("route-method-add") => {
                    let mutation_value = Value::Object(mutation.clone());
                    let mutation = exact_object(
                        &mutation_value,
                        &["operation", "route_index", "method"],
                        "Router route method mutation",
                    )?;
                    let route_index = mutation
                        .get("route_index")
                        .and_then(Value::as_u64)
                        .and_then(|index| usize::try_from(index).ok())
                        .ok_or_else(|| String::from("Router route_index must fit usize"))?;
                    let method = string_field(mutation, "method", "Router method mutation")?;
                    route_table
                        .add_method(route_index, method)
                        .map_err(|error| error.to_string())?;
                }
                Some("route-list-append") => {
                    let mutation_value = Value::Object(mutation.clone());
                    let mutation = exact_object(
                        &mutation_value,
                        &["operation", "route"],
                        "Router route-list append mutation",
                    )?;
                    let route = mutation
                        .get("route")
                        .ok_or_else(|| String::from("Router appended route is missing"))?;
                    endpoints.push(add_native_router_route(route_table, route)?);
                }
                _ => {
                    return Err(String::from(
                        "Rust-native Router sequence supports route method addition and route append",
                    ));
                }
            }
        }
        let observation = router_dispatch_observation(
            route_table,
            endpoints,
            step.get("scope")
                .ok_or_else(|| String::from("Router step scope is missing"))?,
            case.get("redirect_slashes")
                .and_then(Value::as_bool)
                .ok_or_else(|| String::from("Router redirect_slashes must be a boolean"))?,
            false,
        )?;
        observations.push(json!({
            "step_id": step_id,
            "status": "ok",
            "value": observation,
        }));
    }
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": observations,
    }))
}

fn router_dispatch_observation(
    route_table: &RouteTable,
    endpoints: &[Value],
    scope_value: &Value,
    redirect_slashes: bool,
    observe_router_scope: bool,
) -> Result<Value, String> {
    let scope = exact_object(
        scope_value,
        &[
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        ],
        "Router HTTP scope",
    )?;
    if string_field(scope, "type", "Router scope")? != "http"
        || string_field(scope, "http_version", "Router scope")? != "1.1"
        || string_field(scope, "scheme", "Router scope")? != "http"
    {
        return Err(String::from(
            "Router scope differs from the declared HTTP baseline",
        ));
    }
    let path = string_field(scope, "path", "Router scope")?;
    let root_path = string_field(scope, "root_path", "Router scope")?;
    let method = string_field(scope, "method", "Router scope")?;
    let query_string = decode_base64(
        string_field(scope, "query_string_base64", "Router scope")?,
        "Router scope.query_string_base64",
    )?;
    let route_match = route_table.matches_detailed_with_root_path(path, root_path, method);
    let route_path_params = if observe_router_scope {
        let captures = match &route_match {
            DetailedRouteMatch::Matched {
                route_index,
                path_params,
            }
            | DetailedRouteMatch::MethodNotAllowed {
                route_index,
                path_params,
                ..
            } => route_table
                .capture_path_parameters(*route_index, path_params)
                .map_err(|error| error.to_string())?,
            DetailedRouteMatch::NotFound => Vec::new(),
        };
        let mut observations = Map::new();
        for parameter in &captures {
            observations.insert(
                parameter.name.clone(),
                path_parameter_observation(parameter)?,
            );
        }
        Some(observations)
    } else {
        None
    };
    let route_index = match &route_match {
        DetailedRouteMatch::Matched { route_index, .. } => Some(*route_index),
        DetailedRouteMatch::MethodNotAllowed { .. } | DetailedRouteMatch::NotFound => None,
    };
    let redirect_path = if redirect_slashes && matches!(&route_match, DetailedRouteMatch::NotFound)
    {
        route_table.find_slash_redirect_path(path, root_path, method)
    } else {
        None
    };
    let response = match (&route_match, redirect_path) {
        (DetailedRouteMatch::Matched { route_index, .. }, _) => {
            let endpoint = endpoints
                .get(*route_index)
                .and_then(Value::as_object)
                .ok_or_else(|| String::from("selected route endpoint must be an object"))?;
            let content = string_field(endpoint, "content", "selected Router endpoint")?;
            let status = endpoint
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .ok_or_else(|| String::from("selected endpoint status_code must fit u16"))?;
            Response::plain_text_with_status(status, content)
        }
        (DetailedRouteMatch::MethodNotAllowed { .. }, _) => route_match
            .fallback_response()
            .map_err(|error| error.to_string())?
            .ok_or_else(|| String::from("Router fallback did not provide a response"))?,
        (DetailedRouteMatch::NotFound, Some(redirect_path)) => {
            let location = scope_url(scope, &redirect_path, &query_string)?;
            Response::redirect(&location, 307, &[]).map_err(|error| error.to_string())?
        }
        (DetailedRouteMatch::NotFound, None) => route_match
            .fallback_response()
            .map_err(|error| error.to_string())?
            .ok_or_else(|| String::from("Router fallback did not provide a response"))?,
    };
    let body = response.body();
    let body_base64 = encode_base64(body);
    let headers = canonical_headers(response.headers());
    let events = json!([
        {
            "type": "http.response.start",
            "status": response.status_code(),
            "headers": headers,
        },
        {
            "type": "http.response.body",
            "body": {"encoding": "base64", "data": body_base64},
        }
    ]);
    let event_order = json!(["http.response.start", "http.response.body"]);
    let mut observation = json!({
        "route_index": route_index,
        "response_status": response.status_code(),
        "ordered_repeated_headers": headers,
        "response_bytes": {"encoding": "base64", "data": body_base64},
        "asgi_event_order": event_order,
        "asgi_events": events,
    });
    if let Some(path_params) = route_path_params {
        observation["route_scope.path"] = json!(path);
        observation["route_scope.root_path"] = json!(root_path);
        observation["route_scope.app_root_path"] = Value::Null;
        observation["route_scope.path_params"] = Value::Object(path_params);
    }
    Ok(observation)
}

fn run_router_host_case(
    case: &Map<String, Value>,
    route: &Value,
    case_id: &str,
) -> Result<Value, String> {
    let route = exact_object(
        route,
        &["kind", "host", "name", "app"],
        "Router Host route input",
    )?;
    if string_field(route, "kind", "Router Host route input")? != "host-route" {
        return Err(String::from("Router Host route kind must be host-route"));
    }
    let host_pattern = HostPattern::new(string_field(route, "host", "Router Host route input")?)
        .map_err(|error| error.to_string())?;
    let _name = optional_string_field(route, "name", "Router Host route input")?;
    let app = exact_object(
        route
            .get("app")
            .ok_or_else(|| String::from("Router Host route app is missing"))?,
        &["kind", "content", "status_code", "media_type", "cookies"],
        "Router Host app response",
    )?;
    if string_field(app, "kind", "Router Host app response")? != "plain-text-response"
        || string_field(app, "media_type", "Router Host app response")? != "text/plain"
        || app.get("cookies") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Host dispatch requires a plain-text response without cookies",
        ));
    }
    let content = string_field(app, "content", "Router Host app response")?;
    let status_code = app
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|status| u16::try_from(status).ok())
        .ok_or_else(|| String::from("Router Host response status_code must fit u16"))?;
    let observe_router_scope = match case.get("observe_router_scope") {
        None => false,
        Some(Value::Bool(true)) => true,
        Some(_) => {
            return Err(String::from(
                "Router observe_router_scope must be true when supplied",
            ));
        }
    };
    let scope = validate_asgi_http_scope(
        case.get("scope")
            .ok_or_else(|| String::from("Router scope is missing"))?,
        "Router",
    )?;
    if string_field(scope, "http_version", "Router scope")? != "1.1"
        || string_field(scope, "scheme", "Router scope")? != "http"
    {
        return Err(String::from(
            "Router scope differs from the declared HTTP baseline",
        ));
    }
    let scope_path = string_field(scope, "path", "Router scope")?;
    let scope_root_path = string_field(scope, "root_path", "Router scope")?;
    let encoded_headers = scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Router scope.headers_base64_pairs must be an array"))?;
    let headers = encoded_headers
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("Router scope header[{index}] must be a pair"))?;
            let name = decode_base64(
                pair[0]
                    .as_str()
                    .ok_or_else(|| format!("Router scope header[{index}] name must be base64"))?,
                "Router scope header name",
            )?;
            let value = decode_base64(
                pair[1]
                    .as_str()
                    .ok_or_else(|| format!("Router scope header[{index}] value must be base64"))?,
                "Router scope header value",
            )?;
            Ok((name, value))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let host_header = RequestHeaders::new(headers)
        .get(b"host")
        .map(decode_latin1)
        .unwrap_or_default();
    let matched_captures = host_pattern.match_host(&host_header);
    let host_matched = matched_captures.is_some();
    let path_params = matched_captures
        .unwrap_or_default()
        .into_iter()
        .map(|(name, value)| (name, json!({"value": value, "type": "str"})))
        .collect::<Map<_, _>>();
    let response = if host_matched {
        Response::plain_text_with_status(status_code, content)
    } else {
        Response::plain_text_with_status(404, "Not Found")
    };
    let events = response
        .asgi_events()
        .into_iter()
        .map(canonical_response_event)
        .collect::<Vec<_>>();
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let mut observation = json!({
        "route_index": if host_matched { json!(0) } else { Value::Null },
        "response_status": response.status_code(),
        "ordered_repeated_headers": canonical_headers(response.headers()),
        "response_bytes": {"encoding": "base64", "data": encode_base64(response.body())},
        "asgi_event_order": event_order,
        "asgi_events": events,
    });
    if observe_router_scope {
        observation["route_scope.path"] = json!(scope_path);
        observation["route_scope.root_path"] = json!(scope_root_path);
        observation["route_scope.app_root_path"] = Value::Null;
        observation["route_scope.path_params"] = Value::Object(path_params);
    }
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "route-dispatch",
            "status": "ok",
            "value": observation,
        }],
    }))
}

fn run_host_reverse_url_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "route_graph",
            "lookup",
            "request_scope",
            "custom_convertors",
        ],
        "Host URLPath case",
    )?;
    let case_id = string_field(case, "case_id", "Host URLPath case")?;
    if string_field(case, "surface", "Host URLPath case")? != HOST_SURFACE
        || string_field(case, "operation", "Host URLPath case")? != HOST_URL_PATH_OPERATION
        || case.get("observations") != Some(&json!(["reverse-url"]))
        || case.get("assets") != Some(&json!([]))
        || case.get("request_scope") != Some(&Value::Null)
        || case.get("custom_convertors") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Host URLPath requires the declared direct reverse-lookup input",
        ));
    }

    let route = exact_object(
        case.get("route_graph")
            .ok_or_else(|| String::from("Host URLPath route graph is missing"))?,
        &["kind", "host", "name", "routes"],
        "Host URLPath route graph",
    )?;
    if string_field(route, "kind", "Host URLPath route graph")? != "host-route"
        || route
            .get("routes")
            .and_then(Value::as_array)
            .is_none_or(|routes| !routes.is_empty())
    {
        return Err(String::from(
            "Rust-native Host URLPath supports a named Host route without child routes",
        ));
    }
    let route_name = string_field(route, "name", "Host URLPath route graph")?;
    let lookup = exact_object(
        case.get("lookup")
            .ok_or_else(|| String::from("Host URLPath lookup is missing"))?,
        &["name", "path_params"],
        "Host URLPath lookup",
    )?;
    if string_field(lookup, "name", "Host URLPath lookup")? != route_name {
        return Err(String::from(
            "Rust-native Host URLPath requires the lookup name to match the Host name",
        ));
    }
    let path_params = lookup
        .get("path_params")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("Host URLPath lookup.path_params must be an object"))?;
    let path = path_params
        .get("path")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("Host URLPath direct lookup requires a string path"))?;
    let host_params = path_params
        .iter()
        .filter(|(name, _)| name.as_str() != "path")
        .map(|(name, value)| {
            value
                .as_str()
                .map(|value| (name.clone(), value.to_owned()))
                .ok_or_else(|| {
                    format!("Rust-native Host URLPath requires string host parameter {name:?}")
                })
        })
        .collect::<Result<Vec<_>, String>>()?;
    let host_pattern = HostPattern::new(string_field(route, "host", "Host URLPath route graph")?)
        .map_err(|error| error.to_string())?;
    let url_path = host_pattern
        .format_url_path(path, &host_params)
        .map_err(|error| error.to_string())?;

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "reverse-url",
            "status": "ok",
            "value": {
                "reverse-url": {
                    "path": url_path.path,
                    "protocol": url_path.protocol,
                    "host": url_path.host,
                },
            },
        }],
    }))
}

fn run_route_reverse_url_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "route_graph",
            "lookup",
            "request_scope",
            "custom_convertors",
        ],
        "Route URLPath case",
    )?;
    let case_id = string_field(case, "case_id", "Route URLPath case")?;
    if string_field(case, "surface", "Route URLPath case")? != "starlette.routing.Route"
        || string_field(case, "operation", "Route URLPath case")? != ROUTER_URL_PATH_OPERATION
        || case.get("observations") != Some(&json!(["reverse-url"]))
        || case.get("assets") != Some(&json!([]))
        || case.get("request_scope") != Some(&Value::Null)
        || case.get("custom_convertors") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Route URLPath requires the declared one-route reverse-lookup input",
        ));
    }

    let route_spec = exact_object(
        case.get("route_graph")
            .ok_or_else(|| String::from("Route URLPath route is missing"))?,
        &["kind", "path", "name", "methods", "observer"],
        "Route URLPath input",
    )?;
    if string_field(route_spec, "kind", "Route URLPath input")? != "http-route"
        || route_spec.get("observer") != Some(&Value::Null)
    {
        return Err(String::from(
            "Rust-native Route URLPath supports an HTTP path pattern without an endpoint observer",
        ));
    }
    let path = string_field(route_spec, "path", "Route URLPath input")?;
    let route_name = string_field(route_spec, "name", "Route URLPath input")?;
    let route = NativeNamedRoute::new(path, route_name).map_err(|error| error.to_string())?;

    let lookup = exact_object(
        case.get("lookup")
            .ok_or_else(|| String::from("Route URLPath lookup is missing"))?,
        &["name", "path_params"],
        "Route URLPath lookup",
    )?;
    let name = string_field(lookup, "name", "Route URLPath lookup")?;
    let path_params = lookup
        .get("path_params")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("Route URLPath lookup.path_params must be an object"))?
        .iter()
        .map(|(key, value)| {
            let value = match value {
                Value::String(value) => PathParameterValue::String(value.clone()),
                Value::Bool(value) => PathParameterValue::Boolean(*value),
                Value::Number(value) if value.is_f64() => PathParameterValue::Float(
                    value.as_f64().ok_or_else(|| {
                        format!("Rust-native Route URLPath parameter {key:?} is not a finite JSON number")
                    })?,
                ),
                Value::Number(value) => PathParameterValue::Integer(value.to_string()),
                _ => {
                    return Err(format!(
                        "Rust-native Route URLPath requires scalar text or numeric parameter {key:?}"
                    ));
                }
            };
            Ok((key.clone(), value))
        })
        .collect::<Result<Vec<_>, String>>()?;

    let observed = match route.url_path_for_values(name, &path_params) {
        Ok(url_path) => json!({
            "path": url_path.path,
            "protocol": url_path.protocol,
            "host": url_path.host,
        }),
        Err(error @ NamedRouteError::NoMatchFound { .. }) => json!({
            "error": {
                "class": "NoMatchFound",
                "message": error.to_string(),
            },
        }),
        Err(NamedRouteError::RouteFormatting(error)) => route_formatting_observation(&error),
    };

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "reverse-url",
            "status": "ok",
            "value": {"reverse-url": observed},
        }],
    }))
}

fn route_formatting_observation(error: &RouteError) -> Value {
    match error {
        RouteError::ConverterAssertion { message, .. } => json!({
            "error": {
                "class": "AssertionError",
                "message": message,
            },
        }),
        RouteError::InvalidPathParameter {
            converter: PathConverter::Integer,
            value,
            ..
        } => json!({
            "error": {
                "class": "ValueError",
                "message": format!(
                    "invalid literal for int() with base 10: {}",
                    python_string_repr(value),
                ),
            },
        }),
        RouteError::InvalidPathParameter {
            converter: PathConverter::Float,
            value,
            ..
        } => json!({
            "error": {
                "class": "ValueError",
                "message": format!(
                    "could not convert string to float: {}",
                    python_string_repr(value),
                ),
            },
        }),
        _ => json!({
            "error": {
                "class": "RouteFormattingError",
                "message": error.to_string(),
            },
        }),
    }
}

fn append_native_named_route(
    router: &mut NamedRouter,
    node: &Value,
    context: &str,
) -> Result<(), String> {
    let kind = node
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{context}.kind must be a string"))?;
    match kind {
        "router" => {
            let object = exact_object(node, &["kind", "routes"], context)?;
            let routes = object
                .get("routes")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("{context}.routes must be an array"))?;
            for (index, route) in routes.iter().enumerate() {
                append_native_named_route(router, route, &format!("{context}.routes[{index}]"))?;
            }
        }
        "http-route" => {
            let route = exact_object(
                node,
                &["kind", "path", "name", "methods", "observer"],
                context,
            )?;
            if route.get("observer") != Some(&Value::Null) {
                return Err(format!("{context}.observer must be null"));
            }
            let path = string_field(route, "path", context)?;
            let name = string_field(route, "name", context)?;
            let route = NativeNamedRoute::new(path, name).map_err(|error| error.to_string())?;
            router.add_entry(route);
        }
        "websocket-route" => {
            let route = exact_object(node, &["kind", "path", "name", "observer"], context)?;
            if route.get("observer") != Some(&Value::Null) {
                return Err(format!("{context}.observer must be null"));
            }
            let path = string_field(route, "path", context)?;
            let name = string_field(route, "name", context)?;
            let route =
                NativeNamedRoute::new_websocket(path, name).map_err(|error| error.to_string())?;
            router.add_entry(route);
        }
        "mount" => {
            let mount = exact_object(node, &["kind", "path", "name", "routes"], context)?;
            let path = string_field(mount, "path", context)?;
            let name = optional_string_field(mount, "name", context)?;
            let children = mount
                .get("routes")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("{context}.routes must be an array"))?;
            let child_router = native_named_router_from_routes(children, context)?;
            let mount =
                NamedMount::new(path, name, child_router).map_err(|error| error.to_string())?;
            router.add_mount(mount);
        }
        "host-route" => {
            let host = exact_object(node, &["kind", "host", "name", "routes"], context)?;
            let pattern = string_field(host, "host", context)?;
            let name = optional_string_field(host, "name", context)?;
            let children = host
                .get("routes")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("{context}.routes must be an array"))?;
            let child_router = native_named_router_from_routes(children, context)?;
            let host =
                NamedHost::new(pattern, name, child_router).map_err(|error| error.to_string())?;
            router.add_host(host);
        }
        _ => return Err(format!("{context}.kind is unsupported by NamedRouter")),
    }
    Ok(())
}

fn native_named_router_from_routes(routes: &[Value], context: &str) -> Result<NamedRouter, String> {
    let mut router = NamedRouter::new();
    for (index, route) in routes.iter().enumerate() {
        append_native_named_route(&mut router, route, &format!("{context}.routes[{index}]"))?;
    }
    Ok(router)
}

fn native_named_router_from_graph(graph: &Value) -> Result<NamedRouter, String> {
    let route_graph = exact_object(graph, &["kind", "routes"], "Router URLPath route graph")?;
    if string_field(route_graph, "kind", "Router URLPath route graph")? != "router" {
        return Err(String::from(
            "Rust-native Router URLPath requires a Router route graph",
        ));
    }
    let routes = route_graph
        .get("routes")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Router URLPath route graph.routes must be an array"))?;
    native_named_router_from_routes(routes, "Router URLPath route graph")
}

fn run_router_reverse_url_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "observations",
            "route_graph",
            "lookup",
            "request_scope",
            "custom_convertors",
        ],
        "Router URLPath case",
    )?;
    let case_id = string_field(case, "case_id", "Router URLPath case")?;
    if string_field(case, "surface", "Router URLPath case")? != "starlette.routing.Router"
        || string_field(case, "operation", "Router URLPath case")? != ROUTER_URL_PATH_OPERATION
        || case.get("observations") != Some(&json!(["reverse-url"]))
        || case.get("assets") != Some(&json!([]))
        || case.get("request_scope") != Some(&Value::Null)
        || case.get("custom_convertors") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Router URLPath requires a built-in reverse-lookup input",
        ));
    }

    let named_router = native_named_router_from_graph(
        case.get("route_graph")
            .ok_or_else(|| String::from("Router URLPath route graph is missing"))?,
    )?;

    let lookup = exact_object(
        case.get("lookup")
            .ok_or_else(|| String::from("Router URLPath lookup is missing"))?,
        &["name", "path_params"],
        "Router URLPath lookup",
    )?;
    let name = string_field(lookup, "name", "Router URLPath lookup")?;
    let path_params = lookup
        .get("path_params")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("Router URLPath lookup.path_params must be an object"))?
        .iter()
        .map(|(key, value)| {
            let value = match value {
                Value::String(value) => value.clone(),
                Value::Number(value) => value.to_string(),
                _ => {
                    return Err(format!(
                        "Rust-native Router URLPath requires scalar text or numeric parameter {key:?}"
                    ));
                }
            };
            Ok((key.clone(), value))
        })
        .collect::<Result<Vec<_>, String>>()?;

    let observed = match named_router.url_path_for(name, &path_params) {
        Ok(url_path) => json!({
            "path": url_path.path,
            "protocol": url_path.protocol,
            "host": url_path.host,
        }),
        Err(error @ NamedRouterError::NoMatchFound { .. }) => json!({
            "error": {
                "class": "NoMatchFound",
                "message": error.to_string(),
            },
        }),
        Err(NamedRouterError::RouteFormatting(error)) => route_formatting_observation(&error),
        Err(NamedRouterError::HostFormatting(error)) => json!({
            "error": {
                "class": "HostFormattingError",
                "message": error.to_string(),
            },
        }),
    };

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "reverse-url",
            "status": "ok",
            "value": {"reverse-url": observed},
        }],
    }))
}

fn run_mount_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "mount",
            "scope",
            "incoming",
            "send",
            "observations",
        ],
        "Mount route-dispatch case",
    )?;
    let case_id = string_field(case, "case_id", "Mount route-dispatch case")?;
    if string_field(case, "surface", "Mount route-dispatch case")? != "starlette.routing.Mount"
        || string_field(case, "operation", "Mount route-dispatch case")? != "route-dispatch"
        || case.get("observations") != Some(&json!(["route-dispatch"]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "Rust-native Mount route-dispatch requires the declared Mount projection",
        ));
    }

    let mount = mount_from_parity_input(
        case.get("mount")
            .ok_or_else(|| String::from("Mount input is missing"))?,
        "Mount input",
    )?;

    if case.get("incoming") != Some(&json!([]))
        || case.get("send") != Some(&json!({"kind": "capture-asgi-send"}))
    {
        return Err(String::from(
            "Mount dispatch requires an empty receive sequence and captured ASGI send",
        ));
    }
    let scope_input = case
        .get("scope")
        .ok_or_else(|| String::from("Mount scope is missing"))?;
    let mut scope_fields = vec![
        "type",
        "asgi",
        "http_version",
        "method",
        "scheme",
        "path",
        "raw_path_base64",
        "query_string_base64",
        "root_path",
        "headers_base64_pairs",
        "client",
        "server",
    ];
    for optional_field in ["app_root_path", "path_params"] {
        if scope_input.get(optional_field).is_some() {
            scope_fields.push(optional_field);
        }
    }
    let scope = exact_object(scope_input, &scope_fields, "Mount HTTP scope")?;
    if string_field(scope, "type", "Mount scope")? != "http"
        || string_field(scope, "http_version", "Mount scope")? != "1.1"
        || string_field(scope, "scheme", "Mount scope")? != "http"
    {
        return Err(String::from(
            "Mount scope differs from the declared HTTP baseline",
        ));
    }
    let path = string_field(scope, "path", "Mount scope")?;
    let root_path = string_field(scope, "root_path", "Mount scope")?;
    let method = string_field(scope, "method", "Mount scope")?;
    let path_params = mount_inherited_path_params(scope.get("path_params"))?;
    let mut mount_scope = MountScope::new(path, method, root_path).with_path_params(&path_params);
    if let Some(app_root_path) = scope.get("app_root_path") {
        mount_scope = mount_scope.with_app_root_path(
            app_root_path
                .as_str()
                .ok_or_else(|| String::from("Mount scope app_root_path must be a string"))?,
        );
    }
    let result = mount
        .dispatch_tree(&mount_scope)
        .map_err(|error| error.to_string())?;
    let mount_scope = result
        .final_scope_extension()
        .map(mount_scope_observation)
        .transpose()?;

    let response = result.dispatch.response;
    let body = encode_base64(response.body());
    let headers = canonical_headers(response.headers());
    let events = json!([
        {
            "type": "http.response.start",
            "status": response.status_code(),
            "headers": headers,
        },
        {
            "type": "http.response.body",
            "body": {"encoding": "base64", "data": body},
        }
    ]);
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "route-dispatch",
            "status": "ok",
            "value": {
                "mount_scope": mount_scope,
                "response_status": response.status_code(),
                "ordered_repeated_headers": headers,
                "response_bytes": {"encoding": "base64", "data": body},
                "asgi_event_order": ["http.response.start", "http.response.body"],
                "asgi_events": events,
            },
        }],
    }))
}

fn mount_from_parity_input(input: &Value, context: &str) -> Result<NativeMount, String> {
    let mount = exact_object(input, &["path", "routes"], context)?;
    mount_from_parity_fields(mount, context)
}

fn mount_from_parity_fields(
    mount: &Map<String, Value>,
    context: &str,
) -> Result<NativeMount, String> {
    let path = string_field(mount, "path", context)?;
    let routes = mount
        .get("routes")
        .and_then(Value::as_array)
        .filter(|routes| !routes.is_empty())
        .ok_or_else(|| format!("{context}.routes must be a non-empty array"))?;
    let children = routes
        .iter()
        .map(|route| mount_child_from_parity_input(route, context))
        .collect::<Result<Vec<_>, _>>()?;
    NativeMount::with_children(path, children).map_err(|error| error.to_string())
}

fn mount_child_from_parity_input(input: &Value, context: &str) -> Result<MountChild, String> {
    let kind = input
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{context} child must declare a string kind"))?;
    if kind == "mount" {
        let mount = exact_object(input, &["kind", "path", "routes"], "Nested Mount input")?;
        return mount_from_parity_fields(mount, "Nested Mount input").map(MountChild::Mount);
    }
    let route = exact_object(
        input,
        &["kind", "path", "methods", "endpoint"],
        "Mount child route input",
    )?;
    if kind != "http-route" {
        return Err(String::from(
            "Rust-native Mount child kind must be http-route or mount",
        ));
    }
    let path = string_field(route, "path", "Mount child route input")?;
    let methods = route
        .get("methods")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Mount child route methods must be an array"))?;
    let method_values = methods
        .iter()
        .map(|method| {
            method
                .as_str()
                .ok_or_else(|| String::from("Mount child methods must contain strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let endpoint = exact_object(
        route
            .get("endpoint")
            .ok_or_else(|| String::from("Mount child endpoint is missing"))?,
        &["kind", "content", "status_code", "media_type", "cookies"],
        "Mount child endpoint input",
    )?;
    if string_field(endpoint, "kind", "Mount child endpoint")? != "plain-text-response" {
        return Err(String::from(
            "Rust-native Mount currently accepts prebuilt plain-text responses",
        ));
    }
    let content = string_field(endpoint, "content", "Mount child endpoint")?;
    let media_type = string_field(endpoint, "media_type", "Mount child endpoint")?;
    let status = endpoint
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|status| u16::try_from(status).ok())
        .ok_or_else(|| String::from("Mount child status_code must fit u16"))?;
    let cookies = endpoint
        .get("cookies")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Mount child cookies must be an array"))?;
    let mut response = Response::from_content(
        status,
        content.as_bytes().to_vec(),
        Some(media_type),
        std::iter::empty::<(&str, &str)>(),
    )
    .map_err(|error| error.to_string())?;
    for cookie in cookies {
        let cookie = exact_object(cookie, &["key", "value"], "Mount response cookie")?;
        response
            .set_cookie(
                string_field(cookie, "key", "Mount response cookie")?,
                string_field(cookie, "value", "Mount response cookie")?,
            )
            .map_err(|error| error.to_string())?;
    }
    Ok(MountChild::Route(ApplicationRoute::new(
        path,
        method_values,
        response,
    )))
}

fn mount_inherited_path_params(
    path_params: Option<&Value>,
) -> Result<Vec<PathParameterCapture>, String> {
    let Some(path_params) = path_params else {
        return Ok(Vec::new());
    };
    let path_params = path_params
        .as_object()
        .ok_or_else(|| String::from("Mount scope path_params must be an object"))?;
    path_params
        .iter()
        .map(|(name, value)| {
            let (value, converter) = match value {
                Value::String(value) => (value.clone(), PathConverter::String),
                Value::Number(number) => {
                    let value = number.to_string();
                    let converter = if value.contains(['.', 'e', 'E']) {
                        PathConverter::Float
                    } else {
                        PathConverter::Integer
                    };
                    (value, converter)
                }
                _ => {
                    return Err(String::from(
                        "Mount scope path_params values must be strings or numbers",
                    ));
                }
            };
            Ok(PathParameterCapture {
                name: name.clone(),
                value,
                converter,
            })
        })
        .collect()
}

fn mount_scope_observation(scope: &starlette_rs::MountScopeExtension) -> Result<Value, String> {
    let mut path_params = Map::new();
    for parameter in &scope.path_params {
        path_params.insert(
            parameter.name.clone(),
            path_parameter_observation(parameter)?,
        );
    }
    Ok(json!({
        "root_path": scope.root_path,
        "app_root_path": scope.app_root_path,
        "path_params": path_params,
    }))
}

fn path_parameter_observation(parameter: &PathParameterCapture) -> Result<Value, String> {
    let (value, kind) = match parameter.converter {
        PathConverter::String | PathConverter::Path => {
            (Value::String(parameter.value.clone()), "str")
        }
        PathConverter::Integer => (
            Value::Number(
                Number::from_str(&parameter.value)
                    .map_err(|error| format!("invalid integer path capture: {error}"))?,
            ),
            "int",
        ),
        PathConverter::Float => {
            let value = parameter
                .value
                .parse::<f64>()
                .map_err(|error| format!("invalid float path capture: {error}"))?;
            let number = Number::from_f64(value)
                .ok_or_else(|| String::from("float path capture is not a JSON number"))?;
            (Value::Number(number), "float")
        }
        PathConverter::Uuid => (Value::String(canonical_uuid(&parameter.value)?), "UUID"),
    };
    Ok(json!({"value": value, "type": kind}))
}

fn canonical_uuid(value: &str) -> Result<String, String> {
    let hexadecimal = value
        .chars()
        .filter(|character| *character != '-')
        .collect::<String>()
        .to_ascii_lowercase();
    if hexadecimal.len() != 32 || !hexadecimal.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(String::from("UUID path capture is not a valid UUID"));
    }
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &hexadecimal[0..8],
        &hexadecimal[8..12],
        &hexadecimal[12..16],
        &hexadecimal[16..20],
        &hexadecimal[20..32],
    ))
}

fn run_redirect_response_case(case: &Value) -> Result<Value, String> {
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "url",
        "status_code",
        "header_pairs",
        "scope",
        "incoming",
        "send",
        "observations",
    ];
    if case.get("cookie_actions").is_some() {
        expected_fields.push("cookie_actions");
    }
    let case = exact_object(case, &expected_fields, "RedirectResponse asgi-call case")?;
    let case_id = string_field(case, "case_id", "RedirectResponse asgi-call case")?;
    if !case_id.starts_with(&format!(
        "{REDIRECT_RESPONSE_SURFACE}.{REDIRECT_RESPONSE_OPERATION}."
    )) || string_field(case, "surface", "RedirectResponse asgi-call case")?
        != REDIRECT_RESPONSE_SURFACE
        || string_field(case, "operation", "RedirectResponse asgi-call case")?
            != REDIRECT_RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([REDIRECT_RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "case ID or operation is outside the RedirectResponse ASGI call slice",
        ));
    }
    validate_string_array(case, "covers", "RedirectResponse asgi-call covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "RedirectResponse asgi-call target_profiles",
        false,
    )?;

    if case.get("incoming") != Some(&json!([])) {
        return Err(String::from(
            "RedirectResponse asgi-call requires an empty incoming sequence",
        ));
    }
    validate_capture_send(
        case.get("send")
            .ok_or_else(|| String::from("RedirectResponse asgi-call send input is missing"))?,
    )?;

    let _scope = validate_asgi_http_scope(
        case.get("scope")
            .ok_or_else(|| String::from("RedirectResponse asgi-call scope is missing"))?,
        "RedirectResponse",
    )?;
    let url = string_field(case, "url", "RedirectResponse asgi-call case")?;
    let status_code = case
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| {
            String::from("RedirectResponse status_code must be an unsigned 16-bit integer")
        })?;
    let header_pairs = case
        .get("header_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("RedirectResponse header_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("RedirectResponse header_pairs[{index}] must be a pair"))?;
            let name = pair[0].as_str().ok_or_else(|| {
                format!("RedirectResponse header_pairs[{index}] name must be a string")
            })?;
            let value = pair[1].as_str().ok_or_else(|| {
                format!("RedirectResponse header_pairs[{index}] value must be a string")
            })?;
            Ok((name.to_owned(), value.to_owned()))
        })
        .collect::<Result<Vec<_>, String>>()?;

    let mut response =
        Response::redirect(url, status_code, &header_pairs).map_err(|error| error.to_string())?;
    if let Some(actions) = case.get("cookie_actions") {
        apply_response_cookie_actions(&mut response, actions)?;
    }
    let events = response
        .asgi_events()
        .into_iter()
        .map(canonical_response_event)
        .collect::<Vec<_>>();
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": REDIRECT_RESPONSE_OPERATION,
            "status": "ok",
            "value": {
                "response_status": response.status_code(),
                "ordered_repeated_headers": canonical_headers(response.headers()),
                "response_bytes": {
                    "encoding": "base64",
                    "data": encode_base64(response.body()),
                },
                "asgi_event_order": event_order,
                "asgi_events": events,
            },
        }],
    }))
}

fn validate_asgi_http_scope<'a>(
    scope: &'a Value,
    response_name: &str,
) -> Result<&'a Map<String, Value>, String> {
    let context = format!("{response_name} HTTP scope");
    let scope = exact_object(
        scope,
        &[
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        ],
        &context,
    )?;
    if string_field(scope, "type", &context)? != "http" {
        return Err(format!("{response_name} asgi-call scope.type must be http"));
    }
    let asgi = exact_object(
        scope
            .get("asgi")
            .ok_or_else(|| format!("{response_name} scope misses asgi"))?,
        &["version", "spec_version"],
        &format!("{context}.asgi"),
    )?;
    if string_field(asgi, "version", &format!("{context}.asgi"))? != "3.0"
        || string_field(asgi, "spec_version", &format!("{context}.asgi"))? != "2.4"
    {
        return Err(format!(
            "{response_name} scope uses an unsupported ASGI version"
        ));
    }
    for field in ["http_version", "method", "scheme", "path", "root_path"] {
        let _ = string_field(scope, field, &context)?;
    }
    for field in ["raw_path_base64", "query_string_base64"] {
        decode_base64(
            string_field(scope, field, &context)?,
            &format!("{response_name} scope.{field}"),
        )?;
    }
    let headers = scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{response_name} scope.headers_base64_pairs must be an array"))?;
    for (index, pair) in headers.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| format!("{response_name} scope header[{index}] must be a pair"))?;
        for (side, item) in pair.iter().enumerate() {
            let encoded = item.as_str().ok_or_else(|| {
                format!("{response_name} scope header[{index}][{side}] must be base64")
            })?;
            decode_base64(encoded, &format!("{response_name} scope header"))?;
        }
    }
    validate_scope_address(
        scope
            .get("client")
            .ok_or_else(|| format!("{response_name} scope misses client"))?,
        &format!("{response_name} scope.client"),
    )?;
    validate_scope_address(
        scope
            .get("server")
            .ok_or_else(|| format!("{response_name} scope misses server"))?,
        &format!("{response_name} scope.server"),
    )?;
    Ok(scope)
}

fn validated_file_response_scope(scope: &Value) -> Result<(Map<String, Value>, bool), String> {
    let mut scope_without_extensions = scope
        .as_object()
        .cloned()
        .ok_or_else(|| String::from("FileResponse ASGI scope must be a JSON object"))?;
    let scope_type = scope_without_extensions
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    let extensions = scope_without_extensions.remove("extensions");
    let pathsend_extension = match extensions.as_ref() {
        None => false,
        Some(Value::Object(extensions)) if scope_type == "http" => {
            extensions.contains_key("http.response.pathsend")
        }
        Some(Value::Object(_)) => false,
        Some(_) => {
            return Err(String::from(
                "FileResponse ASGI scope.extensions must be an object when present",
            ));
        }
    };
    if scope_type == "websocket" {
        if let Some(extensions) = extensions {
            scope_without_extensions.insert("extensions".to_owned(), extensions);
        }
        let scope_with_extensions = Value::Object(scope_without_extensions);
        validate_websocket_scope(&scope_with_extensions)?;
        let validated = scope_with_extensions
            .as_object()
            .cloned()
            .ok_or_else(|| String::from("FileResponse WebSocket scope must be a JSON object"))?;
        return Ok((validated, false));
    }
    let scope_without_extensions = Value::Object(scope_without_extensions);
    let validated = validate_asgi_http_scope(&scope_without_extensions, "FileResponse")?.clone();
    Ok((validated, pathsend_extension))
}

fn validated_static_files_scope(
    scope: &Value,
) -> Result<(Map<String, Value>, bool, OsString, OsString), String> {
    let scope_object = scope
        .as_object()
        .ok_or_else(|| String::from("StaticFiles HTTP scope must be a JSON object"))?;
    let path = static_files_scope_path_value(
        scope_object
            .get("path")
            .ok_or_else(|| String::from("StaticFiles HTTP scope path is missing"))?,
        "StaticFiles HTTP scope.path",
    )?;
    let root_path = static_files_scope_path_value(
        scope_object
            .get("root_path")
            .ok_or_else(|| String::from("StaticFiles HTTP scope root_path is missing"))?,
        "StaticFiles HTTP scope.root_path",
    )?;

    let mut validator_scope = scope.clone();
    let validator_object = validator_scope
        .as_object_mut()
        .ok_or_else(|| String::from("StaticFiles HTTP scope must be a JSON object"))?;
    if validator_object.get("path").is_some_and(Value::is_object) {
        validator_object.insert(String::from("path"), Value::String(String::new()));
    }
    if validator_object
        .get("root_path")
        .is_some_and(Value::is_object)
    {
        validator_object.insert(String::from("root_path"), Value::String(String::new()));
    }
    let (validated, pathsend_extension) = validated_file_response_scope(&validator_scope)?;
    Ok((validated, pathsend_extension, path, root_path))
}

fn static_files_scope_path_value(value: &Value, context: &str) -> Result<OsString, String> {
    match value {
        Value::String(path) => Ok(OsString::from(path)),
        Value::Object(_) => {
            let encoded_path = exact_object(value, &["encoding", "data"], context)?;
            if string_field(encoded_path, "encoding", context)? != "filesystem-bytes-base64" {
                return Err(format!(
                    "{context}.encoding must be filesystem-bytes-base64"
                ));
            }
            let data = decode_base64(
                string_field(encoded_path, "data", context)?,
                &format!("{context}.data"),
            )?;
            #[cfg(unix)]
            {
                Ok(OsString::from_vec(data))
            }
            #[cfg(not(unix))]
            {
                String::from_utf8(data)
                    .map(OsString::from)
                    .map_err(|_| format!("{context} filesystem bytes are not valid UTF-8"))
            }
        }
        _ => Err(format!(
            "{context} must be a string or tagged filesystem-byte value"
        )),
    }
}

type HeaderPairs = Vec<(Vec<u8>, Vec<u8>)>;

fn parse_scope_request_headers(
    scope: &Map<String, Value>,
    context: &str,
) -> Result<HeaderPairs, String> {
    scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.headers_base64_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context} header[{index}] must be a pair"))?;
            let name = decode_base64(
                pair[0]
                    .as_str()
                    .ok_or_else(|| format!("{context} header[{index}][0] must be base64"))?,
                &format!("{context} header[{index}][0]"),
            )?;
            let value = decode_base64(
                pair[1]
                    .as_str()
                    .ok_or_else(|| format!("{context} header[{index}][1] must be base64"))?,
                &format!("{context} header[{index}][1]"),
            )?;
            Ok((name, value))
        })
        .collect()
}

trait CookieMutationTarget {
    fn apply_set_cookie(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError>;

    fn apply_delete_cookie(
        &mut self,
        key: &str,
        expires: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError>;
}

impl CookieMutationTarget for Response {
    fn apply_set_cookie(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.set_cookie_with_options(key, value, options)
    }

    fn apply_delete_cookie(
        &mut self,
        key: &str,
        expires: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.delete_cookie_with_options(key, expires, options)
    }
}

impl CookieMutationTarget for StreamingResponse {
    fn apply_set_cookie(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.set_cookie_with_options(key, value, options)
    }

    fn apply_delete_cookie(
        &mut self,
        key: &str,
        expires: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.delete_cookie_with_options(key, expires, options)
    }
}

impl CookieMutationTarget for NativeFileResponse {
    fn apply_set_cookie(
        &mut self,
        key: &str,
        value: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.set_cookie_with_options(key, value, options)
    }

    fn apply_delete_cookie(
        &mut self,
        key: &str,
        expires: &str,
        options: &CookieOptions,
    ) -> Result<(), starlette_rs::ResponseError> {
        self.delete_cookie_with_options(key, expires, options)
    }
}

fn run_basic_response_case(case: &Value) -> Result<Value, String> {
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "content",
        "status_code",
        "header_pairs",
        "media_type",
        "scope",
        "incoming",
        "send",
        "observations",
    ];
    if case.get("cookie_actions").is_some() {
        expected_fields.push("cookie_actions");
    }
    if case.get("header_actions").is_some() {
        expected_fields.push("header_actions");
    }
    let case = exact_object(case, &expected_fields, "Response asgi-call case")?;
    let case_id = string_field(case, "case_id", "Response asgi-call case")?;
    let surface = string_field(case, "surface", "Response asgi-call case")?;
    let label = match surface {
        RESPONSE_SURFACE => "Response",
        JSON_RESPONSE_SURFACE => "JSONResponse",
        _ => return Err(String::from("unsupported response surface")),
    };
    if !case_id.starts_with(&format!("{surface}.{RESPONSE_OPERATION}."))
        || string_field(case, "operation", "Response asgi-call case")? != RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "case ID or selectors are outside the Response ASGI-call slice",
        ));
    }
    validate_string_array(case, "covers", "Response asgi-call covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "Response asgi-call target_profiles",
        false,
    )?;
    if case.get("incoming") != Some(&json!([])) {
        return Err(String::from(
            "Response asgi-call requires an empty incoming sequence",
        ));
    }
    validate_capture_send(
        case.get("send")
            .ok_or_else(|| String::from("Response asgi-call send input is missing"))?,
    )?;
    validate_asgi_http_scope(
        case.get("scope")
            .ok_or_else(|| String::from("Response asgi-call scope is missing"))?,
        label,
    )?;

    let content = exact_object(
        case.get("content")
            .ok_or_else(|| String::from("Response asgi-call content is missing"))?,
        &["kind", "value"],
        "Response content",
    )?;
    let content_kind = string_field(content, "kind", "Response content")?;
    let body = match (label, content_kind) {
        ("Response", "none") => {
            if !content.get("value").is_some_and(Value::is_null) {
                return Err(String::from("Response none content.value must be null"));
            }
            Vec::new()
        }
        ("Response", "text") => string_field(content, "value", "Response text content")?
            .as_bytes()
            .to_vec(),
        ("Response", "base64-bytes") => decode_base64(
            string_field(content, "value", "Response base64-bytes content")?,
            "Response content.value",
        )?,
        ("JSONResponse", "json") => {
            let value = content
                .get("value")
                .filter(|value| value.is_null())
                .ok_or_else(|| String::from("JSONResponse content.value must be null"))?;
            serde_json::to_vec(value).map_err(|error| error.to_string())?
        }
        ("Response", _) => {
            return Err(String::from(
                "Response content kind must be none, text, or base64-bytes",
            ));
        }
        ("JSONResponse", _) => {
            return Err(String::from("JSONResponse content kind must be json"));
        }
        _ => return Err(String::from("unsupported response content")),
    };
    let status_code = case
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| String::from("Response status_code must be an unsigned 16-bit integer"))?;
    let header_pairs = case
        .get("header_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Response header_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("Response header_pairs[{index}] must be a pair"))?;
            let name = pair[0]
                .as_str()
                .ok_or_else(|| format!("Response header_pairs[{index}] name must be a string"))?;
            let value = pair[1]
                .as_str()
                .ok_or_else(|| format!("Response header_pairs[{index}] value must be a string"))?;
            Ok((name.to_owned(), value.to_owned()))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let requested_media_type = match case.get("media_type") {
        Some(Value::Null) => None,
        Some(Value::String(media_type)) => Some(media_type.as_str()),
        _ => return Err(String::from("Response media_type must be a string or null")),
    };
    let media_type =
        requested_media_type.or_else(|| (label == "JSONResponse").then_some("application/json"));

    let mut response = Response::from_content(
        status_code,
        body,
        media_type,
        header_pairs
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    )
    .map_err(|error| error.to_string())?;
    if let Some(actions) = case.get("cookie_actions") {
        apply_response_cookie_actions(&mut response, actions)?;
    }
    let header_action_results = case
        .get("header_actions")
        .map(|actions| apply_response_header_actions(&mut response, actions))
        .transpose()?;
    let events = response
        .asgi_events()
        .into_iter()
        .map(canonical_response_event)
        .collect::<Vec<_>>();
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();

    let mut observation = json!({
        "response_status": response.status_code(),
        "ordered_repeated_headers": canonical_headers(response.headers()),
        "response_bytes": {
            "encoding": "base64",
            "data": encode_base64(response.body()),
        },
        "asgi_event_order": event_order,
        "asgi_events": events,
    });
    if label == "Response" {
        observation["background_execution_trace"] = Value::Null;
    }
    if let Some(results) = header_action_results {
        observation["header_action_results"] = json!(results);
    }

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": RESPONSE_OPERATION,
            "status": "ok",
            "value": observation,
        }],
    }))
}

fn apply_response_cookie_actions<T: CookieMutationTarget>(
    response: &mut T,
    value: &Value,
) -> Result<(), String> {
    let actions = value
        .as_array()
        .ok_or_else(|| String::from("Response cookie_actions must be an array"))?;
    for (index, raw_action) in actions.iter().enumerate() {
        let context = format!("Response cookie_actions[{index}]");
        let method = value
            .get(index)
            .and_then(Value::as_object)
            .and_then(|action| action.get("method"))
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{context}.method must be a string"))?;
        let fields = match method {
            "set" => &[
                "method",
                "key",
                "value",
                "max_age",
                "expires",
                "path",
                "domain",
                "secure",
                "httponly",
                "samesite",
                "partitioned",
            ][..],
            "delete" => &[
                "method",
                "key",
                "clock_unix_seconds",
                "path",
                "domain",
                "secure",
                "httponly",
                "samesite",
            ][..],
            _ => return Err(format!("{context}.method must be set or delete")),
        };
        let action = exact_object(raw_action, fields, &context)?;
        let key = string_field(action, "key", &context)?;
        let max_age = if method == "set" {
            match action.get("max_age") {
                Some(Value::Null) => None,
                Some(Value::Number(value)) => Some(
                    value
                        .as_i64()
                        .ok_or_else(|| {
                            format!("{context}.max_age must fit a signed 64-bit integer")
                        })?
                        .to_string(),
                ),
                _ => return Err(format!("{context}.max_age must be an integer or null")),
            }
        } else {
            None
        };
        let expires = if method == "set" {
            optional_string_field(action, "expires", &context)?
        } else {
            None
        };
        let options = CookieOptions {
            max_age,
            expires,
            path: optional_string_field(action, "path", &context)?,
            domain: optional_string_field(action, "domain", &context)?,
            secure: bool_field(action, "secure", &context)?,
            httponly: bool_field(action, "httponly", &context)?,
            samesite: optional_string_field(action, "samesite", &context)?,
            partitioned: if method == "set" {
                bool_field(action, "partitioned", &context)?
            } else {
                false
            },
        };
        if method == "set" {
            let cookie_value = string_field(action, "value", &context)?;
            response
                .apply_set_cookie(key, cookie_value, &options)
                .map_err(|error| format!("{context}: {error}"))?;
        } else {
            let clock_seconds = action
                .get("clock_unix_seconds")
                .and_then(Value::as_u64)
                .ok_or_else(|| format!("{context}.clock_unix_seconds must be non-negative"))?;
            let now = UNIX_EPOCH
                .checked_add(Duration::from_secs(clock_seconds))
                .ok_or_else(|| format!("{context}.clock_unix_seconds is out of range"))?;
            let expires = httpdate::fmt_http_date(now);
            response
                .apply_delete_cookie(key, &expires, &options)
                .map_err(|error| format!("{context}: {error}"))?;
        }
    }
    Ok(())
}

trait ResponseHeaderMutationTarget {
    fn header_get(&self, name: &str) -> Result<Option<String>, ResponseError>;
    fn header_set(&mut self, name: &str, value: &str) -> Result<(), ResponseError>;
    fn header_delete(&mut self, name: &str) -> Result<(), ResponseError>;
    fn header_append(&mut self, name: &str, value: &str) -> Result<(), ResponseError>;
    fn header_get_values(&self, name: &str) -> Result<Vec<String>, ResponseError>;
}

impl ResponseHeaderMutationTarget for Response {
    fn header_get(&self, name: &str) -> Result<Option<String>, ResponseError> {
        self.get_header(name)
    }

    fn header_set(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        self.set_header(name, value)
    }

    fn header_delete(&mut self, name: &str) -> Result<(), ResponseError> {
        self.delete_header(name)
    }

    fn header_append(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        self.append_header(name, value)
    }

    fn header_get_values(&self, name: &str) -> Result<Vec<String>, ResponseError> {
        self.get_header_values(name)
    }
}

impl ResponseHeaderMutationTarget for NativeFileResponse {
    fn header_get(&self, name: &str) -> Result<Option<String>, ResponseError> {
        self.get_header(name)
    }

    fn header_set(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        self.set_header(name, value)
    }

    fn header_delete(&mut self, name: &str) -> Result<(), ResponseError> {
        self.delete_header(name)
    }

    fn header_append(&mut self, name: &str, value: &str) -> Result<(), ResponseError> {
        self.append_header(name, value)
    }

    fn header_get_values(&self, name: &str) -> Result<Vec<String>, ResponseError> {
        self.get_header_values(name)
    }
}

fn apply_response_header_actions<T: ResponseHeaderMutationTarget>(
    response: &mut T,
    value: &Value,
) -> Result<Vec<Value>, String> {
    let actions = value
        .as_array()
        .ok_or_else(|| String::from("Response header_actions must be an array"))?;
    let mut results = Vec::new();
    for (index, raw_action) in actions.iter().enumerate() {
        let context = format!("Response header_actions[{index}]");
        let kind = raw_action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{context}.kind must be a string"))?;
        let action = match kind {
            "get" | "get-values" | "delete" => {
                exact_object(raw_action, &["kind", "key"], &context)?
            }
            "set" | "append" => exact_object(raw_action, &["kind", "key", "value"], &context)?,
            _ => return Err(format!("{context}.kind is unsupported")),
        };
        let key = string_field(action, "key", &context)?;
        match kind {
            "get" => results.push(json!(
                response
                    .header_get(key)
                    .map_err(|error| error.to_string())?
            )),
            "get-values" => results.push(json!(
                response
                    .header_get_values(key)
                    .map_err(|error| error.to_string())?
            )),
            "set" => response
                .header_set(key, string_field(action, "value", &context)?)
                .map_err(|error| error.to_string())?,
            "append" => response
                .header_append(key, string_field(action, "value", &context)?)
                .map_err(|error| error.to_string())?,
            "delete" => response
                .header_delete(key)
                .map_err(|error| error.to_string())?,
            _ => return Err(format!("{context}.kind is unsupported")),
        }
    }
    Ok(results)
}

fn run_streaming_response_case(case: &Value) -> Result<Value, String> {
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "content",
        "status_code",
        "header_pairs",
        "media_type",
        "scope",
        "incoming",
        "send",
        "observations",
        "streaming",
    ];
    if case.get("cookie_actions").is_some() {
        expected_fields.push("cookie_actions");
    }
    let case = exact_object(case, &expected_fields, "StreamingResponse asgi-call case")?;
    let case_id = string_field(case, "case_id", "StreamingResponse asgi-call case")?;
    if !case_id.starts_with(&format!(
        "{STREAMING_RESPONSE_SURFACE}.{RESPONSE_OPERATION}."
    )) || string_field(case, "surface", "StreamingResponse asgi-call case")?
        != STREAMING_RESPONSE_SURFACE
        || string_field(case, "operation", "StreamingResponse asgi-call case")?
            != RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "case ID or selectors are outside the StreamingResponse ASGI-call slice",
        ));
    }
    if string_field(case, "streaming", "StreamingResponse asgi-call case")? != "sync" {
        return Err(String::from(
            "StreamingResponse streaming must be sync for this slice",
        ));
    }
    validate_string_array(case, "covers", "StreamingResponse asgi-call covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "StreamingResponse asgi-call target_profiles",
        false,
    )?;
    if case.get("incoming") != Some(&json!([])) {
        return Err(String::from(
            "StreamingResponse asgi-call requires an empty incoming sequence",
        ));
    }
    validate_capture_send(
        case.get("send")
            .ok_or_else(|| String::from("StreamingResponse asgi-call send input is missing"))?,
    )?;
    validate_asgi_http_scope(
        case.get("scope")
            .ok_or_else(|| String::from("StreamingResponse asgi-call scope is missing"))?,
        "StreamingResponse",
    )?;

    let content = exact_object(
        case.get("content")
            .ok_or_else(|| String::from("StreamingResponse content is missing"))?,
        &["kind", "value"],
        "StreamingResponse content",
    )?;
    if string_field(content, "kind", "StreamingResponse content")? != "chunks" {
        return Err(String::from(
            "StreamingResponse content.kind must be chunks",
        ));
    }
    let chunk_values = content
        .get("value")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StreamingResponse chunks.value must be an array"))?;
    let mut chunks = Vec::with_capacity(chunk_values.len());
    for (index, chunk_value) in chunk_values.iter().enumerate() {
        let context = format!("StreamingResponse chunks.value[{index}]");
        let chunk = exact_object(chunk_value, &["kind", "value"], &context)?;
        let kind = string_field(chunk, "kind", &context)?;
        let value = string_field(chunk, "value", &context)?;
        let bytes = match kind {
            "text" => value.as_bytes().to_vec(),
            "base64-bytes" => decode_base64(value, &format!("{context}.value"))?,
            "memoryview" => {
                return Err(format!("{context}.kind memoryview is unsupported"));
            }
            _ => return Err(format!("{context}.kind must be text or base64-bytes")),
        };
        chunks.push(bytes);
    }

    let status_code = case
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| {
            String::from("StreamingResponse status_code must be an unsigned 16-bit integer")
        })?;
    let header_pairs = case
        .get("header_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StreamingResponse header_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("StreamingResponse header_pairs[{index}] must be a pair"))?;
            let name = pair[0].as_str().ok_or_else(|| {
                format!("StreamingResponse header_pairs[{index}] name must be a string")
            })?;
            let value = pair[1].as_str().ok_or_else(|| {
                format!("StreamingResponse header_pairs[{index}] value must be a string")
            })?;
            Ok((name.to_owned(), value.to_owned()))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let media_type = match case.get("media_type") {
        Some(Value::Null) => None,
        Some(Value::String(media_type)) => Some(media_type.as_str()),
        _ => {
            return Err(String::from(
                "StreamingResponse media_type must be a string or null",
            ));
        }
    };

    let mut response = StreamingResponse::from_chunks(
        status_code,
        chunks,
        media_type,
        header_pairs
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    )
    .map_err(|error| error.to_string())?;
    if let Some(actions) = case.get("cookie_actions") {
        apply_response_cookie_actions(&mut response, actions)?;
    }
    let response_body = response
        .chunks()
        .iter()
        .flatten()
        .copied()
        .collect::<Vec<_>>();
    let events = response
        .asgi_events()
        .into_iter()
        .map(canonical_streaming_response_event)
        .collect::<Vec<_>>();
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": RESPONSE_OPERATION,
            "status": "ok",
            "value": {
                "response_status": response.status_code(),
                "ordered_repeated_headers": canonical_headers(response.headers()),
                "response_bytes": {
                    "encoding": "base64",
                    "data": encode_base64(&response_body),
                },
                "asgi_event_order": event_order,
                "asgi_events": events,
            },
        }],
    }))
}

fn run_file_response_case(case: &Value) -> Result<Value, String> {
    let request_sequence = case.get("calls").is_some();
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "file",
        "status_code",
        "header_pairs",
        "media_type",
        "filename",
        "observations",
    ];
    if request_sequence {
        expected_fields.push("calls");
    } else {
        expected_fields.extend(["scope", "incoming", "send"]);
    }
    if case.get("cookie_actions").is_some() {
        expected_fields.push("cookie_actions");
    }
    if case.get("header_actions").is_some() {
        expected_fields.push("header_actions");
    }
    if case.get("chunk_size").is_some() {
        expected_fields.push("chunk_size");
    }
    if case.get("max_ranges").is_some() {
        expected_fields.push("max_ranges");
    }
    if case.get("content_disposition_type").is_some() {
        expected_fields.push("content_disposition_type");
    }
    if case.get("background_task").is_some() {
        expected_fields.push("background_task");
    }
    if case.get("stat_result").is_some() {
        expected_fields.push("stat_result");
    }
    if case.get("call_time_field_assignments").is_some() {
        expected_fields.push("call_time_field_assignments");
    }
    if case.get("fault_contract").is_some() {
        expected_fields.push("fault_contract");
    }
    let case = exact_object(case, &expected_fields, "FileResponse asgi-call case")?;
    let fault_point = case
        .get("fault_contract")
        .map(|value| {
            let selector = exact_object(
                value,
                &["contract_id", "fault_point"],
                "FileResponse fault-contract selector",
            )?;
            let _contract_id = string_field(
                selector,
                "contract_id",
                "FileResponse fault-contract selector",
            )?;
            let fault_point = string_field(
                selector,
                "fault_point",
                "FileResponse fault-contract selector",
            )?;
            if fault_point != FILE_RESPONSE_RANDOM_SOURCE_FAULT_POINT {
                return Err(String::from(
                    "FileResponse fault-contract point is unsupported",
                ));
            }
            Ok(fault_point.to_owned())
        })
        .transpose()?;
    let case_id = string_field(case, "case_id", "FileResponse asgi-call case")?;
    if !case_id.starts_with(&format!("{FILE_RESPONSE_SURFACE}.{RESPONSE_OPERATION}."))
        || string_field(case, "surface", "FileResponse asgi-call case")? != FILE_RESPONSE_SURFACE
        || string_field(case, "operation", "FileResponse asgi-call case")? != RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "case ID or selectors are outside the FileResponse ASGI-call slice",
        ));
    }
    validate_string_array(
        case,
        "covers",
        "FileResponse asgi-call covers",
        fault_point.is_some(),
    )?;
    validate_string_array(
        case,
        "target_profiles",
        "FileResponse asgi-call target_profiles",
        false,
    )?;
    let mut send_error = None;
    if request_sequence && case.get("header_actions").is_some() {
        return Err(String::from(
            "FileResponse header_actions require one request call",
        ));
    }
    let call_inputs: Vec<&Map<String, Value>> = if request_sequence {
        let calls = case
            .get("calls")
            .and_then(Value::as_array)
            .filter(|calls| calls.len() >= 2)
            .ok_or_else(|| String::from("FileResponse calls must contain at least two requests"))?;
        calls
            .iter()
            .enumerate()
            .map(|(index, call)| {
                let call = exact_object(call, &["scope", "incoming", "send"], "FileResponse call")?;
                if call.get("incoming") != Some(&json!([])) {
                    return Err(format!(
                        "FileResponse calls[{index}] requires empty receive"
                    ));
                }
                validate_capture_send(
                    call.get("send")
                        .ok_or_else(|| format!("FileResponse calls[{index}] send is missing"))?,
                )?;
                Ok(call)
            })
            .collect::<Result<Vec<_>, String>>()?
    } else {
        if case.get("incoming") != Some(&json!([])) {
            return Err(String::from(
                "FileResponse asgi-call requires an empty incoming sequence",
            ));
        }
        let send = case
            .get("send")
            .ok_or_else(|| String::from("FileResponse asgi-call send input is missing"))?;
        let send_object = send
            .as_object()
            .ok_or_else(|| String::from("FileResponse asgi-call send input must be an object"))?;
        if send_object.get("kind").and_then(Value::as_str) == Some("capture-asgi-send") {
            validate_capture_send(send)?;
        } else {
            let send_error_input = exact_object(
                send,
                &["kind", "event_index", "message"],
                "FileResponse bounded failing send",
            )?;
            if string_field(
                send_error_input,
                "kind",
                "FileResponse bounded failing send",
            )? != "capture-asgi-send-until-oserror"
            {
                return Err(String::from(
                    "FileResponse send input must select captured ASGI messages or bounded OSError",
                ));
            }
            let event_index = send_error_input
                .get("event_index")
                .and_then(Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
                .filter(|value| (6..=64).contains(value))
                .ok_or_else(|| {
                    String::from("FileResponse bounded failing send event_index must be 6 to 64")
                })?;
            let message = string_field(
                send_error_input,
                "message",
                "FileResponse bounded failing send",
            )?
            .to_owned();
            send_error = Some((event_index, message));
        }
        vec![case]
    };

    let source_file = case
        .get("file")
        .ok_or_else(|| String::from("FileResponse asgi-call file is missing"))?;
    let (temporary_directory, path, stat_override, error_path_kind) =
        if source_file.get("kind").and_then(Value::as_str).is_some() {
            let source_file =
                exact_object(source_file, &["kind", "path"], "FileResponse error path")?;
            let kind = string_field(source_file, "kind", "FileResponse error path")?;
            if request_sequence || (kind != "directory" && kind != "missing") {
                return Err(String::from("FileResponse error path kind is unsupported"));
            }
            let path_text = string_field(source_file, "path", "FileResponse error path")?;
            let path = Path::new(path_text);
            if path_text.is_empty()
                || path_text.contains('\\')
                || path_text.as_bytes().contains(&0)
                || path.is_absolute()
                || path
                    .components()
                    .any(|component| matches!(component, std::path::Component::ParentDir))
            {
                return Err(String::from(
                    "FileResponse error path must be a safe relative path",
                ));
            }
            if (kind == "directory" && !path.is_dir()) || (kind == "missing" && path.exists()) {
                return Err(format!(
                    "FileResponse {kind} error path does not match the current filesystem"
                ));
            }
            (None, path.to_path_buf(), None, Some(kind.to_owned()))
        } else {
            let source_file = exact_object(
                source_file,
                &["name", "contents_base64", "mtime_seconds"],
                "FileResponse file",
            )?;
            let file_name = string_field(source_file, "name", "FileResponse file")?;
            if file_name.is_empty()
                || file_name == "."
                || file_name == ".."
                || file_name.contains('/')
                || file_name.contains('\\')
                || file_name.as_bytes().contains(&0)
            {
                return Err(String::from(
                    "FileResponse file.name must be a non-empty basename",
                ));
            }
            let contents = decode_base64(
                string_field(source_file, "contents_base64", "FileResponse file")?,
                "FileResponse file.contents_base64",
            )?;
            let mtime_number = source_file
                .get("mtime_seconds")
                .and_then(Value::as_f64)
                .filter(|value| value.is_finite())
                .ok_or_else(|| String::from("FileResponse file.mtime_seconds must be finite"))?;
            let (temporary_directory, path) = create_file_response_input(file_name, &contents)?;
            let metadata = if let Some(stat_result) = case.get("stat_result") {
                let stat_result = exact_object(
                    stat_result,
                    &["size", "mtime_seconds"],
                    "FileResponse stat_result",
                )?;
                let size = stat_result
                    .get("size")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| {
                        String::from("FileResponse stat_result.size must be an unsigned integer")
                    })?;
                let modified_seconds = stat_result
                    .get("mtime_seconds")
                    .and_then(Value::as_f64)
                    .filter(|value| value.is_finite())
                    .ok_or_else(|| {
                        String::from("FileResponse stat_result.mtime_seconds must be finite")
                    })?;
                FileMetadata::from_unix_seconds(size, modified_seconds)
            } else {
                FileMetadata::from_unix_seconds(
                    u64::try_from(contents.len()).map_err(|error| error.to_string())?,
                    mtime_number,
                )
            }
            .map_err(|error| error.to_string())?;
            (Some(temporary_directory), path, Some(metadata), None)
        };

    let status_code = case
        .get("status_code")
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| {
            String::from("FileResponse status_code must be an unsigned 16-bit integer")
        })?;
    let header_pairs = case
        .get("header_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("FileResponse header_pairs must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, pair)| {
            let pair = pair
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("FileResponse header_pairs[{index}] must be a pair"))?;
            let name = pair[0].as_str().ok_or_else(|| {
                format!("FileResponse header_pairs[{index}] name must be a string")
            })?;
            let value = pair[1].as_str().ok_or_else(|| {
                format!("FileResponse header_pairs[{index}] value must be a string")
            })?;
            Ok((name.to_owned(), value.to_owned()))
        })
        .collect::<Result<Vec<_>, String>>()?;
    let media_type = match case.get("media_type") {
        Some(Value::Null) => None,
        Some(Value::String(media_type)) => Some(media_type.clone()),
        _ => {
            return Err(String::from(
                "FileResponse media_type must be a string or null",
            ));
        }
    };
    let filename = match case.get("filename") {
        Some(Value::Null) => None,
        Some(Value::String(filename)) => Some(filename.clone()),
        _ => {
            return Err(String::from(
                "FileResponse filename must be a string or null",
            ));
        }
    };
    let content_disposition_type = match case.get("content_disposition_type") {
        None => String::from("attachment"),
        Some(Value::String(value)) if value == "attachment" || value == "inline" => value.clone(),
        _ => {
            return Err(String::from(
                "FileResponse content_disposition_type must be attachment or inline",
            ));
        }
    };
    let background_task = case
        .get("background_task")
        .map(|value| {
            let task = exact_object(
                value,
                &["kind", "start", "stop", "separator"],
                "FileResponse background task",
            )?;
            if string_field(task, "kind", "FileResponse background task")?
                != "append-number-sequence"
            {
                return Err(String::from(
                    "FileResponse background task kind is unsupported",
                ));
            }
            let start = task.get("start").and_then(Value::as_i64).ok_or_else(|| {
                String::from("FileResponse background task start must be an integer")
            })?;
            let stop = task.get("stop").and_then(Value::as_i64).ok_or_else(|| {
                String::from("FileResponse background task stop must be an integer")
            })?;
            if start > stop || stop.saturating_sub(start) > 1000 {
                return Err(String::from(
                    "FileResponse background task requires an increasing bounded integer range",
                ));
            }
            let separator = string_field(task, "separator", "FileResponse background task")?;
            Ok((start, stop, separator.to_owned()))
        })
        .transpose()?;
    if background_task.is_some() && (request_sequence || error_path_kind.is_some()) {
        return Err(String::from(
            "FileResponse background task requires one regular-file request",
        ));
    }

    let mut options = FileResponseOptions {
        media_type,
        filename,
        content_disposition_type,
        stat_override,
        ..FileResponseOptions::default()
    };
    if let Some(value) = case.get("chunk_size") {
        options.chunk_size = value
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| String::from("FileResponse chunk_size must fit an unsigned integer"))?;
    }
    if let Some(value) = case.get("max_ranges") {
        options.max_ranges = value
            .as_u64()
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| String::from("FileResponse max_ranges must fit an unsigned integer"))?;
    }
    let mut response = match NativeFileResponse::new(
        path.clone(),
        path.to_string_lossy().into_owned(),
        status_code,
        &header_pairs,
        options,
    ) {
        Ok(response) => response,
        Err(error) => {
            let dispatch_error = file_response_dispatch_error(error);
            let value = if request_sequence {
                json!({
                    "responses": [],
                    "dispatch_error": dispatch_error,
                })
            } else {
                let mut observation = json!({
                    "response_status": null,
                    "ordered_repeated_headers": [],
                    "response_bytes": {
                        "encoding": "base64",
                        "data": "",
                    },
                    "asgi_event_order": [],
                    "asgi_events": [],
                    "dispatch_error": dispatch_error,
                });
                if background_task.is_some() {
                    if let Some(observation) = observation.as_object_mut() {
                        observation.insert(
                            String::from("background_task"),
                            json!({
                                "initial_value": "",
                                "value": "",
                                "execution_trace": [],
                            }),
                        );
                    }
                }
                if case.get("header_actions").is_some() {
                    observation["header_action_results"] = json!([]);
                }
                observation
            };
            drop(temporary_directory);
            return Ok(json!({
                "case_id": case_id,
                "status": "completed",
                "observations": [{
                    "step_id": RESPONSE_OPERATION,
                    "status": "ok",
                    "value": value,
                }],
            }));
        }
    };
    let cached_header_view = response.headers().to_vec();
    let mut view_is_raw = true;
    if let Some(assignments) = case.get("call_time_field_assignments") {
        let assignments = assignments
            .as_object()
            .ok_or_else(|| String::from("FileResponse call-time assignments must be an object"))?;
        for (field, value) in assignments {
            match field.as_str() {
                "raw_headers" => {
                    let raw_headers = value.as_array().filter(|headers| headers.is_empty());
                    if raw_headers.is_none() {
                        return Err(String::from(
                            "FileResponse raw_headers assignment must be an empty array",
                        ));
                    }
                    response.replace_headers_raw(Vec::new());
                    view_is_raw = false;
                }
                _ => {
                    return Err(format!(
                        "FileResponse call-time assignment {field:?} is unsupported by the native adapter"
                    ));
                }
            }
        }
    }
    if let Some(actions) = case.get("cookie_actions") {
        apply_response_cookie_actions(&mut response, actions)?;
    }
    let header_action_results = case
        .get("header_actions")
        .map(|actions| apply_response_header_actions(&mut response, actions))
        .transpose()?;
    if fault_point.is_some() {
        #[cfg(feature = "fault-contract")]
        fault_contract_fail_next_random_boundary();
        #[cfg(not(feature = "fault-contract"))]
        return Err(String::from(
            "FileResponse fault-contract instrumentation is not enabled",
        ));
    }
    let mut responses = Vec::with_capacity(call_inputs.len());
    let mut captured_dispatch_error = None;
    let mut execution_trace = Vec::new();
    let mut background_value = String::new();
    for call_input in call_inputs {
        let (scope, pathsend_extension) = validated_file_response_scope(
            call_input
                .get("scope")
                .ok_or_else(|| String::from("FileResponse call scope is missing"))?,
        )?;
        if request_sequence && pathsend_extension {
            return Err(String::from(
                "FileResponse call sequences do not combine with pathsend extensions",
            ));
        }
        let scope_type = string_field(&scope, "type", "FileResponse ASGI scope")?;
        let request_headers = parse_scope_request_headers(&scope, "FileResponse ASGI scope")?;
        let method = if scope_type == "http" {
            string_field(&scope, "method", "FileResponse HTTP scope")?
        } else {
            ""
        };
        let raw_headers = response.headers().to_vec();
        let view_headers = if view_is_raw {
            raw_headers.clone()
        } else {
            cached_header_view.clone()
        };
        let mut call = match response.call_state_with_headers(
            FileResponseHeaderViews {
                view: view_headers,
                raw: raw_headers,
                view_is_raw,
            },
            scope_type,
            method,
            &request_headers,
            pathsend_extension,
            background_task.is_some(),
        ) {
            Ok(call) => call,
            Err(error) => {
                captured_dispatch_error = Some(file_response_dispatch_error(error));
                responses.push(json!({
                    "response_status": null,
                    "ordered_repeated_headers": [],
                    "response_bytes": {
                        "encoding": "base64",
                        "data": "",
                    },
                    "asgi_event_order": [],
                    "asgi_events": [],
                }));
                break;
            }
        };

        let mut response_status = None;
        let mut ordered_headers = Vec::new();
        let mut response_bytes = Vec::new();
        let mut events = Vec::new();
        let mut send_index = 0usize;
        loop {
            let step = match call.step() {
                Ok(step) => step,
                Err(error) => {
                    captured_dispatch_error = Some(file_response_io_dispatch_error(error));
                    break;
                }
            };
            match step {
                FileResponseCallStep::Send(event) => {
                    if send_error
                        .as_ref()
                        .is_some_and(|(event_index, _)| send_index == *event_index)
                    {
                        let message = send_error
                            .as_ref()
                            .map(|(_, message)| message.clone())
                            .ok_or_else(|| {
                                String::from("FileResponse failing send input disappeared")
                            })?;
                        match call
                            .advance(FileResponseCallInput::<String>::Send(Err(message.clone())))
                        {
                            Err(FileResponseCallError::Operation(error)) if error == message => {
                                captured_dispatch_error = Some(json!({
                                    "class": "builtins.OSError",
                                    "kind": "exception",
                                    "message": message,
                                    "stage": "dispatch",
                                    "code": null,
                                    "cause": null,
                                    "suppress_context": false,
                                }));
                                break;
                            }
                            Err(error) => {
                                return Err(format!(
                                    "FileResponse failed-send transition returned an unexpected error: {error:?}"
                                ));
                            }
                            Ok(()) => {
                                return Err(String::from(
                                    "FileResponse failed-send transition unexpectedly succeeded",
                                ));
                            }
                        }
                    }
                    checked_usize_increment(&mut send_index, "FileResponse send event index")?;
                    let websocket = scope_type == "websocket";
                    let event_type = match &event {
                        FileResponseEvent::Start { .. } if websocket => {
                            "websocket.http.response.start"
                        }
                        FileResponseEvent::Start { .. } => "http.response.start",
                        FileResponseEvent::Body { .. } if websocket => {
                            "websocket.http.response.body"
                        }
                        FileResponseEvent::Body { .. } => "http.response.body",
                        FileResponseEvent::Pathsend { .. } => "http.response.pathsend",
                    };
                    execution_trace.push(String::from(event_type));
                    match &event {
                        FileResponseEvent::Start {
                            status_code,
                            headers,
                        } => {
                            response_status = Some(*status_code);
                            ordered_headers = canonical_headers(headers);
                        }
                        FileResponseEvent::Body { body, .. } => {
                            response_bytes.extend_from_slice(body);
                        }
                        FileResponseEvent::Pathsend { .. } => {}
                    }
                    events.push(canonical_file_response_event(event, websocket));
                    call.advance(FileResponseCallInput::<String>::Send(Ok(())))
                        .map_err(|error| {
                            format!("FileResponse send transition failed: {error:?}")
                        })?;
                }
                FileResponseCallStep::RunBackground => {
                    let (start, stop, separator) = background_task.as_ref().ok_or_else(|| {
                        String::from("FileResponse requested a missing background task input")
                    })?;
                    execution_trace.push(String::from("background.start"));
                    for number in *start..=*stop {
                        background_value.push_str(&number.to_string());
                        if number != *stop {
                            background_value.push_str(separator);
                        }
                    }
                    execution_trace.push(String::from("background.complete"));
                    call.advance(FileResponseCallInput::<String>::BackgroundFinished(Ok(())))
                        .map_err(|error| {
                            format!("FileResponse background transition failed: {error:?}")
                        })?;
                }
                FileResponseCallStep::Complete => break,
                FileResponseCallStep::Failed => {
                    return Err(String::from("FileResponse call reached a failed state"));
                }
            }
        }
        let event_order = events
            .iter()
            .filter_map(|event| event.get("type").and_then(Value::as_str))
            .map(str::to_owned)
            .collect::<Vec<_>>();
        responses.push(json!({
            "response_status": response_status,
            "ordered_repeated_headers": ordered_headers,
            "response_bytes": {
                "encoding": "base64",
                "data": encode_base64(&response_bytes),
            },
            "asgi_event_order": event_order,
            "asgi_events": events,
        }));
    }
    let value = if request_sequence {
        json!({"responses": responses})
    } else {
        let mut response = responses
            .into_iter()
            .next()
            .ok_or_else(|| String::from("FileResponse call produced no observations"))?;
        let response_object = response
            .as_object_mut()
            .ok_or_else(|| String::from("FileResponse observation is not an object"))?;
        response_object.insert(
            String::from("dispatch_error"),
            captured_dispatch_error.unwrap_or(Value::Null),
        );
        if background_task.is_some() {
            response_object.insert(
                String::from("background_task"),
                json!({
                    "initial_value": "",
                    "value": background_value,
                    "execution_trace": execution_trace,
                }),
            );
        }
        if let Some(results) = header_action_results {
            response_object.insert(String::from("header_action_results"), json!(results));
        }
        response
    };
    drop(temporary_directory);
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": RESPONSE_OPERATION,
            "status": "ok",
            "value": value,
        }],
    }))
}

fn file_response_dispatch_error(error: FileResponseError) -> Value {
    let (class, message) = match error {
        FileResponseError::HeaderDataIsNotLatin1 { value, index } => (
            "builtins.UnicodeEncodeError",
            unicode_encode_error_message(&value, index),
        ),
        missing @ (FileResponseError::MissingFile(_) | FileResponseError::NotAFile(_)) => {
            ("builtins.RuntimeError", missing.to_string())
        }
        FileResponseError::InvalidTimestamp => (
            "builtins.ValueError",
            String::from("invalid file modification timestamp"),
        ),
        FileResponseError::TimestampYearOutOfRange(year) => (
            "builtins.ValueError",
            if source_python_version_at_least_314() {
                format!("year must be in 1..9999, not {year}")
            } else {
                format!("year {year} is out of range")
            },
        ),
        FileResponseError::MissingContentType => {
            ("builtins.KeyError", String::from("'content-type'"))
        }
        // The core uses u128 so valid addressable inputs retain Python's
        // unbounded Content-Length; this is only its unreachable overflow fallback.
        FileResponseError::ArithmeticOverflow => (
            "builtins.OverflowError",
            String::from("file response arithmetic overflow"),
        ),
        FileResponseError::StatIo(error) => {
            return file_response_io_dispatch_error(error);
        }
        FileResponseError::RandomSource => (
            "builtins.RuntimeError",
            String::from("could not generate multipart boundary"),
        ),
    };
    json!({
        "class": class,
        "kind": "exception",
        "message": message,
        "stage": "dispatch",
        "code": null,
        "cause": null,
        "suppress_context": false,
    })
}

fn file_response_io_dispatch_error(error: io::Error) -> Value {
    let class = match error.kind() {
        io::ErrorKind::NotFound => "builtins.FileNotFoundError",
        io::ErrorKind::PermissionDenied => "builtins.PermissionError",
        io::ErrorKind::IsADirectory => "builtins.IsADirectoryError",
        _ => "builtins.OSError",
    };
    json!({
        "class": class,
        "kind": "exception",
        "message": error.to_string(),
        "stage": "dispatch",
        "code": null,
        "cause": null,
        "suppress_context": false,
    })
}

fn unicode_encode_error_message(value: &str, index: usize) -> String {
    let character = value.chars().nth(index).map_or_else(
        || String::from("\\u0000"),
        |character| {
            let codepoint = u32::from(character);
            if codepoint <= 0xffff {
                format!("\\u{codepoint:04x}")
            } else {
                format!("\\U{codepoint:08x}")
            }
        },
    );
    format!(
        "'latin-1' codec can't encode character '{character}' in position {index}: ordinal not in range(256)"
    )
}

fn source_python_version_at_least_314() -> bool {
    env::var("STARLETTE_PARITY_SOURCE_PYTHON_VERSION")
        .ok()
        .and_then(|version| {
            let (major, minor) = version.split_once('.')?;
            Some((major.parse::<u8>().ok()?, minor.parse::<u8>().ok()?))
        })
        .is_some_and(|version| version >= (3, 14))
}

fn static_files_lookup_error_observation(error: &StaticFilesError) -> Value {
    let category = match error {
        StaticFilesError::InvalidPath => "value-error",
        StaticFilesError::PermissionDenied => "permission-error",
        StaticFilesError::Io(error) if error.kind() == io::ErrorKind::PermissionDenied => {
            "permission-error"
        }
        StaticFilesError::Io(_) => "os-error",
        _ => "other-error",
    };
    json!({
        "resolved_path": null,
        "stat_result_present": false,
        "mode_type_bits": null,
        "is_file": null,
        "is_directory": null,
        "size": null,
        "mtime_seconds": null,
        "lookup_error": {"category": category},
    })
}

fn run_static_files_lookup_path_case(case: &Value) -> Result<Value, String> {
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "directory",
        "files",
        "filesystem",
        "lookup_path",
        "check_dir",
        "follow_symlink",
        "observations",
    ];
    if case.get("observe_lookup_error").is_some() {
        expected_fields.push("observe_lookup_error");
    }
    let case = exact_object(case, &expected_fields, "StaticFiles lookup-path case")?;
    let case_id = string_field(case, "case_id", "StaticFiles lookup-path case")?;
    if string_field(case, "surface", "StaticFiles lookup-path case")? != STATIC_FILES_SURFACE
        || string_field(case, "operation", "StaticFiles lookup-path case")?
            != STATIC_FILES_LOOKUP_PATH_OPERATION
        || case.get("observations") != Some(&json!([STATIC_FILES_LOOKUP_PATH_OPERATION]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "case is outside the StaticFiles lookup-path contract",
        ));
    }
    validate_string_array(case, "covers", "StaticFiles lookup-path covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "StaticFiles lookup-path target_profiles",
        false,
    )?;
    let directory_name = match case.get("directory") {
        Some(Value::String(directory_name)) => Some(directory_name.as_str()),
        Some(Value::Null) => None,
        _ => {
            return Err(String::from(
                "StaticFiles lookup-path directory must be a relative basename or null",
            ));
        }
    };
    let check_dir = case
        .get("check_dir")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles lookup-path check_dir must be boolean"))?;
    let follow_symlink = case
        .get("follow_symlink")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles lookup-path follow_symlink must be boolean"))?;
    let observe_lookup_error = case
        .get("observe_lookup_error")
        .map(|value| {
            value.as_bool().ok_or_else(|| {
                String::from("StaticFiles lookup-path observe_lookup_error must be boolean")
            })
        })
        .transpose()?
        .unwrap_or(false);
    let file_inputs = case
        .get("files")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles lookup-path files must be an array"))?;
    if directory_name.is_some() && file_inputs.is_empty() {
        return Err(String::from(
            "StaticFiles lookup-path requires at least one input file",
        ));
    }
    if directory_name.is_none() && !file_inputs.is_empty() {
        return Err(String::from(
            "StaticFiles lookup-path without a root cannot define files",
        ));
    }
    let has_filesystem_byte_path = case.get("lookup_path").is_some_and(Value::is_object)
        || file_inputs
            .iter()
            .any(|file_input| file_input.get("path").is_some_and(Value::is_object));
    if has_filesystem_byte_path && !cfg!(unix) {
        return Ok(json!({
            "case_id": case_id,
            "status": "skipped",
            "observations": [{
                "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
                "status": "skipped",
                "reason": "filesystem-byte paths require POSIX filesystem surrogateescape support",
            }],
        }));
    }
    let lookup_path = static_files_lookup_path_value(
        case.get("lookup_path")
            .ok_or_else(|| String::from("StaticFiles lookup-path path is missing"))?,
    )?;
    let filesystem = case
        .get("filesystem")
        .ok_or_else(|| String::from("StaticFiles lookup-path filesystem is missing"))?;
    let (temporary_directory, root) = if let Some(directory_name) = directory_name {
        let (temporary_directory, root) =
            create_static_files_lookup_path_input(directory_name, file_inputs, filesystem)?;
        (Some(temporary_directory), Some(root))
    } else {
        let filesystem = exact_object(
            filesystem,
            &[
                "root_symlink_target",
                "directories",
                "outside_files",
                "symlinks",
            ],
            "StaticFiles lookup-path filesystem",
        )?;
        let has_entries = ["directories", "outside_files", "symlinks"]
            .iter()
            .any(|field| {
                filesystem
                    .get(*field)
                    .and_then(Value::as_array)
                    .is_none_or(|values| !values.is_empty())
            });
        if filesystem.get("root_symlink_target") != Some(&Value::Null) || has_entries {
            return Err(String::from(
                "StaticFiles lookup-path without a root cannot define filesystem entries",
            ));
        }
        (None, None)
    };
    let static_files = NativeStaticFiles::new(
        root.clone(),
        root.iter().cloned().collect(),
        false,
        check_dir,
        follow_symlink,
    )
    .map_err(|error| format!("StaticFiles lookup-path construction failed: {error:?}"))?;
    let observation = match static_files.lookup_path(&lookup_path) {
        Err(error) if observe_lookup_error => static_files_lookup_error_observation(&error),
        Err(StaticFilesError::InvalidPath) => json!({
            "lookup_error": {
                "class": "builtins.ValueError",
                "message": "embedded null byte",
            }
        }),
        Err(error) => return Err(format!("StaticFiles lookup_path failed: {error:?}")),
        Ok(Some(file)) => {
            let root = root
                .as_ref()
                .ok_or_else(|| String::from("StaticFiles found a file without configured roots"))?;
            let resolved_root = if follow_symlink {
                root.clone()
            } else {
                root.canonicalize()
                    .map_err(|error| format!("cannot canonicalize StaticFiles root: {error}"))?
            };
            let relative_path = file
                .path
                .strip_prefix(&resolved_root)
                .map_err(|error| format!("StaticFiles result escaped the root: {error}"))?
                .to_path_buf();
            let relative_path_bytes = static_files_relative_path_bytes(&relative_path);
            let mode_type_bits = file
                .metadata
                .stat_result()
                .map(|stat| stat.mode & 0o170000)
                .or({
                    if file.is_file {
                        Some(0o100000)
                    } else if file.is_directory {
                        Some(0o040000)
                    } else {
                        None
                    }
                });
            json!({
                "resolved_path": static_files_path_observation(&relative_path_bytes),
                "stat_result_present": true,
                "mode_type_bits": mode_type_bits,
                "is_file": file.is_file,
                "is_directory": file.is_directory,
                "size": if file.is_file { Some(file.metadata.size()) } else { None },
                "mtime_seconds": if file.is_file {
                    Some(file.metadata.modified_unix_seconds())
                } else {
                    None
                },
            })
        }
        Ok(None) => json!({
            "resolved_path": null,
            "stat_result_present": false,
            "mode_type_bits": null,
            "is_file": null,
            "is_directory": null,
            "size": null,
            "mtime_seconds": null,
        }),
    };
    let observation = if observe_lookup_error {
        let mut observation = observation;
        let fields = observation
            .as_object_mut()
            .ok_or_else(|| String::from("StaticFiles lookup-path observation must be an object"))?;
        fields
            .entry(String::from("lookup_error"))
            .or_insert(Value::Null);
        observation
    } else {
        observation
    };
    drop(temporary_directory);
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": STATIC_FILES_LOOKUP_PATH_OPERATION,
            "status": "ok",
            "value": observation,
        }],
    }))
}

fn static_files_lookup_path_value(value: &Value) -> Result<OsString, String> {
    match value {
        Value::String(path) => Ok(OsString::from(path)),
        Value::Object(_) => {
            let value = exact_object(
                value,
                &["encoding", "data"],
                "StaticFiles lookup-path encoded path",
            )?;
            let encoding = string_field(value, "encoding", "StaticFiles lookup-path encoding")?;
            if encoding != "filesystem-bytes-base64" {
                return Err(String::from(
                    "StaticFiles lookup-path encoding must be filesystem-bytes-base64",
                ));
            }
            let encoded = string_field(value, "data", "StaticFiles lookup-path encoded data")?;
            let bytes = decode_base64(encoded, "StaticFiles lookup-path encoded data")?;
            #[cfg(unix)]
            {
                Ok(OsString::from_vec(bytes))
            }
            #[cfg(not(unix))]
            {
                String::from_utf8(bytes)
                    .map(OsString::from)
                    .map_err(|_| String::from("filesystem path bytes are not valid UTF-8"))
            }
        }
        _ => Err(String::from(
            "StaticFiles lookup-path must be a string or tagged filesystem-byte value",
        )),
    }
}

fn parse_static_files_actions_before(
    call: &Map<String, Value>,
    file_inputs: &[Value],
    context: &str,
) -> Result<Vec<PathBuf>, String> {
    let Some(actions) = call.get("filesystem_actions_before") else {
        return Ok(Vec::new());
    };
    let actions = actions
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    let declared_paths = file_inputs
        .iter()
        .map(|file_input| {
            let file_input = exact_object(
                file_input,
                &["path", "contents_base64", "mtime_seconds"],
                "StaticFiles file",
            )?;
            let path = string_field(file_input, "path", "StaticFiles file")?;
            if path.contains('\0') || !is_static_workspace_relative(Path::new(path)) {
                return Err(String::from(
                    "StaticFiles file path must be a safe relative path",
                ));
            }
            Ok(path.to_owned())
        })
        .collect::<Result<Vec<_>, String>>()?;

    actions
        .iter()
        .enumerate()
        .map(|(index, action)| {
            let action_context = format!("{context}[{index}]");
            let action = exact_object(action, &["operation", "path"], &action_context)?;
            if string_field(action, "operation", &action_context)? != "unlink" {
                return Err(format!(
                    "{action_context}.operation must be the declared `unlink` action"
                ));
            }
            let path = string_field(action, "path", &action_context)?;
            let relative_path = Path::new(path);
            if path.contains('\0') || !is_static_workspace_relative(relative_path) {
                return Err(format!(
                    "{action_context}.path must be a safe relative path"
                ));
            }
            if !declared_paths
                .iter()
                .any(|declared_path| declared_path.as_str() == path)
            {
                return Err(format!(
                    "{action_context}.path must name a declared StaticFiles file input"
                ));
            }
            Ok(relative_path.to_path_buf())
        })
        .collect()
}

fn run_static_files_case(case: &Value) -> Result<Value, String> {
    let request_sequence = case.get("calls").is_some();
    let mut expected_fields = vec![
        "case_id",
        "surface",
        "operation",
        "covers",
        "target_profiles",
        "assets",
        "directory",
        "path_limit_stress",
        "permission_denial_stress",
        "filesystem",
        "packages",
        "files",
        "html",
        "check_dir",
        "follow_symlink",
        "observations",
    ];
    if request_sequence {
        expected_fields.push("calls");
    } else {
        expected_fields.extend(["scope", "incoming", "send"]);
    }
    let case = exact_object(case, &expected_fields, "StaticFiles asgi-call case")?;
    let case_id = string_field(case, "case_id", "StaticFiles asgi-call case")?;
    if string_field(case, "surface", "StaticFiles asgi-call case")? != STATIC_FILES_SURFACE
        || string_field(case, "operation", "StaticFiles asgi-call case")? != RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
        || (!request_sequence && case.get("incoming") != Some(&json!([])))
    {
        return Err(String::from(
            "case is outside the StaticFiles ASGI-call contract",
        ));
    }
    let call_inputs: Vec<&Map<String, Value>> = if request_sequence {
        let calls = case
            .get("calls")
            .and_then(Value::as_array)
            .filter(|calls| calls.len() >= 2)
            .ok_or_else(|| String::from("StaticFiles calls must contain at least two requests"))?;
        calls
            .iter()
            .map(|call| {
                let expected_fields: &[&str] = if call.get("filesystem_actions_before").is_some() {
                    &["scope", "incoming", "send", "filesystem_actions_before"]
                } else {
                    &["scope", "incoming", "send"]
                };
                let call = exact_object(call, expected_fields, "StaticFiles call")?;
                if call.get("incoming") != Some(&json!([])) {
                    return Err(String::from(
                        "StaticFiles call incoming input must be empty",
                    ));
                }
                validate_capture_send(
                    call.get("send")
                        .ok_or_else(|| String::from("StaticFiles call send input is missing"))?,
                )?;
                Ok(call)
            })
            .collect::<Result<Vec<_>, String>>()?
    } else {
        validate_capture_send(
            case.get("send")
                .ok_or_else(|| String::from("StaticFiles ASGI-call send input is missing"))?,
        )?;
        vec![case]
    };
    validate_string_array(case, "covers", "StaticFiles covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "StaticFiles target_profiles",
        false,
    )?;
    let directory_name = string_field(case, "directory", "StaticFiles case")?;
    if directory_name.is_empty()
        || directory_name == "."
        || directory_name == ".."
        || directory_name.contains('/')
        || directory_name.contains('\\')
    {
        return Err(String::from(
            "StaticFiles directory must be a relative basename",
        ));
    }
    let html = case
        .get("html")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles html must be boolean"))?;
    let check_dir = case
        .get("check_dir")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles check_dir must be boolean"))?;
    let follow_symlink = case
        .get("follow_symlink")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles follow_symlink must be boolean"))?;
    let path_limit_stress = parse_static_files_path_limit_stress(case)?;
    let permission_denial_stress = parse_static_files_permission_denial_stress(case)?;
    if path_limit_stress.is_some() && permission_denial_stress.is_some() {
        return Err(String::from(
            "StaticFiles path-limit and permission stress are mutually exclusive",
        ));
    }
    let file_inputs = case
        .get("files")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles files must be an array"))?;
    let package_inputs = case
        .get("packages")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles packages must be an array"))?;
    let filesystem_actions_before = call_inputs
        .iter()
        .enumerate()
        .map(|(index, call)| {
            parse_static_files_actions_before(
                call,
                file_inputs,
                &format!("StaticFiles call {index} filesystem_actions_before"),
            )
        })
        .collect::<Result<Vec<_>, _>>()?;
    let filesystem = case
        .get("filesystem")
        .ok_or_else(|| String::from("StaticFiles filesystem input is missing"))?;
    if request_sequence
        && (!filesystem.is_null()
            || path_limit_stress.is_some()
            || permission_denial_stress.is_some())
    {
        return Err(String::from(
            "StaticFiles call sequences do not combine with filesystem or stress inputs",
        ));
    }
    let null_path = call_inputs.iter().any(|call| {
        call.get("scope")
            .and_then(|scope| scope.get("path"))
            .and_then(Value::as_str)
            .is_some_and(|path| path.contains('\0'))
    });
    if file_inputs.is_empty() && package_inputs.is_empty() && filesystem.is_null() && !null_path {
        return Err(String::from(
            "StaticFiles must configure an asset or filesystem input unless the input path contains a NUL byte",
        ));
    }
    let (temporary_directory, root, package_roots) = if filesystem.is_null() {
        create_static_files_input(directory_name, file_inputs, package_inputs)?
    } else {
        if !package_inputs.is_empty() {
            return Err(String::from(
                "StaticFiles filesystem input cannot be combined with package roots",
            ));
        }
        let (temporary_directory, root) =
            create_static_files_lookup_path_input(directory_name, file_inputs, filesystem)?;
        (temporary_directory, root, Vec::new())
    };

    let first_call = call_inputs
        .first()
        .ok_or_else(|| String::from("StaticFiles ASGI-call has no requests"))?;
    let (_, _, scope_path, root_path) = validated_static_files_scope(
        first_call
            .get("scope")
            .ok_or_else(|| String::from("StaticFiles ASGI-call scope is missing"))?,
    )?;
    let path = NativeStaticFiles::get_path(&scope_path, &root_path);
    let request_path = path.to_string_lossy();
    let root = match path_limit_stress {
        Some(stress) => {
            match prepare_static_files_path_limit_stress(
                &root,
                &package_roots,
                &request_path,
                follow_symlink,
                stress,
            )? {
                #[cfg(unix)]
                StaticFilesPathLimitStressSetup::Ready(root) => root,
                StaticFilesPathLimitStressSetup::Skipped(reason) => {
                    return Ok(static_files_skipped_result(case_id, &reason));
                }
            }
        }
        None => root,
    };
    let mut directories = vec![root.clone()];
    directories.extend(package_roots);
    let static_files = NativeStaticFiles::new(
        Some(root.clone()),
        directories,
        html,
        check_dir,
        follow_symlink,
    )
    .map_err(|error| format!("StaticFiles construction failed: {error:?}"))?;
    static_files
        .check_config()
        .map_err(|error| format!("StaticFiles configuration failed: {error:?}"))?;
    let permission_guard: Option<StaticFilesPermissionGuard> =
        if let Some(stress) = permission_denial_stress {
            match prepare_static_files_permission_denial_stress(&root, &request_path, stress)? {
                #[cfg(unix)]
                StaticFilesPermissionDenialStressSetup::Ready(guard) => Some(guard),
                StaticFilesPermissionDenialStressSetup::Skipped(reason) => {
                    return Ok(static_files_skipped_result(case_id, &reason));
                }
            }
        } else {
            None
        };
    let mut request_observations = Vec::with_capacity(call_inputs.len());
    for (call, actions_before) in call_inputs.iter().zip(filesystem_actions_before) {
        for action_path in actions_before {
            fs::remove_file(root.join(&action_path)).map_err(|error| {
                format!(
                    "cannot apply StaticFiles unlink action for {:?}: {error}",
                    action_path
                )
            })?;
        }
        request_observations.push(observe_static_files_call(&static_files, call)?);
    }
    drop(permission_guard);
    drop(temporary_directory);
    if request_sequence {
        return Ok(json!({
            "case_id": case_id,
            "status": "completed",
            "observations": [{
                "step_id": RESPONSE_OPERATION,
                "status": "ok",
                "value": {"requests": request_observations},
            }],
        }));
    }
    let request_observation = request_observations
        .first()
        .ok_or_else(|| String::from("StaticFiles ASGI-call has no response observation"))?;
    let response_status = request_observation
        .get("status")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("StaticFiles response observation has no status"))?;
    let observation_item = match response_status {
        "ok" => json!({
            "step_id": RESPONSE_OPERATION,
            "status": "ok",
            "value": request_observation
                .get("value")
                .ok_or_else(|| String::from("StaticFiles response observation has no value"))?,
        }),
        "error" => json!({
            "step_id": RESPONSE_OPERATION,
            "status": "error",
            "error": request_observation
                .get("error")
                .ok_or_else(|| String::from("StaticFiles error observation has no error"))?,
            "partial_value": request_observation
                .get("partial_value")
                .ok_or_else(|| String::from("StaticFiles error observation has no partial value"))?,
        }),
        _ => {
            return Err(String::from(
                "StaticFiles response observation status is invalid",
            ));
        }
    };
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [observation_item],
    }))
}

fn observe_static_files_call(
    static_files: &NativeStaticFiles,
    request: &Map<String, Value>,
) -> Result<Value, String> {
    let (scope, pathsend_extension, scope_path, root_path) = validated_static_files_scope(
        request
            .get("scope")
            .ok_or_else(|| String::from("StaticFiles call scope is missing"))?,
    )?;
    let method = string_field(&scope, "method", "StaticFiles HTTP scope")?;
    let request_headers = parse_scope_request_headers(&scope, "StaticFiles HTTP scope")?;
    let path = NativeStaticFiles::get_path(&scope_path, &root_path);
    let selected = match static_files.get_response(&path, &scope_path, method, &request_headers) {
        Ok(selected) => selected,
        Err(StaticFilesError::MethodNotAllowed) => {
            return Ok(static_files_call_error_observation(
                405,
                "Method Not Allowed",
            ));
        }
        Err(StaticFilesError::NotFound) => {
            return Ok(static_files_call_error_observation(404, "Not Found"));
        }
        Err(StaticFilesError::PermissionDenied) => {
            return Ok(static_files_call_error_observation(401, "Unauthorized"));
        }
        Err(error) => return Err(format!("StaticFiles request failed: {error:?}")),
    };

    let (response_status, ordered_headers, response_bytes, events) = match selected {
        StaticFilesResponse::File { file, status_code } => {
            let response = NativeFileResponse::new(
                file.path.clone(),
                file.path.to_string_lossy().into_owned(),
                status_code,
                &[],
                FileResponseOptions {
                    stat_override: Some(file.metadata),
                    ..FileResponseOptions::default()
                },
            )
            .map_err(|error| format!("StaticFiles file response construction failed: {error}"))?;
            let mut call = response
                .call_state("http", method, &request_headers, pathsend_extension, false)
                .map_err(|error| {
                    format!("StaticFiles file response preparation failed: {error}")
                })?;
            let mut status = None;
            let mut headers = Vec::new();
            let mut body = Vec::new();
            let mut events = Vec::new();
            loop {
                match call.step().map_err(|error| error.to_string())? {
                    FileResponseCallStep::Send(event) => {
                        match &event {
                            FileResponseEvent::Start {
                                status_code,
                                headers: response_headers,
                            } => {
                                status = Some(*status_code);
                                headers = canonical_headers(response_headers);
                            }
                            FileResponseEvent::Body { body: chunk, .. } => {
                                body.extend_from_slice(chunk);
                            }
                            FileResponseEvent::Pathsend { .. } => {}
                        }
                        events.push(canonical_file_response_event(event, false));
                        call.advance(FileResponseCallInput::<String>::Send(Ok(())))
                            .map_err(|error| {
                                format!("StaticFiles file response transition failed: {error:?}")
                            })?;
                    }
                    FileResponseCallStep::RunBackground => {
                        return Err(String::from(
                            "StaticFiles adapter has no background callback to execute",
                        ));
                    }
                    FileResponseCallStep::Complete => break,
                    FileResponseCallStep::Failed => {
                        return Err(String::from(
                            "StaticFiles file response reached a failed state",
                        ));
                    }
                }
            }
            (status, headers, body, events)
        }
        StaticFilesResponse::NotModified { headers } => {
            let response = Response::from_parts(304, Vec::new(), headers);
            let events = response
                .asgi_events()
                .into_iter()
                .map(canonical_response_event)
                .collect::<Vec<_>>();
            (
                Some(response.status_code()),
                canonical_headers(response.headers()),
                response.body().to_vec(),
                events,
            )
        }
        StaticFilesResponse::Redirect { path } => {
            let query = decode_base64(
                string_field(&scope, "query_string_base64", "StaticFiles HTTP scope")?,
                "StaticFiles HTTP scope query_string_base64",
            )?;
            let headers = parse_scope_request_headers(&scope, "StaticFiles HTTP scope")?;
            let server = scope.get("server").and_then(Value::as_array);
            let server = server.and_then(|values| {
                Some((
                    values.first()?.as_str()?,
                    u16::try_from(values.get(1)?.as_u64()?).ok()?,
                ))
            });
            let redirect_path = path.to_string_lossy();
            let url = connection_url(
                scope.get("scheme").and_then(Value::as_str),
                &redirect_path,
                &query,
                &headers,
                server,
            )
            .map_err(|error| format!("StaticFiles redirect URL failed: {error}"))?;
            let response = Response::redirect(&url, 307, &[])
                .map_err(|error| format!("StaticFiles redirect response failed: {error}"))?;
            let events = response
                .asgi_events()
                .into_iter()
                .map(canonical_response_event)
                .collect::<Vec<_>>();
            (
                Some(response.status_code()),
                canonical_headers(response.headers()),
                response.body().to_vec(),
                events,
            )
        }
    };
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    Ok(json!({
        "status": "ok",
        "value": {
            "response_status": response_status,
            "ordered_repeated_headers": ordered_headers,
            "response_bytes": {"encoding": "base64", "data": encode_base64(&response_bytes)},
            "asgi_event_order": event_order,
            "asgi_events": events,
        },
    }))
}

fn static_files_call_error_observation(status_code: u16, detail: &str) -> Value {
    json!({
        "status": "error",
        "error": {
            "class": "starlette.exceptions.HTTPException",
            "kind": "exception",
            "message": format!("{status_code}: {detail}"),
            "stage": "dispatch",
            "code": status_code,
            "cause": null,
            "suppress_context": false,
        },
        "partial_value": {
            "response_status": null,
            "ordered_repeated_headers": [],
            "response_bytes": {"encoding": "base64", "data": ""},
            "asgi_event_order": [],
            "asgi_events": [],
        },
    })
}

fn parse_static_files_path_limit_stress(
    case: &Map<String, Value>,
) -> Result<Option<StaticFilesPathLimitStress>, String> {
    let Some(value) = case.get("path_limit_stress") else {
        return Err(String::from(
            "StaticFiles path_limit_stress field is missing",
        ));
    };
    if value.is_null() {
        return Ok(None);
    }
    let stress = exact_object(
        value,
        &[
            "kind",
            "overflow_bytes",
            "later_root_margin_bytes",
            "safe_component_bytes",
        ],
        "StaticFiles path_limit_stress",
    )?;
    if string_field(stress, "kind", "StaticFiles path_limit_stress")?
        != "ordered-root-path-overflow"
    {
        return Err(String::from(
            "StaticFiles path_limit_stress kind is unsupported",
        ));
    }
    let positive_usize = |name: &str, maximum: u64| -> Result<usize, String> {
        let value = stress
            .get(name)
            .and_then(Value::as_u64)
            .filter(|value| (1..=maximum).contains(value))
            .and_then(|value| usize::try_from(value).ok())
            .ok_or_else(|| format!("StaticFiles path_limit_stress.{name} is invalid"))?;
        Ok(value)
    };
    Ok(Some(StaticFilesPathLimitStress {
        overflow_bytes: positive_usize("overflow_bytes", 128)?,
        later_root_margin_bytes: positive_usize("later_root_margin_bytes", 1024)?,
        safe_component_bytes: positive_usize("safe_component_bytes", 255)?,
    }))
}

fn parse_static_files_permission_denial_stress(
    case: &Map<String, Value>,
) -> Result<Option<StaticFilesPermissionDenialStress>, String> {
    let Some(value) = case.get("permission_denial_stress") else {
        return Err(String::from(
            "StaticFiles permission_denial_stress field is missing",
        ));
    };
    if value.is_null() {
        return Ok(None);
    }
    let stress = exact_object(
        value,
        &["kind", "mode"],
        "StaticFiles permission_denial_stress",
    )?;
    if string_field(stress, "kind", "StaticFiles permission_denial_stress")?
        != "permission-denied-root"
    {
        return Err(String::from(
            "StaticFiles permission_denial_stress kind is unsupported",
        ));
    }
    let mode = stress
        .get("mode")
        .and_then(Value::as_u64)
        .filter(|mode| *mode <= 0o777 && *mode & 0o100 == 0)
        .and_then(|mode| u32::try_from(mode).ok())
        .ok_or_else(|| String::from("StaticFiles permission_denial_stress.mode is invalid"))?;
    Ok(Some(StaticFilesPermissionDenialStress { mode }))
}

#[cfg(unix)]
fn prepare_static_files_permission_denial_stress(
    root: &Path,
    request_path: &str,
    stress: StaticFilesPermissionDenialStress,
) -> Result<StaticFilesPermissionDenialStressSetup, String> {
    let original_permissions = fs::metadata(root)
        .map_err(|error| format!("cannot read StaticFiles root permissions: {error}"))?
        .permissions();
    let guard = StaticFilesPermissionDenialGuard {
        path: root.to_path_buf(),
        original_permissions,
    };
    if let Err(error) = fs::set_permissions(root, fs::Permissions::from_mode(stress.mode)) {
        drop(guard);
        return Ok(StaticFilesPermissionDenialStressSetup::Skipped(format!(
            "the temporary filesystem cannot apply the declared directory mode: {error}"
        )));
    }

    match fs::metadata(root.join(request_path)) {
        Err(error) if error.kind() == io::ErrorKind::PermissionDenied => {
            Ok(StaticFilesPermissionDenialStressSetup::Ready(guard))
        }
        Ok(_) => {
            drop(guard);
            Ok(StaticFilesPermissionDenialStressSetup::Skipped(
                "the current process can still traverse the permission-restricted root".to_owned(),
            ))
        }
        Err(error) => {
            drop(guard);
            Err(format!(
                "cannot verify StaticFiles permission fixture: {error}"
            ))
        }
    }
}

#[cfg(not(unix))]
fn prepare_static_files_permission_denial_stress(
    _root: &Path,
    _request_path: &str,
    stress: StaticFilesPermissionDenialStress,
) -> Result<StaticFilesPermissionDenialStressSetup, String> {
    let _mode = stress.mode;
    Ok(StaticFilesPermissionDenialStressSetup::Skipped(
        "permission_denial_stress requires Unix permission bits".to_owned(),
    ))
}

#[cfg(unix)]
fn prepare_static_files_path_limit_stress(
    root: &Path,
    package_roots: &[PathBuf],
    request_path: &str,
    follow_symlink: bool,
    stress: StaticFilesPathLimitStress,
) -> Result<StaticFilesPathLimitStressSetup, String> {
    let relative_path = Path::new(request_path);
    if request_path.is_empty()
        || relative_path.is_absolute()
        || request_path
            .split('/')
            .any(|component| component.is_empty() || matches!(component, "." | ".."))
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "StaticFiles path_limit_stress request path is not normalized and relative".to_owned(),
        ));
    }

    let workspace = root.parent().unwrap_or(root);
    let Some(path_max) = pathconf_limit(workspace, libc::_PC_PATH_MAX) else {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "Unix _PC_PATH_MAX is unavailable".to_owned(),
        ));
    };
    let Some(name_max) = pathconf_limit(workspace, libc::_PC_NAME_MAX) else {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "Unix _PC_NAME_MAX is unavailable for the temporary workspace".to_owned(),
        ));
    };
    let component_limit = stress.safe_component_bytes.min(name_max);
    if component_limit == 0 || !static_files_relative_components_fit(request_path, component_limit)
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the request path cannot fit the declared safe component limit".to_owned(),
        ));
    }

    let mut later_candidate = None;
    for package_root in package_roots {
        let joined_candidate = package_root.join(relative_path);
        let metadata = match fs::metadata(&joined_candidate) {
            Ok(metadata) => metadata,
            Err(error)
                if error.kind() == io::ErrorKind::NotFound
                    || error.kind() == io::ErrorKind::NotADirectory =>
            {
                continue;
            }
            Err(error) => {
                return Err(format!(
                    "cannot inspect later StaticFiles package candidate: {error}"
                ));
            }
        };
        if !metadata.is_file() {
            continue;
        }
        let candidate =
            match static_files_path_candidate(package_root, relative_path, follow_symlink) {
                Ok(candidate) => candidate,
                Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
                Err(error) => {
                    return Err(format!(
                        "cannot resolve later StaticFiles package candidate: {error}"
                    ));
                }
            };
        later_candidate = Some(candidate);
        break;
    }
    let Some(later_candidate) = later_candidate else {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "no later package root contains the requested regular file".to_owned(),
        ));
    };
    if !static_files_path_components_fit(&later_candidate, component_limit) {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "a later package path component exceeds the declared safe component limit".to_owned(),
        ));
    }
    let later_candidate_bytes = later_candidate.as_os_str().as_bytes().len();
    if path_max
        .checked_sub(stress.later_root_margin_bytes)
        .is_none_or(|limit| later_candidate_bytes > limit)
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "later package-root candidate is too close to _PC_PATH_MAX".to_owned(),
        ));
    }

    let requested_candidate_bytes = path_max
        .checked_add(stress.overflow_bytes)
        .ok_or_else(|| String::from("StaticFiles path limit calculation overflowed"))?;
    let lexical_first_root = match static_files_absolute_path(root) {
        Ok(candidate) => candidate,
        Err(error) => {
            return Err(format!(
                "cannot make initial StaticFiles root absolute: {error}"
            ));
        }
    };
    let resolved_first_root = if follow_symlink {
        lexical_first_root.clone()
    } else {
        match fs::canonicalize(root) {
            Ok(candidate) => candidate,
            Err(error) => {
                return Err(format!("cannot resolve initial StaticFiles root: {error}"));
            }
        }
    };
    let lexical_first_candidate = lexical_first_root.join(relative_path);
    let resolved_first_candidate = resolved_first_root.join(relative_path);
    if !static_files_path_components_fit(&lexical_first_candidate, component_limit)
        || !static_files_path_components_fit(&resolved_first_candidate, component_limit)
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the configured first-root path exceeds the declared safe component limit".to_owned(),
        ));
    }
    let first_candidate_bytes = lexical_first_candidate
        .as_os_str()
        .as_bytes()
        .len()
        .min(resolved_first_candidate.as_os_str().as_bytes().len());
    let Some(padding_bytes) = requested_candidate_bytes.checked_sub(first_candidate_bytes) else {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the unpadded first-root candidate already exceeds the overflow target".to_owned(),
        ));
    };
    let Some(padding) = static_files_path_padding(padding_bytes, component_limit) else {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the first-root overflow cannot be represented with safe path components".to_owned(),
        ));
    };
    let padded_root = if padding_bytes == 0 {
        root.to_path_buf()
    } else {
        root.join(&padding)
    };
    let padded_lexical_root = match static_files_absolute_path(&padded_root) {
        Ok(candidate) => candidate,
        Err(error) => {
            return Err(format!(
                "cannot make padded StaticFiles root absolute: {error}"
            ));
        }
    };
    let padded_resolved_root = if follow_symlink {
        padded_lexical_root.clone()
    } else if padding_bytes == 0 {
        resolved_first_root
    } else {
        resolved_first_root.join(&padding)
    };
    let padded_lexical_candidate = padded_lexical_root.join(relative_path);
    let padded_resolved_candidate = padded_resolved_root.join(relative_path);
    let lexical_candidate_bytes = padded_lexical_candidate.as_os_str().as_bytes().len();
    let resolved_candidate_bytes = padded_resolved_candidate.as_os_str().as_bytes().len();
    if lexical_candidate_bytes.min(resolved_candidate_bytes) != requested_candidate_bytes
        || lexical_candidate_bytes <= path_max
        || resolved_candidate_bytes <= path_max
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the lexical and resolved first-root candidates cannot both exceed _PC_PATH_MAX at the declared margin".to_owned(),
        ));
    }
    if !static_files_path_components_fit(&padded_lexical_candidate, component_limit)
        || !static_files_path_components_fit(&padded_resolved_candidate, component_limit)
    {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the padded first-root candidate exceeds the declared safe component limit".to_owned(),
        ));
    }
    let lexical_root_bytes = padded_lexical_root.as_os_str().as_bytes().len();
    let resolved_root_bytes = padded_resolved_root.as_os_str().as_bytes().len();
    if lexical_root_bytes > path_max || resolved_root_bytes > path_max {
        return Ok(StaticFilesPathLimitStressSetup::Skipped(
            "the lexical or resolved padded first root itself exceeds _PC_PATH_MAX".to_owned(),
        ));
    }

    if let Err(error) = fs::create_dir_all(&padded_root) {
        if error.raw_os_error() == Some(libc::ENAMETOOLONG) {
            return Ok(StaticFilesPathLimitStressSetup::Skipped(
                "the padded first root cannot be created within the workspace path limit"
                    .to_owned(),
            ));
        }
        return Err(format!("cannot create StaticFiles padded root: {error}"));
    }

    Ok(StaticFilesPathLimitStressSetup::Ready(padded_root))
}

#[cfg(not(unix))]
fn prepare_static_files_path_limit_stress(
    _root: &Path,
    _package_roots: &[PathBuf],
    _request_path: &str,
    _follow_symlink: bool,
    _stress: StaticFilesPathLimitStress,
) -> Result<StaticFilesPathLimitStressSetup, String> {
    let _declared_limits = (
        _stress.overflow_bytes,
        _stress.later_root_margin_bytes,
        _stress.safe_component_bytes,
    );
    Ok(StaticFilesPathLimitStressSetup::Skipped(
        "path_limit_stress requires Unix pathconf support".to_owned(),
    ))
}

#[cfg(unix)]
fn static_files_relative_components_fit(path: &str, component_limit: usize) -> bool {
    !path.is_empty()
        && path.split('/').all(|component| {
            !component.is_empty()
                && !matches!(component, "." | "..")
                && component.len() <= component_limit
        })
}

#[cfg(unix)]
fn static_files_path_components_fit(path: &Path, component_limit: usize) -> bool {
    path.components().all(|component| match component {
        std::path::Component::RootDir => true,
        std::path::Component::Normal(name) => name.as_bytes().len() <= component_limit,
        std::path::Component::CurDir
        | std::path::Component::ParentDir
        | std::path::Component::Prefix(_) => false,
    })
}

#[cfg(unix)]
fn static_files_path_candidate(
    root: &Path,
    relative_path: &Path,
    follow_symlink: bool,
) -> io::Result<PathBuf> {
    let joined_path = root.join(relative_path);
    if follow_symlink {
        return static_files_absolute_path(&joined_path);
    }
    fs::canonicalize(joined_path)
}

#[cfg(unix)]
fn static_files_absolute_path(path: &Path) -> io::Result<PathBuf> {
    let absolute_path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        env::current_dir()?.join(path)
    };
    let mut normalized_path = PathBuf::new();
    for component in absolute_path.components() {
        match component {
            std::path::Component::RootDir => normalized_path.push(component.as_os_str()),
            std::path::Component::Normal(name) => normalized_path.push(name),
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                normalized_path.pop();
            }
            std::path::Component::Prefix(_) => {}
        }
    }
    Ok(normalized_path)
}

#[cfg(unix)]
// LINT EXCEPTION: POSIX pathconf supplies the filesystem component limit needed by this parity probe.
#[allow(unsafe_code)]
fn pathconf_limit(path: &Path, name: libc::c_int) -> Option<usize> {
    let path = CString::new(path.as_os_str().as_bytes()).ok()?;
    // SAFETY: `path` is a live NUL-terminated CString for the immediate call;
    // pathconf reads the borrowed path synchronously and retains no pointer.
    let value = unsafe { libc::pathconf(path.as_ptr(), name) };
    usize::try_from(value).ok().filter(|limit| *limit > 0)
}

#[cfg(unix)]
fn static_files_path_padding(byte_length: usize, component_limit: usize) -> Option<PathBuf> {
    if byte_length == 0 {
        return Some(PathBuf::new());
    }
    if component_limit == 0 {
        return None;
    }
    let maximum_component_cost = component_limit.checked_add(1)?;
    let mut remaining = byte_length;
    let mut padding = PathBuf::new();
    while remaining > 0 {
        if remaining == 1 {
            return None;
        }
        let mut component_cost = remaining.min(maximum_component_cost);
        if remaining.checked_sub(component_cost) == Some(1) {
            if component_cost <= 2 {
                return None;
            }
            component_cost = component_cost.checked_sub(1)?;
        }
        let component_bytes = component_cost.checked_sub(1)?;
        padding.push("p".repeat(component_bytes));
        remaining = remaining.checked_sub(component_cost)?;
    }
    Some(padding)
}

fn static_files_skipped_result(case_id: &str, reason: &str) -> Value {
    json!({
        "case_id": case_id,
        "status": "skipped",
        "observations": [{
            "step_id": RESPONSE_OPERATION,
            "status": "skipped",
            "reason": reason,
        }],
    })
}

fn create_static_files_input(
    directory_name: &str,
    file_inputs: &[Value],
    package_inputs: &[Value],
) -> Result<(FileResponseTempDirectory, PathBuf, Vec<PathBuf>), String> {
    let temporary_root = env::temp_dir();
    for _ in 0..128 {
        let sequence = NEXT_FILE_RESPONSE_TEMP.fetch_add(1, Ordering::Relaxed);
        let directory = temporary_root.join(format!(
            "starlette-rs-static-files-{}-{sequence}",
            std::process::id()
        ));
        match fs::create_dir(&directory) {
            Ok(()) => {
                let guard = FileResponseTempDirectory(directory.clone());
                let root = directory.join(directory_name);
                fs::create_dir_all(&root)
                    .map_err(|error| format!("cannot create StaticFiles root: {error}"))?;
                for file_input in file_inputs {
                    write_static_asset(&root, file_input, "StaticFiles file")?;
                }
                let package_source_root = directory.join("package-source");
                fs::create_dir_all(&package_source_root).map_err(|error| {
                    format!("cannot create StaticFiles package source root: {error}")
                })?;
                let mut package_roots = Vec::new();
                for package_input in package_inputs {
                    let package = exact_object(
                        package_input,
                        &["name", "statics_dir", "files"],
                        "StaticFiles package input",
                    )?;
                    let package_name = string_field(package, "name", "StaticFiles package")?;
                    let mut package_path = package_source_root.clone();
                    for component in package_name.split('.') {
                        if component.is_empty()
                            || !component.chars().all(|character| {
                                character.is_ascii_alphanumeric() || character == '_'
                            })
                        {
                            return Err(String::from("StaticFiles package name is invalid"));
                        }
                        package_path.push(component);
                        fs::create_dir_all(&package_path).map_err(|error| {
                            format!("cannot create StaticFiles package directory: {error}")
                        })?;
                        fs::write(package_path.join("__init__.py"), b"").map_err(|error| {
                            format!("cannot create StaticFiles package initializer: {error}")
                        })?;
                    }
                    let statics_dir = string_field(package, "statics_dir", "StaticFiles package")?;
                    let relative_statics = Path::new(statics_dir);
                    if relative_statics.is_absolute()
                        || relative_statics
                            .components()
                            .any(|component| matches!(component, std::path::Component::ParentDir))
                    {
                        return Err(String::from("StaticFiles package directory is invalid"));
                    }
                    let package_root = package_path.join(relative_statics);
                    fs::create_dir_all(&package_root).map_err(|error| {
                        format!("cannot create StaticFiles package asset root: {error}")
                    })?;
                    let package_files =
                        package
                            .get("files")
                            .and_then(Value::as_array)
                            .ok_or_else(|| {
                                String::from("StaticFiles package files must be an array")
                            })?;
                    for file_input in package_files {
                        write_static_asset(&package_root, file_input, "StaticFiles package file")?;
                    }
                    package_roots.push(package_root);
                }
                return Ok((guard, root, package_roots));
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "cannot create isolated StaticFiles inputs: {error}"
                ));
            }
        }
    }
    Err(String::from(
        "cannot allocate an isolated StaticFiles input directory",
    ))
}

fn create_static_files_lookup_path_input(
    directory_name: &str,
    file_inputs: &[Value],
    filesystem: &Value,
) -> Result<(FileResponseTempDirectory, PathBuf), String> {
    let filesystem = exact_object(
        filesystem,
        &[
            "root_symlink_target",
            "directories",
            "outside_files",
            "symlinks",
        ],
        "StaticFiles lookup-path filesystem",
    )?;
    let root_symlink_target = match filesystem.get("root_symlink_target") {
        Some(Value::Null) => None,
        Some(Value::String(target)) => Some(target.as_str()),
        _ => {
            return Err(String::from(
                "StaticFiles lookup-path root_symlink_target must be a path or null",
            ));
        }
    };
    let directories = filesystem
        .get("directories")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles lookup-path directories must be an array"))?;
    let outside_files = filesystem
        .get("outside_files")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles lookup-path outside_files must be an array"))?;
    let symlinks = filesystem
        .get("symlinks")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles lookup-path symlinks must be an array"))?;

    if directory_name.is_empty()
        || directory_name == "."
        || directory_name == ".."
        || directory_name.contains('/')
        || directory_name.contains('\\')
    {
        return Err(String::from(
            "StaticFiles lookup-path directory must be a relative basename",
        ));
    }

    let temporary_root = env::temp_dir();
    for _ in 0..128 {
        let sequence = NEXT_FILE_RESPONSE_TEMP.fetch_add(1, Ordering::Relaxed);
        let workspace = temporary_root.join(format!(
            "starlette-rs-static-lookup-{}-{sequence}",
            std::process::id()
        ));
        match fs::create_dir(&workspace) {
            Ok(()) => {
                let guard = FileResponseTempDirectory(workspace.clone());
                let configured_root = Path::new(directory_name);
                let mut deferred_directories = Vec::new();
                for directory in directories {
                    let directory = directory.as_str().ok_or_else(|| {
                        String::from("StaticFiles lookup-path directory path must be a string")
                    })?;
                    let relative = Path::new(directory);
                    if !is_static_workspace_relative(relative) {
                        return Err(String::from(
                            "StaticFiles lookup-path directory escaped its workspace",
                        ));
                    }
                    if root_symlink_target.is_some() && relative.starts_with(configured_root) {
                        deferred_directories.push(workspace.join(relative));
                    } else {
                        fs::create_dir_all(workspace.join(relative)).map_err(|error| {
                            format!("cannot create StaticFiles lookup-path directory: {error}")
                        })?;
                    }
                }

                let root = workspace.join(configured_root);
                if let Some(target) = root_symlink_target {
                    let relative_target = Path::new(target);
                    if !is_static_workspace_relative(relative_target) {
                        return Err(String::from(
                            "StaticFiles lookup-path root symlink target escaped its workspace",
                        ));
                    }
                    fs::create_dir_all(workspace.join(relative_target)).map_err(|error| {
                        format!("cannot create StaticFiles lookup-path root target: {error}")
                    })?;
                    create_path_symlink(relative_target, &root, true).map_err(|error| {
                        format!("cannot create StaticFiles lookup-path root symlink: {error}")
                    })?;
                } else {
                    fs::create_dir_all(&root).map_err(|error| {
                        format!("cannot create StaticFiles lookup-path root: {error}")
                    })?;
                }

                for directory in deferred_directories {
                    fs::create_dir_all(directory).map_err(|error| {
                        format!("cannot create StaticFiles lookup-path directory: {error}")
                    })?;
                }
                for file_input in file_inputs {
                    write_static_lookup_asset(&root, file_input, "StaticFiles lookup-path file")?;
                }
                for file_input in outside_files {
                    write_static_asset(
                        &workspace,
                        file_input,
                        "StaticFiles lookup-path outside file",
                    )?;
                }
                for symlink in symlinks {
                    let symlink = exact_object(
                        symlink,
                        &["path", "target"],
                        "StaticFiles lookup-path symlink",
                    )?;
                    let relative_link =
                        string_field(symlink, "path", "StaticFiles lookup-path symlink")?;
                    let relative_link = Path::new(relative_link);
                    if !is_static_workspace_relative(relative_link) {
                        return Err(String::from(
                            "StaticFiles lookup-path symlink path escaped its root",
                        ));
                    }
                    let target =
                        string_field(symlink, "target", "StaticFiles lookup-path symlink")?;
                    let link = root.join(relative_link);
                    if let Some(parent) = link.parent() {
                        fs::create_dir_all(parent).map_err(|error| {
                            format!("cannot create StaticFiles lookup-path symlink parent: {error}")
                        })?;
                    }
                    let target_path = link.parent().unwrap_or(&root).join(Path::new(target));
                    let target_is_directory = fs::metadata(&target_path)
                        .map_err(|error| {
                            format!(
                                "cannot inspect StaticFiles lookup-path symlink target: {error}"
                            )
                        })?
                        .is_dir();
                    create_path_symlink(Path::new(target), &link, target_is_directory).map_err(
                        |error| format!("cannot create StaticFiles lookup-path symlink: {error}"),
                    )?;
                }
                return Ok((guard, root));
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "cannot allocate isolated StaticFiles lookup-path inputs: {error}"
                ));
            }
        }
    }
    Err(String::from(
        "cannot allocate an isolated StaticFiles lookup-path input directory",
    ))
}

fn is_static_workspace_relative(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && !path.is_absolute()
        && !path.to_string_lossy().contains('\\')
        && path
            .components()
            .all(|component| matches!(component, std::path::Component::Normal(_)))
}

fn create_path_symlink(target: &Path, link: &Path, is_directory: bool) -> io::Result<()> {
    #[cfg(unix)]
    {
        let _ = is_directory;
        std::os::unix::fs::symlink(target, link)
    }
    #[cfg(windows)]
    {
        if is_directory {
            std::os::windows::fs::symlink_dir(target, link)
        } else {
            std::os::windows::fs::symlink_file(target, link)
        }
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (target, link, is_directory);
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "symbolic links are not supported on this platform",
        ))
    }
}

fn write_static_asset(root: &Path, input: &Value, context: &str) -> Result<(), String> {
    let file_input = exact_object(
        input,
        &["path", "contents_base64", "mtime_seconds"],
        context,
    )?;
    let relative_path = string_field(file_input, "path", context)?;
    write_static_asset_with_relative_path(root, file_input, context, Path::new(relative_path))
}

fn write_static_lookup_asset(root: &Path, input: &Value, context: &str) -> Result<(), String> {
    let file_input = exact_object(
        input,
        &["path", "contents_base64", "mtime_seconds"],
        context,
    )?;
    let path_value = file_input
        .get("path")
        .ok_or_else(|| format!("{context}.path is missing"))?;
    let relative_path = static_files_lookup_path_value(path_value)?;
    write_static_asset_with_relative_path(root, file_input, context, Path::new(&relative_path))
}

fn write_static_asset_with_relative_path(
    root: &Path,
    file_input: &Map<String, Value>,
    context: &str,
    relative: &Path,
) -> Result<(), String> {
    if relative.as_os_str().is_empty()
        || relative.is_absolute()
        || relative
            .components()
            .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return Err(format!("{context} path must remain below its root"));
    }
    let bytes = decode_base64(
        string_field(file_input, "contents_base64", context)?,
        "StaticFiles file contents_base64",
    )?;
    let modified_seconds = file_input
        .get("mtime_seconds")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .ok_or_else(|| String::from("StaticFiles mtime_seconds must be finite"))?;
    let target = root.join(relative);
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create StaticFiles asset parent: {error}"))?;
    }
    fs::write(&target, bytes)
        .map_err(|error| format!("cannot write StaticFiles asset: {error}"))?;
    let timestamp = system_time_from_unix_seconds(modified_seconds)
        .ok_or_else(|| String::from("StaticFiles timestamp is out of range"))?;
    let file = fs::OpenOptions::new()
        .write(true)
        .open(&target)
        .map_err(|error| format!("cannot set StaticFiles asset time: {error}"))?;
    file.set_times(
        std::fs::FileTimes::new()
            .set_accessed(timestamp)
            .set_modified(timestamp),
    )
    .map_err(|error| format!("cannot set StaticFiles asset time: {error}"))
}

fn static_files_relative_path_bytes(path: &Path) -> Vec<u8> {
    let mut bytes = Vec::new();
    for component in path.components() {
        let std::path::Component::Normal(component) = component else {
            continue;
        };
        if !bytes.is_empty() {
            bytes.push(b'/');
        }
        #[cfg(unix)]
        bytes.extend_from_slice(component.as_bytes());
        #[cfg(not(unix))]
        bytes.extend_from_slice(component.to_string_lossy().as_bytes());
    }
    if bytes.is_empty() {
        bytes.push(b'.');
    }
    bytes
}

fn static_files_path_observation(path_bytes: &[u8]) -> Value {
    match std::str::from_utf8(path_bytes) {
        Ok(path) => json!(path),
        Err(_) => json!({
            "encoding": "filesystem-bytes-base64",
            "data": encode_base64(path_bytes),
        }),
    }
}

fn system_time_from_unix_seconds(seconds: f64) -> Option<std::time::SystemTime> {
    if !seconds.is_finite() {
        return None;
    }
    let duration = std::time::Duration::try_from_secs_f64(seconds.abs()).ok()?;
    if seconds < 0.0 {
        std::time::UNIX_EPOCH.checked_sub(duration)
    } else {
        std::time::UNIX_EPOCH.checked_add(duration)
    }
}

fn create_file_response_input(
    file_name: &str,
    contents: &[u8],
) -> Result<(FileResponseTempDirectory, PathBuf), String> {
    let temporary_root = env::temp_dir();
    for _ in 0..128 {
        let sequence = NEXT_FILE_RESPONSE_TEMP.fetch_add(1, Ordering::Relaxed);
        let directory = temporary_root.join(format!(
            "starlette-rs-parity-file-{}-{sequence}",
            std::process::id()
        ));
        match fs::create_dir(&directory) {
            Ok(()) => {
                let guard = FileResponseTempDirectory(directory);
                let path = guard.0.join(file_name);
                fs::write(&path, contents).map_err(|error| {
                    format!("cannot materialize FileResponse input file: {error}")
                })?;
                return Ok((guard, path));
            }
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => {
                return Err(format!(
                    "cannot create isolated FileResponse input directory: {error}"
                ));
            }
        }
    }
    Err(String::from(
        "cannot allocate an isolated FileResponse input directory",
    ))
}

fn run_websocket_state_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "incoming",
            "actions",
            "observations",
        ],
        "WebSocket state-sequence case",
    )?;
    let case_id = string_field(case, "case_id", "WebSocket state-sequence case")?;
    if !case_id.starts_with(&format!("{WEBSOCKET_SURFACE}.{WEBSOCKET_STATE_OPERATION}."))
        || string_field(case, "surface", "WebSocket state-sequence case")? != WEBSOCKET_SURFACE
        || string_field(case, "operation", "WebSocket state-sequence case")?
            != WEBSOCKET_STATE_OPERATION
    {
        return Err(String::from(
            "case ID or operation is outside the WebSocket state sequence",
        ));
    }
    validate_native_package_target_profiles(case, "WebSocket state case")?;
    if case.get("assets") != Some(&json!([])) {
        return Err(String::from("WebSocket state cases must select no assets"));
    }
    let covers = case
        .get("covers")
        .and_then(Value::as_array)
        .filter(|items| !items.is_empty())
        .ok_or_else(|| String::from("WebSocket state case covers must be non-empty"))?;
    if covers.iter().any(|item| item.as_str().is_none()) {
        return Err(String::from(
            "WebSocket state case covers must contain strings",
        ));
    }
    let observations = case
        .get("observations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("WebSocket state case observations must be an array"))?;
    if observations.len() != 1 || observations[0].as_str() != Some(WEBSOCKET_STATE_OPERATION) {
        return Err(String::from(
            "WebSocket observations must select the state-sequence workflow result",
        ));
    }

    validate_websocket_scope(
        case.get("scope")
            .ok_or_else(|| String::from("WebSocket state case misses scope"))?,
    )?;
    let incoming = case
        .get("incoming")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("WebSocket state incoming must be an array"))?;
    for (index, message) in incoming.iter().enumerate() {
        validate_websocket_message(message, &format!("WebSocket state incoming[{index}]"), true)?;
    }
    let actions = case
        .get("actions")
        .and_then(Value::as_array)
        .filter(|actions| !actions.is_empty())
        .ok_or_else(|| String::from("WebSocket state actions must be a non-empty array"))?;

    let mut machine = WebSocketStateMachine::new();
    let mut incoming_index = 0;
    let mut receive_calls = 0;
    let mut action_ids = std::collections::BTreeSet::new();
    let mut action_results = Vec::with_capacity(actions.len());
    for (index, action) in actions.iter().enumerate() {
        let context = format!("WebSocket state actions[{index}]");
        let action_object = action
            .as_object()
            .ok_or_else(|| format!("{context} must be an object"))?;
        let action_id = string_field(action_object, "action_id", &context)?;
        if !action_ids.insert(action_id.to_owned()) {
            return Err(format!("duplicate WebSocket state action ID: {action_id}"));
        }
        let result = match string_field(action_object, "action", &context)? {
            "accept" => {
                exact_keys(action_object, &["action_id", "action"], &context)?;
                let receive_result = if machine.client_state() == WebSocketState::Connecting {
                    checked_usize_increment(&mut receive_calls, "WebSocket receive call count")?;
                    let message = incoming.get(incoming_index).ok_or_else(|| {
                        String::from("WebSocket accept action has no input message")
                    })?;
                    checked_usize_increment(&mut incoming_index, "WebSocket input message index")?;
                    let message_object = message.as_object().ok_or_else(|| {
                        String::from("WebSocket accept input message must be an object")
                    })?;
                    let message_type =
                        string_field(message_object, "type", "WebSocket accept input message")?;
                    machine.receive(message_type)
                } else {
                    Ok(())
                };
                match receive_result {
                    Err(error) => json!({
                        "action_id": action_id,
                        "outcome": "error",
                        "error_class": WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS,
                        "error_message": error.message(),
                    }),
                    Ok(()) => match machine.begin_send("websocket.accept", false) {
                        Err(error) => json!({
                            "action_id": action_id,
                            "outcome": "error",
                            "error_class": WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS,
                            "error_message": error.message(),
                        }),
                        Ok(_) => json!({
                            "action_id": action_id,
                            "outcome": "ok",
                        }),
                    },
                }
            }
            "receive" => {
                exact_keys(action_object, &["action_id", "action"], &context)?;
                let message = if matches!(
                    machine.client_state(),
                    WebSocketState::Connecting | WebSocketState::Connected
                ) {
                    checked_usize_increment(&mut receive_calls, "WebSocket receive call count")?;
                    let message = incoming.get(incoming_index).ok_or_else(|| {
                        String::from("WebSocket state receive action has no input message")
                    })?;
                    checked_usize_increment(&mut incoming_index, "WebSocket input message index")?;
                    Some(message)
                } else {
                    None
                };
                let message_type = message
                    .and_then(|value| value.get("type"))
                    .and_then(Value::as_str)
                    .unwrap_or("websocket.receive");
                match machine.receive(message_type) {
                    Ok(()) if message.is_some() => json!({
                        "action_id": action_id,
                        "outcome": "ok",
                    }),
                    Ok(()) => {
                        return Err(format!(
                            "{context} completed without an input message in a terminal state"
                        ));
                    }
                    Err(error) => json!({
                        "action_id": action_id,
                        "outcome": "error",
                        "error_class": WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS,
                        "error_message": error.message(),
                    }),
                }
            }
            "send" => {
                let mut expected = vec!["action_id", "action", "message"];
                if action_object.contains_key("send_error") {
                    expected.push("send_error");
                }
                exact_keys(action_object, &expected, &context)?;
                let message = action_object
                    .get("message")
                    .ok_or_else(|| format!("{context} misses message"))?;
                let message_object = message
                    .as_object()
                    .ok_or_else(|| format!("{context}.message must be an object"))?;
                if message_object.len() == 1
                    && matches!(message_object.get("type"), Some(Value::Null))
                {
                    exact_keys(message_object, &["type"], &format!("{context}.message"))?;
                    let error = machine.invalid_send_type_error("None");
                    json!({
                        "action_id": action_id,
                        "outcome": "error",
                        "error_class": WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS,
                        "error_message": error.message(),
                    })
                } else {
                    validate_websocket_message(message, &format!("{context}.message"), false)?;
                    let message_type =
                        string_field(message_object, "type", &format!("{context}.message"))?;
                    let more_body = message
                        .get("more_body")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    let send_error = action_object
                        .get("send_error")
                        .map(|raw_error| {
                            let error = exact_object(
                                raw_error,
                                &["kind", "message"],
                                &format!("{context}.send_error"),
                            )?;
                            if string_field(error, "kind", &format!("{context}.send_error"))?
                                != "os-error"
                            {
                                return Err(format!("{context}.send_error.kind must be os-error"));
                            }
                            string_field(error, "message", &format!("{context}.send_error"))
                        })
                        .transpose()?;
                    match machine.begin_send(message_type, more_body) {
                        Err(error) => json!({
                            "action_id": action_id,
                            "outcome": "error",
                            "error_class": WEBSOCKET_STATE_ERROR_COMPATIBILITY_CLASS,
                            "error_message": error.message(),
                        }),
                        Ok(catches_os_error) => match send_error {
                            Some(_) if catches_os_error => {
                                machine.send_failed();
                                json!({
                                    "action_id": action_id,
                                    "outcome": "send-error-handled",
                                })
                            }
                            Some(error_message) => json!({
                                "action_id": action_id,
                                "outcome": "error",
                                "error_class": WEBSOCKET_CALLBACK_OSERROR_CLASS,
                                "error_message": error_message,
                            }),
                            None => json!({
                                "action_id": action_id,
                                "outcome": "ok",
                            }),
                        },
                    }
                }
            }
            "set-client-state" => {
                exact_keys(action_object, &["action_id", "action", "state"], &context)?;
                let state =
                    websocket_state_from_name(string_field(action_object, "state", &context)?)?;
                machine.set_client_state(state);
                json!({
                    "action_id": action_id,
                    "outcome": "ok",
                })
            }
            "set-application-state" => {
                exact_keys(action_object, &["action_id", "action", "state"], &context)?;
                let state =
                    websocket_state_from_name(string_field(action_object, "state", &context)?)?;
                machine.set_application_state(state);
                json!({
                    "action_id": action_id,
                    "outcome": "ok",
                })
            }
            _ => {
                return Err(format!(
                    "{context}.action is unsupported by the WebSocketStateMachine surface; only accept, receive, send, and state assignments are declared"
                ));
            }
        };
        action_results.push(result);
    }
    if incoming_index != incoming.len() {
        return Err(String::from(
            "WebSocket state sequence left incoming messages unconsumed",
        ));
    }

    let value = json!({
        "action_results": action_results,
        "client_state": websocket_state_name(machine.client_state()),
        "application_state": websocket_state_name(machine.application_state()),
        "receive_calls": receive_calls,
    });
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": WEBSOCKET_STATE_OPERATION,
            "status": "ok",
            "value": value,
        }],
    }))
}

fn run_websocket_protocol_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "scope",
            "incoming",
            "actions",
            "observations",
        ],
        "WebSocket protocol-sequence case",
    )?;
    let case_id = string_field(case, "case_id", "WebSocket protocol-sequence case")?;
    if !case_id.starts_with(&format!("{WEBSOCKET_SURFACE}.{WEBSOCKET_OPERATION}."))
        || string_field(case, "surface", "WebSocket protocol-sequence case")? != WEBSOCKET_SURFACE
        || string_field(case, "operation", "WebSocket protocol-sequence case")?
            != WEBSOCKET_OPERATION
    {
        return Err(String::from(
            "case ID or operation is outside the WebSocket protocol sequence",
        ));
    }
    validate_native_package_target_profiles(case, "WebSocket protocol case")?;
    if case.get("assets") != Some(&json!([])) {
        return Err(String::from(
            "WebSocket protocol cases must select no assets",
        ));
    }
    let covers = case
        .get("covers")
        .and_then(Value::as_array)
        .filter(|items| !items.is_empty())
        .ok_or_else(|| String::from("WebSocket protocol case covers must be non-empty"))?;
    let mut covered_requirements = std::collections::BTreeSet::new();
    for item in covers {
        let requirement = item
            .as_str()
            .filter(|requirement| requirement.starts_with("starlette.websocket.protocol."))
            .ok_or_else(|| {
                String::from(
                    "WebSocket protocol case covers must name WebSocket protocol requirements",
                )
            })?;
        if !covered_requirements.insert(requirement) {
            return Err(format!(
                "duplicate WebSocket protocol coverage requirement: {requirement}"
            ));
        }
    }
    let observations = case
        .get("observations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("WebSocket protocol case observations must be an array"))?;
    if observations.len() != 1 || observations[0].as_str() != Some(WEBSOCKET_OPERATION) {
        return Err(String::from(
            "WebSocket observations must select the protocol-sequence workflow result",
        ));
    }

    validate_websocket_scope(
        case.get("scope")
            .ok_or_else(|| String::from("WebSocket protocol case misses scope"))?,
    )?;
    let incoming = case
        .get("incoming")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("WebSocket protocol incoming must be an array"))?;
    for (index, message) in incoming.iter().enumerate() {
        validate_websocket_message(
            message,
            &format!("WebSocket protocol incoming[{index}]"),
            true,
        )?;
    }
    let actions = case
        .get("actions")
        .and_then(Value::as_array)
        .filter(|actions| !actions.is_empty())
        .ok_or_else(|| String::from("WebSocket protocol actions must be a non-empty array"))?;

    let mut machine = WebSocketStateMachine::new();
    let mut incoming_index = 0;
    let mut action_ids = std::collections::BTreeSet::new();
    let mut callback_tape = Vec::new();
    for (index, action) in actions.iter().enumerate() {
        let context = format!("WebSocket protocol actions[{index}]");
        let action_object = action
            .as_object()
            .ok_or_else(|| format!("{context} must be an object"))?;
        let action_id = string_field(action_object, "action_id", &context)?;
        if !action_ids.insert(action_id.to_owned()) {
            return Err(format!(
                "duplicate WebSocket protocol action ID: {action_id}"
            ));
        }

        match string_field(action_object, "action", &context)? {
            "receive" => {
                exact_keys(action_object, &["action_id", "action"], &context)?;
                if matches!(
                    machine.client_state(),
                    WebSocketState::Connecting | WebSocketState::Connected
                ) {
                    // Starlette invokes the receive callback before validating
                    // the returned ASGI message. An exhausted scripted callback
                    // raises inside this action and contributes no tape entry.
                    if let Some(message) = incoming.get(incoming_index) {
                        checked_usize_increment(
                            &mut incoming_index,
                            "WebSocket input message index",
                        )?;
                        let canonical = canonical_websocket_message(
                            message,
                            &format!("{context}.incoming message"),
                        )?;
                        callback_tape.push(json!({
                            "direction": "receive",
                            "message": canonical,
                        }));
                        let message_type = string_field(
                            message.as_object().ok_or_else(|| {
                                format!("{context}.incoming message must be an object")
                            })?,
                            "type",
                            &format!("{context}.incoming message"),
                        )?;
                        // Protocol exceptions are per-action results in the
                        // oracle harness, so preserve the tape and continue.
                        let _ = machine.receive(message_type);
                    }
                }
                // A receive attempted after disconnect/denial, or one whose
                // scripted callback is exhausted, produces no callback entry.
            }
            "send" => {
                let mut expected = vec!["action_id", "action", "message"];
                if action_object.contains_key("send_error") {
                    expected.push("send_error");
                }
                exact_keys(action_object, &expected, &context)?;
                let message = action_object
                    .get("message")
                    .ok_or_else(|| format!("{context} misses message"))?;
                validate_websocket_message(message, &format!("{context}.message"), false)?;
                let message_object = message
                    .as_object()
                    .ok_or_else(|| format!("{context}.message must be an object"))?;
                let message_type =
                    string_field(message_object, "type", &format!("{context}.message"))?;
                let more_body = message
                    .get("more_body")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let send_error = action_object
                    .get("send_error")
                    .map(|raw_error| {
                        let error = exact_object(
                            raw_error,
                            &["kind", "message"],
                            &format!("{context}.send_error"),
                        )?;
                        if string_field(error, "kind", &format!("{context}.send_error"))?
                            != "os-error"
                        {
                            return Err(format!("{context}.send_error.kind must be os-error"));
                        }
                        string_field(error, "message", &format!("{context}.send_error"))?;
                        Ok(())
                    })
                    .transpose()?;

                // Starlette validates and updates application state before it
                // invokes the send callback. Invalid sends therefore leave no
                // callback-tape entry.
                if let Ok(catches_os_error) = machine.begin_send(message_type, more_body) {
                    let canonical =
                        canonical_websocket_message(message, &format!("{context}.message"))?;
                    callback_tape.push(json!({
                        "direction": "send",
                        "message": canonical,
                    }));
                    if send_error.is_some() && catches_os_error {
                        machine.send_failed();
                    }
                    // The input contract observes only the callback tape. The
                    // oracle harness catches callback errors and continues.
                }
            }
            _ => {
                return Err(format!(
                    "{context}.action is unsupported; only receive and send are declared"
                ));
            }
        }
    }
    if incoming_index != incoming.len() {
        return Err(String::from(
            "WebSocket protocol sequence left incoming messages unconsumed",
        ));
    }

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": WEBSOCKET_OPERATION,
            "status": "ok",
            "value": { "asgi_callback_tape": callback_tape },
        }],
    }))
}

fn canonical_websocket_message(message: &Value, context: &str) -> Result<Value, String> {
    let object = message
        .as_object()
        .ok_or_else(|| format!("{context} must be an ASGI message object"))?;
    let mut canonical = Map::new();
    for (name, value) in object {
        let value = match name.as_str() {
            "bytes_base64" | "body_base64" => {
                let encoded = value
                    .as_str()
                    .ok_or_else(|| format!("{context}.{name} must be base64"))?;
                Value::String(encode_base64(&decode_base64(
                    encoded,
                    &format!("{context}.{name}"),
                )?))
            }
            "headers_base64_pairs" => {
                let pairs = value
                    .as_array()
                    .ok_or_else(|| format!("{context}.headers_base64_pairs must be an array"))?;
                let mut canonical_pairs = Vec::with_capacity(pairs.len());
                for (index, pair) in pairs.iter().enumerate() {
                    let pair = pair
                        .as_array()
                        .filter(|pair| pair.len() == 2)
                        .ok_or_else(|| {
                            format!("{context}.headers_base64_pairs[{index}] must be a pair")
                        })?;
                    let canonical_pair = pair
                        .iter()
                        .enumerate()
                        .map(|(component, value)| {
                            let encoded = value.as_str().ok_or_else(|| {
                                format!(
                                    "{context}.headers_base64_pairs[{index}][{component}] must be base64"
                                )
                            })?;
                            Ok(Value::String(encode_base64(&decode_base64(
                                encoded,
                                &format!(
                                    "{context}.headers_base64_pairs[{index}][{component}]"
                                ),
                            )?)))
                        })
                        .collect::<Result<Vec<_>, String>>()?;
                    canonical_pairs.push(Value::Array(canonical_pair));
                }
                Value::Array(canonical_pairs)
            }
            _ => value.clone(),
        };
        canonical.insert(name.clone(), value);
    }
    Ok(Value::Object(canonical))
}

fn websocket_state_name(state: WebSocketState) -> &'static str {
    match state {
        WebSocketState::Connecting => "CONNECTING",
        WebSocketState::Connected => "CONNECTED",
        WebSocketState::Disconnected => "DISCONNECTED",
        WebSocketState::Response => "RESPONSE",
    }
}

fn websocket_state_from_name(name: &str) -> Result<WebSocketState, String> {
    match name {
        "CONNECTING" => Ok(WebSocketState::Connecting),
        "CONNECTED" => Ok(WebSocketState::Connected),
        "DISCONNECTED" => Ok(WebSocketState::Disconnected),
        "RESPONSE" => Ok(WebSocketState::Response),
        _ => Err(format!("unsupported WebSocket state name: {name}")),
    }
}

fn validate_websocket_scope(scope: &Value) -> Result<(), String> {
    let scope = object_with_optional_keys(
        scope,
        &[
            "type",
            "asgi",
            "http_version",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
            "subprotocols",
        ],
        &["extensions"],
        "WebSocket scope",
    )?;
    if string_field(scope, "type", "WebSocket scope")? != "websocket" {
        return Err(String::from("WebSocket scope.type must be websocket"));
    }
    let asgi = exact_object(
        scope
            .get("asgi")
            .ok_or_else(|| String::from("WebSocket scope misses asgi"))?,
        &["version", "spec_version"],
        "WebSocket scope.asgi",
    )?;
    if string_field(asgi, "version", "WebSocket scope.asgi")? != "3.0"
        || string_field(asgi, "spec_version", "WebSocket scope.asgi")? != "2.5"
    {
        return Err(String::from(
            "WebSocket scope uses an unsupported ASGI version",
        ));
    }
    for field in ["http_version", "path", "root_path"] {
        let _ = string_field(scope, field, "WebSocket scope")?;
    }
    if !matches!(
        string_field(scope, "scheme", "WebSocket scope")?,
        "ws" | "wss"
    ) {
        return Err(String::from("WebSocket scope.scheme must be ws or wss"));
    }
    let path = string_field(scope, "path", "WebSocket scope")?;
    let raw_path = decode_base64(
        string_field(scope, "raw_path_base64", "WebSocket scope")?,
        "WebSocket scope.raw_path_base64",
    )?;
    if raw_path != path.as_bytes() {
        return Err(String::from("WebSocket raw_path bytes must match path"));
    }
    let _ = decode_base64(
        string_field(scope, "query_string_base64", "WebSocket scope")?,
        "WebSocket scope.query_string_base64",
    )?;
    let headers = scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("WebSocket scope headers must be an array"))?;
    for (index, pair) in headers.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|items| items.len() == 2)
            .ok_or_else(|| format!("WebSocket scope header[{index}] must be a pair"))?;
        for value in pair {
            decode_base64(
                value
                    .as_str()
                    .ok_or_else(|| format!("WebSocket scope header[{index}] must be base64"))?,
                "WebSocket scope header",
            )?;
        }
    }
    validate_scope_address(
        scope
            .get("client")
            .ok_or_else(|| String::from("WebSocket scope misses client"))?,
        "WebSocket scope.client",
    )?;
    validate_scope_address(
        scope
            .get("server")
            .ok_or_else(|| String::from("WebSocket scope misses server"))?,
        "WebSocket scope.server",
    )?;
    validate_string_array(scope, "subprotocols", "WebSocket scope.subprotocols", true)?;
    if let Some(extensions) = scope.get("extensions") {
        let extensions = extensions
            .as_object()
            .ok_or_else(|| String::from("WebSocket scope.extensions must be an object"))?;
        for (name, configuration) in extensions {
            if name.is_empty() {
                return Err(String::from(
                    "WebSocket scope extension name must not be empty",
                ));
            }
            if !configuration.is_object() {
                return Err(String::from(
                    "WebSocket scope extension configurations must be objects",
                ));
            }
        }
    }
    Ok(())
}

fn validate_websocket_message(
    message: &Value,
    context: &str,
    incoming: bool,
) -> Result<(), String> {
    let message = message
        .as_object()
        .ok_or_else(|| format!("{context} must be an ASGI message object"))?;
    let message_type = string_field(message, "type", context)?;
    if incoming {
        match message_type {
            "websocket.connect" => {
                exact_keys(message, &["type", "subprotocols"], context)?;
                validate_string_array(message, "subprotocols", context, true)?;
            }
            "websocket.receive" => {
                if message.contains_key("text") {
                    exact_keys(message, &["type", "text"], context)?;
                    if message.get("text").and_then(Value::as_str).is_none() {
                        return Err(format!("{context}.text must be a string"));
                    }
                } else {
                    exact_keys(message, &["type", "bytes_base64"], context)?;
                    decode_base64(
                        string_field(message, "bytes_base64", context)?,
                        &format!("{context}.bytes_base64"),
                    )?;
                }
            }
            "websocket.disconnect" => {
                if message.contains_key("reason") {
                    exact_keys(message, &["type", "code", "reason"], context)?;
                    if message.get("reason").and_then(Value::as_str).is_none() {
                        return Err(format!("{context}.reason must be a string"));
                    }
                } else {
                    exact_keys(message, &["type", "code"], context)?;
                }
                let code = message
                    .get("code")
                    .and_then(Value::as_i64)
                    .filter(|value| *value >= 0)
                    .ok_or_else(|| format!("{context}.code must be a non-negative integer"))?;
                let _ = code;
            }
            // Unknown string types reach the WebSocket state machine, which
            // owns Starlette's public invalid-message error and repr wording.
            _ => return Ok(()),
        }
        return Ok(());
    }
    match message_type {
        "websocket.accept" => {
            if message
                .keys()
                .any(|key| !["type", "subprotocol", "headers_base64_pairs"].contains(&key.as_str()))
            {
                return Err(format!("{context} has unsupported websocket.accept fields"));
            }
            if message
                .get("subprotocol")
                .is_some_and(|value| !value.is_null() && value.as_str().is_none())
            {
                return Err(format!("{context}.subprotocol must be a string or null"));
            }
            if let Some(headers) = message.get("headers_base64_pairs") {
                validate_websocket_headers(headers, context)?;
            }
        }
        "websocket.close" => {
            if message.contains_key("reason") {
                exact_keys(message, &["type", "code", "reason"], context)?;
                if message.get("reason").and_then(Value::as_str).is_none() {
                    return Err(format!("{context}.reason must be a string"));
                }
            } else {
                exact_keys(message, &["type", "code"], context)?;
            }
            message
                .get("code")
                .and_then(Value::as_i64)
                .filter(|value| *value >= 0)
                .ok_or_else(|| format!("{context}.code must be a non-negative integer"))?;
        }
        "websocket.send" => {
            if message.contains_key("text") {
                exact_keys(message, &["type", "text"], context)?;
                if message.get("text").and_then(Value::as_str).is_none() {
                    return Err(format!("{context}.text must be a string"));
                }
            } else {
                exact_keys(message, &["type", "bytes_base64"], context)?;
                decode_base64(
                    string_field(message, "bytes_base64", context)?,
                    &format!("{context}.bytes_base64"),
                )?;
            }
        }
        "websocket.http.response.start" => {
            exact_keys(
                message,
                &["type", "status", "headers_base64_pairs"],
                context,
            )?;
            message
                .get("status")
                .and_then(Value::as_i64)
                .ok_or_else(|| format!("{context}.status must be an integer"))?;
            validate_websocket_headers(
                message
                    .get("headers_base64_pairs")
                    .ok_or_else(|| format!("{context} misses headers_base64_pairs"))?,
                context,
            )?;
        }
        "websocket.http.response.body" => {
            exact_keys(message, &["type", "body_base64", "more_body"], context)?;
            decode_base64(
                string_field(message, "body_base64", context)?,
                &format!("{context}.body_base64"),
            )?;
            if message.get("more_body").and_then(Value::as_bool).is_none() {
                return Err(format!("{context}.more_body must be boolean"));
            }
        }
        // Preserve unknown types for the state machine's public error path.
        _ => return Ok(()),
    }
    Ok(())
}

fn validate_websocket_headers(headers: &Value, context: &str) -> Result<(), String> {
    let headers = headers
        .as_array()
        .ok_or_else(|| format!("{context}.headers_base64_pairs must be an array"))?;
    for (index, pair) in headers.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|items| items.len() == 2)
            .ok_or_else(|| format!("{context} header[{index}] must be a pair"))?;
        for value in pair {
            decode_base64(
                value
                    .as_str()
                    .ok_or_else(|| format!("{context} header[{index}] must be base64"))?,
                &format!("{context} header[{index}]"),
            )?;
        }
    }
    Ok(())
}

fn run_application_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "steps",
            "observations",
            "execution_schedule",
        ],
        "workflow case",
    )?;
    let case_id = string_field(case, "case_id", "workflow case")?;
    if string_field(case, "surface", "workflow case")? != "starlette.applications.Starlette"
        || string_field(case, "operation", "workflow case")? != "__call__"
    {
        return Err(String::from(
            "workflow case is outside the declared Starlette ASGI slice",
        ));
    }
    let observations = case
        .get("observations")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("workflow case observations must be an array"))?;
    let schedule = case
        .get("execution_schedule")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("workflow execution_schedule must be an array"))?;
    let schedule = schedule
        .iter()
        .map(|event| {
            event
                .as_str()
                .ok_or_else(|| String::from("workflow schedule entries must be strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let steps = case
        .get("steps")
        .and_then(Value::as_array)
        .filter(|steps| matches!(steps.len(), 2 | 3))
        .ok_or_else(|| String::from("workflow case must contain application and dispatch steps"))?;

    let (application, lifespan_spec, route_table) = build_application(&steps[0])?;
    let mut result_observations = Vec::new();
    if steps.len() == 3 {
        if observations.len() != 2
            || observations.first().and_then(Value::as_str) != Some("lifecycle")
            || observations.get(1).and_then(Value::as_str) != Some("dispatch")
            || schedule.as_slice() != ["lifespan.startup", "dispatch", "lifespan.shutdown"]
        {
            return Err(String::from(
                "interleaved lifespan workflow must select its startup/dispatch/shutdown schedule",
            ));
        }
        let lifecycle = begin_lifespan(&steps[1], &lifespan_spec)?;
        if lifecycle.state.phase() != starlette_rs::LifespanPhase::Running {
            return Err(String::from(
                "lifespan must be running before HTTP dispatch",
            ));
        }
        let dispatch = run_dispatch(&steps[2], &application, &route_table, &lifecycle.trace)?;
        let dispatch_events = dispatch
            .get("asgi_events")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("HTTP dispatch omitted its ordered ASGI events"))?;
        let lifecycle = finish_lifespan(lifecycle, dispatch_events)?;
        result_observations.push(json!({
            "step_id": "lifecycle",
            "status": "ok",
            "value": lifecycle.value,
        }));
        result_observations.push(json!({
            "step_id": "dispatch",
            "status": "ok",
            "value": dispatch,
        }));
    } else if observations.len() == 1
        && observations.first().and_then(Value::as_str) == Some("lifecycle")
        && schedule.as_slice() == ["lifespan.startup", "lifespan.shutdown"]
    {
        result_observations.push(run_lifespan_only(&steps[1], &lifespan_spec, &schedule)?);
    } else {
        if observations.len() != 1
            || observations.first().and_then(Value::as_str) != Some("dispatch")
            || schedule.as_slice() != ["dispatch"]
        {
            return Err(String::from(
                "a dispatch-only workflow must select only the dispatch observation",
            ));
        }
        let dispatch = run_dispatch(&steps[1], &application, &route_table, &[])?;
        result_observations.push(json!({
            "step_id": "dispatch",
            "status": "ok",
            "value": dispatch,
        }));
    }

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": result_observations,
    }))
}

fn run_gzip_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "steps",
            "observations",
            "execution_schedule",
        ],
        "GZipMiddleware workflow case",
    )?;
    let case_id = string_field(case, "case_id", "GZipMiddleware workflow case")?;
    if string_field(case, "surface", "GZipMiddleware workflow case")?
        != "starlette.middleware.gzip.GZipMiddleware"
        || string_field(case, "operation", "GZipMiddleware workflow case")? != "__call__"
    {
        return Err(String::from(
            "GZipMiddleware workflow must select its declared __call__ operation",
        ));
    }
    validate_string_array(case, "covers", "GZipMiddleware covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "GZipMiddleware target_profiles",
        false,
    )?;
    if case.get("assets") != Some(&Value::Array(Vec::new())) {
        return Err(String::from(
            "GZipMiddleware workflow does not accept undeclared assets",
        ));
    }
    if case.get("observations") != Some(&json!(["dispatch"]))
        || case.get("execution_schedule") != Some(&json!(["dispatch"]))
    {
        return Err(String::from(
            "GZipMiddleware workflow must select its dispatch observation and schedule",
        ));
    }
    let steps = case
        .get("steps")
        .and_then(Value::as_array)
        .filter(|steps| steps.len() == 2)
        .ok_or_else(|| {
            String::from("GZipMiddleware workflow must construct middleware then dispatch")
        })?;

    let (config, inner_response) = build_gzip_middleware(&steps[0])?;
    let dispatch = parse_gzip_dispatch(&steps[1])?;
    let mut responder = config.responder(&dispatch.request_headers);
    responder.response_start(inner_response.status, inner_response.headers);

    let mut events = Vec::new();
    let mut response_bytes = Vec::new();
    for message in inner_response.messages {
        match message {
            GzipInnerMessage::Body { body, more_body } => {
                let output = responder
                    .response_body(&body, more_body)
                    .map_err(|error| error.to_string())?;
                if let Some(response_start) = output.response_start {
                    events.push(canonical_gzip_start(&response_start));
                }
                response_bytes.extend_from_slice(&output.body);
                events.push(json!({
                    "type": "http.response.body",
                    "body": {"encoding": "base64", "data": encode_base64(&output.body)},
                    "more_body": more_body,
                }));
            }
            GzipInnerMessage::Pathsend { path } => {
                let response_start = responder.pathsend().ok_or_else(|| {
                    String::from("GZipResponder omitted its buffered response start")
                })?;
                events.push(canonical_gzip_start(&response_start));
                events.push(json!({
                    "type": "http.response.pathsend",
                    "path": path,
                }));
            }
        }
    }

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "dispatch",
            "status": "ok",
            "value": {
                "asgi_events": events,
                "response_bytes": {
                    "encoding": "base64",
                    "data": encode_base64(&response_bytes),
                },
            },
        }],
    }))
}

struct GzipInnerResponse {
    status: u16,
    headers: Vec<GzipHeader>,
    messages: Vec<GzipInnerMessage>,
}

enum GzipInnerMessage {
    Body { body: Vec<u8>, more_body: bool },
    Pathsend { path: String },
}

struct GzipDispatchInput {
    request_headers: Vec<GzipHeader>,
}

fn build_gzip_middleware(step: &Value) -> Result<(GzipConfig, GzipInnerResponse), String> {
    let arguments = gzip_step_arguments(step, "middleware", "__init__", None)?;
    const ALLOWED_ARGUMENTS: [&str; 5] = [
        "app",
        "minimum_size",
        "compresslevel",
        "thread_minimum_size",
        "exclude_content_types",
    ];
    if arguments
        .keys()
        .any(|name| !ALLOWED_ARGUMENTS.contains(&name.as_str()))
    {
        return Err(String::from(
            "GZipMiddleware constructor arguments contain an unknown field",
        ));
    }
    if !arguments.contains_key("app") {
        return Err(String::from(
            "GZipMiddleware constructor arguments must include app",
        ));
    }

    let app = argument_value(arguments, "app", "GZipMiddleware constructor arguments")?;
    let app = exact_object(app, &["kind", "messages"], "GZipMiddleware inner app")?;
    if string_field(app, "kind", "GZipMiddleware inner app")? != "asgi-response-sequence" {
        return Err(String::from(
            "GZipMiddleware inner app must be an ASGI response sequence",
        ));
    }
    let messages = app
        .get("messages")
        .and_then(Value::as_array)
        .filter(|messages| messages.len() >= 2)
        .ok_or_else(|| {
            String::from("GZipMiddleware inner app must supply a response start and output")
        })?;
    let start = exact_object(
        &messages[0],
        &["type", "status", "headers_base64_pairs"],
        "GZipMiddleware inner response start",
    )?;
    if string_field(start, "type", "GZipMiddleware inner response start")? != "http.response.start"
    {
        return Err(String::from(
            "GZipMiddleware inner response must begin with http.response.start",
        ));
    }
    let status = start
        .get("status")
        .and_then(Value::as_u64)
        .and_then(|status| u16::try_from(status).ok())
        .filter(|status| (100..=599).contains(status))
        .ok_or_else(|| {
            String::from("GZipMiddleware response status must be from 100 through 599")
        })?;
    let headers = parse_gzip_headers(
        start.get("headers_base64_pairs").ok_or_else(|| {
            String::from("GZipMiddleware response start omitted headers_base64_pairs")
        })?,
        "GZipMiddleware response start headers",
    )?;
    let output_messages = parse_gzip_inner_messages(&messages[1..])?;

    let minimum_size = if arguments.contains_key("minimum_size") {
        integer_argument(
            arguments,
            "minimum_size",
            "GZipMiddleware constructor arguments",
        )?
    } else {
        500
    };
    let thread_minimum_size = if arguments.contains_key("thread_minimum_size") {
        integer_argument(
            arguments,
            "thread_minimum_size",
            "GZipMiddleware constructor arguments",
        )?
    } else {
        128 * 1024
    };
    if minimum_size < 0 || thread_minimum_size < 0 {
        return Err(String::from(
            "GZipMiddleware size settings must be non-negative integers",
        ));
    }
    let compresslevel = if arguments.contains_key("compresslevel") {
        integer_argument(
            arguments,
            "compresslevel",
            "GZipMiddleware constructor arguments",
        )?
    } else {
        9
    };
    let compresslevel = i32::try_from(compresslevel)
        .map_err(|_| String::from("GZipMiddleware compresslevel must fit in i32"))?;
    if !(-1..=9).contains(&compresslevel) {
        return Err(String::from(
            "GZipMiddleware compresslevel must be from -1 through 9",
        ));
    }
    let exclusions: Vec<String> = if arguments.contains_key("exclude_content_types") {
        let exclusions = argument_value(
            arguments,
            "exclude_content_types",
            "GZipMiddleware constructor arguments",
        )?;
        exclusions
            .as_array()
            .ok_or_else(|| String::from("exclude_content_types must be a string array"))?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .map(str::to_owned)
                    .ok_or_else(|| {
                        String::from("exclude_content_types must contain non-empty strings")
                    })
            })
            .collect::<Result<Vec<_>, _>>()?
    } else {
        DEFAULT_EXCLUDED_CONTENT_TYPES
            .iter()
            .map(|content_type| (*content_type).to_owned())
            .collect()
    };

    let config = GzipConfig::new(minimum_size, compresslevel, thread_minimum_size, exclusions);
    Ok((
        config,
        GzipInnerResponse {
            status,
            headers,
            messages: output_messages,
        },
    ))
}

fn parse_gzip_inner_messages(messages: &[Value]) -> Result<Vec<GzipInnerMessage>, String> {
    if messages.is_empty() {
        return Err(String::from(
            "GZipMiddleware inner response output is empty",
        ));
    }
    let mut output = Vec::with_capacity(messages.len());
    for (index, raw_message) in messages.iter().enumerate() {
        let context = format!("GZipMiddleware inner response message[{index}]");
        let message_type = raw_message
            .get("type")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{context}.type must be a string"))?;
        match message_type {
            "http.response.body" => {
                let message =
                    exact_object(raw_message, &["type", "body_base64", "more_body"], &context)?;
                let body = decode_base64(
                    string_field(message, "body_base64", &context)?,
                    &format!("{context}.body_base64"),
                )?;
                let more_body = message
                    .get("more_body")
                    .and_then(Value::as_bool)
                    .ok_or_else(|| format!("{context}.more_body must be a boolean"))?;
                output.push(GzipInnerMessage::Body { body, more_body });
            }
            "http.response.pathsend" => {
                let message = exact_object(raw_message, &["type", "path"], &context)?;
                let path = string_field(message, "path", &context)?.to_owned();
                output.push(GzipInnerMessage::Pathsend { path });
            }
            _ => return Err(format!("{context} uses an unsupported ASGI response type")),
        }
    }
    let all_bodies = output
        .iter()
        .all(|message| matches!(message, GzipInnerMessage::Body { .. }));
    if all_bodies {
        if output.iter().enumerate().any(|(index, message)| {
            let GzipInnerMessage::Body { more_body, .. } = message else {
                return true;
            };
            index
                .checked_add(1)
                .is_none_or(|next_index| *more_body != (next_index != output.len()))
        }) {
            return Err(String::from(
                "GZipMiddleware body messages must end with more_body=false",
            ));
        }
    } else if output.len() != 1
        || !matches!(output.first(), Some(GzipInnerMessage::Pathsend { .. }))
    {
        return Err(String::from(
            "GZipMiddleware pathsend must be the only inner response output",
        ));
    }
    Ok(output)
}

fn parse_gzip_dispatch(step: &Value) -> Result<GzipDispatchInput, String> {
    let arguments = gzip_step_arguments(step, "dispatch", "__call__", Some("middleware"))?;
    exact_keys(
        arguments,
        &["scope", "receive", "send"],
        "GZipMiddleware dispatch arguments",
    )?;
    let scope = argument_value(arguments, "scope", "GZipMiddleware dispatch arguments")?;
    let scope = exact_object(
        scope,
        &[
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        ],
        "GZipMiddleware HTTP scope",
    )?;
    if string_field(scope, "type", "GZipMiddleware HTTP scope")? != "http" {
        return Err(String::from(
            "GZipMiddleware dispatch requires an HTTP scope",
        ));
    }
    let asgi = exact_object(
        scope
            .get("asgi")
            .ok_or_else(|| String::from("GZipMiddleware HTTP scope omitted asgi"))?,
        &["version", "spec_version"],
        "GZipMiddleware HTTP scope asgi",
    )?;
    let _ = string_field(asgi, "version", "GZipMiddleware HTTP scope asgi")?;
    let _ = string_field(asgi, "spec_version", "GZipMiddleware HTTP scope asgi")?;
    for field in ["http_version", "method", "scheme", "path", "root_path"] {
        let _ = string_field(scope, field, "GZipMiddleware HTTP scope")?;
    }
    let path = string_field(scope, "path", "GZipMiddleware HTTP scope")?;
    let raw_path = decode_base64(
        string_field(scope, "raw_path_base64", "GZipMiddleware HTTP scope")?,
        "GZipMiddleware scope.raw_path_base64",
    )?;
    if raw_path != path.as_bytes() {
        return Err(String::from(
            "GZipMiddleware raw_path bytes must match the declared path",
        ));
    }
    let _ = decode_base64(
        string_field(scope, "query_string_base64", "GZipMiddleware HTTP scope")?,
        "GZipMiddleware scope.query_string_base64",
    )?;
    validate_scope_address(
        scope
            .get("client")
            .ok_or_else(|| String::from("GZipMiddleware HTTP scope omitted client"))?,
        "GZipMiddleware scope.client",
    )?;
    validate_scope_address(
        scope
            .get("server")
            .ok_or_else(|| String::from("GZipMiddleware HTTP scope omitted server"))?,
        "GZipMiddleware scope.server",
    )?;
    let request_headers = parse_gzip_headers(
        scope
            .get("headers_base64_pairs")
            .ok_or_else(|| String::from("GZipMiddleware HTTP scope omitted headers"))?,
        "GZipMiddleware request headers",
    )?;
    parse_gzip_receive_messages(argument_value(
        arguments,
        "receive",
        "GZipMiddleware dispatch arguments",
    )?)?;
    validate_capture_send(argument_value(
        arguments,
        "send",
        "GZipMiddleware dispatch arguments",
    )?)?;
    Ok(GzipDispatchInput { request_headers })
}

fn parse_gzip_receive_messages(value: &Value) -> Result<(), String> {
    let messages = value
        .as_array()
        .ok_or_else(|| String::from("GZipMiddleware receive input must be an array"))?;
    for (index, raw_message) in messages.iter().enumerate() {
        let context = format!("GZipMiddleware receive message[{index}]");
        let message = exact_object(raw_message, &["type", "body_base64", "more_body"], &context)?;
        if string_field(message, "type", &context)? != "http.request" {
            return Err(format!("{context}.type must be http.request"));
        }
        let _ = decode_base64(
            string_field(message, "body_base64", &context)?,
            &format!("{context}.body_base64"),
        )?;
        let _ = message
            .get("more_body")
            .and_then(Value::as_bool)
            .ok_or_else(|| format!("{context}.more_body must be a boolean"))?;
    }
    Ok(())
}

fn parse_gzip_headers(value: &Value, context: &str) -> Result<Vec<GzipHeader>, String> {
    let pairs = value
        .as_array()
        .ok_or_else(|| format!("{context} must be an array"))?;
    let mut headers = Vec::with_capacity(pairs.len());
    for (index, raw_pair) in pairs.iter().enumerate() {
        let pair = raw_pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| format!("{context}[{index}] must be a two-item pair"))?;
        let name = pair[0]
            .as_str()
            .ok_or_else(|| format!("{context}[{index}].name must be base64 text"))?;
        let value = pair[1]
            .as_str()
            .ok_or_else(|| format!("{context}[{index}].value must be base64 text"))?;
        let name = decode_base64(name, &format!("{context}[{index}].name"))?;
        if name.is_empty() {
            return Err(format!("{context}[{index}] has an empty header name"));
        }
        let value = decode_base64(value, &format!("{context}[{index}].value"))?;
        headers.push((name, value));
    }
    Ok(headers)
}

fn gzip_step_arguments<'a>(
    step: &'a Value,
    expected_id: &str,
    expected_operation: &str,
    receiver: Option<&str>,
) -> Result<&'a Map<String, Value>, String> {
    let step = exact_object(
        step,
        &["step_id", "surface", "operation", "receiver", "arguments"],
        "GZipMiddleware workflow step",
    )?;
    if string_field(step, "step_id", "GZipMiddleware workflow step")? != expected_id
        || string_field(step, "surface", "GZipMiddleware workflow step")?
            != "starlette.middleware.gzip.GZipMiddleware"
        || string_field(step, "operation", "GZipMiddleware workflow step")? != expected_operation
    {
        return Err(format!(
            "GZipMiddleware step {expected_id:?} does not match the declared operation"
        ));
    }
    match (receiver, step.get("receiver")) {
        (None, Some(value)) if value.is_null() => {}
        (Some(expected), Some(value)) => {
            let binding = exact_object(value, &["kind", "step_id"], "GZipMiddleware receiver")?;
            if string_field(binding, "kind", "GZipMiddleware receiver")? != "binding"
                || string_field(binding, "step_id", "GZipMiddleware receiver")? != expected
            {
                return Err(String::from(
                    "GZipMiddleware step has an invalid receiver binding",
                ));
            }
        }
        _ => return Err(String::from("GZipMiddleware step has an invalid receiver")),
    }
    step.get("arguments")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("GZipMiddleware step arguments must be an object"))
}

fn integer_argument(
    arguments: &Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<i64, String> {
    argument_value(arguments, name, context)?
        .as_i64()
        .ok_or_else(|| format!("{context}.{name} must be a signed integer"))
}

fn validate_string_array(
    object: &Map<String, Value>,
    field: &str,
    context: &str,
    allow_empty: bool,
) -> Result<(), String> {
    let values = object
        .get(field)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context} must be an array"))?;
    if (!allow_empty && values.is_empty()) || values.iter().any(|value| value.as_str().is_none()) {
        return Err(format!("{context} must contain strings"));
    }
    Ok(())
}

fn validate_scope_address(value: &Value, context: &str) -> Result<(), String> {
    let address = value
        .as_array()
        .filter(|address| address.len() == 2)
        .ok_or_else(|| format!("{context} must be a two-item array"))?;
    if address[0].as_str().is_none() || address[1].as_u64().is_none() {
        return Err(format!(
            "{context} must contain a host string and unsigned port"
        ));
    }
    Ok(())
}

fn canonical_gzip_start(start: &GzipResponseStart) -> Value {
    json!({
        "type": "http.response.start",
        "status": start.status,
        "headers": canonical_headers(&start.headers),
    })
}

struct RequestObserver {
    path_parameter: String,
    query_parameter: String,
    header_primary_case: String,
    header_alternate_case: String,
    cookie_name: String,
    response_content: String,
    status_code: u16,
    media_type: String,
}

struct RequestCookiesObserver {
    probe_kind: String,
    response_content: String,
    status_code: u16,
    media_type: String,
}

enum RequestDispatchObserver {
    Request(RequestObserver),
    Cookies(RequestCookiesObserver),
}

struct RequestScope {
    query_string: Vec<u8>,
    headers: RequestHeaders,
}

struct ParsedRequestDispatch {
    method: String,
    path: String,
    scope: RequestScope,
    chunks: RequestChunks,
}

struct ScopeIdentity {
    _token: u8,
}

struct RoutedScope<'a> {
    app: &'a ScopeIdentity,
    router: &'a ScopeIdentity,
    endpoint: Option<&'a ScopeIdentity>,
    path_params: Option<Value>,
}

impl<'a> RoutedScope<'a> {
    fn new(app: &'a ScopeIdentity, router: &'a ScopeIdentity) -> Self {
        Self {
            app,
            router,
            endpoint: None,
            path_params: None,
        }
    }

    fn apply_route(&mut self, endpoint: &'a ScopeIdentity, path_params: Value) {
        self.endpoint = Some(endpoint);
        self.path_params = Some(path_params);
    }

    fn observations(
        &self,
        application: &ScopeIdentity,
        application_router: &ScopeIdentity,
        route_endpoint: &ScopeIdentity,
    ) -> Value {
        json!({
            "app_is_application": std::ptr::eq(self.app, application),
            "router_is_application_router": std::ptr::eq(self.router, application_router),
            "endpoint_is_route_endpoint": self
                .endpoint
                .is_some_and(|endpoint| std::ptr::eq(endpoint, route_endpoint)),
            "path_params_present": self.path_params.is_some(),
            "path_params": self.path_params.as_ref(),
        })
    }
}

type RequestChunks = Vec<(Vec<u8>, bool)>;

fn run_request_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "steps",
            "observations",
            "execution_schedule",
        ],
        "request-dispatch case",
    )?;
    let case_id = string_field(case, "case_id", "request-dispatch case")?;
    if string_field(case, "surface", "request-dispatch case")? != "starlette.applications.Starlette"
        || string_field(case, "operation", "request-dispatch case")? != "request-dispatch"
    {
        return Err(String::from(
            "request-dispatch case is outside the declared Starlette operation",
        ));
    }
    let covers = case
        .get("covers")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("request-dispatch case covers must be an array"))?;
    if covers.iter().any(|item| item.as_str().is_none()) {
        return Err(String::from(
            "request-dispatch case covers must contain only strings",
        ));
    }
    validate_native_package_target_profiles(case, "request-dispatch case")?;
    if case.get("assets") != Some(&json!([]))
        || case.get("observations") != Some(&json!(["dispatch"]))
        || case.get("execution_schedule") != Some(&json!(["dispatch"]))
    {
        return Err(String::from(
            "request-dispatch case must select no assets and dispatch only",
        ));
    }
    let steps = case
        .get("steps")
        .and_then(Value::as_array)
        .filter(|steps| steps.len() == 2)
        .ok_or_else(|| {
            String::from("request-dispatch case must contain application then dispatch steps")
        })?;

    let (routes, response, observer) = build_request_application(&steps[0])?;
    let request = parse_request_dispatch(&steps[1])?;
    let route_match = routes.matches_detailed(&request.path, &request.method);
    let application_identity = ScopeIdentity { _token: 0 };
    let router_identity = ScopeIdentity { _token: 1 };
    let route_endpoint_identity = ScopeIdentity { _token: 2 };
    let mut routed_scope = RoutedScope::new(&application_identity, &router_identity);

    let request_observations = match &route_match {
        DetailedRouteMatch::Matched {
            route_index: 0,
            path_params,
        }
        | DetailedRouteMatch::MethodNotAllowed {
            route_index: 0,
            path_params,
            ..
        } => {
            let route_scope_params = path_params_value(path_params)?;
            routed_scope.apply_route(&route_endpoint_identity, route_scope_params);
            if matches!(&route_match, DetailedRouteMatch::Matched { .. }) {
                observer
                    .as_ref()
                    .map(|observer| {
                        request_observations(&request.scope, &request.chunks, path_params, observer)
                    })
                    .transpose()?
            } else {
                None
            }
        }
        DetailedRouteMatch::Matched { route_index, .. }
        | DetailedRouteMatch::MethodNotAllowed { route_index, .. } => {
            return Err(format!(
                "route table selected unexpected route index {route_index}"
            ));
        }
        DetailedRouteMatch::NotFound => None,
    };

    let response = match &route_match {
        DetailedRouteMatch::Matched { route_index: 0, .. } => response,
        DetailedRouteMatch::Matched { route_index, .. } => {
            return Err(format!(
                "route table selected unexpected route index {route_index}"
            ));
        }
        DetailedRouteMatch::MethodNotAllowed { route_index: 0, .. }
        | DetailedRouteMatch::NotFound => route_match
            .fallback_response()
            .map_err(|error| error.to_string())?
            .ok_or_else(|| String::from("route fallback did not provide its response"))?,
        DetailedRouteMatch::MethodNotAllowed { route_index, .. } => {
            return Err(format!(
                "route table selected unexpected route index {route_index}"
            ));
        }
    };
    let response = request_response_transcript(&response)?;
    let route_scope = routed_scope.observations(
        &application_identity,
        &router_identity,
        &route_endpoint_identity,
    );

    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "dispatch",
            "status": "ok",
            "value": {
                "request_observations": request_observations,
                "sync_endpoint_observations": null,
                "async_endpoint_observations": null,
                "scope_mapping_observation": {
                    "type": "builtins.dict",
                    "app_is_application": true,
                    "router_is_application_router": true,
                    "marker": request.path,
                },
                "route_scope": route_scope,
                "response_status": response["response_status"],
                "ordered_repeated_headers": response["ordered_repeated_headers"],
                "asgi_event_order": response["asgi_event_order"],
                "asgi_events": response["asgi_events"],
            },
        }],
    }))
}

fn build_request_application(
    step: &Value,
) -> Result<(RouteTable, Response, Option<RequestDispatchObserver>), String> {
    let arguments = step_arguments(step, "application", "__init__", None)?;
    exact_keys(
        arguments,
        &[
            "debug",
            "routes",
            "middleware",
            "exception_handlers",
            "lifespan",
            "max_body_size",
        ],
        "request-dispatch application arguments",
    )?;
    if argument_value(arguments, "debug", "application arguments")? != &Value::Bool(false)
        || argument_value(arguments, "middleware", "application arguments")?
            != &Value::Array(Vec::new())
        || argument_value(arguments, "exception_handlers", "application arguments")?
            != &Value::Array(Vec::new())
        || !argument_value(arguments, "max_body_size", "application arguments")?.is_null()
    {
        return Err(String::from(
            "request-dispatch constructor inputs differ from the declared baseline",
        ));
    }
    let lifespan = argument_value(arguments, "lifespan", "application arguments")?;
    let lifespan = exact_object(
        lifespan,
        &["kind", "record_entry", "record_exit"],
        "request-dispatch lifespan input",
    )?;
    if string_field(lifespan, "kind", "request-dispatch lifespan input")? != "async-context-manager"
        || lifespan.get("record_entry") != Some(&Value::Bool(true))
        || lifespan.get("record_exit") != Some(&Value::Bool(true))
    {
        return Err(String::from(
            "request-dispatch lifespan input differs from the declared marker",
        ));
    }

    let routes = argument_value(arguments, "routes", "application arguments")?
        .as_array()
        .filter(|routes| routes.len() == 1)
        .ok_or_else(|| String::from("request-dispatch requires exactly one route"))?;
    let route = exact_object(
        &routes[0],
        &["kind", "path", "methods", "endpoint"],
        "request-dispatch route input",
    )?;
    if string_field(route, "kind", "request-dispatch route input")? != "http-route" {
        return Err(String::from(
            "request-dispatch route kind must be http-route",
        ));
    }
    let route_path = string_field(route, "path", "request-dispatch route input")?;
    let methods = route
        .get("methods")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("request-dispatch route methods must be an array"))?
        .iter()
        .map(|method| {
            method
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| String::from("route methods must contain strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;

    let mut routes = RouteTable::new();
    routes
        .add_route(route_path, methods)
        .map_err(|error| error.to_string())?;

    let endpoint_value = route
        .get("endpoint")
        .ok_or_else(|| String::from("request-dispatch endpoint is missing"))?;
    let endpoint_kind = endpoint_value
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("request-dispatch endpoint kind must be a string"))?;
    let (response, observer) = match endpoint_kind {
        "request-observer" => {
            let endpoint = exact_object(
                endpoint_value,
                &[
                    "kind",
                    "path_parameter",
                    "query_parameter",
                    "header_primary_case",
                    "header_alternate_case",
                    "cookie_name",
                    "response_content",
                    "status_code",
                    "media_type",
                ],
                "request-observer endpoint",
            )?;
            let observer = RequestObserver {
                path_parameter: string_field(
                    endpoint,
                    "path_parameter",
                    "request-observer endpoint",
                )?
                .to_owned(),
                query_parameter: string_field(
                    endpoint,
                    "query_parameter",
                    "request-observer endpoint",
                )?
                .to_owned(),
                header_primary_case: string_field(
                    endpoint,
                    "header_primary_case",
                    "request-observer endpoint",
                )?
                .to_owned(),
                header_alternate_case: string_field(
                    endpoint,
                    "header_alternate_case",
                    "request-observer endpoint",
                )?
                .to_owned(),
                cookie_name: string_field(endpoint, "cookie_name", "request-observer endpoint")?
                    .to_owned(),
                response_content: string_field(
                    endpoint,
                    "response_content",
                    "request-observer endpoint",
                )?
                .to_owned(),
                status_code: endpoint
                    .get("status_code")
                    .and_then(Value::as_u64)
                    .and_then(|status| u16::try_from(status).ok())
                    .ok_or_else(|| String::from("request-observer status_code must be a u16"))?,
                media_type: string_field(endpoint, "media_type", "request-observer endpoint")?
                    .to_owned(),
            };
            let response = Response::from_content(
                observer.status_code,
                observer.response_content.as_bytes().to_vec(),
                Some(&observer.media_type),
                std::iter::empty::<(String, String)>(),
            )
            .map_err(|error| error.to_string())?;
            (response, Some(RequestDispatchObserver::Request(observer)))
        }
        "request-cookies-observer" => {
            let endpoint = exact_object(
                endpoint_value,
                &[
                    "kind",
                    "probe",
                    "response_content",
                    "status_code",
                    "media_type",
                ],
                "request cookies observer endpoint",
            )?;
            let probe = exact_object(
                endpoint
                    .get("probe")
                    .ok_or_else(|| String::from("request cookies observer probe is missing"))?,
                &["kind"],
                "request cookies observer probe",
            )?;
            let probe_kind = string_field(probe, "kind", "request cookies observer probe")?;
            if probe_kind != "items" {
                return Err(String::from(
                    "Rust-native request cookies observer supports only the items probe",
                ));
            }
            let observer = RequestCookiesObserver {
                probe_kind: probe_kind.to_owned(),
                response_content: string_field(
                    endpoint,
                    "response_content",
                    "request cookies observer endpoint",
                )?
                .to_owned(),
                status_code: endpoint
                    .get("status_code")
                    .and_then(Value::as_u64)
                    .and_then(|status| u16::try_from(status).ok())
                    .ok_or_else(|| {
                        String::from("request cookies observer status_code must be a u16")
                    })?,
                media_type: string_field(
                    endpoint,
                    "media_type",
                    "request cookies observer endpoint",
                )?
                .to_owned(),
            };
            let response = Response::from_content(
                observer.status_code,
                observer.response_content.as_bytes().to_vec(),
                Some(&observer.media_type),
                std::iter::empty::<(String, String)>(),
            )
            .map_err(|error| error.to_string())?;
            (response, Some(RequestDispatchObserver::Cookies(observer)))
        }
        "http-exception" => {
            let endpoint = exact_object(
                endpoint_value,
                &["kind", "status_code", "detail", "headers"],
                "HTTP exception endpoint",
            )?;
            let status_code = endpoint
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .ok_or_else(|| String::from("HTTP exception status_code must be a u16"))?;
            let detail = match endpoint.get("detail") {
                Some(Value::String(detail)) => Some(detail.as_str()),
                Some(Value::Null) => None,
                _ => {
                    return Err(String::from(
                        "HTTP exception detail must be a string or null",
                    ));
                }
            };
            let headers = endpoint
                .get("headers")
                .and_then(Value::as_array)
                .ok_or_else(|| String::from("HTTP exception headers must be an array"))?
                .iter()
                .map(|header| {
                    let pair = header
                        .as_array()
                        .filter(|pair| pair.len() == 2)
                        .ok_or_else(|| String::from("HTTP exception headers must be pairs"))?;
                    let name = pair[0].as_str().ok_or_else(|| {
                        String::from("HTTP exception header names must be strings")
                    })?;
                    let value = pair[1].as_str().ok_or_else(|| {
                        String::from("HTTP exception header values must be strings")
                    })?;
                    Ok((name.to_owned(), value.to_owned()))
                })
                .collect::<Result<Vec<_>, String>>()?;
            let response = Response::http_exception(status_code, detail, &headers)
                .map_err(|error| error.to_string())?;
            (response, None)
        }
        _ => {
            return Err(format!(
                "unsupported request-dispatch endpoint kind: {endpoint_kind:?}"
            ));
        }
    };
    Ok((routes, response, observer))
}

fn parse_request_dispatch(step: &Value) -> Result<ParsedRequestDispatch, String> {
    let arguments = step_arguments(step, "dispatch", "request-dispatch", Some("application"))?;
    exact_keys(
        arguments,
        &["scope", "receive", "send"],
        "request-dispatch arguments",
    )?;
    let scope = argument_value(arguments, "scope", "request-dispatch arguments")?;
    let scope = exact_object(
        scope,
        &[
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        ],
        "request-dispatch HTTP scope",
    )?;
    let method = string_field(scope, "method", "request-dispatch HTTP scope")?.to_owned();
    let path = string_field(scope, "path", "request-dispatch HTTP scope")?.to_owned();
    if string_field(scope, "type", "request-dispatch HTTP scope")? != "http"
        || classify_scope("http") != AsgiScopeKind::Http
        || string_field(scope, "http_version", "request-dispatch HTTP scope")? != "1.1"
        || string_field(scope, "scheme", "request-dispatch HTTP scope")? != "http"
        || !string_field(scope, "root_path", "request-dispatch HTTP scope")?.is_empty()
        || scope.get("asgi") != Some(&json!({"version":"3.0","spec_version":"2.4"}))
        || scope.get("client") != Some(&json!(["127.0.0.1", 12345]))
        || scope.get("server") != Some(&json!(["testserver", 80]))
    {
        return Err(String::from(
            "request-dispatch scope differs from the declared direct-ASGI baseline",
        ));
    }

    let raw_path = decode_base64(
        string_field(scope, "raw_path_base64", "request-dispatch HTTP scope")?,
        "scope.raw_path_base64",
    )?;
    if raw_path != path.as_bytes() {
        return Err(String::from("request-dispatch raw path differs from path"));
    }
    let query_string = decode_base64(
        string_field(scope, "query_string_base64", "request-dispatch HTTP scope")?,
        "scope.query_string_base64",
    )?;
    let header_values = scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("scope.headers_base64_pairs must be an array"))?;
    let mut raw_headers = Vec::with_capacity(header_values.len());
    for pair in header_values {
        let pair = pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| String::from("each request header must be a two-item array"))?;
        let name = pair[0]
            .as_str()
            .ok_or_else(|| String::from("request header name must be base64 text"))?;
        let value = pair[1]
            .as_str()
            .ok_or_else(|| String::from("request header value must be base64 text"))?;
        raw_headers.push((
            decode_base64(name, "scope header name")?,
            decode_base64(value, "scope header value")?,
        ));
    }
    let receive = argument_value(arguments, "receive", "request-dispatch arguments")?
        .as_array()
        .ok_or_else(|| String::from("request-dispatch receive input must be an array"))?;
    let mut chunks = Vec::with_capacity(receive.len());
    for message in receive {
        let message = exact_object(
            message,
            &["type", "body_base64", "more_body"],
            "request-dispatch receive message",
        )?;
        if string_field(message, "type", "request-dispatch receive message")? != "http.request" {
            return Err(String::from(
                "request-dispatch receive messages must be http.request",
            ));
        }
        let body = decode_base64(
            string_field(message, "body_base64", "request-dispatch receive message")?,
            "receive.body_base64",
        )?;
        let more_body = message
            .get("more_body")
            .and_then(Value::as_bool)
            .ok_or_else(|| String::from("receive.more_body must be a boolean"))?;
        chunks.push((body, more_body));
    }
    validate_capture_send(argument_value(
        arguments,
        "send",
        "request-dispatch arguments",
    )?)?;

    Ok(ParsedRequestDispatch {
        method,
        path,
        scope: RequestScope {
            query_string,
            headers: RequestHeaders::new(raw_headers),
        },
        chunks,
    })
}

fn request_observations(
    scope: &RequestScope,
    chunks: &[(Vec<u8>, bool)],
    path_params: &[(String, String)],
    observer: &RequestDispatchObserver,
) -> Result<Value, String> {
    if let RequestDispatchObserver::Cookies(observer) = observer {
        if observer.probe_kind != "items" {
            return Err(String::from(
                "unsupported Rust-native request cookies probe",
            ));
        }
        let cookies = Cookies::from_headers(&scope.headers);
        return Ok(json!({"cookies": cookies.items()}));
    }
    let RequestDispatchObserver::Request(observer) = observer else {
        return Err(String::from(
            "request dispatch observer kind is inconsistent",
        ));
    };
    let path_parameter = path_params
        .iter()
        .find(|(name, _)| name == &observer.path_parameter)
        .ok_or_else(|| String::from("matched request is missing its declared path parameter"))?;
    let path_value = path_parameter.1.parse::<u64>().map_err(|error| {
        format!("converted integer path parameter is outside JSON integer range: {error}")
    })?;

    let query = QueryParams::parse(&scope.query_string);
    let query_values = query.get_list(&observer.query_parameter);
    let query_scalar = query
        .get(&observer.query_parameter)
        .ok_or_else(|| String::from("request is missing its declared query parameter"))?;
    let header_primary = scope
        .headers
        .get(observer.header_primary_case.as_bytes())
        .ok_or_else(|| String::from("request is missing its primary-case header"))?;
    let header_alternate = scope
        .headers
        .get(observer.header_alternate_case.as_bytes())
        .ok_or_else(|| String::from("request is missing its alternate-case header"))?;
    let cookies = Cookies::from_headers(&scope.headers);
    let cookie = cookies
        .get(&observer.cookie_name)
        .ok_or_else(|| String::from("request is missing its declared cookie"))?;

    let mut body_state = RequestBodyAccumulator::default();
    body_state
        .begin_body_collection()
        .map_err(|error| error.to_string())?;
    for (body, more_body) in chunks {
        body_state
            .accept_asgi_message("http.request", body, *more_body)
            .map_err(|error| error.to_string())?;
    }
    let body = body_state.cache_body().map_err(|error| error.to_string())?;
    let json_body: Value = serde_json::from_slice(body)
        .map_err(|error| format!("request body is not valid JSON: {error}"))?;

    Ok(json!({
        "path_param": {"value": path_value, "type": "int"},
        "query_params": {
            "getlist": query_values,
            "scalar": query_scalar,
        },
        "headers": {
            "primary_case": decode_latin1(header_primary),
            "alternate_case": decode_latin1(header_alternate),
        },
        "cookie": cookie,
        "json": json_body,
    }))
}

fn path_params_value(path_params: &[(String, String)]) -> Result<Value, String> {
    let mut output = Map::new();
    for (name, value) in path_params {
        let integer = value.parse::<u64>().map_err(|error| {
            format!("converted integer path parameter is outside JSON integer range: {error}")
        })?;
        output.insert(name.clone(), json!(integer));
    }
    Ok(Value::Object(output))
}

fn decode_latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| char::from(*byte)).collect()
}

fn request_response_transcript(response: &Response) -> Result<Value, String> {
    let mut events = Vec::new();
    for event in response.asgi_events() {
        match event {
            ResponseEvent::Start {
                status_code,
                headers,
            } => events.push(json!({
                "type": "http.response.start",
                "status": status_code,
                "headers": canonical_headers(&headers),
            })),
            ResponseEvent::Body { body } => events.push(json!({
                "type": "http.response.body",
                "body": {"encoding": "base64", "data": encode_base64(&body)},
            })),
        }
    }
    let start = events
        .iter()
        .find(|event| event.get("type").and_then(Value::as_str) == Some("http.response.start"))
        .ok_or_else(|| String::from("request response omitted http.response.start"))?;
    let headers = start
        .get("headers")
        .cloned()
        .ok_or_else(|| String::from("request response start omitted headers"))?;
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .collect::<Vec<_>>();
    Ok(json!({
        "response_status": response.status_code(),
        "ordered_repeated_headers": headers,
        "asgi_event_order": event_order,
        "asgi_events": events,
    }))
}

fn step_arguments<'a>(
    step: &'a Value,
    expected_id: &str,
    expected_operation: &str,
    receiver: Option<&str>,
) -> Result<&'a Map<String, Value>, String> {
    let step_object = exact_object(
        step,
        &["step_id", "surface", "operation", "receiver", "arguments"],
        "workflow step",
    )?;
    if string_field(step_object, "step_id", "workflow step")? != expected_id
        || string_field(step_object, "surface", "workflow step")?
            != "starlette.applications.Starlette"
        || string_field(step_object, "operation", "workflow step")? != expected_operation
    {
        return Err(format!(
            "workflow step {expected_id:?} does not match the declared operation"
        ));
    }
    match (receiver, step_object.get("receiver")) {
        (None, Some(value)) if value.is_null() => {}
        (Some(expected), Some(value)) => {
            let binding = exact_object(value, &["kind", "step_id"], "workflow receiver")?;
            if string_field(binding, "kind", "workflow receiver")? != "binding"
                || string_field(binding, "step_id", "workflow receiver")? != expected
            {
                return Err(format!(
                    "workflow step {expected_id:?} has an invalid receiver binding"
                ));
            }
        }
        _ => {
            return Err(format!(
                "workflow step {expected_id:?} has an invalid receiver"
            ));
        }
    }
    step_object
        .get("arguments")
        .and_then(Value::as_object)
        .ok_or_else(|| format!("workflow step {expected_id:?} arguments must be an object"))
}

fn argument_value<'a>(
    arguments: &'a Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<&'a Value, String> {
    let descriptor = arguments
        .get(name)
        .ok_or_else(|| format!("{context}.{name} is missing"))?;
    let descriptor = exact_object(descriptor, &["kind", "value"], context)?;
    if string_field(descriptor, "kind", context)? != "literal" {
        return Err(format!("{context}.{name} must be an input literal"));
    }
    descriptor
        .get("value")
        .ok_or_else(|| format!("{context}.{name}.value is missing"))
}

fn build_application(step: &Value) -> Result<(NativeApplication, Value, RouteTable), String> {
    let arguments = step_arguments(step, "application", "__init__", None)?;
    let expected_arguments = [
        "debug",
        "routes",
        "middleware",
        "exception_handlers",
        "lifespan",
        "max_body_size",
    ];
    exact_keys(arguments, &expected_arguments, "application arguments")?;
    if argument_value(arguments, "exception_handlers", "application arguments")?
        != &Value::Array(Vec::new())
    {
        return Err(String::from(
            "native Starlette profile does not support custom exception handlers",
        ));
    }

    let routes_value = argument_value(arguments, "routes", "application arguments")?;
    let routes_input = routes_value
        .as_array()
        .filter(|routes| routes.len() == 1)
        .ok_or_else(|| String::from("the declared application requires exactly one route"))?;
    let route = exact_object(
        routes_input
            .first()
            .ok_or_else(|| String::from("route input is missing"))?,
        &["kind", "path", "methods", "endpoint"],
        "route input",
    )?;
    if string_field(route, "kind", "route input")? != "http-route" {
        return Err(String::from("route input kind must be http-route"));
    }
    let path = string_field(route, "path", "route input")?;
    let methods_value = route
        .get("methods")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("route methods must be an array"))?;
    let methods = methods_value
        .iter()
        .map(|method| {
            method
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| String::from("route methods must contain strings"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let endpoint_value = route
        .get("endpoint")
        .ok_or_else(|| String::from("route endpoint is missing"))?;
    let endpoint_kind = endpoint_value
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("route endpoint kind must be a string"))?;
    let response = match endpoint_kind {
        "plain-text-response" => {
            let endpoint = exact_object(
                endpoint_value,
                &["kind", "content", "status_code", "media_type", "cookies"],
                "route endpoint",
            )?;
            let content = string_field(endpoint, "content", "route endpoint")?;
            let status_code = endpoint
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .ok_or_else(|| {
                    String::from("response status_code must be an unsigned 16-bit integer")
                })?;
            let media_type = endpoint
                .get("media_type")
                .and_then(Value::as_str)
                .ok_or_else(|| String::from("response media_type must be a string"))?;
            let mut response = Response::from_content(
                status_code,
                content.as_bytes().to_vec(),
                Some(media_type),
                std::iter::empty::<(String, String)>(),
            )
            .map_err(|error| error.to_string())?;
            let cookies = endpoint
                .get("cookies")
                .and_then(Value::as_array)
                .ok_or_else(|| String::from("response cookies must be an array"))?;
            for cookie in cookies {
                let cookie = exact_object(cookie, &["key", "value"], "response cookie")?;
                let key = string_field(cookie, "key", "response cookie")?;
                let value = string_field(cookie, "value", "response cookie")?;
                response
                    .set_cookie(key, value)
                    .map_err(|error| error.to_string())?;
            }
            response
        }
        "http-exception" => {
            let endpoint = exact_object(
                endpoint_value,
                &["kind", "status_code", "detail", "headers"],
                "HTTP exception endpoint",
            )?;
            let status_code = endpoint
                .get("status_code")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .ok_or_else(|| String::from("HTTP exception status_code must be a u16"))?;
            let detail = match endpoint.get("detail") {
                Some(Value::String(detail)) => Some(detail.as_str()),
                Some(Value::Null) => None,
                _ => {
                    return Err(String::from(
                        "HTTP exception detail must be a string or null",
                    ));
                }
            };
            let headers = endpoint
                .get("headers")
                .and_then(Value::as_array)
                .ok_or_else(|| String::from("HTTP exception headers must be an array"))?
                .iter()
                .map(|header| {
                    let pair = header
                        .as_array()
                        .filter(|pair| pair.len() == 2)
                        .ok_or_else(|| String::from("HTTP exception headers must be pairs"))?;
                    let name = pair[0].as_str().ok_or_else(|| {
                        String::from("HTTP exception header names must be strings")
                    })?;
                    let value = pair[1].as_str().ok_or_else(|| {
                        String::from("HTTP exception header values must be strings")
                    })?;
                    Ok((name.to_owned(), value.to_owned()))
                })
                .collect::<Result<Vec<_>, String>>()?;
            Response::http_exception(status_code, detail, &headers)
                .map_err(|error| error.to_string())?
        }
        _ => {
            return Err(format!(
                "unsupported route endpoint kind: {endpoint_kind:?}"
            ));
        }
    };
    let lifespan_spec = argument_value(arguments, "lifespan", "application arguments")?;
    let lifespan_object = lifespan_spec
        .as_object()
        .ok_or_else(|| String::from("lifespan input must be a JSON object"))?;
    let lifespan_kind = string_field(lifespan_object, "kind", "lifespan input")?;
    let lifespan_spec = match lifespan_kind {
        "async-context-manager" => exact_object(
            lifespan_spec,
            &["kind", "record_entry", "record_exit"],
            "lifespan input",
        )?,
        "async-generator" => validate_async_generator_lifespan(lifespan_spec)?,
        _ => {
            return Err(String::from(
                "native lifespan kind must be async-context-manager or async-generator",
            ));
        }
    };
    let mut route_table = RouteTable::new();
    route_table
        .add_route(path, methods.clone())
        .map_err(|error| error.to_string())?;
    let application = NativeApplication::new([ApplicationRoute::new(path, methods, response)])
        .map_err(|error| error.to_string())?;
    Ok((
        application,
        Value::Object(lifespan_spec.clone()),
        route_table,
    ))
}

struct LifecycleResult {
    value: Value,
}

struct LifecycleSession {
    state: LifespanState,
    trace: Vec<String>,
    events: Vec<Value>,
    shutdown_message: String,
    record_exit: bool,
}

fn validate_async_generator_lifespan(lifespan_spec: &Value) -> Result<&Map<String, Value>, String> {
    const REQUIRED_FIELDS: [&str; 7] = [
        "kind",
        "record_entry",
        "record_exit",
        "failure_stage",
        "failure_message",
        "yield_behavior",
        "shutdown_exception_behavior",
    ];
    const OPTIONAL_FIELDS: [&str; 2] = ["failure_exception_type", "yield_state"];
    let object = lifespan_spec
        .as_object()
        .ok_or_else(|| String::from("lifespan input must be a JSON object"))?;
    if REQUIRED_FIELDS
        .iter()
        .any(|field| !object.contains_key(*field))
        || object.keys().any(|field| {
            !REQUIRED_FIELDS.contains(&field.as_str()) && !OPTIONAL_FIELDS.contains(&field.as_str())
        })
    {
        return Err(String::from(
            "async-generator lifespan input has invalid fields",
        ));
    }
    if !bool_field(object, "record_entry", "lifespan input")?
        || !bool_field(object, "record_exit", "lifespan input")?
    {
        return Err(String::from(
            "async-generator lifespan input must record entry and exit effects",
        ));
    }
    let failure_stage = string_field(object, "failure_stage", "lifespan input")?;
    if !["none", "startup", "shutdown"].contains(&failure_stage) {
        return Err(String::from(
            "async-generator lifespan failure_stage is unsupported",
        ));
    }
    string_field(object, "failure_message", "lifespan input")?;
    let yield_behavior = string_field(object, "yield_behavior", "lifespan input")?;
    if !["none", "single", "extra"].contains(&yield_behavior) {
        return Err(String::from(
            "async-generator lifespan yield_behavior is unsupported",
        ));
    }
    let shutdown_behavior = string_field(object, "shutdown_exception_behavior", "lifespan input")?;
    if !["propagate", "suppress"].contains(&shutdown_behavior) {
        return Err(String::from(
            "async-generator shutdown exception behavior is unsupported",
        ));
    }
    let exception_type = object
        .get("failure_exception_type")
        .and_then(Value::as_str)
        .unwrap_or("RuntimeError");
    if !["RuntimeError", "CancelledError"].contains(&exception_type) {
        return Err(String::from(
            "async-generator failure exception type is unsupported",
        ));
    }
    if exception_type == "CancelledError" && failure_stage == "none" {
        return Err(String::from(
            "async-generator cancellation requires a failure stage",
        ));
    }
    if let Some(yield_state) = object.get("yield_state") {
        if !yield_state.is_null() && !yield_state.is_object() {
            return Err(String::from(
                "async-generator yield_state must be an object or null",
            ));
        }
        if !yield_state.is_null() && yield_behavior == "none" {
            return Err(String::from(
                "async-generator without a yield cannot supply lifespan state",
            ));
        }
    }
    Ok(object)
}

fn run_lifespan_only(
    step: &Value,
    lifespan_spec: &Value,
    schedule: &[&str],
) -> Result<Value, String> {
    let arguments = step_arguments(step, "lifecycle", "__call__", Some("application"))?;
    exact_keys(
        arguments,
        &["scope", "receive", "send"],
        "lifespan arguments",
    )?;
    let scope = argument_value(arguments, "scope", "lifespan arguments")?;
    let scope_object = exact_object(scope, &["type", "asgi"], "lifespan scope")?;
    let scope_type = string_field(scope_object, "type", "lifespan scope")?;
    if classify_scope(scope_type) != AsgiScopeKind::Lifespan {
        return Err(String::from("lifecycle scope must classify as lifespan"));
    }
    validate_capture_send(argument_value(arguments, "send", "lifespan arguments")?)?;
    if schedule != ["lifespan.startup", "lifespan.shutdown"] {
        return Err(String::from(
            "lifecycle-only workflow must schedule startup and shutdown",
        ));
    }

    let receive = argument_value(arguments, "receive", "lifespan arguments")?
        .as_array()
        .filter(|actions| actions.len() == schedule.len())
        .ok_or_else(|| {
            String::from("lifecycle-only workflow must supply each scheduled receive outcome")
        })?;
    let startup_action = receive
        .first()
        .ok_or_else(|| String::from("lifespan startup receive action is missing"))?;
    let startup_action = exact_object(
        startup_action,
        &["kind", "message"],
        "lifespan startup receive action",
    )?;
    if string_field(startup_action, "kind", "lifespan startup receive action")? != "message" {
        return Err(String::from(
            "lifecycle-only workflow startup receive must supply a message",
        ));
    }
    let startup_message = exact_object(
        startup_action
            .get("message")
            .ok_or_else(|| String::from("lifespan startup action omitted its message"))?,
        &["type"],
        "lifespan startup message",
    )?;
    let startup_type = string_field(startup_message, "type", "lifespan startup message")?;
    let shutdown_action_value = receive
        .get(1)
        .ok_or_else(|| String::from("lifespan shutdown receive action is missing"))?;
    let shutdown_action = shutdown_action_value
        .as_object()
        .ok_or_else(|| String::from("lifespan shutdown receive action must be an object"))?;
    let shutdown_receive_failure =
        match string_field(shutdown_action, "kind", "lifespan shutdown receive action")? {
            "message" => {
                let shutdown_action = exact_object(
                    shutdown_action_value,
                    &["kind", "message"],
                    "lifespan shutdown receive action",
                )?;
                let shutdown_message = exact_object(
                    shutdown_action.get("message").ok_or_else(|| {
                        String::from("lifespan shutdown action omitted its message")
                    })?,
                    &["type"],
                    "lifespan shutdown message",
                )?;
                if string_field(shutdown_message, "type", "lifespan shutdown message")?
                    != schedule[1]
                {
                    return Err(String::from(
                        "lifecycle-only workflow shutdown message must match its schedule",
                    ));
                }
                None
            }
            "raise" => {
                let shutdown_action = exact_object(
                    shutdown_action_value,
                    &["kind", "exception_type", "message"],
                    "lifespan shutdown receive action",
                )?;
                if string_field(
                    shutdown_action,
                    "exception_type",
                    "lifespan shutdown receive action",
                )? != "RuntimeError"
                {
                    return Err(String::from(
                        "lifecycle-only shutdown receive failure must be RuntimeError",
                    ));
                }
                Some(string_field(
                    shutdown_action,
                    "message",
                    "lifespan shutdown receive action",
                )?)
            }
            _ => {
                return Err(String::from(
                    "lifecycle-only shutdown receive must supply shutdown or raise",
                ));
            }
        };
    if startup_type != schedule[0] || schedule != ["lifespan.startup", "lifespan.shutdown"] {
        return Err(String::from(
            "lifecycle-only workflow receive actions must match the execution schedule",
        ));
    }

    let lifespan_spec = lifespan_spec
        .as_object()
        .ok_or_else(|| String::from("lifespan input must be a JSON object"))?;
    let lifespan_kind = string_field(lifespan_spec, "kind", "lifespan input")?;
    let record_entry = bool_field(lifespan_spec, "record_entry", "lifespan input")?;
    let record_exit = bool_field(lifespan_spec, "record_exit", "lifespan input")?;
    let failure_stage = if lifespan_kind == "async-generator" {
        string_field(lifespan_spec, "failure_stage", "lifespan input")?
    } else if lifespan_kind == "async-context-manager" {
        "none"
    } else {
        return Err(String::from("unsupported lifecycle-only lifespan input"));
    };
    let mut events = Vec::new();
    let mut trace = Vec::new();
    let mut state = LifespanState::new();
    let startup_action = state
        .startup_received(startup_type)
        .map_err(|error| error.to_string())?;
    if startup_action != LifespanAction::EnterContext {
        return Err(String::from(
            "lifespan startup did not request context entry",
        ));
    }
    if record_entry {
        trace.push(String::from("entry"));
    }

    let warnings = if lifespan_kind == "async-generator" {
        vec![json!({
            "category": "starlette.exceptions.StarletteDeprecationWarning",
            "message": "async generator function lifespans are deprecated, use an @contextlib.asynccontextmanager function instead",
        })]
    } else {
        Vec::new()
    };
    let failure = if failure_stage == "none" {
        None
    } else {
        Some(lifespan_failure_error(lifespan_spec)?)
    };

    if failure_stage == "startup" {
        let message_type = state.startup_failed().map_err(|error| error.to_string())?;
        events.push(lifespan_failure_event(message_type, failure.as_ref())?);
        let value = lifecycle_observation_value(events, trace, warnings);
        return Ok(json!({
            "step_id": "lifecycle",
            "status": "error",
            "error": failure.ok_or_else(|| String::from("startup failure input omitted its error"))?,
            "partial_value": value,
        }));
    }

    let startup_completion = state.context_entered().map_err(|error| error.to_string())?;
    if startup_completion != LifespanAction::SendStartupComplete {
        return Err(String::from(
            "lifespan startup completion action is invalid",
        ));
    }
    events.push(lifespan_event(startup_completion)?);
    let shutdown_action = state
        .shutdown_received("lifespan.shutdown")
        .map_err(|error| error.to_string())?;
    if shutdown_action != LifespanAction::ExitContext {
        return Err(String::from(
            "lifespan shutdown did not request context exit",
        ));
    }
    if let Some(message) = shutdown_receive_failure {
        if failure_stage != "none" {
            return Err(String::from(
                "lifecycle-only shutdown receive failure cannot combine with a generator failure",
            ));
        }
        let shutdown_behavior = string_field(
            lifespan_spec,
            "shutdown_exception_behavior",
            "lifespan input",
        )?;
        if shutdown_behavior == "suppress" {
            trace.push(String::from("suppressed-shutdown-error"));
            if record_exit {
                trace.push(String::from("exit"));
            }
            let shutdown_completion = state
                .context_exit_suppressed()
                .map_err(|error| error.to_string())?;
            if shutdown_completion != LifespanAction::SendShutdownComplete {
                return Err(String::from(
                    "suppressed lifespan shutdown did not select shutdown completion",
                ));
            }
            events.push(lifespan_event(shutdown_completion)?);
            if state.phase() != starlette_rs::LifespanPhase::Complete {
                return Err(String::from(
                    "suppressed lifespan shutdown did not complete the lifecycle",
                ));
            }
            return Ok(json!({
                "step_id": "lifecycle",
                "status": "ok",
                "value": lifecycle_observation_value(events, trace, warnings),
            }));
        }

        if record_exit {
            trace.push(String::from("exit"));
        }
        let error = json!({
            "class": "builtins.RuntimeError",
            "kind": "exception",
            "message": message,
            "stage": "lifespan",
            "code": null,
            "cause": null,
            "suppress_context": false,
        });
        let message_type = state
            .shutdown_failed()
            .map_err(|transition_error| transition_error.to_string())?;
        events.push(lifespan_failure_event(message_type, Some(&error))?);
        return Ok(json!({
            "step_id": "lifecycle",
            "status": "error",
            "error": error,
            "partial_value": lifecycle_observation_value(events, trace, warnings),
        }));
    }

    if record_exit {
        trace.push(String::from("exit"));
    }
    if failure_stage == "shutdown" {
        let message_type = state.shutdown_failed().map_err(|error| error.to_string())?;
        events.push(lifespan_failure_event(message_type, failure.as_ref())?);
        let value = lifecycle_observation_value(events, trace, warnings);
        return Ok(json!({
            "step_id": "lifecycle",
            "status": "error",
            "error": failure.ok_or_else(|| String::from("shutdown failure input omitted its error"))?,
            "partial_value": value,
        }));
    }

    let shutdown_completion = state.context_exited().map_err(|error| error.to_string())?;
    if shutdown_completion != LifespanAction::SendShutdownComplete {
        return Err(String::from(
            "lifespan shutdown completion action is invalid",
        ));
    }
    events.push(lifespan_event(shutdown_completion)?);
    if state.phase() != starlette_rs::LifespanPhase::Complete {
        return Err(String::from(
            "lifecycle-only input did not complete startup and shutdown",
        ));
    }
    Ok(json!({
        "step_id": "lifecycle",
        "status": "ok",
        "value": lifecycle_observation_value(events, trace, warnings),
    }))
}

fn lifespan_failure_error(lifespan_spec: &Map<String, Value>) -> Result<Value, String> {
    let exception_type = lifespan_spec
        .get("failure_exception_type")
        .and_then(Value::as_str)
        .unwrap_or("RuntimeError");
    let class = match exception_type {
        "RuntimeError" => "builtins.RuntimeError",
        "CancelledError" => "asyncio.exceptions.CancelledError",
        _ => return Err(String::from("unsupported lifespan failure exception type")),
    };
    Ok(json!({
        "class": class,
        "kind": "exception",
        "message": string_field(lifespan_spec, "failure_message", "lifespan input")?,
        "stage": "lifespan",
        "code": null,
        "cause": null,
        "suppress_context": false,
    }))
}

fn lifespan_failure_event(message_type: &str, error: Option<&Value>) -> Result<Value, String> {
    if !["lifespan.startup.failed", "lifespan.shutdown.failed"].contains(&message_type) {
        return Err(String::from(
            "lifespan failure transition returned an invalid event",
        ));
    }
    let error = error.ok_or_else(|| String::from("lifespan failure event omitted its error"))?;
    let fields = exact_object(
        error,
        &[
            "class",
            "kind",
            "message",
            "stage",
            "code",
            "cause",
            "suppress_context",
        ],
        "lifespan failure error",
    )?;
    string_field(fields, "class", "lifespan failure error")?;
    string_field(fields, "message", "lifespan failure error")?;
    Ok(json!({"type": message_type}))
}

fn lifecycle_observation_value(
    events: Vec<Value>,
    trace: Vec<String>,
    warnings: Vec<Value>,
) -> Value {
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    json!({
        "response_status": null,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": event_order,
        "asgi_events": events,
        "lifespan_scope_state": {"present": false, "value": null},
        "lifecycle_and_cleanup_effects": trace,
        "server_error_observation": {"handler_calls": [], "debug_traceback": null},
        "deprecation_warnings": warnings,
        "sync_endpoint_observations": null,
    })
}

fn begin_lifespan(step: &Value, lifespan_spec: &Value) -> Result<LifecycleSession, String> {
    let arguments = step_arguments(step, "lifecycle", "__call__", Some("application"))?;
    exact_keys(
        arguments,
        &["scope", "receive", "send"],
        "lifespan arguments",
    )?;
    let scope = argument_value(arguments, "scope", "lifespan arguments")?;
    let scope_type = string_field(
        exact_object(scope, &["type", "asgi"], "lifespan scope")?,
        "type",
        "lifespan scope",
    )?;
    if classify_scope(scope_type) != AsgiScopeKind::Lifespan {
        return Err(String::from("lifecycle scope must classify as lifespan"));
    }
    validate_capture_send(argument_value(arguments, "send", "lifespan arguments")?)?;

    let record_entry = lifespan_spec
        .get("record_entry")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("lifespan record_entry must be boolean"))?;
    let record_exit = lifespan_spec
        .get("record_exit")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("lifespan record_exit must be boolean"))?;
    let receive = argument_value(arguments, "receive", "lifespan arguments")?
        .as_array()
        .filter(|messages| messages.len() == 2)
        .ok_or_else(|| {
            String::from("interleaved lifespan requires startup and shutdown messages")
        })?;
    let startup_message = receive
        .first()
        .ok_or_else(|| String::from("lifespan startup message is missing"))?;
    let startup_type = string_field(
        exact_object(startup_message, &["type"], "lifespan startup message")?,
        "type",
        "lifespan startup message",
    )?;
    let shutdown_message = receive
        .get(1)
        .ok_or_else(|| String::from("lifespan shutdown message is missing"))?;
    let shutdown_message = string_field(
        exact_object(shutdown_message, &["type"], "lifespan shutdown message")?,
        "type",
        "lifespan shutdown message",
    )?
    .to_owned();

    let mut state = LifespanState::new();
    let mut trace = Vec::new();
    let mut events = Vec::new();
    let action = state
        .startup_received(startup_type)
        .map_err(|error| error.to_string())?;
    if action != LifespanAction::EnterContext {
        return Err(String::from(
            "lifespan startup did not request context entry",
        ));
    }
    if record_entry {
        trace.push(String::from("entry"));
    }
    let completion = state.context_entered().map_err(|error| error.to_string())?;
    events.push(lifespan_event(completion)?);
    if state.phase() != starlette_rs::LifespanPhase::Running {
        return Err(String::from(
            "lifespan startup did not reach the running phase",
        ));
    }

    Ok(LifecycleSession {
        state,
        trace,
        events,
        shutdown_message,
        record_exit,
    })
}

fn finish_lifespan(
    mut session: LifecycleSession,
    intervening_events: &[Value],
) -> Result<LifecycleResult, String> {
    session.events.extend_from_slice(intervening_events);
    let action = session
        .state
        .shutdown_received(&session.shutdown_message)
        .map_err(|error| error.to_string())?;
    if action != LifespanAction::ExitContext {
        return Err(String::from(
            "lifespan shutdown did not request context exit",
        ));
    }
    if session.record_exit {
        session.trace.push(String::from("exit"));
    }
    let completion = session
        .state
        .context_exited()
        .map_err(|error| error.to_string())?;
    session.events.push(lifespan_event(completion)?);
    if session.state.phase() != starlette_rs::LifespanPhase::Complete {
        return Err(String::from(
            "lifespan input did not complete startup and shutdown",
        ));
    }
    let event_order = session
        .events
        .iter()
        .filter_map(|event: &Value| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let value = json!({
        "response_status": null,
        "ordered_repeated_headers": [],
        "response_bytes": {"encoding": "base64", "data": ""},
        "asgi_event_order": event_order,
        "asgi_events": session.events,
        "lifespan_scope_state": {"present": false, "value": null},
        "lifecycle_and_cleanup_effects": session.trace,
        "server_error_observation": {"handler_calls": [], "debug_traceback": null},
        "deprecation_warnings": [],
        "sync_endpoint_observations": null,
    });
    Ok(LifecycleResult { value })
}

fn lifespan_event(action: LifespanAction) -> Result<Value, String> {
    let message_type = match action {
        LifespanAction::SendStartupComplete => "lifespan.startup.complete",
        LifespanAction::SendShutdownComplete => "lifespan.shutdown.complete",
        LifespanAction::EnterContext | LifespanAction::ExitContext => {
            return Err(String::from(
                "context action is not an ASGI lifespan completion",
            ));
        }
    };
    Ok(json!({"type": message_type}))
}

fn run_dispatch(
    step: &Value,
    application: &NativeApplication,
    route_table: &RouteTable,
    lifecycle_trace: &[String],
) -> Result<Value, String> {
    let arguments = step_arguments(step, "dispatch", "__call__", Some("application"))?;
    exact_keys(
        arguments,
        &["scope", "receive", "send"],
        "dispatch arguments",
    )?;
    let scope = argument_value(arguments, "scope", "dispatch arguments")?;
    let scope_object = exact_object(
        scope,
        &[
            "type",
            "asgi",
            "http_version",
            "method",
            "scheme",
            "path",
            "raw_path_base64",
            "query_string_base64",
            "root_path",
            "headers_base64_pairs",
            "client",
            "server",
        ],
        "HTTP scope input",
    )?;
    let scope_type = string_field(scope_object, "type", "HTTP scope input")?;
    if classify_scope(scope_type) != AsgiScopeKind::Http {
        return Err(String::from("dispatch scope must classify as http"));
    }
    let path = string_field(scope_object, "path", "HTTP scope input")?;
    let method = string_field(scope_object, "method", "HTTP scope input")?;
    let root_path = string_field(scope_object, "root_path", "HTTP scope input")?;
    let query_string = decode_base64(
        string_field(scope_object, "query_string_base64", "HTTP scope input")?,
        "scope.query_string_base64",
    )?;
    let receive_value = argument_value(arguments, "receive", "dispatch arguments")?;
    let receive_messages = parse_http_receive_messages(receive_value)?;
    let mut receive_index = 0usize;
    let mut receive = || {
        let message = receive_messages.get(receive_index).cloned();
        receive_index = receive_index.saturating_add(usize::from(message.is_some()));
        ready(message)
    };
    let send = argument_value(arguments, "send", "dispatch arguments")?;
    validate_capture_send(send)?;
    let mut events = Vec::new();
    let route_match = route_table.matches_detailed_with_root_path(path, root_path, method);
    let redirect = if matches!(&route_match, DetailedRouteMatch::NotFound) {
        route_table
            .find_slash_redirect_path(path, root_path, method)
            .map(|candidate| scope_url(scope_object, &candidate, &query_string))
            .transpose()?
            .map(|location| Response::redirect(&location, 307, &[]))
            .transpose()
            .map_err(|error| error.to_string())?
    } else {
        None
    };
    if let Some(response) = redirect {
        events.extend(
            response
                .asgi_events()
                .into_iter()
                .map(canonical_response_event),
        );
    } else {
        let scope = HttpScope::new(path, method);
        let mut send = |event: ResponseEvent| {
            events.push(canonical_response_event(event));
            ready(Ok::<(), String>(()))
        };
        let _dispatch = block_on_ready(application.call(&scope, &mut receive, &mut send))
            .map_err(|error| format!("native application future did not complete: {error}"))?
            .map_err(|error| error.to_string())?;
    }
    if receive_index != 0 {
        return Err(String::from(
            "the declared response-only route unexpectedly consumed request input",
        ));
    }

    let mut body = Vec::new();
    for event in &events {
        if event.get("type").and_then(Value::as_str) == Some("http.response.body") {
            let encoded = event
                .pointer("/body/data")
                .and_then(Value::as_str)
                .ok_or_else(|| String::from("response body event omitted its encoded body"))?;
            body.extend_from_slice(&decode_base64(encoded, "response body event")?);
        }
    }
    let event_order = events
        .iter()
        .filter_map(|event| event.get("type").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    let start = events
        .iter()
        .find(|event| event.get("type").and_then(Value::as_str) == Some("http.response.start"))
        .ok_or_else(|| String::from("response did not emit http.response.start"))?;
    let status_code = start
        .get("status")
        .cloned()
        .ok_or_else(|| String::from("response start is missing its status"))?;
    let ordered_headers = start
        .get("headers")
        .cloned()
        .ok_or_else(|| String::from("response start is missing its headers"))?;
    Ok(json!({
        "response_status": status_code,
        "ordered_repeated_headers": ordered_headers,
        "response_bytes": {"encoding": "base64", "data": encode_base64(&body)},
        "asgi_event_order": event_order,
        "asgi_events": events,
        "lifespan_scope_state": {"present": false, "value": null},
        "lifecycle_and_cleanup_effects": lifecycle_trace,
        "server_error_observation": {"handler_calls": [], "debug_traceback": null},
        "deprecation_warnings": [],
        "sync_endpoint_observations": null,
    }))
}

fn parse_http_receive_messages(value: &Value) -> Result<Vec<(Vec<u8>, bool)>, String> {
    let messages = value
        .as_array()
        .ok_or_else(|| String::from("HTTP receive input must be an array"))?;
    messages
        .iter()
        .map(|message| {
            let message = exact_object(
                message,
                &["type", "body_base64", "more_body"],
                "HTTP receive message",
            )?;
            if string_field(message, "type", "HTTP receive message")? != "http.request" {
                return Err(String::from("HTTP receive messages must be http.request"));
            }
            let body = string_field(message, "body_base64", "HTTP receive message")?;
            let body = decode_base64(body, "HTTP receive body")?;
            let more_body = message
                .get("more_body")
                .and_then(Value::as_bool)
                .ok_or_else(|| String::from("HTTP receive more_body must be boolean"))?;
            Ok((body, more_body))
        })
        .collect()
}

fn canonical_response_event(event: ResponseEvent) -> Value {
    match event {
        ResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers": canonical_headers(&headers),
        }),
        ResponseEvent::Body { body } => json!({
            "type": "http.response.body",
            "body": {"encoding": "base64", "data": encode_base64(&body)},
        }),
    }
}

fn canonical_file_response_event(event: FileResponseEvent, websocket: bool) -> Value {
    match event {
        FileResponseEvent::Start {
            status_code,
            headers,
        } if websocket => json!({
            "type": "websocket.http.response.start",
            "status": status_code,
            "headers_base64_pairs": canonical_headers(&headers),
        }),
        FileResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers": canonical_headers(&headers),
        }),
        FileResponseEvent::Body { body, more_body } if websocket => {
            let mut event = json!({
                "type": "websocket.http.response.body",
                "body_base64": encode_base64(&body),
            });
            if let Some(more_body) = more_body {
                event["more_body"] = json!(more_body);
            }
            event
        }
        FileResponseEvent::Body { body, more_body } => {
            let mut event = json!({
                "type": "http.response.body",
                "body": {"encoding": "base64", "data": encode_base64(&body)},
            });
            if let Some(more_body) = more_body {
                event["more_body"] = json!(more_body);
            }
            event
        }
        FileResponseEvent::Pathsend { path } => json!({
            "type": "http.response.pathsend",
            "path": path,
        }),
    }
}

fn canonical_streaming_response_event(event: StreamingResponseEvent) -> Value {
    match event {
        StreamingResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers": canonical_headers(&headers),
        }),
        StreamingResponseEvent::Body { body, more_body } => json!({
            "type": "http.response.body",
            "body": {"encoding": "base64", "data": encode_base64(&body)},
            "more_body": more_body,
        }),
    }
}

fn block_on_ready<F: Future>(future: F) -> Result<F::Output, &'static str> {
    let mut context = Context::from_waker(Waker::noop());
    let mut future = Box::pin(future);
    match future.as_mut().poll(&mut context) {
        Poll::Ready(output) => Ok(output),
        Poll::Pending => Err("the parity send callback yielded pending work"),
    }
}

fn canonical_headers(headers: &[(Vec<u8>, Vec<u8>)]) -> Vec<Value> {
    headers
        .iter()
        .map(|(name, value)| json!([encode_base64(name), encode_base64(value)]))
        .collect()
}

fn scope_url(
    scope: &Map<String, Value>,
    path: &str,
    query_string: &[u8],
) -> Result<String, String> {
    let scheme = scope
        .get("scheme")
        .and_then(Value::as_str)
        .unwrap_or("http");
    let query = String::from_utf8(query_string.to_vec())
        .map_err(|error| format!("scope query string is not UTF-8: {error}"))?;

    let mut host_header = None;
    let headers = scope
        .get("headers_base64_pairs")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("scope.headers_base64_pairs must be an array"))?;
    for (index, pair) in headers.iter().enumerate() {
        let pair = pair
            .as_array()
            .filter(|pair| pair.len() == 2)
            .ok_or_else(|| format!("scope header[{index}] must be a pair"))?;
        let name = decode_base64(
            pair[0]
                .as_str()
                .ok_or_else(|| format!("scope header[{index}] name must be base64"))?,
            "scope header name",
        )?;
        let value = decode_base64(
            pair[1]
                .as_str()
                .ok_or_else(|| format!("scope header[{index}] value must be base64"))?,
            "scope header value",
        )?;
        if name == b"host" {
            let candidate = decode_latin1(&value);
            if valid_host_header(&candidate) {
                host_header = Some(candidate);
            }
            break;
        }
    }

    let netloc = if let Some(host_header) = host_header {
        Some(host_header)
    } else {
        match scope.get("server") {
            None | Some(Value::Null) => None,
            Some(Value::Array(server)) if server.len() == 2 => {
                let host = server[0]
                    .as_str()
                    .ok_or_else(|| String::from("scope.server host must be a string"))?;
                let port = server[1]
                    .as_u64()
                    .ok_or_else(|| String::from("scope.server port must be unsigned"))?;
                let default_port = match scheme {
                    "http" | "ws" => 80,
                    "https" | "wss" => 443,
                    _ => return Err(format!("unsupported URL scheme {scheme:?}")),
                };
                Some(if port == default_port {
                    host.to_owned()
                } else {
                    format!("{host}:{port}")
                })
            }
            Some(_) => return Err(String::from("scope.server must be a pair or null")),
        }
    };

    let mut url = if let Some(netloc) = netloc {
        format!("{scheme}://{netloc}{path}")
    } else {
        path.to_owned()
    };
    if !query.is_empty() {
        url.push('?');
        url.push_str(&query);
    }
    Ok(url)
}

fn valid_host_header(value: &str) -> bool {
    if let Some(bracketed) = value.strip_prefix('[') {
        let Some(end) = bracketed.find(']') else {
            return false;
        };
        let address = &bracketed[..end];
        let Some(suffix_start) = end.checked_add(1) else {
            return false;
        };
        let suffix = &bracketed[suffix_start..];
        let Some((left, right)) = address.split_once(':') else {
            return false;
        };
        if !left.bytes().all(|byte| byte.is_ascii_hexdigit())
            || right.is_empty()
            || !right
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() || matches!(byte, b':' | b'.'))
        {
            return false;
        }
        if suffix.is_empty() {
            return true;
        }
        let Some(port) = suffix.strip_prefix(':') else {
            return false;
        };
        return !port.is_empty() && port.bytes().all(|byte| byte.is_ascii_digit());
    }

    let (host, port) = if let Some((host, port)) = value.rsplit_once(':') {
        if host.contains(':') {
            return false;
        }
        (host, Some(port))
    } else {
        (value, None)
    };

    !host.is_empty()
        && host
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-'))
        && port
            .is_none_or(|port| !port.is_empty() && port.bytes().all(|byte| byte.is_ascii_digit()))
}

fn validate_capture_send(send: &Value) -> Result<(), String> {
    let send = exact_object(send, &["kind"], "ASGI send input")?;
    if string_field(send, "kind", "ASGI send input")? != "capture-asgi-send" {
        return Err(String::from(
            "send input must select the declared ASGI event collector",
        ));
    }
    Ok(())
}

fn exact_keys(object: &Map<String, Value>, expected: &[&str], context: &str) -> Result<(), String> {
    let mut actual: Vec<&str> = object.keys().map(String::as_str).collect();
    actual.sort_unstable();
    let mut wanted = expected.to_vec();
    wanted.sort_unstable();
    if actual != wanted {
        return Err(format!(
            "{context} fields differ: expected {wanted:?}, got {actual:?}"
        ));
    }
    Ok(())
}

fn decode_base64(value: &str, context: &str) -> Result<Vec<u8>, String> {
    let input = value.as_bytes();
    let chunks = input.chunks_exact(4);
    if !chunks.remainder().is_empty() {
        return Err(format!("{context} is invalid base64"));
    }
    let chunk_count = chunks.len();
    let decoded_capacity = chunk_count
        .checked_mul(3)
        .ok_or_else(|| format!("{context} decoded length overflow"))?;
    let mut decoded = Vec::new();
    decoded
        .try_reserve_exact(decoded_capacity)
        .map_err(|_| format!("{context} decoded value is too large"))?;
    for (index, chunk) in chunks.enumerate() {
        let final_chunk = checked_usize_add(index, 1, "base64 chunk index")? == chunk_count;
        let first = base64_value(chunk[0]).ok_or_else(|| format!("{context} is invalid base64"))?;
        let second =
            base64_value(chunk[1]).ok_or_else(|| format!("{context} is invalid base64"))?;
        let pad_two = chunk[2] == b'=';
        let pad_three = chunk[3] == b'=';
        if (pad_two && !pad_three) || (pad_three && !final_chunk) {
            return Err(format!("{context} is invalid base64"));
        }
        let third = if pad_two {
            0
        } else {
            base64_value(chunk[2]).ok_or_else(|| format!("{context} is invalid base64"))?
        };
        let fourth = if pad_three {
            0
        } else {
            base64_value(chunk[3]).ok_or_else(|| format!("{context} is invalid base64"))?
        };
        if (pad_two && second & 0x0f != 0) || (pad_three && !pad_two && third & 0x03 != 0) {
            return Err(format!("{context} is invalid base64"));
        }
        decoded.push((first << 2) | (second >> 4));
        if !pad_two {
            decoded.push((second << 4) | (third >> 2));
        }
        if !pad_three {
            decoded.push((third << 6) | fourth);
        }
    }
    if encode_base64(&decoded) != value {
        return Err(format!("{context} is invalid or non-canonical base64"));
    }
    Ok(decoded)
}

fn base64_value(value: u8) -> Option<u8> {
    match value {
        b'A'..=b'Z' => value.checked_sub(b'A'),
        b'a'..=b'z' => value.checked_sub(b'a')?.checked_add(26),
        b'0'..=b'9' => value.checked_sub(b'0')?.checked_add(52),
        b'+' => Some(62),
        b'/' => Some(63),
        _ => None,
    }
}

fn encode_base64(bytes: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut encoded = String::new();
    let mut offset = 0;
    while let Some(first) = bytes.get(offset).copied() {
        let second = offset
            .checked_add(1)
            .and_then(|index| bytes.get(index))
            .copied();
        let third = offset
            .checked_add(2)
            .and_then(|index| bytes.get(index))
            .copied();
        push_base64_character(&mut encoded, TABLE, usize::from(first >> 2));
        let second_index =
            (usize::from(first & 0b11) << 4) | second.map_or(0, |byte| usize::from(byte >> 4));
        push_base64_character(&mut encoded, TABLE, second_index);
        match second {
            Some(second) => {
                let third_index = (usize::from(second & 0b1111) << 2)
                    | third.map_or(0, |byte| usize::from(byte >> 6));
                push_base64_character(&mut encoded, TABLE, third_index);
            }
            None => encoded.push('='),
        }
        match third {
            Some(third) => {
                push_base64_character(&mut encoded, TABLE, usize::from(third & 0b0011_1111))
            }
            None => encoded.push('='),
        }
        let Some(next_offset) = offset.checked_add(3) else {
            break;
        };
        offset = next_offset;
    }
    encoded
}

fn push_base64_character(encoded: &mut String, table: &[u8; 64], index: usize) {
    if let Some(character) = table.get(index) {
        encoded.push(char::from(*character));
    }
}
