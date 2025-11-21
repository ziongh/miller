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

## TOON Format: Token-Optimized Output

### What Is TOON?

**TOON (Token-Oriented Object Notation)** is a compact tabular encoding format that reduces token consumption by 30-60% compared to JSON for large result sets. Developed originally in Julie and migrated to Miller, TOON transforms verbose JSON objects into space-efficient tables.

### Why TOON Matters

**Token efficiency directly impacts performance and cost:**
- Claude API charges by tokens (input + output)
- Large search results (50-100+ symbols) consume thousands of tokens in JSON
- TOON achieves 33.8% average reduction (measured across real queries)
- Faster responses, lower costs, better UX

### How TOON Works

**JSON Format** (verbose):
```json
[
  {
    "name": "calculate_age",
    "kind": "Function",
    "signature": "(birth_year: int) -> int",
    "doc_comment": "Calculate age from birth year",
    "file_path": "src/user.py",
    "start_line": 15,
    "end_line": 17
  },
  {
    "name": "UserService",
    "kind": "Class",
    "signature": null,
    "doc_comment": "Service for user operations",
    "file_path": "src/services.py",
    "start_line": 23,
    "end_line": 45
  }
]
```

**TOON Format** (compact):
```
name|kind|signature|doc_comment|file_path|start_line|end_line
calculate_age|Function|(birth_year: int) -> int|Calculate age from birth year|src/user.py|15|17
UserService|Class||Service for user operations|src/services.py|23|45
```

**Key principles:**
1. **Schema homogeneity**: All objects must have identical fields (TOON requirement)
2. **CSV-like structure**: Header row + data rows
3. **Null representation**: Empty string for null values
4. **Escaping**: Pipe characters in data are escaped as `\|`

### Implementation

**Code location**: `python/miller/toon_utils.py`

All major Miller tools support three output modes:

```python
# Tools with TOON support:
fast_search(query, output_format="auto")      # Auto-switches at 20 results
get_symbols(file, output_format="auto")       # Auto-switches at 20 symbols
fast_refs(symbol, output_format="auto")       # Auto-switches at 10 references
trace_call_path(symbol, output_format="auto") # Auto-switches at 5 nodes
```

**Output modes:**
- `"json"` - Standard JSON (default for backward compatibility)
- `"toon"` - Always use TOON encoding
- `"auto"` - Smart switching based on result count (recommended)

**Auto-mode thresholds:**
- `fast_search`: 20 results
- `get_symbols`: 20 symbols
- `fast_refs`: 10 references
- `trace_call_path`: 5 nodes

### Testing TOON

**Test files:**
- `python/tests/test_toon_format.py` - Core TOON encoding tests (29 tests)
- `python/tests/test_fast_search_toon.py` - fast_search integration (12 tests)
- `python/tests/test_get_symbols_toon.py` - get_symbols integration (10 tests)
- `python/tests/test_fast_refs_toon.py` - fast_refs integration (10 tests)
- `python/tests/test_trace_toon.py` - trace_call_path integration (10 tests)

**What to test:**
```python
def test_toon_encoding_basic():
    """Verify TOON encoding produces correct table format."""
    symbols = [
        {"name": "foo", "kind": "Function", "file_path": "test.py"},
        {"name": "bar", "kind": "Class", "file_path": "test.py"}
    ]
    result = toon_encode(symbols)

    lines = result.strip().split("\n")
    assert lines[0] == "name|kind|file_path"  # Header
    assert lines[1] == "foo|Function|test.py"
    assert lines[2] == "bar|Class|test.py"

def test_auto_mode_threshold():
    """Verify auto mode switches to TOON at threshold."""
    # Small result set (<20) should stay JSON
    result = await fast_search(ctx, "rare_symbol", output_format="auto")
    assert isinstance(result, list)  # JSON

    # Large result set (≥20) should switch to TOON
    result = await fast_search(ctx, "common_term", output_format="auto")
    assert isinstance(result, str)  # TOON string
    assert "|" in result  # Table format
```

### Performance Measurements

**Verified token reduction** (measured with real queries):
- `fast_search`: 37.2% reduction (validated)
- `trace_call_path`: 45.6% reduction (validated)
- `fast_refs`: 44% reduction (validated)
- `get_symbols`: 35-40% reduction (estimated)

**Average**: 33.8% across all tools

**Measurement script**: `python/tests/measure_token_reduction.py`

### Schema Enforcement

**Critical**: TOON requires all objects in a batch to have identical fields. This is enforced at conversion time:

```python
def format_symbol_for_toon(symbol: dict) -> dict:
    """Enforce ToonSymbol schema (all fields present)."""
    return {
        "name": symbol.get("name", ""),
        "kind": symbol.get("kind", ""),
        "signature": symbol.get("signature"),  # May be None
        "doc_comment": truncate_doc(symbol.get("doc_comment")),  # Truncated
        "file_path": symbol.get("file_path", ""),
        "start_line": symbol.get("start_line"),
        "end_line": symbol.get("end_line"),
    }
```

**Why this matters**: If symbols have different fields (some have `signature`, some don't), TOON encoding fails. The schema enforcement ensures consistency.

### Graceful Degradation

**Fallback pattern**: If TOON encoding fails, tools automatically fall back to JSON:

```python
try:
    if output_format == "toon" or (output_format == "auto" and len(results) >= threshold):
        return toon_encode(results)
except Exception as e:
    logger.warning(f"TOON encoding failed: {e}, falling back to JSON")
    return results  # JSON fallback
```

**This ensures**:
- No service disruption if TOON fails
- Backward compatibility maintained
- Errors are logged but don't break the tool

### TOON Development Guidelines

1. **Always test auto-mode thresholds** - ensure switching logic works correctly
2. **Verify schema homogeneity** - test with diverse symbol types
3. **Test escaping** - ensure pipe characters in data don't break parsing
4. **Measure token reduction** - validate actual savings with real queries
5. **Test fallback** - ensure JSON fallback works when TOON fails

### Future Optimizations

**Potential improvements** (not implemented):
- Column ordering optimization (frequent fields first)
- Field omission (skip columns with all-null values)
- Compression (gzip for very large result sets)

**Current philosophy**: Keep it simple. The current implementation achieves 30-60% reduction with minimal complexity.

---

## 🔴 MANDATORY: LAZY LOADING - DO NOT BREAK THIS

### Non-Negotiable Rule: MCP Handshake Must Be Sub-Second

**Miller's MCP handshake must complete in under 1 second.** This requires strict lazy loading discipline.

### The Problem

Heavy ML libraries (torch, sentence-transformers) take 5-6 seconds to import on modern hardware. If these are imported during module initialization, the MCP handshake is blocked until imports complete, making Claude Code wait 5-6 seconds to connect.

**This is unacceptable.**

### The Solution: Background Task Pattern

Miller uses Julie's proven pattern:
1. **Server starts** → MCP handshake completes immediately (~100ms)
2. **Background task** → Imports heavy libraries and initializes components
3. **Indexing** → Runs in background after initialization

**Code locations (DO NOT MODIFY these patterns):**

#### `python/miller/__init__.py`
```python
# ❌ NEVER DO THIS (adds 5+ seconds to startup):
from miller import embeddings, server, storage

# ✅ ALWAYS DO THIS (instant startup):
# DO NOT import modules here - lazy loading is critical for fast MCP handshake
__all__ = ["miller_core"]
```

**Rationale**: The MCP server entry point is `server.py`, not `__init__.py`. There is ZERO reason to import heavy modules at package level.

#### `python/miller/server.py` (lines 109-112)
```python
# Lazy imports - only load heavy ML libraries in background task
from miller.embeddings import EmbeddingManager, VectorStore
from miller.storage import StorageManager
from miller.workspace import WorkspaceScanner
```

**Rationale**: These imports happen INSIDE the `background_initialization_and_indexing()` async function, which runs AFTER the MCP handshake completes. The server becomes ready immediately, then loads libraries in the background.

#### `python/miller/embeddings.py` (lines 16-17)
```python
import torch
from sentence_transformers import SentenceTransformer
```

**Rationale**: These are heavy imports, but they're OK here because this module is ONLY imported in the background task, never at package initialization time.

### Verification

After any changes, verify handshake speed:

```bash
# Start Miller
uv run miller-server

# In another terminal, time the connection
time claude-mcp-client connect miller

# Should see: real 0m0.5s (or similar sub-second time)
# If you see 5-6 seconds, YOU BROKE LAZY LOADING
```

### Common Mistakes That Break Lazy Loading

❌ **Importing heavy modules in `__init__.py`**
```python
# python/miller/__init__.py
from miller import embeddings  # ❌ WRONG - loads torch at import time
```

❌ **Importing heavy modules at module level in `server.py`**
```python
# python/miller/server.py (at top of file)
from miller.embeddings import EmbeddingManager  # ❌ WRONG - blocks handshake
```

❌ **Creating instances at module level**
```python
# python/miller/server.py (at top of file)
embeddings = EmbeddingManager()  # ❌ WRONG - loads torch before handshake
```

✅ **Correct: Import inside background task**
```python
# python/miller/server.py (inside async function)
async def background_initialization_and_indexing():
    from miller.embeddings import EmbeddingManager  # ✅ CORRECT
    embeddings = EmbeddingManager()  # ✅ CORRECT
```

### Why This Matters

**User experience:**
- Fast handshake: Claude Code connects instantly, user can start working immediately
- Slow handshake: Claude Code waits 5-6 seconds, user sees "Connecting..." spinner, terrible UX

**Developer experience:**
- Fast handshake: Quick iteration during development, fast testing
- Slow handshake: Every server restart takes 5-6 seconds, dev velocity destroyed

**This is not optional. Do not break lazy loading. Ever.**

If you find yourself tempted to import a heavy module at module level, STOP. Find another way. Use lazy imports, use background tasks, use dependency injection - anything except module-level imports of torch/sentence-transformers.

### Emergency Fix

If lazy loading breaks and you need to fix it immediately:

1. **Find the culprit**: `rg "^from miller.embeddings import" python/miller/`
2. **Check where it's called**: If it's NOT inside a function, it's wrong
3. **Move import inside function**: Wrap in async function or background task
4. **Verify**: Time the handshake again

**DO NOT COMMIT BROKEN LAZY LOADING. EVER.**

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

**For Linux with NVIDIA GPU:**

```bash
# Check your NVIDIA driver version first
nvidia-smi  # Look for "CUDA Version: X.Y"

# Install matching PyTorch (common versions)
uv pip install torch --index-url https://download.pytorch.org/whl/cu130  # CUDA 13.0
uv pip install torch --index-url https://download.pytorch.org/whl/cu124  # CUDA 12.4
uv pip install torch --index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1
```

**For Linux with AMD GPU:**

```bash
# ROCm support for AMD GPUs (Radeon RX 6000/7000 series, Instinct, etc.)
uv pip install torch --index-url https://download.pytorch.org/whl/rocm6.2

# ✅ This installs: torch with ROCm 6.2 support
# ✅ Supported GPUs: AMD Radeon RX 6000+, Radeon Pro, Instinct MI series
# ✅ Miller auto-detects ROCm and uses GPU acceleration
```

**For Linux/Windows with Intel Arc GPU:**

```bash
# Intel XPU support for Arc A-Series, Data Center GPU Max/Flex
pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu

# ✅ This installs: torch with Intel XPU support (PyTorch 2.5+)
# ✅ Supported: Arc A-Series (A770, A750, etc.), Data Center GPUs
# ✅ Miller auto-detects XPU and uses GPU acceleration
# ⚠️  Note: Requires Intel GPU drivers installed first
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

**Expected output (varies by GPU):**

*NVIDIA GPU (CUDA):*
- `CUDA available: True`
- `GPU: NVIDIA GeForce RTX 4080`
- `Miller using: cuda`

*AMD GPU (ROCm on Linux):*
- `CUDA available: True` (ROCm uses CUDA API)
- `GPU: AMD Radeon RX 7900 XTX`
- `Miller using: cuda` (with ROCm backend)

*Intel Arc (XPU):*
- `XPU available: True`
- `GPU: Intel Arc A770`
- `Miller using: xpu`

*Apple Silicon (MPS):*
- `MPS available: True`
- `Miller using: mps`

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

Miller's `pyproject.toml` lists `torch>=2.0` as a dependency, but **this installs CPU-only version by default**. You must manually install the GPU-enabled version using the commands above.

**Problem: AMD GPU on Linux not detected (showing CPU)**

1. **ROCm not installed**:
   ```bash
   # Verify ROCm PyTorch is installed
   python -c "import torch; print(hasattr(torch.version, 'hip'))"

   # Should print "True" - if "False", reinstall with ROCm:
   pip uninstall torch
   uv pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
   ```

2. **ROCm drivers not installed**:
   - Install AMD GPU drivers and ROCm runtime
   - Check: `rocm-smi` should show your GPU
   - See: https://rocm.docs.amd.com/projects/install-on-linux/

**Problem: Intel Arc GPU not detected (showing CPU or DirectML)**

1. **XPU PyTorch not installed**:
   ```bash
   # Verify XPU support
   python -c "import torch; print(hasattr(torch, 'xpu'))"

   # Should print "True" - if "False", install XPU version:
   pip uninstall torch
   pip install torch --index-url https://download.pytorch.org/whl/nightly/xpu
   ```

2. **Intel GPU drivers not installed**:
   - Linux: Install Intel GPU drivers + compute runtime
   - Windows: Install latest Intel Arc drivers
   - Verify: GPU should appear in device manager/lspci

### DirectML (Optional Fallback for AMD/Intel GPUs on Windows)

If you have an AMD or Intel GPU on Windows, you can use DirectML:

```bash
uv pip install torch-directml
```

Miller will auto-detect DirectML and use it for GPU acceleration (though CUDA on NVIDIA is faster).

### Performance Impact

**Embedding generation speed (100 symbols):**
- CPU: ~8-10 seconds
- GPU (CUDA - NVIDIA): ~0.5-1 second
- GPU (ROCm - AMD): ~0.7-1.5 seconds
- GPU (XPU - Intel Arc): ~1-2 seconds
- GPU (MPS - Apple Silicon): ~1-2 seconds
- GPU (DirectML - Windows fallback): ~2-3 seconds

**Device Priority (Auto-Detection Order):**
1. CUDA (NVIDIA) - Fastest, most mature
2. ROCm (AMD on Linux) - Native AMD, better than DirectML
3. XPU (Intel Arc) - Native Intel, better than DirectML
4. MPS (Apple Silicon) - macOS only
5. DirectML (Windows AMD/Intel fallback) - Universal but slower
6. CPU - Slowest fallback

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
