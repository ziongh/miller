"""
Tests for workspace path utilities.

Following TDD: These tests are written FIRST, before implementation.
"""

import tempfile
from pathlib import Path

import pytest

from miller.workspace_paths import (
    ensure_workspace_directories,
    get_workspace_db_path,
    get_workspace_vector_path,
)


class TestWorkspacePaths:
    """Test workspace path utility functions."""

    def test_get_workspace_db_path(self):
        """Returns correct SQLite path for workspace."""
        path = get_workspace_db_path("my-project_abc123")
        assert path == Path(".miller/indexes/my-project_abc123/symbols.db")

    def test_get_workspace_vector_path(self):
        """Returns correct LanceDB path for workspace."""
        path = get_workspace_vector_path("my-project_abc123")
        assert path == Path(".miller/indexes/my-project_abc123/vectors.lance")

    def test_ensure_workspace_directories_creates_dirs(self):
        """Creates workspace directories if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to temp directory for test
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                workspace_id = "test_abc123"
                ensure_workspace_directories(workspace_id)

                db_path = get_workspace_db_path(workspace_id)
                vector_path = get_workspace_vector_path(workspace_id)

                # Parent directories should exist
                assert db_path.parent.exists()
                assert vector_path.parent.exists()

                # Verify structure
                assert db_path.parent == Path(".miller/indexes/test_abc123")
                assert vector_path.parent == Path(".miller/indexes/test_abc123")

            finally:
                os.chdir(original_dir)

    def test_ensure_workspace_directories_idempotent(self):
        """Calling ensure_workspace_directories multiple times is safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                workspace_id = "test_abc123"

                # Call twice
                ensure_workspace_directories(workspace_id)
                ensure_workspace_directories(workspace_id)

                # Should still work
                db_path = get_workspace_db_path(workspace_id)
                assert db_path.parent.exists()

            finally:
                os.chdir(original_dir)

    def test_workspace_paths_use_consistent_structure(self):
        """DB and vector paths use same parent directory."""
        workspace_id = "my-workspace_xyz789"

        db_path = get_workspace_db_path(workspace_id)
        vector_path = get_workspace_vector_path(workspace_id)

        # Should share same parent directory
        assert db_path.parent == vector_path.parent
        assert db_path.parent == Path(f".miller/indexes/{workspace_id}")
