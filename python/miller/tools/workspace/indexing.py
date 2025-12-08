"""Workspace indexing operations."""

import asyncio
from pathlib import Path
from typing import Optional

from miller import server_state
from miller.workspace_registry import WorkspaceRegistry

from .helpers import index_workspace_and_update_registry


async def handle_index(
    registry: WorkspaceRegistry, path: Optional[str], force: bool
) -> str:
    """
    Handle index operation - index current or specified workspace.

    IMPORTANT: Uses SHARED instances from server_state for unified database architecture.
    All workspaces share the same SQLite database and LanceDB vector store.

    Behavior (aligned with Julie):
    - If workspace already indexed and force=False: returns "already indexed" message
    - If force=True: clears THIS workspace's data and rebuilds (NOT all workspaces!)
    - Registers workspace if not already registered

    Args:
        registry: WorkspaceRegistry instance
        path: Workspace path to index (None = current working directory)
        force: Force complete re-indexing even if already indexed

    Returns:
        Indexing result message
    """
    from miller.workspace import WorkspaceScanner
    from miller.workspace_paths import ensure_miller_directories

    # CRITICAL: Use shared instances from server_state for unified database architecture
    if not server_state.storage or not server_state.embeddings or not server_state.vector_store:
        return "Error: Server not fully initialized. Please wait for initialization to complete."

    storage = server_state.storage
    embeddings = server_state.embeddings
    vector_store = server_state.vector_store

    # Determine workspace path
    if path:
        workspace_path = Path(path).resolve()
        if not workspace_path.exists():
            return f"Error: Path '{path}' does not exist"
        if not workspace_path.is_dir():
            return f"Error: Path '{path}' is not a directory"
    else:
        # Use current working directory
        workspace_path = Path.cwd()

    # Check if this workspace is already registered
    workspace_id = None
    workspace_type = None
    for ws in registry.list_workspaces():
        ws_path = Path(ws["path"]).resolve()
        if ws_path == workspace_path:
            workspace_id = ws["workspace_id"]
            workspace_type = ws.get("workspace_type", "primary")
            break

    # If not registered, register as primary workspace
    if not workspace_id:
        workspace_id = registry.add_workspace(
            path=str(workspace_path),
            name=workspace_path.name,
            workspace_type="primary",
        )
        workspace_type = "primary"

    # Ensure .miller directory exists (unified database goes here)
    ensure_miller_directories()

    # Check if already indexed (has symbols for THIS workspace) when not forcing
    if not force:
        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM symbols WHERE workspace_id = ?",
            (workspace_id,)
        )
        symbol_count = cursor.fetchone()[0]

        if symbol_count > 0:
            return (
                f"✅ Workspace already indexed: {workspace_path}\n"
                f"  {symbol_count:,} symbols\n"
                f"  Use force=True to rebuild index."
            )

    # If force=True, clear existing data for THIS WORKSPACE ONLY (not all workspaces!)
    if force:
        storage.clear_workspace(workspace_id)
        vector_store.clear_workspace(workspace_id)

    # Create scanner for this workspace (uses shared storage/embeddings/vector_store)
    scanner = WorkspaceScanner(
        workspace_root=workspace_path,
        storage=storage,
        embeddings=embeddings,
        vector_store=vector_store,
        workspace_id=workspace_id,
    )

    # Run indexing
    try:
        stats = await scanner.index_workspace()

        # Compute transitive closure for reachability queries
        from miller.closure import compute_transitive_closure

        closure_count = await asyncio.to_thread(
            compute_transitive_closure, storage, 10
        )

        # Get final counts for THIS workspace only
        cursor = storage.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM symbols WHERE workspace_id = ?",
            (workspace_id,)
        )
        symbol_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT file_path) FROM files WHERE workspace_id = ?",
            (workspace_id,)
        )
        file_count = cursor.fetchone()[0]

        # Update registry with stats
        registry.update_workspace_stats(
            workspace_id, symbol_count=symbol_count, file_count=file_count
        )

        # Format result
        files_processed = stats.get("indexed", 0) + stats.get("updated", 0)
        result = [
            f"✅ Indexing complete: {workspace_path}",
            f"  📁 Files: {file_count:,}",
            f"  ✨ Symbols: {symbol_count:,}",
            f"  🔗 Reachability: {closure_count:,} paths",
        ]

        if stats.get("indexed", 0) > 0:
            result.append(f"  📄 New: {stats['indexed']}")
        if stats.get("updated", 0) > 0:
            result.append(f"  🔄 Updated: {stats['updated']}")
        if stats.get("skipped", 0) > 0:
            result.append(f"  ⏭️  Unchanged: {stats['skipped']}")
        if stats.get("deleted", 0) > 0:
            result.append(f"  🗑️  Deleted: {stats['deleted']}")
        if stats.get("errors", 0) > 0:
            result.append(f"  ⚠️  Errors: {stats['errors']}")

        result.append("\nReady for search and navigation!")

        return "\n".join(result)

    except Exception as e:
        return f"❌ Indexing failed: {e}"
