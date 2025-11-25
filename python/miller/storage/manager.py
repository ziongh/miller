"""
Miller Storage Manager - Main SQLite database manager.

Provides high-level interface to storage operations while delegating to
schema, queries, and mutations modules.
"""

import sqlite3
from pathlib import Path
from typing import Any, Optional

from . import mutations, queries
from .schema import StorageError, enable_wal, initialize_schema, _normalize_path


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
        # check_same_thread=False is required for async/background tasks where
        # connection creation thread may differ from usage thread (common on Windows).
        # This is safe because we use WAL mode and serialize writes with commit().
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        # Enable WAL mode (for file-based databases)
        if db_path != ":memory:":
            enable_wal(self.conn)

        # Enable foreign keys
        self.conn.execute("PRAGMA foreign_keys = ON")

        # Initialize schema
        initialize_schema(self.conn)

    # File operations

    def add_file(
        self, file_path: str, language: str, content: str, hash: str, size: int
    ) -> None:
        """
        Add or update a file record.

        Args:
            file_path: Relative file path
            language: Programming language
            content: File content (stored for reference)
            hash: Content hash (for change detection)
            size: File size in bytes
        """
        mutations.add_file(self.conn, file_path, language, content, hash, size)

    def delete_file(self, file_path: str) -> None:
        """
        Delete file and CASCADE to symbols/identifiers/relationships.

        Args:
            file_path: File path to delete
        """
        mutations.delete_file(self.conn, file_path)

    def delete_files_batch(self, file_paths: list[str]) -> int:
        """Delete multiple files in single transaction (batch version)."""
        return mutations.delete_files_batch(self.conn, file_paths)

    # Symbol operations

    def add_symbols_batch(
        self, symbols: list[Any], code_context_map: Optional[dict[str, str]] = None
    ) -> int:
        """
        Bulk insert symbols.

        Args:
            symbols: List of PySymbol objects from extraction
            code_context_map: Optional dict mapping symbol_id to computed code_context.
                             Used for grep-style output (computed from file content).

        Returns:
            Number of symbols inserted
        """
        return mutations.add_symbols_batch(self.conn, symbols, code_context_map)

    def get_symbol_by_name(self, name: str) -> Optional[dict]:
        """
        Get first symbol by name, preferring definitions over references.

        Args:
            name: Symbol name to search for

        Returns:
            Dict with symbol data, or None if not found
        """
        return queries.get_symbol_by_name(self.conn, name)

    def get_symbol_by_id(self, symbol_id: str) -> Optional[dict]:
        """Get symbol by ID."""
        return queries.get_symbol_by_id(self.conn, symbol_id)

    def get_symbols_by_ids(self, symbol_ids: list[str]) -> dict[str, dict]:
        """Get multiple symbols by ID in single query (batch version)."""
        return queries.get_symbols_by_ids(self.conn, symbol_ids)

    # Identifier operations

    def add_identifiers_batch(self, identifiers: list[Any]) -> int:
        """Bulk insert identifiers."""
        return mutations.add_identifiers_batch(self.conn, identifiers)

    def get_identifiers_by_file(self, file_path: str) -> list[dict]:
        """Get all identifiers in a file."""
        return queries.get_identifiers_by_file(self.conn, file_path)

    # Relationship operations

    def add_relationships_batch(self, relationships: list[Any]) -> int:
        """Bulk insert relationships."""
        return mutations.add_relationships_batch(self.conn, relationships)

    def get_relationships_by_file(self, file_path: str) -> list[dict]:
        """Get all relationships in a file."""
        return queries.get_relationships_by_file(self.conn, file_path)

    def get_relationships_from_symbol(self, symbol_id: str) -> list[dict]:
        """Get all relationships where the given symbol is the source."""
        return queries.get_relationships_from_symbol(self.conn, symbol_id)

    # Reachability operations (transitive closure)

    def add_reachability_batch(self, entries: list[tuple[str, str, int]]) -> int:
        """Bulk insert reachability entries."""
        return mutations.add_reachability_batch(self.conn, entries)

    def clear_reachability(self) -> None:
        """Clear all reachability data."""
        mutations.clear_reachability(self.conn)

    def clear_all(self) -> None:
        """
        Clear all data from all tables (for force re-indexing).

        Use this before a complete rebuild of the index.
        """
        mutations.clear_all(self.conn)

    def get_reachability_for_target(self, target_id: str) -> list[dict]:
        """Get all symbols that can reach the target (upstream/callers)."""
        return queries.get_reachability_for_target(self.conn, target_id)

    def get_reachability_from_source(self, source_id: str) -> list[dict]:
        """Get all symbols reachable from source (downstream/callees)."""
        return queries.get_reachability_from_source(self.conn, source_id)

    def get_reachability_for_targets_batch(
        self, target_ids: list[str], min_distance: int = 1
    ) -> dict[str, list[dict]]:
        """Get callers for multiple targets in single query (batch version)."""
        return queries.get_reachability_for_targets_batch(
            self.conn, target_ids, min_distance
        )

    def get_reachability_from_sources_batch(
        self, source_ids: list[str], min_distance: int = 1
    ) -> dict[str, list[dict]]:
        """Get callees for multiple sources in single query (batch version)."""
        return queries.get_reachability_from_sources_batch(
            self.conn, source_ids, min_distance
        )

    def can_reach(self, source_id: str, target_id: str) -> bool:
        """Check if source can reach target (O(1) lookup)."""
        return queries.can_reach(self.conn, source_id, target_id)

    def get_distance(self, source_id: str, target_id: str) -> int | None:
        """Get shortest path distance between source and target."""
        return queries.get_distance(self.conn, source_id, target_id)

    # Workspace scanning operations

    def get_all_files(self) -> list[dict]:
        """Get all indexed files with metadata for workspace scanning."""
        return queries.get_all_files(self.conn)

    # Type intelligence queries

    def find_type_implementations(self, type_name: str) -> list[dict]:
        """Find classes/structs that implement a given interface or type."""
        return queries.find_type_implementations(self.conn, type_name)

    def find_type_hierarchy(self, type_name: str) -> tuple[list[dict], list[dict]]:
        """Find the type hierarchy for a given type."""
        return queries.find_type_hierarchy(self.conn, type_name)

    def find_functions_returning_type(self, type_name: str) -> list[dict]:
        """Find functions that return a given type."""
        return queries.find_functions_returning_type(self.conn, type_name)

    def find_functions_with_parameter_type(self, type_name: str) -> list[dict]:
        """Find functions that take a given type as a parameter."""
        return queries.find_functions_with_parameter_type(self.conn, type_name)

    # Atomic operations

    def incremental_update_atomic(
        self,
        files_to_clean: list[str],
        file_data: list[tuple],
        symbols: list,
        identifiers: list,
        relationships: list,
        code_context_map: Optional[dict[str, str]] = None,
    ) -> dict:
        """
        Perform atomic incremental update.

        See mutations.incremental_update_atomic for full documentation.
        """
        return mutations.incremental_update_atomic(
            self.conn,
            files_to_clean,
            file_data,
            symbols,
            identifiers,
            relationships,
            code_context_map,
        )

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.close()

    def __del__(self):
        """
        Safety net - close connection if not explicitly closed.

        This prevents "unclosed database" warnings when StorageManager
        instances are garbage collected without calling close().
        """
        try:
            self.close()
        except Exception:
            pass  # Ignore errors during cleanup
