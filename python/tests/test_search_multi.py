"""
Tests for cross-workspace search functionality.

Tests the fast_search_multi tool which allows searching across
multiple indexed workspaces simultaneously.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from miller.tools.search_multi import (
    fast_search_multi,
    _format_multi_search_as_text,
)


class TestFormatMultiSearchAsText:
    """Test the text formatting helper for multi-workspace results."""

    def test_empty_results_single_workspace(self):
        """Should show helpful message when no results found."""
        result = _format_multi_search_as_text([], "auth", ["workspace_abc"])
        assert "No matches" in result
        assert '"auth"' in result
        assert "workspace_abc" in result

    def test_empty_results_multiple_workspaces(self):
        """Should list workspaces when no results found."""
        result = _format_multi_search_as_text([], "query", ["ws1", "ws2", "ws3"])
        assert "No matches" in result
        assert "ws1" in result
        assert "ws2" in result
        assert "ws3" in result

    def test_empty_results_many_workspaces_truncates(self):
        """Should truncate workspace list when many are searched."""
        workspaces = ["ws1", "ws2", "ws3", "ws4", "ws5"]
        result = _format_multi_search_as_text([], "query", workspaces)
        assert "No matches" in result
        assert "+2 more" in result

    def test_single_result_with_workspace_attribution(self):
        """Should include workspace prefix in output."""
        results = [
            {
                "workspace": "workspace_abc",
                "file_path": "src/auth.py",
                "start_line": 42,
                "name": "authenticate",
                "kind": "function",
            }
        ]
        result = _format_multi_search_as_text(results, "auth", ["workspace_abc"])

        assert "1 match" in result
        assert "[workspace_abc]" in result
        assert "src/auth.py:42" in result
        assert "authenticate" in result

    def test_multiple_results_from_different_workspaces(self):
        """Should show results from multiple workspaces with attribution."""
        results = [
            {
                "workspace": "ws1",
                "file_path": "a.py",
                "start_line": 10,
                "name": "foo",
                "kind": "function",
            },
            {
                "workspace": "ws2",
                "file_path": "b.py",
                "start_line": 20,
                "name": "bar",
                "kind": "class",
            },
        ]
        result = _format_multi_search_as_text(results, "test", ["ws1", "ws2"])

        assert "2 matches" in result
        assert "2 workspaces" in result
        assert "[ws1]" in result
        assert "[ws2]" in result
        assert "a.py:10" in result
        assert "b.py:20" in result

    def test_results_with_code_context(self):
        """Should include code context when available."""
        results = [
            {
                "workspace": "ws1",
                "file_path": "test.py",
                "start_line": 5,
                "name": "test_func",
                "kind": "function",
                "code_context": "def test_func():\n    pass",
            }
        ]
        result = _format_multi_search_as_text(results, "test", ["ws1"])

        assert "def test_func():" in result
        assert "pass" in result

    def test_results_with_signature_fallback(self):
        """Should use signature when code_context is not available."""
        results = [
            {
                "workspace": "ws1",
                "file_path": "test.py",
                "start_line": 5,
                "name": "my_func",
                "kind": "function",
                "signature": "def my_func(a: int, b: str) -> bool:",
            }
        ]
        result = _format_multi_search_as_text(results, "func", ["ws1"])

        assert "def my_func(a: int, b: str) -> bool:" in result

    def test_results_with_name_kind_fallback(self):
        """Should show name (kind) when neither code_context nor signature available."""
        results = [
            {
                "workspace": "ws1",
                "file_path": "test.py",
                "start_line": 5,
                "name": "MyClass",
                "kind": "class",
            }
        ]
        result = _format_multi_search_as_text(results, "class", ["ws1"])

        assert "MyClass (class)" in result


class TestFastSearchMultiIntegration:
    """Integration tests for fast_search_multi function."""

    @pytest.mark.asyncio
    async def test_no_workspaces_registered(self):
        """Should return helpful message when no workspaces exist."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = []
            MockRegistry.return_value = mock_instance

            result = await fast_search_multi(
                query="test",
                output_format="text",
            )

            assert "No workspaces available" in result
            assert "manage_workspace" in result

    @pytest.mark.asyncio
    async def test_invalid_workspace_ids_ignored(self):
        """Should skip invalid workspace IDs and search valid ones."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.get_workspace.side_effect = lambda ws: (
                MagicMock() if ws == "valid_ws" else None
            )
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                mock_search.return_value = []

                result = await fast_search_multi(
                    query="test",
                    workspaces=["valid_ws", "invalid_ws"],
                    output_format="json",
                )

                # Should only search the valid workspace
                mock_search.assert_called_once()
                call_args = mock_search.call_args
                assert call_args.kwargs["workspace"] == "valid_ws"

    @pytest.mark.asyncio
    async def test_searches_all_workspaces_when_none_specified(self):
        """Should search all registered workspaces when workspaces=None."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [
                {"workspace_id": "ws1"},
                {"workspace_id": "ws2"},
            ]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                mock_search.return_value = []

                await fast_search_multi(
                    query="test",
                    workspaces=None,
                    output_format="json",
                )

                # Should call search for each workspace
                assert mock_search.call_count == 2

    @pytest.mark.asyncio
    async def test_adds_workspace_attribution_to_results(self):
        """Should add workspace field to each result."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [{"workspace_id": "ws1"}]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                mock_search.return_value = [
                    {"name": "test_func", "file_path": "test.py", "start_line": 10}
                ]

                result = await fast_search_multi(
                    query="test",
                    output_format="json",
                    rerank=False,
                )

                assert len(result) == 1
                assert result[0]["workspace"] == "ws1"

    @pytest.mark.asyncio
    async def test_merges_results_from_multiple_workspaces(self):
        """Should merge results from all searched workspaces."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [
                {"workspace_id": "ws1"},
                {"workspace_id": "ws2"},
            ]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                # Return different results for each workspace
                async def search_side_effect(**kwargs):
                    ws = kwargs.get("workspace")
                    if ws == "ws1":
                        return [{"name": "func1", "file_path": "a.py", "start_line": 1}]
                    else:
                        return [{"name": "func2", "file_path": "b.py", "start_line": 2}]

                mock_search.side_effect = search_side_effect

                result = await fast_search_multi(
                    query="test",
                    output_format="json",
                    rerank=False,
                )

                assert len(result) == 2
                workspaces = {r["workspace"] for r in result}
                assert workspaces == {"ws1", "ws2"}

    @pytest.mark.asyncio
    async def test_respects_limit_after_merging(self):
        """Should limit total results after merging."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [
                {"workspace_id": "ws1"},
                {"workspace_id": "ws2"},
            ]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                # Each workspace returns 10 results
                async def search_side_effect(**kwargs):
                    return [
                        {"name": f"func{i}", "file_path": "test.py", "start_line": i}
                        for i in range(10)
                    ]
                mock_search.side_effect = search_side_effect

                result = await fast_search_multi(
                    query="test",
                    limit=5,
                    output_format="json",
                    rerank=False,
                )

                # Should limit to 5 total results
                assert len(result) == 5

    @pytest.mark.asyncio
    async def test_text_output_format(self):
        """Should format results as text when requested."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [{"workspace_id": "ws1"}]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                mock_search.return_value = [
                    {
                        "name": "test_func",
                        "file_path": "test.py",
                        "start_line": 10,
                        "kind": "function",
                    }
                ]

                result = await fast_search_multi(
                    query="test",
                    output_format="text",
                    rerank=False,
                )

                assert isinstance(result, str)
                assert "[ws1]" in result
                assert "test.py:10" in result

    @pytest.mark.asyncio
    async def test_handles_search_errors_gracefully(self):
        """Should continue searching other workspaces if one fails."""
        with patch("miller.tools.search_multi.WorkspaceRegistry") as MockRegistry:
            mock_instance = MagicMock()
            mock_instance.list_workspaces.return_value = [
                {"workspace_id": "ws1"},
                {"workspace_id": "ws2"},
            ]
            MockRegistry.return_value = mock_instance

            with patch(
                "miller.tools.search_multi.single_workspace_search",
                new_callable=AsyncMock,
            ) as mock_search:
                # First workspace fails, second succeeds
                async def search_side_effect(**kwargs):
                    ws = kwargs.get("workspace")
                    if ws == "ws1":
                        raise Exception("Search failed")
                    return [{"name": "func", "file_path": "b.py", "start_line": 1}]

                mock_search.side_effect = search_side_effect

                result = await fast_search_multi(
                    query="test",
                    output_format="json",
                    rerank=False,
                )

                # Should still get results from ws2
                assert len(result) == 1
                assert result[0]["workspace"] == "ws2"
