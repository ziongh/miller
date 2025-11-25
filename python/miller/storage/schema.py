"""
Miller Storage Schema - Database initialization and setup.

Handles:
- Table creation
- Index creation
- WAL mode configuration
- Foreign key setup
"""

import sqlite3
from typing import Any


class StorageError(Exception):
    """Raised when storage operations fail."""

    pass


def _normalize_path(path: str) -> str:
    r"""
    Normalize file path to remove Windows UNC prefix.

    Rust's path canonicalization adds \\?\ prefix on Windows for absolute paths.
    We strip this to ensure FK constraints work correctly.
    """
    if path and path.startswith("\\\\?\\"):
        return path[4:]  # Strip \\?\
    return path


def enable_wal(conn: sqlite3.Connection) -> None:
    """
    Enable Write-Ahead Logging for concurrent access.

    Args:
        conn: SQLite connection

    Raises:
        StorageError: If WAL mode cannot be enabled
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    mode = cursor.fetchone()[0]

    if not mode.upper() == "WAL":
        raise StorageError(
            f"Failed to enable WAL mode (got '{mode}'). This filesystem may not support WAL."
        )

    # Set busy timeout (wait up to 5 seconds for locks)
    conn.execute("PRAGMA busy_timeout = 5000")

    # Set synchronous to NORMAL (safe with WAL, faster than FULL)
    conn.execute("PRAGMA synchronous = NORMAL")


def create_indexes(conn: sqlite3.Connection) -> None:
    """
    Create indexes for fast queries.

    Args:
        conn: SQLite connection
    """
    indexes = [
        # Symbol indexes
        "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)",
        "CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind)",
        "CREATE INDEX IF NOT EXISTS idx_symbols_language ON symbols(language)",
        "CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path)",
        "CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_id)",
        # File indexes
        "CREATE INDEX IF NOT EXISTS idx_files_language ON files(language)",
        # Identifier indexes
        "CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(name)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_file ON identifiers(file_path)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_containing ON identifiers(containing_symbol_id)",
        # Relationship indexes
        "CREATE INDEX IF NOT EXISTS idx_rel_from ON relationships(from_symbol_id)",
        "CREATE INDEX IF NOT EXISTS idx_rel_to ON relationships(to_symbol_id)",
        "CREATE INDEX IF NOT EXISTS idx_rel_kind ON relationships(kind)",
        # Reachability indexes (transitive closure)
        "CREATE INDEX IF NOT EXISTS idx_reach_source ON reachability(source_id)",
        "CREATE INDEX IF NOT EXISTS idx_reach_target ON reachability(target_id)",
        # Composite indexes for batch reachability queries with distance filtering
        # These optimize queries like: WHERE target_id IN (...) AND min_distance = 1
        "CREATE INDEX IF NOT EXISTS idx_reach_target_dist ON reachability(target_id, min_distance)",
        "CREATE INDEX IF NOT EXISTS idx_reach_source_dist ON reachability(source_id, min_distance)",
    ]

    for index_sql in indexes:
        conn.execute(index_sql)


def initialize_schema(conn: sqlite3.Connection) -> None:
    """
    Create all tables if they don't exist.

    Args:
        conn: SQLite connection
    """
    # Files table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            language TEXT NOT NULL,
            hash TEXT NOT NULL,
            size INTEGER NOT NULL,
            last_modified INTEGER NOT NULL,
            last_indexed INTEGER DEFAULT 0,
            symbol_count INTEGER DEFAULT 0,
            content TEXT
        )
    """)

    # Symbols table (core data)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            language TEXT NOT NULL,
            file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
            signature TEXT,
            start_line INTEGER,
            start_col INTEGER,
            end_line INTEGER,
            end_col INTEGER,
            start_byte INTEGER,
            end_byte INTEGER,
            doc_comment TEXT,
            visibility TEXT,
            code_context TEXT,
            parent_id TEXT REFERENCES symbols(id),
            metadata TEXT,
            file_hash TEXT,
            last_indexed INTEGER DEFAULT 0,
            semantic_group TEXT,
            confidence REAL DEFAULT 1.0,
            content_type TEXT DEFAULT NULL
        )
    """)

    # Identifiers table (usage references)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS identifiers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            language TEXT NOT NULL,
            file_path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
            start_line INTEGER NOT NULL,
            start_col INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            end_col INTEGER NOT NULL,
            start_byte INTEGER,
            end_byte INTEGER,
            containing_symbol_id TEXT REFERENCES symbols(id) ON DELETE CASCADE,
            target_symbol_id TEXT REFERENCES symbols(id) ON DELETE SET NULL,
            confidence REAL DEFAULT 1.0,
            code_context TEXT,
            last_indexed INTEGER DEFAULT 0
        )
    """)

    # Relationships table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            from_symbol_id TEXT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            to_symbol_id TEXT NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            file_path TEXT NOT NULL DEFAULT '',
            line_number INTEGER NOT NULL DEFAULT 0,
            confidence REAL DEFAULT 1.0,
            metadata TEXT,
            created_at INTEGER DEFAULT 0
        )
    """)

    # Reachability table (transitive closure for fast impact analysis)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reachability (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            min_distance INTEGER NOT NULL,
            PRIMARY KEY (source_id, target_id)
        )
    """)

    # Create indexes
    create_indexes(conn)

    conn.commit()
