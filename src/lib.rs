// Miller Core - Rust-powered tree-sitter parsing for Python
//
// This is a PyO3 extension module that wraps Julie's battle-tested extractors.
// Architecture: "Rust Sandwich" - Rust for parsing, Python for orchestration.

use pyo3::prelude::*;

// Miller-specific utilities
pub mod utils;

// PyO3 bindings layer (Miller-specific)
pub mod bindings;

/// Miller Core Python module
///
/// Provides tree-sitter-based symbol extraction for 31 programming languages.
#[pymodule]
fn miller_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;

    // Add Python functions
    m.add_function(wrap_pyfunction!(bindings::extract_file, m)?)?;
    m.add_function(wrap_pyfunction!(bindings::detect_language, m)?)?;
    m.add_function(wrap_pyfunction!(bindings::supported_languages, m)?)?;
    m.add_function(wrap_pyfunction!(bindings::extract_files_batch, m)?)?;
    m.add_function(wrap_pyfunction!(bindings::hash_content, m)?)?;
    m.add_function(wrap_pyfunction!(bindings::hash_contents_batch, m)?)?;

    // Add Python classes
    m.add_class::<bindings::PySymbol>()?;
    m.add_class::<bindings::PyIdentifier>()?;
    m.add_class::<bindings::PyRelationship>()?;
    m.add_class::<bindings::PyExtractionResults>()?;

    Ok(())
}
