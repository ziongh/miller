"""
Tests for get_symbols TOON format support.

Validates:
- Three output modes (json/toon/auto)
- Auto threshold behavior (≥20 symbols → TOON)
- Token reduction vs JSON
- Graceful fallback on encoding errors
"""
import pytest
from pathlib import Path
from miller.server import get_symbols


class TestGetSymbolsToonModes:
    """Test the three output format modes."""

    @pytest.mark.asyncio
    async def test_json_mode_returns_list(self, temp_python_file):
        """Test that output_format='json' returns standard list."""
        result = await get_symbols(str(temp_python_file), output_format="json")

        # Should return list, not string
        assert isinstance(result, list)
        if result:  # If file has symbols
            assert isinstance(result[0], dict)

    @pytest.mark.asyncio
    async def test_toon_mode_returns_string(self, temp_python_file):
        """Test that output_format='toon' returns TOON string."""
        result = await get_symbols(str(temp_python_file), output_format="toon")

        # Should return TOON string
        assert isinstance(result, str)
        # TOON format markers
        assert "[" in result or "name:" in result

    @pytest.mark.asyncio
    async def test_auto_mode_uses_json_for_few_symbols(self, temp_small_file):
        """Test that auto mode uses JSON for <20 symbols."""
        # Small file with only 5 symbols
        result = await get_symbols(str(temp_small_file), output_format="auto")

        # Should use JSON for small files
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_auto_mode_uses_toon_for_many_symbols(self, temp_large_file):
        """Test that auto mode uses TOON for ≥20 symbols."""
        # Large file with 30+ symbols
        result = await get_symbols(str(temp_large_file), output_format="auto")

        # Should use TOON for large files
        assert isinstance(result, str)


class TestGetSymbolsToonContent:
    """Test that TOON format preserves all information."""

    @pytest.mark.asyncio
    async def test_toon_includes_symbol_names(self, temp_python_file):
        """Test that TOON output includes symbol names."""
        result = await get_symbols(str(temp_python_file), output_format="toon")

        # Should include specific symbol names from the file
        assert "function_one" in result
        assert "function_two" in result
        assert "TestClass" in result

    @pytest.mark.asyncio
    async def test_toon_includes_symbol_kinds(self, temp_python_file):
        """Test that TOON output includes symbol kinds."""
        result = await get_symbols(str(temp_python_file), output_format="toon")

        # Should include kind indicators (function, class, method, etc.)
        assert "function" in result.lower() or "class" in result.lower() or "method" in result.lower()

    @pytest.mark.asyncio
    async def test_toon_includes_line_numbers(self, temp_python_file):
        """Test that TOON output includes line numbers."""
        result = await get_symbols(str(temp_python_file), output_format="toon")

        # Should include line numbers (check for TOON CSV format with start_line column)
        # TOON format looks like: [N]{name,kind,...,start_line,...}:\n  value,value,...,2,...
        assert "start_line" in result, "Should have start_line column in TOON table"
        # Also verify numeric line numbers appear in the data rows
        import re
        # After the header, there should be lines with comma-separated values including line numbers
        assert re.search(r',\d+,', result), "Should contain numeric line numbers in data rows"


class TestGetSymbolsToonTokenReduction:
    """Test token reduction benefits."""

    @pytest.mark.asyncio
    async def test_toon_is_more_compact_than_json(self, temp_large_file):
        """Test that TOON format is shorter than JSON."""
        json_result = await get_symbols(str(temp_large_file), output_format="json")
        toon_result = await get_symbols(str(temp_large_file), output_format="toon")

        import json
        json_str = json.dumps(json_result)

        # TOON should be more compact
        assert len(toon_result) < len(json_str)
        reduction_pct = (1 - len(toon_result) / len(json_str)) * 100
        assert reduction_pct > 20  # Should achieve at least 20% reduction


class TestGetSymbolsToonEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_file_with_toon(self, temp_empty_file):
        """Test that empty files work with TOON format."""
        result = await get_symbols(str(temp_empty_file), output_format="toon")

        # Should handle empty gracefully
        assert isinstance(result, str)
        assert "No" in result or "[]" in result or len(result) < 50

    @pytest.mark.asyncio
    async def test_default_mode_is_text(self, temp_python_file):
        """Test that default output_format is text (lean, token-efficient)."""
        result = await get_symbols(str(temp_python_file))  # No output_format specified

        # Should default to text format (string, not list)
        assert isinstance(result, str)
        # Text format has file name and symbol count header
        assert "symbol" in result.lower()

    @pytest.mark.asyncio
    async def test_mode_parameter_works_with_toon(self, temp_python_file):
        """Test that mode parameter (structure/minimal/full) works with TOON."""
        # All three modes should work with TOON
        struct = await get_symbols(str(temp_python_file), mode="structure", output_format="toon")
        minimal = await get_symbols(str(temp_python_file), mode="minimal", output_format="toon")
        full = await get_symbols(str(temp_python_file), mode="full", output_format="toon")

        # Verify all return strings
        assert isinstance(struct, str)
        assert isinstance(minimal, str)
        assert isinstance(full, str)

        # Verify that full mode has more content than structure mode
        # (full includes code bodies, structure doesn't)
        assert len(full) >= len(struct), "Full mode should have more content than structure mode"


# Fixtures for test files
@pytest.fixture
def temp_python_file(tmp_path):
    """Create a temporary Python file with some symbols."""
    file = tmp_path / "test.py"
    file.write_text("""
def function_one():
    pass

def function_two():
    pass

class TestClass:
    def method_one(self):
        pass

    def method_two(self):
        pass
""")
    return file


@pytest.fixture
def temp_small_file(tmp_path):
    """Create a small file with <20 symbols."""
    file = tmp_path / "small.py"
    content = "\n".join([f"def func_{i}(): pass" for i in range(5)])
    file.write_text(content)
    return file


@pytest.fixture
def temp_large_file(tmp_path):
    """Create a large file with ≥20 symbols."""
    file = tmp_path / "large.py"
    content = "\n".join([f"def func_{i}(): pass" for i in range(30)])
    file.write_text(content)
    return file


@pytest.fixture
def temp_empty_file(tmp_path):
    """Create an empty file."""
    file = tmp_path / "empty.py"
    file.write_text("")
    return file
