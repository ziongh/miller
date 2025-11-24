"""
MCP tool for checkpoint management (immutable development memories).
"""

import time
from typing import Optional

from fastmcp import Context

from miller.memory_utils import (
    generate_checkpoint_id,
    get_checkpoint_path,
    get_git_context,
    normalize_tags,
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
