"""
MCP tool for recall management (retrieve development memories).
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastmcp import Context

from miller.memory_utils import read_memory_file


async def recall(
    _ctx: Context,
    query: Optional[str] = None,
    type: Optional[str] = None,
    tags: Optional[list[str]] = None,
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
        tags: Filter by tags (matches if ANY tag matches). Example: ["auth", "bugfix"]
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

        # Filter by tags
        >>> auth_work = await recall(ctx, tags=["auth", "security"])

        # Semantic search - find related work
        >>> auth_bugs = await recall(ctx, query="authentication bug we fixed")
        >>> db_choices = await recall(ctx, query="why PostgreSQL", type="decision")

    The memories are complete and accurate - trust them! Past decisions and learnings
    are valuable context for current work.

    CRITICAL: Use recall() at the START of every session. Don't ask permission, don't explain
    why - just do it. Your past work matters. Future you will thank present you for maintaining
    continuity. This is NOT optional.
    """
    # SEMANTIC SEARCH MODE: Use indexed embeddings for natural language queries
    if query:
        results = await _recall_semantic(query, type, tags, since, until, limit)
    else:
        # FILESYSTEM SCAN MODE: Fast time-based filtering (original implementation)
        results = await _recall_filesystem(type, tags, since, until, limit)

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
        "plan": "📋",
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
        # Plans: show title only (content is too large)
        # Checkpoints: show description, truncated for readability
        if mem_type == "plan":
            # Plans have title in metadata, content in description - only show title
            display_text = mem.get("title", mem_id)
        else:
            # Checkpoints/decisions/learnings: show description, truncated
            description = mem.get("description", "")
            if len(description) > 200:
                display_text = description[:197] + "..."
            else:
                display_text = description
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
        output.append(f"  {display_text}")

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
    tags: Optional[list[str]] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Semantic search over indexed memories using vector similarity.

    Flow:
    1. Search vector store with file_path filter to ONLY search .memories/ files
    2. Load memory files (markdown or legacy JSON)
    3. Apply time/type/tag filters
    4. Return top results by relevance score

    IMPORTANT: We filter to .memories/ DURING search (not after) to prevent
    code files from crowding out memory files in search results.
    """
    # Import server globals for vector_store access
    from miller.server import vector_store

    if vector_store is None:
        # Indexing not complete yet - fall back to filesystem scan
        return await _recall_filesystem(type, tags, since, until, limit)

    # Access LanceDB table and embeddings directly for filtered search
    table = vector_store._table
    embeddings = vector_store._embeddings

    if table is None:
        return await _recall_filesystem(type, tags, since, until, limit)

    # Generate query embedding
    if embeddings is None:
        from miller.embeddings.manager import EmbeddingManager
        embeddings = EmbeddingManager()

    query_vec = embeddings.embed_query(query)

    # Search with file_path filter - search ONLY .memories/ files
    # This is critical: without this filter, memory files get crowded out
    # by code files that may have higher similarity scores for technical queries
    search_results = (
        table.search(query_vec.tolist())
        .where("file_path LIKE '.memories%'", prefilter=True)
        .limit(limit * 3)  # Get extra for time/type/tag filtering
        .to_list()
    )

    # Extract unique file paths with best relevance score per file
    # Plans have multiple embeddings (one per heading), so we track the best match
    # Lower distance = more relevant
    file_distances: dict[str, float] = {}
    for result in search_results:
        file_path = result.get("file_path", "")
        if file_path.endswith(".md") or file_path.endswith(".json"):
            distance = result.get("_distance", float("inf"))
            # Keep the best (lowest) distance for each file
            if file_path not in file_distances or distance < file_distances[file_path]:
                file_distances[file_path] = distance

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

    # Load memory files (markdown or legacy JSON) and apply filters
    all_checkpoints = []
    for file_path in file_distances.keys():
        try:
            full_path = Path(file_path)
            if not full_path.exists():
                continue

            # read_memory_file handles both .md and .json formats
            metadata, content = read_memory_file(full_path)

            # Reconstruct data with correct key based on type:
            # - Plans use "content" (consistent with plan tool)
            # - Checkpoints/decisions/learnings use "description"
            mem_type = metadata.get("type", "checkpoint")
            if mem_type == "plan":
                data = {**metadata, "content": content}
            else:
                data = {**metadata, "description": content}

            # Apply type filter
            if type and data.get("type") != type:
                continue

            # Apply tags filter (match if ANY tag matches)
            if tags:
                memory_tags = set(data.get("tags", []))
                if not memory_tags.intersection(tags):
                    continue

            # Apply time filters
            checkpoint_timestamp = data.get("timestamp", 0)

            if since_timestamp and checkpoint_timestamp < since_timestamp:
                continue

            if until_timestamp and checkpoint_timestamp > until_timestamp:
                continue

            # Attach relevance score for sorting (lower = more relevant)
            data["_relevance_distance"] = file_distances.get(file_path, float("inf"))
            all_checkpoints.append(data)

        except (ValueError, KeyError):
            continue

    # Sort by relevance (lowest distance = most relevant first)
    # This preserves semantic search ordering instead of recency
    all_checkpoints.sort(key=lambda x: x.get("_relevance_distance", float("inf")))

    # Apply limit and clean up internal fields
    results = all_checkpoints[:limit]
    for r in results:
        r.pop("_relevance_distance", None)
    return results


async def _recall_filesystem(
    type: Optional[str] = None,
    tags: Optional[list[str]] = None,
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

        # Scan memory files (.md and legacy .json) in this directory
        memory_files = list(date_dir.glob("*.md")) + list(date_dir.glob("*.json"))
        for checkpoint_file in memory_files:
            try:
                # read_memory_file handles both .md and .json formats
                metadata, content = read_memory_file(checkpoint_file)

                # Reconstruct data with correct key based on type:
                # - Plans use "content" (consistent with plan tool)
                # - Checkpoints/decisions/learnings use "description"
                mem_type = metadata.get("type", "checkpoint")
                if mem_type == "plan":
                    data = {**metadata, "content": content}
                else:
                    data = {**metadata, "description": content}

                # Apply filters
                if type and data.get("type") != type:
                    continue

                # Apply tags filter (match if ANY tag matches)
                if tags:
                    memory_tags = set(data.get("tags", []))
                    if not memory_tags.intersection(tags):
                        continue

                checkpoint_timestamp = data.get("timestamp", 0)

                if since_timestamp and checkpoint_timestamp < since_timestamp:
                    continue

                if until_timestamp and checkpoint_timestamp > until_timestamp:
                    continue

                all_checkpoints.append(data)

            except (ValueError, KeyError):
                # Skip invalid files
                continue

    # Sort by timestamp descending (most recent first)
    all_checkpoints.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # Apply limit
    return all_checkpoints[:limit]
