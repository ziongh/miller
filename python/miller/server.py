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
            # CRITICAL: Yield to event loop BEFORE heavy imports
            # Python imports are synchronous and block the event loop. Even though this is an
            # async task, importing torch/sentence-transformers blocks the thread for 3+ seconds.
            # This delay ensures the MCP handshake completes BEFORE we start blocking imports.
            await asyncio.sleep(0.1)  # 100ms delay - lets handshake complete first

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
                     Get workspace IDs from manage_workspace(operation="list")

    Returns:
        List of matching symbols with scores and metadata

    Indexing:
        - Primary workspace: Indexed automatically in background after server starts
        - Reference workspaces: Must be added via manage_workspace(operation="add")
        - Manual indexing: Use manage_workspace(operation="index", force=True)

    Note: Early searches may return empty results if initial indexing hasn't completed.
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


async def get_symbols(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary"
) -> list[dict[str, Any]]:
    """
    Get file structure with enhanced filtering and modes.

    Miller's enhanced get_symbols - better than Julie's with Python/ML capabilities.

    Args:
        file_path: Path to file (relative or absolute)
        mode: Reading mode - "structure" (default), "minimal", or "full"
              - "structure": Names, signatures, no code bodies (fast, token-efficient)
              - "minimal": Code bodies for top-level symbols only
              - "full": Complete code bodies for all symbols
        max_depth: Maximum nesting depth (0=top-level only, 1=include methods, 2+=deeper)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        List of symbol dictionaries with metadata based on mode

    Examples:
        # Quick structure overview (no code)
        await get_symbols("src/user.py", mode="structure", max_depth=1)

        # Find specific class with its methods
        await get_symbols("src/user.py", target="UserService", max_depth=2)

        # Get complete implementation
        await get_symbols("src/utils.py", mode="full", max_depth=2)
    """
    from miller.tools.symbols import get_symbols_enhanced

    return await get_symbols_enhanced(
        file_path=file_path,
        mode=mode,
        max_depth=max_depth,
        target=target,
        limit=limit,
        workspace=workspace
    )


async def fast_refs(
    symbol_name: str,
    kind_filter: Optional[list[str]] = None,
    include_context: bool = False,
    context_file: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary"
) -> dict[str, Any]:
    """
    Find all references to a symbol (where it's used).

    Essential for safe refactoring - shows exactly what will break if you change a symbol.

    Args:
        symbol_name: Name of symbol to find references for
                    Supports qualified names like "User.save" to find methods specifically
        kind_filter: Optional list of relationship types to filter by
                    Common values: ["Call"], ["Import"], ["Reference"], ["Extends", "Implements"]
        include_context: Whether to include code context snippets showing actual usage
        context_file: Optional file path to disambiguate symbols (only find symbols in this file)
        limit: Maximum number of references to return (for pagination with large result sets)
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        Dictionary with:
        - symbol: str (name queried)
        - total_references: int (total count, even if limited)
        - truncated: bool (if results were limited)
        - files: list of {path, references_count, references: [{line, kind, context}]}

    Examples:
        # Find all references
        await fast_refs("calculateAge")

        # With code context for review
        await fast_refs("calculateAge", include_context=True, limit=20)

        # Find only function calls
        await fast_refs("User", kind_filter=["Call"])

        # Disambiguate with qualified name
        await fast_refs("User.save")  # Method specifically

    Note: Shows where symbols are USED (not where defined). Use fast_goto for definitions.
    """
    from miller.tools.refs import find_references
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry
    from miller.storage import StorageManager

    # Get workspace-specific storage
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {
                "symbol": symbol_name,
                "total_references": 0,
                "files": [],
                "error": f"Workspace '{workspace}' not found"
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        # Use primary workspace storage
        workspace_storage = storage

    try:
        result = find_references(
            storage=workspace_storage,
            symbol_name=symbol_name,
            kind_filter=kind_filter,
            include_context=include_context,
            context_file=context_file,
            limit=limit
        )
        return result
    finally:
        # Close workspace storage if it's not the default
        if workspace != "primary":
            workspace_storage.close()


# Import trace tool
from miller.tools.trace import trace_call_path as trace_impl

async def trace_call_path(
    symbol_name: str,
    direction: Literal["upstream", "downstream", "both"] = "downstream",
    max_depth: int = 3,
    context_file: Optional[str] = None,
    output_format: Literal["json", "tree"] = "json",
    workspace: str = "primary"
) -> dict[str, Any] | str:
    """
    Trace call paths across language boundaries using naming variants.

    Miller's killer feature - traces execution flow across TypeScript → Python → SQL
    using intelligent naming variant matching (UserService → user_service → users).

    Args:
        symbol_name: Symbol to trace from (e.g., "UserService", "calculate_age")
        direction: Trace direction
            - "upstream": Find callers (who calls this?)
            - "downstream": Find callees (what does this call?)
            - "both": Bidirectional trace
        max_depth: Maximum depth to traverse (1-10, default 3)
        context_file: Optional file path to disambiguate symbols with same name
        output_format: Return format
            - "json": Structured TracePath dict (for programmatic use)
            - "tree": ASCII tree visualization (for human reading)
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        TracePath dict with root node, statistics, and metadata if json format.
        Formatted ASCII tree string if tree format.

    Examples:
        # Find who calls this function
        await trace_call_path("handleRequest", direction="upstream")

        # Trace execution flow with visualization
        await trace_call_path("UserService", direction="downstream", output_format="tree")

        # Deep trace across language boundaries
        await trace_call_path("IUser", direction="both", max_depth=5)

    Cross-Language Magic:
        Automatically matches symbols across languages using naming variants:
        - TypeScript IUser → Python user → SQL users
        - C# UserDto → Python User → TypeScript userService
        - Rust user_service → TypeScript UserService

    Note: Currently uses exact name matching. Variant matching coming soon!
    """
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry

    # Get workspace-specific storage
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {
                "symbol": symbol_name,
                "error": f"Workspace '{workspace}' not found"
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        # Use primary workspace storage
        workspace_storage = storage

    try:
        result = await trace_impl(
            storage=workspace_storage,
            symbol_name=symbol_name,
            direction=direction,
            max_depth=max_depth,
            context_file=context_file,
            output_format=output_format,
            workspace=workspace,
        )
        return result
    finally:
        # Close workspace storage if it's not the default
        if workspace != "primary":
            workspace_storage.close()


# Register tools with FastMCP
mcp.tool()(fast_search)
mcp.tool()(fast_goto)
mcp.tool()(get_symbols)
mcp.tool()(fast_refs)
mcp.tool()(trace_call_path)

# Register memory tools
mcp.tool()(checkpoint)
mcp.tool()(recall)
mcp.tool()(plan)

# Register workspace management tool
from miller.tools.workspace import manage_workspace

mcp.tool()(manage_workspace)


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
    "fast_refs",
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
