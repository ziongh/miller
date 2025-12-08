"""
Miller Storage Queries - Read-only database operations.

Handles:
- Symbol lookups
- Identifier queries
- Relationship queries
- Reachability (transitive closure) queries
- Type intelligence queries
- File scanning for incremental indexing
"""

import sqlite3
from typing import Optional


def get_symbol_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    """
    Get first symbol by name, preferring definitions over references.

    When multiple symbols share the same name (e.g., import + function definition),
    returns the definition rather than the reference.

    Args:
        conn: SQLite connection
        name: Symbol name to search for

    Returns:
        Dict with symbol data, or None if not found
    """
    # Order by kind priority: definitions (function, class, etc.) before references (import)
    cursor = conn.execute("""
        SELECT * FROM symbols
        WHERE name = ?
        ORDER BY CASE kind
            WHEN 'import' THEN 2
            WHEN 'reference' THEN 2
            ELSE 1
        END
        LIMIT 1
    """, (name,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_symbol_by_id(conn: sqlite3.Connection, symbol_id: str) -> Optional[dict]:
    """
    Get symbol by ID.

    Args:
        conn: SQLite connection
        symbol_id: Symbol ID

    Returns:
        Dict with symbol data, or None if not found
    """
    cursor = conn.execute("SELECT * FROM symbols WHERE id = ?", (symbol_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_symbols_by_ids(conn: sqlite3.Connection, symbol_ids: list[str]) -> dict[str, dict]:
    """
    Get multiple symbols by ID in a single query.

    OPTIMIZED: Uses single WHERE IN query instead of N individual queries.
    This is the batch version of get_symbol_by_id() for search hydration.

    Includes:
    - All symbol fields (id, name, kind, file_path, reference_count, etc.)
    - last_modified from files table (for staleness decay in search ranking)

    Args:
        conn: SQLite connection
        symbol_ids: List of symbol IDs to fetch

    Returns:
        Dict mapping symbol_id -> symbol data. Missing IDs are not in the dict.
    """
    if not symbol_ids:
        return {}

    # Build parameterized query with correct number of placeholders
    # JOIN files to get last_modified for staleness decay scoring
    placeholders = ",".join("?" * len(symbol_ids))
    cursor = conn.execute(
        f"""
        SELECT symbols.*, files.last_modified
        FROM symbols
        LEFT JOIN files ON symbols.file_path = files.path
        WHERE symbols.id IN ({placeholders})
        """,
        symbol_ids,
    )

    # Build lookup dict: id -> symbol data
    return {row["id"]: dict(row) for row in cursor.fetchall()}


def get_identifiers_by_file(conn: sqlite3.Connection, file_path: str) -> list[dict]:
    """
    Get all identifiers in a file.

    Args:
        conn: SQLite connection
        file_path: File path

    Returns:
        List of identifier dicts
    """
    cursor = conn.execute("SELECT * FROM identifiers WHERE file_path = ?", (file_path,))
    return [dict(row) for row in cursor.fetchall()]


def get_relationships_by_file(conn: sqlite3.Connection, file_path: str) -> list[dict]:
    """
    Get all relationships in a file.

    Args:
        conn: SQLite connection
        file_path: File path

    Returns:
        List of relationship dicts
    """
    cursor = conn.execute("SELECT * FROM relationships WHERE file_path = ?", (file_path,))
    return [dict(row) for row in cursor.fetchall()]


def get_relationships_from_symbol(conn: sqlite3.Connection, symbol_id: str) -> list[dict]:
    """
    Get all relationships where the given symbol is the source (from_symbol_id).

    Used for dependency tracing - finds what a symbol depends on.

    Args:
        conn: SQLite connection
        symbol_id: ID of the source symbol

    Returns:
        List of dicts with keys including 'target_id' (the to_symbol_id) and 'kind'
    """
    cursor = conn.execute(
        """
        SELECT id, from_symbol_id, to_symbol_id as target_id, kind, file_path, line_number
        FROM relationships
        WHERE from_symbol_id = ?
        """,
        (symbol_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_reachability_for_target(conn: sqlite3.Connection, target_id: str) -> list[dict]:
    """
    Get all symbols that can reach the target (upstream/callers).

    Args:
        conn: SQLite connection
        target_id: ID of the target symbol

    Returns:
        List of dicts with source_id and min_distance
    """
    cursor = conn.execute(
        "SELECT source_id, target_id, min_distance FROM reachability WHERE target_id = ?",
        (target_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_reachability_from_source(conn: sqlite3.Connection, source_id: str) -> list[dict]:
    """
    Get all symbols reachable from source (downstream/callees).

    Args:
        conn: SQLite connection
        source_id: ID of the source symbol

    Returns:
        List of dicts with target_id and min_distance
    """
    cursor = conn.execute(
        "SELECT source_id, target_id, min_distance FROM reachability WHERE source_id = ?",
        (source_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_reachability_for_targets_batch(
    conn: sqlite3.Connection,
    target_ids: list[str],
    min_distance: int = 1,
) -> dict[str, list[dict]]:
    """
    Get callers (upstream) for multiple targets in a single query.

    OPTIMIZED: Uses single WHERE IN query instead of N individual queries.

    Args:
        conn: SQLite connection
        target_ids: List of target symbol IDs
        min_distance: Filter to only this distance (default 1 for direct callers)

    Returns:
        Dict mapping target_id -> list of caller dicts {source_id, min_distance}
    """
    if not target_ids:
        return {}

    placeholders = ",".join("?" * len(target_ids))
    cursor = conn.execute(
        f"""
        SELECT source_id, target_id, min_distance
        FROM reachability
        WHERE target_id IN ({placeholders}) AND min_distance = ?
        """,
        (*target_ids, min_distance),
    )

    # Group results by target_id
    result: dict[str, list[dict]] = {tid: [] for tid in target_ids}
    for row in cursor.fetchall():
        row_dict = dict(row)
        target_id = row_dict["target_id"]
        if target_id in result:
            result[target_id].append(row_dict)

    return result


def get_reachability_from_sources_batch(
    conn: sqlite3.Connection,
    source_ids: list[str],
    min_distance: int = 1,
) -> dict[str, list[dict]]:
    """
    Get callees (downstream) for multiple sources in a single query.

    OPTIMIZED: Uses single WHERE IN query instead of N individual queries.

    Args:
        conn: SQLite connection
        source_ids: List of source symbol IDs
        min_distance: Filter to only this distance (default 1 for direct callees)

    Returns:
        Dict mapping source_id -> list of callee dicts {target_id, min_distance}
    """
    if not source_ids:
        return {}

    placeholders = ",".join("?" * len(source_ids))
    cursor = conn.execute(
        f"""
        SELECT source_id, target_id, min_distance
        FROM reachability
        WHERE source_id IN ({placeholders}) AND min_distance = ?
        """,
        (*source_ids, min_distance),
    )

    # Group results by source_id
    result: dict[str, list[dict]] = {sid: [] for sid in source_ids}
    for row in cursor.fetchall():
        row_dict = dict(row)
        source_id = row_dict["source_id"]
        if source_id in result:
            result[source_id].append(row_dict)

    return result


def can_reach(conn: sqlite3.Connection, source_id: str, target_id: str) -> bool:
    """
    Check if source can reach target (O(1) lookup).

    Args:
        conn: SQLite connection
        source_id: ID of the source symbol
        target_id: ID of the target symbol

    Returns:
        True if path exists, False otherwise
    """
    cursor = conn.execute(
        "SELECT 1 FROM reachability WHERE source_id = ? AND target_id = ? LIMIT 1",
        (source_id, target_id),
    )
    return cursor.fetchone() is not None


def get_distance(conn: sqlite3.Connection, source_id: str, target_id: str) -> int | None:
    """
    Get shortest path distance between source and target.

    Args:
        conn: SQLite connection
        source_id: ID of the source symbol
        target_id: ID of the target symbol

    Returns:
        Shortest path length, or None if no path exists
    """
    cursor = conn.execute(
        "SELECT min_distance FROM reachability WHERE source_id = ? AND target_id = ?",
        (source_id, target_id),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_all_files(conn: sqlite3.Connection) -> list[dict]:
    """
    Get all indexed files with metadata for workspace scanning.

    Used for incremental indexing to detect which files have changed.

    Args:
        conn: SQLite connection

    Returns:
        List of dicts with keys: path, hash, language, size, last_indexed
    """
    cursor = conn.execute("""
        SELECT path, hash, language, size, last_modified, last_indexed
        FROM files
        ORDER BY path
    """)
    return [dict(row) for row in cursor.fetchall()]


def find_type_implementations(conn: sqlite3.Connection, type_name: str) -> list[dict]:
    """
    Find classes/structs that implement a given interface or type.

    Queries relationships with kind='implements' where the target symbol
    matches the given type name.

    Args:
        conn: SQLite connection
        type_name: Name of the interface/type to find implementations for

    Returns:
        List of symbol dicts representing implementing classes
    """
    cursor = conn.execute("""
        SELECT s.* FROM symbols s
        JOIN relationships r ON s.id = r.from_symbol_id
        JOIN symbols target ON r.to_symbol_id = target.id
        WHERE r.kind = 'implements' AND target.name = ?
    """, (type_name,))
    return [dict(row) for row in cursor.fetchall()]


def find_type_hierarchy(conn: sqlite3.Connection, type_name: str) -> tuple[list[dict], list[dict]]:
    """
    Find the type hierarchy for a given type.

    Returns both parent types (what this type extends/implements) and
    child types (what extends/implements this type).

    Args:
        conn: SQLite connection
        type_name: Name of the type to find hierarchy for

    Returns:
        Tuple of (parents, children) where each is a list of symbol dicts
    """
    # Find parents (types that this type extends)
    parents_cursor = conn.execute("""
        SELECT target.* FROM symbols target
        JOIN relationships r ON target.id = r.to_symbol_id
        JOIN symbols s ON r.from_symbol_id = s.id
        WHERE r.kind = 'extends' AND s.name = ?
    """, (type_name,))
    parents = [dict(row) for row in parents_cursor.fetchall()]

    # Find children (types that extend this type)
    children_cursor = conn.execute("""
        SELECT s.* FROM symbols s
        JOIN relationships r ON s.id = r.from_symbol_id
        JOIN symbols target ON r.to_symbol_id = target.id
        WHERE r.kind = 'extends' AND target.name = ?
    """, (type_name,))
    children = [dict(row) for row in children_cursor.fetchall()]

    return parents, children


def find_functions_returning_type(conn: sqlite3.Connection, type_name: str) -> list[dict]:
    """
    Find functions that return a given type.

    Queries relationships with kind='returns' where the target symbol
    matches the given type name.

    Args:
        conn: SQLite connection
        type_name: Name of the return type to search for

    Returns:
        List of function symbol dicts
    """
    cursor = conn.execute("""
        SELECT s.* FROM symbols s
        JOIN relationships r ON s.id = r.from_symbol_id
        JOIN symbols target ON r.to_symbol_id = target.id
        WHERE r.kind = 'returns' AND target.name = ?
    """, (type_name,))
    return [dict(row) for row in cursor.fetchall()]


def find_functions_with_parameter_type(conn: sqlite3.Connection, type_name: str) -> list[dict]:
    """
    Find functions that take a given type as a parameter.

    Queries relationships with kind='parameter' where the target symbol
    matches the given type name.

    Args:
        conn: SQLite connection
        type_name: Name of the parameter type to search for

    Returns:
        List of function symbol dicts
    """
    cursor = conn.execute("""
        SELECT s.* FROM symbols s
        JOIN relationships r ON s.id = r.from_symbol_id
        JOIN symbols target ON r.to_symbol_id = target.id
        WHERE r.kind = 'parameter' AND target.name = ?
    """, (type_name,))
    return [dict(row) for row in cursor.fetchall()]


def get_cross_directory_dependencies(
    conn: sqlite3.Connection,
    depth: int = 2,
    min_edge_count: int = 1,
) -> list[dict]:
    """
    Get aggregated dependencies between directories for architecture mapping.

    Aggregates relationships (calls, imports, references) between files and
    groups them by directory structure up to a specified depth. This provides
    a "zoom out" view of module dependencies.

    Args:
        conn: SQLite connection
        depth: Directory depth to aggregate at (default: 2)
               e.g., depth=2 for "src/auth" level from "src/auth/login.py"
        min_edge_count: Minimum relationship count to include (default: 1)

    Returns:
        List of dicts with:
        - source_dir: Source directory path
        - target_dir: Target directory path
        - edge_count: Number of relationships
        - relationship_kinds: Comma-separated list of relationship types

    Example:
        >>> get_cross_directory_dependencies(conn, depth=2)
        [
            {"source_dir": "src/auth", "target_dir": "src/db", "edge_count": 45, ...},
            {"source_dir": "src/api", "target_dir": "src/utils", "edge_count": 23, ...},
        ]
    """
    # Build SQL to extract directory prefix at specified depth
    # We use a combination of substr and instr to extract path components
    # This is SQLite-compatible and handles both / and \ path separators

    cursor = conn.execute(
        """
        WITH dir_edges AS (
            SELECT
                -- Extract source directory: get path up to depth components
                -- Using recursive substring extraction for cross-platform support
                CASE
                    WHEN instr(from_sym.file_path, '/') > 0 THEN
                        rtrim(
                            substr(from_sym.file_path, 1,
                                instr(
                                    substr(from_sym.file_path || '/',
                                        instr(from_sym.file_path || '/', '/') + 1
                                    ) || '/',
                                    '/'
                                ) + instr(from_sym.file_path || '/', '/') - 1
                            ),
                            '/'
                        )
                    ELSE from_sym.file_path
                END as source_dir,
                CASE
                    WHEN instr(to_sym.file_path, '/') > 0 THEN
                        rtrim(
                            substr(to_sym.file_path, 1,
                                instr(
                                    substr(to_sym.file_path || '/',
                                        instr(to_sym.file_path || '/', '/') + 1
                                    ) || '/',
                                    '/'
                                ) + instr(to_sym.file_path || '/', '/') - 1
                            ),
                            '/'
                        )
                    ELSE to_sym.file_path
                END as target_dir,
                r.kind as relationship_kind
            FROM relationships r
            JOIN symbols from_sym ON r.from_symbol_id = from_sym.id
            JOIN symbols to_sym ON r.to_symbol_id = to_sym.id
            WHERE from_sym.file_path != to_sym.file_path
        )
        SELECT
            source_dir,
            target_dir,
            COUNT(*) as edge_count,
            GROUP_CONCAT(DISTINCT relationship_kind) as relationship_kinds
        FROM dir_edges
        WHERE source_dir != target_dir
        GROUP BY source_dir, target_dir
        HAVING COUNT(*) >= ?
        ORDER BY edge_count DESC
        """,
        (min_edge_count,),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_exported_symbols(conn: sqlite3.Connection, file_path: str = None) -> list[dict]:
    """
    Get all exported/public symbols, optionally filtered by file.

    Used for import validation - checks if a symbol is available for import.

    Args:
        conn: SQLite connection
        file_path: Optional file path filter

    Returns:
        List of symbol dicts with id, name, kind, file_path, visibility
    """
    if file_path:
        cursor = conn.execute(
            """
            SELECT id, name, kind, file_path, visibility
            FROM symbols
            WHERE file_path = ?
            AND (visibility IS NULL OR visibility IN ('public', 'exported', ''))
            AND kind NOT IN ('parameter', 'variable', 'local')
            """,
            (file_path,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT id, name, kind, file_path, visibility
            FROM symbols
            WHERE (visibility IS NULL OR visibility IN ('public', 'exported', ''))
            AND kind NOT IN ('parameter', 'variable', 'local')
            """
        )
    return [dict(row) for row in cursor.fetchall()]


def find_symbols_by_name_prefix(
    conn: sqlite3.Connection,
    prefix: str,
    limit: int = 20,
) -> list[dict]:
    """
    Find symbols whose name starts with a given prefix.

    Used for import validation to suggest corrections for typos.

    Args:
        conn: SQLite connection
        prefix: Name prefix to search for
        limit: Maximum results

    Returns:
        List of symbol dicts
    """
    cursor = conn.execute(
        """
        SELECT id, name, kind, file_path, visibility
        FROM symbols
        WHERE name LIKE ? || '%'
        AND kind NOT IN ('parameter', 'variable', 'local')
        ORDER BY
            CASE WHEN name = ? THEN 0 ELSE 1 END,  -- Exact match first
            length(name)  -- Shorter names next
        LIMIT ?
        """,
        (prefix, prefix, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
