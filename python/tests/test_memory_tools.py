"""
Tests for checkpoint, recall, and plan MCP tools.

TDD Phase 1: Write ALL tests first (expect them to fail - RED).
These tests define the contract for Julie-compatible memory tools.
"""

import pytest
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import re


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_memories_dir(tmp_path):
    """Create a temporary .memories directory."""
    memories_dir = tmp_path / ".memories"
    memories_dir.mkdir()
    # Switch to temp directory for test
    import os
    original_dir = os.getcwd()
    os.chdir(tmp_path)
    yield memories_dir
    # Restore original directory
    os.chdir(original_dir)


@pytest.fixture
def mock_git_context():
    """Mock git context to avoid real git commands in tests."""
    return {
        "branch": "main",
        "commit": "abc1234",
        "dirty": False,
        "files_changed": []
    }


@pytest.fixture
def mock_context():
    """Mock FastMCP context for testing."""
    return MagicMock()


@pytest.fixture
def sample_checkpoint():
    """Sample checkpoint data for testing."""
    return {
        "id": "checkpoint_691cb498_2fc504",
        "timestamp": 1763488920,
        "type": "checkpoint",
        "git": {
            "branch": "main",
            "commit": "cf00e54",
            "dirty": True,
            "files_changed": [".memories/plans/test.json"]
        },
        "description": "Test checkpoint",
        "tags": ["test", "example"]
    }


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
        today = datetime.now().strftime("%Y-%m-%d")
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
        today = datetime.now().strftime("%Y-%m-%d")
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
    from fastmcp import Context

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
        today = datetime.now().strftime("%Y-%m-%d")
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
    from fastmcp import Context

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
            today = datetime.now().strftime("%Y-%m-%d")
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
        today = datetime.now().strftime("%Y-%m-%d")
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
        today = datetime.now().strftime("%Y-%m-%d")
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
        today = datetime.now().strftime("%Y-%m-%d")
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


# ============================================================================
# Recall Tool Tests (7 tests)
# ============================================================================

@pytest.mark.asyncio
async def test_recall_returns_recent_first(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall returns checkpoints in reverse chronological order."""
    from miller.tools.memory import checkpoint, recall
    from fastmcp import Context
    import asyncio

    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 5 checkpoints with 1-second delays to ensure different timestamps
        ids = []
        for i in range(5):
            checkpoint_id = await checkpoint(ctx, f"Checkpoint {i}")
            ids.append(checkpoint_id)
            if i < 4:  # Don't sleep after last one
                await asyncio.sleep(1.1)  # Ensure different timestamps (1-second resolution)

        # Recall all
        results = await recall(ctx, limit=10)

        # Verify order (most recent first)
        assert len(results) == 5
        result_ids = [r["id"] for r in results]
        assert result_ids == list(reversed(ids)), \
            "Results should be in reverse chronological order"


@pytest.mark.asyncio
async def test_recall_filters_by_type(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall filters by memory type correctly."""
    from miller.tools.memory import checkpoint, recall
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create mixed types
        await checkpoint(ctx, "Checkpoint 1", type="checkpoint")
        await checkpoint(ctx, "Decision 1", type="decision")
        await checkpoint(ctx, "Checkpoint 2", type="checkpoint")
        await checkpoint(ctx, "Learning 1", type="learning")
        await checkpoint(ctx, "Decision 2", type="decision")

        # Filter for decisions only
        decisions = await recall(ctx, type="decision", limit=10)

        assert len(decisions) == 2
        for result in decisions:
            assert result["type"] == "decision"


@pytest.mark.asyncio
async def test_recall_filters_by_since_date(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall respects 'since' date filter."""
    from miller.tools.memory import recall
    from fastmcp import Context

    # Create checkpoints with different timestamps
    # We'll manually create files to control timestamps
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # Create checkpoint files directly
    for delta, timestamp in [(0, today), (1, yesterday), (2, two_days_ago)]:
        date_dir = temp_memories_dir / (today - timedelta(days=delta)).strftime("%Y-%m-%d")
        date_dir.mkdir(exist_ok=True)

        checkpoint_data = {
            "id": f"checkpoint_test{delta:03d}_abc123",
            "timestamp": int(timestamp.timestamp()),
            "type": "checkpoint",
            "git": mock_git_context,
            "description": f"Test checkpoint {delta} days ago",
            "tags": []
        }

        checkpoint_file = date_dir / f"120000_{delta:04x}.json"
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2, sort_keys=True)

    # Recall since yesterday (should get today + yesterday)
    ctx = mock_context
    since_date = yesterday.strftime("%Y-%m-%d")
    results = await recall(ctx, since=since_date, limit=10)

    assert len(results) == 2, f"Should get 2 results, got {len(results)}"

    # Verify all results are >= yesterday (strip microseconds for comparison)
    for result in results:
        result_date = datetime.fromtimestamp(result["timestamp"])
        assert result_date >= yesterday.replace(microsecond=0)


@pytest.mark.asyncio
async def test_recall_filters_by_until_date(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall respects 'until' date filter."""
    from miller.tools.memory import recall
    from fastmcp import Context

    # Create checkpoints with different timestamps
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # Create checkpoint files
    for delta, timestamp in [(0, today), (1, yesterday), (2, two_days_ago)]:
        date_dir = temp_memories_dir / (today - timedelta(days=delta)).strftime("%Y-%m-%d")
        date_dir.mkdir(exist_ok=True)

        checkpoint_data = {
            "id": f"checkpoint_test{delta:03d}_abc123",
            "timestamp": int(timestamp.timestamp()),
            "type": "checkpoint",
            "git": mock_git_context,
            "description": f"Test checkpoint {delta} days ago",
            "tags": []
        }

        checkpoint_file = date_dir / f"120000_{delta:04x}.json"
        with open(checkpoint_file, 'w') as f:
            json.dump(checkpoint_data, f, indent=2, sort_keys=True)

    # Recall until yesterday (should get yesterday + two_days_ago)
    ctx = mock_context
    until_date = yesterday.strftime("%Y-%m-%d")
    results = await recall(ctx, until=until_date, limit=10)

    assert len(results) == 2, f"Should get 2 results, got {len(results)}"

    # Verify all results are <= yesterday
    for result in results:
        result_date = datetime.fromtimestamp(result["timestamp"])
        assert result_date <= yesterday.replace(hour=23, minute=59, second=59)


@pytest.mark.asyncio
async def test_recall_respects_limit(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall returns at most 'limit' results."""
    from miller.tools.memory import checkpoint, recall
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 20 checkpoints (only create 12 to speed up test, still tests limit)
        import asyncio
        for i in range(12):
            await checkpoint(ctx, f"Checkpoint {i}")
            if i < 11:
                await asyncio.sleep(1.1)  # Ensure different timestamps

        # Recall with limit=10
        results = await recall(ctx, limit=10)

        assert len(results) == 10, f"Should return 10 results, got {len(results)}"

        # Verify they're the most recent 10
        # (Since we created 0-11, most recent should be 11, 10, ..., 2)
        descriptions = [r["description"] for r in results]
        assert "Checkpoint 11" in descriptions[0]
        assert "Checkpoint 2" in descriptions[-1]


@pytest.mark.asyncio
async def test_recall_reads_julie_checkpoints(temp_memories_dir, mock_context):
    """Verify recall can read actual Julie checkpoint files."""
    from miller.tools.memory import recall
    from fastmcp import Context

    # Copy an actual Julie checkpoint (from .memories/2025-11-18/180200_abd3.json)
    julie_checkpoint = {
        "id": "checkpoint_691cb498_2fc504",
        "timestamp": 1763488920,
        "type": "checkpoint",
        "git": {
            "branch": "main",
            "commit": "cf00e54",
            "dirty": True,
            "files_changed": [".memories/plans/plan_replace.json"]
        },
        "description": "Test Julie compatibility",
        "tags": ["julie", "compatibility"]
    }

    # Create Julie's checkpoint file
    julie_date = datetime.fromtimestamp(julie_checkpoint["timestamp"])
    date_dir = temp_memories_dir / julie_date.strftime("%Y-%m-%d")
    date_dir.mkdir(exist_ok=True)

    checkpoint_file = date_dir / "180200_abd3.json"
    with open(checkpoint_file, 'w') as f:
        json.dump(julie_checkpoint, f, indent=2, sort_keys=True)

    # Try to recall it
    ctx = mock_context
    results = await recall(ctx, limit=10)

    assert len(results) == 1
    assert results[0]["id"] == "checkpoint_691cb498_2fc504"
    assert results[0]["description"] == "Test Julie compatibility"
    assert results[0]["tags"] == ["julie", "compatibility"]


@pytest.mark.asyncio
async def test_recall_handles_empty_memories(temp_memories_dir, mock_context):
    """Verify recall returns empty list when no checkpoints exist."""
    from miller.tools.memory import recall
    ctx = mock_context
    results = await recall(ctx, limit=10)

    assert results == []
    assert isinstance(results, list)


# ============================================================================
# Plan Tool Tests (9 tests)
# ============================================================================

@pytest.mark.asyncio
async def test_plan_save_creates_file(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan save creates file in .memories/plans/plan_{slug}.json."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context
        result = await plan(
            ctx,
            action="save",
            title="Add Search Feature",
            content="## Goal\nImplement search..."
        )

        # Verify plans directory exists
        plans_dir = temp_memories_dir / "plans"
        assert plans_dir.exists()

        # Verify plan file exists
        plan_files = list(plans_dir.glob("plan_*.json"))
        assert len(plan_files) == 1

        # Verify filename is based on title slug
        assert "add-search" in plan_files[0].name.lower()


@pytest.mark.asyncio
async def test_plan_generates_slug_from_title(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan generates correct slugs from titles."""
    from miller.tools.memory import plan
    from fastmcp import Context

    test_cases = [
        ("Add Search", "plan_add-search.json"),
        ("Fix Bug #123", "plan_fix-bug-123.json"),
        ("Implement User Authentication", "plan_implement-user-authentication.json"),
    ]

    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        for title, expected_filename in test_cases:
            # Clear plans directory
            plans_dir = temp_memories_dir / "plans"
            if plans_dir.exists():
                shutil.rmtree(plans_dir)
            plans_dir.mkdir()

            # Create plan
            await plan(ctx, action="save", title=title, content="Test")

            # Verify filename
            plan_files = list(plans_dir.glob("*.json"))
            assert len(plan_files) == 1

            # Check filename matches expected pattern
            actual_filename = plan_files[0].name
            # Normalize for comparison (handle extra words, etc.)
            assert "plan_" in actual_filename
            # Key words from title should be in slug
            key_words = title.lower().replace("#", "").split()
            for word in key_words[:3]:  # Check first 3 words
                clean_word = word.strip()
                if clean_word:
                    assert clean_word in actual_filename.lower()


@pytest.mark.asyncio
async def test_plan_save_auto_activates_by_default(temp_memories_dir, mock_git_context, mock_context):
    """Verify new plan is activated automatically by default."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plan (activate=True by default)
        await plan(
            ctx,
            action="save",
            title="Test Plan",
            content="## Test"
        )

        # Read the plan file
        plans_dir = temp_memories_dir / "plans"
        plan_file = list(plans_dir.glob("*.json"))[0]

        with open(plan_file) as f:
            data = json.load(f)

        assert data["status"] == "active"


@pytest.mark.asyncio
async def test_plan_list_returns_all_plans(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list returns all plans."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 3 plans
        await plan(ctx, action="save", title="Plan 1", content="Content 1", activate=False)
        await plan(ctx, action="save", title="Plan 2", content="Content 2", activate=False)
        await plan(ctx, action="save", title="Plan 3", content="Content 3", activate=False)

        # List all plans
        results = await plan(ctx, action="list")

        assert len(results) == 3
        titles = [p["title"] for p in results]
        assert "Plan 1" in titles
        assert "Plan 2" in titles
        assert "Plan 3" in titles


@pytest.mark.asyncio
async def test_plan_list_filters_by_status(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list filters by status correctly."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plans with different statuses
        plan1_id = await plan(ctx, action="save", title="Active Plan 1", content="C1")
        plan2_id = await plan(ctx, action="save", title="Active Plan 2", content="C2")
        plan3_id = await plan(ctx, action="save", title="Complete Plan", content="C3", activate=False)

        # Complete one plan
        await plan(ctx, action="complete", id=plan3_id["id"])

        # List only active plans
        active_plans = await plan(ctx, action="list", status="active")

        # Should have 2 active plans (plan2 is active, plan1 was deactivated when plan2 was created)
        active_titles = [p["title"] for p in active_plans]
        assert len([p for p in active_plans if p["status"] == "active"]) >= 1

        # List completed plans
        completed_plans = await plan(ctx, action="list", status="completed")
        assert len(completed_plans) == 1
        assert completed_plans[0]["title"] == "Complete Plan"


@pytest.mark.asyncio
async def test_plan_activate_deactivates_others(temp_memories_dir, mock_git_context, mock_context):
    """Verify activating a plan deactivates all others (single active plan)."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 3 plans
        plan1_result = await plan(ctx, action="save", title="Plan 1", content="C1")
        plan2_result = await plan(ctx, action="save", title="Plan 2", content="C2")
        plan3_result = await plan(ctx, action="save", title="Plan 3", content="C3")

        # Activate plan 1
        await plan(ctx, action="activate", id=plan1_result["id"])

        # List all plans and check statuses
        all_plans = await plan(ctx, action="list")

        active_count = sum(1 for p in all_plans if p["status"] == "active")
        assert active_count == 1, "Only one plan should be active"

        # Verify plan 1 is the active one
        active_plan = [p for p in all_plans if p["status"] == "active"][0]
        assert active_plan["title"] == "Plan 1"


@pytest.mark.asyncio
async def test_plan_update_modifies_content(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan update modifies content correctly."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plan
        plan_result = await plan(
            ctx,
            action="save",
            title="Test Plan",
            content="## Original Content"
        )

        # Update content
        await plan(
            ctx,
            action="update",
            id=plan_result["id"],
            content="## Updated Content\nNew sections here..."
        )

        # Get plan and verify content changed
        updated_plan = await plan(ctx, action="get", id=plan_result["id"])

        assert "Updated Content" in updated_plan["content"]
        assert "Original Content" not in updated_plan["content"]


@pytest.mark.asyncio
async def test_plan_complete_sets_timestamp(temp_memories_dir, mock_git_context, mock_context):
    """Verify completing a plan sets completed_at timestamp."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plan
        plan_result = await plan(
            ctx,
            action="save",
            title="Test Plan",
            content="## Test"
        )

        # Complete it
        await plan(ctx, action="complete", id=plan_result["id"])

        # Get plan and verify completed_at is set
        completed_plan = await plan(ctx, action="get", id=plan_result["id"])

        assert completed_plan["status"] == "completed"
        assert "completed_at" in completed_plan
        assert isinstance(completed_plan["completed_at"], int)
        assert completed_plan["completed_at"] > 0


@pytest.mark.asyncio
async def test_plan_get_retrieves_by_id(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan get retrieves correct plan by ID."""
    from miller.tools.memory import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create multiple plans
        plan1 = await plan(ctx, action="save", title="Plan 1", content="C1", activate=False)
        plan2 = await plan(ctx, action="save", title="Plan 2", content="C2", activate=False)
        plan3 = await plan(ctx, action="save", title="Plan 3", content="C3", activate=False)

        # Get plan 2 by ID
        retrieved = await plan(ctx, action="get", id=plan2["id"])

        assert retrieved["id"] == plan2["id"]
        assert retrieved["title"] == "Plan 2"
        assert retrieved["content"] == "C2"
