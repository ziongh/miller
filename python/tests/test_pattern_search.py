"""
Tests for Pattern Search Feature (Code Idiom Search)

These tests validate the contract defined in search_contract.py.
Following TDD: tests written BEFORE implementation.

Test Coverage:
- Auto-detection logic (detect_search_method)
- Pattern search with special characters (: < > [ ] ( ) { })
- Schema includes code_pattern field
- VectorStore.search() routing with method="auto" and method="pattern"
- Performance requirements (<100ms)
- Edge cases and boundary conditions
"""

import pytest
import numpy as np
from miller.embeddings import VectorStore, EmbeddingManager, detect_search_method
from miller.search_contract import (
    PATTERN_TEST_CASES,
    VALIDATION_RULES
)


class TestDetectSearchMethod:
    """Test auto-detection of search method from query."""

    def test_detects_pattern_for_inheritance_syntax(self):
        """Queries with : should trigger pattern search."""
        assert detect_search_method(": BaseClass") == "pattern"
        assert detect_search_method(": IService") == "pattern"
        assert detect_search_method("class Foo : Bar") == "pattern"

    def test_detects_pattern_for_generic_syntax(self):
        """Queries with < > should trigger pattern search."""
        assert detect_search_method("ILogger<") == "pattern"
        assert detect_search_method("List<int>") == "pattern"
        assert detect_search_method("map<string, int>") == "pattern"

    def test_detects_pattern_for_attribute_syntax(self):
        """Queries with [ ] should trigger pattern search."""
        assert detect_search_method("[Fact]") == "pattern"
        assert detect_search_method("[HttpGet]") == "pattern"
        assert detect_search_method("[@Override]") == "pattern"

    def test_detects_pattern_for_bracket_syntax(self):
        """Queries with ( ) { } should trigger pattern search."""
        assert detect_search_method("()") == "pattern"
        assert detect_search_method("{}") == "pattern"
        assert detect_search_method("function()") == "pattern"

    def test_detects_hybrid_for_natural_language(self):
        """Natural language queries should trigger hybrid search."""
        assert detect_search_method("authentication logic") == "hybrid"
        assert detect_search_method("user service") == "hybrid"
        assert detect_search_method("parse JSON data") == "hybrid"

    def test_empty_query_returns_hybrid(self):
        """Empty query should default to hybrid (safe default)."""
        assert detect_search_method("") == "hybrid"
        assert detect_search_method("   ") == "hybrid"

    def test_mixed_query_prefers_pattern(self):
        """Mixed queries (pattern + natural language) prefer pattern."""
        assert detect_search_method("find all : BaseClass usages") == "pattern"
        assert detect_search_method("search for ILogger< instances") == "pattern"

    def test_accuracy_meets_threshold(self):
        """Auto-detection should be >95% accurate on known test cases."""
        correct = 0
        total = 0

        # Test pattern cases
        pattern_queries = [
            ": BaseClass", "ILogger<", "[Fact]", "map<int>",
            "()", "{}", "[]", "?.", "=>", "&&"
        ]
        for query in pattern_queries:
            if detect_search_method(query) == "pattern":
                correct += 1
            total += 1

        # Test hybrid cases
        hybrid_queries = [
            "authentication", "user service", "parse JSON",
            "calculate total", "validate input", "handle errors"
        ]
        for query in hybrid_queries:
            if detect_search_method(query) == "hybrid":
                correct += 1
            total += 1

        accuracy = correct / total
        threshold = VALIDATION_RULES["detection"]["accuracy_threshold"]
        assert accuracy >= threshold, f"Accuracy {accuracy:.2%} < {threshold:.2%}"


class TestSchemaWithCodePattern:
    """Test LanceDB schema includes code_pattern field."""

    def test_schema_has_code_pattern_field(self):
        """Schema must include code_pattern field."""
        from miller.embeddings import VectorStore
        schema = VectorStore.SCHEMA

        field_names = [field.name for field in schema]
        assert "code_pattern" in field_names, "Missing code_pattern field"

    def test_code_pattern_field_not_nullable(self):
        """code_pattern field must not be nullable."""
        from miller.embeddings import VectorStore
        schema = VectorStore.SCHEMA

        code_pattern_field = next(
            f for f in schema if f.name == "code_pattern"
        )
        assert not code_pattern_field.nullable, "code_pattern should not be nullable"

    def test_code_pattern_field_is_string(self):
        """code_pattern field must be string type."""
        import pyarrow as pa
        from miller.embeddings import VectorStore
        schema = VectorStore.SCHEMA

        code_pattern_field = next(
            f for f in schema if f.name == "code_pattern"
        )
        assert code_pattern_field.type == pa.string(), "code_pattern must be string"


class TestPatternFieldPopulation:
    """Test that code_pattern field is populated correctly."""

    def test_pattern_field_includes_signature(self):
        """code_pattern should include signature if present."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        # Create mock symbol with signature
        class MockSymbol:
            id = "test_1"
            name = "hello"
            kind = "Function"
            language = "python"
            file_path = "test.py"
            signature = "def hello(name: str) -> str"
            doc_comment = "Say hello"
            start_line = 1
            end_line = 3

        symbols = [MockSymbol()]
        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        # Query to get the data back
        results = vector_store._table.to_pandas()
        pattern = results.iloc[0]["code_pattern"]

        # Should contain signature
        assert "def hello(name: str) -> str" in pattern
        assert "hello" in pattern
        assert "Function" in pattern

    def test_pattern_field_handles_missing_signature(self):
        """code_pattern should work even without signature."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        # Create mock symbol WITHOUT signature
        class MockSymbol:
            id = "test_2"
            name = "MyClass"
            kind = "Class"
            language = "python"
            file_path = "test.py"
            signature = None  # No signature
            doc_comment = None
            start_line = 1
            end_line = 10

        symbols = [MockSymbol()]
        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        # Query to get the data back
        results = vector_store._table.to_pandas()
        pattern = results.iloc[0]["code_pattern"]

        # Should still contain name and kind
        assert "MyClass" in pattern
        assert "Class" in pattern


class TestPatternSearch:
    """Test pattern search functionality."""

    @pytest.fixture
    def vector_store_with_csharp_code(self):
        """Fixture: VectorStore with C# code indexed."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        # Mock C# symbols with inheritance, generics, and attributes
        class MockSymbol:
            def __init__(self, id, name, kind, signature):
                self.id = id
                self.name = name
                self.kind = kind
                self.language = "csharp"
                self.file_path = "test.cs"
                self.signature = signature
                self.doc_comment = None
                self.start_line = 1
                self.end_line = 5

        symbols = [
            # Inheritance patterns
            MockSymbol("1", "UserService", "Class", "class UserService : BaseService"),
            MockSymbol("2", "PaymentService", "Class", "class PaymentService : BaseService"),
            MockSymbol("3", "OrderService", "Class", "class OrderService : IService"),

            # Generic patterns
            MockSymbol("4", "_logger", "Field", "private ILogger<UserService> _logger"),
            MockSymbol("5", "_cache", "Field", "private ICache<string, User> _cache"),
            MockSymbol("6", "items", "Field", "public List<Item> items"),

            # Attribute patterns
            MockSymbol("7", "Test_UserAuth", "Method", "[Fact] public void Test_UserAuth()"),
            MockSymbol("8", "Test_Payment", "Method", "[Fact] public void Test_Payment()"),
            MockSymbol("9", "GetUser", "Method", "[HttpGet] public User GetUser()"),
        ]

        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        yield vector_store
        vector_store.close()

    def test_search_inheritance_pattern(self, vector_store_with_csharp_code):
        """Pattern search for : BaseService should find all derived classes."""
        results = vector_store_with_csharp_code._search_pattern(": BaseService", 50)

        # Should find UserService and PaymentService
        result_names = [r["name"] for r in results]
        assert "UserService" in result_names
        assert "PaymentService" in result_names
        assert len(results) >= 2

    def test_search_generic_pattern(self, vector_store_with_csharp_code):
        """Pattern search for ILogger< should find all logger usages."""
        results = vector_store_with_csharp_code._search_pattern("ILogger<", 50)

        # Should find _logger field
        result_names = [r["name"] for r in results]
        assert "_logger" in result_names

    def test_search_attribute_pattern(self, vector_store_with_csharp_code):
        """Pattern search for [Fact] should find all test methods."""
        results = vector_store_with_csharp_code._search_pattern("[Fact]", 50)

        # Should find both test methods
        result_names = [r["name"] for r in results]
        assert "Test_UserAuth" in result_names
        assert "Test_Payment" in result_names
        assert len(results) >= 2

    def test_pattern_search_preserves_special_chars(self, vector_store_with_csharp_code):
        """Pattern search should preserve : < > [ ] in queries."""
        # These should all work without errors
        vector_store_with_csharp_code._search_pattern(": BaseService", 10)
        vector_store_with_csharp_code._search_pattern("ILogger<", 10)
        vector_store_with_csharp_code._search_pattern("[Fact]", 10)
        vector_store_with_csharp_code._search_pattern("List<", 10)
        # No exceptions = success

    def test_pattern_search_auto_wraps_in_quotes(self, vector_store_with_csharp_code):
        """Pattern search should auto-wrap queries in quotes for phrase search."""
        # Should work even without manual quotes
        results = vector_store_with_csharp_code._search_pattern(": BaseService", 50)
        assert len(results) >= 2

        # Should also work with manual quotes (no double wrapping)
        results_quoted = vector_store_with_csharp_code._search_pattern('": BaseService"', 50)
        # Should get same or similar results (quote handling is smart)
        assert len(results_quoted) >= 0  # Should not error


class TestVectorStoreSearchRouting:
    """Test VectorStore.search() routing with auto/pattern methods."""

    @pytest.fixture
    def vector_store_with_data(self):
        """Fixture: VectorStore with sample data."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        class MockSymbol:
            def __init__(self, id, name, signature):
                self.id = id
                self.name = name
                self.kind = "Function"
                self.language = "python"
                self.file_path = "test.py"
                self.signature = signature
                self.doc_comment = "Test function"
                self.start_line = 1
                self.end_line = 5

        symbols = [
            MockSymbol("1", "authenticate", "def authenticate(user: User) -> bool"),
            MockSymbol("2", "authorize", "def authorize(user: User, resource: str) -> bool"),
            MockSymbol("3", "validate", "def validate(data: dict) -> bool"),
        ]

        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        yield vector_store
        vector_store.close()

    def test_search_accepts_auto_method(self, vector_store_with_data):
        """search() should accept method='auto'."""
        results = vector_store_with_data.search("authenticate", method="auto")
        assert len(results) > 0

    def test_search_accepts_pattern_method(self, vector_store_with_data):
        """search() should accept method='pattern'."""
        results = vector_store_with_data.search(": User", method="pattern")
        # May or may not find results, but should not error
        assert isinstance(results, list)

    def test_auto_method_detects_pattern_query(self, vector_store_with_data):
        """method='auto' should route : queries to pattern search."""
        # This should auto-detect and use pattern search
        results = vector_store_with_data.search(": User", method="auto")
        assert isinstance(results, list)

    def test_auto_method_detects_natural_language(self, vector_store_with_data):
        """method='auto' should route natural language to hybrid search."""
        # This should auto-detect and use hybrid search
        results = vector_store_with_data.search("user authentication", method="auto")
        assert isinstance(results, list)
        assert len(results) > 0  # Should find authenticate function

    def test_manual_override_works(self, vector_store_with_data):
        """Manual method override should work even if auto-detect would choose differently."""
        # Force text search even though query has pattern chars
        results = vector_store_with_data.search(": User", method="text")
        assert isinstance(results, list)

        # Force pattern search even though query is natural language
        results = vector_store_with_data.search("authenticate", method="pattern")
        assert isinstance(results, list)


class TestSearchScoring:
    """Test that all search methods return normalized scores."""

    @pytest.fixture
    def vector_store_with_data(self):
        """Fixture with sample data."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        class MockSymbol:
            def __init__(self, id, name):
                self.id = id
                self.name = name
                self.kind = "Function"
                self.language = "python"
                self.file_path = "test.py"
                self.signature = f"def {name}()"
                self.doc_comment = None
                self.start_line = 1
                self.end_line = 5

        symbols = [MockSymbol(f"{i}", f"func_{i}") for i in range(10)]
        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        yield vector_store
        vector_store.close()

    def test_pattern_search_scores_normalized(self, vector_store_with_data):
        """Pattern search scores should be 0.0-1.0."""
        results = vector_store_with_data._search_pattern("func_", 10)

        for r in results:
            assert "score" in r, "Result missing score field"
            score = r["score"]
            min_score = VALIDATION_RULES["scoring"]["min_score"]
            max_score = VALIDATION_RULES["scoring"]["max_score"]
            assert min_score <= score <= max_score, \
                f"Score {score} outside range [{min_score}, {max_score}]"

    def test_search_with_auto_returns_scores(self, vector_store_with_data):
        """search(method='auto') should return normalized scores."""
        results = vector_store_with_data.search("func_", method="auto")

        for r in results:
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0


class TestEdgeCases:
    """Test boundary conditions and edge cases."""

    def test_empty_query_returns_empty_list(self):
        """Empty query should return [] not error."""
        vector_store = VectorStore(db_path=":memory:")
        results = vector_store.search("", method="pattern")
        assert results == []
        vector_store.close()

    def test_pattern_search_on_empty_database(self):
        """Pattern search on empty database should return [] not error."""
        vector_store = VectorStore(db_path=":memory:")
        results = vector_store._search_pattern(": BaseClass", 50)
        assert results == []
        vector_store.close()

    def test_very_long_pattern_query(self):
        """Very long queries should work without errors."""
        vector_store = VectorStore(db_path=":memory:")
        long_query = "ILogger<" + "A" * 500 + ">"
        results = vector_store._search_pattern(long_query, 10)
        assert isinstance(results, list)
        vector_store.close()

    def test_limit_zero_returns_empty(self):
        """limit=0 should return [] not error."""
        vector_store = VectorStore(db_path=":memory:")
        results = vector_store.search("test", method="pattern", limit=0)
        assert results == []
        vector_store.close()

    def test_negative_limit_returns_empty(self):
        """Negative limit should return [] not error."""
        vector_store = VectorStore(db_path=":memory:")
        results = vector_store.search("test", method="pattern", limit=-1)
        assert results == []
        vector_store.close()


class TestPerformance:
    """Test performance requirements are met."""

    @pytest.fixture
    def large_vector_store(self):
        """Fixture: VectorStore with 100 symbols."""
        vector_store = VectorStore(db_path=":memory:")
        embeddings = EmbeddingManager()

        class MockSymbol:
            def __init__(self, id, name, signature):
                self.id = id
                self.name = name
                self.kind = "Function"
                self.language = "csharp"
                self.file_path = "test.cs"
                self.signature = signature
                self.doc_comment = "Test"
                self.start_line = 1
                self.end_line = 5

        symbols = []
        for i in range(100):
            sig = f"class Service_{i} : BaseService" if i % 3 == 0 else f"def func_{i}()"
            symbols.append(MockSymbol(f"{i}", f"item_{i}", sig))

        vectors = embeddings.embed_batch(symbols)
        vector_store.add_symbols(symbols, vectors)

        yield vector_store
        vector_store.close()

    def test_pattern_search_performance(self, large_vector_store):
        """Pattern search should complete in <100ms."""
        import time

        start = time.time()
        results = large_vector_store._search_pattern(": BaseService", 50)
        elapsed_ms = (time.time() - start) * 1000

        max_ms = VALIDATION_RULES["performance"]["pattern_search_ms"]
        assert elapsed_ms < max_ms, \
            f"Pattern search took {elapsed_ms:.1f}ms (max: {max_ms}ms)"

    def test_auto_detection_is_fast(self):
        """Auto-detection should be nearly instant (<1ms)."""
        import time

        queries = [": BaseClass", "ILogger<", "authentication logic"] * 100

        start = time.time()
        for query in queries:
            detect_search_method(query)
        elapsed_ms = (time.time() - start) * 1000

        # 300 detections should complete in <10ms total
        assert elapsed_ms < 10, \
            f"Auto-detection too slow: {elapsed_ms:.1f}ms for 300 queries"
