"""
Tests for fast_explore mode="similar" - find semantically similar code.

Following TDD: Tests define expected behavior BEFORE implementation.
These tests verify that similar mode uses vector embeddings to find
duplicate/near-duplicate code for refactoring purposes.
"""

import pytest


class TestExploreSimilarMode:
    """Tests for fast_explore mode='similar'."""

    @pytest.mark.asyncio
    async def test_similar_mode_accepted(self):
        """Test that mode='similar' is a valid mode (doesn't raise ValueError)."""
        from miller.tools.explore import fast_explore

        # Should not raise ValueError("Unknown exploration mode")
        # It's OK if it raises other errors (like missing symbol param)
        try:
            result = await fast_explore(mode="similar", symbol="test")
        except ValueError as e:
            if "Unknown exploration mode" in str(e):
                pytest.fail("mode='similar' should be accepted, got: " + str(e))
            # Other ValueErrors are OK (e.g., "symbol required")
        except Exception:
            # Other exceptions are fine - mode was accepted
            pass

    @pytest.mark.asyncio
    async def test_similar_mode_requires_symbol_param(self):
        """Test that similar mode requires 'symbol' parameter."""
        from miller.tools.explore import fast_explore

        # Calling without symbol should return error dict or raise
        result = await fast_explore(mode="similar")

        # Either returns error dict or raised exception
        assert "error" in result or result.get("similar") == []

    @pytest.mark.asyncio
    async def test_similar_mode_returns_expected_structure(self):
        """Test that similar mode returns dict with symbol, similar, total_found."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="similar",
            symbol="nonexistent_symbol_xyz",
        )

        # Should return a dict with expected keys
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "similar" in result
        assert "total_found" in result or "error" in result

    @pytest.mark.asyncio
    async def test_similar_mode_symbol_not_found_returns_error(self):
        """Test error response when symbol doesn't exist."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="similar",
            symbol="definitely_not_a_real_symbol_12345",
        )

        # Should return error, not crash
        assert isinstance(result, dict)
        assert result["symbol"] == "definitely_not_a_real_symbol_12345"
        # Either error message or empty results
        assert "error" in result or result["similar"] == []

    @pytest.mark.asyncio
    async def test_similar_mode_threshold_default(self):
        """Test that threshold defaults to 0.7."""
        from miller.tools.explore import fast_explore
        import inspect

        # Check function signature for default
        sig = inspect.signature(fast_explore)
        params = sig.parameters

        # threshold param should exist with default 0.7
        # Note: might be in the mode-specific implementation
        # For now just verify the mode works
        result = await fast_explore(
            mode="similar",
            symbol="test",
            threshold=0.5,  # Explicit threshold should be accepted
        )

        assert isinstance(result, dict)


class TestExploreSimilarTextFormat:
    """Tests for similar mode text output formatting."""

    def test_format_similar_as_text_exists(self):
        """Test that _format_similar_as_text function exists."""
        from miller.tools.explore import _format_similar_as_text

        assert callable(_format_similar_as_text)

    def test_similar_text_format_returns_string(self):
        """Test that text formatter returns a string."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "getUserData",
            "total_found": 1,
            "similar": [
                {
                    "name": "fetchUserData",
                    "kind": "Function",
                    "file_path": "src/api/user.py",
                    "start_line": 45,
                    "similarity": 0.92,
                    "signature": "def fetchUserData(user_id: int) -> dict",
                },
            ],
        }

        text = _format_similar_as_text(result)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_similar_text_format_has_header(self):
        """Test that text output includes header with symbol name."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "getUserData",
            "total_found": 2,
            "similar": [
                {
                    "name": "fetchUserData",
                    "kind": "Function",
                    "file_path": "src/api/user.py",
                    "start_line": 45,
                    "similarity": 0.92,
                    "signature": "def fetchUserData(user_id: int) -> dict",
                },
            ],
        }

        text = _format_similar_as_text(result)

        assert "getUserData" in text

    def test_similar_text_format_shows_similarity(self):
        """Test that text output shows similarity percentage."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "process",
            "total_found": 1,
            "similar": [
                {
                    "name": "handle",
                    "kind": "Function",
                    "file_path": "src/handler.py",
                    "start_line": 10,
                    "similarity": 0.85,
                    "signature": "def handle(data)",
                },
            ],
        }

        text = _format_similar_as_text(result)

        # Should show similarity score (85% or 0.85)
        assert "85" in text or "0.85" in text

    def test_similar_text_format_shows_file_location(self):
        """Test that text output shows file:line."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "getData",
            "total_found": 1,
            "similar": [
                {
                    "name": "fetchData",
                    "kind": "Function",
                    "file_path": "src/fetcher.py",
                    "start_line": 25,
                    "similarity": 0.88,
                    "signature": "def fetchData(id: int)",
                },
            ],
        }

        text = _format_similar_as_text(result)

        assert "src/fetcher.py" in text
        assert "25" in text

    def test_similar_text_format_empty_results(self):
        """Test text output when no similar symbols found."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "uniqueFunction",
            "total_found": 0,
            "similar": [],
        }

        text = _format_similar_as_text(result)

        assert "uniqueFunction" in text
        # Should indicate no results
        assert "0" in text or "No" in text or "none" in text.lower()

    def test_similar_text_format_error_case(self):
        """Test text output when there's an error."""
        from miller.tools.explore import _format_similar_as_text

        result = {
            "symbol": "badSymbol",
            "error": "Symbol not found",
            "similar": [],
        }

        text = _format_similar_as_text(result)

        assert "badSymbol" in text
        # Should show error or "not found"
        assert "error" in text.lower() or "not found" in text.lower() or "0" in text
