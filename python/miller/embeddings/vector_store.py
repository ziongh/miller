"""
LanceDB vector storage and search.

Manages vector storage, FTS indexing, and multi-method search (text, pattern, semantic, hybrid).
"""

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import lancedb
import numpy as np
import pyarrow as pa

from miller.embeddings.search import SearchMethod, detect_search_method, detect_search_intent
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
    from miller.storage import StorageManager

logger = logging.getLogger("miller.vector_store")


class VectorStore:
    """
    Manages LanceDB vector storage and search.

    Features:
    - Text search (keyword matching)
    - Semantic search (vector similarity)
    - Hybrid search (combines both)
    - Metadata storage (symbol fields)
    - Auto-migration when embedding model changes (dimension mismatch detection)
    - Matryoshka Representation Learning (MRL) for fast search + re-ranking
    """

    # Default dimension for schema (Jina-0.5B = 896, BGE-Small = 384)
    DEFAULT_DIMENSION = 896

    # Matryoshka short vector dimension for fast indexing
    # Jina-0.5B embeddings are MRL-compatible: first 64 dims capture most semantics
    # This reduces index size by ~90% while maintaining accuracy via re-ranking
    MRL_SHORT_DIM = 64

    def __init__(
        self,
        db_path: str = ".miller/indexes/vectors.lance",
        embeddings: Optional["EmbeddingManager"] = None,
        expected_dim: int = None,
        storage: Optional["StorageManager"] = None,
        use_mrl: bool = True,
    ):
        """
        Initialize LanceDB connection.

        Args:
            db_path: Path to LanceDB database
                    (use ":memory:" for temp directory in tests)
            embeddings: Optional EmbeddingManager for semantic search
                       (if None, will create on-demand but less efficient)
            expected_dim: Expected vector dimension from EmbeddingManager
                         If None, uses DEFAULT_DIMENSION (896 for Jina)
            storage: Optional StorageManager for coordinating SQLite cache invalidation.
                    When provided, VectorStore will clear SQLite's files table on reset
                    to prevent the "migration death spiral" bug where SQLite thinks files
                    are indexed but the vector store is empty.
            use_mrl: Enable Matryoshka Representation Learning for search (default: True).
                    When True: Uses 64D short_vector for fast candidate retrieval,
                              then re-ranks with full vector for accuracy (~10x faster).
                    When False: Uses full vector directly (slightly more accurate
                               but slower for large datasets).
                    Can also be configured via MILLER_USE_MRL environment variable
                    (set to "0" or "false" to disable).
        """
        self.db_path = db_path
        self._embeddings = embeddings
        self._storage = storage

        # MRL config: explicit param > env var > default (True)
        if use_mrl is True:  # Only check env if using default
            env_mrl = os.getenv("MILLER_USE_MRL", "").lower()
            if env_mrl in ("0", "false", "no", "off"):
                use_mrl = False
                logger.info("MRL disabled via MILLER_USE_MRL environment variable")
        self.use_mrl = use_mrl

        # Determine expected dimension: explicit param > embeddings > default
        if expected_dim is not None:
            self.expected_dim = expected_dim
        elif embeddings is not None and hasattr(embeddings, 'dimensions'):
            self.expected_dim = embeddings.dimensions
        else:
            self.expected_dim = self.DEFAULT_DIMENSION

        # Build schema dynamically based on expected dimension
        # This allows switching between Jina (896D) and BGE (384D)
        # Includes MRL short_vector for fast indexing + re-ranking
        # UNIFIED DATABASE: workspace_id is included for cross-workspace filtering
        self.SCHEMA = pa.schema(
            [
                pa.field("id", pa.string(), nullable=False),
                pa.field("workspace_id", pa.string(), nullable=False),  # For cross-workspace filtering
                pa.field("name", pa.string(), nullable=False),
                pa.field("kind", pa.string(), nullable=False),
                pa.field("language", pa.string(), nullable=False),
                pa.field("file_path", pa.string(), nullable=False),
                pa.field("signature", pa.string(), nullable=True),
                pa.field("doc_comment", pa.string(), nullable=True),
                pa.field("start_line", pa.int32(), nullable=True),
                pa.field("end_line", pa.int32(), nullable=True),
                pa.field("code_pattern", pa.string(), nullable=False),
                pa.field("content", pa.string(), nullable=True),
                # Full vector for re-ranking (896D for Jina-0.5B)
                pa.field("vector", pa.list_(pa.float32(), self.expected_dim), nullable=False),
                # MRL short vector for fast index search (64D)
                pa.field("short_vector", pa.list_(pa.float32(), self.MRL_SHORT_DIM), nullable=False),
            ]
        )

        # Track if we had to reset data (for migration death spiral prevention)
        self.was_reset = False

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

            # AUTO-MIGRATION: Detect schema changes that require re-indexing
            # 1. Dimension mismatch (e.g., BGE 384 → Jina 896)
            # 2. Missing short_vector column (MRL upgrade)
            try:
                current_dim = self._table.schema.field("vector").type.list_size
                has_short_vector = "short_vector" in self._table.schema.names

                needs_migration = False
                migration_reason = ""

                if current_dim != self.expected_dim:
                    needs_migration = True
                    migration_reason = f"vector dimension mismatch: {current_dim} → {self.expected_dim}"
                elif not has_short_vector:
                    needs_migration = True
                    migration_reason = "missing short_vector column (MRL upgrade)"

                if needs_migration:
                    logger.warning(
                        f"📉 Schema migration needed: {migration_reason}. "
                        f"Dropping table for upgrade."
                    )
                    self.db.drop_table(self.table_name)
                    self._table = None
                    self.was_reset = True  # Signal that we wiped data
                    # CRITICAL: Clear SQLite files table to prevent "migration death spiral"
                    # Without this, SQLite thinks files are indexed (has last_indexed timestamps)
                    # but vector store is empty. Scanner sees "already indexed" and skips,
                    # leaving search completely broken.
                    self._invalidate_sqlite_cache()
                else:
                    # Schema matches, create FTS indexes
                    self._create_fts_index()
            except Exception as e:
                logger.debug(f"Could not check schema: {e}")
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

    def _invalidate_sqlite_cache(self) -> None:
        """
        Clear SQLite files table to force full re-indexing.

        This is CRITICAL for preventing the "migration death spiral" bug:
        1. Vector store is reset (dimension change, manual clear, etc.)
        2. SQLite still has files with last_indexed timestamps
        3. Scanner checks SQLite: "File X was indexed at time T, hash matches"
        4. Scanner SKIPS re-indexing (thinks file is up-to-date)
        5. Result: Empty vector store, search returns nothing

        By clearing the SQLite files table, we force the scanner to treat
        all files as "new" and re-index them into the fresh vector store.

        Note: Only clears if storage was provided to VectorStore. If not,
        the was_reset flag is still set for external code to handle.
        """
        if self._storage is None:
            logger.warning(
                "⚠️ Vector store reset but no StorageManager provided. "
                "SQLite files table NOT cleared - caller must check was_reset flag!"
            )
            return

        try:
            logger.warning(
                "♻️ Clearing SQLite files table to force full re-index after vector store reset"
            )
            self._storage.conn.execute("DELETE FROM files")
            self._storage.conn.commit()
            logger.info("✅ SQLite files table cleared - scanner will re-index all files")
        except Exception as e:
            logger.error(f"❌ Failed to clear SQLite files table: {e}")

    def clear_all(self) -> None:
        """
        Clear all vectors from the store (for force re-indexing).

        Drops and recreates the table to ensure a clean slate.
        Also invalidates SQLite cache to prevent the "migration death spiral" bug.
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
        self.was_reset = True  # Signal that we wiped data
        # Clear SQLite to prevent scanner from skipping re-indexing
        self._invalidate_sqlite_cache()

    def add_symbols(
        self,
        symbols: list[Any],
        vectors: np.ndarray,
        workspace_id: str = "primary",
    ) -> int:
        """
        Add symbols with their embeddings to LanceDB.

        Args:
            symbols: List of PySymbol objects
            vectors: Embedding vectors (N x dimensions)
            workspace_id: Workspace identifier for this batch (default: "primary")

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
                    "workspace_id": workspace_id,
                    "name": sym.name,
                    "kind": sym.kind,
                    "language": sym.language,
                    "file_path": sym.file_path,
                    "signature": sym.signature if hasattr(sym, "signature") else None,
                    "doc_comment": sym.doc_comment if hasattr(sym, "doc_comment") else None,
                    "start_line": sym.start_line if hasattr(sym, "start_line") else 0,
                    "end_line": sym.end_line if hasattr(sym, "end_line") else 0,
                    "code_pattern": code_pattern,
                    "content": getattr(sym, "content", None),  # File content for file-level entries
                    "vector": vec.tolist(),  # Full vector for re-ranking
                    "short_vector": vec[:self.MRL_SHORT_DIM].tolist(),  # MRL short vector for fast indexing
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

    def add_symbols_arrow(
        self,
        symbols_table: pa.Table,
        vectors: np.ndarray,
        workspace_id: str = "primary",
    ) -> int:
        """
        Add symbols from Arrow table with embeddings (zero-copy path).

        This avoids creating Python dicts for each symbol - the Arrow table
        from Rust is augmented with vectors and passed directly to LanceDB.

        Args:
            symbols_table: PyArrow Table from ArrowIndexingBuffer.get_symbols_table()
            vectors: Embedding vectors (N x dimensions)
            workspace_id: Workspace identifier for this batch (default: "primary")

        Returns:
            Number of symbols added
        """
        if symbols_table.num_rows == 0:
            return 0

        # Build code_pattern column from existing columns
        names = symbols_table.column("name").to_pylist()
        kinds = symbols_table.column("kind").to_pylist()
        signatures = symbols_table.column("signature").to_pylist()
        patterns = [
            " ".join(filter(None, [sig, name, kind]))
            for sig, name, kind in zip(signatures, names, kinds)
        ]

        # Build short vectors (first MRL_SHORT_DIM dimensions)
        short_vectors = vectors[:, :self.MRL_SHORT_DIM]

        # Build the final table with required columns for LanceDB schema
        # Remove columns not in LanceDB schema, add vectors and code_pattern
        # Create workspace_id column (same value for all rows in batch)
        workspace_ids = pa.array([workspace_id] * symbols_table.num_rows)

        table = pa.table({
            "id": symbols_table.column("id"),
            "workspace_id": workspace_ids,
            "name": symbols_table.column("name"),
            "kind": symbols_table.column("kind"),
            "language": symbols_table.column("language"),
            "file_path": symbols_table.column("file_path"),
            "signature": symbols_table.column("signature"),
            "doc_comment": symbols_table.column("doc_comment"),
            "start_line": symbols_table.column("start_line"),
            "end_line": symbols_table.column("end_line"),
            "code_pattern": pa.array(patterns),
            "content": pa.nulls(symbols_table.num_rows, type=pa.string()),
            # Full vector for re-ranking
            "vector": pa.FixedSizeListArray.from_arrays(
                pa.array(vectors.flatten(), type=pa.float32()),
                self.expected_dim
            ),
            # MRL short vector for fast index search
            "short_vector": pa.FixedSizeListArray.from_arrays(
                pa.array(short_vectors.flatten(), type=pa.float32()),
                self.MRL_SHORT_DIM
            ),
        }, schema=self.SCHEMA)

        # Create or append to LanceDB table
        if self._table is None:
            self._table = self.db.create_table(self.table_name, table, mode="overwrite")
            self._create_fts_index()
        else:
            self._table.add(table)

        return symbols_table.num_rows

    def search(
        self,
        query: str,
        method: SearchMethod = "auto",
        limit: int = 50,
        kind_filter: Optional[list[str]] = None,
        auto_detect_intent: bool = True,
        use_mrl: Optional[bool] = None,
    ) -> list[dict]:
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
            kind_filter: Optional list of symbol kinds to filter by.
                        When provided, only symbols of these kinds are returned.
                        Example: ["class", "struct", "interface"] for definitions
            auto_detect_intent: If True and kind_filter is None, automatically
                               detect intent from query to apply appropriate filter.
                               Example: "how is User defined?" → filter to definition kinds
            use_mrl: Override MRL (Matryoshka Representation Learning) setting for this search.
                    - None: Use instance default (self.use_mrl)
                    - True: Force MRL enabled (fast short-vector + re-rank)
                    - False: Force MRL disabled (direct full-vector search)

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

            >>> # Intent-aware filtering
            >>> search("how is User defined?")  # Auto-detects → class/struct filter
            >>> search("where is config used?") # Auto-detects → variable/field filter

            >>> # Manual kind filtering
            >>> search("User", kind_filter=["class", "struct"])

            >>> # MRL override
            >>> search("auth", use_mrl=False)  # Force full-vector (more accurate)
            >>> search("auth", use_mrl=True)   # Force short-vector + re-rank (faster)
        """
        if self._table is None:
            return []

        # Boundary conditions
        if not query or limit <= 0:
            return []

        # Clamp limit to prevent memory issues
        limit = min(limit, 1000)

        # Auto-detect intent if no explicit kind_filter and auto_detect_intent is enabled
        if kind_filter is None and auto_detect_intent:
            kind_filter = detect_search_intent(query)
            if kind_filter:
                logger.debug(f"Auto-detected intent filter: {kind_filter[:3]}... for query: {query[:50]}")

        # Auto-detect if method is "auto"
        if method == "auto":
            method = detect_search_method(query)

        # Route to appropriate search method
        # MRL config: override > instance default
        # When enabled, pass MRL_SHORT_DIM; when disabled, pass 0
        effective_use_mrl = use_mrl if use_mrl is not None else self.use_mrl
        mrl_dim = self.MRL_SHORT_DIM if effective_use_mrl else 0

        if method == "pattern":
            return search_pattern(self._table, self._pattern_index_created, query, limit, kind_filter)
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
                mrl_dim,
                kind_filter,
            )
        elif method == "semantic":
            return search_semantic(self._table, self._embeddings, query, limit, mrl_dim, kind_filter)
        else:  # hybrid
            return search_hybrid(
                self._table,
                self._fts_index_created,
                self._embeddings,
                query,
                limit,
                self._apply_search_enhancements,
                mrl_dim,
                kind_filter,
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
        mrl_dim = self.MRL_SHORT_DIM if self.use_mrl else 0
        return search_semantic(
            self._table, self._embeddings, query, limit, mrl_dim
        )

    def _search_hybrid(self, query: str, limit: int) -> list[dict]:
        """Hybrid search wrapper for backwards compatibility."""
        mrl_dim = self.MRL_SHORT_DIM if self.use_mrl else 0
        return search_hybrid(
            self._table,
            self._fts_index_created,
            self._embeddings,
            query,
            limit,
            self._apply_search_enhancements,
            mrl_dim,
        )

    def update_file_symbols(
        self,
        file_path: str,
        symbols: list[Any],
        vectors: np.ndarray,
        rebuild_index: bool = True,
        workspace_id: str = "primary",
    ) -> int:
        """
        Update symbols for a file (remove old, add new).

        Args:
            file_path: File path to update
            symbols: New symbols
            vectors: New embeddings
            rebuild_index: Whether to rebuild FTS index after update (default: True)
                          Set to False during batch operations, then call rebuild_fts_index() once at end
            workspace_id: Workspace identifier for this batch (default: "primary")

        Returns:
            Number of symbols updated
        """
        if self._table is None:
            # No existing data, just add
            return self.add_symbols(symbols, vectors, workspace_id=workspace_id)

        # Delete old symbols for this file
        # Escape single quotes for SQL (e.g., kid's_file.py -> kid''s_file.py)
        escaped_path = file_path.replace("'", "''")
        self._table.delete(f"file_path = '{escaped_path}'")

        # Add new symbols
        count = self.add_symbols(symbols, vectors, workspace_id=workspace_id)

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

    def clear_workspace(self, workspace_id: str) -> int:
        """
        Clear all vectors for a specific workspace.

        Used when removing a workspace from the unified database.

        Args:
            workspace_id: Workspace identifier to clear

        Returns:
            Estimated count of vectors deleted (or 0 if none/error)
        """
        if self._table is None:
            return 0

        try:
            # Count before deletion for reporting
            escaped_ws = workspace_id.replace("'", "''")
            pre_count = self._table.count_rows(f"workspace_id = '{escaped_ws}'")

            # Delete all vectors for this workspace
            self._table.delete(f"workspace_id = '{escaped_ws}'")

            logger.info(f"🗑️ Cleared {pre_count} vectors for workspace '{workspace_id}'")
            return pre_count
        except Exception as e:
            logger.warning(f"⚠️ Failed to clear workspace '{workspace_id}': {e}")
            return 0

    def optimize(self) -> dict:
        """
        Run maintenance tasks on the LanceDB table.

        This performs two critical operations:
        1. Compaction: Merges small data fragments into larger files.
           - LanceDB uses an append-only architecture, creating new fragment files
             on every write. Without compaction, queries must check hundreds of tiny
             files instead of a few large ones.

        2. Cleanup: Removes old versions and physically deletes rows.
           - LanceDB uses copy-on-write for deletions, marking rows as hidden
             rather than removing them. Cleanup reclaims this disk space.

        Returns:
            Dict with operation statistics (or empty dict on failure)

        Note:
            This is wrapped in try/except because file locks can cause failures,
            especially on Windows. A failed optimization is logged but doesn't
            crash the server.
        """
        if self._table is None:
            return {}

        logger.info(f"📦 Starting Vector Store optimization for table '{self.table_name}'...")
        start = time.time()

        try:
            # 1. Compact Files (Merges fragments)
            # This dramatically improves search speed after many streaming inserts.
            compact_stats = self._table.compact_files()
            logger.debug(f"   Compact stats: {compact_stats}")

            # 2. Cleanup Old Versions (Garbage Collection)
            # Removes data that is no longer visible (deleted/overwritten).
            # LanceDB keeps old versions for concurrent readers, but for a local
            # tool we can be aggressive with cleanup.
            cleanup_stats = self._table.cleanup_old_versions()
            logger.debug(f"   Cleanup stats: {cleanup_stats}")

            elapsed = time.time() - start
            logger.info(f"✅ Vector Store optimized in {elapsed:.2f}s")

            return {
                "compact": compact_stats,
                "cleanup": cleanup_stats,
                "elapsed_seconds": elapsed,
            }

        except Exception as e:
            # Don't crash the server if optimization fails (e.g., file lock)
            logger.warning(f"⚠️ Vector Store optimization failed: {e}")
            return {}

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
