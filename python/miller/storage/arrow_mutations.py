"""
Arrow-based SQLite mutations for zero-copy indexing.

These functions extract data from PyArrow Tables and insert into SQLite.
While not truly zero-copy (SQLite doesn't support Arrow), this eliminates
the overhead of creating Python objects for each symbol/identifier/relationship.

Key optimization: Instead of iterating PySymbol objects (each field access = allocation),
we extract entire columns as lists and zip them together.
"""

import sqlite3
import time
from typing import Optional

import pyarrow as pa

from .schema import _normalize_path


def add_symbols_from_arrow(
    conn: sqlite3.Connection,
    symbols_table: pa.Table,
    code_context_map: Optional[dict[str, str]] = None,
    workspace_id: str = "primary",
) -> int:
    """
    Bulk insert symbols from Arrow table.

    This is more efficient than add_symbols_batch because:
    1. Column extraction is O(1) per column, not O(n) field accesses
    2. No Python object creation for each symbol
    3. Memory is contiguous (cache-friendly)

    Args:
        conn: SQLite connection
        symbols_table: PyArrow Table with symbol columns
        code_context_map: Optional dict mapping symbol_id to computed code_context
        workspace_id: Workspace identifier for multi-workspace support

    Returns:
        Number of symbols inserted
    """
    from ..workspace_paths import make_qualified_path

    if symbols_table.num_rows == 0:
        return 0

    # Extract columns as Python lists (single allocation per column)
    ids = symbols_table.column("id").to_pylist()
    names = symbols_table.column("name").to_pylist()
    kinds = symbols_table.column("kind").to_pylist()
    languages = symbols_table.column("language").to_pylist()
    file_paths = symbols_table.column("file_path").to_pylist()
    start_lines = symbols_table.column("start_line").to_pylist()
    end_lines = symbols_table.column("end_line").to_pylist()
    signatures = symbols_table.column("signature").to_pylist()
    doc_comments = symbols_table.column("doc_comment").to_pylist()
    parent_ids = symbols_table.column("parent_id").to_pylist()
    code_contexts = symbols_table.column("code_context").to_pylist()

    # Build tuples for executemany
    # Use defaults for columns not in Arrow schema (byte positions, visibility, etc.)
    symbol_data = []
    for i in range(symbols_table.num_rows):
        # Use computed code_context if available
        code_context = (
            code_context_map.get(ids[i]) if code_context_map else None
        ) or code_contexts[i]

        # Qualify file_path with workspace_id for multi-workspace support
        qualified_path = make_qualified_path(workspace_id, _normalize_path(file_paths[i]))

        symbol_data.append((
            ids[i],
            workspace_id,
            names[i],
            kinds[i],
            languages[i],
            qualified_path,
            signatures[i],
            start_lines[i],
            0,  # start_col (default)
            end_lines[i],
            0,  # end_col (default)
            0,  # start_byte (default)
            0,  # end_byte (default)
            doc_comments[i],
            None,  # visibility (default)
            code_context,
            parent_ids[i],
            None,  # metadata
            None,  # file_hash
            0,  # last_indexed
            None,  # semantic_group
            1.0,  # confidence (default to high)
            None,  # content_type
        ))

    conn.executemany(
        """
        INSERT OR REPLACE INTO symbols (
            id, workspace_id, name, kind, language, file_path,
            signature, start_line, start_col, end_line, end_col,
            start_byte, end_byte, doc_comment, visibility, code_context,
            parent_id, metadata, file_hash, last_indexed,
            semantic_group, confidence, content_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        symbol_data,
    )

    conn.commit()
    return len(symbol_data)


def add_identifiers_from_arrow(
    conn: sqlite3.Connection,
    identifiers_table: pa.Table,
    workspace_id: str = "primary",
) -> int:
    """
    Bulk insert identifiers from Arrow table.

    Args:
        conn: SQLite connection
        identifiers_table: PyArrow Table with identifier columns
        workspace_id: Workspace identifier for multi-workspace support

    Returns:
        Number of identifiers inserted
    """
    from ..workspace_paths import make_qualified_path

    if identifiers_table.num_rows == 0:
        return 0

    # Extract columns
    ids = identifiers_table.column("id").to_pylist()
    names = identifiers_table.column("name").to_pylist()
    kinds = identifiers_table.column("kind").to_pylist()
    languages = identifiers_table.column("language").to_pylist()
    file_paths = identifiers_table.column("file_path").to_pylist()
    start_lines = identifiers_table.column("start_line").to_pylist()
    start_columns = identifiers_table.column("start_column").to_pylist()
    end_lines = identifiers_table.column("end_line").to_pylist()
    end_columns = identifiers_table.column("end_column").to_pylist()
    start_bytes = identifiers_table.column("start_byte").to_pylist()
    end_bytes = identifiers_table.column("end_byte").to_pylist()
    containing_ids = identifiers_table.column("containing_symbol_id").to_pylist()
    target_ids = identifiers_table.column("target_symbol_id").to_pylist()
    confidences = identifiers_table.column("confidence").to_pylist()
    code_contexts = identifiers_table.column("code_context").to_pylist()

    # Build tuples with qualified file paths
    identifier_data = [
        (
            ids[i],
            workspace_id,
            names[i],
            kinds[i],
            languages[i],
            make_qualified_path(workspace_id, _normalize_path(file_paths[i])),
            start_lines[i],
            start_columns[i],
            end_lines[i],
            end_columns[i],
            start_bytes[i],
            end_bytes[i],
            containing_ids[i],
            target_ids[i],
            confidences[i],
            code_contexts[i],
            0,  # last_indexed
        )
        for i in range(identifiers_table.num_rows)
    ]

    conn.executemany(
        """
        INSERT OR REPLACE INTO identifiers (
            id, workspace_id, name, kind, language, file_path,
            start_line, start_col, end_line, end_col,
            start_byte, end_byte, containing_symbol_id, target_symbol_id,
            confidence, code_context, last_indexed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        identifier_data,
    )

    conn.commit()
    return len(identifier_data)


def add_relationships_from_arrow(
    conn: sqlite3.Connection,
    relationships_table: pa.Table,
    workspace_id: str = "primary",
) -> int:
    """
    Bulk insert relationships from Arrow table.

    Args:
        conn: SQLite connection
        relationships_table: PyArrow Table with relationship columns
        workspace_id: Workspace identifier for multi-workspace support

    Returns:
        Number of relationships inserted
    """
    from ..workspace_paths import make_qualified_path

    if relationships_table.num_rows == 0:
        return 0

    # Extract columns
    ids = relationships_table.column("id").to_pylist()
    from_ids = relationships_table.column("from_symbol_id").to_pylist()
    to_ids = relationships_table.column("to_symbol_id").to_pylist()
    kinds = relationships_table.column("kind").to_pylist()
    file_paths = relationships_table.column("file_path").to_pylist()
    line_numbers = relationships_table.column("line_number").to_pylist()
    confidences = relationships_table.column("confidence").to_pylist()

    # Build tuples with qualified file paths
    relationship_data = [
        (
            ids[i],
            workspace_id,
            from_ids[i],
            to_ids[i],
            kinds[i],
            make_qualified_path(workspace_id, _normalize_path(file_paths[i])) if file_paths[i] else None,
            line_numbers[i],
            confidences[i],
            None,  # metadata
            0,  # created_at
        )
        for i in range(relationships_table.num_rows)
    ]

    conn.executemany(
        """
        INSERT OR REPLACE INTO relationships (
            id, workspace_id, from_symbol_id, to_symbol_id, kind,
            file_path, line_number, confidence, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        relationship_data,
    )

    conn.commit()
    return len(relationship_data)


def add_files_from_arrow(
    conn: sqlite3.Connection,
    files_table: pa.Table,
    workspace_id: str = "primary",
) -> int:
    """
    Bulk insert file records from Arrow table.

    Args:
        conn: SQLite connection
        files_table: PyArrow Table with file columns
        workspace_id: Workspace identifier for multi-workspace support

    Returns:
        Number of files inserted
    """
    from ..workspace_paths import make_qualified_path

    if files_table.num_rows == 0:
        return 0

    timestamp = int(time.time())

    # Extract columns
    paths = files_table.column("path").to_pylist()
    languages = files_table.column("language").to_pylist()
    contents = files_table.column("content").to_pylist()
    hashes = files_table.column("hash").to_pylist()
    sizes = files_table.column("size").to_pylist()

    # Build tuples with qualified paths
    file_data = [
        (
            make_qualified_path(workspace_id, _normalize_path(paths[i])),
            workspace_id,
            languages[i],
            contents[i],
            hashes[i],
            sizes[i],
            timestamp,
            timestamp,
        )
        for i in range(files_table.num_rows)
    ]

    conn.executemany(
        """
        INSERT OR REPLACE INTO files (
            path, workspace_id, language, content, hash, size, last_modified, last_indexed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        file_data,
    )

    conn.commit()
    return len(file_data)
