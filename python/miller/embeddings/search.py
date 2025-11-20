"""
Search method detection for Miller embeddings.

Provides automatic detection of optimal search method (pattern vs text vs semantic)
based on query characteristics.
"""

from typing import Literal

# Search method type alias
SearchMethod = Literal["auto", "text", "pattern", "semantic", "hybrid"]


def detect_search_method(query: str) -> SearchMethod:
    """
    Auto-detect optimal search method from query characteristics.

    Detection logic:
    - If query contains code pattern chars → "pattern"
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
    """
    # Pattern indicators: special chars commonly used in code syntax
    # Include: inheritance (:), generics (< >), brackets ([ ] ( ) { })
    # operators (=> ?. &&), and other code-specific symbols

    # Check for multi-char patterns first (to avoid false positives)
    multi_char_patterns = ["=>", "?.", "&&"]
    for pattern in multi_char_patterns:
        if pattern in query:
            return "pattern"

    # Check for single-char patterns
    single_char_patterns = [":", "<", ">", "[", "]", "(", ")", "{", "}"]
    for ch in single_char_patterns:
        if ch in query:
            return "pattern"

    # Default to hybrid for natural language queries
    return "hybrid"
