"""
File system watcher for real-time workspace indexing.

This module provides a file watcher that monitors the workspace for changes
and automatically re-indexes modified files. It follows the pattern established
by Julie's watcher implementation but uses Python's watchdog library.

CONTRACT DEFINITION (Test-First TDD - Phase 1: Define Contract)
===============================================================

This module defines the interface and expected behavior BEFORE implementation.
Tests will be written against this contract, then implementation follows.

Typical usage:
--------------
    from miller.watcher import FileWatcher, FileEvent
    from pathlib import Path

    async def on_files_changed(events):
        for event_type, file_path in events:
            if event_type == FileEvent.DELETED:
                await storage.delete_file(file_path)
            else:
                await scanner.index_file(file_path)

    watcher = FileWatcher(
        workspace_path=Path("/workspace"),
        indexing_callback=on_files_changed,
        ignore_patterns={".git", "node_modules", "*.pyc"}
    )
    watcher.start()
    # ... watcher runs in background ...
    watcher.stop()

ERROR CONDITIONS SUMMARY
========================

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

BOUNDARY CONDITIONS SUMMARY
============================

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

from miller.watcher.core import FileWatcher
from miller.watcher.debouncer import DebounceQueue
from miller.watcher.handlers import FileWatcherEventHandler
from miller.watcher.types import FileEvent, FileWatcherProtocol

__all__ = [
    "FileEvent",
    "FileWatcher",
    "FileWatcherProtocol",
    "DebounceQueue",
    "FileWatcherEventHandler",
]
