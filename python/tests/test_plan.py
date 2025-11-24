"""
Tests for plan MCP tool (mutable development plan tracking).

TDD Phase 1: Write ALL tests first (expect them to fail - RED).
These tests define the contract for Julie-compatible plan functionality.
"""

import pytest
import json
import shutil
from pathlib import Path
from unittest.mock import patch


# ============================================================================
# Plan Tool Tests (9 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_plan_save_creates_file(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan save creates file in .memories/plans/plan_{slug}.json."""
    from miller.tools.plan import plan
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
    from miller.tools.plan import plan

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
    from miller.tools.plan import plan
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
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 3 plans
        await plan(ctx, action="save", title="Plan 1", content="Content 1", activate=False)
        await plan(ctx, action="save", title="Plan 2", content="Content 2", activate=False)
        await plan(ctx, action="save", title="Plan 3", content="Content 3", activate=False)

        # List all plans (use json format for structured data in tests)
        results = await plan(ctx, action="list", output_format="json")

        assert len(results) == 3
        titles = [p["title"] for p in results]
        assert "Plan 1" in titles
        assert "Plan 2" in titles
        assert "Plan 3" in titles


@pytest.mark.asyncio
async def test_plan_list_filters_by_status(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list filters by status correctly."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plans with different statuses (use json for structured returns)
        plan1_id = await plan(ctx, action="save", title="Active Plan 1", content="C1", output_format="json")
        plan2_id = await plan(ctx, action="save", title="Active Plan 2", content="C2", output_format="json")
        plan3_id = await plan(ctx, action="save", title="Complete Plan", content="C3", activate=False, output_format="json")

        # Complete one plan
        await plan(ctx, action="complete", id=plan3_id["id"])

        # List only active plans
        active_plans = await plan(ctx, action="list", status="active", output_format="json")

        # Should have 2 active plans (plan2 is active, plan1 was deactivated when plan2 was created)
        active_titles = [p["title"] for p in active_plans]
        assert len([p for p in active_plans if p["status"] == "active"]) >= 1

        # List completed plans
        completed_plans = await plan(ctx, action="list", status="completed", output_format="json")
        assert len(completed_plans) == 1
        assert completed_plans[0]["title"] == "Complete Plan"


@pytest.mark.asyncio
async def test_plan_activate_deactivates_others(temp_memories_dir, mock_git_context, mock_context):
    """Verify activating a plan deactivates all others (single active plan)."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create 3 plans (use json for structured returns)
        plan1_result = await plan(ctx, action="save", title="Plan 1", content="C1", output_format="json")
        plan2_result = await plan(ctx, action="save", title="Plan 2", content="C2", output_format="json")
        plan3_result = await plan(ctx, action="save", title="Plan 3", content="C3", output_format="json")

        # Activate plan 1
        await plan(ctx, action="activate", id=plan1_result["id"])

        # List all plans and check statuses
        all_plans = await plan(ctx, action="list", output_format="json")

        active_count = sum(1 for p in all_plans if p["status"] == "active")
        assert active_count == 1, "Only one plan should be active"

        # Verify plan 1 is the active one
        active_plan = [p for p in all_plans if p["status"] == "active"][0]
        assert active_plan["title"] == "Plan 1"


@pytest.mark.asyncio
async def test_plan_update_modifies_content(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan update modifies content correctly."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plan (use json for structured returns)
        plan_result = await plan(
            ctx,
            action="save",
            title="Test Plan",
            content="## Original Content",
            output_format="json"
        )

        # Update content
        await plan(
            ctx,
            action="update",
            id=plan_result["id"],
            content="## Updated Content\nNew sections here..."
        )

        # Get plan and verify content changed (use json for structured return)
        updated_plan = await plan(ctx, action="get", id=plan_result["id"], output_format="json")

        assert "Updated Content" in updated_plan["content"]
        assert "Original Content" not in updated_plan["content"]


@pytest.mark.asyncio
async def test_plan_complete_sets_timestamp(temp_memories_dir, mock_git_context, mock_context):
    """Verify completing a plan sets completed_at timestamp."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create plan (use json for structured returns)
        plan_result = await plan(
            ctx,
            action="save",
            title="Test Plan",
            content="## Test",
            output_format="json"
        )

        # Complete it
        await plan(ctx, action="complete", id=plan_result["id"])

        # Get plan and verify completed_at is set (use json for structured return)
        completed_plan = await plan(ctx, action="get", id=plan_result["id"], output_format="json")

        assert completed_plan["status"] == "completed"
        assert "completed_at" in completed_plan
        assert isinstance(completed_plan["completed_at"], int)
        assert completed_plan["completed_at"] > 0


@pytest.mark.asyncio
async def test_plan_get_retrieves_by_id(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan get retrieves correct plan by ID."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create multiple plans (use json for structured returns)
        plan1 = await plan(ctx, action="save", title="Plan 1", content="C1", activate=False, output_format="json")
        plan2 = await plan(ctx, action="save", title="Plan 2", content="C2", activate=False, output_format="json")
        plan3 = await plan(ctx, action="save", title="Plan 3", content="C3", activate=False, output_format="json")

        # Get plan 2 by ID (use json for structured return)
        retrieved = await plan(ctx, action="get", id=plan2["id"], output_format="json")

        assert retrieved["id"] == plan2["id"]
        assert retrieved["title"] == "Plan 2"
        assert retrieved["content"] == "C2"


# ============================================================================
# Plan Summary Mode Tests (Token Efficiency)
# ============================================================================


@pytest.mark.asyncio
async def test_plan_list_excludes_content_by_default(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list excludes content field by default for token efficiency."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create a plan with large content
        large_content = "## Goal\n" + "x" * 5000  # 5KB of content
        await plan(ctx, action="save", title="Big Plan", content=large_content)

        # List plans (default - summary mode, use json for structured data)
        plans = await plan(ctx, action="list", output_format="json")

        assert len(plans) == 1
        # Content should NOT be included by default
        assert "content" not in plans[0]
        # But metadata should be present
        assert "id" in plans[0]
        assert "title" in plans[0]
        assert "status" in plans[0]
        assert "timestamp" in plans[0]


@pytest.mark.asyncio
async def test_plan_list_includes_content_when_requested(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list includes content when include_content=True."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        await plan(ctx, action="save", title="Test Plan", content="Test content here")

        # List with include_content=True (use json for structured data)
        plans = await plan(ctx, action="list", include_content=True, output_format="json")

        assert len(plans) == 1
        # Content SHOULD be included when requested
        assert "content" in plans[0]
        assert plans[0]["content"] == "Test content here"


@pytest.mark.asyncio
async def test_plan_list_includes_task_counts(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list includes task_count and completed_count."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        # Create a plan with tasks in markdown format
        content = """## Goal
Implement feature X

## Tasks
- [ ] Task 1
- [x] Task 2 (done)
- [ ] Task 3
- [x] Task 4 (done)
- [ ] Task 5
"""
        await plan(ctx, action="save", title="Task Plan", content=content)

        # List plans (use json for structured data)
        plans = await plan(ctx, action="list", output_format="json")

        assert len(plans) == 1
        # Should have task counts
        assert "task_count" in plans[0]
        assert "completed_count" in plans[0]
        assert plans[0]["task_count"] == 5
        assert plans[0]["completed_count"] == 2


@pytest.mark.asyncio
async def test_plan_list_summary_excludes_git(temp_memories_dir, mock_git_context, mock_context):
    """Verify plan list summary excludes git field to save tokens."""
    from miller.tools.plan import plan
    with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
        ctx = mock_context

        await plan(ctx, action="save", title="Git Plan", content="Content")

        # List plans (summary mode - default, use json for structured data)
        plans = await plan(ctx, action="list", output_format="json")

        assert len(plans) == 1
        # Git should NOT be included in summary
        assert "git" not in plans[0]

        # But should be included with include_content=True
        plans_full = await plan(ctx, action="list", include_content=True, output_format="json")
        assert "git" in plans_full[0]


# ============================================================================
# Text Format Tests
# ============================================================================


class TestPlanTextFormat:
    """Tests for plan text output format."""

    @pytest.mark.asyncio
    async def test_save_text_format_returns_string(self, temp_memories_dir, mock_git_context, mock_context):
        """Save action with text format should return a string confirmation."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            result = await plan(
                mock_context,
                action="save",
                title="Test Plan",
                content="## Goals\n- Task 1",
                output_format="text"
            )

            assert isinstance(result, str)
            assert "Test Plan" in result

    @pytest.mark.asyncio
    async def test_get_text_format_shows_plan_details(self, temp_memories_dir, mock_git_context, mock_context):
        """Get action with text format should show plan details."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            # Create a plan first
            result = await plan(
                mock_context,
                action="save",
                title="Feature Plan",
                content="## Goals\nBuild the feature\n\n## Tasks\n- [ ] Task 1\n- [x] Task 2",
                output_format="json"
            )

            # Get with text format
            text_result = await plan(
                mock_context,
                action="get",
                id=result["id"],
                output_format="text"
            )

            assert isinstance(text_result, str)
            assert "Feature Plan" in text_result
            assert "active" in text_result.lower()

    @pytest.mark.asyncio
    async def test_list_text_format_shows_all_plans(self, temp_memories_dir, mock_git_context, mock_context):
        """List action with text format should show all plans."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            # Create multiple plans
            await plan(mock_context, action="save", title="Plan A", content="A", activate=False)
            await plan(mock_context, action="save", title="Plan B", content="B", activate=False)
            await plan(mock_context, action="save", title="Plan C", content="C")

            # List with text format
            result = await plan(mock_context, action="list", output_format="text")

            assert isinstance(result, str)
            assert "3 plans" in result
            assert "Plan A" in result
            assert "Plan B" in result
            assert "Plan C" in result

    @pytest.mark.asyncio
    async def test_list_text_format_shows_status_icons(self, temp_memories_dir, mock_git_context, mock_context):
        """List text format should show status icons."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            # Create active plan
            active_plan = await plan(
                mock_context, action="save", title="Active Plan", content="A", output_format="json"
            )
            # Create pending plan
            await plan(mock_context, action="save", title="Pending Plan", content="P", activate=False)
            # Create completed plan
            completed_plan = await plan(
                mock_context, action="save", title="Done Plan", content="D", activate=False, output_format="json"
            )
            await plan(mock_context, action="complete", id=completed_plan["id"])

            # List with text format
            result = await plan(mock_context, action="list", output_format="text")

            # Should have status indicators
            assert "▶" in result or "●" in result  # active/pending icons
            assert "✓" in result  # completed icon

    @pytest.mark.asyncio
    async def test_list_text_format_shows_task_progress(self, temp_memories_dir, mock_git_context, mock_context):
        """List text format should show task progress (e.g., '2/5 tasks')."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            content = "## Tasks\n- [x] Done 1\n- [x] Done 2\n- [ ] Todo 1\n- [ ] Todo 2\n- [ ] Todo 3"
            await plan(mock_context, action="save", title="Progress Plan", content=content)

            result = await plan(mock_context, action="list", output_format="text")

            assert isinstance(result, str)
            # Should show task progress
            assert "2/5" in result

    @pytest.mark.asyncio
    async def test_list_text_empty_shows_message(self, temp_memories_dir, mock_context):
        """Empty list should show friendly message."""
        from miller.tools.plan import plan

        result = await plan(mock_context, action="list", output_format="text")

        assert isinstance(result, str)
        assert "No plans" in result or "0 plans" in result

    @pytest.mark.asyncio
    async def test_complete_text_format_shows_confirmation(self, temp_memories_dir, mock_git_context, mock_context):
        """Complete action with text format should show confirmation."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            # Create and complete a plan
            created = await plan(
                mock_context, action="save", title="Finish Me", content="Done", output_format="json"
            )
            result = await plan(
                mock_context, action="complete", id=created["id"], output_format="text"
            )

            assert isinstance(result, str)
            assert "Finish Me" in result or "completed" in result.lower()

    @pytest.mark.asyncio
    async def test_text_format_is_default(self, temp_memories_dir, mock_git_context, mock_context):
        """Default output format should be text."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            await plan(mock_context, action="save", title="Default Test", content="Test")

            # Call list without specifying output_format
            result = await plan(mock_context, action="list")

            # Should be text (string), not JSON (list)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_list_text_format_singular_plan(self, temp_memories_dir, mock_git_context, mock_context):
        """List text format should correctly use singular 'plan' for 1 item."""
        from miller.tools.plan import plan

        with patch('miller.memory_utils.get_git_context', return_value=mock_git_context):
            await plan(mock_context, action="save", title="Only Plan", content="Solo")

            result = await plan(mock_context, action="list", output_format="text")

            assert isinstance(result, str)
            assert "1 plan" in result
            assert "1 plans" not in result
