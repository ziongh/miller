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
from ..workspace_paths import make_qualified_path


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


def clear_workspace(conn: sqlite3.Connection, workspace_id: str) -> dict:
    """
    Clear all data for a specific workspace.

    Used when removing a workspace from the unified database.
    Deletes all files, symbols, identifiers, and relationships
    belonging to the specified workspace.

    Args:
        conn: SQLite connection
        workspace_id: Workspace identifier to clear

    Returns:
        Dict with counts of deleted records
    """
    cursor = conn.cursor()
    counts = {}

    # Count before deletion for reporting
    cursor.execute("SELECT COUNT(*) FROM files WHERE workspace_id = ?", (workspace_id,))
    counts["files"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM symbols WHERE workspace_id = ?", (workspace_id,))
    counts["symbols"] = cursor.fetchone()[0]

    # Delete files - CASCADE will handle symbols, identifiers, relationships
    cursor.execute("DELETE FROM files WHERE workspace_id = ?", (workspace_id,))

    # Also clean up orphaned reachability entries
    # (reachability doesn't have FK constraints)
    cursor.execute("""
        DELETE FROM reachability
        WHERE source_id NOT IN (SELECT id FROM symbols)
        OR target_id NOT IN (SELECT id FROM symbols)
    """)

    conn.commit()
    return counts


def incremental_update_atomic(
    conn: sqlite3.Connection,
    files_to_clean: list[str],
    file_data: list[tuple],
    symbols: list,
    identifiers: list,
    relationships: list,
    code_context_map: Optional[dict[str, str]] = None,
    workspace_id: str = "primary",
) -> dict:
    """
    Perform atomic incremental update - delete old data and insert new in single transaction.

    OPTIMIZED: Uses executemany() for batch inserts instead of row-by-row operations.
    This is typically 10-100x faster for large batches.

    This mirrors Julie's incremental_update_atomic() pattern which prevents data corruption
    during incremental updates. If any step fails, the entire operation is rolled back.

    UNIFIED DATABASE: All data is stored in a single database with workspace_id column
    for filtering. File paths are qualified with workspace_id prefix for uniqueness.

    Args:
        conn: SQLite connection
        files_to_clean: List of file paths to delete (for re-indexing)
        file_data: List of (path, language, content, hash, size) tuples
        symbols: List of PySymbol objects to insert
        identifiers: List of PyIdentifier objects to insert
        relationships: List of PyRelationship objects to insert
        code_context_map: Optional dict mapping symbol_id to computed code_context
                         for grep-style search output
        workspace_id: Workspace identifier for this batch (default: "primary")

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
        # Start transaction with DEFERRED FK checking
        # This allows inserting symbols in any order - FK constraints are checked at COMMIT
        # Critical for self-referential symbols.parent_id where child may be processed before parent
        cursor = conn.cursor()
        cursor.execute("PRAGMA defer_foreign_keys = ON")
        cursor.execute("BEGIN IMMEDIATE")

        # Build set of valid symbol IDs (batch symbols + existing DB symbols)
        # This is needed to filter out cross-batch FK references
        batch_symbol_ids = {sym.id for sym in symbols} if symbols else set()

        # Query existing symbol IDs from database
        cursor.execute("SELECT id FROM symbols")
        existing_symbol_ids = {row[0] for row in cursor.fetchall()}

        # Combined valid IDs: what's in this batch OR already in DB
        valid_symbol_ids = batch_symbol_ids | existing_symbol_ids

        # Step 1: Delete old data for files being re-indexed (batch delete)
        # CASCADE will handle symbols, identifiers, relationships
        # NOTE: After deletion, remove those symbols from valid_symbol_ids
        if files_to_clean:
            # Qualify paths with workspace_id for queries and deletion
            qualified_paths = [
                make_qualified_path(workspace_id, path) for path in files_to_clean
            ]

            # Get symbol IDs that will be deleted (from files being cleaned)
            cursor.execute(
                f"SELECT id FROM symbols WHERE file_path IN ({','.join('?' * len(qualified_paths))})",
                qualified_paths
            )
            deleted_symbol_ids = {row[0] for row in cursor.fetchall()}
            # Remove deleted symbols from valid set (they won't exist after DELETE)
            valid_symbol_ids -= deleted_symbol_ids
            # Re-add batch symbols (they'll be inserted fresh)
            valid_symbol_ids |= batch_symbol_ids
            cursor.executemany(
                "DELETE FROM files WHERE path = ?",
                [(path,) for path in qualified_paths]
            )
            counts["files_cleaned"] = len(files_to_clean)

        # Step 2: Batch insert new file records
        # Paths are qualified with workspace_id for global uniqueness
        if file_data:
            file_tuples = [
                (
                    make_qualified_path(workspace_id, _normalize_path(path)),
                    workspace_id,
                    language,
                    content,
                    file_hash,
                    size,
                    timestamp,
                    timestamp,
                )
                for path, language, content, file_hash, size in file_data
            ]
            cursor.executemany(
                """
                INSERT OR REPLACE INTO files
                (path, workspace_id, language, content, hash, size, last_modified, last_indexed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                file_tuples,
            )
            counts["files_added"] = len(file_data)

        # Step 3: Batch insert symbols
        # IMPORTANT: Sort topologically (parents before children) to satisfy FK constraints
        # SQLite checks FKs row-by-row with IMMEDIATE mode, so child before parent fails
        if symbols:
            # Build parent -> children mapping for topological sort
            symbol_by_id = {sym.id: sym for sym in symbols}
            children_of = {}  # parent_id -> list of children
            roots = []  # symbols with no parent or parent not in batch

            for sym in symbols:
                parent_id = sym.parent_id
                if parent_id and parent_id in symbol_by_id:
                    children_of.setdefault(parent_id, []).append(sym)
                else:
                    roots.append(sym)

            # Topological sort: BFS from roots
            sorted_symbols = []
            queue = list(roots)
            while queue:
                sym = queue.pop(0)
                sorted_symbols.append(sym)
                # Add children to queue
                for child in children_of.get(sym.id, []):
                    queue.append(child)

            # Build tuples for insertion
            symbol_tuples = []
            for sym in sorted_symbols:
                # Qualify file_path with workspace_id to match files table
                file_path = make_qualified_path(
                    workspace_id, _normalize_path(sym.file_path)
                )
                code_context = (
                    code_context_map.get(sym.id) if code_context_map else None
                ) or sym.code_context
                # Set parent_id to NULL if parent doesn't exist in DB or batch
                parent_id = sym.parent_id
                if parent_id and parent_id not in valid_symbol_ids:
                    parent_id = None
                symbol_tuples.append((
                    sym.id,
                    workspace_id,
                    sym.name,
                    sym.kind,
                    sym.signature,
                    file_path,
                    sym.start_line,
                    sym.end_line,
                    parent_id,
                    sym.language,
                    sym.doc_comment,
                    code_context,
                ))
            cursor.executemany(
                """
                INSERT OR REPLACE INTO symbols
                (id, workspace_id, name, kind, signature, file_path, start_line, end_line, parent_id, language, doc_comment, code_context)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                symbol_tuples,
            )
            counts["symbols_added"] = len(symbols)

        # Step 4: Batch insert identifiers
        # Filter: containing_symbol_id must exist, target_symbol_id set to NULL if invalid
        if identifiers:
            identifier_tuples = []
            skipped_identifiers = 0
            for ident in identifiers:
                # containing_symbol_id is NOT NULL FK - must exist
                if ident.containing_symbol_id and ident.containing_symbol_id not in valid_symbol_ids:
                    skipped_identifiers += 1
                    continue

                # target_symbol_id is nullable FK - set to NULL if invalid
                target_id = ident.target_symbol_id
                if target_id and target_id not in valid_symbol_ids:
                    target_id = None

                # Qualify file_path with workspace_id
                file_path = make_qualified_path(
                    workspace_id, _normalize_path(ident.file_path)
                )
                identifier_tuples.append((
                    ident.id,
                    workspace_id,
                    ident.name,
                    ident.kind,
                    ident.language,
                    file_path,
                    ident.start_line,
                    ident.start_column,
                    ident.end_line,
                    ident.end_column,
                    ident.start_byte,
                    ident.end_byte,
                    ident.containing_symbol_id,
                    target_id,  # May be NULL if cross-batch reference
                    ident.confidence,
                    ident.code_context,
                    timestamp,
                ))
            if identifier_tuples:
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO identifiers (
                        id, workspace_id, name, kind, language, file_path,
                        start_line, start_col, end_line, end_col,
                        start_byte, end_byte, containing_symbol_id, target_symbol_id,
                        confidence, code_context, last_indexed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    identifier_tuples,
                )
            counts["identifiers_added"] = len(identifier_tuples)
            if skipped_identifiers > 0:
                counts["identifiers_skipped"] = skipped_identifiers

        # Step 5: Batch insert relationships
        # Filter: both from_symbol_id and to_symbol_id must exist (NOT NULL FKs)
        if relationships:
            relationship_tuples = []
            skipped_relationships = 0
            for rel in relationships:
                # Both FKs are NOT NULL - skip if either doesn't exist
                if rel.from_symbol_id not in valid_symbol_ids:
                    skipped_relationships += 1
                    continue
                if rel.to_symbol_id not in valid_symbol_ids:
                    skipped_relationships += 1
                    continue

                # Qualify file_path with workspace_id if present
                file_path = None
                if rel.file_path:
                    file_path = make_qualified_path(
                        workspace_id, _normalize_path(rel.file_path)
                    )

                relationship_tuples.append((
                    rel.id,
                    workspace_id,
                    rel.from_symbol_id,
                    rel.to_symbol_id,
                    rel.kind,
                    file_path,
                    rel.line_number,
                ))
            if relationship_tuples:
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO relationships
                    (id, workspace_id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    relationship_tuples,
                )
            counts["relationships_added"] = len(relationship_tuples)
            if skipped_relationships > 0:
                counts["relationships_skipped"] = skipped_relationships

        # Step 6: Commit entire transaction atomically
        # FK constraints are checked here (deferred mode)
        conn.commit()

        # Reset defer mode for future transactions
        cursor.execute("PRAGMA defer_foreign_keys = OFF")

        return counts

    except Exception as e:
        # Rollback on any failure
        conn.rollback()
        # Reset defer mode even on failure
        try:
            conn.execute("PRAGMA defer_foreign_keys = OFF")
        except Exception:
            pass  # Ignore if connection is broken
        raise StorageError(f"Atomic incremental update failed: {e}") from e


def update_reference_counts(conn: sqlite3.Connection) -> int:
    """
    Bulk update reference_count for all symbols based on incoming relationships.

    This counts how many times each symbol is referenced (to_symbol_id in relationships).
    A higher count indicates more "important" symbols (frequently used).

    The count includes:
    - Direct calls (function calls, method invocations)
    - Type references (class instantiation, inheritance)
    - Variable usage (field access, parameter passing)

    Used for "importance weighting" in search - frequently referenced symbols
    are boosted in rankings.

    Args:
        conn: SQLite connection

    Returns:
        Number of symbols updated
    """
    # First, reset all counts to 0
    conn.execute("UPDATE symbols SET reference_count = 0")

    # Then update with actual counts from relationships table
    # This counts incoming edges (how many symbols reference this one)
    cursor = conn.execute("""
        UPDATE symbols
        SET reference_count = (
            SELECT COUNT(*)
            FROM relationships
            WHERE relationships.to_symbol_id = symbols.id
        )
        WHERE EXISTS (
            SELECT 1 FROM relationships WHERE relationships.to_symbol_id = symbols.id
        )
    """)

    conn.commit()
    return cursor.rowcount
