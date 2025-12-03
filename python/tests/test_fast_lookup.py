"""Tests for fast_lookup tool - smart batch symbol resolution.

TDD: Write tests first, then implement.

fast_lookup replaces fast_goto with:
- Batch lookup (multiple symbols in one call)
- Semantic fallback when exact match fails
- Import path generation
- Lean text output
"""

import pytest


class TestFastLookupBasic:
    """Tests for basic fast_lookup functionality."""

    @pytest.mark.asyncio
    async def test_lookup_single_symbol_exact_match(self, lookup_workspace):
        """fast_lookup finds a single symbol by exact name."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"], storage=lookup_workspace["storage"]
        )

        assert isinstance(result, str)
        assert "TestClass" in result
        assert "✓" in result  # Found indicator
        assert "test.py" in result  # File location

    @pytest.mark.asyncio
    async def test_lookup_multiple_symbols_batch(self, lookup_workspace):
        """fast_lookup finds multiple symbols in one call."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass", "helper_function", "CONSTANT"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "TestClass" in result
        assert "helper_function" in result
        assert "CONSTANT" in result
        # All should be found
        assert result.count("✓") == 3

    @pytest.mark.asyncio
    async def test_lookup_not_found_no_semantic(self, lookup_workspace):
        """fast_lookup shows not found when no match exists."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["CompletelyNonexistentSymbol12345"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "✗" in result  # Not found indicator
        assert "No match found" in result or "not found" in result.lower()


class TestFastLookupSemanticFallback:
    """Tests for semantic fallback when exact match fails."""

    @pytest.mark.asyncio
    async def test_lookup_semantic_fallback_similar_name(self, lookup_workspace_with_vectors):
        """fast_lookup falls back to semantic search for similar names."""
        from miller.tools.navigation import fast_lookup

        # Search for "TestKlass" - should find "TestClass" via semantic
        result = await fast_lookup(
            ["TestKlass"],
            storage=lookup_workspace_with_vectors["storage"],
            vector_store=lookup_workspace_with_vectors["vector_store"],
        )

        assert isinstance(result, str)
        # Should show semantic fallback indicator
        assert "✗" in result and "→" in result  # "✗ → TestClass (semantic"
        assert "semantic" in result.lower()
        assert "TestClass" in result

    @pytest.mark.asyncio
    async def test_lookup_mixed_exact_and_semantic(self, lookup_workspace_with_vectors):
        """fast_lookup handles mix of exact matches and semantic fallbacks."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass", "TestKlass"],  # First exact, second semantic
            storage=lookup_workspace_with_vectors["storage"],
            vector_store=lookup_workspace_with_vectors["vector_store"],
        )

        assert isinstance(result, str)
        # First should be exact match
        assert "TestClass" in result
        # Should have both exact and semantic indicators
        assert "✓" in result  # At least one exact match

    @pytest.mark.asyncio
    async def test_lookup_rejects_low_score_semantic_matches(self, lookup_workspace):
        """fast_lookup rejects semantic matches below 0.80 threshold."""
        from miller.tools.navigation import fast_lookup

        # Create a mock vector store that returns low-score matches
        class LowScoreVectorStore:
            def search(self, query, method="auto", limit=10, **kwargs):
                # Return matches with scores below threshold
                # Note: "id" field matches LanceDB schema (not "symbol_id")
                return [
                    {
                        "id": "sym_something",
                        "name": "SomethingElse",
                        "kind": "class",
                        "file_path": "other.py",
                        "start_line": 1,
                        "score": 0.75,  # Below 0.80 threshold
                    },
                    {
                        "id": "sym_another",
                        "name": "AnotherThing",
                        "kind": "function",
                        "file_path": "another.py",
                        "start_line": 5,
                        "score": 0.65,  # Well below threshold
                    },
                ]

        result = await fast_lookup(
            ["NonExistentSymbol"],
            storage=lookup_workspace["storage"],
            vector_store=LowScoreVectorStore(),
        )

        assert isinstance(result, str)
        # Should NOT find a match - scores too low
        assert "✗" in result
        assert "No match found" in result
        # Should NOT show semantic match indicator
        assert "SomethingElse" not in result
        assert "AnotherThing" not in result

    @pytest.mark.asyncio
    async def test_lookup_accepts_high_score_semantic_matches(self, lookup_workspace):
        """fast_lookup accepts semantic matches at or above 0.80 threshold."""
        from miller.tools.navigation import fast_lookup

        # Create a mock vector store that returns high-score matches
        # Note: "id" field matches LanceDB schema (not "symbol_id")
        class HighScoreVectorStore:
            def search(self, query, method="auto", limit=10, **kwargs):
                return [
                    {
                        "id": "sym_testclass",  # Matches fixture's symbol ID
                        "name": "TestClass",
                        "kind": "class",
                        "file_path": "test.py",
                        "start_line": 10,
                        "score": 0.85,  # Above 0.80 threshold
                    },
                ]

        result = await fast_lookup(
            ["TstClass"],  # Typo that should match TestClass
            storage=lookup_workspace["storage"],
            vector_store=HighScoreVectorStore(),
        )

        assert isinstance(result, str)
        # Should find TestClass via semantic match (may be fuzzy or vector)
        assert "TestClass" in result
        assert "✗" in result and "→" in result  # Fallback indicator
        # Score should be shown (may be fuzzy 0.89 or vector 0.85)
        assert "0.8" in result  # Score starts with 0.8x


class TestFastLookupVectorStoreFieldNames:
    """Tests for correct handling of LanceDB field names."""

    @pytest.mark.asyncio
    async def test_lookup_uses_id_field_not_symbol_id(self, lookup_workspace):
        """fast_lookup uses 'id' field from LanceDB, not 'symbol_id'.

        LanceDB schema defines the field as 'id', but the code was incorrectly
        looking for 'symbol_id'. This test verifies the fix by using a symbol ID
        that exists in storage but with a different name in the vector result.
        """
        from miller.tools.navigation import fast_lookup

        # Get the actual symbol ID from the fixture's storage
        # The fixture creates a symbol with id starting with "sym_"
        storage = lookup_workspace["storage"]

        # Mock vector store that returns results with 'id' field (matching LanceDB schema)
        # We use the REAL symbol ID from the fixture so get_symbol_by_id will find it
        class CorrectFieldNameVectorStore:
            def search(self, query, method="auto", limit=10, **kwargs):
                return [
                    {
                        "id": "sym_testclass",  # Must match an ID in the fixture
                        "name": "WrongNameInVector",  # Name doesn't match - ID lookup should work
                        "kind": "class",
                        "file_path": "test.py",
                        "start_line": 10,
                        "score": 0.90,
                    },
                ]

        # Use a query that won't match anything via fuzzy search, only vector
        result = await fast_lookup(
            ["XyzNonExistent12345"],  # Won't fuzzy-match anything
            storage=storage,
            vector_store=CorrectFieldNameVectorStore(),
        )

        assert isinstance(result, str)
        # The key test: we should find TestClass (the real symbol in storage)
        # via the ID lookup, not "WrongNameInVector" from the fallback name lookup
        assert "TestClass" in result  # Found via ID lookup from storage
        assert "semantic" in result.lower()


class TestFastLookupImportPaths:
    """Tests for import path generation."""

    @pytest.mark.asyncio
    async def test_lookup_includes_import_statement(self, lookup_workspace):
        """fast_lookup includes import statement for found symbols."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"], storage=lookup_workspace["storage"]
        )

        assert isinstance(result, str)
        # Should include import-like statement
        assert "from" in result or "import" in result

    @pytest.mark.asyncio
    async def test_lookup_relative_import_with_context_file(self, lookup_workspace_multi_file):
        """fast_lookup generates relative imports when context_file provided."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            context_file="src/handlers/auth.py",
            storage=lookup_workspace_multi_file["storage"],
        )

        assert isinstance(result, str)
        # Should have import path relative to context
        assert "from" in result or "import" in result


class TestFastLookupStructure:
    """Tests for symbol structure in output."""

    @pytest.mark.asyncio
    async def test_lookup_shows_signature(self, lookup_workspace):
        """fast_lookup shows symbol signature."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"], storage=lookup_workspace["storage"]
        )

        assert isinstance(result, str)
        # Should show the class signature
        assert "class" in result.lower()

    @pytest.mark.asyncio
    async def test_lookup_shows_methods_at_depth_1(self, lookup_workspace):
        """fast_lookup shows methods/members at max_depth=1."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            max_depth=1,
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        # Should show method names
        assert "test_method" in result

    @pytest.mark.asyncio
    async def test_lookup_depth_0_signature_only(self, lookup_workspace):
        """fast_lookup at max_depth=0 shows only signature."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            max_depth=0,
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        # Should have symbol but maybe not methods
        assert "TestClass" in result

    @pytest.mark.asyncio
    async def test_lookup_include_body(self, lookup_workspace):
        """fast_lookup with include_body shows source code."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            include_body=True,
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        # Should include actual code
        assert "class TestClass" in result or "def" in result


class TestFastLookupOutputFormat:
    """Tests for output format consistency."""

    @pytest.mark.asyncio
    async def test_lookup_header_shows_count(self, lookup_workspace):
        """fast_lookup header shows symbol count."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass", "helper_function"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        # Header should indicate count
        assert "2" in result or "symbols" in result.lower()

    @pytest.mark.asyncio
    async def test_lookup_output_is_lean_text(self, lookup_workspace):
        """fast_lookup returns lean text, not JSON."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"], storage=lookup_workspace["storage"]
        )

        assert isinstance(result, str)
        # Should NOT be JSON
        assert not result.strip().startswith("{")
        assert not result.strip().startswith("[")

    @pytest.mark.asyncio
    async def test_lookup_output_format_json(self, lookup_workspace):
        """fast_lookup with output_format='json' returns list of dicts."""
        from miller.tools.nav_impl.lookup import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            storage=lookup_workspace["storage"],
            output_format="json",
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "TestClass"
        assert result[0]["match_type"] == "exact"

    @pytest.mark.asyncio
    async def test_lookup_output_format_text_default(self, lookup_workspace):
        """fast_lookup defaults to text output format."""
        from miller.tools.nav_impl.lookup import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            storage=lookup_workspace["storage"],
            # No output_format specified - should default to text
        )

        assert isinstance(result, str)
        assert "TestClass" in result
        assert "✓" in result


class TestFastLookupQualifiedNames:
    """Tests for qualified name resolution (Parent.child)."""

    @pytest.mark.asyncio
    async def test_lookup_qualified_name_parent_child(self, lookup_workspace):
        """fast_lookup resolves Parent.child qualified names."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass.test_method"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "test_method" in result
        assert "✓" in result  # Should find it

    @pytest.mark.asyncio
    async def test_lookup_qualified_name_not_found(self, lookup_workspace):
        """fast_lookup handles qualified names where child doesn't exist."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass.nonexistent_method"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "✗" in result  # Not found


class TestFastLookupFuzzyMatching:
    """Tests for fuzzy matching strategies."""

    @pytest.mark.asyncio
    async def test_fuzzy_case_insensitive_match(self, lookup_workspace):
        """fast_lookup finds symbols with different case."""
        from miller.tools.navigation import fast_lookup

        # Search for lowercase version of TestClass
        result = await fast_lookup(
            ["testclass"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "TestClass" in result
        # Should find via case-insensitive match (might be exact or semantic)

    @pytest.mark.asyncio
    async def test_fuzzy_typo_correction_levenshtein(self, lookup_workspace):
        """fast_lookup corrects typos via Levenshtein distance."""
        from miller.tools.navigation import fast_lookup

        # "TestClas" is 1 edit away from "TestClass"
        result = await fast_lookup(
            ["TestClas"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "TestClass" in result
        # Should show semantic/fuzzy match indicator
        assert "→" in result or "semantic" in result.lower()

    @pytest.mark.asyncio
    async def test_fuzzy_substring_match(self, lookup_workspace):
        """fast_lookup finds symbols when query is substring."""
        from miller.tools.navigation import fast_lookup

        # "helper" is substring of "helper_function"
        result = await fast_lookup(
            ["helper"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "helper_function" in result

    @pytest.mark.asyncio
    async def test_fuzzy_double_letter_typo(self, lookup_workspace):
        """fast_lookup handles missing/extra letter typos."""
        from miller.tools.navigation import fast_lookup

        # "TestClasss" has extra 's'
        result = await fast_lookup(
            ["TestClasss"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "TestClass" in result


class TestFastLookupEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_lookup_empty_symbol_list(self, lookup_workspace):
        """fast_lookup handles empty symbol list gracefully."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            [],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "0" in result or "symbol" in result.lower()

    @pytest.mark.asyncio
    async def test_lookup_invalid_workspace(self, lookup_workspace):
        """fast_lookup returns error for invalid workspace."""
        from miller.tools.navigation import fast_lookup

        result = await fast_lookup(
            ["TestClass"],
            workspace="nonexistent_workspace_12345",
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "error" in result.lower() or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_lookup_special_characters_in_name(self, lookup_workspace):
        """fast_lookup handles symbols with special characters safely."""
        from miller.tools.navigation import fast_lookup

        # SQL injection attempt - should not crash
        result = await fast_lookup(
            ["'; DROP TABLE symbols; --"],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "✗" in result  # Not found, but didn't crash

    @pytest.mark.asyncio
    async def test_lookup_very_long_symbol_name(self, lookup_workspace):
        """fast_lookup handles very long symbol names."""
        from miller.tools.navigation import fast_lookup

        long_name = "a" * 500
        result = await fast_lookup(
            [long_name],
            storage=lookup_workspace["storage"],
        )

        assert isinstance(result, str)
        assert "✗" in result  # Not found


class TestFuzzyFindSymbolUnit:
    """Unit tests for _fuzzy_find_symbol function directly."""

    @pytest.mark.asyncio
    async def test_fuzzy_strategy_order(self, lookup_workspace):
        """Verify fuzzy strategies execute in correct order."""
        from miller.tools.navigation import _fuzzy_find_symbol

        storage = lookup_workspace["storage"]
        definition_kinds = ("class", "function", "method")

        # Case-insensitive exact should match first
        result = _fuzzy_find_symbol(storage, "testclass", definition_kinds)
        assert result is not None
        sym, score = result
        assert sym["name"] == "TestClass"
        assert score == 1.0  # Exact case-insensitive match

    @pytest.mark.asyncio
    async def test_fuzzy_levenshtein_score_calculation(self, lookup_workspace):
        """Verify Levenshtein score is calculated correctly."""
        from miller.tools.navigation import _fuzzy_find_symbol

        storage = lookup_workspace["storage"]
        definition_kinds = ("class", "function", "method")

        # "TestClas" -> "TestClass" = 1 edit, score should be high
        result = _fuzzy_find_symbol(storage, "TestClas", definition_kinds)
        assert result is not None
        sym, score = result
        assert sym["name"] == "TestClass"
        assert score >= 0.85  # 8/9 = 0.889


class TestLevenshteinDistance:
    """Unit tests for _levenshtein_distance function."""

    def test_levenshtein_identical_strings(self):
        """Identical strings have distance 0."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("hello", "hello") == 0

    def test_levenshtein_single_insertion(self):
        """Single character insertion has distance 1."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("hello", "helloo") == 1

    def test_levenshtein_single_deletion(self):
        """Single character deletion has distance 1."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("hello", "hell") == 1

    def test_levenshtein_single_substitution(self):
        """Single character substitution has distance 1."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("hello", "hallo") == 1

    def test_levenshtein_empty_string(self):
        """Empty string distance is length of other string."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("", "hello") == 5
        assert _levenshtein_distance("hello", "") == 5

    def test_levenshtein_completely_different(self):
        """Completely different strings have high distance."""
        from miller.tools.navigation import _levenshtein_distance

        assert _levenshtein_distance("abc", "xyz") == 3


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def lookup_workspace(tmp_path):
    """Create a temporary indexed workspace with test symbols."""
    from miller.storage import StorageManager

    db_path = tmp_path / "test.db"
    storage = StorageManager(str(db_path))

    # Add test files
    storage.add_file("test.py", "python", "# test", "hash123", 100)

    # Mock symbol class
    class MockSymbol:
        def __init__(self, id, name, kind, file_path="test.py", parent_id=None, signature=None, start_line=10):
            self.id = id
            self.name = name
            self.kind = kind
            self.language = "python"
            self.file_path = file_path
            self.start_line = start_line
            self.end_line = start_line + 20
            self.start_column = 0
            self.end_column = 0
            self.start_byte = 0
            self.end_byte = 500
            self.signature = signature or (f"class {name}:" if kind == "class" else f"def {name}():")
            self.doc_comment = None
            self.parent_id = parent_id
            self.visibility = "public"
            self.code_context = "class TestClass:\n    def test_method(self):\n        pass"
            self.semantic_group = None
            self.confidence = 1.0
            self.content_type = None

    symbols = [
        MockSymbol("sym_testclass", "TestClass", "class", signature="class TestClass(BaseClass):"),
        MockSymbol("sym_testmethod", "test_method", "method", parent_id="sym_testclass", start_line=12),
        MockSymbol("sym_prop", "my_property", "property", parent_id="sym_testclass", start_line=15),
        MockSymbol("sym_helper", "helper_function", "function", signature="def helper_function(x: int) -> str:", start_line=30),
        MockSymbol("sym_const", "CONSTANT", "constant", signature="CONSTANT = 42", start_line=5),
    ]
    storage.add_symbols_batch(symbols)

    yield {"storage": storage}

    storage.close()


@pytest.fixture
async def lookup_workspace_with_vectors(tmp_path):
    """Create workspace with both SQLite and vector store for semantic tests."""
    from miller.storage import StorageManager

    db_path = tmp_path / "test.db"
    storage = StorageManager(str(db_path))

    # Add test file
    storage.add_file("test.py", "python", "# test", "hash123", 100)

    class MockSymbol:
        def __init__(self, id, name, kind, signature=None):
            self.id = id
            self.name = name
            self.kind = kind
            self.language = "python"
            self.file_path = "test.py"
            self.start_line = 10
            self.end_line = 50
            self.start_column = 0
            self.end_column = 0
            self.start_byte = 0
            self.end_byte = 500
            self.signature = signature or f"class {name}:"
            self.doc_comment = None
            self.parent_id = None
            self.visibility = "public"
            self.code_context = f"class {name}:\n    pass"
            self.semantic_group = None
            self.confidence = 1.0
            self.content_type = None

    symbols = [
        MockSymbol("sym_testclass", "TestClass", "class", signature="class TestClass:"),
    ]
    storage.add_symbols_batch(symbols)

    # Create mock vector store that returns semantic matches
    class MockVectorStore:
        def search(self, query, method="auto", limit=10, **kwargs):
            # Return TestClass as semantic match for anything "Test"-like
            if "test" in query.lower() or "klass" in query.lower():
                return [
                    {
                        "symbol_id": "sym_testclass",
                        "name": "TestClass",
                        "kind": "class",
                        "file_path": "test.py",
                        "start_line": 10,
                        "score": 0.87,
                    }
                ]
            return []

    yield {"storage": storage, "vector_store": MockVectorStore()}

    storage.close()


@pytest.fixture
async def lookup_workspace_multi_file(tmp_path):
    """Create workspace with multiple files for import path tests."""
    from miller.storage import StorageManager

    db_path = tmp_path / "test.db"
    storage = StorageManager(str(db_path))

    # Add multiple files in different locations
    storage.add_file("src/models/user.py", "python", "# user model", "hash1", 50)
    storage.add_file("src/handlers/auth.py", "python", "# auth handler", "hash2", 30)

    class MockSymbol:
        def __init__(self, id, name, kind, file_path, signature=None):
            self.id = id
            self.name = name
            self.kind = kind
            self.language = "python"
            self.file_path = file_path
            self.start_line = 10
            self.end_line = 50
            self.start_column = 0
            self.end_column = 0
            self.start_byte = 0
            self.end_byte = 500
            self.signature = signature or f"class {name}:"
            self.doc_comment = None
            self.parent_id = None
            self.visibility = "public"
            self.code_context = f"class {name}:\n    pass"
            self.semantic_group = None
            self.confidence = 1.0
            self.content_type = None

    symbols = [
        MockSymbol("sym_user", "User", "class", "src/models/user.py", signature="class User(BaseModel):"),
        MockSymbol("sym_testclass", "TestClass", "class", "src/models/user.py", signature="class TestClass:"),
    ]
    storage.add_symbols_batch(symbols)

    yield {"storage": storage}

    storage.close()
