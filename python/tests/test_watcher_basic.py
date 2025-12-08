"""
Tests for FileWatcher basic functionality: initialization, lifecycle, and event detection.

These tests focus on:
1. FileWatcher initialization with various configurations
2. Start/stop lifecycle management
3. Detection of basic file events (create, modify, delete, move)
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from miller.watcher import FileEvent, FileWatcher


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_watcher_init_with_valid_workspace(temp_workspace, mock_callback):
    """Test: FileWatcher initializes successfully with valid workspace."""
    watcher = FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
    )

    assert watcher is not None
    assert not watcher.is_running()  # Not started yet


def test_watcher_init_workspace_not_exists(mock_callback):
    """Test: FileWatcher raises FileNotFoundError if workspace doesn't exist."""
    with pytest.raises(FileNotFoundError):
        FileWatcher(
            workspace_path=Path("/nonexistent/path"),
            indexing_callback=mock_callback,
        )


def test_watcher_init_workspace_is_file(tmp_path, mock_callback):
    """Test: FileWatcher raises ValueError if workspace is a file, not directory."""
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("content")

    with pytest.raises(ValueError, match="not a directory"):
        FileWatcher(
            workspace_path=file_path,
            indexing_callback=mock_callback,
        )


def test_watcher_init_callback_not_callable(temp_workspace):
    """Test: FileWatcher raises TypeError if callback is not callable."""
    with pytest.raises(TypeError, match="callable"):
        FileWatcher(
            workspace_path=temp_workspace,
            indexing_callback="not_a_function",  # type: ignore
        )


# ============================================================================
# LIFECYCLE TESTS (start, stop, is_running)
# ============================================================================


def test_watcher_start_and_stop(watcher):
    """Test: FileWatcher can start and stop successfully."""
    assert not watcher.is_running()

    watcher.start()
    assert watcher.is_running()

    watcher.stop()
    assert not watcher.is_running()


def test_watcher_start_twice_raises_error(watcher):
    """Test: Starting watcher twice raises RuntimeError."""
    watcher.start()
    assert watcher.is_running()

    with pytest.raises(RuntimeError, match="already.*running"):
        watcher.start()

    watcher.stop()


def test_watcher_stop_before_start_is_safe(watcher):
    """Test: Stopping watcher before starting is a no-op (safe)."""
    assert not watcher.is_running()
    watcher.stop()  # Should not raise
    assert not watcher.is_running()


def test_watcher_stop_multiple_times_is_safe(watcher):
    """Test: Stopping watcher multiple times is safe."""
    watcher.start()
    watcher.stop()
    assert not watcher.is_running()

    watcher.stop()  # Second stop should be safe
    assert not watcher.is_running()


# ============================================================================
# EVENT DETECTION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_detects_file_creation(watcher, temp_workspace, mock_callback):
    """Test: Watcher detects when new file is created.

    NOTE: Events are now 3-tuples: (FileEvent, Path, Optional[str] hash)
    NOTE: inotify may send multiple events (CREATE + MODIFY) for a single file creation.
    """
    watcher.start()

    # Create new file
    new_file = temp_workspace / "new_file.py"
    new_file.write_text("def new(): pass")

    # Wait for debounce + processing
    await asyncio.sleep(0.5)  # Rust debounce is 200ms + processing time

    # Verify callback was called with events including CREATED
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]
    assert len(events) >= 1

    # Check that we got a CREATED event for the file
    created_events = [e for e in events if e[0] == FileEvent.CREATED and e[1] == new_file]
    assert len(created_events) >= 1, f"Expected CREATED event, got: {events}"
    event_type, file_path, new_hash = created_events[0]
    assert new_hash is not None  # Created files have hash

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_modification(watcher, sample_file, mock_callback):
    """Test: Watcher detects when existing file is modified.

    NOTE: Events are now 3-tuples: (FileEvent, Path, Optional[str] hash)
    NOTE: inotify may send multiple MODIFY events for a single modification.
    """
    watcher.start()

    # Modify existing file
    sample_file.write_text("def hello(): return 'world'")

    # Wait for debounce + processing
    await asyncio.sleep(0.5)  # Rust debounce is 200ms + processing time

    # Verify callback was called with MODIFIED event
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]
    assert len(events) >= 1

    # Check that we got a MODIFIED event for the file
    modified_events = [e for e in events if e[0] == FileEvent.MODIFIED and e[1] == sample_file]
    assert len(modified_events) >= 1, f"Expected MODIFIED event, got: {events}"
    event_type, file_path, new_hash = modified_events[0]
    assert new_hash is not None  # Modified files have hash

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_deletion(watcher, sample_file, mock_callback):
    """Test: Watcher detects when file is deleted.

    NOTE: Events are now 3-tuples: (FileEvent, Path, Optional[str] hash)
    For deletions, hash is None (no content to hash).
    """
    watcher.start()

    # Delete file
    sample_file.unlink()

    # Wait for debounce + processing
    await asyncio.sleep(0.5)  # Rust debounce is 200ms + processing time

    # Verify callback was called with DELETED event
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    event_type, file_path, new_hash = events[0]
    assert event_type == FileEvent.DELETED
    assert file_path == sample_file
    assert new_hash is None  # Deleted files have no hash

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_move(watcher, sample_file, temp_workspace, mock_callback):
    """Test: Watcher detects file move/rename.

    NOTE: Different platforms/backends report moves differently:
    - Some report DELETED (old) + CREATED (new)
    - Some report MOVED events
    - Some report MODIFIED events

    We just verify that SOME event was detected involving the affected paths.
    """
    watcher.start()

    # Move/rename file
    new_path = temp_workspace / "renamed.py"
    sample_file.rename(new_path)

    # Wait for debounce + processing
    await asyncio.sleep(0.5)  # Rust debounce is 200ms + processing time

    # Verify callback was called with some events
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]
    assert len(events) >= 1, "Expected at least one event for file move"

    # Should see events related to old or new path
    event_paths = [e[1] for e in events]
    paths_detected = {p for p in event_paths}

    # At least one of the paths should be detected
    assert sample_file in paths_detected or new_path in paths_detected, (
        f"Expected events for {sample_file} or {new_path}, got: {event_paths}"
    )

    watcher.stop()
