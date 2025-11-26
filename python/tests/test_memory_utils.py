"""
Tests for memory_utils.py - core memory file handling utilities.

Tests cover:
- Markdown with YAML frontmatter format (write/read)
- Legacy JSON format backward compatibility
- Migration from JSON to Markdown
- Tag normalization
- Slug generation
- Git context capture
"""

import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch

from miller.memory_utils import (
    generate_checkpoint_id,
    generate_checkpoint_filename,
    get_checkpoint_path,
    slugify_title,
    write_memory_file,
    read_memory_file,
    write_json_file,
    read_json_file,
    migrate_json_to_markdown,
    migrate_all_memories,
    normalize_tags,
    get_git_context,
)


# ============================================================================
# Checkpoint ID Generation Tests
# ============================================================================


class TestCheckpointIdGeneration:
    """Tests for checkpoint ID generation."""

    def test_generates_correct_format(self):
        """ID should be {type}_{8hex}_{6hex}."""
        id = generate_checkpoint_id("checkpoint")
        parts = id.split("_")
        assert len(parts) == 3
        assert parts[0] == "checkpoint"
        assert len(parts[1]) == 8  # 8 hex chars
        assert len(parts[2]) == 6  # 6 hex chars

    def test_respects_type_parameter(self):
        """ID should use provided type."""
        for type_name in ["decision", "learning", "observation"]:
            id = generate_checkpoint_id(type_name)
            assert id.startswith(f"{type_name}_")

    def test_generates_unique_ids(self):
        """Each call should generate a unique ID."""
        ids = [generate_checkpoint_id() for _ in range(100)]
        assert len(set(ids)) == 100


class TestCheckpointFilename:
    """Tests for checkpoint filename generation."""

    def test_generates_md_extension(self):
        """Filename should have .md extension."""
        filename = generate_checkpoint_filename()
        assert filename.endswith(".md")

    def test_correct_format(self):
        """Filename should be HHMMSS_XXXX.md."""
        filename = generate_checkpoint_filename()
        # Should be 14 chars: HHMMSS (6) + _ (1) + XXXX (4) + .md (3)
        assert len(filename) == 14
        assert filename[6] == "_"


class TestCheckpointPath:
    """Tests for checkpoint path generation."""

    def test_creates_correct_path_structure(self):
        """Path should be .memories/YYYY-MM-DD/filename.md."""
        timestamp = int(time.time())
        path = get_checkpoint_path(timestamp)

        assert ".memories" in str(path)
        # Should have date directory
        parts = path.parts
        assert len([p for p in parts if "-" in p and len(p) == 10]) >= 1
        assert path.suffix == ".md"


# ============================================================================
# Markdown File I/O Tests
# ============================================================================


class TestWriteMemoryFile:
    """Tests for write_memory_file (Markdown with YAML frontmatter)."""

    def test_creates_parent_directories(self, tmp_path):
        """Should create parent directories if they don't exist."""
        file_path = tmp_path / "deep" / "nested" / "file.md"
        metadata = {"id": "test_123", "type": "checkpoint"}
        content = "Test content"

        write_memory_file(file_path, metadata, content)

        assert file_path.exists()
        assert file_path.parent.exists()

    def test_writes_yaml_frontmatter(self, tmp_path):
        """Should write YAML frontmatter with --- delimiters."""
        file_path = tmp_path / "test.md"
        metadata = {"id": "test_123", "type": "checkpoint", "tags": ["foo", "bar"]}
        content = "Test content here"

        write_memory_file(file_path, metadata, content)

        text = file_path.read_text()
        assert text.startswith("---\n")
        assert "\n---\n" in text
        assert "id: test_123" in text
        assert "type: checkpoint" in text

    def test_writes_content_after_frontmatter(self, tmp_path):
        """Content should appear after the frontmatter."""
        file_path = tmp_path / "test.md"
        metadata = {"id": "test_123"}
        content = "This is the main content"

        write_memory_file(file_path, metadata, content)

        text = file_path.read_text()
        # Content should be after the closing ---
        parts = text.split("---\n")
        assert len(parts) >= 3
        assert "This is the main content" in parts[-1]

    def test_handles_unicode(self, tmp_path):
        """Should handle unicode in content and metadata."""
        file_path = tmp_path / "test.md"
        metadata = {"id": "test_123", "description": "日本語テスト"}
        content = "Content with émojis 🎉 and ünïcödé"

        write_memory_file(file_path, metadata, content)

        # Should be readable
        read_metadata, read_content = read_memory_file(file_path)
        assert "émojis" in read_content
        assert "🎉" in read_content


class TestReadMemoryFile:
    """Tests for read_memory_file (handles both .md and .json)."""

    def test_reads_markdown_format(self, tmp_path):
        """Should read markdown files with YAML frontmatter."""
        file_path = tmp_path / "test.md"
        metadata = {"id": "test_123", "type": "checkpoint", "timestamp": 1234567890}
        content = "Test description"

        write_memory_file(file_path, metadata, content)

        read_metadata, read_content = read_memory_file(file_path)

        assert read_metadata["id"] == "test_123"
        assert read_metadata["type"] == "checkpoint"
        assert read_metadata["timestamp"] == 1234567890
        assert read_content == "Test description"

    def test_reads_legacy_json_format(self, tmp_path):
        """Should read legacy JSON files for backward compatibility."""
        file_path = tmp_path / "test.json"
        data = {
            "id": "checkpoint_abc123",
            "type": "checkpoint",
            "description": "Legacy JSON content",
            "timestamp": 1234567890,
        }
        write_json_file(file_path, data)

        read_metadata, read_content = read_memory_file(file_path)

        assert read_metadata["id"] == "checkpoint_abc123"
        assert read_metadata["type"] == "checkpoint"
        assert read_content == "Legacy JSON content"

    def test_json_extracts_content_field_for_plans(self, tmp_path):
        """JSON plans use 'content' field, checkpoints use 'description'."""
        file_path = tmp_path / "plan.json"
        data = {
            "id": "plan_test",
            "type": "plan",
            "content": "## Goals\n- Task 1",
            "title": "Test Plan",
        }
        write_json_file(file_path, data)

        read_metadata, read_content = read_memory_file(file_path)

        assert read_content == "## Goals\n- Task 1"

    def test_raises_on_invalid_markdown(self, tmp_path):
        """Should raise ValueError for invalid markdown format."""
        file_path = tmp_path / "invalid.md"
        file_path.write_text("No frontmatter here")

        with pytest.raises(ValueError, match="missing frontmatter"):
            read_memory_file(file_path)

    def test_raises_on_unclosed_frontmatter(self, tmp_path):
        """Should raise ValueError for unclosed frontmatter."""
        file_path = tmp_path / "unclosed.md"
        file_path.write_text("---\nid: test\nNo closing delimiter")

        with pytest.raises(ValueError, match="unclosed frontmatter"):
            read_memory_file(file_path)


# ============================================================================
# Migration Tests
# ============================================================================


class TestMigration:
    """Tests for JSON to Markdown migration."""

    def test_migrate_single_file(self, tmp_path):
        """Should migrate a single JSON file to Markdown."""
        json_path = tmp_path / "checkpoint.json"
        data = {
            "id": "checkpoint_abc123",
            "type": "checkpoint",
            "description": "Test checkpoint",
            "timestamp": 1234567890,
            "tags": ["test", "migration"],
        }
        write_json_file(json_path, data)

        md_path = migrate_json_to_markdown(json_path)

        assert md_path.suffix == ".md"
        assert md_path.exists()

        # Verify content
        metadata, content = read_memory_file(md_path)
        assert metadata["id"] == "checkpoint_abc123"
        assert metadata["type"] == "checkpoint"
        assert content == "Test checkpoint"
        assert metadata["tags"] == ["test", "migration"]

    def test_migrate_all_memories(self, tmp_path):
        """Should migrate all JSON files in directory tree."""
        # Create directory structure
        (tmp_path / "2025-01-01").mkdir()
        (tmp_path / "2025-01-02").mkdir()
        (tmp_path / "plans").mkdir()

        # Create JSON files
        files = [
            tmp_path / "2025-01-01" / "checkpoint1.json",
            tmp_path / "2025-01-01" / "checkpoint2.json",
            tmp_path / "2025-01-02" / "checkpoint3.json",
            tmp_path / "plans" / "plan_test.json",
        ]

        for i, file_path in enumerate(files):
            if "plan" in file_path.name:
                data = {"id": f"plan_{i}", "type": "plan", "content": f"Content {i}"}
            else:
                data = {"id": f"checkpoint_{i}", "type": "checkpoint", "description": f"Desc {i}"}
            write_json_file(file_path, data)

        stats = migrate_all_memories(tmp_path)

        assert stats["migrated"] == 4
        assert stats["skipped"] == 0
        assert stats["errors"] == 0

        # Verify .md files exist
        md_files = list(tmp_path.rglob("*.md"))
        assert len(md_files) == 4

    def test_migration_skips_already_migrated(self, tmp_path):
        """Should skip files that already have .md counterpart."""
        json_path = tmp_path / "test.json"
        md_path = tmp_path / "test.md"

        # Create both JSON and MD
        write_json_file(json_path, {"id": "test", "description": "JSON"})
        write_memory_file(md_path, {"id": "test"}, "Markdown")

        stats = migrate_all_memories(tmp_path)

        assert stats["migrated"] == 0
        assert stats["skipped"] == 1


# ============================================================================
# Tag Normalization Tests
# ============================================================================


class TestNormalizeTags:
    """Tests for tag normalization."""

    def test_converts_to_lowercase(self):
        """Should convert tags to lowercase."""
        result = normalize_tags(["TDD", "BugFix", "IMPORTANT"])
        assert result == ["tdd", "bugfix", "important"]

    def test_replaces_underscores_with_hyphens(self):
        """Should replace underscores with hyphens."""
        result = normalize_tags(["bug_fix", "test_case"])
        assert result == ["bug-fix", "test-case"]

    def test_replaces_spaces_with_hyphens(self):
        """Should replace spaces with hyphens."""
        result = normalize_tags(["bug fix", "test case"])
        assert result == ["bug-fix", "test-case"]

    def test_removes_special_characters(self):
        """Should remove special characters except hyphens."""
        result = normalize_tags(["bug#123", "test@home", "fix!now"])
        assert result == ["bug123", "testhome", "fixnow"]

    def test_removes_consecutive_hyphens(self):
        """Should collapse consecutive hyphens."""
        result = normalize_tags(["bug--fix", "test---case"])
        assert result == ["bug-fix", "test-case"]

    def test_removes_leading_trailing_hyphens(self):
        """Should remove leading/trailing hyphens."""
        result = normalize_tags(["-bug-", "--test--"])
        assert result == ["bug", "test"]

    def test_filters_empty_tags(self):
        """Should filter out empty tags."""
        result = normalize_tags(["", "   ", "-", "valid"])
        assert result == ["valid"]


# ============================================================================
# Slug Generation Tests
# ============================================================================


class TestSlugifyTitle:
    """Tests for title slugification."""

    def test_basic_slugification(self):
        """Should convert title to URL-safe slug."""
        assert slugify_title("Add Search") == "add-search"
        assert slugify_title("Fix Bug #123") == "fix-bug-123"

    def test_handles_special_characters(self):
        """Should remove special characters."""
        assert slugify_title("Fix: Critical Bug!") == "fix-critical-bug"

    def test_collapses_multiple_hyphens(self):
        """Should collapse consecutive hyphens."""
        assert slugify_title("Fix   Multiple   Spaces") == "fix-multiple-spaces"

    def test_strips_leading_trailing_hyphens(self):
        """Should strip leading/trailing hyphens."""
        assert slugify_title("  Title  ") == "title"


# ============================================================================
# Git Context Tests
# ============================================================================


class TestGetGitContext:
    """Tests for git context capture."""

    def test_returns_expected_keys(self):
        """Should return dict with expected keys."""
        context = get_git_context()

        assert "branch" in context
        assert "commit" in context
        assert "dirty" in context
        assert "files_changed" in context

    def test_graceful_fallback_outside_git_repo(self, tmp_path, monkeypatch):
        """Should return defaults when not in a git repo."""
        # Change to a non-git directory
        monkeypatch.chdir(tmp_path)

        context = get_git_context()

        assert context["branch"] == "unknown"
        assert context["commit"] == "unknown"
        assert context["dirty"] is False
        assert context["files_changed"] == []
