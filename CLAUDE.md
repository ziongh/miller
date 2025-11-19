# Miller - Python MCP Server with Rust Core

## Project Overview

**Miller** is a hybrid Python/Rust code intelligence server that combines:
- **Rust's performance**: All tree-sitter parsing (31 languages) via PyO3 extension
- **Python's ecosystem**: Superior ML/AI libraries for embeddings and semantic search
- **Battle-tested logic**: Migrated from Julie, a mature Rust-based MCP server

### The Problem We're Solving

Julie (our Rust MCP server) has excellent parsing capabilities but struggles with GPU-accelerated embeddings on Linux due to ONNX Runtime's complex CUDA requirements. Miller solves this by:
1. Keeping Julie's proven tree-sitter engine (compiled as a Python extension)
2. Using Python's mature ML ecosystem (`sentence-transformers`, PyTorch) for embeddings
3. Providing easier GPU setup and better hardware acceleration

### Architecture: "Rust Sandwich" Model

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

---

## 🔴 MANDATORY: Always Verify Latest Package Versions

### Non-Negotiable Rule: NO OUTDATED DEPENDENCIES

**AI assistants have outdated training data.** Always verify the ACTUAL latest version of packages before adding them to the project.

### How to Check Versions

1. **Rust crates**: Search `https://crates.io/crates/{package-name}` or use web search
   ```bash
   # Example searches:
   # - "pyo3 latest version 2025"
   # - "tree-sitter rust crate latest version"
   # - Check https://github.com/PyO3/pyo3/releases
   ```

2. **Python packages**: Search `https://pypi.org/project/{package-name}` or use web search
   ```bash
   # Example searches:
   # - "sentence-transformers latest version 2025"
   # - "fastmcp pypi latest"
   # - Check https://github.com/{org}/{repo}/releases
   ```

3. **Tree-sitter grammars**: Check GitHub releases or crates.io
   - Most are on crates.io: `https://crates.io/crates/tree-sitter-{language}`
   - Some are git-only: Check the GitHub repo's latest commit

### Before Adding ANY Dependency

1. **Web search** for the latest version (MANDATORY)
2. **Check release notes** for breaking changes
3. **Verify compatibility** with other dependencies (especially tree-sitter versions)
4. **Update Cargo.toml or pyproject.toml** with the actual latest version
5. **Test** that it builds and works

### Current Verified Versions (as of 2025-11-17)

**Rust Core:**
- PyO3: `0.27.1` (October 2025) - Supports Python 3.14!
- tree-sitter: `0.25.9` (September 2025)
- maturin: `1.10.1` (November 2025)

**Python:**
- fastmcp: Check PyPI for latest
- sentence-transformers: Check PyPI for latest
- torch: Check PyPI for latest

**Tree-sitter grammars:** See Cargo.toml - we use Julie's proven versions but should verify they're still current.

### Example: Checking PyO3 Version

```bash
# ❌ WRONG - Using training data from 2024
pyo3 = { version = "0.22" }  # Outdated!

# ✅ CORRECT - Web search first
# Search: "pyo3 latest version 2025"
# Result: https://github.com/PyO3/pyo3/releases shows 0.27.1
pyo3 = { version = "0.27.1" }  # Current as of Nov 2025
```

**Remember**: We're building a modern project with the latest tools, not maintaining legacy code. Always use the newest stable versions.

---

## 🔴 MANDATORY: GPU Setup (PyTorch with CUDA)

### Critical for Performance

Miller uses PyTorch for embeddings. **GPU acceleration is 10-50x faster than CPU** for embedding generation.

### Installation Command (Verified 2025-11-18)

**For Windows with NVIDIA GPUs (Python 3.14):**

```bash
# Use uv (faster, better dependency resolution)
uv pip install torch --index-url https://download.pytorch.org/whl/cu130

# ✅ This installs: torch 2.9.1+cu130 (CUDA 13.0 support)
# ✅ Works with: Python 3.14, NVIDIA drivers 527.41+
# ✅ Supports: RTX 20/30/40/50 series, A100, H100, etc.
```

**Why CUDA 13.0 (`cu130`) specifically:**
- PyTorch 2.9.1 added CUDA 13.0 support
- CUDA 12.x indexes (`cu121`, `cu124`) only have wheels up to Python 3.13
- CUDA 13.0 index has Python 3.14 wheels
- CUDA is backward compatible (cu130 binaries work with CUDA 12.x/13.x drivers)

**For macOS (Apple Silicon):**

```bash
# Standard PyPI version includes MPS (Metal Performance Shaders) support
uv pip install torch

# Miller auto-detects MPS and uses GPU acceleration
```

**For Linux:**

```bash
# Check your NVIDIA driver version first
nvidia-smi  # Look for "CUDA Version: X.Y"

# Install matching PyTorch (common versions)
uv pip install torch --index-url https://download.pytorch.org/whl/cu130  # CUDA 13.0
uv pip install torch --index-url https://download.pytorch.org/whl/cu124  # CUDA 12.4
uv pip install torch --index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1
```

### Verification

After installation, verify GPU is detected:

```bash
# Quick check
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# Full check
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# Miller-specific check
python -c "from miller.embeddings import EmbeddingManager; mgr = EmbeddingManager(); print(f'Miller using: {mgr.device}')"
```

**Expected output:**
- `CUDA available: True`
- `GPU: NVIDIA GeForce RTX 4080` (or your specific GPU)
- `Miller using: cuda`

### Troubleshooting

**Problem: "CUDA available: False"**

1. **Wrong PyTorch version installed** (CPU-only):
   ```bash
   # Check installed version
   python -c "import torch; print(torch.__version__)"

   # If it shows "2.9.1+cpu", you have CPU-only version
   # Uninstall and reinstall with CUDA:
   uv pip uninstall torch
   uv pip install torch --index-url https://download.pytorch.org/whl/cu130
   ```

2. **NVIDIA drivers not installed**:
   - Windows: Install from https://www.nvidia.com/Download/index.aspx
   - Linux: `sudo apt install nvidia-driver-535` (or latest)
   - Verify: `nvidia-smi` should show your GPU

3. **Python version mismatch**:
   - CUDA 13.0 index: Python 3.10-3.14 supported
   - CUDA 12.4 index: Python 3.9-3.13 supported
   - CUDA 12.1 index: Python 3.9-3.12 supported

**Problem: "No module named 'torch'"**

Miller's `pyproject.toml` lists `torch>=2.0` as a dependency, but **this installs CPU-only version by default**. You must manually install the CUDA version using the commands above.

### DirectML (Optional Fallback for AMD/Intel GPUs on Windows)

If you have an AMD or Intel GPU on Windows, you can use DirectML:

```bash
uv pip install torch-directml
```

Miller will auto-detect DirectML and use it for GPU acceleration (though CUDA on NVIDIA is faster).

### Performance Impact

**Embedding generation speed (100 symbols):**
- CPU: ~8-10 seconds
- GPU (CUDA): ~0.5-1 second
- GPU (MPS): ~1-2 seconds
- GPU (DirectML): ~2-3 seconds

**On large codebases (1000+ files), GPU acceleration saves minutes to hours.**

---

## 🔴 MANDATORY: File Size Limits

### Non-Negotiable Rule: NO GIANT FILES

**Large files are unreadable in context windows.** Keep files small, focused, and modular.

### Hard Limit: 500 Lines Per File

- **Maximum**: 500 lines (including blank lines and comments)
- **Target**: 200-300 lines for most files
- **Absolute ceiling**: Never exceed 500 lines

### When a File Approaches 500 Lines

1. **Stop immediately** - do not add more code
2. **Refactor into modules** - split by responsibility
3. **Create new files** - move related functionality together
4. **Update imports** - ensure everything still works

### How to Split Large Files

**Python modules:**
```python
# Before: storage.py (600 lines)
storage.py              # Too big!

# After: Split by responsibility
storage/
  __init__.py          # Public API exports
  manager.py           # StorageManager class (200 lines)
  schema.py            # Schema definitions (100 lines)
  queries.py           # Query helpers (150 lines)
```

**Rust modules:**
```rust
// Before: lib.rs (700 lines)
lib.rs                 // Too big!

// After: Split by feature
lib.rs                 // Module declarations + public API (50 lines)
bindings/
  mod.rs              // Re-exports
  symbol.rs           // PySymbol bindings (150 lines)
  identifier.rs       // PyIdentifier bindings (100 lines)
  extraction.rs       // Extraction functions (200 lines)
```

### Red Flags That Indicate File Is Too Large

- ⚠️ Scrolling through file takes more than 3-4 seconds
- ⚠️ Multiple unrelated classes/functions in one file
- ⚠️ Difficult to find specific functionality
- ⚠️ File has more than 3-4 distinct responsibilities
- ⚠️ Line count > 400 (time to plan refactoring)

### Benefits of Small Files

✅ **Readable in context**: AI can see entire file at once
✅ **Easier to test**: Focused modules are simpler to test
✅ **Better separation of concerns**: Each file has one job
✅ **Faster to navigate**: Less scrolling, clearer structure
✅ **Simpler git diffs**: Changes are isolated to specific modules

### Example: Good File Organization

```
python/miller/
├── __init__.py              (20 lines)   - Package exports
├── storage.py               (300 lines)  - SQLite manager
├── embeddings.py            (250 lines)  - LanceDB + sentence-transformers
├── server.py                (200 lines)  - FastMCP server setup
└── tools/
    ├── __init__.py          (10 lines)   - Tool exports
    ├── search.py            (180 lines)  - Search tool handlers
    ├── navigation.py        (150 lines)  - Goto/refs tools
    └── workspace.py         (120 lines)  - Workspace indexing
```

**Every file < 500 lines. Every file has one clear purpose.**

### Enforcement

- Before committing, check line counts: `wc -l python/miller/*.py`
- If any file > 500 lines, **refactor immediately**
- Don't ask permission - just split it

**This is non-negotiable. Large files break the development workflow.**

---

## 🔴 MANDATORY: Test-Driven Development (TDD)

### Non-Negotiable Rules

**This is a TDD project. Not "test later", not "mostly tested", but true TDD.**

1. **NO CODE WITHOUT TESTS**
   - Every function has tests BEFORE implementation
   - Every class has tests BEFORE methods are added
   - Every bug fix starts with a failing test that reproduces it

2. **NO STUBS OR PLACEHOLDERS**
   - If you write a method, it must have real implementation
   - If you write a stub (e.g., `pass` or `raise NotImplementedError`), you MUST have a failing test for it
   - Stubs are only acceptable during refactoring when tests already exist and are currently failing

3. **TESTS ARE AS VALUABLE AS IMPLEMENTATION**
   - Test code deserves the same quality as production code
   - Tests should be readable, maintainable, and well-organized
   - Good tests document the intended behavior better than comments

4. **RED-GREEN-REFACTOR CYCLE**
   ```
   1. RED:    Write a failing test (proves it's testing something)
   2. GREEN:  Write minimal code to make it pass (proves the implementation works)
   3. REFACTOR: Clean up code while tests stay green (proves refactoring is safe)
   ```

5. **NO SHORTCUTS, NO WORKAROUNDS**
   - If something is hard to test, that's a design smell - fix the design
   - If you're tempted to skip a test "just this once" - that's when you need it most
   - If mocking seems complicated, the coupling might be too tight

### Testing Standards

**Rust Tests** (`src/` modules):
- Unit tests: Use `#[cfg(test)]` modules in the same file
- Integration tests: Use `tests/` directory
- Test data: Use fixtures for complex parsing scenarios
- Coverage: Aim for >90% on core extraction logic

**Python Tests** (`python/tests/`):
- Unit tests: One test file per module (`test_storage.py`, `test_embeddings.py`)
- Integration tests: Test Rust ↔ Python bridge (`test_core_integration.py`)
- Fixtures: Use `pytest` fixtures for database setup, mock data, etc.
- Coverage: Aim for >85% on Python orchestration code

**What to Test**:
- ✅ Rust extraction returns correct symbols for each language
- ✅ PyO3 bindings convert Rust → Python types correctly
- ✅ Database schema matches Julie's (compatibility tests)
- ✅ Embeddings generate correct vector dimensions
- ✅ Search returns expected results for known queries
- ✅ MCP tools handle edge cases (missing files, invalid input, etc.)

**Example TDD Workflow**:
```python
# 1. RED - Write failing test first
def test_extract_python_function():
    code = "def hello(): pass"
    result = miller_core.extract_file(code, "python")
    assert len(result.symbols) == 1
    assert result.symbols[0].name == "hello"
    assert result.symbols[0].kind == "Function"

# This test WILL FAIL initially (good!)

# 2. GREEN - Implement minimal code to pass
# ... implement extract_file() in Rust + PyO3 bindings ...

# 3. REFACTOR - Clean up while tests stay green
# ... improve code structure, add error handling, etc ...
```

---

## Development Workflow

### First-Time Setup

```bash
# 1. Clone and navigate
cd C:\source\miller

# 2. Set up Python environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install maturin pytest pytest-cov
pip install fastmcp sentence-transformers lancedb pandas torch

# 4. Build Rust extension
maturin develop --release

# 5. Run tests (should all pass)
pytest python/tests/ -v
cargo test
```

### Iterative Development (TDD Cycle)

**When adding a new feature:**

1. **Write test first** (RED)
   ```bash
   # Add test in python/tests/test_*.py
   # Run it - should FAIL
   pytest python/tests/test_feature.py::test_new_feature -v
   ```

2. **Implement feature** (GREEN)
   ```bash
   # If changing Rust:
   maturin develop --release && pytest python/tests/test_feature.py::test_new_feature -v

   # If changing Python:
   pytest python/tests/test_feature.py::test_new_feature -v
   ```

3. **Refactor** (REFACTOR)
   ```bash
   # Clean up code, run full test suite
   pytest python/tests/ -v
   cargo test
   ```

**When fixing a bug:**

1. **Reproduce bug with a test** (RED)
   ```python
   def test_bug_symbol_extraction_crashes_on_unicode():
       # This test reproduces issue #123
       code = "def café(): pass"  # Unicode in function name
       result = miller_core.extract_file(code, "python")
       assert len(result.symbols) == 1  # Currently fails/crashes
   ```

2. **Fix bug** (GREEN)
   - Debug, fix the root cause
   - Test passes

3. **Add edge cases** (prevent regressions)
   - Add more tests for similar scenarios
   - Run full suite to ensure no breakage

### Running Tests

```bash
# Python tests (fast)
pytest python/tests/ -v                    # All tests
pytest python/tests/test_storage.py -v    # Specific module
pytest python/tests/ -k "search" -v       # Tests matching "search"
pytest python/tests/ --cov=miller         # With coverage

# Rust tests (slower)
cargo test                                 # All tests
cargo test --lib                           # Library tests only
cargo test --test integration              # Integration tests
cargo test -- --nocapture                  # Show print statements

# Watch mode (re-run on file changes)
pytest-watch python/tests/                 # Python
cargo watch -x test                        # Rust
```

---

## Code Organization

### Rust Code (`src/`)

**Core modules** (copied from Julie):
- `src/extractors/` - All 31 language parsers (DO NOT MODIFY unless fixing bugs)
- `src/language.rs` - Language detection and registry (DO NOT MODIFY)

**New modules** (Miller-specific):
- `src/lib.rs` - PyO3 module entry point
- `src/bindings/` - PyO3 wrapper types (Symbol, Identifier, Relationship, etc.)

**Testing**:
- Each extractor should have tests in `src/extractors/{language}/mod.rs`
- Bindings should have tests in `tests/test_bindings.rs`

### Python Code (`python/miller/`)

```
python/
├── miller/
│   ├── __init__.py          # Package exports
│   ├── server.py            # FastMCP server (TDD)
│   ├── storage.py           # SQLite + LanceDB (TDD)
│   ├── embeddings.py        # Sentence-transformers (TDD)
│   ├── tools/               # MCP tool handlers (TDD)
│   │   ├── search.py
│   │   ├── navigation.py
│   │   └── workspace.py
│   └── schemas.py           # Pydantic models (TDD)
│
└── tests/                   # Test suite (MANDATORY)
    ├── conftest.py          # Pytest fixtures
    ├── test_core_integration.py  # Rust ↔ Python bridge
    ├── test_storage.py      # Database tests
    ├── test_embeddings.py   # ML/embedding tests
    ├── test_server.py       # MCP server tests
    └── fixtures/            # Test data
        ├── sample_code/     # Code samples for parsing
        └── expected_output/ # Known-good extraction results
```

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

**Testing database schema**:
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

**Test data integrity**:
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
        # Embedding should run on GPU
        code = "def test(): pass"
        results = miller_core.extract_file(code, "python")
        vectors = embeddings.embed_batch(results.symbols)
        # This should complete without errors
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
    # Create test file
    test_file = Path("test_data/sample.py")
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("def hello(): pass")

    # Call MCP tool
    from fastmcp import Context
    ctx = Context()
    result = await mcp.tools["index_file"](ctx, str(test_file))

    # Verify result
    assert "Success" in result
    assert "1 symbols" in result

    # Verify database was updated
    sym = storage.get_symbol_by_name("hello")
    assert sym is not None
    assert sym["kind"] == "Function"

    # Cleanup
    test_file.unlink()

@pytest.mark.asyncio
async def test_search_tool_text_mode():
    """Test text search mode."""
    # Index sample code
    # ... (setup) ...

    # Search
    from fastmcp import Context
    ctx = Context()
    results = await mcp.tools["fast_search"](ctx, "hello", search_method="text")

    assert len(results) > 0
    assert any("hello" in r.get("content", "").lower() for r in results)

@pytest.mark.asyncio
async def test_search_tool_semantic_mode():
    """Test semantic search mode."""
    # Index sample code with doc comments
    # ... (setup) ...

    # Semantic search (natural language)
    from fastmcp import Context
    ctx = Context()
    results = await mcp.tools["fast_search"](
        ctx,
        "function that greets users",
        search_method="semantic"
    )

    assert len(results) > 0
    # Should find "hello" or "greet" functions
```

---

## Quality Standards

### Code Quality

1. **Rust**:
   - Use `clippy` for linting: `cargo clippy -- -D warnings`
   - Format with `rustfmt`: `cargo fmt`
   - No `unwrap()` in production code (use `?` or proper error handling)
   - Document public APIs with `///` doc comments

2. **Python**:
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
**Solution**: Always run `maturin develop` after Rust changes. Better: use a watch mode script.

### Pitfall: "PyO3 bindings don't match Rust types"
**Solution**: Write conversion tests immediately. Example:
```python
def test_all_rust_fields_accessible_in_python():
    result = miller_core.extract_file("def x(): pass", "python")
    sym = result.symbols[0]

    # Try to access every field
    _ = sym.id
    _ = sym.name
    _ = sym.kind
    # ... etc - if a field is missing, test fails
```

---

## Success Metrics

### Phase 1: Rust Core (Complete when...)
- ✅ All 31 extractors compile and link via PyO3
- ✅ `miller_core.extract_file()` callable from Python
- ✅ Tests pass for 5+ languages (Python, JS, Rust, Go, Java)
- ✅ PyO3 conversion tests pass for all types (Symbol, Identifier, Relationship)

### Phase 2: Storage (Complete when...)
- ✅ SQLite schema matches Julie's (validated by schema comparison test)
- ✅ Can store/retrieve symbols, relationships, identifiers
- ✅ FTS5 search returns results for basic queries
- ✅ CASCADE deletes work (foreign key constraints)
- ✅ Integration test: index file → search → find symbols

### Phase 3: Embeddings (Complete when...)
- ✅ sentence-transformers loads and runs on GPU (if available)
- ✅ Embeddings have correct dimensions (384)
- ✅ LanceDB stores and retrieves vectors
- ✅ Semantic search returns relevant results
- ✅ Performance: >100 symbols/sec on GPU

### Phase 4: MCP Server (Complete when...)
- ✅ FastMCP server starts and accepts connections
- ✅ All tools work: index_file, fast_search, fast_goto, get_symbols
- ✅ Can connect from Claude Desktop
- ✅ End-to-end test: index project → search → get results
- ✅ Error handling: graceful failures, helpful error messages

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
- **Julie**: `c:\source\julie` (reference workspace for comparing implementations)

---

## Final Reminder: TDD is Not Optional

This project follows **strict TDD discipline**. That means:

1. Every new feature starts with a failing test
2. Every bug fix starts with a test that reproduces it
3. No code is committed without accompanying tests
4. No shortcuts, no "I'll test it later", no exceptions

**Why?** Because Miller is a critical tool that developers will rely on. If it breaks, it breaks their workflow. Tests are our safety net, our documentation, and our proof of correctness.

**If you find yourself writing code before tests, stop. Delete the code. Write the test first.**

The test-first discipline might feel slow at first, but it pays dividends:
- Fewer bugs in production
- Easier refactoring (tests prove it's safe)
- Better design (testable code is modular code)
- Faster debugging (tests isolate the problem)
- Confidence (green tests = working code)

**TDD isn't a suggestion. It's how we build Miller.**

---

**Happy coding! 🚀**
