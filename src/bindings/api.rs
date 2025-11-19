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
