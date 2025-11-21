"""
Search Quality Benchmark Suite

Measures search result quality with representative queries.
Used to validate that improvements actually increase relevance.

Metrics:
- Precision@K: What % of top K results are relevant?
- MRR (Mean Reciprocal Rank): How quickly do we find the first relevant result?
- Token efficiency: How many results needed to get good coverage?
"""

import pytest
import numpy as np
from miller.embeddings import VectorStore, EmbeddingManager


# Benchmark query set with expected relevant results
BENCHMARK_QUERIES = [
    # Simple name searches (should find exact matches first)
    ("authenticate", ["authenticate", "authentication", "authenticateUser"]),
    ("UserService", ["UserService", "user_service", "UserServiceImpl"]),
    ("parse", ["parse", "parser", "parseJSON", "parse_data"]),

    # CamelCase searches (should handle splitting)
    ("parseJSON", ["parseJSON", "parse_json", "JSONParser"]),

    # Natural language queries (should find conceptually related)
    ("user authentication", ["authenticate", "login", "auth", "verifyUser"]),
    ("parse json data", ["parse_json", "json_parser", "parseJSON", "read_json"]),

    # Common patterns
    ("calculate", ["calculate", "calculator", "calculateTotal", "compute"]),
    ("validate", ["validate", "validator", "validation", "check"]),

    # Short queries (challenging - need good ranking)
    ("auth", ["auth", "authenticate", "authorization", "authService"]),
    ("user", ["user", "User", "UserService", "getUser", "createUser"]),
]


class MockSymbol:
    """Mock symbol for testing."""
    def __init__(self, id, name, kind, signature=None, doc_comment=None):
        self.id = id
        self.name = name
        self.kind = kind
        self.language = "python"
        self.file_path = "test.py"
        self.signature = signature or f"def {name}()"
        self.doc_comment = doc_comment
        self.start_line = 1
        self.end_line = 5


@pytest.fixture
def benchmark_vector_store():
    """
    VectorStore with diverse symbols for benchmarking.

    Includes:
    - Exact matches
    - Partial matches
    - CamelCase variants
    - Related terms
    - Noise (unrelated symbols)
    """
    vector_store = VectorStore(db_path=":memory:")
    embeddings = EmbeddingManager()

    symbols = [
        # Authentication-related symbols
        MockSymbol("1", "authenticate", "Function", "def authenticate(user: User) -> bool", "Authenticate user credentials"),
        MockSymbol("2", "authentication", "Class", "class authentication:", "Authentication service"),
        MockSymbol("3", "authenticateUser", "Function", "def authenticateUser(username: str, password: str) -> bool"),
        MockSymbol("4", "auth", "Function", "def auth() -> bool", "Short auth function"),
        MockSymbol("5", "authService", "Class", "class authService:", "Authentication service"),
        MockSymbol("6", "login", "Function", "def login(user: str) -> bool", "Login user"),
        MockSymbol("7", "verifyUser", "Function", "def verifyUser(user: User) -> bool", "Verify user identity"),

        # User-related symbols
        MockSymbol("10", "user", "Variable", "user: User", "Current user"),
        MockSymbol("11", "User", "Class", "class User:", "User model"),
        MockSymbol("12", "UserService", "Class", "class UserService:", "User service"),
        MockSymbol("13", "user_service", "Function", "def user_service() -> UserService"),
        MockSymbol("14", "UserServiceImpl", "Class", "class UserServiceImpl: UserService"),
        MockSymbol("15", "getUser", "Function", "def getUser(id: int) -> User", "Get user by ID"),
        MockSymbol("16", "createUser", "Function", "def createUser(data: dict) -> User", "Create new user"),

        # Parsing-related symbols
        MockSymbol("20", "parse", "Function", "def parse(data: str) -> dict", "Parse data"),
        MockSymbol("21", "parser", "Class", "class parser:", "Parser class"),
        MockSymbol("22", "parseJSON", "Function", "def parseJSON(json: str) -> dict", "Parse JSON string"),
        MockSymbol("23", "parse_json", "Function", "def parse_json(data: str) -> dict", "Parse JSON data"),
        MockSymbol("24", "JSONParser", "Class", "class JSONParser:", "JSON parser"),
        MockSymbol("25", "parse_data", "Function", "def parse_data(raw: str) -> dict", "Parse raw data"),
        MockSymbol("26", "read_json", "Function", "def read_json(file: str) -> dict", "Read JSON file"),

        # Calculation-related symbols
        MockSymbol("30", "calculate", "Function", "def calculate(x: int, y: int) -> int", "Calculate result"),
        MockSymbol("31", "calculator", "Class", "class calculator:", "Calculator class"),
        MockSymbol("32", "calculateTotal", "Function", "def calculateTotal(items: list) -> float", "Calculate total"),
        MockSymbol("33", "compute", "Function", "def compute(values: list) -> float", "Compute values"),

        # Validation-related symbols
        MockSymbol("40", "validate", "Function", "def validate(data: dict) -> bool", "Validate data"),
        MockSymbol("41", "validator", "Class", "class validator:", "Validator class"),
        MockSymbol("42", "validation", "Function", "def validation(input: str) -> bool", "Validation logic"),
        MockSymbol("43", "check", "Function", "def check(value: any) -> bool", "Check value"),

        # Noise symbols (unrelated, should rank low)
        MockSymbol("50", "foo", "Function", "def foo()"),
        MockSymbol("51", "bar", "Function", "def bar()"),
        MockSymbol("52", "baz", "Class", "class baz:"),
        MockSymbol("53", "random_func", "Function", "def random_func()"),
        MockSymbol("54", "unrelated", "Function", "def unrelated()"),
    ]

    vectors = embeddings.embed_batch(symbols)
    vector_store.add_symbols(symbols, vectors)

    yield vector_store
    vector_store.close()


def calculate_precision_at_k(results: list[dict], expected: list[str], k: int = 5) -> float:
    """
    Calculate precision@K: what % of top K results are relevant?

    Args:
        results: Search results (sorted by score)
        expected: List of expected relevant symbol names
        k: Number of top results to consider

    Returns:
        Precision score (0.0-1.0)
    """
    if not results or not expected:
        return 0.0

    top_k = results[:k]
    relevant_count = 0

    for result in top_k:
        result_name = result.get("name", "").lower()
        # Check if result name matches any expected (partial match OK)
        if any(exp.lower() in result_name or result_name in exp.lower() for exp in expected):
            relevant_count += 1

    return relevant_count / k


def calculate_mrr(results: list[dict], expected: list[str]) -> float:
    """
    Calculate Mean Reciprocal Rank: how quickly do we find first relevant result?

    Args:
        results: Search results (sorted by score)
        expected: List of expected relevant symbol names

    Returns:
        MRR score (0.0-1.0, higher is better)
    """
    if not results or not expected:
        return 0.0

    for i, result in enumerate(results):
        result_name = result.get("name", "").lower()
        if any(exp.lower() in result_name or result_name in exp.lower() for exp in expected):
            return 1.0 / (i + 1)

    return 0.0  # No relevant result found


class TestSearchQualityBaseline:
    """
    Baseline measurements BEFORE improvements.

    These tests establish current search quality metrics.
    After implementing improvements, we'll compare against these baselines.
    """

    def test_baseline_precision_at_5(self, benchmark_vector_store):
        """Measure current precision@5 across benchmark queries."""
        precisions = []

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=20)
            precision = calculate_precision_at_k(results, expected, k=5)
            precisions.append(precision)

            # Debug output (remove after baseline established)
            print(f"\nQuery: '{query}'")
            print(f"Precision@5: {precision:.2%}")
            if results:
                print(f"Top 5: {[r['name'] for r in results[:5]]}")

        avg_precision = sum(precisions) / len(precisions)
        print(f"\n=== BASELINE PRECISION@5: {avg_precision:.2%} ===")

        # No assertion yet - just measuring
        # Target after improvements: >75%

    def test_baseline_mrr(self, benchmark_vector_store):
        """Measure current MRR across benchmark queries."""
        mrrs = []

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=20)
            mrr = calculate_mrr(results, expected)
            mrrs.append(mrr)

        avg_mrr = sum(mrrs) / len(mrrs)
        print(f"\n=== BASELINE MRR: {avg_mrr:.3f} ===")

        # No assertion yet - just measuring
        # Target after improvements: >0.8

    def test_baseline_token_efficiency(self, benchmark_vector_store):
        """Measure how many results needed for good coverage."""
        coverage_at_k = {5: [], 10: [], 20: [], 50: []}

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=50)

            # Check coverage at different K values
            for k in coverage_at_k.keys():
                precision = calculate_precision_at_k(results, expected, k=k)
                coverage_at_k[k].append(precision)

        print("\n=== BASELINE TOKEN EFFICIENCY ===")
        for k, precisions in coverage_at_k.items():
            avg = sum(precisions) / len(precisions)
            print(f"Precision@{k}: {avg:.2%}")

        # Goal: Achieve same coverage with fewer results after improvements


class TestSearchQualityImproved:
    """
    Tests for IMPROVED search quality (after implementing enhancements).

    These tests will validate that our improvements actually work.
    Initially they may fail - that's expected!
    """

    @pytest.mark.skip(reason="Not implemented yet - placeholder for after improvements")
    def test_improved_precision_at_5(self, benchmark_vector_store):
        """
        After improvements, precision@5 should be >75%.

        Improvements include:
        - Field boosting (name > signature > doc)
        - Query preprocessing (CamelCase handling)
        - Quality filtering (remove low scores)
        - Prefix/suffix matching boost
        - Symbol kind weighting
        """
        precisions = []

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=20)
            precision = calculate_precision_at_k(results, expected, k=5)
            precisions.append(precision)

        avg_precision = sum(precisions) / len(precisions)
        print(f"\n=== IMPROVED PRECISION@5: {avg_precision:.2%} ===")

        # Assert improvement
        assert avg_precision >= 0.75, f"Precision@5 should be ≥75%, got {avg_precision:.2%}"

    @pytest.mark.skip(reason="Not implemented yet - placeholder for after improvements")
    def test_improved_mrr(self, benchmark_vector_store):
        """After improvements, MRR should be >0.8."""
        mrrs = []

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=20)
            mrr = calculate_mrr(results, expected)
            mrrs.append(mrr)

        avg_mrr = sum(mrrs) / len(mrrs)
        print(f"\n=== IMPROVED MRR: {avg_mrr:.3f} ===")

        assert avg_mrr >= 0.8, f"MRR should be ≥0.8, got {avg_mrr:.3f}"

    @pytest.mark.skip(reason="Not implemented yet - placeholder for after improvements")
    def test_token_savings_achieved(self, benchmark_vector_store):
        """
        Verify we can achieve same coverage with 30-40% fewer results.

        Goal: Precision@20 (improved) ≈ Precision@50 (baseline)
        Token savings: (50-20)/50 = 60% fewer tokens!
        """
        precisions_at_20 = []

        for query, expected in BENCHMARK_QUERIES:
            results = benchmark_vector_store.search(query, method="text", limit=20)
            precision = calculate_precision_at_k(results, expected, k=20)
            precisions_at_20.append(precision)

        avg_precision = sum(precisions_at_20) / len(precisions_at_20)
        print(f"\n=== Precision@20 (improved): {avg_precision:.2%} ===")
        print("Compare to baseline Precision@50 to measure token savings")

        # After improvements, Precision@20 should be close to baseline Precision@50
        # This means we can return 20 results instead of 50 (60% token savings)
