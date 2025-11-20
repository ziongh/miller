"""Workspace helper functions for indexing and registry updates."""

from pathlib import Path

from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


async def index_workspace_and_update_registry(
    workspace_id: str,
    workspace_path: Path,
    registry: WorkspaceRegistry,
) -> tuple[dict, int, int]:
    """
    Helper function to index a workspace and update registry.

    Args:
        workspace_id: Workspace ID
        workspace_path: Path to workspace directory
        registry: WorkspaceRegistry instance

    Returns:
        Tuple of (stats dict, symbol_count, file_count)

    Raises:
        Exception: If indexing fails
    """
    from miller.embeddings import EmbeddingManager, VectorStore
    from miller.storage import StorageManager
    from miller.workspace import WorkspaceScanner

    # Initialize components for this workspace
    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    storage = StorageManager(db_path=str(db_path))

    try:
        embeddings = EmbeddingManager()
        vector_store = VectorStore(db_path=str(vector_path), embeddings=embeddings)

        # Create scanner and run indexing
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
        registry.update_workspace_stats(
            workspace_id, symbol_count=symbol_count, file_count=file_count
        )

        return stats, symbol_count, file_count

    finally:
        # Always close storage connection
        storage.close()
