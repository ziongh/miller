"""
Code navigation tools - find references.

Provides fast_refs for finding symbol usages. fast_goto is kept for internal use.
"""

from typing import Any, Literal, Optional, Union


async def fast_goto(
    symbol_name: str,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
    storage=None,
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
        storage: StorageManager instance (injected by server)

    Returns:
        - Text mode: Formatted string with location
        - JSON mode: Symbol location dict (file, line, signature), or None if not found

    Note: For exploring unknown code, use fast_search first. Use fast_goto when
    you already know the symbol name from search results or references.
    """
    # Get workspace-specific storage if needed
    if workspace != "primary":
        from miller.workspace_paths import get_workspace_db_path
        from miller.workspace_registry import WorkspaceRegistry
        from miller.storage import StorageManager

        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if workspace_entry:
            db_path = get_workspace_db_path(workspace)
            storage = StorageManager(db_path=str(db_path))
        else:
            # Return not found for non-existent workspace
            if output_format == "text":
                return f'No definition found for "{symbol_name}" (workspace "{workspace}" not found).'
            else:
                return None

    # Query SQLite for exact match
    # Support qualified names like "ClassName.method" (consistent with fast_refs)
    sym = None
    if "." in symbol_name:
        # Qualified name: Parent.Child
        parts = symbol_name.split(".", 1)
        parent_name, child_name = parts[0], parts[1]
        # Query for child symbol with matching parent
        cursor = storage.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN symbols parent ON s.parent_id = parent.id
            WHERE parent.name = ? AND s.name = ?
            ORDER BY CASE s.kind
                WHEN 'import' THEN 2
                WHEN 'reference' THEN 2
                ELSE 1
            END
            LIMIT 1
        """, (parent_name, child_name))
        row = cursor.fetchone()
        if row:
            sym = dict(row)
    else:
        # Simple name lookup
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
        storage: StorageManager instance (injected by server)

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
    from miller.tools.refs import find_references
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry
    from miller.storage import StorageManager
    from miller.toon_utils import create_toonable_result

    # Get workspace-specific storage
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

        # Use Julie's simple pattern: same structure for both JSON and TOON
        # fast_refs already returns TOON-friendly nested dicts
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
