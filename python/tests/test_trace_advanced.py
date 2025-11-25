"""
Tests for trace_call_path advanced functionality.

TDD Phase 2: Write tests BEFORE implementation.
These tests define behavior for:
- Cross-language call tracing with naming variants
- Semantic similarity fallback matching
- Circular reference handling
- Ambiguous symbol disambiguation
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


class TestCrossLanguageTracing:
    """Test cross-language call tracing using naming variants."""

    @pytest.mark.asyncio
    async def test_typescript_to_python_via_variant(self, cross_language_workspace):
        """
        Test TypeScript → Python tracing via naming variant.

        Setup:
            TypeScript: UserService class
            Python: user_service function (calls UserService via API)

        Query: trace_call_path("UserService", direction="downstream")

        Expected: TypeScript UserService → Python user_service (variant match)
        """
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="UserService",
            direction="downstream",
            max_depth=2
        )

        root = result["root"]
        assert root["name"] == "UserService"
        assert root["language"] == "typescript"

        # Should find Python user_service via naming variant
        assert len(root["children"]) > 0
        python_match = next(
            (child for child in root["children"] if child["name"] == "user_service"),
            None
        )
        assert python_match is not None
        assert python_match["language"] == "python"
        assert python_match["match_type"] == "variant"

    @pytest.mark.asyncio
    async def test_python_model_to_sql_table(self, cross_language_workspace):
        """
        Test Python model → SQL table via pluralization.

        Setup:
            Python: User class (ORM model)
            SQL: users table

        Query: trace_call_path("User", direction="downstream")

        Expected: Python User → SQL users (via pluralization variant)
        """
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="User",
            direction="downstream",
            max_depth=2
        )

        root = result["root"]
        assert root["name"] == "User"
        assert root["language"] == "python"

        # Should find SQL users table via pluralization
        sql_match = next(
            (child for child in root["children"] if child["name"] == "users"),
            None
        )
        assert sql_match is not None
        assert sql_match["language"] == "sql"
        assert sql_match["match_type"] == "variant"

    @pytest.mark.asyncio
    async def test_interface_prefix_stripping(self, cross_language_workspace):
        """
        Test interface prefix stripping (IUser → User).

        Setup:
            TypeScript: IUser interface
            Python: User class

        Query: trace_call_path("IUser", direction="downstream")

        Expected: TypeScript IUser → Python User (via prefix stripping)
        """
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="IUser",
            direction="downstream",
            max_depth=2
        )

        root = result["root"]
        assert root["name"] == "IUser"

        # Should find Python User via prefix stripping
        python_match = next(
            (child for child in root["children"] if child["name"] == "User"),
            None
        )
        assert python_match is not None
        assert python_match["match_type"] == "variant"

    @pytest.mark.asyncio
    async def test_dto_suffix_stripping(self, cross_language_workspace):
        """
        Test DTO suffix stripping (UserDto → User).

        Setup:
            C#: UserDto class
            Python: User class

        Query: trace_call_path("UserDto", direction="downstream")

        Expected: C# UserDto → Python User (via suffix stripping)
        """
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="UserDto",
            direction="downstream",
            max_depth=2
        )

        root = result["root"]
        assert root["name"] == "UserDto"

        python_match = next(
            (child for child in root["children"] if child["name"] == "User"),
            None
        )
        assert python_match is not None
        assert python_match["match_type"] == "variant"


class TestSemanticMatching:
    """Test finding related symbols through various match types."""

    @pytest.mark.asyncio
    async def test_finds_related_via_database(self, semantic_workspace):
        """
        Test that relationships in the database are found.

        Setup:
            Python: calculate_user_age function
            Python: get_age_for_user function (has database relationship)

        Query: trace_call_path("calculate_user_age", direction="downstream")

        Expected: Should find get_age_for_user via database relationship
        (match_type will be "exact" since found via DB, not vector search)

        NOTE: TRUE semantic discovery (finding without relationships) is
        tested in test_semantic_discovery.py
        """
        from miller.tools.trace import trace_call_path

        storage = semantic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="calculate_user_age",
            direction="downstream",
            max_depth=2,
            enable_semantic=True
        )

        root = result["root"]

        # Should find related function via database relationship
        child_names = {child["name"] for child in root["children"]}
        assert "get_age_for_user" in child_names, (
            "Expected to find get_age_for_user via database relationship"
        )

    @pytest.mark.asyncio
    async def test_semantic_below_threshold(self, semantic_workspace):
        """
        Test that low-confidence semantic matches are excluded.

        Setup:
            Python: calculate_user_age
            Python: delete_user_account (semantically different)

        Expected: delete_user_account should NOT appear (similarity < 0.7)
        """
        from miller.tools.trace import trace_call_path

        storage = semantic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="calculate_user_age",
            direction="downstream",
            max_depth=2,
            enable_semantic=True
        )

        root = result["root"]
        child_names = {child["name"] for child in root["children"]}

        # delete_user_account should NOT match (different concept)
        assert "delete_user_account" not in child_names


class TestCycleHandling:
    """Test handling of circular references."""

    @pytest.mark.asyncio
    async def test_direct_cycle(self, cyclic_workspace):
        """
        Test direct cycle (A calls B, B calls A).

        Setup:
            function_a calls function_b
            function_b calls function_a

        Query: trace_call_path("function_a", direction="downstream", max_depth=5)

        Expected: Should detect cycle and not infinitely recurse
        """
        from miller.tools.trace import trace_call_path

        storage = cyclic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            direction="downstream",
            max_depth=5
        )

        # Should complete without infinite recursion
        assert result["nodes_visited"] < 100  # Sanity check

        # Metadata should indicate cycle was detected
        assert "cycles_detected" in result or result["nodes_visited"] > result["total_nodes"]

    @pytest.mark.asyncio
    async def test_indirect_cycle(self, cyclic_workspace):
        """
        Test indirect cycle (A → B → C → A).

        Setup:
            a calls b calls c calls a

        Query: trace_call_path("a", direction="downstream", max_depth=10)

        Expected: Should detect cycle and handle gracefully
        """
        from miller.tools.trace import trace_call_path

        storage = cyclic_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="a",
            direction="downstream",
            max_depth=10
        )

        # Should complete without error
        assert "error" not in result or result.get("error") is None

        # Should not visit the same symbol infinitely
        assert result["nodes_visited"] < 50


class TestAmbiguousSymbols:
    """Test handling of symbols with same name in different files."""

    @pytest.mark.asyncio
    async def test_multiple_symbols_same_name(self, ambiguous_workspace):
        """
        Test when multiple symbols have the same name.

        Setup:
            src/user.py: User class
            src/admin.py: User class

        Query: trace_call_path("User")

        Expected: Should return paths for both User symbols
        """
        from miller.tools.trace import trace_call_path

        storage = ambiguous_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="User",
            direction="downstream",
            max_depth=2
        )

        # Should find both User symbols
        assert result["total_nodes"] >= 2  # At least 2 roots (one per file)

    @pytest.mark.asyncio
    async def test_context_file_disambiguation(self, ambiguous_workspace):
        """
        Test using context_file to disambiguate symbols.

        Setup:
            src/user.py: User class
            src/admin.py: User class

        Query: trace_call_path("User", context_file="src/user.py")

        Expected: Should only trace User from src/user.py
        """
        from miller.tools.trace import trace_call_path

        storage = ambiguous_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="User",
            context_file="src/user.py",
            direction="downstream",
            max_depth=2
        )

        root = result["root"]
        assert root["file_path"] == "src/user.py"
