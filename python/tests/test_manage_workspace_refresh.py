"""
Tests for manage_workspace refresh operation (Phase 3.1).

Following TDD: These tests are written FIRST, before implementation.

Refresh operation should:
- Re-index a workspace to detect new/changed files
- Update workspace metadata (file count, symbol count)
- Return statistics about what was updated
"""

import tempfile
from pathlib import Path
import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry


class TestManageWorkspaceRefresh:
    """Test manage_workspace refresh operation."""

    @pytest.mark.asyncio
    async def test_refresh_requires_workspace_id(self):
        """Refresh operation requires workspace_id parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="refresh")

                # Should return error message
                assert "error" in result.lower() or "required" in result.lower()
                assert "workspace_id" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_refresh_validates_workspace_exists(self):
        """Refresh operation validates workspace_id exists in registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(
                    operation="refresh", workspace="nonexistent_workspace_123"
                )

                # Should return error for non-existent workspace
                assert "error" in result.lower() or "not found" in result.lower()
                assert "nonexistent_workspace_123" in result

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_refresh_reindexes_workspace(self):
        """Refresh re-indexes workspace and detects new files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create a test workspace directory
                workspace_dir = Path(tmpdir) / "test_project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                # Add workspace to registry (which triggers initial indexing via add operation)
                # For this test, we'll simulate that the workspace was already indexed
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Do initial refresh to index the workspace
                await manage_workspace(operation="refresh", workspace=workspace_id)

                # Add a new file after initial indexing
                (workspace_dir / "new.py").write_text("def new_func(): pass")

                # Refresh the workspace again
                result = await manage_workspace(operation="refresh", workspace=workspace_id)

                # Should indicate successful refresh
                assert "refresh" in result.lower()
                assert "Test Project" in result or workspace_id in result

                # Should mention new files detected
                assert "indexed 1 new file" in result.lower() or "1 new file" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_refresh_updates_registry_metadata(self):
        """Refresh updates workspace metadata in registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create a test workspace
                workspace_dir = Path(tmpdir) / "test_project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                # Add workspace to registry
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Do initial refresh
                await manage_workspace(operation="refresh", workspace=workspace_id)

                # Get initial metadata
                workspace_before = registry.get_workspace(workspace_id)
                initial_file_count = workspace_before.file_count if workspace_before else 0

                # Add new files
                (workspace_dir / "new1.py").write_text("def new1(): pass")
                (workspace_dir / "new2.py").write_text("def new2(): pass")

                # Refresh again
                await manage_workspace(operation="refresh", workspace=workspace_id)

                # Check updated metadata (create fresh registry to reload from disk)
                fresh_registry = WorkspaceRegistry()
                workspace_after = fresh_registry.get_workspace(workspace_id)
                assert workspace_after.file_count > initial_file_count
                assert workspace_after.symbol_count > 0

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_refresh_handles_deleted_files(self):
        """Refresh detects and removes deleted files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace with files
                workspace_dir = Path(tmpdir) / "test_project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")
                (workspace_dir / "utils.py").write_text("def util(): pass")

                # Add and index workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Do initial refresh
                await manage_workspace(operation="refresh", workspace=workspace_id)

                # Delete a file
                (workspace_dir / "utils.py").unlink()

                # Refresh again
                result = await manage_workspace(operation="refresh", workspace=workspace_id)

                # Should report deleted files
                assert "deleted" in result.lower() or "removed" in result.lower()
                assert "1" in result  # 1 deleted file

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_refresh_skips_unchanged_files(self):
        """Refresh skips files that haven't changed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace
                workspace_dir = Path(tmpdir) / "test_project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                # Add and index
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Do initial refresh
                await manage_workspace(operation="refresh", workspace=workspace_id)

                # Refresh without changes
                result = await manage_workspace(operation="refresh", workspace=workspace_id)

                # Should report no changes or up to date
                assert "skipped" in result.lower() or "unchanged" in result.lower() or "up to date" in result.lower()

            finally:
                os.chdir(original_dir)
