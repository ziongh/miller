"""
Fuzzy symbol matching for fast_lookup fallback.

Provides multiple strategies for finding symbols when exact match fails:
1. Case-insensitive exact match
2. Substring matching
3. Levenshtein distance (typo correction)
4. Word-part matching (camelCase/snake_case)
"""

import re
from typing import Any, Optional


def fuzzy_find_symbol(
    storage,
    query: str,
    allowed_kinds: tuple[str, ...],
) -> Optional[tuple[dict[str, Any], float]]:
    """Find a symbol by fuzzy name matching.

    Uses multiple strategies:
    1. Case-insensitive exact match
    2. LIKE pattern matching (contains query or query contains name)
    3. Levenshtein-like similarity scoring
    4. Word-part matching

    Returns:
        Tuple of (symbol_dict, similarity_score) or None if no match found.
        Score is 0.0-1.0 where 1.0 is exact match.
    """
    query_lower = query.lower()
    kind_placeholders = ",".join("?" * len(allowed_kinds))

    # Strategy 1: Case-insensitive exact match
    cursor = storage.conn.execute(f"""
        SELECT * FROM symbols
        WHERE LOWER(name) = ?
        AND kind IN ({kind_placeholders})
        LIMIT 1
    """, (query_lower, *allowed_kinds))
    row = cursor.fetchone()
    if row:
        return dict(row), 1.0

    # Strategy 2: Query is substring of name (e.g., "Storage" in "StorageManager")
    cursor = storage.conn.execute(f"""
        SELECT * FROM symbols
        WHERE LOWER(name) LIKE ?
        AND kind IN ({kind_placeholders})
        ORDER BY LENGTH(name)
        LIMIT 5
    """, (f"%{query_lower}%", *allowed_kinds))
    rows = cursor.fetchall()
    if rows:
        # Pick best match - shortest name that contains the query
        best = dict(rows[0])
        # Score based on how much of the name is the query
        score = len(query) / len(best["name"])
        return best, min(score, 0.95)  # Cap at 0.95 for partial matches

    # Strategy 3: Levenshtein distance for typos (run BEFORE word-part matching)
    # Find symbols with similar names (edit distance)
    if len(query) >= 4:
        cursor = storage.conn.execute(f"""
            SELECT * FROM symbols
            WHERE kind IN ({kind_placeholders})
            AND LENGTH(name) BETWEEN ? AND ?
        """, (*allowed_kinds, len(query) - 3, len(query) + 3))

        best_match = None
        best_score = 0.0

        for row in cursor.fetchall():
            sym = dict(row)
            name_lower = sym["name"].lower()

            # Calculate Levenshtein similarity
            distance = levenshtein_distance(query_lower, name_lower)
            max_len = max(len(query), len(sym["name"]))
            score = 1.0 - (distance / max_len)

            if score > best_score and score >= 0.75:
                best_score = score
                best_match = sym

        if best_match:
            return best_match, best_score

    # Strategy 4: Word-part matching (last resort for partial matches)
    # Extract potential substrings from camelCase/snake_case
    parts = re.split(r'(?=[A-Z])|_', query)
    parts = [p for p in parts if len(p) >= 4]  # Only meaningful parts

    for part in parts:
        cursor = storage.conn.execute(f"""
            SELECT * FROM symbols
            WHERE LOWER(name) LIKE ?
            AND kind IN ({kind_placeholders})
            AND LENGTH(name) >= ?
            ORDER BY LENGTH(name)
            LIMIT 3
        """, (f"%{part.lower()}%", *allowed_kinds, len(query) - 2))
        rows = cursor.fetchall()
        if rows:
            best = dict(rows[0])
            # Only accept if the match is close in length to query
            if abs(len(best["name"]) - len(query)) <= 3:
                score = len(part) / max(len(query), len(best["name"]))
                if score >= 0.5:
                    return best, min(score + 0.2, 0.85)

    return None


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings.

    This is the minimum number of single-character edits (insertions,
    deletions, or substitutions) required to change one string into the other.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]
