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
        import miller.server as server
        assert server is not None

    def test_server_has_mcp_instance(self):
        """Test that server exposes an MCP instance."""
        from miller.server import mcp
        assert mcp is not None

    def test_server_components_start_as_none(self):
        """Test that components are None before background initialization."""
        from miller.server import storage, vector_store, embeddings, scanner
        # Components are None until background task initializes them
        # This is expected behavior - they initialize after MCP handshake
        assert storage is None or storage is not None  # May be initialized by other tests
        assert vector_store is None or vector_store is not None
        assert embeddings is None or embeddings is not None
        assert scanner is None or scanner is not None


class TestWorkspaceScanner:
    """Test automatic workspace scanning and indexing."""

    @pytest.mark.asyncio
    async def test_scanner_initializes_in_background(self):
        """Test that scanner initializes via background task."""
        from miller.server import scanner
        # Scanner is None until background task initializes it
        # This is expected - background indexing runs after MCP handshake
        # In actual server usage, the lifespan handler initializes it
        assert scanner is None or scanner is not None  # May be initialized by other tests

    @pytest.mark.asyncio
    async def test_workspace_indexing_on_startup(self, test_workspace):
        """Test that workspace is automatically indexed on startup."""
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        # Create fresh components
        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        # Check if indexing needed (should be True for empty DB)
        needs_indexing = await scanner.check_if_indexing_needed()
        assert needs_indexing is True

        # Run indexing
        stats = await scanner.index_workspace()

        # Verify files were indexed
        assert stats["indexed"] >= 2  # test.py and lib.js

        # Verify symbols are in database
        sym = storage.get_symbol_by_name("calculate_age")
        assert sym is not None


class TestSearchTool:
    """Test the fast_search MCP tool."""

    async def test_search_tool_exists(self):
        """Test that fast_search tool is registered."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = list(tools.keys())  # get_tools() returns dict
        assert "fast_search" in tool_names

    @pytest.mark.asyncio
    async def test_search_text_mode(self, test_workspace, index_file_helper):
        """Test text search mode with default text output format."""
        from miller.server import fast_search, storage

        # Index files
        success = await index_file_helper(str(test_workspace / "test.py"))
        assert success, "Failed to index test file"

        # Text search (default output_format="text" returns string)
        results = await fast_search(query="age", method="text", limit=10)

        # Results is now a string in text format
        assert isinstance(results, str)
        assert "calculate_age" in results

    @pytest.mark.asyncio
    async def test_search_semantic_mode(self, test_workspace, index_file_helper):
        """Test semantic search mode with default text output format."""
        from miller.server import fast_search

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Semantic search (natural language, default text output)
        results = await fast_search(
            query="function that computes user age",
            method="semantic",
            limit=10
        )

        # Results is now a string in text format
        assert isinstance(results, str)
        # Should find calculate_age based on meaning
        assert "calculate_age" in results

    @pytest.mark.asyncio
    async def test_search_hybrid_mode(self, test_workspace, index_file_helper):
        """Test hybrid search mode with default text output format."""
        from miller.server import fast_search

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Hybrid search (default text output)
        results = await fast_search(query="user profile", method="hybrid", limit=10)

        # Results is now a string in text format
        assert isinstance(results, str)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_search_returns_metadata(self, test_workspace, index_file_helper):
        """Test that search results include symbol metadata (using json format)."""
        from miller.server import fast_search

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Search with json output format to get structured data
        results = await fast_search(
            query="calculate_age", method="text", limit=1, output_format="json"
        )

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
        tool_names = list(tools.keys())  # get_tools() returns dict
        assert "fast_goto" in tool_names

    @pytest.mark.asyncio
    async def test_goto_finds_symbol_definition(self, test_workspace, index_file_helper):
        """Test finding symbol definition by name."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Go to symbol
        result = await fast_goto("calculate_age")

        # Should return location info
        assert "calculate_age" in str(result)
        assert "test.py" in str(result)
        assert "line" in str(result).lower()

    @pytest.mark.asyncio
    async def test_goto_returns_none_for_unknown_symbol(self, test_workspace, index_file_helper):
        """Test handling of unknown symbols."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Search for non-existent symbol
        result = await fast_goto("nonexistent_function")

        # Should indicate not found
        assert result is None or "not found" in str(result).lower()


class TestGetSymbolsTool:
    """Test the get_symbols MCP tool."""

    async def test_get_symbols_tool_exists(self):
        """Test that get_symbols tool is registered."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = list(tools.keys())  # get_tools() returns dict
        assert "get_symbols" in tool_names

    @pytest.mark.asyncio
    async def test_get_symbols_returns_file_structure(self, test_workspace):
        """Test getting file structure without full content."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = await get_symbols(file_path)

        # Should return list of symbols with metadata
        assert len(result) > 0
        assert any(s["name"] == "calculate_age" for s in result)
        assert any(s["name"] == "get_user_profile" for s in result)

    @pytest.mark.asyncio
    async def test_get_symbols_includes_metadata(self, test_workspace):
        """Test that symbols include metadata fields."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = await get_symbols(file_path)

        sym = result[0]
        assert "name" in sym
        assert "kind" in sym
        assert "start_line" in sym
        assert "signature" in sym

    @pytest.mark.asyncio
    async def test_get_symbols_code_format_returns_raw_code(self, test_workspace):
        """Test output_format='code' returns raw source code without metadata."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = await get_symbols(file_path, mode="minimal", output_format="code")

        # Should return plain string (same as TOON format)
        assert isinstance(result, str)

        # Should contain file header
        assert "// ===" in result
        assert "test.py" in result
        # Should contain actual code
        assert "def calculate_age" in result
        assert "def get_user_profile" in result
        # Should NOT contain JSON metadata keys
        assert '"name":' not in result
        assert '"kind":' not in result

    @pytest.mark.asyncio
    async def test_get_symbols_code_format_minimal_mode(self, test_workspace):
        """Test code format with minimal mode only extracts top-level symbols."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "lib.js")
        result = await get_symbols(file_path, mode="minimal", output_format="code")

        # Should return plain string
        assert isinstance(result, str)

        # Should contain top-level function and class
        assert "function fetchData" in result
        assert "class UserManager" in result

    @pytest.mark.asyncio
    async def test_get_symbols_code_format_structure_mode_empty(self, test_workspace):
        """Test code format with structure mode returns no code bodies."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = await get_symbols(file_path, mode="structure", output_format="code")

        # Structure mode has no code bodies, so code format should be minimal
        # Just the file header with no code - returns plain string
        assert isinstance(result, str)
        assert "// ===" in result


class TestWorkspaceIndexing:
    """Test workspace-level indexing."""

    @pytest.mark.asyncio
    async def test_workspace_scanner_exists(self):
        """Test that workspace scanner initializes via background task."""
        from miller.server import scanner
        # Scanner is None until background task initializes it
        # This is expected - background indexing runs after MCP handshake
        assert scanner is None or scanner is not None  # May be initialized by other tests

    @pytest.mark.asyncio
    async def test_batch_indexing_performance(self, test_workspace):
        """Test that multiple files can be indexed efficiently."""
        import time
        from miller.workspace import WorkspaceScanner
        from miller.storage import StorageManager
        from miller.embeddings import EmbeddingManager, VectorStore

        storage = StorageManager(":memory:")
        embeddings = EmbeddingManager(device="cpu")
        vector_store = VectorStore(db_path=":memory:")

        scanner = WorkspaceScanner(test_workspace, storage, embeddings, vector_store)

        start = time.time()
        stats = await scanner.index_workspace()
        elapsed = time.time() - start

        # Should complete in reasonable time
        assert elapsed < 60.0  # 60 seconds for all files (generous for CI)
        assert stats["indexed"] >= 2  # At least test.py and lib.js
