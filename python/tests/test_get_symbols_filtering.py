"""
Tests for get_symbols tool - Filtering and Related Symbols Features

Tests cover: target parameter filtering and related symbols suggestions.
"""

import pytest
from pathlib import Path


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
