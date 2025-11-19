"""
Tests for manage_workspace MCP tool.

Following TDD: These tests are written FIRST, before implementation.
"""

import tempfile
from pathlib import Path

import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry


class TestManageWorkspaceList:
    """Test manage_workspace list operation."""

    @pytest.mark.asyncio
    async def test_list_empty_registry(self):
        """List returns empty message when no workspaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="list")
                assert "No workspaces registered" in result
                assert "index" in result.lower()  # Suggests using index command

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_list_shows_workspaces(self):
        """List shows registered workspaces with metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Setup: Add workspaces to registry
                registry = WorkspaceRegistry()
                registry.add_workspace(
                    path="/test/project", name="Test Project", workspace_type="primary"
                )
                registry.add_workspace(
                    path="/reference/lib", name="My Library", workspace_type="reference"
                )

                result = await manage_workspace(operation="list")

                # Should show both workspaces
                assert "Test Project" in result
                assert "My Library" in result

                # Should show workspace types
                assert "PRIMARY" in result
                assert "REFERENCE" in result

                # Should show paths
                assert "/test/project" in result
                assert "/reference/lib" in result

                # Should show stats (even if zero)
                assert "Symbols:" in result or "symbols" in result.lower()
                assert "Files:" in result or "files" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_list_shows_workspace_ids(self):
        """List includes workspace IDs for reference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Setup: Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(path="/test", name="Test")

                result = await manage_workspace(operation="list")

                # Should include workspace ID
                assert workspace_id in result
                assert "ID:" in result or "id:" in result.lower()

            finally:
                os.chdir(original_dir)


class TestManageWorkspaceStats:
    """Test manage_workspace stats operation."""

    @pytest.mark.asyncio
    async def test_stats_requires_workspace_id(self):
        """Stats operation requires workspace_id parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="stats")

                # Should return error
                assert "error" in result.lower() or "required" in result.lower()
                assert "workspace_id" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_stats_nonexistent_workspace(self):
        """Stats returns error for non-existent workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(
                    operation="stats", workspace_id="nonexistent_abc123"
                )

                # Should return error
                assert "error" in result.lower() or "not found" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_stats_shows_workspace_info(self):
        """Stats operation shows detailed workspace information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Setup: Create workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path="/test/project", name="Test Project", workspace_type="primary"
                )

                # Create workspace directories so stats can read them
                from miller.workspace_paths import ensure_workspace_directories

                ensure_workspace_directories(workspace_id)

                result = await manage_workspace(
                    operation="stats", workspace_id=workspace_id
                )

                # Should show workspace details
                assert "Test Project" in result
                assert "primary" in result.lower()
                assert "/test/project" in result

                # Should show statistics
                assert "Symbol" in result or "symbol" in result.lower()
                assert "File" in result or "file" in result.lower()

                # Should show sizes
                assert "MB" in result or "size" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_stats_shows_database_sizes(self):
        """Stats includes database and vector index sizes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Setup: Create workspace with actual files
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(path="/test", name="Test")

                from miller.workspace_paths import (
                    ensure_workspace_directories,
                    get_workspace_db_path,
                )

                ensure_workspace_directories(workspace_id)

                # Create a dummy database file
                db_path = get_workspace_db_path(workspace_id)
                db_path.write_text("dummy data")

                result = await manage_workspace(
                    operation="stats", workspace_id=workspace_id
                )

                # Should show size information
                assert "Database size:" in result or "database" in result.lower()
                assert "Vector" in result or "vector" in result.lower()
                assert "MB" in result

            finally:
                os.chdir(original_dir)


class TestManageWorkspaceUnknownOperation:
    """Test manage_workspace error handling."""

    @pytest.mark.asyncio
    async def test_unknown_operation_returns_error(self):
        """Unknown operation returns helpful error message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="invalid_operation")

                # Should return error
                assert "error" in result.lower() or "not implemented" in result.lower()

            finally:
                os.chdir(original_dir)
