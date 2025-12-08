"""Search method implementations for VectorStore.

Provides text, semantic, hybrid, and pattern search methods with
fallback implementations for compatibility.

All search methods support optional kind_filter for type-aware filtering:
- When kind_filter is provided, results are filtered to matching kinds
- This dramatically improves precision for intent-aware queries
- Example: filter=["class", "struct"] when user asks "how is X defined?"
"""

import logging
from typing import Any, Optional

from miller.embeddings.search import format_kind_filter_sql

logger = logging.getLogger("miller.vector_store")


def search_pattern(
    table: Any,
    pattern_index_created: bool,
    query: str,
    limit: int,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """
    Pattern search using whitespace-tokenized FTS.

    Designed for code idiom search (: < > [ ] ( ) { }).
    Uses whitespace tokenizer which preserves all special characters.

    Args:
        table: LanceDB table to search
        pattern_index_created: Whether pattern index is available
        query: Pattern query (e.g., ": BaseClass", "ILogger<", "[Fact]")
        limit: Maximum results
        kind_filter: Optional list of symbol kinds to filter by

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

        # Build the search query
        search_builder = table.search(search_query, query_type="fts")

        # Apply kind filter if provided
        if kind_filter:
            filter_sql = format_kind_filter_sql(kind_filter)
            if filter_sql:
                search_builder = search_builder.where(filter_sql)

        results = search_builder.limit(limit).to_list()

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


def search_text(
    table: Any,
    fts_index_created: bool,
    query: str,
    limit: int,
    apply_enhancements,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
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
    - Optional kind filtering for intent-aware search

    Args:
        table: LanceDB table to search
        fts_index_created: Whether FTS index is available
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements
        kind_filter: Optional list of symbol kinds to filter by

    Returns:
        List of matching symbols with scores
    """
    if not fts_index_created:
        # Fallback to LIKE queries if FTS not available
        return search_text_fallback(table, query, limit, kind_filter)

    try:
        # Use Tantivy FTS with BM25 scoring (with original query - no preprocessing)
        # Over-fetch to allow kind weighting to re-rank before truncating
        # Min of 50 ensures high-value symbols (functions) aren't cut before boosting
        fetch_limit = max(limit * 3, 50)

        # Build search query
        search_builder = table.search(query, query_type="fts")

        # Apply kind filter if provided
        if kind_filter:
            filter_sql = format_kind_filter_sql(kind_filter)
            if filter_sql:
                search_builder = search_builder.where(filter_sql)

        results = search_builder.limit(fetch_limit).to_list()

        # Convert BM25 scores to 0.0-1.0 range
        # Use a reference normalization rather than per-query max to preserve absolute quality
        # BM25 scores vary widely, typical good matches are 5-20, so we scale by ~20
        if results:
            for r in results:
                raw_score = r.get("_score", 0.0)
                # Scale BM25: typical max around 20 for good matches
                r["score"] = min(raw_score / 20.0, 1.0)

        # Apply search quality enhancements (boosting, weighting, filtering)
        results = apply_enhancements(results, query, method="text")

        # Return top results after enhancement
        return results[:limit]

    except (ValueError, Exception) as e:
        # Tantivy raises ValueError for malformed queries (e.g., SQL injection attempts)
        # Return empty results instead of crashing (safe failure mode)
        logger.warning(f"Text search failed for query '{query}': {e}")
        return []


def search_text_fallback(
    table: Any,
    query: str,
    limit: int,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """
    Fallback text search using LIKE queries (for older LanceDB versions).

    WARNING: Less efficient, no stemming, no BM25 ranking.

    Args:
        table: LanceDB table to search
        query: Search query
        limit: Maximum results
        kind_filter: Optional list of symbol kinds to filter by

    Returns:
        List of matching symbols
    """
    # Use parameterized query to avoid SQL injection
    # Note: LanceDB's where() still uses string formatting for SQL-like syntax
    # This is a limitation of the current API
    where_clause = f"name LIKE '%{query}%' OR signature LIKE '%{query}%' OR doc_comment LIKE '%{query}%'"

    # Add kind filter if provided
    if kind_filter:
        kind_sql = format_kind_filter_sql(kind_filter)
        if kind_sql:
            where_clause = f"({where_clause}) AND {kind_sql}"

    results = (
        table.search()
        .where(where_clause)
        .limit(limit)
        .to_list()
    )

    # Add score (simple match = 1.0)
    for r in results:
        r["score"] = 1.0

    return results


def search_semantic(
    table: Any,
    embeddings,
    query: str,
    limit: int,
    mrl_short_dim: int = 64,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """
    Semantic search with optional Matryoshka Representation Learning (MRL).

    When MRL is enabled (mrl_short_dim > 0):
    - Two-stage search for optimal speed + accuracy:
      1. Fast retrieval: Search short_vector (64D) with higher limit
      2. Re-rank: Compute exact cosine similarity on full vector (896D)
    - This approach gives ~10x faster search with the same accuracy

    When MRL is disabled (mrl_short_dim <= 0):
    - Direct full-vector search (slightly more accurate but slower)
    - Best for small datasets or when accuracy is critical

    Args:
        table: LanceDB table to search
        embeddings: EmbeddingManager instance or None
        query: Search query (natural language)
        limit: Maximum results
        mrl_short_dim: Short vector dimension for MRL (default: 64).
                      Set to 0 or negative to disable MRL and use full vectors.
        kind_filter: Optional list of symbol kinds to filter by

    Returns:
        List of matching symbols with similarity scores
    """
    import numpy as np

    # Get or create embedding manager
    if embeddings is None:
        from miller.embeddings.manager import EmbeddingManager
        embeddings = EmbeddingManager()

    # Embed query to full dimension
    full_query_vec = embeddings.embed_query(query)

    # MRL DISABLED: Direct full-vector search
    if mrl_short_dim <= 0:
        logger.debug("MRL disabled - using direct full-vector search")
        search_builder = table.search(full_query_vec.tolist(), vector_column_name="vector")

        # Apply kind filter if provided
        if kind_filter:
            filter_sql = format_kind_filter_sql(kind_filter)
            if filter_sql:
                search_builder = search_builder.where(filter_sql)

        results = search_builder.limit(limit).to_list()

        # Convert distance to similarity score
        for r in results:
            if "_distance" in r:
                # L2 distance to cosine similarity (vectors are normalized)
                r["score"] = 1.0 - (r["_distance"] / 2.0)
            else:
                r["score"] = 0.5

        return results

    # MRL ENABLED: Two-stage search (short vector retrieval + full vector re-ranking)
    short_query_vec = full_query_vec[:mrl_short_dim]

    # Stage 1: Fast candidate retrieval using short_vector
    # Over-fetch to ensure we have enough candidates for accurate re-ranking
    candidate_limit = max(limit * 5, 100)

    try:
        # Build search query
        search_builder = table.search(short_query_vec.tolist(), vector_column_name="short_vector")

        # Apply kind filter if provided
        if kind_filter:
            filter_sql = format_kind_filter_sql(kind_filter)
            if filter_sql:
                search_builder = search_builder.where(filter_sql)

        results = search_builder.limit(candidate_limit).to_list()

    except Exception as e:
        # Fallback: short_vector column might not exist (old schema)
        logger.warning(f"MRL search failed (missing short_vector?), falling back to full vector: {e}")
        search_builder = table.search(full_query_vec.tolist(), vector_column_name="vector")

        # Apply kind filter in fallback too
        if kind_filter:
            filter_sql = format_kind_filter_sql(kind_filter)
            if filter_sql:
                search_builder = search_builder.where(filter_sql)

        results = search_builder.limit(limit).to_list()
        # Convert distance to similarity
        for r in results:
            if "_distance" in r:
                r["score"] = 1.0 - (r["_distance"] / 2.0)
            else:
                r["score"] = 0.5
        return results

    if not results:
        return []

    # Stage 2: Re-rank using full vectors with exact cosine similarity
    # Extract full vectors from candidates
    for r in results:
        full_vec = np.array(r.get("vector", []), dtype=np.float32)
        if len(full_vec) > 0:
            # Cosine similarity (vectors are L2 normalized, so dot product = cosine)
            similarity = float(np.dot(full_query_vec, full_vec))
            r["score"] = max(0.0, min(1.0, similarity))  # Clamp to [0, 1]
        else:
            # Fallback: use short vector distance
            if "_distance" in r:
                r["score"] = 1.0 - (r["_distance"] / 2.0)
            else:
                r["score"] = 0.5

    # Sort by re-ranked score (highest first)
    results.sort(key=lambda r: r.get("score", 0.0), reverse=True)

    return results[:limit]


def search_hybrid(
    table: Any,
    fts_index_created: bool,
    embeddings,
    query: str,
    limit: int,
    apply_enhancements,
    mrl_short_dim: int = 64,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """
    Hybrid search: combine text (FTS) and semantic (vector) with RRF fusion.

    Uses LanceDB's native Reciprocal Rank Fusion for optimal ranking.
    When MRL is enabled (mrl_short_dim > 0), uses short vectors for faster semantic component.
    When MRL is disabled (mrl_short_dim <= 0), uses full vectors directly.
    Falls back to manual merging if hybrid search not available.

    Args:
        table: LanceDB table to search
        fts_index_created: Whether FTS index is available
        embeddings: EmbeddingManager instance or None
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements
        mrl_short_dim: Short vector dimension for MRL (default: 64).
                      Set to 0 or negative to disable MRL and use full vectors.
        kind_filter: Optional list of symbol kinds to filter by

    Returns:
        List of matching symbols with scores
    """
    if not fts_index_created:
        # Fall back to manual merging if FTS not available
        return search_hybrid_fallback(table, embeddings, query, limit, apply_enhancements, mrl_short_dim, kind_filter)

    try:
        # Use LanceDB's native hybrid search with RRF
        # Need to embed query for vector component
        if embeddings is None:
            from miller.embeddings.manager import EmbeddingManager
            embeddings = EmbeddingManager()

        # Embed query
        full_query_vec = embeddings.embed_query(query)

        # Over-fetch to allow kind weighting to re-rank before truncating
        fetch_limit = max(limit * 3, limit + 50)

        # MRL DISABLED: Use full vector directly
        if mrl_short_dim <= 0:
            logger.debug("MRL disabled - using full vector for hybrid search")
            search_builder = table.search(full_query_vec.tolist(), query_type="hybrid", vector_column_name="vector")

            # Apply kind filter if provided
            if kind_filter:
                filter_sql = format_kind_filter_sql(kind_filter)
                if filter_sql:
                    search_builder = search_builder.where(filter_sql)

            results = search_builder.limit(fetch_limit).to_list()
        else:
            # MRL ENABLED: Try short_vector first for faster search
            short_query_vec = full_query_vec[:mrl_short_dim]

            try:
                search_builder = table.search(short_query_vec.tolist(), query_type="hybrid", vector_column_name="short_vector")

                # Apply kind filter if provided
                if kind_filter:
                    filter_sql = format_kind_filter_sql(kind_filter)
                    if filter_sql:
                        search_builder = search_builder.where(filter_sql)

                results = search_builder.limit(fetch_limit).to_list()
            except Exception:
                # Fall back to full vector hybrid search
                search_builder = table.search(full_query_vec.tolist(), query_type="hybrid", vector_column_name="vector")

                # Apply kind filter in fallback too
                if kind_filter:
                    filter_sql = format_kind_filter_sql(kind_filter)
                    if filter_sql:
                        search_builder = search_builder.where(filter_sql)

                results = search_builder.limit(fetch_limit).to_list()

        # Convert _score to score, normalizing to 0.0-1.0 range
        if results:
            for r in results:
                raw_score = r.get("_score", 0.0)
                # RRF scores: scale to 0-1 range
                r["score"] = min(raw_score * 2.0, 1.0)

        # Apply kind weighting, field boosting, etc.
        results = apply_enhancements(results, query, method="hybrid")

        return results[:limit]

    except Exception as e:
        logger.debug(f"Native hybrid search failed, using fallback: {e}")
        return search_hybrid_fallback(table, embeddings, query, limit, apply_enhancements, mrl_short_dim, kind_filter)


def search_hybrid_fallback(
    table: Any,
    embeddings,
    query: str,
    limit: int,
    apply_enhancements,
    mrl_short_dim: int = 64,
    kind_filter: Optional[list[str]] = None,
) -> list[dict]:
    """
    Fallback hybrid search: manual merging of text and semantic results.

    Used when LanceDB's native hybrid search is not available.
    When MRL is enabled (mrl_short_dim > 0), uses MRL-based semantic search.
    When MRL is disabled (mrl_short_dim <= 0), uses direct full-vector search.

    Args:
        table: LanceDB table to search
        embeddings: EmbeddingManager instance or None
        query: Search query
        limit: Maximum results
        apply_enhancements: Callback function to apply search enhancements
        mrl_short_dim: Short vector dimension for MRL (default: 64).
                      Set to 0 or negative to disable MRL.
        kind_filter: Optional list of symbol kinds to filter by

    Returns:
        List of merged, deduplicated matching symbols with scores
    """
    # Get results from both methods (without enhancements - we'll apply after merge)
    # Pass kind_filter to both search methods
    text_results = search_text(table, True, query, limit * 2, lambda r, q, method=None: r, kind_filter)
    # Use MRL-enabled semantic search
    semantic_results = search_semantic(table, embeddings, query, limit * 2, mrl_short_dim, kind_filter)

    # Merge and deduplicate by ID, keeping the higher score
    seen = {}
    for r in text_results + semantic_results:
        rid = r["id"]
        if rid not in seen or r.get("score", 0) > seen[rid].get("score", 0):
            seen[rid] = r

    merged = list(seen.values())

    # Apply enhancements AFTER merging (so kind weighting affects all results)
    merged = apply_enhancements(merged, query, "hybrid")

    return merged[:limit]
