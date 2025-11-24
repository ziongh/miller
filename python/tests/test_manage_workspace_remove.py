"""
Tests for manage_workspace remove operation (Phase 2.2).

Following TDD: These tests are written FIRST, before implementation.
"""

import tempfile
from pathlib import Path

import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path
from miller.workspace_registry import WorkspaceRegistry


class TestManageWorkspaceRemove:
    """Test manage_workspace remove operation."""

    @pytest.mark.asyncio
    async def test_remove_requires_workspace_id(self):
        """Remove operation requires workspace_id parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="remove")

                # Should return error
                assert "error" in result.lower() or "required" in result.lower()
                assert "workspace_id" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_nonexistent_workspace(self):
        """Removing non-existent workspace returns error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(
                    operation="remove", workspace="nonexistent_abc123"
                )

                # Should return error
                assert "error" in result.lower() or "not found" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_workspace_from_registry(self):
        """Remove operation removes workspace from registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Add workspace to registry
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path="/test/path", name="Test Workspace", workspace_type="reference"
                )

                # Verify it's there
                assert len(registry.list_workspaces()) == 1

                # Remove it
                result = await manage_workspace(
                    operation="remove", workspace=workspace_id
                )

                # Should report success
                assert "success" in result.lower() or "removed" in result.lower()

                # Verify it's gone from registry
                registry = WorkspaceRegistry()
                assert len(registry.list_workspaces()) == 0

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_deletes_workspace_directories(self):
        """Remove operation deletes workspace DB and vector directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path="/test/path", name="Test", workspace_type="reference"
                )

                # Create workspace directories with some files
                from miller.workspace_paths import ensure_workspace_directories

                ensure_workspace_directories(workspace_id)

                db_path = get_workspace_db_path(workspace_id)
                vector_path = get_workspace_vector_path(workspace_id)

                # Create dummy files
                db_path.write_text("dummy db")
                vector_path.parent.mkdir(parents=True, exist_ok=True)
                (vector_path.parent / "test.dat").write_text("dummy data")

                # Verify files exist
                assert db_path.exists()
                assert (vector_path.parent / "test.dat").exists()

                # Remove workspace
                result = await manage_workspace(
                    operation="remove", workspace=workspace_id
                )

                # Verify directories are deleted
                assert not db_path.exists()
                assert not db_path.parent.exists()
                assert not vector_path.parent.exists()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_shows_what_was_removed(self):
        """Remove operation shows workspace name and stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path="/test/path", name="My Reference Workspace", workspace_type="reference"
                )

                result = await manage_workspace(
                    operation="remove", workspace=workspace_id
                )

                # Should include workspace name
                assert "My Reference Workspace" in result
                assert "success" in result.lower() or "removed" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_handles_missing_directories_gracefully(self):
        """Remove still works if directories were already deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Add workspace to registry (but don't create directories)
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path="/test/path", name="Test", workspace_type="reference"
                )

                # Remove without creating directories first
                result = await manage_workspace(
                    operation="remove", workspace=workspace_id
                )

                # Should still succeed (no error about missing dirs)
                assert "success" in result.lower() or "removed" in result.lower()
                assert "error" not in result.lower()

                # Verify registry cleaned up
                registry = WorkspaceRegistry()
                assert len(registry.list_workspaces()) == 0

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_remove_cleans_up_completely(self):
        """Remove operation leaves no trace of workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(path="/test", name="Test")

                from miller.workspace_paths import ensure_workspace_directories

                ensure_workspace_directories(workspace_id)

                # Create files
                db_path = get_workspace_db_path(workspace_id)
                db_path.write_text("data")

                # Remove
                await manage_workspace(operation="remove", workspace=workspace_id)

                # Verify complete cleanup
                registry = WorkspaceRegistry()
                assert len(registry.list_workspaces()) == 0
                assert not db_path.parent.exists()

            finally:
                os.chdir(original_dir)
