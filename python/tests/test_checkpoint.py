"""
Tests for checkpoint MCP tool (memory checkpoint creation).

TDD Phase 1: Write ALL tests first (expect them to fail - RED).
These tests define the contract for Julie-compatible checkpoint functionality.

NOTE: Checkpoints are now stored as Markdown with YAML frontmatter (.md),
not JSON. Tests use read_memory_file() for format-agnostic reading.
"""

import pytest
import re
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from miller.memory_utils import read_memory_file


# ============================================================================
# Checkpoint Tool Tests (8 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_checkpoint_creates_file_in_correct_location(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint creates file in .memories/YYYY-MM-DD/HHMMSS_XXXX.md."""
    from miller.tools.checkpoint import checkpoint

    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        checkpoint_id = await checkpoint(mock_context, "Test checkpoint")

        # Find created file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        assert date_dir.exists(), f"Date directory {date_dir} should exist"

        # Should have exactly one file (now .md format)
        files = list(date_dir.glob("*.md"))
        assert len(files) == 1, f"Should have 1 checkpoint file, found {len(files)}"

        # Verify filename format: HHMMSS_XXXX.md
        filename = files[0].name
        assert re.match(r'^\d{6}_[a-f0-9]{4}\.md$', filename), \
            f"Filename {filename} doesn't match HHMMSS_XXXX.md format"


@pytest.mark.asyncio
async def test_checkpoint_schema_has_all_required_fields(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint has all required fields with correct types."""
    from miller.tools.checkpoint import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        checkpoint_id = await checkpoint(
            ctx,
            "Test checkpoint",
            tags=["test", "example"]
        )

        # Read the created file (now .md format)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.md"))[0]

        metadata, content = read_memory_file(checkpoint_file)

        # Verify all required fields exist in metadata
        assert "id" in metadata, "Missing 'id' field"
        assert "timestamp" in metadata, "Missing 'timestamp' field"
        assert "type" in metadata, "Missing 'type' field"
        assert "git" in metadata, "Missing 'git' field"
        assert "tags" in metadata, "Missing 'tags' field"
        # Description is now the content body, not in metadata
        assert content, "Content (description) should not be empty"

        # Verify field types
        assert isinstance(metadata["id"], str), "id should be string"
        assert isinstance(metadata["timestamp"], int), "timestamp should be int"
        assert isinstance(metadata["type"], str), "type should be string"
        assert isinstance(metadata["git"], dict), "git should be dict"
        assert isinstance(content, str), "content should be string"
        assert isinstance(metadata["tags"], list), "tags should be list"

        # Verify git context structure
        assert "branch" in metadata["git"], "git missing 'branch'"
        assert "commit" in metadata["git"], "git missing 'commit'"
        assert "dirty" in metadata["git"], "git missing 'dirty'"
        assert "files_changed" in metadata["git"], "git missing 'files_changed'"
        assert isinstance(metadata["git"]["dirty"], bool), "git.dirty should be bool"
        assert isinstance(metadata["git"]["files_changed"], list), "git.files_changed should be list"


@pytest.mark.asyncio
async def test_checkpoint_generates_unique_id_format(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint ID format: {type}_{8hex}_{6hex} and uniqueness."""
    from miller.tools.checkpoint import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create multiple checkpoints
        ids = []
        for i in range(5):
            checkpoint_id = await checkpoint(ctx, f"Checkpoint {i}")
            ids.append(checkpoint_id)

        # Verify format for each ID
        for checkpoint_id in ids:
            assert re.match(r'^checkpoint_[a-f0-9]{8}_[a-f0-9]{6}$', checkpoint_id), \
                f"ID {checkpoint_id} doesn't match checkpoint_{{8hex}}_{{6hex}} format"

        # Verify all IDs are unique
        assert len(ids) == len(set(ids)), "Checkpoint IDs should be unique"


@pytest.mark.asyncio
async def test_checkpoint_captures_git_context(temp_memories_dir, mock_context):
    """Verify checkpoint captures branch, commit, dirty, files_changed."""
    from miller.tools.checkpoint import checkpoint

    # Mock git context with realistic data
    mock_git = {
        "branch": "feature/memory-tools",
        "commit": "a1b2c3d",
        "dirty": True,
        "files_changed": [
            "python/miller/tools/memory.py",
            "python/tests/test_memory_tools.py"
        ]
    }

    with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git):
        ctx = mock_context
        checkpoint_id = await checkpoint(ctx, "Test git capture")

        # Read the checkpoint file (now .md format)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.md"))[0]

        metadata, content = read_memory_file(checkpoint_file)

        # Verify git context matches
        assert metadata["git"]["branch"] == "feature/memory-tools"
        assert metadata["git"]["commit"] == "a1b2c3d"
        assert metadata["git"]["dirty"] is True
        assert metadata["git"]["files_changed"] == [
            "python/miller/tools/memory.py",
            "python/tests/test_memory_tools.py"
        ]


@pytest.mark.asyncio
async def test_checkpoint_supports_all_memory_types(temp_memories_dir, mock_git_context, mock_context):
    """Test all memory types: checkpoint, decision, learning, observation."""
    from miller.tools.checkpoint import checkpoint

    memory_types = ["checkpoint", "decision", "learning", "observation"]

    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        for mem_type in memory_types:
            checkpoint_id = await checkpoint(
                ctx,
                f"Test {mem_type}",
                type=mem_type
            )

            # Verify ID starts with correct type
            assert checkpoint_id.startswith(f"{mem_type}_"), \
                f"ID should start with '{mem_type}_', got {checkpoint_id}"

            # Read file and verify type field by finding the correct checkpoint
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            date_dir = temp_memories_dir / today

            # Find the file with matching ID (now .md format)
            found = False
            for checkpoint_file in date_dir.glob("*.md"):
                metadata, content = read_memory_file(checkpoint_file)
                if metadata["id"] == checkpoint_id:
                    assert metadata["type"] == mem_type, f"Type should be '{mem_type}'"
                    found = True
                    break

            assert found, f"Couldn't find checkpoint file for {checkpoint_id}"


@pytest.mark.asyncio
async def test_checkpoint_handles_tags(temp_memories_dir, mock_git_context, mock_context):
    """Verify tags are stored as array with lowercase hyphenated format."""
    from miller.tools.checkpoint import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Test with tags
        checkpoint_id = await checkpoint(
            ctx,
            "Test with tags",
            tags=["TDD-Plan", "Julie_Compatibility", "phase planning"]
        )

        # Read file (now .md format)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.md"))[0]

        metadata, content = read_memory_file(checkpoint_file)

        # Verify tags are normalized (lowercase, hyphenated)
        assert isinstance(metadata["tags"], list)
        for tag in metadata["tags"]:
            assert tag.islower() or "-" in tag, f"Tag '{tag}' should be lowercase"
            assert " " not in tag, f"Tag '{tag}' should not contain spaces"


@pytest.mark.asyncio
async def test_checkpoint_returns_checkpoint_id(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint tool returns the generated checkpoint ID."""
    from miller.tools.checkpoint import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        checkpoint_id = await checkpoint(ctx, "Test return value")

        # Verify return value is a string with correct format
        assert isinstance(checkpoint_id, str)
        assert re.match(r'^checkpoint_[a-f0-9]{8}_[a-f0-9]{6}$', checkpoint_id)

        # Verify the ID in the file matches the return value (now .md format)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.md"))[0]

        metadata, content = read_memory_file(checkpoint_file)

        assert metadata["id"] == checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_file_is_well_formatted(temp_memories_dir, mock_git_context, mock_context):
    """Verify markdown file has proper YAML frontmatter structure."""
    from miller.tools.checkpoint import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        await checkpoint(ctx, "Test formatting", tags=["test"])

        # Read raw file content (now .md format)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.md"))[0]

        raw_content = checkpoint_file.read_text()

        # Verify it has proper YAML frontmatter structure
        assert raw_content.startswith("---\n"), "Should start with YAML frontmatter"
        assert "\n---\n" in raw_content, "Should have closing frontmatter delimiter"

        # Verify it's multi-line (readable format)
        assert raw_content.count("\n") > 5, "Should be multi-line"

        # Verify the content can be parsed correctly
        metadata, content = read_memory_file(checkpoint_file)
        assert metadata["id"], "Should have valid ID in metadata"
        assert content == "Test formatting", "Content should be preserved"
