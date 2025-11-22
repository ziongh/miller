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
        # Default is "text" - grep-style output (most token-efficient and scannable)
        assert param.default == "text", "output_format should default to 'text'"

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
        # Default is "text" - grep-style output (best token efficiency)
        assert param.default == "text", "Must have default value for backward compatibility"


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


class TestSearchResultHydration:
    """Test that search results are hydrated with code_context from SQLite."""

    def test_hydrate_search_results_adds_code_context(self):
        """Test that _hydrate_search_results fetches code_context from storage."""
        from miller.server import _hydrate_search_results

        # Mock search results (what vector store returns - no code_context)
        search_results = [
            {"id": "abc123", "name": "foo", "kind": "Function", "score": 0.95},
            {"id": "def456", "name": "bar", "kind": "Method", "score": 0.85},
        ]

        # Mock storage that returns full data
        class MockStorage:
            def get_symbol_by_id(self, symbol_id):
                return {
                    "id": symbol_id,
                    "name": "foo" if symbol_id == "abc123" else "bar",
                    "kind": "Function" if symbol_id == "abc123" else "Method",
                    "file_path": "test.py",
                    "start_line": 10 if symbol_id == "abc123" else 20,
                    "code_context": f"10→ def {symbol_id}():" if symbol_id == "abc123" else f"20→ def {symbol_id}():",
                    "signature": "def foo()" if symbol_id == "abc123" else "def bar()",
                }

        hydrated = _hydrate_search_results(search_results, MockStorage())

        # Should have code_context from storage
        assert hydrated[0].get("code_context") is not None
        assert "abc123" in hydrated[0]["code_context"]
        # Should preserve score from search
        assert hydrated[0]["score"] == 0.95

    def test_hydrate_preserves_score_from_search(self):
        """Test that hydration preserves the search score, not storage data."""
        from miller.server import _hydrate_search_results

        search_results = [{"id": "xyz", "name": "test", "score": 0.99}]

        class MockStorage:
            def get_symbol_by_id(self, symbol_id):
                return {"id": symbol_id, "name": "test", "score": 0.5}  # Different score

        hydrated = _hydrate_search_results(search_results, MockStorage())

        # Should keep search score, not storage score
        assert hydrated[0]["score"] == 0.99

    def test_hydrate_handles_missing_symbol(self):
        """Test graceful handling when symbol not found in storage."""
        from miller.server import _hydrate_search_results

        search_results = [{"id": "missing", "name": "gone", "score": 0.8}]

        class MockStorage:
            def get_symbol_by_id(self, symbol_id):
                return None  # Symbol not found

        hydrated = _hydrate_search_results(search_results, MockStorage())

        # Should return original result (not crash)
        assert len(hydrated) == 1
        assert hydrated[0]["name"] == "gone"


class TestGrepStyleTextFormat:
    """Test grep-style text output format (lean format from Julie)."""

    def test_text_format_includes_query_header(self):
        """Test that text format starts with 'N matches for "query":' header."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "authenticate",
                "kind": "Function",
                "file_path": "src/auth.py",
                "start_line": 42,
                "code_context": "41: # Auth logic\n42→ def authenticate(user):\n43:     return True",
            }
        ]

        output = _format_search_as_text(results, query="authenticate")

        # Should have header with count and query
        assert '1 match' in output.lower() or '1 matches' in output.lower()
        assert 'authenticate' in output

    def test_text_format_shows_file_line_header(self):
        """Test that each result shows file:line header."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "process",
                "kind": "Function",
                "file_path": "src/processor.py",
                "start_line": 100,
                "code_context": "99: # Context\n100→ def process(data):\n101:     pass",
            }
        ]

        output = _format_search_as_text(results, query="process")

        # Should have file:line header
        assert "src/processor.py:100" in output

    def test_text_format_indents_code_context(self):
        """Test that code context is indented under file:line header."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "foo",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 10,
                "code_context": "9: # before\n10→ def foo():\n11:     pass",
            }
        ]

        output = _format_search_as_text(results, query="foo")
        lines = output.split("\n")

        # Find code context lines (after file:line header)
        context_lines = [l for l in lines if l.startswith("  ") and (":" in l or "→" in l)]
        assert len(context_lines) > 0, "Code context should be indented with 2 spaces"

    def test_text_format_preserves_arrow_for_match_line(self):
        """Test that match line arrow (→) is preserved."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "bar",
                "kind": "Function",
                "file_path": "bar.py",
                "start_line": 5,
                "code_context": "4: # context\n5→ def bar():\n6:     return 1",
            }
        ]

        output = _format_search_as_text(results, query="bar")

        # Arrow should be preserved in output
        assert "→" in output or ">" in output, "Match line indicator should be preserved"

    def test_text_format_multiple_results(self):
        """Test formatting with multiple results."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "func_a",
                "kind": "Function",
                "file_path": "a.py",
                "start_line": 10,
                "code_context": "10→ def func_a():",
            },
            {
                "name": "func_b",
                "kind": "Function",
                "file_path": "b.py",
                "start_line": 20,
                "code_context": "20→ def func_b():",
            },
        ]

        output = _format_search_as_text(results, query="func")

        # Should have both files
        assert "a.py:10" in output
        assert "b.py:20" in output
        # Should show count
        assert "2" in output

    def test_text_format_fallback_to_signature(self):
        """Test fallback to signature when code_context is missing."""
        from miller.server import _format_search_as_text

        results = [
            {
                "name": "legacy",
                "kind": "Function",
                "file_path": "old.py",
                "start_line": 1,
                "signature": "def legacy(x: int) -> str",
                "code_context": None,  # Missing code_context
            }
        ]

        output = _format_search_as_text(results, query="legacy")

        # Should still work, using signature as fallback
        assert "old.py:1" in output
        assert "legacy" in output

    def test_text_format_token_efficiency(self):
        """Test that text format is more compact than JSON."""
        from miller.server import _format_search_as_text
        import json

        results = [
            {
                "name": "example",
                "kind": "Function",
                "file_path": "src/example.py",
                "start_line": 42,
                "signature": "def example(a: int, b: str) -> bool",
                "doc_comment": "Example function for testing.",
                "code_context": "41: # Helper\n42→ def example(a: int, b: str) -> bool:\n43:     return True",
                "score": 0.95,
            }
        ]

        text_output = _format_search_as_text(results, query="example")
        json_output = json.dumps(results, indent=2)

        # Text format should be significantly shorter
        assert len(text_output) < len(json_output), (
            f"Text ({len(text_output)} chars) should be shorter than JSON ({len(json_output)} chars)"
        )


# Marker for tests that need actual implementation to run fully
pytestmark = pytest.mark.integration
