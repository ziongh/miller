# Miller Quick Start Guide

## Prerequisites

- ✅ Python 3.9+ installed (you have 3.14 ✓)
- ⬜ Rust toolchain (install below)
- ⬜ Git (for version control)

## 5-Minute Setup

### 1. Install Rust

```bash
# Download from https://rustup.rs/ or use:
winget install Rustlang.Rustup

# Add useful components
rustup component add clippy rustfmt
```

### 2. Set Up Python Environment

```bash
cd C:\source\miller

# Create virtual environment
python -m venv .venv

# Activate it
.venv\Scripts\activate

# Install all dependencies
pip install -e ".[dev]"
```

### 3. Install Workflow Tools (Optional but Recommended)

```bash
# Auto-rebuild Rust on file changes
cargo install cargo-watch

# Make (for using the Makefile - optional)
choco install make
```

### 4. Verify Setup

```bash
# Check Rust
rustc --version
cargo --version

# Check Python
python --version
pytest --version
maturin --version

# You should see versions for all of these
```

## Your First Build

```bash
# Build the Rust extension (will fail initially - that's expected!)
maturin develop --release

# Run tests (will fail - we need to write them first!)
pytest python/tests/ -v
cargo test
```

**Expected result**: Build might fail because we haven't copied Julie's extractors yet. That's fine - we're starting from scratch with TDD!

## Development Workflow

### TDD Cycle (Recommended)

**Terminal 1** - Auto-rebuild Rust + run Python tests:
```bash
cargo watch -s "maturin develop && pytest python/tests/"
```

**Terminal 2** - Auto-run Python tests on changes:
```bash
pytest-watch python/tests/
```

Now: Make changes → Save → Tests run automatically!

### Manual Workflow

```bash
# After changing Rust code
maturin develop --release
pytest python/tests/

# After changing Python code
pytest python/tests/

# Run specific test
pytest python/tests/test_storage.py::test_sqlite_schema -v

# Format code before committing
make format
# Or manually:
cargo fmt && black python/

# Check code quality
make lint
# Or manually:
cargo clippy -- -D warnings
ruff check python/
mypy python/miller/
```

## Common Commands

```bash
# Build
make build              # Build Rust extension (release mode)
make build-dev          # Build Rust extension (debug mode, faster)

# Test
make test               # Run all tests (Rust + Python)
make test-rust          # Rust tests only
make test-python        # Python tests only
make test-cov           # Python tests with coverage report

# Code Quality
make format             # Format all code (Rust + Python)
make lint               # Run all linters
make lint-fix           # Auto-fix linting issues

# Development
make watch-rust         # Auto-rebuild Rust on changes
make watch-python       # Auto-run Python tests on changes
make dev                # Full dev mode (rebuild + test on any change)

# Cleanup
make clean              # Remove build artifacts
```

## File Structure

```
miller/
├── src/                    # Rust code (PyO3 extension)
│   ├── lib.rs             # PyO3 module entry
│   ├── bindings/          # Rust → Python wrappers
│   └── extractors/        # Tree-sitter parsers (from Julie)
│
├── python/                # Python code
│   ├── miller/            # Main package
│   │   ├── server.py      # FastMCP server
│   │   ├── storage.py     # SQLite + LanceDB
│   │   └── embeddings.py  # Sentence transformers
│   └── tests/             # Test suite
│       ├── conftest.py    # Pytest fixtures
│       └── test_*.py      # Test modules
│
├── docs/
│   ├── PLAN.md            # Detailed migration plan
│   └── CLAUDE.md          # Development guidelines (TDD rules!)
│
├── Cargo.toml             # Rust dependencies
├── pyproject.toml         # Python package config
├── pytest.ini             # Pytest configuration
└── Makefile               # Development commands
```

## Next Steps

1. **Read CLAUDE.md** - Understand the TDD discipline for this project
2. **Read PLAN.md** - Understand the migration strategy from Julie
3. **Phase 1: Rust Core** - Copy extractors from Julie, add PyO3 bindings
4. **Write tests first!** - This is a TDD project, tests come before implementation

## Getting Help

- **PyO3 docs**: https://pyo3.rs/
- **Maturin docs**: https://www.maturin.rs/
- **pytest docs**: https://docs.pytest.org/
- **Rust book**: https://doc.rust-lang.org/book/
- **Project plan**: See `docs/PLAN.md`

## Troubleshooting

### "maturin: command not found"
```bash
pip install maturin
```

### "cargo: command not found"
```bash
# Install Rust: https://rustup.rs/
```

### "Tests failing with 'No module named miller_core'"
```bash
# Build the Rust extension first
maturin develop --release
```

### "Import torch failed on GPU"
```bash
# Install CUDA-enabled PyTorch (if you have NVIDIA GPU)
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### "Rust build is slow"
```bash
# Use debug builds during development (much faster)
maturin develop
# Only use --release for final testing/production
```

## Ready to Start?

```bash
# Activate venv
.venv\Scripts\activate

# Start TDD workflow
make dev
# Or manually:
cargo watch -s "maturin develop && pytest python/tests/"
```

**Remember**: TDD is mandatory! Write tests first, then make them pass. 🚀
