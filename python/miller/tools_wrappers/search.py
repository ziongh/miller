"""
Search tool wrappers for FastMCP.

Contains wrappers for fast_search and fast_search_multi.
"""

from typing import Any, Literal, Optional, Union

from miller import server_state
from miller.tools.search import fast_search as fast_search_impl
from miller.tools.search_multi import fast_search_multi as fast_search_multi_impl
from miller.tools_wrappers.common import await_ready


async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    workspace: str = "primary",
    output_format: Literal["text", "json", "toon"] = "text",
    rerank: bool = True,
    expand: bool = False,
    expand_limit: int = 5,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
) -> Union[list[dict[str, Any]], str]:
    """
    Search indexed code using text, semantic, or hybrid methods.

    This is the PREFERRED way to find code in the codebase. Use this instead of reading
    files or using grep - semantic search understands what you're looking for!

    When to use: ALWAYS before reading files. Search first to narrow scope by 90%,
    then read only what you need. This is 10x faster than reading entire files.

    You are excellent at crafting search queries. The results are ranked by relevance -
    trust the top results as your answer.

    IMPORTANT: Do NOT read files to "verify" search results. The results ARE the verification.
    Miller's pre-indexed results are accurate and complete. Reading files after searching
    wastes the tokens you just saved. Use results directly and move on.

    Method selection (default: auto):
    - auto: Detects query type automatically (RECOMMENDED)
      * Has special chars (: < > [ ]) → pattern search (code idioms)
      * Natural language → hybrid search (text + semantic)
    - text: Full-text search with stemming (general code search)
    - pattern: Code idioms (: BaseClass, ILogger<, [Fact], etc.)
    - semantic: Vector similarity (conceptual matches)
    - hybrid: Combines text + semantic with RRF fusion

    Output format (default: text):
    - text: Clean, scannable format optimized for AI reading (DEFAULT)
    - json: List of dicts with full metadata (for programmatic use)
    - toon: TOON-formatted string (compact tabular format)

    Filtering:
    - language: Filter by programming language (e.g., "python", "rust", "typescript")
    - file_pattern: Filter by glob pattern (e.g., "*.py", "src/**/*.ts", "tests/**")

    Semantic fallback:
    - When method="text" returns 0 results, automatically tries semantic search
    - This helps find conceptually similar code when exact terms don't match

    Examples:
        # Simple search (uses text output by default)
        fast_search("authentication logic")
        fast_search("StorageManager")

        # Method override
        fast_search("user auth", method="semantic")     # Force semantic search
        fast_search(": BaseClass", method="pattern")    # Force pattern search

        # Filter by language
        fast_search("user service", language="python")  # Only Python results

        # Filter by file pattern
        fast_search("test", file_pattern="tests/**")    # Only test files

        # Combine filters
        fast_search("handler", language="rust", file_pattern="src/**")

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return (default: 20)
        workspace: Workspace to query ("primary" or workspace_id from manage_workspace)
        output_format: Output format - "text" (default), "json", or "toon"
        rerank: Enable cross-encoder re-ranking for improved relevance (default: True).
        expand: Include caller/callee context for each result (default: False).
        expand_limit: Maximum callers/callees to include per result (default: 5).
        language: Filter results by programming language (case-insensitive).
        file_pattern: Filter results by file path glob pattern.

    Returns:
        - text mode: Clean scannable format (name, kind, location, signature)
        - json mode: List of symbol dicts with full metadata
        - toon mode: TOON-formatted string (compact tabular)
    """
    if err := await await_ready():
        return err
    return await fast_search_impl(
        query=query,
        method=method,
        limit=limit,
        workspace=workspace,
        output_format=output_format,
        rerank=rerank,
        expand=expand,
        expand_limit=expand_limit,
        language=language,
        file_pattern=file_pattern,
        vector_store=server_state.vector_store,
        storage=server_state.storage,
        embeddings=server_state.embeddings,
    )


async def fast_search_multi(
    query: str,
    workspaces: list[str] = None,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    output_format: Literal["text", "json", "toon"] = "text",
    rerank: bool = True,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
) -> Union[list[dict[str, Any]], str]:
    """
    Search across multiple workspaces simultaneously.

    Use this when you need to find code across multiple repositories at once.
    Results are merged and re-ranked by relevance, with workspace attribution.

    This is the cross-workspace counterpart to fast_search. Use fast_search for
    single-workspace queries (faster), and fast_search_multi when you need to
    search across multiple indexed codebases.

    Args:
        query: Search query (code patterns, keywords, or natural language)
        workspaces: List of workspace IDs to search, or None/empty for ALL registered workspaces.
                   Use manage_workspace(operation="list") to see available workspace IDs.
        method: Search method (auto-detects by default)
        limit: Maximum total results to return after merging (default: 20)
        output_format: Output format - "text" (default), "json", or "toon"
        rerank: Re-rank merged results for better relevance (default: True)
        language: Filter by programming language (e.g., "python", "rust")
        file_pattern: Filter by file glob pattern (e.g., "*.py", "src/**")

    Returns:
        Merged results from all specified workspaces, with workspace attribution.
        Each result includes a "workspace" field identifying its source.

    Examples:
        # Search all registered workspaces
        fast_search_multi("authentication")

        # Search specific workspaces only
        fast_search_multi("user model", workspaces=["workspace_abc", "workspace_def"])

        # Filter by language across all workspaces
        fast_search_multi("config parser", language="python")
    """
    if err := await await_ready():
        return err
    return await fast_search_multi_impl(
        query=query,
        workspaces=workspaces,
        method=method,
        limit=limit,
        output_format=output_format,
        rerank=rerank,
        language=language,
        file_pattern=file_pattern,
        vector_store=server_state.vector_store,
        storage=server_state.storage,
        embeddings=server_state.embeddings,
    )
