"""
Miller - Python MCP Server with Rust-Powered Tree-sitter Core

A hybrid Python/Rust code intelligence server combining battle-tested
tree-sitter parsing with Python's superior ML ecosystem.
"""

__version__ = "0.1.0"

# Import Rust extension module (built as miller.miller_core by maturin)
try:
    from miller import miller_core

    __rust_version__ = miller_core.__version__
except ImportError:
    miller_core = None
    __rust_version__ = None

# DO NOT import modules here - lazy loading is critical for fast MCP handshake
# The MCP server entry point is server.py, which handles imports in background tasks
# Importing embeddings/storage here breaks the ~100ms handshake target (adds 5+ seconds)

__all__ = ["miller_core"]
