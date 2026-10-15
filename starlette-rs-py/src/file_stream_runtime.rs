//! Rust-owned public FileResponse handlers with live Python I/O callbacks.
//!
//! The caller's loop awaits AnyIO's file operations. Rust selects every read,
//! seek, send, context exit, and multipart transition; user overrides remain
//! Python protocol callbacks. Source: pinned Starlette responses.py (BSD-3-Clause).

use pyo3::class::gc::{PyTraverseError, PyVisit};
use pyo3::exceptions::{PyRuntimeError, PyStopIteration};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

use crate::awaitable::{
    AwaitableStateMachine, MachineAction, MachineResume, into_sendable_python_awaitable,
};

pub(crate) enum BodyKind {
    Simple(bool),
    Single(Py<PyAny>, Py<PyAny>, Py<PyAny>),
    Multiple(Py<PyAny>, Py<PyAny>),
}

pub(crate) fn handler(
    py: Python<'_>,
    response: Py<PyAny>,
    send: Py<PyAny>,
    header_only: bool,
    kind: BodyKind,
) -> PyResult<Py<PyAny>> {
    into_sendable_python_awaitable(
        py,
        FileBody {
            response,
            send,
            header_only,
            kind,
            pending: Pending::Start,
            manager: None,
            file: None,
            range_source: None,
            range_iterator: None,
            start: py.None(),
            end: py.None(),
            multipart_start: py.None(),
            multipart_end: py.None(),
            generator: None,
            boundary: None,
            chunk: None,
            more_body: true,
            error: None,
        },
    )
}

enum Pending {
    Start,
    Headers,
    Final,
    Open,
    Enter,
    PartHeader,
    Seek,
    Read,
    Chunk,
    Separator,
    Exit,
}

struct FileBody {
    response: Py<PyAny>,
    send: Py<PyAny>,
    header_only: bool,
    kind: BodyKind,
    pending: Pending,
    manager: Option<Py<PyAny>>,
    file: Option<Py<PyAny>>,
    range_source: Option<Py<PyAny>>,
    range_iterator: Option<Py<PyAny>>,
    start: Py<PyAny>,
    end: Py<PyAny>,
    multipart_start: Py<PyAny>,
    multipart_end: Py<PyAny>,
    generator: Option<Py<PyAny>>,
    boundary: Option<String>,
    chunk: Option<Py<PyAny>>,
    more_body: bool,
    error: Option<Py<PyAny>>,
}

impl AwaitableStateMachine for FileBody {
    fn traverse(&self, visit: &PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.response)?;
        visit.call(&self.send)?;
        visit.call(&self.manager)?;
        visit.call(&self.file)?;
        visit.call(&self.range_source)?;
        visit.call(&self.range_iterator)?;
        visit.call(&self.start)?;
        visit.call(&self.end)?;
        visit.call(&self.multipart_start)?;
        visit.call(&self.multipart_end)?;
        visit.call(&self.generator)?;
        visit.call(&self.chunk)?;
        visit.call(&self.error)?;
        match &self.kind {
            BodyKind::Simple(_) => {}
            BodyKind::Single(start, end, size) => {
                visit.call(start)?;
                visit.call(end)?;
                visit.call(size)?;
            }
            BodyKind::Multiple(ranges, size) => {
                visit.call(ranges)?;
                visit.call(size)?;
            }
        }
        Ok(())
    }

    fn finalize_on_drop(&self) -> bool {
        true
    }

    fn resume(&mut self, py: Python<'_>, input: MachineResume) -> PyResult<MachineAction> {
        let result = match input {
            MachineResume::Start => self.headers(py),
            MachineResume::Value(value) => self.advance(py, value),
            MachineResume::Error(error) | MachineResume::AsyncIterationComplete(error) => {
                Err(error)
            }
        };
        match result {
            Err(error) if self.manager.is_some() && !matches!(self.pending, Pending::Exit) => {
                self.error = Some(error.value(py).clone().into_any().unbind());
                self.exit(py)
            }
            Err(error) => {
                if let Some(original) = &self.error {
                    error.set_context(py, Some(PyErr::from_value(original.bind(py).clone())));
                }
                Err(error)
            }
            Ok(action) => Ok(action),
        }
    }
}

impl FileBody {
    fn headers(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let response = self.response.bind(py);
        let message = PyDict::new(py);
        message.set_item("type", "http.response.start")?;
        match &self.kind {
            BodyKind::Simple(_) => {
                message.set_item("status", response.getattr("status_code")?)?;
                message.set_item("headers", response.getattr("raw_headers")?)?;
            }
            BodyKind::Single(start, end, size) => {
                self.start = start.clone_ref(py);
                self.end = end.clone_ref(py);
                let headers = copied_headers(py, response)?;
                let last = end.bind(py).call_method1("__sub__", (1,))?;
                let length = end.bind(py).call_method1("__sub__", (start.bind(py),))?;
                headers.set_item(
                    "content-range",
                    format!(
                        "bytes {}-{}/{}",
                        start.bind(py).str()?,
                        last.str()?,
                        size.bind(py).str()?
                    ),
                )?;
                headers.set_item("content-length", length.str()?)?;
                message.set_item("status", 206)?;
                message.set_item("headers", headers.getattr("raw")?)?;
            }
            BodyKind::Multiple(ranges, size) => {
                let boundary = py.import("secrets")?.getattr("token_hex")?.call1((13,))?;
                let parts = response.call_method1(
                    "generate_multipart",
                    (
                        ranges.bind(py),
                        &boundary,
                        size.bind(py),
                        response.getattr("headers")?.get_item("content-type")?,
                    ),
                )?;
                let length = parts.get_item(0)?;
                self.generator = Some(parts.get_item(1)?.unbind());
                self.boundary = Some(boundary.extract()?);
                self.range_source = Some(ranges.clone_ref(py));
                let headers = copied_headers(py, response)?;
                headers.set_item(
                    "content-type",
                    format!("multipart/byteranges; boundary={}", boundary.str()?),
                )?;
                headers.set_item("content-length", length.str()?)?;
                message.set_item("status", 206)?;
                message.set_item("headers", headers.getattr("raw")?)?;
            }
        }
        self.send_message(py, message, Pending::Headers)
    }

    fn advance(&mut self, py: Python<'_>, value: Py<PyAny>) -> PyResult<MachineAction> {
        match self.pending {
            Pending::Headers => {
                if self.header_only {
                    return self.send_body(
                        py,
                        PyBytes::new(py, b"").into_any().unbind(),
                        false,
                        Pending::Final,
                    );
                }
                if matches!(self.kind, BodyKind::Simple(true)) {
                    let message = PyDict::new(py);
                    message.set_item("type", "http.response.pathsend")?;
                    message.set_item("path", self.response.bind(py).getattr("path")?.str()?)?;
                    return self.send_message(py, message, Pending::Final);
                }
                let kwargs = PyDict::new(py);
                kwargs.set_item("mode", "rb")?;
                let awaitable = py
                    .import("anyio")?
                    .getattr("open_file")?
                    .call((self.response.bind(py).getattr("path")?,), Some(&kwargs))?;
                self.pending = Pending::Open;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            Pending::Open => {
                let awaitable = value
                    .bind(py)
                    .get_type()
                    .getattr("__aenter__")?
                    .call1((value.bind(py),))?;
                // A failed enter must not invoke __aexit__, matching async with.
                self.file = Some(value);
                self.pending = Pending::Enter;
                Ok(MachineAction::Await(awaitable.unbind()))
            }
            Pending::Enter => {
                self.manager = self.file.take();
                self.file = Some(value);
                match self.kind {
                    BodyKind::Simple(_) => self.read(py),
                    BodyKind::Single(_, _, _) => self.seek(py),
                    BodyKind::Multiple(_, _) => self.part(py),
                }
            }
            Pending::PartHeader => self.seek(py),
            Pending::Seek => self.read(py),
            Pending::Read => {
                let size = value.bind(py).len()?;
                self.chunk = Some(value.clone_ref(py));
                match self.kind {
                    BodyKind::Simple(_) => {
                        self.more_body = size
                            .into_pyobject(py)?
                            .into_any()
                            .eq(self.response.bind(py).getattr("chunk_size")?)?;
                    }
                    BodyKind::Single(_, _, _) => {
                        self.start = py
                            .import("operator")?
                            .call_method1("iadd", (self.start.bind(py), size))?
                            .unbind();
                        self.more_body = size
                            .into_pyobject(py)?
                            .into_any()
                            .eq(self.response.bind(py).getattr("chunk_size")?)?
                            && self.start.bind(py).lt(self.end.bind(py))?;
                    }
                    BodyKind::Multiple(_, _) => {
                        self.multipart_start = py
                            .import("operator")?
                            .call_method1("iadd", (self.multipart_start.bind(py), size))?
                            .unbind();
                        self.more_body = true;
                    }
                }
                self.send_body(py, value, self.more_body, Pending::Chunk)
            }
            Pending::Chunk => match self.kind {
                BodyKind::Simple(_) | BodyKind::Single(_, _, _) => {
                    if self.more_body {
                        self.read(py)
                    } else {
                        self.exit(py)
                    }
                }
                BodyKind::Multiple(_, _) => {
                    if self
                        .multipart_start
                        .bind(py)
                        .lt(self.multipart_end.bind(py))?
                    {
                        self.read(py)
                    } else {
                        self.send_body(
                            py,
                            PyBytes::new(py, b"\r\n").into_any().unbind(),
                            true,
                            Pending::Separator,
                        )
                    }
                }
            },
            Pending::Separator => self.part(py),
            Pending::Final => {
                if self.manager.is_some() {
                    self.exit(py)
                } else {
                    Ok(MachineAction::Complete(py.None()))
                }
            }
            Pending::Exit => {
                self.manager = None;
                match self.error.take() {
                    Some(error) if !value.bind(py).is_truthy()? => {
                        Err(PyErr::from_value(error.into_bound(py)))
                    }
                    _ => Ok(MachineAction::Complete(py.None())),
                }
            }
            Pending::Start => Err(PyRuntimeError::new_err("file handler resumed before start")),
        }
    }

    fn file<'py>(&self, py: Python<'py>) -> PyResult<&Bound<'py, PyAny>> {
        self.file
            .as_ref()
            .map(|file| file.bind(py))
            .ok_or_else(|| PyRuntimeError::new_err("file handler has no open file"))
    }

    fn read(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let chunk_size = self.response.bind(py).getattr("chunk_size")?;
        let size = match self.kind {
            BodyKind::Simple(_) => chunk_size,
            BodyKind::Single(_, _, _) => {
                let remaining = self
                    .end
                    .bind(py)
                    .call_method1("__sub__", (self.start.bind(py),))?;
                py.import("builtins")?
                    .getattr("min")?
                    .call1((chunk_size, remaining))?
            }
            BodyKind::Multiple(_, _) => {
                let remaining = self
                    .multipart_end
                    .bind(py)
                    .call_method1("__sub__", (self.multipart_start.bind(py),))?;
                py.import("builtins")?
                    .getattr("min")?
                    .call1((chunk_size, remaining))?
            }
        };
        let awaitable = self.file(py)?.call_method1("read", (size,))?;
        self.pending = Pending::Read;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn seek(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        let position = match self.kind {
            BodyKind::Single(_, _, _) => self.start.clone_ref(py),
            BodyKind::Multiple(_, _) => self.multipart_start.clone_ref(py),
            BodyKind::Simple(_) => {
                return Err(PyRuntimeError::new_err("simple file response cannot seek"));
            }
        };
        let awaitable = self.file(py)?.call_method1("seek", (position,))?;
        self.pending = Pending::Seek;
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn part(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        if self.range_iterator.is_none() {
            let ranges = self.range_source.as_ref().ok_or_else(|| {
                PyRuntimeError::new_err("multipart file handler has no range source")
            })?;
            self.range_iterator = Some(
                py.import("builtins")?
                    .getattr("iter")?
                    .call1((ranges.bind(py),))?
                    .unbind(),
            );
        }
        let iterator = self.range_iterator.as_ref().ok_or_else(|| {
            PyRuntimeError::new_err("multipart file handler has no range iterator")
        })?;
        let iterator = iterator.bind(py);
        let next = iterator.get_type().getattr("__next__")?;
        let range = match next.call1((iterator,)) {
            Ok(range) => Some(range),
            Err(error) if error.is_instance_of::<PyStopIteration>(py) => None,
            Err(error) => return Err(error),
        };
        if let Some(range) = range {
            let (start, end) = crate::file_range_runtime::unpack_range(py, &range)?;
            self.multipart_start = start.clone().unbind();
            self.multipart_end = end.clone().unbind();
            let generator = self.generator.as_ref().ok_or_else(|| {
                PyRuntimeError::new_err("multipart file handler has no header generator")
            })?;
            self.send_body(
                py,
                generator.bind(py).call1((start, end))?.unbind(),
                true,
                Pending::PartHeader,
            )
        } else {
            let boundary = self
                .boundary
                .as_ref()
                .ok_or_else(|| PyRuntimeError::new_err("multipart file handler has no boundary"))?;
            let body = PyBytes::new(py, format!("--{boundary}--").as_bytes())
                .into_any()
                .unbind();
            self.send_body(py, body, false, Pending::Final)
        }
    }

    fn exit(&mut self, py: Python<'_>) -> PyResult<MachineAction> {
        self.pending = Pending::Exit;
        let manager = self
            .manager
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("file handler has no context manager"))?
            .bind(py);
        let awaitable = match &self.error {
            Some(error) => {
                let error = PyErr::from_value(error.bind(py).clone());
                manager.get_type().getattr("__aexit__")?.call1((
                    manager,
                    error.get_type(py),
                    error.value(py),
                    error.traceback(py),
                ))?
            }
            None => manager.get_type().getattr("__aexit__")?.call1((
                manager,
                py.None(),
                py.None(),
                py.None(),
            ))?,
        };
        Ok(MachineAction::Await(awaitable.unbind()))
    }

    fn send_body(
        &mut self,
        py: Python<'_>,
        body: Py<PyAny>,
        more: bool,
        pending: Pending,
    ) -> PyResult<MachineAction> {
        let message = PyDict::new(py);
        message.set_item("type", "http.response.body")?;
        message.set_item("body", body)?;
        message.set_item("more_body", more)?;
        self.send_message(py, message, pending)
    }

    fn send_message(
        &mut self,
        py: Python<'_>,
        message: Bound<'_, PyDict>,
        pending: Pending,
    ) -> PyResult<MachineAction> {
        let awaitable = self.send.bind(py).call1((message,))?;
        self.pending = pending;
        Ok(MachineAction::Await(awaitable.unbind()))
    }
}

fn copied_headers<'py>(
    py: Python<'py>,
    response: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let kwargs = PyDict::new(py);
    kwargs.set_item(
        "raw",
        PyList::new(
            py,
            response
                .getattr("raw_headers")?
                .try_iter()?
                .collect::<PyResult<Vec<_>>>()?,
        )?,
    )?;
    py.import("starlette.datastructures")?
        .getattr("MutableHeaders")?
        .call((), Some(&kwargs))
}
