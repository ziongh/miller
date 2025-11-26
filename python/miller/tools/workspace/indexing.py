"""Workspace indexing operations."""

from pathlib import Path
from typing import Optional

from miller.workspace_registry import WorkspaceRegistry

from .helpers import index_workspace_and_update_registry


async def handle_index(
    registry: WorkspaceRegistry, path: Optional[str], force: bool
) -> str:
    """
    Handle index operation - index current or specified workspace.

    Behavior (aligned with Julie):
    - If workspace already indexed and force=False: returns "already indexed" message
    - If force=True: clears and rebuilds index from scratch
    - Registers workspace if not already registered

    Args:
        registry: WorkspaceRegistry instance
        path: Workspace path to index (None = current working directory)
        force: Force complete re-indexing even if already indexed

    Returns:
        Indexing result message
    """
    from miller.embeddings import EmbeddingManager, VectorStore
    from miller.storage import StorageManager
    from miller.workspace import WorkspaceScanner
    from miller.workspace_paths import (
        ensure_workspace_directories,
        get_workspace_db_path,
        get_workspace_vector_path,
    )

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

    # Ensure workspace directories exist
    ensure_workspace_directories(workspace_id)

    # Get workspace-specific paths
    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    # Check if already indexed (has symbols) when not forcing
    if not force:
        if db_path.exists():
            import sqlite3

            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM symbols")
                symbol_count = cursor.fetchone()[0]
                conn.close()

                if symbol_count > 0:
                    return (
                        f"✅ Workspace already indexed: {workspace_path}\n"
                        f"  {symbol_count:,} symbols\n"
                        f"  Use force=True to rebuild index."
                    )
            except Exception:
                pass  # DB doesn't exist or is empty, proceed with indexing

    # Initialize components for indexing
    embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")
    storage = StorageManager(db_path=str(db_path))
    vector_store = VectorStore(db_path=str(vector_path), embeddings=embeddings)

    # If force=True, clear existing data from both SQLite and LanceDB
    if force:
        storage.clear_all()
        vector_store.clear_all()

    # Create scanner
    scanner = WorkspaceScanner(
        workspace_root=workspace_path,
        storage=storage,
        embeddings=embeddings,
        vector_store=vector_store,
    )

    # Run indexing
    try:
        stats = await scanner.index_workspace()

        # Get final counts
        cursor = storage.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT file_path) FROM symbols")
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

        storage.close()
        return "\n".join(result)

    except Exception as e:
        storage.close()
        return f"❌ Indexing failed: {e}"
