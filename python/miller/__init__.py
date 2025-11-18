"""
Miller - Python MCP Server with Rust-Powered Tree-sitter Core

A hybrid Python/Rust code intelligence server combining battle-tested
tree-sitter parsing with Python's superior ML ecosystem.
"""

__version__ = "0.1.0"

# Import will fail until we build the Rust extension
try:
    from miller._miller_core import __version__ as core_version
    __rust_version__ = core_version
except ImportError:
    __rust_version__ = None
