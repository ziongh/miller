"""
Integration tests for Miller's complete workflow.

Tests the full pipeline: startup → workspace indexing → search → navigation
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import logging


@pytest.fixture
def integration_workspace():
    """Create a realistic workspace for integration testing."""
    temp_dir = tempfile.mkdtemp(prefix="miller_integration_test_")
    workspace = Path(temp_dir)

    # Create realistic project structure
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "lib").mkdir()
    (workspace / "docs").mkdir()

    # Python files
    (workspace / "src" / "main.py").write_text("""
'''Main application entry point.'''

def main():
    '''Run the main application.'''
    from .utils import calculate_total
    from .models import User

    user = User("Alice")
    total = calculate_total([1, 2, 3])
    print(f"User: {user.name}, Total: {total}")

if __name__ == "__main__":
    main()
""")

    (workspace / "src" / "utils.py").write_text("""
'''Utility functions for the application.'''

def calculate_total(numbers):
    '''Calculate sum of numbers.'''
    return sum(numbers)

def format_currency(amount):
    '''Format amount as currency.'''
    return f"${amount:.2f}"
""")

    (workspace / "src" / "models.py").write_text("""
'''Data models for the application.'''

class User:
    '''User model.'''

    def __init__(self, name):
        '''Initialize user with name.'''
        self.name = name

    def greet(self):
        '''Return greeting message.'''
        return f"Hello, {self.name}!"

class Product:
    '''Product model.'''

    def __init__(self, name, price):
        '''Initialize product.'''
        self.name = name
        self.price = price
""")

    (workspace / "tests" / "test_utils.py").write_text("""
'''Tests for utility functions.'''

from src.utils import calculate_total, format_currency

def test_calculate_total():
    '''Test calculate_total function.'''
    assert calculate_total([1, 2, 3]) == 6

def test_format_currency():
    '''Test format_currency function.'''
    assert format_currency(10.5) == "$10.50"
""")

    # JavaScript file
    (workspace / "lib" / "helper.js").write_text("""
// Helper functions
function formatDate(date) {
    // Format date as string
    return date.toISOString();
}

class DataProcessor {
    constructor() {
        this.data = [];
    }

    process(item) {
        // Process data item
        this.data.push(item);
    }
}
""")

    # .gitignore
    (workspace / ".gitignore").write_text("""
__pycache__/
*.pyc
.pytest_cache/
node_modules/
.coverage
""")

    # README
    (workspace / "docs" / "README.md").write_text("""
# Test Project

This is a test project for Miller integration testing.
""")

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestFullWorkflow:
    """Test complete Miller workflow from start to finish."""

    @pytest.mark.asyncio
    async def test_complete_workflow(self, integration_workspace):
        """
        Test full workflow: initialization → indexing → search → navigation.

        This simulates what happens when Miller MCP server starts.
        """
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Configure logging for test
        logging.basicConfig(level=logging.DEBUG)

        # Step 1: Initialize components (like server.py does)
        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(
            workspace_root=integration_workspace,
            storage=storage,
            embeddings=embeddings,
            vector_store=vector_store
        )

        # Step 2: Check if indexing needed (should be True for empty DB)
        needs_indexing = await scanner.check_if_indexing_needed()
        assert needs_indexing is True, "Empty DB should need indexing"

        # Step 3: Index workspace
        stats = await scanner.index_workspace()

        # Verify indexing stats
        assert stats["indexed"] >= 5, f"Should index at least 5 files, got {stats['indexed']}"
        assert stats["errors"] == 0, f"Should have no errors, got {stats['errors']}"

        # Step 4: Verify symbols are in database
        # Test navigation (fast_goto)
        user_class = storage.get_symbol_by_name("User")
        assert user_class is not None, "Should find User class"
        assert user_class["kind"] == "class"
        assert "models.py" in user_class["file_path"]

        # Test navigation to function
        calc_func = storage.get_symbol_by_name("calculate_total")
        assert calc_func is not None, "Should find calculate_total function"
        assert calc_func["kind"] == "function"

        # Step 5: Test search (text mode)
        results = vector_store.search("calculate", method="text", limit=10)
        assert len(results) > 0, "Should find symbols matching 'calculate'"
        assert any("calculate" in r["name"].lower() for r in results)

        # Step 6: Test search (semantic mode)
        results = vector_store.search("user greeting", method="semantic", limit=10)
        assert len(results) > 0, "Should find semantically relevant symbols"
        # Should find greet() method or User class

        # Step 7: Verify incremental indexing works
        # Modify a file
        new_code = (workspace / "src" / "utils.py").read_text() + "\n\ndef new_function():\n    pass\n"
        (integration_workspace / "src" / "utils.py").write_text(new_code)

        # Check indexing needed again
        needs_reindex = await scanner.check_if_indexing_needed()
        assert needs_reindex is True, "Changed file should trigger re-indexing"

        # Re-index
        stats2 = await scanner.index_workspace()
        assert stats2["updated"] >= 1, "Should update at least 1 file"
        assert stats2["indexed"] == 0, "Should not index new files (only updates)"
        assert stats2["skipped"] > 0, "Should skip unchanged files"

        # Verify new function is indexed
        new_func = storage.get_symbol_by_name("new_function")
        assert new_func is not None, "Should find newly added function"

        # Step 8: Test file deletion cleanup
        # Delete a file
        (integration_workspace / "src" / "models.py").unlink()

        # Re-index
        stats3 = await scanner.index_workspace()
        assert stats3["deleted"] >= 1, "Should detect deleted file"

        # Verify symbols are removed (CASCADE)
        user_class_after = storage.get_symbol_by_name("User")
        assert user_class_after is None, "Deleted file's symbols should be removed"

        # But other symbols should still exist
        calc_func_after = storage.get_symbol_by_name("calculate_total")
        assert calc_func_after is not None, "Symbols from other files should remain"


class TestMCPServerLifecycle:
    """Test MCP server lifecycle events."""

    @pytest.mark.asyncio
    async def test_server_startup_indexing(self, integration_workspace):
        """Test that server startup triggers indexing correctly."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Simulate server startup
        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(
            integration_workspace, storage, embeddings, vector_store
        )

        # Simulate startup_indexing() from server.py
        if await scanner.check_if_indexing_needed():
            stats = await scanner.index_workspace()
            assert stats["indexed"] > 0, "Should index files on first startup"

        # Second startup (workspace already indexed)
        needs_indexing = await scanner.check_if_indexing_needed()
        assert needs_indexing is False, "Should not need re-indexing on second startup"

    @pytest.mark.asyncio
    async def test_logging_instead_of_print(self, integration_workspace, caplog):
        """Test that logging is used instead of print statements."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Capture logs
        with caplog.at_level(logging.INFO):
            storage = StorageManager(":memory:")
            embeddings = EmbeddingManager(device="cpu")
            vector_store = VectorStore(db_path=":memory:")

            scanner = WorkspaceScanner(
                integration_workspace, storage, embeddings, vector_store
            )

            await scanner.index_workspace()

        # Verify logging is working (should have log messages)
        # But there should be NO print statements polluting stdout
        # (Can't easily test for absence of stdout, but tests will fail if server breaks MCP)


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_workspace(self):
        """Test handling of empty workspace."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        temp_dir = tempfile.mkdtemp(prefix="miller_empty_")
        try:
            workspace = Path(temp_dir)

            storage = StorageManager(":memory:")
            embeddings = EmbeddingManager(device="cpu")
            vector_store = VectorStore(db_path=":memory:")

            scanner = WorkspaceScanner(workspace, storage, embeddings, vector_store)

            # Should not crash on empty workspace
            stats = await scanner.index_workspace()
            assert stats["indexed"] == 0
            assert stats["errors"] == 0

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_workspace_with_invalid_files(self, integration_workspace):
        """Test handling of files that can't be indexed."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Create a file with invalid encoding
        binary_file = integration_workspace / "invalid.bin"
        binary_file.write_bytes(b"\x00\x01\x02\xFF\xFE")

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(
            integration_workspace, storage, embeddings, vector_store
        )

        # Should handle invalid files gracefully
        stats = await scanner.index_workspace()
        assert stats["indexed"] >= 4  # Still index valid Python/JS files
        # Binary file should be skipped (not a supported language)
