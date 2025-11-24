# Miller - Agent Onboarding Guide

## What Is Miller?

A hybrid Python/Rust code intelligence MCP server. **Rust** does fast parsing (31 languages via tree-sitter), **Python** handles ML/embeddings and the MCP protocol.

```
Python Layer (FastMCP + sentence-transformers + SQLite/LanceDB)
    ↓
miller_core (PyO3 extension)
    ↓
Rust Core (tree-sitter parsing, symbol extraction)
```

---

## 🔴 Critical Rules (Non-Negotiable)

### 1. TDD Is Mandatory

**No code without tests. Period.**

```bash
# RED: Write failing test first
pytest python/tests/test_feature.py::test_new_thing -v  # Should FAIL

# GREEN: Implement minimal code
# ... write code ...
pytest python/tests/test_feature.py::test_new_thing -v  # Should PASS

# REFACTOR: Clean up, full suite
pytest python/tests/ -v
```

Every bug fix starts with a failing test that reproduces it.

### 2. File Size Limit: 500 Lines Max

- **Hard limit**: 500 lines per file
- **Target**: 200-300 lines
- If approaching 500: **stop and refactor into modules**

Check before committing: `wc -l python/miller/*.py`

### 3. Don't Break Lazy Loading

Heavy ML imports (torch, sentence-transformers) must happen **inside background tasks**, never at module level.

```python
# ❌ WRONG - blocks MCP handshake for 5-6 seconds
from miller.embeddings import EmbeddingManager  # At top of server.py

# ✅ CORRECT - import inside async function
async def background_initialization():
    from miller.embeddings import EmbeddingManager  # Lazy import
```

**Key files** (don't add top-level heavy imports):
- `python/miller/__init__.py` - Keep minimal
- `python/miller/server.py` - Heavy imports only in `background_initialization_and_indexing()`

### 4. Verify Package Versions

AI training data is outdated. **Always web search** for latest versions before adding dependencies.

```bash
# Check PyPI: https://pypi.org/project/{package}/
# Check crates.io: https://crates.io/crates/{crate}/
```

---

## Dogfooding Setup

**Miller is this project's own MCP server.** After code changes:

1. Rebuild if Rust changed: `maturin develop --release`
2. **Restart Claude Code** to pick up Python/server changes

Without restart, you're testing old code!

---

## Workspace-Specific Paths (Important!)

Miller uses **per-workspace databases**, NOT a single global database. This is critical for debugging:

```
.miller/
├── workspace_registry.json          # Maps workspace IDs to paths
└── indexes/
    └── <workspace_id>/              # e.g., miller_816288f4
        ├── symbols.db               # SQLite: symbols, relationships, identifiers
        └── vectors.lance/           # LanceDB: embeddings for semantic search
```

**Common pitfall:** Don't query `.miller/index.db` directly - it may be empty or stale. Use:

```python
from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path

# Get correct paths for a workspace
db_path = get_workspace_db_path("primary")      # → .miller/indexes/<id>/symbols.db
vector_path = get_workspace_vector_path("primary")  # → .miller/indexes/<id>/vectors.lance
```

**For tools that need vector search:** Always pass workspace-specific `vector_store`, don't rely on `server.vector_store` global (it may not match the workspace being queried).

---

## Build & Test Commands

### Build Rust Extension (after Rust changes)
```bash
maturin develop --release
```

### Run Tests
```bash
# Python tests (fast, run frequently)
pytest python/tests/ -v                    # All
pytest python/tests/test_storage.py -v    # Specific module
pytest python/tests/ -k "search" -v       # Pattern match

# Rust tests
cargo test

# Combined (after Rust changes)
maturin develop --release && pytest python/tests/ -v
```

### Linting
```bash
# Rust
cargo clippy -- -D warnings
cargo fmt

# Python
ruff check python/miller/
black python/miller/
```

---

## File Layout

```
miller/
├── CLAUDE.md              # This file (agent onboarding)
├── src/                   # Rust code
│   ├── lib.rs             # PyO3 module entry
│   ├── extractors/        # 31 language parsers (from Julie)
│   └── bindings/          # PyO3 wrapper types
│
├── python/
│   ├── miller/            # Python package
│   │   ├── __init__.py    # Keep minimal (lazy loading!)
│   │   ├── server.py      # FastMCP server, tools
│   │   ├── storage.py     # SQLite manager
│   │   ├── embeddings.py  # LanceDB + sentence-transformers
│   │   ├── workspace.py   # File scanning, indexing
│   │   └── toon_utils.py  # TOON format encoding
│   │
│   └── tests/             # pytest suite
│       ├── conftest.py    # Fixtures
│       ├── test_*.py      # Test modules
│       └── fixtures/      # Test data
│
├── .miller/               # Runtime data (gitignored)
│   ├── index.db           # SQLite database
│   ├── vectors.lance/     # LanceDB vector store
│   └── miller.log         # Server logs
│
├── .memories/             # Development memories (checkpoint/recall)
│   ├── YYYY-MM-DD/        # Daily checkpoints
│   └── plans/             # Mutable plans
│
└── docs/                  # Detailed documentation
    ├── TOON.md            # TOON format spec
    ├── GPU_SETUP.md       # PyTorch GPU installation
    └── DEVELOPMENT.md     # Architecture, testing details
```

---

## Log Files

Server logs are in `.miller/miller.log`. To view:
```bash
tail -f .miller/miller.log
```

For debugging, check:
- MCP connection issues → server startup logs
- Indexing problems → look for "indexing" or "workspace" entries
- Search issues → look for "search" or "query" entries

---

## Key Concepts

### TOON Format
Token-efficient output format (30-60% fewer tokens than JSON). Tools auto-switch to TOON for large results.
→ See [docs/TOON.md](docs/TOON.md)

### PyO3 Bridge
Rust structs exposed to Python via PyO3. Zero-copy field access.
```python
import miller_core
result = miller_core.extract_file(code, "python")
for sym in result.symbols:
    print(sym.name, sym.kind)  # Rust data, Python syntax
```

### Workspaces
- **Primary workspace**: Auto-indexed on startup (current directory)
- **Reference workspaces**: Added via `manage_workspace(operation="add", path="...")`

---

## Common Tasks

### Add a New Tool
1. Write test in `python/tests/test_tools.py`
2. Add tool function in `python/miller/server.py`
3. Register with `@mcp.tool()` decorator
4. Restart Claude Code to test

### Fix a Bug
1. Write failing test that reproduces the bug
2. Fix the code
3. Verify test passes
4. Run full suite: `pytest python/tests/ -v`

### Modify Rust Extraction
1. Edit `src/extractors/{language}/mod.rs`
2. Add/update tests in that file
3. Rebuild: `maturin develop --release`
4. Run Rust tests: `cargo test`
5. Run Python integration tests: `pytest python/tests/test_core_integration.py -v`

---

## Detailed Documentation

- **[docs/TOON.md](docs/TOON.md)** - TOON format specification, encoding details
- **[docs/GPU_SETUP.md](docs/GPU_SETUP.md)** - PyTorch GPU installation (CUDA, ROCm, MPS)
- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** - Architecture deep-dive, testing patterns
- **[docs/PLAN.md](docs/PLAN.md)** - Original migration plan from Julie

---

## Quick Reference

| Task | Command |
|------|---------|
| Build Rust | `maturin develop --release` |
| Python tests | `pytest python/tests/ -v` |
| Rust tests | `cargo test` |
| Check line counts | `wc -l python/miller/*.py` |
| View logs | `tail -f .miller/miller.log` |
| Lint Python | `ruff check python/miller/` |
| Lint Rust | `cargo clippy -- -D warnings` |
