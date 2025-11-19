// PySymbol - PyO3 wrapper for Julie's Symbol type
//
// This wrapper allows Python code to access Symbol fields via zero-copy borrowing.

use crate::extractors::base::types::{Symbol, SymbolKind, Visibility};
use pyo3::prelude::*;
use std::collections::HashMap;

/// Python-accessible Symbol wrapper
///
/// Represents a code symbol (function, class, variable, etc.) extracted from source code.
/// All fields are read-only from Python.
#[pyclass(name = "Symbol")]
pub struct PySymbol {
    // Store the inner Symbol
    inner: Symbol,
}

impl PySymbol {
    /// Create a new PySymbol from Julie's Symbol
    pub fn from_symbol(symbol: Symbol) -> Self {
        PySymbol { inner: symbol }
    }
}

#[pymethods]
impl PySymbol {
    // Required fields (always present)

    #[getter]
    fn id(&self) -> String {
        self.inner.id.clone()
    }

    #[getter]
    fn name(&self) -> String {
        self.inner.name.clone()
    }

    #[getter]
    fn kind(&self) -> String {
        // Convert SymbolKind enum to string
        self.inner.kind.to_string()
    }

    #[getter]
    fn language(&self) -> String {
        self.inner.language.clone()
    }

    #[getter]
    fn file_path(&self) -> String {
        self.inner.file_path.clone()
    }

    #[getter]
    fn start_line(&self) -> u32 {
        self.inner.start_line
    }

    #[getter]
    fn start_column(&self) -> u32 {
        self.inner.start_column
    }

    #[getter]
    fn end_line(&self) -> u32 {
        self.inner.end_line
    }

    #[getter]
    fn end_column(&self) -> u32 {
        self.inner.end_column
    }

    #[getter]
    fn start_byte(&self) -> u32 {
        self.inner.start_byte
    }

    #[getter]
    fn end_byte(&self) -> u32 {
        self.inner.end_byte
    }

    // Optional fields (can be None)

    #[getter]
    fn signature(&self) -> Option<String> {
        self.inner.signature.clone()
    }

    #[getter]
    fn doc_comment(&self) -> Option<String> {
        self.inner.doc_comment.clone()
    }

    #[getter]
    fn visibility(&self) -> Option<String> {
        self.inner.visibility.as_ref().map(|v| v.to_string())
    }

    #[getter]
    fn parent_id(&self) -> Option<String> {
        self.inner.parent_id.clone()
    }

    #[getter]
    fn metadata(&self) -> Option<HashMap<String, String>> {
        // Convert HashMap<String, serde_json::Value> to HashMap<String, String>
        self.inner
            .metadata
            .as_ref()
            .map(|m| m.iter().map(|(k, v)| (k.clone(), v.to_string())).collect())
    }

    #[getter]
    fn semantic_group(&self) -> Option<String> {
        self.inner.semantic_group.clone()
    }

    #[getter]
    fn confidence(&self) -> Option<f32> {
        self.inner.confidence
    }

    #[getter]
    fn code_context(&self) -> Option<String> {
        self.inner.code_context.clone()
    }

    #[getter]
    fn content_type(&self) -> Option<String> {
        self.inner.content_type.clone()
    }

    // Python repr
    fn __repr__(&self) -> String {
        format!(
            "Symbol(name='{}', kind='{}', file_path='{}', line={})",
            self.inner.name,
            self.inner.kind.to_string(),
            self.inner.file_path,
            self.inner.start_line
        )
    }
}
