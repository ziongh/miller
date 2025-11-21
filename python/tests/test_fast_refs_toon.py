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
    async def test_default_mode_is_json(self, storage_with_test_data):
        """Test that default output_format is JSON."""
        result = await fast_refs("test_function")  # No output_format specified

        # Should default to JSON
        assert isinstance(result, dict)
