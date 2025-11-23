"""
Miller Storage Layer - SQLite

Provides persistent storage for extracted symbols.
Search functionality is handled by LanceDB (see embeddings.py).
"""

import sqlite3
from pathlib import Path
from typing import Any, Optional


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


class StorageManager:
    """
    Manages SQLite database for symbol storage.

    Features:
    - WAL mode for concurrent access
    - Foreign keys with CASCADE deletes
    - Relational storage for symbols, identifiers, relationships

    Note: Search is handled by LanceDB, not SQLite.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str = ".miller/indexes/symbols.db"):
        """
        Initialize storage with WAL mode and schema.

        Args:
            db_path: Path to SQLite database (use ":memory:" for testing)
        """
        # Create parent directory if needed
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        # Enable WAL mode (for file-based databases)
        if db_path != ":memory:":
            self._enable_wal()

        # Enable foreign keys
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Initialize schema
        self._initialize_schema()

    def _enable_wal(self):
        """Enable Write-Ahead Logging for concurrent access."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        mode = cursor.fetchone()[0]

        if not mode.upper() == "WAL":
            raise StorageError(
                f"Failed to enable WAL mode (got '{mode}'). This filesystem may not support WAL."
            )

        # Set busy timeout (wait up to 5 seconds for locks)
        self.conn.execute("PRAGMA busy_timeout = 5000")

        # Set synchronous to NORMAL (safe with WAL, faster than FULL)
        self.conn.execute("PRAGMA synchronous = NORMAL")

    def _initialize_schema(self):
        """Create all tables if they don't exist."""
        # Files table
        self.conn.execute("""
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
        self.conn.execute("""
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
        self.conn.execute("""
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
        self.conn.execute("""
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
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reachability (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                min_distance INTEGER NOT NULL,
                PRIMARY KEY (source_id, target_id)
            )
        """)

        # Create indexes
        self._create_indexes()

        self.conn.commit()

    def _create_indexes(self):
        """Create indexes for fast queries."""
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
        ]

        for index_sql in indexes:
            self.conn.execute(index_sql)

    # File operations

    def add_file(self, file_path: str, language: str, content: str, hash: str, size: int) -> None:
        """
        Add or update a file record.

        Args:
            file_path: Relative file path
            language: Programming language
            content: File content (stored for reference)
            hash: Content hash (for change detection)
            size: File size in bytes
        """
        import time

        timestamp = int(time.time())

        # Normalize path to match symbols table (for FK constraints)
        normalized_path = _normalize_path(file_path)

        self.conn.execute(
            """
            INSERT OR REPLACE INTO files (
                path, language, content, hash, size, last_modified, last_indexed
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (normalized_path, language, content, hash, size, timestamp, timestamp),
        )

        self.conn.commit()

    def delete_file(self, file_path: str) -> None:
        """
        Delete file and CASCADE to symbols/identifiers/relationships.

        Args:
            file_path: File path to delete
        """
        self.conn.execute("DELETE FROM files WHERE path = ?", (file_path,))
        self.conn.commit()

    # Symbol operations

    def add_symbols_batch(self, symbols: list[Any]) -> int:
        """
        Bulk insert symbols.

        Args:
            symbols: List of PySymbol objects from extraction

        Returns:
            Number of symbols inserted
        """
        if not symbols:
            return 0

        # Convert PySymbol objects to tuples
        symbol_data = []
        for sym in symbols:
            symbol_data.append(
                (
                    sym.id,
                    sym.name,
                    sym.kind,
                    sym.language,
                    _normalize_path(sym.file_path),  # Normalize path for FK constraints
                    sym.signature,
                    sym.start_line,
                    sym.start_column,
                    sym.end_line,
                    sym.end_column,
                    sym.start_byte,
                    sym.end_byte,
                    sym.doc_comment,
                    sym.visibility,
                    sym.code_context,
                    sym.parent_id,
                    None,  # metadata (TODO: serialize dict to JSON)
                    None,  # file_hash
                    0,  # last_indexed
                    sym.semantic_group,
                    sym.confidence,
                    sym.content_type,
                )
            )

        self.conn.executemany(
            """
            INSERT OR REPLACE INTO symbols (
                id, name, kind, language, file_path,
                signature, start_line, start_col, end_line, end_col,
                start_byte, end_byte, doc_comment, visibility, code_context,
                parent_id, metadata, file_hash, last_indexed,
                semantic_group, confidence, content_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            symbol_data,
        )

        self.conn.commit()
        return len(symbol_data)

    def get_symbol_by_name(self, name: str) -> Optional[dict]:
        """
        Get first symbol by name, preferring definitions over references.

        When multiple symbols share the same name (e.g., import + function definition),
        returns the definition rather than the reference.

        Args:
            name: Symbol name to search for

        Returns:
            Dict with symbol data, or None if not found
        """
        # Order by kind priority: definitions (function, class, etc.) before references (import)
        cursor = self.conn.execute("""
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

    def get_symbol_by_id(self, symbol_id: str) -> Optional[dict]:
        """Get symbol by ID."""
        cursor = self.conn.execute("SELECT * FROM symbols WHERE id = ?", (symbol_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    # Identifier operations

    def add_identifiers_batch(self, identifiers: list[Any]) -> int:
        """Bulk insert identifiers."""
        if not identifiers:
            return 0

        identifier_data = []
        for ident in identifiers:
            identifier_data.append(
                (
                    ident.id,
                    ident.name,
                    ident.kind,
                    ident.language,
                    _normalize_path(ident.file_path),  # Normalize path for FK constraints
                    ident.start_line,
                    ident.start_column,
                    ident.end_line,
                    ident.end_column,
                    ident.start_byte,
                    ident.end_byte,
                    ident.containing_symbol_id,
                    ident.target_symbol_id,
                    ident.confidence,
                    ident.code_context,
                    0,  # last_indexed
                )
            )

        self.conn.executemany(
            """
            INSERT OR REPLACE INTO identifiers (
                id, name, kind, language, file_path,
                start_line, start_col, end_line, end_col,
                start_byte, end_byte, containing_symbol_id, target_symbol_id,
                confidence, code_context, last_indexed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            identifier_data,
        )

        self.conn.commit()
        return len(identifier_data)

    def get_identifiers_by_file(self, file_path: str) -> list[dict]:
        """Get all identifiers in a file."""
        cursor = self.conn.execute("SELECT * FROM identifiers WHERE file_path = ?", (file_path,))
        return [dict(row) for row in cursor.fetchall()]

    # Relationship operations

    def add_relationships_batch(self, relationships: list[Any]) -> int:
        """Bulk insert relationships."""
        if not relationships:
            return 0

        relationship_data = []
        for rel in relationships:
            relationship_data.append(
                (
                    rel.id,
                    rel.from_symbol_id,
                    rel.to_symbol_id,
                    rel.kind,
                    _normalize_path(rel.file_path),  # Normalize path for FK constraints
                    rel.line_number,
                    rel.confidence,
                    None,  # metadata (TODO: serialize)
                    0,  # created_at
                )
            )

        self.conn.executemany(
            """
            INSERT OR REPLACE INTO relationships (
                id, from_symbol_id, to_symbol_id, kind, file_path,
                line_number, confidence, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            relationship_data,
        )

        self.conn.commit()
        return len(relationship_data)

    def get_relationships_by_file(self, file_path: str) -> list[dict]:
        """Get all relationships in a file."""
        cursor = self.conn.execute("SELECT * FROM relationships WHERE file_path = ?", (file_path,))
        return [dict(row) for row in cursor.fetchall()]

    def get_relationships_from_symbol(self, symbol_id: str) -> list[dict]:
        """
        Get all relationships where the given symbol is the source (from_symbol_id).

        Used for dependency tracing - finds what a symbol depends on.

        Args:
            symbol_id: ID of the source symbol

        Returns:
            List of dicts with keys including 'target_id' (the to_symbol_id) and 'kind'
        """
        cursor = self.conn.execute(
            """
            SELECT id, from_symbol_id, to_symbol_id as target_id, kind, file_path, line_number
            FROM relationships
            WHERE from_symbol_id = ?
            """,
            (symbol_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # Reachability operations (transitive closure)

    def add_reachability_batch(self, entries: list[tuple[str, str, int]]) -> int:
        """
        Bulk insert reachability entries.

        Args:
            entries: List of (source_id, target_id, min_distance) tuples

        Returns:
            Number of entries inserted
        """
        if not entries:
            return 0

        self.conn.executemany(
            "INSERT OR REPLACE INTO reachability (source_id, target_id, min_distance) VALUES (?, ?, ?)",
            entries,
        )
        self.conn.commit()
        return len(entries)

    def clear_reachability(self) -> None:
        """Clear all reachability data."""
        self.conn.execute("DELETE FROM reachability")
        self.conn.commit()

    def get_reachability_for_target(self, target_id: str) -> list[dict]:
        """
        Get all symbols that can reach the target (upstream/callers).

        Args:
            target_id: ID of the target symbol

        Returns:
            List of dicts with source_id and min_distance
        """
        cursor = self.conn.execute(
            "SELECT source_id, target_id, min_distance FROM reachability WHERE target_id = ?",
            (target_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_reachability_from_source(self, source_id: str) -> list[dict]:
        """
        Get all symbols reachable from source (downstream/callees).

        Args:
            source_id: ID of the source symbol

        Returns:
            List of dicts with target_id and min_distance
        """
        cursor = self.conn.execute(
            "SELECT source_id, target_id, min_distance FROM reachability WHERE source_id = ?",
            (source_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def can_reach(self, source_id: str, target_id: str) -> bool:
        """
        Check if source can reach target (O(1) lookup).

        Args:
            source_id: ID of the source symbol
            target_id: ID of the target symbol

        Returns:
            True if path exists, False otherwise
        """
        cursor = self.conn.execute(
            "SELECT 1 FROM reachability WHERE source_id = ? AND target_id = ? LIMIT 1",
            (source_id, target_id),
        )
        return cursor.fetchone() is not None

    def get_distance(self, source_id: str, target_id: str) -> int | None:
        """
        Get shortest path distance between source and target.

        Args:
            source_id: ID of the source symbol
            target_id: ID of the target symbol

        Returns:
            Shortest path length, or None if no path exists
        """
        cursor = self.conn.execute(
            "SELECT min_distance FROM reachability WHERE source_id = ? AND target_id = ?",
            (source_id, target_id),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    # Workspace scanning operations

    def get_all_files(self) -> list[dict]:
        """
        Get all indexed files with metadata for workspace scanning.

        Used for incremental indexing to detect which files have changed.

        Returns:
            List of dicts with keys: path, hash, language, size, last_indexed
        """
        cursor = self.conn.execute("""
            SELECT path, hash, language, size, last_modified, last_indexed
            FROM files
            ORDER BY path
        """)
        return [dict(row) for row in cursor.fetchall()]

    # Type intelligence queries

    def find_type_implementations(self, type_name: str) -> list[dict]:
        """
        Find classes/structs that implement a given interface or type.

        Queries relationships with kind='implements' where the target symbol
        matches the given type name.

        Args:
            type_name: Name of the interface/type to find implementations for

        Returns:
            List of symbol dicts representing implementing classes
        """
        cursor = self.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN relationships r ON s.id = r.from_symbol_id
            JOIN symbols target ON r.to_symbol_id = target.id
            WHERE r.kind = 'implements' AND target.name = ?
        """, (type_name,))
        return [dict(row) for row in cursor.fetchall()]

    def find_type_hierarchy(self, type_name: str) -> tuple[list[dict], list[dict]]:
        """
        Find the type hierarchy for a given type.

        Returns both parent types (what this type extends/implements) and
        child types (what extends/implements this type).

        Args:
            type_name: Name of the type to find hierarchy for

        Returns:
            Tuple of (parents, children) where each is a list of symbol dicts
        """
        # Find parents (types that this type extends)
        parents_cursor = self.conn.execute("""
            SELECT target.* FROM symbols target
            JOIN relationships r ON target.id = r.to_symbol_id
            JOIN symbols s ON r.from_symbol_id = s.id
            WHERE r.kind = 'extends' AND s.name = ?
        """, (type_name,))
        parents = [dict(row) for row in parents_cursor.fetchall()]

        # Find children (types that extend this type)
        children_cursor = self.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN relationships r ON s.id = r.from_symbol_id
            JOIN symbols target ON r.to_symbol_id = target.id
            WHERE r.kind = 'extends' AND target.name = ?
        """, (type_name,))
        children = [dict(row) for row in children_cursor.fetchall()]

        return parents, children

    def find_functions_returning_type(self, type_name: str) -> list[dict]:
        """
        Find functions that return a given type.

        Queries relationships with kind='returns' where the target symbol
        matches the given type name.

        Args:
            type_name: Name of the return type to search for

        Returns:
            List of function symbol dicts
        """
        cursor = self.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN relationships r ON s.id = r.from_symbol_id
            JOIN symbols target ON r.to_symbol_id = target.id
            WHERE r.kind = 'returns' AND target.name = ?
        """, (type_name,))
        return [dict(row) for row in cursor.fetchall()]

    def find_functions_with_parameter_type(self, type_name: str) -> list[dict]:
        """
        Find functions that take a given type as a parameter.

        Queries relationships with kind='parameter' where the target symbol
        matches the given type name.

        Args:
            type_name: Name of the parameter type to search for

        Returns:
            List of function symbol dicts
        """
        cursor = self.conn.execute("""
            SELECT s.* FROM symbols s
            JOIN relationships r ON s.id = r.from_symbol_id
            JOIN symbols target ON r.to_symbol_id = target.id
            WHERE r.kind = 'parameter' AND target.name = ?
        """, (type_name,))
        return [dict(row) for row in cursor.fetchall()]

    def incremental_update_atomic(
        self,
        files_to_clean: list[str],
        file_data: list[tuple],
        symbols: list,
        identifiers: list,
        relationships: list,
    ) -> dict:
        """
        Perform atomic incremental update - delete old data and insert new in single transaction.

        This mirrors Julie's incremental_update_atomic() pattern which prevents data corruption
        during incremental updates. If any step fails, the entire operation is rolled back.

        Args:
            files_to_clean: List of file paths to delete (for re-indexing)
            file_data: List of (path, language, content, hash, size) tuples
            symbols: List of PySymbol objects to insert
            identifiers: List of PyIdentifier objects to insert
            relationships: List of PyRelationship objects to insert

        Returns:
            Dict with counts: {files_cleaned, files_added, symbols_added, identifiers_added, relationships_added}

        Raises:
            StorageError: If atomic update fails (transaction is rolled back)
        """
        import time

        timestamp = int(time.time())
        counts = {
            "files_cleaned": 0,
            "files_added": 0,
            "symbols_added": 0,
            "identifiers_added": 0,
            "relationships_added": 0,
        }

        try:
            # Start transaction
            cursor = self.conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")

            # Step 1: Delete old data for files being re-indexed
            # CASCADE will handle symbols, identifiers, relationships
            for file_path in files_to_clean:
                cursor.execute("DELETE FROM files WHERE path = ?", (file_path,))
                counts["files_cleaned"] += cursor.rowcount

            # Step 2: Insert new file records
            for path, language, content, file_hash, size in file_data:
                normalized_path = _normalize_path(path)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO files
                    (path, language, content, hash, size, last_modified, last_indexed)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (normalized_path, language, content, file_hash, size, timestamp, timestamp),
                )
                counts["files_added"] += 1

            # Step 3: Insert symbols (OR REPLACE for safety if cleanup missed any)
            for sym in symbols:
                file_path = _normalize_path(sym.file_path)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO symbols
                    (id, name, kind, signature, file_path, start_line, end_line, parent_id, language, doc_comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sym.id,
                        sym.name,
                        sym.kind,
                        sym.signature,
                        file_path,
                        sym.start_line,
                        sym.end_line,
                        sym.parent_id,
                        sym.language,
                        sym.doc_comment,
                    ),
                )
                counts["symbols_added"] += 1

            # Step 4: Insert identifiers (OR REPLACE for safety if cleanup missed any)
            for ident in identifiers:
                file_path = _normalize_path(ident.file_path)
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO identifiers (
                        id, name, kind, language, file_path,
                        start_line, start_col, end_line, end_col,
                        start_byte, end_byte, containing_symbol_id, target_symbol_id,
                        confidence, code_context, last_indexed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ident.id,
                        ident.name,
                        ident.kind,
                        ident.language,
                        file_path,
                        ident.start_line,
                        ident.start_column,  # PyIdentifier uses start_column → DB start_col
                        ident.end_line,
                        ident.end_column,  # PyIdentifier uses end_column → DB end_col
                        ident.start_byte,
                        ident.end_byte,
                        ident.containing_symbol_id,
                        ident.target_symbol_id,
                        ident.confidence,
                        ident.code_context,
                        timestamp,  # last_indexed
                    ),
                )
                counts["identifiers_added"] += 1

            # Step 5: Insert relationships (OR REPLACE for safety if cleanup missed any)
            for rel in relationships:
                file_path = _normalize_path(rel.file_path) if rel.file_path else None
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO relationships
                    (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rel.id,
                        rel.from_symbol_id,
                        rel.to_symbol_id,
                        rel.kind,
                        file_path,
                        rel.line_number,
                    ),
                )
                counts["relationships_added"] += 1

            # Step 6: Commit entire transaction atomically
            self.conn.commit()

            return counts

        except Exception as e:
            # Rollback on any failure
            self.conn.rollback()
            raise StorageError(f"Atomic incremental update failed: {e}") from e

    def close(self):
        """Close database connection."""
        self.conn.close()

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.close()
