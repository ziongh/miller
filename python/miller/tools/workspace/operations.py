"""Workspace CRUD operations: add, remove, refresh, clean."""

import shutil
from pathlib import Path
from typing import Optional

from miller import server_state
from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry

from .helpers import index_workspace_and_update_registry


async def handle_add(
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
    # IMPORTANT: File watcher is started AFTER indexing completes to avoid
    # memory corruption from concurrent access to embeddings/vector_store
    try:
        stats, symbol_count, file_count = await index_workspace_and_update_registry(
            workspace_id, workspace_path, registry
        )

        # Create a WorkspaceScanner for this workspace and add to file watcher
        # Note: File watcher is added AFTER indexing completes (not during)
        if server_state.embeddings and server_state.storage and server_state.vector_store:
            from miller.workspace import WorkspaceScanner
            from miller.ignore_patterns import load_all_ignores

            # Create scanner for this workspace (for real-time updates via watcher)
            scanner = WorkspaceScanner(
                workspace_root=workspace_path,
                storage=server_state.storage,
                embeddings=server_state.embeddings,
                vector_store=server_state.vector_store,
                workspace_id=workspace_id,
            )

            # Store scanner in workspace_scanners map
            server_state.workspace_scanners[workspace_id] = scanner

            # NOW add to multi-workspace file watcher (indexing is complete, safe to watch)
            if server_state.file_watcher:
                ignore_spec = load_all_ignores(workspace_path)
                pattern_strings = {p.pattern for p in ignore_spec.patterns}

                # Get initial hashes from indexed files
                # Query fresh from DB since indexing just completed
                indexed_files = server_state.storage.get_all_files()
                # Filter to only this workspace's files (workspace_id prefix)
                initial_hashes = {
                    f["path"]: f["hash"]
                    for f in indexed_files
                    if f.get("hash") and f.get("workspace_id") == workspace_id
                }

                await server_state.file_watcher.add_workspace(
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    scanner=scanner,
                    storage=server_state.storage,
                    vector_store=server_state.vector_store,
                    ignore_patterns=pattern_strings,
                    initial_hashes=initial_hashes,
                )

        # Return success message
        files_processed = stats.get("indexed", 0) + stats.get("updated", 0)
        output = [
            f"✅ Successfully added reference workspace: {name}",
            f"  Workspace ID: {workspace_id}",
            f"  Path: {workspace_path}",
            f"  Files indexed: {files_processed:,}",
            f"  Symbols indexed: {symbol_count:,}",
            f"  File watcher: {'active' if server_state.file_watcher and server_state.file_watcher.is_watching(workspace_id) else 'not started'}",
        ]

        return "\n".join(output)

    except Exception as e:
        # Clean up on failure
        registry.remove_workspace(workspace_id)
        # Also remove from scanners and watcher if added
        server_state.workspace_scanners.pop(workspace_id, None)
        if server_state.file_watcher:
            await server_state.file_watcher.remove_workspace(workspace_id)
        return f"Error indexing workspace: {str(e)}"


async def handle_remove(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
    """
    Handle remove operation - remove workspace and delete its data.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to remove

    Returns:
        Success or error message
    """
    # Validate parameter - workspace_id is REQUIRED
    if not workspace_id:
        return (
            "Error: 'workspace' parameter required for remove operation.\n"
            "Use manage_workspace(operation='list') to see available workspace IDs."
        )

    # Get workspace before removing (to show name in confirmation)
    workspace = registry.get_workspace(workspace_id)
    if not workspace:
        return f"Error: Workspace '{workspace_id}' not found"

    workspace_name = workspace.name

    # Stop file watcher for this workspace first
    if server_state.file_watcher:
        await server_state.file_watcher.remove_workspace(workspace_id)

    # Remove scanner from map
    server_state.workspace_scanners.pop(workspace_id, None)

    # Clear workspace data from unified storage
    if server_state.storage:
        server_state.storage.clear_workspace(workspace_id)

    if server_state.vector_store:
        server_state.vector_store.clear_workspace(workspace_id)

    # Remove from registry
    registry.remove_workspace(workspace_id)

    # Note: In unified DB architecture, we don't delete per-workspace directories
    # All data is in the shared .miller/symbols.db and .miller/vectors.lance
    # The clear_workspace() calls above removed workspace-specific data

    # Return success message
    return f"✅ Successfully removed workspace: {workspace_name}\n  Workspace ID: {workspace_id}\n  Data cleared from unified storage"


async def handle_refresh(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
    """
    Handle refresh operation - re-index workspace to detect changes.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to refresh

    Returns:
        Success message with statistics
    """
    # Validate parameter - workspace_id is REQUIRED (aligned with Julie)
    if not workspace_id:
        return (
            "Error: 'workspace' parameter required for refresh operation.\n"
            "Use manage_workspace(operation='list') to see available workspace IDs."
        )

    # Get workspace
    workspace = registry.get_workspace(workspace_id)
    if not workspace:
        return f"Error: Workspace '{workspace_id}' not found"

    workspace_name = workspace.name
    workspace_path = Path(workspace.path)

    # Verify workspace path still exists
    if not workspace_path.exists():
        return f"Error: Workspace path no longer exists: {workspace.path}\n  Use 'clean' operation to remove orphaned workspaces."

    # Re-index the workspace
    try:
        stats, symbol_count, file_count = await index_workspace_and_update_registry(
            workspace_id, workspace_path, registry
        )

        # Format result message
        output = [f"✅ Refreshed workspace: {workspace_name}"]

        # Show what changed
        if stats.get("indexed", 0) > 0:
            output.append(f"  📄 Indexed {stats['indexed']} new file(s)")

        if stats.get("updated", 0) > 0:
            output.append(f"  🔄 Updated {stats['updated']} changed file(s)")

        if stats.get("deleted", 0) > 0:
            output.append(f"  🗑️  Removed {stats['deleted']} deleted file(s)")

        if stats.get("skipped", 0) > 0:
            output.append(f"  ⏭️  Skipped {stats['skipped']} unchanged file(s)")

        # Show totals
        output.append(f"  Total: {file_count:,} files, {symbol_count:,} symbols")

        # If nothing changed
        if all(stats.get(k, 0) == 0 for k in ["indexed", "updated", "deleted"]):
            return f"✅ Workspace '{workspace_name}' is up to date\n  No changes detected"

        return "\n".join(output)

    except Exception as e:
        return f"Error refreshing workspace: {str(e)}"


async def handle_clean(registry: WorkspaceRegistry) -> str:
    """
    Handle clean operation - remove orphaned workspaces.

    Orphaned workspaces are those whose paths no longer exist.

    Args:
        registry: WorkspaceRegistry instance

    Returns:
        Success message with statistics
    """
    workspaces = registry.list_workspaces()

    if not workspaces:
        return "No workspaces registered. Nothing to clean."

    # Find orphaned workspaces (paths that don't exist)
    orphaned = []
    for ws in workspaces:
        workspace_path = Path(ws["path"])
        if not workspace_path.exists():
            orphaned.append(ws)

    if not orphaned:
        return f"✅ All {len(workspaces)} workspace(s) are valid. Nothing to clean."

    # Remove orphaned workspaces
    removed_count = 0
    removed_names = []

    for ws in orphaned:
        workspace_id = ws["workspace_id"]
        workspace_name = ws["name"]

        try:
            # Remove from registry first
            registry.remove_workspace(workspace_id)

            # Delete workspace data directories
            db_path = get_workspace_db_path(workspace_id)
            vector_path = get_workspace_vector_path(workspace_id)

            # Delete DB directory (contains symbols.db)
            if db_path.parent.exists():
                try:
                    shutil.rmtree(db_path.parent)
                except Exception:
                    pass  # Best effort - registry is already cleaned

            # Delete vector directory (same parent as DB in our design)
            # But check if it's separate
            if vector_path.parent.exists() and vector_path.parent != db_path.parent:
                try:
                    shutil.rmtree(vector_path.parent)
                except Exception:
                    pass

            removed_count += 1
            removed_names.append(workspace_name)

        except Exception:
            # Continue with other workspaces if one fails
            continue

    # Format result message
    output = [f"✅ Cleaned {removed_count} orphaned workspace(s):"]

    for name in removed_names:
        output.append(f"  • {name}")

    output.append(f"\nRemaining: {len(workspaces) - removed_count} valid workspace(s)")

    return "\n".join(output)


async def handle_optimize(
    registry: WorkspaceRegistry, workspace_id: Optional[str] = None
) -> str:
    """
    Handle optimize operation - compact and cleanup database storage.

    This forces database maintenance operations that normally happen at the end
    of indexing. Useful when the system feels slow or disk usage is high.

    Operations performed:
    1. SQLite: PRAGMA optimize + WAL checkpoint
    2. LanceDB: Compaction (merges fragments) + Cleanup (removes ghost data)

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Optional workspace ID (defaults to primary)

    Returns:
        Success or error message
    """
    import asyncio
    from miller.storage.manager import StorageManager
    from miller.embeddings.vector_store import VectorStore

    # Default to primary workspace
    if workspace_id is None:
        workspaces = registry.list_workspaces()
        primary = next((w for w in workspaces if w.get("workspace_type") == "primary"), None)
        if primary:
            workspace_id = primary.get("workspace_id")

    if not workspace_id:
        return "Error: No workspace found to optimize"

    # Get workspace info for path resolution
    workspace_info = registry.get_workspace(workspace_id)
    if not workspace_info:
        return f"Error: Workspace '{workspace_id}' not found"

    # Get paths for this workspace
    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    if not db_path.exists():
        return f"Error: Database not found for workspace '{workspace_id}'"

    output = [f"🔧 Optimizing workspace: {workspace_info.get('name', workspace_id)}"]

    # 1. Optimize SQLite
    try:
        storage = StorageManager(str(db_path))
        storage.optimize()
        storage.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        storage.close()
        output.append("✅ SQLite database optimized and checkpointed")
    except Exception as e:
        output.append(f"⚠️ SQLite optimization failed: {e}")

    # 2. Optimize LanceDB
    if vector_path.exists():
        try:
            vector_store = VectorStore(str(vector_path))
            result = await asyncio.to_thread(vector_store.optimize)
            vector_store.close()
            if result:
                output.append(f"✅ Vector Store compacted and cleaned ({result.get('elapsed_seconds', 0):.2f}s)")
            else:
                output.append("⚠️ Vector Store optimization returned no results")
        except Exception as e:
            output.append(f"⚠️ Vector Store optimization failed: {e}")
    else:
        output.append("ℹ️ No vector store found (skipped)")

    return "\n".join(output)
