"""Workspace statistics and reporting operations."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


def handle_list(registry: WorkspaceRegistry) -> str:
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


def handle_stats(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
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


def handle_health(registry: WorkspaceRegistry, detailed: bool = False) -> str:
    """
    Handle health operation - show system health status.

    Args:
        registry: WorkspaceRegistry instance
        detailed: Include detailed per-workspace information

    Returns:
        Health status report
    """
    workspaces = registry.list_workspaces()

    # Basic health header
    output = ["🏥 Miller Workspace Health Check", "=" * 50, ""]

    # No workspaces case
    if not workspaces:
        output.append("📊 Registry: No workspaces registered")
        output.append("")
        output.append("💡 Tip: Use 'index' to index current workspace or 'add' for reference workspaces")
        return "\n".join(output)

    # Workspace counts
    total_count = len(workspaces)
    primary_count = sum(1 for ws in workspaces if ws["workspace_type"] == "primary")
    reference_count = sum(1 for ws in workspaces if ws["workspace_type"] == "reference")

    output.append(f"📊 Registry Status:")
    output.append(f"  Total workspaces: {total_count}")
    output.append(f"  • Primary: {primary_count}")
    output.append(f"  • Reference: {reference_count}")
    output.append("")

    # Aggregate statistics
    total_symbols = sum(ws.get("symbol_count", 0) for ws in workspaces)
    total_files = sum(ws.get("file_count", 0) for ws in workspaces)

    output.append(f"📈 Aggregate Statistics:")
    output.append(f"  Total symbols: {total_symbols:,}")
    output.append(f"  Total files: {total_files:,}")
    output.append("")

    # Check for orphaned workspaces
    orphaned = []
    for ws in workspaces:
        workspace_path = Path(ws["path"])
        if not workspace_path.exists():
            orphaned.append(ws["name"])

    if orphaned:
        output.append(f"⚠️  Issues Found:")
        output.append(f"  Orphaned workspaces: {len(orphaned)}")
        for name in orphaned:
            output.append(f"    • {name} (path no longer exists)")
        output.append("")
        output.append("💡 Tip: Run 'clean' operation to remove orphaned workspaces")
        output.append("")

    # Calculate total storage usage
    total_db_size = 0
    total_vector_size = 0

    for ws in workspaces:
        workspace_id = ws["workspace_id"]
        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        # DB size
        if db_path.exists():
            total_db_size += db_path.stat().st_size

        # Vector size
        if vector_path.parent.exists():
            for file in vector_path.parent.rglob("*"):
                if file.is_file():
                    total_vector_size += file.stat().st_size

    output.append(f"💾 Storage Usage:")
    output.append(f"  Database: {total_db_size / 1024 / 1024:.2f} MB")
    output.append(f"  Vector indexes: {total_vector_size / 1024 / 1024:.2f} MB")
    output.append(f"  Total: {(total_db_size + total_vector_size) / 1024 / 1024:.2f} MB")
    output.append("")

    # Detailed mode: per-workspace breakdown
    if detailed:
        output.append("📋 Workspace Details:")
        output.append("")

        for ws in workspaces:
            workspace_id = ws["workspace_id"]
            workspace_name = ws["name"]
            workspace_type = ws["workspace_type"]
            workspace_path = Path(ws["path"])

            # Check if path exists
            status = "✅" if workspace_path.exists() else "❌"

            output.append(f"{status} {workspace_name} ({workspace_type})")
            output.append(f"  Path: {ws['path']}")
            output.append(f"  Symbols: {ws.get('symbol_count', 0):,}")
            output.append(f"  Files: {ws.get('file_count', 0):,}")

            # Calculate workspace storage
            db_path = get_workspace_db_path(workspace_id)
            vector_path = get_workspace_vector_path(workspace_id)

            ws_db_size = db_path.stat().st_size if db_path.exists() else 0
            ws_vector_size = 0
            if vector_path.parent.exists():
                for file in vector_path.parent.rglob("*"):
                    if file.is_file():
                        ws_vector_size += file.stat().st_size

            output.append(f"  Storage: {(ws_db_size + ws_vector_size) / 1024 / 1024:.2f} MB")

            if ws.get("last_indexed"):
                indexed_dt = datetime.fromtimestamp(ws["last_indexed"])
                indexed_str = indexed_dt.strftime("%Y-%m-%d %H:%M")
                output.append(f"  Last indexed: {indexed_str}")

            output.append("")

    # Overall health status
    if orphaned:
        output.append("🔴 Health Status: Issues detected")
        output.append(f"   {len(orphaned)} orphaned workspace(s) found")
    else:
        output.append("✅ Health Status: All systems healthy")

    return "\n".join(output)
