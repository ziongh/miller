# Miller

**Python MCP Server with Rust-Powered Tree-sitter Core**

Miller is a hybrid Python/Rust code intelligence server that combines the battle-tested tree-sitter parsing from [Julie](https://github.com/yourusername/julie) with Python's superior ML ecosystem for embeddings and semantic search.

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

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for detailed setup instructions.

```bash
# 1. Install Rust
winget install Rustlang.Rustup

# 2. Set up Python environment
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"

# 3. Build and test
maturin develop --release
pytest python/tests/ -v
```

## Development

This is a **TDD project** - tests are written before implementation. See [CLAUDE.md](CLAUDE.md) for development guidelines.

```bash
# TDD workflow (auto-rebuild and test on file changes)
make dev

# Or manually:
maturin develop --release  # After Rust changes
pytest python/tests/       # After Python changes
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

- **[QUICKSTART.md](QUICKSTART.md)** - 5-minute setup guide
- **[CLAUDE.md](CLAUDE.md)** - Development guidelines (TDD rules!)
- **[docs/PLAN.md](docs/PLAN.md)** - Detailed migration plan from Julie
- **[`.memories/`](.memories/)** - Development memory storage

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

Built on the shoulders of [Julie](https://github.com/yourusername/julie), a mature Rust MCP server with excellent tree-sitter parsing.
