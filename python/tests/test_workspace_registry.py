"""
Tests for WorkspaceRegistry - Workspace registration and metadata management.

Following TDD: These tests are written FIRST, before implementation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from miller.workspace_registry import WorkspaceEntry, WorkspaceRegistry


class TestWorkspaceRegistry:
    """Test workspace registry functionality."""

    def test_registry_initializes_empty(self):
        """Registry starts with no workspaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))
            assert registry.list_workspaces() == []

    def test_registry_adds_workspace(self):
        """Can add workspace with metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            workspace_id = registry.add_workspace(
                path="/path/to/project", name="My Project", workspace_type="primary"
            )

            assert workspace_id.startswith("workspace_")
            workspaces = registry.list_workspaces()
            assert len(workspaces) == 1
            assert workspaces[0]["name"] == "My Project"
            assert workspaces[0]["workspace_type"] == "primary"
            assert workspaces[0]["path"] == "/path/to/project"

    def test_registry_persists_to_disk(self):
        """Registry saves and loads from disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Create and add workspace
            registry = WorkspaceRegistry(path=str(registry_path))
            workspace_id = registry.add_workspace(path="/test", name="Test")

            # Reload from disk
            registry2 = WorkspaceRegistry(path=str(registry_path))
            workspaces = registry2.list_workspaces()
            assert len(workspaces) == 1
            assert workspaces[0]["workspace_id"] == workspace_id
            assert workspaces[0]["name"] == "Test"

    def test_registry_generates_unique_ids(self):
        """Workspace IDs are unique and stable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            id1 = registry.add_workspace(path="/project1", name="Proj1")
            id2 = registry.add_workspace(path="/project2", name="Proj2")

            # Different paths should generate different IDs
            assert id1 != id2

            # Same path should generate same ID (idempotent)
            id3 = registry.add_workspace(path="/project1", name="Proj1")
            assert id1 == id3

    def test_get_workspace_by_id(self):
        """Can retrieve specific workspace by ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            workspace_id = registry.add_workspace(path="/test", name="Test Project")

            workspace = registry.get_workspace(workspace_id)
            assert workspace is not None
            assert workspace.name == "Test Project"
            assert workspace.workspace_id == workspace_id

    def test_get_nonexistent_workspace_returns_none(self):
        """Getting non-existent workspace returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            workspace = registry.get_workspace("nonexistent_abc123")
            assert workspace is None

    def test_remove_workspace(self):
        """Can remove workspace from registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            workspace_id = registry.add_workspace(path="/test", name="Test")
            assert len(registry.list_workspaces()) == 1

            # Remove workspace
            result = registry.remove_workspace(workspace_id)
            assert result is True
            assert len(registry.list_workspaces()) == 0

    def test_remove_nonexistent_workspace_returns_false(self):
        """Removing non-existent workspace returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            result = registry.remove_workspace("nonexistent_abc123")
            assert result is False

    def test_workspace_entry_has_metadata_fields(self):
        """WorkspaceEntry includes all expected metadata fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            workspace_id = registry.add_workspace(
                path="/test", name="Test", workspace_type="reference"
            )

            workspace = registry.get_workspace(workspace_id)
            assert workspace.workspace_id == workspace_id
            assert workspace.name == "Test"
            assert workspace.path == "/test"
            assert workspace.workspace_type == "reference"
            assert workspace.created_at > 0
            assert workspace.last_indexed is None  # Not yet indexed
            assert workspace.symbol_count == 0
            assert workspace.file_count == 0

    def test_registry_file_format_is_json(self):
        """Registry file is valid JSON with pretty formatting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = WorkspaceRegistry(path=str(registry_path))

            registry.add_workspace(path="/test", name="Test")

            # Read raw file
            with open(registry_path) as f:
                data = json.load(f)

            # Should be a dict with workspace IDs as keys
            assert isinstance(data, dict)
            assert len(data) == 1

            # File should be pretty-printed (check for indentation)
            with open(registry_path) as f:
                content = f.read()
                assert "  " in content  # Has indentation
