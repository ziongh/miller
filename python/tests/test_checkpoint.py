"""
Tests for checkpoint MCP tool (memory checkpoint creation).

TDD Phase 1: Write ALL tests first (expect them to fail - RED).
These tests define the contract for Julie-compatible checkpoint functionality.
"""

import pytest
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch


# ============================================================================
# Checkpoint Tool Tests (8 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_checkpoint_creates_file_in_correct_location(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint creates file in .memories/YYYY-MM-DD/HHMMSS_XXXX.json."""
    from miller.tools.memory import checkpoint

    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        checkpoint_id = await checkpoint(mock_context, "Test checkpoint")

        # Find created file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        assert date_dir.exists(), f"Date directory {date_dir} should exist"

        # Should have exactly one file
        files = list(date_dir.glob("*.json"))
        assert len(files) == 1, f"Should have 1 checkpoint file, found {len(files)}"

        # Verify filename format: HHMMSS_XXXX.json
        filename = files[0].name
        assert re.match(r'^\d{6}_[a-f0-9]{4}\.json$', filename), \
            f"Filename {filename} doesn't match HHMMSS_XXXX.json format"


@pytest.mark.asyncio
async def test_checkpoint_json_schema_matches_julie(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint JSON has all required fields with correct types."""
    from miller.tools.memory import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        checkpoint_id = await checkpoint(
            ctx,
            "Test checkpoint",
            tags=["test", "example"]
        )

        # Read the created file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.json"))[0]

        with open(checkpoint_file) as f:
            data = json.load(f)

        # Verify all required fields exist
        assert "id" in data, "Missing 'id' field"
        assert "timestamp" in data, "Missing 'timestamp' field"
        assert "type" in data, "Missing 'type' field"
        assert "git" in data, "Missing 'git' field"
        assert "description" in data, "Missing 'description' field"
        assert "tags" in data, "Missing 'tags' field"

        # Verify field types
        assert isinstance(data["id"], str), "id should be string"
        assert isinstance(data["timestamp"], int), "timestamp should be int"
        assert isinstance(data["type"], str), "type should be string"
        assert isinstance(data["git"], dict), "git should be dict"
        assert isinstance(data["description"], str), "description should be string"
        assert isinstance(data["tags"], list), "tags should be list"

        # Verify git context structure
        assert "branch" in data["git"], "git missing 'branch'"
        assert "commit" in data["git"], "git missing 'commit'"
        assert "dirty" in data["git"], "git missing 'dirty'"
        assert "files_changed" in data["git"], "git missing 'files_changed'"
        assert isinstance(data["git"]["dirty"], bool), "git.dirty should be bool"
        assert isinstance(data["git"]["files_changed"], list), "git.files_changed should be list"


@pytest.mark.asyncio
async def test_checkpoint_generates_unique_id_format(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint ID format: {type}_{8hex}_{6hex} and uniqueness."""
    from miller.tools.memory import checkpoint
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
    from miller.tools.memory import checkpoint

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

    with patch('miller.tools.memory.get_git_context', return_value=mock_git):
        ctx = mock_context
        checkpoint_id = await checkpoint(ctx, "Test git capture")

        # Read the checkpoint file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.json"))[0]

        with open(checkpoint_file) as f:
            data = json.load(f)

        # Verify git context matches
        assert data["git"]["branch"] == "feature/memory-tools"
        assert data["git"]["commit"] == "a1b2c3d"
        assert data["git"]["dirty"] is True
        assert data["git"]["files_changed"] == [
            "python/miller/tools/memory.py",
            "python/tests/test_memory_tools.py"
        ]


@pytest.mark.asyncio
async def test_checkpoint_supports_all_memory_types(temp_memories_dir, mock_git_context, mock_context):
    """Test all memory types: checkpoint, decision, learning, observation."""
    from miller.tools.memory import checkpoint

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

            # Find the file with matching ID
            found = False
            for checkpoint_file in date_dir.glob("*.json"):
                with open(checkpoint_file) as f:
                    data = json.load(f)
                if data["id"] == checkpoint_id:
                    assert data["type"] == mem_type, f"Type should be '{mem_type}'"
                    found = True
                    break

            assert found, f"Couldn't find checkpoint file for {checkpoint_id}"


@pytest.mark.asyncio
async def test_checkpoint_handles_tags(temp_memories_dir, mock_git_context, mock_context):
    """Verify tags are stored as array with lowercase hyphenated format."""
    from miller.tools.memory import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Test with tags
        checkpoint_id = await checkpoint(
            ctx,
            "Test with tags",
            tags=["TDD-Plan", "Julie_Compatibility", "phase planning"]
        )

        # Read file
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.json"))[0]

        with open(checkpoint_file) as f:
            data = json.load(f)

        # Verify tags are normalized (lowercase, hyphenated)
        assert isinstance(data["tags"], list)
        for tag in data["tags"]:
            assert tag.islower() or "-" in tag, f"Tag '{tag}' should be lowercase"
            assert " " not in tag, f"Tag '{tag}' should not contain spaces"


@pytest.mark.asyncio
async def test_checkpoint_returns_checkpoint_id(temp_memories_dir, mock_git_context, mock_context):
    """Verify checkpoint tool returns the generated checkpoint ID."""
    from miller.tools.memory import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        checkpoint_id = await checkpoint(ctx, "Test return value")

        # Verify return value is a string with correct format
        assert isinstance(checkpoint_id, str)
        assert re.match(r'^checkpoint_[a-f0-9]{8}_[a-f0-9]{6}$', checkpoint_id)

        # Verify the ID in the file matches the return value
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.json"))[0]

        with open(checkpoint_file) as f:
            data = json.load(f)

        assert data["id"] == checkpoint_id


@pytest.mark.asyncio
async def test_checkpoint_file_is_pretty_printed(temp_memories_dir, mock_git_context, mock_context):
    """Verify JSON is formatted with indent=2 and sorted keys."""
    from miller.tools.memory import checkpoint
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        await checkpoint(ctx, "Test formatting", tags=["test"])

        # Read raw file content
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_dir = temp_memories_dir / today
        checkpoint_file = list(date_dir.glob("*.json"))[0]

        with open(checkpoint_file) as f:
            raw_content = f.read()

        # Verify it's pretty-printed (has indentation)
        assert "  " in raw_content, "JSON should be indented"
        assert raw_content.count("\n") > 5, "JSON should be multi-line"

        # Verify keys are sorted (description comes before git, git before id, etc.)
        # Parse and re-serialize with sort_keys to compare
        data = json.loads(raw_content)
        expected_content = json.dumps(data, indent=2, sort_keys=True) + "\n"
        assert raw_content == expected_content, "JSON should have sorted keys"
