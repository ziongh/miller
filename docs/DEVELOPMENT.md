# Miller Development Guide

This document covers architecture details, testing patterns, and development workflows for contributors.

## Architecture: "Rust Sandwich" Model

```
Python Layer (Orchestration)
├── FastMCP Server (MCP protocol)
├── Embeddings (sentence-transformers)
├── Storage (SQLite + LanceDB)
└── Import miller_core (PyO3 extension)
        ↓
Rust Core (Performance)
├── Tree-sitter parsing (31 languages)
├── Symbol extraction
├── Relationship tracking
└── Identifier resolution
```

**Key principle**: Rust does the heavy lifting (parsing), Python handles the orchestration (storage, embeddings, MCP protocol).

### Why This Architecture?

Julie (our Rust MCP server) has excellent parsing capabilities but struggles with GPU-accelerated embeddings on Linux due to ONNX Runtime's complex CUDA requirements. Miller solves this by:

1. Keeping Julie's proven tree-sitter engine (compiled as a Python extension)
2. Using Python's mature ML ecosystem (`sentence-transformers`, PyTorch) for embeddings
3. Providing easier GPU setup and better hardware acceleration

---

## PyO3 Bridge (Rust ↔ Python)

### How It Works

**Rust side** (`src/bindings/symbol.rs`):
```rust
#[pyclass(name = "Symbol")]
pub struct PySymbol {
    #[pyo3(get)]  // Makes field readable from Python
    pub name: String,
    #[pyo3(get)]
    pub kind: String,
    // ... other fields
}

impl From<Symbol> for PySymbol {
    fn from(symbol: Symbol) -> Self {
        PySymbol {
            name: symbol.name,
            kind: format!("{:?}", symbol.kind),
            // ... convert Rust types to Python-friendly types
        }
    }
}
```

**Python side**:
```python
import miller_core

# Call Rust function
result = miller_core.extract_file(code, "python")

# Access Rust struct fields (zero-copy!)
for symbol in result.symbols:
    print(f"{symbol.name}: {symbol.kind}")  # Rust data, Python syntax
```

**Key insight**: PyO3 handles all conversions automatically. You write Rust, call it from Python, no serialization overhead.

### Testing the Bridge

**CRITICAL**: Test that Rust → Python conversions are correct.

```python
def test_pyo3_symbol_conversion():
    """Verify PyO3 converts Rust Symbol to Python correctly."""
    code = """
    def hello(name: str) -> str:
        '''Say hello.'''
        return f"Hello, {name}"
    """
    result = miller_core.extract_file(code, "python")

    assert len(result.symbols) == 1
    sym = result.symbols[0]

    # Test all fields are accessible
    assert sym.name == "hello"
    assert sym.kind == "Function"
    assert sym.signature == "(name: str) -> str"
    assert sym.doc_comment == "Say hello."
    assert sym.start_line == 2
    assert sym.end_line == 4

    # Test Python-specific behavior
    assert repr(sym).startswith("Symbol(")
    assert isinstance(sym.name, str)
```

---

## Database Schema (SQLite)

**Philosophy**: Exact parity with Julie's schema ensures:
1. We can compare results between Julie and Miller (validation)
2. We don't break assumptions about data structure
3. Migration is provable (run both, diff databases)

### Testing Database Schema

```python
def test_database_schema_matches_julie():
    """Ensure SQLite schema is identical to Julie's."""
    storage = StorageManager(db_path=":memory:")

    # Get actual schema
    cursor = storage.sql_conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table'")
    actual_schema = {row[0] for row in cursor.fetchall()}

    # Load Julie's expected schema
    with open("fixtures/julie_schema.sql") as f:
        expected_schema = set(f.read().split(";"))

    assert actual_schema == expected_schema
```

### Testing Data Integrity

```python
def test_cascade_delete_on_file_removal():
    """Symbols should be deleted when file is deleted (FK constraint)."""
    storage = StorageManager(db_path=":memory:")

    # Add file with symbols
    code = "def hello(): pass"
    results = miller_core.extract_file(code, "python", "test.py")
    storage.add_symbols_batch(results.symbols, "test.py")

    # Verify symbols exist
    cursor = storage.sql_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM symbols")
    assert cursor.fetchone()[0] > 0

    # Delete file
    cursor.execute("DELETE FROM files WHERE path = 'test.py'")

    # Symbols should be auto-deleted (CASCADE)
    cursor.execute("SELECT COUNT(*) FROM symbols")
    assert cursor.fetchone()[0] == 0
```

---

## Embeddings and Semantic Search

### Model: BAAI/bge-small-en-v1.5

- **Dimensions**: 384
- **Max tokens**: 512
- **Normalization**: L2 (cosine similarity)
- **Device**: Auto-detect GPU (CUDA) or fallback to CPU

### Testing Embeddings

```python
def test_embedding_dimensions():
    """Embeddings should have correct dimensionality."""
    embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

    code = "def test(): pass"
    results = miller_core.extract_file(code, "python")
    vectors = embeddings.embed_batch(results.symbols)

    assert vectors.shape == (len(results.symbols), 384)
    assert vectors.dtype == np.float32

def test_semantic_similarity():
    """Similar code should have high cosine similarity."""
    embeddings = EmbeddingManager()

    vec1 = embeddings.embed_query("function to calculate user age")
    vec2 = embeddings.embed_query("compute age of user")
    vec3 = embeddings.embed_query("delete all files")

    # Similar queries should be closer
    sim_12 = np.dot(vec1, vec2)  # Already normalized
    sim_13 = np.dot(vec1, vec3)

    assert sim_12 > 0.8  # High similarity
    assert sim_13 < 0.5  # Low similarity
    assert sim_12 > sim_13  # Sanity check

def test_gpu_acceleration():
    """Verify GPU is being used if available."""
    embeddings = EmbeddingManager(device="auto")

    if torch.cuda.is_available():
        assert embeddings.device == "cuda"
        code = "def test(): pass"
        results = miller_core.extract_file(code, "python")
        vectors = embeddings.embed_batch(results.symbols)
        assert vectors.shape[1] == 384
    else:
        assert embeddings.device == "cpu"
```

---

## MCP Server (FastMCP)

### Testing MCP Tools

**Philosophy**: Test tools as a user would call them (integration tests).

```python
import pytest
from miller.server import mcp, storage, embeddings

@pytest.mark.asyncio
async def test_index_file_tool():
    """Test the index_file MCP tool end-to-end."""
    test_file = Path("test_data/sample.py")
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("def hello(): pass")

    from fastmcp import Context
    ctx = Context()
    result = await mcp.tools["index_file"](ctx, str(test_file))

    assert "Success" in result
    assert "1 symbols" in result

    sym = storage.get_symbol_by_name("hello")
    assert sym is not None
    assert sym["kind"] == "Function"

    test_file.unlink()

@pytest.mark.asyncio
async def test_search_tool_text_mode():
    """Test text search mode."""
    from fastmcp import Context
    ctx = Context()
    results = await mcp.tools["fast_search"](ctx, "hello", search_method="text")

    assert len(results) > 0
    assert any("hello" in r.get("content", "").lower() for r in results)

@pytest.mark.asyncio
async def test_search_tool_semantic_mode():
    """Test semantic search mode."""
    from fastmcp import Context
    ctx = Context()
    results = await mcp.tools["fast_search"](
        ctx,
        "function that greets users",
        search_method="semantic"
    )

    assert len(results) > 0
```

---

## Quality Standards

### Code Quality

**Rust:**
- Use `clippy` for linting: `cargo clippy -- -D warnings`
- Format with `rustfmt`: `cargo fmt`
- No `unwrap()` in production code (use `?` or proper error handling)
- Document public APIs with `///` doc comments

**Python:**
- Type hints on all functions (use `mypy` for checking)
- Format with `black`: `black python/miller/`
- Lint with `ruff`: `ruff check python/miller/`
- Docstrings on all public functions (Google style)

### Performance Expectations

- **Parsing**: Should match Julie's speed (within 2x acceptable due to PyO3 overhead)
- **Embeddings**: >100 symbols/second on GPU, >10 on CPU
- **Search (FTS5)**: <50ms for typical queries
- **Search (semantic)**: <200ms for typical queries (includes embedding + HNSW)

### Git Commit Messages

Follow conventional commits:
```
feat(extractors): add Java enum support
fix(storage): cascade delete not working for relationships
test(embeddings): add GPU acceleration tests
docs(README): update installation instructions
refactor(bindings): simplify PySymbol conversion
```

---

## Common Pitfalls and Solutions

### Pitfall: "I'll add tests later"
**Solution**: No. Tests first. Always. If you write code without tests, delete it and start over with TDD.

### Pitfall: "This is too simple to test"
**Solution**: Simple code is the easiest to test. If you skip it, Murphy's Law guarantees it will break.

### Pitfall: "Mocking is too hard"
**Solution**: Hard-to-mock code is poorly designed code. Use dependency injection, interfaces, or refactor.

### Pitfall: "Tests are failing, I'll just skip them for now"
**Solution**: Failing tests are a gift - they're telling you something is broken. Fix the code or fix the test, but don't skip.

### Pitfall: "I changed Rust code but forgot to rebuild"
**Solution**: Always run `maturin develop` after Rust changes.

### Pitfall: "PyO3 bindings don't match Rust types"
**Solution**: Write conversion tests immediately:
```python
def test_all_rust_fields_accessible_in_python():
    result = miller_core.extract_file("def x(): pass", "python")
    sym = result.symbols[0]

    # Try to access every field - if missing, test fails
    _ = sym.id
    _ = sym.name
    _ = sym.kind
```

---

## Lazy Loading (Critical)

Heavy ML libraries (torch, sentence-transformers) take 5-6 seconds to import. If imported during module initialization, the MCP handshake is blocked.

### The Pattern

```python
# python/miller/server.py
async def background_initialization_and_indexing():
    # Lazy imports - only load heavy ML libraries AFTER handshake
    from miller.embeddings import EmbeddingManager, VectorStore
    from miller.storage import StorageManager
    from miller.workspace import WorkspaceScanner
```

### Key Files to Protect

- `python/miller/__init__.py` - Keep minimal, NO heavy imports
- `python/miller/server.py` - Heavy imports only in background task

### Verification

```bash
# Start Miller, time the connection
uv run miller-server &
time python -c "import miller_core"  # Should be <1 second
```

---

## Success Metrics

### Phase 1: Rust Core
- [x] All 31 extractors compile and link via PyO3
- [x] `miller_core.extract_file()` callable from Python
- [x] Tests pass for 5+ languages (Python, JS, Rust, Go, Java)
- [x] PyO3 conversion tests pass for all types

### Phase 2: Storage
- [x] SQLite schema matches Julie's
- [x] Can store/retrieve symbols, relationships, identifiers
- [x] FTS5 search returns results for basic queries
- [x] CASCADE deletes work (foreign key constraints)
- [x] Integration test: index file → search → find symbols

### Phase 3: Embeddings
- [x] sentence-transformers loads and runs on GPU (if available)
- [x] Embeddings have correct dimensions (384)
- [x] LanceDB stores and retrieves vectors
- [x] Semantic search returns relevant results
- [x] Performance: >100 symbols/sec on GPU

### Phase 4: MCP Server
- [x] FastMCP server starts and accepts connections
- [x] All tools work: index_file, fast_search, fast_goto, get_symbols
- [x] Can connect from Claude Desktop
- [x] End-to-end test: index project → search → get results
- [x] Error handling: graceful failures, helpful error messages

---

## Resources

### Documentation
- **PyO3**: https://pyo3.rs/
- **Maturin**: https://www.maturin.rs/
- **FastMCP**: https://gofastmcp.com/
- **sentence-transformers**: https://www.sbert.net/
- **LanceDB**: https://lancedb.github.io/lancedb/
- **pytest**: https://docs.pytest.org/

### Project Files
- **PLAN.md**: Detailed migration plan with code examples
- **Cargo.toml**: Rust dependencies and build config
- **pyproject.toml**: Python package and Maturin config
- **pytest.ini**: Pytest configuration

### Reference
- **Julie**: Reference workspace for comparing implementations
