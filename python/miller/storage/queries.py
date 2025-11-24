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
