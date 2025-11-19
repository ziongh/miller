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

    elif operation == "add":
        return await _handle_add(registry, path, name)

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


async def _handle_add(
    registry: WorkspaceRegistry, path: Optional[str], name: Optional[str]
) -> str:
    """
    Handle add operation - add reference workspace.

    Args:
        registry: WorkspaceRegistry instance
        path: Workspace path to add
        name: Display name for workspace

    Returns:
        Success or error message
    """
    # Validate parameters
    if not path:
        return "Error: 'path' parameter required for add operation"

    if not name:
        return "Error: 'name' parameter required for add operation"

    # Verify path exists
    workspace_path = Path(path)
    if not workspace_path.exists():
        return f"Error: Path does not exist: {path}"

    if not workspace_path.is_dir():
        return f"Error: Path is not a directory: {path}"

    # Add to registry as reference workspace
    workspace_id = registry.add_workspace(
        path=str(workspace_path.resolve()), name=name, workspace_type="reference"
    )

    # Create workspace directories
    from miller.workspace_paths import ensure_workspace_directories

    ensure_workspace_directories(workspace_id)

    # Index the workspace
    try:
        from miller.embeddings import EmbeddingManager, VectorStore
        from miller.storage import StorageManager
        from miller.workspace import WorkspaceScanner

        # Initialize components for this workspace
        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        storage = StorageManager(db_path=str(db_path))
        embeddings = EmbeddingManager()
        vector_store = VectorStore(db_path=str(vector_path), embeddings=embeddings)

        # Create scanner and index
        scanner = WorkspaceScanner(
            workspace_root=workspace_path,
            storage=storage,
            embeddings=embeddings,
            vector_store=vector_store,
        )

        # Run indexing
        stats = await scanner.index_workspace()

        # Get actual counts from storage (direct SQL queries)
        cursor = storage.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbols")
        file_count = cursor.fetchone()[0]

        # Update registry with stats
        registry.update_workspace_stats(workspace_id, symbol_count=symbol_count, file_count=file_count)

        # Return success message
        files_processed = stats.get("indexed", 0) + stats.get("updated", 0)
        output = [
            f"✅ Successfully added reference workspace: {name}",
            f"  Workspace ID: {workspace_id}",
            f"  Path: {workspace_path}",
            f"  Files indexed: {files_processed:,}",
            f"  Symbols indexed: {symbol_count:,}",
        ]

        return "\n".join(output)

    except Exception as e:
        # Clean up on failure
        registry.remove_workspace(workspace_id)
        return f"Error indexing workspace: {str(e)}"
