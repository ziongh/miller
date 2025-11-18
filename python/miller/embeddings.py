"""
Miller Embeddings Layer - LanceDB + sentence-transformers

Provides vector embeddings and semantic search capabilities.
Uses sentence-transformers for encoding and LanceDB for vector storage.
"""

import numpy as np
import torch
import pyarrow as pa
from typing import List, Dict, Optional, Any, Literal
from pathlib import Path
from sentence_transformers import SentenceTransformer
import lancedb
import sys
import os
from contextlib import redirect_stdout, redirect_stderr


class EmbeddingManager:
    """
    Manages embedding generation with sentence-transformers.

    Features:
    - GPU auto-detection (uses CUDA if available)
    - Batch encoding for performance
    - L2 normalization for cosine similarity
    - BGE-small model (384 dimensions)
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        device: str = "auto"
    ):
        """
        Initialize embedding model.

        Args:
            model_name: HuggingFace model identifier
            device: Device to use ("auto", "cuda", "cpu")
        """
        # Auto-detect device
        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        # Load model (suppress stdout/stderr to keep MCP protocol clean)
        # SentenceTransformer downloads models and writes progress to stdout,
        # which breaks MCP's JSON-RPC protocol (stdout must be clean)
        with open(os.devnull, 'w') as devnull:
            with redirect_stdout(devnull), redirect_stderr(devnull):
                self.model = SentenceTransformer(model_name, device=self.device)

        self.model_name = model_name

        # Get embedding dimension from model
        self.dimensions = self.model.get_sentence_embedding_dimension()

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a single query string.

        Args:
            query: Text to embed

        Returns:
            L2-normalized embedding vector (384 dimensions)
        """
        # Encode and normalize
        embedding = self.model.encode(
            query,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True
        )
        return embedding.astype(np.float32)

    def embed_batch(self, symbols: List[Any]) -> np.ndarray:
        """
        Embed a batch of symbols.

        Args:
            symbols: List of PySymbol objects from extraction

        Returns:
            Array of embeddings (N x 384), L2-normalized
        """
        if not symbols:
            # Return empty array with correct shape
            return np.empty((0, self.dimensions), dtype=np.float32)

        # Build text representations for each symbol
        texts = []
        for sym in symbols:
            # Combine name, signature, doc comment for rich representation
            parts = [sym.name]

            if hasattr(sym, 'signature') and sym.signature:
                parts.append(sym.signature)

            if hasattr(sym, 'doc_comment') and sym.doc_comment:
                parts.append(sym.doc_comment)

            text = " ".join(parts)
            texts.append(text)

        # Batch encode
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # L2 normalize
            convert_to_numpy=True,
            show_progress_bar=False  # Suppress progress bar for tests
        )

        return embeddings.astype(np.float32)


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
    SCHEMA = pa.schema([
        pa.field("id", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
        pa.field("language", pa.string(), nullable=False),
        pa.field("file_path", pa.string(), nullable=False),
        pa.field("signature", pa.string(), nullable=True),      # Optional
        pa.field("doc_comment", pa.string(), nullable=True),    # Optional
        pa.field("start_line", pa.int32(), nullable=True),      # Optional
        pa.field("end_line", pa.int32(), nullable=True),        # Optional
        pa.field("vector", pa.list_(pa.float32(), 384), nullable=False),  # 384-dim embeddings
    ])

    def __init__(self, db_path: str = ".miller/indexes/vectors.lance"):
        """
        Initialize LanceDB connection.

        Args:
            db_path: Path to LanceDB database
                    (use ":memory:" for temp directory in tests)
        """
        self.db_path = db_path

        # Handle :memory: by creating temp directory
        if db_path == ":memory:":
            import tempfile
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
        try:
            self._table = self.db.open_table(self.table_name)
        except Exception:
            # Table doesn't exist yet, will be created on first add_symbols
            self._table = None

    def add_symbols(self, symbols: List[Any], vectors: np.ndarray) -> int:
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
            data.append({
                "id": sym.id,
                "name": sym.name,
                "kind": sym.kind,
                "language": sym.language,
                "file_path": sym.file_path,
                "signature": sym.signature if hasattr(sym, 'signature') else None,
                "doc_comment": sym.doc_comment if hasattr(sym, 'doc_comment') else None,
                "start_line": sym.start_line if hasattr(sym, 'start_line') else 0,
                "end_line": sym.end_line if hasattr(sym, 'end_line') else 0,
                "vector": vec.tolist(),  # LanceDB stores as list
            })

        # Create or append to table
        if self._table is None:
            # First time: create table with explicit schema to handle nullable fields
            import pyarrow as pa
            table = pa.Table.from_pylist(data, schema=self.SCHEMA)
            self._table = self.db.create_table(self.table_name, table, mode="overwrite")
        else:
            # Subsequent times: append (schema already defined)
            self._table.add(data)

        return len(data)

    def search(
        self,
        query: str,
        method: Literal["text", "semantic", "hybrid"] = "hybrid",
        limit: int = 50
    ) -> List[Dict]:
        """
        Search symbols by query.

        Args:
            query: Search query
            method: Search method (text, semantic, hybrid)
            limit: Maximum results

        Returns:
            List of dicts with symbol metadata + score
        """
        if self._table is None:
            return []

        if method == "text":
            return self._search_text(query, limit)
        elif method == "semantic":
            return self._search_semantic(query, limit)
        else:  # hybrid
            return self._search_hybrid(query, limit)

    def _search_text(self, query: str, limit: int) -> List[Dict]:
        """
        Text search using keyword matching.

        Uses LanceDB's full-text search on name, signature, doc_comment.
        """
        # Simple SQL WHERE clause for text matching
        # LanceDB supports SQL-like queries
        results = (
            self._table
            .search()
            .where(f"name LIKE '%{query}%' OR signature LIKE '%{query}%' OR doc_comment LIKE '%{query}%'")
            .limit(limit)
            .to_list()
        )

        # Add score (simple match = 1.0)
        for r in results:
            r["score"] = 1.0

        return results

    def _search_semantic(self, query: str, limit: int) -> List[Dict]:
        """
        Semantic search using vector similarity.

        Requires embedding the query first.
        """
        # Need to embed query - but we don't have access to EmbeddingManager here
        # This is a design issue - let me refactor

        # For now, create temporary embedding manager
        # (In production, we'd pass it as a dependency)
        from miller.embeddings import EmbeddingManager
        embeddings = EmbeddingManager()
        query_vec = embeddings.embed_query(query)

        # Vector search
        results = (
            self._table
            .search(query_vec.tolist())
            .limit(limit)
            .to_list()
        )

        # LanceDB returns _distance - convert to similarity score
        for r in results:
            # Distance is in results, convert to similarity (1 - distance)
            # For L2 normalized vectors, distance ≈ 2*(1 - cosine_similarity)
            if "_distance" in r:
                r["score"] = 1.0 - (r["_distance"] / 2.0)
            else:
                r["score"] = 0.5  # Default

        return results

    def _search_hybrid(self, query: str, limit: int) -> List[Dict]:
        """
        Hybrid search: combine text and semantic results.

        Simple implementation: merge and deduplicate by ID.
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
        self,
        file_path: str,
        symbols: List[Any],
        vectors: np.ndarray
    ) -> int:
        """
        Update symbols for a file (remove old, add new).

        Args:
            file_path: File path to update
            symbols: New symbols
            vectors: New embeddings

        Returns:
            Number of symbols updated
        """
        if self._table is None:
            # No existing data, just add
            return self.add_symbols(symbols, vectors)

        # Delete old symbols for this file
        self._table.delete(f"file_path = '{file_path}'")

        # Add new symbols
        return self.add_symbols(symbols, vectors)

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
