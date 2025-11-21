"""
Tests for types mode in fast_explore - type intelligence queries.

Following TDD: These tests define the type analysis interface BEFORE implementation.
They specify how to find type implementations, hierarchies, and usage patterns.
"""

import pytest
from miller.storage import StorageManager


@pytest.fixture
def storage_with_types():
    """Create storage with type relationship data for testing."""
    storage = StorageManager(db_path=":memory:")

    # Add test files
    storage.add_file("src/interfaces.py", "python", "", "hash1", 100)
    storage.add_file("src/implementations.py", "python", "", "hash2", 200)
    storage.add_file("src/services.py", "python", "", "hash3", 300)

    # Add symbols representing types and functions
    # Symbol data format matches storage.py schema:
    # (id, name, kind, language, file_path, start_line, start_col, end_line, end_col,
    #  start_byte, end_byte, signature, doc_comment, visibility, parent_id,
    #  semantic_group, confidence, content_type)
    symbols = [
        # Interface/base type
        ("sym_iuser", "IUser", "interface", "python", "src/interfaces.py", 1, 0, 10, 0, 0, 100,
         "class IUser(Protocol)", "User interface", "public", None, None, 1.0, None),

        # Implementations
        ("sym_user", "User", "class", "python", "src/implementations.py", 1, 0, 50, 0, 0, 500,
         "class User(IUser)", "User implementation", "public", None, None, 1.0, None),
        ("sym_admin", "AdminUser", "class", "python", "src/implementations.py", 55, 0, 100, 0, 510, 1000,
         "class AdminUser(User)", "Admin user", "public", None, None, 1.0, None),

        # Functions with type parameters/returns
        ("sym_get_user", "get_user", "function", "python", "src/services.py", 1, 0, 10, 0, 0, 100,
         "def get_user(id: int) -> IUser", "Get user by ID", "public", None, None, 1.0, None),
        ("sym_create_user", "create_user", "function", "python", "src/services.py", 15, 0, 30, 0, 150, 300,
         "def create_user(user: IUser) -> bool", "Create a user", "public", None, None, 1.0, None),
        ("sym_list_users", "list_users", "function", "python", "src/services.py", 35, 0, 50, 0, 350, 500,
         "def list_users() -> list[IUser]", "List all users", "public", None, None, 1.0, None),
    ]

    # Insert symbols using internal method
    storage.conn.executemany("""
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, start_col,
                            end_line, end_col, start_byte, end_byte, signature, doc_comment,
                            visibility, parent_id, semantic_group, confidence, content_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, symbols)

    # Add relationships
    # Format: (id, from_symbol_id, to_symbol_id, kind, file_path, line_number, confidence, metadata)
    relationships = [
        # User implements IUser
        ("rel1", "sym_user", "sym_iuser", "implements", "src/implementations.py", 1, 1.0, None),
        # AdminUser extends User
        ("rel2", "sym_admin", "sym_user", "extends", "src/implementations.py", 55, 1.0, None),
        # get_user returns IUser
        ("rel3", "sym_get_user", "sym_iuser", "returns", "src/services.py", 1, 1.0, None),
        # create_user takes IUser parameter
        ("rel4", "sym_create_user", "sym_iuser", "parameter", "src/services.py", 15, 1.0, None),
        # list_users returns IUser (generic)
        ("rel5", "sym_list_users", "sym_iuser", "returns", "src/services.py", 35, 1.0, None),
    ]

    storage.conn.executemany("""
        INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path,
                                  line_number, confidence, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, relationships)
    storage.conn.commit()

    yield storage
    storage.close()


class TestTypeIntelligenceQueries:
    """Test storage layer queries for type intelligence."""

    def test_find_type_implementations(self, storage_with_types):
        """Find classes that implement an interface."""
        impls = storage_with_types.find_type_implementations("IUser")

        assert len(impls) == 1
        assert impls[0]["name"] == "User"
        assert impls[0]["kind"] == "class"

    def test_find_type_hierarchy_children(self, storage_with_types):
        """Find types that extend a given type."""
        parents, children = storage_with_types.find_type_hierarchy("User")

        # User extends nothing directly (only implements IUser)
        # AdminUser extends User
        assert len(children) == 1
        assert children[0]["name"] == "AdminUser"

    def test_find_type_hierarchy_parents(self, storage_with_types):
        """Find types that a given type extends/implements."""
        parents, children = storage_with_types.find_type_hierarchy("AdminUser")

        # AdminUser extends User
        assert len(parents) == 1
        assert parents[0]["name"] == "User"

    def test_find_functions_returning_type(self, storage_with_types):
        """Find functions that return a specific type."""
        funcs = storage_with_types.find_functions_returning_type("IUser")

        assert len(funcs) == 2
        names = {f["name"] for f in funcs}
        assert "get_user" in names
        assert "list_users" in names

    def test_find_functions_with_parameter_type(self, storage_with_types):
        """Find functions that take a specific type as parameter."""
        funcs = storage_with_types.find_functions_with_parameter_type("IUser")

        assert len(funcs) == 1
        assert funcs[0]["name"] == "create_user"

    def test_find_type_implementations_empty(self, storage_with_types):
        """Return empty list for non-existent type."""
        impls = storage_with_types.find_type_implementations("NonExistent")
        assert impls == []


class TestFastExploreTypesMode:
    """Test fast_explore tool with types mode."""

    @pytest.mark.asyncio
    async def test_explore_types_returns_all_categories(self, storage_with_types):
        """Test that types mode returns implementations, hierarchy, returns, parameters."""
        # This test will drive the implementation of fast_explore types mode
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="types",
            type_name="IUser",
            storage=storage_with_types
        )

        assert "type_name" in result
        assert result["type_name"] == "IUser"
        assert "implementations" in result
        assert "hierarchy" in result
        assert "returns" in result
        assert "parameters" in result

    @pytest.mark.asyncio
    async def test_explore_types_finds_implementations(self, storage_with_types):
        """Test that types mode finds interface implementations."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="types",
            type_name="IUser",
            storage=storage_with_types
        )

        assert len(result["implementations"]) == 1
        assert result["implementations"][0]["name"] == "User"

    @pytest.mark.asyncio
    async def test_explore_types_finds_return_usages(self, storage_with_types):
        """Test that types mode finds functions returning the type."""
        from miller.tools.explore import fast_explore

        result = await fast_explore(
            mode="types",
            type_name="IUser",
            storage=storage_with_types
        )

        assert len(result["returns"]) == 2
        names = {r["name"] for r in result["returns"]}
        assert "get_user" in names
        assert "list_users" in names


class TestFastExploreMCPTool:
    """Test fast_explore registered as MCP tool."""

    @pytest.mark.asyncio
    async def test_fast_explore_tool_exists(self):
        """Test that fast_explore is registered as MCP tool."""
        from miller.server import mcp

        tools = await mcp.get_tools()
        tool_names = list(tools.keys())
        assert "fast_explore" in tool_names

    def test_fast_explore_exported(self):
        """Test that fast_explore is in __all__ exports."""
        from miller.server import __all__

        assert "fast_explore" in __all__
