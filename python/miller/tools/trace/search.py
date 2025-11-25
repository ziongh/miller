"""
Symbol search and matching functions for call tracing.
"""

from collections import defaultdict
from typing import Any, Optional
from miller.storage import StorageManager
from miller.tools.naming import generate_variants
from miller.tools.trace_types import TraceDirection


def _find_symbols(
    storage: StorageManager, symbol_name: str, context_file: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Find symbol(s) in database by name.

    Args:
        storage: StorageManager instance
        symbol_name: Symbol name to search for
        context_file: Optional file path to filter results

    Returns:
        List of symbol dicts (may be empty if not found)
    """
    cursor = storage.conn.cursor()

    if context_file:
        # Disambiguate with file path
        cursor.execute(
            """
            SELECT id, name, kind, language, file_path, start_line, end_line,
                   signature, doc_comment
            FROM symbols
            WHERE name = ? AND file_path = ?
            LIMIT 1
            """,
            (symbol_name, context_file),
        )
    else:
        # Find all symbols with this name
        cursor.execute(
            """
            SELECT id, name, kind, language, file_path, start_line, end_line,
                   signature, doc_comment
            FROM symbols
            WHERE name = ?
            """,
            (symbol_name,),
        )

    rows = cursor.fetchall()

    symbols = []
    for row in rows:
        symbols.append(
            {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "language": row[3],
                "file_path": row[4],
                "start_line": row[5],
                "end_line": row[6],
                "signature": row[7],
                "doc_comment": row[8],
            }
        )

    return symbols


def _find_variant_matches(
    storage: StorageManager,
    symbol_name: str,
    variant_names: set[str],
    visited: set[str],
    direction: TraceDirection,
) -> list[tuple[dict[str, Any], str, str]]:
    """
    Find symbols using naming variant matching.

    This enables cross-language tracing:
    - TypeScript UserService → Python user_service
    - Python User → SQL users
    - C# IUser → Python user

    Args:
        storage: StorageManager instance
        symbol_name: Original symbol name
        variant_names: Set of all naming variants to try
        visited: Set of visited symbol IDs
        direction: Trace direction (for relationship queries)

    Returns:
        List of (symbol_dict, relationship_kind, match_type) tuples
    """
    cursor = storage.conn.cursor()
    results = []

    # Search for symbols matching any of the variants
    # Build a query with IN clause for efficiency
    placeholders = ",".join("?" * len(variant_names))

    # Find symbols with names matching our variants
    cursor.execute(
        f"""
        SELECT id, name, kind, language, file_path, start_line, end_line,
               signature, doc_comment
        FROM symbols
        WHERE name IN ({placeholders})
        """,
        tuple(variant_names),
    )

    variant_symbols = {}
    for row in cursor.fetchall():
        symbol_id = row[0]
        if symbol_id not in visited:
            variant_symbols[symbol_id] = {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "language": row[3],
                "file_path": row[4],
                "start_line": row[5],
                "end_line": row[6],
                "signature": row[7],
                "doc_comment": row[8],
            }

    # Now check if any of these variant symbols have relationships
    # that could be cross-language connections
    for symbol_id, symbol_dict in variant_symbols.items():
        # Heuristic: if the symbol is in a different language than the original,
        # it's likely a cross-language connection
        # Mark these as "variant" matches with "Reference" relationship

        # For now, add them as potential cross-language references
        # A more sophisticated approach would check for actual import/usage patterns
        results.append((symbol_dict, "Reference", "variant"))

        # Limit results to prevent explosion
        if len(results) >= 10:
            break

    return results


def _compute_semantic_similarity(name1: str, name2: str, embeddings) -> float:
    """
    Compute semantic similarity between two symbol names using embeddings.

    Args:
        name1: First symbol name
        name2: Second symbol name
        embeddings: EmbeddingManager instance

    Returns:
        Cosine similarity score (0.0 to 1.0)
    """
    try:
        import numpy as np

        # Generate embeddings for both names
        vec1 = embeddings.embed_query(name1)
        vec2 = embeddings.embed_query(name2)

        # Compute cosine similarity (vectors should already be normalized)
        similarity = float(np.dot(vec1, vec2))

        return similarity
    except Exception:
        # If embedding fails, return 0 (no match)
        return 0.0


def semantic_neighbors(
    storage: StorageManager,
    vector_store,
    embeddings,
    symbol: dict[str, Any],
    limit: int = 8,
    threshold: float = 0.7,
    cross_language_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Find semantically similar symbols using vector search.

    This is TRUE semantic discovery - finds connections WITHOUT requiring
    pre-existing database relationships. This is what enables cross-language
    tracing for cases like:
    - "authenticate" (Python) → "verifyCredentials" (TypeScript)
    - "fetchUserData" (JS) → "get_user_info" (Python)

    Unlike _compute_semantic_similarity which only compares two names,
    this function searches the entire vector index for similar symbols.

    Args:
        storage: StorageManager for symbol lookups
        vector_store: VectorStore with indexed symbol embeddings
        embeddings: EmbeddingManager for generating query embeddings
        symbol: Source symbol dict to find neighbors for
        limit: Maximum number of results (default: 8)
        threshold: Minimum similarity score (default: 0.7)
        cross_language_only: If True, only return symbols in different languages

    Returns:
        List of SemanticMatch dicts sorted by similarity (highest first)
    """
    import logging
    logger = logging.getLogger("miller.trace")

    if vector_store is None:
        logger.debug("Semantic discovery disabled - no vector store provided")
        return []

    if embeddings is None:
        logger.debug("Semantic discovery disabled - no embeddings manager provided")
        return []

    # Build searchable text for the source symbol (same format as indexing)
    text_parts = [symbol["name"]]
    if symbol.get("signature"):
        text_parts.append(symbol["signature"])
    if symbol.get("doc_comment"):
        text_parts.append(symbol["doc_comment"])
    searchable_text = " ".join(text_parts)

    # Generate embedding for the source symbol
    try:
        query_vector = embeddings.embed_query(searchable_text)
    except Exception as e:
        logger.debug(f"Failed to embed symbol for semantic search: {e}")
        return []

    # Search vector store for similar symbols
    try:
        # Use LanceDB vector search via the vector store's table
        # Request more results than limit to account for filtering
        fetch_limit = limit * 3 if cross_language_only else limit

        # Access the LanceDB table - handle both VectorStore object and raw table
        if hasattr(vector_store, '_table') and vector_store._table is not None:
            table = vector_store._table
        elif hasattr(vector_store, 'table'):
            table = vector_store.table
        else:
            # Assume it's a raw LanceDB table
            table = vector_store

        search_results = table.search(
            query_vector.tolist()
        ).limit(fetch_limit).to_list()

    except Exception as e:
        logger.debug(f"Vector search failed: {e}")
        return []

    # Filter and format results
    matches = []
    source_language = symbol.get("language", "")
    source_id = symbol.get("id", "")

    for result in search_results:
        # Skip the source symbol itself
        if result.get("id") == source_id:
            continue

        # Get similarity score from LanceDB
        # LanceDB returns _distance for L2 normalized vectors
        # For L2 normalized vectors: distance ≈ 2*(1 - cosine_similarity)
        # So: similarity = 1 - (distance / 2)
        if "_distance" in result:
            similarity = 1.0 - (result["_distance"] / 2.0)
        elif "score" in result:
            similarity = result["score"]
        elif "_score" in result:
            similarity = result["_score"]
        else:
            similarity = 0.5  # Default if no score available

        # Skip if below threshold
        if similarity < threshold:
            continue

        result_language = result.get("language", "")

        # Apply cross-language filter
        if cross_language_only and result_language == source_language:
            continue

        # Build match dict
        match = {
            "symbol_id": result.get("id", ""),
            "name": result.get("name", ""),
            "kind": result.get("kind", ""),
            "language": result_language,
            "file_path": result.get("file_path", ""),
            "line": result.get("start_line", 0),
            "similarity": similarity,
            "relationship_kind": "Call",  # Default for semantic bridges
            "signature": result.get("signature"),
            "doc_comment": result.get("doc_comment"),
        }
        matches.append(match)

        # Stop if we have enough
        if len(matches) >= limit:
            break

    # Sort by similarity (highest first)
    matches.sort(key=lambda x: x["similarity"], reverse=True)

    logger.debug(
        f"Semantic discovery found {len(matches)} cross-language neighbors "
        f"for '{symbol['name']}' (threshold={threshold})"
    )

    return matches


