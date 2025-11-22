"""
Tests for workspace-specific search (Phase 2.3).

Following TDD: These tests are written FIRST, before implementation.
"""

import sys
import tempfile
from pathlib import Path

import pytest

from miller.server import fast_search
from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows has SQLite file locking issues during temp directory cleanup"
)
class TestWorkspaceSearch:
    """Test searching specific workspaces."""

    @pytest.mark.asyncio
    async def test_search_without_workspace_id_uses_default(self):
        """Search without workspace_id parameter works (current behavior)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Search should work without workspace_id (uses default workspace)
                # This should not crash - we may or may not have results
                # Use output_format="json" to get structured results for testing
                results = await fast_search("test", output_format="json")

                # Should return a list (may be empty if nothing indexed)
                assert isinstance(results, list)

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_search_with_workspace_id_parameter(self):
        """fast_search accepts workspace_id parameter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create and add a reference workspace
                ref_workspace = Path(tmpdir) / "ref"
                ref_workspace.mkdir()
                (ref_workspace / "test.py").write_text("def hello(): pass")

                # Add workspace
                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Reference"
                )

                # Get workspace_id from registry
                registry = WorkspaceRegistry()
                workspaces = registry.list_workspaces()
                workspace_id = workspaces[0]["workspace_id"]

                # Search that specific workspace
                # Use output_format="json" to get structured results for testing
                results = await fast_search("hello", workspace_id=workspace_id, output_format="json")

                # Should return a list
                assert isinstance(results, list)

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_search_finds_symbols_in_specific_workspace(self):
        """Search with workspace_id finds symbols in that workspace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create reference workspace with unique symbol
                ref_workspace = Path(tmpdir) / "ref"
                ref_workspace.mkdir()
                (ref_workspace / "unique.py").write_text(
                    """
def unique_function_abc123():
    '''A unique function.'''
    return 'unique'
"""
                )

                # Add workspace and index
                result = await manage_workspace(
                    operation="add", path=str(ref_workspace), name="Unique Workspace"
                )

                # Get workspace_id
                registry = WorkspaceRegistry()
                workspace_id = registry.list_workspaces()[0]["workspace_id"]

                # Search in that workspace
                # Use output_format="json" to get structured results for testing
                results = await fast_search("unique_function_abc123", workspace_id=workspace_id, output_format="json")

                # Should find the symbol
                assert len(results) > 0
                assert any("unique_function_abc123" in r.get("name", "") for r in results)

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_search_different_workspaces_isolated(self):
        """Searching different workspaces returns different results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace A with symbol_a
                workspace_a = Path(tmpdir) / "workspace_a"
                workspace_a.mkdir()
                (workspace_a / "a.py").write_text("def symbol_in_a(): pass")

                # Create workspace B with symbol_b
                workspace_b = Path(tmpdir) / "workspace_b"
                workspace_b.mkdir()
                (workspace_b / "b.py").write_text("def symbol_in_b(): pass")

                # Add both workspaces
                await manage_workspace(operation="add", path=str(workspace_a), name="Workspace A")
                await manage_workspace(operation="add", path=str(workspace_b), name="Workspace B")

                # Get workspace IDs
                registry = WorkspaceRegistry()
                workspaces = {ws["name"]: ws["workspace_id"] for ws in registry.list_workspaces()}

                ws_a_id = workspaces["Workspace A"]
                ws_b_id = workspaces["Workspace B"]

                # Search workspace A (use json format for structured results)
                results_a = await fast_search("symbol", workspace_id=ws_a_id, output_format="json")

                # Search workspace B (use json format for structured results)
                results_b = await fast_search("symbol", workspace_id=ws_b_id, output_format="json")

                # Results should be different (each workspace has different symbols)
                # Workspace A should have symbol_in_a
                names_a = [r.get("name", "") for r in results_a]
                assert "symbol_in_a" in names_a
                assert "symbol_in_b" not in names_a

                # Workspace B should have symbol_in_b
                names_b = [r.get("name", "") for r in results_b]
                assert "symbol_in_b" in names_b
                assert "symbol_in_a" not in names_b

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_search_nonexistent_workspace_returns_empty(self):
        """Searching non-existent workspace returns empty results or error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Search with non-existent workspace_id
                results = await fast_search("test", workspace_id="nonexistent_abc123")

                # Should return empty list (no crash)
                assert isinstance(results, list)
                assert len(results) == 0

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_search_preserves_all_search_methods(self):
        """workspace_id parameter works with all search methods."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace
                ref_workspace = Path(tmpdir) / "ref"
                ref_workspace.mkdir()
                (ref_workspace / "test.py").write_text("def test(): pass")

                # Add workspace
                await manage_workspace(operation="add", path=str(ref_workspace), name="Test")

                # Get workspace_id
                registry = WorkspaceRegistry()
                workspace_id = registry.list_workspaces()[0]["workspace_id"]

                # Test all search methods with workspace_id (use json format for structured results)
                results_auto = await fast_search("test", workspace_id=workspace_id, method="auto", output_format="json")
                results_text = await fast_search("test", workspace_id=workspace_id, method="text", output_format="json")
                results_semantic = await fast_search("test", workspace_id=workspace_id, method="semantic", output_format="json")
                results_hybrid = await fast_search("test", workspace_id=workspace_id, method="hybrid", output_format="json")

                # Verify all methods return valid results (list of dicts with expected keys)
                for results, method in [
                    (results_auto, "auto"),
                    (results_text, "text"),
                    (results_semantic, "semantic"),
                    (results_hybrid, "hybrid")
                ]:
                    assert isinstance(results, list), f"{method} should return a list"
                    # Each result should have the expected structure
                    for result in results:
                        assert "name" in result, f"{method} results should have 'name' field"
                        assert "file_path" in result, f"{method} results should have 'file_path' field"

            finally:
                os.chdir(original_dir)
