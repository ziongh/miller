"""Search result enhancement and ranking logic for VectorStore.

Provides methods to improve search relevance through field matching,
position-based boosting, kind-based weighting, and quality filtering.
"""

import re


def preprocess_query(query: str, method: str) -> str:
    """
    Preprocess query for better search results.

    Enhancements:
    - CamelCase splitting: "UserService" → "User Service" (better tokenization)
    - Noise word removal for text search (optional, currently disabled)
    - Whitespace normalization

    Args:
        query: Original query
        method: Search method ("text", "pattern", "semantic", "hybrid")

    Returns:
        Preprocessed query
    """
    original_query = query
    query = query.strip()

    if not query:
        return original_query

    # For text/hybrid search: handle CamelCase
    if method in ["text", "hybrid"]:
        # Check if query looks like CamelCase (e.g., "UserService", "parseJSON")
        # Heuristic: has uppercase letters that aren't at the start
        if any(c.isupper() for c in query[1:]) and not " " in query:
            # Split on uppercase letters: "UserService" → "User Service"
            # This helps tokenizer match "user" and "service" separately
            query_split = re.sub(r'([A-Z])', r' \1', query).strip()
            # Use split version if it's different and non-empty
            if query_split != query and query_split:
                query = query_split

    return query


def boost_by_field_match(result: dict, query: str) -> float:
    """
    Boost score based on which field matched.

    Relevance hierarchy:
    - Name match: 3.0x boost (most important - symbol name is primary identifier)
    - Signature match: 1.5x boost (important - shows usage)
    - Doc comment match: 1.0x boost (base - contextual info)

    Args:
        result: Search result dict
        query: Search query (lowercased for matching)

    Returns:
        Boosted score (0.0-1.0 after normalization)
    """
    base_score = result.get("score", 0.0)
    query_lower = query.lower().strip()

    if not query_lower:
        return base_score

    # Check for partial match in each field
    name = result.get("name", "").lower()
    signature = (result.get("signature") or "").lower()
    doc_comment = (result.get("doc_comment") or "").lower()

    # Apply boosts based on match location
    if query_lower in name:
        return min(base_score * 3.0, 1.0)  # Name match = highest priority
    elif query_lower in signature:
        return min(base_score * 1.5, 1.0)  # Signature match = medium priority
    elif query_lower in doc_comment:
        return base_score * 1.0  # Doc match = base priority
    else:
        # No obvious match (might be stemmed or fuzzy)
        return base_score


def boost_by_match_position(result: dict, query: str, boost_by_field_match_fn=None) -> float:
    """
    Boost score based on match position (exact > prefix > suffix > substring).

    Match type hierarchy:
    - Exact match: 3.0x boost (query == name)
    - Prefix match: 2.0x boost (name starts with query)
    - Suffix match: 1.5x boost (name ends with query)
    - Substring match: 1.0x boost (query in name)

    Args:
        result: Search result dict
        query: Search query
        boost_by_field_match_fn: Optional callback to boost_by_field_match

    Returns:
        Boosted score (0.0-1.0 after normalization)
    """
    base_score = result.get("score", 0.0)
    query_lower = query.lower().strip()
    name = result.get("name", "").lower()

    if not query_lower or not name:
        return base_score

    # Check match type (in order of specificity)
    if name == query_lower:
        return min(base_score * 3.0, 1.0)  # Exact match = huge boost
    elif name.startswith(query_lower):
        return min(base_score * 2.0, 1.0)  # Prefix match = strong boost
    elif name.endswith(query_lower):
        return min(base_score * 1.5, 1.0)  # Suffix match = moderate boost
    elif query_lower in name:
        return base_score * 1.0  # Substring = base score
    else:
        # Check signature/doc for matches
        if boost_by_field_match_fn:
            return boost_by_field_match_fn(result, query)
        return boost_by_field_match(result, query)


def apply_kind_weighting(result: dict) -> float:
    """
    Apply symbol kind weighting to boost commonly-searched symbol types.

    Rationale:
    - Functions/Classes are usually search targets (user wants to call/extend them)
    - Variables/Fields are less often the primary search target
    - This aligns ranking with developer intent

    Kind weights:
    - Function: 1.5x (most commonly searched)
    - Class: 1.5x
    - Method: 1.3x
    - Interface/Type: 1.2x
    - Variable/Field: 0.8x (less commonly the target)
    - Constant: 0.9x

    Args:
        result: Search result dict

    Returns:
        Weighted score (0.0-1.0 after normalization)
    """
    KIND_WEIGHTS = {
        "Function": 1.5,
        "Class": 1.5,
        "Method": 1.3,
        "Interface": 1.2,
        "Type": 1.2,
        "Struct": 1.2,
        "Enum": 1.1,
        "Variable": 0.8,
        "Field": 0.8,
        "Constant": 0.9,
        "Parameter": 0.7,
        # Deboost noise - you want definitions, not these
        "Import": 0.4,
        "Namespace": 0.6,
        # File-level entries (text files without parsers)
        # Ranked lower than symbols so code results appear first
        "File": 0.5,
    }

    base_score = result.get("score", 0.0)
    kind = result.get("kind", "")

    # Normalize kind to title case (data has "function", dict has "Function")
    weight = KIND_WEIGHTS.get(kind.title(), 1.0)  # Default 1.0 for unknown kinds
    return min(base_score * weight, 1.0)  # Clamp to 1.0


def filter_low_quality_results(results: list[dict], min_score: float = 0.05) -> list[dict]:
    """
    Filter out very low-quality results (noise reduction).

    Low-scoring results are unlikely to be useful and waste tokens.
    Default threshold: 0.05 (5% of max score) - removes obvious noise.

    Args:
        results: Search results with normalized scores (0.0-1.0)
        min_score: Minimum score threshold (default: 0.05)

    Returns:
        Filtered results (only those above threshold)
    """
    return [r for r in results if r.get("score", 0.0) >= min_score]


def apply_search_enhancements(results: list[dict], query: str, method: str) -> list[dict]:
    """
    Apply all search quality enhancements to results.

    Enhancements applied:
    1. Field match boosting (name > signature > doc)
    2. Match position boosting (exact > prefix > suffix)
    3. Symbol kind weighting (functions/classes > variables)
    4. Quality filtering (remove low scores)
    5. Re-sort by enhanced scores

    Args:
        results: Raw search results from FTS/vector search
        query: Original search query
        method: Search method used

    Returns:
        Enhanced and re-ranked results
    """
    if not results:
        return results

    # Preprocess query (same preprocessing as search)
    processed_query = preprocess_query(query, method)

    # Apply enhancements to each result
    for result in results:
        # Start with base score
        score = result.get("score", 0.0)

        # Apply match position boost (exact > prefix > suffix)
        score = boost_by_match_position(result, processed_query, boost_by_field_match_fn=boost_by_field_match)

        # Apply symbol kind weighting
        result["score"] = score  # Update for kind weighting
        score = apply_kind_weighting(result)

        # Store final enhanced score
        result["score"] = score

    # Re-normalize scores to 0.0-1.0 range after boosting
    if results:
        max_score = max(r.get("score", 0.0) for r in results)
        if max_score > 0:
            for r in results:
                r["score"] = r["score"] / max_score

    # Filter low-quality results (remove noise)
    results = filter_low_quality_results(results, min_score=0.05)

    # Re-sort by enhanced scores
    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return results
