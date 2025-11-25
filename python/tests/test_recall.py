"""
Tests for recall MCP tool (memory retrieval).

TDD Phase 1: Write ALL tests first (expect them to fail - RED).
These tests define the contract for Julie-compatible recall functionality.
"""

import pytest
import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch


# ============================================================================
# Recall Tool Tests (7 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_recall_returns_recent_first(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall returns checkpoints in reverse chronological order."""
    from miller.tools.checkpoint import checkpoint
    from miller.tools.recall import recall

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
        results = await recall(ctx, output_format="json", limit=10)

        # Verify order (most recent first)
        assert len(results) == 5
        result_ids = [r["id"] for r in results]
        assert result_ids == list(reversed(ids)), \
            "Results should be in reverse chronological order"


@pytest.mark.asyncio
async def test_recall_filters_by_type(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall filters by memory type correctly."""
    from miller.tools.checkpoint import checkpoint
    from miller.tools.recall import recall
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create mixed types
        await checkpoint(ctx, "Checkpoint 1", type="checkpoint")
        await checkpoint(ctx, "Decision 1", type="decision")
        await checkpoint(ctx, "Checkpoint 2", type="checkpoint")
        await checkpoint(ctx, "Learning 1", type="learning")
        await checkpoint(ctx, "Decision 2", type="decision")

        # Filter for decisions only
        decisions = await recall(ctx, output_format="json", type="decision", limit=10)

        assert len(decisions) == 2
        for result in decisions:
            assert result["type"] == "decision"


@pytest.mark.asyncio
async def test_recall_filters_by_tags(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall filters by tags (ANY match)."""
    from miller.tools.checkpoint import checkpoint
    from miller.tools.recall import recall
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create checkpoints with various tags
        await checkpoint(ctx, "Auth bug fix", tags=["auth", "bugfix"])
        await checkpoint(ctx, "DB optimization", tags=["database", "performance"])
        await checkpoint(ctx, "Auth refactor", tags=["auth", "refactor"])
        await checkpoint(ctx, "No tags")  # No tags at all

        # Filter for auth-related (should match 2)
        auth_results = await recall(ctx, output_format="json", tags=["auth"], limit=10)
        assert len(auth_results) == 2, f"Should get 2 results with 'auth' tag, got {len(auth_results)}"
        for result in auth_results:
            assert "auth" in result.get("tags", [])

        # Filter for ANY of multiple tags (should match 3)
        multi_results = await recall(ctx, output_format="json", tags=["auth", "database"], limit=10)
        assert len(multi_results) == 3, f"Should get 3 results with 'auth' OR 'database' tag, got {len(multi_results)}"


@pytest.mark.asyncio
async def test_recall_filters_by_since_date(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall respects 'since' date filter."""
    from miller.tools.recall import recall

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
    results = await recall(ctx, output_format="json", since=since_date, limit=10)

    assert len(results) == 2, f"Should get 2 results, got {len(results)}"

    # Verify all results are >= yesterday (strip microseconds for comparison)
    for result in results:
        result_date = datetime.fromtimestamp(result["timestamp"])
        assert result_date >= yesterday.replace(microsecond=0)


@pytest.mark.asyncio
async def test_recall_filters_by_until_date(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall respects 'until' date filter."""
    from miller.tools.recall import recall

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
    results = await recall(ctx, output_format="json", until=until_date, limit=10)

    assert len(results) == 2, f"Should get 2 results, got {len(results)}"

    # Verify all results are <= yesterday
    for result in results:
        result_date = datetime.fromtimestamp(result["timestamp"])
        assert result_date <= yesterday.replace(hour=23, minute=59, second=59)


@pytest.mark.asyncio
async def test_recall_respects_limit(temp_memories_dir, mock_git_context, mock_context):
    """Verify recall returns at most 'limit' results."""
    from miller.tools.checkpoint import checkpoint
    from miller.tools.recall import recall
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 20 checkpoints (only create 12 to speed up test, still tests limit)
        for i in range(12):
            await checkpoint(ctx, f"Checkpoint {i}")
            if i < 11:
                await asyncio.sleep(1.1)  # Ensure different timestamps

        # Recall with limit=10
        results = await recall(ctx, output_format="json", limit=10)

        assert len(results) == 10, f"Should return 10 results, got {len(results)}"

        # Verify they're the most recent 10
        # (Since we created 0-11, most recent should be 11, 10, ..., 2)
        descriptions = [r["description"] for r in results]
        assert "Checkpoint 11" in descriptions[0]
        assert "Checkpoint 2" in descriptions[-1]


@pytest.mark.asyncio
async def test_recall_reads_julie_checkpoints(temp_memories_dir, mock_context):
    """Verify recall can read actual Julie checkpoint files."""
    from miller.tools.recall import recall

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
    results = await recall(ctx, output_format="json", limit=10)

    assert len(results) == 1
    assert results[0]["id"] == "checkpoint_691cb498_2fc504"
    assert results[0]["description"] == "Test Julie compatibility"
    assert results[0]["tags"] == ["julie", "compatibility"]


@pytest.mark.asyncio
async def test_recall_handles_empty_memories(temp_memories_dir, mock_context):
    """Verify recall returns empty list when no checkpoints exist."""
    from miller.tools.recall import recall
    ctx = mock_context
    results = await recall(ctx, output_format="json", limit=10)

    assert results == []
    assert isinstance(results, list)


# ============================================================================
# Text Format Tests
# ============================================================================


class TestRecallTextFormat:
    """Tests for recall text output format."""

    @pytest.mark.asyncio
    async def test_text_format_returns_string(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should return a string, not a list."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Test checkpoint")

            result = await recall(mock_context, output_format="text", limit=10)

            assert isinstance(result, str)
            assert "1 memory found" in result

    @pytest.mark.asyncio
    async def test_text_format_contains_description(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should include checkpoint descriptions."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Fixed authentication bug in login flow")

            result = await recall(mock_context, output_format="text", limit=10)

            assert "Fixed authentication bug in login flow" in result

    @pytest.mark.asyncio
    async def test_text_format_shows_type_icons(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should show icons for different memory types."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Regular checkpoint", type="checkpoint")
            await checkpoint(mock_context, "Important decision", type="decision")
            await checkpoint(mock_context, "Learned something", type="learning")

            result = await recall(mock_context, output_format="text", limit=10)

            # Check icons appear
            assert "✓" in result  # checkpoint
            assert "🎯" in result  # decision
            assert "💡" in result  # learning

    @pytest.mark.asyncio
    async def test_text_format_shows_branch(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should show git branch."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Test checkpoint")

            result = await recall(mock_context, output_format="text", limit=10)

            # mock_git_context has branch "main"
            assert "[main]" in result

    @pytest.mark.asyncio
    async def test_text_format_shows_tags(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should show tags when present."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Tagged checkpoint", tags=["bugfix", "auth"])

            result = await recall(mock_context, output_format="text", limit=10)

            assert "Tags:" in result
            assert "bugfix" in result
            assert "auth" in result

    @pytest.mark.asyncio
    async def test_text_format_shows_relative_time(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should show relative time (e.g., '2 min ago')."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Recent checkpoint")

            result = await recall(mock_context, output_format="text", limit=10)

            # Should show some relative time indicator
            assert "ago" in result or "just now" in result

    @pytest.mark.asyncio
    async def test_text_format_empty_shows_message(self, temp_memories_dir, mock_context):
        """Empty results should show a friendly message, not empty string."""
        from miller.tools.recall import recall

        result = await recall(mock_context, output_format="text", limit=10)

        assert isinstance(result, str)
        assert "No memories found" in result

    @pytest.mark.asyncio
    async def test_text_format_plural_memories(self, temp_memories_dir, mock_git_context, mock_context):
        """Text format should correctly pluralize 'memory/memories'."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "First checkpoint")
            await asyncio.sleep(1.1)
            await checkpoint(mock_context, "Second checkpoint")

            result = await recall(mock_context, output_format="text", limit=10)

            assert "2 memories found" in result

    @pytest.mark.asyncio
    async def test_text_format_default(self, temp_memories_dir, mock_git_context, mock_context):
        """Default output format should be text."""
        from miller.tools.checkpoint import checkpoint
        from miller.tools.recall import recall

        with patch('miller.tools.checkpoint.get_git_context', return_value=mock_git_context):
            await checkpoint(mock_context, "Test checkpoint")

            # Call without specifying output_format
            result = await recall(mock_context, limit=10)

            # Should be text (string), not JSON (list)
            assert isinstance(result, str)
            assert "memory found" in result
