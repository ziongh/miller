"""
Tests for get_symbols tool - Phase 2: Advanced Features

Tests cover: cross-language variant hints and symbol importance ranking.
"""

import pytest
from pathlib import Path


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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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
        result = await get_symbols(file_path=str(py_file), output_format="json")

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
        result = await get_symbols(file_path=str(py_file), output_format="json")

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
        result = await get_symbols(file_path=str(py_file1), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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
        result = await get_symbols(file_path=str(test_file), output_format="json")

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
        result = await get_symbols(file_path=str(test_file), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

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

        result = await get_symbols(file_path=str(test_file), output_format="json")

        assert len(result) == 1
        symbol = result[0]

        # Should have default values
        assert symbol["importance_score"] > 0.0  # Some default score
        assert symbol["importance"] in ["low", "medium", "high", "critical"]
        assert isinstance(symbol["is_entry_point"], bool)
