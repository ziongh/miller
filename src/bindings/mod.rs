// PyO3 Bindings Module
//
// This module provides Python bindings for Julie's Rust extractors.
// It wraps Julie's types (Symbol, Identifier, Relationship) in PyO3-compatible types.

mod api;
mod extraction_results;
mod identifier;
mod relationship;
mod symbol;

// Re-export for lib.rs
pub use api::{detect_language, extract_file, supported_languages};
pub use extraction_results::PyExtractionResults;
pub use identifier::PyIdentifier;
pub use relationship::PyRelationship;
pub use symbol::PySymbol;
