# Miller

**Code Intelligence for AI Agents** — Hybrid Python/Rust MCP server with 80% token savings

Miller is a Model Context Protocol (MCP) server that gives AI agents fast, accurate code understanding without reading entire files. Pre-indexed search, symbol navigation, and call tracing return exactly what you need in a lean format that uses 80% fewer tokens than raw file reads.

## Why Miller?

| Without Miller | With Miller |
|----------------|-------------|
| Read 500-line file (2000+ tokens) | `get_symbols` → 20-line overview (200 tokens) |
| `grep` across codebase (slow, no context) | `fast_search` → semantic + text, ranked results |
| Manual reference hunting | `fast_refs` → all usages in <20ms |
| Reading files to trace calls | `trace_call_path` → visual call graph |

**The key insight**: AI agents waste most tokens on file reads. Miller's pre-indexed approach returns *just* what you need, in a format optimized for AI consumption.

## Token-Efficient Output

Every tool outputs its own **lean format** optimized for that tool's data — no verbose JSON by default:

**fast_search** — grep-style with code context:
```
10 matches for "authenticate":

src/auth/handler.py:42
    41: # Auth logic
    42→ def authenticate(user, password):
    43:     return verify_credentials(user, password)
```

**get_symbols** — scannable signature list:
```
src/auth.py: 5 symbols

  authenticate (function) line 42
    def authenticate(user: str, password: str) -> bool

  AuthMiddleware (class) line 58
    class AuthMiddleware
```

**fast_refs** — compact reference list:
```
authenticate: 12 references in 5 files

  src/routes/login.py:23 [Call]
  src/middleware/auth.py:45 [Call]
  tests/test_auth.py:12 [Call]
```

**trace_call_path** — ASCII tree visualization:
```
handleRequest (server.py:50)
├── authenticate (auth.py:42)
│   └── verify_credentials (crypto.py:15)
└── log_request (logger.py:30)
```

**Token savings**: 70-90% reduction compared to JSON, depending on the tool.

## Features

- **29 Languages**: Python, TypeScript, Rust, Go, Java, C#, and [more](docs/LANGUAGES.md)
- **Hybrid Search**: Tantivy FTS + semantic vectors + cross-encoder re-ranking
- **Pre-Indexed**: Sub-20ms queries on codebases of any size
- **GPU Accelerated**: CUDA, MPS (Apple Silicon), DirectML (Windows AMD/Intel)
- **Development Memory**: `checkpoint`/`recall`/`plan` for cross-session continuity
- **Real-time Updates**: File watcher keeps index fresh as you code

## Architecture

```
Python (MCP + ML)                 Rust (Parsing)
├── FastMCP Protocol      ←───→   ├── Tree-sitter (29 languages)
├── sentence-transformers         ├── Symbol extraction
├── SQLite (relations)            ├── Call graph building
└── LanceDB (vectors)             └── PyO3 zero-copy bridge
```

## Quick Start

### Option 1: Install from PyPI (Recommended)

```bash
pip install miller-core
```

### Option 2: Build from Source

**Prerequisites:**
- **Python 3.12+**
- **Rust**: [rustup.rs](https://rustup.rs)
- **uv**: [astral.sh/uv](https://astral.sh/uv) (recommended) or pip

**All Platforms:**
```bash
git clone https://github.com/anortham/miller.git
cd miller
uv sync                      # Install Python dependencies
maturin develop --release    # Build Rust extension
uv run pytest python/tests/ -v -o "addopts="  # Verify
```

**Windows Notes:**
- Use Python 3.12 for CUDA + DirectML GPU support
- If using PowerShell, run from Developer Command Prompt for Rust builds
- See [GPU_SETUP.md](docs/GPU_SETUP.md) for GPU acceleration setup

**macOS Notes:**
- Apple Silicon (M1/M2/M3) uses MPS for GPU acceleration automatically
- Xcode Command Line Tools required: `xcode-select --install`

**Linux Notes:**
- CUDA support requires PyTorch with CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu121`

### Add to Claude Code

After building from source, restart Claude Code, then run:

```bash
# From the miller directory (recommended)
cd /path/to/miller
claude mcp add miller -- uv run python -m miller.server

# Or with explicit path (works from anywhere)
claude mcp add miller -- uv run --directory /path/to/miller python -m miller.server

# User-scoped (available in all projects, not just this one)
claude mcp add --scope user miller -- uv run --directory /path/to/miller python -m miller.server

# If installed from PyPI
claude mcp add miller -- python -m miller.server
```

After adding, **restart Claude Code** to connect. Verify with:
```bash
claude mcp list
```

### Manual Configuration

Alternatively, edit the config file directly:

**Claude Code** (`~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "miller": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/miller", "python", "-m", "miller.server"]
    }
  }
}
```

**Claude Desktop** (config location varies by OS):
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "miller": {
      "command": "python",
      "args": ["-m", "miller.server"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**If installed from PyPI**, simplify to:
```json
{
  "mcpServers": {
    "miller": {
      "command": "python",
      "args": ["-m", "miller.server"]
    }
  }
}
```

## Core Tools

### fast_search — Find code fast
```python
fast_search("authentication logic")     # Semantic search
fast_search("IUserService", method="pattern")  # Code patterns
```

### get_symbols — File structure without reading
```python
get_symbols("src/auth.py", mode="structure")  # Names only (90% token savings)
get_symbols("src/auth.py", target="login", mode="full")  # Just what you need
```

### fast_refs — Impact analysis
```python
fast_refs("authenticate")  # Find ALL usages before refactoring
```

### trace_call_path — Understand execution flow
```python
trace_call_path("handleRequest", direction="downstream")  # What does it call?
trace_call_path("saveUser", direction="upstream")         # Who calls it?
```

### Development Memory
```python
checkpoint("Fixed auth bug - was missing await")  # Save progress
recall(query="authentication")                     # Find past work
plan(action="save", title="Add OAuth")            # Track tasks
```

## Output Formats

| Format | Description | When to Use |
|--------|-------------|-------------|
| **text** (default) | Tool-specific lean format | Most queries — optimized for AI reading |
| **json** | Structured data | Programmatic processing |
| **toon** | Tabular notation | Large result sets needing structure |
| **tree** | ASCII visualization | Call path tracing |

Default is always the leanest option. Override with `output_format="json"` when you need structured data.

## Development

```bash
# After Rust changes
maturin develop --release

# Run tests
uv run pytest python/tests/ -v

# Lint
cargo clippy && cargo fmt
uv run ruff check python/miller/
```

This is a **TDD project**. See [CLAUDE.md](CLAUDE.md) for development guidelines.

## Documentation

- [CLAUDE.md](CLAUDE.md) — Agent onboarding & development rules
- [docs/GPU_SETUP.md](docs/GPU_SETUP.md) — CUDA, MPS, DirectML setup
- [docs/TOON.md](docs/TOON.md) — TOON format specification
- [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) — Build & release

## Status

**v0.1.0** — Initial release. Production-ready for code intelligence workflows.

- ✅ 29-language parsing (tree-sitter via Rust)
- ✅ Hybrid search (FTS + semantic + re-ranking)
- ✅ Development memory (checkpoint/recall/plan)
- ✅ Real-time file watching
- ✅ GPU acceleration (CUDA, MPS, DirectML)

## License

MIT

## Acknowledgments

Tree-sitter extractors originally developed for [Julie](https://github.com/anortham/julie), a Rust MCP server.
