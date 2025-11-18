# Miller Distribution Guide

## Overview

Miller is distributed as a **Python package with Rust extension** (via PyO3). This document explains how we build and distribute it.

## Build System

### Local Development (UV)

**UV** is our package manager of choice - it's 10-100x faster than pip:

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create environment
uv venv                       # <1 second (vs 5-10s with venv)
source .venv/bin/activate

# Install dependencies
uv pip install maturin pytest  # 3-5 seconds (vs 30-60s with pip)

# Build Rust extension
maturin develop --release

# Run tests
pytest python/tests/ -v
```

### Maturin (PyO3 Build Tool)

**Maturin** handles building Python wheels with Rust extensions:

```bash
# Build wheel for current platform
maturin build --release

# Output:
# 📦 Built wheel: target/wheels/miller-1.0.0-cp312-cp312-macosx_11_0_arm64.whl
```

## GitHub Actions Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Purpose**: Run tests on every push/PR to ensure code quality.

**What it does**:
- Tests on **3 platforms** (Linux, macOS, Windows)
- Tests on **3 Python versions** (3.10, 3.11, 3.12)
- Runs **Python tests** (`pytest`)
- Runs **Rust tests** (`cargo test`)
- Checks **code formatting** (ruff, rustfmt)
- Runs **Clippy** (Rust linter)

**Speed optimizations**:
- Uses **UV** for fast dependency installation
- Uses **rust-cache** to cache Rust dependencies
- Uses **UV cache** for Python packages

**Triggers**:
- Every push to `main`
- Every pull request

### 2. Wheels Workflow (`.github/workflows/wheels.yml`)

**Purpose**: Build Python wheels for all platforms and publish to PyPI.

**What it builds**:

| Platform | Target | Architecture |
|----------|--------|--------------|
| macOS | `universal2-apple-darwin` | Intel + Apple Silicon (single wheel!) |
| Linux | `x86_64-unknown-linux-gnu` | x86_64 |
| Linux | `aarch64-unknown-linux-gnu` | ARM64 |
| Windows | `x64` | x86_64 |
| Windows | `aarch64-pc-windows-msvc` | ARM64 |

**Process**:

1. **Build wheels** for all platforms in parallel
2. **Test wheels** by installing and importing on each platform
3. **Build source distribution** (sdist) for users who want to compile from source
4. **Publish to PyPI** (only on releases)

**Triggers**:
- Every push to `main` (builds but doesn't publish)
- Every pull request (builds but doesn't publish)
- **Releases** (builds AND publishes to PyPI)

**Example wheel names**:
```
miller-1.0.0-cp312-cp312-macosx_11_0_universal2.whl  # macOS (Intel + M1/M2/M3)
miller-1.0.0-cp312-cp312-manylinux_2_17_x86_64.whl   # Linux x86_64
miller-1.0.0-cp312-cp312-win_amd64.whl               # Windows x64
```

## Publishing to PyPI

### Setup (One-time)

1. **Create PyPI account**: https://pypi.org/account/register/
2. **Enable Trusted Publishing** (no API tokens needed!):
   - Go to PyPI → Your account → Publishing
   - Add GitHub repository: `yourusername/miller`
   - Workflow: `wheels.yml`
   - Environment: `pypi`

### Release Process

```bash
# 1. Update version in pyproject.toml
# 2. Commit changes
git commit -am "Bump version to 1.0.0"

# 3. Create and push tag
git tag v1.0.0
git push origin v1.0.0

# 4. Create GitHub Release
gh release create v1.0.0 \
  --title "Miller v1.0.0" \
  --notes "Release notes here..."

# 5. GitHub Actions automatically:
#    - Builds wheels for all platforms
#    - Runs tests
#    - Publishes to PyPI
```

### What Users Get

After publishing, users can install Miller with a single command:

```bash
pip install miller
# or faster:
uv pip install miller
```

**Installation flow**:
1. PyPI detects user's platform (macOS ARM64, Linux x86_64, etc.)
2. Downloads pre-compiled wheel (~10MB)
3. Installs instantly (no Rust compiler needed!)
4. Total time: **~30 seconds** (vs 10+ minutes if compiling from source)

## Distribution Artifacts

### Wheels (Binary)
- **What**: Pre-compiled Python packages with Rust extension
- **Size**: ~10-15MB per platform
- **Speed**: Instant installation (no compilation)
- **Platforms**: macOS (Universal), Linux (x86_64, ARM64), Windows (x64, ARM64)

### Source Distribution (sdist)
- **What**: Python source + Rust source (no binaries)
- **Size**: ~1-2MB
- **Speed**: Slow installation (requires Rust compiler, 5-10 min)
- **Use case**: Platforms without pre-built wheels, or users who want to customize

## MCP Server Configuration

After installation, users need to configure Claude Desktop:

```json
{
  "mcpServers": {
    "miller": {
      "command": "python",
      "args": ["-m", "miller.server"],
      "env": {
        "WORKSPACE_ROOT": "/path/to/project"
      }
    }
  }
}
```

## Future: Simplified Distribution

### Option 1: CLI Installer
```bash
# Single command to install and configure
miller init /path/to/workspace
# Automatically installs package + configures Claude Desktop
```

### Option 2: Pre-built Binaries (like Julie)
- Build standalone executables with PyInstaller/PyOxidizer
- Users don't need Python installed
- Larger file size (~50-100MB) but simpler UX

## Comparison: Miller vs Julie Distribution

| Aspect | Julie (Pure Rust) | Miller (Python + Rust) |
|--------|-------------------|------------------------|
| **Package type** | Standalone binary | Python wheel |
| **File size** | ~5-10MB | ~10-15MB |
| **Installation** | Download + extract | `pip install` |
| **Dependencies** | None | Python 3.10+ |
| **Update** | Manual download | `pip install --upgrade` |
| **GPU support** | CUDA only (ONNX Runtime) | CUDA, MPS, DirectML (PyTorch) |
| **Build complexity** | Medium | Medium-High |
| **Distribution** | GitHub Releases | PyPI + GitHub |

## Summary

**For developers**:
- Use **UV** for fast development
- Use **maturin** for local builds
- GitHub Actions handle multi-platform builds automatically

**For users**:
- Install with `pip install miller` (or `uv pip install miller`)
- Pre-built wheels = no Rust compiler needed
- Works on macOS (Intel + Apple Silicon), Linux (x86_64 + ARM), Windows (x64 + ARM)

**Release process**:
1. Bump version
2. Create git tag
3. Create GitHub release
4. GitHub Actions does everything else (build + publish)
