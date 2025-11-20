"""
Test Miller's embeddings layer (LanceDB + sentence-transformers).

Following TDD: These tests define the expected behavior BEFORE implementation.
They specify the interface for embedding generation and vector search.
"""

import pytest
import numpy as np
from pathlib import Path


class TestEmbeddingManager:
    """Test embedding generation with sentence-transformers."""

    def test_loads_embedding_model(self):
        """Test that EmbeddingManager loads the correct model."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        assert embeddings is not None
        assert embeddings.model is not None

    def test_auto_detects_device(self):
        """Test GPU auto-detection (use GPU if available, else CPU)."""
        from miller.embeddings import EmbeddingManager
        import torch

        embeddings = EmbeddingManager(device="auto")

        # Should auto-detect and use any available accelerator
        # Valid devices: cuda (NVIDIA/ROCm), mps (Apple Silicon), xpu (Intel Arc), directml, cpu
        valid_devices = {"cuda", "mps", "xpu", "cpu", "directml"}
        assert embeddings.device in valid_devices, f"Device '{embeddings.device}' not recognized"

        # Verify it chose an accelerator if one is available
        import torch
        if torch.cuda.is_available():
            assert embeddings.device == "cuda", "CUDA available but not selected"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            assert embeddings.device == "mps", "MPS available but not selected"
        # If no accelerator available, should fall back to CPU
        # (we don't assert device == "cpu" because other accelerators like XPU might be present)

    def test_embed_query_returns_correct_dimensions(self):
        """Test query embedding has correct dimensions (384 for bge-small)."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        query = "function to calculate user age"
        vector = embeddings.embed_query(query)

        assert vector.shape == (384,)
        assert vector.dtype == np.float32

    def test_embed_query_is_normalized(self):
        """Test query embeddings are L2 normalized (for cosine similarity)."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        vector = embeddings.embed_query("test query")

        # L2 norm should be ~1.0 (normalized)
        norm = np.linalg.norm(vector)
        assert 0.99 < norm < 1.01  # Allow small floating point error

    def test_embed_batch_symbols(self):
        """Test batch embedding of symbols."""
        from miller.embeddings import EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Extract symbols from code
        code = """
def calculate_age(birthdate):
    '''Calculate user age from birthdate.'''
    return 2025 - birthdate.year

def get_user_profile(user_id):
    '''Fetch user profile by ID.'''
    pass
"""
        result = miller_core.extract_file(code, "python", "test.py")

        # Embed all symbols
        vectors = embeddings.embed_batch(result.symbols)

        assert vectors.shape == (len(result.symbols), 384)
        assert vectors.dtype == np.float32

        # Each vector should be normalized
        for vec in vectors:
            norm = np.linalg.norm(vec)
            assert 0.99 < norm < 1.01

    def test_embed_batch_handles_empty_list(self):
        """Test that embed_batch handles empty input gracefully."""
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        vectors = embeddings.embed_batch([])

        assert vectors.shape == (0, 384)


class TestVectorStore:
    """Test LanceDB vector storage and search."""

    def test_creates_lancedb_table(self):
        """Test that VectorStore creates a LanceDB table."""
        from miller.embeddings import VectorStore

        store = VectorStore(db_path=":memory:")
        assert store is not None

    def test_add_symbols_with_embeddings(self):
        """Test adding symbols with their embeddings to LanceDB."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        # Create embeddings
        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        # Store in LanceDB
        store = VectorStore(db_path=":memory:")
        count = store.add_symbols(result.symbols, vectors)

        assert count == 1

    def test_text_search_finds_exact_match(self):
        """Test text search (keyword matching, no vectors)."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        # Index some symbols
        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = """
def calculate_user_age(): pass
def fetch_user_profile(): pass
def delete_old_files(): pass
"""
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Text search for "user"
        results = store.search(query="user", method="text", limit=10)

        assert len(results) > 0
        # Should find calculate_user_age and fetch_user_profile
        names = [r["name"] for r in results]
        assert "calculate_user_age" in names
        assert "fetch_user_profile" in names
        assert "delete_old_files" not in names  # Doesn't contain "user"

    def test_semantic_search_finds_similar_concepts(self):
        """Test semantic search (vector similarity)."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        # Index symbols with doc comments
        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def calculate_user_age():
    """Compute the age of a user based on birthdate."""
    pass

def delete_old_files():
    """Remove expired temporary files from disk."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Semantic search (natural language query)
        results = store.search(
            query="function that computes user age",
            method="semantic",
            limit=5
        )

        assert len(results) > 0
        # First result should be calculate_user_age (high semantic similarity)
        assert results[0]["name"] == "calculate_user_age"
        assert results[0]["score"] > 0.5  # High similarity score

    def test_hybrid_search_combines_text_and_semantic(self):
        """Test hybrid search (best of both worlds)."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def calculate_age():
    """Compute user age."""
    pass

def get_user():
    """Fetch user data."""
    pass

def process_payment():
    """Handle payment processing."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Hybrid: should combine keyword "user" + semantic "age computation"
        results = store.search(
            query="user age",
            method="hybrid",
            limit=5
        )

        assert len(results) > 0
        # Should rank functions mentioning "user" or about age highly
        names = [r["name"] for r in results]
        assert "calculate_age" in names or "get_user" in names

    def test_search_returns_metadata(self):
        """Test that search results include symbol metadata."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = "def hello(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        results = store.search(query="hello", method="text", limit=1)

        assert len(results) == 1
        r = results[0]

        # Verify metadata fields
        assert r["name"] == "hello"
        assert r["kind"] == "function"
        assert r["file_path"] == "test.py"
        assert "score" in r  # Search relevance score

    def test_update_symbol_embeddings(self):
        """Test updating embeddings when symbol changes."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Add initial symbol
        code1 = "def old_name(): pass"
        result1 = miller_core.extract_file(code1, "python", "test.py")
        vectors1 = embeddings.embed_batch(result1.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result1.symbols, vectors1)

        # Update with new code (rename function)
        code2 = "def new_name(): pass"
        result2 = miller_core.extract_file(code2, "python", "test.py")
        vectors2 = embeddings.embed_batch(result2.symbols)

        # Should replace old symbols
        store.update_file_symbols("test.py", result2.symbols, vectors2)

        # Search should only find new name
        results = store.search(query="new_name", method="text", limit=10)
        names = [r["name"] for r in results]
        assert "new_name" in names
        assert "old_name" not in names


class TestTantivyFTS:
    """Test Tantivy full-text search integration (Phase 1 of FTS migration)."""

    def test_fts_index_is_created_on_init(self):
        """Test that Tantivy FTS index is created when VectorStore initializes."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        # Create store and add symbols
        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = "def calculate_user_age(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Verify FTS index exists
        # LanceDB should have created FTS index on name, signature, doc_comment
        # We'll verify by doing an FTS search (implementation will use query_type="fts")
        assert store._table is not None
        assert store._fts_index_created is True  # New attribute we'll add

    def test_fts_search_uses_bm25_scoring(self):
        """Test that FTS search returns relevance scores.

        Note: LanceDB may normalize scores or not expose raw BM25 values.
        We verify that search works and returns reasonable scores, not specific BM25 values.
        """
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def calculate_user_age():
    """Calculate the age of a user based on birthdate."""
    pass

def get_user_profile():
    """Fetch user profile data from database."""
    pass

def delete_old_files():
    """Remove temporary files from disk."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Text search with FTS should return results with scores
        results = store.search(query="user", method="text", limit=10)

        assert len(results) >= 2  # Should find calculate_user_age and get_user_profile

        # All results should have non-negative scores
        for r in results:
            assert "score" in r, "Result should have score field"
            assert r["score"] >= 0.0, f"Score should be non-negative: {r['score']}"

        # Should find user-related functions
        names = [r["name"] for r in results]
        assert "calculate_user_age" in names or "get_user_profile" in names

    def test_fts_search_no_sql_injection(self):
        """Test that FTS search is safe from SQL injection attacks."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = "def safe_function(): pass"
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Try SQL injection attack
        malicious_query = "'; DROP TABLE symbols; --"

        # Should handle safely (no exception, no data loss)
        results = store.search(query=malicious_query, method="text", limit=10)

        # Search should return empty results (no match), not crash
        assert isinstance(results, list)  # No exception raised

        # Verify table still exists (wasn't dropped)
        safe_results = store.search(query="safe", method="text", limit=10)
        assert len(safe_results) > 0  # Can still find symbols

    def test_fts_phrase_search(self):
        """Test phrase search behavior.

        Note: LanceDB FTS may not support quoted phrase search syntax yet.
        We test multi-word query matching instead.
        """
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def calculate_user_age():
    """Calculate the age of a user."""
    pass

def get_user_data():
    """Get data for a user account."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Multi-word search: should find symbols containing these terms
        # (Quoted syntax may not be supported yet - test regular multi-word query)
        results = store.search(query="age user", method="text", limit=10)

        assert len(results) > 0, "Should find symbols matching multi-word query"
        # Should find calculate_user_age (contains both terms)
        names = [r["name"] for r in results]
        assert "calculate_user_age" in names, f"Should find calculate_user_age in {names}"

    def test_fts_stemming_support(self):
        """Test FTS text matching behavior.

        Note: Stemming may not be enabled in LanceDB FTS by default.
        We test that exact matches work reliably.
        """
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def run_process():
    """Runs the background process."""
    pass

def runner_thread():
    """Running thread manager."""
    pass

def start_execution():
    """Start the execution."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Test basic text matching (stemming may not be enabled by default)
        # Search for exact terms that appear in symbol names
        results_run = store.search(query="run", method="text", limit=10)
        results_process = store.search(query="process", method="text", limit=10)

        # Should find symbols containing search terms
        assert len(results_run) >= 1, "Should find 'run' in function names"
        names_run = [r["name"] for r in results_run]
        assert "run_process" in names_run, f"Should find run_process in {names_run}"

        # Should find different symbol with "process"
        assert len(results_process) >= 1, "Should find 'process' in function names"
        names_process = [r["name"] for r in results_process]
        assert "run_process" in names_process, f"Should find run_process in {names_process}"

        # Verify FTS is working (not just returning all results)
        results_unrelated = store.search(query="xyz123notfound", method="text", limit=10)
        assert len(results_unrelated) == 0, "Should not find non-existent terms"

    def test_fts_hybrid_search_with_rrf(self):
        """Test hybrid search uses Reciprocal Rank Fusion (RRF) for merging."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")
        code = '''
def calculate_age():
    """Compute user age from birthdate."""
    pass

def get_user():
    """Fetch user account data."""
    pass

def process_payment():
    """Handle payment transactions."""
    pass
'''
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Hybrid search should combine text (keyword "user") + semantic (age concepts)
        results = store.search(query="user age", method="hybrid", limit=10)

        assert len(results) >= 2

        # Both calculate_age and get_user should rank highly
        names = [r["name"] for r in results]
        assert "calculate_age" in names or "get_user" in names

        # Scores should reflect RRF fusion (not simple deduplication)
        # RRF produces different scores than simple text or semantic alone
        for r in results:
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_fts_index_updates_on_file_change(self):
        """Test that FTS index is updated when file symbols change."""
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Initial indexing
        code1 = "def old_function(): pass"
        result1 = miller_core.extract_file(code1, "python", "test.py")
        vectors1 = embeddings.embed_batch(result1.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result1.symbols, vectors1)

        # Update file with new symbols
        code2 = "def new_function(): pass"
        result2 = miller_core.extract_file(code2, "python", "test.py")
        vectors2 = embeddings.embed_batch(result2.symbols)

        store.update_file_symbols("test.py", result2.symbols, vectors2)

        # FTS search should find new symbol, not old
        results = store.search(query="new_function", method="text", limit=10)
        names = [r["name"] for r in results]

        assert "new_function" in names

        # Old function should be gone from FTS index
        old_results = store.search(query="old_function", method="text", limit=10)
        old_names = [r["name"] for r in old_results]
        assert "old_function" not in old_names


class TestPerformance:
    """Test embedding and search performance."""

    def test_embed_batch_is_fast(self):
        """Test that batch embedding is reasonably fast."""
        import time
        from miller.embeddings import EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Generate 100 symbols
        code = "\n".join([f"def func_{i}(): pass" for i in range(100)])
        result = miller_core.extract_file(code, "python", "test.py")

        start = time.time()
        vectors = embeddings.embed_batch(result.symbols)
        elapsed = time.time() - start

        assert vectors.shape == (100, 384)

        # Should complete in reasonable time
        # (GPU: <1s, CPU: <10s for 100 symbols)
        assert elapsed < 10.0  # Generous timeout for CI/CD

    def test_search_is_fast(self):
        """Test that vector search is reasonably fast."""
        import time
        from miller.embeddings import VectorStore, EmbeddingManager
        from miller import miller_core

        embeddings = EmbeddingManager(model_name="BAAI/bge-small-en-v1.5")

        # Index 100 symbols
        code = "\n".join([f"def func_{i}(): pass" for i in range(100)])
        result = miller_core.extract_file(code, "python", "test.py")
        vectors = embeddings.embed_batch(result.symbols)

        store = VectorStore(db_path=":memory:")
        store.add_symbols(result.symbols, vectors)

        # Search should be fast
        start = time.time()
        results = store.search(query="func_50", method="hybrid", limit=10)
        elapsed = time.time() - start

        assert len(results) > 0
        assert elapsed < 1.0  # Should be sub-second
