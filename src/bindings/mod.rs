// PyO3 Bindings Module
//
// This module provides Python bindings for Julie's Rust extractors.
// It wraps Julie's types (Symbol, Identifier, Relationship) in PyO3-compatible types.

mod symbol;
mod identifier;
mod relationship;
mod extraction_results;
mod api;

// Re-export for lib.rs
pub use symbol::PySymbol;
pub use identifier::PyIdentifier;
pub use relationship::PyRelationship;
pub use extraction_results::PyExtractionResults;
pub use api::{extract_file, detect_language, supported_languages};
