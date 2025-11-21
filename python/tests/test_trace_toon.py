"""
Tests for TOON format support in trace_call_path.

Tests TracePath and TraceNode encoding with deeply nested structures.
"""

import pytest
from toon_format import decode as toon_decode

from miller.toon_types import encode_trace_path_toon, format_trace_node_for_toon


class TestFormatTraceNodeForToon:
    """Test TraceNode flattening for TOON encoding."""

    def test_formats_minimal_node(self):
        """Test formatting node with only required fields."""
        node = {
            "name": "UserService",
            "kind": "Class",
            "file_path": "user.ts",
            "line": 10,
            "language": "typescript",
            "depth": 0,
            "children": [],
        }

        result = format_trace_node_for_toon(node)

        assert result["name"] == "UserService"
        assert result["kind"] == "Class"
        assert result["file_path"] == "user.ts"
        assert result["line"] == 10
        assert result["language"] == "typescript"
        assert result["depth"] == 0
        assert result["children"] == []

    def test_formats_node_with_children(self):
        """Test recursive formatting of nested children."""
        node = {
            "name": "Parent",
            "kind": "Function",
            "file_path": "parent.py",
            "line": 1,
            "language": "python",
            "depth": 0,
            "children": [
                {
                    "name": "Child1",
                    "kind": "Function",
                    "file_path": "child1.py",
                    "line": 10,
                    "language": "python",
                    "depth": 1,
                    "children": [],
                },
                {
                    "name": "Child2",
                    "kind": "Function",
                    "file_path": "child2.py",
                    "line": 20,
                    "language": "python",
                    "depth": 1,
                    "children": [
                        {
                            "name": "Grandchild",
                            "kind": "Function",
                            "file_path": "grandchild.py",
                            "line": 30,
                            "language": "python",
                            "depth": 2,
                            "children": [],
                        }
                    ],
                },
            ],
        }

        result = format_trace_node_for_toon(node)

        # Check parent
        assert result["name"] == "Parent"
        assert len(result["children"]) == 2

        # Check first child
        assert result["children"][0]["name"] == "Child1"
        assert len(result["children"][0]["children"]) == 0

        # Check second child with grandchild
        assert result["children"][1]["name"] == "Child2"
        assert len(result["children"][1]["children"]) == 1
        assert result["children"][1]["children"][0]["name"] == "Grandchild"

    def test_truncates_long_signature(self):
        """Test that long signatures are truncated."""
        long_sig = "function_with_very_long_signature(" + "x: int, " * 50 + ")"
        node = {
            "name": "test",
            "kind": "Function",
            "file_path": "test.py",
            "line": 1,
            "language": "python",
            "depth": 0,
            "signature": long_sig,
            "children": [],
        }

        result = format_trace_node_for_toon(node)

        assert len(result["signature"]) == 103  # 100 + "..."
        assert result["signature"].endswith("...")


class TestEncodeTracePathToon:
    """Test TracePath TOON encoding."""

    def test_encodes_simple_trace(self):
        """Test encoding minimal TracePath."""
        trace_path = {
            "query_symbol": "User",
            "direction": "downstream",
            "max_depth": 3,
            "total_nodes": 1,
            "max_depth_reached": 0,
            "truncated": False,
            "root": {
                "name": "User",
                "kind": "Class",
                "file_path": "user.py",
                "line": 10,
                "language": "python",
                "depth": 0,
                "children": [],
            },
        }

        result = encode_trace_path_toon(trace_path)

        assert isinstance(result, str)
        assert "User" in result

    def test_encodes_deep_nested_trace(self):
        """Test encoding deeply nested TracePath (3 levels)."""
        trace_path = {
            "query_symbol": "main",
            "direction": "downstream",
            "max_depth": 3,
            "total_nodes": 4,
            "max_depth_reached": 3,
            "truncated": False,
            "root": {
                "name": "main",
                "kind": "Function",
                "file_path": "main.py",
                "line": 1,
                "language": "python",
                "depth": 0,
                "children": [
                    {
                        "name": "level1",
                        "kind": "Function",
                        "file_path": "level1.py",
                        "line": 10,
                        "language": "python",
                        "depth": 1,
                        "children": [
                            {
                                "name": "level2",
                                "kind": "Function",
                                "file_path": "level2.py",
                                "line": 20,
                                "language": "python",
                                "depth": 2,
                                "children": [
                                    {
                                        "name": "level3",
                                        "kind": "Function",
                                        "file_path": "level3.py",
                                        "line": 30,
                                        "language": "python",
                                        "depth": 3,
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }

        result = encode_trace_path_toon(trace_path)

        assert isinstance(result, str)
        # Decode and verify structure
        decoded = toon_decode(result)
        assert decoded["total_nodes"] == 4
        assert "root" in decoded
        assert decoded["root"]["name"] == "main"

    def test_roundtrip_encoding_decoding(self):
        """Test that encode → decode preserves structure."""
        trace_path = {
            "query_symbol": "test_func",
            "direction": "downstream",
            "max_depth": 2,
            "total_nodes": 3,
            "max_depth_reached": 2,
            "truncated": False,
            "root": {
                "name": "test_func",
                "kind": "Function",
                "file_path": "test.py",
                "line": 42,
                "language": "python",
                "depth": 0,
                "relationship_kind": "Definition",
                "match_type": "exact",
                "children": [
                    {
                        "name": "helper",
                        "kind": "Function",
                        "file_path": "helper.py",
                        "line": 10,
                        "language": "python",
                        "depth": 1,
                        "relationship_kind": "Call",
                        "match_type": "exact",
                        "children": [],
                    }
                ],
            },
        }

        # Encode to TOON
        toon_str = encode_trace_path_toon(trace_path)
        assert isinstance(toon_str, str)

        # Decode back
        decoded = toon_decode(toon_str)

        # Verify key fields
        assert decoded["query_symbol"] == "test_func"
        assert decoded["total_nodes"] == 3
        assert decoded["root"]["name"] == "test_func"
        assert len(decoded["root"]["children"]) == 1
        assert decoded["root"]["children"][0]["name"] == "helper"

    def test_handles_empty_trace(self):
        """Test encoding TracePath with no root (symbol not found)."""
        trace_path = {
            "query_symbol": "NonexistentSymbol",
            "direction": "downstream",
            "max_depth": 3,
            "total_nodes": 0,
            "error": "Symbol not found",
        }

        result = encode_trace_path_toon(trace_path)

        assert isinstance(result, str)
        decoded = toon_decode(result)
        assert decoded["total_nodes"] == 0
        assert decoded["error"] == "Symbol not found"

    def test_preserves_metadata_fields(self):
        """Test that optional metadata fields are preserved."""
        trace_path = {
            "query_symbol": "func",
            "direction": "downstream",
            "max_depth": 3,
            "total_nodes": 5,
            "max_depth_reached": 2,
            "truncated": True,
            "languages_found": ["python", "typescript", "rust"],
            "match_types": {"exact": 3, "variant": 2},
            "relationship_kinds": {"Call": 4, "Import": 1},
            "execution_time_ms": 123.45,
            "nodes_visited": 10,
            "root": {
                "name": "func",
                "kind": "Function",
                "file_path": "test.py",
                "line": 1,
                "language": "python",
                "depth": 0,
                "children": [],
            },
        }

        result = encode_trace_path_toon(trace_path)
        decoded = toon_decode(result)

        assert decoded["languages_found"] == ["python", "typescript", "rust"]
        assert decoded["match_types"]["exact"] == 3
        assert decoded["relationship_kinds"]["Call"] == 4
        assert abs(decoded["execution_time_ms"] - 123.45) < 0.01


# Integration tests (will need implementation to run fully)
pytestmark = pytest.mark.integration
