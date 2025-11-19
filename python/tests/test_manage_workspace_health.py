"""
Tests for manage_workspace health operation (Phase 3.3).

Following TDD: These tests are written FIRST, before implementation.

Health check operation should:
- Show registry status (workspace count, types)
- Show database health and sizes
- Show vector index status
- Support detailed mode for more information
- Handle edge cases gracefully
"""

import tempfile
from pathlib import Path
import pytest

from miller.tools.workspace import manage_workspace
from miller.workspace_registry import WorkspaceRegistry


class TestManageWorkspaceHealth:
    """Test manage_workspace health operation."""

    @pytest.mark.asyncio
    async def test_health_with_no_workspaces(self):
        """Health check with no workspaces shows appropriate status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = await manage_workspace(operation="health")

                # Should show health check header
                assert "health" in result.lower()

                # Should indicate no workspaces
                assert "0" in result or "no workspaces" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_shows_workspace_count(self):
        """Health check shows total workspace count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create two workspaces
                for i in range(2):
                    ws_dir = Path(tmpdir) / f"project{i}"
                    ws_dir.mkdir()
                    (ws_dir / "main.py").write_text(f"def func{i}(): pass")

                    registry = WorkspaceRegistry()
                    registry.add_workspace(
                        path=str(ws_dir),
                        name=f"Project {i}",
                        workspace_type="primary" if i == 0 else "reference"
                    )

                result = await manage_workspace(operation="health")

                # Should show workspace count
                assert "2" in result
                assert "workspace" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_shows_workspace_types(self):
        """Health check shows breakdown by workspace type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create primary and reference workspaces
                ws1_dir = Path(tmpdir) / "primary_ws"
                ws1_dir.mkdir()
                (ws1_dir / "main.py").write_text("def hello(): pass")

                ws2_dir = Path(tmpdir) / "reference_ws"
                ws2_dir.mkdir()
                (ws2_dir / "utils.py").write_text("def util(): pass")

                registry = WorkspaceRegistry()
                registry.add_workspace(
                    path=str(ws1_dir), name="Primary", workspace_type="primary"
                )
                registry.add_workspace(
                    path=str(ws2_dir), name="Reference", workspace_type="reference"
                )

                result = await manage_workspace(operation="health")

                # Should show both types
                assert "primary" in result.lower()
                assert "reference" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_shows_total_symbols_and_files(self):
        """Health check shows aggregate statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create and index workspace
                ws_dir = Path(tmpdir) / "project"
                ws_dir.mkdir()
                (ws_dir / "main.py").write_text("def hello(): pass")
                (ws_dir / "utils.py").write_text("def util(): pass")

                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(ws_dir), name="Test Project", workspace_type="primary"
                )

                # Index workspace
                await manage_workspace(operation="refresh", workspace_id=workspace_id)

                result = await manage_workspace(operation="health")

                # Should show totals
                assert "symbols" in result.lower() or "symbol" in result.lower()
                assert "files" in result.lower() or "file" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_detailed_mode(self):
        """Health check with detailed flag shows more information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace
                ws_dir = Path(tmpdir) / "project"
                ws_dir.mkdir()
                (ws_dir / "main.py").write_text("def hello(): pass")

                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(ws_dir), name="Test Project", workspace_type="primary"
                )

                # Index workspace
                await manage_workspace(operation="refresh", workspace_id=workspace_id)

                # Get detailed health
                result = await manage_workspace(operation="health", detailed=True)

                # Detailed mode should show individual workspace info
                assert "Test Project" in result

                # Should show database or storage info
                assert "database" in result.lower() or "storage" in result.lower() or "db" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_shows_storage_sizes(self):
        """Health check shows storage usage information."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create and index workspace
                ws_dir = Path(tmpdir) / "project"
                ws_dir.mkdir()
                (ws_dir / "main.py").write_text("def hello(): pass")

                registry = WorkspaceRegistry()
                workspace_id = registry.add_workspace(
                    path=str(ws_dir), name="Test Project", workspace_type="primary"
                )

                # Index to create data files
                await manage_workspace(operation="refresh", workspace_id=workspace_id)

                result = await manage_workspace(operation="health", detailed=True)

                # Should show size information (MB, KB, or bytes)
                assert "mb" in result.lower() or "kb" in result.lower() or "bytes" in result.lower() or "size" in result.lower()

            finally:
                os.chdir(original_dir)

    @pytest.mark.asyncio
    async def test_health_identifies_issues(self):
        """Health check identifies potential issues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create workspace then delete its directory (orphaned)
                ws_dir = Path(tmpdir) / "project"
                ws_dir.mkdir()
                (ws_dir / "main.py").write_text("def hello(): pass")

                registry = WorkspaceRegistry()
                registry.add_workspace(
                    path=str(ws_dir), name="Test Project", workspace_type="primary"
                )

                # Delete directory to create orphan
                import shutil
                shutil.rmtree(ws_dir)

                result = await manage_workspace(operation="health")

                # Should identify the issue
                assert "orphaned" in result.lower() or "missing" in result.lower() or "issue" in result.lower() or "warning" in result.lower()

            finally:
                os.chdir(original_dir)
