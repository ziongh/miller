"""
Workspace management MCP tool.

Provides operations to manage primary and reference workspaces.
"""

from typing import Literal, Optional

from miller.workspace_registry import WorkspaceRegistry

from .indexing import handle_index
from .operations import handle_add, handle_clean, handle_refresh, handle_remove
from .stats import handle_health, handle_list, handle_stats


async def manage_workspace(
    operation: Literal["index", "list", "add", "remove", "stats", "clean", "refresh", "health"],
    path: Optional[str] = None,
    name: Optional[str] = None,
    workspace: Optional[str] = None,
    force: bool = False,
    detailed: bool = False,
    output_format: Literal["text", "json"] = "text",
) -> str:
    """
    Manage workspaces: index, list, add, remove, stats, clean, refresh, health.

    Operations:
    - list: Show all registered workspaces
    - stats: Show workspace statistics (defaults to primary workspace)
    - index: Index workspace (registers if new, skips if already indexed unless force=True)
    - add: Add reference workspace (indexes into separate storage)
    - remove: Remove workspace and delete its data (REQUIRES workspace parameter)
    - clean: Clean up orphaned data (workspaces with deleted paths)
    - refresh: Re-index existing workspace (REQUIRES workspace parameter)
    - health: System health check (registry status, aggregate stats)

    Index vs Refresh (aligned with Julie):
    - index: For initial setup or force rebuild. Uses path, registers if new.
             If already indexed (has symbols), returns early unless force=True.
    - refresh: For updating existing registered workspace. REQUIRES workspace_id.
               Always incremental (no force option).

    Args:
        operation: Operation to perform
        path: Workspace path (for index, add)
        name: Workspace display name (for add)
        workspace: Workspace ID (REQUIRED for remove, refresh. Optional for stats)
        force: Force complete re-indexing (for index only)
        detailed: Include detailed per-workspace info (for health)
        output_format: Output format - "text" (default, lean) or "json"

    Returns:
        Operation result message

    Examples:
        # Index current workspace (skips if already indexed)
        manage_workspace(operation="index")

        # Force complete rebuild of index
        manage_workspace(operation="index", force=True)

        # Add reference workspace
        manage_workspace(operation="add", path="/path/to/lib", name="MyLibrary")

        # Get stats for primary workspace
        manage_workspace(operation="stats")

        # Refresh specific workspace (workspace parameter REQUIRED)
        manage_workspace(operation="refresh", workspace="workspace_abc123")

        # System health check
        manage_workspace(operation="health", detailed=True)
    """
    registry = WorkspaceRegistry()

    # Default to primary workspace when workspace not provided (for stats only)
    # Note: refresh and remove REQUIRE workspace_id (aligned with Julie)
    workspace_id = workspace
    if workspace_id is None and operation == "stats":
        workspaces = registry.list_workspaces()
        primary = next((w for w in workspaces if w.get("workspace_type") == "primary"), None)
        if primary:
            workspace_id = primary.get("workspace_id")

    if operation == "list":
        return handle_list(registry, output_format)

    elif operation == "stats":
        return handle_stats(registry, workspace_id, output_format)

    elif operation == "index":
        return await handle_index(registry, path, force)

    elif operation == "add":
        return await handle_add(registry, path, name)

    elif operation == "remove":
        return await handle_remove(registry, workspace_id)

    elif operation == "refresh":
        return await handle_refresh(registry, workspace_id)

    elif operation == "clean":
        return await handle_clean(registry)

    elif operation == "health":
        return handle_health(registry, detailed, output_format)

    else:
        return f"Error: Operation '{operation}' not implemented yet"


__all__ = ["manage_workspace"]
