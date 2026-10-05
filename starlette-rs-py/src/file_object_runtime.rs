//! Rust orchestration of FileResponse's public stat and ASGI hooks.

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyFileNotFoundError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};
use crate::file_response_runtime::{PublicFileFacts, prepared_public_call};

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
            pending: Pending::Start,
        },
    )
}

enum Pending {
    Start,
    Stat,
    Body,
}

struct FileCall {
    response: Py<PyAny>,
    scope: Py<PyDict>,
    receive: Py<PyAny>,
    send: Py<PyAny>,
    facts: Option<PublicFileFacts>,
    stat: Option<Py<PyAny>>,
    pending: Pending,
}

impl AwaitableStateMachine for FileCall {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.response)?;
        visit.call(&self.scope)?;
        visit.call(&self.receive)?;
        visit.call(&self.send)?;
        visit.call(&self.stat)
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
                Pending::Body => Ok(MachineAction::Complete(py.None())),
                Pending::Start => Err(PyRuntimeError::new_err(
                    "file call resumed before stat selection",
                )),
            },
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                if matches!(self.pending, Pending::Stat) {
                    Err(self.stat_error(py, error)?)
                } else {
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
            scope_type: scope_type.extract()?,
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
        let awaitable = prepared_public_call(
            py,
            self.response.clone_ref(py),
            self.scope.bind(py),
            self.receive.clone_ref(py),
            self.send.clone_ref(py),
            stat,
            facts,
        )?;
        self.pending = Pending::Body;
        Ok(MachineAction::Await(awaitable))
    }
}
