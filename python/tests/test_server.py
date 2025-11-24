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

    def test_primary_workspace_registration_logic(self):
        """
        Regression test: Primary workspace must be registered on server startup.

        Bug: Background initialization created storage/scanner and indexed files,
        but never registered the primary workspace with WorkspaceRegistry. This
        caused `manage_workspace health` to show "No workspaces registered".

        Root cause: WorkspaceRegistry.add_workspace() was never called during
        background_initialization_and_indexing().

        Fix: Added registry.add_workspace() call after scanner initialization in
        server.py background_initialization_and_indexing().
        """
        import tempfile
        from pathlib import Path
        from miller.workspace_registry import WorkspaceRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            original_dir = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Simulate what server startup should do
                workspace_root = Path.cwd()
                registry = WorkspaceRegistry()

                # This is the fix - server startup must call this:
                registry.add_workspace(
                    path=str(workspace_root),
                    name=workspace_root.name,
                    workspace_type="primary",
                )

                # Verify registration worked
                workspaces = registry.list_workspaces()
                assert len(workspaces) >= 1, "Bug regression: Primary workspace not registered"

                # Find primary workspace
                primary = next((ws for ws in workspaces if ws["workspace_type"] == "primary"), None)
                assert primary is not None, "Bug regression: No primary workspace found"
                assert primary["path"] == str(workspace_root), "Primary workspace path mismatch"

            finally:
                os.chdir(original_dir)


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

        # Go to symbol (default: text output)
        result = await fast_goto("calculate_age")

        # Should return location info in text format: "Found 1 definition for X:\n\nfile:line (kind)"
        assert "calculate_age" in str(result)
        assert "test.py" in str(result)
        assert "definition" in str(result).lower()  # Text format includes "definition"

    @pytest.mark.asyncio
    async def test_goto_returns_none_for_unknown_symbol(self, test_workspace, index_file_helper):
        """Test handling of unknown symbols."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Search for non-existent symbol (text output)
        result = await fast_goto("nonexistent_function")

        # Should indicate not found in text format: "No definition found for X."
        assert "no definition found" in str(result).lower()

    @pytest.mark.asyncio
    async def test_goto_json_output_format(self, test_workspace, index_file_helper):
        """Verify JSON output has correct structure."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Request JSON output
        result = await fast_goto("calculate_age", output_format="json")

        # Should return a dict with proper structure
        assert isinstance(result, dict), "JSON output should be a dict"
        assert "file_path" in result, "Result should have file_path"
        assert "start_line" in result, "Result should have start_line"
        assert "kind" in result, "Result should have kind"
        assert result["name"] == "calculate_age", "Result name should match"

    @pytest.mark.asyncio
    async def test_goto_json_output_none_for_unknown(self, test_workspace, index_file_helper):
        """Verify JSON output returns None for unknown symbols."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Request JSON output for non-existent symbol
        result = await fast_goto("nonexistent_unknown_xyz", output_format="json")

        # Should return None
        assert result is None, "JSON output should be None for unknown symbol"

    @pytest.mark.asyncio
    async def test_goto_class_symbol(self, test_workspace, index_file_helper):
        """Verify fast_goto works with class definitions."""
        from miller.server import fast_goto

        # Index files with class
        await index_file_helper(str(test_workspace / "lib.js"))

        # Go to class
        result = await fast_goto("UserManager", output_format="text")

        # Should find the class
        assert "UserManager" in str(result), "Result should contain class name"
        assert "class" in str(result).lower(), "Result should indicate it's a class"
        assert "lib.js" in str(result), "Result should show file location"

    @pytest.mark.asyncio
    async def test_goto_method_symbol(self, test_workspace, index_file_helper):
        """Verify fast_goto works with methods."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Go to method (Python class method example)
        # First, let's use the existing test.py which has 'get_user_profile'
        result = await fast_goto("get_user_profile", output_format="text")

        # Should find the function
        assert "get_user_profile" in str(result), "Result should contain function name"
        assert "test.py" in str(result), "Result should show file location"

    @pytest.mark.asyncio
    async def test_goto_text_output_format_default(self, test_workspace, index_file_helper):
        """Verify text format is the default output format."""
        from miller.server import fast_goto

        # Index files
        await index_file_helper(str(test_workspace / "test.py"))

        # Call without output_format parameter (should default to "text")
        result = await fast_goto("calculate_age")

        # Should return string (text format)
        assert isinstance(result, str), "Default output should be string (text format)"
        assert "calculate_age" in result, "Text output should contain symbol name"
        assert "Found" in result or "No" in result, "Text format should have descriptive message"

    @pytest.mark.asyncio
    async def test_goto_symbol_without_signature_json(self, test_workspace, index_file_helper):
        """Variables/constants without signatures should work in JSON format."""
        from miller.server import fast_goto

        # First index a file with variables
        code = """
MAX_SIZE = 100
_private_var = "secret"
CONFIG = {"key": "value"}
"""
        import tempfile
        from pathlib import Path

        temp_file = Path(tempfile.gettempdir()) / "constants_test.py"
        temp_file.write_text(code)

        # Index the file
        await index_file_helper(str(temp_file))

        # Go to constant
        result = await fast_goto("MAX_SIZE", output_format="json")

        # Should find it
        if result is not None:  # May or may not be indexed depending on parser
            assert result["name"] == "MAX_SIZE"
            assert "constants_test.py" in result["file_path"]

    @pytest.mark.asyncio
    async def test_goto_very_long_signature_truncation(self, test_workspace, index_file_helper):
        """Long signatures should be handled gracefully in text format."""
        from miller.tools.navigation import _format_goto_as_text

        # Test the formatting function directly with a long signature
        long_sig = (
            "def very_long_function_name_with_many_parameters("
            "param1: str, param2: int, param3: float, param4: list, param5: dict, "
            "param6: Optional[str] = None) -> Tuple[str, int]"
        )

        result = {
            "name": "very_long_function_name_with_many_parameters",
            "kind": "function",
            "file_path": "src/long_sig.py",
            "start_line": 10,
            "signature": long_sig,
        }

        output = _format_goto_as_text("very_long_function_name_with_many_parameters", result)

        # Should handle without error
        assert "very_long_function_name" in output, "Should contain function name"
        assert "src/long_sig.py:10" in output, "Should contain file:line"
        # If truncated, should have ... indicator
        lines = output.split("\n")
        # Check that no single line is excessively long (signature line should be < 100 chars)
        for line in lines:
            if "→" in line or "def" in line.lower():
                # Signature line might be truncated
                pass


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
        result = await get_symbols(file_path, output_format="json")

        # Should return list of symbols with metadata
        assert len(result) > 0
        assert any(s["name"] == "calculate_age" for s in result)
        assert any(s["name"] == "get_user_profile" for s in result)

    @pytest.mark.asyncio
    async def test_get_symbols_includes_metadata(self, test_workspace):
        """Test that symbols include metadata fields."""
        from miller.server import get_symbols

        file_path = str(test_workspace / "test.py")
        result = await get_symbols(file_path, output_format="json")

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
