"""
Tests for manage_workspace add operation (Phase 2.1).

Following TDD: These tests are written FIRST, before implementation.
"""

import tempfile
from pathlib import Path

import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry


class TestManageWorkspaceAdd:
    """Test manage_workspace add operation."""

    @pytest.mark.asyncio
    async def test_add_requires_path(self):
        """Add operation requires path parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="add", name="Test")

                # Should return error
                assert "error" in result.lower() or "required" in result.lower()
                assert "path" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_requires_name(self):
        """Add operation requires name parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="add", path="/test/path")

                # Should return error
                assert "error" in result.lower() or "required" in result.lower()
                assert "name" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_reference_workspace(self):
        """Can add reference workspace to registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create a test workspace directory with some Python files
                ref_workspace = Path(tmpdir) / "reference_project"
                ref_workspace.mkdir()
                (ref_workspace / "test.py").write_text("def hello(): pass")

                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Reference Project"
                )

                # Should report success
                assert "success" in result.lower() or "added" in result.lower()
                assert "Reference Project" in result

                # Verify it's in registry
                registry = WorkspaceRegistry()
                workspaces = registry.list_workspaces()
                assert len(workspaces) == 1

                ws = workspaces[0]
                assert ws["name"] == "Reference Project"
                assert ws["workspace_type"] == "reference"
                # Path may be resolved (e.g., /var -> /private/var on macOS)
                assert ws["path"] == str(ref_workspace.resolve())

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_creates_workspace_directories(self):
        """Adding workspace creates DB and vector directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create test workspace
                ref_workspace = Path(tmpdir) / "reference_project"
                ref_workspace.mkdir()
                (ref_workspace / "test.py").write_text("def test(): pass")

                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Test Workspace"
                )

                # Get workspace ID from registry
                registry = WorkspaceRegistry()
                workspaces = registry.list_workspaces()
                workspace_id = workspaces[0]["workspace_id"]

                # Verify directories were created
                from miller.workspace_paths import get_workspace_db_path, get_workspace_vector_path

                db_path = get_workspace_db_path(workspace_id)
                vector_path = get_workspace_vector_path(workspace_id)

                assert db_path.parent.exists()
                assert vector_path.parent.exists()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_indexes_workspace_symbols(self):
        """Adding reference workspace triggers indexing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create test workspace with actual code
                ref_workspace = Path(tmpdir) / "reference_project"
                ref_workspace.mkdir()

                # Create Python file with symbols
                (ref_workspace / "module.py").write_text(
                    """
def hello():
    '''Say hello.'''
    return 'Hello'

class Person:
    '''A person.'''
    def __init__(self, name):
        self.name = name
"""
                )

                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Indexed Project"
                )

                # Should report indexing
                assert "success" in result.lower() or "indexed" in result.lower()

                # Verify registry has updated stats
                registry = WorkspaceRegistry()
                workspaces = registry.list_workspaces()
                ws = workspaces[0]

                # Should have indexed symbols
                assert ws["symbol_count"] > 0, "Should have indexed symbols"
                assert ws["file_count"] > 0, "Should have indexed files"
                assert ws["last_indexed"] is not None, "Should have last_indexed timestamp"

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_nonexistent_path_fails(self):
        """Adding workspace with non-existent path fails gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(
                    operation="add", path="/does/not/exist/anywhere", name="Phantom Project"
                )

                # Should report error
                assert "error" in result.lower() or "not found" in result.lower() or "exist" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_add_shows_progress(self):
        """Add operation shows indexing progress."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace
                ref_workspace = Path(tmpdir) / "ref"
                ref_workspace.mkdir()
                (ref_workspace / "code.py").write_text("def test(): pass")

                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Test"
                )

                # Should include helpful information
                assert "symbol" in result.lower() or "file" in result.lower()

            finally:
                os.chdir(original_dir)
