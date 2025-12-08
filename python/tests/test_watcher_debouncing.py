"""
Tests for FileWatcher debouncing, batching, and event deduplication.

These tests focus on:
1. Debouncing rapid file modifications into single callbacks
2. Batching changes to multiple files
3. Deduplicating conflicting events (CREATED + DELETED, etc.)
4. DebounceQueue unit tests
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from miller.watcher import FileEvent, FileWatcher, DebounceQueue


# ============================================================================
# DEBOUNCING TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_debounces_rapid_modifications(watcher, sample_file, mock_callback):
    """Test: Multiple rapid modifications to same file → batched callback.

    NOTE: Rust watcher has 200ms debounce window. inotify may send multiple
    events for rapid writes. The key test is that the callback contains events
    for our file with a valid hash (showing content was captured).
    """
    watcher.start()

    # Modify file rapidly 10 times
    for i in range(10):
        sample_file.write_text(f"def hello(): return {i}")
        await asyncio.sleep(0.01)  # 10ms between writes

    # Wait for Rust debounce window (200ms) + processing time
    await asyncio.sleep(0.5)

    # Callback should be called with events for our file
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]
    assert len(events) >= 1

    # Find events for our file
    file_events = [e for e in events if e[1] == sample_file]
    assert len(file_events) >= 1, f"Expected events for {sample_file}, got {events}"

    # At least one should be MODIFIED with a hash
    modified_events = [e for e in file_events if e[0] == FileEvent.MODIFIED]
    assert len(modified_events) >= 1, f"Expected MODIFIED events, got {file_events}"
    assert modified_events[0][2] is not None  # Hash should be present

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_batches_multiple_files(watcher, temp_workspace, mock_callback):
    """Test: Changes to multiple files are batched into callback(s).

    NOTE: Events are now 3-tuples: (FileEvent, Path, Optional[str])
    NOTE: inotify may send multiple events per file (CREATED + MODIFIED),
    so the total event count may exceed the number of files created.
    """
    watcher.start()

    # Create multiple files rapidly
    files = []
    for i in range(5):
        file_path = temp_workspace / f"file_{i}.py"
        file_path.write_text(f"def func_{i}(): pass")
        files.append(file_path)
        await asyncio.sleep(0.01)

    # Wait for Rust debounce window (200ms) + processing time
    await asyncio.sleep(0.5)

    # Callback should be called with events
    mock_callback.assert_called()
    events = mock_callback.call_args[0][0]

    # Should have at least one event per file created
    assert len(events) >= 5, f"Expected at least 5 events, got {len(events)}"

    # Check that all created files have CREATED events
    created_paths = {e[1] for e in events if e[0] == FileEvent.CREATED}
    for f in files:
        assert f in created_paths, f"Missing CREATED event for {f}"

    # All CREATED events should have hashes
    for event_type, file_path, new_hash in events:
        if event_type == FileEvent.CREATED:
            assert new_hash is not None, f"Missing hash for CREATED event on {file_path}"

    watcher.stop()


# ============================================================================
# DEDUPLICATION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_debounce_queue_deduplicates_created_modified():
    """Test: CREATED + MODIFIED for same file → single CREATED event."""
    callback = AsyncMock()
    queue = DebounceQueue(debounce_delay=0.1)
    queue._flush_callback = callback  # type: ignore

    file_path = Path("/test/file.py")

    queue.add(FileEvent.CREATED, file_path)
    queue.add(FileEvent.MODIFIED, file_path)

    await asyncio.sleep(0.2)  # Wait for flush

    callback.assert_called_once()
    events = callback.call_args[0][0]
    assert len(events) == 1
    assert events[0] == (FileEvent.CREATED, file_path)


@pytest.mark.asyncio
async def test_debounce_queue_deduplicates_created_deleted():
    """Test: CREATED + DELETED for same file → no event (cancel out)."""
    callback = AsyncMock()
    queue = DebounceQueue(debounce_delay=0.1)
    queue._flush_callback = callback  # type: ignore

    file_path = Path("/test/file.py")

    queue.add(FileEvent.CREATED, file_path)
    queue.add(FileEvent.DELETED, file_path)

    await asyncio.sleep(0.2)  # Wait for flush

    # No event should be fired (created then deleted = no-op)
    callback.assert_called_once()
    events = callback.call_args[0][0]
    assert len(events) == 0


@pytest.mark.asyncio
async def test_debounce_queue_deduplicates_modified_deleted():
    """Test: MODIFIED + DELETED for same file → single DELETED event."""
    callback = AsyncMock()
    queue = DebounceQueue(debounce_delay=0.1)
    queue._flush_callback = callback  # type: ignore

    file_path = Path("/test/file.py")

    queue.add(FileEvent.MODIFIED, file_path)
    queue.add(FileEvent.DELETED, file_path)

    await asyncio.sleep(0.2)  # Wait for flush

    callback.assert_called_once()
    events = callback.call_args[0][0]
    assert len(events) == 1
    assert events[0] == (FileEvent.DELETED, file_path)


# ============================================================================
# DEBOUNCE QUEUE UNIT TESTS
# ============================================================================


def test_debounce_queue_init():
    """Test: DebounceQueue initializes with valid delay."""
    queue = DebounceQueue(debounce_delay=0.5)
    assert queue is not None


def test_debounce_queue_init_invalid_delay():
    """Test: DebounceQueue raises ValueError for invalid delay."""
    with pytest.raises(ValueError):
        DebounceQueue(debounce_delay=0.0)

    with pytest.raises(ValueError):
        DebounceQueue(debounce_delay=-1.0)

    with pytest.raises(ValueError):
        DebounceQueue(debounce_delay=11.0)


@pytest.mark.asyncio
async def test_debounce_queue_flush_empty_queue():
    """Test: Flushing empty DebounceQueue is safe (no-op)."""
    callback = AsyncMock()
    queue = DebounceQueue(debounce_delay=0.1)
    queue._flush_callback = callback  # type: ignore

    await queue.flush()

    # Should not crash, callback called with empty list
    callback.assert_called_once_with([])
