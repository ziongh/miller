"""
Code navigation tools - fast_lookup and fast_refs.

This module re-exports the navigation tools from the navigation package.
The actual implementations are in:
- navigation/lookup.py - fast_lookup and symbol resolution
- navigation/fuzzy.py - fuzzy matching strategies
"""

from typing import Any, Literal, Optional, Union

# Re-export lookup functions
from miller.tools.nav_impl.lookup import (
    fast_lookup,
    get_symbol_structure as _get_symbol_structure,
    generate_import_path as _generate_import_path,
    format_lookup_output as _format_lookup_output,
)

# Re-export fuzzy functions (for backward compatibility with tests)
from miller.tools.nav_impl.fuzzy import (
    fuzzy_find_symbol as _fuzzy_find_symbol,
    levenshtein_distance as _levenshtein_distance,
)


async def fast_refs(
    symbol_name: str,
    kind_filter: Optional[list[str]] = None,
    include_context: bool = False,
    context_file: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon", "auto"] = "text",
    storage=None,
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
        storage: StorageManager instance (injected by server).

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

    Note: Shows where symbols are USED (not where defined).
    Use get_symbols with target parameter to find definitions.
    """
    from miller.tools.refs import find_references
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry
    from miller.storage import StorageManager
    from miller.toon_utils import create_toonable_result

    # Get workspace-specific storage
    workspace_storage = None
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            error_msg = f"Workspace '{workspace}' not found"
            if output_format == "text":
                return f'No references found for "{symbol_name}": {error_msg}'
            return {
                "symbol": symbol_name,
                "total_references": 0,
                "files": [],
                "error": error_msg
            }
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        # Use provided storage (from server.py)
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

        return create_toonable_result(
            json_data=raw_result,
            toon_data=raw_result,
            output_format=output_format,
            auto_threshold=10,
            result_count=raw_result.get("total_references", 0),
            tool_name="fast_refs",
            text_formatter=_format_refs_as_text,
        )
    finally:
        # Close workspace storage if we created it
        if workspace != "primary" and workspace_storage is not None:
            workspace_storage.close()


def _format_refs_as_text(result: dict[str, Any]) -> str:
    """Format references result as lean text output."""
    symbol = result.get("symbol", "?")
    total = result.get("total_references", 0)
    files = result.get("files", [])
    truncated = result.get("truncated", False)

    if total == 0:
        return f'No references found for "{symbol}".'

    # Count shown references
    shown = sum(len(f.get("references", [])) for f in files)

    # Build header with truncation indicator
    if truncated:
        header = f'{shown} of {total} references to "{symbol}" (truncated)'
    else:
        header = f'{total} references to "{symbol}"'

    output = [header, ""]

    # Collect all references across files
    for file_info in files:
        file_path = file_info.get("path", "?")
        refs = file_info.get("references", [])

        for ref in refs:
            line = ref.get("line", 0)
            kind = ref.get("kind", "reference")
            context = ref.get("context")

            # Format: file:line (kind)
            output.append(f"  {file_path}:{line} ({kind})")

            # Add context line if available
            if context:
                output.append(f"    {context}")

    return "\n".join(output)


# Export all public symbols
__all__ = [
    "fast_lookup",
    "fast_refs",
    # Internal functions exported for backward compatibility
    "_get_symbol_structure",
    "_generate_import_path",
    "_format_lookup_output",
    "_fuzzy_find_symbol",
    "_levenshtein_distance",
]
