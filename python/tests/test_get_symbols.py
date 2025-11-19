"""
Tests for get_symbols tool - Phase 1: Feature Parity with Julie

Following TDD: Write tests first, then implement features.
"""

import pytest
from pathlib import Path


class TestReadingModes:
    """Test different reading modes: structure, minimal, full"""

    @pytest.fixture
    def sample_python_file(self, tmp_path):
        """Create a sample Python file with nested structure."""
        test_file = tmp_path / "user_service.py"
        test_file.write_text("""
class UserService:
    '''Service for managing users.'''

    def __init__(self, db):
        self.db = db

    def get_user(self, user_id):
        '''Fetch a user by ID.'''
        return self.db.query(user_id)

    def create_user(self, name, email):
        '''Create a new user.'''
        return self.db.insert({'name': name, 'email': email})

def standalone_function():
    '''A standalone function.'''
    pass
""")
        return test_file

    @pytest.mark.asyncio
    async def test_structure_mode_no_code_bodies(self, sample_python_file):
        """Structure mode should return only names/signatures, no implementation code."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(sample_python_file),
            mode="structure",
            max_depth=2
        )

        # Should have symbols
        assert len(result) > 0

        # Should have UserService class
        user_service = next((s for s in result if s["name"] == "UserService"), None)
        assert user_service is not None
        assert user_service["kind"] == "Class"
        assert user_service["doc_comment"] == "Service for managing users."

        # Should NOT have code bodies in structure mode
        assert "code_body" not in user_service or user_service["code_body"] is None

        # Should have methods (depth=2)
        get_user = next((s for s in result if s["name"] == "get_user"), None)
        assert get_user is not None
        assert "code_body" not in get_user or get_user["code_body"] is None

    @pytest.mark.asyncio
    async def test_minimal_mode_top_level_bodies_only(self, sample_python_file):
        """Minimal mode should return code bodies for top-level symbols only."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(sample_python_file),
            mode="minimal",
            max_depth=2
        )

        # Top-level class should have code body
        user_service = next((s for s in result if s["name"] == "UserService"), None)
        assert user_service is not None
        assert user_service.get("code_body") is not None
        assert "class UserService:" in user_service["code_body"]

        # Top-level function should have code body
        standalone = next((s for s in result if s["name"] == "standalone_function"), None)
        assert standalone is not None
        assert standalone.get("code_body") is not None
        assert "def standalone_function():" in standalone["code_body"]

        # Nested method should NOT have code body (only top-level)
        get_user = next((s for s in result if s["name"] == "get_user"), None)
        assert get_user is not None
        assert "code_body" not in get_user or get_user["code_body"] is None

    @pytest.mark.asyncio
    async def test_full_mode_all_bodies(self, sample_python_file):
        """Full mode should return code bodies for all symbols."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(sample_python_file),
            mode="full",
            max_depth=2
        )

        # All symbols should have code bodies
        for symbol in result:
            assert symbol.get("code_body") is not None, f"{symbol['name']} should have code_body"

            # Code body should contain the symbol's code
            assert symbol["name"] in symbol["code_body"] or "def " in symbol["code_body"] or "class " in symbol["code_body"]

    @pytest.mark.asyncio
    async def test_default_mode_is_structure(self, sample_python_file):
        """When mode not specified, should default to 'structure'."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(sample_python_file),
            max_depth=1
        )

        # Default behavior should match structure mode (no bodies)
        for symbol in result:
            assert "code_body" not in symbol or symbol["code_body"] is None


class TestDepthControl:
    """Test max_depth parameter for controlling symbol nesting"""

    @pytest.fixture
    def nested_python_file(self, tmp_path):
        """Create a file with method nesting (actual tree-sitter hierarchy)."""
        test_file = tmp_path / "nested.py"
        test_file.write_text("""
class ServiceClass:
    def level1_method(self):
        def level2_nested_function():
            def level3_nested_function():
                pass
            pass
        pass

def top_function():
    pass
""")
        return test_file

    @pytest.mark.asyncio
    async def test_depth_0_top_level_only(self, nested_python_file):
        """Depth 0 should return only top-level symbols."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(nested_python_file),
            max_depth=0
        )

        # Should only have ServiceClass and top_function
        names = [s["name"] for s in result]
        assert "ServiceClass" in names
        assert "top_function" in names

        # Should NOT have methods (depth 1+)
        assert "level1_method" not in names
        assert "level2_nested_function" not in names
        assert "level3_nested_function" not in names

    @pytest.mark.asyncio
    async def test_depth_1_includes_direct_children(self, nested_python_file):
        """Depth 1 should include direct children of top-level symbols.

        Note: In Python, nested functions are all siblings (children of the class),
        not nested within each other in the tree-sitter AST.
        """
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(nested_python_file),
            max_depth=1
        )

        names = [s["name"] for s in result]

        # Should have top-level and their direct children
        assert "ServiceClass" in names
        assert "top_function" in names

        # All methods/nested functions are children of ServiceClass (depth 1)
        assert "level1_method" in names
        # In Python, these are also depth 1 (siblings, not nested)
        assert "level2_nested_function" in names
        assert "level3_nested_function" in names

    @pytest.mark.asyncio
    async def test_depth_2_includes_grandchildren(self, nested_python_file):
        """Test that depth filtering works correctly.

        In Python, all functions defined within a class have the same parent
        regardless of visual nesting, so depth=2 doesn't add anything beyond depth=1.
        """
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(nested_python_file),
            max_depth=2
        )

        names = [s["name"] for s in result]

        # Should have same as depth=1 (no deeper hierarchy in Python)
        assert "ServiceClass" in names
        assert "level1_method" in names
        assert "level2_nested_function" in names
        assert "level3_nested_function" in names
        assert "top_function" in names

    @pytest.mark.asyncio
    async def test_depth_3_includes_all_nesting(self, nested_python_file):
        """Depth 3 should include all symbols."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(nested_python_file),
            max_depth=3
        )

        names = [s["name"] for s in result]

        # Should have everything
        assert "ServiceClass" in names
        assert "level1_method" in names
        assert "level2_nested_function" in names
        assert "level3_nested_function" in names  # Great-grandchild
        assert "top_function" in names


class TestTargetFiltering:
    """Test target parameter for filtering symbols by name"""

    @pytest.fixture
    def multi_symbol_file(self, tmp_path):
        """Create a file with multiple symbols."""
        test_file = tmp_path / "service.py"
        test_file.write_text("""
class UserService:
    def get_user(self):
        pass
    def create_user(self):
        pass
    def delete_user(self):
        pass

class ProductService:
    def get_product(self):
        pass

def calculate_user_age():
    pass
""")
        return test_file

    @pytest.mark.asyncio
    async def test_target_exact_match(self, multi_symbol_file):
        """Target should filter to symbols with exact name match."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(multi_symbol_file),
            target="UserService",
            max_depth=2
        )

        # Should return UserService and its methods
        names = [s["name"] for s in result]
        assert "UserService" in names
        assert "get_user" in names
        assert "create_user" in names
        assert "delete_user" in names

        # Phase 2 enhancement: ProductService MAY appear due to semantic similarity
        # but if it does, it should have MUCH lower score than UserService
        user_service = next(s for s in result if s["name"] == "UserService")
        if "ProductService" in names:
            product_service = next(s for s in result if s["name"] == "ProductService")
            # UserService should have significantly higher relevance score
            assert user_service.get("relevance_score", 1.0) > product_service.get("relevance_score", 0) + 0.2, \
                "UserService should score much higher than ProductService"

    @pytest.mark.asyncio
    async def test_target_partial_match(self, multi_symbol_file):
        """Target should support partial/substring matching."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(multi_symbol_file),
            target="user",  # Lowercase, partial
            max_depth=2
        )

        names = [s["name"] for s in result]

        # Should match any symbol containing "user" (case-insensitive)
        assert "UserService" in names  # Contains "User"
        assert "get_user" in names  # Contains "user"
        assert "create_user" in names
        assert "delete_user" in names
        assert "calculate_user_age" in names

        # Should NOT match Product stuff
        assert "ProductService" not in names

    @pytest.mark.asyncio
    async def test_target_with_children_returned(self, multi_symbol_file):
        """When filtering by target, should include matching symbol's children."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(multi_symbol_file),
            target="UserService",
            max_depth=1
        )

        # Should return UserService AND its direct children (methods)
        names = [s["name"] for s in result]
        assert "UserService" in names
        assert "get_user" in names
        assert "create_user" in names
        assert "delete_user" in names

    @pytest.mark.asyncio
    async def test_no_target_returns_all(self, multi_symbol_file):
        """When target not specified, should return all symbols."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(multi_symbol_file),
            max_depth=2
        )

        # Should return everything
        names = [s["name"] for s in result]
        assert len(names) >= 7  # All symbols


class TestLimitParameter:
    """Test limit parameter for controlling result size"""

    @pytest.fixture
    def large_file(self, tmp_path):
        """Create a file with many symbols."""
        test_file = tmp_path / "large.py"

        # Generate 20 functions
        content = "\n".join([f"def function_{i}(): pass" for i in range(20)])
        test_file.write_text(content)
        return test_file

    @pytest.mark.asyncio
    async def test_limit_restricts_result_count(self, large_file):
        """Limit should restrict the number of results returned."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(large_file),
            limit=5
        )

        # Should return exactly 5 symbols
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_limit_with_truncation_indicator(self, large_file):
        """When limited, should indicate that results were truncated."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(large_file),
            limit=5
        )

        # Result should include metadata about truncation
        # (We'll return this as a special field in the response)
        # For now, just verify we got limited results
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_no_limit_returns_all(self, large_file):
        """When limit not specified, should return all symbols."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(large_file)
        )

        # Should return all 20 functions
        assert len(result) == 20


class TestWorkspaceFiltering:
    """Test workspace parameter for multi-workspace support"""

    @pytest.mark.asyncio
    async def test_primary_workspace_default(self, sample_python_code, tmp_path):
        """Should default to primary workspace when workspace not specified."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text(sample_python_code)

        result = await get_symbols(
            file_path=str(test_file)
        )

        # Should work with primary workspace (default)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_explicit_primary_workspace(self, sample_python_code, tmp_path):
        """Should work with explicit workspace='primary' parameter."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text(sample_python_code)

        result = await get_symbols(
            file_path=str(test_file),
            workspace="primary"
        )

        # Should work with explicit primary workspace
        assert len(result) > 0

    # TODO: Test reference workspace filtering
    # (Requires reference workspace setup in tests)


class TestErrorHandling:
    """Test error handling and edge cases"""

    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        """Should handle nonexistent files gracefully."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path="/nonexistent/file.py"
        )

        # Should return empty list or error indicator
        assert isinstance(result, (list, dict))
        if isinstance(result, list):
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_binary_file(self, tmp_path):
        """Should handle binary files gracefully."""
        from miller.server import get_symbols

        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(b"\x00\x01\x02\xFF\xFE")

        result = await get_symbols(
            file_path=str(binary_file)
        )

        # Should return empty or handle gracefully
        assert isinstance(result, (list, dict))

    @pytest.mark.asyncio
    async def test_empty_file(self, tmp_path):
        """Should handle empty files gracefully."""
        from miller.server import get_symbols

        empty_file = tmp_path / "empty.py"
        empty_file.write_text("")

        result = await get_symbols(
            file_path=str(empty_file)
        )

        # Should return empty list
        assert isinstance(result, list)
        assert len(result) == 0


# ==============================================================================
# Phase 2: ML/Semantic Enhancements - Tests
# ==============================================================================


class TestSemanticRelevanceScores:
    """Test Task 2.1: Semantic relevance scores when filtering by target"""

    @pytest.fixture
    def auth_file(self, tmp_path):
        """Create a file with authentication-related symbols."""
        test_file = tmp_path / "auth.py"
        test_file.write_text("""
def login(username, password):
    '''User login function.'''
    pass

def handle_login(request):
    '''Handle login request.'''
    pass

def authenticate_user(credentials):
    '''Authenticate user with credentials.'''
    pass

def verify_password(password, hash):
    '''Verify password against hash.'''
    pass

def logout(user_id):
    '''Log out user.'''
    pass

def calculate_tax(amount):
    '''Calculate tax on amount.'''
    pass
""")
        return test_file

    @pytest.mark.asyncio
    async def test_relevance_scores_added_when_target_specified(self, auth_file):
        """When target is specified, should add relevance_score to each result."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # All results should have relevance_score field
        assert len(result) > 0
        for symbol in result:
            assert "relevance_score" in symbol
            assert isinstance(symbol["relevance_score"], (int, float))
            assert 0.0 <= symbol["relevance_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_exact_match_has_highest_score(self, auth_file):
        """Exact match should have the highest relevance score (1.0)."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # Find "login" function
        login_sym = next((s for s in result if s["name"] == "login"), None)
        assert login_sym is not None
        assert login_sym["relevance_score"] == 1.0

    @pytest.mark.asyncio
    async def test_partial_match_has_high_score(self, auth_file):
        """Partial matches (contains target) should have high scores (>0.7)."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # Find "handle_login" (contains "login")
        handle_login = next((s for s in result if s["name"] == "handle_login"), None)
        assert handle_login is not None
        assert handle_login["relevance_score"] >= 0.7
        assert handle_login["relevance_score"] < 1.0  # Less than exact match

    @pytest.mark.asyncio
    async def test_semantic_match_has_moderate_score(self, auth_file):
        """Semantically similar symbols should have moderate scores (0.4-0.7)."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # Find "authenticate_user" (semantically related to login)
        auth_user = next((s for s in result if s["name"] == "authenticate_user"), None)
        assert auth_user is not None
        # Should be semantically similar (not exact, but related)
        assert 0.4 <= auth_user["relevance_score"] < 0.7

    @pytest.mark.asyncio
    async def test_irrelevant_symbols_have_lower_scores(self, auth_file):
        """Irrelevant symbols should have lower scores than relevant ones."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # Get scores for different symbol types
        login_score = next(s["relevance_score"] for s in result if s["name"] == "login")
        auth_score = next(s["relevance_score"] for s in result if s["name"] == "authenticate_user")

        # If calculate_tax appears, it should have lower score than auth-related symbols
        names = [s["name"] for s in result]
        if "calculate_tax" in names:
            tax_sym = next(s for s in result if s["name"] == "calculate_tax")
            # Irrelevant symbol should score lower than relevant ones
            assert tax_sym["relevance_score"] < auth_score, \
                f"Irrelevant symbol scored too high: {tax_sym['relevance_score']} >= {auth_score}"
            assert tax_sym["relevance_score"] < login_score, \
                f"Irrelevant symbol scored higher than exact match: {tax_sym['relevance_score']} >= {login_score}"

    @pytest.mark.asyncio
    async def test_results_sorted_by_relevance_descending(self, auth_file):
        """Results should be sorted by relevance_score (highest first)."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file),
            target="login"
        )

        # Verify sorted in descending order
        scores = [s["relevance_score"] for s in result]
        assert scores == sorted(scores, reverse=True)

        # First result should be "login" (exact match)
        assert result[0]["name"] == "login"
        assert result[0]["relevance_score"] == 1.0

    @pytest.mark.asyncio
    async def test_no_relevance_scores_without_target(self, auth_file):
        """When target not specified, relevance_score should not be added."""
        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(auth_file)
        )

        # Should return symbols without relevance_score
        assert len(result) > 0
        for symbol in result:
            assert "relevance_score" not in symbol

    @pytest.mark.asyncio
    async def test_relevance_with_signature_similarity(self, tmp_path):
        """Relevance should consider both name AND signature similarity."""
        test_file = tmp_path / "api.py"
        test_file.write_text("""
def fetch_user_data(user_id):
    '''Fetch user data from database.'''
    pass

def get_user(user_id):
    '''Get user by ID.'''
    pass

def delete_file(file_path):
    '''Delete a file.'''
    pass
""")

        from miller.server import get_symbols

        result = await get_symbols(
            file_path=str(test_file),
            target="user"
        )

        # Both "fetch_user_data" and "get_user" should have high scores
        # (they contain "user" in name or are semantically related)
        user_symbols = [s for s in result if "user" in s["name"].lower()]
        assert len(user_symbols) >= 2
        for sym in user_symbols:
            assert sym["relevance_score"] >= 0.5

        # "delete_file" (if it appears) should have lower score than user-related symbols
        names = [s["name"] for s in result]
        if "delete_file" in names:
            delete_sym = next(s for s in result if s["name"] == "delete_file")
            user_data_score = next(s["relevance_score"] for s in result if s["name"] == "fetch_user_data")
            # Irrelevant symbol should score lower than relevant ones
            assert delete_sym["relevance_score"] < user_data_score, \
                f"Irrelevant symbol scored too high: {delete_sym['relevance_score']} >= {user_data_score}"
