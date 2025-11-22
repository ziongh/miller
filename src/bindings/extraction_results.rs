// PyExtractionResults - PyO3 wrapper for Julie's ExtractionResults
//
// Container for all extracted symbols, identifiers, and relationships

use super::{PyIdentifier, PyRelationship, PySymbol};
use julie_extractors::ExtractionResults;
use pyo3::prelude::*;

/// Python-accessible ExtractionResults wrapper
///
/// Contains all symbols, identifiers, and relationships extracted from a file
#[pyclass(name = "ExtractionResults")]
pub struct PyExtractionResults {
    inner: ExtractionResults,
}

impl PyExtractionResults {
    pub fn from_extraction_results(results: ExtractionResults) -> Self {
        PyExtractionResults { inner: results }
    }
}

#[pymethods]
impl PyExtractionResults {
    #[getter]
    fn symbols(&self) -> Vec<PySymbol> {
        self.inner
            .symbols
            .iter()
            .map(|s| PySymbol::from_symbol(s.clone()))
            .collect()
    }

    #[getter]
    fn identifiers(&self) -> Vec<PyIdentifier> {
        self.inner
            .identifiers
            .iter()
            .map(|i| PyIdentifier::from_identifier(i.clone()))
            .collect()
    }

    #[getter]
    fn relationships(&self) -> Vec<PyRelationship> {
        self.inner
            .relationships
            .iter()
            .map(|r| PyRelationship::from_relationship(r.clone()))
            .collect()
    }

    fn __repr__(&self) -> String {
        format!(
            "ExtractionResults(symbols={}, identifiers={}, relationships={})",
            self.inner.symbols.len(),
            self.inner.identifiers.len(),
            self.inner.relationships.len()
        )
    }
}
