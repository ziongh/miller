// PyO3 Bindings Module
//
// This module provides Python bindings for Julie's Rust extractors.
// It wraps Julie's types (Symbol, Identifier, Relationship) in PyO3-compatible types.

mod api;
mod arrow_extraction;
mod batch_result;
mod extraction_results;
mod identifier;
mod relationship;
mod symbol;

// Re-export for lib.rs
pub use api::{
    detect_language, extract_file, extract_files_batch, extract_files_batch_with_io,
    hash_content, hash_contents_batch, supported_languages,
};
pub use arrow_extraction::{extract_files_to_arrow, PyArrowExtractionBatch};
pub use batch_result::PyBatchFileResult;
pub use extraction_results::PyExtractionResults;
pub use identifier::PyIdentifier;
pub use relationship::PyRelationship;
pub use symbol::PySymbol;
