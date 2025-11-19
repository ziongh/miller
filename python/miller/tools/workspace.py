"""
Workspace management MCP tool.

Provides operations to manage primary and reference workspaces.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


async def _index_workspace_and_update_registry(
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
    - stats: Show workspace statistics for a specific workspace
    - index: Index current or specified workspace (manual trigger)
             Note: Indexing also runs automatically in background after server starts
    - add: Add reference workspace (indexes into separate storage)
    - remove: Remove workspace and delete its data
    - clean: Clean up orphaned data (workspaces with deleted paths)
    - refresh: Re-index workspace to detect new/changed/deleted files
    - health: System health check (registry status, aggregate stats)

    Index vs Refresh:
    - index: Initial indexing of workspace, force rebuilds with force=True
    - refresh: Incremental update, detects file changes since last index

    Args:
        operation: Operation to perform
        path: Workspace path (for index, add)
        name: Workspace display name (for add)
        workspace_id: Workspace ID (for stats, remove, refresh)
        force: Force re-indexing even if up-to-date (for index, refresh)
        detailed: Include detailed per-workspace info (for health)

    Returns:
        Operation result message

    Examples:
        # Index current workspace
        manage_workspace(operation="index")

        # Force rebuild index
        manage_workspace(operation="index", force=True)

        # Add reference workspace
        manage_workspace(operation="add", path="/path/to/lib", name="MyLibrary")

        # Refresh workspace to detect changes
        manage_workspace(operation="refresh", workspace_id="mylib_abc123")

        # System health check
        manage_workspace(operation="health", detailed=True)
    """
    registry = WorkspaceRegistry()

    if operation == "list":
        return _handle_list(registry)

    elif operation == "stats":
        return _handle_stats(registry, workspace_id)

    elif operation == "index":
        return await _handle_index(registry, path, force)

    elif operation == "add":
        return await _handle_add(registry, path, name)

    elif operation == "remove":
        return await _handle_remove(registry, workspace_id)

    elif operation == "refresh":
        return await _handle_refresh(registry, workspace_id)

    elif operation == "clean":
        return await _handle_clean(registry)

    elif operation == "health":
        return _handle_health(registry, detailed)

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


async def _handle_index(
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
    from pathlib import Path

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
            await _index_workspace_and_update_registry(registry, workspace_id, workspace_path, storage)

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
        stats, symbol_count, file_count = await _index_workspace_and_update_registry(
            workspace_id, workspace_path, registry
        )

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


async def _handle_remove(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
    """
    Handle remove operation - remove workspace and delete its data.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to remove

    Returns:
        Success or error message
    """
    # Validate parameter
    if not workspace_id:
        return "Error: 'workspace_id' parameter required for remove operation"

    # Get workspace before removing (to show name in confirmation)
    workspace = registry.get_workspace(workspace_id)
    if not workspace:
        return f"Error: Workspace '{workspace_id}' not found"

    workspace_name = workspace.name

    # Remove from registry first
    registry.remove_workspace(workspace_id)

    # Delete workspace directories
    import shutil

    db_path = get_workspace_db_path(workspace_id)
    vector_path = get_workspace_vector_path(workspace_id)

    # Delete DB directory (contains symbols.db)
    if db_path.parent.exists():
        try:
            shutil.rmtree(db_path.parent)
        except Exception as e:
            # Log but don't fail - registry is already cleaned up
            pass

    # Delete vector directory (same parent as DB, so already deleted)
    # But check if it's separate (shouldn't be in our design)
    if vector_path.parent.exists() and vector_path.parent != db_path.parent:
        try:
            shutil.rmtree(vector_path.parent)
        except Exception:
            pass

    # Return success message
    return f"✅ Successfully removed workspace: {workspace_name}\n  Workspace ID: {workspace_id}"


async def _handle_refresh(registry: WorkspaceRegistry, workspace_id: Optional[str]) -> str:
    """
    Handle refresh operation - re-index workspace to detect changes.

    Args:
        registry: WorkspaceRegistry instance
        workspace_id: Workspace ID to refresh

    Returns:
        Success message with statistics
    """
    # Validate parameter
    if not workspace_id:
        return "Error: 'workspace_id' parameter required for refresh operation"

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
        stats, symbol_count, file_count = await _index_workspace_and_update_registry(
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


async def _handle_clean(registry: WorkspaceRegistry) -> str:
    """
    Handle clean operation - remove orphaned workspaces.

    Orphaned workspaces are those whose paths no longer exist.

    Args:
        registry: WorkspaceRegistry instance

    Returns:
        Success message with statistics
    """
    import shutil

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


def _handle_health(registry: WorkspaceRegistry, detailed: bool = False) -> str:
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
