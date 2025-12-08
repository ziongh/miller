// Arrow-based extraction for zero-copy Python data transfer
//
// This module provides Arrow RecordBatch output instead of individual PyO3 objects,
// eliminating the GC pressure from creating millions of Python string objects.
//
// Key insight: Each field access on PySymbol/PyIdentifier triggers a .clone() in Rust,
// creating a new Python string. For 1MM LOC, this means ~75 million allocations.
// By building Arrow arrays directly, we create only a handful of large allocations.

use arrow_array::builder::{
    Float32Builder, StringBuilder, UInt32Builder,
};
use arrow_array::RecordBatch;
use arrow_schema::{DataType, Field, Schema};
use julie_extractors::{detect_language_from_extension, ExtractorManager};
use pyo3::prelude::*;
use pyo3_arrow::PyRecordBatch;
use rayon::prelude::*;
use std::fs;
use std::path::Path;
use std::sync::Arc;

/// Schema for symbols table - matches VectorStore.SCHEMA
fn symbols_schema() -> Schema {
    Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("kind", DataType::Utf8, false),
        Field::new("language", DataType::Utf8, false),
        Field::new("file_path", DataType::Utf8, false),
        Field::new("start_line", DataType::UInt32, false),
        Field::new("end_line", DataType::UInt32, false),
        Field::new("signature", DataType::Utf8, true),
        Field::new("doc_comment", DataType::Utf8, true),
        Field::new("parent_id", DataType::Utf8, true),
        Field::new("code_context", DataType::Utf8, true),
        // code_pattern is built from signature + name + kind for FTS
        Field::new("code_pattern", DataType::Utf8, false),
    ])
}

/// Schema for identifiers table
fn identifiers_schema() -> Schema {
    Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("name", DataType::Utf8, false),
        Field::new("kind", DataType::Utf8, false),
        Field::new("language", DataType::Utf8, false),
        Field::new("file_path", DataType::Utf8, false),
        Field::new("start_line", DataType::UInt32, false),
        Field::new("start_column", DataType::UInt32, false),
        Field::new("end_line", DataType::UInt32, false),
        Field::new("end_column", DataType::UInt32, false),
        Field::new("start_byte", DataType::UInt32, false),
        Field::new("end_byte", DataType::UInt32, false),
        Field::new("containing_symbol_id", DataType::Utf8, true),
        Field::new("target_symbol_id", DataType::Utf8, true),
        Field::new("confidence", DataType::Float32, false),
        Field::new("code_context", DataType::Utf8, true),
    ])
}

/// Schema for relationships table
fn relationships_schema() -> Schema {
    Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("from_symbol_id", DataType::Utf8, false),
        Field::new("to_symbol_id", DataType::Utf8, false),
        Field::new("kind", DataType::Utf8, false),
        Field::new("file_path", DataType::Utf8, false),
        Field::new("line_number", DataType::UInt32, false),
        Field::new("confidence", DataType::Float32, false),
    ])
}

/// Schema for file metadata
fn files_schema() -> Schema {
    Schema::new(vec![
        Field::new("path", DataType::Utf8, false),
        Field::new("language", DataType::Utf8, false),
        Field::new("content", DataType::Utf8, false),
        Field::new("hash", DataType::Utf8, false),
        Field::new("size", DataType::UInt32, false),
    ])
}

/// Result from extract_files_to_arrow containing all extracted data as Arrow batches
#[pyclass(name = "ArrowExtractionBatch")]
pub struct PyArrowExtractionBatch {
    /// Symbols as Arrow RecordBatch
    #[pyo3(get)]
    pub symbols: Py<PyAny>,
    /// Identifiers as Arrow RecordBatch
    #[pyo3(get)]
    pub identifiers: Py<PyAny>,
    /// Relationships as Arrow RecordBatch
    #[pyo3(get)]
    pub relationships: Py<PyAny>,
    /// File metadata as Arrow RecordBatch
    #[pyo3(get)]
    pub files: Py<PyAny>,
    /// Number of files successfully processed
    #[pyo3(get)]
    pub files_processed: usize,
    /// Number of files that failed
    #[pyo3(get)]
    pub files_failed: usize,
    /// Error messages from failed files
    #[pyo3(get)]
    pub errors: Vec<String>,
}

/// Internal structure for collecting extraction results
struct CollectedResults {
    symbols: Vec<julie_extractors::Symbol>,
    identifiers: Vec<julie_extractors::Identifier>,
    relationships: Vec<julie_extractors::Relationship>,
    files: Vec<(String, String, String, String, usize)>, // (path, language, content, hash, size)
    errors: Vec<String>,
}

impl CollectedResults {
    fn new() -> Self {
        Self {
            symbols: Vec::new(),
            identifiers: Vec::new(),
            relationships: Vec::new(),
            files: Vec::new(),
            errors: Vec::new(),
        }
    }

    fn merge(&mut self, other: CollectedResults) {
        self.symbols.extend(other.symbols);
        self.identifiers.extend(other.identifiers);
        self.relationships.extend(other.relationships);
        self.files.extend(other.files);
        self.errors.extend(other.errors);
    }
}

/// Build symbols RecordBatch from collected symbols
fn build_symbols_batch(symbols: &[julie_extractors::Symbol]) -> anyhow::Result<RecordBatch> {
    let mut id_builder = StringBuilder::new();
    let mut name_builder = StringBuilder::new();
    let mut kind_builder = StringBuilder::new();
    let mut language_builder = StringBuilder::new();
    let mut file_path_builder = StringBuilder::new();
    let mut start_line_builder = UInt32Builder::new();
    let mut end_line_builder = UInt32Builder::new();
    let mut signature_builder = StringBuilder::new();
    let mut doc_comment_builder = StringBuilder::new();
    let mut parent_id_builder = StringBuilder::new();
    let mut code_context_builder = StringBuilder::new();
    let mut code_pattern_builder = StringBuilder::new();

    for sym in symbols {
        id_builder.append_value(&sym.id);
        name_builder.append_value(&sym.name);
        kind_builder.append_value(sym.kind.to_string());
        language_builder.append_value(&sym.language);
        file_path_builder.append_value(&sym.file_path);
        start_line_builder.append_value(sym.start_line);
        end_line_builder.append_value(sym.end_line);

        // Handle optional fields
        match &sym.signature {
            Some(s) => signature_builder.append_value(s),
            None => signature_builder.append_null(),
        }
        match &sym.doc_comment {
            Some(s) => doc_comment_builder.append_value(s),
            None => doc_comment_builder.append_null(),
        }
        match &sym.parent_id {
            Some(s) => parent_id_builder.append_value(s),
            None => parent_id_builder.append_null(),
        }
        match &sym.code_context {
            Some(s) => code_context_builder.append_value(s),
            None => code_context_builder.append_null(),
        }

        // Build code_pattern for FTS (signature + name + kind)
        let kind_str = sym.kind.to_string();
        let mut pattern_parts: Vec<&str> = Vec::new();
        if let Some(sig) = &sym.signature {
            pattern_parts.push(sig.as_str());
        }
        pattern_parts.push(&sym.name);
        pattern_parts.push(&kind_str);
        code_pattern_builder.append_value(pattern_parts.join(" "));
    }

    let schema = Arc::new(symbols_schema());
    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(id_builder.finish()),
            Arc::new(name_builder.finish()),
            Arc::new(kind_builder.finish()),
            Arc::new(language_builder.finish()),
            Arc::new(file_path_builder.finish()),
            Arc::new(start_line_builder.finish()),
            Arc::new(end_line_builder.finish()),
            Arc::new(signature_builder.finish()),
            Arc::new(doc_comment_builder.finish()),
            Arc::new(parent_id_builder.finish()),
            Arc::new(code_context_builder.finish()),
            Arc::new(code_pattern_builder.finish()),
        ],
    )?;

    Ok(batch)
}

/// Build identifiers RecordBatch from collected identifiers
fn build_identifiers_batch(identifiers: &[julie_extractors::Identifier]) -> anyhow::Result<RecordBatch> {
    let mut id_builder = StringBuilder::new();
    let mut name_builder = StringBuilder::new();
    let mut kind_builder = StringBuilder::new();
    let mut language_builder = StringBuilder::new();
    let mut file_path_builder = StringBuilder::new();
    let mut start_line_builder = UInt32Builder::new();
    let mut start_column_builder = UInt32Builder::new();
    let mut end_line_builder = UInt32Builder::new();
    let mut end_column_builder = UInt32Builder::new();
    let mut start_byte_builder = UInt32Builder::new();
    let mut end_byte_builder = UInt32Builder::new();
    let mut containing_symbol_id_builder = StringBuilder::new();
    let mut target_symbol_id_builder = StringBuilder::new();
    let mut confidence_builder = Float32Builder::new();
    let mut code_context_builder = StringBuilder::new();

    for ident in identifiers {
        id_builder.append_value(&ident.id);
        name_builder.append_value(&ident.name);
        kind_builder.append_value(ident.kind.to_string());
        language_builder.append_value(&ident.language);
        file_path_builder.append_value(&ident.file_path);
        start_line_builder.append_value(ident.start_line);
        start_column_builder.append_value(ident.start_column);
        end_line_builder.append_value(ident.end_line);
        end_column_builder.append_value(ident.end_column);
        start_byte_builder.append_value(ident.start_byte);
        end_byte_builder.append_value(ident.end_byte);

        match &ident.containing_symbol_id {
            Some(s) => containing_symbol_id_builder.append_value(s),
            None => containing_symbol_id_builder.append_null(),
        }
        match &ident.target_symbol_id {
            Some(s) => target_symbol_id_builder.append_value(s),
            None => target_symbol_id_builder.append_null(),
        }

        confidence_builder.append_value(ident.confidence);

        match &ident.code_context {
            Some(s) => code_context_builder.append_value(s),
            None => code_context_builder.append_null(),
        }
    }

    let schema = Arc::new(identifiers_schema());
    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(id_builder.finish()),
            Arc::new(name_builder.finish()),
            Arc::new(kind_builder.finish()),
            Arc::new(language_builder.finish()),
            Arc::new(file_path_builder.finish()),
            Arc::new(start_line_builder.finish()),
            Arc::new(start_column_builder.finish()),
            Arc::new(end_line_builder.finish()),
            Arc::new(end_column_builder.finish()),
            Arc::new(start_byte_builder.finish()),
            Arc::new(end_byte_builder.finish()),
            Arc::new(containing_symbol_id_builder.finish()),
            Arc::new(target_symbol_id_builder.finish()),
            Arc::new(confidence_builder.finish()),
            Arc::new(code_context_builder.finish()),
        ],
    )?;

    Ok(batch)
}

/// Build relationships RecordBatch from collected relationships
fn build_relationships_batch(relationships: &[julie_extractors::Relationship]) -> anyhow::Result<RecordBatch> {
    let mut id_builder = StringBuilder::new();
    let mut from_symbol_id_builder = StringBuilder::new();
    let mut to_symbol_id_builder = StringBuilder::new();
    let mut kind_builder = StringBuilder::new();
    let mut file_path_builder = StringBuilder::new();
    let mut line_number_builder = UInt32Builder::new();
    let mut confidence_builder = Float32Builder::new();

    for rel in relationships {
        id_builder.append_value(&rel.id);
        from_symbol_id_builder.append_value(&rel.from_symbol_id);
        to_symbol_id_builder.append_value(&rel.to_symbol_id);
        kind_builder.append_value(rel.kind.to_string());
        file_path_builder.append_value(&rel.file_path);
        line_number_builder.append_value(rel.line_number);
        confidence_builder.append_value(rel.confidence);
    }

    let schema = Arc::new(relationships_schema());
    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(id_builder.finish()),
            Arc::new(from_symbol_id_builder.finish()),
            Arc::new(to_symbol_id_builder.finish()),
            Arc::new(kind_builder.finish()),
            Arc::new(file_path_builder.finish()),
            Arc::new(line_number_builder.finish()),
            Arc::new(confidence_builder.finish()),
        ],
    )?;

    Ok(batch)
}

/// Build files RecordBatch from collected file data
fn build_files_batch(files: &[(String, String, String, String, usize)]) -> anyhow::Result<RecordBatch> {
    let mut path_builder = StringBuilder::new();
    let mut language_builder = StringBuilder::new();
    let mut content_builder = StringBuilder::new();
    let mut hash_builder = StringBuilder::new();
    let mut size_builder = UInt32Builder::new();

    for (path, language, content, hash, size) in files {
        path_builder.append_value(path);
        language_builder.append_value(language);
        content_builder.append_value(content);
        hash_builder.append_value(hash);
        size_builder.append_value(*size as u32);
    }

    let schema = Arc::new(files_schema());
    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(path_builder.finish()),
            Arc::new(language_builder.finish()),
            Arc::new(content_builder.finish()),
            Arc::new(hash_builder.finish()),
            Arc::new(size_builder.finish()),
        ],
    )?;

    Ok(batch)
}

/// Extract files to Arrow RecordBatches (zero-copy Python data transfer)
///
/// This function performs file reading, hashing, language detection, and
/// symbol extraction entirely in Rust, returning Arrow RecordBatches
/// that can be passed directly to LanceDB and SQLite without creating
/// millions of Python string objects.
///
/// # Performance Benefits
/// - Eliminates ~75 million Python object allocations for 1MM LOC
/// - Arrow RecordBatches use zero-copy FFI to Python
/// - Columnar format is cache-friendly for batch operations
/// - No GC pressure from scattered small allocations
///
/// Args:
///     file_paths (list[str]): List of relative file paths from workspace root
///     workspace_root (str): Absolute path to workspace root directory
///
/// Returns:
///     ArrowExtractionBatch: Container with symbols, identifiers, relationships,
///                           and file metadata as Arrow RecordBatches
#[pyfunction]
#[pyo3(signature = (file_paths, workspace_root))]
pub fn extract_files_to_arrow(
    py: Python<'_>,
    file_paths: Vec<String>,
    workspace_root: String,
) -> PyResult<PyArrowExtractionBatch> {
    let workspace_root_path = Path::new(&workspace_root);

    // Parallel extraction with GIL released
    let collected = py.allow_threads(|| {
        // Process files in parallel
        let per_file_results: Vec<CollectedResults> = file_paths
            .par_iter()
            .map(|rel_path| {
                let mut result = CollectedResults::new();
                let full_path = workspace_root_path.join(rel_path);

                // Read file
                let content = match fs::read_to_string(&full_path) {
                    Ok(c) => c,
                    Err(e) => {
                        result.errors.push(format!("{}: {}", rel_path, e));
                        return result;
                    }
                };

                // Compute hash
                let hash = blake3::hash(content.as_bytes()).to_hex().to_string();
                let size = content.len();

                // Detect language
                let extension = full_path
                    .extension()
                    .and_then(|e| e.to_str())
                    .unwrap_or("");
                let language = detect_language_from_extension(extension).unwrap_or("text");

                // Store file metadata
                result.files.push((
                    rel_path.clone(),
                    language.to_string(),
                    content.clone(),
                    hash,
                    size,
                ));

                // Skip extraction for text files
                if language == "text" {
                    return result;
                }

                // Extract symbols
                let manager = ExtractorManager::new();
                let symbols = manager
                    .extract_symbols(rel_path, &content, workspace_root_path)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Symbol extraction failed for {}: {}", rel_path, e);
                        Vec::new()
                    });

                // Extract identifiers
                let identifiers = manager
                    .extract_identifiers(rel_path, &content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Identifier extraction failed for {}: {}", rel_path, e);
                        Vec::new()
                    });

                // Extract relationships
                let relationships = manager
                    .extract_relationships(rel_path, &content, &symbols)
                    .unwrap_or_else(|e| {
                        eprintln!("Warning: Relationship extraction failed for {}: {}", rel_path, e);
                        Vec::new()
                    });

                result.symbols = symbols;
                result.identifiers = identifiers;
                result.relationships = relationships;

                result
            })
            .collect();

        // Merge all results
        let mut collected = CollectedResults::new();
        for r in per_file_results {
            collected.merge(r);
        }
        collected
    });

    // Build Arrow batches
    let symbols_batch = build_symbols_batch(&collected.symbols)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to build symbols batch: {}", e)))?;

    let identifiers_batch = build_identifiers_batch(&collected.identifiers)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to build identifiers batch: {}", e)))?;

    let relationships_batch = build_relationships_batch(&collected.relationships)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to build relationships batch: {}", e)))?;

    let files_batch = build_files_batch(&collected.files)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to build files batch: {}", e)))?;

    // Convert to PyArrow using pyo3-arrow (zero-copy FFI)
    let symbols_pyarrow = PyRecordBatch::new(symbols_batch).into_pyarrow(py)?;
    let identifiers_pyarrow = PyRecordBatch::new(identifiers_batch).into_pyarrow(py)?;
    let relationships_pyarrow = PyRecordBatch::new(relationships_batch).into_pyarrow(py)?;
    let files_pyarrow = PyRecordBatch::new(files_batch).into_pyarrow(py)?;

    let files_processed = collected.files.len();
    let files_failed = collected.errors.len();

    Ok(PyArrowExtractionBatch {
        symbols: symbols_pyarrow.into(),
        identifiers: identifiers_pyarrow.into(),
        relationships: relationships_pyarrow.into(),
        files: files_pyarrow.into(),
        files_processed,
        files_failed,
        errors: collected.errors,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_symbols_schema() {
        let schema = symbols_schema();
        assert_eq!(schema.fields().len(), 12);
        assert!(schema.field_with_name("id").is_ok());
        assert!(schema.field_with_name("name").is_ok());
        assert!(schema.field_with_name("code_pattern").is_ok());
    }

    #[test]
    fn test_identifiers_schema() {
        let schema = identifiers_schema();
        assert_eq!(schema.fields().len(), 15);
        assert!(schema.field_with_name("confidence").is_ok());
    }

    #[test]
    fn test_relationships_schema() {
        let schema = relationships_schema();
        assert_eq!(schema.fields().len(), 7);  // includes confidence
        assert!(schema.field_with_name("confidence").is_ok());
    }

    #[test]
    fn test_files_schema() {
        let schema = files_schema();
        assert_eq!(schema.fields().len(), 5);
    }

    #[test]
    fn test_build_empty_symbols_batch() {
        let batch = build_symbols_batch(&[]).unwrap();
        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.num_columns(), 12);
    }

    #[test]
    fn test_build_empty_identifiers_batch() {
        let batch = build_identifiers_batch(&[]).unwrap();
        assert_eq!(batch.num_rows(), 0);
        assert_eq!(batch.num_columns(), 15);
    }
}
