"""
Memory tool fixtures for test_checkpoint.py, test_recall.py, test_plan.py tests.
"""
import pytest
from pathlib import Path


@pytest.fixture
def temp_memories_dir(tmp_path):
    """Create a temporary .memories directory."""
    memories_dir = tmp_path / ".memories"
    memories_dir.mkdir()
    # Switch to temp directory for test
    import os
    original_dir = os.getcwd()
    os.chdir(tmp_path)
    yield memories_dir
    # Restore original directory
    os.chdir(original_dir)


@pytest.fixture
def mock_git_context():
    """Mock git context to avoid real git commands in tests."""
    return {
        "branch": "main",
        "commit": "abc1234",
        "dirty": False,
        "files_changed": []
    }


@pytest.fixture
def mock_context():
    """Mock FastMCP context for testing."""
    from unittest.mock import MagicMock
    return MagicMock()


@pytest.fixture
def sample_checkpoint():
    """Sample checkpoint data for testing."""
    return {
        "id": "checkpoint_691cb498_2fc504",
        "timestamp": 1763488920,
        "type": "checkpoint",
        "git": {
            "branch": "main",
            "commit": "cf00e54",
            "dirty": True,
            "files_changed": [".memories/plans/test.json"]
        },
        "description": "Test checkpoint",
        "tags": ["test", "example"]
    }


