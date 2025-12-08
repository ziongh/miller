"""
FileWatcher fixtures for test_watcher_*.py tests.
"""
import pytest
from pathlib import Path


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace directory for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_callback():
    """Create mock async callback for indexing."""
    from unittest.mock import AsyncMock
    return AsyncMock()


@pytest.fixture
def sample_file(temp_workspace):
    """Create a sample Python file in workspace."""
    file_path = temp_workspace / "test.py"
    file_path.write_text("def hello(): pass")
    return file_path


class WatcherWrapper:
    """Wrapper that adds a small delay after start() for inotify initialization."""

    def __init__(self, watcher):
        self._watcher = watcher

    def start(self):
        import time
        self._watcher.start()
        # Give inotify time to fully initialize watches
        time.sleep(0.2)

    def __getattr__(self, name):
        return getattr(self._watcher, name)


@pytest.fixture
def watcher(temp_workspace, mock_callback):
    """Create FileWatcher instance (not started).

    Note: debounce_delay is no longer configurable - the Rust watcher
    handles debouncing internally with a 200ms window.

    The wrapper adds a small delay after start() to allow inotify to
    fully initialize before file operations begin.
    """
    from miller.watcher import FileWatcher
    fw = FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
        ignore_patterns={".git", "*.pyc", "__pycache__"},
    )
    return WatcherWrapper(fw)
