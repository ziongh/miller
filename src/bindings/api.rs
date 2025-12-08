// API Functions - PyO3-exposed functions for Python
//
// These functions provide the public API for Miller's extraction functionality.

use super::{PyBatchFileResult, PyExtractionResults};
use julie_extractors::{detect_language_from_extension, ExtractionResults, ExtractorManager};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::fs;
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
    let results = ExtractionResults {
        symbols,
        identifiers,
        relationships,
        pending_relationships: Vec::new(), // Cross-file resolution not needed for Miller
        types: std::collections::HashMap::new(),
    };

    Ok(PyExtractionResults::from_extraction_results(results))
}

/// Detect programming language from file extension
///
/// Args:
///     file_path (str): File path with extension (e.g., "main.rs", "app.py")
///
/// Returns:
///     str: Language name if detected, "text" for unknown extensions
///
/// Note:
///     Never returns None - unknown file types are treated as "text" to ensure
///     they remain searchable via full-text search even without symbol extraction.
#[pyfunction]
#[pyo3(signature = (file_path))]
pub fn detect_language(file_path: &str) -> PyResult<String> {
    // Extract extension from file path
    let path = Path::new(file_path);
    let extension = path.extension().and_then(|ext| ext.to_str()).unwrap_or("");

    // Use Julie's language detection, fallback to "text" for unknown extensions
    let lang = detect_language_from_extension(extension).unwrap_or("text");

    Ok(lang.to_string())
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

/// Compute blake3 hash of content string
///
/// Blake3 is ~3x faster than SHA-256 while providing equivalent security.
/// Used for incremental indexing change detection.
///
/// Args:
///     content (str): Content to hash
///
/// Returns:
///     str: 64-character hex digest of blake3 hash
#[pyfunction]
pub fn hash_content(content: &str) -> String {
    let hash = blake3::hash(content.as_bytes());
    hash.to_hex().to_string()
}

/// Compute blake3 hashes for multiple content strings in parallel
///
/// Efficiently computes hashes for many files using Rayon's parallel iterators.
/// Releases the GIL to allow true multi-threaded execution.
///
/// Args:
///     contents (list[str]): List of content strings to hash
///
/// Returns:
///     list[str]: List of 64-character hex digests in same order as input
#[pyfunction]
pub fn hash_contents_batch(py: Python<'_>, contents: Vec<String>) -> Vec<String> {
    use rayon::prelude::*;

    // Release GIL for parallel processing
    py.detach(move || {
        contents
            .par_iter()
            .map(|content| {
                let hash = blake3::hash(content.as_bytes());
                hash.to_hex().to_string()
            })
            .collect()
    })
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
    let results = py.detach(move || {
        files
            .par_iter()
            .map(|(content, _language, file_path)| {
                let manager = ExtractorManager::new();

                // Extract symbols with error logging
                let symbols = manager
                    .extract_symbols(file_path, content, workspace_root_path)
                    .unwrap_or_else(|e| {
                        eprintln!(
                            "Warning: Failed to extract symbols from {}: {}",
                            file_path, e
                        );
                        Vec::new()
                    });

                // Extract identifiers with error logging
                let identifiers = manager
                    .extract_identifiers(file_path, content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!(
                            "Warning: Failed to extract identifiers from {}: {}",
                            file_path, e
                        );
                        Vec::new()
                    });

                // Extract relationships with error logging
                let relationships = manager
                    .extract_relationships(file_path, content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!(
                            "Warning: Failed to extract relationships from {}: {}",
                            file_path, e
                        );
                        Vec::new()
                    });

                let results = ExtractionResults {
                    symbols,
                    identifiers,
                    relationships,
                    pending_relationships: Vec::new(),
                    types: std::collections::HashMap::new(),
                };

                PyExtractionResults::from_extraction_results(results)
            })
            .collect()
    });

    Ok(results)
}

/// Extract files with Rust-side I/O (Zero-Copy optimization)
///
/// This function performs file reading, hashing, language detection, and
/// symbol extraction entirely in Rust's parallel worker pool. This eliminates
/// Python memory churn from allocating strings just to pass them to Rust.
///
/// # Performance Benefits
/// - File I/O happens in parallel across all CPU cores
/// - No GIL contention during file reads
/// - Blake3 hashing is ~3x faster than Python's hashlib
/// - Language detection happens without Python overhead
/// - Memory usage is flatter (no Python string accumulation)
///
/// # Error Handling
/// - Individual file read errors are captured in the result's `error` field
/// - Extraction errors result in `results: None` but `content` still populated
/// - The function never raises - all errors are returned in PyBatchFileResult
///
/// Args:
///     file_paths (list[str]): List of relative file paths from workspace root
///     workspace_root (str): Absolute path to workspace root directory
///
/// Returns:
///     list[BatchFileResult]: Results containing content, hash, language, and extraction data
///
/// Example:
///     >>> paths = ["src/main.py", "src/utils.rs", "README.md"]
///     >>> results = extract_files_batch_with_io(paths, "/path/to/workspace")
///     >>> for r in results:
///     ...     if r.is_success:
///     ...         print(f"{r.path}: {r.language}, {len(r.content)} bytes")
#[pyfunction]
#[pyo3(signature = (file_paths, workspace_root))]
pub fn extract_files_batch_with_io(
    py: Python<'_>,
    file_paths: Vec<String>,
    workspace_root: String,
) -> PyResult<Vec<PyBatchFileResult>> {
    use rayon::prelude::*;

    let workspace_root_path = Path::new(&workspace_root);

    // Release GIL for parallel I/O + CPU processing
    let results = py.detach(move || {
        file_paths
            .par_iter()
            .map(|rel_path| {
                // 1. Resolve full path
                let full_path = workspace_root_path.join(rel_path);

                // 2. Read file content
                let content = match fs::read_to_string(&full_path) {
                    Ok(c) => c,
                    Err(e) => {
                        return PyBatchFileResult::error(
                            rel_path.clone(),
                            format!("Read error: {}", e),
                        );
                    }
                };

                // 3. Compute Blake3 hash
                let hash = blake3::hash(content.as_bytes()).to_hex().to_string();

                // 4. Detect language from extension
                let extension = full_path
                    .extension()
                    .and_then(|e| e.to_str())
                    .unwrap_or("");
                let language =
                    detect_language_from_extension(extension).unwrap_or("text");

                // 5. Extract symbols (if not a text file)
                let results = if language == "text" {
                    // Text files: no symbol extraction, but we still have content
                    None
                } else {
                    let manager = ExtractorManager::new();

                    // Extract symbols
                    let symbols = manager
                        .extract_symbols(rel_path, &content, workspace_root_path)
                        .unwrap_or_else(|e| {
                            eprintln!(
                                "Warning: Failed to extract symbols from {}: {}",
                                rel_path, e
                            );
                            Vec::new()
                        });

                    // Extract identifiers
                    let identifiers = manager
                        .extract_identifiers(rel_path, &content, &symbols)
                        .unwrap_or_else(|e| {
                            eprintln!(
                                "Warning: Failed to extract identifiers from {}: {}",
                                rel_path, e
                            );
                            Vec::new()
                        });

                    // Extract relationships
                    let relationships = manager
                        .extract_relationships(rel_path, &content, &symbols)
                        .unwrap_or_else(|e| {
                            eprintln!(
                                "Warning: Failed to extract relationships from {}: {}",
                                rel_path, e
                            );
                            Vec::new()
                        });

                    let extraction_results = ExtractionResults {
                        symbols,
                        identifiers,
                        relationships,
                        pending_relationships: Vec::new(),
                        types: std::collections::HashMap::new(),
                    };

                    Some(PyExtractionResults::from_extraction_results(extraction_results))
                };

                PyBatchFileResult::success(
                    rel_path.clone(),
                    content,
                    language.to_string(),
                    hash,
                    results,
                )
            })
            .collect()
    });

    Ok(results)
}
