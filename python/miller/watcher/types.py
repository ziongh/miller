"""
File watcher type definitions and protocol.

This module defines the core types and protocols for file watching:
- FileEvent enum: Event types that trigger re-indexing
- FileWatcherProtocol: Interface contract for file watchers
"""

from enum import Enum
from pathlib import Path
from typing import Callable, Protocol


class FileEvent(Enum):
    """File system event types that trigger re-indexing."""

    CREATED = "created"  # New file added to workspace
    MODIFIED = "modified"  # Existing file content changed
    DELETED = "deleted"  # File removed from workspace
    MOVED = "moved"  # File renamed or moved (treat as delete + create)


class FileWatcherProtocol(Protocol):
    """
    Protocol defining the file watcher interface.

    The file watcher monitors a workspace directory and triggers callbacks
    when files change. It integrates with Miller's indexing system to provide
    real-time updates.

    Expected Behavior:
    ------------------
    1. Watch workspace recursively for file changes
    2. Debounce rapid changes (e.g., save triggers multiple events)
    3. Respect .gitignore patterns (don't watch ignored files)
    4. Handle large file batches efficiently (bulk operations)
    5. Gracefully handle errors (log but don't crash)
    6. Clean shutdown (stop watching, flush pending events)

    Performance Requirements:
    -------------------------
    - Event latency: < 500ms from file change to callback
    - Debounce window: 200ms (collect rapid changes)
    - Max batch size: 100 files per indexing operation
    - Memory overhead: < 50MB for typical workspace

    Thread Safety:
    --------------
    - Watchdog runs in separate thread
    - Callbacks executed in asyncio event loop
    - Use thread-safe queue for event passing
    """

    def start(self) -> None:
        """
        Start watching the workspace for file changes.

        Expected Behavior:
        ------------------
        - Start watchdog observer in background thread
        - Begin monitoring workspace directory recursively
        - Set up event handlers for file changes
        - Initialize debounce timer

        Error Conditions:
        -----------------
        - Raises RuntimeError if already started
        - Raises FileNotFoundError if workspace path doesn't exist
        - Raises PermissionError if no read access to workspace

        Post-conditions:
        ----------------
        - self.is_running() returns True
        - File changes trigger callbacks
        """
        ...

    def stop(self) -> None:
        """
        Stop watching and clean up resources.

        Expected Behavior:
        ------------------
        - Stop watchdog observer gracefully
        - Flush any pending debounced events
        - Wait for in-flight callbacks to complete
        - Clean up thread resources

        Error Conditions:
        -----------------
        - Safe to call if not running (no-op)
        - Timeout after 5 seconds if callbacks don't complete

        Post-conditions:
        ----------------
        - self.is_running() returns False
        - No further callbacks triggered
        """
        ...

    def is_running(self) -> bool:
        """
        Check if watcher is currently active.

        Returns:
        --------
        bool: True if watching, False otherwise

        Expected Behavior:
        ------------------
        - Returns True after start() succeeds
        - Returns False after stop() completes
        - Returns False before start() called
        """
        ...

    async def handle_event(self, event_type: FileEvent, file_path: Path) -> None:
        """
        Handle a file system event (internal callback).

        This is called by the watchdog observer when files change.
        Should NOT be called directly by users.

        Args:
        -----
        event_type: Type of file event (created, modified, deleted, moved)
        file_path: Absolute path to the file that changed

        Expected Behavior:
        ------------------
        1. Validate file_path is within workspace
        2. Check if file should be ignored (.gitignore patterns)
        3. Add to debounce queue (don't index immediately)
        4. If debounce timer expires, flush queue and trigger indexing

        Error Conditions:
        -----------------
        - Log warning if file_path outside workspace (ignore event)
        - Log warning if file doesn't exist (race condition)
        - Log error if indexing callback fails (but continue watching)

        Boundary Conditions:
        --------------------
        - Empty file (0 bytes): Should index successfully
        - Very large file (>10MB): Log warning, skip indexing
        - Binary file: Skip indexing (not source code)
        - Symlink: Resolve and index target if within workspace
        """
        ...
