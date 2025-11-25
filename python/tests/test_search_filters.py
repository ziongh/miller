"""
Tests for Search Filters Feature

Following TDD: tests written BEFORE implementation.

Features:
1. Language filter - filter results by programming language
2. File pattern filter - filter results by glob pattern
3. Semantic fallback - when text search returns 0, try semantic
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import fnmatch


class TestLanguageFilter:
    """Test language filter parameter on fast_search."""

    @pytest.fixture
    def mock_search_results(self):
        """Sample search results with mixed languages."""
        return [
            {"id": "1", "name": "UserService", "language": "python", "file_path": "src/user.py", "score": 0.9},
            {"id": "2", "name": "UserController", "language": "typescript", "file_path": "src/user.ts", "score": 0.85},
            {"id": "3", "name": "user_handler", "language": "rust", "file_path": "src/user.rs", "score": 0.8},
            {"id": "4", "name": "UserModel", "language": "python", "file_path": "src/models/user.py", "score": 0.75},
        ]

    def test_filter_by_language_returns_only_matching(self, mock_search_results):
        """Language filter should return only symbols in that language."""
        from miller.tools.search_filters import apply_language_filter

        filtered = apply_language_filter(mock_search_results, "python")

        assert len(filtered) == 2
        assert all(r["language"] == "python" for r in filtered)

    def test_filter_by_language_case_insensitive(self, mock_search_results):
        """Language filter should be case-insensitive."""
        from miller.tools.search_filters import apply_language_filter

        filtered_lower = apply_language_filter(mock_search_results, "python")
        filtered_upper = apply_language_filter(mock_search_results, "PYTHON")
        filtered_mixed = apply_language_filter(mock_search_results, "Python")

        assert len(filtered_lower) == len(filtered_upper) == len(filtered_mixed) == 2

    def test_filter_no_match_returns_empty(self, mock_search_results):
        """Language filter with no matches should return empty list."""
        from miller.tools.search_filters import apply_language_filter

        filtered = apply_language_filter(mock_search_results, "java")

        assert filtered == []

    def test_filter_none_language_returns_all(self, mock_search_results):
        """None language filter should return all results."""
        from miller.tools.search_filters import apply_language_filter

        filtered = apply_language_filter(mock_search_results, None)

        assert len(filtered) == len(mock_search_results)


class TestFilePatternFilter:
    """Test file_pattern (glob) filter parameter on fast_search."""

    @pytest.fixture
    def mock_search_results(self):
        """Sample search results with various file paths."""
        return [
            {"id": "1", "name": "UserService", "file_path": "src/services/user.py", "score": 0.9},
            {"id": "2", "name": "TestUser", "file_path": "tests/test_user.py", "score": 0.85},
            {"id": "3", "name": "UserModel", "file_path": "src/models/user.py", "score": 0.8},
            {"id": "4", "name": "user_config", "file_path": "config/user.yaml", "score": 0.75},
            {"id": "5", "name": "UserHandler", "file_path": "src/handlers/user_handler.ts", "score": 0.7},
        ]

    def test_filter_by_extension(self, mock_search_results):
        """Should filter by file extension pattern."""
        from miller.tools.search_filters import apply_file_pattern_filter

        filtered = apply_file_pattern_filter(mock_search_results, "*.py")

        assert len(filtered) == 3
        assert all(r["file_path"].endswith(".py") for r in filtered)

    def test_filter_by_directory_glob(self, mock_search_results):
        """Should filter by directory glob pattern."""
        from miller.tools.search_filters import apply_file_pattern_filter

        filtered = apply_file_pattern_filter(mock_search_results, "src/**/*.py")

        assert len(filtered) == 2
        assert all(r["file_path"].startswith("src/") and r["file_path"].endswith(".py") for r in filtered)

    def test_filter_tests_directory(self, mock_search_results):
        """Should filter to tests directory."""
        from miller.tools.search_filters import apply_file_pattern_filter

        filtered = apply_file_pattern_filter(mock_search_results, "tests/**")

        assert len(filtered) == 1
        assert filtered[0]["file_path"].startswith("tests/")

    def test_filter_no_match_returns_empty(self, mock_search_results):
        """File pattern with no matches should return empty list."""
        from miller.tools.search_filters import apply_file_pattern_filter

        filtered = apply_file_pattern_filter(mock_search_results, "nonexistent/**")

        assert filtered == []

    def test_filter_none_pattern_returns_all(self, mock_search_results):
        """None file pattern should return all results."""
        from miller.tools.search_filters import apply_file_pattern_filter

        filtered = apply_file_pattern_filter(mock_search_results, None)

        assert len(filtered) == len(mock_search_results)

    def test_filter_multiple_extensions(self, mock_search_results):
        """Should support multiple extension patterns."""
        from miller.tools.search_filters import apply_file_pattern_filter

        # Filter for .py or .ts files using pattern
        filtered_py = apply_file_pattern_filter(mock_search_results, "*.py")
        filtered_ts = apply_file_pattern_filter(mock_search_results, "*.ts")

        assert len(filtered_py) == 3
        assert len(filtered_ts) == 1


class TestSemanticFallback:
    """Test semantic fallback when text search returns 0 results."""

    @pytest.mark.asyncio
    async def test_semantic_fallback_triggered_when_text_returns_empty(self):
        """When text search returns 0 results, semantic search should be tried."""
        from miller.tools.search import fast_search

        # Mock vector_store to return empty for text, results for semantic
        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(side_effect=[
            [],  # First call (text) returns empty
            [{"id": "1", "name": "auth_handler", "score": 0.8, "language": "python", "file_path": "src/auth.py"}],  # Semantic fallback
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(return_value={
            "id": "1", "name": "auth_handler", "kind": "function",
            "file_path": "src/auth.py", "start_line": 10, "language": "python",
            "code_context": "def auth_handler():"
        })

        result = await fast_search(
            query="authentication handler",
            method="text",  # Explicitly text, so fallback should trigger
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="json",
        )

        # Should have called search twice (text then semantic)
        assert mock_vector_store.search.call_count == 2
        # Second call should be semantic
        second_call_args = mock_vector_store.search.call_args_list[1]
        assert second_call_args[1].get("method") == "semantic"

    @pytest.mark.asyncio
    async def test_semantic_fallback_not_triggered_when_text_has_results(self):
        """When text search returns results, semantic fallback should NOT be triggered."""
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(return_value=[
            {"id": "1", "name": "auth_handler", "score": 0.9, "language": "python", "file_path": "src/auth.py"},
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(return_value={
            "id": "1", "name": "auth_handler", "kind": "function",
            "file_path": "src/auth.py", "start_line": 10, "language": "python",
            "code_context": "def auth_handler():"
        })

        result = await fast_search(
            query="auth_handler",
            method="text",
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="json",
        )

        # Should have called search only once
        assert mock_vector_store.search.call_count == 1

    @pytest.mark.asyncio
    async def test_semantic_fallback_result_includes_fallback_notice(self):
        """Semantic fallback results should include a notice about the fallback."""
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(side_effect=[
            [],  # Text returns empty
            [{"id": "1", "name": "auth_handler", "score": 0.8, "language": "python", "file_path": "src/auth.py"}],
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(return_value={
            "id": "1", "name": "auth_handler", "kind": "function",
            "file_path": "src/auth.py", "start_line": 10, "language": "python",
            "code_context": "def auth_handler():"
        })

        result = await fast_search(
            query="authentication handler",
            method="text",
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="text",  # Text format to check the message
        )

        # Result should mention semantic fallback
        assert "semantic" in result.lower() or "fallback" in result.lower()

    @pytest.mark.asyncio
    async def test_semantic_fallback_triggered_when_scores_are_low(self):
        """When text search returns results but with very low scores, semantic fallback should trigger.

        This catches garbage results from searches like "xyznonexistent123" where
        text search returns partial matches with scores below the quality threshold.
        """
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(side_effect=[
            # Text search returns results but with LOW scores (below 0.3 threshold)
            [
                {"id": "1", "name": "xyz_func", "score": 0.1, "language": "python", "file_path": "src/a.py"},
                {"id": "2", "name": "test_xyz", "score": 0.05, "language": "python", "file_path": "src/b.py"},
            ],
            # Semantic search returns better matches
            [{"id": "3", "name": "real_match", "score": 0.8, "language": "python", "file_path": "src/c.py"}],
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(side_effect=lambda id: {
            "1": {"id": "1", "name": "xyz_func", "kind": "function", "file_path": "src/a.py", "start_line": 10, "language": "python"},
            "2": {"id": "2", "name": "test_xyz", "kind": "function", "file_path": "src/b.py", "start_line": 20, "language": "python"},
            "3": {"id": "3", "name": "real_match", "kind": "function", "file_path": "src/c.py", "start_line": 30, "language": "python"},
        }.get(id))

        result = await fast_search(
            query="xyznonexistent123",
            method="text",
            vector_store=mock_vector_store,
            storage=mock_storage,
            rerank=False,  # Disable reranking to test raw score behavior
            output_format="json",
        )

        # Semantic fallback should have been triggered due to low scores
        # Search should have been called twice (text then semantic)
        assert mock_vector_store.search.call_count == 2
        # Second call should be semantic
        second_call_args = mock_vector_store.search.call_args_list[1]
        assert second_call_args[1].get("method") == "semantic"


class TestSearchWithFilters:
    """Integration tests for search with filters."""

    @pytest.mark.asyncio
    async def test_search_with_language_filter(self):
        """fast_search should accept and apply language filter."""
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(return_value=[
            {"id": "1", "name": "func_py", "score": 0.9, "language": "python", "file_path": "src/a.py"},
            {"id": "2", "name": "func_ts", "score": 0.85, "language": "typescript", "file_path": "src/b.ts"},
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(side_effect=lambda id: {
            "id": id, "name": f"func_{id}", "kind": "function",
            "file_path": f"src/{id}.py", "start_line": 10,
            "language": "python" if id == "1" else "typescript",
            "code_context": "def func():"
        })

        result = await fast_search(
            query="func",
            language="python",
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="json",
        )

        # Should only return Python results
        assert len(result) == 1
        assert result[0]["language"] == "python"

    @pytest.mark.asyncio
    async def test_search_with_file_pattern_filter(self):
        """fast_search should accept and apply file_pattern filter."""
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(return_value=[
            {"id": "1", "name": "test_func", "score": 0.9, "language": "python", "file_path": "tests/test_user.py"},
            {"id": "2", "name": "main_func", "score": 0.85, "language": "python", "file_path": "src/main.py"},
        ])

        mock_storage = MagicMock()
        mock_storage.get_symbol_by_id = MagicMock(side_effect=lambda id: {
            "id": id, "name": f"func_{id}", "kind": "function",
            "file_path": "tests/test_user.py" if id == "1" else "src/main.py",
            "start_line": 10, "language": "python",
            "code_context": "def func():"
        })

        result = await fast_search(
            query="func",
            file_pattern="tests/**",
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="json",
        )

        # Should only return test files
        assert len(result) == 1
        assert result[0]["file_path"].startswith("tests/")

    @pytest.mark.asyncio
    async def test_search_with_both_filters(self):
        """fast_search should apply both language and file_pattern filters."""
        from miller.tools.search import fast_search

        mock_vector_store = MagicMock()
        mock_vector_store.search = MagicMock(return_value=[
            {"id": "1", "name": "test_py", "score": 0.9, "language": "python", "file_path": "tests/test_a.py"},
            {"id": "2", "name": "test_ts", "score": 0.85, "language": "typescript", "file_path": "tests/test_b.ts"},
            {"id": "3", "name": "main_py", "score": 0.8, "language": "python", "file_path": "src/main.py"},
        ])

        mock_storage = MagicMock()
        def mock_get_symbol(id):
            data = {
                "1": {"file_path": "tests/test_a.py", "language": "python"},
                "2": {"file_path": "tests/test_b.ts", "language": "typescript"},
                "3": {"file_path": "src/main.py", "language": "python"},
            }
            return {
                "id": id, "name": f"func_{id}", "kind": "function",
                "start_line": 10, "code_context": "def func():",
                **data[id]
            }
        mock_storage.get_symbol_by_id = MagicMock(side_effect=mock_get_symbol)

        result = await fast_search(
            query="test",
            language="python",
            file_pattern="tests/**",
            vector_store=mock_vector_store,
            storage=mock_storage,
            output_format="json",
        )

        # Should only return Python files in tests/
        assert len(result) == 1
        assert result[0]["language"] == "python"
        assert result[0]["file_path"].startswith("tests/")
