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


# Declare Miller components as module-level globals (initialized in background task)
# These are None during module import to avoid blocking the MCP handshake
storage = None
vector_store = None
embeddings = None
scanner = None
workspace_root = None


# Define lifespan handler (Julie pattern - handshake first, then background work)
@asynccontextmanager
async def lifespan(_app):
    """
    FastMCP lifespan handler - startup and shutdown hooks.

    Startup:
      1. Server becomes ready instantly (MCP handshake completes)
      2. Background task initializes components (non-blocking)
      3. Background task checks if indexing needed and runs if stale
      4. File watcher starts for real-time updates

    Shutdown: Stop file watcher and cleanup

    This matches Julie's pattern: instant handshake, background initialization + indexing.
    """
    global storage, vector_store, embeddings, scanner, workspace_root

    # File watcher reference (initialized by background task)
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

    async def background_initialization_and_indexing():
        """
        Background task that initializes components, indexes workspace, and starts file watcher.

        Runs completely in background so MCP handshake completes immediately.
        """
        nonlocal file_watcher
        global storage, vector_store, embeddings, scanner, workspace_root

        try:
            # PHASE 1: Initialize components (in background, doesn't block handshake)
            logger.info("🔧 Initializing Miller components in background...")

            # Lazy imports - only load heavy ML libraries in background task
            from miller.embeddings import EmbeddingManager, VectorStore
            from miller.storage import StorageManager
            from miller.workspace import WorkspaceScanner

            embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
            storage = StorageManager(db_path=".miller/indexes/symbols.db")
            vector_store = VectorStore(
                db_path=".miller/indexes/vectors.lance", embeddings=embeddings
            )

            workspace_root = Path.cwd()
            logger.info(f"📁 Workspace root: {workspace_root}")

            scanner = WorkspaceScanner(
                workspace_root=workspace_root, storage=storage, embeddings=embeddings, vector_store=vector_store
            )
            logger.info("✅ Miller components initialized and ready")

            # PHASE 2: Check if indexing needed and run if stale (uses hashes + mtime)
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

            # PHASE 3: Start file watcher for real-time updates
            logger.info("👁️  Starting file watcher for real-time indexing...")
            from miller.ignore_patterns import load_gitignore

            ignore_spec = load_gitignore(workspace_root)
            pattern_strings = {p.pattern for p in ignore_spec.patterns}
            file_watcher = FileWatcher(
                workspace_path=workspace_root,
                indexing_callback=on_files_changed,
                ignore_patterns=pattern_strings,
                debounce_delay=0.2,
            )
            file_watcher.start()
            logger.info("✅ File watcher active - workspace changes will be indexed automatically")

        except Exception as e:
            logger.error(f"❌ Background initialization/indexing failed: {e}", exc_info=True)

    # Spawn background task immediately (server becomes ready without waiting)
    logger.info("🚀 Spawning background initialization task...")
    init_task = asyncio.create_task(background_initialization_and_indexing())
    logger.info("✅ Server ready for MCP handshake (initialization running in background)")

    yield  # Server runs here - client sees "Connected" immediately

    # SHUTDOWN: Stop file watcher and wait for background task
    logger.info("🛑 Miller server shutting down...")

    if file_watcher and file_watcher.is_running():
        logger.info("⏹️  Stopping file watcher...")
        file_watcher.stop()
        logger.info("✅ File watcher stopped")

    if not init_task.done():
        logger.info("⏳ Waiting for background initialization to complete...")
        await init_task

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
    workspace_id: Optional[str] = None,
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

        # Workspace-specific search
        fast_search("auth", workspace_id="my-lib_abc123")  # Search specific workspace

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return
        workspace_id: Optional workspace ID to search (defaults to primary workspace)

    Returns:
        List of matching symbols with scores and metadata

    Note: Indexing runs automatically in background via lifespan handler.
          Early searches may return empty results if indexing hasn't completed.
    """

    # If workspace_id specified, use that workspace's vector store
    if workspace_id:
        from miller.workspace_paths import get_workspace_vector_path
        from miller.workspace_registry import WorkspaceRegistry

        # Verify workspace exists
        registry = WorkspaceRegistry()
        workspace = registry.get_workspace(workspace_id)

        if not workspace:
            # Return empty results for non-existent workspace
            return []

        # Open workspace-specific vector store
        from miller.embeddings import VectorStore

        workspace_vector_path = get_workspace_vector_path(workspace_id)
        workspace_vector_store = VectorStore(
            db_path=str(workspace_vector_path), embeddings=embeddings
        )

        # Search in workspace-specific store
        results = workspace_vector_store.search(query, method=method, limit=limit)
    else:
        # Use default vector store (primary workspace)
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

# Register workspace management tool
from miller.tools.workspace import manage_workspace

mcp.tool()(manage_workspace)


# Test helper function for indexing files
def index_file(file_path: str) -> bool:
    """
    Index a single file (test helper function).

    This is a synchronous wrapper for testing. In production, indexing
    happens automatically via the background task in the lifespan handler.

    Args:
        file_path: Absolute path to file

    Returns:
        True if successful, False otherwise
    """
    from pathlib import Path

    # Ensure components are initialized
    if storage is None or embeddings is None or vector_store is None:
        # Initialize components synchronously for testing
        from miller.embeddings import EmbeddingManager, VectorStore
        from miller.storage import StorageManager

        globals()["embeddings"] = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
        globals()["storage"] = StorageManager(db_path=".miller/indexes/symbols.db")
        globals()["vector_store"] = VectorStore(
            db_path=".miller/indexes/vectors.lance", embeddings=globals()["embeddings"]
        )

    if miller_core is None:
        return False

    try:
        file_path_obj = Path(file_path)
        workspace_root = Path.cwd()

        # Convert to relative Unix-style path (or use absolute if outside workspace)
        try:
            relative_path = str(file_path_obj.relative_to(workspace_root)).replace("\\", "/")
        except ValueError:
            # File is outside workspace (e.g., temp test directory)
            # Use filename or absolute path for testing
            relative_path = file_path_obj.name

        # Read file
        content = file_path_obj.read_text(encoding="utf-8")

        # Detect language
        language = miller_core.detect_language(str(file_path_obj))
        if not language:
            return False

        # Extract symbols
        result = miller_core.extract_file(content, language, relative_path)

        # Compute hash
        import hashlib

        file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Store file metadata
        storage.add_file(
            file_path=relative_path, language=language, content=content, hash=file_hash, size=len(content)
        )

        # Store symbols
        if result.symbols:
            storage.add_symbols_batch(result.symbols)

            # Generate embeddings and store in vector DB
            embeddings_list = []
            for sym in result.symbols:
                # Create searchable text for embedding
                search_text = f"{sym.name} {sym.kind}"
                if sym.signature:
                    search_text += f" {sym.signature}"
                if sym.doc_comment:
                    search_text += f" {sym.doc_comment}"

                vec = globals()["embeddings"].embed_query(search_text)
                embeddings_list.append(vec)

            # Add to vector store (convert list to numpy array)
            import numpy as np

            vectors_array = np.array(embeddings_list, dtype=np.float32)
            vector_store.add_symbols(result.symbols, vectors_array)

        # Store identifiers
        if result.identifiers:
            storage.add_identifiers_batch(result.identifiers)

        # Store relationships
        if result.relationships:
            storage.add_relationships_batch(result.relationships)

        return True

    except Exception as e:
        logger.error(f"Failed to index file {file_path}: {e}", exc_info=True)
        return False


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
    "index_file",  # Test helper
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
