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


