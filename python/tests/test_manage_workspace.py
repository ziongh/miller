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

                # Lean format: shows [primary] or [ref] type indicators
                assert "[primary]" in result
                assert "[ref]" in result

                # Should show paths
                assert "/test/project" in result
                assert "/reference/lib" in result

                # Lean format uses "sym" and "files"
                assert "sym" in result.lower()
                assert "files" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_list_json_format_shows_workspace_ids(self):
        """List in JSON format includes workspace IDs for reference."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import json
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Setup: Add workspace
                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(path="/test", name="Test")

                # JSON format includes all metadata including IDs
                result = await manage_workspace(operation="list", output_format="json")
                data = json.loads(result)

                # Should have workspace with ID
                assert len(data) == 1
                assert data[0]["workspace_id"] == workspace_id
                assert data[0]["name"] == "Test"

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

                # Lean format: "Test Project [primary]\n  0 sym | 0 files | 0.00 MB"
                assert "Test Project" in result
                assert "primary" in result.lower()

                # Lean format uses "sym" and "files"
                assert "sym" in result.lower()
                assert "files" in result.lower()

                # Should show sizes
                assert "MB" in result

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

                # Lean format shows total size as "X.XX MB"
                # (combines DB + vector into single total)
                assert "MB" in result

                # JSON format provides detailed breakdown
                result_json = await manage_workspace(
                    operation="stats", workspace_id=workspace_id, output_format="json"
                )
                import json
                data = json.loads(result_json)
                assert "db_size_mb" in data
                assert "vector_size_mb" in data

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
