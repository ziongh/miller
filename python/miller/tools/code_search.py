"""
Code similarity search tool for finding existing implementations.

Uses code-to-code embeddings to find similar code patterns, preventing
agents from reinventing the wheel when similar code already exists.
"""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from miller.embeddings.manager import EmbeddingManager
    from miller.embeddings.vector_store import VectorStore
    from miller.storage import StorageManager

logger = logging.getLogger("miller.code_search")


async def find_similar_implementation(
    code_snippet: str,
    limit: int = 10,
    min_score: float = 0.5,
    language: Optional[str] = None,
    kind_filter: Optional[list[str]] = None,
    # Injected dependencies
    embeddings: Optional["EmbeddingManager"] = None,
    vector_store: Optional["VectorStore"] = None,
    storage: Optional["StorageManager"] = None,
) -> str:
    """
    Find existing implementations similar to the provided code snippet.

    Use this tool BEFORE writing new code to check if similar code already
    exists in the codebase. This prevents:
    - Duplicating existing functionality
    - Reinventing patterns already established
    - Creating inconsistent implementations of the same concept

    The tool uses code-to-code embeddings (Jina similarity task) to find
    semantically similar code, not just text matches.

    Args:
        code_snippet: The code you're about to write or a description of
                     the pattern you're looking for
        limit: Maximum number of results (default: 10)
        min_score: Minimum similarity score 0.0-1.0 (default: 0.5)
        language: Filter to specific language (e.g., "python", "rust")
        kind_filter: Filter to specific symbol kinds (e.g., ["function", "method"])

    Returns:
        Report showing similar implementations with:
        - Similarity score (higher = more similar)
        - File path and line number
        - Symbol name and kind
        - Code preview

    Examples:
        >>> # Before writing a cache implementation
        >>> find_similar_implementation('''
        ... def get_cached(key):
        ...     if key in cache:
        ...         return cache[key]
        ...     result = compute(key)
        ...     cache[key] = result
        ...     return result
        ... ''')

        >>> # Find similar error handling patterns
        >>> find_similar_implementation('''
        ... try:
        ...     result = api.call()
        ... except TimeoutError:
        ...     logger.warning("API timeout")
        ...     return default_value
        ... ''', kind_filter=["function", "method"])
    """
    if embeddings is None or vector_store is None:
        return "Error: Embeddings or vector store not available. Workspace may not be indexed."

    # Embed the code snippet using similarity task (Code→Code)
    try:
        query_vector = embeddings.embed_query(code_snippet, task="similarity")
    except Exception as e:
        logger.error(f"Failed to embed code snippet: {e}")
        return f"Error: Failed to generate embedding for code snippet: {e}"

    # Search vector store for similar code
    try:
        # Use the table directly for similarity search
        table = vector_store.table
        if table is None:
            return "Error: Vector store table not initialized. Run indexing first."

        # Build filter conditions
        filter_conditions = []

        if language:
            # Language is often stored or can be inferred from file extension
            # Using file path pattern for language filtering
            lang_extensions = {
                "python": ".py",
                "rust": ".rs",
                "typescript": ".ts",
                "javascript": ".js",
                "go": ".go",
                "java": ".java",
                "cpp": ".cpp",
                "c": ".c",
            }
            if language.lower() in lang_extensions:
                ext = lang_extensions[language.lower()]
                filter_conditions.append(f"file_path LIKE '%{ext}'")

        if kind_filter:
            kinds_sql = ", ".join(f"'{k}'" for k in kind_filter)
            filter_conditions.append(f"kind IN ({kinds_sql})")

        # Build search query
        search_builder = table.search(
            query_vector.tolist(),
            vector_column_name="vector"
        )

        # Apply filters if any
        if filter_conditions:
            filter_sql = " AND ".join(filter_conditions)
            search_builder = search_builder.where(filter_sql)

        # Get more results initially, then filter by min_score
        raw_results = search_builder.limit(limit * 2).to_list()

    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return f"Error: Vector search failed: {e}"

    # Filter and process results
    results = []
    for r in raw_results:
        # LanceDB returns _distance (L2) - convert to similarity score
        # For normalized vectors: similarity = 1 - (distance^2 / 2)
        distance = r.get("_distance", 0)
        score = max(0.0, 1.0 - (distance ** 2 / 2))

        if score >= min_score:
            results.append({
                "score": score,
                "symbol_id": r.get("symbol_id", ""),
                "name": r.get("name", ""),
                "kind": r.get("kind", ""),
                "file_path": r.get("file_path", ""),
                "line_start": r.get("line_start", 0),
                "signature": r.get("signature", ""),
                "doc": r.get("doc", ""),
            })

    # Sort by score and limit
    results = sorted(results, key=lambda x: -x["score"])[:limit]

    if not results:
        return f"No similar implementations found with score >= {min_score}.\n\nThis code pattern may be unique to your use case, or try lowering min_score."

    # Get code context from storage if available
    if storage:
        symbol_ids = [r["symbol_id"] for r in results if r["symbol_id"]]
        symbols_data = storage.get_symbols_by_ids(symbol_ids)
    else:
        symbols_data = {}

    # Generate report
    lines = [
        "Similar Implementation Search Results",
        "=" * 50,
        f"Found {len(results)} similar implementations",
        "",
    ]

    for i, r in enumerate(results, 1):
        score_pct = r["score"] * 100
        score_bar = "█" * int(score_pct / 10) + "░" * (10 - int(score_pct / 10))

        lines.append(f"─── Result {i} ───")
        lines.append(f"Score: {score_pct:.1f}% [{score_bar}]")
        lines.append(f"Symbol: {r['name']} ({r['kind']})")
        lines.append(f"Location: {r['file_path']}:{r['line_start']}")

        # Add signature if available
        if r["signature"]:
            sig = r["signature"]
            if len(sig) > 100:
                sig = sig[:97] + "..."
            lines.append(f"Signature: {sig}")

        # Add doc if available
        if r["doc"]:
            doc = r["doc"].split("\n")[0]  # First line only
            if len(doc) > 80:
                doc = doc[:77] + "..."
            lines.append(f"Doc: {doc}")

        # Add code context if available from storage
        symbol_data = symbols_data.get(r["symbol_id"], {})
        if symbol_data.get("code_context"):
            context = symbol_data["code_context"]
            # Limit to first 5 lines
            context_lines = context.split("\n")[:5]
            if len(context_lines) < context.count("\n") + 1:
                context_lines.append("...")
            lines.append("Preview:")
            for cl in context_lines:
                lines.append(f"  {cl}")

        lines.append("")

    # Add guidance
    lines.append("─" * 50)
    if results[0]["score"] >= 0.8:
        lines.append("⚠️  High similarity found! Consider reusing or extending existing code.")
    elif results[0]["score"] >= 0.6:
        lines.append("💡 Similar patterns exist. Review before implementing.")
    else:
        lines.append("ℹ️  Some related code found. May serve as reference.")

    return "\n".join(lines)
