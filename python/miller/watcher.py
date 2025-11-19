"""
File system watcher for real-time workspace indexing.

This module provides a file watcher that monitors the workspace for changes
and automatically re-indexes modified files. It follows the pattern established
by Julie's watcher implementation but uses Python's watchdog library.

CONTRACT DEFINITION (Test-First TDD - Phase 1: Define Contract)
===============================================================

This file defines the interface and expected behavior BEFORE implementation.
Tests will be written against this contract, then implementation follows.
"""

import asyncio
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Protocol


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


class DebounceQueue:
    """
    Queue that collects rapid file changes and batches them.

    Behavior:
    ---------
    When a file changes multiple times rapidly (e.g., auto-save), we don't
    want to re-index on every event. Instead:
    1. Collect events for debounce_delay seconds
    2. Deduplicate (same file, multiple events → one event)
    3. Flush batch to indexing callback

    Example:
    --------
    file.py modified at t=0ms
    file.py modified at t=50ms    } Collect these
    file.py modified at t=100ms   }
    → Flush at t=200ms with single "modified" event
    """

    def __init__(
        self,
        debounce_delay: float = 0.2,
        flush_callback: Optional[Callable[[list[tuple[FileEvent, Path]]], None]] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """
        Initialize debounce queue.

        Args:
        -----
        debounce_delay: Seconds to wait before flushing (default: 0.2)
        flush_callback: Callback to call when flushing events
        loop: Event loop for async operations

        Raises:
        -------
        ValueError: If debounce_delay invalid
        """
        if debounce_delay <= 0 or debounce_delay > 10:
            raise ValueError("debounce_delay must be between 0 and 10 seconds")

        self._debounce_delay = debounce_delay
        self._flush_callback = flush_callback

        # Get event loop, creating one if needed
        if loop:
            self._loop = loop
        else:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                # No running loop, create a new one
                self._loop = asyncio.new_event_loop()

        # Queue: maps file_path -> (event_type, file_path)
        # This allows deduplication by file path
        self._queue: dict[Path, tuple[FileEvent, Path]] = {}

        # Timer handle for debouncing
        self._timer_handle: Optional[asyncio.TimerHandle] = None

    def add(self, event_type: FileEvent, file_path: Path) -> None:
        """
        Add event to queue and reset debounce timer.

        Args:
        -----
        event_type: Type of file event
        file_path: Path to changed file

        Deduplication Rules:
        --------------------
        - Same file, multiple MODIFIED → one MODIFIED
        - Same file, CREATED then MODIFIED → one CREATED
        - Same file, MODIFIED then DELETED → one DELETED
        - Same file, CREATED then DELETED → remove entirely (no-op)
        """
        # Apply deduplication rules
        if file_path in self._queue:
            existing_event, _ = self._queue[file_path]

            # CREATED + MODIFIED → CREATED
            if existing_event == FileEvent.CREATED and event_type == FileEvent.MODIFIED:
                # Keep existing CREATED
                pass

            # CREATED + DELETED → remove (no-op)
            elif existing_event == FileEvent.CREATED and event_type == FileEvent.DELETED:
                del self._queue[file_path]

            # MODIFIED + DELETED → DELETED
            elif existing_event == FileEvent.MODIFIED and event_type == FileEvent.DELETED:
                self._queue[file_path] = (FileEvent.DELETED, file_path)

            # MODIFIED + MODIFIED → MODIFIED (last one wins)
            elif existing_event == FileEvent.MODIFIED and event_type == FileEvent.MODIFIED:
                self._queue[file_path] = (event_type, file_path)

            # Any other combination, use latest
            else:
                self._queue[file_path] = (event_type, file_path)
        else:
            # New file, add to queue
            self._queue[file_path] = (event_type, file_path)

        # Cancel existing timer and start new one
        if self._timer_handle:
            self._timer_handle.cancel()

        self._timer_handle = self._loop.call_later(
            self._debounce_delay, lambda: asyncio.create_task(self.flush())
        )

    async def flush(self) -> None:
        """
        Flush all pending events to indexing callback.

        Behavior:
        ---------
        1. Cancel debounce timer
        2. Get all unique events from queue
        3. Clear queue
        4. Call indexing callback with batch

        Exceptions from callback are caught and logged.
        """
        # Cancel timer if running
        if self._timer_handle:
            self._timer_handle.cancel()
            self._timer_handle = None

        # Get events and clear queue
        events = list(self._queue.values())
        self._queue.clear()

        # Call callback if provided (even with empty list)
        if self._flush_callback:
            try:
                # Call callback (may be async or sync)
                result = self._flush_callback(events)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                # Log error but don't raise (keep watching)
                import logging

                logger = logging.getLogger(__name__)
                logger.error(f"Error in flush callback: {e}", exc_info=True)


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
        from watchdog.observers import Observer

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
        self._observer: Optional[Observer] = None
        self._running = False

        # Initialize debounce queue
        self._debounce_queue: Optional[DebounceQueue] = None

        # Event loop for async callbacks
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self) -> None:
        """
        Start watching workspace.

        Raises:
        -------
        RuntimeError: If already running
        """
        import threading

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
        handler = _FileWatcherEventHandler(self)

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
        import time

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


class _FileWatcherEventHandler:
    """Internal event handler for watchdog."""

    def __init__(self, watcher: FileWatcher) -> None:
        self.watcher = watcher
        # Track files we've seen to normalize CREATED vs MODIFIED
        self._seen_files: set[Path] = set()

    def dispatch(self, event) -> None:
        """Dispatch file system events to watcher."""
        from watchdog.events import (
            DirCreatedEvent,
            DirDeletedEvent,
            DirModifiedEvent,
            DirMovedEvent,
            FileCreatedEvent,
            FileDeletedEvent,
            FileModifiedEvent,
            FileMovedEvent,
        )

        # Ignore directory events
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent, DirDeletedEvent, DirMovedEvent)):
            return

        file_path = Path(event.src_path)

        # Determine event type with normalization
        if isinstance(event, FileCreatedEvent):
            # macOS FSEvents quirk: sometimes reports modifications as creations
            # If file was already seen (existed when watcher started), treat as MODIFIED
            if file_path in self._seen_files:
                # File was already tracked - CREATED event is actually MODIFIED
                event_type = FileEvent.MODIFIED
            else:
                # Truly new file
                event_type = FileEvent.CREATED
                self._seen_files.add(file_path)
        elif isinstance(event, FileModifiedEvent):
            event_type = FileEvent.MODIFIED
            self._seen_files.add(file_path)
        elif isinstance(event, FileDeletedEvent):
            event_type = FileEvent.DELETED
            self._seen_files.discard(file_path)  # Remove from tracking
        elif isinstance(event, FileMovedEvent):
            # Handle moves as delete + create
            self._seen_files.discard(Path(event.src_path))
            asyncio.run_coroutine_threadsafe(
                self.watcher.handle_event(FileEvent.DELETED, Path(event.src_path)),
                self.watcher._loop,
            )
            event_type = FileEvent.CREATED
            file_path = Path(event.dest_path)
            self._seen_files.add(file_path)
        else:
            return

        # Schedule async event handling
        asyncio.run_coroutine_threadsafe(
            self.watcher.handle_event(event_type, file_path), self.watcher._loop
        )


# ============================================================================
# ERROR CONDITIONS SUMMARY
# ============================================================================

"""
Comprehensive list of error conditions the watcher must handle:

1. WORKSPACE ERRORS:
   - Workspace path doesn't exist → FileNotFoundError on __init__
   - Workspace path is file, not directory → ValueError on __init__
   - No read permission on workspace → PermissionError on start()
   - Workspace deleted while watching → Log error, stop gracefully

2. FILE ERRORS:
   - File deleted between event and indexing → Log warning, skip
   - File permissions changed (no read) → Log warning, skip
   - File too large (>10MB) → Log warning, skip
   - Binary file detected → Skip silently (not source code)

3. CALLBACK ERRORS:
   - Indexing callback raises exception → Log error, continue watching
   - Callback hangs/timeout → Log error after 30s, cancel
   - Callback returns non-None → Log warning (should be None)

4. SYSTEM ERRORS:
   - OS file watcher limit reached → Raise RuntimeError on start()
   - Out of memory → Let Python raise MemoryError
   - Disk I/O errors → Log error, retry event up to 3 times

5. LIFECYCLE ERRORS:
   - start() called twice → Raise RuntimeError
   - stop() called before start() → No-op (safe)
   - stop() timeout (callbacks won't complete) → Force stop after 5s

6. EDGE CASES:
   - Empty workspace (no files) → Watch successfully, no events
   - Workspace with 100k+ files → Watch successfully (OS permitting)
   - Rapid file changes (1000/sec) → Debounce to manageable batch
   - Symlinks outside workspace → Ignore (don't follow)
   - Symlink loops → Detect and skip (don't infinite loop)
"""

# ============================================================================
# BOUNDARY CONDITIONS SUMMARY
# ============================================================================

"""
Boundary conditions the tests must cover:

1. FILE SIZES:
   - 0 bytes → Index successfully
   - 1 byte → Index successfully
   - 1MB → Index successfully
   - 10MB → Index successfully (performance warning)
   - 11MB → Skip with warning (too large)

2. FILE NAMES:
   - ASCII only → Handle correctly
   - Unicode (café.py) → Handle correctly
   - Spaces (my file.py) → Handle correctly
   - Special chars (!@#$.py) → Handle correctly
   - Very long (250+ chars) → Handle if OS allows

3. EVENT RATES:
   - 1 event/hour → Process immediately (no debounce needed)
   - 1 event/second → Debounce to single event per file
   - 100 events/second → Debounce to batch, process efficiently
   - 1000 events/second → Debounce, batch, warn if queue grows

4. WORKSPACE SIZES:
   - 0 files → Watch successfully
   - 1 file → Watch successfully
   - 100 files → Watch successfully
   - 10,000 files → Watch successfully
   - 100,000 files → Watch if OS allows, warn about performance

5. TIMING:
   - File changed, immediately deleted → Skip (no-op)
   - File created, immediately modified → Single CREATED event
   - File modified rapidly (10x in 100ms) → Single MODIFIED event
   - Watcher stopped mid-debounce → Flush pending events on stop()

6. PATTERNS:
   - No ignore patterns → Watch all files
   - Ignore *.pyc → Skip .pyc files
   - Ignore .git/** → Skip entire .git directory
   - Ignore everything (*) → Watch nothing (weird but valid)

7. PLATFORMS:
   - Linux → Use inotify (kernel support)
   - macOS → Use FSEvents (OS support)
   - Windows → Use ReadDirectoryChangesW (OS support)
   - Paths use forward slashes internally (Unix style)
   - Convert Windows backslashes to forward slashes
"""
