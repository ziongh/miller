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
from typing import Any

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


def add_symbols_batch(conn: sqlite3.Connection, symbols: list[Any]) -> int:
    """
    Bulk insert symbols.

    Args:
        conn: SQLite connection
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


def incremental_update_atomic(
    conn: sqlite3.Connection,
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
        conn: SQLite connection
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
        conn.commit()

        return counts

    except Exception as e:
        # Rollback on any failure
        conn.rollback()
        raise StorageError(f"Atomic incremental update failed: {e}") from e
