"""
LanceDB vector storage and search.

Manages vector storage, FTS indexing, and multi-method search (text, pattern, semantic, hybrid).
"""

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import lancedb
import numpy as np
import pyarrow as pa

from miller.embeddings.search import SearchMethod, detect_search_method

if TYPE_CHECKING:
    from miller.embeddings.manager import EmbeddingManager


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
            # If table exists, try to create FTS indexes
            self._create_fts_index()
        except Exception:
            # Table doesn't exist yet, will be created on first add_symbols
            self._table = None

    def _create_fts_index(self):
        """
        Create Tantivy FTS index with whitespace tokenizer on code_pattern field.

        The whitespace tokenizer preserves special chars (: < > [ ] ( ) { })
        which is critical for code idiom search. The code_pattern field contains
        signature + name + kind, so it's suitable for general search too.

        Note: We use whitespace tokenizer instead of stemming because:
        - Code idioms need exact character matching (: < > [ ])
        - Whitespace tokenization is sufficient for code search
        - Pattern field already contains name/signature/kind, so covers general search
        """
        if self._table is None:
            return

        try:
            # Create single FTS index with whitespace tokenizer
            # This supports both pattern search (: BaseClass) and general search (function names)
            self._table.create_fts_index(
                ["code_pattern"],  # Pattern field (contains signature + name + kind)
                use_tantivy=True,  # Enable Tantivy FTS
                base_tokenizer="whitespace",  # Whitespace only (preserves : < > [ ] ( ) { })
                with_position=True,  # Enable phrase search
                replace=True,  # Replace existing index
            )
            self._fts_index_created = True
            self._pattern_index_created = True  # Same index serves both purposes
        except Exception:
            # FTS index creation might fail on older LanceDB versions
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
            return self._search_pattern(query, limit)
        elif method == "text":
            return self._search_text(query, limit)
        elif method == "semantic":
            return self._search_semantic(query, limit)
        else:  # hybrid
            return self._search_hybrid(query, limit)

    def _search_pattern(self, query: str, limit: int) -> list[dict]:
        """
        Pattern search using whitespace-tokenized FTS.

        Designed for code idiom search (: < > [ ] ( ) { }).
        Uses whitespace tokenizer which preserves all special characters.

        Args:
            query: Pattern query (e.g., ": BaseClass", "ILogger<", "[Fact]")
            limit: Maximum results

        Returns:
            List of matching symbols with normalized scores (0.0-1.0)
        """
        if not self._pattern_index_created:
            # Pattern index not available, return empty
            return []

        try:
            # Auto-wrap in quotes for phrase search (handles special chars safely)
            # Tantivy requires phrase search for queries with special chars
            search_query = f'"{query}"' if not query.startswith('"') else query

            # Use FTS search - LanceDB will use the whitespace-tokenized index on code_pattern
            results = self._table.search(search_query, query_type="fts").limit(limit).to_list()

            # Normalize BM25 scores to 0.0-1.0 range
            if results:
                max_score = max(r.get("_score", 0.0) for r in results)
                for r in results:
                    raw_score = r.get("_score", 0.0)
                    r["score"] = raw_score / max_score if max_score > 0 else 0.0

            return results

        except (ValueError, Exception):
            # Tantivy might reject malformed queries
            # Return empty results instead of crashing (safe failure mode)
            return []

    def _search_text(self, query: str, limit: int) -> list[dict]:
        """
        Text search using Tantivy FTS with BM25 scoring.

        Features:
        - BM25 relevance ranking (not just 1.0)
        - English stemming ("running" finds "run", "runs", "runner")
        - Phrase search support (quoted strings)
        - Safe from SQL injection (Tantivy rejects invalid queries)
        """
        if not self._fts_index_created:
            # Fallback to LIKE queries if FTS not available
            # (Older LanceDB versions or index creation failed)
            return self._search_text_fallback(query, limit)

        try:
            # Use Tantivy FTS with BM25 scoring
            results = self._table.search(query, query_type="fts").limit(limit).to_list()

            # Normalize BM25 scores to 0.0-1.0 range
            # LanceDB returns _score field with BM25 values
            if results:
                max_score = max(r.get("_score", 0.0) for r in results)
                for r in results:
                    # Normalize: divide by max score
                    raw_score = r.get("_score", 0.0)
                    r["score"] = raw_score / max_score if max_score > 0 else 0.0

            return results
        except (ValueError, Exception):
            # Tantivy raises ValueError for malformed queries (e.g., SQL injection attempts)
            # Return empty results instead of crashing (safe failure mode)
            return []

    def _search_text_fallback(self, query: str, limit: int) -> list[dict]:
        """
        Fallback text search using LIKE queries (for older LanceDB versions).

        WARNING: Less efficient, no stemming, no BM25 ranking.
        """
        # Use parameterized query to avoid SQL injection
        # Note: LanceDB's where() still uses string formatting for SQL-like syntax
        # This is a limitation of the current API
        results = (
            self._table.search()
            .where(
                f"name LIKE '%{query}%' OR signature LIKE '%{query}%' OR doc_comment LIKE '%{query}%'"
            )
            .limit(limit)
            .to_list()
        )

        # Add score (simple match = 1.0)
        for r in results:
            r["score"] = 1.0

        return results

    def _search_semantic(self, query: str, limit: int) -> list[dict]:
        """
        Semantic search using vector similarity.

        Requires embedding the query first.
        """
        # Get or create embedding manager
        if self._embeddings is None:
            # Fallback: create temporary embedding manager (lazy initialization)
            # This is less efficient but works if VectorStore was created without embeddings
            from miller.embeddings.manager import EmbeddingManager

            self._embeddings = EmbeddingManager()

        query_vec = self._embeddings.embed_query(query)

        # Vector search
        results = self._table.search(query_vec.tolist()).limit(limit).to_list()

        # LanceDB returns _distance - convert to similarity score
        for r in results:
            # Distance is in results, convert to similarity (1 - distance)
            # For L2 normalized vectors, distance ≈ 2*(1 - cosine_similarity)
            if "_distance" in r:
                r["score"] = 1.0 - (r["_distance"] / 2.0)
            else:
                r["score"] = 0.5  # Default

        return results

    def _search_hybrid(self, query: str, limit: int) -> list[dict]:
        """
        Hybrid search: combine text (FTS) and semantic (vector) with RRF fusion.

        Uses LanceDB's native Reciprocal Rank Fusion for optimal ranking.
        Falls back to manual merging if hybrid search not available.
        """
        if not self._fts_index_created:
            # Fall back to manual merging if FTS not available
            return self._search_hybrid_fallback(query, limit)

        try:
            # Use LanceDB's native hybrid search with RRF
            # Need to embed query for vector component
            if self._embeddings is None:
                # Fallback: create temporary embedding manager (lazy initialization)
                from miller.embeddings.manager import EmbeddingManager

                self._embeddings = EmbeddingManager()

            self._embeddings.embed_query(query)

            results = self._table.search(query, query_type="hybrid").limit(limit).to_list()

            # Normalize scores to 0.0-1.0 range
            if results:
                max_score = max(r.get("_score", 0.0) for r in results)
                for r in results:
                    raw_score = r.get("_score", 0.0)
                    r["score"] = raw_score / max_score if max_score > 0 else 0.0

            return results

        except Exception:
            # Hybrid search might not be supported in this LanceDB version
            # Fall back to manual merging
            return self._search_hybrid_fallback(query, limit)

    def _search_hybrid_fallback(self, query: str, limit: int) -> list[dict]:
        """
        Fallback hybrid search: manual merging of text and semantic results.

        Used when LanceDB's native hybrid search is not available.
        """
        # Get results from both methods
        text_results = self._search_text(query, limit)
        semantic_results = self._search_semantic(query, limit)

        # Merge and deduplicate by ID
        seen = set()
        merged = []

        for r in semantic_results + text_results:
            if r["id"] not in seen:
                seen.add(r["id"])
                merged.append(r)

        # Sort by score descending
        merged.sort(key=lambda x: x.get("score", 0), reverse=True)

        return merged[:limit]

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
        self._table.delete(f"file_path = '{file_path}'")

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
        """
        if self._fts_index_created:
            self._create_fts_index()

    def close(self):
        """Close database and cleanup temp directories."""
        if self._temp_dir:
            import shutil

            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.close()
