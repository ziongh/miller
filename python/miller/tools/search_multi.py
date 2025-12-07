"""
Cross-workspace search tool - query multiple workspaces in one request.

This module provides the fast_search_multi tool which allows searching across
multiple indexed workspaces simultaneously, merging and re-ranking results.

Use Cases:
- Searching across a main project and its dependencies
- Finding code patterns across multiple microservices
- Unified search when working with monorepo-like setups
"""

import asyncio
import logging
from typing import Any, Literal, Optional, Union

from miller.tools.search import fast_search as single_workspace_search
from miller.workspace_registry import WorkspaceRegistry

logger = logging.getLogger("miller.search_multi")


async def fast_search_multi(
    query: str,
    workspaces: Optional[list[str]] = None,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    output_format: Literal["text", "json", "toon"] = "text",
    rerank: bool = True,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
    # Injected by server
    vector_store=None,
    storage=None,
    embeddings=None,
) -> Union[list[dict[str, Any]], str]:
    """
    Search across multiple workspaces simultaneously.

    Results are merged with workspace attribution and re-ranked by relevance.
    This is the cross-workspace counterpart to fast_search.

    Args:
        query: Search query (code patterns, keywords, or natural language)
        workspaces: List of workspace IDs to search, or None/empty list for ALL registered workspaces.
                   Use manage_workspace(operation="list") to see available workspace IDs.
        method: Search method (auto-detects by default)
            - auto: Detects query type automatically (RECOMMENDED)
            - text: Full-text search with stemming
            - pattern: Code idioms (: BaseClass, ILogger<, etc.)
            - semantic: Vector similarity (conceptual matches)
            - hybrid: Combines text + semantic with RRF fusion
        limit: Maximum total results to return after merging (default: 20)
        output_format: Output format - "text" (default), "json", or "toon"
        rerank: Re-rank merged results using cross-encoder (default: True)
        language: Filter by programming language (e.g., "python", "rust")
        file_pattern: Filter by file glob pattern (e.g., "*.py", "src/**")

    Returns:
        Merged results from all workspaces, with workspace attribution.
        Each result includes a "workspace" field identifying its source.

    Examples:
        # Search all registered workspaces
        fast_search_multi("authentication")

        # Search specific workspaces only
        fast_search_multi("user model", workspaces=["workspace_abc", "workspace_def"])

        # Filter by language across all workspaces
        fast_search_multi("config parser", language="python")

        # Combine with file pattern
        fast_search_multi("test", file_pattern="tests/**")
    """
    registry = WorkspaceRegistry()

    # Determine which workspaces to search
    if workspaces is None or len(workspaces) == 0:
        # Search all registered workspaces
        workspace_entries = registry.list_workspaces()
        workspace_ids = [w["workspace_id"] for w in workspace_entries]
    else:
        # Validate provided workspace IDs
        workspace_ids = []
        invalid_workspaces = []
        for ws_id in workspaces:
            if registry.get_workspace(ws_id):
                workspace_ids.append(ws_id)
            else:
                invalid_workspaces.append(ws_id)

        if invalid_workspaces:
            logger.warning(f"Invalid workspace IDs: {invalid_workspaces}")

    if not workspace_ids:
        if output_format == "text":
            return (
                f'No workspaces available to search. '
                f'Use manage_workspace(operation="list") to see registered workspaces, '
                f'or manage_workspace(operation="add") to add new ones.'
            )
        return []

    logger.info(f"Searching {len(workspace_ids)} workspace(s) for: {query}")

    # Search each workspace in parallel
    async def search_one(ws_id: str) -> list[dict]:
        """Search a single workspace and add workspace attribution."""
        try:
            results = await single_workspace_search(
                query=query,
                method=method,
                limit=limit,  # Get up to limit results per workspace (will be merged and re-ranked later)
                workspace=ws_id,
                output_format="json",  # Always structured for merging
                rerank=False,  # We'll rerank merged results
                language=language,
                file_pattern=file_pattern,
                vector_store=vector_store,
                storage=storage,
                embeddings=embeddings,
            )

            # Add workspace attribution to each result
            if isinstance(results, list):
                for r in results:
                    r["workspace"] = ws_id
                return results
            return []
        except Exception as e:
            logger.error(f"Error searching workspace {ws_id}: {e}")
            return []

    # Execute searches in parallel for efficiency
    all_results = await asyncio.gather(*[search_one(ws) for ws in workspace_ids])

    # Flatten results from all workspaces
    merged = []
    for results in all_results:
        merged.extend(results)

    logger.info(f"Found {len(merged)} total results across {len(workspace_ids)} workspace(s)")

    # Re-rank merged results if requested
    if rerank and merged:
        from miller.reranker import rerank_search_results

        merged = rerank_search_results(query, merged, enabled=True)

    # Limit to requested number of results
    merged = merged[:limit]

    # Format output
    if output_format == "text":
        return _format_multi_search_as_text(merged, query, workspace_ids)
    elif output_format == "toon":
        from miller.toon_types import encode_toon

        return encode_toon(merged)
    return merged


def _format_multi_search_as_text(
    results: list[dict],
    query: str,
    workspaces: list[str],
) -> str:
    """
    Format multi-workspace search results as grep-style text output.

    Output format includes workspace attribution:
    ```
    N matches for "query" across M workspace(s):

    [workspace_abc] src/file.py:42
      def matched_function():

    [workspace_def] lib/other.py:100
      class OtherMatch:
    ```

    Args:
        results: List of search result dicts with workspace attribution
        query: The search query (for header)
        workspaces: List of workspace IDs that were searched

    Returns:
        Formatted text string with workspace-prefixed results
    """
    if not results:
        ws_str = ", ".join(workspaces[:3])
        if len(workspaces) > 3:
            ws_str += f" +{len(workspaces) - 3} more"
        return f'No matches for "{query}" across workspaces: {ws_str}'

    output = []

    # Header with count and workspace info
    count = len(results)
    unique_workspaces = set(r.get("workspace", "?") for r in results)
    ws_count = len(unique_workspaces)

    match_word = "match" if count == 1 else "matches"
    ws_word = "workspace" if ws_count == 1 else "workspaces"
    output.append(f'{count} {match_word} for "{query}" across {ws_count} {ws_word}:')
    output.append("")

    # Each result with workspace prefix
    for r in results:
        workspace = r.get("workspace", "?")
        file_path = r.get("file_path", "?")
        start_line = r.get("start_line", 0)
        code_context = r.get("code_context")
        signature = r.get("signature", "")

        # Workspace-prefixed file:line header
        output.append(f"[{workspace}] {file_path}:{start_line}")

        # Code context or fallback
        if code_context:
            for line in code_context.split("\n"):
                output.append(f"  {line}")
        elif signature:
            output.append(f"  {signature}")
        else:
            name = r.get("name", "?")
            kind = r.get("kind", "symbol")
            output.append(f"  {name} ({kind})")

        output.append("")

    # Trim trailing blank line
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)
