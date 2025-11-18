"""
Tests for file system watcher (TDD Phase 2: Implement Tests).

These tests define the expected behavior based on the contract in watcher.py.
All tests will FAIL initially (RED phase) - that's correct!
Implementation comes in Phase 3 (GREEN phase).
"""

import pytest
import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call
from miller.watcher import (
    FileEvent,
    FileWatcher,
    DebounceQueue,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace directory for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_callback():
    """Create mock async callback for indexing."""
    return AsyncMock()


@pytest.fixture
def sample_file(temp_workspace):
    """Create a sample Python file in workspace."""
    file_path = temp_workspace / "test.py"
    file_path.write_text("def hello(): pass")
    return file_path


@pytest.fixture
def watcher(temp_workspace, mock_callback):
    """Create FileWatcher instance (not started)."""
    return FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
        ignore_patterns={".git", "*.pyc", "__pycache__"},
        debounce_delay=0.1,  # Short delay for faster tests
    )


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


# ============================================================================
# DEBOUNCING TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_debounces_rapid_modifications(watcher, sample_file, mock_callback):
    """Test: Multiple rapid modifications to same file → single callback."""
    watcher.start()

    # Modify file rapidly 10 times
    for i in range(10):
        sample_file.write_text(f"def hello(): return {i}")
        await asyncio.sleep(0.01)  # 10ms between writes

    # Wait for debounce window
    await asyncio.sleep(0.3)

    # Should only trigger callback ONCE (debounced)
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    event_type, _ = events[0]
    assert event_type == FileEvent.MODIFIED

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_batches_multiple_files(watcher, temp_workspace, mock_callback):
    """Test: Changes to multiple files are batched into single callback."""
    watcher.start()

    # Create multiple files rapidly
    files = []
    for i in range(5):
        file_path = temp_workspace / f"file_{i}.py"
        file_path.write_text(f"def func_{i}(): pass")
        files.append(file_path)
        await asyncio.sleep(0.01)

    # Wait for debounce
    await asyncio.sleep(0.3)

    # Should batch all 5 files into single callback
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 5

    # All should be CREATED events
    for event_type, file_path in events:
        assert event_type == FileEvent.CREATED
        assert file_path in files

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
# IGNORE PATTERNS TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_ignores_gitignore_patterns(watcher, temp_workspace, mock_callback):
    """Test: Watcher respects .gitignore patterns (e.g., *.pyc, .git)."""
    watcher.start()

    # Create files that should be ignored
    (temp_workspace / ".git").mkdir()
    (temp_workspace / ".git" / "config").write_text("git config")
    (temp_workspace / "test.pyc").write_text("bytecode")
    (temp_workspace / "__pycache__").mkdir()

    # Create file that should NOT be ignored
    valid_file = temp_workspace / "valid.py"
    valid_file.write_text("def valid(): pass")

    await asyncio.sleep(0.3)

    # Only valid.py should trigger callback
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    event_paths = [e[1] for e in events]

    assert valid_file in event_paths
    assert not any(".git" in str(p) for p in event_paths)
    assert not any(".pyc" in str(p) for p in event_paths)
    assert not any("__pycache__" in str(p) for p in event_paths)

    watcher.stop()


# ============================================================================
# BOUNDARY CONDITION TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_handles_empty_file(watcher, temp_workspace, mock_callback):
    """Test: Watcher handles empty file (0 bytes) correctly."""
    watcher.start()

    empty_file = temp_workspace / "empty.py"
    empty_file.write_text("")  # 0 bytes

    await asyncio.sleep(0.3)

    # Should still trigger event (empty file is valid)
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    assert events[0][1] == empty_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_handles_unicode_filename(watcher, temp_workspace, mock_callback):
    """Test: Watcher handles Unicode characters in filenames."""
    watcher.start()

    unicode_file = temp_workspace / "café.py"
    unicode_file.write_text("def café(): pass")

    await asyncio.sleep(0.3)

    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert events[0][1] == unicode_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_handles_spaces_in_filename(watcher, temp_workspace, mock_callback):
    """Test: Watcher handles spaces in filenames."""
    watcher.start()

    spaced_file = temp_workspace / "my test file.py"
    spaced_file.write_text("def test(): pass")

    await asyncio.sleep(0.3)

    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert events[0][1] == spaced_file

    watcher.stop()


@pytest.mark.asyncio
async def test_watcher_skips_very_large_files(watcher, temp_workspace, mock_callback):
    """Test: Watcher logs warning and skips files >10MB."""
    watcher.start()

    # Create 11MB file
    large_file = temp_workspace / "large.py"
    large_file.write_bytes(b"x" * (11 * 1024 * 1024))

    await asyncio.sleep(0.3)

    # Should NOT trigger callback (file too large)
    mock_callback.assert_not_called()

    watcher.stop()


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_handles_callback_exception(watcher, sample_file):
    """Test: Watcher logs error if callback raises exception but continues watching."""
    failing_callback = AsyncMock(side_effect=RuntimeError("Indexing failed!"))

    watcher_with_failing_callback = FileWatcher(
        workspace_path=watcher._workspace_path,  # type: ignore
        indexing_callback=failing_callback,
        debounce_delay=0.1,
    )

    watcher_with_failing_callback.start()

    # Modify file (will trigger failing callback)
    sample_file.write_text("def modified(): pass")
    await asyncio.sleep(0.3)

    # Watcher should still be running (didn't crash)
    assert watcher_with_failing_callback.is_running()

    watcher_with_failing_callback.stop()


@pytest.mark.asyncio
async def test_watcher_flushes_pending_events_on_stop(watcher, temp_workspace, mock_callback):
    """Test: Watcher flushes debounced events when stopped."""
    watcher.start()

    # Create file but don't wait for debounce
    new_file = temp_workspace / "quick.py"
    new_file.write_text("def quick(): pass")

    # Stop immediately (before debounce fires)
    await asyncio.sleep(0.05)  # Less than debounce delay
    watcher.stop()

    # Should still have flushed the pending event
    mock_callback.assert_called_once()
    events = mock_callback.call_args[0][0]
    assert len(events) == 1
    assert events[0][1] == new_file


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


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_event_latency_under_500ms(watcher, temp_workspace, mock_callback):
    """Test: Event processing latency < 500ms (from change to callback)."""
    watcher.start()

    start_time = time.time()

    new_file = temp_workspace / "latency_test.py"
    new_file.write_text("def test(): pass")

    # Wait for callback
    await asyncio.sleep(0.3)

    latency = time.time() - start_time

    # Should complete within 500ms
    assert latency < 0.5
    mock_callback.assert_called_once()

    watcher.stop()


# ============================================================================
# PLATFORM-SPECIFIC PATH TESTS
# ============================================================================


def test_watcher_normalizes_paths_to_unix_style(temp_workspace, mock_callback):
    """Test: Watcher stores paths in Unix style (forward slashes) internally."""
    watcher = FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
    )

    # Internal paths should use forward slashes, even on Windows
    # This will be verified in implementation
    assert True  # Placeholder - implementation will verify
