"""Symbol filtering logic - target, semantic, and limit."""

from typing import Optional
import numpy as np
from .hierarchy import build_parent_to_children


def apply_target_filter(symbols: list, target: str) -> list:
    """Filter symbols by target name (case-insensitive partial matching).

    Returns symbols matching the target AND their children (up to max_depth already applied).
    """
    if not target:
        return symbols

    target_lower = target.lower()
    matching_indices = set()

    # First pass: Find all symbols that match the target
    for idx, symbol in enumerate(symbols):
        symbol_name = getattr(symbol, "name", "")
        if target_lower in symbol_name.lower():
            matching_indices.add(idx)

    # Second pass: Include children of matching symbols
    parent_to_children = build_parent_to_children(symbols)

    def include_children(symbol_idx: int):
        """Recursively include all children of a symbol."""
        matching_indices.add(symbol_idx)
        symbol_id = getattr(symbols[symbol_idx], "id", None)
        if symbol_id and symbol_id in parent_to_children:
            for child_idx in parent_to_children[symbol_id]:
                include_children(child_idx)

    # Build final set including all children
    initial_matches = list(matching_indices)
    for idx in initial_matches:
        include_children(idx)

    # Return in original order
    result_indices = sorted(matching_indices)
    return [symbols[idx] for idx in result_indices]


def apply_limit(symbols: list, limit: Optional[int]) -> tuple[list, bool]:
    """Apply limit to symbols, preserving hierarchy.

    Returns (limited_symbols, was_truncated).
    """
    if limit is None or len(symbols) <= limit:
        return symbols, False

    # Simple truncation for now (preserve hierarchy in future enhancement)
    return symbols[:limit], True


def compute_relevance_scores(
    symbols: list,
    target: str,
    embedding_manager
) -> list[tuple[int, float]]:
    """
    Compute relevance scores for symbols based on target query.

    Uses a hybrid approach:
    1. Exact match bonus (1.0 score)
    2. Partial/substring match bonus (0.75 base score)
    3. Semantic similarity via embeddings (0.0-1.0 range)

    Args:
        symbols: List of symbol objects
        target: Target query string
        embedding_manager: EmbeddingManager instance for computing embeddings

    Returns:
        List of (symbol_index, relevance_score) tuples
    """
    if not symbols:
        return []

    target_lower = target.lower()
    scores = []

    # Embed target query
    target_embedding = embedding_manager.embed_query(target)

    # Embed all symbols (includes name + signature + doc_comment)
    symbol_embeddings = embedding_manager.embed_batch(symbols)

    for idx, symbol in enumerate(symbols):
        symbol_name = getattr(symbol, "name", "").lower()

        # Strategy 1: Exact match (highest priority)
        if symbol_name == target_lower:
            score = 1.0
        # Strategy 2: Partial/substring match (high priority)
        elif target_lower in symbol_name:
            # Partial match gets high score, but less than exact
            score = 0.75
        else:
            # Strategy 3: Semantic similarity via embeddings
            # Compute cosine similarity (embeddings are already L2-normalized)
            symbol_emb = symbol_embeddings[idx]
            cosine_sim = float(np.dot(target_embedding, symbol_emb))

            # Boost slightly to prefer semantic matches over random symbols
            score = max(0.0, cosine_sim)

        scores.append((idx, score))

    return scores


def apply_semantic_filtering(
    symbols: list,
    target: str,
    embedding_manager
) -> tuple[list, list[float]]:
    """
    Apply semantic filtering and ranking to symbols based on target.

    Uses tiered filtering:
    - Exact/partial matches (substring): threshold 0.3
    - Pure semantic matches (no substring): threshold 0.60

    Returns matching symbols AND their children (Phase 1 behavior preserved).

    Args:
        symbols: List of symbol objects
        target: Target query string
        embedding_manager: EmbeddingManager instance

    Returns:
        Tuple of (filtered_symbols, relevance_scores) sorted by relevance
    """
    # Compute relevance scores
    scores = compute_relevance_scores(symbols, target, embedding_manager)

    target_lower = target.lower()
    matching_indices = set()

    # First pass: Find symbols that match the target (above threshold)
    for idx, score in scores:
        symbol_name = getattr(symbols[idx], "name", "").lower()

        # Determine threshold based on whether symbol contains target substring
        if target_lower in symbol_name:
            # Substring match - use lenient threshold
            threshold = 0.3
        else:
            # Pure semantic match - use moderate threshold (balance precision/recall)
            threshold = 0.60

        if score >= threshold:
            matching_indices.add(idx)

    # Second pass: Include children of matching symbols (Phase 1 behavior)
    parent_to_children = build_parent_to_children(symbols)

    def include_children(symbol_idx: int):
        """Recursively include all children of a symbol."""
        matching_indices.add(symbol_idx)
        symbol_id = getattr(symbols[symbol_idx], "id", None)
        if symbol_id and symbol_id in parent_to_children:
            for child_idx in parent_to_children[symbol_id]:
                include_children(child_idx)

    # Build final set including all children
    initial_matches = list(matching_indices)
    for idx in initial_matches:
        include_children(idx)

    # Sort by relevance (descending), using original scores
    score_dict = {idx: score for idx, score in scores}
    filtered_indices = sorted(matching_indices, key=lambda idx: score_dict.get(idx, 0.0), reverse=True)

    # Extract filtered symbols and scores
    filtered_symbols = [symbols[idx] for idx in filtered_indices]
    relevance_scores = [score_dict.get(idx, 0.0) for idx in filtered_indices]

    return filtered_symbols, relevance_scores
