"""Workspace statistics and reporting operations."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


def get_live_workspace_counts(workspace_id: str) -> tuple[int, int]:
    """
    Query actual symbol/file counts from workspace database.

    This queries the database directly rather than relying on potentially
    stale registry data. Mirrors Julie's get_workspace_usage_stats() approach.

    Args:
        workspace_id: Workspace ID to query

    Returns:
        Tuple of (symbol_count, file_count)
    """
    db_path = get_workspace_db_path(workspace_id)
    if not db_path.exists():
        return 0, 0

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Get symbol count
        cursor.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]

        # Get file count (distinct file paths)
        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbols")
        file_count = cursor.fetchone()[0]

        conn.close()
        return symbol_count, file_count
    except Exception:
        return 0, 0


def handle_list(
    registry: WorkspaceRegistry, output_format: Literal["text", "json"] = "text"
) -> str:
    """
    Handle list operation.

    Args:
        registry: WorkspaceRegistry instance
        output_format: "text" (lean default) or "json"

    Returns:
        Formatted list of workspaces
    """
    workspaces = registry.list_workspaces()

    if not workspaces:
        return "No workspaces registered."

    if output_format == "json":
        return json.dumps(workspaces, indent=2)

    # Lean text format
    output = [f"Workspaces ({len(workspaces)}):"]

    for ws in workspaces:
        ws_type = "primary" if ws["workspace_type"] == "primary" else "ref"
        # Query live counts from database (works for primary and reference workspaces)
        sym, files = get_live_workspace_counts(ws["workspace_id"])

        # Main line: name [type] path
        output.append(f"  {ws['name']} [{ws_type}] {ws['path']}")

        # Stats line
        indexed_str = ""
        if ws.get("last_indexed"):
            indexed_dt = datetime.fromtimestamp(ws["last_indexed"])
            indexed_str = f" | {indexed_dt.strftime('%Y-%m-%d %H:%M')}"

        output.append(f"    {sym:,} sym | {files:,} files{indexed_str}")

    return "\n".join(output)


def handle_stats(
    registry: WorkspaceRegistry,
    workspace_id: Optional[str],
    output_format: Literal["text", "json"] = "text",
) -> str:
    """
    Handle stats operation.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to show stats for
        output_format: "text" (lean default) or "json"

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

    total_size = db_size + vector_size

    # Query live counts from database
    symbol_count, file_count = get_live_workspace_counts(workspace_id)

    if output_format == "json":
        data = {
            "name": workspace.name,
            "type": workspace.workspace_type,
            "path": workspace.path,
            "symbols": symbol_count,
            "files": file_count,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "vector_size_mb": round(vector_size / 1024 / 1024, 2),
            "last_indexed": workspace.last_indexed,
        }
        return json.dumps(data, indent=2)

    # Lean text format
    indexed_str = ""
    if workspace.last_indexed:
        indexed_dt = datetime.fromtimestamp(workspace.last_indexed)
        indexed_str = f" | {indexed_dt.strftime('%Y-%m-%d %H:%M')}"

    return (
        f"{workspace.name} [{workspace.workspace_type}]\n"
        f"  {symbol_count:,} sym | {file_count:,} files | "
        f"{total_size / 1024 / 1024:.2f} MB{indexed_str}"
    )


def handle_health(
    registry: WorkspaceRegistry,
    detailed: bool = False,
    output_format: Literal["text", "json"] = "text",
) -> str:
    """
    Handle health operation - show system health status.

    Args:
        registry: WorkspaceRegistry instance
        detailed: Include detailed per-workspace information
        output_format: "text" (lean default) or "json"

    Returns:
        Health status report
    """
    workspaces = registry.list_workspaces()

    # Gather stats (query live counts from each workspace database)
    total_count = len(workspaces)
    primary_count = sum(1 for ws in workspaces if ws["workspace_type"] == "primary")
    reference_count = total_count - primary_count

    # Query live counts from databases (not stale registry values)
    total_symbols = 0
    total_files = 0
    workspace_counts = {}  # Cache for detailed view
    for ws in workspaces:
        sym, files = get_live_workspace_counts(ws["workspace_id"])
        total_symbols += sym
        total_files += files
        workspace_counts[ws["workspace_id"]] = (sym, files)

    # Check for orphaned workspaces
    orphaned = [ws["name"] for ws in workspaces if not Path(ws["path"]).exists()]

    # Calculate total storage
    total_size = 0
    for ws in workspaces:
        workspace_id = ws["workspace_id"]
        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)
        if db_path.exists():
            total_size += db_path.stat().st_size
        if vector_path.parent.exists():
            for file in vector_path.parent.rglob("*"):
                if file.is_file():
                    total_size += file.stat().st_size

    total_mb = total_size / 1024 / 1024

    if output_format == "json":
        data = {
            "healthy": len(orphaned) == 0,
            "workspaces": total_count,
            "primary": primary_count,
            "reference": reference_count,
            "symbols": total_symbols,
            "files": total_files,
            "storage_mb": round(total_mb, 2),
            "orphaned": orphaned,
        }
        return json.dumps(data, indent=2)

    # Lean text format
    if not workspaces:
        return "Health: ✅ OK | No workspaces"

    status = "✅ OK" if not orphaned else f"⚠️ {len(orphaned)} orphaned"
    ws_str = f"{primary_count}p" + (f"+{reference_count}r" if reference_count else "")

    summary = f"Health: {status} | {ws_str} ws | {total_symbols:,} sym | {total_files:,} files | {total_mb:.1f} MB"

    if not detailed:
        return summary

    # Detailed mode adds workspace breakdown
    lines = [summary, ""]
    for ws in workspaces:
        exists = Path(ws["path"]).exists()
        icon = "✓" if exists else "✗"
        ws_type = "p" if ws["workspace_type"] == "primary" else "r"
        # Use cached live counts from earlier query
        sym, files = workspace_counts.get(ws["workspace_id"], (0, 0))
        lines.append(f"  {icon} {ws['name']} [{ws_type}] {sym:,} sym, {files:,} files")

    return "\n".join(lines)
