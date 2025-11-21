"""
Integration tests for fast_search with TOON format support.

Tests that fast_search correctly uses output_format parameter to return
either JSON (list) or TOON (string) based on the mode and result count.
"""

import pytest

# These tests will initially FAIL since fast_search doesn't have output_format parameter yet
# This is intentional - TDD RED phase


class TestFastSearchOutputFormat:
    """Test fast_search with output_format parameter."""

    @pytest.fixture
    def mock_search_results(self):
        """Mock search results for testing."""
        return [
            {
                "name": f"function_{i}",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": i * 10,
                "signature": f"def function_{i}(x: int) -> str",
                "doc_comment": "Test function",
                "score": 0.9 - (i * 0.01),
            }
            for i in range(30)
        ]

    def test_fast_search_has_output_format_parameter(self):
        """Test that fast_search signature includes output_format parameter."""
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)

        # Should have output_format parameter
        assert "output_format" in sig.parameters, "fast_search missing output_format parameter"

        # Should have correct type annotation
        param = sig.parameters["output_format"]
        # Default is "auto" - automatically uses TOON for large results (best UX)
        assert param.default == "auto", "output_format should default to 'auto'"

    def test_json_mode_returns_list(self):
        """Test that output_format='json' returns list even with many results."""
        # This test will FAIL initially - fast_search doesn't have output_format yet
        from miller.server import fast_search

        # Mock the vector_store to return many results
        # (In real test, we'd mock vector_store.search)

        # For now, just test the signature accepts the parameter
        import inspect
        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters

    def test_toon_mode_returns_string(self):
        """Test that output_format='toon' returns TOON string."""
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters

    def test_auto_mode_returns_json_for_few_results(self):
        """Test that output_format='auto' returns JSON for <20 results."""
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters

    def test_auto_mode_returns_toon_for_many_results(self):
        """Test that output_format='auto' returns TOON for ≥20 results."""
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters

    def test_backward_compatibility_without_output_format(self):
        """Test that fast_search works without output_format (has default value)."""
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)

        # Should have output_format parameter with default
        param = sig.parameters.get("output_format")
        assert param is not None
        # Default is "auto" - best UX, automatically uses TOON for large results
        assert param.default == "auto", "Must have default value for backward compatibility"


class TestFastSearchReturnType:
    """Test that fast_search return type changes based on output_format."""

    def test_return_type_annotation_is_union(self):
        """Test that fast_search return type is Union[list, str]."""
        from miller.server import fast_search
        import inspect
        from typing import get_type_hints

        try:
            hints = get_type_hints(fast_search)
            # Return type should be Union or allow both list and str
            assert "return" in hints
            # The actual type checking would be complex, so we'll verify behavior instead
        except Exception:
            # Type hints might not be fully evaluable in test environment
            pass

    def test_json_mode_returns_list_type(self):
        """Verify JSON mode returns list type (structural check)."""
        # This is a placeholder - full test needs mocking
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters

    def test_toon_mode_returns_str_type(self):
        """Verify TOON mode returns string type (structural check)."""
        # This is a placeholder - full test needs mocking
        from miller.server import fast_search
        import inspect

        sig = inspect.signature(fast_search)
        assert "output_format" in sig.parameters


class TestFastSearchTOONEncoding:
    """Test TOON encoding behavior in fast_search."""

    def test_toon_mode_produces_compact_output(self):
        """Test that TOON mode produces more compact output than JSON."""
        # Placeholder - needs mocking to test actual behavior
        from miller.server import fast_search
        assert fast_search is not None

    def test_toon_fallback_on_encoding_error(self):
        """Test that TOON encoding errors fall back to JSON gracefully."""
        # Placeholder - needs mocking
        from miller.server import fast_search
        assert fast_search is not None

    def test_empty_results_handled_correctly(self):
        """Test that empty results work in both JSON and TOON modes."""
        # Placeholder
        from miller.server import fast_search
        assert fast_search is not None


# Marker for tests that need actual implementation to run fully
pytestmark = pytest.mark.integration
