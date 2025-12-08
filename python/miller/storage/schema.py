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
    Enable Write-Ahead Logging with aggressive performance tuning.

    Optimizations for high-throughput identifier writes:
    - Larger autocheckpoint (~40MB) reduces checkpoint frequency
    - Memory mapping reduces read I/O during heavy writes
    - Temp tables in RAM avoid disk spills
    - Longer busy timeout prevents lock failures

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

    # SYNCHRONOUS = NORMAL: Safe with WAL, writes pass to OS cache without force-flush
    conn.execute("PRAGMA synchronous = NORMAL")

    # AUTOCHECKPOINT: Default is 1000 pages (~4MB). We use 10000 (~40MB).
    # Checkpoints happen less often but in larger, more efficient batches.
    conn.execute("PRAGMA wal_autocheckpoint = 10000")

    # MMAP: Allow SQLite to access DB as if it were RAM (512MB mapping).
    # Greatly reduces read I/O lag during heavy writes.
    conn.execute(f"PRAGMA mmap_size = {512 * 1024 * 1024}")

    # BUSY TIMEOUT: Wait up to 10 seconds for locks (longer for big transactions)
    conn.execute("PRAGMA busy_timeout = 10000")

    # TEMP STORE: Keep temp tables/indices in RAM, not disk
    conn.execute("PRAGMA temp_store = MEMORY")


def migrate_schema(conn: sqlite3.Connection) -> None:
    """
    Apply schema migrations to existing databases.

    This handles adding new columns that weren't in the original schema.
    SQLite's CREATE TABLE IF NOT EXISTS won't modify existing tables,
    so we need explicit ALTER TABLE statements.

    Args:
        conn: SQLite connection
    """
    cursor = conn.cursor()

    # Helper to check if column exists in a table
    def has_column(table: str, column: str) -> bool:
        cursor.execute(f"PRAGMA table_info({table})")
        return column in {row[1] for row in cursor.fetchall()}

    # Helper to check if table exists
    def table_exists(table: str) -> bool:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        )
        return cursor.fetchone() is not None

    # Check if symbols table exists
    if not table_exists("symbols"):
        return  # Table doesn't exist yet, will be created fresh

    # Add reference_count column if missing (added for importance-based sorting)
    if not has_column("symbols", "reference_count"):
        cursor.execute("ALTER TABLE symbols ADD COLUMN reference_count INTEGER DEFAULT 0")

    # Migration: Add workspace_id columns (for unified multi-workspace database)
    # All existing data gets 'primary' as default workspace
    tables_needing_workspace_id = ["files", "symbols", "identifiers", "relationships"]
    for table in tables_needing_workspace_id:
        if table_exists(table) and not has_column(table, "workspace_id"):
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'primary'"
            )

    conn.commit()


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
        # Reference count index for importance-based sorting
        "CREATE INDEX IF NOT EXISTS idx_symbols_refcount ON symbols(reference_count DESC)",
        # Workspace indexes (for filtering by workspace and efficient workspace deletion)
        "CREATE INDEX IF NOT EXISTS idx_files_workspace ON files(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_symbols_workspace ON symbols(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_identifiers_workspace ON identifiers(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationships_workspace ON relationships(workspace_id)",
    ]

    for index_sql in indexes:
        conn.execute(index_sql)


def drop_identifier_indexes(conn: sqlite3.Connection) -> None:
    """
    Temporarily drop identifier indexes for faster bulk inserts.

    During massive scans (>1000 files), updating indexes on each insert
    is slower than:
    1. Drop indexes
    2. Bulk insert all data
    3. Re-create indexes once

    Args:
        conn: SQLite connection
    """
    conn.execute("DROP INDEX IF EXISTS idx_identifiers_name")
    conn.execute("DROP INDEX IF EXISTS idx_identifiers_file")
    conn.execute("DROP INDEX IF EXISTS idx_identifiers_containing")
    conn.commit()


def restore_identifier_indexes(conn: sqlite3.Connection) -> None:
    """
    Re-create identifier indexes after bulk inserts.

    Args:
        conn: SQLite connection
    """
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_name ON identifiers(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_file ON identifiers(file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identifiers_containing ON identifiers(containing_symbol_id)")
    conn.commit()


def initialize_schema(conn: sqlite3.Connection) -> None:
    """
    Create all tables if they don't exist.

    Args:
        conn: SQLite connection
    """
    # Files table
    # path format: "{workspace_id}:{relative_path}" for global uniqueness
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT 'primary',
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
    # workspace_id denormalized for efficient filtering
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT 'primary',
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
            content_type TEXT DEFAULT NULL,
            reference_count INTEGER DEFAULT 0
        )
    """)

    # Identifiers table (usage references)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS identifiers (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT 'primary',
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
    # Note: from_symbol_id and to_symbol_id can be from DIFFERENT workspaces!
    # This enables cross-workspace call tracing.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL DEFAULT 'primary',
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

    # Apply migrations for existing databases (adds new columns if needed)
    migrate_schema(conn)

    # Create indexes
    create_indexes(conn)

    conn.commit()
