"""
Miller MCP Server - FastMCP implementation

Provides MCP tools for code indexing and semantic search.
Uses Miller's Rust core for parsing and Python ML stack for embeddings.

CRITICAL: This is an MCP server - NEVER use print() statements!
stdout/stderr are reserved for JSON-RPC protocol. Use logger instead.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastmcp import FastMCP

from miller.logging_config import setup_logging
from miller.tools.memory import checkpoint, plan, recall
from miller.watcher import FileEvent, FileWatcher

# Heavy imports (torch, sentence-transformers) are done lazily in background task:
# - miller.embeddings (EmbeddingManager, VectorStore)
# - miller.storage (StorageManager)
# - miller.workspace (WorkspaceScanner)

# Initialize logging FIRST (before any other operations)
logger = setup_logging()
logger.info("Starting Miller MCP Server initialization...")

# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


# Declare Miller components as module-level globals (lazy-initialized on first use)
# These are None during module import to avoid blocking the MCP handshake
storage = None
vector_store = None
embeddings = None
scanner = None
workspace_root = None

# Lazy initialization state
_init_lock = asyncio.Lock()
_initialized = False


async def _ensure_initialized():
    """
    Lazy initialization of Miller components.

    Called on first tool invocation, NOT on server startup.
    This matches Julie's pattern: instant connection, lazy loading.
    """
    global storage, vector_store, embeddings, scanner, workspace_root, _initialized

    async with _init_lock:
        if _initialized:
            return

        logger.info("🔧 Lazy-initializing Miller components (first tool call)...")

        # Lazy imports - only load heavy ML libraries when actually needed
        from miller.embeddings import EmbeddingManager, VectorStore
        from miller.storage import StorageManager
        from miller.workspace import WorkspaceScanner

        # Initialize components (embeddings first, then pass to vector_store)
        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
        storage = StorageManager(db_path=".miller/indexes/symbols.db")
        vector_store = VectorStore(
            db_path=".miller/indexes/vectors.lance", embeddings=embeddings  # Pass for semantic/hybrid search
        )

        workspace_root = Path.cwd()
        scanner = WorkspaceScanner(
            workspace_root=workspace_root, storage=storage, embeddings=embeddings, vector_store=vector_store
        )

        _initialized = True
        logger.info("✅ Miller components initialized and ready")


# Define lifespan handler (Julie pattern - instant startup, lazy loading)
# Server starts immediately with NO initialization work
@asynccontextmanager
async def lifespan(_app):
    """
    FastMCP lifespan handler - startup and shutdown hooks.

    Startup: NOTHING. Server becomes ready instantly.
    Shutdown: Cleanup any resources that were initialized.

    This matches Julie's pattern: instant connection, zero startup work.
    Components initialize lazily on first tool call.
    """
    logger.info("✅ Miller server ready (components will lazy-load on first use)")

    yield  # Server runs here - INSTANT ready

    # SHUTDOWN: Cleanup if components were initialized
    logger.info("🛑 Miller server shutting down...")
    logger.info("👋 Miller server shutdown complete")



# Create FastMCP server with lifespan handler
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# MCP Tool implementations (plain functions for testing)


async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Search indexed code using text, semantic, or hybrid methods.

    Method selection (default: auto):
    - auto: Detects query type automatically (RECOMMENDED)
      * Has special chars (: < > [ ]) → pattern search (code idioms)
      * Natural language → hybrid search (text + semantic)
    - text: Full-text search with stemming (general code search)
    - pattern: Code idioms (: BaseClass, ILogger<, [Fact], etc.)
    - semantic: Vector similarity (conceptual matches)
    - hybrid: Combines text + semantic with RRF fusion

    Examples:
        # Auto-detection (recommended)
        fast_search("authentication logic")        # Auto → hybrid
        fast_search(": BaseClass")                 # Auto → pattern
        fast_search("ILogger<UserService>")        # Auto → pattern
        fast_search("[Fact]")                      # Auto → pattern

        # Manual override
        fast_search("map<int, string>", method="text")  # Force text
        fast_search("user auth", method="semantic")     # Force semantic

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return

    Returns:
        List of matching symbols with scores and metadata

    Note: Components lazy-load on first call (may take 2-3 sec first time).
    """
    # Lazy initialization on first call
    await _ensure_initialized()

    results = vector_store.search(query, method=method, limit=limit)

    # Format results for MCP
    formatted = []
    for r in results:
        formatted.append(
            {
                "name": r.get("name", ""),
                "kind": r.get("kind", ""),
                "file_path": r.get("file_path", ""),
                "signature": r.get("signature"),
                "doc_comment": r.get("doc_comment"),
                "start_line": r.get("start_line", 0),
                "score": r.get("score", 0.0),
            }
        )

    return formatted


async def fast_goto(symbol_name: str) -> Optional[dict[str, Any]]:
    """
    Find symbol definition location.

    Args:
        symbol_name: Name of symbol to find

    Returns:
        Symbol location info, or None if not found
    """
    # Lazy initialization on first call
    await _ensure_initialized()

    # Query SQLite for exact match
    sym = storage.get_symbol_by_name(symbol_name)

    if not sym:
        return None

    return {
        "name": sym["name"],
        "kind": sym["kind"],
        "file_path": sym["file_path"],
        "start_line": sym["start_line"],
        "end_line": sym["end_line"],
        "signature": sym["signature"],
        "doc_comment": sym["doc_comment"],
    }


async def get_symbols(file_path: str) -> list[dict[str, Any]]:
    """
    Get file structure (symbols without full content).

    Args:
        file_path: Path to file

    Returns:
        List of symbols in file

    Note: This function doesn't require initialization (uses Rust core directly).
    """
    path = Path(file_path)

    if not path.exists():
        return []

    # Read and extract (no lazy init needed - uses miller_core directly)
    try:
        content = path.read_text(encoding="utf-8")
        language = miller_core.detect_language(file_path)

        if not language:
            return []

        result = miller_core.extract_file(content, language, file_path)

        # Convert to dicts
        symbols = []
        for sym in result.symbols:
            symbols.append(
                {
                    "name": sym.name,
                    "kind": sym.kind,
                    "start_line": sym.start_line,
                    "end_line": sym.end_line,
                    "signature": sym.signature if hasattr(sym, "signature") else None,
                    "doc_comment": sym.doc_comment if hasattr(sym, "doc_comment") else None,
                }
            )

        return symbols

    except Exception:
        return []


# Register tools with FastMCP
mcp.tool()(fast_search)
mcp.tool()(fast_goto)
mcp.tool()(get_symbols)

# Register memory tools
mcp.tool()(checkpoint)
mcp.tool()(recall)
mcp.tool()(plan)


# Export functions for direct use (testing)
# The @mcp.tool() decorator wraps them, but we also need raw access
__all__ = [
    "mcp",
    "storage",
    "vector_store",
    "embeddings",
    "scanner",
    "fast_search",
    "fast_goto",
    "get_symbols",
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
