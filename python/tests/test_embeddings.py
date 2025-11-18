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

        if torch.cuda.is_available():
            assert embeddings.device == "cuda"
        else:
            assert embeddings.device == "cpu"

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
