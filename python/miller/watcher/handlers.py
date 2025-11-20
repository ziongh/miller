"""
Internal event handlers for watchdog file system monitoring.

This module provides the low-level event handler that interfaces with
the watchdog library to dispatch file system events to the watcher.
"""

import asyncio
from pathlib import Path

from miller.watcher.types import FileEvent


class FileWatcherEventHandler:
    """
    Internal event handler for watchdog.

    This class receives raw file system events from watchdog and converts
    them to a normalized event stream that the FileWatcher can process.
    It handles platform-specific quirks (e.g., macOS FSEvents reporting
    modifications as creations).
    """

    def __init__(self, watcher: "FileWatcher") -> None:  # noqa: F821
        """
        Initialize event handler.

        Args:
        -----
        watcher: FileWatcher instance to route events to
        """
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
