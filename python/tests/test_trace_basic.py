"""
Tests for trace_call_path basic functionality.

TDD Phase 2: Write tests BEFORE implementation.
These tests define the exact behavior of basic call tracing.
"""

import pytest

from miller.tools.trace_types import TraceDirection, TraceNode, TracePath


# Import the implementation
try:
    from miller.tools.trace import trace_call_path
    TRACE_AVAILABLE = True
except ImportError:
    TRACE_AVAILABLE = False

# Skip all tests if trace module not available
pytestmark = pytest.mark.skipif(
    not TRACE_AVAILABLE,
    reason="trace_call_path module not available"
)


class TestTraceCallPathBasic:
    """Test basic trace_call_path functionality."""

    @pytest.mark.asyncio
    async def test_downstream_single_level(self, sample_indexed_workspace):
        """
        Test downstream tracing for a single level.

        Setup:
            function_a calls function_b
            function_a calls function_c

        Query: trace_call_path("function_a", direction="downstream", max_depth=1)

        Expected: Root with 2 children (function_b, function_c)
        """
        from miller.tools.trace import trace_call_path
        from miller.storage import StorageManager

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            direction="downstream",
            max_depth=1
        )

        assert isinstance(result, dict)
        assert result["query_symbol"] == "function_a"
        assert result["direction"] == "downstream"
        assert result["max_depth"] == 1

        root = result["root"]
        assert root["name"] == "function_a"
        assert root["depth"] == 0
        assert len(root["children"]) == 2

        # Children should be function_b and function_c
        child_names = {child["name"] for child in root["children"]}
        assert child_names == {"function_b", "function_c"}

        # All children should be at depth 1
        for child in root["children"]:
            assert child["depth"] == 1
            assert child["relationship_kind"] == "Call"
            assert child["match_type"] == "exact"

    @pytest.mark.asyncio
    async def test_upstream_single_level(self, sample_indexed_workspace):
        """
        Test upstream tracing for a single level.

        Setup:
            function_a calls function_b
            function_c calls function_b

        Query: trace_call_path("function_b", direction="upstream", max_depth=1)

        Expected: Root with 2 children (function_a, function_c as callers)
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_b",
            direction="upstream",
            max_depth=1
        )

        assert result["query_symbol"] == "function_b"
        assert result["direction"] == "upstream"

        root = result["root"]
        assert root["name"] == "function_b"
        assert len(root["children"]) == 2

        # Children should be function_a and function_c (callers)
        child_names = {child["name"] for child in root["children"]}
        assert child_names == {"function_a", "function_c"}

    @pytest.mark.asyncio
    async def test_both_directions(self, sample_indexed_workspace):
        """
        Test bidirectional tracing.

        Setup:
            function_a calls function_b
            function_b calls function_c

        Query: trace_call_path("function_b", direction="both", max_depth=1)

        Expected: Root with callers and callees
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_b",
            direction="both",
            max_depth=1
        )

        assert result["direction"] == "both"

        root = result["root"]
        child_names = {child["name"] for child in root["children"]}

        # Should include both caller (function_a) and callee (function_c)
        assert "function_a" in child_names  # Caller
        assert "function_c" in child_names  # Callee

    @pytest.mark.asyncio
    async def test_max_depth_limiting(self, sample_indexed_workspace):
        """
        Test that max_depth correctly limits traversal depth.

        Setup:
            a calls b calls c calls d calls e

        Query: trace_call_path("a", direction="downstream", max_depth=2)

        Expected: Only traverse to depth 2 (a → b → c), not further
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            direction="downstream",
            max_depth=2
        )

        assert result["max_depth"] == 2
        assert result["max_depth_reached"] == 2
        assert result["truncated"] is True  # We reached max_depth, so traversal was limited

        # Structure: function_a → [function_b, function_c], function_c → function_b
        root = result["root"]
        assert root["name"] == "function_a"
        assert root["depth"] == 0

        # Level 1: function_b and function_c
        assert len(root["children"]) == 2
        child_names = {child["name"] for child in root["children"]}
        assert child_names == {"function_b", "function_c"}

        # Level 2: function_c has one child (function_b), function_b has none
        for child in root["children"]:
            assert child["depth"] == 1
            if child["name"] == "function_c":
                assert len(child["children"]) == 1
                assert child["children"][0]["name"] == "function_b"
                assert child["children"][0]["depth"] == 2
            else:  # function_b
                assert len(child["children"]) == 0

    @pytest.mark.asyncio
    async def test_symbol_not_found(self, sample_indexed_workspace):
        """
        Test error handling when symbol doesn't exist.

        Query: trace_call_path("nonexistent_function")

        Expected: Empty result with total_nodes=0, or error message
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="nonexistent_function",
            direction="downstream",
            max_depth=3
        )

        # Should return empty result or error
        assert result["query_symbol"] == "nonexistent_function"
        assert result["total_nodes"] == 0 or "error" in result

    @pytest.mark.asyncio
    async def test_symbol_with_no_relationships(self, sample_indexed_workspace):
        """
        Test symbol that exists but has no relationships.

        Setup:
            isolated_function() exists but calls nothing and is called by nothing

        Query: trace_call_path("isolated_function")

        Expected: Root node only, total_nodes=1
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="isolated_function",
            direction="both",
            max_depth=3
        )

        assert result["total_nodes"] == 1
        assert result["truncated"] is False

        root = result["root"]
        assert root["name"] == "isolated_function"
        assert len(root["children"]) == 0
