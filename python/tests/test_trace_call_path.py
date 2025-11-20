"""
Tests for trace_call_path tool.

TDD Phase 2: Write tests BEFORE implementation.
These tests define the exact behavior of cross-language call tracing.
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
            symbol_name="a",
            direction="downstream",
            max_depth=2
        )

        assert result["max_depth"] == 2
        assert result["max_depth_reached"] == 2
        assert result["truncated"] is True  # More nodes exist beyond max_depth

        # Should have a → b → c, but not d or e
        root = result["root"]
        assert root["name"] == "a"
        assert root["depth"] == 0

        # Level 1: b
        assert len(root["children"]) == 1
        level_1 = root["children"][0]
        assert level_1["name"] == "b"
        assert level_1["depth"] == 1

        # Level 2: c
        assert len(level_1["children"]) == 1
        level_2 = level_1["children"][0]
        assert level_2["name"] == "c"
        assert level_2["depth"] == 2

        # No level 3 (d should not be included)
        assert len(level_2["children"]) == 0

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
    """Test semantic similarity fallback when variants don't match."""

    @pytest.mark.asyncio
    async def test_semantic_fallback(self, semantic_workspace):
        """
        Test semantic matching when naming variants don't help.

        Setup:
            Python: calculate_user_age function
            Python: get_age_for_user function (semantically similar)

        Query: trace_call_path("calculate_user_age", direction="downstream")

        Expected: Should find get_age_for_user via semantic similarity
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

        # Should find semantically similar function
        semantic_match = next(
            (child for child in root["children"]
             if child["match_type"] == "semantic"),
            None
        )
        assert semantic_match is not None
        assert semantic_match["confidence"] >= 0.7  # Above threshold

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


class TestOutputFormats:
    """Test different output formats."""

    @pytest.mark.asyncio
    async def test_json_format(self, sample_indexed_workspace):
        """Test JSON output format (default)."""
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            output_format="json"
        )

        assert isinstance(result, dict)
        assert "root" in result
        assert "total_nodes" in result
        assert "execution_time_ms" in result

    @pytest.mark.asyncio
    async def test_tree_format(self, sample_indexed_workspace):
        """
        Test tree output format (human-readable).

        Expected output:
            function_a (python) @ src/main.py:10
            ├─[Call]→ function_b (python) @ src/utils.py:5
            └─[Call]→ function_c (python) @ src/helpers.py:12
        """
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            output_format="tree",
            max_depth=1
        )

        assert isinstance(result, str)
        assert "function_a" in result
        assert "→" in result  # Tree connector
        assert "python" in result  # Language indicator
        assert "src/" in result  # File paths


class TestStatistics:
    """Test statistics and metadata in results."""

    @pytest.mark.asyncio
    async def test_languages_found(self, cross_language_workspace):
        """Test languages_found list."""
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="UserService",
            direction="downstream",
            max_depth=3
        )

        # Should include all languages encountered
        assert "languages_found" in result
        assert "typescript" in result["languages_found"]
        assert "python" in result["languages_found"]

    @pytest.mark.asyncio
    async def test_match_types_counts(self, cross_language_workspace):
        """Test match_types count dictionary."""
        from miller.tools.trace import trace_call_path

        storage = cross_language_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="IUser",
            direction="downstream",
            max_depth=2
        )

        # Should count exact, variant, and semantic matches
        assert "match_types" in result
        assert isinstance(result["match_types"], dict)
        # Should have at least variant matches (IUser → User)
        assert result["match_types"].get("variant", 0) > 0

    @pytest.mark.asyncio
    async def test_relationship_kinds_counts(self, sample_indexed_workspace):
        """Test relationship_kinds count dictionary."""
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            direction="downstream",
            max_depth=2
        )

        # Should count relationship types (Call, Import, Reference, etc.)
        assert "relationship_kinds" in result
        assert isinstance(result["relationship_kinds"], dict)
        assert result["relationship_kinds"].get("Call", 0) > 0

    @pytest.mark.asyncio
    async def test_execution_time(self, sample_indexed_workspace):
        """Test execution_time_ms is recorded."""
        from miller.tools.trace import trace_call_path

        storage = sample_indexed_workspace

        result = await trace_call_path(
            storage=storage,
            symbol_name="function_a",
            direction="downstream",
            max_depth=2
        )

        assert "execution_time_ms" in result
        assert isinstance(result["execution_time_ms"], (int, float))
        assert result["execution_time_ms"] > 0


# Pytest fixtures for test data
@pytest.fixture
def sample_indexed_workspace(tmp_path):
    """
    Create a sample indexed workspace with simple call relationships.

    Structure:
        function_a calls function_b
        function_a calls function_c
        function_c calls function_b
        isolated_function (no relationships)
    """
    from miller.storage import StorageManager
    import miller_core

    # Create temporary database
    db_path = tmp_path / "test.db"
    storage = StorageManager(db_path=str(db_path))

    # Index sample code
    code = """
def function_a():
    function_b()
    function_c()

def function_b():
    pass

def function_c():
    function_b()

def isolated_function():
    pass
"""

    # Extract and store
    result = miller_core.extract_file(code, "python", "test.py")
    storage.add_file("test.py", "python", "hash123", len(code), 0)
    storage.add_symbols_batch(result.symbols, "test.py")
    storage.add_relationships_batch(result.relationships, "test.py")

    return storage


@pytest.fixture
def cross_language_workspace(tmp_path):
    """
    Create workspace with cross-language relationships.

    Structure:
        TypeScript: UserService → Python: user_service
        TypeScript: IUser → Python: User
        Python: User → SQL: users
        C#: UserDto → Python: User
    """
    # TODO: Implement after basic tests pass
    pytest.skip("Cross-language fixture not yet implemented")


@pytest.fixture
def semantic_workspace(tmp_path):
    """Create workspace for testing semantic matching."""
    # TODO: Implement after basic tests pass
    pytest.skip("Semantic workspace fixture not yet implemented")


@pytest.fixture
def cyclic_workspace(tmp_path):
    """Create workspace with circular references."""
    # TODO: Implement after basic tests pass
    pytest.skip("Cyclic workspace fixture not yet implemented")


@pytest.fixture
def ambiguous_workspace(tmp_path):
    """Create workspace with ambiguous symbols (same name, different files)."""
    # TODO: Implement after basic tests pass
    pytest.skip("Ambiguous workspace fixture not yet implemented")
