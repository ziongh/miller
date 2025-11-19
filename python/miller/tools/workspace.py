"""
Workspace management MCP tool.

Provides operations to manage primary and reference workspaces.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


async def manage_workspace(
    operation: Literal["index", "list", "add", "remove", "stats", "clean", "refresh", "health"],
    path: Optional[str] = None,
    name: Optional[str] = None,
    workspace_id: Optional[str] = None,
    force: bool = False,
    detailed: bool = False,
) -> str:
    """
    Manage workspaces: index, list, add, remove, stats, clean, refresh, health.

    Operations:
    - list: Show all registered workspaces
    - stats: Show workspace statistics
    - index: Index current or specified workspace
    - add: Add reference workspace
    - remove: Remove workspace
    - clean: Clean up orphaned data
    - refresh: Re-index workspace
    - health: System health check

    Args:
        operation: Operation to perform
        path: Workspace path (for index, add)
        name: Workspace display name (for add)
        workspace_id: Workspace ID (for stats, remove, refresh)
        force: Force re-indexing (for index, refresh)
        detailed: Include detailed information (for health)

    Returns:
        Operation result message
    """
    registry = WorkspaceRegistry()

    if operation == "list":
        return _handle_list(registry)

    elif operation == "stats":
        return _handle_stats(registry, workspace_id)

    else:
        return f"Error: Operation '{operation}' not implemented yet"


def _handle_list(registry: WorkspaceRegistry) -> str:
    """
    Handle list operation.

    Args:
        registry: WorkspaceRegistry instance

    Returns:
        Formatted list of workspaces
    """
    workspaces = registry.list_workspaces()

    if not workspaces:
        return "No workspaces registered yet. Use 'index' to index current workspace."

    output = ["📁 Registered Workspaces:\n"]

    for ws in workspaces:
        # Workspace type indicator
        if ws["workspace_type"] == "primary":
            status = "🏠 PRIMARY"
        else:
            status = "📚 REFERENCE"

        output.append(f"{status} {ws['name']}")
        output.append(f"  ID: {ws['workspace_id']}")
        output.append(f"  Path: {ws['path']}")
        output.append(f"  Symbols: {ws['symbol_count']:,}")
        output.append(f"  Files: {ws['file_count']:,}")

        if ws.get("last_indexed"):
            indexed_dt = datetime.fromtimestamp(ws["last_indexed"])
            indexed_str = indexed_dt.strftime("%Y-%m-%d %H:%M")
            output.append(f"  Last indexed: {indexed_str}")

        output.append("")  # Blank line between workspaces

    return "\n".join(output)


def _handle_stats(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
    """
    Handle stats operation.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to show stats for

    Returns:
        Formatted statistics
    """
    if not workspace_id:
        return "Error: workspace_id required for stats operation"

    workspace = registry.get_workspace(workspace_id)
    if not workspace:
        return f"Error: Workspace '{workspace_id}' not found"

    # Get database stats
    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    # Calculate sizes
    db_size = db_path.stat().st_size if db_path.exists() else 0

    # Vector size = sum of all files in vector directory
    vector_size = 0
    if vector_path.parent.exists():
        for file in vector_path.parent.rglob("*"):
            if file.is_file():
                vector_size += file.stat().st_size

    # Format output
    output = [
        f"📊 Workspace Statistics: {workspace.name}",
        f"  Type: {workspace.workspace_type}",
        f"  Path: {workspace.path}",
        f"  Symbols: {workspace.symbol_count:,}",
        f"  Files: {workspace.file_count:,}",
        f"  Database size: {db_size / 1024 / 1024:.2f} MB",
        f"  Vector index size: {vector_size / 1024 / 1024:.2f} MB",
    ]

    if workspace.last_indexed:
        indexed_dt = datetime.fromtimestamp(workspace.last_indexed)
        indexed_str = indexed_dt.strftime("%Y-%m-%d %H:%M")
        output.append(f"  Last indexed: {indexed_str}")

    return "\n".join(output)
