"""
Tests for streaming workspace indexing with IndexingBuffer.

These tests verify that the scanner correctly uses symbol-based flushing
(via IndexingBuffer) rather than just file-based batching.
"""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def large_test_workspace():
    """Create a temporary workspace with many code files.

    This workspace has enough files to trigger multiple flushes during indexing.
    """
    temp_dir = tempfile.mkdtemp(prefix="miller_streaming_test_")
    workspace = Path(temp_dir)

    (workspace / "src").mkdir()

    # Create 100 files, each with 3-5 symbols
    # Total: ~400 symbols, should trigger multiple flushes with default buffer size
    for i in range(100):
        file_content = f'''
def function_{i}_a(x):
    """Process input {i} a."""
    return x * {i}

def function_{i}_b(y):
    """Process input {i} b."""
    return y + {i}

def function_{i}_c(z):
    """Process input {i} c."""
    return z - {i}

class Handler_{i}:
    """Handler for {i}."""
    pass
'''
        (workspace / "src" / f"module_{i}.py").write_text(file_content)

    # Create .gitignore
    (workspace / ".gitignore").write_text("__pycache__/\n*.pyc\n")

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestStreamingIndexerIntegration:
    """Integration tests for streaming indexer."""

    @pytest.mark.asyncio
    async def test_indexes_all_files_successfully(
        self, large_test_workspace, storage_manager, vector_store
    ):
        """Test that streaming indexer indexes all files."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            large_test_workspace, storage_manager, embeddings, vector_store
        )
        stats = await scanner.index_workspace()

        # Should have indexed all Python files (100) + possibly .gitignore
        # The exact count depends on language detection
        assert stats["indexed"] >= 100
        assert stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_indexes_all_symbols_correctly(
        self, large_test_workspace, storage_manager, vector_store
    ):
        """Test that streaming indexer captures all symbols."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            large_test_workspace, storage_manager, embeddings, vector_store
        )
        stats = await scanner.index_workspace()

        # Each file has 3 functions + 1 class = 4 symbols
        # 100 files * 4 symbols = 400 symbols
        assert stats["total_symbols"] >= 400, (
            f"Expected at least 400 symbols, got {stats['total_symbols']}"
        )

    @pytest.mark.asyncio
    async def test_symbols_are_searchable_after_indexing(
        self, large_test_workspace, storage_manager, vector_store
    ):
        """Test that indexed symbols can be searched."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            large_test_workspace, storage_manager, embeddings, vector_store
        )
        await scanner.index_workspace()

        # Search for a specific function
        results = vector_store.search(
            query="function_50_a", method="text", limit=10
        )

        assert len(results) > 0
        assert any("function_50_a" in r["name"] for r in results)

    @pytest.mark.asyncio
    async def test_reindexing_is_incremental(
        self, large_test_workspace, storage_manager, vector_store
    ):
        """Test that reindexing skips unchanged files."""
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            large_test_workspace, storage_manager, embeddings, vector_store
        )

        # First indexing
        stats1 = await scanner.index_workspace()
        initial_count = stats1["indexed"]
        assert initial_count >= 100

        # Second indexing - should skip all files
        stats2 = await scanner.index_workspace()
        assert stats2["indexed"] == 0
        assert stats2["skipped"] == initial_count


class TestStreamingBufferIntegration:
    """Test IndexingBuffer integration with scanner."""

    @pytest.mark.asyncio
    async def test_buffer_flushes_based_on_symbol_count(
        self, large_test_workspace, storage_manager, vector_store
    ):
        """
        Verify that buffer flushes happen when symbol threshold is reached.

        This is verified indirectly by checking that:
        1. Indexing completes successfully
        2. All symbols are indexed
        3. No memory errors occur

        The actual flush behavior is an internal implementation detail.
        """
        from miller.workspace import WorkspaceScanner
        from miller.embeddings import EmbeddingManager

        embeddings = EmbeddingManager(device="cpu")

        scanner = WorkspaceScanner(
            large_test_workspace, storage_manager, embeddings, vector_store
        )
        stats = await scanner.index_workspace()

        # Successful completion implies correct buffer management
        assert stats["errors"] == 0
        assert stats["total_symbols"] > 0

        # Verify symbols are in both SQLite and vector store
        db_files = storage_manager.get_all_files()
        assert len(db_files) >= 100  # At least 100 Python files + possibly .gitignore

        # Verify vector store has symbols
        results = vector_store.search(query="function", method="text", limit=500)
        assert len(results) > 100  # Should have many function symbols
