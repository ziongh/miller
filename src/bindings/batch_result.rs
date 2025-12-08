// PyBatchFileResult - Container for file I/O + extraction results
//
// This struct returns everything Python needs from a single file:
// - File content (read by Rust)
// - Content hash (computed by Rust)
// - Language detection (done by Rust)
// - Extraction results (symbols, identifiers, relationships)
// - Error information (if any step failed)
//
// This enables "Zero-Copy" optimization where file I/O happens in
// Rust's parallel worker pool instead of Python's single-threaded event loop.

use super::PyExtractionResults;
use pyo3::prelude::*;

/// Result of processing a single file in batch extraction.
///
/// Contains all data Python needs to populate the database:
/// - path: Relative file path (same as input)
/// - content: File content (None if read failed)
/// - language: Detected language (e.g., "python", "rust", "text")
/// - hash: Blake3 hash of content (empty if read failed)
/// - results: Extraction results (None for text files or on error)
/// - error: Error message if any step failed
#[pyclass(name = "BatchFileResult")]
pub struct PyBatchFileResult {
    #[pyo3(get)]
    pub path: String,

    #[pyo3(get)]
    pub content: Option<String>,

    #[pyo3(get)]
    pub language: String,

    #[pyo3(get)]
    pub hash: String,

    #[pyo3(get)]
    pub size: usize,

    // Note: No #[pyo3(get)] because PyExtractionResults doesn't implement Clone
    // We provide a manual getter method instead
    pub results: Option<PyExtractionResults>,

    #[pyo3(get)]
    pub error: Option<String>,
}

impl PyBatchFileResult {
    /// Create a successful result with extraction data
    pub fn success(
        path: String,
        content: String,
        language: String,
        hash: String,
        results: Option<PyExtractionResults>,
    ) -> Self {
        let size = content.len();
        PyBatchFileResult {
            path,
            content: Some(content),
            language,
            hash,
            size,
            results,
            error: None,
        }
    }

    /// Create a failed result with error message
    pub fn error(path: String, error: String) -> Self {
        PyBatchFileResult {
            path,
            content: None,
            language: "unknown".to_string(),
            hash: String::new(),
            size: 0,
            results: None,
            error: Some(error),
        }
    }
}

#[pymethods]
impl PyBatchFileResult {
    /// Check if this result represents a successful extraction
    #[getter]
    fn is_success(&self) -> bool {
        self.error.is_none() && self.content.is_some()
    }

    /// Check if this file has extractable symbols (not a text file)
    #[getter]
    fn has_symbols(&self) -> bool {
        self.results.is_some()
    }

    /// Get extraction results (None for text files or on error)
    ///
    /// Note: This takes ownership of the results field. Calling this
    /// multiple times will return None after the first call.
    #[getter]
    fn results(&mut self) -> Option<PyExtractionResults> {
        self.results.take()
    }

    fn __repr__(&self) -> String {
        if let Some(ref err) = self.error {
            format!("BatchFileResult(path={:?}, error={:?})", self.path, err)
        } else {
            let has_results = self.results.is_some();
            format!(
                "BatchFileResult(path={:?}, lang={:?}, hash={:?}, has_results={})",
                self.path,
                self.language,
                &self.hash[..8.min(self.hash.len())],
                has_results
            )
        }
    }
}
