"""
Tests for manage_workspace clean operation (Phase 3.2).

Following TDD: These tests are written FIRST, before implementation.

Clean operation should:
- Remove workspaces whose paths no longer exist (orphaned)
- Delete associated database and vector files
- Return statistics about what was cleaned
- Preserve valid workspaces
"""

import tempfile
from pathlib import Path
import shutil
import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry
from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path


class TestManageWorkspaceClean:
    """Test manage_workspace clean operation."""

    @pytest.mark.asyncio
    async def test_clean_with_no_workspaces(self):
        """Clean returns appropriate message when no workspaces exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="clean")

                # Should indicate no workspaces
                assert "no workspaces" in result.lower() or "nothing to clean" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_clean_with_all_valid_workspaces(self):
        """Clean preserves all workspaces when paths are valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace with valid path
                workspace_dir = Path(tmpdir) / "valid_project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                # Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Valid Project", workspace_type="primary"
                )

                # Clean
                result = await manage_workspace(operation="clean")

                # Should report nothing removed
                assert "0" in result or "no orphaned" in result.lower() or "nothing to clean" in result.lower()

                # Verify workspace still exists
                fresh_registry = WorkspaceRegistry()
                workspace = fresh_registry.get_workspace(workspace_id)
                assert workspace is not None

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_clean_removes_orphaned_workspaces(self):
        """Clean removes workspaces whose paths no longer exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create two workspaces
                workspace1_dir = Path(tmpdir) / "project1"
                workspace1_dir.mkdir()
                (workspace1_dir / "main.py").write_text("def hello(): pass")

                workspace2_dir = Path(tmpdir) / "project2"
                workspace2_dir.mkdir()
                (workspace2_dir / "utils.py").write_text("def util(): pass")

                # Add both workspaces
                registry = WorkspaceRegistry()
                ws1_id = registry.add_workspace(
                    path=str(workspace1_dir), name="Project 1", workspace_type="primary"
                )
                ws2_id = registry.add_workspace(
                    path=str(workspace2_dir), name="Project 2", workspace_type="reference"
                )

                # Delete one workspace's directory
                shutil.rmtree(workspace2_dir)

                # Clean
                result = await manage_workspace(operation="clean")

                # Should report 1 removed
                assert "1" in result
                assert "removed" in result.lower() or "cleaned" in result.lower()
                assert "Project 2" in result or ws2_id in result

                # Verify orphaned workspace was removed from registry
                fresh_registry = WorkspaceRegistry()
                assert fresh_registry.get_workspace(ws1_id) is not None
                assert fresh_registry.get_workspace(ws2_id) is None

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_clean_deletes_orphaned_data_files(self):
        """Clean deletes database and vector files for orphaned workspaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace
                workspace_dir = Path(tmpdir) / "project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                # Add workspace and index it
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Index to create data files
                await manage_workspace(operation="refresh", workspace_id=workspace_id)

                # Verify data files exist
                db_path = get_workspace_db_path(workspace_id)
                vector_path = get_workspace_vector_path(workspace_id)
                assert db_path.exists()
                assert vector_path.parent.exists()

                # Delete workspace directory
                shutil.rmtree(workspace_dir)

                # Clean
                await manage_workspace(operation="clean")

                # Verify data files were deleted
                assert not db_path.exists()
                assert not vector_path.parent.exists()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_clean_handles_multiple_orphaned_workspaces(self):
        """Clean removes multiple orphaned workspaces in one operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create three workspaces
                ws_dirs = []
                ws_ids = []
                registry = WorkspaceRegistry()

                for i in range(3):
                    ws_dir = Path(tmpdir) / f"project{i}"
                    ws_dir.mkdir()
                    (ws_dir / "main.py").write_text(f"def func{i}(): pass")
                    ws_dirs.append(ws_dir)

                    ws_id = registry.add_workspace(
                        path=str(ws_dir), name=f"Project {i}", workspace_type="primary"
                    )
                    ws_ids.append(ws_id)

                # Delete two workspace directories
                shutil.rmtree(ws_dirs[0])
                shutil.rmtree(ws_dirs[2])

                # Clean
                result = await manage_workspace(operation="clean")

                # Should report 2 removed
                assert "2" in result
                assert "removed" in result.lower() or "cleaned" in result.lower()

                # Verify correct workspaces removed
                fresh_registry = WorkspaceRegistry()
                assert fresh_registry.get_workspace(ws_ids[0]) is None
                assert fresh_registry.get_workspace(ws_ids[1]) is not None  # Should remain
                assert fresh_registry.get_workspace(ws_ids[2]) is None

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_clean_dry_run_option(self):
        """Clean with dry_run shows what would be removed without removing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace then delete its directory
                workspace_dir = Path(tmpdir) / "project"
                workspace_dir.mkdir()
                (workspace_dir / "main.py").write_text("def hello(): pass")

                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(workspace_dir), name="Test Project", workspace_type="primary"
                )

                # Delete directory
                shutil.rmtree(workspace_dir)

                # Dry run clean (if supported)
                # Note: This test might be updated based on implementation
                result = await manage_workspace(operation="clean")

                # Should still remove it (no dry_run parameter yet)
                assert "1" in result

                # If dry_run is implemented, test would be:
                # result = await manage_workspace(operation="clean", dry_run=True)
                # assert "would remove" in result.lower()
                # fresh_registry = WorkspaceRegistry()
                # assert fresh_registry.get_workspace(workspace_id) is not None

            finally:
                os.chdir(original_dir)
