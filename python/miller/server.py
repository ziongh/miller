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



# Load server instructions (Serena-style behavioral adoption)
_instructions_path = Path(__file__).parent / "instructions.md"
_instructions = _instructions_path.read_text() if _instructions_path.exists() else ""

# Create FastMCP server with lifespan handler and behavioral instructions
# Components will be initialized in lifespan startup (after handshake)
mcp = FastMCP("Miller Code Intelligence Server", lifespan=lifespan, instructions=_instructions)
logger.info("✓ FastMCP server created (components will initialize post-handshake)")


# MCP Tool implementations (plain functions for testing)


async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    workspace_id: Optional[str] = None,
    output_format: Literal["text", "json", "toon"] = "text",
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
        fast_search("auth", workspace_id="my-lib_abc123")

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return (default: 20)
        workspace_id: Optional workspace ID to search (defaults to primary workspace)
                     Get workspace IDs from manage_workspace(operation="list")
        output_format: Output format - "text" (default), "json", or "toon"

    Returns:
        - text mode: Clean scannable format (name, kind, location, signature)
        - json mode: List of symbol dicts with full metadata
        - toon mode: TOON-formatted string (compact tabular)

    Note: Results are complete and accurate. Trust them - no need to verify with file reads!
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

        # Hydrate with full data from workspace-specific SQLite
        from miller.storage import StorageManager
        from miller.workspace_paths import get_workspace_db_path

        workspace_db_path = get_workspace_db_path(workspace_id)
        if workspace_db_path.exists():
            workspace_storage = StorageManager(db_path=str(workspace_db_path))
            results = _hydrate_search_results(results, workspace_storage)
    else:
        # Use default vector store (primary workspace)
        results = vector_store.search(query, method=method, limit=limit)

        # Hydrate with full data from primary workspace SQLite
        if storage is not None:
            results = _hydrate_search_results(results, storage)

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
                "code_context": r.get("code_context"),  # For grep-style output
            }
        )

    # Apply output format
    if output_format == "text":
        return _format_search_as_text(formatted, query=query)
    elif output_format == "toon":
        from miller.toon_types import encode_toon
        return encode_toon(formatted)
    else:  # json
        return formatted


def _format_goto_as_text(symbol_name: str, result: Optional[dict[str, Any]]) -> str:
    """Format goto result as lean text output.

    Output format:
    ```
    Found 1 definition for "symbol_name":

    file.py:42 (function)
      def symbol_name(args)
    ```
    """
    if not result:
        return f'No definition found for "{symbol_name}".'

    file_path = result.get("file_path", "?")
    line = result.get("start_line", 0)
    kind = result.get("kind", "symbol")
    signature = result.get("signature", "")

    output = [f'Found 1 definition for "{symbol_name}":', ""]
    output.append(f"{file_path}:{line} ({kind})")
    if signature:
        # Truncate long signatures
        sig = signature.split("\n")[0]
        if len(sig) > 80:
            sig = sig[:77] + "..."
        output.append(f"  {sig}")

    return "\n".join(output)


async def fast_goto(
    symbol_name: str,
    output_format: Literal["text", "json"] = "text"
) -> Union[str, Optional[dict[str, Any]]]:
    """
    Find symbol definition location - jump directly to where a symbol is defined.

    Use this when you know the symbol name and need to find its definition.
    Returns exact file path and line number - you can navigate there directly.

    Args:
        symbol_name: Name of symbol to find
        output_format: Output format - "text" (default) or "json"
                      - "text": Lean formatted string - DEFAULT
                      - "json": Dict with full metadata

    Returns:
        - Text mode: Formatted string with location
        - JSON mode: Symbol location dict (file, line, signature), or None if not found

    Note: For exploring unknown code, use fast_search first. Use fast_goto when
    you already know the symbol name from search results or references.
    """
    # Query SQLite for exact match
    sym = storage.get_symbol_by_name(symbol_name)

    result = None
    if sym:
        result = {
            "name": sym["name"],
            "kind": sym["kind"],
            "file_path": sym["file_path"],
            "start_line": sym["start_line"],
            "end_line": sym["end_line"],
            "signature": sym["signature"],
            "doc_comment": sym["doc_comment"],
        }

    if output_format == "text":
        return _format_goto_as_text(symbol_name, result)
    else:
        return result


async def get_symbols(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    output_format: Literal["json", "toon", "auto", "code"] = "json"
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
        output_format: Output format - "json" (default), "toon", "auto", or "code"
                      - "json": Standard list format
                      - "toon": TOON-encoded string (30-40% token reduction)
                      - "auto": TOON if ≥20 symbols, else JSON
                      - "code": Raw source code without metadata (optimal for AI reading)

    Returns:
        - JSON mode: List of symbol dictionaries
        - TOON mode: TOON-encoded string (compact table format)
        - Auto mode: Switches based on result count
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
    from miller.tools.symbols import get_symbols_enhanced
    from miller.toon_types import encode_toon, should_use_toon

    result = await get_symbols_enhanced(
        file_path=file_path,
        mode=mode,
        max_depth=max_depth,
        target=target,
        limit=limit,
        workspace=workspace
    )

    # Handle "code" output format - raw source code without metadata
    # Return plain string (same as TOON format)
    if output_format == "code":
        return _format_code_output(file_path, result)

    # Apply TOON encoding if requested
    # Auto mode: use TOON if ≥20 symbols (indicates large file)
    # DEFAULT_TOON_CONFIG has threshold=20, which is perfect for get_symbols
    if should_use_toon(output_format, len(result)):
        return encode_toon(result)
    else:
        return result


def _format_code_output(file_path: str, symbols: list[dict[str, Any]]) -> str:
    """Format symbols as raw code output - optimal for AI reading.

    Returns code bodies separated by blank lines with a minimal file header.
    This format has zero metadata overhead - just the code the agent needs.

    Only includes meaningful code definitions (functions, classes, methods, etc.),
    NOT imports or standalone variables.

    Args:
        file_path: Path to file (for header)
        symbols: List of symbol dicts with optional 'code_body' field

    Returns:
        Formatted string: "// === file_path ===\\n\\n<code1>\\n\\n<code2>..."
    """
    from pathlib import Path

    # Symbol kinds that represent actual code definitions worth showing
    # Excludes imports, variables, and other non-definition symbols
    CODE_DEFINITION_KINDS = {
        "Function", "Method", "Class", "Struct", "Interface", "Trait",
        "Enum", "Constructor", "Module", "Namespace", "Type",
        # Lowercase variants for compatibility
        "function", "method", "class", "struct", "interface", "trait",
        "enum", "constructor", "module", "namespace", "type",
    }

    # Minimal file header
    output = f"// === {Path(file_path).name} ===\n\n"

    # First pass: collect all code definition symbols with their line ranges
    code_symbols = []
    for symbol in symbols:
        kind = symbol.get("kind", "")
        if kind in CODE_DEFINITION_KINDS:
            code_symbols.append({
                "start_line": symbol.get("start_line", 0),
                "end_line": symbol.get("end_line", 0),
                "code_body": symbol.get("code_body"),
                "parent_id": symbol.get("parent_id"),
            })

    # Sort by start_line to process in order
    code_symbols.sort(key=lambda s: s["start_line"])

    # Second pass: filter out nested definitions (those contained within another symbol's range)
    # This handles cases where parent_id isn't set but the symbol is clearly nested
    seen_bodies = set()
    code_bodies = []
    covered_ranges = []  # List of (start, end) tuples

    for symbol in code_symbols:
        start = symbol["start_line"]
        end = symbol["end_line"]
        code_body = symbol["code_body"]
        parent_id = symbol["parent_id"]

        # Skip if explicitly has a parent
        if parent_id:
            continue

        # Skip if this symbol falls entirely within an already-added symbol's range
        # (i.e., it's a nested definition even without parent_id)
        is_nested = any(
            covered_start < start and end < covered_end
            for covered_start, covered_end in covered_ranges
        )
        if is_nested:
            continue

        if code_body and code_body not in seen_bodies:
            seen_bodies.add(code_body)
            code_bodies.append(code_body)
            covered_ranges.append((start, end))

    # Join code bodies with blank lines
    output += "\n\n".join(code_bodies)

    # Ensure single newline at end
    return output.rstrip() + "\n"


def _hydrate_search_results(
    search_results: list[dict[str, Any]], storage: "StorageManager"
) -> list[dict[str, Any]]:
    """Hydrate search results with full symbol data from SQLite.

    Vector search returns lean results (id, name, kind, score).
    This function enriches them with full data from SQLite,
    including code_context for grep-style output.

    Args:
        search_results: Lean results from vector search
        storage: StorageManager instance for SQLite lookups

    Returns:
        Hydrated results with code_context and other fields from SQLite.
        Preserves search score (not storage score).
    """
    hydrated = []
    for result in search_results:
        symbol_id = result.get("id")
        search_score = result.get("score", 0.0)

        if symbol_id:
            # Fetch full symbol data from SQLite
            full_symbol = storage.get_symbol_by_id(symbol_id)
            if full_symbol:
                # Merge: use storage data but preserve search score
                full_symbol["score"] = search_score
                hydrated.append(full_symbol)
                continue

        # Fallback: keep original result if hydration fails
        hydrated.append(result)

    return hydrated


def _format_search_as_text(results: list[dict[str, Any]], query: str = "") -> str:
    """Format search results as grep-style text output.

    Output format (inspired by Julie's lean format):
    ```
    N matches for "query":

    src/file.py:42
      41: # context before
      42→ def matched_line():
      43:     # context after

    src/other.py:100
      99: # context
      100→ another_match
    ```

    Benefits over JSON/TOON:
    - 80% fewer tokens than JSON
    - 60% fewer tokens than TOON
    - Zero parsing overhead - just read the text
    - Grep-style output familiar to developers

    Args:
        results: List of search result dicts with file_path, start_line, code_context
        query: The search query (for header)

    Returns:
        Grep-style formatted text string
    """
    if not results:
        return f'No matches for "{query}".' if query else "No results found."

    output = []

    # Header with count and query
    count = len(results)
    if query:
        match_word = "match" if count == 1 else "matches"
        output.append(f'{count} {match_word} for "{query}":')
    else:
        output.append(f"{count} results:")
    output.append("")  # Blank line after header

    # Each result: file:line header + indented code context
    for r in results:
        file_path = r.get("file_path", "?")
        start_line = r.get("start_line", 0)
        code_context = r.get("code_context")
        signature = r.get("signature", "")

        # File:line header
        output.append(f"{file_path}:{start_line}")

        # Indented code context (preferred) or signature (fallback)
        if code_context:
            for line in code_context.split("\n"):
                output.append(f"  {line}")
        elif signature:
            # Fallback to signature if no code_context
            output.append(f"  {signature}")

        output.append("")  # Blank line between results

    # Trim trailing blank line
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


def _format_refs_as_text(result: dict[str, Any]) -> str:
    """Format references result as lean text output.

    Output format:
    ```
    14 references to "fast_search":

    Definition:
      python/miller/server.py:201 (function) → async def fast_search(...)

    References (13):
      python/tests/test_server.py:32 (calls)
      python/tests/test_server.py:66 (calls)
      ...
    ```
    """
    symbol = result.get("symbol", "?")
    total = result.get("total_references", 0)
    files = result.get("files", [])

    if total == 0:
        return f'No references found for "{symbol}".'

    output = [f'{total} references to "{symbol}":', ""]

    # Collect all references across files
    for file_info in files:
        file_path = file_info.get("path", "?")
        refs = file_info.get("references", [])

        for ref in refs:
            line = ref.get("line", 0)
            kind = ref.get("kind", "reference")
            output.append(f"  {file_path}:{line} ({kind})")

    return "\n".join(output)


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
        raw_result = find_references(
            storage=workspace_storage,
            symbol_name=symbol_name,
            kind_filter=kind_filter,
            include_context=include_context,
            context_file=context_file,
            limit=limit
        )

        # Use Julie's simple pattern: same structure for both JSON and TOON
        # fast_refs already returns TOON-friendly nested dicts
        from miller.toon_utils import create_toonable_result

        # Simple helper decides text vs TOON vs JSON
        return create_toonable_result(
            json_data=raw_result,           # Full result as-is
            toon_data=raw_result,           # Same structure - TOON handles nesting
            output_format=output_format,
            auto_threshold=10,              # 10+ refs → TOON
            result_count=raw_result.get("total_references", 0),
            tool_name="fast_refs",
            text_formatter=_format_refs_as_text,  # Lean text output
        )
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
        # For tree format, return directly (it's already a formatted string)
        if output_format == "tree":
            return await trace_impl(
                storage=workspace_storage,
                symbol_name=symbol_name,
                direction=direction,
                max_depth=max_depth,
                context_file=context_file,
                output_format="tree",
                workspace=workspace,
            )

        # For TOON/auto modes, get JSON first then encode
        result = await trace_impl(
            storage=workspace_storage,
            symbol_name=symbol_name,
            direction=direction,
            max_depth=max_depth,
            context_file=context_file,
            output_format="json",
            workspace=workspace,
        )

        # Use Julie's simple pattern: TOON handles nested structures natively
        from miller.toon_utils import create_toonable_result

        # Simple helper decides TOON vs JSON (same data, TOON handles nesting)
        return create_toonable_result(
            json_data=result,               # Full result as-is
            toon_data=result,               # Same - TOON handles nested TraceNodes
            output_format=output_format,
            auto_threshold=5,               # 5+ nodes → TOON
            result_count=result.get("total_nodes", 0),
            tool_name="trace_call_path"
        )
    finally:
        # Close workspace storage if it's not the default
        if workspace != "primary":
            workspace_storage.close()


def _format_explore_as_text(result: dict[str, Any]) -> str:
    """Format type exploration result as lean text output.

    Output format:
    ```
    Type intelligence for "IUserService":

    Implementations (3):
      src/services/user.py:15 → class UserService
      src/services/admin.py:22 → class AdminService

    Returns this type (2):
      src/factory.py:30 → def create_service() -> IUserService

    Takes as parameter (1):
      src/api/auth.py:45 → def login(service: IUserService)
    ```
    """
    type_name = result.get("type_name", "?")
    total = result.get("total_found", 0)

    if total == 0:
        return f'No type information found for "{type_name}".'

    output = [f'Type intelligence for "{type_name}":', ""]

    # Implementations
    implementations = result.get("implementations", [])
    if implementations:
        output.append(f"Implementations ({len(implementations)}):")
        for impl in implementations:
            file_path = impl.get("file_path", "?")
            line = impl.get("start_line", 0)
            sig = impl.get("signature", impl.get("name", "?"))
            # Truncate signature
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Returns
    returns = result.get("returns", [])
    if returns:
        output.append(f"Returns this type ({len(returns)}):")
        for ret in returns:
            file_path = ret.get("file_path", "?")
            line = ret.get("start_line", 0)
            sig = ret.get("signature", ret.get("name", "?"))
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Parameters
    parameters = result.get("parameters", [])
    if parameters:
        output.append(f"Takes as parameter ({len(parameters)}):")
        for param in parameters:
            file_path = param.get("file_path", "?")
            line = param.get("start_line", 0)
            sig = param.get("signature", param.get("name", "?"))
            if len(sig) > 60:
                sig = sig[:57] + "..."
            output.append(f"  {file_path}:{line} → {sig}")
        output.append("")

    # Hierarchy
    hierarchy = result.get("hierarchy", {})
    parents = hierarchy.get("parents", [])
    children = hierarchy.get("children", [])
    if parents or children:
        output.append("Hierarchy:")
        if parents:
            output.append(f"  Parents: {', '.join(p.get('name', '?') for p in parents)}")
        if children:
            output.append(f"  Children: {', '.join(c.get('name', '?') for c in children)}")

    # Remove trailing empty lines
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


async def fast_explore(
    mode: Literal["types"] = "types",
    type_name: Optional[str] = None,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes - currently supports type intelligence.

    Use this to understand type relationships in OOP codebases:
    - What classes implement an interface?
    - What's the inheritance hierarchy?
    - What functions return or take a specific type?

    Args:
        mode: Exploration mode - currently only "types" is supported
        type_name: Name of type to explore (required for types mode)
              Examples: "IUser", "PaymentProcessor", "BaseService"
        limit: Maximum results per category (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"
                      - "text": Lean formatted string - DEFAULT
                      - "json": Dict with full metadata

    Returns:
        - Text mode: Formatted string with type relationships
        - JSON mode: Dict with exploration results:
          - type_name: The queried type
          - implementations: Classes implementing this interface
          - hierarchy: {parents: [...], children: [...]} - inheritance tree
          - returns: Functions that return this type
          - parameters: Functions taking this type as parameter
          - total_found: Total matches across all categories

    Examples:
        # Find what implements an interface
        await fast_explore(mode="types", type_name="IUserService")

        # Explore a base class hierarchy
        await fast_explore(mode="types", type_name="BaseController")

    Type Intelligence Workflow:
        1. fast_explore(type_name="IService") → See all implementations
        2. get_symbols on implementing class → Understand the implementation
        3. trace_call_path on implementation → See how it's used
    """
    from miller.tools.explore import fast_explore as explore_impl

    # Get workspace-specific storage if needed
    if workspace != "primary":
        from miller.storage import StorageManager
        from miller.workspace_paths import get_workspace_db_path
        from miller.workspace_registry import WorkspaceRegistry

        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {
                "type_name": type_name,
                "error": f"Workspace '{workspace}' not found"
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        workspace_storage = storage

    try:
        result = await explore_impl(
            mode=mode,
            type_name=type_name,
            storage=workspace_storage,
            limit=limit,
        )

        if output_format == "text":
            return _format_explore_as_text(result)
        else:
            return result
    finally:
        if workspace != "primary" and workspace_storage:
            workspace_storage.close()


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
