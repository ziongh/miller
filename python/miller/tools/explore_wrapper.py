"""
Fast explore tool - Multi-mode code exploration.

Provides fast_explore for type intelligence, similar code detection, and dependency analysis.
"""

from typing import Any, Literal, Union, Optional


async def fast_explore(
    mode: Literal["types", "similar", "dependencies"] = "types",
    type_name: Optional[str] = None,
    symbol: Optional[str] = None,
    threshold: float = 0.7,
    depth: int = 3,
    limit: int = 10,
    workspace: str = "primary",
    output_format: Literal["text", "json"] = "text",
    storage=None,
) -> Union[dict[str, Any], str]:
    """
    Explore codebases with different modes.

    Modes:
    - types: Type intelligence (implementations, hierarchy, return/parameter types)
    - similar: Find semantically similar code (for duplicate detection)
    - dependencies: Trace transitive dependencies (for impact analysis)

    Args:
        mode: Exploration mode
        type_name: Name of type to explore (required for types mode)
        symbol: Symbol name to explore (required for similar/dependencies modes)
        threshold: Minimum similarity score for similar mode (0.0-1.0, default 0.7)
        depth: Maximum traversal depth for dependencies mode (1-10, default 3)
        limit: Maximum results (default: 10)
        workspace: Workspace to query ("primary" or workspace_id)
        output_format: Output format - "text" (default) or "json"
        storage: StorageManager instance (injected by server)

    Returns:
        Dict or formatted string based on output_format
    """
    from miller.tools.explore import fast_explore as _fast_explore
    from miller.tools.explore import _format_similar_as_text, _format_dependencies_as_text, _format_explore_as_text
    from miller.storage import StorageManager
    from miller.workspace_paths import get_workspace_db_path
    from miller.workspace_registry import WorkspaceRegistry

    # Get workspace-specific storage if needed
    if workspace != "primary":
        registry = WorkspaceRegistry()
        workspace_entry = registry.get_workspace(workspace)
        if not workspace_entry:
            return {"error": f"Workspace '{workspace}' not found"}
        db_path = get_workspace_db_path(workspace)
        workspace_storage = StorageManager(db_path=str(db_path))
    else:
        workspace_storage = storage

    try:
        result = await _fast_explore(
            mode=mode,
            type_name=type_name,
            symbol=symbol,
            threshold=threshold,
            depth=depth,
            storage=workspace_storage,
            limit=limit,
        )

        if output_format == "text":
            if mode == "similar":
                return _format_similar_as_text(result)
            elif mode == "dependencies":
                return _format_dependencies_as_text(result)
            else:
                return _format_explore_as_text(result)
        return result
    finally:
        if workspace != "primary" and workspace_storage:
            workspace_storage.close()
