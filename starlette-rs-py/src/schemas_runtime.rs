//! Rust-owned implementation of Starlette's docstring-based schema generator.
//!
//! Python objects are retained at the PyO3 boundary for route instances,
//! endpoint callables, schema mappings, and the optional PyYAML module. Rust
//! owns route traversal, inclusion rules, path conversion, and schema assembly.

use pyo3::exceptions::{PyAssertionError, PyModuleNotFoundError, PyNotImplementedError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule, PyString};

pub(crate) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(schemas_optional_yaml_module, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_openapi_render, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_openapi_response_init, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_base_get_schema, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_generator_init, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_get_endpoints, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_remove_converter, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_parse_docstring, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_openapi_response, module)?)?;
    module.add_function(wrap_pyfunction!(schemas_generate, module)?)?;
    Ok(())
}

#[pyfunction(name = "_schemas_optional_yaml_module")]
fn schemas_optional_yaml_module(py: Python<'_>) -> PyResult<Py<PyAny>> {
    match py.import("yaml") {
        Ok(module) => Ok(module.into_any().unbind()),
        Err(error) if error.is_instance_of::<PyModuleNotFoundError>(py) => Ok(py.None()),
        Err(error) => Err(error),
    }
}

#[pyfunction(name = "_schemas_openapi_render")]
fn schemas_openapi_render(
    py: Python<'_>,
    yaml: &Bound<'_, PyAny>,
    content: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    if yaml.is_none() {
        return Err(PyAssertionError::new_err(
            "`pyyaml` must be installed to use OpenAPIResponse.",
        ));
    }
    if !content.is_instance_of::<PyDict>() {
        return Err(PyAssertionError::new_err(
            "The schema passed to OpenAPIResponse should be a dictionary.",
        ));
    }

    let kwargs = PyDict::new(py);
    kwargs.set_item("default_flow_style", false)?;
    let rendered = yaml.getattr("dump")?.call((content,), Some(&kwargs))?;
    rendered
        .call_method1("encode", ("utf-8",))
        .map(Bound::unbind)
}

#[pyfunction(name = "_schemas_openapi_response_init")]
#[pyo3(signature = (yaml, content, status_code=200, headers=None, media_type=None))]
fn schemas_openapi_response_init(
    py: Python<'_>,
    yaml: &Bound<'_, PyAny>,
    content: &Bound<'_, PyAny>,
    status_code: u16,
    headers: Option<Py<PyAny>>,
    media_type: Option<String>,
) -> PyResult<Py<PyAny>> {
    let body = schemas_openapi_render(py, yaml, content)?;
    let media_type = media_type
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "application/vnd.oai.openapi".to_owned());
    let response_type = py.import("starlette_rs_py._core")?.getattr("Response")?;
    let kwargs = PyDict::new(py);
    kwargs.set_item("content", body)?;
    kwargs.set_item("status_code", status_code)?;
    kwargs.set_item("headers", headers)?;
    kwargs.set_item("media_type", media_type)?;
    response_type.call((), Some(&kwargs)).map(Bound::unbind)
}

#[pyfunction(name = "_schemas_base_get_schema")]
fn schemas_base_get_schema(
    _generator: &Bound<'_, PyAny>,
    _routes: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    Err(PyNotImplementedError::new_err(()))
}

#[pyfunction(name = "_schemas_generator_init")]
fn schemas_generator_init(
    generator: &Bound<'_, PyAny>,
    base_schema: &Bound<'_, PyAny>,
) -> PyResult<()> {
    generator.setattr("base_schema", base_schema)
}

#[pyfunction(name = "_schemas_get_endpoints")]
fn schemas_get_endpoints(
    py: Python<'_>,
    generator: &Bound<'_, PyAny>,
    routes: &Bound<'_, PyAny>,
    endpoint_info_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let endpoints = PyList::empty(py);
    let routing = py.import("starlette.routing")?;
    let mount_type = routing.getattr("Mount")?;
    let host_type = routing.getattr("Host")?;
    let route_type = routing.getattr("Route")?;
    let builtins = py.import("builtins")?;
    let getattr = builtins.getattr("getattr")?;
    let hasattr = builtins.getattr("hasattr")?;
    let inspect = py.import("inspect")?;

    for route_result in routes.try_iter()? {
        let route = route_result?;
        let is_mount = route.is_instance(&mount_type)?;
        let is_host = route.is_instance(&host_type)?;

        if is_mount || is_host {
            let nested_routes = route.getattr("routes")?;
            let nested_routes = if nested_routes.is_truthy()? {
                nested_routes
            } else {
                PyList::empty(py).into_any()
            };
            let prefix = if is_mount {
                let mount_path = route.getattr("path")?;
                generator.call_method1("_remove_converter", (&mount_path,))?
            } else {
                PyString::new(py, "").into_any()
            };
            let sub_endpoints = generator.call_method1("get_endpoints", (&nested_routes,))?;

            for sub_endpoint_result in sub_endpoints.try_iter()? {
                let sub_endpoint = sub_endpoint_result?;
                let sub_path = sub_endpoint.getattr("path")?;
                let path_parts = PyList::empty(py);
                path_parts.append(&prefix)?;
                path_parts.append(&sub_path)?;
                let path = PyString::new(py, "").call_method1("join", (path_parts,))?;
                let http_method = sub_endpoint.getattr("http_method")?;
                let func = sub_endpoint.getattr("func")?;
                endpoints.append(make_endpoint_info(
                    endpoint_info_type,
                    &path,
                    &http_method,
                    &func,
                )?)?;
            }
            continue;
        }

        if !route.is_instance(&route_type)? || !route.getattr("include_in_schema")?.is_truthy()? {
            continue;
        }

        let endpoint = route.getattr("endpoint")?;
        let is_function = inspect
            .getattr("isfunction")?
            .call1((&endpoint,))?
            .is_truthy()?;
        let is_method = inspect
            .getattr("ismethod")?
            .call1((&endpoint,))?
            .is_truthy()?;
        let path = generator.call_method1("_remove_converter", (route.getattr("path")?,))?;

        if is_function || is_method {
            let methods = route.getattr("methods")?;
            let methods = if methods.is_truthy()? {
                methods
            } else {
                let default_methods = PyList::empty(py);
                default_methods.append("GET")?;
                default_methods.into_any()
            };

            for method_result in methods.try_iter()? {
                let method = method_result?;
                if method.eq("HEAD")? {
                    continue;
                }
                let http_method = method.call_method0("lower")?;
                endpoints.append(make_endpoint_info(
                    endpoint_info_type,
                    &path,
                    &http_method,
                    &endpoint,
                )?)?;
            }
        } else {
            for method_name in ["get", "post", "put", "patch", "delete", "options"] {
                if !hasattr.call1((&endpoint, method_name))?.extract::<bool>()? {
                    continue;
                }
                let func = getattr.call1((&endpoint, method_name))?;
                let http_method = PyString::new(py, method_name);
                endpoints.append(make_endpoint_info(
                    endpoint_info_type,
                    &path,
                    &http_method,
                    &func,
                )?)?;
            }
        }
    }

    Ok(endpoints.into_any().unbind())
}

fn make_endpoint_info<'py>(
    endpoint_info_type: &Bound<'py, PyAny>,
    path: &Bound<'py, PyAny>,
    http_method: &Bound<'py, PyAny>,
    func: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyAny>> {
    let kwargs = PyDict::new(path.py());
    kwargs.set_item("path", path)?;
    kwargs.set_item("http_method", http_method)?;
    kwargs.set_item("func", func)?;
    endpoint_info_type.call((), Some(&kwargs))
}

#[pyfunction(name = "_schemas_remove_converter")]
fn schemas_remove_converter(py: Python<'_>, path: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    let path = path.extract::<String>()?;
    let characters = path.char_indices().collect::<Vec<_>>();
    let mut normalized = String::with_capacity(path.len());
    let mut last_copied = 0;
    let mut index = 0;

    while index < characters.len() {
        if characters[index].1 == ':' {
            let mut end = index + 1;
            while end < characters.len()
                && (characters[end].1 == '_' || characters[end].1.is_alphanumeric())
            {
                end += 1;
            }
            if end > index + 1 && end < characters.len() && characters[end].1 == '}' {
                let start_byte = characters[index].0;
                let close_byte = characters[end].0;
                normalized.push_str(&path[last_copied..start_byte]);
                normalized.push('}');
                last_copied = close_byte + 1;
                index = end + 1;
                continue;
            }
        }
        index += 1;
    }
    normalized.push_str(&path[last_copied..]);
    Ok(PyString::new(py, &normalized).into_any().unbind())
}

#[pyfunction(name = "_schemas_parse_docstring")]
fn schemas_parse_docstring(
    py: Python<'_>,
    yaml: &Bound<'_, PyAny>,
    func_or_method: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let docstring = func_or_method.getattr("__doc__")?;
    if !docstring.is_truthy()? {
        return Ok(PyDict::new(py).into_any().unbind());
    }
    if yaml.is_none() {
        return Err(PyAssertionError::new_err(
            "`pyyaml` must be installed to use parse_docstring.",
        ));
    }

    let docstring = docstring.call_method1("split", ("---",))?;
    let schema_document = docstring.get_item(-1)?;
    let parsed = yaml.getattr("safe_load")?.call1((schema_document,))?;
    if parsed.is_instance_of::<PyDict>() {
        Ok(parsed.unbind())
    } else {
        Ok(PyDict::new(py).into_any().unbind())
    }
}

#[pyfunction(name = "_schemas_openapi_response")]
fn schemas_openapi_response(
    generator: &Bound<'_, PyAny>,
    request: &Bound<'_, PyAny>,
    response_type: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let routes = request.getattr("app")?.getattr("routes")?;
    let kwargs = PyDict::new(request.py());
    kwargs.set_item("routes", routes)?;
    let schema = generator.call_method("get_schema", (), Some(&kwargs))?;
    response_type.call1((schema,)).map(Bound::unbind)
}

#[pyfunction(name = "_schemas_generate")]
fn schemas_generate(
    py: Python<'_>,
    generator: &Bound<'_, PyAny>,
    routes: &Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    let dict_type = py.import("builtins")?.getattr("dict")?;
    let schema = dict_type.call1((generator.getattr("base_schema")?,))?;
    let default_paths = PyDict::new(py);
    let paths = schema
        .getattr("setdefault")?
        .call1(("paths", default_paths))?;
    let endpoints = generator.call_method1("get_endpoints", (routes,))?;

    for endpoint_result in endpoints.try_iter()? {
        let endpoint = endpoint_result?;
        let func = endpoint.getattr("func")?;
        let parsed = generator.call_method1("parse_docstring", (&func,))?;
        if !parsed.is_truthy()? {
            continue;
        }

        let path = endpoint.getattr("path")?;
        if !paths.contains(&path)? {
            paths.set_item(&path, PyDict::new(py))?;
        }
        let path_operations = paths.get_item(&path)?;
        let http_method = endpoint.getattr("http_method")?;
        path_operations.set_item(http_method, parsed)?;
    }
    Ok(schema.unbind())
}
