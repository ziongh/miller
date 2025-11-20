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


@pytest.fixture
def watcher(temp_workspace, mock_callback):
    """Create FileWatcher instance (not started)."""
    from miller.watcher import FileWatcher
    return FileWatcher(
        workspace_path=temp_workspace,
        indexing_callback=mock_callback,
        ignore_patterns={".git", "*.pyc", "__pycache__"},
        debounce_delay=0.1,  # Short delay for faster tests
    )
