//! Rust-owned dispatch semantics for the pinned Starlette 1.6.0 host middleware.

use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyAssertionError, PyRuntimeError, PyStopAsyncIteration};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString, PyTuple};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_python_awaitable,
};

const ENFORCE_DOMAIN_WILDCARD: &str = "Domain wildcard patterns must be like '*.example.com'.";

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(https_redirect_middleware_call, module)?)?;
    module.add_function(wrap_pyfunction!(trusted_host_validate, module)?)?;
    module.add_function(wrap_pyfunction!(trusted_host_list, module)?)?;
    module.add_function(wrap_pyfunction!(trusted_host_contains, module)?)?;
    module.add_function(wrap_pyfunction!(trusted_host_middleware_call, module)?)?;
    Ok(())
}

#[pyfunction(name = "_https_redirect_middleware_call")]
fn https_redirect_middleware_call(
    py: Python<'_>,
    app: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        HttpsRedirectCall {
            app,
            scope,
            receive,
            send,
            url_type,
            redirect_response_type,
            pending: false,
        },
    )
}

struct HttpsRedirectCall {
    app: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for HttpsRedirectCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("HTTPS redirect middleware continuation is not pending"),
            ),
        }
    }
}

impl HttpsRedirectCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope_type = self.scope.bind(py).get_item("type")?;
        let supported_types = PyTuple::new(py, ["http", "websocket"])?;
        if !supported_types.contains(&scope_type)? {
            return self.call_app(py);
        }

        let scheme = self.scope.bind(py).get_item("scheme")?;
        let cleartext_schemes = PyTuple::new(py, ["http", "ws"])?;
        if !cleartext_schemes.contains(&scheme)? {
            return self.call_app(py);
        }

        let url = url_from_scope(py, self.scope.bind(py), self.url_type.bind(py))?;
        let replacements = PyDict::new(py);
        replacements.set_item("http", "https")?;
        replacements.set_item("ws", "wss")?;
        let redirect_scheme =
            replacements.call_method1("__getitem__", (url.getattr("scheme")?,))?;
        let port = url.getattr("port")?;
        let default_ports = PyTuple::new(py, [80, 443])?;
        let netloc = if default_ports.contains(&port)? {
            url.getattr("hostname")?
        } else {
            url.getattr("netloc")?
        };
        let components = PyDict::new(py);
        components.set_item("scheme", redirect_scheme)?;
        components.set_item("netloc", netloc)?;
        let redirect_url = url.call_method("replace", (), Some(&components))?;
        let response_arguments = PyDict::new(py);
        response_arguments.set_item("status_code", 307)?;
        let response = self
            .redirect_response_type
            .bind(py)
            .call((redirect_url,), Some(&response_arguments))?;
        self.call_response(py, &response)
    }

    fn call_app(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let awaitable = self.app.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn call_response(
        &mut self,
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
    ) -> PyResult<MachineAction> {
        let awaitable = response.call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

/// Validate patterns before the Python facade installs any public fields.
#[pyfunction(name = "_trusted_host_validate")]
fn trusted_host_validate(py: Python<'_>, allowed_hosts: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
    let allowed_hosts = match allowed_hosts {
        Some(allowed_hosts) => allowed_hosts,
        None => PyList::new(py, ["*"])?.into_any().unbind(),
    };
    let slice = py
        .import("builtins")?
        .getattr("slice")?
        .call1((1, py.None(), py.None()))?;
    for pattern in allowed_hosts.bind(py).try_iter()? {
        let pattern = pattern?;
        let suffix = pattern.get_item(&slice)?;
        if suffix.contains("*")? {
            return Err(PyAssertionError::new_err(ENFORCE_DOMAIN_WILDCARD));
        }
        let starts_with_wildcard = pattern.call_method1("startswith", ("*",))?.is_truthy()?;
        if starts_with_wildcard {
            let is_single_wildcard = pattern.rich_compare("*", CompareOp::Ne)?.is_truthy()?;
            if is_single_wildcard {
                let starts_with_domain_wildcard =
                    pattern.call_method1("startswith", ("*.",))?.is_truthy()?;
                if !starts_with_domain_wildcard {
                    return Err(PyAssertionError::new_err(ENFORCE_DOMAIN_WILDCARD));
                }
            }
        }
    }
    Ok(allowed_hosts)
}

/// Reproduce list(allowed_hosts) at the public constructor's assignment point.
#[pyfunction(name = "_trusted_host_list")]
fn trusted_host_list(py: Python<'_>, allowed_hosts: Py<PyAny>) -> PyResult<Py<PyAny>> {
    py.import("builtins")?
        .getattr("list")?
        .call1((allowed_hosts,))
        .map(Bound::unbind)
}

/// Reproduce the later membership check, including iterator inputs.
#[pyfunction(name = "_trusted_host_contains")]
fn trusted_host_contains(allowed_hosts: &Bound<'_, PyAny>) -> PyResult<bool> {
    allowed_hosts.contains("*")
}

#[pyfunction(name = "_trusted_host_middleware_call")]
fn trusted_host_middleware_call(py: Python<'_>, args: TrustedHostCallArgs) -> PyResult<Py<PyAny>> {
    into_python_awaitable(
        py,
        TrustedHostCall {
            app: args.app,
            allowed_hosts: args.allowed_hosts,
            allow_any: args.allow_any,
            www_redirect: args.www_redirect,
            scope: args.scope,
            receive: args.receive,
            send: args.send,
            connection_type: args.connection_type,
            url_type: args.url_type,
            redirect_response_type: args.redirect_response_type,
            plain_text_response_type: args.plain_text_response_type,
            pending: false,
        },
    )
}

#[derive(FromPyObject)]
#[pyo3(from_item_all)]
struct TrustedHostCallArgs {
    app: Py<PyAny>,
    allowed_hosts: Py<PyAny>,
    allow_any: Py<PyAny>,
    www_redirect: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    connection_type: Py<PyAny>,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
}

struct TrustedHostCall {
    app: Py<PyAny>,
    allowed_hosts: Py<PyAny>,
    allow_any: Py<PyAny>,
    www_redirect: Py<PyAny>,
    scope: Py<PyAny>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    connection_type: Py<PyAny>,
    url_type: Py<PyAny>,
    redirect_response_type: Py<PyAny>,
    plain_text_response_type: Py<PyAny>,
    pending: bool,
}

impl AwaitableStateMachine for TrustedHostCall {
    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start if !self.pending => self.start(py),
            MachineResume::Value(_) if self.pending => {
                self.pending = false;
                Ok(MachineAction::Complete(py.None()))
            }
            MachineResume::Error(error) if self.pending => {
                self.pending = false;
                Err(error)
            }
            MachineResume::AsyncIterationComplete => Err(PyStopAsyncIteration::new_err(())),
            MachineResume::Start | MachineResume::Value(_) | MachineResume::Error(_) => Err(
                PyRuntimeError::new_err("trusted-host middleware continuation is not pending"),
            ),
        }
    }
}

impl TrustedHostCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.allow_any.bind(py).is_truthy()? {
            return self.call_app(py);
        }
        let scope_type = self.scope.bind(py).get_item("type")?;
        let supported_types = PyTuple::new(py, ["http", "websocket"])?;
        if !supported_types.contains(&scope_type)? {
            return self.call_app(py);
        }

        let connection = self
            .connection_type
            .bind(py)
            .call1((self.scope.bind(py),))?;
        let headers = connection.getattr("headers")?;
        let host = headers
            .call_method1("get", ("host", ""))?
            .call_method1("split", (":",))?
            .get_item(0)?;
        let slice = py
            .import("builtins")?
            .getattr("slice")?
            .call1((1, py.None(), py.None()))?;
        let mut is_valid_host = false;
        let mut found_www_redirect = false;
        for pattern in self.allowed_hosts.bind(py).try_iter()? {
            let pattern = pattern?;
            let matches_exactly = host.eq(&pattern)?;
            let matches_wildcard = if matches_exactly {
                false
            } else {
                let starts_with_wildcard =
                    pattern.call_method1("startswith", ("*",))?.is_truthy()?;
                if starts_with_wildcard {
                    let suffix = pattern.get_item(&slice)?;
                    host.call_method1("endswith", (suffix,))?.is_truthy()?
                } else {
                    false
                }
            };
            if matches_exactly || matches_wildcard {
                is_valid_host = true;
                break;
            }
            let www_host = PyString::new(py, "www.").call_method1("__add__", (&host,))?;
            if www_host.eq(&pattern)? {
                found_www_redirect = true;
            }
        }

        if is_valid_host {
            return self.call_app(py);
        }
        if found_www_redirect && self.www_redirect.bind(py).is_truthy()? {
            let url = url_from_scope(py, self.scope.bind(py), self.url_type.bind(py))?;
            let netloc =
                PyString::new(py, "www.").call_method1("__add__", (url.getattr("netloc")?,))?;
            let components = PyDict::new(py);
            components.set_item("netloc", netloc)?;
            let redirect_url = url.call_method("replace", (), Some(&components))?;
            let redirect_url = py
                .import("builtins")?
                .getattr("str")?
                .call1((redirect_url,))?;
            let response_arguments = PyDict::new(py);
            response_arguments.set_item("url", redirect_url)?;
            let response = self
                .redirect_response_type
                .bind(py)
                .call((), Some(&response_arguments))?;
            self.call_response(py, &response)
        } else {
            let response_arguments = PyDict::new(py);
            response_arguments.set_item("status_code", 400)?;
            let response = self
                .plain_text_response_type
                .bind(py)
                .call(("Invalid host header",), Some(&response_arguments))?;
            self.call_response(py, &response)
        }
    }

    fn call_app(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let awaitable = self.app.bind(py).call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn call_response(
        &mut self,
        py: Python<'_>,
        response: &Bound<'_, PyAny>,
    ) -> PyResult<MachineAction> {
        let awaitable = response.call1((
            self.scope.bind(py),
            self.receive.bind(py),
            self.send.bind(py),
        ))?;
        self.pending = true;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn url_from_scope<'py>(
    py: Python<'py>,
    scope: &Bound<'py, PyAny>,
    url_type: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let arguments = PyDict::new(py);
    arguments.set_item("scope", scope)?;
    url_type.call((), Some(&arguments))
}
