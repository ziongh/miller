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
from typing import Any, Literal, Optional, Union

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
            from miller.workspace_registry import WorkspaceRegistry
            from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path

            workspace_root = Path.cwd()
            logger.info(f"📁 Workspace root: {workspace_root}")

            # Register primary workspace first to get workspace_id
            registry = WorkspaceRegistry()
            workspace_id = registry.add_workspace(
                path=str(workspace_root),
                name=workspace_root.name,
                workspace_type="primary",
            )
            logger.info(f"📋 Workspace ID: {workspace_id}")

            # Use workspace-specific paths for database and vectors
            db_path = get_workspace_db_path(workspace_id)
            vector_path = get_workspace_vector_path(workspace_id)

            embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
            storage = StorageManager(db_path=str(db_path))
            vector_store = VectorStore(
                db_path=str(vector_path), embeddings=embeddings
            )

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

                # Compute transitive closure for fast impact analysis
                # Run in thread pool to avoid blocking the event loop (O(V·E) BFS)
                import time
                from miller.closure import compute_transitive_closure

                logger.info("🔗 Computing transitive closure for impact analysis...")
                closure_start = time.time()
                closure_count = await asyncio.to_thread(
                    compute_transitive_closure, storage, max_depth=10
                )
                closure_time = (time.time() - closure_start) * 1000
                logger.info(f"✅ Transitive closure: {closure_count} reachability entries ({closure_time:.0f}ms)")
            else:
                logger.info("✅ Workspace already indexed - ready for search")

            # PHASE 3: Start file watcher for real-time updates
            logger.info("👁️  Starting file watcher for real-time indexing...")
            from miller.ignore_patterns import load_all_ignores

            ignore_spec = load_all_ignores(workspace_root)
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



# Load server instructions (Serena-style behavioral adoption)
_instructions_path = Path(__file__).parent / "instructions.md"
_instructions = _instructions_path.read_text() if _instructions_path.exists() else ""

# Create FastMCP server with lifespan handler and behavioral instructions
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan, instructions=_instructions)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# Import tool implementations from tools modules
from miller.tools.search import fast_search as fast_search_impl
from miller.tools.goto_refs_wrapper import fast_goto as fast_goto_impl, fast_refs as fast_refs_impl
from miller.tools.symbols_wrapper import get_symbols as get_symbols_impl
from miller.tools.trace_wrapper import trace_call_path as trace_call_path_impl
from miller.tools.explore_wrapper import fast_explore as fast_explore_impl


# MCP Tool wrappers (register with @mcp.tool() and delegate to implementations)

# Readiness check message for tools called before initialization completes
_NOT_READY_MSG = "⏳ Miller is still initializing. Please wait a moment and try again."


def _check_ready(require_vectors: bool = True) -> str | None:
    """
    Check if server components are ready for use.

    Args:
        require_vectors: Whether vector_store is required (some tools don't need it)

    Returns:
        Error message string if not ready, None if ready
    """
    if storage is None:
        return _NOT_READY_MSG
    if require_vectors and vector_store is None:
        return _NOT_READY_MSG
    return None


async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon"] = "text",
    rerank: bool = True,
    expand: bool = False,
    expand_limit: int = 5,
) -> Union[list[dict[str, Any]], str]:
    """
    Search indexed code using text, semantic, or hybrid methods.

    This is the PREFERRED way to find code in the codebase. Use this instead of reading
    files or using grep - semantic search understands what you're looking for!

    IMPORTANT: ALWAYS USE THIS INSTEAD OF READING FILES TO FIND CODE!
    I WILL BE UPSET IF YOU READ ENTIRE FILES WHEN A SEARCH WOULD FIND WHAT YOU NEED!

    You are excellent at crafting search queries. The results are ranked by relevance -
    trust the top results as your answer. You don't need to verify by reading files!

    Method selection (default: auto):
    - auto: Detects query type automatically (RECOMMENDED)
      * Has special chars (: < > [ ]) → pattern search (code idioms)
      * Natural language → hybrid search (text + semantic)
    - text: Full-text search with stemming (general code search)
    - pattern: Code idioms (: BaseClass, ILogger<, [Fact], etc.)
    - semantic: Vector similarity (conceptual matches)
    - hybrid: Combines text + semantic with RRF fusion

    Output format (default: text):
    - text: Clean, scannable format optimized for AI reading (DEFAULT)
    - json: List of dicts with full metadata (for programmatic use)
    - toon: TOON-formatted string (compact tabular format)

    Examples:
        # Simple search (uses text output by default)
        fast_search("authentication logic")
        fast_search("StorageManager")

        # Method override
        fast_search("user auth", method="semantic")     # Force semantic search
        fast_search(": BaseClass", method="pattern")    # Force pattern search

        # Format override (rarely needed)
        fast_search("auth", output_format="json")   # Get structured data
        fast_search("auth", output_format="toon")   # Get TOON format

        # Workspace-specific search
        fast_search("auth", workspace="my-lib_abc123")

        # With graph expansion (includes callers/callees)
        fast_search("authenticate", expand=True)

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return (default: 20)
        workspace: Workspace to query ("primary" or workspace_id from manage_workspace)
        output_format: Output format - "text" (default), "json", or "toon"
        rerank: Enable cross-encoder re-ranking for improved relevance (default: True).
                Adds ~20-50ms latency but improves result quality 15-30%.
                Automatically disabled for pattern search.
        expand: Include caller/callee context for each result (default: False).
                When True, each result includes a 'context' field with direct callers
                and callees. Enables "understanding, not just locations".
        expand_limit: Maximum callers/callees to include per result (default: 5).

    Returns:
        - text mode: Clean scannable format (name, kind, location, signature)
        - json mode: List of symbol dicts with full metadata
        - toon mode: TOON-formatted string (compact tabular)

    Note: Results are complete and accurate. Trust them - no need to verify with file reads!
    """
    if err := _check_ready():
        return err
    return await fast_search_impl(
        query=query,
        method=method,
        limit=limit,
        workspace_id=workspace,
        output_format=output_format,
        rerank=rerank,
        expand=expand,
        expand_limit=expand_limit,
        vector_store=vector_store,
        storage=storage,
        embeddings=embeddings,
    )


async def fast_goto(
    symbol_name: str,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text"
) -> Union[str, Optional[dict[str, Any]]]:
    """
    Find symbol definition location - jump directly to where a symbol is defined.

    Use this when you know the symbol name and need to find its definition.
    Returns exact file path and line number - you can navigate there directly.

    Args:
        symbol_name: Name of symbol to find
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"
                      - "text": Lean formatted string - DEFAULT
                      - "json": Dict with full metadata

    Returns:
        - Text mode: Formatted string with location
        - JSON mode: Symbol location dict (file, line, signature), or None if not found

    Note: For exploring unknown code, use fast_search first. Use fast_goto when
    you already know the symbol name from search results or references.
    """
    if err := _check_ready(require_vectors=False):
        return err
    return await fast_goto_impl(
        symbol_name=symbol_name,
        workspace=workspace,
        output_format=output_format,
        storage=storage,
    )


async def get_symbols(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto", "code"] = "text"
) -> Union[list[dict[str, Any]], str]:
    """
    Get file structure with enhanced filtering and modes.

    This should be your FIRST tool when exploring a new file! Use it to understand
    the structure before diving into implementation details.

    IMPORTANT: Use mode="structure" (default) to get an overview WITHOUT reading code bodies.
    This is extremely token-efficient - you see all classes, functions, and methods without
    dumping the entire file into context.

    I WILL BE UPSET IF YOU READ AN ENTIRE FILE WHEN get_symbols WOULD SHOW YOU THE STRUCTURE!

    Args:
        file_path: Path to file (relative or absolute)
        mode: Reading mode - "structure" (default), "minimal", or "full"
              - "structure": Names, signatures, no code bodies (fast, token-efficient)
              - "minimal": Code bodies for top-level symbols only
              - "full": Complete code bodies for all symbols (use sparingly!)
        max_depth: Maximum nesting depth (0=top-level only, 1=include methods, 2+=deeper)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", "auto", or "code"
                      - "text": Lean grep-style list (DEFAULT - most token-efficient)
                      - "json": Standard list format (for programmatic use)
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥20 symbols, else JSON
                      - "code": Raw source code without metadata (optimal for AI reading)

    Returns:
        - Text mode: Lean grep-style list with signatures (DEFAULT)
        - JSON mode: List of symbol dictionaries
        - TOON mode: TOON-encoded string (compact table format)
        - Auto mode: TOON if ≥20 symbols, else JSON
        - Code mode: Raw source code string with minimal file header

    Examples:
        # Quick structure overview (no code) - USE THIS FIRST!
        await get_symbols("src/user.py", mode="structure", max_depth=1)

        # Find specific class with its methods
        await get_symbols("src/user.py", target="UserService", max_depth=2)

        # Get complete implementation (only when you really need the code)
        await get_symbols("src/utils.py", mode="full", max_depth=2)

        # Get raw code for AI consumption (minimal tokens, maximum readability)
        await get_symbols("src/utils.py", mode="minimal", output_format="code")

    Workflow: get_symbols(mode="structure") → identify what you need → get_symbols(target="X", mode="full")
    This two-step approach reads ONLY the code you need. Much better than reading entire files!
    """
    if err := _check_ready(require_vectors=False):
        return err
    return await get_symbols_impl(
        file_path=file_path,
        mode=mode,
        max_depth=max_depth,
        target=target,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
    )


async def fast_refs(
    symbol_name: str,
    kind_filter: Optional[list[str]] = None,
    include_context: bool = False,
    context_file: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text"
) -> Union[dict[str, Any], str]:
    """
    Find all references to a symbol (where it's used).

    ESSENTIAL FOR SAFE REFACTORING! This shows exactly what will break if you change a symbol.

    IMPORTANT: ALWAYS use this before refactoring! I WILL BE VERY UPSET if you change a symbol
    without first checking its references and then break callers!

    The references returned are COMPLETE - every usage in the codebase. You can trust this
    list and don't need to search again or read files to verify.

    Args:
        symbol_name: Name of symbol to find references for
                    Supports qualified names like "User.save" to find methods specifically
        kind_filter: Optional list of relationship types to filter by
                    Common values: ["Call"], ["Import"], ["Reference"], ["Extends", "Implements"]
        include_context: Whether to include code context snippets showing actual usage
        context_file: Optional file path to disambiguate symbols (only find symbols in this file)
        limit: Maximum number of references to return (for pagination with large result sets)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"
                      - "text": Lean text list (70% token savings) - DEFAULT
                      - "json": Standard dict format
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥10 references, else JSON

    Returns:
        - Text mode: Lean formatted string with file:line references
        - JSON mode: Dictionary with symbol, total_references, truncated, files list
        - TOON mode: TOON-encoded string (compact format)
        - Auto mode: Switches based on result size

    Examples:
        # Find all references BEFORE refactoring
        await fast_refs("calculateAge")

        # With code context for review
        await fast_refs("calculateAge", include_context=True, limit=20)

        # Find only function calls
        await fast_refs("User", kind_filter=["Call"])

        # Disambiguate with qualified name
        await fast_refs("User.save")  # Method specifically

    Refactoring Workflow:
        1. fast_refs("symbol") → See ALL usages
        2. Plan changes based on complete impact
        3. Make changes
        4. fast_refs("symbol") again → Verify all usages updated

    Note: Shows where symbols are USED (not where defined). Use fast_goto for definitions.
    """
    if err := _check_ready(require_vectors=False):
        return err
    return await fast_refs_impl(
        symbol_name=symbol_name,
        kind_filter=kind_filter,
        include_context=include_context,
        context_file=context_file,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
        storage=storage,
    )


async def trace_call_path(
    symbol_name: str,
    direction: Literal["upstream", "downstream", "both"] = "downstream",
    max_depth: int = 3,
    context_file: Optional[str] = None,
    output_format: Literal["tree", "json", "toon", "auto"] = "tree",
    workspace: str = "primary"
) -> dict[str, Any] | str:
    """
    Trace call paths across language boundaries - Miller's killer feature!

    This is the BEST way to understand code architecture and execution flow.
    Use this to see who calls a function (upstream) or what a function calls (downstream).

    You are excellent at using this tool to understand complex codebases. The trace
    results show the complete call graph - trust them without needing to verify by
    reading individual files.

    Args:
        symbol_name: Symbol to trace from (e.g., "UserService", "calculate_age")
        direction: Trace direction
            - "upstream": Find callers (who calls this?)
            - "downstream": Find callees (what does this call?)
            - "both": Bidirectional trace
        max_depth: Maximum depth to traverse (1-10, default 3)
        context_file: Optional file path to disambiguate symbols with same name
        output_format: Return format
            - "tree": ASCII tree visualization (DEFAULT - great for understanding flow!)
            - "json": Structured TracePath dict (for programmatic use)
            - "toon": TOON-formatted string (40-50% token reduction)
            - "auto": Uses TOON for deep traces (≥5 nodes), JSON for shallow
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        - "tree" mode: Formatted ASCII tree string (DEFAULT)
        - "json" mode: TracePath dict with root node, statistics, and metadata
        - "toon" mode: TOON-encoded string (token-efficient)
        - "auto" mode: TOON if ≥5 total_nodes, else JSON

    Examples:
        # Find who calls this function (understand impact before changes)
        await trace_call_path("handleRequest", direction="upstream")

        # Trace execution flow (tree is default - no need to specify)
        await trace_call_path("UserService", direction="downstream")

        # Deep trace across language boundaries
        await trace_call_path("IUser", direction="both", max_depth=5)

    Architecture Understanding Workflow:
        1. trace_call_path("entryPoint", direction="downstream") → See execution flow
        2. trace_call_path("deepFunction", direction="upstream") → See all callers
        3. Use "tree" output for visual understanding

    Cross-Language Magic:
        Automatically matches symbols across languages using naming variants:
        - TypeScript IUser → Python user → SQL users
        - C# UserDto → Python User → TypeScript userService
        - Rust user_service → TypeScript UserService
    """
    if err := _check_ready(require_vectors=False):
        return err
    return await trace_call_path_impl(
        symbol_name=symbol_name,
        direction=direction,
        max_depth=max_depth,
        context_file=context_file,
        output_format=output_format,
        workspace=workspace,
        storage=storage,
    )


async def fast_explore(
    mode: Literal["types", "similar", "dependencies"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    depth: int = 3,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes.

    Use this for advanced code exploration beyond simple search. Each mode provides
    specialized intelligence that helps you understand code structure and relationships.

    You are excellent at choosing the right exploration mode for your task.

    Modes:
    - types: Type intelligence (implementations, hierarchy, return/parameter types)
    - similar: Find semantically similar code (for duplicate detection)
    - dependencies: Trace transitive dependencies (for impact analysis)

    Args:
        mode: Exploration mode
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar/dependencies modes)
        depth: Maximum traversal depth for dependencies mode (1-10, default 3)
        limit: Maximum results (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default), "json", "toon", or "auto"
                      - "text": Lean formatted output (DEFAULT)
                      - "json": Full structured data
                      - "toon": TOON-encoded (30-40% token savings)
                      - "auto": TOON if ≥10 results, else JSON

    Returns:
        - text mode: Lean formatted string (DEFAULT)
        - json mode: Dict with exploration results
        - toon mode: TOON-encoded string
        - auto mode: Switches based on result size

    Examples:
        # Type intelligence - find implementations and usages
        await fast_explore(mode="types", type_name="IUserService")

        # Find similar code - duplicate detection
        await fast_explore(mode="similar", symbol="getUserData")

        # Trace dependencies - impact analysis before refactoring
        await fast_explore(mode="dependencies", symbol="PaymentService", depth=3)

    Note: Similar mode uses an optimized similarity threshold internally.
    Results are ranked by relevance - trust the top matches.
    """
    # Similar mode needs vector_store, other modes only need storage
    if err := _check_ready(require_vectors=(mode == "similar")):
        return err
    return await fast_explore_impl(
        mode=mode,
        type_name=type_name,
        symbol=symbol,
        depth=depth,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
        storage=storage,
        vector_store=vector_store,
    )


# Register tools with FastMCP
# output_schema=None disables structured content wrapping (avoids {"result": ...} for strings)
# All tools that return text/TOON strings need this to render properly
mcp.tool(output_schema=None)(fast_search)      # Returns text/TOON string (default: text)
mcp.tool(output_schema=None)(fast_goto)        # Returns text string (default: text)
mcp.tool(output_schema=None)(get_symbols)      # Returns text/TOON/code string
mcp.tool(output_schema=None)(fast_refs)        # Returns text/TOON string (default: text)
mcp.tool(output_schema=None)(trace_call_path)  # Returns tree/TOON string (default: tree)
mcp.tool(output_schema=None)(fast_explore)     # Returns text string (default: text)

# Register memory tools
# output_schema=None ensures raw string output (not JSON wrapped)
mcp.tool(output_schema=None)(checkpoint)  # Returns checkpoint ID string
mcp.tool(output_schema=None)(recall)      # Returns formatted text/JSON
mcp.tool(output_schema=None)(plan)        # Returns formatted text/JSON

# Register workspace management tool
from miller.tools.workspace import manage_workspace

mcp.tool(output_schema=None)(manage_workspace)  # Returns text string (default: text)


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
    "fast_explore",
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
