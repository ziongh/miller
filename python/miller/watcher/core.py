"""
Core file watching implementation using watchdog.

This module provides the FileWatcher class that monitors a workspace
directory and triggers callbacks when files change.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from miller.watcher.debouncer import DebounceQueue
from miller.watcher.handlers import FileWatcherEventHandler
from miller.watcher.types import FileEvent, FileWatcherProtocol

logger = logging.getLogger(__name__)


class FileWatcher:
    """
    Concrete implementation of file watcher using watchdog library.

    This class implements FileWatcherProtocol using the watchdog library.

    Constructor Args:
    -----------------
    workspace_path: Root directory to watch
    indexing_callback: Async function to call when files change
        Signature: async def callback(events: list[tuple[FileEvent, Path]]) -> None
    ignore_patterns: Optional set of gitignore-style patterns to exclude

    Example Usage:
    --------------
    >>> async def on_files_changed(events):
    ...     for event_type, file_path in events:
    ...         if event_type == FileEvent.DELETED:
    ...             await storage.delete_file(file_path)
    ...         else:
    ...             await scanner._index_file(file_path)
    ...
    >>> watcher = FileWatcher(
    ...     workspace_path=Path("/workspace"),
    ...     indexing_callback=on_files_changed,
    ...     ignore_patterns={".git", "node_modules", "*.pyc"}
    ... )
    >>> watcher.start()
    >>> # ... watcher runs in background ...
    >>> watcher.stop()

    Implementation:
    ---------------
    1. Uses watchdog.observers.Observer for cross-platform watching
    2. Uses watchdog.events.FileSystemEventHandler for callbacks
    3. Uses asyncio.Queue for thread-safe event passing
    4. Uses DebounceQueue to batch rapid changes
    5. Respects pathspec patterns from .gitignore
    6. Handles Windows/Unix path differences
    """

    def __init__(
        self,
        workspace_path: Path,
        indexing_callback: Callable[[list[tuple[FileEvent, Path]]], None],
        ignore_patterns: Optional[set[str]] = None,
        debounce_delay: float = 0.2,
    ) -> None:
        """
        Initialize file watcher (not started yet).

        Args:
        -----
        workspace_path: Root directory to watch recursively
        indexing_callback: Async function called when files change
        ignore_patterns: Gitignore-style patterns to exclude
        debounce_delay: Seconds to wait before flushing events (default: 0.2)

        Raises:
        -------
        FileNotFoundError: If workspace_path doesn't exist
        ValueError: If workspace_path is not a directory or debounce_delay invalid
        TypeError: If indexing_callback not callable
        """
        import pathspec

        # Validate workspace exists and is directory
        if not workspace_path.exists():
            raise FileNotFoundError(f"Workspace path does not exist: {workspace_path}")
        if not workspace_path.is_dir():
            raise ValueError(f"Workspace path is not a directory: {workspace_path}")

        # Validate callback is callable
        if not callable(indexing_callback):
            raise TypeError("indexing_callback must be callable")

        # Validate debounce delay
        if debounce_delay <= 0 or debounce_delay > 10:
            raise ValueError("debounce_delay must be between 0 and 10 seconds")

        self._workspace_path = workspace_path.resolve()
        self._indexing_callback = indexing_callback
        self._debounce_delay = debounce_delay

        # Set up ignore patterns using pathspec
        self._ignore_patterns = ignore_patterns or set()
        if self._ignore_patterns:
            self._pathspec = pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, self._ignore_patterns
            )
        else:
            self._pathspec = None

        # Initialize watchdog observer (not started)
        self._observer: Optional["Observer"] = None  # noqa: F821
        self._running = False

        # Initialize debounce queue
        self._debounce_queue: Optional[DebounceQueue] = None

        # Event loop for async callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """
        Start watching workspace.

        Raises:
        -------
        RuntimeError: If already running
        """
        from watchdog.observers import Observer

        if self._running:
            raise RuntimeError("FileWatcher is already running")

        # Try to get running loop, otherwise create a new one
        try:
            self._loop = asyncio.get_running_loop()
            self._loop_thread = None  # Using existing loop
        except RuntimeError:
            # No running loop, create new one in background thread
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_event_loop, daemon=True, name="FileWatcherEventLoop"
            )
            self._loop_thread.start()

        # Create debounce queue with callback
        self._debounce_queue = DebounceQueue(
            debounce_delay=self._debounce_delay,
            flush_callback=self._indexing_callback,
            loop=self._loop,
        )

        # Create event handler
        handler = FileWatcherEventHandler(self)

        # Initialize seen files with existing files in workspace
        # This helps distinguish CREATED (new files) from MODIFIED (existing files)
        for file_path in self._workspace_path.rglob("*"):
            if file_path.is_file() and not self._should_ignore(file_path):
                handler._seen_files.add(file_path)

        # Create and start observer
        self._observer = Observer()
        self._observer.schedule(handler, str(self._workspace_path), recursive=True)
        self._observer.start()

        self._running = True

    def _run_event_loop(self) -> None:
        """Run event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def stop(self) -> None:
        """
        Stop watching and clean up resources.

        Flushes any pending debounced events before stopping.
        """
        if not self._running:
            return  # Safe to call if not running

        # Stop observer first to prevent new events
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)

        # Give a grace period for in-flight events to be added to queue
        # macOS FSEvents can be slow (up to 1-2 seconds latency)
        time.sleep(0.5)

        # Flush pending events
        if self._debounce_queue and self._loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self._debounce_queue.flush(), self._loop)
                future.result(timeout=1.0)
            except Exception:
                # Best effort flush - may timeout due to platform event latency
                pass

        # Stop event loop if we created it
        if self._loop and hasattr(self, "_loop_thread") and self._loop_thread:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread.is_alive():
                self._loop_thread.join(timeout=2.0)

        self._running = False
        self._observer = None
        self._debounce_queue = None
        self._loop = None

    def is_running(self) -> bool:
        """Check if watcher is currently active."""
        return self._running

    async def handle_event(self, event_type: FileEvent, file_path: Path) -> None:
        """
        Handle file system event internally.

        This is called by the watchdog observer when files change.

        Args:
        -----
        event_type: Type of file event
        file_path: Absolute path to the file that changed
        """
        # Validate file is within workspace
        try:
            file_path.relative_to(self._workspace_path)
        except ValueError:
            # File outside workspace, ignore
            return

        # Check if file should be ignored
        if self._should_ignore(file_path):
            return

        # Check file size (skip very large files >10MB)
        if file_path.exists() and event_type != FileEvent.DELETED:
            file_size = file_path.stat().st_size
            if file_size > 10 * 1024 * 1024:  # 10MB
                # Log warning and skip
                return

        # Add to debounce queue
        if self._debounce_queue:
            self._debounce_queue.add(event_type, file_path)

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if file should be ignored based on patterns."""
        if not self._pathspec:
            return False

        # Get relative path for pattern matching
        try:
            rel_path = file_path.relative_to(self._workspace_path)
        except ValueError:
            return True  # Outside workspace

        # Convert to Unix-style forward slashes
        rel_path_str = str(rel_path).replace("\\", "/")

        # Check if matches any ignore pattern
        return self._pathspec.match_file(rel_path_str)
