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


def test_watcher_init_invalid_debounce_delay(temp_workspace, mock_callback):
    """Test: FileWatcher raises ValueError for invalid debounce delay."""
    with pytest.raises(ValueError, match="debounce_delay"):
        FileWatcher(
            workspace_path=temp_workspace,
            indexing_callback=mock_callback,
            debounce_delay=-0.1,  # Negative not allowed
        )

    with pytest.raises(ValueError, match="debounce_delay"):
        FileWatcher(
            workspace_path=temp_workspace,
            indexing_callback=mock_callback,
            debounce_delay=15.0,  # Too long (>10)
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
    """Test: Watcher detects when new file is created."""
    watcher.start()

    # Create new file
    new_file = temp_workspace / "new_file.py"
    new_file.write_text("def new(): pass")

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Verify callback was called with CREATED event
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    event_type, file_path = events[0]
    assert event_type == FileEvent.CREATED
    assert file_path == new_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_modification(watcher, sample_file, mock_callback):
    """Test: Watcher detects when existing file is modified."""
    watcher.start()

    # Modify existing file
    sample_file.write_text("def hello(): return 'world'")

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Verify callback was called with MODIFIED event
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    event_type, file_path = events[0]
    assert event_type == FileEvent.MODIFIED
    assert file_path == sample_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_deletion(watcher, sample_file, mock_callback):
    """Test: Watcher detects when file is deleted."""
    watcher.start()

    # Delete file
    sample_file.unlink()

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Verify callback was called with DELETED event
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    event_type, file_path = events[0]
    assert event_type == FileEvent.DELETED
    assert file_path == sample_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_move(watcher, sample_file, temp_workspace, mock_callback):
    """Test: Watcher detects file move/rename as DELETE + CREATE."""
    watcher.start()

    # Move/rename file
    new_path = temp_workspace / "renamed.py"
    sample_file.rename(new_path)

    # Wait for debounce + processing
    await asyncio.sleep(0.3)

    # Verify callback called with MOVED or DELETE+CREATE events
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]

    # Should see deletion of old path and creation of new path
    event_types = [e[0] for e in events]
    event_paths = [e[1] for e in events]

    assert FileEvent.DELETED in event_types or FileEvent.MOVED in event_types
    assert sample_file in event_paths or new_path in event_paths

    watcher.stop()
