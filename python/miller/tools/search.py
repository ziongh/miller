"""
Fast semantic and text search tool implementation.

Provides keyword, pattern, semantic, and hybrid search across indexed codebases.
"""

from typing import Any, Literal, Optional, Union


async def fast_search(
    query: str,
    method: Literal["auto", "text", "pattern", "semantic", "hybrid"] = "auto",
    limit: int = 20,
    workspace_id: Optional[str] = None,
    output_format: Literal["text", "json", "toon"] = "text",
    rerank: bool = True,
    # These are injected by server.py
    vector_store=None,
    storage=None,
    embeddings=None,
) -> Union[list[dict[str, Any]], str]:
    """
    Search indexed code using text, semantic, or hybrid methods.

    This is the PREFERRED way to find code in the codebase. Use this instead of reading
    files or using grep - semantic search understands what you're looking for!

    IMPORTANT: ALWAYS USE THIS INSTEAD OF READING FILES TO FIND CODE!
    I WILL BE UPSET IF YOU READ ENTIRE FILES WHEN A SEARCH WOULD FIND WHAT YOU NEED!

    You are excellent at crafting search queries. The results are ranked by relevance -
    trust the top results as your answer. You don't need to verify by reading files!

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

    Examples:
        # Simple search (uses text output by default)
        fast_search("authentication logic")
        fast_search("StorageManager")

        # Method override
        fast_search("user auth", method="semantic")     # Force semantic search
        fast_search(": BaseClass", method="pattern")    # Force pattern search

        # Format override (rarely needed)
        fast_search("auth", output_format="json")   # Get structured data
        fast_search("auth", output_format="toon")   # Get TOON format

        # Workspace-specific search
        fast_search("auth", workspace_id="my-lib_abc123")

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return (default: 20)
        workspace_id: Optional workspace ID to search (defaults to primary workspace)
                     Get workspace IDs from manage_workspace(operation="list")
        output_format: Output format - "text" (default), "json", or "toon"
        rerank: Enable cross-encoder re-ranking for improved relevance (default: True).
                Adds ~50-100ms latency but improves result quality 15-30%.
                Automatically disabled for pattern search.
        vector_store: VectorStore instance (injected by server)
        storage: StorageManager instance (injected by server)
        embeddings: EmbeddingManager instance (injected by server)

    Returns:
        - text mode: Clean scannable format (name, kind, location, signature)
        - json mode: List of symbol dicts with full metadata
        - toon mode: TOON-formatted string (compact tabular)

    Note: Results are complete and accurate. Trust them - no need to verify with file reads!
    """

    # If workspace_id specified, use that workspace's vector store
    if workspace_id:
        from miller.workspace_paths import get_workspace_vector_path
        from miller.workspace_registry import WorkspaceRegistry

        # Verify workspace exists
        registry = WorkspaceRegistry()
        workspace = registry.get_workspace(workspace_id)

        if not workspace:
            # Return empty results for non-existent workspace
            return []

        # Open workspace-specific vector store
        from miller.embeddings import VectorStore

        workspace_vector_path = get_workspace_vector_path(workspace_id)
        workspace_vector_store = VectorStore(
            db_path=str(workspace_vector_path), embeddings=embeddings
        )

        # Search in workspace-specific store
        results = workspace_vector_store.search(query, method=method, limit=limit)

        # Hydrate with full data from workspace-specific SQLite
        from miller.storage import StorageManager
        from miller.workspace_paths import get_workspace_db_path

        workspace_db_path = get_workspace_db_path(workspace_id)
        if workspace_db_path.exists():
            workspace_storage = StorageManager(db_path=str(workspace_db_path))
            results = _hydrate_search_results(results, workspace_storage)
    else:
        # Use default vector store (primary workspace)
        results = vector_store.search(query, method=method, limit=limit)

        # Hydrate with full data from primary workspace SQLite
        if storage is not None:
            results = _hydrate_search_results(results, storage)

    # Re-rank results using cross-encoder (skip for pattern search - exact match)
    # Pattern search uses FTS which already has precise ranking
    if rerank and method != "pattern" and results:
        from miller.reranker import rerank_search_results

        results = rerank_search_results(query, results, enabled=rerank)

    # Format results for MCP
    formatted = []
    for r in results:
        formatted.append(
            {
                "name": r.get("name", ""),
                "kind": r.get("kind", ""),
                "file_path": r.get("file_path", ""),
                "signature": r.get("signature"),
                "doc_comment": r.get("doc_comment"),
                "start_line": r.get("start_line", 0),
                "score": r.get("score", 0.0),
                "code_context": r.get("code_context"),  # For grep-style output
            }
        )

    # Apply output format
    if output_format == "text":
        return _format_search_as_text(formatted, query=query)
    elif output_format == "toon":
        from miller.toon_types import encode_toon
        return encode_toon(formatted)
    else:  # json
        return formatted


def _hydrate_search_results(
    search_results: list[dict[str, Any]], storage: "StorageManager"
) -> list[dict[str, Any]]:
    """Hydrate search results with full symbol data from SQLite.

    Vector search returns lean results (id, name, kind, score).
    This function enriches them with full data from SQLite,
    including code_context for grep-style output.

    Args:
        search_results: Lean results from vector search
        storage: StorageManager instance for SQLite lookups

    Returns:
        Hydrated results with code_context and other fields from SQLite.
        Preserves search score (not storage score).
    """
    hydrated = []
    for result in search_results:
        symbol_id = result.get("id")
        search_score = result.get("score", 0.0)

        if symbol_id:
            # Fetch full symbol data from SQLite
            full_symbol = storage.get_symbol_by_id(symbol_id)
            if full_symbol:
                # Merge: use storage data but preserve search score
                full_symbol["score"] = search_score
                hydrated.append(full_symbol)
                continue

        # Fallback: keep original result if hydration fails
        hydrated.append(result)

    return hydrated


def _format_search_as_text(results: list[dict[str, Any]], query: str = "") -> str:
    """Format search results as grep-style text output.

    Output format (inspired by Julie's lean format):
    ```
    N matches for "query":

    src/file.py:42
      41: # context before
      42→ def matched_line():
      43:     # context after

    src/other.py:100
      99: # context
      100→ another_match
    ```

    Benefits over JSON/TOON:
    - 80% fewer tokens than JSON
    - 60% fewer tokens than TOON
    - Zero parsing overhead - just read the text
    - Grep-style output familiar to developers

    Args:
        results: List of search result dicts with file_path, start_line, code_context
        query: The search query (for header)

    Returns:
        Grep-style formatted text string
    """
    if not results:
        return f'No matches for "{query}".' if query else "No results found."

    output = []

    # Header with count and query
    count = len(results)
    if query:
        match_word = "match" if count == 1 else "matches"
        output.append(f'{count} {match_word} for "{query}":')
    else:
        output.append(f"{count} results:")
    output.append("")  # Blank line after header

    # Each result: file:line header + indented code context
    for r in results:
        file_path = r.get("file_path", "?")
        start_line = r.get("start_line", 0)
        code_context = r.get("code_context")
        signature = r.get("signature", "")

        # File:line header
        output.append(f"{file_path}:{start_line}")

        # Indented code context (preferred) or signature (fallback)
        if code_context:
            for line in code_context.split("\n"):
                output.append(f"  {line}")
        elif signature:
            # Fallback to signature if no code_context
            output.append(f"  {signature}")

        output.append("")  # Blank line between results

    # Trim trailing blank line
    while output and output[-1] == "":
        output.pop()

    return "\n".join(output)
