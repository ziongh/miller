"""
Symbol overview tools - Miller's enhanced get_symbols implementation

Provides different levels of code context based on reading mode and filtering options.
Better than Julie's implementation with Python/ML enhancements.
"""

from typing import Any, Optional
from pathlib import Path
import numpy as np


def build_parent_to_children(symbols: list) -> dict[str, list[int]]:
    """Build a parent_id -> children indices map for efficient hierarchy navigation."""
    parent_to_children: dict[str, list[int]] = {}

    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id:
            if parent_id not in parent_to_children:
                parent_to_children[parent_id] = []
            parent_to_children[parent_id].append(idx)

    return parent_to_children


def find_top_level_symbols(symbols: list) -> list[int]:
    """Find all top-level symbols (those with no parent)."""
    top_level = []
    for idx, symbol in enumerate(symbols):
        parent_id = getattr(symbol, "parent_id", None)
        if parent_id is None:
            top_level.append(idx)
    return top_level


def collect_symbols_by_depth(
    indices: list[int],
    depth: int,
    max_depth: int,
    all_symbols: list,
    parent_to_children: dict[str, list[int]],
    result: list[int]
):
    """Recursively collect symbols up to maximum depth."""
    if depth > max_depth:
        return

    for idx in indices:
        result.append(idx)

        if depth < max_depth:
            symbol_id = getattr(all_symbols[idx], "id", None)
            if symbol_id and symbol_id in parent_to_children:
                children_indices = parent_to_children[symbol_id]
                collect_symbols_by_depth(
                    children_indices,
                    depth + 1,
                    max_depth,
                    all_symbols,
                    parent_to_children,
                    result
                )


def apply_max_depth_filter(all_symbols: list, max_depth: int) -> list:
    """Apply max_depth filtering to symbols.

    Returns filtered symbols in original order, keeping only those within
    the maximum depth from top-level symbols.
    """
    parent_to_children = build_parent_to_children(all_symbols)
    top_level_indices = find_top_level_symbols(all_symbols)

    indices_to_include = []
    collect_symbols_by_depth(
        top_level_indices,
        0,
        max_depth,
        all_symbols,
        parent_to_children,
        indices_to_include
    )

    # Preserve original order
    indices_to_include.sort()

    return [all_symbols[idx] for idx in indices_to_include]


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


def extract_code_bodies(
    symbols: list,
    file_path: str,
    mode: str
) -> dict[str, str]:
    """Extract code bodies for symbols based on mode parameter.

    Returns a dict mapping symbol.id -> code_body string.

    Modes:
    - "structure": No code bodies (just names and signatures)
    - "minimal": Code bodies for top-level symbols only
    - "full": Code bodies for all symbols
    """
    code_bodies = {}

    if mode == "structure":
        # No code bodies in structure mode
        return code_bodies

    # Read source file for body extraction
    try:
        with open(file_path, "rb") as f:
            source_bytes = f.read()
    except Exception:
        # If file can't be read, return empty dict
        return code_bodies

    # Extract bodies based on mode
    for symbol in symbols:
        should_extract = False

        if mode == "minimal":
            # Only top-level symbols (no parent)
            should_extract = getattr(symbol, "parent_id", None) is None
        elif mode == "full":
            # All symbols
            should_extract = True

        if should_extract:
            start_byte = getattr(symbol, "start_byte", 0)
            end_byte = getattr(symbol, "end_byte", 0)

            if 0 <= start_byte < len(source_bytes) and start_byte < end_byte <= len(source_bytes):
                code_bytes = source_bytes[start_byte:end_byte]
                symbol_id = getattr(symbol, "id", "")
                if symbol_id:
                    code_bodies[symbol_id] = code_bytes.decode("utf-8", errors="replace")

    return code_bodies


def symbol_to_dict(symbol, code_bodies: dict[str, str]) -> dict[str, Any]:
    """Convert a symbol object to a dictionary.

    Args:
        symbol: Symbol object from miller_core
        code_bodies: Dict mapping symbol.id -> code_body string
    """
    # Normalize kind to PascalCase for consistency with Julie
    kind_raw = getattr(symbol, "kind", "")
    kind = kind_raw.capitalize() if kind_raw else ""

    result = {
        "name": getattr(symbol, "name", ""),
        "kind": kind,
        "start_line": getattr(symbol, "start_line", 0),
        "end_line": getattr(symbol, "end_line", 0),
    }

    # Optional fields
    if hasattr(symbol, "signature") and symbol.signature:
        result["signature"] = symbol.signature
    if hasattr(symbol, "doc_comment") and symbol.doc_comment:
        result["doc_comment"] = symbol.doc_comment
    if hasattr(symbol, "parent_id") and symbol.parent_id:
        result["parent_id"] = symbol.parent_id

    # Add code body if available
    symbol_id = getattr(symbol, "id", "")
    if symbol_id and symbol_id in code_bodies:
        result["code_body"] = code_bodies[symbol_id]

    return result


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


async def get_symbols_enhanced(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary"
) -> list[dict[str, Any]]:
    """
    Get file structure with enhanced filtering and modes.

    Args:
        file_path: Path to file (relative or absolute)
        mode: Reading mode - "structure" (default), "minimal", or "full"
        max_depth: Maximum nesting depth (0=top-level only, 1=include direct children, etc.)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)

    Returns:
        List of symbol dictionaries with metadata based on mode
    """
    # Import miller_core from server module (it handles the Rust binding import)
    from miller import server

    path = Path(file_path)

    # Handle nonexistent files
    if not path.exists():
        return []

    # Check if miller_core is available
    if server.miller_core is None:
        return []

    # Read and extract symbols
    try:
        content = path.read_text(encoding="utf-8")
        language = server.miller_core.detect_language(str(path))

        if not language:
            return []

        result = server.miller_core.extract_file(content, language, str(path))
        symbols = list(result.symbols)

        if not symbols:
            return []

        # Apply filters in order
        # 1. Max depth filter
        symbols = apply_max_depth_filter(symbols, max_depth)

        # 2. Target filter with semantic relevance (if specified)
        relevance_scores = None
        if target:
            # Phase 2 enhancement: Use semantic filtering with embeddings
            try:
                embedding_mgr = server.embeddings  # Global embedding manager from server
                if embedding_mgr is not None:
                    # Apply semantic filtering (filters + sorts by relevance)
                    symbols, relevance_scores = apply_semantic_filtering(
                        symbols, target, embedding_mgr
                    )
                else:
                    # Fallback: basic target filtering (Phase 1 behavior)
                    symbols = apply_target_filter(symbols, target)
            except Exception as e:
                # If embeddings fail, fall back to basic filtering
                import logging
                logger = logging.getLogger("miller.tools.symbols")
                logger.warning(f"Semantic filtering failed, falling back to basic: {e}")
                symbols = apply_target_filter(symbols, target)

        # 3. Apply limit
        symbols, was_truncated = apply_limit(symbols, limit)

        # 4. Extract code bodies based on mode (returns dict: id -> code_body)
        code_bodies = extract_code_bodies(symbols, str(path), mode)

        # Convert to dicts
        result_dicts = []
        for idx, sym in enumerate(symbols):
            sym_dict = symbol_to_dict(sym, code_bodies)

            # Add relevance_score if available (Phase 2 enhancement)
            if relevance_scores is not None and idx < len(relevance_scores):
                sym_dict["relevance_score"] = relevance_scores[idx]

            result_dicts.append(sym_dict)

        return result_dicts

    except Exception as e:
        # Debug: print the exception
        import traceback
        traceback.print_exc()
        print(f"Exception in get_symbols_enhanced: {e}")
        return []
