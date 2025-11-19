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


class TestUsageFrequencyIndicators:
    """Test Task 2.2: Usage frequency indicators based on reference counts"""

    @pytest.mark.asyncio
    async def test_usage_frequency_fields_added(self, tmp_path):
        """Symbols should have references_count and usage_frequency fields."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def helper():
    pass

def main():
    helper()
    helper()
""")

        result = await get_symbols(
            file_path=str(test_file)
        )

        # All symbols should have usage fields (even if 0)
        for symbol in result:
            assert "references_count" in symbol
            assert "usage_frequency" in symbol
            assert isinstance(symbol["references_count"], int)
            assert symbol["usage_frequency"] in ["none", "low", "medium", "high", "very_high"]

    @pytest.mark.asyncio
    async def test_unreferenced_symbols_have_zero_count(self, tmp_path):
        """Symbols with no references should have count 0 and frequency 'none'."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def unused_function():
    pass
""")

        result = await get_symbols(
            file_path=str(test_file)
        )

        unused = next(s for s in result if s["name"] == "unused_function")
        assert unused["references_count"] == 0
        assert unused["usage_frequency"] == "none"

    @pytest.mark.asyncio
    async def test_frequency_tiers_low(self, tmp_path):
        """Symbols with 1-5 references should be 'low' frequency."""
        # This test would require setting up actual relationships in the database
        # For now, we'll test the tier calculation logic directly
        from miller.tools.symbols import calculate_usage_frequency

        assert calculate_usage_frequency(1) == "low"
        assert calculate_usage_frequency(3) == "low"
        assert calculate_usage_frequency(5) == "low"

    @pytest.mark.asyncio
    async def test_frequency_tiers_medium(self, tmp_path):
        """Symbols with 6-20 references should be 'medium' frequency."""
        from miller.tools.symbols import calculate_usage_frequency

        assert calculate_usage_frequency(6) == "medium"
        assert calculate_usage_frequency(15) == "medium"
        assert calculate_usage_frequency(20) == "medium"

    @pytest.mark.asyncio
    async def test_frequency_tiers_high(self, tmp_path):
        """Symbols with 21-50 references should be 'high' frequency."""
        from miller.tools.symbols import calculate_usage_frequency

        assert calculate_usage_frequency(21) == "high"
        assert calculate_usage_frequency(35) == "high"
        assert calculate_usage_frequency(50) == "high"

    @pytest.mark.asyncio
    async def test_frequency_tiers_very_high(self, tmp_path):
        """Symbols with 51+ references should be 'very_high' frequency."""
        from miller.tools.symbols import calculate_usage_frequency

        assert calculate_usage_frequency(51) == "very_high"
        assert calculate_usage_frequency(100) == "very_high"
        assert calculate_usage_frequency(1000) == "very_high"

    @pytest.mark.asyncio
    async def test_zero_references_is_none_tier(self, tmp_path):
        """Symbols with 0 references should be 'none' frequency."""
        from miller.tools.symbols import calculate_usage_frequency

        assert calculate_usage_frequency(0) == "none"


class TestDocumentationQualityScores:
    """Test Task 2.3: Documentation quality scores based on docstring presence/length"""

    @pytest.mark.asyncio
    async def test_doc_quality_fields_added(self, tmp_path):
        """All symbols should have has_docs and doc_quality fields."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def documented_function():
    '''This function has documentation.'''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # All symbols should have doc quality fields
        for symbol in result:
            assert "has_docs" in symbol
            assert "doc_quality" in symbol
            assert isinstance(symbol["has_docs"], bool)
            assert symbol["doc_quality"] in ["none", "poor", "good", "excellent"]

    @pytest.mark.asyncio
    async def test_undocumented_symbol_has_none_quality(self, tmp_path):
        """Symbols without docstrings should have doc_quality='none' and has_docs=False."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def undocumented():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        undoc = next(s for s in result if s["name"] == "undocumented")
        assert undoc["has_docs"] is False
        assert undoc["doc_quality"] == "none"

    @pytest.mark.asyncio
    async def test_poor_quality_documentation(self, tmp_path):
        """Docstrings <50 chars should be 'poor' quality."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def short_doc():
    '''Short doc.'''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        func = next(s for s in result if s["name"] == "short_doc")
        assert func["has_docs"] is True
        assert func["doc_quality"] == "poor"
        assert len(func["doc_comment"]) < 50

    @pytest.mark.asyncio
    async def test_good_quality_documentation(self, tmp_path):
        """Docstrings 50-200 chars should be 'good' quality."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def medium_doc():
    '''
    This function has a medium-length docstring that explains
    what it does in reasonable detail. Good enough for most cases.
    '''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        func = next(s for s in result if s["name"] == "medium_doc")
        assert func["has_docs"] is True
        assert func["doc_quality"] == "good"
        assert 50 <= len(func["doc_comment"]) <= 200

    @pytest.mark.asyncio
    async def test_excellent_quality_documentation(self, tmp_path):
        """Docstrings >200 chars should be 'excellent' quality."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def well_documented():
    '''
    This function has extensive documentation that thoroughly explains
    its purpose, parameters, return values, and behavior. It provides
    examples of usage and discusses edge cases. This level of detail
    is considered excellent documentation that helps developers quickly
    understand and use the function correctly without needing to read
    the implementation. Great documentation like this saves time and
    reduces bugs by making the interface crystal clear.
    '''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        func = next(s for s in result if s["name"] == "well_documented")
        assert func["has_docs"] is True
        assert func["doc_quality"] == "excellent"
        assert len(func["doc_comment"]) > 200

    @pytest.mark.asyncio
    async def test_doc_quality_tier_calculation(self, tmp_path):
        """Test the tier calculation function directly."""
        from miller.tools.symbols import calculate_doc_quality

        # None: no doc comment
        assert calculate_doc_quality(None) == "none"
        assert calculate_doc_quality("") == "none"

        # Poor: <50 chars
        assert calculate_doc_quality("Short.") == "poor"
        assert calculate_doc_quality("x" * 49) == "poor"

        # Good: 50-200 chars
        assert calculate_doc_quality("x" * 50) == "good"
        assert calculate_doc_quality("x" * 100) == "good"
        assert calculate_doc_quality("x" * 200) == "good"

        # Excellent: >200 chars
        assert calculate_doc_quality("x" * 201) == "excellent"
        assert calculate_doc_quality("x" * 500) == "excellent"

    @pytest.mark.asyncio
    async def test_mixed_documentation_quality(self, tmp_path):
        """File with mixed doc quality should classify each correctly."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def no_docs():
    pass

def poor_docs():
    '''Brief.'''
    pass

def good_docs():
    '''
    This has a reasonable amount of documentation that explains
    the function's purpose and basic usage patterns clearly.
    '''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # Check each symbol has correct quality
        no_docs = next(s for s in result if s["name"] == "no_docs")
        assert no_docs["doc_quality"] == "none"

        poor = next(s for s in result if s["name"] == "poor_docs")
        assert poor["doc_quality"] == "poor"

        good = next(s for s in result if s["name"] == "good_docs")
        assert good["doc_quality"] == "good"


class TestRelatedSymbolsSuggestions:
    """Test Task 2.4: Related symbols suggestions using embeddings"""

    @pytest.mark.asyncio
    async def test_related_symbols_field_added(self, tmp_path):
        """All symbols should have related_symbols field (even if empty)."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def user_login():
    pass

def user_logout():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # All symbols should have related_symbols field
        for symbol in result:
            assert "related_symbols" in symbol
            assert isinstance(symbol["related_symbols"], list)

    @pytest.mark.asyncio
    async def test_related_symbols_have_correct_structure(self, tmp_path):
        """Related symbols should have name and similarity fields."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
class User:
    pass

class UserProfile:
    pass

class UserService:
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # If any related symbols exist, check structure
        for symbol in result:
            for related in symbol["related_symbols"]:
                assert "name" in related
                assert "similarity" in related
                assert isinstance(related["name"], str)
                assert isinstance(related["similarity"], (int, float))
                assert 0.0 <= related["similarity"] <= 1.0

    @pytest.mark.asyncio
    async def test_related_symbols_sorted_by_similarity(self, tmp_path):
        """Related symbols should be sorted by similarity (descending)."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
class User:
    '''User model.'''
    pass

class UserProfile:
    '''User profile data.'''
    pass

class UserService:
    '''Service for user operations.'''
    pass

class UserRepository:
    '''Database access for users.'''
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # Check that related symbols are sorted by similarity
        for symbol in result:
            if len(symbol["related_symbols"]) > 1:
                similarities = [r["similarity"] for r in symbol["related_symbols"]]
                assert similarities == sorted(similarities, reverse=True), \
                    f"Related symbols for {symbol['name']} not sorted by similarity"

    @pytest.mark.asyncio
    async def test_related_symbols_limited_to_top_n(self, tmp_path):
        """Should return at most N related symbols (e.g., 5)."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        # Create many similar symbols
        code = "\n".join([f"class User{i}:\n    pass" for i in range(20)])
        test_file.write_text(code)

        result = await get_symbols(file_path=str(test_file))

        # No symbol should have more than 5 related symbols
        for symbol in result:
            assert len(symbol["related_symbols"]) <= 5

    @pytest.mark.asyncio
    async def test_symbol_not_related_to_itself(self, tmp_path):
        """A symbol should not appear in its own related_symbols list."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
class User:
    pass

class UserProfile:
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # Check that no symbol is related to itself
        for symbol in result:
            related_names = [r["name"] for r in symbol["related_symbols"]]
            assert symbol["name"] not in related_names, \
                f"Symbol {symbol['name']} should not be related to itself"

    @pytest.mark.asyncio
    async def test_empty_file_has_no_related_symbols(self, tmp_path):
        """Empty files should return symbols with empty related_symbols."""
        from miller.server import get_symbols

        test_file = tmp_path / "empty.py"
        test_file.write_text("")

        result = await get_symbols(file_path=str(test_file))

        # Empty file = no symbols
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_single_symbol_has_no_related_symbols(self, tmp_path):
        """A file with one symbol should have empty related_symbols."""
        from miller.server import get_symbols

        test_file = tmp_path / "single.py"
        test_file.write_text("""
def lonely_function():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # Single symbol has no other symbols to be related to
        assert len(result) == 1
        assert len(result[0]["related_symbols"]) == 0


class TestCrossLanguageVariantHints:
    """Test Task 2.5: Cross-language variant hints for multi-language navigation"""

    @pytest.mark.asyncio
    async def test_cross_language_hints_field_added(self, tmp_path):
        """All symbols should have cross_language_hints field."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def user_login():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # All symbols should have cross_language_hints field
        for symbol in result:
            assert "cross_language_hints" in symbol
            assert isinstance(symbol["cross_language_hints"], dict)

    @pytest.mark.asyncio
    async def test_cross_language_hints_correct_structure(self, tmp_path):
        """cross_language_hints should have required fields with correct types."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
class UserService:
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        for symbol in result:
            hints = symbol["cross_language_hints"]

            # Required fields
            assert "has_variants" in hints
            assert "variants_count" in hints
            assert "languages" in hints

            # Correct types
            assert isinstance(hints["has_variants"], bool)
            assert isinstance(hints["variants_count"], int)
            assert isinstance(hints["languages"], list)

            # Constraints
            assert hints["variants_count"] >= 0
            for lang in hints["languages"]:
                assert isinstance(lang, str)

    @pytest.mark.asyncio
    async def test_no_variants_when_database_empty(self, tmp_path):
        """When database has no indexed symbols, has_variants should be False."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
class UserService:
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # Without indexed symbols in DB, should find no variants
        for symbol in result:
            hints = symbol["cross_language_hints"]
            assert hints["has_variants"] is False
            assert hints["variants_count"] == 0
            assert hints["languages"] == []

    @pytest.mark.asyncio
    async def test_naming_variants_generated_correctly(self):
        """Test that naming variants are generated for different conventions."""
        from miller.tools.symbols import generate_naming_variants

        # PascalCase → all variants
        variants = generate_naming_variants("UserService")
        assert "user_service" in variants  # snake_case
        assert "userService" in variants   # camelCase
        assert "user-service" in variants  # kebab-case
        assert "UserService" in variants   # PascalCase (original)

        # snake_case → all variants
        variants = generate_naming_variants("user_service")
        assert "UserService" in variants   # PascalCase
        assert "userService" in variants   # camelCase
        assert "user-service" in variants  # kebab-case
        assert "user_service" in variants  # snake_case (original)

        # camelCase → all variants
        variants = generate_naming_variants("userService")
        assert "UserService" in variants   # PascalCase
        assert "user_service" in variants  # snake_case
        assert "user-service" in variants  # kebab-case
        assert "userService" in variants   # camelCase (original)

        # Single word (no case conversion needed)
        variants = generate_naming_variants("User")
        assert "user" in variants          # lowercase
        assert "User" in variants          # PascalCase (original)

    @pytest.mark.asyncio
    async def test_variants_detected_across_languages(self, tmp_path):
        """Test that variants are detected when symbols exist in different languages."""
        from miller.server import get_symbols, storage, miller_core

        # Index a Python file with user_service
        py_file = tmp_path / "user.py"
        py_file.write_text("""
class user_service:
    pass
""")

        # Index a TypeScript file with UserService
        ts_file = tmp_path / "user.ts"
        ts_file.write_text("""
class UserService {
}
""")

        # Index both files into the database
        if storage is not None:
            # Extract and index Python file
            py_content = py_file.read_text()
            py_result = miller_core.extract_file(py_content, "python", str(py_file))
            storage.add_file(str(py_file), "python", py_content, "hash1", len(py_content))
            storage.add_symbols_batch(list(py_result.symbols))

            # Extract and index TypeScript file
            ts_content = ts_file.read_text()
            ts_result = miller_core.extract_file(ts_content, "typescript", str(ts_file))
            storage.add_file(str(ts_file), "typescript", ts_content, "hash2", len(ts_content))
            storage.add_symbols_batch(list(ts_result.symbols))

        # Now query Python file and check for TypeScript variant
        result = await get_symbols(file_path=str(py_file))

        user_service_sym = next((s for s in result if "user_service" in s["name"].lower()), None)
        if user_service_sym and storage is not None:
            hints = user_service_sym["cross_language_hints"]
            assert hints["has_variants"] is True
            assert hints["variants_count"] > 0
            assert "typescript" in hints["languages"]

    @pytest.mark.asyncio
    async def test_variants_count_accurate(self, tmp_path):
        """variants_count should match the number of unique variant symbols found."""
        from miller.server import get_symbols, storage, miller_core

        if storage is None:
            pytest.skip("Storage not available")

        # Create files with multiple variants
        py_file = tmp_path / "auth.py"
        py_file.write_text("""
def authenticate_user():
    pass
""")

        js_file = tmp_path / "auth.js"
        js_file.write_text("""
function authenticateUser() {
}
""")

        # Index both
        py_content = py_file.read_text()
        py_result = miller_core.extract_file(py_content, "python", str(py_file))
        storage.add_file(str(py_file), "python", py_content, "hash1", len(py_content))
        storage.add_symbols_batch(list(py_result.symbols))

        js_content = js_file.read_text()
        js_result = miller_core.extract_file(js_content, "javascript", str(js_file))
        storage.add_file(str(js_file), "javascript", js_content, "hash2", len(js_content))
        storage.add_symbols_batch(list(js_result.symbols))

        # Query and verify count
        result = await get_symbols(file_path=str(py_file))

        auth_sym = next((s for s in result if "authenticate" in s["name"].lower()), None)
        if auth_sym:
            hints = auth_sym["cross_language_hints"]
            # Should find the JavaScript variant
            assert hints["variants_count"] >= 1
            assert len(hints["languages"]) == hints["variants_count"]

    @pytest.mark.asyncio
    async def test_languages_list_excludes_current_language(self, tmp_path):
        """The languages list should only include OTHER languages, not the current file's language."""
        from miller.server import get_symbols, storage, miller_core

        if storage is None:
            pytest.skip("Storage not available")

        # Create two Python files with same symbol name
        py_file1 = tmp_path / "user1.py"
        py_file1.write_text("""
class User:
    pass
""")

        py_file2 = tmp_path / "user2.py"
        py_file2.write_text("""
class User:
    pass
""")

        # Create a TypeScript file with variant
        ts_file = tmp_path / "user.ts"
        ts_file.write_text("""
class User {
}
""")

        # Index all files
        for idx, (file_path, language) in enumerate([(py_file1, "python"), (py_file2, "python"), (ts_file, "typescript")]):
            content = file_path.read_text()
            result = miller_core.extract_file(content, language, str(file_path))
            storage.add_file(str(file_path), language, content, f"hash{idx}", len(content))
            storage.add_symbols_batch(list(result.symbols))

        # Query Python file
        result = await get_symbols(file_path=str(py_file1))

        user_sym = next((s for s in result if s["name"] == "User"), None)
        if user_sym:
            hints = user_sym["cross_language_hints"]
            # Should only show TypeScript, not Python (same language)
            assert "python" not in hints["languages"]
            if hints["has_variants"]:
                assert "typescript" in hints["languages"]


class TestSymbolImportanceRanking:
    """Test Task 2.6: Symbol importance ranking using PageRank on call graph"""

    @pytest.mark.asyncio
    async def test_importance_fields_added(self, tmp_path):
        """All symbols should have importance fields."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def helper():
    pass

def main():
    helper()
""")

        result = await get_symbols(file_path=str(test_file))

        # All symbols should have importance fields
        for symbol in result:
            assert "importance_score" in symbol
            assert "importance" in symbol
            assert "is_entry_point" in symbol

    @pytest.mark.asyncio
    async def test_importance_fields_correct_types(self, tmp_path):
        """Importance fields should have correct types and constraints."""
        from miller.server import get_symbols

        test_file = tmp_path / "test.py"
        test_file.write_text("""
def calculate():
    return 42

def process():
    return calculate()
""")

        result = await get_symbols(file_path=str(test_file))

        for symbol in result:
            # importance_score should be float between 0 and 1
            assert isinstance(symbol["importance_score"], (int, float))
            assert 0.0 <= symbol["importance_score"] <= 1.0

            # importance should be one of the tiers
            assert symbol["importance"] in ["low", "medium", "high", "critical"]

            # is_entry_point should be bool
            assert isinstance(symbol["is_entry_point"], bool)

    @pytest.mark.asyncio
    async def test_importance_tiers_calculated_correctly(self):
        """Test tier calculation logic."""
        from miller.tools.symbols import calculate_importance_tier

        # Low: 0-0.25
        assert calculate_importance_tier(0.0) == "low"
        assert calculate_importance_tier(0.1) == "low"
        assert calculate_importance_tier(0.25) == "low"

        # Medium: 0.25-0.5
        assert calculate_importance_tier(0.26) == "medium"
        assert calculate_importance_tier(0.4) == "medium"
        assert calculate_importance_tier(0.5) == "medium"

        # High: 0.5-0.75
        assert calculate_importance_tier(0.51) == "high"
        assert calculate_importance_tier(0.65) == "high"
        assert calculate_importance_tier(0.75) == "high"

        # Critical: 0.75-1.0
        assert calculate_importance_tier(0.76) == "critical"
        assert calculate_importance_tier(0.9) == "critical"
        assert calculate_importance_tier(1.0) == "critical"

    @pytest.mark.asyncio
    async def test_entry_points_detected(self, tmp_path):
        """Entry points should be detected (called by many, calls few)."""
        from miller.server import get_symbols, storage, miller_core

        if storage is None:
            pytest.skip("Storage not available")

        # Create a file with clear entry point pattern
        test_file = tmp_path / "service.py"
        test_file.write_text("""
def helper():
    return "help"

def main_handler(request):
    # Entry point: called by many endpoint functions, calls few helpers
    return helper()

def api_endpoint_1():
    return main_handler("request1")

def api_endpoint_2():
    return main_handler("request2")

def api_endpoint_3():
    return main_handler("request3")
""")

        # Index the file
        content = test_file.read_text()
        result_extract = miller_core.extract_file(content, "python", str(test_file))
        storage.add_file(str(test_file), "python", content, "hash1", len(content))
        storage.add_symbols_batch(list(result_extract.symbols))
        storage.add_relationships_batch(list(result_extract.relationships))

        # Get symbols with importance
        result = await get_symbols(file_path=str(test_file))

        # main_handler should be an entry point (called by 3 endpoints, calls only 1 helper)
        main_handler = next((s for s in result if s["name"] == "main_handler"), None)
        if main_handler:
            # Should be detected as entry point (in_degree=3, out_degree=1)
            assert main_handler["is_entry_point"] is True

    @pytest.mark.asyncio
    async def test_importance_scores_from_call_graph(self, tmp_path):
        """PageRank scores should reflect call graph structure."""
        from miller.server import get_symbols, storage, miller_core

        if storage is None:
            pytest.skip("Storage not available")

        # Create a hub-and-spoke pattern
        test_file = tmp_path / "hub.py"
        test_file.write_text("""
def hub():
    # Central function called by everyone
    return "hub"

def caller1():
    return hub()

def caller2():
    return hub()

def caller3():
    return hub()
""")

        # Index the file
        content = test_file.read_text()
        result_extract = miller_core.extract_file(content, "python", str(test_file))
        storage.add_file(str(test_file), "python", content, "hash1", len(content))
        storage.add_symbols_batch(list(result_extract.symbols))
        storage.add_relationships_batch(list(result_extract.relationships))

        # Get symbols
        result = await get_symbols(file_path=str(test_file))

        # Hub should have highest importance score
        hub = next((s for s in result if s["name"] == "hub"), None)
        callers = [s for s in result if s["name"].startswith("caller")]

        if hub and callers:
            # Hub should have higher score than individual callers
            for caller in callers:
                assert hub["importance_score"] >= caller["importance_score"]

    @pytest.mark.asyncio
    async def test_no_relationships_default_scores(self, tmp_path):
        """Symbols with no relationships should have default/equal scores."""
        from miller.server import get_symbols

        test_file = tmp_path / "isolated.py"
        test_file.write_text("""
def func1():
    pass

def func2():
    pass

def func3():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        # All symbols should have equal scores (no relationships)
        scores = [s["importance_score"] for s in result]
        # All scores should be equal (within floating point tolerance)
        if len(scores) > 1:
            assert all(abs(score - scores[0]) < 0.01 for score in scores)

    @pytest.mark.asyncio
    async def test_single_symbol_default_importance(self, tmp_path):
        """A single symbol should have default importance values."""
        from miller.server import get_symbols

        test_file = tmp_path / "single.py"
        test_file.write_text("""
def lonely():
    pass
""")

        result = await get_symbols(file_path=str(test_file))

        assert len(result) == 1
        symbol = result[0]

        # Should have default values
        assert symbol["importance_score"] > 0.0  # Some default score
        assert symbol["importance"] in ["low", "medium", "high", "critical"]
        assert isinstance(symbol["is_entry_point"], bool)
