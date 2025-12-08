"""
Miller MCP tool wrappers - thin delegating functions for FastMCP.

These are the actual MCP tool implementations that FastMCP calls. They do minimal work,
delegating to the implementation modules while handling readiness checks and state access.

This package is split across modules to keep each file under 500 lines while maintaining
a clean separation of concerns: tool registration in server.py, tool implementation in tools/,
and thin wrappers here.
"""

# Re-export all wrappers from submodules
from miller.tools_wrappers.search import fast_search, fast_search_multi
from miller.tools_wrappers.navigation import get_symbols, fast_lookup, fast_refs
from miller.tools_wrappers.trace import trace_call_path, fast_explore
from miller.tools_wrappers.refactor import rename_symbol
from miller.tools_wrappers.agent import (
    get_architecture_map,
    validate_imports,
    find_similar_implementation,
)

__all__ = [
    # Search
    "fast_search",
    "fast_search_multi",
    # Navigation
    "get_symbols",
    "fast_lookup",
    "fast_refs",
    # Trace & Explore
    "trace_call_path",
    "fast_explore",
    # Refactoring
    "rename_symbol",
    # Agent Tooling
    "get_architecture_map",
    "validate_imports",
    "find_similar_implementation",
]
