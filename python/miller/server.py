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

from miller.embeddings import EmbeddingManager, VectorStore
from miller.logging_config import setup_logging
from miller.storage import StorageManager
from miller.tools.memory import checkpoint, plan, recall
from miller.watcher import FileEvent, FileWatcher
from miller.workspace import WorkspaceScanner

# Initialize logging FIRST (before any other operations)
logger = setup_logging()
logger.info("Starting Miller MCP Server initialization...")

# Import Rust core
try:
    from . import miller_core
except ImportError:
    # For testing without building Rust extension
    miller_core = None


# Declare Miller components as module-level globals (initialized in lifespan)
# These are None during module import to avoid blocking the MCP handshake
storage = None
vector_store = None
embeddings = None
scanner = None
workspace_root = None


# Define lifespan handler (Julie pattern - background indexing + file watching)
# This follows Julie's pattern: handshake completes immediately,
# then components are initialized and indexing runs in background
@asynccontextmanager
async def lifespan(_app):
    """
    FastMCP lifespan handler - startup and shutdown hooks.

    Startup:
      1. Initialize Miller components (AFTER handshake completes)
      2. Launch background indexing task (non-blocking)
      3. Start file watcher for real-time updates

    Shutdown: Stop file watcher and cleanup
    """
    global storage, vector_store, embeddings, scanner, workspace_root

    # PHASE 1: Initialize components (happens AFTER MCP handshake)
    # This defers expensive ML model loading until after connection is established
    logger.info("🔧 Initializing Miller components (post-handshake)...")

    storage = StorageManager(db_path=".miller/indexes/symbols.db")
    vector_store = VectorStore(db_path=".miller/indexes/vectors.lance")
    embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")

    workspace_root = Path.cwd()
    logger.info(f"📁 Workspace root: {workspace_root}")

    scanner = WorkspaceScanner(
        workspace_root=workspace_root, storage=storage, embeddings=embeddings, vector_store=vector_store
    )
    logger.info("✅ Miller components initialized and ready")

    # PHASE 2: Launch background indexing task (non-blocking)
    logger.info("🚀 Spawning background indexing task")

    # File watcher reference (initialized after initial indexing)
    file_watcher = None

    async def on_files_changed(events: list[tuple[FileEvent, Path]]):
        """
        Callback for file watcher - re-indexes changed files in real-time.

        Args:
            events: List of (event_type, file_path) tuples from watcher
        """
        for event_type, file_path in events:
            try:
                if event_type == FileEvent.DELETED:
                    # Convert to relative path for storage
                    rel_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")
                    storage.delete_file(rel_path)
                    logger.info(f"🗑️  Deleted from index: {rel_path}")
                else:
                    # Re-index file (handles CREATED and MODIFIED)
                    success = await scanner._index_file(file_path)
                    rel_path = str(file_path.relative_to(workspace_root)).replace("\\", "/")
                    if success:
                        action = "Indexed" if event_type == FileEvent.CREATED else "Updated"
                        logger.info(f"✏️  {action}: {rel_path}")
                    else:
                        logger.warning(f"⚠️  Failed to index: {rel_path}")
            except Exception as e:
                logger.error(f"❌ Error processing file change {file_path}: {e}", exc_info=True)

    async def background_indexing():
        """Background task that runs initial indexing, then starts file watcher."""
        nonlocal file_watcher
        try:
            # Small delay to ensure server is fully ready
            await asyncio.sleep(0.5)

            # Initial indexing
            logger.info("🔍 Checking if workspace indexing needed...")
            if await scanner.check_if_indexing_needed():
                logger.info("📚 Workspace needs indexing - starting background indexing")
                stats = await scanner.index_workspace()
                logger.info(
                    f"✅ Indexing complete: {stats['indexed']} indexed, "
                    f"{stats['updated']} updated, {stats['skipped']} skipped, "
                    f"{stats['deleted']} deleted, {stats['errors']} errors"
                )
            else:
                logger.info("✅ Workspace already indexed - ready for search")

            # Start file watcher for real-time updates
            logger.info("👁️  Starting file watcher for real-time indexing...")
            # Use load_gitignore() to get same patterns as workspace scanner
            # (combines DEFAULT_IGNORES + .gitignore file patterns)
            from miller.ignore_patterns import load_gitignore

            ignore_spec = load_gitignore(workspace_root)
            # Extract pattern strings from PathSpec (patterns are GitWildMatchPattern objects)
            pattern_strings = {p.pattern for p in ignore_spec.patterns}
            file_watcher = FileWatcher(
                workspace_path=workspace_root,
                indexing_callback=on_files_changed,
                ignore_patterns=pattern_strings,  # Use exact same patterns as scanner
                debounce_delay=0.2,
            )
            file_watcher.start()
            logger.info("✅ File watcher active - workspace changes will be indexed automatically")

        except Exception as e:
            logger.error(f"❌ Background indexing/watcher startup failed: {e}", exc_info=True)

    # Spawn background task (non-blocking - server continues)
    indexing_task = asyncio.create_task(background_indexing())

    yield  # Server runs here

    # SHUTDOWN: Stop file watcher and wait for background task
    logger.info("🛑 Miller server shutting down...")

    if file_watcher and file_watcher.is_running():
        logger.info("⏹️  Stopping file watcher...")
        file_watcher.stop()
        logger.info("✅ File watcher stopped")

    if not indexing_task.done():
        logger.info("⏳ Waiting for background indexing to complete...")
        await indexing_task

    logger.info("👋 Miller server shutdown complete")


# Create FastMCP server with lifespan handler
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# MCP Tool implementations (plain functions for testing)


def fast_search(
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

    Note: Indexing runs automatically in background via lifespan handler.
          Early searches may return empty results if indexing hasn't completed.
    """
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


def fast_goto(symbol_name: str) -> Optional[dict[str, Any]]:
    """
    Find symbol definition location.

    Args:
        symbol_name: Name of symbol to find

    Returns:
        Symbol location info, or None if not found
    """
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


def get_symbols(file_path: str) -> list[dict[str, Any]]:
    """
    Get file structure (symbols without full content).

    Args:
        file_path: Path to file

    Returns:
        List of symbols in file
    """
    path = Path(file_path)

    if not path.exists():
        return []

    # Read and extract
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
