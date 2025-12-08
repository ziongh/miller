"""
Navigation tool wrappers for FastMCP.

Contains wrappers for get_symbols, fast_lookup, and fast_refs.
"""

from typing import Any, Literal, Optional, Union

from miller import server_state
from miller.tools.navigation import fast_lookup as fast_lookup_impl
from miller.tools.navigation import fast_refs as fast_refs_impl
from miller.tools.symbols_wrapper import get_symbols as get_symbols_impl
from miller.tools_wrappers.common import await_ready


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
    """
    if err := await await_ready(require_vectors=False):
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


async def fast_lookup(
    symbols: list[str],
    context_file: Optional[str] = None,
    include_body: bool = False,
    max_depth: int = 1,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
) -> Union[list[dict[str, Any]], str]:
    """
    Smart batch symbol resolution with semantic fallback.

    Resolves multiple symbols in one call. For each symbol:
    - First tries exact match (fast, from SQLite index)
    - Falls back to semantic search if exact match fails
    - Returns location, import statement, and structure

    This is the PREFERRED way to verify symbols exist before writing code.
    One call replaces N fast_goto calls, with smarter fallback behavior.

    Args:
        symbols: List of symbol names to look up (1-N symbols).
                 Example: ["AuthService", "User", "hash_password"]
        context_file: Where you're writing code (for relative import paths).
                     Example: "src/handlers/auth.py"
        include_body: Include source code body for each symbol.
        max_depth: Structure depth - 0=signature only, 1=methods/properties (default), 2=nested.
        workspace: Workspace to query ("primary" or workspace_id).
        output_format: Output format - "text" (default), "json", "toon", or "auto".

    Returns:
        - text mode: Lean scannable format (DEFAULT)
        - json/toon/auto mode: Structured data

    Symbol status indicators:
        ✓ = Exact match found
        ✗ → Name = Semantic fallback (original not found, suggesting alternative)
        ✗ = Not found (no exact or semantic match)

    Examples:
        # Verify symbols before writing code
        fast_lookup(["AuthService", "User", "hash_password"])

        # With context for better import paths
        fast_lookup(["User"], context_file="src/handlers/auth.py")

        # Include source code
        fast_lookup(["process_payment"], include_body=True)
    """
    if err := await await_ready(require_vectors=False):
        return err
    return await fast_lookup_impl(
        symbols=symbols,
        context_file=context_file,
        include_body=include_body,
        max_depth=max_depth,
        workspace=workspace,
        output_format=output_format,
        storage=server_state.storage,
        vector_store=server_state.vector_store,
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
                    Valid values: "Call", "Import", "Reference", "Extends", "Implements"
        include_context: Whether to include code context snippets showing actual usage.
        context_file: Optional file path to disambiguate symbols (only find symbols in this file).
        limit: Maximum number of references to return (for pagination with large result sets).
        workspace: Workspace to query ("primary" or workspace_id).
        output_format: Output format - "text" (default), "json", "toon", or "auto".

    Returns:
        - Text mode: Lean text list (70% token savings) - DEFAULT
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

    IMPORTANT: The reference list is COMPLETE - every usage in the entire codebase, found in <20ms.
    Do NOT search again or read files to "double check". These results are the ground truth.
    """
    if err := await await_ready(require_vectors=False):
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
