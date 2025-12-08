# Arrow-Based Extraction Pipeline

## Problem Statement

The current Rust→Python bridge creates millions of Python objects when indexing large codebases:
- Each symbol/identifier field access triggers a `.clone()` in Rust, creating a new Python string
- For 1MM LOC: ~50,000 symbols × 11 fields + ~5,000,000 identifiers × 15 fields = **~75 million allocations**
- This creates immense GC pressure and dominates indexing time

## Solution: Arrow-Native Pipeline

Replace Python object creation with Arrow columnar format:

```
Before:  Rust → PySymbol objects → Python list → PyArrow Table → LanceDB
After:   Rust → Arrow RecordBatch → Python (zero-copy) → LanceDB
```

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ Rust Layer (miller_core)                                         │
├──────────────────────────────────────────────────────────────────┤
│  extract_files_to_arrow(paths, workspace_root)                   │
│    → Returns PyArrowBatch { symbols, identifiers, relationships, │
│                             file_data }                          │
│    → Each field is a PyArrow RecordBatch (zero-copy to Python)   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Zero-copy FFI via Arrow PyCapsule
┌──────────────────────────────────────────────────────────────────┐
│ Python Layer                                                      │
├──────────────────────────────────────────────────────────────────┤
│  ArrowIndexingBuffer:                                             │
│    - Accumulates RecordBatch objects (not Python objects)         │
│    - Concatenates batches on flush                                │
│                                                                   │
│  VectorStore.add_arrow_batch(batch, vectors):                     │
│    - Appends vector column to batch                               │
│    - Passes directly to LanceDB (already uses Arrow)              │
│                                                                   │
│  SQLite writes via apsw or direct executemany from Arrow:         │
│    - Extract columns as Python lists using .to_pylist()           │
│    - Or use polars for df.write_database()                        │
└──────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Add Arrow Dependencies to Rust ✓
- Add `arrow` crate (v54.x) to Cargo.toml
- Add `pyo3-arrow` crate for zero-copy Python FFI
- Note: `pyo3-arrow` is preferred over `arrow::pyarrow` for extension type support

```toml
[dependencies]
arrow = { version = "54", default-features = false, features = ["ffi"] }
pyo3-arrow = "0.6"
```

### Phase 2: Create Arrow Schema Definitions
Define Arrow schemas matching our data structures:

**Symbols Schema:**
```rust
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
])
```

**Identifiers Schema:**
```rust
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
    Field::new("containing_symbol_id", DataType::Utf8, true),
    Field::new("target_symbol_id", DataType::Utf8, true),
    Field::new("confidence", DataType::Float32, false),
])
```

### Phase 3: Implement `extract_files_to_arrow()` in Rust
New function that:
1. Reads files and extracts symbols/identifiers in parallel (existing logic)
2. Builds Arrow arrays directly from Rust Vecs (no Python objects)
3. Returns `PyArrowBatch` struct containing all RecordBatches

```rust
#[pyclass]
pub struct PyArrowBatch {
    symbols: PyObject,      // pyarrow.RecordBatch
    identifiers: PyObject,  // pyarrow.RecordBatch
    relationships: PyObject, // pyarrow.RecordBatch
    file_data: PyObject,    // pyarrow.RecordBatch
}

#[pyfunction]
pub fn extract_files_to_arrow(
    py: Python<'_>,
    file_paths: Vec<String>,
    workspace_root: String,
) -> PyResult<PyArrowBatch> {
    // ... implementation
}
```

### Phase 4: Update Python Indexing Flow
Modify `WorkspaceScanner.index_workspace()`:

```python
# Before
buffer = IndexingBuffer(max_symbols=512)
for res in batch_results:
    buffer.add_result(...)  # Accumulates PySymbol objects

# After
buffer = ArrowIndexingBuffer(max_rows=512)
arrow_batch = miller_core.extract_files_to_arrow(paths, workspace_root)
buffer.add_batch(arrow_batch)  # Just stores RecordBatch reference
```

### Phase 5: Update VectorStore for Arrow Input

```python
def add_arrow_batch(self, symbols_batch: pa.RecordBatch, vectors: np.ndarray) -> int:
    """Add symbols from Arrow batch with embeddings."""
    # Add vector column to batch
    vector_array = pa.FixedSizeListArray.from_arrays(
        pa.array(vectors.flatten(), pa.float32()),
        self.dimension
    )
    augmented = symbols_batch.append_column("vector", vector_array)

    # Pass directly to LanceDB
    if self._table is None:
        self._table = self.db.create_table(self.table_name, augmented)
    else:
        self._table.add(augmented)

    return symbols_batch.num_rows
```

### Phase 6: Update SQLite Storage for Arrow Input

Option A: Extract columns as lists (simple, uses existing executemany):
```python
def add_symbols_from_arrow(self, symbols_batch: pa.RecordBatch) -> int:
    tuples = list(zip(
        symbols_batch.column("id").to_pylist(),
        symbols_batch.column("name").to_pylist(),
        # ... etc
    ))
    cursor.executemany(INSERT_SQL, tuples)
```

Option B: Use Polars (faster for large batches):
```python
import polars as pl

def add_symbols_from_arrow(self, symbols_batch: pa.RecordBatch) -> int:
    df = pl.from_arrow(symbols_batch)
    df.write_database("symbols", self.conn, if_table_exists="append")
```

### Phase 7: Maintain Backward Compatibility
Keep existing `extract_files_batch_with_io()` for:
- Existing tests
- Gradual migration
- Fallback if Arrow path fails

Add a feature flag or config option to switch between modes.

## Testing Strategy

1. **Unit Tests**: Arrow schema validation, column types
2. **Integration Tests**: Full indexing pipeline with Arrow path
3. **Benchmarks**: Compare GC pressure and throughput:
   - Memory profiling with `tracemalloc`
   - Indexing time comparison
   - GC collection counts

## Expected Benefits

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Python objects created | ~75M | ~10 | 7,500,000x fewer |
| Memory churn | High | Minimal | Stable memory |
| GC collections | Many | Few | Faster throughput |
| Indexing time | Baseline | -30-50% | Faster |

## Risks and Mitigations

1. **Arrow version conflicts**: Pin versions carefully, test with LanceDB
2. **pyo3-arrow compatibility**: May need to match pyo3 version (currently 0.27.1)
3. **Increased Rust complexity**: More code in bindings layer
4. **Embedding generation**: Still needs Python objects for model input
   - Mitigation: Only convert necessary text fields for embedding

## Implementation Order

1. ✓ Phase 1: Add Rust dependencies
2. ✓ Phase 2: Define Arrow schemas
3. Phase 3: Implement `extract_files_to_arrow()`
4. Phase 4: Create `ArrowIndexingBuffer`
5. Phase 5: Add `VectorStore.add_arrow_batch()`
6. Phase 6: Add SQLite Arrow methods
7. Phase 7: Integration and testing
