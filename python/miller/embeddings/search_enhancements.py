"""Search result enhancement and ranking logic for VectorStore.

Provides methods to improve search relevance through field matching,
position-based boosting, kind-based weighting, staleness decay,
importance weighting, and quality filtering.
"""

import math
import re
import time


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
    # Kind weights are intentionally modest to avoid overshadowing relevance scores.
    # Previously 1.5x caused even low-relevance results to hit 1.0 ceiling.
    # Weights are tuned so unrelated queries stay below 80% of keyword matches.
    KIND_WEIGHTS = {
        "Function": 1.1,
        "Class": 1.1,
        "Method": 1.05,
        "Interface": 1.05,
        "Type": 1.05,
        "Struct": 1.05,
        "Enum": 1.0,
        "Variable": 0.9,
        "Field": 0.9,
        "Constant": 0.95,
        "Parameter": 0.85,
        # Deboost noise - you want definitions, not these
        "Import": 0.6,
        "Namespace": 0.7,
        # File-level entries (text files without parsers)
        # Ranked lower than symbols so code results appear first
        "File": 0.65,
    }

    base_score = result.get("score", 0.0)
    kind = result.get("kind", "")

    # Normalize kind to title case (data has "function", dict has "Function")
    weight = KIND_WEIGHTS.get(kind.title(), 1.0)  # Default 1.0 for unknown kinds
    return min(base_score * weight, 1.0)  # Clamp to 1.0


def calculate_staleness_factor(
    last_modified: int | None,
    now: int | None = None,
    decay_rate: float = 0.1,
    min_factor: float = 0.5,
) -> float:
    """
    Calculate staleness decay factor based on file modification time.

    Older code is slightly penalized as it may be deprecated or less relevant.
    The decay is gradual (-10% per year by default) with a floor (50% by default)
    to ensure old but still-valid code isn't completely buried.

    Formula: factor = max(min_factor, 1.0 - decay_rate * years_old)

    Args:
        last_modified: Unix timestamp of last file modification (from files.last_modified)
        now: Current timestamp (defaults to time.time())
        decay_rate: Score reduction per year (default: 0.1 = 10% per year)
        min_factor: Minimum factor floor (default: 0.5 = 50% of original score)

    Returns:
        Staleness factor (0.5-1.0) to multiply with score

    Example:
        - File modified today → factor = 1.0
        - File modified 1 year ago → factor = 0.9
        - File modified 5 years ago → factor = 0.5 (floor)
    """
    if last_modified is None:
        return 1.0  # No timestamp available, no penalty

    if now is None:
        now = int(time.time())

    # Calculate age in years
    age_seconds = now - last_modified
    if age_seconds <= 0:
        return 1.0  # Future timestamp or current = no decay

    years_old = age_seconds / (365.25 * 24 * 60 * 60)

    # Apply decay with floor
    factor = 1.0 - (decay_rate * years_old)
    return max(min_factor, factor)


def calculate_importance_boost(
    reference_count: int | None,
    log_base: float = 2.0,
    boost_factor: float = 0.1,
    max_boost: float = 1.5,
) -> float:
    """
    Calculate importance boost based on incoming reference count.

    Frequently referenced symbols are boosted as they're likely more important
    ("central" to the codebase). The boost is logarithmic to avoid extreme
    scores for highly-referenced core utilities.

    Formula: boost = min(max_boost, 1.0 + boost_factor * log2(1 + count))

    Args:
        reference_count: Number of incoming references (from symbols.reference_count)
        log_base: Base for logarithmic scaling (default: 2.0)
        boost_factor: Multiplier for log value (default: 0.1 = 10% per doubling)
        max_boost: Maximum boost factor (default: 1.5 = 50% max increase)

    Returns:
        Importance boost factor (1.0-1.5) to multiply with score

    Example:
        - 0 references → boost = 1.0 (no boost)
        - 1 reference → boost = 1.1
        - 7 references → boost = 1.3
        - 31 references → boost = 1.5 (capped)
        - 1000 references → boost = 1.5 (capped)
    """
    if reference_count is None or reference_count <= 0:
        return 1.0  # No references or missing data = no boost

    # Logarithmic scaling: log2(1 + count) gives nice progression
    # 1 ref = 1.0, 3 refs = 2.0, 7 refs = 3.0, 15 refs = 4.0, etc.
    log_value = math.log(1 + reference_count, log_base)
    boost = 1.0 + (boost_factor * log_value)

    return min(max_boost, boost)


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


def apply_search_enhancements(
    results: list[dict],
    query: str,
    method: str,
    apply_data_quality: bool = False,
) -> list[dict]:
    """
    Apply all search quality enhancements to results.

    Enhancements applied (in order):
    1. Field match boosting (name > signature > doc)
    2. Match position boosting (exact > prefix > suffix)
    3. Symbol kind weighting (functions/classes > variables)
    4. [Optional] Data quality adjustments (requires hydrated results):
       - Staleness decay (older code slightly penalized)
       - Importance boost (frequently referenced symbols boosted)
    5. Quality filtering (remove low scores)
    6. Re-sort by enhanced scores

    Args:
        results: Raw search results from FTS/vector search
        query: Original search query
        method: Search method used
        apply_data_quality: If True, apply staleness/importance adjustments.
                           Requires results to have 'last_modified' and 'reference_count'
                           fields (from search hydration).

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

        # Store enhanced score
        result["score"] = score

    # NOTE: We intentionally do NOT re-normalize after boosting.
    # Re-normalization would make every query's best result = 1.0,
    # losing information about absolute match quality.
    # A query for "xyz123notfound" should have lower scores than "run".
    # Boost functions already cap at 1.0 with min(..., 1.0).

    # Filter low-quality results (remove noise)
    # Use a higher threshold since scores aren't re-normalized
    results = filter_low_quality_results(results, min_score=0.1)

    # Re-sort by enhanced scores
    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return results


def apply_data_quality_enhancements(results: list[dict]) -> list[dict]:
    """
    Apply data quality enhancements based on staleness and importance.

    This is called AFTER hydration (when results have 'last_modified' and
    'reference_count' from SQLite) and AFTER initial search enhancements.

    Adjustments:
    - Staleness decay: Older files are slightly penalized (-10% per year, min 50%)
    - Importance boost: Highly-referenced symbols are boosted (up to +50%)

    These are intentionally conservative to avoid burying legitimate old code
    or over-promoting popular utilities.

    Args:
        results: Hydrated search results with last_modified and reference_count

    Returns:
        Results with adjusted scores, re-sorted
    """
    if not results:
        return results

    current_time = int(time.time())

    for result in results:
        score = result.get("score", 0.0)

        # Apply staleness decay (penalize old code slightly)
        last_modified = result.get("last_modified")
        staleness_factor = calculate_staleness_factor(last_modified, now=current_time)
        score *= staleness_factor

        # Apply importance boost (boost frequently-referenced symbols)
        reference_count = result.get("reference_count")
        importance_boost = calculate_importance_boost(reference_count)
        score *= importance_boost

        # Cap at 1.0 after all adjustments
        result["score"] = min(score, 1.0)

    # Re-sort by adjusted scores
    results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    return results
