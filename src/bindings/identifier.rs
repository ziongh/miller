// PyIdentifier - PyO3 wrapper for Julie's Identifier type
//
// Represents a usage reference (function call, variable reference, etc.)

use julie_extractors::Identifier;
use pyo3::prelude::*;

/// Python-accessible Identifier wrapper
///
/// Represents an identifier usage (call, variable reference, type usage, etc.)
#[pyclass(name = "Identifier")]
pub struct PyIdentifier {
    inner: Identifier,
}

impl PyIdentifier {
    pub fn from_identifier(identifier: Identifier) -> Self {
        PyIdentifier { inner: identifier }
    }
}

#[pymethods]
impl PyIdentifier {
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
        // Convert IdentifierKind enum to string
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

    #[getter]
    fn containing_symbol_id(&self) -> Option<String> {
        self.inner.containing_symbol_id.clone()
    }

    #[getter]
    fn target_symbol_id(&self) -> Option<String> {
        self.inner.target_symbol_id.clone()
    }

    #[getter]
    fn confidence(&self) -> f32 {
        self.inner.confidence
    }

    #[getter]
    fn code_context(&self) -> Option<String> {
        self.inner.code_context.clone()
    }

    fn __repr__(&self) -> String {
        format!(
            "Identifier(name='{}', kind='{}', file_path='{}', line={})",
            self.inner.name, self.inner.kind, self.inner.file_path, self.inner.start_line
        )
    }
}
