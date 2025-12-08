"""
Search method detection for Miller embeddings.

Provides automatic detection of optimal search method (pattern vs text vs semantic)
based on query characteristics, plus intent-based kind filtering for improved precision.
"""

import re
from typing import Literal, Optional

# Search method type alias
SearchMethod = Literal["auto", "text", "pattern", "semantic", "hybrid"]

# ==================== Intent-Based Kind Filtering ====================
#
# When searching for code, the user's intent often implies a specific symbol type.
# For example:
#   - "How is User defined?" → Looking for class/struct/interface definitions
#   - "Where is user used?" → Looking for variable/parameter references
#
# By detecting intent and hard-filtering at the database level, we dramatically
# improve Precision@5 (the top 5 results are much more likely to be relevant).

# Symbol kinds that represent DEFINITIONS (the "what" - types, functions, etc.)
DEFINITION_KINDS = [
    "class",
    "struct",
    "interface",
    "enum",
    "type",
    "trait",
    "protocol",
    "record",
    "function",
    "method",
    "constructor",
    "module",
]

# Symbol kinds that represent USAGES (the "where" - variables, parameters, etc.)
USAGE_KINDS = [
    "variable",
    "parameter",
    "field",
    "property",
    "constant",
    "call",
    "reference",
]

# Patterns that indicate looking for DEFINITIONS
# Uses word boundaries to avoid false positives
DEFINITION_PATTERNS = [
    r"\bdefin(e|ed|ition|ing)\b",  # "define", "defined", "definition"
    r"\bimplement(s|ed|ation|ing)?\b",  # "implements", "implementation"
    r"\bclass\b",
    r"\bstruct\b",
    r"\binterface\b",
    r"\bwhat is\b",
    r"\bhow is\b.*\b(defined|implemented|declared|created)\b",
    r"\bwhere is\b.*\b(defined|declared)\b",
    r"\bfind the\b.*\b(class|struct|function|interface|type)\b",
    r"\bshow me the\b.*\b(class|struct|function|interface|type)\b",
    r"\bdeclar(e|ed|ation|ing)\b",
    r"\bcreate[sd]?\b",  # "creates", "created"
]

# Patterns that indicate looking for USAGES
USAGE_PATTERNS = [
    r"\bused?\b",  # "use", "used"
    r"\busage\b",
    r"\breference[sd]?\b",  # "reference", "references", "referenced"
    r"\bcall(s|ed|ing)?\b",  # "call", "calls", "called", "calling"
    r"\bwhere is\b.*\bused\b",
    r"\bwho (uses|calls)\b",
    r"\bfind (all )?usages?\b",
    r"\bfind (all )?references?\b",
    r"\binstances? of\b",
    r"\boccurrences? of\b",
]


def detect_search_intent(query: str) -> Optional[list[str]]:
    """
    Detect user intent from query to determine which symbol kinds to filter.

    This is a conservative detection - it only returns a filter when confident.
    If the intent is ambiguous, returns None (no filtering, return all kinds).

    Args:
        query: User's search query (natural language or code terms)

    Returns:
        - List of symbol kinds to filter by (e.g., ["class", "struct", "interface"])
        - None if intent is unclear (no filtering applied)

    Examples:
        >>> detect_search_intent("How is User defined?")
        ["class", "struct", "interface", "enum", "type", ...]

        >>> detect_search_intent("Where is user used?")
        ["variable", "parameter", "field", ...]

        >>> detect_search_intent("User")  # Ambiguous
        None

        >>> detect_search_intent("find all usages of Config")
        ["variable", "parameter", "field", ...]
    """
    query_lower = query.lower().strip()

    # Check for DEFINITION patterns
    for pattern in DEFINITION_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return DEFINITION_KINDS

    # Check for USAGE patterns
    for pattern in USAGE_PATTERNS:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return USAGE_KINDS

    # Intent unclear - don't filter (return all kinds)
    return None


def format_kind_filter_sql(kinds: list[str]) -> str:
    """
    Format a list of kinds into a SQL-compatible IN clause for LanceDB.

    Args:
        kinds: List of symbol kinds (e.g., ["class", "struct"])

    Returns:
        SQL-like filter string for LanceDB .where() clause

    Example:
        >>> format_kind_filter_sql(["class", "struct", "interface"])
        "kind IN ('class', 'struct', 'interface')"
    """
    if not kinds:
        return ""
    escaped = [k.replace("'", "''") for k in kinds]
    values = ", ".join(f"'{k}'" for k in escaped)
    return f"kind IN ({values})"


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
