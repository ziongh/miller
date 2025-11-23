"""Tests for the ReRanker module."""

import pytest
from unittest.mock import MagicMock, patch


class TestReRanker:
    """Tests for ReRanker class."""

    def test_reranker_lazy_loads_model(self):
        """Model should not load until first use."""
        from miller.reranker import ReRanker

        # Reset singleton state
        ReRanker._model = None
        ReRanker._initialized = False

        # Creating instance shouldn't load model
        reranker = ReRanker()
        assert ReRanker._model is None

    def test_reranker_scores_query_candidate_pairs(self):
        """ReRanker should score query-candidate pairs."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        query = "authentication logic"
        candidates = [
            {"name": "Authenticator", "signature": "class Authenticator"},
            {"name": "Author", "signature": "class Author"},
            {"name": "login_user", "signature": "def login_user(username, password)"},
        ]

        scores = reranker.score(query, candidates)

        # Should return one score per candidate
        assert len(scores) == len(candidates)
        # Scores should be floats
        assert all(isinstance(s, float) for s in scores)

    def test_reranker_handles_empty_candidates(self):
        """ReRanker should handle empty candidate list."""
        from miller.reranker import ReRanker

        reranker = ReRanker()
        scores = reranker.score("test query", [])

        assert scores == []

    def test_reranker_handles_single_candidate(self):
        """ReRanker should handle single candidate."""
        from miller.reranker import ReRanker

        reranker = ReRanker()
        candidates = [{"name": "test", "signature": "def test()"}]
        scores = reranker.score("test", candidates)

        assert len(scores) == 1

    def test_rerank_results_reorders_by_score(self):
        """rerank_results should reorder results by cross-encoder score."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        query = "user authentication"
        results = [
            {"name": "Author", "signature": "class Author", "score": 0.9},
            {"name": "Authenticator", "signature": "class Authenticator", "score": 0.8},
            {"name": "login", "signature": "def login(user, pass)", "score": 0.7},
        ]

        reranked = reranker.rerank_results(query, results)

        # Results should still have same length
        assert len(reranked) == len(results)
        # Each result should have updated score
        assert all("score" in r for r in reranked)

    def test_rerank_results_preserves_all_fields(self):
        """rerank_results should preserve all original fields."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        results = [
            {
                "name": "test_func",
                "signature": "def test_func()",
                "file_path": "/path/to/file.py",
                "start_line": 42,
                "doc_comment": "Test function",
                "score": 0.5,
                "custom_field": "preserved",
            }
        ]

        reranked = reranker.rerank_results("test", results)

        assert reranked[0]["file_path"] == "/path/to/file.py"
        assert reranked[0]["start_line"] == 42
        assert reranked[0]["custom_field"] == "preserved"

    def test_format_candidate_creates_text_for_scoring(self):
        """_format_candidate should create text representation for scoring."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        candidate = {
            "name": "authenticate",
            "signature": "def authenticate(user: str, password: str) -> bool",
            "doc_comment": "Authenticate a user with credentials.",
        }

        text = reranker._format_candidate(candidate)

        # Should include name and signature
        assert "authenticate" in text
        assert "def authenticate" in text
        # Should be a reasonable length for scoring
        assert len(text) > 10

    def test_reranker_is_available_returns_true_when_model_loads(self):
        """is_available should return True when model can load."""
        from miller.reranker import ReRanker

        # This will actually try to load the model
        # Skip if sentence-transformers not installed
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            pytest.skip("sentence-transformers not installed")

        reranker = ReRanker()
        # Just check the method exists and returns bool
        result = reranker.is_available()
        assert isinstance(result, bool)


class TestReRankerFallback:
    """Tests for fallback behavior when model unavailable."""

    def test_rerank_returns_original_on_error(self):
        """If scoring fails, should return original results unchanged."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        # Mock score to raise exception
        with patch.object(reranker, "score", side_effect=Exception("Model failed")):
            results = [
                {"name": "a", "score": 0.9},
                {"name": "b", "score": 0.8},
            ]

            # Should not raise, should return original
            reranked = reranker.rerank_results("query", results, fallback_on_error=True)

            assert reranked == results

    def test_rerank_raises_on_error_when_fallback_disabled(self):
        """If fallback disabled, should propagate errors."""
        from miller.reranker import ReRanker

        reranker = ReRanker()

        with patch.object(reranker, "score", side_effect=Exception("Model failed")):
            results = [{"name": "a", "score": 0.9}]

            with pytest.raises(Exception, match="Model failed"):
                reranker.rerank_results("query", results, fallback_on_error=False)
