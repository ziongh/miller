"""Search method implementations for VectorStore.

Provides text, semantic, hybrid, and pattern search methods with
fallback implementations for compatibility.
"""

import logging
from typing import Any

logger = logging.getLogger("miller.vector_store")


def search_pattern(table: Any, pattern_index_created: bool, query: str, limit: int) -> list[dict]:
    """
    Pattern search using whitespace-tokenized FTS.

    Designed for code idiom search (: < > [ ] ( ) { }).
    Uses whitespace tokenizer which preserves all special characters.

    Args:
        table: LanceDB table to search
        pattern_index_created: Whether pattern index is available
        query: Pattern query (e.g., ": BaseClass", "ILogger<", "[Fact]")
        limit: Maximum results

    Returns:
        List of matching symbols with normalized scores (0.0-1.0)
    """
    if not pattern_index_created:
        # Pattern index not available, return empty
        return []

    try:
        # Auto-wrap in quotes for phrase search (handles special chars safely)
        # Tantivy requires phrase search for queries with special chars
        search_query = f'"{query}"' if not query.startswith('"') else query

        # Use FTS search - LanceDB will use the whitespace-tokenized index on code_pattern
        results = table.search(search_query, query_type="fts").limit(limit).to_list()

        # Normalize BM25 scores to 0.0-1.0 range
        if results:
            max_score = max(r.get("_score", 0.0) for r in results)
            for r in results:
                raw_score = r.get("_score", 0.0)
                r["score"] = raw_score / max_score if max_score > 0 else 0.0

        return results

    except (ValueError, Exception) as e:
        # Tantivy might reject malformed queries
        # Return empty results instead of crashing (safe failure mode)
        logger.warning(f"Pattern search failed for query '{query}': {e}")
        return []


def search_text(table: Any, fts_index_created: bool, query: str, limit: int, apply_enhancements) -> list[dict]:
    """
    Text search using Tantivy FTS with BM25 scoring + quality enhancements.

    Features:
    - BM25 relevance ranking (not just 1.0)
    - Whitespace tokenization (preserves CamelCase, no stemming currently)
    - Phrase search support (quoted strings)
    - Safe from SQL injection (Tantivy rejects invalid queries)
    - Field boosting (name > signature > doc)
    - Match position boosting (exact > prefix > suffix)
    - Symbol kind weighting (functions/classes > variables)
    - Quality filtering (removes noise)

    Args:
        table: LanceDB table to search
        fts_index_created: Whether FTS index is available
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements

    Returns:
        List of matching symbols with scores
    """
    if not fts_index_created:
        # Fallback to LIKE queries if FTS not available
        return search_text_fallback(table, query, limit)

    try:
        # Use Tantivy FTS with BM25 scoring (with original query - no preprocessing)
        # Over-fetch to allow kind weighting to re-rank before truncating
        # Min of 50 ensures high-value symbols (functions) aren't cut before boosting
        fetch_limit = max(limit * 3, 50)
        results = table.search(query, query_type="fts").limit(fetch_limit).to_list()

        # Normalize BM25 scores to 0.0-1.0 range (initial normalization)
        # LanceDB returns _score field with BM25 values
        if results:
            max_score = max(r.get("_score", 0.0) for r in results)
            for r in results:
                # Normalize: divide by max score
                raw_score = r.get("_score", 0.0)
                r["score"] = raw_score / max_score if max_score > 0 else 0.0

        # Apply search quality enhancements (boosting, weighting, filtering)
        results = apply_enhancements(results, query, method="text")

        # Return top results after enhancement
        return results[:limit]

    except (ValueError, Exception) as e:
        # Tantivy raises ValueError for malformed queries (e.g., SQL injection attempts)
        # Return empty results instead of crashing (safe failure mode)
        logger.warning(f"Text search failed for query '{query}': {e}")
        return []


def search_text_fallback(table: Any, query: str, limit: int) -> list[dict]:
    """
    Fallback text search using LIKE queries (for older LanceDB versions).

    WARNING: Less efficient, no stemming, no BM25 ranking.

    Args:
        table: LanceDB table to search
        query: Search query
        limit: Maximum results

    Returns:
        List of matching symbols
    """
    # Use parameterized query to avoid SQL injection
    # Note: LanceDB's where() still uses string formatting for SQL-like syntax
    # This is a limitation of the current API
    results = (
        table.search()
        .where(
            f"name LIKE '%{query}%' OR signature LIKE '%{query}%' OR doc_comment LIKE '%{query}%'"
        )
        .limit(limit)
        .to_list()
    )

    # Add score (simple match = 1.0)
    for r in results:
        r["score"] = 1.0

    return results


def search_semantic(table: Any, embeddings, query: str, limit: int) -> list[dict]:
    """
    Semantic search using vector similarity.

    Requires embedding the query first.

    Args:
        table: LanceDB table to search
        embeddings: EmbeddingManager instance or None
        query: Search query (natural language)
        limit: Maximum results

    Returns:
        List of matching symbols with similarity scores
    """
    # Get or create embedding manager
    if embeddings is None:
        # Fallback: create temporary embedding manager (lazy initialization)
        # This is less efficient but works if VectorStore was created without embeddings
        from miller.embeddings.manager import EmbeddingManager

        embeddings = EmbeddingManager()

    query_vec = embeddings.embed_query(query)

    # Vector search
    results = table.search(query_vec.tolist()).limit(limit).to_list()

    # LanceDB returns _distance - convert to similarity score
    for r in results:
        # Distance is in results, convert to similarity (1 - distance)
        # For L2 normalized vectors, distance ≈ 2*(1 - cosine_similarity)
        if "_distance" in r:
            r["score"] = 1.0 - (r["_distance"] / 2.0)
        else:
            r["score"] = 0.5  # Default

    return results


def search_hybrid(table: Any, fts_index_created: bool, embeddings, query: str, limit: int, apply_enhancements) -> list[dict]:
    """
    Hybrid search: combine text (FTS) and semantic (vector) with RRF fusion.

    Uses LanceDB's native Reciprocal Rank Fusion for optimal ranking.
    Falls back to manual merging if hybrid search not available.

    Args:
        table: LanceDB table to search
        fts_index_created: Whether FTS index is available
        embeddings: EmbeddingManager instance or None
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements

    Returns:
        List of matching symbols with scores
    """
    if not fts_index_created:
        # Fall back to manual merging if FTS not available
        return search_hybrid_fallback(table, embeddings, query, limit, apply_enhancements)

    try:
        # Use LanceDB's native hybrid search with RRF
        # Need to embed query for vector component
        if embeddings is None:
            # Fallback: create temporary embedding manager (lazy initialization)
            from miller.embeddings.manager import EmbeddingManager

            embeddings = EmbeddingManager()

        embeddings.embed_query(query)

        # Over-fetch to allow kind weighting to re-rank before truncating
        # Without this, high-value symbols (functions, classes) might be cut
        # before they can be boosted above low-value symbols (imports)
        fetch_limit = max(limit * 3, limit + 50)
        results = table.search(query, query_type="hybrid").limit(fetch_limit).to_list()

        # Normalize scores to 0.0-1.0 range
        if results:
            max_score = max(r.get("_score", 0.0) for r in results)
            for r in results:
                raw_score = r.get("_score", 0.0)
                r["score"] = raw_score / max_score if max_score > 0 else 0.0

        # Apply kind weighting, field boosting, etc.
        results = apply_enhancements(results, query, method="hybrid")

        # Now truncate to requested limit (after re-ranking)
        return results[:limit]

    except Exception as e:
        # Hybrid search might not be supported in this LanceDB version
        # Fall back to manual merging
        logger.debug(f"Native hybrid search failed, using fallback: {e}")
        return search_hybrid_fallback(table, embeddings, query, limit, apply_enhancements)


def search_hybrid_fallback(table: Any, embeddings, query: str, limit: int, apply_enhancements) -> list[dict]:
    """
    Fallback hybrid search: manual merging of text and semantic results.

    Used when LanceDB's native hybrid search is not available.

    Args:
        table: LanceDB table to search
        embeddings: EmbeddingManager instance or None
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements

    Returns:
        List of merged, deduplicated matching symbols with scores
    """
    # Get results from both methods
    text_results = search_text(table, True, query, limit, apply_enhancements)
    semantic_results = search_semantic(table, embeddings, query, limit)

    # Merge and deduplicate by ID
    seen = set()
    merged = []

    for r in semantic_results + text_results:
        if r["id"] not in seen:
            seen.add(r["id"])
            merged.append(r)

    # Sort by score descending
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)

    return merged[:limit]
