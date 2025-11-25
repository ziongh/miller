"""
Main call tracing entry point.
"""

import time
from collections import defaultdict
from typing import Optional
from miller.storage import StorageManager
from miller.tools.trace_types import (
    DEFAULT_MAX_DEPTH,
    MAX_ALLOWED_DEPTH,
    TraceDirection,
    TracePath,
)
from .search import _find_symbols, _find_variant_matches, _compute_semantic_similarity
from .builder import _build_trace_node, _find_related_symbols
from .utils import _count_nodes, _get_max_depth, _format_as_tree


async def trace_call_path(
    storage: StorageManager,
    symbol_name: str,
    direction: TraceDirection = "downstream",
    max_depth: int = DEFAULT_MAX_DEPTH,
    context_file: Optional[str] = None,
    output_format: str = "json",
    workspace: str = "primary",
    enable_semantic: bool = True,  # NOW DEFAULT TRUE - uses vector search for cross-language discovery
    embeddings=None,
    vector_store=None,  # Pass vector store for TRUE semantic discovery
) -> dict[str, Any] | str:
    """
    Trace call paths across language boundaries using naming variants.

    Args:
        storage: StorageManager instance
        symbol_name: Symbol to trace from
        direction: "upstream" (callers), "downstream" (callees), or "both"
        max_depth: Maximum depth to traverse (1-10)
        context_file: Optional file path to disambiguate symbols
        output_format: "json" or "tree"
        workspace: Workspace identifier (currently unused, for future multi-workspace)
        enable_semantic: Whether to use semantic similarity fallback (future feature)

    Returns:
        TracePath dict if output_format="json", formatted string if "tree"

    Raises:
        ValueError: If max_depth is invalid or direction is invalid
    """
    start_time = time.time()

    # Initialize embeddings if semantic matching is enabled
    if enable_semantic and embeddings is None:
        from miller.embeddings import EmbeddingManager
        embeddings = EmbeddingManager()

    # Validate inputs
    if max_depth < 1 or max_depth > MAX_ALLOWED_DEPTH:
        raise ValueError(
            f"max_depth must be between 1 and {MAX_ALLOWED_DEPTH}, got {max_depth}"
        )

    if direction not in ["upstream", "downstream", "both"]:
        raise ValueError(
            f"direction must be 'upstream', 'downstream', or 'both', got '{direction}'"
        )

    # Find starting symbol(s)
    symbols = _find_symbols(storage, symbol_name, context_file)

    if not symbols:
        # Symbol not found - return empty result
        execution_time = (time.time() - start_time) * 1000
        return {
            "query_symbol": symbol_name,
            "direction": direction,
            "max_depth": max_depth,
            "total_nodes": 0,
            "error": f"Symbol '{symbol_name}' not found in workspace '{workspace}'",
            "execution_time_ms": execution_time,
        }

    # For simplicity, use first matching symbol (TODO: handle multiple matches)
    start_symbol = symbols[0]

    # Build trace tree
    visited = set()  # Track visited symbols to prevent cycles
    languages_found = set()
    match_types_count = defaultdict(int)
    relationship_kinds_count = defaultdict(int)
    nodes_visited_ref = [0]  # Use list to modify in place in recursive function
    cycles_detected_ref = [0]  # Track number of cycles encountered

    root = _build_trace_node(
        storage=storage,
        symbol=start_symbol,
        direction=direction,
        current_depth=0,
        max_depth=max_depth,
        visited=visited,
        languages_found=languages_found,
        match_types_count=match_types_count,
        relationship_kinds_count=relationship_kinds_count,
        nodes_visited_ref=nodes_visited_ref,
        cycles_detected_ref=cycles_detected_ref,
        enable_semantic=enable_semantic,
        embeddings=embeddings,
        vector_store=vector_store,  # NEW: For true semantic discovery
    )

    # Count total nodes
    total_nodes = _count_nodes(root)

    # Check if truncated
    max_depth_reached = _get_max_depth(root)
    truncated = max_depth_reached >= max_depth

    execution_time = (time.time() - start_time) * 1000

    result: TracePath = {
        "query_symbol": symbol_name,
        "direction": direction,
        "max_depth": max_depth,
        "root": root,
        "total_nodes": total_nodes,
        "max_depth_reached": max_depth_reached,
        "truncated": truncated,
        "languages_found": sorted(languages_found),
        "match_types": dict(match_types_count),
        "relationship_kinds": dict(relationship_kinds_count),
        "execution_time_ms": execution_time,
        "nodes_visited": nodes_visited_ref[0],
        "cycles_detected": cycles_detected_ref[0],
    }

    if output_format == "tree":
        return _format_as_tree(root, max_depth=max_depth, max_depth_reached=max_depth_reached)
    else:
        return result


