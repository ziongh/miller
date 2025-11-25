"""
Miller MCP tool wrappers - thin delegating functions for FastMCP.

These are the actual MCP tool implementations that FastMCP calls. They do minimal work,
delegating to the implementation modules while handling readiness checks and state access.

This module is separate from server.py to keep server.py under 500 lines while maintaining
a clean separation of concerns: tool registration in server.py, tool implementation in tools/,
and thin wrappers here.
"""

from typing import Any, Literal, Optional, Union

from miller import server_state
from miller.tools.search import fast_search as fast_search_impl
from miller.tools.navigation import fast_refs as fast_refs_impl
from miller.tools.symbols_wrapper import get_symbols as get_symbols_impl
from miller.tools.trace_wrapper import trace_call_path as trace_call_path_impl
from miller.tools.explore_wrapper import fast_explore as fast_explore_impl
from miller.tools.refactor import rename_symbol as rename_symbol_impl


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
    if server_state.storage is None:
        return _NOT_READY_MSG
    if require_vectors and server_state.vector_store is None:
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
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
) -> Union[list[dict[str, Any]], str]:
    """
    Search indexed code using text, semantic, or hybrid methods.

    This is the PREFERRED way to find code in the codebase. Use this instead of reading
    files or using grep - semantic search understands what you're looking for!

    When to use: ALWAYS before reading files. Search first to narrow scope by 90%,
    then read only what you need. This is 10x faster than reading entire files.

    You are excellent at crafting search queries. The results are ranked by relevance -
    trust the top results as your answer. No need to verify by reading files -
    Miller's pre-indexed results are accurate and complete.

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

    Filtering:
    - language: Filter by programming language (e.g., "python", "rust", "typescript")
    - file_pattern: Filter by glob pattern (e.g., "*.py", "src/**/*.ts", "tests/**")

    Semantic fallback:
    - When method="text" returns 0 results, automatically tries semantic search
    - This helps find conceptually similar code when exact terms don't match

    Examples:
        # Simple search (uses text output by default)
        fast_search("authentication logic")
        fast_search("StorageManager")

        # Method override
        fast_search("user auth", method="semantic")     # Force semantic search
        fast_search(": BaseClass", method="pattern")    # Force pattern search

        # Filter by language
        fast_search("user service", language="python")  # Only Python results

        # Filter by file pattern
        fast_search("test", file_pattern="tests/**")    # Only test files

        # Combine filters
        fast_search("handler", language="rust", file_pattern="src/**")

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
        language: Filter results by programming language (case-insensitive).
        file_pattern: Filter results by file path glob pattern.

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
        workspace=workspace,
        output_format=output_format,
        rerank=rerank,
        expand=expand,
        expand_limit=expand_limit,
        language=language,
        file_pattern=file_pattern,
        vector_store=server_state.vector_store,
        storage=server_state.storage,
        embeddings=server_state.embeddings,
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

    When to use: ALWAYS before reading any file. A 500-line file becomes a 20-line overview.
    Use mode="structure" (default) to see all classes, functions, and methods WITHOUT
    dumping entire file content into context. This saves 70-90% of tokens.

    Workflow: get_symbols(mode="structure") → identify what you need → get_symbols(target="X", mode="full")
    This two-step approach reads ONLY the code you need.

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

    When to use: REQUIRED before changing, renaming, or deleting any symbol. Changing code
    without checking references WILL break dependencies. This is not optional.

    The references returned are COMPLETE - every usage in the codebase (<20ms). You can
    trust this list and don't need to search again or read files to verify.

    Args:
        symbol_name: Name of symbol to find references for.
                    Supports qualified names like "User.save" to find methods specifically.
        kind_filter: Optional list of relationship kinds to filter by.
                    Valid values (case-sensitive):
                    - "Call" - Function/method calls
                    - "Import" - Import statements
                    - "Reference" - General references (variable usage, etc.)
                    - "Extends" - Class inheritance (class Foo(Bar))
                    - "Implements" - Interface implementation
                    Example: kind_filter=["Call"] returns only call sites.
        include_context: Whether to include code context snippets showing actual usage.
        context_file: Optional file path to disambiguate symbols (only find symbols in this file).
        limit: Maximum number of references to return (for pagination with large result sets).
        workspace: Workspace to query ("primary" or workspace_id).
        output_format: Output format - "text" (default), "json", "toon", or "auto".
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

    Note: Shows where symbols are USED (not where defined). Use get_symbols with target parameter to find definitions.
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
        storage=server_state.storage,
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
        storage=server_state.storage,
    )


async def fast_explore(
    mode: Literal["types", "similar"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
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
    - similar: Find semantically similar code using TRUE vector embedding similarity

    Note: For dependency tracing, use trace_call_path(direction="downstream") instead,
    which provides richer features including semantic cross-language discovery.

    Args:
        mode: Exploration mode ("types" or "similar")
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar mode)
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

        # Find semantically similar code - duplicate/pattern detection
        await fast_explore(mode="similar", symbol="getUserData")

    Note: Similar mode uses TRUE semantic similarity - it finds code with similar
    meaning/patterns, not just matching text. This works across naming conventions
    and even different languages (e.g., getUserData ↔ fetch_user_info).
    """
    # Similar mode needs vector_store and embeddings, types mode only needs storage
    if err := _check_ready(require_vectors=(mode == "similar")):
        return err
    return await fast_explore_impl(
        mode=mode,
        type_name=type_name,
        symbol=symbol,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
        storage=server_state.storage,
        vector_store=server_state.vector_store,
        embeddings=server_state.embeddings,
    )


async def rename_symbol(
    old_name: str,
    new_name: str,
    scope: str = "workspace",
    dry_run: bool = True,
    update_imports: bool = True,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
) -> Union[str, dict[str, Any]]:
    """
    Safely rename a symbol across the codebase with reference checking.

    This is Miller's SAFE REFACTORING tool. It uses fast_refs to find ALL references
    (definition + usages), then applies changes atomically with word-boundary safety.

    IMPORTANT: Default dry_run=True shows a preview WITHOUT modifying files.
    Set dry_run=False only after reviewing the preview.

    Args:
        old_name: Current symbol name to rename (e.g., "getUserData", "User.save")
                  Supports qualified names for method disambiguation
        new_name: New name for the symbol (must be valid identifier)
        scope: Rename scope - "workspace" (default) or "file" (future)
        dry_run: If True (default), show preview only. If False, apply changes.
        update_imports: Whether to update import statements (default True)
        workspace: Workspace to operate on ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"

    Returns:
        - dry_run=True: Preview showing all files/lines that would change
        - dry_run=False: Summary of applied changes

    Safety Features:
        - Word-boundary matching prevents renaming substrings
          (renaming "get" won't affect "get_user" or "forget")
        - Name collision detection warns if new_name already exists
        - Identifier validation ensures new_name is syntactically valid
        - Preview mode lets you review before committing

    Examples:
        # Preview a rename (safe, no changes)
        await rename_symbol("getUserData", "fetchUserData")

        # Apply after reviewing preview
        await rename_symbol("getUserData", "fetchUserData", dry_run=False)

        # Rename a method specifically
        await rename_symbol("User.save", "User.persist", dry_run=False)

    Workflow:
        1. rename_symbol("old", "new") → Review preview
        2. rename_symbol("old", "new", dry_run=False) → Apply changes
        3. Run tests to verify no breakage
    """
    if err := _check_ready(require_vectors=False):
        return err
    return await rename_symbol_impl(
        old_name=old_name,
        new_name=new_name,
        scope=scope,
        dry_run=dry_run,
        update_imports=update_imports,
        workspace=workspace,
        output_format=output_format,
        storage=server_state.storage,
        vector_store=server_state.vector_store,
    )
