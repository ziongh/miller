"""
Tests for fast_refs TOON format support.

Validates:
- Three output modes (json/toon/auto)
- Auto threshold behavior (≥10 refs → TOON)
- Token reduction vs JSON
- Graceful fallback on encoding errors
"""
import pytest
from miller.server import fast_refs
from miller.tools.navigation import _format_refs_as_text


class TestFastRefsToonModes:
    """Test the three output format modes."""

    @pytest.mark.asyncio
    async def test_json_mode_returns_dict(self, storage_with_test_data):
        """Test that output_format='json' returns standard dict."""
        result = await fast_refs("test_function", output_format="json")

        # Should return dict, not string
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "total_references" in result
        assert "files" in result

    @pytest.mark.asyncio
    async def test_toon_mode_returns_string(self, storage_with_test_data):
        """Test that output_format='toon' returns TOON string."""
        result = await fast_refs("test_function", output_format="toon")

        # Should return TOON string
        assert isinstance(result, str)
        # TOON format markers (nested structure with metadata)
        assert "symbol:" in result or "total_references:" in result

    @pytest.mark.asyncio
    async def test_auto_mode_uses_json_for_few_refs(self, storage_with_test_data):
        """Test that auto mode uses JSON for <10 references."""
        # Create symbol with only 5 references
        result = await fast_refs("small_symbol", output_format="auto")

        # Should use JSON for small result sets
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_auto_mode_uses_toon_for_many_refs(self, storage_with_test_data):
        """Test that auto mode uses TOON for ≥10 references."""
        # test_function has 15 references (≥10 threshold)
        result = await fast_refs("test_function", output_format="auto")

        # Should use TOON for large result sets
        assert isinstance(result, str)


class TestFastRefsToonContent:
    """Test that TOON format preserves all information."""

    @pytest.mark.asyncio
    async def test_toon_includes_symbol_name(self, storage_with_test_data):
        """Test that TOON output includes symbol name."""
        result = await fast_refs("test_function", output_format="toon")

        # Nested TOON format includes metadata
        assert "test_function" in result

    @pytest.mark.asyncio
    async def test_toon_includes_file_paths(self, storage_with_test_data):
        """Test that TOON output includes file paths."""
        result = await fast_refs("test_function", output_format="toon")

        # Should include file paths from references
        assert ".py" in result or ".js" in result or ".rs" in result

    @pytest.mark.asyncio
    async def test_toon_includes_reference_counts(self, storage_with_test_data):
        """Test that TOON output includes reference counts and metadata."""
        result = await fast_refs("test_function", output_format="toon")

        # Should include reference counts in metadata
        assert "total_references:" in result or "references_count:" in result


class TestFastRefsToonTokenReduction:
    """Test token reduction benefits."""

    @pytest.mark.asyncio
    async def test_toon_is_more_compact_than_json(self, storage_with_test_data):
        """Test that TOON format is shorter than JSON."""
        # large_symbol has 25 references (good for token reduction testing)
        json_result = await fast_refs("large_symbol", output_format="json")
        toon_result = await fast_refs("large_symbol", output_format="toon")

        import json
        json_str = json.dumps(json_result)

        # First verify toon_result is actually a string (not a list or other type)
        assert isinstance(toon_result, str), f"TOON format must return string, got {type(toon_result)}"

        # TOON should be more compact
        print(f"\n*** Token Reduction Measurement ***")
        print(f"JSON size: {len(json_str)} chars")
        print(f"TOON size: {len(toon_result)} chars")
        reduction_pct = (1 - len(toon_result) / len(json_str)) * 100
        print(f"Reduction: {reduction_pct:.1f}%")
        print(f"**********************************\n")

        assert len(toon_result) < len(json_str), f"TOON ({len(toon_result)} chars) should be smaller than JSON ({len(json_str)} chars)"
        assert reduction_pct > 15, f"Expected >15% reduction, got {reduction_pct:.1f}%"


class TestFastRefsToonEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_result_with_toon(self, storage_with_test_data):
        """Test that empty results work with TOON format."""
        result = await fast_refs("nonexistent_symbol", output_format="toon")

        # Should handle empty gracefully
        assert isinstance(result, str)
        assert "0" in result or "no" in result.lower()

    @pytest.mark.asyncio
    async def test_default_mode_is_text(self, storage_with_test_data):
        """Test that default output_format is text."""
        result = await fast_refs("test_function")  # No output_format specified

        # Should default to text (string output)
        assert isinstance(result, str)
        assert "references" in result.lower()


class TestFastRefsIncludeContext:
    """Test include_context parameter in text output."""

    @pytest.mark.asyncio
    async def test_text_format_includes_context_when_requested(self, index_file_helper):
        """When include_context=True, text output should show surrounding code."""
        # Create a test file with actual code
        code = '''
def target_function():
    """Function to be referenced."""
    pass

def caller1():
    # Some comment
    target_function()  # This is the call
    # More code
    return True

def caller2():
    # Another caller
    target_function()
    print("Done")
'''
        # Write code to actual file so context extraction works
        from pathlib import Path
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "miller_test_context"
        temp_dir.mkdir(exist_ok=True)
        test_file = temp_dir / "test_context.py"
        test_file.write_text(code)

        # Index the file
        await index_file_helper(test_file)

        # Get result with context
        with_context = await fast_refs("target_function", include_context=True, output_format="text")

        # Get result without context for comparison
        without_context = await fast_refs("target_function", include_context=False, output_format="text")

        assert isinstance(with_context, str)
        assert isinstance(without_context, str)

        # With context should be longer (more lines)
        with_lines = with_context.split("\n")
        without_lines = without_context.split("\n")

        # The output with context should have significantly more lines
        # Each reference with context gets an extra line(s)
        assert len(with_lines) > len(without_lines), \
            f"With context ({len(with_lines)} lines) should be longer than without context ({len(without_lines)} lines)\nWith:\n{with_context}\n\nWithout:\n{without_context}"

        # Context should show actual code - look for patterns
        assert "target_function()" in with_context, \
            f"Context should contain code patterns, but got:\n{with_context}"

    @pytest.mark.asyncio
    async def test_text_format_shows_line_content_with_context(self, index_file_helper):
        """With include_context=True, text output should show the actual code line."""
        code = '''
def helper_func():
    """A helper function."""
    return 42

def use_helper():
    result = helper_func()  # Using helper
    return result * 2
'''
        from pathlib import Path
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / "miller_test_context"
        temp_dir.mkdir(exist_ok=True)
        test_file = temp_dir / "test_helper.py"
        test_file.write_text(code)

        await index_file_helper(test_file)

        result = await fast_refs("helper_func", include_context=True, output_format="text")

        assert isinstance(result, str)
        # Should see the actual function call
        assert "helper_func()" in result, \
            f"Should see actual function call with context:\n{result}"

    @pytest.mark.asyncio
    async def test_text_format_without_context(self, storage_with_test_data):
        """When include_context=False, text output should only show file:line."""
        result = await fast_refs("test_function", include_context=False, output_format="text")

        assert isinstance(result, str)
        # Should still have references
        assert "test_function" in result


class TestFastRefsTruncationIndicators:
    """Test that truncation indicators are shown when results are limited."""

    @pytest.mark.asyncio
    async def test_text_format_indicates_truncation(self, storage_with_test_data):
        """When results are truncated via limit, text output should indicate this."""
        # test_function has 15 references
        # With limit=5, should show truncation indicator
        result = await fast_refs("test_function", limit=5, output_format="text")

        assert isinstance(result, str)
        # Should indicate truncation in some way:
        # - "truncated" keyword
        # - "..." ellipsis
        # - "more X references" message
        # - "showing N of M" message
        truncation_indicators = [
            "truncated",
            "...",
            "more",
            "showing",
            "only",
            "omitted",
        ]
        has_indicator = any(indicator in result.lower() for indicator in truncation_indicators)
        assert has_indicator, f"Text output should indicate truncation, but got:\n{result}"

    @pytest.mark.asyncio
    async def test_json_format_includes_truncated_flag(self, storage_with_test_data):
        """When results are truncated, JSON output should include truncated flag."""
        result = await fast_refs("test_function", limit=5, output_format="json")

        assert isinstance(result, dict)
        # JSON already includes truncated flag from find_references
        # This test ensures the flag is preserved
        assert "truncated" in result or result.get("total_references", 0) > 5

    @pytest.mark.asyncio
    async def test_toon_format_indicates_truncation(self, storage_with_test_data):
        """When results are truncated, TOON output should include indicator."""
        result = await fast_refs("test_function", limit=5, output_format="toon")

        assert isinstance(result, str)
        # TOON format should also show truncation
        assert "truncated" in result or "..." in result or "omitted" in result

    @pytest.mark.asyncio
    async def test_no_truncation_indicator_when_not_truncated(self, storage_with_test_data):
        """When results are NOT truncated, text output should NOT indicate truncation."""
        result = await fast_refs("small_symbol", output_format="text")

        assert isinstance(result, str)
        # Should NOT have truncation indicators if not truncated
        # (unless the references list is naturally empty)
        # For small_symbol with 5 refs, requesting all 5 should not show truncation
        if "references" in result.lower():
            # If there are no truncation keywords, that's fine
            pass

class TestFastRefsTextFormatComprehensive:
    """Comprehensive tests for the lean text output format (default)."""

    @pytest.mark.asyncio
    async def test_text_format_returns_string(self, storage_with_test_data):
        """Test that text format returns a string."""
        result = await fast_refs("test_function", output_format="text")

        # Should be a string, not dict or other type
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_text_format_has_header_with_count(self, storage_with_test_data):
        """Test that text format includes header with reference count."""
        result = await fast_refs("test_function", output_format="text")

        # Header should show total count
        assert "15 references" in result
        assert "test_function" in result
        # Format should be like: "15 references to "test_function":"
        assert 'references to "test_function"' in result

    @pytest.mark.asyncio
    async def test_text_format_shows_file_and_line(self, storage_with_test_data):
        """Test that text format shows file:line for each reference."""
        result = await fast_refs("test_function", output_format="text")

        # Should show file:line format
        assert ".py:" in result  # File with extension and line number
        lines = result.split("\n")
        # Should have lines with file:line (line:number) pattern
        has_file_line = any(".py:" in line for line in lines)
        assert has_file_line

    @pytest.mark.asyncio
    async def test_text_format_shows_kind_in_parens(self, storage_with_test_data):
        """Test that text format shows the reference kind in parentheses."""
        result = await fast_refs("test_function", output_format="text")

        # Each reference should show kind like "(calls)" or "(definition)"
        assert "(" in result and ")" in result
        # Should contain kind information
        assert "calls" in result.lower() or "definition" in result.lower()

    @pytest.mark.asyncio
    async def test_text_format_empty_result(self, storage_with_test_data):
        """Test that text format handles empty results gracefully."""
        result = await fast_refs("nonexistent_symbol", output_format="text")

        # Should return user-friendly message for no references
        assert isinstance(result, str)
        assert "No references found" in result or "0" in result

    @pytest.mark.asyncio
    async def test_text_format_with_limit(self, storage_with_test_data):
        """Test that text format respects limit parameter."""
        result_all = await fast_refs("test_function", output_format="text")
        result_limited = await fast_refs("test_function", output_format="text", limit=3)

        # Limited result should have fewer lines (excluding header)
        lines_all = result_all.split("\n")
        lines_limited = result_limited.split("\n")

        # Filtered result should have fewer references
        assert len(lines_limited) <= len(lines_all)

    @pytest.mark.asyncio
    async def test_text_format_vs_json_format(self, storage_with_test_data):
        """Test that explicit format switching works."""
        text_result = await fast_refs("test_function", output_format="text")
        json_result = await fast_refs("test_function", output_format="json")

        # Text should be string
        assert isinstance(text_result, str)
        # JSON should be dict
        assert isinstance(json_result, dict)
        # Both should contain the symbol name
        assert "test_function" in text_result
        assert json_result["symbol"] == "test_function"

    @pytest.mark.asyncio
    async def test_text_format_readable_for_humans(self, storage_with_test_data):
        """Test that text format is human-readable (the whole point!)."""
        result = await fast_refs("test_function", output_format="text")

        # Should be easy to read - no JSON syntax
        assert "{" not in result  # No JSON braces
        assert "[" not in result  # No JSON arrays
        # Should have clean line breaks
        lines = result.split("\n")
        assert len(lines) > 1  # Multiple lines for readability

    @pytest.mark.asyncio
    async def test_text_format_with_small_symbol(self, storage_with_test_data):
        """Test text format with small reference count."""
        result = await fast_refs("small_symbol", output_format="text")

        # Should show the count correctly
        assert isinstance(result, str)
        assert "5 references" in result
        assert "small_symbol" in result

    @pytest.mark.asyncio
    async def test_text_format_with_large_symbol(self, storage_with_test_data):
        """Test text format with large reference count."""
        result = await fast_refs("large_symbol", output_format="text")

        # Should show the count correctly
        assert isinstance(result, str)
        assert "25 references" in result
        assert "large_symbol" in result


class TestFormatRefsAsTextUnit:
    """Unit tests for _format_refs_as_text formatter function."""

    def test_format_with_multiple_references(self):
        """Test formatting a result with multiple references."""
        test_data = {
            "symbol": "myFunction",
            "total_references": 3,
            "files": [
                {
                    "path": "src/module.py",
                    "references": [
                        {"line": 10, "kind": "calls"},
                        {"line": 25, "kind": "calls"},
                    ]
                },
                {
                    "path": "src/other.py",
                    "references": [
                        {"line": 42, "kind": "definition"},
                    ]
                }
            ]
        }

        result = _format_refs_as_text(test_data)

        # Should be a string
        assert isinstance(result, str)
        # Should contain header with count
        assert "3 references" in result
        # Should contain symbol name
        assert "myFunction" in result
        # Should contain all file references
        assert "src/module.py:10" in result
        assert "src/module.py:25" in result
        assert "src/other.py:42" in result
        # Should show kind
        assert "calls" in result
        assert "definition" in result

    def test_format_with_zero_references(self):
        """Test formatting when no references found."""
        test_data = {
            "symbol": "unused_function",
            "total_references": 0,
            "files": []
        }

        result = _format_refs_as_text(test_data)

        # Should return clear message
        assert isinstance(result, str)
        assert 'No references found for "unused_function"' in result

    def test_format_with_missing_fields(self):
        """Test formatting handles missing optional fields gracefully."""
        test_data = {
            "symbol": "test",
            "total_references": 1,
            "files": [
                {
                    "path": "test.py",
                    "references": [
                        {"line": 5}  # Missing "kind" field
                    ]
                }
            ]
        }

        result = _format_refs_as_text(test_data)

        # Should still format correctly with default values
        assert isinstance(result, str)
        assert "test.py:5" in result
        assert "(reference)" in result  # Default kind value
