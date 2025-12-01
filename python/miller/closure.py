"""Transitive closure computation for fast impact analysis.

This module computes reachability between symbols, enabling O(1) lookups
for questions like "what breaks if I change X?" instead of BFS traversal.

Algorithm: BFS from each symbol to find all reachable nodes within max_depth.
Space: O(E * avg_path_length) where E is number of edges
Time: O(V * (V + E)) worst case, but sparse call graphs are much faster.
"""

from collections import defaultdict

from miller.storage import StorageManager


def compute_transitive_closure(
    storage: StorageManager,
    max_depth: int = 10,
    relationship_kinds: list[str] | None = None,
) -> int:
    """
    Compute transitive closure for all symbols in the call graph.

    This pre-computes reachability so that impact analysis becomes O(1) lookup
    instead of O(N) BFS traversal.

    Args:
        storage: StorageManager with symbols and relationships
        max_depth: Maximum path length to compute (default 10)
        relationship_kinds: Relationship types to follow (default: ["Call"])

    Returns:
        Number of reachability entries created
    """
    if relationship_kinds is None:
        # Include both capitalized and lowercase variants for compatibility
        # (Rust extractors use lowercase, some tests use capitalized)
        relationship_kinds = ["Call", "calls"]

    # Clear existing closure
    storage.clear_reachability()

    # Build adjacency list from relationships
    downstream = defaultdict(set)  # symbol_id -> set of symbols it calls

    # Get all relationships of specified kinds (case-insensitive matching)
    cursor = storage.conn.execute(
        f"""
        SELECT from_symbol_id, to_symbol_id
        FROM relationships
        WHERE LOWER(kind) IN ({','.join('?' * len(relationship_kinds))})
        """,
        [k.lower() for k in relationship_kinds],
    )

    for row in cursor.fetchall():
        downstream[row[0]].add(row[1])

    if not downstream:
        return 0

    # Get all unique symbol IDs that participate in relationships
    all_symbols = set(downstream.keys())
    for targets in downstream.values():
        all_symbols.update(targets)

    # BFS from each symbol to compute reachability
    reachability_entries = []

    for start_symbol in all_symbols:
        if start_symbol not in downstream:
            continue  # No outgoing edges, skip

        # BFS to find all reachable nodes
        visited = {start_symbol: 0}  # symbol -> distance
        queue = [(start_symbol, 0)]

        while queue:
            current, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            for neighbor in downstream.get(current, set()):
                if neighbor not in visited:
                    new_depth = depth + 1
                    visited[neighbor] = new_depth
                    queue.append((neighbor, new_depth))
                    reachability_entries.append((start_symbol, neighbor, new_depth))

    # Bulk insert
    if reachability_entries:
        storage.add_reachability_batch(reachability_entries)

    return len(reachability_entries)


def should_compute_closure(storage: StorageManager) -> bool:
    """
    Determine if transitive closure should be computed.

    Returns True if:
    - There are relationships in the database (something to compute)
    - AND reachability table is empty (not yet computed)

    This allows closure to run on startup even for already-indexed workspaces
    where reachability was never populated.

    Args:
        storage: StorageManager instance

    Returns:
        True if closure should be computed, False otherwise
    """
    cursor = storage.conn.cursor()

    # Check if we have relationships to compute from
    cursor.execute("SELECT COUNT(*) FROM relationships")
    relationship_count = cursor.fetchone()[0]

    if relationship_count == 0:
        return False  # Nothing to compute

    # Check if reachability is already populated
    cursor.execute("SELECT COUNT(*) FROM reachability")
    reachability_count = cursor.fetchone()[0]

    # Need to compute if we have relationships but no reachability
    return reachability_count == 0


def is_reachability_stale(storage: StorageManager) -> bool:
    """
    Check if reachability data is stale (doesn't reflect current relationships).

    Reachability is stale if:
    - There are direct relationships (A->B) that don't exist in reachability at distance=1
    - OR there are reachability entries for relationships that no longer exist

    This is a heuristic check - for full accuracy, we'd need to recompute.
    The check is O(relationships) which is fast for typical codebases.

    Args:
        storage: StorageManager instance

    Returns:
        True if reachability should be refreshed, False if it's current
    """
    cursor = storage.conn.cursor()

    # Check if any direct relationship is missing from reachability
    # (ignoring self-referential edges which we don't track)
    cursor.execute("""
        SELECT COUNT(*) FROM relationships r
        WHERE LOWER(r.kind) IN ('call', 'calls')
        AND r.from_symbol_id != r.to_symbol_id
        AND NOT EXISTS (
            SELECT 1 FROM reachability
            WHERE source_id = r.from_symbol_id
            AND target_id = r.to_symbol_id
        )
    """)
    missing_count = cursor.fetchone()[0]

    if missing_count > 0:
        return True

    # Also check if reachability has entries for deleted relationships
    # (orphaned reachability entries at distance=1)
    cursor.execute("""
        SELECT COUNT(*) FROM reachability reach
        WHERE reach.min_distance = 1
        AND NOT EXISTS (
            SELECT 1 FROM relationships r
            WHERE LOWER(r.kind) IN ('call', 'calls')
            AND r.from_symbol_id = reach.source_id
            AND r.to_symbol_id = reach.target_id
        )
    """)
    orphan_count = cursor.fetchone()[0]

    return orphan_count > 0


def refresh_reachability(
    storage: StorageManager,
    max_depth: int = 10,
    relationship_kinds: list[str] | None = None,
) -> int:
    """
    Refresh reachability table by recomputing transitive closure.

    This clears and recomputes the entire reachability table.
    Use this after incremental file changes to ensure reachability is current.

    For large codebases, consider debouncing calls to avoid excessive recomputation.

    Args:
        storage: StorageManager with symbols and relationships
        max_depth: Maximum path length to compute (default 10)
        relationship_kinds: Relationship types to follow (default: ["Call", "calls"])

    Returns:
        Number of reachability entries created
    """
    # Simply delegate to compute_transitive_closure which handles clearing
    return compute_transitive_closure(storage, max_depth, relationship_kinds)


def get_all_relationships_by_kind(
    storage: StorageManager, kinds: list[str]
) -> list[tuple[str, str]]:
    """
    Get all relationships of specified kinds.

    Args:
        storage: StorageManager
        kinds: List of relationship kinds (e.g., ["Call", "Import"])

    Returns:
        List of (from_symbol_id, to_symbol_id) tuples
    """
    cursor = storage.conn.execute(
        f"""
        SELECT from_symbol_id, to_symbol_id
        FROM relationships
        WHERE kind IN ({','.join('?' * len(kinds))})
        """,
        kinds,
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]
