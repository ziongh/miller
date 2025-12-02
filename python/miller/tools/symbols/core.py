"""Core symbol retrieval orchestration."""

from typing import Any, Optional
from pathlib import Path

from .hierarchy import apply_max_depth_filter
from .filters import apply_target_filter, apply_semantic_filtering, apply_limit
from .formatters import (
    extract_code_bodies,
    symbol_to_dict,
    calculate_usage_frequency,
    calculate_doc_quality,
    calculate_importance_tier,
)
from .analysis import (
    get_reference_counts,
    find_related_symbols,
    find_cross_language_variants,
    calculate_importance_scores,
)


async def get_symbols_enhanced(
    file_path: str,
    mode: str = "structure",
    max_depth: int = 1,
    target: Optional[str] = None,
    limit: Optional[int] = None,
    workspace: str = "primary",
    workspace_storage: Optional[Any] = None
) -> list[dict[str, Any]]:
    """
    Get file structure with enhanced filtering and modes.

    Args:
        file_path: Path to file (relative or absolute, resolved by caller)
        mode: Reading mode - "structure" (default), "minimal", or "full"
        max_depth: Maximum nesting depth (0=top-level only, 1=include direct children, etc.)
        target: Filter to symbols matching this name (case-insensitive partial match)
        limit: Maximum number of symbols to return
        workspace: Workspace to query ("primary" or workspace_id)
        workspace_storage: Optional workspace-specific StorageManager for metadata lookups

    Returns:
        List of symbol dictionaries with metadata based on mode
    """
    # Import miller_core from server module (it handles the Rust binding import)
    import miller.server as server

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

        # Use workspace-specific storage if provided, otherwise fall back to global
        active_storage = workspace_storage if workspace_storage is not None else server.storage

        # 5. Get reference counts from relationships table (Task 2.2)
        reference_counts = {}
        try:
            if active_storage is not None:
                reference_counts = get_reference_counts(symbols, active_storage)
        except Exception:
            # If storage unavailable, continue without reference counts
            pass

        # 6. Find related symbols using embeddings (Task 2.4)
        related_symbols_map = {}
        try:
            embedding_mgr = server.embeddings
            if embedding_mgr is not None:
                related_symbols_map = find_related_symbols(symbols, embedding_mgr)
        except Exception:
            # If embeddings unavailable, continue without related symbols
            pass

        # 7. Find cross-language variants (Task 2.5)
        cross_language_map = {}
        try:
            if active_storage is not None:
                cross_language_map = find_cross_language_variants(symbols, active_storage, language)
        except Exception:
            # If storage unavailable, continue without cross-language hints
            pass

        # 8. Calculate symbol importance using PageRank (Task 2.6)
        importance_scores = {}
        entry_points = {}
        try:
            if active_storage is not None:
                importance_scores, entry_points = calculate_importance_scores(symbols, active_storage)
        except Exception:
            # If calculation fails, use defaults
            pass

        # Convert to dicts
        result_dicts = []
        for idx, sym in enumerate(symbols):
            sym_dict = symbol_to_dict(sym, code_bodies, file_path=str(path))

            # Add relevance_score if available (Phase 2 Task 2.1)
            if relevance_scores is not None and idx < len(relevance_scores):
                sym_dict["relevance_score"] = relevance_scores[idx]

            # Add usage frequency indicators (Phase 2 Task 2.2)
            symbol_id = getattr(sym, "id", "")
            ref_count = reference_counts.get(symbol_id, 0)
            sym_dict["references_count"] = ref_count
            sym_dict["usage_frequency"] = calculate_usage_frequency(ref_count)

            # Add documentation quality indicators (Phase 2 Task 2.3)
            doc_comment = sym_dict.get("doc_comment")
            sym_dict["has_docs"] = bool(doc_comment and doc_comment.strip())
            sym_dict["doc_quality"] = calculate_doc_quality(doc_comment)

            # Add related symbols suggestions (Phase 2 Task 2.4)
            related_symbols = related_symbols_map.get(symbol_id, [])
            sym_dict["related_symbols"] = related_symbols

            # Add cross-language variant hints (Phase 2 Task 2.5)
            cross_lang_hints = cross_language_map.get(symbol_id, {
                "has_variants": False,
                "variants_count": 0,
                "languages": []
            })
            sym_dict["cross_language_hints"] = cross_lang_hints

            # Add symbol importance ranking (Phase 2 Task 2.6)
            importance_score = importance_scores.get(symbol_id, 0.5)  # Default to medium
            sym_dict["importance_score"] = importance_score
            sym_dict["importance"] = calculate_importance_tier(importance_score)
            sym_dict["is_entry_point"] = entry_points.get(symbol_id, False)

            result_dicts.append(sym_dict)

        return result_dicts

    except Exception as e:
        import logging
        logger = logging.getLogger("miller.tools.symbols")
        logger.exception(f"Error in get_symbols_enhanced: {e}")
        return []
