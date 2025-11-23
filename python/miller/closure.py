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
        relationship_kinds = ["Call"]

    # Clear existing closure
    storage.clear_reachability()

    # Build adjacency list from relationships
    downstream = defaultdict(set)  # symbol_id -> set of symbols it calls

    # Get all relationships of specified kinds
    cursor = storage.conn.execute(
        f"""
        SELECT from_symbol_id, to_symbol_id
        FROM relationships
        WHERE kind IN ({','.join('?' * len(relationship_kinds))})
        """,
        relationship_kinds,
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
