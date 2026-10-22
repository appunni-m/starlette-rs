//! Input-driven probes for direct Rust-native APIs whose operations are added
//! to the fixture index separately from the Starlette compatibility surface.

use base64::Engine;
use serde_json::{Map, Value, json};
use starlette_rs::{
    FormData, HostPattern, LifespanAction, LifespanPhase, LifespanState, NamedRouteTable, Response,
    ResponseCallError, ResponseCallInput, ResponseCallStep, RouteTable, SupplementalRouteMatch,
    connection_url_with_port_text,
};

type EncodedPairs = Vec<(Vec<u8>, Vec<u8>)>;

pub(super) fn dispatch(case: &Value) -> Option<Result<Value, String>> {
    let surface = case.get("surface").and_then(Value::as_str)?;
    let operation = case.get("operation").and_then(Value::as_str)?;
    let result = match (surface, operation) {
        ("starlette-rs.FormData", "parse-urlencoded") => run_form_data(case),
        ("starlette-rs.Connection", "build-url") => run_connection(case),
        ("starlette-rs.HostPattern", "match-format") => run_host_pattern(case),
        ("starlette-rs.NamedRouteTable", "url-path-for") => run_named_route_table(case),
        ("starlette-rs.LifespanState", "transition-sequence") => run_lifespan_state(case),
        ("starlette-rs.RouteTable", "dispatch-plan") => run_route_dispatch_plan(case),
        ("starlette-rs.Response", "call-state-sequence") => run_response_call_state(case),
        _ => return None,
    };
    Some(result)
}

fn run_form_data(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.FormData", "parse-urlencoded")?;
    let input = exact_object(
        input,
        &["body_base64", "max_fields", "max_part_size", "lookup_keys"],
        "FormData parse input",
    )?;
    let body = decode_base64(
        string_field(input, "body_base64", "FormData parse input")?,
        "FormData parse input.body_base64",
    )?;
    let max_fields = input
        .get("max_fields")
        .and_then(Value::as_f64)
        .ok_or_else(|| String::from("FormData parse input.max_fields must be numeric"))?;
    let max_part_size = input
        .get("max_part_size")
        .and_then(Value::as_i64)
        .ok_or_else(|| String::from("FormData parse input.max_part_size must be an integer"))?;
    let lookup_keys = string_array(input, "lookup_keys", "FormData parse input")?;
    let result = FormData::parse_urlencoded(&body, max_fields, max_part_size);
    let mut values = Map::new();
    match result {
        Ok(form) => {
            values.insert(String::from("result.status"), json!("ok"));
            values.insert(String::from("multi_items"), json!(form.multi_items()));
            values.insert(String::from("keys"), json!(form.keys()));
            values.insert(String::from("values"), json!(form.values()));
            values.insert(String::from("items"), json!(form.items()));
            values.insert(String::from("length"), json!(form.len()));
            values.insert(String::from("is_empty"), json!(form.is_empty()));
            values.insert(
                String::from("lookups"),
                json!(lookup_keys
                    .iter()
                    .map(|key| json!({"key": key, "value": form.get(key), "values": form.get_list(key)}))
                    .collect::<Vec<_>>()),
            );
        }
        Err(error) => {
            values.insert(String::from("result.status"), json!("error"));
            let _ = error;
        }
    }
    direct_result(case_id, values)
}

fn run_connection(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.Connection", "build-url")?;
    let input = exact_object(
        input,
        &[
            "scheme",
            "path",
            "query_base64",
            "headers_base64_pairs",
            "server",
        ],
        "connection URL input",
    )?;
    let scheme = optional_string(input, "scheme", "connection URL input")?;
    let path = string_field(input, "path", "connection URL input")?;
    let query = decode_base64(
        string_field(input, "query_base64", "connection URL input")?,
        "connection URL input.query_base64",
    )?;
    let headers = base64_pairs(input, "headers_base64_pairs", "connection URL input")?;
    let server_storage;
    let server = match input.get("server") {
        Some(Value::Null) => None,
        Some(Value::Object(_)) => {
            let server = exact_object(
                input
                    .get("server")
                    .ok_or_else(|| String::from("connection URL server is absent"))?,
                &["host", "port_text"],
                "connection URL server",
            )?;
            server_storage = (
                string_field(server, "host", "connection URL server")?.to_owned(),
                string_field(server, "port_text", "connection URL server")?.to_owned(),
            );
            Some((server_storage.0.as_str(), server_storage.1.as_str()))
        }
        _ => {
            return Err(String::from(
                "connection URL input.server must be an object or null",
            ));
        }
    };
    let mut values = Map::new();
    match connection_url_with_port_text(scheme, path, &query, &headers, server) {
        Ok(url) => {
            values.insert(String::from("result.status"), json!("ok"));
            values.insert(String::from("result.url"), json!(url));
        }
        Err(error) => {
            values.insert(String::from("result.status"), json!("error"));
            let _ = error;
        }
    }
    direct_result(case_id, values)
}

fn run_host_pattern(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.HostPattern", "match-format")?;
    let input = exact_object(
        input,
        &["pattern", "host_header", "path", "format_params"],
        "HostPattern input",
    )?;
    let pattern = string_field(input, "pattern", "HostPattern input")?;
    let host_header = string_field(input, "host_header", "HostPattern input")?;
    let path = string_field(input, "path", "HostPattern input")?;
    let format_params = string_pairs(input, "format_params", "HostPattern input")?;
    let mut values = Map::new();
    match HostPattern::new(pattern) {
        Err(error) => {
            values.insert(String::from("registration.status"), json!("error"));
            let _ = error;
        }
        Ok(host) => {
            values.insert(String::from("registration.status"), json!("ok"));
            values.insert(
                String::from("match"),
                host.match_host(host_header)
                    .map_or(Value::Null, |captures| json!(captures)),
            );
            match host.format_url_path(path, &format_params) {
                Ok(url_path) => {
                    values.insert(String::from("format.status"), json!("ok"));
                    values.insert(String::from("format.path"), json!(url_path.path()));
                    values.insert(String::from("format.protocol"), json!(url_path.protocol()));
                    values.insert(String::from("format.host"), json!(url_path.host()));
                }
                Err(error) => {
                    values.insert(String::from("format.status"), json!("error"));
                    let _ = error;
                }
            }
        }
    }
    direct_result(case_id, values)
}

fn run_named_route_table(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.NamedRouteTable", "url-path-for")?;
    let input = exact_object(input, &["routes", "lookup"], "NamedRouteTable input")?;
    let routes = input
        .get("routes")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("NamedRouteTable input.routes must be an array"))?;
    let mut table = NamedRouteTable::new();
    for (index, route) in routes.iter().enumerate() {
        let route = exact_object(route, &["path", "name"], "NamedRouteTable route")?;
        let path = string_field(route, "path", "NamedRouteTable route")?;
        let name = string_field(route, "name", "NamedRouteTable route")?;
        table.add_route(path, name).map_err(|error| {
            format!("NamedRouteTable route[{index}] registration failed: {error}")
        })?;
    }
    let lookup = exact_object(
        input
            .get("lookup")
            .ok_or_else(|| String::from("NamedRouteTable input.lookup is required"))?,
        &["name", "params"],
        "NamedRouteTable lookup",
    )?;
    let name = string_field(lookup, "name", "NamedRouteTable lookup")?;
    let params = string_pairs(lookup, "params", "NamedRouteTable lookup")?;
    let mut values = Map::new();
    match table.url_path_for(name, &params) {
        Ok(url_path) => {
            values.insert(String::from("lookup.status"), json!("ok"));
            values.insert(String::from("lookup.path"), json!(url_path.path()));
            values.insert(String::from("lookup.protocol"), json!(url_path.protocol()));
            values.insert(String::from("lookup.host"), json!(url_path.host()));
        }
        Err(error) => {
            values.insert(String::from("lookup.status"), json!("error"));
            let _ = error;
        }
    }
    direct_result(case_id, values)
}

fn run_lifespan_state(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.LifespanState", "transition-sequence")?;
    let input = exact_object(input, &["actions"], "LifespanState input")?;
    let actions = input
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("LifespanState input.actions must be an array"))?;
    let mut state = LifespanState::new();
    let mut trace = Vec::with_capacity(actions.len());
    for (index, raw_action) in actions.iter().enumerate() {
        let context = format!("LifespanState input.actions[{index}]");
        let action = raw_action
            .as_object()
            .ok_or_else(|| format!("{context} must be an object"))?;
        let kind = action
            .get("kind")
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{context}.kind must be a string"))?;
        let result = match kind {
            "startup-received" => state
                .startup_received(string_field(action, "message_type", &context)?)
                .map(|value| format!("{value:?}")),
            "context-entered" => state.context_entered().map(|value| format!("{value:?}")),
            "startup-failed" => state.startup_failed().map(str::to_owned),
            "shutdown-received" => state
                .shutdown_received(string_field(action, "message_type", &context)?)
                .map(|value| format!("{value:?}")),
            "context-exited" => state.context_exited().map(|value| format!("{value:?}")),
            "context-exit-suppressed" => state
                .context_exit_suppressed()
                .map(|value| format!("{value:?}")),
            "shutdown-failed" => state.shutdown_failed().map(str::to_owned),
            _ => return Err(format!("{context}.kind is unsupported")),
        };
        let (status, outcome) = match result {
            Ok(action) => ("ok", json!({"action": action})),
            Err(error) => (
                "error",
                json!({"display": error.to_string(), "debug": format!("{error:?}")}),
            ),
        };
        trace.push(json!({
            "index": index,
            "kind": kind,
            "status": status,
            "phase": format!("{:?}", state.phase()),
            "outcome": outcome,
        }));
    }
    let values = Map::from_iter([
        (
            String::from("initial_phase"),
            json!(format!("{:?}", LifespanPhase::AwaitingStartup)),
        ),
        (String::from("trace"), json!(trace)),
        (
            String::from("final_phase"),
            json!(format!("{:?}", state.phase())),
        ),
        (String::from("actions"), json!(action_names())),
    ]);
    direct_result(case_id, values)
}

fn action_names() -> Vec<&'static str> {
    [
        LifespanAction::EnterContext,
        LifespanAction::SendStartupComplete,
        LifespanAction::ExitContext,
        LifespanAction::SendShutdownComplete,
    ]
    .iter()
    .map(|action| match action {
        LifespanAction::EnterContext => "EnterContext",
        LifespanAction::SendStartupComplete => "SendStartupComplete",
        LifespanAction::ExitContext => "ExitContext",
        LifespanAction::SendShutdownComplete => "SendShutdownComplete",
    })
    .collect()
}

fn run_route_dispatch_plan(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.RouteTable", "dispatch-plan")?;
    let input = input
        .as_object()
        .ok_or_else(|| String::from("RouteTable dispatch input must be an object"))?;
    let required = ["routes", "path", "root_path", "method"];
    let optional = [
        "router_route_indexes",
        "supplemental_matches",
        "path_builds",
        "captures",
    ];
    if required.iter().any(|key| !input.contains_key(*key))
        || input
            .keys()
            .any(|key| !required.contains(&key.as_str()) && !optional.contains(&key.as_str()))
    {
        return Err(String::from(
            "RouteTable dispatch input has missing or unknown fields",
        ));
    }
    let route_inputs = input
        .get("routes")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("RouteTable dispatch input.routes must be an array"))?;
    let table = native_route_table(route_inputs)?;
    let path = string_field(input, "path", "RouteTable dispatch input")?;
    let root_path = string_field(input, "root_path", "RouteTable dispatch input")?;
    let method = string_field(input, "method", "RouteTable dispatch input")?;
    let plan = native_route_dispatch_plan(&table, input, path, root_path, method)?;
    let mut values = Map::new();
    values.insert(String::from("plan"), dispatch_plan_value(&plan.0));
    if !plan.1.is_null() {
        values.insert(String::from("planner_error"), plan.1);
    }
    if input.contains_key("path_builds") {
        values.insert(
            String::from("path_builds"),
            json!(run_path_builds(&table, input.get("path_builds"))?),
        );
    }
    if input.contains_key("captures") {
        values.insert(
            String::from("captures"),
            json!(run_captures(&table, input.get("captures"))?),
        );
    }
    direct_result(case_id, values)
}

fn native_route_table(route_inputs: &[Value]) -> Result<RouteTable, String> {
    let mut table = RouteTable::new();
    for (index, raw_route) in route_inputs.iter().enumerate() {
        let route = exact_object(raw_route, &["path", "methods"], "RouteTable route")?;
        let path = string_field(route, "path", "RouteTable route")?;
        let methods = string_array(route, "methods", "RouteTable route")?;
        table
            .add_route(path, &methods)
            .map_err(|error| format!("RouteTable route[{index}] registration failed: {error}"))?;
    }
    Ok(table)
}

fn native_route_dispatch_plan(
    table: &RouteTable,
    input: &Map<String, Value>,
    path: &str,
    root_path: &str,
    method: &str,
) -> Result<(starlette_rs::HttpDispatchPlan, Value), String> {
    let plan = if let Some(raw_indexes) = input.get("router_route_indexes") {
        let indexes = raw_indexes
            .as_array()
            .ok_or_else(|| String::from("router_route_indexes must be an array"))?
            .iter()
            .map(|value| {
                value
                    .as_u64()
                    .and_then(|value| usize::try_from(value).ok())
                    .ok_or_else(|| String::from("router_route_indexes entries must be usize"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        let supplemental = input
            .get("supplemental_matches")
            .and_then(Value::as_array)
            .ok_or_else(|| String::from("supplemental_matches must be an array"))?
            .iter()
            .map(|raw| {
                let candidate = exact_object(
                    raw,
                    &["path", "kind", "route_index", "allowed_methods"],
                    "supplemental match",
                )?;
                Ok((
                    string_field(candidate, "path", "supplemental match")?.to_owned(),
                    match string_field(candidate, "kind", "supplemental match")? {
                        "matched" => SupplementalRouteMatch::Matched {
                            route_index: usize_field(
                                candidate,
                                "route_index",
                                "supplemental match",
                            )?,
                        },
                        "method-not-allowed" => SupplementalRouteMatch::MethodNotAllowed {
                            route_index: usize_field(
                                candidate,
                                "route_index",
                                "supplemental match",
                            )?,
                            allowed_methods: string_array(
                                candidate,
                                "allowed_methods",
                                "supplemental match",
                            )?,
                        },
                        other => {
                            return Err(format!("unsupported supplemental match kind {other:?}"));
                        }
                    },
                ))
            })
            .collect::<Result<Vec<_>, String>>()?;
        table
            .dispatch_plan_with_candidates(
                path,
                root_path,
                method,
                &indexes,
                true,
                |candidate_path, _| {
                    supplemental
                        .iter()
                        .filter(|(path, _)| path == candidate_path)
                        .map(|(_, candidate)| candidate.clone())
                        .collect()
                },
            )
            .map_or_else(
                |error| {
                    (
                        starlette_rs::HttpDispatchPlan::NotFound,
                        json!({"display": error.to_string()}),
                    )
                },
                |plan| (plan, Value::Null),
            )
    } else {
        (table.dispatch_plan(path, root_path, method), Value::Null)
    };
    Ok(plan)
}

fn run_response_call_state(case: &Value) -> Result<Value, String> {
    let (case_id, input) = direct_case(case, "starlette-rs.Response", "call-state-sequence")?;
    let input = exact_object(
        input,
        &[
            "status_code",
            "body",
            "headers",
            "has_background",
            "actions",
        ],
        "Response call-state input",
    )?;
    let status_code = u16_field(input, "status_code", "Response call-state input")?;
    let body = string_field(input, "body", "Response call-state input")?;
    let headers = string_pairs(input, "headers", "Response call-state input")?;
    let response = Response::from_content(
        status_code,
        body.as_bytes().to_vec(),
        Some("text/plain"),
        headers
            .iter()
            .map(|(name, value)| (name.as_str(), value.as_str())),
    );
    let mut values = Map::new();
    let response = match response {
        Ok(response) => response,
        Err(error) => {
            values.insert(String::from("construction.status"), json!("error"));
            values.insert(
                String::from("construction.error.display"),
                json!(error.to_string()),
            );
            return direct_result(case_id, values);
        }
    };
    let has_background = bool_field(input, "has_background", "Response call-state input")?;
    let mut call = response.call_state(has_background);
    let actions = input
        .get("actions")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("Response call-state input.actions must be an array"))?;
    let (events, background_called, error) = run_response_actions(&mut call, actions)?;
    values.insert(String::from("events"), json!(events));
    values.insert(String::from("background_called"), json!(background_called));
    values.insert(
        String::from("result_status"),
        json!(if error.is_null() { "ok" } else { "error" }),
    );
    values.insert(String::from("error"), error);
    direct_result(case_id, values)
}

fn run_response_actions(
    call: &mut starlette_rs::ResponseCall,
    actions: &[Value],
) -> Result<(Vec<Value>, bool, Value), String> {
    let mut events = Vec::with_capacity(2);
    let mut background_called = false;
    let mut error = Value::Null;
    for (index, raw_action) in actions.iter().enumerate() {
        let action = raw_action.as_object().ok_or_else(|| {
            format!("Response call-state input.actions[{index}] must be an object")
        })?;
        let kind = action.get("kind").and_then(Value::as_str).ok_or_else(|| {
            format!("Response call-state input.actions[{index}].kind must be a string")
        })?;
        let step_before = call.step();
        let input = match kind {
            "send-ok" => ResponseCallInput::Send(Ok(())),
            "send-error" => {
                ResponseCallInput::Send(Err(
                    string_field(action, "message", "Response action")?.to_owned()
                ))
            }
            "background-ok" => ResponseCallInput::BackgroundFinished(Ok(())),
            "background-error" => ResponseCallInput::BackgroundFinished(Err(string_field(
                action,
                "message",
                "Response action",
            )?
            .to_owned())),
            _ => {
                return Err(format!(
                    "Response call-state action {kind:?} is unsupported"
                ));
            }
        };
        let outcome = match call.advance(input) {
            Ok(_) => {
                if let ResponseCallStep::Send(event) = step_before {
                    events.push(response_event_value(&event));
                }
                if matches!(kind, "background-ok" | "background-error") {
                    background_called = true;
                }
                None
            }
            Err(ResponseCallError::Operation(message)) => Some(message),
            Err(ResponseCallError::UnexpectedInput) => {
                Some(String::from("unexpected response call input"))
            }
        };
        if let Some(message) = outcome {
            if matches!(kind, "background-ok" | "background-error") {
                background_called = true;
            }
            error = json!({"message": message});
            break;
        }
    }
    Ok((events, background_called, error))
}

fn response_event_value(event: &starlette_rs::ResponseEvent) -> Value {
    match event {
        starlette_rs::ResponseEvent::Start {
            status_code,
            headers,
        } => json!({
            "kind": "send-start",
            "status_code": status_code,
            "headers_base64_pairs": headers.iter().map(|(name, value)| [base64::engine::general_purpose::STANDARD.encode(name), base64::engine::general_purpose::STANDARD.encode(value)]).collect::<Vec<_>>(),
        }),
        starlette_rs::ResponseEvent::Body { body } => json!({
            "kind": "send-body",
            "body_base64": base64::engine::general_purpose::STANDARD.encode(body),
        }),
    }
}

fn dispatch_plan_value(plan: &starlette_rs::HttpDispatchPlan) -> Value {
    match plan {
        starlette_rs::HttpDispatchPlan::Matched {
            route_index,
            path_params,
        } => json!({
            "kind": "matched", "route_index": route_index, "path_params": path_params_value(path_params)
        }),
        starlette_rs::HttpDispatchPlan::MethodNotAllowed {
            route_index,
            allowed_methods,
            path_params,
        } => json!({
            "kind": "method-not-allowed", "route_index": route_index,
            "allowed_methods": allowed_methods, "path_params": path_params_value(path_params)
        }),
        starlette_rs::HttpDispatchPlan::Redirect { path } => {
            json!({"kind": "redirect", "path": path})
        }
        starlette_rs::HttpDispatchPlan::NotFound => json!({"kind": "not-found"}),
    }
}

fn path_params_value(path_params: &[(String, String)]) -> Value {
    let mut values = Map::new();
    for (name, value) in path_params {
        values.insert(name.clone(), json!(value));
    }
    Value::Object(values)
}

fn run_path_builds(table: &RouteTable, input: Option<&Value>) -> Result<Vec<Value>, String> {
    let empty = Vec::new();
    input
        .map(|value| {
            value
                .as_array()
                .ok_or_else(|| String::from("RouteTable path_builds must be an array"))
        })
        .transpose()?
        .unwrap_or(&empty)
        .iter()
        .map(|raw| {
            let build = exact_object(raw, &["route_index", "params"], "RouteTable path build")?;
            let route_index = usize_field(build, "route_index", "RouteTable path build")?;
            let params = string_pairs(build, "params", "RouteTable path build")?;
            Ok(match table.build_path_partial(route_index, &params) {
                Ok((path, remaining)) => {
                    json!({"status": "ok", "path": path, "remaining": remaining})
                }
                Err(error) => json!({"status": "error", "display": error.to_string()}),
            })
        })
        .collect()
}

fn run_captures(table: &RouteTable, input: Option<&Value>) -> Result<Vec<Value>, String> {
    let empty = Vec::new();
    input
        .map(|value| value.as_array().ok_or_else(|| String::from("RouteTable captures must be an array")))
        .transpose()?
        .unwrap_or(&empty)
        .iter()
        .map(|raw| {
            let capture = exact_object(raw, &["route_index", "params"], "RouteTable capture")?;
            let route_index = usize_field(capture, "route_index", "RouteTable capture")?;
            let params = string_pairs(capture, "params", "RouteTable capture")?;
            Ok(match table.capture_path_parameters(route_index, &params) {
                Ok(values) => json!({"status": "ok", "values": values.iter().map(|value| json!({"name": value.name, "value": value.value, "converter": format!("{:?}", value.converter)})).collect::<Vec<_>>()}),
                Err(error) => json!({"status": "error", "display": error.to_string()}),
            })
        })
        .collect()
}

fn direct_case<'a>(
    case: &'a Value,
    expected_surface: &str,
    expected_operation: &str,
) -> Result<(&'a str, &'a Value), String> {
    let case = case
        .as_object()
        .ok_or_else(|| String::from("native direct case must be an object"))?;
    let case_id = case
        .get("case_id")
        .and_then(Value::as_str)
        .ok_or_else(|| String::from("native direct case.case_id must be a string"))?;
    if case.get("surface").and_then(Value::as_str) != Some(expected_surface)
        || case.get("operation").and_then(Value::as_str) != Some(expected_operation)
    {
        return Err(String::from(
            "native direct case surface or operation is unsupported",
        ));
    }
    if case.get("assets") != Some(&json!([]))
        || case.get("observations") != Some(&json!(["workflow"]))
    {
        return Err(String::from(
            "native direct cases require empty assets and the workflow observation",
        ));
    }
    let input = case
        .get("input")
        .ok_or_else(|| String::from("native direct case.input is required"))?;
    if !input.is_object() {
        return Err(String::from("native direct case.input must be an object"));
    }
    Ok((case_id, input))
}

fn exact_object<'a>(
    value: &'a Value,
    expected: &[&str],
    context: &str,
) -> Result<&'a Map<String, Value>, String> {
    let object = value
        .as_object()
        .ok_or_else(|| format!("{context} must be an object"))?;
    if object.len() != expected.len() || object.keys().any(|key| !expected.contains(&key.as_str()))
    {
        return Err(format!(
            "{context} must contain exactly these fields: {}",
            expected.join(", ")
        ));
    }
    Ok(object)
}

fn string_field<'a>(
    object: &'a Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<&'a str, String> {
    object
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{context}.{name} must be a string"))
}

fn optional_string<'a>(
    object: &'a Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<Option<&'a str>, String> {
    match object.get(name) {
        Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value)),
        _ => Err(format!("{context}.{name} must be a string or null")),
    }
}

fn bool_field(object: &Map<String, Value>, name: &str, context: &str) -> Result<bool, String> {
    object
        .get(name)
        .and_then(Value::as_bool)
        .ok_or_else(|| format!("{context}.{name} must be a boolean"))
}

fn usize_field(object: &Map<String, Value>, name: &str, context: &str) -> Result<usize, String> {
    object
        .get(name)
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| format!("{context}.{name} must be a usize"))
}

fn u16_field(object: &Map<String, Value>, name: &str, context: &str) -> Result<u16, String> {
    object
        .get(name)
        .and_then(Value::as_u64)
        .and_then(|value| u16::try_from(value).ok())
        .ok_or_else(|| format!("{context}.{name} must be a u16"))
}

fn string_array(
    object: &Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<Vec<String>, String> {
    object
        .get(name)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.{name} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, value)| {
            value
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("{context}.{name}[{index}] must be a string"))
        })
        .collect()
}

fn string_pairs(
    object: &Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<Vec<(String, String)>, String> {
    object
        .get(name)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.{name} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let pair = value
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}.{name}[{index}] must be a pair"))?;
            let key = pair[0]
                .as_str()
                .ok_or_else(|| format!("{context}.{name}[{index}][0] must be a string"))?;
            let value = pair[1]
                .as_str()
                .ok_or_else(|| format!("{context}.{name}[{index}][1] must be a string"))?;
            Ok((key.to_owned(), value.to_owned()))
        })
        .collect()
}

fn base64_pairs(
    object: &Map<String, Value>,
    name: &str,
    context: &str,
) -> Result<EncodedPairs, String> {
    object
        .get(name)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{context}.{name} must be an array"))?
        .iter()
        .enumerate()
        .map(|(index, value)| {
            let pair = value
                .as_array()
                .filter(|pair| pair.len() == 2)
                .ok_or_else(|| format!("{context}.{name}[{index}] must be a pair"))?;
            let key = pair[0]
                .as_str()
                .ok_or_else(|| format!("{context}.{name}[{index}][0] must be base64"))?;
            let value = pair[1]
                .as_str()
                .ok_or_else(|| format!("{context}.{name}[{index}][1] must be base64"))?;
            Ok((decode_base64(key, context)?, decode_base64(value, context)?))
        })
        .collect()
}

fn decode_base64(value: &str, context: &str) -> Result<Vec<u8>, String> {
    base64::engine::general_purpose::STANDARD
        .decode(value)
        .map_err(|error| format!("{context} is invalid base64: {error}"))
}

fn direct_result(case_id: &str, values: Map<String, Value>) -> Result<Value, String> {
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
