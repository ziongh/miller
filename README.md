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
- 🔍 **Dual Search**: FTS5 text search + semantic vector search
- 🎯 **LSP-Quality**: Go-to-definition, find-references, symbol outline
- 🧠 **GPU-Accelerated**: sentence-transformers with CUDA support
- 📦 **Zero-Copy Bridge**: PyO3 for Rust ↔ Python with no serialization overhead

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

## Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - 5-minute setup guide
- **[CLAUDE.md](CLAUDE.md)** - Development guidelines (TDD rules!)
- **[docs/PLAN.md](docs/PLAN.md)** - Detailed migration plan from Julie

## Project Status

🚧 **Phase 1: Rust Core Extension** (In Progress)
- [ ] Copy Julie's extractors
- [ ] Create PyO3 bindings
- [ ] Test extraction for 5+ languages

⏳ **Phase 2: Storage Layer** (Not Started)
⏳ **Phase 3: Embeddings** (Not Started)
⏳ **Phase 4: MCP Server** (Not Started)

## License

MIT

## Acknowledgments

Built on the shoulders of [Julie](https://github.com/yourusername/julie), a mature Rust MCP server with excellent tree-sitter parsing.
