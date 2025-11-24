"""
MCP tools for checkpoint, recall, and plan management.

These tools provide Julie-compatible development memory system:
- checkpoint: Create immutable development memories
- recall: Retrieve development memories with filtering
- plan: Manage mutable development plans
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastmcp import Context

from miller.memory_utils import (
    generate_checkpoint_id,
    get_checkpoint_path,
    get_git_context,
    normalize_tags,
    read_json_file,
    slugify_title,
    write_json_file,
)


async def checkpoint(
    _ctx: Context, description: str, tags: Optional[list[str]] = None, type: str = "checkpoint"
) -> str:
    """
    Create immutable development memory checkpoint.

    USE THIS PROACTIVELY! Your memory persists across sessions. When you discover
    something important, make a decision, or learn something new - checkpoint it!

    Future you (or another agent) will thank you for leaving breadcrumbs.

    IMPORTANT: Don't wait to be asked - checkpoint important findings, decisions,
    and learnings as you go. This builds a knowledge base that makes future work faster.

    Checkpoints are stored in `.memories/YYYY-MM-DD/` (UTC timezone) with
    automatic git context capture (branch, commit, dirty status, changed files).

    Args:
        ctx: FastMCP context
        description: What was accomplished or learned (1-3 sentences)
        tags: Optional tags for categorization (lowercase, hyphenated)
        type: Memory type - "checkpoint", "decision", "learning", or "observation"

    Returns:
        Checkpoint ID (format: {type}_{8hex}_{6hex})

    When to Checkpoint:
        - After fixing a tricky bug → type="checkpoint"
        - When making an architectural choice → type="decision"
        - When discovering how something works → type="learning"
        - When noticing something important → type="observation"

    Examples:
        # After fixing something
        >>> id = await checkpoint(ctx, "Fixed authentication bug - was missing await on token validation")

        # After making a decision
        >>> id = await checkpoint(
        ...     ctx,
        ...     "Decided to use PostgreSQL over MongoDB for better transactions",
        ...     tags=["architecture", "database"],
        ...     type="decision"
        ... )

        # After learning something
        >>> id = await checkpoint(
        ...     ctx,
        ...     "Learned that async context managers need __aenter__ and __aexit__",
        ...     tags=["python", "async"],
        ...     type="learning"
        ... )
    """
    # Generate checkpoint ID and timestamp
    checkpoint_id = generate_checkpoint_id(type)
    timestamp = int(time.time())

    # Get git context (fast now with stdin=DEVNULL fix)
    git_context = get_git_context()

    # Normalize tags
    normalized_tags = normalize_tags(tags) if tags else []

    # Create checkpoint data
    checkpoint_data = {
        "id": checkpoint_id,
        "timestamp": timestamp,
        "type": type,
        "git": git_context,
        "description": description,
        "tags": normalized_tags,
    }

    # Write checkpoint file
    checkpoint_path = get_checkpoint_path(timestamp)
    write_json_file(checkpoint_path, checkpoint_data)

    return checkpoint_id


async def recall(
    _ctx: Context,
    query: Optional[str] = None,
    type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 10,
    output_format: str = "text",
) -> str | list[dict[str, Any]]:
    """
    Retrieve development memory checkpoints with filtering and semantic search.

    USE THIS WHEN RESUMING WORK OR INVESTIGATING PAST DECISIONS!

    Your checkpoints persist across sessions. When you're working on something related
    to past work, recall what you (or previous agents) learned. Don't reinvent the wheel!

    Two modes:
    1. Time-based (fast filesystem scan): When no query provided
    2. Semantic search (indexed): When query provided - uses hybrid text+semantic search

    Args:
        ctx: FastMCP context
        query: Optional natural language search query (enables semantic search mode)
               Example: "authentication bug", "PostgreSQL decision", "indexing performance"
        type: Filter by memory type ("checkpoint", "decision", "learning", "observation")
        since: Memories since this date (ISO 8601: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS")
               Uses local timezone - automatically converted to UTC for filtering
        until: Memories until this date (ISO 8601, same format as since)
        limit: Maximum number of results (default: 10)
        output_format: "text" (default, lean) or "json" (structured)

    Returns:
        - text mode: Formatted summary of memories (default)
        - json mode: List of checkpoint dictionaries with keys:
        - id: Checkpoint ID
        - timestamp: Unix timestamp (seconds)
        - type: Memory type
        - description: Memory description
        - tags: List of tags
        - git: Dict with branch, commit, dirty, files_changed

    When to Recall:
        - Starting work on a feature → recall related past work
        - Debugging a bug → recall past fixes in the area
        - Making a decision → recall past architectural decisions
        - Onboarding to unfamiliar code → recall learnings about it

    Examples:
        # What did we do recently?
        >>> memories = await recall(ctx)  # Last 10 memories

        # What decisions did we make?
        >>> decisions = await recall(ctx, type="decision", limit=20)

        # Semantic search - find related work
        >>> auth_bugs = await recall(ctx, query="authentication bug we fixed")
        >>> db_choices = await recall(ctx, query="why PostgreSQL", type="decision")

    The memories are complete and accurate - trust them! Past decisions and learnings
    are valuable context for current work.
    """
    # SEMANTIC SEARCH MODE: Use indexed embeddings for natural language queries
    if query:
        results = await _recall_semantic(query, type, since, until, limit)
    else:
        # FILESYSTEM SCAN MODE: Fast time-based filtering (original implementation)
        results = await _recall_filesystem(type, since, until, limit)

    # Apply output format
    if output_format == "json":
        return results
    else:
        return _format_recall_as_text(results, query=query)


def _format_recall_as_text(results: list[dict[str, Any]], query: Optional[str] = None) -> str:
    """Format recall results as lean text output.

    Output format:
    ```
    5 memories found:

    ✓ checkpoint_abc123 (2 min ago) [main]
      Fixed authentication bug - was missing await

    🎯 decision_def456 (1 hour ago) [feature-x]
      Decided to use PostgreSQL for transactions
      Tags: architecture, database
    ```
    """
    if not results:
        if query:
            return f'No memories found matching "{query}".'
        return "No memories found."

    # Type icons
    icons = {
        "checkpoint": "✓",
        "decision": "🎯",
        "learning": "💡",
        "observation": "👁️",
    }

    count = len(results)
    header = f'{count} {"memory" if count == 1 else "memories"} found'
    if query:
        header += f' for "{query}"'
    header += ":"

    output = [header, ""]

    now = time.time()
    for mem in results:
        mem_type = mem.get("type", "checkpoint")
        icon = icons.get(mem_type, "•")
        mem_id = mem.get("id", "?")
        description = mem.get("description", "")
        tags = mem.get("tags", [])
        timestamp = mem.get("timestamp", 0)
        git = mem.get("git", {})
        branch = git.get("branch", "?")

        # Relative time
        diff = now - timestamp
        if diff < 60:
            rel_time = "just now"
        elif diff < 3600:
            mins = int(diff / 60)
            rel_time = f"{mins} min ago"
        elif diff < 86400:
            hours = int(diff / 3600)
            rel_time = f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            days = int(diff / 86400)
            rel_time = f"{days} day{'s' if days > 1 else ''} ago"

        # Format: icon id (time) [branch]
        output.append(f"{icon} {mem_id} ({rel_time}) [{branch}]")
        output.append(f"  {description}")

        if tags:
            output.append(f"  Tags: {', '.join(tags)}")

        output.append("")

    # Trim trailing blank line
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)


async def _recall_semantic(
    query: str,
    type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Semantic search over indexed memories using hybrid text+semantic search.

    Flow:
    1. Search vector store with query (get more results for filtering)
    2. Filter to only .memories/ paths
    3. Load actual JSON files
    4. Apply time/type filters
    5. Return top results by relevance score
    """
    # Import server globals for vector_store access
    from miller.server import vector_store

    if vector_store is None:
        # Indexing not complete yet - fall back to filesystem scan
        return await _recall_filesystem(type, since, until, limit)

    # Search with higher limit since we'll filter by path
    # Use hybrid search for best results (combines text + semantic)
    search_results = vector_store.search(query, method="hybrid", limit=limit * 5)

    # Filter to only memory files (.memories/ paths)
    memory_paths = set()
    for result in search_results:
        file_path = result.get("file_path", "")
        if file_path.startswith(".memories/") and file_path.endswith(".json"):
            memory_paths.add(file_path)

    # Parse date filters
    since_timestamp = None
    until_timestamp = None

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            since_timestamp = int(since_dt.timestamp())
        except ValueError:
            pass

    if until:
        try:
            until_dt = datetime.fromisoformat(until)
            if "T" not in until:
                until_dt = until_dt.replace(hour=23, minute=59, second=59)
            until_timestamp = int(until_dt.timestamp())
        except ValueError:
            pass

    # Load JSON files and apply filters
    all_checkpoints = []
    for file_path in memory_paths:
        try:
            full_path = Path(file_path)
            if not full_path.exists():
                continue

            data = read_json_file(full_path)

            # Apply type filter
            if type and data.get("type") != type:
                continue

            # Apply time filters
            checkpoint_timestamp = data.get("timestamp", 0)

            if since_timestamp and checkpoint_timestamp < since_timestamp:
                continue

            if until_timestamp and checkpoint_timestamp > until_timestamp:
                continue

            all_checkpoints.append(data)

        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by timestamp descending (most recent first)
    all_checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # Apply limit
    return all_checkpoints[:limit]


async def _recall_filesystem(
    type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Fast filesystem scan for time-based memory retrieval (original implementation).

    Used when no semantic query is provided - optimized for chronological filtering.
    """
    memories_dir = Path(".memories")

    # Return empty list if .memories doesn't exist
    if not memories_dir.exists():
        return []

    # Parse date filters
    since_timestamp = None
    until_timestamp = None

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            since_timestamp = int(since_dt.timestamp())
        except ValueError:
            pass  # Ignore invalid date format

    if until:
        try:
            until_dt = datetime.fromisoformat(until)
            # Set to end of day if only date provided
            if "T" not in until:
                until_dt = until_dt.replace(hour=23, minute=59, second=59)
            until_timestamp = int(until_dt.timestamp())
        except ValueError:
            pass  # Ignore invalid date format

    # Scan all date directories
    all_checkpoints = []

    for date_dir in sorted(memories_dir.glob("*/"), reverse=True):
        # Skip if not a date directory (YYYY-MM-DD format)
        if date_dir.name.count("-") != 2:
            continue

        # Scan JSON files in this directory
        for checkpoint_file in date_dir.glob("*.json"):
            try:
                data = read_json_file(checkpoint_file)

                # Apply filters
                if type and data.get("type") != type:
                    continue

                checkpoint_timestamp = data.get("timestamp", 0)

                if since_timestamp and checkpoint_timestamp < since_timestamp:
                    continue

                if until_timestamp and checkpoint_timestamp > until_timestamp:
                    continue

                all_checkpoints.append(data)

            except (json.JSONDecodeError, KeyError):
                # Skip invalid JSON files
                continue

    # Sort by timestamp descending (most recent first)
    all_checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # Apply limit
    return all_checkpoints[:limit]


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


def _count_tasks(content: str) -> tuple[int, int]:
    """Count total tasks and completed tasks in markdown content.

    Looks for markdown checkbox patterns: - [ ] and - [x]

    Returns:
        Tuple of (total_count, completed_count)
    """
    import re
    if not content:
        return 0, 0

    # Match markdown checkboxes: - [ ] or - [x] or - [X]
    unchecked = len(re.findall(r'- \[ \]', content))
    checked = len(re.findall(r'- \[[xX]\]', content))

    return unchecked + checked, checked


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

        # Create plan data
        plan_data = {
            "id": plan_id,
            "timestamp": int(time.time()),
            "type": "plan",
            "title": title,
            "status": "active" if activate else "pending",
            "content": content or "",
            "git": get_git_context(),
        }

        # Deactivate other plans if activating this one
        if activate:
            await _deactivate_all_plans(plans_dir)

        # Write plan file
        plan_file = plans_dir / f"{plan_id}.json"
        write_json_file(plan_file, plan_data)

        # Return based on output_format
        if output_format == "json":
            return plan_data
        return f"✓ Created plan '{title}' ({plan_id})"

    elif action == "get":
        if not id:
            raise ValueError("id is required for get action")

        plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        plan_data = read_json_file(plan_file)
        if output_format == "json":
            return plan_data
        return _format_plan_as_text(plan_data)

    elif action == "list":
        all_plans = []

        for plan_file in plans_dir.glob("plan_*.json"):
            try:
                plan_data = read_json_file(plan_file)

                # Filter by status if specified
                if status and plan_data.get("status") != status:
                    continue

                # Calculate task counts from content
                plan_content = plan_data.get("content", "")
                task_count, completed_count = _count_tasks(plan_content)

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

            except (json.JSONDecodeError, KeyError):
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

        # Activate this plan
        plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        plan_data = read_json_file(plan_file)
        plan_data["status"] = "active"
        write_json_file(plan_file, plan_data)

        if output_format == "json":
            return {"status": "success", "message": f"Plan {id} activated", "id": id}
        return f"✓ Plan '{plan_data.get('title', id)}' activated"

    elif action == "update":
        if not id:
            raise ValueError("id is required for update action")

        plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        plan_data = read_json_file(plan_file)

        # Update fields
        if content is not None:
            plan_data["content"] = content
        if status is not None:
            plan_data["status"] = status

        write_json_file(plan_file, plan_data)

        task_count, completed_count = _count_tasks(plan_data.get("content", ""))
        if output_format == "json":
            return {
                "id": plan_data.get("id"),
                "title": plan_data.get("title"),
                "status": plan_data.get("status"),
                "task_count": task_count,
                "completed_count": completed_count,
                "message": "Plan updated successfully",
            }
        title = plan_data.get("title", id)
        progress = f"[{completed_count}/{task_count}]" if task_count > 0 else ""
        return f"✓ Updated '{title}' {progress}"

    elif action == "complete":
        if not id:
            raise ValueError("id is required for complete action")

        plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        plan_data = read_json_file(plan_file)
        plan_data["status"] = "completed"
        plan_data["completed_at"] = int(time.time())
        write_json_file(plan_file, plan_data)

        task_count, completed_count = _count_tasks(plan_data.get("content", ""))
        if output_format == "json":
            return {
                "id": plan_data.get("id"),
                "title": plan_data.get("title"),
                "status": "completed",
                "completed_at": plan_data["completed_at"],
                "task_count": task_count,
                "completed_count": completed_count,
                "message": "Plan completed! 🎉",
            }
        title = plan_data.get("title", id)
        progress = f"[{completed_count}/{task_count}]" if task_count > 0 else ""
        return f"🎉 Completed '{title}' {progress}"

    else:
        raise ValueError(f"Unknown action: {action}")


async def _deactivate_all_plans(plans_dir: Path) -> None:
    """
    Helper to deactivate all plans (enforces single active plan).

    Args:
        plans_dir: Path to plans directory
    """
    for plan_file in plans_dir.glob("plan_*.json"):
        try:
            plan_data = read_json_file(plan_file)

            if plan_data.get("status") == "active":
                plan_data["status"] = "pending"
                write_json_file(plan_file, plan_data)

        except (json.JSONDecodeError, KeyError):
            continue
