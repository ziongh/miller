"""Semantic analysis - embeddings, importance, cross-language variants."""

from typing import Any
import numpy as np
from .naming import generate_naming_variants


def find_related_symbols(symbols: list, embedding_manager, top_n: int = 5) -> dict[str, list[dict]]:
    """
    Find related symbols using embedding similarity.

    For each symbol, finds the top-N most similar symbols (excluding itself).

    Args:
        symbols: List of symbol objects
        embedding_manager: EmbeddingManager instance for computing embeddings
        top_n: Maximum number of related symbols to return per symbol

    Returns:
        Dict mapping symbol_id -> list of related symbols with similarity scores
        Each related symbol is: {"name": str, "similarity": float}
    """
    if not symbols or not embedding_manager or len(symbols) < 2:
        # Need at least 2 symbols to find relationships
        return {}

    try:
        # Compute embeddings for all symbols
        symbol_embeddings = embedding_manager.embed_batch(symbols)

        if symbol_embeddings is None or len(symbol_embeddings) == 0:
            return {}

        related_map = {}

        # For each symbol, find most similar other symbols
        for idx, symbol in enumerate(symbols):
            symbol_id = getattr(symbol, "id", "")
            if not symbol_id:
                continue

            # Get this symbol's embedding
            query_embedding = symbol_embeddings[idx]

            # Compute similarity with all other symbols
            similarities = []
            for other_idx, other_symbol in enumerate(symbols):
                if idx == other_idx:
                    # Skip self
                    continue

                other_embedding = symbol_embeddings[other_idx]

                # Compute cosine similarity (embeddings are already L2-normalized)
                similarity = float(np.dot(query_embedding, other_embedding))

                similarities.append((other_idx, similarity))

            # Sort by similarity (descending) and take top N
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_similar = similarities[:top_n]

            # Build related symbols list
            related = []
            for other_idx, similarity in top_similar:
                other_name = getattr(symbols[other_idx], "name", "")
                if other_name:
                    related.append({
                        "name": other_name,
                        "similarity": similarity
                    })

            related_map[symbol_id] = related

    except Exception:
        # If embedding computation fails, return empty
        return {}

    return related_map


def find_cross_language_variants(
    symbols: list,
    storage_manager,
    current_language: str
) -> dict[str, dict]:
    """
    Find cross-language naming variants for symbols.

    For each symbol, generates naming variants (snake_case, camelCase, etc.)
    and queries the database for symbols with those names in OTHER languages.

    Args:
        symbols: List of symbol objects
        storage_manager: StorageManager instance to query database
        current_language: Language of the current file (to exclude from results)

    Returns:
        Dict mapping symbol_id -> cross_language_hints dict
        Each hints dict contains:
            - has_variants: bool
            - variants_count: int
            - languages: list[str] (languages where variants are found, excluding current)
    """
    if not storage_manager or not symbols:
        # Return empty hints for all symbols
        return {
            getattr(sym, "id", ""): {
                "has_variants": False,
                "variants_count": 0,
                "languages": []
            }
            for sym in symbols
        }

    variants_map = {}

    try:
        for symbol in symbols:
            symbol_id = getattr(symbol, "id", "")
            symbol_name = getattr(symbol, "name", "")

            if not symbol_name:
                variants_map[symbol_id] = {
                    "has_variants": False,
                    "variants_count": 0,
                    "languages": []
                }
                continue

            # Generate naming variants
            variants = generate_naming_variants(symbol_name)

            # Query database for symbols with variant names
            # Exclude current language
            found_languages = set()

            if variants:
                # Build query to find symbols with any of the variant names
                placeholders = ",".join("?" * len(variants))
                query = f"""
                    SELECT DISTINCT language
                    FROM symbols
                    WHERE name IN ({placeholders})
                    AND language != ?
                """

                cursor = storage_manager.conn.cursor()
                cursor.execute(query, list(variants) + [current_language])
                rows = cursor.fetchall()

                for row in rows:
                    found_languages.add(row[0])

            variants_map[symbol_id] = {
                "has_variants": len(found_languages) > 0,
                "variants_count": len(found_languages),
                "languages": sorted(list(found_languages))
            }

    except Exception:
        # If query fails, return empty hints for all symbols
        return {
            getattr(sym, "id", ""): {
                "has_variants": False,
                "variants_count": 0,
                "languages": []
            }
            for sym in symbols
        }

    return variants_map


def calculate_importance_scores(symbols: list, storage_manager) -> tuple[dict[str, float], dict[str, bool]]:
    """
    Calculate symbol importance using PageRank on the call graph.

    Uses relationships table to build a directed graph and computes PageRank scores.
    Also detects entry points (high in-degree, low out-degree).

    Args:
        symbols: List of symbol objects
        storage_manager: StorageManager instance to query relationships

    Returns:
        Tuple of (importance_scores dict, is_entry_point dict)
        - importance_scores: symbol_id -> PageRank score (0.0 to 1.0)
        - is_entry_point: symbol_id -> bool (True if entry point)
    """
    if not storage_manager or not symbols:
        # Return default values for all symbols
        default_score = 1.0 / max(len(symbols), 1)  # Equal distribution
        return (
            {getattr(sym, "id", ""): default_score for sym in symbols},
            {getattr(sym, "id", ""): False for sym in symbols}
        )

    try:
        import networkx as nx

        # Build call graph from relationships table
        symbol_ids = [getattr(sym, "id", None) for sym in symbols]
        symbol_ids = [sid for sid in symbol_ids if sid]

        if not symbol_ids:
            return ({}, {})

        # Query relationships for these symbols
        placeholders = ",".join("?" * len(symbol_ids))
        query = f"""
            SELECT from_symbol_id, to_symbol_id
            FROM relationships
            WHERE from_symbol_id IN ({placeholders})
            OR to_symbol_id IN ({placeholders})
        """

        cursor = storage_manager.conn.cursor()
        cursor.execute(query, symbol_ids + symbol_ids)
        edges = cursor.fetchall()

        # Build directed graph
        G = nx.DiGraph()

        # Add all symbols as nodes (even if no edges)
        for sid in symbol_ids:
            G.add_node(sid)

        # Add edges from relationships
        for from_id, to_id in edges:
            if from_id and to_id:
                G.add_edge(from_id, to_id)

        # Compute PageRank scores
        if len(G.nodes()) > 0:
            pagerank_scores = nx.pagerank(G, alpha=0.85)
        else:
            pagerank_scores = {}

        # Normalize scores to 0-1 range
        if pagerank_scores:
            max_score = max(pagerank_scores.values())
            min_score = min(pagerank_scores.values())
            score_range = max_score - min_score

            if score_range > 0:
                normalized_scores = {
                    node: (score - min_score) / score_range
                    for node, score in pagerank_scores.items()
                }
            else:
                # All scores equal, use uniform distribution
                normalized_scores = {node: 0.5 for node in pagerank_scores}
        else:
            # No graph, use default
            default_score = 1.0 / max(len(symbol_ids), 1)
            normalized_scores = {sid: default_score for sid in symbol_ids}

        # Detect entry points (high in-degree, low out-degree)
        entry_points = {}
        for node in G.nodes():
            in_degree = G.in_degree(node)
            out_degree = G.out_degree(node)

            # Entry point criteria: called by at least 2 others, calls fewer than it's called by
            is_entry = in_degree >= 2 and out_degree < in_degree
            entry_points[node] = is_entry

        return (normalized_scores, entry_points)

    except Exception:
        # If anything fails, return default values
        default_score = 1.0 / max(len(symbols), 1)
        return (
            {getattr(sym, "id", ""): default_score for sym in symbols},
            {getattr(sym, "id", ""): False for sym in symbols}
        )


def get_reference_counts(symbols: list, storage_manager) -> dict[str, int]:
    """
    Get reference counts for symbols from the relationships table.

    Args:
        symbols: List of symbol objects with .id attribute
        storage_manager: StorageManager instance to query relationships

    Returns:
        Dict mapping symbol_id -> reference_count
    """
    if not storage_manager:
        # No storage available, return empty counts
        return {}

    reference_counts = {}

    try:
        # Get all symbol IDs
        symbol_ids = [getattr(sym, "id", None) for sym in symbols]
        symbol_ids = [sid for sid in symbol_ids if sid]  # Filter out None

        if not symbol_ids:
            return {}

        # Query relationships table for reference counts
        # Count how many times each symbol appears as to_symbol_id
        placeholders = ",".join("?" * len(symbol_ids))
        query = f"""
            SELECT to_symbol_id, COUNT(*) as ref_count
            FROM relationships
            WHERE to_symbol_id IN ({placeholders})
            GROUP BY to_symbol_id
        """

        cursor = storage_manager.conn.execute(query, symbol_ids)
        for row in cursor:
            reference_counts[row[0]] = row[1]

    except Exception:
        # If query fails (e.g., relationships table doesn't exist yet), return empty
        pass

    return reference_counts
