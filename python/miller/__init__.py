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

# Export main modules
from miller import storage, embeddings, server

__all__ = ["miller_core", "storage", "embeddings", "server"]
