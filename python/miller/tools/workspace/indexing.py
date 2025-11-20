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

    Args:
        registry: WorkspaceRegistry instance
        path: Workspace path to index (None = current workspace)
        force: Force re-indexing even if up-to-date

    Returns:
        Indexing result message
    """
    from miller.embeddings import EmbeddingManager, VectorStore
    from miller.storage import StorageManager
    from miller.workspace import WorkspaceScanner

    # Determine workspace path
    if path:
        workspace_path = Path(path).resolve()
        if not workspace_path.exists():
            return f"Error: Path '{path}' does not exist"
    else:
        # Use current working directory
        workspace_path = Path.cwd()

    # Check if this workspace is already registered
    workspace_id = None
    for ws in registry.list_workspaces():
        ws_path = Path(ws["path"]).resolve()
        if ws_path == workspace_path:
            workspace_id = ws["id"]
            break

    # Initialize components for indexing
    embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5", device="auto")

    if workspace_id:
        # Index registered workspace into its own storage
        from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path

        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        storage = StorageManager(db_path=str(db_path))
        vector_store = VectorStore(db_path=str(vector_path), embeddings=embeddings)
    else:
        # Index into default/primary storage
        storage = StorageManager(db_path=".miller/indexes/symbols.db")
        vector_store = VectorStore(db_path=".miller/indexes/vectors.lance", embeddings=embeddings)

    # Create scanner
    scanner = WorkspaceScanner(
        workspace_root=workspace_path, storage=storage, embeddings=embeddings, vector_store=vector_store
    )

    # Check if indexing needed (unless force=True)
    if not force:
        needs_indexing = await scanner.check_if_indexing_needed()
        if not needs_indexing:
            return f"✅ Workspace already up-to-date: {workspace_path}\nUse force=True to rebuild index."

    # Run indexing
    try:
        stats = await scanner.index_workspace()

        # Update registry if this is a registered workspace
        if workspace_id:
            await index_workspace_and_update_registry(workspace_id, workspace_path, registry)

        # Format result
        result = [
            f"✅ Indexing complete: {workspace_path}",
            f"  📁 Files processed: {stats['indexed'] + stats['updated']}",
            f"  ✨ Symbols indexed: {stats.get('total_symbols', 0)}",
            f"  ⏭️  Skipped (unchanged): {stats['skipped']}",
            f"  🗑️  Deleted: {stats['deleted']}",
        ]

        if stats["errors"] > 0:
            result.append(f"  ⚠️  Errors: {stats['errors']}")

        storage.close()
        return "\n".join(result)

    except Exception as e:
        storage.close()
        return f"❌ Indexing failed: {e}"
