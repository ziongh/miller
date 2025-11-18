"""
MCP tools for checkpoint, recall, and plan management.

These tools provide Julie-compatible development memory system:
- checkpoint: Create immutable development memories
- recall: Retrieve development memories with filtering
- plan: Manage mutable development plans
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastmcp import Context

from miller.memory_utils import (
    generate_checkpoint_id,
    get_checkpoint_path,
    get_git_context,
    slugify_title,
    normalize_tags,
    write_json_file,
    read_json_file
)


async def checkpoint(
    ctx: Context,
    description: str,
    tags: Optional[List[str]] = None,
    type: str = "checkpoint"
) -> str:
    """
    Create immutable development memory checkpoint.

    Args:
        ctx: FastMCP context
        description: Description of what was accomplished or learned
        tags: Optional tags for categorization
        type: Memory type (checkpoint, decision, learning, observation)

    Returns:
        Checkpoint ID (e.g., "checkpoint_691cb498_2fc504")

    Example:
        >>> checkpoint_id = await checkpoint(
        ...     ctx,
        ...     "Fixed authentication bug",
        ...     tags=["bug", "auth"]
        ... )
    """
    # Generate checkpoint ID and timestamp
    checkpoint_id = generate_checkpoint_id(type)
    timestamp = int(time.time())

    # Get git context
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
        "tags": normalized_tags
    }

    # Write checkpoint file
    checkpoint_path = get_checkpoint_path(timestamp)
    write_json_file(checkpoint_path, checkpoint_data)

    return checkpoint_id


async def recall(
    ctx: Context,
    type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Retrieve development memory checkpoints with filtering.

    Args:
        ctx: FastMCP context
        type: Filter by memory type (checkpoint, decision, learning, observation)
        since: Return memories since this date (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        until: Return memories until this date (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
        limit: Maximum number of results to return

    Returns:
        List of checkpoint dictionaries, sorted by timestamp descending (newest first)

    Example:
        >>> memories = await recall(ctx, type="decision", limit=5)
        >>> for memory in memories:
        ...     print(f"{memory['description']}")
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
        if not date_dir.name.count("-") == 2:
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


async def plan(
    ctx: Context,
    action: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    id: Optional[str] = None,
    status: Optional[str] = None,
    activate: bool = True
) -> Any:
    """
    Manage mutable development plans.

    Actions:
        - save: Create new plan
        - get: Retrieve specific plan by ID
        - list: See all plans (optionally filter by status)
        - activate: Set as active plan (deactivates all others)
        - update: Modify existing plan (content, status, etc.)
        - complete: Mark plan as done

    Args:
        ctx: FastMCP context
        action: Action to perform (save, get, list, activate, update, complete)
        title: Plan title (required for save)
        content: Plan content in markdown (optional for save/update)
        id: Plan ID (required for get, update, activate, complete)
        status: Plan status (optional for update)
        activate: Activate after saving (optional for save, defaults to True)

    Returns:
        Depends on action:
        - save: Plan dict with ID
        - get: Plan dict
        - list: List of plan dicts
        - activate: Success message
        - update: Updated plan dict
        - complete: Completed plan dict

    Examples:
        >>> # Create plan
        >>> plan_result = await plan(
        ...     ctx,
        ...     action="save",
        ...     title="Add Search",
        ...     content="## Goal\\nImplement search..."
        ... )
        >>> # Get plan
        >>> my_plan = await plan(ctx, action="get", id=plan_result["id"])
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
            "git": get_git_context()
        }

        # Deactivate other plans if activating this one
        if activate:
            await _deactivate_all_plans(plans_dir)

        # Write plan file
        plan_file = plans_dir / f"{plan_id}.json"
        write_json_file(plan_file, plan_data)

        return plan_data

    elif action == "get":
        if not id:
            raise ValueError("id is required for get action")

        plan_file = plans_dir / f"{id}.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Plan {id} not found")

        return read_json_file(plan_file)

    elif action == "list":
        all_plans = []

        for plan_file in plans_dir.glob("plan_*.json"):
            try:
                plan_data = read_json_file(plan_file)

                # Filter by status if specified
                if status and plan_data.get("status") != status:
                    continue

                all_plans.append(plan_data)

            except (json.JSONDecodeError, KeyError):
                continue

        # Sort by timestamp descending
        all_plans.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

        return all_plans

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

        return {"status": "success", "message": f"Plan {id} activated"}

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

        return plan_data

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

        return plan_data

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
