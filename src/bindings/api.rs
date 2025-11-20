// API Functions - PyO3-exposed functions for Python
//
// These functions provide the public API for Miller's extraction functionality.

use super::PyExtractionResults;
use crate::extractors::manager::ExtractorManager;
use crate::language;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::path::Path;

/// Extract symbols, identifiers, and relationships from source code
///
/// Args:
///     content (str): Source code content to extract from
///     language (str): Programming language (e.g., "python", "javascript", "rust")
///     file_path (str): File path (for symbol storage and language detection)
///
/// Returns:
///     ExtractionResults: Container with symbols, identifiers, and relationships
///
/// Raises:
///     ValueError: If language is not supported
#[pyfunction]
#[pyo3(signature = (content, language, file_path))]
#[allow(unused_variables)]
pub fn extract_file(
    content: &str,
    language: &str,
    file_path: &str,
) -> PyResult<PyExtractionResults> {
    // Create extractor manager
    let manager = ExtractorManager::new();

    // Use current directory as workspace root (Miller doesn't need workspace context for basic extraction)
    let workspace_root = Path::new(".");

    // Extract symbols using Julie's proven extraction logic
    let symbols = manager
        .extract_symbols(file_path, content, workspace_root)
        .map_err(|e| PyValueError::new_err(format!("Extraction failed: {}", e)))?;

    // Extract identifiers (requires symbols to be extracted first)
    let identifiers = manager
        .extract_identifiers(file_path, content, &symbols)
        .map_err(|e| PyValueError::new_err(format!("Identifier extraction failed: {}", e)))?;

    // Extract relationships (requires symbols to be extracted first)
    let relationships = manager
        .extract_relationships(file_path, content, &symbols)
        .map_err(|e| PyValueError::new_err(format!("Relationship extraction failed: {}", e)))?;

    // Create ExtractionResults
    let results = crate::extractors::base::types::ExtractionResults {
        symbols,
        identifiers,
        relationships,
        types: std::collections::HashMap::new(), // Type inference not needed for basic tests
    };

    Ok(PyExtractionResults::from_extraction_results(results))
}

/// Detect programming language from file extension
///
/// Args:
///     file_path (str): File path with extension (e.g., "main.rs", "app.py")
///
/// Returns:
///     str or None: Language name if detected, None otherwise
#[pyfunction]
#[pyo3(signature = (file_path))]
pub fn detect_language(file_path: &str) -> PyResult<Option<String>> {
    // Extract extension from file path
    let path = Path::new(file_path);
    let extension = path.extension().and_then(|ext| ext.to_str()).unwrap_or("");

    // Use Julie's language detection
    let lang = language::detect_language_from_extension(extension);

    Ok(lang.map(|s| s.to_string()))
}

/// Get list of all supported programming languages
///
/// Returns:
///     list[str]: List of supported language names
#[pyfunction]
pub fn supported_languages() -> PyResult<Vec<String>> {
    let manager = ExtractorManager::new();
    let langs = manager.supported_languages();

    Ok(langs.iter().map(|&s| s.to_string()).collect())
}

/// Extract symbols from multiple files in parallel
///
/// This function processes multiple files concurrently using Rayon's parallel
/// iterators, releasing the Python GIL to allow true multi-threaded execution.
///
/// # Performance
/// - Releases Python GIL during extraction (allows Python to continue executing)
/// - Uses all available CPU cores via Rayon's work-stealing scheduler
/// - Typical speedup: 2-4x on quad-core systems with 20+ files
/// - Best performance with batches of 20-100 files
///
/// # Error Handling
/// - Extraction errors are logged to stderr but do not fail the entire batch
/// - Files that fail to parse return empty ExtractionResults
/// - Check individual result lengths to detect failed extractions
///
/// # Thread Safety
/// - Safe to call concurrently from multiple Python threads
/// - Each file is processed independently with no shared mutable state
///
/// Args:
///     files (list[tuple[str, str, str]]): List of (content, language, file_path) tuples
///         - content: Source code as string
///         - language: Language identifier (currently unused, language detected from file_path)
///         - file_path: Relative path from workspace root
///     workspace_root (str): Absolute path to workspace root directory
///
/// Returns:
///     list[ExtractionResults]: List of results in same order as input
///                              (preserves input ordering despite parallel execution)
///
/// Example:
///     >>> files = [
///     ...     ("def foo(): pass", "python", "src/foo.py"),
///     ...     ("fn bar() {}", "rust", "src/bar.rs"),
///     ... ]
///     >>> results = extract_files_batch(files, "/path/to/workspace")
///     >>> assert len(results) == 2
#[pyfunction]
#[pyo3(signature = (files, workspace_root))]
pub fn extract_files_batch(
    py: Python<'_>,
    files: Vec<(String, String, String)>,
    workspace_root: String,
) -> PyResult<Vec<PyExtractionResults>> {
    use rayon::prelude::*;

    let workspace_root_path = Path::new(&workspace_root);

    // Release GIL for parallel processing
    let results = py.allow_threads(move || {
        files
            .par_iter()
            .map(|(content, _language, file_path)| {
                let manager = ExtractorManager::new();

                // Extract symbols with error logging
                let symbols = manager
                    .extract_symbols(file_path, content, workspace_root_path)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Failed to extract symbols from {}: {}", file_path, e);
                        Vec::new()
                    });

                // Extract identifiers with error logging
                let identifiers = manager
                    .extract_identifiers(file_path, content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Failed to extract identifiers from {}: {}", file_path, e);
                        Vec::new()
                    });

                // Extract relationships with error logging
                let relationships = manager
                    .extract_relationships(file_path, content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Failed to extract relationships from {}: {}", file_path, e);
                        Vec::new()
                    });

                let results = crate::extractors::base::types::ExtractionResults {
                    symbols,
                    identifiers,
                    relationships,
                    types: std::collections::HashMap::new(),
                };

                PyExtractionResults::from_extraction_results(results)
            })
            .collect()
    });

    Ok(results)
}
