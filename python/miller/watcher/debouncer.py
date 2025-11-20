"""
Event debouncing for file watcher.

This module provides the DebounceQueue class that collects rapid file changes
and batches them for efficient processing.
"""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from miller.watcher.types import FileEvent

logger = logging.getLogger(__name__)


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
                logger.error(f"Error in flush callback: {e}", exc_info=True)
