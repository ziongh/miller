"""
LanceDB vector storage and search.

Manages vector storage, FTS indexing, and multi-method search (text, pattern, semantic, hybrid).
"""

import logging
import tempfile

logger = logging.getLogger("miller.vector_store")
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
            logger.debug(f"Opened existing LanceDB table '{self.table_name}'")
            # If table exists, try to create FTS indexes
            self._create_fts_index()
        except Exception:
            # Table doesn't exist yet, will be created on first add_symbols
            logger.debug(f"LanceDB table '{self.table_name}' not found, will create on first add")
            self._table = None

    def _create_fts_index(self, max_retries: int = 3):
        """
        Create Tantivy FTS index with whitespace tokenizer on code_pattern field.

        The whitespace tokenizer preserves special chars (: < > [ ] ( ) { })
        which is critical for code idiom search. The code_pattern field contains
        signature + name + kind, so it's suitable for general search too.

        Note: We use whitespace tokenizer instead of stemming because:
        - Code idioms need exact character matching (: < > [ ])
        - Whitespace tokenization is sufficient for code search
        - Pattern field already contains name/signature/kind, so covers general search

        Args:
            max_retries: Number of retry attempts for Windows file locking issues.
                         Tantivy has a known race condition on Windows where file
                         operations can fail with PermissionDenied. Usually succeeds
                         on retry. See: https://github.com/quickwit-oss/tantivy/issues/587
        """
        import sys
        import time

        if self._table is None:
            return

        last_error = None
        for attempt in range(max_retries):
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
                if attempt > 0:
                    logger.info(f"FTS index created successfully on retry {attempt + 1}")
                else:
                    logger.debug("FTS index created successfully on code_pattern field")
                return  # Success!

            except Exception as e:
                last_error = e
                error_str = str(e)

                # Check if this is a retryable Windows error
                # Tantivy has known race conditions on Windows that cause transient failures:
                # 1. PermissionDenied (code 5) - file locking race condition
                # 2. "index writer was killed" - thread panic, often from I/O race
                # See: https://github.com/quickwit-oss/tantivy/issues/587
                is_windows_transient = (
                    "PermissionDenied" in error_str
                    or "Access is denied" in error_str
                    or "index writer was killed" in error_str
                    or "worker thread encountered an error" in error_str
                    or (hasattr(e, "errno") and e.errno == 5)
                )

                if is_windows_transient and sys.platform == "win32" and attempt < max_retries - 1:
                    # Exponential backoff: 100ms, 200ms, 400ms...
                    delay = 0.1 * (2 ** attempt)
                    logger.debug(
                        f"FTS index creation hit Windows issue (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {delay:.1f}s: {error_str[:100]}"
                    )
                    time.sleep(delay)
                    continue

                # Non-retryable error or max retries exceeded
                break

        # All retries failed or non-retryable error
        logger.warning(f"FTS index creation failed: {last_error}", exc_info=True)
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
            # OPTIMIZATION: Route text search to hybrid instead of whitespace-FTS
            # Reason: Our FTS index uses whitespace tokenizer (for pattern search),
            # which can't do stemming/prefix matching. Hybrid search (semantic + FTS)
            # provides much better text search quality.
            # Users should use "pattern" for code idioms, "text"/"auto"/"hybrid" for general search.
            return self._search_hybrid(query, limit)
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

        except (ValueError, Exception) as e:
            # Tantivy might reject malformed queries
            # Return empty results instead of crashing (safe failure mode)
            logger.warning(f"Pattern search failed for query '{query}': {e}")
            return []

    def _search_text(self, query: str, limit: int) -> list[dict]:
        """
        Text search using Tantivy FTS with BM25 scoring + quality enhancements.

        Features:
        - BM25 relevance ranking (not just 1.0)
        - Whitespace tokenization (preserves CamelCase, no stemming currently)
        - Phrase search support (quoted strings)
        - Safe from SQL injection (Tantivy rejects invalid queries)
        - Field boosting (name > signature > doc)
        - Match position boosting (exact > prefix > suffix)
        - Symbol kind weighting (functions/classes > variables)
        - Quality filtering (removes noise)

        Note: Currently using whitespace tokenizer (shared with pattern search).
        For better stemming support, need dual FTS indexes (TODO).
        """
        if not self._fts_index_created:
            # Fallback to LIKE queries if FTS not available
            # (Older LanceDB versions or index creation failed)
            return self._search_text_fallback(query, limit)

        try:
            # Use Tantivy FTS with BM25 scoring (with original query - no preprocessing)
            # Over-fetch to allow kind weighting to re-rank before truncating
            # Min of 50 ensures high-value symbols (functions) aren't cut before boosting
            fetch_limit = max(limit * 3, 50)
            results = self._table.search(query, query_type="fts").limit(fetch_limit).to_list()

            # Normalize BM25 scores to 0.0-1.0 range (initial normalization)
            # LanceDB returns _score field with BM25 values
            if results:
                max_score = max(r.get("_score", 0.0) for r in results)
                for r in results:
                    # Normalize: divide by max score
                    raw_score = r.get("_score", 0.0)
                    r["score"] = raw_score / max_score if max_score > 0 else 0.0

            # Apply search quality enhancements (boosting, weighting, filtering)
            results = self._apply_search_enhancements(results, query, method="text")

            # Return top results after enhancement
            return results[:limit]

        except (ValueError, Exception) as e:
            # Tantivy raises ValueError for malformed queries (e.g., SQL injection attempts)
            # Return empty results instead of crashing (safe failure mode)
            logger.warning(f"Text search failed for query '{query}': {e}")
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

            # Over-fetch to allow kind weighting to re-rank before truncating
            # Without this, high-value symbols (functions, classes) might be cut
            # before they can be boosted above low-value symbols (imports)
            fetch_limit = max(limit * 3, limit + 50)
            results = self._table.search(query, query_type="hybrid").limit(fetch_limit).to_list()

            # Normalize scores to 0.0-1.0 range
            if results:
                max_score = max(r.get("_score", 0.0) for r in results)
                for r in results:
                    raw_score = r.get("_score", 0.0)
                    r["score"] = raw_score / max_score if max_score > 0 else 0.0

            # Apply kind weighting, field boosting, etc.
            results = self._apply_search_enhancements(results, query, method="hybrid")

            # Now truncate to requested limit (after re-ranking)
            return results[:limit]

        except Exception as e:
            # Hybrid search might not be supported in this LanceDB version
            # Fall back to manual merging
            logger.debug(f"Native hybrid search failed, using fallback: {e}")
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

    # === SEARCH QUALITY ENHANCEMENTS ===
    # Methods below improve search relevance and ranking

    def _preprocess_query(self, query: str, method: str) -> str:
        """
        Preprocess query for better search results.

        Enhancements:
        - CamelCase splitting: "UserService" → "User Service" (better tokenization)
        - Noise word removal for text search (optional, currently disabled)
        - Whitespace normalization

        Args:
            query: Original query
            method: Search method ("text", "pattern", "semantic", "hybrid")

        Returns:
            Preprocessed query
        """
        import re

        original_query = query
        query = query.strip()

        if not query:
            return original_query

        # For text/hybrid search: handle CamelCase
        if method in ["text", "hybrid"]:
            # Check if query looks like CamelCase (e.g., "UserService", "parseJSON")
            # Heuristic: has uppercase letters that aren't at the start
            if any(c.isupper() for c in query[1:]) and not " " in query:
                # Split on uppercase letters: "UserService" → "User Service"
                # This helps tokenizer match "user" and "service" separately
                query_split = re.sub(r'([A-Z])', r' \1', query).strip()
                # Use split version if it's different and non-empty
                if query_split != query and query_split:
                    query = query_split

        return query

    def _boost_by_field_match(self, result: dict, query: str) -> float:
        """
        Boost score based on which field matched.

        Relevance hierarchy:
        - Name match: 3.0x boost (most important - symbol name is primary identifier)
        - Signature match: 1.5x boost (important - shows usage)
        - Doc comment match: 1.0x boost (base - contextual info)

        Args:
            result: Search result dict
            query: Search query (lowercased for matching)

        Returns:
            Boosted score (0.0-1.0 after normalization)
        """
        base_score = result.get("score", 0.0)
        query_lower = query.lower().strip()

        if not query_lower:
            return base_score

        # Check for partial match in each field
        name = result.get("name", "").lower()
        signature = (result.get("signature") or "").lower()
        doc_comment = (result.get("doc_comment") or "").lower()

        # Apply boosts based on match location
        if query_lower in name:
            return min(base_score * 3.0, 1.0)  # Name match = highest priority
        elif query_lower in signature:
            return min(base_score * 1.5, 1.0)  # Signature match = medium priority
        elif query_lower in doc_comment:
            return base_score * 1.0  # Doc match = base priority
        else:
            # No obvious match (might be stemmed or fuzzy)
            return base_score

    def _boost_by_match_position(self, result: dict, query: str) -> float:
        """
        Boost score based on match position (exact > prefix > suffix > substring).

        Match type hierarchy:
        - Exact match: 3.0x boost (query == name)
        - Prefix match: 2.0x boost (name starts with query)
        - Suffix match: 1.5x boost (name ends with query)
        - Substring match: 1.0x boost (query in name)

        Args:
            result: Search result dict
            query: Search query

        Returns:
            Boosted score (0.0-1.0 after normalization)
        """
        base_score = result.get("score", 0.0)
        query_lower = query.lower().strip()
        name = result.get("name", "").lower()

        if not query_lower or not name:
            return base_score

        # Check match type (in order of specificity)
        if name == query_lower:
            return min(base_score * 3.0, 1.0)  # Exact match = huge boost
        elif name.startswith(query_lower):
            return min(base_score * 2.0, 1.0)  # Prefix match = strong boost
        elif name.endswith(query_lower):
            return min(base_score * 1.5, 1.0)  # Suffix match = moderate boost
        elif query_lower in name:
            return base_score * 1.0  # Substring = base score
        else:
            # Check signature/doc for matches
            return self._boost_by_field_match(result, query)

    def _apply_kind_weighting(self, result: dict) -> float:
        """
        Apply symbol kind weighting to boost commonly-searched symbol types.

        Rationale:
        - Functions/Classes are usually search targets (user wants to call/extend them)
        - Variables/Fields are less often the primary search target
        - This aligns ranking with developer intent

        Kind weights:
        - Function: 1.5x (most commonly searched)
        - Class: 1.5x
        - Method: 1.3x
        - Interface/Type: 1.2x
        - Variable/Field: 0.8x (less commonly the target)
        - Constant: 0.9x

        Args:
            result: Search result dict

        Returns:
            Weighted score (0.0-1.0 after normalization)
        """
        KIND_WEIGHTS = {
            "Function": 1.5,
            "Class": 1.5,
            "Method": 1.3,
            "Interface": 1.2,
            "Type": 1.2,
            "Struct": 1.2,
            "Enum": 1.1,
            "Variable": 0.8,
            "Field": 0.8,
            "Constant": 0.9,
            "Parameter": 0.7,
            # Deboost noise - you want definitions, not these
            "Import": 0.4,
            "Namespace": 0.6,
        }

        base_score = result.get("score", 0.0)
        kind = result.get("kind", "")

        # Normalize kind to title case (data has "function", dict has "Function")
        weight = KIND_WEIGHTS.get(kind.title(), 1.0)  # Default 1.0 for unknown kinds
        return min(base_score * weight, 1.0)  # Clamp to 1.0

    def _filter_low_quality_results(self, results: list[dict], min_score: float = 0.05) -> list[dict]:
        """
        Filter out very low-quality results (noise reduction).

        Low-scoring results are unlikely to be useful and waste tokens.
        Default threshold: 0.05 (5% of max score) - removes obvious noise.

        Args:
            results: Search results with normalized scores (0.0-1.0)
            min_score: Minimum score threshold (default: 0.05)

        Returns:
            Filtered results (only those above threshold)
        """
        return [r for r in results if r.get("score", 0.0) >= min_score]

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
        if not results:
            return results

        # Preprocess query (same preprocessing as search)
        processed_query = self._preprocess_query(query, method)

        # Apply enhancements to each result
        for result in results:
            # Start with base score
            score = result.get("score", 0.0)

            # Apply match position boost (exact > prefix > suffix)
            score = self._boost_by_match_position(result, processed_query)

            # Apply symbol kind weighting
            result["score"] = score  # Update for kind weighting
            score = self._apply_kind_weighting(result)

            # Store final enhanced score
            result["score"] = score

        # Re-normalize scores to 0.0-1.0 range after boosting
        if results:
            max_score = max(r.get("score", 0.0) for r in results)
            if max_score > 0:
                for r in results:
                    r["score"] = r["score"] / max_score

        # Filter low-quality results (remove noise)
        results = self._filter_low_quality_results(results, min_score=0.05)

        # Re-sort by enhanced scores
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        return results

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
            import shutil

            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def __enter__(self):
        """Context manager support."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support."""
        self.close()
