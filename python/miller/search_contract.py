"""
Pattern Search Feature Contract

This file defines the interface contract for pattern search functionality.
Write tests against this contract BEFORE implementing.

SUCCESS CRITERIA:
- ✅ Can search for `: BaseClass` and find all inheritance
- ✅ Can search for `ILogger<` and find all generic usages
- ✅ Can search for `[Fact]` and find all test attributes
- ✅ Auto-detection works >95% of time
- ✅ Manual override available for edge cases
- ✅ Performance <100ms (no regression)
"""

from typing import Literal, List, Dict, Any
from typing_extensions import TypedDict
import pyarrow as pa


# Type Definitions
SearchMethod = Literal["auto", "text", "pattern", "semantic", "hybrid"]
"""
Search method options:
- auto: Auto-detect based on query (default, recommended)
- text: Full-text search with stemming (general code search)
- pattern: Code idioms using whitespace tokenizer (: < > [ ] preserved)
- semantic: Vector similarity search (conceptual matches)
- hybrid: Combines text + semantic with RRF fusion
"""


class SearchResult(TypedDict):
    """
    Search result structure returned by all search methods.

    All search methods MUST return this structure.
    """
    id: str                    # Symbol ID
    name: str                  # Symbol name
    kind: str                  # Symbol kind (Function, Class, etc.)
    language: str              # Programming language
    file_path: str             # File path
    signature: str | None      # Function/method signature
    doc_comment: str | None    # Documentation comment
    start_line: int            # Start line number
    end_line: int              # End line number
    score: float               # Normalized relevance score (0.0-1.0)


# Schema Contract
PATTERN_SEARCH_SCHEMA = pa.schema([
    pa.field("id", pa.string(), nullable=False),
    pa.field("name", pa.string(), nullable=False),
    pa.field("kind", pa.string(), nullable=False),
    pa.field("language", pa.string(), nullable=False),
    pa.field("file_path", pa.string(), nullable=False),
    pa.field("signature", pa.string(), nullable=True),
    pa.field("doc_comment", pa.string(), nullable=True),
    pa.field("start_line", pa.int32(), nullable=True),
    pa.field("end_line", pa.int32(), nullable=True),
    # NEW FIELD: Pattern-preserving content for code idiom search
    pa.field("code_pattern", pa.string(), nullable=False),
    pa.field("vector", pa.list_(pa.float32(), 384), nullable=False),
])
"""
Extended schema with code_pattern field for pattern search.

code_pattern field:
- Contains: signature + name + kind (space-separated)
- Tokenization: whitespace only (preserves : < > [ ] ( ) { })
- Purpose: Enables code idiom search (inheritance, generics, attributes)
- Example: "def hello(name: str) -> str hello Function"
"""


# Function Contracts
def detect_search_method(query: str) -> SearchMethod:
    """
    Auto-detect optimal search method from query characteristics.

    Detection logic:
    - If query contains code pattern chars (: < > [ ] ( ) { }) → "pattern"
    - Otherwise → "hybrid" (best quality for general search)

    Args:
        query: User's search query

    Returns:
        Detected search method ("pattern" or "hybrid")

    Examples:
        >>> detect_search_method(": BaseClass")
        "pattern"
        >>> detect_search_method("ILogger<UserService>")
        "pattern"
        >>> detect_search_method("[Fact]")
        "pattern"
        >>> detect_search_method("authentication logic")
        "hybrid"

    Boundary conditions:
        - Empty string → "hybrid" (safe default)
        - Whitespace only → "hybrid"
        - Mixed (pattern chars + natural language) → "pattern" (pattern takes precedence)

    Error conditions:
        - Never raises exceptions
        - Always returns valid SearchMethod
    """
    raise NotImplementedError("Contract only - implement in embeddings.py")


def search(
    query: str,
    method: SearchMethod = "auto",
    limit: int = 50
) -> List[SearchResult]:
    """
    Search symbols with auto-detection and method routing.

    This is the main entry point for all searches.

    Args:
        query: Search query (code patterns, keywords, or natural language)
        method: Search method (auto-detects by default)
        limit: Maximum results to return (default: 50)

    Returns:
        List of search results, sorted by relevance (highest score first)
        Each result has normalized score (0.0-1.0)

    Routing logic:
        1. If method == "auto" → call detect_search_method(query)
        2. Route to appropriate search method:
           - "pattern" → _search_pattern()
           - "text" → _search_text()
           - "semantic" → _search_semantic()
           - "hybrid" → _search_hybrid()

    Examples:
        >>> # Auto-detection (recommended)
        >>> search("authentication logic")  # Auto → hybrid
        >>> search(": BaseClass")           # Auto → pattern
        >>> search("ILogger<")              # Auto → pattern

        >>> # Manual override
        >>> search("map<int, string>", method="text")     # Force text
        >>> search("user auth", method="semantic")        # Force semantic

    Boundary conditions:
        - Empty query → return [] (no error)
        - limit <= 0 → return [] (no error)
        - limit > 1000 → clamp to 1000 (prevent memory issues)
        - No table/index → return [] (no error)

    Error conditions:
        - Invalid Tantivy syntax → return [] (safe failure)
        - Missing FTS index → fallback to LIKE queries
        - Missing embeddings → skip semantic component
        - Never raises exceptions to caller

    Performance requirements:
        - Text search: < 50ms (Tantivy FTS)
        - Pattern search: < 100ms (whitespace tokenizer + phrase search)
        - Semantic search: < 200ms (includes embedding + HNSW)
        - Hybrid search: < 250ms (RRF fusion)
    """
    raise NotImplementedError("Contract only - implement in VectorStore.search()")


def _search_pattern(query: str, limit: int) -> List[SearchResult]:
    """
    Search code patterns using whitespace-tokenized field.

    This method handles code idioms with special characters that need
    to be preserved (: < > [ ] ( ) { }).

    Implementation requirements:
        - Use LanceDB FTS on code_pattern field
        - Tokenizer: whitespace only (base_tokenizer="whitespace")
        - Query wrapping: Auto-wrap in quotes for phrase search
        - Score normalization: 0.0-1.0 range

    Args:
        query: Pattern query (e.g., ": BaseClass", "ILogger<", "[Fact]")
        limit: Maximum results

    Returns:
        List of matching symbols with normalized scores

    Query preprocessing:
        - If query not wrapped in quotes → wrap in quotes
        - Preserves all special chars (no escaping needed)
        - Example: `ILogger<` → `"ILogger<"` (phrase search)

    Examples:
        >>> _search_pattern(": BaseClass", 50)
        [{"name": "UserService", "signature": ": BaseClass", "score": 0.95}, ...]

        >>> _search_pattern("ILogger<", 50)
        [{"name": "service", "signature": "ILogger<UserService>", "score": 0.98}, ...]

        >>> _search_pattern("[Fact]", 50)
        [{"name": "TestMethod", "signature": "[Fact] void TestMethod()", "score": 1.0}, ...]

    Boundary conditions:
        - Empty query → return []
        - Query with only special chars → valid (search for those chars)
        - Very long query (>512 chars) → valid (Tantivy handles it)

    Error conditions:
        - Malformed Tantivy syntax → return [] (safe failure)
        - Missing pattern field → return [] (schema mismatch)
        - Missing FTS index → return [] (index not created)

    Performance:
        - Target: < 100ms for typical queries
        - Whitespace tokenizer is faster than stemming
        - Phrase search adds minimal overhead
    """
    raise NotImplementedError("Contract only - implement in VectorStore")


# Test Scenarios (for TDD)
PATTERN_TEST_CASES = [
    # Inheritance patterns
    (": BaseClass", ["UserService", "PaymentService"]),
    (": IService", ["UserService", "AuthService"]),

    # Generic patterns
    ("ILogger<", ["service", "controller", "repository"]),
    ("List<", ["items", "users", "orders"]),
    ("map<", ["cache", "lookup", "index"]),

    # Attribute patterns
    ("[Fact]", ["Test_UserAuth", "Test_Payment"]),
    ("[HttpGet]", ["GetUser", "GetOrders"]),
    ("@Override", ["toString", "equals", "hashCode"]),

    # Operator patterns
    ("?.", ["user?.name", "order?.items"]),
    ("=>", ["arrow functions", "lambda expressions"]),
    ("&&", ["logical AND operations"]),

    # Bracket patterns
    ("[]", ["array declarations", "indexers"]),
    ("{}", ["object literals", "blocks"]),
    ("()", ["function calls", "method invocations"]),
]
"""
Test cases for pattern search validation.

Each case is (query, expected_symbol_names_to_find).
Tests should verify these patterns are found with high confidence.
"""


# Validation Rules
VALIDATION_RULES = {
    "schema": {
        "code_pattern_field_required": True,
        "code_pattern_not_nullable": True,
        "vector_dimension": 384,
    },
    "detection": {
        "pattern_chars": [':', '<', '>', '[', ']', '(', ')', '{', '}'],
        "accuracy_threshold": 0.95,  # >95% correct auto-detection
    },
    "performance": {
        "text_search_ms": 50,
        "pattern_search_ms": 100,
        "semantic_search_ms": 200,
        "hybrid_search_ms": 250,
    },
    "scoring": {
        "min_score": 0.0,
        "max_score": 1.0,
        "normalization_required": True,
    }
}
"""
Validation rules for contract compliance.

Tests MUST verify these requirements are met.
"""
