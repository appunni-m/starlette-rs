//! Rust orchestration of FileResponse's public stat and ASGI hooks.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyFileNotFoundError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use crate::file_response_runtime::PublicFileFacts;

pub(crate) fn call(
    py: Python<'_>,
    response: Py<PyAny>,
    scope: Py<PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        FileCall {
            response,
            scope,
            receive,
            send,
            facts: None,
            stat: None,
            handled_error: None,
            pending: Pending::Start,
        },
    )
}

enum Pending {
    Start,
    Stat,
    Body,
    ErrorResponse,
    Background,
}

struct FileCall {
    response: Py<PyAny>,
    scope: Py<PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    facts: Option<PublicFileFacts>,
    stat: Option<Py<PyAny>>,
    handled_error: Option<Py<PyAny>>,
    pending: Pending,
}

impl AwaitableStateMachine for FileCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.response)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.stat)?;
        visit.call(&self.handled_error)
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        match input {
            MachineResume::Start => self.start(py),
            MachineResume::Value(stat) => match self.pending {
                Pending::Stat => {
                    // The source's try block includes both worker stat and the
                    // public hook. A FileNotFoundError from either is wrapped.
                    if let Err(error) = self
                        .response
                        .bind(py)
                        .call_method1("set_stat_headers", (stat.bind(py),))
                    {
                        return Err(self.stat_error(py, error)?);
                    }
                    let mode: u64 = stat.bind(py).getattr("st_mode")?.extract()?;
                    if mode & 0o170_000 != 0o100_000 {
                        return Err(PyRuntimeError::new_err(format!(
                            "File at path {} is not a file.",
                            self.response.bind(py).getattr("path")?.str()?
                        )));
                    }
                    self.body(py, stat)
                }
                Pending::Body => {
                    let response = self.response.bind(py);
                    if response.getattr("background")?.is_none() {
                        Ok(MachineAction::Complete(py.None()))
                    } else {
                        self.pending = Pending::Background;
                        Ok(MachineAction::Await(
                            response.getattr("background")?.call0()?.unbind(),
                        ))
                    }
                }
                Pending::ErrorResponse | Pending::Background => {
                    Ok(MachineAction::Complete(py.None()))
                }
                Pending::Start => Err(PyRuntimeError::new_err(
                    "file call resumed before stat selection",
                )),
            },
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                if matches!(self.pending, Pending::Stat) {
                    Err(self.stat_error(py, error)?)
                } else {
                    if matches!(self.pending, Pending::ErrorResponse) {
                        if let Some(original) = &self.handled_error {
                            error.set_context(
                                py,
                                Some(PyErr::from_value(original.bind(py).clone())),
                            );
                        }
                    }
                    Err(error)
                }
            }
        }
    }
}

impl FileCall {
    fn start(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let scope = self.scope.bind(py);
        let scope_type = scope
            .get_item("type")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("type"))?;
        let http = scope_type.eq("http")?;
        let header_only = http
            && scope
                .get_item("method")?
                .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("method"))?
                .call_method0("upper")?
                .eq("HEAD")?;
        let pathsend = http
            && match scope.get_item("extensions")? {
                Some(extensions) => extensions.contains("http.response.pathsend")?,
                None => false,
            };
        if scope_type.eq("websocket")? {
            self.send = self
                .response
                .bind(py)
                .call_method1("_wrap_websocket_denial_send", (self.send.bind(py),))?
                .unbind();
        }
        self.facts = Some(PublicFileFacts {
            header_only,
            pathsend,
        });
        let response = self.response.bind(py);
        if response.getattr("stat_result")?.is_none() {
            let stat = py.import("os")?.getattr("stat")?;
            let path = response.getattr("path")?;
            self.pending = Pending::Stat;
            Ok(MachineAction::Await(
                py.import("anyio.to_thread")?
                    .getattr("run_sync")?
                    .call1((stat, path))?
                    .unbind(),
            ))
        } else {
            self.body(py, response.getattr("stat_result")?.unbind())
        }
    }

    fn stat_error(&self, py: Python<'_>, error: PyErr) -> PyResult<PyErr> {
        if !error.is_instance_of::<PyFileNotFoundError>(py) {
            return Ok(error);
        }
        let result = PyRuntimeError::new_err(format!(
            "File at path {} does not exist.",
            self.response.bind(py).getattr("path")?.str()?
        ));
        result.value(py).setattr("__context__", error.value(py))?;
        Ok(result)
    }

    fn body(&mut self, py: Python<'_>, stat: Py<PyAny>) -> PyResult<MachineAction> {
        // The source keeps its stat_result local alive through the body and
        // background callback even if the public attribute is later replaced.
        self.stat = Some(stat.clone_ref(py));
        let facts = self
            .facts
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("file call lost its scope facts"))?;
        let response = self.response.bind(py);
        let kwargs = PyDict::new(py);
        kwargs.set_item("scope", self.scope.bind(py))?;
        let headers = py
            .import("starlette.datastructures")?
            .getattr("Headers")?
            .call((), Some(&kwargs))?;
        let range = headers.call_method1("get", ("range",))?;
        let if_range = headers.call_method1("get", ("if-range",))?;
        let simple = range.is_none()
            || (!if_range.is_none()
                && !response
                    .call_method1("_should_use_range", (if_range,))?
                    .is_truthy()?);
        let awaitable = if simple {
            response.call_method1(
                "_handle_simple",
                (self.send.bind(py), facts.header_only, facts.pathsend),
            )?
        } else {
            let parsed = response.call_method1(
                "_parse_range_header",
                (range, stat.bind(py).getattr("st_size")?),
            );
            let ranges = match parsed {
                Ok(ranges) => ranges,
                Err(error) => {
                    let module = py.import("starlette.responses")?;
                    let kwargs = PyDict::new(py);
                    let error_response = if error
                        .value(py)
                        .is_instance(&module.getattr("MalformedRangeHeader")?)?
                    {
                        kwargs.set_item("status_code", 400)?;
                        module
                            .getattr("PlainTextResponse")?
                            .call((error.value(py).getattr("content")?,), Some(&kwargs))?
                    } else if error
                        .value(py)
                        .is_instance(&module.getattr("RangeNotSatisfiable")?)?
                    {
                        kwargs.set_item("status_code", 416)?;
                        let headers = PyDict::new(py);
                        headers.set_item(
                            "Content-Range",
                            format!("bytes */{}", error.value(py).getattr("max_size")?.str()?),
                        )?;
                        kwargs.set_item("headers", headers)?;
                        module
                            .getattr("PlainTextResponse")?
                            .call((), Some(&kwargs))?
                    } else {
                        return Err(error);
                    };
                    self.handled_error = Some(error.value(py).clone().into_any().unbind());
                    self.pending = Pending::ErrorResponse;
                    return Ok(MachineAction::Await(
                        error_response
                            .call1((
                                self.scope.bind(py),
                                self.receive.bind(py),
                                self.send.bind(py),
                            ))?
                            .unbind(),
                    ));
                }
            };
            match ranges.len()? {
                0 => response.call_method1(
                    "_handle_simple",
                    (self.send.bind(py), facts.header_only, facts.pathsend),
                )?,
                1 => {
                    let range = ranges.get_item(0)?;
                    response.call_method1(
                        "_handle_single_range",
                        (
                            self.send.bind(py),
                            range.get_item(0)?,
                            range.get_item(1)?,
                            stat.bind(py).getattr("st_size")?,
                            facts.header_only,
                        ),
                    )?
                }
                _ => response.call_method1(
                    "_handle_multiple_ranges",
                    (
                        self.send.bind(py),
                        ranges,
                        stat.bind(py).getattr("st_size")?,
                        facts.header_only,
                    ),
                )?,
            }
        }
        .unbind();
        self.pending = Pending::Body;
        Ok(MachineAction::Await(awaitable))
    }
}
