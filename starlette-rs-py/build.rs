//! Configure the linker arguments required for a Python extension module.

fn main() {
    pyo3_build_config::add_extension_module_link_args();
}
