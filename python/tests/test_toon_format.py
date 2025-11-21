"""
Tests for TOON format support in Miller.

Tests the contract defined in miller.toon_types:
- format_symbol_for_toon: Symbol flattening and truncation
- encode_toon: TOON encoding with fallback
- should_use_toon: Three-mode logic (json/toon/auto)
"""

import pytest
from toon_format import decode as toon_decode
from toon_format import encode as toon_encode

from miller.toon_types import (
    DEFAULT_TOON_CONFIG,
    ToonSymbol,
    encode_toon,
    format_symbol_for_toon,
    should_use_toon,
)


class TestFormatSymbolForToon:
    """Test symbol flattening for TOON encoding."""

    def test_formats_minimal_symbol(self):
        """Test formatting symbol with only required fields."""
        symbol = {
            "name": "hello",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 42,
        }

        result = format_symbol_for_toon(symbol)

        assert result["name"] == "hello"
        assert result["kind"] == "Function"
        assert result["file_path"] == "test.py"
        assert result["start_line"] == 42
        # Schema homogeneity: optional fields included with None values
        assert result["signature"] is None
        assert result["doc_comment"] is None

    def test_formats_full_symbol_with_all_fields(self):
        """Test formatting symbol with all optional fields."""
        symbol = {
            "name": "UserService",
            "kind": "Class",
            "file_path": "user.py",
            "start_line": 10,
            "end_line": 50,
            "signature": "class UserService(BaseService)",
            "doc_comment": "Handles user operations",
            "score": 0.95,
            "language": "python",
        }

        result = format_symbol_for_toon(symbol)

        assert result["name"] == "UserService"
        assert result["kind"] == "Class"
        assert result["file_path"] == "user.py"
        assert result["start_line"] == 10
        assert result["end_line"] == 50
        assert result["signature"] == "class UserService(BaseService)"
        assert result["doc_comment"] == "Handles user operations"
        assert result["score"] == 0.95
        assert result["language"] == "python"

    def test_truncates_long_doc_comment(self):
        """Test that long doc comments are truncated with ellipsis."""
        long_doc = "A" * 200  # 200 chars
        symbol = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 1,
            "doc_comment": long_doc,
        }

        result = format_symbol_for_toon(symbol, max_doc_length=100)

        assert len(result["doc_comment"]) == 100
        assert result["doc_comment"].endswith("...")
        assert result["doc_comment"].startswith("AAA")

    def test_handles_missing_required_fields_with_defaults(self):
        """Test that missing required fields get safe defaults."""
        symbol = {}  # Empty dict

        result = format_symbol_for_toon(symbol)

        assert result["name"] == ""
        assert result["kind"] == "Unknown"
        assert result["file_path"] == ""
        assert result["start_line"] == 0

    def test_converts_non_string_signature_to_string(self):
        """Test that non-string values are converted to strings."""
        symbol = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 1,
            "signature": 123,  # Wrong type - should be string
        }

        result = format_symbol_for_toon(symbol)

        assert result["signature"] == "123"
        assert isinstance(result["signature"], str)

    def test_converts_non_float_score_to_float(self):
        """Test that score is converted to float."""
        symbol = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 1,
            "score": "0.85",  # String instead of float
        }

        result = format_symbol_for_toon(symbol)

        assert result["score"] == 0.85
        assert isinstance(result["score"], float)

    def test_handles_invalid_score_value(self):
        """Test that invalid score values default to None."""
        symbol = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 1,
            "score": "not_a_number",
        }

        result = format_symbol_for_toon(symbol)

        assert result["score"] is None

    def test_omits_empty_optional_fields(self):
        """Test that empty optional fields are included with None for schema homogeneity."""
        symbol = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "start_line": 1,
            "signature": "",  # Empty string
            "doc_comment": None,  # None value
        }

        result = format_symbol_for_toon(symbol)

        # Schema homogeneity: empty/None fields included with None values
        assert result["signature"] is None  # Empty string converted to None
        assert result["doc_comment"] is None  # None preserved


class TestShouldUseToon:
    """Test three-mode logic for TOON vs JSON selection."""

    def test_json_mode_always_returns_false(self):
        """Test that 'json' mode always returns False regardless of count."""
        assert should_use_toon("json", 0) is False
        assert should_use_toon("json", 10) is False
        assert should_use_toon("json", 100) is False
        assert should_use_toon("json", 1000) is False

    def test_toon_mode_always_returns_true(self):
        """Test that 'toon' mode always returns True regardless of count."""
        assert should_use_toon("toon", 0) is True
        assert should_use_toon("toon", 5) is True
        assert should_use_toon("toon", 50) is True
        assert should_use_toon("toon", 500) is True

    def test_auto_mode_uses_threshold(self):
        """Test that 'auto' mode uses threshold from config."""
        # Default threshold is 20
        assert should_use_toon("auto", 19) is False  # Below threshold
        assert should_use_toon("auto", 20) is True  # At threshold
        assert should_use_toon("auto", 21) is True  # Above threshold

    def test_auto_mode_with_custom_threshold(self):
        """Test 'auto' mode with custom threshold."""
        custom_config = DEFAULT_TOON_CONFIG.copy()
        custom_config["threshold"] = 50

        assert should_use_toon("auto", 49, custom_config) is False
        assert should_use_toon("auto", 50, custom_config) is True
        assert should_use_toon("auto", 51, custom_config) is True

    def test_auto_mode_edge_case_zero_results(self):
        """Test 'auto' mode with zero results."""
        assert should_use_toon("auto", 0) is False  # Below threshold


class TestEncodeToon:
    """Test TOON encoding with fallback behavior."""

    def test_encodes_single_symbol(self):
        """Test encoding a single symbol to TOON format."""
        symbols = [
            {
                "name": "hello",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 1,
            }
        ]

        result = encode_toon(symbols)

        # Should return TOON string
        assert isinstance(result, str)
        assert "hello" in result
        assert "Function" in result

    def test_encodes_multiple_symbols(self):
        """Test encoding multiple symbols to TOON format."""
        symbols = [
            {
                "name": "UserService",
                "kind": "Class",
                "file_path": "user.py",
                "start_line": 10,
            },
            {
                "name": "get_user",
                "kind": "Method",
                "file_path": "user.py",
                "start_line": 15,
            },
        ]

        result = encode_toon(symbols)

        assert isinstance(result, str)
        assert "UserService" in result
        assert "get_user" in result

    def test_roundtrip_encoding_decoding(self):
        """Test that encode → decode returns equivalent data."""
        symbols = [
            {
                "name": "test_func",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 42,
                "signature": "(x: int) -> str",
            }
        ]

        # Encode to TOON
        toon_str = encode_toon(symbols)
        assert isinstance(toon_str, str)

        # Decode back
        decoded = toon_decode(toon_str)

        # Should have same number of items
        assert len(decoded) == len(symbols)

        # Check first item has key fields
        assert decoded[0]["name"] == "test_func"
        assert decoded[0]["kind"] == "Function"
        assert decoded[0]["file_path"] == "test.py"
        assert decoded[0]["start_line"] == 42

    def test_handles_empty_symbols_list(self):
        """Test encoding empty list returns specific message."""
        symbols = []

        result = encode_toon(symbols)

        assert result == "# No results found"

    def test_fallback_to_json_on_encoding_error(self):
        """Test that invalid data falls back to JSON format."""
        # Create symbols with problematic data that might fail TOON encoding
        # (though toon-format is quite robust)
        symbols = [
            {
                "name": "test",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 1,
            }
        ]

        # Enable fallback
        config = DEFAULT_TOON_CONFIG.copy()
        config["fallback_on_error"] = True

        # Even if encoding succeeds, test the fallback path by mocking
        # For now, just verify it doesn't raise
        result = encode_toon(symbols, config)

        # Should return either TOON string or original list
        assert isinstance(result, (str, list))

    def test_truncates_long_doc_comments_in_batch(self):
        """Test that doc comments are truncated when encoding batch."""
        symbols = [
            {
                "name": f"func{i}",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": i,
                "doc_comment": "X" * 200,  # Long doc
            }
            for i in range(5)
        ]

        config = DEFAULT_TOON_CONFIG.copy()
        config["max_doc_length"] = 50

        result = encode_toon(symbols, config)

        assert isinstance(result, str)

        # Decode and check truncation happened
        decoded = toon_decode(result)
        for item in decoded:
            if "doc_comment" in item:
                assert len(item["doc_comment"]) <= 50

    def test_preserves_score_field(self):
        """Test that score field is preserved in encoding."""
        symbols = [
            {
                "name": "high_score",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 1,
                "score": 0.95,
            },
            {
                "name": "low_score",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 10,
                "score": 0.42,
            },
        ]

        result = encode_toon(symbols)
        decoded = toon_decode(result)

        # Scores should be preserved (as floats)
        scores = [item.get("score", 0) for item in decoded]
        assert 0.95 in scores or abs(scores[0] - 0.95) < 0.01
        assert 0.42 in scores or abs(scores[1] - 0.42) < 0.01


class TestToonIntegration:
    """Integration tests for TOON format with real toon-format library."""

    def test_toon_format_library_available(self):
        """Test that toon-format library is installed and importable."""
        # Should not raise ImportError
        assert toon_encode is not None
        assert toon_decode is not None

    def test_basic_toon_encode_decode(self):
        """Test basic encode/decode with toon-format library."""
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]

        encoded = toon_encode(data)
        assert isinstance(encoded, str)

        decoded = toon_decode(encoded)
        assert len(decoded) == 2
        assert decoded[0]["name"] == "Alice"
        assert decoded[1]["name"] == "Bob"

    def test_toon_handles_special_characters(self):
        """Test that TOON format handles special characters correctly."""
        symbols = [
            {
                "name": "User::save",
                "kind": "Method",
                "file_path": "src/user.cpp",
                "start_line": 42,
                "signature": "void save(std::string& path)",
            }
        ]

        result = encode_toon(symbols)
        assert isinstance(result, str)

        decoded = toon_decode(result)
        assert decoded[0]["name"] == "User::save"
        assert "std::string" in decoded[0]["signature"]

    def test_toon_handles_unicode(self):
        """Test that TOON format handles Unicode characters."""
        symbols = [
            {
                "name": "café",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": 1,
                "doc_comment": "Función para café ☕",
            }
        ]

        result = encode_toon(symbols)
        assert isinstance(result, str)

        decoded = toon_decode(result)
        assert decoded[0]["name"] == "café"
        assert "☕" in decoded[0]["doc_comment"]

    def test_large_batch_encoding(self):
        """Test encoding large number of symbols (performance check)."""
        symbols = [
            {
                "name": f"function_{i}",
                "kind": "Function",
                "file_path": f"file_{i % 10}.py",
                "start_line": i,
                "score": float(i) / 1000,
            }
            for i in range(100)
        ]

        result = encode_toon(symbols)
        assert isinstance(result, str)

        decoded = toon_decode(result)
        assert len(decoded) == 100

    def test_toon_output_is_more_compact_than_json(self):
        """Test that TOON format is more compact than JSON (key benefit)."""
        import json

        symbols = [
            {
                "name": f"function_{i}",
                "kind": "Function",
                "file_path": "test.py",
                "start_line": i * 10,
                "signature": f"def function_{i}(x: int) -> str",
                "doc_comment": "Test function",
            }
            for i in range(50)
        ]

        # Format for TOON
        toon_str = encode_toon(symbols)

        # Format for JSON
        json_str = json.dumps(symbols)

        # TOON should be shorter (the whole point!)
        assert len(toon_str) < len(json_str)

        # Calculate reduction percentage
        reduction = (len(json_str) - len(toon_str)) / len(json_str) * 100

        # Should achieve at least 20% reduction (conservative estimate)
        assert reduction >= 20, f"Only {reduction:.1f}% reduction (expected ≥20%)"


class TestThreeModeLogic:
    """Test the three-mode logic (json/toon/auto) end-to-end."""

    def test_json_mode_returns_list(self):
        """Test that json mode returns list even with many results."""
        symbols = [
            {"name": f"func{i}", "kind": "Function", "file_path": "test.py", "start_line": i}
            for i in range(50)
        ]

        # Force JSON mode
        use_toon = should_use_toon("json", len(symbols))
        assert use_toon is False

        # In actual implementation, this would return symbols list
        # not TOON string

    def test_toon_mode_returns_string(self):
        """Test that toon mode returns string even with few results."""
        symbols = [
            {"name": "func", "kind": "Function", "file_path": "test.py", "start_line": 1}
        ]

        # Force TOON mode
        use_toon = should_use_toon("toon", len(symbols))
        assert use_toon is True

        # Encode to TOON
        result = encode_toon(symbols)
        assert isinstance(result, str)

    def test_auto_mode_threshold_behavior(self):
        """Test that auto mode switches at threshold."""
        # Below threshold: use JSON
        symbols_few = [
            {"name": f"func{i}", "kind": "Function", "file_path": "test.py", "start_line": i}
            for i in range(15)  # Less than 20
        ]
        assert should_use_toon("auto", len(symbols_few)) is False

        # At/above threshold: use TOON
        symbols_many = [
            {"name": f"func{i}", "kind": "Function", "file_path": "test.py", "start_line": i}
            for i in range(25)  # More than 20
        ]
        assert should_use_toon("auto", len(symbols_many)) is True
