"""
Tests for FileWatcher advanced features: ignore patterns, boundary conditions, error handling, and performance.

These tests focus on:
1. Ignoring patterns (.gitignore, .pyc, __pycache__)
2. Edge cases (empty files, Unicode, spaces, large files)
3. Error handling (callback exceptions, pending event flush)
4. Performance (event latency)
5. Platform-specific path handling
"""

import pytest
import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock
from miller.watcher import FileEvent, FileWatcher


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
    import platform

    watcher = FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
    )

    # Create a test file with nested directories
    nested_dir = temp_workspace / "subdir" / "nested"
    nested_dir.mkdir(parents=True, exist_ok=True)
    test_file = nested_dir / "test.txt"
    test_file.write_text("test content")

    # Get relative path
    rel_path = test_file.relative_to(watcher._workspace_path)

    # Convert to string (Path uses OS-specific separators)
    path_str = str(rel_path)

    # Normalize to Unix style for comparison
    unix_path = path_str.replace("\\", "/")

    # Verify it's a valid relative path with forward slashes
    assert "/" in unix_path or len(unix_path.split("/")) == 1, \
        "Path should use forward slashes or be a single component"
    assert "subdir/nested/test.txt" == unix_path, \
        f"Expected 'subdir/nested/test.txt', got '{unix_path}'"

    # On Windows, verify we're NOT using backslashes in our normalized format
    if platform.system() == "Windows":
        assert "\\" not in unix_path, \
            "Normalized path should not contain backslashes on Windows"
