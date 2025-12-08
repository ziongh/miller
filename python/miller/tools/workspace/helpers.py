"""Workspace helper functions for indexing and registry updates."""

import logging
from pathlib import Path

from miller import server_state
from miller.workspace_registry import WorkspaceRegistry

logger = logging.getLogger("miller.workspace")


async def index_workspace_and_update_registry(
    workspace_id: str,
    workspace_path: Path,
    registry: WorkspaceRegistry,
) -> tuple[dict, int, int]:
    """
    Helper function to index a workspace and update registry.

    IMPORTANT: Uses SHARED instances from server_state for unified database architecture.
    All workspaces share the same SQLite database and LanceDB vector store.
    Creating new instances would trigger schema migration that wipes existing data!

    This function acquires the indexing lock to prevent concurrent indexing operations,
    which can cause memory corruption in native code (LanceDB/Arrow, PyTorch CUDA).

    Args:
        workspace_id: Workspace ID
        workspace_path: Path to workspace directory
        registry: WorkspaceRegistry instance

    Returns:
        Tuple of (stats dict, symbol_count, file_count)

    Raises:
        Exception: If indexing fails or server_state not initialized
    """
    from miller.workspace import WorkspaceScanner

    # CRITICAL: Use shared instances from server_state for unified database architecture
    # DO NOT create new StorageManager/VectorStore instances - this would trigger
    # schema migration that clears all existing data from other workspaces!
    if not server_state.storage or not server_state.embeddings or not server_state.vector_store:
        raise RuntimeError(
            "Server not fully initialized. Cannot index workspace before "
            "storage, embeddings, and vector_store are ready."
        )

    storage = server_state.storage
    embeddings = server_state.embeddings
    vector_store = server_state.vector_store

    # Create scanner for this workspace (uses shared storage/embeddings/vector_store)
    scanner = WorkspaceScanner(
        workspace_root=workspace_path,
        storage=storage,
        embeddings=embeddings,
        vector_store=vector_store,
        workspace_id=workspace_id,
    )

    # Acquire indexing lock to prevent concurrent indexing operations
    # This prevents memory corruption in native code (LanceDB, PyTorch CUDA)
    indexing_lock = server_state.get_indexing_lock()

    if indexing_lock.locked():
        logger.info(f"⏳ Waiting for another indexing operation to complete...")

    async with indexing_lock:
        # Run indexing (protected by lock)
        stats = await scanner.index_workspace()

    # Get actual counts from storage for THIS workspace only
    # Filter by workspace_id since we have unified database
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

    return stats, symbol_count, file_count
