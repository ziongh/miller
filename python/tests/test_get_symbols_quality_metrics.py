"""
Tests for get_symbols tool - Phase 2: Quality Metrics and ML Enhancements

Tests cover: semantic relevance scores, usage frequency indicators, and documentation quality metrics.
"""

import pytest
from pathlib import Path


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
