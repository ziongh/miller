"""
MCP tool for plan management (mutable development plans).
"""

import re
import time
from pathlib import Path
from typing import Any, Optional

from fastmcp import Context

from miller.memory_utils import (
    get_git_context,
    read_memory_file,
    slugify_title,
    write_memory_file,
)


async def plan(
    _ctx: Context,
    action: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    id: Optional[str] = None,
    status: Optional[str] = None,
    activate: bool = True,
    include_content: bool = False,
    output_format: str = "text",
) -> Any:
    """
    Manage mutable development plans.

    USE THIS TO TRACK COMPLEX TASKS! Plans help you stay organized and provide
    context when resuming work. Only one plan can be active at a time - this
    keeps you focused.

    Plans are stored in `.memories/plans/` and persist across sessions.

    Actions:
        - save: Create new plan (start a new task)
        - get: Retrieve specific plan by ID
        - list: See all plans (check what's in progress)
        - activate: Set as active plan (switch focus)
        - update: Modify existing plan (track progress)
        - complete: Mark plan as done (celebrate!)

    Args:
        ctx: FastMCP context
        action: Action to perform (save|get|list|activate|update|complete)
        title: Plan title (required for save) - converted to slug for ID
        content: Plan content in markdown (optional for save/update)
        id: Plan ID (required for get/update/activate/complete)
        status: Plan status (optional for update/list filter) - "active"|"pending"|"completed"
        activate: Auto-activate after save (default: True, enforces single-active)
        include_content: Include full content in list (default: False for token efficiency)
        output_format: "text" (default, lean) or "json" (structured)

    Returns:
        - text mode (default): Lean confirmation messages
        - json mode: Structured dicts/lists for programmatic use

    Task Counting:
        The `task_count` and `completed_count` fields in list results are calculated
        from markdown checkboxes in the plan content:
        - Unchecked: `- [ ]` (counts toward task_count)
        - Checked: `- [x]` or `- [X]` (counts toward both task_count and completed_count)

        Use standard markdown task syntax for accurate counting. Other formats like
        emoji checkmarks (✅) are not counted as they represent outcomes/criteria,
        not actionable tasks.

    Workflow:
        1. plan(action="save", title="Feature X") → Start tracking
        2. Work on the feature, update plan as you go
        3. plan(action="update", id="...", content="## Progress\\n...") → Track progress
        4. plan(action="complete", id="...") → Mark done when finished

    Examples:
        # Start a new task
        >>> plan_result = await plan(
        ...     ctx,
        ...     action="save",
        ...     title="Add Search Feature",
        ...     content="## Goal\\nImplement full-text search\\n\\n## Tasks\\n- [ ] FTS index\\n- [ ] UI"
        ... )

        # Check what's active
        >>> active_plans = await plan(ctx, action="list", status="active")

        # Update progress
        >>> updated = await plan(
        ...     ctx,
        ...     action="update",
        ...     id="plan_add-search-feature",
        ...     content="## Goal\\n...\\n\\n## Done\\n- [x] FTS index\\n\\n## Remaining\\n- [ ] UI"
        ... )

        # Mark complete when done
        >>> completed = await plan(ctx, action="complete", id="plan_add-search-feature")

    Note: Single-active enforcement means activating a new plan deactivates others.
    This keeps you focused on one task at a time.
    """
    plans_dir = Path(".memories/plans")

    if action == "save":
        # Validate required fields
        if not title:
            raise ValueError("title is required for save action")

        # Generate plan ID from title
        slug = slugify_title(title)
        plan_id = f"plan_{slug}"

        # Create plan metadata (frontmatter)
        metadata = {
            "id": plan_id,
            "timestamp": int(time.time()),
            "type": "plan",
            "title": title,
            "status": "active" if activate else "pending",
            "git": get_git_context(),
        }

        # Deactivate other plans if activating this one
        if activate:
            await _deactivate_all_plans(plans_dir)

        # Write plan file as markdown with frontmatter
        plan_file = plans_dir / f"{plan_id}.md"
        write_memory_file(plan_file, metadata, content or "")

        # Return based on output_format
        if output_format == "json":
            # OPTIMIZATION: Return lean confirmation instead of full plan_data
            return {
                "id": plan_id,
                "title": title,
                "status": metadata["status"],
                "message": "Plan created successfully",
            }
        return f"✓ Created plan '{title}' ({plan_id})"

    elif action == "get":
        if not id:
            raise ValueError("id is required for get action")

        # Try .md first, fall back to legacy .json
        plan_file = plans_dir / f"{id}.md"
        if not plan_file.exists():
            plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        metadata, content = read_memory_file(plan_file)
        plan_data = {**metadata, "content": content}
        if output_format == "json":
            return plan_data
        return _format_plan_as_text(plan_data)

    elif action == "list":
        all_plans = []

        # Scan both .md and legacy .json files
        plan_files = list(plans_dir.glob("plan_*.md")) + list(plans_dir.glob("plan_*.json"))
        for plan_file in plan_files:
            try:
                metadata, content = read_memory_file(plan_file)
                plan_data = {**metadata, "content": content}

                # Filter by status if specified
                if status and plan_data.get("status") != status:
                    continue

                # Calculate task counts from content
                task_count, completed_count = _count_tasks(content)

                if include_content:
                    # Full mode: include everything plus task counts
                    plan_data["task_count"] = task_count
                    plan_data["completed_count"] = completed_count
                    all_plans.append(plan_data)
                else:
                    # Summary mode (default): exclude content and git for token efficiency
                    summary = {
                        "id": plan_data.get("id"),
                        "title": plan_data.get("title"),
                        "status": plan_data.get("status"),
                        "timestamp": plan_data.get("timestamp"),
                        "task_count": task_count,
                        "completed_count": completed_count,
                    }
                    all_plans.append(summary)

            except (ValueError, KeyError):
                continue

        # Sort by timestamp descending
        all_plans.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        if output_format == "json":
            return all_plans
        return _format_plan_list_as_text(all_plans)

    elif action == "activate":
        if not id:
            raise ValueError("id is required for activate action")

        # Deactivate all plans
        await _deactivate_all_plans(plans_dir)

        # Activate this plan - try .md first, fall back to legacy .json
        plan_file = plans_dir / f"{id}.md"
        if not plan_file.exists():
            plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        metadata, content = read_memory_file(plan_file)
        metadata["status"] = "active"
        _write_plan_file(plan_file, metadata, content)

        if output_format == "json":
            return {"status": "success", "message": f"Plan {id} activated", "id": id}
        return f"✓ Plan '{metadata.get('title', id)}' activated"

    elif action == "update":
        if not id:
            raise ValueError("id is required for update action")

        # Try .md first, fall back to legacy .json
        plan_file = plans_dir / f"{id}.md"
        if not plan_file.exists():
            plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        metadata, existing_content = read_memory_file(plan_file)

        # Update fields
        new_content = content if content is not None else existing_content
        if status is not None:
            metadata["status"] = status

        _write_plan_file(plan_file, metadata, new_content)

        task_count, completed_count = _count_tasks(new_content)
        if output_format == "json":
            return {
                "id": metadata.get("id"),
                "title": metadata.get("title"),
                "status": metadata.get("status"),
                "task_count": task_count,
                "completed_count": completed_count,
                "message": "Plan updated successfully",
            }
        title = metadata.get("title", id)
        progress = f"[{completed_count}/{task_count}]" if task_count > 0 else ""
        return f"✓ Updated '{title}' {progress}"

    elif action == "complete":
        if not id:
            raise ValueError("id is required for complete action")

        # Try .md first, fall back to legacy .json
        plan_file = plans_dir / f"{id}.md"
        if not plan_file.exists():
            plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        metadata, content = read_memory_file(plan_file)
        metadata["status"] = "completed"
        metadata["completed_at"] = int(time.time())
        _write_plan_file(plan_file, metadata, content)

        task_count, completed_count = _count_tasks(content)
        if output_format == "json":
            return {
                "id": metadata.get("id"),
                "title": metadata.get("title"),
                "status": "completed",
                "completed_at": metadata["completed_at"],
                "task_count": task_count,
                "completed_count": completed_count,
                "message": "Plan completed! 🎉",
            }
        title = metadata.get("title", id)
        progress = f"[{completed_count}/{task_count}]" if task_count > 0 else ""
        return f"🎉 Completed '{title}' {progress}"

    else:
        raise ValueError(f"Unknown action: {action}")


def _format_plan_as_text(plan_data: dict[str, Any]) -> str:
    """Format a single plan as readable text with content.

    Output format:
    ```
    Plan: Add Search Feature (plan_add-search-feature)
    Status: active
    Progress: [2/5] tasks

    ## Content
    [plan markdown content]
    ```
    """
    plan_id = plan_data.get("id", "?")
    title = plan_data.get("title", "Untitled")
    status = plan_data.get("status", "pending")
    content = plan_data.get("content", "")

    task_count, completed_count = _count_tasks(content)
    progress = f"[{completed_count}/{task_count}] tasks" if task_count > 0 else "No tasks"

    output = [
        f"Plan: {title} ({plan_id})",
        f"Status: {status}",
        f"Progress: {progress}",
        "",
    ]

    if content:
        output.append(content)

    return "\n".join(output)


def _format_plan_list_as_text(plans: list[dict[str, Any]]) -> str:
    """Format plan list as lean text output.

    Output format:
    ```
    3 plans:

    ● [active] Add Search Feature [2/5]
      plan_add-search-feature

    ○ [pending] Fix Authentication [0/3]
      plan_fix-auth

    ✓ [completed] Database Migration [5/5]
      plan_db-migration
    ```
    """
    if not plans:
        return "No plans found."

    count = len(plans)
    output = [f'{count} {"plan" if count == 1 else "plans"}:', ""]

    # Status icons
    icons = {
        "active": "●",
        "pending": "○",
        "completed": "✓",
    }

    for plan in plans:
        plan_id = plan.get("id", "?")
        title = plan.get("title", "Untitled")
        status = plan.get("status", "pending")
        task_count = plan.get("task_count", 0)
        completed_count = plan.get("completed_count", 0)

        icon = icons.get(status, "○")
        progress = f"[{completed_count}/{task_count}]" if task_count > 0 else ""

        output.append(f"{icon} [{status}] {title} {progress}")
        output.append(f"  {plan_id}")
        output.append("")

    # Trim trailing blank line
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


def _write_plan_file(plan_file: Path, metadata: dict[str, Any], content: str) -> Path:
    """
    Write plan file, converting legacy .json to .md format.

    If plan_file is a .json file, writes to .md instead and removes the old .json.
    This ensures automatic migration from JSON to Markdown format.

    Args:
        plan_file: Original plan file path (may be .json or .md)
        metadata: Plan metadata (frontmatter)
        content: Plan content (markdown)

    Returns:
        Path to the written file (always .md)
    """
    # Convert .json to .md if needed
    if plan_file.suffix == ".json":
        md_file = plan_file.with_suffix(".md")
        write_memory_file(md_file, metadata, content)
        # Remove old JSON file after successful write
        if plan_file.exists():
            plan_file.unlink()
        return md_file
    else:
        write_memory_file(plan_file, metadata, content)
        return plan_file


def _count_tasks(content: str) -> tuple[int, int]:
    """Count total tasks and completed tasks in markdown content.

    Looks for markdown checkbox patterns: - [ ] and - [x]

    Returns:
        Tuple of (total_count, completed_count)
    """
    if not content:
        return 0, 0

    # Match markdown checkboxes: - [ ] or - [x] or - [X]
    unchecked = len(re.findall(r'- \[ \]', content))
    checked = len(re.findall(r'- \[[xX]\]', content))

    return unchecked + checked, checked


async def _deactivate_all_plans(plans_dir: Path) -> None:
    """
    Helper to deactivate all plans (enforces single active plan).

    Args:
        plans_dir: Path to plans directory
    """
    # Scan both .md and legacy .json files
    plan_files = list(plans_dir.glob("plan_*.md")) + list(plans_dir.glob("plan_*.json"))
    for plan_file in plan_files:
        try:
            metadata, content = read_memory_file(plan_file)

            if metadata.get("status") == "active":
                metadata["status"] = "pending"
                _write_plan_file(plan_file, metadata, content)

        except (ValueError, KeyError):
            continue
