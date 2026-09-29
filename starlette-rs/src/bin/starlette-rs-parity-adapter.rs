//! Process-isolated native adapter for the first Starlette migration-parity slice.

use std::env;
use std::fs;
use std::future::{Future, ready};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::str::FromStr;
use std::sync::atomic::{AtomicU64, Ordering};
use std::task::{Context, Poll, Waker};

#[cfg(unix)]
use std::ffi::CString;
#[cfg(unix)]
use std::os::unix::ffi::OsStrExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

// The workspace's flate2 dependency is used by the companion library target.
use flate2 as _;
use getrandom as _;
use httpdate as _;
use md5 as _;
use mime_guess as _;
use serde_json::{Map, Number, Value, json};
use sha2::{Digest, Sha256};
use starlette_rs::{
    ApplicationRoute, AsgiScopeKind, CookieOptions, Cookies, DEFAULT_EXCLUDED_CONTENT_TYPES,
    DetailedRouteMatch, FileMetadata, FileResponse as NativeFileResponse, FileResponseCallInput,
    FileResponseCallStep, FileResponseEvent, FileResponseOptions, GzipConfig, GzipHeader,
    GzipResponseStart, HttpScope, LifespanAction, LifespanState, Mount as NativeMount, MountChild,
    MountScope, PathConverter, PathParameterCapture, QueryParams, RequestBodyAccumulator,
    RequestHeaders, Response, ResponseEvent, RouteTable, Starlette as NativeApplication,
    StaticFiles as NativeStaticFiles, StaticFilesError, StaticFilesResponse, StreamingResponse,
    StreamingResponseEvent, WebSocketState, WebSocketStateMachine, classify_scope, connection_url,
};

const REQUEST_SCHEMA: &str = "migration-parity/adapter-request@1";
const RESPONSE_SCHEMA: &str = "migration-parity/adapter-response@1";
const SUBJECT_ID: &str = "rust-native";
const REDIRECT_RESPONSE_SURFACE: &str = "starlette.responses.RedirectResponse";
const REDIRECT_RESPONSE_OPERATION: &str = "asgi-call";
const RESPONSE_SURFACE: &str = "starlette.responses.Response";
const JSON_RESPONSE_SURFACE: &str = "starlette.responses.JSONResponse";
const STREAMING_RESPONSE_SURFACE: &str = "starlette.responses.StreamingResponse";
const FILE_RESPONSE_SURFACE: &str = "starlette.responses.FileResponse";
const STATIC_FILES_SURFACE: &str = "starlette.staticfiles.StaticFiles";
const STATIC_FILES_LOOKUP_PATH_OPERATION: &str = "lookup-path";
const RESPONSE_OPERATION: &str = "asgi-call";
const QUERY_PARAMS_SURFACE: &str = "starlette.datastructures.QueryParams";
const QUERY_PARAMS_OPERATION: &str = "construction-and-mapping-sequence";
const WEBSOCKET_SURFACE: &str = "starlette.websockets.WebSocket";
const WEBSOCKET_OPERATION: &str = "protocol-sequence";
const WEBSOCKET_STATE_OPERATION: &str = "state-sequence";

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

struct StaticFilesPermissionDenialGuard {
    path: PathBuf,
    original_permissions: fs::Permissions,
}

impl Drop for StaticFilesPermissionDenialGuard {
    fn drop(&mut self) {
        let _ = fs::set_permissions(&self.path, self.original_permissions.clone());
    }
}

enum StaticFilesPathLimitStressSetup {
    Ready(PathBuf),
    Skipped(String),
}

enum StaticFilesPermissionDenialStressSetup {
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
    serde_json::from_str(line).map_err(|error| format!("invalid adapter request JSON: {error}"))
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
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let workspace_root = manifest_dir
        .parent()
        .ok_or_else(|| String::from("crate manifest has no workspace parent"))?;
    let source_fingerprint = source_fingerprint(workspace_root, &manifest_dir)?;
    let head = git_output(workspace_root, &["rev-parse", "--verify", "HEAD"]);
    let status = git_output(
        workspace_root,
        &[
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "starlette-rs",
            "Cargo.toml",
            "Cargo.lock",
        ],
    );
    let dirty = head.is_none() || status.as_deref().is_none_or(|value| !value.is_empty());
    let base_revision = head.unwrap_or_else(|| String::from("uncommitted"));
    let revision = format!("{base_revision}+source-fnv1a64-{source_fingerprint:016x}");
    let runtime = rust_runtime();
    let lock_path = workspace_root.join("Cargo.lock");
    let lock_bytes = fs::read(&lock_path).map_err(|error| {
        format!(
            "cannot read workspace dependency lock {}: {error}",
            lock_path.display()
        )
    })?;
    let dependency_lock_sha256 = format!("{:x}", Sha256::digest(&lock_bytes));
    if let Ok(expected) = env::var("STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256") {
        if expected != dependency_lock_sha256 {
            return Err(String::from(
                "workspace Cargo.lock SHA256 does not match STARLETTE_PARITY_DEPENDENCY_LOCK_SHA256",
            ));
        }
    }

    Ok(json!({
        "subject_id": SUBJECT_ID,
        "revision": revision,
        "dirty": dirty,
        "runtime": runtime,
        "os": env::consts::OS,
        "architecture": env::consts::ARCH,
        "backend": "native",
        "features": [],
        "package_version": env!("CARGO_PKG_VERSION"),
        "dependency_lock_sha256": dependency_lock_sha256,
    }))
}

fn rust_runtime() -> String {
    let rustc = Command::new("rustc").arg("--version").output();
    let version = match rustc {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        _ => String::from("rustc version unavailable"),
    };
    format!("{version} ({} {})", env::consts::OS, env::consts::ARCH)
}

fn git_output(root: &Path, arguments: &[&str]) -> Option<String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(arguments)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn source_fingerprint(workspace_root: &Path, crate_root: &Path) -> Result<u64, String> {
    let mut files = vec![
        workspace_root.join("Cargo.toml"),
        workspace_root.join("Cargo.lock"),
        crate_root.join("Cargo.toml"),
    ];
    collect_files(&crate_root.join("src"), &mut files)?;
    files.sort();

    let mut hash = 0xcbf2_9ce4_8422_2325_u64;
    for path in files {
        let relative = path
            .strip_prefix(workspace_root)
            .map_err(|error| error.to_string())?;
        hash_bytes(&mut hash, relative.to_string_lossy().as_bytes());
        hash_byte(&mut hash, 0);
        let contents = fs::read(&path)
            .map_err(|error| format!("cannot read identity source {}: {error}", path.display()))?;
        hash_bytes(&mut hash, &contents);
        hash_byte(&mut hash, 0xff);
    }
    Ok(hash)
}

fn collect_files(directory: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    let entries = fs::read_dir(directory).map_err(|error| {
        format!(
            "cannot list identity source {}: {error}",
            directory.display()
        )
    })?;
    for entry in entries {
        let entry = entry.map_err(|error| error.to_string())?;
        let path = entry.path();
        let file_type = entry.file_type().map_err(|error| error.to_string())?;
        if file_type.is_dir() {
            collect_files(&path, files)?;
        } else if file_type.is_file() {
            files.push(path);
        }
    }
    Ok(())
}

fn hash_bytes(hash: &mut u64, bytes: &[u8]) {
    for byte in bytes {
        hash_byte(hash, *byte);
    }
}

fn hash_byte(hash: &mut u64, byte: u8) {
    *hash ^= u64::from(byte);
    *hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
}

fn run_case(case: &Value) -> Result<Value, String> {
    if case.get("surface").and_then(Value::as_str) == Some(WEBSOCKET_SURFACE) {
        return match case.get("operation").and_then(Value::as_str) {
            Some(WEBSOCKET_STATE_OPERATION) => run_websocket_state_case(case),
            Some(WEBSOCKET_OPERATION) => Err(String::from(
                "Rust-native does not implement the full WebSocket protocol-sequence output contract",
            )),
            _ => Err(String::from("WebSocket operation is unsupported")),
        };
    }
    match (
        case.get("surface").and_then(Value::as_str),
        case.get("operation").and_then(Value::as_str),
    ) {
        (Some("starlette.middleware.gzip.GZipMiddleware"), Some("__call__")) => {
            return run_gzip_case(case);
        }
        (Some("starlette.applications.Starlette"), Some("request-dispatch")) => {
            return run_request_case(case);
        }
        (Some("starlette.routing.Router"), Some("route-dispatch")) => {
            return run_router_case(case);
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
        (Some("starlette.applications.Starlette"), Some("__call__")) => {}
        _ => return Err(String::from("workflow surface or operation is unsupported")),
    }

    run_application_case(case)
}

fn run_query_params_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
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
        lookups.push(json!({
            "key": key,
            "contains": scalar.is_some(),
            "get": scalar,
            "get_with_default": scalar.unwrap_or("__starlette_rs_default__"),
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
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "custom_convertors",
            "routes",
            "redirect_slashes",
            "scope",
            "incoming",
            "send",
            "observations",
        ],
        "Router route-dispatch case",
    )?;
    let case_id = string_field(case, "case_id", "Router route-dispatch case")?;
    if string_field(case, "surface", "Router route-dispatch case")? != "starlette.routing.Router"
        || string_field(case, "operation", "Router route-dispatch case")? != "route-dispatch"
        || case.get("observations") != Some(&json!(["route-dispatch"]))
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
    let mut route_table = RouteTable::new();
    for route in routes {
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
    }
    if case.get("incoming") != Some(&json!([]))
        || case.get("send") != Some(&json!({"kind": "capture-asgi-send"}))
    {
        return Err(String::from(
            "Router dispatch requires an empty receive sequence and captured ASGI send",
        ));
    }
    let scope = exact_object(
        case.get("scope")
            .ok_or_else(|| String::from("Router scope is missing"))?,
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
    let route_index = match &route_match {
        DetailedRouteMatch::Matched { route_index, .. }
        | DetailedRouteMatch::MethodNotAllowed { route_index, .. } => Some(*route_index),
        DetailedRouteMatch::NotFound => None,
    };
    let redirect_path = if redirect_slashes && matches!(&route_match, DetailedRouteMatch::NotFound)
    {
        route_table.find_slash_redirect_path(path, root_path, method)
    } else {
        None
    };
    let response = match (&route_match, redirect_path) {
        (DetailedRouteMatch::Matched { route_index, .. }, _) => {
            let route = exact_object(
                &routes[*route_index],
                &["kind", "path", "methods", "endpoint"],
                "selected Router route",
            )?;
            let endpoint = route
                .get("endpoint")
                .and_then(Value::as_object)
                .ok_or_else(|| String::from("selected route endpoint must be an object"))?;
            let content = string_field(endpoint, "content", "selected Router endpoint")?;
            let status = endpoint
                .get("status_code")
                .and_then(Value::as_u64)
                .filter(|status| *status <= u16::MAX as u64)
                .ok_or_else(|| String::from("selected endpoint status_code must fit u16"))?;
            Response::plain_text_with_status(status as u16, content)
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
    Ok(json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": "route-dispatch",
            "status": "ok",
            "value": {
                "route_index": route_index,
                "response_status": response.status_code(),
                "ordered_repeated_headers": headers,
                "response_bytes": {"encoding": "base64", "data": body_base64},
                "asgi_event_order": event_order,
                "asgi_events": events,
            },
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
        .filter(|status| *status <= u16::MAX as u64)
        .ok_or_else(|| String::from("Mount child status_code must fit u16"))?;
    let cookies = endpoint
        .get("cookies")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Mount child cookies must be an array"))?;
    let mut response = Response::from_content(
        status as u16,
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
    let case = exact_object(
        case,
        &[
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
        ],
        "RedirectResponse asgi-call case",
    )?;
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

    let response =
        Response::redirect(url, status_code, &header_pairs).map_err(|error| error.to_string())?;
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
        .ok_or_else(|| String::from("FileResponse HTTP scope must be a JSON object"))?;
    let pathsend_extension = match scope_without_extensions.remove("extensions") {
        None => false,
        Some(Value::Object(extensions)) => extensions.contains_key("http.response.pathsend"),
        Some(_) => {
            return Err(String::from(
                "FileResponse HTTP scope.extensions must be an object when present",
            ));
        }
    };
    let scope_without_extensions = Value::Object(scope_without_extensions);
    let validated = validate_asgi_http_scope(&scope_without_extensions, "FileResponse")?.clone();
    Ok((validated, pathsend_extension))
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
            "step_id": RESPONSE_OPERATION,
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

fn apply_response_cookie_actions(response: &mut Response, value: &Value) -> Result<(), String> {
    let actions = value
        .as_array()
        .ok_or_else(|| String::from("Response cookie_actions must be an array"))?;
    for (index, raw_action) in actions.iter().enumerate() {
        let context = format!("Response cookie_actions[{index}]");
        let action = exact_object(
            raw_action,
            &[
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
            ],
            &context,
        )?;
        if string_field(action, "method", &context)? != "set" {
            return Err(format!("{context}.method must be set"));
        }
        let key = string_field(action, "key", &context)?;
        let cookie_value = string_field(action, "value", &context)?;
        let max_age = match action.get("max_age") {
            Some(Value::Null) => None,
            Some(Value::Number(value)) => Some(
                value
                    .as_i64()
                    .ok_or_else(|| format!("{context}.max_age must fit a signed 64-bit integer"))?
                    .to_string(),
            ),
            _ => return Err(format!("{context}.max_age must be an integer or null")),
        };
        let options = CookieOptions {
            max_age,
            expires: optional_string_field(action, "expires", &context)?,
            path: optional_string_field(action, "path", &context)?,
            domain: optional_string_field(action, "domain", &context)?,
            secure: bool_field(action, "secure", &context)?,
            httponly: bool_field(action, "httponly", &context)?,
            samesite: optional_string_field(action, "samesite", &context)?,
            partitioned: bool_field(action, "partitioned", &context)?,
        };
        response
            .set_cookie_with_options(key, cookie_value, &options)
            .map_err(|error| format!("{context}: {error}"))?;
    }
    Ok(())
}

fn run_streaming_response_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
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
        ],
        "StreamingResponse asgi-call case",
    )?;
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

    let response = StreamingResponse::from_chunks(
        status_code,
        chunks,
        media_type,
        header_pairs
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    )
    .map_err(|error| error.to_string())?;
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
    let case = exact_object(
        case,
        &[
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
            "scope",
            "incoming",
            "send",
            "observations",
        ],
        "FileResponse asgi-call case",
    )?;
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
    validate_string_array(case, "covers", "FileResponse asgi-call covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "FileResponse asgi-call target_profiles",
        false,
    )?;
    if case.get("incoming") != Some(&json!([])) {
        return Err(String::from(
            "FileResponse asgi-call requires an empty incoming sequence",
        ));
    }
    validate_capture_send(
        case.get("send")
            .ok_or_else(|| String::from("FileResponse asgi-call send input is missing"))?,
    )?;

    let source_file = exact_object(
        case.get("file")
            .ok_or_else(|| String::from("FileResponse asgi-call file is missing"))?,
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
    let mtime_text = python_float_text_for_input(mtime_number);

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

    let (scope, pathsend_extension) = validated_file_response_scope(
        case.get("scope")
            .ok_or_else(|| String::from("FileResponse asgi-call scope is missing"))?,
    )?;
    let request_headers = parse_scope_request_headers(&scope, "FileResponse HTTP scope")?;
    let method = string_field(&scope, "method", "FileResponse HTTP scope")?;

    let (temporary_directory, path) = create_file_response_input(file_name, &contents)?;
    let metadata = FileMetadata::from_unix_seconds(
        u64::try_from(contents.len()).map_err(|error| error.to_string())?,
        mtime_number,
        mtime_text,
    )
    .map_err(|error| error.to_string())?;
    let response = NativeFileResponse::new(
        path.clone(),
        path.to_string_lossy().into_owned(),
        status_code,
        &header_pairs,
        FileResponseOptions {
            media_type,
            filename,
            stat_override: Some(metadata),
            ..FileResponseOptions::default()
        },
    )
    .map_err(|error| error.to_string())?;
    let mut call = response
        .call_state("http", method, &request_headers, pathsend_extension, false)
        .map_err(|error| error.to_string())?;

    let mut response_status = None;
    let mut ordered_headers = Vec::new();
    let mut response_bytes = Vec::new();
    let mut events = Vec::new();
    loop {
        match call.step().map_err(|error| error.to_string())? {
            FileResponseCallStep::Send(event) => {
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
                events.push(canonical_file_response_event(event));
                call.advance(FileResponseCallInput::<String>::Send(Ok(())))
                    .map_err(|error| format!("FileResponse send transition failed: {error:?}"))?;
            }
            FileResponseCallStep::RunBackground => {
                return Err(String::from(
                    "FileResponse adapter has no background callback to execute",
                ));
            }
            FileResponseCallStep::Complete => break,
            FileResponseCallStep::Failed => {
                return Err(String::from("FileResponse call reached a failed state"));
            }
        }
    }
    drop(temporary_directory);

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
                "response_status": response_status,
                "ordered_repeated_headers": ordered_headers,
                "response_bytes": {
                    "encoding": "base64",
                    "data": encode_base64(&response_bytes),
                },
                "asgi_event_order": event_order,
                "asgi_events": events,
            },
        }],
    }))
}

fn run_static_files_lookup_path_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
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
        ],
        "StaticFiles lookup-path case",
    )?;
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
    let directory_name = string_field(case, "directory", "StaticFiles lookup-path case")?;
    let check_dir = case
        .get("check_dir")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles lookup-path check_dir must be boolean"))?;
    let follow_symlink = case
        .get("follow_symlink")
        .and_then(Value::as_bool)
        .ok_or_else(|| String::from("StaticFiles lookup-path follow_symlink must be boolean"))?;
    let file_inputs = case
        .get("files")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("StaticFiles lookup-path files must be an array"))?;
    if file_inputs.is_empty() {
        return Err(String::from(
            "StaticFiles lookup-path requires at least one input file",
        ));
    }
    let lookup_path = string_field(case, "lookup_path", "StaticFiles lookup-path case")?;
    let filesystem = case
        .get("filesystem")
        .ok_or_else(|| String::from("StaticFiles lookup-path filesystem is missing"))?;
    let (temporary_directory, root) =
        create_static_files_lookup_path_input(directory_name, file_inputs, filesystem)?;
    let static_files = NativeStaticFiles::new(
        Some(root.clone()),
        vec![root.clone()],
        false,
        check_dir,
        follow_symlink,
    )
    .map_err(|error| format!("StaticFiles lookup-path construction failed: {error:?}"))?;
    let lookup = static_files
        .lookup_path(lookup_path)
        .map_err(|error| format!("StaticFiles lookup_path failed: {error:?}"))?;
    let observation = match lookup {
        Some(file) => {
            let resolved_root = if follow_symlink {
                root
            } else {
                root.canonicalize()
                    .map_err(|error| format!("cannot canonicalize StaticFiles root: {error}"))?
            };
            let relative_path = file
                .path
                .strip_prefix(&resolved_root)
                .map_err(|error| format!("StaticFiles result escaped the root: {error}"))?
                .components()
                .map(|component| component.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
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
                "resolved_path": relative_path,
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
        None => json!({
            "resolved_path": null,
            "stat_result_present": false,
            "mode_type_bits": null,
            "is_file": null,
            "is_directory": null,
            "size": null,
            "mtime_seconds": null,
        }),
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

fn run_static_files_case(case: &Value) -> Result<Value, String> {
    let case = exact_object(
        case,
        &[
            "case_id",
            "surface",
            "operation",
            "covers",
            "target_profiles",
            "assets",
            "directory",
            "path_limit_stress",
            "permission_denial_stress",
            "packages",
            "files",
            "html",
            "check_dir",
            "follow_symlink",
            "scope",
            "incoming",
            "send",
            "observations",
        ],
        "StaticFiles asgi-call case",
    )?;
    let case_id = string_field(case, "case_id", "StaticFiles asgi-call case")?;
    if string_field(case, "surface", "StaticFiles asgi-call case")? != STATIC_FILES_SURFACE
        || string_field(case, "operation", "StaticFiles asgi-call case")? != RESPONSE_OPERATION
        || case.get("observations") != Some(&json!([RESPONSE_OPERATION]))
        || case.get("assets") != Some(&json!([]))
        || case.get("incoming") != Some(&json!([]))
    {
        return Err(String::from(
            "case is outside the StaticFiles ASGI-call contract",
        ));
    }
    validate_string_array(case, "covers", "StaticFiles covers", false)?;
    validate_string_array(
        case,
        "target_profiles",
        "StaticFiles target_profiles",
        false,
    )?;
    validate_capture_send(
        case.get("send")
            .ok_or_else(|| String::from("StaticFiles ASGI-call send input is missing"))?,
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
    let null_path = case
        .get("scope")
        .and_then(|scope| scope.get("path"))
        .and_then(Value::as_str)
        .is_some_and(|path| path.contains('\0'));
    if file_inputs.is_empty() && package_inputs.is_empty() && !null_path {
        return Err(String::from(
            "StaticFiles must configure at least one asset unless the input path contains a NUL byte",
        ));
    }
    let (temporary_directory, root, package_roots) =
        create_static_files_input(directory_name, file_inputs, package_inputs)?;

    let (scope, pathsend_extension) = validated_file_response_scope(
        case.get("scope")
            .ok_or_else(|| String::from("StaticFiles ASGI-call scope is missing"))?,
    )?;
    let scope_path = string_field(&scope, "path", "StaticFiles HTTP scope")?;
    let root_path = string_field(&scope, "root_path", "StaticFiles HTTP scope")?;
    let method = string_field(&scope, "method", "StaticFiles HTTP scope")?;
    let request_headers = parse_scope_request_headers(&scope, "StaticFiles HTTP scope")?;
    let path = NativeStaticFiles::get_path(scope_path, root_path);
    let root = match path_limit_stress {
        Some(stress) => {
            match prepare_static_files_path_limit_stress(
                &root,
                &package_roots,
                &path,
                follow_symlink,
                stress,
            )? {
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
    let permission_guard = if let Some(stress) = permission_denial_stress {
        match prepare_static_files_permission_denial_stress(&root, &path, stress)? {
            StaticFilesPermissionDenialStressSetup::Ready(guard) => Some(guard),
            StaticFilesPermissionDenialStressSetup::Skipped(reason) => {
                return Ok(static_files_skipped_result(case_id, &reason));
            }
        }
    } else {
        None
    };
    let selected_result = static_files.get_response(&path, scope_path, method, &request_headers);
    drop(permission_guard);
    let selected = match selected_result {
        Ok(selected) => selected,
        Err(StaticFilesError::MethodNotAllowed) => {
            return Ok(static_files_error_result(
                case_id,
                405,
                "Method Not Allowed",
            ));
        }
        Err(StaticFilesError::NotFound) => {
            return Ok(static_files_error_result(case_id, 404, "Not Found"));
        }
        Err(StaticFilesError::PermissionDenied) => {
            return Ok(static_files_error_result(case_id, 401, "Unauthorized"));
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
                        events.push(canonical_file_response_event(event));
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
            let server = server.and_then(|server| {
                Some((server.first()?.as_str()?, server.get(1)?.as_u64()? as u16))
            });
            let url = connection_url(
                scope.get("scheme").and_then(Value::as_str),
                &path,
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
    drop(temporary_directory);
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
                "response_status": response_status,
                "ordered_repeated_headers": ordered_headers,
                "response_bytes": {"encoding": "base64", "data": encode_base64(&response_bytes)},
                "asgi_event_order": event_order,
                "asgi_events": events,
            },
        }],
    }))
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
#[allow(unsafe_code)]
fn pathconf_limit(path: &Path, name: libc::c_int) -> Option<usize> {
    let path = CString::new(path.as_os_str().as_bytes()).ok()?;
    // SAFETY: `path` is a live NUL-terminated CString for the immediate call;
    // pathconf reads the borrowed path synchronously and retains no pointer.
    let value = unsafe { libc::pathconf(path.as_ptr(), name) };
    usize::try_from(value).ok().filter(|limit| *limit > 0)
}

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
        if remaining > component_cost && remaining - component_cost == 1 {
            if component_cost <= 2 {
                return None;
            }
            component_cost -= 1;
        }
        let component_bytes = component_cost - 1;
        padding.push("p".repeat(component_bytes));
        remaining -= component_cost;
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

fn static_files_error_result(case_id: &str, status_code: u16, detail: &str) -> Value {
    let message = format!("{status_code}: {detail}");
    json!({
        "case_id": case_id,
        "status": "completed",
        "observations": [{
            "step_id": RESPONSE_OPERATION,
            "status": "error",
            "error": {
                "class": "starlette.exceptions.HTTPException",
                "kind": "exception",
                "message": message,
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
                    write_static_asset(&root, file_input, "StaticFiles lookup-path file")?;
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
    let relative = Path::new(relative_path);
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

fn python_float_text_for_input(value: f64) -> String {
    let mut text = value.to_string();
    if !text.contains('.') && !text.contains('e') && !text.contains('E') {
        text.push_str(".0");
    }
    text
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
    if case.get("target_profiles")
        != Some(&json!(["rust-native-local", "python-package-cpython312"]))
        || case.get("assets") != Some(&json!([]))
    {
        return Err(String::from(
            "WebSocket state cases must select both profiles and no assets",
        ));
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
            "receive" => {
                exact_keys(action_object, &["action_id", "action"], &context)?;
                let message = if matches!(
                    machine.client_state(),
                    WebSocketState::Connecting | WebSocketState::Connected
                ) {
                    let message = incoming.get(incoming_index).ok_or_else(|| {
                        String::from("WebSocket state receive action has no input message")
                    })?;
                    incoming_index += 1;
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
                validate_websocket_message(message, &format!("{context}.message"), false)?;
                let message_type = string_field(
                    message
                        .as_object()
                        .ok_or_else(|| format!("{context}.message must be an object"))?,
                    "type",
                    &format!("{context}.message"),
                )?;
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
                            "error_message": error_message,
                        }),
                        None => json!({
                            "action_id": action_id,
                            "outcome": "ok",
                        }),
                    },
                }
            }
            _ => {
                return Err(format!(
                    "{context}.action is unsupported by the WebSocketStateMachine surface; only receive and send are declared"
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

fn websocket_state_name(state: WebSocketState) -> &'static str {
    match state {
        WebSocketState::Connecting => "CONNECTING",
        WebSocketState::Connected => "CONNECTED",
        WebSocketState::Disconnected => "DISCONNECTED",
        WebSocketState::Response => "RESPONSE",
    }
}

fn validate_websocket_scope(scope: &Value) -> Result<(), String> {
    let scope = exact_object(
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
    validate_string_array(scope, "subprotocols", "WebSocket scope.subprotocols", true)
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
            _ => {
                return Err(format!(
                    "{context}.type is unsupported for incoming messages"
                ));
            }
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
        _ => {
            return Err(format!(
                "{context}.type is unsupported for outgoing messages"
            ));
        }
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
    let required_arguments = [
        "app",
        "minimum_size",
        "compresslevel",
        "thread_minimum_size",
    ];
    if arguments.contains_key("exclude_content_types") {
        exact_keys(
            arguments,
            &[
                "app",
                "minimum_size",
                "compresslevel",
                "thread_minimum_size",
                "exclude_content_types",
            ],
            "GZipMiddleware constructor arguments",
        )?;
    } else {
        exact_keys(
            arguments,
            &required_arguments,
            "GZipMiddleware constructor arguments",
        )?;
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

    let minimum_size = integer_argument(
        arguments,
        "minimum_size",
        "GZipMiddleware constructor arguments",
    )?;
    let thread_minimum_size = integer_argument(
        arguments,
        "thread_minimum_size",
        "GZipMiddleware constructor arguments",
    )?;
    if minimum_size < 0 || thread_minimum_size < 0 {
        return Err(String::from(
            "GZipMiddleware size settings must be non-negative integers",
        ));
    }
    let compresslevel = integer_argument(
        arguments,
        "compresslevel",
        "GZipMiddleware constructor arguments",
    )?;
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
            *more_body != (index + 1 != output.len())
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
    if case.get("target_profiles")
        != Some(&json!(["rust-native-local", "python-package-cpython312"]))
        || case.get("assets") != Some(&json!([]))
        || case.get("observations") != Some(&json!(["dispatch"]))
        || case.get("execution_schedule") != Some(&json!(["dispatch"]))
    {
        return Err(String::from(
            "request-dispatch case must select both targets, no assets, and dispatch only",
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
) -> Result<(RouteTable, Response, Option<RequestObserver>), String> {
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
            (response, Some(observer))
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
                Some(Value::String(detail)) => detail.as_str(),
                Some(Value::Null) => {
                    return Err(String::from(
                        "native HTTP exception detail must be a string; null is package-only",
                    ));
                }
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
    observer: &RequestObserver,
) -> Result<Value, String> {
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
            let detail = endpoint
                .get("detail")
                .and_then(Value::as_str)
                .ok_or_else(|| String::from("native HTTP exception detail must be a string"))?;
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
    let lifespan_spec = exact_object(
        lifespan_spec,
        &["kind", "record_entry", "record_exit"],
        "lifespan input",
    )?;
    if string_field(lifespan_spec, "kind", "lifespan input")? != "async-context-manager" {
        return Err(String::from("lifespan kind must be async-context-manager"));
    }
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

fn canonical_file_response_event(event: FileResponseEvent) -> Value {
    match event {
        FileResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "type": "http.response.start",
            "status": status_code,
            "headers": canonical_headers(&headers),
        }),
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
        let suffix = &bracketed[end + 1..];
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
    if input.len() % 4 != 0 {
        return Err(format!("{context} is invalid base64"));
    }
    let mut decoded = Vec::with_capacity(input.len() / 4 * 3);
    let chunks = input.chunks_exact(4);
    let chunk_count = chunks.len();
    for (index, chunk) in chunks.enumerate() {
        let final_chunk = index + 1 == chunk_count;
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
        b'A'..=b'Z' => Some(value - b'A'),
        b'a'..=b'z' => Some(value - b'a' + 26),
        b'0'..=b'9' => Some(value - b'0' + 52),
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
        let second = bytes.get(offset + 1).copied();
        let third = bytes.get(offset + 2).copied();
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
        offset += 3;
    }
    encoded
}

fn push_base64_character(encoded: &mut String, table: &[u8; 64], index: usize) {
    if let Some(character) = table.get(index) {
        encoded.push(char::from(*character));
    }
}
