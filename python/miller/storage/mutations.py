"""
Miller Storage Mutations - Write database operations.

Handles:
- File CRUD operations
- Symbol batch inserts
- Identifier batch inserts
- Relationship batch inserts
- Reachability updates
- Atomic incremental updates
"""

import sqlite3
import time
from typing import Any, Optional

from .schema import StorageError, _normalize_path


def add_file(
    conn: sqlite3.Connection,
    file_path: str,
    language: str,
    content: str,
    hash: str,
    size: int,
) -> None:
    """
    Add or update a file record.

    Args:
        conn: SQLite connection
        file_path: Relative file path
        language: Programming language
        content: File content (stored for reference)
        hash: Content hash (for change detection)
        size: File size in bytes
    """
    timestamp = int(time.time())

    # Normalize path to match symbols table (for FK constraints)
    normalized_path = _normalize_path(file_path)

    conn.execute(
        """
        INSERT OR REPLACE INTO files (
            path, language, content, hash, size, last_modified, last_indexed
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (normalized_path, language, content, hash, size, timestamp, timestamp),
    )

    conn.commit()


def delete_file(conn: sqlite3.Connection, file_path: str) -> None:
    """
    Delete file and CASCADE to symbols/identifiers/relationships.

    Args:
        conn: SQLite connection
        file_path: File path to delete
    """
    conn.execute("DELETE FROM files WHERE path = ?", (file_path,))
    conn.commit()


def delete_files_batch(conn: sqlite3.Connection, file_paths: list[str]) -> int:
    """
    Delete multiple files in single transaction.

    OPTIMIZED: Uses single transaction instead of N individual commits.
    CASCADE will handle symbols/identifiers/relationships automatically.

    Args:
        conn: SQLite connection
        file_paths: List of file paths to delete

    Returns:
        Number of files deleted
    """
    if not file_paths:
        return 0

    conn.executemany(
        "DELETE FROM files WHERE path = ?",
        [(path,) for path in file_paths]
    )
    conn.commit()
    return len(file_paths)


def add_symbols_batch(
    conn: sqlite3.Connection,
    symbols: list[Any],
    code_context_map: Optional[dict[str, str]] = None,
) -> int:
    """
    Bulk insert symbols.

    Args:
        conn: SQLite connection
        symbols: List of PySymbol objects from extraction
        code_context_map: Optional dict mapping symbol_id to computed code_context.
                         If provided, overrides sym.code_context (which is typically None).
                         This allows Python to compute grep-style context from file content.

    Returns:
        Number of symbols inserted
    """
    if not symbols:
        return 0

    # Convert PySymbol objects to tuples
    symbol_data = []
    for sym in symbols:
        # Use computed code_context if available, otherwise fall back to extractor's value
        code_context = (
            code_context_map.get(sym.id) if code_context_map else None
        ) or sym.code_context

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
                code_context,
                sym.parent_id,
                None,  # metadata (TODO: serialize dict to JSON)
                None,  # file_hash
                0,  # last_indexed
                sym.semantic_group,
                sym.confidence,
                sym.content_type,
            )
        )

    conn.executemany(
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

    conn.commit()
    return len(symbol_data)


def add_identifiers_batch(conn: sqlite3.Connection, identifiers: list[Any]) -> int:
    """
    Bulk insert identifiers.

    Args:
        conn: SQLite connection
        identifiers: List of PyIdentifier objects from extraction

    Returns:
        Number of identifiers inserted
    """
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

    conn.executemany(
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

    conn.commit()
    return len(identifier_data)


def add_relationships_batch(conn: sqlite3.Connection, relationships: list[Any]) -> int:
    """
    Bulk insert relationships.

    Args:
        conn: SQLite connection
        relationships: List of PyRelationship objects from extraction

    Returns:
        Number of relationships inserted
    """
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

    conn.executemany(
        """
        INSERT OR REPLACE INTO relationships (
            id, from_symbol_id, to_symbol_id, kind, file_path,
            line_number, confidence, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        relationship_data,
    )

    conn.commit()
    return len(relationship_data)


def add_reachability_batch(
    conn: sqlite3.Connection,
    entries: list[tuple[str, str, int]],
) -> int:
    """
    Bulk insert reachability entries.

    Args:
        conn: SQLite connection
        entries: List of (source_id, target_id, min_distance) tuples

    Returns:
        Number of entries inserted
    """
    if not entries:
        return 0

    conn.executemany(
        "INSERT OR REPLACE INTO reachability (source_id, target_id, min_distance) VALUES (?, ?, ?)",
        entries,
    )
    conn.commit()
    return len(entries)


def clear_reachability(conn: sqlite3.Connection) -> None:
    """
    Clear all reachability data.

    Args:
        conn: SQLite connection
    """
    conn.execute("DELETE FROM reachability")
    conn.commit()


def clear_all(conn: sqlite3.Connection) -> None:
    """
    Clear all data from all tables (for force re-indexing).

    Deletes from tables in correct order to respect foreign key constraints,
    even though CASCADE should handle it. This is more explicit and safer.

    Args:
        conn: SQLite connection
    """
    # Delete in reverse dependency order (children before parents)
    conn.execute("DELETE FROM reachability")
    conn.execute("DELETE FROM relationships")
    conn.execute("DELETE FROM identifiers")
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM files")
    conn.commit()


def incremental_update_atomic(
    conn: sqlite3.Connection,
    files_to_clean: list[str],
    file_data: list[tuple],
    symbols: list,
    identifiers: list,
    relationships: list,
    code_context_map: Optional[dict[str, str]] = None,
) -> dict:
    """
    Perform atomic incremental update - delete old data and insert new in single transaction.

    OPTIMIZED: Uses executemany() for batch inserts instead of row-by-row operations.
    This is typically 10-100x faster for large batches.

    This mirrors Julie's incremental_update_atomic() pattern which prevents data corruption
    during incremental updates. If any step fails, the entire operation is rolled back.

    Args:
        conn: SQLite connection
        files_to_clean: List of file paths to delete (for re-indexing)
        file_data: List of (path, language, content, hash, size) tuples
        symbols: List of PySymbol objects to insert
        identifiers: List of PyIdentifier objects to insert
        relationships: List of PyRelationship objects to insert
        code_context_map: Optional dict mapping symbol_id to computed code_context
                         for grep-style search output

    Returns:
        Dict with counts: {files_cleaned, files_added, symbols_added, identifiers_added, relationships_added}

    Raises:
        StorageError: If atomic update fails (transaction is rolled back)
    """
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
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        # Step 1: Delete old data for files being re-indexed (batch delete)
        # CASCADE will handle symbols, identifiers, relationships
        if files_to_clean:
            cursor.executemany(
                "DELETE FROM files WHERE path = ?",
                [(path,) for path in files_to_clean]
            )
            counts["files_cleaned"] = len(files_to_clean)

        # Step 2: Batch insert new file records
        if file_data:
            file_tuples = [
                (_normalize_path(path), language, content, file_hash, size, timestamp, timestamp)
                for path, language, content, file_hash, size in file_data
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO files
                (path, language, content, hash, size, last_modified, last_indexed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                file_tuples,
            )
            counts["files_added"] = len(file_data)

        # Step 3: Batch insert symbols
        if symbols:
            symbol_tuples = []
            for sym in symbols:
                file_path = _normalize_path(sym.file_path)
                code_context = (
                    code_context_map.get(sym.id) if code_context_map else None
                ) or sym.code_context
                symbol_tuples.append((
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
                    code_context,
                ))
            cursor.executemany(
                """
                INSERT OR REPLACE INTO symbols
                (id, name, kind, signature, file_path, start_line, end_line, parent_id, language, doc_comment, code_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                symbol_tuples,
            )
            counts["symbols_added"] = len(symbols)

        # Step 4: Batch insert identifiers
        if identifiers:
            identifier_tuples = [
                (
                    ident.id,
                    ident.name,
                    ident.kind,
                    ident.language,
                    _normalize_path(ident.file_path),
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
                    timestamp,
                )
                for ident in identifiers
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO identifiers (
                    id, name, kind, language, file_path,
                    start_line, start_col, end_line, end_col,
                    start_byte, end_byte, containing_symbol_id, target_symbol_id,
                    confidence, code_context, last_indexed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                identifier_tuples,
            )
            counts["identifiers_added"] = len(identifiers)

        # Step 5: Batch insert relationships
        if relationships:
            relationship_tuples = [
                (
                    rel.id,
                    rel.from_symbol_id,
                    rel.to_symbol_id,
                    rel.kind,
                    _normalize_path(rel.file_path) if rel.file_path else None,
                    rel.line_number,
                )
                for rel in relationships
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO relationships
                (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                relationship_tuples,
            )
            counts["relationships_added"] = len(relationships)

        # Step 6: Commit entire transaction atomically
        conn.commit()

        return counts

    except Exception as e:
        # Rollback on any failure
        conn.rollback()
        raise StorageError(f"Atomic incremental update failed: {e}") from e
