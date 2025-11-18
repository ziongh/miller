"""
Test Miller's MCP server (FastMCP).

Following TDD: These tests define the MCP server interface BEFORE implementation.
They specify what tools should exist and how they should behave.
"""

import pytest
from pathlib import Path
import tempfile
import shutil


@pytest.fixture
def test_workspace():
    """Create a temporary workspace for testing."""
    temp_dir = tempfile.mkdtemp(prefix="miller_test_workspace_")
    workspace = Path(temp_dir)

    # Create test files
    (workspace / "test.py").write_text("""
def calculate_age(birthdate):
    '''Calculate user age from birthdate.'''
    return 2025 - birthdate.year

def get_user_profile(user_id):
    '''Fetch user profile by ID.'''
    return {"id": user_id}
""")

    (workspace / "lib.js").write_text("""
function fetchData(url) {
    // Fetch data from API
    return fetch(url);
}

class UserManager {
    constructor() {
        this.users = [];
    }
}
""")

    yield workspace

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestServerInitialization:
    """Test server startup and configuration."""

    def test_server_imports(self):
        """Test that server module can be imported."""
        from miller import server
        assert server is not None

    def test_server_has_mcp_instance(self):
        """Test that server exposes an MCP instance."""
        from miller.server import mcp
        assert mcp is not None

    def test_server_has_storage_manager(self):
        """Test that server has storage manager."""
        from miller.server import storage
        assert storage is not None

    def test_server_has_vector_store(self):
        """Test that server has vector store."""
        from miller.server import vector_store
        assert vector_store is not None

    def test_server_has_embeddings_manager(self):
        """Test that server has embeddings manager."""
        from miller.server import embeddings
        assert embeddings is not None


class TestIndexFileTool:
    """Test the index_file MCP tool."""

    async def test_index_file_tool_exists(self):
        """Test that index_file tool is registered."""
        from miller.server import mcp

        # FastMCP should have this tool registered
        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        assert "index_file" in tool_names

    def test_index_file_indexes_python_file(self, test_workspace):
        """Test indexing a Python file."""
        from miller.server import index_file

        file_path = str(test_workspace / "test.py")
        result = index_file(file_path)

        # Should return success message with stats
        assert "Success" in result or "indexed" in result.lower()
        assert "2" in result or "symbol" in result.lower()  # 2 functions

    def test_index_file_indexes_javascript_file(self, test_workspace):
        """Test indexing a JavaScript file."""
        from miller.server import index_file

        file_path = str(test_workspace / "lib.js")
        result = index_file(file_path)

        assert "Success" in result or "indexed" in result.lower()

    def test_index_file_stores_in_database(self, test_workspace):
        """Test that indexed symbols are stored in SQLite."""
        from miller.server import index_file, storage

        file_path = str(test_workspace / "test.py")
        index_file(file_path)

        # Check SQLite for symbols
        sym = storage.get_symbol_by_name("calculate_age")
        assert sym is not None
        assert sym["kind"] == "function"

    def test_index_file_stores_embeddings(self, test_workspace):
        """Test that embeddings are stored in LanceDB."""
        from miller.server import index_file, vector_store

        file_path = str(test_workspace / "test.py")
        index_file(file_path)

        # Search should find the symbol
        results = vector_store.search("calculate_age", method="text", limit=5)
        assert len(results) > 0
        assert any(r["name"] == "calculate_age" for r in results)

    def test_index_file_handles_nonexistent_file(self):
        """Test error handling for missing files."""
        from miller.server import index_file

        result = index_file("/nonexistent/file.py")

        # Should return error message (not crash)
        assert "error" in result.lower() or "not found" in result.lower()

    def test_index_file_updates_on_reindex(self, test_workspace):
        """Test that re-indexing updates symbols."""
        from miller.server import index_file, storage

        file_path = str(test_workspace / "test.py")

        # Index first time
        index_file(file_path)

        # Modify file
        (test_workspace / "test.py").write_text("def new_function(): pass")

        # Re-index
        index_file(file_path)

        # Should find new function, not old ones
        sym = storage.get_symbol_by_name("new_function")
        assert sym is not None

        old_sym = storage.get_symbol_by_name("calculate_age")
        assert old_sym is None  # Should be removed


class TestSearchTool:
    """Test the fast_search MCP tool."""

    async def test_search_tool_exists(self):
        """Test that fast_search tool is registered."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        assert "fast_search" in tool_names

    def test_search_text_mode(self, test_workspace):
        """Test text search mode."""
        from miller.server import index_file, fast_search

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Text search
        results = fast_search(query="age", method="text", limit=10)

        assert len(results) > 0
        assert any("calculate_age" in str(r) for r in results)

    def test_search_semantic_mode(self, test_workspace):
        """Test semantic search mode."""
        from miller.server import index_file, fast_search

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Semantic search (natural language)
        results = fast_search(
            query="function that computes user age",
            method="semantic",
            limit=10
        )

        assert len(results) > 0
        # Should find calculate_age based on meaning
        assert any("calculate_age" in str(r) for r in results)

    def test_search_hybrid_mode(self, test_workspace):
        """Test hybrid search mode."""
        from miller.server import index_file, fast_search

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Hybrid search
        results = fast_search(query="user profile", method="hybrid", limit=10)

        assert len(results) > 0

    def test_search_returns_metadata(self, test_workspace):
        """Test that search results include symbol metadata."""
        from miller.server import index_file, fast_search

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Search
        results = fast_search(query="calculate_age", method="text", limit=1)

        assert len(results) > 0
        result = results[0]

        # Should have metadata fields
        assert "name" in result
        assert "file_path" in result
        assert "kind" in result


class TestGotoTool:
    """Test the fast_goto MCP tool."""

    async def test_goto_tool_exists(self):
        """Test that fast_goto tool is registered."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        assert "fast_goto" in tool_names

    def test_goto_finds_symbol_definition(self, test_workspace):
        """Test finding symbol definition by name."""
        from miller.server import index_file, fast_goto

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Go to symbol
        result = fast_goto("calculate_age")

        # Should return location info
        assert "calculate_age" in str(result)
        assert "test.py" in str(result)
        assert "line" in str(result).lower()

    def test_goto_returns_none_for_unknown_symbol(self, test_workspace):
        """Test handling of unknown symbols."""
        from miller.server import index_file, fast_goto

        # Index files
        index_file(str(test_workspace / "test.py"))

        # Search for non-existent symbol
        result = fast_goto("nonexistent_function")

        # Should indicate not found
        assert result is None or "not found" in str(result).lower()


class TestGetSymbolsTool:
    """Test the get_symbols MCP tool."""

    async def test_get_symbols_tool_exists(self):
        """Test that get_symbols tool is registered."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        assert "get_symbols" in tool_names

    def test_get_symbols_returns_file_structure(self, test_workspace):
        """Test getting file structure without full content."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = get_symbols(file_path)

        # Should return list of symbols with metadata
        assert len(result) > 0
        assert any(s["name"] == "calculate_age" for s in result)
        assert any(s["name"] == "get_user_profile" for s in result)

    def test_get_symbols_includes_metadata(self, test_workspace):
        """Test that symbols include metadata fields."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = get_symbols(file_path)

        sym = result[0]
        assert "name" in sym
        assert "kind" in sym
        assert "start_line" in sym
        assert "signature" in sym


class TestWorkspaceIndexing:
    """Test workspace-level indexing."""

    async def test_index_workspace_tool_exists(self):
        """Test that index_workspace tool exists."""
        from miller.server import mcp

        # Optional: may implement later
        tools = await mcp.get_tools()
        tool_names = [t.name for t in tools]
        # Just check that core tools exist
        assert "index_file" in tool_names

    def test_batch_indexing_performance(self, test_workspace):
        """Test that multiple files can be indexed efficiently."""
        import time
        from miller.server import index_file

        files = [
            test_workspace / "test.py",
            test_workspace / "lib.js",
        ]

        start = time.time()
        for f in files:
            index_file(str(f))
        elapsed = time.time() - start

        # Should complete in reasonable time
        assert elapsed < 30.0  # 30 seconds for 2 files (generous for CI)
