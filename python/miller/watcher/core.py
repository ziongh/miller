"""
Core file watching implementation with WSL2 fallback.

This module provides the FileWatcher class that monitors a workspace
directory and triggers callbacks when files change.

On native platforms (Linux, macOS, Windows), uses miller_core.PyFileWatcher (Rust) for:
- Zero GIL contention (file monitoring runs entirely in Rust)
- Hash-based change detection (only notifies when content actually changes)
- Efficient handling of 100k+ files
- Cross-platform support (inotify, FSEvents, ReadDirectoryChangesW)

On WSL2 with Windows-mounted paths (/mnt/c/, /mnt/d/, etc.), falls back to
Python's watchdog library because inotify events don't propagate correctly
across the 9P filesystem bridge. Native Linux paths within WSL2 use Rust.
"""

import asyncio
import logging
import os
import platform
from pathlib import Path
from typing import Callable, Optional

from miller.watcher.types import FileEvent, FileWatcherProtocol

logger = logging.getLogger(__name__)


def is_wsl2() -> bool:
    """
    Detect if we're running inside WSL2.

    Returns True if running in WSL2 environment, regardless of filesystem.
    """
    # Check for /proc/version containing "microsoft" (case insensitive)
    try:
        with open("/proc/version", "r") as f:
            version = f.read().lower()
            return "microsoft" in version or "wsl" in version
    except (FileNotFoundError, PermissionError):
        pass

    # Check WSL environment variable
    if os.environ.get("WSL_DISTRO_NAME"):
        return True

    # Check platform
    if platform.system() == "Linux":
        try:
            uname = os.uname()
            return "microsoft" in uname.release.lower()
        except AttributeError:
            pass

    return False


def is_windows_mount(path: Path) -> bool:
    """
    Check if a path is on a Windows-mounted filesystem in WSL2.

    Windows drives are mounted under /mnt/ (e.g., /mnt/c/, /mnt/d/).
    These paths use the 9P protocol which doesn't support inotify properly.

    Args:
        path: Path to check (should be resolved/absolute)

    Returns:
        True if path is on a Windows mount, False otherwise
    """
    path_str = str(path.resolve())

    # Check for /mnt/<drive letter>/ pattern
    if path_str.startswith("/mnt/") and len(path_str) > 6:
        # /mnt/c, /mnt/d, etc.
        drive_letter = path_str[5]
        if drive_letter.isalpha() and (len(path_str) == 6 or path_str[6] == "/"):
            return True

    return False


# Cache WSL2 detection result
_IS_WSL2: Optional[bool] = None


def get_is_wsl2() -> bool:
    """Get cached WSL2 detection result."""
    global _IS_WSL2
    if _IS_WSL2 is None:
        _IS_WSL2 = is_wsl2()
        if _IS_WSL2:
            logger.info("Detected WSL2 environment")
    return _IS_WSL2


def needs_watchdog_fallback(workspace_path: Path) -> bool:
    """
    Determine if watchdog fallback is needed for the given workspace.

    Fallback is only needed when BOTH conditions are true:
    1. Running in WSL2 environment
    2. Workspace is on a Windows-mounted filesystem (/mnt/c/, /mnt/d/, etc.)

    Native Linux paths within WSL2 (e.g., /home/user/projects/) work fine
    with the Rust inotify-based watcher.

    Args:
        workspace_path: Root directory of the workspace

    Returns:
        True if watchdog fallback should be used
    """
    if not get_is_wsl2():
        return False

    if is_windows_mount(workspace_path):
        logger.info(
            f"Workspace {workspace_path} is on Windows mount - using watchdog fallback"
        )
        return True

    logger.debug(
        f"Workspace {workspace_path} is on native Linux filesystem - using Rust watcher"
    )
    return False


class FileWatcher:
    """
    File watcher with automatic WSL2/Windows-mount fallback.

    On native platforms (including native Linux paths in WSL2), uses the
    Rust-native PyFileWatcher for high performance with inotify/FSEvents/etc.

    On WSL2 with Windows-mounted paths (/mnt/c/, /mnt/d/, etc.), falls back
    to Python's watchdog library because inotify doesn't work across 9P.

    Constructor Args:
    -----------------
    workspace_path: Root directory to watch
    indexing_callback: Async function to call when files change
        Signature: async def callback(events: list[tuple[FileEvent, Path, Optional[str]]]) -> None
        Where the third element is the new file hash (None for deletions)
    ignore_patterns: Optional set of gitignore-style patterns to exclude
    initial_hashes: Optional dict mapping file paths to their known hashes

    Example Usage:
    --------------
    >>> async def on_files_changed(events):
    ...     for event_type, file_path, new_hash in events:
    ...         if event_type == FileEvent.DELETED:
    ...             await storage.delete_file(file_path)
    ...         else:
    ...             await scanner._index_file(file_path)
    ...             watcher.update_hash(str(file_path), new_hash)
    ...
    >>> watcher = FileWatcher(
    ...     workspace_path=Path("/workspace"),
    ...     indexing_callback=on_files_changed,
    ...     ignore_patterns={".git", "node_modules", "*.pyc"},
    ...     initial_hashes={"src/main.py": "abc123..."}
    ... )
    >>> watcher.start()
    >>> # ... watcher runs in background ...
    >>> watcher.stop()
    """

    def __init__(
        self,
        workspace_path: Path,
        indexing_callback: Callable[[list[tuple[FileEvent, Path, Optional[str]]]], None],
        ignore_patterns: Optional[set[str]] = None,
        initial_hashes: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Initialize file watcher (not started yet).

        Args:
        -----
        workspace_path: Root directory to watch recursively
        indexing_callback: Async function called when files change
        ignore_patterns: Gitignore-style patterns to exclude
        initial_hashes: Dict mapping file paths to their known hashes
                       (used to detect if content actually changed)

        Raises:
        -------
        FileNotFoundError: If workspace_path doesn't exist
        ValueError: If workspace_path is not a directory
        TypeError: If indexing_callback not callable
        """
        # Validate workspace exists and is directory
        if not workspace_path.exists():
            raise FileNotFoundError(f"Workspace path does not exist: {workspace_path}")
        if not workspace_path.is_dir():
            raise ValueError(f"Workspace path is not a directory: {workspace_path}")

        # Validate callback is callable
        if not callable(indexing_callback):
            raise TypeError("indexing_callback must be callable")

        self._workspace_path = workspace_path.resolve()
        self._indexing_callback = indexing_callback
        self._ignore_patterns = list(ignore_patterns) if ignore_patterns else []
        self._initial_hashes = initial_hashes or {}

        # Watcher instance (Rust or Python, depending on platform)
        self._rust_watcher = None
        self._watchdog_observer = None

        # Watchdog fallback components
        self._debounce_queue = None
        self._event_handler = None

        # Event loop for async callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Track if we're using fallback (only for Windows mounts in WSL2)
        self._use_fallback = needs_watchdog_fallback(self._workspace_path)

    def start(self) -> None:
        """
        Start watching workspace.

        Raises:
        -------
        RuntimeError: If already running
        """
        if self.is_running():
            raise RuntimeError("FileWatcher is already running")

        # Get or create event loop
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - we'll create one when needed
            self._loop = None

        if self._use_fallback:
            self._start_watchdog()
        else:
            self._start_rust()

    def _start_rust(self) -> None:
        """Start the Rust-native file watcher."""
        from miller import miller_core

        # Create Rust watcher
        self._rust_watcher = miller_core.PyFileWatcher(
            str(self._workspace_path),
            self._initial_hashes,
            self._ignore_patterns,
        )

        logger.info(
            f"Starting Rust file watcher for {self._workspace_path} "
            f"({self._rust_watcher.tracked_file_count()} files tracked)"
        )

        # Start watching with callback bridge
        self._rust_watcher.start(self._on_rust_events)

    def _start_watchdog(self) -> None:
        """Start the Python watchdog fallback (for WSL2)."""
        from watchdog.observers import Observer
        from miller.watcher.handlers import FileWatcherEventHandler
        from miller.watcher.debouncer import DebounceQueue

        logger.info(
            f"Starting watchdog file watcher for {self._workspace_path} "
            f"(WSL2 fallback mode)"
        )

        # Create debounce queue with flush callback
        self._debounce_queue = DebounceQueue(
            debounce_delay=0.2,
            flush_callback=self._on_watchdog_flush,
            loop=self._loop,
        )

        # Create event handler (passes self - FileWatcher instance)
        self._event_handler = FileWatcherEventHandler(watcher=self)

        # Create and start observer
        self._watchdog_observer = Observer()
        self._watchdog_observer.schedule(
            self._event_handler,
            str(self._workspace_path),
            recursive=True,
        )
        self._watchdog_observer.start()

    async def handle_event(self, event_type: FileEvent, file_path: Path) -> None:
        """
        Handle file event from watchdog (WSL2 fallback mode).

        Called by FileWatcherEventHandler when a file system event occurs.
        Adds the event to the debounce queue for batched processing.

        Args:
        -----
        event_type: Type of file event (CREATED, MODIFIED, DELETED)
        file_path: Absolute path to the changed file
        """
        # Check if path matches ignore patterns
        if self._should_ignore(file_path):
            return

        # Add to debounce queue
        if hasattr(self, "_debounce_queue") and self._debounce_queue:
            self._debounce_queue.add(event_type, file_path)

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if a file path should be ignored based on patterns."""
        import fnmatch

        # Hardcoded check for temporary files (defense in depth)
        # These cause race conditions when created/deleted rapidly by tests, editors, etc.
        file_name = file_path.name
        if (
            file_name.endswith(".tmp")
            or ".tmp." in file_name  # pytest-style: file.py.tmp.12345.67890
            or file_name.endswith("~")  # Editor backup files
            or file_name.endswith(".swp")  # Vim swap
            or file_name.endswith(".swo")  # Vim swap
            or file_name.startswith(".#")  # Emacs lock files
        ):
            return True

        rel_path = str(file_path.relative_to(self._workspace_path))

        for pattern in self._ignore_patterns:
            # Handle directory patterns (e.g., ".git", "node_modules")
            if "/" not in pattern and "*" not in pattern:
                # Simple name pattern - check each path component
                for part in file_path.parts:
                    if part == pattern:
                        return True
            # Handle glob patterns
            elif fnmatch.fnmatch(rel_path, pattern):
                return True
            elif fnmatch.fnmatch(file_path.name, pattern):
                return True

        return False

    def _on_rust_events(self, events: list[tuple[str, str, Optional[str]]]) -> None:
        """
        Bridge callback from Rust to Python.

        Args:
        -----
        events: List of (event_type, file_path, new_hash) tuples from Rust
        """
        if not events:
            return

        # Convert to Python types
        converted_events = []
        for event_type_str, path_str, new_hash in events:
            # Map string event type to enum
            event_type = {
                "created": FileEvent.CREATED,
                "modified": FileEvent.MODIFIED,
                "deleted": FileEvent.DELETED,
            }.get(event_type_str, FileEvent.MODIFIED)

            file_path = self._workspace_path / path_str
            converted_events.append((event_type, file_path, new_hash))

        logger.debug(f"Received {len(converted_events)} file change events from Rust watcher")
        self._invoke_callback(converted_events)

    def _on_watchdog_flush(self, events: list[tuple[FileEvent, Path]]) -> None:
        """
        Handle flushed events from watchdog debounce queue.

        Args:
        -----
        events: List of (event_type, file_path) tuples from debouncer
        """
        if not events:
            return

        # Convert to 3-tuple format (with hash computation)
        import hashlib

        converted_events = []
        for event_type, file_path in events:
            new_hash = None
            if event_type != FileEvent.DELETED and file_path.exists():
                # Compute hash for non-deleted files
                try:
                    content = file_path.read_bytes()
                    new_hash = hashlib.blake2b(content).hexdigest()
                except (OSError, PermissionError):
                    pass
            converted_events.append((event_type, file_path, new_hash))

        logger.debug(f"Received {len(converted_events)} file change events from watchdog")
        self._invoke_callback(converted_events)

    def _invoke_callback(self, events: list[tuple[FileEvent, Path, Optional[str]]]) -> None:
        """Invoke the indexing callback with events."""
        try:
            if asyncio.iscoroutinefunction(self._indexing_callback):
                # Async callback - need to run in event loop
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._indexing_callback(events), self._loop
                    )
                else:
                    # Create new event loop for this call
                    asyncio.run(self._indexing_callback(events))
            else:
                # Sync callback
                self._indexing_callback(events)
        except Exception as e:
            logger.error(f"Error in indexing callback: {e}")

    def stop(self) -> None:
        """
        Stop watching and clean up resources.
        """
        if self._rust_watcher is not None:
            logger.info("Stopping Rust file watcher")
            self._rust_watcher.stop()
            self._rust_watcher = None

        if self._watchdog_observer is not None:
            logger.info("Stopping watchdog file watcher")
            self._watchdog_observer.stop()
            self._watchdog_observer.join()
            self._watchdog_observer = None
            self._debounce_queue = None
            self._event_handler = None

    def is_running(self) -> bool:
        """Check if watcher is currently active."""
        if self._rust_watcher is not None:
            return self._rust_watcher.is_running()
        if self._watchdog_observer is not None:
            return self._watchdog_observer.is_alive()
        return False

    def update_hash(self, file_path: str, new_hash: str) -> None:
        """
        Update the known hash for a file.

        Call this after successfully indexing a file to prevent
        redundant re-indexing on subsequent saves without changes.

        Args:
        -----
        file_path: Relative path to the file
        new_hash: New Blake3 hash of file content
        """
        if self._rust_watcher:
            self._rust_watcher.update_hash(file_path, new_hash)
        # Note: Watchdog fallback doesn't track hashes (re-indexes on every change)

    def remove_hash(self, file_path: str) -> None:
        """
        Remove a file from hash tracking.

        Call this after a file is deleted.

        Args:
        -----
        file_path: Relative path to the file
        """
        if self._rust_watcher:
            self._rust_watcher.remove_hash(file_path)

    def tracked_file_count(self) -> int:
        """Get the number of files being tracked."""
        if self._rust_watcher:
            return self._rust_watcher.tracked_file_count()
        return len(self._initial_hashes)

    def get_tracked_files(self) -> list[str]:
        """Get list of all tracked file paths."""
        if self._rust_watcher:
            return self._rust_watcher.get_tracked_files()
        return list(self._initial_hashes.keys())


# Legacy compatibility: Keep old class name as alias
RustFileWatcher = FileWatcher
