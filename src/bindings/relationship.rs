// PyRelationship - PyO3 wrapper for Julie's Relationship type
//
// Represents a relationship between two symbols (calls, extends, implements, etc.)

use crate::extractors::base::types::Relationship;
use pyo3::prelude::*;
use std::collections::HashMap;

/// Python-accessible Relationship wrapper
///
/// Represents a relationship between two code symbols
#[pyclass(name = "Relationship")]
pub struct PyRelationship {
    inner: Relationship,
}

impl PyRelationship {
    pub fn from_relationship(relationship: Relationship) -> Self {
        PyRelationship {
            inner: relationship,
        }
    }
}

#[pymethods]
impl PyRelationship {
    #[getter]
    fn id(&self) -> String {
        self.inner.id.clone()
    }

    #[getter]
    #[allow(clippy::wrong_self_convention)]
    fn from_symbol_id(&self) -> String {
        self.inner.from_symbol_id.clone()
    }

    #[getter]
    fn to_symbol_id(&self) -> String {
        self.inner.to_symbol_id.clone()
    }

    #[getter]
    fn kind(&self) -> String {
        // Convert RelationshipKind enum to string
        self.inner.kind.to_string()
    }

    #[getter]
    fn file_path(&self) -> String {
        self.inner.file_path.clone()
    }

    #[getter]
    fn line_number(&self) -> u32 {
        self.inner.line_number
    }

    #[getter]
    fn confidence(&self) -> f32 {
        self.inner.confidence
    }

    #[getter]
    fn metadata(&self) -> Option<HashMap<String, String>> {
        // Convert HashMap<String, serde_json::Value> to HashMap<String, String>
        self.inner
            .metadata
            .as_ref()
            .map(|m| m.iter().map(|(k, v)| (k.clone(), v.to_string())).collect())
    }

    fn __repr__(&self) -> String {
        format!(
            "Relationship(kind='{}', from='{}', to='{}', file_path='{}', line={})",
            self.inner.kind,
            self.inner.from_symbol_id,
            self.inner.to_symbol_id,
            self.inner.file_path,
            self.inner.line_number
        )
    }
}
