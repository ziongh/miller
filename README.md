# Miller

**Python MCP Server with Rust-Powered Tree-sitter Core**

Miller is a hybrid Python/Rust code intelligence server that combines battle-tested tree-sitter parsing (31 languages) with Python's superior ML ecosystem for embeddings and semantic search.

## Architecture

```
Python (Orchestration)          Rust (Performance)
├── FastMCP Server      ←───→   ├── Tree-sitter (31 languages)
├── Embeddings                  ├── Symbol extraction
├── Storage (SQLite)            ├── Relationship tracking
└── LanceDB (vectors)           └── Identifier resolution
```

**Key Principle**: Rust does the heavy lifting (parsing), Python handles the orchestration (storage, embeddings, MCP protocol).

## Features

- 🚀 **31 Language Support**: Python, JavaScript, TypeScript, Rust, Go, Java, C#, and more
- 🔍 **Hybrid Search**: Tantivy FTS (BM25) + semantic vector search (dual-mode)
- 🎯 **LSP-Quality**: Go-to-definition, find-references, symbol outline
- 🧠 **GPU-Accelerated**: sentence-transformers with CUDA support
- 📦 **Zero-Copy Bridge**: PyO3 for Rust ↔ Python with no serialization overhead
- 💾 **Development Memory**: checkpoint/recall/plan tools for tracking development progress
- ⚡ **TOON Format**: 30-60% token reduction for faster responses and lower API costs

## Performance: TOON Format

Miller uses **TOON (Token-Oriented Object Notation)** to reduce token consumption by 30-60% for large result sets. This makes responses faster and API usage more efficient.

### What Is TOON?

TOON transforms verbose JSON into compact tables:

**JSON** (822 tokens):
```json
[
  {"name": "UserService", "kind": "Class", "signature": null, "doc_comment": "User management", ...},
  {"name": "calculate_age", "kind": "Function", "signature": "(year: int) -> int", ...},
  ...
]
```

**TOON** (515 tokens, 37% reduction):
```
name|kind|signature|doc_comment|file_path|start_line|end_line
UserService|Class||User management|src/services.py|10|45
calculate_age|Function|(year: int) -> int|Calculate user age|src/user.py|15|17
...
```

### Automatic Optimization

Miller's tools automatically switch to TOON for large results:

- **`fast_search`**: Uses TOON when ≥20 results found
- **`get_symbols`**: Uses TOON for files with ≥20 symbols
- **`fast_refs`**: Uses TOON when ≥10 references found
- **`trace_call_path`**: Uses TOON for trees with ≥5 nodes

**You don't need to do anything** - the `output_format="auto"` mode (default) handles it automatically.

### Manual Control

You can force a specific format if needed:

```python
# Always use JSON (verbose but structured)
await fast_search(ctx, "user", output_format="json")

# Always use TOON (compact table format)
await fast_search(ctx, "user", output_format="toon")

# Auto-select based on result size (recommended)
await fast_search(ctx, "user", output_format="auto")  # Default
```

### Why It Matters

**Token efficiency = better performance:**
- 📉 **Lower costs**: Claude API charges by tokens (input + output)
- ⚡ **Faster responses**: Less data to transmit and parse
- 🧠 **Better context usage**: More room for code in Claude's context window

**Real measurements**:
- `fast_search`: 37.2% average token reduction
- `trace_call_path`: 45.6% average token reduction
- `fast_refs`: 44% average token reduction

On large codebases with 100+ results, TOON can save thousands of tokens per query.

## Quick Start

### Linux/macOS

```bash
# 1. Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 2. Install UV (modern Python package manager - 10-100x faster than pip!)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Set up Python environment and build
uv venv                      # Create venv (<1 second!)
source .venv/bin/activate
uv pip install maturin pytest
maturin develop --release

# 4. Test
pytest python/tests/ -v
```

### Windows

```powershell
# 1. Install Rust (download installer from https://rustup.rs)
winget install Rustlang.Rustup
# Or download rustup-init.exe from https://win.rustup.rs

# 2. Install UV
winget install astral-sh.uv
# Or: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 3. Set up Python environment (use 3.12 for GPU support)
uv venv --python 3.12        # Python 3.12 for CUDA + DirectML support
.venv\Scripts\activate       # PowerShell
# Or: .venv\Scripts\activate.bat  # CMD

# 4. Install GPU-accelerated PyTorch (choose one):
uv pip install torch --index-url https://download.pytorch.org/whl/cu128  # NVIDIA GPU
# Or: uv pip install torch-directml  # Intel Arc / AMD GPU

# 5. Install build tools and dependencies
uv pip install -e ".[dev]"   # Install package with dev dependencies
uv tool install maturin      # Install maturin as global tool

# 6. Build Rust extension
maturin develop --release

# 7. Test
pytest python/tests/ -v
```

> **⚠️ Windows GPU Note:** Use Python 3.12 for maximum GPU compatibility:
> - Python 3.12: CUDA ✅ + DirectML ✅ (recommended)
> - Python 3.13: CUDA ✅ + DirectML ❌
> - Python 3.14: CUDA ❌ + DirectML ❌ (CPU only)
>
> See [docs/GPU_SETUP.md](docs/GPU_SETUP.md) for detailed GPU setup instructions.

## Development

This is a **TDD project** - tests are written before implementation. See [CLAUDE.md](CLAUDE.md) for development guidelines.

### Why UV?

Miller uses **[uv](https://github.com/astral-sh/uv)** instead of pip for:
- ⚡ **10-100x faster** installations (Rust-powered)
- 🧠 **Smart caching** across projects
- 🔧 **Better dependency resolution**
- 🐍 **Python version management** built-in

```bash
# TDD workflow
# After Rust changes:
maturin develop --release

# After Python changes:
pytest python/tests/

# Install new dependency (use uv instead of pip):
uv pip install package-name
```

## Memory Tools

Miller includes a development memory system for tracking checkpoints, decisions, learnings, and plans throughout your development process.

### Quick Start

```bash
# Create a checkpoint
/checkpoint Fixed authentication bug --type decision

# Recall recent memories
/recall 1hr                    # Last hour
/recall authentication         # Search by topic
/recall --type decision        # Filter by type

# Manage plans
/plan                          # List plans
```

### MCP Tools

**checkpoint** - Create immutable development memories
```python
await checkpoint(ctx, "Implemented search feature", tags=["feature", "search"])
```

**recall** - Retrieve memories with filtering
```python
await recall(ctx, type="decision", since="2025-11-17", limit=10)
```

**plan** - Manage development plans
```python
await plan(ctx, action="save", title="Add Auth", content="## Goal...")
```

### Features

- ✅ **100% Julie Compatible**: Same JSON schema, file format, directory structure
- ✅ **4 Memory Types**: checkpoint, decision, learning, observation
- ✅ **Git Context**: Automatically captures branch, commit, dirty status, changed files
- ✅ **Tag Support**: Normalized lowercase tags for categorization
- ✅ **Time Filtering**: ISO 8601 date ranges with timezone support
- ✅ **Plan Management**: Single-active plan enforcement, lifecycle tracking
- ✅ **Slash Commands**: Convenient `/checkpoint` and `/recall` CLI interface

### Storage

Memories are stored in `.memories/` directory:

```
.memories/
├── 2025-11-18/
│   ├── 180200_abd3.json    # Checkpoint at 18:02:00 UTC
│   ├── 181800_9a93.json
│   └── 182824_4ec9.json
└── plans/
    └── plan_add-search.json
```

All memory files are git-friendly JSON with:
- Pretty printing (indent=2, sorted keys)
- Trailing newline for clean diffs
- UTC timezone for cross-timezone consistency

See `.claude/commands/` for slash command definitions.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Development guidelines and agent onboarding
- **[docs/TOON.md](docs/TOON.md)** - TOON format specification
- **[docs/GPU_SETUP.md](docs/GPU_SETUP.md)** - PyTorch GPU installation
- **[docs/DISTRIBUTION.md](docs/DISTRIBUTION.md)** - Build and release process

## Project Status

✅ **Phase 1: Rust Core Extension** (Complete)
- ✅ Julie's extractors integrated (31 languages)
- ✅ PyO3 bindings created
- ✅ Extraction tested and working

✅ **Phase 2: Storage Layer** (Complete)
- ✅ SQLite for relations and metadata
- ✅ LanceDB for vectors and FTS
- ✅ Tantivy full-text search with BM25 ranking

✅ **Phase 3: Embeddings** (Complete)
- ✅ sentence-transformers integration
- ✅ GPU acceleration (CUDA)
- ✅ Semantic search operational

✅ **Phase 4: MCP Server** (Complete)
- ✅ FastMCP server with tools
- ✅ File watcher for real-time indexing
- ✅ Memory tools (checkpoint/recall/plan)
- ✅ Slash commands for UX

🚀 **Status**: Production-ready, actively dogfooding Miller for development

## License

MIT

## Acknowledgments

Tree-sitter extractors originally developed for Julie, a Rust MCP server project.
