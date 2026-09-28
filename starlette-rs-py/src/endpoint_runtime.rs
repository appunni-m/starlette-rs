//! Rust-owned dispatch for Starlette class-based HTTP and WebSocket endpoints.
//!
//! The public Python classes are callback/awaitable facades. Python request,
//! WebSocket, response, JSON, and user callback objects remain at the boundary;
//! Rust owns scope checks, handler selection, decoding policy, and protocol
//! sequencing.

use pyo3::exceptions::{PyAssertionError, PyException, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(endpoint_validate_scope, module)?)?;
    module.add_function(wrap_pyfunction!(http_endpoint_allowed_methods, module)?)?;
    module.add_function(wrap_pyfunction!(http_endpoint_dispatch, module)?)?;
    module.add_function(wrap_pyfunction!(http_endpoint_method_not_allowed, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_endpoint_dispatch, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_endpoint_decode, module)?)?;
    module.add_function(wrap_pyfunction!(websocket_endpoint_on_connect, module)?)?;
    Ok(())
}

#[pyfunction(name = "_endpoint_validate_scope")]
fn endpoint_validate_scope(scope: &Bound<'_, PyAny>, expected: &str, debug: bool) -> PyResult<()> {
    if debug && !scope.get_item("type")?.eq(expected)? {
        return Err(PyAssertionError::new_err(()));
    }
    Ok(())
}

#[pyfunction(name = "_http_endpoint_allowed_methods")]
fn http_endpoint_allowed_methods(
    py: Python<'_>,
    endpoint: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let names = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"];
    let getattr = py.import("builtins")?.getattr("getattr")?;
    let methods = PyList::empty(py);
    for method in names {
        let name = method.to_ascii_lowercase();
        let handler = getattr.call1((endpoint, name, py.None()))?;
        if !handler.is_none() {
            methods.append(method)?;
        }
    }
    Ok(methods.into_any().unbind())
}

#[pyfunction(name = "_http_endpoint_dispatch")]
fn http_endpoint_dispatch(
    py: Python<'_>,
    endpoint: Py<PyAny>,
    request_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        HttpEndpointCall {
            endpoint,
            request_type,
            run_in_threadpool,
            pending: None,
        },
    )
}

#[derive(Clone, Copy)]
enum HttpEndpointPending {
    Handler,
    Response,
}

struct HttpEndpointCall {
    endpoint: Py<PyAny>,
    request_type: Py<PyAny>,
    run_in_threadpool: Py<PyAny>,
    pending: Option<HttpEndpointPending>,
}

impl AwaitableStateMachine for HttpEndpointCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(HttpEndpointPending::Handler) => self.send_response(py, value),
                Some(HttpEndpointPending::Response) => Ok(MachineAction::Complete(py.None())),
                None => Err(PyRuntimeError::new_err(
                    "HTTP endpoint continuation has no pending operation",
                )),
            },
            MachineResume::Error(error) => {
                self.pending = None;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "HTTP endpoint continuation has a pending operation",
            )),
        }
    }
}

impl HttpEndpointCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.endpoint.bind(py).getattr("scope")?;
        let receive = self.endpoint.bind(py).getattr("receive")?;
        let request_arguments = PyDict::new(py);
        request_arguments.set_item("receive", receive)?;
        let request = self
            .request_type
            .bind(py)
            .call((scope,), Some(&request_arguments))?;
        let method = request.getattr("method")?;
        let is_head = method.eq("HEAD")?;
        let handler_name = if is_head
            && !py
                .import("builtins")?
                .getattr("hasattr")?
                .call1((self.endpoint.bind(py), "head"))?
                .extract::<bool>()?
        {
            PyString::new(py, "get").into_any()
        } else {
            method.call_method0("lower")?
        };
        let allowed_methods = self.endpoint.bind(py).getattr("_allowed_methods")?;
        let is_allowed =
            allowed_methods.contains(&method)? || (is_head && allowed_methods.contains("GET")?);
        let handler = if is_allowed {
            py.import("builtins")?
                .getattr("getattr")?
                .call1((self.endpoint.bind(py), handler_name))?
        } else {
            self.endpoint.bind(py).getattr("method_not_allowed")?
        };
        let is_async = crate::background::is_async_callable(py, &handler)?;
        let awaitable = if is_async {
            handler.call1((request,))?
        } else {
            self.run_in_threadpool.bind(py).call1((handler, request))?
        };
        self.pending = Some(HttpEndpointPending::Handler);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn send_response(&mut self, py: Python<'_>, response: Py<PyAny>) -> PyResult<MachineAction> {
        let scope = self.endpoint.bind(py).getattr("scope")?;
        let receive = self.endpoint.bind(py).getattr("receive")?;
        let send = self.endpoint.bind(py).getattr("send")?;
        let awaitable = response.bind(py).call1((scope, receive, send))?;
        self.pending = Some(HttpEndpointPending::Response);
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

#[pyfunction(name = "_http_endpoint_method_not_allowed")]
fn http_endpoint_method_not_allowed(
    py: Python<'_>,
    endpoint: &Bound<'_, PyAny>,
    _request: &Bound<'_, PyAny>,
    http_exception_type: &Bound<'_, PyAny>,
    plain_text_response_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let methods = endpoint.getattr("_allowed_methods")?;
    let allow = PyString::new(py, ", ").call_method1("join", (methods,))?;
    let headers = PyDict::new(py);
    headers.set_item("Allow", allow)?;
    let scope = endpoint.getattr("scope")?;
    if scope.contains("app")? {
        let arguments = PyDict::new(py);
        arguments.set_item("status_code", 405)?;
        arguments.set_item("headers", headers)?;
        let exception = http_exception_type.call((), Some(&arguments))?;
        return Err(PyErr::from_value(exception));
    }
    let arguments = PyDict::new(py);
    arguments.set_item("status_code", 405)?;
    arguments.set_item("headers", headers)?;
    plain_text_response_type
        .call(("Method Not Allowed",), Some(&arguments))
        .map(Bound::unbind)
}

#[pyfunction(name = "_websocket_endpoint_dispatch")]
fn websocket_endpoint_dispatch(
    py: Python<'_>,
    endpoint: Py<PyAny>,
    websocket_type: Py<PyAny>,
    status_module: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        WebSocketEndpointCall {
            endpoint,
            websocket_type,
            status_module,
            websocket: None,
            close_code: None,
            original_exception: None,
            pending: None,
        },
    )
}

#[derive(Clone, Copy)]
enum WebSocketEndpointPending {
    Connect,
    Receive,
    Decode,
    OnReceive,
    Disconnect,
}

struct WebSocketEndpointCall {
    endpoint: Py<PyAny>,
    websocket_type: Py<PyAny>,
    status_module: Py<PyAny>,
    websocket: Option<Py<PyAny>>,
    close_code: Option<Py<PyAny>>,
    original_exception: Option<PyErr>,
    pending: Option<WebSocketEndpointPending>,
}

impl AwaitableStateMachine for WebSocketEndpointCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if self.pending.is_none() => self.start(py),
            MachineResume::Value(value) => match self.pending.take() {
                Some(WebSocketEndpointPending::Connect) => self.connected(py),
                Some(WebSocketEndpointPending::Receive) => {
                    let result = self.process_message(py, value);
                    self.protocol_result(py, result)
                }
                Some(WebSocketEndpointPending::Decode) => {
                    let result = self.call_on_receive(py, value);
                    self.protocol_result(py, result)
                }
                Some(WebSocketEndpointPending::OnReceive) => {
                    let result = self.receive_next(py);
                    self.protocol_result(py, result)
                }
                Some(WebSocketEndpointPending::Disconnect) => self.disconnected(py),
                None => Err(PyRuntimeError::new_err(
                    "WebSocket endpoint continuation has no pending operation",
                )),
            },
            MachineResume::Error(error) => match self.pending.take() {
                Some(WebSocketEndpointPending::Connect | WebSocketEndpointPending::Disconnect) => {
                    Err(error)
                }
                Some(
                    WebSocketEndpointPending::Receive
                    | WebSocketEndpointPending::Decode
                    | WebSocketEndpointPending::OnReceive,
                ) => self.protocol_error(py, error),
                None => Err(error),
            },
            MachineResume::AsyncIterationComplete => {
                let error = PyStopAsyncIteration::new_err(());
                match self.pending.take() {
                    Some(
                        WebSocketEndpointPending::Connect | WebSocketEndpointPending::Disconnect,
                    ) => Err(error),
                    Some(
                        WebSocketEndpointPending::Receive
                        | WebSocketEndpointPending::Decode
                        | WebSocketEndpointPending::OnReceive,
                    ) => self.protocol_error(py, error),
                    None => Err(error),
                }
            }
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "WebSocket endpoint continuation has a pending operation",
            )),
        }
    }
}

impl WebSocketEndpointCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.endpoint.bind(py).getattr("scope")?;
        let receive = self.endpoint.bind(py).getattr("receive")?;
        let send = self.endpoint.bind(py).getattr("send")?;
        let arguments = PyDict::new(py);
        arguments.set_item("receive", receive)?;
        arguments.set_item("send", send)?;
        let websocket = self
            .websocket_type
            .bind(py)
            .call((scope,), Some(&arguments))?
            .unbind();
        let awaitable = self
            .endpoint
            .bind(py)
            .getattr("on_connect")?
            .call1((websocket.bind(py),))?;
        self.websocket = Some(websocket);
        self.pending = Some(WebSocketEndpointPending::Connect);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn connected(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        self.close_code = Some(
            self.status_module
                .bind(py)
                .getattr("WS_1000_NORMAL_CLOSURE")?
                .unbind(),
        );
        let result = self.receive_next(py);
        self.protocol_result(py, result)
    }

    fn receive_next(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let websocket = self.websocket(py)?;
        let awaitable = websocket.call_method0("receive")?;
        self.pending = Some(WebSocketEndpointPending::Receive);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn process_message(&mut self, py: Python<'_>, message: Py<PyAny>) -> PyResult<MachineAction> {
        let message_type = message.bind(py).get_item("type")?;
        if message_type.eq("websocket.receive")? {
            let websocket = self.websocket(py)?;
            let awaitable = self
                .endpoint
                .bind(py)
                .getattr("decode")?
                .call1((websocket, message.bind(py)))?;
            self.pending = Some(WebSocketEndpointPending::Decode);
            return Ok(MachineAction::Await(awaitable.unbind()));
        }
        if message_type.eq("websocket.disconnect")? {
            let code = message.bind(py).call_method1("get", ("code",))?;
            let code = if code.is_truthy()? {
                code
            } else {
                self.status_module
                    .bind(py)
                    .getattr("WS_1000_NORMAL_CLOSURE")?
            };
            let code = py.import("builtins")?.getattr("int")?.call1((code,))?;
            self.close_code = Some(code.unbind());
            return self.begin_disconnect(py);
        }
        self.receive_next(py)
    }

    fn call_on_receive(&mut self, py: Python<'_>, data: Py<PyAny>) -> PyResult<MachineAction> {
        let websocket = self.websocket(py)?;
        let awaitable = self
            .endpoint
            .bind(py)
            .getattr("on_receive")?
            .call1((websocket, data.bind(py)))?;
        self.pending = Some(WebSocketEndpointPending::OnReceive);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn begin_disconnect(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let websocket = self.websocket(py)?;
        let close_code = self
            .close_code
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("WebSocket endpoint has no close code"))?;
        let awaitable = self
            .endpoint
            .bind(py)
            .getattr("on_disconnect")?
            .call1((websocket, close_code.bind(py)))?;
        self.pending = Some(WebSocketEndpointPending::Disconnect);
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn protocol_result(
        &mut self,
        py: Python<'_>,
        result: PyResult<MachineAction>,
    ) -> PyResult<MachineAction> {
        match result {
            Ok(action) => Ok(action),
            Err(error) => self.protocol_error(py, error),
        }
    }

    fn protocol_error(&mut self, py: Python<'_>, error: PyErr) -> PyResult<MachineAction> {
        let error = if error.is_instance_of::<PyException>(py) {
            match self
                .status_module
                .bind(py)
                .getattr("WS_1011_INTERNAL_ERROR")
            {
                Ok(code) => {
                    self.close_code = Some(code.unbind());
                    error
                }
                Err(status_error) => status_error,
            }
        } else {
            error
        };
        self.original_exception = Some(error);
        self.begin_disconnect(py)
    }

    fn disconnected(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        match self.original_exception.take() {
            Some(error) => Err(error),
            None => Ok(MachineAction::Complete(py.None())),
        }
    }

    fn websocket<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.websocket
            .as_ref()
            .map(|websocket| websocket.bind(py).clone())
            .ok_or_else(|| PyRuntimeError::new_err("WebSocket endpoint has no connection"))
    }
}

#[pyfunction(name = "_websocket_endpoint_decode")]
fn websocket_endpoint_decode(
    py: Python<'_>,
    encoding: Py<PyAny>,
    websocket: Py<PyAny>,
    message: Py<PyAny>,
    json_module: Py<PyAny>,
    status_module: Py<PyAny>,
    debug: bool,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        WebSocketDecodeCall {
            encoding,
            websocket,
            message,
            json_module,
            status_module,
            debug,
            pending_error: None,
            pending: false,
        },
    )
}

struct WebSocketDecodeCall {
    encoding: Py<PyAny>,
    websocket: Py<PyAny>,
    message: Py<PyAny>,
    json_module: Py<PyAny>,
    status_module: Py<PyAny>,
    debug: bool,
    pending_error: Option<PyErr>,
    pending: bool,
}

impl AwaitableStateMachine for WebSocketDecodeCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                match self.pending_error.take() {
                    Some(error) => Err(error),
                    None => Err(PyRuntimeError::new_err(
                        "WebSocket decode continuation has no pending error",
                    )),
                }
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                self.pending_error = None;
                Err(error)
            }
            MachineResume::AsyncIterationComplete if self.pending => {
                self.pending = false;
                self.pending_error = None;
                Err(PyStopAsyncIteration::new_err(()))
            }
            MachineResume::Value(_) => Err(PyRuntimeError::new_err(
                "WebSocket decode continuation has no pending operation",
            )),
            MachineResume::Error(error) => Err(error),
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start => Err(PyRuntimeError::new_err(
                "WebSocket decode continuation has a pending operation",
            )),
        }
    }
}

impl WebSocketDecodeCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let encoding = self.encoding.bind(py);
        if encoding.eq("text")? {
            return self.decode_text(py);
        }
        if encoding.eq("bytes")? {
            return self.decode_bytes(py);
        }
        if encoding.eq("json")? {
            return self.decode_json(py);
        }
        if self.debug && !encoding.is_none() {
            let name = py.import("builtins")?.getattr("str")?.call1((encoding,))?;
            return Err(PyAssertionError::new_err(format!(
                "Unsupported 'encoding' attribute {}",
                name.extract::<String>()?
            )));
        }
        let message = self.message.bind(py);
        let text = message.call_method1("get", ("text",))?;
        if text.is_truthy()? {
            return Ok(MachineAction::Complete(text.unbind()));
        }
        message
            .get_item("bytes")
            .map(|value| MachineAction::Complete(value.unbind()))
    }

    fn decode_text(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py);
        if !message.contains("text")? {
            return self.close_then_error(
                py,
                "WS_1003_UNSUPPORTED_DATA",
                "Expected text websocket messages, but got bytes",
            );
        }
        message
            .get_item("text")
            .map(|value| MachineAction::Complete(value.unbind()))
    }

    fn decode_bytes(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py);
        if !message.contains("bytes")? {
            return self.close_then_error(
                py,
                "WS_1003_UNSUPPORTED_DATA",
                "Expected bytes websocket messages, but got text",
            );
        }
        message
            .get_item("bytes")
            .map(|value| MachineAction::Complete(value.unbind()))
    }

    fn decode_json(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let message = self.message.bind(py);
        let text = message.call_method1("get", ("text",))?;
        let text = if !text.is_none() {
            text
        } else {
            message
                .get_item("bytes")?
                .call_method1("decode", ("utf-8",))?
        };
        let loads = self.json_module.bind(py).getattr("loads")?;
        match loads.call1((text,)) {
            Ok(value) => Ok(MachineAction::Complete(value.unbind())),
            Err(error) => {
                let json_decode_error = self
                    .json_module
                    .bind(py)
                    .getattr("decoder")?
                    .getattr("JSONDecodeError")?;
                if error.value(py).is_instance(&json_decode_error)? {
                    self.close_then_error(
                        py,
                        "WS_1003_UNSUPPORTED_DATA",
                        "Malformed JSON data received.",
                    )
                } else {
                    Err(error)
                }
            }
        }
    }

    fn close_then_error(
        &mut self,
        py: Python<'_>,
        close_code_name: &str,
        error_message: &str,
    ) -> PyResult<MachineAction> {
        let close_code = self.status_module.bind(py).getattr(close_code_name)?;
        let arguments = PyDict::new(py);
        arguments.set_item("code", close_code)?;
        let close = self
            .websocket
            .bind(py)
            .getattr("close")?
            .call((), Some(&arguments))?;
        self.pending_error = Some(PyRuntimeError::new_err(error_message.to_owned()));
        self.pending = true;
        Ok(MachineAction::Await(close.unbind()))
    }
}

#[pyfunction(name = "_websocket_endpoint_on_connect")]
fn websocket_endpoint_on_connect(websocket: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    websocket.call_method0("accept").map(Bound::unbind)
}
