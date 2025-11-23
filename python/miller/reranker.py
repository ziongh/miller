"""Cross-encoder re-ranking for improved search relevance.

This module provides re-ranking capabilities using cross-encoder models,
which score query-candidate pairs together for better semantic understanding
than bi-encoder (embedding) approaches.

Key features:
- Lazy model loading (doesn't block server startup)
- Graceful fallback on errors
- Configurable model selection via environment variable
"""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Default model - fast and good quality
DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"

# Alternative models (can be set via MILLER_RERANKER_MODEL env var):
# - "BAAI/bge-reranker-base" (278M params, higher quality)
# - "BAAI/bge-reranker-v2-m3" (multilingual, best quality)
# - "BAAI/bge-reranker-large" (560M params, slower but accurate)


class ReRanker:
    """Cross-encoder re-ranker for search results.

    Uses lazy loading to avoid blocking server startup. The model is only
    loaded when first needed (on first call to score() or rerank_results()).

    Example:
        reranker = ReRanker()
        reranked = reranker.rerank_results("auth logic", search_results)
    """

    _model = None
    _initialized = False
    _load_failed = False

    def __init__(self, model_name: str | None = None):
        """Initialize ReRanker.

        Args:
            model_name: Model to use. Defaults to env var MILLER_RERANKER_MODEL
                       or DEFAULT_MODEL if not set.
        """
        self.model_name = model_name or os.environ.get(
            "MILLER_RERANKER_MODEL", DEFAULT_MODEL
        )

    def _ensure_model_loaded(self) -> bool:
        """Lazily load the cross-encoder model.

        Returns:
            True if model is available, False otherwise.
        """
        if ReRanker._initialized:
            return ReRanker._model is not None

        if ReRanker._load_failed:
            return False

        try:
            # Lazy import to avoid blocking startup
            from sentence_transformers import CrossEncoder

            logger.info(f"Loading cross-encoder model: {self.model_name}")
            ReRanker._model = CrossEncoder(self.model_name)
            ReRanker._initialized = True
            logger.info("Cross-encoder model loaded successfully")
            return True

        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Re-ranking disabled. Install with: pip install sentence-transformers"
            )
            ReRanker._load_failed = True
            ReRanker._initialized = True
            return False

        except Exception as e:
            logger.warning(f"Failed to load cross-encoder model: {e}")
            ReRanker._load_failed = True
            ReRanker._initialized = True
            return False

    def is_available(self) -> bool:
        """Check if re-ranking is available.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        return self._ensure_model_loaded()

    def _format_candidate(self, candidate: dict[str, Any]) -> str:
        """Format a candidate for scoring.

        Creates a text representation combining name, signature, and doc_comment
        for the cross-encoder to evaluate against the query.

        Args:
            candidate: Search result dict with name, signature, etc.

        Returns:
            Text representation for scoring.
        """
        parts = []

        # Name is most important
        if name := candidate.get("name"):
            parts.append(name)

        # Signature provides type info and context
        if signature := candidate.get("signature"):
            parts.append(signature)

        # Doc comment provides semantic context
        if doc := candidate.get("doc_comment"):
            # Truncate long docs to avoid overwhelming the model
            doc_truncated = doc[:500] if len(doc) > 500 else doc
            parts.append(doc_truncated)

        return " ".join(parts)

    def score(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> list[float]:
        """Score query-candidate pairs using cross-encoder.

        Args:
            query: Search query string.
            candidates: List of candidate dicts (search results).

        Returns:
            List of scores (one per candidate), higher = more relevant.
            Returns empty list if candidates is empty.

        Raises:
            RuntimeError: If model not available and called directly.
        """
        if not candidates:
            return []

        if not self._ensure_model_loaded():
            raise RuntimeError(
                "Cross-encoder model not available. "
                "Install sentence-transformers or check logs for errors."
            )

        # Format candidates for scoring
        candidate_texts = [self._format_candidate(c) for c in candidates]

        # Create query-candidate pairs for cross-encoder
        pairs = [[query, text] for text in candidate_texts]

        # Score all pairs in batch
        scores = ReRanker._model.predict(pairs)

        # Convert numpy array to list of floats
        return [float(s) for s in scores]

    def rerank_results(
        self,
        query: str,
        results: list[dict[str, Any]],
        fallback_on_error: bool = True,
    ) -> list[dict[str, Any]]:
        """Re-rank search results using cross-encoder scores.

        This is the main entry point for re-ranking. It scores all results,
        updates their scores, and returns them sorted by the new scores.

        Args:
            query: Search query string.
            results: List of search result dicts.
            fallback_on_error: If True, return original results on error.
                              If False, propagate exceptions.

        Returns:
            Results sorted by cross-encoder score (highest first).
            Original results unchanged if error and fallback_on_error=True.
        """
        if not results:
            return results

        try:
            # Get cross-encoder scores
            scores = self.score(query, results)

            # Update scores and create new list (don't mutate original)
            reranked = []
            for result, new_score in zip(results, scores):
                updated = result.copy()
                updated["score"] = new_score
                reranked.append(updated)

            # Sort by score descending
            reranked.sort(key=lambda x: x.get("score", 0.0), reverse=True)

            return reranked

        except Exception as e:
            if fallback_on_error:
                logger.warning(f"Re-ranking failed, using original order: {e}")
                return results
            raise


# Singleton instance for convenience
_default_reranker: ReRanker | None = None


def get_reranker() -> ReRanker:
    """Get the default ReRanker instance.

    Returns:
        Singleton ReRanker instance.
    """
    global _default_reranker
    if _default_reranker is None:
        _default_reranker = ReRanker()
    return _default_reranker


def rerank_search_results(
    query: str,
    results: list[dict[str, Any]],
    enabled: bool = True,
) -> list[dict[str, Any]]:
    """Convenience function to re-rank search results.

    This is the recommended entry point for integrating re-ranking into
    search tools. It handles all edge cases and provides graceful fallback.

    Args:
        query: Search query string.
        results: Search results to re-rank.
        enabled: If False, return results unchanged (skip re-ranking).

    Returns:
        Re-ranked results, or original results if disabled or on error.
    """
    if not enabled or not results:
        return results

    reranker = get_reranker()

    # Check if model is available before attempting
    if not reranker.is_available():
        logger.debug("Re-ranker not available, returning original results")
        return results

    return reranker.rerank_results(query, results, fallback_on_error=True)
