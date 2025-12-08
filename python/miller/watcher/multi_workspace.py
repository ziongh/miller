"""
Multi-workspace file watcher manager.

Manages FileWatcher instances for multiple workspaces, routing file change
events to the appropriate workspace-specific callbacks.

This enables the unified database architecture where all workspaces share
a single SQLite database and LanceDB vector store, but each workspace
has its own file watcher for real-time updates.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from miller.watcher.core import FileWatcher
from miller.watcher.types import FileEvent

logger = logging.getLogger(__name__)


class MultiWorkspaceWatcher:
    """
    Manages file watchers for multiple workspaces.

    Each workspace gets its own FileWatcher instance, with file change events
    routed to a workspace-specific callback that knows the workspace_id.

    This is used with the unified database architecture where:
    - All workspaces share a single SQLite database and LanceDB vector store
    - Each workspace has its own workspace_id for filtering/isolation
    - File paths in the database are qualified with workspace_id

    Example Usage:
    --------------
    >>> watcher_manager = MultiWorkspaceWatcher()
    >>>
    >>> # Add primary workspace
    >>> watcher_manager.add_workspace(
    ...     workspace_id="primary",
    ...     workspace_path=Path("/main/project"),
    ...     scanner=primary_scanner,
    ...     storage=storage,
    ...     vector_store=vector_store,
    ...     ignore_patterns={".git", "node_modules"},
    ...     initial_hashes={"src/main.py": "abc123..."}
    ... )
    >>>
    >>> # Add reference workspace
    >>> watcher_manager.add_workspace(
    ...     workspace_id="utils_abc123",
    ...     workspace_path=Path("/shared/utils"),
    ...     scanner=utils_scanner,
    ...     storage=storage,
    ...     vector_store=vector_store,
    ...     ignore_patterns={".git"},
    ...     initial_hashes={}
    ... )
    >>>
    >>> # Later: remove a workspace
    >>> watcher_manager.remove_workspace("utils_abc123")
    >>>
    >>> # Shutdown
    >>> watcher_manager.stop_all()
    """

    def __init__(self) -> None:
        """Initialize the multi-workspace watcher manager."""
        # Map workspace_id -> FileWatcher instance
        self._watchers: dict[str, FileWatcher] = {}

        # Map workspace_id -> associated metadata (scanner, paths, etc.)
        self._workspace_data: dict[str, dict] = {}

        # Lock for thread-safe access
        self._lock = asyncio.Lock()

    async def add_workspace(
        self,
        workspace_id: str,
        workspace_path: Path,
        scanner: "WorkspaceScanner",  # noqa: F821
        storage: "StorageManager",  # noqa: F821
        vector_store: "VectorStore",  # noqa: F821
        ignore_patterns: Optional[set[str]] = None,
        initial_hashes: Optional[dict[str, str]] = None,
        auto_start: bool = True,
    ) -> bool:
        """
        Add a workspace to be watched for file changes.

        Args:
            workspace_id: Unique identifier for this workspace
            workspace_path: Root directory of the workspace
            scanner: WorkspaceScanner instance for this workspace
            storage: StorageManager (shared across all workspaces)
            vector_store: VectorStore (shared across all workspaces)
            ignore_patterns: Gitignore-style patterns to exclude
            initial_hashes: Dict mapping file paths to their known hashes
            auto_start: Start watching immediately (default: True)

        Returns:
            True if workspace was added successfully, False if already exists
        """
        async with self._lock:
            if workspace_id in self._watchers:
                logger.warning(f"Workspace '{workspace_id}' already being watched")
                return False

            workspace_path = Path(workspace_path).resolve()

            if not workspace_path.exists():
                logger.error(f"Workspace path does not exist: {workspace_path}")
                return False

            if not workspace_path.is_dir():
                logger.error(f"Workspace path is not a directory: {workspace_path}")
                return False

            # Store workspace metadata
            self._workspace_data[workspace_id] = {
                "path": workspace_path,
                "scanner": scanner,
                "storage": storage,
                "vector_store": vector_store,
            }

            # Create workspace-specific callback
            callback = self._create_callback(workspace_id)

            try:
                # Create FileWatcher for this workspace
                watcher = FileWatcher(
                    workspace_path=workspace_path,
                    indexing_callback=callback,
                    ignore_patterns=ignore_patterns,
                    initial_hashes=initial_hashes or {},
                )

                self._watchers[workspace_id] = watcher

                if auto_start:
                    watcher.start()
                    logger.info(
                        f"Started file watcher for workspace '{workspace_id}' at {workspace_path}"
                    )
                else:
                    logger.info(
                        f"Added file watcher for workspace '{workspace_id}' (not started)"
                    )

                return True

            except Exception as e:
                logger.error(f"Failed to create watcher for workspace '{workspace_id}': {e}")
                # Cleanup on failure
                self._workspace_data.pop(workspace_id, None)
                return False

    def _create_callback(
        self, workspace_id: str
    ) -> Callable[[list[tuple[FileEvent, Path, Optional[str]]]], None]:
        """
        Create a workspace-specific callback for file change events.

        The callback captures the workspace_id in a closure, allowing the
        event handler to know which workspace a file belongs to.

        Args:
            workspace_id: Workspace identifier for this callback

        Returns:
            Async callback function for FileWatcher
        """

        async def on_files_changed(
            events: list[tuple[FileEvent, Path, Optional[str]]]
        ) -> None:
            """Handle file change events for a specific workspace."""
            await self._handle_workspace_events(workspace_id, events)

        return on_files_changed

    async def _handle_workspace_events(
        self,
        workspace_id: str,
        events: list[tuple[FileEvent, Path, Optional[str]]],
    ) -> None:
        """
        Handle file change events for a specific workspace.

        This is the core event handler that processes file changes and
        updates the unified database with workspace-qualified paths.

        Args:
            workspace_id: Workspace that generated these events
            events: List of (event_type, file_path, new_hash) tuples
        """
        if not events:
            return

        data = self._workspace_data.get(workspace_id)
        if not data:
            logger.warning(f"Received events for unknown workspace: {workspace_id}")
            return

        workspace_path = data["path"]
        scanner = data["scanner"]
        storage = data["storage"]
        vector_store = data["vector_store"]
        watcher = self._watchers.get(workspace_id)

        # Phase 1: Deduplicate events by file path (keep latest event per file)
        file_events: dict[Path, tuple[FileEvent, Optional[str]]] = {}
        for event_type, file_path, new_hash in events:
            if file_path in file_events:
                if event_type == FileEvent.DELETED:
                    file_events[file_path] = (event_type, new_hash)
                elif file_events[file_path][0] != FileEvent.DELETED:
                    file_events[file_path] = (event_type, new_hash)
            else:
                file_events[file_path] = (event_type, new_hash)

        # Phase 2: Separate deletions from indexing operations
        deleted_files: list[str] = []
        files_to_index: list[tuple[FileEvent, Path, Optional[str]]] = []

        for file_path, (event_type, new_hash) in file_events.items():
            if event_type == FileEvent.DELETED:
                rel_path = str(file_path.relative_to(workspace_path)).replace("\\", "/")
                deleted_files.append(rel_path)
            else:
                files_to_index.append((event_type, file_path, new_hash))

        # Phase 3: Batch process deletions
        if deleted_files:
            try:
                for rel_path in deleted_files:
                    storage.delete_file(rel_path)
                    if watcher:
                        watcher.remove_hash(rel_path)
                vector_store.delete_files_batch(deleted_files)
                logger.info(
                    f"[{workspace_id}] Deleted {len(deleted_files)} file(s) from index"
                )
            except Exception as e:
                logger.error(
                    f"[{workspace_id}] Error batch deleting files: {e}", exc_info=True
                )

        # Phase 4: Process indexing operations concurrently
        if files_to_index:

            async def index_one(
                event_type: FileEvent, file_path: Path, new_hash: Optional[str]
            ) -> tuple[bool, FileEvent, Path, Optional[str]]:
                """Index a single file and return result."""
                try:
                    success = await scanner._index_file(file_path)
                    return (success, event_type, file_path, new_hash)
                except Exception as e:
                    logger.error(
                        f"[{workspace_id}] Error indexing {file_path}: {e}",
                        exc_info=True,
                    )
                    return (False, event_type, file_path, new_hash)

            results = await asyncio.gather(
                *[index_one(et, fp, nh) for et, fp, nh in files_to_index]
            )

            # Log results and update hash cache
            any_success = False
            for success, event_type, file_path, new_hash in results:
                rel_path = str(file_path.relative_to(workspace_path)).replace("\\", "/")
                if success:
                    any_success = True
                    action = "Indexed" if event_type == FileEvent.CREATED else "Updated"
                    logger.info(f"[{workspace_id}] {action}: {rel_path}")
                    if new_hash and watcher:
                        watcher.update_hash(rel_path, new_hash)
                else:
                    logger.warning(f"[{workspace_id}] Failed to index: {rel_path}")

            # Refresh reachability if files changed
            if any_success or deleted_files:
                from miller.closure import is_reachability_stale, refresh_reachability

                if await asyncio.to_thread(is_reachability_stale, storage):
                    logger.info(f"[{workspace_id}] Refreshing reachability...")
                    count = await asyncio.to_thread(refresh_reachability, storage, 10)
                    logger.info(f"[{workspace_id}] Reachability refreshed: {count} entries")

    async def remove_workspace(self, workspace_id: str) -> bool:
        """
        Remove a workspace from file watching.

        Stops the watcher and removes all associated resources.

        Args:
            workspace_id: Workspace to remove

        Returns:
            True if workspace was removed, False if not found
        """
        async with self._lock:
            watcher = self._watchers.pop(workspace_id, None)
            self._workspace_data.pop(workspace_id, None)

            if watcher is None:
                logger.warning(f"Workspace '{workspace_id}' not found")
                return False

            try:
                if watcher.is_running():
                    watcher.stop()
                logger.info(f"Removed file watcher for workspace '{workspace_id}'")
                return True
            except Exception as e:
                logger.error(f"Error stopping watcher for '{workspace_id}': {e}")
                return False

    def stop_all(self) -> None:
        """Stop all file watchers."""
        for workspace_id, watcher in list(self._watchers.items()):
            try:
                if watcher.is_running():
                    watcher.stop()
                    logger.info(f"Stopped file watcher for workspace '{workspace_id}'")
            except Exception as e:
                logger.error(f"Error stopping watcher for '{workspace_id}': {e}")

        self._watchers.clear()
        self._workspace_data.clear()
        logger.info("All file watchers stopped")

    def get_workspace_ids(self) -> list[str]:
        """Get list of all watched workspace IDs."""
        return list(self._watchers.keys())

    def is_watching(self, workspace_id: str) -> bool:
        """Check if a workspace is being watched."""
        watcher = self._watchers.get(workspace_id)
        return watcher is not None and watcher.is_running()

    def get_watcher(self, workspace_id: str) -> Optional[FileWatcher]:
        """Get the FileWatcher instance for a workspace (if any)."""
        return self._watchers.get(workspace_id)

    def update_hash(self, workspace_id: str, file_path: str, new_hash: str) -> None:
        """
        Update the known hash for a file in a specific workspace.

        Args:
            workspace_id: Workspace containing the file
            file_path: Relative path to the file
            new_hash: New Blake3 hash of file content
        """
        watcher = self._watchers.get(workspace_id)
        if watcher:
            watcher.update_hash(file_path, new_hash)

    def __len__(self) -> int:
        """Get number of watched workspaces."""
        return len(self._watchers)
