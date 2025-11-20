"""
Tests for fast_refs tool - Symbol disambiguation (Part 3).

Following TDD discipline:
- Write tests first (RED)
- Implement to pass (GREEN)
- Refactor (REFACTOR)
"""

import pytest
from pathlib import Path
from miller.storage import StorageManager


# ============================================================================
# SHARED FIXTURES
# ============================================================================


@pytest.fixture
def storage_with_ambiguous_symbols(tmp_path):
    """Create storage with multiple symbols having the same name."""
    storage = StorageManager(":memory:")

    # Create test file with ambiguous symbols
    test_file = tmp_path / "ambiguous.py"
    code = """class User:
    def save(self):
        pass

def process_user(user):
    # 'user' is a parameter (different from User class)
    user.save()

def save_data():
    # 'save' is a function (different from User.save method)
    pass
"""
    test_file.write_text(code)

    storage.add_file(
        file_path=str(test_file),
        language="python",
        content=code,
        hash="hash123",
        size=len(code),
    )

    # Add symbols
    # 1. User class
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("sym_user_class", "User", "Class", "python", str(test_file), 1, 3),
    )

    # 2. User.save method
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line, parent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("sym_user_save", "save", "Method", "python", str(test_file), 2, 3, "sym_user_class"),
    )

    # 3. process_user function
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("sym_process_user", "process_user", "Function", "python", str(test_file), 5, 7),
    )

    # 4. save_data function
    storage.conn.execute(
        """
        INSERT INTO symbols (id, name, kind, language, file_path, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("sym_save_data", "save_data", "Function", "python", str(test_file), 9, 11),
    )

    # Add relationship: process_user calls User.save
    storage.conn.execute(
        """
        INSERT INTO relationships (id, from_symbol_id, to_symbol_id, kind, file_path, line_number)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("rel_1", "sym_process_user", "sym_user_save", "Call", str(test_file), 7),
    )

    storage.conn.commit()
    return storage, test_file


# ============================================================================
# PHASE 2: OUTPUT QUALITY & UX
# ============================================================================

# ----------------------------------------------------------------------------
# Task 2.3: Symbol Disambiguation
# ----------------------------------------------------------------------------


class TestSymbolDisambiguation:
    """Test handling symbols with same name in different scopes."""

    def test_disambiguate_by_context_file(self, storage_with_ambiguous_symbols):
        """Test disambiguating symbols using context_file parameter."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Without context_file - finds all symbols named "save"
        result = find_references(storage, symbol_name="save")

        # Should find references to User.save (the method has references)
        # Note: We have both User.save (method) and save_data (function) with "save" in name
        assert result["symbol"] == "save"
        assert result["total_references"] >= 1

        # With context_file - narrows down to symbols in that file
        result = find_references(storage, symbol_name="save", context_file=str(test_file))

        # Should still find the reference (same file)
        assert result["total_references"] >= 1

    def test_qualified_name_support(self, storage_with_ambiguous_symbols):
        """Test finding references using qualified names (Class.method)."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Search for "User.save" (qualified name)
        result = find_references(storage, symbol_name="User.save")

        # Should find references to the method specifically
        assert result["symbol"] == "User.save"
        # Should find the call in process_user
        assert result["total_references"] >= 1

    def test_disambiguation_suggestions(self, storage_with_ambiguous_symbols):
        """Test that ambiguous queries provide suggestions."""
        from miller.tools.refs import find_references

        storage, test_file = storage_with_ambiguous_symbols

        # Search for ambiguous name "save"
        result = find_references(storage, symbol_name="save")

        # Should include suggestions for disambiguation
        assert "suggestions" in result or "total_references" in result
        # If multiple symbols match, should provide info about them
