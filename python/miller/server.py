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
_instructions = _instructions_path.read_text(encoding='utf-8') if _instructions_path.exists() else ""

# Create FastMCP server with lifespan handler and behavioral instructions
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan, instructions=_instructions)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# Import tool wrappers (thin delegating functions for FastMCP)
from miller.tools_wrappers import (
    fast_search,
    fast_search_multi,
    get_symbols,
    fast_lookup,
    fast_refs,
    trace_call_path,
    fast_explore,
    rename_symbol,
)


# Register tools with FastMCP
# output_schema=None disables structured content wrapping (avoids {"result": ...} for strings)
# All tools that return text/TOON strings need this to render properly
mcp.tool(output_schema=None)(fast_search)      # Returns text/TOON string (default: text)
mcp.tool(output_schema=None)(fast_search_multi)  # Cross-workspace search (returns text/TOON)
mcp.tool(output_schema=None)(get_symbols)      # Returns text/TOON/code string
mcp.tool(output_schema=None)(fast_lookup)      # Returns lean text string (batch symbol lookup)
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

    STDIO HARDENING (for MCP client integration):
    - UTF-8 encoding enforced on stdout/stderr
    - BrokenPipeError handled gracefully (client disconnect)
    """
    # CRITICAL: Apply stdio hardening FIRST before any output
    # This ensures UTF-8 encoding and clean streams for JSON-RPC protocol
    from miller.stdio_hardening import harden_stdio

    harden_stdio()

    logger.info("🚀 Starting Miller MCP server...")
    logger.info("📡 Server will respond to MCP handshake immediately")
    logger.info("📚 Background indexing will start after connection established")
    logger.info("👁️  File watcher will activate for real-time workspace updates")

    # Suppress FastMCP banner to keep stdout clean for MCP protocol
    # Handle BrokenPipeError if client disconnects unexpectedly
    try:
        mcp.run(show_banner=False)
    except BrokenPipeError:
        # Client disconnected - exit cleanly without stack trace
        import sys

        sys.stderr.write("Client disconnected. Shutting down.\n")
        sys.exit(0)


def main_http(host: str = None, port: int = None):
    """
    HTTP entry point for multi-client Miller server.

    Unlike STDIO mode, this allows multiple clients to connect
    to a single running server instance simultaneously.

    This is useful when you have:
    - A wrapper process that needs to query Miller
    - Claude Code also needing to access the same Miller instance
    - Multiple AI agents sharing one Miller server

    Args:
        host: Host to bind to (default: 127.0.0.1, or MILLER_HOST env var)
        port: Port to listen on (default: 8765, or MILLER_PORT env var)
    """
    import os

    # Support environment variable configuration
    host = host or os.environ.get("MILLER_HOST", "127.0.0.1")
    port = port or int(os.environ.get("MILLER_PORT", "8765"))

    logger.info(f"🚀 Starting Miller MCP server (HTTP mode)")
    logger.info(f"📡 Listening on http://{host}:{port}/mcp")
    logger.info(f"📚 Multiple clients can connect to this instance")

    try:
        mcp.run(transport="http", host=host, port=port)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down Miller HTTP server...")


def main_http_cli():
    """
    CLI entry point with argument parsing for HTTP server.

    Usage:
        miller-server-http --host 0.0.0.0 --port 8765

    Or via environment variables:
        MILLER_HOST=0.0.0.0 MILLER_PORT=8765 miller-server-http
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Miller MCP Server (HTTP mode) - allows multiple clients to connect"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: 127.0.0.1, or MILLER_HOST env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on (default: 8765, or MILLER_PORT env var)",
    )
    args = parser.parse_args()
    main_http(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
