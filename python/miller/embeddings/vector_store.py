"""
LanceDB vector storage and search.

Manages vector storage, FTS indexing, and multi-method search (text, pattern, semantic, hybrid).
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import lancedb
import numpy as np
import pyarrow as pa

from miller.embeddings.search import SearchMethod, detect_search_method
from miller.embeddings.fts_index import create_fts_index
from miller.embeddings.search_methods import (
    search_pattern,
    search_text,
    search_semantic,
    search_hybrid,
)
from miller.embeddings.search_enhancements import apply_search_enhancements

if TYPE_CHECKING:
    from miller.embeddings.manager import EmbeddingManager

logger = logging.getLogger("miller.vector_store")


class VectorStore:
    """
    Manages LanceDB vector storage and search.

    Features:
    - Text search (keyword matching)
    - Semantic search (vector similarity)
    - Hybrid search (combines both)
    - Metadata storage (symbol fields)
    """

    # Explicit PyArrow schema with nullable fields for optional symbol attributes
    SCHEMA = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("name", pa.string(), nullable=False),
            pa.field("kind", pa.string(), nullable=False),
            pa.field("language", pa.string(), nullable=False),
            pa.field("file_path", pa.string(), nullable=False),
            pa.field("signature", pa.string(), nullable=True),  # Optional
            pa.field("doc_comment", pa.string(), nullable=True),  # Optional
            pa.field("start_line", pa.int32(), nullable=True),  # Optional
            pa.field("end_line", pa.int32(), nullable=True),  # Optional
            pa.field(
                "code_pattern", pa.string(), nullable=False
            ),  # Pattern-preserving content for code idiom search
            pa.field("vector", pa.list_(pa.float32(), 384), nullable=False),  # 384-dim embeddings
        ]
    )

    def __init__(
        self,
        db_path: str = ".miller/indexes/vectors.lance",
        embeddings: Optional["EmbeddingManager"] = None,
    ):
        """
        Initialize LanceDB connection.

        Args:
            db_path: Path to LanceDB database
                    (use ":memory:" for temp directory in tests)
            embeddings: Optional EmbeddingManager for semantic search
                       (if None, will create on-demand but less efficient)
        """
        self.db_path = db_path
        self._embeddings = embeddings

        # Handle :memory: by creating temp directory
        if db_path == ":memory:":
            self._temp_dir = tempfile.mkdtemp(prefix="miller_test_")
            actual_path = self._temp_dir
        else:
            self._temp_dir = None
            actual_path = db_path
            # Create parent directory if needed
            Path(actual_path).parent.mkdir(parents=True, exist_ok=True)

        # Connect to LanceDB
        self.db = lancedb.connect(actual_path)

        # Load existing table or create on first add_symbols
        self.table_name = "symbols"
        self._fts_index_created = False
        self._pattern_index_created = False  # Separate flag for pattern index
        try:
            self._table = self.db.open_table(self.table_name)
            logger.debug(f"Opened existing LanceDB table '{self.table_name}'")
            # If table exists, try to create FTS indexes
            self._create_fts_index()
        except Exception:
            # Table doesn't exist yet, will be created on first add_symbols
            logger.debug(f"LanceDB table '{self.table_name}' not found, will create on first add")
            self._table = None

    def _create_fts_index(self, max_retries: int = 3):
        """Create FTS index using helper function from fts_index module."""
        fts_created, pattern_created = create_fts_index(self._table, max_retries)
        self._fts_index_created = fts_created
        self._pattern_index_created = pattern_created

    def clear_all(self) -> None:
        """
        Clear all vectors from the store (for force re-indexing).

        Drops and recreates the table to ensure a clean slate.
        """
        try:
            self.db.drop_table(self.table_name)
            logger.info(f"Dropped LanceDB table '{self.table_name}'")
        except Exception:
            # Table might not exist
            pass
        self._table = None
        self._fts_index_created = False
        self._pattern_index_created = False

    def add_symbols(self, symbols: list[Any], vectors: np.ndarray) -> int:
        """
        Add symbols with their embeddings to LanceDB.

        Args:
            symbols: List of PySymbol objects
            vectors: Embedding vectors (N x 384)

        Returns:
            Number of symbols added
        """
        if not symbols:
            return 0

        # Build data for LanceDB
        data = []
        for sym, vec in zip(symbols, vectors):
            # Build pattern-preserving content for code idiom search
            # Combines signature + name + kind to enable searches like ": BaseClass", "ILogger<", "[Fact]"
            pattern_parts = []
            if hasattr(sym, "signature") and sym.signature:
                pattern_parts.append(sym.signature)
            pattern_parts.append(sym.name)
            if sym.kind:
                pattern_parts.append(sym.kind)

            code_pattern = " ".join(pattern_parts)

            data.append(
                {
                    "id": sym.id,
                    "name": sym.name,
                    "kind": sym.kind,
                    "language": sym.language,
                    "file_path": sym.file_path,
                    "signature": sym.signature if hasattr(sym, "signature") else None,
                    "doc_comment": sym.doc_comment if hasattr(sym, "doc_comment") else None,
                    "start_line": sym.start_line if hasattr(sym, "start_line") else 0,
                    "end_line": sym.end_line if hasattr(sym, "end_line") else 0,
                    "code_pattern": code_pattern,  # NEW: Pattern-preserving field
                    "vector": vec.tolist(),  # LanceDB stores as list
                }
            )

        # Create or append to table
        if self._table is None:
            # First time: create table with explicit schema to handle nullable fields
            table = pa.Table.from_pylist(data, schema=self.SCHEMA)
            self._table = self.db.create_table(self.table_name, table, mode="overwrite")
            # Create FTS index after table creation
            self._create_fts_index()
        else:
            # Subsequent times: append (schema already defined)
            self._table.add(data)

        return len(data)

    def search(self, query: str, method: SearchMethod = "auto", limit: int = 50) -> list[dict]:
        """
        Search symbols with auto-detection and method routing.

        Args:
            query: Search query (code patterns, keywords, or natural language)
            method: Search method (auto/text/pattern/semantic/hybrid)
                   - auto: Auto-detect based on query (default, recommended)
                   - text: Full-text search with stemming
                   - pattern: Code idioms (: < > [ ] preserved)
                   - semantic: Vector similarity
                   - hybrid: Combines text + semantic
            limit: Maximum results

        Returns:
            List of dicts with symbol metadata + score (0.0-1.0)

        Examples:
            >>> # Auto-detection (recommended)
            >>> search("authentication logic")  # Auto → hybrid
            >>> search(": BaseClass")           # Auto → pattern
            >>> search("ILogger<")              # Auto → pattern

            >>> # Manual override
            >>> search("map<int>", method="text")     # Force text
            >>> search("user auth", method="semantic") # Force semantic
        """
        if self._table is None:
            return []

        # Boundary conditions
        if not query or limit <= 0:
            return []

        # Clamp limit to prevent memory issues
        limit = min(limit, 1000)

        # Auto-detect if method is "auto"
        if method == "auto":
            method = detect_search_method(query)

        # Route to appropriate search method
        if method == "pattern":
            return search_pattern(self._table, self._pattern_index_created, query, limit)
        elif method == "text":
            # OPTIMIZATION: Route text search to hybrid instead of whitespace-FTS
            # Reason: Our FTS index uses whitespace tokenizer (for pattern search),
            # which can't do stemming/prefix matching. Hybrid search (semantic + FTS)
            # provides much better text search quality.
            # Users should use "pattern" for code idioms, "text"/"auto"/"hybrid" for general search.
            return search_hybrid(
                self._table,
                self._fts_index_created,
                self._embeddings,
                query,
                limit,
                self._apply_search_enhancements,
            )
        elif method == "semantic":
            return search_semantic(self._table, self._embeddings, query, limit)
        else:  # hybrid
            return search_hybrid(
                self._table,
                self._fts_index_created,
                self._embeddings,
                query,
                limit,
                self._apply_search_enhancements,
            )

    def _apply_search_enhancements(self, results: list[dict], query: str, method: str) -> list[dict]:
        """
        Apply all search quality enhancements to results.

        Enhancements applied:
        1. Field match boosting (name > signature > doc)
        2. Match position boosting (exact > prefix > suffix)
        3. Symbol kind weighting (functions/classes > variables)
        4. Quality filtering (remove low scores)
        5. Re-sort by enhanced scores

        Args:
            results: Raw search results from FTS/vector search
            query: Original search query
            method: Search method used

        Returns:
            Enhanced and re-ranked results
        """
        return apply_search_enhancements(results, query, method)

    # Backwards compatibility wrappers for tests that call internal methods directly
    def _search_pattern(self, query: str, limit: int) -> list[dict]:
        """Pattern search wrapper for backwards compatibility."""
        return search_pattern(self._table, self._pattern_index_created, query, limit)

    def _search_text(self, query: str, limit: int) -> list[dict]:
        """Text search wrapper for backwards compatibility."""
        from miller.embeddings.search_methods import search_text_fallback
        return search_text_fallback(self._table, query, limit)

    def _search_semantic(self, query: str, limit: int) -> list[dict]:
        """Semantic search wrapper for backwards compatibility."""
        return search_semantic(self._table, self._embeddings, query, limit)

    def _search_hybrid(self, query: str, limit: int) -> list[dict]:
        """Hybrid search wrapper for backwards compatibility."""
        return search_hybrid(
            self._table,
            self._fts_index_created,
            self._embeddings,
            query,
            limit,
            self._apply_search_enhancements,
        )

    def update_file_symbols(
        self, file_path: str, symbols: list[Any], vectors: np.ndarray, rebuild_index: bool = True
    ) -> int:
        """
        Update symbols for a file (remove old, add new).

        Args:
            file_path: File path to update
            symbols: New symbols
            vectors: New embeddings
            rebuild_index: Whether to rebuild FTS index after update (default: True)
                          Set to False during batch operations, then call rebuild_fts_index() once at end

        Returns:
            Number of symbols updated
        """
        if self._table is None:
            # No existing data, just add
            return self.add_symbols(symbols, vectors)

        # Delete old symbols for this file
        # Escape single quotes for SQL (e.g., kid's_file.py -> kid''s_file.py)
        escaped_path = file_path.replace("'", "''")
        self._table.delete(f"file_path = '{escaped_path}'")

        # Add new symbols
        count = self.add_symbols(symbols, vectors)

        # Rebuild FTS index after updating symbols (unless deferred)
        # (LanceDB's Tantivy index needs to be recreated after deletions)
        if rebuild_index and self._fts_index_created:
            self._create_fts_index()

        return count

    def rebuild_fts_index(self):
        """
        Rebuild the FTS index.

        Call this after batch operations where rebuild_index=False was used.
        Always attempts rebuild regardless of previous state - this allows
        recovery from failed index creation.
        """
        if self._table is None:
            logger.debug("Cannot rebuild FTS index: no table exists")
            return
        logger.debug("Rebuilding FTS index...")
        self._create_fts_index()
        if self._fts_index_created:
            logger.info("FTS index rebuilt successfully")
        else:
            logger.warning("FTS index rebuild failed - text search may be degraded")

    def delete_files_batch(self, file_paths: list[str]) -> int:
        """
        Delete all vectors for a batch of files.

        Use this before add_symbols when updating files to prevent stale vectors.

        Args:
            file_paths: List of file paths to delete vectors for

        Returns:
            Number of files processed (not individual vectors deleted)
        """
        if self._table is None or not file_paths:
            return 0

        # Build OR condition for all file paths
        # LanceDB delete uses SQL-like WHERE syntax
        # Escape single quotes for SQL (e.g., kid's_file.py -> kid''s_file.py)
        escaped_paths = [fp.replace("'", "''") for fp in file_paths]
        conditions = " OR ".join(f"file_path = '{fp}'" for fp in escaped_paths)
        self._table.delete(conditions)

        return len(file_paths)

    def close(self):
        """Close database and cleanup temp directories."""
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def __del__(self):
        """Destructor to ensure cleanup if close() was not called."""
        self.close()

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.close()
