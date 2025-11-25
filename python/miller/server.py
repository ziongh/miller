"""
Miller MCP Server - FastMCP implementation

Provides MCP tools for code indexing and semantic search.
Uses Miller's Rust core for parsing and Python ML stack for embeddings.

CRITICAL: This is an MCP server - NEVER use print() statements!
stdout/stderr are reserved for JSON-RPC protocol. Use logger instead.
"""

from pathlib import Path

from fastmcp import FastMCP

from miller.logging_config import setup_logging
from miller.tools.checkpoint import checkpoint
from miller.tools.plan import plan
from miller.tools.recall import recall
from miller.lifecycle import lifespan
from miller import server_state

# Heavy imports (torch, sentence-transformers) are done in background task after handshake:
# - miller.embeddings (EmbeddingManager, VectorStore)
# - miller.storage (StorageManager)
# - miller.workspace (WorkspaceScanner)
# This ensures MCP handshake completes in milliseconds (Julie's pattern)

# Initialize logging FIRST (before any other operations)
logger = setup_logging()
logger.info("Starting Miller MCP Server initialization...")

# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None



# Load server instructions (Serena-style behavioral adoption)
_instructions_path = Path(__file__).parent / "instructions.md"
_instructions = _instructions_path.read_text() if _instructions_path.exists() else ""

# Create FastMCP server with lifespan handler and behavioral instructions
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan, instructions=_instructions)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# Import tool wrappers (thin delegating functions for FastMCP)
from miller.tools_wrappers import (
    fast_search,
    get_symbols,
    fast_refs,
    trace_call_path,
    fast_explore,
    rename_symbol,
)


# Register tools with FastMCP
# output_schema=None disables structured content wrapping (avoids {"result": ...} for strings)
# All tools that return text/TOON strings need this to render properly
mcp.tool(output_schema=None)(fast_search)      # Returns text/TOON string (default: text)
mcp.tool(output_schema=None)(get_symbols)      # Returns text/TOON/code string
mcp.tool(output_schema=None)(fast_refs)        # Returns text/TOON string (default: text)
mcp.tool(output_schema=None)(trace_call_path)  # Returns tree/TOON string (default: tree)
mcp.tool(output_schema=None)(fast_explore)     # Returns text string (default: text)

# Register refactoring tools
mcp.tool(output_schema=None)(rename_symbol)  # Returns text/JSON (default: text)

# Register memory tools
# output_schema=None ensures raw string output (not JSON wrapped)
mcp.tool(output_schema=None)(checkpoint)  # Returns checkpoint ID string
mcp.tool(output_schema=None)(recall)      # Returns formatted text/JSON
mcp.tool(output_schema=None)(plan)        # Returns formatted text/JSON

# Register workspace management tool
from miller.tools.workspace import manage_workspace

mcp.tool(output_schema=None)(manage_workspace)  # Returns text string (default: text)


# Module-level __getattr__ for backwards compatibility
# This allows `from miller.server import storage` to still work
# even though storage is now in server_state module
def __getattr__(name: str):
    """
    Dynamically resolve global state variables from server_state module.

    This provides backwards compatibility for code that imports globals like:
        from miller.server import storage, vector_store, etc.

    The actual state is stored in server_state.py so that both server.py and
    lifecycle.py can access and modify the same objects.
    """
    if name in ("storage", "vector_store", "embeddings", "scanner", "workspace_root"):
        return getattr(server_state, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Export functions for direct use (testing)
# The @mcp.tool() decorator wraps them, but we also need raw access
__all__ = [
    "mcp",
    "storage",
    "vector_store",
    "embeddings",
    "scanner",
    "fast_search",
    "get_symbols",
    "fast_refs",
    "trace_call_path",
    "fast_explore",
    "rename_symbol",
    "checkpoint",
    "recall",
    "plan",
]


# Server entry point
def main():
    """
    Main entry point for Miller MCP server.

    Follows Julie's proven startup pattern:
    1. Server starts immediately
    2. MCP handshake completes in milliseconds
    3. Background indexing runs via lifespan handler (non-blocking)
    4. File watcher starts after initial indexing (real-time updates)
    """
    logger.info("🚀 Starting Miller MCP server...")
    logger.info("📡 Server will respond to MCP handshake immediately")
    logger.info("📚 Background indexing will start after connection established")
    logger.info("👁️  File watcher will activate for real-time workspace updates")

    # Suppress FastMCP banner to keep stdout clean for MCP protocol
    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
